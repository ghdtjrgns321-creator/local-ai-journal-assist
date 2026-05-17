"""Dataset split policies for leak-safe Phase 2 evaluation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

DEFAULT_TRAIN_YEARS = (2022, 2023)
DEFAULT_TEST_YEARS = (2024,)
_DOC_ID_COL = "document_id"
_FISCAL_YEAR_COL = "fiscal_year"
_POSTING_DATE_COL = "posting_date"
_CREATED_BY_COL = "created_by"


@dataclass(frozen=True)
class TemporalHoldoutSplit:
    """Indices for a document-safe temporal holdout split."""

    train_idx: np.ndarray
    test_idx: np.ndarray
    policy: str
    group_column: str
    train_years: tuple[int, ...]
    test_years: tuple[int, ...]


def split_document_temporal_holdout(
    df: pd.DataFrame,
    *,
    group_column: str = _DOC_ID_COL,
    train_years: tuple[int, ...] = DEFAULT_TRAIN_YEARS,
    test_years: tuple[int, ...] = DEFAULT_TEST_YEARS,
) -> TemporalHoldoutSplit:
    """Split a dataframe by fiscal year while preventing document leakage."""
    if group_column not in df.columns:
        raise ValueError(f"{group_column} column is required for temporal splitting")

    years = extract_split_years(df)
    group_years = _group_year_map(df[group_column], years, group_column=group_column)

    train_groups = {group_id for group_id, year in group_years.items() if year in train_years}
    test_groups = {group_id for group_id, year in group_years.items() if year in test_years}
    overlap = train_groups & test_groups
    if overlap:
        raise ValueError(
            f"{group_column} leakage across temporal holdout: "
            f"{sorted(overlap)[:5]}",
        )

    train_mask = df[group_column].isin(train_groups).to_numpy()
    test_mask = df[group_column].isin(test_groups).to_numpy()

    if not train_mask.any():
        raise ValueError(f"no rows found for train_years={train_years}")
    if not test_mask.any():
        raise ValueError(f"no rows found for test_years={test_years}")

    return TemporalHoldoutSplit(
        train_idx=np.flatnonzero(train_mask),
        test_idx=np.flatnonzero(test_mask),
        policy="temporal_holdout",
        group_column=group_column,
        train_years=train_years,
        test_years=test_years,
    )


def split_user_year_holdout(
    df: pd.DataFrame,
    *,
    user_column: str = _CREATED_BY_COL,
    year_column: str = _FISCAL_YEAR_COL,
    train_years: tuple[int, ...] = DEFAULT_TRAIN_YEARS,
    test_years: tuple[int, ...] = DEFAULT_TEST_YEARS,
) -> TemporalHoldoutSplit:
    """Split by train/test years and remove test rows for train-seen users."""
    if user_column not in df.columns:
        raise ValueError(f"{user_column} column is required for user-year holdout")

    years = _extract_years_for_column(df, year_column)
    users = df[user_column].astype(str)

    train_year_mask = years.isin(train_years)
    test_year_mask = years.isin(test_years)

    train_users = set(users[train_year_mask].tolist())
    test_users = set(users[test_year_mask].tolist())
    overlapping_users = train_users & test_users

    train_mask = train_year_mask.to_numpy()
    test_mask = (test_year_mask & ~users.isin(overlapping_users)).to_numpy()

    if not train_mask.any():
        raise ValueError(f"no rows found for train_years={train_years}")
    if not test_mask.any():
        raise ValueError(
            f"no user-disjoint test rows found for test_years={test_years}",
        )

    return TemporalHoldoutSplit(
        train_idx=np.flatnonzero(train_mask),
        test_idx=np.flatnonzero(test_mask),
        policy="user_year_holdout",
        group_column=user_column,
        train_years=train_years,
        test_years=test_years,
    )


def choose_train_validation_split(
    df: pd.DataFrame,
    *,
    group_column: str = _DOC_ID_COL,
    train_years: tuple[int, ...] = DEFAULT_TRAIN_YEARS,
    test_years: tuple[int, ...] = DEFAULT_TEST_YEARS,
    test_size: float = 0.2,
) -> TemporalHoldoutSplit:
    """Pick the safest available split policy automatically.

    Priority:
    1. Temporal holdout when both train/test year buckets exist.
    2. Group holdout when only a single year or missing target years are available.
    """
    if group_column not in df.columns:
        raise ValueError(f"{group_column} column is required for Phase 2 splitting")

    if group_column == _CREATED_BY_COL:
        try:
            return split_user_year_holdout(
                df,
                user_column=group_column,
                train_years=train_years,
                test_years=test_years,
            )
        except ValueError:
            try:
                years = extract_split_years(df)
            except ValueError:
                years = None
            if years is not None:
                available_years = set(years.unique().tolist())
                if set(test_years).issubset(available_years) and available_years & set(train_years):
                    raise

    try:
        years = extract_split_years(df)
    except ValueError:
        years = None

    if years is not None:
        available_years = set(years.unique().tolist())
        if set(test_years).issubset(available_years) and available_years & set(train_years):
            return split_document_temporal_holdout(
                df,
                group_column=group_column,
                train_years=train_years,
                test_years=test_years,
            )

    return split_group_holdout(df, group_column=group_column, test_size=test_size)


def split_group_holdout(
    df: pd.DataFrame,
    *,
    group_column: str = _DOC_ID_COL,
    test_size: float = 0.2,
) -> TemporalHoldoutSplit:
    """Leak-safe fallback split for single-year datasets."""
    if group_column not in df.columns:
        raise ValueError(f"{group_column} column is required for group holdout")

    groups = df[group_column].astype(str).to_numpy()
    unique_groups = np.unique(groups)
    if len(unique_groups) < 2:
        raise ValueError(f"at least 2 unique {group_column} values are required")

    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=42)
    train_idx, test_idx = next(gss.split(df, groups=groups))
    return TemporalHoldoutSplit(
        train_idx=train_idx,
        test_idx=test_idx,
        policy="document_group_holdout",
        group_column=group_column,
        train_years=tuple(),
        test_years=tuple(),
    )


def build_document_group_kfold(
    df: pd.DataFrame,
    *,
    n_splits: int,
    group_column: str = _DOC_ID_COL,
) -> tuple[GroupKFold, np.ndarray]:
    """Build document-level GroupKFold inputs."""
    if group_column not in df.columns:
        raise ValueError(f"{group_column} column is required for GroupKFold evaluation")
    groups = df[group_column].astype(str).to_numpy()
    unique_docs = np.unique(groups)
    if len(unique_docs) < n_splits:
        raise ValueError(
            f"not enough unique document_id values for GroupKFold: "
            f"{len(unique_docs)} < {n_splits}",
        )
    return GroupKFold(n_splits=n_splits), groups


def extract_split_years(df: pd.DataFrame) -> pd.Series:
    """Return per-row fiscal years for split logic."""
    if _FISCAL_YEAR_COL in df.columns:
        years = pd.to_numeric(df[_FISCAL_YEAR_COL], errors="coerce")
    elif _POSTING_DATE_COL in df.columns:
        posting_dates = pd.to_datetime(df[_POSTING_DATE_COL], errors="coerce")
        years = posting_dates.dt.year
    else:
        raise ValueError(
            "Phase 2 splitting requires either fiscal_year or posting_date column",
        )

    if years.isna().any():
        raise ValueError("unable to resolve split year for all rows")
    return years.astype(int)


def _extract_years_for_column(df: pd.DataFrame, year_column: str) -> pd.Series:
    if year_column in df.columns:
        years = pd.to_numeric(df[year_column], errors="coerce")
    elif year_column == _FISCAL_YEAR_COL:
        return extract_split_years(df)
    else:
        raise ValueError(f"{year_column} column is required for user-year holdout")

    if years.isna().any():
        raise ValueError("unable to resolve split year for all rows")
    return years.astype(int)


def _group_year_map(group_ids: pd.Series, years: pd.Series, *, group_column: str) -> dict[str, int]:
    pairs = pd.DataFrame({
        group_column: group_ids.astype(str),
        "split_year": years.astype(int),
    })
    grouped = pairs.groupby(group_column, dropna=False)["split_year"].nunique()
    inconsistent = grouped[grouped > 1]
    if not inconsistent.empty:
        raise ValueError(
            f"{group_column} spans multiple fiscal years: "
            f"{inconsistent.index.tolist()[:5]}",
        )
    return (
        pairs.drop_duplicates(subset=[group_column])
        .set_index(group_column)["split_year"]
        .to_dict()
    )
