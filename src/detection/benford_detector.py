"""Benford 독립 트랙 — DETECTION_RULES.md §2.3 Benford 독립 트랙 가중치 0.15.

Why: Benford는 전체 분포 검정이라 행별 룰(L3-04~L4-04)과 성격이 다르다.
     L4-02는 독립 트랙으로 분리하여 score_aggregator가
     LAYER_WEIGHTS[Layer.BENFORD] = 0.15를 별도 적용할 수 있게 한다.
     L4-02 행별 선별 로직 + deviation 비례 스코어는 anomaly_rules_statistical.py를 재사용.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.detection.anomaly_rules_statistical import c07_benford_violation
from src.detection.base import BaseDetector, validate_input
from src.detection.explanation_schema import RuleExplanation

if TYPE_CHECKING:
    from src.detection.base import DetectionResult


_RULE_ID = "L4-02"

BENFORD_RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    "L4-02": RuleExplanation(
        principle=(
            "Analytical procedures should evaluate population-level digit distribution anomalies."
        ),
        violation_reason=(
            "The amount population deviates from expected Benford first-digit behavior."
        ),
        audit_next_action=(
            "Review account/process populations, inspect high-deviation digit groups, and use "
            "candidate rows as drill-down context rather than standalone conclusions."
        ),
        reference="ISA 520; PCAOB AS 2305",
    ),
}


class BenfordDetector(BaseDetector):
    """Benford 독립 탐지 트랙 (가중치 0.15)."""

    @property
    def track_name(self) -> str:
        return "benford"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """Benford 분석 → 비적합 시 편차 큰 자릿수 행 플래그."""
        start = time.perf_counter()
        warnings: list[str] = []

        missing = validate_input(df, ["debit_amount", "credit_amount"])
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        try:
            scores, meta = c07_benford_violation(df, settings=self._settings)
        except Exception as exc:
            warnings.append(f"{_RULE_ID} 실행 실패: {exc}")
            self._logger.warning("%s 실행 실패: %s", _RULE_ID, exc)
            return self._empty_result(df, warnings, time.perf_counter() - start)

        elapsed = time.perf_counter() - start

        # Why: Benford는 개별 전표 적발보다 모집단/계정 단위 분포 이상 finding이 본질이다.
        #      c07_benford_violation()의 점수는 drill-down 후보 점수로 metadata에만 남기고,
        #      최종 anomaly_score/anomaly_flags에는 단독 L4-02 행별 플래그를 반영하지 않는다.
        candidate_scores = scores.astype(float)
        candidate_count = int((candidate_scores > 0).sum())
        meta["benford_candidate_count"] = candidate_count
        meta["benford_candidate_indices"] = candidate_scores[candidate_scores > 0].index.tolist()
        meta["benford_candidate_score_max"] = (
            float(candidate_scores.max()) if not candidate_scores.empty else 0.0
        )
        meta["benford_row_scoring_mode"] = "finding_first_drilldown_only"

        scores = pd.Series(0.0, index=df.index, dtype=float)
        flagged_indices: list[int] = []

        rule_flags = [
            self._create_rule_flag(
                rule_id=_RULE_ID,
                flagged_count=0,
                total_count=len(df),
                detail=(
                    f"finding_count={len(meta.get('benford_findings', []))}; "
                    f"candidate_rows={candidate_count}; row_flags_disabled=true"
                ),
            )
        ]

        metadata: dict[str, Any] = {"elapsed": elapsed, "skipped_rules": []}
        metadata.update(meta)

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=pd.DataFrame({_RULE_ID: scores}, index=df.index),
            metadata=metadata,
            warnings=warnings,
        )

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """빈 결과 생성."""
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index if not df.empty else pd.RangeIndex(0)),
            rule_flags=[],
            details=pd.DataFrame(index=df.index if not df.empty else pd.RangeIndex(0)),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
