"""Audit DataSynth manipulation-v4 candidate guards.

The checks here are intentionally data-shape and accounting-substance checks.
They do not gate on Phase2 AUPRC or expected topic recall, because those are
model behavior measurements and would create fitting pressure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v4_candidate"
DEFAULT_OUT_JSON = ROOT / "artifacts" / "manipulation_v4_candidate_guard.json"
DEFAULT_OUT_MD = ROOT / "artifacts" / "manipulation_v4_candidate_guard.md"

SCENARIO_ALIAS = {
    "approval_sod_bypass": "approval_sod_bypass",
    "circular_related_party_transaction": "circular_related_party",
    "embezzlement_concealment": "embezzlement_concealment",
    "expense_capitalization": "expense_capitalization",
    "fictitious_entry": "fictitious_entry",
    "period_end_adjustment_manipulation": "period_end_adjustment",
    "suspense_account_abuse": "suspense_account_abuse",
    "unusual_timing_manipulation": "unusual_timing_manipulation",
}
SUSPENSE_ACCOUNTS = {"15110", "15120", "25110"}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype("string").str.lower().isin({"true", "1", "yes"})


def load_journal(data_dir: Path) -> pd.DataFrame:
    parts = []
    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "fiscal_period",
        "document_number",
        "document_date",
        "posting_date",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "local_amount",
        "source",
        "created_by",
        "approved_by",
        "business_process",
        "document_type",
        "supporting_doc_type",
        "has_attachment",
        "is_suspense_account",
        "settlement_status",
        "is_cleared",
        "amount_open",
    ]
    for year in (2022, 2023, 2024):
        path = data_dir / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        usecols = [col for col in cols if col in header]
        parts.append(
            pd.read_csv(path, usecols=usecols, low_memory=False, dtype={"gl_account": "string"})
        )
    df = pd.concat(parts, ignore_index=True)
    for col in ("debit_amount", "credit_amount", "local_amount", "amount_open"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in ("document_date", "posting_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def load_truth(data_dir: Path) -> pd.DataFrame:
    truth = pd.read_csv(data_dir / "labels" / "manipulated_entry_truth.csv")
    truth["document_id"] = truth["document_id"].astype(str)
    truth["scenario"] = (
        truth["manipulation_scenario"].map(SCENARIO_ALIAS).fillna(truth["manipulation_scenario"])
    )
    return truth


def doc_features(df: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["document_id"] = work["document_id"].astype(str)
    work["abs_amount"] = work[["debit_amount", "credit_amount", "local_amount"]].abs().max(axis=1)
    work["is_manual_source"] = work["source"].isin(["manual", "adjustment"])
    work["is_suspense_gl"] = work["gl_account"].astype("string").isin(SUSPENSE_ACCOUNTS)
    work["is_asset_gl"] = work["gl_account"].astype("string").str.startswith("15", na=False)
    work["is_expense_gl"] = work["gl_account"].astype("string").str.startswith("8", na=False)
    work["is_revenue_gl"] = work["gl_account"].astype("string").str.startswith("4", na=False)
    work["is_ar_or_cash_gl"] = (
        work["gl_account"].astype("string").str.startswith(("10", "11"), na=False)
    )
    work["is_etc_support"] = work.get("supporting_doc_type", "").astype("string").eq("기타증빙")
    work["is_suspense_marker"] = _bool_series(work.get("is_suspense_account", pd.Series("")))
    work["long_aging_days"] = (work["posting_date"] - work["document_date"]).dt.days
    work["hour"] = work["posting_date"].dt.hour
    work["dow"] = work["posting_date"].dt.dayofweek
    work["f_weekend"] = work["dow"].isin([5, 6])
    work["f_offhour"] = work["hour"].lt(8) | work["hour"].ge(20)
    work["f_self_approval"] = work["approved_by"].notna() & work["approved_by"].eq(
        work["created_by"]
    )

    agg = work.groupby("document_id", dropna=False).agg(
        company_code=("company_code", "first"),
        fiscal_year=("fiscal_year", "first"),
        fiscal_period=("fiscal_period", "first"),
        source=("source", "first"),
        f_manual=("is_manual_source", "max"),
        f_weekend=("f_weekend", "max"),
        f_offhour=("f_offhour", "max"),
        f_self_approval=("f_self_approval", "max"),
        max_abs_amount=("abs_amount", "max"),
        n_lines=("gl_account", "size"),
        has_suspense_gl=("is_suspense_gl", "max"),
        has_asset_gl=("is_asset_gl", "max"),
        has_expense_gl=("is_expense_gl", "max"),
        has_revenue_gl=("is_revenue_gl", "max"),
        has_ar_or_cash_gl=("is_ar_or_cash_gl", "max"),
        etc_support=("is_etc_support", "max"),
        suspense_marker=("is_suspense_marker", "max"),
        max_aging_days=("long_aging_days", "max"),
        settlement_status=(
            "settlement_status",
            lambda s: ",".join(sorted(set(s.dropna().astype(str)))),
        ),
    )
    agg = agg.reset_index()
    agg = agg.merge(
        truth[["document_id", "scenario", "manipulation_scenario"]], on="document_id", how="left"
    )
    agg["scenario"] = agg["scenario"].fillna("normal")
    return agg


def revenue_amount_diversity(doc_df: pd.DataFrame) -> dict[str, Any]:
    sub = doc_df[doc_df["scenario"] == "fictitious_entry"]
    rounded = sub["max_abs_amount"].round(-3)
    return {
        "n_docs": int(len(sub)),
        "unique_rounded_amounts": int(rounded.nunique()),
        "top_amount_share": float(rounded.value_counts(normalize=True).iloc[0])
        if len(sub)
        else 0.0,
    }


def scenario_rates(doc_df: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    rows: dict[str, dict[str, float | int]] = {}
    feature_cols = ["f_manual", "f_weekend", "f_offhour", "f_self_approval"]
    for scenario, sub in doc_df.groupby("scenario"):
        rec: dict[str, float | int] = {"n_docs": int(len(sub))}
        for col in feature_cols:
            rec[col] = float(sub[col].mean()) if len(sub) else 0.0
        if scenario == "unusual_timing_manipulation":
            simultaneous = sub[feature_cols].sum(axis=1)
            rec["all_four_shortcut_share"] = float((simultaneous == 4).mean()) if len(sub) else 0.0
            rec["two_or_three_feature_share"] = (
                float(simultaneous.isin([2, 3]).mean()) if len(sub) else 0.0
            )
            rec["pattern_count"] = int(
                sub[feature_cols].astype(int).astype(str).agg("".join, axis=1).nunique()
            )
        rows[scenario] = rec
    return rows


def guard_report(data_dir: Path) -> dict[str, Any]:
    truth = load_truth(data_dir)
    journal = load_journal(data_dir)
    docs = doc_features(journal, truth)

    counts = docs[docs["scenario"] != "normal"]["scenario"].value_counts().sort_index().to_dict()
    normal = docs[docs["scenario"] == "normal"]
    expense = docs[docs["scenario"] == "expense_capitalization"]
    suspense = docs[docs["scenario"] == "suspense_account_abuse"]
    unusual = docs[docs["scenario"] == "unusual_timing_manipulation"]

    result = {
        "dataset": _rel(data_dir),
        "truth_docs": int(len(truth)),
        "scenario_counts": {str(k): int(v) for k, v in counts.items()},
        "normal_manual_rate": float(normal["f_manual"].mean()),
        "scenario_shortcut_rates": scenario_rates(docs),
        "expense_capitalization": {
            "n_docs": int(len(expense)),
            "asset_and_expense_pair_share": float(
                (expense["has_asset_gl"] & expense["has_expense_gl"]).mean()
            ),
            "other_supporting_doc_share": float(expense["etc_support"].mean()),
        },
        "suspense_account_abuse": {
            "n_docs": int(len(suspense)),
            "suspense_gl_share": float(suspense["has_suspense_gl"].mean()),
            "suspense_marker_share": float(suspense["suspense_marker"].mean()),
            "aging_90_plus_share": float((suspense["max_aging_days"] >= 90).mean()),
            "cleared_late_docs": int(
                suspense["settlement_status"].str.contains("cleared_late", na=False).sum()
            ),
            "open_over_90_days_docs": int(
                suspense["settlement_status"].str.contains("open_over_90_days", na=False).sum()
            ),
        },
        "fictitious_entry": revenue_amount_diversity(docs),
    }
    unusual_features = unusual[["f_manual", "f_weekend", "f_offhour", "f_self_approval"]].sum(
        axis=1
    )
    checks = {
        "truth_total_620": int(len(truth)) == 620,
        "new_scenarios_100_each": counts.get("expense_capitalization") == 100
        and counts.get("suspense_account_abuse") == 100,
        "normal_manual_rate_not_shortcut": 0.30 <= result["normal_manual_rate"] <= 0.55,
        "unusual_not_all_four": bool((unusual_features == 4).sum() == 0),
        "unusual_two_or_three_features": bool(unusual_features.isin([2, 3]).mean() >= 0.80),
        "expense_has_asset_expense_pair": result["expense_capitalization"][
            "asset_and_expense_pair_share"
        ]
        >= 0.95,
        "suspense_has_long_aging": result["suspense_account_abuse"]["aging_90_plus_share"] >= 0.95,
        "fictitious_amount_not_deterministic": result["fictitious_entry"]["unique_rounded_amounts"]
        >= 20,
    }
    result["checks"] = checks
    result["status"] = "pass" if all(checks.values()) else "fail"
    return result


def write_markdown(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# Manipulation v4 Candidate Guard",
        "",
        f"- dataset: `{result['dataset']}`",
        f"- status: **{result['status'].upper()}**",
        f"- truth docs: {result['truth_docs']}",
        "",
        "## Checks",
        "",
    ]
    for key, value in result["checks"].items():
        lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
    lines.extend(["", "## Scenario Counts", ""])
    for key, value in result["scenario_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Substance Metrics",
            "",
            f"- normal_manual_rate: {result['normal_manual_rate']:.4f}",
            "- expense asset+expense pair share: "
            f"{result['expense_capitalization']['asset_and_expense_pair_share']:.4f}",
            "- suspense aging >=90d share: "
            f"{result['suspense_account_abuse']['aging_90_plus_share']:.4f}",
            "- fictitious unique rounded amounts: "
            f"{result['fictitious_entry']['unique_rounded_amounts']}",
            "",
            "Phase2 AUPRC and topic recall are intentionally excluded from pass/fail gates.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    result = guard_report(args.data_dir)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(result, args.out_md)
    print(
        json.dumps(
            {"status": result["status"], "out_json": _rel(args.out_json)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
