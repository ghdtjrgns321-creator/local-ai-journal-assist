from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


WEEKEND_LEAK_DOC = "e4868bfb-1c51-47fa-9c8e-a01e0ef34447"
WEEKEND_CLAMP_DATE = "2024-12-28"
WEEKEND_CLAMP_DATETIME = "2024-12-28 15:36:46"
WEEKEND_CLAMP_DOCNUM = "C002-2024-WE-000001"

PERIOD_CONTROL_COUNTS = {
    2022: {"reopen_period": 18, "special_period_13": 9, "closing_adjustment_period": 13},
    2023: {"reopen_period": 21, "special_period_13": 11, "closing_adjustment_period": 15},
    2024: {"reopen_period": 23, "special_period_13": 12, "closing_adjustment_period": 18},
}

WEEKEND_CONTEXT_COUNTS = {
    2022: {"scheduled_batch": 44, "month_end_close": 23, "logistics_24h": 18},
    2023: {"scheduled_batch": 39, "month_end_close": 26, "logistics_24h": 21},
    2024: {"scheduled_batch": 42, "month_end_close": 29, "logistics_24h": 24},
}

PERIOD_REASON = {
    "reopen_period": "prior_period_reopen_after_close",
    "special_period_13": "special_period_or_adjustment_period",
    "closing_adjustment_period": "closing_adjustment_booked_to_control_period",
}

WEEKEND_REASON = {
    "scheduled_batch": "scheduled_weekend_erp_batch",
    "month_end_close": "normal_close_calendar_weekend",
    "logistics_24h": "warehouse_or_factory_24h_operation",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v36 DataSynth label-realism cleanup candidate.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v35_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


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


def _safe_bool_false(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.lower().isin(["false", "0", ""])


def remove_ghost_labels(output: Path, labels: pd.DataFrame, je_docs: set[str]) -> tuple[pd.DataFrame, list[dict]]:
    ghost_mask = ~labels["document_id"].astype(str).isin(je_docs)
    ghost = labels[ghost_mask].copy()
    records = ghost[
        ["anomaly_id", "anomaly_type", "document_id", "anomaly_date", "description"]
    ].to_dict("records")
    cleaned = labels[~ghost_mask].copy()
    labels_dir = output / "labels"
    if records:
        write_records(labels_dir / "removed_ghost_labels.csv", records)
        (labels_dir / "removed_ghost_labels.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cleaned, records


def clamp_2025_weekend_leak(output: Path, je: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    mask = je["document_id"].astype(str).eq(WEEKEND_LEAK_DOC)
    records: list[dict] = []
    if mask.any():
        before = je.loc[mask].iloc[0]
        je.loc[mask, "fiscal_year"] = 2024
        je.loc[mask, "fiscal_period"] = 12
        je.loc[mask, "posting_date"] = WEEKEND_CLAMP_DATETIME
        if "document_number" in je.columns:
            je.loc[mask, "document_number"] = WEEKEND_CLAMP_DOCNUM
        records.append(
            {
                "document_id": WEEKEND_LEAK_DOC,
                "previous_fiscal_year": int(before["fiscal_year"]),
                "patched_fiscal_year": 2024,
                "previous_fiscal_period": int(before["fiscal_period"]),
                "patched_fiscal_period": 12,
                "previous_posting_date": str(before["posting_date"]),
                "patched_posting_date": WEEKEND_CLAMP_DATETIME,
                "patch_reason": "clamp_weekend_posting_inside_2024_dataset_boundary",
            }
        )

    label_mask = labels["document_id"].astype(str).eq(WEEKEND_LEAK_DOC)
    for idx, row in labels[label_mask].iterrows():
        metadata = read_metadata(row.get("metadata_json", ""))
        metadata.update(
            {
                "v36_patch": "clamped_weekend_date_inside_dataset_boundary",
                "previous_new_date": metadata.get("new_date", "2025-01-04"),
                "new_date": WEEKEND_CLAMP_DATE,
            }
        )
        labels.at[idx, "anomaly_date"] = WEEKEND_CLAMP_DATE
        labels.at[idx, "description"] = "Moved posting from 2024-12-31 (Tue) to 2024-12-28 (Sat)"
        labels.at[idx, "metadata_json"] = dump_metadata(metadata)

    return je, labels, records


def add_wrongperiod_negative_controls(je: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    label_docs = set(labels["document_id"].dropna().astype(str))
    docs = je.drop_duplicates("document_id").copy()
    docs["posting_ts"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["posting_month"] = docs["posting_ts"].dt.month
    docs["is_period_end"] = docs["posting_ts"].dt.day.ge(26).fillna(False) | docs["posting_ts"].dt.day.le(5).fillna(False)
    usable = docs[
        docs["posting_ts"].notna()
        & docs["fiscal_year"].isin([2022, 2023, 2024])
        & ~docs["document_id"].astype(str).isin(label_docs)
        & _safe_bool_false(docs["is_anomaly"])
        & _safe_bool_false(docs["is_fraud"])
        & docs["fiscal_period"].eq(docs["posting_month"])
        & docs["source"].fillna("").astype(str).str.lower().isin(["manual", "adjustment", "automated", "recurring"])
    ].copy()

    rng = random.Random(3608)
    records: list[dict] = []
    used_docs: set[str] = set()
    for year, counts in PERIOD_CONTROL_COUNTS.items():
        year_pool = usable[usable["fiscal_year"].eq(year)].copy()
        doc_ids = list(year_pool["document_id"].astype(str))
        rng.shuffle(doc_ids)
        year_pool = year_pool.set_index(year_pool["document_id"].astype(str)).loc[doc_ids].reset_index(drop=True)
        for control_type, count in counts.items():
            picked = 0
            for _, row in year_pool.iterrows():
                doc_id = str(row["document_id"])
                if doc_id in used_docs:
                    continue
                if control_type == "closing_adjustment_period" and not bool(row["is_period_end"]):
                    continue
                posting_month = int(row["posting_month"])
                if control_type == "special_period_13":
                    patched_period = 13
                elif control_type == "reopen_period":
                    patched_period = 12 if posting_month == 1 else posting_month - 1
                else:
                    patched_period = 1 if posting_month == 12 else posting_month + 1
                records.append(
                    {
                        "document_id": doc_id,
                        "company_code": row["company_code"],
                        "fiscal_year": int(row["fiscal_year"]),
                        "posting_date": str(row["posting_ts"]),
                        "posting_month": posting_month,
                        "previous_fiscal_period": int(row["fiscal_period"]),
                        "patched_fiscal_period": int(patched_period),
                        "business_process": row["business_process"],
                        "source": row["source"],
                        "negative_control_type": control_type,
                        "normal_period_reason": PERIOD_REASON[control_type],
                        "anomaly_label_expected": "false",
                    }
                )
                used_docs.add(doc_id)
                picked += 1
                if picked >= count:
                    break
            if picked < count:
                raise RuntimeError(f"Only selected {picked}/{count} {control_type} controls for {year}")

    period_by_doc = {r["document_id"]: r["patched_fiscal_period"] for r in records}
    for doc_id, period in period_by_doc.items():
        je.loc[je["document_id"].astype(str).eq(doc_id), "fiscal_period"] = period
    return je, records


def build_weekend_context_sidecars(je: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    label_docs = set(labels["document_id"].dropna().astype(str))
    docs = je.drop_duplicates("document_id").copy()
    docs["posting_ts"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["is_weekend"] = docs["posting_ts"].dt.dayofweek.isin([5, 6]).fillna(False)
    docs["is_period_end"] = docs["posting_ts"].dt.day.ge(26).fillna(False) | docs["posting_ts"].dt.day.le(5).fillna(False)
    usable = docs[
        docs["is_weekend"]
        & docs["posting_ts"].notna()
        & docs["fiscal_year"].isin([2022, 2023, 2024])
        & ~docs["document_id"].astype(str).isin(label_docs)
        & _safe_bool_false(docs["is_anomaly"])
        & _safe_bool_false(docs["is_fraud"])
    ].copy()

    rng = random.Random(3615)
    records: list[dict] = []
    used_docs: set[str] = set()
    for year, counts in WEEKEND_CONTEXT_COUNTS.items():
        year_pool = usable[usable["fiscal_year"].eq(year)].copy()
        doc_ids = list(year_pool["document_id"].astype(str))
        rng.shuffle(doc_ids)
        year_pool = year_pool.set_index(year_pool["document_id"].astype(str)).loc[doc_ids].reset_index(drop=True)
        for control_type, count in counts.items():
            picked = 0
            for _, row in year_pool.iterrows():
                doc_id = str(row["document_id"])
                if doc_id in used_docs:
                    continue
                if control_type == "scheduled_batch" and str(row["source"]).lower() not in {"automated", "recurring"}:
                    continue
                if control_type == "month_end_close" and not bool(row["is_period_end"]):
                    continue
                if control_type == "logistics_24h" and row.get("business_process") not in {"P2P", "TRE", "A2R", "R2R"}:
                    continue
                records.append(
                    {
                        "document_id": doc_id,
                        "company_code": row["company_code"],
                        "fiscal_year": int(row["fiscal_year"]),
                        "posting_date": str(row["posting_ts"]),
                        "weekday": int(row["posting_ts"].dayofweek),
                        "document_number": row.get("document_number", ""),
                        "document_type": row.get("document_type", ""),
                        "business_process": row["business_process"],
                        "source": row["source"],
                        "created_by": row.get("created_by", ""),
                        "normal_weekend_reason": WEEKEND_REASON[control_type],
                        "weekend_context_type": control_type,
                        "expected_l305_raw_result": "flagged_fp_without_context",
                        "anomaly_label_expected": "false",
                    }
                )
                used_docs.add(doc_id)
                picked += 1
                if picked >= count:
                    break
            if picked < count:
                raise RuntimeError(f"Only selected {picked}/{count} {control_type} weekend controls for {year}")
    return records


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(records[0]) if records else []
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


def rewrite_label_jsons(labels_dir: Path, labels: pd.DataFrame) -> None:
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
                "severity": int(row["severity"]) if pd.notna(row["severity"]) else None,
                "description": row["description"],
                "related_entities": related,
                "monetary_impact": None
                if pd.isna(row.get("monetary_impact")) or row.get("monetary_impact") == ""
                else row.get("monetary_impact"),
                "metadata": metadata,
                "is_injected": bool(row["is_injected"]),
                "injection_strategy": row["injection_strategy"],
                "cluster_id": None
                if pd.isna(row.get("cluster_id")) or row.get("cluster_id") == ""
                else row.get("cluster_id"),
                "causal_reason": causal,
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
        "with_provenance": int(labels["causal_reason_json"].fillna("").astype(str).str.len().gt(0).sum()),
        "in_scenarios": int(labels["scenario_id"].fillna("").astype(str).str.len().gt(0).sum()),
        "in_clusters": int(labels["cluster_id"].fillna("").astype(str).str.len().gt(0).sum()),
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def patch_json_journal(output: Path) -> None:
    json_path = output / "journal_entries.json"
    if not json_path.exists():
        return
    tmp_path = output / "journal_entries.json.tmp"
    in_target_header = False
    with json_path.open("r", encoding="utf-8") as src, tmp_path.open("w", encoding="utf-8", newline="") as dst:
        for line in src:
            if f'"document_id": "{WEEKEND_LEAK_DOC}"' in line:
                in_target_header = True
            if in_target_header:
                line = line.replace('"fiscal_year": 2025', '"fiscal_year": 2024')
                line = line.replace('"fiscal_period": 1', '"fiscal_period": 12')
                line = line.replace('"posting_date": "2025-01-04"', f'"posting_date": "{WEEKEND_CLAMP_DATE}"')
                line = line.replace('"document_number": "C002-2025-000001"', f'"document_number": "{WEEKEND_CLAMP_DOCNUM}"')
                if '"lines": [' in line:
                    in_target_header = False
            dst.write(line)
    tmp_path.replace(json_path)


def rewrite_journal_csvs(output: Path, je: pd.DataFrame) -> None:
    je.to_csv(output / "journal_entries.csv", index=False)
    for old in output.glob("journal_entries_*.csv"):
        old.unlink()
    for year, year_df in je.groupby("fiscal_year"):
        if int(year) not in {2022, 2023, 2024}:
            raise RuntimeError(f"Unexpected fiscal_year after v36 cleanup: {year}")
        year_df.to_csv(output / f"journal_entries_{int(year)}.csv", index=False)


def update_json_summary(output: Path, summary: dict) -> None:
    (output / "V36_LABEL_REALISM_CLEANUP.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_preview(output: Path, summary: dict) -> None:
    text = f"""# DataSynth v36 Candidate

v36은 v35의 L3-06/L3-07 보강을 유지하면서 남은 라벨 정합성 및 과도하게 깨끗한 benchmark 문제를 정리한 후보 데이터입니다.

## 변경 요약

- 기준 데이터: `datasynth_v35_candidate`
- ghost `ReversedAmount` 라벨 제거: {summary['removed_ghost_labels']}건
- 2025 누출 문서 clamp: {summary['clamped_2025_docs']}건
- WrongPeriod 정상 negative control 추가: {summary['wrongperiod_negative_controls']['total']}건
- Weekend 정상 context sidecar 추가: {summary['weekend_context_controls']['total']}건

## 검증 결과

- ghost labels remaining: {summary['verification']['ghost_labels_remaining']}
- fiscal years in JE: {summary['verification']['journal_fiscal_years']}
- `journal_entries_2025.csv` exists: {summary['verification']['journal_entries_2025_exists']}
- period mismatch docs: {summary['verification']['period_mismatch_docs']}
- WrongPeriod labels: {summary['verification']['wrongperiod_labels']}
- WrongPeriod unlabeled negative controls: {summary['verification']['wrongperiod_unlabeled_mismatch_docs']}
- normal weekend sidecar docs: {summary['verification']['weekend_context_docs']}

## 생성 파일

- `labels/removed_ghost_labels.csv/json`
- `labels/wrongperiod_negative_controls.csv/json`
- `labels/wrongperiod_negative_controls_2022/2023/2024.csv/json`
- `labels/normal_weekend_context.csv/json`
- `labels/normal_weekend_context_2022/2023/2024.csv/json`
- `V36_LABEL_REALISM_CLEANUP.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V36_CANDIDATE.md").write_text(text, encoding="utf-8")


def verify(output: Path) -> dict:
    je = pd.read_csv(output / "journal_entries.csv", low_memory=False, parse_dates=["posting_date"])
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv", low_memory=False)
    je_docs = set(je["document_id"].astype(str))
    labels["doc_exists"] = labels["document_id"].astype(str).isin(je_docs)
    docs = je.drop_duplicates("document_id").copy()
    docs["posting_month"] = docs["posting_date"].dt.month
    docs["period_mismatch"] = docs["fiscal_period"].ne(docs["posting_month"])
    label_docs = set(labels["document_id"].astype(str))
    wp_label_docs = set(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].astype(str))
    wp_controls = pd.read_csv(output / "labels" / "wrongperiod_negative_controls.csv")
    weekend_context = pd.read_csv(output / "labels" / "normal_weekend_context.csv")
    return {
        "ghost_labels_remaining": int((~labels["doc_exists"]).sum()),
        "journal_fiscal_years": [int(x) for x in sorted(je["fiscal_year"].dropna().unique())],
        "journal_entries_2025_exists": (output / "journal_entries_2025.csv").exists(),
        "period_mismatch_docs": int(docs["period_mismatch"].sum()),
        "wrongperiod_labels": int(len(wp_label_docs)),
        "wrongperiod_unlabeled_mismatch_docs": int(
            docs[
                docs["period_mismatch"]
                & ~docs["document_id"].astype(str).isin(label_docs)
            ]["document_id"].nunique()
        ),
        "wrongperiod_control_overlap_labels": int(len(set(wp_controls["document_id"].astype(str)) & label_docs)),
        "weekend_context_docs": int(weekend_context["document_id"].nunique()),
        "weekend_context_overlap_labels": int(len(set(weekend_context["document_id"].astype(str)) & label_docs)),
    }


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if not source.exists():
        raise FileNotFoundError(source)
    if output.exists():
        if not args.force:
            raise FileExistsError(f"{output} already exists; pass --force to overwrite")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    je = pd.read_csv(output / "journal_entries.csv", low_memory=False)
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv", low_memory=False)
    je_docs = set(je["document_id"].astype(str))
    labels, ghost_records = remove_ghost_labels(output, labels, je_docs)
    je, labels, clamp_records = clamp_2025_weekend_leak(output, je, labels)
    je, wrongperiod_records = add_wrongperiod_negative_controls(je, labels)
    weekend_records = build_weekend_context_sidecars(je, labels)

    rewrite_journal_csvs(output, je)
    patch_json_journal(output)

    labels_dir = output / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    rewrite_label_jsons(labels_dir, labels)
    write_sidecar_family(labels_dir, "wrongperiod_negative_controls", wrongperiod_records)
    write_sidecar_family(labels_dir, "normal_weekend_context", weekend_records)

    summary = {
        "candidate_version": "v36_candidate",
        "source_baseline": "datasynth_v35_candidate",
        "removed_ghost_labels": len(ghost_records),
        "removed_ghost_label_types": dict(Counter(r["anomaly_type"] for r in ghost_records)),
        "clamped_2025_docs": len(clamp_records),
        "clamped_2025_records": clamp_records,
        "wrongperiod_negative_controls": {
            "total": len(wrongperiod_records),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in wrongperiod_records).items())},
            "by_type": {
                str(k): int(v) for k, v in sorted(Counter(r["negative_control_type"] for r in wrongperiod_records).items())
            },
        },
        "weekend_context_controls": {
            "total": len(weekend_records),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in weekend_records).items())},
            "by_type": {
                str(k): int(v) for k, v in sorted(Counter(r["weekend_context_type"] for r in weekend_records).items())
            },
        },
    }
    summary["verification"] = verify(output)
    update_json_summary(output, summary)
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
