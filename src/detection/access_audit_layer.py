"""AccessAuditDetector — 접근감사/감사추적 독립 트랙 (WU-15).

Why: 접근통제·변경이력·전표번호 연속성·승인 프로세스 검증을 독립 트랙으로 분리.
     AA01은 change_log JOIN이 필요하여 기존 Layer B 단일 DF 패턴에 부적합.
     RelationalDetector(doc_flow_df 주입)와 동일한 외부 DF 주입 패턴 사용.

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import AuditSettings
from src.detection.access_audit_rules import (
    aa01_document_modification,
    aa02_abnormal_ip_access,
    aa03_document_number_gap,
    aa04_approval_process,
)
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import SEVERITY_MAP

if TYPE_CHECKING:
    from collections.abc import Callable


class AccessAuditDetector(BaseDetector):
    """AA01~AA04 접근감사 탐지기. RelationalDetector _build_registry 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        change_log_df: pd.DataFrame | None = None,
        audit_rules: dict | None = None,
    ) -> None:
        super().__init__(settings)
        self._change_log_df = change_log_df
        self._audit_rules = audit_rules or {}

    @property
    def track_name(self) -> str:
        return "access_audit"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """AA01~AA04 순차 실행. 각 룰은 try/except로 격리."""
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
        """서브룰 레지스트리 — settings + audit_rules 기반 파라미터 주입."""
        s = self._settings
        aa_config = self._audit_rules.get("access_audit", {})

        registry: list[tuple[str, Callable, dict]] = [
            ("AA01", aa01_document_modification, {
                "change_log_df": self._change_log_df,
                "watched_fields": tuple(
                    aa_config.get("modification_watched_fields",
                                  ["line_text", "header_text"])
                ),
                "high_amount_quantile": s.aa01_high_amount_quantile,
            }),
            ("AA02", aa02_abnormal_ip_access, {}),
            ("AA03", aa03_document_number_gap, {
                "exclude_doc_types": tuple(
                    aa_config.get("gap_exclude_doc_types", ["ST", "MG"])
                ),
            }),
            ("AA04", aa04_approval_process, {
                "approval_thresholds": s.approval_thresholds,
                "max_delay_days": int(
                    aa_config.get("approval_delay_days", s.aa04_max_delay_days)
                ),
            }),
        ]
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
        # Why: severity/5.0 정규화 (RelationalDetector 패턴 동일)
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
