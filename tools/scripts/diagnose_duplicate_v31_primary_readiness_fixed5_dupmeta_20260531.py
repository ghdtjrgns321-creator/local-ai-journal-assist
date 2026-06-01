"""Duplicate v3.1 primary readiness synthesis for fixed5_dupmeta.

This diagnostic-only script does not run duplicate detection. It reads the
existing aggregate duplicate primary-target and sidecar artifacts, then emits a
smaller readiness contract for product-policy consumers and docs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRIMARY_ARTIFACT = (
    ROOT / "artifacts" / "duplicate_primary_target_fixed5_dupmeta_20260530.json"
)
SIDECAR_ARTIFACT = (
    ROOT / "artifacts" / "duplicate_candidate_sidecar_fixed5_dupmeta_20260530.json"
)
OUT_JSON = ROOT / "artifacts" / "duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_clean_leak_check(payload: dict[str, Any]) -> None:
    leak = payload.get("raw_identifier_leak_check", {})
    expected = {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
    if leak != expected:
        raise ValueError(f"raw identifier leak check failed: {leak!r}")


def build_payload() -> dict[str, Any]:
    primary = _read_json(PRIMARY_ARTIFACT)
    sidecar = _read_json(SIDECAR_ARTIFACT)
    _assert_clean_leak_check(primary)
    _assert_clean_leak_check(sidecar)

    attrition = primary["stage_attrition"]
    profile = primary["row_score_selection_profile"]
    sidecar_decision = sidecar["decision"]
    sidecar_samples = sidecar["sidecar_sampling_candidate"]
    oracle_probe = sidecar_samples["duplicate_primary_metadata_probe_sample"]
    non_oracle_l2 = sidecar_samples["l2_03d_stratified_low_score_sample"]
    non_oracle_rule = sidecar_samples["rule_balanced_duplicate_candidate_sample"]
    no_row_score_profile = sidecar["primary_gap_groups"]["no_row_score_primary_docs"]
    low_score_profile = sidecar["primary_gap_groups"]["low_score_l2_03d_primary_docs"]

    selected_min = profile["selected_candidate_min_score"]
    primary_l2_score = profile["primary_row_score_quantiles"]["max"]
    score_floor_gap = (
        selected_min - primary_l2_score
        if selected_min is not None and primary_l2_score is not None
        else None
    )

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": primary["dataset"],
        "diagnostic_only": True,
        "source_artifacts": {
            "primary_target": str(PRIMARY_ARTIFACT.relative_to(ROOT)).replace("\\", "/"),
            "candidate_sidecar": str(SIDECAR_ARTIFACT.relative_to(ROOT)).replace("\\", "/"),
        },
        "production_first_review_ranking_changed": False,
        "row_score_threshold_changed": False,
        "row_scores_changed": False,
        "top_pairs_cap_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_metadata_used_as_selector": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "v31_primary_target": {
            "primary_candidate_docs": primary["duplicate_primary_target"]["primary_doc_count"],
            "pair_groups": primary["duplicate_primary_target"]["pair_group_count"],
            "pair_group_size_distribution": primary["duplicate_primary_target"][
                "pair_group_size_distribution"
            ],
            "scenario_distribution": primary["duplicate_primary_target"][
                "scenario_distribution"
            ],
        },
        "attrition_lock": {
            "primary_candidate_docs": attrition["primary_target_docs"],
            "row_score_primary_docs": attrition["row_score_primary_docs"],
            "no_row_score_primary_docs": sidecar["row_score_coverage_gap_docs"],
            "candidate_subset_primary_docs": attrition["candidate_subset_primary_docs"],
            "generated_pair_primary_docs": attrition["generated_pair_primary_docs"],
            "top_pairs_primary_docs": attrition["top_pairs_primary_docs"],
            "case_grade_top_pairs_primary_docs": attrition[
                "case_grade_top_pairs_primary_docs"
            ],
            "duplicate_case_primary_docs": attrition["duplicate_case_primary_docs"],
        },
        "score_path_lock": {
            "all_duplicate_row_score_hits": profile["all_row_score_hit_count"],
            "primary_row_score_hit_row_count": profile["primary_row_score_hit_row_count"],
            "primary_row_score_hit_doc_count": profile["primary_row_score_hit_doc_count"],
            "primary_rule_doc_counts": profile["primary_rule_doc_counts"],
            "primary_rule_row_counts": profile["primary_rule_row_counts"],
            "primary_l2_03d_score": primary_l2_score,
            "candidate_subset_min_score": selected_min,
            "primary_l2_03d_below_candidate_floor": bool(
                primary_l2_score is not None
                and selected_min is not None
                and primary_l2_score < selected_min
            ),
            "candidate_subset_selected_rows": primary["candidate_subset"][
                "selected_candidate_rows"
            ],
            "candidate_subset_mode": primary["candidate_subset"]["coverage"][
                "large_input_candidate_mode"
            ],
        },
        "primary_gap_decomposition": {
            "no_row_score_primary_docs": {
                "doc_count": no_row_score_profile["doc_count"],
                "pair_group_count": no_row_score_profile["semantic_group_count"],
                "observable_profile": {
                    "similarity_injection_source_distribution": no_row_score_profile[
                        "similarity_injection_source_distribution"
                    ],
                    "time_shift_bucket_distribution": no_row_score_profile[
                        "time_shift_bucket_distribution"
                    ],
                    "amount_similarity_bucket_distribution": no_row_score_profile[
                        "amount_similarity_bucket_distribution"
                    ],
                    "reference_similarity_bucket_distribution": no_row_score_profile[
                        "reference_similarity_bucket_distribution"
                    ],
                    "text_similarity_bucket_distribution": no_row_score_profile[
                        "text_similarity_bucket_distribution"
                    ],
                    "partner_match_ratio": no_row_score_profile["partner_match_ratio"],
                    "same_account_ratio": no_row_score_profile["same_account_ratio"],
                    "same_business_process_ratio": no_row_score_profile[
                        "same_business_process_ratio"
                    ],
                    "row_count_bucket_distribution": no_row_score_profile[
                        "row_count_bucket_distribution"
                    ],
                    "line_amount_bucket_distribution": no_row_score_profile[
                        "line_amount_bucket_distribution"
                    ],
                    "source_distribution": no_row_score_profile["source_distribution"],
                    "process_distribution": no_row_score_profile["process_distribution"],
                    "phase1_action_tier_distribution": no_row_score_profile[
                        "phase1_action_tier_distribution"
                    ],
                },
                "read": (
                    "Primary docs have duplicate-like metadata, but the current "
                    "observable row-score features do not emit duplicate row-score "
                    "hits for this group."
                ),
            },
            "low_score_l2_03d_primary_docs": {
                "doc_count": low_score_profile["doc_count"],
                "pair_group_count": low_score_profile["semantic_group_count"],
                "row_score_hit_row_count": profile["primary_row_score_hit_row_count"],
                "score_floor_gap": score_floor_gap,
                "primary_l2_03d_score": primary_l2_score,
                "candidate_subset_min_score": selected_min,
                "primary_to_candidate_floor_ratio": (
                    primary_l2_score / selected_min
                    if selected_min is not None and primary_l2_score is not None
                    else None
                ),
                "observable_profile": {
                    "time_shift_bucket_distribution": low_score_profile[
                        "time_shift_bucket_distribution"
                    ],
                    "amount_similarity_bucket_distribution": low_score_profile[
                        "amount_similarity_bucket_distribution"
                    ],
                    "reference_similarity_bucket_distribution": low_score_profile[
                        "reference_similarity_bucket_distribution"
                    ],
                    "text_similarity_bucket_distribution": low_score_profile[
                        "text_similarity_bucket_distribution"
                    ],
                    "partner_match_ratio": low_score_profile["partner_match_ratio"],
                    "same_account_ratio": low_score_profile["same_account_ratio"],
                    "same_business_process_ratio": low_score_profile[
                        "same_business_process_ratio"
                    ],
                    "phase1_action_tier_distribution": low_score_profile[
                        "phase1_action_tier_distribution"
                    ],
                },
                "read": (
                    "Primary docs that do receive row scores are all lower-score "
                    "L2-03d time-shifted hits and remain below the large-input "
                    "candidate subset floor."
                ),
            },
        },
        "pair_path_lock": {
            "generated_pair_count": primary["pair_artifact"]["generated_pair_count"],
            "top_pairs_count": primary["pair_artifact"]["top_pairs_count"],
            "generated_primary_doc_count": primary["pair_artifact"][
                "generated_primary_doc_count"
            ],
            "top_pairs_primary_doc_count": primary["pair_artifact"][
                "top_pairs_primary_doc_count"
            ],
            "top_pairs_case_grade_primary_doc_count": primary["pair_artifact"][
                "top_pairs_case_grade_primary_doc_count"
            ],
            "retention_sizes_checked": sorted(
                int(key) for key in primary["retention_diagnostic"]
            ),
            "top_pairs_cap_is_bottleneck": sidecar["top_pairs_cap_is_bottleneck"],
        },
        "sidecar_readiness": {
            "non_oracle_sidecar_pair_feasibility_confirmed": sidecar[
                "non_oracle_sidecar_pair_feasibility_confirmed"
            ],
            "oracle_probe_pair_feasibility_confirmed": sidecar["pair_feasibility_confirmed"],
            "oracle_probe_primary_docs": oracle_probe[
                "generated_pair_evidence_primary_docs"
            ],
            "oracle_probe_case_grade_primary_docs": oracle_probe[
                "case_grade_pair_primary_docs"
            ],
            "oracle_probe_weak_pair_ratio": oracle_probe["weak_pair_ratio"],
            "l2_03d_stratified_primary_docs": non_oracle_l2[
                "generated_pair_evidence_primary_docs"
            ],
            "rule_balanced_primary_docs": non_oracle_rule[
                "generated_pair_evidence_primary_docs"
            ],
            "product_sidecar_adoption_allowed": False,
        },
        "non_oracle_sidecar_failure_profile": {
            "l2_03d_stratified_low_score_sample": {
                "sidecar_candidate_docs": non_oracle_l2["sidecar_candidate_docs"],
                "bounded_row_count": non_oracle_l2["bounded_row_count"],
                "duplicate_primary_docs_entering_sidecar": non_oracle_l2[
                    "duplicate_primary_docs_entering_sidecar"
                ],
                "generated_pair_evidence_primary_docs": non_oracle_l2[
                    "generated_pair_evidence_primary_docs"
                ],
                "case_grade_pair_primary_docs": non_oracle_l2[
                    "case_grade_pair_primary_docs"
                ],
                "rule_id_distribution": non_oracle_l2["rule_id_distribution"],
                "weak_pair_ratio": non_oracle_l2["weak_pair_ratio"],
                "case_grade_pair_ratio": non_oracle_l2["case_grade_pair_ratio"],
            },
            "rule_balanced_duplicate_candidate_sample": {
                "sidecar_candidate_docs": non_oracle_rule["sidecar_candidate_docs"],
                "bounded_row_count": non_oracle_rule["bounded_row_count"],
                "duplicate_primary_docs_entering_sidecar": non_oracle_rule[
                    "duplicate_primary_docs_entering_sidecar"
                ],
                "generated_pair_evidence_primary_docs": non_oracle_rule[
                    "generated_pair_evidence_primary_docs"
                ],
                "case_grade_pair_primary_docs": non_oracle_rule[
                    "case_grade_pair_primary_docs"
                ],
                "rule_id_distribution": non_oracle_rule["rule_id_distribution"],
                "weak_pair_ratio": non_oracle_rule["weak_pair_ratio"],
                "case_grade_pair_ratio": non_oracle_rule["case_grade_pair_ratio"],
            },
            "oracle_probe_contrast": {
                "duplicate_primary_docs_entering_sidecar": oracle_probe[
                    "duplicate_primary_docs_entering_sidecar"
                ],
                "generated_pair_evidence_primary_docs": oracle_probe[
                    "generated_pair_evidence_primary_docs"
                ],
                "case_grade_pair_primary_docs": oracle_probe[
                    "case_grade_pair_primary_docs"
                ],
                "weak_pair_ratio": oracle_probe["weak_pair_ratio"],
                "case_grade_pair_ratio": oracle_probe["case_grade_pair_ratio"],
                "same_partner_ratio": oracle_probe["same_partner_ratio"],
                "usable_as_product_selector": False,
            },
            "read": (
                "Current non-oracle bounded samples select 10,000 candidate docs "
                "but still admit 0 primary docs. The oracle probe proves pair "
                "construction is possible only when truth metadata supplies the "
                "candidate set, so it cannot justify product selection."
            ),
        },
        "decision": {
            "production_first_review_ordering_change": False,
            "row_score_threshold_change": False,
            "top_pairs_cap_expansion": False,
            "weak_pair_promotion": False,
            "truth_metadata_selector": False,
            "next_improvement_class": (
                "row_score_feature_coverage_or_observable_lower_score_pair_path"
            ),
            "next_diagnostic_focus": [
                "why 48 primary docs receive no observable duplicate row score",
                "why 28 L2-03d primary docs remain below the candidate subset floor",
                "whether an oracle-free lower-score pair path can produce case-grade evidence",
            ],
            "read": (
                "Native DuplicateCase primary recall remains pending because v3.1 "
                "duplicate-like primary docs do not reach observable pair evidence. "
                "This is not a top_pairs retention problem."
            ),
        },
        "guardrails": {
            "do_not_use_duplicate_primary_metadata_as_selector": True,
            "do_not_relax_row_score_threshold_for_fixed5": True,
            "do_not_expand_top_pairs_cap_as_primary_fix": True,
            "do_not_promote_weak_pairs_to_duplicate_case": True,
            "preserve_current_first_review_ordering": True,
        },
        "raw_identifier_leak_check": primary["raw_identifier_leak_check"],
    }

    if sidecar_decision != {
        "main_first_review_ordering_change": False,
        "threshold_change": False,
        "weak_pair_promotion": False,
        "top_pairs_cap_expansion": False,
        "next_product_direction": sidecar_decision["next_product_direction"],
    }:
        raise ValueError(f"unexpected sidecar decision shape: {sidecar_decision!r}")
    return payload


def main() -> None:
    OUT_JSON.write_text(
        json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
