"""탐지 결과 설명 builder.

Why: UI와 export가 같은 설명 메타를 소비하도록 track/rule/document 단위
     explanation 조립을 한 곳에 모은다.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import pandas as pd

from src.detection.base import DetectionResult
from src.detection.constants import RULE_CODES, get_rule_explanation


def parse_flagged_rules(value: Any) -> list[str]:
    """CSV flagged_rules 문자열을 룰 코드 리스트로 변환."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [rule.strip() for rule in text.split(",") if rule.strip()]


def build_track_explanation(result: DetectionResult) -> dict[str, Any]:
    """DetectionResult 기준 track-level 설명 블록 생성."""
    return {
        "track_name": result.track_name,
        "display_name": result.display_name,
        "summary": result.explanation_summary,
        "why_it_flagged": result.why_it_flagged,
        "used_columns": result.used_columns,
        "false_positive_risks": result.false_positive_risks,
        "auditor_checks": result.auditor_checks,
        "references": result.references,
        "warnings": [str(w) for w in result.warnings],
    }


def build_rule_explanation(rule_id: str) -> dict[str, Any]:
    """룰별 구조화 설명 반환."""
    rule = get_rule_explanation(rule_id)
    return {
        "rule_id": rule_id,
        "rule_name": RULE_CODES.get(rule_id, "미등록 룰"),
        "plain_reason": rule.plain_reason,
        "used_columns": [str(value) for value in rule.used_columns],
        "false_positive_risks": [str(value) for value in rule.false_positive_risks],
        "auditor_checks": [str(value) for value in rule.auditor_checks],
        "references": [str(value) for value in rule.references],
    }


def build_document_explanation(
    doc_id: str,
    result_data: pd.DataFrame,
    results: list[DetectionResult] | None = None,
) -> dict[str, Any]:
    """문서 단위 설명 블록 생성."""
    doc_lines = result_data[result_data.get("document_id") == doc_id].copy()
    if doc_lines.empty:
        return {
            "document_id": doc_id,
            "headline": f"전표 {doc_id} 설명 정보를 찾을 수 없습니다.",
            "triggered_rules": [],
            "auditor_focus_points": [],
            "used_columns": [],
            "false_positive_risks": [],
            "references": [],
            "track_explanations": [],
            "narrative": f"전표 {doc_id}에 대한 설명 정보를 찾을 수 없습니다.",
        }

    first_row = doc_lines.iloc[0]
    rule_ids = parse_flagged_rules(first_row.get("flagged_rules"))
    rule_explanations = [build_rule_explanation(rule_id) for rule_id in rule_ids]

    track_explanations: list[dict[str, Any]] = []
    if results:
        active_tracks = []
        doc_indices = set(int(idx) for idx in doc_lines.index.tolist())
        for result in results:
            if doc_indices.intersection(set(int(idx) for idx in result.flagged_indices)):
                active_tracks.append(build_track_explanation(result))
        track_explanations = active_tracks

    used_columns = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("used_columns", [])
    )
    false_positive_risks = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("false_positive_risks", [])
    )
    auditor_focus_points = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("auditor_checks", [])
    )
    references = _merge_unique(
        item
        for block in [*rule_explanations, *track_explanations]
        for item in block.get("references", [])
    )

    risk_level = str(first_row.get("risk_level", "Unknown"))
    anomaly_score = float(first_row.get("anomaly_score", 0.0) or 0.0)
    if rule_explanations:
        top_reasons = ", ".join(
            f"{item['rule_id']}({item['rule_name']})" for item in rule_explanations[:3]
        )
        headline = (
            f"전표 {doc_id}은 위험도 {risk_level}, 점수 {anomaly_score:.3f}로 평가되었고 "
            f"{top_reasons} 신호가 확인되었습니다."
        )
    else:
        headline = (
            f"전표 {doc_id}은 위험도 {risk_level}, 점수 {anomaly_score:.3f}로 평가되었고 "
            "규칙 기반 신호는 없지만 추가 검토가 권고됩니다."
        )

    return {
        "document_id": doc_id,
        "headline": headline,
        "triggered_rules": rule_explanations,
        "auditor_focus_points": auditor_focus_points,
        "used_columns": used_columns,
        "false_positive_risks": false_positive_risks,
        "references": references,
        "track_explanations": track_explanations,
        "narrative": _build_narrative(doc_id, risk_level, anomaly_score, rule_explanations, auditor_focus_points),
    }


def build_export_narrative(
    document_id: str,
    score: float,
    risk: str,
    rules: list[str],
    top_features: list[tuple[str, float]],
) -> str:
    """export용 간결 narrative 생성."""
    rule_explanations = [build_rule_explanation(rule_id) for rule_id in rules]
    parts = [
        f"전표 {document_id}은 위험도 '{risk}' (anomaly_score={score:.3f})로 분류되었습니다.",
    ]
    if rule_explanations:
        rule_text = ", ".join(
            _format_rule_export_text(rule["rule_id"], rule["rule_name"], rule["references"])
            for rule in rule_explanations
        )
        parts.append(f"위반 룰: {rule_text}.")
    else:
        parts.append("위반 룰: 없음 (ML 모델 단독 판정).")

    if top_features:
        feat_text = ", ".join(
            f"{name}(기여도 {contrib:.3f})" for name, contrib in top_features
        )
        parts.append(f"VAE 재구성 오차 주요 기여 피처: {feat_text}.")

    auditor_checks = _merge_unique(
        item for rule in rule_explanations for item in rule.get("auditor_checks", [])
    )
    if auditor_checks:
        parts.append(f"감사인 재검토 권고. 감사자 확인 포인트: {auditor_checks[0]}.")
    else:
        parts.append("감사인 재검토 권고.")
    return " ".join(parts)


def _build_narrative(
    doc_id: str,
    risk_level: str,
    anomaly_score: float,
    rule_explanations: list[dict[str, Any]],
    auditor_focus_points: list[str],
) -> str:
    if rule_explanations:
        reasons = ", ".join(
            f"{item['rule_id']} {item['plain_reason']}" for item in rule_explanations[:3]
        )
        text = (
            f"전표 {doc_id}은 위험도 {risk_level}, 점수 {anomaly_score:.3f}로 평가되었습니다. "
            f"주요 탐지 사유는 {reasons}입니다."
        )
    else:
        text = (
            f"전표 {doc_id}은 위험도 {risk_level}, 점수 {anomaly_score:.3f}로 평가되었습니다. "
            "규칙 기반 신호는 없지만 추가 검토가 권고됩니다."
        )
    if auditor_focus_points:
        text += f" 감사자 확인 포인트: {auditor_focus_points[0]}."
    return text


def _format_rule_export_text(rule_id: str, rule_name: str, references: list[str]) -> str:
    if references:
        return f"{rule_id}({rule_name}) [{references[0]}]"
    return f"{rule_id}({rule_name})"


def _merge_unique(values) -> list[str]:
    merged = OrderedDict()
    for value in values:
        text = str(value).strip()
        if text:
            merged[text] = None
    return list(merged.keys())
