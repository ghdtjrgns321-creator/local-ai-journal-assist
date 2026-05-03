"""대시보드 테스트 공용 fixture — sample DataFrame + FilterState."""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """WU1 컴포넌트 테스트용 최소 DataFrame (20행).

    Why: general_ledger 핵심 컬럼을 모사하여 차트·필터 단위 테스트에 사용.
    """
    n = 20
    return pd.DataFrame({
        "document_id": [f"DOC{i:04d}" for i in range(1, n + 1)],
        "company_code": ["C001"] * 10 + ["C002"] * 10,
        "fiscal_year": [2024] * n,
        "fiscal_period": list(range(1, 13)) + list(range(1, 9)),
        "posting_date": pd.date_range("2024-01-15", periods=n, freq="18D"),
        "document_date": pd.date_range("2024-01-14", periods=n, freq="18D"),
        "document_type": ["SA", "KR", "KZ", "DR"] * 5,
        "gl_account": ["1100", "2100", "4010", "5010"] * 5,
        "debit_amount": [1_000_000 * (i + 1) for i in range(n)],
        "credit_amount": [0.0] * n,
        "line_text": ["테스트 적요"] * n,
        "header_text": ["테스트 헤더"] * n,
        "created_by": ["user_a", "user_b"] * 10,
        "source": ["Manual", "Automated", "Recurring", "Adjustment"] * 5,
        "business_process": ["P2P", "O2C", "R2R", "H2R", "TRE"] * 4,
        "user_persona": ["junior", "senior", "controller", "manager", "automated_system"] * 4,
        "approved_by": ["mgr_a", "mgr_b"] * 10,
        "risk_level": (["High"] * 3 + ["Medium"] * 5 + ["Low"] * 5 + ["Normal"] * 7),
        "anomaly_score": [0.9, 0.85, 0.75, 0.6, 0.55, 0.5, 0.48, 0.45,
                          0.35, 0.3, 0.28, 0.25, 0.22, 0.15, 0.12,
                          0.1, 0.08, 0.05, 0.03, 0.01],
        "flagged_rules": [
            "L2-01,L3-04", "L1-04,L3-06", "L1-01", "L1-05", "L3-05,L3-06",
            "L3-02", "L3-07", "L1-06", "", "L3-08",
            "L4-03", "L4-04", "L3-09", "", "",
            "", "", "", "", "",
        ],
        "is_fraud": [True] * 3 + [False] * 17,
        "fraud_type": ["DuplicatePayment", "SelfApproval", "ManualJE"] + [""] * 17,
        "is_anomaly": [True] * 8 + [False] * 12,
        "anomaly_type": ["TimingAnomaly"] * 3 + ["AmountAnomaly"] * 5 + [""] * 12,
        "sod_violation": [False] * n,
        "sod_conflict_type": [""] * n,
    })


@pytest.fixture
def single_row_df() -> pd.DataFrame:
    """1행 DataFrame — 경계값 테스트용."""
    return pd.DataFrame({
        "document_id": ["DOC0001"],
        "company_code": ["C001"],
        "fiscal_year": [2024],
        "fiscal_period": [1],
        "posting_date": pd.Timestamp("2024-01-15"),
        "document_date": pd.Timestamp("2024-01-14"),
        "document_type": ["SA"],
        "gl_account": ["1100"],
        "debit_amount": [1_000_000],
        "credit_amount": [0.0],
        "business_process": ["P2P"],
        "user_persona": ["junior"],
        "source": ["Manual"],
        "risk_level": ["High"],
        "anomaly_score": [0.9],
        "flagged_rules": ["L2-01,L3-04"],
        "is_fraud": [True],
        "fraud_type": ["DuplicatePayment"],
        "is_anomaly": [True],
        "anomaly_type": ["TimingAnomaly"],
    })


@pytest.fixture
def large_df() -> pd.DataFrame:
    """10,000행 DataFrame — 샘플링·성능 경계값 테스트용."""
    import numpy as np
    n = 10_000
    rng = np.random.default_rng(42)
    risk_levels = rng.choice(
        ["High", "Medium", "Low", "Normal"],
        size=n,
        p=[0.03, 0.07, 0.15, 0.75],
    )
    scores = rng.uniform(0, 1, size=n)
    return pd.DataFrame({
        "document_id": [f"DOC{i:06d}" for i in range(n)],
        "company_code": rng.choice(["C001", "C002", "C003"], size=n).tolist(),
        "fiscal_period": rng.integers(1, 13, size=n).tolist(),
        "posting_date": pd.date_range("2024-01-01", periods=n, freq="h"),
        "document_type": rng.choice(["SA", "KR", "KZ", "DR"], size=n).tolist(),
        "gl_account": rng.choice(["1100", "2100", "4010", "5010"], size=n).tolist(),
        "debit_amount": rng.lognormal(mean=14, sigma=2, size=n),
        "credit_amount": [0.0] * n,
        "business_process": rng.choice(["P2P", "O2C", "R2R", "H2R", "TRE"], size=n).tolist(),
        "user_persona": rng.choice(
            ["junior", "senior", "controller", "manager", "automated_system"],
            size=n,
        ).tolist(),
        "source": rng.choice(["Manual", "Automated", "Recurring", "Adjustment"], size=n).tolist(),
        "risk_level": risk_levels.tolist(),
        "anomaly_score": scores.tolist(),
        "flagged_rules": rng.choice(
            ["L2-01,L3-04", "L1-01", "L3-06", "L3-02", ""],
            size=n,
        ).tolist(),
        "is_fraud": (risk_levels == "High").tolist(),
        "fraud_type": ["DuplicatePayment" if r == "High" else "" for r in risk_levels],
        "is_anomaly": (risk_levels != "Normal").tolist(),
        "anomaly_type": ["TimingAnomaly" if r != "Normal" else "" for r in risk_levels],
    })


@pytest.fixture
def benford_digits_df() -> pd.DataFrame:
    """Benford 차트 테스트용 9행 DataFrame."""
    import math
    return pd.DataFrame({
        "digit": list(range(1, 10)),
        "observed_freq": [0.32, 0.17, 0.13, 0.09, 0.08, 0.07, 0.06, 0.05, 0.03],
        "expected_freq": [math.log10(1 + 1 / d) for d in range(1, 10)],
        "deviation": [0.02, 0.005, 0.003, 0.01, 0.002, 0.003, 0.005, 0.001, 0.02],
    })
