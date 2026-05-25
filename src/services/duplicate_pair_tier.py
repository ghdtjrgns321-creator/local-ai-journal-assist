"""Duplicate family pair evidence tier classifier (lane sort 보조).

Why: PHASE2 duplicate family 의 row score 는 q95~q99 가 모두 0.6 대에 cap 되어
     동률 bucket 이 크다. `DuplicatePairDetector.metadata.pair_artifact.top_pairs`
     에 이미 same_partner / reference_similarity / text_similarity /
     amount_similarity feature 가 있지만 lane sort key 에 반영되지 않아
     동률 분해에 활용되지 않는다. 본 모듈은 pair feature 를 categorical tier
     (strong / moderate / weak) 로 분류하여 `phase2_lane_sort.sort_lane`
     의 duplicate lane 한정 sort key 보조에 사용한다.

도메인 정합성:
  - PCAOB AS 2401 §B7 "transactions that are duplicates of others" 는 의도성
    증거(동일 거래처 + 동일 reference + 동일 적요)와 우연 일치를 구분해야
    한다는 점에서 기준서 인용 가능.
  - 임계는 사용자 lock (D044 fitting-risk check 통과 절차에 준함).
    truth recall 보고 재조정 금지.

거버넌스:
  - lexicographic sort key 한 자리만 차지한다. weighted sum 금지.
  - row score / DetectionResult / family score 변경 0.
  - pair_artifact 미존재 시 호출측은 weight=0 graceful fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

PairTier = Literal["strong", "moderate", "weak"]

# tier 가중치 (lane sort 보조용, desc 정렬).
PAIR_TIER_ORDER: dict[str, int] = {"strong": 3, "moderate": 2, "weak": 1}

# 사용자 lock 임계 (2026-05-25). 변경은 D044 절차 준수 필수.
_STRONG_REF_MIN = 0.90
_STRONG_TEXT_MIN = 0.90
_STRONG_AMOUNT_MIN = 0.98

_MODERATE_REF_MIN = 0.70
_MODERATE_TEXT_MIN = 0.80
_MODERATE_AMOUNT_MIN = 0.95


def classify_pair_evidence_tier(features: dict[str, Any] | None) -> PairTier:
    """Pair feature dict → categorical tier.

    Args:
        features: ``DuplicatePairArtifact.top_pairs[*]["features"]`` payload.
            None 값은 명시적 evidence 부재로 간주하여 strong/moderate 조건에서
            False 처리한다.

    Returns:
        "strong" / "moderate" / "weak".

    Strong (의도성 증거 다수):
        same_partner=True AND reference_similarity >= 0.90 AND
        (text_similarity >= 0.90 OR amount_similarity >= 0.98).

    Moderate (일부 의도성 증거):
        same_partner=True AND
        (reference_similarity >= 0.70 OR text_similarity >= 0.80
         OR amount_similarity >= 0.95).

    Weak:
        그 외 (same_partner=False/None 인 경우 모두 weak).
    """
    if not features:
        return "weak"
    same_partner = bool(features.get("same_partner") or False)
    if not same_partner:
        return "weak"

    ref_sim = _as_float(features.get("reference_similarity"))
    text_sim = _as_float(features.get("text_similarity"))
    amount_sim = _as_float(features.get("amount_similarity"))

    if ref_sim >= _STRONG_REF_MIN and (
        text_sim >= _STRONG_TEXT_MIN or amount_sim >= _STRONG_AMOUNT_MIN
    ):
        return "strong"
    if (
        ref_sim >= _MODERATE_REF_MIN
        or text_sim >= _MODERATE_TEXT_MIN
        or amount_sim >= _MODERATE_AMOUNT_MIN
    ):
        return "moderate"
    return "weak"


def best_pair_tier(tiers: Sequence[PairTier | str | None]) -> tuple[PairTier | None, int]:
    """여러 pair tier 중 최고 tier 반환 (case 단위 집계용).

    Returns:
        (tier_name, tier_weight). 빈 입력은 (None, 0).
    """
    best_tier: PairTier | None = None
    best_weight = 0
    for tier in tiers:
        if not tier:
            continue
        weight = PAIR_TIER_ORDER.get(str(tier), 0)
        if weight > best_weight:
            best_weight = weight
            best_tier = tier  # type: ignore[assignment]
    return best_tier, best_weight


def pair_tier_weight(tier: PairTier | str | None) -> int:
    """tier name → weight (None / 미등록 → 0)."""
    if not tier:
        return 0
    return PAIR_TIER_ORDER.get(str(tier), 0)


def _as_float(value: Any) -> float:
    """None/NaN/비숫자는 0.0 (strong/moderate 임계 미달 처리)."""
    if value is None:
        return 0.0
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if num != num:  # NaN
        return 0.0
    return num
