"""L1-L4 anomaly-rule track orchestrator — L3-04~L3-08, L4-03~L4-06.

룰 레지스트리를 순회하며 try/except로 격리 실행.
한 룰 실패해도 나머지 계속 진행, 실패 룰은 skipped + warning 기록.
L4-02(Benford)은 BenfordDetector 독립 트랙으로 분리됨 (DETECTION_RULES.md §2.4 점수 체계).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from src.detection.anomaly_rules_batch import c13_batch_anomaly
from src.detection.anomaly_rules_reversal import c11_reversal_entry
from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c01_period_end_sensitive_account,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c05_fiscal_period_mismatch,
    c06_missing_or_corrupted_description,
    c08_amount_outlier,
    c10_suspense_account,
    c12_abnormal_hours_concentration,
)
from src.detection.anomaly_rules_statistical import c09_rare_account_pair
from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.detection.base import DetectionResult

# Why: 최소한 금액 컬럼은 있어야 L1-L4 anomaly-rule track 실행 의미가 있음
_REQUIRED_COLUMNS = ["debit_amount", "credit_amount"]


class AnomalyDetector(BaseDetector):
    """L3-04~L3-08, L4-03~L4-05 이상 징후 탐지. 보조 레이어 (가중치 0.25).

    L4-02(Benford)은 BenfordDetector 독립 트랙으로 분리.
    """

    def __init__(self, settings=None, audit_rules: dict | None = None) -> None:
        super().__init__(settings)
        if audit_rules is None:
            from config.settings import get_audit_rules
            audit_rules = get_audit_rules()
        self._audit_rules = audit_rules

    @property
    def track_name(self) -> str:
        return "layer_c"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """L3-04~L3-08, L4-03~L4-05 순차 실행. 각 룰은 try/except로 격리."""
        start = time.perf_counter()
        warnings: list[str] = []

        missing = validate_input(df, _REQUIRED_COLUMNS)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry():
            try:
                rule_results[rule_id] = func(df, **kwargs)
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        elapsed = time.perf_counter() - start
        return self._build_result(df, rule_results, skipped, warnings, elapsed)

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """룰 레지스트리: (rule_id, callable, kwargs)."""
        s = self._settings
        patterns = self._audit_rules.get("patterns", {})
        return [
            ("L3-04", c01_period_end_large, {
                "quantile": s.period_end_amount_quantile,
                "min_group_size": s.c01_min_group_size,
                "whitelist_patterns": patterns.get("period_end_whitelist", []),
            }),
            ("L3-05", c02_weekend_entry, {}),
            ("L3-06", c03_after_hours_entry, {}),
            ("L3-07", c04_backdated_entry, {"threshold_days": s.backdated_threshold_days}),
            ("L1-08", c05_fiscal_period_mismatch, {
                "policy": patterns.get("fiscal_period_mismatch_policy", {}),
            }),
            ("L3-08", c06_missing_or_corrupted_description, {}),
            # L4-02(Benford)은 BenfordDetector 독립 트랙으로 분리
            ("L4-03", c08_amount_outlier, {
                "zscore_threshold": s.zscore_threshold,
                "min_amount_quantile": s.l403_min_amount_quantile,
            }),
            ("L4-04", c09_rare_account_pair, {"percentile": s.account_pair_rare_percentile}),
            ("L3-09", c10_suspense_account, {
                "threshold_days": s.suspense_aging_days,
                "min_open_amount": s.suspense_min_open_amount,
            }),
            ("L2-05", c11_reversal_entry, {
                "match_window_days": s.reversal_match_window_days,
                "rolling_window_days": s.reversal_rolling_window_days,
                "zero_threshold": s.reversal_zero_threshold,
                "score_threshold": s.reversal_score_threshold,
            }),
            ("L4-05", c12_abnormal_hours_concentration, {
                "sigma_threshold": s.abnormal_sigma_threshold,
                "rapid_approval_minutes": s.rapid_approval_minutes,
                "min_abnormal_ratio": s.min_abnormal_ratio,
                "min_midnight_entries": s.min_midnight_entries,
                "min_user_entries": s.min_user_entries,
                "min_high_context_midnight_entries": s.min_high_context_midnight_entries,
                "auto_entry_sources": s.auto_entry_sources,
            }),
            ("L4-06", c13_batch_anomaly, {
                "batch_sources": s.batch_source_values,
                "period_end_ratio": s.batch_period_end_ratio,
                "simultaneous_threshold": s.batch_simultaneous_threshold,
                "amount_zscore": s.batch_amount_zscore,
            }),
        ]

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """룰별 bool Series → scores, details, RuleFlag 통합."""
        if not rule_results:
            return self._empty_result(df, warnings, elapsed)

        details = pd.DataFrame(index=df.index)
        rule_breakdowns: dict[str, object] = {}
        row_annotations: dict[str, object] = {}
        for rule_id, flagged in rule_results.items():
            severity_score = SEVERITY_MAP[rule_id] / 5.0
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            if score_series is not None:
                score = pd.Series(score_series, index=df.index).fillna(0.0).astype(float)
                if rule_id == "L3-04":
                    score = self._score_l304(df, flagged, severity_score, base_score=score)
                details[rule_id] = score
            elif rule_id == "L3-04":
                details[rule_id] = self._score_l304(df, flagged, severity_score)
            else:
                details[rule_id] = flagged.astype(float) * severity_score
            breakdown = flagged.attrs.get("breakdown") if hasattr(flagged, "attrs") else None
            if breakdown:
                rule_breakdowns[rule_id] = breakdown
            annotations = (
                flagged.attrs.get("row_annotations")
                if hasattr(flagged, "attrs")
                else None
            )
            if annotations:
                row_annotations[rule_id] = annotations

        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()

        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int(flagged.sum()),
                total_count=len(df),
                detail=(
                    self._l307_detail(df, flagged)
                    if rule_id == "L3-07"
                    else self._format_rule_detail(rule_id, flagged)
                ),
            )
            for rule_id, flagged in rule_results.items()
        ]

        metadata = {
            "elapsed": elapsed,
            "skipped_rules": skipped,
            "rule_breakdowns": rule_breakdowns,
            "row_annotations": row_annotations,
        }

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=metadata,
            warnings=warnings,
        )

    def _score_l304(
        self,
        df: pd.DataFrame,
        flagged: pd.Series,
        severity_score: float,
        base_score: pd.Series | None = None,
    ) -> pd.Series:
        """Apply sensitive-account priority bonus without creating new L3-04 flags."""
        score = (
            base_score.copy()
            if base_score is not None
            else flagged.astype(float) * severity_score
        )
        patterns = self._audit_rules.get("patterns", {})
        sensitive = c01_period_end_sensitive_account(
            df,
            patterns.get("period_end_sensitive_accounts", {}),
        )
        bonus = float(getattr(self._settings, "period_end_sensitive_bonus", 0.15))
        return (score + (flagged & sensitive).astype(float) * bonus).clip(upper=1.0)

    def _l307_detail(self, df: pd.DataFrame, flagged: pd.Series) -> str | None:
        """Summarize L3-07 direction without changing score columns."""
        if "days_backdated" not in df.columns:
            return None

        days = pd.to_numeric(df["days_backdated"], errors="coerce")
        flagged_mask = flagged.reindex(df.index, fill_value=False).astype(bool)
        flagged_days = days[flagged_mask]
        if flagged_days.empty:
            return None

        late_count = int((flagged_days > 0).sum())
        forward_count = int((flagged_days < 0).sum())
        return (
            f"late_posting={late_count}, "
            f"forward_date_gap={forward_count}, "
            f"threshold_days={self._settings.backdated_threshold_days}"
        )

    def _format_rule_detail(self, rule_id: str, flagged: pd.Series) -> str | None:
        """Render optional rule detail from attrs for surfaced rules."""
        if not hasattr(flagged, "attrs"):
            return None
        breakdown = flagged.attrs.get("breakdown")
        if not breakdown:
            return None
        if rule_id == "L3-09":
            return f"threshold_days={breakdown.get('base_threshold_days')}"
        if rule_id == "L2-05":
            return (
                "high_confidence="
                f"{breakdown.get('high_confidence_count', 0)}, "
                "candidate="
                f"{breakdown.get('candidate_count', 0)}"
            )
        return None

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """빈 결과 생성 — 필수 컬럼 누락 또는 모든 룰 실패 시."""
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index if not df.empty else pd.RangeIndex(0)),
            rule_flags=[],
            details=pd.DataFrame(index=df.index if not df.empty else pd.RangeIndex(0)),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
