"""Detection 모듈 공용 상수 — 38개 룰 메타데이터 + 레이어/위험 등급 열거형.

Why: 룰 ID·이름·심각도를 한 곳에서 관리하여 하드코딩 제거.
     EDA·대시보드 등 외부 모듈에서도 import하여 일관성 유지.
"""

from __future__ import annotations

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
}


# ── 가중치·임계값 ────────────────────────────────────────────

LAYER_WEIGHTS: dict[Layer, float] = {
    Layer.LAYER_A: 0.15,
    Layer.LAYER_B: 0.45,
    Layer.LAYER_C: 0.25,
    Layer.BENFORD: 0.15,
}

# Why: 기존회사 트랙에서 Layer D 추가 시 가중치 재배분.
#      Layer B(부정) 비중이 가장 높되, Layer D에 0.18 할당.
LAYER_WEIGHTS_WITH_PRIOR: dict[Layer, float] = {
    Layer.LAYER_A: 0.12,
    Layer.LAYER_B: 0.38,
    Layer.LAYER_C: 0.20,
    Layer.BENFORD: 0.12,
    Layer.LAYER_D: 0.18,
}

# Why: WU-06 시계열 트랙 추가에 따른 가중치 재배분.
#      시계열은 보조 레이어(0.12). B(부정) 여전히 최고 비중.
#      호출부에서 aggregate_scores(weights=LAYER_WEIGHTS_WITH_TIMESERIES) 명시 필수.
LAYER_WEIGHTS_WITH_TIMESERIES: dict[Layer, float] = {
    Layer.LAYER_A: 0.13,
    Layer.LAYER_B: 0.40,
    Layer.LAYER_C: 0.22,
    Layer.BENFORD: 0.13,
    Layer.TIMESERIES: 0.12,
}

# Why: Phase 2 ML 트랙(지도+비지도) 포함 가중치. 룰 기반(0.68)이 주축, ML(0.32)은 보조.
#      비지도(0.17) > 지도(0.15): 합성 데이터 순환 학습 없어 적합도 높음.
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
