"""Build v69 manifest for L1 realism controls.

v69 is cumulative on v68. It does not create unlabeled field violations.
Instead it adds realistic normal/boundary controls and small approval-date
timing variation so the dataset is not only a clean contract fixture.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v68_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v69_patch_manifest"
YEARS = (2022, 2023, 2024)
APPROVAL_THRESHOLDS = (10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000)


def _stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def _read_docs() -> pd.DataFrame:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "approval_date",
        "fiscal_period",
        "debit_amount",
        "credit_amount",
        "gl_account",
        "line_text",
        "header_text",
    ]
    frames = []
    for year in YEARS:
        frame = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False)
        for col in ("debit_amount", "credit_amount"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        posting_date=("posting_date", "first"),
        document_date=("document_date", "first"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        fiscal_period=("fiscal_period", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
        row_count=("document_id", "size"),
        gl_accounts=("gl_account", lambda s: "|".join(sorted(set(s.dropna().astype(str).str.strip()))[:4])),
        line_text=("line_text", "first"),
        header_text=("header_text", "first"),
    )
    docs["document_amount"] = docs["debit_amount"]
    docs["posting_ts"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["posting_month"] = docs["posting_ts"].dt.month
    docs["posting_day"] = docs["posting_ts"].dt.day
    docs["fiscal_period_num"] = pd.to_numeric(docs["fiscal_period"], errors="coerce")
    docs["_sort"] = docs["document_id"].map(_stable_int)
    return docs


def _write_json(path: Path, df: pd.DataFrame) -> None:
    path.write_text(
        json.dumps(df.where(pd.notna(df), None).to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_sidecar(df: pd.DataFrame, stem: str) -> None:
    df.to_csv(MANIFEST_DIR / f"{stem}.csv", index=False)
    _write_json(MANIFEST_DIR / f"{stem}.json", df)
    for year in YEARS:
        subset = df.loc[df["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(MANIFEST_DIR / f"{stem}_{year}.csv", index=False)
        _write_json(MANIFEST_DIR / f"{stem}_{year}.json", subset)


def _near_threshold(amount: float) -> str:
    for threshold in APPROVAL_THRESHOLDS:
        if threshold * 0.75 <= amount < threshold:
            pct = amount / threshold
            return f"below_{threshold}_at_{pct:.2f}"
    return ""


def _new_approval_date(row: pd.Series) -> str:
    posting = pd.to_datetime(row["posting_date"], errors="coerce")
    if pd.isna(posting):
        posting = pd.Timestamp(f"{int(row['fiscal_year'])}-01-01")
    source = str(row["source"]).lower()
    seed = _stable_int(str(row["document_id"]))
    if source == "manual":
        offset = 2 + seed % 5
    elif source == "adjustment":
        offset = 1 + seed % 4
    elif source == "recurring":
        offset = seed % 4
    else:
        offset = 0 if seed % 100 < 85 else 1
    return (posting.normalize() + timedelta(days=offset)).strftime("%Y-%m-%d")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    docs = _read_docs()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    labeled_docs = set(labels["document_id"].dropna().astype(str))

    normal = docs.loc[~docs["document_id"].astype(str).isin(labeled_docs)].copy()
    has_approver = normal["approved_by"].fillna("").astype(str).str.strip().ne("")
    has_approval_date = normal["approval_date"].fillna("").astype(str).str.strip().ne("")
    manualish = normal["source"].fillna("").astype(str).str.lower().isin(["manual", "adjustment", "recurring"])
    delayed = normal.loc[has_approver & has_approval_date & manualish].sort_values(["fiscal_year", "_sort"]).copy()
    delayed = delayed.groupby("fiscal_year", group_keys=False).head(180).copy()
    delayed["old_approval_date"] = delayed["approval_date"]
    delayed["new_approval_date"] = delayed.apply(_new_approval_date, axis=1)
    delayed = delayed.loc[delayed["new_approval_date"].ne(delayed["old_approval_date"])].copy()
    delayed["control_type"] = "approval_date_delayed_but_present"
    delayed["normal_reason"] = "approval evidence exists but timestamp is delayed in a plausible workflow"

    period_boundary = normal.loc[
        normal["posting_day"].isin([1, 2, 28, 29, 30, 31])
        & normal["fiscal_period_num"].eq(normal["posting_month"])
    ].sort_values(["fiscal_year", "_sort"]).groupby("fiscal_year", group_keys=False).head(120).copy()
    period_boundary["control_type"] = "period_boundary_correct"
    period_boundary["normal_reason"] = "posting date is near period boundary but fiscal_period is correct"

    threshold_controls = normal.copy()
    threshold_controls["threshold_band"] = threshold_controls["document_amount"].map(_near_threshold)
    threshold_controls = threshold_controls.loc[threshold_controls["threshold_band"].ne("")].sort_values(
        ["fiscal_year", "_sort"]
    ).groupby("fiscal_year", group_keys=False).head(120).copy()
    threshold_controls["control_type"] = "approval_threshold_near_miss"
    threshold_controls["normal_reason"] = "amount is close to an approval threshold but does not cross it"

    text_controls = normal.loc[
        normal["line_text"].fillna("").astype(str).str.len().between(1, 8)
        | normal["header_text"].fillna("").astype(str).str.len().between(1, 8)
    ].sort_values(["fiscal_year", "_sort"]).groupby("fiscal_year", group_keys=False).head(80).copy()
    text_controls["control_type"] = "short_description_but_not_missing"
    text_controls["normal_reason"] = "description is terse but not missing or corrupted"

    patch_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "old_approval_date",
        "new_approval_date",
        "control_type",
        "normal_reason",
    ]
    delayed[patch_cols].to_csv(MANIFEST_DIR / "approval_date_delay_manifest.csv", index=False)

    common_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "approval_date",
        "fiscal_period",
        "document_amount",
        "row_count",
        "control_type",
        "normal_reason",
    ]
    for df in (period_boundary, threshold_controls, text_controls):
        for col in common_cols:
            if col not in df.columns:
                df[col] = ""
    delayed_controls = delayed.drop(columns=["approval_date"], errors="ignore").rename(
        columns={"new_approval_date": "approval_date"}
    )
    controls = pd.concat(
        [
            delayed_controls[common_cols],
            period_boundary[common_cols],
            threshold_controls[common_cols],
            text_controls[common_cols],
        ],
        ignore_index=True,
    ).drop_duplicates(["document_id", "control_type"])
    _write_sidecar(controls, "l1_realism_normal_controls")

    summary = {
        "candidate_version": "v69",
        "source_baseline": "data/journal/primary/datasynth_v68_candidate",
        "patch_scope": "L1 realism normal/boundary controls",
        "approval_date_delayed_docs": int(delayed["document_id"].nunique()),
        "normal_control_docs": int(controls["document_id"].nunique()),
        "normal_control_rows": int(len(controls)),
        "control_type_counts": controls["control_type"].value_counts().to_dict(),
        "anti_fitting_note": (
            "v69 adds normal lookalikes and timing variation without creating unlabeled confirmed field violations."
        ),
    }
    (MANIFEST_DIR / "v69_l1_realism_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v69 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v68_candidate`\n\n"
        "Scope: add L1 normal/boundary realism without breaking strict truth contracts.\n\n"
        "- Delay approval dates on selected normal approved documents.\n"
        "- Add period-boundary, threshold-near-miss, and terse-description normal controls.\n"
        "- Do not create unlabeled L1 field violations.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
