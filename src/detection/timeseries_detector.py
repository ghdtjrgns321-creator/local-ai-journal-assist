"""Timeseries family statistical anomaly orchestrator.

Why: rule-style boolean burst/frequency 를 robust z-score + zero-preserving ECDF
+ period-end concentration 결합으로 격상. TS01/TS02 rule_id 와 detector contract
는 유지하고 내부 score 만 continuous 화한다.

PHASE2 family aggregation 은 max(ts01_signal, ts02_signal) 을 사용하며,
ts01_signal = max(daily_burst, period_end_concentration), ts02_signal = group_frequency.
ECDF threshold 단일 기준으로 TS01/TS02 boolean 을 재계산해 분포 변별력을 확보한다.

Phase 1 rule hit / flagged_rules / DataSynth 라벨을 입력으로 사용하지 않는다.
"""

from __future__ import annotations

import time

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
        round_unit = float(getattr(s, "round_unit", 1_000_000.0))
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
            round_amount_score(df, round_unit=round_unit),
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
