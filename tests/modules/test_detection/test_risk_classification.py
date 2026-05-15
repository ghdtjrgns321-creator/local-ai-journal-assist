"""행 단위 RISK_THRESHOLDS 재설정 (§9.4) 회귀 테스트.

권고 B(HIGH=0.50, MEDIUM=0.25, LOW=0.10)가 constants.py에 적용된 뒤
classify_risk_level과 _apply_policy_risk_floors의 경계/충돌을 점검한다.

근거: artifacts/phase1_score_band_audit.md §5-1, phase1_score_band_audit_after.md
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.constants import RISK_THRESHOLDS, RiskLevel
from src.detection.score_aggregator import aggregate_scores, classify_risk_level

# ── Threshold contract ──────────────────────────────────────


class TestNewThresholdValues:
    """권고 B 임계값이 코드 상수에 반영됐는지 단순 확인."""

    def test_high_threshold_matches_recommendation_b(self):
        assert RISK_THRESHOLDS[RiskLevel.HIGH] == pytest.approx(0.50)

    def test_medium_threshold_matches_recommendation_b(self):
        assert RISK_THRESHOLDS[RiskLevel.MEDIUM] == pytest.approx(0.25)

    def test_low_threshold_matches_recommendation_b(self):
        assert RISK_THRESHOLDS[RiskLevel.LOW] == pytest.approx(0.10)

    def test_thresholds_strictly_descending(self):
        assert (
            RISK_THRESHOLDS[RiskLevel.HIGH]
            > RISK_THRESHOLDS[RiskLevel.MEDIUM]
            > RISK_THRESHOLDS[RiskLevel.LOW]
            > 0.0
        )


# ── Boundary classification ─────────────────────────────────


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, RiskLevel.NORMAL),
        (0.05, RiskLevel.NORMAL),
        (0.099, RiskLevel.NORMAL),
        (0.10, RiskLevel.LOW),
        (0.20, RiskLevel.LOW),
        (0.249, RiskLevel.LOW),
        (0.25, RiskLevel.MEDIUM),
        (0.40, RiskLevel.MEDIUM),
        (0.499, RiskLevel.MEDIUM),
        (0.50, RiskLevel.HIGH),
        (0.75, RiskLevel.HIGH),
        (1.0, RiskLevel.HIGH),
    ],
)
def test_classify_risk_level_recommendation_b_boundaries(score: float, expected: str) -> None:
    """권고 B 경계 12개 점수가 정확한 등급으로 분류되는지 확인."""

    result = classify_risk_level(pd.Series([score]))
    assert result.iloc[0] == expected


# ── Policy floor compatibility ──────────────────────────────


def _df(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({"val": range(n)})


def _l105_immediate(raw: float) -> DetectionResult:
    details = pd.DataFrame({"L1-05": [raw, 0.0, 0.0, 0.0, 0.0]})
    return DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=pd.Series([raw, 0.0, 0.0, 0.0, 0.0]),
        rule_flags=[RuleFlag("L1-05", "L1-05", 4, 1, 5)],
        details=details,
        metadata={
            "elapsed": 0.01,
            "skipped_rules": [],
            "row_annotations": {"L1-05": {0: {"bucket": "immediate", "score": raw}}},
        },
        warnings=[],
    )


def _l105_escalated_abnormal_time(raw: float) -> DetectionResult:
    details = pd.DataFrame({"L1-05": [raw, 0.0, 0.0, 0.0, 0.0]})
    return DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=pd.Series([raw, 0.0, 0.0, 0.0, 0.0]),
        rule_flags=[RuleFlag("L1-05", "L1-05", 4, 1, 5)],
        details=details,
        metadata={
            "elapsed": 0.01,
            "skipped_rules": [],
            "row_annotations": {"L1-05": {0: {"bucket": "escalated_abnormal_time", "score": raw}}},
        },
        warnings=[],
    )


class TestPolicyFloorCompatibility:
    """RISK_THRESHOLDS 인하 후에도 정책 floor가 HIGH 경계를 통과하는지 점검.

    근거: phase1_score_band_audit.md §2-3 — 정책 floor 4,894 행이 변동 없이
    HIGH 등급으로 노출돼야 한다.
    """

    def test_l105_immediate_still_classifies_high(self):
        """immediate floor = RISK_THRESHOLDS[HIGH]이므로 새 HIGH(0.50) 라인을 정확히 통과."""

        result = aggregate_scores(_df(), [_l105_immediate(0.80)])

        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= RISK_THRESHOLDS[RiskLevel.HIGH]
        assert result["risk_floor_reasons"].iloc[0] == "L1-05:immediate"

    def test_l105_escalated_abnormal_time_floor_dominates_high_threshold(self):
        """escalated_abnormal_time 고정 floor(0.75)가 새 HIGH(0.50)을 넘어 HIGH로 안착."""

        result = aggregate_scores(_df(), [_l105_escalated_abnormal_time(0.60)])

        assert result["risk_level"].iloc[0] == RiskLevel.HIGH
        assert result["anomaly_score"].iloc[0] >= 0.75
        assert result["risk_floor_reasons"].iloc[0] == "L1-05:escalated_abnormal_time"

    def test_anomaly_score_zero_stays_normal(self):
        """자연 점수 0인 행은 등급도 NORMAL로 유지."""

        result = classify_risk_level(pd.Series([0.0, 0.0, 0.0]))
        assert (result == RiskLevel.NORMAL).all()


# ── Distribution sanity ─────────────────────────────────────


class TestDistributionSanity:
    """권고 B 임계값에서 분포가 의미 있는 등급 분리를 만들어내는지 점검."""

    def test_uniform_distribution_split(self):
        """0~1 등간격 100점이 NORMAL/LOW/MEDIUM/HIGH로 적절히 나눠지는지."""

        scores = pd.Series([i / 100 for i in range(101)])
        levels = classify_risk_level(scores)
        counts = levels.value_counts()

        # 각 등급에 적어도 한 행은 잡혀야 한다 (분포가 한 등급으로 쏠리지 않음).
        for label in (RiskLevel.NORMAL, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH):
            assert counts.get(label, 0) > 0, f"{label} band missing"

        # HIGH 비율은 51% (0.50 이상). 권고 B 의도와 부합.
        assert counts[RiskLevel.HIGH] == 51
        # MEDIUM 비율은 25% (0.25 이상 0.50 미만).
        assert counts[RiskLevel.MEDIUM] == 25
        # LOW 비율은 15% (0.10 이상 0.25 미만).
        assert counts[RiskLevel.LOW] == 15
        # NORMAL 비율은 10% (0.10 미만).
        assert counts[RiskLevel.NORMAL] == 10
