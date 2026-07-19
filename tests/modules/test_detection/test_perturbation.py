"""Feature Perturbation 강건성 테스트 — VAE 상관관계 학습 검증.

정상 전표를 복사 후 피처 간 상관관계를 파괴하여 변조.
개별 피처 값은 정상 범위이나 조합이 비정상 → VAE 재구성 오차 상승 → 탐지.
VAE가 단순 통계가 아닌 데이터의 논리적 관계를 이해했는지 증명.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.vae_detector import UnsupervisedDetector
from src.preprocessing.feature_groups import FeatureGroups

_FEATURES = [f"f{i}" for i in range(1, 6)]

# 정상 데이터의 공분산 구조: f1-f2 양의 상관(0.8), f3-f4 음의 상관(-0.7)
_COV = [
    [1.0,  0.8,  0.0,  0.0, 0.0],
    [0.8,  1.0,  0.0,  0.0, 0.0],
    [0.0,  0.0,  1.0, -0.7, 0.0],
    [0.0,  0.0, -0.7,  1.0, 0.0],
    [0.0,  0.0,  0.0,  0.0, 1.0],
]


@dataclass
class PerturbationDataset:
    """Perturbation 테스트용 데이터 번들."""

    X_train: pd.DataFrame         # 정상 학습용 (500행)
    X_test_normal: pd.DataFrame   # 정상 테스트용 (50행)
    X_test_perturbed: pd.DataFrame  # 상관관계 파괴 변조 (20행)
    groups: FeatureGroups = field(default_factory=lambda: FeatureGroups(
        numeric=_FEATURES, categorical_high=[], categorical_low=[],
        boolean=[], ordinal=[], excluded=[],
    ))


@pytest.fixture(scope="module")
def perturbation_data() -> PerturbationDataset:
    """상관관계 있는 다변량 정규분포 + 상관 파괴 변조."""
    rng = np.random.default_rng(42)
    X_all = rng.multivariate_normal([0] * 5, _COV, size=570)

    X_train = pd.DataFrame(X_all[:500], columns=_FEATURES)
    X_test_normal = pd.DataFrame(X_all[500:550], columns=_FEATURES)

    # Why: 변조 = 정상 복사 후 상관관계를 극단적으로 파괴.
    #       f1과 f2는 양의 상관(ρ=0.8) → f2를 f1의 반대 방향 극값으로 설정.
    #       f3과 f4는 음의 상관(ρ=-0.7) → f4를 f3과 같은 방향 극값으로 설정.
    perturbed = X_all[550:570].copy()
    # f1↑→f2↓ 강제: f1 절대값 스케일로 f2를 반대 방향
    perturbed[:, 1] = -np.abs(perturbed[:, 0]) * 2
    # f3↑→f4↑ 강제: f3 절대값 스케일로 f4를 같은 방향
    perturbed[:, 3] = np.abs(perturbed[:, 2]) * 2
    X_test_perturbed = pd.DataFrame(perturbed, columns=_FEATURES)

    return PerturbationDataset(
        X_train=X_train,
        X_test_normal=X_test_normal,
        X_test_perturbed=X_test_perturbed,
    )


@pytest.fixture(scope="module")
def trained_vae(perturbation_data: PerturbationDataset) -> UnsupervisedDetector:
    """경량 VAE 학습 (정상 데이터만)."""
    settings = AuditSettings(
        vae_latent_dim=3, vae_epochs=30, vae_batch_size=64,
        if_contamination=0.02,
    )
    det = UnsupervisedDetector(settings=settings)
    det.train(perturbation_data.X_train, perturbation_data.groups)
    return det


# ── 테스트 ───────────────────────────────────────────────────


class TestVAERawReconstructionError:
    """VAE raw 재구성 오차로 상관관계 학습 검증.

    Why: IF는 고립도 측정이므로 상관관계 파괴에 둔감할 수 있음.
         VAE 재구성 오차(_score_vae)를 직접 비교하여 VAE가 공분산 구조를
         학습했는지 순수하게 검증한다.
    """

    def test_normal_low_reconstruction_error(self, trained_vae, perturbation_data):
        """정상 데이터의 VAE 재구성 오차 중앙값이 변조보다 낮음."""
        vae_normal = trained_vae._score_vae(perturbation_data.X_test_normal)
        vae_perturbed = trained_vae._score_vae(perturbation_data.X_test_perturbed)
        assert np.median(vae_normal) < np.median(vae_perturbed), (
            f"정상 중앙값({np.median(vae_normal):.3f}) >= "
            f"변조 중앙값({np.median(vae_perturbed):.3f})"
        )

    def test_perturbed_higher_than_normal(self, trained_vae, perturbation_data):
        """변조 데이터 VAE 평균 오차 > 정상 평균 오차."""
        vae_normal = trained_vae._score_vae(perturbation_data.X_test_normal)
        vae_perturbed = trained_vae._score_vae(perturbation_data.X_test_perturbed)
        assert vae_perturbed.mean() > vae_normal.mean(), (
            f"변조({vae_perturbed.mean():.3f}) <= 정상({vae_normal.mean():.3f})"
        )

    def test_correlation_violation_detected(self, trained_vae, perturbation_data):
        """변조 평균 VAE 오차 > 정상 VAE 오차의 75th percentile."""
        vae_normal = trained_vae._score_vae(perturbation_data.X_test_normal)
        vae_perturbed = trained_vae._score_vae(perturbation_data.X_test_perturbed)
        p75 = np.percentile(vae_normal, 75)
        assert vae_perturbed.mean() > p75, (
            f"변조 평균({vae_perturbed.mean():.3f}) <= 정상 P75({p75:.3f})"
        )


class TestPerturbationDetection:
    """변조 데이터의 VAE 탐지율 및 단변량 정상성 검증."""

    def test_vae_flagged_ratio(self, trained_vae, perturbation_data):
        """변조 20건 중 VAE 오차가 정상 P90 초과하는 비율 > 30%."""
        vae_normal = trained_vae._score_vae(perturbation_data.X_test_normal)
        vae_perturbed = trained_vae._score_vae(perturbation_data.X_test_perturbed)
        # Why: 앙상블 threshold 대신 VAE 자체의 정상 분포 P90을 기준으로 판정
        p90 = np.percentile(vae_normal, 90)
        flagged_rate = (vae_perturbed > p90).mean()
        assert flagged_rate > 0.3, f"VAE 탐지율 {flagged_rate:.1%} <= 30%"

    def test_individual_features_in_range(self, perturbation_data):
        """변조 데이터의 개별 피처가 정상 범위(±3σ) 내 — 단변량으로는 정상."""
        train_mean = perturbation_data.X_train.mean()
        train_std = perturbation_data.X_train.std()
        perturbed = perturbation_data.X_test_perturbed

        for col in _FEATURES:
            lower = train_mean[col] - 3 * train_std[col]
            upper = train_mean[col] + 3 * train_std[col]
            out_of_range = ((perturbed[col] < lower) | (perturbed[col] > upper)).sum()
            # 대부분의 값이 정상 범위 내여야 함 (일부 경계값 허용)
            assert out_of_range <= len(perturbed) * 0.3, (
                f"{col}: {out_of_range}/{len(perturbed)}건이 ±3σ 초과"
            )
