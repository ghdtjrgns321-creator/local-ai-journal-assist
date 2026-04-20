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
        with pytest.raises(ValueError, match="empty"):
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
        flag = RuleFlag("L1-01", "차대변 균형", 5, flagged_count=10, total_count=100)
        assert flag.flag_rate == pytest.approx(0.1)

    def test_flag_rate_zero_total(self):
        """total_count=0 → 0.0 (ZeroDivisionError 방지)."""
        flag = RuleFlag("L1-01", "차대변 균형", 5, flagged_count=0, total_count=0)
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

    def test_detector_profile_fallback(self):
        """등록된 track_name이면 운영 메타를 기본값으로 읽는다."""
        result = DetectionResult(
            track_name="layer_a",
            flagged_indices=[],
            scores=pd.Series(dtype=float),
            rule_flags=[],
            details=pd.DataFrame(),
            metadata={"elapsed": 0.01},
        )
        assert result.display_name == "L1"
        assert result.maturity == "production"
        assert result.default_enabled is True
        assert result.activation_requirements == []
        assert "structural integrity" in result.explanation_summary
        assert "debit_amount" in result.used_columns
        assert result.references == []

    def test_metadata_can_override_profile_defaults(self):
        """metadata에 명시된 운영 상태 값이 우선한다."""
        result = DetectionResult(
            track_name="nlp",
            flagged_indices=[],
            scores=pd.Series(dtype=float),
            rule_flags=[],
            details=pd.DataFrame(),
            metadata={
                "elapsed": 0.01,
                "display_name": "NLP Custom",
                "maturity": "experimental",
                "default_enabled": False,
                "activation_requirements": ["external_api"],
                "run_status": "skipped",
                "skip_reason": "disabled_by_settings",
                "explanation_summary": "사용자 정의 설명",
                "used_columns": ["line_text"],
                "references": ["커스텀 근거"],
            },
        )
        assert result.display_name == "NLP Custom"
        assert result.maturity == "experimental"
        assert result.default_enabled is False
        assert result.activation_requirements == ["external_api"]
        assert result.run_status == "skipped"
        assert result.skip_reason == "disabled_by_settings"
        assert result.explanation_summary == "사용자 정의 설명"
        assert result.used_columns == ["line_text"]
        assert result.references == ["커스텀 근거"]
