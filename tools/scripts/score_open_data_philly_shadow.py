"""Score OpenDataPhilly public payments with payment-level shadow signals.

This is not PHASE1 fraud detection and does not produce fraud labels. It scores
only signals available in the public payment data: amount tail, vendor
concentration, same vendor/date/amount repetition, threshold proximity,
period-end, round amount, and negative payment rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _to_amount(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[\$,]", "", regex=True)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _safe_rank(series: pd.Series) -> pd.Series:
    return series.fillna(0).rank(pct=True, method="average").fillna(0.0)


def _near_threshold_flag(amount: pd.Series) -> pd.Series:
    abs_amount = amount.abs()
    bands = np.array([1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000])
    mask = pd.Series(False, index=amount.index)
    for band in bands:
        mask |= abs_amount.ge(band * 0.98) & abs_amount.lt(band)
    return mask.fillna(False)


def _load_public_payments(path: Path, *, fiscal_year_end_month: int) -> pd.DataFrame:
    df = (
        pd.read_csv(path, low_memory=False)
        .reset_index()
        .rename(columns={"index": "external_row_id"})
    )
    df["external_row_id"] = df["external_row_id"].astype(str)
    df["vendor_name"] = df["vendor_name"].fillna("").astype(str).str.strip()
    df["department"] = df["department_title"].fillna("").astype(str).str.strip()
    df["payment_date"] = pd.to_datetime(df["check_date"], errors="coerce")
    df["amount"] = _to_amount(df["transaction_amount"])
    df["abs_amount"] = df["amount"].abs()
    df["document_number"] = df["document_no"].fillna("").astype(str).str.strip()
    df["contract_number"] = df["contract_number"].fillna("").astype(str).str.strip()
    df["description"] = df["contract_description"].fillna("").astype(str).str.strip()
    df["is_negative_amount"] = df["amount"].lt(0).fillna(False)
    df["is_round_1000"] = df["abs_amount"].mod(1000).eq(0) & df["abs_amount"].gt(0)
    df["is_near_common_threshold"] = _near_threshold_flag(df["amount"])
    df["is_month_end_window"] = df["payment_date"].dt.is_month_end.fillna(False)
    df["is_quarter_end_window"] = (
        df["payment_date"].dt.month.isin([3, 6, 9, 12]) & df["payment_date"].dt.is_month_end
    ).fillna(False)
    df["is_fiscal_year_end_window"] = (
        df["payment_date"].dt.month.eq(fiscal_year_end_month) & df["payment_date"].dt.is_month_end
    ).fillna(False)
    return df


def _add_context_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    vendor_group = df.groupby("vendor_name", dropna=False)
    df["vendor_payment_count"] = vendor_group["external_row_id"].transform("count")
    df["vendor_abs_amount_total"] = vendor_group["abs_amount"].transform("sum")
    total_abs = float(df["abs_amount"].sum())
    df["vendor_abs_amount_share"] = df["vendor_abs_amount_total"] / total_abs if total_abs else 0.0

    vendor_date_amount = ["vendor_name", "payment_date", "abs_amount"]
    vendor_dept_date_amount = ["vendor_name", "department", "payment_date", "abs_amount"]
    vendor_contract_date_amount = ["vendor_name", "contract_number", "payment_date", "abs_amount"]
    df["same_vendor_date_amount_group_size"] = (
        df.groupby(vendor_date_amount, dropna=False)["external_row_id"]
        .transform("count")
        .astype(int)
    )
    df["same_vendor_department_date_amount_group_size"] = (
        df.groupby(vendor_dept_date_amount, dropna=False)["external_row_id"]
        .transform("count")
        .astype(int)
    )
    contract_nonempty = df["contract_number"].ne("")
    contract_group_size = pd.Series(0, index=df.index, dtype="int64")
    contract_group_size.loc[contract_nonempty] = (
        df.loc[contract_nonempty]
        .groupby(vendor_contract_date_amount, dropna=False)["external_row_id"]
        .transform("count")
        .astype(int)
    )
    df["same_vendor_contract_date_amount_group_size"] = contract_group_size
    return df


def _score(df: pd.DataFrame) -> pd.DataFrame:
    df = _add_context_features(df)
    amount_tail = _safe_rank(df["abs_amount"])
    vendor_concentration = _safe_rank(df["vendor_abs_amount_share"])
    duplicate_signal = np.log1p(df["same_vendor_contract_date_amount_group_size"].clip(lower=0))
    duplicate_signal = pd.Series(duplicate_signal, index=df.index)
    duplicate_signal = duplicate_signal / max(float(duplicate_signal.max()), 1.0)
    period_signal = (
        df["is_month_end_window"] | df["is_quarter_end_window"] | df["is_fiscal_year_end_window"]
    ).astype(float)
    threshold_signal = df["is_near_common_threshold"].astype(float)
    negative_signal = df["is_negative_amount"].astype(float)
    round_signal = df["is_round_1000"].astype(float)

    df["shadow_amount_tail_score"] = amount_tail
    df["shadow_vendor_concentration_score"] = vendor_concentration
    df["shadow_duplicate_score"] = duplicate_signal
    df["shadow_period_end_score"] = period_signal
    df["shadow_threshold_score"] = threshold_signal
    df["shadow_negative_score"] = negative_signal
    df["shadow_round_score"] = round_signal
    df["shadow_review_score"] = (
        0.30 * amount_tail
        + 0.20 * duplicate_signal
        + 0.15 * vendor_concentration
        + 0.12 * threshold_signal
        + 0.10 * period_signal
        + 0.08 * negative_signal
        + 0.05 * round_signal
    )
    df["shadow_rank"] = df["shadow_review_score"].rank(ascending=False, method="min").astype(int)
    df["shadow_percentile"] = df["shadow_review_score"].rank(pct=True, method="average")
    return df


def _reason(row: pd.Series) -> str:
    reasons: list[str] = []
    if float(row.get("shadow_amount_tail_score", 0)) >= 0.95:
        reasons.append("amount_tail")
    if int(row.get("same_vendor_contract_date_amount_group_size", 0)) > 1:
        reasons.append("same_vendor_contract_date_amount")
    elif int(row.get("same_vendor_date_amount_group_size", 0)) > 1:
        reasons.append("same_vendor_date_amount")
    if float(row.get("vendor_abs_amount_share", 0)) >= 0.01:
        reasons.append("vendor_concentration")
    if str(row.get("is_near_common_threshold", "")).lower() == "true":
        reasons.append("near_threshold")
    if str(row.get("is_fiscal_year_end_window", "")).lower() == "true":
        reasons.append("fiscal_year_end")
    elif str(row.get("is_quarter_end_window", "")).lower() == "true":
        reasons.append("quarter_end")
    if str(row.get("is_negative_amount", "")).lower() == "true":
        reasons.append("negative_amount")
    if str(row.get("is_round_1000", "")).lower() == "true":
        reasons.append("round_1000")
    return "|".join(reasons) if reasons else "low_signal"


def _compare_with_golden(scored: pd.DataFrame, review_path: Path) -> pd.DataFrame:
    review = pd.read_csv(review_path, dtype=str, keep_default_na=False)
    keep = [
        "external_row_id",
        "sample_bucket",
        "review_label",
        "review_confidence_1_5",
        "review_rationale",
        "eligible_for_supervised_positive",
    ]
    merged = scored.merge(review[keep], on="external_row_id", how="inner")
    merged["shadow_reason"] = merged.apply(_reason, axis=1)
    return merged.sort_values("shadow_rank", kind="mergesort")


def _label_summary(compared: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, grp in compared.groupby("review_label", dropna=False):
        rows.append(
            {
                "review_label": label,
                "count": int(len(grp)),
                "score_mean": float(grp["shadow_review_score"].mean()),
                "score_median": float(grp["shadow_review_score"].median()),
                "rank_median": float(grp["shadow_rank"].median()),
                "top_1pct_count": int(grp["shadow_percentile"].ge(0.99).sum()),
                "top_5pct_count": int(grp["shadow_percentile"].ge(0.95).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("review_label")


def _false_positive_reasons(compared: pd.DataFrame) -> pd.DataFrame:
    benign = compared[compared["review_label"].eq("benign_explainable")].copy()
    high = benign[benign["shadow_percentile"].ge(0.95)]
    if high.empty:
        return pd.DataFrame(columns=["shadow_reason", "count"])
    exploded = high.assign(shadow_reason=high["shadow_reason"].str.split("|")).explode(
        "shadow_reason"
    )
    return (
        exploded.groupby("shadow_reason", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    label_summary: pd.DataFrame,
    fp_reasons: pd.DataFrame,
    compared: pd.DataFrame,
) -> None:
    lines = [
        "# OpenDataPhilly Payment Shadow Score Report",
        "",
        f"- Created at: {summary['created_at']}",
        f"- Full rows scored: {summary['full_rows']}",
        f"- Golden rows compared: {summary['golden_rows']}",
        "",
        "This is an unlabeled public-payment shadow analysis. It is not fraud precision, "
        "recall, or supervised promotion evidence.",
        "",
        "Important caveat: the `triage_top_k` review rows were originally selected "
        "using similar public-payment signals. High ranking for "
        "`audit_review_candidate` is therefore a workflow consistency check, not an "
        "independent detector-performance result.",
        "",
        "## Label Score Summary",
        "",
        label_summary.to_markdown(index=False),
        "",
        "## Benign High-Score Reason Profile",
        "",
    ]
    if fp_reasons.empty:
        lines.append("No `benign_explainable` rows fell in the top 5% shadow score band.")
    else:
        lines.append(fp_reasons.to_markdown(index=False))
    top_rows = compared.head(20)
    lines.extend(
        [
            "",
            "## Top Golden Rows By Shadow Score",
            "",
            "| Rank | Row | Label | Vendor | Date | Amount | Reasons |",
            "|---:|---|---|---|---|---:|---|",
        ]
    )
    for row in top_rows.to_dict(orient="records"):
        payment_date = row["payment_date"]
        rendered_date = payment_date.date() if hasattr(payment_date, "date") else payment_date
        lines.append(
            f"| {int(row['shadow_rank'])} | `{row['external_row_id']}` | "
            f"`{row['review_label']}` | {row['vendor_name']} | "
            f"{rendered_date} | {float(row['amount']):.2f} | `{row['shadow_reason']}` |"
        )
    output_dir.joinpath("open_data_philly_detector_shadow_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _write_false_positive_markdown(output_dir: Path, fp_reasons: pd.DataFrame) -> None:
    lines = [
        "# OpenDataPhilly False-Positive Reason Profile",
        "",
        "Scope: `benign_explainable` rows that the public-payment shadow scorer ranks "
        "in the top 5% band.",
        "",
        "These are not model errors yet. They are the main operating-noise reasons to "
        "document before using similar signals in a real audit queue.",
        "",
    ]
    if fp_reasons.empty:
        lines.append("No high-scoring benign rows were observed in the 200-row packet.")
    else:
        lines.append(fp_reasons.to_markdown(index=False))
    output_dir.joinpath("open_data_philly_false_positive_reasons.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="OpenDataPhilly CSV path.")
    parser.add_argument("--review-sheet", required=True, help="Labeled golden review sheet CSV.")
    parser.add_argument("--output-dir", required=True, help="Output directory.")
    parser.add_argument(
        "--fiscal-year-end-month",
        type=int,
        default=6,
        choices=range(1, 13),
        metavar="{1..12}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    full = _load_public_payments(Path(args.input), fiscal_year_end_month=args.fiscal_year_end_month)
    scored = _score(full)
    compared = _compare_with_golden(scored, Path(args.review_sheet))
    label_summary = _label_summary(compared)
    fp_reasons = _false_positive_reasons(compared)
    score_cols = [
        "external_row_id",
        "vendor_name",
        "department",
        "payment_date",
        "amount",
        "document_number",
        "contract_number",
        "description",
        "shadow_review_score",
        "shadow_rank",
        "shadow_percentile",
        "shadow_amount_tail_score",
        "shadow_vendor_concentration_score",
        "shadow_duplicate_score",
        "shadow_period_end_score",
        "shadow_threshold_score",
        "shadow_negative_score",
        "shadow_round_score",
        "same_vendor_date_amount_group_size",
        "same_vendor_department_date_amount_group_size",
        "same_vendor_contract_date_amount_group_size",
        "vendor_abs_amount_share",
    ]
    scored[score_cols].to_csv(
        output_dir / "open_data_philly_shadow_scores.csv",
        index=False,
        encoding="utf-8-sig",
    )
    compared.to_csv(
        output_dir / "open_data_philly_review_score_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    label_summary.to_csv(
        output_dir / "open_data_philly_review_score_label_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    fp_reasons.to_csv(
        output_dir / "open_data_philly_false_positive_reasons.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary = {
        "created_at": _now_iso(),
        "input": args.input,
        "review_sheet": args.review_sheet,
        "full_rows": int(len(scored)),
        "golden_rows": int(len(compared)),
        "fiscal_year_end_month": int(args.fiscal_year_end_month),
        "top_1pct_score_threshold": float(scored["shadow_review_score"].quantile(0.99)),
        "top_5pct_score_threshold": float(scored["shadow_review_score"].quantile(0.95)),
        "note": "Payment-level shadow scoring only; no fraud labels or promotion evidence.",
    }
    (output_dir / "open_data_philly_shadow_score_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(output_dir, summary, label_summary, fp_reasons, compared)
    _write_false_positive_markdown(output_dir, fp_reasons)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
