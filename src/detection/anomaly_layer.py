"""Layer C: 이상 징후 오케스트레이터 — C01~C06, C08~C12.

룰 레지스트리를 순회하며 try/except로 격리 실행.
한 룰 실패해도 나머지 계속 진행, 실패 룰은 skipped + warning 기록.
C07(Benford)은 BenfordDetector 독립 트랙으로 분리됨 (DETECTION_RULES.md §2.4 점수 체계).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c05_fiscal_period_mismatch,
    c06_risky_description,
    c08_amount_outlier,
    c10_suspense_account,
    c12_abnormal_hours_concentration,
)
from src.detection.anomaly_rules_reversal import c11_reversal_entry
from src.detection.anomaly_rules_statistical import c09_rare_account_pair
from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.detection.base import DetectionResult

# Why: 최소한 금액 컬럼은 있어야 Layer C 실행 의미가 있음
_REQUIRED_COLUMNS = ["debit_amount", "credit_amount"]


class AnomalyDetector(BaseDetector):
    """C01~C06, C08~C12 이상 징후 탐지. 보조 레이어 (가중치 0.25).

    C07(Benford)은 BenfordDetector 독립 트랙으로 분리.
    """

    @property
    def track_name(self) -> str:
        return "layer_c"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """C01~C06, C08~C12 순차 실행. 각 룰은 try/except로 격리."""
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
        return [
            ("C01", c01_period_end_large, {"quantile": s.period_end_amount_quantile}),
            ("C02", c02_weekend_entry, {}),
            ("C03", c03_after_hours_entry, {}),
            ("C04", c04_backdated_entry, {"threshold_days": s.backdated_threshold_days}),
            ("C05", c05_fiscal_period_mismatch, {}),
            ("C06", c06_risky_description, {}),
            # C07(Benford)은 BenfordDetector 독립 트랙으로 분리
            ("C08", c08_amount_outlier, {"zscore_threshold": s.zscore_threshold}),
            ("C09", c09_rare_account_pair, {"percentile": s.account_pair_rare_percentile}),
            ("C10", c10_suspense_account, {}),
            ("C11", c11_reversal_entry, {
                "match_window_days": s.reversal_match_window_days,
                "rolling_window_days": s.reversal_rolling_window_days,
                "zero_threshold": s.reversal_zero_threshold,
                "score_threshold": s.reversal_score_threshold,
            }),
            ("C12", c12_abnormal_hours_concentration, {
                "sigma_threshold": s.abnormal_sigma_threshold,
                "rapid_approval_minutes": s.rapid_approval_minutes,
                "min_abnormal_ratio": s.min_abnormal_ratio,
                "min_midnight_entries": s.min_midnight_entries,
                "min_user_entries": s.min_user_entries,
                "auto_entry_sources": s.auto_entry_sources,
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
        for rule_id, flagged in rule_results.items():
            severity_score = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = flagged.astype(float) * severity_score

        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()

        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int(flagged.sum()),
                total_count=len(df),
            )
            for rule_id, flagged in rule_results.items()
        ]

        metadata = {"elapsed": elapsed, "skipped_rules": skipped}

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=metadata,
            warnings=warnings,
        )

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
