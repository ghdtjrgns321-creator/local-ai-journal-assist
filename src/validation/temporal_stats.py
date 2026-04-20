"""시간 패턴 통계 — 요일/기말 집중도 + YoY 비교.

L3-04(기말 대규모), L3-05(휴일 전기), L3-06(심야 전기) detection 보조.
"""

from __future__ import annotations

import logging

import pandas as pd

from config.settings import AuditSettings
from src.validation.models import TemporalPatternStats

logger = logging.getLogger(__name__)


def analyze_temporal_patterns(
    df: pd.DataFrame,
    *,
    settings: AuditSettings,
) -> tuple[TemporalPatternStats, list[str]]:
    """요일 분포, 주말 비율, 기말 집중도, YoY 비교."""
    warnings: list[str] = []

    if "posting_date" not in df.columns:
        warnings.append("posting_date 컬럼 부재 — 시간 패턴 분석 건너뜀")
        return TemporalPatternStats({}, 0.0, 0.0, None), warnings

    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    valid = dates.dropna()
    total = len(valid)

    if total == 0:
        warnings.append("유효한 posting_date 없음 — 시간 패턴 분석 건너뜀")
        return TemporalPatternStats({}, 0.0, 0.0, None), warnings

    # 요일 분포 (0=Mon ~ 6=Sun)
    dow = valid.dt.dayofweek
    weekday_vol = {int(k): int(v) for k, v in dow.value_counts().sort_index().items()}

    # 주말 비율
    weekend_count = dow[dow >= 5].shape[0]
    weekend_ratio = round(weekend_count / total, 4)

    # 기말 집중도: 월말 margin일 이내 거래 비율
    margin = settings.period_end_margin_days
    month_end = valid.dt.to_period("M").dt.end_time.dt.normalize()
    days_to_end = (month_end - valid.dt.normalize()).dt.days
    period_end_count = int((days_to_end.between(0, margin)).sum())
    period_end_conc = round(period_end_count / total, 4)

    # YoY: 2개 연도 이상이면 월별 평균 YoY 변화율 산출
    yoy: dict[str, float] | None = None
    if "debit_amount" in df.columns or "credit_amount" in df.columns:
        yoy = _compute_yoy(df, valid, warnings)

    return TemporalPatternStats(
        weekday_volume=weekday_vol,
        weekend_ratio=weekend_ratio,
        period_end_concentration=period_end_conc,
        yoy_change=yoy,
    ), warnings


def _compute_yoy(
    df: pd.DataFrame,
    dates: pd.Series,
    warnings: list[str],
) -> dict[str, float] | None:
    """연도별 월간 총액 → 월별 평균 YoY 변화율.

    키 포맷: {"01": 0.05, "02": -0.12, ...} — 대시보드 차트 렌더링 최적화.
    """
    years = dates.dt.year.unique()
    if len(years) < 2:
        return None

    # 대표 금액 산출
    base = pd.Series(0.0, index=df.index)
    if "debit_amount" in df.columns:
        base = base.add(df["debit_amount"].fillna(0), fill_value=0)
    if "credit_amount" in df.columns:
        base = pd.concat([base, df["credit_amount"].fillna(0)], axis=1).max(axis=1)

    year_month = dates.dt.to_period("M")
    monthly = base.groupby(year_month).sum()

    # 피벗: 행=월(1~12), 열=연도
    pivot = pd.DataFrame({
        "year": [p.year for p in monthly.index],
        "month": [p.month for p in monthly.index],
        "amount": monthly.values,
    }).pivot_table(index="month", columns="year", values="amount", aggfunc="sum")

    if pivot.shape[1] < 2:
        return None

    # 연도 간 변화율 → 월별 평균
    yoy_rates = pivot.pct_change(axis=1).iloc[:, 1:]
    avg_yoy = yoy_rates.mean(axis=1)

    result: dict[str, float] = {}
    for month, rate in avg_yoy.items():
        if pd.notna(rate):
            result[f"{int(month):02d}"] = round(float(rate), 4)

    if not result:
        warnings.append("YoY 변화율 산출 불가: 동일 월 데이터 부족")
        return None

    return result
