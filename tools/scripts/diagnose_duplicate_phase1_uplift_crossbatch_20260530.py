"""Cross-batch Duplicate PHASE1-uplift diagnostic.

This script measures Duplicate native surfaces by their incremental review role
against the stored PHASE1 case order. It is diagnostic-only: detector thresholds,
row scores, PHASE1 ranking, PHASE2 family fusion, and the production duplicate
selector are not changed. Truth labels are used only after candidate construction
for aggregate evaluation.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import build_duplicate_pair_artifact
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _copy_settings_with_top_n,
    raw_identifier_leak_check,
)
from tools.scripts.diagnose_duplicate_phase1_uplift_fixed5_20260529 import (
    _case_docs_for_top_n,
    _case_surface_summary,
    _load_case_input,
    _load_phase1_result,
    _load_truth,
    _pair_surface_summary,
    _phase1_doc_rank_map,
    _policy_constraints,
    _select_phase1_gap_case_grade_pairs,
    _truth_bucket_distribution,
)
from tools.scripts.diagnose_duplicate_retention_candidates_fixed5_20260529 import (
    _case_result_for_pairs,
    _default_order_cases,
    _order_current_top100_case_anchor_plus_diversity_fill,
    _select_pair_diversity_score,
    _select_score_order,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

OUT_JSON = ROOT / "artifacts" / "duplicate_phase1_uplift_crossbatch_20260530.json"


@dataclass(frozen=True)
class BatchSpec:
    name: str
    dataset: str
    case_input: Path
    phase1_result: Path
    truth_csv: Path
    retention_batch_prefix: str


BATCHES = (
    BatchSpec(
        name="fixed4",
        dataset="datasynth_manipulation_v7_candidate_fixed4",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl",
        phase1_result=ROOT / "artifacts" / "stage7_fixed4_phase1_case_result.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed4"
        / "labels"
        / "manipulated_entry_truth.csv",
        retention_batch_prefix="fixed4_duplicate_phase1_uplift",
    ),
    BatchSpec(
        name="fixed5_normalcal5",
        dataset="datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl",
        phase1_result=ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
        / "labels"
        / "manipulated_entry_truth.csv",
        retention_batch_prefix="fixed5_duplicate_phase1_uplift",
    ),
)


def _run_batch(spec: BatchSpec) -> dict[str, Any]:
    started = time.perf_counter()
    df = _load_case_input(spec.case_input)
    truth = _load_truth(spec.truth_csv)
    truth_docs = set(truth["document_id"])
    scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    phase1_result = _load_phase1_result(spec.phase1_result)
    rank_by_doc = _phase1_doc_rank_map(phase1_result)

    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    generated_artifact = build_duplicate_pair_artifact(
        df,
        _copy_settings_with_top_n(settings, int(settings.duplicate_max_total_pairs)),
        candidate_scores=result.scores,
        candidate_details=result.details,
    ).to_dict()
    generated_pairs = list(generated_artifact.get("top_pairs", []))
    current_pairs = _select_score_order(generated_pairs, 500)
    evidence_pairs = _select_pair_diversity_score(generated_pairs, 500)
    phase1_gap_pairs = _select_phase1_gap_case_grade_pairs(
        pairs=generated_pairs,
        rank_by_doc=rank_by_doc,
        top_n=500,
    )

    current_cases = _case_result_for_pairs(
        pairs=current_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_current_500",
    )
    evidence_cases = _case_result_for_pairs(
        pairs=evidence_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_evidence_diversity_500",
    )
    phase1_gap_cases = _case_result_for_pairs(
        pairs=phase1_gap_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_phase1_gap_case_grade_500",
    )

    current_order = _default_order_cases(current_cases)
    evidence_order = _default_order_cases(evidence_cases)
    phase1_gap_order = _default_order_cases(phase1_gap_cases)
    anchor_order = _order_current_top100_case_anchor_plus_diversity_fill(
        current_cases=current_cases,
        candidate_cases=evidence_cases,
    )
    baseline_top100_docs = _case_docs_for_top_n(current_order, 100)

    phase1_all_truth_docs = set(rank_by_doc) & truth_docs
    phase1_top100_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 100}
    phase1_top500_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 500}
    phase1_top1000_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 1000}

    case_surfaces = {
        "current_document_diversity_top_500": _case_surface_summary(
            name="current_document_diversity_top_500",
            ordered_cases=current_order,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            rank_by_doc=rank_by_doc,
            baseline_top100_docs=baseline_top100_docs,
        ),
        "evidence_diversity_top_500": _case_surface_summary(
            name="evidence_diversity_top_500",
            ordered_cases=evidence_order,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            rank_by_doc=rank_by_doc,
            baseline_top100_docs=baseline_top100_docs,
        ),
        "phase1_gap_case_grade_top_500": _case_surface_summary(
            name="phase1_gap_case_grade_top_500",
            ordered_cases=phase1_gap_order,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            rank_by_doc=rank_by_doc,
            baseline_top100_docs=baseline_top100_docs,
        ),
        "current_top100_anchor_plus_diversity_fill": _case_surface_summary(
            name="current_top100_anchor_plus_diversity_fill",
            ordered_cases=anchor_order,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            rank_by_doc=rank_by_doc,
            baseline_top100_docs=baseline_top100_docs,
        ),
    }

    current_top100 = case_surfaces["current_document_diversity_top_500"]["top100"]
    evidence_top500 = case_surfaces["evidence_diversity_top_500"]["top500"]
    anchor_top500 = case_surfaces["current_top100_anchor_plus_diversity_fill"]["top500"]
    return {
        "dataset": spec.dataset,
        "phase1_reference": {
            "source": spec.phase1_result.name,
            "rank_basis": "stored_phase1_case_order_min_case_rank_per_document",
            "case_count": len(getattr(phase1_result, "cases", ())),
            "truth_doc_count": len(truth_docs),
            "truth_docs_in_phase1_cases": len(phase1_all_truth_docs),
            "truth_docs_in_phase1_top100": len(phase1_top100_docs & truth_docs),
            "truth_docs_in_phase1_top500": len(phase1_top500_docs & truth_docs),
            "truth_docs_in_phase1_top1000": len(phase1_top1000_docs & truth_docs),
            "truth_phase1_bucket_distribution": _truth_bucket_distribution(
                truth_docs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
        },
        "pair_surfaces": {
            "generated_capped_pair_evidence": _pair_surface_summary(
                pairs=generated_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "current_document_diversity_top_500": _pair_surface_summary(
                pairs=current_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "evidence_diversity_top_500": _pair_surface_summary(
                pairs=evidence_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "phase1_gap_case_grade_top_500": _pair_surface_summary(
                pairs=phase1_gap_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
        },
        "case_surfaces": case_surfaces,
        "directional_checks": {
            "current_top100_has_phase1_top100_complement_value": current_top100[
                "incremental_vs_phase1"
            ]["truth_docs_outside_phase1_top100"]
            > 0,
            "evidence_top500_improves_total_truth": evidence_top500["truth_doc_count"]
            > case_surfaces["current_document_diversity_top_500"]["top500"][
                "truth_doc_count"
            ],
            "evidence_top500_reduces_phase1_top100_complement_vs_current_top100": (
                evidence_top500["incremental_vs_phase1"][
                    "truth_docs_outside_phase1_top100"
                ]
                < current_top100["incremental_vs_phase1"][
                    "truth_docs_outside_phase1_top100"
                ]
            ),
            "anchor_top500_preserves_current_phase1_top100_complement": (
                anchor_top500["incremental_vs_phase1"][
                    "truth_docs_outside_phase1_top100"
                ]
                >= current_top100["incremental_vs_phase1"][
                    "truth_docs_outside_phase1_top100"
                ]
            ),
        },
        "policy_constraints": _policy_constraints(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    started = time.perf_counter()
    batches = {spec.name: _run_batch(spec) for spec in BATCHES}
    all_truth_docs: set[str] = set()
    for spec in BATCHES:
        truth = _load_truth(spec.truth_csv)
        all_truth_docs.update(truth["document_id"].astype(str))

    payload: dict[str, Any] = {
        "schema_version": 1,
        "measurement_scope": (
            "diagnostic-only duplicate cross-batch PHASE1-uplift comparison; "
            "aggregate only; raw identifiers omitted"
        ),
        "batches": batches,
        "interpretation": {
            "primary_question": (
                "Does Duplicate native evidence preserve PHASE1 TOP100 complement "
                "value while controlling weak pair pressure and export burden?"
            ),
            "current_read": (
                "Current document-diversity remains the first-review baseline; "
                "evidence-diversity is export/sidecar oriented unless cross-batch "
                "PHASE1-uplift improves without burden expansion."
            ),
            "production_default_selector_changed": False,
            "production_adoption_pending": True,
        },
        "policy_constraints": _policy_constraints(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=all_truth_docs,
    )
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(OUT_JSON),
                "elapsed_seconds": payload["elapsed_seconds"],
                "summary": {
                    name: batch["directional_checks"] for name, batch in batches.items()
                },
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
