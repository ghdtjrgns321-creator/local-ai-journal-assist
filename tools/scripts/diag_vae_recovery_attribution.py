"""회수 건의 기여 피처 분해 — VAE 가 무엇을 보고 올렸는가.

사용:
  uv run python tools/scripts/diag_vae_recovery_attribution.py <fraud_dataset_dir> \
      --model-cache reports/s5_fraud_overlay/_model_cache_r9allow2.pkl --tag r9allow2

배경(2026-07-29): 판별력 있는 룰이 놓친 부정 124건 중 VAE 가 27건을 상위 1%로 올렸는데,
**27건 전부가 가공매출(FS01·FS05)** 이었다. 유령급여(FS14) 27건·FS08 11건은 한 건도
회수되지 않았다. 4벌 내내 예외가 없다. 왜 한 계열만 잡히는지를 확인한다.

이 질문은 "부정의 실체를 잡았나, 생성기 흔적을 잡았나"와 같은 자리다.
  계정·거래처·금액 조합이 위에 오면  → 실제 원장에서도 성립하는 신호
  배선 칸(전기시각·요일 등)이 위에 오면 → 합성 데이터에만 있는 봉제선 의심

**SHAP 을 쓰지 않는다.** VAE 점수는 정의상 칸별 재구성 제곱오차의 합이라 정확한 분해가
이미 존재한다(`_score_vae_per_feature`). SHAP 은 그 정확한 값을 근사로 바꾸고 계산만
수십 배 비싸진다.

산출: reports/s5_fraud_overlay/vae_recovery_attribution_*.json
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports/s5_fraud_overlay"
BASELINE_DOCS = 400
BASELINE_SEED = 20260729


def _load_scheme_map(dataset_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    path = dataset_dir / "labels" / "phase2_scheme_provenance.csv"
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            mapping[row["document_id"]] = row["scheme_id"]
    return mapping


def _recovered_docs(dataset_dir: Path, tag: str) -> tuple[set[str], set[str]]:
    """판별력 기준 미표면 문서와, 그중 VAE 상위 1% 진입분."""
    builder_path = OUT / f"builder_performance_{dataset_dir.name}.json"
    top1_path = OUT / f"vae_top1pct_docs_{dataset_dir.name}_{tag}.json"
    builder = json.loads(builder_path.read_text(encoding="utf-8"))
    missed = set(builder["surface_coverage_informative"]["missed_docs"])
    top1 = set(json.loads(top1_path.read_text(encoding="utf-8")))
    return missed, missed & top1


def _feature_axis(name: str) -> str:
    """전처리 후 피처명을 감사가 읽는 축으로 되돌린다.

    이름 모양: `prepared__<원본칸>__<변환·범주>`. 앞의 `prepared__` 는 ColumnTransformer
    블록 이름이라 떼고 봐야 원본 칸이 나온다(2026-07-29: 이걸 안 떼서 전 칸이 "기타"로
    떨어졌다).
    """
    text = str(name)
    if text.startswith("prepared__"):
        text = text[len("prepared__") :]
    source = text.split("__")[0]
    axes = {
        "계정": (
            "gl_account",
            "semantic_account_subtype",
            "debit_account_subtype",
            "credit_account_subtype",
        ),
        "금액": (
            "debit_amount",
            "credit_amount",
            "local_amount",
            "invoice_amount",
            "supply_amount",
            "tax_amount",
            "p2_amount_trailing_zeros",
            "p2_amount_first_digit",
            "p2_approver_limit_amount",
        ),
        "거래처·조직": (
            "trading_partner",
            "auxiliary_account_number",
            "auxiliary_account_label",
            "cost_center",
            "profit_center",
            "counterparty_type",
        ),
        "사람·승인": ("created_by", "approved_by", "user_persona", "p2_approver_in_master"),
        "증빙·적요": (
            "has_attachment",
            "supporting_doc_type",
            "line_text",
            "header_text",
            "line_text_family",
        ),
        "시점": (
            "p2_posting_dow",
            "p2_posting_hour",
            "p2_posting_day_of_month",
            "p2_is_holiday",
            "p2_days_posting_minus_document",
            "p2_days_approval_minus_posting",
            "p2_days_delivery_minus_document",
            "fiscal_year",
            "fiscal_period",
        ),
        "전표 속성": (
            "document_type",
            "business_process",
            "event_type",
            "source",
            "tax_treatment",
            "tax_code",
            "is_intercompany",
            "is_suspense_account",
            "is_cleared",
            "company_code",
            "currency",
            "ledger",
            "exchange_rate",
        ),
    }
    for axis, columns in axes.items():
        if source in columns:
            return axis
    return "기타"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir")
    parser.add_argument("--model-cache", required=True)
    parser.add_argument("--tag", default="r9allow2")
    args = parser.parse_args()

    import pandas as pd

    from config.settings import get_settings
    from src.services.phase2_training_service import prepare_phase2_feature_inputs

    dataset_dir = Path(args.dataset_dir)

    missed, recovered = _recovered_docs(dataset_dir, args.tag)
    scheme = _load_scheme_map(dataset_dir)
    print(f"=== {dataset_dir.name} ===")
    print(f"판별력 기준 미표면 {len(missed)}건 · VAE 회수 {len(recovered)}건", flush=True)
    if not recovered:
        print("회수 0건 — 분해할 대상이 없다")
        return 0

    with Path(args.model_cache).open("rb") as fh:
        det = pickle.load(fh)["detector"]

    # Why: 이 분석은 1,300행 남짓만 필요한데 35만 행 파이프라인을 통째로 돌릴 이유가 없다.
    #      PHASE2 입력은 허용 목록 기반이라 원본 CSV 에서 바로 만들어진다. 파이프라인을
    #      빼면 실행이 분 단위에서 초 단위로 내려간다.
    frame = pd.read_csv(dataset_dir / "journal_entries.csv", low_memory=False)
    frame.attrs["source_path"] = str(dataset_dir / "journal_entries.csv")
    doc_ids = frame["document_id"].astype(str)
    # Why: 전 행(35만)의 피처별 오차 행렬은 1GB 를 넘는다. 회수 문서와 정상 대조군만 잰다.
    normal_docs = sorted(set(doc_ids) - set(scheme))
    rng = np.random.default_rng(BASELINE_SEED)
    baseline_docs = set(
        rng.choice(normal_docs, size=min(BASELINE_DOCS, len(normal_docs)), replace=False)
    )
    wanted = recovered | baseline_docs
    subset = frame.loc[doc_ids.isin(wanted)].copy()
    subset_docs = subset["document_id"].astype(str)
    del frame
    gc.collect()

    # Why: 매트릭스 빌더는 `p2_*` 파생 12칸을 기대한다. 원본 칸만 넘기면 reindex 에서
    #      NaN 이 되어 전부 `__RARE__`/0 으로 채워지고, 시점 축이 통째로 죽은 채 계산된다
    #      (2026-07-29: 이 버그로 시점 축 -10%p 라는 잘못된 결과를 냈다. 절대 오차 1위가
    #      `p2_posting_dow____RARE__` 인데 배율이 정확히 1.0 이었던 것이 그 신호였다).
    prepared, _groups, _payload = prepare_phase2_feature_inputs(subset, settings=get_settings())
    per_feature, names = det._score_vae_per_feature(det._prepare_detection_features(prepared))
    axes = [_feature_axis(n) for n in names]
    print(f"분해 대상 {len(subset)}행 × {per_feature.shape[1]}칸", flush=True)

    recovered_mask = subset_docs.isin(recovered).to_numpy()
    baseline_mask = ~recovered_mask

    def _axis_share(mask: np.ndarray) -> dict[str, float]:
        block = per_feature[mask]
        totals: dict[str, float] = {}
        for axis in sorted(set(axes)):
            columns = [i for i, a in enumerate(axes) if a == axis]
            totals[axis] = float(block[:, columns].sum())
        grand = sum(totals.values()) or 1.0
        return {k: round(v / grand * 100, 2) for k, v in totals.items()}

    recovered_share = _axis_share(recovered_mask)
    baseline_share = _axis_share(baseline_mask)

    top_features = []
    rec_mean = per_feature[recovered_mask].mean(axis=0)
    base_mean = per_feature[baseline_mask].mean(axis=0)
    lift = np.divide(rec_mean, np.maximum(base_mean, 1e-12))
    # Why: 절대 오차로 줄 세우면 모두에게 어려운 칸(희소 범주 등)이 위로 온다 — 배율 1.0.
    #      회수건과 정상 대조군의 **차이**가 "이 건이 왜 올라왔나"에 답한다.
    delta = rec_mean - base_mean
    order = np.argsort(-delta)[:20]
    for i in order:
        top_features.append(
            {
                "feature": names[i],
                "axis": axes[i],
                "recovered_mean_error": round(float(rec_mean[i]), 5),
                "baseline_mean_error": round(float(base_mean[i]), 5),
                "delta": round(float(delta[i]), 5),
                "lift": round(float(lift[i]), 2),
            }
        )

    print("\n=== 축별 재구성 오차 점유율 (%) ===")
    print(f"{'축':<12}{'회수건':>9}{'정상대조':>10}{'차이':>9}")
    for axis in sorted(recovered_share, key=lambda a: -recovered_share[a]):
        r, b = recovered_share[axis], baseline_share.get(axis, 0.0)
        print(f"{axis:<12}{r:>8.1f}%{b:>9.1f}%{r - b:>+8.1f}")

    print("\n=== 회수건 상위 기여 칸 ===")
    print(f"{'칸':<40}{'축':<12}{'회수':>8}{'정상':>8}{'차이':>8}{'배율':>7}")
    for row in top_features[:14]:
        name = row["feature"].replace("prepared__", "")[:39]
        print(
            f"{name:<40}{row['axis']:<12}"
            f"{row['recovered_mean_error']:>8.3f}{row['baseline_mean_error']:>8.3f}"
            f"{row['delta']:>8.3f}{row['lift']:>7.1f}"
        )

    payload = {
        "dataset": dataset_dir.name,
        "missed_docs": len(missed),
        "recovered_docs": len(recovered),
        "recovered_schemes": {
            s: sum(1 for d in recovered if scheme.get(d) == s)
            for s in sorted({scheme.get(d, "?") for d in recovered})
        },
        "rows_analyzed": int(len(subset)),
        "baseline_docs": len(baseline_docs),
        "axis_share_recovered_pct": recovered_share,
        "axis_share_baseline_pct": baseline_share,
        "top_features": top_features,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"vae_recovery_attribution_{dataset_dir.name}_{args.tag}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n산출: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
