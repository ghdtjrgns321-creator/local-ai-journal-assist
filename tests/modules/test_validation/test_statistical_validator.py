"""L3 통계 검증 오케스트레이터 통합 테스트."""

import json

import numpy as np
import pandas as pd
import pytest

from config.settings import AuditSettings
from src.validation.statistical_validator import result_to_dict, validate_statistics


@pytest.fixture()
def settings() -> AuditSettings:
    return AuditSettings()


def _make_full_df(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """통합 테스트용 정상 DataFrame 생성.

    필수 컬럼 + first_digit 포함, 12개월 분산.
    """
    rng = np.random.default_rng(seed)
    months = rng.integers(1, 13, size=n)
    days = rng.integers(1, 29, size=n)

    dates = pd.to_datetime([f"2024-{m:02d}-{d:02d}" for m, d in zip(months, days)])
    amounts = rng.lognormal(10, 1.5, size=n)

    # Benford 분포를 따르는 첫째자리
    benford_probs = [0.301, 0.176, 0.125, 0.097, 0.079, 0.067, 0.058, 0.051, 0.046]
    first_digits = rng.choice(range(1, 10), size=n, p=benford_probs)

    return pd.DataFrame({
        "posting_date": dates,
        "debit_amount": amounts,
        "credit_amount": np.where(rng.random(n) > 0.5, amounts * 0.1, 0.0),
        "gl_account": pd.array(rng.choice([1110, 2110, 4100, 5200], size=n), dtype="Int64"),
        "document_id": [f"JE{i:05d}" for i in range(n)],
        "first_digit": pd.array(first_digits, dtype="Int64"),
    })


class TestValidateStatistics:

    def test_full_dataframe_all_fields_populated(self, settings):
        """정상 DataFrame → 모든 필드 populated."""
        df = _make_full_df()
        result = validate_statistics(df, settings=settings)

        assert result.total_rows == 500
        assert result.analysis_timestamp
        assert len(result.monthly_volatility.monthly_totals) > 0
        assert result.distribution.shapiro_statistic is not None
        assert result.benford.sample_size > 0
        assert result.account_stats.account_count > 0
        assert len(result.temporal_patterns.weekday_volume) > 0

    def test_missing_columns_graceful(self, settings):
        """최소 컬럼만 → 경고 누적, crash 없음."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2024-01-15"] * 20),
            "debit_amount": [100.0] * 20,
        })
        result = validate_statistics(df, settings=settings)

        assert result.total_rows == 20
        assert len(result.warnings) > 0  # gl_account 부재 등

    def test_empty_dataframe(self, settings):
        """빈 DataFrame → crash 없이 빈 결과."""
        df = pd.DataFrame({
            "posting_date": pd.Series([], dtype="datetime64[ns]"),
            "debit_amount": pd.Series([], dtype="float64"),
            "credit_amount": pd.Series([], dtype="float64"),
        })
        result = validate_statistics(df, settings=settings)

        assert result.total_rows == 0
        assert result.benford.sample_size == 0

    def test_flags_collected(self, settings):
        """이상 징후 발생 시 flags 목록 생성."""
        df = _make_full_df(n=1000)
        result = validate_statistics(df, settings=settings)

        # flags는 list[dict] 형태
        assert isinstance(result.flags, list)
        for flag in result.flags:
            assert "type" in flag
            assert "detail" in flag


class TestResultToDict:

    def test_json_roundtrip(self, settings):
        """result_to_dict → json.dumps → json.loads 왕복 성공."""
        df = _make_full_df(200)
        result = validate_statistics(df, settings=settings)
        d = result_to_dict(result)

        # JSON 직렬화 성공 확인
        json_str = json.dumps(d, ensure_ascii=False)
        loaded = json.loads(json_str)

        assert loaded["total_rows"] == 200
        assert "benford" in loaded
        assert "monthly_volatility" in loaded

    def test_no_numpy_types(self, settings):
        """dict 내 numpy 타입 잔존 여부 확인."""
        df = _make_full_df(100)
        result = validate_statistics(df, settings=settings)
        d = result_to_dict(result)

        def _check_no_numpy(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _check_no_numpy(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _check_no_numpy(v, f"{path}[{i}]")
            else:
                assert not isinstance(obj, (np.integer, np.floating, np.bool_)), \
                    f"numpy type at {path}: {type(obj)}"

        _check_no_numpy(d)

    def test_first_digit_fallback(self, settings):
        """first_digit 없는 DataFrame → 내부 재계산 fallback."""
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2024-01-15"] * 200),
            "debit_amount": rng.lognormal(10, 1, size=200),
            "credit_amount": [0.0] * 200,
            "gl_account": pd.array([1110] * 200, dtype="Int64"),
        })
        # first_digit 컬럼 없음
        result = validate_statistics(df, settings=settings)

        assert result.benford.sample_size > 0
