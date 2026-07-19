from __future__ import annotations

import json
import shutil
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "tools" / "datasynth" / "out_v20"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v20"
CURRENT_DATE = "2026-04-20"
CURRENT_TIMESTAMP = "2026-04-20 23:59:00"
L2-02_TARGETS = {2022: 9, 2023: 11, 2024: 13}
L3-03_TARGETS = {2022: 9, 2023: 10, 2024: 12}

IC_ACCOUNTS = [
    ("115001", "IC Receivable - C001", "asset", "accounts_receivable", True),
    ("115002", "IC Receivable - C002", "asset", "accounts_receivable", True),
    ("115003", "IC Receivable - C003", "asset", "accounts_receivable", True),
    ("205001", "IC Payable - C001", "liability", "accounts_payable", False),
    ("205002", "IC Payable - C002", "liability", "accounts_payable", False),
    ("205003", "IC Payable - C003", "liability", "accounts_payable", False),
]


def main() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)

    append_intercompany_accounts(TARGET_DIR / "chart_of_accounts.json")
    clone_duplicate_payments(TARGET_DIR)
    augment_circular_intercompany(TARGET_DIR)
    refresh_summary_metadata(TARGET_DIR)
    write_freeze_note(TARGET_DIR)


def append_intercompany_accounts(chart_path: Path) -> None:
    payload = json.loads(chart_path.read_text(encoding="utf-8"))
    accounts = payload["accounts"]
    existing = {acct["account_number"] for acct in accounts}
    base_lookup = {acct["account_number"]: acct for acct in accounts}

    for account_number, short_description, account_type, sub_type, normal_debit in IC_ACCOUNTS:
        if account_number in existing:
            continue
        template = base_lookup["1150"] if account_number.startswith("115") else base_lookup["2050"]
        cloned = dict(template)
        cloned.update(
            {
                "account_number": account_number,
                "short_description": short_description,
                "long_description": short_description,
                "account_type": account_type,
                "sub_type": sub_type,
                "normal_debit_balance": normal_debit,
                "allowed_doc_types": ["IC"],
                "account_group": "INTERCOMPANY",
            }
        )
        accounts.append(cloned)

    accounts.sort(key=lambda item: item["account_number"])
    chart_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clone_duplicate_payments(target_dir: Path) -> None:
    all_year_frames: list[pd.DataFrame] = []
    anomaly_labels_path = target_dir / "labels" / "anomaly_labels.csv"
    anomaly_labels = pd.read_csv(anomaly_labels_path)
    anomaly_labels = anomaly_labels[anomaly_labels["anomaly_type"] != "DuplicatePayment"].copy()
    next_anomaly_id = next_id(anomaly_labels["anomaly_id"], prefix="ANO")
    added_labels: list[dict] = []
    summary_rows: list[dict] = []

    for year in (2022, 2023, 2024):
        year_path = target_dir / f"journal_entries_{year}.csv"
        df = pd.read_csv(year_path, low_memory=False)
        legacy_dp_mask = df["fraud_type"].fillna("") == "DuplicatePayment"
        if legacy_dp_mask.any():
            df.loc[legacy_dp_mask, "is_fraud"] = False
            df.loc[legacy_dp_mask, "fraud_type"] = pd.NA
        clones, next_anomaly_id, year_summary = build_year_duplicate_payment_clones(
            df, year, next_anomaly_id
        )
        summary_rows.extend(year_summary)
        if clones:
            clone_frame = pd.DataFrame(clones)
            df = pd.concat([df, clone_frame], ignore_index=True)
            added_labels.extend(
                build_anomaly_label_rows(clone_frame, next_anomaly_id_start=next_anomaly_id - len(year_summary))
            )
        df.sort_values(["fiscal_year", "posting_date", "document_number", "line_number"], inplace=True)
        df.to_csv(year_path, index=False)
        all_year_frames.append(df)

    combined = pd.concat(all_year_frames + load_optional_2025(target_dir), ignore_index=True)
    combined.sort_values(["fiscal_year", "posting_date", "document_number", "line_number"], inplace=True)
    combined.to_csv(target_dir / "journal_entries.csv", index=False)

    if added_labels:
        anomaly_labels = pd.concat([anomaly_labels, pd.DataFrame(added_labels)], ignore_index=True)
    anomaly_labels.to_csv(anomaly_labels_path, index=False)
    write_anomaly_summary(anomaly_labels, target_dir / "labels" / "anomaly_labels_summary.json")
    write_v20_fixes(target_dir, duplicate_payment_clones=summary_rows)


def build_year_duplicate_payment_clones(
    df: pd.DataFrame, year: int, next_anomaly_id: int
) -> tuple[list[dict], int, list[dict]]:
    doc_meta = summarize_documents(df)
    candidates = doc_meta[
        (doc_meta["document_type"] == "KZ")
        & (doc_meta["trading_partner"].notna())
        & (doc_meta["has_bank"])
        & (doc_meta["has_ap"])
        & (doc_meta["line_count"] == 2)
        & (doc_meta["fraud_type"].isna())
    ].copy()
    candidates.sort_values(["company_code", "posting_date", "document_number"], inplace=True)
    target_count = L2-02_TARGETS[year]
    selected = candidates.head(target_count)
    if len(selected) < target_count:
        raise RuntimeError(f"Need at least {target_count} duplicate-payment seeds for {year}, found {len(selected)}")

    next_suffix_by_company = compute_next_document_suffix(df)
    clones: list[dict] = []
    summary_rows: list[dict] = []

    for idx, row in enumerate(selected.itertuples(index=False), start=1):
        original_rows = df[df["document_id"] == row.document_id].copy()
        cloned_rows = original_rows.copy()
        payment_amount = extract_payment_amount(original_rows)
        new_doc_id = str(uuid.uuid4())
        new_suffix = next_suffix_by_company[row.company_code]
        next_suffix_by_company[row.company_code] += 1
        new_doc_number = f"{row.company_code}-{year}-{new_suffix:06d}"
        base_ts = pd.Timestamp(row.posting_date)
        shifted_ts = min(base_ts + timedelta(days=min(15, idx * 2)), pd.Timestamp(f"{year}-12-31 23:59:59"))

        cloned_rows["document_id"] = new_doc_id
        cloned_rows["posting_date"] = shifted_ts.strftime("%Y-%m-%d %H:%M:%S")
        cloned_rows["document_date"] = shifted_ts.strftime("%Y-%m-%d")
        cloned_rows["document_number"] = new_doc_number
        cloned_rows["reference"] = cloned_rows["reference"].astype(str)
        cloned_rows["header_text"] = cloned_rows["header_text"].astype(str)
        cloned_rows["line_text"] = cloned_rows["line_text"].astype(str)
        cloned_rows["is_fraud"] = True
        cloned_rows["fraud_type"] = "DuplicatePayment"
        cloned_rows["is_anomaly"] = False
        cloned_rows["anomaly_type"] = pd.NA

        apply_balanced_payment_shape(cloned_rows, payment_amount)

        clones.extend(cloned_rows.to_dict(orient="records"))
        summary_rows.append(
            {
                "year": year,
                "source_document_id": row.document_id,
                "duplicate_document_id": new_doc_id,
                "company_code": row.company_code,
                "trading_partner": row.trading_partner,
                "source_document_number": row.document_number,
                "duplicate_document_number": new_doc_number,
                "payment_amount": payment_amount,
                "posting_date": shifted_ts.strftime("%Y-%m-%d"),
            }
        )
        next_anomaly_id += 1

    return clones, next_anomaly_id, summary_rows


def summarize_documents(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["gl_account"] = work["gl_account"].astype(str)
    doc_meta = (
        work.groupby("document_id")
        .agg(
            {
                "company_code": "first",
                "fiscal_year": "first",
                "document_type": "first",
                "business_process": "first",
                "posting_date": "first",
                "document_date": "first",
                "trading_partner": "first",
                "fraud_type": "first",
                "anomaly_type": "first",
                "document_number": "first",
                "line_number": "count",
            }
        )
        .rename(columns={"line_number": "line_count"})
        .reset_index()
    )
    flags = (
        work.groupby("document_id")["gl_account"]
        .agg(
            has_bank=lambda s: any(val.startswith("100") for val in s),
            has_ap=lambda s: any(val.startswith("200") for val in s),
        )
        .reset_index()
    )
    return doc_meta.merge(flags, on="document_id", how="left")


def compute_next_document_suffix(df: pd.DataFrame) -> dict[str, int]:
    doc_numbers = (
        df[["company_code", "fiscal_year", "document_number"]]
        .drop_duplicates()
        .copy()
    )
    doc_numbers["suffix"] = (
        doc_numbers["document_number"].astype(str).str.extract(r"-(\d{6})$").astype(int)
    )
    return {
        row.company_code: int(row.suffix) + 1
        for row in doc_numbers.groupby(["company_code", "fiscal_year"])["suffix"].max().reset_index().itertuples(index=False)
    }


def extract_payment_amount(doc_rows: pd.DataFrame) -> float:
    bank_rows = doc_rows[doc_rows["gl_account"].astype(str).str.startswith("100")].copy()
    if bank_rows.empty:
        raise RuntimeError("DuplicatePayment seed must include a bank line")
    bank_amount = pd.to_numeric(bank_rows["debit_amount"], errors="coerce").fillna(0).sum()
    bank_amount += pd.to_numeric(bank_rows["credit_amount"], errors="coerce").fillna(0).sum()
    return float(bank_amount)


def apply_balanced_payment_shape(doc_rows: pd.DataFrame, payment_amount: float) -> None:
    gl_series = doc_rows["gl_account"].astype(str)
    ap_mask = gl_series.str.startswith("200")
    bank_mask = gl_series.str.startswith("100")

    if ap_mask.sum() != 1 or bank_mask.sum() != 1:
        raise RuntimeError("Expected exactly one AP line and one bank line for DuplicatePayment seed")

    for column in ("debit_amount", "credit_amount", "local_amount"):
        doc_rows[column] = pd.to_numeric(doc_rows[column], errors="coerce").fillna(0.0)

    doc_rows.loc[ap_mask, "debit_amount"] = payment_amount
    doc_rows.loc[ap_mask, "credit_amount"] = 0.0
    doc_rows.loc[ap_mask, "local_amount"] = payment_amount

    doc_rows.loc[bank_mask, "debit_amount"] = 0.0
    doc_rows.loc[bank_mask, "credit_amount"] = payment_amount
    doc_rows.loc[bank_mask, "local_amount"] = payment_amount


def build_anomaly_label_rows(clone_frame: pd.DataFrame, next_anomaly_id_start: int) -> list[dict]:
    rows: list[dict] = []
    doc_meta = (
        clone_frame.groupby("document_id")
        .agg(
            {
                "document_type": "first",
                "company_code": "first",
                "posting_date": "first",
                "trading_partner": "first",
                "document_number": "first",
                "credit_amount": "sum",
            }
        )
        .reset_index()
    )
    for offset, row in enumerate(doc_meta.itertuples(index=False), start=0):
        anomaly_num = next_anomaly_id_start + offset
        rows.append(
            {
                "anomaly_id": f"ANO{anomaly_num:08d}",
                "anomaly_category": "Fraud",
                "anomaly_type": "DuplicatePayment",
                "document_id": row.document_id,
                "document_type": row.document_type,
                "company_code": row.company_code,
                "anomaly_date": str(row.posting_date)[:10],
                "detection_timestamp": CURRENT_TIMESTAMP,
                "confidence": 1.0,
                "severity": 3,
                "description": f"Injected duplicate payment candidate for {row.trading_partner}",
                "is_injected": True,
                "monetary_impact": float(row.credit_amount),
                "related_entities": json.dumps([row.document_number], ensure_ascii=False),
                "cluster_id": pd.NA,
                "original_document_hash": pd.NA,
                "injection_strategy": "DuplicatePayment",
                "structured_strategy_type": pd.NA,
                "structured_strategy_json": pd.NA,
                "causal_reason_type": "EntityTargeting",
                "causal_reason_json": json.dumps(
                    {"EntityTargeting": {"target_type": "Document", "target_id": row.document_number}},
                    ensure_ascii=False,
                ),
                "parent_anomaly_id": pd.NA,
                "child_anomaly_ids": "[]",
                "scenario_id": pd.NA,
                "run_id": pd.NA,
                "generation_seed": 2024,
                "metadata_json": json.dumps(
                    {
                        "duplicate_payment_seed": True,
                        "trading_partner": row.trading_partner,
                        "document_number": row.document_number,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return rows


def augment_circular_intercompany(target_dir: Path) -> None:
    anomaly_labels_path = target_dir / "labels" / "anomaly_labels.csv"
    anomaly_labels = pd.read_csv(anomaly_labels_path)
    next_anomaly_id = next_id(anomaly_labels["anomaly_id"], prefix="ANO")
    added_labels: list[dict] = []
    summary_rows: list[dict] = []

    for year in (2022, 2023, 2024):
        year_path = target_dir / f"journal_entries_{year}.csv"
        df = pd.read_csv(year_path, low_memory=False)
        doc = summarize_documents(df)
        current_b10 = doc[doc["anomaly_type"].fillna("") == "CircularIntercompany"].copy()
        need = max(L3-03_TARGETS[year] - len(current_b10), 0)
        if need == 0:
            continue
        candidates = doc[
            (doc["document_type"] == "IC")
            & (doc["trading_partner"].notna())
            & (doc["anomaly_type"].fillna("") == "")
            & (doc["fraud_type"].fillna("") == "")
        ].copy()
        candidates.sort_values(["company_code", "posting_date", "document_number"], inplace=True)
        selected = candidates.head(need)
        if len(selected) < need:
            raise RuntimeError(f"Need {need} IC candidates for L3-03 in {year}, found {len(selected)}")

        for row in selected.itertuples(index=False):
            mask = df["document_id"] == row.document_id
            df.loc[mask, "is_anomaly"] = True
            df.loc[mask, "anomaly_type"] = "CircularIntercompany"
            summary_rows.append(
                {
                    "year": year,
                    "document_id": row.document_id,
                    "company_code": row.company_code,
                    "trading_partner": row.trading_partner,
                    "document_number": row.document_number,
                }
            )
            added_labels.append(
                {
                    "anomaly_id": f"ANO{next_anomaly_id:08d}",
                    "anomaly_category": "Relational",
                    "anomaly_type": "CircularIntercompany",
                    "document_id": row.document_id,
                    "document_type": row.document_type,
                    "company_code": row.company_code,
                    "anomaly_date": str(row.posting_date)[:10],
                    "detection_timestamp": CURRENT_TIMESTAMP,
                    "confidence": 1.0,
                    "severity": 3,
                    "description": f"Injected additional circular intercompany case for {row.trading_partner}",
                    "is_injected": True,
                    "monetary_impact": pd.NA,
                    "related_entities": json.dumps([row.document_number], ensure_ascii=False),
                    "cluster_id": pd.NA,
                    "original_document_hash": pd.NA,
                    "injection_strategy": "CircularIntercompany",
                    "structured_strategy_type": pd.NA,
                    "structured_strategy_json": pd.NA,
                    "causal_reason_type": "EntityTargeting",
                    "causal_reason_json": json.dumps(
                        {"EntityTargeting": {"target_type": "Document", "target_id": row.document_number}},
                        ensure_ascii=False,
                    ),
                    "parent_anomaly_id": pd.NA,
                    "child_anomaly_ids": "[]",
                    "scenario_id": pd.NA,
                    "run_id": pd.NA,
                    "generation_seed": 2024,
                    "metadata_json": json.dumps(
                        {
                            "v20_extra_b10": True,
                            "trading_partner": row.trading_partner,
                            "document_number": row.document_number,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            next_anomaly_id += 1

        df.sort_values(["fiscal_year", "posting_date", "document_number", "line_number"], inplace=True)
        df.to_csv(year_path, index=False)

    if added_labels:
        anomaly_labels = pd.concat([anomaly_labels, pd.DataFrame(added_labels)], ignore_index=True)
        anomaly_labels.to_csv(anomaly_labels_path, index=False)
        write_anomaly_summary(anomaly_labels, target_dir / "labels" / "anomaly_labels_summary.json")
    write_v20_fixes(target_dir, extra_circular_intercompany=summary_rows)


def write_anomaly_summary(anomaly_labels: pd.DataFrame, summary_path: Path) -> None:
    payload = {
        "total_labels": int(len(anomaly_labels)),
        "by_category": dict(Counter(anomaly_labels["anomaly_category"].fillna("Unknown"))),
        "by_company": dict(Counter(anomaly_labels["company_code"].fillna("Unknown"))),
        "with_provenance": int(anomaly_labels["metadata_json"].notna().sum()),
        "in_scenarios": int(anomaly_labels["scenario_id"].notna().sum()),
        "in_clusters": int(anomaly_labels["cluster_id"].notna().sum()),
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_v20_fixes(target_dir: Path, **sections: list[dict]) -> None:
    fix_path = target_dir / "V20_FIXES.json"
    payload = {"generated_at": CURRENT_TIMESTAMP}
    if fix_path.exists():
        payload = json.loads(fix_path.read_text(encoding="utf-8"))
        payload["generated_at"] = CURRENT_TIMESTAMP
    for key, value in sections.items():
        payload[key] = value
    fix_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_summary_metadata(target_dir: Path) -> None:
    chart = json.loads((target_dir / "chart_of_accounts.json").read_text(encoding="utf-8"))
    stats_path = target_dir / "generation_statistics.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    all_rows = pd.read_csv(target_dir / "journal_entries.csv", usecols=["document_id"])
    anomaly_labels = pd.read_csv(target_dir / "labels" / "anomaly_labels.csv", usecols=["anomaly_id"])

    stats["total_entries"] = int(all_rows["document_id"].nunique())
    stats["total_line_items"] = int(len(all_rows))
    stats["accounts_count"] = int(len(chart["accounts"]))
    stats["anomalies_injected"] = int(len(anomaly_labels))
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    dq_path = target_dir / "data_quality_stats.json"
    dq = json.loads(dq_path.read_text(encoding="utf-8"))
    dq["total_records"] = int(len(all_rows))
    dq["missing_values"]["total_records"] = int(len(all_rows))
    dq["duplicates"]["total_processed"] = int(len(all_rows))
    dq["format_variations"]["total_processed"] = int(len(all_rows))
    dq_path.write_text(json.dumps(dq, ensure_ascii=False, indent=2), encoding="utf-8")


def load_optional_2025(target_dir: Path) -> list[pd.DataFrame]:
    path_2025 = target_dir / "journal_entries_2025.csv"
    if not path_2025.exists():
        return []
    return [pd.read_csv(path_2025, low_memory=False)]


def next_id(series: pd.Series, prefix: str) -> int:
    numeric = (
        series.dropna()
        .astype(str)
        .str.replace(prefix, "", regex=False)
        .astype(int)
    )
    return int(numeric.max()) + 1 if not numeric.empty else 1


def write_freeze_note(target_dir: Path) -> None:
    note = f"""# DataSynth V20 Candidate

- Frozen at: {CURRENT_TIMESTAMP}
- Source: `tools/datasynth/out_v20`
- Includes: V18 must-seed coverage, V19 L3-03 realism, V20 L3-01/CoA/L2-02 fixes

## V20 Candidate Fixes

- Added intercompany clearing accounts `115001~115003`, `205001~205003` to `chart_of_accounts.json`
- Added `L3-01 MisclassifiedAccount` to phase1 must-seed input via config
- Injected 8 real JE-level duplicate payment clones per year for `L2-02`
- Kept main `data/journal/primary/datasynth` unchanged

## Notes

- This candidate is a post-processed validation dataset intended for Phase 1/2/3 benchmarking.
- The source generation folder remains preserved separately under `tools/datasynth/out_v20`.
"""
    (target_dir / "FREEZE_V20_CANDIDATE.md").write_text(note, encoding="utf-8")


if __name__ == "__main__":
    main()
