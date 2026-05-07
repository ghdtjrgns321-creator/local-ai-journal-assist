"""Clean up v128 manipulation regressions.

Fixes:
- round-split imbalance in circular RP documents
- label-leakage wording in intercompany sidecars
- journal/IC sidecar document_type mismatch
- singleton circular RP cycle classified as a counterpart-only subtype
- overly regular circular posting times
- oversized embezzlement concealment amounts that conflict with petty captions
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("data/journal/primary/datasynth_manipulation")
YEARS = (2022, 2023, 2024)


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


def _set_balanced_amount(df: pd.DataFrame, mask: pd.Series, amount: float) -> None:
    rows = df.loc[mask].sort_values("line_number").index.tolist()
    if not rows:
        return
    debit_rows = [r for r in rows if float(df.at[r, "debit_amount"] or 0) >= float(df.at[r, "credit_amount"] or 0)]
    credit_rows = [r for r in rows if r not in debit_rows]
    if not debit_rows or not credit_rows:
        half = max(1, len(rows) // 2)
        debit_rows = rows[:half]
        credit_rows = rows[half:] or rows[:1]
    debit_alloc = _allocate_amount(amount, len(debit_rows))
    credit_alloc = _allocate_amount(amount, len(credit_rows))
    for row_idx, value in zip(debit_rows, debit_alloc, strict=False):
        df.at[row_idx, "debit_amount"] = value
        df.at[row_idx, "credit_amount"] = 0.0
        df.at[row_idx, "local_amount"] = value
    for row_idx, value in zip(credit_rows, credit_alloc, strict=False):
        df.at[row_idx, "debit_amount"] = 0.0
        df.at[row_idx, "credit_amount"] = value
        df.at[row_idx, "local_amount"] = -value


def _allocate_amount(amount: float, n: int) -> list[float]:
    if n <= 0:
        return []
    cents = int(round(amount * 100))
    base = cents // n
    rem = cents - base * n
    return [round((base + (1 if i < rem else 0)) / 100, 2) for i in range(n)]


def _rebalance_existing_doc(df: pd.DataFrame, doc_id: str) -> None:
    mask = df["document_id"].astype(str).eq(doc_id)
    if not mask.any():
        return
    debit = float(df.loc[mask, "debit_amount"].sum())
    credit = float(df.loc[mask, "credit_amount"].sum())
    amount = round(max(debit, credit), 2)
    _set_balanced_amount(df, mask, amount)


def clean_circular(df_by_year: dict[int, pd.DataFrame], truth: pd.DataFrame) -> pd.DataFrame:
    circ = truth[truth["manipulation_scenario"].eq("circular_related_party_transaction")].copy()
    circ = circ.sort_values(["fiscal_year", "posting_date", "document_id"]).reset_index(drop=True)
    for year, gy in circ.groupby("fiscal_year"):
        df = df_by_year[int(year)]
        docs = gy["document_id"].astype(str).tolist()
        complete_n = (len(docs) // 3) * 3
        for i, doc_id in enumerate(docs):
            mask = df["document_id"].astype(str).eq(doc_id)
            if not mask.any():
                continue
            first = df.loc[mask].iloc[0]
            ref = str(first["reference"])
            # Keep complete cycles as three-document refs. The unavoidable remainder is not a "cycle".
            if list(circ["document_id"].astype(str)).count(doc_id) == 0:
                continue
            cycle_index = i // 3 + 1
            pos = i % 3
            if i < complete_n:
                ref = f"IC-CYCLE-{int(year)}-{cycle_index:03d}"
                subtype = "shared_rp_three_company_cycle"
            else:
                ref = f"IC-RP-LINK-{int(year)}-{cycle_index:03d}"
                subtype = "shared_rp_counterparty_link"
            base = datetime(int(year), [2, 5, 8, 11][(cycle_index - 1) % 4], 9 + ((cycle_index + pos) % 6))
            dt = base + timedelta(days=[0, 1, 4, 2, 5][(i + pos) % 5], hours=[0, 1, 3, 5, 6][(i + pos) % 5], minutes=[17, 29, 43, 8, 36][i % 5])
            df.loc[mask, "posting_date"] = _fmt_dt(dt)
            df.loc[mask, "document_date"] = _fmt_date(dt)
            df.loc[mask, "fiscal_period"] = dt.month
            df.loc[mask, "reference"] = ref
            df.loc[mask, "document_type"] = "IC"
            _rebalance_existing_doc(df, doc_id)
            truth.loc[truth["document_id"].astype(str).eq(doc_id), "posting_date"] = _fmt_dt(dt)
            truth.loc[truth["document_id"].astype(str).eq(doc_id), "document_type"] = "IC"
            truth.loc[truth["document_id"].astype(str).eq(doc_id), "reference_pattern"] = f"circular_related_party_transaction:{subtype}"
            truth.loc[truth["document_id"].astype(str).eq(doc_id), "manipulation_subtype"] = subtype
    return truth


def clip_embezzlement_amounts(df_by_year: dict[int, pd.DataFrame], truth: pd.DataFrame) -> pd.DataFrame:
    emb = truth[truth["manipulation_scenario"].eq("embezzlement_concealment")]
    for _, row in emb.iterrows():
        year = int(row["fiscal_year"])
        df = df_by_year[year]
        mask = df["document_id"].astype(str).eq(str(row["document_id"]))
        if not mask.any():
            continue
        amount = float(df.loc[mask, "debit_amount"].sum())
        if amount <= 5_000_000_000:
            continue
        # Keep over-limit signal but make the caption plausible for concealment.
        new_amount = 4_850_000_000 + (hash(str(row["document_id"])) % 12) * 10_000_000
        _set_balanced_amount(df, mask, new_amount)
        df.loc[mask, "line_text"] = "愿怨꾩궗 ??ш툑 ?뺣━"
        df.loc[mask, "header_text"] = "愿怨꾩궗 ??ш툑 ?뺣━"
        truth.loc[truth["document_id"].astype(str).eq(str(row["document_id"])), "line_amount"] = new_amount
        truth.loc[truth["document_id"].astype(str).eq(str(row["document_id"])), "reference_pattern"] = "embezzlement_concealment:large_but_plausible_concealment"
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


def refresh_ic_sidecars(base: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> None:
    inter_dir = base / "intercompany"
    circ_doc_ids = set(truth.loc[truth["manipulation_scenario"].eq("circular_related_party_transaction"), "document_id"].astype(str))
    pairs = [
        p
        for p in _read_json(inter_dir / "ic_matched_pairs.json")
        if not str(p.get("ic_reference", "")).startswith(("IC-CYCLE-", "IC-RP-LINK-"))
        and str(p.get("document_id", "")) not in circ_doc_ids
    ]
    sellers = [
        x
        for x in _read_json(inter_dir / "ic_seller_journal_entries.json")
        if not str(x.get("header", {}).get("reference", "")).startswith(("IC-CYCLE-", "IC-RP-LINK-"))
        and str(x.get("header", {}).get("document_id", "")) not in circ_doc_ids
    ]
    buyers = [
        x
        for x in _read_json(inter_dir / "ic_buyer_journal_entries.json")
        if not str(x.get("header", {}).get("reference", "")).startswith(("IC-CYCLE-", "IC-RP-LINK-"))
        and str(x.get("header", {}).get("document_id", "")) not in circ_doc_ids
    ]
    circ = truth[truth["manipulation_scenario"].eq("circular_related_party_transaction")].sort_values(["fiscal_year", "posting_date"])
    for i, row in enumerate(circ.itertuples(index=False), start=1):
        year = int(row.fiscal_year)
        df = df_by_year[year]
        doc = df[df["document_id"].astype(str).eq(str(row.document_id))]
        if doc.empty:
            continue
        first = doc.iloc[0]
        ref = str(first["reference"])
        if not ref.startswith("IC-CYCLE-"):
            continue
        company = str(first["company_code"])
        partner = str(first["trading_partner"])
        partner_company = {"V-000001": "C001", "V-000002": "C002", "V-000003": "C003", "C-000001": "C001", "C-000002": "C002", "C-000003": "C003"}.get(partner, "UNKNOWN")
        amount = round(float(doc["debit_amount"].sum()), 2)
        pairs.append(
            {
                "ic_reference": ref,
                "transaction_type": "shared_related_party_cycle",
                "seller_company": company,
                "buyer_company": partner_company,
                "amount": str(amount),
                "currency": "KRW",
                "transaction_date": str(first["posting_date"]).split(" ")[0],
                "posting_date": str(first["posting_date"]).split(" ")[0],
                "seller_document": str(first["document_number"]),
                "buyer_document": f"ICB-{year}-{i:04d}",
                "description": f"Shared RP settlement {company}->{partner_company}",
                "transfer_pricing_policy": "manual_review_required",
                "withholding_tax": None,
                "settlement_status": "open",
                "settlement_date": None,
                "netting_reference": ref,
                "document_id": str(row.document_id),
            }
        )
        sellers.append(_sidecar_record(first, doc, ref, company, partner_company, seller=True))
        buyers.append(_sidecar_record(first, doc, ref, partner_company, company, seller=False))
    _write_json(inter_dir / "ic_matched_pairs.json", pairs)
    _write_json(inter_dir / "ic_seller_journal_entries.json", sellers)
    _write_json(inter_dir / "ic_buyer_journal_entries.json", buyers)


def _sidecar_record(first: pd.Series, doc: pd.DataFrame, ref: str, company: str, partner_company: str, *, seller: bool) -> dict[str, Any]:
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
        "header_text": f"愿怨꾩궗 {'留ㅼ텧' if seller else '留ㅼ엯'} ?뺤궛 - {partner_company}",
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
                "cost_center": line.get("cost_center") if pd.notna(line.get("cost_center")) else None,
                "profit_center": line.get("profit_center") if pd.notna(line.get("profit_center")) else None,
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
    text = " ".join(
        [
            json.dumps(_read_json(base / "intercompany" / "ic_matched_pairs.json"), ensure_ascii=False),
            json.dumps(_read_json(base / "intercompany" / "ic_seller_journal_entries.json"), ensure_ascii=False),
            json.dumps(_read_json(base / "intercompany" / "ic_buyer_journal_entries.json"), ensure_ascii=False),
        ]
    ).lower()
    leak_tokens = ["label_leak_marker", "manipulated", "source_truth", "manipulated_entry_truth"]
    leaks = {tok: text.count(tok.lower()) for tok in leak_tokens}
    if any(leaks.values()):
        failures.append(f"intercompany sidecar leakage remains: {leaks}")
    pairs = [p for p in _read_json(base / "intercompany" / "ic_matched_pairs.json") if str(p.get("ic_reference", "")).startswith("IC-CYCLE-")]
    from collections import Counter

    counts = Counter(p["ic_reference"] for p in pairs)
    incomplete = {k: v for k, v in counts.items() if v != 3}
    if incomplete:
        failures.append(f"incomplete IC cycles: {incomplete}")
    circ_ids = set(truth.loc[truth["manipulation_scenario"].eq("circular_related_party_transaction"), "document_id"].astype(str))
    doc_types = journal[journal["document_id"].astype(str).isin(circ_ids)].sort_values("line_number").drop_duplicates("document_id")["document_type"].astype(str)
    if not doc_types.isin(["IC"]).all():
        failures.append("circular journal document_type is not IC")
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
            "version": "v129_manipulation_cleanup",
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
        "# DataSynth Manipulation v129",
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
    df_by_year = {}
    for year in YEARS:
        df = pd.read_csv(base / f"journal_entries_{year}.csv", low_memory=False)
        df["gl_account"] = df["gl_account"].astype("object")
        df_by_year[year] = df
    truth = clean_circular(df_by_year, truth)
    truth = clip_embezzlement_amounts(df_by_year, truth)
    truth = refresh_truth(labels_dir, truth, df_by_year)
    refresh_ic_sidecars(base, truth, df_by_year)
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
        "version": "v129_manipulation_cleanup",
        "base_version": "v128_manipulation_rp_and_weak_signals",
        "data_dir": str(base),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "row_count": int(len(combined)),
        "document_count": int(combined["document_id"].nunique()),
        "manipulated_entry_truth_count": int(truth["document_id"].nunique()),
        "checks": checks,
    }
    _write_json(base / "V129_MANIPULATION_CLEANUP_PATCH.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
