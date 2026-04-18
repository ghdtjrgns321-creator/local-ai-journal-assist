"""Detection 모듈 공용 상수 — 38개 룰 메타데이터 + 레이어/위험 등급 열거형.

Why: 룰 ID·이름·심각도를 한 곳에서 관리하여 하드코딩 제거.
     EDA·대시보드 등 외부 모듈에서도 import하여 일관성 유지.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# ── 열거형 ────────────────────────────────────────────────────


class RiskLevel(StrEnum):
    """위험 등급 — score_aggregator가 최종 분류에 사용."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    NORMAL = "Normal"


class Layer(StrEnum):
    """탐지 레이어 — DetectionResult.track_name과 1:1 대응."""

    LAYER_A = "layer_a"
    LAYER_B = "layer_b"
    LAYER_C = "layer_c"
    BENFORD = "benford"  # C07과 별도, 전체 분포 판정 (가중치 0.15 독립)
    LAYER_D = "layer_d"  # 전기 대비 변동 탐지 (기존회사 전용)
    DUPLICATE = "duplicate"  # Exact + Fuzzy 중복 전표 탐지 (WU-05)
    TIMESERIES = "timeseries"  # 시계열 거래 급증/빈도 이상 (WU-06)
    INTERCOMPANY = "intercompany"  # 내부거래 매칭 (WU-07)
    RELATIONAL = "relational"  # 관계 기반 이상 탐지 (WU-08)
    ML_SUPERVISED = "ml_supervised"  # 지도학습 (WU-01)
    ML_UNSUPERVISED = "ml_unsupervised"  # 비지도학습 VAE+IF (WU-02)
    ML_TRANSFORMER = "ml_transformer"  # FT-Transformer 지도학습 (WU-01b)
    ML_SEQUENCE = "ml_sequence"  # BiLSTM+Attention 시퀀스 탐지 (WU-01c)
    ENSEMBLE = "ensemble"  # Stacking Meta-Learner 앙상블 (WU-03)
    ACCESS_AUDIT = "access_audit"  # 접근감사/감사추적 (WU-15)
    EVIDENCE = "evidence"  # 증빙/컷오프/금액 탐지 (WU-14)
    TRENDBREAK = "trendbreak"  # 회계추정치 편의 탐지 (WU-16)
    GRAPH = "graph"  # 그래프 기반 순환/이전가격 탐지 (WU-22)
    NLP = "nlp"  # 적요 NLP + 임베딩 기반 의미 탐지 (WU-21)


class DetectorMaturity(StrEnum):
    """탐지기 운영 성숙도."""

    PRODUCTION = "production"
    BETA = "beta"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class DetectorProfile:
    """탐지기 운영 메타데이터."""

    track_name: str
    display_name: str
    maturity: DetectorMaturity
    default_enabled: bool
    activation_requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetectorExplanationProfile:
    """탐지기 공통 설명 메타데이터."""

    track_name: str
    summary: str
    why_it_flagged: str
    used_columns: tuple[str, ...] = ()
    false_positive_risks: tuple[str, ...] = ()
    auditor_checks: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleExplanation:
    """룰별 설명 메타데이터."""

    rule_id: str
    plain_reason: str
    used_columns: tuple[str, ...] = ()
    false_positive_risks: tuple[str, ...] = ()
    auditor_checks: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


# ── 룰 메타데이터 ────────────────────────────────────────────

# Why: DETECTION_RULES.md Phase 1 테이블에서 추출.
#      룰 추가 시 여기만 수정하면 base.py·Layer·대시보드에 자동 반영.

RULE_CODES: dict[str, str] = {
    # Layer A: 데이터 무결성
    "A01": "차대변 균형",
    "A02": "필수필드 누락",
    "A03": "무효 계정",
    # Layer B: 부정 탐지
    "B01": "매출 이상 변동",
    "B02": "승인한도 직하",
    "B03": "승인한도 초과",
    "B04": "중복 지급",
    "B05": "중복 전표",
    "B05a": "중복 전표 (Exact)",
    "B05b": "중복 전표 (Fuzzy)",
    "B05c": "분할 거래",
    "B05d": "시차 중복",
    "B06": "자기 승인",
    "B07": "직무분리 위반",
    "B08": "수기 전표",
    "B09": "승인 생략",
    "B10": "관계사 순환거래",
    "B11": "비용 자산화",
    "B19": "Top-side JE",  # 복합 룰: 수기(게이트키퍼) + C01/B06/B09/A03/C09/C08/C06 조합
    # Layer C: 이상 징후
    "C01": "기말 대규모",
    "C02": "주말 전기",
    "C03": "심야 전기",
    "C04": "소급 전기",
    "C05": "기간 불일치",
    "C06": "위험 적요",
    "C07": "Benford 위반",
    "C08": "이상 고액",
    "C09": "비정상 계정조합",
    "C10": "가수금 장기체류",
    "C11": "역분개 패턴",
    "C12": "비정상시간 집중입력",
    "C13": "배치 전표 이상",
    # Layer D: 전기 대비 변동
    "D01": "계정과목 집계 급변",
    "D02": "월별 분포 패턴 변화",
    # Timeseries: 시계열 탐지
    "TS01": "거래 급증",
    "TS02": "비정상 거래 주기",
    # Intercompany: 내부거래 매칭 (WU-07)
    "IC01": "미매칭 내부거래",
    "IC02": "내부거래 금액 불일치",
    "IC03": "내부거래 시차 이상",
    # Relational: 관계 기반 이상 탐지 (WU-08)
    "R01": "신규 거래처 대액 지급",
    "R02": "휴면 계정 활동",
    "R03": "IC 이전가격 이상",
    "R04": "문서 흐름 누락",
    # ML: 지도학습 탐지
    "ML01": "지도학습 이상 탐지",
    "ML02": "비지도학습 이상 탐지",
    "ML03": "FT-Transformer 이상 탐지",
    "ML04": "시퀀스 이상 탐지",
    # Ensemble: Stacking Meta-Learner (WU-03)
    "EN01": "앙상블 이상 탐지",
    # Access Audit: 접근감사/감사추적 (WU-15)
    "AA01": "전표 수정/삭제 이력",
    "AA02": "IP 비정상 접근",
    "AA03": "전표번호 연속성 갭",
    "AA04": "승인 프로세스 검증",
    # Evidence: 증빙/컷오프/금액 탐지 (WU-14)
    "EV01": "증빙 존재 확인",
    "EV02": "컷오프 검증",
    "EV03": "증빙 금액 불일치",
    # TrendBreak: 회계추정치 편의 탐지 (WU-16)
    "TB01": "추정치 부호 편향",
    "TB02": "추정치 범위 극단",
    # Graph: 그래프 기반 순환/이전가격 탐지 (WU-22)
    "GR01": "순환거래 탐지",
    "GR03": "그래프 이전가격 이상",
    # NLP: 적요 NLP + 임베딩 기반 의미 탐지 (WU-21)
    "NLP01": "헤더-계정 의미 불일치",
    "NLP02": "프로세스-계정 의미 불일치",
    "NLP03": "비정형 적요",
    "NLP04": "IC 적요 패턴 이상",
    "NLP05": "위험 키워드 동의어 우회",
}

SEVERITY_MAP: dict[str, int] = {
    "A01": 5, "A02": 2, "A03": 3,
    "B01": 5, "B02": 3, "B03": 3, "B04": 3, "B05": 3,
    "B05a": 3, "B05b": 3, "B05c": 4, "B05d": 3,
    "B06": 3, "B07": 4, "B08": 4, "B09": 4, "B10": 4, "B11": 4, "B19": 5,
    "C01": 3, "C02": 2, "C03": 2, "C04": 3, "C05": 4,
    "C06": 1, "C07": 2, "C08": 3, "C09": 2, "C10": 3, "C11": 4, "C12": 3, "C13": 3,
    "D01": 4, "D02": 3,
    "TS01": 4, "TS02": 2,
    "IC01": 3, "IC02": 2, "IC03": 2,
    "R01": 1, "R02": 2, "R03": 4, "R04": 1,
    "ML01": 4,
    "ML02": 4,
    "ML03": 4,
    "ML04": 4,
    "EN01": 5,
    "AA01": 4, "AA02": 3, "AA03": 3, "AA04": 4,
    "EV01": 4, "EV02": 3, "EV03": 3,
    # Why: ISA 540 경영진 편의 — 부호 편향은 직접적 징후 (D01급), 범위 극단은 간접 징후
    "TB01": 4, "TB02": 3,
    # Why: ISA 550 특수관계자 — 순환·이전가격 모두 B10과 동급의 부정 징후
    "GR01": 4, "GR03": 4,
    # Why: ISA 315/240 경제적 실질 — NLP01(header-계정)이 직접 징후, NLP05(은어)는 은폐 시도
    "NLP01": 4, "NLP02": 3, "NLP03": 2, "NLP04": 3, "NLP05": 3,
}


# ── 가중치·임계값 ────────────────────────────────────────────

LAYER_WEIGHTS: dict[Layer, float] = {
    Layer.LAYER_A: 0.15,
    Layer.LAYER_B: 0.45,
    Layer.LAYER_C: 0.25,
    Layer.BENFORD: 0.15,
}

# Why: 기존회사 트랙에서 Layer D 추가 시 가중치 재배분.
LAYER_WEIGHTS_WITH_PRIOR: dict[Layer, float] = {
    Layer.LAYER_A: 0.12,
    Layer.LAYER_B: 0.38,
    Layer.LAYER_C: 0.20,
    Layer.BENFORD: 0.12,
    Layer.LAYER_D: 0.18,
}

# Why: WU-06 시계열 트랙 추가에 따른 가중치 재배분.
LAYER_WEIGHTS_WITH_TIMESERIES: dict[Layer, float] = {
    Layer.LAYER_A: 0.13,
    Layer.LAYER_B: 0.40,
    Layer.LAYER_C: 0.22,
    Layer.BENFORD: 0.13,
    Layer.TIMESERIES: 0.12,
}

# Why: Phase 2 ML 트랙(지도+비지도) 포함 가중치. 룰 기반이 주축, ML은 보조.
#      Phase 3 D034 Stacking meta-learner가 데이터 기반으로 가중치 자동 학습 시 대체 예정.
LAYER_WEIGHTS_WITH_ML: dict[Layer, float] = {
    Layer.LAYER_A: 0.10,
    Layer.LAYER_B: 0.30,
    Layer.LAYER_C: 0.18,
    Layer.BENFORD: 0.10,
    Layer.ML_SUPERVISED: 0.15,
    Layer.ML_UNSUPERVISED: 0.17,
}

# Why: WU-16 TrendBreak 단독 가중치. ISA 540 경영진 편의 탐지는
#      부정(B) 다음으로 중요하므로 0.15 배분. 기본 4레이어 재배분.
LAYER_WEIGHTS_WITH_TRENDBREAK: dict[Layer, float] = {
    Layer.LAYER_A: 0.13,
    Layer.LAYER_B: 0.38,
    Layer.LAYER_C: 0.22,
    Layer.BENFORD: 0.12,
    Layer.TRENDBREAK: 0.15,
}

# Why: Layer D + TrendBreak 공존 시 가중치. 기존회사에서 전기 대비 변동과
#      다기간 추세 편향을 동시 분석. D와 TB 각각 0.15 배분.
LAYER_WEIGHTS_WITH_PRIOR_AND_TRENDBREAK: dict[Layer, float] = {
    Layer.LAYER_A: 0.10,
    Layer.LAYER_B: 0.32,
    Layer.LAYER_C: 0.18,
    Layer.BENFORD: 0.10,
    Layer.LAYER_D: 0.15,
    Layer.TRENDBREAK: 0.15,
}

# Why: Stacking meta-learner의 OOF 행렬 열 순서.
#      _build_score_matrix()에서 이 순서로 (N, 8) 행렬 조립.
STACKING_BASE_MODELS: list[str] = [
    Layer.LAYER_A,
    Layer.LAYER_B,
    Layer.LAYER_C,
    Layer.BENFORD,
    Layer.ML_SUPERVISED,
    Layer.ML_UNSUPERVISED,
    Layer.ML_TRANSFORMER,
    Layer.ML_SEQUENCE,
]

# Why: Stacking fallback 모드용 고정 가중치 — 라벨 부족 시 Percentile Ranking 가중합.
#      B(부정)에 가장 높은 비중. ML 4종은 균등 배분.
STACKING_FALLBACK_WEIGHTS: dict[str, float] = {
    Layer.LAYER_A: 0.08,
    Layer.LAYER_B: 0.24,
    Layer.LAYER_C: 0.14,
    Layer.BENFORD: 0.08,
    Layer.ML_SUPERVISED: 0.12,
    Layer.ML_UNSUPERVISED: 0.14,
    Layer.ML_TRANSFORMER: 0.10,
    Layer.ML_SEQUENCE: 0.10,
}


DETECTOR_DISPLAY_ORDER: list[str] = [
    Layer.LAYER_A,
    Layer.LAYER_B,
    Layer.LAYER_C,
    Layer.BENFORD,
    Layer.DUPLICATE,
    Layer.INTERCOMPANY,
    Layer.RELATIONAL,
    Layer.EVIDENCE,
    Layer.ACCESS_AUDIT,
    Layer.LAYER_D,
    Layer.TRENDBREAK,
    Layer.GRAPH,
    Layer.NLP,
    Layer.ML_SUPERVISED,
    Layer.ML_UNSUPERVISED,
    Layer.ENSEMBLE,
    Layer.ML_TRANSFORMER,
    Layer.ML_SEQUENCE,
]


DETECTOR_PROFILES: dict[str, DetectorProfile] = {
    Layer.LAYER_A: DetectorProfile(
        track_name=Layer.LAYER_A,
        display_name="Layer A",
        maturity=DetectorMaturity.PRODUCTION,
        default_enabled=True,
    ),
    Layer.LAYER_B: DetectorProfile(
        track_name=Layer.LAYER_B,
        display_name="Layer B",
        maturity=DetectorMaturity.PRODUCTION,
        default_enabled=True,
    ),
    Layer.LAYER_C: DetectorProfile(
        track_name=Layer.LAYER_C,
        display_name="Layer C",
        maturity=DetectorMaturity.PRODUCTION,
        default_enabled=True,
    ),
    Layer.BENFORD: DetectorProfile(
        track_name=Layer.BENFORD,
        display_name="Benford",
        maturity=DetectorMaturity.PRODUCTION,
        default_enabled=True,
    ),
    Layer.DUPLICATE: DetectorProfile(
        track_name=Layer.DUPLICATE,
        display_name="Duplicate",
        maturity=DetectorMaturity.BETA,
        default_enabled=True,
    ),
    Layer.INTERCOMPANY: DetectorProfile(
        track_name=Layer.INTERCOMPANY,
        display_name="Intercompany",
        maturity=DetectorMaturity.BETA,
        default_enabled=True,
    ),
    Layer.RELATIONAL: DetectorProfile(
        track_name=Layer.RELATIONAL,
        display_name="Relational",
        maturity=DetectorMaturity.BETA,
        default_enabled=False,
        activation_requirements=("settings",),
    ),
    Layer.EVIDENCE: DetectorProfile(
        track_name=Layer.EVIDENCE,
        display_name="Evidence",
        maturity=DetectorMaturity.BETA,
        default_enabled=False,
        activation_requirements=("settings",),
    ),
    Layer.ACCESS_AUDIT: DetectorProfile(
        track_name=Layer.ACCESS_AUDIT,
        display_name="Access Audit",
        maturity=DetectorMaturity.BETA,
        default_enabled=False,
        activation_requirements=("settings",),
    ),
    Layer.LAYER_D: DetectorProfile(
        track_name=Layer.LAYER_D,
        display_name="Layer D",
        maturity=DetectorMaturity.BETA,
        default_enabled=False,
        activation_requirements=("settings", "historical_data"),
    ),
    Layer.TRENDBREAK: DetectorProfile(
        track_name=Layer.TRENDBREAK,
        display_name="TrendBreak",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("settings", "historical_data"),
    ),
    Layer.GRAPH: DetectorProfile(
        track_name=Layer.GRAPH,
        display_name="Graph",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("settings", "optional_dependency"),
    ),
    Layer.NLP: DetectorProfile(
        track_name=Layer.NLP,
        display_name="NLP",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("settings", "external_api"),
    ),
    Layer.ML_SUPERVISED: DetectorProfile(
        track_name=Layer.ML_SUPERVISED,
        display_name="ML Supervised",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("settings", "trained_model"),
    ),
    Layer.ML_UNSUPERVISED: DetectorProfile(
        track_name=Layer.ML_UNSUPERVISED,
        display_name="ML Unsupervised",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("settings", "trained_model"),
    ),
    Layer.ENSEMBLE: DetectorProfile(
        track_name=Layer.ENSEMBLE,
        display_name="Ensemble",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("settings", "trained_model"),
    ),
    Layer.ML_TRANSFORMER: DetectorProfile(
        track_name=Layer.ML_TRANSFORMER,
        display_name="ML Transformer",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("trained_model",),
    ),
    Layer.ML_SEQUENCE: DetectorProfile(
        track_name=Layer.ML_SEQUENCE,
        display_name="ML Sequence",
        maturity=DetectorMaturity.EXPERIMENTAL,
        default_enabled=False,
        activation_requirements=("trained_model",),
    ),
}


DETECTOR_EXPLANATION_PROFILES: dict[str, DetectorExplanationProfile] = {
    Layer.LAYER_A: DetectorExplanationProfile(
        track_name=Layer.LAYER_A,
        summary="전표 구조와 필수 필드 무결성을 확인하는 기본 통제 계층입니다.",
        why_it_flagged="차대 불일치, 필수 필드 누락, 유효하지 않은 계정처럼 전표 구조 자체가 비정상일 때 탐지됩니다.",
        used_columns=("debit_amount", "credit_amount", "gl_account", "document_id"),
        false_positive_risks=("전표 적재 전 컬럼 매핑 오류", "계정 마스터 미정비"),
        auditor_checks=("원천 전표의 차대 합계 일치 여부를 재확인", "계정 마스터와 매핑 설정을 대조"),
        references=("일반기업회계기준 기본원칙", "ISA 315"),
    ),
    Layer.LAYER_B: DetectorExplanationProfile(
        track_name=Layer.LAYER_B,
        summary="부정 및 통제 우회 징후를 집중 점검하는 규칙 계층입니다.",
        why_it_flagged="승인한도 초과, 자기 승인, 승인 누락, 중복 지급 같은 부정 위험 패턴이 보이면 탐지됩니다.",
        used_columns=("created_by", "approved_by", "amount", "gl_account", "vendor_name"),
        false_positive_risks=("긴급 수기 처리", "조직 개편 후 승인권자 정보 미갱신"),
        auditor_checks=("승인 라인과 결재 증빙을 대조", "예외 승인 사유와 내부통제 승인권을 검토"),
        references=("ISA 240", "COSO 2013"),
    ),
    Layer.LAYER_C: DetectorExplanationProfile(
        track_name=Layer.LAYER_C,
        summary="시점, 금액, 계정 조합 등 이상 징후를 점수화하는 규칙 계층입니다.",
        why_it_flagged="기말 집중, 심야 전기, 이상 고액, 위험 적요처럼 패턴상 이례성이 높을 때 탐지됩니다.",
        used_columns=("posting_date", "amount", "header_text", "line_text", "gl_account"),
        false_positive_risks=("월말 결산 집중", "대규모 정산 또는 일회성 프로젝트"),
        auditor_checks=("거래 발생 시점과 결산 일정의 정합성을 확인", "적요와 계약/증빙의 일치 여부를 검토"),
        references=("ISA 240", "ISA 315", "K-IFRS 1001"),
    ),
    Layer.BENFORD: DetectorExplanationProfile(
        track_name=Layer.BENFORD,
        summary="금액의 선행 숫자 분포가 자연 분포와 다른지 점검합니다.",
        why_it_flagged="금액 첫 자리 분포가 Benford 기대 분포에서 유의하게 벗어나면 탐지됩니다.",
        used_columns=("amount",),
        false_positive_risks=("가격 정책이 고정된 거래 집합", "표본 수 부족"),
        auditor_checks=("모집단 구성과 표본 수를 확인", "정수 단위 반올림/고정가 정책 존재 여부를 검토"),
        references=("Benford's Law",),
    ),
    Layer.DUPLICATE: DetectorExplanationProfile(
        track_name=Layer.DUPLICATE,
        summary="중복 전표와 분할 지급 징후를 찾는 계층입니다.",
        why_it_flagged="동일 또는 유사 전표가 반복되거나, 한도를 우회하려는 분할 거래 패턴이 보이면 탐지됩니다.",
        used_columns=("vendor_name", "amount", "posting_date", "document_id"),
        false_positive_risks=("정상 반복 청구", "정기 자동전표"),
        auditor_checks=("원청구서/세금계산서의 중복 여부를 대조", "지급 사유와 계약 주기를 검토"),
        references=("PCAOB AS 2401", "ISA 240"),
    ),
    Layer.INTERCOMPANY: DetectorExplanationProfile(
        track_name=Layer.INTERCOMPANY,
        summary="내부거래 상계와 대응 전표 일치 여부를 확인합니다.",
        why_it_flagged="상대 전표가 없거나 금액/시점이 어긋나 내부거래 정합성이 낮을 때 탐지됩니다.",
        used_columns=("company_code", "counterparty_code", "amount", "posting_date"),
        false_positive_risks=("결산 시차", "상대 법인 전표 지연 인식"),
        auditor_checks=("상대 법인 원장과 금액 및 시점을 대조", "결산 조정 분개 여부를 확인"),
        references=("K-IFRS 1024",),
    ),
    Layer.RELATIONAL: DetectorExplanationProfile(
        track_name=Layer.RELATIONAL,
        summary="거래 상대방과 문서 흐름 관계를 기반으로 이상 패턴을 찾습니다.",
        why_it_flagged="신규 거래처 집중, 비정상 문서 흐름, 관계 기반 이상 연결이 보이면 탐지됩니다.",
        references=("ISA 315",),
    ),
    Layer.EVIDENCE: DetectorExplanationProfile(
        track_name=Layer.EVIDENCE,
        summary="증빙 존재 여부와 금액 일치를 점검합니다.",
        why_it_flagged="증빙 누락, OCR 금액 불일치, 증빙 메타 이상이 있으면 탐지됩니다.",
        references=("ISA 500",),
    ),
    Layer.ACCESS_AUDIT: DetectorExplanationProfile(
        track_name=Layer.ACCESS_AUDIT,
        summary="접근 로그와 결재 로그를 바탕으로 통제 흔적을 점검합니다.",
        why_it_flagged="비정상 접근, 수정 흔적, 승인 프로세스 우회가 보이면 탐지됩니다.",
        references=("ISA 240", "ITGC"),
    ),
    Layer.LAYER_D: DetectorExplanationProfile(
        track_name=Layer.LAYER_D,
        summary="전기 대비 계정 집계와 분포 변화를 비교합니다.",
        why_it_flagged="전기 대비 급격한 잔액/분포 변화가 보이면 탐지됩니다.",
        references=("ISA 520",),
    ),
    Layer.TRENDBREAK: DetectorExplanationProfile(
        track_name=Layer.TRENDBREAK,
        summary="추정치와 실제치의 괴리를 이용해 비정상 변곡을 찾습니다.",
        why_it_flagged="다년 추세 기반 기대 범위를 벗어나면 탐지됩니다.",
        references=("ISA 540",),
    ),
    Layer.GRAPH: DetectorExplanationProfile(
        track_name=Layer.GRAPH,
        summary="거래 네트워크 구조에서 순환 및 비정상 연결을 찾습니다.",
        why_it_flagged="순환 거래나 비정상 이전가격 연결이 나타나면 탐지됩니다.",
        references=("ISA 550",),
    ),
    Layer.NLP: DetectorExplanationProfile(
        track_name=Layer.NLP,
        summary="적요와 계정/프로세스 의미가 어긋나는지를 점검합니다.",
        why_it_flagged="적요 의미와 계정, 프로세스, 내부거래 맥락이 맞지 않으면 탐지됩니다.",
        references=("ISA 240", "ISA 315"),
    ),
    Layer.ML_SUPERVISED: DetectorExplanationProfile(
        track_name=Layer.ML_SUPERVISED,
        summary="학습된 정상/이상 패턴과 현재 전표 특성을 비교합니다.",
        why_it_flagged="과거 학습 데이터 기준으로 이상 거래일 확률이 높으면 탐지됩니다.",
        references=("Statistical anomaly detection",),
    ),
    Layer.ML_UNSUPERVISED: DetectorExplanationProfile(
        track_name=Layer.ML_UNSUPERVISED,
        summary="비지도 잠재표현에서 재구성 오차가 큰 전표를 찾습니다.",
        why_it_flagged="정상 군집에서 멀어 재구성 오차와 이상 점수가 높으면 탐지됩니다.",
        references=("VAE", "Isolation Forest"),
    ),
    Layer.ENSEMBLE: DetectorExplanationProfile(
        track_name=Layer.ENSEMBLE,
        summary="복수 탐지기의 신호를 종합해 최종 이상 가능성을 평가합니다.",
        why_it_flagged="개별 탐지기 신호가 결합되어 종합 위험도가 높아지면 탐지됩니다.",
        references=("Stacking ensemble",),
    ),
}


RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    "A01": RuleExplanation(
        rule_id="A01",
        plain_reason="차변과 대변 금액 합계가 맞지 않습니다.",
        used_columns=("debit_amount", "credit_amount"),
        false_positive_risks=("적재 중 금액 부호 반전",),
        auditor_checks=("전표 원본의 차대 합계와 업로드 데이터 합계를 비교",),
        references=("일반기업회계기준 기본원칙",),
    ),
    "A02": RuleExplanation(
        rule_id="A02",
        plain_reason="감사에 필요한 필수 필드가 비어 있습니다.",
        used_columns=("document_id", "posting_date", "gl_account"),
        false_positive_risks=("원본 추출 포맷 차이",),
        auditor_checks=("ERP 추출 조건과 컬럼 매핑을 재확인",),
        references=("ISA 315 A113",),
    ),
    "A03": RuleExplanation(
        rule_id="A03",
        plain_reason="유효하지 않거나 정의되지 않은 계정이 사용되었습니다.",
        used_columns=("gl_account",),
        false_positive_risks=("계정 마스터 최신화 지연",),
        auditor_checks=("계정 마스터와 전표의 계정코드를 대조",),
        references=("ISA 315",),
    ),
    "B02": RuleExplanation(
        rule_id="B02",
        plain_reason="생성자와 승인자 관계가 비정상적이거나 통제 우회 징후가 보입니다.",
        used_columns=("created_by", "approved_by"),
        false_positive_risks=("긴급 전표 처리",),
        auditor_checks=("승인권자 위임 기록과 긴급 처리 사유를 확인",),
        references=("ISA 240 §33",),
    ),
    "B03": RuleExplanation(
        rule_id="B03",
        plain_reason="거래 금액이 승인한도를 초과했습니다.",
        used_columns=("amount", "approved_by"),
        false_positive_risks=("한도 마스터 미반영",),
        auditor_checks=("승인권자 한도표와 결재 증빙을 대조",),
        references=("ISA 240 §33",),
    ),
    "B04": RuleExplanation(
        rule_id="B04",
        plain_reason="유사한 지급 전표가 반복되어 중복 지급 가능성이 있습니다.",
        used_columns=("vendor_name", "amount", "posting_date"),
        false_positive_risks=("정상 반복 청구",),
        auditor_checks=("청구서 번호와 지급 근거 문서를 대조",),
        references=("ISA 240 §33", "PCAOB AS 2401",),
    ),
    "B06": RuleExplanation(
        rule_id="B06",
        plain_reason="전표 작성자와 승인자가 동일해 자기 승인 징후가 있습니다.",
        used_columns=("created_by", "approved_by"),
        false_positive_risks=("소규모 조직의 예외 승인",),
        auditor_checks=("예외 승인 정책과 실제 결재 흔적을 검토",),
        references=("COSO 2013 원칙 10",),
    ),
    "B19": RuleExplanation(
        rule_id="B19",
        plain_reason="Top-side JE로 보이는 복합 위험 신호가 결합되었습니다.",
        used_columns=("posting_date", "created_by", "amount", "line_text"),
        false_positive_risks=("정상 결산 조정 분개",),
        auditor_checks=("결산 분개 승인 근거와 작성 배경을 검토",),
        references=("ISA 240 §33",),
    ),
    "C01": RuleExplanation(
        rule_id="C01",
        plain_reason="결산 시점에 집중된 이례적 거래입니다.",
        used_columns=("posting_date", "amount"),
        false_positive_risks=("정상 월말 마감 전표",),
        auditor_checks=("결산일정과 거래 발생일, 증빙일자를 대조",),
        references=("ISA 240 §32",),
    ),
    "C06": RuleExplanation(
        rule_id="C06",
        plain_reason="적요에 위험 키워드 또는 설명 취약 징후가 포함되어 있습니다.",
        used_columns=("line_text", "header_text"),
        false_positive_risks=("정상 수정분개 적요",),
        auditor_checks=("적요와 실제 계약/증빙 문구의 일치 여부를 확인",),
        references=("ISA 240 §33(b)",),
    ),
    "C07": RuleExplanation(
        rule_id="C07",
        plain_reason="금액 선행 숫자 분포가 기대 분포와 다릅니다.",
        used_columns=("amount",),
        false_positive_risks=("고정가 또는 정책가격 데이터",),
        auditor_checks=("표본 수와 모집단 성격을 검토",),
        references=("Benford's Law",),
    ),
    "C08": RuleExplanation(
        rule_id="C08",
        plain_reason="동일 모집단 대비 금액이 이례적으로 큽니다.",
        used_columns=("amount", "gl_account"),
        false_positive_risks=("대형 일회성 계약",),
        auditor_checks=("거래 규모의 사업적 배경과 승인 근거를 확인",),
        references=("ISA 240 §32",),
    ),
    "IC01": RuleExplanation(
        rule_id="IC01",
        plain_reason="대응되는 내부거래 전표를 찾지 못했습니다.",
        used_columns=("company_code", "counterparty_code", "amount"),
        false_positive_risks=("상대 법인 입력 지연",),
        auditor_checks=("상대 법인 원장과 전표 반영 시점을 대조",),
        references=("K-IFRS 1024",),
    ),
    "ML01": RuleExplanation(
        rule_id="ML01",
        plain_reason="지도학습 모델이 이상 거래 확률을 높게 평가했습니다.",
        auditor_checks=("학습 라벨 기준과 유사 과거 케이스를 함께 확인",),
        references=("Supervised anomaly detection",),
    ),
    "ML02": RuleExplanation(
        rule_id="ML02",
        plain_reason="비지도 이상 탐지 모델의 재구성 오차가 높습니다.",
        auditor_checks=("상위 기여 피처와 규칙 기반 신호를 함께 검토",),
        references=("VAE", "Isolation Forest"),
    ),
    "EN01": RuleExplanation(
        rule_id="EN01",
        plain_reason="복수 모델 신호가 합쳐져 종합 위험도가 상승했습니다.",
        auditor_checks=("기저 모델별 신호를 함께 확인",),
        references=("Stacking ensemble",),
    ),
}


def get_detector_profile(track_name: str) -> DetectorProfile:
    """track_name 기준 운영 메타 반환. 미등록 트랙은 보수적으로 beta 처리."""

    return DETECTOR_PROFILES.get(
        track_name,
        DetectorProfile(
            track_name=track_name,
            display_name=track_name,
            maturity=DetectorMaturity.BETA,
            default_enabled=False,
        ),
    )


def get_detector_explanation_profile(track_name: str) -> DetectorExplanationProfile:
    """track_name 기준 설명 메타 반환. 미등록 트랙은 축약 기본값 사용."""

    return DETECTOR_EXPLANATION_PROFILES.get(
        track_name,
        DetectorExplanationProfile(
            track_name=track_name,
            summary=f"{track_name} 탐지 결과입니다.",
            why_it_flagged="탐지기별 세부 설명이 아직 등록되지 않았습니다.",
        ),
    )


def get_rule_explanation(rule_id: str) -> RuleExplanation:
    """룰별 설명 메타 반환. 미등록 룰은 축약 기본값 사용."""

    return RULE_EXPLANATIONS.get(
        rule_id,
        RuleExplanation(
            rule_id=rule_id,
            plain_reason=f"{RULE_CODES.get(rule_id, '미등록 룰')} 신호가 감지되었습니다.",
        ),
    )

# Why: B19 Top-side JE 가점 조건 — score_aggregator에서 순회하며 OR 결합.
#      룰 ID를 한 곳에 모아 하드코딩 제거. 각 그룹 내 OR 논리.
TOPSIDE_BONUS_RULES: list[tuple[str, list[tuple[str, str]]]] = [
    ("기말 시점",        [("C01", "layer_c")]),
    ("승인 우회",        [("B06", "layer_b"), ("B09", "layer_b")]),
    ("비정상 계정",      [("A03", "layer_a"), ("C09", "layer_c")]),
    ("이상 고액",        [("C08", "layer_c")]),
    ("위험 적요",        [("C06", "layer_c")]),
]

# Why: 0.7 이상 High, 0.4 이상 Medium, 0.2 이상 Low, 나머지 Normal.
RISK_THRESHOLDS: dict[str, float] = {
    RiskLevel.HIGH: 0.7,
    RiskLevel.MEDIUM: 0.4,
    RiskLevel.LOW: 0.2,
}
