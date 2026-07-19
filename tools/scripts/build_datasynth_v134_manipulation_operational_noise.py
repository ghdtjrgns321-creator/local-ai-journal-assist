"""Create an operational-noise manipulation split from the v133 freeze.

The manipulation truth documents are preserved. Only non-truth background
documents are softened so the dataset is useful for operational ranking demos,
not only hard-negative stress tests.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("data/journal/primary/datasynth_manipulation")
YEARS = (2022, 2023, 2024)

TARGET_KEEP = {
    "manual_context": 0.03,
    "period_context": 0.03,
    "weekend_context": 0.10,
    "afterhours_context": 0.10,
    "ic_context": 0.10,
}


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    path.write_text(df.to_json(orient="records", force_ascii=False, date_format="iso"), encoding="utf-8")


def _stable_bucket(values: pd.Series, modulo: int = 100) -> pd.Series:
    return values.astype(str).map(lambda value: sum(ord(ch) for ch in value) % modulo)


def _is_period_window(ts: pd.Series) -> pd.Series:
    dates = pd.to_datetime(ts, errors="coerce")
    month_end = dates + pd.offsets.MonthEnd(0)
    days_to_end = (month_end - dates).dt.days
    return dates.dt.day.le(5) | days_to_end.le(5)


def _is_weekend(ts: pd.Series) -> pd.Series:
    dates = pd.to_datetime(ts, errors="coerce")
    return dates.dt.dayofweek.ge(5)


def _is_afterhours(ts: pd.Series) -> pd.Series:
    dates = pd.to_datetime(ts, errors="coerce")
    return dates.dt.hour.ge(20) | dates.dt.hour.lt(6)


def _safe_midmonth_datetime(original: Any, doc_id: str) -> datetime:
    dt = pd.to_datetime(original, errors="coerce")
    if pd.isna(dt):
        year = 2022
        month = 6
    else:
        year = int(dt.year)
        month = int(dt.month)
    day = 10 + (sum(ord(ch) for ch in str(doc_id)) % 10)
    candidate = datetime(year, month, day, 10 + (sum(ord(ch) for ch in str(doc_id)) % 5), 15, 0)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _safe_midmonth_datetime_str(original: Any, doc_id: str) -> str:
    return _dt_str(_safe_midmonth_datetime(original, doc_id))


def _safe_midmonth_date_str(original: Any, doc_id: str) -> str:
    return _date_str(_safe_midmonth_datetime(original, doc_id))


def _safe_midmonth_period(original: Any, doc_id: str) -> int:
    return _safe_midmonth_datetime(original, doc_id).month


def _date_str(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _dt_str(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _doc_frame(df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    docs = []
    for year, df in df_by_year.items():
        d = df.sort_values("line_number").drop_duplicates("document_id").copy()
        d["_year_file"] = year
        docs.append(d)
    return pd.concat(docs, ignore_index=True)


def _context_counts(docs: pd.DataFrame, truth_docs: set[str]) -> dict[str, Any]:
    nontruth = docs[~docs["document_id"].astype(str).isin(truth_docs)].copy()
    post = nontruth["posting_date"]
    source = nontruth["source"].fillna("").astype(str).str.lower()
    partner = nontruth.get("trading_partner", pd.Series("", index=nontruth.index)).fillna("").astype(str)
    created = nontruth["created_by"].fillna("").astype(str)
    persona = nontruth["user_persona"].fillna("").astype(str).str.lower()
    flags = {
        "nontruth_docs": int(nontruth["document_id"].nunique()),
        "manual_or_adjustment_docs": int(nontruth.loc[source.isin({"manual", "adjustment"}), "document_id"].nunique()),
        "period_window_docs": int(nontruth.loc[_is_period_window(post), "document_id"].nunique()),
        "weekend_docs": int(nontruth.loc[_is_weekend(post), "document_id"].nunique()),
        "afterhours_docs": int(nontruth.loc[_is_afterhours(post), "document_id"].nunique()),
        "ic_partner_docs": int(nontruth.loc[partner.str.startswith("C-", na=False), "document_id"].nunique()),
        "human_created_docs": int(nontruth.loc[~created.isin({"SYSTEM", "SYSTEM_AUTO_APPROVED"}) & ~persona.eq("automated_system"), "document_id"].nunique()),
    }
    flags["proxy_review_union_docs"] = int(
        nontruth.loc[
            source.isin({"manual", "adjustment"})
            | _is_period_window(post)
            | _is_weekend(post)
            | _is_afterhours(post)
            | partner.str.startswith("C-", na=False),
            "document_id",
        ].nunique()
    )
    flags["proxy_review_union_rate"] = round(flags["proxy_review_union_docs"] / max(flags["nontruth_docs"], 1), 4)
    return flags


def _soften_background(df_by_year: dict[int, pd.DataFrame], truth_docs: set[str]) -> dict[str, Any]:
    before = _context_counts(_doc_frame(df_by_year), truth_docs)
    changed_docs: dict[str, int] = {
        "source_to_automated": 0,
        "date_to_midmonth_business_hours": 0,
        "ic_partner_to_vendor": 0,
    }
    for year, df in df_by_year.items():
        doc_rows = df.sort_values("line_number").drop_duplicates("document_id").copy()
        doc_ids = doc_rows["document_id"].astype(str)
        nontruth = ~doc_ids.isin(truth_docs)
        bucket = _stable_bucket(doc_ids)
        source_norm = doc_rows["source"].fillna("").astype(str).str.lower()
        posting = doc_rows["posting_date"]
        partner = doc_rows.get("trading_partner", pd.Series("", index=doc_rows.index)).fillna("").astype(str)

        manual_reduce_docs = set(
            doc_rows.loc[
                nontruth
                & source_norm.isin({"manual", "adjustment"})
                & bucket.ge(int(TARGET_KEEP["manual_context"] * 100)),
                "document_id",
            ].astype(str)
        )
        period_shift_docs = set(
            doc_rows.loc[
                nontruth
                & _is_period_window(posting)
                & bucket.ge(int(TARGET_KEEP["period_context"] * 100)),
                "document_id",
            ].astype(str)
        )
        weekend_shift_docs = set(
            doc_rows.loc[
                nontruth
                & _is_weekend(posting)
                & bucket.ge(int(TARGET_KEEP["weekend_context"] * 100)),
                "document_id",
            ].astype(str)
        )
        afterhours_shift_docs = set(
            doc_rows.loc[
                nontruth
                & _is_afterhours(posting)
                & bucket.ge(int(TARGET_KEEP["afterhours_context"] * 100)),
                "document_id",
            ].astype(str)
        )
        ic_reduce_docs = set(
            doc_rows.loc[
                nontruth
                & partner.str.startswith("C-", na=False)
                & bucket.ge(int(TARGET_KEEP["ic_context"] * 100)),
                "document_id",
            ].astype(str)
        )

        source_mask = df["document_id"].astype(str).isin(manual_reduce_docs)
        if source_mask.any():
            df.loc[source_mask, "source"] = "automated"
            df.loc[source_mask, "created_by"] = "SYSTEM"
            df.loc[source_mask, "user_persona"] = "automated_system"
            df.loc[source_mask, "approved_by"] = "SYSTEM_AUTO_APPROVED"
            changed_docs["source_to_automated"] += len(manual_reduce_docs)

        date_docs = period_shift_docs | weekend_shift_docs | afterhours_shift_docs
        changed_docs["date_to_midmonth_business_hours"] += len(date_docs)
        if date_docs:
            date_mask = df["document_id"].astype(str).isin(date_docs)
            doc_date_map = (
                df.loc[date_mask, ["document_id", "posting_date"]]
                .drop_duplicates("document_id")
                .assign(
                    safe_posting=lambda x: x.apply(
                        lambda row: _safe_midmonth_datetime_str(row["posting_date"], str(row["document_id"])), axis=1
                    ),
                    safe_date=lambda x: x.apply(
                        lambda row: _safe_midmonth_date_str(row["posting_date"], str(row["document_id"])), axis=1
                    ),
                    safe_period=lambda x: x.apply(
                        lambda row: _safe_midmonth_period(row["posting_date"], str(row["document_id"])), axis=1
                    ),
                )
                .set_index("document_id")
            )
            ids = df.loc[date_mask, "document_id"]
            df.loc[date_mask, "posting_date"] = ids.map(doc_date_map["safe_posting"]).values
            df.loc[date_mask, "document_date"] = ids.map(doc_date_map["safe_date"]).values
            df.loc[date_mask, "fiscal_period"] = ids.map(doc_date_map["safe_period"]).values
            if "approval_date" in df.columns:
                approved_mask = date_mask & df["approved_by"].notna() & df["approved_by"].astype(str).ne("")
                df.loc[approved_mask, "approval_date"] = df.loc[approved_mask, "document_id"].map(doc_date_map["safe_date"]).values
            if "delivery_date" in df.columns:
                delivery_mask = date_mask & df["delivery_date"].notna()
                df.loc[delivery_mask, "delivery_date"] = df.loc[delivery_mask, "document_id"].map(doc_date_map["safe_date"]).values

        ic_mask = df["document_id"].astype(str).isin(ic_reduce_docs)
        if ic_mask.any():
            vendor_values = df.loc[ic_mask, "company_code"].fillna("C001").astype(str).map(
                lambda company: f"V-{(sum(ord(ch) for ch in company) % 899999) + 100000:06d}"
            )
            df.loc[ic_mask, "trading_partner"] = vendor_values.values
            if "auxiliary_account_number" in df.columns:
                df.loc[ic_mask, "auxiliary_account_number"] = vendor_values.values
            if "auxiliary_account_label" in df.columns:
                df.loc[ic_mask, "auxiliary_account_label"] = vendor_values.values
            changed_docs["ic_partner_to_vendor"] += len(ic_reduce_docs)

    after = _context_counts(_doc_frame(df_by_year), truth_docs)
    return {"before": before, "after": after, "changed_docs": changed_docs}


def _refresh_metadata(base: Path, metrics: dict[str, Any]) -> None:
    meta_path = base / "validated_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["version"] = "v134_manipulation_operational_noise"
    meta["status"] = "pass"
    meta["generated_at"] = datetime.now().isoformat(timespec="seconds")
    meta["operational_noise_contract"] = {
        "base_version": "v133_manipulation_label_contract",
        "target": "lower non-truth review background while preserving manipulation truth",
        "metrics": metrics,
    }
    _write_json(meta_path, meta)
    _write_json(
        base / "V134_MANIPULATION_OPERATIONAL_NOISE.json",
        {
            "version": "v134_manipulation_operational_noise",
            "base_version": "v133_manipulation_label_contract",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "metrics": metrics,
        },
    )


def _update_preview(base: Path, metrics: dict[str, Any]) -> None:
    path = base / "PREVIEW.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("# DataSynth Manipulation v133", "# DataSynth Manipulation v134")
    insert = f"""

## Operational Noise Contract

This version preserves the 420 manipulation truth documents and lowers non-truth background review noise for operational ranking demos.

| Metric | Before | After |
|---|---:|---:|
| Non-truth proxy review union docs | {metrics['before']['proxy_review_union_docs']:,} | {metrics['after']['proxy_review_union_docs']:,} |
| Non-truth proxy review union rate | {metrics['before']['proxy_review_union_rate']:.2%} | {metrics['after']['proxy_review_union_rate']:.2%} |
| Manual/adjustment docs | {metrics['before']['manual_or_adjustment_docs']:,} | {metrics['after']['manual_or_adjustment_docs']:,} |
| Period-window docs | {metrics['before']['period_window_docs']:,} | {metrics['after']['period_window_docs']:,} |
| Weekend docs | {metrics['before']['weekend_docs']:,} | {metrics['after']['weekend_docs']:,} |
| After-hours docs | {metrics['before']['afterhours_docs']:,} | {metrics['after']['afterhours_docs']:,} |
| IC-partner docs | {metrics['before']['ic_partner_docs']:,} | {metrics['after']['ic_partner_docs']:,} |
"""
    if "## Operational Noise Contract" not in text:
        text += insert
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--write-json", action="store_true", help="Also rewrite large journal_entries*.json files.")
    args = parser.parse_args()
    base = args.data_dir
    truth = pd.read_csv(base / "labels" / "manipulated_entry_truth.csv")
    truth_docs = set(truth["document_id"].astype(str))
    df_by_year = {year: pd.read_csv(base / f"journal_entries_{year}.csv", low_memory=False) for year in YEARS}
    metrics = _soften_background(df_by_year, truth_docs)
    combined = pd.concat([df_by_year[year] for year in YEARS], ignore_index=True)
    for year, df in df_by_year.items():
        df.to_csv(base / f"journal_entries_{year}.csv", index=False)
        if args.write_json:
            _write_json_records(base / f"journal_entries_{year}.json", df)
    combined.to_csv(base / "journal_entries.csv", index=False)
    if args.write_json:
        _write_json_records(base / "journal_entries.json", combined)
    _refresh_metadata(base, metrics)
    _update_preview(base, metrics)
    print(json.dumps({"version": "v134_manipulation_operational_noise", "metrics": metrics}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
