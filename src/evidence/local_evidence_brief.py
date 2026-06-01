"""Deterministic local evidence brief for PHASE1 case drilldown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.detection.constants import RULE_CODES
from src.detection.rule_detail_metadata import get_rule_detail_metadata


@dataclass(frozen=True)
class LocalEvidenceBrief:
    """Display-only summary derived from existing PHASE1/PHASE2 evidence."""

    key_evidence: list[str]
    audit_actions: list[str]
    limitations: list[str]


def build_local_evidence_brief(drilldown: dict[str, Any]) -> LocalEvidenceBrief:
    """Build a local, deterministic brief from already-computed evidence.

    The function does not call external clients, does not recalculate priority,
    and only formats signals already present in the drilldown payload.
    """
    case = _as_mapping(drilldown.get("case"))
    raw_rule_hits = _records(drilldown.get("raw_rule_hits"))
    documents = _records(drilldown.get("documents"))

    evidence: list[str] = []
    actions: list[str] = []

    _append_text(evidence, case.get("risk_narrative"))
    _append_text(evidence, case.get("representative_explanation"))
    _append_focus(evidence, case.get("review_focus"))
    _append_rule_evidence(evidence, raw_rule_hits, documents)
    _append_document_evidence(evidence, documents)
    _append_family_evidence(evidence, drilldown)

    _append_actions(actions, case.get("recommended_audit_actions"))
    _append_rule_actions(actions, raw_rule_hits, documents)

    if not evidence:
        evidence.append("선택된 case에 연결된 표시 가능한 룰/문서 신호가 없습니다.")
    if not actions:
        actions.extend(
            [
                "선택된 전표의 원천 증빙과 승인 근거를 확인합니다.",
                "동일 거래처, 금액, 작성자 기준의 반복 분개 여부를 확인합니다.",
                "업무상 정상 예외인지 회사 정책과 결산 절차에 비추어 검토합니다.",
            ]
        )

    return LocalEvidenceBrief(
        key_evidence=_dedupe(evidence)[:5],
        audit_actions=_dedupe(actions)[:5],
        limitations=[
            "이미 산출된 PHASE1 룰 신호와 표시 가능한 family 신호만 요약합니다.",
            "확정 판단이 아니며 원천 증빙과 업무 맥락 확인이 필요합니다.",
        ],
    )


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [_as_mapping(item) for item in value]
    return []


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _append_text(items: list[str], value: Any) -> None:
    text = _clean_text(value)
    if text:
        items.append(text)


def _append_focus(items: list[str], value: Any) -> None:
    for text in _text_items(value):
        items.append(f"검토 초점: {text}")


def _append_actions(items: list[str], value: Any) -> None:
    for text in _text_items(value):
        items.append(text)


def _append_rule_evidence(
    items: list[str],
    raw_rule_hits: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> None:
    rule_ids = _collect_rule_ids(raw_rule_hits, documents)
    if not rule_ids:
        return
    labels = [f"{rule_id} {_rule_label(rule_id)}" for rule_id in rule_ids[:5]]
    items.append("적중 룰 신호: " + ", ".join(labels))


def _append_document_evidence(items: list[str], documents: list[dict[str, Any]]) -> None:
    if not documents:
        return
    matched_docs = [
        str(doc.get("document_id"))
        for doc in documents
        if doc.get("document_id") and _list_values(doc.get("matched_rules"))
    ]
    if matched_docs:
        items.append(f"룰 신호가 연결된 전표 {len(matched_docs)}건: " + ", ".join(matched_docs[:3]))

    same_approver_docs = [
        str(doc.get("document_id"))
        for doc in documents
        if doc.get("document_id")
        and doc.get("created_by")
        and doc.get("created_by") == doc.get("approved_by")
    ]
    if same_approver_docs:
        items.append(
            "작성자와 승인자가 같은 전표가 포함됩니다: " + ", ".join(same_approver_docs[:3])
        )


def _append_family_evidence(items: list[str], drilldown: dict[str, Any]) -> None:
    contributions = drilldown.get("family_contributions")
    rows = _records(contributions)
    if not rows:
        return
    names = [_clean_text(row.get("family") or row.get("lane") or row.get("signal")) for row in rows]
    names = [name for name in names if name]
    if names:
        items.append("보조 family 신호: " + ", ".join(_dedupe(names)[:3]))


def _append_rule_actions(
    items: list[str],
    raw_rule_hits: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> None:
    rule_ids = _collect_rule_ids(raw_rule_hits, documents)
    if rule_ids:
        items.append("적중 룰별 근거 필드와 원천 문서의 일치 여부를 확인합니다.")
    if any(
        doc.get("created_by") and doc.get("created_by") == doc.get("approved_by")
        for doc in documents
    ):
        items.append("작성자와 승인자가 같은 사유 및 대체 승인 근거를 확인합니다.")


def _collect_rule_ids(
    raw_rule_hits: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> list[str]:
    rule_ids: list[str] = []
    for hit in raw_rule_hits:
        rule_id = _clean_text(hit.get("rule_id"))
        if rule_id:
            rule_ids.append(rule_id)
    for doc in documents:
        rule_ids.extend(_list_values(doc.get("matched_rules")))
    return _dedupe(rule_ids)


def _rule_label(rule_id: str) -> str:
    try:
        meta = get_rule_detail_metadata(rule_id)
    except KeyError:
        return RULE_CODES.get(rule_id, "")
    return meta.display_copy.display_title or RULE_CODES.get(rule_id, "")


def _text_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_clean_text(value)] if _clean_text(value) else []
    if isinstance(value, (list, tuple, set)):
        return [_clean_text(item) for item in value if _clean_text(item)]
    return []


def _list_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return []


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
