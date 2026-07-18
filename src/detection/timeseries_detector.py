"""Timeseries family statistical anomaly orchestrator.

Why: rule-style boolean burst/frequency 를 robust z-score + zero-preserving ECDF
+ period-end concentration 결합으로 격상. TS01/TS02 rule_id 와 detector contract
는 유지하고 내부 score 만 continuous 화한다.

PHASE2 family aggregation 은 max(ts01_signal, ts02_signal) 을 사용하며,
ts01_signal = max(daily_burst, period_end_concentration), ts02_signal = group_frequency.
ECDF threshold 단일 기준으로 TS01/TS02 boolean 을 재계산해 분포 변별력을 확보한다.

Phase 1 rule hit / flagged_rules / DataSynth 라벨을 입력으로 사용하지 않는다.

S6 Phase B (2026-05-28): timeseries detector 가 row 단위 score / details /
rule_flags / 기존 metadata 를 변경하지 않으면서 새 metadata key
``timeseries_window_artifact`` 를 부착한다 (invariant #62). artifact 는 TS01/TS02
의 (rule_id, subject, window) 단위 sanitized projection 으로 row_indices /
row_positions 양쪽을 보유 — MultiIndex 안전 (invariant #63).

도메인 정당화:
    - TS01 daily burst → PCAOB AS 2401 §B7 (unusual posting timing /
      period-end clustering — burst 는 의도성 증거 보강).
    - TS02 unusual frequency → ISA 240 §32 (Management override via timing
      manipulation — 짧은 기간 vendor/account 활동 집중).

truth recall 직접 조정 압력은 사용하지 않는다 (D044 — feedback_phase1_truth_recall_guard).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.detection.base import BaseDetector, DetectionResult, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.timeseries_rules import (
    CompositeResult,
    SubSignalResult,
    account_process_rarity_score,
    after_hours_or_weekend_score,
    composite_temporal_anomaly,
    daily_burst_positive_robust_z_score,
    group_frequency_positive_robust_z_score,
    manual_or_adjustment_score,
    partner_account_rarity_score,
    period_end_concentration_score,
    round_amount_score,
    row_amount_tail_score,
    user_account_rarity_score,
    zero_preserving_ecdf,
)

_REQUIRED_COLUMNS = ["posting_date"]

# subject 컬럼 우선순위 — gl_account 우선, 없으면 business_process 로 fallback.
_SUBJECT_COLUMN_CANDIDATES: tuple[str, ...] = ("gl_account", "business_process")
# TS02 group spike window — group_frequency_positive_robust_z 의 trailing window 일수.
_TS02_DEFAULT_WINDOW_DAYS = 7
# evidence tier 분기 — q95 strong / q80 moderate / 그 외 weak.
_STRONG_QUANTILE = 0.95
_MODERATE_QUANTILE = 0.80
# sub_signal_high gate — strong tier AND score/max ≥ 0.6 (Δ13 단순화 spec).
_SUB_SIGNAL_HIGH_RATIO = 0.6
# artifact entry cap — 운영 가시성. 빌더 / store 가 별도 cap 하지 않음.
_WINDOW_ARTIFACT_CAP = 500
# Baseline context only. These values do not change detector flags or ranking.
_BASELINE_WINDOW_DAYS = 28
_BASELINE_MIN_OBSERVATIONS = 5


def _ts_json_safe(value: Any) -> Any:
    """duplicate_pair_features._json_safe / IC matcher _ic_json_safe 패턴 동일.

    index label sanitization — JSON 직렬화 가능한 primitive 로 강제. tuple /
    Timestamp / numpy scalar / 기타 → str 평탄화.
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return str(value)


@dataclass
class TimeseriesWindowArtifact:
    """Timeseries detector 가 산출하는 sanitized window-level artifact (S6 Phase B).

    duplicate ``pair_artifact`` / IC ``ic_pair_artifact`` 패턴 정합. JSON 직렬화
    가능한 dict / list 만 보유 — raw 적요 / partner 풀텍스트는 노출하지 않으며,
    case identity (sub_rule + subject + window_start) 와 evidence_tier /
    sub_signal_high 만 builder 가 사용한다.
    """

    schema_version: int = 1
    windows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "windows": list(self.windows),
            "coverage": dict(self.coverage),
        }


def _empty_timeseries_window_artifact() -> dict[str, Any]:
    """_skipped_result 경로용 — 빈 artifact dict (builder graceful fallback 호환)."""
    return TimeseriesWindowArtifact().to_dict()


def _resolve_subject_column(df: pd.DataFrame) -> str | None:
    """subject 컬럼 선택 — gl_account 우선, business_process 로 fallback."""
    for col in _SUBJECT_COLUMN_CANDIDATES:
        if col in df.columns and df[col].notna().any():
            return col
    return None


def _assign_evidence_tier(
    score: float,
    *,
    score_q95: float,
    score_q80: float,
) -> str:
    """row score → strong / moderate / weak tier.

    q95+ strong, q80~q95 moderate, 그 외 weak. precision/recall 튜닝 압력
    사용 금지 (D044). 빈 분포 (q95 == 0) 에서는 양수 score → strong 으로 보수적.
    """
    if score_q95 <= 0.0:
        return "strong" if score > 0.0 else "weak"
    if score >= score_q95:
        return "strong"
    if score >= max(score_q80, 0.0):
        return "moderate"
    return "weak"


def _is_period_end_context(day: pd.Timestamp, *, proximity_days: int) -> bool:
    """월말 proximity context flag. Ranking / threshold 입력으로 쓰지 않는다."""
    if pd.isna(day):
        return False
    month_end = day + pd.offsets.MonthEnd(0)
    return 0 <= int((month_end.normalize() - day.normalize()).days) <= max(proximity_days, 0)


def _normalized_deviation(observed: int, baseline_values: list[int]) -> float | None:
    """Median/MAD 기반 normalized deviation. baseline 부재 시 None."""
    if len(baseline_values) < _BASELINE_MIN_OBSERVATIONS:
        return None
    values = np.asarray(baseline_values, dtype=float)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad > 0.0:
        return float((float(observed) - median) / (1.4826 * mad))
    # Degenerate but valid baseline: use relative deviation from the median.
    return float((float(observed) - median) / max(abs(median), 1.0))


def _build_daily_count_lookup(
    df: pd.DataFrame,
    *,
    subject_col: str,
    posting_date: pd.Series,
) -> tuple[dict[str, dict[pd.Timestamp, int]], dict[str, int]]:
    work = pd.DataFrame(
        {
            "subject": df[subject_col].astype(str),
            "posting_date_norm": posting_date.dt.normalize(),
        }
    ).dropna(subset=["subject", "posting_date_norm"])
    if work.empty:
        return {}, {}
    grouped = work.groupby(["subject", "posting_date_norm"], sort=False).size()
    daily_counts: dict[str, dict[pd.Timestamp, int]] = {}
    for (subject, day), count in grouped.items():
        daily_counts.setdefault(str(subject), {})[pd.Timestamp(day).normalize()] = int(count)
    subject_totals = work.groupby("subject", sort=False).size().astype(int).to_dict()
    return daily_counts, {str(k): int(v) for k, v in subject_totals.items()}


def _subject_activity_ranks(subject_totals: dict[str, int]) -> dict[str, int]:
    ordered = sorted(subject_totals.items(), key=lambda item: (-item[1], item[0]))
    return {subject: rank for rank, (subject, _count) in enumerate(ordered, start=1)}


def _baseline_payload(
    *,
    rule_id: str,
    subject: str,
    day: pd.Timestamp,
    observed_count: int,
    window_offset: pd.Timedelta,
    daily_counts: dict[str, dict[pd.Timestamp, int]],
    subject_totals: dict[str, int],
    subject_ranks: dict[str, int],
    period_end_proximity_days: int,
) -> dict[str, Any]:
    """Subject trailing baseline for artifact context only.

    Uses prior active daily/window observations. If the subject lacks enough
    history, expected_count stays None rather than falling back to 0.0.
    """
    subject_key = str(subject)
    subject_daily_counts = daily_counts.get(subject_key, {})
    baseline_values: list[int] = []
    for offset_days in range(1, _BASELINE_WINDOW_DAYS + 1):
        prior_end = (day - pd.Timedelta(days=offset_days)).normalize()
        if rule_id == "TS01":
            count = subject_daily_counts.get(prior_end, 0)
        else:
            prior_start = prior_end - window_offset
            count = sum(
                value
                for candidate_day, value in subject_daily_counts.items()
                if prior_start <= candidate_day <= prior_end
            )
        if count > 0:
            baseline_values.append(int(count))

    expected_count: float | None = None
    robust_z: float | None = None
    if len(baseline_values) >= _BASELINE_MIN_OBSERVATIONS:
        expected_count = float(np.median(np.asarray(baseline_values, dtype=float)))
        robust_z = _normalized_deviation(observed_count, baseline_values)

    method = (
        "subject_trailing_active_day_median"
        if rule_id == "TS01"
        else "subject_trailing_window_median"
    )
    total_subjects = max(len(subject_totals), 1)
    rank = subject_ranks.get(subject_key)
    period_end_day_offset = None
    if not pd.isna(day):
        month_end = day + pd.offsets.MonthEnd(0)
        period_end_day_offset = int((month_end.normalize() - day.normalize()).days)

    subject_period_days = 0
    subject_non_period_values: list[int] = []
    subject_period_values: list[int] = []
    for candidate_day, value in subject_daily_counts.items():
        if candidate_day >= day.normalize():
            continue
        if _is_period_end_context(candidate_day, proximity_days=period_end_proximity_days):
            subject_period_days += 1
            subject_period_values.append(int(value))
        else:
            subject_non_period_values.append(int(value))

    historical_total = len(subject_period_values) + len(subject_non_period_values)
    subject_period_end_historical_ratio = (
        subject_period_days / historical_total if historical_total else None
    )
    subject_non_period_end_baseline_count = (
        float(np.median(np.asarray(subject_non_period_values, dtype=float)))
        if len(subject_non_period_values) >= _BASELINE_MIN_OBSERVATIONS
        else None
    )
    period_end_expected_count = (
        float(np.median(np.asarray(subject_period_values, dtype=float)))
        if len(subject_period_values) >= _BASELINE_MIN_OBSERVATIONS
        else None
    )
    period_end_lift = (
        float(observed_count) / period_end_expected_count
        if period_end_expected_count is not None and period_end_expected_count > 0
        else None
    )

    return {
        "expected_count": expected_count,
        "baseline_method": method if expected_count is not None else None,
        "baseline_window_days": _BASELINE_WINDOW_DAYS,
        "baseline_observation_count": len(baseline_values),
        "robust_z": robust_z,
        "period_end_context": _is_period_end_context(
            day,
            proximity_days=period_end_proximity_days,
        ),
        "period_end_day_offset": period_end_day_offset,
        "subject_period_end_historical_ratio": subject_period_end_historical_ratio,
        "subject_non_period_end_baseline_count": subject_non_period_end_baseline_count,
        "period_end_expected_count": period_end_expected_count,
        "period_end_lift": period_end_lift,
        "subject_activity_rank": rank,
        "subject_frequency_context": {
            "subject_total_count": subject_totals.get(subject_key, 0),
            "subject_rank_percentile": (rank / total_subjects) if rank is not None else None,
        },
    }


def build_timeseries_window_artifact(
    df: pd.DataFrame,
    *,
    ts01_signal: pd.Series,
    ts01_flag: pd.Series,
    ts02_signal: pd.Series,
    ts02_flag: pd.Series,
    settings: Any,
    amount_tail_context: pd.Series | None = None,
    manual_or_adjustment_context: pd.Series | None = None,
    after_hours_or_weekend_context: pd.Series | None = None,
    round_amount_context: pd.Series | None = None,
    account_process_rarity_context: pd.Series | None = None,
    user_account_rarity_context: pd.Series | None = None,
    partner_account_rarity_context: pd.Series | None = None,
) -> TimeseriesWindowArtifact:
    """TS01/TS02 row score → (rule_id, subject, window) 단위 sanitized artifact.

    Args:
        df: detection 대상 GL DataFrame. ``posting_date`` 필수. ``gl_account`` /
            ``business_process`` 중 하나라도 있어야 subject 추출 가능 — 없으면
            artifact 는 빈 windows 로 graceful fallback.
        ts01_signal: TS01 row score Series (df.index 정합).
        ts01_flag: TS01 boolean flag — True 인 row 만 artifact entry 후보.
        ts02_signal: TS02 row score Series.
        ts02_flag: TS02 boolean flag.
        settings: AuditSettings — ``ts_group_window_days`` 로 TS02 window 폭 결정.

    Returns:
        TimeseriesWindowArtifact — windows + coverage. TS01 은 single-day window
        (start == end), TS02 는 trailing window (start = end - window_days+1).
    """
    artifact = TimeseriesWindowArtifact()
    subject_col = _resolve_subject_column(df)
    if subject_col is None or "posting_date" not in df.columns:
        artifact.coverage = {"TS01": 0, "TS02": 0}
        return artifact

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    daily_counts, subject_totals = _build_daily_count_lookup(
        df,
        subject_col=subject_col,
        posting_date=posting_date,
    )
    subject_ranks = _subject_activity_ranks(subject_totals)
    # quantile 산출 — evidence_tier 분기용. 양수 score 만 분포에 포함.
    ts01_positive = ts01_signal[ts01_signal > 0].astype(float)
    ts02_positive = ts02_signal[ts02_signal > 0].astype(float)
    ts01_q95 = float(ts01_positive.quantile(_STRONG_QUANTILE)) if not ts01_positive.empty else 0.0
    ts01_q80 = float(ts01_positive.quantile(_MODERATE_QUANTILE)) if not ts01_positive.empty else 0.0
    ts01_max = float(ts01_positive.max()) if not ts01_positive.empty else 0.0
    ts02_q95 = float(ts02_positive.quantile(_STRONG_QUANTILE)) if not ts02_positive.empty else 0.0
    ts02_q80 = float(ts02_positive.quantile(_MODERATE_QUANTILE)) if not ts02_positive.empty else 0.0
    ts02_max = float(ts02_positive.max()) if not ts02_positive.empty else 0.0

    window_days = max(int(getattr(settings, "ts_group_window_days", _TS02_DEFAULT_WINDOW_DAYS)), 1)
    ts02_window_offset = pd.Timedelta(days=window_days - 1)
    period_end_proximity_days = int(getattr(settings, "ts_period_end_window_days", 3))

    ts01_count = 0
    ts02_count = 0

    # TS01 — single-day burst window (start == end)
    ts01_count = _append_windows(
        artifact,
        df=df,
        subject_col=subject_col,
        posting_date=posting_date,
        rule_id="TS01",
        signal=ts01_signal,
        flag=ts01_flag,
        score_q95=ts01_q95,
        score_q80=ts01_q80,
        score_max=ts01_max,
        window_offset=pd.Timedelta(days=0),
        daily_counts=daily_counts,
        subject_totals=subject_totals,
        subject_ranks=subject_ranks,
        period_end_proximity_days=period_end_proximity_days,
        amount_tail_context=amount_tail_context,
        manual_or_adjustment_context=manual_or_adjustment_context,
        after_hours_or_weekend_context=after_hours_or_weekend_context,
        round_amount_context=round_amount_context,
        account_process_rarity_context=account_process_rarity_context,
        user_account_rarity_context=user_account_rarity_context,
        partner_account_rarity_context=partner_account_rarity_context,
    )

    # TS02 — trailing window (start = end - window_days+1, end = posting_date)
    ts02_count = _append_windows(
        artifact,
        df=df,
        subject_col=subject_col,
        posting_date=posting_date,
        rule_id="TS02",
        signal=ts02_signal,
        flag=ts02_flag,
        score_q95=ts02_q95,
        score_q80=ts02_q80,
        score_max=ts02_max,
        window_offset=ts02_window_offset,
        daily_counts=daily_counts,
        subject_totals=subject_totals,
        subject_ranks=subject_ranks,
        period_end_proximity_days=period_end_proximity_days,
        amount_tail_context=amount_tail_context,
        manual_or_adjustment_context=manual_or_adjustment_context,
        after_hours_or_weekend_context=after_hours_or_weekend_context,
        round_amount_context=round_amount_context,
        account_process_rarity_context=account_process_rarity_context,
        user_account_rarity_context=user_account_rarity_context,
        partner_account_rarity_context=partner_account_rarity_context,
    )

    artifact.coverage = {"TS01": ts01_count, "TS02": ts02_count}
    return artifact


def _append_windows(
    artifact: TimeseriesWindowArtifact,
    *,
    df: pd.DataFrame,
    subject_col: str,
    posting_date: pd.Series,
    rule_id: str,
    signal: pd.Series,
    flag: pd.Series,
    score_q95: float,
    score_q80: float,
    score_max: float,
    window_offset: pd.Timedelta,
    daily_counts: dict[str, dict[pd.Timestamp, int]],
    subject_totals: dict[str, int],
    subject_ranks: dict[str, int],
    period_end_proximity_days: int,
    amount_tail_context: pd.Series | None,
    manual_or_adjustment_context: pd.Series | None,
    after_hours_or_weekend_context: pd.Series | None,
    round_amount_context: pd.Series | None,
    account_process_rarity_context: pd.Series | None,
    user_account_rarity_context: pd.Series | None,
    partner_account_rarity_context: pd.Series | None,
) -> int:
    """flag True 인 row 들을 (subject, day) 그룹핑해 artifact.windows 에 추가.

    한 (rule_id, subject, day) 가 여러 row 에 등장하면 dedup 되고 row_indices /
    row_positions 가 그 row 들을 모두 보유.

    Returns:
        artifact 에 추가된 window entry 개수.
    """
    flag_bool = flag.astype(bool, copy=False)
    if not flag_bool.any():
        return 0

    # row position 부여 — df.index.get_loc 회피, 단일 패스로 처리.
    work = pd.DataFrame(
        {
            "subject": df[subject_col].astype(object),
            "posting_date_norm": posting_date.dt.normalize()
            if not posting_date.empty
            else posting_date,
            "score": signal.astype(float),
            "flag": flag_bool,
        },
        index=df.index,
    )
    work["row_position"] = np.arange(len(work), dtype=int)
    # Why: 연산 우선순위 — & 가 > 보다 약하므로 score > 0 를 먼저 평가하도록 괄호.
    candidates = work[work["flag"] & (work["score"] > 0)]
    # NaN subject / posting_date_norm 은 grouping 불가 → skip
    candidates = candidates.dropna(subset=["subject", "posting_date_norm"])
    if candidates.empty:
        return 0

    added = 0
    for (subject, day_ts), grp in candidates.groupby(["subject", "posting_date_norm"], sort=False):
        if added >= _WINDOW_ARTIFACT_CAP:
            break
        if pd.isna(day_ts):
            continue
        day = pd.Timestamp(day_ts)
        window_start = (day - window_offset).date().isoformat()
        window_end = day.date().isoformat()
        max_score = float(grp["score"].max())
        tier = _assign_evidence_tier(max_score, score_q95=score_q95, score_q80=score_q80)
        # Δ13 단순화 sub_signal_high — strong tier AND score/max ≥ 0.6
        sub_signal_high = bool(
            tier == "strong" and score_max > 0 and (max_score / score_max) >= _SUB_SIGNAL_HIGH_RATIO
        )
        labels = [_ts_json_safe(label) for label in grp.index.tolist()]
        positions = [int(p) for p in grp["row_position"].tolist()]
        daily_count = int(len(grp))
        subject_daily_counts = daily_counts.get(str(subject), {})
        window_count = sum(
            value
            for candidate_day, value in subject_daily_counts.items()
            if pd.Timestamp(window_start) <= candidate_day <= pd.Timestamp(window_end)
        )
        observed_count = daily_count if rule_id == "TS01" else int(window_count)
        baseline = _baseline_payload(
            rule_id=rule_id,
            subject=str(subject),
            day=day,
            observed_count=observed_count,
            window_offset=window_offset,
            daily_counts=daily_counts,
            subject_totals=subject_totals,
            subject_ranks=subject_ranks,
            period_end_proximity_days=period_end_proximity_days,
        )
        context = _window_context_payload(
            row_labels=grp.index.tolist(),
            amount_tail_context=amount_tail_context,
            manual_or_adjustment_context=manual_or_adjustment_context,
            after_hours_or_weekend_context=after_hours_or_weekend_context,
            round_amount_context=round_amount_context,
            account_process_rarity_context=account_process_rarity_context,
            user_account_rarity_context=user_account_rarity_context,
            partner_account_rarity_context=partner_account_rarity_context,
        )
        entry = {
            "rule_id": rule_id,
            "subject": str(subject),
            "window_start": window_start,
            "window_end": window_end,
            "row_indices": labels,
            "row_positions": positions,
            "daily_count": daily_count,
            "window_count": int(window_count),
            "z_score": max_score,
            "sub_signal_high": sub_signal_high,
            "evidence_tier": tier,
            **baseline,
            **context,
        }
        artifact.windows.append(entry)
        added += 1
    return added


def _series_max_for_labels(series: pd.Series | None, labels: list[Any]) -> float:
    if series is None or not labels:
        return 0.0
    values = series.reindex(labels).fillna(0.0).astype(float)
    return float(values.max()) if not values.empty else 0.0


def _window_context_payload(
    *,
    row_labels: list[Any],
    amount_tail_context: pd.Series | None,
    manual_or_adjustment_context: pd.Series | None,
    after_hours_or_weekend_context: pd.Series | None,
    round_amount_context: pd.Series | None,
    account_process_rarity_context: pd.Series | None,
    user_account_rarity_context: pd.Series | None,
    partner_account_rarity_context: pd.Series | None,
) -> dict[str, Any]:
    amount_tail = _series_max_for_labels(amount_tail_context, row_labels)
    manual = _series_max_for_labels(manual_or_adjustment_context, row_labels)
    after_hours = _series_max_for_labels(after_hours_or_weekend_context, row_labels)
    round_amount = _series_max_for_labels(round_amount_context, row_labels)
    rarity_values = [
        _series_max_for_labels(account_process_rarity_context, row_labels),
        _series_max_for_labels(user_account_rarity_context, row_labels),
        _series_max_for_labels(partner_account_rarity_context, row_labels),
    ]
    rarity_context_count = sum(1 for value in rarity_values if value > 0.0)
    context_evidence_count = sum(
        [
            amount_tail > 0.0,
            manual > 0.0,
            after_hours > 0.0,
            round_amount > 0.0,
            rarity_context_count > 0,
        ]
    )
    return {
        "amount_tail_context": amount_tail,
        "manual_or_adjustment_context": manual,
        "after_hours_or_weekend_context": after_hours,
        "round_amount_context": round_amount,
        "rarity_context_count": int(rarity_context_count),
        "context_evidence_count": int(context_evidence_count),
    }


class TimeseriesDetector(BaseDetector):
    """Statistical anomaly timeseries family detector.

    Why: posting_date 기반 일별 robust z-score + 그룹별 단기 빈도 robust z-score
         + 월말/분기말/연말 concentration 을 zero-preserving ECDF 로 정규화하고,
         TS01/TS02 boolean 은 ECDF percentile 임계로 재계산한다.
    """

    @property
    def track_name(self) -> str:
        return "timeseries"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        start = time.perf_counter()
        warnings: list[str] = []

        missing = validate_input(df, _REQUIRED_COLUMNS)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._skipped_result(df, warnings, time.perf_counter() - start)

        sub_signals = self._compute_sub_signals(df)
        elapsed = time.perf_counter() - start
        active_sub_signals = [s for s in sub_signals if s.active]
        if not active_sub_signals:
            warnings.append("statistical sub-signal 미활성: 모두 graceful skip")
            return self._skipped_result(
                df,
                warnings,
                elapsed,
                sub_signals=sub_signals,
            )

        return self._build_result(df, sub_signals, warnings, elapsed)

    # ------------------------------------------------------------------ helpers

    def _compute_sub_signals(self, df: pd.DataFrame) -> list[SubSignalResult]:
        s = self._settings
        rarity_min_pop = int(getattr(s, "ts_rarity_min_pair_population", 50))
        round_max_sig = int(getattr(s, "round_max_significant_digits", 2))
        round_min_digits = int(getattr(s, "round_min_digits", 3))
        return [
            daily_burst_positive_robust_z_score(
                df,
                window_days=int(getattr(s, "ts_burst_window_days", 14)),
            ),
            group_frequency_positive_robust_z_score(
                df,
                window_days=int(getattr(s, "ts_group_window_days", 7)),
                min_support=int(getattr(s, "ts_group_min_support", 10)),
                min_active_days=int(getattr(s, "ts_group_min_active_days", 3)),
                min_excess_count=int(getattr(s, "ts_group_min_excess_count", 3)),
                spike_ratio_min=float(getattr(s, "ts_group_spike_ratio_min", 2.0)),
                cold_start_score_cap=float(getattr(s, "ts_group_cold_start_score_cap", 0.30)),
            ),
            period_end_concentration_score(
                df,
                proximity_window_days=int(getattr(s, "ts_period_end_window_days", 3)),
            ),
            # Why: rarity axis sub-signal. amount_tail 은 단독으로 row_score 에
            # 기여 금지 — composite gate (context_count >= 2 + rarity >= q95) 통과 시만.
            row_amount_tail_score(df),
            # Why: context axis (boolean 0/0.5) — composite gate 의 context_count 입력 전용.
            after_hours_or_weekend_score(df),
            manual_or_adjustment_score(df),
            round_amount_score(
                df,
                max_significant_digits=round_max_sig,
                min_digits=round_min_digits,
            ),
            # Why: rarity axis 신규 3축 — composite gate 의 rarity_tail 입력 전용.
            account_process_rarity_score(df, min_pair_population=rarity_min_pop),
            user_account_rarity_score(df, min_pair_population=rarity_min_pop),
            partner_account_rarity_score(df, min_pair_population=rarity_min_pop),
        ]

    def _build_result(
        self,
        df: pd.DataFrame,
        sub_signals: list[SubSignalResult],
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        s = self._settings
        burst_high = float(getattr(s, "ts_burst_high_pctile", 0.95))
        freq_high = float(getattr(s, "ts_freq_high_pctile", 0.95))
        period_end_high = float(getattr(s, "ts_period_end_high", 0.80))
        context_cap = float(getattr(s, "ts_period_end_context_cap", 0.30))
        context_threshold = float(getattr(s, "ts_period_end_context_threshold", 0.50))
        strong_present_threshold = float(getattr(s, "ts_strong_present_threshold", 0.30))
        composite_min_evidence = int(getattr(s, "ts_composite_min_evidence_count", 3))
        composite_tail_q = float(getattr(s, "ts_composite_tail_q", 0.90))
        composite_strong_tail_q = float(getattr(s, "ts_composite_strong_tail_q", 0.95))
        composite_boost_max = float(getattr(s, "ts_composite_context_boost_max", 0.80))
        composite_period_end_min = float(getattr(s, "ts_composite_period_end_min", 0.05))

        signals_by_name = {sub.name: sub for sub in sub_signals}
        s1 = signals_by_name.get("daily_burst_positive_robust_z")
        s2 = signals_by_name.get("group_frequency_positive_robust_z")
        s3 = signals_by_name.get("period_end_concentration")
        amount_tail = signals_by_name.get("row_amount_tail")
        after_hours = signals_by_name.get("after_hours_or_weekend")
        manual = signals_by_name.get("manual_or_adjustment")
        round_amt = signals_by_name.get("round_amount")
        acc_proc = signals_by_name.get("account_process_rarity")
        user_acc = signals_by_name.get("user_account_rarity")
        partner_acc = signals_by_name.get("partner_account_rarity")

        def _series_or_zero(sub: SubSignalResult | None) -> pd.Series:
            if sub is not None and sub.active:
                return sub.score.astype(float)
            return pd.Series(0.0, index=df.index, dtype=float)

        # Why: positive z-score를 batch ECDF 로 정규화 → 0 행은 0 보존.
        s1_ecdf = (
            zero_preserving_ecdf(s1.score) if s1 and s1.active else pd.Series(0.0, index=df.index)
        )
        # Why: s2 는 group_spike-only (broad activity 제거). ECDF 정규화 후 strong axis.
        s2_ecdf = (
            zero_preserving_ecdf(s2.score) if s2 and s2.active else pd.Series(0.0, index=df.index)
        )
        # Why: period_end 는 0~1 도메인 raw score. 단독으로 strong anomaly 로 쓰지 않음.
        s3_raw = s3.score if s3 and s3.active else pd.Series(0.0, index=df.index)
        amount_tail_score = _series_or_zero(amount_tail)
        after_hours_score = _series_or_zero(after_hours)
        manual_score = _series_or_zero(manual)
        round_amount_signal = _series_or_zero(round_amt)
        acc_proc_score = _series_or_zero(acc_proc)
        user_acc_score = _series_or_zero(user_acc)
        partner_acc_score = _series_or_zero(partner_acc)

        # Why: strong axis = daily_burst + group_spike (spike-only). amount_tail 단독은 strong 아님.
        strong_score = pd.concat([s1_ecdf, s2_ecdf], axis=1).max(axis=1).astype(float)
        strong_present = strong_score >= strong_present_threshold

        # Why: period_end gating context_present 판정 — strong (s1/s2) + amount_tail 사용.
        # context boost 진입 자격 (strong path 의 context 보강).
        context_present_for_period_end = (
            pd.concat([s1_ecdf, s2_ecdf, amount_tail_score.astype(float)], axis=1)
            .max(axis=1)
            .astype(float)
            >= context_threshold
        )
        gated_period_end = s3_raw.where(
            context_present_for_period_end, s3_raw.clip(upper=context_cap)
        ).astype(float)
        gated_context = gated_period_end.where(
            strong_present, gated_period_end.clip(upper=context_cap)
        )

        # Why: composite temporal anomaly path — strong 부재 행에 대해 context_count + rarity_tail
        # 결합 조건 충족 시 cap 초과 허용. amount_tail/rarity/context 단독은 cap 이하.
        composite: CompositeResult = composite_temporal_anomaly(
            df,
            strong_burst=strong_score,
            period_end_raw=s3_raw,
            after_hours_score=after_hours_score,
            manual_score=manual_score,
            round_amount_signal=round_amount_signal,
            amount_tail=amount_tail_score,
            account_process_rarity=acc_proc_score,
            user_account_rarity=user_acc_score,
            partner_account_rarity=partner_acc_score,
            period_end_min=composite_period_end_min,
            min_evidence_count=composite_min_evidence,
            tail_q=composite_tail_q,
            strong_tail_q=composite_strong_tail_q,
            context_boost_max=composite_boost_max,
            strong_present_threshold=strong_present_threshold,
        )
        composite_score = composite.score.astype(float)

        # Why: TS01 details = daily_burst + context-gated period_end + composite (composite path 도
        # period_end 결합이 포함됐을 때 TS01 라벨에 묶임). TS02 details = group_spike only.
        ts01_signal = (
            pd.concat([s1_ecdf, gated_period_end, composite_score], axis=1)
            .max(axis=1)
            .astype(float)
        )
        ts02_signal = s2_ecdf.astype(float)

        ts01_flag = ts01_signal >= burst_high
        if s3 and s3.active:
            ts01_flag = ts01_flag | (gated_period_end >= period_end_high)
        ts02_flag = ts02_signal >= freq_high

        ts01_severity_norm = SEVERITY_MAP["TS01"] / 5.0
        ts02_severity_norm = SEVERITY_MAP["TS02"] / 5.0

        details = pd.DataFrame(index=df.index)
        details["TS01"] = ts01_signal.where(ts01_flag, 0.0) * ts01_severity_norm
        details["TS02"] = ts02_signal.where(ts02_flag, 0.0) * ts02_severity_norm

        # Why: row_score = max(strong axis, composite, gated_context).
        # - strong axis (daily_burst/group_spike) 단독: 가능
        # - composite (context_count + rarity tail): cap composite_boost_max(0.80) 까지
        # - context-only (gated_period_end + strong 부재): cap context_cap(0.30)
        # - amount_tail/rarity/context 단독: 모두 위 경로 차단 → row_score ≤ cap
        scores = (
            pd.concat([strong_score, composite_score, gated_context], axis=1)
            .max(axis=1)
            .astype(float)
            .reindex(df.index)
            .fillna(0.0)
        )
        flagged_mask = ts01_flag | ts02_flag
        flagged_indices = list(df.index[flagged_mask])

        rule_flags = [
            self._create_rule_flag(
                rule_id="TS01",
                flagged_count=int(ts01_flag.sum()),
                total_count=len(df),
            ),
            self._create_rule_flag(
                rule_id="TS02",
                flagged_count=int(ts02_flag.sum()),
                total_count=len(df),
            ),
        ]

        period_end_only_capped_rows = int(((~context_present_for_period_end) & (s3_raw > 0)).sum())
        period_end_with_context_rows = int((context_present_for_period_end & (s3_raw > 0)).sum())
        context_capped_by_strong_absent_rows = int(
            ((~strong_present) & (gated_period_end > 0)).sum()
        )
        context_boost_rows = int((strong_present & (gated_period_end > 0)).sum())

        metadata = {
            "elapsed": elapsed,
            "skipped_rules": [],
            "sub_signals": [self._serialize_sub_signal(sub) for sub in sub_signals],
            "score_distribution": {
                "ts01_signal_q95": float(ts01_signal.quantile(0.95)),
                "ts01_signal_q99": float(ts01_signal.quantile(0.99)),
                "ts02_signal_q95": float(ts02_signal.quantile(0.95)),
                "ts02_signal_q99": float(ts02_signal.quantile(0.99)),
                "strong_score_q95": float(strong_score.quantile(0.95)),
                "strong_score_q99": float(strong_score.quantile(0.99)),
                "composite_score_q95": float(composite_score.quantile(0.95)),
                "composite_score_q99": float(composite_score.quantile(0.99)),
                "composite_score_max": float(composite_score.max())
                if not composite_score.empty
                else 0.0,
                "row_score_nonzero_rate": float((scores > 0).mean()) if len(scores) else 0.0,
            },
            "evidence_role_gating": {
                "strong_present_threshold": strong_present_threshold,
                "context_cap": context_cap,
                "composite_boost_max": composite_boost_max,
                "composite_min_evidence_count": composite_min_evidence,
                "composite_tail_q": composite_tail_q,
                "composite_strong_tail_q": composite_strong_tail_q,
                "strong_axes": [
                    "daily_burst_positive_robust_z_ecdf",
                    "group_frequency_positive_robust_z_ecdf (spike-only)",
                ],
                "context_axes": [
                    "period_end_concentration (context-gated)",
                    "after_hours_or_weekend",
                    "manual_or_adjustment",
                    "round_amount",
                ],
                "rarity_axes": [
                    "row_amount_tail",
                    "account_process_rarity",
                    "user_account_rarity",
                    "partner_account_rarity",
                ],
                "strong_present_row_count": int(strong_present.sum()),
                "context_boost_rows": context_boost_rows,
                "context_capped_by_strong_absent_rows": context_capped_by_strong_absent_rows,
            },
            "composite_temporal_gating": composite.meta,
            "period_end_gating": {
                "context_threshold": context_threshold,
                "context_cap": context_cap,
                "context_axes": [
                    "daily_burst_positive_robust_z_ecdf",
                    "group_frequency_positive_robust_z_ecdf (spike-only)",
                    "row_amount_tail",
                ],
                "amount_tail_active": bool(amount_tail.active) if amount_tail else False,
                "period_end_only_capped_rows": period_end_only_capped_rows,
                "period_end_with_context_rows": period_end_with_context_rows,
                "context_present_row_count": int(context_present_for_period_end.sum()),
                "gated_period_end_q95": float(gated_period_end.quantile(0.95)),
                "gated_period_end_q99": float(gated_period_end.quantile(0.99)),
                "gated_period_end_max": float(gated_period_end.max()),
                "raw_period_end_q95": float(s3_raw.quantile(0.95)),
                "raw_period_end_max": float(s3_raw.max()),
            },
            "explanation_summary": (
                "Statistical anomaly: 3-axis 결합식. strong = daily_burst + group_spike, "
                "context = period_end + after_hours + manual + round, rarity = amount_tail + "
                "account/user/partner-account rarity. row_score = max(strong, composite, "
                "gated_context). composite = (context_count + rarity tail) 결합 충족 시만 "
                f"cap {composite_boost_max:.2f} 까지 boost. 단독 context/rarity 는 cap "
                f"{context_cap:.2f} 이하."
            ),
            "why_it_flagged": (
                "TS01 = daily burst robust z 또는 composite temporal anomaly (context 결합 + "
                f"rarity tail) 가 분포 상위 {burst_high:.0%}를 초과한 행. "
                f"TS02 = vendor/account 그룹의 단기 빈도 robust z 가 분포 상위 "
                f"{freq_high:.0%}를 초과한 행 (group_spike-only). amount_tail/period_end/"
                f"after_hours/manual/round 단독 거래는 row score ≤ {context_cap:.2f} 로 cap."
            ),
        }

        # S6 Phase B — sanitized window artifact (invariant #62: 기존 metadata 회귀 0건)
        window_artifact = build_timeseries_window_artifact(
            df,
            ts01_signal=ts01_signal,
            ts01_flag=ts01_flag,
            ts02_signal=ts02_signal,
            ts02_flag=ts02_flag,
            settings=s,
            amount_tail_context=amount_tail_score,
            manual_or_adjustment_context=manual_score,
            after_hours_or_weekend_context=after_hours_score,
            round_amount_context=round_amount_signal,
            account_process_rarity_context=acc_proc_score,
            user_account_rarity_context=user_acc_score,
            partner_account_rarity_context=partner_acc_score,
        )
        metadata["timeseries_window_artifact"] = window_artifact.to_dict()

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=metadata,
            warnings=warnings,
        )

    def _skipped_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
        sub_signals: list[SubSignalResult] | None = None,
    ) -> DetectionResult:
        """필수 컬럼 누락 / 모든 sub-signal 비활성 시 빈 결과."""
        idx = df.index if not df.empty else pd.RangeIndex(0)
        metadata = {
            "elapsed": elapsed,
            "skipped_rules": ["TS01", "TS02"],
            "sub_signals": ([self._serialize_sub_signal(sub) for sub in (sub_signals or [])]),
            "run_status": "skipped",
            "skip_reason": "no_active_sub_signals",
            # S6 Phase B — builder graceful fallback 호환 위해 빈 artifact 부착.
            "timeseries_window_artifact": _empty_timeseries_window_artifact(),
        }
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=idx),
            rule_flags=[],
            details=pd.DataFrame(index=idx),
            metadata=metadata,
            warnings=warnings,
        )

    @staticmethod
    def _serialize_sub_signal(sub: SubSignalResult) -> dict[str, object]:
        """SubSignalResult → JSON-serializable dict (DataFrame/Series 미포함)."""
        ecdf_summary: dict[str, float] = {}
        if sub.active and not sub.score.empty:
            positive = sub.score[sub.score > 0]
            ecdf_summary = {
                "nonzero_row_count": int(len(positive)),
                "score_q95": float(sub.score.quantile(0.95)),
                "score_q99": float(sub.score.quantile(0.99)),
                "score_max": float(sub.score.max()),
            }
        return {
            "name": sub.name,
            "active": bool(sub.active),
            "meta": dict(sub.meta),
            "ecdf_summary": ecdf_summary,
        }
