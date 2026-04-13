"""Tier 1: 기본 무결성 — 행/전표 레벨 전수 검증."""
from __future__ import annotations

import time

import duckdb

from ..models import CheckResult


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def r1_01_no_double_sided(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R1-01: debit>0 AND credit>0 동시 존재 행 = 0."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE CAST(debit_amount AS DOUBLE) > 0
          AND CAST(credit_amount AS DOUBLE) > 0
    """).fetchone()[0]
    return CheckResult(
        check_id="R1-01", tier=1,
        name="차변/대변 동시 양수",
        status="PASS" if cnt == 0 else "FAIL",
        expected="0건",
        actual=f"{cnt:,}건",
        elapsed_ms=_elapsed(start),
    )


def r1_02_no_zero_lines(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R1-02: debit=0 AND credit=0 행."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE CAST(debit_amount AS DOUBLE) = 0
          AND CAST(credit_amount AS DOUBLE) = 0
    """).fetchone()[0]
    return CheckResult(
        check_id="R1-02", tier=1,
        name="차변/대변 모두 0",
        status="PASS" if cnt == 0 else "WARNING",
        expected="0건",
        actual=f"{cnt:,}건",
        elapsed_ms=_elapsed(start),
    )


def r1_03_header_consistency(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R1-03: 같은 전표 내 header_text 일관성."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id
            FROM je
            GROUP BY document_id
            HAVING COUNT(DISTINCT header_text) > 1
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="R1-03", tier=1,
        name="전표 내 header 일관성",
        status="PASS" if cnt == 0 else "FAIL",
        expected="불일치 0건",
        actual=f"{cnt:,}건 불일치",
        elapsed_ms=_elapsed(start),
    )


def r1_04_doc_field_consistency(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R1-04: 전표 내 헤더 레벨 필드 일관성 (company, date, user 등)."""
    start = _timer()
    # Why: 전표의 모든 라인은 동일한 헤더 필드를 가져야 함
    header_cols = [
        "company_code", "posting_date", "created_by",
        "business_process", "source", "user_persona", "document_type",
    ]
    bad_cols = []
    for col in header_cols:
        cnt = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT document_id FROM je
                GROUP BY document_id
                HAVING COUNT(DISTINCT {col}) > 1
            )
        """).fetchone()[0]
        if cnt > 0:
            bad_cols.append(f"{col}={cnt}")

    status = "PASS" if len(bad_cols) == 0 else "FAIL"
    return CheckResult(
        check_id="R1-04", tier=1,
        name="전표 내 헤더필드 일관성",
        status=status,
        expected="모든 헤더필드 일관",
        actual="OK" if not bad_cols else ", ".join(bad_cols),
        elapsed_ms=_elapsed(start),
    )


def r1_05_date_range(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R1-05: posting_date 범위 (config 기반 2022-01-01 ~ 2024-12-31)."""
    start = _timer()
    total = con.execute("SELECT COUNT(DISTINCT document_id) FROM je").fetchone()[0]
    # Why: 자정 경계(00:00:xx)로 12/31이 넘어갈 수 있어 1일 여유
    out = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE CAST(posting_date AS DATE) < '2022-01-01'
           OR CAST(posting_date AS DATE) > '2025-01-01'
    """).fetchone()[0]
    pct = out / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R1-05", tier=1,
        name="posting_date 범위",
        status="PASS" if pct < 1 else "WARNING",
        expected="범위 밖 <1%",
        actual=f"{out:,}건 ({pct:.2f}%)",
        elapsed_ms=_elapsed(start),
    )


def r1_06_gl_null_rate(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R1-06: GL 계정 NaN 비율."""
    start = _timer()
    total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    null_cnt = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE gl_account IS NULL
           OR CAST(gl_account AS VARCHAR) = ''
           OR CAST(gl_account AS VARCHAR) = 'nan'
    """).fetchone()[0]
    pct = null_cnt / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R1-06", tier=1,
        name="GL 계정 NaN 비율",
        status="PASS" if pct < 3 else "WARNING",
        expected="<3%",
        actual=f"{null_cnt:,}건 ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r1_07_line_number_sequential(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R1-07: line_number 순차성 (1부터 N까지)."""
    start = _timer()
    # Why: 각 전표의 max(line_number)와 count(*)가 같아야 순차
    bad = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id
            FROM je
            GROUP BY document_id
            HAVING MAX(CAST(line_number AS INT))
                != COUNT(*)
                OR MIN(CAST(line_number AS INT)) != 1
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="R1-07", tier=1,
        name="line_number 순차성",
        status="PASS" if bad == 0 else "FAIL",
        expected="전표 100% 순차",
        actual=f"비순차 {bad:,}건",
        elapsed_ms=_elapsed(start),
    )


def run_tier1(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 1 전체 실행."""
    return [
        r1_01_no_double_sided(con),
        r1_02_no_zero_lines(con),
        r1_03_header_consistency(con),
        r1_04_doc_field_consistency(con),
        r1_05_date_range(con),
        r1_06_gl_null_rate(con),
        r1_07_line_number_sequential(con),
    ]
