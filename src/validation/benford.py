"""Benford's Law 분석 — L4-02 detection의 통계적 기반.

판정 기준: MAD(주, Nigrini 2012) + Chi-square(주) + KS(보조).
KS는 이산 분포에 엄밀하지 않으므로 참고 지표로만 사용.
입력: feature/pattern_features.add_first_digit()가 생성한 first_digit(Int64, 1~9) 컬럼.

근거: 감사기준서 520호 §5, 240 A45(e).
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from scipy import stats

from config.settings import AuditSettings
from src.validation.models import BenfordResult

logger = logging.getLogger(__name__)

# ── Benford 이론 분포 상수 ────────────────────────────────────

BENFORD_EXPECTED: dict[int, float] = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

# ── MAD 판정 기준 (Nigrini 2012) ─────────────────────────────

_MAD_CLOSE = 0.006
_MAD_ACCEPTABLE = 0.012
_MAD_MARGINALLY = 0.015


# ── Private helpers ──────────────────────────────────────────


def _classify_mad(mad: float) -> str:
    """MAD 값 → Nigrini 4단계 판정."""
    if mad <= _MAD_CLOSE:
        return "close"
    if mad <= _MAD_ACCEPTABLE:
        return "acceptable"
    if mad <= _MAD_MARGINALLY:
        return "marginally"
    return "nonconforming"


def _assess_confidence(n: int) -> str:
    """샘플 크기 기반 신뢰도 판정."""
    if n >= 500:
        return "high"
    if n >= 100:
        return "moderate"
    return "low"


def _empty_result() -> BenfordResult:
    """유효 데이터 없을 때 빈 결과 반환."""
    return BenfordResult(
        sample_size=0,
        observed={d: 0.0 for d in range(1, 10)},
        expected=dict(BENFORD_EXPECTED),
        mad=None,
        mad_conformity="nonconforming",
        chi2_statistic=None,
        chi2_p_value=None,
        ks_statistic=None,
        ks_p_value=None,
        is_conforming=False,
        confidence="low",
    )


# ── Public API ───────────────────────────────────────────────


def analyze_benford(
    first_digits: pd.Series,
    *,
    settings: AuditSettings,
) -> tuple[BenfordResult, list[str]]:
    """첫째자리 분포 → MAD + Chi-square + KS 분석.

    Returns:
        (BenfordResult, warnings 리스트)
    """
    warnings: list[str] = []

    # NaN·0 제거 → 유효 숫자(1~9)만 추출
    # Why: IntegerArray는 .between() 미지원 → Series 변환 후 필터
    series = pd.Series(first_digits)
    clean = series.dropna()
    clean = clean[(clean >= 1) & (clean <= 9)].astype(int)
    n = len(clean)

    if n == 0:
        warnings.append("Benford 분석 불가: 유효한 첫째자리 숫자 없음")
        return _empty_result(), warnings

    confidence = _assess_confidence(n)
    if n < settings.benford_min_sample:
        warnings.append(f"Benford 신뢰도 낮음: n={n} < 최소 표본 {settings.benford_min_sample}")

    # 실제 분포 계산 (1~9 모든 자릿수 포함, 0건도 0.0)
    counts = clean.value_counts()
    observed = {d: int(counts.get(d, 0)) for d in range(1, 10)}
    total = sum(observed.values())
    observed_freq = {d: c / total for d, c in observed.items()}

    # MAD 계산
    mad = float(np.mean([abs(observed_freq[d] - BENFORD_EXPECTED[d]) for d in range(1, 10)]))
    mad_conformity = _classify_mad(mad)

    # Chi-square 검정
    observed_counts = [observed[d] for d in range(1, 10)]
    expected_counts = [BENFORD_EXPECTED[d] * total for d in range(1, 10)]
    chi2_stat, chi2_p = stats.chisquare(observed_counts, f_exp=expected_counts)

    # KS 검정 (보조 — 이산 분포 한계 있으므로 판정에 미사용)
    # Why: 연속 CDF 가정이므로 이산 첫째자리에는 p-value 과대평가 가능
    ks_stat: float | None = None
    ks_p: float | None = None
    if n >= 50:
        benford_probs = [BENFORD_EXPECTED[d] for d in range(1, 10)]
        benford_cdf = np.cumsum(benford_probs)

        observed_sorted = np.sort(clean.values)
        ecdf = np.searchsorted(observed_sorted, range(1, 10), side="right") / n
        ks_stat = float(np.max(np.abs(ecdf - benford_cdf)))
        # Why: 근사 p-value — Kolmogorov 분포 이용
        ks_p = float(stats.ksone.sf(ks_stat, n) * 2) if ks_stat > 0 else 1.0

    # 종합 판정: MAD + Chi-square 기준
    is_conforming = bool(
        mad <= settings.benford_mad_threshold and chi2_p >= settings.benford_chi2_alpha
    )

    return BenfordResult(
        sample_size=n,
        observed=observed_freq,
        expected=dict(BENFORD_EXPECTED),
        mad=round(mad, 6),
        mad_conformity=mad_conformity,
        chi2_statistic=round(float(chi2_stat), 4),
        chi2_p_value=round(float(chi2_p), 6),
        ks_statistic=round(ks_stat, 4) if ks_stat is not None else None,
        ks_p_value=round(ks_p, 6) if ks_p is not None else None,
        is_conforming=is_conforming,
        confidence=confidence,
    ), warnings
