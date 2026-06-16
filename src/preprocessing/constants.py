"""Preprocessing constants shared across training paths."""

from __future__ import annotations

LABEL_COLUMNS = frozenset(
    {
        "is_fraud",
        "fraud_type",
        "is_anomaly",
        "anomaly_type",
        "sod_violation",
        "sod_conflict_type",
        "label",
        "target",
    }
)

# DataSynth-only columns. Real customer CSVs never contain these, so they must
# not appear in raw-data previews, mapping selectboxes, or recommended-mapping
# warnings. Composed of (a) truth labels and (b) manipulation sidecar metadata.
SYNTHETIC_ONLY_COLUMNS = LABEL_COLUMNS | frozenset(
    {
        "mutation_base_event_type",
        "mutation_type",
        "mutation_mutated_field",
        "mutation_original_value",
        "mutation_mutated_value",
        "mutation_reason",
        "detection_surface_hints",
        "is_mutated",
        "is_synthetic",
        "semantic_scenario_id",
    }
)

# Stage 1 leakage deny-list: DataSynth truth sidecar and identifier-only leak columns.
# Confirmed by Stage 0 AUROC >= 0.95, explicit mutation metadata denies, and residual audit.
LEAKAGE_DENY_COLUMNS_BASE = frozenset(
    {
        "detection_surface_hints",
        "document_id",
        "document_number",
        "header_text",
        "ip_address",
        "is_mutated",
        "is_synthetic",
        "mutation_base_event_type",
        "mutation_mutated_field",
        "mutation_mutated_value",
        "mutation_original_value",
        "mutation_reason",
        "mutation_type",
        "reference",
        "semantic_scenario_id",
    }
)

# DataSynth manipulation V6 baseline limitation.
# Source: artifacts/datasynth_v6_phase2_cheat_route_audit.md
# These columns encode synthetic manipulation mechanics or deterministic
# enrichment tails. They are denied for PHASE2 training until a later generator
# version proves each column has non-shortcut real-data-like overlap.
LEAKAGE_DENY_COLUMNS_V6_BASELINE = frozenset(
    {
        # amount-related: synthetic manipulation scenarios still separate too cleanly
        "amount_magnitude",
        "amount_zscore",
        "credit_amount",
        "debit_amount",
        "document_approval_amount",
        "invoice_amount",
        "local_amount",
        "near_threshold_amount",
        "supply_amount",
        "tax_amount",
        # approval/anachronism-related: intended manipulation timing signals
        "approval_after_30d",
        "approval_before_posting",
        "approval_date_null",
        "approval_excess_amount",
        "approval_lag_abs",
        "approval_lag_days",
        "approval_level",
        "approval_limit_exceeded_independent",
        "exceeds_threshold",
        # scenario-specific synthetic surfaces
        "approval_contract_gap",
        "approval_matrix_gap",
        "days_backdated",
        "first_digit",
        "has_revenue_line",
        "is_intercompany",
        "is_round_number",
        "is_suspense_account",
        "master_counterparty_intercompany",
        "near_threshold_ratio_to_limit",
        "self_approval",
    }
)

# DataSynth manipulation V7 phase2 cheat-route residuals.
# Source: artifacts/datasynth_v7_phase2_cheat_route_audit.md
# These are derived near-threshold/approval-limit or technical line-position
# features that let a supervised probe recover synthetic truth after the V6
# baseline deny-list is applied.
LEAKAGE_DENY_COLUMNS_V7_DERIVED = frozenset(
    {
        "approver_can_approve_je",
        "approver_limit_amount",
        "line_number",
        "near_threshold_gap_amount",
        "near_threshold_gap_ratio",
        "near_threshold_limit_amount",
    }
)

LEAKAGE_DENY_COLUMNS = (
    LEAKAGE_DENY_COLUMNS_BASE | LEAKAGE_DENY_COLUMNS_V6_BASELINE | LEAKAGE_DENY_COLUMNS_V7_DERIVED
)

# Stage 5 concentration risk — deterministic Top-5 rule columns are removed
# from ML training inputs to block circular shortcut learning. Rules remain
# available to PHASE1 score_aggregator / PHASE3 narrator.
#
# Stage 5 v4 rerun (artifacts/manipulation_v4_audit_rerun_summary_20260516.md):
# 24-dim AUPRC 0.397, Top-5 deny 후 0.056 (잔존 14.0%, drop ratio 0.86).
# v3 에서 강했던 L1-09, L2-02 는 v4 shortcut noise 로 약화되어 deny 에서 제외.
LEAKAGE_DENY_RULES = frozenset(
    {
        "rule_L3-02",  # 수기 전표 (v4 univariate AUPRC 0.1472)
        "rule_L3-09",  # (v4 신규 진입, AUPRC 0.1282)
        "rule_L1-03",  # (v4 신규 진입, AUPRC 0.0827)
        "rule_L2-03",  # 중복 지급 (v4 AUPRC 0.0532)
        "rule_L1-05",  # 자기 승인 (v4 AUPRC 0.0422)
    }
)

DEFAULT_GROUND_TRUTH_LABEL_COLUMNS = (
    "is_fraud",
    "is_anomaly",
)
