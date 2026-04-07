"""VarianceDetector 오케스트레이터 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.prior_data_loader import PriorSummary
from src.detection.variance_layer import VarianceDetector


# ── fixture ────────────────────────────────────────────────


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """12건 — 계정 1000(8건, 1~8월), 계정 2000(4건, 1~4월)."""
    return pd.DataFrame({
        "gl_account": ["1000"] * 8 + ["2000"] * 4,
        "debit_amount": [100.0] * 12,
        "credit_amount": [0.0] * 12,
        "fiscal_period": [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4],
    })


@pytest.fixture
def prior_summary_normal() -> PriorSummary:
    """전기와 당기 거의 동일 → D01/D02 모두 미플래그 기대."""
    return PriorSummary(
        account_aggregates={
            "1000": {"total_amount": 800.0, "count": 8, "avg_amount": 100.0},
            "2000": {"total_amount": 400.0, "count": 4, "avg_amount": 100.0},
        },
        monthly_patterns={
            "1000": {m: 1 / 8 for m in range(1, 9)},
            "2000": {m: 1 / 4 for m in range(1, 5)},
        },
        prior_total_rows=12,
        prior_fiscal_year=2024,
    )


@pytest.fixture
def prior_summary_high_variance() -> PriorSummary:
    """전기 소규모 → 당기 대규모 — D01 플래그 기대."""
    return PriorSummary(
        account_aggregates={
            "1000": {"total_amount": 100.0, "count": 1, "avg_amount": 100.0},
            # 2000은 전기에 없음 → 신규 계정 자동 플래그
        },
        monthly_patterns={
            "1000": {m: 1 / 12 for m in range(1, 13)},
        },
        prior_total_rows=1,
        prior_fiscal_year=2024,
    )


# ── 테스트 ─────────────────────────────────────────────────


class TestVarianceDetectorBasic:
    """VarianceDetector 기본 동작."""

    def test_prior_none_returns_empty(self, sample_df: pd.DataFrame):
        """prior_summary=None → 빈 결과 + 경고 메시지."""
        detector = VarianceDetector(prior_summary=None)
        result = detector.detect(sample_df)

        assert result.track_name == "layer_d"
        assert result.flagged_count == 0
        assert len(result.rule_flags) == 0
        assert any("스킵" in w for w in result.warnings)

    def test_track_name(self):
        """track_name은 'layer_d'."""
        detector = VarianceDetector()
        assert detector.track_name == "layer_d"

    def test_normal_prior_no_flags(
        self, sample_df: pd.DataFrame, prior_summary_normal: PriorSummary
    ):
        """전기/당기 동일 → 플래그 없음."""
        detector = VarianceDetector(prior_summary=prior_summary_normal)
        result = detector.detect(sample_df)

        assert result.track_name == "layer_d"
        assert result.flagged_count == 0

    def test_high_variance_flags_detected(
        self, sample_df: pd.DataFrame, prior_summary_high_variance: PriorSummary
    ):
        """전기 소규모 → 당기 대규모 — D01 플래그 발생."""
        detector = VarianceDetector(prior_summary=prior_summary_high_variance)
        result = detector.detect(sample_df)

        assert result.track_name == "layer_d"
        assert result.flagged_count > 0
        # D01이 실행되었는지 확인
        rule_ids = [rf.rule_id for rf in result.rule_flags]
        assert "D01" in rule_ids


class TestVarianceDetectorEdgeCases:
    """VarianceDetector 엣지 케이스."""

    def test_missing_required_columns(self):
        """필수 컬럼 없으면 빈 결과."""
        df = pd.DataFrame({"some_col": [1, 2, 3]})
        prior = PriorSummary(
            account_aggregates={"1000": {"total_amount": 100.0, "count": 1, "avg_amount": 100.0}},
            monthly_patterns={},
            prior_total_rows=1,
            prior_fiscal_year=2024,
        )
        detector = VarianceDetector(prior_summary=prior)
        result = detector.detect(df)

        assert result.flagged_count == 0
        assert any("컬럼 누락" in w for w in result.warnings)

    def test_d02_runs_with_fiscal_period(
        self, sample_df: pd.DataFrame, prior_summary_normal: PriorSummary
    ):
        """fiscal_period 있으면 D02도 실행."""
        detector = VarianceDetector(prior_summary=prior_summary_normal)
        result = detector.detect(sample_df)

        rule_ids = [rf.rule_id for rf in result.rule_flags]
        assert "D01" in rule_ids
        assert "D02" in rule_ids

    def test_result_scores_shape(
        self, sample_df: pd.DataFrame, prior_summary_normal: PriorSummary
    ):
        """결과 scores의 index가 원본 DataFrame과 일치."""
        detector = VarianceDetector(prior_summary=prior_summary_normal)
        result = detector.detect(sample_df)

        assert len(result.scores) == len(sample_df)
        assert result.scores.index.equals(sample_df.index)

    def test_empty_df_raises(self, prior_summary_normal: PriorSummary):
        """빈 DataFrame → ValueError (validate_input)."""
        df = pd.DataFrame(columns=["gl_account", "debit_amount", "credit_amount"])
        detector = VarianceDetector(prior_summary=prior_summary_normal)
        with pytest.raises(ValueError, match="비어 있습니다"):
            detector.detect(df)
