"""VAE 판별력의 출처 분해 — 무엇이 부정을 가르는가.

사용: uv run python tools/scripts/diag_vae_separation_source.py <fraud_dir>

배경(2026-07-28): overlay 재설계 후 문서 AUROC 가 1.0000 → 0.9059 로 내려왔다.
1.0 이 아니게 된 것은 결측·조합 아티팩트가 사라졌다는 뜻이지만, 남은 0.906 이
무엇에서 오는지는 따로 가려야 인용 가능 여부가 정해진다.

가르는 축 4개:
  A 계정계  — 부정이 정상에 없는 계정 조합을 쓰는 데서 오는 것. 부정의 실체이므로 인용 가능.
  B 룰출력  — PHASE1 룰 발화가 VAE 입력에 들어와 있는 데서 오는 것.
              3-surface 비병합 원칙(PHASE1/PHASE2 독립) 위반이므로 발견 시 제거 대상.
  C 도너계  — 승인·시점·거래처 등 도너에서 물려받는 칸. 재설계로 정상 분포를 따르므로
              여기서 큰 분리가 나오면 재설계가 덜 된 것이다.
  D 상수    — 전 행 동일값. 죽은 입력이므로 제외 후보.

측정: 입력 피처별 단변량 AUC(문서 단위, 행 최대값 집계). 0.5 가 정보 없음.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 축 분류 — 접두어 매칭. 어느 쪽도 아니면 C(도너계)로 본다.
ACCOUNT_PREFIXES = (
    "gl_account",
    "account_code",
    "semantic_account_subtype",
    "debit_account_subtype",
    "credit_account_subtype",
    "is_suspense_account",
    "is_cleared",
    "is_revenue_account",
    "line_text",
    "amount",
    "first_digit",
    "is_round_number",
)
RULE_PREFIXES = (
    "review_rules",
    "flagged_rules",
    "batch_combo_reasons",
    "work_scope_combo_reasons",
    "intercompany_exception_reasons",
    "rule_",
    "near_threshold",
    "approval_excess",
    "approval_limit",
    "approval_contract",
    "exceeds_threshold",
    "description_",
    "is_manual_je",
    "is_period_end",
    "is_weekend",
    "is_after_hours",
    "is_holiday",
    "fiscal_period_mismatch",
    "employee_",
    "master_",
    "document_flow_",
    "ic_",
)


def axis_of(column: str) -> str:
    if column.startswith(ACCOUNT_PREFIXES):
        return "A 계정계"
    if column.startswith(RULE_PREFIXES):
        return "B 룰·피처출력"
    return "C 도너계"


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    pos = labels.astype(bool)
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: diag_vae_separation_source.py <fraud_dir>")
        return 2
    fraud_dir = Path(sys.argv[1])

    from config.settings import get_settings
    from src.pipeline import AuditPipeline
    from src.services.phase2_training_service import prepare_phase2_feature_inputs

    res = AuditPipeline(skip_db=True).run(str(fraud_dir / "journal_entries.csv"))
    # Why: 탐지 전 스냅샷을 쓴다 — res.data 는 aggregate 가 되쓴 PHASE1 산출물을 포함한다.
    featured = res.featured_data if res.featured_data is not None else res.data
    cleaned, _groups, _payload = prepare_phase2_feature_inputs(featured, settings=get_settings())
    doc_ids = featured["document_id"].astype(str).to_numpy()

    prov = pd.read_csv(fraud_dir / "labels/phase2_scheme_provenance.csv", dtype=str)
    fraud_docs = set(prov["document_id"])

    frame = pd.DataFrame(cleaned)
    frame["_doc"] = doc_ids
    # 문서 단위 집계 — VAE 채점과 같은 방식(행 최대)
    grouped = frame.groupby("_doc").max(numeric_only=True)
    labels = np.array([1 if d in fraud_docs else 0 for d in grouped.index])
    print(f"입력 피처 {frame.shape[1] - 1}개 · 문서 {len(grouped):,} (부정 {int(labels.sum())})\n")

    rows = []
    constant = []
    for column in grouped.columns:
        # nullable boolean/Int64 는 fillna(0.0) 이 dtype 오류를 낸다 — numpy 변환 시 결측을 채운다.
        values = pd.to_numeric(grouped[column], errors="coerce").to_numpy(
            dtype="float64", na_value=0.0
        )
        if np.nanstd(values) == 0:
            constant.append(column)
            continue
        a = auc(labels, values)
        rows.append((column, axis_of(column), a, abs(a - 0.5)))

    table = pd.DataFrame(rows, columns=["feature", "axis", "auc", "sep"]).sort_values(
        "sep", ascending=False
    )
    print(f"{'피처':<44}{'축':<14}{'단변량AUC':>10}")
    for _, r in table.head(25).iterrows():
        print(f"{r['feature']:<44}{r['axis']:<14}{r['auc']:>10.4f}")

    print("\n=== 축별 요약 ===")
    summary = (
        table.groupby("axis")
        .agg(피처수=("feature", "size"), 최대분리=("sep", "max"), 평균분리=("sep", "mean"))
        .sort_values("최대분리", ascending=False)
    )
    summary["최대AUC"] = summary["최대분리"].apply(lambda s: 0.5 + s)
    print(summary.round(4).to_string())

    print(f"\n=== D 상수(죽은 입력) {len(constant)}개 ===")
    print("  " + ", ".join(constant) if constant else "  없음")

    strong = table[table["sep"] >= 0.15]
    print(f"\n=== 단변량 AUC 0.65 이상 {len(strong)}개 ===")
    if len(strong):
        print(strong.groupby("axis").size().to_string())
    else:
        print("  없음 — 단일 피처로는 갈리지 않는다(분리가 조합에서 온다는 뜻)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
