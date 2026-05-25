"""Canonical remeasurement for fixed5 PHASE2 family-single recall.

Why: earlier TS/IC experiment reports mixed two different metrics under similar
labels:

- canonical fixed5 baseline: case-level family queue
- experiment helper reports: raw document-level family score ranking

This script uses only the canonical case-level family queue implemented in
``phase1_phase2_integration_stage7.measure_phase2_family_single_recall`` and
writes a comparison artifact. It does not rescore PHASE2 families.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.scripts.phase1_phase2_integration_stage7 as stage7

TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)
PHASE1_CACHE = ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"
OUT_JSON = ROOT / "artifacts" / "fixed5_family_single_canonical_remeasure_20260525.json"

TOP_NS = [100, 500, 1000, 2000, 5000, 10000]
RUNS = {
    "baseline_fixed5_normalcal5": ROOT
    / "artifacts"
    / "stage7_fixed5_normalcal5_phase2_family_by_doc_20260524.parquet",
    "ts_split": ROOT
    / "artifacts"
    / "stage7_fixed5_ts_design_fix_20260524_phase2_family_by_doc.parquet",
    "ts_redesign": ROOT
    / "artifacts"
    / "stage7_fixed5_ts_redesign_20260524_phase2_family_by_doc.parquet",
    "ic_design_fix": ROOT
    / "artifacts"
    / "stage7_fixed5_ic_design_fix_20260524_phase2_family_by_doc.parquet",
    "ic_refix": ROOT / "artifacts" / "stage7_fixed5_ic_refix_20260524_phase2_family_by_doc.parquet",
}


def _queue_recall(base_df: pd.DataFrame, truth_docs: set[str]) -> dict[str, Any]:
    queues = {
        "phase1": stage7.build_phase1_queue(base_df),
        "phase2": stage7.build_phase2_queue(base_df),
        "integrated": stage7.build_integrated_queue(base_df, k=stage7.RRF_K),
    }
    return {
        name: {
            str(n): {
                "matched": int((m := stage7.measure_doc_recall(queue, truth_docs, n))[
                    "matched_truth_docs"
                ]),
                "recall": float(m["recall"]),
            }
            for n in TOP_NS
        }
        for name, queue in queues.items()
    }


def main() -> int:
    truth = pd.read_csv(TRUTH, dtype=str)
    truth_docs = set(truth["document_id"].astype(str))
    with PHASE1_CACHE.open("rb") as fh:
        phase1_result = pickle.load(fh)

    runs: dict[str, Any] = {}
    for label, path in RUNS.items():
        if not path.exists():
            runs[label] = {"status": "missing", "path": str(path.relative_to(ROOT))}
            continue
        phase2_by_doc = pd.read_parquet(path)
        base_df = stage7._build_base_rows(phase1_result, phase2_by_doc, [], truth_docs)
        runs[label] = {
            "status": "ok",
            "path": str(path.relative_to(ROOT)),
            "phase2_scored_docs": int(len(phase2_by_doc)),
            "phase1_cases": int(len(base_df)),
            "family_single": stage7.measure_phase2_family_single_recall(
                base_df, truth_docs, TOP_NS
            ),
            "queues": _queue_recall(base_df, truth_docs),
        }

    payload = {
        "measurement_contract": {
            "name": "canonical_case_level_family_single_recall",
            "description": (
                "For each PHASE2 family, build PHASE1 case-level base_df, sort by "
                "[phase2_<family>_score_max, total_amount, rule_count] descending, "
                "then call stage7.measure_doc_recall(document_ids_joined)."
            ),
            "implementation": (
                "tools.scripts.phase1_phase2_integration_stage7."
                "measure_phase2_family_single_recall"
            ),
            "top_ns": TOP_NS,
            "truth_docs": int(len(truth_docs)),
        },
        "runs": runs,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    for label, result in runs.items():
        if result.get("status") != "ok":
            print(f"{label}: missing")
            continue
        ts = result["family_single"]["timeseries"]["phase2"]
        p2 = result["queues"]["phase2"]
        print(
            f"{label}: TS@100={ts['100']['matched']} TS@500={ts['500']['matched']} "
            f"Phase2@100={p2['100']['matched']} Phase2@500={p2['500']['matched']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
