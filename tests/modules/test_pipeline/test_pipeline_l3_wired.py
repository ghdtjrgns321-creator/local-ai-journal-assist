"""L3 통계 검증 파이프라인 연결 테스트.

검증 항목:
1. _validate() 호출 시 validate_statistics()가 실제로 호출됨
2. L3 결과의 warnings/flags가 PipelineResult.warnings에 통합됨
3. self._stat_result에 결과가 보관됨
4. validate_statistics() 예외 시 graceful 스킵 (파이프라인 중단 없음)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.pipeline import AuditPipeline
from src.validation.models import (
    AccountStats,
    BenfordResult,
    DistributionStats,
    MonthlyVolatility,
    StatisticalResult,
    TemporalPatternStats,
)


def _make_stat_result(*, with_flags: bool = True) -> StatisticalResult:
    """헬퍼 — 가짜 StatisticalResult 생성."""
    flags = []
    warnings = []
    if with_flags:
        flags = [{"type": "benford_violation", "detail": "MAD=0.025"}]
        warnings = ["L3 사전 경고 메시지"]

    return StatisticalResult(
        total_rows=4,
        analysis_timestamp="2026-04-11T00:00:00Z",
        monthly_volatility=MonthlyVolatility(
            monthly_totals={}, mom_change_rates={},
            outlier_months=[], seasonality_index=None,
        ),
        distribution=DistributionStats(
            shapiro_statistic=None, shapiro_p_value=None, is_normal=None,
            skewness=None, skewness_label=None, kurtosis=None,
            kurtosis_label=None, outlier_concentration=None,
        ),
        benford=BenfordResult(
            sample_size=0, observed={}, expected={}, mad=None,
            mad_conformity="acceptable", chi2_statistic=None, chi2_p_value=None,
            ks_statistic=None, ks_p_value=None, is_conforming=True, confidence="low",
        ),
        account_stats=AccountStats(
            account_count=0, cv_by_account={}, high_cv_accounts=[],
            hhi=0.0, hhi_label="diversified", activity_frequency={},
        ),
        temporal_patterns=TemporalPatternStats(
            weekday_volume={}, weekend_ratio=0.0,
            period_end_concentration=0.0, yoy_change=None,
        ),
        warnings=warnings,
        flags=flags,
    )


class TestL3Wired:
    """L3 호출이 _validate()에 실제로 연결되어 있는지 검증."""

    def test_validate_statistics_is_called(self, small_gl_df):
        """_validate() 실행 시 validate_statistics()가 호출된다."""
        with patch(
            "src.validation.validate_statistics",
            return_value=_make_stat_result(with_flags=False),
        ) as mock_stat:
            AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
            assert mock_stat.called, "validate_statistics 호출 누락 (Dead Code 회귀)"

    def test_warnings_propagate(self, small_gl_df):
        """L3 warnings/flags가 PipelineResult.warnings에 통합된다."""
        with patch(
            "src.validation.validate_statistics",
            return_value=_make_stat_result(with_flags=True),
        ):
            result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        # Why: L3 warning 메시지와 flag 평탄화 메시지 둘 다 포함되어야 함
        assert any("L3 사전 경고 메시지" in w for w in result.warnings)
        assert any("L3 benford_violation" in w for w in result.warnings)

    def test_graceful_on_exception(self, small_gl_df):
        """validate_statistics()가 예외를 던져도 파이프라인은 계속 진행."""
        with patch(
            "src.validation.validate_statistics",
            side_effect=RuntimeError("강제 에러"),
        ):
            # Why: 예외 전파되면 안 됨 — graceful 스킵
            result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert any("L3 통계 검증 스킵" in w for w in result.warnings)
        assert "anomaly_score" in result.data.columns  # 정상 완료 증거

    def test_stat_result_cached_on_pipeline(self, small_gl_df):
        """파이프라인 인스턴스에 _stat_result가 보관된다."""
        stat = _make_stat_result(with_flags=False)
        pipe = AuditPipeline(skip_db=True)
        with patch("src.validation.validate_statistics", return_value=stat):
            pipe.run_from_dataframe(small_gl_df)
        # Why: 후속 단계(대시보드 EDA 탭)에서 재사용 가능해야 함
        assert getattr(pipe, "_stat_result", None) is stat
