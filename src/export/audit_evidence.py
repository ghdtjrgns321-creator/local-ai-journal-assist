"""audit_evidence — 탐지 결과를 감사조서 문구로 구조화하는 템플릿.

Why: 감사인이 "왜 이 전표가 이상 의심인가?"라는 질문에 시스템 출력을 그대로
     인용할 수 있어야 한다. 단순 score 숫자가 아니라 다음 요소를 조합한 문장:
     - 위반 룰 ID + 룰명 + 법규 근거 (감사기준서/내부통제 원칙)
     - VAE Top-K 기여 피처 + 각 피처 기여도
     - anomaly_score, risk_level

ISA 240 §32~33 "부정 위험 대응" 절차에서 요구하는 "정량적 근거" 포맷을 충족한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.detection.constants import RULE_CODES

# Why: 룰 ID → 감사기준서/법규 근거 매핑. 감사조서 문구의 "근거 법규" 필드로 사용.
#      모든 룰을 망라하진 않음 (새 룰 추가 시 해당 룰에 대해 명시적 등록 필요).
RULE_LEGAL_BASIS: dict[str, str] = {
    # Layer A: 무결성 — 회계원칙 기반
    "A01": "일반기업회계기준 기본원칙 (차대 균형)",
    "A02": "ISA 315 A113 — 재무보고 필수 정보",
    "A03": "ISA 315 — 계정체계 무결성",
    # Layer B: 부정 — ISA 240
    "B01": "ISA 240 §32 — 매출 인식 부정 추정",
    "B02": "ISA 240 §33 — 경영진 override 우회",
    "B03": "ISA 240 §33 — 승인한도 초과",
    "B04": "ISA 240 §33 — 중복 지급 (P2P 내부통제)",
    "B05": "PCAOB AS 2401 — 중복 전표",
    "B05a": "PCAOB AS 2401 — 완전일치 중복",
    "B05b": "PCAOB AS 2401 — 퍼지 매칭 중복",
    "B05c": "PCAOB AS 2401 §65 — 분할 거래 (threshold 우회)",
    "B05d": "PCAOB AS 2401 — 시차 중복",
    "B06": "COSO 2013 원칙 10 — 직무분리 (자기 승인)",
    "B07": "COSO 2013 원칙 10 — 직무분리 위반",
    "B08": "ISA 240 §33(b) — 수기 전표 집중",
    "B09": "ISA 240 §33 — 승인 생략",
    "B10": "K-IFRS 1024 — 관계자 거래 공시",
    "B11": "K-IFRS 1016 — 비용의 자산화 오류",
    "B19": "ISA 240 §33 — Top-side JE 복합 위험",
    # Layer C: 이상 징후
    "C01": "ISA 240 §32 — 결산 시점 이상 거래",
    "C02": "내부통제 — 주말 전기",
    "C03": "내부통제 — 심야 전기",
    "C04": "ISA 315 — 소급 전기",
    "C05": "K-IFRS 1001 §27 — 기간 귀속",
    "C06": "ISA 240 §33(b) — 위험 적요 키워드",
    "C07": "Benford's Law (벤포드 법칙)",
    "C08": "ISA 240 §32 — 이상 고액",
    "C09": "ISA 315 — 비정상 계정조합",
    "C10": "K-IFRS 1001 — 가수금 장기체류",
    "C11": "ISA 240 §32 — 역분개 패턴",
    "C12": "내부통제 — 비정상 시간 집중 입력",
    "C13": "내부통제 — 배치 전표 이상",
    # ML
    "ML01": "Statistical anomaly (XGBoost 지도학습)",
    "ML02": "Statistical anomaly (VAE+IF 비지도학습)",
    "ML03": "Statistical anomaly (FT-Transformer)",
    "ML04": "Statistical anomaly (BiLSTM 시퀀스)",
    "EN01": "Stacking meta-learner 앙상블 종합 판정",
}


@dataclass
class AuditEvidence:
    """단일 전표의 감사 증거 구조체."""

    document_id: str
    anomaly_score: float
    risk_level: str
    violated_rules: list[str]       # 위반 룰 ID 목록
    top_features: list[tuple[str, float]]  # [(피처명, 기여도), ...]
    narrative: str                  # 감사조서 문구 (한국어)


def build_evidence_row(
    row: pd.Series,
    top_feature_k: int = 3,
) -> AuditEvidence:
    """DataFrame의 한 행 → AuditEvidence 변환.

    필요 컬럼:
    - document_id, anomaly_score, risk_level, flagged_rules (comma-separated str)
    - ML02_top_feature_1..3 + ML02_top_feature_1..3_contrib (VAE Top-K, 선택)

    Why: 대시보드 AgGrid 행 클릭 시 또는 리포트 생성 시 사용.
         누락 컬럼은 graceful하게 빈 값으로 처리.
    """
    doc_id = str(row.get("document_id", "UNKNOWN"))
    score = float(row.get("anomaly_score", 0.0))
    risk = str(row.get("risk_level", "Normal"))

    # 위반 룰 파싱 (comma-separated)
    flagged_str = row.get("flagged_rules", "") or ""
    rules = [r.strip() for r in flagged_str.split(",") if r.strip()]

    # VAE Top-K 피처 추출 (있는 경우에만)
    top_features: list[tuple[str, float]] = []
    for i in range(1, top_feature_k + 1):
        feat_col = f"ML02_top_feature_{i}"
        contrib_col = f"ML02_top_feature_{i}_contrib"
        if feat_col in row.index and contrib_col in row.index:
            name = row[feat_col]
            contrib = row[contrib_col]
            if pd.notna(name) and pd.notna(contrib):
                top_features.append((str(name), float(contrib)))

    narrative = format_narrative(
        document_id=doc_id,
        score=score,
        risk=risk,
        rules=rules,
        top_features=top_features,
    )
    return AuditEvidence(
        document_id=doc_id,
        anomaly_score=score,
        risk_level=risk,
        violated_rules=rules,
        top_features=top_features,
        narrative=narrative,
    )


def format_narrative(
    document_id: str,
    score: float,
    risk: str,
    rules: list[str],
    top_features: list[tuple[str, float]],
) -> str:
    """감사조서 문구 포맷터.

    예시 출력:
        전표 D000123은 위험도 'High' (anomaly_score=0.87)로 분류되었습니다.
        위반 룰: C01(기말 대규모) [ISA 240 §32 — 결산 시점 이상 거래],
        B19(Top-side JE) [ISA 240 §33 — Top-side JE 복합 위험].
        VAE 재구성 오차 주요 기여 피처: amount(기여도 0.432), gl_account(0.187),
        posting_date(0.093). 감사인 재검토 권고.
    """
    parts: list[str] = [
        f"전표 {document_id}은 위험도 '{risk}' "
        f"(anomaly_score={score:.3f})로 분류되었습니다.",
    ]

    if rules:
        rule_descriptions: list[str] = []
        for rule_id in rules:
            name = RULE_CODES.get(rule_id, "미등록 룰")
            basis = RULE_LEGAL_BASIS.get(rule_id, "")
            if basis:
                rule_descriptions.append(f"{rule_id}({name}) [{basis}]")
            else:
                rule_descriptions.append(f"{rule_id}({name})")
        parts.append("위반 룰: " + ", ".join(rule_descriptions) + ".")
    else:
        parts.append("위반 룰: 없음 (ML 모델 단독 판정).")

    if top_features:
        feat_str = ", ".join(
            f"{name}(기여도 {contrib:.3f})" for name, contrib in top_features
        )
        parts.append(f"VAE 재구성 오차 주요 기여 피처: {feat_str}.")

    parts.append("감사인 재검토 권고.")
    return " ".join(parts)


def build_evidence_report(
    df: pd.DataFrame,
    top_feature_k: int = 3,
    min_score: float = 0.0,
) -> list[AuditEvidence]:
    """여러 전표에 대한 증거 리스트 생성.

    Args:
        df: pipeline 결과 DataFrame (anomaly_score, risk_level, flagged_rules 포함)
        top_feature_k: VAE Top-K 피처 수
        min_score: 이 점수 이상인 전표만 리포트 대상

    Why: 감사조서 일괄 생성용. 대시보드에서 CSV/Excel 내보내기 시 호출.
    """
    if "anomaly_score" not in df.columns:
        return []
    filtered = df[df["anomaly_score"] >= min_score]
    return [
        build_evidence_row(row, top_feature_k=top_feature_k)
        for _, row in filtered.iterrows()
    ]
