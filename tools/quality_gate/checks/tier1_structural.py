"""Tier 1: 구조적 무결성 (P0 Blocking, 14개 체크)."""
from __future__ import annotations

import time

import duckdb

from ..models import CheckResult


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _get_excluded_doc_ids(labels_con: duckdb.DuckDBPyConnection | None, anomaly_types: list[str]) -> set[str]:
    """라벨에서 제외할 document_id 집합 반환. labels_con이 None이면 빈 집합."""
    if labels_con is None or not anomaly_types:
        return set()
    types_str = ", ".join(f"'{t}'" for t in anomaly_types)
    rows = labels_con.execute(
        f"SELECT DISTINCT document_id FROM labels WHERE anomaly_type IN ({types_str})"
    ).fetchall()
    return {r[0] for r in rows}


def _register_exclusion(con: duckdb.DuckDBPyConnection, table_name: str, doc_ids: set[str]) -> None:
    """제외 doc_id를 con의 임시 테이블로 등록. 이미 존재하면 교체."""
    con.execute(f"DROP TABLE IF EXISTS {table_name}")
    if not doc_ids:
        con.execute(f"CREATE TEMP TABLE {table_name} (document_id VARCHAR)")
        return
    con.execute(f"CREATE TEMP TABLE {table_name} (document_id VARCHAR)")
    con.executemany(
        f"INSERT INTO {table_name} VALUES (?)",
        [(d,) for d in doc_ids],
    )


def _excluded_subquery(
    con: duckdb.DuckDBPyConnection,
    labels_con: duckdb.DuckDBPyConnection | None,
    anomaly_types: list[str],
    table_name: str = "_excl",
) -> str:
    """labels_con에서 제외 doc_id를 가져와 con 임시 테이블에 등록 후 서브쿼리 반환."""
    doc_ids = _get_excluded_doc_ids(labels_con, anomaly_types)
    _register_exclusion(con, table_name, doc_ids)
    return f"SELECT document_id FROM {table_name}"


# ---------------------------------------------------------------------------
# T1-01 ~ T1-14
# ---------------------------------------------------------------------------

def t1_01(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """행수/컬럼수 정합."""
    start = time.perf_counter()
    row_count = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    col_count = len(con.execute("PRAGMA table_info('je')").fetchall())
    elapsed = (time.perf_counter() - start) * 1000

    expected = "rows=1,104,914; cols=39"
    actual = f"rows={row_count:,}; cols={col_count}"
    status = "PASS" if row_count > 0 and col_count == 39 else "FAIL"

    return CheckResult(
        check_id="T1-01", tier=1, name="행수/컬럼수",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_02(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """필수 10컬럼 존재 + dtype 확인."""
    start = time.perf_counter()
    cols_info = con.execute("PRAGMA table_info('je')").fetchall()
    col_map = {row[1]: row[2] for row in cols_info}  # name -> type
    elapsed = (time.perf_counter() - start) * 1000

    # 허용 타입: 각 컬럼에 대해 호환 가능한 DuckDB 타입 목록
    required: dict[str, list[str]] = {
        "document_id": ["VARCHAR"],
        "company_code": ["VARCHAR"],
        "fiscal_year": ["INTEGER", "BIGINT", "SMALLINT", "INT"],
        "fiscal_period": ["INTEGER", "BIGINT", "SMALLINT", "INT"],
        "posting_date": ["DATE", "TIMESTAMP"],
        "document_date": ["DATE", "TIMESTAMP"],
        "gl_account": ["VARCHAR"],
        "debit_amount": ["DOUBLE", "FLOAT", "BIGINT", "INTEGER", "DECIMAL"],
        "credit_amount": ["DOUBLE", "FLOAT", "BIGINT", "INTEGER", "DECIMAL"],
        "document_type": ["VARCHAR"],
    }

    missing = [c for c in required if c not in col_map]
    # dtype 호환성 검사: DuckDB 실제 타입이 허용 목록에 포함되는지
    wrong_type = []
    for col, allowed_types in required.items():
        if col in col_map:
            actual_type = col_map[col].upper()
            if not any(t in actual_type for t in allowed_types):
                wrong_type.append(f"{col}({col_map[col]})")

    issues = missing + wrong_type
    status = "PASS" if not issues else "FAIL"
    expected = "필수 10컬럼 존재 + 올바른 dtype"
    actual = "OK" if not issues else f"issues={issues}"

    return CheckResult(
        check_id="T1-02", tier=1, name="필수컬럼 존재+dtype",
        status=status, expected=expected, actual=actual,
        detail={"missing": missing, "wrong_type": wrong_type} if issues else None,
        elapsed_ms=elapsed,
    )


def t1_03(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """보호필드 NOT NULL (document_id, company_code, posting_date)."""
    start = time.perf_counter()
    null_counts = con.execute("""
        SELECT
            SUM(CASE WHEN document_id IS NULL THEN 1 ELSE 0 END) AS null_doc,
            SUM(CASE WHEN company_code IS NULL THEN 1 ELSE 0 END) AS null_cc,
            SUM(CASE WHEN posting_date IS NULL THEN 1 ELSE 0 END) AS null_pd
        FROM je
    """).fetchone()
    elapsed = (time.perf_counter() - start) * 1000

    null_doc, null_cc, null_pd = null_counts
    total_nulls = null_doc + null_cc + null_pd
    status = "PASS" if total_nulls == 0 else "FAIL"
    expected = "document_id/company_code/posting_date NULL=0"
    actual = f"null_doc={null_doc}, null_cc={null_cc}, null_pd={null_pd}"

    return CheckResult(
        check_id="T1-03", tier=1, name="보호필드 NOT NULL",
        status=status, expected=expected, actual=actual,
        detail={"null_document_id": null_doc, "null_company_code": null_cc, "null_posting_date": null_pd} if total_nulls > 0 else None,
        elapsed_ms=elapsed,
    )


def t1_04(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """금액 음수 (ReversedAmount 라벨 제외)."""
    start = time.perf_counter()
    excl = _excluded_subquery(con, labels_con, ["ReversedAmount", "UnusuallyLowAmount", "RoundDollarManipulation"])
    neg_count = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE document_id NOT IN ({excl})
          AND (debit_amount < 0 OR credit_amount < 0)
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if neg_count == 0 else "FAIL"
    expected = "음수 금액=0 (ReversedAmount 등 제외)"
    actual = f"neg_count={neg_count:,}"

    return CheckResult(
        check_id="T1-04", tier=1, name="금액 음수",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_05(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """전표 대차일치 (UnbalancedEntry 라벨 제외)."""
    start = time.perf_counter()
    excl = _excluded_subquery(con, labels_con, [
        "UnbalancedEntry", "RoundingError", "CurrencyError", "DecimalError",
        "TransposedDigits", "ReversedAmount", "JustBelowThreshold",
    ])
    unbal_count = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT document_id
            FROM je
            WHERE document_id NOT IN ({excl})
            GROUP BY document_id
            HAVING ABS(SUM(debit_amount) - SUM(credit_amount)) > 1.0
        )
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if unbal_count == 0 else "FAIL"
    expected = "대차불일치 전표=0 (금액변형 anomaly 제외)"
    actual = f"unbalanced_docs={unbal_count:,}"

    return CheckResult(
        check_id="T1-05", tier=1, name="전표 대차일치",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_06(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """company_code 도메인 검증."""
    start = time.perf_counter()
    bad_count = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE company_code NOT IN ('C001', 'C002', 'C003')
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if bad_count == 0 else "FAIL"
    expected = "company_code IN (C001,C002,C003)"
    actual = f"out_of_domain={bad_count:,}"

    return CheckResult(
        check_id="T1-06", tier=1, name="company_code 도메인",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_07(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """기간 범위 (fiscal_year=2022, period 1~12, posting_date 2022년 범위)."""
    start = time.perf_counter()

    # fiscal_year != 2022
    bad_fy = con.execute("""
        SELECT COUNT(*) FROM je WHERE fiscal_year != 2022
    """).fetchone()[0]

    # fiscal_period 범위
    bad_fp = con.execute("""
        SELECT COUNT(*) FROM je WHERE fiscal_period < 1 OR fiscal_period > 12
    """).fetchone()[0]

    # posting_date 범위: 2022 밖은 WARNING (전후월 허용)
    out_of_range = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE posting_date < '2022-01-01' OR posting_date > '2022-12-31'
    """).fetchone()[0]

    elapsed = (time.perf_counter() - start) * 1000

    # fiscal_year/period 위반은 FAIL, posting_date 범위 초과만이면 WARNING
    if bad_fy > 0 or bad_fp > 0:
        status = "FAIL"
    elif out_of_range > 0:
        status = "WARNING"
    else:
        status = "PASS"

    expected = "fiscal_year=2022, period=1~12, posting_date≈2022"
    actual = f"bad_fy={bad_fy:,}, bad_fp={bad_fp:,}, date_out_of_range={out_of_range:,}"

    return CheckResult(
        check_id="T1-07", tier=1, name="기간 범위",
        status=status, expected=expected, actual=actual,
        detail={"bad_fiscal_year": bad_fy, "bad_fiscal_period": bad_fp, "date_out_of_range": out_of_range},
        elapsed_ms=elapsed,
    )


def t1_08(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """라벨 orphan: labels에 있지만 je에 없는 document_id."""
    start = time.perf_counter()

    if labels_con is None:
        elapsed = (time.perf_counter() - start) * 1000
        return CheckResult(
            check_id="T1-08", tier=1, name="라벨 orphan",
            status="SKIP", expected="orphan=0", actual="labels_con=None",
            elapsed_ms=elapsed,
        )

    # je의 document_id 목록을 임시 테이블로 labels_con에 등록
    je_docs = con.execute("SELECT DISTINCT document_id FROM je").fetchall()
    je_doc_set = {row[0] for row in je_docs}

    label_docs = labels_con.execute("SELECT DISTINCT document_id FROM labels").fetchall()
    orphan_count = sum(1 for row in label_docs if row[0] not in je_doc_set)

    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if orphan_count == 0 else "FAIL"
    expected = "orphan labels=0"
    actual = f"orphan_count={orphan_count:,}"

    return CheckResult(
        check_id="T1-08", tier=1, name="라벨 orphan",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_09(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """단일행 전표 (UnbalancedEntry, MissingField 제외)."""
    start = time.perf_counter()
    excl = _excluded_subquery(con, labels_con, ["UnbalancedEntry", "MissingField"])
    single_count = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT document_id
            FROM je
            WHERE document_id NOT IN ({excl})
            GROUP BY document_id
            HAVING COUNT(*) < 2
        )
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if single_count == 0 else "FAIL"
    expected = "단일행 전표=0 (UnbalancedEntry+MissingField 제외)"
    actual = f"single_line_docs={single_count:,}"

    return CheckResult(
        check_id="T1-09", tier=1, name="단일행 전표",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_10(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """KRW 소수점 (정수 금액 기대)."""
    start = time.perf_counter()
    frac_count = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE debit_amount % 1 != 0 OR credit_amount % 1 != 0
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if frac_count == 0 else "FAIL"
    expected = "소수점 금액=0 (KRW)"
    actual = f"fractional_count={frac_count:,}"

    return CheckResult(
        check_id="T1-10", tier=1, name="KRW 소수점",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_11(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """문서 내 일관성 (같은 doc 내 company_code, posting_date 불일치)."""
    start = time.perf_counter()
    inconsistent = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id
            FROM je
            GROUP BY document_id
            HAVING COUNT(DISTINCT company_code) > 1
                OR COUNT(DISTINCT posting_date) > 1
        )
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if inconsistent == 0 else "FAIL"
    expected = "문서 내 company_code/posting_date 불일치=0"
    actual = f"inconsistent_docs={inconsistent:,}"

    return CheckResult(
        check_id="T1-11", tier=1, name="문서 내 일관성",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_12(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """gl_account 형식 (InvalidAccount+DormantAccountActivity 제외)."""
    start = time.perf_counter()
    excl = _excluded_subquery(con, labels_con, ["InvalidAccount", "DormantAccountActivity"])
    # 4~6자리 숫자, 선택적으로 'C'+숫자 접미사
    bad_count = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE document_id NOT IN ({excl})
          AND gl_account IS NOT NULL
          AND NOT regexp_matches(gl_account, '^[0-9]{{4,6}}(C[0-9])?$')
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    status = "PASS" if bad_count == 0 else "FAIL"
    expected = "gl_account 형식 불일치=0 (InvalidAccount+DormantAccountActivity 제외)"
    actual = f"bad_format={bad_count:,}"

    return CheckResult(
        check_id="T1-12", tier=1, name="gl_account 형식",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_13(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """document_type NOT NULL — MCAR 2% 전역 적용 기준 비율 체크."""
    start = time.perf_counter()
    total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    null_count = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE document_type IS NULL OR TRIM(document_type) = ''
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    null_rate = (null_count / total * 100) if total > 0 else 0
    # MCAR 2% 전역 적용 → 0.5~4% 범위면 정상, 4~8% WARNING, 그 외 FAIL
    if 0.5 <= null_rate <= 4.0:
        status = "PASS"
    elif 4.0 < null_rate <= 8.0:
        status = "WARNING"
    else:
        status = "FAIL"
    expected = "MCAR 빈값 비율 0.5~4% (전역 2% 적용)"
    actual = f"null_or_empty={null_count:,} ({null_rate:.2f}%)"

    return CheckResult(
        check_id="T1-13", tier=1, name="document_type MCAR 비율",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


def t1_14(con: duckdb.DuckDBPyConnection, labels_con: duckdb.DuckDBPyConnection | None) -> CheckResult:
    """gl_account NOT NULL — MCAR 2% 전역 적용 기준 비율 체크."""
    start = time.perf_counter()
    total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    null_count = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE gl_account IS NULL OR TRIM(gl_account) = ''
    """).fetchone()[0]
    elapsed = (time.perf_counter() - start) * 1000

    null_rate = (null_count / total * 100) if total > 0 else 0
    # MCAR 2% 전역 적용 → 0.5~4% 범위면 정상, 4~8% WARNING, 그 외 FAIL
    if 0.5 <= null_rate <= 4.0:
        status = "PASS"
    elif 4.0 < null_rate <= 8.0:
        status = "WARNING"
    else:
        status = "FAIL"
    expected = "MCAR 빈값 비율 0.5~4% (전역 2% 적용)"
    actual = f"null_or_empty={null_count:,} ({null_rate:.2f}%)"

    return CheckResult(
        check_id="T1-14", tier=1, name="gl_account MCAR 비율",
        status=status, expected=expected, actual=actual,
        elapsed_ms=elapsed,
    )


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

def run_tier1(
    con: duckdb.DuckDBPyConnection,
    labels_con: duckdb.DuckDBPyConnection | None = None,
) -> list[CheckResult]:
    """Tier 1 전체 체크 실행. labels_con은 라벨 제외용."""
    results: list[CheckResult] = []
    for fn in [
        t1_01, t1_02, t1_03, t1_04, t1_05, t1_06, t1_07,
        t1_08, t1_09, t1_10, t1_11, t1_12, t1_13, t1_14,
    ]:
        results.append(fn(con, labels_con))
    return results
