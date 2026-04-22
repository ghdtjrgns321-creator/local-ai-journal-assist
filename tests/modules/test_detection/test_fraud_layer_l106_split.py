from __future__ import annotations

import pandas as pd

from src.detection.fraud_layer import FraudLayer


def test_l1_06_rule_flag_detail_and_score_band() -> None:
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
    assert l106.detail == "immediate=0, review=2"
    assert result.details["L1-06"].eq(0.4).all()
    assert result.metadata["rule_breakdowns"]["L1-06"]["review_rows"] == 2


def test_l1_06_review_is_promoted_by_cross_rule_signal() -> None:
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
    assert l106.detail == "immediate=2, review=0"
    assert result.details["L1-06"].eq(0.8).all()
    assert result.metadata["rule_breakdowns"]["L1-06"]["corroborated_review_rows"] == 2
