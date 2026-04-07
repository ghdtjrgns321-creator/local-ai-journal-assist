"""Layer D: 전기 대비 변동 탐지 오케스트레이터 — D01, D02.

Why: 과거 engagement가 있는 기존회사에서만 실행.
     AnomalyDetector(anomaly_layer.py)와 동일한 레지스트리 패턴.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.prior_data_loader import PriorSummary
from src.detection.variance_rules import (
    d01_account_aggregate_variance,
    d02_monthly_pattern_variance,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.detection.base import DetectionResult

# Why: 최소한 금액 + 계정 컬럼은 있어야 Layer D 실행 의미가 있음
_REQUIRED_COLUMNS = ["debit_amount", "credit_amount", "gl_account"]


class VarianceDetector(BaseDetector):
    """Layer D: 전기 대비 변동 탐지. 기존회사 전용.

    Why: 과거 데이터가 있는 회사에서만 실행되어
         계정과목별 급변(D01)과 월별 패턴 변화(D02)를 탐지.
    """

    def __init__(
        self,
        settings=None,
        prior_summary: PriorSummary | None = None,
    ) -> None:
        super().__init__(settings)
        self._prior = prior_summary

    @property
    def track_name(self) -> str:
        return "layer_d"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """D01, D02 순차 실행. prior_summary 없으면 빈 결과."""
        start = time.perf_counter()
        warnings: list[str] = []

        if self._prior is None:
            warnings.append("전기 데이터 없음 — Layer D 스킵")
            return self._empty_result(df, warnings, time.perf_counter() - start)

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
        registry: list[tuple[str, Callable, dict]] = [
            ("D01", d01_account_aggregate_variance, {
                "prior_aggregates": self._prior.account_aggregates,
                "variance_threshold": s.variance_threshold,
            }),
        ]

        # Why: fiscal_period 누락 시 d02 내부에서 조기 반환 처리.
        #      레지스트리에는 항상 등록하여 실패 룰 추적(skipped) 일관성 유지.
        registry.append(
            ("D02", d02_monthly_pattern_variance, {
                "prior_patterns": self._prior.monthly_patterns,
                "jsd_threshold": s.monthly_pattern_threshold,
            })
        )

        return registry

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
        """빈 결과 생성 — prior 없음, 컬럼 누락, 모든 룰 실패 시."""
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index if not df.empty else pd.RangeIndex(0)),
            rule_flags=[],
            details=pd.DataFrame(index=df.index if not df.empty else pd.RangeIndex(0)),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
