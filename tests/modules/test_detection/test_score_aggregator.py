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
    RISK_THRESHOLDS,
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
    metadata: dict | None = None,
) -> DetectionResult:
    """DetectionResult 간편 생성 헬퍼."""
    idx = index or list(range(len(scores)))
    scores_s = pd.Series(scores, index=idx, dtype=float)
    details_df = pd.DataFrame(details_dict, index=idx)
    flagged = scores_s[scores_s > 0].index.tolist()
    rule_flags = [
        RuleFlag(
            rule_id=col,
            rule_name=col,
            severity=3,
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
        metadata={"elapsed": 0.01, "skipped_rules": [], **(metadata or {})},
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
            ).normalized_score
            * RULE_LEVEL_WEIGHTS["L1"]
            + normalize_rule_evidence(
                rule_id="L3-04",
                evidence_type="timing_anomaly",
                severity=3,
                raw_value=0.4,
            ).normalized_score
            * RULE_LEVEL_WEIGHTS["L3"]
            + normalize_rule_evidence(
                rule_id="L4-01",
                evidence_type="statistical_outlier",
                severity=3,
                raw_value=0.6,
            ).normalized_score
            * RULE_LEVEL_WEIGHTS["L4"]
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
            "intercompany_exception_score",
            "intercompany_exception_reasons",
            "batch_combo_score",
            "batch_combo_reasons",
            "work_scope_combo_score",
            "work_scope_combo_reasons",
            "topside_score",
        ]

    def test_l301_total_score_preserves_raw_reason_order(self):
        """L3-01 exact deny hit should outrank category and strict review hits."""
        df = pd.DataFrame({"val": range(3)})
        detection_result = _make_result(
            "layer_a",
            [0.65, 0.45, 0.40],
            {"L3-01": [0.65, 0.45, 0.40]},
            index=[0, 1, 2],
        )

        result = aggregate_scores(df, [detection_result])

        assert result["anomaly_score"].tolist() == pytest.approx(
            [
                0.65 * 0.6 * 0.75 * RULE_LEVEL_WEIGHTS["L3"],
                0.45 * 0.6 * 0.75 * RULE_LEVEL_WEIGHTS["L3"],
                0.40 * 0.6 * 0.75 * RULE_LEVEL_WEIGHTS["L3"],
            ]
        )
        assert result["anomaly_score"].iloc[0] > result["anomaly_score"].iloc[1]
        assert result["anomaly_score"].iloc[1] > result["anomaly_score"].iloc[2]
        assert result["risk_level"].tolist() == [RiskLevel.NORMAL] * 3

    def test_l103_bucket_scores_are_monotonic_in_rule_level_score(self, base_df):
        """L1-03 split scores should survive PHASE1 rule-level aggregation."""
        df = base_df.iloc[:4].copy()
        details = pd.DataFrame({"L1-03": [0.60, 0.70, 0.75, 0.80]}, index=df.index)
        layer_a = DetectionResult(
            track_name="layer_a",
            flagged_indices=df.index.tolist(),
            scores=details["L1-03"],
            rule_flags=[RuleFlag("L1-03", "InvalidAccount", 3, 4, len(df))],
            details=details,
            metadata={
                "row_annotations": {
                    "L1-03": {
                        0: {"bucket": "unknown_account", "score": 0.60},
                        1: {"bucket": "unknown_account_family", "score": 0.70},
                        2: {"bucket": "malformed_account", "score": 0.75},
                        3: {"bucket": "placeholder_or_reserved", "score": 0.80},
                    }
                }
            },
        )

        result = aggregate_scores(df, [layer_a])

        assert result["anomaly_score"].tolist() == sorted(result["anomaly_score"].tolist())
        assert result["anomaly_score"].iloc[3] > result["anomaly_score"].iloc[0]

    def test_l307_bucket_scores_are_monotonic_in_rule_level_score(self, base_df):
        """L3-07 gap buckets should not invert when folded into PHASE1 scoring."""
        df = base_df.iloc[:3].copy()
        details = pd.DataFrame({"L3-07": [0.45, 0.60, 0.75]}, index=df.index)
        layer_c = DetectionResult(
            track_name="layer_c",
            flagged_indices=df.index.tolist(),
            scores=details["L3-07"],
            rule_flags=[RuleFlag("L3-07", "Posting-Document Date Gap", 3, 3, len(df))],
            details=details,
            metadata={
                "row_annotations": {
                    "L3-07": {
                        0: {"bucket": "late_moderate_gap", "score": 0.45},
                        1: {"bucket": "late_large_gap", "score": 0.60},
                        2: {"bucket": "late_extreme_gap", "score": 0.75},
                    }
                }
            },
        )

        result = aggregate_scores(df, [layer_c])

        assert result["anomaly_score"].tolist() == pytest.approx([0.0495, 0.0675, 0.09])
        assert result["anomaly_score"].tolist() == sorted(result["anomaly_score"].tolist())

    def test_l306_human_after_hours_outscores_system_context_in_phase1(self, base_df):
        """L3-06 raw bands should keep their order after PHASE1 aggregation."""
        df = base_df.iloc[:3].copy()
        details = pd.DataFrame({"L3-06": [0.20, 0.45, 0.0]}, index=df.index)
        layer_c = DetectionResult(
            track_name="layer_c",
            flagged_indices=[0, 1],
            scores=details["L3-06"],
            rule_flags=[RuleFlag("L3-06", "AfterHoursPosting", 2, 2, len(df))],
            details=details,
            metadata={
                "row_annotations": {
                    "L3-06": {
                        0: {"bucket": "normal_system_context", "score": 0.20},
                        1: {"bucket": "confirmed_after_hours", "score": 0.45},
                    }
                }
            },
        )

        result = aggregate_scores(df, [layer_c])

        assert result["anomaly_score"].iloc[0] < result["anomaly_score"].iloc[1]
        assert result["risk_level"].tolist() == ["Normal", "Normal", "Normal"]

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
            ).normalized_score
            * RULE_LEVEL_WEIGHTS["L1"]
            + normalize_rule_evidence(
                rule_id="L3-04",
                evidence_type="timing_anomaly",
                severity=3,
                raw_value=0.5,
            ).normalized_score
            * RULE_LEVEL_WEIGHTS["L3"]
            + normalize_rule_evidence(
                rule_id="L4-01",
                evidence_type="statistical_outlier",
                severity=3,
                raw_value=0.5,
            ).normalized_score
            * RULE_LEVEL_WEIGHTS["L4"]
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
        assert immediate_score * RULE_LEVEL_WEIGHTS["L1"] < RISK_THRESHOLDS[RiskLevel.HIGH]
        assert result["anomaly_score"].iloc[1] == pytest.approx(RISK_THRESHOLDS[RiskLevel.HIGH])
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

    def test_l204_review_candidate_scores_without_confirmed_flag(self, base_df):
        details = pd.DataFrame({"L2-04": [0.0, 0.80, 0.0, 0.0, 0.0]})
        layer_b = DetectionResult(
            track_name="layer_b",
            flagged_indices=[1],
            scores=pd.Series([0.0, 0.80, 0.0, 0.0, 0.0]),
            rule_flags=[
                RuleFlag(
                    rule_id="L2-04",
                    rule_name="L2-04",
                    severity=4,
                    flagged_count=1,
                    total_count=5,
                )
            ],
            details=details,
            metadata={
                "elapsed": 0.01,
                "skipped_rules": [],
                "row_annotations": {
                    "L2-04": {
                        0: {
                            "queue_label": "review",
                            "confidence_band": "medium",
                            "review_score": 0.65,
                        },
                        1: {
                            "queue_label": "immediate",
                            "confidence_band": "high",
                            "score": 0.80,
                        },
                    }
                },
            },
            warnings=[],
        )

        result = aggregate_scores(base_df, [layer_b])

        review_score = normalize_rule_evidence(
            rule_id="L2-04",
            evidence_type="logic_mismatch",
            severity=4,
            raw_value=0.65,
            display_label="review",
        ).normalized_score
        assert result["anomaly_score"].iloc[0] == pytest.approx(
            review_score * RULE_LEVEL_WEIGHTS["L2"]
        )
        assert result["flagged_rules"].iloc[0] == ""
        assert result["review_rules"].iloc[0] == "L2-04"
        assert result["flagged_rules"].iloc[1] == "L2-04"
        assert result["review_rules"].iloc[1] == ""

    # ── TestClassifyRiskLevel ─────────────────────────────────

    def test_l302_population_stays_review_rule_but_scores_low(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.0, 0.60, 0.0, 0.0, 0.0],
            {"L3-02": [0.0, 0.60, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L3-02": {
                0: {"bucket": "manual_population", "score": 0.35},
                1: {"bucket": "manual_priority", "score": 0.60},
            }
        }

        result = aggregate_scores(base_df, [layer_b])

        assert result["flagged_rules"].iloc[0] == ""
        assert result["review_rules"].iloc[0] == "L3-02"
        assert result["flagged_rules"].iloc[1] == "L3-02"
        assert result["review_rules"].iloc[1] == ""
        assert 0.0 < result["anomaly_score"].iloc[0] < result["anomaly_score"].iloc[1]

    def test_l106_score_bands_align_to_risk_floors(self, base_df):
        layer_b = DetectionResult(
            track_name="layer_b",
            flagged_indices=[0, 1, 2, 3],
            scores=pd.Series([0.50, 0.70, 0.80, 0.95, 0.0], index=base_df.index),
            rule_flags=[RuleFlag("L1-06", "L1-06", 4, 4, len(base_df))],
            details=pd.DataFrame(
                {"L1-06": [0.50, 0.70, 0.80, 0.95, 0.0]},
                index=base_df.index,
            ),
            metadata={
                "row_annotations": {
                    "L1-06": {
                        0: {"bucket": "direct_low", "score": 0.50},
                        1: {"bucket": "direct_medium", "score": 0.70},
                        2: {"bucket": "direct_high", "score": 0.80},
                        3: {"bucket": "direct_critical", "score": 0.95},
                    }
                }
            },
        )

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].tolist()[:4] == [
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.HIGH,
        ]
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.LOW]
        assert result["anomaly_score"].iloc[0] < RISK_THRESHOLDS[RiskLevel.MEDIUM]
        assert result["anomaly_score"].iloc[1] >= RISK_THRESHOLDS[RiskLevel.MEDIUM]
        assert result["anomaly_score"].iloc[1] < RISK_THRESHOLDS[RiskLevel.HIGH]
        assert result["anomaly_score"].iloc[2] >= RISK_THRESHOLDS[RiskLevel.HIGH]
        assert result["anomaly_score"].iloc[3] == pytest.approx(0.85)
        assert result["risk_floor_reasons"].iloc[1] == "L1-06:direct_medium"
        assert result["risk_floor_reasons"].iloc[2] == "L1-06:direct_high"
        assert result["risk_floor_reasons"].iloc[3] == "L1-06:direct_critical"


class TestClassifyRiskLevel:
    """위험 등급 분류 임계값. RISK_THRESHOLDS 기준 동적 검증."""

    def test_high_above_threshold(self):
        score = RISK_THRESHOLDS[RiskLevel.HIGH] + 0.05
        assert classify_risk_level(pd.Series([score])).iloc[0] == RiskLevel.HIGH

    def test_high_boundary(self):
        score = RISK_THRESHOLDS[RiskLevel.HIGH]
        assert classify_risk_level(pd.Series([score])).iloc[0] == RiskLevel.HIGH

    def test_medium_band(self):
        score = (RISK_THRESHOLDS[RiskLevel.MEDIUM] + RISK_THRESHOLDS[RiskLevel.HIGH]) / 2
        assert classify_risk_level(pd.Series([score])).iloc[0] == RiskLevel.MEDIUM

    def test_medium_boundary(self):
        score = RISK_THRESHOLDS[RiskLevel.MEDIUM]
        assert classify_risk_level(pd.Series([score])).iloc[0] == RiskLevel.MEDIUM

    def test_low_band(self):
        score = (RISK_THRESHOLDS[RiskLevel.LOW] + RISK_THRESHOLDS[RiskLevel.MEDIUM]) / 2
        assert classify_risk_level(pd.Series([score])).iloc[0] == RiskLevel.LOW

    def test_low_boundary(self):
        score = RISK_THRESHOLDS[RiskLevel.LOW]
        assert classify_risk_level(pd.Series([score])).iloc[0] == RiskLevel.LOW

    def test_normal_below_low(self):
        score = max(RISK_THRESHOLDS[RiskLevel.LOW] - 0.05, 0.0)
        assert classify_risk_level(pd.Series([score])).iloc[0] == RiskLevel.NORMAL


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
            scores,
            mode="quantile",
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
        layer_b.metadata["row_annotations"] = {"L1-05": {0: {"bucket": "escalated_materiality"}}}

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= 0.8
        assert result["risk_floor_reasons"].iloc[0] == "L1-05:escalated_materiality"

    def test_l109_manual_missing_date_gets_low_floor(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.55, 0.0, 0.0, 0.0, 0.0],
            {"L1-09": [0.55, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L1-09": {0: {"bucket": "single_control_gap", "score": 0.55}}
        }

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].iloc[0] == RiskLevel.LOW
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.LOW]
        assert result["risk_floor_reasons"].iloc[0] == "L1-09:manual_missing_date"

    def test_l109_material_missing_date_gets_medium_floor(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.70, 0.0, 0.0, 0.0, 0.0],
            {"L1-09": [0.70, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L1-09": {0: {"bucket": "material_control_gap", "score": 0.70}}
        }

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].iloc[0] == RiskLevel.MEDIUM
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.MEDIUM]
        assert result["risk_floor_reasons"].iloc[0] == "L1-09:material_missing_date"

    def test_l109_with_strong_l1_control_gets_high_floor(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.80, 0.0, 0.0, 0.0, 0.0],
            {
                "L1-09": [0.55, 0.0, 0.0, 0.0, 0.0],
                "L1-05": [0.80, 0.0, 0.0, 0.0, 0.0],
            },
        )
        layer_b.metadata["row_annotations"] = {
            "L1-09": {0: {"bucket": "single_control_gap", "score": 0.55}},
            "L1-05": {0: {"bucket": "immediate", "score": 0.80}},
        }

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.HIGH]
        assert "L1-09:corroborated_control" in result["risk_floor_reasons"].iloc[0]


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
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.MEDIUM]
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
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.HIGH]


# ── TestFlaggedRules ──────────────────────────────────────


class TestL101RiskFloors:
    def test_severe_imbalance_promotes_to_medium(self, base_df):
        layer_a = _make_result(
            "layer_a",
            [0.90, 0.0, 0.0, 0.0, 0.0],
            {"L1-01": [0.90, 0.0, 0.0, 0.0, 0.0]},
        )

        result = aggregate_scores(base_df, [layer_a])

        assert result["anomaly_score"].iloc[0] == pytest.approx(RISK_THRESHOLDS[RiskLevel.MEDIUM])
        assert result["risk_level"].iloc[0] == RiskLevel.MEDIUM
        assert result["risk_floor_reasons"].iloc[0] == "L1-01:severe_imbalance"

    def test_material_imbalance_sets_floor_reason(self, base_df):
        details = pd.DataFrame(
            {"L1-01": [0.65, 0.0, 0.0, 0.0, 0.0]},
            index=base_df.index,
        )
        layer_a = DetectionResult(
            track_name="layer_a",
            flagged_indices=[0],
            scores=details.max(axis=1),
            rule_flags=[RuleFlag("L1-01", "UnbalancedEntry", 5, 1, len(base_df))],
            details=details,
            metadata={"elapsed": 0.01, "skipped_rules": []},
        )

        result = aggregate_scores(base_df, [layer_a])

        # Why: natural normalized score (0.26)는 새 RISK_THRESHOLDS 하에서 MEDIUM 영역에
        # 자연 도달한다. 정책 floor는 최소 LOW 보장을 위한 안전망 역할로 남는다.
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.LOW]
        assert result["risk_level"].iloc[0] in {RiskLevel.LOW, RiskLevel.MEDIUM}
        assert result["risk_floor_reasons"].iloc[0] == "L1-01:material_imbalance"


class TestWorkScopeCorroboration:
    """L3-12 work-scope signal is promoted only with independent corroboration."""

    def test_l312_only_stays_low_score(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.0, 0.0, 0.0, 0.0, 0.0],
            {"L3-12": [0.0, 0.0, 0.0, 0.0, 0.0]},
            metadata={
                "row_annotations": {
                    "L3-12": {0: {"bucket": "compound_scope_concentration", "review_score": 0.65}}
                }
            },
        )

        result = aggregate_scores(base_df, [layer_b])

        assert result["work_scope_combo_score"].iloc[0] == pytest.approx(0.0)
        assert result["work_scope_combo_reasons"].iloc[0] == ""
        assert result["risk_level"].iloc[0] == RiskLevel.NORMAL
        assert result["flagged_rules"].iloc[0] == ""
        assert "L3-12" in result["review_rules"].iloc[0]

    def test_l312_plus_two_groups_promotes_medium(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.65, 0.0, 0.0, 0.0, 0.0],
            {
                "L3-12": [0.0, 0.0, 0.0, 0.0, 0.0],
                "L3-02": [0.60, 0.0, 0.0, 0.0, 0.0],
                "L3-10": [0.50, 0.0, 0.0, 0.0, 0.0],
            },
            metadata={
                "row_annotations": {
                    "L3-12": {0: {"bucket": "compound_scope_concentration", "review_score": 0.65}}
                }
            },
        )

        result = aggregate_scores(base_df, [layer_b])

        assert result["work_scope_combo_score"].iloc[0] == pytest.approx(0.4)
        assert result["work_scope_combo_reasons"].iloc[0] == (
            "manual_or_control,sensitive_or_amount"
        )
        assert result["risk_level"].iloc[0] == RiskLevel.MEDIUM
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.MEDIUM]

    def test_l312_plus_three_groups_promotes_high(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [0.65, 0.0, 0.0, 0.0, 0.0],
            {
                "L3-12": [0.0, 0.0, 0.0, 0.0, 0.0],
                "L3-02": [0.60, 0.0, 0.0, 0.0, 0.0],
                "L3-10": [0.50, 0.0, 0.0, 0.0, 0.0],
            },
            metadata={
                "row_annotations": {
                    "L3-12": {0: {"bucket": "compound_scope_concentration", "review_score": 0.65}}
                }
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
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.HIGH]


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
        # Why: 새 RISK_THRESHOLDS(0.50/0.25/0.10) 하에서 L1-01 severity=5 raw=0.90 자연 점수
        # (0.36)는 MEDIUM(0.25)을 자연 초과한다. severe_imbalance floor는 추가 클립 없음.
        assert result["anomaly_score"].iloc[1] >= RISK_THRESHOLDS[RiskLevel.MEDIUM]
        assert result["anomaly_score"].iloc[1] < RISK_THRESHOLDS[RiskLevel.HIGH]
        assert result["risk_level"].iloc[1] == RiskLevel.MEDIUM

    def test_l107_component_score_is_weighted_in_row_anomaly_score(self):
        """L1-07 component score contributes monotonically through the L1 family weight."""
        df = pd.DataFrame({"val": range(3)})
        details = pd.DataFrame({"L1-07": [0.70, 0.85, 0.95]}, index=df.index)
        layer_b = DetectionResult(
            track_name="layer_b",
            flagged_indices=[0, 1, 2],
            scores=details.max(axis=1),
            rule_flags=[RuleFlag("L1-07", "SkippedApproval", 4, 3, len(df))],
            details=details,
            metadata={"elapsed": 0.01, "skipped_rules": []},
            warnings=[],
        )

        result = aggregate_scores(df, [layer_b])

        assert result["anomaly_score"].tolist() == pytest.approx(
            [0.70 * 0.40, 0.85 * 0.40, 0.95 * 0.40]
        )
        assert result["anomaly_score"].is_monotonic_increasing


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
    b_scores = [
        max(b06_v, b09_v)
        for b06_v, b09_v in zip(layer_b_details["L1-05"], layer_b_details["L1-07"])
    ]
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
            c01=[0.6] * 5,
            b06=[0.6] * 5,
            a03=[0.6] * 5,
            c08=[0.6] * 5,
            c06=[0.2] * 5,
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
            c01=[0.6] * 5,
            b06=[0.6] * 5,
            a03=[0.6] * 5,
            c08=[0.6] * 5,
            c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        # Why: 자동 전표는 가점 만점이어도 Top-side JE 아님
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.0)

    def test_no_manual_column(self):
        """is_manual_je 컬럼 없음 → 전체 0점 (안전 차단)."""
        df = pd.DataFrame({"val": range(5)})  # is_manual_je 없음
        layers = _topside_layers(
            c01=[0.6] * 5,
            b06=[0.6] * 5,
            a03=[0.6] * 5,
            c08=[0.6] * 5,
            c06=[0.2] * 5,
        )
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.0)

    def test_missing_layers(self):
        """일부 레이어 없음 → 해당 조건 0점, 에러 없음."""
        df = pd.DataFrame({"is_manual_je": [True] * 3})
        # layer_a, layer_b 없이 layer_c만 전달
        layer_c = _make_result(
            "layer_c",
            [0.6] * 3,
            {
                "L3-04": [0.6] * 3,
                "L4-03": [0.6] * 3,
                "L3-08": [0.2] * 3,
            },
        )
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
            a03=[0.6] * 5,
            c01=[0.6] * 5,
            c08=[0.6] * 5,
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


class TestIntercompanyExceptionScoring:
    """L3-03 population signal and IC exception floors."""

    def test_l303_population_only_stays_low(self):
        """L3-03 단독은 PHASE1 모집단 신호로만 낮게 반영."""
        df = pd.DataFrame({"is_intercompany": [True]})
        layer_b = DetectionResult(
            track_name="layer_b",
            flagged_indices=[0],
            scores=pd.Series([0.4]),
            rule_flags=[RuleFlag("L3-03", "L3-03", 4, 1, 1)],
            details=pd.DataFrame({"L3-03": [0.4]}),
            metadata={"elapsed": 0.01, "skipped_rules": []},
            warnings=[],
        )

        result = aggregate_scores(df, [layer_b])

        assert result["anomaly_score"].iloc[0] < RISK_THRESHOLDS[RiskLevel.LOW]
        assert result["risk_level"].iloc[0] == RiskLevel.NORMAL
        assert result["intercompany_exception_score"].iloc[0] == pytest.approx(0.0)

    def test_ic01_exception_gets_medium_floor(self):
        """IC01 미대사 예외는 row-level 대표 점수에서도 Medium 이상 노출."""
        df = pd.DataFrame({"is_intercompany": [True]})
        layer_b = DetectionResult(
            track_name="layer_b",
            flagged_indices=[0],
            scores=pd.Series([0.4]),
            rule_flags=[RuleFlag("L3-03", "L3-03", 4, 1, 1)],
            details=pd.DataFrame({"L3-03": [0.4]}),
            metadata={"elapsed": 0.01, "skipped_rules": []},
            warnings=[],
        )
        intercompany = DetectionResult(
            track_name="intercompany",
            flagged_indices=[0],
            scores=pd.Series([0.6]),
            rule_flags=[RuleFlag("IC01", "IC01", 3, 1, 1)],
            details=pd.DataFrame({"IC01": [0.6]}),
            metadata={"elapsed": 0.01, "skipped_rules": []},
            warnings=[],
        )

        result = aggregate_scores(df, [layer_b, intercompany])

        assert result["anomaly_score"].iloc[0] == pytest.approx(RISK_THRESHOLDS[RiskLevel.MEDIUM])
        assert result["risk_level"].iloc[0] == RiskLevel.MEDIUM
        assert result["intercompany_exception_score"].iloc[0] == pytest.approx(
            RISK_THRESHOLDS[RiskLevel.MEDIUM]
        )
        assert result["intercompany_exception_reasons"].iloc[0] == "IC01"

    def test_single_ic02_exception_gets_low_floor(self):
        """IC02 단독 금액 차이는 Low floor로 표시."""
        df = pd.DataFrame({"is_intercompany": [True]})
        intercompany = DetectionResult(
            track_name="intercompany",
            flagged_indices=[0],
            scores=pd.Series([0.4]),
            rule_flags=[RuleFlag("IC02", "IC02", 2, 1, 1)],
            details=pd.DataFrame({"IC02": [0.4]}),
            metadata={"elapsed": 0.01, "skipped_rules": []},
            warnings=[],
        )

        result = aggregate_scores(df, [intercompany])

        assert result["anomaly_score"].iloc[0] == pytest.approx(RISK_THRESHOLDS[RiskLevel.LOW])
        assert result["risk_level"].iloc[0] == RiskLevel.LOW
        assert result["intercompany_exception_reasons"].iloc[0] == "IC02"

    def test_multiple_ic_exceptions_get_medium_floor(self):
        """금액 차이와 시차 이상이 같이 있으면 Medium floor로 승격."""
        df = pd.DataFrame({"is_intercompany": [True]})
        intercompany = DetectionResult(
            track_name="intercompany",
            flagged_indices=[0],
            scores=pd.Series([0.4]),
            rule_flags=[
                RuleFlag("IC02", "IC02", 2, 1, 1),
                RuleFlag("IC03", "IC03", 2, 1, 1),
            ],
            details=pd.DataFrame({"IC02": [0.4], "IC03": [0.4]}),
            metadata={"elapsed": 0.01, "skipped_rules": []},
            warnings=[],
        )

        result = aggregate_scores(df, [intercompany])

        assert result["anomaly_score"].iloc[0] == pytest.approx(RISK_THRESHOLDS[RiskLevel.MEDIUM])
        assert result["risk_level"].iloc[0] == RiskLevel.MEDIUM
        assert result["intercompany_exception_reasons"].iloc[0] == "IC02,IC03"


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
            base_df,
            [layer_a, ml_unsup],
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
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.5 * RULE_LEVEL_WEIGHTS["L1"])

    def test_cold_start_no_ml_results(self, base_df, four_layer_results):
        """ML 결과 없이 LAYER_WEIGHTS_WITH_ML 적용 → ML 트랙 0점, 에러 없음."""
        from src.detection.constants import LAYER_WEIGHTS_WITH_ML

        result = aggregate_scores(
            base_df,
            four_layer_results,
            weights=LAYER_WEIGHTS_WITH_ML,
        )
        assert (result["anomaly_score"] >= 0).all()
        assert (result["anomaly_score"] <= 1).all()
