"""preprocessing 테스트 공통 fixtures.

prefix: pp_ (preprocessing)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.eda.models import EDAProfile
from src.eda.profiler import profile_dataframe


@pytest.fixture()
def pp_sample_df() -> pd.DataFrame:
    """테스트용 감사 전표 DataFrame (100행)."""
    rng = np.random.default_rng(42)
    n = 100

    amounts = rng.lognormal(mean=15, sigma=1.5, size=n)
    gl_choices = [1110, 2110, 4100, 5200, 1200]

    return pd.DataFrame({
        "document_id": [f"DOC-{i:04d}" for i in range(n)],
        "posting_date": pd.date_range("2025-01-01", periods=n, freq="h"),
        "document_date": pd.date_range("2025-01-01", periods=n, freq="h"),
        "fiscal_period": pd.array(rng.choice([1, 2, 3], n), dtype="Int64"),
        "debit_amount": amounts,
        "credit_amount": amounts * rng.uniform(0, 0.3, n),
        "gl_account": pd.array(rng.choice(gl_choices, n), dtype="Int64"),
        "source": rng.choice(["SA", "AUTO", "Manual"], n),
        "company_code": rng.choice(["HQ", "SUB01", "INTER"], n),
        "document_type": rng.choice(["SA", "RE", "KR"], n),
        "line_text": rng.choice(["매출 입금", "가수금 정리", "일반 전표", None], n),
        "header_text": rng.choice(["월말 정리", "정상 거래", None], n),
        "is_weekend": rng.choice([True, False], n, p=[0.2, 0.8]),
        "is_after_hours": rng.choice([True, False], n, p=[0.15, 0.85]),
        "amount_zscore": rng.normal(0, 1, n),
        "is_round_number": rng.choice([True, False], n, p=[0.3, 0.7]),
        "is_fraud": rng.choice([True, False], n, p=[0.05, 0.95]),
        "is_anomaly": rng.choice([True, False], n, p=[0.10, 0.90]),
        "description_quality": rng.choice(["high", "medium", "low"], n),
        "has_risk_keyword": rng.choice([True, False], n, p=[0.1, 0.9]),
    })


@pytest.fixture()
def pp_sample_profile(pp_sample_df) -> EDAProfile:
    """테스트용 EDAProfile."""
    return profile_dataframe(pp_sample_df)
