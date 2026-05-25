"""Validated metadata helpers for DataSynth CSV outputs.

Why:
- DataSynth-reported JSON metadata can drift from the actual CSV outputs.
- Some quality counters such as ``records_with_issues`` are generator-internal
  and are not safely reusable as CSV-grounded evidence.
- This module defines a stable, observable reconciliation policy based on the
  ledger rows that the project actually consumes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_JE_COLUMNS: tuple[str, ...] = (
    "document_id",
    "company_code",
    "posting_date",
    "document_type",
    "gl_account",
    "line_number",
    "semantic_scenario_id",
    "counterparty_type",
)
PRIMARY_DUPLICATE_KEY_COLUMNS: tuple[str, ...] = ("document_id", "line_number")
LABEL_COLUMNS: tuple[str, ...] = (
    "is_fraud",
    "fraud_type",
    "is_anomaly",
    "anomaly_type",
    "sod_violation",
    "sod_conflict_type",
)
CRITICAL_GENERATION_FIELDS: tuple[str, ...] = (
    "total_entries",
    "total_line_items",
)
VALIDATED_ISSUE_DEFINITION = {
    "records_with_issues": [
        "normal_required_field_missing",
        "duplicate_document_line_key",
        "normal_unbalanced_document",
    ],
    "exclusions": [
        "generator-only typo counts",
        "format variation counts without source-of-truth baseline",
        "fuzzy duplicate inference without baseline pair labels",
    ],
}


@dataclass(frozen=True)
class ObservedMetadata:
    generation_statistics: dict[str, Any]
    data_quality_stats: dict[str, Any]
    issue_breakdown: dict[str, int]
    validation_policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetadataReconciliation:
    status: str
    critical_mismatches: list[str]
    warning_mismatches: list[str]
    reported_generation_statistics: dict[str, Any]
    reported_data_quality_stats: dict[str, Any]
    observed: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DATASYNTH_METADATA_STATUS_ATTR = "datasynth_metadata_status"
DATASYNTH_METADATA_PATH_ATTR = "datasynth_metadata_path"
DATASYNTH_METADATA_CRITICAL_ATTR = "datasynth_metadata_critical_mismatches"
DATASYNTH_METADATA_WARNING_ATTR = "datasynth_metadata_warning_mismatches"


def build_validated_metadata(
    source_csv: str | Path,
    *,
    generation_statistics_path: str | Path | None = None,
    data_quality_stats_path: str | Path | None = None,
) -> MetadataReconciliation:
    """Build reconciled metadata from a DataSynth ledger CSV and nearby JSON files."""
    source = Path(source_csv)
    df = pd.read_csv(source, low_memory=False)
    df = _attach_label_sidecar_if_needed(df, source)
    observed = _with_label_sidecar_counts(summarize_observed_metadata(df), source)
    generation_stats = _load_json_if_exists(Path(generation_statistics_path)) if generation_statistics_path else _load_json_if_exists(source.parent / "generation_statistics.json")
    data_quality = _load_json_if_exists(Path(data_quality_stats_path)) if data_quality_stats_path else _load_json_if_exists(source.parent / "data_quality_stats.json")
    return reconcile_reported_metadata(
        observed=observed,
        generation_statistics=generation_stats,
        data_quality_stats=data_quality,
    )


def write_validated_metadata(
    source_csv: str | Path,
    *,
    output_path: str | Path | None = None,
    generation_statistics_path: str | Path | None = None,
    data_quality_stats_path: str | Path | None = None,
) -> Path:
    """Write reconciled metadata JSON next to the source CSV."""
    source = Path(source_csv)
    target = Path(output_path) if output_path else default_validated_metadata_path(source)
    reconciliation = build_validated_metadata(
        source,
        generation_statistics_path=generation_statistics_path,
        data_quality_stats_path=data_quality_stats_path,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(reconciliation.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_semantic_validation_report(source, reconciliation)
    return target


def ensure_validated_metadata_json(source_csv: str | Path) -> Path | None:
    """Return a fresh validated metadata json, rebuilding it when needed."""
    source = Path(source_csv)
    target = default_validated_metadata_path(source)
    if target.exists() and not _validated_metadata_needs_refresh(source, target):
        return target
    if not source.exists():
        return target if target.exists() else None
    return write_validated_metadata(source, output_path=target)


def load_validated_metadata_json(source_csv: str | Path) -> MetadataReconciliation | None:
    """Load validated metadata JSON, generating it first when possible."""
    target = ensure_validated_metadata_json(source_csv)
    if target is None or not target.exists():
        return None
    payload = _load_json_if_exists(target)
    if payload is None:
        return None
    return MetadataReconciliation(
        status=str(payload.get("status", "unknown")),
        critical_mismatches=list(payload.get("critical_mismatches", [])),
        warning_mismatches=list(payload.get("warning_mismatches", [])),
        reported_generation_statistics=dict(payload.get("reported_generation_statistics", {})),
        reported_data_quality_stats=dict(payload.get("reported_data_quality_stats", {})),
        observed=dict(payload.get("observed", {})),
    )


def apply_validated_metadata_attrs(
    df: pd.DataFrame,
    reconciliation: MetadataReconciliation | None,
    *,
    source_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Attach validated metadata summary attrs to a dataframe."""
    out = df.copy()
    if reconciliation is None:
        return out
    out.attrs[DATASYNTH_METADATA_STATUS_ATTR] = reconciliation.status
    out.attrs[DATASYNTH_METADATA_CRITICAL_ATTR] = list(reconciliation.critical_mismatches)
    out.attrs[DATASYNTH_METADATA_WARNING_ATTR] = list(reconciliation.warning_mismatches)
    if source_csv is not None:
        out.attrs[DATASYNTH_METADATA_PATH_ATTR] = str(default_validated_metadata_path(source_csv))
    return out


def build_validated_metadata_messages(
    reconciliation: MetadataReconciliation | None,
) -> list[str]:
    """Return user-facing warning/error messages from validated metadata."""
    if reconciliation is None:
        return []

    messages: list[str] = []
    if reconciliation.critical_mismatches:
        critical_preview = "; ".join(reconciliation.critical_mismatches[:3])
        messages.append(
            "DataSynth metadata validation failed: "
            f"{critical_preview}"
        )
    if reconciliation.warning_mismatches:
        warning_preview = "; ".join(reconciliation.warning_mismatches[:3])
        messages.append(
            "DataSynth metadata warning: "
            f"{warning_preview}"
        )
    return messages


def default_validated_metadata_path(source_csv: str | Path) -> Path:
    """Return a stable validated metadata path for a ledger CSV."""
    source = Path(source_csv)
    stem = source.stem
    if stem.startswith("journal_entries_"):
        suffix = stem.removeprefix("journal_entries_")
        return source.parent / f"validated_metadata_{suffix}.json"
    return source.parent / "validated_metadata.json"


def semantic_validation_report_path(source_csv: str | Path) -> Path:
    return Path(source_csv).parent / "reports" / "semantic_validation_report.md"


def _write_semantic_validation_report(
    source_csv: Path,
    reconciliation: MetadataReconciliation,
) -> None:
    observed = reconciliation.observed
    generation = observed.get("generation_statistics", {})
    issues = observed.get("issue_breakdown", {})
    policy = observed.get("validation_policy", {})
    lines = [
        "# DataSynth Semantic Validation Report",
        "",
        f"- source_csv: `{source_csv.as_posix()}`",
        f"- status: `{reconciliation.status}`",
        "",
        "## Export Counts",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| total_entries | {generation.get('total_entries', 0)} |",
        f"| total_line_items | {generation.get('total_line_items', 0)} |",
        f"| anomalies_injected | {generation.get('anomalies_injected', '')} |",
        f"| anomaly_or_fraud_row_count | {generation.get('anomaly_or_fraud_row_count', 0)} |",
        f"| anomaly_or_fraud_document_count | {generation.get('anomaly_or_fraud_document_count', 0)} |",
        "",
        "## Input Contract Issues",
        "",
        "| issue | rows |",
        "|---|---:|",
    ]
    for key in (
        "normal_required_field_missing",
        "required_field_missing",
        "duplicate_document_line_key",
        "normal_unbalanced_document",
        "unbalanced_document",
        "abnormal_unbalanced_document",
    ):
        lines.append(f"| {key} | {issues.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Reconciliation",
            "",
            "| type | count |",
            "|---|---:|",
            f"| critical_mismatches | {len(reconciliation.critical_mismatches)} |",
            f"| warning_mismatches | {len(reconciliation.warning_mismatches)} |",
            "",
            "## Policy",
            "",
            "Records with issues are based on normal input-contract failures and duplicate keys, not optional evaluation metadata.",
            "",
            "```json",
            json.dumps(policy, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    if reconciliation.critical_mismatches:
        lines.extend(["## Critical Mismatches", ""])
        lines.extend(f"- {item}" for item in reconciliation.critical_mismatches)
        lines.append("")
    if reconciliation.warning_mismatches:
        lines.extend(["## Warning Mismatches", ""])
        lines.extend(f"- {item}" for item in reconciliation.warning_mismatches)
        lines.append("")

    report = semantic_validation_report_path(source_csv)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")


def summarize_observed_metadata(df: pd.DataFrame) -> ObservedMetadata:
    """Compute observable metadata directly from the ledger dataframe."""
    total_rows = int(len(df))
    total_documents = _distinct_document_count(df)
    anomaly_mask = _anomaly_or_fraud_mask(df)
    anomaly_rows = int(anomaly_mask.sum())
    anomaly_documents = (
        int(df.loc[anomaly_mask, "document_id"].dropna().nunique())
        if "document_id" in df.columns
        else 0
    )
    anomalies_injected = _count_labeled_documents(df)

    missing_masks = {
        column: _missing_mask(df[column])
        for column in df.columns
    }
    total_missing = int(sum(mask.sum() for mask in missing_masks.values()))
    records_with_missing_mask = _combine_masks(missing_masks.values())

    duplicate_key_mask = _duplicate_key_group_mask(df)
    unbalanced_mask = _unbalanced_document_mask(df)
    required_missing_mask = _required_field_missing_mask(df)
    normal_mask = ~anomaly_mask
    normal_required_missing_mask = required_missing_mask & normal_mask
    normal_unbalanced_mask = unbalanced_mask & normal_mask

    records_with_issues_mask = _combine_masks(
        (normal_required_missing_mask, duplicate_key_mask, normal_unbalanced_mask)
    )
    issue_breakdown = {
        "required_field_missing": int(required_missing_mask.sum()),
        "normal_required_field_missing": int(normal_required_missing_mask.sum()),
        "duplicate_document_line_key": int(duplicate_key_mask.sum()),
        "unbalanced_document": int(unbalanced_mask.sum()),
        "normal_unbalanced_document": int(normal_unbalanced_mask.sum()),
        "abnormal_unbalanced_document": int((unbalanced_mask & anomaly_mask).sum()),
    }

    data_quality_stats = {
        "missing_values": {
            "total_fields": int(df.shape[0] * df.shape[1]),
            "total_missing": total_missing,
            "by_field": {
                column: int(mask.sum())
                for column, mask in missing_masks.items()
                if int(mask.sum()) > 0
            },
            "records_with_missing": int(records_with_missing_mask.sum()),
            "total_records": total_rows,
        },
        "format_variations": {
            "date_variations": 0,
            "amount_variations": 0,
            "identifier_variations": 0,
            "text_variations": 0,
            "total_processed": total_rows,
        },
        "duplicates": {
            "total_processed": total_rows,
            "total_duplicates": int(_duplicate_key_count(df)),
            "exact_duplicates": int(df.duplicated(keep="first").sum()),
            "near_duplicates": 0,
            "fuzzy_duplicates": 0,
            "cross_system_duplicates": 0,
        },
        "typos": {
            "total_characters": 0,
            "total_typos": 0,
            "by_type": {},
            "total_words": 0,
            "words_with_typos": 0,
        },
        "encoding_issues": 0,
        "total_records": total_rows,
        "records_with_issues": int(records_with_issues_mask.sum()),
    }
    generation_statistics = {
        "total_entries": total_documents,
        "total_line_items": total_rows,
        "anomalies_injected": anomalies_injected,
        "anomaly_label_count": anomalies_injected,
        "anomaly_label_document_count": anomalies_injected,
        "anomaly_or_fraud_row_count": anomaly_rows,
        "anomaly_or_fraud_document_count": anomaly_documents,
        "data_quality_issues": int(records_with_issues_mask.sum()),
    }
    return ObservedMetadata(
        generation_statistics=generation_statistics,
        data_quality_stats=data_quality_stats,
        issue_breakdown=issue_breakdown,
        validation_policy={
            "records_with_issues_definition": VALIDATED_ISSUE_DEFINITION["records_with_issues"],
            "exclusions": VALIDATED_ISSUE_DEFINITION["exclusions"],
        },
    )


def reconcile_reported_metadata(
    *,
    observed: ObservedMetadata,
    generation_statistics: dict[str, Any] | None = None,
    data_quality_stats: dict[str, Any] | None = None,
) -> MetadataReconciliation:
    """Compare reported JSON metadata with observable CSV-grounded metadata."""
    reported_generation = generation_statistics or {}
    reported_quality = data_quality_stats or {}
    critical_mismatches: list[str] = []
    warning_mismatches: list[str] = []

    for field in CRITICAL_GENERATION_FIELDS:
        observed_value = observed.generation_statistics.get(field)
        reported_value = reported_generation.get(field)
        mismatch = _compare_scalar_field(
            field=field,
            reported=reported_value,
            observed=observed_value,
        )
        if mismatch:
            critical_mismatches.append(mismatch)

    quality_field_map = {
        "records_with_issues": observed.data_quality_stats.get("records_with_issues"),
        "missing_values.total_missing": observed.data_quality_stats["missing_values"].get("total_missing"),
        "duplicates.total_duplicates": observed.data_quality_stats["duplicates"].get("total_duplicates"),
    }
    for field, observed_value in quality_field_map.items():
        reported_value = _get_nested_value(reported_quality, field)
        mismatch = _compare_scalar_field(
            field=field,
            reported=reported_value,
            observed=observed_value,
        )
        if not mismatch:
            continue
        warning_mismatches.append(mismatch)

    if observed.issue_breakdown.get("normal_required_field_missing", 0):
        critical_mismatches.append(
            "normal_required_field_missing: "
            f"observed={observed.issue_breakdown['normal_required_field_missing']}"
        )
    if observed.issue_breakdown.get("normal_unbalanced_document", 0):
        critical_mismatches.append(
            "normal_unbalanced_document: "
            f"observed={observed.issue_breakdown['normal_unbalanced_document']}"
        )

    status = "pass"
    if critical_mismatches:
        status = "fail"
    elif warning_mismatches:
        status = "warning"

    return MetadataReconciliation(
        status=status,
        critical_mismatches=critical_mismatches,
        warning_mismatches=warning_mismatches,
        reported_generation_statistics=reported_generation,
        reported_data_quality_stats=reported_quality,
        observed=observed.to_dict(),
    )


def _distinct_document_count(df: pd.DataFrame) -> int:
    if "document_id" not in df.columns:
        return 0
    return int(df["document_id"].dropna().nunique())


def _count_labeled_documents(df: pd.DataFrame) -> int | None:
    if "document_id" not in df.columns:
        return None
    label_cols = [col for col in ("is_anomaly", "is_fraud") if col in df.columns]
    if not label_cols:
        return None
    working = df[label_cols].copy()
    truthy = pd.Series(False, index=df.index)
    for col in label_cols:
        series = working[col]
        if pd.api.types.is_bool_dtype(series):
            truthy = truthy | series.fillna(False)
        elif col.endswith("_type"):
            truthy = truthy | (~_missing_mask(series))
        else:
            lowered = series.astype("string").str.strip().str.lower()
            truthy = truthy | lowered.isin({"1", "true", "y", "yes"})
    return int(df.loc[truthy, "document_id"].dropna().nunique())


def _with_label_sidecar_counts(
    observed: ObservedMetadata,
    source_csv: Path,
) -> ObservedMetadata:
    label_path = source_csv.parent / "labels" / "anomaly_labels.csv"
    if not label_path.exists():
        return observed
    try:
        labels = pd.read_csv(label_path, usecols=lambda column: column == "document_id")
    except Exception:
        return observed
    label_count = int(len(labels))
    label_document_count = (
        int(labels["document_id"].dropna().nunique())
        if "document_id" in labels.columns
        else label_count
    )
    generation_statistics = dict(observed.generation_statistics)
    generation_statistics["anomalies_injected"] = label_count
    generation_statistics["anomaly_label_count"] = label_count
    generation_statistics["anomaly_label_document_count"] = label_document_count
    return replace(observed, generation_statistics=generation_statistics)


def _anomaly_or_fraud_mask(df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for column in ("is_anomaly", "is_fraud"):
        if column not in df.columns:
            continue
        series = df[column]
        if pd.api.types.is_bool_dtype(series):
            mask = mask | series.fillna(False)
        else:
            mask = mask | series.astype("string").str.strip().str.lower().isin(
                {"1", "true", "y", "yes"}
            )
    return mask.fillna(False)


def _required_field_missing_mask(df: pd.DataFrame) -> pd.Series:
    masks: list[pd.Series] = []
    for column in REQUIRED_JE_COLUMNS:
        if column not in df.columns:
            masks.append(pd.Series(True, index=df.index))
            continue
        masks.append(_missing_mask(df[column]))
    return _combine_masks(masks)


def _duplicate_key_group_mask(df: pd.DataFrame) -> pd.Series:
    available = [col for col in PRIMARY_DUPLICATE_KEY_COLUMNS if col in df.columns]
    if len(available) != len(PRIMARY_DUPLICATE_KEY_COLUMNS):
        return pd.Series(False, index=df.index)
    return df.duplicated(subset=available, keep=False)


def _duplicate_key_count(df: pd.DataFrame) -> int:
    available = [col for col in PRIMARY_DUPLICATE_KEY_COLUMNS if col in df.columns]
    if len(available) != len(PRIMARY_DUPLICATE_KEY_COLUMNS):
        return 0
    return int(df.duplicated(subset=available, keep="first").sum())


def _unbalanced_document_mask(df: pd.DataFrame) -> pd.Series:
    required = {"document_id", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        return pd.Series(False, index=df.index)

    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    grouped = pd.DataFrame({
        "document_id": df["document_id"],
        "debit_amount": debit,
        "credit_amount": credit,
    }).groupby("document_id", dropna=True, sort=False).sum()
    unbalanced_ids = grouped.index[(grouped["debit_amount"] - grouped["credit_amount"]).abs() > 0.01]
    if len(unbalanced_ids) == 0:
        return pd.Series(False, index=df.index)
    return df["document_id"].isin(unbalanced_ids)


def _missing_mask(series: pd.Series) -> pd.Series:
    mask = series.isna()
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        mask = mask | series.astype("string").str.strip().eq("")
    return mask.fillna(False)


def _combine_masks(masks: Any) -> pd.Series:
    masks = list(masks)
    if not masks:
        return pd.Series(dtype=bool)
    combined = masks[0].copy()
    for mask in masks[1:]:
        combined = combined | mask
    return combined.fillna(False)


def _get_nested_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _compare_scalar_field(*, field: str, reported: Any, observed: Any) -> str | None:
    if reported is None and observed is None:
        return None
    if reported == observed:
        return None
    return f"{field}: reported={reported!r}, observed={observed!r}"


def _attach_label_sidecar_if_needed(df: pd.DataFrame, source_csv: Path) -> pd.DataFrame:
    if any(column in df.columns for column in LABEL_COLUMNS):
        return df
    if "document_id" not in df.columns:
        return df

    from src.ingest.datasynth_labels import load_document_labels

    labels_df = load_document_labels(source_csv)
    if labels_df is None or labels_df.empty or "document_id" not in labels_df.columns:
        return df
    available = ["document_id", *[col for col in LABEL_COLUMNS if col in labels_df.columns]]
    if len(available) == 1:
        return df
    return df.merge(labels_df[available], on="document_id", how="left", validate="m:1")


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def _validated_metadata_needs_refresh(source_csv: Path, validated_json: Path) -> bool:
    try:
        baseline_mtime = source_csv.stat().st_mtime
        for extra in ("generation_statistics.json", "data_quality_stats.json"):
            candidate = source_csv.parent / extra
            if candidate.exists():
                baseline_mtime = max(baseline_mtime, candidate.stat().st_mtime)
        return validated_json.stat().st_mtime < baseline_mtime
    except OSError:
        return False
