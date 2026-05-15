"""base.py 단위 테스트 — validate_input, RuleFlag, DetectionResult, BaseDetector."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.detection.base import (
    BaseDetector,
    DetectionResult,
    RuleFlag,
    validate_input,
)
from src.detection.constants import Layer

# ── validate_input ───────────────────────────────────────────


class TestValidateInput:
    """validate_input() 유틸 함수 검증."""

    def test_empty_dataframe_raises(self) -> None:
        df = pd.DataFrame()
        with pytest.raises(ValueError, match="비어 있습니다"):
            validate_input(df, ["col_a"])

    def test_missing_columns_returned(self) -> None:
        df = pd.DataFrame({"a": [1], "b": [2]})
        missing = validate_input(df, ["a", "c", "d"])
        assert missing == ["c", "d"]

    def test_all_present_returns_empty(self) -> None:
        df = pd.DataFrame({"x": [1], "y": [2]})
        assert validate_input(df, ["x", "y"]) == []

    def test_empty_required_returns_empty(self) -> None:
        df = pd.DataFrame({"a": [1]})
        assert validate_input(df, []) == []


# ── RuleFlag ─────────────────────────────────────────────────


class TestRuleFlag:
    """RuleFlag dataclass 검증."""

    def test_creation(self) -> None:
        flag = RuleFlag(
            rule_id="L1-01",
            rule_name="차대변 균형",
            severity=5,
            flagged_count=3,
            total_count=100,
        )
        assert flag.rule_id == "L1-01"
        assert flag.severity == 5

    def test_flag_rate(self) -> None:
        flag = RuleFlag("L2-01", "승인한도 직하", 3, 25, 100)
        assert flag.flag_rate == pytest.approx(0.25)

    def test_flag_rate_zero_total(self) -> None:
        flag = RuleFlag("L3-08", "위험 적요", 1, 0, 0)
        assert flag.flag_rate == 0.0

    def test_detail_default_none(self) -> None:
        flag = RuleFlag("L1-02", "필수필드 누락", 2, 1, 10)
        assert flag.detail is None

    def test_detail_custom(self) -> None:
        flag = RuleFlag("L1-03", "무효 계정", 3, 5, 50, detail="CoA 미제공")
        assert flag.detail == "CoA 미제공"

    def test_negative_flagged_count_raises(self) -> None:
        with pytest.raises(ValueError, match="음수"):
            RuleFlag("L1-01", "차대변 균형", 5, -1, 10)

    def test_flagged_exceeds_total_raises(self) -> None:
        with pytest.raises(ValueError, match="초과"):
            RuleFlag("L1-01", "차대변 균형", 5, 11, 10)


# ── DetectionResult ──────────────────────────────────────────


class TestDetectionResult:
    """DetectionResult dataclass + 편의 프로퍼티 검증."""

    @pytest.fixture
    def sample_result(self) -> DetectionResult:
        return DetectionResult(
            track_name="layer_a",
            flagged_indices=[0, 3, 7],
            scores=pd.Series([0.5, 0.0, 0.0, 0.8, 0.0, 0.0, 0.0, 0.3]),
            rule_flags=[
                RuleFlag("L1-01", "차대변 균형", 5, 2, 8),
                RuleFlag("L1-02", "필수필드 누락", 2, 1, 8),
            ],
            details=pd.DataFrame(
                {"L1-01": [1.0, 0, 0, 1.0, 0, 0, 0, 0], "L1-02": [0, 0, 0, 0, 0, 0, 0, 0.4]},
            ),
            metadata={"elapsed": 0.123, "skipped_rules": []},
        )

    def test_elapsed_seconds(self, sample_result: DetectionResult) -> None:
        assert sample_result.elapsed_seconds == pytest.approx(0.123)

    def test_elapsed_seconds_missing_key(self) -> None:
        result = DetectionResult(
            track_name="layer_b",
            flagged_indices=[],
            scores=pd.Series(dtype=float),
            rule_flags=[],
            details=pd.DataFrame(),
            metadata={},
        )
        assert result.elapsed_seconds == 0.0

    def test_flagged_count(self, sample_result: DetectionResult) -> None:
        assert sample_result.flagged_count == 3

    def test_total_rules_run(self, sample_result: DetectionResult) -> None:
        assert sample_result.total_rules_run == 2

    def test_warnings_default_empty(self, sample_result: DetectionResult) -> None:
        assert sample_result.warnings == []


# ── BaseDetector ─────────────────────────────────────────────


class _StubDetector(BaseDetector):
    """테스트용 구현체."""

    @property
    def track_name(self) -> str:
        return Layer.LAYER_A

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index),
            rule_flags=[],
            details=pd.DataFrame(index=df.index),
            metadata={"elapsed": 0.0},
            warnings=[],
        )


class TestBaseDetector:
    """BaseDetector ABC 검증."""

    def test_abstract_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            BaseDetector()  # type: ignore[abstract]

    def test_stub_instantiates(self) -> None:
        detector = _StubDetector()
        assert detector.track_name == "layer_a"

    def test_stub_detect_returns_result(self) -> None:
        detector = _StubDetector()
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = detector.detect(df)
        assert isinstance(result, DetectionResult)
        assert result.track_name == "layer_a"

    def test_make_result_numpy_int_defense(self) -> None:
        """numpy.int64 인덱스가 순수 Python int로 변환되는지 확인."""
        detector = _StubDetector()
        np_indices = [np.int64(0), np.int64(5), np.int64(99)]
        result = detector._make_result(
            flagged_indices=np_indices,
            scores=pd.Series(dtype=float),
            rule_flags=[],
            details=pd.DataFrame(),
            metadata={"elapsed": 0.0},
            warnings=[],
        )
        for idx in result.flagged_indices:
            assert type(idx) is int  # noqa: E721 — 정확한 타입 검사 의도

    def test_create_rule_flag(self) -> None:
        detector = _StubDetector()
        flag = detector._create_rule_flag("L1-06", 10, 200, detail="테스트")
        assert flag.rule_id == "L1-06"
        assert flag.rule_name == "Segregation of Duties Violation"
        assert flag.severity == 4
        assert flag.flagged_count == 10
        assert flag.detail == "테스트"

    def test_create_rule_flag_invalid_id_raises(self) -> None:
        detector = _StubDetector()
        with pytest.raises(ValueError, match="알 수 없는 rule_id.*Z99"):
            detector._create_rule_flag("Z99", 0, 0)

    def test_settings_injection(self) -> None:
        """settings=None이면 기본 get_settings() 사용."""
        detector = _StubDetector()
        assert detector._settings is not None
