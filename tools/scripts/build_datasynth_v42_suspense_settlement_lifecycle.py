from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


SUSPENSE_PREFIXES = ("1190", "1290", "2190", "2900", "9990")
ANOMALY_COUNTS = {2022: 18, 2023: 23, 2024: 21}
NORMAL_CONTROL_COUNTS = {2022: 360, 2023: 340, 2024: 370}
CLOSED_STATUSES = ("settled", "cleared", "closed", "resolved", "matched")
OPEN_STATUSES = ("open", "unresolved", "in_review", "pending_clearing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v42 L3-09 suspense settlement lifecycle candidate.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v41_candidate")
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


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict], year_key: str = "fiscal_year") -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(r[year_key]) for r in records}):
        year_records = [r for r in records if int(r[year_key]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(json.dumps(year_records, ensure_ascii=False, indent=2), encoding="utf-8")


def is_suspense_account(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.startswith(SUSPENSE_PREFIXES).fillna(False)


def document_amount(df: pd.DataFrame) -> pd.Series:
    return df[["debit_amount", "credit_amount"]].fillna(0).abs().max(axis=1)


def build_year_lifecycle(output: Path, year: int) -> tuple[list[dict], list[dict], list[dict], dict[str, dict]]:
    rng = random.Random(4200 + year)
    path = output / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, low_memory=False, parse_dates=["posting_date"])
    for col in ["lettrage", "lettrage_date", "amount_open", "is_cleared", "settlement_status", "settlement_date"]:
        if col not in df.columns:
            df[col] = pd.NA

    df["_is_suspense_line"] = is_suspense_account(df["gl_account"])
    df["_line_amount"] = document_amount(df)
    suspense_lines = df[df["_is_suspense_line"]].copy()
    doc_summary = (
        suspense_lines.groupby("document_id")
        .agg(
            company_code=("company_code", "first"),
            fiscal_year=("fiscal_year", "first"),
            posting_date=("posting_date", "first"),
            document_number=("document_number", "first"),
            document_type=("document_type", "first"),
            business_process=("business_process", "first"),
            source=("source", "first"),
            created_by=("created_by", "first"),
            suspense_accounts=("gl_account", lambda s: "|".join(sorted(set(s.astype(str))))),
            suspense_line_count=("_is_suspense_line", "size"),
            max_amount=("_line_amount", "max"),
        )
        .reset_index()
    )
    dataset_end = df["posting_date"].max()
    doc_summary["age_to_dataset_end"] = (dataset_end - doc_summary["posting_date"]).dt.days
    doc_summary = doc_summary[doc_summary["age_to_dataset_end"].ge(45)].copy()

    high_amount = doc_summary["max_amount"].quantile(0.55)
    anomaly_pool = doc_summary[doc_summary["max_amount"].ge(high_amount)].copy()
    anomaly_pool = anomaly_pool.sort_values(["posting_date", "document_id"])
    anomaly_ids = _pick_spread(anomaly_pool["document_id"].astype(str).tolist(), ANOMALY_COUNTS[year], rng)

    normal_pool = doc_summary[~doc_summary["document_id"].astype(str).isin(anomaly_ids)].copy()
    normal_ids = _pick_normal_controls(normal_pool, NORMAL_CONTROL_COUNTS[year], rng)

    lifecycle_by_doc: dict[str, dict] = {}
    population_records: list[dict] = []
    anomaly_records: list[dict] = []
    normal_records: list[dict] = []

    for row in doc_summary.itertuples(index=False):
        doc_id = str(row.document_id)
        if doc_id in anomaly_ids:
            scenario = _anomaly_scenario(len(anomaly_records))
            status = _open_status(len(anomaly_records))
            settlement_date = ""
            lettrage_date = ""
            is_cleared = False
            open_ratio = scenario["open_ratio"]
            truth = "confirmed_suspense_aging_anomaly"
            aging_days = int(row.age_to_dataset_end)
        elif doc_id in normal_ids:
            scenario = _normal_scenario(len(normal_records))
            status = scenario["status"]
            is_cleared = bool(scenario["is_cleared"])
            days = int(scenario["days"])
            settlement_ts = pd.Timestamp(row.posting_date) + pd.Timedelta(days=days)
            if settlement_ts > dataset_end:
                settlement_ts = pd.Timestamp(row.posting_date) + pd.Timedelta(days=max(1, min(20, int(row.age_to_dataset_end) - 1)))
            settlement_date = settlement_ts.strftime("%Y-%m-%d")
            lettrage_date = settlement_date if scenario["with_lettrage"] else ""
            open_ratio = float(scenario["open_ratio"])
            truth = "normal_suspense_clearing_control"
            aging_days = days
        else:
            scenario = _background_scenario(doc_id)
            status = scenario["status"]
            is_cleared = bool(scenario["is_cleared"])
            if is_cleared:
                days = int(scenario["days"])
                settlement_ts = pd.Timestamp(row.posting_date) + pd.Timedelta(days=min(days, max(1, int(row.age_to_dataset_end) - 1)))
                settlement_date = settlement_ts.strftime("%Y-%m-%d")
                lettrage_date = settlement_date if scenario["with_lettrage"] else ""
                aging_days = (settlement_ts - pd.Timestamp(row.posting_date)).days
            else:
                settlement_date = ""
                lettrage_date = ""
                aging_days = int(row.age_to_dataset_end)
            open_ratio = float(scenario["open_ratio"])
            truth = "suspense_lifecycle_population"

        amount_open = round(float(row.max_amount) * open_ratio, 2)
        lettrage = f"CLR-{year}-{_stable_int(doc_id) % 900000 + 100000}" if lettrage_date else ""
        lifecycle = {
            "document_id": doc_id,
            "settlement_status": status,
            "is_cleared": is_cleared,
            "settlement_date": settlement_date,
            "lettrage_date": lettrage_date,
            "lettrage": lettrage,
            "amount_open": amount_open,
            "aging_days": int(aging_days),
            "truth_basis": truth,
        }
        lifecycle_by_doc[doc_id] = lifecycle
        record = {
            **lifecycle,
            "company_code": row.company_code,
            "fiscal_year": int(row.fiscal_year),
            "posting_date": pd.Timestamp(row.posting_date).strftime("%Y-%m-%d %H:%M:%S"),
            "document_number": row.document_number,
            "document_type": row.document_type,
            "business_process": row.business_process,
            "source": row.source,
            "created_by": row.created_by,
            "suspense_accounts": row.suspense_accounts,
            "suspense_line_count": int(row.suspense_line_count),
            "max_amount": round(float(row.max_amount), 2),
            "is_confirmed_suspense_abuse": doc_id in anomaly_ids,
            "is_normal_suspense_control": doc_id in normal_ids,
            "evaluation_policy": "settlement_lifecycle_truth_not_suspense_account_usage",
        }
        population_records.append(record)
        if doc_id in anomaly_ids:
            anomaly_records.append({**record, "scenario_variant": scenario["variant"], "anomaly_type": "SuspenseAccountAbuse"})
        if doc_id in normal_ids:
            normal_records.append({**record, "control_id": f"L309NC-{year}-{len(normal_records)+1:04d}", "normal_control_type": scenario["variant"]})

    _apply_lifecycle_to_csv(df, lifecycle_by_doc, path, output)
    return population_records, anomaly_records, normal_records, lifecycle_by_doc


def _pick_spread(ids: list[str], count: int, rng: random.Random) -> set[str]:
    if len(ids) < count:
        raise RuntimeError(f"Not enough suspense candidates: {len(ids)}/{count}")
    buckets = [ids[i::count] for i in range(count)]
    picked = []
    for bucket in buckets:
        if not bucket:
            continue
        picked.append(rng.choice(bucket))
    return set(picked[:count])


def _pick_normal_controls(pool: pd.DataFrame, count: int, rng: random.Random) -> set[str]:
    rows = pool.sort_values(["business_process", "source", "posting_date", "document_id"])["document_id"].astype(str).tolist()
    rng.shuffle(rows)
    if len(rows) < count:
        raise RuntimeError(f"Not enough normal suspense controls: {len(rows)}/{count}")
    return set(rows[:count])


def _anomaly_scenario(idx: int) -> dict:
    variants = [
        {"variant": "aged_unresolved_customer_receipt", "open_ratio": 1.00},
        {"variant": "aged_partial_employee_advance", "open_ratio": 0.55},
        {"variant": "aged_grir_not_cleared", "open_ratio": 0.80},
        {"variant": "aged_misc_suspense_balance", "open_ratio": 0.35},
    ]
    return variants[idx % len(variants)]


def _normal_scenario(idx: int) -> dict:
    variants = [
        {"variant": "cleared_within_week", "status": "cleared", "is_cleared": True, "days": 5, "open_ratio": 0.0, "with_lettrage": True},
        {"variant": "month_end_matched", "status": "matched", "is_cleared": True, "days": 18, "open_ratio": 0.0, "with_lettrage": True},
        {"variant": "resolved_after_supporting_doc", "status": "resolved", "is_cleared": True, "days": 24, "open_ratio": 0.0, "with_lettrage": False},
        {"variant": "small_residual_open_under_review", "status": "in_review", "is_cleared": False, "days": 12, "open_ratio": 0.02, "with_lettrage": False},
    ]
    return variants[idx % len(variants)]


def _background_scenario(doc_id: str) -> dict:
    n = _stable_int(doc_id) % 100
    if n < 72:
        return {"status": CLOSED_STATUSES[n % len(CLOSED_STATUSES)], "is_cleared": True, "days": 3 + (n % 24), "open_ratio": 0.0, "with_lettrage": n % 3 != 0}
    if n < 88:
        return {"status": "in_review", "is_cleared": False, "days": 8 + (n % 18), "open_ratio": 0.01 + (n % 4) * 0.01, "with_lettrage": False}
    return {"status": OPEN_STATUSES[n % len(OPEN_STATUSES)], "is_cleared": False, "days": 20 + (n % 9), "open_ratio": 0.0, "with_lettrage": False}


def _open_status(idx: int) -> str:
    return OPEN_STATUSES[idx % len(OPEN_STATUSES)]


def _stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16)


def _apply_lifecycle_to_csv(df: pd.DataFrame, lifecycle_by_doc: dict[str, dict], path: Path, output: Path) -> None:
    df["_doc_id_str"] = df["document_id"].astype(str)
    suspense_mask = df["_is_suspense_line"].astype(bool)
    for doc_id, lifecycle in lifecycle_by_doc.items():
        mask = suspense_mask & df["_doc_id_str"].eq(doc_id)
        if not mask.any():
            continue
        df.loc[mask, "lettrage"] = lifecycle["lettrage"]
        df.loc[mask, "lettrage_date"] = lifecycle["lettrage_date"]
        df.loc[mask, "amount_open"] = lifecycle["amount_open"]
        df.loc[mask, "is_cleared"] = lifecycle["is_cleared"]
        df.loc[mask, "settlement_status"] = lifecycle["settlement_status"]
        df.loc[mask, "settlement_date"] = lifecycle["settlement_date"]
    df = df.drop(columns=["_is_suspense_line", "_line_amount", "_doc_id_str"])
    df.to_csv(path, index=False)
    all_year = pd.concat(
        [pd.read_csv(output / f"journal_entries_{year}.csv", low_memory=False) for year in [2022, 2023, 2024]],
        ignore_index=True,
    )
    all_year.to_csv(output / "journal_entries.csv", index=False)


def patch_journal_json(output: Path, population: list[dict]) -> dict:
    json_path = output / "journal_entries.json"
    if not json_path.exists():
        return {"documents_patched": 0, "suspense_lines_patched": 0}
    lifecycle_by_doc = {str(record["document_id"]): record for record in population}
    tmp_path = json_path.with_suffix(".json.tmp")
    documents_patched = 0
    suspense_lines_patched = 0
    first_written = False

    with json_path.open("r", encoding="utf-8") as src, tmp_path.open("w", encoding="utf-8", newline="\n") as dst:
        dst.write("[\n")
        buffer: list[str] = []
        depth = 0
        in_object = False
        for line in src:
            stripped = line.strip()
            if not in_object:
                if stripped in {"[", "]"}:
                    continue
                if stripped.startswith("{"):
                    in_object = True
                    buffer = [line]
                    depth = line.count("{") - line.count("}")
                continue
            buffer.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0:
                raw = "".join(buffer).rstrip()
                if raw.endswith(","):
                    raw = raw[:-1]
                record = json.loads(raw)
                doc_id = str(record.get("header", {}).get("document_id", ""))
                lifecycle = lifecycle_by_doc.get(doc_id)
                patched_lines = _patch_json_record_settlement(record, lifecycle)
                if patched_lines:
                    documents_patched += 1
                    suspense_lines_patched += patched_lines
                if first_written:
                    dst.write(",\n")
                dst.write(json.dumps(record, ensure_ascii=False, indent=2))
                first_written = True
                in_object = False
                buffer = []
        dst.write("\n]\n")
    tmp_path.replace(json_path)
    return {"documents_patched": documents_patched, "suspense_lines_patched": suspense_lines_patched}


def _patch_json_record_settlement(record: dict, lifecycle: dict | None) -> int:
    patched = 0
    for line in record.get("lines", []):
        for col in ["lettrage", "lettrage_date", "amount_open", "is_cleared", "settlement_status", "settlement_date"]:
            line.setdefault(col, None)
        if not lifecycle:
            continue
        if not str(line.get("gl_account", "")).strip().startswith(SUSPENSE_PREFIXES):
            continue
        line["lettrage"] = lifecycle["lettrage"] or None
        line["lettrage_date"] = lifecycle["lettrage_date"] or None
        line["amount_open"] = lifecycle["amount_open"]
        line["is_cleared"] = bool(lifecycle["is_cleared"])
        line["settlement_status"] = lifecycle["settlement_status"]
        line["settlement_date"] = lifecycle["settlement_date"] or None
        patched += 1
    return patched


def append_anomaly_labels(output: Path, anomaly_records: list[dict]) -> pd.DataFrame:
    labels_path = output / "labels" / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, low_memory=False)
    max_num = _max_anomaly_num(labels)
    rows = []
    cols = list(labels.columns)
    for offset, record in enumerate(anomaly_records, start=1):
        metadata = {
            "scenario_variant": record["scenario_variant"],
            "settlement_status": record["settlement_status"],
            "amount_open": record["amount_open"],
            "aging_days": record["aging_days"],
            "suspense_accounts": record["suspense_accounts"],
            "v42_label_policy": "settlement_lifecycle_scenario_truth_not_detector_backfill",
        }
        row = {col: "" for col in cols}
        row.update(
            {
                "anomaly_id": f"ANO{max_num + offset:08d}",
                "anomaly_category": "Logic",
                "anomaly_type": "SuspenseAccountAbuse",
                "document_id": record["document_id"],
                "document_type": "JE",
                "company_code": record["company_code"],
                "anomaly_date": str(record["posting_date"])[:10],
                "detection_timestamp": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "confidence": 0.84,
                "severity": 3,
                "description": f"Suspense account remains unresolved beyond aging threshold ({record['scenario_variant']})",
                "is_injected": True,
                "related_entities": json.dumps([record["suspense_accounts"]], ensure_ascii=False),
                "injection_strategy": "SuspenseAccountAbuse",
                "scenario_id": f"L309-{record['fiscal_year']}-{offset:04d}",
                "metadata_json": json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            }
        )
        rows.append(row)
    labels = pd.concat([labels, pd.DataFrame(rows, columns=cols)], ignore_index=True)
    labels.to_csv(labels_path, index=False)
    rewrite_label_jsons(output / "labels", labels)
    return labels


def _max_anomaly_num(labels: pd.DataFrame) -> int:
    nums = labels["anomaly_id"].fillna("").astype(str).str.extract(r"ANO(\d+)")[0].dropna().astype(int)
    return int(nums.max()) if not nums.empty else 0


def read_metadata(value: object) -> dict:
    if pd.isna(value) or str(value).strip() == "":
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def rewrite_label_jsons(labels_dir: Path, labels: pd.DataFrame) -> None:
    records = []
    for _, row in labels.iterrows():
        raw = row.get("related_entities", "")
        related = []
        if pd.notna(raw) and str(raw).strip():
            try:
                parsed = json.loads(str(raw))
                related = parsed if isinstance(parsed, list) else [str(raw)]
            except json.JSONDecodeError:
                related = [str(raw)]
        records.append(
            {
                "anomaly_id": row["anomaly_id"],
                "anomaly_type": {row["anomaly_category"]: row["anomaly_type"]},
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": str(row["anomaly_date"]),
                "detection_timestamp": str(row["detection_timestamp"]),
                "confidence": row["confidence"],
                "severity": int(row["severity"]) if pd.notna(row["severity"]) and str(row["severity"]) != "" else None,
                "description": row["description"],
                "related_entities": related,
                "metadata": read_metadata(row.get("metadata_json", "")),
                "is_injected": bool(row["is_injected"]),
                "injection_strategy": row["injection_strategy"],
            }
        )
    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "total_labels": int(len(labels)),
        "by_category": {k: int(v) for k, v in labels["anomaly_category"].value_counts().to_dict().items()},
        "by_company": {k: int(v) for k, v in labels["company_code"].value_counts().to_dict().items()},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def write_preview(output: Path, summary: dict) -> None:
    text = f"""# DataSynth v42 Candidate

v42 keeps v41 and adds L3-09 suspense/open-item settlement lifecycle fields.

## Summary

- Source baseline: `datasynth_v41_candidate`
- Suspense lifecycle population: {summary['suspense_lifecycle_population']['total']} documents
- L3-09 aging review population: {summary['suspense_aging_review_population']['total']} documents
- Confirmed SuspenseAccountAbuse labels: {summary['confirmed_suspense_abuse']['total']} documents
- Normal suspense clearing controls: {summary['normal_suspense_controls']['total']} documents
- Added CSV columns: `lettrage`, `lettrage_date`, `amount_open`, `is_cleared`, `settlement_status`, `settlement_date`
- Policy: L3-09 evaluates long-open suspense balances, not suspense-account usage alone.

## Files

- `labels/suspense_lifecycle_population.csv/json`
- `labels/suspense_lifecycle_population_2022/2023/2024.csv/json`
- `labels/suspense_aging_review_population.csv/json`
- `labels/suspense_confirmed_anomalies.csv/json`
- `labels/suspense_normal_controls.csv/json`
- `V42_SUSPENSE_SETTLEMENT_LIFECYCLE.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V42_CANDIDATE.md").write_text(text, encoding="utf-8")


def _is_l309_review_hit(record: dict) -> bool:
    status = str(record.get("settlement_status", "")).strip().lower()
    closed = status in CLOSED_STATUSES
    unresolved = (not bool(record.get("is_cleared", False))) or not closed
    amount_open = float(record.get("amount_open") or 0.0)
    aging_days = int(record.get("aging_days") or 0)
    return unresolved and amount_open > 0.0 and aging_days >= 30


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise FileExistsError(f"{output} already exists; pass --force")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    population: list[dict] = []
    anomalies: list[dict] = []
    controls: list[dict] = []
    for year in [2022, 2023, 2024]:
        year_population, year_anomalies, year_controls, _ = build_year_lifecycle(output, year)
        population.extend(year_population)
        anomalies.extend(year_anomalies)
        controls.extend(year_controls)

    json_patch_summary = patch_journal_json(output, population)
    labels = append_anomaly_labels(output, anomalies)
    labels_dir = output / "labels"
    review_population = [
        record for record in population
        if _is_l309_review_hit(record)
    ]
    write_sidecar_family(labels_dir, "suspense_lifecycle_population", population)
    write_sidecar_family(labels_dir, "suspense_aging_review_population", review_population)
    write_sidecar_family(labels_dir, "suspense_confirmed_anomalies", anomalies)
    write_sidecar_family(labels_dir, "suspense_normal_controls", controls)

    summary = {
        "candidate_version": "v42_candidate",
        "source_baseline": "datasynth_v41_candidate",
        "focus": "Add settlement/open-item lifecycle fields for L3-09 SuspenseAccountAbuse evaluation",
        "suspense_lifecycle_population": {
            "total": len(population),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in population).items())},
        },
        "suspense_aging_review_population": {
            "total": len(review_population),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in review_population).items())},
        },
        "confirmed_suspense_abuse": {
            "total": len(anomalies),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in anomalies).items())},
            "by_variant": {str(k): int(v) for k, v in sorted(Counter(r["scenario_variant"] for r in anomalies).items())},
        },
        "normal_suspense_controls": {
            "total": len(controls),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in controls).items())},
            "by_type": {str(k): int(v) for k, v in sorted(Counter(r["normal_control_type"] for r in controls).items())},
        },
        "label_counts_after_patch": {
            "SuspenseAccountAbuse": int((labels["anomaly_type"] == "SuspenseAccountAbuse").sum()),
        },
        "journal_json_patch": json_patch_summary,
        "contract": {
            "l309_truth": "SuspenseAccountAbuse requires suspense account + unresolved open item + aging threshold.",
            "l309_review_population": "All long-open suspense balances are review candidates and are not all confirmed anomaly truth.",
            "normal_controls": "Cleared, matched, resolved, and short-open suspense documents are not anomaly truth.",
            "not_test_fitting": "Lifecycle scenarios are generated before detector evaluation and include negative controls.",
        },
    }
    (output / "V42_SUSPENSE_SETTLEMENT_LIFECYCLE.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
