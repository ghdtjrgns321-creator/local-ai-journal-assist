"""Rule-level scoring normalization for PHASE1 case aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.detection.constants import SEVERITY_MAP

SIGNAL_STRENGTH_MAP: dict[str, float] = {
    "critical": 1.0,
    "high": 1.0,
    "상": 1.0,
    "위험높음": 1.0,
    "위험 높음": 1.0,
    "medium": 0.6,
    "moderate": 0.6,
    "중": 0.6,
    "review_needed": 0.6,
    "검토필요": 0.6,
    "검토 필요": 0.6,
    "low": 0.3,
    "하": 0.3,
    "info": 0.2,
    "참고": 0.2,
    "normal": 0.0,
    "none": 0.0,
    "false": 0.0,
}

EVIDENCE_STRENGTH_FACTOR: dict[str, float] = {
    "strong": 1.0,
    "medium": 0.75,
    "weak": 0.45,
    "info": 0.25,
}

SCORING_ROLE_FACTOR: dict[str, float] = {
    "primary": 1.0,
    "booster": 0.65,
    "combo_only": 0.35,
    "macro_only": 0.0,
}

# OFF-TIME 보조축: 근무시간 외 입력 신호 묶음 (주말·공휴일 | 심야 | 작성자 비정상시간 집중).
# 설계상 tier 게이트·점수 병합에 참여하지 않고 within-tier 정렬·UI 표시 전용이다
# (HIGH_COMBO_GROUNDING.md §2(5), PHASE1_TIER_SCORING_SPEC.md §4). 따라서 PHASE1-1 통합
# 점수경로(row anomaly_score 정규화 합산·auto-escalation 카운트·corroboration)에서 0 기여로
# 차단한다. 단일 출처 — score_aggregator·phase1_case_builder 가 import 한다.
# 기간귀속(L3-04 기말·L3-11 컷오프)은 off-time 이 아니므로 절대 포함하지 않는다.
OFF_TIME_SET: frozenset[str] = frozenset({"L3-05", "L3-06", "L4-05"})


@dataclass(frozen=True)
class TopicMetadata:
    """Auditor-facing PHASE1 ranking topic."""

    topic_id: str
    label: str


TOPIC_REGISTRY: dict[str, TopicMetadata] = {
    "ledger_integrity": TopicMetadata("ledger_integrity", "원장기록·데이터정합성"),
    "approval_control": TopicMetadata("approval_control", "승인·권한·업무분장 통제"),
    "closing_timing": TopicMetadata("closing_timing", "결산·기간귀속·입력시점"),
    "account_logic": TopicMetadata("account_logic", "계정분류·거래실질 불일치"),
    "duplicate_outflow": TopicMetadata("duplicate_outflow", "중복·상계·자금유출"),
    "revenue_statistical": TopicMetadata("revenue_statistical", "수익·금액·모집단 통계 이상"),
}

# L1-04·L3-07·L3-09·L4-03 는 binary 룰(기다/아니다)로 통일.
# 옛 bucket 등급표는 룰이 더 이상 등급 label 을 생성하지 않아 죽은 코드였으므로 제거.
# binary hit → 정규화 fallback(generic)이 일관된 signal_strength 를 준다.


@dataclass(frozen=True)
class RuleScoringMetadata:
    """PHASE1 scoring contract for one rule."""

    rule_id: str
    evidence_type: str
    evidence_strength: str
    scoring_role: str = "primary"
    contribution_weight: float = 1.0
    final_topic: str | None = None
    secondary_topics: tuple[str, ...] = field(default_factory=tuple)
    standalone_rankable: bool = True
    floor_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    floor_eligible_labels: frozenset[str] | None = None
    combo_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    fraud_scenario_tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def severity(self) -> int:
        return int(SEVERITY_MAP.get(self.rule_id, 1))


@dataclass(frozen=True)
class NormalizedRuleEvidence:
    """A raw rule result translated into the common PHASE1 score scale."""

    rule_id: str
    evidence_type: str
    severity: int
    display_label: str
    signal_strength: float
    evidence_strength: str
    scoring_role: str
    normalized_score: float
    final_topic: str | None = None
    secondary_topics: tuple[str, ...] = field(default_factory=tuple)
    standalone_rankable: bool = True
    floor_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    combo_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    fraud_scenario_tags: tuple[str, ...] = field(default_factory=tuple)


RULE_SCORING_REGISTRY: dict[str, RuleScoringMetadata] = {
    "L1-01": RuleScoringMetadata(
        "L1-01",
        "data_integrity_failure",
        "strong",
        final_topic="ledger_integrity",
        fraud_scenario_tags=("ledger_integrity_failure",),
    ),
    "L1-02": RuleScoringMetadata(
        "L1-02",
        "data_integrity_failure",
        "medium",
        final_topic="ledger_integrity",
        fraud_scenario_tags=("missing_or_incomplete_data",),
    ),
    "L1-03": RuleScoringMetadata(
        "L1-03",
        "logic_mismatch",
        "medium",
        # 데이터정합성 묶음(L1-01·02·03, HIGH_COMBO §2(1)) — ledger_integrity 로 교정(2026-06-20).
        # 구 account_logic(부정 토픽)은 "계정과목표 밖 계정"을 fraud 신호로 오분류해 누수.
        final_topic="ledger_integrity",
        fraud_scenario_tags=("account_classification_mismatch",),
    ),
    "L1-04": RuleScoringMetadata(
        "L1-04",
        "control_failure",
        "strong",
        final_topic="approval_control",
        fraud_scenario_tags=("approval_bypass",),
    ),
    "L1-05": RuleScoringMetadata(
        "L1-05",
        "control_failure",
        "strong",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        fraud_scenario_tags=("approval_bypass",),
    ),
    "L1-06": RuleScoringMetadata(
        "L1-06",
        "control_failure",
        "strong",
        final_topic="approval_control",
        fraud_scenario_tags=("segregation_of_duties",),
    ),
    "L1-07": RuleScoringMetadata(
        "L1-07",
        "control_failure",
        "strong",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        fraud_scenario_tags=("approval_bypass",),
    ),
    "L1-08": RuleScoringMetadata(
        "L1-08",
        "data_integrity_failure",
        "medium",
        final_topic="closing_timing",
        secondary_topics=("ledger_integrity",),
        fraud_scenario_tags=("cutoff_or_period_mismatch",),
    ),
    "L1-07-02": RuleScoringMetadata(
        "L1-07-02",
        "control_failure",
        "strong",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        fraud_scenario_tags=("approval_bypass",),
    ),
    "L2-01": RuleScoringMetadata(
        "L2-01",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        secondary_topics=("approval_control",),
        fraud_scenario_tags=("threshold_splitting",),
    ),
    "L2-02": RuleScoringMetadata(
        "L2-02",
        "duplicate_or_outflow",
        "strong",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("duplicate_payment",),
    ),
    "L2-03": RuleScoringMetadata(
        "L2-03",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03a": RuleScoringMetadata(
        "L2-03a",
        "duplicate_or_outflow",
        "strong",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03b": RuleScoringMetadata(
        "L2-03b",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03c": RuleScoringMetadata(
        "L2-03c",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03d": RuleScoringMetadata(
        "L2-03d",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-04": RuleScoringMetadata(
        "L2-04",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        fraud_scenario_tags=("transaction_substance_mismatch",),
    ),
    "L2-05": RuleScoringMetadata(
        "L2-05",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("topside_or_outflow_pattern",),
    ),
    "L3-02": RuleScoringMetadata(
        "L3-02",
        "control_failure",
        "medium",
        final_topic="approval_control",
        fraud_scenario_tags=("manual_entry_concentration",),
    ),
    "L3-03": RuleScoringMetadata(
        "L3-03",
        # intercompany_cycle 제거(2026-06-14) → account_logic 계열로 재배치.
        "logic_mismatch",
        "weak",
        "booster",
        final_topic="account_logic",
        standalone_rankable=False,
        fraud_scenario_tags=("intercompany_population_context",),
    ),
    "L3-04": RuleScoringMetadata(
        "L3-04",
        "timing_anomaly",
        "medium",
        final_topic="closing_timing",
        fraud_scenario_tags=("cutoff_or_late_posting",),
    ),
    "L3-05": RuleScoringMetadata(
        "L3-05",
        "timing_anomaly",
        "weak",
        "booster",
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        standalone_rankable=False,
        fraud_scenario_tags=("non_business_day_activity",),
    ),
    "L3-06": RuleScoringMetadata(
        "L3-06",
        "timing_anomaly",
        "weak",
        "booster",
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        standalone_rankable=False,
        fraud_scenario_tags=("after_hours_activity",),
    ),
    "L3-07": RuleScoringMetadata(
        "L3-07",
        "timing_anomaly",
        "medium",
        final_topic="closing_timing",
        fraud_scenario_tags=("posting_document_date_gap",),
    ),
    "L3-09": RuleScoringMetadata(
        "L3-09",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        fraud_scenario_tags=("aging_or_settlement_mismatch",),
    ),
    "L3-10": RuleScoringMetadata(
        "L3-10",
        "logic_mismatch",
        "weak",
        "booster",
        final_topic="account_logic",
        secondary_topics=("approval_control", "revenue_statistical"),
        standalone_rankable=False,
        fraud_scenario_tags=("sensitive_amount_or_account_context",),
    ),
    "L3-11": RuleScoringMetadata(
        "L3-11",
        "timing_anomaly",
        "medium",
        final_topic="closing_timing",
        fraud_scenario_tags=("period_end_concentration",),
    ),
    # L3-12(업무범위 집중)는 PHASE1-2 family(사용자·연도 집계) 귀속. macro_only 로 PHASE1-1
    # row anomaly_score·tier 에 0 기여(2026-06-21 완전 제거). registry 항목은 폴백 점수 방지를
    # 위해 유지(L4-02 와 동일 사유). combo_policy_ids 제거 — work_scope corroboration 폐기.
    "L3-12": RuleScoringMetadata(
        "L3-12",
        "access_scope_review",
        "weak",
        "macro_only",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        standalone_rankable=False,
        fraud_scenario_tags=("work_scope_concentration",),
    ),
    "L4-01": RuleScoringMetadata(
        "L4-01",
        "statistical_outlier",
        "medium",
        final_topic="revenue_statistical",
        fraud_scenario_tags=("amount_outlier",),
    ),
    # macro(L4-02/Benford·D01·D02)는 PHASE1-2 family 귀속(계정/월 모집단, 2026-06-15 결정).
    # 단 registry 에는 macro_only 로 유지한다 — role_factor=0 으로 PHASE1-1 row anomaly_score·
    # case score 에 0 기여하도록 "중화"하는 역할. 항목을 지우면 normalize_rule_evidence 가
    # 기본값(primary)으로 폴백해 오히려 점수가 붙는다(score_aggregator). PHASE1-2 재정립 시
    # PHASE1-2 surface 로 이동.
    "L4-02": RuleScoringMetadata(
        "L4-02",
        "statistical_outlier",
        "weak",
        "macro_only",
        final_topic="ledger_integrity",
        secondary_topics=("revenue_statistical",),
        standalone_rankable=False,
        fraud_scenario_tags=("benford_distribution_anomaly",),
    ),
    "Benford": RuleScoringMetadata(
        "Benford",
        "statistical_outlier",
        "weak",
        "macro_only",
        final_topic="ledger_integrity",
        secondary_topics=("revenue_statistical",),
        standalone_rankable=False,
        fraud_scenario_tags=("benford_distribution_anomaly",),
    ),
    "L4-03": RuleScoringMetadata(
        "L4-03",
        "statistical_outlier",
        "medium",
        final_topic="revenue_statistical",
        fraud_scenario_tags=("amount_outlier",),
    ),
    "L4-04": RuleScoringMetadata(
        "L4-04",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        fraud_scenario_tags=("rare_account_partner_pair",),
    ),
    "L4-05": RuleScoringMetadata(
        "L4-05",
        "timing_anomaly",
        "weak",
        "booster",
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        standalone_rankable=False,
        fraud_scenario_tags=("behavioral_timing_context",),
    ),
    # L4-06(배치성 전표)는 PHASE1-2 family(배치·모집단) 귀속. macro_only 로 PHASE1-1 row
    # anomaly_score·tier 에 0 기여(2026-06-21 완전 제거). combo_policy_ids 제거 — batch
    # corroboration 폐기.
    "L4-06": RuleScoringMetadata(
        "L4-06",
        "statistical_outlier",
        "weak",
        "macro_only",
        final_topic="revenue_statistical",
        standalone_rankable=False,
        fraud_scenario_tags=("batch_population_anomaly",),
    ),
    # IC01~03·GR01/03 제거: intercompany/graph 는 PHASE1 정규 32룰이 아니다
    # (RULE_DETAIL_METADATA_V1_LOCK §). PHASE1 점수경로에서 제외.
    # 탐지기 파일(intercompany_matcher·graph_detector)은 완전 삭제됨(2026-06-30).
    # D01/D02 도 macro_only 유지(중화). PHASE1-2 family(TS) 귀속이나 위 L4-02 와 동일 사유로
    # registry 항목 유지 — 지우면 폴백 점수가 붙는다.
    "D01": RuleScoringMetadata(
        "D01",
        "macro_finding",
        "medium",
        "macro_only",
        final_topic="account_logic",
        secondary_topics=("revenue_statistical",),
        standalone_rankable=False,
        fraud_scenario_tags=("macro_account_logic_anomaly",),
    ),
    "D02": RuleScoringMetadata(
        "D02",
        "macro_finding",
        "medium",
        "macro_only",
        final_topic="closing_timing",
        secondary_topics=("revenue_statistical",),
        standalone_rankable=False,
        fraud_scenario_tags=("macro_timing_anomaly",),
    ),
}


def normalize_signal_strength(
    value: Any,
    *,
    severity: int,
    display_label: str | None = None,
) -> float:
    """Return 0..1 signal strength independent of severity weighting."""

    label = str(display_label or "").strip().lower()
    if label in SIGNAL_STRENGTH_MAP:
        return SIGNAL_STRENGTH_MAP[label]

    if isinstance(value, bool):
        return 1.0 if value else 0.0

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        text = str(value or "").strip().lower()
        return SIGNAL_STRENGTH_MAP.get(text, 0.0)

    if numeric <= 0:
        return 0.0

    severity_factor = max(float(severity) / 5.0, 0.01)
    if numeric <= severity_factor + 1e-9:
        return min(numeric / severity_factor, 1.0)
    return min(numeric, 1.0)


def normalize_rule_evidence(
    *,
    rule_id: str,
    evidence_type: str,
    severity: int,
    raw_value: Any,
    display_label: str | None = None,
) -> NormalizedRuleEvidence:
    """Translate one rule hit into the common PHASE1 aggregation contract."""

    metadata = RULE_SCORING_REGISTRY.get(
        rule_id,
        RuleScoringMetadata(
            rule_id=rule_id,
            evidence_type=evidence_type,
            evidence_strength="medium" if severity >= 3 else "weak",
        ),
    )
    signal_strength = _rule_specific_signal_strength(
        rule_id=rule_id,
        raw_value=raw_value,
        severity=severity,
        display_label=display_label,
    )
    severity_factor = max(min(float(severity) / 5.0, 1.0), 0.0)
    evidence_factor = EVIDENCE_STRENGTH_FACTOR.get(metadata.evidence_strength, 0.45)
    role_factor = SCORING_ROLE_FACTOR.get(metadata.scoring_role, 1.0)
    normalized_score = (
        signal_strength
        * severity_factor
        * evidence_factor
        * role_factor
        * metadata.contribution_weight
    )
    label_key = str(display_label or "").strip().lower()
    floor_eligible = (
        metadata.floor_eligible_labels is None or label_key in metadata.floor_eligible_labels
    )
    return NormalizedRuleEvidence(
        rule_id=rule_id,
        evidence_type=evidence_type,
        severity=severity,
        display_label=display_label or "",
        signal_strength=max(0.0, min(signal_strength, 1.0)),
        evidence_strength=metadata.evidence_strength,
        scoring_role=metadata.scoring_role,
        normalized_score=max(0.0, min(float(normalized_score), 1.0)),
        final_topic=metadata.final_topic,
        secondary_topics=metadata.secondary_topics,
        standalone_rankable=metadata.standalone_rankable,
        floor_policy_ids=metadata.floor_policy_ids if floor_eligible else (),
        combo_policy_ids=metadata.combo_policy_ids,
        fraud_scenario_tags=metadata.fraud_scenario_tags,
    )


def _rule_specific_signal_strength(
    *,
    rule_id: str,
    raw_value: Any,
    severity: int,
    display_label: str | None,
) -> float:
    label = str(display_label or "").strip().lower()
    # L1-04: binary 통일 — 옛 L104 bucket 등급 제거. generic fallback 으로 일관된 binary 강도.
    if rule_id == "L1-03":
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        severity_factor = max(min(float(severity) / 5.0, 1.0), 0.01)
        return min(numeric, 1.0) / severity_factor
    if rule_id == "L1-07":
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        severity_factor = max(min(float(severity) / 5.0, 1.0), 0.01)
        return min(numeric, 1.0) / severity_factor
    # L3-09: binary 통일 — 옛 L309 aging 등급 제거. generic fallback 으로 일관된 binary 강도.
    if rule_id == "L3-10":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    # L4-04: binary 통일 — 옛 rare-pair bucket(0.25/0.35/0.45) 차등 폐기.
    # 발화(raw>0)면 강도 1.0, bucket 크기 무시. 강도·정황·조합은 통합점수·case priority 소관.
    if rule_id == "L4-04":
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        return 1.0 if numeric > 0.0 else 0.0
    # L3-12: macro_only(2026-06-21) → _combined_normalized_rule_details 에서 선행 0강제되어 이
    # 분기는 실제 도달하지 않는다. registry 폴백(primary) 점수 부착 방지용으로만 유지.
    if rule_id == "L3-12":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L3-06":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L4-05":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    # L4-03: binary 통일 — 수행중요성 절대임계 초과 binary. generic fallback 으로 일관된 binary 강도.
    return normalize_signal_strength(
        raw_value,
        severity=severity,
        display_label=display_label,
    )
