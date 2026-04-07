"""Layer B: 부정 탐지 오케스트레이터 — B01~B11.

룰 레지스트리를 순회하며 try/except로 격리 실행.
한 룰 실패해도 나머지 계속 진행, 실패 룰은 skipped + warning 기록.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b10_circular_intercompany,
)
from src.detection.fraud_rules_feature import (
    b01_revenue_manipulation,
    b02_near_threshold,
    b03_exceeds_threshold,
    b08_manual_override,
)
from src.detection.fraud_rules_groupby import (
    b04_duplicate_payment,
    b05_duplicate_entry,
    b11_expense_capitalization,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from config.settings import AuditSettings
    from src.detection.base import DetectionResult

# Why: 최소한 금액 컬럼은 있어야 Layer B 실행 의미가 있음
_REQUIRED_COLUMNS = ["debit_amount", "credit_amount"]


class FraudLayer(BaseDetector):
    """B01~B10 부정 탐지. 핵심 레이어 (가중치 0.45)."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        audit_rules: dict | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules

    @property
    def track_name(self) -> str:
        return "layer_b"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """B01~B10 순차 실행. 각 룰은 try/except로 격리."""
        start = time.perf_counter()
        warnings: list[str] = []

        # Why: 빈 DataFrame이면 validate_input에서 ValueError → 빈 결과 반환
        missing = validate_input(df, _REQUIRED_COLUMNS)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry():
            try:
                result = func(df, **kwargs)
                rule_results[rule_id] = result
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
            ("B01", b01_revenue_manipulation, {"zscore_threshold": s.zscore_threshold}),
            ("B02", b02_near_threshold, {}),
            ("B03", b03_exceeds_threshold, {}),
            ("B04", b04_duplicate_payment, {"window_days": s.duplicate_payment_window_days}),
            ("B05", b05_duplicate_entry, {}),
            ("B06", b06_self_approval, {"min_amount": s.approval_thresholds[0], "audit_rules": self._audit_rules}),
            ("B07", b07_segregation_of_duties, {"sod_threshold": s.sod_process_threshold, "audit_rules": self._audit_rules}),
            ("B08", b08_manual_override, {}),
            ("B09", b09_skipped_approval, {}),
            ("B10", b10_circular_intercompany, {}),
            ("B11", b11_expense_capitalization, {}),
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

        # Why: details는 행×룰 매트릭스 (severity/5 정규화)
        details = pd.DataFrame(index=df.index)
        for rule_id, flagged in rule_results.items():
            severity_score = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = flagged.astype(float) * severity_score

        # Why: 행별 최대 severity 점수 사용 (합산 아닌 최대값)
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
        """빈 결과 생성 — 필수 컬럼 누락 또는 모든 룰 실패 시."""
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index if not df.empty else pd.RangeIndex(0)),
            rule_flags=[],
            details=pd.DataFrame(index=df.index if not df.empty else pd.RangeIndex(0)),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
