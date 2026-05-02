"""Rebuild DataSynth L4-03 high-amount rule truth from current detector contract.

This patch works in-place on ``data/journal/primary/datasynth``. It does not
mutate journal rows or injected anomaly labels. It rebuilds only the L4-03
review population / rule truth from the current journal using:

- amount_zscore > settings.zscore_threshold
- max(debit_amount, credit_amount) >= global amount quantile
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.anomaly_rules_simple import c08_amount_outlier  # noqa: E402
from src.feature.amount_features import _compute_base_amount, add_amount_zscore  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


DATASET = ROOT / "data" / "journal" / "primary" / "datasynth"
LABELS = DATASET / "labels"
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
    "posting_date",
    "gl_account",
    "debit_amount",
    "credit_amount",
]


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    year_key = df["fiscal_year"].astype(str).str.replace(r"\.0$", "", regex=True)
    for year in YEARS:
        year_df = df.loc[year_key.eq(str(year))].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _read_year(year: int) -> pd.DataFrame:
    path = DATASET / f"journal_entries_{year}.csv"
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
    rows = pd.concat([_read_year(year) for year in YEARS], ignore_index=True, sort=False)
    rows["posting_date"] = pd.to_datetime(rows["posting_date"], errors="coerce")
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    rows.attrs[SOURCE_PATH_ATTR] = str((DATASET / "journal_entries_2022.csv").resolve())
    return rows


def _add_l403_features(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    out.attrs[SOURCE_PATH_ATTR] = rows.attrs[SOURCE_PATH_ATTR]
    audit_rules = get_audit_rules()
    add_amount_zscore(
        out,
        _compute_base_amount(out),
        coa_prefixes=audit_rules.get("coa_category_prefixes"),
    )
    return out


def _clean_account(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


def _line_amount(rows: pd.DataFrame) -> pd.Series:
    debit = pd.to_numeric(rows["debit_amount"], errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(rows["credit_amount"], errors="coerce").fillna(0.0).abs()
    return pd.concat([debit, credit], axis=1).max(axis=1)


def _account_flags(accounts: pd.Series) -> dict[str, bool]:
    cleaned = _clean_account(accounts)
    return {
        "has_asset_line": bool(cleaned.str.startswith("1").any()),
        "has_liability_line": bool(cleaned.str.startswith("2").any()),
        "has_revenue_line": bool(cleaned.str.startswith("4").any()),
        "has_expense_line": bool(cleaned.str.startswith("5").any()),
        "has_cash_line": bool(cleaned.str.startswith(("100", "101", "102")).any()),
    }


def _period_boundary(values: pd.Series) -> bool:
    dates = pd.to_datetime(values, errors="coerce")
    if dates.dropna().empty:
        return False
    day = dates.dropna().dt.day
    return bool(day.le(5).any() or day.ge(26).any())


def _amount_band(amount: float, q90: float, q95: float, q99: float) -> str:
    if amount >= q99:
        return "global_p99_plus"
    if amount >= q95:
        return "global_p95_p99"
    if amount >= q90:
        return "global_p90_p95"
    return "below_guard"


def _bucket(zscore: float) -> str:
    if zscore >= 10.0:
        return "extreme_zscore"
    if zscore >= 5.0:
        return "strong_zscore"
    return "review_zscore"


def _build_l403_sets(rows: pd.DataFrame, flag: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = rows.copy()
    work["_flag"] = flag.fillna(False).astype(bool)
    work["_line_amount"] = _line_amount(work)
    work["_gl"] = _clean_account(work["gl_account"])

    q90 = float(work["_line_amount"].quantile(0.90))
    q95 = float(work["_line_amount"].quantile(0.95))
    q99 = float(work["_line_amount"].quantile(0.99))

    flagged = work.loc[work["_flag"]].copy()
    if flagged.empty:
        empty = pd.DataFrame()
        return empty, empty

    records: list[dict[str, object]] = []
    for document_id, group in flagged.groupby("document_id", sort=True):
        fiscal_year = str(group["fiscal_year"].iloc[0]).replace(".0", "")
        max_idx = group["_line_amount"].idxmax()
        max_amount = float(group.loc[max_idx, "_line_amount"])
        max_zscore = float(pd.to_numeric(group["amount_zscore"], errors="coerce").max())
        accounts = group["_gl"].dropna()
        flags = _account_flags(accounts)
        record = {
            "document_id": document_id,
            "fiscal_year": fiscal_year,
            "company_code": group["company_code"].iloc[0],
            "document_number": group["document_number"].iloc[0],
            "document_type": group["document_type"].iloc[0],
            "posting_date": str(group["posting_date"].iloc[0]),
            "business_process": group["business_process"].iloc[0],
            "source": group["source"].iloc[0],
            "created_by": group["created_by"].iloc[0],
            "approved_by": group["approved_by"].iloc[0],
            "line_count": int(group["document_id"].size),
            "flagged_row_count": int(group["_flag"].sum()),
            "max_amount_account": group.loc[max_idx, "_gl"],
            "max_line_amount": max_amount,
            "max_amount_zscore": round(max_zscore, 4),
            "amount_band": _amount_band(max_amount, q90, q95, q99),
            "zscore_bucket": _bucket(max_zscore),
            "is_period_boundary": _period_boundary(group["posting_date"]),
            "truth_basis": "L4-03 rule truth: amount_zscore above threshold and global amount guard passed",
            "evaluation_policy": "review anchor rule truth; injected high-amount anomalies remain sidecar subset",
            "truth_derivation": "src.detection.anomaly_rules_simple.c08_amount_outlier",
            **flags,
        }
        records.append(record)

    review = pd.DataFrame(records).sort_values(
        ["fiscal_year", "company_code", "document_number", "document_id"]
    ).reset_index(drop=True)
    per_year_seq = review.groupby("fiscal_year").cumcount() + 1
    review.insert(
        0,
        "case_id",
        [
            f"L403RULE-{year}-{seq:05d}"
            for year, seq in zip(review["fiscal_year"].astype(str), per_year_seq, strict=True)
        ],
    )
    review.insert(
        0,
        "population_id",
        [
            f"L403POP-{year}-{seq:05d}"
            for year, seq in zip(review["fiscal_year"].astype(str), per_year_seq, strict=True)
        ],
    )

    truth = review[
        [
            "document_id",
            "fiscal_year",
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "business_process",
            "source",
            "flagged_row_count",
            "max_line_amount",
            "max_amount_zscore",
            "amount_band",
            "zscore_bucket",
            "truth_basis",
            "evaluation_policy",
            "truth_derivation",
        ]
    ].copy()
    truth["rule_id"] = "L4-03"
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["evaluation_unit"] = "document"
    return review, truth


def _rebuild_combined_rule_truth(l403_truth: pd.DataFrame) -> pd.DataFrame:
    path = LABELS / "rule_truth.csv"
    if path.exists():
        combined = pd.read_csv(path, dtype=str, low_memory=False)
        combined = combined.loc[combined.get("rule_id", "").astype(str).ne("L4-03")].copy()
        if combined.empty:
            combined = l403_truth.copy()
        else:
            combined = pd.concat([combined, l403_truth], ignore_index=True, sort=False)
    else:
        combined = l403_truth.copy()
    combined.to_csv(path, index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth.json", combined)
    return combined


def main() -> None:
    if not DATASET.exists():
        raise SystemExit(f"missing dataset: {DATASET}")
    LABELS.mkdir(parents=True, exist_ok=True)

    old_review_path = LABELS / "high_amount_review_population.csv"
    old_review_count = (
        len(pd.read_csv(old_review_path, usecols=["document_id"], dtype=str))
        if old_review_path.exists()
        else 0
    )

    rows = _add_l403_features(_read_rows())
    settings = get_settings()
    flag = c08_amount_outlier(
        rows,
        zscore_threshold=settings.zscore_threshold,
        min_amount_quantile=settings.l403_min_amount_quantile,
    )
    review, truth = _build_l403_sets(rows, flag)

    _write_family("high_amount_review_population", review)
    _write_family("rule_truth_L4_03", truth)
    combined = _rebuild_combined_rule_truth(truth)

    summary = {
        "version": "v109",
        "base_dataset": "data/journal/primary/datasynth",
        "journal_rows_mutated": 0,
        "rule_truth_rebuilt": ["L4-03"],
        "zscore_threshold": float(settings.zscore_threshold),
        "min_amount_quantile": float(settings.l403_min_amount_quantile),
        "old_high_amount_review_docs": int(old_review_count),
        "new_high_amount_review_docs": int(review["document_id"].nunique()),
        "new_rule_truth_docs": int(truth["document_id"].nunique()),
        "new_rule_truth_by_year": {
            str(year): int(truth.loc[truth["fiscal_year"].astype(str).eq(str(year)), "document_id"].nunique())
            for year in YEARS
        },
        "zscore_bucket_counts": {
            str(k): int(v) for k, v in review["zscore_bucket"].value_counts().sort_index().items()
        },
        "amount_band_counts": {
            str(k): int(v) for k, v in review["amount_band"].value_counts().sort_index().items()
        },
        "combined_rule_truth_counts": {
            str(rule): int(count)
            for rule, count in combined.get("rule_id", pd.Series(dtype=str)).value_counts().sort_index().to_dict().items()
        },
        "anti_fitting_note": (
            "L4-03 truth is recomputed from the detector contract over the current journal. "
            "It is a Phase 1 review-anchor truth, not injected fraud truth."
        ),
    }

    (DATASET / "V109_L403_TRUTH_REALIGNMENT.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DATASET / "FREEZE_V109_CANDIDATE.md").write_text(
        "# DataSynth v109 Candidate\n\n"
        "Scope: rebuild L4-03 high-amount review population and rule truth from the current detector contract.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
