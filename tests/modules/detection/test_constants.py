"""constants.py 단위 테스트 — 룰 메타데이터 무결성 검증."""

from __future__ import annotations

import pytest

from src.detection.constants import (
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    RULE_CODES,
    SEVERITY_MAP,
    Layer,
    RiskLevel,
)


class TestRuleCodesIntegrity:
    """RULE_CODES 룰 ID·이름 무결성. 신규 룰 추가 시 카운트 갱신."""

    def test_rule_count(self) -> None:
        # Why: Current registry includes L1-L4, analytical, graph, evidence, access,
        # trendbreak, NLP, and Phase2 ML rule codes.
        assert len(RULE_CODES) == 70

    def test_layer_a_ids(self) -> None:
        for rid in ("L1-01", "L1-02", "L1-03"):
            assert rid in RULE_CODES

    def test_layer_b_ids(self) -> None:
        for rid in ("L2-01", "L2-02", "L2-03", "L2-04", "L2-05"):
            assert rid in RULE_CODES

    def test_layer_c_ids(self) -> None:
        for rid in (
            "L3-01",
            "L3-02",
            "L3-03",
            "L3-04",
            "L3-05",
            "L3-06",
            "L3-07",
            "L3-08",
            "L3-09",
            "L3-10",
            "L3-11",
            "L3-12",
        ):
            assert rid in RULE_CODES

    def test_all_names_nonempty(self) -> None:
        for rid, name in RULE_CODES.items():
            assert name, f"{rid}의 이름이 비어 있음"


class TestSeverityMap:
    """SEVERITY_MAP 22개 룰 severity 범위 검증."""

    def test_keys_match_rule_codes(self) -> None:
        assert set(SEVERITY_MAP.keys()) == set(RULE_CODES.keys())

    def test_severity_range(self) -> None:
        for rid, sev in SEVERITY_MAP.items():
            assert 1 <= sev <= 5, f"{rid} severity={sev}, 범위 1~5 벗어남"

    @pytest.mark.parametrize(
        "rule_id, expected",
        [("L1-01", 5), ("L3-08", 1), ("L1-06", 4)],
    )
    def test_specific_severities(self, rule_id: str, expected: int) -> None:
        assert SEVERITY_MAP[rule_id] == expected


class TestLayerWeights:
    """LAYER_WEIGHTS 합계 = 1.0, 키 = Layer enum."""

    def test_sum_equals_one(self) -> None:
        assert abs(sum(LAYER_WEIGHTS.values()) - 1.0) < 1e-9

    def test_keys_are_layer_enum(self) -> None:
        for key in LAYER_WEIGHTS:
            assert key in [e.value for e in Layer]


class TestRiskThresholds:
    """RISK_THRESHOLDS 내림차순 검증."""

    def test_descending_order(self) -> None:
        vals = list(RISK_THRESHOLDS.values())
        assert vals == sorted(vals, reverse=True)


class TestEnums:
    """RiskLevel·Layer enum 값 검증."""

    def test_risk_level_values(self) -> None:
        assert set(RiskLevel) == {"High", "Medium", "Low", "Normal"}

    def test_layer_values(self) -> None:
        # Why: 신규 트랙 추가 시 갱신. 기본 5종 + Phase 2/3 확장 레이어.
        expected = {
            "layer_a",
            "layer_b",
            "layer_c",
            "benford",
            "layer_d",
            "duplicate",
            "timeseries",
            "intercompany",
            "relational",
            "ml_supervised",
            "ml_unsupervised",
            "ml_transformer",
            "ml_sequence",
            "ensemble",
            "access_audit",
            "evidence",
            "trendbreak",
            "graph",
            "nlp",
        }
        assert set(Layer) == expected
