"""base.py 단위 테스트 — validate_input, RuleFlag, DetectionResult."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag, validate_input


class TestValidateInput:
    """validate_input 함수 테스트."""

    def test_empty_df_raises(self):
        """빈 DataFrame → ValueError."""
        df = pd.DataFrame()
        with pytest.raises(ValueError, match="비어"):
            validate_input(df, ["col_a"])

    def test_returns_missing_columns(self):
        """존재하지 않는 컬럼을 리스트로 반환."""
        df = pd.DataFrame({"a": [1], "b": [2]})
        missing = validate_input(df, ["a", "c", "d"])
        assert set(missing) == {"c", "d"}

    def test_all_present_returns_empty(self):
        """모든 컬럼 존재 시 빈 리스트."""
        df = pd.DataFrame({"a": [1], "b": [2]})
        assert validate_input(df, ["a", "b"]) == []


class TestRuleFlag:
    """RuleFlag 프로퍼티 테스트."""

    def test_flag_rate_normal(self):
        """플래그 비율 계산."""
        flag = RuleFlag("A01", "차대변 균형", 5, flagged_count=10, total_count=100)
        assert flag.flag_rate == pytest.approx(0.1)

    def test_flag_rate_zero_total(self):
        """total_count=0 → 0.0 (ZeroDivisionError 방지)."""
        flag = RuleFlag("A01", "차대변 균형", 5, flagged_count=0, total_count=0)
        assert flag.flag_rate == 0.0


class TestDetectionResult:
    """DetectionResult 프로퍼티 테스트."""

    def test_flagged_count(self):
        """flagged_count 프로퍼티."""
        result = DetectionResult(
            track_name="layer_a",
            flagged_indices=[0, 2, 5],
            scores=pd.Series([1.0, 0.0, 1.0]),
            rule_flags=[],
            details=pd.DataFrame(),
            metadata={"elapsed": 0.01},
        )
        assert result.flagged_count == 3

    def test_elapsed_seconds(self):
        """elapsed_seconds 프로퍼티."""
        result = DetectionResult(
            track_name="layer_a",
            flagged_indices=[],
            scores=pd.Series(dtype=float),
            rule_flags=[],
            details=pd.DataFrame(),
            metadata={"elapsed": 0.123},
        )
        assert result.elapsed_seconds == pytest.approx(0.123)
