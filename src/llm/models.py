"""LLM 응답 Pydantic 스키마 — 전처리 추천 결과의 데이터 계약.

Why: LLM JSON 응답을 검증하고, StrEnum으로 sklearn Pipeline 옵션과
1:1 대응시켜 타입 안전성을 확보한다.
tree_model/distance_model 분기로 1회 LLM 호출에 전 모델 전략 수령.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


# ── 전처리 전략 열거형 ──


class ImputerStrategy(StrEnum):
    """결측치 대체 전략."""

    MEDIAN = "median"
    MEAN = "mean"
    MOST_FREQUENT = "most_frequent"
    CONSTANT = "constant"
    FORWARD_FILL = "forward_fill"
    DROP = "drop"


class EncoderStrategy(StrEnum):
    """범주형 인코딩 전략."""

    ORDINAL = "ordinal"
    TARGET = "target"
    ONEHOT = "onehot"
    PASSTHROUGH = "passthrough"


class ScalerStrategy(StrEnum):
    """스케일링 전략."""

    STANDARD = "standard"
    MINMAX = "minmax"
    ROBUST = "robust"
    NONE = "none"


class OutlierStrategy(StrEnum):
    """이상치 처리 전략."""

    CLIP = "clip"
    LOG = "log"
    REMOVE = "remove"
    NONE = "none"


class ImbalanceStrategy(StrEnum):
    """불균형 대응 전략."""

    SMOTE = "smote"
    CLASS_WEIGHT = "class_weight"
    NONE = "none"


# ── 복합 모델 ──


class ModelGroupStrategy(BaseModel):
    """모델 그룹별 스케일링/이상치 전략.

    tree_model(XGBoost)과 distance_model(VAE/IF)은 스케일링 요구가 다르므로
    1회 LLM 호출로 양쪽 전략을 동시에 수령한다.
    """

    scaler: ScalerStrategy = ScalerStrategy.NONE
    scaler_reason: str = ""
    outlier: OutlierStrategy = OutlierStrategy.NONE
    outlier_reason: str = ""


class ColumnPreprocessing(BaseModel):
    """컬럼 1개에 대한 전처리 추천."""

    column: str
    dtype_group: str
    imputer: ImputerStrategy
    imputer_reason: str = ""
    encoder: EncoderStrategy = EncoderStrategy.PASSTHROUGH
    encoder_reason: str = ""
    tree_model: ModelGroupStrategy = Field(default_factory=ModelGroupStrategy)
    distance_model: ModelGroupStrategy = Field(default_factory=ModelGroupStrategy)


class PreprocessingAdvice(BaseModel):
    """전체 전처리 추천 결과.

    source 필드로 LLM 추천("llm")과 규칙 기반 폴백("rule_based")을 구분.
    대시보드에서 출처를 사용자에게 표시한다.
    """

    columns: list[ColumnPreprocessing]
    imbalance: ImbalanceStrategy = ImbalanceStrategy.NONE
    imbalance_reason: str = ""
    general_notes: list[str] = Field(default_factory=list)
    source: str = "llm"  # "llm" | "rule_based" — LLM 추천과 규칙 기반 폴백 구분
