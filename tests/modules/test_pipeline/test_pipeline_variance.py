"""Layer D 파이프라인 통합 테스트 — 전기 대비 변동 탐지."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.company.models import EngagementProfile, EngagementStatus
from src.detection.prior_data_loader import PriorSummary
from src.pipeline import AuditPipeline, PipelineResult


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def sample_prior_summary() -> PriorSummary:
    """테스트용 PriorSummary — 균등 분포 2개 계정."""
    return PriorSummary(
        account_aggregates={
            "1000": {"total_amount": 1_000_000.0, "count": 100, "avg_amount": 10_000.0},
            "2000": {"total_amount": 500_000.0, "count": 50, "avg_amount": 10_000.0},
        },
        monthly_patterns={
            "1000": {m: 1 / 12 for m in range(1, 13)},
            "2000": {m: 1 / 12 for m in range(1, 13)},
        },
        prior_total_rows=1000,
        prior_fiscal_year=2024,
    )


@pytest.fixture
def prior_engagement() -> EngagementProfile:
    """전기 engagement 프로파일."""
    return EngagementProfile(
        engagement_id="test_2024",
        company_id="test_corp",
        fiscal_year=2024,
        status=EngagementStatus.COMPLETED,
    )


@pytest.fixture
def named_ctx(tmp_path):
    """named context — fiscal_year 포함, anonymous 아님."""
    import dataclasses
    from src.context import ContextFactory
    ctx = ContextFactory.create_anonymous()
    return dataclasses.replace(
        ctx,
        company_id="test_corp",
        engagement_id="test_2025",
        fiscal_year=2025,
        db_path=tmp_path / "test_audit.duckdb",
    )


@pytest.fixture
def mock_conn():
    """in-memory DuckDB 커넥션 — _try_variance_detection에서 get_connection 호출 방지."""
    import duckdb
    from src.db.schema import initialize_schema
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def mock_repo():
    """CompanyRepository mock."""
    from src.company.repository import CompanyRepository
    return MagicMock(spec=CompanyRepository)


# ── TC1: anonymous → Layer D 미실행 ─────────────────────────


class TestAnonymousSkipsLayerD:

    def test_anonymous_no_layer_d(self, small_gl_df):
        """anonymous context → 4레이어만, layer_d 없음."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names
        assert len(result.results) == 4


# ── TC2: named + 전기 존재 → 5레이어 ───────────────────────


class TestNamedWithPrior:

    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_five_layers_with_prior(
        self, mock_find, mock_load,
        named_ctx, mock_conn, mock_repo, prior_engagement, sample_prior_summary,
        small_gl_df,
    ):
        """전기 존재 → 5레이어 실행, layer_d 포함."""
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        result = AuditPipeline(
            context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn,
        ).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" in track_names
        assert len(result.results) == 5

    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_layer_d_has_rule_flags(
        self, mock_find, mock_load,
        named_ctx, mock_conn, mock_repo, prior_engagement, sample_prior_summary,
        small_gl_df,
    ):
        """Layer D 결과에 D01/D02 RuleFlag 포함."""
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        result = AuditPipeline(
            context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn,
        ).run_from_dataframe(small_gl_df)

        layer_d = next(r for r in result.results if r.track_name == "layer_d")
        rule_ids = {rf.rule_id for rf in layer_d.rule_flags}
        assert "D01" in rule_ids or "D02" in rule_ids


# ── TC3: named + 전기 미존재 → graceful fallback ───────────


class TestNopriorFallback:

    @patch("src.detection.prior_data_loader.find_prior_engagement", return_value=None)
    def test_no_prior_four_layers(self, _mock, named_ctx, mock_repo, small_gl_df):
        """전기 없음 → 4레이어만."""
        result = AuditPipeline(
            context=named_ctx, skip_db=True, repo=mock_repo,
        ).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names
        assert len(result.results) == 4


# ── TC4: 가중치 자동 전환 ───────────────────────────────────


class TestWeightAutoSelection:

    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_weights_with_prior(
        self, mock_find, mock_load,
        named_ctx, mock_conn, mock_repo, prior_engagement, sample_prior_summary,
        small_gl_df,
    ):
        """Layer D 존재 시 LAYER_WEIGHTS_WITH_PRIOR 적용."""
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        with patch(
            "src.detection.score_aggregator.aggregate_scores",
            wraps=__import__("src.detection.score_aggregator", fromlist=["aggregate_scores"]).aggregate_scores,
        ) as mock_agg:
            result = AuditPipeline(
                context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn,
            ).run_from_dataframe(small_gl_df)

            # Why: aggregate_scores 호출 시 weights가 LAYER_WEIGHTS_WITH_PRIOR인지 확인
            call_kwargs = mock_agg.call_args
            weights = call_kwargs.kwargs.get("weights") or (
                call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None
            )
            assert weights is not None
            # Why: Layer enum 값으로 키가 들어오므로 .value 변환 후 확인
            weight_keys = {k.value if hasattr(k, "value") else k for k in weights}
            assert "layer_d" in weight_keys


# ── TC5: repo=None → 하위 호환 ──────────────────────────────


class TestBackwardCompatNoRepo:

    def test_no_repo_skips_layer_d(self, named_ctx, small_gl_df):
        """repo 미주입 → Layer D 스킵, 기존 동작 유지."""
        result = AuditPipeline(
            context=named_ctx, skip_db=True,
        ).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names
        assert len(result.results) == 4


# ── TC6: Layer D 예외 격리 ──────────────────────────────────


class TestLayerDIsolation:

    def test_layer_d_exception_isolated(self, named_ctx, mock_repo, small_gl_df):
        """Layer D 예외 → 4레이어 정상 완료."""
        with patch(
            "src.detection.prior_data_loader.find_prior_engagement",
            side_effect=RuntimeError("DB 에러"),
        ):
            result = AuditPipeline(
                context=named_ctx, skip_db=True, repo=mock_repo,
            ).run_from_dataframe(small_gl_df)

        assert len(result.results) == 4
        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names


# ── TC7: redetect + Layer D ─────────────────────────────────


class TestRedetectWithVariance:

    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_redetect_includes_layer_d(
        self, mock_find, mock_load,
        named_ctx, mock_conn, mock_repo, prior_engagement, sample_prior_summary,
        small_gl_df,
    ):
        """redetect()에서도 Layer D 재실행."""
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        pipeline = AuditPipeline(context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn)
        # Why: redetect는 피처 완료 DF를 받으므로 먼저 run으로 피처 생성
        first = pipeline.run_from_dataframe(small_gl_df)

        result = pipeline.redetect(first.featured_data)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" in track_names
        assert len(result.results) == 5
