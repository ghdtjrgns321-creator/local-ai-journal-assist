"""Layer D 룰 함수 — D01 계정과목 집계 급변, D02 월별 분포 패턴 변화.

Why: 전기 대비 변동을 탐지하는 순수 함수.
     PriorSummary 객체 의존 없이 dict만 받아 테스트 용이성 확보.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon

# Why: 전기 값이 0인 계정의 division-by-zero 방지.
#      1.0으로 설정 시 당기 금액이 그대로 변동률이 되어 신규 계정에 준하는 처리.
#      원 단위 금액 기준이므로 1원 미만의 정밀도는 의미 없음.
_EPSILON = 1.0

# Why: D01 가중평균 — 총액 변동이 가장 중요, 건수·평균 순
_W_TOTAL = 0.5
_W_COUNT = 0.3
_W_AVG = 0.2

# Why: D02 — 비교 의미 있는 최소 월 수
_MIN_MONTHS = 3


def d01_account_aggregate_variance(
    df: pd.DataFrame,
    prior_aggregates: dict[str, dict[str, float]],
    variance_threshold: float = 0.5,
) -> pd.Series:
    """D01 계정과목 집계 급변: 전기 대비 50% 초과 변동 계정 플래그.

    Why: ISA 520 §5 분석적 절차 — 계정과목별 총액·건수·평균의
         가중 변동률이 임계값을 초과하면 급변으로 판정.
    """
    if "gl_account" not in df.columns:
        return pd.Series(False, index=df.index)
    if not prior_aggregates:
        return pd.Series(False, index=df.index)

    # 당기 계정별 집계
    amount = df[["debit_amount", "credit_amount"]].fillna(0).sum(axis=1)
    current_agg = (
        df.assign(_amount=amount)
        .groupby("gl_account")["_amount"]
        .agg(total_amount="sum", count="count", avg_amount="mean")
    )

    # 계정별 가중 변동률 산출
    flagged_accounts: set[str] = set()
    for acct, row in current_agg.iterrows():
        prior = prior_aggregates.get(acct)
        if prior is None:
            # Why: 전기에 없던 신규 계정 → 자동 플래그
            flagged_accounts.add(acct)
            continue

        # Why: abs() 필수 — 증가/감소 모두 "급변"으로 탐지
        total_var = abs(row["total_amount"] - prior["total_amount"]) / max(prior["total_amount"], _EPSILON)
        count_var = abs(row["count"] - prior["count"]) / max(prior["count"], _EPSILON)
        avg_var = abs(row["avg_amount"] - prior["avg_amount"]) / max(prior["avg_amount"], _EPSILON)

        weighted = total_var * _W_TOTAL + count_var * _W_COUNT + avg_var * _W_AVG
        if weighted > variance_threshold:
            flagged_accounts.add(acct)

    return df["gl_account"].isin(flagged_accounts)


def d02_monthly_pattern_variance(
    df: pd.DataFrame,
    prior_patterns: dict[str, dict[int, float]],
    jsd_threshold: float = 0.3,
) -> pd.Series:
    """D02 월별 분포 패턴 변화: JSD로 전기/당기 월별 분포 비교.

    Why: ISA 520 §5 — 특정 월에 거래가 급격히 집중되면
         기말 매출 조작, 비용 이연 등을 의심할 수 있음.
    """
    if "gl_account" not in df.columns or "fiscal_period" not in df.columns:
        return pd.Series(False, index=df.index)
    if not prior_patterns:
        return pd.Series(False, index=df.index)

    # 당기 계정×월별 금액 합계
    amount = df[["debit_amount", "credit_amount"]].fillna(0).sum(axis=1)
    monthly = (
        df.assign(_amount=amount)
        .groupby(["gl_account", "fiscal_period"])["_amount"]
        .sum()
    )

    flagged_accounts: set[str] = set()

    for acct in monthly.index.get_level_values("gl_account").unique():
        prior_dist_dict = prior_patterns.get(acct)
        if prior_dist_dict is None:
            continue

        # Why: 12개월 고정 벡터로 정렬 — 없는 월은 0.0 패딩
        prior_vec = np.array([prior_dist_dict.get(m, 0.0) for m in range(1, 13)])
        current_amounts = monthly.loc[acct]
        current_vec = np.zeros(12)
        for period, amt in current_amounts.items():
            try:
                month_idx = int(period) - 1
            except (TypeError, ValueError):
                continue  # NaN 또는 비정수 period는 무시
            if 0 <= month_idx < 12:
                current_vec[month_idx] = amt

        # Why: 비교 의미 있으려면 전기/당기 모두 3개월 이상 데이터 필요
        if np.count_nonzero(prior_vec) < _MIN_MONTHS:
            continue
        if np.count_nonzero(current_vec) < _MIN_MONTHS:
            continue

        # Why: JSD는 확률분포 비교 → 합이 1.0이 되도록 정규화
        prior_sum = prior_vec.sum()
        current_sum = current_vec.sum()
        if prior_sum == 0 or current_sum == 0:
            continue

        prior_norm = prior_vec / prior_sum
        current_norm = current_vec / current_sum

        jsd = jensenshannon(prior_norm, current_norm)
        if jsd > jsd_threshold:
            flagged_accounts.add(acct)

    return df["gl_account"].isin(flagged_accounts)
