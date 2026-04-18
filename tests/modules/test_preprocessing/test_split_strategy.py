from __future__ import annotations

import pandas as pd
import pytest

from src.preprocessing.split_strategy import (
    build_document_group_kfold,
    choose_train_validation_split,
    extract_split_years,
    split_document_temporal_holdout,
)


@pytest.fixture()
def temporal_df() -> pd.DataFrame:
    rows: list[dict] = []
    for year in (2022, 2023, 2024):
        for doc_idx in range(3):
            for line_idx in range(2):
                rows.append({
                    "document_id": f"D{year}_{doc_idx}",
                    "fiscal_year": year,
                    "posting_date": f"{year}-01-{line_idx + 1:02d}",
                    "amount": 100 + doc_idx,
                })
    return pd.DataFrame(rows)


def test_extract_split_years_prefers_fiscal_year(temporal_df):
    years = extract_split_years(temporal_df)
    assert years.iloc[0] == 2022
    assert years.iloc[-1] == 2024


def test_split_document_temporal_holdout_uses_expected_years(temporal_df):
    split = split_document_temporal_holdout(temporal_df)
    train_years = set(temporal_df.iloc[split.train_idx]["fiscal_year"].unique())
    test_years = set(temporal_df.iloc[split.test_idx]["fiscal_year"].unique())

    assert train_years == {2022, 2023}
    assert test_years == {2024}
    assert not (
        set(temporal_df.iloc[split.train_idx]["document_id"])
        & set(temporal_df.iloc[split.test_idx]["document_id"])
    )


def test_split_document_temporal_holdout_rejects_cross_year_document(temporal_df):
    temporal_df.loc[0, "document_id"] = "D_cross"
    temporal_df.loc[len(temporal_df) - 1, "document_id"] = "D_cross"

    with pytest.raises(ValueError, match="document_id spans multiple fiscal years"):
        split_document_temporal_holdout(temporal_df)


def test_build_document_group_kfold_returns_groups(temporal_df):
    gkf, groups = build_document_group_kfold(temporal_df, n_splits=3)
    assert gkf.n_splits == 3
    assert len(groups) == len(temporal_df)


def test_choose_train_validation_split_falls_back_for_single_year(temporal_df):
    single_year = temporal_df.copy()
    single_year["fiscal_year"] = 2026
    single_year["posting_date"] = pd.to_datetime("2026-01-01")

    split = choose_train_validation_split(single_year)

    assert split.policy == "document_group_holdout"
    assert len(split.train_idx) > 0
    assert len(split.test_idx) > 0
    assert not (
        set(single_year.iloc[split.train_idx]["document_id"])
        & set(single_year.iloc[split.test_idx]["document_id"])
    )
