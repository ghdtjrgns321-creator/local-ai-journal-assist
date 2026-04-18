"""SequenceDetector (BiLSTM+Attention) 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import NotFittedError

from src.detection.base import DetectionResult
from src.detection.constants import RULE_CODES, SEVERITY_MAP
from src.detection.sequence_detector import SequenceDetector
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.label_strategy import LabelResult
from src.preprocessing.model_registry import ModelRegistry
from src.preprocessing.sequence_builder import SequenceResult, build_sequences


# ── Fixtures ──


@pytest.fixture()
def seq_groups() -> FeatureGroups:
    """최소 피처 그룹 (created_by, posting_date는 preprocessor에서 DROP)."""
    return FeatureGroups(
        numeric=["f1", "f2", "f3"],
        categorical_low=["cat1"],
        boolean=["flag1"],
    )


@pytest.fixture()
def seq_train_data() -> tuple[pd.DataFrame, LabelResult]:
    """학습용 합성 데이터 (300행, 3명 사용자 각 100건, 양성 ~15%).

    Why: 시퀀스 빌딩을 위해 created_by와 posting_date가 필수.
    각 사용자가 seq_len(8) 이상 행을 갖도록 100건씩 배분.
    """
    rng = np.random.default_rng(42)
    n = 300
    users = np.repeat(["user_A", "user_B", "user_C"], 100)
    # Why: 사용자별 독립 날짜 범위로 시간순 정렬 가능하게 구성
    dates = (
        pd.date_range("2025-01-01", periods=100, freq="D").tolist()
        + pd.date_range("2025-01-01", periods=100, freq="D").tolist()
        + pd.date_range("2025-01-01", periods=100, freq="D").tolist()
    )
    df = pd.DataFrame({
        "created_by": users,
        "posting_date": pd.to_datetime(dates),
        "fiscal_year": [2025] * n,
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
def trained_seq_detector(seq_train_data, seq_groups) -> SequenceDetector:
    """학습 완료된 SequenceDetector (경량 하이퍼파라미터)."""
    from config.settings import AuditSettings

    # Why: CI에서 빠르게 통과하도록 경량 설정
    settings = AuditSettings(
        bilstm_hidden_size=16, bilstm_seq_len=8, bilstm_stride=4,
        bilstm_epochs=2, bilstm_batch_size=32, bilstm_lr=1e-3,
        bilstm_dropout=0.1, bilstm_num_layers=1,
    )
    det = SequenceDetector(settings=settings)
    df, label = seq_train_data
    det.train(df, label, seq_groups)
    return det


# ── TestSequenceBuilder ──


class TestSequenceBuilder:
    """build_sequences() 단위 테스트."""

    def test_basic_windowing(self):
        """단일 사용자, 20행 → seq_len=8, stride=1 → 13개 윈도우."""
        X = np.random.default_rng(42).standard_normal((20, 5)).astype(np.float32)
        y = np.zeros(20, dtype=np.int64)
        users = np.array(["u1"] * 20)
        times = np.arange(20)
        result = build_sequences(X, y, users, times, seq_len=8, stride=1)
        assert result.X_seq.shape == (13, 8, 5)
        assert len(result.original_indices) == 13

    def test_stride(self):
        """stride=4일 때 윈도우 수 검증."""
        X = np.random.default_rng(42).standard_normal((20, 5)).astype(np.float32)
        y = np.zeros(20, dtype=np.int64)
        users = np.array(["u1"] * 20)
        times = np.arange(20)
        result = build_sequences(X, y, users, times, seq_len=8, stride=4)
        # (20-8)/4 + 1 = 4개 윈도우
        assert result.X_seq.shape[0] == 4

    def test_padding_short_user(self):
        """2건 사용자 → 제로 패딩 + mask."""
        X = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        y = np.array([0, 1], dtype=np.int64)
        users = np.array(["u1", "u1"])
        times = np.array([0, 1])
        result = build_sequences(X, y, users, times, seq_len=8, stride=1)
        assert result.X_seq.shape == (1, 8, 3)
        # 앞 6개 패딩 (mask=False), 뒤 2개 유효 (mask=True)
        assert result.mask[0, :6].sum() == 0
        assert result.mask[0, 6:].all()
        # 라벨은 마지막 항목의 값 (방식 A)
        assert result.y_seq[0] == 1

    def test_multiple_users(self):
        """2명 사용자 각 10건 → 독립 윈도우."""
        X = np.random.default_rng(42).standard_normal((20, 3)).astype(np.float32)
        y = np.zeros(20, dtype=np.int64)
        users = np.array(["u1"] * 10 + ["u2"] * 10)
        times = np.tile(np.arange(10), 2)
        result = build_sequences(X, y, users, times, seq_len=8, stride=1)
        # 각 사용자 10건 → 3개 윈도우씩 → 6개
        assert result.X_seq.shape[0] == 6

    def test_original_indices_point_to_last_item(self):
        """original_indices가 윈도우 마지막 항목의 원본 위치를 가리키는지 확인."""
        X = np.random.default_rng(42).standard_normal((10, 3)).astype(np.float32)
        y = np.zeros(10, dtype=np.int64)
        users = np.array(["u1"] * 10)
        times = np.arange(10)
        result = build_sequences(X, y, users, times, seq_len=4, stride=1)
        # 윈도우 0: [0,1,2,3] → 마지막=3
        # 윈도우 1: [1,2,3,4] → 마지막=4
        assert result.original_indices[0] == 3
        assert result.original_indices[1] == 4

    def test_y_seq_uses_last_item_label(self):
        """y_seq는 윈도우 마지막 항목의 라벨을 사용 (방식 A)."""
        X = np.random.default_rng(42).standard_normal((8, 3)).astype(np.float32)
        y = np.array([0, 0, 0, 1, 0, 0, 0, 1], dtype=np.int64)
        users = np.array(["u1"] * 8)
        times = np.arange(8)
        result = build_sequences(X, y, users, times, seq_len=4, stride=1)
        # 윈도우 0: [0,1,2,3] → y[3]=1
        assert result.y_seq[0] == 1
        # 윈도우 1: [1,2,3,4] → y[4]=0
        assert result.y_seq[1] == 0

    def test_empty_input(self):
        """빈 입력 → 빈 결과."""
        X = np.empty((0, 5), dtype=np.float32)
        y = np.empty(0, dtype=np.int64)
        users = np.empty(0)
        times = np.empty(0)
        result = build_sequences(X, y, users, times, seq_len=8)
        assert result.X_seq.shape[0] == 0

    def test_y_none_inference_mode(self):
        """y=None (추론 모드)에서도 동작."""
        X = np.random.default_rng(42).standard_normal((10, 3)).astype(np.float32)
        users = np.array(["u1"] * 10)
        times = np.arange(10)
        result = build_sequences(X, None, users, times, seq_len=4, stride=1)
        assert result.X_seq.shape[0] == 7
        assert (result.y_seq == 0).all()


# ── TestInit ──


class TestInit:
    def test_track_name(self):
        det = SequenceDetector()
        assert det.track_name == "ml_sequence"

    def test_detect_before_train_raises(self):
        det = SequenceDetector()
        df = pd.DataFrame({
            "f1": [1.0],
            "created_by": ["u1"],
            "posting_date": [pd.Timestamp("2025-01-01")],
        })
        with pytest.raises(NotFittedError):
            det.detect(df)


# ── TestTrain ──


class TestTrain:
    def test_returns_metadata(self, seq_train_data, seq_groups):
        from config.settings import AuditSettings

        settings = AuditSettings(
            bilstm_hidden_size=16, bilstm_seq_len=8, bilstm_stride=4,
            bilstm_epochs=2, bilstm_batch_size=32,
        )
        det = SequenceDetector(settings=settings)
        df, label = seq_train_data
        meta = det.train(df, label, seq_groups)
        assert "optimal_threshold" in meta
        assert "n_train_sequences" in meta
        assert "n_val_sequences" in meta
        assert meta["split_policy"] == "document_group_holdout"

    def test_sets_preprocessor_and_classifier(self, trained_seq_detector):
        assert hasattr(trained_seq_detector, "preprocessor_")
        assert hasattr(trained_seq_detector, "classifier_")

    def test_sets_optimal_threshold(self, trained_seq_detector):
        assert 0.1 <= trained_seq_detector.optimal_threshold_ <= 0.9

    def test_missing_created_by_raises(self, seq_groups):
        """created_by 컬럼 누락 시 ValueError."""
        from config.settings import AuditSettings

        df = pd.DataFrame({
            "f1": [1.0, 2.0], "f2": [1.0, 2.0], "f3": [1.0, 2.0],
            "cat1": ["A", "B"], "flag1": [0, 1],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
        })
        y = np.array([0, 1])
        label = LabelResult(
            y=y, strategy="datasynth",
            label_source="ground_truth", positive_rate=0.5,
        )
        settings = AuditSettings(bilstm_seq_len=2, bilstm_epochs=1)
        det = SequenceDetector(settings=settings)
        with pytest.raises(ValueError, match="created_by"):
            det.train(df, label, seq_groups)

    def test_zero_positive_raises(self, seq_groups):
        """양성 0건이면 ValueError."""
        rng = np.random.default_rng(42)
        n = 100
        df = pd.DataFrame({
            "created_by": np.repeat(["u1", "u2"], 50),
            "posting_date": pd.date_range("2025-01-01", periods=n, freq="D"),
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
        det = SequenceDetector()
        with pytest.raises(ValueError, match="양성 샘플이 0건"):
            det.train(df, label, seq_groups)


# ── TestDetect ──


class TestDetect:
    def test_returns_detection_result(self, trained_seq_detector, seq_train_data):
        df, _ = seq_train_data
        result = trained_seq_detector.detect(df)
        assert isinstance(result, DetectionResult)

    def test_scores_range(self, trained_seq_detector, seq_train_data):
        df, _ = seq_train_data
        result = trained_seq_detector.detect(df)
        assert (result.scores >= 0.0).all()
        assert (result.scores <= 1.0).all()

    def test_scores_index_matches_df(self, trained_seq_detector, seq_train_data):
        """scores의 인덱스가 원본 DataFrame 인덱스와 일치."""
        df, _ = seq_train_data
        result = trained_seq_detector.detect(df)
        assert result.scores.index.equals(df.index)

    def test_details_has_ml04(self, trained_seq_detector, seq_train_data):
        df, _ = seq_train_data
        result = trained_seq_detector.detect(df)
        assert "ML04" in result.details.columns

    def test_flagged_indices_subset(self, trained_seq_detector, seq_train_data):
        df, _ = seq_train_data
        result = trained_seq_detector.detect(df)
        assert set(result.flagged_indices).issubset(set(df.index.tolist()))

    def test_track_name_in_result(self, trained_seq_detector, seq_train_data):
        df, _ = seq_train_data
        result = trained_seq_detector.detect(df)
        assert result.track_name == "ml_sequence"

    def test_rule_flags_contain_ml04(self, trained_seq_detector, seq_train_data):
        df, _ = seq_train_data
        result = trained_seq_detector.detect(df)
        assert any(rf.rule_id == "ML04" for rf in result.rule_flags)

    def test_noncontiguous_index(self, trained_seq_detector, seq_train_data):
        """비연속 인덱스(필터링된 DataFrame)에서도 행 매핑이 정확."""
        df, _ = seq_train_data
        # 짝수 행만 선택 → 비연속 인덱스 (0, 2, 4, ...)
        df_filtered = df.iloc[::2].copy()
        result = trained_seq_detector.detect(df_filtered)
        assert result.scores.index.equals(df_filtered.index)
        assert set(result.flagged_indices).issubset(set(df_filtered.index.tolist()))


# ── TestModelPersistence ──


class TestModelPersistence:
    def test_save_and_load(self, trained_seq_detector, seq_train_data, tmp_path):
        registry = ModelRegistry(registry_dir=tmp_path)
        trained_seq_detector._registry = registry
        trained_seq_detector.save_model(mean_f1=0.70)
        saved_threshold = trained_seq_detector.optimal_threshold_

        det2 = SequenceDetector(model_registry=registry)
        det2.load_model("bilstm_sequence")
        assert hasattr(det2, "preprocessor_")
        assert hasattr(det2, "classifier_")
        assert det2.optimal_threshold_ == saved_threshold

    def test_save_without_registry_raises(self, trained_seq_detector):
        trained_seq_detector._registry = None
        with pytest.raises(ValueError, match="model_registry"):
            trained_seq_detector.save_model(mean_f1=0.70)


# ── TestConstants ──


class TestConstants:
    def test_ml04_in_rule_codes(self):
        assert "ML04" in RULE_CODES
        assert RULE_CODES["ML04"] == "시퀀스 이상 탐지"

    def test_ml04_in_severity_map(self):
        assert "ML04" in SEVERITY_MAP
        assert SEVERITY_MAP["ML04"] == 4


# ── TestPostingTime (P1-1) ──


class TestPostingTime:
    """posting_time(시:분:초) 컬럼이 시퀀스 정렬에 반영되는지 검증."""

    def test_build_timestamps_without_posting_time(self):
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
        })
        ts = SequenceDetector._build_timestamps(df)
        # Why: posting_time 없으면 date만 사용 → 00:00:00
        assert pd.Timestamp(ts[0]) == pd.Timestamp("2025-01-01 00:00:00")
        assert pd.Timestamp(ts[1]) == pd.Timestamp("2025-01-02 00:00:00")

    def test_build_timestamps_with_posting_time(self):
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "posting_time": ["09:30:15", "14:35:22"],
        })
        ts = SequenceDetector._build_timestamps(df)
        # Why: 같은 날짜라도 시간이 다르면 정렬 가능
        assert pd.Timestamp(ts[0]) == pd.Timestamp("2025-01-01 09:30:15")
        assert pd.Timestamp(ts[1]) == pd.Timestamp("2025-01-01 14:35:22")
        assert ts[0] < ts[1]

    def test_build_timestamps_handles_missing_posting_time(self):
        # Why: posting_time 일부 NaN → fillna(0)으로 자동 보정
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "posting_time": ["09:30:15", None],
        })
        ts = SequenceDetector._build_timestamps(df)
        assert pd.Timestamp(ts[0]) == pd.Timestamp("2025-01-01 09:30:15")
        # NaT가 아닌 자정으로 설정 (fillna)
        assert pd.Timestamp(ts[1]) == pd.Timestamp("2025-01-01 00:00:00")

    def test_same_day_ordering_via_posting_time(self):
        # Why: build_sequences가 timestamps 기준 stable sort → 시간순 윈도우 형성
        from src.preprocessing.sequence_builder import build_sequences

        # 같은 사용자 + 같은 날짜 + 다른 시간 8건
        # Why: 의도적으로 역순 입력하여 sort가 동작하는지 검증
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01"] * 8),
            "posting_time": [
                "16:00:00", "15:00:00", "14:00:00", "13:00:00",
                "12:00:00", "11:00:00", "10:00:00", "09:00:00",
            ],
        })
        ts = SequenceDetector._build_timestamps(df)
        X = np.arange(8 * 3, dtype=np.float32).reshape(8, 3)
        users = np.array(["u1"] * 8)

        result = build_sequences(
            X=X, y=None, user_ids=users, timestamps=ts,
            seq_len=8, stride=1,
        )
        # 윈도우 1개. original_indices[0]는 시간순 정렬 후 마지막 항목 = 16:00:00 → 원본 index 0
        assert result.X_seq.shape == (1, 8, 3)
        assert result.original_indices[0] == 0


# ── TestBiLSTMAttention (묶음 1) ──


class TestBiLSTMAttention:
    """BiLSTMClassifier.get_attention_weights() public API 검증."""

    def test_attention_shape(self):
        from src.preprocessing.bilstm_wrapper import BiLSTMClassifier

        rng = np.random.default_rng(42)
        n_windows, seq_len, n_features = 20, 8, 5
        X = rng.normal(0, 1, (n_windows, seq_len, n_features)).astype(np.float32)
        y = rng.choice([0, 1], n_windows, p=[0.7, 0.3]).astype(np.int64)
        mask = np.ones((n_windows, seq_len), dtype=bool)

        clf = BiLSTMClassifier(
            hidden_size=8, epochs=2, batch_size=16, device="cpu",
        ).fit(X, y, mask)
        weights = clf.get_attention_weights(X, mask)
        # Why: (n_windows, seq_len) — 시퀀스 시점별 attention
        assert weights.shape == (n_windows, seq_len)

    def test_attention_sums_to_one(self):
        from src.preprocessing.bilstm_wrapper import BiLSTMClassifier

        rng = np.random.default_rng(42)
        n_windows, seq_len, n_features = 10, 8, 5
        X = rng.normal(0, 1, (n_windows, seq_len, n_features)).astype(np.float32)
        y = rng.choice([0, 1], n_windows).astype(np.int64)
        mask = np.ones((n_windows, seq_len), dtype=bool)

        clf = BiLSTMClassifier(
            hidden_size=8, epochs=2, batch_size=16, device="cpu",
        ).fit(X, y, mask)
        weights = clf.get_attention_weights(X, mask)
        # Why: softmax 출력 → 행 합 ≈ 1
        row_sums = weights.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-5)

    def test_attention_masked_positions_zero(self):
        # Why: mask=False 위치는 attention weight=0 (padded 구간 제외)
        from src.preprocessing.bilstm_wrapper import BiLSTMClassifier

        rng = np.random.default_rng(42)
        n_windows, seq_len, n_features = 5, 8, 5
        X = rng.normal(0, 1, (n_windows, seq_len, n_features)).astype(np.float32)
        y = rng.choice([0, 1], n_windows).astype(np.int64)
        mask = np.ones((n_windows, seq_len), dtype=bool)
        # 앞 3개 timestep padding
        mask[:, :3] = False

        clf = BiLSTMClassifier(
            hidden_size=8, epochs=2, batch_size=16, device="cpu",
        ).fit(X, y, mask)
        weights = clf.get_attention_weights(X, mask)
        # 앞 3개 위치는 거의 0 (masked_fill(-inf) + softmax)
        assert (weights[:, :3] < 1e-5).all()
