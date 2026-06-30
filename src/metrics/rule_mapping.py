"""Rule mappings for Phase 1 evaluation and user-action layer taxonomy."""

from __future__ import annotations

from dataclasses import dataclass

RULE_TO_LABEL: dict[str, list[str]] = {
    "L1-01": ["UnbalancedEntry"],
    "L1-02": ["MissingField"],
    "L1-03": ["InvalidAccount"],
    "L4-01": ["RevenueManipulation"],
    "L2-01": ["JustBelowThreshold"],
    "L1-04": ["ExceededApprovalLimit"],
    "L2-02": ["DuplicatePayment"],
    "L2-03": ["DuplicateEntry", "ExactDuplicateAmount"],
    "L1-05": ["SelfApproval"],
    "L1-06": ["SegregationOfDutiesViolation"],
    "L3-02": ["ManualOverride"],
    "L1-07": ["SkippedApproval"],
    "L1-07-02": ["UnknownApprover"],
    "L3-03": ["CircularIntercompany"],
    "L2-04": ["ExpenseCapitalization", "ImproperCapitalization"],
    "L3-04": ["RushedPeriodEnd"],
    "L3-05": ["WeekendPosting"],
    "L3-06": ["AfterHoursPosting"],
    "L3-07": ["BackdatedEntry", "LatePosting"],
    "L1-08": ["WrongPeriod"],
    "L4-02": ["BenfordViolation"],
    "L4-03": ["UnusuallyHighAmount", "StatisticalOutlier"],
    "L4-04": ["UnusualAccountPair"],
    "L3-09": [],
    "L3-10": [],
    "L3-11": ["RevenueCutoffMismatch", "ExpenseCutoffMismatch"],
    "L3-12": ["WorkScopeExcessReview"],
    "L2-05": ["ReversedAmount"],
    "L4-05": ["AbnormalHoursConcentration"],
    "L4-06": [],
    "IC01": ["UnmatchedIntercompany"],
    "IC02": ["IntercompanyAmountMismatch"],
    "IC03": ["IntercompanyTimingMismatch"],
}

# NOTE:
# L3-02 and L3-03 are population rules in recent datasynth candidates.
# Their anomaly labels remain for legacy anomaly evaluation, but preferred
# datasynth truth is population coverage rather than strict anomaly precision.
RULE_TO_POPULATION_TRUTH: dict[str, str] = {
    "L1-01": "labels/l101_unbalanced_truth.csv",
    "L2-01": "labels/l201_just_below_threshold_truth.csv",
    "L4-01": "labels/revenue_manipulation_l401_direct_truth.csv",
    "L3-02": "labels/manual_entry_population_truth.csv",
    "L3-03": "labels/intercompany_population_truth.csv",
    "L3-05": "labels/weekend_review_population.csv",
    "L3-09": "labels/suspense_aging_review_population.csv",
    "L3-10": "labels/high_risk_account_review_population.csv",
    "L3-11": "labels/cutoff_review_population.csv",
    "L3-12": "labels/work_scope_excess_review_population.csv",
    "L4-03": "labels/high_amount_review_population.csv",
    "L4-04": "labels/rare_account_pair_review_population.csv",
}

RULE_TO_TRUTH_BASIS: dict[str, str] = {
    "L1-01": "document imbalance population",
    "L4-01": (
        "RevenueManipulation broad label with high_value_revenue_outlier as direct L4-01 truth"
    ),
    "L2-01": "JustBelowThreshold labels with threshold-proximity bands",
    "L2-02": "DuplicatePayment labels; detector evidence is document-pair based",
    "L2-03": "DuplicateEntry/ExactDuplicateAmount labels with binary re-posting evidence",
    "L2-04": (
        "expense-capitalization family labels; strict ImproperCapitalization "
        "is an auxiliary confirmed subset"
    ),
    "L2-05": (
        "confirmed ReversedAmount labels for high-confidence reversals; "
        "clearing/reclass candidates are review population"
    ),
    "L1-06": (
        "strict SegregationOfDutiesViolation labels are evaluated against "
        "direct SoD findings only; role/process-breadth review signals are "
        "excluded from L1-06 and belong to L3-12/work-scope review"
    ),
    "L3-02": "manual/adjustment source population",
    "L3-03": "intercompany account population",
    "L3-05": (
        "weekend/holiday posting review population; confirmed anomaly subset is WeekendPosting"
    ),
    "L3-09": (
        "suspense account aging review population; confirmed anomaly subset is SuspenseAccountAbuse"
    ),
    "L3-10": "high-risk account review population; confirmed anomaly subset is HighRiskAccountUse",
    "L4-03": "confirmed high-amount anomaly subset; high_amount_review_population is coverage only",
    "L4-04": (
        "rare account-pair raw review universe; confirmed UnusualAccountPair is a separate subset"
    ),
    "IC01": "confirmed unmatched intercompany labels",
    "IC02": "amount-mismatch review candidates, evaluated against matching exception labels",
    "IC03": "timing-gap review candidates, evaluated against matching exception labels",
    "L3-06": "after-hours-only anomaly labels",
    "L4-05": (
        "combined-context abnormal-hours behavior review universe; confirmed "
        "AbnormalHoursConcentration is a separate subset"
    ),
    "L3-11": (
        "cutoff review population; confirmed revenue/expense cutoff labels are "
        "direct anomaly subset"
    ),
    "L3-12": (
        "current-period user work-scope scored review population; raw candidate "
        "coverage is stored separately in work_scope_raw_candidate_population"
    ),
    "L4-06": (
        "auxiliary batch-processing review signal; no confirmed anomaly label "
        "contract is defined yet"
    ),
}

RULE_TO_TRUTH_DISPLAY: dict[str, str] = {
    "L4-01": "RevenueManipulation/high-value outlier subset",
    "L2-01": "JustBelowThreshold proximity bands",
    "L2-02": "DuplicatePayment pair candidates",
    "L2-03": "binary duplicate-entry scores",
    "L2-04": "ExpenseCapitalization family",
    "L2-05": "ReversedAmount confirmed subset",
    "L1-06": "SegregationOfDutiesViolation immediate subset",
    "L3-02": "manual/adjustment population",
    "L3-03": "intercompany population",
    "L3-05": "weekend/holiday review population",
    "L3-09": "suspense aging review population",
    "L3-10": "high-risk account review population",
    "L4-03": "high-amount confirmed subset",
    "L4-04": "rare account-pair review population",
    "IC01": "UnmatchedIntercompany",
    "IC02": "IntercompanyAmountMismatch",
    "IC03": "IntercompanyTimingMismatch",
    "L3-11": "cutoff review population",
    "L3-12": "work-scope concentration review population",
    "L4-05": "abnormal-hours behavior review",
    "L4-06": "batch-processing auxiliary review",
}

RULE_TO_EVALUATION_NOTE: dict[str, str] = {
    "L3-03": "Population rule. Do not score against CircularIntercompany as fraud precision.",
    "L3-05": (
        "Weekend/holiday calendar screen. Raw hits are review population; "
        "confirmed WeekendPosting labels are only the direct anomaly subset."
    ),
    "L3-09": (
        "Suspense aging screen. Raw hits are unresolved suspense-account review "
        "population; confirmed SuspenseAccountAbuse judgement remains downstream."
    ),
    "L4-01": (
        "RevenueManipulation is broad. Score direct L4-01 recall only when "
        "high_value_revenue_outlier direct-truth metadata or sidecars exist; "
        "other revenue subtypes are combination or Phase 2/3 coverage."
    ),
    "L2-01": (
        "Threshold-proximity screen. Interpret lower/close/razor bands separately; "
        "unresolved approver limits are coverage issues, not hits."
    ),
    "L2-02": (
        "Duplicate-payment screen is pair-oriented. Phase 1 rule truth is the "
        "raw duplicate-payment review universe; DuplicatePayment labels and "
        "pair sidecars are only confirmed subsets. Reference and fallback reason "
        "bands drive downstream priority rather than truth inclusion."
    ),
    "L2-03": (
        "Duplicate-entry screen is binary and limited to explicit reference "
        "re-posting or full row-clone evidence. Near, document-profile, and split "
        "patterns are not L2-03 primary hits."
    ),
    "L2-04": (
        "Expense-capitalization review rule. Score family coverage separately from "
        "strict ImproperCapitalization precision; review/immediate bands drive "
        "queue priority."
    ),
    "L2-05": (
        "Reversal-pattern review rule. High-confidence reversal is the confirmed "
        "ReversedAmount subset; candidate clearing/reclass hits remain review "
        "population."
    ),
    "L1-06": (
        "Direct SoD rule. Score strict SegregationOfDutiesViolation "
        "precision/recall against direct conflict findings only. "
        "Role/process-breadth signals are L3-12 work-scope review candidates, "
        "not L1-06 review or promotion signals. Self-approval, skipped "
        "approval, and manual override are evaluated by L1-05, L1-07, and "
        "L3-02."
    ),
    "IC02": (
        "Phase 1 review candidate. Preserve recall; precision is handled by case priority/Phase 2."
    ),
    "IC03": (
        "Phase 1 review candidate. Preserve recall; precision is handled by case priority/Phase 2."
    ),
    "L3-11": (
        "Cutoff review rule. Long but reasonable delay controls may appear as raw "
        "hits and should be handled by case priority/Phase 2."
    ),
    "L3-12": (
        "Work-scope concentration review rule. Evaluate raw candidate coverage "
        "against work_scope_raw_candidate_population and scored review accuracy "
        "against rule_truth_L3_12/work_scope_excess_review_population. Do not "
        "count zero-score system/admin observations as scored-truth false "
        "positives."
    ),
    "L4-03": (
        "High-amount review anchor. Score confirmed anomaly recall separately from "
        "high_amount_review_population coverage; normal large business events are "
        "not confirmed anomalies."
    ),
    "L4-04": (
        "Rare account-pair review anchor. Phase 1 rule truth is the raw detector "
        "review universe. Confirmed UnusualAccountPair labels and normal rare-pair "
        "controls are subset/context sidecars, not the strict precision denominator."
    ),
    "L4-02": (
        "Benford is a population-level account distribution finding. Do not read "
        "legacy BenfordViolation document labels as row-level precision/recall. "
        "Use benford_finding_truth, normal controls, drill-down size, and v54 "
        "holdout sidecars."
    ),
    "L4-05": (
        "User-behavior abnormal-hours screen. Phase 1 rule truth is the raw "
        "combined-context behavior review universe. Confirmed "
        "AbnormalHoursConcentration labels are a subset, and annual single-year "
        "runs are robustness checks rather than the strict truth benchmark."
    ),
    "L4-06": (
        "Auxiliary batch-processing signal. Phase 1 rule truth is the raw "
        "batch detector review universe, while BatchAnomaly labels are only a "
        "confirmed subset. Normal and boundary batch controls stay outside "
        "strict rule truth. Escalate only when independent corroborating rule "
        "groups are present."
    ),
}

RULE_TO_TRACK: dict[str, str] = {
    "L1-01": "layer_a",
    "L1-02": "layer_a",
    "L1-03": "layer_a",
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
    "L1-07-02": "layer_b",
    "L3-03": "layer_b",
    "L2-04": "layer_b",
    "L3-10": "layer_b",
    "L3-11": "evidence",
    "L3-12": "layer_b",
    "L3-04": "layer_c",
    "L3-05": "layer_c",
    "L3-06": "layer_c",
    "L3-07": "layer_c",
    "L1-08": "layer_c",
    "L4-02": "benford",
    "L4-03": "layer_c",
    "L4-04": "layer_c",
    "L3-09": "layer_c",
    "L2-05": "layer_c",
    "L4-05": "layer_c",
    "L4-06": "layer_c",
    "IC01": "intercompany",
    "IC02": "intercompany",
    "IC03": "intercompany",
}


@dataclass(frozen=True)
class ActionLayerProfile:
    """User-facing Phase 1 action layer metadata."""

    layer_id: str
    title: str
    caption: str
    user_action: str


@dataclass(frozen=True)
class RuleEvaluationProfile:
    """User-facing rule evaluation metadata."""

    rule_objective: str
    broad_fraud_type: str = ""
    expected_coverage: str = ""
    status: str = "ok"
    note: str = ""


RULE_EVALUATION_PROFILES: dict[str, RuleEvaluationProfile] = {
    "L2-02": RuleEvaluationProfile(
        rule_objective="Potential duplicate payment pair",
        broad_fraud_type="DuplicatePayment",
        expected_coverage="pair/document review",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L2-02"],
    ),
    "L2-03": RuleEvaluationProfile(
        rule_objective="Duplicate-entry binary re-posting candidate",
        broad_fraud_type="DuplicateEntry",
        expected_coverage="binary re-posting review",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L2-03"],
    ),
    "L2-04": RuleEvaluationProfile(
        rule_objective="Expense-capitalization family review",
        broad_fraud_type="ExpenseCapitalization",
        expected_coverage="family coverage / queue bands",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L2-04"],
    ),
    "L2-05": RuleEvaluationProfile(
        rule_objective="Reversal, clearing, or reclass pattern",
        broad_fraud_type="ReversedAmount",
        expected_coverage="confirmed subset plus review population",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L2-05"],
    ),
    "L1-06": RuleEvaluationProfile(
        rule_objective="Segregation-of-duties structural conflict",
        broad_fraud_type="SegregationOfDutiesViolation",
        expected_coverage="direct conflict subset only",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L1-06"],
    ),
    "L4-01": RuleEvaluationProfile(
        rule_objective="High-value revenue z-score outlier",
        broad_fraud_type="RevenueManipulation",
        expected_coverage="partial / anchor",
        status="coverage_anchor",
        note=(
            "L4-01 is a high-value revenue outlier anchor, not a full "
            "RevenueManipulation classifier. When direct L4-01 truth is absent, "
            "do not fall back to broad RevenueManipulation labels; interpret "
            "hits through overlap with cutoff, reversal, manual, period-end, "
            "and approval signals."
        ),
    ),
    "L4-02": RuleEvaluationProfile(
        rule_objective="Company/account first-digit distribution finding",
        broad_fraud_type="BenfordViolation",
        expected_coverage="population finding / drill-down review",
        status="population",
        note=RULE_TO_EVALUATION_NOTE["L4-02"],
    ),
    "L4-03": RuleEvaluationProfile(
        rule_objective="High-amount positive z-score review anchor",
        broad_fraud_type="UnusuallyHighAmount",
        expected_coverage="confirmed subset plus high-amount review population",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L4-03"],
    ),
    "L4-04": RuleEvaluationProfile(
        rule_objective="Rare debit-credit account-pair review anchor",
        broad_fraud_type="UnusualAccountPair",
        expected_coverage="confirmed subset plus rare-pair review population",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L4-04"],
    ),
    "L4-05": RuleEvaluationProfile(
        rule_objective="User-level abnormal-hours behavior concentration",
        broad_fraud_type="AbnormalHoursConcentration",
        expected_coverage="confirmed subset plus behavior review queue",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L4-05"],
    ),
    "L4-06": RuleEvaluationProfile(
        rule_objective="Batch-processing anomaly auxiliary evidence",
        broad_fraud_type="BatchAnomaly",
        expected_coverage="auxiliary review signal / combo evidence",
        status="coverage_anchor",
        note=RULE_TO_EVALUATION_NOTE["L4-06"],
    ),
}


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
    "L1-07-02": "confirmed_issue",
    "L3-03": "review_needed",
    "L2-04": "fraud_signal",
    "L3-04": "review_needed",
    "L3-05": "review_needed",
    "L3-06": "review_needed",
    "L3-07": "review_needed",
    "L1-08": "confirmed_issue",
    "L4-02": "stat_outlier",
    "L4-03": "stat_outlier",
    "L4-04": "stat_outlier",
    "L3-09": "review_needed",
    "L3-10": "review_needed",
    "L3-11": "review_needed",
    "L3-12": "review_needed",
    "L2-05": "fraud_signal",
    "L4-05": "stat_outlier",
    "L4-06": "stat_outlier",
    "IC01": "review_needed",
    "IC02": "review_needed",
    "IC03": "review_needed",
}

PHASE1_TRACKS: tuple[str, ...] = ("layer_a", "layer_b", "layer_c", "benford", "evidence")


def covered_label_types() -> set[str]:
    """Return label types that are mapped to core Phase 1 tracks."""
    covered: set[str] = set()
    for rule_id, label_types in RULE_TO_LABEL.items():
        if RULE_TO_TRACK.get(rule_id) in PHASE1_TRACKS:
            covered.update(label_types)
    return covered


def get_action_layer(rule_id: str) -> str:
    """Return the user-action layer id for a rule code."""
    return RULE_TO_ACTION_LAYER.get(rule_id, "")


def get_truth_basis(rule_id: str) -> str:
    """Return the preferred ground-truth basis description for a rule."""
    if rule_id in RULE_TO_TRUTH_BASIS:
        return RULE_TO_TRUTH_BASIS[rule_id]
    labels = RULE_TO_LABEL.get(rule_id, [])
    if labels:
        return "anomaly labels"
    return "unmapped"


def get_truth_display(rule_id: str) -> str:
    """Return the user-facing truth label/basis string for a rule."""
    if rule_id in RULE_TO_TRUTH_DISPLAY:
        return RULE_TO_TRUTH_DISPLAY[rule_id]
    labels = RULE_TO_LABEL.get(rule_id, [])
    return ",".join(labels) if labels else "(none)"


def get_evaluation_note(rule_id: str) -> str:
    """Return user-facing evaluation caveat for review/population rules."""
    profile = RULE_EVALUATION_PROFILES.get(rule_id)
    if profile and profile.note:
        return profile.note
    return RULE_TO_EVALUATION_NOTE.get(rule_id, "")


def get_rule_evaluation_profile(rule_id: str) -> RuleEvaluationProfile | None:
    """Return metadata that explains how a rule should be evaluated."""
    return RULE_EVALUATION_PROFILES.get(rule_id)


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
