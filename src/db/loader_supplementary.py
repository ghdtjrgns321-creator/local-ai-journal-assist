"""DataSynth 보조 JSON/CSV → DuckDB 적재 로더.

기존 loader.py(GL/anomaly/benford)와 분리하여
Document Flow·Master Data·Labels·Subledger 보조 데이터를 적재한다.

방어 전략:
  - 중첩 JSON → _normalize_nested_doc로 정규화 (KeyError/Empty 방어)
  - Pandas 타입 추론 ↔ DuckDB 엄격성 → _coerce_types로 DDL 기반 캐스팅
  - 파일 미존재 → 빈 리스트 (예외 없음)
  - 개별 로드 실패 → 로그 + 스킵
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pandas as pd

from src.db.schema_supplementary import (
    ANOMALY_LABELS_COLUMNS,
    CHANGE_LOG_COLUMNS,
    CUSTOMER_INVOICE_HEADERS_COLUMNS,
    CUSTOMER_INVOICE_LINES_COLUMNS,
    CUSTOMERS_COLUMNS,
    DELIVERY_HEADERS_COLUMNS,
    DELIVERY_LINES_COLUMNS,
    DOCUMENT_REFERENCES_COLUMNS,
    EMPLOYEES_COLUMNS,
    FIXED_ASSETS_COLUMNS,
    FRAUD_RED_FLAGS_COLUMNS,
    GOODS_RECEIPT_HEADERS_COLUMNS,
    GOODS_RECEIPT_LINES_COLUMNS,
    IC_MATCHED_PAIRS_COLUMNS,
    MATERIALS_COLUMNS,
    PAYMENT_ALLOCATIONS_COLUMNS,
    PAYMENT_HEADERS_COLUMNS,
    PURCHASE_ORDER_HEADERS_COLUMNS,
    PURCHASE_ORDER_LINES_COLUMNS,
    SALES_ORDER_HEADERS_COLUMNS,
    SALES_ORDER_LINES_COLUMNS,
    SUBLEDGER_AP_COLUMNS,
    SUBLEDGER_AR_COLUMNS,
    SUPPLEMENTARY_DDL,
    VENDOR_INVOICE_HEADERS_COLUMNS,
    VENDOR_INVOICE_LINES_COLUMNS,
    VENDORS_COLUMNS,
)

logger = logging.getLogger(__name__)

# ── DDL 타입 파싱 패턴 ──────────────────────────────────────

_DDL_TYPE_RE = re.compile(
    r"^\s+(\w+)\s+(VARCHAR|DOUBLE|INTEGER|BOOLEAN|TIMESTAMP|JSON)",
    re.MULTILINE,
)


# ── 유틸리티 (private) ──────────────────────────────────────


def _load_json_file(path: Path) -> list[dict]:
    """JSON 파일 → list[dict]. 파일 미존재 시 빈 리스트."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return []


def _parse_ddl_types(ddl: str) -> dict[str, str]:
    """DDL 문자열에서 {컬럼명: DuckDB타입} 매핑 추출."""
    return {m.group(1): m.group(2) for m in _DDL_TYPE_RE.finditer(ddl)}


def _coerce_types(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """SUPPLEMENTARY_DDL[table_name]에서 타입 매핑을 파싱하고 DataFrame 컬럼을 강제 캐스팅.

    - created_at 컬럼은 스킵 (DB DEFAULT)
    - df에 없는 DDL 컬럼은 무시
    """
    ddl = SUPPLEMENTARY_DDL.get(table_name, "")
    if not ddl:
        return df

    type_map = _parse_ddl_types(ddl)
    df = df.copy()

    for col, dtype in type_map.items():
        if col == "created_at" or col not in df.columns:
            continue

        if dtype == "VARCHAR":
            # Why: notna인 값만 str 변환, None/NaN은 DB NULL 보존
            mask = df[col].notna()
            df[col] = df[col].where(~mask, df[col].astype(str)).where(mask, None)
        elif dtype == "DOUBLE":
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        elif dtype == "INTEGER":
            df[col] = (
                pd.to_numeric(df[col], errors="coerce")
                .fillna(0)
                .astype("Int64")
            )
        elif dtype == "BOOLEAN":
            # Why: object dtype에서 fillna → 다운캐스팅 경고 방지
            col_ser = df[col]
            if col_ser.dtype == object:
                col_ser = col_ser.map(lambda x: False if pd.isna(x) else bool(x))
            else:
                col_ser = col_ser.astype("boolean").fillna(False)
            df[col] = col_ser.astype(bool)
        elif dtype == "TIMESTAMP":
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def _extract_header(record: dict) -> dict:
    """중첩 record에서 header dict를 추출하고 플랫화.

    record["header"] 안의 필드들 + record 최상위 스칼라 필드를 합친다.
    document_references, items 등 list/dict 필드는 제외.
    """
    header = dict(record.get("header", {}))
    header.pop("document_references", None)

    for key, val in record.items():
        if key == "header":
            continue
        if isinstance(val, (list, dict)):
            continue
        header[key] = val

    return header


def _normalize_nested_doc(
    records: list[dict],
    header_columns: list[str],
    lines_key: str = "items",
    lines_columns: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """중첩 JSON → (headers_df, lines_df, refs_df) 정규화.

    Returns: (headers_df, lines_df, refs_df) — 빈 경우에도 올바른 컬럼의 빈 DataFrame
    """
    all_headers: list[dict] = []
    all_lines: list[dict] = []
    all_refs: list[dict] = []

    for record in records:
        header = _extract_header(record)
        all_headers.append(header)

        doc_id = header.get("document_id", "")

        # lines 추출
        lines = record.get(lines_key, []) or []
        for line in lines:
            line["document_id"] = doc_id
            all_lines.append(line)

        # document_references 추출
        raw_header = record.get("header", {})
        refs = raw_header.get("document_references", []) or []
        for ref in refs:
            all_refs.append(ref)

    headers_df = (
        pd.DataFrame(all_headers) if all_headers
        else pd.DataFrame(columns=header_columns)
    )
    headers_df = headers_df.reindex(columns=header_columns)

    _lines_cols = lines_columns or []
    lines_df = (
        pd.DataFrame(all_lines) if all_lines
        else pd.DataFrame(columns=_lines_cols)
    )
    if _lines_cols:
        lines_df = lines_df.reindex(columns=_lines_cols)

    refs_df = (
        pd.DataFrame(all_refs) if all_refs
        else pd.DataFrame(columns=DOCUMENT_REFERENCES_COLUMNS)
    )
    refs_df = refs_df.reindex(columns=DOCUMENT_REFERENCES_COLUMNS)

    return headers_df, lines_df, refs_df


# Why: f-string SQL에 외부 입력이 들어가는 것을 방지 — allowlist 검증
_ALLOWED_TABLES = frozenset(SUPPLEMENTARY_DDL.keys())
_CONFLICT_IGNORE_TABLES = frozenset(
    table_name
    for table_name, ddl in SUPPLEMENTARY_DDL.items()
    if "PRIMARY KEY" in ddl.upper()
)


def _insert_df(
    conn,
    df: pd.DataFrame,
    table_name: str,
    columns: list[str],
    *,
    on_conflict_ignore: bool = True,
) -> int:
    """DataFrame을 DuckDB 테이블에 INSERT. coerce_types 적용.

    빈 DataFrame이면 0 반환.
    on_conflict_ignore=True: PK 충돌 시 무시 (document_references용).
    """
    if df.empty:
        return 0
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"허용되지 않은 테이블명: {table_name}")

    df = df.reindex(columns=columns)
    df = _coerce_types(df, table_name)

    col_list = ", ".join(columns)
    conflict = (
        " ON CONFLICT DO NOTHING"
        if on_conflict_ignore and table_name in _CONFLICT_IGNORE_TABLES
        else ""
    )
    before_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    conn.register("_tmp_df", df)
    try:
        conn.execute(
            f"INSERT INTO {table_name} ({col_list}) "
            f"SELECT * FROM _tmp_df{conflict}"
        )
    finally:
        conn.unregister("_tmp_df")
    after_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    return max(int(after_count) - int(before_count), 0)


# ── Document Flow 로드 (7개) ────────────────────────────────


def load_purchase_orders(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    headers_df, lines_df, refs_df = _normalize_nested_doc(
        records,
        header_columns=PURCHASE_ORDER_HEADERS_COLUMNS,
        lines_key="items",
        lines_columns=PURCHASE_ORDER_LINES_COLUMNS,
    )
    headers_df["upload_batch_id"] = batch_id
    lines_df["upload_batch_id"] = batch_id
    refs_df["upload_batch_id"] = batch_id

    header_count = _insert_df(
        conn, headers_df, "purchase_order_headers", PURCHASE_ORDER_HEADERS_COLUMNS
    )
    line_count = _insert_df(conn, lines_df, "purchase_order_lines", PURCHASE_ORDER_LINES_COLUMNS)
    _insert_df(
        conn,
        refs_df,
        "document_references",
        DOCUMENT_REFERENCES_COLUMNS,
        on_conflict_ignore=True,
    )
    return header_count + line_count


def load_goods_receipts(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    headers_df, lines_df, refs_df = _normalize_nested_doc(
        records,
        header_columns=GOODS_RECEIPT_HEADERS_COLUMNS,
        lines_key="items",
        lines_columns=GOODS_RECEIPT_LINES_COLUMNS,
    )
    headers_df["upload_batch_id"] = batch_id
    lines_df["upload_batch_id"] = batch_id
    refs_df["upload_batch_id"] = batch_id

    header_count = _insert_df(
        conn, headers_df, "goods_receipt_headers", GOODS_RECEIPT_HEADERS_COLUMNS
    )
    line_count = _insert_df(conn, lines_df, "goods_receipt_lines", GOODS_RECEIPT_LINES_COLUMNS)
    _insert_df(
        conn,
        refs_df,
        "document_references",
        DOCUMENT_REFERENCES_COLUMNS,
        on_conflict_ignore=True,
    )
    return header_count + line_count


def load_vendor_invoices(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    headers_df, lines_df, refs_df = _normalize_nested_doc(
        records,
        header_columns=VENDOR_INVOICE_HEADERS_COLUMNS,
        lines_key="items",
        lines_columns=VENDOR_INVOICE_LINES_COLUMNS,
    )
    headers_df["upload_batch_id"] = batch_id
    lines_df["upload_batch_id"] = batch_id
    refs_df["upload_batch_id"] = batch_id

    header_count = _insert_df(
        conn, headers_df, "vendor_invoice_headers", VENDOR_INVOICE_HEADERS_COLUMNS
    )
    line_count = _insert_df(
        conn, lines_df, "vendor_invoice_lines", VENDOR_INVOICE_LINES_COLUMNS
    )
    _insert_df(
        conn,
        refs_df,
        "document_references",
        DOCUMENT_REFERENCES_COLUMNS,
        on_conflict_ignore=True,
    )
    return header_count + line_count


def load_payments(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    headers_df, lines_df, refs_df = _normalize_nested_doc(
        records,
        header_columns=PAYMENT_HEADERS_COLUMNS,
        lines_key="allocations",
        lines_columns=PAYMENT_ALLOCATIONS_COLUMNS,
    )
    headers_df["upload_batch_id"] = batch_id
    lines_df["upload_batch_id"] = batch_id
    refs_df["upload_batch_id"] = batch_id

    header_count = _insert_df(conn, headers_df, "payment_headers", PAYMENT_HEADERS_COLUMNS)
    line_count = _insert_df(conn, lines_df, "payment_allocations", PAYMENT_ALLOCATIONS_COLUMNS)
    _insert_df(
        conn,
        refs_df,
        "document_references",
        DOCUMENT_REFERENCES_COLUMNS,
        on_conflict_ignore=True,
    )
    return header_count + line_count


def load_sales_orders(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    headers_df, lines_df, refs_df = _normalize_nested_doc(
        records,
        header_columns=SALES_ORDER_HEADERS_COLUMNS,
        lines_key="items",
        lines_columns=SALES_ORDER_LINES_COLUMNS,
    )
    headers_df["upload_batch_id"] = batch_id
    lines_df["upload_batch_id"] = batch_id
    refs_df["upload_batch_id"] = batch_id

    header_count = _insert_df(conn, headers_df, "sales_order_headers", SALES_ORDER_HEADERS_COLUMNS)
    line_count = _insert_df(conn, lines_df, "sales_order_lines", SALES_ORDER_LINES_COLUMNS)
    _insert_df(
        conn,
        refs_df,
        "document_references",
        DOCUMENT_REFERENCES_COLUMNS,
        on_conflict_ignore=True,
    )
    return header_count + line_count


def load_deliveries(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    headers_df, lines_df, refs_df = _normalize_nested_doc(
        records,
        header_columns=DELIVERY_HEADERS_COLUMNS,
        lines_key="items",
        lines_columns=DELIVERY_LINES_COLUMNS,
    )
    headers_df["upload_batch_id"] = batch_id
    lines_df["upload_batch_id"] = batch_id
    refs_df["upload_batch_id"] = batch_id

    header_count = _insert_df(conn, headers_df, "delivery_headers", DELIVERY_HEADERS_COLUMNS)
    line_count = _insert_df(conn, lines_df, "delivery_lines", DELIVERY_LINES_COLUMNS)
    _insert_df(
        conn,
        refs_df,
        "document_references",
        DOCUMENT_REFERENCES_COLUMNS,
        on_conflict_ignore=True,
    )
    return header_count + line_count


def load_customer_invoices(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    headers_df, lines_df, refs_df = _normalize_nested_doc(
        records,
        header_columns=CUSTOMER_INVOICE_HEADERS_COLUMNS,
        lines_key="items",
        lines_columns=CUSTOMER_INVOICE_LINES_COLUMNS,
    )
    headers_df["upload_batch_id"] = batch_id
    lines_df["upload_batch_id"] = batch_id
    refs_df["upload_batch_id"] = batch_id

    header_count = _insert_df(
        conn, headers_df, "customer_invoice_headers", CUSTOMER_INVOICE_HEADERS_COLUMNS
    )
    line_count = _insert_df(
        conn, lines_df, "customer_invoice_lines", CUSTOMER_INVOICE_LINES_COLUMNS
    )
    _insert_df(
        conn,
        refs_df,
        "document_references",
        DOCUMENT_REFERENCES_COLUMNS,
        on_conflict_ignore=True,
    )
    return header_count + line_count


# ── Master Data 로드 (5개) ──────────────────────────────────


def _flatten_master_record(record: dict) -> dict:
    """Master Data JSON에서 list/dict 중첩 필드를 제거한 플랫 dict 반환."""
    return {
        k: v for k, v in record.items()
        if not isinstance(v, (list, dict))
    }


def load_vendors(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = [_flatten_master_record(r) for r in records]
    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "vendors", VENDORS_COLUMNS)


def load_customers(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = [_flatten_master_record(r) for r in records]
    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "customers", CUSTOMERS_COLUMNS)


def load_employees(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = [_flatten_master_record(r) for r in records]
    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "employees", EMPLOYEES_COLUMNS)


def load_materials(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = []
    for r in records:
        flat = _flatten_master_record(r)
        # Why: base_uom이 {"code": "EA", ...} dict인 경우 코드만 추출
        uom = r.get("base_uom")
        if isinstance(uom, dict):
            flat["base_uom"] = uom.get("code", str(uom))
        rows.append(flat)

    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "materials", MATERIALS_COLUMNS)


def load_fixed_assets(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = [_flatten_master_record(r) for r in records]
    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "fixed_assets", FIXED_ASSETS_COLUMNS)


# ── Labels 로드 (2개) ───────────────────────────────────────


def load_anomaly_labels_json(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = []
    for r in records:
        flat = {
            k: v for k, v in r.items()
            if not isinstance(v, (list, dict))
        }

        # Why: anomaly_type이 {"Relational": "UnusualAccountPair"} dict인 경우
        #      category=key, subtype=value로 분해
        atype = r.get("anomaly_type")
        if isinstance(atype, dict):
            flat["anomaly_category"] = next(iter(atype.keys()), "")
            flat["anomaly_subtype"] = next(iter(atype.values()), "")
            flat["anomaly_type"] = json.dumps(atype, ensure_ascii=False)
        else:
            flat.setdefault("anomaly_category", "")
            flat.setdefault("anomaly_subtype", "")

        rows.append(flat)

    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(
        conn,
        df,
        "anomaly_labels",
        ANOMALY_LABELS_COLUMNS,
        on_conflict_ignore=True,
    )


def load_fraud_red_flags(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = []
    for r in records:
        flat = {
            k: v for k, v in r.items()
            if k != "details" and not isinstance(v, (list, dict))
        }
        # Why: details dict → JSON 문자열로 직렬화
        details = r.get("details")
        if isinstance(details, dict):
            flat["details_json"] = json.dumps(details, ensure_ascii=False)
        else:
            flat["details_json"] = ""
        rows.append(flat)

    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "fraud_red_flags", FRAUD_RED_FLAGS_COLUMNS)


# ── P1 로드 (4개) ───────────────────────────────────────────

# Subledger에서 skip할 중첩 필드
_AP_SKIP_KEYS = {"lines", "tax_details", "clearing_info", "withholding_tax", "notes"}
_AR_SKIP_KEYS = {"dunning_info", "reference_documents", "tax_details"}


def _flatten_subledger_record(
    record: dict,
    skip_keys: set[str],
) -> dict:
    """Subledger JSON에서 중첩 필드를 skip하고 플랫 dict 반환.

    payment_terms dict → code 추출, 금액 dict → amount 추출.
    """
    flat: dict = {}
    for k, v in record.items():
        if k in skip_keys:
            continue

        # payment_terms가 {"code": "NET30", "days": 30} 형태
        if k == "payment_terms" and isinstance(v, dict):
            flat[k] = v.get("code", str(v))
            continue

        # 금액 필드가 {"amount": 1000, "currency": "KRW"} 형태
        if isinstance(v, dict) and "amount" in v:
            flat[k] = v.get("amount", 0.0)
            continue

        if isinstance(v, (list, dict)):
            continue

        flat[k] = v

    return flat


def load_subledger_ap(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = [_flatten_subledger_record(r, _AP_SKIP_KEYS) for r in records]
    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "subledger_ap", SUBLEDGER_AP_COLUMNS)


def load_subledger_ar(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    rows = [_flatten_subledger_record(r, _AR_SKIP_KEYS) for r in records]
    df = pd.DataFrame(rows)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "subledger_ar", SUBLEDGER_AR_COLUMNS)


def load_ic_matched_pairs(conn, path: Path, batch_id: str) -> int:
    records = _load_json_file(path)
    if not records:
        return 0

    # 완전 플랫 JSON
    df = pd.DataFrame(records)
    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "ic_matched_pairs", IC_MATCHED_PAIRS_COLUMNS)


def load_change_log(conn, path: Path, batch_id: str) -> int:
    if not path.exists():
        return 0

    df = pd.read_csv(path, encoding="utf-8")
    if df.empty:
        return 0

    df["upload_batch_id"] = batch_id
    return _insert_df(conn, df, "change_log", CHANGE_LOG_COLUMNS)


# ── 통합 함수 ───────────────────────────────────────────────

# (상대경로, 이름, 로더함수) 매핑
_LOADERS: list[tuple[str, str, object]] = [
    # Document Flows
    ("document_flows/purchase_orders.json", "purchase_orders", load_purchase_orders),
    ("document_flows/goods_receipts.json", "goods_receipts", load_goods_receipts),
    ("document_flows/vendor_invoices.json", "vendor_invoices", load_vendor_invoices),
    ("document_flows/payments.json", "payments", load_payments),
    ("document_flows/sales_orders.json", "sales_orders", load_sales_orders),
    ("document_flows/deliveries.json", "deliveries", load_deliveries),
    ("document_flows/customer_invoices.json", "customer_invoices", load_customer_invoices),
    # Master Data
    ("master_data/vendors.json", "vendors", load_vendors),
    ("master_data/customers.json", "customers", load_customers),
    ("master_data/employees.json", "employees", load_employees),
    ("master_data/materials.json", "materials", load_materials),
    ("master_data/fixed_assets.json", "fixed_assets", load_fixed_assets),
    # Labels
    ("labels/anomaly_labels.json", "anomaly_labels", load_anomaly_labels_json),
    ("labels/fraud_red_flags.json", "fraud_red_flags", load_fraud_red_flags),
    # P1
    ("subledger/ap_invoices.json", "subledger_ap", load_subledger_ap),
    ("subledger/ar_invoices.json", "subledger_ar", load_subledger_ar),
    ("intercompany/ic_matched_pairs.json", "ic_matched_pairs", load_ic_matched_pairs),
    ("change_log.csv", "change_log", load_change_log),
]


def load_supplementary(
    conn,
    datasynth_dir: Path,
    batch_id: str,
) -> dict[str, int]:
    """DataSynth 보조 데이터 일괄 적재.

    각 파일별로 try/except → 실패 시 로그 후 스킵.
    Returns: {"purchase_orders": 120, "vendors": 50, ...} 테이블별 적재 건수
    """
    counts: dict[str, int] = {}

    for rel_path, name, loader_fn in _LOADERS:
        full_path = datasynth_dir / rel_path
        try:
            n = loader_fn(conn, full_path, batch_id)
            if n > 0:
                counts[name] = n
                logger.info("Supplementary data loaded: %s = %d rows", name, n)
        except Exception:
            logger.warning("Supplementary data load failed; skipping: %s", name, exc_info=True)

    return counts
