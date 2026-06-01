"""Shared explanation builders for UI and export paths."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import pandas as pd

from src.detection.base import DetectionResult
from src.detection.constants import RULE_CODES, get_rule_explanation

_DEFAULT_RULE_REFERENCES: dict[str, tuple[str, ...]] = {
    "L1-01": ("ISA 240.32-33", "ISA 230"),
    "L2-02": ("ISA 240.32-33",),
    "L2-05": ("ISA 240.32-33",),
    "L3-04": ("ISA 240.32-33",),
    "L4-02": ("ISA 520.5",),
    "ML02": ("ISA 240.32-33",),
    "EN01": ("ISA 240.32-33",),
}


def parse_flagged_rules(value: Any) -> list[str]:
    """Parse a CSV or list value into rule codes."""

    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [rule.strip() for rule in text.split(",") if rule.strip()]


def build_track_explanation(result: DetectionResult) -> dict[str, Any]:
    """Build track-level explanation metadata."""

    return {
        "track_name": result.track_name,
        "display_name": result.display_name,
        "summary": result.explanation_summary,
        "why_it_flagged": result.why_it_flagged,
        "used_columns": result.used_columns,
        "false_positive_risks": result.false_positive_risks,
        "auditor_checks": result.auditor_checks,
        "references": result.references,
        "warnings": [str(warning) for warning in result.warnings],
    }


def build_rule_explanation(rule_id: str) -> dict[str, Any]:
    """Build rule-level explanation metadata."""

    rule = get_rule_explanation(rule_id)
    references = rule.references or _DEFAULT_RULE_REFERENCES.get(rule_id, ())
    return {
        "rule_id": rule_id,
        "rule_name": RULE_CODES.get(rule_id, "Unknown Rule"),
        "plain_reason": rule.plain_reason,
        "used_columns": [str(value) for value in rule.used_columns],
        "false_positive_risks": [str(value) for value in rule.false_positive_risks],
        "auditor_checks": [str(value) for value in rule.auditor_checks],
        "references": [str(value) for value in references],
    }


def build_document_explanation(
    doc_id: str,
    result_data: pd.DataFrame,
    results: list[DetectionResult] | None = None,
) -> dict[str, Any]:
    """Build a document-level explanation block."""

    if "document_id" not in result_data.columns:
        return _empty_document_explanation(doc_id)

    doc_lines = result_data[result_data["document_id"] == doc_id].copy()
    if doc_lines.empty:
        return _empty_document_explanation(doc_id)

    first_row = doc_lines.iloc[0]
    rule_ids = parse_flagged_rules(first_row.get("flagged_rules"))
    rule_explanations = [build_rule_explanation(rule_id) for rule_id in rule_ids]

    track_explanations: list[dict[str, Any]] = []
    row_annotations_by_rule: dict[str, dict[int, dict[str, Any]]] = {}
    if results:
        doc_indices = set(int(index) for index in doc_lines.index.tolist())
        for result in results:
            if doc_indices.intersection(int(index) for index in result.flagged_indices):
                track_explanations.append(build_track_explanation(result))
            annotations = (result.metadata or {}).get("row_annotations", {})
            for rule_id, rule_annotations in annotations.items():
                filtered = {
                    int(index): value
                    for index, value in rule_annotations.items()
                    if int(index) in doc_indices
                }
                if filtered:
                    row_annotations_by_rule[rule_id] = filtered

    used_columns = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("used_columns", [])
    )
    false_positive_risks = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("false_positive_risks", [])
    )
    auditor_focus_points = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("auditor_checks", [])
    )
    references = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("references", [])
    )
    transaction_details = _build_transaction_details(doc_lines, rule_ids, row_annotations_by_rule)

    risk_level = str(first_row.get("risk_level", "Unknown"))
    anomaly_score = float(first_row.get("anomaly_score", 0.0) or 0.0)
    if rule_explanations:
        top_reasons = ", ".join(
            f"{item['rule_id']}({item['rule_name']})" for item in rule_explanations[:3]
        )
        headline = (
            f"Document {doc_id} was rated {risk_level} with anomaly_score={anomaly_score:.3f}. "
            f"Top signals: {top_reasons}."
        )
    else:
        headline = (
            f"Document {doc_id} was rated {risk_level} with anomaly_score={anomaly_score:.3f}. "
            "No rule-level signal was attached."
        )

    return {
        "document_id": doc_id,
        "headline": headline,
        "triggered_rules": rule_explanations,
        "auditor_focus_points": auditor_focus_points,
        "auditor_action_guides": auditor_focus_points,
        "transaction_details": transaction_details,
        "used_columns": used_columns,
        "false_positive_risks": false_positive_risks,
        "references": references,
        "track_explanations": track_explanations,
        "narrative": _build_narrative(
            doc_id,
            risk_level,
            anomaly_score,
            rule_explanations,
            transaction_details,
            auditor_focus_points,
        ),
    }


def build_export_narrative(
    document_id: str,
    score: float,
    risk: str,
    rules: list[str],
    top_features: list[tuple[str, float]],
) -> str:
    """Build a short export narrative."""

    rule_explanations = [build_rule_explanation(rule_id) for rule_id in rules]
    parts = [f"Document {document_id} was classified as {risk} (anomaly_score={score:.3f})."]
    if rule_explanations:
        rule_text = ", ".join(
            _format_rule_export_text(rule["rule_id"], rule["rule_name"], rule["references"])
            for rule in rule_explanations
        )
        parts.append(f"Triggered rules: {rule_text}.")
    else:
        parts.append("No rule-based trigger was attached. ML 모델 단독 판정.")

    if top_features:
        feature_text = ", ".join(
            f"{name} (contribution={value:.3f})" for name, value in top_features
        )
        parts.append(f"Top feature contributions: {feature_text}.")

    auditor_checks = _merge_unique(
        item for rule in rule_explanations for item in rule.get("auditor_checks", [])
    )
    if auditor_checks:
        parts.append(f"Recommended audit follow-up: {auditor_checks[0]}. 재검토 권고.")
    elif rule_explanations:
        parts.append("재검토 권고.")

    return " ".join(parts)


def _empty_document_explanation(doc_id: str) -> dict[str, Any]:
    """Return an empty explanation payload."""

    return {
        "document_id": doc_id,
        "headline": f"No explanation metadata was found for document {doc_id}.",
        "triggered_rules": [],
        "auditor_focus_points": [],
        "auditor_action_guides": [],
        "transaction_details": [],
        "used_columns": [],
        "false_positive_risks": [],
        "references": [],
        "track_explanations": [],
        "narrative": f"No explanation metadata was found for document {doc_id}.",
    }


def _build_transaction_details(
    doc_lines: pd.DataFrame,
    rule_ids: list[str],
    row_annotations_by_rule: dict[str, dict[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Build line-level transaction details."""

    top_rules = rule_ids[:3]
    details: list[dict[str, Any]] = []
    for _, row in doc_lines.iterrows():
        amount = _coalesce_amount(row)
        details.append(
            {
                "document_id": str(row.get("document_id", "")),
                "line_number": _scalar_or_none(row.get("line_number")),
                "posting_date": _format_scalar(row.get("posting_date")),
                "gl_account": _format_scalar(row.get("gl_account")),
                "amount": amount,
                "amount_display": _format_amount(amount),
                "trigger_value": _build_trigger_value(
                    row,
                    doc_lines,
                    top_rules,
                    row_annotations_by_rule,
                ),
            }
        )
    return details


def _build_trigger_value(
    row: pd.Series,
    doc_lines: pd.DataFrame,
    rule_ids: list[str],
    row_annotations_by_rule: dict[str, dict[int, dict[str, Any]]],
) -> str:
    """Build a concise trigger summary."""

    if not rule_ids:
        return "No specific rule explanation is attached."

    triggers = []
    for rule_id in rule_ids:
        rule_annotations = row_annotations_by_rule.get(rule_id, {})
        row_annotation = rule_annotations.get(int(row.name))
        text = _rule_trigger_text(rule_id, row, doc_lines, row_annotation)
        if text:
            triggers.append(text)

    if triggers:
        return " / ".join(_merge_unique(triggers))
    return f"Rules {', '.join(rule_ids)} were triggered."


def _rule_trigger_text(
    rule_id: str,
    row: pd.Series,
    doc_lines: pd.DataFrame,
    row_annotation: dict[str, Any] | None = None,
) -> str:
    """Build a trigger sentence for one rule."""

    amount = _coalesce_amount(row)
    gl_account = _format_scalar(row.get("gl_account"))
    creator = _format_scalar(row.get("created_by"))
    approver = _format_scalar(row.get("approved_by"))
    source = _format_scalar(row.get("source"))
    business_process = _format_scalar(row.get("business_process"))
    line_text = _format_scalar(row.get("line_text"))
    header_text = _format_scalar(row.get("header_text"))

    if rule_id == "L1-01":
        debit_total = float(doc_lines.get("debit_amount", pd.Series(dtype=float)).fillna(0).sum())
        credit_total = float(doc_lines.get("credit_amount", pd.Series(dtype=float)).fillna(0).sum())
        return (
            f"Document is unbalanced: debit={debit_total:,.0f}, "
            f"credit={credit_total:,.0f}, diff={debit_total - credit_total:,.0f}"
        )
    if rule_id == "L1-02":
        missing = [
            field
            for field in ("document_id", "posting_date", "gl_account")
            if _is_missing(row.get(field))
        ]
        if missing:
            return f"Missing required fields: {', '.join(missing)}"
    if rule_id == "L1-03" and gl_account:
        return f"Invalid GL account {gl_account}"
    if rule_id == "L3-01" and gl_account and business_process:
        return f"Account {gl_account} is unusual for process {business_process}"
    if rule_id == "L2-01":
        return f"Amount is just below approval threshold ({_format_amount(amount)})"
    if rule_id == "L1-04":
        return f"Amount exceeds approval threshold ({_format_amount(amount)})"
    if rule_id == "L2-02":
        return f"Duplicate-payment pattern on amount {_format_amount(amount)}"
    if rule_id == "L2-03":
        return f"Duplicate-entry pattern on account {gl_account or '-'}"
    if rule_id == "L1-05" and creator and approver:
        return f"Self approval: preparer={creator}, approver={approver}"
    if rule_id == "L1-06":
        return f"SoD violation for user {creator or '-'} in process {business_process or '-'}"
    if rule_id == "L3-02":
        return f"Manual entry path source={source or '-'}"
    if rule_id == "L1-07":
        return f"Approval missing or skipped (approver={approver or 'NULL'})"
    if rule_id == "L3-03":
        return "Related-party account review signal"
    if rule_id == "L3-04":
        posting_date = _format_scalar(row.get("posting_date"))
        return f"Period-start/end closing review candidate on {posting_date}"
    if rule_id == "L3-05":
        return "Weekend or holiday posting"
    if rule_id == "L3-06":
        return "After-hours posting"
    if rule_id == "L3-07":
        return _l307_trigger_text(row)
    if rule_id == "L1-08":
        return "Fiscal period mismatch"
    if rule_id == "L3-08":
        text = line_text or header_text
        return f"Vague description '{text[:60]}'" if text else "Vague description"
    if rule_id == "L4-01":
        return f"Revenue outlier on account {gl_account or '-'}"
    if rule_id == "L4-02":
        return "Benford first-digit deviation"
    if rule_id == "L4-03":
        return f"High amount outlier {_format_amount(amount)}"
    if rule_id == "L4-04":
        return "Rare debit-credit account pair"
    if rule_id == "L3-09":
        return "Long-open suspense-account balance"
    if rule_id == "L2-05":
        if row_annotation:
            label = str(row_annotation.get("interpretation_label", "")).strip()
            reason = str(row_annotation.get("reason_text", "")).strip()
            if label and reason:
                return f"{label}: {reason}"
            if label:
                return label
        return "Candidate reversal / clearing / reclass pattern"

    return build_rule_explanation(rule_id)["plain_reason"]


def _l307_trigger_text(row: pd.Series) -> str:
    """Explain L3-07 with direction and day gap when available."""
    raw_days = row.get("days_backdated")
    if _is_missing(raw_days):
        return "Posting-document date gap"

    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return "Posting-document date gap"

    abs_days = abs(days)
    if days > 0:
        return f"Long-delayed posting: posting date is {abs_days} days after document date"
    if days < 0:
        return f"Forward-date gap: posting date is {abs_days} days before document date"
    return "Posting-document date gap"


def _build_narrative(
    doc_id: str,
    risk_level: str,
    anomaly_score: float,
    rule_explanations: list[dict[str, Any]],
    transaction_details: list[dict[str, Any]],
    auditor_focus_points: list[str],
) -> str:
    """Build a compact human-readable narrative."""

    if rule_explanations:
        reasons = ", ".join(
            f"{item['rule_id']} {item['plain_reason']}" for item in rule_explanations[:3]
        )
        text = (
            f"Document {doc_id} was rated {risk_level} with anomaly_score={anomaly_score:.3f}. "
            f"Primary reasons: {reasons}."
        )
    else:
        text = (
            f"Document {doc_id} was rated {risk_level} with anomaly_score={anomaly_score:.3f}. "
            "No rule-level explanation is attached."
        )

    if transaction_details:
        text += f" Trigger detail: {transaction_details[0]['trigger_value']}."
    if auditor_focus_points:
        text += f" Recommended follow-up: {auditor_focus_points[0]}."
    return text


def _coalesce_amount(row: pd.Series) -> float | None:
    """Return the dominant signed-line amount magnitude."""

    debit = row.get("debit_amount")
    credit = row.get("credit_amount")
    candidates = [value for value in (debit, credit) if pd.notna(value)]
    if not candidates:
        return None
    return float(max(candidates, key=lambda value: abs(float(value))))


def _format_rule_export_text(rule_id: str, rule_name: str, references: list[str]) -> str:
    """Format a rule token for export text."""

    if rule_name == "Unknown Rule":
        rule_name = "미등록 룰"
    if references:
        return f"{rule_id}({rule_name}) [{references[0]}]"
    return f"{rule_id}({rule_name})"


def _format_amount(value: float | None) -> str:
    """Format amount for human-readable output."""

    if value is None:
        return "-"
    return f"{value:,.0f}"


def _format_scalar(value: Any) -> str:
    """Format a scalar value for explanation output."""

    if _is_missing(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


def _scalar_or_none(value: Any) -> Any:
    """Return None for missing values, else the original value."""

    if _is_missing(value):
        return None
    return value


def _is_missing(value: Any) -> bool:
    """Return True when a scalar should be treated as missing."""

    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _merge_unique(values) -> list[str]:
    """Merge values while preserving order and removing blanks."""

    merged = OrderedDict()
    for value in values:
        text = str(value).strip()
        if text:
            merged[text] = None
    return list(merged.keys())
