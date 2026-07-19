"""D062 PHASE2 / PHASE1+2 통합 3등급 분류 helper 회귀 잠금.

분류 정책은 config/phase2_review_band.yaml 의 도메인 잠금. 본 테스트는
count 보고 임계 재조정 금지 (D060 5조 5번) 정책을 코드 단에서 잠근다.
"""

from __future__ import annotations

import pytest

from src.services.phase2_case_contract import (
    classify_phase2_review_band,
    classify_phase12_review_band,
)


def _classify(
    *,
    tier: str | None = None,
    coverage: int = 0,
    ecdf: float | None = None,
    family_contributions: list[dict] | None = None,
    has_phase2_signal: bool = True,
) -> str:
    return classify_phase2_review_band(
        max_evidence_tier=tier,
        coverage_breadth_q95=coverage,
        max_family_ecdf=ecdf,
        family_contributions=family_contributions or [],
        has_phase2_signal=has_phase2_signal,
    )


# ---- PHASE2 positive (immediate) ---------------------------------------------


def test_phase2_strong_with_coverage_2_immediate():
    """strong tier + coverage>=2 → 즉시검토."""

    assert _classify(tier="strong", coverage=2) == "immediate"


def test_phase2_strong_with_coverage_5_immediate():
    """coverage>=2 만족하면 더 높은 coverage 도 즉시검토 유지."""

    assert _classify(tier="strong", coverage=5) == "immediate"


# ---- PHASE2 negative lock (≠ immediate) --------------------------------------


def test_phase2_strong_with_coverage_1_review():
    """strong tier 단독 (coverage<2) → 즉시검토 X, 검토대상."""

    assert _classify(tier="strong", coverage=1) == "review"


def test_phase2_strong_with_coverage_0_review():
    """strong tier 단독 (coverage 0) → 검토대상."""

    assert _classify(tier="strong", coverage=0) == "review"


def test_phase2_moderate_with_coverage_2_review():
    """moderate + coverage>=2 → 검토대상 (즉시검토 X)."""

    assert _classify(tier="moderate", coverage=2) == "review"


def test_phase2_moderate_with_coverage_1_candidate():
    """moderate + coverage 1 → 후보 (D060 4번 단독 금지 적용 — moderate 는 coverage 필요)."""

    assert _classify(tier="moderate", coverage=1) == "candidate"


def test_phase2_ml_quantile_with_ecdf_and_ml_only_and_coverage_review():
    """ml_quantile + ecdf>=0.995 + unsupervised family + coverage>=2 → 검토대상."""

    contributions = [{"family": "unsupervised", "score": 0.6}]
    assert (
        _classify(
            tier="ml_quantile",
            coverage=2,
            ecdf=0.995,
            family_contributions=contributions,
        )
        == "review"
    )


def test_phase2_ml_quantile_without_coverage_candidate():
    """ml_quantile + ecdf>=0.995 + unsupervised + coverage<2 → 후보."""

    contributions = [{"family": "unsupervised", "score": 0.6}]
    assert (
        _classify(
            tier="ml_quantile",
            coverage=1,
            ecdf=0.995,
            family_contributions=contributions,
        )
        == "candidate"
    )


def test_phase2_ml_quantile_without_ml_only_family_candidate():
    """ml_quantile + ecdf>=0.995 + coverage>=2 이지만 ML-only family 기여 없음 → 후보.

    rule-style family (duplicate / timeseries 등) 의 ecdf 가 같은 임계로 즉시검토
    진입하면 PHASE2 tier 정책이 흐려진다. ml_only_families 제한 (D062).
    """

    contributions = [{"family": "duplicate", "score": 0.6}]
    assert (
        _classify(
            tier="ml_quantile",
            coverage=2,
            ecdf=0.995,
            family_contributions=contributions,
        )
        == "candidate"
    )


def test_phase2_ml_quantile_with_ecdf_below_threshold_candidate():
    """ml_quantile + ecdf<0.995 → 후보 (임계 미달)."""

    contributions = [{"family": "unsupervised", "score": 0.6}]
    assert (
        _classify(
            tier="ml_quantile",
            coverage=2,
            ecdf=0.99,
            family_contributions=contributions,
        )
        == "candidate"
    )


def test_phase2_weak_with_coverage_5_candidate():
    """weak 단독 (강한 seed 없음) — coverage 가 아무리 높아도 후보 (D060 4번)."""

    assert _classify(tier="weak", coverage=5) == "candidate"


def test_phase2_no_signal_none():
    """has_phase2_signal=False → 신호없음."""

    assert _classify(tier=None, coverage=0, has_phase2_signal=False) == "none"


# ---- PHASE1+2 통합 분류 -------------------------------------------------------


@pytest.mark.parametrize(
    "p1_band,p2_band,expected",
    [
        # 즉시검토: 양측 모두 immediate (교집합)
        ("immediate", "immediate", "immediate"),
        # 검토대상: 한쪽이라도 immediate 또는 review
        ("immediate", "review", "review"),
        ("immediate", "candidate", "review"),
        ("immediate", "none", "review"),
        ("review", "immediate", "review"),
        ("review", "review", "review"),
        ("review", "candidate", "review"),
        ("review", "none", "review"),
        ("candidate", "immediate", "review"),
        ("none", "immediate", "review"),
        ("candidate", "review", "review"),
        ("none", "review", "review"),
        # 후보: 한쪽이라도 candidate, 양측 모두 immediate/review 아님
        ("candidate", "candidate", "candidate"),
        ("candidate", "none", "candidate"),
        ("none", "candidate", "candidate"),
        # 신호없음: 양측 모두 none
        ("none", "none", "none"),
    ],
)
def test_phase12_combine(p1_band: str, p2_band: str, expected: str):
    assert classify_phase12_review_band(p1_band, p2_band) == expected


def test_phase12_immediate_requires_both_sides():
    """통합 즉시검토는 P1 또는 P2 단독으로는 진입 불가 — 교집합 검증."""

    assert classify_phase12_review_band("immediate", "review") != "immediate"
    assert classify_phase12_review_band("review", "immediate") != "immediate"
    assert classify_phase12_review_band("immediate", "candidate") != "immediate"
    assert classify_phase12_review_band("candidate", "immediate") != "immediate"


def test_phase12_p1_review_not_demoted_to_candidate_by_p2_none():
    """P1 검토대상이 P2 신호없음 만으로 통합 후보로 격하되지 않음 (max band 안전망)."""

    assert classify_phase12_review_band("review", "none") == "review"
