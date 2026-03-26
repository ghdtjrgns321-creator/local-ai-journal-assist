"""라벨 생성 전략 테스트 — datasynth / pseudo / hybrid."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.preprocessing.label_strategy import LabelResult, create_labels


class TestDataSynthStrategy:
    """DataSynth GT 라벨 생성 검증."""

    def test_creates_labels_from_is_fraud(self, pp_sample_df):
        result = create_labels(pp_sample_df, strategy="datasynth")
        assert isinstance(result, LabelResult)
        assert result.strategy == "datasynth"

    def test_positive_rate_calculated(self, pp_sample_df):
        result = create_labels(pp_sample_df, strategy="datasynth")
        assert 0.0 <= result.positive_rate <= 1.0

    def test_no_label_columns(self):
        df = pd.DataFrame({"amount": [100, 200, 300]})
        result = create_labels(df, strategy="datasynth")
        assert np.all(result.y == 0)


class TestPseudoStrategy:
    """Pseudo 라벨 (룰 기반 점수) 검증."""

    def test_creates_labels_from_scores(self, pp_sample_df):
        scores = np.random.default_rng(42).uniform(0, 1, len(pp_sample_df))
        result = create_labels(pp_sample_df, detection_scores=scores, strategy="pseudo")
        assert len(result.y) == len(pp_sample_df)

    def test_threshold_respected(self, pp_sample_df):
        scores = np.array([0.3, 0.5, 0.7, 0.9, 0.1])
        df = pp_sample_df.head(5)
        result = create_labels(df, detection_scores=scores, strategy="pseudo", threshold=0.5)
        np.testing.assert_array_equal(result.y, [0, 1, 1, 1, 0])

    def test_raises_without_scores(self, pp_sample_df):
        with pytest.raises(ValueError, match="detection_scores"):
            create_labels(pp_sample_df, strategy="pseudo")


class TestHybridStrategy:
    """Hybrid 전략 (DataSynth 우선 → pseudo 폴백) 검증."""

    def test_prefers_datasynth(self, pp_sample_df):
        result = create_labels(pp_sample_df, strategy="hybrid")
        assert result.strategy == "hybrid"
        # DataSynth 컬럼이 있으므로 ground_truth 소스 사용
        assert result.label_source == "ground_truth"

    def test_falls_back_to_pseudo(self):
        df = pd.DataFrame({"amount": [100, 200, 300]})
        scores = np.array([0.1, 0.6, 0.8])
        result = create_labels(df, detection_scores=scores, strategy="hybrid")
        assert result.label_source == "pseudo_fallback"

    def test_all_zero_when_nothing(self):
        df = pd.DataFrame({"amount": [100, 200, 300]})
        result = create_labels(df, strategy="hybrid")
        assert np.all(result.y == 0)
        assert result.label_source == "unsupervised"
