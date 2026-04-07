"""RC-1: AuditPipeline CompanyContext 주입 통합 테스트."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from config.settings import AuditSettings
from src.context import CompanyContext, ContextFactory
from src.pipeline import AuditPipeline, PipelineResult


# ── 하위 호환 ────────────────────────────────────────────────


class TestBackwardCompat:
    """context=None / settings만 전달 시 기존 동작 유지."""

    def test_context_none(self, small_gl_df):
        """AuditPipeline() → create_anonymous 폴백."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        assert isinstance(result, PipelineResult)
        assert "anomaly_score" in result.data.columns

    def test_settings_only(self, small_gl_df):
        """AuditPipeline(settings=s) → from_settings 폴백."""
        settings = AuditSettings()
        result = AuditPipeline(settings=settings, skip_db=True).run_from_dataframe(
            small_gl_df
        )
        assert isinstance(result, PipelineResult)
        assert result.data is not None


# ── Context 주입 ─────────────────────────────────────────────


class TestContextInjection:
    """CompanyContext가 파이프라인 전 구간에 전달되는지 검증."""

    def test_ctx_settings_used(self, small_gl_df):
        """context로 전달한 settings가 실제 사용됨."""
        custom = AuditSettings(balance_tolerance=999.0)
        ctx = ContextFactory.from_settings(custom)
        pipe = AuditPipeline(context=ctx, skip_db=True)

        assert pipe._ctx is ctx
        assert pipe._settings.balance_tolerance == 999.0

    def test_ctx_chart_of_accounts_passed(self, small_gl_df):
        """IntegrityDetector에 ctx.chart_of_accounts 전달."""
        custom_coa = {"1000", "2000", "3000"}
        ctx = ContextFactory.from_settings(AuditSettings())
        ctx = dataclasses.replace(ctx, chart_of_accounts=custom_coa)

        pipe = AuditPipeline(context=ctx, skip_db=True)
        # Why: _run_detection 실행 후 IntegrityDetector가 ctx.coa를 받았는지 간접 검증
        #      — IntegrityDetector 내부의 _coa 속성이 ctx 값과 동일해야 함
        from src.detection.integrity_layer import IntegrityDetector

        original_init = IntegrityDetector.__init__
        captured_coa = {}

        def spy_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured_coa["value"] = self._coa

        with patch.object(IntegrityDetector, "__init__", spy_init):
            pipe._run_detection(small_gl_df)

        assert captured_coa["value"] == custom_coa

    def test_different_context_different_results(self, small_gl_df):
        """서로 다른 approval_thresholds → 탐지 결과 상이."""
        # Why: approval_thresholds가 다르면 is_over_approval 피처가 달라짐
        low_limit = AuditSettings(approval_thresholds=[100.0])
        high_limit = AuditSettings(approval_thresholds=[100_000_000.0])

        ctx_low = ContextFactory.from_settings(low_limit)
        ctx_high = ContextFactory.from_settings(high_limit)

        r_low = AuditPipeline(context=ctx_low, skip_db=True).run_from_dataframe(
            small_gl_df
        )
        r_high = AuditPipeline(context=ctx_high, skip_db=True).run_from_dataframe(
            small_gl_df
        )

        # Why: 임계값이 극단적으로 다르면 anomaly_score 합계가 달라야 함
        score_low = r_low.data["anomaly_score"].sum()
        score_high = r_high.data["anomaly_score"].sum()
        assert score_low != score_high, (
            f"다른 approval_thresholds인데 점수 동일: {score_low}"
        )


# ── batch_id ─────────────────────────────────────────────────


class TestBatchId:
    """batch_id 생성 로직 검증."""

    def test_anonymous_no_prefix(self, small_gl_df):
        """anonymous context → 8자 hex, 접두사 없음."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        assert len(result.batch_id) == 8
        int(result.batch_id, 16)

    def test_engagement_prefix(self, small_gl_df):
        """engagement_id가 batch_id 접두사에 포함."""
        ctx = ContextFactory.from_settings(AuditSettings())
        ctx = dataclasses.replace(ctx, company_id="acme_corp", engagement_id="acme_2025")
        result = AuditPipeline(context=ctx, skip_db=True).run_from_dataframe(
            small_gl_df
        )
        assert result.batch_id.startswith("acme_2025_")

    def test_sanitize_special_chars(self, small_gl_df):
        """engagement_id 특수문자 → 밑줄로 치환."""
        ctx = ContextFactory.from_settings(AuditSettings())
        ctx = dataclasses.replace(ctx, company_id="test_corp", engagement_id="2025-Q1")
        result = AuditPipeline(context=ctx, skip_db=True).run_from_dataframe(
            small_gl_df
        )
        # Why: "-" → "_" 치환 → "2025_Q1_" 접두사
        assert result.batch_id.startswith("2025_Q1_")
        assert "-" not in result.batch_id

    def test_sanitize_slash(self, small_gl_df):
        """engagement_id에 슬래시 → 밑줄로 치환."""
        ctx = ContextFactory.from_settings(AuditSettings())
        ctx = dataclasses.replace(ctx, company_id="test_corp", engagement_id="audit/2025")
        result = AuditPipeline(context=ctx, skip_db=True).run_from_dataframe(
            small_gl_df
        )
        assert result.batch_id.startswith("audit_2025_")
        assert "/" not in result.batch_id


# ── 익명 DB 방어 ─────────────────────────────────────────────


class TestAnonymousDb:
    """anonymous context의 DB 경로 방어 로직."""

    def test_anonymous_uses_memory_db(self, small_gl_df):
        """anonymous context + skip_db=False → :memory: DB 사용."""
        with patch("src.db.connection.get_connection") as mock_conn:
            # Why: get_connection mock으로 path 인자 검증
            import duckdb
            mem_conn = duckdb.connect(":memory:")
            from src.db.schema import initialize_schema
            initialize_schema(mem_conn)
            mock_conn.return_value = mem_conn

            pipe = AuditPipeline(skip_db=False)
            assert pipe._ctx.is_anonymous
            pipe.run_from_dataframe(small_gl_df)

            mock_conn.assert_called_once_with(path=":memory:")
            mem_conn.close()
