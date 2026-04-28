"""Build DataSynth v58 by restoring required L1-09 and L2-02 truth.

This patch is intentionally applied on top of the current production DataSynth
baseline. It does not regenerate the corpus.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth"
DEFAULT_OUTPUT = ROOT / "data" / "journal" / "primary" / "datasynth_v58_candidate"
YEARS = (2022, 2023, 2024)
L109_YEAR_TARGETS = {2022: 7, 2023: 8, 2024: 11}
L202_YEAR_TARGETS = {2022: 9, 2023: 11, 2024: 13}
LABEL_TIMESTAMP = "2026-04-26 13:30:00"


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def records_for_json(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{key: clean_value(value) for key, value in row.items()} for row in df.to_dict(orient="records")]


def copy_source(source: Path, output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)


def document_frame(df: pd.DataFrame) -> pd.DataFrame:
    group = df.groupby("document_id", as_index=False)
    agg: dict[str, tuple[str, str]] = {}
    for column in [
        "fiscal_year",
        "company_code",
        "document_type",
        "document_date",
        "source",
        "business_process",
        "approved_by",
        "approval_date",
        "document_number",
        "reference",
        "header_text",
        "auxiliary_account_number",
        "trading_partner",
        "auxiliary_account_label",
    ]:
        if column in df.columns:
            agg[column] = (column, "first")
    if "posting_date" in df.columns:
        agg["posting_date"] = ("posting_date", "min")
    for column in ["debit_amount", "credit_amount", "local_amount"]:
        if column in df.columns:
            agg[column] = (column, "sum")
    agg["row_count"] = ("document_id", "size")
    return group.agg(**agg)


def next_anomaly_ids(labels: pd.DataFrame, count: int) -> list[str]:
    numbers = labels["anomaly_id"].fillna("").astype(str).str.extract(r"ANO(\d+)")[0].dropna()
    max_num = int(numbers.astype(int).max()) if not numbers.empty else 0
    return [f"ANO{max_num + offset:08d}" for offset in range(1, count + 1)]


def write_anomaly_labels(labels_dir: Path, labels: pd.DataFrame) -> None:
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = records_for_json(labels)
    (labels_dir / "anomaly_labels.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "total_labels": int(len(labels)),
        "by_anomaly_type": {str(k): int(v) for k, v in labels["anomaly_type"].value_counts().to_dict().items()},
        "by_category": {str(k): int(v) for k, v in labels["anomaly_category"].value_counts().to_dict().items()},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_sidecar_family(labels_dir: Path, stem: str, rows: list[dict[str, Any]]) -> None:
    df = pd.DataFrame(rows)
    df.to_csv(labels_dir / f"{stem}.csv", index=False)
    (labels_dir / f"{stem}.json").write_text(
        json.dumps(records_for_json(df), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if "fiscal_year" not in df.columns:
        return
    for year in YEARS:
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
        subset.to_csv(labels_dir / f"{stem}_{year}.csv", index=False)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(records_for_json(subset), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def write_year_files(output: Path, df: pd.DataFrame) -> None:
    df.to_csv(output / "journal_entries.csv", index=False)
    for year in YEARS:
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
        subset.to_csv(output / f"journal_entries_{year}.csv", index=False)


def make_label(
    *,
    anomaly_id: str,
    anomaly_type: str,
    row: pd.Series,
    category: str,
    severity: int,
    description: str,
    metadata: dict[str, Any],
    columns: list[str],
) -> dict[str, Any]:
    document_number = clean_value(row.get("document_number"))
    record = {
        "anomaly_id": anomaly_id,
        "anomaly_category": category,
        "anomaly_type": anomaly_type,
        "document_id": row["document_id"],
        "document_type": row.get("document_type"),
        "company_code": row.get("company_code"),
        "anomaly_date": pd.to_datetime(row.get("posting_date")).strftime("%Y-%m-%d"),
        "detection_timestamp": LABEL_TIMESTAMP,
        "confidence": 1.0,
        "severity": severity,
        "description": description,
        "is_injected": True,
        "monetary_impact": clean_value(row.get("local_amount")),
        "related_entities": json.dumps([document_number], ensure_ascii=False),
        "cluster_id": None,
        "original_document_hash": None,
        "injection_strategy": anomaly_type,
        "structured_strategy_type": None,
        "structured_strategy_json": None,
        "causal_reason_type": "EntityTargeting",
        "causal_reason_json": json.dumps(
            {"EntityTargeting": {"target_type": "Document", "target_id": document_number}},
            ensure_ascii=False,
        ),
        "parent_anomaly_id": None,
        "child_anomaly_ids": "[]",
        "scenario_id": None,
        "run_id": None,
        "generation_seed": None,
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
    }
    return {column: record.get(column) for column in columns}


def restore_l109(df: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    labeled_docs = set(labels["document_id"].dropna().astype(str))
    doc = document_frame(df)
    approved = doc["approved_by"].fillna("").astype(str).str.strip().ne("")
    has_date = doc["approval_date"].fillna("").astype(str).str.strip().ne("")
    eligible = doc.loc[
        ~doc["document_id"].astype(str).isin(labeled_docs)
        & approved
        & has_date
        & doc["fiscal_year"].isin(YEARS)
        & doc["source"].isin(["manual", "adjustment"])
        & doc["row_count"].between(2, 8)
    ].copy()
    eligible["_sort"] = eligible["company_code"].astype(str) + ":" + eligible["posting_date"].astype(str) + ":" + eligible["document_id"].astype(str)
    eligible = eligible.sort_values(["fiscal_year", "business_process", "_sort"])

    cases: list[dict[str, Any]] = []
    chosen_rows: list[pd.Series] = []
    for year, target in L109_YEAR_TARGETS.items():
        pool = eligible.loc[eligible["fiscal_year"].eq(year)]
        process_limits = {
            2022: {"P2P": 2, "O2C": 1, "R2R": 1, "H2R": 1, "TRE": 1, "A2R": 1},
            2023: {"P2P": 2, "O2C": 2, "R2R": 1, "H2R": 1, "TRE": 1, "A2R": 1},
            2024: {"P2P": 3, "O2C": 2, "R2R": 2, "H2R": 1, "TRE": 2, "A2R": 1},
        }[year]
        selected = []
        used: set[str] = set()
        for process, limit in process_limits.items():
            part = pool.loc[pool["business_process"].eq(process)].head(limit)
            selected.append(part)
            used.update(part["document_id"].astype(str))
        picked = pd.concat(selected, ignore_index=True) if selected else pool.head(0)
        if len(picked) < target:
            extra = pool.loc[~pool["document_id"].astype(str).isin(used)].head(target - len(picked))
            picked = pd.concat([picked, extra], ignore_index=True)
        if len(picked) < target:
            raise RuntimeError(f"not enough L1-09 candidates for {year}: {len(picked)} < {target}")
        chosen_rows.extend([row for _, row in picked.head(target).iterrows()])

    label_ids = next_anomaly_ids(labels, len(chosen_rows))
    label_rows: list[dict[str, Any]] = []
    scenario_cycle = ["workflow_timestamp_drop", "manual_log_gap", "approval_archive_missing", "interface_sync_loss"]
    for idx, row in enumerate(chosen_rows):
        doc_id = str(row["document_id"])
        scenario = scenario_cycle[idx % len(scenario_cycle)]
        original_approval_date = clean_value(row.get("approval_date"))
        df.loc[df["document_id"].astype(str).eq(doc_id), "approval_date"] = None
        cases.append(
            {
                "approval_date_missing_case_id": f"ADM-V58-{idx + 1:03d}",
                "document_id": doc_id,
                "document_number": row.get("document_number"),
                "fiscal_year": int(row["fiscal_year"]),
                "company_code": row.get("company_code"),
                "business_process": row.get("business_process"),
                "source": row.get("source"),
                "approved_by": row.get("approved_by"),
                "original_approval_date": original_approval_date,
                "scenario": scenario,
                "truth_basis": "approver retained while approval timestamp is missing",
            }
        )
        label_rows.append(
            make_label(
                anomaly_id=label_ids[idx],
                anomaly_type="ApprovalDateMissing",
                row=row,
                category="ProcessIssue",
                severity=3,
                description=f"Approver present but approval_date is missing ({scenario})",
                metadata={
                    "approval_date_missing_case_id": f"ADM-V58-{idx + 1:03d}",
                    "approved_by": row.get("approved_by"),
                    "original_approval_date": original_approval_date,
                    "scenario": scenario,
                    "patch_version": "v58",
                },
                columns=list(labels.columns),
            )
        )
    return df, cases, label_rows


def payment_doc_candidates(doc: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    labeled_docs = set(labels["document_id"].dropna().astype(str))
    partner = doc["auxiliary_account_number"].fillna("").astype(str).str.strip()
    has_partner = partner.ne("") & partner.ne("None") & partner.str.startswith("V-")
    return doc.loc[
        ~doc["document_id"].astype(str).isin(labeled_docs)
        & doc["fiscal_year"].isin(YEARS)
        & doc["business_process"].eq("P2P")
        & doc["row_count"].between(2, 6)
        & has_partner
        & doc["local_amount"].fillna(0).abs().gt(0)
    ].copy()


def restore_l202(df: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    doc = document_frame(df)
    candidates = payment_doc_candidates(doc, labels)
    candidates["_date"] = pd.to_datetime(candidates["posting_date"], errors="coerce")
    candidates["_sort"] = candidates["company_code"].astype(str) + ":" + candidates["auxiliary_account_number"].astype(str) + ":" + candidates["document_id"].astype(str)
    candidates = candidates.sort_values(["fiscal_year", "_sort"])

    pairs: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    duplicate_label_docs: list[pd.Series] = []
    used_docs: set[str] = set()
    variant_cycle = ["exact", "reference_blank", "reference_variant", "date_shifted", "amount_rounding"]
    gaps = [3, 6, 9, 12, 16, 21, 28]

    for year, target in L202_YEAR_TARGETS.items():
        pool = candidates.loc[candidates["fiscal_year"].eq(year)].copy()
        pool = pool.loc[~pool["document_id"].astype(str).isin(used_docs)]
        if len(pool) < target * 2:
            raise RuntimeError(f"not enough L2-02 candidates for {year}: {len(pool)} < {target * 2}")
        cursor = 0
        made = 0
        while made < target and cursor + 1 < len(pool):
            original = pool.iloc[cursor]
            duplicate = pool.iloc[cursor + 1]
            cursor += 2
            original_id = str(original["document_id"])
            duplicate_id = str(duplicate["document_id"])
            if original_id in used_docs or duplicate_id in used_docs:
                continue
            used_docs.update({original_id, duplicate_id})
            sequence = made + 1
            pair_id = f"DP-V58-{year}-{sequence:03d}"
            variant = variant_cycle[(sequence + year) % len(variant_cycle)]
            gap = gaps[(sequence + year) % len(gaps)]
            original_date = pd.to_datetime(original["posting_date"], errors="coerce")
            duplicate_date = original_date + pd.Timedelta(days=gap)
            if duplicate_date.year != year:
                duplicate_date = original_date - pd.Timedelta(days=min(gap, 10))
            reference = str(original.get("reference") or f"PAY-{year}-{made:04d}").strip()
            if not reference or reference.lower() == "nan":
                reference = f"PAY-{year}-{made:04d}"
            duplicate_reference = reference
            if variant == "reference_blank":
                duplicate_reference = ""
            elif variant == "reference_variant":
                duplicate_reference = f"{reference}-R"

            original_mask = df["document_id"].astype(str).eq(original_id)
            duplicate_mask = df["document_id"].astype(str).eq(duplicate_id)
            original_lines = df.loc[original_mask].sort_values("line_number").reset_index(drop=True)
            duplicate_indices = df.loc[duplicate_mask].sort_values("line_number").index.tolist()
            if len(duplicate_indices) != len(original_lines):
                continue
            made = sequence
            amount_factor = 1.0
            if variant == "amount_rounding":
                amount_factor = 1.0 + (0.001 * ((sequence % 3) + 1))

            for pos, target_idx in enumerate(duplicate_indices):
                source_line = original_lines.iloc[pos]
                for column in ["gl_account", "cost_center", "profit_center", "tax_code", "trading_partner", "auxiliary_account_number", "auxiliary_account_label"]:
                    if column in df.columns:
                        df.at[target_idx, column] = source_line.get(column)
                for amount_col in ["debit_amount", "credit_amount", "local_amount", "tax_amount"]:
                    if amount_col in df.columns:
                        value = pd.to_numeric(source_line.get(amount_col), errors="coerce")
                        if pd.notna(value):
                            df.at[target_idx, amount_col] = round(float(value) * amount_factor, 2)
                if "line_text" in df.columns:
                    df.at[target_idx, "line_text"] = str(source_line.get("line_text") or "").replace("매입", "지급")

            for doc_id, ref_value, post_date, role in [
                (original_id, reference, original_date, "original"),
                (duplicate_id, duplicate_reference, duplicate_date, "duplicate"),
            ]:
                mask = df["document_id"].astype(str).eq(doc_id)
                df.loc[mask, "document_type"] = "KZ"
                df.loc[mask, "business_process"] = "P2P"
                df.loc[mask, "source"] = "manual" if sequence % 4 else "adjustment"
                df.loc[mask, "reference"] = ref_value
                df.loc[mask, "posting_date"] = post_date.strftime("%Y-%m-%d %H:%M:%S")
                df.loc[mask, "document_date"] = post_date.strftime("%Y-%m-%d")
                df.loc[mask, "fraud_type"] = "DuplicatePayment"
                df.loc[mask, "is_fraud"] = True
                if "header_text" in df.columns:
                    suffix = "원 지급" if role == "original" else "중복 지급"
                    df.loc[mask, "header_text"] = f"P2P 지급 {suffix} - {original.get('auxiliary_account_label') or original.get('auxiliary_account_number')}"

            duplicate_doc = document_frame(df.loc[df["document_id"].astype(str).eq(duplicate_id)]).iloc[0]
            duplicate_label_docs.append(duplicate_doc)
            pairs.append(
                {
                    "duplicate_payment_pair_id": pair_id,
                    "fiscal_year": year,
                    "company_code": original.get("company_code"),
                    "original_document_id": original_id,
                    "duplicate_document_id": duplicate_id,
                    "original_document_number": original.get("document_number"),
                    "duplicate_document_number": duplicate.get("document_number"),
                    "partner_key": original.get("auxiliary_account_number"),
                    "variant": variant,
                    "original_posting_date": original_date.strftime("%Y-%m-%d"),
                    "duplicate_posting_date": duplicate_date.strftime("%Y-%m-%d"),
                    "day_gap": int(abs((duplicate_date - original_date).days)),
                    "reference_original": reference,
                    "reference_duplicate": duplicate_reference,
                    "truth_basis": "same P2P/KZ vendor payment repeated within 45 days",
                    "expected_l202_label_document_id": duplicate_id,
                }
            )
        if made < target:
            raise RuntimeError(f"only made {made} L2-02 pairs for {year}, expected {target}")

        control_pool = pool.loc[~pool["document_id"].astype(str).isin(used_docs)].head(max(6, target // 2))
        for idx, (_, row) in enumerate(control_pool.iterrows(), start=1):
            controls.append(
                {
                    "negative_control_id": f"DP-NC-V58-{year}-{idx:03d}",
                    "fiscal_year": year,
                    "document_id": row["document_id"],
                    "company_code": row.get("company_code"),
                    "partner_key": row.get("auxiliary_account_number"),
                    "scenario": "normal_vendor_repeat_or_scheduled_payment",
                    "expected_l202_confirmed_anomaly": False,
                }
            )

    label_ids = next_anomaly_ids(labels, len(duplicate_label_docs))
    label_rows = []
    for idx, row in enumerate(duplicate_label_docs):
        pair = pairs[idx]
        label_rows.append(
            make_label(
                anomaly_id=label_ids[idx],
                anomaly_type="DuplicatePayment",
                row=row,
                category="Fraud",
                severity=3,
                description=f"Repeated P2P/KZ vendor payment pair ({pair['variant']})",
                metadata={
                    "duplicate_payment_pair_id": pair["duplicate_payment_pair_id"],
                    "original_document_id": pair["original_document_id"],
                    "variant": pair["variant"],
                    "day_gap": pair["day_gap"],
                    "patch_version": "v58",
                },
                columns=list(labels.columns),
            )
        )
    return df, pairs, controls, label_rows


def verify_required_truth(output: Path) -> dict[str, Any]:
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv")
    vc = labels["anomaly_type"].value_counts()
    approval_cases = pd.read_csv(output / "labels" / "approval_date_missing_cases.csv")
    payment_pairs = pd.read_csv(output / "labels" / "duplicate_payment_pairs.csv")
    payment_controls = pd.read_csv(output / "labels" / "duplicate_payment_negative_controls.csv")
    by_year: dict[str, dict[str, int]] = {}
    orphan_total = 0
    for year in YEARS:
        df = pd.read_csv(output / f"journal_entries_{year}.csv", low_memory=False)
        doc = document_frame(df)
        approved = doc["approved_by"].fillna("").astype(str).str.strip().ne("")
        missing_date = doc["approval_date"].fillna("").astype(str).str.strip().eq("")
        orphan_docs = set(doc.loc[approved & missing_date, "document_id"].astype(str))
        l109_docs = set(approval_cases.loc[approval_cases["fiscal_year"].eq(year), "document_id"].astype(str))
        pair_docs = set(payment_pairs.loc[payment_pairs["fiscal_year"].eq(year), "duplicate_document_id"].astype(str))
        l202_label_docs = set(labels.loc[labels["anomaly_type"].eq("DuplicatePayment"), "document_id"].astype(str))
        orphan_total += len(orphan_docs)
        by_year[str(year)] = {
            "approval_missing_docs": len(orphan_docs),
            "approval_missing_case_docs": len(l109_docs),
            "approval_case_alignment_missing": len(orphan_docs.symmetric_difference(l109_docs)),
            "duplicate_payment_pairs": int(payment_pairs["fiscal_year"].eq(year).sum()),
            "duplicate_payment_label_docs": len(pair_docs & l202_label_docs),
            "duplicate_payment_negative_controls": int(payment_controls["fiscal_year"].eq(year).sum()),
        }
    failures = []
    if int(vc.get("ApprovalDateMissing", 0)) <= 0:
        failures.append("ApprovalDateMissing labels are missing")
    if int(vc.get("DuplicatePayment", 0)) <= 0:
        failures.append("DuplicatePayment labels are missing")
    if len(approval_cases) != int(vc.get("ApprovalDateMissing", 0)):
        failures.append("ApprovalDateMissing label count does not match sidecar")
    if len(payment_pairs) != int(vc.get("DuplicatePayment", 0)):
        failures.append("DuplicatePayment label count does not match pair sidecar")
    for year, values in by_year.items():
        if values["approval_case_alignment_missing"]:
            failures.append(f"L1-09 sidecar/date mismatch in {year}")
        if values["duplicate_payment_pairs"] != values["duplicate_payment_label_docs"]:
            failures.append(f"L2-02 pair/label mismatch in {year}")
    return {
        "approval_date_missing_labels": int(vc.get("ApprovalDateMissing", 0)),
        "duplicate_payment_labels": int(vc.get("DuplicatePayment", 0)),
        "approval_date_missing_sidecar_rows": int(len(approval_cases)),
        "duplicate_payment_pair_rows": int(len(payment_pairs)),
        "duplicate_payment_negative_control_rows": int(len(payment_controls)),
        "approved_by_with_missing_approval_date_docs": int(orphan_total),
        "by_year": by_year,
        "failures": failures,
    }


def update_manifest(output: Path, validation: dict[str, Any]) -> None:
    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    patches = manifest.setdefault("candidate_patches", [])
    patches.append(
        {
            "version": "v58_candidate",
            "source": "data/journal/primary/datasynth",
            "purpose": "restore required L1-09 and L2-02 truth lost in candidate lineage",
            "required_truth_validation": validation,
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_docs(output: Path, validation: dict[str, Any]) -> None:
    freeze = f"""# DataSynth v58 Candidate

Status: candidate. Built on top of current production `data/journal/primary/datasynth` v57.

## Purpose

Restore required Phase 1 truth that was lost during earlier candidate lineage changes.

## Restored Contracts

- L1-09 `ApprovalDateMissing`: `{validation["approval_date_missing_labels"]}` labels.
- L2-02 `DuplicatePayment`: `{validation["duplicate_payment_labels"]}` confirmed duplicate-result labels.
- L2-02 pair sidecar: `{validation["duplicate_payment_pair_rows"]}` rows.
- L2-02 negative controls: `{validation["duplicate_payment_negative_control_rows"]}` rows.

## Year Split

| Year | L1-09 cases | L2-02 pairs | L2-02 controls |
|---|---:|---:|---:|
| 2022 | {validation["by_year"]["2022"]["approval_missing_docs"]} | {validation["by_year"]["2022"]["duplicate_payment_pairs"]} | {validation["by_year"]["2022"]["duplicate_payment_negative_controls"]} |
| 2023 | {validation["by_year"]["2023"]["approval_missing_docs"]} | {validation["by_year"]["2023"]["duplicate_payment_pairs"]} | {validation["by_year"]["2023"]["duplicate_payment_negative_controls"]} |
| 2024 | {validation["by_year"]["2024"]["approval_missing_docs"]} | {validation["by_year"]["2024"]["duplicate_payment_pairs"]} | {validation["by_year"]["2024"]["duplicate_payment_negative_controls"]} |

## Anti-Fitting Notes

- L1-09 counts are intentionally non-uniform by year and process.
- L2-02 confirmed labels are limited to duplicate-result documents, not every row with `fraud_type=DuplicatePayment`.
- L2-02 keeps reference-blank, reference-variant, date-gap, and small rounding variants.
- Normal repeat-payment controls remain separate from confirmed anomalies.

## Validation

Failures: `{len(validation["failures"])}`
"""
    preview = f"""# DataSynth v58 Candidate Preview

`datasynth_v58_candidate` restores missing required Phase 1 truth on top of production v57.

- `ApprovalDateMissing`: `{validation["approval_date_missing_labels"]}`
- `DuplicatePayment`: `{validation["duplicate_payment_labels"]}`
- `duplicate_payment_pairs`: `{validation["duplicate_payment_pair_rows"]}`
- `duplicate_payment_negative_controls`: `{validation["duplicate_payment_negative_control_rows"]}`

This candidate should be promoted only if required-truth validation has zero failures.
"""
    (output / "FREEZE_V58_CANDIDATE.md").write_text(freeze, encoding="utf-8")
    (output / "PREVIEW.md").write_text(preview, encoding="utf-8")
    (output / "V58_REQUIRED_TRUTH_RESTORE.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    source = DEFAULT_SOURCE
    output = DEFAULT_OUTPUT
    copy_source(source, output)

    df = pd.read_csv(output / "journal_entries.csv", low_memory=False)
    for amount_column in ["debit_amount", "credit_amount", "local_amount", "tax_amount"]:
        if amount_column in df.columns:
            df[amount_column] = pd.to_numeric(df[amount_column], errors="coerce").astype(float)
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv")
    existing = set(labels["anomaly_type"].astype(str))
    if "ApprovalDateMissing" in existing or "DuplicatePayment" in existing:
        raise RuntimeError("v58 restore expected missing ApprovalDateMissing/DuplicatePayment labels in source")

    df, approval_cases, approval_labels = restore_l109(df, labels)
    labels = pd.concat([labels, pd.DataFrame(approval_labels)], ignore_index=True)
    df, payment_pairs, payment_controls, payment_labels = restore_l202(df, labels)
    labels = pd.concat([labels, pd.DataFrame(payment_labels)], ignore_index=True)
    labels = labels.sort_values(["anomaly_date", "anomaly_id"], kind="stable").reset_index(drop=True)

    write_year_files(output, df)
    labels_dir = output / "labels"
    write_anomaly_labels(labels_dir, labels)
    write_sidecar_family(labels_dir, "approval_date_missing_cases", approval_cases)
    write_sidecar_family(labels_dir, "duplicate_payment_pairs", payment_pairs)
    write_sidecar_family(labels_dir, "duplicate_payment_negative_controls", payment_controls)

    validation = verify_required_truth(output)
    update_manifest(output, validation)
    write_docs(output, validation)
    if validation["failures"]:
        raise RuntimeError(json.dumps(validation, ensure_ascii=False, indent=2))
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
