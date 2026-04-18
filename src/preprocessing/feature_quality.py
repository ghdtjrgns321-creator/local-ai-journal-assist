"""Feature quality policy shared across training and inference paths.

Why: DataSynth optional fields can be sparse or unstable enough to hurt
     Phase 2 model training. This module centralizes lightweight, repeatable
     policy decisions:
     - normalize user_persona before any model consumes it
     - exclude sparse feature families from supervised training by default
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import get_close_matches
import re

import pandas as pd

from src.preprocessing.constants import LABEL_COLUMNS
from src.preprocessing.feature_groups import FeatureGroups

USER_PERSONA_COLUMN = "user_persona"
UNKNOWN_PERSONA = "unknown_persona"
CANONICAL_USER_PERSONAS = (
    "automated_system",
    "junior_accountant",
    "senior_accountant",
    "controller",
    "manager",
)
_PERSONA_ALIAS_MAP = {
    "automatedsystem": "automated_system",
    "automated_system": "automated_system",
    "automated_systems": "automated_system",
    "automatic_system": "automated_system",
    "auto_system": "automated_system",
    "utomated_system": "automated_system",
    "junioraccountant": "junior_accountant",
    "junior_accountant": "junior_accountant",
    "jr_accountant": "junior_accountant",
    "senioraccountant": "senior_accountant",
    "senior_accountant": "senior_accountant",
    "sr_accountant": "senior_accountant",
    "senior_accoutant": "senior_accountant",
    "senor_accountant": "senior_accountant",
    "controller": "controller",
    "controlelr": "controller",
    "controler": "controller",
    "manager": "manager",
    "maanger": "manager",
    "manger": "manager",
}
_TOKEN_HINTS = (
    ("automated", "automated_system"),
    ("system", "automated_system"),
    ("junior", "junior_accountant"),
    ("senior", "senior_accountant"),
    ("controller", "controller"),
    ("control", "controller"),
    ("manager", "manager"),
)
_SPARSE_FEATURE_THRESHOLDS = {
    "cost_center": 0.30,
    "tax_code": 0.20,
    "tax_amount": 0.20,
    "trading_partner": 0.50,
    "auxiliary_account_number": 0.50,
    "auxiliary_account_label": 0.50,
}
FEATURE_FAMILIES = {
    "persona": ("user_persona",),
    "cost_center": ("cost_center",),
    "tax": ("tax_code", "tax_amount"),
    "trading_partner": ("trading_partner",),
    "auxiliary": ("auxiliary_account_number", "auxiliary_account_label"),
}


@dataclass
class FeatureQualityReport:
    normalized_persona: bool = False
    unknown_persona_count: int = 0
    sparse_dropped_columns: list[str] = field(default_factory=list)
    sparse_column_coverage: dict[str, float] = field(default_factory=dict)
    family_statuses: dict[str, dict] = field(default_factory=dict)
    ablation_plan: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_user_persona_series(series: pd.Series) -> tuple[pd.Series, int]:
    """Normalize user_persona variants into canonical values."""
    normalized = series.map(_normalize_user_persona_value)
    unknown_mask = normalized == UNKNOWN_PERSONA
    return normalized, int(unknown_mask.sum())


def apply_feature_quality_policy(
    df: pd.DataFrame,
    groups: FeatureGroups | None = None,
    *,
    for_training: bool,
) -> tuple[pd.DataFrame, FeatureGroups | None, FeatureQualityReport]:
    """Apply persona normalization plus training-only sparse feature gating."""
    cleaned = _drop_label_columns(df.copy())
    report = FeatureQualityReport()

    if USER_PERSONA_COLUMN in cleaned.columns:
        normalized, unknown_count = normalize_user_persona_series(cleaned[USER_PERSONA_COLUMN])
        cleaned[USER_PERSONA_COLUMN] = normalized
        report.normalized_persona = True
        report.unknown_persona_count = unknown_count

    adjusted_groups = _copy_groups(groups) if groups is not None else None
    if for_training and adjusted_groups is not None:
        sparse_coverages = {
            col: _coverage(cleaned, col)
            for col in _SPARSE_FEATURE_THRESHOLDS
            if col in cleaned.columns
        }
        dropped = _collect_sparse_feature_drops(cleaned, adjusted_groups)
        if dropped:
            cleaned = cleaned.drop(columns=dropped, errors="ignore")
            report.sparse_dropped_columns.extend(sorted(dropped))
            for col in dropped:
                report.sparse_column_coverage[col] = sparse_coverages.get(col, 0.0)

    report.family_statuses = summarize_feature_families(cleaned, report.sparse_dropped_columns)
    report.ablation_plan = build_feature_family_ablation_plan(cleaned, report.family_statuses)
    return cleaned, adjusted_groups, report


def summarize_feature_families(
    df: pd.DataFrame,
    sparse_dropped_columns: list[str] | None = None,
) -> dict[str, dict]:
    dropped_set = set(sparse_dropped_columns or [])
    statuses: dict[str, dict] = {}
    for family, columns in FEATURE_FAMILIES.items():
        available = [col for col in columns if col in df.columns]
        dropped = [col for col in columns if col in dropped_set]
        statuses[family] = {
            "available_columns": available,
            "dropped_columns": dropped,
            "active": bool(available) and not dropped,
        }
    return statuses


def build_feature_family_ablation_plan(
    df: pd.DataFrame,
    family_statuses: dict[str, dict] | None = None,
) -> list[dict]:
    statuses = family_statuses or summarize_feature_families(df)
    active_families = [
        family
        for family, status in statuses.items()
        if status.get("available_columns") and not status.get("dropped_columns")
    ]
    plan = [
        {
            "variant": "baseline_core",
            "include_families": [],
            "description": "Core stable features only",
        }
    ]
    for family in active_families:
        plan.append(
            {
                "variant": f"plus_{family}",
                "include_families": [family],
                "description": f"Baseline + {family} family",
            }
        )
    if active_families:
        plan.append(
            {
                "variant": "full_active",
                "include_families": active_families,
                "description": "All currently active optional families",
            }
        )
    return plan


def _normalize_user_persona_value(value):
    if pd.isna(value):
        return value
    text = str(value).strip().lower()
    if not text:
        return pd.NA
    normalized = re.sub(r"[^a-z]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    if normalized in _PERSONA_ALIAS_MAP:
        return _PERSONA_ALIAS_MAP[normalized]
    if normalized.replace("_", "") in _PERSONA_ALIAS_MAP:
        return _PERSONA_ALIAS_MAP[normalized.replace("_", "")]

    for token, canonical in _TOKEN_HINTS:
        if token in normalized:
            return canonical

    matches = get_close_matches(normalized, CANONICAL_USER_PERSONAS, n=1, cutoff=0.80)
    if matches:
        return matches[0]
    return UNKNOWN_PERSONA


def _drop_label_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols_to_drop = [col for col in df.columns if col.lower() in LABEL_COLUMNS]
    if not cols_to_drop:
        return df
    return df.drop(columns=cols_to_drop, errors="ignore")


def _copy_groups(groups: FeatureGroups | None) -> FeatureGroups | None:
    if groups is None:
        return None
    return FeatureGroups(
        numeric=list(groups.numeric),
        categorical_high=list(groups.categorical_high),
        categorical_low=list(groups.categorical_low),
        boolean=list(groups.boolean),
        ordinal=list(groups.ordinal),
        excluded=list(groups.excluded),
    )


def _collect_sparse_feature_drops(df: pd.DataFrame, groups: FeatureGroups) -> set[str]:
    drops: set[str] = set()
    for col, min_coverage in _SPARSE_FEATURE_THRESHOLDS.items():
        if col not in df.columns:
            continue
        if _coverage(df, col) >= min_coverage:
            continue
        _remove_column_from_groups(groups, col)
        drops.add(col)
    return drops


def _remove_column_from_groups(groups: FeatureGroups, column: str) -> None:
    for group_name in ("numeric", "categorical_high", "categorical_low", "boolean", "ordinal"):
        group = getattr(groups, group_name)
        if column in group:
            group.remove(column)
    if column not in groups.excluded:
        groups.excluded.append(column)


def _coverage(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns or len(df) == 0:
        return 0.0
    series = df[column]
    filled = series.notna()
    if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
        text = series.astype("string")
        filled = filled & text.str.strip().ne("")
    return float(filled.mean())
