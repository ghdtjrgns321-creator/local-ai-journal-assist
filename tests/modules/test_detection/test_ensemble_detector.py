"""EnsembleDetector 단위 테스트 — Stacking meta-learner 오케스트레이션."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.constants import STACKING_BASE_MODELS
from src.detection.ensemble_detector import EnsembleDetector

# ── Fixture ───────────────────────────────────────────────


def _make_detection_result(
    track_name: str, n: int = 100, seed: int = 0,
) -> DetectionResult:
    """합성 DetectionResult 생성."""
    rng = np.random.default_rng(seed)
    scores = pd.Series(rng.uniform(0, 1, n), name=track_name)
    return DetectionResult(
        track_name=track_name,
        flagged_indices=[],
        scores=scores,
        rule_flags=[],
        details=pd.DataFrame({track_name: scores}),
        metadata={"elapsed": 0.01},
    )


@pytest.fixture()
def full_results() -> list[DetectionResult]:
    """8개 base model의 DetectionResult 리스트."""
    return [
        _make_detection_result(name, seed=i)
        for i, name in enumerate(STACKING_BASE_MODELS)
    ]


@pytest.fixture()
def partial_results() -> list[DetectionResult]:
    """3개만 존재하는 부분 결과 (Cold Start 시뮬레이션)."""
    return [
        _make_detection_result("layer_a", seed=0),
        _make_detection_result("layer_b", seed=1),
        _make_detection_result("benford", seed=3),
    ]


@pytest.fixture()
def df_index() -> pd.Index:
    return pd.RangeIndex(100)


@pytest.fixture()
def labels_sufficient() -> np.ndarray:
    """양성 60건 — stacking 학습 가능."""
    y = np.zeros(100, dtype=int)
    y[:60] = 1
    return y


@pytest.fixture()
def labels_insufficient() -> np.ndarray:
    """양성 5건 — fallback 판정."""
    y = np.zeros(100, dtype=int)
    y[:5] = 1
    return y


# ── BuildScoreMatrix ──────────────────────────────────────


class TestBuildScoreMatrix:
    def test_full_results_shape(self, full_results, df_index):
        matrix = EnsembleDetector._build_score_matrix(full_results, df_index)
        assert matrix.shape == (100, len(STACKING_BASE_MODELS))

    def test_partial_results_fills_zero(self, partial_results, df_index):
        """누락 모델 열은 0.0으로 채워져야 한다."""
        matrix = EnsembleDetector._build_score_matrix(partial_results, df_index)
        assert matrix.shape == (100, len(STACKING_BASE_MODELS))
        # ml_supervised(인덱스 4)는 누락 → 전부 0
        assert np.all(matrix[:, 4] == 0.0)

    def test_column_order(self, full_results, df_index):
        """열 순서가 STACKING_BASE_MODELS와 일치."""
        matrix = EnsembleDetector._build_score_matrix(full_results, df_index)
        for col_idx, track_name in enumerate(STACKING_BASE_MODELS):
            result = next(r for r in full_results if r.track_name == track_name)
            np.testing.assert_array_almost_equal(
                matrix[:, col_idx], result.scores.values,
            )


# ── Fallback 판정 ─────────────────────────────────────────


class TestFallback:
    def test_sufficient_labels_no_fallback(self, labels_sufficient):
        det = EnsembleDetector()
        assert not det._check_fallback_needed(labels_sufficient)

    def test_insufficient_labels_triggers_fallback(self, labels_insufficient):
        det = EnsembleDetector()
        assert det._check_fallback_needed(labels_insufficient)

    def test_fallback_percentile_ranking_range(self, full_results, df_index):
        det = EnsembleDetector()
        scores = det._fallback_percentile_ranking(full_results, df_index)
        assert scores.min() >= 0.0
        assert scores.max() <= 1.0

    def test_fallback_percentile_ranking_name(self, full_results, df_index):
        det = EnsembleDetector()
        # ECDF 없이도 동작 (Cold Start fallback)
        scores = det._fallback_percentile_ranking(full_results, df_index)
        assert scores.name == "EN01"

    def test_fallback_ecdf_stored_after_train(self, full_results, labels_insufficient, df_index):
        """train_from_results fallback 시 ECDF 분포가 저장된다."""
        det = EnsembleDetector()
        det.train_from_results(full_results, labels_insufficient, df_index)
        assert len(det._fallback_ecdf) > 0

    def test_fallback_ecdf_used_in_detect(self, full_results, labels_insufficient, df_index):
        """ECDF가 저장된 후 detect_from_results에서 사용된다."""
        det = EnsembleDetector()
        det.train_from_results(full_results, labels_insufficient, df_index)
        result = det.detect_from_results(full_results, df_index)
        assert result.metadata["mode"] == "fallback"
        assert (result.scores >= 0.0).all()
        assert (result.scores <= 1.0).all()


# ── TrainFromResults ──────────────────────────────────────


class TestTrainFromResults:
    def test_stacking_mode(self, full_results, labels_sufficient, df_index):
        det = EnsembleDetector()
        info = det.train_from_results(full_results, labels_sufficient, df_index)
        assert info["mode"] == "stacking"
        assert "feature_weights" in info

    def test_fallback_mode(self, full_results, labels_insufficient, df_index):
        det = EnsembleDetector()
        info = det.train_from_results(full_results, labels_insufficient, df_index)
        assert info["mode"] == "fallback"

    def test_feature_weights_non_negative(self, full_results, labels_sufficient, df_index):
        det = EnsembleDetector()
        info = det.train_from_results(full_results, labels_sufficient, df_index)
        for name, w in info["feature_weights"].items():
            assert w >= 0.0, f"{name} 가중치가 음수: {w}"


# ── DetectFromResults ─────────────────────────────────────


class TestDetectFromResults:
    def test_returns_detection_result(self, full_results, labels_sufficient, df_index):
        det = EnsembleDetector()
        det.train_from_results(full_results, labels_sufficient, df_index)
        result = det.detect_from_results(full_results, df_index)
        assert isinstance(result, DetectionResult)

    def test_scores_range(self, full_results, labels_sufficient, df_index):
        det = EnsembleDetector()
        det.train_from_results(full_results, labels_sufficient, df_index)
        result = det.detect_from_results(full_results, df_index)
        assert (result.scores >= 0.0).all()
        assert (result.scores <= 1.0).all()

    def test_track_name(self, full_results, labels_sufficient, df_index):
        det = EnsembleDetector()
        det.train_from_results(full_results, labels_sufficient, df_index)
        result = det.detect_from_results(full_results, df_index)
        assert result.track_name == "ensemble"

    def test_details_has_en01(self, full_results, labels_sufficient, df_index):
        det = EnsembleDetector()
        det.train_from_results(full_results, labels_sufficient, df_index)
        result = det.detect_from_results(full_results, df_index)
        assert "EN01" in result.details.columns

    def test_index_alignment(self, full_results, labels_sufficient):
        """비연속 인덱스에서도 정렬 유지."""
        custom_index = pd.Index(range(200, 300))
        # 결과도 동일 인덱스로 재생성
        results = []
        for i, name in enumerate(STACKING_BASE_MODELS):
            rng = np.random.default_rng(i)
            scores = pd.Series(rng.uniform(0, 1, 100), index=custom_index, name=name)
            results.append(DetectionResult(
                track_name=name, flagged_indices=[], scores=scores,
                rule_flags=[], details=pd.DataFrame({name: scores}),
                metadata={"elapsed": 0.01},
            ))
        det = EnsembleDetector()
        det.train_from_results(results, labels_sufficient, custom_index)
        result = det.detect_from_results(results, custom_index)
        assert result.scores.index.equals(custom_index)

    def test_fallback_mode_detect(self, full_results, labels_insufficient, df_index):
        """fallback 모드에서도 detect_from_results 정상 동작."""
        det = EnsembleDetector()
        det.train_from_results(full_results, labels_insufficient, df_index)
        result = det.detect_from_results(full_results, df_index)
        assert result.metadata["mode"] == "fallback"
        assert (result.scores >= 0.0).all()


# ── AggregatorIntegration ─────────────────────────────────


class TestAggregatorIntegration:
    """score_aggregator + stacking_scores 통합."""

    def test_stacking_scores_override(self, full_results, df_index):
        """stacking_scores가 있으면 가중합 대신 사용."""
        from src.detection.score_aggregator import aggregate_scores

        stacking_scores = pd.Series(0.75, index=df_index)
        df = pd.DataFrame({"dummy": 1}, index=df_index)
        agg_df = aggregate_scores(df, full_results, stacking_scores=stacking_scores)
        # 모든 행이 0.75
        assert (agg_df["anomaly_score"] == 0.75).all()

    def test_none_stacking_uses_weighted_sum(self, full_results, df_index):
        """stacking_scores=None이면 기존 가중합."""
        from src.detection.score_aggregator import aggregate_scores

        df = pd.DataFrame({"dummy": 1}, index=df_index)
        agg_df = aggregate_scores(df, full_results, stacking_scores=None)
        # 가중합 결과가 0.75 균일이 아님 (랜덤 scores)
        assert agg_df["anomaly_score"].std() > 0.0


# ── OOF (User-Leakage 방어) ───────────────────────────────


class TestOOFBuildScoreMatrix:
    """`_build_score_matrix_from_oof` — leakage-prone 트랙 OOF 합성."""

    def test_oof_overrides_leakage_columns(self, full_results, df_index):
        # Why: ML_SUPERVISED 등 leakage-prone 트랙은 oof_scores에서 값을 가져와야 함
        oof = {
            "ml_supervised": np.full(100, 0.42),
            "ml_transformer": np.full(100, 0.55),
            "ml_sequence": np.full(100, 0.68),
        }
        # leakage 없는 5개만 비OOF로 전달
        non_leakage = [
            r for r in full_results
            if r.track_name not in oof
        ]
        matrix = EnsembleDetector._build_score_matrix_from_oof(
            non_leakage_results=non_leakage,
            oof_scores=oof,
            df_index=df_index,
        )
        assert matrix.shape == (100, len(STACKING_BASE_MODELS))
        # 각 leakage-prone 컬럼이 OOF 값으로 채워짐
        sup_idx = STACKING_BASE_MODELS.index("ml_supervised")
        tfm_idx = STACKING_BASE_MODELS.index("ml_transformer")
        seq_idx = STACKING_BASE_MODELS.index("ml_sequence")
        np.testing.assert_array_equal(matrix[:, sup_idx], np.full(100, 0.42))
        np.testing.assert_array_equal(matrix[:, tfm_idx], np.full(100, 0.55))
        np.testing.assert_array_equal(matrix[:, seq_idx], np.full(100, 0.68))

    def test_non_leakage_columns_preserved(self, full_results, df_index):
        # Why: 룰/VAE 컬럼은 non_leakage_results의 score 그대로 유지
        oof = {
            "ml_supervised": np.zeros(100),
            "ml_transformer": np.zeros(100),
            "ml_sequence": np.zeros(100),
        }
        non_leakage = [
            r for r in full_results
            if r.track_name not in oof
        ]
        matrix = EnsembleDetector._build_score_matrix_from_oof(
            non_leakage_results=non_leakage,
            oof_scores=oof,
            df_index=df_index,
        )
        # layer_b 컬럼이 정확히 원본 결과와 일치해야 함
        b_idx = STACKING_BASE_MODELS.index("layer_b")
        layer_b_result = next(r for r in non_leakage if r.track_name == "layer_b")
        np.testing.assert_array_almost_equal(
            matrix[:, b_idx], layer_b_result.scores.values,
        )


class TestOOFGroupKFoldLeakage:
    """GroupKFold가 user-leakage를 차단하는지 직접 검증."""

    def test_user_disjoint_across_folds(self):
        from sklearn.model_selection import GroupKFold

        # Why: 사용자 10명, 각 5건. fold가 끊어진 사용자를 만들어선 안 된다.
        n_users = 10
        rows_per_user = 5
        user_ids = np.repeat(np.arange(n_users), rows_per_user)
        X = pd.DataFrame({"x": np.arange(len(user_ids))})
        y = np.zeros(len(user_ids), dtype=int)
        y[::3] = 1

        gkf = GroupKFold(n_splits=3)
        for train_idx, val_idx in gkf.split(X, y, groups=user_ids):
            train_users = set(user_ids[train_idx])
            val_users = set(user_ids[val_idx])
            # 핵심 검증: train ∩ val 사용자 = 공집합
            assert train_users.isdisjoint(val_users), (
                f"User leakage 발생: {train_users & val_users}"
            )


class TestOOFFallbackPath:
    """train_oof도 라벨 부족 시 fallback 모드로 안전 진입한다."""

    def test_oof_falls_back_with_few_labels(
        self, full_results, labels_insufficient, df_index,
    ):
        from src.preprocessing.label_strategy import LabelResult

        det = EnsembleDetector()
        # Why: 단일 사용자 user_ids — 어차피 fallback 진입이라 GroupKFold는 호출 안 됨
        user_ids = np.zeros(100, dtype=int)
        label_result = LabelResult(
            y=labels_insufficient,
            strategy="test",
            label_source="manual",
            positive_rate=float(labels_insufficient.mean()),
        )
        info = det.train_oof(
            X=pd.DataFrame({"x": np.arange(100)}, index=df_index),
            label_result=label_result,
            user_ids=user_ids,
            df_index=df_index,
            non_leakage_results=full_results,
            groups=None,
        )
        assert info["mode"] == "fallback"
        assert info["n_folds"] == 0
        assert det._is_fallback is True
        assert len(det._fallback_ecdf) > 0

    def test_train_oof_rejects_user_ids_not_matching_created_by(
        self, full_results, labels_insufficient, df_index,
    ):
        from src.preprocessing.label_strategy import LabelResult

        det = EnsembleDetector()
        label_result = LabelResult(
            y=labels_insufficient,
            strategy="test",
            label_source="manual",
            positive_rate=float(labels_insufficient.mean()),
        )
        X = pd.DataFrame(
            {
                "created_by": [f"user_{idx % 3}" for idx in range(100)],
                "x": np.arange(100),
            },
            index=df_index,
        )

        with pytest.raises(ValueError, match="must match X\\['created_by'\\]"):
            det.train_oof(
                X=X,
                label_result=label_result,
                user_ids=np.full(100, "not_created_by"),
                df_index=df_index,
                non_leakage_results=full_results,
                groups=None,
            )
