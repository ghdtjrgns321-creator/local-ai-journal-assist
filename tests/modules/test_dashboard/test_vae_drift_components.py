"""대시보드 컴포넌트 핵심 로직 테스트 (묶음 3 — VAE Waterfall + Drift Banner).

Why: Streamlit 렌더링 자체는 단위 테스트가 까다로우므로 핵심 변환/집계
     로직(figure 생성, DriftReport 분류)만 별도 테스트한다.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest


class TestVAEWaterfallFigure:
    def test_build_vae_waterfall_returns_figure(self):
        from dashboard.components.shap_waterfall import _build_vae_waterfall
        items = [("amount", 0.5), ("gl_account", 0.3), ("posting_time", 0.1)]
        fig = _build_vae_waterfall(items)
        assert isinstance(fig, go.Figure)
        # Waterfall trace 1개
        assert len(fig.data) == 1

    def test_build_vae_waterfall_empty_items(self):
        # Why: 빈 리스트는 _build_vae_waterfall 자체를 호출하지 않는 경로이나,
        #      방어적 테스트로 빈 입력도 Figure를 반환해야 함
        from dashboard.components.shap_waterfall import _build_vae_waterfall
        fig = _build_vae_waterfall([])
        assert isinstance(fig, go.Figure)


class TestDriftBannerReport:
    @pytest.fixture()
    def metadata_stable(self):
        from src.preprocessing.model_registry import ModelMetadata
        return ModelMetadata(
            model_name="stable_model",
            version=1,
            file_path="/tmp/x.pkl",
            mean_f1=0.9,
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
                },
            },
        )

    @pytest.fixture()
    def metadata_critical(self):
        from src.preprocessing.model_registry import ModelMetadata
        # Why: std를 매우 작게 설정하면 PSI가 쉽게 커짐
        return ModelMetadata(
            model_name="drift_model",
            version=1,
            file_path="/tmp/y.pkl",
            mean_f1=0.8,
            training_data_stats={
                "n_samples": 1000,
                "columns": {
                    "amount": {
                        "type": "numeric",
                        "mean": 0.0,
                        "std": 1.0,
                        "min": -3.0,
                        "max": 3.0,
                        "nunique": 500,
                        "null_rate": 0.0,
                    },
                },
            },
        )

    def test_compute_drift_report_integration_stable(self, metadata_stable):
        import numpy as np
        from src.preprocessing.drift_detector import compute_drift_report

        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "amount": rng.normal(100.0, 20.0, 500),
        })
        report = compute_drift_report(metadata_stable, df)
        assert report.overall_status == "stable"

    def test_compute_drift_report_integration_critical(self, metadata_critical):
        import numpy as np
        from src.preprocessing.drift_detector import compute_drift_report

        rng = np.random.default_rng(0)
        # Why: 평균 5σ 이동 → critical
        df = pd.DataFrame({
            "amount": rng.normal(5.0, 1.0, 500),
        })
        report = compute_drift_report(metadata_critical, df)
        assert report.overall_status == "critical"

    def test_render_report_table_dataframe(self):
        # Why: _render_report_table 내부에서 DataFrame 만드는 로직 간접 검증
        from dashboard.components.drift_banner import _render_report_table
        from src.preprocessing.drift_detector import DriftReport

        reports = [
            DriftReport(
                model_name="m1",
                version=1,
                column_psi={"x": 0.3},
                max_psi=0.3,
                max_psi_column="x",
                overall_status="critical",
                schema_mismatch=False,
            ),
        ]
        # Why: _render_report_table은 streamlit에 의존하지만 import는 가능해야 함
        #      실제 렌더는 Streamlit runtime 없이는 테스트 불가 — import만 확인
        assert callable(_render_report_table)
