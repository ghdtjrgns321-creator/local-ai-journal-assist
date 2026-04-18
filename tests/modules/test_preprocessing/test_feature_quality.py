from __future__ import annotations

import pandas as pd

from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.feature_quality import (
    UNKNOWN_PERSONA,
    apply_feature_quality_policy,
    normalize_user_persona_series,
)


def test_normalize_user_persona_series_maps_typos_to_canonical_values() -> None:
    series = pd.Series([
        "senior_accoutant",
        "utomated_system",
        "maanger",
        "controller",
        None,
        "mystery_role",
    ])

    normalized, unknown_count = normalize_user_persona_series(series)

    assert normalized.tolist()[:4] == [
        "senior_accountant",
        "automated_system",
        "manager",
        "controller",
    ]
    assert pd.isna(normalized.iloc[4])
    assert normalized.iloc[5] == UNKNOWN_PERSONA
    assert unknown_count == 1


def test_apply_feature_quality_policy_drops_sparse_training_columns() -> None:
    df = pd.DataFrame({
        "f1": [1.0, 2.0, 3.0, 4.0],
        "user_persona": [
            "senor_accountant",
            "manager",
            "utomated_system",
            "controller",
        ],
        "cost_center": [None, None, None, "CC100"],
        "tax_code": [None, None, None, None],
        "auxiliary_account_number": ["V-1", None, None, None],
    })
    groups = FeatureGroups(
        numeric=["f1"],
        categorical_low=[
            "user_persona",
            "cost_center",
            "tax_code",
            "auxiliary_account_number",
        ],
    )

    cleaned, adjusted_groups, report = apply_feature_quality_policy(
        df,
        groups,
        for_training=True,
    )

    assert "cost_center" not in cleaned.columns
    assert "tax_code" not in cleaned.columns
    assert "auxiliary_account_number" not in cleaned.columns
    assert cleaned["user_persona"].tolist() == [
        "senior_accountant",
        "manager",
        "automated_system",
        "controller",
    ]
    assert adjusted_groups is not None
    assert adjusted_groups.categorical_low == ["user_persona"]
    assert report.sparse_dropped_columns == [
        "auxiliary_account_number",
        "cost_center",
        "tax_code",
    ]
    assert report.family_statuses["persona"]["active"] is True
    assert report.family_statuses["cost_center"]["active"] is False
    assert report.ablation_plan[0]["variant"] == "baseline_core"
    assert report.ablation_plan[-1]["variant"] == "full_active"
