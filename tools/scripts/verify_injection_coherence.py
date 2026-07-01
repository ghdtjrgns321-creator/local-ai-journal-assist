"""정합 오라클 2·3층 (T4) — 주입 부정 전표의 구조 정합 검사.

원칙(DESIGN ⑦): 부정은 substance(실질)만 조작하고 structure(구조)는 지킨다.
구조 불변식(HARD)이 깨지면 = 의도된 부정이 아니라 생성 사고(accident) = 재생성 대상.
declared_violations(의미 truth)는 채점(T7)이 쓰고, 이 오라클은 구조만 본다.

사용:
  python verify_injection_coherence.py <dataset_dir>      # fraud 문서 검사, 사고 0이면 exit 0
  python verify_injection_coherence.py --self-test        # 오라클 비-hollow 자가검증
spec: dev/active/integrated-usefulness-benchmark/COHERENCE_ORACLE_SPEC.md
"""

import csv
import json
import os
import sys
from collections import defaultdict


def _f(x):
    """금액 파싱 — 빈값은 0, round2(회계 float 오차 방어)."""
    x = (x or "").strip()
    if x == "":
        return 0.0
    return round(float(x), 2)


def _date(x):
    """'YYYY-MM-DD[ HH:MM:SS]' → 'YYYY-MM-DD' (날짜부만 비교). 빈값 None."""
    x = (x or "").strip()
    if x == "":
        return None
    return x[:10]


# ---- 불변식 (순수 함수: rows/context → 위반 리스트) ----
# rows = 한 document_id의 라인 리스트. ctx = {doc_ids:set, open_refs:set}


def inv_bal(doc_id, rows, ctx):
    """INV-BAL(1층): 문서 차대균형."""
    d = round(sum(_f(r["debit_amount"]) for r in rows), 2)
    c = round(sum(_f(r["credit_amount"]) for r in rows), 2)
    return [] if abs(d - c) < 0.005 else [f"INV-BAL {doc_id}: Σdebit={d} != Σcredit={c}"]


def inv_pos(doc_id, rows, ctx):
    """INV-POS(1층): 음수 금지 + 라인당 debit/credit XOR."""
    v = []
    for r in rows:
        d, c = _f(r["debit_amount"]), _f(r["credit_amount"])
        if d < 0 or c < 0:
            v.append(f"INV-POS {doc_id} L{r.get('line_number')}: 음수 금액 d={d} c={c}")
        if d > 0 and c > 0:
            v.append(f"INV-POS {doc_id} L{r.get('line_number')}: debit·credit 동시 >0")
    return v


def inv_ref(doc_id, rows, ctx):
    """INV-REV/ORIG(2층): 역분개·원전표 참조가 실존 document_id인지."""
    v = []
    for r in rows:
        for col, tag in (("reversal_document_id", "INV-REV"), ("original_document_id", "INV-ORIG")):
            ref = (r.get(col) or "").strip()
            if ref and ref not in ctx["doc_ids"]:
                v.append(f"{tag} {doc_id}: {col}={ref} 참조 대상 부재")
    return v


def inv_temporal(doc_id, rows, ctx):
    """INV-TEMPORAL(3층): approval≥document, settlement≥posting."""
    v = []
    for r in rows:
        ad, dd = _date(r.get("approval_date")), _date(r.get("document_date"))
        if ad and dd and ad < dd:
            v.append(f"INV-TEMPORAL {doc_id}: approval {ad} < document {dd}")
        sd, pd = _date(r.get("settlement_date")), _date(r.get("posting_date"))
        if sd and pd and sd < pd:
            v.append(f"INV-TEMPORAL {doc_id}: settlement {sd} < posting {pd}")
    return v


def inv_clear(doc_id, rows, ctx):
    """INV-CLEAR(3층): is_cleared/settlement_status 와 amount_open 자기정합."""
    v = []
    for r in rows:
        cleared = (r.get("is_cleared") or "").strip().lower() == "true" or (
            r.get("settlement_status") or ""
        ).strip().lower() == "cleared"
        if cleared and _f(r.get("amount_open")) > 0:
            v.append(
                f"INV-CLEAR {doc_id} L{r.get('line_number')}: cleared인데 amount_open={_f(r.get('amount_open'))}>0"
            )
    return v


def inv_ar_exists(doc_id, rows, ctx):
    """INV-AR-EXISTS(3층): '없는 AR 갚기' 금지. clearing 라인이 참조하는 AR/포지션이
    base의 열린 포지션 집합(open_refs)에 있어야 한다."""
    v = []
    for r in rows:
        cleared = (r.get("is_cleared") or "").strip().lower() == "true" or (
            r.get("settlement_status") or ""
        ).strip().lower() == "cleared"
        if not cleared:
            continue
        # 실제 대사 링크 키만: lettrage/auxiliary_account_number. reference는 일반 참조라 제외(오탐).
        key = (r.get("lettrage") or r.get("auxiliary_account_number") or "").strip()
        if key and key not in ctx["open_refs"]:
            v.append(
                f"INV-AR-EXISTS {doc_id} L{r.get('line_number')}: 없는/미열린 AR 참조 key={key}"
            )
    return v


CHECKS = [inv_bal, inv_pos, inv_ref, inv_temporal, inv_clear, inv_ar_exists]


def run_checks(fraud_docs, ctx):
    """fraud_docs: {doc_id: [rows]} → 층별 사고 리스트."""
    acc = defaultdict(list)
    for doc_id, rows in fraud_docs.items():
        for chk in CHECKS:
            for msg in chk(doc_id, rows, ctx):
                acc[msg.split()[0]].append(msg)
    return acc


def load_dataset(dpath):
    truth = os.path.join(dpath, "labels")
    tfile = next(
        (os.path.join(truth, f) for f in os.listdir(truth) if f.endswith("_truth.csv")), None
    )
    if tfile is None:
        raise FileNotFoundError(f"truth sidecar(*_truth.csv) 없음: {truth}")
    fraud_ids = set()
    for r in csv.DictReader(open(tfile, encoding="utf-8")):
        fraud_ids.update(json.loads(r["member_document_ids"]))
    # journal 1-pass: 전체 doc_id + fraud 문서 라인 + open_refs(정상 라인의 실재 참조 키공간)
    all_ids, fraud_docs, open_refs = set(), defaultdict(list), set()
    for row in csv.DictReader(open(os.path.join(dpath, "journal_entries.csv"), encoding="utf-8")):
        all_ids.add(row["document_id"])
        if row["document_id"] in fraud_ids:
            fraud_docs[row["document_id"]].append(row)
        else:
            # 정상 라인의 실제 대사 링크 키(lettrage/aux) = 실재 열린 포지션 키공간
            for k in ("lettrage", "auxiliary_account_number"):
                val = (row.get(k) or "").strip()
                if val:
                    open_refs.add(val)
    return fraud_ids, fraud_docs, {"doc_ids": all_ids, "open_refs": open_refs}


def main(dpath):
    fraud_ids, fraud_docs, ctx = load_dataset(dpath)
    acc = run_checks(fraud_docs, ctx)
    total = sum(len(v) for v in acc.values())
    print(f"[정합 오라클] dataset={os.path.basename(dpath)}")
    print(f"  fraud 문서 {len(fraud_docs)} / truth fraud_id {len(fraud_ids)}")
    for inv in [
        "INV-BAL",
        "INV-POS",
        "INV-REV",
        "INV-ORIG",
        "INV-TEMPORAL",
        "INV-CLEAR",
        "INV-AR-EXISTS",
    ]:
        print(f"  {inv:14} 사고 {len(acc.get(inv, []))}")
    print(f"  === 총 사고(spec 밖) = {total} ===")
    for msgs in acc.values():
        for m in msgs[:5]:
            print("   ·", m)
    return 0 if total == 0 else 1


def self_test():
    """비-hollow 검증: 각 불변식을 깨는 인위 문서 → FLAG, 정상 문서 → PASS."""
    ctx = {"doc_ids": {"D1", "D2"}, "open_refs": {"AR-100"}}
    clean = [
        {
            "line_number": "1",
            "debit_amount": "100",
            "credit_amount": "0",
            "gl_account": "1100",
            "document_date": "2022-01-01",
            "approval_date": "2022-01-02",
            "posting_date": "2022-01-01",
            "settlement_date": "",
            "is_cleared": "",
            "amount_open": "",
            "settlement_status": "",
            "reversal_document_id": "",
            "original_document_id": "",
            "lettrage": "",
            "auxiliary_account_number": "",
            "reference": "",
        },
        {
            "line_number": "2",
            "debit_amount": "0",
            "credit_amount": "100",
            "gl_account": "4000",
            "document_date": "2022-01-01",
            "approval_date": "2022-01-02",
            "posting_date": "2022-01-01",
            "settlement_date": "",
            "is_cleared": "",
            "amount_open": "",
            "settlement_status": "",
            "reversal_document_id": "",
            "original_document_id": "",
            "lettrage": "",
            "auxiliary_account_number": "",
            "reference": "",
        },
    ]
    # (rows, target_inv). target=None → clean(총 0). 나머지 → 해당 INV가 발화해야(부수 발화 허용).
    # 각 결함 픽스처는 차대균형 유지(INV-BAL 부수발화 배제)해 타깃만 격리.
    cases = {
        "clean": (clean, None),
        "INV-BAL": (
            [dict(clean[0], debit_amount="100"), dict(clean[1], credit_amount="90")],
            "INV-BAL",
        ),
        "INV-POS": (
            [
                dict(clean[0], debit_amount="-100", credit_amount="0"),
                dict(clean[1], debit_amount="-100", credit_amount="0"),
            ],
            "INV-POS",
        ),
        "INV-REV": ([dict(clean[0], reversal_document_id="GHOST"), clean[1]], "INV-REV"),
        "INV-TEMPORAL": ([dict(clean[0], approval_date="2021-12-31"), clean[1]], "INV-TEMPORAL"),
        "INV-CLEAR": ([dict(clean[0], is_cleared="true", amount_open="50"), clean[1]], "INV-CLEAR"),
        "INV-AR-EXISTS": (
            [dict(clean[0], is_cleared="true", amount_open="0", lettrage="AR-999"), clean[1]],
            "INV-AR-EXISTS",
        ),
    }
    ok = True
    for name, (rows, target) in cases.items():
        acc = run_checks({"T": rows}, ctx)
        total = sum(len(v) for v in acc.values())
        if target is None:
            good = total == 0
            detail = f"총 {total}(기대 0)"
        else:
            good = len(acc.get(target, [])) >= 1
            detail = f"{target} 발화 {len(acc.get(target, []))}(기대 ≥1)"
        ok = ok and good
        print(f"  self-test {name:16} {detail}  [{'OK' if good else 'FAIL'}]")
    print("=== self-test", "PASS" if ok else "FAIL", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        sys.exit(self_test())
    if len(sys.argv) < 2:
        print("usage: verify_injection_coherence.py <dataset_dir> | --self-test")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
