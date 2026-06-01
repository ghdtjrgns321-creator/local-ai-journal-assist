"""DuplicateDetector — Exact + Fuzzy 중복 전표 탐지 독립 트랙 (WU-05).

Why: 기존 L2-03 exact match recall 9%. 4가지 서브룰(Exact/Fuzzy/Split/TimeShift)로
     유사 금액, 분할 거래, 시차 중복까지 포착. BenfordDetector와 동일한 독립 트랙 패턴.

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).
      flagged_rules에는 L2-03a~d가 표시되지만 anomaly_score 가중합에는 미참여.
      FraudLayer의 기존 L2-03(exact match)는 하위 호환 목적으로 병존 유지.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pandas as pd

from src.detection.base import BaseDetector, DetectionResult, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.duplicate_pair_features import build_duplicate_pair_artifact
from src.detection.duplicate_rules import (
    b05a_exact_duplicate,
    b05b_fuzzy_duplicate,
    b05c_split_transaction,
    b05d_time_shifted_duplicate,
)


class DuplicateDetector(BaseDetector):
    """Exact + Fuzzy 중복 전표 탐지. FraudLayer _build_registry 패턴 준수."""

    @property
    def track_name(self) -> str:
        return "duplicate"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        start = time.perf_counter()
        warnings: list[str] = []
        if df.empty:
            raise ValueError("입력 DataFrame이 비어 있습니다")

        missing = validate_input(df, ["debit_amount", "credit_amount"])
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        # Why: 대규모 gl_account 그룹 사전 경고
        if "gl_account" in df.columns:
            grp_sizes = df.groupby("gl_account").size()
            big = grp_sizes[grp_sizes > self._settings.duplicate_max_group_size]
            if len(big) > 0:
                warnings.append(
                    f"gl_account 그룹 {len(big)}개가 "
                    f"{self._settings.duplicate_max_group_size}건 초과 → 스킵"
                )

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []
        coverage_issues: list[dict[str, Any]] = []

        for rule_id, func, kwargs in self._build_registry():
            missing_inputs = self._missing_inputs(rule_id, df)
            if missing_inputs:
                skipped.append(rule_id)
                coverage_issues.append(
                    {
                        "rule_id": rule_id,
                        "kind": "missing_prerequisites",
                        "missing_inputs": missing_inputs,
                    }
                )
                warnings.append(f"{rule_id} skipped: missing inputs {missing_inputs}")
                rule_results[rule_id] = pd.Series(0.0, index=df.index)
                continue
            try:
                rule_results[rule_id] = func(df, **kwargs)
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        elapsed = time.perf_counter() - start
        return self._build_result(df, rule_results, skipped, warnings, elapsed, coverage_issues)

    def _missing_inputs(self, rule_id: str, df: pd.DataFrame) -> list[str]:
        if rule_id == "L2-03b" and "line_text" not in df.columns:
            return ["line_text"]
        return []

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """서브룰 레지스트리: (rule_id, callable, kwargs)."""
        s = self._settings
        return [
            ("L2-03a", b05a_exact_duplicate, {}),
            (
                "L2-03b",
                b05b_fuzzy_duplicate,
                {
                    "fuzzy_threshold": s.duplicate_fuzzy_threshold,
                    "amount_tolerance": s.duplicate_amount_tolerance,
                    "max_group_size": s.duplicate_max_group_size,
                },
            ),
            (
                "L2-03c",
                b05c_split_transaction,
                {
                    "window_days": s.duplicate_split_window_days,
                    "amount_tolerance": s.duplicate_amount_tolerance,
                    "max_group_size": s.duplicate_max_group_size,
                },
            ),
            (
                "L2-03d",
                b05d_time_shifted_duplicate,
                {
                    "window_days": s.duplicate_time_window_days,
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
        coverage_issues: list[dict[str, Any]] | None = None,
    ) -> DetectionResult:
        if not rule_results:
            return self._empty_result(df, warnings, elapsed, skipped, coverage_issues)

        # Why: 각 서브룰의 연속 점수에 severity/5 정규화 적용
        details = pd.DataFrame(index=df.index)
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = raw_scores.reindex(df.index, fill_value=0.0) * severity_factor

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

        pair_artifact = build_duplicate_pair_artifact(
            df,
            self._settings,
            candidate_scores=scores,
            candidate_details=details,
        )
        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={
                "elapsed": elapsed,
                "skipped_rules": skipped,
                "coverage_issues": coverage_issues or [],
                "analysis_degraded": bool(coverage_issues),
                "pair_artifact": pair_artifact.to_dict(),
            },
            warnings=warnings,
        )

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
        skipped: list[str] | None = None,
        coverage_issues: list[dict[str, Any]] | None = None,
    ) -> DetectionResult:
        pair_artifact = build_duplicate_pair_artifact(df, self._settings)
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index),
            rule_flags=[],
            details=pd.DataFrame(index=df.index),
            metadata={
                "elapsed": elapsed,
                "skipped_rules": skipped or [],
                "coverage_issues": coverage_issues or [],
                "analysis_degraded": bool(coverage_issues),
                "pair_artifact": pair_artifact.to_dict(),
            },
            warnings=warnings,
        )
