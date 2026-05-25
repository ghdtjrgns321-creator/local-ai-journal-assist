"""R03/TS01 natural-distribution calibration audit for fixed4.

This script measures distributional reference points before changing rule
parameters. Truth-positive/negative splits are reported for diagnostics only;
threshold decisions must use the truth-negative natural distribution plus
domain rationale, not recall/grid-search optimization.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl"
TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed4"
    / "labels"
    / "manipulated_entry_truth.csv"
)
RUN_DATE = datetime.now().strftime("%Y%m%d")
OUT_JSON = ROOT / "artifacts" / f"r03_ts01_natural_distribution_fixed4_{RUN_DATE}.json"
OUT_MD = ROOT / "artifacts" / f"r03_ts01_natural_distribution_fixed4_{RUN_DATE}.md"

QUANTILES = (0.25, 0.50, 0.75, 0.90, 0.95, 0.99)


def _quantiles(series: pd.Series, qs: tuple[float, ...] = QUANTILES) -> dict[str, float | None]:
    clean = (
        pd.to_numeric(series, errors="coerce")
        .replace([float("inf"), -float("inf")], pd.NA)
        .dropna()
    )
    if clean.empty:
        return {f"q{int(q * 100):02d}": None for q in qs}
    values = clean.quantile(list(qs))
    return {f"q{int(q * 100):02d}": float(values.loc[q]) for q in qs}


def _load_input() -> pd.DataFrame:
    with PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"].copy()

    truth = pd.read_csv(TRUTH)
    truth_docs = set(truth["document_id"].astype(str))
    df["is_truth"] = df["document_id"].astype(str).isin(truth_docs)
    return df


def _r03_distribution(df: pd.DataFrame) -> dict[str, Any]:
    required = {"is_intercompany", "trading_partner", "gl_account", "debit_amount", "credit_amount"}
    missing = sorted(required - set(df.columns))
    if missing:
        return {"status": "skipped", "missing_columns": missing}

    amount = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    ic_mask = df["is_intercompany"].fillna(False).astype(bool)
    ic = df.loc[ic_mask, ["trading_partner", "gl_account", "is_truth"]].copy()
    ic["amount"] = amount.loc[ic.index]

    if ic.empty:
        return {"status": "skipped", "reason": "no_intercompany_rows"}

    group_keys = ["trading_partner", "gl_account"]
    group_mean = ic.groupby(group_keys)["amount"].transform("mean")
    group_count = ic.groupby(group_keys)["amount"].transform("count")
    ic["group_count"] = group_count
    ic["deviation"] = (ic["amount"] - group_mean).abs() / group_mean.clip(lower=1e-10)

    valid = ic[ic["group_count"] >= 3].copy()
    truth_positive = valid[valid["is_truth"]]
    truth_negative = valid[~valid["is_truth"]]

    group_sizes = ic.groupby(group_keys, dropna=False).size()
    group_total = int(len(group_sizes))
    group_size_thresholds = {
        "lt_3_share": float((group_sizes < 3).sum() / max(group_total, 1)),
        "lt_5_share": float((group_sizes < 5).sum() / max(group_total, 1)),
        "lt_10_share": float((group_sizes < 10).sum() / max(group_total, 1)),
    }

    return {
        "status": "ok",
        "ic_rows": int(len(ic)),
        "eligible_rows_group_count_ge_3": int(len(valid)),
        "truth_positive_rows": int(len(truth_positive)),
        "truth_negative_rows": int(len(truth_negative)),
        "deviation_quantiles": {
            "all_eligible_rows": _quantiles(valid["deviation"]),
            "truth_positive_rows_informational_only": _quantiles(truth_positive["deviation"]),
            "truth_negative_rows_decision_basis": _quantiles(truth_negative["deviation"]),
        },
        "group_size": {
            "group_count": group_total,
            "quantiles": _quantiles(group_sizes),
            **group_size_thresholds,
        },
    }


def _ts01_distribution(df: pd.DataFrame, window_days: int = 7) -> dict[str, Any]:
    if "posting_date" not in df.columns:
        return {"status": "skipped", "missing_columns": ["posting_date"]}

    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    valid_mask = dates.notna()
    if not valid_mask.any():
        return {"status": "skipped", "reason": "no_valid_posting_date"}

    date_only = dates.dt.normalize()
    daily_counts = date_only[valid_mask].groupby(date_only[valid_mask]).count()
    daily_counts.index = pd.DatetimeIndex(daily_counts.index)
    daily_counts = daily_counts.resample("D").sum().fillna(0)

    shifted = daily_counts.shift(1)
    rolling = shifted.rolling(window=window_days, min_periods=window_days)
    rolling_mean = rolling.mean()
    rolling_std = rolling.std(ddof=1)
    z_score = ((daily_counts - rolling_mean) / rolling_std.replace(0, pd.NA)).dropna()

    truth_dates = set(date_only[valid_mask & df["is_truth"]].dropna().unique())
    z_frame = pd.DataFrame({"z_score": z_score})
    z_frame["is_truth_date"] = z_frame.index.normalize().isin(truth_dates)

    sigma_3_share = float((z_frame["z_score"] > 3.0).sum() / max(len(z_frame), 1))
    sigma_3_quantile_rank = float((z_frame["z_score"] <= 3.0).sum() / max(len(z_frame), 1))

    return {
        "status": "ok",
        "window_days": window_days,
        "calendar_days": int(len(daily_counts)),
        "zscore_days": int(len(z_frame)),
        "truth_dates": int(z_frame["is_truth_date"].sum()),
        "zscore_quantiles": {
            "all_days": _quantiles(z_frame["z_score"], qs=(0.50, 0.75, 0.90, 0.95, 0.99)),
            "truth_positive_dates_informational_only": _quantiles(
                z_frame.loc[z_frame["is_truth_date"], "z_score"],
                qs=(0.50, 0.75, 0.90, 0.95, 0.99),
            ),
            "truth_negative_dates_decision_basis": _quantiles(
                z_frame.loc[~z_frame["is_truth_date"], "z_score"],
                qs=(0.50, 0.75, 0.90, 0.95, 0.99),
            ),
        },
        "sigma_3": {
            "exceeding_day_count": int((z_frame["z_score"] > 3.0).sum()),
            "exceeding_day_share": sigma_3_share,
            "empirical_quantile_rank": sigma_3_quantile_rank,
        },
    }


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.6f}"


def _write_markdown(report: dict[str, Any]) -> None:
    r03 = report["r03_transfer_pricing_anomaly"]
    ts01 = report["ts01_transaction_burst"]

    lines = [
        "# R03 / TS01 Natural Distribution Audit — fixed4",
        "",
        f"- Generated: `{report['generated_at']}`",
        "- Fitting guard: thresholds are selected from truth-negative natural distributions "
        "and domain rationale.",
        "- Truth-positive splits below are informational outcome diagnostics only, "
        "not tuning criteria.",
        "",
        "## R03 IC Pair Deviation",
        "",
    ]

    if r03["status"] == "ok":
        q = r03["deviation_quantiles"]
        lines.extend([
            f"- IC rows: {r03['ic_rows']:,}",
            f"- Eligible rows (group n >= 3): {r03['eligible_rows_group_count_ge_3']:,}",
            "",
            "| population | q50 | q75 | q90 | q95 | q99 |",
            "|---|---:|---:|---:|---:|---:|",
            "| all eligible | "
            + " | ".join(
                _fmt_num(q["all_eligible_rows"].get(k))
                for k in ("q50", "q75", "q90", "q95", "q99")
            )
            + " |",
            "| truth-negative decision basis | "
            + " | ".join(
                _fmt_num(q["truth_negative_rows_decision_basis"].get(k))
                for k in ("q50", "q75", "q90", "q95", "q99")
            )
            + " |",
            "| truth-positive informational only | "
            + " | ".join(
                _fmt_num(q["truth_positive_rows_informational_only"].get(k))
                for k in ("q50", "q75", "q90", "q95", "q99")
            )
            + " |",
            "",
            "### R03 Group Size",
            "",
            "| q25 | q50 | q75 | q90 | groups < 3 | groups < 5 | groups < 10 |",
            "|---:|---:|---:|---:|---:|---:|---:|",
            "| "
            + " | ".join(
                _fmt_num(r03["group_size"]["quantiles"].get(k))
                for k in ("q25", "q50", "q75", "q90")
            )
            + f" | {_fmt_pct(r03['group_size']['lt_3_share'])}"
            + f" | {_fmt_pct(r03['group_size']['lt_5_share'])}"
            + f" | {_fmt_pct(r03['group_size']['lt_10_share'])} |",
        ])
    else:
        lines.append(f"- Skipped: `{r03}`")

    lines.extend(["", "## TS01 Daily Burst Z-Score", ""])
    if ts01["status"] == "ok":
        q = ts01["zscore_quantiles"]
        lines.extend([
            f"- Window days: {ts01['window_days']}",
            f"- Z-score days: {ts01['zscore_days']:,}",
            f"- sigma=3 empirical quantile rank: {ts01['sigma_3']['empirical_quantile_rank']:.4f}",
            "",
            "| population | q50 | q75 | q90 | q95 | q99 |",
            "|---|---:|---:|---:|---:|---:|",
            "| all days | "
            + " | ".join(
                _fmt_num(q["all_days"].get(k))
                for k in ("q50", "q75", "q90", "q95", "q99")
            )
            + " |",
            "| truth-negative decision basis | "
            + " | ".join(
                _fmt_num(q["truth_negative_dates_decision_basis"].get(k))
                for k in ("q50", "q75", "q90", "q95", "q99")
            )
            + " |",
            "| truth-positive informational only | "
            + " | ".join(
                _fmt_num(q["truth_positive_dates_informational_only"].get(k))
                for k in ("q50", "q75", "q90", "q95", "q99")
            )
            + " |",
        ])
    else:
        lines.append(f"- Skipped: `{ts01}`")

    lines.extend([
        "",
        "## Fitting Guard Notes",
        "",
        "- Do not grid-search recall curves from this output.",
        "- Do not select thresholds using truth ratio targets.",
        "- Use truth-negative q95/q99 and audit-domain rationale for Step 2.",
    ])
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    print("loading fixed4 input ...")
    df = _load_input()
    print(f"  rows={len(df):,} docs={df['document_id'].nunique():,}")

    report: dict[str, Any] = {
        "dataset": "datasynth_manipulation_v7_candidate_fixed4",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fitting_guard": {
            "recall_grid_search": "forbidden",
            "truth_ratio_threshold_selection": "forbidden",
            "decision_basis": "truth_negative_distribution_quantiles_plus_domain_rationale",
            "truth_positive_split_usage": "informational_outcome_diagnostic_only",
        },
        "r03_transfer_pricing_anomaly": _r03_distribution(df),
        "ts01_transaction_burst": _ts01_distribution(df),
    }

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(report)
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
