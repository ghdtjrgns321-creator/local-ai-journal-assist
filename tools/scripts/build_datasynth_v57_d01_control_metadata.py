from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd


D01_STEMS = [
    "account_activity_variance_truth",
    "account_activity_variance_normal_controls",
    "account_activity_variance_review_population",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v57 D01 control metadata sidecar patch.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v56_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_json(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return pd.read_csv(path, dtype=str, keep_default_na=False).to_dict("records")


def numeric(record: dict, key: str) -> float:
    try:
        return float(record.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def boolean(record: dict, key: str) -> bool:
    return str(record.get(key, "")).strip().lower() == "true"


def business_event(record: dict) -> tuple[str, str, str]:
    scenario = record.get("scenario_type", "")
    family = record.get("account_family", "")
    processes = str(record.get("business_processes", ""))
    sources = str(record.get("sources", "")).lower()
    total_var = numeric(record, "total_amount_variance")
    count_var = numeric(record, "count_variance")
    avg_var = numeric(record, "avg_amount_variance")

    if boolean(record, "is_true_positive_account"):
        if scenario == "suspicious_new_or_bypass_account":
            return "suspicious_bypass_account", "confirmed_truth", "Prior-year absence plus D01 target anomaly indicates a suspicious new or bypass account."
        if scenario == "revenue_expense_activity_surge":
            return "abnormal_revenue_expense_surge", "confirmed_truth", "Revenue or expense activity increased sharply with count and amount movement beyond normal review thresholds."
        if scenario == "anomaly_supported_activity_shift":
            return "anomaly_supported_shift", "confirmed_truth", "The account activity shift is supported by D01-relevant injected anomaly evidence."
        return "target_anomaly_concentration", "confirmed_truth", "D01-relevant anomaly documents are concentrated in an account with material activity variance."

    if scenario == "review_only_activity_variance":
        return "review_queue_only", "review_queue", "D01 should surface this account for analytical review, but no confirmed D01 anomaly evidence is attached."
    if scenario == "non_d01_anomaly_not_account_variance_truth":
        return "non_d01_document_context", "auxiliary_non_d01_context", "The account contains document-level anomaly context, but that context is not an account-activity variance truth."
    if scenario == "normal_high_volume_operational_change":
        return "high_volume_operations", "normal_business_control", "Cash, bank, AP, AR, or treasury clearing accounts can move materially from normal operating volume."
    if scenario == "normal_investment_or_working_capital_change":
        if "A2R" in processes:
            return "capex_investment_event", "normal_business_control", "Asset activity variance is consistent with capex, fixed-asset, or investment timing."
        if "O2C" in processes or "P2P" in processes:
            return "working_capital_timing", "normal_business_control", "Asset activity variance is consistent with AR, inventory, prepayment, or supplier timing."
        return "working_capital_or_investment_timing", "normal_business_control", "Asset activity variance can arise from normal investment or working-capital timing."
    if scenario == "normal_business_volume_or_price_change":
        if count_var >= avg_var and count_var >= 0.75:
            return "volume_growth", "normal_business_control", "The main driver is transaction count growth, consistent with normal volume expansion."
        if avg_var > count_var and avg_var >= 0.75:
            return "price_increase", "normal_business_control", "The main driver is average entry amount growth, consistent with price, mix, or unit-cost changes."
        if "P2P" in processes or "O2C" in processes:
            return "entity_process_expansion", "normal_business_control", "Process coverage expanded across purchasing or sales flows, consistent with normal business expansion."
        if "recurring" in sources or "automated" in sources:
            return "recurring_or_system_volume_shift", "normal_business_control", "Recurring or automated activity changed materially without D01 truth evidence."
        if total_var >= 1.0:
            return "volume_or_price_growth", "normal_business_control", "Total account activity moved materially, but supporting evidence points to normal business growth."
        return "normal_business_drift", "normal_business_control", "The account has a normal business drift pattern without confirmed D01 anomaly evidence."
    if boolean(record, "prior_missing"):
        return "normal_new_account", "normal_business_control", "The account is new to the comparison year but has no D01 target anomaly evidence."
    return "unclassified_review_context", "review_queue", "The account remains in the analytical review queue pending business context."


def enrich(record: dict) -> dict:
    event_type, bucket, reason = business_event(record)
    enriched = dict(record)
    enriched["business_event_type"] = event_type
    enriched["evaluation_bucket"] = bucket
    if not enriched.get("normal_reason") or bucket != "confirmed_truth":
        enriched["normal_reason"] = reason
    enriched["d01_control_metadata_version"] = "v57"
    enriched["precision_policy"] = {
        "confirmed_truth": "count_as_d01_truth",
        "normal_business_control": "expected_raw_flag_but_exclude_from_confirmed_truth",
        "review_queue": "review_queue_not_false_positive",
        "auxiliary_non_d01_context": "separate_from_d01_precision_denominator",
    }.get(bucket, "review_required")
    return enriched


def rewrite_sidecar_family(labels_dir: Path, stem: str) -> list[dict]:
    all_records = [enrich(record) for record in read_records(labels_dir / f"{stem}.csv")]
    write_records(labels_dir / f"{stem}.csv", all_records)
    write_json(labels_dir / f"{stem}.json", all_records)

    for year in (2023, 2024):
        year_records = [record for record in all_records if str(record.get("fiscal_year")) == str(year)]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        write_json(labels_dir / f"{stem}_{year}.json", year_records)
    return all_records


def summarize(records: list[dict]) -> dict:
    return {
        "total": len(records),
        "by_year": pd.Series([record.get("fiscal_year", "") for record in records]).value_counts().sort_index().to_dict()
        if records
        else {},
        "by_evaluation_bucket": pd.Series([record.get("evaluation_bucket", "") for record in records]).value_counts().to_dict()
        if records
        else {},
        "by_business_event_type": pd.Series([record.get("business_event_type", "") for record in records]).value_counts().to_dict()
        if records
        else {},
    }


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
    enriched = {stem: rewrite_sidecar_family(labels_dir, stem) for stem in D01_STEMS}
    summary = {stem: summarize(records) for stem, records in enriched.items()}

    summary_path = labels_dir / "anomaly_labels_summary.json"
    label_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    label_summary["v57_d01_control_metadata"] = {
        "policy": "D01 normal-control metadata enrichment; journal rows and D01 truth membership unchanged.",
        "summary": summary,
    }
    summary_path.write_text(json.dumps(label_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v57_candidate",
            "source": source.name,
            "purpose": "Enrich D01 account activity variance sidecars with business_event_type and evaluation_bucket.",
            "summary": summary,
            "anti_fitting_policy": [
                "Do not change journal rows or D01 truth membership.",
                "Clarify normal-control interpretation for reporting.",
                "Keep expected_d01_flag separate from is_true_positive_account.",
                "Separate review_queue and auxiliary_non_d01_context from confirmed precision denominators.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (output / "FREEZE_V57_CANDIDATE.md").write_text(
        "# DataSynth v57 Candidate\n\n"
        "D01 normal-control metadata enrichment patch.\n\n"
        "- Source: `datasynth_v56_candidate`\n"
        "- Keeps journal rows, anomaly labels, and D01 truth membership unchanged.\n"
        "- Adds `business_event_type`, `evaluation_bucket`, `precision_policy`, and `d01_control_metadata_version` to D01 sidecars.\n"
        "- Clarifies normal business controls, review queue cases, and auxiliary non-D01 context.\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
