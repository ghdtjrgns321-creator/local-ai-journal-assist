"""TransformerDetector 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import NotFittedError

from src.detection.base import DetectionResult
from src.detection.constants import RULE_CODES, SEVERITY_MAP
from src.detection.tabular_transformer import TransformerDetector
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.label_strategy import LabelResult
from src.preprocessing.model_registry import ModelRegistry


@pytest.fixture()
def ft_groups() -> FeatureGroups:
    """최소 피처 그룹."""
    return FeatureGroups(
        numeric=["f1", "f2", "f3"],
        categorical_low=["cat1"],
        boolean=["flag1"],
    )


@pytest.fixture()
def ft_train_data() -> tuple[pd.DataFrame, LabelResult]:
    """학습용 합성 데이터 (200행, 양성 ~15%)."""
    rng = np.random.default_rng(42)
    n = 200
    df = pd.DataFrame({
        "document_id": [f"D2022_{i}" for i in range(n // 2)] + [f"D2023_{i}" for i in range(n // 4)] + [f"D2024_{i}" for i in range(n // 4)],
        "fiscal_year": ([2022] * (n // 2)) + ([2023] * (n // 4)) + ([2024] * (n // 4)),
        "f1": rng.normal(0, 1, n),
        "f2": rng.normal(0, 1, n),
        "f3": rng.normal(0, 1, n),
        "cat1": rng.choice(["A", "B", "C"], n),
        "flag1": rng.choice([0, 1], n),
    })
    y = rng.choice([0, 1], n, p=[0.85, 0.15])
    label = LabelResult(
        y=y,
        strategy="datasynth",
        label_source="ground_truth",
        positive_rate=float(y.mean()),
    )
    return df, label


@pytest.fixture()
def trained_detector(ft_train_data, ft_groups) -> TransformerDetector:
    """학습 완료된 TransformerDetector (경량 하이퍼파라미터)."""
    from config.settings import AuditSettings

    # Why: CI 환경에서 빠르게 통과하도록 경량 설정
    settings = AuditSettings(
        ft_d_token=16, ft_n_layers=1, ft_n_heads=2, ft_d_ff=32,
        ft_epochs=2, ft_batch_size=32, ft_lr=1e-3,
    )
    det = TransformerDetector(settings=settings)
    df, label = ft_train_data
    det.train(df, label, ft_groups)
    return det


class TestInit:
    def test_track_name(self):
        det = TransformerDetector()
        assert det.track_name == "ml_transformer"

    def test_detect_before_train_raises(self):
        det = TransformerDetector()
        df = pd.DataFrame({"f1": [1.0]})
        with pytest.raises(NotFittedError):
            det.detect(df)


class TestTrain:
    def test_returns_metadata(self, ft_train_data, ft_groups):
        from config.settings import AuditSettings

        settings = AuditSettings(
            ft_d_token=16, ft_n_layers=1, ft_n_heads=2, ft_d_ff=32,
            ft_epochs=2, ft_batch_size=32,
        )
        det = TransformerDetector(settings=settings)
        df, label = ft_train_data
        meta = det.train(df, label, ft_groups)
        assert "optimal_threshold" in meta
        assert "n_train" in meta
        assert "n_val" in meta

    def test_sets_pipeline(self, trained_detector):
        assert hasattr(trained_detector, "pipeline_")

    def test_sets_optimal_threshold(self, trained_detector):
        assert 0.1 <= trained_detector.optimal_threshold_ <= 0.9

    def test_zero_positive_raises(self, ft_groups):
        """양성 0건이면 ValueError."""
        rng = np.random.default_rng(42)
        n = 100
        df = pd.DataFrame({
            "document_id": [f"D2022_{i}" for i in range(n // 2)] + [f"D2023_{i}" for i in range(n // 4)] + [f"D2024_{i}" for i in range(n // 4)],
            "fiscal_year": ([2022] * (n // 2)) + ([2023] * (n // 4)) + ([2024] * (n // 4)),
            "f1": rng.normal(0, 1, n),
            "f2": rng.normal(0, 1, n),
            "f3": rng.normal(0, 1, n),
            "cat1": rng.choice(["A", "B", "C"], n),
            "flag1": rng.choice([0, 1], n),
        })
        y = np.zeros(n, dtype=int)
        label = LabelResult(
            y=y, strategy="datasynth",
            label_source="ground_truth", positive_rate=0.0,
        )
        det = TransformerDetector()
        with pytest.raises(ValueError, match="양성 샘플이 0건"):
            det.train(df, label, ft_groups)


class TestDetect:
    def test_returns_detection_result(self, trained_detector, ft_train_data):
        df, _ = ft_train_data
        result = trained_detector.detect(df)
        assert isinstance(result, DetectionResult)

    def test_scores_range(self, trained_detector, ft_train_data):
        df, _ = ft_train_data
        result = trained_detector.detect(df)
        assert (result.scores >= 0.0).all()
        assert (result.scores <= 1.0).all()

    def test_details_has_ml03(self, trained_detector, ft_train_data):
        df, _ = ft_train_data
        result = trained_detector.detect(df)
        assert "ML03" in result.details.columns

    def test_rule_flags_contain_ml03(self, trained_detector, ft_train_data):
        df, _ = ft_train_data
        result = trained_detector.detect(df)
        assert any(rf.rule_id == "ML03" for rf in result.rule_flags)

    def test_flagged_indices_subset(self, trained_detector, ft_train_data):
        df, _ = ft_train_data
        result = trained_detector.detect(df)
        assert set(result.flagged_indices).issubset(set(df.index.tolist()))

    def test_track_name_in_result(self, trained_detector, ft_train_data):
        df, _ = ft_train_data
        result = trained_detector.detect(df)
        assert result.track_name == "ml_transformer"


class TestModelPersistence:
    def test_save_and_load(self, trained_detector, ft_train_data, tmp_path):
        registry = ModelRegistry(registry_dir=tmp_path)
        trained_detector._registry = registry

        trained_detector.save_model(mean_f1=0.75)
        saved_threshold = trained_detector.optimal_threshold_

        det2 = TransformerDetector(model_registry=registry)
        det2.load_model("ft_transformer")
        assert hasattr(det2, "pipeline_")
        assert det2.optimal_threshold_ == saved_threshold

    def test_save_without_registry_raises(self, trained_detector):
        trained_detector._registry = None
        with pytest.raises(ValueError, match="model_registry"):
            trained_detector.save_model(mean_f1=0.75)


class TestConstants:
    def test_ml03_in_rule_codes(self):
        assert "ML03" in RULE_CODES

    def test_ml03_in_severity_map(self):
        assert "ML03" in SEVERITY_MAP
        assert SEVERITY_MAP["ML03"] == 4
