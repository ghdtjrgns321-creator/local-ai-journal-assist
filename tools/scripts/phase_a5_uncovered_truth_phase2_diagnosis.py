"""Phase A.5 measurement for TS-13 uncovered truth documents.

Measurement-only script. It does not retrain PHASE2, does not tune weights with
truth labels, and does not modify production code.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.services.queue_fusion import K_DEFAULT as RRF_K
from src.services.queue_fusion import compute_rrf_score
from tools.scripts.phase2_family_correlation_audit import FAMILIES, score_all_families

DATASET_VERSION = "datasynth_manipulation_v7_candidate_fixed3"
PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
TRUTH_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / DATASET_VERSION
    / "labels"
    / "manipulated_entry_truth.csv"
)
TS13_PATH = ROOT / "artifacts" / "ts13_uncovered_truth_80_analysis.json"
FAMILY_BY_DOC_PATH = ROOT / "artifacts" / "stage7_phase2_family_by_doc.parquet"
QUEUE_DIR = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "review_queue"
    / "v1"
)
QUEUE_PHASE1_PATH = QUEUE_DIR / "queue_phase1.parquet"
QUEUE_PHASE2_PATH = QUEUE_DIR / "queue_phase2.parquet"
OUT_JSON = ROOT / "artifacts" / "doc_level_ranking_phase_a5_20260519.json"
OUT_MD = ROOT / "artifacts" / "doc_level_ranking_phase_a5_20260519.md"

TOP_NS = (100, 500, 1000, 2000)
DOC_CEILING_REFERENCE = 87.10
FAMILY_MAX_COLS = {
    family: f"phase2_{family}_score_max"
    for family in FAMILIES
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def quantiles(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return {
        "q50": float(clean.quantile(0.50)),
        "q75": float(clean.quantile(0.75)),
        "q90": float(clean.quantile(0.90)),
        "q95": float(clean.quantile(0.95)),
        "q99": float(clean.quantile(0.99)),
    }


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def load_inputs() -> dict[str, Any]:
    with PKL_PATH.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    df["fiscal_year"] = df["fiscal_year"].astype(int)

    truth = pd.read_csv(TRUTH_PATH)
    truth["document_id"] = truth["document_id"].astype(str)

    with TS13_PATH.open(encoding="utf-8") as fh:
        ts13 = json.load(fh)
    uncovered_docs = {str(doc_id) for doc_id in ts13["uncovered_document_ids"]}

    queues = {
        "phase1": pd.read_parquet(QUEUE_PHASE1_PATH),
        "phase2": pd.read_parquet(QUEUE_PHASE2_PATH),
    }
    family_by_doc = pd.read_parquet(FAMILY_BY_DOC_PATH)
    family_by_doc["document_id"] = family_by_doc["document_id"].astype(str)

    return {
        "df": df,
        "truth": truth,
        "truth_docs": set(truth["document_id"]),
        "uncovered_docs": uncovered_docs,
        "queues": queues,
        "family_by_doc": family_by_doc,
    }


def to_ecdf(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return values.rank(method="average", pct=True).astype(float)


def row_family_scores(df: pd.DataFrame) -> pd.DataFrame:
    scores = score_all_families(df)
    scores["document_id"] = df["document_id"].astype(str).to_numpy()
    for family in FAMILIES:
        scores[family] = pd.to_numeric(scores[family], errors="coerce").fillna(0.0)
    return scores


def family_quantile_summary(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    row_count = max(len(frame), 1)
    for family in FAMILIES:
        clean = pd.to_numeric(frame[family], errors="coerce").fillna(0.0)
        item = quantiles(clean)
        item["nonzero_rate"] = float((clean > 0).sum() / row_count)
        out[family] = item
    return out


def family_hit_matrix(frame: pd.DataFrame) -> dict[str, Any]:
    bools = frame[list(FAMILIES)].fillna(0.0).gt(0.0)
    combo_counts: Counter[str] = Counter()
    for row in bools.itertuples(index=False, name=None):
        active = [family for family, hit in zip(FAMILIES, row, strict=True) if hit]
        combo_counts["+".join(active) if active else "none"] += 1
    return {
        "family_nonzero_row_count": {family: int(bools[family].sum()) for family in FAMILIES},
        "row_count_by_family_hit_count": {
            str(hit_count): int(count)
            for hit_count, count in bools.sum(axis=1).value_counts().sort_index().items()
        },
        "family_combination_row_count": dict(sorted(combo_counts.items())),
    }


def doc_family_max(row_scores: pd.DataFrame) -> pd.DataFrame:
    return (
        row_scores.groupby("document_id", as_index=False)[list(FAMILIES)]
        .max()
        .sort_values("document_id", kind="mergesort")
        .reset_index(drop=True)
    )


def doc_max_quantiles(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {family: quantiles(frame[family]) for family in FAMILIES}


def scenario_summary(doc_max_80: pd.DataFrame, truth: pd.DataFrame) -> dict[str, Any]:
    merged = doc_max_80.merge(
        truth[["document_id", "manipulation_scenario"]],
        on="document_id",
        how="left",
    )
    out: dict[str, Any] = {}
    for scenario, group in merged.groupby("manipulation_scenario", dropna=False):
        name = str(scenario)
        out[name] = {
            "doc_count": int(len(group)),
            "family_max_quantiles": doc_max_quantiles(group),
        }
    return out


def build_truth_case_mapping(
    truth_docs: set[str],
    phase1_queue: pd.DataFrame,
) -> tuple[dict[str, str | None], dict[str, Any]]:
    candidates: dict[str, list[tuple[float, str]]] = {doc: [] for doc in truth_docs}
    mapping_cols = ["case_id", "phase1_priority_score", "document_ids_joined"]
    for row in phase1_queue[mapping_cols].itertuples(index=False):
        score = float(row.phase1_priority_score)
        case_id = str(row.case_id)
        for doc in str(row.document_ids_joined or "").split(";"):
            doc_id = doc.strip()
            if doc_id in candidates:
                candidates[doc_id].append((score, case_id))

    mapping: dict[str, str | None] = {}
    for doc_id, rows in candidates.items():
        if not rows:
            mapping[doc_id] = None
            continue
        rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        mapping[doc_id] = rows[0][1]

    queued = sum(case_id is not None for case_id in mapping.values())
    total = len(truth_docs)
    ceiling = queued / max(total, 1) * 100
    summary = {
        "truth_doc_count": total,
        "truth_case_count_after_mapping": total,
        "queued_truth_case_count": int(queued),
        "uncovered_truth_case_count": int(total - queued),
        "case_ceiling_pct": float(round(ceiling, 2)),
        "doc_ceiling_pct_reference": DOC_CEILING_REFERENCE,
        "mapping_consistent": bool(total == 620 and round(ceiling, 2) == DOC_CEILING_REFERENCE),
    }
    return mapping, summary


def build_rrf_2way_queue(phase1_queue: pd.DataFrame) -> pd.DataFrame:
    base = phase1_queue.copy().reset_index(drop=True)
    rankers = {
        "phase1_composite": base["phase1_composite_sort_score"]
        .astype(np.float64)
        .reset_index(drop=True),
        "phase2_unsupervised": base["phase2_unsupervised_score_max"]
        .astype(np.float64)
        .reset_index(drop=True),
    }
    rrf = compute_rrf_score(rankers, k=RRF_K)
    merged = base.join(rrf)
    ranked = merged.sort_values(
        by=["rrf_score", "phase1_composite_sort_score"],
        ascending=False,
        kind="mergesort",
    ).reset_index(drop=True)
    if "review_rank" in ranked.columns:
        ranked = ranked.drop(columns=["review_rank"])
    ranked.insert(0, "review_rank", ranked.index + 1)
    return ranked


def case_recall(queue_df: pd.DataFrame, mapping: dict[str, str | None]) -> list[dict[str, Any]]:
    denom = max(len(mapping), 1)
    out: list[dict[str, Any]] = []
    for top_n in TOP_NS:
        selected = set(queue_df.head(top_n)["case_id"].astype(str))
        matched = sum(case_id in selected for case_id in mapping.values() if case_id is not None)
        out.append(
            {
                "top_n": int(top_n),
                "matched_truth_cases": int(matched),
                "recall": float(matched / denom),
            }
        )
    return out


def m1_measurement(inputs: dict[str, Any]) -> dict[str, Any]:
    row_scores = row_family_scores(inputs["df"])
    uncovered_docs = inputs["uncovered_docs"]
    rows_80 = row_scores[row_scores["document_id"].isin(uncovered_docs)].copy()
    doc_max_all = doc_family_max(row_scores)
    doc_max_80 = doc_max_all[doc_max_all["document_id"].isin(uncovered_docs)].copy()

    covered_docs = inputs["truth_docs"] - uncovered_docs
    doc_max_540 = doc_max_all[doc_max_all["document_id"].isin(covered_docs)].copy()
    background_q95 = {
        family: float(doc_max_540[family].fillna(0.0).quantile(0.95))
        for family in FAMILIES
    }
    above_q95 = {
        family: (
            int((doc_max_80[family].fillna(0.0) >= background_q95[family]).sum())
            if background_q95[family] > 0.0
            else 0
        )
        for family in FAMILIES
    }

    doc_matrix = [
        {
            "document_id": row.document_id,
            **{family: finite_float(getattr(row, family)) for family in FAMILIES},
        }
        for row in doc_max_80.sort_values("document_id").itertuples(index=False)
    ]

    def doc_class(row: pd.Series) -> str:
        values = row[list(FAMILIES)].astype(float)
        if bool((values == 0.0).all()):
            return "all_zero"
        strong = any(
            background_q95[family] > 0.0 and float(values[family]) >= background_q95[family]
            for family in FAMILIES
        )
        return "strong" if strong else "weak_nonzero"

    classes = doc_max_80.apply(doc_class, axis=1)
    all_zero = int((classes == "all_zero").sum())
    weak = int((classes == "weak_nonzero").sum())
    strong = int((classes == "strong").sum())
    interpretation = (
        "집계 손실 가능성"
        if strong >= max(5, len(doc_max_80) * 0.10)
        else "탐지기 한계"
    )

    return {
        "row_count_in_80_docs": int(len(rows_80)),
        "row_level_family_quantiles": family_quantile_summary(rows_80),
        "row_family_hit_matrix": family_hit_matrix(rows_80),
        "doc_level_family_max_quantiles": doc_max_quantiles(doc_max_80),
        "doc_level_family_max_matrix_80x5": doc_matrix,
        "comparison_with_covered_540_docs": {
            "background_q95_per_family": background_q95,
            "80_docs_above_background_q95_count_per_family": above_q95,
            "covered_540_doc_level_family_max_quantiles": doc_max_quantiles(doc_max_540),
        },
        "by_scenario": scenario_summary(doc_max_80, inputs["truth"]),
        "verdict": {
            "all_zero_count": all_zero,
            "weak_nonzero_count": weak,
            "strong_count": strong,
            "all_zero_rate": float(all_zero / max(len(doc_max_80), 1)),
            "weak_nonzero_rate": float(weak / max(len(doc_max_80), 1)),
            "strong_rate": float(strong / max(len(doc_max_80), 1)),
            "interpretation": interpretation,
        },
    }


def build_json_payload(inputs: dict[str, Any]) -> dict[str, Any]:
    m1 = m1_measurement(inputs)
    mapping, m2 = build_truth_case_mapping(inputs["truth_docs"], inputs["queues"]["phase1"])
    rrf_2way = build_rrf_2way_queue(inputs["queues"]["phase1"])
    m3 = {
        "phase1": case_recall(inputs["queues"]["phase1"], mapping),
        "phase2": case_recall(inputs["queues"]["phase2"], mapping),
        "rrf_2way": case_recall(rrf_2way, mapping),
    }
    return {
        "generated_at": now_iso(),
        "purpose": "Phase A.5 — TS-13 80건 PHASE2 진단 + case-level ceiling 재산정",
        "fitting_guard": {
            "truth_used_for": "evaluation_only",
            "phase2_model_retrain": False,
            "case_truth_mapping_method": "priority_score_argmax",
        },
        "input_sources": [
            str(TRUTH_PATH.relative_to(ROOT)),
            str(TS13_PATH.relative_to(ROOT)),
            str(PKL_PATH.relative_to(ROOT)),
            str(FAMILY_BY_DOC_PATH.relative_to(ROOT)),
            str(QUEUE_PHASE1_PATH.relative_to(ROOT)),
            str(QUEUE_PHASE2_PATH.relative_to(ROOT)),
        ],
        "M1_uncovered_80_phase2_distribution": m1,
        "M2_case_level_ceiling": m2,
        "M3_case_level_recall": m3,
    }


def family_table(summary: dict[str, Any]) -> str:
    rows = [
        "| family | q50 | q75 | q90 | q95 | q99 | nonzero |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family in FAMILIES:
        item = summary[family]
        rows.append(
            f"| {family} | {item['q50']:.6f} | {item['q75']:.6f} | {item['q90']:.6f} | "
            f"{item['q95']:.6f} | {item['q99']:.6f} | {pct(item['nonzero_rate'])} |"
        )
    return "\n".join(rows)


def doc_max_table(summary: dict[str, Any]) -> str:
    rows = ["| family | q50 | q75 | q90 | q95 | q99 |", "|---|---:|---:|---:|---:|---:|"]
    for family in FAMILIES:
        item = summary[family]
        rows.append(
            f"| {family} | {item['q50']:.6f} | {item['q75']:.6f} | {item['q90']:.6f} | "
            f"{item['q95']:.6f} | {item['q99']:.6f} |"
        )
    return "\n".join(rows)


def background_table(m1: dict[str, Any]) -> str:
    comp = m1["comparison_with_covered_540_docs"]
    rows = [
        "| family | covered 540 q95 | 80 docs >= q95 |",
        "|---|---:|---:|",
    ]
    for family in FAMILIES:
        rows.append(
            f"| {family} | {comp['background_q95_per_family'][family]:.6f} | "
            f"{comp['80_docs_above_background_q95_count_per_family'][family]} |"
        )
    return "\n".join(rows)


def scenario_table(by_scenario: dict[str, Any]) -> str:
    rows = [
        (
            "| scenario | docs | unsup q95 | timeseries q95 | relational q95 | "
            "duplicate q95 | intercompany q95 |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario, item in sorted(by_scenario.items()):
        q = item["family_max_quantiles"]
        rows.append(
            f"| {scenario} | {item['doc_count']} | {q['unsupervised']['q95']:.6f} | "
            f"{q['timeseries']['q95']:.6f} | {q['relational']['q95']:.6f} | "
            f"{q['duplicate']['q95']:.6f} | {q['intercompany']['q95']:.6f} |"
        )
    return "\n".join(rows)


def verdict_table(verdict: dict[str, Any]) -> str:
    total = verdict["all_zero_count"] + verdict["weak_nonzero_count"] + verdict["strong_count"]
    rows = ["| class | count | rate |", "|---|---:|---:|"]
    rows.append(
        f"| all-zero | {verdict['all_zero_count']} | "
        f"{pct(verdict['all_zero_count'] / max(total, 1))} |"
    )
    rows.append(
        f"| weak-nonzero | {verdict['weak_nonzero_count']} | "
        f"{pct(verdict['weak_nonzero_count'] / max(total, 1))} |"
    )
    rows.append(
        f"| strong | {verdict['strong_count']} | "
        f"{pct(verdict['strong_count'] / max(total, 1))} |"
    )
    return "\n".join(rows)


def recall_table(m3: dict[str, Any]) -> str:
    rows = [
        "| queue | TOP-100 | TOP-500 | TOP-1000 | TOP-2000 |",
        "|---|---:|---:|---:|---:|",
    ]
    for queue_name in ("phase1", "phase2", "rrf_2way"):
        by_top = {item["top_n"]: item for item in m3[queue_name]}
        cells = []
        for top_n in TOP_NS:
            item = by_top[top_n]
            cells.append(f"{item['matched_truth_cases']} ({pct(item['recall'])})")
        rows.append(f"| {queue_name} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def build_markdown(payload: dict[str, Any]) -> str:
    m1 = payload["M1_uncovered_80_phase2_distribution"]
    m2 = payload["M2_case_level_ceiling"]
    m3 = payload["M3_case_level_recall"]
    verdict = m1["verdict"]
    one_line = (
        "ceiling 확정 — all-zero 또는 weak-nonzero 대부분 → 탐지기 본질 한계, ceiling 확정"
        if verdict["interpretation"] == "탐지기 한계"
        else (
            "옵션 나 재검토 — weak-nonzero 분포가 background와 구별 가능 "
            "→ cross-doc corroboration 재검토"
        )
    )
    return f"""# Phase A.5 — TS-13 80건 PHASE2 진단 + case-level ceiling 재산정

## 0. 한 줄 결론 — 80건 회수 가능성 최종 판정
{one_line}

## 1. 측정 환경
- generated_at: `{payload['generated_at']}`
- truth_used_for: evaluation_only
- phase2_model_retrain: false
- case_truth_mapping_method: priority_score_argmax
- src/dashboard/config/docs 변경 없음

## 2. M1 — 80 doc의 PHASE2 row-level 5 family 분포

### 2.1. row-level quantile 표
{family_table(m1['row_level_family_quantiles'])}

### 2.2. doc-level max quantile 표
{doc_max_table(m1['doc_level_family_max_quantiles'])}

### 2.3. background (540 covered docs) 대비 비교
{background_table(m1)}

### 2.4. 시나리오별 분포
{scenario_table(m1['by_scenario'])}

### 2.5. all-zero / weak-nonzero / strong 비율
{verdict_table(verdict)}

## 3. M2 — case-level ceiling 재산정
- truth doc count: {m2['truth_doc_count']}
- truth case count after mapping: {m2['truth_case_count_after_mapping']}
- queued truth case count: {m2['queued_truth_case_count']}
- uncovered truth case count: {m2['uncovered_truth_case_count']}
- case ceiling: {m2['case_ceiling_pct']:.2f}%
- doc ceiling reference: {m2['doc_ceiling_pct_reference']:.2f}%
- mapping consistent: {m2['mapping_consistent']}

## 4. M3 — case-level recall 표
{recall_table(m3)}

## 5. 결론 — Phase B/C 분기 결정
{one_line}

## 6. fitting 가드 체크리스트
- [x] truth label은 평가용으로만 사용
- [x] truth 기반 산식 weight 튜닝 없음
- [x] PHASE2 row score 산식 변경 없음
- [x] model_bundle.pt 재학습 없음
- [x] 1 truth doc → 1 truth case 매핑은 priority_score 기준만 사용
- [x] src/, dashboard/, config/, docs/ 변경 없음
- [x] Phase B/C 코드 작성 없음
"""


def write_outputs(payload: dict[str, Any]) -> None:
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(build_markdown(payload), encoding="utf-8")


def main() -> int:
    inputs = load_inputs()
    payload = build_json_payload(inputs)
    write_outputs(payload)
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
