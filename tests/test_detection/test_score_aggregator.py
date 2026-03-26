"""score_aggregator 단위 테스트 — 12개.

aggregate_scores / classify_risk_level / auto_escalation / flagged_rules / edge cases.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.constants import Layer, RiskLevel
from src.detection.score_aggregator import aggregate_scores, classify_risk_level


# ── 테스트 헬퍼 ───────────────────────────────────────────


def _make_result(
    track_name: str,
    scores: list[float],
    details_dict: dict[str, list[float]],
    index: list[int] | None = None,
) -> DetectionResult:
    """DetectionResult 간편 생성 헬퍼."""
    idx = index or list(range(len(scores)))
    scores_s = pd.Series(scores, index=idx, dtype=float)
    details_df = pd.DataFrame(details_dict, index=idx)
    flagged = scores_s[scores_s > 0].index.tolist()
    rule_flags = [
        RuleFlag(
            rule_id=col, rule_name=col, severity=3,
            flagged_count=int((details_df[col] > 0).sum()),
            total_count=len(idx),
        )
        for col in details_df.columns
    ]
    return DetectionResult(
        track_name=track_name,
        flagged_indices=flagged,
        scores=scores_s,
        rule_flags=rule_flags,
        details=details_df,
        metadata={"elapsed": 0.01, "skipped_rules": []},
        warnings=[],
    )


# ── 공용 fixture ──────────────────────────────────────────


@pytest.fixture
def base_df() -> pd.DataFrame:
    """5행짜리 기본 DataFrame."""
    return pd.DataFrame({"val": range(5)})


@pytest.fixture
def four_layer_results() -> list[DetectionResult]:
    """4개 레이어 결과 — 행 5개, Layer A~C + Benford."""
    layer_a = _make_result("layer_a", [1.0, 0.0, 0.0, 0.0, 0.0], {"A01": [1.0, 0.0, 0.0, 0.0, 0.0]})
    layer_b = _make_result("layer_b", [0.6, 0.6, 0.0, 0.0, 0.0], {"B01": [0.6, 0.0, 0.0, 0.0, 0.0], "B03": [0.0, 0.6, 0.0, 0.0, 0.0]})
    layer_c = _make_result("layer_c", [0.4, 0.0, 0.4, 0.0, 0.0], {"C01": [0.4, 0.0, 0.4, 0.0, 0.0]})
    benford = _make_result("benford", [0.3, 0.3, 0.3, 0.3, 0.3], {"C07": [0.3, 0.3, 0.3, 0.3, 0.3]})
    return [layer_a, layer_b, layer_c, benford]


# ── TestAggregateScores ───────────────────────────────────


class TestAggregateScores:
    """가중합 산출 핵심 로직."""

    def test_basic_weighted_sum(self, base_df, four_layer_results):
        """4개 레이어 가중합 = 수동 계산값."""
        result = aggregate_scores(base_df, four_layer_results)

        # 행 0: A=1.0×0.15 + B=0.6×0.45 + C=0.4×0.25 + Ben=0.3×0.15
        expected_row0 = 1.0 * 0.15 + 0.6 * 0.45 + 0.4 * 0.25 + 0.3 * 0.15
        assert result["anomaly_score"].iloc[0] == pytest.approx(expected_row0)

        # 행 4: 모든 레이어 0 (Benford만 0.3)
        expected_row4 = 0.3 * 0.15
        assert result["anomaly_score"].iloc[4] == pytest.approx(expected_row4)

        assert list(result.columns) == ["anomaly_score", "risk_level", "flagged_rules"]

    def test_missing_layer(self, base_df):
        """3개만 전달 → 누락 레이어 0점 처리, 에러 없음."""
        layer_a = _make_result("layer_a", [0.5] * 5, {"A01": [0.5] * 5})
        layer_b = _make_result("layer_b", [0.5] * 5, {"B01": [0.5] * 5})
        layer_c = _make_result("layer_c", [0.5] * 5, {"C01": [0.5] * 5})
        # benford 누락

        result = aggregate_scores(base_df, [layer_a, layer_b, layer_c])
        # 0.5×0.15 + 0.5×0.45 + 0.5×0.25 + 0(누락)×0.15 = 0.425
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.425)

    def test_custom_weights(self, base_df):
        """weights 파라미터 오버라이드."""
        layer_a = _make_result("layer_a", [1.0] * 5, {"A01": [1.0] * 5})
        custom_weights = {"layer_a": 0.5}

        result = aggregate_scores(base_df, [layer_a], weights=custom_weights)
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.5)


# ── TestClassifyRiskLevel ─────────────────────────────────


class TestClassifyRiskLevel:
    """위험 등급 분류 임계값."""

    def test_high(self):
        assert classify_risk_level(pd.Series([0.8])).iloc[0] == RiskLevel.HIGH

    def test_medium(self):
        assert classify_risk_level(pd.Series([0.5])).iloc[0] == RiskLevel.MEDIUM

    def test_low(self):
        assert classify_risk_level(pd.Series([0.3])).iloc[0] == RiskLevel.LOW

    def test_normal(self):
        assert classify_risk_level(pd.Series([0.1])).iloc[0] == RiskLevel.NORMAL


# ── TestAutoEscalation ────────────────────────────────────


class TestAutoEscalation:
    """Layer A + B 복합 위반 자동 승격."""

    def test_triggers(self, base_df):
        """A 1개 위반 + B 2개 위반 → 원래 Medium이어도 High."""
        # 행 0: A01 위반 + B01·B03 위반 → 자동 승격 대상
        layer_a = _make_result("layer_a", [0.4, 0.0, 0.0, 0.0, 0.0], {"A01": [0.4, 0.0, 0.0, 0.0, 0.0]})
        layer_b = _make_result("layer_b", [0.6, 0.0, 0.0, 0.0, 0.0], {
            "B01": [0.6, 0.0, 0.0, 0.0, 0.0],
            "B03": [0.6, 0.0, 0.0, 0.0, 0.0],
        })

        result = aggregate_scores(base_df, [layer_a, layer_b])
        assert result["risk_level"].iloc[0] == RiskLevel.HIGH

    def test_no_trigger(self, base_df):
        """A 위반 + B 1개만 → 승격 안됨."""
        layer_a = _make_result("layer_a", [0.4, 0.0, 0.0, 0.0, 0.0], {"A01": [0.4, 0.0, 0.0, 0.0, 0.0]})
        layer_b = _make_result("layer_b", [0.6, 0.0, 0.0, 0.0, 0.0], {
            "B01": [0.6, 0.0, 0.0, 0.0, 0.0],
        })

        result = aggregate_scores(base_df, [layer_a, layer_b])
        # 행 0: 0.4×0.15 + 0.6×0.45 = 0.33 → Low (승격 안됨)
        assert result["risk_level"].iloc[0] == RiskLevel.LOW


# ── TestFlaggedRules ──────────────────────────────────────


class TestFlaggedRules:
    """위반 룰 ID comma-separated 형식."""

    def test_comma_separated(self, base_df):
        layer_a = _make_result("layer_a", [1.0, 0.0, 0.0, 0.0, 0.0], {"A01": [1.0, 0.0, 0.0, 0.0, 0.0]})
        layer_b = _make_result("layer_b", [0.6, 0.0, 0.0, 0.0, 0.0], {"B03": [0.6, 0.0, 0.0, 0.0, 0.0]})

        result = aggregate_scores(base_df, [layer_a, layer_b])
        # 행 0: A01 + B03 모두 위반
        assert result["flagged_rules"].iloc[0] == "A01,B03"
        # 행 1: 위반 없음
        assert result["flagged_rules"].iloc[1] == ""


# ── TestEdgeCases ─────────────────────────────────────────


class TestEdgeCases:
    """경계 케이스."""

    def test_score_clamped(self):
        """가중합 > 1.0 시 clip 확인."""
        df = pd.DataFrame({"val": range(3)})
        # 모든 레이어 scores=1.0이면 가중합=1.0 (정상). 가중치 합이 1 초과하도록 커스텀.
        layer_a = _make_result("layer_a", [1.0, 1.0, 1.0], {"A01": [1.0, 1.0, 1.0]})
        layer_b = _make_result("layer_b", [1.0, 1.0, 1.0], {"B01": [1.0, 1.0, 1.0]})
        weights = {"layer_a": 0.8, "layer_b": 0.8}  # 합 1.6

        result = aggregate_scores(df, [layer_a, layer_b], weights=weights)
        assert result["anomaly_score"].iloc[0] == pytest.approx(1.0)

    def test_preserves_original_index(self):
        """비연속 인덱스 [10, 20, 30] 보존."""
        df = pd.DataFrame({"val": [1, 2, 3]}, index=[10, 20, 30])
        layer_a = _make_result("layer_a", [0.5, 0.0, 0.0], {"A01": [0.5, 0.0, 0.0]}, index=[10, 20, 30])

        result = aggregate_scores(df, [layer_a])
        assert list(result.index) == [10, 20, 30]
