"""PHASE1 auditor-facing topic scoring utilities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Any, cast

from src.detection.rule_scoring import RULE_SCORING_REGISTRY, TOPIC_REGISTRY

DEFAULT_TOPIC_CAP = 1.0
DEFAULT_TOPIC_FLOORS: dict[str, float] = {}
DEFAULT_COMBO_FLOORS: dict[str, float] = {
    "fictitious_entry_medium": 0.60,
    "fictitious_entry_high": 0.75,
    "period_end_adjustment_high": 0.75,
    "embezzlement_concealment_medium": 0.60,
    "embezzlement_concealment_high": 0.75,
    "suspense_concealment_medium": 0.60,
    "suspense_concealment_high": 0.75,
    "expense_capitalization_medium": 0.60,
    "expense_capitalization_high": 0.75,
    "related_party_reversal_medium": 0.60,
    "rare_account_bypass_medium": 0.60,
    "approval_bypass_high": 0.75,
}

_DUPLICATE_ENTRY_RULES = {"L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d"}
_REVENUE_OR_AMOUNT_RULES = {"L4-01", "L4-03"}
# §3.0 HIGH-4 첫 leg (L3-04|L3-11). §8(5) "L3-07·L1-08@H4 헛다리 삭제"로 두 룰 제거.
_TIMING_SEED_RULES = {"L3-04", "L3-11"}
_OUTFLOW_RULES = {"L2-02", "L2-05"} | _DUPLICATE_ENTRY_RULES
_APPROVAL_BYPASS_RULES = {"L1-04", "L1-05", "L1-06", "L1-07", "L1-07-02"}
# §3.0 HIGH-4 둘째 leg (L3-10|L4-04|L4-03). §8(1) 고액 L4-03 복원, 적요부실 룰은 폐기됨.
_PERIOD_END_CORROBORANT_RULES = {"L3-10", "L4-04", "L4-03"}
# Why: 가공전표(fictitious_entry_high) 조합의 "셋째 다리"(2차 정황) 풀.
#      FSS HIGH 17건 재감사(A안, HIGH_COMBO_GROUNDING.md §5b / DECISION D075)에서
#      같은 가공전표 스토리인데 셋째 정황만 다른 11건이 그물을 빠져나간 것을 확인 →
#      기존 (L4-04·중복L2-03)에 관계사·민감계정·자기승인·cutoff 를 실증에 맞게 추가.
#      과탐 가드(정상 v42j 측정, HIGH ≤ 2%): 후보였던 L3-04(기말)·승인일공백은
#      정상 결산전표에 흔해 과발화 → 제외. 기말 fraud 는 closing_timing 조합의 영역이다.
#      유지한 L3-03·L1-05·L3-11 은 정상 발화 0~54 로 특이적이며 FSS 10/11건을 커버한다.
#      L3-10 제거(§8(5) HIGH-1 2차정황 0/67 헛다리 삭제) → §3.0 HIGH-1 풀
#      {L4-04|L2-03|L3-03|L1-05|L3-11} 와 일치(L2-03=_DUPLICATE_ENTRY_RULES).
_FICTITIOUS_SECONDARY_RULES = {
    "L4-04",  # 희소계정쌍
    "L3-03",  # 관계사 거래 (분식 실행 통로)
    "L1-05",  # 자기승인
    "L3-11",  # cutoff 위반
} | _DUPLICATE_ENTRY_RULES


@dataclass(frozen=True)
class _FraudComboFloor:
    topic_id: str
    policy_id: str
    floor: float
    tag: str
    reason: str


@dataclass(frozen=True)
class TopicScoreBreakdown:
    """PHASE1 topic 트리거 분해 (가중합 점수 폐기 — tier 트리거 정보만 보유).

    `score`는 가중합이 아니라 발화한 floor/combo 의 tier 컷값(0.75/0.60/0.45 등)이다.
    band·정렬은 tier(`compute_topic_tiers`)가 결정하며, 본 구조는 어떤 트리거가
    발화했는지(floor/combo policy ids)와 has_rankable_primary 만 운반한다.
    """

    topic_id: str
    score: float
    floor_policy_ids: tuple[str, ...]
    combo_policy_ids: tuple[str, ...]
    fraud_combo_policy_ids: tuple[str, ...]
    fraud_combo_tags: tuple[str, ...]
    has_rankable_primary: bool
    has_combo_floor: bool


# PHASE1 tier (PHASE1_TIER_SCORING_SPEC.md §2). 순서형 — 크기 의미 없음.
TIER_RANK: dict[str, int] = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "CONTEXT": 0}
# 기존 floor/combo 숫자값을 tier 라벨로 분류만 한다(값 자체는 band 결정에 노출 안 함).
_HIGH_FLOOR_MIN = 0.75
_MEDIUM_FLOOR_MIN = 0.45


@dataclass(frozen=True)
class TierBreakdown:
    """PHASE1 tier per topic (PHASE1_TIER_SCORING_SPEC §6)."""

    topic_id: str
    tier: str
    fired_triggers: tuple[str, ...]
    has_rankable_primary: bool


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
    topic_floor_policies: Mapping[str, float] | None = None,
    combo_floor_policies: Mapping[str, float] | None = None,
    fraud_combo_rule_scope: AbstractSet[str] | None = None,
    return_breakdown: bool = False,
) -> dict[str, float] | dict[str, TopicScoreBreakdown]:
    """PHASE1 topic 트리거 분해를 산출한다 (가중합 점수 폐기).

    band·정렬은 tier(`compute_topic_tiers`)가 결정한다. 본 함수는 가중합을 계산하지
    않고, floor/combo 트리거의 발화 여부만 평가한다. 각 topic 의 `score`는 발화한
    floor/combo 의 tier 컷값(미발화 시 0)이며, has_rankable_primary 게이트로 booster/
    macro/combo-only 단독 승격을 막는다.
    """

    views = [_coerce_evidence(evidence) for evidence in evidences]
    combo_policies = {**DEFAULT_COMBO_FLOORS, **(combo_floor_policies or {})}
    fraud_combo_floors = _fraud_combo_floor_results(
        views,
        combo_policies=combo_policies,
        rule_scope=fraud_combo_rule_scope,
    )

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
        topic_views = topic_views_by_topic[topic_id]
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

        # 가중합 점수 폐기(2026-06-17): score 시작값 0 → floor/combo 적용값(tier 컷)만 남는다.
        # tier(band)는 발화한 floor/combo policy_ids + has_rankable_primary 로 결정한다.
        floor_score, floor_policy_ids = apply_topic_floors(
            {topic_id: 0.0},
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
            fraud_combo_rule_scope=fraud_combo_rule_scope,
        )
        fraud_floors_for_topic = fraud_combo_floors.get(topic_id, ())
        fraud_combo_policy_ids = tuple(floor.reason for floor in fraud_floors_for_topic)
        fraud_combo_tags = tuple(dict.fromkeys(floor.tag for floor in fraud_floors_for_topic))
        breakdowns[topic_id] = TopicScoreBreakdown(
            topic_id=topic_id,
            score=_clamp(combo_score[topic_id]),
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
    fraud_combo_rule_scope: AbstractSet[str] | None = None,
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
        rule_scope=fraud_combo_rule_scope,
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


def _floor_value_tier(value: float) -> str | None:
    """floor/combo 숫자값을 tier 라벨로 분류 (값 자체는 폐기, 분류에만 사용)."""
    if value >= _HIGH_FLOOR_MIN:
        return "HIGH"
    if value >= _MEDIUM_FLOOR_MIN:
        return "MEDIUM"
    return None


def compute_topic_tiers(
    evidences: Iterable[Any],
    *,
    topic_floor_policies: Mapping[str, float] | None = None,
    combo_floor_policies: Mapping[str, float] | None = None,
    fraud_combo_rule_scope: AbstractSet[str] | None = None,
    breakdowns: Mapping[str, TopicScoreBreakdown] | None = None,
) -> dict[str, TierBreakdown]:
    """PHASE1 v2 tier per topic (PHASE1_TIER_SCORING_SPEC §2-§3).

    가중합/floor 숫자 컷을 band 결정에 쓰지 않는다. 기존 트리거 조건(floor/combo/
    fraud-combo)의 발화 여부 + has_rankable_primary 로 순서형 tier 를 정한다.

    - HIGH    : HIGH 트리거(분류값 >= 0.75) 발화 + has_rankable_primary
    - MEDIUM  : MEDIUM 트리거(분류값 >= 0.45) 발화 + has_rankable_primary
    - LOW     : standalone primary seed 만 존재
    - CONTEXT : booster/macro/combo_only 신호만 (단독 큐 불가)

    `breakdowns`: 호출부가 이미 동일 인자로 compute_topic_scores(return_breakdown=True)를
    구한 경우 그걸 전달하면 재계산을 생략한다(전수 빌드 성능). tier 는 has_rankable_primary·
    floor_policy_ids·combo_policy_ids 만 쓰므로 materiality/repeat/audit 인자와 무관.
    """
    views = [_coerce_evidence(evidence) for evidence in evidences]
    if breakdowns is None:
        breakdowns = cast(
            "dict[str, TopicScoreBreakdown]",
            compute_topic_scores(
                views,
                topic_floor_policies=topic_floor_policies,
                combo_floor_policies=combo_floor_policies,
                fraud_combo_rule_scope=fraud_combo_rule_scope,
                return_breakdown=True,
            ),
        )
    floor_policies = {**DEFAULT_TOPIC_FLOORS, **(topic_floor_policies or {})}
    combo_policies = {**DEFAULT_COMBO_FLOORS, **(combo_floor_policies or {})}
    repeat_by_topic = {topic_id: 0.0 for topic_id in TOPIC_REGISTRY}
    fraud_floors = _fraud_combo_floor_results(
        views,
        combo_policies=combo_policies,
        repeat_by_topic=repeat_by_topic,
        rule_scope=fraud_combo_rule_scope,
    )

    result: dict[str, TierBreakdown] = {}
    for topic_id, breakdown in breakdowns.items():
        triggers: list[str] = []
        tier = "CONTEXT"
        # has_rankable_primary gate: booster/macro/combo_only 단독으로는 tier 승격 불가.
        if breakdown.has_rankable_primary:
            tier = "LOW"

            def _lift(policy_id: str, value: float) -> None:
                nonlocal tier
                candidate = _floor_value_tier(value)
                if candidate is None:
                    return
                triggers.append(policy_id)
                if TIER_RANK[candidate] > TIER_RANK[tier]:
                    tier = candidate

            for policy_id in breakdown.floor_policy_ids:
                _lift(policy_id, floor_policies.get(policy_id, 0.0))
            for policy_id in breakdown.combo_policy_ids:
                _lift(policy_id, combo_policies.get(policy_id, 0.0))
            for floor in fraud_floors.get(topic_id, ()):
                _lift(floor.policy_id, floor.floor)

        result[topic_id] = TierBreakdown(
            topic_id=topic_id,
            tier=tier,
            fired_triggers=tuple(dict.fromkeys(triggers)),
            has_rankable_primary=breakdown.has_rankable_primary,
        )
    return result


def case_tier(tiers: Mapping[str, TierBreakdown]) -> str:
    """case 의 최고 tier (HIGH > MEDIUM > LOW > CONTEXT)."""
    best = "CONTEXT"
    for breakdown in tiers.values():
        if TIER_RANK.get(breakdown.tier, 0) > TIER_RANK.get(best, 0):
            best = breakdown.tier
    return best


def pick_primary_topic_by_tier(tiers: Mapping[str, TierBreakdown]) -> str | None:
    """최고 tier 토픽을 primary 로 선택 (동률 시 TOPIC_REGISTRY 순서)."""
    best_topic: str | None = None
    best_rank = 0
    for topic_id in TOPIC_REGISTRY:
        breakdown = tiers.get(topic_id)
        if breakdown is None:
            continue
        rank = TIER_RANK.get(breakdown.tier, 0)
        if rank > best_rank:
            best_rank = rank
            best_topic = topic_id
    return best_topic if best_rank > 0 else None


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


def _fraud_combo_floor_results(
    evidences: Iterable[_EvidenceView],
    *,
    combo_policies: Mapping[str, float] | None = None,
    repeat_by_topic: Mapping[str, float] | None = None,
    rule_scope: AbstractSet[str] | None = None,
) -> dict[str, tuple[_FraudComboFloor, ...]]:
    policies = {**DEFAULT_COMBO_FLOORS, **(combo_policies or {})}
    views = [view for view in evidences if view.normalized_score > 0]
    rule_ids = {view.rule_id for view in views}
    # Why: fraud combo는 사람 행위(승인 우회·수기 조정·기말 조작)를 전제한다. 신뢰 가능한
    #      자동 전표에서만 발화한 룰은 콤보 트리거가 될 수 없다 — rule_scope가 주어지면
    #      그 안의 룰(비자동/위장의심 행 발화)만 콤보 평가에 쓴다 (OPEN_ISSUES #14).
    if rule_scope is not None:
        rule_ids = rule_ids & set(rule_scope)
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
    has_timing_seed = bool(rule_ids & _TIMING_SEED_RULES)
    has_outflow = bool(rule_ids & _OUTFLOW_RULES)
    has_approval_bypass = bool(rule_ids & _APPROVAL_BYPASS_RULES)
    has_period_end_corroborant = bool(rule_ids & _PERIOD_END_CORROBORANT_RULES)

    if (
        has_revenue_or_amount
        and "L3-02" in rule_ids
        and bool(rule_ids & _FICTITIOUS_SECONDARY_RULES)
    ):
        add(
            "revenue_statistical",
            "fictitious_entry_high",
            "fictitious_entry_risk",
            "revenue_or_amount_outlier + manual_adjustment + secondary_red_flag",
        )
    elif has_revenue_or_amount and "L3-02" in rule_ids:
        # §3.0 MEDIUM(b) 약화형 가공전표(HIGH-1): (L4-01|L4-03) & L3-02, 2차정황 없음.
        add(
            "revenue_statistical",
            "fictitious_entry_medium",
            "fictitious_entry_risk",
            "revenue_or_amount_outlier + manual_adjustment (no_secondary)",
        )

    # 고액(L4-03) 게이트 제거(2026-06-17): AS2401 §61 부정전표 특성 목록에 "고액"이 없다
    #   (라운드넘버는 §61(e)이나 금액 크기는 아님). 결산조작 근거는 ISA240 §32(b) 추정 편의지
    #   금액이 아니다. 고액은 중요성(ISA320)·tier 내부 랭킹 렌즈로만 쓰고 combo 게이트에서 뺀다.
    # §3.0 HIGH-4: (L3-04|L3-11) & (L3-10|L4-04|L4-03). 고액 L4-03 복원(§8(1)).
    # cutoff 분기(L3-11&(L4-01|L4-03))는 §8(5) "H4 미수정" — FSS 신규 0건(H1 흡수)으로 폐기.
    # period_end_adjustment_medium 분기도 폐기 확정(§3-3 B).
    if has_timing_seed and has_period_end_corroborant:
        add(
            "closing_timing",
            "period_end_adjustment_high",
            "period_end_adjustment_risk",
            "period_end_or_late_posting + weak_description_or_sensitive_account",
        )

    # A안(DECISION D075): 횡령은폐가 항상 승인 흔적을 남기지는 않는다. FSS 감리2013-1-가·
    # A-6유형-가는 역분개(L2-05) + 수기(L3-02)로 나타나 승인우회 필수 조건에서 탈락했다
    # → 승인우회 OR (역분개 + 수기) 분기 추가. 고액(L4-03) 게이트 제거(2026-06-17): 과탐가드용
    # 패딩이었고 AS2401 §61에 고액 특성 없음. 정상 reversal+clearing 과탐은 L2-05/L2-03 룰의
    # 발화조건(step3)에서 다루고 고액으로 되막지 않는다.
    # §3.0 HIGH-2: ((L2-02|L2-03|L2-05)&bypass) | ((L2-02|L2-03|L2-05)&L3-02&L4-03).
    #   §8(6) H2 일반화 — 자금유출+수기+고액 일반형(역분개 L2-05 한정 해제).
    if has_outflow and (has_approval_bypass or ("L3-02" in rule_ids and "L4-03" in rule_ids)):
        add(
            "duplicate_outflow",
            "embezzlement_concealment_high",
            "embezzlement_concealment_risk",
            "outflow_or_duplicate + (approval_bypass or manual_with_high_amount)",
        )
    elif "L2-01" in rule_ids and (rule_ids & {"L1-05", "L1-06", "L1-07", "L1-07-02"}):
        # §3.0 MEDIUM(a) 한도직하 분할: L2-01 & (L1-05|L1-06|L1-07|L1-07-02).
        #   §8(7) M2 — 한도초과 L1-04 는 한도분할과 논리 모순이라 bypass 에서 제외.
        add(
            "duplicate_outflow",
            "embezzlement_concealment_medium",
            "embezzlement_concealment_risk",
            "threshold_splitting + approval_bypass(no_L1-04)",
        )

    # Why: 가수금·미결제 계정(L3-09)은 횡령 자금이 정착하는 은폐 통로다. FSS 실증(P1 9개
    #      HIGH 사례 직접 확인)에서 L3-09 HIGH는 이상고액(L4-03) 8/9·횡령룰 7/9와 동반하나
    #      수기(L3-02)는 1/9뿐 — 조합을 outflow+L4-03으로 고정. 6/6 HIGH, 그중 3건은 승인우회
    #      조합이 못 잡는 신규 포착이라 독립 if로 둔다(high_combo_grounding.md §8 결정1).
    if "L3-09" in rule_ids and has_outflow and "L4-03" in rule_ids:
        add(
            "duplicate_outflow",
            "suspense_concealment_high",
            "embezzlement_concealment_risk",
            "suspense_aging + outflow_or_duplicate + high_amount",
        )
    elif "L3-09" in rule_ids and has_outflow:
        # §3.0 MEDIUM(b) 약화형 가수금(HIGH-3): L3-09 & (L2-02|L2-03|L2-05), 고액 없음.
        add(
            "duplicate_outflow",
            "suspense_concealment_medium",
            "embezzlement_concealment_risk",
            "suspense_aging + outflow (no_high_amount)",
        )

    # HIGH-7 → MEDIUM 이관(§8(4)): 역분개(L2-05)&관계사(L3-03) FSS HIGH 0/158, ISA550/240
    #   개념근거-only. §4a-4 형태 `L3-03 & L2-05`로 재정의(기말 L3-04 필수 제외).
    #   host=duplicate_outflow: 기말(L3-04) 제외로 closing_timing엔 standalone primary seed가
    #   없어 has_rankable_primary=False → CONTEXT로 죽는다. L2-05가 duplicate_outflow primary
    #   seed이므로 host를 그쪽으로 이관해 combo floor가 tier로 승격되게 한다(L3-03은 booster·
    #   standalone_rankable=False라 seed 불가).
    if {"L2-05", "L3-03"}.issubset(rule_ids):
        add(
            "duplicate_outflow",
            "related_party_reversal_medium",
            "related_party_reversal_risk",
            "reversal + related_party (no_period_end)",
        )

    # §3.0 HIGH-9 비용자산화: L2-04 & L3-02 & (L4-03|L3-04|L1-06). §8(6) H9 셋째슬롯 확장
    #   (L1-06 직무분리 동반 회복). host=account_logic(L2-04 primary seed).
    if {"L2-04", "L3-02"}.issubset(rule_ids) and (rule_ids & {"L4-03", "L3-04", "L1-06"}):
        add(
            "account_logic",
            "expense_capitalization_high",
            "expense_capitalization_risk",
            "expense_capitalization + manual + period_end",
        )
    elif {"L2-04", "L3-02"}.issubset(rule_ids):
        # §3.0 MEDIUM(b) 약화형 비용자산화(HIGH-9): L2-04 & L3-02, 셋째다리 없음.
        add(
            "account_logic",
            "expense_capitalization_medium",
            "expense_capitalization_risk",
            "expense_capitalization + manual (no_third_leg)",
        )

    # §3.0 MEDIUM(a) 희소계정쌍+승인우회: L4-04 & bypass. §8(7) M1 — bypass 세트 전체.
    #   host=account_logic(L4-04 primary seed).
    if "L4-04" in rule_ids and has_approval_bypass:
        add(
            "account_logic",
            "rare_account_bypass_medium",
            "rare_account_bypass_risk",
            "rare_account_pair + approval_bypass",
        )

    # intercompany_cycle circular_transaction combo 제거 (2026-06-14): IC/GR 제거에 따라
    # 관계사·순환 주제 자체가 폐지됨.

    # §3.0 HIGH-5 승인통제: bypass & (L4-03|L2-02|L2-03). §8(6) corroborant 확장
    #   (고액·중복지급·중복전표). approval_bypass_medium 전 분기 폐기(§8(5)).
    if has_approval_bypass and (
        "L4-03" in rule_ids or "L2-02" in rule_ids or bool(rule_ids & _DUPLICATE_ENTRY_RULES)
    ):
        add(
            "approval_control",
            "approval_bypass_high",
            "approval_bypass_risk",
            "approval_bypass + high_amount_or_duplicate",
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
