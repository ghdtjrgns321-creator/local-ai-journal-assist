"""Benford 독립 트랙 — DETECTION_RULES.md §2.3 Benford 독립 트랙 가중치 0.15.

Why: Benford는 전체 분포 검정이라 행별 룰(L3-04~L4-04)과 성격이 다르다.
     Layer C 내부가 아닌 독립 트랙으로 분리하여 score_aggregator가
     LAYER_WEIGHTS[Layer.BENFORD] = 0.15를 별도 적용할 수 있게 한다.
     L4-02 행별 선별 로직 + deviation 비례 스코어는 anomaly_rules_statistical.py를 재사용.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.detection.anomaly_rules_statistical import c07_benford_violation
from src.detection.base import BaseDetector, validate_input

if TYPE_CHECKING:
    from src.detection.base import DetectionResult


_RULE_ID = "L4-02"


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

        # Why: c07_benford_violation이 이미 deviation 비례 [0, 0.8] 점수를 반환하므로
        #      여기서 추가 가중 없이 그대로 사용 (이전 0.4 고정값 → 차등화 완료)
        scores = scores.astype(float)
        flagged_indices = scores[scores > 0].index.tolist()

        rule_flags = [
            self._create_rule_flag(
                rule_id=_RULE_ID,
                flagged_count=int((scores > 0).sum()),
                total_count=len(df),
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
