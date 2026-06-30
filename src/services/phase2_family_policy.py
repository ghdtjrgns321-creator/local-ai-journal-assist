"""Aggregate-only PHASE2 native family policy constants.

This module is intentionally neutral: inference/dashboard metadata can import
family role labels without importing detector or case-builder implementation
modules. Constants here are descriptive policy metadata, not scoring inputs.
"""

INTERCOMPANY_PRODUCT_ROLE = "ic_specific_evidence_strengthening"
INTERCOMPANY_BROAD_RECALL_EXPANSION_FAMILY = False

RELATIONAL_REVIEW_SURFACE_POLICY = "structural_moderate_audit_then_business_lane_split_v1"
RELATIONAL_REVIEW_SURFACE_NAME = "structural_moderate_audit_then_business_lane_split_surface"
RELATIONAL_PRODUCT_ROLE = "relationship_evidence_review_surface"
RELATIONAL_PRIMARY_DENOMINATOR_STATUS = "pending_relationship_primary_metadata"
RELATIONAL_PRIMARY_TARGET_TRUTH_DOCS_FIXED5_RELMETA = 0
RELATIONAL_PRIMARY_TARGET_MATCHED_DOCS_FIXED5_RELMETA = 0
RELATIONAL_COMPANION_TRUTH_DOCS_FIXED5_V32D = 139
RELATIONAL_COMPANION_MATCHED_DOCS_FIXED5_V32D = 33
RELATIONAL_CO_PRIMARY_OVERLAP_COUNT_FIXED5_RELMETA = 0
RELATIONAL_PRIMARY_METADATA_BACKLOG = (
    "injected_relationship_edge_primary",
    "relationship_edge_semantic_group",
)
RELATIONAL_STRUCTURAL_LANE_SUB_RULES = ("R03", "R07")
RELATIONAL_MODERATE_AUDIT_BUSINESS_LANE_SUB_RULES = ("R01", "R02")
RELATIONAL_CONTEXT_LANE_SUB_RULES = ("R05", "R06")

UNSUPERVISED_COMPANION_POLICY_ID = "unsupervised_document_review_priority_soft_guard_v1"
UNSUPERVISED_COMPANION_SURFACE_NAME = "hybrid_with_soft_repeated_normal_guard"
UNSUPERVISED_DEFAULT_DISPLAY_ORDERING = "document_case_max_score_order"
UNSUPERVISED_PRODUCT_ROLE = "broad_statistical_review_companion_evidence_surface"
UNSUPERVISED_COMPANION_ARTIFACT_PATH = (
    "artifacts/unsupervised_soft_guard_stability_fixed5_20260530.json"
)
UNSUPERVISED_V31_OWNER_SURFACE_ARTIFACT_PATH = (
    "artifacts/unsupervised_v31_owner_surface_fixed5_20260531.json"
)
UNSUPERVISED_ADOPTION_NOTE = (
    "default display ordering uses document-level max-score order with context "
    "fields display-only; q95 gate, VAE score, detector threshold/weight, PHASE1 "
    "ranking, and PHASE2 fusion remain unchanged; case generation intentionally "
    "changed from row cases to document review cases"
)

TIMESERIES_PRODUCT_ROLE = "timing_primary_diagnostic_candidate"
TIMESERIES_NATIVE_ORDERING = "native"
TIMESERIES_STABILIZED_SURFACE = "ts_specific_top100_stabilized_surface"
TIMESERIES_DEFAULT_ORDERING = TIMESERIES_STABILIZED_SURFACE
TIMESERIES_V31_PRIMARY_ARTIFACT_PATH = (
    "artifacts/timeseries_v31_primary_fixed5_ownermeta_ic_20260531.json"
)


def build_relational_policy_summary(relational_cases: tuple[object, ...]) -> dict:
    """Return aggregate-only relational review-surface policy metadata.

    v3.2d does not contain a relationship-primary denominator. That is a
    denominator status, not product-family retirement: the adopted relational
    surface remains the product review surface until relationship-primary or
    co-primary metadata is regenerated and measured.
    """

    return {
        "primary_product_role": RELATIONAL_PRODUCT_ROLE,
        "product_role": RELATIONAL_PRODUCT_ROLE,
        "role_scope": "relationship_review_surface_primary_pending",
        "primary_target_status": RELATIONAL_PRIMARY_DENOMINATOR_STATUS,
        "primary_denominator_status": RELATIONAL_PRIMARY_DENOMINATOR_STATUS,
        "primary_target_recall_applicable": False,
        "primary_recall_pending_reason": (
            "fixed5 v3.2d has no relationship-primary denominator; regenerate "
            "DataSynth relationship-primary/co-primary metadata before owned "
            "recall tuning"
        ),
        "primary_recall_tuning_allowed": False,
        "primary_recall_tuning_blocked_until_metadata": True,
        "primary_target_truth_docs": RELATIONAL_PRIMARY_TARGET_TRUTH_DOCS_FIXED5_RELMETA,
        "primary_target_matched_docs": (RELATIONAL_PRIMARY_TARGET_MATCHED_DOCS_FIXED5_RELMETA),
        "primary_target_recall_fixed5_relmeta": None,
        "co_primary_allowed_by_policy": True,
        "co_primary_with": [],
        "co_primary_overlap_count": RELATIONAL_CO_PRIMARY_OVERLAP_COUNT_FIXED5_RELMETA,
        "adopted_surface": RELATIONAL_REVIEW_SURFACE_POLICY,
        "primary_metadata_backlog": RELATIONAL_PRIMARY_METADATA_BACKLOG,
        "relational_review_surface_policy": RELATIONAL_REVIEW_SURFACE_POLICY,
        "relational_review_surface_name": RELATIONAL_REVIEW_SURFACE_NAME,
        "structural_lane_sub_rules": RELATIONAL_STRUCTURAL_LANE_SUB_RULES,
        "moderate_audit_business_lane_sub_rules": (
            RELATIONAL_MODERATE_AUDIT_BUSINESS_LANE_SUB_RULES
        ),
        "context_lane_sub_rules": RELATIONAL_CONTEXT_LANE_SUB_RULES,
        "interleave_ratio": "1:1",
        "r05_r06_primary_surface_default": False,
        "diagnostic_upper_bound_not_adopted": "structural_anchor_moderate_1_to_4_surface",
        "fixed5_ratio_tuning_allowed": False,
        "production_ranking_changed": False,
        "phase2_fusion_changed": False,
        "phase1_ranking_changed": False,
        "detector_gate_changed": False,
        "relational_gate_changed": False,
        "case_count": len(relational_cases),
        "relationship_companion_coverage_fixed5_v32d": {
            "truth_docs": RELATIONAL_COMPANION_TRUTH_DOCS_FIXED5_V32D,
            "matched_docs": RELATIONAL_COMPANION_MATCHED_DOCS_FIXED5_V32D,
            "recall": (
                RELATIONAL_COMPANION_MATCHED_DOCS_FIXED5_V32D
                / RELATIONAL_COMPANION_TRUTH_DOCS_FIXED5_V32D
            ),
            "metric_role": (
                "interim_relationship_evidence_surface_until_primary_denominator_available"
            ),
        },
        "improvement_focus": (
            "restore and measure relationship-primary/co-primary coverage from "
            "DataSynth metadata; keep R03/R07 structural evidence and R01/R02 "
            "moderate-tail explanation visible until then"
        ),
        "guardrails": {
            "do_not_claim_primary_recall_without_primary_denominator": True,
            "do_not_treat_pending_denominator_as_family_retirement": True,
            "do_not_mix_r05_r06_into_primary_surface": True,
            "do_not_tune_against_fixed5_truth_ratio": True,
            "preserve_audit_then_business_ordering": True,
            "relationship_sidecar_used_for_detector_or_ranking": False,
        },
    }


def build_unsupervised_policy_summary(unsupervised_cases: tuple[object, ...]) -> dict:
    """Return aggregate-only unsupervised companion-surface policy metadata."""

    top_features_available_case_count = sum(
        1 for case in unsupervised_cases if getattr(case, "top_features", ())
    )
    return {
        "primary_product_role": UNSUPERVISED_PRODUCT_ROLE,
        "product_role": UNSUPERVISED_PRODUCT_ROLE,
        "role_scope": "broad_statistical_review_companion",
        "fraud_primary_recall_family": False,
        "primary_recall_metric_role": "diagnostic_only_not_product_judgement",
        "native_row_ordering_changed": True,
        "production_default_ranking_changed": False,
        "production_adoption": True,
        "adoption_candidate": False,
        "recommended_surface": UNSUPERVISED_DEFAULT_DISPLAY_ORDERING,
        "default_display_ordering": UNSUPERVISED_DEFAULT_DISPLAY_ORDERING,
        "case_generation_changed": True,
        "case_generation_change": "row_case_to_document_case",
        "ordering_context_policy": {
            "ordering_layer_uses_document_context": False,
            "used_context_fields": (),
            "context_fields_display_only": True,
            "detector_score_weight_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "overlay_context_used_for_primary_queue": False,
        },
        "evidence_quality_ready": True,
        "evidence_quality_improved": True,
        "top_features_connected": True,
        "q95_gate_change_recommended": False,
        "adoption_note": UNSUPERVISED_ADOPTION_NOTE,
        "case_count": len(unsupervised_cases),
        "top_features_available_case_count": top_features_available_case_count,
        "optional_companion_surface": {
            "policy_id": UNSUPERVISED_COMPANION_POLICY_ID,
            "surface_name": UNSUPERVISED_COMPANION_SURFACE_NAME,
            "artifact_path": UNSUPERVISED_COMPANION_ARTIFACT_PATH,
            "v31_owner_surface_artifact_path": (UNSUPERVISED_V31_OWNER_SURFACE_ARTIFACT_PATH),
            "adoption_state": "historical_diagnostic_not_current_default",
            "descriptor_only": True,
            "replaces_native_case_ordering": False,
            "top_features_used_for_ranking": False,
            "p5_pressure_watchpoint": (
                "document_case_top500_pressure_spike_measurement_first_followup_required"
            ),
            "aggregate_counts": {
                "native_top500_truth_docs_fixed5": 39,
                "recommended_surface_top500_truth_docs_fixed5": 151,
                "fixed5_slice_top500_ge_native": "74/74",
                "fixed5_slice_pressure_below_native": "65/74",
            },
        },
        "product_judgement_metrics": {
            "broad_statistical_review_contribution": {
                "native_top500_truth_docs_fixed5": 39,
                "recommended_surface_top500_truth_docs_fixed5": 151,
                "metric_role": "review_contribution_not_fraud_primary_recall",
            },
            "repeated_normal_pressure": {
                "native_top500_fixed5": 0.716,
                "recommended_surface_top500_fixed5": 0.256,
                "interpretation": "lower_is_better_review_burden_guardrail",
            },
            "outside_phase1_complement": {
                "top500_phase1_immediate_review_outside_truth_docs": 95,
                "top500_phase1_review_or_above_outside_truth_docs": 64,
                "top500_phase1_candidate_or_above_outside_truth_docs": 11,
                "metric_role": "phase1_complement_not_exception_confirmation",
            },
            "evidence_explainability": {
                "top_features_connected": True,
                "top_features_used_for_ranking": False,
            },
        },
        "native_top500_truth_docs_fixed5": 39,
        "recommended_surface_top500_truth_docs_fixed5": 151,
        "native_repeated_normal_pressure_fixed5": 0.716,
        "recommended_surface_repeated_normal_pressure_fixed5": 0.256,
        "fixed5_slice_top500_ge_native": "74/74",
        "fixed5_slice_pressure_below_native": "65/74",
        "responsibility_target": {
            "primary_target_status": "debug_only_historical_v31_not_product_goal",
            "primary_target_metric_role": "debug_only_not_fraud_primary_recall",
            "primary_target_truth_docs_fixed5": 168,
            "primary_target_source": ("historical v3.1 fictitious-entry statistical diagnostic"),
            "primary_target_product_goal": False,
            "must_capture_statistical_primary_40_by_vae": False,
            "companion_target_truth_docs_fixed5": 339,
            "native_row_queue_top100_primary_docs_fixed5": 12,
            "soft_guard_top100_primary_docs_fixed5": 24,
            "native_row_queue_top500_primary_docs_fixed5": 23,
            "soft_guard_top500_primary_docs_fixed5": 110,
            "soft_guard_phase1_immediate_outside_top500_primary_docs_fixed5": 110,
            "soft_guard_phase1_review_or_above_outside_top500_primary_docs_fixed5": 74,
            "soft_guard_phase1_candidate_or_above_outside_top500_primary_docs_fixed5": 73,
            "native_row_queue_top500_companion_docs_fixed5": 34,
            "soft_guard_top500_companion_docs_fixed5": 33,
            "soft_guard_phase1_immediate_outside_top500_companion_docs_fixed5": 33,
            "soft_guard_phase1_review_or_above_outside_top500_companion_docs_fixed5": 32,
            "soft_guard_phase1_candidate_or_above_outside_top500_companion_docs_fixed5": 25,
        },
        "v31_adoption_readiness": {
            "default_native_ordering_unchanged": False,
            "soft_guard_role": ("historical_document_review_priority_diagnostic"),
            "product_default_adoption": False,
            "primary_top500_lift_vs_native": 87,
            "primary_lift_metric_role": "debug_only_historical_v31",
            "companion_top500_lift_vs_native": -1,
            "companion_top500_improved": False,
            "readiness_artifact_path": UNSUPERVISED_V31_OWNER_SURFACE_ARTIFACT_PATH,
            "monitoring_guardrails": (
                "repeated-normal pressure requires monitoring",
                "period-end normal background requires monitoring",
                "account/process concentration requires monitoring",
                "single-row high amount normal proxy requires monitoring",
                "companion TOP500 does not improve",
            ),
        },
        "pressure_monitoring": {
            "repeated_normal_pressure": "monitor",
            "period_end_normal_background": "monitor",
            "account_process_concentration": "monitor",
            "single_row_high_amount_normal_proxy": "monitor",
            "v31_primary_native_repeated_normal_pressure_top500": 0.818,
            "v31_primary_soft_guard_repeated_normal_pressure_top500": 0.336,
            "v31_primary_soft_guard_period_end_normal_background_top500": 0.578,
            "v31_primary_soft_guard_account_top1_share_top500": (0.14396887159533073),
            "v31_primary_soft_guard_process_top1_share_top500": (0.35797665369649806),
            "v31_primary_soft_guard_single_row_high_amount_normal_proxy_top500": 0.0,
        },
        "q95_backlog_policy": {
            "near_miss_promoted_to_case": False,
            "tracking_role": "future_validation_backlog",
        },
        "anti_fitting_guardrails": {
            "hybrid_upper_bound_default_adoption": False,
            "q95_gate_relaxation": False,
            "vae_score_threshold_recall_fitting": False,
            "threshold_or_weight_recall_fitting": False,
            "top_features_used_for_ranking": False,
            "phase1_prior_disguised_as_vae": False,
            "datasynth_changed_to_match_vae_score": False,
            "truth_owner_scenario_shortcut_feature_allowed": False,
            "truth_or_owner_metadata_used_as_selector": False,
        },
    }


def build_timeseries_policy_summary(timeseries_cases: tuple[object, ...]) -> dict:
    """Return aggregate-only TS-primary diagnostic surface policy metadata."""

    return {
        "primary_product_role": TIMESERIES_PRODUCT_ROLE,
        "production_adoption": True,
        "production_default_ordering_changed": True,
        "native_ordering_changed": True,
        "explicit_ordering_flag_available": True,
        "default_ordering_strategy": TIMESERIES_DEFAULT_ORDERING,
        "native_ordering_fallback": True,
        "candidate_ordering_strategy": TIMESERIES_STABILIZED_SURFACE,
        "candidate_surface": TIMESERIES_STABILIZED_SURFACE,
        "v31_primary_artifact_path": TIMESERIES_V31_PRIMARY_ARTIFACT_PATH,
        "case_count": len(timeseries_cases),
        "v31_primary_target": {
            "truth_docs": 21,
            "period_end_context_docs": 92,
            "native_top100_matched_docs": 0,
            "native_top500_matched_docs": 0,
            "candidate_top100_matched_docs": 21,
            "candidate_top500_matched_docs": 21,
            "phase1_immediate_high_covered_docs": 0,
            "phase1_review_or_higher_covered_docs": 2,
            "phase1_candidate_or_higher_covered_docs": 21,
        },
        "context_target": {
            "period_end_context_docs": 92,
            "used_as_primary_denominator": False,
            "broad_companion_used_as_ts_primary": False,
        },
        "selector_input_policy": {
            "truth_label_used": False,
            "scenario_label_used": False,
            "phase1_rank_used": False,
            "raw_identifier_used": False,
            "matched_result_used": False,
            "features": [
                "period_end_context",
                "row_ref_support_count",
                "round_amount_context",
                "after_hours_or_weekend_context",
                "context_evidence_count",
                "period_end_lift",
                "robust_z",
                "subject_activity_rank",
            ],
        },
        "guardrails": {
            "threshold_changed": False,
            "detector_gate_changed": False,
            "phase2_fusion_changed": False,
            "phase1_ranking_changed": False,
            "broad_companion_used_as_ts_primary": False,
        },
        "adoption_readiness": {
            "status": "product_default_ordering_adopted",
            "product_default_ordering_strategy": TIMESERIES_DEFAULT_ORDERING,
            "candidate_ordering_strategy": TIMESERIES_STABILIZED_SURFACE,
            "explicit_flag_required": False,
            "product_default_adoption_allowed": True,
            "native_fallback_strategy": TIMESERIES_NATIVE_ORDERING,
            "period_end_context_primary_denominator": False,
            "fixed4_used_for_product_judgment": False,
            "required_validation_before_default": {
                "regenerated_owner_metadata_datasynth": {
                    "required": True,
                    "minimum_primary_docs": 21,
                    "required_top100_primary_capture": 21,
                    "required_top500_primary_capture": 21,
                    "period_end_context_denominator_allowed": False,
                },
                "fixed5_compatible_slice_validation": {
                    "required": True,
                    "each_slice_top500_capture_must_equal_primary_docs": True,
                    "top100_slice_regression_requires_review": True,
                    "must_not_use_fixed4": True,
                },
                "selector_contract": {
                    "truth_label_allowed": False,
                    "scenario_label_allowed": False,
                    "owner_metadata_allowed": False,
                    "phase1_rank_allowed": False,
                    "matched_result_allowed": False,
                    "raw_identifier_allowed": False,
                },
            },
            "post_adoption_monitoring": [
                "single fixed5 owner-metadata candidate validation only",
                (
                    "requires regenerated owner-metadata DataSynth or fixed5-compatible "
                    "slice validation after default adoption"
                ),
                "must keep period-end context docs out of TS primary denominator",
            ],
        },
    }


__all__ = [
    "INTERCOMPANY_BROAD_RECALL_EXPANSION_FAMILY",
    "INTERCOMPANY_PRODUCT_ROLE",
    "RELATIONAL_CONTEXT_LANE_SUB_RULES",
    "RELATIONAL_MODERATE_AUDIT_BUSINESS_LANE_SUB_RULES",
    "RELATIONAL_CO_PRIMARY_OVERLAP_COUNT_FIXED5_RELMETA",
    "RELATIONAL_PRIMARY_DENOMINATOR_STATUS",
    "RELATIONAL_PRIMARY_METADATA_BACKLOG",
    "RELATIONAL_PRIMARY_TARGET_MATCHED_DOCS_FIXED5_RELMETA",
    "RELATIONAL_PRIMARY_TARGET_TRUTH_DOCS_FIXED5_RELMETA",
    "RELATIONAL_PRODUCT_ROLE",
    "RELATIONAL_REVIEW_SURFACE_NAME",
    "RELATIONAL_REVIEW_SURFACE_POLICY",
    "RELATIONAL_COMPANION_MATCHED_DOCS_FIXED5_V32D",
    "RELATIONAL_COMPANION_TRUTH_DOCS_FIXED5_V32D",
    "RELATIONAL_STRUCTURAL_LANE_SUB_RULES",
    "TIMESERIES_NATIVE_ORDERING",
    "TIMESERIES_DEFAULT_ORDERING",
    "TIMESERIES_PRODUCT_ROLE",
    "TIMESERIES_STABILIZED_SURFACE",
    "TIMESERIES_V31_PRIMARY_ARTIFACT_PATH",
    "UNSUPERVISED_ADOPTION_NOTE",
    "UNSUPERVISED_COMPANION_ARTIFACT_PATH",
    "UNSUPERVISED_COMPANION_POLICY_ID",
    "UNSUPERVISED_COMPANION_SURFACE_NAME",
    "UNSUPERVISED_PRODUCT_ROLE",
    "UNSUPERVISED_V31_OWNER_SURFACE_ARTIFACT_PATH",
    "build_relational_policy_summary",
    "build_timeseries_policy_summary",
    "build_unsupervised_policy_summary",
]
