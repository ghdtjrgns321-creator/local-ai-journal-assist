from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


MIDNIGHT_START = 22
MIDNIGHT_END = 6

NEGATIVE_CONTROL_COUNTS = {
    2022: {"night_batch": 31, "global_ops": 17, "shift_work": 13, "month_end_interface": 11},
    2023: {"night_batch": 28, "global_ops": 23, "shift_work": 16, "month_end_interface": 12},
    2024: {"night_batch": 33, "global_ops": 19, "shift_work": 21, "month_end_interface": 15},
}

LIMITATION_COUNTS = {
    2022: {"date_only_time_loss": 5, "timezone_shift": 4},
    2023: {"date_only_time_loss": 6, "timezone_shift": 5},
    2024: {"date_only_time_loss": 7, "timezone_shift": 6},
}

CONTEXT_BY_TYPE = {
    "night_batch": {
        "normal_after_hours_reason": "scheduled_erp_batch",
        "operating_context": "nightly interface or settlement batch",
        "expected_l306_raw_result": "flagged_fp_without_context",
    },
    "global_ops": {
        "normal_after_hours_reason": "overseas_or_shared_service_timezone",
        "operating_context": "local business hour may appear as head-office midnight",
        "expected_l306_raw_result": "flagged_fp_without_timezone_context",
    },
    "shift_work": {
        "normal_after_hours_reason": "factory_logistics_24h_shift",
        "operating_context": "24-hour plant, warehouse, or logistics operation",
        "expected_l306_raw_result": "flagged_fp_without_shift_calendar",
    },
    "month_end_interface": {
        "normal_after_hours_reason": "month_end_automated_interface",
        "operating_context": "normal closing interface posted after cutoff",
        "expected_l306_raw_result": "flagged_review_candidate",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add L3-06 operational negative and limitation controls to a datasynth candidate."
    )
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v34_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def is_midnight_hour(hour: pd.Series) -> pd.Series:
    return (hour >= MIDNIGHT_START) | (hour < MIDNIGHT_END)


def normalize_scalar(value: object) -> object:
    if pd.isna(value):
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def load_docs(output: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    doc_cols = [
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
        "is_fraud",
        "fraud_type",
        "is_anomaly",
        "anomaly_type",
        "approved_by",
        "approval_date",
    ]
    je = pd.read_csv(output / "journal_entries.csv", usecols=doc_cols, low_memory=False)
    docs = je.drop_duplicates("document_id").copy()
    docs["posting_ts"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["posting_hour"] = docs["posting_ts"].dt.hour
    docs["is_after_hours"] = is_midnight_hour(docs["posting_hour"]).fillna(False)
    docs["is_weekend"] = docs["posting_ts"].dt.dayofweek.isin([5, 6]).fillna(False)
    docs["is_period_end"] = docs["posting_ts"].dt.day.ge(26).fillna(False) | docs["posting_ts"].dt.day.le(5).fillna(False)
    docs["is_automated_like"] = (
        docs["source"].fillna("").astype(str).str.lower().isin({"automated", "recurring"})
        | docs["user_persona"].fillna("").astype(str).str.lower().eq("automated_system")
    )
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv", low_memory=False)
    return docs, labels


def _safe_bool_false(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.lower().isin(["false", "0", ""])


def build_negative_controls(docs: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    label_types = labels.groupby("document_id")["anomaly_type"].apply(lambda s: "|".join(sorted(set(s)))).to_dict()
    label_docs = set(labels["document_id"].dropna().astype(str))
    afterhours_labels = set(labels.loc[labels["anomaly_type"].eq("AfterHoursPosting"), "document_id"].astype(str))
    usable = docs[
        docs["is_after_hours"]
        & docs["posting_ts"].notna()
        & ~docs["document_id"].astype(str).isin(label_docs)
        & ~docs["document_id"].astype(str).isin(afterhours_labels)
        & _safe_bool_false(docs["is_anomaly"])
        & _safe_bool_false(docs["is_fraud"])
    ].copy()
    if usable.empty:
        raise RuntimeError("No usable normal after-hours documents found")

    rng = random.Random(3506)
    records: list[dict] = []
    used_docs: set[str] = set()
    for year, counts in NEGATIVE_CONTROL_COUNTS.items():
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
                if control_type == "night_batch" and not bool(row["is_automated_like"]):
                    continue
                if control_type == "month_end_interface" and not bool(row["is_period_end"]):
                    continue
                if control_type == "shift_work" and row.get("business_process") not in {"P2P", "TRE", "A2R", "R2R"}:
                    continue
                ctx = CONTEXT_BY_TYPE[control_type]
                anomaly_types = label_types.get(doc_id, "")
                records.append(
                    {
                        "document_id": doc_id,
                        "company_code": row["company_code"],
                        "fiscal_year": int(row["fiscal_year"]),
                        "posting_date": normalize_scalar(row["posting_ts"]),
                        "posting_hour": int(row["posting_hour"]),
                        "document_number": row["document_number"],
                        "document_type": row["document_type"],
                        "business_process": row["business_process"],
                        "created_by": row["created_by"],
                        "user_persona": row["user_persona"],
                        "source": row["source"],
                        "negative_control_type": control_type,
                        "normal_after_hours_reason": ctx["normal_after_hours_reason"],
                        "operating_context": ctx["operating_context"],
                        "expected_l306_raw_result": ctx["expected_l306_raw_result"],
                        "has_any_anomaly_label": anomaly_types != "",
                        "anomaly_types": anomaly_types,
                    }
                )
                used_docs.add(doc_id)
                picked += 1
                if picked >= count:
                    break
            if picked < count:
                raise RuntimeError(f"Only selected {picked}/{count} {control_type} controls for {year}")
    return records


def build_limitation_controls(docs: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    afterhours_docs = set(labels.loc[labels["anomaly_type"].eq("AfterHoursPosting"), "document_id"].astype(str))
    pool = docs[docs["document_id"].astype(str).isin(afterhours_docs) & docs["posting_ts"].notna()].copy()
    if pool.empty:
        raise RuntimeError("No AfterHoursPosting labels available for limitation controls")

    rng = random.Random(3516)
    records: list[dict] = []
    used_docs: set[str] = set()
    for year, counts in LIMITATION_COUNTS.items():
        year_pool = pool[pool["fiscal_year"].eq(year)].copy()
        doc_ids = list(year_pool["document_id"].astype(str))
        rng.shuffle(doc_ids)
        year_pool = year_pool.set_index(year_pool["document_id"].astype(str)).loc[doc_ids].reset_index(drop=True)
        for limitation_type, count in counts.items():
            picked = 0
            for _, row in year_pool.iterrows():
                doc_id = str(row["document_id"])
                key = f"{doc_id}|{limitation_type}"
                if key in used_docs:
                    continue
                posting_ts = row["posting_ts"]
                if limitation_type == "date_only_time_loss":
                    degraded = posting_ts.normalize()
                    expected = "potential_fn_if_upload_is_date_only"
                    explanation = "ERP export drops time-of-day; L3-06 cannot reconstruct midnight posting."
                    timezone_offset = ""
                    local_hour = ""
                else:
                    offset = -8 if int(row["posting_hour"]) >= 22 else 9
                    shifted = posting_ts + pd.Timedelta(hours=offset)
                    degraded = shifted
                    expected = "potential_fn_or_fp_if_timezone_context_is_wrong"
                    explanation = "Head-office and local posting timezone differ; midnight status depends on timezone contract."
                    timezone_offset = offset
                    local_hour = int(shifted.hour)
                records.append(
                    {
                        "document_id": doc_id,
                        "company_code": row["company_code"],
                        "fiscal_year": int(row["fiscal_year"]),
                        "posting_date": normalize_scalar(posting_ts),
                        "posting_hour": int(row["posting_hour"]),
                        "simulated_observed_posting_date": normalize_scalar(degraded),
                        "simulated_observed_hour": "" if pd.isna(degraded) else int(degraded.hour),
                        "timezone_offset_hours": timezone_offset,
                        "local_hour_after_shift": local_hour,
                        "limitation_type": limitation_type,
                        "expected_l306_limitation": expected,
                        "limitation_explanation": explanation,
                        "source_label_type": "AfterHoursPosting",
                    }
                )
                used_docs.add(key)
                picked += 1
                if picked >= count:
                    break
            if picked < count:
                raise RuntimeError(f"Only selected {picked}/{count} {limitation_type} controls for {year}")
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
    for year in sorted({int(record["fiscal_year"]) for record in records}):
        year_records = [record for record in records if int(record["fiscal_year"]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def summarize(records: list[dict], type_col: str) -> dict:
    return {
        "total": len(records),
        "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in records).items())},
        f"by_{type_col}": {str(k): int(v) for k, v in sorted(Counter(r[type_col] for r in records).items())},
    }


def verify(output: Path, negative_records: list[dict], limitation_records: list[dict]) -> dict:
    docs, labels = load_docs(output)
    label_docs = set(labels["document_id"].dropna().astype(str))
    afterhours_labels = set(labels.loc[labels["anomaly_type"].eq("AfterHoursPosting"), "document_id"].astype(str))
    negative_docs = {record["document_id"] for record in negative_records}
    limitation_docs = {record["document_id"] for record in limitation_records}
    negative_doc = docs[docs["document_id"].astype(str).isin(negative_docs)]
    label_doc = docs[docs["document_id"].astype(str).isin(afterhours_labels)]
    return {
        "negative_control_docs": int(len(negative_docs)),
        "negative_controls_after_hours": int(negative_doc["is_after_hours"].sum()),
        "negative_controls_labeled_overlap": int(len(negative_docs & label_docs)),
        "negative_controls_afterhours_label_overlap": int(len(negative_docs & afterhours_labels)),
        "limitation_control_rows": int(len(limitation_records)),
        "limitation_source_docs": int(len(limitation_docs)),
        "limitation_source_afterhours_label_overlap": int(len(limitation_docs & afterhours_labels)),
        "afterhours_labels": int(len(afterhours_labels)),
        "afterhours_labels_actual_midnight": int(label_doc["is_after_hours"].sum()),
    }


def write_preview(output: Path, summary: dict) -> None:
    verification = summary["verification"]
    text = f"""# DataSynth v35 Candidate

v35는 v34 위에 L3-06 심야 전기 룰의 실무형 negative/limitation control을 추가한 후보 데이터입니다.

## 변경 요약

- 기준 데이터: `datasynth_v34_candidate`
- 대상 룰: `L3-06` 심야 전기
- 원장 본문 변경: 없음
- anomaly 라벨 추가: 없음
- 목적: `AfterHoursPosting` 계약 정합성은 유지하되, 정상 야간 운영과 시간정보 한계를 별도로 노출해 benchmark가 과하게 깨끗해지지 않게 함

## Negative Control

- 총 {summary['negative_controls']['total']}개
- 연도 분포: {summary['negative_controls']['by_year']}
- 유형 분포: {summary['negative_controls']['by_negative_control_type']}
- 의미: 라벨 없는 정상 심야 문서다. raw L3-06에서는 잡히는 것이 정상이며, context-adjusted 평가에서만 별도 해석한다.

## Limitation Control

- 총 {summary['limitation_controls']['total']}행
- 연도 분포: {summary['limitation_controls']['by_year']}
- 유형 분포: {summary['limitation_controls']['by_limitation_type']}
- 의미: 실제 JE를 훼손하지 않고, date-only export 또는 timezone 오류가 있을 때 L3-06 FN/FP가 생길 수 있음을 시뮬레이션 sidecar로 남긴다.

## 검증 결과

- negative controls after-hours: {verification['negative_controls_after_hours']} / {verification['negative_control_docs']}
- negative controls label overlap: {verification['negative_controls_labeled_overlap']}
- negative controls AfterHoursPosting overlap: {verification['negative_controls_afterhours_label_overlap']}
- limitation source docs overlapping AfterHoursPosting: {verification['limitation_source_afterhours_label_overlap']} / {verification['limitation_source_docs']}
- AfterHoursPosting labels actual midnight: {verification['afterhours_labels_actual_midnight']} / {verification['afterhours_labels']}

## 생성 파일

- `labels/afterhours_negative_controls.csv/json`
- `labels/afterhours_negative_controls_2022.csv/json`
- `labels/afterhours_negative_controls_2023.csv/json`
- `labels/afterhours_negative_controls_2024.csv/json`
- `labels/afterhours_limitation_controls.csv/json`
- `labels/afterhours_limitation_controls_2022.csv/json`
- `labels/afterhours_limitation_controls_2023.csv/json`
- `labels/afterhours_limitation_controls_2024.csv/json`
- `V35_AFTERHOURS_CONTROLS.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V35_CANDIDATE.md").write_text(text, encoding="utf-8")


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

    docs, labels = load_docs(output)
    negative_records = build_negative_controls(docs, labels)
    limitation_records = build_limitation_controls(docs, labels)
    labels_dir = output / "labels"
    write_sidecar_family(labels_dir, "afterhours_negative_controls", negative_records)
    write_sidecar_family(labels_dir, "afterhours_limitation_controls", limitation_records)

    summary = {
        "candidate_version": "v35_candidate",
        "source_baseline": "datasynth_v34_candidate",
        "focus_rule": "L3-06",
        "purpose": "Expose realistic normal after-hours activity and timestamp limitations without weakening the AfterHoursPosting label contract.",
        "negative_controls": summarize(negative_records, "negative_control_type"),
        "limitation_controls": summarize(limitation_records, "limitation_type"),
        "contract": {
            "afterhours_label_truth": "AfterHoursPosting remains the anomaly-label truth for L3-06 contract checks.",
            "raw_operational_score": "Normal after-hours controls should appear as raw L3-06 hits, not silently disappear.",
            "context_adjusted_score": "Controls may be separately explained after audit context review.",
            "limitation_controls": "Simulated date-only and timezone-shift cases document expected FN/FP risks without changing production JE rows.",
        },
    }
    summary["verification"] = verify(output, negative_records, limitation_records)
    (output / "V35_AFTERHOURS_CONTROLS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
