"""Detection 테스트 공용 fixture."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag


@pytest.fixture
def dt_balanced_df() -> pd.DataFrame:
    """균형 전표 2건 — A01 정상 케이스."""
    return pd.DataFrame({
        "document_id": ["D001", "D001", "D002", "D002"],
        "debit_amount": [100.0, 0.0, 50.0, 0.0],
        "credit_amount": [0.0, 100.0, 0.0, 50.0],
        "gl_account": [1000, 2000, 1000, 2000],
        "company_code": ["C1"] * 4,
        "fiscal_year": [2025] * 4,
        "posting_date": pd.to_datetime(["2025-01-01"] * 4),
        "document_date": pd.to_datetime(["2025-01-01"] * 4),
        "document_type": ["SA"] * 4,
    })


@pytest.fixture
def dt_unbalanced_df() -> pd.DataFrame:
    """D001 균형 + D002 불균형 (차변 100 vs 대변 50) — A01 위반."""
    return pd.DataFrame({
        "document_id": ["D001", "D001", "D002", "D002"],
        "debit_amount": [100.0, 0.0, 100.0, 0.0],
        "credit_amount": [0.0, 100.0, 0.0, 50.0],
        "gl_account": [1000, 2000, 1000, 2000],
        "company_code": ["C1"] * 4,
        "fiscal_year": [2025] * 4,
        "posting_date": pd.to_datetime(["2025-01-01"] * 4),
        "document_date": pd.to_datetime(["2025-01-01"] * 4),
        "document_type": ["SA"] * 4,
    })


@pytest.fixture
def dt_missing_fields_df() -> pd.DataFrame:
    """gl_account NULL 1건, posting_date NaT 1건 — A02 위반."""
    return pd.DataFrame({
        "document_id": ["D001", "D002", "D003"],
        "debit_amount": [100.0, 200.0, 300.0],
        "credit_amount": [100.0, 200.0, 300.0],
        "gl_account": pd.array([1000, None, 3000], dtype=pd.Int64Dtype()),
        "company_code": ["C1", "C1", "C1"],
        "fiscal_year": [2025, 2025, 2025],
        "posting_date": pd.to_datetime(["2025-01-01", pd.NaT, "2025-01-03"]),
        "document_date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
        "document_type": ["SA", "SA", "SA"],
    })


@pytest.fixture
def dt_coa() -> set[str]:
    """테스트용 CoA — 1000, 2000만 유효."""
    return {"1000", "2000"}


# ── ML 통합 테스트용 헬퍼 ─────────────────────────────────────


def make_detection_result(
    track_name: str,
    n: int = 100,
    *,
    score_mean: float = 0.3,
    seed: int = 42,
) -> DetectionResult:
    """합성 DetectionResult 생성 헬퍼."""
    rng = np.random.default_rng(seed)
    scores = pd.Series(rng.uniform(0, score_mean * 2, n).clip(0, 1))
    flagged = scores[scores > 0.5].index.tolist()
    return DetectionResult(
        track_name=track_name,
        flagged_indices=flagged,
        scores=scores,
        rule_flags=[
            RuleFlag(rule_id="T01", rule_name="test", severity=3,
                     flagged_count=len(flagged), total_count=n),
        ],
        details=pd.DataFrame({"T01": scores}),
        metadata={"elapsed": 0.01},
    )
