"""Build case-centric Phase 1 results from raw detection outputs."""

# ruff: noqa: E501

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import PROJECT_ROOT
from src.detection.base import DetectionResult
from src.detection.constants import BATCH_CORROBORATION_RULES, TOPSIDE_BONUS_RULES
from src.models.phase1_case import (
    CaseDocumentRef,
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
    ThemeSummary,
)

SCHEMA_VERSION = "1.0.0"

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
    "L3-01": ("logic_mismatch", "logic_mismatch"),
    "L3-09": ("logic_mismatch", "logic_mismatch"),
    "L3-10": ("logic_mismatch", "logic_mismatch"),
    "L4-04": ("logic_mismatch", "logic_mismatch"),
    "L1-04": ("control_failure", "control_failure"),
    "L1-05": ("control_failure", "control_failure"),
    "L1-06": ("control_failure", "control_failure"),
    "L1-07": ("control_failure", "control_failure"),
    "L1-09": ("control_failure", "control_failure"),
    "L3-02": ("control_failure", "control_failure"),
    "L2-01": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-02": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03a": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03b": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03c": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-03d": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L2-05": ("duplicate_or_outflow", "duplicate_or_outflow"),
    "L3-04": ("timing_anomaly", "timing_anomaly"),
    "L3-05": ("timing_anomaly", "timing_anomaly"),
    "L3-06": ("timing_anomaly", "timing_anomaly"),
    "L3-07": ("timing_anomaly", "timing_anomaly"),
    "L3-08": ("timing_anomaly", "timing_anomaly"),
    "L3-11": ("timing_anomaly", "timing_anomaly"),
    "L4-05": ("timing_anomaly", "timing_anomaly"),
    "L4-01": ("statistical_outlier", "statistical_outlier"),
    "L4-02": ("statistical_outlier", "statistical_outlier"),
    "L4-03": ("statistical_outlier", "statistical_outlier"),
    "L4-06": ("statistical_outlier", "statistical_outlier"),
    "L3-03": ("intercompany_structure", "intercompany_structure"),
    "IC01": ("intercompany_structure", "intercompany_structure"),
    "IC02": ("intercompany_structure", "intercompany_structure"),
    "IC03": ("intercompany_structure", "intercompany_structure"),
}

_STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1}

_MACRO_FINDING_RULES = {"L4-02", "D01", "D02"}

_THEME_EXPLANATION_PRIORITY = {
    "control_failure": (
        "control_failure",
        "statistical_outlier",
        "timing_anomaly",
        "logic_mismatch",
        "duplicate_or_outflow",
        "intercompany_structure",
        "data_integrity_failure",
    ),
    "timing_anomaly": (
        "timing_anomaly",
        "control_failure",
        "logic_mismatch",
        "statistical_outlier",
        "duplicate_or_outflow",
        "intercompany_structure",
        "data_integrity_failure",
    ),
    "duplicate_or_outflow": (
        "duplicate_or_outflow",
        "control_failure",
        "statistical_outlier",
        "timing_anomaly",
        "logic_mismatch",
        "intercompany_structure",
        "data_integrity_failure",
    ),
    "statistical_outlier": (
        "statistical_outlier",
        "timing_anomaly",
        "control_failure",
        "logic_mismatch",
        "duplicate_or_outflow",
        "intercompany_structure",
        "data_integrity_failure",
    ),
    "logic_mismatch": (
        "logic_mismatch",
        "statistical_outlier",
        "timing_anomaly",
        "control_failure",
        "duplicate_or_outflow",
        "intercompany_structure",
        "data_integrity_failure",
    ),
    "intercompany_structure": (
        "intercompany_structure",
        "statistical_outlier",
        "timing_anomaly",
        "duplicate_or_outflow",
        "control_failure",
        "logic_mismatch",
        "data_integrity_failure",
    ),
}

_RULE_EXPRESSION_METADATA: dict[str, dict[str, Any]] = {
    "L1-01": {
        "evidence_strength": "strong",
        "focus": "unbalanced_entry",
        "action": ["차변·대변 합계 재계산", "원천 전표 적재 오류 여부 확인"],
    },
    "L1-02": {
        "evidence_strength": "medium",
        "focus": "missing_required_field",
        "action": ["필수 필드 누락 원인 확인", "원천 ERP 추출 범위와 매핑 확인"],
    },
    "L1-03": {
        "evidence_strength": "medium",
        "focus": "invalid_account",
        "action": ["계정 마스터 유효성 확인", "전표 입력 시점의 계정 사용 가능 여부 확인"],
    },
    "L1-04": {
        "evidence_strength": "strong",
        "focus": "approval_limit_exceeded",
        "action": ["승인권한 한도 확인", "예외 승인 문서 확인"],
    },
    "L1-05": {
        "evidence_strength": "strong",
        "focus": "approval_control_bypass",
        "action": ["작성자와 승인자 동일 여부 확인", "승인권한 정책 확인"],
    },
    "L1-06": {
        "evidence_strength": "strong",
        "focus": "segregation_of_duties_conflict",
        "action": ["입력자와 승인자의 역할 충돌 여부 확인", "직무분리 예외 승인 여부 확인"],
    },
    "L1-07": {
        "evidence_strength": "strong",
        "focus": "skipped_approval",
        "action": ["승인 누락 사유 확인", "사후 승인 또는 대체 통제 존재 여부 확인"],
    },
    "L1-08": {
        "evidence_strength": "medium",
        "focus": "period_mismatch",
        "action": ["전기일과 회계기간 정합성 확인", "기간 귀속 조정 근거 확인"],
    },
    "L1-09": {
        "evidence_strength": "medium",
        "focus": "approval_traceability_gap",
        "action": ["승인일 로그 존재 여부 확인", "승인자와 승인 시점의 추적 가능성 확인"],
    },
    "L2-01": {
        "evidence_strength": "medium",
        "focus": "just_below_approval_threshold",
        "action": ["승인한도 직하 반복 여부 확인", "분할 입력 또는 승인 정책 적용 여부 확인"],
    },
    "L2-02": {
        "evidence_strength": "strong",
        "focus": "duplicate_payment",
        "action": ["동일 거래처 지급 내역 대조", "세금계산서와 지급 승인 내역 확인"],
    },
    "L2-03": {
        "evidence_strength": "medium",
        "focus": "duplicate_entry",
        "action": ["중복 전표 원문 비교", "취소·재입력·정상 반복 여부 확인"],
    },
    "L2-03a": {
        "evidence_strength": "strong",
        "focus": "duplicate_entry",
        "action": ["중복 전표 원문 비교", "취소·재입력·정상 반복 여부 확인"],
    },
    "L2-03b": {
        "evidence_strength": "medium",
        "focus": "duplicate_entry",
        "action": ["중복 전표 원문 비교", "취소·재입력·정상 반복 여부 확인"],
    },
    "L2-03c": {
        "evidence_strength": "medium",
        "focus": "split_or_duplicate_entry",
        "action": ["분할 입력 여부 확인", "동일 거래처·금액대 전표 묶음 확인"],
    },
    "L2-03d": {
        "evidence_strength": "medium",
        "focus": "duplicate_entry",
        "action": ["중복 전표 원문 비교", "취소·재입력·정상 반복 여부 확인"],
    },
    "L2-04": {
        "evidence_strength": "medium",
        "focus": "expense_capitalization",
        "action": ["자산화 판단 근거 확인", "비용/자산 계정 처리 기준 확인"],
    },
    "L2-05": {
        "evidence_strength": "medium",
        "focus": "reversal_or_offset_pattern",
        "action": ["후속 역분개·상계 전표 연결 확인", "원거래와 정리 전표의 사업 목적 확인"],
    },
    "L3-01": {
        "evidence_strength": "medium",
        "focus": "account_process_mismatch",
        "action": ["업무 프로세스와 계정 조합 정합성 확인", "예외 계정 사용 승인 여부 확인"],
    },
    "L3-02": {
        "evidence_strength": "medium",
        "focus": "manual_entry",
        "action": ["수기 입력 사유 확인", "자동 처리 예외 또는 보정 전표 여부 확인"],
    },
    "L3-03": {
        "evidence_strength": "weak",
        "focus": "related_party_transaction",
        "action": ["거래상대와 관계사 여부 확인", "계약 근거와 사업 목적 확인"],
    },
    "L3-04": {
        "evidence_strength": "medium",
        "focus": "period_end_manual_adjustment",
        "action": ["결산조정 승인 문서 확인", "마감 전후 전표 집중 사유 확인"],
    },
    "L3-05": {
        "evidence_strength": "weak",
        "focus": "non_workday_posting",
        "action": ["주말·공휴일 입력 사유 확인", "비정상 근무 승인 또는 배치 처리 여부 확인"],
    },
    "L3-06": {
        "evidence_strength": "weak",
        "focus": "after_hours_posting",
        "action": ["심야 입력 사유 확인", "입력자 근무 기록 또는 시스템 배치 여부 확인"],
    },
    "L3-07": {
        "evidence_strength": "medium",
        "focus": "posting_document_date_gap",
        "action": ["전기일과 문서일 차이 사유 확인", "기간 귀속 근거 확인"],
    },
    "L3-08": {
        "evidence_strength": "weak",
        "focus": "missing_or_corrupted_description",
        "action": ["전표 적요와 증빙의 설명 충분성 확인"],
    },
    "L3-09": {
        "evidence_strength": "medium",
        "focus": "suspense_account_linger",
        "action": ["가계정 정리 계획 확인", "장기 미정리 사유와 후속 정리 전표 확인"],
    },
    "L3-10": {
        "evidence_strength": "weak",
        "focus": "sensitive_account_touch",
        "action": ["민감 계정 사용 사유 확인", "승인 문서와 증빙 대사"],
    },
    "L3-11": {
        "evidence_strength": "medium",
        "focus": "revenue_cutoff_mismatch",
        "action": ["매출 인식일과 증빙일 대조", "납품·검수·청구 조건 확인"],
    },
    "L4-01": {
        "evidence_strength": "medium",
        "focus": "revenue_anomaly",
        "action": ["매출 변동 원인 확인", "기간 말 매출 거래와 반품·취소 조건 확인"],
    },
    "L4-02": {
        "evidence_strength": "weak",
        "focus": "benford_population_anomaly",
        "action": ["계정/월 모집단의 숫자 분포 이상 원인 확인", "해당 모집단의 표본 전표 추가 검토"],
    },
    "L4-03": {
        "evidence_strength": "medium",
        "focus": "high_amount",
        "action": ["금액 산정 근거 확인", "수행중요성 대비 영향 확인"],
    },
    "L4-04": {
        "evidence_strength": "medium",
        "focus": "rare_account_pair",
        "action": ["차대 계정 조합의 경제적 실질 확인", "희소 계정 조합 승인 근거 확인"],
    },
    "L4-05": {
        "evidence_strength": "weak",
        "focus": "abnormal_time_concentration",
        "action": ["특정 사용자·시간대 전표 집중 사유 확인", "근무시간 외 처리 승인 여부 확인"],
    },
    "L4-06": {
        "evidence_strength": "weak",
        "focus": "batch_anomaly",
        "action": ["배치 처리 로그 확인", "대량 자동 전표의 결산·금액 이상 결합 여부 확인"],
    },
    "IC01": {
        "evidence_strength": "medium",
        "focus": "intercompany_reconciliation_gap",
        "action": ["관계사 대사 차이 확인", "상대 회사 전표와 reference 대조"],
    },
    "IC02": {
        "evidence_strength": "medium",
        "focus": "intercompany_amount_mismatch",
        "action": ["관계사 양방향 금액 차이 확인", "세금·환율·상계 조건 확인"],
    },
    "IC03": {
        "evidence_strength": "medium",
        "focus": "intercompany_timing_mismatch",
        "action": ["관계사 전표 시차 확인", "기간 귀속과 사후 정리 여부 확인"],
    },
}


_THEME_LABELS = {
    "control_failure": "승인·권한 통제 검토",
    "timing_anomaly": "결산·시점 검토",
    "duplicate_or_outflow": "지급·중복 거래 검토",
    "logic_mismatch": "계정 사용 논리 검토",
    "statistical_outlier": "수익·금액·통계 예외",
    "data_integrity_failure": "데이터 정합성 오류",
    "intercompany_structure": "관계사·연결 거래 검토",
}

_CONTROL_RULES = {
    "L1-04": "승인한도 초과",
    "L1-05": "자기승인",
    "L1-06": "직무분리 위반",
    "L1-07": "승인 생략",
    "L1-09": "승인일 누락",
    "L3-02": "수기 입력",
}

_OUTFLOW_RULES = {
    "L2-01": "승인한도 직하",
    "L2-02": "동일 거래처 반복 지급",
    "L2-03": "근접일자 중복 전표",
    "L2-03a": "정확 중복 전표",
    "L2-03b": "유사 중복 전표",
    "L2-03c": "분할 중복 후보",
    "L2-03d": "연속 중복 전표",
    "L2-05": "역분개 연계",
}

_LOGIC_RULES = {
    "L3-10": "고위험 계정 사용",
    "L1-03": "무효 계정",
    "L2-04": "비용 자산화 의심",
    "L3-01": "계정 분류 불일치",
    "L3-09": "가수금 장기체류",
    "L4-04": "희소 차대 계정쌍",
}

_TIMING_RULES = {
    "L3-04": "기말 집중",
    "L3-05": "주말 전기",
    "L3-06": "심야 전기",
    "L3-07": "전기일-문서일 장기 괴리",
    "L3-08": "적요 결손/파손",
    "L3-11": "매출 컷오프 불일치",
    "L4-05": "비정상 시간대 집중",
}

_STAT_RULES = {
    "L4-01": "매출 이상 변동",
    "L4-02": "Benford 위반",
    "L4-03": "이상 고액",
    "L4-06": "배치 전표 이상",
}

_INTEGRITY_RULES = {
    "L1-01": "차대변 불일치",
    "L1-02": "필수필드 누락",
    "L1-08": "회계기간 불일치",
}

_INTERCOMPANY_RULES = {
    "L3-03": "관계사 거래 검토 신호",
    "IC01": "관계사 거래 대사 이상",
    "IC02": "관계사 거래 금액 불일치",
    "IC03": "관계사 거래 시차 이상",
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
        row_annotations = (result.metadata or {}).get("row_annotations", {})
        for rule_flag in result.rule_flags:
            if rule_flag.rule_id in _MACRO_FINDING_RULES:
                continue
            mapping = _RULE_THEME_MAP.get(rule_flag.rule_id)
            if mapping is None or rule_flag.rule_id not in details.columns:
                continue
            theme_id, evidence_type = mapping
            column = details[rule_flag.rule_id]
            rule_annotations = row_annotations.get(rule_flag.rule_id, {})
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
                        detail=_rule_hit_detail(
                            rule_flag.rule_id,
                            rule_flag.detail,
                            rule_annotations.get(int(row_index)),
                        ),
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

    max_amount = (
        max(
            (_case_total_amount(df, group["row_indices"]) for group in groups.values()),
            default=0.0,
        )
        or 1.0
    )
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
        secondary_tags = _secondary_tags(theme_id, evidence_scores, config)
        priority_score = _priority_score(
            amount_score=amount_score,
            control_score=control_score,
            logic_score=logic_score,
            behavior_score=behavior_score,
            config=config,
        )
        base_priority_score = priority_score
        priority_score, behavior_score, repeat_score = _apply_timing_priority_adjustments(
            df=df,
            theme_id=theme_id,
            rows=rows,
            case_hits=case_hits,
            secondary_tags=secondary_tags,
            amount_score=amount_score,
            behavior_score=behavior_score,
            repeat_score=repeat_score,
            priority_score=priority_score,
            config=config,
        )
        priority_score, behavior_score, adjustment_reasons, bonuses = _apply_priority_adjustments(
            rows=rows,
            case_hits=case_hits,
            evidence_types=evidence_types,
            priority_score=priority_score,
            behavior_score=behavior_score,
            config=config,
        )
        priority_band = _priority_band(priority_score, config, repeat_score)
        l304_repeat_pattern = _is_l304_repeat_pattern_case(
            df,
            rows,
            case_hits,
            config.get("timing_priority", {}),
        )
        auditor_insight = _auditor_insight(
            theme_id=theme_id,
            case_hits=case_hits,
            total_amount=total_amount,
        )

        cases.append(
            CaseGroupResult(
                case_id=f"case_{theme_id}_{ordinal:05d}",
                primary_theme=theme_id,
                secondary_tags=secondary_tags,
                evidence_types=evidence_types,
                case_key=case_key,
                case_key_parts=group["case_key_parts"],
                priority_score=priority_score,
                base_priority_score=base_priority_score,
                topside_bonus=bonuses["topside_bonus"],
                batch_combo_bonus=bonuses["batch_combo_bonus"],
                weak_evidence_bonus=bonuses["weak_evidence_bonus"],
                priority_adjustment_reasons=adjustment_reasons,
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
                first_posting_date=(
                    _date_string(rows["posting_date"].min())
                    if "posting_date" in rows.columns
                    else None
                ),
                last_posting_date=(
                    _date_string(rows["posting_date"].max())
                    if "posting_date" in rows.columns
                    else None
                ),
                repeat_months=repeat_months,
                representative_explanation=auditor_insight["risk_narrative"],
                review_focus=auditor_insight["review_focus"],
                risk_narrative=auditor_insight["risk_narrative"],
                recommended_audit_actions=auditor_insight["recommended_audit_actions"],
                rule_evidence_summary=auditor_insight["rule_evidence_summary"],
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
                has_repeat_pattern=(repeat_months >= repeat_tiebreak) or l304_repeat_pattern,
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


def _build_theme_summaries(
    cases: list[CaseGroupResult],
    top_n_per_theme: int,
) -> list[ThemeSummary]:
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
    summaries.sort(
        key=lambda item: (item.high_count, item.total_amount, item.case_count),
        reverse=True,
    )
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


def _secondary_tags(
    theme_id: str,
    evidence_scores: dict[str, float],
    config: dict[str, Any],
) -> list[str]:
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


def _build_document_refs(
    rows: pd.DataFrame,
    hits: list[_RawHit],
    config: dict[str, Any],
) -> list[CaseDocumentRef]:
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


def _apply_priority_adjustments(
    *,
    rows: pd.DataFrame,
    case_hits: list[_RawHit],
    evidence_types: list[str],
    priority_score: float,
    behavior_score: float,
    config: dict[str, Any],
) -> tuple[float, float, list[str], dict[str, float]]:
    adjustments = config.get("priority_adjustments", {})
    bonuses = {
        "topside_bonus": 0.0,
        "batch_combo_bonus": 0.0,
        "weak_evidence_bonus": 0.0,
    }
    if adjustments.get("enabled", True) is False:
        return priority_score, behavior_score, [], bonuses

    rule_ids = {hit.rule_id for hit in case_hits}
    reasons: list[str] = []
    adjusted_priority = float(priority_score)
    adjusted_behavior = float(behavior_score)

    topside_score = _case_topside_score(rows, rule_ids, adjustments.get("topside", {}))
    topside_cfg = adjustments.get("topside", {})
    if topside_score >= float(topside_cfg.get("high_threshold", 0.60)):
        bonuses["topside_bonus"] = float(topside_cfg.get("high_bonus", 0.20))
        reasons.append(f"topside_score={topside_score:.2f}")
    elif topside_score >= float(topside_cfg.get("medium_threshold", 0.40)):
        bonuses["topside_bonus"] = float(topside_cfg.get("medium_bonus", 0.10))
        reasons.append(f"topside_score={topside_score:.2f}")

    batch_count = _batch_corroboration_group_count(rule_ids)
    batch_cfg = adjustments.get("batch_combo", {})
    if "L4-06" in rule_ids and batch_count >= int(batch_cfg.get("high_group_count", 3)):
        bonuses["batch_combo_bonus"] = float(batch_cfg.get("high_bonus", 0.15))
        adjusted_behavior = max(
            adjusted_behavior,
            float(batch_cfg.get("high_behavior_floor", 1.0)),
        )
        reasons.append(f"batch_combo_groups={batch_count}")
    elif "L4-06" in rule_ids and batch_count >= int(batch_cfg.get("medium_group_count", 2)):
        bonuses["batch_combo_bonus"] = float(batch_cfg.get("medium_bonus", 0.08))
        adjusted_behavior = max(
            adjusted_behavior,
            float(batch_cfg.get("medium_behavior_floor", 0.70)),
        )
        reasons.append(f"batch_combo_groups={batch_count}")

    weak_tags = _case_weak_evidence_tags(
        rows=rows,
        rule_ids=rule_ids,
        evidence_types=evidence_types,
        config=adjustments.get("weak_evidence", {}),
    )
    weak_cfg = adjustments.get("weak_evidence", {})
    if weak_tags:
        bonuses["weak_evidence_bonus"] = min(
            len(weak_tags) * float(weak_cfg.get("per_tag_bonus", 0.03)),
            float(weak_cfg.get("max_bonus", 0.09)),
        )
        reasons.append("weak_evidence=" + ",".join(weak_tags))

    adjusted_priority += sum(bonuses.values())
    return max(0.0, min(adjusted_priority, 1.0)), adjusted_behavior, reasons, bonuses


def _case_topside_score(
    rows: pd.DataFrame,
    rule_ids: set[str],
    config: dict[str, Any],
) -> float:
    if config.get("require_manual", True) and not _case_has_true(rows, "is_manual_je"):
        return 0.0

    matched = 0
    for _label, rule_pairs in TOPSIDE_BONUS_RULES:
        if any(rule_id in rule_ids for rule_id, _layer_name in rule_pairs):
            matched += 1
    return matched / max(len(TOPSIDE_BONUS_RULES), 1)


def _batch_corroboration_group_count(rule_ids: set[str]) -> int:
    count = 0
    for _label, rule_pairs in BATCH_CORROBORATION_RULES:
        if any(rule_id in rule_ids for rule_id, _layer_name in rule_pairs):
            count += 1
    return count


def _case_weak_evidence_tags(
    *,
    rows: pd.DataFrame,
    rule_ids: set[str],
    evidence_types: list[str],
    config: dict[str, Any],
) -> list[str]:
    strong_evidence = {
        "control_failure",
        "timing_anomaly",
        "logic_mismatch",
        "duplicate_or_outflow",
    }
    if config.get("require_strong_evidence", True) and not (
        strong_evidence & set(evidence_types)
    ):
        return []

    tags: list[str] = []
    default_columns = [
        "is_round_number",
        "is_rare_account",
        "significant_unusual_transaction",
        "is_period_end_manual",
        "sensitive_account_touch",
    ]
    for column in config.get("boolean_columns", default_columns):
        if _case_has_true(rows, str(column)):
            tags.append(str(column))

    if config.get("include_l3_08_as_weak_description", True) and "L3-08" in rule_ids:
        tags.append("missing_or_corrupted_description")

    if (
        config.get("derive_manual_period_end", True)
        and _case_has_true(rows, "is_manual_je")
        and (_case_has_true(rows, "is_period_end") or "L3-04" in rule_ids)
    ):
        tags.append("manual_period_end")

    return sorted(set(tags))


def _case_has_true(rows: pd.DataFrame, column: str) -> bool:
    if column not in rows.columns:
        return False
    return bool(rows[column].fillna(False).astype(bool).any())


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


def _apply_timing_priority_adjustments(
    *,
    df: pd.DataFrame,
    theme_id: str,
    rows: pd.DataFrame,
    case_hits: list[_RawHit],
    secondary_tags: list[str],
    amount_score: float,
    behavior_score: float,
    repeat_score: float,
    priority_score: float,
    config: dict[str, Any],
) -> tuple[float, float, float]:
    """Tune L3-04 case priority without changing detection coverage."""
    if theme_id != "timing_anomaly":
        return priority_score, behavior_score, repeat_score

    rule_ids = {hit.rule_id for hit in case_hits}
    if "L3-04" not in rule_ids:
        return priority_score, behavior_score, repeat_score

    timing_cfg = config.get("timing_priority", {})
    l304_only = rule_ids == {"L3-04"}
    has_sensitive = _case_has_sensitive_account(rows, timing_cfg)
    has_high_amount = amount_score >= float(timing_cfg.get("l304_high_amount_case_score", 0.75))
    has_combo_signal = bool(
        rule_ids & {"L3-05", "L3-06", "L3-07", "L3-08", "L3-11", "L4-05", "L4-03"}
        or {"control_failure", "duplicate_or_outflow"} & set(secondary_tags)
    )
    repeat_pattern = _is_l304_repeat_pattern_case(df, rows, case_hits, timing_cfg)

    adjusted_priority = float(priority_score)
    adjusted_behavior = float(behavior_score)
    adjusted_repeat = float(repeat_score)

    if l304_only:
        adjusted_priority -= float(timing_cfg.get("l304_only_penalty", 0.20))
    if has_sensitive:
        adjusted_priority += float(timing_cfg.get("l304_sensitive_bonus", 0.15))
    if has_high_amount:
        adjusted_priority += float(timing_cfg.get("l304_high_amount_bonus", 0.10))
    if has_combo_signal:
        combo_bonus = float(timing_cfg.get("l304_combo_bonus", 0.20))
        adjusted_priority += combo_bonus
        adjusted_behavior = min(adjusted_behavior + (combo_bonus / 2.0), 1.0)
    if repeat_pattern:
        adjusted_priority -= float(timing_cfg.get("l304_repeat_pattern_penalty", 0.15))
        adjusted_repeat = min(
            adjusted_repeat,
            float(timing_cfg.get("l304_repeat_pattern_repeat_cap", 0.30)),
        )

    return max(0.0, min(adjusted_priority, 1.0)), adjusted_behavior, adjusted_repeat


def _case_has_sensitive_account(rows: pd.DataFrame, timing_cfg: dict[str, Any]) -> bool:
    prefixes = [
        str(value).strip()
        for value in timing_cfg.get("l304_sensitive_account_prefixes", [])
        if str(value).strip()
    ]
    if not prefixes or "gl_account" not in rows.columns:
        return False
    gl = rows["gl_account"].fillna("").astype(str).str.strip()
    return bool(gl.str.startswith(tuple(prefixes), na=False).any())


def _is_l304_repeat_pattern_case(
    df: pd.DataFrame,
    rows: pd.DataFrame,
    case_hits: list[_RawHit],
    timing_cfg: dict[str, Any],
) -> bool:
    """Approximate recurring close-entry pattern for L3-04-only cases."""
    if {hit.rule_id for hit in case_hits} != {"L3-04"}:
        return False

    required = {"posting_date", "source", "document_type", "business_process", "gl_account"}
    if not required.issubset(rows.columns):
        return False

    work = rows.copy()
    posting = pd.to_datetime(work["posting_date"], errors="coerce")
    work = work.loc[posting.notna()].copy()
    posting = posting.loc[posting.notna()]
    if work.empty:
        return False

    work = _add_l304_repeat_signature_columns(work, posting)
    signature_share = work["pattern_signature"].value_counts(normalize=True, dropna=False)
    if signature_share.empty:
        return False

    dominant_signature = str(signature_share.index[0])
    if float(signature_share.iloc[0]) < float(
        timing_cfg.get("l304_repeat_pattern_min_signature_share", 0.60)
    ):
        return False

    all_rows = df.copy()
    all_posting = pd.to_datetime(all_rows["posting_date"], errors="coerce")
    all_rows = all_rows.loc[all_posting.notna()].copy()
    all_posting = all_posting.loc[all_posting.notna()]
    if all_rows.empty:
        return False

    all_rows = _add_l304_repeat_signature_columns(all_rows, all_posting)
    dominant = all_rows.loc[all_rows["pattern_signature"] == dominant_signature].copy()
    repeat_months = int(dominant["period_month"].nunique())
    if repeat_months < int(timing_cfg.get("l304_repeat_pattern_min_months", 3)):
        return False

    monthly_amounts = dominant.groupby("period_month")["amount"].median()
    if monthly_amounts.empty:
        return False
    mean_amount = float(monthly_amounts.mean())
    if mean_amount <= 0:
        return False

    amount_cv = (
        float(monthly_amounts.std(ddof=0) / mean_amount)
        if len(monthly_amounts) > 1
        else 0.0
    )
    return amount_cv <= float(timing_cfg.get("l304_repeat_pattern_max_amount_cv", 0.35))


def _add_l304_repeat_signature_columns(
    rows: pd.DataFrame,
    posting: pd.Series,
) -> pd.DataFrame:
    result = rows.copy()
    result["period_month"] = posting.dt.strftime("%Y-%m")
    result["period_side"] = posting.dt.day.map(
        lambda day: "month_start" if day <= 5 else "month_end"
    )
    result["amount"] = result.apply(_line_amount, axis=1)
    result["pattern_signature"] = (
        result["source"].fillna("").astype(str).str.strip()
        + "|"
        + result["document_type"].fillna("").astype(str).str.strip()
        + "|"
        + result["business_process"].fillna("").astype(str).str.strip()
        + "|"
        + result["gl_account"].fillna("").astype(str).str.strip()
        + "|"
        + result["period_side"]
    )
    return result


def _repeat_months(rows: pd.DataFrame) -> int:
    if "posting_date" not in rows.columns:
        return 0
    series = pd.to_datetime(rows["posting_date"], errors="coerce").dt.strftime("%Y-%m").dropna()
    return int(series.nunique())


def _case_total_amount(df: pd.DataFrame, indices: set[int] | list[int]) -> float:
    rows = df.loc[sorted(indices)]
    return float(rows.apply(_line_amount, axis=1).sum())


def _auditor_insight(
    *,
    theme_id: str,
    case_hits: list[_RawHit],
    total_amount: float,
) -> dict[str, Any]:
    ordered_hits = sorted(
        case_hits,
        key=lambda hit: (
            _STRENGTH_RANK.get(_rule_evidence_strength(hit), 0),
            hit.severity,
            hit.score,
        ),
        reverse=True,
    )
    review_focus = _ordered_unique(_rule_focus(hit.rule_id) for hit in ordered_hits)
    recommended_actions = _ordered_unique(
        action
        for hit in ordered_hits
        for action in _rule_actions(hit.rule_id)
    )
    rule_evidence_summary = [_rule_evidence_summary(hit) for hit in ordered_hits]
    risk_narrative = _risk_narrative(
        theme_id=theme_id,
        case_hits=ordered_hits,
        total_amount=total_amount,
    )
    return {
        "review_focus": review_focus,
        "risk_narrative": risk_narrative,
        "recommended_audit_actions": recommended_actions,
        "rule_evidence_summary": rule_evidence_summary,
    }


def _risk_narrative(
    *,
    theme_id: str,
    case_hits: list[_RawHit],
    total_amount: float,
) -> str:
    rule_ids = sorted({hit.rule_id for hit in case_hits})
    evidence_types = sorted({hit.evidence_type for hit in case_hits})
    primary_evidence = _pick_primary_explanation_evidence_for_theme(theme_id, evidence_types)

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
        return f"{label} 징후가 관찰되었고 총금액은 {total_amount:,.0f}입니다. 관련 근거와 증빙을 확인해야 합니다."
    return f"{label} 징후가 관찰되었습니다. 관련 근거와 증빙을 확인해야 합니다."


def _pick_primary_explanation_evidence_for_theme(
    theme_id: str,
    evidence_types: list[str],
) -> str | None:
    evidence_set = set(evidence_types)
    priority = _THEME_EXPLANATION_PRIORITY.get(theme_id, _EXPLANATION_PRIORITY)
    for evidence in priority:
        if evidence in evidence_set:
            return evidence
    return None


def _rule_metadata(rule_id: str) -> dict[str, Any]:
    return _RULE_EXPRESSION_METADATA.get(rule_id, {})


def _rule_focus(rule_id: str) -> str:
    metadata = _rule_metadata(rule_id)
    focus = metadata.get("focus")
    if isinstance(focus, str) and focus:
        return focus
    return rule_id.lower().replace("-", "_")


def _rule_actions(rule_id: str) -> list[str]:
    metadata = _rule_metadata(rule_id)
    actions = metadata.get("action", [])
    if isinstance(actions, list):
        return [str(action) for action in actions if str(action).strip()]
    return []


def _rule_evidence_strength(hit: _RawHit) -> str:
    metadata = _rule_metadata(hit.rule_id)
    strength = metadata.get("evidence_strength")
    if strength in _STRENGTH_RANK:
        return str(strength)
    if hit.severity >= 4:
        return "strong"
    if hit.severity >= 3:
        return "medium"
    return "weak"


def _rule_evidence_summary(hit: _RawHit) -> dict[str, Any]:
    return {
        "rule_id": hit.rule_id,
        "rule_label": _rule_label(hit.rule_id),
        "evidence_type": hit.evidence_type,
        "evidence_strength": _rule_evidence_strength(hit),
        "focus": _rule_focus(hit.rule_id),
        "severity": hit.severity,
        "summary": _rule_summary_text(hit),
    }


def _rule_summary_text(hit: _RawHit) -> str:
    if hit.rule_id == "L3-10" and hit.detail:
        return f"{_rule_label(hit.rule_id)}: {hit.detail}"
    strength_label = {
        "strong": "강한",
        "medium": "중간",
        "weak": "보조",
    }.get(_rule_evidence_strength(hit), "보조")
    label = _rule_label(hit.rule_id)
    theme_label = _THEME_LABELS.get(hit.evidence_type, hit.evidence_type)
    return f"{label}: {strength_label} {theme_label} 근거"


def _rule_label(rule_id: str) -> str:
    for mapping in (
        _CONTROL_RULES,
        _OUTFLOW_RULES,
        _LOGIC_RULES,
        _TIMING_RULES,
        _STAT_RULES,
        _INTEGRITY_RULES,
        _INTERCOMPANY_RULES,
    ):
        label = mapping.get(rule_id)
        if label:
            return label
    return rule_id


def _ordered_unique(values) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _pick_primary_explanation_evidence(evidence_types: list[str]) -> str | None:
    evidence_set = set(evidence_types)
    for evidence in _EXPLANATION_PRIORITY:
        if evidence in evidence_set:
            return evidence
    return None


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
        return f"{label} 징후가 관찰되었고 총금액은 {total_amount:,.0f}입니다."
    return f"{label} 징후가 관찰되었습니다."


def _control_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _CONTROL_RULES) or ["승인 통제 위반"]
    lead = " + ".join(labels[:3])
    if total_amount > 0:
        return (
            f"{lead}이 함께 발생했고 관련 전표 총금액은 {total_amount:,.0f}입니다. "
            "승인·권한 통제 적용과 예외 승인 근거를 우선 확인해야 합니다."
        )
    return (
        f"{lead}이 함께 발생했습니다. "
        "승인·권한 통제 적용과 예외 승인 근거를 우선 확인해야 합니다."
    )


def _outflow_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _OUTFLOW_RULES)
    lead = " + ".join(labels[:3]) if labels else "지급·중복 징후"
    if total_amount > 0:
        return (
            f"{lead}가 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. "
            "동일 지급·중복 처리 여부와 승인·증빙 대사를 확인해야 합니다."
        )
    return (
        f"{lead}가 관찰되었습니다. "
        "동일 지급·중복 처리 여부와 승인·증빙 대사를 확인해야 합니다."
    )


def _logic_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _LOGIC_RULES)
    lead = " + ".join(labels[:3]) if labels else "회계 처리 논리 이상"
    if total_amount > 0:
        return (
            f"{lead}이 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. "
            "거래의 경제적 실질과 계정 사용이 맞는지 재검토해야 합니다."
        )
    return (
        f"{lead}이 관찰되었습니다. "
        "거래의 경제적 실질과 계정 사용이 맞는지 재검토해야 합니다."
    )


def _timing_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _TIMING_RULES)
    lead = " + ".join(labels[:3]) if labels else "기말·시점 이상"
    if total_amount > 0:
        return (
            f"{lead}이 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. "
            "결산 시점의 기간 귀속, 결산 조정 승인, 사후 보정 근거를 확인해야 합니다."
        )
    return (
        f"{lead}이 관찰되었습니다. "
        "결산 시점의 기간 귀속, 결산 조정 승인, 사후 보정 근거를 확인해야 합니다."
    )


def _statistical_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _STAT_RULES)
    lead = " + ".join(labels[:3]) if labels else "통계적 이상치"
    if total_amount > 0:
        return (
            f"{lead}가 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. "
            "일반 분포에서 벗어난 예외 거래인지 확인이 필요합니다."
        )
    return f"{lead}가 관찰되었습니다. 일반 분포에서 벗어난 예외 거래인지 확인이 필요합니다."


def _intercompany_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _INTERCOMPANY_RULES)
    lead = " + ".join(labels[:3]) if labels else "관계사 거래 검토 신호"
    if total_amount > 0:
        return (
            f"{lead}가 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. "
            "거래 상대방, 계약 근거, 정상 가격 및 대사 여부를 확인해야 합니다."
        )
    return (
        f"{lead}가 관찰되었습니다. "
        "거래 상대방, 계약 근거, 정상 가격 및 대사 여부를 확인해야 합니다."
    )


def _integrity_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _INTEGRITY_RULES)
    lead = " + ".join(labels[:3]) if labels else "데이터 정합성 오류"
    if total_amount > 0:
        return (
            f"{lead}가 관찰되었고 관련 금액은 {total_amount:,.0f}입니다. "
            "원천 데이터와 장부 반영 내역의 정합성을 먼저 점검해야 합니다."
        )
    return f"{lead}가 관찰되었습니다. 원천 데이터와 장부 반영 내역의 정합성을 먼저 점검해야 합니다."


def _ordered_rule_labels(rule_ids: list[str], mapping: dict[str, str]) -> list[str]:
    labels: list[str] = []
    for rule_id in rule_ids:
        label = mapping.get(rule_id)
        if label and label not in labels:
            labels.append(label)
    return labels


def _rule_hit_detail(
    rule_id: str,
    base_detail: str | None,
    row_annotation: dict[str, Any] | None,
) -> str | None:
    """Render row-level detail for case drill-down."""

    if rule_id == "L2-05" and row_annotation:
        label = str(row_annotation.get("interpretation_label", "")).strip()
        primary_signal = str(row_annotation.get("primary_signal", "")).strip()
        reason = str(row_annotation.get("reason_text", "")).strip()
        parts = [part for part in [label, primary_signal, reason] if part]
        if not parts:
            return base_detail
        if base_detail:
            return f"{base_detail}; {'; '.join(parts)}"
        return "; ".join(parts)

    if rule_id != "L3-10" or not row_annotation:
        return base_detail

    match_type = str(row_annotation.get("match_type", "")).strip()
    matched_value = str(row_annotation.get("matched_value", "")).strip()
    matched_group = str(row_annotation.get("matched_group", "")).strip()
    signal_category = str(row_annotation.get("signal_category", "")).strip()
    category_reason = str(row_annotation.get("category_reason", "")).strip()

    parts: list[str] = []
    if match_type and matched_value:
        parts.append(f"{match_type}={matched_value}")
    if matched_group:
        parts.append(f"group={matched_group}")
    if signal_category:
        parts.append(f"result={signal_category}")
    if category_reason:
        parts.append(f"reason={category_reason}")

    if not parts:
        return base_detail
    if base_detail:
        return f"{base_detail}; {'; '.join(parts)}"
    return "; ".join(parts)


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
    counterparty_columns = config.get(
        "counterparty_columns",
        ("auxiliary_account_number", "vendor_name", "customer_name"),
    )
    for field in counterparty_columns:
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
