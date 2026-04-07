"""사이드바 필터 단위 테스트 — apply_filters 각 조건별 독립 검증."""

from __future__ import annotations

import pandas as pd
import pytest

from dashboard.components.filters import apply_filters


# ── 빈 필터 (전체 통과) ───────────────────────────────────────


def test_apply_empty_filters(sample_df):
    """빈 dict이면 전체 데이터 반환."""
    result = apply_filters(sample_df, {})
    assert len(result) == len(sample_df)


def test_apply_empty_df():
    """빈 DataFrame에 필터 적용해도 에러 없이 빈 결과."""
    result = apply_filters(pd.DataFrame(), {"risk_levels": ["High"]})
    assert result.empty


# ── 기본 필터 4개 ──────────────────────────────────────────────


def test_risk_level_filter(sample_df):
    result = apply_filters(sample_df, {"risk_levels": ["High"]})
    assert len(result) > 0
    assert all(result["risk_level"] == "High")


def test_risk_level_multiple(sample_df):
    result = apply_filters(sample_df, {"risk_levels": ["High", "Medium"]})
    assert all(result["risk_level"].isin(["High", "Medium"]))


def test_date_range_filter(sample_df):
    result = apply_filters(sample_df, {"date_range": ("2024-01-01", "2024-03-31")})
    dates = pd.to_datetime(result["posting_date"])
    assert all(dates <= "2024-03-31")


def test_amount_range_filter(sample_df):
    result = apply_filters(sample_df, {"amount_range": (5_000_000, 10_000_000)})
    assert all(result["debit_amount"].between(5_000_000, 10_000_000))


def test_rule_codes_filter(sample_df):
    """flagged_rules CSV 문자열에서 set intersection으로 필터."""
    result = apply_filters(sample_df, {"rule_codes": ["B02"]})
    assert len(result) > 0
    assert all(result["flagged_rules"].str.contains("B02"))


# ── 차원 필터 ──────────────────────────────────────────────────


def test_business_process_filter(sample_df):
    result = apply_filters(sample_df, {"business_processes": ["P2P"]})
    assert all(result["business_process"] == "P2P")


def test_company_code_filter(sample_df):
    result = apply_filters(sample_df, {"company_codes": ["C001"]})
    assert all(result["company_code"] == "C001")


def test_source_filter(sample_df):
    result = apply_filters(sample_df, {"sources": ["Manual"]})
    assert all(result["source"] == "Manual")


# ── 복합 필터 ──────────────────────────────────────────────────


def test_combined_filters(sample_df):
    """여러 필터 동시 적용 — AND 논리."""
    result = apply_filters(sample_df, {
        "risk_levels": ["High", "Medium"],
        "company_codes": ["C001"],
    })
    assert all(result["risk_level"].isin(["High", "Medium"]))
    assert all(result["company_code"] == "C001")


# ── 개발 모드 필터 ────────────────────────────────────────────


def test_fraud_type_filter(sample_df):
    result = apply_filters(sample_df, {"fraud_types": ["DuplicatePayment"]})
    assert len(result) > 0
    assert all(result["fraud_type"] == "DuplicatePayment")


# ── 경계값 테스트 ──────────────────────────────────────────────


def test_single_row_filter(single_row_df):
    """1행 DataFrame 필터 동작."""
    result = apply_filters(single_row_df, {"risk_levels": ["High"]})
    assert len(result) == 1

    result = apply_filters(single_row_df, {"risk_levels": ["Normal"]})
    assert result.empty


def test_rule_codes_filter_multiple(sample_df):
    """여러 룰 코드 동시 필터 — 벡터화 정규식 매칭 검증."""
    result = apply_filters(sample_df, {"rule_codes": ["B02", "A01"]})
    assert len(result) > 0
    assert all(
        result["flagged_rules"].str.contains("B02") | result["flagged_rules"].str.contains("A01")
    )


def test_large_df_filter_performance(large_df):
    """10,000행 필터 — 벡터화 성능 확인 (에러 없이 완료)."""
    result = apply_filters(large_df, {
        "risk_levels": ["High", "Medium"],
        "rule_codes": ["B02", "C01"],
        "company_codes": ["C001"],
    })
    assert all(result["risk_level"].isin(["High", "Medium"]))
    assert all(result["company_code"] == "C001")
