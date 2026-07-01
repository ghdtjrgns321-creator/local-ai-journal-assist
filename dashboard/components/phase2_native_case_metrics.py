"""Overview 탭용 PHASE2 native case 기반 지표 헬퍼.

Why: tab_phase2 의 KPI ribbon / 활성 분포 / 분석 영역 요약 세 섹션이 동일하게
``Phase2CaseSet`` 의 5 family case 를 집계해야 한다. 호출 지점마다 case_set 을
순회하는 중복을 막고 SRP 로 분리한다. overlay 기반 지표 (``phase2_case_overlays``)
와 정의 자체가 달라 모듈도 분리한다.

사용자 결정 (2026-05-28):
  - 신호 케이스 = evidence_tier ∈ {strong, moderate}
  - Active Lane 분모 = 9 (Active 5 + Dormant 4) 유지 — 표시 일관성
  - dormant family 는 native case 가 항상 0 이므로 분자에 기여하지 않는다.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.models.phase2_case import Phase2CaseBase, Phase2CaseSet

# evidence_tier 중 "신호" 로 카운트할 tier — 사용자 결정 (Strong + Moderate)
SIGNAL_TIERS: frozenset[str] = frozenset({"strong", "moderate"})

# Active family 순서 — `dashboard.components.phase2_family_matrix.ACTIVE_FAMILIES` 와 동기화 필요.
# 별도 import 하면 본 모듈이 그 파일에 강결합되어 reverse import 위험. 동일 값을
# 명시 보관하되 일치는 unit test 에서 확인 (필요 시 follow-up).
_ACTIVE_FAMILIES: tuple[str, ...] = (
    "unsupervised",
    "timeseries",
)


def resolve_phase2_case_set_from_state() -> Phase2CaseSet | None:
    """session_state 의 phase2_result 에서 ``Phase2CaseSet`` 추출.

    None 반환 케이스: phase2_result 부재 / phase2_case_set attribute 부재 / 타입 불일치.
    """
    from dashboard._state import KEY_PHASE2_RESULT

    state = st.session_state if hasattr(st, "session_state") else {}
    phase2_result = state.get(KEY_PHASE2_RESULT) if hasattr(state, "get") else None
    case_set = getattr(phase2_result, "phase2_case_set", None)
    return case_set if isinstance(case_set, Phase2CaseSet) else None


def _iter_all_cases(case_set: Phase2CaseSet | None) -> list[Phase2CaseBase]:
    """active family case 를 평탄화한 리스트. None / 빈 set → []."""
    if case_set is None:
        return []
    return list(case_set.iter_all_cases_sorted())


def count_native_cases_total(case_set: Phase2CaseSet | None) -> int:
    """전체 native case 수 (active family 합산)."""
    return len(_iter_all_cases(case_set))


def count_native_cases_signaled(case_set: Phase2CaseSet | None) -> int:
    """evidence_tier ∈ SIGNAL_TIERS 인 native case 수."""
    return sum(1 for c in _iter_all_cases(case_set) if c.evidence_tier in SIGNAL_TIERS)


def count_native_cases_by_family(case_set: Phase2CaseSet | None) -> dict[str, int]:
    """family → case 수 매핑. active family 모두 키로 포함 (없으면 0)."""
    counts: dict[str, int] = dict.fromkeys(_ACTIVE_FAMILIES, 0)
    if case_set is None:
        return counts
    counts["unsupervised"] = len(case_set.unsupervised_cases)
    counts["timeseries"] = len(case_set.timeseries_cases)
    return counts


def count_active_native_families(case_set: Phase2CaseSet | None) -> int:
    """native case 가 1건 이상 존재하는 family 수 (Active lane 분자)."""
    return sum(1 for n in count_native_cases_by_family(case_set).values() if n > 0)


def top_native_case_family(
    case_set: Phase2CaseSet | None,
    *,
    exclude: frozenset[str] = frozenset({"unsupervised"}),
) -> tuple[str, int] | None:
    """case 수 최대 family. unsupervised 는 기본 제외 (모든 row 가 점수 가져 비교 무의미).

    Returns:
        (family_key, count) 또는 None (모든 family 가 0건).
    """
    counts = count_native_cases_by_family(case_set)
    eligible = {f: n for f, n in counts.items() if f not in exclude and n > 0}
    if not eligible:
        return None
    best_family, best_count = max(eligible.items(), key=lambda kv: kv[1])
    return best_family, best_count


def count_native_cases_by_family_tier(
    case_set: Phase2CaseSet | None,
) -> dict[str, dict[str, int]]:
    """family × evidence_tier 분포. matrix 차트용.

    Returns:
        {family: {tier: count}} — Active 5 family × 발생 tier.
    """
    matrix: dict[str, dict[str, int]] = {f: {} for f in _ACTIVE_FAMILIES}
    if case_set is None:
        return matrix
    for case in _iter_all_cases(case_set):
        family = case.family if case.family in matrix else None
        if family is None:
            continue
        tier = case.evidence_tier or "unknown"
        matrix[family][tier] = matrix[family].get(tier, 0) + 1
    return matrix


def iter_unsupervised_cases(case_set: Phase2CaseSet | None) -> Any:
    """unsupervised family case 시퀀스 — VAE 분포 패널에서 anomaly_score 활용."""
    if case_set is None:
        return ()
    return case_set.unsupervised_cases


__all__ = [
    "SIGNAL_TIERS",
    "count_active_native_families",
    "count_native_cases_by_family",
    "count_native_cases_by_family_tier",
    "count_native_cases_signaled",
    "count_native_cases_total",
    "iter_unsupervised_cases",
    "resolve_phase2_case_set_from_state",
    "top_native_case_family",
]
