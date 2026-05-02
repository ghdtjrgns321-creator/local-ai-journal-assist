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
from src.detection.rule_scoring import normalize_rule_evidence
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
    "access_scope_review",
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
    "L3-12": ("access_scope_review", "access_scope_review"),
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

_MACRO_FINDING_RULES = {"L4-02", "D01", "D02", "GR01", "GR03"}

_THEME_EXPLANATION_PRIORITY = {
    "control_failure": (
        "control_failure",
        "access_scope_review",
        "statistical_outlier",
        "timing_anomaly",
        "logic_mismatch",
        "duplicate_or_outflow",
        "intercompany_structure",
        "data_integrity_failure",
    ),
    "access_scope_review": (
        "access_scope_review",
        "control_failure",
        "logic_mismatch",
        "timing_anomaly",
        "statistical_outlier",
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
    "L3-12": {
        "evidence_strength": "weak",
        "focus": "work_scope_concentration",
        "action": [
            "한 사용자의 다중 업무 관여가 해당 기간에 예정된 역할인지 확인",
            "수기·민감계정·고액·결산 맥락이 있으면 대체 검토 통제 확인",
        ],
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
    "access_scope_review": "업무범위 집중 검토",
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
    "L3-12": "Work scope concentration",
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
    signal_strength: float
    normalized_score: float
    evidence_strength: str
    scoring_role: str
    display_label: str
    signal_status: str
    document_id: str
    record_id: str | None
    detail: str | None
    annotation: dict[str, Any] | None = None


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
    macro_findings = _build_macro_findings(
        results,
        df=df,
        top_n=int(config.get("top_n_macro_findings", 100)),
    )
    raw_hits = _collect_raw_hits(df, results)
    cases = _build_cases(df, raw_hits, config, macro_findings)
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
            "macro_findings": macro_findings,
            "macro_finding_count": len(macro_findings),
            "macro_finding_policy": (
                "L4-02/D01/D02/GR01/GR03 are Account/Process Queue findings. They do not create "
                "transaction queue priority_score or row-level anomaly_score by themselves."
            ),
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
        result.metadata["phase1_macro_finding_count"] = reference[
            "phase1_macro_finding_count"
        ]
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
        "phase1_macro_finding_count": int(
            phase1_result.metadata.get("macro_finding_count", 0) or 0
        ),
        "top_theme_ids": [summary.theme_id for summary in phase1_result.theme_summaries[:3]],
        "phase1_case_schema_version": phase1_result.schema_version,
    }


def _build_macro_findings(
    results: list[DetectionResult],
    *,
    df: pd.DataFrame | None = None,
    top_n: int,
) -> list[dict[str, Any]]:
    """Build Account/Process Queue findings that must not enter transaction scoring."""

    findings: list[dict[str, Any]] = []
    for result in results:
        metadata = result.metadata or {}
        findings.extend(_build_l402_macro_findings(result.track_name, metadata))
        findings.extend(_build_d01_macro_findings(result.track_name, metadata))
        findings.extend(_build_d02_macro_findings(result.track_name, metadata))
        findings.extend(_build_graph_macro_findings(result.track_name, result.details, df))

    findings.sort(
        key=lambda item: (
            float(item.get("macro_priority_score") or item.get("review_score") or 0.0),
            int(item.get("candidate_rows") or item.get("review_row_count") or 0),
        ),
        reverse=True,
    )
    if top_n > 0:
        findings = findings[:top_n]
    return [_json_safe_mapping(item) for item in findings]


def _build_l402_macro_findings(
    track_name: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, finding in enumerate(metadata.get("benford_findings", []) or [], start=1):
        if not isinstance(finding, dict):
            continue
        rows.append({
            "finding_id": f"L4-02:{ordinal:04d}",
            "rule_id": "L4-02",
            "rule_label": "Benford population anomaly",
            "queue_type": "account_process_macro",
            "source_track": track_name,
            "scope": finding.get("scope") or "company_gl_account",
            "company_code": finding.get("company_code"),
            "gl_account": finding.get("gl_account"),
            "sample_size": finding.get("sample_size"),
            "review_score": finding.get("candidate_score", 0.0),
            "finding_severity": finding.get("finding_severity", ""),
            "candidate_rows": finding.get("candidate_rows", 0),
            "candidate_documents": finding.get("candidate_documents"),
            "flagged_digits": finding.get("flagged_digits", []),
            "metrics": {
                "mad": finding.get("mad"),
                "chi2_p_value": finding.get("chi2_p_value"),
                "max_deviation": finding.get("max_deviation"),
            },
            "interpretation": (
                "Population-level digit distribution finding. Drill-down rows are "
                "review candidates, not confirmed transaction exceptions."
            ),
        })
    return rows


def _build_d01_macro_findings(
    track_name: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, finding in enumerate(
        metadata.get("account_activity_variance", []) or [],
        start=1,
    ):
        if not isinstance(finding, dict):
            continue
        priority_score = _d01_macro_priority_score(finding)
        queue_bucket = _d01_queue_bucket(finding)
        normal_likelihood = _d01_normal_likelihood(finding, queue_bucket)
        rows.append({
            "finding_id": f"D01:{ordinal:04d}",
            "rule_id": "D01",
            "rule_label": "Account activity variance",
            "queue_type": "account_process_macro",
            "source_track": track_name,
            "scope": "company_gl_account" if finding.get("company_code") else "gl_account",
            "fiscal_year": finding.get("fiscal_year"),
            "prior_fiscal_year": finding.get("prior_fiscal_year"),
            "company_code": finding.get("company_code"),
            "gl_account": finding.get("gl_account"),
            "review_row_count": finding.get("review_row_count", 0),
            "review_score": finding.get("weighted_variance", 0.0),
            "macro_priority_score": priority_score,
            "queue_bucket": queue_bucket,
            "normal_likelihood": normal_likelihood,
            "scoring_policy": "macro_priority_calibrated_not_row_score",
            "finding_severity": queue_bucket,
            "business_event_type": finding.get("business_event_type"),
            "precision_policy": finding.get("precision_policy"),
            "metrics": {
                "current_total_amount": finding.get("current_total_amount"),
                "prior_total_amount": finding.get("prior_total_amount"),
                "total_var": finding.get("total_var"),
                "count_var": finding.get("count_var"),
                "avg_var": finding.get("avg_var"),
                "weighted_variance": finding.get("weighted_variance"),
                "d01_target_document_count": finding.get("d01_target_document_count"),
                "non_d01_document_count": finding.get("non_d01_document_count"),
            },
            "interpretation": (
                "Account-level activity shift finding. Use it to select accounts for "
                "analytical review and corroborate transaction-level exceptions."
            ),
        })
    return rows


def _build_d02_macro_findings(
    track_name: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, finding in enumerate(metadata.get("d02_account_diagnostics", []) or [], start=1):
        if not isinstance(finding, dict) or not bool(finding.get("flagged", False)):
            continue
        priority_score = _d02_macro_priority_score(finding)
        queue_bucket = _d02_queue_bucket(finding)
        normal_likelihood = _d02_normal_likelihood(finding, queue_bucket)
        rows.append({
            "finding_id": f"D02:{ordinal:04d}",
            "rule_id": "D02",
            "rule_label": "Monthly pattern shift",
            "queue_type": "account_process_macro",
            "source_track": track_name,
            "scope": "company_gl_account" if finding.get("company_code") else "gl_account",
            "fiscal_year": finding.get("fiscal_year"),
            "prior_fiscal_year": finding.get("prior_fiscal_year"),
            "company_code": finding.get("company_code"),
            "gl_account": finding.get("gl_account"),
            "group_key": finding.get("d02_group_key"),
            "review_score": finding.get("jsd", 0.0),
            "macro_priority_score": priority_score,
            "queue_bucket": queue_bucket,
            "normal_likelihood": normal_likelihood,
            "scoring_policy": "macro_priority_calibrated_not_row_score",
            "finding_severity": queue_bucket,
            "scenario_type": finding.get("scenario_type"),
            "metrics": {
                key: value
                for key, value in finding.items()
                if key not in {"flagged", "company_code", "gl_account", "d02_group_key"}
            },
            "interpretation": (
                "Account-level monthly distribution shift finding. It does not identify "
                "one incorrect journal line without corroborating evidence."
            ),
        })
    return rows


def _build_graph_macro_findings(
    track_name: str,
    details: pd.DataFrame | None,
    df: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    """Build macro queue items for graph findings without row score inflation."""

    if details is None or details.empty or df is None or df.empty:
        return []

    rows: list[dict[str, Any]] = []
    for rule_id in ("GR01", "GR03"):
        if rule_id not in details.columns:
            continue
        scores = pd.to_numeric(details[rule_id].reindex(df.index), errors="coerce").fillna(0.0)
        if not scores.gt(0).any():
            continue

        work = df.loc[scores.gt(0)].copy()
        work["_graph_score"] = scores.loc[work.index].astype(float)
        work["_row_position"] = [df.index.get_loc(index_value) for index_value in work.index]
        group_columns = [
            column
            for column in ("fiscal_year", "company_code", "gl_account")
            if column in work.columns
        ]
        if not group_columns:
            group_columns = ["_graph_scope"]
            work["_graph_scope"] = "all"

        for ordinal, (_group_key, group) in enumerate(
            work.groupby(group_columns, dropna=False),
            start=1,
        ):
            review_score = float(group["_graph_score"].max())
            document_ids = _ordered_unique(
                _string_value(value)
                for value in group.get("document_id", pd.Series(dtype=object)).tolist()
                if _string_value(value)
            )
            rows.append({
                "finding_id": f"{rule_id}:{ordinal:04d}",
                "rule_id": rule_id,
                "rule_label": _graph_rule_label(rule_id),
                "queue_type": "account_process_macro",
                "source_track": track_name,
                "scope": "company_gl_account" if "company_code" in group_columns else "gl_account",
                "fiscal_year": _first_group_value(group, "fiscal_year"),
                "company_code": _first_group_value(group, "company_code"),
                "gl_account": _first_group_value(group, "gl_account"),
                "review_score": review_score,
                "macro_priority_score": _graph_macro_priority_score(review_score),
                "queue_bucket": _graph_queue_bucket(rule_id),
                "normal_likelihood": 0.35,
                "scoring_policy": "macro_priority_calibrated_not_row_score",
                "finding_severity": "graph_review",
                "candidate_rows": int(len(group)),
                "candidate_documents": len(document_ids),
                "document_ids": document_ids[:25],
                "row_indices": [int(value) for value in group["_row_position"].tolist()],
                "metrics": {
                    "max_graph_score": review_score,
                    "mean_graph_score": float(group["_graph_score"].mean()),
                },
                "interpretation": (
                    "Graph-level relationship finding. Use it as macro corroboration for "
                    "matching transaction-level cases, especially related-party review."
                ),
            })
    return rows


def _graph_rule_label(rule_id: str) -> str:
    if rule_id == "GR01":
        return "Graph circular transaction"
    if rule_id == "GR03":
        return "Graph transfer-pricing asymmetry"
    return rule_id


def _graph_queue_bucket(rule_id: str) -> str:
    if rule_id == "GR01":
        return "corroborated_graph_cycle"
    if rule_id == "GR03":
        return "corroborated_graph_transfer_pricing"
    return "corroborated_graph_review"


def _graph_macro_priority_score(review_score: float) -> float:
    return max(0.55, min(float(review_score), 0.85))


def _first_group_value(group: pd.DataFrame, column: str) -> Any:
    if column not in group.columns or group.empty:
        return None
    value = group[column].iloc[0]
    return None if pd.isna(value) else value


def _bounded_score(value: object, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(0.0, min(numeric, 1.0))


def _positive_int(value: object) -> int:
    try:
        return max(int(float(value)), 0)
    except (TypeError, ValueError):
        return 0


def _d01_queue_bucket(finding: dict[str, Any]) -> str:
    bucket = str(finding.get("evaluation_bucket") or "").strip().lower()
    policy = str(finding.get("precision_policy") or "").strip().lower()
    event_type = str(finding.get("business_event_type") or "").strip().lower()
    scenario = str(finding.get("scenario_type") or "").strip().lower()

    if bucket == "confirmed_truth" or policy == "count_as_d01_truth":
        return "confirmed_account_shift"
    if bucket == "normal_business_control" or policy.startswith("expected_raw_flag_but"):
        return "normal_business_review"
    if bucket == "auxiliary_non_d01_context":
        return "auxiliary_non_d01_context"
    if bucket == "review_queue":
        return "analytical_review"
    if _positive_int(finding.get("d01_target_document_count")) > 0:
        return "corroborated_account_shift"
    if scenario.startswith("normal_") or event_type in {
        "price_increase",
        "volume_growth",
        "high_volume_operations",
        "capex_investment_event",
        "working_capital_timing",
        "working_capital_or_investment_timing",
        "recurring_or_system_volume_shift",
        "entity_process_expansion",
    }:
        return "normal_business_review"
    return "analytical_review"


def _d01_normal_likelihood(finding: dict[str, Any], queue_bucket: str) -> float:
    if queue_bucket == "normal_business_review":
        return 0.85
    if queue_bucket == "auxiliary_non_d01_context":
        return 0.70
    if queue_bucket == "analytical_review":
        return 0.45
    if queue_bucket == "corroborated_account_shift":
        return 0.20
    return 0.05


def _d01_macro_priority_score(finding: dict[str, Any]) -> float:
    weighted = _bounded_score(float(finding.get("weighted_variance") or 0.0) / 3.0)
    target_docs = _positive_int(finding.get("d01_target_document_count"))
    queue_bucket = _d01_queue_bucket(finding)

    if queue_bucket == "confirmed_account_shift":
        return max(0.75, min(1.0, 0.65 + weighted * 0.25 + min(target_docs, 5) * 0.02))
    if queue_bucket == "corroborated_account_shift":
        return max(0.55, min(0.80, 0.45 + weighted * 0.25 + min(target_docs, 3) * 0.03))
    if queue_bucket == "normal_business_review":
        return min(0.35, 0.12 + weighted * 0.18)
    if queue_bucket == "auxiliary_non_d01_context":
        return min(0.40, 0.18 + weighted * 0.18)
    return min(0.55, 0.25 + weighted * 0.25)


def _d02_queue_bucket(finding: dict[str, Any]) -> str:
    scenario = str(finding.get("scenario_type") or "").strip().lower()
    sources = str(finding.get("sources") or "").strip().lower()
    target_docs = _positive_int(finding.get("d02_target_document_count"))
    normal_docs = _positive_int(finding.get("normal_context_document_count"))

    if scenario in {
        "revenue_period_end_push",
        "expense_deferral_or_yearend_concentration",
        "target_anomaly_monthly_shift",
        "manual_monthly_shift_with_target_anomaly",
    }:
        return "confirmed_monthly_shift"
    if target_docs > 0:
        return "corroborated_monthly_shift"
    if scenario.startswith("normal_"):
        return "normal_pattern_review"
    if normal_docs > target_docs:
        return "auxiliary_non_d02_context"
    if any(token in sources for token in ("automated", "recurring", "interface", "batch", "system")):
        return "normal_pattern_review"
    return "analytical_review"


def _d02_normal_likelihood(finding: dict[str, Any], queue_bucket: str) -> float:
    if queue_bucket == "normal_pattern_review":
        return 0.85
    if queue_bucket == "auxiliary_non_d02_context":
        return 0.70
    if queue_bucket == "analytical_review":
        return 0.45
    if queue_bucket == "corroborated_monthly_shift":
        return 0.20
    return 0.05


def _d02_macro_priority_score(finding: dict[str, Any]) -> float:
    jsd = _bounded_score(finding.get("jsd"))
    top_delta = _bounded_score(finding.get("top_month_delta"))
    target_docs = _positive_int(finding.get("d02_target_document_count"))
    queue_bucket = _d02_queue_bucket(finding)
    shape_score = max(jsd, top_delta)

    if queue_bucket == "confirmed_monthly_shift":
        return max(0.75, min(1.0, 0.62 + shape_score * 0.25 + min(target_docs, 5) * 0.02))
    if queue_bucket == "corroborated_monthly_shift":
        return max(0.55, min(0.80, 0.42 + shape_score * 0.25 + min(target_docs, 3) * 0.03))
    if queue_bucket == "normal_pattern_review":
        return min(0.35, 0.12 + shape_score * 0.20)
    if queue_bucket == "auxiliary_non_d02_context":
        return min(0.40, 0.18 + shape_score * 0.20)
    return min(0.55, 0.25 + shape_score * 0.25)


def _json_safe_mapping(item: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in item.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_value(child) for key, child in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe_value(child) for child in value]
    if isinstance(value, datetime | pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _collect_raw_hits(df: pd.DataFrame, results: list[DetectionResult]) -> list[_RawHit]:
    hits: list[_RawHit] = []
    row_positions = {label: pos for pos, label in enumerate(df.index)}
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
            for row_label, raw_score in column.items():
                row_pos = row_positions.get(row_label)
                if row_pos is None:
                    try:
                        candidate_pos = int(row_label)
                    except (TypeError, ValueError):
                        continue
                    if candidate_pos < 0 or candidate_pos >= len(df):
                        continue
                    row_pos = candidate_pos
                row = df.iloc[row_pos]
                document_id = _string_value(row.get("document_id")) or f"row-{row_pos}"
                row_annotation = _lookup_row_annotation(rule_annotations, row_label, row_pos)
                raw_score_float = float(raw_score)
                annotation_score = _annotation_score(row_annotation)
                score = max(raw_score_float, annotation_score)
                if score <= 0:
                    continue
                signal_status = (
                    "confirmed" if raw_score_float > 0 else "review_candidate"
                )
                normalized = normalize_rule_evidence(
                    rule_id=rule_flag.rule_id,
                    evidence_type=evidence_type,
                    severity=int(rule_flag.severity),
                    raw_value=score,
                    display_label=_row_display_label(row_annotation),
                )
                hits.append(
                    _RawHit(
                        rule_id=rule_flag.rule_id,
                        theme_id=theme_id,
                        evidence_type=evidence_type,
                        severity=int(rule_flag.severity),
                        row_index=row_pos,
                        score=float(score),
                        signal_strength=normalized.signal_strength,
                        normalized_score=normalized.normalized_score,
                        evidence_strength=normalized.evidence_strength,
                        scoring_role=normalized.scoring_role,
                        display_label=normalized.display_label,
                        signal_status=signal_status,
                        document_id=document_id,
                        record_id=_optional_string(row.get("record_id")),
                        detail=_rule_hit_detail(
                            rule_flag.rule_id,
                            rule_flag.detail,
                            row_annotation,
                        ),
                        annotation=row_annotation,
                    )
                )
    return hits


def _build_cases(
    df: pd.DataFrame,
    raw_hits: list[_RawHit],
    config: dict[str, Any],
    macro_findings: list[dict[str, Any]] | None = None,
) -> list[CaseGroupResult]:
    if not raw_hits:
        return []

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    hits_by_row: dict[int, list[_RawHit]] = defaultdict(list)
    for hit in raw_hits:
        hits_by_row[hit.row_index].append(hit)
        row = df.iloc[hit.row_index]
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
        rows = df.iloc[indices]
        case_hits = _collect_case_hits(indices, hits_by_row)
        evidence_types = sorted({hit.evidence_type for hit in case_hits})
        evidence_scores = _theme_scores(case_hits, config)
        total_amount = _case_total_amount(df, indices)
        amount_score = _amount_score(total_amount, max_amount, config)
        access_scope_score = min(evidence_scores.get("access_scope_review", 0.0), 1.0)
        control_score = min(evidence_scores.get("control_failure", 0.0), 1.0)
        duplicate_or_outflow_score = min(
            evidence_scores.get("duplicate_or_outflow", 0.0),
            1.0,
        )
        timing_score = min(evidence_scores.get("timing_anomaly", 0.0), 1.0)
        data_integrity_score = min(evidence_scores.get("data_integrity_failure", 0.0), 1.0)
        intercompany_score = min(evidence_scores.get("intercompany_structure", 0.0), 1.0)
        logic_score = min(
            max(
                evidence_scores.get("logic_mismatch", 0.0),
                intercompany_score,
                data_integrity_score,
            ),
            1.0,
        )
        behavior_score = max(min(len(indices) / 10.0, 1.0), access_scope_score)
        repeat_months = _repeat_months(rows)
        repeat_score = min(max(repeat_months - 1, 0) / 2.0, 1.0)
        secondary_tags = _secondary_tags(theme_id, evidence_scores, config)
        priority_score = _priority_score(
            amount_score=amount_score,
            control_score=control_score,
            duplicate_or_outflow_score=duplicate_or_outflow_score,
            logic_score=logic_score,
            timing_score=timing_score,
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
            amount_score=amount_score,
            total_amount=total_amount,
            priority_score=priority_score,
            behavior_score=behavior_score,
            config=config,
        )
        priority_score, floor_reasons = _apply_priority_floors(
            case_hits=case_hits,
            priority_score=priority_score,
            config=config,
        )
        adjustment_reasons.extend(floor_reasons)
        macro_contexts = _case_macro_contexts(rows, macro_findings or [])
        priority_score, macro_reasons = _apply_macro_context_priority(
            priority_score,
            macro_contexts,
        )
        adjustment_reasons.extend(macro_reasons)
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
                l301_priority_bonus=bonuses["l301_priority_bonus"],
                priority_adjustment_reasons=adjustment_reasons,
                priority_band=priority_band,
                amount_score=amount_score,
                control_score=control_score,
                duplicate_or_outflow_score=duplicate_or_outflow_score,
                logic_score=logic_score,
                data_integrity_score=data_integrity_score,
                intercompany_score=intercompany_score,
                timing_score=timing_score,
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
                evidence_tags=sorted({
                    *evidence_types,
                    *secondary_tags,
                    *(_macro_context_tags(macro_contexts)),
                }),
                macro_contexts=macro_contexts,
                documents=_build_document_refs(df, case_hits, config),
                raw_rule_hits=[
                    RawRuleHitRef(
                        rule_id=hit.rule_id,
                        severity=hit.severity,
                        document_id=hit.document_id,
                        row_index=hit.row_index,
                        record_id=hit.record_id,
                        score=hit.score,
                        signal_strength=hit.signal_strength,
                        normalized_score=hit.normalized_score,
                        evidence_strength=hit.evidence_strength,
                        scoring_role=hit.scoring_role,
                        display_label=hit.display_label,
                        signal_status=hit.signal_status,
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


def _case_macro_contexts(
    rows: pd.DataFrame,
    macro_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if rows.empty or not macro_findings or "gl_account" not in rows.columns:
        return []

    row_document_ids = {
        _string_value(value)
        for value in rows.get("document_id", pd.Series(dtype=object)).tolist()
        if _string_value(value)
    }
    row_keys = {
        (
            _macro_key_part(row.get("fiscal_year")),
            _macro_key_part(row.get("company_code")),
            _macro_key_part(row.get("gl_account")),
        )
        for _, row in rows.iterrows()
    }
    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding in macro_findings:
        rule_id = str(finding.get("rule_id") or "")
        if rule_id not in {"D01", "D02", "GR01", "GR03"}:
            continue
        macro_year = _macro_key_part(finding.get("fiscal_year"))
        macro_company = _macro_key_part(finding.get("company_code"))
        macro_account = _macro_key_part(finding.get("gl_account"))
        finding_document_ids = {
            _string_value(value)
            for value in finding.get("document_ids", []) or []
            if _string_value(value)
        }
        if not macro_account:
            continue
        if finding_document_ids and row_document_ids.intersection(finding_document_ids):
            matched = True
        else:
            matched = any(
                _macro_key_matches(
                    row_key,
                    (macro_year, macro_company, macro_account),
                )
                for row_key in row_keys
            )
        if not matched:
            continue
        context_id = str(finding.get("finding_id") or f"{rule_id}:{macro_account}")
        if context_id in seen:
            continue
        seen.add(context_id)
        contexts.append({
            "finding_id": context_id,
            "rule_id": rule_id,
            "queue_bucket": finding.get("queue_bucket"),
            "macro_priority_score": finding.get("macro_priority_score"),
            "normal_likelihood": finding.get("normal_likelihood"),
            "company_code": finding.get("company_code"),
            "gl_account": finding.get("gl_account"),
            "fiscal_year": finding.get("fiscal_year"),
            "review_score": finding.get("review_score"),
            "candidate_documents": finding.get("candidate_documents"),
            "scoring_effect": _macro_context_scoring_effect(finding),
        })
    contexts.sort(
        key=lambda item: (
            float(item.get("macro_priority_score") or 0.0),
            str(item.get("rule_id") or ""),
        ),
        reverse=True,
    )
    return contexts


def _macro_key_matches(
    row_key: tuple[str, str, str],
    macro_key: tuple[str, str, str],
) -> bool:
    row_year, row_company, row_account = row_key
    macro_year, macro_company, macro_account = macro_key
    if macro_account and row_account != macro_account:
        return False
    if macro_company and row_company != macro_company:
        return False
    if macro_year and row_year != macro_year:
        return False
    return True


def _macro_key_part(value: Any) -> str:
    text = _string_value(value)
    if not text:
        return ""
    try:
        numeric = float(text)
    except ValueError:
        return text
    if numeric.is_integer():
        return str(int(numeric))
    return text


def _macro_context_scoring_effect(finding: dict[str, Any]) -> str:
    bucket = str(finding.get("queue_bucket") or "")
    if bucket.startswith("confirmed_"):
        return "priority_booster"
    if bucket.startswith("corroborated_"):
        return "weak_priority_booster"
    return "context_only"


def _apply_macro_context_priority(
    priority_score: float,
    macro_contexts: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons: list[str] = []
    for context in macro_contexts:
        effect = str(context.get("scoring_effect") or "")
        if effect == "priority_booster":
            increment = 0.06
        elif effect == "weak_priority_booster":
            increment = 0.04
        else:
            continue
        bonus += increment
        reasons.append(
            "macro_context="
            f"{context.get('rule_id')}:{context.get('queue_bucket')}+{increment:.2f}"
        )
    if not bonus:
        return priority_score, []
    return min(priority_score + min(bonus, 0.10), 1.0), reasons


def _macro_context_tags(macro_contexts: list[dict[str, Any]]) -> set[str]:
    tags: set[str] = set()
    for context in macro_contexts:
        rule_id = str(context.get("rule_id") or "").lower()
        bucket = str(context.get("queue_bucket") or "").lower()
        if rule_id:
            tags.add(f"{rule_id}_macro_context")
        if bucket:
            tags.add(bucket)
    return tags


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
    if theme_id == "access_scope_review":
        return {
            "created_by": _string_value(row.get("created_by")) or "UNKNOWN_USER",
            "user_persona": _string_value(row.get("user_persona")) or "UNKNOWN_PERSONA",
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
    df: pd.DataFrame,
    hits: list[_RawHit],
    config: dict[str, Any],
) -> list[CaseDocumentRef]:
    by_doc: dict[str, list[_RawHit]] = defaultdict(list)
    for hit in hits:
        by_doc[hit.document_id].append(hit)
    refs: list[CaseDocumentRef] = []
    for document_id, doc_hits in by_doc.items():
        hit_positions = [hit.row_index for hit in doc_hits]
        row = df.iloc[hit_positions].iloc[0]
        refs.append(
            CaseDocumentRef(
                document_id=document_id,
                posting_date=_date_string(row.get("posting_date")),
                created_by=_optional_string(row.get("created_by")),
                business_process=_optional_string(row.get("business_process")),
                gl_account=_optional_string(row.get("gl_account")),
                counterparty=_counterparty(row, config),
                amount=_document_amount(df, document_id, hit_positions),
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
        totals[hit.evidence_type] += hit.normalized_score

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
    duplicate_or_outflow_score: float,
    logic_score: float,
    timing_score: float,
    behavior_score: float,
    config: dict[str, Any],
) -> float:
    weights = config.get("priority_weights", {})
    return (
        float(weights.get("control", 0.25)) * control_score
        + float(weights.get("amount", 0.25)) * amount_score
        + float(weights.get("outflow", 0.15)) * duplicate_or_outflow_score
        + float(weights.get("logic", 0.15)) * logic_score
        + float(weights.get("timing", 0.10)) * timing_score
        + float(weights.get("behavior", 0.10)) * behavior_score
    )


def _amount_score(total_amount: float, max_amount: float, config: dict[str, Any]) -> float:
    relative_score = min(total_amount / (max_amount or 1.0), 1.0)
    materiality_amount = float(config.get("materiality_amount", 0.0) or 0.0)
    if materiality_amount <= 0:
        return relative_score
    materiality_score = min(total_amount / materiality_amount, 1.0)
    return max(relative_score, materiality_score)


def _apply_priority_floors(
    *,
    case_hits: list[_RawHit],
    priority_score: float,
    config: dict[str, Any],
) -> tuple[float, list[str]]:
    floors = config.get("priority_floors", [])
    if not isinstance(floors, list) or not floors:
        return priority_score, []

    adjusted = float(priority_score)
    reasons: list[str] = []
    for floor in floors:
        if not isinstance(floor, dict):
            continue
        rule_id = str(floor.get("rule_id", "")).strip()
        if not rule_id:
            continue
        labels = {
            str(label).strip().lower()
            for label in floor.get("labels", [])
            if str(label).strip()
        }
        min_raw_score = floor.get("min_raw_score")
        matched = False
        for hit in case_hits:
            if hit.rule_id != rule_id:
                continue
            label = str(hit.display_label or "").strip().lower()
            label_match = not labels or label in labels
            score_match = min_raw_score is None or hit.score >= float(min_raw_score)
            field_match = _priority_floor_missing_field_match(hit, floor)
            corroboration_match = _priority_floor_corroboration_match(case_hits, floor)
            if label_match and score_match and field_match and corroboration_match:
                matched = True
                break
        if not matched:
            continue
        floor_score = float(floor.get("min_priority_score", adjusted))
        if floor_score > adjusted:
            adjusted = floor_score
        reason = str(floor.get("reason") or f"priority_floor:{rule_id}")
        reasons.append(reason)
    return max(0.0, min(adjusted, 1.0)), reasons


def _priority_floor_corroboration_match(
    case_hits: list[_RawHit],
    floor: dict[str, Any],
) -> bool:
    required_rules = {
        str(rule_id).strip()
        for rule_id in floor.get("required_rules", [])
        if str(rule_id).strip()
    }
    if not required_rules:
        return True

    hit_rules = {hit.rule_id for hit in case_hits}
    match_mode = str(floor.get("required_rules_match", "all")).strip().lower()
    if match_mode == "any":
        return bool(required_rules & hit_rules)
    return required_rules.issubset(hit_rules)


def _priority_floor_missing_field_match(hit: _RawHit, floor: dict[str, Any]) -> bool:
    field_conditions = (
        "missing_fields" in floor
        or "min_missing_count" in floor
        or "min_matching_missing_fields" in floor
    )
    if not field_conditions:
        return True

    missing_fields = _hit_missing_fields(hit)
    if not missing_fields:
        return False

    configured_fields = {
        str(field).strip()
        for field in floor.get("missing_fields", [])
        if str(field).strip()
    }
    if configured_fields:
        matching_count = len(missing_fields & configured_fields)
        match_mode = str(floor.get("missing_fields_match", "any")).strip().lower()
        if match_mode == "all":
            if not configured_fields.issubset(missing_fields):
                return False
        elif matching_count == 0:
            return False
    else:
        matching_count = len(missing_fields)

    min_missing_count = floor.get("min_missing_count")
    if min_missing_count is not None and len(missing_fields) < int(min_missing_count):
        return False

    min_matching = floor.get("min_matching_missing_fields")
    if min_matching is not None and matching_count < int(min_matching):
        return False

    return True


def _hit_missing_fields(hit: _RawHit) -> set[str]:
    annotation = hit.annotation or {}
    raw_fields = annotation.get("missing_fields")
    if isinstance(raw_fields, str):
        return {field.strip() for field in raw_fields.split(",") if field.strip()}
    if isinstance(raw_fields, (list, tuple, set)):
        return {str(field).strip() for field in raw_fields if str(field).strip()}
    return set()


def _apply_priority_adjustments(
    *,
    rows: pd.DataFrame,
    case_hits: list[_RawHit],
    evidence_types: list[str],
    amount_score: float,
    total_amount: float,
    priority_score: float,
    behavior_score: float,
    config: dict[str, Any],
) -> tuple[float, float, list[str], dict[str, float]]:
    adjustments = config.get("priority_adjustments", {})
    bonuses = {
        "topside_bonus": 0.0,
        "batch_combo_bonus": 0.0,
        "weak_evidence_bonus": 0.0,
        "l301_priority_bonus": 0.0,
        "l203_duplicate_bonus": 0.0,
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

    l108_bonus, l108_reasons = _l108_priority_adjustment(
        case_hits=case_hits,
        config=adjustments.get("l108_context_priority", {}),
    )
    if l108_bonus > 0:
        adjusted_priority += l108_bonus
        reasons.extend(l108_reasons)

    duplicate_entry_cfg = dict(adjustments.get("duplicate_entry", {}))
    duplicate_entry_cfg["_phase1_materiality_amount"] = config.get("materiality_amount", 0.0)
    l203_bonus, l203_floor, l203_reasons = _l203_priority_adjustment(
        case_hits=case_hits,
        evidence_types=evidence_types,
        amount_score=amount_score,
        total_amount=total_amount,
        config=duplicate_entry_cfg,
    )
    if l203_floor is not None:
        if adjusted_priority + l203_bonus < l203_floor:
            adjusted_priority = l203_floor
        elif l203_bonus > 0:
            bonuses["l203_duplicate_bonus"] = l203_bonus
    elif l203_bonus > 0:
        bonuses["l203_duplicate_bonus"] = l203_bonus
    reasons.extend(l203_reasons)

    rare_pair_cfg = adjustments.get("rare_account_pair", {})
    if rare_pair_cfg.get("enabled", True) and "L4-04" in rule_ids:
        non_l404_rules = rule_ids - {"L4-04"}
        if not non_l404_rules:
            penalty = float(rare_pair_cfg.get("l404_only_penalty", 0.10))
            adjusted_priority -= penalty
            reasons.append(f"l404_only_penalty=-{penalty:.2f}")

        recurring_ratio = _case_source_ratio(
            rows,
            rare_pair_cfg.get("recurring_sources", ["recurring", "automated", "batch", "interface", "system"]),
        )
        recurring_threshold = float(rare_pair_cfg.get("recurring_source_ratio", 0.60))
        if recurring_ratio >= recurring_threshold:
            penalty = float(rare_pair_cfg.get("recurring_source_penalty", 0.08))
            adjusted_priority -= penalty
            reasons.append(f"l404_recurring_source_penalty=-{penalty:.2f}")

    _l301_priority, l301_bonus, l301_reasons = _l301_priority_adjustment(
        rows=rows,
        rule_ids=rule_ids,
        priority_score=adjusted_priority,
        config=adjustments.get("l301_context_priority", {}),
    )
    if l301_bonus > 0:
        bonuses["l301_priority_bonus"] = l301_bonus
        reasons.extend(l301_reasons)

    adjusted_priority += sum(bonuses.values())
    return max(0.0, min(adjusted_priority, 1.0)), adjusted_behavior, reasons, bonuses


def _l203_priority_adjustment(
    *,
    case_hits: list[_RawHit],
    evidence_types: list[str],
    amount_score: float,
    total_amount: float,
    config: dict[str, Any],
) -> tuple[float, float | None, list[str]]:
    """Elevate only corroborated high-confidence duplicate-entry candidates."""

    if config.get("enabled", True) is False:
        return 0.0, None, []

    l203_hits = [
        hit
        for hit in case_hits
        if hit.rule_id in {"L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d"}
    ]
    if not l203_hits:
        return 0.0, None, []

    high_confidence_score = float(config.get("high_confidence_score", 0.85))
    has_high_confidence = any(
        hit.score >= high_confidence_score
        or str((hit.annotation or {}).get("confidence_band", "")).strip().lower() == "high"
        or _annotation_confidence(hit.annotation) >= high_confidence_score
        for hit in l203_hits
    )
    if not has_high_confidence:
        return 0.0, None, []

    corroborating_evidence = set(
        config.get(
            "corroborating_evidence_types",
            [
                "control_failure",
                "timing_anomaly",
                "logic_mismatch",
                "statistical_outlier",
                "data_integrity_failure",
                "access_scope_review",
                "intercompany_structure",
            ],
        )
    )
    has_independent_signal = bool(set(evidence_types) & corroborating_evidence)

    materiality_amount = float(config.get("materiality_amount", 0.0) or 0.0)
    if materiality_amount <= 0:
        materiality_amount = float(config.get("_phase1_materiality_amount", 0.0) or 0.0)
    min_total_amount = float(config.get("min_total_amount", 0.0) or 0.0)
    amount_threshold = float(config.get("amount_score_threshold", 0.75))
    has_amount_support = (
        amount_score >= amount_threshold
        and (
            (materiality_amount > 0 and total_amount >= materiality_amount * amount_threshold)
            or (min_total_amount > 0 and total_amount >= min_total_amount)
        )
    )

    if not (has_independent_signal or has_amount_support):
        return 0.0, None, []

    bonus = float(config.get("bonus", 0.08))
    floor = float(config.get("min_priority_score", 0.45))
    reason = (
        "l203_high_confidence_corroborated"
        if has_independent_signal
        else "l203_high_confidence_material"
    )
    return bonus, floor, [reason]


def _l108_priority_adjustment(
    *,
    case_hits: list[_RawHit],
    config: dict[str, Any],
) -> tuple[float, list[str]]:
    """Raise L1-08 case priority when the Boolean hit has corroborating context."""

    if config.get("enabled", True) is False:
        return 0.0, []

    l108_hits = [hit for hit in case_hits if hit.rule_id == "L1-08"]
    if not l108_hits:
        return 0.0, []

    context_reasons: set[str] = set()
    for hit in l108_hits:
        annotation = hit.annotation or {}
        raw_reasons = annotation.get("context_reasons", [])
        if isinstance(raw_reasons, str):
            context_reasons.update(part.strip() for part in raw_reasons.split(",") if part.strip())
        elif isinstance(raw_reasons, (list, tuple, set)):
            context_reasons.update(str(reason).strip() for reason in raw_reasons if str(reason).strip())

    if not context_reasons:
        return 0.0, []

    per_context_bonus = float(config.get("per_context_bonus", 0.03))
    max_bonus = float(config.get("max_bonus", 0.12))
    bonus = min(len(context_reasons) * per_context_bonus, max_bonus)
    return bonus, ["l108_context=" + ",".join(sorted(context_reasons))]


def _l301_priority_adjustment(
    *,
    rows: pd.DataFrame,
    rule_ids: set[str],
    priority_score: float,
    config: dict[str, Any],
) -> tuple[float, float, list[str]]:
    """Raise L3-01 review queue priority only when corroborating context exists."""

    if "L3-01" not in rule_ids or config.get("enabled", True) is False:
        return priority_score, 0.0, []

    tags = _l301_context_tags(rows, rule_ids, config)
    if not tags:
        return priority_score, 0.0, ["l301_raw_population_only"]

    tag_bonus = {
        "manual_entry": float(config.get("manual_bonus", 0.12)),
        "high_amount": float(config.get("high_amount_bonus", 0.12)),
        "period_end": float(config.get("period_end_bonus", 0.10)),
        "approval_issue": float(config.get("approval_issue_bonus", 0.18)),
        "abnormal_time": float(config.get("abnormal_time_bonus", 0.08)),
        "intercompany": float(config.get("intercompany_bonus", 0.14)),
        "repeat_pattern": float(config.get("repeat_pattern_bonus", 0.12)),
        "logic_combo": float(config.get("logic_combo_bonus", 0.08)),
    }
    raw_bonus = sum(tag_bonus.get(tag, 0.0) for tag in tags)
    adjusted = float(priority_score)

    if "manual_entry" in tags:
        adjusted = max(adjusted, float(config.get("manual_floor", 0.75)))
    if "high_amount" in tags or "period_end" in tags:
        adjusted = max(adjusted, float(config.get("amount_or_period_floor", 0.80)))
    if {"high_amount", "period_end"}.issubset(tags):
        adjusted = max(adjusted, float(config.get("amount_and_period_floor", 0.85)))
    if {"approval_issue", "intercompany", "repeat_pattern"} & set(tags):
        adjusted = max(adjusted, float(config.get("strong_context_floor", 0.90)))
    if len(tags) >= int(config.get("critical_context_count", 3)):
        adjusted = max(adjusted, float(config.get("critical_context_floor", 0.95)))

    floor_delta = max(0.0, adjusted - float(priority_score))
    bonus = min(
        max(raw_bonus, floor_delta),
        float(config.get("max_bonus", 0.70)),
    )
    return priority_score, bonus, ["l301_context=" + ",".join(tags)]


def _l301_context_tags(
    rows: pd.DataFrame,
    rule_ids: set[str],
    config: dict[str, Any],
) -> list[str]:
    tags: list[str] = []
    if _case_has_true(rows, "is_manual_je") or _case_source_ratio(
        rows,
        config.get("manual_sources", ["manual", "adjustment"]),
    ) > 0:
        tags.append("manual_entry")

    if _case_has_high_amount(rows, config):
        tags.append("high_amount")

    if _case_has_true(rows, "is_period_end") or "L3-04" in rule_ids:
        tags.append("period_end")

    if rule_ids & set(config.get("approval_rules", ["L1-04", "L1-05", "L1-07", "L1-09"])):
        tags.append("approval_issue")

    if rule_ids & set(config.get("abnormal_time_rules", ["L3-05", "L3-06", "L4-05"])):
        tags.append("abnormal_time")

    if (
        rule_ids & set(config.get("intercompany_rules", ["L3-03", "IC01", "IC02", "IC03"]))
    ) or _case_has_true(rows, "is_intercompany"):
        tags.append("intercompany")

    if _case_has_repeat_context(rows, config):
        tags.append("repeat_pattern")

    if rule_ids & set(config.get("logic_combo_rules", ["L2-04", "L3-10", "L4-04"])):
        tags.append("logic_combo")

    return sorted(set(tags))


def _case_has_high_amount(rows: pd.DataFrame, config: dict[str, Any]) -> bool:
    if rows.empty:
        return False
    amount_threshold = float(config.get("high_amount_threshold", 100_000_000.0) or 0.0)
    if amount_threshold > 0:
        return any(_line_amount(row) >= amount_threshold for _, row in rows.iterrows())
    quantile = float(config.get("high_amount_quantile", 0.90))
    amounts = rows.apply(_line_amount, axis=1)
    if amounts.empty:
        return False
    threshold = float(amounts.quantile(quantile))
    return bool((amounts >= threshold).any() and amounts.max() > 0)


def _case_has_repeat_context(rows: pd.DataFrame, config: dict[str, Any]) -> bool:
    if len(rows) < int(config.get("repeat_min_rows", 3)):
        return False
    group_cols = [
        col
        for col in config.get("repeat_group_columns", ["business_process", "gl_account", "created_by"])
        if col in rows.columns
    ]
    if not group_cols:
        return False
    min_count = int(config.get("repeat_min_count", 3))
    return bool(rows.groupby(group_cols, dropna=False).size().ge(min_count).any())


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

    if (
        config.get("include_l3_08_as_weak_description", True)
        and "L3-08" in rule_ids
        and _l308_has_corroborating_rule(rule_ids, config)
    ):
        tags.append("missing_or_corrupted_description")

    if (
        config.get("derive_manual_period_end", True)
        and _case_has_true(rows, "is_manual_je")
        and (_case_has_true(rows, "is_period_end") or "L3-04" in rule_ids)
    ):
        tags.append("manual_period_end")

    return sorted(set(tags))


def _l308_has_corroborating_rule(rule_ids: set[str], config: dict[str, Any]) -> bool:
    """Allow L3-08 weak-description bonus only with an independent review signal."""

    default_rules = {
        "L1-03",
        "L1-05",
        "L1-07",
        "L1-09",
        "L2-02",
        "L2-03",
        "L2-05",
        "L3-02",
        "L3-04",
        "L3-05",
        "L3-06",
        "L3-07",
        "L3-09",
        "L3-10",
        "L3-11",
        "L4-03",
        "L4-04",
        "L4-05",
        "L4-06",
    }
    configured = config.get("l3_08_corroborating_rules")
    if configured is None:
        corroborating_rules = default_rules
    else:
        corroborating_rules = {
            str(rule_id).strip()
            for rule_id in configured
            if str(rule_id).strip()
        }
    return bool((set(rule_ids) - {"L3-08"}) & corroborating_rules)


def _case_has_true(rows: pd.DataFrame, column: str) -> bool:
    if column not in rows.columns:
        return False
    return bool(rows[column].fillna(False).astype(bool).any())


def _case_source_ratio(rows: pd.DataFrame, source_values: list[str]) -> float:
    if "source" not in rows.columns or rows.empty:
        return 0.0
    normalized = rows["source"].fillna("").astype(str).str.strip().str.lower()
    source_set = {str(value).strip().lower() for value in source_values if str(value).strip()}
    if not source_set:
        return 0.0
    return float(normalized.isin(source_set).mean())


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
    rows = df.iloc[sorted(indices)]
    return float(rows.apply(_line_amount, axis=1).sum())


def _document_amount(df: pd.DataFrame, document_id: str, hit_positions: list[int]) -> float:
    rows = df.iloc[hit_positions]
    if document_id and "document_id" in df.columns:
        document_ids = df["document_id"].fillna("").astype(str).str.strip()
        document_rows = df[document_ids == document_id]
        if not document_rows.empty:
            rows = document_rows
    return float(rows.apply(_line_amount, axis=1).sum())


def _lookup_row_annotation(
    rule_annotations: dict[Any, Any],
    row_label: Any,
    row_pos: int,
) -> dict[str, Any] | None:
    if not isinstance(rule_annotations, dict):
        return None
    keys: list[Any] = [row_label, row_pos, str(row_label), str(row_pos)]
    try:
        keys.append(int(row_label))
    except (TypeError, ValueError):
        pass
    for key in keys:
        value = rule_annotations.get(key)
        if isinstance(value, dict):
            return value
    return None


def _row_display_label(row_annotation: dict[str, Any] | None) -> str | None:
    if not isinstance(row_annotation, dict):
        return None
    for key in (
        "reason_code",
        "risk_level",
        "finding_severity",
        "severity_label",
        "signal_strength",
        "signal_category",
        "bucket",
        "queue_label",
        "label",
    ):
        value = row_annotation.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _annotation_score(row_annotation: dict[str, Any] | None) -> float:
    if not isinstance(row_annotation, dict):
        return 0.0
    for key in ("score", "review_score", "normalized_score"):
        try:
            score = float(row_annotation.get(key))
        except (TypeError, ValueError):
            continue
        if score > 0:
            return score
    return 0.0


def _annotation_confidence(row_annotation: dict[str, Any] | None) -> float:
    if not isinstance(row_annotation, dict):
        return 0.0
    try:
        return float(row_annotation.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
    if primary_evidence == "access_scope_review":
        return _access_scope_explanation(rule_ids, total_amount)
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
    if hit.evidence_strength in _STRENGTH_RANK:
        return hit.evidence_strength
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
        "display_label": hit.display_label,
        "signal_strength": hit.signal_strength,
        "normalized_score": hit.normalized_score,
        "scoring_role": hit.scoring_role,
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
    if primary_evidence == "access_scope_review":
        return _access_scope_explanation(rule_ids, total_amount)
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


def _access_scope_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _LOGIC_RULES) or ["Work scope concentration"]
    lead = " + ".join(labels[:3])
    if total_amount > 0:
        return (
            f"{lead} signal was observed and related entry amount totals {total_amount:,.0f}. "
            "L1-06 handles explicit SoD violations; this case should review one user's broad current-period activity and compensating controls."
        )
    return (
        f"{lead} signal was observed. L1-06 handles explicit SoD violations; "
        "this case should review one user's broad current-period activity and compensating controls."
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
