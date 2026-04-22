"""Build case-centric Phase 1 results from raw detection outputs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import PROJECT_ROOT
from src.detection.base import DetectionResult
from src.models.phase1_case import (
    CaseDocumentRef,
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
    ThemeSummary,
)

SCHEMA_VERSION = "1.0.0"

_THEME_LABELS = {
    "control_failure": "승인·권한 통제 우회",
    "timing_anomaly": "결산·기말 조정 이상",
    "duplicate_or_outflow": "지급·중복·자금 유출 위험",
    "logic_mismatch": "계정 사용 논리 이상",
    "statistical_outlier": "수익·금액·통계 이상",
    "data_integrity_failure": "데이터 무결성 붕괴",
    "intercompany_structure": "관계사·연결 구조 이상",
}

_EXPLANATION_PRIORITY = (
    "control_failure",
    "duplicate_or_outflow",
    "logic_mismatch",
    "timing_anomaly",
    "statistical_outlier",
    "intercompany_structure",
    "data_integrity_failure",
)

_RULE_THEME_MAP = {
    "L1-01": ("data_integrity_failure", "data_integrity_failure"),
    "L1-02": ("data_integrity_failure", "data_integrity_failure"),
    "L1-08": ("data_integrity_failure", "data_integrity_failure"),
    "L1-03": ("logic_mismatch", "logic_mismatch"),
    "L2-04": ("logic_mismatch", "logic_mismatch"),
    "L3-09": ("logic_mismatch", "logic_mismatch"),
    "L4-04": ("logic_mismatch", "logic_mismatch"),
    "L1-04": ("control_failure", "control_failure"),
    "L1-05": ("control_failure", "control_failure"),
    "L1-06": ("control_failure", "control_failure"),
    "L1-07": ("control_failure", "control_failure"),
    "L3-02": ("control_failure", "control_failure"),
    "L2-01": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-02": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03a": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03b": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03c": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03d": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-06": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L3-04": ("timing_anomaly", "timing_anomaly"),
    "L3-05": ("timing_anomaly", "timing_anomaly"),
    "L3-06": ("timing_anomaly", "timing_anomaly"),
    "L3-07": ("timing_anomaly", "timing_anomaly"),
    "L3-08": ("timing_anomaly", "timing_anomaly"),
    "L4-05": ("timing_anomaly", "timing_anomaly"),
    "L4-01": ("statistical_outlier", "statistical_outlier"),
    "L4-02": ("statistical_outlier", "statistical_outlier"),
    "L4-03": ("statistical_outlier", "statistical_outlier"),
    "L4-06": ("statistical_outlier", "statistical_outlier"),
    "L3-03": ("intercompany_structure", "intercompany_structure"),
    "IL3-04": ("intercompany_structure", "intercompany_structure"),
    "IL3-05": ("intercompany_structure", "intercompany_structure"),
    "IL3-06": ("intercompany_structure", "intercompany_structure"),
}

_CONTROL_RULES = {
    "L1-04": "승인한도 초과",
    "L1-05": "자기승인",
    "L1-06": "직무분리 위반",
    "L1-07": "승인 생략",
    "L3-02": "수기 입력",
}

_OUTFLOW_RULES = {
    "L2-01": "승인한도 직하",
    "L2-02": "동일 거래처 반복 지급",
    "L2-03": "근접일자 중복 전표",
    "L2-03a": "근접일자 중복 전표",
    "L2-03b": "근접일자 중복 전표",
    "L2-03c": "근접일자 중복 전표",
    "L2-03d": "근접일자 중복 전표",
    "L2-06": "역분개 연계",
}

_LOGIC_RULES = {
    "L1-03": "무효 계정",
    "L2-04": "비용 자산화 의심",
    "L3-09": "가수금 장기체류",
    "L4-04": "비정상 계정조합",
}

_TIMING_RULES = {
    "L3-04": "기말 집중",
    "L3-05": "주말 전기",
    "L3-06": "심야 전기",
    "L3-07": "소급 전기",
    "L3-08": "설명 부실",
    "L4-05": "배치 시점 이상",
}

_STAT_RULES = {
    "L4-01": "매출 이상 변동",
    "L4-02": "Benford 위반",
    "L4-03": "고액 전표",
    "L4-06": "배치 전표 이상",
}

_INTEGRITY_RULES = {
    "L1-01": "차대변 불일치",
    "L1-02": "필수필드 누락",
    "L1-08": "회계기간 불일치",
}

_INTERCOMPANY_RULES = {
    "L3-03": "관계사 순환 구조",
    "IL3-04": "관계사 순환 구조",
    "IL3-05": "관계사 순환 구조",
    "IL3-06": "관계사 순환 구조",
}


@dataclass
class _RawHit:
    rule_id: str
    theme_id: str
    evidence_type: str
    severity: int
    row_index: int
    score: float
    document_id: str
    record_id: str | None
    detail: str | None


def build_phase1_case_run_id(
    *,
    company_id: str | None,
    batch_id: str | None,
    dataset_id: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    timestamp = (generated_at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    if company_id and batch_id:
        return f"phase1case_{company_id}_{batch_id}_{timestamp}"
    if company_id and dataset_id:
        return f"phase1case_{company_id}_{dataset_id}_{timestamp}"
    return f"phase1case_default_{timestamp}"


def phase1_case_artifact_path(company_id: str, run_id: str) -> Path:
    return PROJECT_ROOT / "artifacts" / "phase1_cases" / company_id / f"{run_id}.json"


def save_phase1_case_result(result: Phase1CaseResult) -> Path:
    path = phase1_case_artifact_path(result.company_id, result.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_phase1_case_result(path: str | Path) -> Phase1CaseResult:
    artifact_path = Path(path)
    return Phase1CaseResult.model_validate_json(artifact_path.read_text(encoding="utf-8"))


def build_phase1_case_result(
    df: pd.DataFrame,
    results: list[DetectionResult],
    *,
    company_id: str,
    batch_id: str | None,
    dataset_id: str | None,
    phase1_case_config: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> Phase1CaseResult:
    generated_at = generated_at or datetime.now(UTC)
    config = (phase1_case_config or {}).get("phase1_case", {})
    run_id = build_phase1_case_run_id(
        company_id=company_id,
        batch_id=batch_id,
        dataset_id=dataset_id,
        generated_at=generated_at,
    )
    raw_hits = _collect_raw_hits(df, results)
    cases = _build_cases(df, raw_hits, config)
    theme_summaries = _build_theme_summaries(cases, int(config.get("top_n_per_theme", 10)))
    return Phase1CaseResult(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        company_id=company_id,
        dataset_id=dataset_id,
        batch_id=batch_id,
        generated_at=generated_at,
        top_n_cases=int(config.get("top_n_cases", 50)),
        top_n_per_theme=int(config.get("top_n_per_theme", 10)),
        theme_summaries=theme_summaries,
        cases=cases,
        raw_rule_reference={
            "source": "detection_results",
            "track_names": [result.track_name for result in results],
        },
        metadata={
            "phase1_case_config_version": SCHEMA_VERSION,
            "score_cutoff": {
                "high": float(config.get("priority_band", {}).get("high", 0.75)),
                "medium": float(config.get("priority_band", {}).get("medium", 0.45)),
            },
            "grouping_window": {
                "near_period_days": int(config.get("near_period_days", 7)),
                "period_end_window_days": int(config.get("period_end_window_days", 5)),
            },
        },
    )


def annotate_detection_results_with_phase1_refs(
    results: list[DetectionResult],
    phase1_result: Phase1CaseResult,
    artifact_path: Path,
) -> None:
    reference = build_phase1_case_reference(phase1_result, artifact_path)
    for result in results:
        result.metadata["phase1_case_run_id"] = reference["phase1_case_run_id"]
        result.metadata["phase1_case_path"] = reference["phase1_case_path"]
        result.metadata["phase1_case_count"] = reference["phase1_case_count"]
        result.metadata["top_theme_ids"] = reference["top_theme_ids"]
        result.metadata["phase1_case_schema_version"] = reference["phase1_case_schema_version"]


def build_phase1_case_reference(
    phase1_result: Phase1CaseResult,
    artifact_path: str | Path,
) -> dict[str, Any]:
    return {
        "phase1_case_run_id": phase1_result.run_id,
        "phase1_case_path": str(artifact_path),
        "phase1_case_count": len(phase1_result.cases),
        "top_theme_ids": [summary.theme_id for summary in phase1_result.theme_summaries[:3]],
        "phase1_case_schema_version": phase1_result.schema_version,
    }


def _collect_raw_hits(df: pd.DataFrame, results: list[DetectionResult]) -> list[_RawHit]:
    hits: list[_RawHit] = []
    for result in results:
        details = result.details if result.details is not None else pd.DataFrame(index=df.index)
        for rule_flag in result.rule_flags:
            mapping = _RULE_THEME_MAP.get(rule_flag.rule_id)
            if mapping is None or rule_flag.rule_id not in details.columns:
                continue
            theme_id, evidence_type = mapping
            column = details[rule_flag.rule_id]
            for row_index, score in column[column > 0].items():
                row = df.loc[row_index]
                document_id = _string_value(row.get("document_id")) or f"row-{row_index}"
                hits.append(
                    _RawHit(
                        rule_id=rule_flag.rule_id,
                        theme_id=theme_id,
                        evidence_type=evidence_type,
                        severity=int(rule_flag.severity),
                        row_index=int(row_index),
                        score=float(score),
                        document_id=document_id,
                        record_id=_optional_string(row.get("record_id")),
                        detail=rule_flag.detail,
                    )
                )
    return hits


def _build_cases(
    df: pd.DataFrame,
    raw_hits: list[_RawHit],
    config: dict[str, Any],
) -> list[CaseGroupResult]:
    if not raw_hits:
        return []

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    hits_by_row: dict[int, list[_RawHit]] = defaultdict(list)
    for hit in raw_hits:
        hits_by_row[hit.row_index].append(hit)
        row = df.loc[hit.row_index]
        case_key_parts = _make_case_key_parts(hit.theme_id, row, config)
        case_key = " / ".join(str(value) for value in case_key_parts.values())
        group_key = (hit.theme_id, case_key)
        if group_key not in groups:
            groups[group_key] = {
                "case_key_parts": case_key_parts,
                "row_indices": set(),
            }
        groups[group_key]["row_indices"].add(hit.row_index)

    max_amount = max((_case_total_amount(df, group["row_indices"]) for group in groups.values()), default=0.0) or 1.0
    repeat_tiebreak = int(config.get("repeat_months_tiebreak", 3))
    cases: list[CaseGroupResult] = []

    for ordinal, ((theme_id, case_key), group) in enumerate(groups.items(), start=1):
        indices = sorted(group["row_indices"])
        rows = df.loc[indices]
        case_hits = _collect_case_hits(indices, hits_by_row)
        evidence_types = sorted({hit.evidence_type for hit in case_hits})
        evidence_scores = _theme_scores(case_hits, config)
        total_amount = _case_total_amount(df, indices)
        amount_score = min(total_amount / max_amount, 1.0)
        control_score = min(evidence_scores.get("control_failure", 0.0), 1.0)
        logic_score = min(
            max(
                evidence_scores.get("logic_mismatch", 0.0),
                evidence_scores.get("intercompany_structure", 0.0),
                evidence_scores.get("data_integrity_failure", 0.0),
            ),
            1.0,
        )
        behavior_score = min(len(indices) / 10.0, 1.0)
        repeat_months = _repeat_months(rows)
        repeat_score = min(max(repeat_months - 1, 0) / 2.0, 1.0)
        priority_score = _priority_score(
            amount_score=amount_score,
            control_score=control_score,
            logic_score=logic_score,
            behavior_score=behavior_score,
            config=config,
        )
        priority_band = _priority_band(priority_score, config, repeat_score)
        secondary_tags = _secondary_tags(theme_id, evidence_scores, config)

        cases.append(
            CaseGroupResult(
                case_id=f"case_{theme_id}_{ordinal:05d}",
                primary_theme=theme_id,
                secondary_tags=secondary_tags,
                evidence_types=evidence_types,
                case_key=case_key,
                case_key_parts=group["case_key_parts"],
                priority_score=priority_score,
                priority_band=priority_band,
                amount_score=amount_score,
                control_score=control_score,
                logic_score=logic_score,
                behavior_score=behavior_score,
                repeat_score=repeat_score,
                rule_count=len({hit.rule_id for hit in case_hits}),
                evidence_count=len(case_hits),
                document_count=len({hit.document_id for hit in case_hits}),
                row_count=len(indices),
                total_amount=total_amount,
                first_posting_date=_date_string(rows["posting_date"].min()) if "posting_date" in rows.columns else None,
                last_posting_date=_date_string(rows["posting_date"].max()) if "posting_date" in rows.columns else None,
                repeat_months=repeat_months,
                representative_explanation=_representative_explanation(
                    theme_id=theme_id,
                    case_hits=case_hits,
                    total_amount=total_amount,
                ),
                evidence_tags=sorted({*evidence_types, *secondary_tags}),
                documents=_build_document_refs(rows, case_hits, config),
                raw_rule_hits=[
                    RawRuleHitRef(
                        rule_id=hit.rule_id,
                        severity=hit.severity,
                        document_id=hit.document_id,
                        row_index=hit.row_index,
                        record_id=hit.record_id,
                        score=hit.score,
                        detail=hit.detail,
                        evidence_type=hit.evidence_type,
                    )
                    for hit in case_hits
                ],
                has_control_failure="control_failure" in evidence_types,
                has_high_materiality=amount_score >= 0.75,
                has_repeat_pattern=repeat_months >= repeat_tiebreak,
            )
        )

    cases.sort(
        key=lambda item: (
            item.priority_score,
            item.repeat_months >= repeat_tiebreak,
            item.total_amount,
            item.rule_count,
        ),
        reverse=True,
    )
    for index, case in enumerate(cases, start=1):
        case.exposure_rank = index
        case.is_top_case = index <= int(config.get("top_n_cases", 50))
    _apply_theme_ranks(cases)
    return cases


def _build_theme_summaries(cases: list[CaseGroupResult], top_n_per_theme: int) -> list[ThemeSummary]:
    grouped: dict[str, list[CaseGroupResult]] = defaultdict(list)
    for case in cases:
        grouped[case.primary_theme].append(case)
    summaries: list[ThemeSummary] = []
    for theme_id, theme_cases in grouped.items():
        summaries.append(
            ThemeSummary(
                theme_id=theme_id,
                theme_label=_THEME_LABELS.get(theme_id, theme_id),
                case_count=len(theme_cases),
                high_count=sum(1 for case in theme_cases if case.priority_band == "high"),
                medium_count=sum(1 for case in theme_cases if case.priority_band == "medium"),
                low_count=sum(1 for case in theme_cases if case.priority_band == "low"),
                total_amount=sum(case.total_amount for case in theme_cases),
                top_case_ids=[case.case_id for case in theme_cases[:top_n_per_theme]],
                secondary_tag_case_count=sum(1 for case in theme_cases if case.secondary_tags),
            )
        )
    summaries.sort(key=lambda item: (item.high_count, item.total_amount, item.case_count), reverse=True)
    return summaries


def _collect_case_hits(indices: list[int], hits_by_row: dict[int, list[_RawHit]]) -> list[_RawHit]:
    collected: list[_RawHit] = []
    seen: set[tuple[str, int]] = set()
    for row_index in indices:
        for hit in hits_by_row.get(row_index, []):
            key = (hit.rule_id, hit.row_index)
            if key in seen:
                continue
            seen.add(key)
            collected.append(hit)
    return collected


def _secondary_tags(theme_id: str, evidence_scores: dict[str, float], config: dict[str, Any]) -> list[str]:
    threshold = float(config.get("secondary_tag_min_score", 0.40))
    return sorted(
        evidence
        for evidence, score in evidence_scores.items()
        if evidence != theme_id and score >= threshold
    )


def _make_case_key_parts(theme_id: str, row: pd.Series, config: dict[str, Any]) -> dict[str, Any]:
    posting_month = _posting_month(row)
    if theme_id == "control_failure":
        return {
            "created_by": _string_value(row.get("created_by")) or "UNKNOWN_USER",
            "business_process": _string_value(row.get("business_process")) or "UNKNOWN_PROCESS",
            "period_month": posting_month,
        }
    if theme_id == "timing_anomaly":
        return {
            "created_by": _string_value(row.get("created_by")) or "UNKNOWN_USER",
            "account_family": _account_family(row, config),
            "period_window": _period_end_window(row, int(config.get("period_end_window_days", 5))),
        }
    if theme_id == "duplicate_or_outflow":
        return {
            "counterparty": _counterparty(row, config),
            "amount_band": _amount_band(row),
            "near_period": _near_period_bucket(row, int(config.get("near_period_days", 7))),
        }
    if theme_id == "intercompany_structure":
        return {
            "company_pair": _company_pair(row, config),
            "counterparty": _counterparty(row, config),
            "period_month": posting_month,
        }
    if theme_id == "statistical_outlier":
        return {
            "business_process": _string_value(row.get("business_process")) or "UNKNOWN_PROCESS",
            "account_family": _account_family(row, config),
            "period_month": posting_month,
        }
    if theme_id == "logic_mismatch":
        return {
            "account_family": _account_family(row, config),
            "document_type": _string_value(row.get("document_type")) or "UNKNOWN_DOCUMENT_TYPE",
            "period_month": posting_month,
        }
    return {
        "company": _string_value(row.get("company_code")) or "UNKNOWN_COMPANY",
        "document_type": _string_value(row.get("document_type")) or "UNKNOWN_DOCUMENT_TYPE",
        "load_batch": _load_batch_value(row, config),
    }


def _build_document_refs(rows: pd.DataFrame, hits: list[_RawHit], config: dict[str, Any]) -> list[CaseDocumentRef]:
    by_doc: dict[str, list[_RawHit]] = defaultdict(list)
    for hit in hits:
        by_doc[hit.document_id].append(hit)
    refs: list[CaseDocumentRef] = []
    for document_id, doc_hits in by_doc.items():
        row = rows.loc[[hit.row_index for hit in doc_hits]].iloc[0]
        refs.append(
            CaseDocumentRef(
                document_id=document_id,
                posting_date=_date_string(row.get("posting_date")),
                created_by=_optional_string(row.get("created_by")),
                business_process=_optional_string(row.get("business_process")),
                gl_account=_optional_string(row.get("gl_account")),
                counterparty=_counterparty(row, config),
                amount=_line_amount(row),
                matched_rules=sorted({hit.rule_id for hit in doc_hits}),
                evidence_tags=sorted({hit.evidence_type for hit in doc_hits}),
            )
        )
    refs.sort(key=lambda item: (item.posting_date or "", item.document_id))
    return refs


def _theme_scores(hits: list[_RawHit], config: dict[str, Any]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for hit in hits:
        counts[hit.evidence_type] += 1
        totals[hit.evidence_type] += hit.severity / 5.0

    cap = float(config.get("evidence_type_cap", 1.0))
    scale = str(config.get("rule_repeat_scale", "sqrt")).lower()
    scores: dict[str, float] = {}
    for evidence_type, total in totals.items():
        count = counts[evidence_type]
        if scale == "log":
            scaled = total / max(1.0, count.bit_length())
        elif scale == "sqrt":
            scaled = total / (count**0.5)
        else:
            scaled = total
        scores[evidence_type] = min(scaled, cap)
    return scores


def _priority_score(
    *,
    amount_score: float,
    control_score: float,
    logic_score: float,
    behavior_score: float,
    config: dict[str, Any],
) -> float:
    weights = config.get("priority_weights", {})
    return (
        float(weights.get("control", 0.35)) * control_score
        + float(weights.get("amount", 0.30)) * amount_score
        + float(weights.get("logic", 0.20)) * logic_score
        + float(weights.get("behavior", 0.15)) * behavior_score
    )


def _priority_band(priority_score: float, config: dict[str, Any], repeat_score: float) -> str:
    bands = config.get("priority_band", {})
    high = float(bands.get("high", 0.75))
    medium = float(bands.get("medium", 0.45))
    promote_cutoff = float(config.get("repeat_score_promote", 0.70))
    if priority_score >= high:
        return "high"
    if priority_score >= medium:
        if repeat_score >= promote_cutoff:
            return "high"
        return "medium"
    if repeat_score >= promote_cutoff:
        return "medium"
    return "low"


def _repeat_months(rows: pd.DataFrame) -> int:
    if "posting_date" not in rows.columns:
        return 0
    series = pd.to_datetime(rows["posting_date"], errors="coerce").dt.strftime("%Y-%m").dropna()
    return int(series.nunique())


def _case_total_amount(df: pd.DataFrame, indices: set[int] | list[int]) -> float:
    rows = df.loc[sorted(indices)]
    return float(rows.apply(_line_amount, axis=1).sum())


def _representative_explanation(
    *,
    theme_id: str,
    case_hits: list[_RawHit],
    total_amount: float,
) -> str:
    rule_ids = sorted({hit.rule_id for hit in case_hits})
    evidence_types = sorted({hit.evidence_type for hit in case_hits})
    primary_evidence = _pick_primary_explanation_evidence(evidence_types)

    if primary_evidence == "control_failure":
        return _control_explanation(rule_ids, total_amount)
    if primary_evidence == "duplicate_or_outflow":
        return _outflow_explanation(rule_ids, total_amount)
    if primary_evidence == "logic_mismatch":
        return _logic_explanation(rule_ids, total_amount)
    if primary_evidence == "timing_anomaly":
        return _timing_explanation(rule_ids, total_amount)
    if primary_evidence == "statistical_outlier":
        return _statistical_explanation(rule_ids, total_amount)
    if primary_evidence == "intercompany_structure":
        return _intercompany_explanation(rule_ids, total_amount)
    if primary_evidence == "data_integrity_failure":
        return _integrity_explanation(rule_ids, total_amount)

    label = _THEME_LABELS.get(theme_id, theme_id)
    if total_amount > 0:
        return f"{label} 징후가 관찰되었고 총금액이 {total_amount:,.0f}입니다."
    return f"{label} 징후가 관찰되었습니다."


def _pick_primary_explanation_evidence(evidence_types: list[str]) -> str | None:
    evidence_set = set(evidence_types)
    for evidence in _EXPLANATION_PRIORITY:
        if evidence in evidence_set:
            return evidence
    return None


def _control_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _CONTROL_RULES)
    if not labels:
        labels = ["승인 통제 위반"]
    lead = " + ".join(labels[:3])
    if total_amount > 0:
        return f"{lead}이 함께 발생했고 관련 전표 총금액은 {total_amount:,.0f}입니다. 승인·권한 통제가 실제로 우회되었는지 우선 검토해야 합니다."
    return f"{lead}이 함께 발생했습니다. 승인·권한 통제가 실제로 우회되었는지 우선 검토해야 합니다."


def _outflow_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _OUTFLOW_RULES)
    lead = " + ".join(labels[:3]) if labels else "지급·중복 징후"
    if total_amount > 0:
        return f"{lead}이 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. 실제 자금 유출이나 중복 집행으로 이어졌는지 확인이 필요합니다."
    return f"{lead}이 관찰되었습니다. 실제 자금 유출이나 중복 집행으로 이어졌는지 확인이 필요합니다."


def _logic_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _LOGIC_RULES)
    lead = " + ".join(labels[:3]) if labels else "회계 처리 논리 이상"
    if total_amount > 0:
        return f"{lead}이 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. 거래의 경제적 실질과 계정 사용이 맞는지 재검토해야 합니다."
    return f"{lead}이 관찰되었습니다. 거래의 경제적 실질과 계정 사용이 맞는지 재검토해야 합니다."


def _timing_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _TIMING_RULES)
    lead = " + ".join(labels[:3]) if labels else "기말·시점 이상"
    if total_amount > 0:
        return f"{lead}이 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. 결산 시점에 맞춘 조정이나 사후 보정 흔적인지 확인이 필요합니다."
    return f"{lead}이 관찰되었습니다. 결산 시점에 맞춘 조정이나 사후 보정 흔적인지 확인이 필요합니다."


def _statistical_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _STAT_RULES)
    lead = " + ".join(labels[:3]) if labels else "통계적 이상치"
    if total_amount > 0:
        return f"{lead}가 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. 일반 분포에서 벗어난 예외 거래인지 확인이 필요합니다."
    return f"{lead}가 관찰되었습니다. 일반 분포에서 벗어난 예외 거래인지 확인이 필요합니다."


def _intercompany_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _INTERCOMPANY_RULES)
    lead = " + ".join(labels[:3]) if labels else "관계사 구조 이상"
    if total_amount > 0:
        return f"{lead}이 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. 관계사 간 순환 흐름이나 상계 은폐 가능성을 확인해야 합니다."
    return f"{lead}이 관찰되었습니다. 관계사 간 순환 흐름이나 상계 은폐 가능성을 확인해야 합니다."


def _integrity_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _INTEGRITY_RULES)
    lead = " + ".join(labels[:3]) if labels else "데이터 무결성 붕괴"
    if total_amount > 0:
        return f"{lead}이 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. 장부 자체가 성립하는지 먼저 정합성을 점검해야 합니다."
    return f"{lead}이 관찰되었습니다. 장부 자체가 성립하는지 먼저 정합성을 점검해야 합니다."


def _ordered_rule_labels(rule_ids: list[str], mapping: dict[str, str]) -> list[str]:
    labels: list[str] = []
    for rule_id in rule_ids:
        label = mapping.get(rule_id)
        if label and label not in labels:
            labels.append(label)
    return labels


def _apply_theme_ranks(cases: list[CaseGroupResult]) -> None:
    by_theme: dict[str, list[CaseGroupResult]] = defaultdict(list)
    for case in cases:
        by_theme[case.primary_theme].append(case)
    for theme_cases in by_theme.values():
        for rank, case in enumerate(theme_cases, start=1):
            case.theme_rank = rank


def _posting_month(row: pd.Series) -> str:
    value = _timestamp(row.get("posting_date"))
    return value.strftime("%Y-%m") if value is not None else "UNKNOWN_MONTH"


def _period_end_window(row: pd.Series, days: int) -> str:
    timestamp = _timestamp(row.get("posting_date"))
    if timestamp is None:
        return "UNKNOWN_PERIOD_WINDOW"
    if bool(row.get("is_period_end", False)):
        return f"{timestamp.strftime('%Y-%m')}-period_end"
    month_end = timestamp + pd.offsets.MonthEnd(0)
    if abs((month_end - timestamp).days) <= days:
        return f"{timestamp.strftime('%Y-%m')}-month_end_window"
    return timestamp.strftime("%Y-%m")


def _near_period_bucket(row: pd.Series, days: int) -> str:
    timestamp = _timestamp(row.get("posting_date"))
    if timestamp is None:
        return "UNKNOWN_NEAR_PERIOD"
    ordinal = timestamp.toordinal()
    bucket_start = ordinal - (ordinal % max(days, 1))
    return datetime.fromordinal(bucket_start).strftime("%Y-%m-%d")


def _counterparty(row: pd.Series, config: dict[str, Any]) -> str:
    for field in config.get("counterparty_columns", ("auxiliary_account_number", "vendor_name", "customer_name")):
        value = _string_value(row.get(field))
        if value:
            return value
    return str(config.get("counterparty_fallback", "UNKNOWN_COUNTERPARTY"))


def _account_family(row: pd.Series, config: dict[str, Any]) -> str:
    for key in config.get(
        "account_family_fallback_order",
        ("account_family", "first_digit", "gl_account_prefix_2", "gl_account_prefix_3"),
    ):
        value = _account_family_value(row, key)
        if value:
            return value
    return str(config.get("account_family_fallback", "UNKNOWN_ACCOUNT_FAMILY"))


def _account_family_value(row: pd.Series, key: str) -> str:
    if key == "gl_account_prefix_2":
        gl_account = _string_value(row.get("gl_account"))
        return gl_account[:2] if gl_account else ""
    if key == "gl_account_prefix_3":
        gl_account = _string_value(row.get("gl_account"))
        return gl_account[:3] if gl_account else ""
    return _string_value(row.get(key))


def _company_pair(row: pd.Series, config: dict[str, Any]) -> str:
    fields = list(config.get("intercompany_pair_columns", ("company_code", "trading_partner")))
    values = [_string_value(row.get(field)) or f"UNKNOWN_{field.upper()}" for field in fields[:2]]
    if len(values) == 1:
        values.append("UNKNOWN_TRADING_PARTNER")
    return "+".join(values[:2])


def _load_batch_value(row: pd.Series, config: dict[str, Any]) -> str:
    for field in config.get("load_batch_columns", ("upload_batch_id",)):
        value = _string_value(row.get(field))
        if value:
            return value
    return "UNKNOWN_BATCH"


def _amount_band(row: pd.Series) -> str:
    amount = _line_amount(row)
    if amount >= 1_000_000_000:
        return "1B+"
    if amount >= 100_000_000:
        return "100M-1B"
    if amount >= 10_000_000:
        return "10M-100M"
    return "<10M"


def _line_amount(row: pd.Series) -> float:
    debit = float(pd.to_numeric(row.get("debit_amount"), errors="coerce") or 0.0)
    credit = float(pd.to_numeric(row.get("credit_amount"), errors="coerce") or 0.0)
    return max(debit, credit)


def _timestamp(value: Any) -> pd.Timestamp | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp


def _date_string(value: Any) -> str | None:
    timestamp = _timestamp(value)
    return timestamp.strftime("%Y-%m-%d") if timestamp is not None else None


def _optional_string(value: Any) -> str | None:
    text = _string_value(value)
    return text or None


def _string_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
