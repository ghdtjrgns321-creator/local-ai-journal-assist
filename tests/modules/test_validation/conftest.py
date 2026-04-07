"""validation 테스트용 공통 fixture.

prefix: sv_ (schema validator), av_ (accounting validator), vr_ (validation report)
"""

import numpy as np
import pandas as pd
import pytest

from src.validation.models import AccountingResult, SchemaResult


def _make_required_columns(n: int = 5) -> dict:
    """필수 10개 컬럼의 정상 데이터 생성."""
    return {
        "document_id": [f"JE{i:04d}" for i in range(n)],
        "company_code": ["1000"] * n,
        "fiscal_year": pd.array([2025] * n, dtype="Int64"),
        "fiscal_period": pd.array([1] * n, dtype="Int64"),
        "posting_date": pd.to_datetime(
            [f"2025-01-{i + 1:02d}" for i in range(n)]
        ),
        "document_date": pd.to_datetime(
            [f"2025-01-{i + 1:02d}" for i in range(n)]
        ),
        "gl_account": ["1110", "2110", "1110", "4100", "5200"][:n],
        "debit_amount": [100_000.0, 0.0, 50_000.0, 0.0, 200_000.0][:n],
        "credit_amount": [0.0, 100_000.0, 0.0, 50_000.0, 0.0][:n],
        "document_type": ["SA", "SA", "RE", "AB", "SA"][:n],
    }


def _make_optional_columns(n: int = 5) -> dict:
    """권장 컬럼 중 주요 6개 — DataSynth v1.2.0 라벨·승인 컬럼 포함."""
    return {
        "created_by": ["USER01", "USER02", "USER01", None, "USER03"][:n],
        "source": ["manual", "automated", "manual", None, "recurring"][:n],
        "line_text": ["사무용품", "매출입금", None, "복리후생", "교통비"][:n],
        "line_number": pd.array([1, 2, 3, 4, 5], dtype="Int64")[:n],
        "sod_violation": pd.array([False, True, False, None, False], dtype="boolean")[:n],
        "approval_date": pd.to_datetime(
            ["2025-01-02", "2025-01-03", None, "2025-01-05", "2025-01-06"]
        )[:n],
    }


def _make_feature_columns(n: int = 5) -> dict:
    """피처 엔진이 추가하는 18개 컬럼 — L1 검증 대상 외."""
    rng = np.random.default_rng(42)
    return {
        "is_weekend": [False, True, True, False, False][:n],
        "is_after_hours": [False, True, False, False, False][:n],
        "is_period_end": [False, False, False, False, True][:n],
        "days_backdated": pd.array([0, 5, -5, 0, 0], dtype="Int64")[:n],
        "fiscal_period_mismatch": [False] * n,
        "is_holiday": [True, False, False, False, False][:n],
        "is_near_threshold": [False, True, False, False, False][:n],
        "exceeds_threshold": [False, True, False, False, False][:n],
        "amount_zscore": rng.standard_normal(n).tolist(),
        "amount_magnitude": ["medium", "large", "small", "zero", "medium"][:n],
        "is_round_number": [False, False, True, False, False][:n],
        "is_manual_je": [True, False, True, False, True][:n],
        "is_intercompany": [False] * n,
        "is_revenue_account": [False, False, False, True, False][:n],
        "first_digit": pd.array([1, 1, 5, 5, 2], dtype="Int64")[:n],
        "is_suspense_account": [False] * n,
        "description_quality": ["normal", "normal", "poor", "normal", "normal"][:n],
        "has_risk_keyword": [False] * n,
    }


@pytest.fixture()
def sv_valid_df() -> pd.DataFrame:
    """필수 10개 + 권장 4개 + 피처 18개 — 정상 DataFrame."""
    n = 5
    data = {
        **_make_required_columns(n),
        **_make_optional_columns(n),
        **_make_feature_columns(n),
    }
    return pd.DataFrame(data)


@pytest.fixture()
def sv_minimal_df() -> pd.DataFrame:
    """필수 10개만 포함된 최소 DataFrame."""
    return pd.DataFrame(_make_required_columns(5))


@pytest.fixture()
def sv_empty_df() -> pd.DataFrame:
    """행 0건 — 구조만 올바른 빈 DataFrame."""
    data = _make_required_columns(5)
    df = pd.DataFrame(data)
    return df.iloc[:0].copy()


# ── accounting validator fixtures (av_) ───────────────────────


@pytest.fixture()
def av_balanced_df() -> pd.DataFrame:
    """3개 document, 모두 대차일치 — 정상 케이스."""
    return pd.DataFrame({
        "document_id": ["D001", "D001", "D002", "D002", "D003", "D003"],
        "posting_date": pd.to_datetime([
            "2025-01-06", "2025-01-06",  # 월
            "2025-01-07", "2025-01-07",  # 화
            "2025-01-08", "2025-01-08",  # 수
        ]),
        "debit_amount": [100_000.0, 0.0, 50_000.0, 0.0, 200_000.0, 0.0],
        "credit_amount": [0.0, 100_000.0, 0.0, 50_000.0, 0.0, 200_000.0],
        "gl_account": ["1110", "2110", "1110", "4100", "5200", "1110"],
        "document_type": ["SA"] * 6,
        "company_code": ["1000"] * 6,
        "fiscal_year": pd.array([2025] * 6, dtype="Int64"),
        "document_date": pd.to_datetime(["2025-01-06"] * 6),
    })


@pytest.fixture()
def av_unbalanced_df() -> pd.DataFrame:
    """D001 일치, D002 불일치(차변 > 대변 100원)."""
    return pd.DataFrame({
        "document_id": ["D001", "D001", "D002", "D002"],
        "posting_date": pd.to_datetime([
            "2025-01-06", "2025-01-06",
            "2025-01-07", "2025-01-07",
        ]),
        "debit_amount": [100_000.0, 0.0, 50_100.0, 0.0],
        "credit_amount": [0.0, 100_000.0, 0.0, 50_000.0],
        "gl_account": ["1110", "2110", "1110", "4100"],
        "document_type": ["SA"] * 4,
        "company_code": ["1000"] * 4,
        "fiscal_year": pd.array([2025] * 4, dtype="Int64"),
        "document_date": pd.to_datetime(["2025-01-06"] * 4),
    })


@pytest.fixture()
def av_continuous_df() -> pd.DataFrame:
    """2025-01-06(월)~2025-01-10(금) — 영업일 연속."""
    dates = pd.date_range("2025-01-06", "2025-01-10", freq="B")
    n = len(dates)
    return pd.DataFrame({
        "document_id": [f"D{i:03d}" for i in range(n)],
        "posting_date": dates,
        "debit_amount": [10_000.0] * n,
        "credit_amount": [10_000.0] * n,
        "gl_account": ["1110"] * n,
        "document_type": ["SA"] * n,
        "company_code": ["1000"] * n,
        "fiscal_year": pd.array([2025] * n, dtype="Int64"),
        "document_date": dates,
    })


@pytest.fixture()
def av_gap_df() -> pd.DataFrame:
    """2025-01-06(월)~2025-01-10(금) 중 수요일(08) 누락."""
    dates = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-09", "2025-01-10"])
    n = len(dates)
    return pd.DataFrame({
        "document_id": [f"D{i:03d}" for i in range(n)],
        "posting_date": dates,
        "debit_amount": [10_000.0] * n,
        "credit_amount": [10_000.0] * n,
        "gl_account": ["1110"] * n,
        "document_type": ["SA"] * n,
        "company_code": ["1000"] * n,
        "fiscal_year": pd.array([2025] * n, dtype="Int64"),
        "document_date": dates,
    })


@pytest.fixture()
def av_duplicate_df() -> pd.DataFrame:
    """동일 행 2쌍 (원본+중복 = 4행 중 중복 2행)."""
    base = {
        "document_id": ["D001", "D002", "D001", "D002"],
        "posting_date": pd.to_datetime(["2025-01-06"] * 4),
        "debit_amount": [100_000.0, 50_000.0, 100_000.0, 50_000.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "gl_account": ["1110", "2110", "1110", "2110"],
        "document_type": ["SA", "RE", "SA", "RE"],
        "company_code": ["1000"] * 4,
        "fiscal_year": pd.array([2025] * 4, dtype="Int64"),
        "document_date": pd.to_datetime(["2025-01-06"] * 4),
    }
    return pd.DataFrame(base)


@pytest.fixture()
def av_minimal_df() -> pd.DataFrame:
    """금액 컬럼 없음 — graceful degradation 검증."""
    return pd.DataFrame({
        "document_id": ["D001", "D002"],
        "posting_date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
    })


@pytest.fixture()
def av_empty_df() -> pd.DataFrame:
    """0행 DataFrame."""
    return pd.DataFrame({
        "document_id": pd.Series([], dtype="str"),
        "posting_date": pd.Series([], dtype="datetime64[ns]"),
        "debit_amount": pd.Series([], dtype="float64"),
        "credit_amount": pd.Series([], dtype="float64"),
    })


@pytest.fixture()
def av_nan_amounts_df() -> pd.DataFrame:
    """debit/credit에 NaN 포함."""
    return pd.DataFrame({
        "document_id": ["D001", "D001", "D001"],
        "posting_date": pd.to_datetime(["2025-01-06"] * 3),
        "debit_amount": [100_000.0, np.nan, 0.0],
        "credit_amount": [0.0, 50_000.0, np.nan],
    })


@pytest.fixture()
def av_single_date_df() -> pd.DataFrame:
    """모든 행이 동일 날짜."""
    return pd.DataFrame({
        "document_id": ["D001", "D002"],
        "posting_date": pd.to_datetime(["2025-01-06", "2025-01-06"]),
        "debit_amount": [100_000.0, 0.0],
        "credit_amount": [0.0, 100_000.0],
    })


@pytest.fixture()
def av_with_features_df() -> pd.DataFrame:
    """피처 컬럼 포함 — check_duplicates에서 피처 제외 확인용.

    원본 컬럼은 동일(중복), 피처 컬럼만 다른 2행.
    피처 제외 시 중복 1건, 포함 시 중복 0건.
    """
    return pd.DataFrame({
        "document_id": ["D001", "D001"],
        "posting_date": pd.to_datetime(["2025-01-06", "2025-01-06"]),
        "debit_amount": [100_000.0, 100_000.0],
        "credit_amount": [0.0, 0.0],
        "gl_account": ["1110", "1110"],
        "document_type": ["SA", "SA"],
        "company_code": ["1000", "1000"],
        "fiscal_year": pd.array([2025, 2025], dtype="Int64"),
        "document_date": pd.to_datetime(["2025-01-06", "2025-01-06"]),
        # 피처 컬럼 — 값이 다름
        "is_weekend": [False, True],
        "amount_zscore": [0.5, -0.3],
    })


# ── report generator fixtures (vr_) ──────────────────────────


@pytest.fixture()
def vr_sample_df() -> pd.DataFrame:
    """10행 3전표 — report_generator 테스트용."""
    return pd.DataFrame({
        "document_id": ["D001"] * 3 + ["D002"] * 4 + ["D003"] * 3,
        "posting_date": pd.to_datetime([
            "2025-01-06", "2025-01-06", "2025-01-06",
            "2025-01-07", "2025-01-07", "2025-01-07", "2025-01-07",
            "2025-01-08", "2025-01-08", "2025-01-08",
        ]),
        "debit_amount": [100_000.0, 0.0, 0.0, 50_000.0, 0.0, 0.0, 0.0,
                         200_000.0, 0.0, 0.0],
        "credit_amount": [0.0, 60_000.0, 40_000.0, 0.0, 30_000.0, 20_000.0, 0.0,
                          0.0, 100_000.0, 100_000.0],
        "gl_account": [
            "1110", "2110", "4100", "1110", "2110", "4100", "5200", "1110", "2110", "4100",
        ],
    })


@pytest.fixture()
def vr_empty_df() -> pd.DataFrame:
    """0행 DataFrame — edge case."""
    return pd.DataFrame({
        "document_id": pd.Series([], dtype="str"),
        "posting_date": pd.Series([], dtype="datetime64[ns]"),
    })


@pytest.fixture()
def vr_nat_df() -> pd.DataFrame:
    """posting_date 전체 NaT — date_range 방어 로직 검증."""
    return pd.DataFrame({
        "document_id": ["D001", "D002"],
        "posting_date": pd.to_datetime([None, None]),
        "debit_amount": [100.0, 0.0],
        "credit_amount": [0.0, 100.0],
    })


@pytest.fixture()
def vr_schema_valid() -> SchemaResult:
    """L1 통과 — 에러 0건, 경고 0건."""
    return SchemaResult(is_valid=True, errors=[], warnings=[], column_stats={})


@pytest.fixture()
def vr_schema_invalid() -> SchemaResult:
    """L1 실패 — 필수 컬럼 누락 에러."""
    return SchemaResult(
        is_valid=False,
        errors=[
            {"column": "gl_account", "check": "not_nullable", "failure_count": 5},
            {"column": "posting_date", "check": "dtype", "failure_count": 3},
        ],
        warnings=[],
        column_stats={},
    )


@pytest.fixture()
def vr_schema_warnings_only() -> SchemaResult:
    """L1 통과 + 경고 2건."""
    return SchemaResult(
        is_valid=True,
        errors=[],
        warnings=[
            {"column": "line_text", "issue": "high_null_rate", "detail": "결측률 92.0%"},
            {"column": "source", "issue": "high_null_rate", "detail": "결측률 95.0%"},
        ],
        column_stats={},
    )


@pytest.fixture()
def vr_accounting_clean() -> AccountingResult:
    """L2 통과 — 모든 검증 정상."""
    return AccountingResult(
        balance_check=True,
        balance_diff=0.0,
        unbalanced_docs=[],
        date_continuity=True,
        missing_dates=[],
        duplicate_entries=0,
    )


@pytest.fixture()
def vr_accounting_issues() -> AccountingResult:
    """L2 위반 — 대차불일치 2건 + 일자 불연속 + 중복 3건."""
    return AccountingResult(
        balance_check=False,
        balance_diff=150.0,
        unbalanced_docs=["D002", "D003"],
        date_continuity=False,
        missing_dates=["2025-01-08"],
        duplicate_entries=3,
    )
