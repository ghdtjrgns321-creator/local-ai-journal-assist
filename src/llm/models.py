"""LLM 응답 Pydantic 스키마 — 전처리 추천 결과의 데이터 계약.

Why: LLM JSON 응답을 검증하고, StrEnum으로 sklearn Pipeline 옵션과
1:1 대응시켜 타입 안전성을 확보한다.
tree_model/distance_model 분기로 1회 LLM 호출에 전 모델 전략 수령.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

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


# ── WU-25: 인사이트 + XAI 사유서 스키마 ──


class SignificantTxOpinion(BaseModel):
    """유의적 거래(L4-03 AND L4-01) 1건에 대한 LLM 보조 의견 (ISA 240 §32(c))."""

    document_id: str
    account: str
    amount: float
    business_rationale: str
    audit_flag: Literal["reasonable", "questionable", "high_risk"]


class BatchInsight(BaseModel):
    """감사 배치 전체 자연어 요약 + 유의적 거래 의견 (#78, #80)."""

    summary: str
    top_risks: list[str]
    significant_tx_opinions: list[SignificantTxOpinion]


class EntryNarrative(BaseModel):
    """개별 전표 1건의 XAI 위험 사유서 (#86)."""

    document_id: str
    rationale: str
    cited_rules: list[str]


class NarrativeBatch(BaseModel):
    """LLM 배치 응답 래퍼 — list[EntryNarrative]를 root로 반환하면 일부 모델이
    strict 스키마를 거부하므로 객체로 한 번 감싼다."""

    narratives: list[EntryNarrative]


# ── WU-30: 감사규칙 피드백 루프 스키마 ──
# Why: LLM이 새 데이터 패턴을 분석해 audit_rules.yaml 개선 제안을 생성하고,
#      사용자 승인 후 회사별 오버라이드에 기록하는 Data Flywheel의 입구.


class RuleCategory(StrEnum):
    """피드백 루프가 제안 가능한 룰 카테고리 — audit_rules.yaml 키와 1:1 대응."""

    MANUAL_SOURCE_CODES = "manual_source_codes"
    SUSPENSE_KEYWORDS = "suspense_keywords"
    SUSPENSE_ACCOUNT_CODES = "suspense_account_codes"
    REVENUE_ACCOUNT_PREFIXES = "revenue_account_prefixes"
    INTERCOMPANY_IDENTIFIERS = "intercompany_identifiers"


class EvidenceSample(BaseModel):
    """제안 근거가 되는 전표 1건의 요약 (3~5건이 제안당 첨부)."""

    document_id: str
    gl_account: str
    description: str
    debit_amount: float = 0.0
    credit_amount: float = 0.0


class IntercompanyPair(BaseModel):
    """IC 계정 쌍 — 문자열 평탄화 대신 중첩 JSON으로 주고받아 포맷 오류 차단."""

    receivable: str
    payable: str


class RuleSuggestion(BaseModel):
    """LLM이 제안하는 신규 룰 1건 + 근거.

    Why: proposed_value를 Union으로 두면 OpenAI strict 스키마가 복잡해진다.
         IC는 별도 intercompany_pair 필드로 분리하고, 일반 카테고리는 proposed_value만 쓴다.
         category로 분기해 둘 중 하나만 채운다 (UI/apply 측 검증).
    """

    category: RuleCategory
    proposed_value: str = ""  # 일반 카테고리용 (IC는 빈 문자열)
    intercompany_pair: IntercompanyPair | None = None  # IC 전용
    rationale: str
    evidence_samples: list[EvidenceSample] = Field(min_length=1, max_length=5)
    confidence: Literal["low", "medium", "high"]
    conflicts_with_existing: list[str] = Field(default_factory=list)


class RuleFeedbackReport(BaseModel):
    """1회 LLM 호출의 전체 응답 — 5개 카테고리 제안 + 메타."""

    suggestions: list[RuleSuggestion] = Field(default_factory=list)
    generated_at: str = ""  # ISO timestamp — 엔진이 주입
    sample_summary: dict[str, int] = Field(default_factory=dict)


# ── WU-28: 헤더 탐지 LLM 보조 스키마 ──


class HeaderLLMResponse(BaseModel):
    """헤더 행 재검증 응답 (header_detector._llm_header_check용).

    Why: 구조 스코어 < min_header_confidence(0.3)일 때만 LLM에 "이 후보 행이 진짜
    헤더인가?"를 물어 confidence를 보정한다. is_header=False면 0.0, True면 confidence
    값이 그대로 반환되어 structural score와 max() 합성된다.
    """

    is_header: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
