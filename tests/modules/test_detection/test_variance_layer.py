"""VarianceDetector 오케스트레이터 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from config.settings import AuditSettings
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
        rule_ids = [rf.rule_id for rf in result.rule_flags]
        assert "D01" in rule_ids
        assert result.details["D01"].sum() == 0.0
        assert result.metadata["d01_row_scoring_mode"] == "account_review_metadata_only"
        assert result.metadata["d01_review_account_count"] == 2
        assert result.metadata["d01_review_row_count"] == 12
        accounts = {item["gl_account"] for item in result.metadata["account_activity_variance"]}
        assert accounts == {"1000", "2000"}

    def test_d01_metadata_keeps_company_account_pairs(self):
        """company_code가 있으면 D01 review metadata도 회사별 계정 단위다."""
        df = pd.DataFrame({
            "company_code": ["C001", "C001", "C002", "C002"],
            "gl_account": ["1000", "1000", "1000", "1000"],
            "debit_amount": [500.0, 500.0, 100.0, 100.0],
            "credit_amount": [0.0, 0.0, 0.0, 0.0],
            "fiscal_period": [1, 2, 1, 2],
        })
        prior = PriorSummary(
            account_aggregates={
                "C001::1000": {"total_amount": 100.0, "count": 1, "avg_amount": 100.0},
                "C002::1000": {"total_amount": 200.0, "count": 2, "avg_amount": 100.0},
            },
            monthly_patterns={},
            prior_total_rows=3,
            prior_fiscal_year=2024,
        )
        detector = VarianceDetector(prior_summary=prior)

        result = detector.detect(df)

        assert result.metadata["d01_review_account_count"] == 1
        assert result.metadata["d01_review_row_count"] == 2
        assert result.metadata["account_activity_variance"][0]["company_code"] == "C001"
        assert result.metadata["account_activity_variance"][0]["gl_account"] == "1000"


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

    def test_d02_does_not_create_row_level_scores(self, sample_df: pd.DataFrame):
        """D02는 분석적 검토 신호로만 리포팅하고 row score는 만들지 않는다."""
        prior = PriorSummary(
            account_aggregates={},
            monthly_patterns={"1000": {m: 1 / 12 for m in range(1, 13)}},
            prior_total_rows=12,
            prior_fiscal_year=2024,
        )
        df = pd.DataFrame({
            "gl_account": ["1000"] * 120,
            "debit_amount": [10.0] * 110 + [500.0] * 10,
            "credit_amount": [0.0] * 120,
            "fiscal_period": ([1] * 110) + ([12] * 10),
        })
        detector = VarianceDetector(
            settings=AuditSettings(
                d02_min_account_docs=1,
                d02_min_top_month_delta=0.0,
                min_monthly_data_months=1,
            ),
            prior_summary=prior,
        )

        result = detector.detect(df)

        d02_flag = next(rf for rf in result.rule_flags if rf.rule_id == "D02")
        assert d02_flag.flagged_count == len(df)
        assert result.details["D02"].sum() == 0.0
        assert result.flagged_count == 0

    def test_d02_metadata_keeps_all_flagged_groups_for_evaluation(self):
        """D02 diagnostics metadata is not capped before account-level evaluation."""
        group_count = 105
        rows = []
        monthly_patterns = {}
        for idx in range(group_count):
            account = str(1000 + idx)
            monthly_patterns[f"C001::{account}"] = {month: 1 / 12 for month in range(1, 13)}
            for month in range(1, 13):
                rows.append({
                    "company_code": "C001",
                    "gl_account": account,
                    "document_id": f"D{idx}-{month}",
                    "debit_amount": 500.0 if month == 12 else 10.0,
                    "credit_amount": 0.0,
                    "fiscal_period": month,
                })
        df = pd.DataFrame(rows)
        prior = PriorSummary(
            account_aggregates={},
            monthly_patterns=monthly_patterns,
            prior_total_rows=group_count * 12,
            prior_fiscal_year=2023,
        )
        detector = VarianceDetector(
            settings=AuditSettings(
                monthly_pattern_threshold=0.1,
                d02_min_account_docs=1,
                d02_min_top_month_delta=0.0,
            ),
            prior_summary=prior,
        )

        result = detector.detect(df)
        flagged = [
            item for item in result.metadata["d02_account_diagnostics"]
            if item["flagged"]
        ]

        assert len(flagged) == group_count

    def test_d02_uses_min_monthly_data_months_setting(
        self, sample_df: pd.DataFrame, prior_summary_normal: PriorSummary
    ):
        """settings.min_monthly_data_months를 D02에 전달한다."""
        settings = AuditSettings(min_monthly_data_months=9)
        detector = VarianceDetector(settings=settings, prior_summary=prior_summary_normal)

        result = detector.detect(sample_df)

        d02_flag = next(rf for rf in result.rule_flags if rf.rule_id == "D02")
        assert d02_flag.flagged_count == 0

    def test_result_metadata_documents_operational_limits(
        self, sample_df: pd.DataFrame, prior_summary_normal: PriorSummary
    ):
        """Layer D 결과에는 단독 한계와 위험 조합 메타데이터를 포함한다."""
        detector = VarianceDetector(prior_summary=prior_summary_normal)

        result = detector.detect(sample_df)

        assert result.metadata["operational_limitations"]
        assert "D02" in result.metadata["high_risk_combinations"]
        assert "L3-04" in result.metadata["high_risk_combinations"]["D02"]
        assert result.metadata["d02_guardrails"]["group_keys"] == [
            "company_code",
            "gl_account",
        ]

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
        with pytest.raises(ValueError, match="input DataFrame is empty"):
            detector.detect(df)
