"""Build v107 candidate by realigning L4-01 truth to current features.

Base: datasynth_v106_candidate.

This patch does not mutate journal rows. It rebuilds only L4-01 rule truth from
the current journal using the same feature generation and detector contract as
the application: is_revenue_account and amount_zscore > settings.zscore_threshold.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.fraud_rules_feature import b01_revenue_manipulation  # noqa: E402
from src.feature.amount_features import add_all_amount_features  # noqa: E402
from src.feature.pattern_features import add_all_pattern_features  # noqa: E402
from src.feature.time_features import add_all_time_features  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v106_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v107_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)

INPUT_COLUMNS = [
    "document_id",
    "fiscal_year",
    "company_code",
    "document_number",
    "document_type",
    "business_process",
    "source",
    "created_by",
    "approved_by",
    "approval_date",
    "posting_date",
    "document_date",
    "fiscal_period",
    "currency",
    "reference",
    "header_text",
    "line_text",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "description_quality",
]


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    for year in YEARS:
        year_df = df.loc[df["fiscal_year"].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(year))].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _read_year(year: int) -> pd.DataFrame:
    path = DEST / f"journal_entries_{year}.csv"
    available = pd.read_csv(path, nrows=0).columns.tolist()
    cols = [col for col in INPUT_COLUMNS if col in available]
    frame = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
    for col in INPUT_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = frame[INPUT_COLUMNS].copy()
    frame["fiscal_year"] = frame["fiscal_year"].fillna(str(year))
    return frame


def _read_rows() -> pd.DataFrame:
    rows = pd.concat([_read_year(year) for year in YEARS], ignore_index=True)
    for col in ("posting_date", "document_date"):
        rows[col] = pd.to_datetime(rows[col], errors="coerce")
    rows["fiscal_period"] = pd.to_numeric(rows["fiscal_period"], errors="coerce")
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    rows.attrs[SOURCE_PATH_ATTR] = str((DEST / "journal_entries_2022.csv").resolve())
    return rows


def _add_rule_features(rows: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    audit_rules = get_audit_rules()
    out = rows.copy()
    out.attrs[SOURCE_PATH_ATTR] = rows.attrs[SOURCE_PATH_ATTR]
    add_all_time_features(out, settings)
    add_all_amount_features(out, settings, audit_rules)
    add_all_pattern_features(out, audit_rules.get("patterns", {}))
    return out


def _doc_context(rows: pd.DataFrame) -> pd.DataFrame:
    context_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
    ]
    docs = (
        rows[context_cols]
        .dropna(subset=["document_id"])
        .drop_duplicates(subset=["document_id"], keep="first")
        .copy()
    )
    docs["posting_date"] = docs["posting_date"].astype(str)
    return docs


def _build_l401_truth(rows: pd.DataFrame, flag: pd.Series) -> pd.DataFrame:
    flagged = rows.loc[flag.fillna(False).astype(bool)].copy()
    docs = _doc_context(flagged) if not flagged.empty else _doc_context(rows).iloc[0:0].copy()
    if flagged.empty:
        docs["flagged_row_count"] = pd.Series(dtype="int64")
    else:
        counts = flagged.groupby("document_id", as_index=False).size().rename(columns={"size": "flagged_row_count"})
        docs = docs.merge(counts, on="document_id", how="left")
    docs["rule_id"] = "L4-01"
    docs["expected_hit"] = True
    docs["truth_layer"] = "rule_truth"
    docs["truth_basis"] = "actual revenue-account amount z-score rule candidate population"
    docs["evaluation_unit"] = "document"
    docs["truth_derivation"] = "src.detection.fraud_rules_feature.b01_revenue_manipulation"
    docs["source_candidate"] = "v107"
    return docs.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _build_review_sidecar(rows: pd.DataFrame, flag: pd.Series) -> pd.DataFrame:
    flagged = rows.loc[flag.fillna(False).astype(bool)].copy()
    if flagged.empty:
        return pd.DataFrame(
            columns=[
                "case_id",
                "document_id",
                "fiscal_year",
                "company_code",
                "document_number",
                "document_type",
                "posting_date",
                "business_process",
                "source",
                "matched_revenue_accounts",
                "max_amount_zscore",
                "revenue_line_count",
                "truth_basis",
            ]
        )

    work = flagged.copy()
    work["_gl"] = work["gl_account"].astype(str).str.replace(r"\.0$", "", regex=True)
    grouped = work.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        matched_revenue_accounts=("_gl", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        max_amount_zscore=("amount_zscore", "max"),
        revenue_line_count=("document_id", "size"),
    )
    grouped = grouped.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)
    grouped["case_id"] = [
        f"L401POP-{int(float(row.fiscal_year))}-{idx + 1:04d}"
        for idx, row in enumerate(grouped.itertuples(index=False))
    ]
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["truth_basis"] = "current feature-backed L4-01 revenue z-score review population"
    return grouped[
        [
            "case_id",
            "document_id",
            "fiscal_year",
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "business_process",
            "source",
            "matched_revenue_accounts",
            "max_amount_zscore",
            "revenue_line_count",
            "truth_basis",
        ]
    ]


def _build_boundary_controls(rows: pd.DataFrame, flag: pd.Series) -> pd.DataFrame:
    is_rev = rows["is_revenue_account"].fillna(False).astype(bool)
    zscore = pd.to_numeric(rows["amount_zscore"], errors="coerce").fillna(0.0)
    boundary = is_rev & ~flag.fillna(False).astype(bool) & zscore.gt(2.5) & zscore.le(3.0)
    work = rows.loc[boundary].copy()
    if work.empty:
        return pd.DataFrame()
    work["_gl"] = work["gl_account"].astype(str).str.replace(r"\.0$", "", regex=True)
    grouped = work.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        matched_revenue_accounts=("_gl", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        max_amount_zscore=("amount_zscore", "max"),
        revenue_line_count=("document_id", "size"),
    )
    grouped = grouped.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)
    grouped["case_id"] = [
        f"L401BC-{int(float(row.fiscal_year))}-{idx + 1:04d}"
        for idx, row in enumerate(grouped.itertuples(index=False))
    ]
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["normal_reason"] = "near_threshold_revenue_zscore_not_l401_rule_truth"
    grouped["truth_basis"] = "boundary control: revenue z-score <= threshold"
    return grouped[
        [
            "case_id",
            "document_id",
            "fiscal_year",
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "business_process",
            "source",
            "matched_revenue_accounts",
            "max_amount_zscore",
            "revenue_line_count",
            "truth_basis",
            "normal_reason",
        ]
    ]


def _rebuild_rule_truth_combined() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if path.stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth.json", combined)
    return combined


def main() -> None:
    _copy_candidate_safely()
    old_truth = pd.read_csv(LABELS / "rule_truth_L4_01.csv", dtype=str, low_memory=False)

    rows = _add_rule_features(_read_rows())
    settings = get_settings()
    flag = b01_revenue_manipulation(rows, zscore_threshold=settings.zscore_threshold)

    truth = _build_l401_truth(rows, flag)
    review = _build_review_sidecar(rows, flag)
    boundary = _build_boundary_controls(rows, flag)

    _write_family("rule_truth_L4_01", truth)
    _write_family("revenue_outlier_review_population", review)
    _write_family("revenue_outlier_boundary_controls", boundary)
    combined = _rebuild_rule_truth_combined()

    old_ids = set(old_truth["document_id"].dropna().astype(str))
    new_ids = set(truth["document_id"].dropna().astype(str))
    summary = {
        "version": "v107_candidate",
        "base_version": "v106_candidate",
        "journal_rows_mutated": 0,
        "rule_truth_rebuilt": ["L4-01"],
        "zscore_threshold": float(settings.zscore_threshold),
        "old_l401_truth_docs": int(len(old_ids)),
        "new_l401_truth_docs": int(len(new_ids)),
        "added_truth_docs": sorted(new_ids - old_ids),
        "removed_truth_docs": sorted(old_ids - new_ids),
        "review_population_docs": int(len(review)),
        "boundary_control_docs": int(len(boundary)),
        "combined_rule_truth_counts": {
            str(rule): int(count)
            for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()
        },
    }
    (DEST / "V107_L401_TRUTH_REALIGNMENT.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V107_CANDIDATE.md").write_text(
        "# DataSynth v107 Candidate\n\n"
        f"Source baseline: `{SOURCE.relative_to(ROOT).as_posix()}`.\n\n"
        "Scope: rebuild L4-01 rule truth from current feature-backed detector contract.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
