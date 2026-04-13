"""drift_detector — PSI 기반 드리프트 감지 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.preprocessing.drift_detector import (
    DRIFT_THRESHOLD_CRITICAL,
    DRIFT_THRESHOLD_WARN,
    DriftReport,
    compute_drift_report,
    compute_psi_categorical,
    compute_psi_numeric,
)
from src.preprocessing.model_registry import ModelMetadata


class TestComputePsiNumeric:
    def test_identical_distribution_psi_near_zero(self):
        # Why: 동일 분포 → PSI ≈ 0
        rng = np.random.default_rng(42)
        current = rng.normal(0.0, 1.0, 10_000)
        psi = compute_psi_numeric(
            baseline_mean=0.0, baseline_std=1.0, current_values=current,
        )
        assert psi < 0.05  # 노이즈 허용

    def test_shifted_mean_psi_high(self):
        # Why: 평균 2σ 이동 → PSI 크게 증가
        rng = np.random.default_rng(42)
        current = rng.normal(2.0, 1.0, 10_000)
        psi = compute_psi_numeric(
            baseline_mean=0.0, baseline_std=1.0, current_values=current,
        )
        assert psi > DRIFT_THRESHOLD_CRITICAL

    def test_empty_current_returns_zero(self):
        psi = compute_psi_numeric(0.0, 1.0, np.array([]))
        assert psi == 0.0

    def test_zero_std_baseline_safe(self):
        # Why: baseline_std=0은 분포 축소 상태 → PSI 계산 불가, 0 반환
        psi = compute_psi_numeric(0.0, 0.0, np.array([1.0, 2.0, 3.0]))
        assert psi == 0.0


class TestComputePsiCategorical:
    def test_identical_categories_psi_low(self):
        baseline = {"A": 500, "B": 300, "C": 200}
        current = pd.Series(["A"] * 500 + ["B"] * 300 + ["C"] * 200)
        psi = compute_psi_categorical(baseline, current)
        assert psi < 0.05

    def test_new_category_triggers_drift(self):
        # Why: baseline에 없던 새 카테고리가 대량 유입 → PSI 상승
        baseline = {"A": 800, "B": 200}
        current = pd.Series(["A"] * 400 + ["B"] * 100 + ["Z_NEW"] * 500)
        psi = compute_psi_categorical(baseline, current)
        assert psi > DRIFT_THRESHOLD_WARN

    def test_empty_baseline_returns_zero(self):
        current = pd.Series(["A", "B", "C"])
        assert compute_psi_categorical({}, current) == 0.0


class TestComputeDriftReport:
    @pytest.fixture()
    def stable_metadata(self) -> ModelMetadata:
        # Why: 학습 시점에 저장된 분포 통계 — 수치형(amount) + 범주형(currency)
        return ModelMetadata(
            model_name="test_model",
            version=1,
            file_path="/tmp/test.pkl",
            mean_f1=0.8,
            training_data_stats={
                "n_samples": 1000,
                "columns": {
                    "amount": {
                        "type": "numeric",
                        "mean": 100.0,
                        "std": 20.0,
                        "min": 0.0,
                        "max": 200.0,
                        "nunique": 50,
                        "null_rate": 0.0,
                    },
                    "currency": {
                        "type": "categorical",
                        "nunique": 2,
                        "null_rate": 0.0,
                        "top_categories": {"KRW": 800, "USD": 200},
                    },
                },
            },
            feature_schema_version=42,
        )

    def test_stable_distribution_status(self, stable_metadata):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "amount": rng.normal(100.0, 20.0, 1000),
            "currency": ["KRW"] * 800 + ["USD"] * 200,
        })
        report = compute_drift_report(stable_metadata, df)
        assert isinstance(report, DriftReport)
        assert report.overall_status == "stable"
        assert report.max_psi < DRIFT_THRESHOLD_WARN
        assert not report.schema_mismatch

    def test_shifted_amount_triggers_critical(self, stable_metadata):
        # Why: amount 평균을 크게 이동 → critical
        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "amount": rng.normal(200.0, 20.0, 1000),  # 5σ 이동
            "currency": ["KRW"] * 800 + ["USD"] * 200,
        })
        report = compute_drift_report(stable_metadata, df)
        assert report.overall_status == "critical"
        assert report.max_psi_column == "amount"

    def test_schema_mismatch_flagged(self, stable_metadata):
        # Why: baseline 컬럼이 현재 데이터에서 누락 → 스키마 불일치
        df = pd.DataFrame({"currency": ["KRW"] * 1000})  # amount 누락
        report = compute_drift_report(stable_metadata, df)
        assert report.schema_mismatch is True
        assert "amount" in report.column_psi

    def test_empty_stats_returns_stable(self):
        # Why: 학습 메타가 없으면 (구버전 registry) stable 반환
        meta = ModelMetadata(
            model_name="legacy", version=1, file_path="/tmp/x.pkl",
            mean_f1=0.0, training_data_stats={},
        )
        df = pd.DataFrame({"x": [1, 2, 3]})
        report = compute_drift_report(meta, df)
        assert report.overall_status == "stable"
        assert report.max_psi == 0.0
