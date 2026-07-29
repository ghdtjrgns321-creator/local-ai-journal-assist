"""차단 근거 전수 재검 — deny 목록이 지금 데이터에서도 유효한가.

사용: uv run python tools/scripts/diag_deny_basis_recheck.py <fraud_dataset_dir>

배경(2026-07-29): PHASE2 leakage deny 목록 58칸의 근거는 DataSynth **v6/v7**
(2026-05) 시점의 치트루트 감사다. 그 뒤 생성기를 도너 복제 구조로 전면 재설계했고
(r9, 2026-07-27) 결측·조합 누출을 제거했다. **차단 근거는 한 번도 재측정하지 않았다.**

실측 예: `debit_amount` 단독 AUROC 가 v6 에서 0.917 이었는데 r9 에서 0.72 다.
0.95(HARD)·0.80(SOFT) 어느 기준에도 못 미친다 — 근거가 사라졌는데 차단만 남아 있다.
그 결과 VAE 는 원장의 핵심인 차대변 금액을 못 본다.

분모는 손으로 만들지 않는다. 파이프라인이 실제로 내놓는 전 컬럼을 population 으로
박제하고, 컬럼마다 한 줄씩 흔적을 남긴다(census 스킬).

측정:
  수치형·불리언  단독 AUROC (행 단위 · 문서 단위 합계). 방향 무관이라 max(a, 1-a).
  범주형         값 하나로 부정을 집어내는가 — 최고 단일 값의 정밀도·재현율.
                 (verify_overlay_column_contract 의 C2 축과 같은 기준)

판정 (v6 감사가 쓴 기준선 그대로):
  HARD   AUROC ≥ 0.95  또는 정밀도 ≥ 0.99 & 재현율 ≥ 0.05 → 차단 유지
  SOFT   AUROC 0.80~0.95                                   → 재검토
  근거소멸 그 아래                                          → 차단 해제 후보
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports/s5_fraud_overlay"

HARD_AUROC = 0.95
SOFT_AUROC = 0.80
HARD_PRECISION = 0.99
HARD_RECALL = 0.05

# 재측정으로 풀 수 없는 차단 — 데이터가 바뀌어도 유지된다.
#   label      DataSynth 가 적어둔 정답. 실 ERP 에 없다.
#   meta       조작 방식 메모. 실 ERP 에 없다.
#   identifier 전표·배치 번호. 값이 거의 다 달라 모델엔 난수.
#   privacy    비식별화 정책상 ML 입력 금지.
#   datetime   원본 날짜는 파생 피처로만 쓴다(크기 비교가 무의미).
STRUCTURAL_REASONS = {
    "leakage_label",
    "identifier",
    "datetime_raw",
    "phase_output_deny",
    "phase_output_prefix",
}
STRUCTURAL_COLUMNS = {
    "document_id",
    "reference",
    "ip_address",
    "is_synthetic",
    "is_mutated",
    "detection_surface_hints",
    "semantic_scenario_id",
    "mutation_base_event_type",
    "mutation_type",
    "mutation_mutated_field",
    "mutation_original_value",
    "mutation_mutated_value",
    "mutation_reason",
}


def _auroc(values: pd.Series, labels: np.ndarray) -> float:
    """방향 무관 단독 AUROC. 어느 쪽으로 갈리든 지름길이므로 max(a, 1-a)."""
    mask = values.notna().to_numpy()
    if mask.sum() == 0:
        return float("nan")
    numeric = pd.to_numeric(values[mask], errors="coerce")
    keep = numeric.notna().to_numpy()
    y = labels[mask][keep]
    if y.sum() == 0 or (~y).sum() == 0:
        return float("nan")
    ranks = numeric[keep].rank().to_numpy()
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    area = (ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(max(area, 1 - area))


def _best_category(values: pd.Series, labels: np.ndarray) -> tuple[float, float, str]:
    """부정을 가장 잘 집어내는 단일 값의 (정밀도, 재현율, 값)."""
    frame = pd.DataFrame({"v": values.astype("string").fillna("__MISSING__"), "y": labels})
    grouped = frame.groupby("v")["y"].agg(["sum", "size"])
    total_pos = int(labels.sum())
    if total_pos == 0 or grouped.empty:
        return 0.0, 0.0, ""
    grouped["precision"] = grouped["sum"] / grouped["size"]
    grouped["recall"] = grouped["sum"] / total_pos
    grouped["score"] = grouped["precision"] * grouped["recall"]
    top = grouped.sort_values("score", ascending=False).iloc[0]
    return (
        float(top["precision"]),
        float(top["recall"]),
        str(grouped.sort_values("score", ascending=False).index[0]),
    )


def _verdict(kind: str, auroc: float, precision: float, recall: float) -> str:
    if kind == "numeric":
        if not np.isfinite(auroc):
            return "측정불가"
        if auroc >= HARD_AUROC:
            return "HARD"
        if auroc >= SOFT_AUROC:
            return "SOFT"
        return "근거소멸"
    if precision >= HARD_PRECISION and recall >= HARD_RECALL:
        return "HARD"
    if precision >= HARD_PRECISION or recall >= 0.5:
        return "SOFT"
    return "근거소멸"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir")
    args = parser.parse_args()

    from config.settings import get_settings
    from src.eda.profiler import profile_dataframe
    from src.pipeline import AuditPipeline
    from src.preprocessing.constants import (
        LEAKAGE_DENY_COLUMNS_MEASURED,
        LEAKAGE_DENY_COLUMNS_PHASE1_OUTPUT,
        LEAKAGE_DENY_COLUMNS_STRUCTURAL,
    )
    from src.preprocessing.phase2_features import PHASE2_SOURCE_COLUMNS
    from src.preprocessing.phase2_plan import build_phase2_preprocessing_plan

    origin = {}
    for name, columns in (
        ("STRUCTURAL", LEAKAGE_DENY_COLUMNS_STRUCTURAL),
        ("MEASURED", LEAKAGE_DENY_COLUMNS_MEASURED),
        ("PHASE1", LEAKAGE_DENY_COLUMNS_PHASE1_OUTPUT),
    ):
        for column in columns:
            origin[column] = name
    # 2026-07-29: 허용 목록이 1차 관문이 된 뒤로는 "차단됐다"보다 "허용 목록에 없다"가
    #             더 흔한 미채택 사유다. 둘을 구분해서 표시한다.
    allow_list = set(PHASE2_SOURCE_COLUMNS)

    dataset_dir = Path(args.dataset_dir)
    settings = get_settings()

    result = AuditPipeline(skip_db=True).run(str(dataset_dir / "journal_entries.csv"))
    featured = result.featured_data if result.featured_data is not None else result.data

    provenance = pd.read_csv(dataset_dir / "labels" / "phase2_scheme_provenance.csv", dtype=str)
    fraud_docs = set(provenance["document_id"])
    doc_ids = featured["document_id"].astype(str)
    row_labels = doc_ids.isin(fraud_docs).to_numpy()

    plan = build_phase2_preprocessing_plan(
        profile_dataframe(
            featured,
            max_rows=getattr(settings, "phase2_profile_max_rows", None),
            random_seed=int(getattr(settings, "phase2_random_seed", 42)),
        ),
        high_card_threshold=int(getattr(settings, "heuristic_high_cardinality_threshold", 50)),
    )
    decisions = {d["column"]: d for d in plan.to_dict()["decisions"]}

    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"deny_basis_recheck_{dataset_dir.name}"
    population_path = OUT / f"{stem}_population.txt"
    done_path = OUT / f"{stem}_done.txt"
    population_path.write_text(
        "\n".join(str(column) for column in featured.columns) + "\n", encoding="utf-8"
    )

    rows: list[dict] = []
    done: list[str] = []
    for column in featured.columns:
        series = featured[column]
        decision = decisions.get(column, {})
        action = str(decision.get("action", "—"))
        reason = str(decision.get("reason_code", "—"))
        numeric_like = pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)
        kind = "numeric" if numeric_like else "categorical"

        auroc_row = _auroc(series, row_labels) if numeric_like else float("nan")
        auroc_doc = float("nan")
        if numeric_like:
            grouped = (
                pd.to_numeric(series, errors="coerce").groupby(doc_ids.to_numpy()).sum(min_count=1)
            )
            auroc_doc = _auroc(grouped, np.isin(grouped.index.to_numpy(), list(fraud_docs)))
        precision, recall, best = (
            _best_category(series, row_labels) if not numeric_like else (0.0, 0.0, "")
        )

        structural = (
            column in STRUCTURAL_COLUMNS
            or reason in STRUCTURAL_REASONS
            or reason.startswith("leakage_label")
        )
        if structural:
            verdict = "구조적차단"
        elif action == "include":
            verdict = "사용중 · " + _verdict(kind, auroc_row, precision, recall)
        else:
            verdict = _verdict(kind, auroc_row, precision, recall)

        rows.append(
            {
                "column": column,
                "kind": kind,
                "action": action,
                "reason_code": reason,
                "deny_origin": origin.get(column, ""),
                "in_allow_list": column in allow_list,
                "missing_pct": round(float(series.isna().mean()) * 100, 2),
                "auroc_row": None if not np.isfinite(auroc_row) else round(auroc_row, 4),
                "auroc_doc": None if not np.isfinite(auroc_doc) else round(auroc_doc, 4),
                "top_precision": round(precision, 4),
                "top_recall": round(recall, 4),
                "top_value": best[:40],
                "verdict": verdict,
            }
        )
        done.append(str(column))

    done_path.write_text("\n".join(done) + "\n", encoding="utf-8")
    table = pd.DataFrame(rows)
    table.to_csv(OUT / f"{stem}.csv", index=False, encoding="utf-8-sig")
    (OUT / f"{stem}.json").write_text(
        json.dumps(
            {
                "dataset": dataset_dir.name,
                "columns": int(len(table)),
                "fraud_docs": len(fraud_docs),
                "fraud_rows": int(row_labels.sum()),
                "verdict_counts": table["verdict"].value_counts().to_dict(),
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"=== {dataset_dir.name} · 컬럼 {len(table)} · 부정 문서 {len(fraud_docs)} ===\n")
    print(table["verdict"].value_counts().to_string(), "\n")

    blocked = table[(table["action"] != "include") & (table["verdict"] != "구조적차단")]
    print("=== 차단 중이며 구조적 사유가 아닌 칸 ===")
    print(
        blocked[
            [
                "column",
                "kind",
                "reason_code",
                "deny_origin",
                "in_allow_list",
                "auroc_row",
                "auroc_doc",
                "top_precision",
                "top_recall",
                "verdict",
            ]
        ].to_string(index=False),
        "\n",
    )
    print(f"산출: {OUT / stem}.csv · .json · _population.txt · _done.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
