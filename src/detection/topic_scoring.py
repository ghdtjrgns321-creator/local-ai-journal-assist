"""PHASE1 auditor-facing topic scoring utilities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.detection.rule_scoring import RULE_SCORING_REGISTRY, TOPIC_REGISTRY

TOPIC_SCORE_WEIGHTS: dict[str, float] = {
    "max_primary_rule_score": 0.62,
    "secondary_evidence_score": 0.08,
    "corroboration_score": 0.08,
    "materiality_score": 0.08,
    "repeat_score": 0.05,
    "macro_context_score": 0.03,
    "audit_evidence_score": 0.06,
}

DEFAULT_TOPIC_CAP = 1.0
DEFAULT_TOPIC_FLOORS: dict[str, float] = {
    "approval_control_high": 0.75,
    "duplicate_outflow_high": 0.75,
    "intercompany_exception": 0.45,
}
DEFAULT_COMBO_FLOORS: dict[str, float] = {
    "batch_combo": 0.45,
    "work_scope_combo": 0.45,
    "fictitious_entry_medium": 0.60,
    "fictitious_entry_high": 0.75,
    "period_end_adjustment_medium": 0.60,
    "period_end_adjustment_high": 0.75,
    "embezzlement_concealment_medium": 0.60,
    "embezzlement_concealment_high": 0.75,
    "circular_transaction_medium": 0.45,
    "circular_transaction_high": 0.75,
    "approval_bypass_medium": 0.60,
    "approval_bypass_high": 0.75,
}

_DUPLICATE_ENTRY_RULES = {"L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d"}
_REVENUE_OR_AMOUNT_RULES = {"L4-01", "L4-03"}
_TIMING_SEED_RULES = {"L3-04", "L3-07", "L3-11", "L1-08"}
_OUTFLOW_RULES = {"L2-02", "L2-05"} | _DUPLICATE_ENTRY_RULES
_APPROVAL_BYPASS_RULES = {"L1-04", "L1-05", "L1-06", "L1-07"}
_RELATED_PARTY_RULES = {"L3-03", "IC01", "IC02", "IC03"}
_AMOUNT_OR_TIMING_RULES = {"L4-03", "L3-04", "L3-05", "L3-11"}
_WEAK_DESCRIPTION_OR_SENSITIVE_ACCOUNT_RULES = {"L3-08", "L3-10", "L4-04"}


@dataclass(frozen=True)
class _FraudComboFloor:
    topic_id: str
    policy_id: str
    floor: float
    tag: str
    reason: str


@dataclass(frozen=True)
class TopicScoreBreakdown:
    """Component scores behind one PHASE1 topic score."""

    topic_id: str
    score: float
    max_primary_rule_score: float
    secondary_evidence_score: float
    corroboration_score: float
    materiality_score: float
    repeat_score: float
    macro_context_score: float
    audit_evidence_score: float
    floor_policy_ids: tuple[str, ...]
    combo_policy_ids: tuple[str, ...]
    fraud_combo_policy_ids: tuple[str, ...]
    fraud_combo_tags: tuple[str, ...]
    has_rankable_primary: bool
    has_combo_floor: bool


@dataclass(frozen=True)
class _EvidenceView:
    rule_id: str
    normalized_score: float
    scoring_role: str
    final_topic: str | None
    secondary_topics: tuple[str, ...]
    standalone_rankable: bool
    floor_policy_ids: tuple[str, ...]
    combo_policy_ids: tuple[str, ...]
    fraud_scenario_tags: tuple[str, ...]


def compute_topic_scores(
    evidences: Iterable[Any],
    *,
    materiality_score: float | Mapping[str, float] = 0.0,
    repeat_score: float | Mapping[str, float] = 0.0,
    audit_evidence_score: float | Mapping[str, float] = 0.0,
    topic_caps: Mapping[str, float] | None = None,
    topic_floor_policies: Mapping[str, float] | None = None,
    combo_floor_policies: Mapping[str, float] | None = None,
    return_breakdown: bool = False,
) -> dict[str, float] | dict[str, TopicScoreBreakdown]:
    """Compute PHASE1 v1 topic scores for one row or case.

    A topic only receives a non-zero standalone ranking score when it has at
    least one rankable primary rule. Booster, combo-only, and macro-only rules
    can lift an existing topic but cannot seed a Top N row by themselves.
    """

    views = [_coerce_evidence(evidence) for evidence in evidences]
    caps = {topic_id: DEFAULT_TOPIC_CAP for topic_id in TOPIC_REGISTRY}
    caps.update({str(k): float(v) for k, v in (topic_caps or {}).items()})
    repeat_by_topic = {
        topic_id: _topic_component(repeat_score, topic_id) for topic_id in TOPIC_REGISTRY
    }
    combo_policies = {**DEFAULT_COMBO_FLOORS, **(combo_floor_policies or {})}
    fraud_combo_floors = _fraud_combo_floor_results(
        views,
        combo_policies=combo_policies,
        repeat_by_topic=repeat_by_topic,
    )

    breakdowns: dict[str, TopicScoreBreakdown] = {}
    for topic_id in TOPIC_REGISTRY:
        topic_views = [view for view in views if _touches_topic(view, topic_id)]
        primary_views = [
            view
            for view in topic_views
            if (
                view.final_topic == topic_id
                and view.scoring_role == "primary"
                and view.standalone_rankable
                and view.normalized_score > 0
            )
        ]
        has_rankable_primary = bool(primary_views)
        max_primary = max((view.normalized_score for view in primary_views), default=0.0)

        if has_rankable_primary:
            secondary = max(
                (
                    view.normalized_score
                    for view in topic_views
                    if topic_id in view.secondary_topics and view.normalized_score > 0
                ),
                default=0.0,
            )
            corroboration = _corroboration_score(topic_views, primary_views)
            macro_context = max(
                (
                    view.normalized_score
                    for view in topic_views
                    if view.scoring_role == "macro_only" and view.normalized_score > 0
                ),
                default=0.0,
            )
            audit_evidence = _topic_component(audit_evidence_score, topic_id)
        else:
            secondary = 0.0
            corroboration = 0.0
            macro_context = 0.0
            audit_evidence = 0.0

        materiality = _topic_component(materiality_score, topic_id)
        repeat = _topic_component(repeat_score, topic_id)
        base_score = (
            TOPIC_SCORE_WEIGHTS["max_primary_rule_score"] * max_primary
            + TOPIC_SCORE_WEIGHTS["secondary_evidence_score"] * secondary
            + TOPIC_SCORE_WEIGHTS["corroboration_score"] * corroboration
            + TOPIC_SCORE_WEIGHTS["materiality_score"] * materiality
            + TOPIC_SCORE_WEIGHTS["repeat_score"] * repeat
            + TOPIC_SCORE_WEIGHTS["macro_context_score"] * macro_context
            + TOPIC_SCORE_WEIGHTS["audit_evidence_score"] * audit_evidence
        )
        score = min(base_score, caps.get(topic_id, DEFAULT_TOPIC_CAP))
        floor_score, floor_policy_ids = apply_topic_floors(
            {topic_id: score},
            topic_views,
            floor_policies=topic_floor_policies,
            require_primary=has_rankable_primary,
            return_policy_ids=True,
        )
        combo_score, combo_policy_ids = apply_combo_floors(
            floor_score,
            views,
            combo_policies=combo_policies,
            require_primary=has_rankable_primary,
            return_policy_ids=True,
            repeat_score=repeat_by_topic,
        )
        fraud_floors_for_topic = fraud_combo_floors.get(topic_id, ())
        fraud_combo_policy_ids = tuple(floor.reason for floor in fraud_floors_for_topic)
        fraud_combo_tags = tuple(dict.fromkeys(floor.tag for floor in fraud_floors_for_topic))
        final_score = min(combo_score[topic_id], caps.get(topic_id, DEFAULT_TOPIC_CAP))
        breakdowns[topic_id] = TopicScoreBreakdown(
            topic_id=topic_id,
            score=_clamp(final_score),
            max_primary_rule_score=_clamp(max_primary),
            secondary_evidence_score=_clamp(secondary),
            corroboration_score=_clamp(corroboration),
            materiality_score=_clamp(materiality),
            repeat_score=_clamp(repeat),
            macro_context_score=_clamp(macro_context),
            audit_evidence_score=_clamp(audit_evidence),
            floor_policy_ids=tuple(floor_policy_ids.get(topic_id, ())),
            combo_policy_ids=tuple(combo_policy_ids.get(topic_id, ())),
            fraud_combo_policy_ids=fraud_combo_policy_ids,
            fraud_combo_tags=fraud_combo_tags,
            has_rankable_primary=has_rankable_primary,
            has_combo_floor=bool(fraud_floors_for_topic or combo_policy_ids.get(topic_id)),
        )

    if return_breakdown:
        return breakdowns
    return {topic_id: breakdown.score for topic_id, breakdown in breakdowns.items()}


def apply_topic_floors(
    topic_scores: Mapping[str, float],
    evidences: Iterable[Any],
    *,
    floor_policies: Mapping[str, float] | None = None,
    require_primary: bool = True,
    return_policy_ids: bool = False,
) -> dict[str, float] | tuple[dict[str, float], dict[str, tuple[str, ...]]]:
    """Apply explicit rule floor policies without creating macro-only rows."""

    policies = {**DEFAULT_TOPIC_FLOORS, **(floor_policies or {})}
    scores = {str(topic): _clamp(score) for topic, score in topic_scores.items()}
    applied: dict[str, list[str]] = {topic: [] for topic in scores}
    if require_primary:
        views = [_coerce_evidence(evidence) for evidence in evidences]
        for view in views:
            if view.normalized_score <= 0 or view.scoring_role == "macro_only":
                continue
            topic_id = view.final_topic
            if topic_id not in scores:
                continue
            for policy_id in view.floor_policy_ids:
                floor = policies.get(policy_id)
                if floor is None:
                    continue
                scores[topic_id] = max(scores[topic_id], _clamp(floor))
                applied[topic_id].append(policy_id)
    applied_tuple = {topic: tuple(dict.fromkeys(ids)) for topic, ids in applied.items()}
    if return_policy_ids:
        return scores, applied_tuple
    return scores


def apply_combo_floors(
    topic_scores: Mapping[str, float],
    evidences: Iterable[Any],
    *,
    combo_policies: Mapping[str, float] | None = None,
    require_primary: bool = True,
    return_policy_ids: bool = False,
    repeat_score: float | Mapping[str, float] = 0.0,
) -> dict[str, float] | tuple[dict[str, float], dict[str, tuple[str, ...]]]:
    """Apply combo-only and fraud-combo floors to existing official topics."""

    policies = {**DEFAULT_COMBO_FLOORS, **(combo_policies or {})}
    scores = {str(topic): _clamp(score) for topic, score in topic_scores.items()}
    applied: dict[str, list[str]] = {topic: [] for topic in scores}
    views = [_coerce_evidence(evidence) for evidence in evidences]
    if require_primary:
        for view in views:
            if view.normalized_score <= 0 or view.scoring_role != "combo_only":
                continue
            topic_id = view.final_topic
            if topic_id not in scores:
                continue
            for policy_id in view.combo_policy_ids:
                floor = policies.get(policy_id)
                if floor is None:
                    continue
                scores[topic_id] = max(scores[topic_id], _clamp(floor))
                applied[topic_id].append(policy_id)
    repeat_by_topic = {
        topic_id: _topic_component(repeat_score, topic_id) for topic_id in TOPIC_REGISTRY
    }
    for topic_id, floors in _fraud_combo_floor_results(
        views,
        combo_policies=policies,
        repeat_by_topic=repeat_by_topic,
    ).items():
        if topic_id not in scores:
            continue
        for floor in floors:
            scores[topic_id] = max(scores[topic_id], _clamp(floor.floor))
            applied[topic_id].append(floor.reason)
    applied_tuple = {topic: tuple(dict.fromkeys(ids)) for topic, ids in applied.items()}
    if return_policy_ids:
        return scores, applied_tuple
    return scores


def compute_fraud_scenario_tags(evidences: Iterable[Any]) -> tuple[str, ...]:
    """Return ordered fraud scenario tags carried by positive evidence and combos."""

    tags: list[str] = []
    views = [_coerce_evidence(evidence) for evidence in evidences]
    for view in views:
        if view.normalized_score <= 0:
            continue
        tags.extend(view.fraud_scenario_tags)
    for floors in _fraud_combo_floor_results(views).values():
        tags.extend(floor.tag for floor in floors)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


def pick_primary_topic(topic_scores: Mapping[str, float]) -> str | None:
    """Pick the highest-scoring official topic using registry order as tie-break."""

    best_topic: str | None = None
    best_score = 0.0
    for topic_id in TOPIC_REGISTRY:
        score = _clamp(topic_scores.get(topic_id, 0.0))
        if score > best_score:
            best_topic = topic_id
            best_score = score
    return best_topic


def _coerce_evidence(evidence: Any) -> _EvidenceView:
    getter = (
        evidence.get
        if isinstance(evidence, Mapping)
        else lambda key, default=None: getattr(evidence, key, default)
    )
    rule_id = str(getter("rule_id", ""))
    metadata = RULE_SCORING_REGISTRY.get(rule_id)
    return _EvidenceView(
        rule_id=rule_id,
        normalized_score=_clamp(getter("normalized_score", 0.0)),
        scoring_role=str(getter("scoring_role", metadata.scoring_role if metadata else "primary")),
        final_topic=getter("final_topic", metadata.final_topic if metadata else None),
        secondary_topics=tuple(
            getter("secondary_topics", metadata.secondary_topics if metadata else ())
        ),
        standalone_rankable=bool(
            getter("standalone_rankable", metadata.standalone_rankable if metadata else True)
        ),
        floor_policy_ids=tuple(
            getter("floor_policy_ids", metadata.floor_policy_ids if metadata else ())
        ),
        combo_policy_ids=tuple(
            getter("combo_policy_ids", metadata.combo_policy_ids if metadata else ())
        ),
        fraud_scenario_tags=tuple(
            getter("fraud_scenario_tags", metadata.fraud_scenario_tags if metadata else ())
        ),
    )


def _touches_topic(evidence: _EvidenceView, topic_id: str) -> bool:
    return evidence.final_topic == topic_id or topic_id in evidence.secondary_topics


def _corroboration_score(
    topic_views: list[_EvidenceView],
    primary_views: list[_EvidenceView],
) -> float:
    primary_ids = {view.rule_id for view in primary_views}
    corroborating_ids = {
        view.rule_id
        for view in topic_views
        if view.normalized_score > 0
        and view.rule_id not in primary_ids
        and view.scoring_role in {"primary", "booster", "combo_only"}
    }
    return _clamp(len(corroborating_ids) / 3.0)


def _fraud_combo_floor_results(
    evidences: Iterable[_EvidenceView],
    *,
    combo_policies: Mapping[str, float] | None = None,
    repeat_by_topic: Mapping[str, float] | None = None,
) -> dict[str, tuple[_FraudComboFloor, ...]]:
    policies = {**DEFAULT_COMBO_FLOORS, **(combo_policies or {})}
    views = [view for view in evidences if view.normalized_score > 0]
    rule_ids = {view.rule_id for view in views}
    results: dict[str, list[_FraudComboFloor]] = {}

    def add(topic_id: str, policy_id: str, tag: str, reason: str) -> None:
        floor = policies.get(policy_id)
        if floor is None:
            return
        results.setdefault(topic_id, []).append(
            _FraudComboFloor(
                topic_id=topic_id,
                policy_id=policy_id,
                floor=_clamp(floor),
                tag=tag,
                reason=reason,
            )
        )

    has_revenue_or_amount = bool(rule_ids & _REVENUE_OR_AMOUNT_RULES)
    has_duplicate_entry = bool(rule_ids & _DUPLICATE_ENTRY_RULES)
    has_timing_seed = bool(rule_ids & _TIMING_SEED_RULES)
    has_outflow = bool(rule_ids & _OUTFLOW_RULES)
    has_approval_bypass = bool(rule_ids & _APPROVAL_BYPASS_RULES)
    has_related_party = bool(rule_ids & _RELATED_PARTY_RULES)
    has_amount_or_timing = bool(rule_ids & _AMOUNT_OR_TIMING_RULES)
    has_weak_description_or_sensitive = bool(
        rule_ids & _WEAK_DESCRIPTION_OR_SENSITIVE_ACCOUNT_RULES
    )

    if (
        has_revenue_or_amount
        and "L3-02" in rule_ids
        and ("L4-04" in rule_ids or has_duplicate_entry)
    ):
        add(
            "revenue_statistical",
            "fictitious_entry_high",
            "fictitious_entry_risk",
            "revenue_or_amount_outlier + manual_adjustment + rare_or_duplicate_pattern",
        )
    elif ("L4-01" in rule_ids and "L3-04" in rule_ids) or (
        "L4-03" in rule_ids and "L4-06" in rule_ids and "L3-02" in rule_ids
    ):
        add(
            "revenue_statistical",
            "fictitious_entry_medium",
            "fictitious_entry_risk",
            "revenue_or_amount_outlier + closing_or_batch_context",
        )

    if has_timing_seed and "L4-03" in rule_ids and has_weak_description_or_sensitive:
        add(
            "closing_timing",
            "period_end_adjustment_high",
            "period_end_adjustment_risk",
            "period_end_or_late_posting + high_amount + weak_description_or_sensitive_account",
        )
    elif "L3-11" in rule_ids and has_revenue_or_amount:
        add(
            "closing_timing",
            "period_end_adjustment_high",
            "period_end_adjustment_risk",
            "cutoff_mismatch + revenue_or_high_amount",
        )

    if has_outflow and has_approval_bypass:
        add(
            "duplicate_outflow",
            "embezzlement_concealment_high",
            "embezzlement_concealment_risk",
            "outflow_or_duplicate + approval_bypass",
        )
    elif "L2-01" in rule_ids and {"L1-04", "L1-05"} & rule_ids:
        add(
            "duplicate_outflow",
            "embezzlement_concealment_medium",
            "embezzlement_concealment_risk",
            "threshold_splitting + approval_bypass",
        )

    intercompany_repeat = _topic_component(repeat_by_topic or 0.0, "intercompany_cycle")
    if has_related_party and has_amount_or_timing and intercompany_repeat > 0:
        add(
            "intercompany_cycle",
            "circular_transaction_high",
            "circular_transaction_risk",
            "related_party_or_ic + amount_or_timing_anomaly + repeat_or_counterparty_cycle",
        )
    elif has_related_party and has_amount_or_timing:
        add(
            "intercompany_cycle",
            "circular_transaction_medium",
            "circular_transaction_risk",
            "related_party_or_ic + amount_or_timing_anomaly",
        )
    elif "L3-03" in rule_ids and "L4-04" in rule_ids:
        add(
            "intercompany_cycle",
            "circular_transaction_medium",
            "circular_transaction_risk",
            "related_party_or_ic + rare_account_pair",
        )
    elif {"IC01", "IC02", "IC03"} & rule_ids:
        add(
            "intercompany_cycle",
            "circular_transaction_medium",
            "circular_transaction_risk",
            "related_party_or_ic + intercompany_exception",
        )

    has_strong_approval_context = (
        "L4-03" in rule_ids
        or "L3-11" in rule_ids
        or {"L3-04", "L3-02"}.issubset(rule_ids)
        or {"L3-06", "L3-02"}.issubset(rule_ids)
    )
    if has_approval_bypass and has_strong_approval_context:
        add(
            "approval_control",
            "approval_bypass_high",
            "approval_bypass_risk",
            "approval_bypass + high_amount_or_cutoff_or_strong_abnormal_timing",
        )
    elif {"L1-09", "L4-03", "L3-02"}.issubset(rule_ids):
        add(
            "approval_control",
            "approval_bypass_medium",
            "approval_bypass_risk",
            "missing_approval_trace + high_amount + manual_adjustment",
        )
    elif has_approval_bypass and "L3-02" in rule_ids:
        add(
            "approval_control",
            "approval_bypass_medium",
            "approval_bypass_risk",
            "approval_bypass + manual_adjustment_context",
        )
    elif has_approval_bypass and "L3-06" in rule_ids:
        add(
            "approval_control",
            "approval_bypass_medium",
            "approval_bypass_risk",
            "approval_bypass + after_hours_context",
        )
    elif has_approval_bypass and "L3-05" in rule_ids:
        add(
            "approval_control",
            "approval_bypass_medium",
            "approval_bypass_risk",
            "approval_bypass + non_business_day_context",
        )
    elif "L3-12" in rule_ids and {"L1-05", "L1-07"} & rule_ids:
        add(
            "approval_control",
            "approval_bypass_medium",
            "approval_bypass_risk",
            "work_scope_concentration + approval_bypass",
        )

    return {topic_id: tuple(floors) for topic_id, floors in results.items()}


def _topic_component(value: float | Mapping[str, float], topic_id: str) -> float:
    if isinstance(value, Mapping):
        return _clamp(value.get(topic_id, 0.0))
    return _clamp(value)


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(numeric, 1.0))
