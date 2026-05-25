"""Bootstrap external real-data review sheets from public payment datasets.

The first target is OpenDataPhilly FY2017 Detailed Payments, but the script is
intentionally column-name tolerant so it can also profile similar public payment
CSVs. It does not train models and does not infer fraud labels. It produces:

- schema_mapping_report.json/.md
- base_rate_profile.json/.csv/.md
- golden_review_sheet.csv

Usage:
    uv run python tools/scripts/bootstrap_open_data_philly_golden.py \
        --input path/to/payments.csv \
        --output-dir artifacts/external_validation/open_data_philly_20260519
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
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


CANONICAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "vendor_name": (
        r"vendor",
        r"payee",
        r"supplier",
        r"creditor",
        r"recipient",
        r"merchant",
    ),
    "department": (
        r"department",
        r"dept",
        r"agency",
        r"bureau",
        r"directorate",
        r"organisation",
        r"organization",
    ),
    "payment_date": (
        r"check.*date",
        r"payment.*date",
        r"paid.*date",
        r"posting.*date",
        r"transaction.*date",
        r"date",
    ),
    "amount": (
        r"net.*amount",
        r"payment.*amount",
        r"check.*amount",
        r"amount",
        r"gross",
        r"paid",
    ),
    "document_number": (
        r"document",
        r"voucher",
        r"transaction.*no",
        r"transaction.*num",
        r"reference",
        r"invoice",
        r"check.*number",
    ),
    "description": (
        r"description",
        r"purpose",
        r"memo",
        r"subjective",
        r"service",
        r"category",
    ),
    "contract_number": (
        r"contract",
        r"po.*number",
        r"purchase.*order",
        r"agreement",
    ),
}

REVIEW_LABELS = (
    "confirmed_exception",
    "control_issue",
    "accounting_error",
    "audit_review_candidate",
    "benign_explainable",
    "insufficient_evidence",
)


@dataclass(frozen=True)
class MappingChoice:
    canonical: str
    source: str | None
    confidence: str
    reason: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _normalize_col(name: str) -> str:
    lowered = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower())
    return re.sub(r"_+", "_", lowered).strip("_")


def _read_input(path_or_url: str) -> pd.DataFrame:
    suffix = Path(path_or_url.split("?", 1)[0]).suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path_or_url)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path_or_url)
    return pd.read_csv(path_or_url, low_memory=False)


def _choose_mapping(columns: list[str]) -> dict[str, MappingChoice]:
    normalized = {_normalize_col(col): col for col in columns}
    mapping: dict[str, MappingChoice] = {}
    for canonical, patterns in CANONICAL_PATTERNS.items():
        matches: list[tuple[int, str, str]] = []
        for norm_name, original in normalized.items():
            for order, pattern in enumerate(patterns):
                if re.search(pattern, norm_name):
                    matches.append((order, norm_name, original))
                    break
        if not matches:
            mapping[canonical] = MappingChoice(
                canonical,
                None,
                "missing",
                "No source column matched the known public-payment aliases.",
            )
            continue
        matches.sort(key=lambda item: (item[0], len(item[1])))
        best = matches[0][2]
        confidence = "high" if matches[0][0] <= 1 else "medium"
        mapping[canonical] = MappingChoice(
            canonical,
            best,
            confidence,
            f"Matched alias pattern rank {matches[0][0]} from normalized column '{matches[0][1]}'.",
        )
    return mapping


def _to_amount(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[\$,]", "", regex=True)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _build_work_frame(
    df: pd.DataFrame,
    mapping: dict[str, MappingChoice],
    *,
    fiscal_year_end_month: int,
) -> pd.DataFrame:
    work = pd.DataFrame(index=df.index)
    for canonical, choice in mapping.items():
        if choice.source is not None:
            work[canonical] = df[choice.source]
        else:
            work[canonical] = pd.NA

    work["amount"] = (
        _to_amount(work["amount"]) if "amount" in work else pd.Series(np.nan, index=df.index)
    )
    work["payment_date"] = pd.to_datetime(work["payment_date"], errors="coerce")
    work["vendor_name"] = work["vendor_name"].fillna("").astype(str).str.strip()
    work["department"] = work["department"].fillna("").astype(str).str.strip()
    work["document_number"] = work["document_number"].fillna("").astype(str).str.strip()
    work["description"] = work["description"].fillna("").astype(str).str.strip()
    work["contract_number"] = work["contract_number"].fillna("").astype(str).str.strip()

    abs_amount = work["amount"].abs()
    work["abs_amount"] = abs_amount
    work["is_negative_amount"] = work["amount"] < 0
    work["is_zero_amount"] = work["amount"].fillna(0).eq(0)
    work["is_round_100"] = abs_amount.mod(100).eq(0) & abs_amount.gt(0)
    work["is_round_1000"] = abs_amount.mod(1000).eq(0) & abs_amount.gt(0)
    work["is_weekend"] = work["payment_date"].dt.dayofweek.isin([5, 6]).fillna(False)
    work["is_month_end_window"] = work["payment_date"].dt.is_month_end.fillna(False)
    work["is_quarter_end_window"] = (
        work["payment_date"].dt.month.isin([3, 6, 9, 12]) & work["payment_date"].dt.is_month_end
    ).fillna(False)
    work["is_calendar_year_end_window"] = (
        work["payment_date"].dt.month.eq(12) & work["payment_date"].dt.is_month_end
    ).fillna(False)
    work["is_fiscal_year_end_window"] = (
        work["payment_date"].dt.month.eq(fiscal_year_end_month)
        & work["payment_date"].dt.is_month_end
    ).fillna(False)
    work["document_prefix"] = (
        work["document_number"].str.extract(r"^([A-Za-z]+)", expand=False).fillna("").str.upper()
    )
    return work


def _safe_rate(mask: pd.Series, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(mask.fillna(False).sum() / denominator)


def _json_number(value: Any) -> float | int | str | None:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    return value


def _top_share(series: pd.Series, amount: pd.Series, top_n: int) -> float:
    valid = pd.DataFrame({"key": series.fillna("").astype(str), "amount": amount.abs()})
    total = valid["amount"].sum()
    if total <= 0:
        return 0.0
    grouped = valid.groupby("key", dropna=False)["amount"].sum().nlargest(top_n).sum()
    return float(grouped / total)


def _near_threshold_flag(amount: pd.Series) -> pd.Series:
    """Heuristic only: near common approval bands, not a label."""

    abs_amount = amount.abs()
    bands = np.array([1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000], dtype=float)
    flags = pd.Series(False, index=amount.index)
    for band in bands:
        lower = band * 0.98
        flags |= abs_amount.ge(lower) & abs_amount.lt(band)
    return flags.fillna(False)


def _duplicate_group_size(
    work: pd.DataFrame,
    keys: list[str],
    *,
    require_nonempty: str | None = None,
) -> pd.Series:
    valid = work[keys].copy()
    valid["payment_date"] = pd.to_datetime(valid["payment_date"], errors="coerce")
    if require_nonempty is not None:
        nonempty = valid[require_nonempty].fillna("").astype(str).str.strip().ne("")
        valid = valid.loc[nonempty]
    group_size = valid.groupby(keys, dropna=False)[keys[0]].transform("size")
    result = pd.Series(0, index=work.index, dtype="int64")
    result.loc[group_size.index] = group_size.fillna(0).astype(int)
    return result


def _add_duplicate_features(work: pd.DataFrame) -> pd.DataFrame:
    vendor_date_amount_keys = ["vendor_name", "payment_date", "abs_amount"]
    vendor_dept_date_amount_keys = ["vendor_name", "department", "payment_date", "abs_amount"]
    vendor_contract_date_amount_keys = [
        "vendor_name",
        "contract_number",
        "payment_date",
        "abs_amount",
    ]

    work["same_vendor_date_amount_group_size"] = _duplicate_group_size(
        work,
        vendor_date_amount_keys,
    )
    work["same_vendor_department_date_amount_group_size"] = _duplicate_group_size(
        work,
        vendor_dept_date_amount_keys,
    )
    work["same_vendor_contract_date_amount_group_size"] = _duplicate_group_size(
        work,
        vendor_contract_date_amount_keys,
        require_nonempty="contract_number",
    )
    work["is_same_vendor_date_amount_duplicate_candidate"] = work[
        "same_vendor_date_amount_group_size"
    ].gt(1)
    work["is_same_vendor_department_date_amount_duplicate_candidate"] = work[
        "same_vendor_department_date_amount_group_size"
    ].gt(1)
    work["is_same_vendor_contract_date_amount_duplicate_candidate"] = work[
        "same_vendor_contract_date_amount_group_size"
    ].gt(1)
    return work


def _profile_base_rates(work: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    n = len(work)
    work = _add_duplicate_features(work)
    work["is_near_common_threshold"] = _near_threshold_flag(work["amount"])

    amount = work["amount"]
    date = work["payment_date"]
    profile: dict[str, Any] = {
        "created_at": _now_iso(),
        "rows": int(n),
        "unique_vendors": int(work["vendor_name"].replace("", np.nan).nunique(dropna=True)),
        "unique_departments": int(work["department"].replace("", np.nan).nunique(dropna=True)),
        "date_min": None if date.dropna().empty else str(date.min().date()),
        "date_max": None if date.dropna().empty else str(date.max().date()),
        "amount_total_abs": _json_number(amount.abs().sum()),
        "amount_p50_abs": _json_number(amount.abs().quantile(0.50)),
        "amount_p90_abs": _json_number(amount.abs().quantile(0.90)),
        "amount_p95_abs": _json_number(amount.abs().quantile(0.95)),
        "amount_p99_abs": _json_number(amount.abs().quantile(0.99)),
        "missing_vendor_rate": _safe_rate(work["vendor_name"].eq(""), n),
        "missing_date_rate": _safe_rate(date.isna(), n),
        "missing_amount_rate": _safe_rate(amount.isna(), n),
        "negative_amount_rate": _safe_rate(work["is_negative_amount"], n),
        "zero_amount_rate": _safe_rate(work["is_zero_amount"], n),
        "round_100_rate": _safe_rate(work["is_round_100"], n),
        "round_1000_rate": _safe_rate(work["is_round_1000"], n),
        "weekend_rate": _safe_rate(work["is_weekend"], n),
        "month_end_rate": _safe_rate(work["is_month_end_window"], n),
        "quarter_end_rate": _safe_rate(work["is_quarter_end_window"], n),
        "calendar_year_end_rate": _safe_rate(work["is_calendar_year_end_window"], n),
        "fiscal_year_end_rate": _safe_rate(work["is_fiscal_year_end_window"], n),
        "near_common_threshold_rate": _safe_rate(work["is_near_common_threshold"], n),
        "same_vendor_date_amount_duplicate_candidate_rate": _safe_rate(
            work["is_same_vendor_date_amount_duplicate_candidate"],
            n,
        ),
        "same_vendor_department_date_amount_duplicate_candidate_rate": _safe_rate(
            work["is_same_vendor_department_date_amount_duplicate_candidate"],
            n,
        ),
        "same_vendor_contract_date_amount_duplicate_candidate_rate": _safe_rate(
            work["is_same_vendor_contract_date_amount_duplicate_candidate"],
            n,
        ),
        "top1_vendor_abs_amount_share": _top_share(work["vendor_name"], amount, 1),
        "top5_vendor_abs_amount_share": _top_share(work["vendor_name"], amount, 5),
        "top10_vendor_abs_amount_share": _top_share(work["vendor_name"], amount, 10),
    }

    rows = [{"metric": key, "value": value} for key, value in profile.items()]
    return profile, pd.DataFrame(rows)


def _triage_score(work: pd.DataFrame) -> pd.Series:
    amount_rank = work["abs_amount"].rank(pct=True).fillna(0.0)
    duplicate = work["is_same_vendor_date_amount_duplicate_candidate"].astype(float)
    threshold = work["is_near_common_threshold"].astype(float)
    weekend = work["is_weekend"].astype(float)
    period_end = (
        work["is_month_end_window"]
        | work["is_quarter_end_window"]
        | work["is_fiscal_year_end_window"]
    ).astype(float)
    round_amount = work["is_round_1000"].astype(float)
    return (
        0.40 * amount_rank
        + 0.20 * duplicate
        + 0.15 * threshold
        + 0.10 * weekend
        + 0.10 * period_end
        + 0.05 * round_amount
    )


def _make_review_sheet(work: pd.DataFrame, *, top_k: int, random_n: int, seed: int) -> pd.DataFrame:
    review = work.copy()
    review["external_dataset"] = "OpenDataPhilly_or_public_payments"
    review["external_row_id"] = review.index.astype(str)
    review["triage_score"] = _triage_score(review)
    review["sample_bucket"] = ""

    top = review.nlargest(min(top_k, len(review)), "triage_score").copy()
    top["sample_bucket"] = "triage_top_k"
    remaining = review.drop(index=top.index, errors="ignore")
    random = remaining.sample(n=min(random_n, len(remaining)), random_state=seed).copy()
    random["sample_bucket"] = "random_control"

    selected = pd.concat([top, random], ignore_index=False).reset_index(drop=True)
    selected["review_label"] = ""
    selected["review_label_allowed_values"] = "|".join(REVIEW_LABELS)
    selected["reviewer"] = ""
    selected["review_confidence_1_5"] = ""
    selected["review_rationale"] = ""
    selected["evidence_needed"] = ""
    selected["eligible_for_supervised_positive"] = ""

    columns = [
        "external_dataset",
        "external_row_id",
        "sample_bucket",
        "triage_score",
        "vendor_name",
        "department",
        "payment_date",
        "amount",
        "document_number",
        "document_prefix",
        "description",
        "contract_number",
        "is_negative_amount",
        "is_zero_amount",
        "is_round_1000",
        "is_weekend",
        "is_month_end_window",
        "is_quarter_end_window",
        "is_calendar_year_end_window",
        "is_fiscal_year_end_window",
        "is_near_common_threshold",
        "same_vendor_date_amount_group_size",
        "same_vendor_department_date_amount_group_size",
        "same_vendor_contract_date_amount_group_size",
        "review_label",
        "review_label_allowed_values",
        "reviewer",
        "review_confidence_1_5",
        "review_rationale",
        "evidence_needed",
        "eligible_for_supervised_positive",
    ]
    return selected[[col for col in columns if col in selected.columns]]


def _write_mapping_report(
    output_dir: Path,
    mapping: dict[str, MappingChoice],
    source_columns: list[str],
) -> None:
    payload = {
        "created_at": _now_iso(),
        "source_columns": source_columns,
        "mapping": {
            key: {
                "source": choice.source,
                "confidence": choice.confidence,
                "reason": choice.reason,
            }
            for key, choice in mapping.items()
        },
    }
    (output_dir / "schema_mapping_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Schema Mapping Report",
        "",
        "| Canonical field | Source column | Confidence | Reason |",
        "|---|---|---|---|",
    ]
    for key, choice in mapping.items():
        source = choice.source or "`missing`"
        lines.append(f"| `{key}` | {source} | {choice.confidence} | {choice.reason} |")
    (output_dir / "schema_mapping_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_base_rate_report(
    output_dir: Path,
    profile: dict[str, Any],
    profile_df: pd.DataFrame,
) -> None:
    (output_dir / "base_rate_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    profile_df.to_csv(output_dir / "base_rate_profile.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# Base-Rate Profile",
        "",
        "This report is unlabeled. Do not read these rates as fraud precision, recall, or AUPRC.",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in profile.items():
        if isinstance(value, float):
            rendered = f"{value:.6f}"
        else:
            rendered = str(value)
        lines.append(f"| `{key}` | {rendered} |")
    (output_dir / "base_rate_profile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="Local file path or public CSV/Parquet/XLSX URL.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "artifacts" / "external_validation" / "open_data_philly_bootstrap"),
        help="Directory for reports and review sheet.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=100,
        help="Number of triage-ranked rows to review.",
    )
    parser.add_argument("--random-n", type=int, default=100, help="Number of random control rows.")
    parser.add_argument("--seed", type=int, default=20260519, help="Random sample seed.")
    parser.add_argument(
        "--fiscal-year-end-month",
        type=int,
        default=12,
        choices=range(1, 13),
        metavar="{1..12}",
        help="Fiscal year-end month for period-end base-rate measurement.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = _read_input(args.input)
    mapping = _choose_mapping(list(df.columns))
    work = _build_work_frame(
        df,
        mapping,
        fiscal_year_end_month=args.fiscal_year_end_month,
    )
    profile, profile_df = _profile_base_rates(work)
    review_sheet = _make_review_sheet(
        work,
        top_k=args.top_k,
        random_n=args.random_n,
        seed=args.seed,
    )

    _write_mapping_report(output_dir, mapping, list(df.columns))
    _write_base_rate_report(output_dir, profile, profile_df)
    review_sheet.to_csv(output_dir / "golden_review_sheet.csv", index=False, encoding="utf-8-sig")

    summary = {
        "created_at": _now_iso(),
        "input": args.input,
        "rows": int(len(df)),
        "output_dir": str(output_dir),
        "review_rows": int(len(review_sheet)),
        "top_k": int(args.top_k),
        "random_n": int(args.random_n),
        "fiscal_year_end_month": int(args.fiscal_year_end_month),
        "note": "Unlabeled bootstrap only. No supervised training or active promotion.",
    }
    (output_dir / "bootstrap_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
