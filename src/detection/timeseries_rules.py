"""Timeseries family statistical anomaly sub-signals + legacy boolean rules.

Why: rule-style boolean burst/frequency → robust z-score + ECDF normalization +
period-end concentration 결합으로 격상. row-level continuous score를 산출하고
TimeseriesDetector가 ECDF threshold로 TS01/TS02 boolean을 재계산한다.

Phase 1 rule hit / flagged_rules / DataSynth 라벨을 입력으로 사용하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.detection.boolean_utils import bool_column
from src.feature.amount_features import significant_digit_stats

_MAD_SCALE = 0.6745  # modified z-score (normal consistent constant)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _empty_score(index: pd.Index) -> pd.Series:
    return pd.Series(0.0, index=index, dtype=float)


def zero_preserving_ecdf(scores: pd.Series) -> pd.Series:
    """0/NaN 행을 0으로 보존하는 batch-local ECDF.

    Why: 0점 행이 batch rank 때문에 양수 ECDF를 받으면 family coverage가
    부풀려진다. 양수 행 사이 ranking 은 동률 그룹이 자기 그룹 최대 rank 를
    받도록 method="max" — 동일 z 값을 가진 burst day 행 다수가 평균 rank 때문에
    percentile 이 깎여 high tail 진입을 놓치는 boundary effect 를 막는다.
    """
    series = scores if isinstance(scores, pd.Series) else pd.Series(scores)
    clean = pd.Series(pd.to_numeric(series, errors="coerce"), index=series.index).fillna(0.0)
    clean = clean.astype(float)
    ecdf = pd.Series(0.0, index=clean.index, dtype=float)
    positive = clean > 0
    if positive.any():
        ecdf.loc[positive] = clean.loc[positive].rank(method="max", pct=True)
    return ecdf


def _robust_z(value: float, median: float, mad: float, iqr: float) -> float:
    """MAD → IQR → Poisson std (count data) fallback 순.

    Why: 거래 건수처럼 평탄 baseline 에서 MAD=0/IQR=0 이 자주 나온다.
         count data 는 Poisson 가까운 경우가 많아 std ≈ sqrt(median)으로
         보수 fallback. median=0 이면 raw value 자체를 capped score 로 사용.
    """
    if mad and mad > 0:
        return _MAD_SCALE * (value - median) / mad
    if iqr and iqr > 0:
        # Why: 표본이 적거나 다수 동일값이라 MAD=0인 경우 IQR로 보정.
        return (value - median) / (iqr / 1.349)
    if median > 0:
        poisson_std = max(median**0.5, 1.0)
        return (value - median) / poisson_std
    if value > 0:
        return float(min(value, 10.0))
    return 0.0


_ROBUST_Z_NOISE_FLOOR = 1.5  # modified z 의 표준 노이즈 cutoff (대략 |z|≈1 MAD)


def _positive_clip(values: pd.Series) -> pd.Series:
    """음의 z + noise floor 차단.

    Why: rolling baseline 의 partial window / cycle effect 에서 modified z 가
         1.0~1.5 수준의 작은 양수가 자주 잡힌다. 도메인적으로 의미 있는 burst
         는 보통 z ≥ 2 이상이므로 1.5 미만은 0 으로 절단해 false positive 차단.
    """
    return (values - _ROBUST_Z_NOISE_FLOOR).clip(lower=0.0)


# ---------------------------------------------------------------------------
# sub-signal score functions
# ---------------------------------------------------------------------------


@dataclass
class SubSignalResult:
    """Sub-signal 산출 결과 + JSON-serializable metadata."""

    name: str
    active: bool
    score: pd.Series
    meta: dict[str, object] = field(default_factory=dict)


def daily_burst_positive_robust_z_score(
    df: pd.DataFrame,
    *,
    window_days: int = 14,
) -> SubSignalResult:
    """일별 거래 건수의 robust z-score (positive only).

    Why: rolling median + MAD 기반 modified z-score는 outlier에 둔감하다.
         shift(1) 로 leave-one-out → 당일 자체가 baseline을 끌어올려
         자기 자신을 감추는 효과 차단.
    """
    name = "daily_burst_positive_robust_z"
    if "posting_date" not in df.columns or df.empty:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "missing_posting_date"},
        )

    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    valid_mask = dates.notna()
    if not valid_mask.any():
        return SubSignalResult(
            name=name, active=False, score=_empty_score(df.index), meta={"reason": "all_dates_nat"}
        )

    date_only = dates.dt.normalize()
    daily_counts = date_only[valid_mask].groupby(date_only[valid_mask]).size().astype(float)
    daily_counts.index = pd.DatetimeIndex(daily_counts.index)
    # Why: 영업일 공백을 0으로 채워 rolling window가 캘린더 기준으로 동작.
    daily_counts = daily_counts.resample("D").sum().fillna(0.0)

    if len(daily_counts) < 2:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "single_day_series", "support_days": int(len(daily_counts))},
        )

    shifted = daily_counts.shift(1)
    rolling = shifted.rolling(window=window_days, min_periods=max(2, window_days // 2))
    rolling_median = rolling.median()
    abs_dev = (shifted - rolling_median).abs()
    rolling_mad = abs_dev.rolling(window=window_days, min_periods=max(2, window_days // 2)).median()
    rolling_q75 = shifted.rolling(
        window=window_days, min_periods=max(2, window_days // 2)
    ).quantile(0.75)
    rolling_q25 = shifted.rolling(
        window=window_days, min_periods=max(2, window_days // 2)
    ).quantile(0.25)
    rolling_iqr = (rolling_q75 - rolling_q25).fillna(0.0)

    z_by_date = pd.Series(0.0, index=daily_counts.index, dtype=float)
    for date_value in daily_counts.index:
        med = rolling_median.get(date_value, np.nan)
        mad = rolling_mad.get(date_value, np.nan)
        iqr_v = rolling_iqr.get(date_value, 0.0)
        if pd.isna(med):
            continue
        z_by_date.loc[date_value] = _robust_z(
            float(daily_counts.loc[date_value]),
            float(med),
            float(mad if not pd.isna(mad) else 0.0),
            float(iqr_v if not pd.isna(iqr_v) else 0.0),
        )

    z_by_date = _positive_clip(z_by_date)
    raw_max = float(z_by_date.max()) if not z_by_date.empty else 0.0
    # Why: 극단 z 가 family score를 monopoly 하지 않게 [0,30] clip.
    #      30 은 Poisson fallback 기준 baseline=5 의 burst 90건 수준이라
    #      현실적으로 충분히 큰 burst 까지 분해능을 보존.
    z_by_date_clipped = z_by_date.clip(upper=30.0)

    score = _empty_score(df.index)
    if z_by_date_clipped.gt(0).any():
        date_score_map = z_by_date_clipped.to_dict()
        normalized = date_only.map(
            lambda x: date_score_map.get(pd.Timestamp(x).normalize(), 0.0) if pd.notna(x) else 0.0
        )
        score = normalized.astype(float)

    return SubSignalResult(
        name=name,
        active=True,
        score=score,
        meta={
            "window_days": int(window_days),
            "support_days": int(len(daily_counts)),
            "raw_max_positive_z": float(raw_max),
            "nonzero_day_count": int((z_by_date_clipped > 0).sum()),
        },
    )


def group_frequency_positive_robust_z_score(
    df: pd.DataFrame,
    *,
    window_days: int = 7,
    min_support: int = 10,
    min_active_days: int = 3,
    min_excess_count: int = 3,
    spike_ratio_min: float = 2.0,
    cold_start_score_cap: float = 0.30,
    group_candidates: tuple[str, ...] = (
        "auxiliary_account_number",
        "trading_partner",
        "created_by",
    ),
) -> SubSignalResult:
    """그룹별 단기 window 빈도의 robust z-score (true spike only).

    Why: 동일 vendor/account 가 짧은 기간에 자기 baseline 대비 비정상적으로
         몰리는 spike 패턴만 양수 score 로 인정한다. broad activity / routine
         frequency / cold-start 첫 활동은 strong anomaly 가 아니라 context 신호
         (cold_start_score_cap 이하) 로만 본다.

    Spike 인정 AND 조건 (sanity guard — truth recall 튜닝 아님):
      1. group 총 support ≥ min_support — baseline 유의성
      2. group 활성일 ≥ min_active_days — 단일 일자는 daily_burst(TS01) 영역
      3. baseline = leave-one-out rolling window median (당일 자기 활동 제외)
      4. 절대 excess: current_count - baseline_median ≥ min_excess_count
      5. 비율: current_count / max(baseline_median, 1) ≥ spike_ratio_min
      6. baseline_median == 0 인 cold-start group 은 score ≤ cold_start_score_cap

    위 조건 위반 행은 suppressed_broad_activity_rows 카운터에만 기록되고
    score = 0 (TS02 details / row_score 양쪽 모두 미기여).
    """
    name = "group_frequency_positive_robust_z"
    if "posting_date" not in df.columns or df.empty:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "missing_posting_date"},
        )

    chosen_group: str | None = next(
        (col for col in group_candidates if col in df.columns and df[col].notna().any()),
        None,
    )
    if chosen_group is None:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "no_group_column", "candidates": list(group_candidates)},
        )

    work = df[["posting_date", chosen_group]].copy()
    work["_date"] = pd.to_datetime(work["posting_date"], errors="coerce")
    work = work[work["_date"].notna() & work[chosen_group].notna()]
    if work.empty:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "no_valid_rows", "group_col": chosen_group},
        )

    score = _empty_score(df.index)
    group_stats: list[dict[str, object]] = []
    spike_group_count = 0
    cold_start_group_count = 0
    suppressed_low_support_group_count = 0
    suppressed_low_active_days_group_count = 0
    suppressed_broad_activity_rows = 0
    spike_row_count = 0
    cold_start_row_count = 0
    evaluated_group_count = 0
    min_periods = max(2, window_days // 2)

    for group_value, grp in work.groupby(chosen_group, sort=False):
        evaluated_group_count += 1
        # Why(가드 1): 그룹 총 support 가 부족하면 baseline 의 통계적 유의성 없음.
        if len(grp) < min_support:
            suppressed_low_support_group_count += 1
            suppressed_broad_activity_rows += int(len(grp))
            continue
        grp_sorted = grp.sort_values("_date")
        grp_dates_normalized = grp_sorted["_date"].dt.normalize()
        # Why(가드 2): 활성일 부족은 단일 일자 burst (TS01 daily_burst 영역) 또는
        # 극희소 신호 — group spike 의 의미적 정의를 만족하지 않음.
        active_days = int(grp_dates_normalized.nunique())
        if active_days < min_active_days:
            suppressed_low_active_days_group_count += 1
            suppressed_broad_activity_rows += int(len(grp))
            continue
        # Why: 같은 일자 행은 동일 score — row-position cycle effect 차단.
        daily_grp_counts = (
            pd.Series(1.0, index=pd.DatetimeIndex(grp_dates_normalized)).groupby(level=0).sum()
        )
        if len(daily_grp_counts) < 2:
            suppressed_broad_activity_rows += int(len(grp))
            continue
        daily_grp_counts = daily_grp_counts.resample("D").sum().fillna(0.0)
        # Why: 일자 단위 trailing window sum + leave-one-out (shift(1)) 으로
        # baseline 산출 — 당일 자기 활동이 자기 baseline 을 끌어올려 spike 를
        # 감추는 효과 차단.
        shifted = daily_grp_counts.shift(1)
        rolling_sum_shifted = shifted.rolling(window=window_days, min_periods=min_periods).sum()
        current_window_sum = daily_grp_counts.rolling(
            window=window_days, min_periods=min_periods
        ).sum()
        valid = rolling_sum_shifted.dropna()
        if len(valid) < 2:
            suppressed_broad_activity_rows += int(len(grp))
            continue
        baseline_median = float(valid.median())
        baseline_mad = float((valid - baseline_median).abs().median())
        baseline_iqr = float(valid.quantile(0.75) - valid.quantile(0.25))
        is_cold_start = baseline_median == 0.0

        z_by_day: dict[pd.Timestamp, float] = {}
        spike_day_count_grp = 0
        cold_start_day_count_grp = 0
        suppressed_day_count_grp = 0
        raw_max = 0.0
        for day_ts in current_window_sum.index:
            value = current_window_sum.loc[day_ts]
            if pd.isna(value):
                continue
            value_f = float(value)
            if value_f <= 0:
                continue
            if is_cold_start:
                # Why(가드 6): baseline 정보가 없으므로 boost 입력 자격만. cap 이하 score.
                # value 가 클수록 cold_start_cap 에 수렴 (1 - exp(-value/3))*cap.
                cold_score = float(cold_start_score_cap * (1.0 - np.exp(-value_f / 3.0)))
                if cold_score > 0:
                    z_by_day[pd.Timestamp(day_ts)] = cold_score
                    cold_start_day_count_grp += 1
                    raw_max = max(raw_max, cold_score)
                continue
            excess = value_f - baseline_median
            ratio = value_f / max(baseline_median, 1.0)
            # Why(가드 4, 5): 절대 excess + 비율 동시 만족 시만 spike 인정.
            # 둘 중 하나라도 미달이면 broad activity / routine 으로 분류 → score=0.
            if excess < min_excess_count or ratio < spike_ratio_min:
                suppressed_day_count_grp += 1
                continue
            raw_z = _robust_z(value_f, baseline_median, baseline_mad, baseline_iqr)
            # Why: noise floor 차감 후 [0, 30] clip — daily_burst 와 일관.
            clipped = float(np.clip(raw_z - _ROBUST_Z_NOISE_FLOOR, 0.0, 30.0))
            if clipped > 0:
                z_by_day[pd.Timestamp(day_ts)] = clipped
                spike_day_count_grp += 1
                raw_max = max(raw_max, clipped)
            else:
                suppressed_day_count_grp += 1

        # Why: suppressed_day → 해당 일자 group 행은 broad 카운터에 반영.
        if suppressed_day_count_grp > 0:
            day_to_rowcount = grp_dates_normalized.value_counts().to_dict()
            for day_ts in current_window_sum.index:
                if day_ts in z_by_day:
                    continue
                value = current_window_sum.get(day_ts)
                if value is None or pd.isna(value) or float(value) <= 0:
                    continue
                suppressed_broad_activity_rows += int(day_to_rowcount.get(pd.Timestamp(day_ts), 0))

        if not z_by_day:
            continue

        score_for_grp = grp_dates_normalized.map(
            lambda x: z_by_day.get(pd.Timestamp(x), 0.0) if pd.notna(x) else 0.0
        ).astype(float)
        score.loc[grp_sorted.index] = score_for_grp.values
        nonzero_row_mask = score_for_grp > 0

        if is_cold_start:
            cold_start_group_count += 1
            cold_start_row_count += int(nonzero_row_mask.sum())
        if spike_day_count_grp > 0:
            spike_group_count += 1
            # Why: cold-start 가 아닌 group 에서 z_by_day 양수 행 = 실제 spike row.
            spike_row_count += int(nonzero_row_mask.sum()) if not is_cold_start else 0
        group_stats.append(
            {
                "group_value": str(group_value),
                "row_count": int(len(grp)),
                "active_days": active_days,
                "baseline_median_window_sum": baseline_median,
                "max_positive_z": raw_max,
                "is_cold_start": bool(is_cold_start),
                "spike_day_count": int(spike_day_count_grp),
            }
        )

    raw_max = float(score.max()) if not score.empty else 0.0
    return SubSignalResult(
        name=name,
        active=True,
        score=score,
        meta={
            "group_col": chosen_group,
            "window_days": int(window_days),
            "min_support": int(min_support),
            "min_active_days": int(min_active_days),
            "min_excess_count": int(min_excess_count),
            "spike_ratio_min": float(spike_ratio_min),
            "cold_start_score_cap": float(cold_start_score_cap),
            "raw_max_positive_z": raw_max,
            "evaluated_group_count": int(evaluated_group_count),
            "spike_group_count": int(spike_group_count),
            "cold_start_group_count": int(cold_start_group_count),
            "suppressed_low_support_group_count": int(suppressed_low_support_group_count),
            "suppressed_low_active_days_group_count": int(suppressed_low_active_days_group_count),
            "suppressed_broad_activity_rows": int(suppressed_broad_activity_rows),
            "spike_row_count": int(spike_row_count),
            "cold_start_row_count": int(cold_start_row_count),
            # Why: 상위 5개 그룹만 노출 — JSON serializable scalar/list 만.
            "top_group_examples": sorted(
                group_stats,
                key=lambda x: x["max_positive_z"],
                reverse=True,
            )[:5],
        },
    )


def period_end_concentration_score(
    df: pd.DataFrame,
    *,
    proximity_window_days: int = 3,
) -> SubSignalResult:
    """월말/분기말/회계연도말 근접도 × 해당 일자 거래량 모집단 percentile.

    Why: ISA 240 ¶A41 (period end transaction) 직접 인용. 단순 결산기 routine 은
         모든 결산일에서 비슷한 daily volume percentile 을 가져 분포 tail 만
         점수가 부풀려지지 않도록 ECDF 정규화와 함께 사용.
    """
    name = "period_end_concentration"
    if "posting_date" not in df.columns or df.empty:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "missing_posting_date"},
        )

    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    valid_mask = dates.notna()
    if not valid_mask.any():
        return SubSignalResult(
            name=name, active=False, score=_empty_score(df.index), meta={"reason": "all_dates_nat"}
        )

    # Why: 일자별 거래량 모집단 percentile (top-tail 만 사용).
    date_only = dates.dt.normalize()
    daily_counts = date_only[valid_mask].value_counts().astype(float)
    if daily_counts.empty:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "no_daily_counts"},
        )
    daily_pctile = daily_counts.rank(method="average", pct=True)
    # Why: 상위 tail 만 의미 — 0.5 (median) 이하는 0 으로 절단.
    daily_pctile_tail = (daily_pctile - 0.5).clip(lower=0.0) * 2.0

    # Why: 월말/분기말/연말까지 일수 → 선형 감쇠 가중치.
    window = max(int(proximity_window_days), 1)
    month_end = date_only + pd.offsets.MonthEnd(0)
    quarter_end = date_only + pd.offsets.QuarterEnd(0)
    year_end = date_only + pd.offsets.YearEnd(0)
    days_to_month_end = (month_end - date_only).dt.days.abs()
    days_to_quarter_end = (quarter_end - date_only).dt.days.abs()
    days_to_year_end = (year_end - date_only).dt.days.abs()

    # Why: distance/(window+1) 로 나눠 D-window 가 0 점이 되지 않도록 한다.
    # 결과 — D0=1.0, D-1=window/(w+1), …, D-window=1/(w+1) 모두 양수.
    # 외부(window+1일 이상)는 clip 으로 0.
    def _proximity(distance: pd.Series) -> pd.Series:
        clipped = distance.clip(lower=0.0, upper=window + 1)
        return (1.0 - clipped / (window + 1)).fillna(0.0)

    proximity = pd.concat(
        [
            _proximity(days_to_month_end),
            _proximity(days_to_quarter_end) * 1.0,
            _proximity(days_to_year_end) * 1.0,
        ],
        axis=1,
    ).max(axis=1)

    daily_tail_map = daily_pctile_tail.to_dict()
    daily_tail_series = date_only.map(
        lambda x: daily_tail_map.get(pd.Timestamp(x).normalize(), 0.0) if pd.notna(x) else 0.0
    ).astype(float)

    raw_score = (proximity * daily_tail_series).clip(lower=0.0, upper=1.0)
    raw_score.loc[~valid_mask] = 0.0

    return SubSignalResult(
        name=name,
        active=True,
        score=raw_score.astype(float),
        meta={
            "proximity_window_days": int(window),
            "support_days": int(len(daily_counts)),
            "nonzero_row_count": int((raw_score > 0).sum()),
            "raw_max_score": float(raw_score.max()) if not raw_score.empty else 0.0,
            "sub_signal_only": True,
        },
    )


# ---------------------------------------------------------------------------
# amount tail helper (period_end gating context 산출용)
# ---------------------------------------------------------------------------


_AMOUNT_COLUMN_CANDIDATES: tuple[str, ...] = (
    "amount",
    "transaction_amount",
    "absolute_amount",
    "debit_amount",
    "credit_amount",
)


def row_amount_tail_score(
    df: pd.DataFrame,
    *,
    candidates: tuple[str, ...] = _AMOUNT_COLUMN_CANDIDATES,
) -> SubSignalResult:
    """행 금액의 모집단 top-tail percentile (0.5 median 이하 = 0).

    Why: ISA 240 기반 audit anomaly 판정에서 금액 규모가 큰 거래는 분포 tail
         만으로도 의미 있는 context signal 이다. period_end gating 의 anomaly
         context 한 축으로 사용 — 단독 사용 금지 (graceful: 컬럼 없으면 inactive).
    """
    name = "row_amount_tail"
    if df.empty:
        return SubSignalResult(
            name=name, active=False, score=_empty_score(df.index), meta={"reason": "empty_df"}
        )

    chosen: str | None = None
    for col in candidates:
        if col not in df.columns:
            continue
        col_series = pd.Series(pd.to_numeric(df[col], errors="coerce"), index=df.index)
        if col_series.abs().fillna(0.0).gt(0).any():
            chosen = col
            break
    if chosen is None:
        # Why: debit/credit 둘 다 있으면 row 별 큰 쪽 사용.
        debit = df.get("debit_amount")
        credit = df.get("credit_amount")
        if debit is None or credit is None:
            return SubSignalResult(
                name=name,
                active=False,
                score=_empty_score(df.index),
                meta={"reason": "no_amount_column", "candidates": list(candidates)},
            )
        debit_series = pd.to_numeric(debit, errors="coerce").abs().fillna(0.0)
        credit_series = pd.to_numeric(credit, errors="coerce").abs().fillna(0.0)
        amount_abs = pd.concat([debit_series, credit_series], axis=1).max(axis=1).astype(float)
        chosen = "debit_or_credit_max"
    else:
        amount_abs = pd.to_numeric(df[chosen], errors="coerce").abs().fillna(0.0).astype(float)

    positive_n = int((amount_abs > 0).sum())
    if positive_n < 2:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={
                "reason": "insufficient_positive_amounts",
                "amount_col": chosen,
                "positive_n": positive_n,
            },
        )

    # Why: 모든 금액이 동률이면 distribution tail signal 자체가 의미 없다.
    # context gating 의 false-positive (amount_tail 이 모든 행에 1.0 부여) 방지.
    unique_amounts = int(amount_abs[amount_abs > 0].nunique())
    if unique_amounts < 3:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={
                "reason": "insufficient_amount_variance",
                "amount_col": chosen,
                "unique_positive_amounts": unique_amounts,
            },
        )

    pctile = amount_abs.rank(method="max", pct=True)
    # Why: 상위 tail 만 의미 — 0.5 (median) 이하는 0 으로 절단 → 0~1 scale.
    score = ((pctile - 0.5).clip(lower=0.0) * 2.0).astype(float)
    return SubSignalResult(
        name=name,
        active=True,
        score=score,
        meta={
            "amount_col": chosen,
            "positive_amount_row_count": positive_n,
            "score_q95": float(score.quantile(0.95)),
            "score_q99": float(score.quantile(0.99)),
            "score_max": float(score.max()),
        },
    )


# ---------------------------------------------------------------------------
# context axis sub-signals (after_hours / manual / round)
# ---------------------------------------------------------------------------


def after_hours_or_weekend_score(df: pd.DataFrame) -> SubSignalResult:
    """근무시간 외/주말 boolean context signal.

    Why: ISA 240 ¶A41 (b) 비정상 시간대 거래. is_after_hours 또는 is_weekend 가
         True 인 행에 0.5 score (boolean context — composite gate 입력 전용).
         단독으로 row_score 에 기여 금지 (context_count 산입만).
    """
    name = "after_hours_or_weekend"
    if df.empty:
        return SubSignalResult(
            name=name, active=False, score=_empty_score(df.index), meta={"reason": "empty_df"}
        )

    has_after_hours = "is_after_hours" in df.columns
    has_weekend = "is_weekend" in df.columns
    if not (has_after_hours or has_weekend):
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "no_temporal_flag", "candidates": ["is_after_hours", "is_weekend"]},
        )

    flag = pd.Series(False, index=df.index)
    if has_after_hours:
        flag = flag | bool_column(df, "is_after_hours")
    if has_weekend:
        flag = flag | bool_column(df, "is_weekend")

    # Why: 0.5 는 boolean context 의 sub-signal score (rarity_tail 산입 금지, context_count
    #      판정 입력만). composite gate 통과 시 합산되지 않고 raw 신호로만 사용.
    score = flag.astype(float) * 0.5
    nonzero = int(flag.sum())
    return SubSignalResult(
        name=name,
        active=True,
        score=score,
        meta={
            "nonzero_row_count": nonzero,
            "nonzero_rate": float(flag.mean()) if len(flag) else 0.0,
            "has_after_hours": has_after_hours,
            "has_weekend": has_weekend,
            "context_only": True,
        },
    )


def manual_or_adjustment_score(
    df: pd.DataFrame,
    *,
    manual_source_values: tuple[str, ...] = (
        "manual",
        "MANUAL",
        "Manual",
        "hand",
        "HAND",
        "adjustment",
        "ADJUSTMENT",
        "adj",
        "ADJ",
        "수기",
    ),
) -> SubSignalResult:
    """수기/조정 전표 boolean context signal.

    Why: PCAOB AS 2401 §B7 manual journal entries 직접 인용. is_manual_je 또는
         source ∈ {manual, hand, adjustment, …} 인 행에 0.5 score.
    """
    name = "manual_or_adjustment"
    if df.empty:
        return SubSignalResult(
            name=name, active=False, score=_empty_score(df.index), meta={"reason": "empty_df"}
        )

    flag = pd.Series(False, index=df.index)
    used: list[str] = []
    if "is_manual_je" in df.columns:
        flag = flag | bool_column(df, "is_manual_je")
        used.append("is_manual_je")
    if "source" in df.columns:
        manual_set = {str(v).strip().lower() for v in manual_source_values}
        source_match = df["source"].astype(str).str.strip().str.lower().isin(manual_set)
        flag = flag | source_match.fillna(False)
        used.append("source")

    if not used:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "no_manual_flag", "candidates": ["is_manual_je", "source"]},
        )

    score = flag.astype(float) * 0.5
    nonzero = int(flag.sum())
    return SubSignalResult(
        name=name,
        active=True,
        score=score,
        meta={
            "nonzero_row_count": nonzero,
            "nonzero_rate": float(flag.mean()) if len(flag) else 0.0,
            "columns_used": used,
            "context_only": True,
        },
    )


def round_amount_score(
    df: pd.DataFrame,
    *,
    max_significant_digits: int = 2,
    min_digits: int = 3,
) -> SubSignalResult:
    """근사치 금액 boolean context signal.

    Why: PCAOB AS 2401 §B7 round-dollar amounts. is_round_number 가 있으면 우선 사용,
         없으면 |debit-credit| 의 max 로 같은 상대 기준(끝자리 0 개수)을 재계산한다.
         2026-07-15 절대 단위(round_unit) 폐기 — feature 정의와 fallback 이 어긋나면
         is_round_number 유무에 따라 같은 전표가 다르게 판정된다.
    """
    name = "round_amount"
    if df.empty:
        return SubSignalResult(
            name=name, active=False, score=_empty_score(df.index), meta={"reason": "empty_df"}
        )

    if "is_round_number" in df.columns:
        flag = bool_column(df, "is_round_number")
        score = flag.astype(float) * 0.5
        return SubSignalResult(
            name=name,
            active=True,
            score=score,
            meta={
                "nonzero_row_count": int(flag.sum()),
                "nonzero_rate": float(flag.mean()) if len(flag) else 0.0,
                "source": "is_round_number",
                "context_only": True,
            },
        )

    debit = df.get("debit_amount")
    credit = df.get("credit_amount")
    if debit is None and credit is None:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "no_amount_column"},
        )

    debit_abs = (
        pd.to_numeric(debit, errors="coerce").abs().fillna(0.0)
        if debit is not None
        else pd.Series(0.0, index=df.index)
    )
    credit_abs = (
        pd.to_numeric(credit, errors="coerce").abs().fillna(0.0)
        if credit is not None
        else pd.Series(0.0, index=df.index)
    )
    amount_abs = pd.concat([debit_abs, credit_abs], axis=1).max(axis=1).astype(float)
    digits, significant = significant_digit_stats(amount_abs.round(0))
    flag = (
        (amount_abs > 0)
        & (significant <= int(max_significant_digits))
        & (digits >= int(min_digits))
    )
    score = flag.astype(float) * 0.5
    return SubSignalResult(
        name=name,
        active=True,
        score=score,
        meta={
            "nonzero_row_count": int(flag.sum()),
            "nonzero_rate": float(flag.mean()) if len(flag) else 0.0,
            "source": "debit_credit_significant_digits",
            "max_significant_digits": int(max_significant_digits),
            "min_digits": int(min_digits),
            "context_only": True,
        },
    )


# ---------------------------------------------------------------------------
# rarity axis sub-signals (account_process / user_account / partner_account)
# ---------------------------------------------------------------------------


def _pair_rarity_score(
    df: pd.DataFrame,
    col_a: str,
    col_b: str,
    *,
    name: str,
    min_pair_population: int,
) -> SubSignalResult:
    """전역 (col_a, col_b) pair 빈도의 inverse → batch-local ECDF rarity score.

    Why: rare combination 은 단순 첫 등장이 아니라 *전역 모집단 대비 드문* 조합.
         freq=1 인 행이 rarity 1.0 에 가깝고, freq=N 인 행은 0 에 가깝다. ECDF
         (zero-preserving) 로 0~1 정규화. batch-local 한계는 metadata 명시.
    """
    if df.empty:
        return SubSignalResult(
            name=name, active=False, score=_empty_score(df.index), meta={"reason": "empty_df"}
        )
    if col_a not in df.columns or col_b not in df.columns:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "missing_columns", "required": [col_a, col_b]},
        )

    work = df[[col_a, col_b]].copy()
    valid = work[col_a].notna() & work[col_b].notna()
    if not valid.any():
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={"reason": "all_null"},
        )

    # Why: pair 모집단이 작으면 통계적으로 의미있는 rarity 산출 불가 (R05 와 일관).
    work_valid = work[valid]
    pair_freq = work_valid.groupby([col_a, col_b]).size()
    unique_pairs = int(len(pair_freq))
    if unique_pairs < min_pair_population:
        return SubSignalResult(
            name=name,
            active=False,
            score=_empty_score(df.index),
            meta={
                "reason": "insufficient_unique_pairs",
                "unique_pairs": unique_pairs,
                "min_pair_population": int(min_pair_population),
            },
        )

    freq_map = pair_freq.to_dict()
    freq_series = pd.Series(0.0, index=df.index, dtype=float)
    work_valid_freq = work_valid.apply(
        lambda row: float(freq_map.get((row[col_a], row[col_b]), 0)), axis=1
    )
    freq_series.loc[work_valid.index] = work_valid_freq.astype(float).values

    # Why: inverse freq 가 batch-local ECDF 의 입력. freq=1 행이 가장 큰 inverse_freq.
    inverse_freq = pd.Series(0.0, index=df.index, dtype=float)
    positive = freq_series > 0
    inverse_freq.loc[positive] = 1.0 / freq_series.loc[positive]
    score = zero_preserving_ecdf(inverse_freq).astype(float)

    return SubSignalResult(
        name=name,
        active=True,
        score=score,
        meta={
            "unique_pairs": unique_pairs,
            "min_pair_population": int(min_pair_population),
            "rare_pair_count": int((freq_series == 1).sum()),
            "median_freq": float(pair_freq.median()),
            "max_freq": int(pair_freq.max()),
            "score_q95": float(score.quantile(0.95)),
            "score_q99": float(score.quantile(0.99)),
            "batch_local_ecdf": True,
            "rarity_axis": True,
        },
    )


def account_process_rarity_score(
    df: pd.DataFrame, *, min_pair_population: int = 50
) -> SubSignalResult:
    """(gl_account, business_process) 희소 조합 rarity.

    Why: 비전형적 계정-프로세스 조합 (e.g. 수익 계정이 구매 프로세스에서 사용) 은
         routine 거래와 구분되는 evidence. composite gate 통과 시 rarity 축 입력.
    """
    return _pair_rarity_score(
        df,
        "gl_account",
        "business_process",
        name="account_process_rarity",
        min_pair_population=min_pair_population,
    )


def user_account_rarity_score(
    df: pd.DataFrame, *, min_pair_population: int = 50
) -> SubSignalResult:
    """(created_by, gl_account) 희소 조합 rarity.

    Why: 평소 다루지 않던 계정을 다룬 사용자 (R06 과 유사하나 batch-local rarity).
    """
    return _pair_rarity_score(
        df,
        "created_by",
        "gl_account",
        name="user_account_rarity",
        min_pair_population=min_pair_population,
    )


def partner_account_rarity_score(
    df: pd.DataFrame, *, min_pair_population: int = 50
) -> SubSignalResult:
    """(trading_partner, gl_account) 희소 조합 rarity.

    Why: 비전형적 거래처-계정 조합 (R05 와 유사). composite gate 의 rarity 축 입력.
    """
    return _pair_rarity_score(
        df,
        "trading_partner",
        "gl_account",
        name="partner_account_rarity",
        min_pair_population=min_pair_population,
    )


# ---------------------------------------------------------------------------
# composite temporal anomaly (3-axis 결합)
# ---------------------------------------------------------------------------


@dataclass
class CompositeResult:
    """Composite temporal anomaly 결합 결과."""

    score: pd.Series
    context_count: pd.Series
    rarity_tail: pd.Series
    strong_present: pd.Series
    meta: dict[str, object] = field(default_factory=dict)


def composite_temporal_anomaly(
    df: pd.DataFrame,
    *,
    strong_burst: pd.Series,
    period_end_raw: pd.Series,
    after_hours_score: pd.Series,
    manual_score: pd.Series,
    round_amount_signal: pd.Series,
    amount_tail: pd.Series,
    account_process_rarity: pd.Series,
    user_account_rarity: pd.Series,
    partner_account_rarity: pd.Series,
    period_end_min: float,
    min_evidence_count: int,
    tail_q: float,
    strong_tail_q: float,
    context_boost_max: float,
    strong_present_threshold: float,
) -> CompositeResult:
    """3-axis evidence 결합으로 composite_score 산출.

    Why: strong (daily_burst / group_spike) 부재 행에 대해 context + rarity 신호가
         결합될 때만 cap 초과 허용. 단독 신호는 차단.

    결합식 (사용자 결정):
      - context_count        = count(period_end_present, after_hours, manual, round)
      - rarity_tail          = max(amount_tail, account_process, user_account,
                                   partner_account)
      - rarity_high_count_qX = count of rarity signals >= qX
      - evidence_count_qX    = context_count + rarity_high_count_qX
      - strong_present       = strong_burst >= strong_present_threshold
      - strong-composite path : evidence_count_q95 >= min_evidence_count
                                AND context_count >= 1 AND rarity_tail >= strong_tail_q
                                → score = min(rarity_tail, context_boost_max)
      - moderate path        : evidence_count_q90 >= min_evidence_count
                                AND context_count >= 1 AND rarity_tail >= tail_q
                                → score = min(rarity_tail * 0.7, context_boost_max)
      - else                  : score = 0 (context-only cap 은 row_score 결합 시 별도)

    허용 케이스 (사용자 명시):
      A. amount_tail + period_end + manual          (ctx=2, rarity_high=1 → ev=3)
      B. amount_tail + after_hours + rare_user_acc  (ctx=1, rarity_high=2 → ev=3)
      C. amount_tail + period_end + round           (ctx=2, rarity_high=1 → ev=3)
    금지 케이스:
      - amount_tail / period_end / after_hours / manual / round / rarity 단독
        → ev<3 or context_count<1 → cap.
    """
    period_end_present = (period_end_raw.fillna(0.0).astype(float) >= float(period_end_min)).astype(
        int
    )
    after_hours_present = (after_hours_score.fillna(0.0).astype(float) > 0).astype(int)
    manual_present = (manual_score.fillna(0.0).astype(float) > 0).astype(int)
    round_present = (round_amount_signal.fillna(0.0).astype(float) > 0).astype(int)
    context_count = (
        period_end_present + after_hours_present + manual_present + round_present
    ).astype(int)

    rarity_components = pd.concat(
        [
            amount_tail.fillna(0.0).astype(float),
            account_process_rarity.fillna(0.0).astype(float),
            user_account_rarity.fillna(0.0).astype(float),
            partner_account_rarity.fillna(0.0).astype(float),
        ],
        axis=1,
    )
    rarity_tail = rarity_components.max(axis=1).astype(float)
    # Why: rarity signal 개수 (q95 / q90 threshold 각각) — context_count 와 합산하여
    #      evidence_count 산출.
    rarity_high_count_q95 = (rarity_components >= float(strong_tail_q)).sum(axis=1).astype(int)
    rarity_high_count_q90 = (rarity_components >= float(tail_q)).sum(axis=1).astype(int)
    evidence_count_q95 = (context_count + rarity_high_count_q95).astype(int)
    evidence_count_q90 = (context_count + rarity_high_count_q90).astype(int)

    strong_present = strong_burst.fillna(0.0).astype(float) >= float(strong_present_threshold)

    composite = pd.Series(0.0, index=df.index, dtype=float)
    # Why: strong-composite path — evidence_count(q95) 충분 + context 존재 + rarity 상위 5%.
    strong_composite_mask = (
        (evidence_count_q95 >= int(min_evidence_count))
        & (context_count >= 1)
        & (rarity_tail >= float(strong_tail_q))
    )
    composite = composite.where(
        ~strong_composite_mask, rarity_tail.clip(upper=float(context_boost_max))
    )
    # Why: moderate path — evidence_count(q90) 충분 + context 존재 + rarity 상위 10%.
    #      strong-composite 미충족 행에만 적용.
    moderate_mask = (
        (evidence_count_q90 >= int(min_evidence_count))
        & (context_count >= 1)
        & (rarity_tail >= float(tail_q))
        & (~strong_composite_mask)
    )
    composite = composite.where(
        ~moderate_mask, (rarity_tail * 0.7).clip(upper=float(context_boost_max))
    )
    # Why: strong 부재 행에만 composite 적용. strong path 는 별도 분기에서 처리.
    composite = composite.where(~strong_present, 0.0)

    meta = {
        "min_evidence_count": int(min_evidence_count),
        "tail_q": float(tail_q),
        "strong_tail_q": float(strong_tail_q),
        "context_boost_max": float(context_boost_max),
        "period_end_min": float(period_end_min),
        "strong_present_threshold": float(strong_present_threshold),
        "row_count": int(len(df)),
        "strong_present_row_count": int(strong_present.sum()),
        "strong_composite_row_count": int((strong_composite_mask & ~strong_present).sum()),
        "moderate_composite_row_count": int((moderate_mask & ~strong_present).sum()),
        "composite_nonzero_row_count": int((composite > 0).sum()),
        "context_count_distribution": {
            "ctx0": int((context_count == 0).sum()),
            "ctx1": int((context_count == 1).sum()),
            "ctx2": int((context_count == 2).sum()),
            "ctx3": int((context_count == 3).sum()),
            "ctx4": int((context_count == 4).sum()),
        },
        "rarity_high_count_q95_distribution": {
            "n0": int((rarity_high_count_q95 == 0).sum()),
            "n1": int((rarity_high_count_q95 == 1).sum()),
            "n2": int((rarity_high_count_q95 == 2).sum()),
            "n3_plus": int((rarity_high_count_q95 >= 3).sum()),
        },
        "rarity_tail_q90": float(rarity_tail.quantile(0.90)),
        "rarity_tail_q95": float(rarity_tail.quantile(0.95)),
        "rarity_tail_q99": float(rarity_tail.quantile(0.99)),
        "rarity_tail_max": float(rarity_tail.max()) if not rarity_tail.empty else 0.0,
        "composite_q95": float(composite.quantile(0.95)),
        "composite_q99": float(composite.quantile(0.99)),
        "composite_max": float(composite.max()) if not composite.empty else 0.0,
    }
    return CompositeResult(
        score=composite,
        context_count=context_count.astype(int),
        rarity_tail=rarity_tail,
        strong_present=strong_present,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# legacy boolean wrappers (kept for backward compatibility w/ tests/imports)
# ---------------------------------------------------------------------------


def ts01_transaction_burst(
    df: pd.DataFrame,
    window_days: int = 7,
    sigma: float = 3.0,
) -> pd.Series:
    """Legacy rolling mean + σ boolean. Detector 는 더 이상 사용하지 않는다.

    Why: 외부 직접 호출 호환만 위해 보존. statistical anomaly 경로는
         daily_burst_positive_robust_z_score + period_end_concentration_score
         + ECDF threshold 조합으로 대체됐다.
    """
    if "posting_date" not in df.columns:
        return pd.Series(False, index=df.index)

    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    valid_mask = dates.notna()
    if not valid_mask.any():
        return pd.Series(False, index=df.index)

    date_only = dates.dt.normalize()
    daily_counts = date_only[valid_mask].groupby(date_only[valid_mask]).count()
    daily_counts.index = pd.DatetimeIndex(daily_counts.index)
    daily_counts = daily_counts.resample("D").sum().fillna(0)

    if len(daily_counts) <= 1:
        return pd.Series(False, index=df.index)

    shifted = daily_counts.shift(1)
    rolling = shifted.rolling(window=window_days, min_periods=window_days)
    rolling_mean = rolling.mean()
    rolling_std = rolling.std(ddof=1).fillna(0.0)

    threshold = rolling_mean + sigma * rolling_std
    burst_dates = set(daily_counts[daily_counts > threshold].index.normalize())

    if not burst_dates:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    result.loc[valid_mask] = date_only[valid_mask].isin(burst_dates).to_numpy(dtype=bool)
    return result


def ts02_unusual_frequency(
    df: pd.DataFrame,
    group_col: str = "auxiliary_account_number",
    window_days: int = 7,
    min_count: int = 5,
) -> pd.Series:
    """Legacy 그룹 sliding window boolean. Detector 는 사용하지 않는다.

    Why: 외부 호환만 보존. statistical anomaly 경로는
         group_frequency_positive_robust_z_score + ECDF threshold 로 대체됐다.
    """
    if "posting_date" not in df.columns or group_col not in df.columns:
        return pd.Series(False, index=df.index)

    sorted_df = df.sort_values("posting_date").copy()
    sorted_df["_date"] = pd.to_datetime(sorted_df["posting_date"], errors="coerce")
    valid = sorted_df["_date"].notna()

    result = pd.Series(False, index=df.index)
    if not valid.any():
        return result

    window_ns = np.timedelta64(window_days, "D")
    for _group, grp in sorted_df[valid].groupby(group_col):
        if len(grp) < min_count:
            continue
        dates = grp["_date"].to_numpy(dtype="datetime64[ns]")
        max_in_window = 0
        left = 0
        for right in range(len(dates)):
            while dates[right] - dates[left] > window_ns:
                left += 1
            max_in_window = max(max_in_window, right - left + 1)
        if max_in_window >= min_count:
            result.loc[grp.index] = True

    return result
