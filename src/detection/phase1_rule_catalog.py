"""PHASE1 rule/topic/queue catalog shared by case builder and dashboard.

The scoring registry remains the source for rule evidence semantics. This
module centralizes the presentation queue mappings that were previously copied
across the case builder and dashboard.
"""

from __future__ import annotations

from src.detection.rule_scoring import RULE_SCORING_REGISTRY

TOPIC_LEGACY_THEME_MAP: dict[str, str] = {
    "ledger_integrity": "data_integrity_failure",
    "approval_control": "control_failure",
    "closing_timing": "timing_anomaly",
    "account_logic": "logic_mismatch",
    "duplicate_outflow": "duplicate_or_outflow",
    "revenue_statistical": "statistical_outlier",
}

LEGACY_THEME_TOPIC_MAP: dict[str, str] = {
    legacy_theme: topic_id for topic_id, legacy_theme in TOPIC_LEGACY_THEME_MAP.items()
}

ISSUE_QUEUE_LABELS: dict[str, str] = {
    "data_integrity": "데이터 정합성",
    "control_approval": "통제/승인",
    "timing_close": "시점/마감",
    "amount_statistical": "금액/통계",
    "duplicate_outflow": "중복/유출",
    "account_logic": "계정/논리",
    "manipulation_candidate": "조작 후보 종합",
}

THEME_QUEUE_MAP: dict[str, str] = {
    "data_integrity_failure": "data_integrity",
    "control_failure": "control_approval",
    "access_scope_review": "control_approval",
    "timing_anomaly": "timing_close",
    "statistical_outlier": "amount_statistical",
    "duplicate_or_outflow": "duplicate_outflow",
    "logic_mismatch": "account_logic",
}

EVIDENCE_QUEUE_MAP: dict[str, str] = dict(THEME_QUEUE_MAP)

RULE_THEME_MAP: dict[str, tuple[str, str]] = {
    rule_id: (metadata.evidence_type, metadata.evidence_type)
    for rule_id, metadata in RULE_SCORING_REGISTRY.items()
    if metadata.evidence_type in EVIDENCE_QUEUE_MAP
}

RULE_QUEUE_MAP: dict[str, str] = {
    rule_id: EVIDENCE_QUEUE_MAP[metadata.evidence_type]
    for rule_id, metadata in RULE_SCORING_REGISTRY.items()
    if metadata.evidence_type in EVIDENCE_QUEUE_MAP
}


PHASE1_RULE_IDS: tuple[str, ...] = (
    "L1-01",
    "L1-02",
    "L1-03",
    "L3-01",
    "L4-01",
    "L2-01",
    "L1-04",
    "L2-02",
    "L2-03",
    "L1-05",
    "L1-06",
    "L3-02",
    "L1-07",
    "L1-09",
    "L3-10",
    "L3-12",
    "L3-03",
    "L2-04",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L1-08",
    "L3-08",
    "L4-03",
    "L4-04",
    "L3-09",
    "L2-05",
    "L4-05",
    "L4-06",
    "L4-02",
    "D01",
    "D02",
)

TOPIC_RULE_WHITELIST: dict[str, set[str]] = {
    "ledger_integrity": {"L1-01", "L1-02", "L1-08", "L3-08"},
    "approval_control": {
        "L1-04",
        "L1-05",
        "L1-06",
        "L1-07",
        "L1-09",
        "L2-01",
        "L3-02",
        "L3-05",
        "L3-06",
        "L3-10",
        "L3-12",
        "L4-05",
    },
    "closing_timing": {
        "L1-08",
        "L3-04",
        "L3-05",
        "L3-06",
        "L3-07",
        "L3-08",
        "L3-11",
        "L4-05",
        "D02",
    },
    "account_logic": {
        "L1-03",
        "L2-04",
        "L3-01",
        "L3-03",
        "L3-09",
        "L3-10",
        "L4-04",
        "D01",
    },
    "duplicate_outflow": {
        "L1-05",
        "L1-07",
        "L2-01",
        "L2-02",
        "L2-03",
        "L2-05",
        "L3-12",
    },
    "revenue_statistical": {
        "L3-10",
        "L4-01",
        "L4-02",
        "L4-03",
        "L4-06",
        "Benford",
        "D01",
        "D02",
    },
}
