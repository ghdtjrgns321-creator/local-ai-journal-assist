"""Repair text corrupted by legacy encoding mis-detection."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

DEFAULT_TEXT_COLUMNS = ("line_text", "header_text", "description")


def repair_dataframe_text_mojibake(
    df: pd.DataFrame,
    columns: Iterable[str] = DEFAULT_TEXT_COLUMNS,
) -> pd.DataFrame:
    """Repair Korean UTF-8 text previously decoded as ``ptcp154``.

    The ingest reader now prefers strict UTF-8, but existing session/DB/feature
    caches can still contain the old Cyrillic-looking strings. This function is
    conservative: it only changes text that looks like Cyrillic/Greek mojibake
    and whose ptcp154 -> UTF-8 roundtrip produces Hangul.
    """

    target_columns = [column for column in columns if column in df.columns]
    if not target_columns:
        return df

    out: pd.DataFrame | None = None
    for column in target_columns:
        series = df[column]
        if not _series_may_contain_mojibake(series):
            continue
        repaired = series.map(_repair_text_value)
        if repaired.equals(series):
            continue
        if out is None:
            out = df.copy()
        out[column] = repaired

    if out is None:
        return df
    out.attrs.update(df.attrs)
    return out


def _repair_text_value(value: object) -> object:
    if value is None:
        return value
    if not isinstance(value, str):
        return value
    if not _looks_like_ptcp154_mojibake(value):
        return value
    try:
        candidate = value.encode("ptcp154").decode("utf-8")
    except UnicodeError:
        return value
    if _hangul_count(candidate) == 0:
        return value
    return candidate


def _series_may_contain_mojibake(series: pd.Series) -> bool:
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return False
    return any(_looks_like_ptcp154_mojibake(value) for value in sample)


def _looks_like_ptcp154_mojibake(value: str) -> bool:
    if len(value.strip()) < 4:
        return False
    if _hangul_count(value) > 0:
        return False
    return _cyrillic_or_greek_count(value) >= 2


def _hangul_count(value: str) -> int:
    return sum("\uac00" <= char <= "\ud7a3" for char in value)


def _cyrillic_or_greek_count(value: str) -> int:
    return sum(("\u0400" <= char <= "\u04ff") or ("\u0370" <= char <= "\u03ff") for char in value)
