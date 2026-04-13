"""TS01(거래 급증), TS02(비정상 거래 주기) 시계열 룰 함수.

Why: Phase 1의 C01~C03은 시점별 이상만 탐지. 거래 빈도 패턴(급증, 주기 이상)은 미탐지.
     두 룰 모두 posting_date 기반 시계열 밀도 분석으로 보완.
"""

from __future__ import annotations

import pandas as pd


def ts01_transaction_burst(
    df: pd.DataFrame,
    window_days: int = 7,
    sigma: float = 3.0,
) -> pd.Series:
    """일별 거래 건수가 롤링 평균 + σ×std 초과 시 급증 플래그.

    Why: 특정 기간에 거래가 비정상적으로 몰리면 부정·오류 의심.
         감사기준서 240호 근거 (severity 4).
    """
    if "posting_date" not in df.columns:
        return pd.Series(False, index=df.index)

    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    valid_mask = dates.notna()
    if not valid_mask.any():
        return pd.Series(False, index=df.index)

    # Why: 날짜 단위 truncate → 일별 거래 건수 집계
    date_only = dates.dt.normalize()
    daily_counts = date_only[valid_mask].groupby(date_only[valid_mask]).count()

    # Why: 주말·공휴일에는 행 자체가 없으므로 resample로 빈 날짜를 0으로 채워야
    #      rolling 윈도우가 "존재하는 행" 기준이 아닌 실제 날짜 기준으로 동작
    daily_counts.index = pd.DatetimeIndex(daily_counts.index)
    daily_counts = daily_counts.resample("D").sum().fillna(0)

    if len(daily_counts) <= 1:
        return pd.Series(False, index=df.index)

    # Why: shift(1)로 당일을 제외한 직전 window_days의 통계만 사용.
    #      당일 건수가 자기 자신의 baseline을 올려 미탐지되는 것을 방지.
    # Why: min_periods=window_days → 워밍업 기간(데이터 부족)은 NaN → 미플래그
    shifted = daily_counts.shift(1)
    rolling = shifted.rolling(window=window_days, min_periods=window_days)
    rolling_mean = rolling.mean()
    rolling_std = rolling.std(ddof=1).fillna(0.0)

    threshold = rolling_mean + sigma * rolling_std
    # Why: NaN threshold → daily_counts > NaN = False → 자동 미플래그
    burst_dates = set(daily_counts[daily_counts > threshold].index.normalize())

    if not burst_dates:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    result[valid_mask] = date_only[valid_mask].isin(burst_dates)
    return result


def ts02_unusual_frequency(
    df: pd.DataFrame,
    group_col: str = "auxiliary_account_number",
    window_days: int = 7,
    min_count: int = 5,
) -> pd.Series:
    """그룹(거래처/계정)별 단기간 거래 집중 탐지.

    Why: 특정 vendor에 거래가 비정상적으로 몰리면 담합·분할 의심.
         감사기준서 240호 근거 (severity 2).
    """
    if "posting_date" not in df.columns or group_col not in df.columns:
        return pd.Series(False, index=df.index)

    # Why: 정렬 없이 groupby+rolling하면 미래 날짜와 계산이 섞이는 치명적 오류.
    #      sort_values는 인덱스 보존 → grp.index = 원본 df.index. reset_index() 금지.
    sorted_df = df.sort_values("posting_date").copy()
    sorted_df["_date"] = pd.to_datetime(sorted_df["posting_date"], errors="coerce")
    valid = sorted_df["_date"].notna()

    result = pd.Series(False, index=df.index)
    if not valid.any():
        return result

    # Why: 그룹별로 슬라이딩 윈도우 내 최대 건수를 계산하여 집중 여부 판정
    import numpy as np

    window_ns = np.timedelta64(window_days, "D")
    for _group, grp in sorted_df[valid].groupby(group_col):
        if len(grp) < min_count:
            continue

        # Why: .values 대신 명시적 dtype 지정 → numpy.datetime64 뺄셈 타입 안전
        dates = grp["_date"].to_numpy(dtype="datetime64[ns]")
        # Why: 투 포인터로 윈도우 내 건수 계산 (O(n) 복잡도)
        max_in_window = 0
        left = 0
        for right in range(len(dates)):
            while dates[right] - dates[left] > window_ns:
                left += 1
            max_in_window = max(max_in_window, right - left + 1)

        if max_in_window >= min_count:
            result.loc[grp.index] = True

    return result
