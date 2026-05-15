"""Variance pipeline integration tests."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.company.models import EngagementProfile, EngagementStatus
from src.detection.prior_data_loader import PriorSummary
from src.pipeline import AuditPipeline


@pytest.fixture
def sample_prior_summary() -> PriorSummary:
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
    return EngagementProfile(
        engagement_id="test_2024",
        company_id="test_corp",
        fiscal_year=2024,
        status=EngagementStatus.COMPLETED,
    )


@pytest.fixture
def named_ctx(tmp_path):
    from src.context import ContextFactory

    ctx = ContextFactory.create_anonymous()
    settings = ctx.settings.model_copy(update={"enable_variance_detection": True})
    return dataclasses.replace(
        ctx,
        company_id="test_corp",
        engagement_id="test_2025",
        fiscal_year=2025,
        db_path=tmp_path / "test_audit.duckdb",
        settings=settings,
    )


@pytest.fixture
def mock_conn():
    import duckdb

    from src.db.schema import initialize_schema

    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def mock_repo():
    from src.company.repository import CompanyRepository

    return MagicMock(spec=CompanyRepository)


class TestAnonymousSkipsLayerD:
    def test_anonymous_no_layer_d(self, small_gl_df):
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names
        assert {"layer_a", "layer_b", "layer_c", "benford"}.issubset(track_names)
        assert "evidence" not in track_names


class TestNamedWithPrior:
    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_five_layers_with_prior(
        self,
        mock_find,
        mock_load,
        named_ctx,
        mock_conn,
        mock_repo,
        prior_engagement,
        sample_prior_summary,
        small_gl_df,
    ):
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        result = AuditPipeline(
            context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn
        ).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" in track_names
        assert {
            "layer_a", "layer_b", "layer_c", "benford", "layer_d",
        }.issubset(track_names)
        assert "evidence" not in track_names

    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_layer_d_has_rule_flags(
        self,
        mock_find,
        mock_load,
        named_ctx,
        mock_conn,
        mock_repo,
        prior_engagement,
        sample_prior_summary,
        small_gl_df,
    ):
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        result = AuditPipeline(
            context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn
        ).run_from_dataframe(small_gl_df)

        layer_d = next(r for r in result.results if r.track_name == "layer_d")
        rule_ids = {rf.rule_id for rf in layer_d.rule_flags}
        assert "D01" in rule_ids or "D02" in rule_ids


class TestNopriorFallback:
    @patch("src.detection.prior_data_loader.find_prior_engagement", return_value=None)
    def test_no_prior_four_layers(self, _mock, named_ctx, mock_repo, small_gl_df):
        result = AuditPipeline(
            context=named_ctx, skip_db=True, repo=mock_repo
        ).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names
        assert {"layer_a", "layer_b", "layer_c", "benford"}.issubset(track_names)
        assert "evidence" not in track_names


class TestWeightAutoSelection:
    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_weights_with_prior(
        self,
        mock_find,
        mock_load,
        named_ctx,
        mock_conn,
        mock_repo,
        prior_engagement,
        sample_prior_summary,
        small_gl_df,
    ):
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        with patch(
            "src.detection.score_aggregator.aggregate_scores",
            wraps=__import__(
                "src.detection.score_aggregator", fromlist=["aggregate_scores"]
            ).aggregate_scores,
        ) as mock_agg:
            AuditPipeline(
                context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn
            ).run_from_dataframe(small_gl_df)

            call_kwargs = mock_agg.call_args
            weights = call_kwargs.kwargs.get("weights") or (
                call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None
            )
            assert weights is None


class TestBackwardCompatNoRepo:
    def test_no_repo_skips_layer_d(self, named_ctx, small_gl_df):
        result = AuditPipeline(context=named_ctx, skip_db=True).run_from_dataframe(
            small_gl_df
        )

        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names
        assert {"layer_a", "layer_b", "layer_c", "benford"}.issubset(track_names)
        assert "evidence" not in track_names


class TestLayerDIsolation:
    def test_layer_d_exception_isolated(self, named_ctx, mock_repo, small_gl_df):
        with patch(
            "src.detection.prior_data_loader.find_prior_engagement",
            side_effect=RuntimeError("DB error"),
        ):
            result = AuditPipeline(
                context=named_ctx, skip_db=True, repo=mock_repo
            ).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" not in track_names
        assert {"layer_a", "layer_b", "layer_c", "benford"}.issubset(track_names)
        assert "evidence" not in track_names


class TestRedetectWithVariance:
    @patch("src.detection.prior_data_loader.load_prior_summary")
    @patch("src.detection.prior_data_loader.find_prior_engagement")
    def test_redetect_includes_layer_d(
        self,
        mock_find,
        mock_load,
        named_ctx,
        mock_conn,
        mock_repo,
        prior_engagement,
        sample_prior_summary,
        small_gl_df,
    ):
        mock_find.return_value = prior_engagement
        mock_load.return_value = sample_prior_summary
        mock_repo.db_path.return_value = Path("/fake/prior.duckdb")

        pipeline = AuditPipeline(
            context=named_ctx, skip_db=True, repo=mock_repo, conn=mock_conn
        )
        first = pipeline.run_from_dataframe(small_gl_df)
        result = pipeline.redetect(first.featured_data)

        track_names = {r.track_name for r in result.results}
        assert "layer_d" in track_names
        assert {
            "layer_a", "layer_b", "layer_c", "benford", "layer_d",
        }.issubset(track_names)
        assert "evidence" not in track_names
