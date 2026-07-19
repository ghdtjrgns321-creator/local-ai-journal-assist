"""Pipeline 테스트 공용 fixture."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASYNTH_CSV = PROJECT_ROOT / "data/journal/primary/datasynth/journal_entries.csv"


@pytest.fixture
def small_gl_df() -> pd.DataFrame:
    """최소 GL DataFrame — 필수 컬럼 포함, 4행."""
    return pd.DataFrame({
        "document_id": ["D001", "D001", "D002", "D002"],
        "debit_amount": [1_000_000.0, 0.0, 50_000.0, 0.0],
        "credit_amount": [0.0, 1_000_000.0, 0.0, 50_000.0],
        "gl_account": ["1000", "2000", "1000", "2000"],
        "company_code": ["C1"] * 4,
        "fiscal_year": [2025] * 4,
        "fiscal_period": [6] * 4,
        "posting_date": pd.to_datetime(["2025-06-15"] * 4),
        "document_date": pd.to_datetime(["2025-06-15"] * 4),
        "document_type": ["SA"] * 4,
        "line_number": [1, 2, 1, 2],
    })


@pytest.fixture
def datasynth_csv_path() -> Path:
    """DataSynth CSV 경로 — 파일 부재 시 skip."""
    if not DATASYNTH_CSV.exists():
        pytest.skip("DataSynth CSV 없음")
    return DATASYNTH_CSV
