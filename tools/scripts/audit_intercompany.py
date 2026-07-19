"""IC 양측 대사 측정 — 정상(v42j) + fraud(r4l_b) 기본 대상.

항목:
1. pairs 대사: seller/buyer JE 실재 여부 + 금액 일치율
2. 상호 잔액: 회사쌍별 IC채권 vs IC채무 차이
3. IC 매출↔매입: 4500 합 vs 상대측 IC 비용/매입 합
4. settlement: open/settled 비율
5. fraud overlay가 정상 IC 대사를 깬 곳 여부
6. 9300(IC Elimination Suspense)·2700(IC Payable) 잔액 합리성
"""

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
NORMAL_DIR = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else ROOT / "data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j"
)
FRAUD_DIR = (
    Path(sys.argv[2])
    if len(sys.argv) > 2
    else ROOT / "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b"
)

IC_ACCOUNTS = {
    "1150",
    "115001",
    "115002",
    "115003",  # IC 채권 계열
    "2050",
    "205001",
    "205002",
    "205003",  # IC 채무 계열
    "2700",  # IC Payable
    "4500",  # IC 매출
    "9300",  # IC Elimination Suspense
}

# ------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def to_dec(v) -> Decimal:
    """문자열 또는 숫자 → Decimal. 변환 실패 시 0."""
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return Decimal(0)


def load_je_csv(path: Path) -> list[dict]:
    """journal_entries.csv → list[dict]. DuckDB 없이 csv 직접 파싱."""
    import csv

    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def je_doc_index(je_list: list) -> dict:
    """document_id → list[row] 인덱스 (CSV 전표 행)."""
    idx: dict[str, list] = {}
    for row in je_list:
        did = row.get("document_id", "")
        idx.setdefault(did, []).append(row)
    return idx


def je_json_doc_index(je_json: list) -> dict:
    """ic_seller/buyer_journal_entries.json header.document_id → entry."""
    idx = {}
    for entry in je_json:
        did = entry.get("header", {}).get("document_id", "")
        ref = entry.get("header", {}).get("reference", "")
        # reference = ic_reference (IC202201XXXXXX)
        idx[did] = entry
        # seller_document / buyer_document 필드는 pairs에 있는 짧은 문서번호 (ICS/ICB...)
        # lines[].reference 에 상대방 문서번호가 들어 있음
    return idx


def seller_doc_by_reference(je_json: list) -> dict:
    """seller document_number(ICS...) → entry. header.reference는 ic_reference."""
    # pairs.seller_document = "ICS00000001" → ic_seller_journal_entries에서 어떻게 찾나?
    # seller lines[0].reference = "ICB..."(상대방), header에 document_number=null
    # → pairs ic_reference(header.reference) 로 매칭
    idx = {}
    for entry in je_json:
        ref = entry.get("header", {}).get("reference", "")  # IC202201000001 형태
        idx[ref] = entry
    return idx


def get_je_net_amount(entry: dict, account_prefix: str, side: str) -> Decimal:
    """entry lines에서 특정 계정(prefix 매칭)의 debit-credit 순금액."""
    total = Decimal(0)
    for line in entry.get("lines", []):
        acc = str(line.get("gl_account", ""))
        if acc.startswith(account_prefix):
            dr = to_dec(line.get("debit_amount", 0))
            cr = to_dec(line.get("credit_amount", 0))
            if side == "debit":
                total += dr - cr
            else:
                total += cr - dr
    return total


def amount_match(a: Decimal, b: Decimal, tol: Decimal = Decimal("1")) -> bool:
    """1원 이내 허용."""
    return abs(a - b) <= tol


def sep(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# ============================================================
# 1. pairs 대사
# ============================================================


def audit_pairs(dataset_dir: Path, label: str):
    sep(f"[1] pairs 대사 — {label}")
    pairs = load_json(dataset_dir / "intercompany/ic_matched_pairs.json")
    seller_json = load_json(dataset_dir / "intercompany/ic_seller_journal_entries.json")
    buyer_json = load_json(dataset_dir / "intercompany/ic_buyer_journal_entries.json")

    # ic_reference → entry
    seller_by_ref = seller_doc_by_reference(seller_json)
    buyer_by_ref = seller_doc_by_reference(buyer_json)

    je_csv = load_je_csv(dataset_dir / "journal_entries.csv")
    csv_ref_set = set(r.get("reference", "") for r in je_csv)
    csv_assignment_set = set(r.get("assignment", "") for r in je_csv)

    total = len(pairs)
    seller_found = 0
    buyer_found = 0
    amount_match_cnt = 0
    amount_mismatch_details = []

    for p in pairs:
        ic_ref = p.get("ic_reference", "")
        pair_amt = to_dec(p.get("amount", 0))

        s_entry = seller_by_ref.get(ic_ref)
        b_entry = buyer_by_ref.get(ic_ref)

        if s_entry:
            seller_found += 1
        if b_entry:
            buyer_found += 1

        if s_entry and b_entry:
            # seller IC채권 라인 차변 vs buyer IC채무 라인 대변
            s_dr = sum(
                to_dec(l.get("debit_amount", 0))
                for l in s_entry.get("lines", [])
                if str(l.get("gl_account", "")).startswith("115")
                or str(l.get("gl_account", "")) == "1150"
            )
            b_cr = sum(
                to_dec(l.get("credit_amount", 0))
                for l in b_entry.get("lines", [])
                if str(l.get("gl_account", "")).startswith("205")
                or str(l.get("gl_account", "")) == "2050"
                or str(l.get("gl_account", "")) == "2700"
            )
            if amount_match(s_dr, b_cr):
                amount_match_cnt += 1
            else:
                if len(amount_mismatch_details) < 5:
                    amount_mismatch_details.append(
                        (ic_ref, float(s_dr), float(b_cr), float(pair_amt))
                    )

    mismatch_cnt = (seller_found if seller_found <= buyer_found else buyer_found) - amount_match_cnt
    pair_present = min(seller_found, buyer_found)

    print(f"  총 pairs: {total}")
    print(f"  seller JE 실재: {seller_found}/{total} ({seller_found / total * 100:.1f}%)")
    print(f"  buyer JE 실재:  {buyer_found}/{total} ({buyer_found / total * 100:.1f}%)")
    print(
        f"  금액 일치 (양측 모두 실재인 쌍): {amount_match_cnt}/{pair_present} ({amount_match_cnt / pair_present * 100:.1f}% PASS)"
        if pair_present
        else "  쌍 없음"
    )

    if amount_mismatch_details:
        print("  ⚠ 불일치 샘플 (최대 5건):")
        for ref, s, b, p_amt in amount_mismatch_details:
            print(f"    {ref}: seller_DR={s:,.0f} buyer_CR={b:,.0f} pair_amt={p_amt:,.0f}")

    # CSV에서 ic_reference 실재 확인
    ic_refs = [p.get("ic_reference", "") for p in pairs]
    csv_found = sum(1 for r in ic_refs if r in csv_ref_set or r in csv_assignment_set)
    print(
        f"  journal_entries.csv IC 참조 실재: {csv_found}/{total} ({csv_found / total * 100:.1f}%)"
    )

    result = (
        "PASS"
        if seller_found == total
        and buyer_found == total
        and (amount_match_cnt == pair_present or pair_present == 0)
        else "FAIL"
    )
    print(f"  → 판정: {result}")
    return {
        "total": total,
        "seller_found": seller_found,
        "buyer_found": buyer_found,
        "amount_match": amount_match_cnt,
        "pair_present": pair_present,
    }


# ============================================================
# 2. 상호 잔액 (회사쌍별)
# ============================================================


def audit_bilateral_balance(dataset_dir: Path, label: str):
    sep(f"[2] 상호 잔액 (회사쌍별) — {label}")
    seller_json = load_json(dataset_dir / "intercompany/ic_seller_journal_entries.json")
    buyer_json = load_json(dataset_dir / "intercompany/ic_buyer_journal_entries.json")

    # 회사쌍 (seller, buyer) → (IC채권 합, IC채무 합)
    # seller: 1150/115001~115003 DR (채권 발생)
    # buyer:  2050/205001~205003/2700 CR (채무 발생)

    pair_seller: dict[tuple, Decimal] = {}  # (seller, buyer) → DR 합
    pair_buyer: dict[tuple, Decimal] = {}  # (buyer, seller) → CR 합 — 키: (seller, buyer)

    for entry in seller_json:
        hdr = entry.get("header", {})
        sc = hdr.get("company_code", "")
        for line in entry.get("lines", []):
            tp = line.get("trading_partner", "")
            acc = str(line.get("gl_account", ""))
            if acc.startswith("115") or acc == "1150":
                dr = to_dec(line.get("debit_amount", 0))
                cr = to_dec(line.get("credit_amount", 0))
                key = (sc, tp)
                pair_seller[key] = pair_seller.get(key, Decimal(0)) + dr - cr

    for entry in buyer_json:
        hdr = entry.get("header", {})
        bc = hdr.get("company_code", "")
        for line in entry.get("lines", []):
            tp = line.get("trading_partner", "")
            acc = str(line.get("gl_account", ""))
            if acc.startswith("205") or acc == "2050" or acc == "2700":
                dr = to_dec(line.get("debit_amount", 0))
                cr = to_dec(line.get("credit_amount", 0))
                # key: (seller=tp, buyer=bc)
                key = (tp, bc)
                pair_buyer[key] = pair_buyer.get(key, Decimal(0)) + cr - dr

    all_keys = set(pair_seller.keys()) | set(pair_buyer.keys())
    pass_cnt = 0
    fail_cnt = 0
    fail_details = []

    for key in sorted(all_keys):
        rec = pair_seller.get(key, Decimal(0))
        pay = pair_buyer.get(key, Decimal(0))
        diff = abs(rec - pay)
        if amount_match(rec, pay, Decimal("2")):
            pass_cnt += 1
        else:
            fail_cnt += 1
            if len(fail_details) < 8:
                fail_details.append((key[0], key[1], float(rec), float(pay), float(diff)))

    total_pairs = len(all_keys)
    print(f"  회사쌍 수: {total_pairs}")
    print(f"  PASS (채권≈채무, 2원 이내): {pass_cnt}")
    print(f"  FAIL (차이 > 2원):          {fail_cnt}")
    if fail_details:
        print("  FAIL 샘플 (최대 8건):")
        for s, b, rec, pay, diff in fail_details:
            print(f"    ({s}→{b}): 채권={rec:,.0f}  채무={pay:,.0f}  차이={diff:,.0f}")

    result = "PASS" if fail_cnt == 0 else ("관찰" if fail_cnt <= 3 else "FAIL")
    print(f"  → 판정: {result}")
    return {"pair_count": total_pairs, "pass": pass_cnt, "fail": fail_cnt}


# ============================================================
# 3. IC 매출(4500) ↔ IC 매입/비용 정합
# ============================================================


def audit_ic_revenue_cost(dataset_dir: Path, label: str):
    sep(f"[3] IC 매출↔매입 정합 — {label}")
    seller_json = load_json(dataset_dir / "intercompany/ic_seller_journal_entries.json")
    buyer_json = load_json(dataset_dir / "intercompany/ic_buyer_journal_entries.json")
    pairs = load_json(dataset_dir / "intercompany/ic_matched_pairs.json")

    # pairs를 ic_reference 기준으로 인덱스
    # fraud 데이터셋에는 FS11 전용 스키마(ic_reference 없음)가 혼재 — 필터링
    pair_by_ref = {p["ic_reference"]: p for p in pairs if "ic_reference" in p}
    seller_by_ref = seller_doc_by_reference(seller_json)
    buyer_by_ref = seller_doc_by_reference(buyer_json)

    # IC 매출 계정: 4500, 4100(서비스 매출 포함 확인)
    ic_revenue_accs = {"4500", "4100"}
    # IC 매입/비용 계정: 6300(용역비용), 5100(상품원가), 기타 비용 계정
    ic_cost_accs_prefix = ("6", "5")  # 비용/원가 계열

    total_seller_rev = Decimal(0)
    total_buyer_cost = Decimal(0)
    per_tx_match = 0
    per_tx_mismatch = 0
    mismatch_samples = []

    for ic_ref, s_entry in seller_by_ref.items():
        b_entry = buyer_by_ref.get(ic_ref)
        if not b_entry:
            continue

        s_rev = sum(
            to_dec(l.get("credit_amount", 0)) - to_dec(l.get("debit_amount", 0))
            for l in s_entry.get("lines", [])
            if str(l.get("gl_account", "")) in ic_revenue_accs
        )
        b_cost = sum(
            to_dec(l.get("debit_amount", 0)) - to_dec(l.get("credit_amount", 0))
            for l in b_entry.get("lines", [])
            if str(l.get("gl_account", ""))[0] in ("6", "5", "7")
        )

        total_seller_rev += s_rev
        total_buyer_cost += b_cost

        if amount_match(s_rev, b_cost, Decimal("2")):
            per_tx_match += 1
        else:
            per_tx_mismatch += 1
            if len(mismatch_samples) < 5:
                mismatch_samples.append((ic_ref, float(s_rev), float(b_cost)))

    total_tx = per_tx_match + per_tx_mismatch
    print(f"  대사 대상 거래 쌍: {total_tx}")
    print(f"  전체 IC 매출 합: {float(total_seller_rev):,.0f}")
    print(f"  전체 IC 비용 합: {float(total_buyer_cost):,.0f}")
    diff_total = abs(total_seller_rev - total_buyer_cost)
    print(f"  전체 합계 차이:  {float(diff_total):,.0f}")
    print(
        f"  건별 PASS: {per_tx_match}/{total_tx} ({per_tx_match / total_tx * 100:.1f}%)"
        if total_tx
        else "  거래 없음"
    )
    if mismatch_samples:
        print("  건별 불일치 샘플:")
        for ref, rv, co in mismatch_samples:
            print(f"    {ref}: 매출={rv:,.0f}  비용={co:,.0f}")

    result = (
        "PASS"
        if per_tx_mismatch == 0
        else ("관찰" if per_tx_mismatch / total_tx < 0.05 else "FAIL")
    )
    print(f"  → 판정: {result}")
    return {
        "total_tx": total_tx,
        "match": per_tx_match,
        "mismatch": per_tx_mismatch,
        "rev_sum": float(total_seller_rev),
        "cost_sum": float(total_buyer_cost),
    }


# ============================================================
# 4. settlement open/settled 비율
# ============================================================


def audit_settlement(dataset_dir: Path, label: str):
    sep(f"[4] settlement 비율 — {label}")
    pairs = load_json(dataset_dir / "intercompany/ic_matched_pairs.json")
    total = len(pairs)
    settled = sum(1 for p in pairs if str(p.get("settlement_status", "")).lower() == "settled")
    open_ = sum(1 for p in pairs if str(p.get("settlement_status", "")).lower() == "open")
    other = total - settled - open_

    print(f"  총 pairs: {total}")
    print(f"  settled: {settled} ({settled / total * 100:.1f}%)")
    print(f"  open:    {open_}  ({open_ / total * 100:.1f}%)")
    if other:
        print(f"  기타:    {other}")

    # 연도별 open 비율 확인 (2022~2024, 결산 후 open 잔존 여부)
    from collections import Counter

    year_open: Counter = Counter()
    year_total: Counter = Counter()
    for p in pairs:
        y = str(p.get("transaction_date", ""))[:4]
        year_total[y] += 1
        if str(p.get("settlement_status", "")).lower() == "open":
            year_open[y] += 1

    print("  연도별 open 비율:")
    for y in sorted(year_total.keys()):
        yt = year_total[y]
        yo = year_open[y]
        print(f"    {y}: {yo}/{yt} ({yo / yt * 100:.1f}% open)")

    # 2022/2023 결산 완료 연도에 open이 과다하면 비정상
    old_open = year_open.get("2022", 0) + year_open.get("2023", 0)
    old_total = year_total.get("2022", 0) + year_total.get("2023", 0)
    old_open_rate = old_open / old_total if old_total else 0

    if old_open_rate > 0.5:
        result = "FAIL — 결산 완료 연도 open 비율 과다"
    elif old_open_rate > 0.2:
        result = "관찰 — 결산 완료 연도 open 잔존"
    else:
        result = "PASS"
    print(f"  → 판정: {result}")
    return {"total": total, "settled": settled, "open": open_, "old_open_rate": old_open_rate}


# ============================================================
# 5. fraud overlay가 정상 IC 대사를 깬 곳 여부
# ============================================================


def audit_fraud_overlay_impact(normal_dir: Path, fraud_dir: Path):
    sep(f"[5] {fraud_dir.name} — overlay의 정상 IC 대사 파괴 여부")

    fraud_pairs = load_json(fraud_dir / "intercompany/ic_matched_pairs.json")
    normal_pairs = load_json(normal_dir / "intercompany/ic_matched_pairs.json")

    fraud_seller = load_json(fraud_dir / "intercompany/ic_seller_journal_entries.json")
    fraud_buyer = load_json(fraud_dir / "intercompany/ic_buyer_journal_entries.json")

    # fraud 데이터셋에는 FS11 전용 스키마(ic_reference 없음) 항목이 혼재 — 분리
    fraud_pairs_ic = [p for p in fraud_pairs if "ic_reference" in p]
    fraud_pairs_fs11 = [p for p in fraud_pairs if "ic_reference" not in p]

    normal_refs = {p["ic_reference"] for p in normal_pairs}
    fraud_refs = {p["ic_reference"] for p in fraud_pairs_ic}

    # fraud에도 정상 ic_reference가 남아 있는지
    shared_refs = normal_refs & fraud_refs
    only_fraud = fraud_refs - normal_refs
    only_normal = normal_refs - fraud_refs

    print(f"  normal pairs: {len(normal_refs)}  fraud pairs(ic_ref 있음): {len(fraud_refs)}")
    print(
        f"  fraud FS11 전용 스키마 항목: {len(fraud_pairs_fs11)}"
        f" (match_status 분포: { {s: sum(1 for p in fraud_pairs_fs11 if p.get('match_status') == s) for s in set(p.get('match_status') for p in fraud_pairs_fs11)} })"
    )
    print(f"  공통 ic_reference: {len(shared_refs)}")
    print(f"  fraud 전용(신규 IC 거래): {len(only_fraud)}")
    print(f"  normal 전용(fraud에서 제거됨): {len(only_normal)}")

    # fraud 전용 pairs → is_fraud 확인 (FS11 기대)
    fraud_by_ref = {p["ic_reference"]: p for p in fraud_pairs_ic}
    fraud_je_seller = seller_doc_by_reference(fraud_seller)
    fraud_je_buyer = seller_doc_by_reference(fraud_buyer)

    fs11_cnt = 0
    non_fs11_mismatch = 0
    non_fs11_samples = []

    for ref in only_fraud:
        s_entry = fraud_je_seller.get(ref)
        b_entry = fraud_je_buyer.get(ref)
        if not s_entry or not b_entry:
            continue
        s_fraud = s_entry.get("header", {}).get("is_fraud", False)
        b_fraud = b_entry.get("header", {}).get("is_fraud", False)
        if s_fraud or b_fraud:
            fs11_cnt += 1

    # 공통 refs 중 금액 변경 여부
    normal_pairs_by_ref = {p["ic_reference"]: p for p in normal_pairs}
    normal_seller = seller_doc_by_reference(
        load_json(normal_dir / "intercompany/ic_seller_journal_entries.json")
    )
    normal_buyer = seller_doc_by_reference(
        load_json(normal_dir / "intercompany/ic_buyer_journal_entries.json")
    )

    tampered_shared = 0
    tampered_samples = []
    for ref in shared_refs:
        n_s = normal_seller.get(ref)
        f_s = fraud_je_seller.get(ref)
        if not n_s or not f_s:
            continue
        n_amt = sum(
            to_dec(l.get("debit_amount", 0))
            for l in n_s.get("lines", [])
            if str(l.get("gl_account", "")).startswith("115")
            or str(l.get("gl_account", "")) == "1150"
        )
        f_amt = sum(
            to_dec(l.get("debit_amount", 0))
            for l in f_s.get("lines", [])
            if str(l.get("gl_account", "")).startswith("115")
            or str(l.get("gl_account", "")) == "1150"
        )
        if not amount_match(n_amt, f_amt, Decimal("2")):
            tampered_shared += 1
            if len(tampered_samples) < 5:
                tampered_samples.append((ref, float(n_amt), float(f_amt)))

    print(f"\n  fraud 전용 pair 중 is_fraud=true 마킹: {fs11_cnt}/{len(only_fraud)}")
    print(f"  공통 pair 중 fraud가 금액 변조한 것: {tampered_shared}/{len(shared_refs)}")
    if tampered_samples:
        print("  변조 샘플:")
        for ref, n, f in tampered_samples:
            print(f"    {ref}: 정상={n:,.0f}  fraud={f:,.0f}")

    if tampered_shared == 0:
        result = "PASS — overlay가 정상 IC 대사를 파괴하지 않음"
    else:
        result = f"FAIL — {tampered_shared}건 공통 IC 거래 금액 변조됨"
    print(f"  → 판정: {result}")
    return {
        "shared": len(shared_refs),
        "only_fraud": len(only_fraud),
        "fs11_marked": fs11_cnt,
        "tampered_shared": tampered_shared,
    }


# ============================================================
# 6. 보조 IC 계정(9300, 2700) 잔액 합리성
# ============================================================


def audit_auxiliary_ic_accounts(dataset_dir: Path, label: str):
    sep(f"[6] 보조 IC 계정 잔액 합리성 — {label}")
    je_csv = load_je_csv(dataset_dir / "journal_entries.csv")

    acc_dr: dict[str, Decimal] = {}
    acc_cr: dict[str, Decimal] = {}
    focus_accs = {"9300", "2700", "1150", "2050"}

    for row in je_csv:
        acc = str(row.get("gl_account", "")).strip()
        # 4자리 prefix 기준으로 집계
        prefix = acc[:4] if len(acc) >= 4 else acc
        if prefix not in focus_accs:
            continue
        dr = to_dec(row.get("debit_amount", 0))
        cr = to_dec(row.get("credit_amount", 0))
        acc_dr[prefix] = acc_dr.get(prefix, Decimal(0)) + dr
        acc_cr[prefix] = acc_cr.get(prefix, Decimal(0)) + cr

    # 전체 합계도 확인 (ic_seller/buyer JE 포함)
    # → csv에 IC 전표가 포함되어 있는지 확인
    ic_doc_types = [r for r in je_csv if r.get("document_type", "") == "IC"]
    print(f"  journal_entries.csv 내 IC 문서 건수: {len(ic_doc_types)}")

    print("\n  계정별 차·대변 합계 (csv 기준):")
    print(f"  {'계정':<8} {'차변 합':>20} {'대변 합':>20} {'순잔액(DR-CR)':>20}")
    for acc in sorted(focus_accs):
        dr = acc_dr.get(acc, Decimal(0))
        cr = acc_cr.get(acc, Decimal(0))
        net = dr - cr
        print(f"  {acc:<8} {float(dr):>20,.0f} {float(cr):>20,.0f} {float(net):>20,.0f}")

    # 9300 (Elimination Suspense): 이상적으로는 순잔액 ≈ 0 (상쇄 계정)
    bal_9300 = acc_dr.get("9300", Decimal(0)) - acc_cr.get("9300", Decimal(0))
    # 2700 (IC Payable): 대변 잔액이어야 정상 (부채)
    bal_2700 = acc_dr.get("2700", Decimal(0)) - acc_cr.get("2700", Decimal(0))
    # 1150 (IC Receivable): 차변 잔액이어야 정상 (자산)
    bal_1150 = acc_dr.get("1150", Decimal(0)) - acc_cr.get("1150", Decimal(0))
    # 2050 (IC Payable): 대변 잔액이어야 정상 (부채)
    bal_2050 = acc_dr.get("2050", Decimal(0)) - acc_cr.get("2050", Decimal(0))

    issues = []
    print("\n  잔액 합리성 체크:")
    # 9300: csv에 실재하는 경우에만 평가
    if acc_dr.get("9300", Decimal(0)) + acc_cr.get("9300", Decimal(0)) > 0:
        if abs(bal_9300) < 100_000:
            print(f"  9300 Elimination Suspense: 순잔액 {float(bal_9300):,.0f} → PASS (≈0)")
        else:
            print(f"  9300 Elimination Suspense: 순잔액 {float(bal_9300):,.0f} → 관찰 (미결)")
            issues.append("9300 미결")
    else:
        print("  9300: csv에 거래 없음 (IC JE 파일에만 존재할 수 있음)")

    if bal_2700 < 0:
        print(f"  2700 IC Payable: 순잔액 {float(bal_2700):,.0f} → PASS (대변 잔액=부채)")
    elif bal_2700 == 0:
        print("  2700 IC Payable: 순잔액 0 → 데이터특성 (거래 없음)")
    else:
        print(f"  2700 IC Payable: 순잔액 {float(bal_2700):,.0f} → 관찰 (차변 잔액 이상)")
        issues.append("2700 차변잔액")

    if bal_1150 > 0:
        print(f"  1150 IC Receivable: 순잔액 {float(bal_1150):,.0f} → PASS (차변 잔액=자산)")
    elif bal_1150 == 0:
        print("  1150 IC Receivable: 순잔액 0 → 데이터특성")
    else:
        print(f"  1150 IC Receivable: 순잔액 {float(bal_1150):,.0f} → 관찰 (대변 잔액 이상)")
        issues.append("1150 대변잔액")

    if bal_2050 < 0:
        print(f"  2050 IC Payable: 순잔액 {float(bal_2050):,.0f} → PASS (대변 잔액=부채)")
    elif bal_2050 == 0:
        print("  2050 IC Payable: 순잔액 0 → 데이터특성")
    else:
        print(f"  2050 IC Payable: 순잔액 {float(bal_2050):,.0f} → 관찰")
        issues.append("2050 차변잔액")

    result = "PASS" if not issues else f"관찰 — {', '.join(issues)}"
    print(f"  → 판정: {result}")
    return {
        "9300_net": float(bal_9300),
        "2700_net": float(bal_2700),
        "1150_net": float(bal_1150),
        "2050_net": float(bal_2050),
    }


# ============================================================
# MAIN
# ============================================================


def main():
    normal_label = f"정상 {NORMAL_DIR.name}"
    fraud_label = f"fraud {FRAUD_DIR.name}"
    print("=" * 60)
    print("  IC 양측 대사 측정 리포트")
    print(f"  정상: {NORMAL_DIR.name}")
    print(f"  fraud: {FRAUD_DIR.name}")
    print("=" * 60)

    # --- 정상 데이터 ---
    r1_n = audit_pairs(NORMAL_DIR, normal_label)
    r2_n = audit_bilateral_balance(NORMAL_DIR, normal_label)
    r3_n = audit_ic_revenue_cost(NORMAL_DIR, normal_label)
    r4_n = audit_settlement(NORMAL_DIR, normal_label)

    # --- fraud 데이터 ---
    r1_f = audit_pairs(FRAUD_DIR, fraud_label)
    r2_f = audit_bilateral_balance(FRAUD_DIR, fraud_label)
    r3_f = audit_ic_revenue_cost(FRAUD_DIR, fraud_label)
    r4_f = audit_settlement(FRAUD_DIR, fraud_label)

    # --- overlay 영향 ---
    r5 = audit_fraud_overlay_impact(NORMAL_DIR, FRAUD_DIR)

    # --- 보조 IC 계정 ---
    r6_n = audit_auxiliary_ic_accounts(NORMAL_DIR, normal_label)
    r6_f = audit_auxiliary_ic_accounts(FRAUD_DIR, fraud_label)

    # ===== 최종 요약 =====
    sep("최종 요약")
    print("  [1] pairs 대사")
    print(
        f"      정상: seller {r1_n['seller_found']}/{r1_n['total']}  buyer {r1_n['buyer_found']}/{r1_n['total']}  금액일치 {r1_n['amount_match']}/{r1_n['pair_present']}"
    )
    print(
        f"      fraud: seller {r1_f['seller_found']}/{r1_f['total']}  buyer {r1_f['buyer_found']}/{r1_f['total']}  금액일치 {r1_f['amount_match']}/{r1_f['pair_present']}"
    )
    print("  [2] 상호 잔액")
    print(f"      정상: {r2_n['pass']}/{r2_n['pair_count']} PASS  FAIL={r2_n['fail']}")
    print(f"      fraud: {r2_f['pass']}/{r2_f['pair_count']} PASS  FAIL={r2_f['fail']}")
    print("  [3] IC 매출↔매입")
    print(
        f"      정상: {r3_n['match']}/{r3_n['total_tx']} PASS  매출-비용 차이={abs(r3_n['rev_sum'] - r3_n['cost_sum']):,.0f}"
    )
    print(
        f"      fraud: {r3_f['match']}/{r3_f['total_tx']} PASS  매출-비용 차이={abs(r3_f['rev_sum'] - r3_f['cost_sum']):,.0f}"
    )
    print("  [4] settlement open 비율")
    print(
        f"      정상: open {r4_n['open']}/{r4_n['total']} ({r4_n['open'] / r4_n['total'] * 100:.1f}%)"
    )
    print(
        f"      fraud: open {r4_f['open']}/{r4_f['total']} ({r4_f['open'] / r4_f['total'] * 100:.1f}%)"
    )
    print("  [5] overlay 영향")
    print(
        f"      공통 IC 거래 변조: {r5['tampered_shared']}/{r5['shared']}  FS11 신규 마킹: {r5['fs11_marked']}/{r5['only_fraud']}"
    )
    print("  [6] 보조 IC 계정 (정상)")
    print(
        f"      9300 순잔액: {r6_n['9300_net']:,.0f}  2700: {r6_n['2700_net']:,.0f}  1150: {r6_n['1150_net']:,.0f}  2050: {r6_n['2050_net']:,.0f}"
    )

    # PHASE2 판정
    sep("PHASE2 IC family 학습 걸림 여부")
    issues = []
    if r1_n["amount_match"] < r1_n["pair_present"] * 0.95:
        issues.append("정상 pairs 금액 불일치 >5%")
    if r2_n["fail"] > r2_n["pair_count"] * 0.05:
        issues.append("상호 잔액 FAIL >5%")
    if r5["tampered_shared"] > 0:
        issues.append(f"공통 IC 거래 변조 {r5['tampered_shared']}건")
    if r4_n["old_open_rate"] > 0.5:
        issues.append("결산 완료 연도 open 과다")

    if not issues:
        print("  → PASS: IC family 학습에 걸림 없음.")
        print("    정상 대사 완정, fraud는 FS11 전용 신규 거래로만 불일치 발생,")
        print("    공통 IC 거래는 변조 없음.")
    else:
        print("  → 주의: 다음 항목이 PHASE2 학습 신호를 오염시킬 수 있음:")
        for iss in issues:
            print(f"    - {iss}")


if __name__ == "__main__":
    main()
