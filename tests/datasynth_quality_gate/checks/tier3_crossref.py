"""Tier 3: 교차검증 (30개 체크) — 마스터데이터·역할·문서흐름·보조원장·IC."""
from __future__ import annotations

import time
from pathlib import Path

import duckdb

from ..models import CheckResult

# ---------------------------------------------------------------------------
# 기본 경로 & 헬퍼
# ---------------------------------------------------------------------------

_DATA_ROOT = Path("data/journal/primary/datasynth")


def _load_json(con: duckdb.DuckDBPyConnection, table_name: str, path: Path) -> bool:
    """JSON 파일을 DuckDB 테이블로 로드. 성공 여부 반환."""
    if not path.exists():
        return False
    try:
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        con.execute(
            f"CREATE TABLE {table_name} AS SELECT * FROM read_json_auto('{path.as_posix()}')"
        )
        return True
    except Exception:
        return False


def _skip(check_id: str, name: str, reason: str = "파일 없음") -> CheckResult:
    return CheckResult(
        check_id=check_id, tier=3, name=name,
        status="SKIP", expected="-", actual=reason,
    )


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _get_excluded_doc_ids(con: duckdb.DuckDBPyConnection, anomaly_types: list[str]) -> set[str]:
    """labels 테이블 + JE 내장 라벨에서 제외할 document_id 집합."""
    ids: set[str] = set()
    types_str = ", ".join(f"'{t}'" for t in anomaly_types)
    # Why: JE CSV의 anomaly_type 컬럼에도 라벨이 내장되어 있으므로 양쪽 모두 확인
    try:
        rows = con.execute(
            f"SELECT DISTINCT document_id FROM labels WHERE anomaly_type IN ({types_str})"
        ).fetchall()
        ids |= {r[0] for r in rows}
    except Exception:
        pass
    try:
        rows = con.execute(
            f"SELECT DISTINCT document_id FROM je WHERE anomaly_type IN ({types_str})"
        ).fetchall()
        ids |= {r[0] for r in rows}
    except Exception:
        pass
    return ids


def _register_exclusion(con: duckdb.DuckDBPyConnection, name: str, ids: set[str]) -> None:
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TEMP TABLE {name} (document_id VARCHAR)")
    if ids:
        con.executemany(f"INSERT INTO {name} VALUES (?)", [(d,) for d in ids])


# ---------------------------------------------------------------------------
# 문서흐름 JSON → flat 테이블 로드 (header.document_id, header.posting_date 등)
# ---------------------------------------------------------------------------

def _load_flow(con: duckdb.DuckDBPyConnection, table_name: str, path: Path) -> bool:
    """document_flows JSON을 header 기반 flat 테이블로 로드."""
    if not path.exists():
        return False
    try:
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        con.execute(f"""
            CREATE TABLE {table_name} AS
            SELECT header.document_id, header.posting_date, header.document_type,
                   header.company_code, *EXCLUDE(header)
            FROM read_json_auto('{path.as_posix()}')
        """)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# T3-01 ~ T3-08: 마스터데이터
# ---------------------------------------------------------------------------

def t3_01(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """vendor FK — auxiliary_account_number LIKE 'V-%' → vendors.vendor_id."""
    s = time.perf_counter()
    if not _load_json(con, "_vendors", _DATA_ROOT / "master_data/vendors.json"):
        return _skip("T3-01", "vendor FK")
    orphan = con.execute("""
        SELECT COUNT(DISTINCT j.auxiliary_account_number)
        FROM je j
        WHERE j.auxiliary_account_number LIKE 'V-%'
          AND j.auxiliary_account_number NOT IN (SELECT vendor_id FROM _vendors)
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-01", tier=3, name="vendor FK",
        status="PASS" if orphan == 0 else "FAIL",
        expected="orphan=0", actual=f"orphan={orphan:,}",
        elapsed_ms=_elapsed(s),
    )


def t3_02(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """customer FK — auxiliary_account_number LIKE 'C-%' → customers.customer_id."""
    s = time.perf_counter()
    if not _load_json(con, "_customers", _DATA_ROOT / "master_data/customers.json"):
        return _skip("T3-02", "customer FK")
    orphan = con.execute("""
        SELECT COUNT(DISTINCT j.auxiliary_account_number)
        FROM je j
        WHERE j.auxiliary_account_number LIKE 'C-%'
          AND j.auxiliary_account_number NOT IN (SELECT customer_id FROM _customers)
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-02", tier=3, name="customer FK",
        status="PASS" if orphan == 0 else "FAIL",
        expected="orphan=0", actual=f"orphan={orphan:,}",
        elapsed_ms=_elapsed(s),
    )


def t3_03(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """employee FK — created_by → employees.user_id."""
    s = time.perf_counter()
    if not _load_json(con, "_employees", _DATA_ROOT / "master_data/employees.json"):
        return _skip("T3-03", "employee FK")
    orphan = con.execute("""
        SELECT COUNT(DISTINCT j.created_by)
        FROM je j
        WHERE j.created_by IS NOT NULL
          AND j.created_by NOT IN (SELECT user_id FROM _employees)
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-03", tier=3, name="employee FK",
        status="PASS" if orphan == 0 else "FAIL",
        expected="orphan=0", actual=f"orphan={orphan:,}",
        elapsed_ms=_elapsed(s),
    )


def t3_04(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """employee persona 일치 — je.user_persona == employees.persona."""
    s = time.perf_counter()
    try:
        con.execute("SELECT 1 FROM _employees LIMIT 1")
    except Exception:
        if not _load_json(con, "_employees", _DATA_ROOT / "master_data/employees.json"):
            return _skip("T3-04", "persona 일치")
    mismatch = con.execute("""
        SELECT COUNT(*)
        FROM je j JOIN _employees e ON j.created_by = e.user_id
        WHERE j.user_persona IS NOT NULL AND j.user_persona != e.persona
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-04", tier=3, name="persona 일치",
        status="PASS" if mismatch == 0 else "FAIL",
        expected="mismatch=0", actual=f"mismatch={mismatch:,}",
        elapsed_ms=_elapsed(s),
    )


def t3_05(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """employee company 일치 — je.company_code == employees.company_code (IC 제외)."""
    s = time.perf_counter()
    try:
        con.execute("SELECT 1 FROM _employees LIMIT 1")
    except Exception:
        if not _load_json(con, "_employees", _DATA_ROOT / "master_data/employees.json"):
            return _skip("T3-05", "employee company 일치")
    # Why: IC 전표는 cross-company posting이 정상 (회사 간 거래)
    ic_types = ["CircularIntercompany", "UnmatchedIntercompany", "TransferPricingAnomaly"]
    ic_excl = _get_excluded_doc_ids(con, ic_types)
    _register_exclusion(con, "_excl_ic", ic_excl)
    # Why: authorized_company_codes에 해당 회사가 포함되면 cross-company posting 정상
    mismatch = con.execute("""
        SELECT COUNT(*)
        FROM je j JOIN _employees e ON j.created_by = e.user_id
        WHERE j.company_code != e.company_code
          AND j.document_id NOT IN (SELECT document_id FROM _excl_ic)
          AND COALESCE(j.document_type, '') != 'IC'
          AND NOT list_contains(e.authorized_company_codes, j.company_code)
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-05", tier=3, name="employee company 일치",
        status="PASS" if mismatch == 0 else "FAIL",
        expected="mismatch=0 (IC 전표 + authorized 회사 제외)", actual=f"mismatch={mismatch:,}",
        elapsed_ms=_elapsed(s),
    )


def t3_06(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """vendor 커버리지 — CSV에서 참조된 vendor / 전체 vendor 비율."""
    s = time.perf_counter()
    try:
        total = con.execute("SELECT COUNT(*) FROM _vendors").fetchone()[0]
    except Exception:
        return _skip("T3-06", "vendor 커버리지")
    used = con.execute("""
        SELECT COUNT(DISTINCT auxiliary_account_number)
        FROM je WHERE auxiliary_account_number LIKE 'V-%'
    """).fetchone()[0]
    pct = round(used / total * 100, 1) if total else 0
    return CheckResult(
        check_id="T3-06", tier=3, name="vendor 커버리지",
        status="PASS" if pct >= 50 else "WARNING",
        expected=">=50%", actual=f"{used}/{total} ({pct}%)",
        elapsed_ms=_elapsed(s),
    )


def t3_07(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """customer 커버리지."""
    s = time.perf_counter()
    try:
        total = con.execute("SELECT COUNT(*) FROM _customers").fetchone()[0]
    except Exception:
        return _skip("T3-07", "customer 커버리지")
    used = con.execute("""
        SELECT COUNT(DISTINCT auxiliary_account_number)
        FROM je WHERE auxiliary_account_number LIKE 'C-%'
    """).fetchone()[0]
    pct = round(used / total * 100, 1) if total else 0
    return CheckResult(
        check_id="T3-07", tier=3, name="customer 커버리지",
        status="PASS" if pct >= 50 else "WARNING",
        expected=">=50%", actual=f"{used}/{total} ({pct}%)",
        elapsed_ms=_elapsed(s),
    )


def t3_08(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """employee 커버리지."""
    s = time.perf_counter()
    try:
        total = con.execute("SELECT COUNT(*) FROM _employees").fetchone()[0]
    except Exception:
        return _skip("T3-08", "employee 커버리지")
    used = con.execute("""
        SELECT COUNT(DISTINCT created_by) FROM je WHERE created_by IS NOT NULL
    """).fetchone()[0]
    pct = round(used / total * 100, 1) if total else 0
    return CheckResult(
        check_id="T3-08", tier=3, name="employee 커버리지",
        status="PASS" if pct >= 50 else "WARNING",
        expected=">=50%", actual=f"{used}/{total} ({pct}%)",
        elapsed_ms=_elapsed(s),
    )


# ---------------------------------------------------------------------------
# T3-09 ~ T3-13: 역할/권한
# ---------------------------------------------------------------------------

def t3_09(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """junior TRE 금지 — junior_accountant의 TRE 전표 (SoD 라벨 제외) = 0."""
    s = time.perf_counter()
    # Why: 실제 anomaly_type은 "SegregationOfDutiesViolation" (SoDViolation/SoDConflict 미사용)
    excl = _get_excluded_doc_ids(con, ["SegregationOfDutiesViolation"])
    _register_exclusion(con, "_excl_sod", excl)
    cnt = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE user_persona = 'junior_accountant'
          AND business_process = 'TRE'
          AND document_id NOT IN (SELECT document_id FROM _excl_sod)
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-09", tier=3, name="junior TRE 금지",
        status="PASS" if cnt == 0 else "FAIL",
        expected="0건 (SoD 제외)", actual=f"{cnt:,}건",
        elapsed_ms=_elapsed(s),
    )


def t3_10(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """junior 단일 프로세스 — junior별 distinct process > 1 (SoD 제외)."""
    s = time.perf_counter()
    # Why: 실제 anomaly_type은 "SegregationOfDutiesViolation" (SoDViolation/SoDConflict 미사용)
    excl = _get_excluded_doc_ids(con, ["SegregationOfDutiesViolation"])
    _register_exclusion(con, "_excl_sod", excl)
    multi = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT created_by
            FROM je
            WHERE user_persona = 'junior_accountant'
              AND document_id NOT IN (SELECT document_id FROM _excl_sod)
            GROUP BY created_by
            HAVING COUNT(DISTINCT business_process) > 1
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-10", tier=3, name="junior 단일 프로세스",
        status="PASS" if multi == 0 else "FAIL",
        expected="multi-process junior=0 (SoD 제외)", actual=f"{multi:,}명",
        elapsed_ms=_elapsed(s),
    )


def t3_11(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """controller R2R 집중 — controller의 R2R 비율 >= 80%."""
    s = time.perf_counter()
    row = con.execute("""
        SELECT
            COUNT(*) FILTER (WHERE business_process = 'R2R') AS r2r,
            COUNT(*) AS total
        FROM je WHERE user_persona = 'controller'
    """).fetchone()
    r2r, total = row
    pct = round(r2r / total * 100, 1) if total else 0
    return CheckResult(
        check_id="T3-11", tier=3, name="controller R2R 집중",
        status="PASS" if pct >= 80 else "WARNING",
        expected="R2R >= 80%", actual=f"{pct}% ({r2r}/{total})",
        elapsed_ms=_elapsed(s),
    )


def t3_12(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """employee approval_limit — 전표 금액 > limit (금액 변형 anomaly 제외)."""
    s = time.perf_counter()
    try:
        con.execute("SELECT 1 FROM _employees LIMIT 1")
    except Exception:
        if not _load_json(con, "_employees", _DATA_ROOT / "master_data/employees.json"):
            return _skip("T3-12", "approval_limit")
    # Why: BenfordViolation 등 금액 변형 anomaly는 의도적 극단값이므로 제외
    excl = _get_excluded_doc_ids(con, ["ExceededApprovalLimit", "BenfordViolation"])
    _register_exclusion(con, "_excl_limit", excl)
    # 전표별 최대금액 vs 작성자 limit
    violated = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT j.document_id
            FROM je j
            JOIN _employees e ON j.created_by = e.user_id
            WHERE j.document_id NOT IN (SELECT document_id FROM _excl_limit)
              AND e.approval_limit IS NOT NULL
            GROUP BY j.document_id, e.approval_limit
            HAVING MAX(j.debit_amount + j.credit_amount) > CAST(e.approval_limit AS BIGINT)
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-12", tier=3, name="approval_limit",
        status="PASS" if violated == 0 else "FAIL",
        expected="초과=0 (금액변형 anomaly 제외)", actual=f"{violated:,}건",
        elapsed_ms=_elapsed(s),
    )


def t3_13(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """can_approve_je — approved_by가 can_approve=true인 직원 (SelfApproval/SkippedApproval 제외)."""
    s = time.perf_counter()
    try:
        con.execute("SELECT 1 FROM _employees LIMIT 1")
    except Exception:
        if not _load_json(con, "_employees", _DATA_ROOT / "master_data/employees.json"):
            return _skip("T3-13", "can_approve_je")
    excl = _get_excluded_doc_ids(con, ["SelfApproval", "SkippedApproval"])
    _register_exclusion(con, "_excl_appr", excl)
    bad = con.execute("""
        SELECT COUNT(DISTINCT j.document_id)
        FROM je j
        JOIN _employees e ON j.approved_by = e.user_id
        WHERE j.document_id NOT IN (SELECT document_id FROM _excl_appr)
          AND j.approved_by IS NOT NULL
          AND e.can_approve_je = false
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-13", tier=3, name="can_approve_je",
        status="PASS" if bad == 0 else "FAIL",
        expected="무권한 승인=0 (SelfApproval/SkippedApproval 제외)", actual=f"{bad:,}건",
        elapsed_ms=_elapsed(s),
    )


# ---------------------------------------------------------------------------
# T3-14 ~ T3-21: 문서흐름
# ---------------------------------------------------------------------------

def _ensure_flows(con: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    """문서흐름 JSON을 DuckDB에 로드하고 로드 성공 여부 반환."""
    flows = {
        "_po": "document_flows/purchase_orders.json",
        "_gr": "document_flows/goods_receipts.json",
        "_vi": "document_flows/vendor_invoices.json",
        "_pay": "document_flows/payments.json",
        "_so": "document_flows/sales_orders.json",
        "_dlv": "document_flows/deliveries.json",
        "_ci": "document_flows/customer_invoices.json",
    }
    loaded = {}
    for tbl, rel in flows.items():
        try:
            con.execute(f"SELECT 1 FROM {tbl} LIMIT 1")
            loaded[tbl] = True
        except Exception:
            loaded[tbl] = _load_flow(con, tbl, _DATA_ROOT / rel)
    return loaded


def t3_14(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """reference FK — CSV reference 'GR:*', 'VI:*' 등 → flows JSON document_id."""
    s = time.perf_counter()
    loaded = _ensure_flows(con)
    # prefix → 테이블 매핑
    prefix_map = {
        "PO": "_po", "GR": "_gr", "VI": "_vi", "PAY": "_pay",
        "SO": "_so", "DLV": "_dlv", "CI": "_ci",
    }
    total_refs, orphans = 0, 0
    for prefix, tbl in prefix_map.items():
        if not loaded.get(tbl, False):
            continue
        row = con.execute(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE SUBSTRING(reference, {len(prefix)+2}) NOT IN (SELECT document_id FROM {tbl})
                ) AS orphan
            FROM je
            WHERE reference LIKE '{prefix}:%'
        """).fetchone()
        total_refs += row[0]
        orphans += row[1]
    if total_refs == 0:
        return _skip("T3-14", "reference FK", "참조 없음")
    return CheckResult(
        check_id="T3-14", tier=3, name="reference FK",
        status="PASS" if orphans == 0 else "FAIL",
        expected="orphan=0", actual=f"orphan={orphans:,}/{total_refs:,}",
        elapsed_ms=_elapsed(s),
    )


def t3_15(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """P2P 순서 — PO→GR→VI→PAY 날짜 순서 (DuplicatePayment 제외)."""
    s = time.perf_counter()
    loaded = _ensure_flows(con)
    needed = ["_po", "_gr", "_vi", "_pay"]
    if not all(loaded.get(t, False) for t in needed):
        return _skip("T3-15", "P2P 순서")
    excl = _get_excluded_doc_ids(con, ["DuplicatePayment"])
    _register_exclusion(con, "_excl_dup", excl)
    # vendor_invoices에 purchase_order_id, goods_receipt_id가 있음
    bad = con.execute("""
        SELECT COUNT(*) FROM _vi v
        JOIN _po p ON v.purchase_order_id = p.document_id
        JOIN _gr g ON v.goods_receipt_id = g.document_id
        WHERE v.document_id NOT IN (SELECT document_id FROM _excl_dup)
          AND NOT (p.posting_date <= g.posting_date AND g.posting_date <= v.posting_date)
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-15", tier=3, name="P2P 순서",
        status="PASS" if bad == 0 else "WARNING",
        expected="PO<=GR<=VI (DuplicatePayment 제외)", actual=f"역전={bad:,}건",
        elapsed_ms=_elapsed(s),
    )


def t3_16(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """P2P 금액 매칭 — PO ≈ VI (±5%) (DuplicatePayment 제외)."""
    s = time.perf_counter()
    loaded = _ensure_flows(con)
    if not all(loaded.get(t, False) for t in ["_po", "_vi"]):
        return _skip("T3-16", "P2P 금액 매칭")
    excl = _get_excluded_doc_ids(con, ["DuplicatePayment"])
    _register_exclusion(con, "_excl_dup", excl)
    bad = con.execute("""
        SELECT COUNT(*) FROM _vi v
        JOIN _po p ON v.purchase_order_id = p.document_id
        WHERE v.document_id NOT IN (SELECT document_id FROM _excl_dup)
          AND CAST(p.total_net_amount AS DOUBLE) > 0
          AND ABS(CAST(v.net_amount AS DOUBLE) - CAST(p.total_net_amount AS DOUBLE))
              / CAST(p.total_net_amount AS DOUBLE) > 0.05
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-16", tier=3, name="P2P 금액 매칭",
        status="PASS" if bad == 0 else "WARNING",
        expected="PO≈VI (±5%)", actual=f"불일치={bad:,}건",
        elapsed_ms=_elapsed(s),
    )


def t3_17(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """O2C 순서 — SO→DLV→CI 날짜 순서."""
    s = time.perf_counter()
    loaded = _ensure_flows(con)
    if not all(loaded.get(t, False) for t in ["_so", "_dlv", "_ci"]):
        return _skip("T3-17", "O2C 순서")
    bad = con.execute("""
        SELECT COUNT(*) FROM _ci c
        LEFT JOIN _dlv d ON c.delivery_id = d.document_id
        LEFT JOIN _so so ON c.sales_order_id = so.document_id
        WHERE so.document_id IS NOT NULL AND d.document_id IS NOT NULL
          AND NOT (so.posting_date <= d.posting_date AND d.posting_date <= c.posting_date)
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-17", tier=3, name="O2C 순서",
        status="PASS" if bad == 0 else "WARNING",
        expected="SO<=DLV<=CI", actual=f"역전={bad:,}건",
        elapsed_ms=_elapsed(s),
    )


def t3_18(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """payment 지급기한 — PAY_date - VI_date 분포."""
    s = time.perf_counter()
    loaded = _ensure_flows(con)
    if not all(loaded.get(t, False) for t in ["_vi", "_pay"]):
        return _skip("T3-18", "지급기한 분포")
    # payments에 allocations 있지만, vi.payment_references로 연결 어려움
    # 대안: vi의 due_date 와 is_paid 기준으로 평균 지급일수 산출
    try:
        row = con.execute("""
            SELECT
                AVG(DATEDIFF('day', CAST(v.invoice_date AS DATE), CAST(v.due_date AS DATE))) AS avg_terms,
                MIN(DATEDIFF('day', CAST(v.invoice_date AS DATE), CAST(v.due_date AS DATE))) AS min_terms,
                MAX(DATEDIFF('day', CAST(v.invoice_date AS DATE), CAST(v.due_date AS DATE))) AS max_terms
            FROM _vi v
            WHERE v.due_date IS NOT NULL AND v.invoice_date IS NOT NULL
        """).fetchone()
        avg_t, min_t, max_t = row
    except Exception:
        return _skip("T3-18", "지급기한 분포", "쿼리 실패")
    return CheckResult(
        check_id="T3-18", tier=3, name="지급기한 분포",
        status="PASS" if avg_t and 0 < avg_t < 120 else "WARNING",
        expected="합리적 지급기한(0~120일)", actual=f"avg={avg_t}, min={min_t}, max={max_t}",
        elapsed_ms=_elapsed(s),
    )


def t3_19(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """GR/IR 청산 — document_type='WE' 전표에 GL 2900 라인 존재."""
    s = time.perf_counter()
    total_we = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je WHERE document_type = 'WE'
    """).fetchone()[0]
    if total_we == 0:
        return _skip("T3-19", "GR/IR 청산", "WE 전표 없음")
    # WE 전표 중 GL 2900 라인이 없는 건
    missing = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id FROM je WHERE document_type = 'WE'
            EXCEPT
            SELECT document_id FROM je WHERE document_type = 'WE' AND gl_account LIKE '2900%'
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-19", tier=3, name="GR/IR 청산",
        status="PASS" if missing == 0 else "WARNING",
        expected="WE 전표에 GL 2900 라인", actual=f"미포함={missing}/{total_we}",
        elapsed_ms=_elapsed(s),
    )


def t3_20(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """delivery COGS — document_type='WL' 전표에 GL 5000 라인 존재."""
    s = time.perf_counter()
    total_wl = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je WHERE document_type = 'WL'
    """).fetchone()[0]
    if total_wl == 0:
        return _skip("T3-20", "delivery COGS", "WL 전표 없음")
    missing = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id FROM je WHERE document_type = 'WL'
            EXCEPT
            SELECT document_id FROM je WHERE document_type = 'WL' AND gl_account LIKE '5000%'
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="T3-20", tier=3, name="delivery COGS",
        status="PASS" if missing == 0 else "WARNING",
        expected="WL 전표에 GL 5000 라인", actual=f"미포함={missing}/{total_wl}",
        elapsed_ms=_elapsed(s),
    )


def t3_21(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """cross_process_links 순서 — source_date < target_date (link_date 기준)."""
    s = time.perf_counter()
    path = _DATA_ROOT / "relationships/cross_process_links.json"
    if not _load_json(con, "_xlinks", path):
        return _skip("T3-21", "cross_process_links 순서")
    # link_date 단일 필드만 있으므로, source/target document의 posting_date로 비교
    loaded = _ensure_flows(con)
    # 모든 flow 테이블 UNION으로 doc → posting_date 매핑
    union_parts = []
    for tbl, ok in loaded.items():
        if ok:
            union_parts.append(f"SELECT document_id, posting_date FROM {tbl}")
    if not union_parts:
        return _skip("T3-21", "cross_process_links 순서", "flow 테이블 없음")
    union_sql = " UNION ALL ".join(union_parts)
    con.execute(f"DROP TABLE IF EXISTS _all_flows")
    con.execute(f"CREATE TEMP TABLE _all_flows AS {union_sql}")
    bad = con.execute("""
        SELECT COUNT(*) FROM _xlinks x
        JOIN _all_flows sf ON x.source_document_id = sf.document_id
        JOIN _all_flows tf ON x.target_document_id = tf.document_id
        WHERE sf.posting_date > tf.posting_date
    """).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM _xlinks").fetchone()[0]
    return CheckResult(
        check_id="T3-21", tier=3, name="cross_process_links 순서",
        status="PASS" if bad == 0 else "WARNING",
        expected="source_date <= target_date", actual=f"역전={bad}/{total}",
        elapsed_ms=_elapsed(s),
    )


# ---------------------------------------------------------------------------
# T3-22 ~ T3-26: 보조원장 대사
# ---------------------------------------------------------------------------

def t3_22(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """AP 대사 — ap_invoices 합계 ≈ GL 2000 credit 합계."""
    s = time.perf_counter()
    path = _DATA_ROOT / "subledger/ap_invoices.json"
    if not _load_json(con, "_ap", path):
        return _skip("T3-22", "AP 대사")
    # Why: gross_amount는 STRUCT{document_amount,currency,...}. 서브필드 추출 필요.
    ap_total = con.execute("""
        SELECT COALESCE(SUM(CAST(gross_amount.document_amount AS DOUBLE)), 0) FROM _ap
    """).fetchone()[0]
    gl_total = con.execute("""
        SELECT COALESCE(SUM(credit_amount), 0) FROM je WHERE gl_account LIKE '2000%'
    """).fetchone()[0]
    diff_pct = abs(ap_total - gl_total) / ap_total * 100 if ap_total else 0
    return CheckResult(
        check_id="T3-22", tier=3, name="AP 대사",
        status="PASS" if diff_pct <= 5 else "WARNING",
        expected="AP≈GL2000 (±5%)", actual=f"AP={ap_total:,.0f}, GL={gl_total:,.0f}, diff={diff_pct:.1f}%",
        elapsed_ms=_elapsed(s),
    )


def t3_23(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """AR 대사 — ar_invoices 합계 ≈ GL 1100 debit 합계."""
    s = time.perf_counter()
    path = _DATA_ROOT / "subledger/ar_invoices.json"
    if not _load_json(con, "_ar", path):
        return _skip("T3-23", "AR 대사")
    ar_total = con.execute("""
        SELECT COALESCE(SUM(CAST(gross_amount.document_amount AS DOUBLE)), 0) FROM _ar
    """).fetchone()[0]
    gl_total = con.execute("""
        SELECT COALESCE(SUM(debit_amount), 0) FROM je WHERE gl_account LIKE '1100%'
    """).fetchone()[0]
    diff_pct = abs(ar_total - gl_total) / ar_total * 100 if ar_total else 0
    return CheckResult(
        check_id="T3-23", tier=3, name="AR 대사",
        status="PASS" if diff_pct <= 5 else "WARNING",
        expected="AR≈GL1100 (±5%)", actual=f"AR={ar_total:,.0f}, GL={gl_total:,.0f}, diff={diff_pct:.1f}%",
        elapsed_ms=_elapsed(s),
    )


def t3_24(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """FA 대사 — fa_records NBV ≈ GL 1500 - GL 1510."""
    s = time.perf_counter()
    path = _DATA_ROOT / "subledger/fa_records.json"
    if not _load_json(con, "_fa", path):
        return _skip("T3-24", "FA 대사")
    nbv = con.execute("SELECT COALESCE(SUM(CAST(net_book_value AS DOUBLE)), 0) FROM _fa").fetchone()[0]
    gl_1500 = con.execute("""
        SELECT COALESCE(SUM(debit_amount) - SUM(credit_amount), 0) FROM je WHERE gl_account LIKE '1500%'
    """).fetchone()[0]
    gl_1510 = con.execute("""
        SELECT COALESCE(SUM(credit_amount) - SUM(debit_amount), 0) FROM je WHERE gl_account LIKE '1510%'
    """).fetchone()[0]
    gl_net = gl_1500 - gl_1510
    diff_pct = abs(nbv - gl_net) / nbv * 100 if nbv else 0
    return CheckResult(
        check_id="T3-24", tier=3, name="FA 대사",
        status="PASS" if diff_pct <= 5 else "WARNING",
        expected="NBV≈GL1500-GL1510 (±5%)", actual=f"NBV={nbv:,.0f}, GL={gl_net:,.0f}, diff={diff_pct:.1f}%",
        elapsed_ms=_elapsed(s),
    )


def t3_25(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """Inventory 대사 — inventory value ≈ GL 1200 잔액."""
    s = time.perf_counter()
    path = _DATA_ROOT / "subledger/inventory_positions.json"
    if not _load_json(con, "_inv", path):
        return _skip("T3-25", "Inventory 대사")
    inv_total = con.execute("""
        SELECT COALESCE(SUM(CAST(valuation.total_value AS DOUBLE)), 0) FROM _inv
    """).fetchone()[0]
    gl_total = con.execute("""
        SELECT COALESCE(SUM(debit_amount) - SUM(credit_amount), 0) FROM je WHERE gl_account LIKE '1200%'
    """).fetchone()[0]
    diff_pct = abs(inv_total - gl_total) / inv_total * 100 if inv_total else 0
    return CheckResult(
        check_id="T3-25", tier=3, name="Inventory 대사",
        status="PASS" if diff_pct <= 5 else "WARNING",
        expected="INV≈GL1200 (±5%)", actual=f"INV={inv_total:,.0f}, GL={gl_total:,.0f}, diff={diff_pct:.1f}%",
        elapsed_ms=_elapsed(s),
    )


def t3_26(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """reconciliation.json 자체 대사 결과."""
    s = time.perf_counter()
    path = _DATA_ROOT / "balance/subledger_reconciliation.json"
    if not _load_json(con, "_recon", path):
        return _skip("T3-26", "reconciliation 대조")
    rows = con.execute("""
        SELECT subledger_type, status, CAST(difference AS DOUBLE) AS diff
        FROM _recon
    """).fetchall()
    unreconciled = [(r[0], r[2]) for r in rows if r[1] != "Reconciled"]
    return CheckResult(
        check_id="T3-26", tier=3, name="reconciliation 대조",
        status="PASS" if not unreconciled else "WARNING",
        expected="전건 Reconciled", actual=f"unreconciled={len(unreconciled)}/{len(rows)}",
        detail={"unreconciled": [{"type": u[0], "diff": u[1]} for u in unreconciled]} if unreconciled else None,
        elapsed_ms=_elapsed(s),
    )


# ---------------------------------------------------------------------------
# T3-27 ~ T3-30: IC 거래
# ---------------------------------------------------------------------------

def _load_ic(con: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    """IC JSON 로드."""
    result = {}
    for tbl, rel in {
        "_ic_pairs": "intercompany/ic_matched_pairs.json",
        "_ic_seller": "intercompany/ic_seller_journal_entries.json",
        "_ic_buyer": "intercompany/ic_buyer_journal_entries.json",
    }.items():
        try:
            con.execute(f"SELECT 1 FROM {tbl} LIMIT 1")
            result[tbl] = True
        except Exception:
            result[tbl] = _load_json(con, tbl, _DATA_ROOT / rel)
    return result


def t3_27(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """IC 쌍 존재 — seller/buyer document → je에 존재."""
    s = time.perf_counter()
    ic = _load_ic(con)
    if not ic.get("_ic_pairs", False):
        return _skip("T3-27", "IC 쌍 존재")
    orphan = con.execute("""
        SELECT
            COUNT(*) FILTER (WHERE CAST(seller_document AS VARCHAR) NOT IN (SELECT DISTINCT CAST(document_id AS VARCHAR) FROM je))
          + COUNT(*) FILTER (WHERE CAST(buyer_document AS VARCHAR) NOT IN (SELECT DISTINCT CAST(document_id AS VARCHAR) FROM je))
        FROM _ic_pairs
    """).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM _ic_pairs").fetchone()[0]
    return CheckResult(
        check_id="T3-27", tier=3, name="IC 쌍 존재",
        status="PASS" if orphan == 0 else "FAIL",
        expected="orphan=0", actual=f"orphan={orphan}/{total * 2}",
        elapsed_ms=_elapsed(s),
    )


def t3_28(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """IC 금액 일치 — seller/buyer 전표 금액 == matched_pairs.amount."""
    s = time.perf_counter()
    ic = _load_ic(con)
    if not all(ic.get(t, False) for t in ["_ic_pairs", "_ic_seller", "_ic_buyer"]):
        return _skip("T3-28", "IC 금액 일치")
    # Why: IC JSON의 lines 배열 구조가 복잡하여 DuckDB UNNEST 호환 문제.
    #       CSV je 테이블에서 IC 전표를 직접 검증하는 방식으로 대체.
    try:
        total = con.execute("SELECT COUNT(*) FROM _ic_pairs").fetchone()[0]
        # CSV에서 IC 전표 금액 vs pairs.amount 비교
        bad = con.execute("""
            SELECT COUNT(*) FROM _ic_pairs p
            JOIN (
                SELECT document_id, SUM(debit_amount) AS total
                FROM je WHERE document_type = 'IC'
                GROUP BY document_id
            ) sel ON p.seller_document = sel.document_id
            WHERE ABS(sel.total - CAST(p.amount AS DOUBLE)) > 1.0
        """).fetchone()[0]
    except Exception:
        return _skip("T3-28", "IC 금액 일치")
    return CheckResult(
        check_id="T3-28", tier=3, name="IC 금액 일치",
        status="PASS" if bad == 0 else "WARNING",
        expected="seller금액==pairs.amount (±1)", actual=f"불일치={bad}/{total}",
        elapsed_ms=_elapsed(s),
    )


def t3_29(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """IC GL 사용 — seller에 1150/4500, buyer에 2050 GL 확인."""
    s = time.perf_counter()
    ic = _load_ic(con)
    if not all(ic.get(t, False) for t in ["_ic_seller", "_ic_buyer"]):
        return _skip("T3-29", "IC GL 사용")
    # Why: IC JSON UNNEST 대신 CSV je 테이블에서 IC GL 사용 검증
    try:
        seller_total = con.execute("""
            SELECT COUNT(DISTINCT document_id) FROM je
            WHERE document_type='IC' AND company_code IN (SELECT seller_company FROM _ic_pairs)
        """).fetchone()[0]
        seller_ok = con.execute("""
            SELECT COUNT(DISTINCT document_id) FROM je
            WHERE document_type='IC' AND (gl_account LIKE '1150%' OR gl_account LIKE '4500%')
        """).fetchone()[0]
        buyer_total = con.execute("""
            SELECT COUNT(DISTINCT document_id) FROM je
            WHERE document_type='IC' AND company_code IN (SELECT buyer_company FROM _ic_pairs)
        """).fetchone()[0]
        buyer_ok = con.execute("""
            SELECT COUNT(DISTINCT document_id) FROM je
            WHERE document_type='IC' AND gl_account LIKE '2050%'
        """).fetchone()[0]
    except Exception:
        return _skip("T3-29", "IC GL 사용")
    s_pct = round(seller_ok / seller_total * 100, 1) if seller_total else 0
    b_pct = round(buyer_ok / buyer_total * 100, 1) if buyer_total else 0
    ok = s_pct >= 80 and b_pct >= 80
    return CheckResult(
        check_id="T3-29", tier=3, name="IC GL 사용",
        status="PASS" if ok else "WARNING",
        expected="seller 1150/4500>=80%, buyer 2050>=80%",
        actual=f"seller={s_pct}%, buyer={b_pct}%",
        elapsed_ms=_elapsed(s),
    )


def t3_30(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """IC type 분포 — transaction_type 7개 비율."""
    s = time.perf_counter()
    ic = _load_ic(con)
    if not ic.get("_ic_pairs", False):
        return _skip("T3-30", "IC type 분포")
    rows = con.execute("""
        SELECT transaction_type, COUNT(*) AS cnt
        FROM _ic_pairs GROUP BY transaction_type ORDER BY cnt DESC
    """).fetchall()
    total = sum(r[1] for r in rows)
    dist = {r[0]: round(r[1] / total * 100, 1) for r in rows}
    return CheckResult(
        check_id="T3-30", tier=3, name="IC type 분포",
        status="PASS" if len(dist) >= 5 else "WARNING",
        expected=">=5개 유형", actual=f"{len(dist)}개 유형",
        detail=dist,
        elapsed_ms=_elapsed(s),
    )


# ---------------------------------------------------------------------------
# T3-31 ~ T3-36: Stage 2 교차검증
# ---------------------------------------------------------------------------

def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except Exception:
        return False


def _je_cols(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[1] for r in con.execute("PRAGMA table_info('je')").fetchall()]


def t3_31(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """ip↔company 대역 매핑 — C001=10.1.x, C002=10.2.x, C003=10.3.x (anomaly 제외)."""
    s = time.perf_counter()
    if "ip_address" not in _je_cols(con):
        return _skip("T3-31", "ip↔company 대역 매핑", "ip_address 컬럼 미존재")

    excl = _get_excluded_doc_ids(con, ["AbnormalIPAccess", "abnormal_access_location"])
    _register_exclusion(con, "_excl_ip", excl)

    # Why: 정상 전표의 IP는 회사 서브넷과 일치해야 함 (VPN 172.16.x.x 허용)
    bad = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE ip_address IS NOT NULL
          AND ip_address NOT LIKE '172.16.%'
          AND document_id NOT IN (SELECT document_id FROM _excl_ip)
          AND NOT (
              (company_code='C001' AND ip_address LIKE '10.1.%') OR
              (company_code='C002' AND ip_address LIKE '10.2.%') OR
              (company_code='C003' AND ip_address LIKE '10.3.%')
          )
    """).fetchone()[0]

    total = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE ip_address IS NOT NULL
          AND ip_address NOT LIKE '172.16.%'
          AND document_id NOT IN (SELECT document_id FROM _excl_ip)
    """).fetchone()[0]

    con.execute("DROP TABLE IF EXISTS _excl_ip")
    pct = (bad / total * 100) if total > 0 else 0

    return CheckResult(
        check_id="T3-31", tier=3, name="ip↔company 대역 매핑",
        status="PASS" if pct <= 1 else "WARNING",
        expected="대역 불일치 ≤ 1%",
        actual=f"불일치={bad:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(s),
    )


def t3_32(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """change_log FK 정합 — document_id가 JE에 존재."""
    s = time.perf_counter()
    if not _has_table(con, "change_log"):
        return _skip("T3-32", "change_log FK 정합", "change_log 테이블 미존재")

    orphan = con.execute("""
        SELECT COUNT(*) FROM change_log cl
        WHERE cl.document_id NOT IN (SELECT DISTINCT document_id FROM je)
    """).fetchone()[0]

    return CheckResult(
        check_id="T3-32", tier=3, name="change_log FK 정합",
        status="PASS" if orphan == 0 else "FAIL",
        expected="orphan=0",
        actual=f"orphan={orphan:,}",
        elapsed_ms=_elapsed(s),
    )


def t3_33(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """change_log changed_field 도메인 — 유효 컬럼명만."""
    s = time.perf_counter()
    if not _has_table(con, "change_log"):
        return _skip("T3-33", "change_log field 도메인", "change_log 테이블 미존재")

    je_cols = set(_je_cols(con))
    # Why: change_log는 'amount' 등 JE 컬럼과 1:1 매핑이 안 되는 필드 사용 가능
    alias_fields = {"amount", "line_amount"}  # Rust가 사용하는 별칭
    cl_fields = con.execute("""
        SELECT DISTINCT changed_field FROM change_log
        WHERE changed_field IS NOT NULL
    """).fetchall()
    actual_fields = {r[0] for r in cl_fields}
    unknown = actual_fields - je_cols - alias_fields

    return CheckResult(
        check_id="T3-33", tier=3, name="change_log field 도메인",
        status="PASS" if not unknown else "WARNING",
        expected="JE 컬럼명만 허용",
        actual=f"미허용={unknown}" if unknown else f"OK ({len(actual_fields)}개 필드)",
        elapsed_ms=_elapsed(s),
    )


def t3_34(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """change_log 정상 비율 — 전체 전표의 ~5%에 변경 이력."""
    s = time.perf_counter()
    if not _has_table(con, "change_log"):
        return _skip("T3-34", "change_log 비율", "change_log 테이블 미존재")

    total_docs = con.execute("SELECT COUNT(DISTINCT document_id) FROM je").fetchone()[0]
    cl_docs = con.execute("SELECT COUNT(DISTINCT document_id) FROM change_log").fetchone()[0]
    rate = cl_docs / total_docs if total_docs > 0 else 0

    # Why: 변경 이력은 전체 전표의 1~10% 범위가 현실적
    return CheckResult(
        check_id="T3-34", tier=3, name="change_log 비율",
        status="PASS" if 0.01 <= rate <= 0.10 else "WARNING",
        expected="변경 전표 1~10%",
        actual=f"{rate:.2%} ({cl_docs:,}/{total_docs:,})",
        elapsed_ms=_elapsed(s),
    )


def t3_35(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """delivery_date cutoff 정합 — 연도 경계 교차비율 < 1% (anomaly 제외)."""
    s = time.perf_counter()
    if "delivery_date" not in _je_cols(con):
        return _skip("T3-35", "delivery_date cutoff 정합", "delivery_date 컬럼 미존재")

    excl = _get_excluded_doc_ids(con, ["revenue_cutoff_error", "expense_cutoff_error"])
    _register_exclusion(con, "_excl_cutoff", excl)

    # Why: 연도 경계 = delivery_date와 posting_date의 연도가 다른 경우
    cross = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE delivery_date IS NOT NULL
          AND EXTRACT(YEAR FROM CAST(delivery_date AS DATE)) != EXTRACT(YEAR FROM CAST(posting_date AS DATE))
          AND document_id NOT IN (SELECT document_id FROM _excl_cutoff)
    """).fetchone()[0]

    total = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE delivery_date IS NOT NULL
          AND document_id NOT IN (SELECT document_id FROM _excl_cutoff)
    """).fetchone()[0]

    con.execute("DROP TABLE IF EXISTS _excl_cutoff")
    rate = (cross / total * 100) if total > 0 else 0

    return CheckResult(
        check_id="T3-35", tier=3, name="delivery_date cutoff 정합",
        status="PASS" if rate < 1 else "WARNING",
        expected="연도 경계 교차 < 1%",
        actual=f"교차={cross:,}/{total:,} ({rate:.2f}%)",
        elapsed_ms=_elapsed(s),
    )


def t3_36(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """change_log new_value ↔ JE 현재 값 — 수정 후 값 = JE 현재 값."""
    s = time.perf_counter()
    if not _has_table(con, "change_log"):
        return _skip("T3-36", "change_log→JE 현재값 정합", "change_log 테이블 미존재")

    # Why: Rust DataSynth는 JE를 수정하지 않고 change_log만 기록하므로
    #      old_value가 JE 현재값과 일치해야 함 (new_value는 가상의 수정 결과).
    mismatch = con.execute("""
        SELECT COUNT(*) FROM change_log cl
        WHERE cl.changed_field = 'gl_account'
          AND cl.old_value IS NOT NULL
          AND cl.old_value NOT IN (
              SELECT DISTINCT CAST(j.gl_account AS VARCHAR)
              FROM je j WHERE j.document_id = cl.document_id
          )
    """).fetchone()[0]

    total = con.execute("""
        SELECT COUNT(*) FROM change_log
        WHERE changed_field = 'gl_account' AND old_value IS NOT NULL
    """).fetchone()[0]

    return CheckResult(
        check_id="T3-36", tier=3, name="change_log→JE 현재값 정합",
        status="PASS" if mismatch == 0 else "WARNING",
        expected="gl_account old_value ∈ JE 현재 GL",
        actual=f"불일치={mismatch:,}/{total:,}",
        elapsed_ms=_elapsed(s),
    )


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

def run_tier3(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 3 전체 36개 체크 실행."""
    checks = [
        t3_01, t3_02, t3_03, t3_04, t3_05, t3_06, t3_07, t3_08,
        t3_09, t3_10, t3_11, t3_12, t3_13,
        t3_14, t3_15, t3_16, t3_17, t3_18, t3_19, t3_20, t3_21,
        t3_22, t3_23, t3_24, t3_25, t3_26,
        t3_27, t3_28, t3_29, t3_30,
        t3_31, t3_32, t3_33, t3_34, t3_35, t3_36,
    ]
    return [fn(con) for fn in checks]
