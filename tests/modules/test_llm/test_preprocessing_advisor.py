"""preprocessing_advisor.py 테스트 — advise, rule_based_fallback, to_pipeline_config."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.eda.models import ColumnProfile, EDAProfile
from src.llm.models import (
    EncoderStrategy,
    ImbalanceStrategy,
    ImputerStrategy,
    ModelGroupStrategy,
    OutlierStrategy,
    PreprocessingAdvice,
    ScalerStrategy,
)
from src.llm.preprocessing_advisor import PreprocessingAdvisor


# ── Fixtures ──


@pytest.fixture()
def lm_advisor() -> PreprocessingAdvisor:
    """mock client로 PreprocessingAdvisor 생성."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = False
    return PreprocessingAdvisor(client=mock_client)


@pytest.fixture()
def lm_high_skew_profile() -> EDAProfile:
    """고왜도 수치형 + 고카디널리티 범주형 프로파일."""
    return EDAProfile(
        total_rows=10_000,
        total_columns=2,
        memory_bytes=160_000,
        duplicate_rows=0,
        columns={
            "amount": ColumnProfile(
                name="amount",
                dtype="float64",
                dtype_group="numeric",
                missing_rate=0.05,
                unique_count=8000,
                skewness=5.0,
                kurtosis=30.0,
                mean=1e6,
                median=5e5,
                std=2e6,
                q1=1e5,
                q3=1e6,
                iqr=9e5,
                outlier_count=1200,  # 12% outlier_rate
                min_val=0.0,
                max_val=1e9,
            ),
            "account": ColumnProfile(
                name="account",
                dtype="object",
                dtype_group="categorical",
                missing_rate=0.0,
                unique_count=200,
                cardinality=200,  # > 50 threshold
                top_values=[("4100", 500)],
            ),
        },
    )


@pytest.fixture()
def lm_low_skew_profile() -> EDAProfile:
    """저왜도 수치형 + 저카디널리티 범주형 프로파일."""
    return EDAProfile(
        total_rows=1000,
        total_columns=2,
        memory_bytes=16_000,
        duplicate_rows=0,
        columns={
            "score": ColumnProfile(
                name="score",
                dtype="float64",
                dtype_group="numeric",
                missing_rate=0.01,
                unique_count=500,
                skewness=0.3,
                kurtosis=2.5,
                mean=50.0,
                median=48.0,
                std=10.0,
                q1=42.0,
                q3=58.0,
                iqr=16.0,
                outlier_count=5,  # 0.5% outlier_rate
                min_val=10.0,
                max_val=95.0,
            ),
            "category": ColumnProfile(
                name="category",
                dtype="object",
                dtype_group="categorical",
                missing_rate=0.0,
                unique_count=5,
                cardinality=5,  # < 50 threshold
                top_values=[("A", 300), ("B", 250)],
            ),
        },
    )


# ── rule_based_fallback ──


class TestRuleBasedFallback:
    def test_high_skew_uses_median(self, lm_advisor, lm_high_skew_profile):
        """고왜도(5.0 > 2.0) → imputer=median."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        amount_col = next(c for c in advice.columns if c.column == "amount")
        assert amount_col.imputer == ImputerStrategy.MEDIAN

    def test_low_skew_uses_mean(self, lm_advisor, lm_low_skew_profile):
        """저왜도(0.3 < 2.0) → imputer=mean."""
        advice = lm_advisor.rule_based_fallback(lm_low_skew_profile)
        score_col = next(c for c in advice.columns if c.column == "score")
        assert score_col.imputer == ImputerStrategy.MEAN

    def test_high_cardinality_uses_target(self, lm_advisor, lm_high_skew_profile):
        """고카디널리티(200 > 50) → encoder=target."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        account_col = next(c for c in advice.columns if c.column == "account")
        assert account_col.encoder == EncoderStrategy.TARGET

    def test_low_cardinality_uses_ordinal(self, lm_advisor, lm_low_skew_profile):
        """저카디널리티(5 < 50) → encoder=ordinal."""
        advice = lm_advisor.rule_based_fallback(lm_low_skew_profile)
        cat_col = next(c for c in advice.columns if c.column == "category")
        assert cat_col.encoder == EncoderStrategy.ORDINAL

    def test_tree_model_no_scaling(self, lm_advisor, lm_high_skew_profile):
        """tree_model은 항상 scaler=none, outlier=none."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        amount_col = next(c for c in advice.columns if c.column == "amount")
        assert amount_col.tree_model.scaler == ScalerStrategy.NONE
        assert amount_col.tree_model.outlier == OutlierStrategy.NONE

    def test_distance_model_robust_for_outliers(self, lm_advisor, lm_high_skew_profile):
        """이상치 12% > 10% → distance_model.scaler=robust."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        amount_col = next(c for c in advice.columns if c.column == "amount")
        assert amount_col.distance_model.scaler == ScalerStrategy.ROBUST

    def test_distance_model_standard_for_clean(self, lm_advisor, lm_low_skew_profile):
        """이상치 0.5% < 10% → distance_model.scaler=standard."""
        advice = lm_advisor.rule_based_fallback(lm_low_skew_profile)
        score_col = next(c for c in advice.columns if c.column == "score")
        assert score_col.distance_model.scaler == ScalerStrategy.STANDARD

    def test_high_skew_log_outlier(self, lm_advisor, lm_high_skew_profile):
        """|skewness|=5.0 > 3.0 → distance_model.outlier=log."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        amount_col = next(c for c in advice.columns if c.column == "amount")
        assert amount_col.distance_model.outlier == OutlierStrategy.LOG

    def test_source_is_rule_based(self, lm_advisor, lm_high_skew_profile):
        """폴백 결과의 source는 'rule_based'."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        assert advice.source == "rule_based"

    def test_datetime_column_forward_fill(self, lm_advisor):
        """datetime 컬럼 → imputer=forward_fill."""
        profile = EDAProfile(
            total_rows=100,
            total_columns=1,
            memory_bytes=800,
            duplicate_rows=0,
            columns={
                "date": ColumnProfile(
                    name="date",
                    dtype="datetime64[ns]",
                    dtype_group="datetime",
                    missing_rate=0.05,
                    unique_count=30,
                    min_date="2025-01-01",
                    max_date="2025-01-30",
                    date_range_days=29,
                ),
            },
        )
        advice = lm_advisor.rule_based_fallback(profile)
        date_col = next(c for c in advice.columns if c.column == "date")
        assert date_col.imputer == ImputerStrategy.FORWARD_FILL
        assert date_col.encoder == EncoderStrategy.PASSTHROUGH

    def test_categorical_not_numeric_no_scaling(self, lm_advisor, lm_high_skew_profile):
        """범주형 컬럼 — distance_model에서도 scaler=none."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        account_col = next(c for c in advice.columns if c.column == "account")
        assert account_col.distance_model.scaler == ScalerStrategy.NONE


# ── advise (LLM mock) ──


class TestAdvise:
    def test_advise_llm_unavailable_falls_back(self, lm_high_skew_profile):
        """LLM 미실행 → rule_based_fallback."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        advisor = PreprocessingAdvisor(client=mock_client)

        advice = advisor.advise(lm_high_skew_profile)
        assert advice.source == "rule_based"
        mock_client.chat.assert_not_called()

    def test_advise_llm_success(self, lm_high_skew_profile, lm_valid_advice_dict):
        """LLM 정상 응답 → source='llm'."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.chat.return_value = json.dumps(lm_valid_advice_dict)
        advisor = PreprocessingAdvisor(client=mock_client)

        advice = advisor.advise(lm_high_skew_profile)
        assert advice.source == "llm"
        assert len(advice.columns) == 2

    def test_advise_llm_parse_failure_retries(self, lm_high_skew_profile):
        """LLM 파싱 실패 → 재시도 후 폴백."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.chat.return_value = "invalid json {"
        advisor = PreprocessingAdvisor(client=mock_client)

        advice = advisor.advise(lm_high_skew_profile)
        assert advice.source == "rule_based"
        # 2회 호출 (원본 + 1회 재시도)
        assert mock_client.chat.call_count == 2

    def test_advise_passes_schema_format(self, lm_high_skew_profile, lm_valid_advice_dict):
        """Structured Output — format에 JSON Schema 전달 확인."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.chat.return_value = json.dumps(lm_valid_advice_dict)
        advisor = PreprocessingAdvisor(client=mock_client)

        advisor.advise(lm_high_skew_profile)

        call_kwargs = mock_client.chat.call_args
        format_arg = call_kwargs.kwargs.get("format")
        assert isinstance(format_arg, dict)
        assert "properties" in format_arg


# ── to_pipeline_config ──


class TestToPipelineConfig:
    def test_tree_config(self, lm_advisor, lm_high_skew_profile):
        """tree 모델 그룹 config — scaler=none."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        config = lm_advisor.to_pipeline_config(advice, model_group="tree")

        assert "amount" in config["numeric_cols"]
        assert "account" in config["categorical_cols"]
        assert config["scalers"]["amount"] == "none"
        assert config["model_group"] == "tree"

    def test_distance_config(self, lm_advisor, lm_high_skew_profile):
        """distance 모델 그룹 config — scaler=robust (이상치 많음)."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        config = lm_advisor.to_pipeline_config(advice, model_group="distance")

        assert config["scalers"]["amount"] == "robust"
        assert config["outlier_strategies"]["amount"] == "log"
        assert config["model_group"] == "distance"

    def test_config_has_all_keys(self, lm_advisor, lm_high_skew_profile):
        """Pipeline config에 필수 키 모두 존재."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        config = lm_advisor.to_pipeline_config(advice)

        required_keys = {
            "numeric_cols", "categorical_cols", "datetime_cols", "boolean_cols",
            "imputers", "encoders", "scalers", "outlier_strategies",
            "imbalance", "model_group", "source",
        }
        assert required_keys.issubset(config.keys())

    def test_imbalance_in_config(self, lm_advisor, lm_high_skew_profile):
        """imbalance 전략이 config에 반영."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        config = lm_advisor.to_pipeline_config(advice)
        assert config["imbalance"] == "class_weight"

    def test_encoders_in_config(self, lm_advisor, lm_high_skew_profile):
        """인코더 매핑이 올바른지 확인."""
        advice = lm_advisor.rule_based_fallback(lm_high_skew_profile)
        config = lm_advisor.to_pipeline_config(advice)
        assert config["encoders"]["account"] == "target"
        assert config["encoders"]["amount"] == "passthrough"
