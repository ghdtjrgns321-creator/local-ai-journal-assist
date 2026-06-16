"""
audit_document_flow.py
문서흐름(Document Flow) 체인 무결성 측정 스크립트.
측정·보고 전용 — 데이터 수정 없음.
"""

import json
import pathlib
import sys
from decimal import Decimal, InvalidOperation

import duckdb
import pandas as pd

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "journal" / "primary"

NORMAL_DIR = (
    pathlib.Path(sys.argv[1])
    if len(sys.argv) > 1
    else DATA_ROOT / "datasynth_semantic_v1_normal_20260613_v42j"
)
FRAUD_DIR = (
    pathlib.Path(sys.argv[2])
    if len(sys.argv) > 2
    else DATA_ROOT / "datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b"
)

FLOW_NORMAL = NORMAL_DIR / "document_flows"
FLOW_FRAUD = FRAUD_DIR / "document_flows"
REL_NORMAL = NORMAL_DIR / "relationships" / "cross_process_links.json"
PROV_CSV = FRAUD_DIR / "labels" / "phase2_scheme_provenance.csv"

# GR/IR 계정 식별: 하드코딩 금지 — semantic_account_subtype='GRIR'로 동적 조회
GRIR_SUBTYPE = "GRIR"


# ─── 유틸 ────────────────────────────────────────────────────────────────────


def load_json(path: pathlib.Path) -> list:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # 간혹 dict 래퍼로 감싸진 경우 대비
        if "items" in data:
            return data["items"]
        return list(data.values())
    return data


def doc_id(doc: dict) -> str:
    return doc["header"]["document_id"]


def doc_refs(doc: dict) -> list[str]:
    """document_references 에서 source_doc_id 목록 반환"""
    return [r["source_doc_id"] for r in doc["header"].get("document_references", [])]


def to_decimal(val) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except InvalidOperation:
        return None


def fmt_rate(num: int, denom: int) -> str:
    if denom == 0:
        return "0/0 (N/A)"
    return f"{num}/{denom} ({num / denom * 100:.1f}%)"


# ─── 1. P2P 체인 검사 ─────────────────────────────────────────────────────────


def check_p2p(flow_dir: pathlib.Path, label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"[1] P2P 체인 무결성 — {label}")
    print("=" * 60)

    pos = load_json(flow_dir / "purchase_orders.json")
    grs = load_json(flow_dir / "goods_receipts.json")
    vis = load_json(flow_dir / "vendor_invoices.json")
    pays = load_json(flow_dir / "payments.json")

    po_ids = {doc_id(d) for d in pos}
    gr_ids = {doc_id(d) for d in grs}
    vi_ids = {doc_id(d) for d in vis}
    pay_ids = {doc_id(d) for d in pays}

    print(f"  PO: {len(po_ids)}  GR: {len(gr_ids)}  VI: {len(vi_ids)}  PAY: {len(pay_ids)}")

    # ── 1-a. Orphan 검사 (상위 문서 없는 하위 문서) ──────────────────────────

    # GR → PO 역참조
    gr_orphan = sum(1 for d in grs if d.get("purchase_order_id") not in po_ids)
    # VI → PO 역참조
    vi_orphan_po = sum(1 for d in vis if d.get("purchase_order_id") not in po_ids)
    # VI → GR 역참조
    vi_orphan_gr = sum(1 for d in vis if d.get("goods_receipt_id") not in gr_ids)
    # PAY → VI via allocations
    # 부정 데이터셋은 일부 alloc이 invoice_id 대신 document_id 키를 가짐 — 데이터 특성으로 계수
    pay_orphan = 0
    pay_nonstandard_alloc = 0  # invoice_id 키 없는 alloc 보유 PAY 수
    for d in pays:
        has_nonstandard = False
        orphan_this = False
        for alloc in d.get("allocations", []):
            if "invoice_id" not in alloc:
                has_nonstandard = True
            elif alloc["invoice_id"] not in vi_ids:
                orphan_this = True
        if has_nonstandard:
            pay_nonstandard_alloc += 1
        elif orphan_this:
            pay_orphan += 1

    print("\n  1-a. Orphan (상위 문서 미참조)")
    print(f"    GR→PO 없음:  {fmt_rate(gr_orphan, len(grs))}")
    print(f"    VI→PO 없음:  {fmt_rate(vi_orphan_po, len(vis))}")
    print(f"    VI→GR 없음:  {fmt_rate(vi_orphan_gr, len(vis))}")
    print(f"    PAY→VI 없음: {fmt_rate(pay_orphan, len(pays))}")
    if pay_nonstandard_alloc > 0:
        print(
            f"    PAY 비표준alloc(invoice_id 키 없음): {pay_nonstandard_alloc}건 [데이터 특성 — fraud scheme 비정형 payment]"
        )

    orphan_verdict = all(x == 0 for x in [gr_orphan, vi_orphan_po, vi_orphan_gr, pay_orphan])
    print(f"    → {'PASS' if orphan_verdict else 'FAIL (orphan 존재)'}")

    # ── 1-b. PO 수량 vs GR 수량 정합 ─────────────────────────────────────────
    po_qty: dict[str, Decimal] = {}
    for d in pos:
        total = sum((to_decimal(it["quantity"]) or Decimal(0)) for it in d.get("items", []))
        po_qty[doc_id(d)] = total

    gr_qty_by_po: dict[str, Decimal] = {}
    for d in grs:
        po_ref = d.get("purchase_order_id")
        if not po_ref:
            continue
        qty = sum((to_decimal(it["quantity"]) or Decimal(0)) for it in d.get("items", []))
        gr_qty_by_po[po_ref] = gr_qty_by_po.get(po_ref, Decimal(0)) + qty

    qty_ok = qty_over = qty_under = 0
    for po_id_k, po_q in po_qty.items():
        gr_q = gr_qty_by_po.get(po_id_k, Decimal(0))
        if gr_q == 0:
            qty_under += 1  # GR 없음 (미수령)
        elif gr_q > po_q * Decimal("1.01"):  # 1% 허용오차
            qty_over += 1
        else:
            qty_ok += 1

    print(f"\n  1-b. PO vs GR 수량 정합 (PO 기준 {len(po_qty)}건)")
    print(f"    정상:      {qty_ok}")
    print(f"    GR 초과:   {qty_over}  ← 데이터 특성(부분수령/분할GR 포함)")
    print(f"    GR 미기록: {qty_under}  ← 미수령 PO (정상 가능)")
    qty_verdict = qty_over == 0
    print(f"    → {'PASS' if qty_verdict else 'FAIL (GR 수량 초과)'}")

    # ── 1-c. 금액 정합 (VI vs PAY) ───────────────────────────────────────────
    vi_amt: dict[str, Decimal] = {}
    for d in vis:
        amt = to_decimal(d.get("gross_amount")) or Decimal(0)
        vi_amt[doc_id(d)] = amt

    pay_alloc_sum: dict[str, Decimal] = {}
    for d in pays:
        for alloc in d.get("allocations", []):
            # 비표준 alloc(invoice_id 키 없음)은 금액 집계에서 제외 — 데이터 특성
            if "invoice_id" not in alloc:
                continue
            inv_id = alloc["invoice_id"]
            paid = to_decimal(alloc.get("amount")) or Decimal(0)
            pay_alloc_sum[inv_id] = pay_alloc_sum.get(inv_id, Decimal(0)) + paid

    amt_over = amt_under = amt_ok = 0
    tol = Decimal("0.02")  # 2센트 오차 허용
    for vi_id_k, vi_a in vi_amt.items():
        paid_a = pay_alloc_sum.get(vi_id_k, Decimal(0))
        diff = paid_a - vi_a
        if abs(diff) <= tol:
            amt_ok += 1
        elif diff > tol:
            amt_over += 1
        else:
            amt_under += 1  # 미결제

    print(f"\n  1-c. VI vs PAY 금액 정합 (VI 기준 {len(vi_amt)}건)")
    print(f"    일치:    {amt_ok}")
    print(f"    초과결제: {amt_over}")
    print(f"    미결제:  {amt_under}  ← 미납 인보이스 (정상 가능)")
    amt_verdict = amt_over == 0
    print(f"    → {'PASS' if amt_verdict else 'FAIL (초과결제 존재)'}")


# ─── 2. O2C 체인 검사 ─────────────────────────────────────────────────────────


def check_o2c(flow_dir: pathlib.Path, label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"[2] O2C 체인 무결성 — {label}")
    print("=" * 60)

    sos = load_json(flow_dir / "sales_orders.json")
    dlvs = load_json(flow_dir / "deliveries.json")
    cis = load_json(flow_dir / "customer_invoices.json")

    so_ids = {doc_id(d) for d in sos}
    dlv_ids = {doc_id(d) for d in dlvs}
    ci_ids = {doc_id(d) for d in cis}

    print(f"  SO: {len(so_ids)}  DLV: {len(dlv_ids)}  CI: {len(ci_ids)}")

    # ── 2-a. DLV → SO 연결 ───────────────────────────────────────────────────
    dlv_no_so = sum(1 for d in dlvs if d.get("sales_order_id") not in so_ids)
    dlv_so_null = sum(1 for d in dlvs if not d.get("sales_order_id"))
    print("\n  2-a. DLV→SO 역참조")
    print(f"    DLV SO참조 없음(SO 부재): {fmt_rate(dlv_no_so, len(dlvs))}")
    print(f"    DLV SO필드 null:          {fmt_rate(dlv_so_null, len(dlvs))}")

    # ── 2-b. CI → SO 연결 ────────────────────────────────────────────────────
    ci_no_so = sum(1 for d in cis if d.get("sales_order_id") not in so_ids)
    ci_so_null = sum(1 for d in cis if not d.get("sales_order_id"))
    ci_no_dlv = sum(1 for d in cis if d.get("delivery_id") not in dlv_ids)
    ci_dlv_null = sum(1 for d in cis if not d.get("delivery_id"))
    print("\n  2-b. CI→SO / CI→DLV 역참조")
    print(f"    CI SO참조 없음(SO 부재):  {fmt_rate(ci_no_so, len(cis))}")
    print(f"    CI SO필드 null:           {fmt_rate(ci_so_null, len(cis))}")
    print(f"    CI DLV참조 없음(DLV 부재):{fmt_rate(ci_no_dlv, len(cis))}")
    print(f"    CI DLV필드 null:          {fmt_rate(ci_dlv_null, len(cis))}")

    # 22k CI vs 50 SO 비율 분석 (의미 있는 핵심 지표)
    ci_linked_so = sum(
        1 for d in cis if d.get("sales_order_id") and d.get("sales_order_id") in so_ids
    )
    ci_with_any_so = sum(1 for d in cis if d.get("sales_order_id"))
    print(f"\n  [핵심] SO 50건 vs CI {len(cis)}건 연결 현황")
    print(f"    SO 존재 집합에 매핑된 CI:   {fmt_rate(ci_linked_so, len(cis))}")
    print(f"    SO 필드 보유(실존 여부 무관):{fmt_rate(ci_with_any_so, len(cis))}")

    # SO당 평균 CI 수
    so_ci_count: dict[str, int] = {}
    for d in cis:
        so_ref = d.get("sales_order_id")
        if so_ref:
            so_ci_count[so_ref] = so_ci_count.get(so_ref, 0) + 1
    if so_ci_count:
        avg_ci = sum(so_ci_count.values()) / len(so_ci_count)
        max_ci = max(so_ci_count.values())
        print(f"    SO당 평균 CI: {avg_ci:.1f}  최대: {max_ci}")

    dlv_verdict = dlv_no_so == 0
    ci_verdict = ci_no_so == 0 and ci_no_dlv == 0
    print(
        f"\n  → DLV→SO: {'PASS' if dlv_verdict else 'FAIL'} | CI→SO+DLV: {'PASS' if ci_verdict else 'FAIL'}"
    )


# ─── 3. Journal ↔ Flow 링크 ──────────────────────────────────────────────────


def check_journal_flow_link(base_dir: pathlib.Path, label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"[3] Journal ↔ Flow 링크 — {label}")
    print("=" * 60)

    # flow 문서의 journal_entry_id 수집
    flow_je_ids: list[str] = []
    flow_doc_ids: set[str] = set()
    for fname in [
        "purchase_orders",
        "goods_receipts",
        "vendor_invoices",
        "payments",
        "sales_orders",
        "deliveries",
        "customer_invoices",
    ]:
        docs = load_json(base_dir / "document_flows" / f"{fname}.json")
        for d in docs:
            flow_doc_ids.add(d["header"]["document_id"])
            je_id = d["header"].get("journal_entry_id")
            if je_id:
                flow_je_ids.append(je_id)

    # journal_entries에서 document_id 수집 (DuckDB)
    je_csv = base_dir / "journal_entries.csv"
    con = duckdb.connect()
    je_doc_ids = set(
        con.execute(f"SELECT DISTINCT document_id FROM read_csv_auto('{je_csv.as_posix()}')")
        .fetchdf()["document_id"]
        .tolist()
    )
    je_references = set(
        row[0]
        for row in con.execute(
            f"SELECT DISTINCT reference FROM read_csv_auto('{je_csv.as_posix()}') WHERE reference IS NOT NULL"
        ).fetchall()
    )
    total_je = con.execute(
        f"SELECT COUNT(DISTINCT document_id) FROM read_csv_auto('{je_csv.as_posix()}')"
    ).fetchone()[0]
    con.close()

    # Flow → JE: flow에서 journal_entry_id가 실제 JE에 존재하는 비율
    total_flow_je = len(flow_je_ids)
    if total_flow_je > 0:
        found_je = sum(1 for jid in flow_je_ids if jid in je_doc_ids)
        print(f"  Flow→JE: {fmt_rate(found_je, total_flow_je)}")
        print(f"    (journal_entry_id 보유 flow 문서 {total_flow_je}건 중 JE에 실재)")
    else:
        print("  Flow→JE: flow 문서에 journal_entry_id 필드가 모두 null")
        print("    → OBSERVE: flow ↔ JE 직접 ID 링크 없음 (설계 확인 필요)")

    # JE → Flow: journal reference가 flow doc_id를 가리키는 비율
    je_ref_to_flow = sum(1 for ref in je_references if ref in flow_doc_ids)
    print(
        f"  JE→Flow 역방향: reference가 flow doc_id를 가리킴 = {fmt_rate(je_ref_to_flow, len(je_references))} (reference 고유값 {len(je_references)}건 기준)"
    )
    print(f"  총 JE 문서 수: {total_je}, 총 Flow 문서 수: {len(flow_doc_ids)}")


# ─── 4. GR/IR 청산 잔액 ──────────────────────────────────────────────────────


def check_grir(base_dir: pathlib.Path, label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"[4] GR/IR 청산 잔액 — {label}")
    print("=" * 60)

    je_csv = base_dir / "journal_entries.csv"
    con = duckdb.connect()

    # GR/IR 계정: 고정 계정코드 사용 금지 — semantic_account_subtype='GRIR'로 동적 식별
    result = con.execute(f"""
        SELECT
            gl_account,
            SUM(COALESCE(debit_amount, 0) - COALESCE(credit_amount, 0)) AS net_balance,
            COUNT(*) AS line_count,
            SUM(COALESCE(debit_amount, 0)) AS total_debit,
            SUM(COALESCE(credit_amount, 0)) AS total_credit
        FROM read_csv_auto('{je_csv.as_posix()}')
        WHERE semantic_account_subtype = '{GRIR_SUBTYPE}'
        GROUP BY gl_account
        ORDER BY gl_account
    """).fetchdf()
    con.close()

    if result.empty:
        print("  GRIR subtype 전표 없음 — OBSERVE")
    else:
        total_grir_balance = result["net_balance"].sum()
        print(f"  GRIR subtype 계정 수: {len(result)}  총 순잔액: {total_grir_balance:,.0f}")
        for _, row in result.iterrows():
            bal = row["net_balance"]
            rationality = (
                "합리적(소액 미청산)" if abs(bal) < 500_000 else "대규모 미청산 — 검토 필요"
            )
            print(
                f"  계정 {row['gl_account']}: 순잔액={bal:,.0f}"
                f"  (Dr={row['total_debit']:,.0f}, Cr={row['total_credit']:,.0f})"
                f"  [line={int(row['line_count'])}]  → {rationality}"
            )
        grir_verdict = abs(total_grir_balance) < 50_000_000  # 5천만 이하 합리적
        print(
            f"  → {'PASS (전체 미청산 잔액 합리적)' if grir_verdict else 'FAIL (전체 미청산 잔액 비대 — 검토 필요)'}"
        )


# ─── 5. Fraud 문서 Flow 멤버십 ────────────────────────────────────────────────


def check_fraud_flow_membership() -> None:
    print(f"\n{'=' * 60}")
    print(f"[5] Fraud 부정 문서 Flow 멤버십 — {FRAUD_DIR.name}")
    print("=" * 60)

    prov = pd.read_csv(PROV_CSV)
    fraud_doc_ids = set(prov["document_id"].dropna().astype(str).tolist())
    print(f"  provenance 부정 문서 수: {len(fraud_doc_ids)}")
    print(f"  유니크 scheme: {sorted(prov['scheme_id'].unique().tolist())}")

    # flow 전체 문서 ID 수집
    flow_doc_ids: set[str] = set()
    for fname in [
        "purchase_orders",
        "goods_receipts",
        "vendor_invoices",
        "payments",
        "sales_orders",
        "deliveries",
        "customer_invoices",
    ]:
        docs = load_json(FLOW_FRAUD / f"{fname}.json")
        for d in docs:
            flow_doc_ids.add(d["header"]["document_id"])

    # fraud doc_id 형식 샘플 vs flow doc_id 형식 샘플
    fraud_sample = list(fraud_doc_ids)[:3]
    flow_sample = list(flow_doc_ids)[:3]
    print(f"  fraud doc_id 형식 예: {fraud_sample}")
    print(f"  flow doc_id 형식 예:  {flow_sample}")

    # 교집합
    in_flow = fraud_doc_ids & flow_doc_ids
    print(f"\n  fraud 문서 중 flow 멤버: {fmt_rate(len(in_flow), len(fraud_doc_ids))}")
    print(
        f"    → {'PASS (fraud 문서가 flow에 포함됨)' if len(in_flow) > 0 else 'OBSERVE: fraud doc_id가 flow doc_id 공간과 분리됨 (UUID vs ERP 코드 형식 차이 가능)'}"
    )

    # journal_exposed 기준 분리 분석
    journal_exposed_true = prov[prov["journal_exposed"] == True]
    journal_exposed_false = prov[prov["journal_exposed"] == False]
    print(f"\n  journal_exposed=True:  {len(journal_exposed_true)}건")
    print(f"  journal_exposed=False: {len(journal_exposed_false)}건")
    print("  → fraud 문서는 journal 노출 여부가 명시됨 (flow 직접 멤버십과 별개)")


# ─── 6. cross_process_links Dangling ─────────────────────────────────────────


def check_cross_process_links(base_dir: pathlib.Path, label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"[6] cross_process_links Dangling — {label}")
    print("=" * 60)

    links = load_json(base_dir / "relationships" / "cross_process_links.json")
    print(f"  총 링크: {len(links)}")

    # 모든 flow 문서 ID 수집
    flow_doc_ids: set[str] = set()
    for fname in [
        "purchase_orders",
        "goods_receipts",
        "vendor_invoices",
        "payments",
        "sales_orders",
        "deliveries",
        "customer_invoices",
    ]:
        docs = load_json(base_dir / "document_flows" / f"{fname}.json")
        for d in docs:
            flow_doc_ids.add(d["header"]["document_id"])

    # dangling 검사
    # cross_process_links 는 두 가지 스키마 혼재:
    #   스키마 A (inventory_movement 등): source_document_id / target_document_id
    #   스키마 B (document_reference):    source_doc_id / target_doc_id
    def _src(lk: dict) -> str:
        return lk.get("source_document_id") or lk.get("source_doc_id", "")

    def _tgt(lk: dict) -> str:
        return lk.get("target_document_id") or lk.get("target_doc_id", "")

    # 스키마별 건수 확인
    schema_a = sum(1 for lk in links if "source_document_id" in lk)
    schema_b = sum(1 for lk in links if "source_doc_id" in lk)
    print(f"  스키마A(source_document_id): {schema_a}건  스키마B(source_doc_id): {schema_b}건")

    dangling_src = sum(1 for lk in links if _src(lk) not in flow_doc_ids)
    dangling_tgt = sum(1 for lk in links if _tgt(lk) not in flow_doc_ids)
    dangling_both = sum(
        1 for lk in links if _src(lk) not in flow_doc_ids and _tgt(lk) not in flow_doc_ids
    )

    print(f"  source 실재 못함(dangling src): {fmt_rate(dangling_src, len(links))}")
    print(f"  target 실재 못함(dangling tgt): {fmt_rate(dangling_tgt, len(links))}")
    print(f"  양쪽 dangling:                  {fmt_rate(dangling_both, len(links))}")

    # link_type 분포
    lt_counts: dict[str, int] = {}
    for lk in links:
        lt = lk.get("link_type", "unknown")
        lt_counts[lt] = lt_counts.get(lt, 0) + 1
    print(f"  link_type 분포: {lt_counts}")

    verdict = dangling_src == 0 and dangling_tgt == 0
    print(f"  → {'PASS' if verdict else 'FAIL'} (dangling {'없음' if verdict else '존재'})")


# ─── 종합 판정 ────────────────────────────────────────────────────────────────


def print_summary() -> None:
    print(f"\n{'=' * 60}")
    print("★ PHASE2 ML 학습 걸림 여부 종합 판정")
    print("=" * 60)


# ─── main ────────────────────────────────────────────────────────────────────


def main() -> None:
    normal_label = f"normal {NORMAL_DIR.name}"
    fraud_label = f"fraud {FRAUD_DIR.name}"
    print("=" * 60)
    print("문서흐름 체인 무결성 감사")
    print(f"Normal : {NORMAL_DIR.name}")
    print(f"Fraud  : {FRAUD_DIR.name}")
    print("=" * 60)

    # Normal 데이터셋
    check_p2p(FLOW_NORMAL, normal_label)
    check_o2c(FLOW_NORMAL, normal_label)
    check_journal_flow_link(NORMAL_DIR, normal_label)
    check_grir(NORMAL_DIR, normal_label)

    # Fraud 데이터셋
    check_p2p(FLOW_FRAUD, fraud_label)
    check_o2c(FLOW_FRAUD, fraud_label)
    check_journal_flow_link(FRAUD_DIR, fraud_label)
    check_grir(FRAUD_DIR, fraud_label)

    # Fraud-specific
    check_fraud_flow_membership()

    # cross_process_links (normal 기준)
    check_cross_process_links(NORMAL_DIR, normal_label)

    print_summary()


if __name__ == "__main__":
    main()
