"""Rule mappings for Phase 1 evaluation and user-action layer taxonomy."""

from __future__ import annotations

from dataclasses import dataclass

RULE_TO_LABEL: dict[str, list[str]] = {
    "L1-01": ["UnbalancedEntry"],
    "L1-02": ["MissingField"],
    "L1-03": ["InvalidAccount"],
    "L3-01": ["MisclassifiedAccount"],
    "L4-01": ["RevenueManipulation"],
    "L2-01": ["JustBelowThreshold"],
    "L1-04": ["ExceededApprovalLimit"],
    "L2-02": ["DuplicatePayment"],
    "L2-03": ["DuplicateEntry", "ExactDuplicateAmount"],
    "L1-05": ["SelfApproval"],
    "L1-06": ["SegregationOfDutiesViolation"],
    "L3-02": ["ManualOverride"],
    "L1-07": ["SkippedApproval"],
    "L3-03": ["CircularIntercompany", "CircularTransaction"],
    "L2-04": ["ImproperCapitalization"],
    "L3-04": ["RushedPeriodEnd"],
    "L3-05": ["WeekendPosting"],
    "L3-06": ["AfterHoursPosting", "UnusualTiming"],
    "L3-07": ["BackdatedEntry", "LatePosting"],
    "L1-08": ["WrongPeriod"],
    "L3-08": ["VagueDescription"],
    "L4-02": ["BenfordViolation"],
    "L4-03": ["UnusuallyHighAmount", "StatisticalOutlier"],
    "L4-04": ["UnusualAccountPair"],
    "L3-09": [],
    "L2-06": ["ReversedAmount"],
    "L4-05": [],
    "L4-06": [],
}

RULE_TO_TRACK: dict[str, str] = {
    "L1-01": "layer_a",
    "L1-02": "layer_a",
    "L1-03": "layer_a",
    "L3-01": "layer_a",
    "L4-01": "layer_b",
    "L2-01": "layer_b",
    "L1-04": "layer_b",
    "L2-02": "layer_b",
    "L2-03": "layer_b",
    "L2-03a": "layer_b",
    "L2-03b": "layer_b",
    "L2-03c": "layer_b",
    "L2-03d": "layer_b",
    "L1-05": "layer_b",
    "L1-06": "layer_b",
    "L3-02": "layer_b",
    "L1-07": "layer_b",
    "L3-03": "layer_b",
    "L2-04": "layer_b",
    "L2-05": "layer_b",
    "L3-04": "layer_c",
    "L3-05": "layer_c",
    "L3-06": "layer_c",
    "L3-07": "layer_c",
    "L1-08": "layer_c",
    "L3-08": "layer_c",
    "L4-02": "benford",
    "L4-03": "layer_c",
    "L4-04": "layer_c",
    "L3-09": "layer_c",
    "L2-06": "layer_c",
    "L4-05": "layer_c",
    "L4-06": "layer_c",
}


@dataclass(frozen=True)
class ActionLayerProfile:
    """User-facing Phase 1 action layer metadata."""

    layer_id: str
    title: str
    caption: str
    user_action: str


ACTION_LAYER_PROFILES: dict[str, ActionLayerProfile] = {
    "confirmed_issue": ActionLayerProfile(
        layer_id="confirmed_issue",
        title="L1 Confirmed Issue",
        caption="Rules that support immediate correction or clear control-violation reporting.",
        user_action="Correct the entry, fix the data, or report the violation.",
    ),
    "fraud_signal": ActionLayerProfile(
        layer_id="fraud_signal",
        title="L2 Fraud or Control-Circumvention Signal",
        caption="Rules that represent a concrete fraud scenario or strong circumvention pattern.",
        user_action="Inspect support, approval flow, and related entries with high priority.",
    ),
    "review_needed": ActionLayerProfile(
        layer_id="review_needed",
        title="L3 Review Needed",
        caption="Rules that are suspicious enough to review but not sufficient on their own.",
        user_action="Check business context, period-end rationale, and exception handling.",
    ),
    "stat_outlier": ActionLayerProfile(
        layer_id="stat_outlier",
        title="L4 Statistical Outlier",
        caption="Rules that highlight distributional or statistical deviation.",
        user_action="Review top outliers and intersect with other rules before concluding.",
    ),
}

ACTION_LAYER_ORDER: tuple[str, ...] = (
    "confirmed_issue",
    "fraud_signal",
    "review_needed",
    "stat_outlier",
)

RULE_TO_ACTION_LAYER: dict[str, str] = {
    "L1-01": "confirmed_issue",
    "L1-02": "confirmed_issue",
    "L1-03": "confirmed_issue",
    "L3-01": "review_needed",
    "L4-01": "stat_outlier",
    "L2-01": "fraud_signal",
    "L1-04": "confirmed_issue",
    "L2-02": "fraud_signal",
    "L2-03": "fraud_signal",
    "L2-03a": "fraud_signal",
    "L2-03b": "fraud_signal",
    "L2-03c": "fraud_signal",
    "L2-03d": "fraud_signal",
    "L1-05": "confirmed_issue",
    "L1-06": "confirmed_issue",
    "L3-02": "review_needed",
    "L1-07": "confirmed_issue",
    "L3-03": "review_needed",
    "L2-04": "fraud_signal",
    "L2-05": "fraud_signal",
    "L3-04": "review_needed",
    "L3-05": "review_needed",
    "L3-06": "review_needed",
    "L3-07": "review_needed",
    "L1-08": "confirmed_issue",
    "L3-08": "review_needed",
    "L4-02": "stat_outlier",
    "L4-03": "stat_outlier",
    "L4-04": "stat_outlier",
    "L3-09": "review_needed",
    "L2-06": "fraud_signal",
    "L4-05": "stat_outlier",
    "L4-06": "stat_outlier",
}

PHASE1_TRACKS: tuple[str, ...] = ("layer_a", "layer_b", "layer_c", "benford")


def covered_label_types() -> set[str]:
    """Return all label types that are mapped to Phase 1 rules."""
    covered: set[str] = set()
    for label_types in RULE_TO_LABEL.values():
        covered.update(label_types)
    return covered


def get_action_layer(rule_id: str) -> str:
    """Return the user-action layer id for a rule code."""
    return RULE_TO_ACTION_LAYER.get(rule_id, "")


def get_action_layer_profile(layer_id: str) -> ActionLayerProfile | None:
    """Return metadata for a user-action layer."""
    return ACTION_LAYER_PROFILES.get(layer_id)


def iter_action_layer_groups(
    rule_ids: tuple[str, ...] | None = None,
) -> list[tuple[ActionLayerProfile, tuple[str, ...]]]:
    """Return ordered action-layer groups with their rule ids."""
    candidates = tuple(RULE_TO_ACTION_LAYER) if rule_ids is None else rule_ids
    grouped: list[tuple[ActionLayerProfile, tuple[str, ...]]] = []
    for layer_id in ACTION_LAYER_ORDER:
        profile = ACTION_LAYER_PROFILES[layer_id]
        ids = tuple(
            rule_id for rule_id in candidates if RULE_TO_ACTION_LAYER.get(rule_id) == layer_id
        )
        if ids:
            grouped.append((profile, ids))
    return grouped
