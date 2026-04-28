"""Build v63 manifest for SoD strict/review truth separation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v62_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v63_patch_manifest"
YEARS = (2022, 2023, 2024)


def _read_docs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "user_persona",
        "sod_violation",
        "sod_conflict_type",
    ]
    for year in YEARS:
        df = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False)
        frames.append(df)
    rows = pd.concat(frames, ignore_index=True)
    return rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        posting_date=("posting_date", "min"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        user_persona=("user_persona", "first"),
        sod_violation=("sod_violation", "first"),
        sod_conflict_type=("sod_conflict_type", "first"),
    )


def _true_mask(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _load_labels() -> pd.DataFrame:
    return pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)


def _write_json(path: Path, df: pd.DataFrame) -> None:
    path.write_text(json.dumps(df.where(pd.notna(df), None).to_dict(orient="records"), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sidecar(df: pd.DataFrame, stem: str) -> None:
    df.to_csv(MANIFEST_DIR / f"{stem}.csv", index=False)
    _write_json(MANIFEST_DIR / f"{stem}.json", df)
    for year in YEARS:
        subset = df.loc[df["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(MANIFEST_DIR / f"{stem}_{year}.csv", index=False)
        _write_json(MANIFEST_DIR / f"{stem}_{year}.json", subset)


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    docs = _read_docs()
    labels = _load_labels()
    confirmed_docs = set(labels.loc[labels["anomaly_type"].eq("SegregationOfDutiesViolation"), "document_id"].astype(str))
    broad = docs.loc[_true_mask(docs["sod_violation"])].copy()
    broad["was_sod_violation"] = True
    broad["truth_layer"] = broad["document_id"].astype(str).map(
        lambda doc_id: "confirmed_anomaly" if doc_id in confirmed_docs else "review_population"
    )
    broad["expected_l106_flag"] = broad["document_id"].astype(str).isin(confirmed_docs)

    confirmed = broad.loc[broad["document_id"].astype(str).isin(confirmed_docs)].copy()
    review = broad.loc[~broad["document_id"].astype(str).isin(confirmed_docs)].copy()

    patch = review[["document_id", "fiscal_year", "sod_violation", "sod_conflict_type"]].copy()
    patch["new_sod_violation"] = "false"
    patch["new_sod_conflict_type"] = ""
    patch["reason"] = "v63 separates broad SoD review population from strict SegregationOfDutiesViolation truth"
    patch.to_csv(MANIFEST_DIR / "journal_sod_patch_manifest.csv", index=False)

    sidecar_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "user_persona",
        "sod_conflict_type",
        "was_sod_violation",
        "expected_l106_flag",
        "truth_layer",
    ]
    _write_sidecar(review[sidecar_cols], "sod_review_population")
    _write_sidecar(confirmed[sidecar_cols], "sod_confirmed_anomalies")

    summary = {
        "candidate_version": "v63",
        "source_baseline": "data/journal/primary/datasynth_v62_candidate",
        "patch_scope": "Separate SoD strict labels from broad review population",
        "source_sod_true_docs": int(len(broad)),
        "confirmed_label_docs": int(len(confirmed_docs)),
        "confirmed_sod_docs": int(len(confirmed)),
        "review_population_docs": int(len(review)),
        "journal_docs_to_clear": int(len(patch)),
        "review_by_year": {str(k): int(v) for k, v in review["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "confirmed_by_year": {str(k): int(v) for k, v in confirmed["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "anti_fitting_note": "This patch does not change detector logic or sample detector hits. It corrects a truth-layer ambiguity by preserving broad SoD signals in a sidecar and reserving sod_violation=True for confirmed labels.",
    }
    (MANIFEST_DIR / "sod_contract_manifest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v63 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v62_candidate`\n\n"
        "Scope: split SoD broad review signals from strict L1-06 truth.\n\n"
        "- `sod_violation=True` becomes strict and must match `SegregationOfDutiesViolation` labels.\n"
        "- Former broad SoD records are preserved in `sod_review_population*` sidecars.\n"
        "- Confirmed labels are preserved in `sod_confirmed_anomalies*` sidecars.\n"
        "- Journal rows are changed only for non-confirmed broad SoD records.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
