"""Overlay shortcut/leak scanner.

Detects columns where overlay-injected (truth) rows carry value patterns that
NEVER appear in the normal population - a leak an ML model could exploit to
separate fraud from normal without learning structure. Goes beyond exact-value
frequency: also catches FORMAT-signature and NUMERIC-RANGE leaks (the class the
prior narrow scan missed for `reference`).

Detection modes per column:
  - exact_value : truth value with count>=N_VALUE and normal count == 0
  - format_sig  : truth string format signature (letters->A, digits->#) absent in normal
  - numeric_rng : truth numeric-suffix bucket (//step) absent in normal

Natural per-document unique keys (document_id) are pattern/range-only (their raw
values are unique by design, so exact-value mode is meaningless and skipped).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

N_VALUE = 5  # exact-value: truth occurrences threshold
N_SIG = 5  # format/range: truth occurrences threshold for a signature/bucket
RANGE_STEP = 1000  # numeric-suffix bucket size

# Columns to scan (token/id/text/reference surfaces). Amounts excluded (continuous,
# legitimately overlap). document_id is identifier-only -> pattern/range modes only.
SCAN_COLS = [
    "document_id",
    "document_number",
    "reference",
    "header_text",
    "line_text",
    "line_text_family",
    "reversal_type",
    "reversal_reason",
    "reversal_reason_code",
    "batch_id",
    "job_id",
    "batch_type",
    "source",
    "created_by",
    "approved_by",
    "user_persona",
    "trading_partner",
    "counterparty_type",
    "document_type",
    "tax_treatment",
    "sod_conflict_type",
    "cost_center",
    "profit_center",
]
IDENTIFIER_COLS = {"document_id"}  # exact-value mode skipped (unique by design)

_DIGIT = re.compile(r"\d")
_ALPHA = re.compile(r"[A-Za-z]")
_NUM_SUFFIX = re.compile(r"(\d+)$")


def fmt_sig(v: str) -> str:
    """Collapse to a format signature: digits->#, ascii letters->A, keep others."""
    s = _DIGIT.sub("#", str(v))
    s = _ALPHA.sub("A", s)
    # collapse runs so 'AAA-####' ~ 'AA-###' don't explode; keep structural shape
    s = re.sub(r"A+", "A", s)
    s = re.sub(r"#+", "#", s)
    return s


def num_bucket(v: str):
    m = _NUM_SUFFIX.search(str(v))
    return (int(m.group(1)) // RANGE_STEP) if m else None


def jlist(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    t = str(v).strip()
    if not t:
        return []
    try:
        return [str(i) for i in json.loads(t)] if t.startswith("[") else [t]
    except Exception:
        return [t]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", type=Path)
    ap.add_argument("--n-value", type=int, default=N_VALUE)
    ap.add_argument("--n-sig", type=int, default=N_SIG)
    args = ap.parse_args(argv)
    D = args.data_dir

    truth = pd.read_csv(D / "labels" / "p3_2_rule_truth.csv")
    tdocs = set()
    for _, r in truth.iterrows():
        tdocs.update(jlist(r.get("member_document_ids")))
        tdocs.update(jlist(r.get("base_document_ids")))
    print(f"[scan] truth docs={len(tdocs)} cols={len(SCAN_COLS)}")

    cols = [c for c in SCAN_COLS]
    tv = defaultdict(lambda: defaultdict(int))  # truth exact value counts
    nv = defaultdict(set)  # normal exact value set
    tsig = defaultdict(lambda: defaultdict(int))  # truth format-sig counts
    nsig = defaultdict(set)  # normal format-sig set
    trng = defaultdict(lambda: defaultdict(int))  # truth numeric-bucket counts
    nrng = defaultdict(set)  # normal numeric-bucket set

    for ch in pd.read_csv(
        D / "journal_entries.csv",
        usecols=lambda c: c in (["document_id"] + cols),
        chunksize=200000,
        dtype=str,
        low_memory=False,
    ):
        ist = ch["document_id"].astype(str).isin(tdocs)
        for c in cols:
            if c not in ch.columns:
                continue
            tser = ch.loc[ist, c].dropna()
            nser = ch.loc[~ist, c].dropna()
            if c not in IDENTIFIER_COLS:
                for v in tser:
                    tv[c][v] += 1
                nv[c].update(nser.unique())
            for v in tser:
                tsig[c][fmt_sig(v)] += 1
                b = num_bucket(v)
                if b is not None:
                    trng[c][b] += 1
            for v in nser.unique():
                nsig[c].add(fmt_sig(v))
            for v in nser:
                b = num_bucket(v)
                if b is not None:
                    nrng[c].add(b)

    findings = []
    for c in cols:
        if c not in IDENTIFIER_COLS:
            ev = [(v, n) for v, n in tv[c].items() if n >= args.n_value and v not in nv[c]]
            if ev:
                findings.append((c, "exact_value", len(ev), ev[:3]))
        sg = [(s, n) for s, n in tsig[c].items() if n >= args.n_sig and s not in nsig[c]]
        if sg:
            findings.append((c, "format_sig", len(sg), sg[:3]))
        rg = [(b, n) for b, n in trng[c].items() if n >= args.n_sig and b not in nrng[c]]
        if rg:
            findings.append(
                (
                    c,
                    "numeric_rng",
                    len(rg),
                    [(f"{b * RANGE_STEP}-{(b + 1) * RANGE_STEP - 1}", n) for b, n in rg[:3]],
                )
            )

    print(f"\n[scan] FINDINGS ({len(findings)} column-mode hits):")
    if not findings:
        print("  (none) - no truth-only value/format/range leak above thresholds")
    for c, mode, count, examples in sorted(findings, key=lambda x: (-x[2], x[0])):
        print(f"  {c:24s} {mode:12s} {count:4d}  e.g. {examples}")

    out = D / "reports" / "phase1_detector_catch" / "overlay_shortcut_scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "truth_docs": len(tdocs),
                "n_value": args.n_value,
                "n_sig": args.n_sig,
                "findings": [
                    {"column": c, "mode": m, "count": n, "examples": [list(e) for e in ex]}
                    for c, m, n, ex in findings
                ],
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n[scan] wrote {out}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
