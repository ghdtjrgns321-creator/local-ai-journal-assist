from __future__ import annotations

import pandas as pd
import pytest

from src.preprocessing.split_strategy import (
    build_document_group_kfold,
    choose_train_validation_split,
    extract_split_years,
    split_document_temporal_holdout,
    split_user_year_holdout,
)


@pytest.fixture()
def temporal_df() -> pd.DataFrame:
    rows: list[dict] = []
    for year in (2022, 2023, 2024):
        for doc_idx in range(3):
            for line_idx in range(2):
                rows.append({
                    "document_id": f"D{year}_{doc_idx}",
                    "created_by": f"user_{doc_idx}",
                    "fiscal_year": year,
                    "posting_date": f"{year}-01-{line_idx + 1:02d}",
                    "amount": 100 + doc_idx,
                })
    rows.append({
        "document_id": "D2024_new_user",
        "created_by": "new_2024_user",
        "fiscal_year": 2024,
        "posting_date": "2024-02-01",
        "amount": 500,
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


def test_split_user_year_holdout_removes_train_seen_users_from_test(temporal_df):
    split = split_user_year_holdout(temporal_df)
    train = temporal_df.iloc[split.train_idx]
    test = temporal_df.iloc[split.test_idx]

    assert set(train["created_by"]) & set(test["created_by"]) == set()
    assert (train["fiscal_year"] == 2024).sum() == 0
    assert (pd.to_datetime(train["posting_date"]).dt.year == 2024).sum() == 0
    assert set(test["created_by"]) == {"new_2024_user"}


def test_choose_train_validation_split_prefers_user_year_holdout(temporal_df):
    split = choose_train_validation_split(temporal_df, group_column="created_by")

    assert split.policy == "user_year_holdout"
    assert set(temporal_df.iloc[split.train_idx]["created_by"]) & set(
        temporal_df.iloc[split.test_idx]["created_by"]
    ) == set()


def test_choose_train_validation_split_requires_document_id(temporal_df):
    without_document_id = temporal_df.drop(columns=["document_id"])

    with pytest.raises(ValueError, match="document_id column is required"):
        choose_train_validation_split(without_document_id)


def test_choose_train_validation_split_keeps_documents_disjoint(temporal_df):
    split = choose_train_validation_split(temporal_df)

    train_docs = set(temporal_df.iloc[split.train_idx]["document_id"])
    test_docs = set(temporal_df.iloc[split.test_idx]["document_id"])
    assert split.policy == "temporal_holdout"
    assert train_docs.isdisjoint(test_docs)


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
