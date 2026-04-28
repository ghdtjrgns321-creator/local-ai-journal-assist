"""score_aggregator 단위 테스트 — 21개.

aggregate_scores / classify_risk_level / auto_escalation / flagged_rules / topside / edge cases.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.constants import (
    LAYER_WEIGHTS_WITH_ML,
    RULE_LEVEL_WEIGHTS,
    Layer,
    RiskLevel,
)
from src.detection.rule_scoring import normalize_rule_evidence
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
    """4개 트랙 결과 — 행 5개, L1/L2/L3-L4 + Benford."""
    layer_a = _make_result(
        "layer_a",
        [1.0, 0.0, 0.0, 0.0, 0.0],
        {"L1-01": [1.0, 0.0, 0.0, 0.0, 0.0]},
    )
    layer_b = _make_result(
        "layer_b",
        [0.6, 0.6, 0.0, 0.0, 0.0],
        {
            "L4-01": [0.6, 0.0, 0.0, 0.0, 0.0],
            "L1-04": [0.0, 0.6, 0.0, 0.0, 0.0],
        },
    )
    layer_c = _make_result(
        "layer_c",
        [0.4, 0.0, 0.4, 0.0, 0.0],
        {"L3-04": [0.4, 0.0, 0.4, 0.0, 0.0]},
    )
    benford = _make_result(
        "benford",
        [0.3, 0.3, 0.3, 0.3, 0.3],
        {"L4-02": [0.3, 0.3, 0.3, 0.3, 0.3]},
    )
    return [layer_a, layer_b, layer_c, benford]


# ── TestAggregateScores ───────────────────────────────────


class TestAggregateScores:
    """가중합 산출 핵심 로직."""

    def test_basic_weighted_sum(self, base_df, four_layer_results):
        """4개 레이어 가중합 = 수동 계산값."""
        result = aggregate_scores(base_df, four_layer_results)

        # 행 0: 기본 집계는 legacy layer가 아니라 정규화된 L1/L2/L3/L4 룰 family 기준.
        expected_row0 = (
            normalize_rule_evidence(
                rule_id="L1-01",
                evidence_type="data_integrity_failure",
                severity=3,
                raw_value=1.0,
            ).normalized_score * RULE_LEVEL_WEIGHTS["L1"]
            + normalize_rule_evidence(
                rule_id="L3-04",
                evidence_type="timing_anomaly",
                severity=3,
                raw_value=0.4,
            ).normalized_score * RULE_LEVEL_WEIGHTS["L3"]
            + normalize_rule_evidence(
                rule_id="L4-01",
                evidence_type="statistical_outlier",
                severity=3,
                raw_value=0.6,
            ).normalized_score * RULE_LEVEL_WEIGHTS["L4"]
        )
        assert result["anomaly_score"].iloc[0] == pytest.approx(expected_row0)

        # 행 4: L4-02 Benford는 macro-only라 transaction anomaly_score에 직접 더하지 않음.
        expected_row4 = 0.0
        assert result["anomaly_score"].iloc[4] == pytest.approx(expected_row4)

        assert list(result.columns) == [
            "anomaly_score",
            "risk_level",
            "flagged_rules",
            "review_rules",
            "risk_floor_reasons",
            "batch_combo_score",
            "batch_combo_reasons",
            "work_scope_combo_score",
            "work_scope_combo_reasons",
            "topside_score",
        ]

    def test_missing_layer(self, base_df):
        """3개만 전달 → 누락 레이어 0점 처리, 에러 없음."""
        layer_a = _make_result("layer_a", [0.5] * 5, {"L1-01": [0.5] * 5})
        layer_b = _make_result("layer_b", [0.5] * 5, {"L4-01": [0.5] * 5})
        layer_c = _make_result("layer_c", [0.5] * 5, {"L3-04": [0.5] * 5})
        # benford 누락

        result = aggregate_scores(base_df, [layer_a, layer_b, layer_c])
        expected = (
            normalize_rule_evidence(
                rule_id="L1-01",
                evidence_type="data_integrity_failure",
                severity=3,
                raw_value=0.5,
            ).normalized_score * RULE_LEVEL_WEIGHTS["L1"]
            + normalize_rule_evidence(
                rule_id="L3-04",
                evidence_type="timing_anomaly",
                severity=3,
                raw_value=0.5,
            ).normalized_score * RULE_LEVEL_WEIGHTS["L3"]
            + normalize_rule_evidence(
                rule_id="L4-01",
                evidence_type="statistical_outlier",
                severity=3,
                raw_value=0.5,
            ).normalized_score * RULE_LEVEL_WEIGHTS["L4"]
        )
        assert result["anomaly_score"].iloc[0] == pytest.approx(expected)

    def test_custom_weights(self, base_df):
        """weights 파라미터 오버라이드."""
        layer_a = _make_result("layer_a", [1.0] * 5, {"L1-01": [1.0] * 5})
        custom_weights = {"layer_a": 0.5}

        result = aggregate_scores(base_df, [layer_a], weights=custom_weights)
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.5)

    def test_rule_level_aggregation_uses_l1_rule_labels(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.4, 0.8, 0.0, 0.0, 0.0],
            {"L1-05": [0.4, 0.8, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L1-05": {
                0: {"bucket": "review"},
                1: {"bucket": "immediate"},
            }
        }

        result = aggregate_scores(base_df, [layer_b])

        review_score = normalize_rule_evidence(
            rule_id="L1-05",
            evidence_type="control_failure",
            severity=3,
            raw_value=0.4,
            display_label="review",
        ).normalized_score
        immediate_score = normalize_rule_evidence(
            rule_id="L1-05",
            evidence_type="control_failure",
            severity=3,
            raw_value=0.8,
            display_label="immediate",
        ).normalized_score
        assert result["anomaly_score"].iloc[0] == pytest.approx(
            review_score * RULE_LEVEL_WEIGHTS["L1"]
        )
        assert immediate_score * RULE_LEVEL_WEIGHTS["L1"] < 0.7
        assert result["anomaly_score"].iloc[1] == pytest.approx(0.7)
        assert result["risk_floor_reasons"].iloc[1] == "L1-05:immediate"
        assert result["anomaly_score"].iloc[1] > result["anomaly_score"].iloc[0]

    def test_rule_level_aggregation_splits_review_only_annotation_rules(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.0, 0.75, 0.0, 0.0, 0.0],
            {"L1-04": [0.0, 0.75, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L1-04": {
                0: {"bucket": "boundary", "queue_label": "review", "review_score": 0.4},
                1: {"bucket": "severe", "queue_label": "immediate", "score": 0.75},
            }
        }

        result = aggregate_scores(base_df, [layer_b])

        review_score = normalize_rule_evidence(
            rule_id="L1-04",
            evidence_type="control_failure",
            severity=3,
            raw_value=0.4,
            display_label="boundary",
        ).normalized_score
        assert result["anomaly_score"].iloc[0] == pytest.approx(
            review_score * RULE_LEVEL_WEIGHTS["L1"]
        )
        assert result["flagged_rules"].iloc[0] == ""
        assert result["review_rules"].iloc[0] == "L1-04"
        assert result["flagged_rules"].iloc[1] == "L1-04"
        assert result["review_rules"].iloc[1] == ""
        assert result["anomaly_score"].iloc[1] > result["anomaly_score"].iloc[0]


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
    """L1 + L2 복합 위반 자동 승격."""

    def test_triggers(self, base_df):
        """A 1개 위반 + B 2개 위반 → 원래 Medium이어도 High."""
        # 행 0: L1-01 위반 + L4-01·L1-04 위반 → 자동 승격 대상
        layer_a = _make_result(
            "layer_a",
            [0.4, 0.0, 0.0, 0.0, 0.0],
            {"L1-01": [0.4, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_b = _make_result(
            "layer_b",
            [0.6, 0.0, 0.0, 0.0, 0.0],
            {
                "L4-01": [0.6, 0.0, 0.0, 0.0, 0.0],
                "L1-04": [0.6, 0.0, 0.0, 0.0, 0.0],
            },
        )

        result = aggregate_scores(base_df, [layer_a, layer_b])
        assert result["risk_level"].iloc[0] == RiskLevel.HIGH

    def test_no_trigger(self, base_df):
        """A 위반 + B 1개만 → 승격 안됨."""
        layer_a = _make_result(
            "layer_a",
            [0.4, 0.0, 0.0, 0.0, 0.0],
            {"L1-01": [0.4, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_b = _make_result(
            "layer_b",
            [0.6, 0.0, 0.0, 0.0, 0.0],
            {"L4-01": [0.6, 0.0, 0.0, 0.0, 0.0]},
        )

        result = aggregate_scores(base_df, [layer_a, layer_b])
        # 행 0: 0.4×0.15 + 0.6×0.45 = 0.33 → Low (승격 안됨)
        assert result["risk_level"].iloc[0] == RiskLevel.LOW


class TestPolicyRiskFloors:
    """Policy floors for severe single-rule control failures."""

    def test_l105_escalated_materiality_is_high_even_as_single_rule(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.8, 0.0, 0.0, 0.0, 0.0],
            {"L1-05": [0.8, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L1-05": {0: {"bucket": "escalated_materiality"}}
        }

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= 0.7
        assert result["risk_floor_reasons"].iloc[0] == "L1-05:escalated_materiality"


class TestBatchCorroboration:
    """L4-06 batch 신호는 결합될 때만 우선순위를 올린다."""

    def test_l406_only_stays_low_priority(self, base_df):
        layer_c = _make_result(
            "layer_c",
            [0.4, 0.0, 0.0, 0.0, 0.0],
            {"L4-06": [0.4, 0.0, 0.0, 0.0, 0.0]},
        )
        result = aggregate_scores(base_df, [layer_c])
        assert result["batch_combo_score"].iloc[0] == pytest.approx(0.0)
        assert result["risk_level"].iloc[0] == RiskLevel.NORMAL

    def test_l406_plus_two_groups_promotes_medium(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.6, 0.0, 0.0, 0.0, 0.0],
            {"L1-07": [0.6, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_c = _make_result(
            "layer_c",
            [0.4, 0.0, 0.0, 0.0, 0.0],
            {
                "L4-06": [0.4, 0.0, 0.0, 0.0, 0.0],
                "L3-04": [0.6, 0.0, 0.0, 0.0, 0.0],
            },
        )
        result = aggregate_scores(base_df, [layer_b, layer_c])
        assert result["batch_combo_score"].iloc[0] == pytest.approx(0.4)
        assert result["risk_level"].iloc[0] == RiskLevel.MEDIUM
        assert result["batch_combo_reasons"].iloc[0] == "closing_or_cutoff,control_failure"

    def test_l406_plus_three_groups_promotes_high(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.6, 0.0, 0.0, 0.0, 0.0],
            {"L1-07": [0.6, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_c = _make_result(
            "layer_c",
            [0.6, 0.0, 0.0, 0.0, 0.0],
            {
                "L4-06": [0.4, 0.0, 0.0, 0.0, 0.0],
                "L3-04": [0.6, 0.0, 0.0, 0.0, 0.0],
                "L4-03": [0.6, 0.0, 0.0, 0.0, 0.0],
            },
        )
        result = aggregate_scores(base_df, [layer_b, layer_c])
        assert result["batch_combo_score"].iloc[0] == pytest.approx(0.6)
        assert result["risk_level"].iloc[0] == RiskLevel.HIGH


# ── TestFlaggedRules ──────────────────────────────────────


class TestWorkScopeCorroboration:
    """L3-12 work-scope signal is promoted only with independent corroboration."""

    def test_l312_only_stays_low_score(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.65, 0.0, 0.0, 0.0, 0.0],
            {"L3-12": [0.65, 0.0, 0.0, 0.0, 0.0]},
        )

        result = aggregate_scores(base_df, [layer_b])

        assert result["work_scope_combo_score"].iloc[0] == pytest.approx(0.0)
        assert result["work_scope_combo_reasons"].iloc[0] == ""
        assert result["risk_level"].iloc[0] == RiskLevel.NORMAL
        assert "L3-12" in result["flagged_rules"].iloc[0]

    def test_l312_plus_two_groups_promotes_medium(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.65, 0.0, 0.0, 0.0, 0.0],
            {
                "L3-12": [0.65, 0.0, 0.0, 0.0, 0.0],
                "L3-02": [0.60, 0.0, 0.0, 0.0, 0.0],
                "L3-10": [0.50, 0.0, 0.0, 0.0, 0.0],
            },
        )

        result = aggregate_scores(base_df, [layer_b])

        assert result["work_scope_combo_score"].iloc[0] == pytest.approx(0.4)
        assert result["work_scope_combo_reasons"].iloc[0] == (
            "manual_or_control,sensitive_or_amount"
        )
        assert result["risk_level"].iloc[0] == RiskLevel.MEDIUM
        assert result["anomaly_score"].iloc[0] >= 0.4

    def test_l312_plus_three_groups_promotes_high(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.65, 0.0, 0.0, 0.0, 0.0],
            {
                "L3-12": [0.65, 0.0, 0.0, 0.0, 0.0],
                "L3-02": [0.60, 0.0, 0.0, 0.0, 0.0],
                "L3-10": [0.50, 0.0, 0.0, 0.0, 0.0],
            },
        )
        layer_c = _make_result(
            "layer_c",
            [0.60, 0.0, 0.0, 0.0, 0.0],
            {"L3-04": [0.60, 0.0, 0.0, 0.0, 0.0]},
        )

        result = aggregate_scores(base_df, [layer_b, layer_c])

        assert result["work_scope_combo_score"].iloc[0] == pytest.approx(0.6)
        assert result["work_scope_combo_reasons"].iloc[0] == (
            "manual_or_control,sensitive_or_amount,closing_or_timing"
        )
        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= 0.7


class TestFlaggedRules:
    """위반 룰 ID comma-separated 형식."""

    def test_comma_separated(self, base_df):
        layer_a = _make_result(
            "layer_a",
            [1.0, 0.0, 0.0, 0.0, 0.0],
            {"L1-01": [1.0, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_b = _make_result(
            "layer_b",
            [0.6, 0.0, 0.0, 0.0, 0.0],
            {"L1-04": [0.6, 0.0, 0.0, 0.0, 0.0]},
        )

        result = aggregate_scores(base_df, [layer_a, layer_b])
        # 행 0: L1-01 + L1-04 모두 위반
        assert result["flagged_rules"].iloc[0] == "L1-01,L1-04"
        # 행 1: 위반 없음
        assert result["flagged_rules"].iloc[1] == ""


# ── TestEdgeCases ─────────────────────────────────────────


class TestEdgeCases:
    """경계 케이스."""

    def test_score_clamped(self):
        """가중합 > 1.0 시 clip 확인."""
        df = pd.DataFrame({"val": range(3)})
        # 모든 레이어 scores=1.0이면 가중합=1.0 (정상). 가중치 합이 1 초과하도록 커스텀.
        layer_a = _make_result("layer_a", [1.0, 1.0, 1.0], {"L1-01": [1.0, 1.0, 1.0]})
        layer_b = _make_result("layer_b", [1.0, 1.0, 1.0], {"L4-01": [1.0, 1.0, 1.0]})
        weights = {"layer_a": 0.8, "layer_b": 0.8}  # 합 1.6

        result = aggregate_scores(df, [layer_a, layer_b], weights=weights)
        assert result["anomaly_score"].iloc[0] == pytest.approx(1.0)

    def test_preserves_original_index(self):
        """비연속 인덱스 [10, 20, 30] 보존."""
        df = pd.DataFrame({"val": [1, 2, 3]}, index=[10, 20, 30])
        layer_a = _make_result(
            "layer_a",
            [0.5, 0.0, 0.0],
            {"L1-01": [0.5, 0.0, 0.0]},
            index=[10, 20, 30],
        )

        result = aggregate_scores(df, [layer_a])
        assert list(result.index) == [10, 20, 30]

    def test_l101_split_score_is_weighted_in_row_anomaly_score(self):
        """L1-01 split score contributes through the L1 family weight."""
        df = pd.DataFrame({"val": range(2)})
        details = pd.DataFrame({"L1-01": [0.15, 0.90]}, index=df.index)
        layer_a = DetectionResult(
            track_name="layer_a",
            flagged_indices=[0, 1],
            scores=details.max(axis=1),
            rule_flags=[RuleFlag("L1-01", "UnbalancedEntry", 5, 2, len(df))],
            details=details,
            metadata={"elapsed": 0.01, "skipped_rules": []},
            warnings=[],
        )

        result = aggregate_scores(df, [layer_a])

        assert result["anomaly_score"].iloc[0] == pytest.approx(0.15 * 0.40)
        assert result["anomaly_score"].iloc[1] == pytest.approx(0.90 * 0.40)


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
    layer_a = _make_result("layer_a", a03 or z, {"L1-03": a03 or z})
    layer_b_details = {
        "L1-05": b06 or z,
        "L1-07": b09 or z,
    }
    b_scores = [max(b06_v, b09_v) for b06_v, b09_v in
                zip(layer_b_details["L1-05"], layer_b_details["L1-07"])]
    layer_b = _make_result("layer_b", b_scores, layer_b_details)
    layer_c_details = {
        "L3-04": c01 or z,
        "L3-08": c06 or z,
        "L4-03": c08 or z,
        "L4-04": c09 or z,
    }
    c_scores = [max(vals) for vals in zip(*layer_c_details.values())]
    layer_c = _make_result("layer_c", c_scores, layer_c_details)
    benford = _make_result("benford", z, {"L4-02": z})
    return [layer_a, layer_b, layer_c, benford]


class TestTopsideDetection:
    """Top-side JE internal score feature."""

    def test_all_conditions_met(self):
        """수기 + 5개 가점 전부 → topside_score 만점."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        layers = _topside_layers(
            c01=[0.6] * 5, b06=[0.6] * 5,
            a03=[0.6] * 5, c08=[0.6] * 5, c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(1.0)

    def test_threshold_boundary(self):
        """수기 + 정확히 2개 가점 → topside_score 0.4."""
        df = pd.DataFrame({"is_manual_je": [True, False, True, True, True]})
        layers = _topside_layers(
            c01=[0.6, 0.0, 0.6, 0.0, 0.0],
            c08=[0.6, 0.0, 0.6, 0.0, 0.0],
        )
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.4)
        # 행 1: 자동 + L3-04 + L4-03 = 0점 (게이트키퍼) → 미플래그
        assert "L2-05" not in result["flagged_rules"].iloc[1]

    def test_below_threshold(self):
        """수기 + 1개 가점만 → L2-05 미플래그."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        layers = _topside_layers(c01=[0.6] * 5)  # 가점 1개만
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]

    def test_automated_je_blocked(self):
        """자동 전표 + 5개 가점 전부 → L2-05 미플래그 (게이트키퍼 핵심 테스트)."""
        df = pd.DataFrame({"is_manual_je": [False] * 5})
        layers = _topside_layers(
            c01=[0.6] * 5, b06=[0.6] * 5,
            a03=[0.6] * 5, c08=[0.6] * 5, c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        # Why: 자동 전표는 가점 만점이어도 Top-side JE 아님
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.0)

    def test_no_manual_column(self):
        """is_manual_je 컬럼 없음 → 전체 0점 (안전 차단)."""
        df = pd.DataFrame({"val": range(5)})  # is_manual_je 없음
        layers = _topside_layers(
            c01=[0.6] * 5, b06=[0.6] * 5,
            a03=[0.6] * 5, c08=[0.6] * 5, c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.0)

    def test_missing_layers(self):
        """일부 레이어 없음 → 해당 조건 0점, 에러 없음."""
        df = pd.DataFrame({"is_manual_je": [True] * 3})
        # layer_a, layer_b 없이 layer_c만 전달
        layer_c = _make_result("layer_c", [0.6] * 3, {
            "L3-04": [0.6] * 3, "L4-03": [0.6] * 3, "L3-08": [0.2] * 3,
        })
        benford = _make_result("benford", [0.0] * 3, {"L4-02": [0.0] * 3})
        result = aggregate_scores(df, [layer_c, benford])
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.6)

    def test_topside_score_column(self):
        """결과에 topside_score 컬럼 존재 (0.0~1.0 범위)."""
        df = pd.DataFrame({"val": range(5)})
        layers = _topside_layers()
        result = aggregate_scores(df, layers)
        assert "topside_score" in result.columns
        assert result["topside_score"].between(0.0, 1.0).all()

    def test_flagged_rules_not_appended(self):
        """Top-side score does not append L2-05 to flagged_rules."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        # L1-03 + L3-04 + L4-03 → 기존 플래그 + L2-05
        layers = _topside_layers(
            a03=[0.6] * 5, c01=[0.6] * 5, c08=[0.6] * 5,
        )
        result = aggregate_scores(df, layers)
        rules = result["flagged_rules"].iloc[0]
        assert "L1-03" in rules
        assert "L2-05" not in rules

    def test_combined_with_auto_escalation(self):
        """auto_escalation과 topside 동시 적용 시 충돌 없음."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        # L1-01 위반(1개) + L1-05·L1-07 위반(2개) → auto_escalation 트리거
        # + L3-04 + L4-03 → topside 트리거
        layer_a = _make_result("layer_a", [0.4] * 5, {"L1-01": [0.4] * 5, "L1-03": [0.4] * 5})
        layer_b = _make_result("layer_b", [0.6] * 5, {"L1-05": [0.6] * 5, "L1-07": [0.6] * 5})
        layer_c = _make_result("layer_c", [0.6] * 5, {"L3-04": [0.6] * 5, "L4-03": [0.6] * 5})
        benford = _make_result("benford", [0.0] * 5, {"L4-02": [0.0] * 5})
        result = aggregate_scores(df, [layer_a, layer_b, layer_c, benford])
        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert "L2-05" not in result["flagged_rules"].iloc[0]


# ── TestMLWeights ────────────────────────────────────────


class TestMLWeights:
    """ML 트랙 포함 가중합."""

    def test_ml_weights_sum_to_one(self):
        """LAYER_WEIGHTS_WITH_ML 합계 = 1.0."""
        assert sum(LAYER_WEIGHTS_WITH_ML.values()) == pytest.approx(1.0)

    def test_ml_tracks_included(self, base_df):
        """ML 트랙 결과가 가중합에 반영."""
        layer_a = _make_result("layer_a", [0.5] * 5, {"L1-01": [0.5] * 5})
        ml_unsup = _make_result("ml_unsupervised", [0.8] * 5, {"ML02": [0.8] * 5})
        result = aggregate_scores(
            base_df, [layer_a, ml_unsup],
            weights=LAYER_WEIGHTS_WITH_ML,
        )
        expected = (
            0.5 * LAYER_WEIGHTS_WITH_ML[Layer.LAYER_A]
            + 0.8 * LAYER_WEIGHTS_WITH_ML[Layer.ML_UNSUPERVISED]
        )
        assert result["anomaly_score"].iloc[0] == pytest.approx(expected)

    def test_ml_tracks_ignored_without_ml_weights(self, base_df):
        """기본 LAYER_WEIGHTS 사용 시 ML 트랙 0점 처리."""
        layer_a = _make_result("layer_a", [0.5] * 5, {"L1-01": [0.5] * 5})
        ml_unsup = _make_result("ml_unsupervised", [0.8] * 5, {"ML02": [0.8] * 5})
        result = aggregate_scores(base_df, [layer_a, ml_unsup])
        # ML 트랙은 기본 L1/L2/L3/L4 가중치에 없으므로 무시됨
        assert result["anomaly_score"].iloc[0] == pytest.approx(
            0.5 * RULE_LEVEL_WEIGHTS["L1"]
        )

    def test_cold_start_no_ml_results(self, base_df, four_layer_results):
        """ML 결과 없이 LAYER_WEIGHTS_WITH_ML 적용 → ML 트랙 0점, 에러 없음."""
        from src.detection.constants import LAYER_WEIGHTS_WITH_ML
        result = aggregate_scores(
            base_df, four_layer_results,
            weights=LAYER_WEIGHTS_WITH_ML,
        )
        assert (result["anomaly_score"] >= 0).all()
        assert (result["anomaly_score"] <= 1).all()
