from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd


EXACT_ACCOUNTS = {"1190": "suspense_clearing", "2190": "suspense_clearing"}
PREFIX_GROUPS = {"111": "cash_equivalent", "112": "cash_equivalent", "113": "cash_equivalent"}
TARGET_CONFIRMED = {2022: 19, 2023: 24, 2024: 17}
TARGET_CONTROLS = {2022: 108, 2023: 94, 2024: 121}
LABEL_TYPE = "HighRiskAccountUse"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v45 L3-10 high-risk account truth sidecars.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v44_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def account_code(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().str.replace(r"\.0+$", "", regex=True)


def bool_series(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip().str.lower().isin({"true", "1", "yes", "y"})


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict]) -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(r["fiscal_year"]) for r in records}):
        year_records = [r for r in records if int(r["fiscal_year"]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def first_nonempty(values: pd.Series) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value)
    return ""


def match_accounts(accounts: list[str]) -> tuple[list[str], list[str], list[str]]:
    matched_accounts: list[str] = []
    match_types: list[str] = []
    groups: list[str] = []
    for account in accounts:
        if account in EXACT_ACCOUNTS:
            matched_accounts.append(account)
            match_types.append("exact")
            groups.append(EXACT_ACCOUNTS[account])
            continue
        for prefix, group in PREFIX_GROUPS.items():
            if account.startswith(prefix):
                matched_accounts.append(account)
                match_types.append(f"prefix:{prefix}")
                groups.append(group)
                break
    return sorted(set(matched_accounts)), sorted(set(match_types)), sorted(set(groups))


def document_population(df: pd.DataFrame, year: int, existing_label_docs: set[str]) -> pd.DataFrame:
    df = df.copy()
    df["_account_code"] = account_code(df["gl_account"])
    df["_l310_hit"] = df["_account_code"].isin(EXACT_ACCOUNTS) | df["_account_code"].str.startswith(tuple(PREFIX_GROUPS))
    df["_line_amount"] = pd.concat(
        [
            pd.to_numeric(df.get("debit_amount", 0), errors="coerce").fillna(0.0).abs(),
            pd.to_numeric(df.get("credit_amount", 0), errors="coerce").fillna(0.0).abs(),
        ],
        axis=1,
    ).max(axis=1)

    hit_docs = set(df.loc[df["_l310_hit"], "document_id"].astype(str))
    doc_rows: list[dict] = []
    for doc_id, group in df[df["document_id"].astype(str).isin(hit_docs)].groupby("document_id", sort=False):
        accounts, match_types, matched_groups = match_accounts(group.loc[group["_l310_hit"], "_account_code"].tolist())
        source = first_nonempty(group.get("source", pd.Series(dtype=object))).lower()
        approved_by = first_nonempty(group.get("approved_by", pd.Series(dtype=object)))
        approval_date = first_nonempty(group.get("approval_date", pd.Series(dtype=object)))
        description_quality = first_nonempty(group.get("description_quality", pd.Series(dtype=object))).lower()
        posting_date = first_nonempty(group.get("posting_date", pd.Series(dtype=object)))
        is_after_hours = bool_series(group.get("is_after_hours", pd.Series(False, index=group.index))).any()
        is_weekend = bool_series(group.get("is_weekend", pd.Series(False, index=group.index))).any()
        is_holiday = bool_series(group.get("is_holiday", pd.Series(False, index=group.index))).any()
        is_period_end = bool_series(group.get("is_period_end", pd.Series(False, index=group.index))).any()
        settlement_status = first_nonempty(group.get("settlement_status", pd.Series(dtype=object))).lower()
        is_cleared = bool_series(group.get("is_cleared", pd.Series(False, index=group.index))).any()
        max_line_amount = float(group["_line_amount"].max())
        doc_rows.append(
            {
                "truth_id": f"L310POP-{year}-{len(doc_rows) + 1:05d}",
                "document_id": str(doc_id),
                "company_code": first_nonempty(group.get("company_code", pd.Series(dtype=object))),
                "fiscal_year": year,
                "posting_date": posting_date,
                "document_number": first_nonempty(group.get("document_number", pd.Series(dtype=object))),
                "document_type": first_nonempty(group.get("document_type", pd.Series(dtype=object))),
                "business_process": first_nonempty(group.get("business_process", pd.Series(dtype=object))),
                "source": source,
                "created_by": first_nonempty(group.get("created_by", pd.Series(dtype=object))),
                "approved_by": approved_by,
                "approval_date": approval_date,
                "description_quality": description_quality,
                "matched_accounts": "|".join(accounts),
                "match_types": "|".join(match_types),
                "matched_groups": "|".join(matched_groups),
                "max_line_amount": round(max_line_amount, 2),
                "is_manual_or_adjustment": source in {"manual", "adjustment"},
                "is_after_hours": bool(is_after_hours),
                "is_weekend": bool(is_weekend),
                "is_holiday": bool(is_holiday),
                "is_period_end": bool(is_period_end),
                "has_missing_approval_date": bool(approved_by and not approval_date),
                "is_uncleared": bool((not is_cleared) and settlement_status in {"open", "unresolved", "partial"}),
                "has_existing_anomaly_label": str(doc_id) in existing_label_docs,
                "truth_basis": "L3-10 configured high-risk account review population",
                "evaluation_policy": "review_population_not_confirmed_fraud",
            }
        )
    return pd.DataFrame(doc_rows)


def classify_confirmed(population: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    pop = population.copy()
    q85 = pop["max_line_amount"].quantile(0.85)
    q65 = pop["max_line_amount"].quantile(0.65)
    pop["risk_reason"] = ""

    reason_masks = [
        ("manual_period_end_sensitive_account", pop["is_manual_or_adjustment"] & pop["is_period_end"]),
        ("manual_missing_approval_sensitive_account", pop["is_manual_or_adjustment"] & pop["has_missing_approval_date"]),
        ("manual_corrupted_description_sensitive_account", pop["is_manual_or_adjustment"] & pop["description_quality"].isin(["missing", "corrupted"])),
        ("after_hours_sensitive_account", pop["is_after_hours"] & (pop["max_line_amount"] >= q65)),
        ("uncleared_high_amount_sensitive_account", pop["is_uncleared"] & (pop["max_line_amount"] >= q85)),
        ("high_amount_sensitive_account_review", pop["is_manual_or_adjustment"] & (pop["max_line_amount"] >= q85)),
        ("manual_high_amount_sensitive_account", pop["is_manual_or_adjustment"] & (pop["max_line_amount"] >= q65)),
        ("manual_sensitive_account_review", pop["is_manual_or_adjustment"]),
    ]

    picked_ids: list[str] = []
    picked_reasons: dict[str, str] = {}
    for reason, mask in reason_masks:
        pool = pop[mask & ~pop["document_id"].isin(picked_ids)].copy()
        pool["_sort_key"] = pool["document_id"].map(lambda value: f"{year}:{reason}:{value}")
        per_reason = max(2, TARGET_CONFIRMED[year] // len(reason_masks))
        for _, row in pool.sort_values(["_sort_key"]).head(per_reason).iterrows():
            picked_ids.append(row["document_id"])
            picked_reasons[row["document_id"]] = reason

    if len(picked_ids) < TARGET_CONFIRMED[year]:
        pool = pop[
            ~pop["document_id"].isin(picked_ids)
            & (
                pop["is_manual_or_adjustment"]
                | pop["is_after_hours"]
                | pop["has_missing_approval_date"]
                | pop["is_uncleared"]
            )
        ].copy()
        pool["_sort_key"] = pool["document_id"].map(lambda value: f"{year}:backfill:{value}")
        for _, row in pool.sort_values(["max_line_amount", "_sort_key"], ascending=[False, True]).head(
            TARGET_CONFIRMED[year] - len(picked_ids)
        ).iterrows():
            picked_ids.append(row["document_id"])
            picked_reasons[row["document_id"]] = "manual_sensitive_account_review"

    confirmed = pop[pop["document_id"].isin(picked_ids)].copy()
    confirmed["case_id"] = [f"L310A-{year}-{idx + 1:04d}" for idx in range(len(confirmed))]
    confirmed["risk_reason"] = confirmed["document_id"].map(picked_reasons)
    confirmed["truth_basis"] = "confirmed high-risk account anomaly with corroborating context"

    controls_pool = pop[
        ~pop["document_id"].isin(picked_ids)
        & ~pop["has_existing_anomaly_label"]
        & pop["description_quality"].isin(["", "normal"])
        & ~pop["has_missing_approval_date"]
        & (
            pop["source"].isin(["automated", "recurring", "batch", "system"])
            | (~pop["is_after_hours"] & ~pop["is_weekend"] & ~pop["is_holiday"])
        )
    ].copy()
    if len(controls_pool) < TARGET_CONTROLS[year]:
        controls_pool = pop[~pop["document_id"].isin(picked_ids)].copy()
    controls_pool["_sort_key"] = controls_pool["document_id"].map(lambda value: f"{year}:control:{value}")
    controls = controls_pool.sort_values(["has_existing_anomaly_label", "_sort_key"]).head(TARGET_CONTROLS[year]).copy()
    controls["control_id"] = [f"L310NC-{year}-{idx + 1:04d}" for idx in range(len(controls))]
    controls["control_reason"] = "normal_sensitive_account_usage"
    controls["truth_basis"] = "normal control for sensitive-account review population"
    return confirmed, controls


def append_anomaly_labels(labels_dir: Path, confirmed_records: list[dict]) -> None:
    labels_path = labels_dir / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    existing_ids = labels["anomaly_id"].astype(str)
    max_id = max(int(value.replace("ANO", "")) for value in existing_ids if value.startswith("ANO"))
    new_rows = []
    for offset, record in enumerate(confirmed_records, start=1):
        metadata = {
            "rule_id": "L3-10",
            "case_id": record["case_id"],
            "matched_accounts": record["matched_accounts"],
            "matched_groups": record["matched_groups"],
            "risk_reason": record["risk_reason"],
            "truth_basis": "confirmed subset; see high_risk_account_review_population for coverage truth",
        }
        new_rows.append(
            {
                "anomaly_id": f"ANO{max_id + offset:08d}",
                "anomaly_category": "ReviewSignal",
                "anomaly_type": LABEL_TYPE,
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "company_code": record["company_code"],
                "anomaly_date": record["posting_date"],
                "detection_timestamp": "2026-04-25 00:00:00",
                "confidence": "0.72",
                "severity": "3",
                "description": f"L3-10 sensitive account review: {record['risk_reason']}",
                "is_injected": "True",
                "monetary_impact": record["max_line_amount"],
                "related_entities": json.dumps([record["document_id"]], ensure_ascii=False),
                "cluster_id": "",
                "original_document_hash": "",
                "injection_strategy": "HighRiskAccountUse",
                "structured_strategy_type": "HighRiskAccountUse",
                "structured_strategy_json": "",
                "causal_reason_type": "CorroboratingContext",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": "",
                "run_id": "",
                "generation_seed": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            }
        )

    merged = pd.concat([labels, pd.DataFrame(new_rows, columns=labels.columns)], ignore_index=True)
    merged.to_csv(labels_path, index=False)
    merged.to_json(labels_dir / "anomaly_labels.json", orient="records", force_ascii=False, indent=2)
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for record in merged.to_dict("records"):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary_path = labels_dir / "anomaly_labels_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {}
    counts = merged["anomaly_type"].value_counts().to_dict()
    summary["total_labels"] = int(len(merged))
    summary["label_counts"] = {str(key): int(value) for key, value in counts.items()}
    summary["v45_high_risk_account_use"] = {
        "added_confirmed_labels": len(new_rows),
        "policy": "confirmed subset only; L3-10 review coverage uses high_risk_account_review_population.csv",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {output}")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    labels_dir = output / "labels"
    existing_labels = pd.read_csv(labels_dir / "anomaly_labels.csv", dtype=str, keep_default_na=False)
    existing_label_docs = set(existing_labels["document_id"].astype(str))

    population_records: list[dict] = []
    confirmed_records: list[dict] = []
    control_records: list[dict] = []
    summary: dict[int, dict[str, int]] = {}
    for year in (2022, 2023, 2024):
        df = pd.read_csv(output / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        population = document_population(df, year, existing_label_docs)
        confirmed, controls = classify_confirmed(population, year)
        population_records.extend(population.to_dict("records"))
        confirmed_records.extend(confirmed.to_dict("records"))
        control_records.extend(controls.to_dict("records"))
        summary[year] = {
            "review_population": int(len(population)),
            "confirmed_anomalies": int(len(confirmed)),
            "normal_controls": int(len(controls)),
        }

    write_sidecar_family(labels_dir, "high_risk_account_review_population", population_records)
    write_sidecar_family(labels_dir, "high_risk_account_confirmed_anomalies", confirmed_records)
    write_sidecar_family(labels_dir, "high_risk_account_normal_controls", control_records)
    append_anomaly_labels(labels_dir, confirmed_records)

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    patches = manifest.setdefault("candidate_patches", [])
    patches.append(
        {
            "version": "v45_candidate",
            "source": source.name,
            "purpose": "Add L3-10 high-risk account review population, confirmed subset, and normal controls.",
            "summary": {str(year): values for year, values in summary.items()},
            "anti_fitting_policy": [
                "Do not label every sensitive-account document as an anomaly.",
                "Use high_risk_account_review_population for L3-10 coverage.",
                "Use HighRiskAccountUse labels only for corroborated suspicious context.",
                "Keep normal sensitive-account controls to prevent shortcut learning.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    freeze = output / "FREEZE_V45_CANDIDATE.md"
    freeze.write_text(
        "# DataSynth v45 Candidate\n\n"
        "L3-10 high-risk account truth patch.\n\n"
        "- Source: `datasynth_v44_candidate`\n"
        "- Adds `labels/high_risk_account_review_population*` for all configured sensitive-account hits.\n"
        "- Adds `labels/high_risk_account_confirmed_anomalies*` for a small corroborated subset.\n"
        "- Adds `labels/high_risk_account_normal_controls*` for normal sensitive-account usage.\n"
        "- Adds `HighRiskAccountUse` labels only for confirmed subset, not for every L3-10 review hit.\n\n"
        f"Summary: `{json.dumps({str(year): values for year, values in summary.items()}, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps({str(year): values for year, values in summary.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
