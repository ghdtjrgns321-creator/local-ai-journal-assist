"""Duplicate v3.1 next-improvement diagnostic.

This synthesis keeps the duplicate product path unchanged and turns the current
primary-readiness artifact into an explicit improvement plan.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts" / "duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json"
OUT_JSON = ROOT / "artifacts" / "duplicate_v31_improvement_next_fixed5_dupmeta_20260531.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    source = _read_json(SOURCE)
    attrition = source["attrition_lock"]
    score_path = source["score_path_lock"]
    no_score = source["primary_gap_decomposition"]["no_row_score_primary_docs"]
    low_score = source["primary_gap_decomposition"]["low_score_l2_03d_primary_docs"]

    primary_docs = int(attrition["primary_candidate_docs"])
    no_score_docs = int(attrition["no_row_score_primary_docs"])
    low_score_docs = int(attrition["row_score_primary_docs"])

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "diagnostic_only": True,
        "source_artifact": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "production_first_review_ranking_changed": False,
        "row_score_threshold_changed": False,
        "row_scores_changed": False,
        "top_pairs_cap_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_or_owner_metadata_used_as_selector": False,
        "truth_or_owner_metadata_used_only_for_aggregate_evaluation": True,
        "primary_target": source["v31_primary_target"],
        "blocking_stage": {
            "classification": "candidate_generation_before_pair_evidence",
            "not_top_pairs_retention": True,
            "primary_docs": primary_docs,
            "no_row_score_docs": no_score_docs,
            "low_score_docs_below_candidate_floor": low_score_docs,
            "candidate_subset_primary_docs": attrition["candidate_subset_primary_docs"],
            "generated_pair_primary_docs": attrition["generated_pair_primary_docs"],
            "duplicate_case_primary_docs": attrition["duplicate_case_primary_docs"],
        },
        "gap_profile": {
            "no_row_score_primary_docs": {
                "doc_count": no_score_docs,
                "share": no_score_docs / primary_docs,
                "observable_profile": no_score["observable_profile"],
                "read": no_score["read"],
            },
            "low_score_l2_03d_primary_docs": {
                "doc_count": low_score_docs,
                "share": low_score_docs / primary_docs,
                "score_floor_gap": low_score["score_floor_gap"],
                "primary_l2_03d_score": low_score["primary_l2_03d_score"],
                "candidate_subset_min_score": low_score["candidate_subset_min_score"],
                "primary_to_candidate_floor_ratio": low_score[
                    "primary_to_candidate_floor_ratio"
                ],
                "observable_profile": low_score["observable_profile"],
                "read": low_score["read"],
            },
        },
        "rejected_fixes": {
            "expand_top_pairs_cap": "not bottleneck; primary docs never reach pair evidence",
            "change_pair_retention_order": "not bottleneck for v3.1 primary target",
            "promote_weak_pairs": (
                "oracle probe weak ratio is too high and would weaken audit semantics"
            ),
            "use_duplicate_primary_metadata_selector": (
                "truth/owner metadata selector is prohibited"
            ),
            "lower_global_row_score_threshold": (
                "would admit broad lower-score candidates without proving pair evidence quality"
            ),
        },
        "recommended_experiments": [
            {
                "name": "observable_l2_03d_floor_band_pair_path",
                "goal": (
                    "Allow a bounded L2-03d lower-score band into diagnostic pair generation "
                    "using only observable row-score details, then measure case-grade primary docs."
                ),
                "selector_inputs_allowed": [
                    "rule id L2-03d",
                    "row duplicate score band",
                    "time-shift window",
                    "reference/text/partner similarity from pair evidence",
                    "document/document-pair diversity caps",
                ],
                "selector_inputs_forbidden": [
                    "truth label",
                    "owner metadata",
                    "scenario label",
                    "raw document id",
                    "PHASE1 rank",
                ],
            },
            {
                "name": "same_account_relaxation_diagnostic",
                "goal": (
                    "Test whether near amount + exact reference + same partner + same process "
                    "can produce case-grade pair evidence when same_account is false."
                ),
                "selector_inputs_allowed": [
                    "same partner",
                    "same business process",
                    "near amount bucket",
                    "exact reference similarity",
                    "time shift bucket",
                ],
                "selector_inputs_forbidden": [
                    "truth label",
                    "owner metadata",
                    "scenario label",
                    "raw document id",
                ],
            },
        ],
        "decision": {
            "change_product_default_now": False,
            "next_improvement_class": (
                "row_score_feature_coverage_and_observable_lower_score_pair_path"
            ),
            "next_prompt": (
                "Implement diagnostic-only duplicate candidate generation experiments "
                "for v3.1 primary docs: (1) bounded L2-03d lower-score band pair path, "
                "and (2) same-account relaxation when same partner/process, exact "
                "reference, near amount, and 1-3 day shift are present. Do not use "
                "truth/owner metadata as selector, do not change global row-score "
                "threshold, do not expand top_pairs as the primary fix, and report "
                "case-grade primary docs plus weak-pair pressure."
            ),
        },
        "raw_identifier_leak_check": source["raw_identifier_leak_check"],
        "source_score_path_lock": score_path,
    }

    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
