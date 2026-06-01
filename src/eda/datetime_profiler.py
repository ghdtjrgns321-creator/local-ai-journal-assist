"""datetime 컬럼 프로파일링 — min/max/range/요일·월별 분포.

분포 키는 정수 유지 (weekday: 0=Mon~6=Sun, monthly: 1~12).
라벨 매핑은 report.py 또는 대시보드에서 처리.
"""

from __future__ import annotations

import pandas as pd


def profile_datetime(series: pd.Series) -> dict:
    """datetime Series → 통계 dict. 전체 NaT이면 모든 값 None."""
    # Why: dropna()가 DatetimeIndex를 반환할 수 있어 .dt accessor 사용 불가
    # pd.Series로 감싸서 .dt accessor를 보장한다
    clean = pd.Series(series.dropna().values)
    if len(clean) == 0:
        return _empty_datetime()

    min_dt = clean.min()
    max_dt = clean.max()
    range_days = (max_dt - min_dt).days

    # 요일 분포: sort_index()로 0~6 순서 보장
    weekday_dist = clean.dt.dayofweek.value_counts().sort_index().to_dict()
    # 월별 분포: sort_index()로 1~12 순서 보장
    monthly_dist = clean.dt.month.value_counts().sort_index().to_dict()

    return {
        "min_date": min_dt.isoformat(),
        "max_date": max_dt.isoformat(),
        "date_range_days": int(range_days),
        "weekday_distribution": {int(k): int(v) for k, v in weekday_dist.items()},
        "monthly_distribution": {int(k): int(v) for k, v in monthly_dist.items()},
    }


def _empty_datetime() -> dict:
    """전체 NaT일 때 반환할 빈 dict."""
    return {
        "min_date": None,
        "max_date": None,
        "date_range_days": None,
        "weekday_distribution": None,
        "monthly_distribution": None,
    }
