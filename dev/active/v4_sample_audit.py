"""V4 candidate 분개 — 다중 시드 샘플링 후 회계 논리 위반(non-pass)만 추출."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

ROOT = Path("data/journal/primary/datasynth_manipulation_v4_candidate")
OUT = Path("dev/active/v4_sample_audit.txt")
SEEDS = [11, 22, 33, 44, 55]
NORMAL_PER_SEED = 7
MANIP_PER_SCENARIO_PER_SEED = 1

con = duckdb.connect(":memory:")
print("loading je table ...", flush=True)
con.execute(
    f"CREATE TABLE je AS SELECT * FROM read_csv_auto('{ROOT.as_posix()}/journal_entries.csv', sample_size=-1)"
)
con.execute("CREATE INDEX idx_je_doc ON je(document_id)")
print("loading truth table ...", flush=True)
con.execute(
    f"CREATE TABLE truth AS SELECT * FROM read_csv_auto('{ROOT.as_posix()}/labels/manipulated_entry_truth.csv', sample_size=-1)"
)
print("tables ready", flush=True)

with open(ROOT / "chart_of_accounts.json", encoding="utf-8") as f:
    coa_raw = json.load(f)
coa = {str(a["account_number"]): a for a in coa_raw["accounts"]}


def acct(code):
    return coa.get(str(code))


@dataclass
class DocAudit:
    seed: int
    label: str
    document_id: str
    posting_date: str
    sem_scen: str
    flags: list[str] = field(default_factory=list)
    detail: list[str] = field(default_factory=list)


# ---- candidate pool (cached once) ----
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
scenarios = [
    r[0]
    for r in con.execute("SELECT DISTINCT manipulation_scenario FROM truth ORDER BY 1").fetchall()
]
manip_pool = {
    s: [
        r[0]
        for r in con.execute(
            "SELECT document_id FROM truth WHERE manipulation_scenario = ?", [s]
        ).fetchall()
    ]
    for s in scenarios
}


def sample_for_seed(seed: int):
    rng = random.Random(seed)
    normal_pick = rng.sample(all_normal, NORMAL_PER_SEED)
    manip_pick = []
    for s in scenarios:
        pool = manip_pool[s][:]
        rng.shuffle(pool)
        for d in pool[:MANIP_PER_SCENARIO_PER_SEED]:
            manip_pick.append((s, d))
    return [(None, d) for d in normal_pick] + manip_pick


def audit_doc(seed: int, scen: str | None, did: str) -> DocAudit:
    hdr = con.execute(
        """
        SELECT DISTINCT document_id, company_code, posting_date, document_type, currency,
                        reference, header_text, created_by, user_persona, source,
                        business_process, semantic_scenario_id, counterparty_type,
                        approved_by, approval_date, sod_violation
        FROM je WHERE document_id = ?
        """,
        [did],
    ).fetchone()
    rows = con.execute(
        """
        SELECT line_number, gl_account, debit_amount, credit_amount,
               line_text, trading_partner, is_suspense_account
        FROM je WHERE document_id = ? ORDER BY line_number
        """,
        [did],
    ).fetchall()

    label = scen or "NORMAL"
    audit = DocAudit(
        seed=seed,
        label=label,
        document_id=str(did),
        posting_date=str(hdr[2]),
        sem_scen=str(hdr[11]),
    )

    # ---- mechanical checks ----
    tot_d = sum(float(r[2] or 0) for r in rows)
    tot_c = sum(float(r[3] or 0) for r in rows)
    if abs(tot_d - tot_c) > 1:
        audit.flags.append("BALANCE_FAIL")
        audit.detail.append(f"DR={tot_d:,.0f} CR={tot_c:,.0f} diff={tot_d - tot_c:,.0f}")

    # zero-filler lines (both DR and CR ~ 0)
    zero_lines = [r for r in rows if (float(r[2] or 0) < 1 and float(r[3] or 0) < 1)]
    if zero_lines:
        audit.flags.append("ZERO_FILLER_LINE")
        audit.detail.append(f"zero lines: {[r[0] for r in zero_lines]}")

    # self-approval but sod_violation=False
    cby, aby, sod = hdr[7], hdr[13], hdr[15]
    if cby and aby and cby == aby and sod is False:
        audit.flags.append("SELF_APPROVAL_NO_SOD")
        audit.detail.append(f"created_by={cby}==approved_by={aby} sod={sod}")

    # approval anachronism
    pdate = hdr[2]
    adate = hdr[14]
    if pdate is not None and adate is not None:
        try:
            pd = datetime.fromisoformat(str(pdate).split(" ")[0])
            ad = datetime.fromisoformat(str(adate).split(" ")[0])
            delta = (ad - pd).days
            if delta < 0:
                audit.flags.append("APPROVAL_BEFORE_POSTING")
                audit.detail.append(f"approval={ad.date()} posting={pd.date()} delta={delta}d")
            elif delta > 60:
                audit.flags.append("APPROVAL_AFTER_POSTING_LATE")
                audit.detail.append(f"approval={ad.date()} posting={pd.date()} delta=+{delta}d")
        except Exception:
            pass

    # CoA missing accounts
    missing = [str(r[1]) for r in rows if str(r[1]) not in coa]
    if missing:
        audit.flags.append("ACCOUNT_NOT_IN_COA")
        audit.detail.append(f"missing accts: {missing}")

    # template-specific sanity: O2C_CUSTOMER_INVOICE expects revenue on credit side
    sem = hdr[11] or ""
    cr_subtypes = []
    dr_subtypes = []
    for r in rows:
        a = acct(r[1])
        if not a:
            continue
        side = "DR" if float(r[2] or 0) > 0 else "CR"
        if side == "CR":
            cr_subtypes.append(a.get("sub_type"))
        else:
            dr_subtypes.append(a.get("sub_type"))
    if sem == "O2C_CUSTOMER_INVOICE":
        revenue_credits = [s for s in cr_subtypes if s and "revenue" in s.lower()]
        ar_debits = [s for s in dr_subtypes if s and "receivable" in s.lower()]
        if not revenue_credits:
            audit.flags.append("O2C_INVOICE_NO_REVENUE_CR")
            audit.detail.append(f"CR sub_types={cr_subtypes}")
        if not ar_debits:
            audit.flags.append("O2C_INVOICE_NO_AR_DR")
            audit.detail.append(f"DR sub_types={dr_subtypes}")
    if sem == "H2R_PAYROLL_PAYMENT":
        salary_dr = [
            s
            for s in dr_subtypes
            if s and ("personnel" in s.lower() or "salary" in s.lower() or "payroll" in s.lower())
        ]
        if not salary_dr:
            audit.flags.append("PAYROLL_NO_SALARY_DR")
            audit.detail.append(f"DR sub_types={dr_subtypes}")
    if sem == "P2P_VENDOR_INVOICE":
        ap_cr = [s for s in cr_subtypes if s and "payable" in s.lower()]
        clearing_cr = [s for s in cr_subtypes if s and "clearing" in s.lower()]
        if not ap_cr and clearing_cr:
            audit.flags.append("P2P_INVOICE_GR_IR_INSTEAD_OF_AP")
            audit.detail.append(f"CR sub_types={cr_subtypes}")

    return audit


# ---- run all seeds ----
all_audits: list[DocAudit] = []
for seed in SEEDS:
    for scen, did in sample_for_seed(seed):
        all_audits.append(audit_doc(seed, scen, did))

failed = [a for a in all_audits if a.flags]

# ---- write report ----
lines: list[str] = []
lines.append(f"# V4 Candidate Sampling Audit (seeds={SEEDS})")
lines.append(f"total sampled: {len(all_audits)}  |  flagged: {len(failed)}")
lines.append("")
# group by flag for summary
flag_counts: dict[str, int] = {}
for a in failed:
    for f in a.flags:
        flag_counts[f] = flag_counts.get(f, 0) + 1
lines.append("## flag summary")
for f, c in sorted(flag_counts.items(), key=lambda x: -x[1]):
    lines.append(f"- {f}: {c}")
lines.append("")
lines.append("## flagged documents (with full journal lines)")
for a in failed:
    lines.append("=" * 110)
    lines.append(
        f"[seed={a.seed}] [{a.label}] {a.document_id}  posting={a.posting_date}  sem={a.sem_scen}"
    )
    lines.append(f"  flags : {a.flags}")
    for d in a.detail:
        lines.append(f"  - {d}")
    # full lines for context
    rows = con.execute(
        """
        SELECT line_number, gl_account, debit_amount, credit_amount, line_text, trading_partner, is_suspense_account
        FROM je WHERE document_id = ? ORDER BY line_number
        """,
        [a.document_id],
    ).fetchall()
    hdr = con.execute(
        """
        SELECT DISTINCT header_text, created_by, user_persona, approved_by, approval_date, sod_violation
        FROM je WHERE document_id = ?
        """,
        [a.document_id],
    ).fetchone()
    lines.append(
        f"  hdr   : '{hdr[0]}' creator={hdr[1]}({hdr[2]}) approver={hdr[3]} adate={hdr[4]} sod={hdr[5]}"
    )
    for L in rows:
        ln, code, dr, cr, txt, tp, susp = L
        a_ = acct(code)
        atype = (a_ or {}).get("account_type", "?")
        sub = (a_ or {}).get("sub_type", "?")
        side = "DR" if float(dr or 0) > 0 else "CR"
        amt = float(dr or 0) if side == "DR" else float(cr or 0)
        flag = " [SUSP]" if susp else ""
        tp_s = f" tp={tp}" if tp else ""
        lines.append(
            f"    {ln:>2}  {code}  {atype[:9]:<9}/{(sub or '?')[:24]:<24}  {side} {amt:>15,.0f}  {(txt or '')[:36]}{tp_s}{flag}"
        )

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} | sampled={len(all_audits)} flagged={len(failed)}")
