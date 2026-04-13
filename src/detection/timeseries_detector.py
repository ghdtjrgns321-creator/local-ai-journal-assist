"""시계열 탐지 오케스트레이터 — TS01(거래 급증), TS02(비정상 거래 주기).

Why: Phase 1의 C01~C03은 시점별 이상만 탐지. 거래 빈도 패턴은 미탐지.
     VarianceDetector(Layer D)와 동일한 레지스트리 패턴.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.timeseries_rules import (
    ts01_transaction_burst,
    ts02_unusual_frequency,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.detection.base import DetectionResult

_REQUIRED_COLUMNS = ["posting_date"]


class TimeseriesDetector(BaseDetector):
    """시계열 밀도 분석 탐지기. TransactionBurst + UnusualFrequency.

    Why: posting_date 기반 일별 건수 급증(TS01)과
         그룹별 단기 집중(TS02)을 규칙 기반으로 탐지.
    """

    @property
    def track_name(self) -> str:
        return "timeseries"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """TS01, TS02 순차 실행."""
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
            ("TS01", ts01_transaction_burst, {
                "window_days": s.burst_window_days,
                "sigma": s.burst_sigma,
            }),
            ("TS02", ts02_unusual_frequency, {
                "window_days": s.frequency_window_days,
                "min_count": s.frequency_min_count,
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

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={"elapsed": elapsed, "skipped_rules": skipped},
            warnings=warnings,
        )

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """빈 결과 — 컬럼 누락, 모든 룰 실패 시."""
        idx = df.index if not df.empty else pd.RangeIndex(0)
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=idx),
            rule_flags=[],
            details=pd.DataFrame(index=idx),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
