"""Restore O2C/P2P mix for circular RP manipulation and clean report leak keys."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("data/journal/primary/datasynth_manipulation")
YEARS = (2022, 2023, 2024)

TEXT_SALES = "\uad00\uacc4\uc0ac \ub9e4\ucd9c \uc815\uc0b0"
TEXT_PURCHASE = "\uad00\uacc4\uc0ac \ub9e4\uc785 \uc815\uc0b0"
TEXT_LINK = "\uad00\uacc4\uc0ac \uc815\uc0b0"

COMPANY_PARTNER = {"C001": "C-000001", "C002": "C-000002", "C003": "C-000003"}
PARTNER_COMPANY = {v: k for k, v in COMPANY_PARTNER.items()}
EXPECTED_CYCLE_EDGES = {("C001", "C002"), ("C002", "C003"), ("C003", "C001")}

LEAK_MARKERS = {
    "mojibake_marker_gwan": "\u613f",
    "mojibake_marker_suffix": "\uafbe",
    "mojibake_marker_jeongri": "\ub6e3",
    "mojibake_marker_geum": "\ud234",
    "label_marker_manipulated": "manipulated",
    "label_marker_source_truth": "source_truth",
    "label_marker_manipulated_entry_truth": "manipulated_entry_truth",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    path.write_text(df.to_json(orient="records", force_ascii=False, date_format="iso"), encoding="utf-8")


def _cycle_ref(row: pd.Series) -> str:
    return str(row.get("reference", ""))


def _allocate_amount(amount: float, n: int) -> list[float]:
    cents = int(round(amount * 100))
    base = cents // n
    rem = cents - base * n
    return [round((base + (1 if i < rem else 0)) / 100, 2) for i in range(n)]


def _set_doc_amount(df: pd.DataFrame, mask: pd.Series, amount: float, debit_accounts: list[str], credit_accounts: list[str]) -> None:
    rows = df.loc[mask].sort_values("line_number").index.tolist()
    if not rows:
        return
    debit_rows = [idx for idx in rows if float(df.at[idx, "debit_amount"] or 0) >= float(df.at[idx, "credit_amount"] or 0)]
    credit_rows = [idx for idx in rows if idx not in debit_rows]
    if not debit_rows or not credit_rows:
        midpoint = max(1, len(rows) // 2)
        debit_rows = rows[:midpoint]
        credit_rows = rows[midpoint:] or rows[:1]
    debit_values = _allocate_amount(amount, len(debit_rows))
    credit_values = _allocate_amount(amount, len(credit_rows))
    for pos, idx in enumerate(debit_rows):
        value = debit_values[pos]
        df.at[idx, "debit_amount"] = value
        df.at[idx, "credit_amount"] = 0.0
        df.at[idx, "local_amount"] = value
        df.at[idx, "gl_account"] = debit_accounts[pos % len(debit_accounts)]
    for pos, idx in enumerate(credit_rows):
        value = credit_values[pos]
        df.at[idx, "debit_amount"] = 0.0
        df.at[idx, "credit_amount"] = value
        df.at[idx, "local_amount"] = -value
        df.at[idx, "gl_account"] = credit_accounts[pos % len(credit_accounts)]


def _cycle_groups(df_by_year: dict[int, pd.DataFrame], truth: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    circ_ids = set(truth.loc[truth["manipulation_scenario"].eq("circular_related_party_transaction"), "document_id"].astype(str))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for year, df in df_by_year.items():
        doc_rows = df[df["document_id"].astype(str).isin(circ_ids)].sort_values("line_number").drop_duplicates("document_id")
        for row in doc_rows.itertuples(index=False):
            ref = str(getattr(row, "reference"))
            if ref.startswith("IC-CYCLE-"):
                groups[ref].append({"year": year, "document_id": str(getattr(row, "document_id"))})
    return groups


def restore_circular_process_mix(base: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    groups = _cycle_groups(df_by_year, truth)
    for ref, docs in sorted(groups.items()):
        docs = sorted(docs, key=lambda x: x["document_id"])
        for pos, item in enumerate(docs):
            year = item["year"]
            doc_id = item["document_id"]
            df = df_by_year[year]
            mask = df["document_id"].astype(str).eq(doc_id)
            if not mask.any():
                continue
            doc = df.loc[mask].sort_values("line_number")
            amount = float(doc["debit_amount"].sum())
            if pos == 0:
                seller, buyer = "C001", "C002"
                company, partner = seller, COMPANY_PARTNER[buyer]
                process, doc_type, text = "O2C", "SA", f"{TEXT_SALES} {seller}-{buyer}"
                debit_accounts, credit_accounts = ["1150", "1100"], ["4500", "4000"]
            elif pos == 1:
                seller, buyer = "C002", "C003"
                company, partner = buyer, COMPANY_PARTNER[seller]
                process, doc_type, text = "P2P", "KR", f"{TEXT_PURCHASE} {buyer}-{seller}"
                debit_accounts, credit_accounts = ["5000", "1200"], ["2050", "2000"]
            else:
                seller, buyer = "C003", "C001"
                company, partner = seller, COMPANY_PARTNER[buyer]
                process, doc_type, text = "O2C", "SA", f"{TEXT_SALES} {seller}-{buyer}"
                debit_accounts, credit_accounts = ["1150", "1100"], ["4500", "4000"]
            df.loc[mask, "company_code"] = company
            df.loc[mask, "trading_partner"] = partner
            df.loc[mask, "business_process"] = process
            df.loc[mask, "document_type"] = doc_type
            df.loc[mask, "header_text"] = text
            df.loc[mask, "line_text"] = text
            _set_doc_amount(df, mask, amount, debit_accounts, credit_accounts)

            truth_mask = truth["document_id"].astype(str).eq(doc_id)
            truth.loc[truth_mask, "company_code"] = company
            truth.loc[truth_mask, "business_process"] = process
            truth.loc[truth_mask, "document_type"] = doc_type
            truth.loc[truth_mask, "reference_pattern"] = "circular_related_party_transaction:shared_rp_three_company_cycle_o2c_p2p_mix"
            truth.loc[truth_mask, "manipulation_subtype"] = "shared_rp_three_company_cycle_o2c_p2p_mix"

    singleton = truth[
        truth["manipulation_scenario"].eq("circular_related_party_transaction")
        & truth["manipulation_subtype"].astype(str).str.contains("counterparty_link", na=False)
    ]
    for row in singleton.itertuples(index=False):
        year = int(row.fiscal_year)
        df = df_by_year[year]
        mask = df["document_id"].astype(str).eq(str(row.document_id))
        if not mask.any():
            continue
        amount = float(df.loc[mask, "debit_amount"].sum())
        df.loc[mask, "company_code"] = "C001"
        df.loc[mask, "trading_partner"] = COMPANY_PARTNER["C002"]
        df.loc[mask, "business_process"] = "O2C"
        df.loc[mask, "document_type"] = "SA"
        df.loc[mask, "header_text"] = f"{TEXT_LINK} C001-C002"
        df.loc[mask, "line_text"] = f"{TEXT_LINK} C001-C002"
        _set_doc_amount(df, mask, amount, ["1150", "1100"], ["4500", "4000"])
        truth_mask = truth["document_id"].astype(str).eq(str(row.document_id))
        truth.loc[truth_mask, "company_code"] = "C001"
        truth.loc[truth_mask, "business_process"] = "O2C"
        truth.loc[truth_mask, "document_type"] = "SA"
    rebuild_ic_sidecars(base, truth, df_by_year)
    return truth


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
    groups = _cycle_groups(df_by_year, truth)
    for ref, docs in sorted(groups.items()):
        docs = sorted(docs, key=lambda x: x["document_id"])
        for pos, item in enumerate(docs):
            year = item["year"]
            doc = df_by_year[year][df_by_year[year]["document_id"].astype(str).eq(item["document_id"])].sort_values("line_number")
            if doc.empty:
                continue
            first = doc.iloc[0]
            if pos == 0:
                seller, buyer = "C001", "C002"
            elif pos == 1:
                seller, buyer = "C002", "C003"
            else:
                seller, buyer = "C003", "C001"
            amount = round(float(doc["debit_amount"].sum()), 2)
            pairs.append(
                {
                    "ic_reference": ref,
                    "transaction_type": "shared_related_party_cycle",
                    "seller_company": seller,
                    "buyer_company": buyer,
                    "amount": str(amount),
                    "currency": "KRW",
                    "transaction_date": str(first["posting_date"]).split(" ")[0],
                    "posting_date": str(first["posting_date"]).split(" ")[0],
                    "seller_document": str(first["document_number"]) if str(first["business_process"]) == "O2C" else f"ICS-{year}-{len(pairs):04d}",
                    "buyer_document": str(first["document_number"]) if str(first["business_process"]) == "P2P" else f"ICB-{year}-{len(pairs):04d}",
                    "description": f"Shared RP settlement {seller}->{buyer}",
                    "transfer_pricing_policy": "manual_review_required",
                    "withholding_tax": None,
                    "settlement_status": "open",
                    "settlement_date": None,
                    "netting_reference": ref,
                    "document_id": item["document_id"],
                }
            )
            sellers.append(_ic_record(first, doc, ref, seller, buyer, "seller"))
            buyers.append(_ic_record(first, doc, ref, buyer, seller, "buyer"))
    _write_json(inter_dir / "ic_matched_pairs.json", pairs)
    _write_json(inter_dir / "ic_seller_journal_entries.json", sellers)
    _write_json(inter_dir / "ic_buyer_journal_entries.json", buyers)


def _ic_record(first: pd.Series, doc: pd.DataFrame, ref: str, company: str, partner_company: str, role: str) -> dict[str, Any]:
    process = "O2C" if role == "seller" else "P2P"
    doc_type = "SA" if role == "seller" else "KR"
    text = f"{TEXT_SALES if role == 'seller' else TEXT_PURCHASE} - {partner_company}"
    header = {
        "document_id": str(first["document_id"]),
        "company_code": company,
        "fiscal_year": int(first["fiscal_year"]),
        "fiscal_period": int(first["fiscal_period"]),
        "posting_date": str(first["posting_date"]).split(" ")[0],
        "document_date": str(first["document_date"]).split(" ")[0],
        "document_type": doc_type,
        "currency": "KRW",
        "exchange_rate": "1",
        "reference": ref,
        "header_text": text,
        "created_by": str(first["created_by"]),
        "user_persona": str(first["user_persona"]),
        "source": str(first["source"]),
        "business_process": process,
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
                "line_text": text,
                "text": text,
                "reference": ref,
                "assignment": ref,
                "trading_partner": partner_company,
            }
        )
    return {"header": header, "lines": lines}


def refresh_truth(labels_dir: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    docs = pd.concat([df.sort_values("line_number").drop_duplicates("document_id") for df in df_by_year.values()], ignore_index=True).set_index("document_id")
    for idx, row in truth.iterrows():
        doc_id = str(row["document_id"])
        if doc_id not in docs.index:
            continue
        src = docs.loc[doc_id]
        for col in [
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "business_process",
            "source",
            "created_by",
            "approved_by",
            "approval_date",
            "user_persona",
        ]:
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


def validate(base: Path, truth: pd.DataFrame, journal: pd.DataFrame) -> dict[str, Any]:
    failures: list[str] = []
    ids = set(truth["document_id"].astype(str))
    je = journal[journal["document_id"].astype(str).isin(ids)]
    bal = je.groupby("document_id")[["debit_amount", "credit_amount"]].sum()
    unbalanced = int(((bal["debit_amount"] - bal["credit_amount"]).abs() > 0.001).sum())
    if unbalanced:
        failures.append(f"unbalanced manipulated docs: {unbalanced}")
    input_text = json.dumps(
        {
            "journal": je[["header_text", "line_text", "reference"]].fillna("").astype(str).to_dict("records"),
            "ic_pairs": _read_json(base / "intercompany" / "ic_matched_pairs.json"),
            "ic_seller": _read_json(base / "intercompany" / "ic_seller_journal_entries.json"),
            "ic_buyer": _read_json(base / "intercompany" / "ic_buyer_journal_entries.json"),
        },
        ensure_ascii=False,
    ).lower()
    leak_marker_counts = {name: input_text.count(token.lower()) for name, token in LEAK_MARKERS.items()}
    if any(leak_marker_counts.values()):
        failures.append(f"encoding/leakage markers remain: {leak_marker_counts}")

    pairs = [p for p in _read_json(base / "intercompany" / "ic_matched_pairs.json") if str(p.get("ic_reference", "")).startswith("IC-CYCLE-")]
    pair_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for pair in pairs:
        pair_groups[str(pair["ic_reference"])].append((str(pair["seller_company"]), str(pair["buyer_company"])))
    bad_cycles = {ref: edges for ref, edges in pair_groups.items() if len(edges) != 3 or set(edges) != EXPECTED_CYCLE_EDGES}
    if bad_cycles:
        failures.append(f"bad IC cycle edges: {bad_cycles}")

    circ = (
        je.sort_values("line_number")
        .drop_duplicates("document_id")
        .merge(truth[["document_id", "manipulation_scenario"]], on="document_id")
    )
    circ = circ[circ["manipulation_scenario"].eq("circular_related_party_transaction")]
    circ_process_docs = circ.groupby("business_process")["document_id"].nunique().to_dict()
    if not {"O2C", "P2P"}.issubset(set(circ_process_docs)):
        failures.append(f"circular RP process mix missing O2C/P2P: {circ_process_docs}")

    doc = je.sort_values("line_number").drop_duplicates("document_id").merge(
        truth[["document_id", "manipulation_scenario", "manipulation_subtype"]], on="document_id"
    )
    metrics = {}
    for scenario, group in doc.groupby("manipulation_scenario"):
        metrics[scenario] = {
            "documents": int(len(group)),
            "subtypes": group["manipulation_subtype"].value_counts().to_dict(),
            "max_amount": float(bal.loc[group["document_id"], "debit_amount"].max()),
        }
    return {
        "failures": failures,
        "leak_marker_counts": leak_marker_counts,
        "complete_ic_cycle_count": len(pair_groups),
        "circular_rp_process_docs": {str(k): int(v) for k, v in circ_process_docs.items()},
        "scenario_metrics": metrics,
    }


def refresh_metadata(base: Path, journal: pd.DataFrame, truth: pd.DataFrame, checks: dict[str, Any]) -> None:
    meta = _read_json(base / "validated_metadata.json")
    meta.pop("checks", None)
    meta.update(
        {
            "status": "pass" if not checks["failures"] else "fail",
            "version": "v131_manipulation_process_mix_and_report_keys",
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
        "# DataSynth Manipulation v131",
        "",
        "This split contains normal journal rows plus actual manipulation scenario truth only.",
        "",
        f"- Rows: {len(journal):,}",
        f"- Documents: {journal['document_id'].nunique():,}",
        f"- Manipulated-entry truth documents: {truth['document_id'].nunique():,}",
        f"- Complete circular IC cycles: {checks['complete_ic_cycle_count']}",
        f"- Circular RP process mix: `{checks['circular_rp_process_docs']}`",
        f"- Validation status: {'pass' if not checks['failures'] else 'fail'}",
        "",
        "## Scenario Metrics",
        "",
        "| Scenario | Docs | Max Amount | Subtypes |",
        "|---|---:|---:|---|",
    ]
    for scenario, metric in checks["scenario_metrics"].items():
        lines.append(f"| {scenario} | {metric['documents']} | {metric['max_amount']:.2f} | `{metric['subtypes']}` |")
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
    df_by_year = {}
    for year in YEARS:
        df = pd.read_csv(base / f"journal_entries_{year}.csv", low_memory=False)
        df["gl_account"] = df["gl_account"].astype("object")
        df_by_year[year] = df
    truth = restore_circular_process_mix(base, truth, df_by_year)
    truth = refresh_truth(labels_dir, truth, df_by_year)
    combined = pd.concat([df_by_year[year] for year in YEARS], ignore_index=True)
    for year, df in df_by_year.items():
        df.to_csv(base / f"journal_entries_{year}.csv", index=False)
        _write_json_records(base / f"journal_entries_{year}.json", df)
    combined.to_csv(base / "journal_entries.csv", index=False)
    _write_json_records(base / "journal_entries.json", combined)
    checks = validate(base, truth, combined)
    refresh_metadata(base, combined, truth, checks)
    write_preview(base, checks, combined, truth)
    manifest = {
        "version": "v131_manipulation_process_mix_and_report_keys",
        "base_version": "v130_manipulation_encoding_and_cycle_fix",
        "data_dir": str(base),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "row_count": int(len(combined)),
        "document_count": int(combined["document_id"].nunique()),
        "manipulated_entry_truth_count": int(truth["document_id"].nunique()),
        "checks": checks,
    }
    _write_json(base / "V131_MANIPULATION_PROCESS_MIX_AND_REPORT_KEYS.json", manifest)
    print(json.dumps(manifest, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
