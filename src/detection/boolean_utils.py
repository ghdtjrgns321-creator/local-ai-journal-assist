"""Robust boolean coercion helpers for detector inputs."""

from __future__ import annotations

from typing import Any

import pandas as pd

_TRUE_STRINGS = {"true", "1", "yes", "y", "t"}
_FALSE_STRINGS = {"false", "0", "no", "n", "f", "", "nan", "none", "null", "<na>"}


def coerce_bool_value(value: Any, *, default: bool = False) -> bool:
    """Return a bool scalar using the same string rules as ``coerce_bool_series``."""

    if pd.isna(value):
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _TRUE_STRINGS:
        return True
    if normalized in _FALSE_STRINGS:
        return False
    numeric = pd.to_numeric(pd.Series([normalized]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        return bool(numeric != 0)
    return default


def coerce_bool_series(
    values: pd.Series | Any,
    *,
    index: pd.Index | None = None,
    default: bool = False,
) -> pd.Series:
    """Return a bool Series without treating non-empty strings as truthy."""

    if isinstance(values, pd.Series):
        series = values
    else:
        series = pd.Series(values, index=index)
    if index is not None:
        series = series.reindex(index, fill_value=default)
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(default).astype(bool)
    normalized = series.fillna(default).astype(str).str.strip().str.lower()
    result = pd.Series(default, index=series.index, dtype=bool)
    result.loc[normalized.isin(_TRUE_STRINGS)] = True
    result.loc[normalized.isin(_FALSE_STRINGS)] = False
    numeric = pd.to_numeric(normalized, errors="coerce")
    result.loc[numeric.notna()] = numeric.loc[numeric.notna()].ne(0)
    return result.astype(bool)


def bool_column(df: pd.DataFrame, column: str, *, default: bool = False) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)
    return coerce_bool_series(df[column], index=df.index, default=default)
