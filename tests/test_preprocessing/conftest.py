"""preprocessing 테스트 공통 fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.eda.models import ColumnProfile, EDAProfile


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    """테스트용 감사 전표 DataFrame (100행)."""
    rng = np.random.default_rng(42)
    n = 100

    df = pd.DataFrame({
        # 필수 컬럼
        "document_id": [f"DOC-{i:04d}" for i in range(n)],
        "posting_date": pd.date_range("2025-01-01", periods=n, freq="D"),
        "document_date": pd.date_range("2024-12-20", periods=n, freq="D"),
        "gl_account": rng.choice(range(1000, 5000), size=n),
        "debit_amount": rng.exponential(1_000_000, size=n),
        "credit_amount": rng.exponential(500_000, size=n),
        "company_code": rng.choice(["C001", "C002", "C003"], size=n),
        "source": rng.choice(["SAP", "ORACLE", "MANUAL"], size=n),
        "document_type": rng.choice(["SA", "AB", "KR"], size=n),

        # 파생변수 (boolean)
        "is_weekend": rng.choice([True, False], size=n, p=[0.15, 0.85]),
        "is_after_hours": rng.choice([True, False], size=n, p=[0.1, 0.9]),
        "is_period_end": rng.choice([True, False], size=n, p=[0.2, 0.8]),
        "fiscal_period_mismatch": rng.choice([True, False], size=n, p=[0.05, 0.95]),
        "is_holiday": rng.choice([True, False], size=n, p=[0.03, 0.97]),
        "is_near_threshold": rng.choice([True, False], size=n, p=[0.1, 0.9]),
        "exceeds_threshold": rng.choice([True, False], size=n, p=[0.05, 0.95]),
        "is_round_number": rng.choice([True, False], size=n, p=[0.15, 0.85]),
        "is_manual_je": rng.choice([True, False], size=n, p=[0.2, 0.8]),
        "is_intercompany": rng.choice([True, False], size=n, p=[0.1, 0.9]),
        "is_revenue_account": rng.choice([True, False], size=n, p=[0.3, 0.7]),
        "is_suspense_account": rng.choice([True, False], size=n, p=[0.02, 0.98]),

        # 파생변수 (numeric)
        "amount_zscore": rng.normal(0, 1, size=n),
        "amount_magnitude": rng.uniform(3, 10, size=n),
        "days_backdated": rng.choice([0, 1, 5, 10, np.nan], size=n),
        "first_digit": rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, np.nan], size=n),

        # 파생변수 (ordinal text)
        "description_quality": rng.choice(["missing", "poor", "normal"], size=n),
        "has_risk_keyword": rng.choice(["none", "low", "medium", "high"], size=n),

        # 레이블
        "is_fraud": rng.choice([False, True], size=n, p=[0.95, 0.05]),
        "is_anomaly": rng.choice([False, True], size=n, p=[0.90, 0.10]),
    })

    return df


@pytest.fixture()
def sample_profile(sample_df) -> EDAProfile:
    """테스트용 EDAProfile."""
    columns = {}

    for col in sample_df.columns:
        s = sample_df[col]
        missing_rate = float(s.isna().mean())
        unique_count = int(s.nunique())

        # dtype_group 판정
        if pd.api.types.is_bool_dtype(s):
            dtype_group = "boolean"
        elif pd.api.types.is_datetime64_any_dtype(s):
            dtype_group = "datetime"
        elif pd.api.types.is_numeric_dtype(s):
            dtype_group = "numeric"
        else:
            dtype_group = "categorical"

        cp = ColumnProfile(
            name=col,
            dtype=str(s.dtype),
            dtype_group=dtype_group,
            missing_rate=missing_rate,
            unique_count=unique_count,
            mode=str(s.mode().iloc[0]) if not s.mode().empty else None,
        )

        # 범주형 카디널리티
        if dtype_group == "categorical":
            cp.cardinality = unique_count

        columns[col] = cp

    return EDAProfile(
        total_rows=len(sample_df),
        total_columns=len(sample_df.columns),
        memory_bytes=int(sample_df.memory_usage(deep=True).sum()),
        duplicate_rows=0,
        columns=columns,
    )
