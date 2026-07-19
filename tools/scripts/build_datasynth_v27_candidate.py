"""Build DataSynth v27 candidate with L1-09 ApprovalDateMissing labels.

Source baseline is the latest DataSynth candidate when available so previously
fixed candidate-only improvements stay intact.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v26_candidate"
if not SOURCE_DIR.exists():
    SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v27_candidate"
APPROVAL_LABEL = "ApprovalDateMissing"
YEAR_TARGETS = {2022: 6, 2023: 8, 2024: 10}
SCENARIOS = (
    "manual_log_gap",
    "workflow_timestamp_drop",
    "approval_archive_missing",
)
PROCESS_SCENARIO = {
    "O2C": "manual_log_gap",
    "R2R": "manual_log_gap",
    "P2P": "workflow_timestamp_drop",
    "TRE": "workflow_timestamp_drop",
    "H2R": "approval_archive_missing",
    "A2R": "approval_archive_missing",
}


def _copy_source() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _document_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "min"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        document_number=("document_number", "first"),
        row_count=("document_id", "size"),
    )


def _eligible_documents(df: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    labeled_docs = set(labels.loc[labels["document_id"].notna(), "document_id"].astype(str))
    doc = _document_frame(df)
    approved = doc["approved_by"].fillna("").astype(str).str.strip().ne("")
    has_date = doc["approval_date"].fillna("").astype(str).str.strip().ne("")
    eligible = doc.loc[
        ~doc["document_id"].astype(str).isin(labeled_docs)
        & approved
        & has_date
        & doc["fiscal_year"].isin(list(YEAR_TARGETS))
        & doc["source"].isin(["manual", "adjustment"])
        & doc["row_count"].between(2, 8)
    ].copy()
    eligible["source_rank"] = eligible["source"].map({"manual": 0, "adjustment": 1}).fillna(9)
    eligible["process_rank"] = eligible["business_process"].map(
        {"P2P": 0, "O2C": 1, "R2R": 2, "H2R": 3, "TRE": 4, "A2R": 5}
    ).fillna(9)
    return eligible.sort_values(
        ["fiscal_year", "source_rank", "process_rank", "posting_date", "document_id"]
    ).reset_index(drop=True)


def _choose_documents(eligible: pd.DataFrame) -> pd.DataFrame:
    chosen: list[pd.DataFrame] = []
    for year, needed in YEAR_TARGETS.items():
        year_pool = eligible.loc[eligible["fiscal_year"].eq(year)].copy()
        if len(year_pool) < needed:
            raise RuntimeError(f"not enough eligible L1-09 candidates for {year}: {len(year_pool)} < {needed}")
        # Keep some process diversity, but do not force perfectly even 1-per-process splits.
        preferred_process_order = ["P2P", "O2C", "R2R", "H2R", "TRE", "A2R"]
        process_caps = {
            2022: {"P2P": 2, "O2C": 1, "R2R": 1, "H2R": 1, "TRE": 1},
            2023: {"P2P": 2, "O2C": 2, "R2R": 2, "H2R": 1, "TRE": 1},
            2024: {"P2P": 3, "O2C": 2, "R2R": 2, "H2R": 1, "TRE": 1, "A2R": 1},
        }.get(year, {})
        picks = []
        used_ids: set[str] = set()
        for process in preferred_process_order:
            cap = process_caps.get(process, 0)
            if cap <= 0:
                continue
            group = year_pool.loc[year_pool["business_process"].eq(process)].head(cap)
            if group.empty:
                continue
            picks.append(group)
            used_ids.update(group["document_id"].astype(str).tolist())
        picked = pd.concat(picks, ignore_index=True) if picks else pd.DataFrame(columns=year_pool.columns)
        if len(picked) < needed:
            remainder = year_pool.loc[~year_pool["document_id"].astype(str).isin(used_ids)].head(needed - len(picked))
            picked = pd.concat([picked, remainder], ignore_index=True)
        chosen.append(picked.head(needed))
    return pd.concat(chosen, ignore_index=True)


def _scenario_for_row(row: pd.Series, sequence: int) -> str:
    process = str(row.get("business_process") or "")
    source = str(row.get("source") or "")
    if process in PROCESS_SCENARIO:
        scenario = PROCESS_SCENARIO[process]
        if source == "adjustment" and scenario == "manual_log_gap":
            return "approval_archive_missing"
        return scenario
    return SCENARIOS[sequence % len(SCENARIOS)]


def _next_anomaly_ids(labels: pd.DataFrame, count: int) -> list[str]:
    numbers = labels["anomaly_id"].fillna("").astype(str).str.extract(r"ANO(\d+)")[0].dropna()
    max_num = int(numbers.astype(int).max()) if not numbers.empty else 0
    return [f"ANO{max_num + i:08d}" for i in range(1, count + 1)]


def _write_label_sidecars(labels: pd.DataFrame) -> None:
    labels_dir = TARGET_DIR / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = labels.where(pd.notna(labels), None).to_dict(orient="records")
    (labels_dir / "anomaly_labels.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "total_labels": len(labels),
        "by_anomaly_type": labels["anomaly_type"].value_counts().to_dict(),
        "by_category": labels["anomaly_category"].value_counts().to_dict() if "anomaly_category" in labels else {},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_year_splits(df: pd.DataFrame) -> None:
    for year in (2022, 2023, 2024, 2025):
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)]
        path = TARGET_DIR / f"journal_entries_{year}.csv"
        if subset.empty:
            if path.exists():
                path.unlink()
            continue
        subset.to_csv(path, index=False)


def _write_docs(validation: dict[str, object]) -> None:
    counts = validation["approval_date_missing_by_year"]
    scenarios = validation["scenario_counts"]
    preview = f"""# DataSynth v27 Candidate Preview

Status: candidate only. Production data remains unchanged.

## What Changed

`v27_candidate` adds L1-09 `ApprovalDateMissing` anomalies on top of the latest candidate baseline.

- `approved_by` stays populated.
- `approval_date` is blanked for selected labeled documents.
- Labels are attached at document level.
- A sidecar records the original approval date and injection scenario.

## L1-09 Counts

- Total labeled docs: `{validation["approval_date_missing_labels"]}`
- `2022`: `{counts.get("2022", 0)}`
- `2023`: `{counts.get("2023", 0)}`
- `2024`: `{counts.get("2024", 0)}`

Scenario mix:

- `manual_log_gap`: `{scenarios.get("manual_log_gap", 0)}`
- `workflow_timestamp_drop`: `{scenarios.get("workflow_timestamp_drop", 0)}`
- `approval_archive_missing`: `{scenarios.get("approval_archive_missing", 0)}`

## Data Integrity Check

- Docs with approved_by and missing approval_date: `{validation["orphan_approval_docs"]}`
- L1-09 labels on those docs: `{validation["approval_date_missing_labels"]}`
- Labeled docs with blank approval_date: `{validation["labels_with_blank_date"]}`
- Labeled docs with approver retained: `{validation["labels_with_approver"]}`

## Sidecars

- `labels/approval_date_missing_cases.csv`
- `labels/approval_date_missing_cases.json`
- `V27_APPROVAL_DATE_MISSING_PATCH.json`
"""
    freeze = f"""# DataSynth v27 Candidate

Status: candidate, not production.

Source baseline: `{SOURCE_DIR.relative_to(ROOT).as_posix()}`

## Purpose

Add L1-09 `ApprovalDateMissing` labeled cases with realistic retained approver metadata and missing approval timestamps.

## Summary

- Total L1-09 labels: `{validation["approval_date_missing_labels"]}`
- Pair/duplicate changes from earlier candidate baseline preserved: `yes`
- Docs with approved_by and missing approval_date after patch: `{validation["orphan_approval_docs"]}`
- Labeled docs with approver retained: `{validation["labels_with_approver"]}`
- Labeled docs with blank approval_date: `{validation["labels_with_blank_date"]}`

Year counts:

- `2022`: `{counts.get("2022", 0)}`
- `2023`: `{counts.get("2023", 0)}`
- `2024`: `{counts.get("2024", 0)}`
"""
    (TARGET_DIR / "PREVIEW.md").write_text(preview, encoding="utf-8")
    (TARGET_DIR / "FREEZE_V27_CANDIDATE.md").write_text(freeze, encoding="utf-8")


def main() -> None:
    _copy_source()
    df = pd.read_csv(TARGET_DIR / "journal_entries.csv", low_memory=False)
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv")

    eligible = _eligible_documents(df, labels)
    chosen = _choose_documents(eligible)
    anomaly_ids = _next_anomaly_ids(labels, len(chosen))

    cases: list[dict[str, object]] = []
    new_labels: list[dict[str, object]] = []

    for idx, row in chosen.reset_index(drop=True).iterrows():
        doc_id = str(row["document_id"])
        scenario = _scenario_for_row(row, idx)
        original_approval_date = row["approval_date"]
        df.loc[df["document_id"].astype(str).eq(doc_id), "approval_date"] = None
        cases.append(
            {
                "approval_date_missing_case_id": f"ADM-{idx + 1:03d}",
                "document_id": doc_id,
                "document_number": row["document_number"],
                "fiscal_year": int(row["fiscal_year"]),
                "company_code": row["company_code"],
                "document_type": row["document_type"],
                "business_process": row["business_process"],
                "source": row["source"],
                "approved_by": row["approved_by"],
                "original_approval_date": original_approval_date,
                "scenario": scenario,
            }
        )
        new_labels.append(
            {
                "anomaly_id": anomaly_ids[idx],
                "anomaly_category": "ProcessIssue",
                "anomaly_type": APPROVAL_LABEL,
                "document_id": doc_id,
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": pd.to_datetime(row["posting_date"]).strftime("%Y-%m-%d"),
                "detection_timestamp": "2026-04-24 12:00:00",
                "confidence": 1.0,
                "severity": 3,
                "description": f"Approver present but approval_date missing ({scenario})",
                "is_injected": True,
                "monetary_impact": None,
                "related_entities": json.dumps([row["document_number"]], ensure_ascii=False),
                "cluster_id": None,
                "original_document_hash": None,
                "injection_strategy": APPROVAL_LABEL,
                "structured_strategy_type": None,
                "structured_strategy_json": None,
                "causal_reason_type": "EntityTargeting",
                "causal_reason_json": json.dumps(
                    {"EntityTargeting": {"target_type": "Document", "target_id": row["document_number"]}},
                    ensure_ascii=False,
                ),
                "parent_anomaly_id": None,
                "child_anomaly_ids": "[]",
                "scenario_id": None,
                "run_id": None,
                "generation_seed": None,
                "metadata_json": json.dumps(
                    {
                        "approved_by": row["approved_by"],
                        "original_approval_date": original_approval_date,
                        "scenario": scenario,
                        "document_number": row["document_number"],
                    },
                    ensure_ascii=False,
                ),
            }
        )

    new_labels_df = pd.DataFrame(new_labels).reindex(columns=labels.columns)
    labels = pd.concat([labels, new_labels_df], ignore_index=True)
    labels = labels.sort_values(["anomaly_date", "anomaly_id"], kind="stable").reset_index(drop=True)

    df.to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    _write_year_splits(df)
    _write_label_sidecars(labels)

    labels_dir = TARGET_DIR / "labels"
    cases_df = pd.DataFrame(cases)
    cases_df.to_csv(labels_dir / "approval_date_missing_cases.csv", index=False)
    (labels_dir / "approval_date_missing_cases.json").write_text(
        json.dumps(cases_df.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    doc = _document_frame(df)
    approved = doc["approved_by"].fillna("").astype(str).str.strip().ne("")
    missing = doc["approval_date"].fillna("").astype(str).str.strip().eq("")
    orphan_docs = doc.loc[approved & missing, "document_id"].astype(str)
    validation = {
        "approval_date_missing_labels": len(cases_df),
        "approval_date_missing_by_year": {
            str(k): int(v) for k, v in cases_df["fiscal_year"].value_counts().sort_index().to_dict().items()
        },
        "scenario_counts": {str(k): int(v) for k, v in cases_df["scenario"].value_counts().to_dict().items()},
        "orphan_approval_docs": int(len(orphan_docs)),
        "labels_with_blank_date": int(
            sum(doc.loc[doc["document_id"].astype(str).isin(cases_df["document_id"].astype(str)), "approval_date"].fillna("").astype(str).str.strip().eq(""))
        ),
        "labels_with_approver": int(
            sum(doc.loc[doc["document_id"].astype(str).isin(cases_df["document_id"].astype(str)), "approved_by"].fillna("").astype(str).str.strip().ne(""))
        ),
        "source_baseline": str(SOURCE_DIR.relative_to(ROOT).as_posix()),
    }
    (TARGET_DIR / "V27_APPROVAL_DATE_MISSING_PATCH.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
