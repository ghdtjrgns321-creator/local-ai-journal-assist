from __future__ import annotations

import pandas as pd
import pytest

from src.eda.profiler import profile_dataframe
from src.preprocessing.phase2_matrix import Phase2AutoencoderMatrixBuilder
from src.preprocessing.phase2_plan import build_phase2_preprocessing_plan


def _decisions_by_column(plan):
    return {decision.column: decision for decision in plan.decisions}


def test_phase2_preprocessing_plan_excludes_leakage_columns():
    df = pd.DataFrame(
        {
            "amount": [100.0, 200.0, 300.0],
            "risk_level": ["High", "Low", "Medium"],
            "rule_hit_count": [2, 0, 1],
            "model_score": [0.9, 0.1, 0.4],
            "export_status": ["ready", "ready", "blocked"],
            "dashboard_url": ["/a", "/b", "/c"],
            "is_fraud": [1, 0, 0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    assert decisions["amount"].action == "include"
    assert decisions["risk_level"].reason_code == "leakage_risk"
    assert decisions["rule_hit_count"].reason_code == "leakage_rule"
    assert decisions["model_score"].reason_code == "leakage_score"
    assert decisions["export_status"].reason_code == "leakage_export"
    assert decisions["dashboard_url"].reason_code == "leakage_dashboard"
    assert decisions["is_fraud"].reason_code == "leakage_label"
    assert all(
        decisions[column].action == "exclude"
        for column in (
            "risk_level",
            "rule_hit_count",
            "model_score",
            "export_status",
            "dashboard_url",
            "is_fraud",
        )
    )


def test_phase2_preprocessing_plan_excludes_v6_baseline_deny_columns():
    df = pd.DataFrame(
        {
            "amount_magnitude": [1.0, 2.0, 3.0],
            "approval_lag_abs": [0, 5, 10],
            "is_suspense_account": [False, True, False],
            "operating_feature": [10.0, 11.0, 12.0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    for column in ("amount_magnitude", "approval_lag_abs", "is_suspense_account"):
        assert decisions[column].action == "exclude"
        assert decisions[column].reason_code == "leakage_deny_column"
    assert decisions["operating_feature"].action == "include"


def test_phase2_preprocessing_plan_excludes_v7_derived_deny_columns():
    df = pd.DataFrame(
        {
            "near_threshold_gap_amount": [1.0, 2.0, 3.0],
            "approver_limit_amount": [10.0, 20.0, 30.0],
            "line_number": [1, 2, 3],
            "operating_feature": [10.0, 11.0, 12.0],
        }
    )

    plan = build_phase2_preprocessing_plan(profile_dataframe(df))
    decisions = _decisions_by_column(plan)

    for column in ("near_threshold_gap_amount", "approver_limit_amount", "line_number"):
        assert decisions[column].action == "exclude"
        assert decisions[column].reason_code == "leakage_deny_column"
    assert decisions["operating_feature"].action == "include"


def test_phase2_preprocessing_plan_column_decision_snapshot():
    df = pd.DataFrame(
        {
            "customer_id": ["c1", "c2", "c3", "c4"],
            "posting_date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
            ),
            "is_anomaly": [0, 1, 0, 0],
            "vendor_name": ["A", "B", "C", "D"],
            "amount": [100.0, 200.0, 300.0, 400.0],
            "approved": [True, False, True, True],
            "user_persona": ["manager", "controller", "manager", "junior_accountant"],
        }
    )

    plan = build_phase2_preprocessing_plan(
        profile_dataframe(df),
        high_card_threshold=3,
    )
    snapshot = {
        decision.column: {
            "role": decision.role,
            "action": decision.action,
            "reason_code": decision.reason_code,
        }
        for decision in plan.decisions
    }

    assert snapshot == {
        "customer_id": {
            "role": "identifier",
            "action": "exclude",
            "reason_code": "identifier",
        },
        "posting_date": {
            "role": "datetime",
            "action": "exclude",
            "reason_code": "datetime_raw",
        },
        "is_anomaly": {
            "role": "label",
            "action": "exclude",
            "reason_code": "leakage_label",
        },
        "vendor_name": {
            "role": "categorical_high",
            "action": "include",
            "reason_code": "high_cardinality",
        },
        "amount": {
            "role": "numeric",
            "action": "include",
            "reason_code": "numeric",
        },
        "approved": {
            "role": "boolean",
            "action": "include",
            "reason_code": "boolean",
        },
        "user_persona": {
            "role": "categorical_low",
            "action": "include",
            "reason_code": "domain_low_card",
        },
    }


def test_phase2_matrix_rejects_standalone_f_manual():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 200.0, 300.0],
            "f_manual": [True, False, True],
        }
    )
    plan = build_phase2_preprocessing_plan(profile_dataframe(df))

    with pytest.raises(ValueError, match="f_manual"):
        Phase2AutoencoderMatrixBuilder(plan).fit(df)


def test_phase2_matrix_allows_f_manual_interaction_feature():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [100.0, 200.0, 300.0],
            "f_manual_x_amount_high": [True, False, True],
        }
    )
    plan = build_phase2_preprocessing_plan(profile_dataframe(df))

    matrix = Phase2AutoencoderMatrixBuilder(plan).fit_transform(df)

    assert "f_manual_x_amount_high" in matrix.columns
