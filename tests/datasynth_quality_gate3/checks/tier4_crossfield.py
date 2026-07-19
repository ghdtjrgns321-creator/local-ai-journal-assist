"""Tier 4: 교차 필드 정합성 — 프로세스↔GL, persona↔source 등."""
from __future__ import annotations

import time

import duckdb

from ..models import CheckResult

_REGRESSION_DOCUMENT_ID = "9ddc8ff9-097f-4251-981e-abad8b70519f"


def _columns(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute("DESCRIBE je").fetchall()
    return {str(row[0]) for row in rows}


def _normal_row_clause(con: duckdb.DuckDBPyConnection) -> str:
    cols = _columns(con)
    clauses = []
    if "description_quality" in cols:
        clauses.append(
            "(description_quality IS NULL "
            "OR LOWER(CAST(description_quality AS VARCHAR)) = 'normal')"
        )
    if "is_mutated" in cols:
        clauses.append(
            "(is_mutated IS NULL OR LOWER(CAST(is_mutated AS VARCHAR)) NOT IN ('true', '1', 'yes'))"
        )
    if "is_anomaly" in cols:
        clauses.append(
            "(is_anomaly IS NULL OR LOWER(CAST(is_anomaly AS VARCHAR)) NOT IN ('true', '1', 'yes'))"
        )
    if "mutation_type" in cols:
        clauses.append(
            "(mutation_type IS NULL OR TRIM(CAST(mutation_type AS VARCHAR)) IN ('', 'nan', 'None'))"
        )
    return " AND ".join(clauses) if clauses else "TRUE"


_TEXT_BLOB = """
    LOWER(
        COALESCE(CAST(line_text AS VARCHAR), '') || ' ' ||
        COALESCE(CAST(header_text AS VARCHAR), '') || ' ' ||
        COALESCE(CAST(supporting_doc_type AS VARCHAR), '')
    )
"""

_LABOR_SIGNAL = f"""
    (
        {_TEXT_BLOB} LIKE '%급여%'
        OR {_TEXT_BLOB} LIKE '%상여%'
        OR {_TEXT_BLOB} LIKE '%미지급급여%'
        OR {_TEXT_BLOB} LIKE '%직접노무비%'
        OR {_TEXT_BLOB} LIKE '%노무비%'
        OR {_TEXT_BLOB} LIKE '%인건비%'
        OR {_TEXT_BLOB} LIKE '%원천세%'
        OR {_TEXT_BLOB} LIKE '%4대보험%'
        OR {_TEXT_BLOB} LIKE '%퇴직급여%'
        OR {_TEXT_BLOB} LIKE '%payroll%'
        OR {_TEXT_BLOB} LIKE '%salary%'
        OR {_TEXT_BLOB} LIKE '%wage%'
        OR {_TEXT_BLOB} LIKE '%direct labor%'
        OR {_TEXT_BLOB} LIKE '%labor cost%'
        OR {_TEXT_BLOB} LIKE '%withholding%'
    )
"""

_OFFICE_SUPPLIER_SIGNAL = f"""
    (
        {_TEXT_BLOB} LIKE '%기업문구%'
        OR {_TEXT_BLOB} LIKE '%오피스%'
        OR {_TEXT_BLOB} LIKE '%문구%'
        OR {_TEXT_BLOB} LIKE '%복사용지%'
        OR {_TEXT_BLOB} LIKE '%토너%'
        OR LOWER(COALESCE(CAST(auxiliary_account_label AS VARCHAR), '')) LIKE '%기업문구%'
        OR LOWER(COALESCE(CAST(auxiliary_account_label AS VARCHAR), '')) LIKE '%오피스%'
        OR LOWER(COALESCE(CAST(auxiliary_account_label AS VARCHAR), '')) LIKE '%문구%'
        OR LOWER(COALESCE(CAST(auxiliary_account_label AS VARCHAR), '')) LIKE '%office%'
        OR LOWER(COALESCE(CAST(auxiliary_account_label AS VARCHAR), '')) LIKE '%stationery%'
    )
"""

_DEPRECIATION_SIGNAL = f"""
    (
        {_TEXT_BLOB} LIKE '%감가%'
        OR {_TEXT_BLOB} LIKE '%상각%'
        OR {_TEXT_BLOB} LIKE '%depreciation%'
        OR {_TEXT_BLOB} LIKE '%amortization%'
    )
"""

_REVENUE_SIGNAL = f"""
    (
        CAST(gl_account AS VARCHAR)[1] = '4'
        OR {_TEXT_BLOB} LIKE '%매출%'
        OR {_TEXT_BLOB} LIKE '%고객 청구%'
        OR {_TEXT_BLOB} LIKE '%청구%'
        OR {_TEXT_BLOB} LIKE '%revenue%'
        OR {_TEXT_BLOB} LIKE '%sales invoice%'
        OR {_TEXT_BLOB} LIKE '%customer invoice%'
        OR {_TEXT_BLOB} LIKE '%billing%'
    )
"""

_AP_GRIR_ACCOUNT_SIGNAL = """
    (
        REGEXP_MATCHES(CAST(gl_account AS VARCHAR), '^(2000|2050|20500[1-3]|29|2900)')
        OR LOWER(COALESCE(CAST(line_text AS VARCHAR), '')) LIKE '%매입채무%'
        OR LOWER(COALESCE(CAST(line_text AS VARCHAR), '')) LIKE '%gr/ir%'
    )
"""

_PURCHASE_INVOICE_SIGNAL = """
    (
        document_type IN ('KR', 'RE', 'PURCHASE_INVOICE', 'TAX_INVOICE')
        OR supporting_doc_type IN ('세금계산서', '발주서')
        OR LOWER(COALESCE(CAST(reference AS VARCHAR), '')) LIKE 'po-%'
    )
"""

_VENDOR_COUNTERPARTY_SIGNAL = """
    (
        LOWER(COALESCE(CAST(auxiliary_account_number AS VARCHAR), '')) LIKE 'v-%'
        OR LOWER(COALESCE(CAST(trading_partner AS VARCHAR), '')) LIKE 'v-%'
        OR LOWER(COALESCE(CAST(header_text AS VARCHAR), '')) LIKE '%매입%'
        OR LOWER(COALESCE(CAST(reference AS VARCHAR), '')) LIKE 'po-%'
    )
"""


def _semantic_count_result(
    con: duckdb.DuckDBPyConnection,
    check_id: str,
    name: str,
    sql: str,
    sample_sql: str | None = None,
) -> CheckResult:
    start = _timer()
    count = con.execute(sql).fetchone()[0] or 0
    detail = {"semantic_contradiction_count": count}
    if sample_sql and count:
        detail["sample_document_ids"] = [
            row[0] for row in con.execute(sample_sql).fetchall()
        ]
    return CheckResult(
        check_id=check_id,
        tier=4,
        name=name,
        status="PASS" if count == 0 else "FAIL",
        expected="0 normal semantic contradictions",
        actual=f"{count:,} documents",
        detail=detail,
        elapsed_ms=_elapsed(start),
    )


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def r4_01_o2c_revenue(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-01: O2C 대변 중 수익(4xxx) GL 비율 (>=40%)."""
    start = _timer()
    total, revenue = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN CAST(gl_account AS VARCHAR)[1] = '4' THEN 1 ELSE 0 END)
        FROM je
        WHERE business_process = 'O2C'
          AND CAST(credit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
    """).fetchone()
    pct = revenue / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-01", tier=4,
        name="O2C 대변 수익 GL 비율",
        status="PASS" if pct >= 40 else "FAIL",
        expected=">=40%",
        actual=f"{revenue:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_02_h2r_expense(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-02: H2R 차변 중 비용(5-6xxx) GL 비율 (>=80%)."""
    start = _timer()
    total, expense = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6')
                     THEN 1 ELSE 0 END)
        FROM je
        WHERE business_process = 'H2R'
          AND CAST(debit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
    """).fetchone()
    pct = expense / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-02", tier=4,
        name="H2R 차변 비용 GL 비율",
        status="PASS" if pct >= 80 else "WARNING",
        expected=">=80%",
        actual=f"{expense:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_03_p2p_wrong_debit(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-03: P2P 차변에 수익/자본 GL 비율 (<=3%)."""
    start = _timer()
    total, wrong = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN CAST(gl_account AS VARCHAR)[1] IN ('3','4')
                     THEN 1 ELSE 0 END)
        FROM je
        WHERE business_process = 'P2P'
          AND CAST(debit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
    """).fetchone()
    pct = wrong / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-03", tier=4,
        name="P2P 차변에 수익/자본 GL",
        status="PASS" if pct <= 3 else "WARNING",
        expected="<=3%",
        actual=f"{wrong:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_04_auto_manual(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-04: automated_system + source=manual 비율 (<=5%)."""
    start = _timer()
    # Why: 시스템 계정이 수동 입력하는 건 논리적 모순
    total, wrong = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE
                WHEN user_persona = 'automated_system' AND source = 'manual'
                THEN document_id END)
        FROM je
    """).fetchone()
    pct = wrong / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-04", tier=4,
        name="automated_system + manual",
        status="PASS" if pct <= 5 else "WARNING",
        expected="<=5%",
        actual=f"{wrong:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_05_sod_type_complete(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-05: SoD 위반 + conflict_type 누락 = 0건."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE sod_violation = 'true'
          AND (sod_conflict_type IS NULL
               OR CAST(sod_conflict_type AS VARCHAR) = ''
               OR CAST(sod_conflict_type AS VARCHAR) = 'nan')
    """).fetchone()[0]
    return CheckResult(
        check_id="R4-05", tier=4,
        name="SoD 위반 + type 누락",
        status="PASS" if cnt == 0 else "FAIL",
        expected="0건",
        actual=f"{cnt:,}건",
        elapsed_ms=_elapsed(start),
    )


def _r4_06_fraud_type_complete_legacy(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-06: fraud=true + fraud_type 누락 = 0건."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE is_fraud = 'true'
          AND (fraud_type IS NULL
               OR CAST(fraud_type AS VARCHAR) = ''
               OR CAST(fraud_type AS VARCHAR) = 'nan')
    """).fetchone()[0]
    # Why: 라벨 오염 역방향도 체크 — 정상인데 fraud_type 있는 건
    contaminated = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE (is_fraud IS NULL OR is_fraud != 'true')
          AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) != ''
          AND CAST(fraud_type AS VARCHAR) != 'nan'
    """).fetchone()[0]
    total_bad = cnt + contaminated
    return CheckResult(
        check_id="R4-06", tier=4,
        name="fraud 라벨 정합성",
        status="PASS" if total_bad == 0 else "FAIL",
        expected="누락 0건, 오염 0건",
        actual=f"누락 {cnt:,}건, 오염 {contaminated:,}건",
        elapsed_ms=_elapsed(start),
    )


def r4_07_ip_company_isolation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-07: IP 대역-회사 분리 (교차 사용 0건)."""
    start = _timer()
    # Why: 10.1=C001, 10.2=C002, 10.3=C003, 172.16=VPN(공용)
    cross = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT
                company_code,
                SPLIT_PART(ip_address, '.', 1) || '.' ||
                SPLIT_PART(ip_address, '.', 2) AS prefix
            FROM je
            WHERE ip_address IS NOT NULL
              AND SPLIT_PART(ip_address, '.', 1) != '172'
        )
        WHERE (company_code = 'C001' AND prefix != '10.1')
           OR (company_code = 'C002' AND prefix != '10.2')
           OR (company_code = 'C003' AND prefix != '10.3')
    """).fetchone()[0]
    return CheckResult(
        check_id="R4-07", tier=4,
        name="IP-회사 분리",
        status="PASS" if cross == 0 else "FAIL",
        expected="교차 0건",
        actual=f"교차 {cross:,}건",
        elapsed_ms=_elapsed(start),
    )


def r4_08_expense_cost_center(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-08: 비용GL(5-6xxx)에 cost_center 누락 비율 (<=10%)."""
    start = _timer()
    total, missing = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE
                WHEN cost_center IS NULL
                  OR CAST(cost_center AS VARCHAR) = ''
                  OR CAST(cost_center AS VARCHAR) = 'nan'
                THEN 1 ELSE 0 END)
        FROM je
        WHERE gl_account IS NOT NULL
          AND CAST(gl_account AS VARCHAR)[1] IN ('5', '6')
    """).fetchone()
    pct = missing / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-08", tier=4,
        name="비용GL + cost_center 누락",
        status="PASS" if pct <= 10 else "WARNING",
        expected="<=10%",
        actual=f"{missing:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_09_korean_user_id(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-09: 사람 사용자 ID에 한국식 이름 비율 (한글 + 로마자)."""
    start = _timer()
    # Why: 한국 기업인데 NRODRI032 등 서양식 ID만 있으면 비현실적
    #       DataSynth는 로마자 한국이름(MKIM001, JPARK042) 형태로 생성하므로
    #       한글 유니코드뿐 아니라 로마자 한국 성씨 패턴도 탐지해야 함
    # 로마자 한국 성씨 목록 (대소문자 무시, user_id에서 첫 1글자 이니셜 + 성씨 + 숫자 패턴)
    korean_surnames_pattern = "|".join([
        "KIM", "LEE", "PARK", "CHOI", "JUNG", "KANG", "CHO", "YOON",
        "JANG", "LIM", "HAN", "OH", "SEO", "SHIN", "KWON", "HWANG",
        "AHN", "SONG", "RYU", "JEON",
    ])
    row = con.execute(f"""
        SELECT
            COUNT(DISTINCT created_by) AS total,
            COUNT(DISTINCT CASE
                WHEN created_by NOT LIKE 'SYSTEM-%'
                 AND (
                    REGEXP_MATCHES(created_by, '[가-힣]')
                    OR REGEXP_MATCHES(UPPER(created_by),
                       '^[A-Z]({korean_surnames_pattern})[0-9]')
                 )
                THEN created_by END) AS korean
        FROM je
        WHERE created_by NOT LIKE 'SYSTEM-%'
          AND created_by IS NOT NULL
    """).fetchone()
    total, korean = row[0] or 0, row[1] or 0
    pct = korean / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-09", tier=4,
        name="한국식 사용자 ID 비율",
        status="PASS" if pct > 0 else "WARNING",
        expected="한국식 ID 존재 (한글 또는 로마자 한국 성씨)",
        actual=f"한국식 {korean:,}/{total:,}명 ({pct:.0f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_10_regression_document_semantic_contradiction(
    con: duckdb.DuckDBPyConnection,
) -> CheckResult:
    """R4-10: Known datasynth_contract semantic contradiction fixture remains visible."""
    normal = _normal_row_clause(con)
    return _semantic_count_result(
        con,
        "R4-10",
        "Known semantic contradiction fixture",
        f"""
        SELECT COUNT(DISTINCT document_id)
        FROM je
        WHERE {normal}
          AND document_id = '{_REGRESSION_DOCUMENT_ID}'
          AND business_process = 'P2P'
          AND {_LABOR_SIGNAL}
          AND {_OFFICE_SUPPLIER_SIGNAL}
          AND {_PURCHASE_INVOICE_SIGNAL}
        """,
    )


def r4_11_normal_labor_p2p(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-11: Normal labor/payroll/direct-labor text must not appear in P2P."""
    normal = _normal_row_clause(con)
    query = f"""
        SELECT COUNT(DISTINCT document_id)
        FROM je
        WHERE {normal}
          AND business_process = 'P2P'
          AND {_LABOR_SIGNAL}
    """
    samples = f"""
        SELECT DISTINCT document_id
        FROM je
        WHERE {normal}
          AND business_process = 'P2P'
          AND {_LABOR_SIGNAL}
        LIMIT 5
    """
    return _semantic_count_result(
        con,
        "R4-11",
        "Normal labor/payroll/direct labor + P2P",
        query,
        samples,
    )


def r4_12_normal_labor_ap_grir(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-12: Normal labor/payroll/direct-labor entries must not use AP or GR/IR."""
    normal = _normal_row_clause(con)
    query = f"""
        WITH normal_rows AS (
            SELECT *
            FROM je
            WHERE {normal}
        ),
        labor_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_LABOR_SIGNAL}
        ),
        ap_grir_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_AP_GRIR_ACCOUNT_SIGNAL}
        )
        SELECT COUNT(*)
        FROM labor_docs
        JOIN ap_grir_docs USING (document_id)
    """
    samples = f"""
        WITH normal_rows AS (
            SELECT *
            FROM je
            WHERE {normal}
        ),
        labor_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_LABOR_SIGNAL}
        ),
        ap_grir_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_AP_GRIR_ACCOUNT_SIGNAL}
        )
        SELECT labor_docs.document_id
        FROM labor_docs
        JOIN ap_grir_docs USING (document_id)
        LIMIT 5
    """
    return _semantic_count_result(
        con,
        "R4-12",
        "Normal labor/payroll/direct labor + AP/GRIR",
        query,
        samples,
    )


def r4_13_normal_labor_office_supplier(
    con: duckdb.DuckDBPyConnection,
) -> CheckResult:
    """R4-13: Normal labor/payroll/direct-labor entries must not use office suppliers."""
    normal = _normal_row_clause(con)
    query = f"""
        SELECT COUNT(DISTINCT document_id)
        FROM je
        WHERE {normal}
          AND {_LABOR_SIGNAL}
          AND {_OFFICE_SUPPLIER_SIGNAL}
    """
    samples = f"""
        SELECT DISTINCT document_id
        FROM je
        WHERE {normal}
          AND {_LABOR_SIGNAL}
          AND {_OFFICE_SUPPLIER_SIGNAL}
        LIMIT 5
    """
    return _semantic_count_result(
        con,
        "R4-13",
        "Normal labor/payroll/direct labor + office supplier",
        query,
        samples,
    )


def r4_14_purchase_invoice_payroll_text(
    con: duckdb.DuckDBPyConnection,
) -> CheckResult:
    """R4-14: Purchase or tax invoice documents must not carry payroll text."""
    normal = _normal_row_clause(con)
    query = f"""
        SELECT COUNT(DISTINCT document_id)
        FROM je
        WHERE {normal}
          AND {_PURCHASE_INVOICE_SIGNAL}
          AND {_LABOR_SIGNAL}
    """
    samples = f"""
        SELECT DISTINCT document_id
        FROM je
        WHERE {normal}
          AND {_PURCHASE_INVOICE_SIGNAL}
          AND {_LABOR_SIGNAL}
        LIMIT 5
    """
    return _semantic_count_result(
        con,
        "R4-14",
        "Purchase/tax invoice + payroll text",
        query,
        samples,
    )


def r4_15_depreciation_ap_vendor(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-15: Depreciation entries must not use AP vendor invoice semantics."""
    normal = _normal_row_clause(con)
    query = f"""
        WITH normal_rows AS (
            SELECT *
            FROM je
            WHERE {normal}
        ),
        dep_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_DEPRECIATION_SIGNAL}
        ),
        ap_vendor_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_AP_GRIR_ACCOUNT_SIGNAL}
               OR {_PURCHASE_INVOICE_SIGNAL}
               OR {_VENDOR_COUNTERPARTY_SIGNAL}
        )
        SELECT COUNT(*)
        FROM dep_docs
        JOIN ap_vendor_docs USING (document_id)
    """
    samples = f"""
        WITH normal_rows AS (
            SELECT *
            FROM je
            WHERE {normal}
        ),
        dep_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_DEPRECIATION_SIGNAL}
        ),
        ap_vendor_docs AS (
            SELECT DISTINCT document_id
            FROM normal_rows
            WHERE {_AP_GRIR_ACCOUNT_SIGNAL}
               OR {_PURCHASE_INVOICE_SIGNAL}
               OR {_VENDOR_COUNTERPARTY_SIGNAL}
        )
        SELECT dep_docs.document_id
        FROM dep_docs
        JOIN ap_vendor_docs USING (document_id)
        LIMIT 5
    """
    return _semantic_count_result(
        con,
        "R4-15",
        "Normal depreciation + AP vendor semantics",
        query,
        samples,
    )


def r4_16_revenue_non_customer_counterparty(
    con: duckdb.DuckDBPyConnection,
) -> CheckResult:
    """R4-16: Revenue/customer-billing entries must use customer-like counterparties."""
    normal = _normal_row_clause(con)
    query = f"""
        SELECT COUNT(DISTINCT document_id)
        FROM je
        WHERE {normal}
          AND {_REVENUE_SIGNAL}
          AND COALESCE(business_process, '') NOT IN ('O2C', 'Intercompany')
    """
    samples = f"""
        SELECT DISTINCT document_id
        FROM je
        WHERE {normal}
          AND {_REVENUE_SIGNAL}
          AND COALESCE(business_process, '') NOT IN ('O2C', 'Intercompany')
        LIMIT 5
    """
    return _semantic_count_result(
        con,
        "R4-16",
        "Normal revenue + non-customer counterparty/process",
        query,
        samples,
    )


def r4_06_fraud_type_complete(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-06: fraud=true rows must have fraud_type when fraud columns exist."""
    start = _timer()
    cols = _columns(con)
    if "is_fraud" not in cols or "fraud_type" not in cols:
        return CheckResult(
            check_id="R4-06", tier=4,
            name="fraud label completeness",
            status="SKIP",
            expected="is_fraud/fraud_type columns",
            actual="fraud columns not present",
            elapsed_ms=_elapsed(start),
        )
    cnt = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE is_fraud = 'true'
          AND (fraud_type IS NULL
               OR CAST(fraud_type AS VARCHAR) = ''
               OR CAST(fraud_type AS VARCHAR) = 'nan')
    """).fetchone()[0]
    contaminated = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE (is_fraud IS NULL OR is_fraud != 'true')
          AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) != ''
          AND CAST(fraud_type AS VARCHAR) != 'nan'
    """).fetchone()[0]
    total_bad = cnt + contaminated
    return CheckResult(
        check_id="R4-06", tier=4,
        name="fraud label completeness",
        status="PASS" if total_bad == 0 else "FAIL",
        expected="missing 0, contamination 0",
        actual=f"missing {cnt:,}, contamination {contaminated:,}",
        elapsed_ms=_elapsed(start),
    )


def run_tier4(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 4 전체 실행."""
    return [
        r4_01_o2c_revenue(con),
        r4_02_h2r_expense(con),
        r4_03_p2p_wrong_debit(con),
        r4_04_auto_manual(con),
        r4_05_sod_type_complete(con),
        r4_06_fraud_type_complete(con),
        r4_07_ip_company_isolation(con),
        r4_08_expense_cost_center(con),
        r4_09_korean_user_id(con),
        r4_10_regression_document_semantic_contradiction(con),
        r4_11_normal_labor_p2p(con),
        r4_12_normal_labor_ap_grir(con),
        r4_13_normal_labor_office_supplier(con),
        r4_14_purchase_invoice_payroll_text(con),
        r4_15_depreciation_ap_vendor(con),
        r4_16_revenue_non_customer_counterparty(con),
    ]
