"""Detection 모듈 — 12트랙(A/B/C/D/Timeseries/Duplicate/Intercompany/Relational/AccessAudit/ML×3 + Benford) 45개 룰 이상탐지.

Public API: BaseDetector(ABC), DetectionResult, RuleFlag, validate_input,
            Layer, RiskLevel, RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS, RISK_THRESHOLDS,
            aggregate_scores, classify_risk_level.
"""

from src.detection.access_audit_layer import AccessAuditDetector
from src.detection.anomaly_layer import AnomalyDetector
from src.detection.base import (
    BaseDetector,
    DetectionResult,
    RuleFlag,
    validate_input,
)
from src.detection.benford_detector import BenfordDetector
from src.detection.constants import (
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    RULE_CODES,
    SEVERITY_MAP,
    Layer,
    RiskLevel,
)
# Why: ensemble_detector는 joblib(ml dependency group)을 요구.
#      core 환경에서는 미설치이므로 graceful import — 미사용 시 None 노출.
try:
    from src.detection.ensemble_detector import EnsembleDetector
except ModuleNotFoundError:
    EnsembleDetector = None  # type: ignore[assignment]
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.fraud_layer import FraudLayer
from src.detection.integrity_layer import IntegrityDetector
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.relational_detector import RelationalDetector
from src.detection.score_aggregator import aggregate_scores, classify_risk_level
from src.detection.sequence_detector import SequenceDetector
from src.detection.supervised_detector import SupervisedDetector
from src.detection.tabular_transformer import TransformerDetector
from src.detection.timeseries_detector import TimeseriesDetector
from src.detection.trendbreak_detector import TrendBreakDetector
from src.detection.vae_detector import UnsupervisedDetector
from src.detection.variance_layer import VarianceDetector

__all__ = [
    "AccessAuditDetector",
    "AnomalyDetector",
    "BaseDetector",
    "BenfordDetector",
    "aggregate_scores",
    "classify_risk_level",
    "DetectionResult",
    "EnsembleDetector",
    "DuplicateDetector",
    "FraudLayer",
    "IntercompanyMatcher",
    "IntegrityDetector",
    "RelationalDetector",
    "Layer",
    "LAYER_WEIGHTS",
    "RISK_THRESHOLDS",
    "RULE_CODES",
    "RiskLevel",
    "RuleFlag",
    "SEVERITY_MAP",
    "SequenceDetector",
    "SupervisedDetector",
    "TimeseriesDetector",
    "TransformerDetector",
    "TrendBreakDetector",
    "UnsupervisedDetector",
    "validate_input",
    "VarianceDetector",
]
