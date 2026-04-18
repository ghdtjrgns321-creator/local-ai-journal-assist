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
        rule_flags=[RuleFlag("C01", "기말 대규모", 3, 1, 2)],
        details=pd.DataFrame({"C01": [0.0, 1.0]}, index=[0, 1]),
        metadata={"elapsed": 0.01},
    )


def test_parse_flagged_rules_handles_csv_and_empty():
    assert parse_flagged_rules("B02,C01") == ["B02", "C01"]
    assert parse_flagged_rules("") == []
    assert parse_flagged_rules(None) == []


def test_build_track_explanation_uses_result_defaults():
    result = _make_result("layer_a", [1])

    explanation = build_track_explanation(result)

    assert explanation["display_name"] == "Layer A"
    assert "기본 통제 계층" in explanation["summary"]
    assert "debit_amount" in explanation["used_columns"]


def test_build_rule_explanation_returns_fallback_for_unknown():
    explanation = build_rule_explanation("ZZ99")

    assert explanation["rule_id"] == "ZZ99"
    assert explanation["rule_name"] == "미등록 룰"
    assert "미등록 룰" in explanation["plain_reason"]


def test_build_document_explanation_aggregates_rules_and_tracks():
    df = pd.DataFrame(
        {
            "document_id": ["DOC1", "DOC1", "DOC2"],
            "risk_level": ["High", "High", "Low"],
            "anomaly_score": [0.91, 0.91, 0.1],
            "flagged_rules": ["B02,C01", "B02,C01", ""],
            "line_text": ["manual adjustment", "manual adjustment", "normal"],
        },
        index=[0, 1, 2],
    )
    result = _make_result("layer_b", [0, 1])

    explanation = build_document_explanation("DOC1", df, [result])

    assert "DOC1" in explanation["headline"]
    assert {item["rule_id"] for item in explanation["triggered_rules"]} == {"B02", "C01"}
    assert explanation["auditor_focus_points"]
    assert explanation["track_explanations"][0]["display_name"] == "Layer B"


def test_build_export_narrative_includes_rule_and_auditor_check():
    text = build_export_narrative(
        document_id="DOC9",
        score=0.88,
        risk="High",
        rules=["B04"],
        top_features=[("amount", 0.42)],
    )

    assert "DOC9" in text
    assert "B04" in text
    assert "감사자 확인 포인트" in text
    assert "amount" in text
