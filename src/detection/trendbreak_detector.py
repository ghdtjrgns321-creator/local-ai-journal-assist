"""TrendBreak: 회계추정치 편의(bias) 탐지 오케스트레이터 — TB01, TB02.

Why: ISA 540 소급 검토 방식으로 추정치 계정의 다기간 편향을 탐지.
     기존회사에서 3개년 이상 engagement가 존재할 때만 실행.
     VarianceDetector(variance_layer.py)와 동일한 레지스트리 패턴.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.trendbreak_rules import tb01_sign_bias, tb02_range_extremity

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from src.detection.base import DetectionResult
    from src.detection.multi_year_loader import MultiYearEstimates

_REQUIRED_COLUMNS = ["gl_account"]


class TrendBreakDetector(BaseDetector):
    """TrendBreak: 회계추정치 편의(bias) 탐지기.

    Why: ISA 540 소급 검토 방식으로 추정치 계정의 다기간 편향을 탐지.
         기존회사에서 3개년 이상 engagement가 존재할 때만 실행.
    """

    def __init__(
        self,
        settings=None,
        multi_year_estimates: MultiYearEstimates | None = None,
    ) -> None:
        super().__init__(settings)
        self._estimates = multi_year_estimates

    @property
    def track_name(self) -> str:
        return "trendbreak"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """TB01, TB02 순차 실행. multi_year_estimates 없으면 빈 결과."""
        start = time.perf_counter()
        warnings: list[str] = []

        if self._estimates is None:
            warnings.append("다기간 추정치 데이터 없음 — TrendBreak 스킵")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        missing = validate_input(df, _REQUIRED_COLUMNS)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry():
            try:
                # Why: 룰 함수는 계정 단위 dict 반환 → 행 단위 pd.Series로 변환
                account_results: dict[str, dict[str, Any]] = func(**kwargs)
                flagged_accounts = {
                    acct for acct, info in account_results.items() if info.get("flagged", False)
                }
                rule_results[rule_id] = df["gl_account"].isin(flagged_accounts)
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
            (
                "TB01",
                tb01_sign_bias,
                {
                    "estimation_errors": self._estimates.estimation_errors,
                    "min_periods": s.trendbreak_min_periods,
                    "bias_ratio_threshold": s.trendbreak_bias_ratio,
                },
            ),
            (
                "TB02",
                tb02_range_extremity,
                {
                    "provision_amounts": self._estimates.provision_amounts,
                    # Why: TB02는 IQR 계산에 최소 3개 필요. min_periods가 1로 낮아져도 안전.
                    "min_periods": max(s.trendbreak_min_periods + 1, 3),
                    "extremity_quantile": s.trendbreak_extremity_quantile,
                },
            ),
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
        """빈 결과 — estimates 없음, 컬럼 누락, 모든 룰 실패 시."""
        idx = df.index if not df.empty else pd.RangeIndex(0)
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=idx),
            rule_flags=[],
            details=pd.DataFrame(index=idx),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
