"""TrendBreakDetector 오케스트레이터 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.multi_year_loader import EstimationRecord, MultiYearEstimates
from src.detection.trendbreak_detector import TrendBreakDetector


def _make_estimates(
    *,
    errors: dict[str, list[float]] | None = None,
    provisions: dict[str, list[float]] | None = None,
) -> MultiYearEstimates:
    """테스트용 MultiYearEstimates 생성 헬퍼."""
    errors = errors or {"1020": [-50.0, -60.0, -70.0]}
    provisions = provisions or {"1020": [100.0, 90.0, 80.0, 70.0]}
    records_by_account = {
        acct: [
            EstimationRecord(
                fiscal_year=2022 + i,
                gl_account=acct,
                account_name="테스트",
                ending_balance=100.0,
                total_debit=50.0,
                total_credit=p,
                row_count=10,
            )
            for i, p in enumerate(prov)
        ]
        for acct, prov in provisions.items()
    }
    return MultiYearEstimates(
        records_by_account=records_by_account,
        fiscal_years=[2022, 2023, 2024, 2025],
        estimation_errors=errors,
        provision_amounts=provisions,
        current_fiscal_year=2025,
    )


def _make_df(accounts: list[str] | None = None) -> pd.DataFrame:
    """테스트용 DataFrame 생성."""
    accounts = accounts or ["1020", "1020", "1599", "4000"]
    return pd.DataFrame({
        "gl_account": accounts,
        "debit_amount": [100.0] * len(accounts),
        "credit_amount": [100.0] * len(accounts),
    })


class TestTrendBreakDetector:
    """TrendBreakDetector 오케스트레이터 테스트."""

    def test_track_name(self):
        det = TrendBreakDetector()
        assert det.track_name == "trendbreak"

    def test_estimates_none_returns_empty(self):
        """estimates=None → 빈 결과 + 경고."""
        det = TrendBreakDetector(multi_year_estimates=None)
        df = _make_df()
        result = det.detect(df)
        assert result.track_name == "trendbreak"
        assert result.flagged_count == 0
        assert any("다기간" in w for w in result.warnings)

    def test_no_gl_account_column(self):
        """gl_account 컬럼 없음 → 빈 결과."""
        det = TrendBreakDetector(multi_year_estimates=_make_estimates())
        df = pd.DataFrame({"amount": [100.0]})
        result = det.detect(df)
        assert result.flagged_count == 0

    def test_bias_flags_rows(self):
        """TB01 bias 계정(1020) → 해당 계정 행만 flagged."""
        # 모든 error 음수 → bias_ratio=1.0 → 플래그
        estimates = _make_estimates(
            errors={"1020": [-50.0, -60.0, -70.0]},
            provisions={"1020": [100.0, 105.0, 98.0, 102.0]},
        )
        det = TrendBreakDetector(multi_year_estimates=estimates)
        df = _make_df(["1020", "1020", "4000", "4000"])
        result = det.detect(df)

        # 1020 행(index 0,1)만 flagged
        assert result.scores.iloc[0] > 0
        assert result.scores.iloc[1] > 0
        assert result.scores.iloc[2] == 0.0
        assert result.scores.iloc[3] == 0.0

    def test_scores_shape_matches_df(self):
        """scores.index == df.index."""
        det = TrendBreakDetector(multi_year_estimates=_make_estimates())
        df = _make_df()
        result = det.detect(df)
        assert len(result.scores) == len(df)
        assert result.scores.index.equals(df.index)

    def test_both_rules_run(self):
        """TB01 + TB02 모두 실행 → rule_flags에 존재."""
        det = TrendBreakDetector(multi_year_estimates=_make_estimates())
        df = _make_df()
        result = det.detect(df)

        rule_ids = {rf.rule_id for rf in result.rule_flags}
        assert "TB01" in rule_ids
        assert "TB02" in rule_ids

    def test_rule_failure_isolation(self):
        """TB01 실패해도 TB02는 정상 실행."""
        # estimation_errors를 잘못된 타입으로 주입하여 TB01 실패 유도
        estimates = _make_estimates()
        # TB01의 estimation_errors를 None으로 → TypeError 발생
        bad_estimates = MultiYearEstimates(
            records_by_account=estimates.records_by_account,
            fiscal_years=estimates.fiscal_years,
            estimation_errors=None,  # type: ignore[arg-type]
            provision_amounts=estimates.provision_amounts,
            current_fiscal_year=2025,
        )
        det = TrendBreakDetector(multi_year_estimates=bad_estimates)
        df = _make_df()
        result = det.detect(df)

        # TB01 실패, TB02는 정상 → skipped에 TB01 포함
        assert "TB01" in result.metadata.get("skipped_rules", [])
        rule_ids = {rf.rule_id for rf in result.rule_flags}
        assert "TB02" in rule_ids
