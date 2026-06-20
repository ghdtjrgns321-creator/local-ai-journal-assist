from __future__ import annotations

import pandas as pd

from src.detection.fraud_layer import FraudLayer


def test_l1_06_review_pair_is_excluded_from_l106_score() -> None:
    df = pd.DataFrame({
        "debit_amount": [1.0, 1.0],
        "credit_amount": [0.0, 0.0],
        "created_by": ["U1", "U1"],
        "business_process": ["R2R", "P2P"],
        "user_persona": ["senior_accountant", "senior_accountant"],
        "exceeds_threshold": [True, True],
    })
    layer = FraudLayer()
    result = layer.detect(df)
    l106 = next(flag for flag in result.rule_flags if flag.rule_id == "L1-06")
    assert l106.detail == "immediate=0, review=0"
    assert l106.flagged_count == 0
    assert result.details["L1-06"].eq(0.0).all()
    assert result.metadata["rule_breakdowns"]["L1-06"]["review_rows"] == 0
    assert result.metadata["rule_breakdowns"]["L1-06"]["yellow_rows"] == 2
    assert result.metadata["row_annotations"]["L1-06"][0]["signal_class"] == "yellow"


def test_l1_06_review_is_not_promoted_by_self_approval() -> None:
    df = pd.DataFrame({
        "debit_amount": [1.0, 1.0],
        "credit_amount": [0.0, 0.0],
        "created_by": ["U1", "U1"],
        "approved_by": ["U1", "U1"],
        "business_process": ["R2R", "P2P"],
        "user_persona": ["senior_accountant", "senior_accountant"],
        "exceeds_threshold": [True, True],
    })
    layer = FraudLayer()
    result = layer.detect(df)
    l106 = next(flag for flag in result.rule_flags if flag.rule_id == "L1-06")
    assert l106.detail == "immediate=0, review=0"
    assert l106.flagged_count == 0
    assert result.details["L1-06"].eq(0.0).all()
    assert result.metadata["rule_breakdowns"]["L1-06"]["corroborated_review_rows"] == 0
    assert result.metadata["rule_breakdowns"]["L1-06"]["yellow_rows"] == 2
