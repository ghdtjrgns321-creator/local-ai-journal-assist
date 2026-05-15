"""Summarize Phase1 surface coverage for manipulation-v2 truth docs."""

# ruff: noqa: E501,I001

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def normalize_risk(value: object) -> str:
    text = str(value)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.title()


def doc_risk(values: pd.Series) -> str:
    risks = {normalize_risk(value) for value in values}
    for level in ("High", "Medium", "Low"):
        if level in risks:
            return level
    return "Normal"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--phase1-cache", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("tests/datasynth_quality_gate3/results"))
    args = parser.parse_args()

    truth = pd.read_csv(args.dataset / "labels" / "manipulated_entry_truth.csv", dtype=str, low_memory=False)
    truth_docs = set(truth["document_id"].astype(str))
    with args.phase1_cache.open("rb") as handle:
        payload = pickle.load(handle)
    df = payload["df"]
    rows = df.loc[df["document_id"].astype(str).isin(truth_docs)].copy()
    if "risk_level" in rows.columns:
        doc_risk_df = rows.groupby("document_id", as_index=False).agg(risk_level=("risk_level", doc_risk))
    else:
        doc_risk_df = pd.DataFrame({"document_id": sorted(truth_docs), "risk_level": "Unknown"})
    for column in ("flagged_rules", "review_rules"):
        if column in rows.columns:
            has_signal = rows[column].fillna("").astype(str).str.strip().ne("")
            signal_docs = rows.loc[has_signal, ["document_id"]].drop_duplicates()
            doc_risk_df[f"has_{column}"] = doc_risk_df["document_id"].isin(set(signal_docs["document_id"].astype(str)))
    merged = truth.merge(doc_risk_df, on="document_id", how="left")
    crosstab = pd.crosstab(merged["manipulation_scenario"], merged["risk_level"]).reset_index()
    signal_summary = (
        merged.groupby("manipulation_scenario", as_index=False)
        .agg(
            truth_docs=("document_id", "nunique"),
            high_docs=("risk_level", lambda s: int((s == "High").sum())),
            medium_or_high_docs=("risk_level", lambda s: int(s.isin(["High", "Medium"]).sum())),
            signaled_docs=("has_flagged_rules", lambda s: int(s.fillna(False).sum())),
            review_signaled_docs=("has_review_rules", lambda s: int(s.fillna(False).sum())),
        )
        .sort_values("manipulation_scenario")
    )
    signal_summary["medium_or_high_rate"] = (
        signal_summary["medium_or_high_docs"] / signal_summary["truth_docs"].clip(lower=1)
    ).round(4)
    signal_summary["signaled_rate"] = (
        signal_summary["signaled_docs"] / signal_summary["truth_docs"].clip(lower=1)
    ).round(4)

    summary = {
        "dataset": str(args.dataset),
        "phase1_cache": str(args.phase1_cache),
        "truth_docs": int(len(truth_docs)),
        "truth_rows_in_phase1": int(len(rows)),
        "truth_docs_in_phase1": int(rows["document_id"].nunique()),
        "doc_risk_counts": {str(k): int(v) for k, v in merged["risk_level"].value_counts().sort_index().to_dict().items()},
        "docs_with_flagged_rules": int(merged["has_flagged_rules"].fillna(False).sum()) if "has_flagged_rules" in merged.columns else None,
        "docs_with_review_rules": int(merged["has_review_rules"].fillna(False).sum()) if "has_review_rules" in merged.columns else None,
        "note": "Manipulation truth is not a Phase1 rule contract; this is surface coverage only.",
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "manipulation_v2_phase1_surface_summary.json"
    crosstab_path = args.out_dir / "manipulation_v2_phase1_surface_risk_crosstab.csv"
    signal_path = args.out_dir / "manipulation_v2_phase1_surface_by_scenario.csv"
    report_path = args.out_dir / "manipulation_v2_phase1_surface.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    crosstab.to_csv(crosstab_path, index=False, encoding="utf-8")
    signal_summary.to_csv(signal_path, index=False, encoding="utf-8")
    report_path.write_text(
        "\n".join(
            [
                "# Manipulation V2 Phase1 Surface",
                "",
                f"- truth docs: `{summary['truth_docs']}`",
                f"- docs with flagged rules: `{summary['docs_with_flagged_rules']}`",
                f"- docs with review rules: `{summary['docs_with_review_rules']}`",
                "",
                "This is not an A-axis rule contract. Manipulation labels are scenario truth for downstream experiments.",
                "",
                "## By Scenario",
                "",
                signal_summary.to_markdown(index=False),
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
