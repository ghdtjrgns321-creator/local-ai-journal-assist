"""Build v88 candidate by reducing over-heavy manual/adjustment source mix.

L3-02 truth is source-contract truth: manual or adjustment documents should be
flagged. v87 had ~74% manual/adjustment documents, which is too high for a
general ERP-like journal. This patch changes document source distribution and
rebuilds L3-02 truth from journal fields.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v87_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v88_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-02"
SOURCE_SENSITIVE_LABELS = {
    "SelfApproval",
    "SkippedApproval",
    "SegregationOfDutiesViolation",
}

# Realistic but still review-rich target ratios.
TARGET_MANUAL_ADJUST_RATIO = {
    "P2P": 0.18,
    "O2C": 0.18,
    "H2R": 0.28,
    "TRE": 0.30,
    "A2R": 0.42,
    "R2R": 0.46,
}

NON_MANUAL_SOURCE_CYCLE = {
    "P2P": ["automated", "interface", "recurring", "automated", "interface"],
    "O2C": ["automated", "interface", "recurring", "automated", "interface"],
    "H2R": ["automated", "recurring", "interface", "automated"],
    "TRE": ["automated", "interface", "automated", "recurring"],
    "A2R": ["automated", "recurring", "interface"],
    "R2R": ["automated", "recurring", "interface", "automated"],
}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_year_rows() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frame["_year_file"] = str(year)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _write_year_rows(rows: pd.DataFrame) -> None:
    write_cols = [col for col in rows.columns if col != "_year_file"]
    for year in YEARS:
        rows.loc[rows["_year_file"].astype(str).eq(str(year)), write_cols].to_csv(
            DEST / f"journal_entries_{year}.csv",
            index=False,
            encoding="utf-8",
        )
    rows[write_cols].to_csv(DEST / "journal_entries.csv", index=False, encoding="utf-8")


def _is_close_period(posting: pd.Series) -> pd.Series:
    day = pd.to_datetime(posting, errors="coerce").dt.day
    return day.ge(25) | day.le(5)


def _source_sensitive_docs() -> set[str]:
    protected: set[str] = set()
    path = LABELS / "anomaly_labels.csv"
    if path.exists():
        labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"])
        protected.update(
            labels.loc[labels["anomaly_type"].isin(SOURCE_SENSITIVE_LABELS), "document_id"]
            .dropna()
            .astype(str)
        )
    for sidecar_name in (
        "self_approval_review_population.csv",
        "skipped_approval_confirmed_anomalies.csv",
        "sod_confirmed_anomalies.csv",
    ):
        sidecar_path = LABELS / sidecar_name
        if sidecar_path.exists():
            sidecar = pd.read_csv(sidecar_path, dtype=str, usecols=["document_id"])
            protected.update(sidecar["document_id"].dropna().astype(str))
    return protected


def _choose_convert_docs_for_group(process_docs: pd.DataFrame, process: str, target_ratio: float, year: str) -> list[str]:
    manual_mask = process_docs["source"].fillna("").str.lower().isin(["manual", "adjustment"])
    current_manual = int(manual_mask.sum())
    target_manual = int(round(len(process_docs) * target_ratio))
    convert_count = max(0, current_manual - target_manual)
    if convert_count <= 0:
        return []

    candidates = process_docs.loc[manual_mask].copy()
    candidates["_close_period"] = _is_close_period(candidates["posting_date"])
    # Keep close-period, R2R/A2R, and anomaly-labelled manual docs more often by
    # converting lower-risk routine-looking docs first.
    candidates["_has_anomaly"] = candidates["anomaly_type"].fillna("").astype(str).str.strip().ne("")
    candidates["_sort"] = (
        candidates["_close_period"].astype(int).astype(str)
        + "|"
        + candidates["_has_anomaly"].astype(int).astype(str)
        + "|"
        + candidates["company_code"].fillna("")
        + "|"
        + candidates["document_number"].fillna("")
        + "|"
        + candidates["document_id"].astype(str)
        + "|"
        + process
        + "|"
        + year
    )
    selected = candidates.sort_values("_sort").head(convert_count)
    return selected["document_id"].astype(str).tolist()


def _choose_convert_docs(docs: pd.DataFrame, process: str, target_ratio: float) -> list[str]:
    process_docs = docs.loc[docs["business_process"].eq(process)].copy()
    if process_docs.empty:
        return []
    selected: list[str] = []
    for year, group in process_docs.groupby("fiscal_year", sort=True):
        selected.extend(_choose_convert_docs_for_group(group.copy(), process, target_ratio, str(year)))
    return selected


def _patch_sources(rows: pd.DataFrame) -> pd.DataFrame:
    docs = rows.drop_duplicates("document_id").copy()
    protected_docs = _source_sensitive_docs()
    docs = docs.loc[~docs["document_id"].astype(str).isin(protected_docs)].copy()
    patch_frames: list[pd.DataFrame] = []
    for process, ratio in TARGET_MANUAL_ADJUST_RATIO.items():
        doc_ids = _choose_convert_docs(docs, process, ratio)
        cycle = NON_MANUAL_SOURCE_CYCLE[process]
        if not doc_ids:
            continue
        selected = docs.loc[docs["document_id"].astype(str).isin(set(doc_ids))].copy()
        order = {doc_id: idx for idx, doc_id in enumerate(doc_ids)}
        selected["_patch_order"] = selected["document_id"].astype(str).map(order)
        selected = selected.sort_values("_patch_order").reset_index(drop=True)
        selected["source_before"] = selected["source"]
        selected["source_after"] = [cycle[idx % len(cycle)] for idx in range(len(selected))]
        selected["patch_reason"] = "reduce synthetic manual_adjustment overrepresentation"
        patch_frames.append(
            selected[
                [
                    "document_id",
                    "fiscal_year",
                    "company_code",
                    "document_number",
                    "business_process",
                    "source_before",
                    "source_after",
                    "patch_reason",
                ]
            ]
        )

    if not patch_frames:
        return pd.DataFrame()

    patch_log = pd.concat(patch_frames, ignore_index=True, sort=False)
    source_map = patch_log.set_index("document_id")["source_after"]
    row_doc = rows["document_id"].astype(str)
    mapped = row_doc.map(source_map)
    update_mask = mapped.notna()
    rows.loc[update_mask, "source"] = mapped.loc[update_mask].to_numpy()
    system_mask = update_mask & rows["source"].isin(["automated", "interface"])
    rows.loc[system_mask, "user_persona"] = "automated_system"
    return patch_log


def _doc_amount(rows: pd.DataFrame) -> pd.Series:
    debit = pd.to_numeric(rows["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(rows["credit_amount"], errors="coerce").fillna(0.0)
    return debit.where(debit.gt(0), credit)


def _build_l302_truth(rows: pd.DataFrame) -> pd.DataFrame:
    source = rows["source"].fillna("").str.lower()
    l302_rows = rows.loc[source.isin(["manual", "adjustment"])].copy()
    l302_rows["_line_amount"] = _doc_amount(l302_rows)
    truth = l302_rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        materiality_amount=("_line_amount", "sum"),
    )
    truth["rule_id"] = RULE_ID
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "manual or adjustment source population"
    truth["evaluation_unit"] = "document"
    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
        "created_by",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "materiality_amount",
    ]
    return truth[columns].sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _write_l302_truth(truth: pd.DataFrame) -> None:
    for stem in ("rule_truth_L3_02", "manual_entry_population_truth"):
        truth.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _rebuild_combined_rule_truth() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    # Avoid leaving a stale huge JSON copy from the source candidate. CSV is the
    # authoritative combined rule-truth file for these candidates.
    combined_json = LABELS / "rule_truth.json"
    if combined_json.exists():
        combined_json.unlink()
    return combined


def _source_summary(rows: pd.DataFrame) -> dict[str, object]:
    docs = rows.drop_duplicates("document_id").copy()
    docs["_manual_adjustment"] = docs["source"].fillna("").str.lower().isin(["manual", "adjustment"])
    by_year = docs.groupby("fiscal_year")["_manual_adjustment"].agg(["sum", "count", "mean"]).reset_index()
    by_process = docs.groupby("business_process")["_manual_adjustment"].agg(["sum", "count", "mean"]).reset_index()
    return {
        "source_counts": {str(k): int(v) for k, v in docs["source"].value_counts(dropna=False).to_dict().items()},
        "manual_adjustment_by_year": {
            str(row["fiscal_year"]): {
                "docs": int(row["sum"]),
                "total": int(row["count"]),
                "ratio": round(float(row["mean"]), 4),
            }
            for _, row in by_year.iterrows()
        },
        "manual_adjustment_by_process": {
            str(row["business_process"]): {
                "docs": int(row["sum"]),
                "total": int(row["count"]),
                "ratio": round(float(row["mean"]), 4),
            }
            for _, row in by_process.iterrows()
        },
    }


def main() -> None:
    _copy_candidate_safely()
    rows = _read_year_rows()
    before = _source_summary(rows)
    patch_log = _patch_sources(rows)
    truth = _build_l302_truth(rows)
    _write_l302_truth(truth)
    combined = _rebuild_combined_rule_truth()
    _write_year_rows(rows)

    if not patch_log.empty:
        patch_log.to_csv(LABELS / "l302_source_distribution_patch_log.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / "l302_source_distribution_patch_log.json", patch_log)

    after = _source_summary(rows)
    summary = {
        "candidate": "v88",
        "source": str(SOURCE.relative_to(ROOT)),
        "destination": str(DEST.relative_to(ROOT)),
        "purpose": "reduce manual/adjustment source overrepresentation and rebuild L3-02 truth",
        "patched_documents": int(len(patch_log)),
        "l302_truth_docs": int(truth["document_id"].nunique()),
        "before": before,
        "after": after,
        "combined_rule_truth_counts": {str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()},
    }
    (DEST / "V88_L302_SOURCE_DISTRIBUTION.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEST / "FREEZE_V88_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v88 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: reduce over-heavy manual/adjustment source distribution and rebuild L3-02 truth.",
                "",
                f"- Patched documents: `{summary['patched_documents']}`",
                f"- L3-02 truth docs: `{summary['l302_truth_docs']}`",
                f"- Source counts after: `{summary['after']['source_counts']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
