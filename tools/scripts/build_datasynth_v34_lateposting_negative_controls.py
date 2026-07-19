from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


NEGATIVE_CONTROL_COUNTS = {
    2022: {"boundary": 21, "business_delay": 13},
    2023: {"boundary": 24, "business_delay": 18},
    2024: {"boundary": 25, "business_delay": 26},
}

BUSINESS_REASONS = [
    "vendor_invoice_received_late",
    "tax_invoice_matching_delay",
    "goods_receipt_acceptance_pending",
    "project_milestone_acceptance_delay",
    "month_end_cutoff_review",
    "shared_service_backlog",
    "customer_credit_note_dispute",
    "supporting_document_reconciliation",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add L3-07 late-posting negative controls to a datasynth candidate."
    )
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v33_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def normalize_date(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d")


def normalize_datetime(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def select_candidates(je: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    label_docs = set(labels["document_id"].dropna().astype(str))
    doc = je.drop_duplicates("document_id").copy()
    doc["posting_ts"] = pd.to_datetime(doc["posting_date"], errors="coerce")
    doc["document_ts"] = pd.to_datetime(doc["document_date"], errors="coerce")
    doc["current_diff_days"] = (
        doc["posting_ts"].dt.normalize() - doc["document_ts"].dt.normalize()
    ).dt.days

    usable = doc[
        doc["posting_ts"].notna()
        & doc["document_id"].notna()
        & ~doc["document_id"].astype(str).isin(label_docs)
        & doc["current_diff_days"].between(-5, 30)
        & doc["is_anomaly"].fillna(False).astype(str).str.lower().isin(["false", "0", ""])
        & doc["is_fraud"].fillna(False).astype(str).str.lower().isin(["false", "0", ""])
        & doc["source"].fillna("").str.lower().isin(["manual", "automated", "recurring", "adjustment"])
        & doc["business_process"].fillna("").isin(["P2P", "O2C", "R2R", "TRE", "A2R"])
    ].copy()

    rng = random.Random(3407)
    selected: list[dict] = []
    used_docs: set[str] = set()
    for year, kinds in NEGATIVE_CONTROL_COUNTS.items():
        year_pool = usable[usable["fiscal_year"].eq(year)].copy()
        if year_pool.empty:
            raise RuntimeError(f"No usable candidates for {year}")

        # Stable shuffle without depending on pandas' random implementation.
        doc_ids = list(year_pool["document_id"].astype(str))
        rng.shuffle(doc_ids)
        shuffled = year_pool.set_index(year_pool["document_id"].astype(str)).loc[doc_ids].reset_index(drop=True)

        for kind, count in kinds.items():
            picked = 0
            for _, row in shuffled.iterrows():
                doc_id = str(row["document_id"])
                if doc_id in used_docs:
                    continue
                posting_ts = row["posting_ts"]
                max_delay = min(45, (posting_ts.normalize() - pd.Timestamp(f"{year}-01-01")).days)
                if kind == "boundary":
                    allowed = [d for d in range(20, 31) if d <= max_delay]
                else:
                    allowed = [d for d in range(31, 46) if d <= max_delay]
                if not allowed:
                    continue

                base = len(selected) + year + int(row.get("line_number", 0) or 0)
                delay_days = allowed[base % len(allowed)]
                reason = BUSINESS_REASONS[(base + len(doc_id)) % len(BUSINESS_REASONS)]
                patched_document_date = posting_ts.normalize() - pd.Timedelta(days=delay_days)
                selected.append(
                    {
                        "document_id": doc_id,
                        "fiscal_year": int(year),
                        "company_code": row.get("company_code", ""),
                        "business_process": row.get("business_process", ""),
                        "source": row.get("source", ""),
                        "document_type": row.get("document_type", ""),
                        "posting_date": normalize_datetime(posting_ts),
                        "previous_document_date": normalize_date(row["document_ts"])
                        if pd.notna(row["document_ts"])
                        else "",
                        "patched_document_date": normalize_date(patched_document_date),
                        "previous_diff_days": int(row["current_diff_days"])
                        if pd.notna(row["current_diff_days"])
                        else "",
                        "actual_diff_days": int(delay_days),
                        "negative_control_type": kind,
                        "normal_delay_reason": reason,
                        "anomaly_label_expected": "false",
                    }
                )
                used_docs.add(doc_id)
                picked += 1
                if picked >= count:
                    break
            if picked < count:
                raise RuntimeError(f"Only selected {picked}/{count} {kind} controls for {year}")
    return selected


def patch_journal(output: Path, records: list[dict]) -> pd.DataFrame:
    journal_csv = output / "journal_entries.csv"
    je = pd.read_csv(journal_csv, low_memory=False)
    by_doc = {record["document_id"]: record for record in records}
    for doc_id, record in by_doc.items():
        je.loc[je["document_id"].astype(str).eq(doc_id), "document_date"] = record["patched_document_date"]
    je.to_csv(journal_csv, index=False)
    for year, year_df in je.groupby("fiscal_year"):
        year_df.to_csv(output / f"journal_entries_{int(year)}.csv", index=False)
    return je


def patch_json_journal(output: Path, records: list[dict]) -> None:
    json_path = output / "journal_entries.json"
    if not json_path.exists():
        return
    by_doc = {record["document_id"]: record for record in records}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    entries = data.get("entries", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return
    for entry in entries:
        doc_id = str(entry.get("document_id", ""))
        if doc_id in by_doc:
            entry["document_date"] = by_doc[doc_id]["patched_document_date"]
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_sidecars(output: Path, records: list[dict]) -> dict:
    labels_dir = output / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "document_id",
        "fiscal_year",
        "company_code",
        "business_process",
        "source",
        "document_type",
        "posting_date",
        "previous_document_date",
        "patched_document_date",
        "previous_diff_days",
        "actual_diff_days",
        "negative_control_type",
        "normal_delay_reason",
        "anomaly_label_expected",
    ]
    csv_path = labels_dir / "lateposting_negative_controls.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    (labels_dir / "lateposting_negative_controls.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for year in sorted({record["fiscal_year"] for record in records}):
        year_records = [record for record in records if record["fiscal_year"] == year]
        with (labels_dir / f"lateposting_negative_controls_{year}.csv").open(
            "w", encoding="utf-8", newline=""
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(year_records)
        (labels_dir / f"lateposting_negative_controls_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    by_year = Counter(record["fiscal_year"] for record in records)
    by_type = Counter(record["negative_control_type"] for record in records)
    by_reason = Counter(record["normal_delay_reason"] for record in records)
    summary = {
        "candidate_version": "v34_candidate",
        "source_baseline": "datasynth_v33_candidate",
        "focus_rule": "L3-07",
        "purpose": "Add realistic unlabeled normal posting-document date gaps so L3-07 is not a perfect label-fitting benchmark.",
        "total_negative_controls": len(records),
        "by_year": {str(k): int(v) for k, v in sorted(by_year.items())},
        "by_negative_control_type": {k: int(v) for k, v in sorted(by_type.items())},
        "by_normal_delay_reason": {k: int(v) for k, v in sorted(by_reason.items())},
        "contract": {
            "boundary": "Normal unlabeled documents with posting_date - document_date between 20 and 30 days.",
            "business_delay": "Normal unlabeled documents with posting_date - document_date between 31 and 45 days and an explicit business reason.",
            "anomaly_labels": "No LatePosting/BackdatedEntry labels are added for these controls.",
        },
    }
    (output / "V34_LATEPOSTING_NEGATIVE_CONTROLS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def verify(output: Path, records: list[dict]) -> dict:
    je = pd.read_csv(
        output / "journal_entries.csv",
        low_memory=False,
        parse_dates=["posting_date", "document_date"],
    )
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv", low_memory=False)
    label_docs = set(labels["document_id"].dropna().astype(str))
    doc = je.drop_duplicates("document_id").copy()
    doc["diff_days"] = (
        doc["posting_date"].dt.normalize() - doc["document_date"].dt.normalize()
    ).dt.days
    control_docs = {record["document_id"] for record in records}
    control_doc = doc[doc["document_id"].astype(str).isin(control_docs)]
    unlabeled_long = doc[doc["diff_days"].abs().gt(30) & ~doc["document_id"].astype(str).isin(label_docs)]
    late_labels = set(labels.loc[labels["anomaly_type"].eq("LatePosting"), "document_id"].dropna().astype(str))
    late_doc = doc[doc["document_id"].astype(str).isin(late_labels)]
    return {
        "control_docs": int(control_doc["document_id"].nunique()),
        "control_labeled_overlap": int(len(control_docs & label_docs)),
        "business_delay_controls": int((control_doc["diff_days"] > 30).sum()),
        "boundary_controls": int(control_doc["diff_days"].between(20, 30).sum()),
        "unlabeled_abs_diff_gt_30_docs": int(unlabeled_long["document_id"].nunique()),
        "lateposting_labels": int(len(late_labels)),
        "lateposting_labels_actual_diff_gt_30": int((late_doc["diff_days"] > 30).sum()),
        "lateposting_labels_min_diff": int(late_doc["diff_days"].min()) if not late_doc.empty else None,
        "lateposting_labels_max_diff": int(late_doc["diff_days"].max()) if not late_doc.empty else None,
    }


def write_preview(output: Path, summary: dict, verification: dict) -> None:
    text = f"""# DataSynth v34 Candidate

v34는 v33의 L3-07 라벨-필드 정합성을 유지하면서, 실무형 negative control을 추가한 후보 데이터입니다.

## 변경 요약

- 기준 데이터: `datasynth_v33_candidate`
- 대상 룰: `L3-07` 전기일-문서일 장기 괴리
- 추가 문서: {summary['total_negative_controls']}개
- anomaly 라벨 추가: 없음
- 목적: `FP=0/FN=0`처럼 보이는 완전 매칭 benchmark를 깨고, 정상 장기 지연 문서를 별도로 식별 가능하게 함

## Negative Control 구성

- boundary: {summary['by_negative_control_type'].get('boundary', 0)}개, 정상 `diff=20~30일`
- business_delay: {summary['by_negative_control_type'].get('business_delay', 0)}개, 정상 `diff=31~45일`
- 연도 분포: {summary['by_year']}

## 검증 결과

- control docs: {verification['control_docs']}
- control/labeled overlap: {verification['control_labeled_overlap']}
- unlabeled abs(diff)>30 docs: {verification['unlabeled_abs_diff_gt_30_docs']}
- LatePosting labels actual diff>30: {verification['lateposting_labels_actual_diff_gt_30']} / {verification['lateposting_labels']}
- LatePosting diff range: {verification['lateposting_labels_min_diff']}~{verification['lateposting_labels_max_diff']}일

## 생성 파일

- `labels/lateposting_negative_controls.csv`
- `labels/lateposting_negative_controls.json`
- `labels/lateposting_negative_controls_2022.csv/json`
- `labels/lateposting_negative_controls_2023.csv/json`
- `labels/lateposting_negative_controls_2024.csv/json`
- `V34_LATEPOSTING_NEGATIVE_CONTROLS.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V34_CANDIDATE.md").write_text(text, encoding="utf-8")


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
    records = select_candidates(je, labels)
    patch_journal(output, records)
    patch_json_journal(output, records)
    summary = write_sidecars(output, records)
    verification = verify(output, records)
    summary["verification"] = verification
    (output / "V34_LATEPOSTING_NEGATIVE_CONTROLS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_preview(output, summary, verification)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
