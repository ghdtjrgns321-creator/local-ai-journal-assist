"""Detection 모듈 — 4레이어(A/B/C/D + Benford) 29개 룰 이상탐지.

Public API: BaseDetector(ABC), DetectionResult, RuleFlag, validate_input,
            Layer, RiskLevel, RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS, RISK_THRESHOLDS,
            aggregate_scores, classify_risk_level.
"""

from src.detection.base import (
    BaseDetector,
    DetectionResult,
    RuleFlag,
    validate_input,
)
from src.detection.constants import (
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    RULE_CODES,
    SEVERITY_MAP,
    Layer,
    RiskLevel,
)
from src.detection.anomaly_layer import AnomalyDetector
from src.detection.benford_detector import BenfordDetector
from src.detection.fraud_layer import FraudLayer
from src.detection.integrity_layer import IntegrityDetector
from src.detection.score_aggregator import aggregate_scores, classify_risk_level
from src.detection.variance_layer import VarianceDetector

__all__ = [
    "AnomalyDetector",
    "BaseDetector",
    "BenfordDetector",
    "aggregate_scores",
    "classify_risk_level",
    "DetectionResult",
    "FraudLayer",
    "IntegrityDetector",
    "Layer",
    "LAYER_WEIGHTS",
    "RISK_THRESHOLDS",
    "RULE_CODES",
    "RiskLevel",
    "RuleFlag",
    "SEVERITY_MAP",
    "validate_input",
    "VarianceDetector",
]
