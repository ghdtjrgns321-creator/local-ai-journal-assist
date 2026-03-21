"""models.py Pydantic 스키마 검증 테스트."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.llm.models import (
    ColumnPreprocessing,
    EncoderStrategy,
    ImbalanceStrategy,
    ImputerStrategy,
    ModelGroupStrategy,
    OutlierStrategy,
    PreprocessingAdvice,
    ScalerStrategy,
)


# ── StrEnum 검증 ──


class TestStrEnums:
    """StrEnum 값이 sklearn 옵션과 정확히 대응하는지 검증."""

    def test_imputer_values(self):
        assert set(ImputerStrategy) == {
            "median", "mean", "most_frequent", "constant", "forward_fill", "drop",
        }

    def test_encoder_values(self):
        assert set(EncoderStrategy) == {
            "ordinal", "target", "onehot", "passthrough",
        }

    def test_scaler_values(self):
        assert set(ScalerStrategy) == {"standard", "minmax", "robust", "none"}

    def test_outlier_values(self):
        assert set(OutlierStrategy) == {"clip", "log", "remove", "none"}

    def test_imbalance_values(self):
        assert set(ImbalanceStrategy) == {"smote", "class_weight", "none"}

    def test_strenum_is_string(self):
        """StrEnum 값이 일반 문자열로 비교 가능한지 확인."""
        assert ImputerStrategy.MEDIAN == "median"
        assert ScalerStrategy.ROBUST == "robust"


# ── ModelGroupStrategy ──


class TestModelGroupStrategy:
    def test_defaults(self):
        mg = ModelGroupStrategy()
        assert mg.scaler == ScalerStrategy.NONE
        assert mg.outlier == OutlierStrategy.NONE

    def test_with_values(self):
        mg = ModelGroupStrategy(
            scaler="robust",
            scaler_reason="이상치 다수",
            outlier="log",
            outlier_reason="고왜도",
        )
        assert mg.scaler == ScalerStrategy.ROBUST
        assert mg.outlier == OutlierStrategy.LOG

    def test_invalid_scaler_raises(self):
        with pytest.raises(ValidationError, match="scaler"):
            ModelGroupStrategy(scaler="invalid_scaler")


# ── ColumnPreprocessing ──


class TestColumnPreprocessing:
    def test_minimal_valid(self):
        cp = ColumnPreprocessing(
            column="amount",
            dtype_group="numeric",
            imputer="median",
        )
        assert cp.encoder == EncoderStrategy.PASSTHROUGH
        assert cp.tree_model.scaler == ScalerStrategy.NONE

    def test_full_valid(self):
        cp = ColumnPreprocessing(
            column="gl_account",
            dtype_group="categorical",
            imputer="most_frequent",
            encoder="target",
            encoder_reason="고카디널리티",
            tree_model={"scaler": "none", "outlier": "none"},
            distance_model={"scaler": "standard", "outlier": "clip"},
        )
        assert cp.encoder == EncoderStrategy.TARGET
        assert cp.distance_model.scaler == ScalerStrategy.STANDARD

    def test_missing_required_column_raises(self):
        with pytest.raises(ValidationError, match="column"):
            ColumnPreprocessing(
                dtype_group="numeric",
                imputer="median",
            )

    def test_missing_required_imputer_raises(self):
        with pytest.raises(ValidationError, match="imputer"):
            ColumnPreprocessing(
                column="amount",
                dtype_group="numeric",
            )

    def test_invalid_imputer_raises(self):
        with pytest.raises(ValidationError, match="imputer"):
            ColumnPreprocessing(
                column="amount",
                dtype_group="numeric",
                imputer="unknown_strategy",
            )


# ── PreprocessingAdvice ──


class TestPreprocessingAdvice:
    def test_from_valid_dict(self, lm_valid_advice_dict):
        """유효한 JSON dict → Pydantic 파싱 성공."""
        advice = PreprocessingAdvice(**lm_valid_advice_dict)
        assert len(advice.columns) == 2
        assert advice.columns[0].imputer == ImputerStrategy.MEDIAN
        assert advice.columns[1].encoder == EncoderStrategy.TARGET
        assert advice.imbalance == ImbalanceStrategy.CLASS_WEIGHT
        assert advice.source == "llm"

    def test_from_json_string(self, lm_valid_advice_dict):
        """JSON 문자열 → dict → Pydantic 파싱 (LLM 응답 시뮬레이션)."""
        json_str = json.dumps(lm_valid_advice_dict, ensure_ascii=False)
        parsed = json.loads(json_str)
        advice = PreprocessingAdvice(**parsed)
        assert advice.columns[0].column == "debit_amount"

    def test_model_group_strategies(self, lm_valid_advice_dict):
        """tree_model/distance_model 분기 검증."""
        advice = PreprocessingAdvice(**lm_valid_advice_dict)
        debit = advice.columns[0]
        assert debit.tree_model.scaler == ScalerStrategy.NONE
        assert debit.distance_model.scaler == ScalerStrategy.ROBUST
        assert debit.distance_model.outlier == OutlierStrategy.LOG

    def test_defaults(self):
        """최소 필드만으로 생성 — 기본값 검증."""
        advice = PreprocessingAdvice(
            columns=[
                ColumnPreprocessing(
                    column="col_a",
                    dtype_group="numeric",
                    imputer="mean",
                ),
            ],
        )
        assert advice.imbalance == ImbalanceStrategy.NONE
        assert advice.general_notes == []
        assert advice.source == "llm"

    def test_empty_columns_valid(self):
        """빈 컬럼 리스트도 유효 (엣지 케이스)."""
        advice = PreprocessingAdvice(columns=[])
        assert len(advice.columns) == 0

    def test_invalid_imbalance_raises(self):
        with pytest.raises(ValidationError, match="imbalance"):
            PreprocessingAdvice(
                columns=[],
                imbalance="invalid_strategy",
            )

    def test_json_schema_generation(self):
        """model_json_schema()가 Ollama Structured Output용 스키마를 생성하는지 확인."""
        schema = PreprocessingAdvice.model_json_schema()
        assert "properties" in schema
        assert "columns" in schema["properties"]
        # StrEnum 값이 스키마에 포함되는지 확인
        col_schema = schema["$defs"]["ColumnPreprocessing"]
        assert "imputer" in col_schema["properties"]

    def test_roundtrip_serialization(self, lm_valid_advice_dict):
        """dict → Pydantic → JSON → dict 왕복 직렬화."""
        advice = PreprocessingAdvice(**lm_valid_advice_dict)
        json_str = advice.model_dump_json()
        restored = PreprocessingAdvice.model_validate_json(json_str)
        assert restored.columns[0].column == advice.columns[0].column
        assert restored.imbalance == advice.imbalance
