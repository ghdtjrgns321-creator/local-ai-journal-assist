"""V4 candidate 분개 샘플 추출 — 회계 논리 LLM 검증용."""

from __future__ import annotations

import json
import random
from pathlib import Path

import duckdb

ROOT = Path("data/journal/primary/datasynth_manipulation_v4_candidate")
OUT = Path("dev/active/v4_sample_dump.txt")

random.seed(20260516)
con = duckdb.connect(":memory:")
con.execute(
    f"CREATE VIEW je AS SELECT * FROM read_csv_auto('{ROOT.as_posix()}/journal_entries.csv', sample_size=-1)"
)
con.execute(
    f"CREATE VIEW truth AS SELECT * FROM read_csv_auto('{ROOT.as_posix()}/labels/manipulated_entry_truth.csv', sample_size=-1)"
)

with open(ROOT / "chart_of_accounts.json", encoding="utf-8") as f:
    coa_raw = json.load(f)
coa = {str(a["account_number"]): a for a in coa_raw["accounts"]}


def acct_meta(code: str):
    a = coa.get(str(code))
    if not a:
        return ("?", "?", None)
    return (a.get("account_type", "?"), a.get("sub_type", "?"), a.get("normal_debit_balance"))


# Normal sample (7) — 부문별 다양성 확보 위해 source 별로 흩어 뽑음
all_normal = [
    r[0]
    for r in con.execute(
        """
        SELECT DISTINCT j.document_id
        FROM je j LEFT JOIN truth t USING (document_id)
        WHERE t.document_id IS NULL
        """
    ).fetchall()
]
random.shuffle(all_normal)
normal_ids = all_normal[:7]

# Manipulated — 시나리오별 1건
scenarios = [
    r[0]
    for r in con.execute("SELECT DISTINCT manipulation_scenario FROM truth ORDER BY 1").fetchall()
]
manip_pick = []
for s in scenarios:
    docs = [
        r[0]
        for r in con.execute(
            "SELECT document_id FROM truth WHERE manipulation_scenario = ?", [s]
        ).fetchall()
    ]
    random.shuffle(docs)
    manip_pick.append((s, docs[0]))

all_docs = [(None, d) for d in normal_ids] + manip_pick

lines_out: list[str] = []


def w(s: str = ""):
    lines_out.append(s)


for scen, did in all_docs:
    hdr = con.execute(
        """
        SELECT DISTINCT document_id, company_code, fiscal_year, fiscal_period, posting_date,
                        document_type, currency, reference, header_text, created_by, user_persona,
                        source, business_process, semantic_scenario_id, counterparty_type,
                        approved_by, approval_date, sod_violation
        FROM je WHERE document_id = ?
        """,
        [did],
    ).fetchone()
    rows = con.execute(
        """
        SELECT line_number, gl_account, debit_amount, credit_amount, local_amount,
               line_text, tax_code, tax_amount, trading_partner, auxiliary_account_label,
               is_suspense_account
        FROM je WHERE document_id = ? ORDER BY line_number
        """,
        [did],
    ).fetchall()
    truth = con.execute(
        """
        SELECT manipulation_scenario, manipulation_subtype, manipulation_intent,
               year_concept, evaluation_note, truth_layer, stealth_profile
        FROM truth WHERE document_id = ?
        """,
        [did],
    ).fetchone()

    label = scen or "NORMAL"
    w("=" * 110)
    w(f"[{label}] {hdr[0]}  posting={hdr[4]}  type={hdr[5]}  cur={hdr[6]}  ref={hdr[7]}")
    w(f"  header_text : {hdr[8]}")
    w(f"  source      : {hdr[11]}  bp={hdr[12]}  sem_scen={hdr[13]}  ctp_type={hdr[14]}")
    w(
        f"  created_by  : {hdr[9]} ({hdr[10]})  approved_by={hdr[15]}  approval_date={hdr[16]}  sod={hdr[17]}"
    )
    if truth:
        w(
            f"  TRUTH       : scenario={truth[0]} subtype={truth[1]} intent={truth[2]} year={truth[3]} layer={truth[5]} stealth={truth[6]}"
        )
        w(f"  eval_note   : {truth[4]}")
    w(f"  lines ({len(rows)}):")
    tot_d = tot_c = 0.0
    for L in rows:
        ln, acct, dr, cr, la, txt, tcode, tamt, tp, aux, susp = L
        atype, sub, ndb = acct_meta(acct)
        side = "DR" if dr and float(dr) > 0 else "CR"
        amt = float(dr) if side == "DR" else float(cr)
        flag = ""
        if side == "DR" and ndb is False:
            flag += " [ABN-SIDE]"
        if side == "CR" and ndb is True:
            flag += " [ABN-SIDE]"
        if susp:
            flag += " [SUSPENSE]"
        atype_short = (atype or "?")[:9]
        sub_short = (sub or "?")[:24]
        txt_short = (txt or "")[:36]
        tp_short = f" tp={tp}" if tp else ""
        w(
            f"    {ln:>2}  {acct}  {atype_short:<9}/{sub_short:<24}  {side} {amt:>15,.0f}  {txt_short}{tp_short}{flag}"
        )
        tot_d += float(dr or 0)
        tot_c += float(cr or 0)
    bal = "OK" if abs(tot_d - tot_c) < 1 else f"FAIL DR-CR={tot_d - tot_c:,.0f}"
    w(f"  totals: DR={tot_d:>15,.0f}  CR={tot_c:>15,.0f}  balance={bal}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines_out), encoding="utf-8")
print(f"wrote {OUT} ({len(lines_out)} lines)")
