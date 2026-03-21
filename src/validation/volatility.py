"""월별 변동성 + 분포 분석 + 계정별 통계.

C01(기말집중), C08(이상고액) detection의 통계적 기반.
Shapiro-Wilk 정규성 검정, 계정별 CV/HHI 집중도 분석.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats

from config.settings import AuditSettings
from src.validation.models import AccountStats, DistributionStats, MonthlyVolatility

logger = logging.getLogger(__name__)

_SHAPIRO_MIN_N = 20
_SHAPIRO_MAX_N = 5000
_SHAPIRO_RANDOM_STATE = 42  # 대시보드 새로고침 시 p-value 안정화

_CV_EPSILON = 1e-5  # mean ≈ 0 계정의 ZeroDivisionError 방지


# ── Monthly Volatility ───────────────────────────────────────


def analyze_monthly_volatility(
    df: pd.DataFrame,
    base_amount: pd.Series,
    *,
    settings: AuditSettings,
) -> tuple[MonthlyVolatility, list[str]]:
    """월별 총액 → MoM 변화율 → Z-score 기반 급변월 탐지."""
    warnings: list[str] = []

    if "posting_date" not in df.columns:
        warnings.append("posting_date 컬럼 부재 — 월별 변동성 분석 건너뜀")
        return MonthlyVolatility({}, {}, [], None), warnings

    month_key = df["posting_date"].dt.to_period("M")
    monthly = base_amount.groupby(month_key).sum()

    # YYYY-MM 문자열 키로 변환 (JSON-serializable)
    totals = {str(k): float(v) for k, v in monthly.items()}

    # MoM 변화율
    pct = monthly.pct_change().dropna()
    mom_rates = {str(k): round(float(v), 4) for k, v in pct.items()}

    # Z-score 기반 급변월 탐지
    outlier_months: list[str] = []
    if len(pct) >= 2:
        mean_pct = pct.mean()
        std_pct = pct.std()
        if std_pct > 0:
            z_scores = (pct - mean_pct) / std_pct
            threshold = settings.monthly_volatility_zscore
            outliers = z_scores[z_scores.abs() > threshold]
            outlier_months = [str(k) for k in outliers.index]
    elif len(pct) < 2:
        warnings.append("월별 변동성: 2개월 미만 데이터 — MoM Z-score 산출 불가")

    # 계절성 지수: 월(1~12) 평균 대비 비율
    seasonality: dict[int, float] | None = None
    if len(monthly) >= 3:
        month_num = pd.Series(
            monthly.values, index=[p.month for p in monthly.index]
        )
        month_avg = month_num.groupby(month_num.index).mean()
        overall_avg = month_num.mean()
        if overall_avg > 0:
            seasonality = {
                int(m): round(float(v / overall_avg), 4)
                for m, v in month_avg.items()
            }

    return MonthlyVolatility(totals, mom_rates, outlier_months, seasonality), warnings


# ── Distribution Analysis ────────────────────────────────────


def analyze_distribution(
    amount_series: pd.Series,
    *,
    settings: AuditSettings,
) -> tuple[DistributionStats, list[str]]:
    """금액 분포 정규성 + 왜도/첨도 해석 + 이상치 집중도."""
    warnings: list[str] = []
    clean = amount_series.dropna()

    if len(clean) == 0:
        warnings.append("분포 분석 불가: 유효 금액 데이터 없음")
        return DistributionStats(None, None, None, None, None, None, None, None), warnings

    # Shapiro-Wilk 정규성 검정
    shapiro_stat: float | None = None
    shapiro_p: float | None = None
    is_normal: bool | None = None

    if len(clean) >= _SHAPIRO_MIN_N:
        sample = clean
        if len(clean) > _SHAPIRO_MAX_N:
            sample = clean.sample(n=_SHAPIRO_MAX_N, random_state=_SHAPIRO_RANDOM_STATE)
        stat, p = stats.shapiro(sample)
        shapiro_stat = round(float(stat), 6)
        shapiro_p = round(float(p), 6)
        is_normal = bool(p > settings.shapiro_alpha)
    else:
        warnings.append(f"Shapiro-Wilk 스킵: n={len(clean)} < 최소 {_SHAPIRO_MIN_N}")

    # 왜도·첨도 해석
    skew = float(clean.skew())
    kurt = float(clean.kurtosis())

    skew_label = "symmetric" if abs(skew) < 0.5 else ("right_skewed" if skew > 0 else "left_skewed")
    kurt_label = "mesokurtic" if abs(kurt) < 1 else ("leptokurtic" if kurt > 0 else "platykurtic")

    # 이상치 집중도: Tukey IQR
    q1, q3 = float(clean.quantile(0.25)), float(clean.quantile(0.75))
    iqr = q3 - q1
    outlier_conc: float | None = None
    total_sum = float(clean.sum())
    if total_sum > 0:
        if iqr > 0:
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outlier_sum = float(clean[(clean < lower) | (clean > upper)].sum())
        else:
            # Why: IQR=0 (대부분 동일값) → Q3 초과분을 이상치로 간주
            outlier_sum = float(clean[clean > q3].sum()) if clean.nunique() > 1 else 0.0
        outlier_conc = round(outlier_sum / total_sum, 4) if outlier_sum > 0 else 0.0

    return DistributionStats(
        shapiro_statistic=shapiro_stat,
        shapiro_p_value=shapiro_p,
        is_normal=is_normal,
        skewness=round(skew, 4),
        skewness_label=skew_label,
        kurtosis=round(kurt, 4),
        kurtosis_label=kurt_label,
        outlier_concentration=outlier_conc,
    ), warnings


# ── Account Statistics ───────────────────────────────────────


def analyze_accounts(
    df: pd.DataFrame,
    base_amount: pd.Series,
    *,
    settings: AuditSettings,
) -> tuple[AccountStats, list[str]]:
    """계정별 CV, HHI 집중도, 거래 빈도."""
    warnings: list[str] = []

    if "gl_account" not in df.columns:
        warnings.append("gl_account 컬럼 부재 — 계정별 통계 건너뜀")
        return AccountStats(0, {}, [], 0.0, "diversified", {}), warnings

    grouped = base_amount.groupby(df["gl_account"])
    agg = grouped.agg(["mean", "std", "count", "sum"])

    account_count = len(agg)
    activity = {str(k): int(v) for k, v in agg["count"].items()}

    # CV 계산 — mean ≈ 0 방어 (상계·동일 금액 반복), std=NaN 방어 (단일 행 그룹)
    cv_dict: dict[str, float] = {}
    for acct, row in agg.iterrows():
        mean_val = float(row["mean"]) if not pd.isna(row["mean"]) else 0.0
        std_val = float(row["std"]) if not pd.isna(row["std"]) else 0.0
        if abs(mean_val) > _CV_EPSILON:
            cv_dict[str(acct)] = round(std_val / abs(mean_val), 4)
        else:
            cv_dict[str(acct)] = 0.0

    high_cv = [a for a, cv in cv_dict.items() if cv > settings.cv_high_threshold]

    # HHI 집중도
    total_amount = agg["sum"].sum()
    if total_amount > 0:
        shares = agg["sum"] / total_amount
        hhi = float((shares ** 2).sum())
    else:
        hhi = 0.0

    hhi_label = (
        "concentrated" if hhi >= settings.hhi_concentrated_threshold
        else "moderate" if hhi >= 0.15
        else "diversified"
    )

    return AccountStats(
        account_count=account_count,
        cv_by_account=cv_dict,
        high_cv_accounts=high_cv,
        hhi=round(hhi, 6),
        hhi_label=hhi_label,
        activity_frequency=activity,
    ), warnings
