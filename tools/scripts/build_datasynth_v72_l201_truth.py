"""Build v72 manifest for L2-01 just-below-threshold field truth."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v71_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v72_patch_manifest"
YEARS = (2022, 2023, 2024)
NEAR_RATIO = 0.90


def _load_limits() -> dict[str, float]:
    employees = json.loads((SOURCE_DIR / "master_data" / "employees.json").read_text(encoding="utf-8"))
    return {
        str(row.get("user_id", "")).strip(): float(row.get("approval_limit") or 0.0)
        for row in employees
        if str(row.get("user_id", "")).strip()
    }


def _read_docs() -> pd.DataFrame:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "approved_by",
        "debit_amount",
        "credit_amount",
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
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        approved_by=("approved_by", "first"),
        debit_total=("debit_amount", "sum"),
        credit_total=("credit_amount", "sum"),
        line_count=("document_id", "size"),
    )
    docs["document_amount"] = docs[["debit_total", "credit_total"]].max(axis=1)
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


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    limits = _load_limits()
    docs = _read_docs()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    label_docs = set(labels.loc[labels["anomaly_type"].eq("JustBelowThreshold"), "document_id"].dropna().astype(str))

    docs["approval_limit"] = docs["approved_by"].fillna("").astype(str).str.strip().map(limits)
    truth = docs.loc[
        docs["approval_limit"].notna()
        & docs["approval_limit"].gt(0)
        & docs["document_amount"].ge(docs["approval_limit"] * NEAR_RATIO)
        & docs["document_amount"].lt(docs["approval_limit"])
    ].copy()
    truth["ratio_to_limit"] = truth["document_amount"] / truth["approval_limit"]
    truth["gap_to_limit"] = truth["approval_limit"] - truth["document_amount"]
    truth["gap_ratio"] = truth["gap_to_limit"] / truth["approval_limit"]
    truth["is_audit_issue_label"] = truth["document_id"].astype(str).isin(label_docs)
    truth["rule_id"] = "L2-01"
    truth["truth_layer"] = "field_condition_truth"
    truth["truth_basis"] = "approval_limit * 0.9 <= max(sum(debit),sum(credit)) < approval_limit"
    truth["near_threshold_band"] = pd.cut(
        truth["ratio_to_limit"],
        bins=[0.0, 0.95, 0.99, 1.0],
        labels=["lower_band", "upper_band", "hairline_band"],
        include_lowest=True,
    ).astype(str)
    _write_sidecar(truth, "l201_just_below_threshold_truth")

    summary = {
        "candidate_version": "v72",
        "source_baseline": "data/journal/primary/datasynth_v71_candidate",
        "patch_scope": "L2-01 field truth uses actual approver-limit near-threshold condition",
        "l201_truth_docs": int(len(truth)),
        "just_below_threshold_audit_labels": int(len(label_docs)),
        "truth_label_intersection": int(truth["is_audit_issue_label"].sum()),
        "truth_by_year": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "truth_by_source": {str(k): int(v) for k, v in truth["source"].value_counts().to_dict().items()},
        "top_approvers": {str(k): int(v) for k, v in truth["approved_by"].value_counts().head(10).to_dict().items()},
        "anti_fitting_note": "L2-01 truth is derived from approver-limit field conditions, not from detector output or JustBelowThreshold causal labels.",
    }
    (MANIFEST_DIR / "v72_l201_truth_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v72 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v71_candidate`\n\n"
        "Scope: make L2-01 truth equal to actual approver-limit near-threshold condition.\n\n"
        "- Preserve `JustBelowThreshold` as causal/audit issue labels.\n"
        "- Add `labels/l201_just_below_threshold_truth.csv` as L2-01 field truth.\n"
        "- Include automated/recurring documents if they satisfy the same field condition.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
