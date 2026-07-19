"""Strictly repair circular related-party manipulation flow consistency."""

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

COMPANY_PARTNER = {"C001": "C-000001", "C002": "C-000002", "C003": "C-000003"}
PARTNER_COMPANY = {v: k for k, v in COMPANY_PARTNER.items()}
EDGE_SEQUENCE = [("C001", "C002"), ("C002", "C003"), ("C003", "C001")]
EXPECTED_EDGES = set(EDGE_SEQUENCE)

TEXT_SALES = "\uad00\uacc4\uc0ac \ub9e4\ucd9c \uc815\uc0b0"
TEXT_PURCHASE = "\uad00\uacc4\uc0ac \ub9e4\uc785 \uc815\uc0b0"
TEXT_LINK = "\uad00\uacc4\uc0ac \uc815\uc0b0"

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


def _allocate_amount(amount: float, n: int) -> list[float]:
    cents = int(round(amount * 100))
    base = cents // n
    rem = cents - base * n
    return [round((base + (1 if i < rem else 0)) / 100, 2) for i in range(n)]


def _set_doc_amount(df: pd.DataFrame, mask: pd.Series, amount: float, debit_accounts: list[str], credit_accounts: list[str]) -> None:
    rows = df.loc[mask].sort_values("line_number").index.tolist()
    debit_rows = [idx for idx in rows if float(df.at[idx, "debit_amount"] or 0) >= float(df.at[idx, "credit_amount"] or 0)]
    credit_rows = [idx for idx in rows if idx not in debit_rows]
    if not debit_rows or not credit_rows:
        midpoint = max(1, len(rows) // 2)
        debit_rows = rows[:midpoint]
        credit_rows = rows[midpoint:] or rows[:1]
    for idx, value in zip(debit_rows, _allocate_amount(amount, len(debit_rows)), strict=False):
        df.at[idx, "debit_amount"] = value
        df.at[idx, "credit_amount"] = 0.0
        df.at[idx, "local_amount"] = value
    for idx, value in zip(credit_rows, _allocate_amount(amount, len(credit_rows)), strict=False):
        df.at[idx, "debit_amount"] = 0.0
        df.at[idx, "credit_amount"] = value
        df.at[idx, "local_amount"] = -value
    for pos, idx in enumerate(debit_rows):
        df.at[idx, "gl_account"] = debit_accounts[pos % len(debit_accounts)]
    for pos, idx in enumerate(credit_rows):
        df.at[idx, "gl_account"] = credit_accounts[pos % len(credit_accounts)]


def _cycle_groups(df_by_year: dict[int, pd.DataFrame], truth: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    circ_ids = set(truth.loc[truth["manipulation_scenario"].eq("circular_related_party_transaction"), "document_id"].astype(str))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for year, df in df_by_year.items():
        docs = df[df["document_id"].astype(str).isin(circ_ids)].sort_values("line_number").drop_duplicates("document_id")
        for row in docs.itertuples(index=False):
            ref = str(getattr(row, "reference"))
            if ref.startswith("IC-CYCLE-"):
                groups[ref].append({"year": year, "document_id": str(getattr(row, "document_id"))})
    return groups


def _cycle_number(ref: str) -> int:
    try:
        return int(ref.rsplit("-", 1)[-1])
    except ValueError:
        return 1


def repair_circular_rp(base: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    groups = _cycle_groups(df_by_year, truth)
    for ref, docs in sorted(groups.items()):
        docs = sorted(docs, key=lambda item: item["document_id"])
        purchase_pos = (_cycle_number(ref) - 1) % 3
        base_amount = 9_500_000 + _cycle_number(ref) * 430_000
        for pos, item in enumerate(docs):
            seller, buyer = EDGE_SEQUENCE[pos]
            df = df_by_year[item["year"]]
            mask = df["document_id"].astype(str).eq(item["document_id"])
            if not mask.any():
                continue
            if pos == purchase_pos:
                company = buyer
                partner = COMPANY_PARTNER[seller]
                process = "P2P"
                doc_type = "KR"
                text = f"{TEXT_PURCHASE} {buyer}-{seller}"
                amount = base_amount * 2
                debit_accounts = ["5000", "1200"]
                credit_accounts = ["2050", "2000"]
            else:
                company = seller
                partner = COMPANY_PARTNER[buyer]
                process = "O2C"
                doc_type = "SA"
                text = f"{TEXT_SALES} {seller}-{buyer}"
                amount = base_amount
                debit_accounts = ["1150", "1100"]
                credit_accounts = ["4500", "4000"]
            df.loc[mask, "company_code"] = company
            df.loc[mask, "trading_partner"] = partner
            df.loc[mask, "business_process"] = process
            df.loc[mask, "document_type"] = doc_type
            df.loc[mask, "header_text"] = text
            df.loc[mask, "line_text"] = text
            _set_doc_amount(df, mask, amount, debit_accounts, credit_accounts)

            truth_mask = truth["document_id"].astype(str).eq(item["document_id"])
            truth.loc[truth_mask, "company_code"] = company
            truth.loc[truth_mask, "business_process"] = process
            truth.loc[truth_mask, "document_type"] = doc_type
            truth.loc[truth_mask, "manipulation_subtype"] = "shared_rp_three_company_cycle_balanced_o2c_p2p"
            truth.loc[truth_mask, "reference_pattern"] = "circular_related_party_transaction:shared_rp_three_company_cycle_balanced_o2c_p2p"

    singleton = truth[
        truth["manipulation_scenario"].eq("circular_related_party_transaction")
        & truth["manipulation_subtype"].astype(str).str.contains("counterparty_link", na=False)
    ]
    for row in singleton.itertuples(index=False):
        df = df_by_year[int(row.fiscal_year)]
        mask = df["document_id"].astype(str).eq(str(row.document_id))
        if not mask.any():
            continue
        amount = float(df.loc[mask, "debit_amount"].sum())
        df.loc[mask, "company_code"] = "C002"
        df.loc[mask, "trading_partner"] = COMPANY_PARTNER["C001"]
        df.loc[mask, "business_process"] = "P2P"
        df.loc[mask, "document_type"] = "KR"
        df.loc[mask, "header_text"] = f"{TEXT_LINK} C002-C001"
        df.loc[mask, "line_text"] = f"{TEXT_LINK} C002-C001"
        _set_doc_amount(df, mask, amount, ["5000", "1200"], ["2050", "2000"])
        truth_mask = truth["document_id"].astype(str).eq(str(row.document_id))
        truth.loc[truth_mask, "company_code"] = "C002"
        truth.loc[truth_mask, "business_process"] = "P2P"
        truth.loc[truth_mask, "document_type"] = "KR"
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
        docs = sorted(docs, key=lambda item: item["document_id"])
        for pos, item in enumerate(docs):
            seller, buyer = EDGE_SEQUENCE[pos]
            doc = df_by_year[item["year"]][df_by_year[item["year"]]["document_id"].astype(str).eq(item["document_id"])].sort_values("line_number")
            if doc.empty:
                continue
            first = doc.iloc[0]
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
                    "seller_document": str(first["document_number"]),
                    "buyer_document": str(first["document_number"]),
                    "description": f"Shared RP settlement {seller}->{buyer}",
                    "transfer_pricing_policy": "manual_review_required",
                    "withholding_tax": None,
                    "settlement_status": "open",
                    "settlement_date": None,
                    "netting_reference": ref,
                    "document_id": item["document_id"],
                }
            )
            sellers.append(_ic_record(first, doc, ref, seller, buyer))
            buyers.append(_ic_record(first, doc, ref, seller, buyer))
    _write_json(inter_dir / "ic_matched_pairs.json", pairs)
    _write_json(inter_dir / "ic_seller_journal_entries.json", sellers)
    _write_json(inter_dir / "ic_buyer_journal_entries.json", buyers)


def _ic_record(first: pd.Series, doc: pd.DataFrame, ref: str, seller: str, buyer: str) -> dict[str, Any]:
    header = {
        "document_id": str(first["document_id"]),
        "company_code": str(first["company_code"]),
        "fiscal_year": int(first["fiscal_year"]),
        "fiscal_period": int(first["fiscal_period"]),
        "posting_date": str(first["posting_date"]).split(" ")[0],
        "document_date": str(first["document_date"]).split(" ")[0],
        "document_type": str(first["document_type"]),
        "currency": "KRW",
        "exchange_rate": "1",
        "reference": ref,
        "header_text": str(first["header_text"]),
        "created_by": str(first["created_by"]),
        "user_persona": str(first["user_persona"]),
        "source": str(first["source"]),
        "business_process": str(first["business_process"]),
        "ledger": "0L",
        "sod_violation": bool(str(first.get("sod_violation")).lower() in {"true", "1"}),
        "sod_conflict_type": first.get("sod_conflict_type") if pd.notna(first.get("sod_conflict_type")) else None,
        "approved_by": first.get("approved_by") if pd.notna(first.get("approved_by")) else None,
        "approval_date": first.get("approval_date") if pd.notna(first.get("approval_date")) else None,
        "has_attachment": bool(str(first.get("has_attachment")).lower() in {"true", "1"}),
        "document_number": str(first["document_number"]),
        "cycle_seller_company": seller,
        "cycle_buyer_company": buyer,
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
                "trading_partner": str(line["trading_partner"]) if pd.notna(line["trading_partner"]) else None,
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

    circ_truth = truth[truth["manipulation_scenario"].eq("circular_related_party_transaction")]
    circ_ids = set(circ_truth["document_id"].astype(str))
    circ_rows = journal[journal["document_id"].astype(str).isin(circ_ids)]
    circ_doc = circ_rows.sort_values("line_number").drop_duplicates("document_id")
    circ_amounts = circ_rows.groupby("document_id")["debit_amount"].sum().to_dict()
    complete_doc = circ_doc[circ_doc["reference"].astype(str).str.startswith("IC-CYCLE-")]
    company_docs = complete_doc.groupby("company_code")["document_id"].nunique().to_dict()
    company_process_docs = complete_doc.groupby(["company_code", "business_process"])["document_id"].nunique().to_dict()
    rp_values = sorted(complete_doc["trading_partner"].dropna().astype(str).unique().tolist())
    if set(company_docs) != {"C001", "C002", "C003"}:
        failures.append(f"circular RP missing company participation: {company_docs}")
    for company in ["C001", "C002", "C003"]:
        for process in ["O2C", "P2P"]:
            if int(company_process_docs.get((company, process), 0)) == 0:
                failures.append(f"circular RP missing {company}/{process}")
    if set(rp_values) != {"C-000001", "C-000002", "C-000003"}:
        failures.append(f"circular RP missing RP diversity: {rp_values}")

    pairs = [p for p in _read_json(base / "intercompany" / "ic_matched_pairs.json") if str(p.get("ic_reference", "")).startswith("IC-CYCLE-")]
    pair_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        pair_groups[str(pair["ic_reference"])].append(pair)
    bad_cycles = {}
    amount_mismatch_cycles = {}
    for ref, rows in pair_groups.items():
        edges = {(str(row["seller_company"]), str(row["buyer_company"])) for row in rows}
        if len(rows) != 3 or edges != EXPECTED_EDGES:
            bad_cycles[ref] = sorted(edges)
        row_docs = set(str(row["document_id"]) for row in rows)
        docs = complete_doc[complete_doc["document_id"].astype(str).isin(row_docs)]
        sales = float(sum(circ_amounts.get(doc_id, 0.0) for doc_id in docs.loc[docs["business_process"].eq("O2C"), "document_id"]))
        purchases = float(sum(circ_amounts.get(doc_id, 0.0) for doc_id in docs.loc[docs["business_process"].eq("P2P"), "document_id"]))
        if abs(sales - purchases) > 1.0:
            amount_mismatch_cycles[ref] = {"sales": round(sales, 2), "purchases": round(purchases, 2)}
    if bad_cycles:
        failures.append(f"bad IC cycle edges: {bad_cycles}")
    if amount_mismatch_cycles:
        failures.append(f"circular RP sales/purchase mismatch: {amount_mismatch_cycles}")

    sidecar_mismatches = []
    doc_type_map = complete_doc.set_index("document_id")["document_type"].astype(str).to_dict()
    for sidecar_name in ["ic_seller_journal_entries.json", "ic_buyer_journal_entries.json"]:
        for rec in _read_json(base / "intercompany" / sidecar_name):
            header = rec.get("header", {})
            doc_id = str(header.get("document_id", ""))
            if doc_id in doc_type_map and str(header.get("document_type")) != doc_type_map[doc_id]:
                sidecar_mismatches.append({"file": sidecar_name, "document_id": doc_id, "sidecar": header.get("document_type"), "journal": doc_type_map[doc_id]})
    if sidecar_mismatches:
        failures.append(f"circular sidecar document_type mismatch: {sidecar_mismatches[:5]} total={len(sidecar_mismatches)}")

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
        "circular_rp_company_docs": {str(k): int(v) for k, v in company_docs.items()},
        "circular_rp_company_process_docs": {f"{k[0]}:{k[1]}": int(v) for k, v in company_process_docs.items()},
        "circular_rp_unique_partners": rp_values,
        "circular_sidecar_document_type_mismatches": len(sidecar_mismatches),
        "scenario_metrics": metrics,
    }


def refresh_metadata(base: Path, journal: pd.DataFrame, truth: pd.DataFrame, checks: dict[str, Any]) -> None:
    meta = _read_json(base / "validated_metadata.json")
    meta.update(
        {
            "status": "pass" if not checks["failures"] else "fail",
            "version": "v132_manipulation_circular_rp_strict",
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
        "# DataSynth Manipulation v132",
        "",
        "This split contains normal journal rows plus actual manipulation scenario truth only.",
        "",
        f"- Rows: {len(journal):,}",
        f"- Documents: {journal['document_id'].nunique():,}",
        f"- Manipulated-entry truth documents: {truth['document_id'].nunique():,}",
        f"- Complete circular IC cycles: {checks['complete_ic_cycle_count']}",
        f"- Circular RP company docs: `{checks['circular_rp_company_docs']}`",
        f"- Circular RP company/process docs: `{checks['circular_rp_company_process_docs']}`",
        f"- Circular RP unique partners: `{checks['circular_rp_unique_partners']}`",
        f"- Circular sidecar document_type mismatches: {checks['circular_sidecar_document_type_mismatches']}",
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
    truth = repair_circular_rp(base, truth, df_by_year)
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
        "version": "v132_manipulation_circular_rp_strict",
        "base_version": "v131_manipulation_process_mix_and_report_keys",
        "data_dir": str(base),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "row_count": int(len(combined)),
        "document_count": int(combined["document_id"].nunique()),
        "manipulated_entry_truth_count": int(truth["document_id"].nunique()),
        "checks": checks,
    }
    _write_json(base / "V132_MANIPULATION_CIRCULAR_RP_STRICT.json", manifest)
    print(json.dumps(manifest, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
