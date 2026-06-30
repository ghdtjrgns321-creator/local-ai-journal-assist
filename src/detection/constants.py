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
    "L1-07-02": "Unknown Approver",
    "L3-03": "Related Party Transaction Review Signal",
    "L2-04": "Expense Capitalization Signal",
    "L2-05": "Reversal Pattern",
    "L3-04": "Period-start/end Closing Review Candidate",
    "L3-05": "Weekend Posting",
    "L3-06": "After-hours Posting",
    "L3-07": "Posting-Document Date Gap",
    "L1-08": "Wrong Fiscal Period",
    "L4-02": "Benford Violation",
    "L4-03": "High Amount Outlier",
    "L4-04": "Rare Debit-Credit Account Pair",
    "L3-09": "Suspense Aging",
    "L3-10": "High-risk Account Use",
    "L4-05": "Abnormal Hours Cluster",
    "L4-06": "Batch Posting Outlier",
    "D01": "Account Activity Shift",
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
    "R05": "Rare Account-Partner Edge",
    "R06": "User Account Degree Spike",
    "R07": "Dormant Partner Reactivation",
    "ML01": "Supervised ML Alert",
    "ML02": "비지도학습 이상 탐지",
    "ML03": "Transformer ML Alert",
    "ML04": "시퀀스 이상 탐지",
    "EN01": "Ensemble Alert",
    "AA01": "Entry Change Trail",
    "AA02": "Abnormal IP Access",
    "AA03": "Sequential Document Numbering",
    "AA04": "Approval Process Validation",
    "EV01": "Evidence Presence Check",
    "L3-11": "Revenue Cutoff Mismatch",
    "L3-12": "Work Scope Excess Review",
    "EV03": "Evidence Amount Mismatch",
    "TB01": "Estimate Bias Drift",
    "TB02": "Estimate Range Extreme",
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
    "L1-07-02": 4,
    "L3-03": 4,
    "L2-04": 4,
    "L2-05": 4,
    "L3-04": 3,
    "L3-05": 2,
    "L3-06": 2,
    "L3-07": 3,
    "L1-08": 4,
    "L4-02": 2,
    "L4-03": 3,
    "L4-04": 2,
    "L3-09": 3,
    "L3-10": 3,
    "L4-05": 3,
    "L4-06": 2,
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
    "R05": 3,
    "R06": 3,
    "R07": 4,
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
    "L3-11": 3,
    "L3-12": 3,
    "EV03": 3,
    "TB01": 4,
    "TB02": 3,
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

RULE_LEVEL_WEIGHTS: dict[str, float] = {
    "L1": 0.40,
    "L2": 0.25,
    "L3": 0.20,
    "L4": 0.15,
}

RULE_LEVEL_WEIGHTS_WITH_ML: dict[str | Layer, float] = {
    "L1": 0.30,
    "L2": 0.18,
    "L3": 0.12,
    "L4": 0.10,
    Layer.ML_SUPERVISED: 0.15,
    Layer.ML_UNSUPERVISED: 0.15,
}

RULE_LEVEL_WEIGHTS_WITH_TRENDBREAK: dict[str | Layer, float] = {
    "L1": 0.34,
    "L2": 0.21,
    "L3": 0.17,
    "L4": 0.13,
    Layer.TRENDBREAK: 0.15,
}

LAYER_WEIGHTS_WITH_PRIOR: dict[Layer, float] = {
    Layer.LAYER_A: 0.15,
    Layer.LAYER_B: 0.45,
    Layer.LAYER_C: 0.25,
    Layer.BENFORD: 0.15,
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
    Layer.LAYER_A: 0.13,
    Layer.LAYER_B: 0.38,
    Layer.LAYER_C: 0.22,
    Layer.BENFORD: 0.12,
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
    Layer.LAYER_A: DetectorProfile(
        Layer.LAYER_A,
        "L1/L3 Data Quality Rules",
        DetectorMaturity.PRODUCTION,
        True,
    ),
    Layer.LAYER_B: DetectorProfile(
        Layer.LAYER_B,
        "L1-L4 Fraud Rules",
        DetectorMaturity.PRODUCTION,
        True,
    ),
    Layer.LAYER_C: DetectorProfile(
        Layer.LAYER_C,
        "L1-L4 Anomaly Rules",
        DetectorMaturity.PRODUCTION,
        True,
    ),
    Layer.BENFORD: DetectorProfile(
        Layer.BENFORD,
        "L4-02 Benford",
        DetectorMaturity.PRODUCTION,
        True,
    ),
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
        "L3-11 Cutoff / Evidence",
        DetectorMaturity.PRODUCTION,
        True,
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
        plain_reason=(
            "The same user owns conflicting business functions in one entry "
            "(toxic process combination derived from created_by + business_process)."
        ),
        # sod_violation·sod_conflict_type 제거(2026-06-21): 구 주입 컬럼 방식 폐기.
        # b07_segregation_of_duties 는 created_by+business_process 로 toxic 쌍을 직접 도출한다.
        used_columns=(
            "created_by",
            "business_process",
            "user_persona",
            "source",
            "debit_amount",
            "credit_amount",
        ),
    ),
    "L1-07": RuleExplanation(
        rule_id="L1-07",
        plain_reason="Approval appears to be missing despite approval being required.",
        used_columns=("approved_by", "source", "debit_amount", "credit_amount"),
    ),
    "L1-07-02": RuleExplanation(
        rule_id="L1-07-02",
        plain_reason="An approver is populated but absent from the employee master.",
        used_columns=("approved_by", "approver_in_master"),
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
        plain_reason=(
            "The document mixes expense and asset patterns consistent with capitalization risk."
        ),
        used_columns=("document_id", "gl_account", "debit_amount", "credit_amount"),
    ),
    "L2-05": RuleExplanation(
        rule_id="L2-05",
        plain_reason=(
            "A high-confidence reversal or a reversal-like clearing/reclass pattern was detected."
        ),
    ),
    "L3-02": RuleExplanation(
        rule_id="L3-02",
        plain_reason="The entry is manual and should be reviewed in context.",
        used_columns=("source", "debit_amount", "credit_amount"),
    ),
    "L3-03": RuleExplanation(
        rule_id="L3-03",
        plain_reason=(
            "The entry uses an intercompany account and should be reviewed as a "
            "related-party transaction candidate."
        ),
        used_columns=("company_code", "trading_partner", "gl_account"),
    ),
    "L3-04": RuleExplanation(
        rule_id="L3-04",
        plain_reason=(
            "The entry was posted near period start or period end; amount, manual source, "
            "and other context signals only raise review priority."
        ),
        used_columns=("posting_date", "is_period_end", "debit_amount", "credit_amount"),
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
        plain_reason=("The posting date and document date differ beyond the allowed threshold."),
        used_columns=("posting_date", "document_date"),
    ),
    "L3-09": RuleExplanation(
        rule_id="L3-09",
        plain_reason="A suspense-account balance remained unresolved beyond the aging threshold.",
        used_columns=("gl_account", "posting_date", "amount_open"),
    ),
    "L3-10": RuleExplanation(
        rule_id="L3-10",
        plain_reason="The entry uses an account configured as high risk.",
        used_columns=("gl_account",),
    ),
    "L3-11": RuleExplanation(
        rule_id="L3-11",
        plain_reason=(
            "The revenue or expense posting date differs from the available "
            "recognition-basis event date beyond the allowed cutoff window."
        ),
        used_columns=("posting_date", "delivery_date", "gl_account", "is_revenue_account"),
        false_positive_risks=(
            "Delivery date may be only a proxy for the actual recognition basis.",
            "Service, subscription, construction, acceptance-based, and installation-based "
            "transactions require more specific source-event dates when available.",
            "Missing source-event dates mean cutoff could not be tested, not that "
            "cutoff is normal.",
        ),
        auditor_checks=(
            "Confirm the applicable revenue recognition basis for the transaction type.",
            "Tie posting date to delivery, acceptance, installation, service "
            "confirmation, or billing plan evidence.",
            "Review period-end manual adjustments and subsequent credit memos or reversals.",
        ),
    ),
    "L3-12": RuleExplanation(
        rule_id="L3-12",
        plain_reason=(
            "One user is concentrated across multiple work areas in the current "
            "audit population. This is a review signal only; explicit SoD or "
            "authorization-matrix violations remain L1-06."
        ),
        used_columns=(
            "created_by",
            "user_persona",
            "business_process",
            "company_code",
            "document_type",
            "gl_account",
            "source",
        ),
        false_positive_risks=(
            "Small teams, backup coverage, shared service centers, and month-end "
            "support can legitimately concentrate multiple processes in one user.",
            "The rule uses current-period breadth only and does not prove an "
            "authorization violation.",
        ),
        auditor_checks=(
            "Confirm whether the user's broad activity was expected for the period.",
            "Check compensating review controls when one user spans many processes "
            "or company codes.",
            "Prioritize cases with manual source, sensitive accounts, high amounts, "
            "or period-end postings.",
        ),
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
        plain_reason=(
            "The debit-credit account pair is rare in this population and should be "
            "reviewed with other risk signals."
        ),
        used_columns=("document_id", "gl_account", "debit_amount", "credit_amount"),
    ),
    "L4-05": RuleExplanation(
        rule_id="L4-05",
        plain_reason="The user or time-cluster pattern is statistically unusual.",
    ),
    "L4-06": RuleExplanation(
        rule_id="L4-06",
        plain_reason=(
            "The automated or batch-like posting pattern is a review signal, "
            "especially when corroborated by cutoff, control, amount, account, "
            "description, reversal, or duplicate indicators."
        ),
        used_columns=("source", "is_period_end", "posting_date", "debit_amount", "credit_amount"),
        false_positive_risks=(
            "Payroll, depreciation, allocations, and approved interfaces can create "
            "normal high-volume postings.",
            "Company-specific batch jobs may not be identifiable from source alone.",
        ),
    ),
    "D01": RuleExplanation(
        rule_id="D01",
        plain_reason=(
            "The account's current-period activity level changed materially from the prior period."
        ),
        used_columns=("gl_account", "debit_amount", "credit_amount"),
        false_positive_risks=(
            "Business growth, restructuring, new product launches, ERP migration, or "
            "chart-of-account changes can create legitimate activity shifts.",
            "The rule flags the account's current rows, not a specific journal line "
            "as definitively wrong.",
        ),
        auditor_checks=(
            "Compare the shifted account with budget, trial balance movement, account "
            "mapping changes, and management explanations.",
            "Prioritize when combined with high amount, rare account-pair, period-end, "
            "sensitive-account, or approval-control signals.",
        ),
        references=("ISA 520.5", "PCAOB AS 2305"),
    ),
    "D02": RuleExplanation(
        rule_id="D02",
        plain_reason=(
            "The account's monthly amount distribution changed materially from the prior period."
        ),
        used_columns=("gl_account", "fiscal_period", "debit_amount", "credit_amount"),
        false_positive_risks=(
            "Seasonality changes, project timing, policy changes, reorganizations, or "
            "missing fiscal periods can create legitimate distribution shifts.",
            "The rule detects account-level timing drift and does not identify the "
            "specific abnormal journal line by itself.",
        ),
        auditor_checks=(
            "Review the months that drive the concentration and tie them to cutoff "
            "evidence, closing adjustments, reversals, and source documents.",
            "Treat as higher risk when combined with period-end, posting-document date "
            "gap, wrong fiscal period, high amount, rare account pair, missing or "
            "corrupted description, or reversal signals.",
        ),
        references=("ISA 520.5",),
    ),
}

TOPSIDE_BONUS_RULES: list[tuple[str, list[tuple[str, str]]]] = [
    ("period_end", [("L3-04", "layer_c")]),
    ("approval_bypass", [("L1-05", "layer_b"), ("L1-07", "layer_b")]),
    ("invalid_accounting_pattern", [("L1-03", "layer_a"), ("L4-04", "layer_c")]),
    ("high_amount", [("L4-03", "layer_c")]),
]

# BATCH_CORROBORATION_RULES·WORK_SCOPE_CORROBORATION_RULES 제거(2026-06-21):
# L4-06(배치)·L3-12(업무범위)는 PHASE1-2 family 귀속이라 PHASE1-1 row anomaly_score/risk_level
# corroboration 승격을 폐기했다(score_aggregator 의 해당 함수도 제거).

RISK_THRESHOLDS: dict[str, float] = {
    RiskLevel.HIGH: 0.50,
    RiskLevel.MEDIUM: 0.25,
    RiskLevel.LOW: 0.10,
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


def get_rule_level_label(rule_id: str) -> str:
    """Return the user-facing L1-L4 bucket for a rule id."""
    code = str(rule_id or "").strip().upper()
    for prefix in ("L1", "L2", "L3", "L4"):
        if code.startswith(prefix):
            return prefix
    if code.startswith(("IC", "GR")):
        return "L3"
    if code.startswith(("EV", "D", "TS", "TB")):
        return "Analytical"
    if code.startswith(("ML", "NLP")):
        return "Phase 2/3"
    return ""


def get_track_display_label(track_name: str, rule_id: str | None = None) -> str:
    """Return a user-facing label without exposing legacy layer_a/b/c names."""
    if rule_id:
        rule_level = get_rule_level_label(rule_id)
        if rule_level:
            if str(rule_id).upper() == "L4-02":
                return "L4 Benford"
            return rule_level
    return get_detector_profile(str(track_name)).display_name


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
