"""EDA 테스트용 공통 fixture.

prefix: ed_ (eda profiling)
"""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def ed_full_df() -> pd.DataFrame:
    """원본 13컬럼 + 파생 18컬럼 시뮬레이션, 10행."""
    return pd.DataFrame({
        # 원본 컬럼
        "posting_date": pd.to_datetime([
            "2025-01-01 10:00", "2025-01-04 23:30", "2025-01-05 03:00",
            "2025-01-06 14:00", "2025-01-28 09:00", "2025-01-31 17:00",
            "2025-02-28 12:00", "2025-03-01 08:00", "2025-01-15 11:00",
            "2025-01-20 16:00",
        ]),
        "debit_amount": [45e6, 0, 1e6, 0, 10e6, 5e6, 3e6, 0, 2e6, 8e6],
        "credit_amount": [0, 55e6, 0, 0, 0, 0, 0, 7e6, 0, 0],
        "gl_account": pd.array(
            [4100, 1200, 4200, 9100, 1000, 2000, 3000, 4100, 1200, 9100],
            dtype="Int64",
        ),
        "source": ["SA", "AUTO", "Manual", "수기", None, "SA", "AUTO", "Manual", "SA", None],
        "company_code": ["HQ", "SUB01", "HQ", "INTER", "HQ", "SUB01", "HQ", "INTER", "HQ", "HQ"],
        "line_text": ["가수금 정리", "매출 입금", None, "일반 전표", "가지급금", "결산", "매출", "입금", "정리", None],
        # bool 파생변수 (일부)
        "is_weekend": [False, True, True, False, False, False, False, True, False, False],
        "is_after_hours": [False, True, True, False, False, False, False, False, False, False],
        "is_round_number": [True, False, True, False, True, True, True, False, True, True],
    })


@pytest.fixture()
def ed_numeric_df() -> pd.DataFrame:
    """수치형만 (float64, Int64)."""
    return pd.DataFrame({
        "amount": [100.0, 200.0, 300.0, 400.0, 500.0, 10000.0],
        "count": pd.array([1, 2, 3, 4, 5, 100], dtype="Int64"),
    })


@pytest.fixture()
def ed_mixed_df() -> pd.DataFrame:
    """4개 dtype 모두 포함."""
    return pd.DataFrame({
        "num": [1.0, 2.0, 3.0, 4.0, 5.0],
        "cat": ["A", "B", "A", "C", "B"],
        "dt": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]),
        "flag": [True, False, True, True, False],
    })


@pytest.fixture()
def ed_empty_df() -> pd.DataFrame:
    """0행 빈 DataFrame."""
    return pd.DataFrame({
        "col_a": pd.Series([], dtype="float64"),
        "col_b": pd.Series([], dtype="object"),
    })


@pytest.fixture()
def ed_all_null_df() -> pd.DataFrame:
    """전체 NaN 컬럼 포함."""
    return pd.DataFrame({
        "valid": [1.0, 2.0, 3.0],
        "all_nan": [np.nan, np.nan, np.nan],
        "all_nat": pd.to_datetime([None, None, None]),
    })


@pytest.fixture()
def ed_large_df() -> pd.DataFrame:
    """110만행 — 샘플링 트리거 검증."""
    rng = np.random.default_rng(42)
    n = 1_100_000
    return pd.DataFrame({
        "amount": rng.normal(10_000, 2_000, n),
        "category": rng.choice(["A", "B", "C"], n),
    })
