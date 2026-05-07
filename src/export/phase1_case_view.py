"""Projection helpers for Phase 1 case queues, summaries, and drill-down views."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from src.detection.phase1_case_builder import (
    _rule_actions,
    _rule_focus,
    _rule_label,
    load_phase1_case_result,
)
from src.models.phase1_case import CaseGroupResult, Phase1CaseResult

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)

_LOW_SIGNAL_QUEUE_ID = "low_signal_candidate"
_LOW_SIGNAL_QUEUE_LABEL = "Low-signal 후보"
_LOW_SIGNAL_MAX_DOCS = 5_000
_LOW_SIGNAL_RELEVANT_RULES = {
    "L1-07",
    "L1-09",
    "L2-01",
    "L2-02",
    "L2-03",
    "L3-01",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-12",
    "L4-03",
}


def resolve_phase1_case_result(
    pr: PipelineResult,
    *,
    load_artifact: bool = True,
) -> Phase1CaseResult | None:
    """Return an in-memory case result or load it from the saved artifact path."""
    existing = getattr(pr, "phase1_case_result", None)
    if existing is not None:
        # A restored/partially-built result can carry an empty placeholder object.
        # Treat that as absent so all dashboard aggregations fall through to the
        # persisted artifact instead of reporting 0 case breakdowns.
        if getattr(existing, "cases", None):
            return existing
        try:
            pr.phase1_case_result = None
        except Exception:
            pass
    if not load_artifact:
        return None
    artifact_path = getattr(pr, "phase1_case_path", None)
    if not artifact_path:
        return None
    try:
        loaded = load_phase1_case_result(artifact_path)
    except Exception:
        logger.warning("PHASE1 case artifact load failed: %s", artifact_path, exc_info=True)
        return None
    if not getattr(loaded, "cases", None):
        return None
    try:
        pr.phase1_case_result = loaded
    except Exception:
        pass
    return loaded


def summarize_phase1_case_result(
    pr: PipelineResult,
    *,
    load_artifact: bool = True,
) -> dict[str, Any]:
    """Build a compact summary contract for UI/report overview surfaces."""
    phase1 = resolve_phase1_case_result(pr, load_artifact=load_artifact)
    if phase1 is None:
        case_count = int(getattr(pr, "phase1_case_count", 0) or 0)
        return {
            "available": case_count > 0,
            "metadata_only": case_count > 0,
            "run_id": getattr(pr, "phase1_case_run_id", None),
            "case_count": case_count,
            "macro_finding_count": int(getattr(pr, "phase1_macro_finding_count", 0) or 0),
            "macro_findings": [],
            "top_theme_ids": list(getattr(pr, "phase1_top_theme_ids", []) or []),
            "top_theme_labels": [],
            "themes": [],
            "queues": [],
        }

    queue_summaries = _queue_summaries(phase1)
    low_signal_summary = _low_signal_summary(pr, phase1)
    if low_signal_summary is not None:
        queue_summaries.append(low_signal_summary)
    return {
        "available": True,
        "metadata_only": False,
        "schema_version": phase1.schema_version,
        "run_id": phase1.run_id,
        "case_count": len(phase1.cases),
        "macro_finding_count": int(phase1.metadata.get("macro_finding_count", 0) or 0),
        "macro_findings": list(phase1.metadata.get("macro_findings", []) or [])[:5],
        "top_theme_ids": [theme.theme_id for theme in phase1.theme_summaries[:3]],
        "top_theme_labels": [theme.theme_label for theme in phase1.theme_summaries[:3]],
        "queues": queue_summaries,
        "top_queue_ids": [queue["queue_id"] for queue in queue_summaries[:3]],
        "top_queue_labels": [queue["queue_label"] for queue in queue_summaries[:3]],
        "themes": [
            {
                "theme_id": theme.theme_id,
                "theme_label": theme.theme_label,
                "case_count": theme.case_count,
                "high_count": theme.high_count,
                "medium_count": theme.medium_count,
                "low_count": theme.low_count,
                "total_amount": theme.total_amount,
                "top_case_ids": list(theme.top_case_ids),
            }
            for theme in phase1.theme_summaries
        ],
    }


def build_phase1_case_queue(
    pr: PipelineResult,
    *,
    queue_id: str | None = None,
    theme_id: str | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Return queue rows for case list views."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []

    items = phase1.cases
    if queue_id == _LOW_SIGNAL_QUEUE_ID:
        items = _low_signal_rows(pr, phase1)
        if theme_id:
            items = []
        if top_n is not None:
            items = items[:top_n]
        return items

    if queue_id:
        queue = str(queue_id)
        items = [
            case
            for case in items
            if case.primary_queue == queue or queue in case.secondary_queues
        ]
    if theme_id:
        items = [case for case in items if case.primary_theme == theme_id]
    items = sorted(
        items,
        key=lambda case: (
            -int(case.exposure_rank or 1_000_000_000),
            case.priority_score,
            case.triage_rank_score,
            case.repeat_months,
            case.total_amount,
            case.rule_count,
        ),
        reverse=True,
    )
    if top_n is not None:
        items = items[:top_n]
    return [_case_row(case, phase1) for case in items]


def build_phase1_data_quality_gate(pr: PipelineResult) -> dict[str, Any]:
    """Return data-quality/contract issues as work items, not global Top-N risk cases."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "items": [], "cases": []}

    cases = [
        case
        for case in phase1.cases
        if case.primary_queue == "data_integrity"
        or case.data_integrity_score > 0
        or any(hit.evidence_type == "data_integrity_failure" for hit in case.raw_rule_hits)
    ]
    rule_items: dict[str, dict[str, Any]] = {}
    for case in cases:
        for hit in case.raw_rule_hits:
            if hit.evidence_type != "data_integrity_failure":
                continue
            item = rule_items.setdefault(
                hit.rule_id,
                {
                    "rule_id": hit.rule_id,
                    "rule_label": _rule_label(hit.rule_id),
                    "document_ids": set(),
                    "case_ids": set(),
                    "score_only_document_ids": set(),
                    "normal_score_only_document_ids": set(),
                    "high_case_ids": set(),
                    "medium_case_ids": set(),
                    "actions": [],
                    "review_focus": _rule_focus(hit.rule_id),
                    "strongest_signal": 0.0,
                },
            )
            item["document_ids"].add(hit.document_id)
            item["case_ids"].add(case.case_id)
            item["strongest_signal"] = max(
                item["strongest_signal"],
                float(hit.normalized_score or hit.score or 0.0),
            )
            if case.priority_band == "high":
                item["high_case_ids"].add(case.case_id)
            elif case.priority_band == "medium":
                item["medium_case_ids"].add(case.case_id)
            for action in _rule_actions(hit.rule_id):
                if action not in item["actions"]:
                    item["actions"].append(action)

    _add_data_quality_score_rows(pr, rule_items)

    items = []
    for item in rule_items.values():
        items.append(
            {
                "rule_id": item["rule_id"],
                "rule_label": item["rule_label"],
                "documents": len(item["document_ids"]),
                "cases": len(item["case_ids"]),
                "score_only_documents": len(item["score_only_document_ids"]),
                "normal_score_only_documents": len(item["normal_score_only_document_ids"]),
                "high_cases": len(item["high_case_ids"]),
                "medium_cases": len(item["medium_case_ids"]),
                "review_focus": item["review_focus"],
                "actions": item["actions"],
                "strongest_signal": item["strongest_signal"],
            }
        )
    items.sort(
        key=lambda row: (
            row["documents"],
            row["high_cases"],
            row["strongest_signal"],
            row["rule_id"],
        ),
        reverse=True,
    )
    return {
        "available": True,
        "items": items,
        "cases": [_case_row(case, phase1) for case in cases],
        "document_count": len(
            {doc for item in rule_items.values() for doc in item["document_ids"]}
        ),
        "case_count": len(cases),
    }


def build_phase1_integrity_rule_view(
    pr: PipelineResult,
    rule_ids: list[str] | tuple[str, ...] | set[str],
) -> dict[str, Any]:
    """Aggregate case-level rule hits for the supplied rule whitelist.

    데이터 정합성 탭에서 evidence_type 이 data_integrity_failure 가 아닌
    룰(L1-04~L1-09 control_failure, L1-03/L3-01 logic_mismatch,
    L3-04/L3-07 timing_anomaly 등)을 카테고리별 보조 카드로 노출하기 위해
    phase1.cases 의 raw_rule_hits 를 룰 단위로 집계한다.
    """
    phase1 = resolve_phase1_case_result(pr)
    rule_set = {str(rid) for rid in rule_ids}
    if phase1 is None or not rule_set:
        return {"available": False, "items": [], "document_count": 0, "case_count": 0}

    rule_items: dict[str, dict[str, Any]] = {}
    matched_case_ids: set[str] = set()
    for case in phase1.cases:
        case_matched = False
        for hit in case.raw_rule_hits:
            if hit.rule_id not in rule_set:
                continue
            case_matched = True
            item = rule_items.setdefault(
                hit.rule_id,
                {
                    "rule_id": hit.rule_id,
                    "rule_label": _rule_label(hit.rule_id),
                    "document_ids": set(),
                    "case_ids": set(),
                    "high_case_ids": set(),
                    "medium_case_ids": set(),
                    "actions": [],
                    "review_focus": _rule_focus(hit.rule_id),
                    "strongest_signal": 0.0,
                },
            )
            item["document_ids"].add(hit.document_id)
            item["case_ids"].add(case.case_id)
            item["strongest_signal"] = max(
                item["strongest_signal"],
                float(hit.normalized_score or hit.score or 0.0),
            )
            if case.priority_band == "high":
                item["high_case_ids"].add(case.case_id)
            elif case.priority_band == "medium":
                item["medium_case_ids"].add(case.case_id)
            for action in _rule_actions(hit.rule_id):
                if action not in item["actions"]:
                    item["actions"].append(action)
        if case_matched:
            matched_case_ids.add(case.case_id)

    items = []
    for value in rule_items.values():
        items.append(
            {
                "rule_id": value["rule_id"],
                "rule_label": value["rule_label"],
                "documents": len(value["document_ids"]),
                "cases": len(value["case_ids"]),
                "high_cases": len(value["high_case_ids"]),
                "medium_cases": len(value["medium_case_ids"]),
                "review_focus": value["review_focus"],
                "actions": value["actions"],
                "strongest_signal": value["strongest_signal"],
            }
        )
    items.sort(
        key=lambda row: (
            row["documents"],
            row["high_cases"],
            row["strongest_signal"],
            row["rule_id"],
        ),
        reverse=True,
    )

    return {
        "available": True,
        "items": items,
        "document_count": len(
            {doc for value in rule_items.values() for doc in value["document_ids"]}
        ),
        "case_count": len(matched_case_ids),
    }


def build_phase1_rule_document_counts(pr: PipelineResult) -> dict[str, int]:
    """Return rule_id -> PHASE1 risk case count.

    The dashboard rule pills are case-centric. A broad review population or macro
    candidate is not counted unless it survived into a generated PHASE1 case as
    raw rule-hit evidence. The same case can contribute to multiple rules, but a
    rule is counted at most once per case even when multiple documents in that
    case carry the same rule hit.
    """
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {}

    case_sets: dict[str, set[str]] = {}
    for case in phase1.cases:
        case_id = str(case.case_id or "").strip()
        if not case_id:
            continue
        for hit in case.raw_rule_hits:
            rule_id = str(hit.rule_id or "").strip()
            if not rule_id:
                continue
            case_sets.setdefault(rule_id, set()).add(case_id)
    return {rule_id: len(case_ids) for rule_id, case_ids in case_sets.items()}


def build_phase1_rule_documents(
    pr: PipelineResult,
    rule_id: str,
) -> list[dict[str, Any]]:
    """Return distinct document rows hit by a single rule.

    pr.data 에서 해당 룰이 매칭된 row 를 직접 추출해 가능한 모든 원본
    GL 컬럼(document_type, fiscal_period, line_text, approved_by 등)을
    함께 반환한다. 같은 document_id 의 첫 row 를 대표로 사용하고,
    case_id/priority_band 는 phase1.cases 메타데이터로 보강한다.
    """
    target = str(rule_id)
    if not target:
        return []

    data = _feature_frame(pr)
    if data is None or data.empty or "document_id" not in data.columns:
        return []

    rule_text = _rule_text_series(data)
    mask = rule_text.map(lambda value: target in _rule_tokens(value))
    if not bool(mask.any()):
        return []

    relevant = data.loc[mask].copy()
    doc_groups = _document_groups(data, relevant["document_id"])

    # phase1.cases 메타로 case_id/priority_band 매핑 (있는 doc만 보강)
    phase1 = resolve_phase1_case_result(pr)
    case_meta: dict[str, dict[str, Any]] = {}
    if phase1 is not None:
        for case in phase1.cases:
            case_doc_ids = {
                str(hit.document_id)
                for hit in case.raw_rule_hits
                if hit.rule_id == target
            }
            for doc in case.documents:
                doc_id = str(doc.document_id)
                if doc_id in case_doc_ids or target in (doc.matched_rules or []):
                    case_meta.setdefault(
                        doc_id,
                        {
                            "case_id": case.case_id,
                            "priority_band": case.priority_band,
                            "counterparty": doc.counterparty,
                        },
                    )

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for _, record in relevant.iterrows():
        doc_id = str(record.get("document_id") or "").strip()
        if not doc_id or doc_id.lower() == "nan" or doc_id in seen:
            continue
        seen.add(doc_id)
        meta = case_meta.get(doc_id, {})
        amount = _row_amount(record)
        evidence = _rule_document_evidence(
            target,
            record,
            doc_groups.get(doc_id),
            amount,
        )
        rows.append(
            {
                "document_id": doc_id,
                **evidence,
                "posting_date": _row_value(record, "posting_date"),
                "document_date": _row_value(record, "document_date"),
                "fiscal_period": _row_value(record, "fiscal_period"),
                "company_code": _row_value(record, "company_code"),
                "document_type": _row_value(record, "document_type"),
                "business_process": _row_value(record, "business_process"),
                "source": _row_value(record, "source"),
                "created_by": _row_value(record, "created_by"),
                "approved_by": _row_value(record, "approved_by"),
                "approved_at": _row_value(record, "approved_at"),
                "approval_limit": _row_value(record, "approval_limit"),
                "gl_account": _row_value(record, "gl_account"),
                "counterparty": _row_value(record, "counterparty") or meta.get("counterparty"),
                "line_text": _row_value(record, "line_text"),
                "reference": _row_value(record, "reference"),
                "amount": amount,
                "debit_amount": _row_numeric(record, "debit_amount"),
                "credit_amount": _row_numeric(record, "credit_amount"),
                "local_amount": _row_numeric(record, "local_amount"),
                "risk_level": _row_value(record, "risk_level"),
                "anomaly_score": _row_numeric(record, "anomaly_score"),
                "flagged_rules": _row_value(record, "flagged_rules"),
                "review_rules": _row_value(record, "review_rules"),
                "case_id": meta.get("case_id"),
                "priority_band": meta.get("priority_band"),
            }
        )

    rows.sort(
        key=lambda row: (
            -float(row.get("amount") or 0.0),
            str(row.get("posting_date") or ""),
            str(row.get("document_id") or ""),
        )
    )
    return rows


def build_phase1_rule_document_detail(
    pr: PipelineResult,
    rule_id: str,
    document_id: str,
) -> dict[str, Any] | None:
    """Return detail-panel data for one rule/document selection."""
    target = str(rule_id or "").strip()
    doc_id = str(document_id or "").strip()
    if not target or not doc_id:
        return None

    master_rows = build_phase1_rule_documents(pr, target)
    selected = next(
        (row for row in master_rows if str(row.get("document_id") or "") == doc_id),
        None,
    )
    if selected is None:
        return None

    data = _feature_frame(pr)
    raw_lines: list[dict[str, Any]] = []
    if data is not None and not data.empty and "document_id" in data.columns:
        subset = data[data["document_id"].astype(str) == doc_id]
        raw_lines = [_jsonable_record(row) for row in subset.to_dict("records")]

    related_cases: list[dict[str, Any]] = []
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is not None:
        for case in phase1.cases:
            case_doc_ids = {str(doc.document_id) for doc in case.documents}
            case_hit_docs = {
                str(hit.document_id)
                for hit in case.raw_rule_hits
                if str(hit.rule_id) == target
            }
            if doc_id not in case_doc_ids and doc_id not in case_hit_docs:
                continue
            related_cases.append(
                {
                    "case_id": case.case_id,
                    "priority_band": case.priority_band,
                    "primary_queue": case.primary_queue,
                    "primary_theme": case.primary_theme,
                    "document_count": case.document_count,
                    "rule_count": case.rule_count,
                }
            )

    return {
        "rule_id": target,
        "document_id": doc_id,
        "violation_summary": selected.get("violation_summary")
        or selected.get("evidence_summary"),
        "violation_details": selected.get("violation_details") or [],
        "review_point": selected.get("review_point"),
        "master_row": selected,
        "raw_lines": raw_lines,
        "related_cases": related_cases,
    }


def _jsonable_record(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        result[key] = _jsonable_value(value)
    return result


def _jsonable_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
    except Exception:  # noqa: BLE001
        pass
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:  # noqa: BLE001
        pass
    return value


def _document_groups(data: Any, document_ids: Any) -> dict[str, Any]:
    if data is None or data.empty or "document_id" not in data.columns:
        return {}
    wanted = {
        str(value).strip()
        for value in document_ids.dropna().astype(str).unique()
        if str(value).strip() and str(value).strip().lower() != "nan"
    }
    if not wanted:
        return {}
    subset = data[data["document_id"].astype(str).isin(wanted)]
    return {str(doc_id): group for doc_id, group in subset.groupby("document_id", sort=False)}


def _rule_document_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    builder = _EVIDENCE_BUILDERS.get(rule_id, _generic_evidence)
    try:
        return builder(rule_id, record, doc_rows, amount)
    except Exception:  # noqa: BLE001
        logger.debug("Phase1 evidence build failed for %s", rule_id, exc_info=True)
        return _generic_evidence(rule_id, record, doc_rows, amount)


def _ev(
    summary: str,
    expected: Any,
    actual: Any,
    difference: Any,
    review_point: str,
    amount: float,
    *,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detail_items = details or [
        _detail_item("Expected / baseline", expected),
        _detail_item("Actual", actual),
        _detail_item("Difference / excess", difference, kind="delta"),
    ]
    return {
        "violation_summary": summary,
        "violation_details": detail_items,
        "evidence_summary": summary,
        "expected_value": expected,
        "actual_value": actual,
        "difference_value": difference,
        "review_point": review_point,
        "evidence_amount": amount,
    }


def _detail_item(
    label: str,
    value: Any,
    *,
    kind: str = "text",
    unit: str | None = None,
) -> dict[str, Any]:
    item = {"label": label, "value": value, "kind": kind}
    if unit:
        item["unit"] = unit
    return item


def _compact(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value) if str(value) else "-"
    if abs(number) >= 1:
        return f"{number:,.0f}"
    return f"{number:,.3f}"


def _sum_amount(doc_rows: Any, column: str) -> float:
    if doc_rows is None or getattr(doc_rows, "empty", True) or column not in doc_rows.columns:
        return 0.0
    import pandas as pd

    return float(pd.to_numeric(doc_rows[column], errors="coerce").fillna(0.0).sum())


def _value(record: Any, column: str, default: str = "-") -> Any:
    value = _row_value(record, column)
    if value is None or value == "":
        return default
    return value


def _family(account: Any) -> str:
    text = str(account or "").strip()
    if not text:
        return "-"
    return {
        "1": "asset",
        "2": "liability",
        "3": "equity",
        "4": "revenue",
        "5": "expense",
        "6": "expense",
        "7": "expense",
        "8": "expense",
    }.get(text[:1], "unknown")


def _posting_month(record: Any) -> int | None:
    value = _row_value(record, "posting_date")
    if value is None:
        return None
    import pandas as pd

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return int(parsed.month)


def _date_gap(record: Any) -> int | None:
    posting = _row_value(record, "posting_date")
    document = _row_value(record, "document_date")
    if posting is None or document is None:
        return None
    import pandas as pd

    posting_date = pd.to_datetime(posting, errors="coerce")
    document_date = pd.to_datetime(document, errors="coerce")
    if pd.isna(posting_date) or pd.isna(document_date):
        return None
    return int((posting_date - document_date).days)


def _generic_evidence(rule_id: str, record: Any, doc_rows: Any, amount: float) -> dict[str, Any]:
    return _ev(
        f"{rule_id} 신호",
        "룰 정책 참조",
        _value(record, "line_text", _value(record, "gl_account")),
        "",
        "전표를 열어 해당 룰이 매칭된 원천 증거를 확인하세요.",
        amount,
    )


def _balance_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    debit = _sum_amount(doc_rows, "debit_amount") or float(
        _row_numeric(record, "debit_amount") or 0.0
    )
    credit = _sum_amount(doc_rows, "credit_amount") or float(
        _row_numeric(record, "credit_amount") or 0.0
    )
    diff = debit - credit
    direction = "차변 초과" if diff > 0 else "대변 초과"
    return _ev(
        f"{direction} {_compact(abs(diff))}",
        "차변 합 = 대변 합",
        f"차변 {_compact(debit)} / 대변 {_compact(credit)}",
        abs(diff),
        "전표 라인 합계를 재계산하고, 차이가 큰 라인부터 점검하세요.",
        max(abs(debit), abs(credit), amount),
        details=[
            _detail_item("차변 합계", debit, kind="amount"),
            _detail_item("대변 합계", credit, kind="amount"),
            _detail_item("불일치 금액", abs(diff), kind="amount"),
        ],
    )


def _missing_field_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    required = [
        "document_id",
        "posting_date",
        "document_date",
        "fiscal_period",
        "company_code",
        "document_type",
        "gl_account",
        "debit_amount",
        "credit_amount",
    ]
    missing = [column for column in required if _row_value(record, column) is None]
    return _ev(
        f"누락: {', '.join(missing) if missing else '필수 필드'}",
        "필수 필드 모두 채워짐",
        f"{len(missing)}개 누락",
        len(missing),
        "원천 필드를 복구하거나, 추적이 회복될 때까지 해당 전표를 분리·보류하세요.",
        amount,
        details=[
            _detail_item("누락 개수", len(missing), kind="number"),
            _detail_item("누락 필드", ", ".join(missing) if missing else "-", kind="text"),
        ],
    )


def _invalid_account_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    account = _value(record, "gl_account")
    return _ev(
        f"미존재 계정 {account}",
        "계정과목표(CoA)에 등록된 계정",
        account,
        "마스터 부재",
        "CoA 마스터, 매핑 프로파일, 임시 계정 사용 여부를 점검하세요.",
        amount,
        details=[
            _detail_item("계정", account, kind="text"),
            _detail_item("기준", "계정과목표(CoA)에 등록", kind="text"),
            _detail_item("예외 사유", "마스터 부재", kind="text"),
        ],
    )


def _approval_limit_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    limit = float(_row_numeric(record, "approval_limit") or 0.0)
    excess = amount - limit if limit else ""
    return _ev(
        f"한도 {_compact(excess)} 초과" if limit else "승인 한도 초과",
        f"승인 한도 {_compact(limit)}",
        f"전표 금액 {_compact(amount)}",
        excess,
        "전기일 기준 승인 위임 및 승인 매트릭스를 확인하세요.",
        amount,
        details=[
            _detail_item("승인 한도", limit, kind="amount"),
            _detail_item("전표 금액", amount, kind="amount"),
            _detail_item("초과 금액", excess, kind="amount"),
        ],
    )


def _self_approval_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    created = _value(record, "created_by")
    approved = _value(record, "approved_by")
    return _ev(
        f"{created}이(가) 작성·승인 동시 수행",
        "작성자·승인자 분리",
        f"{created} / {approved}",
        "동일인",
        "자기 승인 예외, 상시 승인 권한, 보완 통제 여부를 확인하세요.",
        amount,
        details=[
            _detail_item("작성자", created, kind="user"),
            _detail_item("승인자", approved, kind="user"),
            _detail_item("예외 사유", "동일인", kind="text"),
        ],
    )


def _sod_evidence(rule_id: str, record: Any, doc_rows: Any, amount: float) -> dict[str, Any]:
    return _ev(
        f"SoD 충돌: {_value(record, 'sod_conflict_type', '충돌')}",
        "직무 충돌 없음",
        f"{_value(record, 'created_by')} / {_value(record, 'business_process')}",
        "충돌",
        "역할 부여와 실제 거래 증빙을 함께 확인하세요.",
        amount,
        details=[
            _detail_item("사용자", _value(record, "created_by"), kind="user"),
            _detail_item("프로세스", _value(record, "business_process"), kind="text"),
            _detail_item("충돌 유형", _value(record, "sod_conflict_type", "충돌"), kind="text"),
        ],
    )


def _approval_missing_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    field = "approval_date" if rule_id == "L1-09" else "approved_by"
    field_label = "승인일자" if field == "approval_date" else "승인자"
    return _ev(
        f"{field_label} 누락",
        f"{field_label} 입력됨",
        _value(record, field, "누락"),
        "누락",
        "GL 추출본 외부 워크플로우 로그에 승인 기록이 있는지 확인하세요.",
        amount,
        details=[
            _detail_item("필요 필드", field_label, kind="text"),
            _detail_item("관찰 값", _value(record, field, "누락"), kind="text"),
            _detail_item("예외 사유", "누락", kind="text"),
        ],
    )


def _period_evidence(rule_id: str, record: Any, doc_rows: Any, amount: float) -> dict[str, Any]:
    expected = _posting_month(record)
    actual = _row_numeric(record, "fiscal_period")
    diff = (float(actual) - float(expected)) if expected is not None and actual is not None else ""
    expected_text = f"{int(expected)}월" if expected is not None else "-"
    actual_text = f"{int(actual)}기" if actual is not None else "-"
    return _ev(
        f"전기일 {expected_text} ≠ 회계기간 {actual_text}",
        expected,
        actual,
        diff,
        "회계연도 정책, 특별기간 운영, 기간 변경 근거를 확인하세요.",
        amount,
        details=[
            _detail_item("전기일 월", expected, kind="number", unit="월"),
            _detail_item("회계기간", actual, kind="number", unit="기"),
            _detail_item("기간 차이", diff, kind="delta", unit="개월"),
        ],
    )


def _near_limit_evidence(rule_id: str, record: Any, doc_rows: Any, amount: float) -> dict[str, Any]:
    limit = float(_row_numeric(record, "approval_limit") or 0.0)
    ratio = amount / limit if limit else None
    return _ev(
        f"승인 한도의 {_compact((ratio or 0) * 100)}% 사용",
        "근접 임계 구간 외",
        f"{_compact(amount)} / {_compact(limit)}",
        ratio,
        "분할 구매, 한도 근접 반복 승인, 승인자 선택 패턴을 확인하세요.",
        amount,
        details=[
            _detail_item("전표 금액", amount, kind="amount"),
            _detail_item("승인 한도", limit, kind="amount"),
            _detail_item("한도 사용률", ratio, kind="ratio"),
        ],
    )


def _relationship_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    spec = _RELATIONSHIP_RULES[rule_id]
    return _ev(
        spec["summary"],
        spec["expected"],
        f"{_value(record, 'counterparty')} / {_compact(amount)} / {_value(record, 'reference')}",
        spec["difference"],
        spec["review"],
        amount,
        details=[
            _detail_item("거래처", _value(record, "counterparty"), kind="text"),
            _detail_item("금액", amount, kind="amount"),
            _detail_item("참조번호", _value(record, "reference"), kind="text"),
            _detail_item("예외 사유", spec["difference"], kind="text"),
        ],
    )


def _classification_evidence(
    rule_id: str,
    record: Any,
    doc_rows: Any,
    amount: float,
) -> dict[str, Any]:
    account = _value(record, "gl_account")
    spec = _CLASSIFICATION_RULES[rule_id]
    return _ev(
        spec["summary"].format(
            account=account,
            family=_family(account),
            process=_value(record, "business_process"),
        ),
        spec["expected"],
        f"{account} ({_family(account)})",
        spec["difference"],
        spec["review"],
        amount,
        details=[
            _detail_item("계정", account, kind="text"),
            _detail_item("계정 분류", _family(account), kind="text"),
            _detail_item("프로세스", _value(record, "business_process"), kind="text"),
            _detail_item("예외 사유", spec["difference"], kind="text"),
        ],
    )


def _timing_evidence(rule_id: str, record: Any, doc_rows: Any, amount: float) -> dict[str, Any]:
    spec = _TIMING_RULES[rule_id]
    gap = _date_gap(record)
    actual = f"{_value(record, 'document_date')} → {_value(record, 'posting_date')}"
    return _ev(
        spec["summary"].format(date=_value(record, "posting_date"), gap=_compact(gap)),
        spec["expected"],
        actual,
        gap if gap is not None else spec["difference"],
        spec["review"],
        amount,
        details=[
            _detail_item("증빙일", _value(record, "document_date"), kind="date"),
            _detail_item("전기일", _value(record, "posting_date"), kind="date"),
            _detail_item("일자 차이", gap if gap is not None else "-", kind="delta", unit="일"),
        ],
    )


def _stat_evidence(rule_id: str, record: Any, doc_rows: Any, amount: float) -> dict[str, Any]:
    spec = _STAT_RULES[rule_id]
    score = _row_numeric(record, "anomaly_score")
    return _ev(
        spec["summary"].format(amount=_compact(amount)),
        spec["expected"],
        spec["actual"].format(
            amount=_compact(amount),
            account=_value(record, "gl_account"),
            company=_value(record, "company_code"),
            source=_value(record, "source"),
            user=_value(record, "created_by"),
        ),
        score if score is not None else spec["difference"],
        spec["review"],
        amount,
        details=[
            _detail_item("회사", _value(record, "company_code"), kind="text"),
            _detail_item("계정", _value(record, "gl_account"), kind="text"),
            _detail_item("금액", amount, kind="amount"),
            _detail_item("점수", score if score is not None else spec["difference"], kind="score"),
        ],
    )


_RELATIONSHIP_RULES = {
    "L2-02": {
        "summary": "중복 지급 의심",
        "expected": "거래처·참조번호·지급 단일성",
        "difference": "지급 속성 일치",
        "review": "쌍 전표·지급 참조·은행 결제·역분개 여부를 비교 확인하세요.",
    },
    "L2-03": {
        "summary": "중복 전표 의심",
        "expected": "유일한 전표",
        "difference": "중복 시그니처",
        "review": "원전표와 중복 전표의 일자·금액·계정·적요를 비교하세요.",
    },
    "L2-03a": {
        "summary": "완전 일치 중복 전표",
        "expected": "유일한 전표",
        "difference": "완전 일치 중복",
        "review": "원전표·중복 전표·역분개 여부·전표 출처를 비교하세요.",
    },
    "L2-03b": {
        "summary": "유사 중복 전표",
        "expected": "근접 중복 없음",
        "difference": "유사 중복 시그니처",
        "review": "금액·일자·계정·적요 유사성과 거래 근거를 비교하세요.",
    },
    "L2-03c": {
        "summary": "분할 전표 패턴 의심",
        "expected": "설명 가능한 분할 전기 없음",
        "difference": "분할 중복 패턴",
        "review": "여러 전표가 단일 거래·승인 한도를 분할한 것인지 확인하세요.",
    },
    "L2-03d": {
        "summary": "연속 중복 전표 의심",
        "expected": "연속된 동일 전표 패턴 없음",
        "difference": "연속 중복 패턴",
        "review": "인접 전표번호·배치 출처·반복 라인 시그니처를 점검하세요.",
    },
    "L2-05": {
        "summary": "역분개 의심 패턴",
        "expected": "설명되지 않는 역분개 없음",
        "difference": "반대 금액/일자 패턴",
        "review": "원분개와 매칭하여 취소·정정·은폐 근거를 확인하세요.",
    },
    "L3-03": {
        "summary": "관계사·내부거래 신호",
        "expected": "내부거래 거래처·결제 매칭",
        "difference": "내부거래 검토",
        "review": "거래 상대 전표·금액·시점·연결제거 처리를 매칭 확인하세요.",
    },
    "IC01": {
        "summary": "내부거래 거래처 예외",
        "expected": "유효한 내부거래 거래처 매칭",
        "difference": "거래처 불일치",
        "review": "거래처 매핑·상대 전표·연결제거 처리 여부를 확인하세요.",
    },
    "IC02": {
        "summary": "내부거래 금액 불일치",
        "expected": "내부거래 양쪽 금액 일치",
        "difference": "금액 불일치",
        "review": "내부거래 양면 전표와 결제 증빙을 비교하세요.",
    },
    "IC03": {
        "summary": "내부거래 시점 불일치",
        "expected": "내부거래 양쪽 시점 일치",
        "difference": "시점 불일치",
        "review": "양쪽 회계기간·컷오프 처리·후속 결제를 비교하세요.",
    },
}

_CLASSIFICATION_RULES = {
    "L2-04": {
        "summary": "{family} 계정에 비용성 항목 분개",
        "expected": "비용 계정 또는 자본화 근거",
        "difference": "분류 불일치",
        "review": "송장 성격·자본화 메모·자산 마스터 생성 여부를 점검하세요.",
    },
    "L3-01": {
        "summary": "{process} 프로세스에 {family} 계정 사용",
        "expected": "프로세스에 부합하는 계정 분류",
        "difference": "프로세스/계정 불일치",
        "review": "계정과목 분류·프로세스 컨텍스트·예외 승인을 확인하세요.",
    },
    "L3-09": {
        "summary": "장기 미해소 임시·반제 계정 {account}",
        "expected": "정책 윈도우 내 해소",
        "difference": "장기 미해소",
        "review": "미해소 잔액 경과·반제 전표·담당자 해소 계획을 점검하세요.",
    },
    "L3-10": {
        "summary": "민감 계정 사용: {account}",
        "expected": "맥락 없는 고위험 계정 사용 없음",
        "difference": "민감 계정",
        "review": "계정 사용 목적·승인·연관 룰 조합을 확인하세요.",
    },
    "L3-12": {
        "summary": "{process} 광범위 작업 범위",
        "expected": "역할에 맞는 회사·프로세스 범위",
        "difference": "범위 검토",
        "review": "접근 프로파일·프로세스 책임·충돌 활동을 점검하세요.",
    },
    "L4-04": {
        "summary": "드문 계정 조합 ({account} 포함)",
        "expected": "프로세스 내 일반적 계정 조합",
        "difference": "과거 빈도 낮음",
        "review": "전표 전체 라인을 열람하고 정당한 회계 경로인지 확인하세요.",
    },
}

_TIMING_RULES = {
    "L3-04": {
        "summary": "기말 경계 전기: {date}",
        "expected": "정상 결산 주기 또는 승인된 결산 분개",
        "difference": "기말 집중",
        "review": "결산 일정·승인 근거·민감 계정 영향을 확인하세요.",
    },
    "L3-05": {
        "summary": "주말·공휴일 전기: {date}",
        "expected": "영업일 전기 또는 배치 예외",
        "difference": "비영업일",
        "review": "정기 배치 일정·긴급 승인·소급 전기 여부를 확인하세요.",
    },
    "L3-06": {
        "summary": "야간·근무외 전기: {date}",
        "expected": "근무시간 내 전기",
        "difference": "근무외 시간",
        "review": "로그인·워크플로우 로그와 배치 사용자 여부를 확인하세요.",
    },
    "L3-07": {
        "summary": "전기일·증빙일 간격 {gap}일",
        "expected": "허용 일자 간격 이내",
        "difference": "일자 간격",
        "review": "컷오프 기준·송장 지연 수령·소급 전기 승인을 확인하세요.",
    },
    "L3-11": {
        "summary": "컷오프 일자 간격 {gap}일",
        "expected": "수익을 정확한 인도·용역 기간에 인식",
        "difference": "컷오프 간격",
        "review": "수익을 인도·용역 증빙과 연결하고 기말 컷오프 테스트를 수행하세요.",
    },
}

_STAT_RULES = {
    "L4-01": {
        "summary": "매출 이상 금액 {amount}",
        "expected": "매출 계정 분포 내",
        "actual": "{account} / {amount}",
        "difference": "이상치 점수",
        "review": "동종 매출 전표·매출 증빙과 비교하세요.",
    },
    "L4-02": {
        "summary": "Benford 분포 편차",
        "expected": "기대 첫자리 분포",
        "actual": "{company} / {account}",
        "difference": "MAD/편차",
        "review": "모집단 정의·편차 지표·기여도 상위 거래를 검토하세요.",
    },
    "L4-03": {
        "summary": "고액 이상치: {amount}",
        "expected": "설정된 백분위 임계 이하",
        "actual": "{amount}",
        "difference": "이상치 점수",
        "review": "거래 근거·승인 단계·증빙 자료를 확인하세요.",
    },
    "L4-05": {
        "summary": "비정상 시간 클러스터",
        "expected": "정상 전기 시간 분포",
        "actual": "{user} / {source}",
        "difference": "클러스터",
        "review": "사용자 군집·동일 분 전기·배치 일정 예외를 확인하세요.",
    },
    "L4-06": {
        "summary": "배치 전기 이상치",
        "expected": "공식 배치 작업 또는 정상 거래량",
        "actual": "{user} / {source}",
        "difference": "배치 이상",
        "review": "배치 작업 ID·실행 로그·비정상 거래량/시간대를 확인하세요.",
    },
    "D01": {
        "summary": "전기 대비 계정 활동 변동",
        "expected": "전기 계정 활동 기준",
        "actual": "{company} / {account}",
        "difference": "변동 점수",
        "review": "당기/전기의 금액·건수·평균 거래규모를 비교하세요.",
    },
    "D02": {
        "summary": "전기 대비 월별 비율 분포 변동",
        "expected": "전기 월별 분포",
        "actual": "{company} / {account}",
        "difference": "분포 점수",
        "review": "월별 분포 변화와 집중 월을 검토하세요.",
    },
}

_EVIDENCE_BUILDERS = {
    "L1-01": _balance_evidence,
    "L1-02": _missing_field_evidence,
    "L1-03": _invalid_account_evidence,
    "L1-04": _approval_limit_evidence,
    "L1-05": _self_approval_evidence,
    "L1-06": _sod_evidence,
    "L1-07": _approval_missing_evidence,
    "L1-08": _period_evidence,
    "L1-09": _approval_missing_evidence,
    "L2-01": _near_limit_evidence,
    **{rule: _relationship_evidence for rule in _RELATIONSHIP_RULES},
    **{rule: _classification_evidence for rule in _CLASSIFICATION_RULES},
    "L3-02": lambda rule_id, record, doc_rows, amount: _ev(
        f"수기 입력: {_value(record, 'source')}",
        "가능한 영역은 자동/인터페이스 처리",
        _value(record, "source"),
        "수기 입력",
        "수기 입력 근거·작성자 권한·자동화 우회 반복 여부를 확인하세요.",
        amount,
    ),
    "L3-08": lambda rule_id, record, doc_rows, amount: _ev(
        "적요 누락 또는 손상",
        "추적 가능한 업무 적요",
        _value(record, "line_text", "누락"),
        "적요 부실",
        "원천 적요와 증빙 추적을 복구하세요.",
        amount,
    ),
    **{rule: _timing_evidence for rule in _TIMING_RULES},
    **{rule: _stat_evidence for rule in _STAT_RULES},
}

PHASE1_RULE_DOCUMENT_RULES = frozenset(_EVIDENCE_BUILDERS)


def _row_value(record: Any, column: str) -> Any:
    if column not in record.index:
        return None
    value = record.get(column)
    try:
        import pandas as pd

        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
    except Exception:  # noqa: BLE001
        pass
    text = str(value)
    if text.lower() == "nan" or text == "NaT":
        return None
    return value


def _row_numeric(record: Any, column: str) -> float | None:
    value = _row_value(record, column)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_amount(record: Any) -> float:
    """Best-effort 거래 금액 — line_amount → debit-credit → local_amount 순."""
    for column in ("line_amount", "amount"):
        if column in record.index:
            value = _row_numeric(record, column)
            if value:
                return value
    debit = _row_numeric(record, "debit_amount") or 0.0
    credit = _row_numeric(record, "credit_amount") or 0.0
    if debit or credit:
        return float(debit - credit)
    local = _row_numeric(record, "local_amount")
    return float(local or 0.0)


def build_phase1_audit_risk_queue(
    pr: PipelineResult,
    *,
    top_n: int | None = 10,
    queue_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return the actual audit-risk Top-N, excluding data-quality gate items."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []
    excluded = {"data_integrity", _LOW_SIGNAL_QUEUE_ID}
    items = [
        case
        for case in phase1.cases
        if case.primary_queue not in excluded
        and case.primary_theme != "data_integrity_failure"
        and _case_signal_counts(case)["direct_risk"] > 0
    ]
    if queue_id:
        items = [
            case
            for case in items
            if case.primary_queue == queue_id or queue_id in case.secondary_queues
        ]
    items = sorted(
        items,
        key=lambda case: (
            _band_rank(case.priority_band),
            case.priority_score,
            _queue_tiebreaker(case, queue_id or case.primary_queue)["score"],
            case.triage_rank_score,
            case.total_amount,
            case.rule_count,
            -case.document_count,
        ),
        reverse=True,
    )
    if top_n is not None:
        items = items[:top_n]
    return [_case_row(case, phase1, tie_queue_id=queue_id) for case in items]


def build_phase1_audit_risk_by_queue(
    pr: PipelineResult,
    *,
    top_n_per_queue: int = 5,
) -> dict[str, Any]:
    """Return audit-risk candidates grouped by audit work queue."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "queues": []}

    queue_order = [
        "control_approval",
        "timing_close",
        "amount_statistical",
        "account_logic",
        "duplicate_outflow",
        "intercompany_cycle",
        "manipulation_candidate",
    ]
    queue_labels = _audit_queue_labels(phase1)
    excluded = {"data_integrity", _LOW_SIGNAL_QUEUE_ID}
    source_cases = [
        case
        for case in phase1.cases
        if case.primary_queue not in excluded
        and case.primary_theme != "data_integrity_failure"
        and _case_signal_counts(case)["direct_risk"] > 0
    ]

    queues = []
    for queue_id in queue_order:
        members = [
            case
            for case in source_cases
            if case.primary_queue == queue_id or queue_id in case.secondary_queues
        ]
        if not members:
            continue
        members = sorted(
            members,
            key=lambda case: (
                _band_rank(case.priority_band),
                case.priority_score,
                _queue_tiebreaker(case, queue_id)["score"],
                case.triage_rank_score,
                case.total_amount,
                case.rule_count,
                -case.document_count,
            ),
            reverse=True,
        )
        queues.append(
            {
                "queue_id": queue_id,
                "queue_label": queue_labels.get(queue_id, queue_id.replace("_", " ")),
                "total_cases": len(members),
                "items": [
                    _case_row(case, phase1, tie_queue_id=queue_id)
                    for case in members[:top_n_per_queue]
                ],
            }
        )
    return {"available": True, "queues": queues}


def build_phase1_review_candidate_summary(pr: PipelineResult) -> dict[str, Any]:
    """Return review/sidecar candidates as type counts, not a Top-N ranking."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "items": []}

    rows: dict[str, dict[str, Any]] = {}
    for case in phase1.cases:
        signal_counts = _case_signal_counts(case)
        is_review = (
            signal_counts["review_context"] > 0
            or signal_counts["macro_finding"] > 0
            or case.primary_queue == _LOW_SIGNAL_QUEUE_ID
            or case.priority_band == "low"
        )
        if not is_review or case.primary_queue == "data_integrity":
            continue
        key = case.primary_queue or case.primary_theme
        row = rows.setdefault(
            key,
            {
                "queue_id": key,
                "queue_label": case.primary_queue_label or key.replace("_", " "),
                "cases": 0,
                "documents": set(),
                "review_hits": 0,
                "direct_hits": 0,
                "high_cases": 0,
                "medium_cases": 0,
                "low_cases": 0,
                "sample_case_ids": [],
                "review_focus": [],
                "actions": [],
            },
        )
        row["cases"] += 1
        row["review_hits"] += signal_counts["review_context"] + signal_counts["macro_finding"]
        row["direct_hits"] += signal_counts["direct_risk"]
        for doc in case.documents:
            row["documents"].add(doc.document_id)
        if case.priority_band == "high":
            row["high_cases"] += 1
        elif case.priority_band == "medium":
            row["medium_cases"] += 1
        else:
            row["low_cases"] += 1
        if len(row["sample_case_ids"]) < 5:
            row["sample_case_ids"].append(case.case_id)
        for focus in case.review_focus:
            if focus not in row["review_focus"]:
                row["review_focus"].append(focus)
        for action in case.recommended_audit_actions:
            if action not in row["actions"]:
                row["actions"].append(action)

    items = []
    for row in rows.values():
        items.append(
            {
                "queue_id": row["queue_id"],
                "queue_label": row["queue_label"],
                "cases": row["cases"],
                "documents": len(row["documents"]),
                "review_hits": row["review_hits"],
                "direct_hits": row["direct_hits"],
                "high_cases": row["high_cases"],
                "medium_cases": row["medium_cases"],
                "low_cases": row["low_cases"],
                "sample_case_ids": row["sample_case_ids"],
                "review_focus": row["review_focus"][:5],
                "actions": row["actions"][:5],
            }
        )
    items.sort(key=lambda row: (row["cases"], row["documents"], row["review_hits"]), reverse=True)
    return {"available": True, "items": items}


def build_phase1_macro_finding_queue(
    pr: PipelineResult,
    *,
    rule_id: str | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Return Account/Process Queue rows for macro findings such as L4-02."""

    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []

    items = list(phase1.metadata.get("macro_findings", []) or [])
    if rule_id:
        rule = str(rule_id)
        items = [item for item in items if str(item.get("rule_id", "")) == rule]
    if top_n is not None:
        items = items[:top_n]
    return items


def _add_data_quality_score_rows(
    pr: PipelineResult,
    rule_items: dict[str, dict[str, Any]],
) -> None:
    data = _feature_frame(pr)
    if data is None or data.empty or "document_id" not in data.columns:
        return
    rule_text = _rule_text_series(data)
    data_quality_rules = rule_text.map(lambda value: _rule_tokens(value) & _INTEGRITY_RULES)
    mask = data["document_id"].notna() & data_quality_rules.map(bool)
    if not bool(mask.any()):
        return

    score = _to_numeric(data["anomaly_score"]) if "anomaly_score" in data.columns else None
    risk = (
        data["risk_level"].fillna("").astype(str).str.lower()
        if "risk_level" in data.columns
        else None
    )
    rows = data.loc[mask, ["document_id"]].copy()
    rows["_rules"] = data_quality_rules[mask]
    rows["_score"] = score[mask] if score is not None else 0.0
    rows["_risk"] = risk[mask] if risk is not None else ""

    seen: set[tuple[str, str]] = set()
    for _, row in rows.iterrows():
        document_id = str(row["document_id"])
        if not document_id or document_id.lower() == "nan":
            continue
        for rule_id in row["_rules"]:
            key = (rule_id, document_id)
            if key in seen:
                continue
            seen.add(key)
            item = rule_items.setdefault(
                rule_id,
                {
                    "rule_id": rule_id,
                    "rule_label": _rule_label(rule_id),
                    "document_ids": set(),
                    "case_ids": set(),
                    "score_only_document_ids": set(),
                    "normal_score_only_document_ids": set(),
                    "high_case_ids": set(),
                    "medium_case_ids": set(),
                    "actions": list(_rule_actions(rule_id)),
                    "review_focus": _rule_focus(rule_id),
                    "strongest_signal": 0.0,
                },
            )
            in_case = document_id in item["document_ids"]
            item["document_ids"].add(document_id)
            item["strongest_signal"] = max(
                item["strongest_signal"],
                float(row["_score"] or 0.0),
            )
            if not in_case:
                item["score_only_document_ids"].add(document_id)
                if str(row["_risk"]).lower() == "normal":
                    item["normal_score_only_document_ids"].add(document_id)
            for action in _rule_actions(rule_id):
                if action not in item["actions"]:
                    item["actions"].append(action)


def build_phase1_case_drilldown(pr: PipelineResult, case_id: str) -> dict[str, Any] | None:
    """Return a drill-down payload for a single case."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return None

    case = next((item for item in phase1.cases if item.case_id == case_id), None)
    if case is None:
        if str(case_id).startswith(f"{_LOW_SIGNAL_QUEUE_ID}:"):
            return _low_signal_drilldown(pr, phase1, case_id)
        return None

    raw_rule_hits = [_raw_hit_row(hit) for hit in case.raw_rule_hits]
    return {
        "case": _case_row(case, phase1),
        "documents": [
            {
                "document_id": doc.document_id,
                "posting_date": doc.posting_date,
                "created_by": doc.created_by,
                "business_process": doc.business_process,
                "gl_account": doc.gl_account,
                "counterparty": doc.counterparty,
                "amount": doc.amount,
                "matched_rules": list(doc.matched_rules),
                "evidence_tags": list(doc.evidence_tags),
            }
            for doc in case.documents
        ],
        "raw_rule_hits": raw_rule_hits,
        "signal_sections": {
            signal_type: [row for row in raw_rule_hits if row["signal_type"] == signal_type]
            for signal_type in (
                "direct_risk",
                "review_context",
                "integrity_blocker",
                "macro_finding",
            )
        },
    }


def _case_row(
    case: CaseGroupResult,
    phase1: Phase1CaseResult,
    *,
    tie_queue_id: str | None = None,
) -> dict[str, Any]:
    signal_counts = _case_signal_counts(case)
    tie = _queue_tiebreaker(case, tie_queue_id or case.primary_queue)
    return {
        "case_id": case.case_id,
        "primary_theme": case.primary_theme,
        "primary_theme_label": _theme_label(phase1, case.primary_theme),
        "primary_queue": case.primary_queue,
        "primary_queue_label": case.primary_queue_label,
        "secondary_queues": list(case.secondary_queues),
        "secondary_queue_labels": list(case.secondary_queue_labels),
        "secondary_tags": list(case.secondary_tags),
        "case_key": case.case_key,
        "case_key_parts": dict(case.case_key_parts),
        "priority_score": case.priority_score,
        "base_priority_score": case.base_priority_score,
        "topside_bonus": case.topside_bonus,
        "batch_combo_bonus": case.batch_combo_bonus,
        "weak_evidence_bonus": case.weak_evidence_bonus,
        "l301_priority_bonus": case.l301_priority_bonus,
        "priority_adjustment_reasons": list(case.priority_adjustment_reasons),
        "priority_band": case.priority_band,
        "triage_rank_score": case.triage_rank_score,
        "triage_rank_reasons": list(case.triage_rank_reasons),
        "queue_tiebreaker_score": tie["score"],
        "queue_tiebreaker_reasons": tie["reasons"],
        "queue_tiebreaker_queue": tie["queue_id"],
        "exposure_rank": case.exposure_rank,
        "theme_rank": case.theme_rank,
        "document_count": case.document_count,
        "row_count": case.row_count,
        "rule_count": case.rule_count,
        "direct_risk_count": signal_counts["direct_risk"],
        "review_context_count": signal_counts["review_context"],
        "integrity_blocker_count": signal_counts["integrity_blocker"],
        "macro_finding_count": signal_counts["macro_finding"],
        "case_type": _case_type(case, signal_counts),
        "main_reason": _main_reason(case),
        "total_amount": case.total_amount,
        "amount_score": case.amount_score,
        "control_score": case.control_score,
        "duplicate_or_outflow_score": case.duplicate_or_outflow_score,
        "logic_score": case.logic_score,
        "data_integrity_score": case.data_integrity_score,
        "intercompany_score": case.intercompany_score,
        "timing_score": case.timing_score,
        "behavior_score": case.behavior_score,
        "repeat_months": case.repeat_months,
        "representative_explanation": case.representative_explanation,
        "review_focus": list(case.review_focus),
        "risk_narrative": case.risk_narrative,
        "recommended_audit_actions": list(case.recommended_audit_actions),
        "rule_evidence_summary": list(case.rule_evidence_summary),
        "evidence_tags": list(case.evidence_tags),
        "has_control_failure": case.has_control_failure,
        "has_high_materiality": case.has_high_materiality,
        "has_repeat_pattern": case.has_repeat_pattern,
    }


def _low_signal_summary(pr: PipelineResult, phase1: Phase1CaseResult) -> dict[str, Any] | None:
    grouped_scores = _low_signal_grouped_scores(pr, phase1)
    if grouped_scores is None or grouped_scores.empty:
        return None
    top_rows = grouped_scores.head(_LOW_SIGNAL_MAX_DOCS)
    case_count = int(len(top_rows))
    return {
        "queue_id": _LOW_SIGNAL_QUEUE_ID,
        "queue_label": _LOW_SIGNAL_QUEUE_LABEL,
        "case_count": case_count,
        "high_count": 0,
        "medium_count": 0,
        "low_count": case_count,
        "total_amount": float(top_rows["total_amount"].sum()),
        "top_case_ids": [
            f"{_LOW_SIGNAL_QUEUE_ID}:{document_id}"
            for document_id in top_rows["_document_id"].astype(str).head(10)
        ],
    }


def _low_signal_rows(
    pr: PipelineResult,
    phase1: Phase1CaseResult,
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    data = _feature_frame(pr)
    if data is None or data.empty:
        return []
    cache_key = (id(data), phase1.run_id, _LOW_SIGNAL_MAX_DOCS)
    cache = getattr(pr, "_phase1_low_signal_projection_cache", None)
    if isinstance(cache, dict) and cache.get("key") == cache_key:
        rows = list(cache.get("rows", []))
        return rows[:top_n] if top_n is not None else rows

    grouped_scores = _low_signal_grouped_scores(pr, phase1)
    if grouped_scores is None or grouped_scores.empty:
        return []
    candidate_docs = set(grouped_scores.head(_LOW_SIGNAL_MAX_DOCS)["_document_id"].astype(str))

    rows = _low_signal_filtered_rows(pr, phase1, candidate_docs)
    if rows is None or rows.empty:
        return []

    score_lookup = {
        str(row["_document_id"]): row
        for row in grouped_scores[grouped_scores["_document_id"].isin(candidate_docs)].to_dict(
            "records"
        )
    }

    grouped: dict[str, dict[str, Any]] = {}
    for _, row in rows.iterrows():
        document_id = str(row["_document_id"])
        score_row = score_lookup[document_id]
        item = grouped.setdefault(
            document_id,
            {
                "document_id": document_id,
                "row_count": 0,
                "priority_score": 0.0,
                "total_amount": 0.0,
                "rules": set(),
                "posting_dates": [],
                "created_by": "",
                "business_process": "",
                "gl_account": "",
                "counterparty": "",
            },
        )
        item["row_count"] += 1
        item["priority_score"] = float(score_row["priority_score"] or 0.0)
        item["total_amount"] = float(score_row["total_amount"] or 0.0)
        item["rules"].update(row["_relevant_rules"])
        if not item["created_by"] and "created_by" in rows.columns:
            item["created_by"] = str(row.get("created_by") or "")
        if not item["business_process"] and "business_process" in rows.columns:
            item["business_process"] = str(row.get("business_process") or "")
        if not item["gl_account"] and "gl_account" in rows.columns:
            item["gl_account"] = str(row.get("gl_account") or "")
        if not item["counterparty"] and "counterparty" in rows.columns:
            item["counterparty"] = str(row.get("counterparty") or "")
        if "posting_date" in rows.columns and row.get("posting_date") is not None:
            item["posting_dates"].append(row.get("posting_date"))

    projected = [_low_signal_case_row(item) for item in grouped.values()]
    projected.sort(
        key=lambda row: (
            row["priority_score"],
            row["rule_count"],
            row["row_count"],
            row["total_amount"],
            row["case_key"],
        ),
        reverse=True,
    )
    try:
        setattr(
            pr,
            "_phase1_low_signal_projection_cache",
            {"key": cache_key, "rows": projected},
        )
    except Exception:
        pass
    return projected[:top_n] if top_n is not None else projected


def _low_signal_grouped_scores(pr: PipelineResult, phase1: Phase1CaseResult) -> Any:
    rows = _low_signal_filtered_rows(pr, phase1)
    if rows is None or rows.empty:
        return None

    rows["_line_amount"] = _amount_series(rows)
    return (
        rows.groupby("_document_id", sort=False)
        .agg(
            priority_score=("_anomaly_score", "max"),
            row_count=("_document_id", "size"),
            total_amount=("_line_amount", lambda values: float(values.abs().sum())),
        )
        .reset_index()
        .sort_values(
            ["priority_score", "row_count", "total_amount", "_document_id"],
            ascending=[False, False, False, False],
        )
    )


def _low_signal_filtered_rows(
    pr: PipelineResult,
    phase1: Phase1CaseResult,
    candidate_docs: set[str] | None = None,
) -> Any:
    data = _feature_frame(pr)
    if data is None or data.empty:
        return None
    required = {"document_id", "risk_level", "anomaly_score"}
    if not required.issubset(data.columns):
        return None

    docs_in_cases = _case_document_ids(phase1)
    doc_ids = data["document_id"].fillna("").astype(str).str.strip()
    score = _to_numeric(data["anomaly_score"])
    risk = data["risk_level"].astype(str).str.lower()
    rule_text = _rule_text_series(data)
    relevant_rules = rule_text.map(_relevant_rule_tokens)
    mask = (
        doc_ids.ne("")
        & ~doc_ids.isin(docs_in_cases)
        & risk.eq("normal")
        & score.gt(0)
        & relevant_rules.map(bool)
    )
    if candidate_docs is not None:
        mask = mask & doc_ids.isin(candidate_docs)
    if not bool(mask.any()):
        return None

    rows = data.loc[mask].copy()
    rows["_document_id"] = doc_ids[mask]
    rows["_anomaly_score"] = score[mask]
    rows["_relevant_rules"] = relevant_rules[mask]
    return rows


def _low_signal_case_row(item: dict[str, Any]) -> dict[str, Any]:
    rules = sorted(item["rules"])
    score = float(item["priority_score"] or 0.0)
    document_id = str(item["document_id"])
    return {
        "case_id": f"{_LOW_SIGNAL_QUEUE_ID}:{document_id}",
        "primary_theme": "low_signal_candidate",
        "primary_theme_label": _LOW_SIGNAL_QUEUE_LABEL,
        "primary_queue": _LOW_SIGNAL_QUEUE_ID,
        "primary_queue_label": _LOW_SIGNAL_QUEUE_LABEL,
        "secondary_queues": [],
        "secondary_queue_labels": [],
        "secondary_tags": ["normal_risk_low_signal"],
        "case_key": document_id,
        "case_key_parts": {"document_id": document_id},
        "priority_score": score,
        "base_priority_score": score,
        "topside_bonus": 0.0,
        "batch_combo_bonus": 0.0,
        "weak_evidence_bonus": 0.0,
        "l301_priority_bonus": 0.0,
        "priority_adjustment_reasons": [],
        "priority_band": "low",
        "triage_rank_score": min(score + min(len(rules), 5) * 0.03, 1.0),
        "triage_rank_reasons": [
            "risk_level=Normal",
            f"weak_signal_rules={len(rules)}",
            "not_mixed_into_main_queue",
        ],
        "exposure_rank": None,
        "theme_rank": None,
        "document_count": 1,
        "row_count": int(item["row_count"]),
        "rule_count": len(rules),
        "direct_risk_count": len([rule for rule in rules if rule not in _REVIEW_CONTEXT_RULES]),
        "review_context_count": len([rule for rule in rules if rule in _REVIEW_CONTEXT_RULES]),
        "integrity_blocker_count": 0,
        "macro_finding_count": 0,
        "case_type": _LOW_SIGNAL_QUEUE_LABEL,
        "main_reason": "Normal risk row with weak PHASE1 signal",
        "total_amount": float(item["total_amount"] or 0.0),
        "amount_score": 0.0,
        "control_score": 0.0,
        "duplicate_or_outflow_score": 0.0,
        "logic_score": 0.0,
        "data_integrity_score": 0.0,
        "intercompany_score": 0.0,
        "timing_score": 0.0,
        "behavior_score": 0.0,
        "repeat_months": 0,
        "representative_explanation": "Normal로 남아 본 queue에는 섞지 않는 약신호 후보입니다.",
        "review_focus": ["약신호 규칙 조합", "전표 단위 근거 확인"],
        "risk_narrative": (
            "위험등급은 Normal이지만 PHASE1 관련 규칙 또는 review 신호가 있어 "
            "별도 후보 queue에 표시됩니다."
        ),
        "recommended_audit_actions": ["필요 시 보조 queue에서 샘플 검토"],
        "rule_evidence_summary": [{"rule_id": rule, "count": 1} for rule in rules],
        "evidence_tags": rules,
        "has_control_failure": False,
        "has_high_materiality": False,
        "has_repeat_pattern": False,
    }


def _low_signal_drilldown(
    pr: PipelineResult,
    phase1: Phase1CaseResult,
    case_id: str,
) -> dict[str, Any] | None:
    rows = _low_signal_rows(pr, phase1, top_n=None)
    case = next((row for row in rows if row["case_id"] == case_id), None)
    if case is None:
        return None
    document_id = str(case["case_key"])
    return {
        "case": case,
        "documents": [
            {
                "document_id": document_id,
                "posting_date": None,
                "created_by": "",
                "business_process": "",
                "gl_account": "",
                "counterparty": "",
                "amount": case["total_amount"],
                "matched_rules": list(case["evidence_tags"]),
                "evidence_tags": list(case["evidence_tags"]),
            }
        ],
        "raw_rule_hits": [],
        "signal_sections": {
            "direct_risk": [],
            "review_context": [],
            "integrity_blocker": [],
            "macro_finding": [],
        },
    }


def _feature_frame(pr: PipelineResult) -> Any:
    featured = getattr(pr, "featured_data", None)
    if featured is not None:
        return featured
    return getattr(pr, "data", None)


def _case_document_ids(phase1: Phase1CaseResult) -> set[str]:
    docs: set[str] = set()
    for case in phase1.cases:
        for doc in case.documents:
            if doc.document_id:
                docs.add(str(doc.document_id))
        for hit in case.raw_rule_hits:
            if hit.document_id:
                docs.add(str(hit.document_id))
    return docs


def _rule_text_series(data: Any) -> Any:
    parts = []
    for column in ("flagged_rules", "review_rules"):
        if column in data.columns:
            parts.append(data[column].fillna("").astype(str))
    if not parts:
        return data["document_id"].fillna("").astype(str).map(lambda _: "")
    result = parts[0]
    for part in parts[1:]:
        result = result + "," + part
    return result


def _relevant_rule_tokens(value: Any) -> set[str]:
    return _rule_tokens(value) & _LOW_SIGNAL_RELEVANT_RULES


def _rule_tokens(value: Any) -> set[str]:
    return {
        token.strip()
        for token in re.split(r"[,|;]", str(value or ""))
        if token.strip() and token.strip().lower() != "nan"
    }


def _to_numeric(series: Any) -> Any:
    import pandas as pd

    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _amount_series(data: Any) -> Any:
    import pandas as pd

    if "line_amount" in data.columns:
        return pd.to_numeric(data["line_amount"], errors="coerce").fillna(0.0)
    debit = (
        pd.to_numeric(data["debit_amount"], errors="coerce").fillna(0.0)
        if "debit_amount" in data.columns
        else 0.0
    )
    credit = (
        pd.to_numeric(data["credit_amount"], errors="coerce").fillna(0.0)
        if "credit_amount" in data.columns
        else 0.0
    )
    return debit - credit


def _raw_hit_row(hit: Any) -> dict[str, Any]:
    signal_type = _signal_type(hit)
    return {
        "rule_id": hit.rule_id,
        "signal_type": signal_type,
        "signal_type_label": _SIGNAL_TYPE_LABELS[signal_type],
        "severity": hit.severity,
        "document_id": hit.document_id,
        "row_index": hit.row_index,
        "record_id": hit.record_id,
        "score": hit.score,
        "signal_strength": hit.signal_strength,
        "normalized_score": hit.normalized_score,
        "evidence_strength": hit.evidence_strength,
        "scoring_role": hit.scoring_role,
        "display_label": hit.display_label,
        "signal_status": hit.signal_status,
        "detail": hit.detail,
        "evidence_type": hit.evidence_type,
    }


def _queue_summaries(phase1: Phase1CaseResult) -> list[dict[str, Any]]:
    by_queue: dict[str, dict[str, Any]] = {}
    for case in phase1.cases:
        queues = [case.primary_queue, *case.secondary_queues]
        for queue_id in queues:
            if not queue_id:
                continue
            row = by_queue.setdefault(
                queue_id,
                {
                    "queue_id": queue_id,
                    "queue_label": _queue_label(case, queue_id),
                    "case_count": 0,
                    "high_count": 0,
                    "medium_count": 0,
                    "low_count": 0,
                    "total_amount": 0.0,
                    "top_case_ids": [],
                },
            )
            row["case_count"] += 1
            band = str(case.priority_band).lower()
            if band == "high":
                row["high_count"] += 1
            elif band == "medium":
                row["medium_count"] += 1
            else:
                row["low_count"] += 1
            row["total_amount"] += float(case.total_amount or 0.0)
            if len(row["top_case_ids"]) < 10:
                row["top_case_ids"].append(case.case_id)
    return sorted(
        by_queue.values(),
        key=lambda row: (
            row["queue_id"] != "manipulation_candidate",
            -int(row["high_count"]),
            -int(row["case_count"]),
            str(row["queue_label"]),
        ),
    )


def _queue_label(case: CaseGroupResult, queue_id: str) -> str:
    if queue_id == case.primary_queue and case.primary_queue_label:
        return case.primary_queue_label
    if queue_id in case.secondary_queues:
        index = case.secondary_queues.index(queue_id)
        if index < len(case.secondary_queue_labels):
            return case.secondary_queue_labels[index]
    return queue_id.replace("_", " ")


def _audit_queue_labels(phase1: Phase1CaseResult) -> dict[str, str]:
    labels: dict[str, str] = {}
    for case in phase1.cases:
        if case.primary_queue and case.primary_queue_label:
            labels.setdefault(case.primary_queue, case.primary_queue_label)
        for queue_id, label in zip(
            case.secondary_queues,
            case.secondary_queue_labels,
            strict=False,
        ):
            if queue_id and label:
                labels.setdefault(queue_id, label)
    return labels


def _band_rank(priority_band: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(priority_band).lower(), 0)


def _queue_tiebreaker(case: CaseGroupResult, queue_id: str | None) -> dict[str, Any]:
    queue = str(queue_id or case.primary_queue or "")
    rule_ids = {str(hit.rule_id) for hit in case.raw_rule_hits}
    signal_counts = _case_signal_counts(case)
    small_case_score = 1.0 / max(int(case.document_count or 1), 1)
    rule_score = min(float(case.rule_count or len(rule_ids)) / 8.0, 1.0)
    direct_score = min(float(signal_counts["direct_risk"]) / 12.0, 1.0)
    amount_score = max(
        float(case.amount_score or 0.0),
        1.0 if case.total_amount >= 100_000_000 else 0.0,
    )
    amount_score = min(amount_score, 1.0)
    overlap_score = min(
        float(len([queue for queue in [case.primary_queue, *case.secondary_queues] if queue]))
        / 7.0,
        1.0,
    )
    repeat_score = min(float(case.repeat_months or 0) / 3.0, 1.0)

    components: list[tuple[str, float, float]] = [
        ("direct risk evidence", direct_score, 0.15),
        ("material amount", amount_score, 0.15),
        ("small review set", small_case_score, 0.10),
        ("rule corroboration", rule_score, 0.10),
    ]
    if queue == "control_approval":
        components.extend(
            [
                ("control rule strength", min(float(case.control_score or 0.0), 1.0), 0.30),
                (
                    "L1 control rules",
                    _rule_presence(rule_ids, {"L1-04", "L1-05", "L1-06", "L1-07", "L1-09"}),
                    0.20,
                ),
            ]
        )
    elif queue == "timing_close":
        components.extend(
            [
                ("timing rule strength", min(float(case.timing_score or 0.0), 1.0), 0.30),
                (
                    "close/cutoff rules",
                    _rule_presence(rule_ids, {"L3-04", "L3-07", "L3-09", "L3-11"}),
                    0.15,
                ),
                ("repeat timing pattern", repeat_score, 0.05),
            ]
        )
    elif queue == "amount_statistical":
        components.extend(
            [
                ("amount/stat score", min(float(case.amount_score or 0.0), 1.0), 0.30),
                (
                    "statistical rules",
                    _rule_presence(
                        rule_ids,
                        {"L3-01", "L4-01", "L4-03", "L4-04", "L4-05", "L4-06"},
                    ),
                    0.20,
                ),
            ]
        )
    elif queue == "account_logic":
        components.extend(
            [
                ("account logic score", min(float(case.logic_score or 0.0), 1.0), 0.30),
                (
                    "logic/account rules",
                    _rule_presence(rule_ids, {"L2-05", "L3-02", "L3-05", "L3-06"}),
                    0.20,
                ),
            ]
        )
    elif queue == "duplicate_outflow":
        components.extend(
            [
                (
                    "duplicate/outflow score",
                    min(float(case.duplicate_or_outflow_score or 0.0), 1.0),
                    0.30,
                ),
                (
                    "duplicate/outflow rules",
                    _rule_presence(rule_ids, {"L2-02", "L2-03", "L2-04"}),
                    0.20,
                ),
            ]
        )
    elif queue == "intercompany_cycle":
        components.extend(
            [
                ("intercompany score", min(float(case.intercompany_score or 0.0), 1.0), 0.30),
                ("IC/cycle rules", _rule_presence(rule_ids, {"L3-03", "L3-12"}), 0.15),
                ("repeat IC pattern", repeat_score, 0.05),
            ]
        )
    elif queue == "manipulation_candidate":
        components.extend(
            [
                ("queue overlap", overlap_score, 0.25),
                ("small composite case", small_case_score, 0.15),
                ("corroborating rules", rule_score, 0.10),
            ]
        )
    else:
        components.extend(
            [
                ("queue overlap", overlap_score, 0.20),
                ("repeat pattern", repeat_score, 0.10),
            ]
        )

    total_weight = sum(weight for _, _, weight in components) or 1.0
    score = sum(value * weight for _, value, weight in components) / total_weight
    reasons = [
        label
        for label, value, _ in sorted(components, key=lambda item: item[1] * item[2], reverse=True)
        if value > 0
    ][:5]
    return {
        "queue_id": queue,
        "score": round(min(max(score, 0.0), 1.0), 4),
        "reasons": reasons,
    }


def _rule_presence(rule_ids: set[str], target_rules: set[str]) -> float:
    return min(len(rule_ids & target_rules) / max(len(target_rules), 1), 1.0)


_SIGNAL_TYPE_LABELS = {
    "direct_risk": "직접 위험",
    "review_context": "리뷰/맥락",
    "integrity_blocker": "정합성/탐지제약",
    "macro_finding": "계정/모집단",
}

_INTEGRITY_RULES = {"L1-01", "L1-02", "L1-03", "L1-08"}
_MACRO_RULES = {"L4-02", "D01", "D02", "GR01", "GR03"}
_REVIEW_CONTEXT_RULES = {"L3-03", "L3-05", "L3-06", "L3-08", "L3-12", "L4-06"}
_L302_DIRECT_BUCKETS = {"manual_control_bypass"}
_L304_DIRECT_BUCKETS = {"closing_amount_p90", "closing_amount_p95"}


def _case_signal_counts(case: CaseGroupResult) -> dict[str, int]:
    counts = {
        "direct_risk": 0,
        "review_context": 0,
        "integrity_blocker": 0,
        "macro_finding": 0,
    }
    for hit in case.raw_rule_hits:
        counts[_signal_type(hit)] += 1
    return counts


def _signal_type(hit: Any) -> str:
    rule_id = str(hit.rule_id)
    label = str(hit.display_label or "").strip().lower()
    scoring_role = str(hit.scoring_role or "").strip().lower()
    evidence_type = str(hit.evidence_type or "").strip().lower()
    signal_status = str(hit.signal_status or "").strip().lower()

    if rule_id in _MACRO_RULES or scoring_role == "macro_only":
        return "macro_finding"
    if rule_id in _INTEGRITY_RULES or evidence_type == "data_integrity_failure":
        return "integrity_blocker"
    if signal_status == "review_candidate":
        return "review_context"
    if scoring_role in {"booster", "combo_only"}:
        return "review_context"
    if rule_id in _REVIEW_CONTEXT_RULES:
        return "review_context"
    if rule_id == "L3-02" and label not in _L302_DIRECT_BUCKETS:
        return "review_context"
    if rule_id == "L3-04" and label and label not in _L304_DIRECT_BUCKETS:
        return "review_context"
    return "direct_risk"


def _case_type(case: CaseGroupResult, signal_counts: dict[str, int]) -> str:
    if signal_counts["direct_risk"] > 0:
        return "직접 위험 케이스"
    if signal_counts["integrity_blocker"] > 0:
        return "정합성/탐지제약 케이스"
    if signal_counts["macro_finding"] > 0:
        return "계정/모집단 분석 케이스"
    if signal_counts["review_context"] > 0:
        return "리뷰/맥락 케이스"
    return _theme_label_from_id(case.primary_theme)


def _main_reason(case: CaseGroupResult) -> str:
    if case.review_focus:
        return ", ".join(case.review_focus[:3])
    if case.risk_narrative:
        return case.risk_narrative
    return case.representative_explanation


def _theme_label_from_id(theme_id: str) -> str:
    return theme_id.replace("_", " ")


def _theme_label(phase1: Phase1CaseResult, theme_id: str) -> str:
    for theme in phase1.theme_summaries:
        if theme.theme_id == theme_id:
            return theme.theme_label
    return theme_id
