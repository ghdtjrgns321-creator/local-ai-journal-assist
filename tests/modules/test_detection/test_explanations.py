from __future__ import annotations

import pandas as pd

from src.detection.base import DetectionResult, RuleFlag
from src.detection.explanations import (
    build_document_explanation,
    build_export_narrative,
    build_rule_explanation,
    build_track_explanation,
    parse_flagged_rules,
)


def _make_result(track_name: str, flagged_indices: list[int]) -> DetectionResult:
    return DetectionResult(
        track_name=track_name,
        flagged_indices=flagged_indices,
        scores=pd.Series([0.2, 0.9], index=[0, 1], dtype=float),
        rule_flags=[RuleFlag("L3-04", "기말 대규모", 3, 1, 2)],
        details=pd.DataFrame({"L3-04": [0.0, 1.0]}, index=[0, 1]),
        metadata={"elapsed": 0.01},
    )


def test_parse_flagged_rules_handles_csv_and_empty():
    assert parse_flagged_rules("L2-01,L3-04") == ["L2-01", "L3-04"]
    assert parse_flagged_rules("") == []
    assert parse_flagged_rules(None) == []


def test_build_track_explanation_uses_result_defaults():
    result = _make_result("layer_a", [1])

    explanation = build_track_explanation(result)

    assert explanation["display_name"] == "L1"
    assert "structural integrity" in explanation["summary"]
    assert "debit_amount" in explanation["used_columns"]


def test_build_rule_explanation_returns_fallback_for_unknown():
    explanation = build_rule_explanation("ZZ99")

    assert explanation["rule_id"] == "ZZ99"
    assert explanation["rule_name"] == "Unknown Rule"
    assert "ZZ99" in explanation["plain_reason"]


def test_build_rule_explanation_includes_d02_limits_and_checks():
    explanation = build_rule_explanation("D02")

    assert explanation["rule_id"] == "D02"
    assert "monthly amount distribution" in explanation["plain_reason"]
    assert "fiscal_period" in explanation["used_columns"]
    assert explanation["false_positive_risks"]
    assert any("period-end" in item for item in explanation["auditor_checks"])


def test_build_document_explanation_aggregates_rules_and_tracks():
    df = pd.DataFrame(
        {
            "document_id": ["DOC1", "DOC1", "DOC2"],
            "risk_level": ["High", "High", "Low"],
            "anomaly_score": [0.91, 0.91, 0.1],
            "flagged_rules": ["L2-01,L3-04", "L2-01,L3-04", ""],
            "line_text": ["manual adjustment", "manual adjustment", "normal"],
        },
        index=[0, 1, 2],
    )
    result = _make_result("layer_b", [0, 1])

    explanation = build_document_explanation("DOC1", df, [result])

    assert "DOC1" in explanation["headline"]
    assert {item["rule_id"] for item in explanation["triggered_rules"]} == {"L2-01", "L3-04"}
    assert explanation["track_explanations"]
    assert explanation["track_explanations"][0]["display_name"] == "L2"


def test_build_document_explanation_describes_l307_direction():
    df = pd.DataFrame(
        {
            "document_id": ["DOC1", "DOC2"],
            "risk_level": ["High", "High"],
            "anomaly_score": [0.91, 0.88],
            "flagged_rules": ["L3-07", "L3-07"],
            "line_text": ["late", "forward"],
            "days_backdated": [45, -35],
        },
        index=[0, 1],
    )

    late = build_document_explanation("DOC1", df, [])
    forward = build_document_explanation("DOC2", df, [])

    assert "45 days after document date" in late["transaction_details"][0]["trigger_value"]
    assert "35 days before document date" in forward["transaction_details"][0]["trigger_value"]


def test_build_document_explanation_splits_l205_interpretation():
    df = pd.DataFrame(
        {
            "document_id": ["DOC1", "DOC2"],
            "risk_level": ["High", "Medium"],
            "anomaly_score": [0.91, 0.61],
            "flagged_rules": ["L2-05", "L2-05"],
            "line_text": ["system reverse", "reclass accrual"],
        },
        index=[0, 1],
    )
    result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0, 1],
        scores=pd.Series([0.9, 0.6], index=[0, 1], dtype=float),
        rule_flags=[RuleFlag("L2-05", "Reversal Pattern", 4, 2, 2)],
        details=pd.DataFrame({"L2-05": [0.8, 0.8]}, index=[0, 1]),
        metadata={
            "elapsed": 0.01,
            "row_annotations": {
                "L2-05": {
                    0: {
                        "interpretation_label": "High-confidence reversal",
                        "reason_text": (
                            "ERP reversal reference fields link "
                            "the original and reversal entries"
                        ),
                    },
                    1: {
                        "interpretation_label": "Candidate reversal / clearing / reclass",
                        "reason_text": (
                            "an opposite-signed document pair "
                            "matched on account and amount"
                        ),
                    },
                }
            },
        },
    )

    high = build_document_explanation("DOC1", df, [result])
    candidate = build_document_explanation("DOC2", df, [result])

    assert "High-confidence reversal" in high["transaction_details"][0]["trigger_value"]
    assert (
        "Candidate reversal / clearing / reclass"
        in candidate["transaction_details"][0]["trigger_value"]
    )


def test_build_export_narrative_includes_rule_and_auditor_check():
    text = build_export_narrative(
        document_id="DOC9",
        score=0.88,
        risk="High",
        rules=["L2-02"],
        top_features=[("amount", 0.42)],
    )

    assert "DOC9" in text
    assert "L2-02" in text
    assert "Top feature contributions" in text
    assert "amount" in text
