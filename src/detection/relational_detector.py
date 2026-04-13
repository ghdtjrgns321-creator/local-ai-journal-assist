"""RelationalDetector — 관계 기반 이상 탐지 독립 트랙 (WU-08).

Why: GL 전표의 거래처/계정/문서 관계에서 이상 패턴을 탐지.
     R01(신규 거래처 대액) + R02(휴면 계정) + R03(IC 이전가격) + R04(문서 흐름 누락).

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import SEVERITY_MAP
from src.detection.relational_rules import (
    r01_new_counterparty,
    r02_dormant_account_activity,
    r03_transfer_pricing_anomaly,
    r04_missing_relationship,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class RelationalDetector(BaseDetector):
    """관계 기반 이상 탐지기. IntercompanyMatcher _build_registry 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        audit_rules: dict | None = None,
        doc_flow_df: pd.DataFrame | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules or {}
        self._doc_flow_df = doc_flow_df

    @property
    def track_name(self) -> str:
        return "relational"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        start = time.perf_counter()
        warnings: list[str] = []

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
        if not rule_results:
            return self._empty_result(df, warnings, elapsed)
        return self._build_result(df, rule_results, skipped, warnings, elapsed)

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """서브룰 레지스트리 — settings 기반 파라미터 주입."""
        s = self._settings
        registry: list[tuple[str, Callable, dict]] = [
            ("R01", r01_new_counterparty, {
                "lookback_days": s.rel_new_cp_lookback_days,
                "large_quantile": s.rel_new_cp_large_quantile,
            }),
            ("R02", r02_dormant_account_activity, {
                "inactive_days": s.rel_dormant_inactive_days,
                "reactivation_window_days": s.rel_dormant_reactivation_window_days,
                "min_amount": s.rel_dormant_reactivation_min_amount,
            }),
            ("R03", r03_transfer_pricing_anomaly, {
                "deviation_threshold": s.rel_tp_ic_deviation_threshold,
                "min_ic_pairs": s.rel_tp_min_ic_pairs,
            }),
        ]
        # Why: R04는 document_flows 데이터가 있을 때만 실행 (graceful)
        if self._doc_flow_df is not None and not self._doc_flow_df.empty:
            registry.append(
                ("R04", r04_missing_relationship, {
                    "doc_flow_df": self._doc_flow_df,
                }),
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
        """룰별 연속 점수 → scores, details, RuleFlag 통합."""
        # Why: severity/5.0 정규화 (IntercompanyMatcher 패턴 동일)
        details = pd.DataFrame(index=df.index)
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = (
                raw_scores.reindex(df.index, fill_value=0.0) * severity_factor
            )

        # Why: MAX 패턴 — 행별 최대 점수 (합산 아님)
        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()

        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int((raw_scores > 0).sum()),
                total_count=len(df),
            )
            for rule_id, raw_scores in rule_results.items()
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
        self, df: pd.DataFrame, warnings: list[str], elapsed: float,
    ) -> DetectionResult:
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index),
            rule_flags=[],
            details=pd.DataFrame(index=df.index),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
