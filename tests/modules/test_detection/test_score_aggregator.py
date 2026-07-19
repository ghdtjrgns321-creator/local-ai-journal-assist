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
    SEVERITY_MAP,
    Layer,
    RiskLevel,
)
from src.detection.rule_scoring import (
    EVIDENCE_STRENGTH_FACTOR,
    OFF_TIME_SET,
    SIGNAL_STRENGTH_MAP,
    normalize_rule_evidence,
)
from src.detection.score_aggregator import (
    _POLICY_LABEL_FLOORS,
    aggregate_scores,
    classify_risk_level,
)

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


def test_phase2_only_expected_missing_legacy_tracks_are_not_warnings(
    base_df: pd.DataFrame,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ml_unsup = _make_result("ml_unsupervised", [0.2] * 5, {"ML02": [0.2] * 5})

    with caplog.at_level("WARNING", logger="src.detection.score_aggregator"):
        aggregate_scores(
            base_df,
            [ml_unsup],
            weights=LAYER_WEIGHTS_WITH_ML,
            detection_scope="phase2_only",
        )

    assert "track 'layer_a' missing; treating as zero" not in caplog.text
    assert "track 'layer_b' missing; treating as zero" not in caplog.text
    assert "track 'layer_c' missing; treating as zero" not in caplog.text
    assert "track 'benford' missing; treating as zero" not in caplog.text
    assert "track 'ml_supervised' missing; treating as zero" not in caplog.text


def test_default_scope_missing_legacy_tracks_remain_warnings(
    base_df: pd.DataFrame,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ml_unsup = _make_result("ml_unsupervised", [0.2] * 5, {"ML02": [0.2] * 5})

    with caplog.at_level("WARNING", logger="src.detection.score_aggregator"):
        aggregate_scores(base_df, [ml_unsup], weights=LAYER_WEIGHTS_WITH_ML)

    assert "track 'layer_a' missing; treating as zero" in caplog.text


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

        # batch/work_scope/intercompany corroboration 컬럼 제거(2026-06-21): PHASE1-2 family 귀속.
        assert list(result.columns) == [
            "anomaly_score",
            "risk_level",
            "flagged_rules",
            "review_rules",
            "risk_floor_reasons",
            "topside_score",
        ]

    def test_l103_data_integrity_score_is_neutralized(self, base_df):
        """L1-03 is a data-integrity track rule, not row risk scoring."""
        df = base_df.iloc[:4].copy()
        details = pd.DataFrame({"L1-03": [1.0, 1.0, 1.0, 1.0]}, index=df.index)
        layer_a = DetectionResult(
            track_name="layer_a",
            flagged_indices=df.index.tolist(),
            scores=details["L1-03"],
            rule_flags=[RuleFlag("L1-03", "InvalidAccount", 3, 4, len(df))],
            details=details,
            metadata={
                "row_annotations": {
                    "L1-03": {
                        0: {"gl_account": "1999"},
                        1: {"gl_account": "9000"},
                        2: {"gl_account": "ABC"},
                        3: {"gl_account": "9999"},
                    }
                }
            },
        )

        result = aggregate_scores(df, [layer_a])

        assert result["anomaly_score"].tolist() == pytest.approx([0.0, 0.0, 0.0, 0.0])
        assert result["risk_level"].tolist() == [RiskLevel.NORMAL] * 4

    def test_ic01_sidecar_no_longer_floors_anomaly_score(self):
        """IC01(IC matcher)은 PHASE1-2 family 귀속 — row anomaly_score corroboration floor 폐기(2026-06-21).

        과거 high/review evidence sidecar 가 Medium/Low floor 를 걸었으나, IC 를 PHASE1-1
        통합점수에서 완전 제거하면서 floor 와 보조 컬럼을 모두 없앴다.
        """
        df = pd.DataFrame({"val": range(2)})
        ic = _make_result(
            "intercompany",
            [0.0, 0.0],
            {"IC01": [0.0, 0.0]},
            index=[0, 1],
            metadata={
                "row_sidecar": {"ic01_evidence_level": pd.Series(["high", ""], index=[0, 1])}
            },
        )

        result = aggregate_scores(df, [ic], detection_scope="phase2_only")

        assert result.loc[0, "anomaly_score"] == pytest.approx(0.0)
        assert result.loc[0, "risk_level"] == RiskLevel.NORMAL
        assert "intercompany_exception_score" not in result.columns

    def test_l307_binary_scores_are_uniform_in_rule_level_score(self, base_df):
        """L3-07 은 binary 통일(2026-06-20) — gap 크기 무관 동일 anomaly_score."""
        df = base_df.iloc[:3].copy()
        details = pd.DataFrame({"L3-07": [1.0, 1.0, 1.0]}, index=df.index)
        layer_c = DetectionResult(
            track_name="layer_c",
            flagged_indices=df.index.tolist(),
            scores=details["L3-07"],
            rule_flags=[RuleFlag("L3-07", "Posting-Document Date Gap", 3, 3, len(df))],
            details=details,
            metadata={},
        )

        result = aggregate_scores(df, [layer_c])

        scores = result["anomaly_score"].tolist()
        # binary: 모든 hit 동일 점수(등급 없음)
        assert len({round(s, 6) for s in scores}) == 1

    def test_l306_after_hours_source_context_scores_equally_in_phase1(self, base_df):
        """L3-06 is binary; source context must not discount after-hours rows."""
        df = base_df.iloc[:3].copy()
        details = pd.DataFrame({"L3-06": [1.0, 1.0, 0.0]}, index=df.index)
        layer_c = DetectionResult(
            track_name="layer_c",
            flagged_indices=[0, 1],
            scores=details["L3-06"],
            rule_flags=[RuleFlag("L3-06", "AfterHoursPosting", 2, 2, len(df))],
            details=details,
            metadata={
                "row_annotations": {
                    "L3-06": {
                        0: {"source": "automated", "score": 1.0},
                        1: {"source": "manual", "score": 1.0},
                    }
                }
            },
        )

        result = aggregate_scores(df, [layer_c])

        # OFF-TIME(L3-06)은 row anomaly_score 0 기여 — "서로 같다"만이 아니라 실제 0 임을 명시 검증.
        assert result["anomaly_score"].iloc[0] == pytest.approx(result["anomaly_score"].iloc[1])
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.0)
        assert result["anomaly_score"].iloc[1] == pytest.approx(0.0)
        assert result["anomaly_score"].iloc[2] == pytest.approx(0.0)

    def test_missing_layer(self, base_df):
        """3개만 전달 → 누락 레이어 0점 처리, 에러 없음."""
        layer_a = _make_result("layer_a", [0.5] * 5, {"L1-01": [0.5] * 5})
        layer_b = _make_result("layer_b", [0.5] * 5, {"L4-01": [0.5] * 5})
        layer_c = _make_result("layer_c", [0.5] * 5, {"L3-04": [0.5] * 5})
        # benford 누락

        result = aggregate_scores(base_df, [layer_a, layer_b, layer_c])
        expected = (
            normalize_rule_evidence(
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

    def test_l302_manual_entries_are_binary_flagged_rules(self, base_df):
        layer_b = _make_result(
            "layer_b",
            [1.0, 1.0, 0.0, 0.0, 0.0],
            {"L3-02": [1.0, 1.0, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L3-02": {
                0: {"score": 1.0, "source": "manual"},
                1: {"score": 1.0, "source": "adjustment"},
            }
        }

        result = aggregate_scores(base_df, [layer_b])

        assert result["flagged_rules"].iloc[0] == "L3-02"
        assert result["review_rules"].iloc[0] == ""
        assert result["flagged_rules"].iloc[1] == "L3-02"
        assert result["review_rules"].iloc[1] == ""
        assert result["anomaly_score"].iloc[0] == pytest.approx(result["anomaly_score"].iloc[1])

    def test_l106_standalone_not_force_escalated(self, base_df):
        # SOD_TOXIC_COMBINATIONS_GROUNDING §3: 직무분리(L1-06) RED 는 단독이면 LOW,
        # 행위신호와 조합될 때만 HIGH(겸직만으로 부정 단정 불가). 구 direct_* 강제 risk floor
        # 제거(2026-06-30) 후 L1-06 단독은 정책 floor 로 HIGH 승격되지 않고 정규 점수경로로만
        # 분류된다. 실 탐지기 출력(binary 1.0) 단독 입력으로 "강제 HIGH 없음"을 검증한다.
        layer_b = DetectionResult(
            track_name="layer_b",
            flagged_indices=[0, 1],
            scores=pd.Series([1.0, 1.0, 0.0, 0.0, 0.0], index=base_df.index),
            rule_flags=[RuleFlag("L1-06", "L1-06", 4, 4, len(base_df))],
            details=pd.DataFrame(
                {"L1-06": [1.0, 1.0, 0.0, 0.0, 0.0]},
                index=base_df.index,
            ),
            metadata={"row_annotations": {"L1-06": {0: {"signal_class": "red", "score": 1.0}}}},
        )

        result = aggregate_scores(base_df, [layer_b])

        # 강제 risk floor 미적용: L1-06:direct_* 사유가 더 이상 생기지 않는다
        assert not result["risk_floor_reasons"].str.contains("L1-06").any()
        # L1-06 단독은 HIGH 로 강제 승격되지 않는다(정규 점수 → HIGH 임계 미만)
        l106_rows = result.loc[[0, 1]]
        assert (l106_rows["risk_level"] != RiskLevel.HIGH).all()
        assert (l106_rows["anomaly_score"] < RISK_THRESHOLDS[RiskLevel.HIGH]).all()


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
        # 행 0: L1-01은 데이터 정합성 트랙이라 row risk에 기여하지 않고,
        # L4-01 단독 기여도도 Low threshold 미만이다.
        assert result["risk_level"].iloc[0] == RiskLevel.NORMAL


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

    def test_l105_escalated_high_risk_account_floor(self, base_df):
        """L1-05 escalated_high_risk_account 단독 floor가 0.80 이상으로 clip되고 HIGH로 승격."""
        layer_b = _make_result(
            "layer_b",
            [0.40, 0.0, 0.0, 0.0, 0.0],
            {"L1-05": [0.40, 0.0, 0.0, 0.0, 0.0]},
        )
        layer_b.metadata["row_annotations"] = {
            "L1-05": {0: {"bucket": "escalated_high_risk_account"}}
        }

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= 0.80
        assert result["risk_floor_reasons"].iloc[0] == "L1-05:escalated_high_risk_account"

    def test_l104_immediate_floor(self, base_df):
        """L1-04 raw 0.80 이상 → immediate floor 적용 + HIGH 승격."""
        layer_b = _make_result(
            "layer_b",
            [0.85, 0.0, 0.0, 0.0, 0.0],
            {"L1-04": [0.85, 0.0, 0.0, 0.0, 0.0]},
        )

        result = aggregate_scores(base_df, [layer_b])

        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.HIGH]
        assert "L1-04:immediate" in result["risk_floor_reasons"].iloc[0]

    def test_policy_label_floors_immediate_follows_risk_thresholds_high(self):
        """_POLICY_LABEL_FLOORS["immediate"] follows RISK_THRESHOLDS[HIGH]."""
        # Why: 향후 RISK_THRESHOLDS[HIGH]가 변경되면 immediate floor도 같이 따라가야 한다.
        # literal 0.50 하드코딩 회귀를 차단한다.
        assert _POLICY_LABEL_FLOORS["immediate"] == pytest.approx(RISK_THRESHOLDS[RiskLevel.HIGH])


class TestDataIntegrityTrackRules:
    def test_l101_does_not_promote_risk_level(self, base_df):
        layer_a = _make_result(
            "layer_a",
            [1.0, 0.0, 0.0, 0.0, 0.0],
            {"L1-01": [1.0, 0.0, 0.0, 0.0, 0.0]},
        )

        result = aggregate_scores(base_df, [layer_a])

        assert result["anomaly_score"].iloc[0] == pytest.approx(0.0)
        assert result["risk_level"].iloc[0] == RiskLevel.NORMAL
        assert result["risk_floor_reasons"].iloc[0] == ""

    def test_l103_does_not_contribute_row_anomaly_score(self, base_df):
        details = pd.DataFrame(
            {"L1-03": [1.0, 0.0, 0.0, 0.0, 0.0]},
            index=base_df.index,
        )
        layer_a = DetectionResult(
            track_name="layer_a",
            flagged_indices=[0],
            scores=details.max(axis=1),
            rule_flags=[RuleFlag("L1-03", "InvalidAccount", 3, 1, len(base_df))],
            details=details,
            metadata={"elapsed": 0.01, "skipped_rules": []},
        )

        result = aggregate_scores(base_df, [layer_a])

        assert result["anomaly_score"].iloc[0] == pytest.approx(0.0)
        assert result["risk_level"].iloc[0] == RiskLevel.NORMAL
        assert result["flagged_rules"].iloc[0] == "L1-03"


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

    def test_l101_uniform_score_does_not_affect_row_anomaly_score(self):
        """L1-01 is collected as data integrity, not row risk scoring."""
        df = pd.DataFrame({"val": range(2)})
        details = pd.DataFrame({"L1-01": [1.0, 1.0]}, index=df.index)
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

        assert result["anomaly_score"].tolist() == pytest.approx([0.0, 0.0])
        assert result["risk_level"].tolist() == [RiskLevel.NORMAL, RiskLevel.NORMAL]

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
        """수기 + 4개 가점 전부 → topside_score 만점."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        layers = _topside_layers(
            c01=[0.6] * 5,
            b06=[0.6] * 5,
            a03=[0.6] * 5,
            c08=[0.6] * 5,
        )
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(1.0)

    def test_threshold_boundary(self):
        """수기 + 정확히 2개 가점 → topside_score 0.5 (4개 조건 중 2개)."""
        df = pd.DataFrame({"is_manual_je": [True, False, True, True, True]})
        layers = _topside_layers(
            c01=[0.6, 0.0, 0.6, 0.0, 0.0],
            c08=[0.6, 0.0, 0.6, 0.0, 0.0],
        )
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.5)
        # 행 1: 자동 + L3-04 + L4-03 = 0점 (게이트키퍼) → 미플래그
        assert "L2-05" not in result["flagged_rules"].iloc[1]

    def test_below_threshold(self):
        """수기 + 1개 가점만 → L2-05 미플래그."""
        df = pd.DataFrame({"is_manual_je": [True] * 5})
        layers = _topside_layers(c01=[0.6] * 5)  # 가점 1개만
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]

    def test_automated_je_blocked(self):
        """자동 전표 + 4개 가점 전부 → L2-05 미플래그 (게이트키퍼 핵심 테스트)."""
        df = pd.DataFrame({"is_manual_je": [False] * 5})
        layers = _topside_layers(
            c01=[0.6] * 5,
            b06=[0.6] * 5,
            a03=[0.6] * 5,
            c08=[0.6] * 5,
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
        )
        result = aggregate_scores(df, layers)
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.0)

    def test_missing_layers(self):
        """일부 레이어 없음 → 해당 조건 0점, 에러 없음."""
        df = pd.DataFrame({"is_manual_je": [True] * 3})
        # layer_a, layer_b 없이 layer_c만 전달 → 4개 조건 중 period_end·high_amount 2개만 충족.
        layer_c = _make_result(
            "layer_c",
            [0.6] * 3,
            {
                "L3-04": [0.6] * 3,
                "L4-03": [0.6] * 3,
            },
        )
        benford = _make_result("benford", [0.0] * 3, {"L4-02": [0.0] * 3})
        result = aggregate_scores(df, [layer_c, benford])
        assert "L2-05" not in result["flagged_rules"].iloc[0]
        assert result["topside_score"].iloc[0] == pytest.approx(0.5)

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
        # ML 트랙은 기본 L1/L2/L3/L4 가중치에 없고, L1-01은 데이터 정합성 트랙이라 무시됨.
        assert result["anomaly_score"].iloc[0] == pytest.approx(0.0)

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


# ── TestNormalizationCoverage ─────────────────────────────────


def _single_rule_result(
    rule_id: str,
    raw_value: float,
    label: str | None = None,
) -> DetectionResult:
    """단일 룰 하나로 구성된 DetectionResult — registry severity 사용."""
    severity = SEVERITY_MAP[rule_id]
    details = pd.DataFrame({rule_id: [raw_value]})
    metadata: dict = {"elapsed": 0.01, "skipped_rules": []}
    if label is not None:
        metadata["row_annotations"] = {rule_id: {0: {"bucket": label, "score": raw_value}}}
    return DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=pd.Series([raw_value]),
        rule_flags=[RuleFlag(rule_id, rule_id, severity, 1, 1)],
        details=details,
        metadata=metadata,
        warnings=[],
    )


@pytest.mark.parametrize(
    "rule_id, evidence_type, raw_value, label",
    [
        # weak / medium / strong evidence_strength를 모두 거치는 registry 미커버 룰들.
        ("L1-02", "data_integrity_failure", 0.60, None),
        ("L1-08", "data_integrity_failure", 0.60, None),
        ("L2-01", "duplicate_or_outflow", 0.60, "close_band"),
        ("L2-02", "duplicate_or_outflow", 0.70, "reference_match"),
        ("L2-03", "duplicate_or_outflow", 0.60, None),
        ("L3-05", "timing_anomaly", 1.0, "weekend"),
        ("L3-09", "logic_mismatch", 0.60, "aging_60_90"),
        ("L3-11", "timing_anomaly", 0.60, None),
        ("L4-05", "timing_anomaly", 0.60, None),
    ],
)
def test_normalize_rule_values_covers_uncovered_rules(
    rule_id: str,
    evidence_type: str,
    raw_value: float,
    label: str | None,
):
    """registry 미커버 룰들의 raw → normalized 변환이 normalize_rule_evidence와 일치."""
    df = pd.DataFrame({"val": [0]})
    detection = _single_rule_result(rule_id, raw_value, label)

    result = aggregate_scores(df, [detection])

    severity = SEVERITY_MAP[rule_id]
    expected_normalized = normalize_rule_evidence(
        rule_id=rule_id,
        evidence_type=evidence_type,
        severity=severity,
        raw_value=raw_value,
        display_label=label,
    ).normalized_score
    level = rule_id.split("-", 1)[0]
    # OFF-TIME(L3-05·L3-06·L4-05)은 within-tier 정렬·UI 전용이라 row anomaly_score 기여 0.
    expected = (
        0.0
        if rule_id in {"L1-01", "L1-02", "L1-03"} or rule_id in OFF_TIME_SET
        else (expected_normalized * RULE_LEVEL_WEIGHTS[level])
    )
    assert result["anomaly_score"].iloc[0] == pytest.approx(expected, abs=1e-6)
    # 점수는 0이어도 표시용 flagged_rules 에는 남는다(UI 표시 유지).
    assert rule_id in result["flagged_rules"].iloc[0]


@pytest.mark.parametrize(
    "rule_id",
    ["L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d"],
)
def test_l203_reason_code_variants_each_aggregate_into_l2_family(rule_id: str):
    """L2-03 canonical + a~d 변형들은 L2 family 가중치를 통해 모두 anomaly_score에 기여."""
    df = pd.DataFrame({"val": [0]})
    detection = _single_rule_result(rule_id, 0.60)

    result = aggregate_scores(df, [detection])

    severity = SEVERITY_MAP[rule_id]
    expected_normalized = normalize_rule_evidence(
        rule_id=rule_id,
        evidence_type="duplicate_or_outflow",
        severity=severity,
        raw_value=0.60,
    ).normalized_score
    expected = expected_normalized * RULE_LEVEL_WEIGHTS["L2"]
    assert result["anomaly_score"].iloc[0] == pytest.approx(expected, abs=1e-6)
    assert result["flagged_rules"].iloc[0] == rule_id


def test_l203_variants_share_canonical_l2_family_weight():
    """L2-03 canonical + 변형 4개가 동시에 들어오면 max(normalized) * L2 weight."""
    df = pd.DataFrame({"val": [0]})
    details = pd.DataFrame(
        {
            "L2-03": [0.60],
            "L2-03a": [0.60],
            "L2-03b": [0.60],
            "L2-03c": [0.60],
            "L2-03d": [0.60],
        }
    )
    rule_flags = [RuleFlag(rid, rid, SEVERITY_MAP[rid], 1, 1) for rid in details.columns]
    detection = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=rule_flags,
        details=details,
        metadata={"elapsed": 0.01, "skipped_rules": []},
        warnings=[],
    )

    result = aggregate_scores(df, [detection])

    normalized_values = [
        normalize_rule_evidence(
            rule_id=rid,
            evidence_type="duplicate_or_outflow",
            severity=SEVERITY_MAP[rid],
            raw_value=0.60,
        ).normalized_score
        for rid in details.columns
    ]
    expected = max(normalized_values) * RULE_LEVEL_WEIGHTS["L2"]
    assert result["anomaly_score"].iloc[0] == pytest.approx(expected, abs=1e-6)


# ── TestSignalStrengthMapping ─────────────────────────────────


class TestEvidenceStrengthFactor:
    """evidence_strength → severity-independent multiplier 매핑."""

    @pytest.mark.parametrize(
        "evidence_strength, expected_factor",
        [
            ("weak", 0.45),
            ("medium", 0.75),
            ("strong", 1.0),
            ("info", 0.25),
        ],
    )
    def test_default_signal_strength_maps_weak_medium_strong(
        self,
        evidence_strength: str,
        expected_factor: float,
    ):
        """EVIDENCE_STRENGTH_FACTOR가 weak/medium/strong/info를 0.45/0.75/1.0/0.25로 매핑."""
        # Why: rule_scoring에서 normalize_rule_evidence가 이 factor를 곱하므로,
        # 값이 바뀌면 모든 rule normalized_score가 전역 회귀된다.
        assert EVIDENCE_STRENGTH_FACTOR[evidence_strength] == pytest.approx(expected_factor)

    @pytest.mark.parametrize(
        "label, expected_strength",
        [
            ("high", 1.0),
            ("critical", 1.0),
            ("medium", 0.6),
            ("moderate", 0.6),
            ("low", 0.3),
            ("info", 0.2),
            ("normal", 0.0),
        ],
    )
    def test_signal_strength_map_canonical_labels(
        self,
        label: str,
        expected_strength: float,
    ):
        """SIGNAL_STRENGTH_MAP의 기준 label이 기대 signal strength로 매핑."""
        assert SIGNAL_STRENGTH_MAP[label] == pytest.approx(expected_strength)
