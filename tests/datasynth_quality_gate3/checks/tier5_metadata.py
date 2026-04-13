"""Tier 5: 메타데이터 정합성 — local_amount, reference, dates, GL 체계."""
from __future__ import annotations

import time

import duckdb

from ..models import CheckResult


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def r5_01_local_amount(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-01: 정상 전표의 local_amount ≠ debit/credit (<=0.5%)."""
    start = _timer()
    # Why: 비정상 전표의 불일치는 anomaly injection 결과일 수 있으므로 정상만 검사
    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE
                WHEN local_amount IS NOT NULL
                 AND ABS(CAST(local_amount AS DOUBLE)
                     - CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                            THEN CAST(debit_amount AS DOUBLE)
                            ELSE CAST(credit_amount AS DOUBLE) END) > 1
                THEN 1 ELSE 0 END) AS mismatch
        FROM je
        WHERE (CAST(debit_amount AS DOUBLE) > 0
               OR CAST(credit_amount AS DOUBLE) > 0)
          AND is_fraud != 'true' AND is_anomaly != 'true'
    """).fetchone()
    total, mismatch = row[0] or 0, row[1] or 0
    pct = mismatch / total * 100 if total > 0 else 0

    neg = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE CAST(local_amount AS DOUBLE) < 0
          AND is_fraud != 'true' AND is_anomaly != 'true'
    """).fetchone()[0]

    return CheckResult(
        check_id="R5-01", tier=5,
        name="정상전표 local_amount 불일치",
        status="PASS" if pct <= 0.5 else "FAIL",
        expected="정상전표 <=0.5%",
        actual=f"정상 {mismatch:,}/{total:,} ({pct:.1f}%), 정상 음수 {neg:,}건",
        detail={"normal_mismatch_pct": round(pct, 2), "normal_negative": neg},
        elapsed_ms=_elapsed(start),
    )


def r5_02_reference_year(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-02: reference 연도 ≠ posting_date 연도 (<=1%)."""
    start = _timer()
    row = con.execute("""
        WITH refs AS (
            SELECT DISTINCT ON (document_id)
                document_id,
                reference,
                EXTRACT(YEAR FROM CAST(posting_date AS TIMESTAMP))::INT AS post_year,
                REGEXP_EXTRACT(reference, '-(\\d{4})-', 1) AS ref_year
            FROM je
            WHERE reference IS NOT NULL
        )
        SELECT
            COUNT(*) FILTER (WHERE ref_year IS NOT NULL
                             AND ref_year != '') AS total,
            COUNT(*) FILTER (WHERE ref_year IS NOT NULL
                             AND ref_year != ''
                             AND TRY_CAST(ref_year AS INT) IS NOT NULL
                             AND TRY_CAST(ref_year AS INT) != post_year) AS mismatch
        FROM refs
    """).fetchone()
    total, mismatch = row[0], row[1]
    pct = mismatch / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R5-02", tier=5,
        name="reference 연도 불일치",
        status="PASS" if pct <= 1 else "WARNING",
        expected="<=1%",
        actual=f"{mismatch:,}/{total:,} ({pct:.3f}%)",
        elapsed_ms=_elapsed(start),
    )


def r5_03_approval_gap(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-03: approval_date - posting_date 극단값 (|gap| > 30일 <= 0.1%)."""
    start = _timer()
    row = con.execute("""
        WITH doc AS (
            SELECT DISTINCT ON (document_id)
                document_id,
                CAST(posting_date AS DATE) AS pd,
                CAST(approval_date AS DATE) AS ad
            FROM je
            WHERE approval_date IS NOT NULL
        )
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE ABS(DATEDIFF('day', pd, ad)) > 30) AS extreme
        FROM doc
    """).fetchone()
    total, extreme = row[0], row[1]
    pct = extreme / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R5-03", tier=5,
        name="승인-전기 간격 극단값 (>30일)",
        status="PASS" if pct <= 0.1 else "WARNING",
        expected="<=0.1%",
        actual=f"{extreme:,}/{total:,} ({pct:.3f}%)",
        elapsed_ms=_elapsed(start),
    )


def r5_04_tax_free_ratio(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-04: 면세 거래 — Phase 3 Tax 모듈 scope. 현재 SKIP."""
    start = _timer()
    return CheckResult(
        check_id="R5-04", tier=5,
        name="면세 거래 비율",
        status="SKIP",
        expected="Phase 3 Tax 모듈 scope",
        actual="현재 미구현 (설계 의도)",
        elapsed_ms=_elapsed(start),
    )


def r5_05_gl_digit_mix(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-05: GL 4자리/6자리 혼합 전표 비율 (<=50%)."""
    start = _timer()
    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN gl_len_cnt > 1 THEN 1 ELSE 0 END) AS mixed
        FROM (
            SELECT document_id,
                   COUNT(DISTINCT LENGTH(CAST(gl_account AS VARCHAR))) AS gl_len_cnt
            FROM je
            WHERE gl_account IS NOT NULL
              AND CAST(gl_account AS VARCHAR) != ''
              AND CAST(gl_account AS VARCHAR) != 'nan'
            GROUP BY document_id
        )
    """).fetchone()
    total, mixed = row
    pct = mixed / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R5-05", tier=5,
        name="GL 4/6자리 혼합 전표",
        status="PASS" if pct <= 50 else "WARNING",
        expected="<=50%",
        actual=f"{mixed:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r5_06_tax_code_fill(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-06: tax_code — Phase 3 Tax 모듈 scope. 현재 SKIP."""
    start = _timer()
    return CheckResult(
        check_id="R5-06", tier=5,
        name="tax_code/tax_amount 채움률",
        status="SKIP",
        expected="Phase 3 Tax 모듈 scope",
        actual="현재 미구현 (설계 의도)",
        elapsed_ms=_elapsed(start),
    )


def r5_07_ic_header_language(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-07: IC 전표 header가 영어 + line_text NaN."""
    start = _timer()
    row = con.execute("""
        WITH ic_docs AS (
            SELECT DISTINCT document_id FROM je
            WHERE document_type = 'IC'
        )
        SELECT
            COUNT(DISTINCT ic.document_id) AS total,
            COUNT(DISTINCT CASE
                WHEN NOT REGEXP_MATCHES(je.header_text, '[가-힣]')
                THEN ic.document_id END) AS english_header,
            SUM(CASE
                WHEN je.line_text IS NULL
                  OR CAST(je.line_text AS VARCHAR) = ''
                  OR CAST(je.line_text AS VARCHAR) = 'nan'
                THEN 1 ELSE 0 END) AS null_linetext
        FROM ic_docs ic
        JOIN je ON ic.document_id = je.document_id
    """).fetchone()
    total = row[0] or 0
    eng = row[1] or 0
    null_lt = row[2] or 0
    eng_pct = eng / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R5-07", tier=5,
        name="IC 전표 영어header + NaN적요",
        status="WARNING" if eng_pct > 50 else "PASS",
        expected="IC header 한글화",
        actual=f"영어header {eng:,}/{total:,} ({eng_pct:.0f}%), NaN적요 {null_lt:,}행",
        elapsed_ms=_elapsed(start),
    )


def r5_08_lettrage_fill(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-08: lettrage — K-IFRS 비해당 (French GAAP 전용). SKIP."""
    start = _timer()
    return CheckResult(
        check_id="R5-08", tier=5,
        name="lettrage(대사) 채움률",
        status="SKIP",
        expected="K-IFRS 비해당",
        actual="French GAAP 전용 필드",
        elapsed_ms=_elapsed(start),
    )


def r5_09_self_offset(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-09: 같은 GL에 차변/대변 (자기상쇄) 정상 전표."""
    start = _timer()
    # Why: 같은 계정에 동일 금액 Dr/Cr이면 순효과 0원 → 의미 없는 전표
    row = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM (
            SELECT document_id, CAST(gl_account AS VARCHAR) AS gl,
                   SUM(CAST(debit_amount AS DOUBLE)) AS d,
                   SUM(CAST(credit_amount AS DOUBLE)) AS c
            FROM je
            WHERE gl_account IS NOT NULL
              AND is_fraud != 'true' AND is_anomaly != 'true'
            GROUP BY document_id, CAST(gl_account AS VARCHAR)
            HAVING d > 0 AND c > 0 AND ABS(d - c) < 1
        )
    """).fetchone()
    cnt = row[0] or 0
    total = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
    """).fetchone()[0]
    pct = cnt / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R5-09", tier=5,
        name="정상전표 GL 자기상쇄",
        status="PASS" if pct <= 0.5 else ("WARNING" if pct <= 2 else "FAIL"),
        expected="<=0.5%: PASS, <=2%: WARNING",
        actual=f"{cnt:,}/{total:,} ({pct:.2f}%)",
        elapsed_ms=_elapsed(start),
    )


def r5_10_doctype_null_normal(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R5-10: 정상 전표의 document_type null."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE (document_type IS NULL
               OR CAST(document_type AS VARCHAR) IN ('','null','nan'))
          AND is_fraud != 'true' AND is_anomaly != 'true'
    """).fetchone()[0]
    return CheckResult(
        check_id="R5-10", tier=5,
        name="정상전표 document_type null",
        status="PASS" if cnt == 0 else "FAIL",
        expected="0건",
        actual=f"{cnt:,}건",
        elapsed_ms=_elapsed(start),
    )


def run_tier5(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 5 전체 실행."""
    return [
        r5_01_local_amount(con),
        r5_02_reference_year(con),
        r5_03_approval_gap(con),
        r5_04_tax_free_ratio(con),
        r5_05_gl_digit_mix(con),
        r5_06_tax_code_fill(con),
        r5_07_ic_header_language(con),
        r5_08_lettrage_fill(con),
        r5_09_self_offset(con),
        r5_10_doctype_null_normal(con),
    ]
