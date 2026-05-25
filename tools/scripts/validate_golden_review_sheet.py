"""Validate and summarize a human-labeled golden review sheet.

This script does not train a model. It checks whether a review sheet is ready
for shadow evaluation and whether it satisfies the minimum supervised gate
counts. Empty labels are allowed and reported as IN_PROGRESS.

Usage:
    uv run python tools/scripts/validate_golden_review_sheet.py \
        --input artifacts/external_validation/open_data_philly_20260519/golden_review_sheet.csv \
        --output-dir artifacts/external_validation/open_data_philly_20260519
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

ALLOWED_LABELS = frozenset(
    {
        "confirmed_exception",
        "control_issue",
        "accounting_error",
        "audit_review_candidate",
        "benign_explainable",
        "insufficient_evidence",
    }
)

SUPERVISED_POSITIVE_LABELS = frozenset(
    {
        "confirmed_exception",
        "control_issue",
        "accounting_error",
    }
)

SUPERVISED_NEGATIVE_LABELS = frozenset({"benign_explainable"})
EXCLUDED_FROM_SUPERVISED_LABELS = frozenset(
    {
        "audit_review_candidate",
        "insufficient_evidence",
    }
)

REQUIRED_COLUMNS = frozenset(
    {
        "external_row_id",
        "sample_bucket",
        "vendor_name",
        "payment_date",
        "amount",
        "document_number",
        "review_label",
        "review_confidence_1_5",
        "review_rationale",
        "eligible_for_supervised_positive",
    }
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clean_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _as_bool_text(series: pd.Series) -> pd.Series:
    return _clean_text(series).str.lower()


def _confidence(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_review_sheet(path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing_columns = sorted(REQUIRED_COLUMNS - set(df.columns))
    issues: list[dict[str, Any]] = []

    label = _clean_text(df.get("review_label", pd.Series("", index=df.index)))
    confidence = _confidence(df.get("review_confidence_1_5", pd.Series("", index=df.index)))
    rationale = _clean_text(df.get("review_rationale", pd.Series("", index=df.index)))
    eligible = _as_bool_text(
        df.get("eligible_for_supervised_positive", pd.Series("", index=df.index))
    )

    reviewed_mask = label.ne("")
    invalid_label_mask = reviewed_mask & ~label.isin(ALLOWED_LABELS)
    invalid_confidence_mask = reviewed_mask & ~(confidence.between(1, 5, inclusive="both"))
    missing_rationale_mask = reviewed_mask & rationale.eq("")

    positive_mask = label.isin(SUPERVISED_POSITIVE_LABELS)
    negative_mask = label.isin(SUPERVISED_NEGATIVE_LABELS)
    excluded_mask = label.isin(EXCLUDED_FROM_SUPERVISED_LABELS)

    invalid_positive_eligibility_mask = positive_mask & ~eligible.isin({"true", "false"})
    invalid_excluded_eligibility_mask = excluded_mask & eligible.eq("true")
    invalid_negative_eligibility_mask = negative_mask & eligible.eq("true")

    issue_masks = {
        "invalid_label": invalid_label_mask,
        "invalid_confidence": invalid_confidence_mask,
        "missing_rationale": missing_rationale_mask,
        "positive_missing_eligibility_decision": invalid_positive_eligibility_mask,
        "excluded_label_marked_supervised_positive": invalid_excluded_eligibility_mask,
        "negative_label_marked_supervised_positive": invalid_negative_eligibility_mask,
    }
    for issue_type, mask in issue_masks.items():
        for row_idx in df.index[mask].tolist():
            issues.append(
                {
                    "row_index": int(row_idx),
                    "external_row_id": str(df.at[row_idx, "external_row_id"])
                    if "external_row_id" in df.columns
                    else "",
                    "issue_type": issue_type,
                    "review_label": str(label.at[row_idx]),
                }
            )

    trusted_positive_mask = (
        positive_mask
        & eligible.eq("true")
        & confidence.ge(4)
        & rationale.ne("")
        & ~invalid_label_mask
        & ~invalid_confidence_mask
    )
    trusted_negative_mask = (
        negative_mask
        & confidence.ge(3)
        & rationale.ne("")
        & ~invalid_label_mask
        & ~invalid_confidence_mask
    )
    supervised_labeled_mask = trusted_positive_mask | trusted_negative_mask

    reviewed_rows = int(reviewed_mask.sum())
    trusted_positive_count = int(trusted_positive_mask.sum())
    trusted_negative_count = int(trusted_negative_mask.sum())
    supervised_labeled_count = int(supervised_labeled_mask.sum())
    trusted_positive_rate = (
        trusted_positive_count / supervised_labeled_count if supervised_labeled_count else 0.0
    )

    if missing_columns or issues:
        status = "FAIL"
    elif reviewed_rows == 0:
        status = "IN_PROGRESS"
    elif trusted_positive_count >= 50 and trusted_positive_rate >= 0.01:
        status = "SHADOW_ELIGIBLE"
    else:
        status = "REVIEWED_LOW_SIGNAL"

    label_counts = label[reviewed_mask].value_counts(dropna=False).sort_index().to_dict()
    bucket_counts = (
        df.groupby(["sample_bucket", label.where(reviewed_mask, "__unlabeled__")], dropna=False)
        .size()
        .reset_index(name="count")
    )

    summary: dict[str, Any] = {
        "created_at": _now_iso(),
        "input": str(path),
        "status": status,
        "rows": int(len(df)),
        "reviewed_rows": reviewed_rows,
        "unreviewed_rows": int((~reviewed_mask).sum()),
        "missing_columns": missing_columns,
        "issue_count": int(len(issues)),
        "label_counts": {str(k): int(v) for k, v in label_counts.items()},
        "trusted_positive_count": trusted_positive_count,
        "trusted_negative_count": trusted_negative_count,
        "supervised_labeled_count": supervised_labeled_count,
        "trusted_positive_rate": trusted_positive_rate,
        "supervised_gate": {
            "min_positive_count": 50,
            "min_positive_rate": 0.01,
            "eligible": status == "SHADOW_ELIGIBLE",
            "note": (
                "Shadow eligibility only. Active promotion still requires leakage "
                "and split checks."
            ),
        },
        "issues": issues[:200],
    }
    return summary, bucket_counts


def _write_markdown(path: Path, summary: dict[str, Any], bucket_counts: pd.DataFrame) -> None:
    lines = [
        "# Golden Review Sheet Validation",
        "",
        f"- Status: **{summary['status']}**",
        f"- Rows: {summary['rows']}",
        f"- Reviewed rows: {summary['reviewed_rows']}",
        f"- Unreviewed rows: {summary['unreviewed_rows']}",
        f"- Issue count: {summary['issue_count']}",
        f"- Trusted positives: {summary['trusted_positive_count']}",
        f"- Trusted negatives: {summary['trusted_negative_count']}",
        f"- Trusted positive rate: {summary['trusted_positive_rate']:.4%}",
        "",
        "## Label Counts",
        "",
        "| Label | Count |",
        "|---|---:|",
    ]
    for label, count in summary["label_counts"].items():
        lines.append(f"| `{label}` | {count} |")
    if not summary["label_counts"]:
        lines.append("| `(none)` | 0 |")

    lines.extend(
        [
            "",
            "## Bucket Counts",
            "",
            "| Sample bucket | Label | Count |",
            "|---|---|---:|",
        ]
    )
    for row in bucket_counts.to_dict(orient="records"):
        lines.append(
            f"| `{row['sample_bucket']}` | `{row['review_label']}` | {int(row['count'])} |"
        )

    if summary["missing_columns"]:
        lines.extend(["", "## Missing Columns", ""])
        for col in summary["missing_columns"]:
            lines.append(f"- `{col}`")

    if summary["issues"]:
        lines.extend(
            [
                "",
                "## First Issues",
                "",
                "| Row | External row | Issue | Label |",
                "|---:|---|---|---|",
            ]
        )
        for issue in summary["issues"][:25]:
            lines.append(
                f"| {issue['row_index']} | `{issue['external_row_id']}` | "
                f"`{issue['issue_type']}` | `{issue['review_label']}` |"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to golden_review_sheet.csv.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Defaults to the input file's parent.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    summary, bucket_counts = validate_review_sheet(input_path)
    _json_dump(output_dir / "golden_review_validation.json", summary)
    bucket_counts.to_csv(
        output_dir / "golden_review_bucket_counts.csv",
        index=False,
        encoding="utf-8-sig",
    )
    _write_markdown(output_dir / "golden_review_validation.md", summary, bucket_counts)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
