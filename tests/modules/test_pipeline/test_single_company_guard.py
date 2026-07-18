"""단일 법인 스코프 가드 — 다회사 원장 입력 시 모집단 통계 오염을 경고로 표면화.

근거: CONSTRAINTS.md §단일 법인 분석으로 한정. Benford/D01/D02 는 company_code 를
groupby 키에 포함하지만, 사용자 행동·배치·고액 분포 통계는 그렇지 않아 3개 회사가
한 모집단으로 섞이면 정합하지 않는다.
"""

from __future__ import annotations

import pandas as pd

from src.pipeline import single_company_scope_warnings


def _df(company_codes: list[object]) -> pd.DataFrame:
    return pd.DataFrame({"company_code": company_codes, "debit_amount": [1.0] * len(company_codes)})


def test_single_company_emits_no_warning() -> None:
    assert single_company_scope_warnings(_df(["C001", "C001", "C001"])) == []


def test_multi_company_emits_warning_listing_companies() -> None:
    warnings = single_company_scope_warnings(_df(["C001", "C002", "C003"]))

    assert len(warnings) == 1
    assert "C001" in warnings[0]
    assert "C002" in warnings[0]
    assert "C003" in warnings[0]
    assert "3" in warnings[0]


def test_missing_company_code_column_emits_no_warning() -> None:
    assert single_company_scope_warnings(pd.DataFrame({"debit_amount": [1.0]})) == []


def test_blank_company_codes_are_not_counted_as_companies() -> None:
    """company_code 결측/공백은 회사가 아니다 — 단일회사 + 결측이면 경고 없음."""
    assert single_company_scope_warnings(_df(["C001", None, "", "  ", float("nan")])) == []


def test_multi_company_with_blanks_counts_only_real_companies() -> None:
    warnings = single_company_scope_warnings(_df(["C001", "C002", None, float("nan")]))

    assert len(warnings) == 1
    assert "2" in warnings[0]


def test_empty_frame_emits_no_warning() -> None:
    assert single_company_scope_warnings(pd.DataFrame({"company_code": []})) == []
