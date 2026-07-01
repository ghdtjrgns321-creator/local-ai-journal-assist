"""Rule detail metadata v1 registry and accessors.

This module is intentionally independent from scoring execution.  It provides
the locked v1 metadata contract used to decide canonical rule identity, row
detail eligibility, display surface, and column-source policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml


class RuleStatus(StrEnum):
    """Locked v1 metadata status values."""

    ACTIVE = "active"
    MACRO = "macro"
    SIDECAR = "sidecar"
    ALIAS = "alias"
    INTERNAL_REASON_CODE = "internal_reason_code"


class PresenterSurface(StrEnum):
    """Locked v1 presentation surfaces."""

    TRANSACTION_DETAIL = "transaction_detail"
    CONTEXT_BADGE = "context_badge"
    ACCOUNT_PROCESS_MACRO = "account_process_macro"
    INTERCOMPANY_SIDECAR = "intercompany_sidecar"
    GRAPH_SIDECAR = "graph_sidecar"
    DRILLDOWN_REASON = "drilldown_reason"


class ScoringRole(StrEnum):
    """Locked v1 scoring roles."""

    PRIMARY = "primary"
    BOOSTER = "booster"
    COMBO_ONLY = "combo_only"
    MACRO_ONLY = "macro_only"


@dataclass(frozen=True)
class ColumnSources:
    """Split ledger inputs from derived, sidecar, and macro outputs."""

    required_ledger_columns: tuple[str, ...] = field(default_factory=tuple)
    optional_ledger_columns: tuple[str, ...] = field(default_factory=tuple)
    derived_columns: tuple[str, ...] = field(default_factory=tuple)
    sidecar_output_columns: tuple[str, ...] = field(default_factory=tuple)
    macro_output_columns: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DisplayCopy:
    """Compact display guidance from the v1 lock and Context B."""

    display_title: str
    user_question: str = ""
    review_guidance: str = ""
    display_tone: str = ""


@dataclass(frozen=True)
class RuleDetailMetadata:
    """Minimal frozen v1 rule detail metadata entry."""

    rule_id: str
    canonical_rule_id: str
    status: RuleStatus
    presenter_surface: PresenterSurface
    final_topic: str | None
    secondary_topics: tuple[str, ...]
    scoring_role: ScoringRole
    standalone_rankable: bool
    include_in_l1_l4_transaction_count: bool
    allow_row_violation_detail: bool
    allow_standalone_violation_copy: bool
    allow_topic_seed: bool
    display_copy: DisplayCopy
    column_sources: ColumnSources
    conflict_note: str = ""


LOCKED_TOPICS = frozenset(
    {
        "ledger_integrity",
        "approval_control",
        "closing_timing",
        "account_logic",
        "duplicate_outflow",
        "intercompany_cycle",
        "revenue_statistical",
    }
)

CANONICALIZATION_MAP = {
    "L2-03a": "L2-03",
    "L2-03b": "L2-03",
    "L2-03c": "L2-03",
    "L2-03d": "L2-03",
    "Benford": "L4-02",
}

LOCKED_NO_STANDALONE_COPY_RULE_IDS = frozenset(
    {"L3-05", "L3-06", "L3-10", "L3-12", "L4-05", "L4-06"}
)
LOCKED_CONTEXT_ROW_DETAIL_RULE_IDS = frozenset(
    {"L3-03", "L3-05", "L3-06", "L3-10", "L3-12", "L4-05", "L4-06"}
)

CANONICAL_TRANSACTION_RULE_IDS = (
    "L1-01",
    "L1-02",
    "L1-03",
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L1-08",
    "L1-07-02",
    "L2-01",
    "L2-02",
    "L2-03",
    "L2-04",
    "L2-05",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L3-09",
    "L3-10",
    "L3-11",
    "L3-12",
    "L4-01",
    # L4-02 제거 (2026-06-15): macro(Benford 모집단 자릿수 분포)는 전표 단위 PHASE1-1 룰이
    # 아니라 PHASE1-2 family 로 이관. 2026-06-20 폐기 룰까지 반영해 count 30.
    "L4-03",
    "L4-04",
    "L4-05",
    "L4-06",
)

_ROW_DETAIL_RULE_IDS = frozenset(
    {
        "L1-01",
        "L1-02",
        "L1-03",
        "L1-04",
        "L1-05",
        "L1-06",
        "L1-07",
        "L1-08",
        "L1-07-02",
        "L2-01",
        "L2-02",
        "L2-03",
        "L2-04",
        "L2-05",
        "L3-02",
        "L3-04",
        "L3-07",
        "L3-09",
        "L3-11",
        "L4-01",
        "L4-03",
        "L4-04",
    }
)


def _display(rule_id: str, title: str, tone: str) -> DisplayCopy:
    return DisplayCopy(
        display_title=title,
        user_question=f"What should be reviewed for {rule_id}?",
        review_guidance=f"Use {rule_id} metadata as the v1 display contract.",
        display_tone=tone,
    )


def _columns(
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
    derived: tuple[str, ...] = (),
    sidecar: tuple[str, ...] = (),
    macro: tuple[str, ...] = (),
) -> ColumnSources:
    return ColumnSources(
        required_ledger_columns=required,
        optional_ledger_columns=optional,
        derived_columns=derived,
        sidecar_output_columns=sidecar,
        macro_output_columns=macro,
    )


def _transaction_columns(*extra_required: str, derived: tuple[str, ...] = ()) -> ColumnSources:
    return _columns(
        ("document_id", "company_code", "posting_date", *extra_required),
        (
            "document_type",
            "gl_account",
            "debit_amount",
            "credit_amount",
            "created_by",
            "approved_by",
            "source",
            "business_process",
            "line_text",
            "reference",
        ),
        ("amount", "evidence_summary", "violation_details", *derived),
    )


def _entry(
    rule_id: str,
    *,
    canonical_rule_id: str | None = None,
    status: RuleStatus = RuleStatus.ACTIVE,
    presenter_surface: PresenterSurface = PresenterSurface.TRANSACTION_DETAIL,
    final_topic: str | None,
    secondary_topics: tuple[str, ...] = (),
    scoring_role: ScoringRole = ScoringRole.PRIMARY,
    standalone_rankable: bool = True,
    include_in_l1_l4_transaction_count: bool | None = None,
    allow_row_violation_detail: bool | None = None,
    allow_standalone_violation_copy: bool | None = None,
    allow_topic_seed: bool | None = None,
    title: str | None = None,
    tone: str = "direct_review",
    column_sources: ColumnSources | None = None,
    conflict_note: str = "",
) -> RuleDetailMetadata:
    canonical = canonical_rule_id or rule_id
    if include_in_l1_l4_transaction_count is None:
        include_in_l1_l4_transaction_count = canonical in CANONICAL_TRANSACTION_RULE_IDS and (
            rule_id == canonical
        )
    if allow_row_violation_detail is None:
        allow_row_violation_detail = (
            presenter_surface == PresenterSurface.TRANSACTION_DETAIL
            and rule_id in _ROW_DETAIL_RULE_IDS
        )
    if allow_standalone_violation_copy is None:
        allow_standalone_violation_copy = allow_row_violation_detail
    if allow_topic_seed is None:
        allow_topic_seed = standalone_rankable or presenter_surface in {
            PresenterSurface.INTERCOMPANY_SIDECAR,
            PresenterSurface.ACCOUNT_PROCESS_MACRO,
        }
    return RuleDetailMetadata(
        rule_id=rule_id,
        canonical_rule_id=canonical,
        status=status,
        presenter_surface=presenter_surface,
        final_topic=final_topic,
        secondary_topics=secondary_topics,
        scoring_role=scoring_role,
        standalone_rankable=standalone_rankable,
        include_in_l1_l4_transaction_count=include_in_l1_l4_transaction_count,
        allow_row_violation_detail=allow_row_violation_detail,
        allow_standalone_violation_copy=allow_standalone_violation_copy,
        allow_topic_seed=allow_topic_seed,
        display_copy=_display(rule_id, title or rule_id, tone),
        column_sources=column_sources or _transaction_columns(),
        conflict_note=conflict_note,
    )


RULE_DETAIL_METADATA_REGISTRY: dict[str, RuleDetailMetadata] = {
    "L1-01": _entry(
        "L1-01",
        final_topic="ledger_integrity",
        title="Unbalanced entry",
        column_sources=_transaction_columns(
            "gl_account",
            "debit_amount",
            "credit_amount",
            derived=("imbalance_amount", "debit_sum", "credit_sum"),
        ),
    ),
    "L1-02": _entry(
        "L1-02",
        final_topic="ledger_integrity",
        title="Missing required information",
        column_sources=_transaction_columns(
            "fiscal_year",
            "fiscal_period",
            "document_date",
            "document_type",
            "gl_account",
            "debit_amount",
            "credit_amount",
            derived=("missing_fields", "missing_category"),
        ),
    ),
    "L1-03": _entry(
        "L1-03",
        final_topic="account_logic",
        title="Invalid account usage",
        column_sources=_transaction_columns(
            "document_type",
            "gl_account",
        ),
    ),
    "L1-04": _entry(
        "L1-04",
        final_topic="approval_control",
        title="Approval limit exceeded",
        column_sources=_transaction_columns(
            "created_by",
            "approved_by",
            "business_process",
            derived=("approval_limit", "difference_value", "display_label"),
        ),
    ),
    "L1-05": _entry(
        "L1-05",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        title="Self approval",
        column_sources=_transaction_columns(
            "created_by",
            "approved_by",
            "source",
            "business_process",
            derived=("display_label", "signal_strength"),
        ),
    ),
    "L1-06": _entry(
        "L1-06",
        final_topic="approval_control",
        title="Segregation of duties conflict",
        column_sources=_transaction_columns(
            "created_by",
            "business_process",
            "sod_violation",
            "sod_conflict_type",
            derived=("display_label", "signal_strength"),
        ),
        conflict_note="Separated from L3-12 work-scope context review.",
    ),
    "L1-07": _entry(
        "L1-07",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        allow_topic_seed=False,
        title="Approval bypass",
        column_sources=_transaction_columns(
            "created_by",
            "approved_by",
            "source",
            "business_process",
            derived=("display_label", "signal_status"),
        ),
        conflict_note=(
            "Case seeder authority revoked (§9.1 light_seeder audit 2026-05-14). "
            "Retains standalone_rankable + topic_score contribution as corroborating evidence."
        ),
    ),
    "L1-08": _entry(
        "L1-08",
        final_topic="closing_timing",
        secondary_topics=("ledger_integrity",),
        title="Fiscal period mismatch",
        column_sources=_transaction_columns(
            "fiscal_year",
            "fiscal_period",
            "document_date",
            derived=("expected_value", "actual_value", "difference_value"),
        ),
        conflict_note="Final topic locked to closing_timing for v1.",
    ),
    "L1-07-02": _entry(
        "L1-07-02",
        final_topic="approval_control",
        title="Unknown approver",
        column_sources=_transaction_columns(
            "created_by",
            "approved_by",
            "source",
            derived=("approver_in_master", "display_label"),
        ),
    ),
    "L2-01": _entry(
        "L2-01",
        final_topic="duplicate_outflow",
        secondary_topics=("approval_control",),
        title="Near-threshold approval pattern",
        column_sources=_transaction_columns(
            "created_by",
            "approved_by",
            "business_process",
            derived=("approval_limit", "difference_value", "anomaly_score"),
        ),
    ),
    "L2-02": _entry(
        "L2-02",
        final_topic="duplicate_outflow",
        title="Duplicate payment signal",
        column_sources=_transaction_columns(
            "reference",
            "auxiliary_account_number",
            "auxiliary_account_label",
            "debit_amount",
            "credit_amount",
            derived=("counterparty", "duplicate_group_id"),
        ),
    ),
    "L2-03": _entry(
        "L2-03",
        final_topic="duplicate_outflow",
        title="Duplicate document signal",
        column_sources=_transaction_columns(
            "document_number",
            "reference",
            "gl_account",
            "source",
            derived=("counterparty", "duplicate_signature", "duplicate_group_id"),
        ),
        conflict_note="L2-03a-d are internal reason codes under this rule.",
    ),
    "L2-03a": _entry(
        "L2-03a",
        canonical_rule_id="L2-03",
        status=RuleStatus.INTERNAL_REASON_CODE,
        presenter_surface=PresenterSurface.DRILLDOWN_REASON,
        final_topic="duplicate_outflow",
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        allow_topic_seed=False,
        title="Exact duplicate reason",
        tone="drilldown_only",
        column_sources=_columns((), derived=("internal_reason_code", "duplicate_signature")),
        conflict_note="Internal reason code, not a standalone rule.",
    ),
    "L2-03b": _entry(
        "L2-03b",
        canonical_rule_id="L2-03",
        status=RuleStatus.INTERNAL_REASON_CODE,
        presenter_surface=PresenterSurface.DRILLDOWN_REASON,
        final_topic="duplicate_outflow",
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        allow_topic_seed=False,
        title="Similar duplicate reason",
        tone="drilldown_only",
        column_sources=_columns((), derived=("internal_reason_code", "similarity_score")),
        conflict_note="Internal reason code, not a standalone rule.",
    ),
    "L2-03c": _entry(
        "L2-03c",
        canonical_rule_id="L2-03",
        status=RuleStatus.INTERNAL_REASON_CODE,
        presenter_surface=PresenterSurface.DRILLDOWN_REASON,
        final_topic="duplicate_outflow",
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        allow_topic_seed=False,
        title="Split candidate reason",
        tone="drilldown_only",
        column_sources=_columns((), derived=("internal_reason_code", "split_group_id")),
        conflict_note="Internal reason code, not a standalone rule.",
    ),
    "L2-03d": _entry(
        "L2-03d",
        canonical_rule_id="L2-03",
        status=RuleStatus.INTERNAL_REASON_CODE,
        presenter_surface=PresenterSurface.DRILLDOWN_REASON,
        final_topic="duplicate_outflow",
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        allow_topic_seed=False,
        title="Sequential duplicate reason",
        tone="drilldown_only",
        column_sources=_columns((), derived=("internal_reason_code", "sequential_group_id")),
        conflict_note="Internal reason code, not a standalone rule.",
    ),
    "L2-04": _entry(
        "L2-04",
        final_topic="account_logic",
        title="Expense or asset account mismatch",
        column_sources=_transaction_columns(
            "document_type",
            "gl_account",
            "business_process",
            derived=("amount", "account_family", "display_label", "signal_status"),
        ),
    ),
    "L2-05": _entry(
        "L2-05",
        final_topic="duplicate_outflow",
        title="Reversal or offset pattern",
        column_sources=_transaction_columns(
            "reference",
            "lettrage",
            "lettrage_date",
            "gl_account",
            derived=("counterparty", "reversal_pair_id", "difference_value"),
        ),
    ),
    "L3-02": _entry(
        "L3-02",
        final_topic="approval_control",
        title="Manual journal entry",
        column_sources=_transaction_columns(
            "source",
            "created_by",
            "business_process",
            "document_type",
            derived=("display_label", "signal_status"),
        ),
    ),
    "L3-03": _entry(
        "L3-03",
        presenter_surface=PresenterSurface.CONTEXT_BADGE,
        final_topic="intercompany_cycle",
        secondary_topics=("account_logic",),
        scoring_role=ScoringRole.BOOSTER,
        standalone_rankable=False,
        allow_row_violation_detail=True,
        allow_standalone_violation_copy=False,
        title="Intercompany transaction context",
        tone="context_only",
        column_sources=_transaction_columns(
            "trading_partner",
            "auxiliary_account_number",
            "gl_account",
            derived=("counterparty", "intercompany_pair", "signal_status"),
        ),
        conflict_note="Context badge only; not standalone violation copy.",
    ),
    "L3-04": _entry(
        "L3-04",
        final_topic="closing_timing",
        title="Period-end or period-start posting",
        column_sources=_transaction_columns(
            "fiscal_period",
            "source",
            "created_by",
            "gl_account",
            derived=("is_period_end", "display_label"),
        ),
    ),
    "L3-05": _entry(
        "L3-05",
        presenter_surface=PresenterSurface.CONTEXT_BADGE,
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        scoring_role=ScoringRole.BOOSTER,
        standalone_rankable=False,
        allow_row_violation_detail=True,
        allow_standalone_violation_copy=False,
        title="Non-business-day posting context",
        tone="context_only",
        column_sources=_transaction_columns(
            "created_by",
            "source",
            "business_process",
            derived=("is_non_workday", "holiday_flag", "signal_status"),
        ),
        conflict_note="Locked context rule; standalone copy forbidden.",
    ),
    "L3-06": _entry(
        "L3-06",
        presenter_surface=PresenterSurface.CONTEXT_BADGE,
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        scoring_role=ScoringRole.BOOSTER,
        standalone_rankable=False,
        allow_row_violation_detail=True,
        allow_standalone_violation_copy=False,
        title="After-hours posting context",
        tone="context_only",
        column_sources=_transaction_columns(
            "created_by",
            "source",
            "business_process",
            derived=("posting_hour", "after_hours_flag", "signal_status"),
        ),
        conflict_note="Locked context rule; standalone copy forbidden.",
    ),
    "L3-07": _entry(
        "L3-07",
        final_topic="closing_timing",
        title="Posting and document date gap",
        column_sources=_transaction_columns(
            "document_date",
            "created_by",
            "reference",
            derived=("date_gap_days", "difference_value", "display_label"),
        ),
    ),
    "L3-09": _entry(
        "L3-09",
        final_topic="account_logic",
        title="Aged suspense account",
        column_sources=_transaction_columns(
            "gl_account",
            "lettrage",
            "lettrage_date",
            derived=("account_family", "aging_days", "unresolved_flag"),
        ),
    ),
    "L3-10": _entry(
        "L3-10",
        presenter_surface=PresenterSurface.CONTEXT_BADGE,
        final_topic="account_logic",
        secondary_topics=("approval_control", "revenue_statistical"),
        scoring_role=ScoringRole.BOOSTER,
        standalone_rankable=False,
        allow_row_violation_detail=True,
        allow_standalone_violation_copy=False,
        title="Sensitive account context",
        tone="context_only",
        column_sources=_transaction_columns(
            "gl_account",
            "created_by",
            "approved_by",
            "source",
            derived=("match_type", "matched_value", "matched_group"),
        ),
        conflict_note="Locked context rule; standalone copy forbidden.",
    ),
    "L3-11": _entry(
        "L3-11",
        final_topic="closing_timing",
        title="Revenue cutoff mismatch",
        column_sources=_transaction_columns(
            "document_date",
            "delivery_date",
            "gl_account",
            "reference",
            derived=("date_gap_days", "cutoff_window", "difference_value"),
        ),
    ),
    "L3-12": _entry(
        "L3-12",
        presenter_surface=PresenterSurface.CONTEXT_BADGE,
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        scoring_role=ScoringRole.COMBO_ONLY,
        standalone_rankable=False,
        allow_row_violation_detail=True,
        allow_standalone_violation_copy=False,
        title="Work-scope concentration context",
        tone="context_only",
        column_sources=_transaction_columns(
            "created_by",
            "business_process",
            "gl_account",
            derived=("work_scope_score", "company_count", "process_count"),
        ),
        conflict_note="Review context only; separated from L1-06 direct SoD.",
    ),
    "L4-01": _entry(
        "L4-01",
        final_topic="revenue_statistical",
        title="Revenue variance outlier",
        column_sources=_transaction_columns(
            "document_type",
            "gl_account",
            derived=("anomaly_score", "z_score", "percentile", "population_key"),
        ),
    ),
    "L4-02": _entry(
        "L4-02",
        status=RuleStatus.MACRO,
        presenter_surface=PresenterSurface.ACCOUNT_PROCESS_MACRO,
        final_topic="ledger_integrity",
        secondary_topics=("revenue_statistical",),
        scoring_role=ScoringRole.MACRO_ONLY,
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        title="Benford distribution macro signal",
        tone="macro_review",
        column_sources=_columns(
            ("company_code", "fiscal_year", "gl_account"),
            ("fiscal_period", "debit_amount", "credit_amount"),
            macro=(
                "macro_finding_id",
                "population_key",
                "sample_size",
                "benford_mad",
                "chi2_p_value",
                "flagged_digits",
                "candidate_rows",
                "candidate_documents",
                "metrics",
            ),
        ),
        conflict_note=(
            "PHASE1-2 family(Benford 모집단통계)로 이관 — canonical L1~L4 count 제외(2026-06-15)."
        ),
    ),
    "Benford": _entry(
        "Benford",
        canonical_rule_id="L4-02",
        status=RuleStatus.ALIAS,
        presenter_surface=PresenterSurface.ACCOUNT_PROCESS_MACRO,
        final_topic="ledger_integrity",
        secondary_topics=("revenue_statistical",),
        scoring_role=ScoringRole.MACRO_ONLY,
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        title="Benford display alias",
        tone="alias_only",
        column_sources=_columns((), macro=("macro_finding_id", "population_key", "metrics")),
        conflict_note="Display alias for L4-02; never counted separately.",
    ),
    "L4-03": _entry(
        "L4-03",
        final_topic="revenue_statistical",
        title="High-amount outlier",
        column_sources=_transaction_columns(
            "gl_account",
            "source",
            "local_amount",
            derived=("anomaly_score", "z_score", "percentile"),
        ),
    ),
    "L4-04": _entry(
        "L4-04",
        final_topic="account_logic",
        secondary_topics=("intercompany_cycle",),
        title="Rare account pair",
        column_sources=_transaction_columns(
            "gl_account",
            "business_process",
            "source",
            derived=("account_pair", "rarity_score", "anomaly_score", "account_family"),
        ),
    ),
    "L4-05": _entry(
        "L4-05",
        presenter_surface=PresenterSurface.CONTEXT_BADGE,
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        scoring_role=ScoringRole.BOOSTER,
        standalone_rankable=False,
        allow_row_violation_detail=True,
        allow_standalone_violation_copy=False,
        title="Unusual user timing context",
        tone="context_only",
        column_sources=_transaction_columns(
            "created_by",
            "source",
            "business_process",
            derived=("posting_hour", "cluster_score", "anomaly_score"),
        ),
        conflict_note="Locked context rule; standalone copy forbidden.",
    ),
    "L4-06": _entry(
        "L4-06",
        presenter_surface=PresenterSurface.CONTEXT_BADGE,
        final_topic="revenue_statistical",
        scoring_role=ScoringRole.COMBO_ONLY,
        standalone_rankable=False,
        allow_row_violation_detail=True,
        allow_standalone_violation_copy=False,
        title="Batch posting context",
        tone="context_only",
        column_sources=_transaction_columns(
            "source",
            "created_by",
            "gl_account",
            derived=("upload_batch_id", "batch_anomaly_score", "anomaly_score"),
        ),
        conflict_note="Combo-only context rule; standalone copy forbidden.",
    ),
    "D01": _entry(
        "D01",
        status=RuleStatus.MACRO,
        presenter_surface=PresenterSurface.ACCOUNT_PROCESS_MACRO,
        final_topic="account_logic",
        secondary_topics=("intercompany_cycle", "revenue_statistical"),
        scoring_role=ScoringRole.MACRO_ONLY,
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        title="Account activity variance macro",
        tone="macro_review",
        column_sources=_columns(
            ("company_code", "fiscal_year", "gl_account"),
            ("business_process", "debit_amount", "credit_amount"),
            macro=(
                "macro_finding_id",
                "prior_amount",
                "current_amount",
                "prior_count",
                "current_count",
                "weighted_variance",
                "review_score",
                "macro_priority_score",
                "queue_bucket",
                "population_key",
            ),
        ),
        conflict_note="Macro finding, excluded from L1-L4 transaction count.",
    ),
    "D02": _entry(
        "D02",
        status=RuleStatus.MACRO,
        presenter_surface=PresenterSurface.ACCOUNT_PROCESS_MACRO,
        final_topic="closing_timing",
        secondary_topics=("intercompany_cycle", "revenue_statistical"),
        scoring_role=ScoringRole.MACRO_ONLY,
        standalone_rankable=False,
        include_in_l1_l4_transaction_count=False,
        allow_standalone_violation_copy=False,
        title="Monthly pattern variance macro",
        tone="macro_review",
        column_sources=_columns(
            ("company_code", "fiscal_year", "fiscal_period", "gl_account"),
            ("business_process", "debit_amount", "credit_amount"),
            macro=(
                "macro_finding_id",
                "prior_month_distribution",
                "current_month_distribution",
                "jsd",
                "top_month_delta",
                "review_score",
                "macro_priority_score",
                "queue_bucket",
                "population_key",
            ),
        ),
        conflict_note="Macro finding, excluded from L1-L4 transaction count.",
    ),
}


def canonicalize_rule_id(rule_id: str) -> str:
    """Return the locked canonical ID for aliases and internal reason codes."""

    return CANONICALIZATION_MAP.get(rule_id, rule_id)


def get_rule_detail_metadata(rule_id: str) -> RuleDetailMetadata:
    """Return metadata for a requested rule ID.

    If a future compatibility caller provides a mapped ID that is not itself in
    the registry, fall back to its canonical metadata.
    """

    if rule_id in RULE_DETAIL_METADATA_REGISTRY:
        return RULE_DETAIL_METADATA_REGISTRY[rule_id]
    canonical_rule_id = canonicalize_rule_id(rule_id)
    try:
        return RULE_DETAIL_METADATA_REGISTRY[canonical_rule_id]
    except KeyError as exc:
        raise KeyError(f"Unknown rule detail metadata ID: {rule_id}") from exc


def can_render_row_violation_detail(rule_id: str) -> bool:
    """Return whether a requested rule can render transaction row detail."""

    metadata = get_rule_detail_metadata(rule_id)
    return metadata.allow_row_violation_detail


def can_generate_standalone_violation_copy(rule_id: str) -> bool:
    """Return whether a requested rule can use direct standalone violation copy."""

    metadata = get_rule_detail_metadata(rule_id)
    return (
        can_render_row_violation_detail(rule_id)
        and metadata.allow_standalone_violation_copy
        and metadata.rule_id not in LOCKED_NO_STANDALONE_COPY_RULE_IDS
    )


def include_in_l1_l4_transaction_count(rule_id: str) -> bool:
    """Return whether a registry entry contributes to the canonical 30 count."""

    return get_rule_detail_metadata(rule_id).include_in_l1_l4_transaction_count


def get_canonical_transaction_rule_ids() -> tuple[str, ...]:
    """Return canonical L1-L4 rule IDs contributing to the locked count."""

    return tuple(
        metadata.canonical_rule_id
        for metadata in RULE_DETAIL_METADATA_REGISTRY.values()
        if metadata.include_in_l1_l4_transaction_count
    )


def _schema_column_names(schema_path: Path | None = None) -> set[str]:
    path = schema_path or Path(__file__).resolve().parents[2] / "config" / "schema.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(column["name"]) for column in data.get("columns", [])}


def validate_rule_detail_metadata_registry(schema_path: Path | None = None) -> list[str]:
    """Return hard validation errors for the locked v1 metadata contract."""

    errors: list[str] = []
    canonical_seen: set[str] = set()
    schema_columns = _schema_column_names(schema_path)

    for rule_id, metadata in RULE_DETAIL_METADATA_REGISTRY.items():
        if not metadata.canonical_rule_id:
            errors.append(f"{rule_id}: canonical_rule_id is required")
        if metadata.final_topic is not None and metadata.final_topic not in LOCKED_TOPICS:
            errors.append(f"{rule_id}: unknown final_topic {metadata.final_topic}")
        for topic in metadata.secondary_topics:
            if topic not in LOCKED_TOPICS:
                errors.append(f"{rule_id}: unknown secondary_topic {topic}")
        if canonicalize_rule_id(metadata.canonical_rule_id) != metadata.canonical_rule_id:
            errors.append(f"{rule_id}: canonicalization loop detected")
        if metadata.include_in_l1_l4_transaction_count:
            if metadata.status in {RuleStatus.ALIAS, RuleStatus.INTERNAL_REASON_CODE}:
                errors.append(f"{rule_id}: alias/internal reason code counted")
            if metadata.canonical_rule_id in canonical_seen:
                errors.append(f"{rule_id}: duplicate canonical count entry")
            canonical_seen.add(metadata.canonical_rule_id)
        if (
            metadata.presenter_surface != PresenterSurface.TRANSACTION_DETAIL
            and metadata.allow_row_violation_detail
            and rule_id not in LOCKED_CONTEXT_ROW_DETAIL_RULE_IDS
        ):
            errors.append(f"{rule_id}: non-transaction surface allows row detail")
        if (
            rule_id in LOCKED_NO_STANDALONE_COPY_RULE_IDS
            and metadata.allow_standalone_violation_copy
        ):
            errors.append(f"{rule_id}: locked context rule allows standalone copy")
        if (
            metadata.presenter_surface
            in {
                PresenterSurface.CONTEXT_BADGE,
                PresenterSurface.ACCOUNT_PROCESS_MACRO,
                PresenterSurface.INTERCOMPANY_SIDECAR,
                PresenterSurface.GRAPH_SIDECAR,
                PresenterSurface.DRILLDOWN_REASON,
            }
            and metadata.allow_standalone_violation_copy
        ):
            errors.append(f"{rule_id}: non-row surface allows standalone copy")
        missing_required = set(metadata.column_sources.required_ledger_columns) - schema_columns
        if missing_required:
            missing = ", ".join(sorted(missing_required))
            errors.append(f"{rule_id}: required ledger columns absent from schema: {missing}")

    if len(canonical_seen) != 29:
        errors.append(f"canonical transaction/detail count is {len(canonical_seen)}, expected 29")
    if "Benford" in canonical_seen:
        errors.append("Benford counted separately from L4-02")
    if {"L2-03a", "L2-03b", "L2-03c", "L2-03d"} & canonical_seen:
        errors.append("L2-03 internal reason codes counted separately from L2-03")
    # L4-02(Benford macro)는 PHASE1-2 family 로 이관(2026-06-15) → canonical L1~L4 count 제외.
    if "L4-02" in canonical_seen:
        errors.append("L4-02 must be excluded from canonical count (moved to PHASE1-2 family)")
    return errors


def assert_rule_detail_metadata_registry_valid(schema_path: Path | None = None) -> None:
    """Raise ValueError if the registry violates the locked v1 contract."""

    errors = validate_rule_detail_metadata_registry(schema_path)
    if errors:
        raise ValueError("Rule detail metadata registry validation failed: " + "; ".join(errors))


assert_rule_detail_metadata_registry_valid()
