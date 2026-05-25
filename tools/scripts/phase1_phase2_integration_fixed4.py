"""Stage 7 — fixed4 PHASE1↔PHASE2 통합 review queue recall 측정 (재사용 스크립트).

기존 `phase1_phase2_integration_stage7.py` 의 로직을 fixed4 PKL/truth/bundle 로 실행하여
phase1 / phase2 / integrated 큐의 TOP-N document recall 을 측정한다.
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
FIXED4_PHASE2_FAMILY_CACHE = ROOT / "artifacts" / "stage7_fixed4_phase2_family_by_doc.parquet"
FIXED4_INTEGRATION_JSON = (
    ROOT / "artifacts" / "phase1_phase2_integration_report_fixed4_20260523.json"
)


def main() -> int:
    t_start = time.perf_counter()

    print(f"[fixed4] loading PKL: {FIXED4_PKL.relative_to(ROOT)}")
    with FIXED4_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    detection_results = data["results"]
    print(f"[fixed4]   df rows={len(df):,} results={len(detection_results)}")

    truth = pd.read_csv(FIXED4_TRUTH)
    truth_docs = set(truth["document_id"].astype(str))
    print(f"[fixed4]   truth docs={len(truth_docs):,}")

    if FIXED4_PHASE1_CACHE.exists():
        print(f"[fixed4] loading phase1 case cache: {FIXED4_PHASE1_CACHE.relative_to(ROOT)}")
        with FIXED4_PHASE1_CACHE.open("rb") as fh:
            phase1_result = pickle.load(fh)
    else:
        print("[fixed4] running PHASE1 case_builder ...")
        phase1_result = build_phase1_case_result(
            df,
            detection_results,
            company_id="_ci_baseline",
            batch_id="v7_fixed4_2026-05-23",
            dataset_id="datasynth_manipulation_v7_candidate_fixed4",
        )
        with FIXED4_PHASE1_CACHE.open("wb") as fh:
            pickle.dump(phase1_result, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[fixed4]   phase1 cases={len(phase1_result.cases):,}")

    if FIXED4_PHASE2_FAMILY_CACHE.exists():
        print(
            f"[fixed4] loading phase2 5-family cache: "
            f"{FIXED4_PHASE2_FAMILY_CACHE.relative_to(ROOT)}"
        )
        phase2_by_doc = stage7._ensure_phase2_family_columns(
            pd.read_parquet(FIXED4_PHASE2_FAMILY_CACHE)
        )
    else:
        print("[fixed4] scoring PHASE2 5 families on full df ...")
        phase2_by_doc = stage7.score_phase2_families_by_document(df)
        phase2_by_doc.to_parquet(FIXED4_PHASE2_FAMILY_CACHE, index=False)
    print(f"[fixed4]   phase2 scored docs={len(phase2_by_doc):,}")

    print("[fixed4] building base review queue rows ...")
    overlays: list[dict[str, Any]] = []  # overlay not required for recall
    base_df = stage7._build_base_rows(phase1_result, phase2_by_doc, overlays, truth_docs)
    queue_phase1 = stage7.build_phase1_queue(base_df)
    queue_phase2 = stage7.build_phase2_queue(base_df)
    queue_integrated = stage7.build_integrated_queue(base_df, k=stage7.RRF_K)

    top_ns = [100, 500, 1000, 2000, 5000, 10000]
    doc_recall_by_queue: dict[str, list[dict[str, Any]]] = {
        "phase1": [stage7.measure_doc_recall(queue_phase1, truth_docs, n) for n in top_ns],
        "phase2": [stage7.measure_doc_recall(queue_phase2, truth_docs, n) for n in top_ns],
        "integrated": [stage7.measure_doc_recall(queue_integrated, truth_docs, n) for n in top_ns],
    }

    family_rank_distribution = stage7.summarize_family_rank_distribution(queue_integrated)

    report = {
        "dataset_version": "datasynth_manipulation_v7_candidate_fixed4",
        "elapsed_sec": round(time.perf_counter() - t_start, 2),
        "phase1_cases": len(phase1_result.cases),
        "phase2_scored_docs": int(len(phase2_by_doc)),
        "total_truth_docs": len(truth_docs),
        "rrf_k": int(stage7.RRF_K),
        "doc_recall_by_queue": doc_recall_by_queue,
        "family_rank_distribution": family_rank_distribution,
    }
    FIXED4_INTEGRATION_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[fixed4] wrote {FIXED4_INTEGRATION_JSON.relative_to(ROOT)}")

    for queue_name, recalls in doc_recall_by_queue.items():
        print(f"\n[fixed4] {queue_name}")
        for item in recalls:
            print(
                f"  TOP {item['top_n']:>6}  matched {item['matched_truth_docs']:>4}  "
                f"recall {item['recall']:.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
