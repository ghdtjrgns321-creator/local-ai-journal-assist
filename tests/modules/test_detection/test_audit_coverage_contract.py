from __future__ import annotations

import pandas as pd

from src.detection.anomaly_layer import AnomalyDetector
from src.detection.fraud_layer import FraudLayer


def test_fraud_layer_marks_missing_feature_rule_as_skipped() -> None:
    df = pd.DataFrame(
        {
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-01-01"]),
        }
    )
    result = FraudLayer().detect(df)
    assert "L4-01" in result.metadata.get("skipped_rules", [])
    assert any(
        issue.get("rule_id") == "L4-01" for issue in result.metadata.get("coverage_issues", [])
    )


def test_anomaly_layer_marks_missing_feature_rule_as_skipped() -> None:
    df = pd.DataFrame(
        {
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-01-01"]),
            "document_id": ["D1"],
            "gl_account": ["1000"],
        }
    )
    result = AnomalyDetector().detect(df)
    assert "L3-04" in result.metadata.get("skipped_rules", [])
    assert any(
        issue.get("rule_id") == "L3-04" for issue in result.metadata.get("coverage_issues", [])
    )
