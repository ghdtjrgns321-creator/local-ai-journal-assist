"""BenfordDetector 독립 트랙 테스트."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.benford_detector import BenfordDetector


@pytest.fixture
def benford_df() -> pd.DataFrame:
    """Benford 테스트용 DataFrame — 300행, Benford 적합 분포."""
    n = 300
    digits = []
    for d in range(1, 10):
        count = round(n * math.log10(1 + 1 / d))
        digits.extend([d] * count)
    while len(digits) < n:
        digits.append(1)
    return pd.DataFrame({
        "first_digit": pd.array(digits[:n], dtype=pd.Int64Dtype()),
        "debit_amount": [100.0] * n,
        "credit_amount": [0.0] * n,
    })


class TestBenfordDetector:
    def test_track_name(self) -> None:
        assert BenfordDetector().track_name == "benford"

    def test_returns_detection_result(self, benford_df: pd.DataFrame) -> None:
        result = BenfordDetector().detect(benford_df)
        assert isinstance(result, DetectionResult)
        assert result.track_name == "benford"

    def test_scores_range(self, benford_df: pd.DataFrame) -> None:
        result = BenfordDetector().detect(benford_df)
        assert result.scores.min() >= 0.0
        assert result.scores.max() <= 1.0

    def test_conforming_all_zero(self, benford_df: pd.DataFrame) -> None:
        """Benford 적합 → 전체 0점."""
        result = BenfordDetector().detect(benford_df)
        assert (result.scores == 0.0).all()

    def test_benford_result_in_metadata(self, benford_df: pd.DataFrame) -> None:
        """benford_result가 metadata에 포함."""
        result = BenfordDetector().detect(benford_df)
        assert "benford_result" in result.metadata

    def test_rule_flags_c07(self, benford_df: pd.DataFrame) -> None:
        """rule_flags에 C07 포함."""
        result = BenfordDetector().detect(benford_df)
        assert len(result.rule_flags) == 1
        assert result.rule_flags[0].rule_id == "C07"

    def test_missing_first_digit_graceful(self) -> None:
        """first_digit 미존재 → 0점."""
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        result = BenfordDetector().detect(df)
        assert (result.scores == 0.0).all()

    def test_empty_df_raises(self) -> None:
        """빈 DataFrame → ValueError."""
        df = pd.DataFrame({"debit_amount": pd.Series(dtype=float),
                           "credit_amount": pd.Series(dtype=float)})
        with pytest.raises(ValueError):
            BenfordDetector().detect(df)
