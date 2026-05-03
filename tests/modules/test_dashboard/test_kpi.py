"""KPI·데이터 품질 계산 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from dashboard._kpi import compute_kpis, compute_quality

# ── compute_kpis 기본 동작 ───────────────────────────────────


def test_kpis_basic(sample_df):
    """20행 sample_df에서 6개 KPI 정상 계산."""
    kpis = compute_kpis(sample_df)
    assert kpis["total_docs"] == 20
    assert kpis["total_lines"] == 20
    # Why: risk_level != "Normal"인 행 = High 3 + Medium 5 + Low 5 = 13건.
    assert kpis["anomaly_docs"] == 13
    assert kpis["anomaly_rate"] == 65.0
    assert kpis["fraud_suspect"] > 0


def test_kpis_empty_df():
    """빈 DataFrame → 모든 KPI가 0."""
    kpis = compute_kpis(pd.DataFrame())
    assert kpis["total_docs"] == 0
    assert kpis["total_lines"] == 0
    assert kpis["anomaly_amount"] == 0.0
    assert kpis["fraud_suspect"] == 0


def test_kpis_all_normal():
    """전체 Normal → 이상 전표 0, 이상 금액 0."""
    df = pd.DataFrame({
        "document_id": ["D1", "D2", "D3"],
        "risk_level": ["Normal", "Normal", "Normal"],
        "debit_amount": [100, 200, 300],
        "flagged_rules": ["", "", ""],
    })
    kpis = compute_kpis(df)
    assert kpis["anomaly_docs"] == 0
    assert kpis["anomaly_rate"] == 0.0
    assert kpis["anomaly_amount"] == 0.0
    assert kpis["fraud_suspect"] == 0


# ── anomaly_amount 전표 단위 중복 제거 ───────────────────────


def test_anomaly_amount_no_duplicate_counting():
    """동일 전표 내 2라인이 모두 High → 전표 금액은 1회만 합산."""
    df = pd.DataFrame({
        "document_id": ["D1", "D1", "D2"],
        "risk_level": ["High", "High", "Medium"],
        "debit_amount": [1000, 2000, 500],
        "flagged_rules": ["L2-01", "L2-01", "L1-05"],
    })
    kpis = compute_kpis(df)
    # D1: 1000+2000=3000 (전표 합계), D2: 500 → 총 3500
    assert kpis["anomaly_amount"] == 3500
    # 전표 단위이므로 anomaly_docs = 2 (D1, D2)
    assert kpis["anomaly_docs"] == 2


def test_anomaly_amount_low_excluded():
    """Low/Normal 전표는 anomaly_amount에서 제외."""
    df = pd.DataFrame({
        "document_id": ["D1", "D2", "D3"],
        "risk_level": ["Low", "Normal", "High"],
        "debit_amount": [10000, 20000, 500],
        "flagged_rules": ["L3-04", "", "L2-01"],
    })
    kpis = compute_kpis(df)
    # High인 D3만 포함
    assert kpis["anomaly_amount"] == 500


# ── fraud_suspect ────────────────────────────────────────────


def test_fraud_suspect_counts_b_and_l2_l3_rules():
    """flagged_rules에 B 접두사 룰이 있는 전표(document_id) 단위 집계."""
    df = pd.DataFrame({
        "document_id": ["D1", "D1", "D2", "D3"],
        "risk_level": ["High", "High", "Medium", "Normal"],
        "debit_amount": [100, 200, 300, 400],
        "flagged_rules": ["L2-01,L3-04", "L2-01", "L1-01", "L3-02"],
    })
    kpis = compute_kpis(df)
    # Why: D1(L2-01 2라인이지만 전표 1건), D3(L3-02) → 전표 단위 2건
    assert kpis["fraud_suspect"] == 2


# ── compute_quality ──────────────────────────────────────────


def test_quality_basic(sample_df):
    """sample_df 데이터 품질 지표 정상 계산."""
    quality = compute_quality(sample_df)
    assert quality["total_rows"] == 20
    assert quality["total_columns"] > 0
    assert 0 <= quality["completeness"] <= 100


def test_quality_empty():
    """빈 DataFrame → completeness 0."""
    quality = compute_quality(pd.DataFrame())
    assert quality["completeness"] == 0.0
    assert quality["total_rows"] == 0


def test_quality_with_nulls():
    """null 포함 DataFrame → completeness < 100."""
    df = pd.DataFrame({
        "a": [1, None, 3],
        "b": [None, None, None],
    })
    quality = compute_quality(df)
    # a: 1/3 null, b: 3/3 null → 평균 null율 2/3 → completeness ~33.3%
    assert quality["completeness"] == pytest.approx(33.3, abs=0.1)
