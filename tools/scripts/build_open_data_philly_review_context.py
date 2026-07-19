"""Build reviewer context artifacts for OpenDataPhilly golden review rows.

The golden review sheet intentionally contains one sampled payment row per
record. This script adds surrounding public-data context without assigning
labels:

- selected_review_context.csv: sampled rows plus original public fields
- duplicate_cluster_context.csv: rows sharing vendor/date/amount with samples
- vendor_context.csv: vendor-level population statistics
- reviewer_packet.md: concise packet summary
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _read_full(path: Path) -> pd.DataFrame:
    full = pd.read_csv(path, low_memory=False)
    full = full.reset_index().rename(columns={"index": "external_row_id"})
    full["external_row_id"] = full["external_row_id"].astype(str)
    full["payment_date"] = pd.to_datetime(full["check_date"], errors="coerce")
    full["amount"] = _to_amount(full["transaction_amount"])
    full["abs_amount"] = full["amount"].abs()
    full["vendor_name"] = full["vendor_name"].fillna("").astype(str).str.strip()
    full["department_title"] = full["department_title"].fillna("").astype(str).str.strip()
    full["contract_number"] = full["contract_number"].fillna("").astype(str).str.strip()
    full["document_no"] = full["document_no"].fillna("").astype(str).str.strip()
    return full


def _vendor_context(full: pd.DataFrame) -> pd.DataFrame:
    grouped = full.groupby("vendor_name", dropna=False)
    context = grouped.agg(
        vendor_payment_count=("external_row_id", "count"),
        vendor_abs_amount_total=("abs_amount", "sum"),
        vendor_abs_amount_median=("abs_amount", "median"),
        vendor_abs_amount_p95=("abs_amount", lambda value: value.quantile(0.95)),
        vendor_first_payment_date=("payment_date", "min"),
        vendor_last_payment_date=("payment_date", "max"),
        vendor_department_count=("department_title", "nunique"),
        vendor_contract_count=("contract_number", lambda value: value.replace("", pd.NA).nunique()),
    ).reset_index()
    total_abs = float(full["abs_amount"].sum())
    context["vendor_abs_amount_share"] = (
        context["vendor_abs_amount_total"] / total_abs if total_abs else 0.0
    )
    return context


def _duplicate_cluster_context(full: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    review_keys = review[["vendor_name", "payment_date", "amount"]].copy()
    review_keys["payment_date"] = pd.to_datetime(review_keys["payment_date"], errors="coerce")
    review_keys["amount"] = pd.to_numeric(review_keys["amount"], errors="coerce")
    review_keys = review_keys.dropna(subset=["payment_date", "amount"]).drop_duplicates()
    if review_keys.empty:
        return pd.DataFrame()

    keyed = full.merge(
        review_keys,
        on=["vendor_name", "payment_date", "amount"],
        how="inner",
        suffixes=("", "_review"),
    )
    columns = [
        "external_row_id",
        "vendor_name",
        "department_title",
        "payment_date",
        "amount",
        "document_no",
        "doc_ref_no_prefix",
        "doc_ref_no_prefix_definition",
        "contract_number",
        "contract_description",
        "character_title",
        "sub_obj_title",
    ]
    return keyed[[col for col in columns if col in keyed.columns]].sort_values(
        ["vendor_name", "payment_date", "amount", "document_no"],
        kind="mergesort",
    )


def _selected_context(
    full: pd.DataFrame,
    review: pd.DataFrame,
    vendors: pd.DataFrame,
) -> pd.DataFrame:
    selected = review.merge(
        full[
            [
                "external_row_id",
                "fy",
                "fm",
                "dept",
                "char_",
                "character_title",
                "sub_obj",
                "sub_obj_title",
                "doc_ref_no_prefix",
                "doc_ref_no_prefix_definition",
            ]
        ],
        on="external_row_id",
        how="left",
    )
    selected = selected.merge(vendors, on="vendor_name", how="left")
    return selected


def _json_number(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _write_packet(
    output_dir: Path,
    selected: pd.DataFrame,
    clusters: pd.DataFrame,
    vendors: pd.DataFrame,
) -> None:
    summary = {
        "created_at": _now_iso(),
        "selected_review_rows": int(len(selected)),
        "duplicate_cluster_rows": int(len(clusters)),
        "review_vendors": int(selected["vendor_name"].nunique(dropna=True)),
        "top_sample_rows": int((selected["sample_bucket"] == "triage_top_k").sum()),
        "random_control_rows": int((selected["sample_bucket"] == "random_control").sum()),
    }
    (output_dir / "review_context_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_number),
        encoding="utf-8",
    )

    top_vendors = vendors.sort_values("vendor_abs_amount_total", ascending=False).head(10)
    lines = [
        "# OpenDataPhilly Review Context Packet",
        "",
        f"- Created at: {summary['created_at']}",
        f"- Selected review rows: {summary['selected_review_rows']}",
        f"- Duplicate cluster context rows: {summary['duplicate_cluster_rows']}",
        f"- Unique review vendors: {summary['review_vendors']}",
        "",
        "## How To Use",
        "",
        "Use `selected_review_context.csv` as the main review file. Use "
        "`duplicate_cluster_context.csv` when a sampled row has same-vendor/date/amount "
        "matches. Use `vendor_context.csv` to distinguish recurring high-volume vendors "
        "from isolated unusual payments.",
        "",
        "Do not assign fraud labels from this packet alone. It is supporting context for "
        "the human review taxonomy in `REVIEW_GUIDE.md`.",
        "",
        "## Top Vendors By Absolute Amount",
        "",
        "| Vendor | Payment count | Abs amount total | Share | Departments | Contracts |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in top_vendors.to_dict(orient="records"):
        lines.append(
            "| "
            f"{row['vendor_name']} | "
            f"{int(row['vendor_payment_count'])} | "
            f"{float(row['vendor_abs_amount_total']):.2f} | "
            f"{float(row['vendor_abs_amount_share']):.4%} | "
            f"{int(row['vendor_department_count'])} | "
            f"{int(row['vendor_contract_count'])} |"
        )
    (output_dir / "reviewer_packet.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-input", required=True, help="Original OpenDataPhilly CSV.")
    parser.add_argument("--review-sheet", required=True, help="golden_review_sheet.csv path.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for context artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    full = _read_full(Path(args.full_input))
    review = pd.read_csv(args.review_sheet, dtype=str, keep_default_na=False)
    vendors = _vendor_context(full)
    selected = _selected_context(full, review, vendors)
    clusters = _duplicate_cluster_context(full, review)

    selected.to_csv(output_dir / "selected_review_context.csv", index=False, encoding="utf-8-sig")
    clusters.to_csv(output_dir / "duplicate_cluster_context.csv", index=False, encoding="utf-8-sig")
    vendors.to_csv(output_dir / "vendor_context.csv", index=False, encoding="utf-8-sig")
    _write_packet(output_dir, selected, clusters, vendors)

    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "selected_review_rows": int(len(selected)),
                "duplicate_cluster_rows": int(len(clusters)),
                "vendor_context_rows": int(len(vendors)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
