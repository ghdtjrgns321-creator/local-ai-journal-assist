from __future__ import annotations

import pandas as pd

from config.settings import AuditSettings
from src.detection.anomaly_layer import AnomalyDetector
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.fraud_layer import FraudLayer
from src.detection.graph_detector import GraphDetector


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
    assert any(issue.get("rule_id") == "L4-01" for issue in result.metadata.get("coverage_issues", []))


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
    assert any(issue.get("rule_id") == "L3-04" for issue in result.metadata.get("coverage_issues", []))


def test_duplicate_detector_marks_missing_line_text_as_skipped() -> None:
    df = pd.DataFrame(
        {
            "gl_account": [1000, 1000],
            "debit_amount": [100.0, 100.0],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
        }
    )
    result = DuplicateDetector().detect(df)
    assert "L2-03b" in result.metadata.get("skipped_rules", [])
    assert any(issue.get("rule_id") == "L2-03b" for issue in result.metadata.get("coverage_issues", []))


def test_duplicate_detector_processes_oversized_group_without_skip() -> None:
    settings = AuditSettings(duplicate_max_group_size=2)
    df = pd.DataFrame(
        {
            "gl_account": [1000] * 5,
            "debit_amount": [100.0] * 5,
            "credit_amount": [0.0] * 5,
            "posting_date": pd.to_datetime(["2025-01-01"] * 5),
            "line_text": ["test"] * 5,
        }
    )
    result = DuplicateDetector(settings).detect(df)
    coverage = result.metadata.get("coverage_issues", [])
    assert "L2-03b" not in result.metadata.get("skipped_rules", [])
    assert not any(issue.get("kind") == "oversized_group_skipped" for issue in coverage)


def test_graph_detector_exposes_gr01_coverage_issue() -> None:
    settings = AuditSettings(graph_gr01_max_edges=1)
    df = pd.DataFrame(
        {
            "document_id": ["D1", "D2", "D3"],
            "company_code": ["C1", "C2", "C3"],
            "trading_partner": ["C2", "C3", "C1"],
            "gl_account": ["4500", "4500", "4500"],
            "credit_amount": [20_000_000, 20_000_001, 20_000_002],
            "debit_amount": [0.0, 0.0, 0.0],
            "is_intercompany": [True, True, True],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
        }
    )
    result = GraphDetector(settings).detect(df)
    coverage = result.metadata.get("coverage_issues", [])
    assert any(issue.get("rule_id") == "GR01" for issue in coverage)
