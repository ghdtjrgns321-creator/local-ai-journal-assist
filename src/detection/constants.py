"""Shared detection constants and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskLevel(StrEnum):
    """Risk level assigned by the score aggregator."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    NORMAL = "Normal"


class Layer(StrEnum):
    """Detector track names."""

    LAYER_A = "layer_a"
    LAYER_B = "layer_b"
    LAYER_C = "layer_c"
    BENFORD = "benford"
    LAYER_D = "layer_d"
    DUPLICATE = "duplicate"
    TIMESERIES = "timeseries"
    INTERCOMPANY = "intercompany"
    RELATIONAL = "relational"
    ML_SUPERVISED = "ml_supervised"
    ML_UNSUPERVISED = "ml_unsupervised"
    ML_TRANSFORMER = "ml_transformer"
    ML_SEQUENCE = "ml_sequence"
    ENSEMBLE = "ensemble"
    ACCESS_AUDIT = "access_audit"
    EVIDENCE = "evidence"
    TRENDBREAK = "trendbreak"
    GRAPH = "graph"
    NLP = "nlp"


class DetectorMaturity(StrEnum):
    """Deployment maturity for a detector."""

    PRODUCTION = "production"
    BETA = "beta"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class DetectorProfile:
    """Detector metadata."""

    track_name: str
    display_name: str
    maturity: DetectorMaturity
    default_enabled: bool
    activation_requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetectorExplanationProfile:
    """Shared explanation metadata for a detector track."""

    track_name: str
    summary: str
    why_it_flagged: str
    used_columns: tuple[str, ...] = ()
    false_positive_risks: tuple[str, ...] = ()
    auditor_checks: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleExplanation:
    """Explanation metadata for a rule."""

    rule_id: str
    plain_reason: str
    used_columns: tuple[str, ...] = ()
    false_positive_risks: tuple[str, ...] = ()
    auditor_checks: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


RULE_CODES: dict[str, str] = {
    "L1-01": "Unbalanced Entry",
    "L1-02": "Missing Required Field",
    "L1-03": "Invalid Account",
    "L3-01": "Misclassified Account",
    "L4-01": "Revenue Outlier",
    "L2-01": "Just Below Approval Threshold",
    "L1-04": "Exceeded Approval Limit",
    "L2-02": "Duplicate Payment",
    "L2-03": "Duplicate Entry",
    "L2-03a": "Duplicate Entry (Exact)",
    "L2-03b": "Duplicate Entry (Fuzzy)",
    "L2-03c": "Split Transaction",
    "L2-03d": "Serial Duplicate",
    "L1-05": "Self Approval",
    "L1-06": "Segregation of Duties Violation",
    "L3-02": "Manual Entry Override",
    "L1-07": "Skipped Approval",
    "L3-03": "Intercompany Circularity Signal",
    "L2-04": "Expense Capitalization Signal",
    "L2-05": "Top-side JE Composite",
    "L3-04": "Period-end Rush",
    "L3-05": "Weekend Posting",
    "L3-06": "After-hours Posting",
    "L3-07": "Backdated Entry",
    "L1-08": "Wrong Fiscal Period",
    "L3-08": "Vague Description",
    "L4-02": "Benford Violation",
    "L4-03": "High Amount Outlier",
    "L4-04": "Unusual Account Pair",
    "L3-09": "Suspense Account Use",
    "L2-06": "Reversal Pattern",
    "L4-05": "Abnormal Hours Cluster",
    "L4-06": "Batch Posting Outlier",
    "D01": "Account Balance Shift",
    "D02": "Ratio Distribution Shift",
    "TS01": "Transaction Burst",
    "TS02": "Unusual Periodicity",
    "IC01": "Unmatched Intercompany",
    "IC02": "Intercompany Amount Mismatch",
    "IC03": "Intercompany Timing Gap",
    "R01": "New Counterparty",
    "R02": "Dormant Account Activity",
    "R03": "Transfer Pricing Anomaly",
    "R04": "Document Name Missing",
    "ML01": "Supervised ML Alert",
    "ML02": "Unsupervised ML Alert",
    "ML03": "Transformer ML Alert",
    "ML04": "Sequence ML Alert",
    "EN01": "Ensemble Alert",
    "AA01": "Entry Change Trail",
    "AA02": "Abnormal IP Access",
    "AA03": "Sequential Document Numbering",
    "AA04": "Approval Process Validation",
    "EV01": "Evidence Presence Check",
    "EV02": "Evidence OCR Check",
    "EV03": "Evidence Amount Mismatch",
    "TB01": "Estimate Bias Drift",
    "TB02": "Estimate Range Extreme",
    "GR01": "Circular Transaction Graph Signal",
    "GR03": "Transfer Pricing Graph Signal",
    "NLP01": "Header-Account Semantic Mismatch",
    "NLP02": "Process-Account Semantic Mismatch",
    "NLP03": "Abnormal Description",
    "NLP04": "Intercompany Narrative Anomaly",
    "NLP05": "Risk Keyword Evasion",
}

SEVERITY_MAP: dict[str, int] = {
    "L1-01": 5,
    "L1-02": 2,
    "L1-03": 3,
    "L3-01": 3,
    "L4-01": 5,
    "L2-01": 3,
    "L1-04": 3,
    "L2-02": 3,
    "L2-03": 3,
    "L2-03a": 3,
    "L2-03b": 3,
    "L2-03c": 4,
    "L2-03d": 3,
    "L1-05": 3,
    "L1-06": 4,
    "L3-02": 4,
    "L1-07": 4,
    "L3-03": 4,
    "L2-04": 4,
    "L2-05": 5,
    "L3-04": 3,
    "L3-05": 2,
    "L3-06": 2,
    "L3-07": 3,
    "L1-08": 4,
    "L3-08": 1,
    "L4-02": 2,
    "L4-03": 3,
    "L4-04": 2,
    "L3-09": 3,
    "L2-06": 4,
    "L4-05": 3,
    "L4-06": 3,
    "D01": 4,
    "D02": 3,
    "TS01": 4,
    "TS02": 2,
    "IC01": 3,
    "IC02": 2,
    "IC03": 2,
    "R01": 1,
    "R02": 2,
    "R03": 4,
    "R04": 1,
    "ML01": 4,
    "ML02": 4,
    "ML03": 4,
    "ML04": 4,
    "EN01": 5,
    "AA01": 4,
    "AA02": 3,
    "AA03": 3,
    "AA04": 4,
    "EV01": 4,
    "EV02": 3,
    "EV03": 3,
    "TB01": 4,
    "TB02": 3,
    "GR01": 4,
    "GR03": 4,
    "NLP01": 4,
    "NLP02": 3,
    "NLP03": 2,
    "NLP04": 3,
    "NLP05": 3,
}

LAYER_WEIGHTS: dict[Layer, float] = {
    Layer.LAYER_A: 0.15,
    Layer.LAYER_B: 0.45,
    Layer.LAYER_C: 0.25,
    Layer.BENFORD: 0.15,
}

LAYER_WEIGHTS_WITH_PRIOR: dict[Layer, float] = {
    Layer.LAYER_A: 0.12,
    Layer.LAYER_B: 0.38,
    Layer.LAYER_C: 0.20,
    Layer.BENFORD: 0.12,
    Layer.LAYER_D: 0.18,
}

LAYER_WEIGHTS_WITH_TIMESERIES: dict[Layer, float] = {
    Layer.LAYER_A: 0.13,
    Layer.LAYER_B: 0.40,
    Layer.LAYER_C: 0.22,
    Layer.BENFORD: 0.13,
    Layer.TIMESERIES: 0.12,
}

LAYER_WEIGHTS_WITH_ML: dict[Layer, float] = {
    Layer.LAYER_A: 0.10,
    Layer.LAYER_B: 0.30,
    Layer.LAYER_C: 0.18,
    Layer.BENFORD: 0.10,
    Layer.ML_SUPERVISED: 0.15,
    Layer.ML_UNSUPERVISED: 0.17,
}

LAYER_WEIGHTS_WITH_TRENDBREAK: dict[Layer, float] = {
    Layer.LAYER_A: 0.13,
    Layer.LAYER_B: 0.38,
    Layer.LAYER_C: 0.22,
    Layer.BENFORD: 0.12,
    Layer.TRENDBREAK: 0.15,
}

LAYER_WEIGHTS_WITH_PRIOR_AND_TRENDBREAK: dict[Layer, float] = {
    Layer.LAYER_A: 0.10,
    Layer.LAYER_B: 0.32,
    Layer.LAYER_C: 0.18,
    Layer.BENFORD: 0.10,
    Layer.LAYER_D: 0.15,
    Layer.TRENDBREAK: 0.15,
}

STACKING_BASE_MODELS: list[str] = [
    Layer.LAYER_A,
    Layer.LAYER_B,
    Layer.LAYER_C,
    Layer.BENFORD,
    Layer.ML_SUPERVISED,
    Layer.ML_UNSUPERVISED,
    Layer.ML_TRANSFORMER,
    Layer.ML_SEQUENCE,
]

STACKING_FALLBACK_WEIGHTS: dict[str, float] = {
    Layer.LAYER_A: 0.08,
    Layer.LAYER_B: 0.24,
    Layer.LAYER_C: 0.14,
    Layer.BENFORD: 0.08,
    Layer.ML_SUPERVISED: 0.12,
    Layer.ML_UNSUPERVISED: 0.14,
    Layer.ML_TRANSFORMER: 0.10,
    Layer.ML_SEQUENCE: 0.10,
}

DETECTOR_DISPLAY_ORDER: list[str] = [
    Layer.LAYER_A,
    Layer.LAYER_B,
    Layer.LAYER_C,
    Layer.BENFORD,
    Layer.DUPLICATE,
    Layer.INTERCOMPANY,
    Layer.RELATIONAL,
    Layer.EVIDENCE,
    Layer.ACCESS_AUDIT,
    Layer.LAYER_D,
    Layer.TRENDBREAK,
    Layer.GRAPH,
    Layer.NLP,
    Layer.ML_SUPERVISED,
    Layer.ML_UNSUPERVISED,
    Layer.ENSEMBLE,
    Layer.ML_TRANSFORMER,
    Layer.ML_SEQUENCE,
]

DETECTOR_PROFILES: dict[str, DetectorProfile] = {
    Layer.LAYER_A: DetectorProfile(Layer.LAYER_A, "L1", DetectorMaturity.PRODUCTION, True),
    Layer.LAYER_B: DetectorProfile(Layer.LAYER_B, "L2", DetectorMaturity.PRODUCTION, True),
    Layer.LAYER_C: DetectorProfile(Layer.LAYER_C, "L3/L4", DetectorMaturity.PRODUCTION, True),
    Layer.BENFORD: DetectorProfile(Layer.BENFORD, "Benford", DetectorMaturity.PRODUCTION, True),
    Layer.DUPLICATE: DetectorProfile(Layer.DUPLICATE, "Duplicate", DetectorMaturity.BETA, True),
    Layer.INTERCOMPANY: DetectorProfile(
        Layer.INTERCOMPANY,
        "Intercompany",
        DetectorMaturity.BETA,
        True,
    ),
    Layer.RELATIONAL: DetectorProfile(
        Layer.RELATIONAL,
        "Relational",
        DetectorMaturity.BETA,
        False,
        ("settings",),
    ),
    Layer.EVIDENCE: DetectorProfile(
        Layer.EVIDENCE,
        "Evidence",
        DetectorMaturity.BETA,
        False,
        ("settings",),
    ),
    Layer.ACCESS_AUDIT: DetectorProfile(
        Layer.ACCESS_AUDIT,
        "Access Audit",
        DetectorMaturity.BETA,
        False,
        ("settings",),
    ),
    Layer.LAYER_D: DetectorProfile(
        Layer.LAYER_D,
        "Variance",
        DetectorMaturity.BETA,
        False,
        ("settings", "historical_data"),
    ),
    Layer.TRENDBREAK: DetectorProfile(
        Layer.TRENDBREAK,
        "TrendBreak",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("settings", "historical_data"),
    ),
    Layer.GRAPH: DetectorProfile(
        Layer.GRAPH,
        "Graph",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("settings", "optional_dependency"),
    ),
    Layer.NLP: DetectorProfile(
        Layer.NLP,
        "NLP",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("settings", "external_api"),
    ),
    Layer.ML_SUPERVISED: DetectorProfile(
        Layer.ML_SUPERVISED,
        "ML Supervised",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("settings", "trained_model"),
    ),
    Layer.ML_UNSUPERVISED: DetectorProfile(
        Layer.ML_UNSUPERVISED,
        "ML Unsupervised",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("settings", "trained_model"),
    ),
    Layer.ENSEMBLE: DetectorProfile(
        Layer.ENSEMBLE,
        "Ensemble",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("settings", "trained_model"),
    ),
    Layer.ML_TRANSFORMER: DetectorProfile(
        Layer.ML_TRANSFORMER,
        "ML Transformer",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("trained_model",),
    ),
    Layer.ML_SEQUENCE: DetectorProfile(
        Layer.ML_SEQUENCE,
        "ML Sequence",
        DetectorMaturity.EXPERIMENTAL,
        False,
        ("trained_model",),
    ),
}

DETECTOR_EXPLANATION_PROFILES: dict[str, DetectorExplanationProfile] = {
    Layer.LAYER_A: DetectorExplanationProfile(
        track_name=Layer.LAYER_A,
        summary="Checks structural integrity and required data quality gates.",
        why_it_flagged="The entry breaks a hard integrity or required-field rule.",
        used_columns=("document_id", "gl_account", "debit_amount", "credit_amount"),
    ),
    Layer.LAYER_B: DetectorExplanationProfile(
        track_name=Layer.LAYER_B,
        summary="Checks fraud and control-circumvention scenarios.",
        why_it_flagged="The entry matches a concrete fraud or control-evasion pattern.",
        used_columns=("created_by", "approved_by", "gl_account", "debit_amount", "credit_amount"),
    ),
    Layer.LAYER_C: DetectorExplanationProfile(
        track_name=Layer.LAYER_C,
        summary="Checks suspicious behavioral or contextual anomalies.",
        why_it_flagged="The entry looks suspicious enough to review but is not conclusive alone.",
        used_columns=("posting_date", "document_date", "line_text", "gl_account"),
    ),
    Layer.BENFORD: DetectorExplanationProfile(
        track_name=Layer.BENFORD,
        summary="Checks first-digit distribution against Benford's law.",
        why_it_flagged="The amount distribution deviates materially from the expected baseline.",
        used_columns=("debit_amount", "credit_amount"),
    ),
}

RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    "L1-01": RuleExplanation(
        rule_id="L1-01",
        plain_reason="Debit and credit totals do not balance for the document.",
        used_columns=("document_id", "debit_amount", "credit_amount"),
    ),
    "L1-02": RuleExplanation(
        rule_id="L1-02",
        plain_reason="A required input field is missing.",
        used_columns=("document_id", "posting_date", "gl_account"),
    ),
    "L1-03": RuleExplanation(
        rule_id="L1-03",
        plain_reason="The GL account is not valid in the configured chart of accounts.",
        used_columns=("gl_account",),
    ),
    "L1-04": RuleExplanation(
        rule_id="L1-04",
        plain_reason="The amount exceeds the configured approval limit.",
        used_columns=("debit_amount", "credit_amount", "approved_by"),
    ),
    "L1-05": RuleExplanation(
        rule_id="L1-05",
        plain_reason="The preparer and approver are the same user.",
        used_columns=("created_by", "approved_by"),
    ),
    "L1-06": RuleExplanation(
        rule_id="L1-06",
        plain_reason="The entry violates segregation-of-duties controls.",
        used_columns=("created_by", "business_process", "sod_conflict_type"),
    ),
    "L1-07": RuleExplanation(
        rule_id="L1-07",
        plain_reason="Approval appears to be missing despite approval being required.",
        used_columns=("approved_by", "source", "debit_amount", "credit_amount"),
    ),
    "L1-08": RuleExplanation(
        rule_id="L1-08",
        plain_reason="Fiscal period does not match the posting date period.",
        used_columns=("fiscal_period", "posting_date"),
    ),
    "L2-01": RuleExplanation(
        rule_id="L2-01",
        plain_reason="The amount sits just below a configured approval threshold.",
        used_columns=("debit_amount", "credit_amount"),
    ),
    "L2-02": RuleExplanation(
        rule_id="L2-02",
        plain_reason="A duplicate payment pattern was detected.",
        used_columns=("auxiliary_account_number", "posting_date", "debit_amount", "credit_amount"),
    ),
    "L2-03": RuleExplanation(
        rule_id="L2-03",
        plain_reason="A duplicate-entry pattern was detected.",
        used_columns=("gl_account", "posting_date", "debit_amount", "credit_amount"),
    ),
    "L2-04": RuleExplanation(
        rule_id="L2-04",
        plain_reason="The document mixes expense and asset patterns consistent with capitalization risk.",
        used_columns=("document_id", "gl_account", "debit_amount", "credit_amount"),
    ),
    "L2-05": RuleExplanation(
        rule_id="L2-05",
        plain_reason="Multiple top-side journal-entry risk signals were triggered together.",
        used_columns=("posting_date", "line_text", "created_by"),
    ),
    "L2-06": RuleExplanation(
        rule_id="L2-06",
        plain_reason="A reversal pattern suggests an elevated control or fraud signal.",
    ),
    "L3-01": RuleExplanation(
        rule_id="L3-01",
        plain_reason="The account is used in a business process that looks atypical.",
        used_columns=("business_process", "gl_account"),
    ),
    "L3-02": RuleExplanation(
        rule_id="L3-02",
        plain_reason="The entry is manual and should be reviewed in context.",
        used_columns=("source", "debit_amount", "credit_amount"),
    ),
    "L3-03": RuleExplanation(
        rule_id="L3-03",
        plain_reason="The intercompany pattern requires additional review.",
        used_columns=("company_code", "trading_partner", "gl_account"),
    ),
    "L3-04": RuleExplanation(
        rule_id="L3-04",
        plain_reason="A large entry was posted near period end.",
        used_columns=("posting_date", "debit_amount", "credit_amount"),
    ),
    "L3-05": RuleExplanation(
        rule_id="L3-05",
        plain_reason="The entry was posted on a weekend or holiday.",
        used_columns=("posting_date",),
    ),
    "L3-06": RuleExplanation(
        rule_id="L3-06",
        plain_reason="The entry was posted outside normal business hours.",
        used_columns=("posting_date",),
    ),
    "L3-07": RuleExplanation(
        rule_id="L3-07",
        plain_reason="The posting date trails the document date beyond the allowed threshold.",
        used_columns=("posting_date", "document_date"),
    ),
    "L3-08": RuleExplanation(
        rule_id="L3-08",
        plain_reason="The description is vague or matches a risky keyword pattern.",
        used_columns=("line_text", "header_text"),
    ),
    "L3-09": RuleExplanation(
        rule_id="L3-09",
        plain_reason="A suspense-account usage pattern requires review.",
        used_columns=("gl_account", "line_text"),
    ),
    "L4-01": RuleExplanation(
        rule_id="L4-01",
        plain_reason="A revenue-account amount is an outlier within its peer distribution.",
        used_columns=("gl_account", "amount_zscore"),
    ),
    "L4-02": RuleExplanation(
        rule_id="L4-02",
        plain_reason="The amount distribution deviates from Benford's law.",
        used_columns=("debit_amount", "credit_amount"),
    ),
    "L4-03": RuleExplanation(
        rule_id="L4-03",
        plain_reason="The amount is a statistical outlier.",
        used_columns=("amount_zscore", "debit_amount", "credit_amount"),
    ),
    "L4-04": RuleExplanation(
        rule_id="L4-04",
        plain_reason="The debit-credit account pair is rare for this population.",
    ),
    "L4-05": RuleExplanation(
        rule_id="L4-05",
        plain_reason="The user or time-cluster pattern is statistically unusual.",
    ),
    "L4-06": RuleExplanation(
        rule_id="L4-06",
        plain_reason="The batch-posting pattern is statistically unusual.",
    ),
}

TOPSIDE_BONUS_RULES: list[tuple[str, list[tuple[str, str]]]] = [
    ("period_end", [("L3-04", "layer_c")]),
    ("approval_bypass", [("L1-05", "layer_b"), ("L1-07", "layer_b")]),
    ("invalid_accounting_pattern", [("L1-03", "layer_a"), ("L4-04", "layer_c")]),
    ("high_amount", [("L4-03", "layer_c")]),
    ("vague_description", [("L3-08", "layer_c")]),
]

RISK_THRESHOLDS: dict[str, float] = {
    RiskLevel.HIGH: 0.7,
    RiskLevel.MEDIUM: 0.4,
    RiskLevel.LOW: 0.2,
}


def get_detector_profile(track_name: str) -> DetectorProfile:
    """Return detector metadata with a safe fallback."""

    return DETECTOR_PROFILES.get(
        track_name,
        DetectorProfile(
            track_name=track_name,
            display_name=track_name,
            maturity=DetectorMaturity.BETA,
            default_enabled=False,
        ),
    )


def get_detector_explanation_profile(track_name: str) -> DetectorExplanationProfile:
    """Return detector explanation metadata with a safe fallback."""

    return DETECTOR_EXPLANATION_PROFILES.get(
        track_name,
        DetectorExplanationProfile(
            track_name=track_name,
            summary=f"{track_name} detector result.",
            why_it_flagged="No detector explanation metadata is registered yet.",
        ),
    )


def _get_rule_track(rule_id: str) -> str:
    """Return the detector track mapped to a rule id when available."""

    try:
        from src.metrics.rule_mapping import RULE_TO_TRACK
    except ImportError:
        return ""
    return str(RULE_TO_TRACK.get(rule_id, "") or "")


def get_rule_explanation(rule_id: str) -> RuleExplanation:
    """Return rule explanation metadata with a detector-level fallback."""

    if rule_id in RULE_EXPLANATIONS:
        return RULE_EXPLANATIONS[rule_id]

    track_name = _get_rule_track(rule_id)
    detector = get_detector_explanation_profile(track_name) if track_name else None
    return RuleExplanation(
        rule_id=rule_id,
        plain_reason=f"{RULE_CODES.get(rule_id, rule_id)} was flagged.",
        used_columns=detector.used_columns if detector else (),
        false_positive_risks=detector.false_positive_risks if detector else (),
        auditor_checks=detector.auditor_checks if detector else (),
        references=detector.references if detector else (),
    )
