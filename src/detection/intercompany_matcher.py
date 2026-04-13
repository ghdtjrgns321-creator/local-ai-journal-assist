"""IntercompanyMatcher — 내부거래 매칭 독립 트랙 (WU-07).

Why: B10(MVP)은 is_intercompany bool만 flag하여 recall 7%.
     양측 거래 대사(group-level matching)로 미매칭/금액불일치/시차이상 탐지.
     N:M 다대다 매칭 + 이종 통화 방어 적용.

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).
      FraudLayer의 기존 B10(IC 전표 존재 감지)은 하위 호환 목적으로 병존 유지.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.intercompany_rules import (
    ic01_unmatched_intercompany,
    ic02_amount_mismatch,
    ic03_timing_gap,
    load_ic_pairs,
    match_ic_groups,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class IntercompanyMatcher(BaseDetector):
    """내부거래 매칭 탐지기. DuplicateDetector _build_registry 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        audit_rules: dict | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules or {}
        self._pair_map = load_ic_pairs(self._audit_rules)

    @property
    def track_name(self) -> str:
        return "intercompany"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        start = time.perf_counter()
        warnings: list[str] = []

        required = [
            "is_intercompany", "gl_account",
            "debit_amount", "credit_amount",
        ]
        missing = validate_input(df, required)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        if not self._pair_map:
            warnings.append("intercompany.pairs 설정 비어있음 — IC 매칭 스킵")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        ic_count = df["is_intercompany"].fillna(False).sum()
        if ic_count < self._settings.ic_min_ic_rows:
            warnings.append(
                f"IC 행 {ic_count}건 < 최소 {self._settings.ic_min_ic_rows}건 — 스킵",
            )
            return self._empty_result(df, warnings, time.perf_counter() - start)

        # Why: match_ic_groups를 한 번만 호출하여 3개 서브룰에 공유 (O(n) → O(3n) 방지)
        match_df = match_ic_groups(
            df, self._pair_map, self._settings.ic_amount_tolerance,
        )

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry(match_df):
            try:
                rule_results[rule_id] = func(df, **kwargs)
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        elapsed = time.perf_counter() - start
        return self._build_result(df, rule_results, skipped, warnings, elapsed)

    def _build_registry(
        self, match_df: pd.DataFrame,
    ) -> list[tuple[str, Callable, dict]]:
        """서브룰 레지스트리 — 사전 계산된 match_df를 공유."""
        s = self._settings
        return [
            ("IC01", ic01_unmatched_intercompany, {
                "match_df": match_df,
            }),
            ("IC02", ic02_amount_mismatch, {
                "match_df": match_df,
                "amount_tolerance": s.ic_amount_tolerance,
                "max_diff_ratio": s.ic_max_diff_ratio,
            }),
            ("IC03", ic03_timing_gap, {
                "match_df": match_df,
                "date_window_days": s.ic_date_window_days,
                "max_day_diff": s.ic_max_day_diff,
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
        """룰별 연속 점수 → scores, details, RuleFlag 통합."""
        if not rule_results:
            return self._empty_result(df, warnings, elapsed)

        # Why: severity/5.0 정규화 (DuplicateDetector 패턴 동일)
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
