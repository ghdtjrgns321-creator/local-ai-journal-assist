"""DB 모듈 테스트 공용 픽스처.

Prefix: db_ (connection/schema/loader/queries 공용)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import pandas as pd
import pytest

from src.db.schema import initialize_schema


# ── 커넥션 픽스처 ────────────────────────────────────────────


@pytest.fixture()
def db_conn():
    """테스트용 in-memory DuckDB 커넥션 (스키마 초기화 포함)."""
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def db_raw_conn():
    """스키마 미초기화 in-memory 커넥션 — schema 테스트용."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


# ── 샘플 DataFrame 픽스처 ────────────────────────────────────


@pytest.fixture()
def db_sample_df() -> pd.DataFrame:
    """GL 적재용 최소 DataFrame (3행, 필수 컬럼 + 탐지 결과)."""
    return pd.DataFrame({
        "document_id": ["JE-001", "JE-001", "JE-002"],
        "company_code": ["C001", "C001", "C001"],
        "fiscal_year": [2022, 2022, 2022],
        "fiscal_period": [1, 1, 1],
        "posting_date": pd.to_datetime(["2022-01-10", "2022-01-10", "2022-01-15"]),
        "document_date": pd.to_datetime(["2022-01-10", "2022-01-10", "2022-01-15"]),
        "document_type": ["SA", "SA", "KR"],
        "gl_account": ["1000", "2000", "1200"],
        "debit_amount": [5_000_000.0, 0.0, 200_000_000.0],
        "credit_amount": [0.0, 5_000_000.0, 0.0],
        "line_number": [1, 2, 1],
        "created_by": ["USR-JA-001", "USR-JA-001", "USR-SA-001"],
        "source": ["Manual", "Manual", "Automated"],
        "business_process": ["R2R", "R2R", "P2P"],
        "anomaly_score": [0.6, 0.6, 0.3],
        "risk_level": ["Medium", "Medium", "Normal"],
        "flagged_rules": ["A01,B03", "A01,B03", ""],
    })


@pytest.fixture()
def db_large_df() -> pd.DataFrame:
    """승인 레벨 파생 테스트용 — 6단계 금액 범위 커버."""
    amounts = [
        5_000_000,        # Level 1 (≤1천만)
        50_000_000,       # Level 2 (≤1억)
        500_000_000,      # Level 3 (≤10억)
        3_000_000_000,    # Level 4 (≤50억)
        8_000_000_000,    # Level 5 (≤100억)
        50_000_000_000,   # Level 6 (>100억)
    ]
    return pd.DataFrame({
        "document_id": [f"JE-{i:03d}" for i in range(6)],
        "company_code": ["C001"] * 6,
        "fiscal_year": [2022] * 6,
        "fiscal_period": [1] * 6,
        "posting_date": pd.to_datetime(["2022-01-10"] * 6),
        "document_date": pd.to_datetime(["2022-01-10"] * 6),
        "document_type": ["SA"] * 6,
        "gl_account": ["1000"] * 6,
        "debit_amount": [float(a) for a in amounts],
        "credit_amount": [0.0] * 6,
        "line_number": list(range(1, 7)),
        "created_by": ["USR-JA-001"] * 6,
        "source": ["Manual"] * 6,
        "business_process": ["R2R"] * 6,
        "anomaly_score": [0.0] * 6,
        "risk_level": ["Normal"] * 6,
        "flagged_rules": [""] * 6,
    })


# ── Mock DetectionResult ─────────────────────────────────────


@dataclass
class MockDetectionResult:
    """테스트용 DetectionResult 대체."""

    track_name: str
    details: pd.DataFrame
    metadata: dict = field(default_factory=dict)


@pytest.fixture()
def db_detection_results(db_sample_df) -> list[MockDetectionResult]:
    """샘플 DetectionResult 리스트 (layer_b 1개)."""
    details = pd.DataFrame(
        {"B01": [0.0, 0.0, 0.6], "B03": [0.8, 0.8, 0.0]},
        index=db_sample_df.index,
    )
    return [MockDetectionResult(track_name="layer_b", details=details)]


# ── Mock BenfordResult ───────────────────────────────────────


@dataclass
class MockBenfordResult:
    """테스트용 BenfordResult 대체."""

    sample_size: int = 1000
    observed: dict = field(default_factory=lambda: {
        1: 0.301, 2: 0.176, 3: 0.125, 4: 0.097,
        5: 0.079, 6: 0.067, 7: 0.058, 8: 0.051, 9: 0.046,
    })
    expected: dict = field(default_factory=lambda: {
        1: 0.301, 2: 0.176, 3: 0.125, 4: 0.097,
        5: 0.079, 6: 0.067, 7: 0.058, 8: 0.051, 9: 0.046,
    })
    mad: float = 0.003
    mad_conformity: str = "close"
    chi2_statistic: float = 5.2
    chi2_p_value: float = 0.74
    ks_statistic: float = 0.02
    ks_p_value: float = 0.95
    is_conforming: bool = True
    confidence: str = "high"


@pytest.fixture()
def db_benford_results() -> list[MockDetectionResult]:
    """BenfordResult 포함 DetectionResult (layer_c)."""
    details = pd.DataFrame({"C07": [0.0, 0.0, 0.0]})
    return [
        MockDetectionResult(
            track_name="layer_c",
            details=details,
            metadata={"benford_result": MockBenfordResult()},
        ),
    ]
