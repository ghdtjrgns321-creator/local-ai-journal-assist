"""P3-2 overlay 156 truth unit exhaustive injection audit.

For every injected truth unit (standard + evasion), pull the actual journal rows
referenced by member_document_ids and dump the trigger-relevant columns, joined
with the detector catch flag. This is the data foundation for classifying each
unit as: real-catch / coincidental-catch / detector-miss / injection-defect /
structural. No sampling: all 156 units.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# Per-rule trigger-relevant journal columns (grounded in RULES standard_reason
# + detector used_columns). Dumped so the trigger verdict is data-backed.
RULE_COLS = {
    "L1-01": ["debit_amount", "credit_amount", "local_amount"],
    "L1-02": ["gl_account", "posting_date", "document_type", "reference", "header_text"],
    "L1-03": ["fiscal_period", "posting_date", "fiscal_year"],
    "L1-04": [
        "debit_amount",
        "credit_amount",
        "approval_limit",
        "approver_authority_limit",
        "approved_by",
        "approval_required",
    ],
    "L1-05": ["approved_by", "approval_date", "created_by", "debit_amount", "credit_amount"],
    "L1-06": ["approved_by", "created_by", "sod_violation", "sod_conflict_type"],
    "L1-07": ["approved_by", "approval_date", "created_by"],
    "L1-08": ["created_by", "approved_by", "sod_violation", "sod_conflict_type"],
    "L1-09": ["approval_date", "posting_date", "approved_by"],
    "L2-01": ["reference", "debit_amount", "credit_amount", "gl_account"],
    "L2-02": ["reference", "debit_amount", "credit_amount", "document_date", "posting_date"],
    "L2-03": ["reference", "debit_amount", "credit_amount", "document_date"],
    "L2-04": ["reference", "gl_account", "debit_amount", "credit_amount"],
    "L2-05": [
        "reversal_document_id",
        "original_document_id",
        "reversal_type",
        "reversal_reason_code",
        "debit_amount",
        "credit_amount",
    ],
    "L3-01": ["gl_account", "business_process", "semantic_account_subtype", "line_text"],
    "L3-02": ["debit_amount", "credit_amount", "local_amount"],
    "L3-03": ["debit_amount", "credit_amount", "gl_account"],
    "L3-04": ["posting_date", "is_period_end", "debit_amount", "credit_amount"],
    "L3-05": ["posting_date"],
    "L3-06": ["posting_date", "created_by"],
    "L3-07": ["posting_date", "document_date", "delivery_date"],
    "L3-08": ["line_text", "header_text", "line_text_family"],
    "L3-09": ["gl_account", "semantic_account_subtype", "posting_date", "document_date"],
    "L3-10": ["gl_account", "semantic_account_subtype"],
    "L3-11": [
        "delivery_date",
        "document_date",
        "posting_date",
        "gl_account",
        "semantic_account_subtype",
    ],
    "L3-12": ["created_by", "user_persona"],
    "L4-01": [
        "gl_account",
        "debit_amount",
        "credit_amount",
        "fiscal_period",
        "semantic_account_subtype",
    ],
    "L4-02": ["debit_amount", "credit_amount", "local_amount"],
    "L4-03": ["debit_amount", "credit_amount", "gl_account"],
    "L4-04": ["gl_account", "debit_account_subtype", "credit_account_subtype"],
    "L4-05": ["created_by", "posting_date", "user_persona"],
    "L4-06": ["batch_id", "batch_type", "job_id", "source"],
    "IC01": [
        "is_intercompany",
        "trading_partner",
        "counterparty_type",
        "company_code",
        "gl_account",
    ],
    "IC02": ["is_intercompany", "trading_partner", "debit_amount", "credit_amount", "currency"],
    "IC03": ["is_intercompany", "trading_partner", "posting_date", "document_date"],
    "GR01": ["is_intercompany", "trading_partner", "company_code", "debit_amount", "credit_amount"],
    "GR03": [
        "is_intercompany",
        "trading_partner",
        "company_code",
        "debit_amount",
        "credit_amount",
        "currency",
    ],
    "D01": ["gl_account", "debit_amount", "credit_amount", "fiscal_year", "fiscal_period"],
    "D02": ["gl_account", "debit_amount", "credit_amount", "fiscal_period"],
}
ALWAYS = ["document_id", "line_number", "is_mutated", "is_synthetic", "company_code", "fiscal_year"]
ACCOUNT_CODE_KEYS = {
    "account_code",
    "account_number",
    "gl_account",
    "code",
    "number",
    "id",
}


def normalize_account_code(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def collect_account_codes(value) -> set[str]:
    codes: set[str] = set()
    if isinstance(value, list):
        for item in value:
            codes.update(collect_account_codes(item))
        return codes
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ACCOUNT_CODE_KEYS:
                code = normalize_account_code(item)
                if code:
                    codes.add(code)
            if isinstance(item, dict) and normalize_account_code(key).isdigit():
                codes.add(normalize_account_code(key))
            codes.update(collect_account_codes(item))
    return codes


def load_dataset_coa_accounts(data_dir: Path) -> set[str]:
    candidates = [
        data_dir / "chart_of_accounts.json",
        data_dir / "master_data" / "chart_of_accounts.json",
    ]
    for path in candidates:
        if path.exists():
            return collect_account_codes(json.loads(path.read_text(encoding="utf-8-sig")))
    return set()


def load_config_coa_accounts(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str)
    for col in ("gl_account", "account_code", "account_number", "code"):
        if col in df.columns:
            return {
                normalize_account_code(v)
                for v in df[col].dropna()
                if normalize_account_code(v)
            }
    return set()


def allowed_l103_invalid_docs(data_dir: Path) -> set[str]:
    truth_path = data_dir / "labels" / "p3_2_rule_truth.csv"
    if not truth_path.exists():
        return set()
    truth = pd.read_csv(truth_path, dtype=str)
    required = {"rule_id", "case_kind", "member_document_ids"}
    if not required.issubset(truth.columns):
        return set()
    target = truth[
        truth["rule_id"].astype(str).eq("L1-03")
        & truth["case_kind"].astype(str).eq("standard")
    ]
    docs: set[str] = set()
    for value in target["member_document_ids"]:
        docs.update(jlist(value))
    return docs


def audit_coa_coverage(data_dir: Path, config_coa_path: Path) -> dict[str, object]:
    dataset_accounts = load_dataset_coa_accounts(data_dir)
    config_accounts = load_config_coa_accounts(config_coa_path)
    allowed_invalid_docs = allowed_l103_invalid_docs(data_dir)
    records: dict[str, dict[str, object]] = {}

    for chunk in pd.read_csv(
        data_dir / "journal_entries.csv",
        usecols=lambda c: c in {"document_id", "gl_account"},
        dtype=str,
        chunksize=200000,
        low_memory=False,
    ):
        if "gl_account" not in chunk.columns:
            continue
        if "document_id" not in chunk.columns:
            chunk["document_id"] = ""
        for row in chunk[["document_id", "gl_account"]].itertuples(index=False):
            doc_id = str(row.document_id).strip()
            account = normalize_account_code(row.gl_account)
            if not account:
                continue
            missing_dataset = account not in dataset_accounts
            missing_config = account not in config_accounts
            if not missing_dataset and not missing_config:
                continue
            item = records.setdefault(
                account,
                {
                    "gl_account": account,
                    "missing_dataset_coa": missing_dataset,
                    "missing_config_coa": missing_config,
                    "allowed_l103_rows": 0,
                    "forbidden_rows": 0,
                    "allowed_l103_docs": set(),
                    "forbidden_docs": set(),
                },
            )
            item["missing_dataset_coa"] = bool(item["missing_dataset_coa"] or missing_dataset)
            item["missing_config_coa"] = bool(item["missing_config_coa"] or missing_config)
            if doc_id in allowed_invalid_docs:
                item["allowed_l103_rows"] = int(item["allowed_l103_rows"]) + 1
                item["allowed_l103_docs"].add(doc_id)  # type: ignore[union-attr]
            else:
                item["forbidden_rows"] = int(item["forbidden_rows"]) + 1
                item["forbidden_docs"].add(doc_id)  # type: ignore[union-attr]

    findings = []
    for item in sorted(records.values(), key=lambda x: str(x["gl_account"])):
        findings.append(
            {
                "gl_account": item["gl_account"],
                "missing_dataset_coa": item["missing_dataset_coa"],
                "missing_config_coa": item["missing_config_coa"],
                "allowed_l103_rows": item["allowed_l103_rows"],
                "allowed_l103_docs": len(item["allowed_l103_docs"]),
                "forbidden_rows": item["forbidden_rows"],
                "forbidden_docs": len(item["forbidden_docs"]),
            }
        )

    forbidden = [row for row in findings if int(row["forbidden_rows"]) > 0]
    return {
        "status": "PASS" if not forbidden else "FAIL",
        "dataset_coa_accounts": len(dataset_accounts),
        "config_coa_accounts": len(config_accounts),
        "allowed_l103_invalid_docs": len(allowed_invalid_docs),
        "missing_account_findings": findings,
        "forbidden_missing_accounts": forbidden,
    }


def jlist(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    t = str(v).strip()
    if not t:
        return []
    x = json.loads(t) if t.startswith("[") else t.split("|")
    return [str(i) for i in x if str(i)]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", type=Path)
    ap.add_argument(
        "--config-coa",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config" / "chart_of_accounts.csv",
    )
    args = ap.parse_args(argv)
    D = args.data_dir
    R = D / "reports" / "phase1_detector_catch"
    R.mkdir(parents=True, exist_ok=True)

    coa_report = audit_coa_coverage(D, args.config_coa)
    coa_path = R / "coa_coverage_gate.json"
    coa_path.write_text(json.dumps(coa_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "[audit] coa coverage "
        f"status={coa_report['status']} "
        f"findings={len(coa_report['missing_account_findings'])} "
        f"forbidden={len(coa_report['forbidden_missing_accounts'])}"
    )
    if coa_report["status"] != "PASS":
        print(f"[audit][FAIL] CoA coverage gate failed: {coa_path}")
        for row in coa_report["forbidden_missing_accounts"]:
            print(
                "[audit][FAIL] missing CoA outside L1-03 standard "
                f"gl_account={row['gl_account']} "
                f"dataset_missing={row['missing_dataset_coa']} "
                f"config_missing={row['missing_config_coa']} "
                f"forbidden_docs={row['forbidden_docs']} "
                f"forbidden_rows={row['forbidden_rows']}"
            )
        return 1

    truth = pd.read_csv(D / "labels" / "p3_2_rule_truth.csv")
    truth["member_document_ids"] = truth["member_document_ids"].map(jlist)
    truth["base_document_ids"] = (
        truth["base_document_ids"].map(jlist)
        if "base_document_ids" in truth.columns
        else [[] for _ in range(len(truth))]
    )
    meas = pd.read_csv(R / "truth_unit_measurement.csv")
    caught_map = {
        (r.rule_id, r.case_kind, int(r.case_index)): bool(r.caught) for r in meas.itertuples()
    }
    pos_map = {
        (r.rule_id, r.case_kind, int(r.case_index)): int(r.positive_rows) for r in meas.itertuples()
    }

    # All member + base docs across 156 units
    all_docs = set()
    for _, row in truth.iterrows():
        all_docs.update(row["member_document_ids"])
        all_docs.update(row["base_document_ids"])
    print(f"[audit] truth units={len(truth)} target docs={len(all_docs)}")

    # Stream journal, keep only target-doc rows
    use = list(dict.fromkeys(ALWAYS + [c for cs in RULE_COLS.values() for c in cs]))
    chunks = []
    for ch in pd.read_csv(
        D / "journal_entries.csv", usecols=lambda c: c in use, chunksize=200000, low_memory=False
    ):
        hit = ch[ch["document_id"].astype(str).isin(all_docs)]
        if len(hit):
            chunks.append(hit)
    jr = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=use)
    distinct_docs = jr["document_id"].astype(str).nunique() if len(jr) else 0
    print(f"[audit] journal rows matched={len(jr)} distinct docs={distinct_docs}")
    by_doc = {d: g for d, g in jr.groupby(jr["document_id"].astype(str))} if len(jr) else {}

    records = []
    for _, row in truth.iterrows():
        rid = str(row["rule_id"])
        ck = str(row["case_kind"])
        ci = int(row["case_index"])
        docs = list(row["member_document_ids"]) + list(row["base_document_ids"])
        found = (
            pd.concat([by_doc[d] for d in docs if d in by_doc], ignore_index=True)
            if any(d in by_doc for d in docs)
            else pd.DataFrame()
        )
        rec = {
            "rule_id": rid,
            "case_kind": ck,
            "case_index": ci,
            "natural_unit_type": str(row.get("natural_unit_type", "")),
            "expected_surface": str(row.get("expected_surface", "")),
            "evasion_vector": str(row.get("evasion_vector", "")),
            "caught": caught_map.get((rid, ck, ci)),
            "positive_rows": pos_map.get((rid, ck, ci)),
            "member_docs": len(set(docs)),
            "journal_rows_found": int(len(found)),
            "is_mutated_any": bool(
                found["is_mutated"].astype(str).str.lower().isin(["true", "1"]).any()
            )
            if len(found) and "is_mutated" in found.columns
            else None,
        }
        # dump rule-specific columns as compact json of unique values
        for c in RULE_COLS.get(rid, []):
            if len(found) and c in found.columns:
                vals = found[c].tolist()
                rec[f"col::{c}"] = json.dumps(vals, ensure_ascii=True, default=str)[:300]
            else:
                rec[f"col::{c}"] = ""
        records.append(rec)

    out = pd.DataFrame(records)
    out_path = R / "overlay_injection_audit.csv"
    out.to_csv(out_path, index=False, encoding="utf-8")
    print(f"[audit] wrote {out_path} rows={len(out)}")
    # quick coverage stats
    nf = out[out["journal_rows_found"] == 0]
    print(f"[audit] units with NO journal rows found: {len(nf)}")
    if len(nf):
        print(nf["rule_id"].value_counts().sort_index().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
