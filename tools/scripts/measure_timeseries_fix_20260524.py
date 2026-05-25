"""Phase 2 timeseries family gating fix — fixed4 standalone rerun (cache 미사용).

Why: 사용자 지시에 따라 기존 stage7_fixed4_phase2_family_by_doc.parquet cache 를
사용하지 않고 timeseries detector 변경 후 새로 score 를 산출한다. 결과는
artifacts/20260524_timeseries_fix_*.{parquet,json,md} 에 저장하며, 기존
DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md 는 업데이트하지 않는다.

측정 항목:
  - timeseries single-family TOP-N document recall (단독 ranking)
  - PHASE2 5-family 통합 (Noisy-OR) TOP-N document recall
  - PHASE1 단독 + PHASE1+PHASE2 통합 TOP-N document recall
  - timeseries 포함 5 family score distribution (nonzero count, mean, q95, max)

이 결과는 사후 검증 (post-hoc) 용도이며 truth recall 기준으로 detector 를 재튜닝
하지 않는다 (fitting 회피).
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.scripts.phase1_phase2_integration_stage7 as stage7
from src.detection.phase1_case_builder import build_phase1_case_result

FIXED4_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl"
FIXED4_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed4"
    / "labels"
    / "manipulated_entry_truth.csv"
)
FIXED4_PHASE1_CACHE = ROOT / "artifacts" / "stage7_fixed4_phase1_case_result.pkl"

OUT_PHASE2_PARQUET = ROOT / "artifacts" / "20260524_timeseries_fix_phase2_family_by_doc.parquet"
OUT_REPORT_JSON = ROOT / "artifacts" / "20260524_timeseries_fix_report.json"
OUT_REPORT_MD = ROOT / "artifacts" / "20260524_timeseries_fix_report.md"

TOP_NS = [100, 500, 1000, 2000, 5000, 10000]


def _timeseries_single_family_recall(
    phase2_by_doc: pd.DataFrame,
    truth_docs: set[str],
    top_ns: list[int],
) -> list[dict[str, Any]]:
    """timeseries family score 만으로 ranking 한 TOP-N document recall."""
    score_col = "phase2_timeseries_score_max"
    if score_col not in phase2_by_doc.columns:
        return []
    ordered = (
        phase2_by_doc[["document_id", score_col]]
        .copy()
        .assign(_score=lambda x: pd.to_numeric(x[score_col], errors="coerce").fillna(0.0))
        .sort_values(by="_score", ascending=False, kind="mergesort")
        .reset_index(drop=True)
    )
    docs = ordered["document_id"].astype(str).tolist()
    total_truth = len(truth_docs)
    rows: list[dict[str, Any]] = []
    for n in top_ns:
        top_docs = set(docs[:n])
        matched = len(top_docs & truth_docs)
        rows.append(
            {
                "top_n": int(n),
                "matched_truth_docs": int(matched),
                "total_truth_docs": int(total_truth),
                "recall": (matched / total_truth) if total_truth else 0.0,
            }
        )
    return rows


def _family_score_distribution(phase2_by_doc: pd.DataFrame) -> dict[str, dict[str, float]]:
    """5 family doc-level score (max) 분포 요약 — 변경 전후 비교용."""
    summary: dict[str, dict[str, float]] = {}
    for family in stage7.PHASE2_FAMILIES:
        col = stage7.PHASE2_FAMILY_SCORE_MAX_COLUMNS[family]
        if col not in phase2_by_doc.columns:
            continue
        series = pd.to_numeric(phase2_by_doc[col], errors="coerce").fillna(0.0)
        summary[family] = {
            "nonzero_doc_count": int((series > 0).sum()),
            "nonzero_doc_rate": float((series > 0).mean()),
            "score_mean": float(series.mean()),
            "score_q95": float(series.quantile(0.95)),
            "score_q99": float(series.quantile(0.99)),
            "score_max": float(series.max()),
        }
    return summary


def _render_md(report: dict[str, Any]) -> str:
    def _recall_table(rows: list[dict[str, Any]]) -> str:
        lines = ["| TOP-N | matched | total | recall |", "|---:|---:|---:|---:|"]
        for r in rows:
            lines.append(
                f"| {r['top_n']:,} | {r['matched_truth_docs']:,} | "
                f"{r['total_truth_docs']:,} | {r['recall']:.4f} |"
            )
        return "\n".join(lines)

    out = ["# Phase 2 timeseries gating fix — fixed4 standalone rerun"]
    out.append("")
    out.append(
        f"- dataset: `{report['dataset_version']}`  "
        f"\n- elapsed: {report['elapsed_sec']:.2f} s  "
        f"\n- phase1 cases: {report['phase1_cases']:,}  "
        f"\n- phase2 scored docs: {report['phase2_scored_docs']:,}  "
        f"\n- truth docs: {report['total_truth_docs']:,}"
    )
    out.append("")
    out.append("## 1. timeseries single-family TOP-N document recall")
    out.append("")
    out.append(_recall_table(report["timeseries_single_family_recall"]))
    out.append("")
    out.append("## 2. PHASE2 단독 큐 (Noisy-OR 5-family) TOP-N recall")
    out.append("")
    out.append(_recall_table(report["doc_recall_by_queue"]["phase2"]))
    out.append("")
    out.append("## 3. PHASE1 단독 큐 TOP-N recall")
    out.append("")
    out.append(_recall_table(report["doc_recall_by_queue"]["phase1"]))
    out.append("")
    out.append("## 4. PHASE1+PHASE2 통합 큐 (2-way RRF k=60) TOP-N recall")
    out.append("")
    out.append(_recall_table(report["doc_recall_by_queue"]["integrated"]))
    out.append("")
    out.append("## 5. Family score distribution (document-level max)")
    out.append("")
    out.append("| family | nonzero docs | nonzero rate | mean | q95 | q99 | max |")
    out.append("|---|---:|---:|---:|---:|---:|---:|")
    for family, stats in report["family_score_distribution"].items():
        out.append(
            f"| `{family}` | {stats['nonzero_doc_count']:,} | "
            f"{stats['nonzero_doc_rate']:.4f} | {stats['score_mean']:.4f} | "
            f"{stats['score_q95']:.4f} | {stats['score_q99']:.4f} | "
            f"{stats['score_max']:.4f} |"
        )
    out.append("")
    out.append(
        "> 본 결과는 사후 검증 (post-hoc) 용도이며 truth recall 기준으로 detector "
        "를 재튜닝하지 않는다. 기존 결과 문서 (DETECTION_RESULTS_MANIPULATION_V7_"
        "FIXED4_PHASE2.md) 는 업데이트하지 않는다."
    )
    out.append("")
    return "\n".join(out)


def main() -> int:
    t_start = time.perf_counter()

    print(f"[ts-fix] loading PKL: {FIXED4_PKL.relative_to(ROOT)}")
    with FIXED4_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    detection_results = data["results"]
    print(f"[ts-fix]   df rows={len(df):,} results={len(detection_results)}")

    truth = pd.read_csv(FIXED4_TRUTH)
    truth_docs = set(truth["document_id"].astype(str))
    print(f"[ts-fix]   truth docs={len(truth_docs):,}")

    if FIXED4_PHASE1_CACHE.exists():
        print(
            f"[ts-fix] loading phase1 case cache (untouched by this fix): "
            f"{FIXED4_PHASE1_CACHE.relative_to(ROOT)}"
        )
        with FIXED4_PHASE1_CACHE.open("rb") as fh:
            phase1_result = pickle.load(fh)
    else:
        print("[ts-fix] running PHASE1 case_builder ...")
        phase1_result = build_phase1_case_result(
            df,
            detection_results,
            company_id="_ci_baseline",
            batch_id="v7_fixed4_2026-05-23",
            dataset_id="datasynth_manipulation_v7_candidate_fixed4",
        )
        with FIXED4_PHASE1_CACHE.open("wb") as fh:
            pickle.dump(phase1_result, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[ts-fix]   phase1 cases={len(phase1_result.cases):,}")

    print(
        "[ts-fix] scoring PHASE2 5 families on full df "
        f"(fresh; output={OUT_PHASE2_PARQUET.relative_to(ROOT)}) ..."
    )
    phase2_by_doc = stage7.score_phase2_families_by_document(df)
    phase2_by_doc.to_parquet(OUT_PHASE2_PARQUET, index=False)
    print(f"[ts-fix]   phase2 scored docs={len(phase2_by_doc):,}")

    print("[ts-fix] building base review queue rows ...")
    overlays: list[dict[str, Any]] = []
    base_df = stage7._build_base_rows(phase1_result, phase2_by_doc, overlays, truth_docs)
    queue_phase1 = stage7.build_phase1_queue(base_df)
    queue_phase2 = stage7.build_phase2_queue(base_df)
    queue_integrated = stage7.build_integrated_queue(base_df, k=stage7.RRF_K)

    doc_recall_by_queue: dict[str, list[dict[str, Any]]] = {
        "phase1": [stage7.measure_doc_recall(queue_phase1, truth_docs, n) for n in TOP_NS],
        "phase2": [stage7.measure_doc_recall(queue_phase2, truth_docs, n) for n in TOP_NS],
        "integrated": [stage7.measure_doc_recall(queue_integrated, truth_docs, n) for n in TOP_NS],
    }
    timeseries_single = _timeseries_single_family_recall(phase2_by_doc, truth_docs, TOP_NS)
    family_distribution = _family_score_distribution(phase2_by_doc)
    family_rank_distribution = stage7.summarize_family_rank_distribution(queue_integrated)

    report = {
        "dataset_version": "datasynth_manipulation_v7_candidate_fixed4",
        "elapsed_sec": round(time.perf_counter() - t_start, 2),
        "phase1_cases": len(phase1_result.cases),
        "phase2_scored_docs": int(len(phase2_by_doc)),
        "total_truth_docs": len(truth_docs),
        "rrf_k": int(stage7.RRF_K),
        "top_ns": TOP_NS,
        "timeseries_single_family_recall": timeseries_single,
        "doc_recall_by_queue": doc_recall_by_queue,
        "family_score_distribution": family_distribution,
        "family_rank_distribution": family_rank_distribution,
        "notes": (
            "Phase 2 timeseries detector period_end gating fix (2026-05-24). "
            "ts_period_end_context_cap=0.30, ts_period_end_context_threshold=0.50. "
            "Cache stage7_fixed4_phase2_family_by_doc.parquet 미사용. "
            "결과는 사후 검증 (post-hoc) 용도, truth-recall 기준 재튜닝 금지."
        ),
    }
    OUT_REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    OUT_REPORT_MD.write_text(_render_md(report), encoding="utf-8")

    print(f"[ts-fix] wrote {OUT_REPORT_JSON.relative_to(ROOT)}")
    print(f"[ts-fix] wrote {OUT_REPORT_MD.relative_to(ROOT)}")

    for queue_name, recalls in doc_recall_by_queue.items():
        print(f"\n[ts-fix] {queue_name}")
        for item in recalls:
            print(
                f"  TOP {item['top_n']:>6}  matched {item['matched_truth_docs']:>4}  "
                f"recall {item['recall']:.4f}"
            )
    print("\n[ts-fix] timeseries single-family")
    for item in timeseries_single:
        print(
            f"  TOP {item['top_n']:>6}  matched {item['matched_truth_docs']:>4}  "
            f"recall {item['recall']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
