"""Create an independent second-pass review and compare with user labels.

The assistant labels are conservative and use only public OpenDataPhilly fields.
They are not fraud determinations. Their purpose is to highlight rows where the
human review label may deserve a second look before the packet is used for
shadow evaluation.
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


def _num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def _contains(series: pd.Series, *tokens: str) -> pd.Series:
    text = series.fillna("").astype(str).str.lower()
    mask = pd.Series(False, index=series.index)
    for token in tokens:
        mask |= text.str.contains(token.lower(), regex=False)
    return mask


def _assistant_labels(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    amount = _num(work["amount"])
    vendor_count = _num(work.get("vendor_payment_count", pd.Series(0, index=work.index)))
    vendor_share = _num(work.get("vendor_abs_amount_share", pd.Series(0, index=work.index)))
    dup_contract = _num(
        work.get("same_vendor_contract_date_amount_group_size", pd.Series(0, index=work.index))
    )
    dup_vendor = _num(
        work.get("same_vendor_date_amount_group_size", pd.Series(0, index=work.index))
    )

    has_contract = (
        work.get("contract_number", pd.Series("", index=work.index))
        .astype(str)
        .str.strip()
        .ne("")
    )
    has_description = (
        work.get("description", pd.Series("", index=work.index))
        .astype(str)
        .str.strip()
        .ne("")
    )
    near_threshold = _bool(work.get("is_near_common_threshold", pd.Series(False, index=work.index)))
    fiscal_or_quarter = _bool(
        work.get("is_fiscal_year_end_window", pd.Series(False, index=work.index))
    ) | _bool(
        work.get("is_quarter_end_window", pd.Series(False, index=work.index)),
    )
    round_1000 = _bool(work.get("is_round_1000", pd.Series(False, index=work.index)))
    negative = amount.lt(0)
    desc = work.get("description", pd.Series("", index=work.index))
    sub_obj = work.get("sub_obj_title", pd.Series("", index=work.index))
    correction_text = _contains(desc, "refund", "credit", "adjust", "correction") | _contains(
        sub_obj,
        "refund",
        "credit",
        "adjust",
    )

    labels: list[str] = []
    confidence: list[int] = []
    rationale: list[str] = []
    eligible: list[str] = []

    for idx in work.index:
        if negative.at[idx] or correction_text.at[idx]:
            labels.append("accounting_error")
            confidence.append(3)
            rationale.append(
                "Public fields show negative/correction-like payment characteristics; "
                "treat as accounting/correction review, not a fraud-positive label."
            )
            eligible.append("false")
        elif (near_threshold.at[idx] or fiscal_or_quarter.at[idx] or round_1000.at[idx]) and (
            dup_contract.at[idx] > 1 or dup_vendor.at[idx] > 1
        ):
            labels.append("audit_review_candidate")
            confidence.append(2)
            rationale.append(
                "Combination of threshold/period/round signal and repeated "
                "vendor-date-amount pattern warrants review, but public fields do not "
                "prove an exception."
            )
            eligible.append("false")
        elif amount.at[idx] >= 100_000 and (
            not has_contract.at[idx] or not has_description.at[idx]
        ):
            labels.append("insufficient_evidence")
            confidence.append(2)
            rationale.append(
                "Large payment lacks enough public contract/description context for a "
                "positive or benign determination."
            )
            eligible.append("false")
        elif vendor_count.at[idx] >= 50 and vendor_share.at[idx] >= 0.0005 and (
            has_contract.at[idx] or has_description.at[idx]
        ):
            labels.append("benign_explainable")
            confidence.append(2)
            rationale.append(
                "High-volume vendor with public contract/description context; visible "
                "fields are consistent with recurring public payment operations."
            )
            eligible.append("false")
        elif not has_contract.at[idx] and not has_description.at[idx]:
            labels.append("insufficient_evidence")
            confidence.append(2)
            rationale.append("Public fields do not provide enough context for classification.")
            eligible.append("false")
        else:
            labels.append("audit_review_candidate")
            confidence.append(2)
            rationale.append(
                "Visible public fields support review but not a clear exception, control "
                "issue, accounting error, or benign conclusion."
            )
            eligible.append("false")

    return pd.DataFrame(
        {
            "assistant_review_label": labels,
            "assistant_confidence_1_5": confidence,
            "assistant_rationale": rationale,
            "assistant_eligible_for_supervised_positive": eligible,
        },
        index=work.index,
    )


def compare_labels(input_path: Path) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    df = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    assistant = _assistant_labels(df)
    compared = pd.concat([df, assistant], axis=1)
    compared["label_agreement"] = compared["review_label"].eq(compared["assistant_review_label"])
    compared["needs_second_review"] = ~compared["label_agreement"]

    matrix = pd.crosstab(
        compared["review_label"],
        compared["assistant_review_label"],
        dropna=False,
    )
    total = len(compared)
    agreement = int(compared["label_agreement"].sum())
    summary = {
        "created_at": _now_iso(),
        "input": str(input_path),
        "rows": total,
        "agreement_count": agreement,
        "disagreement_count": int(total - agreement),
        "agreement_rate": agreement / total if total else 0.0,
        "user_label_counts": compared["review_label"].value_counts().sort_index().to_dict(),
        "assistant_label_counts": (
            compared["assistant_review_label"].value_counts().sort_index().to_dict()
        ),
        "note": (
            "Assistant labels are conservative second-pass review labels from public fields only. "
            "Disagreement means review-needed, not user error."
        ),
    }
    return compared, summary, matrix


def _write_markdown(
    path: Path,
    summary: dict[str, Any],
    matrix: pd.DataFrame,
    compared: pd.DataFrame,
) -> None:
    lines = [
        "# OpenDataPhilly Review Label Comparison",
        "",
        f"- Rows: {summary['rows']}",
        f"- Agreement: {summary['agreement_count']} ({summary['agreement_rate']:.2%})",
        f"- Disagreement: {summary['disagreement_count']}",
        "",
        "Assistant labels are conservative second-pass labels based only on public fields. "
        "They are not fraud determinations.",
        "",
        "## User Label Counts",
        "",
        "| Label | Count |",
        "|---|---:|",
    ]
    for label, count in summary["user_label_counts"].items():
        lines.append(f"| `{label}` | {int(count)} |")
    lines.extend(["", "## Assistant Label Counts", "", "| Label | Count |", "|---|---:|"])
    for label, count in summary["assistant_label_counts"].items():
        lines.append(f"| `{label}` | {int(count)} |")
    lines.extend(["", "## Confusion Matrix", ""])
    lines.append(matrix.to_markdown())

    disagreements = compared.loc[~compared["label_agreement"]].head(30)
    lines.extend(
        [
            "",
            "## First Disagreements",
            "",
            "| Row | User label | Assistant label | Vendor | Date | Amount | Reason |",
            "|---|---|---|---|---|---:|---|",
        ]
    )
    for row in disagreements.to_dict(orient="records"):
        reason = str(row["assistant_rationale"]).replace("|", "/")
        lines.append(
            f"| `{row['external_row_id']}` | `{row['review_label']}` | "
            f"`{row['assistant_review_label']}` | {row['vendor_name']} | "
            f"{row['payment_date']} | {row['amount']} | {reason} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="selected_review_context.csv path.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for comparison artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    compared, summary, matrix = compare_labels(Path(args.input))

    compared.to_csv(
        output_dir / "golden_review_label_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    matrix.to_csv(output_dir / "golden_review_label_confusion_matrix.csv", encoding="utf-8-sig")
    (output_dir / "golden_review_label_comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown(output_dir / "golden_review_label_comparison.md", summary, matrix, compared)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
