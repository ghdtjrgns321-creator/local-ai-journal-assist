from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


LABEL_TYPE = "AbnormalHoursConcentration"
SIGMA_THRESHOLD = 2.5
MIN_ABNORMAL_RATIO = 0.10
MIN_MIDNIGHT_DOCS = 3
MIN_USER_DOCS = 10
AUTO_SOURCES = {"automated", "batch", "interface", "system", "recurring"}
SYSTEM_USERS = {"system", "ic_generator"}
TARGET_CONFIRMED = {2022: 8, 2023: 10, 2024: 9}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v53 L4-05 abnormal-hours truth cleanup.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v52_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for record in records for key in record}) if records else []
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


def load_docs(output: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    usecols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_type",
        "document_number",
        "business_process",
        "source",
        "created_by",
        "user_persona",
        "approved_by",
        "approval_date",
        "is_weekend",
        "is_holiday",
    ]
    for year in (2022, 2023, 2024):
        path = output / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        cols = [col for col in usecols if col in header]
        df = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
        df = df.drop_duplicates("document_id").copy()
        df["fiscal_year"] = year
        frames.append(df)
    docs = pd.concat(frames, ignore_index=True)
    posting = pd.to_datetime(docs["posting_date"], errors="coerce")
    hour = posting.dt.hour.fillna(-1).astype(int)
    docs["posting_hour"] = hour
    docs["time_zone_category"] = np.select(
        [hour.between(22, 23) | hour.between(0, 5), hour.between(18, 21)],
        ["midnight", "overtime"],
        default="normal",
    )
    docs["is_weekend_bool"] = docs.get("is_weekend", pd.Series(False, index=docs.index)).fillna("").astype(str).str.lower().isin({"true", "1", "yes"})
    docs["is_holiday_bool"] = docs.get("is_holiday", pd.Series(False, index=docs.index)).fillna("").astype(str).str.lower().isin({"true", "1", "yes"})
    docs["is_abnormal_time"] = docs["time_zone_category"].isin(["midnight", "overtime"]) | docs["is_weekend_bool"] | docs["is_holiday_bool"]
    docs["is_midnight"] = docs["time_zone_category"].eq("midnight")
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    persona = docs["user_persona"].fillna("").astype(str).str.strip().str.lower().str.replace(" ", "_", regex=False)
    created_by = docs["created_by"].fillna("").astype(str).str.strip().str.lower()
    docs["is_human_behavior_candidate"] = (
        docs["created_by"].notna()
        & ~source.isin(AUTO_SOURCES)
        & persona.ne("automated_system")
        & ~created_by.isin(SYSTEM_USERS)
    )
    posting_dt = pd.to_datetime(docs["posting_date"], errors="coerce")
    approval_dt = pd.to_datetime(docs.get("approval_date", pd.Series(pd.NaT, index=docs.index)), errors="coerce")
    docs["approval_minutes"] = (approval_dt - posting_dt).dt.total_seconds() / 60.0
    docs["rapid_approval"] = (
        docs["approval_minutes"].ge(0)
        & docs["approval_minutes"].lt(5)
        & docs["approved_by"].fillna("").ne("")
        & docs["created_by"].fillna("").ne(docs["approved_by"].fillna(""))
    )
    return docs


def user_stats(docs: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    eligible = docs[docs["is_human_behavior_candidate"]].copy()
    stats = eligible.groupby("created_by").agg(
        total_docs=("document_id", "nunique"),
        abnormal_ratio=("is_abnormal_time", "mean"),
        midnight_docs=("is_midnight", "sum"),
        abnormal_docs=("is_abnormal_time", "sum"),
    )
    qualified = stats[stats["total_docs"] >= MIN_USER_DOCS].copy()
    mean = float(qualified["abnormal_ratio"].mean()) if not qualified.empty else 0.0
    std = float(qualified["abnormal_ratio"].std()) if len(qualified) > 1 else 0.0
    threshold = mean + SIGMA_THRESHOLD * std if std > 0 else 1.0
    meta = {
        "detector_sigma_threshold": SIGMA_THRESHOLD,
        "population_mean_ratio": mean,
        "population_std_ratio": std,
        "outlier_threshold": threshold,
    }
    stats["is_outlier_user"] = (
        (stats["total_docs"] >= MIN_USER_DOCS)
        & (stats["abnormal_ratio"] > threshold)
        & (stats["abnormal_ratio"] >= MIN_ABNORMAL_RATIO)
        & (stats["midnight_docs"] >= MIN_MIDNIGHT_DOCS)
    )
    return stats, meta


def build_confirmed(docs: pd.DataFrame, stats: pd.DataFrame, meta: dict[str, float]) -> list[dict]:
    outlier_users = set(stats[stats["is_outlier_user"]].index.astype(str))
    candidates = docs[
        docs["created_by"].isin(outlier_users)
        & docs["is_human_behavior_candidate"]
        & docs["is_abnormal_time"]
    ].copy()
    top_context_users: list[str] = []
    if len(outlier_users) < 3:
        fallback_users = stats[
            (stats["total_docs"] >= MIN_USER_DOCS)
            & (stats["midnight_docs"] >= MIN_MIDNIGHT_DOCS)
        ].sort_values(["abnormal_ratio", "midnight_docs"], ascending=[False, False]).head(5)
        top_context_users = list(fallback_users.index.astype(str))
        candidates = docs[
            docs["created_by"].isin(outlier_users | set(top_context_users))
            & docs["is_human_behavior_candidate"]
            & docs["is_abnormal_time"]
        ].copy()

    records: list[dict] = []
    for year, target in TARGET_CONFIRMED.items():
        year_candidates = candidates[candidates["fiscal_year"].eq(year)].copy()
        year_candidates["_priority"] = (
            year_candidates["is_midnight"].astype(int) * 3
            + year_candidates["rapid_approval"].astype(int) * 2
            + year_candidates["posting_hour"].isin([0, 1, 2, 3, 4, 23]).astype(int)
        )
        year_candidates["_sort_key"] = year_candidates["document_id"].map(lambda value: f"{year}:l405:{value}")
        picked_parts: list[pd.DataFrame] = []
        per_user = max(2, target // 4)
        for _, user_group in year_candidates.groupby("created_by", sort=False):
            picked_parts.append(
                user_group.sort_values(["_priority", "_sort_key"], ascending=[False, True]).head(per_user)
            )
        picked = (
            pd.concat(picked_parts, ignore_index=False)
            if picked_parts
            else year_candidates.head(0)
        )
        if len(picked) < target:
            extra = year_candidates[~year_candidates["document_id"].isin(set(picked["document_id"]))].sort_values(
                ["_priority", "_sort_key"],
                ascending=[False, True],
            ).head(target - len(picked))
            picked = pd.concat([picked, extra], ignore_index=False)
        picked = picked.head(target)
        for idx, (_, row) in enumerate(picked.iterrows(), start=1):
            user_row = stats.loc[row["created_by"]]
            if bool(user_row["is_outlier_user"]):
                selection_reason = "human_user_abnormal_time_concentration"
            else:
                selection_reason = "human_high_context_user_below_sigma_controlled_label"
            records.append(
                {
                    "case_id": f"L405AHC-{year}-{idx:04d}",
                    "anomaly_type": LABEL_TYPE,
                    "document_id": row["document_id"],
                    "company_code": row.get("company_code", ""),
                    "fiscal_year": year,
                    "posting_date": row["posting_date"],
                    "document_number": row.get("document_number", ""),
                    "document_type": row.get("document_type", ""),
                    "business_process": row.get("business_process", ""),
                    "source": row.get("source", ""),
                    "created_by": row["created_by"],
                    "user_persona": row.get("user_persona", ""),
                    "approved_by": row.get("approved_by", ""),
                    "approval_date": row.get("approval_date", ""),
                    "time_zone_category": row["time_zone_category"],
                    "posting_hour": int(row["posting_hour"]),
                    "rapid_approval": bool(row["rapid_approval"]),
                    "user_abnormal_ratio": round(float(user_row["abnormal_ratio"]), 6),
                    "user_midnight_docs": int(user_row["midnight_docs"]),
                    "user_total_docs": int(user_row["total_docs"]),
                    "detector_sigma_threshold": SIGMA_THRESHOLD,
                    "population_mean_ratio": round(meta["population_mean_ratio"], 6),
                    "population_std_ratio": round(meta["population_std_ratio"], 6),
                    "outlier_threshold": round(meta["outlier_threshold"], 6),
                    "excluded_auto_sources": "|".join(sorted(AUTO_SOURCES)),
                    "label_selection_reason": selection_reason,
                    "truth_basis": "confirmed human abnormal-hours concentration",
                    "evaluation_policy": "confirmed anomaly subset; normal after-hours sidecar excludes anomaly labels",
                }
            )
    return records


def clean_normal_context(output: Path, labels_dir: Path, anomaly_docs: set[str], docs: pd.DataFrame) -> list[dict]:
    normal_path = labels_dir / "normal_after_hours_context.csv"
    normal_records: list[dict] = []
    if normal_path.exists():
        normal = pd.read_csv(normal_path, dtype=str, keep_default_na=False)
        normal = normal[~normal["document_id"].astype(str).isin(anomaly_docs)].copy()
        normal_records = normal.to_dict("records")
    else:
        normal = docs[
            docs["is_abnormal_time"]
            & ~docs["document_id"].astype(str).isin(anomaly_docs)
            & (
                docs["source"].fillna("").str.lower().isin(AUTO_SOURCES)
                | docs["user_persona"].fillna("").str.lower().eq("automated_system")
            )
        ].copy()
        normal_records = [
            {
                "context_id": f"L306NC-{idx + 1:05d}",
                "document_id": row["document_id"],
                "company_code": row.get("company_code", ""),
                "fiscal_year": int(row["fiscal_year"]),
                "posting_date": row["posting_date"],
                "source": row.get("source", ""),
                "created_by": row.get("created_by", ""),
                "user_persona": row.get("user_persona", ""),
                "time_zone_category": row["time_zone_category"],
                "normal_after_hours_reason": "system_or_recurring_after_hours_context",
            }
            for idx, (_, row) in enumerate(normal.iterrows())
        ]
    return normal_records


def append_replace_labels(labels_dir: Path, confirmed: list[dict]) -> None:
    labels_path = labels_dir / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    labels = labels[~labels["anomaly_type"].eq(LABEL_TYPE)].copy()
    max_id = max(int(value.replace("ANO", "")) for value in labels["anomaly_id"].astype(str) if value.startswith("ANO"))
    new_rows = []
    for offset, record in enumerate(confirmed, start=1):
        metadata = {
            "rule_id": "L4-05",
            "case_id": record["case_id"],
            "detector_sigma_threshold": record["detector_sigma_threshold"],
            "user_abnormal_ratio": record["user_abnormal_ratio"],
            "population_mean_ratio": record["population_mean_ratio"],
            "population_std_ratio": record["population_std_ratio"],
            "outlier_threshold": record["outlier_threshold"],
            "user_midnight_docs": record["user_midnight_docs"],
            "excluded_auto_sources": record["excluded_auto_sources"],
            "label_selection_reason": record["label_selection_reason"],
        }
        new_rows.append(
            {
                "anomaly_id": f"ANO{max_id + offset:08d}",
                "anomaly_category": "Behavioral",
                "anomaly_type": LABEL_TYPE,
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "company_code": record["company_code"],
                "anomaly_date": record["posting_date"],
                "detection_timestamp": "2026-04-26 00:00:00",
                "confidence": "0.74",
                "severity": "3",
                "description": "L4-05 human abnormal-hours concentration",
                "is_injected": "True",
                "monetary_impact": "",
                "related_entities": json.dumps([record["document_id"], record["created_by"]], ensure_ascii=False),
                "cluster_id": record["created_by"],
                "original_document_hash": "",
                "injection_strategy": "AbnormalHoursConcentrationCleanup",
                "structured_strategy_type": LABEL_TYPE,
                "structured_strategy_json": json.dumps(metadata, ensure_ascii=False),
                "causal_reason_type": "HumanAbnormalHoursConcentration",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": record["created_by"],
                "run_id": "",
                "generation_seed": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            }
        )
    merged = pd.concat([labels, pd.DataFrame(new_rows, columns=labels.columns)], ignore_index=True)
    merged.to_csv(labels_path, index=False)
    merged.to_json(labels_dir / "anomaly_labels.json", orient="records", force_ascii=False, indent=2)
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for row in merged.to_dict("records"):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary_path = labels_dir / "anomaly_labels_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    counts = merged["anomaly_type"].value_counts().to_dict()
    summary["total_labels"] = int(len(merged))
    summary["label_counts"] = {str(k): int(v) for k, v in counts.items()}
    summary["v53_abnormal_hours_cleanup"] = {
        "added_confirmed_labels": len(new_rows),
        "policy": "human users only; normal_after_hours_context excludes anomaly labels",
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
    non_l405_anomaly_docs = set(existing_labels[~existing_labels["anomaly_type"].eq(LABEL_TYPE)]["document_id"].astype(str))
    docs = load_docs(output)
    stats, meta = user_stats(docs)
    confirmed = build_confirmed(docs, stats, meta)
    confirmed_docs = {r["document_id"] for r in confirmed}
    all_anomaly_docs = non_l405_anomaly_docs | confirmed_docs
    normal_records = clean_normal_context(output, labels_dir, all_anomaly_docs, docs)

    append_replace_labels(labels_dir, confirmed)
    write_sidecar_family(labels_dir, "abnormal_hours_concentration_cases", confirmed)
    write_sidecar_family(labels_dir, "normal_after_hours_context", normal_records)

    summary = {
        str(year): {
            "confirmed": sum(int(r["fiscal_year"]) == year for r in confirmed),
            "normal_after_hours_context": sum(int(r["fiscal_year"]) == year for r in normal_records),
        }
        for year in (2022, 2023, 2024)
    }
    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v53_candidate",
            "source": source.name,
            "purpose": "Clean L4-05 abnormal-hours labels and normal after-hours sidecar overlap.",
            "summary": summary,
            "detector_contract": {
                "sigma_threshold": SIGMA_THRESHOLD,
                "min_abnormal_ratio": MIN_ABNORMAL_RATIO,
                "min_midnight_docs": MIN_MIDNIGHT_DOCS,
                "min_user_docs": MIN_USER_DOCS,
                "excluded_auto_sources": sorted(AUTO_SOURCES),
            },
            "anti_fitting_policy": [
                "Confirmed L4-05 labels are human user behavior only.",
                "System/automated/recurring sources are excluded from confirmed labels.",
                "normal_after_hours_context excludes all anomaly-labeled documents.",
                "Detector thresholds are recorded in sidecars for reproducible evaluation.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "FREEZE_V53_CANDIDATE.md").write_text(
        "# DataSynth v53 Candidate\n\n"
        "L4-05 abnormal-hours truth cleanup.\n\n"
        "- Source: `datasynth_v52_candidate`\n"
        "- Replaces `AbnormalHoursConcentration` labels with human-only confirmed cases.\n"
        "- Rebuilds `labels/abnormal_hours_concentration_cases*` with detector threshold metadata.\n"
        "- Rebuilds `labels/normal_after_hours_context*` excluding all anomaly-labeled documents.\n"
        "- Excludes automated/system/recurring/batch/interface sources from confirmed L4-05 labels.\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
