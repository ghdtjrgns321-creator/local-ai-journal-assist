"""GraphDetector — 그래프 기반 순환/이전가격 탐지 독립 트랙 (WU-22).

Why: L3-03 MVP(is_intercompany 플래그)의 recall 7% 한계 개선. networkx 기반
     Johnson N-hop 순환(GR01) + 양방향 IC 엣지 price asymmetry(GR03).

Note: LAYER_WEIGHTS에 의도적 미등록 — RelationalDetector 선례 준수. 성능 평가 후
      Phase 3 Stacking 단계에서 가중치 배분.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import SEVERITY_MAP

if TYPE_CHECKING:
    from collections.abc import Callable


class GraphDetector(BaseDetector):
    """그래프 기반 순환/이전가격 탐지기. RelationalDetector 패턴 미러링."""

    def __init__(self, settings: AuditSettings | None = None) -> None:
        super().__init__(settings)
        try:
            import networkx as nx  # noqa: F401

            self._nx_available = True
        except ImportError:
            self._nx_available = False

    @property
    def track_name(self) -> str:
        return "graph"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        if df.empty:
            raise ValueError("입력 DataFrame이 비어 있습니다")

        start = time.perf_counter()
        warnings: list[str] = []

        if not self._nx_available:
            warnings.append("networkx 미설치 — GraphDetector 스킵")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []
        rule_metadata: dict[str, dict] = {}

        # Why: rule 함수에 metadata dict를 주입하여 사이드채널로 통계 수집
        for rule_id, func, kwargs in self._build_registry():
            meta: dict = {}
            try:
                rule_results[rule_id] = func(df, metadata=meta, **kwargs)
                rule_metadata[rule_id] = meta
                # Why: 엣지 수 임계 초과 warning을 rule metadata에서 수집
                if meta.get("gr01_max_edges_raised"):
                    warnings.append(
                        f"GR01 엣지 수 임계 초과 — min_amount 자동 상향 "
                        f"(최종 {meta.get('gr01_min_amount_effective'):.0f}원)"
                    )
                if meta.get("gr01_skipped_components", 0) > 0:
                    warnings.append(
                        f"GR01 대형 component {meta['gr01_skipped_components']}개 skip"
                    )
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        elapsed = time.perf_counter() - start
        if not rule_results:
            return self._empty_result(df, warnings, elapsed)
        return self._build_result(
            df, rule_results, skipped, warnings, elapsed, rule_metadata
        )

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """서브룰 레지스트리 — settings 기반 파라미터 주입."""
        s = self._settings
        from src.detection.graph_rules import (
            gr01_circular_transaction,
            gr03_transfer_pricing_graph,
        )

        return [
            ("GR01", gr01_circular_transaction, {
                "max_cycle_length": s.graph_gr01_max_cycle_length,
                "min_amount": s.graph_gr01_min_amount,
                "max_edges": s.graph_gr01_max_edges,
                "max_component_size": s.graph_gr01_max_component_size,
            }),
            ("GR03", gr03_transfer_pricing_graph, {
                "min_path_length": s.graph_gr03_min_path_length,
                "deviation_threshold": s.graph_gr03_price_deviation_threshold,
            }),
        ]

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
        rule_metadata: dict[str, dict],
    ) -> DetectionResult:
        """룰별 연속 점수 → scores, details, RuleFlag 통합."""
        details = pd.DataFrame(index=df.index)
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = (
                raw_scores.reindex(df.index, fill_value=0.0) * severity_factor
            )

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

        # Why: 룰별 metadata를 top-level로 병합
        merged_meta: dict = {"elapsed": elapsed, "skipped_rules": skipped}
        for rule_meta in rule_metadata.values():
            merged_meta.update(rule_meta)

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=merged_meta,
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
