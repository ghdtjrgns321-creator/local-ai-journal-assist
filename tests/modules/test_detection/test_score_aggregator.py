"""score_aggregator 단위 테스트 — 21개.

aggregate_scores / classify_risk_level / auto_escalation / flagged_rules / topside / edge cases.
"""

from __future__ import annotations

import numpy as np
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

        assert list(result.columns) == ["anomaly_score", "risk_level", "flagged_rules", "topside_score"]

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


class TestClassifyRiskLevelQuantile:
    """분위수 기반 risk_level 분류 (묶음 1 — risk_classification_mode='quantile')."""

    def test_top_quantile_is_high(self):
        # Why: 100개 score 중 상위 10%는 HIGH (quantile 기본값 high=0.9)
        scores = pd.Series(np.linspace(0.01, 1.0, 100))
        levels = classify_risk_level(scores, mode="quantile")
        # 상위 10개 = HIGH
        assert (levels.iloc[-10:] == RiskLevel.HIGH).all()

    def test_bottom_quantile_is_normal(self):
        # Why: 하위 50%는 NORMAL
        scores = pd.Series(np.linspace(0.01, 1.0, 100))
        levels = classify_risk_level(scores, mode="quantile")
        assert (levels.iloc[:50] == RiskLevel.NORMAL).all()

    def test_zero_scores_always_normal(self):
        # Why: score=0인 행은 rank가 높더라도 NORMAL (실제 위험 없음)
        scores = pd.Series([0.0] * 50 + [0.9] * 50)
        levels = classify_risk_level(scores, mode="quantile")
        assert (levels.iloc[:50] == RiskLevel.NORMAL).all()

    def test_all_zero_returns_all_normal(self):
        scores = pd.Series([0.0] * 20)
        levels = classify_risk_level(scores, mode="quantile")
        assert (levels == RiskLevel.NORMAL).all()

    def test_custom_quantiles(self):
        # Why: 커스텀 분위수 — 상위 50%만 HIGH
        scores = pd.Series(np.linspace(0.01, 1.0, 100))
        levels = classify_risk_level(
            scores, mode="quantile",
            quantiles={
                RiskLevel.HIGH: 0.5,
                RiskLevel.MEDIUM: 0.3,
                RiskLevel.LOW: 0.1,
            },
        )
        assert (levels.iloc[-50:] == RiskLevel.HIGH).all()


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


# ── TestTopsideDetection ────────────────────────────────


def _topside_layers(
    n: int = 5,
    c01: list[float] | None = None,
    b06: list[float] | None = None,
    b09: list[float] | None = None,
    a03: list[float] | None = None,
    c09: list[float] | None = None,
    c08: list[float] | None = None,
    c06: list[float] | None = None,
) -> list:
    """Top-side JE 테스트용 4개 레이어 결과 생성 헬퍼."""
    z = [0.0] * n
    layer_a = _make_result("layer_a", a03 or z, {"A03": a03 or z})
    layer_b_details = {
        "B06": b06 or z,
        "B09": b09 or z,
    }
    b_scores = [max(b06_v, b09_v) for b06_v, b09_v in
                zip(layer_b_details["B06"], layer_b_details["B09"])]
    layer_b = _make_result("layer_b", b_scores, layer_b_details)
    layer_c_details = {
        "C01": c01 or z,
        "C06": c06 or z,
        "C08": c08 or z,
        "C09": c09 or z,
    }
    c_scores = [max(vals) for vals in zip(*layer_c_details.values())]
    layer_c = _make_result("layer_c", c_scores, layer_c_details)
    benford = _make_result("benford", z, {"C07": z})
    return [layer_a, layer_b, layer_c, benford]


class TestTopsideDetection:
    """B19 Top-side JE 복합 탐지 — 게이트키퍼(수기) + 5개 가점."""

    def test_all_conditions_met(self):
        """수기 + 5개 가점 전부 → B19 플래그, risk_level=High."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        layers = _topside_layers(
            c01=[0.6] * 5, b06=[0.6] * 5,
            a03=[0.6] * 5, c08=[0.6] * 5, c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert "B19" in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(1.0)

    def test_threshold_boundary(self):
        """수기 + 정확히 2개 가점 → B19 플래그 (임계값 기본 2)."""
        df = pd.DataFrame({"is_manual_je": [True, False, True, True, True]})
        layers = _topside_layers(
            c01=[0.6, 0.0, 0.6, 0.0, 0.0],
            c08=[0.6, 0.0, 0.6, 0.0, 0.0],
        )
        result = aggregate_scores(df, layers)
        # 행 0: 수기 + C01 + C08 = 2점 → 플래그
        assert "B19" in result["flagged_rules"].iloc[0]
        # 행 1: 자동 + C01 + C08 = 0점 (게이트키퍼) → 미플래그
        assert "B19" not in result["flagged_rules"].iloc[1]

    def test_below_threshold(self):
        """수기 + 1개 가점만 → B19 미플래그."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        layers = _topside_layers(c01=[0.6] * 5)  # 가점 1개만
        result = aggregate_scores(df, layers)
        assert "B19" not in result["flagged_rules"].iloc[0]

    def test_automated_je_blocked(self):
        """자동 전표 + 5개 가점 전부 → B19 미플래그 (게이트키퍼 핵심 테스트)."""
        df = pd.DataFrame({"is_manual_je": [False] * 5})
        layers = _topside_layers(
            c01=[0.6] * 5, b06=[0.6] * 5,
            a03=[0.6] * 5, c08=[0.6] * 5, c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        # Why: 자동 전표는 가점 만점이어도 Top-side JE 아님
        assert "B19" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.0)

    def test_no_manual_column(self):
        """is_manual_je 컬럼 없음 → 전체 0점 (안전 차단)."""
        df = pd.DataFrame({"val": range(5)})  # is_manual_je 없음
        layers = _topside_layers(
            c01=[0.6] * 5, b06=[0.6] * 5,
            a03=[0.6] * 5, c08=[0.6] * 5, c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        assert "B19" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.0)

    def test_missing_layers(self):
        """일부 레이어 없음 → 해당 조건 0점, 에러 없음."""
        df = pd.DataFrame({"is_manual_je": [True] * 3})
        # layer_a, layer_b 없이 layer_c만 전달
        layer_c = _make_result("layer_c", [0.6] * 3, {
            "C01": [0.6] * 3, "C08": [0.6] * 3, "C06": [0.2] * 3,
        })
        benford = _make_result("benford", [0.0] * 3, {"C07": [0.0] * 3})
        result = aggregate_scores(df, [layer_c, benford])
        # C01 + C08 + C06 = 3점 → 2점 이상이므로 B19
        assert "B19" in result["flagged_rules"].iloc[0]

    def test_topside_score_column(self):
        """결과에 topside_score 컬럼 존재 (0.0~1.0 범위)."""
        df = pd.DataFrame({"val": range(5)})
        layers = _topside_layers()
        result = aggregate_scores(df, layers)
        assert "topside_score" in result.columns
        assert result["topside_score"].between(0.0, 1.0).all()

    def test_flagged_rules_appended(self):
        """기존 flagged_rules에 B19 정상 추가."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        # A03 + C01 + C08 → 기존 플래그 + B19
        layers = _topside_layers(
            a03=[0.6] * 5, c01=[0.6] * 5, c08=[0.6] * 5,
        )
        result = aggregate_scores(df, layers)
        rules = result["flagged_rules"].iloc[0]
        # 기존 룰(A03, C01, C08)과 B19 모두 포함
        assert "A03" in rules
        assert "B19" in rules

    def test_combined_with_auto_escalation(self):
        """auto_escalation과 topside 동시 적용 시 충돌 없음."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        # A01 위반(1개) + B06·B09 위반(2개) → auto_escalation 트리거
        # + C01 + C08 → topside 트리거
        layer_a = _make_result("layer_a", [0.4] * 5, {"A01": [0.4] * 5, "A03": [0.4] * 5})
        layer_b = _make_result("layer_b", [0.6] * 5, {"B06": [0.6] * 5, "B09": [0.6] * 5})
        layer_c = _make_result("layer_c", [0.6] * 5, {"C01": [0.6] * 5, "C08": [0.6] * 5})
        benford = _make_result("benford", [0.0] * 5, {"C07": [0.0] * 5})
        result = aggregate_scores(df, [layer_a, layer_b, layer_c, benford])
        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert "B19" in result["flagged_rules"].iloc[0]


# ── TestMLWeights ────────────────────────────────────────


class TestMLWeights:
    """ML 트랙 포함 가중합."""

    def test_ml_weights_sum_to_one(self):
        """LAYER_WEIGHTS_WITH_ML 합계 = 1.0."""
        from src.detection.constants import LAYER_WEIGHTS_WITH_ML
        assert sum(LAYER_WEIGHTS_WITH_ML.values()) == pytest.approx(1.0)

    def test_ml_tracks_included(self, base_df):
        """ML 트랙 결과가 가중합에 반영."""
        from src.detection.constants import LAYER_WEIGHTS_WITH_ML
        layer_a = _make_result("layer_a", [0.5] * 5, {"A01": [0.5] * 5})
        ml_unsup = _make_result("ml_unsupervised", [0.8] * 5, {"ML02": [0.8] * 5})
        result = aggregate_scores(
            base_df, [layer_a, ml_unsup],
            weights=LAYER_WEIGHTS_WITH_ML,
        )
        # 0.5×0.10 + 0.8×0.17 = 0.186
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.05 + 0.136)

    def test_ml_tracks_ignored_without_ml_weights(self, base_df):
        """기본 LAYER_WEIGHTS 사용 시 ML 트랙 0점 처리."""
        layer_a = _make_result("layer_a", [0.5] * 5, {"A01": [0.5] * 5})
        ml_unsup = _make_result("ml_unsupervised", [0.8] * 5, {"ML02": [0.8] * 5})
        result = aggregate_scores(base_df, [layer_a, ml_unsup])
        # ML 트랙은 기본 가중치에 없으므로 무시됨
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.5 * 0.15)

    def test_cold_start_no_ml_results(self, base_df, four_layer_results):
        """ML 결과 없이 LAYER_WEIGHTS_WITH_ML 적용 → ML 트랙 0점, 에러 없음."""
        from src.detection.constants import LAYER_WEIGHTS_WITH_ML
        result = aggregate_scores(
            base_df, four_layer_results,
            weights=LAYER_WEIGHTS_WITH_ML,
        )
        assert (result["anomaly_score"] >= 0).all()
        assert (result["anomaly_score"] <= 1).all()
