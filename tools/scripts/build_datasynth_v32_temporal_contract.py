from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


MIDNIGHT_START = 22
MIDNIGHT_END = 6
NORMAL_AFTER_HOURS_TYPES = {"AfterHoursPosting"}
L4_05_TYPE = "AbnormalHoursConcentration"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build DataSynth v32 temporal contract candidate from v31.",
    )
    parser.add_argument("--source", required=True, help="Source dataset directory")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def is_midnight_hour(hour: pd.Series) -> pd.Series:
    return (hour >= MIDNIGHT_START) | (hour < MIDNIGHT_END)


def read_metadata(value: object) -> dict:
    if pd.isna(value) or str(value).strip() == "":
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def dump_metadata(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def doc_level_frame(journal_csv: Path) -> pd.DataFrame:
    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_date",
        "document_number",
        "document_type",
        "business_process",
        "created_by",
        "user_persona",
        "source",
        "approved_by",
        "approval_date",
    ]
    df = pd.read_csv(journal_csv, usecols=cols, low_memory=False)
    docs = df.drop_duplicates("document_id").copy()
    docs["posting_ts"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["approval_ts"] = pd.to_datetime(docs["approval_date"], errors="coerce")
    hour = docs["posting_ts"].dt.hour
    docs["is_after_hours"] = is_midnight_hour(hour).fillna(False)
    docs["is_weekend"] = docs["posting_ts"].dt.dayofweek.isin([5, 6]).fillna(False)
    docs["is_overtime"] = hour.ge(18).fillna(False) & hour.lt(MIDNIGHT_START).fillna(False)
    docs["time_zone_category"] = "normal"
    docs.loc[docs["is_overtime"], "time_zone_category"] = "overtime"
    docs.loc[docs["is_after_hours"], "time_zone_category"] = "midnight"
    approval_delta = (docs["approval_ts"].dt.normalize() - docs["posting_ts"].dt.normalize()).dt.days
    docs["rapid_approval"] = approval_delta.notna() & approval_delta.between(0, 1)
    docs["is_automated_source"] = (
        docs["source"].fillna("").astype(str).str.lower().isin({"automated", "recurring"})
        | docs["user_persona"].fillna("").astype(str).str.lower().eq("automated_system")
    )
    return docs


def write_records(path: Path, records: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_json(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_scalar(value: object) -> object:
    if pd.isna(value):
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def build_background_sidecars(output: Path, docs: pd.DataFrame, labels: pd.DataFrame) -> dict:
    label_types = labels.groupby("document_id")["anomaly_type"].apply(lambda s: "|".join(sorted(set(s)))).to_dict()
    l306_labeled_docs = set(labels.loc[labels["anomaly_type"].eq("AfterHoursPosting"), "document_id"])

    bg = docs[docs["is_after_hours"] & ~docs["document_id"].isin(l306_labeled_docs)].copy()
    records: list[dict] = []
    for _, row in bg.sort_values(["fiscal_year", "posting_date", "document_id"]).iterrows():
        anomaly_types = label_types.get(row["document_id"], "")
        records.append(
            {
                "document_id": row["document_id"],
                "company_code": row["company_code"],
                "fiscal_year": int(row["fiscal_year"]),
                "posting_date": normalize_scalar(row["posting_date"]),
                "posting_hour": int(row["posting_ts"].hour),
                "document_number": row["document_number"],
                "document_type": row["document_type"],
                "business_process": row["business_process"],
                "created_by": row["created_by"],
                "user_persona": row["user_persona"],
                "source": row["source"],
                "time_zone_category": "midnight",
                "normal_after_hours_context": anomaly_types == "",
                "background_temporal_pattern": True,
                "has_any_anomaly_label": anomaly_types != "",
                "anomaly_types": anomaly_types,
            }
        )

    fieldnames = list(records[0]) if records else [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "posting_hour",
        "document_number",
        "document_type",
        "business_process",
        "created_by",
        "user_persona",
        "source",
        "time_zone_category",
        "normal_after_hours_context",
        "background_temporal_pattern",
        "has_any_anomaly_label",
        "anomaly_types",
    ]
    labels_dir = output / "labels"
    write_records(labels_dir / "normal_after_hours_context.csv", records, fieldnames)
    write_json(labels_dir / "normal_after_hours_context.json", records)
    for year, year_records in _records_by_year(records).items():
        write_records(labels_dir / f"normal_after_hours_context_{year}.csv", year_records, fieldnames)
        write_json(labels_dir / f"normal_after_hours_context_{year}.json", year_records)

    return {
        "background_after_hours_docs": len(records),
        "normal_after_hours_context_docs": sum(1 for r in records if r["normal_after_hours_context"]),
        "background_year_counts": dict(Counter(str(r["fiscal_year"]) for r in records)),
    }


def _records_by_year(records: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for record in records:
        out.setdefault(int(record["fiscal_year"]), []).append(record)
    return dict(sorted(out.items()))


def build_l405_cases(docs: pd.DataFrame) -> list[dict]:
    work = docs[~docs["is_automated_source"]].copy()
    work["is_abnormal_time"] = work["is_after_hours"] | work["is_overtime"] | work["is_weekend"]
    stats = work.groupby("created_by").agg(
        total_docs=("document_id", "nunique"),
        abnormal_docs=("is_abnormal_time", "sum"),
        midnight_docs=("is_after_hours", "sum"),
        rapid_abnormal_docs=("rapid_approval", lambda s: int((s & work.loc[s.index, "is_abnormal_time"]).sum())),
    )
    stats["abnormal_ratio"] = stats["abnormal_docs"] / stats["total_docs"].clip(lower=1)
    qualified = stats[
        (stats["total_docs"] >= 20)
        & (stats["abnormal_docs"] >= 5)
        & (stats["midnight_docs"] >= 2)
        & (stats["rapid_abnormal_docs"] >= 1)
    ].copy()
    if qualified.empty:
        return []

    threshold = max(0.08, float(qualified["abnormal_ratio"].mean() + qualified["abnormal_ratio"].std(ddof=0)))
    target_users = set(qualified[qualified["abnormal_ratio"] >= threshold].index)
    if not target_users:
        target_users = set(qualified.sort_values("abnormal_ratio", ascending=False).head(5).index)

    candidates = work[
        work["created_by"].isin(target_users)
        & work["is_abnormal_time"]
        & work["rapid_approval"]
    ].copy()
    candidates["sort_key"] = (
        candidates["is_after_hours"].astype(int) * 3
        + candidates["is_weekend"].astype(int) * 2
        + candidates["is_overtime"].astype(int)
    )
    candidates = candidates.sort_values(["fiscal_year", "sort_key", "posting_date"], ascending=[True, False, True])

    records: list[dict] = []
    for year, group in candidates.groupby("fiscal_year"):
        limit = {2022: 8, 2023: 10, 2024: 9}.get(int(year), 5)
        for _, row in group.head(limit).iterrows():
            user_stat = qualified.loc[row["created_by"]]
            records.append(
                {
                    "document_id": row["document_id"],
                    "company_code": row["company_code"],
                    "fiscal_year": int(row["fiscal_year"]),
                    "posting_date": normalize_scalar(row["posting_date"]),
                    "posting_hour": int(row["posting_ts"].hour),
                    "document_number": row["document_number"],
                    "document_type": row["document_type"],
                    "business_process": row["business_process"],
                    "created_by": row["created_by"],
                    "source": row["source"],
                    "time_zone_category": row["time_zone_category"],
                    "rapid_approval": bool(row["rapid_approval"]),
                    "user_total_docs": int(user_stat["total_docs"]),
                    "user_abnormal_docs": int(user_stat["abnormal_docs"]),
                    "user_midnight_docs": int(user_stat["midnight_docs"]),
                    "user_abnormal_ratio": round(float(user_stat["abnormal_ratio"]), 6),
                    "l405_reason": "user_abnormal_time_concentration",
                }
            )
    return records


def append_l405_labels(labels: pd.DataFrame, cases: list[dict]) -> pd.DataFrame:
    if not cases:
        return labels

    existing = set(labels["document_id"].astype(str) + "|" + labels["anomaly_type"].astype(str))
    new_rows = []
    next_id = len(labels) + 1
    for case in cases:
        key = f"{case['document_id']}|{L4_05_TYPE}"
        if key in existing:
            continue
        metadata = {
            "l405_reason": case["l405_reason"],
            "time_zone_category": case["time_zone_category"],
            "posting_hour": str(case["posting_hour"]),
            "rapid_approval": str(case["rapid_approval"]).lower(),
            "user_abnormal_ratio": str(case["user_abnormal_ratio"]),
            "detector_contract": "l4_05_abnormal_hours_concentration",
        }
        new_rows.append(
            {
                "anomaly_id": f"V32-L405-{next_id:06d}",
                "anomaly_category": "Statistical",
                "anomaly_type": L4_05_TYPE,
                "document_id": case["document_id"],
                "document_type": "JE",
                "company_code": case["company_code"],
                "anomaly_date": str(case["posting_date"])[:10],
                "detection_timestamp": pd.Timestamp.now().isoformat(),
                "confidence": 1.0,
                "severity": 3,
                "description": "Abnormal hours concentration: user-level abnormal-time cluster with rapid approval",
                "is_injected": True,
                "monetary_impact": "",
                "related_entities": json.dumps([case["created_by"]], ensure_ascii=False),
                "cluster_id": "",
                "original_document_hash": "",
                "injection_strategy": L4_05_TYPE,
                "structured_strategy_type": "",
                "structured_strategy_json": "",
                "causal_reason_type": "UserTemporalConcentration",
                "causal_reason_json": json.dumps(
                    {"UserTemporalConcentration": {"created_by": case["created_by"]}},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": "",
                "run_id": "",
                "generation_seed": "",
                "metadata_json": dump_metadata(metadata),
            }
        )
        next_id += 1
    if not new_rows:
        return labels
    return pd.concat([labels, pd.DataFrame(new_rows)], ignore_index=True)


def rewrite_label_jsons(labels_dir: Path, labels: pd.DataFrame) -> None:
    category_by_type = dict(zip(labels["anomaly_type"], labels["anomaly_category"]))
    records = []
    for _, row in labels.iterrows():
        metadata = read_metadata(row.get("metadata_json", ""))
        related = []
        related_raw = row.get("related_entities", "")
        if pd.notna(related_raw) and str(related_raw).strip():
            try:
                parsed = json.loads(str(related_raw))
                related = parsed if isinstance(parsed, list) else [str(related_raw)]
            except json.JSONDecodeError:
                related = [str(related_raw)]
        causal = None
        causal_raw = row.get("causal_reason_json", "")
        if pd.notna(causal_raw) and str(causal_raw).strip():
            try:
                causal = json.loads(str(causal_raw))
            except json.JSONDecodeError:
                causal = None
        record = {
            "anomaly_id": row["anomaly_id"],
            "anomaly_type": {row["anomaly_category"]: row["anomaly_type"]},
            "document_id": row["document_id"],
            "document_type": row["document_type"],
            "company_code": row["company_code"],
            "anomaly_date": str(row["anomaly_date"]),
            "detection_timestamp": str(row["detection_timestamp"]),
            "confidence": row["confidence"],
            "severity": int(row["severity"]) if pd.notna(row["severity"]) else None,
            "description": row["description"],
            "related_entities": related,
            "monetary_impact": None if pd.isna(row.get("monetary_impact")) or row.get("monetary_impact") == "" else row.get("monetary_impact"),
            "metadata": metadata,
            "is_injected": bool(row["is_injected"]),
            "injection_strategy": row["injection_strategy"],
            "cluster_id": None if pd.isna(row.get("cluster_id")) or row.get("cluster_id") == "" else row.get("cluster_id"),
            "causal_reason": causal,
        }
        records.append(record)

    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "total_labels": int(len(labels)),
        "by_category": {k: int(v) for k, v in labels["anomaly_category"].value_counts().to_dict().items()},
        "by_company": {k: int(v) for k, v in labels["company_code"].value_counts().to_dict().items()},
        "with_provenance": int(labels["causal_reason_json"].fillna("").astype(str).str.len().gt(0).sum()),
        "in_scenarios": int(labels["scenario_id"].fillna("").astype(str).str.len().gt(0).sum()),
        "in_clusters": int(labels["cluster_id"].fillna("").astype(str).str.len().gt(0).sum()),
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def patch_labels(output: Path, docs: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    labels_dir = output / "labels"
    labels = pd.read_csv(labels_dir / "anomaly_labels.csv", low_memory=False)
    docs_by_id = docs.set_index("document_id")

    converted = Counter()
    for idx, row in labels[labels["anomaly_type"].eq("UnusualTiming")].iterrows():
        doc = docs_by_id.loc[row["document_id"]]
        metadata = read_metadata(row.get("metadata_json", ""))
        metadata.update(
            {
                "migrated_from": "UnusualTiming",
                "detector_contract": "l3_06_is_after_hours_only",
                "midnight_start": str(MIDNIGHT_START),
                "midnight_end": str(MIDNIGHT_END),
            }
        )
        if bool(doc["is_after_hours"]):
            labels.at[idx, "anomaly_type"] = "AfterHoursPosting"
            labels.at[idx, "injection_strategy"] = "AfterHoursPosting"
            labels.at[idx, "description"] = "After-hours posting: migrated from UnusualTiming under L3-06 contract"
            converted["UnusualTiming_to_AfterHoursPosting"] += 1
        elif bool(doc["is_weekend"]):
            labels.at[idx, "anomaly_type"] = "WeekendPosting"
            labels.at[idx, "injection_strategy"] = "WeekendPosting"
            labels.at[idx, "description"] = "Weekend posting: migrated from UnusualTiming under L3-06 contract"
            converted["UnusualTiming_to_WeekendPosting"] += 1
        labels.at[idx, "metadata_json"] = dump_metadata(metadata)

    cases = build_l405_cases(docs)
    labels = append_l405_labels(labels, cases)
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    rewrite_label_jsons(labels_dir, labels)

    l405_fields = list(cases[0]) if cases else [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "posting_hour",
        "document_number",
        "document_type",
        "business_process",
        "created_by",
        "source",
        "time_zone_category",
        "rapid_approval",
        "user_total_docs",
        "user_abnormal_docs",
        "user_midnight_docs",
        "user_abnormal_ratio",
        "l405_reason",
    ]
    write_records(labels_dir / "abnormal_hours_concentration_cases.csv", cases, l405_fields)
    write_json(labels_dir / "abnormal_hours_concentration_cases.json", cases)
    for year, year_records in _records_by_year(cases).items():
        write_records(labels_dir / f"abnormal_hours_concentration_cases_{year}.csv", year_records, l405_fields)
        write_json(labels_dir / f"abnormal_hours_concentration_cases_{year}.json", year_records)

    return labels, {
        **converted,
        "abnormal_hours_concentration_labels_added": len(cases),
        "abnormal_hours_concentration_year_counts": dict(Counter(str(c["fiscal_year"]) for c in cases)),
    }


def write_contract(output: Path, labels: pd.DataFrame, background_summary: dict, patch_summary: dict) -> None:
    counts = labels["anomaly_type"].value_counts()
    contract = {
        "candidate_version": "v32_candidate",
        "source_baseline": "datasynth_v31_candidate",
        "detector_contracts": {
            "L3-06": {
                "label_types": ["AfterHoursPosting"],
                "contract": "is_after_hours_only",
                "midnight_start": MIDNIGHT_START,
                "midnight_end": MIDNIGHT_END,
                "excluded_from_l3_06": ["UnusualTiming", "overtime"],
            },
            "L4-05": {
                "label_types": [L4_05_TYPE],
                "contract": "user_level_abnormal_hours_concentration",
                "excludes_automated_sources": True,
                "requires_rapid_approval_context": True,
            },
        },
        "label_counts": {
            "AfterHoursPosting": int(counts.get("AfterHoursPosting", 0)),
            "UnusualTiming": int(counts.get("UnusualTiming", 0)),
            L4_05_TYPE: int(counts.get(L4_05_TYPE, 0)),
        },
        "background_context": background_summary,
        "patch_summary": patch_summary,
    }
    (output / "V32_TEMPORAL_CONTRACT.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    preview = f"""# DataSynth v32 Candidate Preview

`datasynth_v32_candidate` updates the temporal detector contract for L3-06 and L4-05.

## L3-06 Contract

- `L3-06` uses `AfterHoursPosting` only.
- The time window is `22:00 <= posting hour` or `posting hour < 06:00`.
- `UnusualTiming` is not used as L3-06 ground truth in this candidate.
- Normal/background after-hours documents are separated into `labels/normal_after_hours_context*.csv`.

## L4-05 Contract

- `AbnormalHoursConcentration` labels are added for user-level abnormal-time concentration.
- Automated and recurring/system entries are excluded from the L4-05 case selection.
- Cases include rapid-approval context and user-level concentration stats.

## Snapshot

- `AfterHoursPosting`: `{int(counts.get('AfterHoursPosting', 0))}`
- `UnusualTiming`: `{int(counts.get('UnusualTiming', 0))}`
- `AbnormalHoursConcentration`: `{int(counts.get(L4_05_TYPE, 0))}`
- Background after-hours docs: `{background_summary['background_after_hours_docs']}`
- Normal after-hours context docs: `{background_summary['normal_after_hours_context_docs']}`
"""
    (output / "PREVIEW.md").write_text(preview, encoding="utf-8")

    freeze = f"""# Freeze Note

Version: `datasynth_v32_candidate`

## Scope

This candidate clarifies the temporal-rule data contract.

## Key Points

- L3-06 maps to `AfterHoursPosting` only.
- Normal after-hours background remains in the data and is exposed through sidecars.
- L4-05 gets explicit `AbnormalHoursConcentration` labels and case sidecars.
- Detector contract metadata is stored in `V32_TEMPORAL_CONTRACT.json`.

## Status

Candidate only. Not yet promoted to `data/journal/primary/datasynth/`.
"""
    (output / "FREEZE_V32_CANDIDATE.md").write_text(freeze, encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output already exists: {output}")
        shutil.rmtree(output)
    shutil.copytree(source, output)
    for stale_name in (
        "FREEZE_V31_CANDIDATE.md",
        "V31_L304_SUMMARY.json",
    ):
        stale_path = output / stale_name
        if stale_path.exists():
            stale_path.unlink()

    docs = doc_level_frame(output / "journal_entries.csv")
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv", low_memory=False)
    patched_labels, patch_summary = patch_labels(output, docs)
    background_summary = build_background_sidecars(output, docs, patched_labels)
    write_contract(output, patched_labels, background_summary, patch_summary)

    print(
        json.dumps(
            {
                "output": str(output),
                "patch_summary": patch_summary,
                "background_summary": background_summary,
                "label_counts": {
                    k: int(v)
                    for k, v in patched_labels["anomaly_type"].value_counts().items()
                    if k in {"AfterHoursPosting", "UnusualTiming", L4_05_TYPE}
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
