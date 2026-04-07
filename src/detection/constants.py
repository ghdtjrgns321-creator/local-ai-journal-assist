"""Detection 모듈 공용 상수 — 27개 룰 메타데이터 + 레이어/위험 등급 열거형.

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


# ── 27개 룰 메타데이터 ────────────────────────────────────────

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
    # Layer D: 전기 대비 변동
    "D01": "계정과목 집계 급변",
    "D02": "월별 분포 패턴 변화",
}

SEVERITY_MAP: dict[str, int] = {
    "A01": 5, "A02": 2, "A03": 3,
    "B01": 5, "B02": 3, "B03": 3, "B04": 3, "B05": 3,
    "B06": 3, "B07": 4, "B08": 4, "B09": 4, "B10": 4, "B11": 4, "B19": 5,
    "C01": 3, "C02": 2, "C03": 2, "C04": 3, "C05": 4,
    "C06": 1, "C07": 2, "C08": 3, "C09": 2, "C10": 3, "C11": 4, "C12": 3,
    "D01": 4, "D02": 3,
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

# Why: 0.7 이상 High, 0.4 이상 Medium, 0.2 이상 Low, 나머지 Normal.
RISK_THRESHOLDS: dict[str, float] = {
    RiskLevel.HIGH: 0.7,
    RiskLevel.MEDIUM: 0.4,
    RiskLevel.LOW: 0.2,
}
