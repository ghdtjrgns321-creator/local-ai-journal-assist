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
    """RULE_CODES 29개 룰 ID·이름 무결성 (24+B19+B11+D01+D02)."""

    def test_rule_count(self) -> None:
        assert len(RULE_CODES) == 29

    def test_layer_a_ids(self) -> None:
        for rid in ("A01", "A02", "A03"):
            assert rid in RULE_CODES

    def test_layer_b_ids(self) -> None:
        for i in range(1, 11):
            assert f"B{i:02d}" in RULE_CODES

    def test_layer_c_ids(self) -> None:
        for i in range(1, 10):
            assert f"C{i:02d}" in RULE_CODES

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
        [("A01", 5), ("C06", 1), ("B07", 4)],
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
        assert set(Layer) == {"layer_a", "layer_b", "layer_c", "benford", "layer_d"}
