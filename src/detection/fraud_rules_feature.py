"""Feature-based fraud rules: L4-01, L2-01, L1-04, L3-02."""

from __future__ import annotations

import pandas as pd

from config.settings import get_audit_rules


def _check_features(df: pd.DataFrame, required: list[str]) -> list[str]:
    """Return missing feature columns."""
    return [c for c in required if c not in df.columns]


def b01_revenue_manipulation(
    df: pd.DataFrame,
    zscore_threshold: float = 3.0,
) -> pd.Series:
    """L4-01 revenue account outlier: revenue account and high amount z-score."""
    missing = _check_features(df, ["is_revenue_account", "amount_zscore"])
    if missing:
        return pd.Series(False, index=df.index)
    return df["is_revenue_account"].fillna(False) & (
        df["amount_zscore"].fillna(0.0) > zscore_threshold
    )


def b02_near_threshold(df: pd.DataFrame) -> pd.Series:
    """L2-01 just below approval threshold."""
    if "is_near_threshold" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["is_near_threshold"].fillna(False)


def b03_exceeds_threshold(df: pd.DataFrame) -> pd.Series:
    """L1-04 approval limit exceeded."""
    if "exceeds_threshold" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["exceeds_threshold"].fillna(False)


def b08_manual_override(df: pd.DataFrame) -> pd.Series:
    """L3-02 manual entry: source/manual feature only."""
    if "is_manual_je" in df.columns:
        return df["is_manual_je"].fillna(False).astype(bool)

    if "source" not in df.columns:
        return pd.Series(False, index=df.index)

    rules = get_audit_rules()
    manual_sources = {
        str(v).strip().lower()
        for v in rules.get("patterns", {}).get("manual_source_codes", ["manual", "adjustment"])
    }
    if not manual_sources:
        return pd.Series(False, index=df.index)
    return df["source"].fillna("").astype(str).str.strip().str.lower().isin(manual_sources)
