"""Preflight checks for DataSynth manipulation V7 fixed candidates.

The approval-lag probes are reported with deny-list awareness. If a probe is in
LEAKAGE_DENY_COLUMNS, its AUROC is diagnostic and does not block promotion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.preprocessing.constants import LEAKAGE_DENY_COLUMNS  # noqa: E402

DEFAULT_DATASET = (
    ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v7_candidate_fixed3"
)
DEFAULT_OUT_JSON = ROOT / "artifacts" / "datasynth_v7_fixed3_preflight_check.json"
DEFAULT_OUT_MD = ROOT / "artifacts" / "datasynth_v7_fixed3_preflight_check.md"


def _rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _union_csv(dataset: Path) -> pd.DataFrame:
    frames = []
    for year in (2022, 2023, 2024):
        path = dataset / f"journal_entries_{year}.csv"
        frames.append(pd.read_csv(path, low_memory=False))
    return pd.concat(frames, ignore_index=True)


def _load_truth(dataset: Path) -> pd.DataFrame:
    return pd.read_csv(dataset / "labels" / "manipulated_entry_truth.csv", low_memory=False)


def _oriented_auc(y: pd.Series, score: pd.Series) -> tuple[float | None, float | None]:
    valid = y.notna() & score.notna()
    if valid.sum() < 2 or y.loc[valid].nunique() < 2 or score.loc[valid].nunique() < 2:
        return None, None
    raw = float(roc_auc_score(y.loc[valid].astype(int), score.loc[valid].astype(float)))
    return raw, max(raw, 1.0 - raw)


def _doc_frame(journal: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    truth_docs = set(truth["document_id"].astype(str))
    df = journal.copy()
    df["document_id"] = df["document_id"].astype(str)
    df["is_truth"] = df["document_id"].isin(truth_docs)
    df["posting_dt"] = pd.to_datetime(df["posting_date"], errors="coerce")
    df["approval_dt"] = pd.to_datetime(df["approval_date"], errors="coerce")
    df["approval_lag_days_row"] = (df["approval_dt"] - df["posting_dt"]).dt.days
    df["approval_lag_abs_row"] = df["approval_lag_days_row"].abs()
    df["approval_before_posting_row"] = df["approval_lag_days_row"].lt(0)
    df["is_revenue_line"] = df["gl_account"].astype(str).str.startswith("4") & pd.to_numeric(
        df["credit_amount"], errors="coerce"
    ).gt(0)
    created = df["created_by"].fillna("").astype(str).str.strip()
    approved = df["approved_by"].fillna("").astype(str).str.strip()
    df["self_approval_false_row"] = created.eq(approved) & created.ne("") & df[
        "sod_violation"
    ].fillna("").astype(str).str.lower().eq("false")
    grouped = df.groupby("document_id", sort=False)
    return grouped.agg(
        is_truth=("is_truth", "max"),
        business_process=("business_process", "first"),
        document_type=("document_type", "first"),
        approval_lag_abs=("approval_lag_abs_row", "max"),
        approval_before_posting=("approval_before_posting_row", "max"),
        self_approval_false=("self_approval_false_row", "max"),
        has_revenue_line=("is_revenue_line", "max"),
    )


def build_report(dataset: Path) -> dict[str, Any]:
    journal = _union_csv(dataset)
    truth = _load_truth(dataset)
    docs = _doc_frame(journal, truth)
    y = docs["is_truth"].astype(int)

    lag_checks = {}
    for feature in ("approval_lag_abs", "approval_before_posting"):
        raw, oriented = _oriented_auc(y, pd.to_numeric(docs[feature], errors="coerce"))
        deny_listed = feature in LEAKAGE_DENY_COLUMNS
        lag_checks[feature] = {
            "raw_auroc": raw,
            "oriented_auroc": oriented,
            "target": "<0.80 unless deny-listed",
            "deny_listed": deny_listed,
            "informational_only": deny_listed,
            "go_no_go_relevant": not deny_listed,
            "pass": deny_listed or (oriented is not None and oriented < 0.80),
        }

    o2c_docs = docs.loc[docs["business_process"].eq("O2C") & docs["document_type"].eq("DR")]
    o2c_missing = int((~o2c_docs["has_revenue_line"]).sum())
    sod_false = int(docs["self_approval_false"].sum())
    verdict = (
        all(row["pass"] for row in lag_checks.values())
        and o2c_missing == 0
        and sod_false == 0
    )
    return {
        "dataset": _rel(dataset),
        "go_no_go": "GO" if verdict else "NO-GO",
        "document_count": int(len(docs)),
        "truth_document_count": int(docs["is_truth"].sum()),
        "journal_rows": int(len(journal)),
        "cr_1a_approval_lag": lag_checks,
        "cr_1b_sod_violation": {"self_approval_false_rows": sod_false, "pass": sod_false == 0},
        "cr_1c_o2c_revenue": {
            "o2c_dr_docs": int(len(o2c_docs)),
            "missing_revenue_docs": o2c_missing,
            "pass": o2c_missing == 0,
        },
    }


def write_markdown(report: dict[str, Any], out: Path) -> None:
    lines = [
        "# DataSynth V7 fixed3 Preflight Check",
        "",
        f"- dataset: `{report['dataset']}`",
        f"- verdict: **{report['go_no_go']}**",
        "",
        "## CR-1A Approval Lag",
        "",
        "| feature | raw AUROC | oriented AUROC | deny-listed | GO/NO-GO relevant | verdict |",
        "|---|---:|---:|---|---|---|",
    ]
    for feature, row in report["cr_1a_approval_lag"].items():
        verdict = (
            "INFORMATIONAL"
            if row["informational_only"]
            else ("PASS" if row["pass"] else "FAIL")
        )
        lines.append(
            f"| {feature} | {row['raw_auroc']} | {row['oriented_auroc']} | "
            f"{row['deny_listed']} | {row['go_no_go_relevant']} | {verdict} |"
        )
    lines.extend([
        "",
        "## CR-1B/CR-1C",
        "",
        "- SOD self-approval false rows: "
        f"`{report['cr_1b_sod_violation']['self_approval_false_rows']}`",
        "- O2C DR missing revenue docs: "
        f"`{report['cr_1c_o2c_revenue']['missing_revenue_docs']}` / "
        f"`{report['cr_1c_o2c_revenue']['o2c_dr_docs']}`",
    ])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    report = build_report(Path(args.dataset))
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, out_md)
    print(
        json.dumps(
            {"out_json": _rel(out_json), "out_md": _rel(out_md), "verdict": report["go_no_go"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["go_no_go"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
