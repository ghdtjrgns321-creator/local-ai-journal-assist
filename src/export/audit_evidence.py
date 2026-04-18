"""audit_evidence — 탐지 결과를 분석 증거 문구로 구조화하는 템플릿.

Why: 감사인이 "왜 이 전표가 이상 의심인가?"라는 질문에 시스템 출력을 그대로
     인용할 수 있어야 한다. 단순 score 숫자가 아니라 다음 요소를 조합한 문장:
     - 위반 룰 ID + 룰명 + 법규 근거 (감사기준서/내부통제 원칙)
     - VAE Top-K 기여 피처 + 각 피처 기여도
     - anomaly_score, risk_level

생성된 문구는 ``데이터 분석 결과 보고서``의 이상 전표 시트/섹션에서
사용된다. 감사인이 이 문구를 자신의 감사조서(ISA 230) 작성에 참조 자료로
활용하는 것이지, 도구가 직접 감사조서를 산출하지는 않는다.

ISA 240 §32~33 "부정 위험 대응" 절차의 정량적 근거 포맷을 충족한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.detection.constants import RULE_EXPLANATIONS
from src.detection.explanations import build_export_narrative, parse_flagged_rules

# Why: 하위 호환 테스트/외부 import를 위해 export 모듈에서도 공개.
RULE_LEGAL_BASIS: dict[str, str] = {
    rule_id: explanation.references[0]
    for rule_id, explanation in RULE_EXPLANATIONS.items()
    if explanation.references
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
    rules = parse_flagged_rules(row.get("flagged_rules", ""))

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
    """분석 증거 문구 포맷터 (보고서/대시보드 공용)."""
    return build_export_narrative(
        document_id=document_id,
        score=score,
        risk=risk,
        rules=rules,
        top_features=top_features,
    )


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
