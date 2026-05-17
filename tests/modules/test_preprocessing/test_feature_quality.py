from __future__ import annotations

import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from src.preprocessing.constants import (
    LEAKAGE_DENY_COLUMNS,
    LEAKAGE_DENY_COLUMNS_V6_BASELINE,
    LEAKAGE_DENY_COLUMNS_V7_DERIVED,
    LEAKAGE_DENY_RULES,
)
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.feature_quality import (
    UNKNOWN_PERSONA,
    apply_feature_quality_policy,
    normalize_user_persona_series,
)

EXPECTED_V4_TOP5_LEAKAGE_DENY_RULES = (
    "rule_L3-02",
    "rule_L3-09",
    "rule_L1-03",
    "rule_L2-03",
    "rule_L1-05",
)


def _assert_residual_auroc_below_099(
    df: pd.DataFrame,
    target: pd.Series,
    *,
    threshold: float = 0.99,
) -> None:
    for col in df.columns:
        series = df[col]
        if series.nunique(dropna=True) <= 1:
            continue
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            encoded = pd.to_numeric(series, errors="coerce")
        else:
            encoded = pd.Series(pd.factorize(series.astype("string"), sort=True)[0], index=df.index)
        valid = encoded.notna() & target.notna()
        if valid.sum() < 2 or target.loc[valid].nunique() < 2:
            continue
        auroc = roc_auc_score(target.loc[valid].astype(int), encoded.loc[valid])
        auroc = max(float(auroc), 1.0 - float(auroc))
        if auroc >= threshold:
            raise ValueError(
                f"Residual leakage candidate '{col}' has single-column AUROC "
                f"{auroc:.4f}. Add this column to LEAKAGE_DENY_COLUMNS deny-list."
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


def test_leakage_deny_columns_dropped() -> None:
    df = pd.DataFrame({col: [1] for col in LEAKAGE_DENY_COLUMNS})
    df["feature_probe"] = [100]
    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)
    assert set(cleaned.columns).isdisjoint(LEAKAGE_DENY_COLUMNS)
    assert "feature_probe" in cleaned.columns


def test_leakage_deny_rules_drop_top5_and_keep_remaining_rule_inputs() -> None:
    remaining_rule_columns = [
        "rule_L1-01",
        "rule_L1-02",
        "rule_L1-04",
        "rule_L1-06",
        "rule_L1-07",
        "rule_L1-08",
        "rule_L1-09",
        "rule_L2-01",
        "rule_L2-02",
        "rule_L2-04",
        "rule_L2-05",
        "rule_L3-01",
        "rule_L3-03",
        "rule_L3-04",
        "rule_L3-05",
        "rule_L3-06",
        "rule_L3-07",
        "rule_L3-08",
        "rule_L4-01",
        "rule_L4-02",
        "rule_L4-03",
        "rule_L4-04",
    ]
    assert len(remaining_rule_columns) == 22
    df = pd.DataFrame({
        "debit_amount": [100, 200],
        **{col: [1, 0] for col in LEAKAGE_DENY_RULES},
        **{col: [0, 1] for col in remaining_rule_columns},
    })

    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)

    assert set(cleaned.columns).isdisjoint(LEAKAGE_DENY_RULES)
    assert set(remaining_rule_columns).issubset(cleaned.columns)


def test_v4_top5_leakage_deny_rules_are_locked_and_dropped() -> None:
    assert LEAKAGE_DENY_RULES == frozenset(EXPECTED_V4_TOP5_LEAKAGE_DENY_RULES)

    df = pd.DataFrame({
        **{col: [1, 0] for col in EXPECTED_V4_TOP5_LEAKAGE_DENY_RULES},
        "rule_L1-09": [1, 0],
        "rule_L2-02": [0, 1],
        "feature_probe": [100, 200],
    })

    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)

    assert set(cleaned.columns).isdisjoint(EXPECTED_V4_TOP5_LEAKAGE_DENY_RULES)
    assert {"rule_L1-09", "rule_L2-02", "feature_probe"}.issubset(cleaned.columns)


def test_v6_baseline_leakage_deny_columns_are_locked_and_dropped() -> None:
    expected_v6_columns = frozenset({
        "amount_magnitude",
        "amount_zscore",
        "credit_amount",
        "debit_amount",
        "document_approval_amount",
        "invoice_amount",
        "local_amount",
        "near_threshold_amount",
        "supply_amount",
        "tax_amount",
        "approval_after_30d",
        "approval_before_posting",
        "approval_date_null",
        "approval_excess_amount",
        "approval_lag_abs",
        "approval_lag_days",
        "approval_level",
        "approval_limit_exceeded_independent",
        "exceeds_threshold",
        "approval_contract_gap",
        "approval_matrix_gap",
        "days_backdated",
        "first_digit",
        "has_revenue_line",
        "is_intercompany",
        "is_round_number",
        "is_suspense_account",
        "master_counterparty_intercompany",
        "near_threshold_ratio_to_limit",
        "self_approval",
    })
    assert LEAKAGE_DENY_COLUMNS_V6_BASELINE == expected_v6_columns

    df = pd.DataFrame({
        **{col: [1, 0] for col in expected_v6_columns},
        "user_persona": ["manager", "controller"],
    })

    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)

    assert set(cleaned.columns).isdisjoint(expected_v6_columns)
    assert "user_persona" in cleaned.columns


def test_v7_derived_leakage_deny_columns_are_locked_and_dropped() -> None:
    expected_v7_columns = frozenset({
        "approver_can_approve_je",
        "approver_limit_amount",
        "line_number",
        "near_threshold_gap_amount",
        "near_threshold_gap_ratio",
        "near_threshold_limit_amount",
    })
    assert LEAKAGE_DENY_COLUMNS_V7_DERIVED == expected_v7_columns

    df = pd.DataFrame({
        **{col: [1, 0] for col in expected_v7_columns},
        "operating_feature": [100, 200],
    })

    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)

    assert set(cleaned.columns).isdisjoint(expected_v7_columns)
    assert "operating_feature" in cleaned.columns


def test_residual_auroc_below_099() -> None:
    df = pd.DataFrame(
        {
            "is_fraud": [0, 0, 0, 1, 1, 1],
            "residual_probe": [0, 0, 0, 1, 1, 1],
            "debit_amount": [100, 125, 90, 110, 105, 95],
        }
    )
    target = df["is_fraud"]
    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)

    with pytest.raises(ValueError, match="LEAKAGE_DENY_COLUMNS deny-list"):
        _assert_residual_auroc_below_099(cleaned, target)
