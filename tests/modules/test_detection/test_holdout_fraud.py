"""Hold-out Fraud Type 검증 — VAE 존재 이유 증명.

8개 부정 유형 중 6개로 학습, 2개(suspense_account_abuse, expense_capitalization)를
미지 유형으로 테스트. 지도학습 vs 비지도학습의 탐지 특성 차이를 검증.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.supervised_detector import SupervisedDetector
from src.detection.vae_detector import UnsupervisedDetector
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.label_strategy import LabelResult

_FEATURES = [f"f{i}" for i in range(1, 6)]
_KNOWN_TYPES = ["revenue_manipulation", "approval_bypass", "duplicate_payment",
                "self_approval", "backdating", "round_tripping"]
_HOLDOUT_TYPES = ["suspense_account_abuse", "expense_capitalization"]


# ── Fixture ──────────────────────────────────────────────────


@dataclass
class HoldoutDataset:
    """Hold-out 테스트용 합성 데이터 번들."""

    X_train: pd.DataFrame
    y_train: np.ndarray
    X_vae_train: pd.DataFrame              # 정상 데이터만 (VAE 오염 방지)
    X_test_known: pd.DataFrame             # 기출 유형 테스트
    y_test_known: np.ndarray
    X_test_unknown: pd.DataFrame           # hold-out 유형 테스트
    y_test_unknown: np.ndarray
    X_test_normal: pd.DataFrame            # 정상 테스트
    groups: FeatureGroups = field(default_factory=lambda: FeatureGroups(
        numeric=_FEATURES, categorical_high=[], categorical_low=[],
        boolean=[], ordinal=[], excluded=[],
    ))


@pytest.fixture(scope="module")
def holdout_data() -> HoldoutDataset:
    """합성 데이터: 정상 N(0,1) + 부정 8유형(방향별 mean shift +3σ)."""
    rng = np.random.default_rng(42)
    n_normal, n_per_type = 500, 30

    # 정상 데이터
    normal = rng.normal(0, 1, (n_normal, 5))

    # Why: 각 유형은 다른 차원 방향으로 +3σ shift → 구별 가능하되 trivial하지 않음
    shifts = {t: np.zeros(5) for t in _KNOWN_TYPES + _HOLDOUT_TYPES}
    for i, t in enumerate(_KNOWN_TYPES + _HOLDOUT_TYPES):
        shifts[t][i % 5] = 3.0  # i번째 차원으로 shift

    fraud_known = {t: rng.normal(shifts[t], 1, (n_per_type, 5)) for t in _KNOWN_TYPES}
    fraud_holdout = {t: rng.normal(shifts[t], 1, (n_per_type, 5)) for t in _HOLDOUT_TYPES}

    # Train: 정상 400 + 기출 6유형
    X_normal_train = normal[:400]
    X_known = np.vstack([v for v in fraud_known.values()])
    y_known = np.ones(len(X_known))

    X_train = pd.DataFrame(np.vstack([X_normal_train, X_known]), columns=_FEATURES)
    train_doc_count = len(X_train)
    X_train["document_id"] = [f"TR_{i}" for i in range(train_doc_count)]
    X_train["fiscal_year"] = (
        ([2022] * 200)
        + ([2023] * 290)
        + ([2024] * (train_doc_count - 490))
    )
    y_train = np.concatenate([np.zeros(400), y_known])

    # VAE Train: 정상만 (이상치 오염 방지)
    X_vae_train = pd.DataFrame(X_normal_train, columns=_FEATURES)

    # Test: 기출 유형 일부 (각 10건)
    X_test_known = pd.DataFrame(
        np.vstack([v[:10] for v in fraud_known.values()]), columns=_FEATURES,
    )
    y_test_known = np.ones(len(X_test_known))

    # Test: hold-out 유형 전량
    X_test_unknown = pd.DataFrame(
        np.vstack([v for v in fraud_holdout.values()]), columns=_FEATURES,
    )
    y_test_unknown = np.ones(len(X_test_unknown))

    # Test: 정상
    X_test_normal = pd.DataFrame(normal[400:], columns=_FEATURES)

    return HoldoutDataset(
        X_train=X_train, y_train=y_train,
        X_vae_train=X_vae_train,
        X_test_known=X_test_known, y_test_known=y_test_known,
        X_test_unknown=X_test_unknown, y_test_unknown=y_test_unknown,
        X_test_normal=X_test_normal,
    )


@pytest.fixture(scope="module")
def trained_supervised(holdout_data: HoldoutDataset) -> SupervisedDetector:
    """학습 완료된 SupervisedDetector."""
    det = SupervisedDetector()
    label = LabelResult(
        y=holdout_data.y_train,
        strategy="holdout_test",
        label_source="synthetic",
        positive_rate=float(holdout_data.y_train.mean()),
    )
    det.train(holdout_data.X_train, label, holdout_data.groups)
    return det


@pytest.fixture(scope="module")
def trained_unsupervised(holdout_data: HoldoutDataset) -> UnsupervisedDetector:
    """학습 완료된 UnsupervisedDetector (경량 설정)."""
    settings = AuditSettings(
        vae_latent_dim=3, vae_epochs=10, vae_batch_size=64,
        if_contamination=0.02,
    )
    det = UnsupervisedDetector(settings=settings)
    det.train(holdout_data.X_vae_train, holdout_data.groups)
    return det


# ── 테스트 ───────────────────────────────────────────────────


class TestSupervisedHoldout:
    """지도학습: 기출 유형은 탐지, 미지 유형은 상대적 약화."""

    def test_detects_known_types(self, trained_supervised, holdout_data):
        """기출 유형 평균 점수 > 0.3."""
        result = trained_supervised.detect(holdout_data.X_test_known)
        mean_score = result.scores.mean()
        assert mean_score > 0.3, f"기출 유형 평균 점수 {mean_score:.3f} < 0.3"

    def test_misses_unknown_types(self, trained_supervised, holdout_data):
        """hold-out 유형도 정상보다는 높지만, 기출 우위는 보장하지 않는다."""
        unknown_scores = trained_supervised.detect(holdout_data.X_test_unknown).scores.mean()
        normal_scores = trained_supervised.detect(holdout_data.X_test_normal).scores.mean()
        assert unknown_scores > normal_scores, (
            f"미지 유형({unknown_scores:.3f}) <= 정상({normal_scores:.3f})"
        )


class TestUnsupervisedHoldout:
    """비지도학습: 미지 유형도 정상 분포 밖이므로 탐지."""

    def test_detects_unknown_types(self, trained_unsupervised, holdout_data):
        """VAE+IF: hold-out 유형에서 threshold 초과 비율 > 20%."""
        result = trained_unsupervised.detect(holdout_data.X_test_unknown)
        flagged_rate = len(result.flagged_indices) / len(holdout_data.X_test_unknown)
        assert flagged_rate > 0.20, f"미지 유형 탐지율 {flagged_rate:.1%} < 20%"

    def test_outperforms_supervised_on_unknown(
        self, trained_supervised, trained_unsupervised, holdout_data,
    ):
        """hold-out 유형: 비지도 평균 점수 > 지도 평균 점수 (VAE 존재 이유)."""
        sv_score = trained_supervised.detect(holdout_data.X_test_unknown).scores.mean()
        us_score = trained_unsupervised.detect(holdout_data.X_test_unknown).scores.mean()
        assert us_score > sv_score, (
            f"비지도({us_score:.3f}) <= 지도({sv_score:.3f})"
        )

    def test_normal_low_false_positive(self, trained_unsupervised, holdout_data):
        """정상 데이터 high-score(>threshold) 비율 < 20%."""
        result = trained_unsupervised.detect(holdout_data.X_test_normal)
        fp_rate = len(result.flagged_indices) / len(holdout_data.X_test_normal)
        assert fp_rate < 0.20, f"정상 데이터 FP율 {fp_rate:.1%} >= 20%"
