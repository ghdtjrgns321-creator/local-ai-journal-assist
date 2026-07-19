"""Fix v129 manipulation encoding and related-party cycle edge regressions."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("data/journal/primary/datasynth_manipulation")
YEARS = (2022, 2023, 2024)

TEXT_RELATED_PARTY_LOAN = "\uad00\uacc4\uc0ac \ub300\uc5ec\uae08 \uc815\ub9ac"
TEXT_RELATED_PARTY_SETTLEMENT = "\uad00\uacc4\uc0ac \uc815\uc0b0"
TEXT_RELATED_PARTY_SALES = "\uad00\uacc4\uc0ac \ub9e4\ucd9c \uc815\uc0b0"
TEXT_RELATED_PARTY_PURCHASE = "\uad00\uacc4\uc0ac \ub9e4\uc785 \uc815\uc0b0"

EDGE_SEQUENCE = [
    ("C001", "C002", "C-000002"),
    ("C002", "C003", "C-000003"),
    ("C003", "C001", "C-000001"),
]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    path.write_text(df.to_json(orient="records", force_ascii=False, date_format="iso"), encoding="utf-8")


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _is_bad_text(value: Any) -> bool:
    text = "" if pd.isna(value) else str(value)
    return any(token in text for token in ["愿", "꾩", "뺣", "툑", "?"])


def _clean_bad_text_frame(df: pd.DataFrame) -> None:
    for col in ["header_text", "line_text"]:
        if col in df.columns:
            mask = df[col].map(_is_bad_text)
            df.loc[mask, col] = TEXT_RELATED_PARTY_LOAN


def _allocate_amount(amount: float, n: int) -> list[float]:
    cents = int(round(amount * 100))
    base = cents // n
    rem = cents - base * n
    return [round((base + (1 if i < rem else 0)) / 100, 2) for i in range(n)]


def _set_balanced_doc(df: pd.DataFrame, mask: pd.Series, amount: float, debit_accounts: list[str], credit_accounts: list[str]) -> None:
    rows = df.loc[mask].sort_values("line_number").index.tolist()
    if not rows:
        return
    debit_rows = [r for r in rows if float(df.at[r, "debit_amount"] or 0) >= float(df.at[r, "credit_amount"] or 0)]
    credit_rows = [r for r in rows if r not in debit_rows]
    if not debit_rows or not credit_rows:
        half = max(1, len(rows) // 2)
        debit_rows = rows[:half]
        credit_rows = rows[half:] or rows[:1]
    for i, row_idx in enumerate(debit_rows):
        value = _allocate_amount(amount, len(debit_rows))[i]
        df.at[row_idx, "debit_amount"] = value
        df.at[row_idx, "credit_amount"] = 0.0
        df.at[row_idx, "local_amount"] = value
        df.at[row_idx, "gl_account"] = debit_accounts[i % len(debit_accounts)]
    for i, row_idx in enumerate(credit_rows):
        value = _allocate_amount(amount, len(credit_rows))[i]
        df.at[row_idx, "debit_amount"] = 0.0
        df.at[row_idx, "credit_amount"] = value
        df.at[row_idx, "local_amount"] = -value
        df.at[row_idx, "gl_account"] = credit_accounts[i % len(credit_accounts)]


def _cycle_datetime(year: int, cycle_no: int, edge_pos: int) -> datetime:
    month = [2, 5, 8, 11][(cycle_no - 1) % 4]
    day = 9 + ((cycle_no + edge_pos) % 6)
    hour = [9, 11, 14][edge_pos] + ((cycle_no + edge_pos) % 2)
    minute = [17, 43, 8, 29, 36][(cycle_no + edge_pos) % 5]
    return datetime(year, month, day, hour, minute, 0) + timedelta(days=[0, 2, 5][edge_pos])


def fix_circular_cycles(truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    circ = truth[truth["manipulation_scenario"].eq("circular_related_party_transaction")].sort_values(
        ["fiscal_year", "posting_date", "document_id"]
    )
    for year, gy in circ.groupby("fiscal_year"):
        docs = gy["document_id"].astype(str).tolist()
        df = df_by_year[int(year)]
        complete_n = (len(docs) // 3) * 3
        for i, doc_id in enumerate(docs):
            mask = df["document_id"].astype(str).eq(doc_id)
            if not mask.any():
                continue
            if i < complete_n:
                cycle_no = i // 3 + 1
                edge_pos = i % 3
                seller, buyer, partner = EDGE_SEQUENCE[edge_pos]
                ref = f"IC-CYCLE-{int(year)}-{cycle_no:03d}"
                subtype = "shared_rp_three_company_cycle"
                amount = 9_000_000 + (int(year) - 2020) * 350_000 + cycle_no * 410_000
                amount = round(amount * [1.0, 1.012, 0.988][edge_pos], 2)
                dt = _cycle_datetime(int(year), cycle_no, edge_pos)
            else:
                seller, buyer, partner = "C001", "C002", "C-000002"
                ref = f"IC-RP-LINK-{int(year)}-{i // 3 + 1:03d}"
                subtype = "shared_rp_counterparty_link"
                amount = 7_500_000 + i * 100_000
                dt = _cycle_datetime(int(year), i // 3 + 1, 0)

            df.loc[mask, "company_code"] = seller
            df.loc[mask, "trading_partner"] = partner
            df.loc[mask, "business_process"] = "R2R"
            df.loc[mask, "document_type"] = "IC"
            df.loc[mask, "reference"] = ref
            df.loc[mask, "posting_date"] = _fmt_dt(dt)
            df.loc[mask, "document_date"] = _fmt_date(dt)
            df.loc[mask, "fiscal_period"] = dt.month
            df.loc[mask, "header_text"] = f"{TEXT_RELATED_PARTY_SETTLEMENT} {seller}-{buyer}"
            df.loc[mask, "line_text"] = f"{TEXT_RELATED_PARTY_SETTLEMENT} {seller}-{buyer}"
            _set_balanced_doc(df, mask, amount, ["1150", "1100"], ["4500", "4000"])

            truth_mask = truth["document_id"].astype(str).eq(doc_id)
            truth.loc[truth_mask, "company_code"] = seller
            truth.loc[truth_mask, "business_process"] = "R2R"
            truth.loc[truth_mask, "document_type"] = "IC"
            truth.loc[truth_mask, "posting_date"] = _fmt_dt(dt)
            truth.loc[truth_mask, "reference_pattern"] = f"circular_related_party_transaction:{subtype}"
            truth.loc[truth_mask, "manipulation_subtype"] = subtype
    return truth


def refresh_truth(labels_dir: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    docs = pd.concat([df.sort_values("line_number").drop_duplicates("document_id") for df in df_by_year.values()], ignore_index=True).set_index("document_id")
    for idx, row in truth.iterrows():
        doc_id = str(row["document_id"])
        if doc_id not in docs.index:
            continue
        src = docs.loc[doc_id]
        for col in ["company_code", "document_number", "document_type", "posting_date", "business_process", "source", "created_by", "approved_by", "approval_date", "user_persona"]:
            truth.at[idx, col] = src[col]
        year_df = df_by_year[int(row["fiscal_year"])]
        mask = year_df["document_id"].astype(str).eq(doc_id)
        truth.at[idx, "line_count"] = int(mask.sum())
        truth.at[idx, "line_amount"] = float(year_df.loc[mask, "debit_amount"].sum())
    write_label_family(labels_dir, truth, "manipulated_entry_truth")
    summary = truth.groupby(["fiscal_year", "manipulation_scenario"]).size().reset_index(name="document_count")
    summary.to_csv(labels_dir / "manipulated_entry_scenario_summary.csv", index=False)
    _write_json_records(labels_dir / "manipulated_entry_scenario_summary.json", summary)
    return truth


def write_label_family(labels_dir: Path, df: pd.DataFrame, stem: str) -> None:
    df.to_csv(labels_dir / f"{stem}.csv", index=False)
    _write_json_records(labels_dir / f"{stem}.json", df)
    for year, sub in df.groupby("fiscal_year"):
        year = int(year)
        sub.to_csv(labels_dir / f"{stem}_{year}.csv", index=False)
        _write_json_records(labels_dir / f"{stem}_{year}.json", sub)


def rebuild_ic_sidecars(base: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> None:
    inter_dir = base / "intercompany"
    circ_ids = set(truth.loc[truth["manipulation_scenario"].eq("circular_related_party_transaction"), "document_id"].astype(str))
    pairs = [
        p
        for p in _read_json(inter_dir / "ic_matched_pairs.json")
        if not str(p.get("ic_reference", "")).startswith(("IC-CYCLE-", "IC-RP-LINK-")) and str(p.get("document_id", "")) not in circ_ids
    ]
    sellers = [
        x
        for x in _read_json(inter_dir / "ic_seller_journal_entries.json")
        if not str(x.get("header", {}).get("reference", "")).startswith(("IC-CYCLE-", "IC-RP-LINK-")) and str(x.get("header", {}).get("document_id", "")) not in circ_ids
    ]
    buyers = [
        x
        for x in _read_json(inter_dir / "ic_buyer_journal_entries.json")
        if not str(x.get("header", {}).get("reference", "")).startswith(("IC-CYCLE-", "IC-RP-LINK-")) and str(x.get("header", {}).get("document_id", "")) not in circ_ids
    ]
    circ = truth[truth["manipulation_scenario"].eq("circular_related_party_transaction")].sort_values(["fiscal_year", "posting_date"])
    partner_company_by_partner = {"C-000001": "C001", "C-000002": "C002", "C-000003": "C003"}
    for i, row in enumerate(circ.itertuples(index=False), start=1):
        if row.manipulation_subtype != "shared_rp_three_company_cycle":
            continue
        year = int(row.fiscal_year)
        doc = df_by_year[year][df_by_year[year]["document_id"].astype(str).eq(str(row.document_id))]
        if doc.empty:
            continue
        first = doc.iloc[0]
        seller = str(first["company_code"])
        partner_company = partner_company_by_partner.get(str(first["trading_partner"]), "UNKNOWN")
        ref = str(first["reference"])
        amount = round(float(doc["debit_amount"].sum()), 2)
        pairs.append(
            {
                "ic_reference": ref,
                "transaction_type": "shared_related_party_cycle",
                "seller_company": seller,
                "buyer_company": partner_company,
                "amount": str(amount),
                "currency": "KRW",
                "transaction_date": str(first["posting_date"]).split(" ")[0],
                "posting_date": str(first["posting_date"]).split(" ")[0],
                "seller_document": str(first["document_number"]),
                "buyer_document": f"ICB-{year}-{i:04d}",
                "description": f"Shared RP settlement {seller}->{partner_company}",
                "transfer_pricing_policy": "manual_review_required",
                "withholding_tax": None,
                "settlement_status": "open",
                "settlement_date": None,
                "netting_reference": ref,
                "document_id": str(row.document_id),
            }
        )
        sellers.append(_ic_record(first, doc, ref, seller, partner_company, True))
        buyers.append(_ic_record(first, doc, ref, partner_company, seller, False))
    _write_json(inter_dir / "ic_matched_pairs.json", pairs)
    _write_json(inter_dir / "ic_seller_journal_entries.json", sellers)
    _write_json(inter_dir / "ic_buyer_journal_entries.json", buyers)


def _ic_record(first: pd.Series, doc: pd.DataFrame, ref: str, company: str, partner_company: str, seller: bool) -> dict[str, Any]:
    header = {
        "document_id": str(first["document_id"]),
        "company_code": company,
        "fiscal_year": int(first["fiscal_year"]),
        "fiscal_period": int(first["fiscal_period"]),
        "posting_date": str(first["posting_date"]).split(" ")[0],
        "document_date": str(first["document_date"]).split(" ")[0],
        "document_type": str(first["document_type"]),
        "currency": "KRW",
        "exchange_rate": "1",
        "reference": ref,
        "header_text": f"{TEXT_RELATED_PARTY_SALES if seller else TEXT_RELATED_PARTY_PURCHASE} - {partner_company}",
        "created_by": str(first["created_by"]),
        "user_persona": str(first["user_persona"]),
        "source": str(first["source"]),
        "business_process": "R2R",
        "ledger": "0L",
        "sod_violation": bool(str(first.get("sod_violation")).lower() in {"true", "1"}),
        "sod_conflict_type": first.get("sod_conflict_type") if pd.notna(first.get("sod_conflict_type")) else None,
        "approved_by": first.get("approved_by") if pd.notna(first.get("approved_by")) else None,
        "approval_date": first.get("approval_date") if pd.notna(first.get("approval_date")) else None,
        "has_attachment": bool(str(first.get("has_attachment")).lower() in {"true", "1"}),
        "document_number": str(first["document_number"]),
    }
    lines = []
    for _, line in doc.iterrows():
        lines.append(
            {
                "document_id": str(line["document_id"]),
                "line_number": int(line["line_number"]),
                "gl_account": str(line["gl_account"]),
                "debit_amount": str(line["debit_amount"]),
                "credit_amount": str(line["credit_amount"]),
                "local_amount": str(line["local_amount"]),
                "line_text": str(line["line_text"]),
                "text": str(line["line_text"]),
                "reference": ref,
                "assignment": ref,
                "trading_partner": partner_company,
            }
        )
    return {"header": header, "lines": lines}


def validate(base: Path, truth: pd.DataFrame, journal: pd.DataFrame) -> dict[str, Any]:
    failures: list[str] = []
    ids = set(truth["document_id"].astype(str))
    je = journal[journal["document_id"].astype(str).isin(ids)]
    bal = je.groupby("document_id")[["debit_amount", "credit_amount"]].sum()
    unbalanced = int(((bal["debit_amount"] - bal["credit_amount"]).abs() > 0.001).sum())
    if unbalanced:
        failures.append(f"unbalanced manipulated docs: {unbalanced}")
    text = json.dumps(
        {
            "journal": je[["header_text", "line_text", "reference"]].fillna("").astype(str).to_dict("records"),
            "ic_pairs": _read_json(base / "intercompany" / "ic_matched_pairs.json"),
            "ic_seller": _read_json(base / "intercompany" / "ic_seller_journal_entries.json"),
            "ic_buyer": _read_json(base / "intercompany" / "ic_buyer_journal_entries.json"),
        },
        ensure_ascii=False,
    ).lower()
    bad_tokens = ["愿", "꾩", "뺣", "툑", "manipulated", "source_truth", "manipulated_entry_truth"]
    leaks = {tok: text.count(tok.lower()) for tok in bad_tokens}
    if any(leaks.values()):
        failures.append(f"encoding/leakage tokens remain: {leaks}")
    pairs = [p for p in _read_json(base / "intercompany" / "ic_matched_pairs.json") if str(p.get("ic_reference", "")).startswith("IC-CYCLE-")]
    from collections import Counter

    counts = Counter(p["ic_reference"] for p in pairs)
    expected_edges = {("C001", "C002"), ("C002", "C003"), ("C003", "C001")}
    bad_cycles = {}
    for ref, count in counts.items():
        rows = [p for p in pairs if p["ic_reference"] == ref]
        edges = {(p["seller_company"], p["buyer_company"]) for p in rows}
        if count != 3 or edges != expected_edges:
            bad_cycles[ref] = sorted(edges)
    if bad_cycles:
        failures.append(f"bad IC cycle edges: {bad_cycles}")
    doc = je.sort_values("line_number").drop_duplicates("document_id").merge(truth[["document_id", "manipulation_scenario", "manipulation_subtype"]], on="document_id")
    metrics = {}
    for scenario, g in doc.groupby("manipulation_scenario"):
        metrics[scenario] = {
            "documents": int(len(g)),
            "subtypes": g["manipulation_subtype"].value_counts().to_dict(),
            "max_amount": float(bal.loc[g["document_id"], "debit_amount"].max()),
        }
    return {"failures": failures, "leaks": leaks, "complete_ic_cycle_count": len(counts), "scenario_metrics": metrics}


def refresh_metadata(base: Path, journal: pd.DataFrame, truth: pd.DataFrame, checks: dict[str, Any]) -> None:
    meta = _read_json(base / "validated_metadata.json")
    meta.update(
        {
            "status": "pass" if not checks["failures"] else "fail",
            "version": "v130_manipulation_encoding_and_cycle_fix",
            "total_entries": int(journal["document_id"].nunique()),
            "total_line_items": int(len(journal)),
            "scenario_truth_documents": int(truth["document_id"].nunique()),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "checks": checks,
        }
    )
    _write_json(base / "validated_metadata.json", meta)


def write_preview(base: Path, checks: dict[str, Any], journal: pd.DataFrame, truth: pd.DataFrame) -> None:
    lines = [
        "# DataSynth Manipulation v130",
        "",
        "This split contains normal journal rows plus actual manipulation scenario truth only.",
        "",
        f"- Rows: {len(journal):,}",
        f"- Documents: {journal['document_id'].nunique():,}",
        f"- Manipulated-entry truth documents: {truth['document_id'].nunique():,}",
        f"- Complete circular IC cycles: {checks['complete_ic_cycle_count']}",
        f"- Validation status: {'pass' if not checks['failures'] else 'fail'}",
        "",
        "## Scenario Metrics",
        "",
        "| Scenario | Docs | Max Amount | Subtypes |",
        "|---|---:|---:|---|",
    ]
    for scenario, m in checks["scenario_metrics"].items():
        lines.append(f"| {scenario} | {m['documents']} | {m['max_amount']:.2f} | `{m['subtypes']}` |")
    if checks["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in checks["failures"])
    (base / "PREVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    base = args.data_dir
    labels_dir = base / "labels"
    truth = pd.read_csv(labels_dir / "manipulated_entry_truth.csv")
    _clean_bad_text_frame(truth)
    df_by_year: dict[int, pd.DataFrame] = {}
    for year in YEARS:
        df = pd.read_csv(base / f"journal_entries_{year}.csv", low_memory=False)
        df["gl_account"] = df["gl_account"].astype("object")
        _clean_bad_text_frame(df)
        df_by_year[year] = df
    truth = fix_circular_cycles(truth, df_by_year)
    truth = refresh_truth(labels_dir, truth, df_by_year)
    rebuild_ic_sidecars(base, truth, df_by_year)
    combined = pd.concat([df_by_year[y] for y in YEARS], ignore_index=True)
    for year, df in df_by_year.items():
        df.to_csv(base / f"journal_entries_{year}.csv", index=False)
        _write_json_records(base / f"journal_entries_{year}.json", df)
    combined.to_csv(base / "journal_entries.csv", index=False)
    _write_json_records(base / "journal_entries.json", combined)
    checks = validate(base, truth, combined)
    refresh_metadata(base, combined, truth, checks)
    write_preview(base, checks, combined, truth)
    manifest = {
        "version": "v130_manipulation_encoding_and_cycle_fix",
        "base_version": "v129_manipulation_cleanup",
        "data_dir": str(base),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "row_count": int(len(combined)),
        "document_count": int(combined["document_id"].nunique()),
        "manipulated_entry_truth_count": int(truth["document_id"].nunique()),
        "checks": checks,
    }
    _write_json(base / "V130_MANIPULATION_ENCODING_AND_CYCLE_FIX.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
