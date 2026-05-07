"""EvidenceDetector — 증빙/컷오프/금액 탐지 독립 트랙 (WU-14).

Why: 감사기준서 240호/500호/315호/330호 근거.
     EV01(증빙 존재) + L3-11(컷오프) + EV03(금액 불일치).

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import SEVERITY_MAP
from src.detection.evidence_rules import (
    ev01_missing_evidence,
    ev02_cutoff_violation,
    ev03_amount_mismatch,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class EvidenceDetector(BaseDetector):
    """증빙/컷오프/금액 탐지기. RelationalDetector _build_registry 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        audit_rules: dict | None = None,
        rule_ids: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules or {}
        self._rule_ids = {rule_id.upper() for rule_id in rule_ids} if rule_ids else None

    @property
    def track_name(self) -> str:
        return "evidence"

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
        """서브룰 레지스트리 — settings + audit_rules 기반 파라미터 주입."""
        s = self._settings
        evidence_cfg = self._audit_rules.get("evidence", {})
        registry = [
            ("EV01", ev01_missing_evidence, {
                "qualified_doc_types": evidence_cfg.get("qualified_doc_types"),
                "tax_threshold": s.ev_tax_threshold,
                "split_max_amount": s.ev_split_max_amount,
                "split_min_count": s.ev_split_min_count,
            }),
            ("L3-11", ev02_cutoff_violation, {
                "revenue_cutoff_days": s.ev_revenue_cutoff_days,
                "expense_cutoff_days": s.ev_expense_cutoff_days,
                "period_end_weight": s.ev_cutoff_period_end_weight,
                "max_day_diff": s.ev_cutoff_max_day_diff,
                "use_business_days": s.ev_cutoff_use_business_days,
                "custom_holidays": s.custom_holidays or None,
                # Why: evidence 섹션 우선, 없으면 patterns 섹션 fallback (비대칭 방지)
                "revenue_account_prefixes": (
                    evidence_cfg.get("revenue_account_prefixes")
                    or self._audit_rules.get("patterns", {}).get("revenue_account_prefixes")
                ),
                "expense_account_prefixes": evidence_cfg.get(
                    "expense_account_prefixes",
                ),
            }),
            ("EV03", ev03_amount_mismatch, {
                "amount_tolerance": s.ev_amount_tolerance,
                "vat_rate": s.ev_vat_rate,
                "vat_tolerance": s.ev_vat_tolerance,
            }),
        ]
        if self._rule_ids is None:
            return registry
        return [item for item in registry if item[0].upper() in self._rule_ids]

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
        rule_breakdowns: dict[str, object] = {}
        row_annotations: dict[str, object] = {}
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            score_series = (
                raw_scores.attrs.get("score_series")
                if hasattr(raw_scores, "attrs")
                else None
            )
            if score_series is not None:
                base_scores = pd.Series(score_series, index=df.index).fillna(0.0)
            else:
                base_scores = raw_scores.reindex(df.index, fill_value=0.0)
            details[rule_id] = base_scores * severity_factor
            breakdown = raw_scores.attrs.get("breakdown") if hasattr(raw_scores, "attrs") else None
            if breakdown:
                rule_breakdowns[rule_id] = breakdown
            annotations = (
                raw_scores.attrs.get("row_annotations")
                if hasattr(raw_scores, "attrs")
                else None
            )
            if annotations:
                row_annotations[rule_id] = annotations

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
            metadata={
                "elapsed": elapsed,
                "skipped_rules": skipped,
                "rule_breakdowns": rule_breakdowns,
                "row_annotations": row_annotations,
            },
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
            metadata={
                "elapsed": elapsed,
                "skipped_rules": [],
                "rule_breakdowns": {},
                "row_annotations": {},
            },
            warnings=warnings,
        )
