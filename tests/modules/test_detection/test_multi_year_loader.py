"""다기간 추정치 데이터 로더 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.company.models import EngagementProfile, EngagementStatus
from src.detection.multi_year_loader import (
    EstimationRecord,
    MultiYearEstimates,
    _compute_errors_and_provisions,
    _compute_net_balance,
    _df_to_records,
    find_multi_year_engagements,
)

import pandas as pd


def _make_engagement(fy: int, status: EngagementStatus = EngagementStatus.COMPLETED) -> EngagementProfile:
    """테스트용 EngagementProfile 생성."""
    return EngagementProfile(
        company_id="c1",
        engagement_id=f"eng_{fy}",
        fiscal_year=fy,
        status=status,
        fiscal_year_start=1,
    )


def _make_repo(engagements: list[EngagementProfile]) -> MagicMock:
    """테스트용 CompanyRepository mock."""
    repo = MagicMock()
    repo.list_engagements.return_value = engagements
    return repo


# ── find_multi_year_engagements ──────────────────────────────


class TestFindMultiYearEngagements:

    def test_3year_complete(self):
        """FY2022~2024 COMPLETED, 당기 FY2025 → 3개 반환."""
        repo = _make_repo([
            _make_engagement(2022),
            _make_engagement(2023),
            _make_engagement(2024),
        ])
        result = find_multi_year_engagements(repo, "c1", 2025, min_years=3)
        assert result is not None
        assert len(result) == 3
        assert [e.fiscal_year for e in result] == [2022, 2023, 2024]

    def test_insufficient_years(self):
        """FY2024만 → 과거 1개 + 당기 1개 = 2개년 < min_years=3 → None."""
        repo = _make_repo([_make_engagement(2024)])
        result = find_multi_year_engagements(repo, "c1", 2025, min_years=3)
        assert result is None

    def test_status_priority(self):
        """같은 연도 DRAFT + COMPLETED → COMPLETED 선택."""
        repo = _make_repo([
            _make_engagement(2023, EngagementStatus.DRAFT),
            _make_engagement(2023, EngagementStatus.COMPLETED),
            _make_engagement(2024),
        ])
        result = find_multi_year_engagements(repo, "c1", 2025, min_years=3)
        assert result is not None
        match_2023 = [e for e in result if e.fiscal_year == 2023]
        assert match_2023[0].status == EngagementStatus.COMPLETED

    def test_max_years_limit(self):
        """max_years=3 → 최근 3개년(FY2022~2024)만."""
        repo = _make_repo([
            _make_engagement(2020),
            _make_engagement(2021),
            _make_engagement(2022),
            _make_engagement(2023),
            _make_engagement(2024),
        ])
        result = find_multi_year_engagements(repo, "c1", 2025, max_years=3, min_years=3)
        assert result is not None
        years = [e.fiscal_year for e in result]
        assert years == [2022, 2023, 2024]

    def test_empty_engagements(self):
        """engagement 없음 → None."""
        repo = _make_repo([])
        result = find_multi_year_engagements(repo, "c1", 2025, min_years=3)
        assert result is None


# ── 유틸리티 함수 ──────────────────────────────────────────


class TestComputeNetBalance:

    def test_credit_normal(self):
        """대변 정상: credit - debit."""
        assert _compute_net_balance(30.0, 100.0, "credit_normal") == 70.0

    def test_debit_normal(self):
        """차변 정상: debit - credit."""
        assert _compute_net_balance(100.0, 30.0, "debit_normal") == 70.0


class TestDfToRecords:

    def test_basic_conversion(self):
        """DataFrame → EstimationRecord dict 변환."""
        df = pd.DataFrame({
            "gl_account": ["1020", "1599"],
            "total_debit": [50.0, 30.0],
            "total_credit": [100.0, 80.0],
            "row_count": [10, 5],
        })
        names = {"1020": "대손충당금", "1599": "감가상각"}
        sign_conv = {"1020": "credit_normal", "1599": "credit_normal"}

        records = _df_to_records(df, 2024, names, sign_conv)

        assert "1020" in records
        assert records["1020"].ending_balance == 50.0  # 100 - 50
        assert records["1020"].account_name == "대손충당금"
        assert records["1599"].ending_balance == 50.0  # 80 - 30


class TestComputeErrorsAndProvisions:

    def test_estimation_error_formula(self):
        """error[t] = total_credit[t-1] - total_debit[t] (설정 vs 상각 분리)."""
        records = {
            "1020": [
                EstimationRecord(2022, "1020", "충당금", 50.0, 30.0, 100.0, 10),
                EstimationRecord(2023, "1020", "충당금", 60.0, 40.0, 110.0, 12),
                EstimationRecord(2024, "1020", "충당금", 70.0, 50.0, 120.0, 15),
            ],
        }
        sign_conv = {"1020": "credit_normal"}

        errors, provisions = _compute_errors_and_provisions(
            records, [2022, 2023, 2024], sign_conv,
        )

        # error[2023] = credit[2022] - debit[2023] = 100 - 40 = 60
        # error[2024] = credit[2023] - debit[2024] = 110 - 50 = 60
        assert errors["1020"] == [60.0, 60.0]

    def test_provision_amounts(self):
        """provision_amounts = total_credit 시계열."""
        records = {
            "1020": [
                EstimationRecord(2022, "1020", "충당금", 50.0, 30.0, 100.0, 10),
                EstimationRecord(2023, "1020", "충당금", 60.0, 40.0, 110.0, 12),
            ],
        }
        sign_conv = {"1020": "credit_normal"}

        _, provisions = _compute_errors_and_provisions(
            records, [2022, 2023], sign_conv,
        )

        assert provisions["1020"] == [100.0, 110.0]

    def test_negative_error_means_underprovision(self):
        """전기 설정 < 당기 상각 → 음수 error (이익 편향)."""
        records = {
            "1020": [
                EstimationRecord(2022, "1020", "충당금", 50.0, 30.0, 50.0, 10),  # 설정 50
                EstimationRecord(2023, "1020", "충당금", 30.0, 80.0, 60.0, 12),  # 상각 80
            ],
        }
        sign_conv = {"1020": "credit_normal"}

        errors, _ = _compute_errors_and_provisions(
            records, [2022, 2023], sign_conv,
        )

        # error = credit[2022] - debit[2023] = 50 - 80 = -30
        assert errors["1020"] == [-30.0]
