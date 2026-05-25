"""Stage7 재측정 — IntercompanyMatcher cap fix 효과를 fixed4 PKL 로 측정.

기존 캐시 (`artifacts/stage7_fixed4_phase2_family_by_doc.parquet`) 를 사용하지 않고
강제로 PHASE2 5-family 점수를 재계산한다. 산출물은 `_intercompany_fix_20260524`
접미사로 분리한다. truth label 기준 cap/threshold 재튜닝은 하지 않으며 결과는
사후 검증으로만 사용한다.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
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

OUT_DIR = ROOT / "artifacts"
OUT_PHASE2_PARQUET = (
    OUT_DIR / "stage7_fixed4_intercompany_fix_20260524_phase2_family_by_doc.parquet"
)
OUT_REPORT_JSON = OUT_DIR / "stage7_fixed4_intercompany_fix_20260524_report.json"

TOP_NS = [100, 500, 1000, 2000, 5000, 10000]


def _distribution_summary(series: pd.Series) -> dict[str, float]:
    """nonzero count + mean + q95 + max for a numeric Series."""
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)
    nonzero = clean[clean > 0]
    return {
        "row_count": int(len(clean)),
        "nonzero_count": int(len(nonzero)),
        "nonzero_ratio": float(len(nonzero) / max(len(clean), 1)),
        "mean": float(clean.mean()) if len(clean) else 0.0,
        "nonzero_mean": float(nonzero.mean()) if len(nonzero) else 0.0,
        "q95": float(np.quantile(clean, 0.95)) if len(clean) else 0.0,
        "max": float(clean.max()) if len(clean) else 0.0,
    }


def _intercompany_single_family_recall(
    phase2_by_doc: pd.DataFrame, truth_docs: set[str], top_ns: list[int]
) -> list[dict[str, Any]]:
    """intercompany family score (per document max) 단독 ranking 의 TOP-N recall."""
    if "phase2_intercompany_score_max" not in phase2_by_doc.columns:
        return []
    ranked = phase2_by_doc[["document_id", "phase2_intercompany_score_max"]].copy()
    ranked["phase2_intercompany_score_max"] = pd.to_numeric(
        ranked["phase2_intercompany_score_max"], errors="coerce"
    ).fillna(0.0)
    ranked = ranked.sort_values("phase2_intercompany_score_max", ascending=False, kind="mergesort")
    out: list[dict[str, Any]] = []
    for n in top_ns:
        top = ranked.head(n)
        matched = sum(1 for doc in top["document_id"].astype(str) if doc in truth_docs)
        out.append(
            {
                "top_n": int(n),
                "matched_truth_docs": int(matched),
                "recall": float(matched / max(len(truth_docs), 1)),
            }
        )
    return out


def main() -> int:
    t_start = time.perf_counter()

    print(f"[ic-fix] loading PKL: {FIXED4_PKL.relative_to(ROOT)}")
    with FIXED4_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    detection_results = data["results"]
    print(f"[ic-fix]   df rows={len(df):,} results={len(detection_results)}")

    truth = pd.read_csv(FIXED4_TRUTH)
    truth_docs = set(truth["document_id"].astype(str))
    print(f"[ic-fix]   truth docs={len(truth_docs):,}")

    if FIXED4_PHASE1_CACHE.exists():
        print(f"[ic-fix] loading phase1 case cache: {FIXED4_PHASE1_CACHE.relative_to(ROOT)}")
        with FIXED4_PHASE1_CACHE.open("rb") as fh:
            phase1_result = pickle.load(fh)
    else:
        print("[ic-fix] running PHASE1 case_builder ...")
        phase1_result = build_phase1_case_result(
            df,
            detection_results,
            company_id="_ci_baseline",
            batch_id="v7_fixed4_2026-05-23",
            dataset_id="datasynth_manipulation_v7_candidate_fixed4",
        )
        with FIXED4_PHASE1_CACHE.open("wb") as fh:
            pickle.dump(phase1_result, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[ic-fix]   phase1 cases={len(phase1_result.cases):,}")

    # Phase2 5-family 점수는 cap fix 반영을 위해 항상 재계산 (cache 무시)
    print("[ic-fix] scoring PHASE2 5 families on full df (no cache) ...")
    t_p2 = time.perf_counter()
    phase2_by_doc = stage7.score_phase2_families_by_document(df)
    print(
        f"[ic-fix]   phase2 scored docs={len(phase2_by_doc):,}  "
        f"elapsed={time.perf_counter() - t_p2:.1f}s"
    )
    OUT_PHASE2_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    phase2_by_doc.to_parquet(OUT_PHASE2_PARQUET, index=False)
    print(f"[ic-fix]   wrote {OUT_PHASE2_PARQUET.relative_to(ROOT)}")

    # score distribution (intercompany 단독)
    ic_score_dist = _distribution_summary(phase2_by_doc["phase2_intercompany_score_max"])

    print("[ic-fix] building base review queue rows ...")
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

    intercompany_recall = _intercompany_single_family_recall(phase2_by_doc, truth_docs, TOP_NS)

    family_rank_distribution = stage7.summarize_family_rank_distribution(queue_integrated)

    report = {
        "dataset_version": "datasynth_manipulation_v7_candidate_fixed4",
        "fix_label": "intercompany_cap_fix_20260524",
        "elapsed_sec": round(time.perf_counter() - t_start, 2),
        "phase1_cases": len(phase1_result.cases),
        "phase2_scored_docs": int(len(phase2_by_doc)),
        "total_truth_docs": len(truth_docs),
        "rrf_k": int(stage7.RRF_K),
        "intercompany_score_distribution": ic_score_dist,
        "intercompany_single_family_recall": intercompany_recall,
        "doc_recall_by_queue": doc_recall_by_queue,
        "family_rank_distribution": family_rank_distribution,
    }
    OUT_REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ic-fix] wrote {OUT_REPORT_JSON.relative_to(ROOT)}")

    print("\n[ic-fix] intercompany single-family TOP recall")
    for item in intercompany_recall:
        print(
            f"  TOP {item['top_n']:>6}  matched {item['matched_truth_docs']:>4}  "
            f"recall {item['recall']:.4f}"
        )
    print("\n[ic-fix] intercompany score distribution (per-doc max)")
    for key, value in ic_score_dist.items():
        print(f"  {key}: {value}")
    for queue_name, recalls in doc_recall_by_queue.items():
        print(f"\n[ic-fix] {queue_name}")
        for item in recalls:
            print(
                f"  TOP {item['top_n']:>6}  matched {item['matched_truth_docs']:>4}  "
                f"recall {item['recall']:.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
