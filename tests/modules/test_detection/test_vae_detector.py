"""UnsupervisedDetector (VAE + IF 앙상블) 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import NotFittedError

from src.detection.base import DetectionResult
from src.detection.constants import RULE_CODES, SEVERITY_MAP
from src.detection.vae_detector import UnsupervisedDetector
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.model_registry import ModelRegistry


@pytest.fixture()
def unsup_groups() -> FeatureGroups:
    """최소 피처 그룹 (수치형 5개)."""
    return FeatureGroups(numeric=["f1", "f2", "f3", "f4", "f5"])


@pytest.fixture()
def unsup_train_data() -> tuple[pd.DataFrame, np.ndarray]:
    """학습용 합성 데이터 (300행, 양성 ~2%)."""
    rng = np.random.default_rng(42)
    n = 300
    df = pd.DataFrame({f"f{i}": rng.normal(0, 1, n) for i in range(1, 6)})
    y = np.zeros(n, dtype=int)
    y[rng.choice(n, int(n * 0.02), replace=False)] = 1
    return df, y


@pytest.fixture()
def trained_detector(
    unsup_train_data, unsup_groups,
) -> UnsupervisedDetector:
    """학습 완료된 UnsupervisedDetector (epochs=3으로 속도 확보)."""
    det = UnsupervisedDetector()
    df, y = unsup_train_data
    det.train(df, unsup_groups, y=y)
    return det


class TestInit:
    def test_track_name(self):
        det = UnsupervisedDetector()
        assert det.track_name == "ml_unsupervised"

    def test_detect_before_train_raises(self):
        det = UnsupervisedDetector()
        df = pd.DataFrame({"f1": [1.0]})
        with pytest.raises(NotFittedError):
            det.detect(df)


class TestTrain:
    def test_returns_metadata(self, unsup_train_data, unsup_groups):
        det = UnsupervisedDetector()
        df, y = unsup_train_data
        meta = det.train(df, unsup_groups, y=y)
        assert "ensemble_threshold" in meta
        assert "n_train_samples" in meta
        assert "n_features" in meta

    def test_sets_pipelines(self, trained_detector):
        assert hasattr(trained_detector, "vae_pipeline_")
        assert hasattr(trained_detector, "if_pipeline_")

    def test_sets_threshold(self, trained_detector):
        assert 0.0 <= trained_detector.threshold_ <= 1.0

    def test_stores_ecdf_distributions(self, trained_detector):
        """ECDF용 학습 분포 배열이 저장되어야 함."""
        assert hasattr(trained_detector, "vae_train_scores_")
        assert hasattr(trained_detector, "if_train_scores_")
        # 정렬되어 있어야 함
        assert np.all(np.diff(trained_detector.vae_train_scores_) >= 0)
        assert np.all(np.diff(trained_detector.if_train_scores_) >= 0)

    def test_trains_without_y(self, unsup_train_data, unsup_groups):
        """y=None 시 X 전체로 학습."""
        det = UnsupervisedDetector()
        df, _ = unsup_train_data
        meta = det.train(df, unsup_groups)
        assert meta["n_train_samples"] == len(df)

    def test_y_used_for_eval_only(self, unsup_train_data, unsup_groups):
        """y가 있어도 학습 데이터 = X 전체 (필터링 없음)."""
        det = UnsupervisedDetector()
        df, y = unsup_train_data
        meta = det.train(df, unsup_groups, y=y)
        # n_train_samples가 X 전체 행 수와 일치해야 함
        assert meta["n_train_samples"] == len(df)


class TestDetect:
    def test_returns_detection_result(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        assert isinstance(result, DetectionResult)

    def test_scores_range_0_to_1(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        assert (result.scores >= 0.0).all()
        assert (result.scores <= 1.0).all()

    def test_details_has_ml02(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        assert "ML02" in result.details.columns

    def test_rule_flags_contain_ml02(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        assert any(rf.rule_id == "ML02" for rf in result.rule_flags)

    def test_flagged_indices_subset(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        assert set(result.flagged_indices).issubset(set(df.index.tolist()))

    def test_track_name_in_result(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        assert result.track_name == "ml_unsupervised"


class TestExplainability:
    """피처별 재구성 오차 분해 — 감사조서 정량 증거 검증."""

    def test_details_has_topk_columns(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        for i in range(1, 4):  # _TOP_K_FEATURES = 3
            assert f"ML02_top_feature_{i}" in result.details.columns
            assert f"ML02_top_feature_{i}_contrib" in result.details.columns

    def test_topk_contrib_descending(self, trained_detector, unsup_train_data):
        # Why: top1 ≥ top2 ≥ top3 — 정렬 검증
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        c1 = result.details["ML02_top_feature_1_contrib"].values
        c2 = result.details["ML02_top_feature_2_contrib"].values
        c3 = result.details["ML02_top_feature_3_contrib"].values
        assert (c1 >= c2).all()
        assert (c2 >= c3).all()

    def test_topk_contrib_non_negative(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        for i in range(1, 4):
            col = result.details[f"ML02_top_feature_{i}_contrib"]
            assert (col >= 0).all()

    def test_topk_feature_names_valid(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        # Why: 피처명은 비어있으면 안 됨 (전처리기에서 정상 추출)
        col = result.details["ML02_top_feature_1"]
        assert col.notna().all()
        assert (col.astype(str).str.len() > 0).all()

    def test_score_vae_per_feature_shape(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        per_feature, names = trained_detector._score_vae_per_feature(df)
        assert per_feature.shape[0] == len(df)
        assert per_feature.shape[1] == len(names)
        assert len(names) > 0


class TestECDF:
    def test_ecdf_small_batch_no_false_alarm(self, trained_detector):
        """10건 정상 배치 → 모두 threshold 이하여야 함 (ECDF 안정성)."""
        rng = np.random.default_rng(99)
        small_df = pd.DataFrame(
            {f"f{i}": rng.normal(0, 0.5, 10) for i in range(1, 6)},
        )
        result = trained_detector.detect(small_df)
        # 정상 분포 중심(0,0.5)이므로 대부분 저점수 기대
        high_score_count = (result.scores > trained_detector.threshold_).sum()
        # 10건 중 과반이 플래그되면 오탐 (ECDF 없이 rankdata면 ~50% 오탐)
        assert high_score_count <= 5

    def test_ecdf_consistent_across_batch_size(self, trained_detector):
        """동일 데이터의 점수가 배치 크기 변경 시에도 동일."""
        rng = np.random.default_rng(77)
        df_large = pd.DataFrame(
            {f"f{i}": rng.normal(0, 1, 100) for i in range(1, 6)},
        )
        # 전체 100건 중 첫 10건의 점수
        result_large = trained_detector.detect(df_large)
        scores_from_large = result_large.scores.iloc[:10].values

        # 첫 10건만 별도 배치로 detect
        result_small = trained_detector.detect(df_large.iloc[:10])
        scores_from_small = result_small.scores.values

        np.testing.assert_array_almost_equal(
            scores_from_large, scores_from_small, decimal=5,
        )

    def test_ecdf_scores_bounded_0_1(self, trained_detector, unsup_train_data):
        df, _ = unsup_train_data
        result = trained_detector.detect(df)
        assert result.scores.min() >= 0.0
        assert result.scores.max() <= 1.0


class TestEnsemble:
    def test_combine_scores_equal_weight(self, trained_detector, unsup_train_data):
        """VAE와 IF 점수가 모두 앙상블에 기여 (상수가 아님)."""
        df, _ = unsup_train_data
        vae_raw = trained_detector._score_vae(df)
        if_raw = trained_detector._score_if(df)
        # 두 점수 모두 분산이 0이 아닌지 확인 (상수면 기여 없음)
        assert np.std(vae_raw) > 0, "VAE 점수가 상수 — 학습 실패 가능성"
        assert np.std(if_raw) > 0, "IF 점수가 상수 — 학습 실패 가능성"

    def test_if_sign_inversion(self, trained_detector, unsup_train_data):
        """IF decision_function 음수(이상)가 높은 ECDF 점수로 매핑."""
        df, _ = unsup_train_data
        if_raw = trained_detector._score_if(df)
        # IF: 음수=이상 → -if_raw를 ECDF에 넣으므로, if_raw가 가장 음수인 행이 최고 점수
        most_anomalous_idx = np.argmin(if_raw)
        ecdf_scores = np.searchsorted(
            trained_detector.if_train_scores_, -if_raw,
        ) / len(trained_detector.if_train_scores_)
        assert ecdf_scores[most_anomalous_idx] >= np.median(ecdf_scores)


class TestModelPersistence:
    def test_save_and_load(
        self, trained_detector, unsup_train_data, tmp_path,
    ):
        registry = ModelRegistry(registry_dir=tmp_path)
        trained_detector._registry = registry

        trained_detector.save_model(metric_value=0.0)
        saved_threshold = trained_detector.threshold_

        det2 = UnsupervisedDetector(model_registry=registry)
        det2.load_model("unsupervised")
        assert det2.threshold_ == saved_threshold
        assert hasattr(det2, "vae_train_scores_")
        assert hasattr(det2, "if_train_scores_")

        df, _ = unsup_train_data
        r1 = trained_detector.detect(df)
        r2 = det2.detect(df)
        np.testing.assert_array_almost_equal(
            r1.scores.values, r2.scores.values,
        )

    def test_save_without_registry_raises(self, trained_detector):
        trained_detector._registry = None
        with pytest.raises(ValueError, match="model_registry"):
            trained_detector.save_model(metric_value=0.0)


class TestConstants:
    def test_ml02_in_rule_codes(self):
        assert "ML02" in RULE_CODES
        assert RULE_CODES["ML02"] == "비지도학습 이상 탐지"

    def test_ml02_in_severity_map(self):
        assert "ML02" in SEVERITY_MAP
        assert SEVERITY_MAP["ML02"] == 4
