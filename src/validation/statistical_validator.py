"""L3 통계 검증 오케스트레이터 — 서브모듈 조합 + flags 수집.

Why: benford/volatility/temporal 서브모듈 결과를 StatisticalResult로 조립.
detection L3/L4 rules (L3-04 기말집중, L4-02 Benford, L4-03 이상고액)의 통계적 기반 제공.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config.settings import AuditSettings, get_settings
from src.validation.benford import analyze_benford
from src.validation.models import StatisticalResult
from src.validation.temporal_stats import analyze_temporal_patterns
from src.validation.volatility import (
    analyze_accounts,
    analyze_distribution,
    analyze_monthly_volatility,
)

logger = logging.getLogger(__name__)


def validate_statistics(
    df: pd.DataFrame,
    *,
    settings: AuditSettings | None = None,
) -> StatisticalResult:
    """L3 통계 검증 — 5개 서브분석 실행 후 종합 결과 반환.

    Args:
        df: feature 추가 완료된 DataFrame (first_digit 컬럼 포함 권장)
        settings: None이면 get_settings() 자동 로드
    """
    s = settings or get_settings()
    warnings: list[str] = []

    # 대표 금액 사전 계산 — 서브모듈 공유
    base_amount = _compute_base_amount(df)

    # 1) 월별 변동성
    monthly, w = analyze_monthly_volatility(df, base_amount, settings=s)
    warnings.extend(w)

    # 2) 분포 분석
    dist, w = analyze_distribution(base_amount, settings=s)
    warnings.extend(w)

    # 3) 계정별 통계
    accounts, w = analyze_accounts(df, base_amount, settings=s)
    warnings.extend(w)

    # 4) Benford 분석
    first_digits = _get_first_digits(df)
    benford, w = analyze_benford(first_digits, settings=s)
    warnings.extend(w)

    # 5) 시간 패턴
    temporal, w = analyze_temporal_patterns(df, settings=s)
    warnings.extend(w)

    # flags 수집
    flags = _collect_flags(monthly, dist, benford, accounts, temporal, s)

    return StatisticalResult(
        total_rows=len(df),
        analysis_timestamp=datetime.now(timezone.utc).isoformat(),
        monthly_volatility=monthly,
        distribution=dist,
        benford=benford,
        account_stats=accounts,
        temporal_patterns=temporal,
        warnings=warnings,
        flags=flags,
    )


def result_to_dict(result: StatisticalResult) -> dict:
    """StatisticalResult → JSON-serializable dict. numpy 타입 변환 포함."""
    raw = asdict(result)
    return _sanitize(raw)


# ── Private helpers ──────────────────────────────────────────


def _compute_base_amount(df: pd.DataFrame) -> pd.Series:
    """차변/대변 중 큰 값을 대표 금액으로 산출."""
    cols = [c for c in ["debit_amount", "credit_amount"] if c in df.columns]
    if not cols:
        return pd.Series(0.0, index=df.index)
    return df[cols].fillna(0).max(axis=1)


def _get_first_digits(df: pd.DataFrame) -> pd.Series:
    """first_digit 컬럼 반환. 없으면 대표 금액에서 재계산."""
    if "first_digit" in df.columns:
        return df["first_digit"]
    # Why: feature 미적용 DataFrame에서도 동작하도록 fallback
    base = _compute_base_amount(df)
    amount = base.where(base > 0)
    digits = amount.astype(str).str.extract(r"([1-9])", expand=False)
    return pd.to_numeric(digits, errors="coerce").astype("Int64")


def _collect_flags(monthly, dist, benford, accounts, temporal, settings):
    """각 서브 결과에서 이상 징후를 flags로 수집."""
    flags: list[dict[str, str]] = []

    if not benford.is_conforming and benford.sample_size > 0:
        flags.append({
            "type": "benford_violation",
            "detail": f"MAD={benford.mad}, {benford.mad_conformity}",
        })

    if monthly.outlier_months:
        flags.append({
            "type": "monthly_volatility",
            "detail": f"급변월: {', '.join(monthly.outlier_months)}",
        })

    if dist.is_normal is False:
        flags.append({
            "type": "non_normal_distribution",
            "detail": f"Shapiro p={dist.shapiro_p_value}, {dist.skewness_label}",
        })

    if dist.outlier_concentration and dist.outlier_concentration > 0.5:
        flags.append({
            "type": "high_outlier_concentration",
            "detail": f"이상치 금액 비중 {dist.outlier_concentration:.1%}",
        })

    if accounts.hhi_label == "concentrated":
        flags.append({
            "type": "account_concentration",
            "detail": f"HHI={accounts.hhi:.4f}, 소수 계정 집중",
        })

    if temporal.period_end_concentration > 0.5:
        flags.append({
            "type": "period_end_concentration",
            "detail": f"기말 {temporal.period_end_concentration:.1%} 집중",
        })

    return flags


def _sanitize(obj):
    """numpy/pandas 타입 → Python 네이티브 재귀 변환."""
    if isinstance(obj, dict):
        return {_sanitize(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        sanitized = [_sanitize(item) for item in obj]
        return tuple(sanitized) if isinstance(obj, tuple) else sanitized
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj
