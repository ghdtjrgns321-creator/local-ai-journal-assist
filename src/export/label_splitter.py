"""Utilities for separating ledger rows and document-level labels."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.preprocessing.constants import LABEL_COLUMNS

_DEFAULT_KEY_COLUMNS = ("document_id",)


def split_label_columns(
    df: pd.DataFrame,
    *,
    key_columns: tuple[str, ...] = _DEFAULT_KEY_COLUMNS,
    label_columns: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a ledger dataframe into body rows and document-level labels."""
    if not key_columns:
        raise ValueError("key_columns must not be empty")

    missing_keys = [col for col in key_columns if col not in df.columns]
    if missing_keys:
        raise ValueError(f"missing key columns: {missing_keys}")

    label_cols = _resolve_label_columns(df, label_columns)
    body_df = df.drop(columns=list(label_cols), errors="ignore").copy()
    labels_df = _build_document_labels(df, key_columns=key_columns, label_columns=label_cols)
    return body_df, labels_df


def split_label_csv(
    source_csv: str | Path,
    *,
    body_output_csv: str | Path,
    labels_output_csv: str | Path,
    key_columns: tuple[str, ...] = _DEFAULT_KEY_COLUMNS,
    label_columns: tuple[str, ...] | None = None,
    encoding: str = "utf-8-sig",
) -> tuple[Path, Path]:
    """Read a ledger CSV, split labels, and write two CSV files."""
    src = Path(source_csv)
    body_path = Path(body_output_csv)
    labels_path = Path(labels_output_csv)

    df = pd.read_csv(src, low_memory=False)
    body_df, labels_df = split_label_columns(
        df,
        key_columns=key_columns,
        label_columns=label_columns,
    )

    body_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    body_df.to_csv(body_path, index=False, encoding=encoding)
    labels_df.to_csv(labels_path, index=False, encoding=encoding)
    return body_path, labels_path


def _resolve_label_columns(
    df: pd.DataFrame,
    label_columns: tuple[str, ...] | None,
) -> tuple[str, ...]:
    requested = label_columns or tuple(LABEL_COLUMNS)
    existing = [col for col in df.columns if col in requested]
    return tuple(existing)


def _build_document_labels(
    df: pd.DataFrame,
    *,
    key_columns: tuple[str, ...],
    label_columns: tuple[str, ...],
) -> pd.DataFrame:
    if not label_columns:
        return df.loc[:, list(key_columns)].drop_duplicates().reset_index(drop=True)

    records: list[dict] = []
    grouped = df.groupby(list(key_columns), dropna=False, sort=True)

    for key_values, group in grouped:
        record = _build_key_record(key_columns, key_values)
        for col in label_columns:
            record[col] = _collapse_document_label(group[col], key=record, column=col)
        records.append(record)

    return pd.DataFrame(records, columns=[*key_columns, *label_columns])


def _build_key_record(
    key_columns: tuple[str, ...],
    key_values,
) -> dict:
    if len(key_columns) == 1 and not isinstance(key_values, tuple):
        key_values = (key_values,)
    return dict(zip(key_columns, key_values, strict=False))


def _collapse_document_label(series: pd.Series, *, key: dict, column: str):
    normalized = _normalize_series(series)
    unique_values = normalized.drop_duplicates().tolist()
    if len(unique_values) > 1:
        raise ValueError(
            f"inconsistent label values for key={key}, column='{column}': {unique_values}",
        )
    if not unique_values:
        return None
    return unique_values[0]


def _normalize_series(series: pd.Series) -> pd.Series:
    cleaned = series.dropna()
    if cleaned.empty:
        return cleaned
    if cleaned.dtype == object:
        cleaned = cleaned.astype(str).str.strip()
        cleaned = cleaned[cleaned != ""]
    return cleaned
