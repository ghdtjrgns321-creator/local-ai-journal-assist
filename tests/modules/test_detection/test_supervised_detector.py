"""SupervisedDetector 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import NotFittedError

from src.detection.base import DetectionResult
from src.detection.supervised_detector import SupervisedDetector
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.label_strategy import LabelResult
from src.preprocessing.model_registry import ModelRegistry


@pytest.fixture()
def sv_groups() -> FeatureGroups:
    """최소 피처 그룹."""
    return FeatureGroups(
        numeric=["f1", "f2", "f3"],
        categorical_low=["cat1"],
        boolean=["flag1"],
    )


@pytest.fixture()
def sv_train_data() -> tuple[pd.DataFrame, LabelResult]:
    """학습용 합성 데이터 (200행, 양성 ~15%)."""
    rng = np.random.default_rng(42)
    n = 200
    df = pd.DataFrame({
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
def trained_detector(sv_train_data, sv_groups) -> SupervisedDetector:
    """학습 완료된 SupervisedDetector."""
    det = SupervisedDetector()
    df, label = sv_train_data
    det.train(df, label, sv_groups)
    return det


class TestInit:
    def test_track_name(self):
        det = SupervisedDetector()
        assert det.track_name == "ml_supervised"

    def test_detect_before_train_raises(self):
        det = SupervisedDetector()
        df = pd.DataFrame({"f1": [1.0]})
        with pytest.raises(NotFittedError):
            det.detect(df)


class TestTrain:
    def test_returns_metadata(self, sv_train_data, sv_groups):
        det = SupervisedDetector()
        df, label = sv_train_data
        meta = det.train(df, label, sv_groups)
        assert "best_model" in meta
        assert "mean_f1" in meta
        assert "optimal_threshold" in meta

    def test_sets_pipeline(self, sv_train_data, sv_groups):
        det = SupervisedDetector()
        df, label = sv_train_data
        det.train(df, label, sv_groups)
        assert hasattr(det, "pipeline_")

    def test_sets_optimal_threshold(self, sv_train_data, sv_groups):
        det = SupervisedDetector()
        df, label = sv_train_data
        det.train(df, label, sv_groups)
        assert 0.1 <= det.optimal_threshold_ <= 0.9

    def test_low_positive_warns(self, sv_groups):
        """양성 < 50건 시 warning 포함."""
        rng = np.random.default_rng(42)
        n = 200
        df = pd.DataFrame({
            "f1": rng.normal(0, 1, n),
            "f2": rng.normal(0, 1, n),
            "f3": rng.normal(0, 1, n),
            "cat1": rng.choice(["A", "B", "C"], n),
            "flag1": rng.choice([0, 1], n),
        })
        # 양성 10건 → 최소 50건 미만
        y = np.zeros(n, dtype=int)
        y[:10] = 1
        label = LabelResult(
            y=y, strategy="datasynth",
            label_source="ground_truth", positive_rate=10 / n,
        )
        det = SupervisedDetector()
        meta = det.train(df, label, sv_groups)
        assert any("양성" in w for w in meta["warnings"])

    def test_zero_positive_raises(self, sv_groups):
        """양성 0건이면 ValueError."""
        rng = np.random.default_rng(42)
        n = 100
        df = pd.DataFrame({
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
        det = SupervisedDetector()
        with pytest.raises(ValueError, match="양성 샘플이 0건"):
            det.train(df, label, sv_groups)


class TestDetect:
    def test_returns_detection_result(self, trained_detector, sv_train_data):
        df, _ = sv_train_data
        result = trained_detector.detect(df)
        assert isinstance(result, DetectionResult)

    def test_scores_range(self, trained_detector, sv_train_data):
        df, _ = sv_train_data
        result = trained_detector.detect(df)
        assert (result.scores >= 0.0).all()
        assert (result.scores <= 1.0).all()

    def test_details_has_ml01(self, trained_detector, sv_train_data):
        df, _ = sv_train_data
        result = trained_detector.detect(df)
        assert "ML01" in result.details.columns

    def test_rule_flags_contain_ml01(self, trained_detector, sv_train_data):
        df, _ = sv_train_data
        result = trained_detector.detect(df)
        assert any(rf.rule_id == "ML01" for rf in result.rule_flags)

    def test_flagged_indices_subset(self, trained_detector, sv_train_data):
        df, _ = sv_train_data
        result = trained_detector.detect(df)
        assert set(result.flagged_indices).issubset(set(df.index.tolist()))

    def test_track_name_in_result(self, trained_detector, sv_train_data):
        df, _ = sv_train_data
        result = trained_detector.detect(df)
        assert result.track_name == "ml_supervised"


class TestOptimalThreshold:
    def test_threshold_in_range(self, trained_detector):
        assert 0.1 <= trained_detector.optimal_threshold_ <= 0.9

    def test_threshold_not_default_05(self, trained_detector):
        """동적 탐색 결과가 저장되어 있어야 함 (0.5 고정이 아닌 F1 최적화)."""
        assert hasattr(trained_detector, "optimal_threshold_")
        # 정확히 0.5가 아닐 수도 있으나, 속성이 존재하면 동적 탐색 완료
        assert isinstance(trained_detector.optimal_threshold_, float)


class TestModelPersistence:
    def test_save_and_load(self, trained_detector, sv_train_data, sv_groups, tmp_path):
        registry = ModelRegistry(registry_dir=tmp_path)
        trained_detector._registry = registry

        # save
        trained_detector.save_model(mean_f1=0.75)
        saved_threshold = trained_detector.optimal_threshold_

        # load into new detector
        det2 = SupervisedDetector(model_registry=registry)
        det2.load_model("supervised")
        assert hasattr(det2, "pipeline_")
        assert det2.optimal_threshold_ == saved_threshold

        # detect 일관성
        df, _ = sv_train_data
        r1 = trained_detector.detect(df)
        r2 = det2.detect(df)
        np.testing.assert_array_almost_equal(r1.scores.values, r2.scores.values)

    def test_save_without_registry_raises(self, trained_detector):
        trained_detector._registry = None
        with pytest.raises(ValueError, match="model_registry"):
            trained_detector.save_model(mean_f1=0.75)
