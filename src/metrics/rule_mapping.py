"""Rule-to-label mappings for ground-truth evaluation."""

from __future__ import annotations

RULE_TO_LABEL: dict[str, list[str]] = {
    "A01": ["UnbalancedEntry"],
    "A02": ["MissingField"],
    "A03": ["InvalidAccount"],
    "B01": ["RevenueManipulation"],
    "B02": ["JustBelowThreshold"],
    "B03": ["ExceededApprovalLimit"],
    "B04": ["DuplicatePayment"],
    "B05": ["DuplicateEntry", "ExactDuplicateAmount"],
    "B06": ["SelfApproval"],
    "B07": ["SegregationOfDutiesViolation"],
    "B08": ["ManualOverride"],
    "B09": ["SkippedApproval"],
    "B10": ["CircularIntercompany", "CircularTransaction"],
    "B11": ["ImproperCapitalization"],
    "C01": ["RushedPeriodEnd"],
    "C02": ["WeekendPosting"],
    "C03": ["AfterHoursPosting", "UnusualTiming"],
    "C04": ["BackdatedEntry", "LatePosting"],
    "C05": ["WrongPeriod"],
    "C06": ["VagueDescription"],
    "C07": ["BenfordViolation"],
    "C08": ["UnusuallyHighAmount", "StatisticalOutlier"],
    "C09": ["UnusualAccountPair"],
    "C10": [],
    "C11": ["ReversedAmount"],
    "C12": [],
}

RULE_TO_TRACK: dict[str, str] = {
    "A01": "layer_a", "A02": "layer_a", "A03": "layer_a",
    "B01": "layer_b", "B02": "layer_b", "B03": "layer_b",
    "B04": "layer_b", "B05": "layer_b", "B06": "layer_b",
    "B07": "layer_b", "B08": "layer_b", "B09": "layer_b",
    "B10": "layer_b", "B11": "layer_b",
    "C01": "layer_c", "C02": "layer_c", "C03": "layer_c",
    "C04": "layer_c", "C05": "layer_c", "C06": "layer_c",
    "C07": "benford", "C08": "layer_c", "C09": "layer_c",
    "C10": "layer_c", "C11": "layer_c", "C12": "layer_c",
}

PHASE1_TRACKS: tuple[str, ...] = ("layer_a", "layer_b", "layer_c", "benford")


def covered_label_types() -> set[str]:
    """Return all label types that are mapped to Phase 1 rules."""
    covered: set[str] = set()
    for label_types in RULE_TO_LABEL.values():
        covered.update(label_types)
    return covered
