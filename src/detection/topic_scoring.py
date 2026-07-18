"""PHASE1 topic 귀속·standalone 게이트 (tier 자동 등급 폐지 — 2026-07-17).

구 체계(가중합 → floor/combo/fraud-combo → HIGH/MEDIUM tier)는
docs/spec/PHASE1_COMBO_BUILDER_SPEC.md 로 대체 폐지됐다(§6 폐지 목록).
등급(HIGH/MEDIUM)은 어디서도 만들지 않는다 — 검토 조합은 감사인이 조합 빌더에서 선택한다.

남은 책임 두 가지:
  1) topic 귀속 — evidence 를 TOPIC_REGISTRY 주제로 묶고 has_rankable_primary 산출
  2) standalone 게이트 — booster/macro/combo_only 만 있는 묶음(CONTEXT)은 단독 승격 불가.
     LOW/CONTEXT 는 위험 등급이 아니라 "단독으로 큐에 설 자격" 게이트다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from src.detection.rule_scoring import RULE_SCORING_REGISTRY, TOPIC_REGISTRY

# 순서형 2단 게이트 (등급 아님). HIGH/MEDIUM 은 폐지 — 생산 경로 없음.
TIER_RANK: dict[str, int] = {"LOW": 1, "CONTEXT": 0}


@dataclass(frozen=True)
class TopicScoreBreakdown:
    """topic 귀속 분해. score 는 항상 0.0 — 가중합·floor·combo 폐지 후 호환 유지용 필드."""

    topic_id: str
    score: float
    has_rankable_primary: bool


@dataclass(frozen=True)
class TierBreakdown:
    """topic 별 standalone 게이트 결과. tier ∈ {"LOW", "CONTEXT"}."""

    topic_id: str
    tier: str
    has_rankable_primary: bool


@dataclass(frozen=True)
class _EvidenceView:
    rule_id: str
    normalized_score: float
    scoring_role: str
    final_topic: str | None
    secondary_topics: tuple[str, ...]
    standalone_rankable: bool
    fraud_scenario_tags: tuple[str, ...]


def compute_topic_scores(
    evidences: Iterable[Any],
    *,
    return_breakdown: bool = False,
) -> dict[str, float] | dict[str, TopicScoreBreakdown]:
    """topic 귀속 분해를 산출한다. 점수는 만들지 않는다(전부 0.0).

    각 topic 의 has_rankable_primary = 그 topic 을 final_topic 으로 가진
    standalone primary 룰이 양성 발화했는가. booster/macro/combo_only 단독은 False.
    """

    views = [_coerce_evidence(evidence) for evidence in evidences]
    topic_views_by_topic: dict[str, list[_EvidenceView]] = {
        topic_id: [] for topic_id in TOPIC_REGISTRY
    }
    for view in views:
        touched_topics: set[str] = set()
        if view.final_topic in topic_views_by_topic:
            touched_topics.add(str(view.final_topic))
        touched_topics.update(
            topic_id for topic_id in view.secondary_topics if topic_id in topic_views_by_topic
        )
        for topic_id in touched_topics:
            topic_views_by_topic[topic_id].append(view)

    breakdowns: dict[str, TopicScoreBreakdown] = {}
    for topic_id in TOPIC_REGISTRY:
        has_rankable_primary = any(
            view.final_topic == topic_id
            and view.scoring_role == "primary"
            and view.standalone_rankable
            and view.normalized_score > 0
            for view in topic_views_by_topic[topic_id]
        )
        breakdowns[topic_id] = TopicScoreBreakdown(
            topic_id=topic_id,
            score=0.0,
            has_rankable_primary=has_rankable_primary,
        )

    if return_breakdown:
        return breakdowns
    return {topic_id: breakdown.score for topic_id, breakdown in breakdowns.items()}


def compute_topic_tiers(
    evidences: Iterable[Any],
    *,
    breakdowns: Mapping[str, TopicScoreBreakdown] | None = None,
) -> dict[str, TierBreakdown]:
    """topic 별 standalone 게이트: LOW(standalone primary 있음) / CONTEXT(그 외).

    HIGH/MEDIUM 승격 경로는 폐지됐다 — combo floor·config priority floor 어느 쪽도
    게이트를 올리지 못한다.
    """
    if breakdowns is None:
        breakdowns = cast(
            "dict[str, TopicScoreBreakdown]",
            compute_topic_scores(evidences, return_breakdown=True),
        )
    return {
        topic_id: TierBreakdown(
            topic_id=topic_id,
            tier="LOW" if breakdown.has_rankable_primary else "CONTEXT",
            has_rankable_primary=breakdown.has_rankable_primary,
        )
        for topic_id, breakdown in breakdowns.items()
    }


def case_tier(tiers: Mapping[str, TierBreakdown]) -> str:
    """묶음의 게이트 대표값 (LOW > CONTEXT)."""
    best = "CONTEXT"
    for breakdown in tiers.values():
        if TIER_RANK.get(breakdown.tier, 0) > TIER_RANK.get(best, 0):
            best = breakdown.tier
    return best


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


def compute_fraud_scenario_tags(evidences: Iterable[Any]) -> tuple[str, ...]:
    """양성 evidence 가 지닌 fraud scenario 태그(룰 메타데이터 기원)만 수집.

    구 fraud-combo 태그 주입은 tier 폐지와 함께 제거됐다.
    """

    tags: list[str] = []
    for evidence in evidences:
        view = _coerce_evidence(evidence)
        if view.normalized_score <= 0:
            continue
        tags.extend(view.fraud_scenario_tags)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


def _coerce_evidence(evidence: Any) -> _EvidenceView:
    if isinstance(evidence, _EvidenceView):
        return evidence
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
        fraud_scenario_tags=tuple(
            getter("fraud_scenario_tags", metadata.fraud_scenario_tags if metadata else ())
        ),
    )


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(numeric, 1.0))
