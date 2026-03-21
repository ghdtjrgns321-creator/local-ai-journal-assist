"""label_strategy 테스트 — 3가지 라벨 전략."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.preprocessing.label_strategy import create_labels


class TestDataSynthStrategy:
    """datasynth 전략 검증."""

    def test_creates_labels_from_is_fraud(self, sample_df):
        """is_fraud 컬럼에서 라벨 생성."""
        result = create_labels(sample_df, strategy="datasynth")
        assert len(result.y) == len(sample_df)
        assert result.label_source == "datasynth"
        assert "is_fraud" in result.source_breakdown

    def test_positive_rate_calculated(self, sample_df):
        """양성률이 0~1 범위인지."""
        result = create_labels(sample_df, strategy="datasynth")
        assert 0.0 <= result.positive_rate <= 1.0

    def test_no_label_columns(self):
        """레이블 컬럼이 없으면 전체 0."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = create_labels(df, strategy="datasynth")
        assert result.y.sum() == 0


class TestPseudoStrategy:
    """pseudo 전략 검증."""

    def test_creates_labels_from_scores(self, sample_df):
        """detection_scores에서 라벨 생성."""
        scores = pd.Series(np.random.default_rng(42).uniform(0, 1, size=len(sample_df)))
        result = create_labels(sample_df, detection_scores=scores, strategy="pseudo")
        assert len(result.y) == len(sample_df)
        assert result.label_source == "pseudo"

    def test_threshold_respected(self, sample_df):
        """threshold 이상이 양성인지."""
        scores = pd.Series([0.3, 0.7, 0.5, 0.9])
        df = sample_df.head(4)
        result = create_labels(df, detection_scores=scores, strategy="pseudo", pseudo_threshold=0.5)
        assert result.y.tolist() == [0, 1, 1, 1]

    def test_raises_without_scores(self, sample_df):
        """detection_scores 없이 pseudo 전략이면 에러."""
        with pytest.raises(ValueError, match="detection_scores"):
            create_labels(sample_df, strategy="pseudo")


class TestHybridStrategy:
    """hybrid 전략 검증."""

    def test_prefers_datasynth(self, sample_df):
        """DataSynth 컬럼이 있으면 우선 사용."""
        result = create_labels(sample_df, strategy="hybrid")
        assert result.label_source == "hybrid"
        assert result.positive_rate > 0

    def test_falls_back_to_pseudo(self):
        """DataSynth 없으면 pseudo 폴백."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        scores = pd.Series([0.1, 0.8, 0.3])
        result = create_labels(df, detection_scores=scores, strategy="hybrid")
        assert result.label_source == "hybrid"

    def test_all_zero_when_nothing(self):
        """양쪽 모두 없으면 전체 정상."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = create_labels(df, strategy="hybrid")
        assert result.y.sum() == 0
