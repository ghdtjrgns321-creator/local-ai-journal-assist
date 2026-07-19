"""Build v99 candidate by rebalancing duplicate-payment pairs across companies.

The patch does not mutate journal rows. It rebuilds DuplicatePayment truth from
naturally reconstructable same-company, same-partner, same-amount, <=45 day P2P
payment pairs in the current journal.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v98_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v99_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
PAIR_COUNT = 33
VARIANTS = [
    "exact",
    "reference_blank",
    "reference_variant",
    "date_shifted",
    "amount_rounding",
]


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl_records(path: Path, df: pd.DataFrame) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in df.where(pd.notna(df), None).to_dict(orient="records"):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _document_summary() -> pd.DataFrame:
    parts = []
    usecols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "business_process",
        "posting_date",
        "reference",
        "trading_partner",
        "debit_amount",
        "credit_amount",
    ]
    for year in YEARS:
        df = pd.read_csv(DEST / f"journal_entries_{year}.csv", usecols=usecols, low_memory=False)
        debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
        credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
        df["_line_amount"] = debit.where(debit.gt(0), credit)
        parts.append(
            df.groupby("document_id", as_index=False).agg(
                fiscal_year=("fiscal_year", "first"),
                company_code=("company_code", "first"),
                document_number=("document_number", "first"),
                document_type=("document_type", "first"),
                business_process=("business_process", "first"),
                posting_date=("posting_date", "first"),
                reference=("reference", "first"),
                trading_partner=("trading_partner", "first"),
                amount=("_line_amount", "sum"),
            )
        )
    docs = pd.concat(parts, ignore_index=True)
    docs = docs[
        docs["business_process"].eq("P2P")
        & docs["document_type"].isin(["KZ", "KR"])
    ].copy()
    docs["posting_dt"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["partner_key"] = docs["trading_partner"].fillna("").astype(str).str.strip()
    bad_partner = docs["partner_key"].eq("") | docs["partner_key"].str.lower().isin({"none", "nan", "nat"})
    extracted = docs["reference"].fillna("").astype(str).str.extract(
        r"(V-\d+|VI[:\-A-Z0-9]+|PO[:\-A-Z0-9]+|PAY[:\-A-Z0-9]+)",
        expand=False,
    )
    docs.loc[bad_partner, "partner_key"] = extracted.loc[bad_partner].fillna("")
    docs["amount_round"] = docs["amount"].round(0).astype("int64")
    return docs


def _candidate_pairs(docs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (year, company, partner, amount), group in docs.groupby(
        ["fiscal_year", "company_code", "partner_key", "amount_round"],
        dropna=False,
    ):
        if not partner or len(group) < 2:
            continue
        group = group.sort_values(["posting_dt", "document_number", "document_id"])
        values = group.to_dict("records")
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                if pd.isna(values[i]["posting_dt"]) or pd.isna(values[j]["posting_dt"]):
                    continue
                gap = int((values[j]["posting_dt"] - values[i]["posting_dt"]).days)
                if 0 < gap <= 45:
                    rows.append(
                        {
                            "fiscal_year": int(year),
                            "company_code": company,
                            "partner_key": partner,
                            "amount": float(amount),
                            "day_gap": gap,
                            "original_document_id": values[i]["document_id"],
                            "duplicate_document_id": values[j]["document_id"],
                            "original_document_number": values[i]["document_number"],
                            "duplicate_document_number": values[j]["document_number"],
                            "original_posting_date": values[i]["posting_date"],
                            "duplicate_posting_date": values[j]["posting_date"],
                            "reference_original": values[i]["reference"],
                            "reference_duplicate": values[j]["reference"],
                            "document_type": values[j]["document_type"],
                        }
                    )
                    break
    return pd.DataFrame(rows)


def _select_pairs(candidates: pd.DataFrame) -> pd.DataFrame:
    candidates = candidates.sort_values(
        ["company_code", "fiscal_year", "day_gap", "partner_key", "duplicate_document_id"]
    ).copy()
    used_docs: set[str] = set()
    buckets = {
        (company, int(year)): frame.reset_index(drop=True)
        for (company, year), frame in candidates.groupby(["company_code", "fiscal_year"], sort=True)
    }
    cursor = {key: 0 for key in buckets}
    companies = sorted(candidates["company_code"].dropna().astype(str).unique())
    years = [2024, 2023, 2022]
    selected = []

    def _try_select(company: str, year: int) -> bool:
        key = (company, year)
        if key not in buckets:
            return False
        frame = buckets[key]
        while cursor[key] < len(frame):
            row = frame.iloc[cursor[key]]
            cursor[key] += 1
            docs = {str(row["original_document_id"]), str(row["duplicate_document_id"])}
            if docs & used_docs:
                continue
            selected.append(row)
            used_docs.update(docs)
            return True
        return False

    # First consume available non-2022 evidence so the truth set is not a
    # chronological artifact of sorted source rows.
    non_2022_company_year_cap = max(1, (PAIR_COUNT // len(companies) + 1) // 2)
    for year in [2024, 2023]:
        for company in companies:
            while len(selected) < PAIR_COUNT:
                company_selected = sum(1 for row in selected if str(row["company_code"]) == company)
                company_year_selected = sum(
                    1
                    for row in selected
                    if str(row["company_code"]) == company and int(row["fiscal_year"]) == year
                )
                if company_selected >= PAIR_COUNT // len(companies):
                    break
                if company_year_selected >= non_2022_company_year_cap:
                    break
                if not _try_select(company, year):
                    break

    while len(selected) < PAIR_COUNT:
        progressed = False
        for company in companies:
            company_selected = sum(1 for row in selected if str(row["company_code"]) == company)
            if company_selected >= PAIR_COUNT // len(companies):
                continue
            for year in years:
                if _try_select(company, year):
                    progressed = True
                    break
                if progressed:
                    break
            if len(selected) >= PAIR_COUNT:
                break
        if not progressed:
            break
    if len(selected) < PAIR_COUNT:
        raise SystemExit(f"not enough non-overlapping duplicate payment pairs: {len(selected)} < {PAIR_COUNT}")
    out = pd.DataFrame(selected).reset_index(drop=True)
    out["variant"] = [VARIANTS[i % len(VARIANTS)] for i in range(len(out))]
    out["duplicate_payment_pair_id"] = [
        f"DP-V99-{int(row.fiscal_year)}-{i + 1:03d}" for i, row in out.iterrows()
    ]
    out["truth_basis"] = "same P2P vendor/payment repeated within 45 days"
    out["expected_l202_label_document_id"] = out["duplicate_document_id"]
    cols = [
        "duplicate_payment_pair_id",
        "fiscal_year",
        "company_code",
        "original_document_id",
        "duplicate_document_id",
        "original_document_number",
        "duplicate_document_number",
        "partner_key",
        "variant",
        "original_posting_date",
        "duplicate_posting_date",
        "day_gap",
        "reference_original",
        "reference_duplicate",
        "document_type",
        "amount",
        "truth_basis",
        "expected_l202_label_document_id",
    ]
    return out[cols]


def _negative_controls(docs: pd.DataFrame, selected_docs: set[str]) -> pd.DataFrame:
    controls = []
    eligible = docs.loc[
        ~docs["document_id"].astype(str).isin(selected_docs)
        & docs["company_code"].isin(["C001", "C002", "C003"])
    ].sort_values(["fiscal_year", "company_code", "posting_dt", "document_id"])
    for year in YEARS:
        for company in ["C001", "C002", "C003"]:
            subset = eligible.loc[
                eligible["fiscal_year"].eq(year) & eligible["company_code"].eq(company)
            ].head(2)
            for idx, (_, row) in enumerate(subset.iterrows(), start=1):
                controls.append(
                    {
                        "negative_control_id": f"DP-NC-V99-{year}-{company}-{idx:03d}",
                        "fiscal_year": year,
                        "document_id": row["document_id"],
                        "company_code": company,
                        "partner_key": row["partner_key"],
                        "scenario": "normal_vendor_repeat_or_scheduled_payment",
                        "expected_l202_confirmed_anomaly": False,
                    }
                )
    return pd.DataFrame(controls)


def _write_pairs(pairs: pd.DataFrame, controls: pd.DataFrame) -> None:
    pairs.to_csv(LABELS / "duplicate_payment_pairs.csv", index=False)
    _write_json_records(LABELS / "duplicate_payment_pairs.json", pairs)
    controls.to_csv(LABELS / "duplicate_payment_negative_controls.csv", index=False)
    _write_json_records(LABELS / "duplicate_payment_negative_controls.json", controls)
    for year in YEARS:
        y_pairs = pairs.loc[pairs["fiscal_year"].eq(year)].copy()
        y_pairs.to_csv(LABELS / f"duplicate_payment_pairs_{year}.csv", index=False)
        _write_json_records(LABELS / f"duplicate_payment_pairs_{year}.json", y_pairs)
        y_controls = controls.loc[controls["fiscal_year"].eq(year)].copy()
        y_controls.to_csv(LABELS / f"duplicate_payment_negative_controls_{year}.csv", index=False)
        _write_json_records(LABELS / f"duplicate_payment_negative_controls_{year}.json", y_controls)


def _write_rule_truth(pairs: pd.DataFrame) -> None:
    truth = pairs[
        ["expected_l202_label_document_id", "fiscal_year", "company_code"]
    ].rename(columns={"expected_l202_label_document_id": "document_id"})
    truth["rule_id"] = "L2-02"
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "same payment appears to be paid again"
    truth["evaluation_unit"] = "document_pair"
    truth.to_csv(LABELS / "rule_truth_L2_02.csv", index=False)
    _write_json_records(LABELS / "rule_truth_L2_02.json", truth)
    for year in YEARS:
        y_truth = truth.loc[truth["fiscal_year"].eq(year)].copy()
        y_truth.to_csv(LABELS / f"rule_truth_L2_02_{year}.csv", index=False)
        _write_json_records(LABELS / f"rule_truth_L2_02_{year}.json", y_truth)
    combined = pd.read_csv(LABELS / "rule_truth.csv", low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne("L2-02")].copy()
    combined = pd.concat([combined, truth], ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)


def _replace_anomaly_labels(pairs: pd.DataFrame) -> None:
    path = LABELS / "anomaly_labels.csv"
    labels = pd.read_csv(path, low_memory=False)
    old = labels.loc[labels["anomaly_type"].eq("DuplicatePayment")].copy().reset_index(drop=True)
    if len(old) != len(pairs):
        raise SystemExit(f"DuplicatePayment count changed: old={len(old)} new={len(pairs)}")
    keep = labels.loc[~labels["anomaly_type"].eq("DuplicatePayment")].copy()
    new_rows = old.copy()
    for i, row in pairs.reset_index(drop=True).iterrows():
        meta = {
            "duplicate_payment_pair_id": row["duplicate_payment_pair_id"],
            "original_document_id": row["original_document_id"],
            "variant": row["variant"],
            "day_gap": int(row["day_gap"]),
            "patch_version": "v99",
        }
        new_rows.loc[i, "document_id"] = row["duplicate_document_id"]
        new_rows.loc[i, "document_type"] = row.get("document_type", "KZ")
        new_rows.loc[i, "company_code"] = row["company_code"]
        new_rows.loc[i, "anomaly_date"] = row["duplicate_posting_date"]
        new_rows.loc[i, "description"] = (
            f"Repeated P2P/{row.get('document_type', 'KZ')} vendor payment pair ({row['variant']})"
        )
        new_rows.loc[i, "related_entities"] = json.dumps([row["duplicate_document_number"]], ensure_ascii=False)
        new_rows.loc[i, "monetary_impact"] = row.get("amount")
        new_rows.loc[i, "structured_strategy_json"] = json.dumps(meta, ensure_ascii=False)
        new_rows.loc[i, "causal_reason_json"] = json.dumps({"EntityTargeting": {"target_type": "Document", "target_id": row["duplicate_document_number"]}}, ensure_ascii=False)
        new_rows.loc[i, "metadata_json"] = json.dumps(meta, ensure_ascii=False)
    rebuilt = pd.concat([keep, new_rows], ignore_index=True)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "anomaly_labels.json", rebuilt)
    _write_jsonl_records(LABELS / "anomaly_labels.jsonl", rebuilt)


def _write_manifest(pairs: pd.DataFrame, controls: pd.DataFrame, candidates: pd.DataFrame) -> None:
    manifest = {
        "version": "v99_candidate",
        "base_version": "v98_candidate",
        "patch": "duplicate_payment_company_diversity",
        "candidate_pairs_found": int(len(candidates)),
        "selected_pairs": int(len(pairs)),
        "negative_controls": int(len(controls)),
        "by_company": {str(k): int(v) for k, v in pairs["company_code"].value_counts().items()},
        "by_year": {str(k): int(v) for k, v in pairs["fiscal_year"].value_counts().sort_index().items()},
        "by_variant": {str(k): int(v) for k, v in pairs["variant"].value_counts().items()},
        "contract": "selected pairs are naturally reconstructable in the current journal; journal rows are not mutated",
    }
    (LABELS / "V99_DUPLICATE_PAYMENT_DIVERSITY.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V99_CANDIDATE.md").write_text(
        "# DataSynth v99 Candidate\n\n"
        "Base: `datasynth_v98_candidate`.\n\n"
        "Patch: rebalance DuplicatePayment pairs across companies using naturally reconstructable journal pairs.\n\n"
        f"```json\n{json.dumps(manifest, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    docs = _document_summary()
    candidates = _candidate_pairs(docs)
    pairs = _select_pairs(candidates)
    selected_docs = set(pairs["original_document_id"].astype(str)) | set(pairs["duplicate_document_id"].astype(str))
    controls = _negative_controls(docs, selected_docs)
    _write_pairs(pairs, controls)
    _write_rule_truth(pairs)
    _replace_anomaly_labels(pairs)
    _write_manifest(pairs, controls, candidates)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "candidate_pairs_found": int(len(candidates)),
                "selected_pairs": int(len(pairs)),
                "by_company": {
                    str(k): int(v) for k, v in pairs["company_code"].value_counts().items()
                },
                "by_year": {
                    str(k): int(v) for k, v in pairs["fiscal_year"].value_counts().sort_index().items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
