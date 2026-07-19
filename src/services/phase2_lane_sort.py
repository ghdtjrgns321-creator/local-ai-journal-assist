"""PHASE2 family lane 정렬 helper — Phase E.

lane 내부 정렬은 RRF 를 쓰지 않는다 (Phase C 측정에서 internal RRF 가 reject 됨).
대신 evidence_tier 와 family ECDF score 로 categorical sort 한다.

정렬 기준 (desc, lexicographic):
  1. evidence_tier_weight (strong=3 > moderate=2 > weak=1 > ml_quantile=0)
  2. family ECDF score
  3. family raw score
  4. review-only count

near-dormant family lane 은 비어 있을 수 있으며, dashboard 에서는 "데이터 미보유"
배지로 표시한다.

본 모듈은 primary PHASE1+VAE 2-way RRF queue 의 순위를 변경하지 않는다.
(docs/spec/PHASE2_GOVERNANCE_DESIGN.md 결정 8)
"""

from __future__ import annotations

from typing import Any

from src.services.subdetector_tiers import TIER_ORDER, get_subdetector_tier_index


def sort_lane(
    family: str,
    case_overlays: list[dict[str, Any]],
    *,
    include_zero_score: bool = False,
) -> list[dict[str, Any]]:
    """단일 family lane 의 case overlay 를 정렬해서 반환.

    Args:
        family: lane 이름 (e.g. "timeseries").
        case_overlays: `build_phase2_case_overlays` 결과 dict 리스트.
            각 overlay 의 `family_contributions` 에서 해당 family entry 추출.
        include_zero_score: True 면 score==0 case 도 lane 에 포함(monitoring 용).
            False(기본)면 score>0 또는 ecdf>0 case 만 노출.

    Returns:
        정렬된 case overlay 리스트. lane 진입 case 가 없으면 빈 list.
    """
    candidates: list[tuple[tuple, dict[str, Any]]] = []
    for overlay in case_overlays:
        entry = _find_family_entry(overlay, family)
        if entry is None:
            continue
        score = float(entry.get("score") or 0.0)
        ecdf = float(entry.get("ecdf") or 0.0)
        review_only_count = int(entry.get("review_only_count") or 0)
        if not include_zero_score and score <= 0 and ecdf <= 0 and review_only_count <= 0:
            continue
        tier_weight = int(entry.get("evidence_tier_weight") or 0)
        candidates.append(
            (
                (tier_weight, ecdf, score, review_only_count),
                overlay,
            )
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [overlay for _key, overlay in candidates]


def _find_family_entry(overlay: dict[str, Any], family: str) -> dict[str, Any] | None:
    """overlay 의 family_contributions 에서 family entry 추출."""
    contributions = overlay.get("family_contributions") or []
    for entry in contributions:
        if entry.get("family") == family:
            return entry
    return None


def lane_summary(
    family: str,
    case_overlays: list[dict[str, Any]],
    *,
    family_role: str | None = None,
) -> dict[str, Any]:
    """lane 의 요약 메타 — dashboard 배지·count 표시용.

    near-dormant family 는 원칙적으로 "데이터 미보유" 배지로 표시하되,
    review-only 신호처럼 score 승격 없이 확인해야 하는 신호는 count 로 남긴다.
    """
    sorted_overlays = sort_lane(family, case_overlays)
    review_only_count = 0
    for overlay in sorted_overlays:
        entry = _find_family_entry(overlay, family)
        if entry is not None:
            review_only_count += int(entry.get("review_only_count") or 0)

    if family_role == "near-dormant" and not sorted_overlays:
        return {
            "family": family,
            "role": family_role,
            "case_count": 0,
            "tier_counts": {"strong": 0, "moderate": 0, "weak": 0, "ml_quantile": 0},
            "review_only_count": 0,
            "badge": "데이터 미보유",
        }

    tier_counts = {tier: 0 for tier in TIER_ORDER}
    for overlay in sorted_overlays:
        entry = _find_family_entry(overlay, family)
        if entry is None:
            continue
        tier = entry.get("evidence_tier")
        if tier in tier_counts:
            tier_counts[tier] += 1
    return {
        "family": family,
        "role": family_role or "unknown",
        "case_count": len(sorted_overlays),
        "tier_counts": tier_counts,
        "review_only_count": review_only_count,
        "badge": _build_badge(family_role, tier_counts, review_only_count=review_only_count),
    }


def _build_badge(
    family_role: str | None,
    tier_counts: dict[str, int],
    *,
    review_only_count: int = 0,
) -> str:
    """family lane 배지 문구."""
    if review_only_count > 0:
        return f"검토-only {review_only_count}건"
    if family_role == "near-dormant":
        return "데이터 미보유"
    strong = tier_counts.get("strong", 0)
    if family_role == "coarse-booster":
        return f"보조 — strong {strong}건"
    if family_role == "tail-only-fallback":
        return f"꼬리만 — strong {strong}건"
    return f"활성 — strong {strong}건"


def list_active_lanes(
    family_roles: dict[str, str],
    *,
    include_near_dormant: bool = True,
) -> list[str]:
    """lane selector 에 노출할 family 목록.

    near-dormant 도 기본 포함 (coverage gap 표시 용도).
    """
    candidates = []
    for family, role in family_roles.items():
        if role == "near-dormant" and not include_near_dormant:
            continue
        # unsupervised 는 primary queue 이미 노출 → lane 으로 별도 표시 안 함
        if family == "unsupervised":
            continue
        candidates.append(family)
    return sorted(candidates)


# ──────────────────────────────────────────────────────────────────────────────
# evidence_tier 기반 sub-detector tier lookup (lane 내부 정렬에 사용)
# ──────────────────────────────────────────────────────────────────────────────


def best_subdetector_tier(family: str, sub_codes: list[str]) -> tuple[str | None, int]:
    """family + sub_detector code 리스트 → 가장 높은 tier 반환.

    Returns:
        (tier_name, tier_weight) — 매칭 없으면 (None, 0).
    """
    tier_index = get_subdetector_tier_index()
    best_tier: str | None = None
    best_weight = 0
    for code in sub_codes:
        key = (family, code)
        if key not in tier_index:
            continue
        item = tier_index[key]
        if item.tier_weight > best_weight:
            best_weight = item.tier_weight
            best_tier = item.tier
    return best_tier, best_weight
