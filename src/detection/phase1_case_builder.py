"""Build case-centric Phase 1 results from raw detection outputs."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import PROJECT_ROOT, AuditSettings
from src.detection.base import DetectionResult
from src.detection.boolean_utils import bool_column, coerce_bool_value
from src.detection.constants import SEVERITY_MAP, TOPSIDE_BONUS_RULES
from src.detection.phase1_rule_catalog import (
    EVIDENCE_QUEUE_MAP as _EVIDENCE_QUEUE_MAP,
)
from src.detection.phase1_rule_catalog import (
    ISSUE_QUEUE_LABELS as _ISSUE_QUEUE_LABELS,
)
from src.detection.phase1_rule_catalog import (
    LEGACY_THEME_TOPIC_MAP as _LEGACY_THEME_TOPIC_MAP,
)
from src.detection.phase1_rule_catalog import (
    RULE_QUEUE_MAP as _RULE_QUEUE_MAP,
)
from src.detection.phase1_rule_catalog import (
    RULE_THEME_MAP as _RULE_THEME_MAP,
)
from src.detection.phase1_rule_catalog import (
    THEME_QUEUE_MAP as _THEME_QUEUE_MAP,
)
from src.detection.phase1_rule_catalog import (
    TOPIC_LEGACY_THEME_MAP as _TOPIC_LEGACY_THEME_MAP,
)
from src.detection.rule_detail_metadata import (
    PresenterSurface,
    canonicalize_rule_id,
    get_rule_detail_metadata,
)
from src.detection.rule_scoring import (
    OFF_TIME_SET,
    RULE_SCORING_REGISTRY,
    TOPIC_REGISTRY,
    normalize_rule_evidence,
)
from src.detection.source_trust import trusted_automated_mask
from src.detection.topic_scoring import (
    TIER_RANK,
    case_tier,
    compute_fraud_scenario_tags,
    compute_topic_scores,
    compute_topic_tiers,
    pick_primary_topic,
)
from src.models.phase1_case import (
    CaseDocumentRef,
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
    ThemeSummary,
)
from src.models.phase1_unit import DocumentUnit, FlowUnit, Phase1Unit
from src.services.phase2_ref_canonical import canonicalize_ref_key
from src.services.phase2_ref_pseudonymize import hash_ref_key

SCHEMA_VERSION = "1.0.0"

# OFF-TIME 룰별 시점심각도(뱃지/UI 표시 전용) 가중치. OFF_TIME_SET(rule_scoring 단일 출처)과
# 키가 반드시 일치해야 한다 — 아래 모듈 가드가 import 시 드리프트를 차단한다. tier 게이트·점수
# 병합·within-tier 정렬에 미참여(현행 _tier_sort_score 미포함, 정렬 반영은 PHASE1-2 구현 예정).
# 대시보드 "시점심각도" 컬럼 표시용. high(2): L3-05 주말·L4-05 작성자집중 / med(1): L3-06 심야.
# 근거 SoT: HIGH_COMBO_GROUNDING §2(5), PHASE1_TIER_SCORING_SPEC §4.
_TIME_SEVERITY_WEIGHTS: dict[str, int] = {"L3-05": 2, "L4-05": 2, "L3-06": 1}
assert set(_TIME_SEVERITY_WEIGHTS) == set(OFF_TIME_SET), (
    "_TIME_SEVERITY_WEIGHTS 키가 OFF_TIME_SET 과 어긋남 — OFF-TIME 멤버 변경 시 동기화 필요"
)


def compute_time_severity_score(fired_rule_ids: set[str]) -> int:
    """case가 발화한 룰ID 집합으로 OFF-TIME 보조축 점수를 계산한다.

    합산(상한 없음). 금액·시각 임계·연도 리터럴 미사용 — 룰ID 발화 여부만 본다.
    """
    return sum(
        weight for rule_id, weight in _TIME_SEVERITY_WEIGHTS.items() if rule_id in fired_rule_ids
    )


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

_FAST_CASE_KEY_THEMES = {
    "control_failure",
    "access_scope_review",
    "timing_anomaly",
    "duplicate_or_outflow",
    "intercompany_structure",
    "statistical_outlier",
    "logic_mismatch",
}

_STRONG_TRIAGE_RULES = {
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L1-07-02",
    "L2-02",
    "L2-03",
    "L2-05",
    "L3-02",
    "L3-04",
    "L4-01",
    "L4-03",
}

_STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1}

# GR01/GR03 제거 (2026-06-14): graph 는 PHASE2 family 영역. macro finding 은 L4-02·D01·D02 만.
_MACRO_FINDING_RULES = {"L4-02", "D01", "D02"}

# 데이터 정합성 트랙 (2026-06-15 결정): 차대불일치·필수필드·무효계정은 부정 위험이 아니라
# 데이터 품질 문제다. 위험 큐(topic/tier/priority)에서 분리해 별도 트랙으로만 보여준다.
# macro 와 동일하게 case_hits 에서 제외 → topic·tier·priority 기여 0. 별도 수집은
# _build_data_integrity_findings 가 raw 탐지 결과에서 직접 한다. L1-08(기간불일치)은 위험 큐 잔류.
_DATA_INTEGRITY_TRACK_RULES = {"L1-01", "L1-02", "L1-03"}
_DUAL_INTEGRITY_TRACK_RULES = {"L1-08"}

_DOCUMENT_UNIT_RULES = {
    "L1-01",
    "L1-02",
    "L1-03",
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L1-08",
    "L1-07-02",
    "L2-01",
    "L2-04",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L3-09",
    "L3-10",
    "L3-11",
    "L4-01",
    "L4-03",
    "L4-04",
}

# IC01-03·GR01/03 (PHASE1-2 family) 는 2026-06-30 완전 삭제 — flow/transaction unit case 미생성.
_FLOW_UNIT_RULES = {"L2-02", "L2-03", "L2-05"}
# transaction case 생성에서 제외하는 룰(각 사유 상이):
# L4-02·D01·D02=macro finding, L3-12=사용자 업무범위, L4-06=배치 모집단, L4-05=OFF-TIME 작성자 집계.
_REVIEW_POPULATION_RULES = {
    "L4-02",
    "D01",
    "D02",
    "L3-12",
    "L4-05",
    "L4-06",
}

_FLOW_ID_SCHEMA_VERSION = "p1_flow_v1"
_DUPLICATE_DETAIL_RULE_IDS = ("L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d", "L2-03e")
_REVERSAL_REFERENCE_COLUMNS = (
    "reversal_document_id",
    "original_document_id",
    "reversed_document_id",
    "reverse_document_id",
)
_FLOW_SETTINGS = AuditSettings()

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
    "L1-07-02": {
        "evidence_strength": "medium",
        "focus": "unknown_approver",
        "action": [
            "승인자가 직원 마스터에 존재하는지 확인",
            "승인자 값의 출처와 우회 입력 여부 확인",
        ],
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
    "L3-09": {
        "evidence_strength": "medium",
        "focus": "suspense_account_linger",
        "action": ["가계정 정리 계획 확인", "장기 미정리 사유와 후속 정리 전표 확인"],
    },
    "L3-10": {
        "evidence_strength": "weak",
        "focus": "estimate_account_use",
        "action": ["추정계정 사용 사유 확인", "추정 근거·증빙과 결산시점 대사"],
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
        "action": [
            "계정/월 모집단의 숫자 분포 이상 원인 확인",
            "해당 모집단의 표본 전표 추가 검토",
        ],
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
    "L1-07-02": "유령 승인자",
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
    "L3-12": "권한·업무 범위 집중",
    "L3-10": "추정계정 사용",
    "L1-03": "무효 계정",
    "L2-04": "비용 자산화 의심",
    "L3-09": "가수금 장기체류",
    "L4-04": "희소 차대 계정쌍",
}

_TIMING_RULES = {
    "L3-04": "기말 집중",
    "L3-05": "주말 전기",
    "L3-06": "심야 전기",
    "L3-07": "전기일-문서일 장기 괴리",
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
}


@dataclass
class _RawHit:
    rule_id: str
    requested_rule_id: str
    canonical_rule_id: str
    theme_id: str
    topic_id: str
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
    can_seed_case: bool = True
    secondary_topics: tuple[str, ...] = ()
    standalone_rankable: bool = True
    floor_policy_ids: tuple[str, ...] = ()
    combo_policy_ids: tuple[str, ...] = ()
    fraud_scenario_tags: tuple[str, ...] = ()


@dataclass
class _UnitScoreProjection:
    priority_score: float = 0.0
    base_priority_score: float = 0.0
    composite_sort_score: float = 0.0
    composite_sort_score_components: dict[str, float] | None = None
    topic_scores: dict[str, float] | None = None
    topic_score_breakdown: dict[str, dict[str, Any]] | None = None
    priority_band: str = "low"
    triage_rank_score: float = 0.0
    triage_rank_reasons: list[str] | None = None


@dataclass
class _AuditEvidenceContext:
    posting_months: list[str]
    manual_context: list[bool]
    support_gap: list[bool]
    approval_gap: list[bool]
    post_close_gap: list[bool]
    related_party_context: list[bool]
    reversal_context: list[bool]
    partner_value: list[bool]
    master_counterparty_inactive: list[bool]
    master_counterparty_known: list[bool]
    document_flow_orphan: list[bool]
    ic_matched_pair_found: list[bool]
    ic_unmatched_reference: list[bool]
    approval_matrix_gap: list[bool]
    approval_limit_exceeded_independent: list[bool]
    trusted_automated: list[bool]


def _fraud_combo_rule_scope(hits, audit_context: _AuditEvidenceContext) -> set[str]:
    """fraud combo 트리거로 인정할 룰 — 신뢰 자동 행에서만 발화한 룰은 제외.

    Why: 자동 결산 배치 전표는 승인 부재·결산기 집중이 정상이라 사람 행위 전제의
         fraud combo를 구성할 수 없다. 위장 의심(단독 자동) 행은 신뢰하지 않으므로
         그 발화는 콤보 트리거로 유지된다 (OPEN_ISSUES #14·#16).
    """
    trusted = audit_context.trusted_automated
    size = len(trusted)
    scope: set[str] = set()
    for hit in hits:
        position = getattr(hit, "row_index", None)
        try:
            pos = int(position) if position is not None else -1
        except (TypeError, ValueError):
            pos = -1
        on_trusted = 0 <= pos < size and trusted[pos]
        if not on_trusted:
            scope.add(str(getattr(hit, "rule_id", "")))
    scope.discard("")
    return scope


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
    engagement_salt: str = "",
    settings: Any = None,
) -> Phase1CaseResult:
    # Why: ``engagement_salt`` 는 S6.next Phase 1 (옵션 C) — RawRuleHitRef 의
    # canonical_label_hash / doc_id_hash 산출 시 PHASE2 store 와 동일 salt 를
    # 그대로 사용한다. 기본값 "" 일 때 신규 hash 필드는 모두 빈 값으로 남고
    # (invariant #71), salt 가 명시되면 동일 row position 의 PHASE2 row_ref_map
    # hash 와 동일한 값이 PHASE1 산출물 자체에 채워진다 (invariant #70).
    import time as _time

    _build_t0 = _time.perf_counter()
    generated_at = generated_at or datetime.now(UTC)
    config = (phase1_case_config or {}).get("phase1_case", {})
    # PHASE1-2 거래처 배지(첫등장/희소/휴면재활성) — df 전체 1회 계산, case/unit 에 positional 집계.
    # settings 부재 시 배지 계산 스킵(None) — 실제 파이프라인은 ctx.settings 를 명시 전달한다.
    # 전역 get_settings() 를 여기서 호출하지 않는다(lru_cache 싱글톤을 monkeypatch 한 테스트가
    # Mock 속성을 흘려 float() 크래시 유발하는 오염 벡터 회피). 점수 비병합(배지 전용).
    partner_row_badges: pd.DataFrame | None = None
    if settings is not None:
        from src.detection.partner_signals import compute_partner_signals

        partner_row_badges = compute_partner_signals(df, settings).row_badges
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
    data_integrity_findings = _build_data_integrity_findings(results)
    import os as _os_dbg

    _dbg = bool(_os_dbg.environ.get("PHASE1_BUILD_STAGE_TIMING"))

    def _stage(name: str, t0: float) -> float:
        if _dbg:
            print(f"[stage] {name}: {_time.perf_counter() - t0:.2f}s", flush=True)
        return _time.perf_counter()

    _st = _time.perf_counter()
    raw_hits = _collect_raw_hits(df, results)
    _st = _stage("collect_raw_hits", _st)
    flow_units = _build_flow_units(
        df,
        results,
        engagement_salt=engagement_salt,
    )
    _st = _stage("build_flow_units", _st)
    flow_member_document_ids = _measurement_eligible_flow_member_document_ids(flow_units)
    document_units = _build_document_units(
        raw_hits,
        df=df,
        absorbed_document_ids=flow_member_document_ids,
        engagement_salt=engagement_salt,
    )
    _st = _stage("build_document_units", _st)
    flow_units = _absorb_document_hits_into_flow_units(
        raw_hits,
        flow_units,
        df,
        engagement_salt=engagement_salt,
    )
    _st = _stage("absorb_document_hits", _st)
    units = [*document_units, *flow_units]
    units = _score_phase1_units(
        units,
        raw_hits,
        df,
        config,
        partner_row_badges=partner_row_badges,
    )
    _st = _stage("score_phase1_units", _st)
    cases = _build_cases(
        df,
        raw_hits,
        config,
        macro_findings,
        engagement_salt=engagement_salt,
        partner_row_badges=partner_row_badges,
    )
    _st = _stage("build_cases", _st)
    cases = _derive_case_scores_from_units(cases, units, config)
    _st = _stage("derive_case_scores", _st)
    theme_summaries = _build_theme_summaries(cases, int(config.get("top_n_per_theme", 10)))
    # Why: PHASE1 빌드 + 탐지기 실행 시간 합산. 탐지기별 metadata["elapsed"] 합 + 빌드 시간.
    detector_elapsed = 0.0
    for result in results:
        meta = getattr(result, "metadata", {}) or {}
        try:
            detector_elapsed += float(meta.get("elapsed", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
    build_elapsed = _time.perf_counter() - _build_t0
    elapsed_seconds = detector_elapsed + build_elapsed
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
        units=units,
        raw_rule_reference={
            "source": "detection_results",
            "track_names": [result.track_name for result in results],
        },
        metadata={
            "phase1_case_config_version": SCHEMA_VERSION,
            "score_cutoff": {
                "high": float(config.get("priority_band", {}).get("high", 0.90)),
                "medium": float(config.get("priority_band", {}).get("medium", 0.75)),
            },
            "grouping_window": {
                "near_period_days": int(config.get("near_period_days", 7)),
                "period_end_window_days": int(config.get("period_end_window_days", 5)),
            },
            "macro_findings": macro_findings,
            "macro_finding_count": len(macro_findings),
            "macro_finding_policy": (
                "L4-02/D01/D02 are Account/Process Queue findings. They do not create "
                "transaction queue priority_score or row-level anomaly_score by themselves."
            ),
            "data_integrity_findings": data_integrity_findings,
            "data_integrity_finding_count": sum(
                int(item.get("flagged_row_count", 0)) for item in data_integrity_findings
            ),
            "data_integrity_policy": (
                "L1-01/L1-02/L1-03 are data-quality checks shown in a separate data-integrity "
                "track. They do not contribute to risk topic/tier/priority (HIGH/MEDIUM/LOW)."
            ),
            "elapsed_seconds": float(elapsed_seconds),
            "detector_elapsed_seconds": float(detector_elapsed),
            "build_elapsed_seconds": float(build_elapsed),
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
        result.metadata["phase1_macro_finding_count"] = reference["phase1_macro_finding_count"]
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
        # GR macro finding 제거 (2026-06-14): graph(GR01/03)는 PHASE2 family.

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


_DATA_INTEGRITY_RULE_LABELS: dict[str, str] = {
    "L1-01": "차대변 불일치",
    "L1-02": "필수필드 누락",
    "L1-03": "무효 계정",
    "L1-08": "회계기간 불일치(데이터 품질)",
}


def _build_data_integrity_findings(
    results: list[DetectionResult],
) -> list[dict[str, Any]]:
    """데이터 정합성 트랙(L1-01/L1-02/L1-03) 별도 수집.

    이 룰들은 부정 위험이 아니라 데이터 품질 문제라 위험 큐(topic/tier/priority)에서
    제외(_DATA_INTEGRITY_TRACK_RULES)된다. 여기서는 raw 탐지 결과에서 룰별 발화 건수만
    집계해 별도 트랙으로 표시하게 한다(위험 점수 기여 없음). 표시는 룰별 기존 화면 사용.
    L1-08은 dual 트랙: 정합성 finding은 raw mismatch를 집계하고 부정 큐에는 final mismatch가 잔류한다.
    """

    counts: dict[str, int] = {}
    sort_metadata: dict[str, dict[str, Any]] = {}
    for result in results:
        details = result.details
        row_annotations = result.metadata.get("row_annotations", {}) if result.metadata else {}
        for rule_flag in result.rule_flags:
            canonical_rule_id = canonicalize_rule_id(str(rule_flag.rule_id))
            if canonical_rule_id not in _DATA_INTEGRITY_TRACK_RULES:
                continue
            flagged = 0
            if details is not None:
                detail_column = (
                    str(rule_flag.rule_id)
                    if str(rule_flag.rule_id) in details.columns
                    else canonical_rule_id
                )
                if detail_column in details.columns:
                    scores = pd.to_numeric(details[detail_column], errors="coerce").fillna(0.0)
                    flagged = int(scores.gt(0).sum())
            counts[canonical_rule_id] = counts.get(canonical_rule_id, 0) + flagged
            annotations = row_annotations.get(canonical_rule_id, {})
            if isinstance(annotations, dict):
                metadata = sort_metadata.setdefault(canonical_rule_id, {})
                if canonical_rule_id == "L1-01":
                    amounts = [
                        float(annotation.get("imbalance_amount", 0.0) or 0.0)
                        for annotation in annotations.values()
                        if isinstance(annotation, dict)
                    ]
                    if amounts:
                        metadata["sort_key"] = "imbalance_amount_desc"
                        metadata["max_imbalance_amount"] = max(
                            float(metadata.get("max_imbalance_amount", 0.0)),
                            max(amounts),
                        )
                elif canonical_rule_id == "L1-02":
                    categories = [
                        int(annotation.get("missing_category"))
                        for annotation in annotations.values()
                        if isinstance(annotation, dict)
                        and annotation.get("missing_category") in (1, 2)
                    ]
                    if categories:
                        metadata["sort_key"] = "missing_category_asc"
                        metadata["min_missing_category"] = min(
                            int(metadata.get("min_missing_category", 2)),
                            min(categories),
                        )

        rule_breakdowns = result.metadata.get("rule_breakdowns", {}) if result.metadata else {}
        for rule_id in _DUAL_INTEGRITY_TRACK_RULES:
            breakdown = rule_breakdowns.get(rule_id, {})
            raw_count = 0
            if isinstance(breakdown, dict):
                raw_count = int(
                    breakdown.get("raw_fiscal_period_mismatch_rows")
                    or breakdown.get("raw_fiscal_period_mismatch_count")
                    or 0
                )
            raw_count = int(
                result.metadata.get("raw_fiscal_period_mismatch_count", raw_count)
                if result.metadata
                else raw_count
            )
            counts[rule_id] = counts.get(rule_id, 0) + raw_count

    findings: list[dict[str, Any]] = []
    for rule_id in sorted(_DATA_INTEGRITY_TRACK_RULES | _DUAL_INTEGRITY_TRACK_RULES):
        interpretation = (
            "기간 귀속 점검 신호. cutoff 부정후보(위험 큐)와 별도로 본다."
            if rule_id in _DUAL_INTEGRITY_TRACK_RULES
            else "데이터 품질·정합성 점검 신호. 부정 위험 등급(HIGH/MEDIUM/LOW)과 분리해 본다."
        )
        finding = {
            "rule_id": rule_id,
            "rule_label": _DATA_INTEGRITY_RULE_LABELS.get(rule_id, rule_id),
            "track": "data_integrity",
            "flagged_row_count": int(counts.get(rule_id, 0)),
            "interpretation": interpretation,
        }
        finding.update(sort_metadata.get(rule_id, {}))
        findings.append(finding)
    return findings


def _build_l402_macro_findings(
    track_name: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, finding in enumerate(metadata.get("benford_findings", []) or [], start=1):
        if not isinstance(finding, dict):
            continue
        rows.append(
            {
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
            }
        )
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
        rows.append(
            {
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
            }
        )
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
        rows.append(
            {
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
            }
        )
    return rows


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
    if any(
        token in sources for token in ("automated", "recurring", "interface", "batch", "system")
    ):
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
    return _collect_raw_hits_profiled(df, results, profile_callback=None)


def _collect_raw_hits_profiled(
    df: pd.DataFrame,
    results: list[DetectionResult],
    *,
    profile_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[_RawHit]:
    hits: list[_RawHit] = []
    row_positions = {label: pos for pos, label in enumerate(df.index)}
    document_ids = (
        df["document_id"].fillna("").astype(str).str.strip().to_numpy()
        if "document_id" in df.columns
        else None
    )
    record_ids = (
        df["record_id"].fillna("").astype(str).str.strip().to_numpy()
        if "record_id" in df.columns
        else None
    )
    normalized_cache: dict[
        tuple[str, str, int, float, str | None],
        Any,
    ] = {}
    case_candidate_labels = _case_candidate_index_labels(df)
    for result in results:
        details = result.details if result.details is not None else pd.DataFrame(index=df.index)
        row_annotations = (result.metadata or {}).get("row_annotations", {})
        for rule_flag in result.rule_flags:
            requested_rule_id = str(rule_flag.rule_id)
            canonical_rule_id = canonicalize_rule_id(requested_rule_id)
            rule_detail_metadata = _safe_rule_detail_metadata(requested_rule_id)
            if canonical_rule_id in _MACRO_FINDING_RULES:
                continue
            # 데이터 정합성 트랙: 위험 큐에서 분리(별도 트랙 표시). 위험 topic/tier/priority 기여 0.
            if canonical_rule_id in _DATA_INTEGRITY_TRACK_RULES:
                continue
            metadata = RULE_SCORING_REGISTRY.get(canonical_rule_id) or RULE_SCORING_REGISTRY.get(
                requested_rule_id
            )
            topic_id = metadata.final_topic if metadata is not None else None
            if rule_detail_metadata is not None and rule_detail_metadata.final_topic:
                topic_id = rule_detail_metadata.final_topic
            mapping = _RULE_THEME_MAP.get(canonical_rule_id) or _RULE_THEME_MAP.get(
                requested_rule_id
            )
            if topic_id is None and mapping is not None:
                topic_id = _LEGACY_THEME_TOPIC_MAP.get(mapping[0])
            detail_column = (
                requested_rule_id if requested_rule_id in details.columns else canonical_rule_id
            )
            if topic_id not in TOPIC_REGISTRY or detail_column not in details.columns:
                continue
            rule_start = time.perf_counter()
            hit_start_count = len(hits)
            fallback_theme_id, fallback_evidence_type = mapping or (
                _TOPIC_LEGACY_THEME_MAP.get(str(topic_id), str(topic_id)),
                metadata.evidence_type if metadata is not None else str(topic_id),
            )
            theme_id = _TOPIC_LEGACY_THEME_MAP.get(str(topic_id), fallback_theme_id)
            evidence_type = (
                metadata.evidence_type if metadata is not None else fallback_evidence_type
            )
            column = details[detail_column]
            rule_annotations = row_annotations.get(
                requested_rule_id,
                row_annotations.get(canonical_rule_id, {}),
            )
            raw_scores = pd.to_numeric(column, errors="coerce").fillna(0.0)
            seed_labels: set[Any] = set(raw_scores[raw_scores.gt(0)].index.tolist())
            if case_candidate_labels is not None:
                seed_labels.intersection_update(case_candidate_labels)
            context_labels: set[Any] = set()
            if isinstance(rule_annotations, dict):
                for raw_idx, annotation in rule_annotations.items():
                    if not isinstance(annotation, dict):
                        continue
                    row_label = raw_idx if raw_idx in row_positions else None
                    if row_label is None:
                        try:
                            candidate_pos = int(raw_idx)
                        except (TypeError, ValueError):
                            continue
                        if 0 <= candidate_pos < len(df):
                            row_label = df.index[candidate_pos]
                    if row_label is None:
                        continue
                    if case_candidate_labels is not None and row_label not in case_candidate_labels:
                        continue
                    if _annotation_can_seed_case(requested_rule_id, annotation):
                        seed_labels.add(row_label)
                    elif _annotation_score(annotation) > 0:
                        context_labels.add(row_label)

            candidate_labels = seed_labels | context_labels
            for row_label in candidate_labels:
                row_pos = row_positions.get(row_label)
                if row_pos is None:
                    try:
                        candidate_pos = int(row_label)
                    except (TypeError, ValueError):
                        continue
                    if candidate_pos < 0 or candidate_pos >= len(df):
                        continue
                    row_pos = candidate_pos
                row_annotation = _lookup_row_annotation(rule_annotations, row_label, row_pos)
                raw_score_float = float(raw_scores.iloc[row_pos])
                annotation_score = _annotation_score(row_annotation)
                score = max(raw_score_float, annotation_score)
                if score <= 0:
                    continue
                signal_status = "confirmed" if raw_score_float > 0 else "review_candidate"
                can_seed_case = row_label in seed_labels
                display_label = _row_display_label(row_annotation)
                severity = int(rule_flag.severity)
                normalized_key = (
                    canonical_rule_id,
                    evidence_type,
                    severity,
                    round(float(score), 8),
                    display_label,
                )
                normalized = normalized_cache.get(normalized_key)
                if normalized is None:
                    normalized = normalize_rule_evidence(
                        rule_id=canonical_rule_id,
                        evidence_type=evidence_type,
                        severity=severity,
                        raw_value=score,
                        display_label=display_label,
                    )
                    normalized_cache[normalized_key] = normalized
                can_seed_case = can_seed_case and _hit_can_seed_case(
                    requested_rule_id=requested_rule_id,
                    normalized=normalized,
                )
                document_id = (
                    str(document_ids[row_pos])
                    if document_ids is not None and str(document_ids[row_pos])
                    else f"row-{row_pos}"
                )
                record_id = (
                    str(record_ids[row_pos])
                    if record_ids is not None and str(record_ids[row_pos])
                    else None
                )
                hits.append(
                    _RawHit(
                        rule_id=canonical_rule_id,
                        requested_rule_id=requested_rule_id,
                        canonical_rule_id=canonical_rule_id,
                        theme_id=theme_id,
                        topic_id=str(normalized.final_topic or topic_id),
                        evidence_type=evidence_type,
                        severity=severity,
                        row_index=row_pos,
                        score=float(score),
                        signal_strength=normalized.signal_strength,
                        normalized_score=normalized.normalized_score,
                        evidence_strength=normalized.evidence_strength,
                        scoring_role=normalized.scoring_role,
                        display_label=normalized.display_label,
                        signal_status=signal_status,
                        document_id=document_id,
                        record_id=record_id,
                        detail=_rule_hit_detail(
                            canonical_rule_id,
                            rule_flag.detail,
                            row_annotation,
                        ),
                        annotation=row_annotation,
                        can_seed_case=can_seed_case,
                        secondary_topics=tuple(normalized.secondary_topics),
                        standalone_rankable=bool(normalized.standalone_rankable),
                        floor_policy_ids=tuple(normalized.floor_policy_ids),
                        combo_policy_ids=tuple(normalized.combo_policy_ids),
                        fraud_scenario_tags=tuple(normalized.fraud_scenario_tags),
                    )
                )
            if profile_callback is not None:
                profile_callback(
                    f"collect_raw_hits.{requested_rule_id}",
                    {
                        "elapsed_sec": round(time.perf_counter() - rule_start, 3),
                        "candidate_labels": len(candidate_labels),
                        "seed_candidate_labels": len(seed_labels),
                        "context_candidate_labels": len(context_labels - seed_labels),
                        "hits_added": len(hits) - hit_start_count,
                    },
                )
    return hits


def _case_candidate_index_labels(df: pd.DataFrame) -> set[Any] | None:
    """Return row labels eligible for the Phase 1 case queue after aggregation."""

    if "risk_level" in df.columns:
        risk = df["risk_level"].astype(str)
        return set(risk[risk.ne("Normal")].index.tolist())
    if "anomaly_score" in df.columns:
        score = pd.to_numeric(df["anomaly_score"], errors="coerce").fillna(0.0)
        return set(score[score.gt(0)].index.tolist())
    return None


def _build_cases(
    df: pd.DataFrame,
    raw_hits: list[_RawHit],
    config: dict[str, Any],
    macro_findings: list[dict[str, Any]] | None = None,
    profile_callback: Callable[[str, dict[str, Any]], None] | None = None,
    *,
    engagement_salt: str = "",
    partner_row_badges: pd.DataFrame | None = None,
) -> list[CaseGroupResult]:
    if not raw_hits:
        return []

    build_start = time.perf_counter()
    step_start = build_start
    line_amounts = _line_amount_series(df)
    document_amounts = _document_amounts_by_id(df, line_amounts)
    document_ref_columns = _document_ref_columns(df, config)
    macro_index = _build_macro_context_index(macro_findings or [])
    macro_row_context = _build_macro_row_context(df)
    audit_context = _build_audit_evidence_context(df)
    if profile_callback is not None:
        profile_callback(
            "build_cases.init_amount_cache",
            {
                "elapsed_sec": round(time.perf_counter() - step_start, 3),
                "document_amounts": len(document_amounts),
            },
        )

    step_start = time.perf_counter()
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    hits_by_row: dict[int, list[_RawHit]] = defaultdict(list)
    theme_row_pairs: dict[tuple[str, int], None] = {}
    row_cache: dict[int, pd.Series] = {}
    for hit in raw_hits:
        hits_by_row[hit.row_index].append(hit)
        if hit.can_seed_case:
            theme_row_pairs.setdefault((hit.topic_id, hit.row_index), None)
    case_key_context = _build_case_key_context(
        df,
        line_amounts,
        config,
        sorted(hits_by_row),
    )
    for theme_id, row_index in theme_row_pairs:
        legacy_theme_id = _legacy_theme_for_topic(theme_id)
        row = row_cache.get(row_index)
        if row is None and legacy_theme_id not in _FAST_CASE_KEY_THEMES:
            row = df.iloc[row_index]
            row_cache[row_index] = row
        case_key_parts = _make_case_key_parts_from_context(
            legacy_theme_id,
            row_index,
            case_key_context,
        )
        if case_key_parts is None:
            if row is None:
                row = df.iloc[row_index]
                row_cache[row_index] = row
            case_key_parts = _make_case_key_parts(legacy_theme_id, row, config)
        case_key = " / ".join(str(value) for value in case_key_parts.values())
        group_key = (theme_id, case_key)
        if group_key not in groups:
            groups[group_key] = {
                "case_key_parts": case_key_parts,
                "row_indices": set(),
            }
        groups[group_key]["row_indices"].add(row_index)
    if profile_callback is not None:
        profile_callback(
            "build_cases.group_raw_hits",
            {
                "elapsed_sec": round(time.perf_counter() - step_start, 3),
                "groups": len(groups),
                "hit_rows": len(hits_by_row),
                "theme_row_pairs": len(theme_row_pairs),
                "row_cache": len(row_cache),
            },
        )

    step_start = time.perf_counter()
    max_amount = (
        max(
            (
                _case_total_amount(df, group["row_indices"], line_amounts=line_amounts)
                for group in groups.values()
            ),
            default=0.0,
        )
        or 1.0
    )
    if profile_callback is not None:
        profile_callback(
            "build_cases.max_amount",
            {
                "elapsed_sec": round(time.perf_counter() - step_start, 3),
                "max_amount": float(max_amount),
            },
        )
    repeat_tiebreak = int(config.get("repeat_months_tiebreak", 3))
    cases: list[CaseGroupResult] = []
    step_start = time.perf_counter()
    l304_repeat_signatures = (
        _l304_repeat_pattern_signatures(df, config.get("timing_priority", {}))
        if any(hit.rule_id == "L3-04" for hit in raw_hits)
        else set()
    )
    if profile_callback is not None:
        profile_callback(
            "build_cases.l304_repeat_signatures",
            {
                "elapsed_sec": round(time.perf_counter() - step_start, 3),
                "count": len(l304_repeat_signatures),
            },
        )

    step_start = time.perf_counter()
    loop_timings: dict[str, float] = defaultdict(float)
    raw_rule_hit_ref_cache: dict[tuple[str, int], RawRuleHitRef] = {}
    document_ref_cache: dict[tuple[str, tuple[tuple[str, int, str], ...]], CaseDocumentRef] = {}
    for ordinal, ((theme_id, case_key), group) in enumerate(groups.items(), start=1):
        legacy_theme_id = _legacy_theme_for_topic(theme_id)
        segment_start = time.perf_counter()
        indices = sorted(group["row_indices"])
        rows = df.iloc[indices]
        case_hits = _collect_case_hits(indices, hits_by_row)
        evidence_types = sorted({hit.evidence_type for hit in case_hits})
        evidence_scores = _theme_scores(case_hits, config)
        total_amount = _case_total_amount(df, indices, line_amounts=line_amounts)
        amount_score = _amount_score(total_amount, max_amount, config)
        loop_timings["prep"] += time.perf_counter() - segment_start

        segment_start = time.perf_counter()
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
        repeat_months = _repeat_months_from_positions(indices, audit_context.posting_months)
        repeat_score = min(max(repeat_months - 1, 0) / 2.0, 1.0)
        secondary_tags = _secondary_tags(legacy_theme_id, evidence_scores, config)
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
        loop_timings["base_score"] += time.perf_counter() - segment_start

        segment_start = time.perf_counter()
        priority_score, behavior_score, repeat_score = _apply_timing_priority_adjustments(
            df=df,
            theme_id=legacy_theme_id,
            rows=rows,
            case_hits=case_hits,
            secondary_tags=secondary_tags,
            amount_score=amount_score,
            behavior_score=behavior_score,
            repeat_score=repeat_score,
            priority_score=priority_score,
            config=config,
            l304_repeat_signatures=l304_repeat_signatures,
        )
        loop_timings["timing_adjust"] += time.perf_counter() - segment_start

        segment_start = time.perf_counter()
        (
            priority_score,
            behavior_score,
            adjustment_reasons,
            bonuses,
            case_weak_tags,
        ) = _apply_priority_adjustments(
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
        loop_timings["priority_adjust"] += time.perf_counter() - segment_start

        segment_start = time.perf_counter()
        macro_contexts = _case_macro_contexts(
            rows,
            macro_findings or [],
            indices=indices,
            macro_index=macro_index,
            macro_row_context=macro_row_context,
        )
        # macro(D01/D02/L4-02·Benford)는 PHASE1-1 점수경로에서 제외(2026-06-15, PHASE1-2 귀속).
        # case_hits 만으로 topic score/tier 산출. macro_contexts 는 _macro_context_tags 로 별도
        # 표시 surface 에만 반영, priority_score 에는 가산하지 않는다.
        loop_timings["macro_context"] += time.perf_counter() - segment_start

        segment_start = time.perf_counter()
        topic_breakdowns = compute_topic_scores(
            case_hits,
            topic_floor_policies=_topic_floor_policies(config),
            combo_floor_policies=_combo_floor_policies(config),
            fraud_combo_rule_scope=_fraud_combo_rule_scope(case_hits, audit_context),
            return_breakdown=True,
        )
        # PHASE1_TIER_SCORING_SPEC: 주제 점수·선택·band·정렬 전부 tier(가중합 .score 폐기).
        topic_tiers = compute_topic_tiers(
            case_hits,
            topic_floor_policies=_topic_floor_policies(config),
            combo_floor_policies=_combo_floor_policies(config),
            fraud_combo_rule_scope=_fraud_combo_rule_scope(case_hits, audit_context),
            breakdowns=topic_breakdowns,  # 이미 위에서 계산 — 재계산 생략(성능)
        )
        # topic_scores = tier 대표값(가중합 아님). CONTEXT 제외. pick_primary_topic 은 max 라
        # 자동으로 최고 tier 주제를 선택(동률은 TOPIC_REGISTRY 순서).
        topic_scores = {
            topic_id: _TIER_TO_PRIORITY_SCORE[tier_breakdown.tier]
            for topic_id, tier_breakdown in topic_tiers.items()
            if tier_breakdown.tier != "CONTEXT"
        }
        primary_topic = (
            theme_id if topic_scores.get(theme_id, 0.0) > 0 else pick_primary_topic(topic_scores)
        )
        if primary_topic is None:
            continue
        primary_topic_label = _topic_label(primary_topic)
        secondary_topics = [
            topic_id
            for topic_id in _case_secondary_topics(case_hits, topic_scores)
            if topic_id != primary_topic
        ]
        topic_score_breakdown = {
            topic_id: asdict(breakdown)
            for topic_id, breakdown in topic_breakdowns.items()
            if topic_id in topic_scores
        }
        # band·정렬은 tier 가 결정(가중합 아님). priority_score 는 tier 대표값(소비처 [0,1] 호환).
        case_tier_value = case_tier(topic_tiers)
        priority_band = _TIER_TO_BAND.get(case_tier_value, "low")
        priority_score = _TIER_TO_PRIORITY_SCORE.get(case_tier_value, 0.0)
        composite_sort_score, composite_sort_score_components = _tier_sort_score(
            case_tier_value, case_hits, amount_score
        )
        l304_repeat_pattern = _is_l304_repeat_pattern_case(
            df,
            rows,
            case_hits,
            config.get("timing_priority", {}),
            l304_repeat_signatures=l304_repeat_signatures,
        )
        legacy_primary_queue, legacy_secondary_queues = _case_issue_queues(
            legacy_theme_id,
            case_hits,
            evidence_types,
        )
        primary_theme = primary_topic
        primary_queue = primary_topic
        primary_queue_label = primary_topic_label
        secondary_queues = secondary_topics
        secondary_queue_labels = [_topic_label(queue) for queue in secondary_queues]
        triage_rank_score, triage_rank_reasons = _triage_rank_score(
            primary_queue=legacy_primary_queue,
            secondary_queues=legacy_secondary_queues,
            case_hits=case_hits,
            evidence_types=evidence_types,
            document_count=len({hit.document_id for hit in case_hits}),
            amount_score=amount_score,
            total_amount=total_amount,
            has_repeat_pattern=l304_repeat_pattern or repeat_months >= repeat_tiebreak,
        )
        auditor_insight = _auditor_insight(
            theme_id=legacy_theme_id,
            case_hits=case_hits,
            total_amount=total_amount,
        )
        loop_timings["auditor_insight"] += time.perf_counter() - segment_start

        segment_start = time.perf_counter()
        documents = _build_document_refs(
            df,
            case_hits,
            config,
            document_amounts=document_amounts,
            line_amounts=line_amounts,
            ref_cache=document_ref_cache,
            document_ref_columns=document_ref_columns,
        )
        raw_rule_hits = _raw_rule_hit_refs(
            case_hits,
            raw_rule_hit_ref_cache,
            df=df,
            engagement_salt=engagement_salt,
        )
        loop_timings["refs"] += time.perf_counter() - segment_start

        segment_start = time.perf_counter()
        case_rule_ids = {hit.rule_id for hit in case_hits}
        case_time_severity = compute_time_severity_score(case_rule_ids)
        case_badge_tags = _compose_badge_tags(
            partner_tags=_partner_badges_for_positions(partner_row_badges, indices),
            time_severity_score=case_time_severity,
            fired_rule_ids=case_rule_ids,
            weak_tags=case_weak_tags,
        )
        cases.append(
            CaseGroupResult(
                case_id=f"case_{theme_id}_{ordinal:05d}",
                primary_topic=primary_topic,
                primary_topic_label=primary_topic_label,
                topic_scores=topic_scores,
                topic_score_breakdown=topic_score_breakdown,
                secondary_topics=secondary_topics,
                fraud_scenario_tags=list(compute_fraud_scenario_tags(case_hits)),
                primary_theme=primary_theme,
                primary_queue=primary_queue,
                primary_queue_label=primary_queue_label,
                secondary_queues=secondary_queues,
                secondary_queue_labels=secondary_queue_labels,
                secondary_tags=secondary_tags,
                evidence_types=evidence_types,
                case_key=case_key,
                case_key_parts=group["case_key_parts"],
                priority_score=priority_score,
                base_priority_score=base_priority_score,
                composite_sort_score=composite_sort_score,
                composite_sort_score_components=composite_sort_score_components,
                topside_bonus=bonuses["topside_bonus"],
                weak_evidence_bonus=bonuses["weak_evidence_bonus"],
                priority_adjustment_reasons=adjustment_reasons,
                priority_band=priority_band,
                triage_rank_score=triage_rank_score,
                triage_rank_reasons=triage_rank_reasons,
                amount_score=amount_score,
                control_score=control_score,
                duplicate_or_outflow_score=duplicate_or_outflow_score,
                logic_score=logic_score,
                data_integrity_score=data_integrity_score,
                intercompany_score=intercompany_score,
                timing_score=timing_score,
                behavior_score=behavior_score,
                repeat_score=repeat_score,
                time_severity_score=case_time_severity,
                badge_tags=case_badge_tags,
                rule_count=len(case_rule_ids),
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
                evidence_tags=sorted(
                    {
                        *evidence_types,
                        *secondary_tags,
                        *(_macro_context_tags(macro_contexts)),
                    }
                ),
                macro_contexts=macro_contexts,
                documents=documents,
                raw_rule_hits=raw_rule_hits,
                has_control_failure="control_failure" in evidence_types,
                has_high_materiality=amount_score >= 0.75,
                has_repeat_pattern=(repeat_months >= repeat_tiebreak) or l304_repeat_pattern,
            )
        )
        loop_timings["model_append"] += time.perf_counter() - segment_start
        if profile_callback is not None and ordinal % 1000 == 0:
            profile_callback(
                "build_cases.case_loop_progress",
                {
                    "elapsed_sec": round(time.perf_counter() - step_start, 3),
                    "processed": ordinal,
                    "total_groups": len(groups),
                    "cases": len(cases),
                    "timings": {
                        name: round(value, 3) for name, value in sorted(loop_timings.items())
                    },
                },
            )

    if profile_callback is not None:
        profile_callback(
            "build_cases.case_loop_done",
            {
                "elapsed_sec": round(time.perf_counter() - step_start, 3),
                "processed": len(groups),
                "cases": len(cases),
                "timings": {name: round(value, 3) for name, value in sorted(loop_timings.items())},
            },
        )

    step_start = time.perf_counter()
    # §9.3 정렬: composite_sort_score 1차 → (triage_rank_score, total_amount, rule_count) 보조.
    # total_amount 를 1차 결정자에서 보조 결정자로 격하해 truth 가 amount 큰 nontruth 에 묻히지 않게 한다.
    cases.sort(
        key=lambda item: (
            item.composite_sort_score,
            item.triage_rank_score,
            item.total_amount,
            item.rule_count,
        ),
        reverse=True,
    )
    for index, case in enumerate(cases, start=1):
        case.exposure_rank = index
        case.is_top_case = index <= int(config.get("top_n_cases", 50))
    _apply_theme_ranks(cases)
    if profile_callback is not None:
        profile_callback(
            "build_cases.sort_rank",
            {
                "elapsed_sec": round(time.perf_counter() - step_start, 3),
                "total_elapsed_sec": round(time.perf_counter() - build_start, 3),
                "cases": len(cases),
            },
        )
    return cases


def _build_document_units(
    raw_hits: list[_RawHit],
    *,
    df: pd.DataFrame,
    absorbed_document_ids: set[str] | None = None,
    engagement_salt: str = "",
) -> list[Phase1Unit]:
    absorbed_document_ids = absorbed_document_ids or set()
    document_hits: dict[str, list[_RawHit]] = defaultdict(list)
    for hit in raw_hits:
        if hit.signal_status != "confirmed":
            continue
        if hit.document_id in absorbed_document_ids:
            continue
        if hit.rule_id in _FLOW_UNIT_RULES or hit.rule_id in _REVIEW_POPULATION_RULES:
            continue
        if hit.rule_id not in _DOCUMENT_UNIT_RULES:
            continue
        document_hits[hit.document_id].append(hit)

    units: list[Phase1Unit] = []
    raw_rule_hit_ref_cache: dict[tuple[str, int], RawRuleHitRef] = {}
    for document_id in sorted(document_hits):
        hits = sorted(document_hits[document_id], key=lambda item: (item.row_index, item.rule_id))
        evidence_rows = _raw_rule_hit_refs(
            hits,
            raw_rule_hit_ref_cache,
            df=df,
            engagement_salt=engagement_salt,
        )
        units.append(DocumentUnit(unit_id=document_id, evidence_rows=evidence_rows))
    return units


def _score_phase1_units(
    units: list[Phase1Unit],
    raw_hits: list[_RawHit],
    df: pd.DataFrame,
    config: dict[str, Any],
    *,
    partner_row_badges: pd.DataFrame | None = None,
) -> list[Phase1Unit]:
    if not units:
        return units
    hit_lookup = {(hit.rule_id, hit.row_index): hit for hit in raw_hits}
    hits_by_document: dict[str, list[_RawHit]] = defaultdict(list)
    for hit in raw_hits:
        if hit.document_id:
            hits_by_document[hit.document_id].append(hit)
    unit_hits: dict[str, list[_RawHit]] = {}
    line_amounts = _line_amount_series(df)
    audit_context = _build_audit_evidence_context(df)
    # Why(성능): document_id→positions 맵을 1회만 구축해 _unit_total_amount 의 per-unit 910k 전체
    #      스캔을 제거(O(units×n)→O(n+units)). 정규화는 기존 스캔과 동일(fillna("")+astype(str)).
    doc_positions: dict[str, list[int]] = defaultdict(list)
    if "document_id" in df.columns:
        for _pos, _doc_id in enumerate(df["document_id"].fillna("").astype(str).tolist()):
            doc_positions[_doc_id].append(_pos)
    unit_amounts: dict[str, float] = {}
    for unit in units:
        hits = _unit_scoring_hits(unit, hit_lookup, hits_by_document)
        unit_hits[unit.unit_id] = hits
        unit_amounts[unit.unit_id] = _unit_total_amount(
            df,
            unit,
            hits,
            line_amounts=line_amounts,
            doc_positions=doc_positions,
        )
    max_amount = max(unit_amounts.values(), default=0.0) or 1.0

    scored_units: list[Phase1Unit] = []
    for unit in units:
        # 이 unit이 발화한 룰ID 집합 = evidence_rows + (FlowUnit) absorbed_rule_hits.
        # compute_time_severity_score 는 시각·연도 리터럴 없이 룰ID 발화 여부만 본다.
        fired_rule_ids = {ref.rule_id for ref in unit.evidence_rows}
        if isinstance(unit, FlowUnit):
            fired_rule_ids.update(ref.rule_id for ref in unit.absorbed_rule_hits)
        unit_total_amount = unit_amounts.get(unit.unit_id, 0.0)
        unit_time_severity = compute_time_severity_score(fired_rule_ids)
        unit_badge_tags = _compose_badge_tags(
            partner_tags=_partner_badges_for_positions(
                partner_row_badges, _unit_row_positions(unit, doc_positions)
            ),
            time_severity_score=unit_time_severity,
            fired_rule_ids=fired_rule_ids,
        )
        hits = unit_hits.get(unit.unit_id, [])
        if not hits:
            scored_units.append(
                unit.model_copy(
                    update={
                        "total_amount": unit_total_amount,
                        "time_severity_score": unit_time_severity,
                        "badge_tags": unit_badge_tags,
                    }
                )
            )
            continue
        projection = _score_unit_hits(
            df=df,
            unit=unit,
            hits=hits,
            total_amount=unit_total_amount,
            max_amount=max_amount,
            config=config,
            audit_context=audit_context,
        )
        scored_units.append(
            unit.model_copy(
                update={
                    "priority_score": projection.priority_score,
                    "base_priority_score": projection.base_priority_score,
                    "composite_sort_score": projection.composite_sort_score,
                    "composite_sort_score_components": projection.composite_sort_score_components
                    or {},
                    "topic_scores": projection.topic_scores or {},
                    "topic_score_breakdown": projection.topic_score_breakdown or {},
                    "priority_band": projection.priority_band,
                    "triage_rank_score": projection.triage_rank_score,
                    "triage_rank_reasons": projection.triage_rank_reasons or [],
                    "total_amount": unit_total_amount,
                    "time_severity_score": unit_time_severity,
                    "badge_tags": unit_badge_tags,
                }
            )
        )
    return scored_units


def _unit_scoring_hits(
    unit: Phase1Unit,
    hit_lookup: dict[tuple[str, int], _RawHit],
    hits_by_document: dict[str, list[_RawHit]],
) -> list[_RawHit]:
    hits = [
        hit_lookup[key]
        for ref in unit.evidence_rows
        if (key := (ref.rule_id, ref.row_index)) in hit_lookup
    ]
    if isinstance(unit, DocumentUnit):
        hits.extend(
            hit
            for hit in hits_by_document.get(unit.unit_id, [])
            if hit.document_id == unit.unit_id
            and hit.signal_status == "confirmed"
            and hit.rule_id not in _REVIEW_POPULATION_RULES
        )
    deduped = {(hit.rule_id, hit.row_index, hit.document_id): hit for hit in hits}
    return sorted(deduped.values(), key=lambda hit: (hit.row_index, hit.rule_id))


def _unit_total_amount(
    df: pd.DataFrame,
    unit: Phase1Unit,
    hits: list[_RawHit],
    *,
    line_amounts: pd.Series,
    doc_positions: dict[str, list[int]] | None = None,
) -> float:
    if isinstance(unit, FlowUnit) and unit.member_document_ids and "document_id" in df.columns:
        doc_ids = set(unit.member_document_ids)
        if doc_positions is not None:
            # Why(성능): doc_positions 는 호출부에서 1회 구축한 document_id→positions 맵.
            #      과거엔 FlowUnit 마다 df["document_id"] 910k 행 전체를 스캔(O(units×n))해
            #      score_phase1_units 가 수 분 소요. 맵 조회로 대체 — 동일 정규화(fillna("")+astype(str))
            #      라 같은 positions 집합 반환(동작 보존).
            positions = sorted({pos for doc in doc_ids for pos in doc_positions.get(doc, ())})
        else:
            positions = [
                int(pos)
                for pos, document_id in enumerate(df["document_id"].fillna("").astype(str).tolist())
                if document_id in doc_ids
            ]
    else:
        positions = sorted({hit.row_index for hit in hits})
    return _case_total_amount(df, positions, line_amounts=line_amounts)


def _score_unit_hits(
    *,
    df: pd.DataFrame,
    unit: Phase1Unit,
    hits: list[_RawHit],
    total_amount: float,
    max_amount: float,
    config: dict[str, Any],
    audit_context: _AuditEvidenceContext,
) -> _UnitScoreProjection:
    indices = sorted({hit.row_index for hit in hits})
    rows = df.iloc[indices]
    evidence_types = sorted({hit.evidence_type for hit in hits})
    evidence_scores = _theme_scores(hits, config)
    amount_score = _amount_score(total_amount, max_amount, config)
    access_scope_score = min(evidence_scores.get("access_scope_review", 0.0), 1.0)
    control_score = min(evidence_scores.get("control_failure", 0.0), 1.0)
    duplicate_or_outflow_score = min(evidence_scores.get("duplicate_or_outflow", 0.0), 1.0)
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
    (
        priority_score,
        behavior_score,
        adjustment_reasons,
        _bonuses,
        _weak_tags,
    ) = _apply_priority_adjustments(
        rows=rows,
        case_hits=hits,
        evidence_types=evidence_types,
        amount_score=amount_score,
        total_amount=total_amount,
        priority_score=priority_score,
        behavior_score=behavior_score,
        config=config,
    )
    priority_score, floor_reasons = _apply_priority_floors(
        case_hits=hits,
        priority_score=priority_score,
        config=config,
    )
    adjustment_reasons.extend(floor_reasons)
    if _is_low_risk_linked_l205_reversal(unit, rows):
        priority_score = min(
            priority_score, float(config.get("l205_linked_reversal_low_cap", 0.35))
        )
        adjustment_reasons = [*adjustment_reasons, "l205_linked_accrual_reversal_low"]
    topic_breakdowns = compute_topic_scores(
        hits,
        topic_floor_policies=_topic_floor_policies(config),
        combo_floor_policies=_combo_floor_policies(config),
        fraud_combo_rule_scope=_fraud_combo_rule_scope(hits, audit_context),
        return_breakdown=True,
    )
    # PHASE1_TIER_SCORING_SPEC: unit topic 점수·band·정렬 전부 tier(가중합 .score 폐기).
    # _derive_case_scores_from_units 가 이 unit 점수를 case 로 전파하므로 활성 경로는 여기다.
    topic_tiers = compute_topic_tiers(
        hits,
        topic_floor_policies=_topic_floor_policies(config),
        combo_floor_policies=_combo_floor_policies(config),
        fraud_combo_rule_scope=_fraud_combo_rule_scope(hits, audit_context),
        breakdowns=topic_breakdowns,  # 이미 위에서 계산 — 재계산 생략(성능)
    )
    # topic_scores = tier 대표값(가중합 아님). pick_primary_topic 이 max 라 자동 최고 tier.
    topic_scores = {
        topic_id: _TIER_TO_PRIORITY_SCORE[tier_breakdown.tier]
        for topic_id, tier_breakdown in topic_tiers.items()
        if tier_breakdown.tier != "CONTEXT"
    }
    # priority_score = tier 대표값([0,1]) → _derive 의 _priority_band 가 올바른 band 자동 전파.
    topic_tier = case_tier(topic_tiers)
    # config priority_floors(명시 도메인 조건: SoD critical·승인생략·핵심필드 누락 등)도
    # tier 트리거다. floor-only 점수(가중합 배제, 0.0 기준)로 산출해 합류.
    floor_only_score, _ = _apply_priority_floors(case_hits=hits, priority_score=0.0, config=config)
    floor_tier = _legacy_floor_tier(floor_only_score)
    unit_tier = topic_tier if TIER_RANK[topic_tier] >= TIER_RANK[floor_tier] else floor_tier
    priority_score = _TIER_TO_PRIORITY_SCORE.get(unit_tier, 0.0)
    priority_band = _TIER_TO_BAND.get(unit_tier, "low")
    composite_sort_score, composite_sort_score_components = _tier_sort_score(
        unit_tier, hits, amount_score
    )
    if _is_low_risk_linked_l205_reversal(unit, rows):
        # tier 경로는 priority_score 를 tier 대표값으로 덮으므로 low cap 을 여기서 재적용.
        # _derive_case_scores_from_units 가 priority_score 로 case band 를 재계산하기 때문.
        priority_score = min(
            priority_score, float(config.get("l205_linked_reversal_low_cap", 0.35))
        )
        composite_sort_score = min(composite_sort_score, priority_score)
        priority_band = "low"
    return _UnitScoreProjection(
        priority_score=float(priority_score),
        base_priority_score=float(base_priority_score),
        composite_sort_score=float(composite_sort_score),
        composite_sort_score_components=composite_sort_score_components,
        topic_scores=topic_scores,
        topic_score_breakdown={
            topic_id: asdict(breakdown)
            for topic_id, breakdown in topic_breakdowns.items()
            if topic_id in topic_scores
        },
        priority_band=priority_band,
        triage_rank_score=float(priority_score),
        triage_rank_reasons=adjustment_reasons,
    )


def _is_low_risk_linked_l205_reversal(unit: Phase1Unit, rows: pd.DataFrame) -> bool:
    if not isinstance(unit, FlowUnit) or unit.flow_type != "reversal":
        return False
    link_type = str(unit.link_key.get("link_type") or "").strip().lower()
    if link_type != "structural_reference":
        return False
    text = " ".join(
        str(value).lower()
        for column in ("line_text", "header_text", "description", "business_process")
        if column in rows.columns
        for value in rows[column].fillna("").tolist()
    )
    return any(token in text for token in ("accrual", "reversal", "미지급", "발생", "역분개"))


def _build_audit_evidence_context(df: pd.DataFrame) -> _AuditEvidenceContext:
    if "posting_date" in df.columns:
        posting_months = (
            pd.to_datetime(df["posting_date"], errors="coerce")
            .dt.strftime("%Y-%m")
            .fillna("")
            .astype(str)
            .tolist()
        )
    else:
        posting_months = [""] * len(df)

    source = _precomputed_string_column(df, "source")
    persona = _precomputed_string_column(df, "user_persona")
    created_by = _precomputed_string_column(df, "created_by")
    approved_by = _precomputed_string_column(df, "approved_by")
    business_process = _precomputed_string_column(df, "business_process")
    reference = _precomputed_string_column(df, "reference")
    trading_partner = _precomputed_string_column(df, "trading_partner")
    auxiliary = _precomputed_string_column(df, "auxiliary_account_number")
    lettrage = _precomputed_string_column(df, "lettrage")
    settlement = _precomputed_string_column(df, "settlement_status")

    manual_context = (
        source.str.contains("manual", case=False, na=False)
        | persona.str.contains("manual|accountant|manager", case=False, na=False)
        | (~created_by.str.upper().str.startswith("SYSTEM", na=False))
    ).tolist()

    support_gap = pd.Series(False, index=df.index)
    if "has_attachment" in df.columns:
        attachment = _precomputed_string_column(df, "has_attachment").str.strip().str.lower()
        support_gap = support_gap | attachment.isin({"false", "0", "nan", "none", ""})
    if "supporting_doc_type" in df.columns:
        support_type = _precomputed_string_column(df, "supporting_doc_type").str.strip().str.lower()
        support_gap = support_gap | support_type.isin({"", "nan", "none", "null"})

    created_strip = created_by.str.strip()
    approved_strip = approved_by.str.strip()
    manual_rows = ~created_strip.str.upper().str.startswith("SYSTEM", na=False)
    approver_missing = approved_strip.eq("") | approved_strip.str.lower().isin(
        {"nan", "none", "null"}
    )
    self_approval = created_strip.ne("") & approved_strip.ne("") & created_strip.eq(approved_strip)
    approval_gap = manual_rows & (approver_missing | self_approval)
    if {"posting_date", "approval_date"}.issubset(df.columns):
        posting = pd.to_datetime(df["posting_date"], errors="coerce")
        approval = pd.to_datetime(df["approval_date"], errors="coerce")
        approval_gap = approval_gap | (approval.notna() & posting.notna() & (approval < posting))

    if "posting_date" in df.columns:
        posting = pd.to_datetime(df["posting_date"], errors="coerce")
        post_close_gap = posting.dt.day.ge(28) | posting.dt.month.isin({3, 6, 9, 12})
    else:
        post_close_gap = pd.Series(False, index=df.index)

    related_party_context = (
        trading_partner.str.strip().ne("")
        | business_process.str.contains("IC|intercompany", case=False, na=False)
        | reference.str.contains(r"\bIC", case=False, regex=True, na=False)
    )
    reversal_context = lettrage.str.strip().ne("") | settlement.str.contains(
        "revers|offset|clear|settled",
        case=False,
        na=False,
    )
    if "is_cleared" in df.columns:
        cleared = _precomputed_string_column(df, "is_cleared").str.strip().str.lower()
        reversal_context = reversal_context | cleared.isin({"true", "1"})

    return _AuditEvidenceContext(
        posting_months=posting_months,
        manual_context=[bool(value) for value in manual_context],
        support_gap=[bool(value) for value in support_gap.tolist()],
        approval_gap=[bool(value) for value in approval_gap.tolist()],
        post_close_gap=[bool(value) for value in post_close_gap.fillna(False).tolist()],
        related_party_context=[bool(value) for value in related_party_context.tolist()],
        reversal_context=[bool(value) for value in reversal_context.tolist()],
        partner_value=[
            bool(value)
            for value in (
                auxiliary.str.strip().ne("") | trading_partner.str.strip().ne("")
            ).tolist()
        ],
        master_counterparty_inactive=_precomputed_true_column(df, "master_counterparty_inactive"),
        master_counterparty_known=_precomputed_true_column(df, "master_counterparty_known"),
        document_flow_orphan=_precomputed_true_column(df, "document_flow_orphan"),
        ic_matched_pair_found=_precomputed_true_column(df, "ic_matched_pair_found"),
        ic_unmatched_reference=_precomputed_true_column(df, "ic_unmatched_reference"),
        approval_matrix_gap=_precomputed_true_column(df, "approval_matrix_gap"),
        # Why: fraud-combo floor 게이트 — 신뢰 자동 전표(무리지은 배치) 행 표시 (이슈 #14)
        trusted_automated=[bool(value) for value in trusted_automated_mask(df).tolist()],
        approval_limit_exceeded_independent=_precomputed_true_column(
            df,
            "approval_limit_exceeded_independent",
        ),
    )


def _precomputed_string_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series("", index=df.index, dtype="string")
    # Why: nullable dtype(예: has_attachment 의 pandas "boolean") 컬럼은 fillna("")가
    #      TypeError('Invalid value "" for dtype boolean'). object 로 변환 후 NA→"" 로
    #      처리해 어떤 dtype 이 와도 문자열 컬럼을 보장한다 (함수 계약: string column).
    series = df[column]
    return series.astype(object).where(series.notna(), "").astype(str)


def _precomputed_true_column(df: pd.DataFrame, column: str) -> list[bool]:
    if column not in df.columns:
        return [False] * len(df)
    return [bool(value) for value in bool_column(df, column).tolist()]


def _repeat_months_from_positions(row_positions: list[int], posting_months: list[str]) -> int:
    return len(
        {
            posting_months[pos]
            for pos in row_positions
            if 0 <= pos < len(posting_months) and posting_months[pos]
        }
    )


def _derive_case_scores_from_units(
    cases: list[CaseGroupResult],
    units: list[Phase1Unit],
    config: dict[str, Any],
) -> list[CaseGroupResult]:
    if not cases or not units:
        return cases
    # Why: 과거 case마다 전체 units 를 스캔해 ref 교집합 → O(cases*units) 준-이차로
    #      전수(984k)에서 스톨. (rule_id,row_index) → unit 역인덱스로 case 당 실제 공유 ref
    #      를 가진 unit 만 수집(근사선형). unit_index 로 원래 units 순서를 복원해 동작
    #      (max 동점 처리·topic dict 삽입순서)을 정확히 보존한다.
    unit_index: dict[str, int] = {unit.unit_id: i for i, unit in enumerate(units)}
    units_by_id: dict[str, Phase1Unit] = {unit.unit_id: unit for unit in units}
    ref_to_units: dict[tuple[str, int], list[str]] = {}
    for unit in units:
        for ref in unit.evidence_rows:
            ref_to_units.setdefault((ref.rule_id, ref.row_index), []).append(unit.unit_id)
    derived_cases: list[CaseGroupResult] = []
    for case in cases:
        case_refs = {(ref.rule_id, ref.row_index) for ref in case.raw_rule_hits}
        linked_ids: set[str] = set()
        for ref in case_refs:
            linked_ids.update(ref_to_units.get(ref, ()))
        linked_units = [units_by_id[uid] for uid in sorted(linked_ids, key=lambda u: unit_index[u])]
        if not linked_units:
            derived_cases.append(
                case.model_copy(
                    update={
                        "priority_score": 0.0,
                        "base_priority_score": 0.0,
                        "composite_sort_score": 0.0,
                        "composite_sort_score_components": {"derived_unit_count": 0.0},
                        "topic_scores": {},
                        "topic_score_breakdown": {},
                        "priority_band": "low",
                    }
                )
            )
            continue
        max_unit = max(linked_units, key=lambda unit: unit.priority_score)
        max_composite = max(linked_units, key=lambda unit: unit.composite_sort_score)
        topic_scores: dict[str, float] = {}
        topic_score_breakdown: dict[str, dict[str, Any]] = {}
        for unit in linked_units:
            for topic_id, score in unit.topic_scores.items():
                if score > topic_scores.get(topic_id, 0.0):
                    topic_scores[topic_id] = score
                    topic_score_breakdown[topic_id] = unit.topic_score_breakdown.get(topic_id, {})
        derived_priority = float(max_unit.priority_score)
        derived_composite = float(max_composite.composite_sort_score)
        derived_cases.append(
            case.model_copy(
                update={
                    "priority_score": derived_priority,
                    "base_priority_score": max(
                        float(unit.base_priority_score) for unit in linked_units
                    ),
                    "composite_sort_score": derived_composite,
                    "composite_sort_score_components": max_composite.composite_sort_score_components,
                    "topic_scores": topic_scores,
                    "topic_score_breakdown": topic_score_breakdown,
                    "priority_band": _priority_band(derived_priority, config),
                    "triage_rank_score": max(
                        float(unit.triage_rank_score) for unit in linked_units
                    ),
                    "triage_rank_reasons": sorted(
                        {reason for unit in linked_units for reason in unit.triage_rank_reasons}
                    ),
                }
            )
        )
    derived_cases.sort(
        key=lambda item: (
            item.composite_sort_score,
            item.triage_rank_score,
            item.total_amount,
            item.rule_count,
        ),
        reverse=True,
    )
    for index, case in enumerate(derived_cases, start=1):
        case.exposure_rank = index
        case.is_top_case = index <= int(config.get("top_n_cases", 50))
    _apply_theme_ranks(derived_cases)
    return derived_cases


def _measurement_eligible_flow_member_document_ids(units: list[Phase1Unit]) -> set[str]:
    member_document_ids: set[str] = set()
    for unit in units:
        if not isinstance(unit, FlowUnit) or not unit.measurement_eligible:
            continue
        member_document_ids.update(str(doc_id) for doc_id in unit.member_document_ids if doc_id)
    return member_document_ids


def _absorb_document_hits_into_flow_units(
    raw_hits: list[_RawHit],
    flow_units: list[Phase1Unit],
    df: pd.DataFrame,
    *,
    engagement_salt: str = "",
) -> list[Phase1Unit]:
    confirmed_document_hits: dict[str, list[_RawHit]] = defaultdict(list)
    for hit in raw_hits:
        if hit.signal_status != "confirmed":
            continue
        if hit.rule_id in _FLOW_UNIT_RULES or hit.rule_id in _REVIEW_POPULATION_RULES:
            continue
        if hit.rule_id not in _DOCUMENT_UNIT_RULES:
            continue
        confirmed_document_hits[hit.document_id].append(hit)

    eligible_flow_units = [
        unit for unit in flow_units if isinstance(unit, FlowUnit) and unit.measurement_eligible
    ]
    primary_flow_by_document = _primary_measurement_flow_by_document(eligible_flow_units)
    cross_ref_flow_ids_by_document = _cross_ref_flow_ids_by_document(eligible_flow_units)

    raw_rule_hit_ref_cache: dict[tuple[str, int], RawRuleHitRef] = {}
    absorbed_units: list[Phase1Unit] = []
    for unit in flow_units:
        if not isinstance(unit, FlowUnit) or not unit.measurement_eligible:
            absorbed_units.append(unit)
            continue
        hits: list[_RawHit] = []
        for document_id in unit.member_document_ids:
            document_id = str(document_id)
            if primary_flow_by_document.get(document_id) != unit.unit_id:
                continue
            hits.extend(confirmed_document_hits.get(document_id, []))
        if not hits:
            absorbed_units.append(unit)
            continue
        hits = sorted(hits, key=lambda item: (item.document_id, item.row_index, item.rule_id))
        absorbed_refs = _raw_rule_hit_refs(
            hits,
            raw_rule_hit_ref_cache,
            df=df,
            engagement_salt=engagement_salt,
        )
        absorbed_document_ids = sorted({hit.document_id for hit in hits})
        cross_ref_flow_ids = sorted(
            {
                flow_id
                for document_id in absorbed_document_ids
                for flow_id in cross_ref_flow_ids_by_document.get(document_id, [])
                if flow_id != unit.unit_id
            }
        )
        absorbed_units.append(
            unit.model_copy(
                update={
                    "evidence_rows": [*unit.evidence_rows, *absorbed_refs],
                    "absorbed_document_ids": absorbed_document_ids,
                    "absorbed_rule_hits": absorbed_refs,
                    "measurement_owner_unit_id": unit.unit_id,
                    "cross_ref_flow_ids": cross_ref_flow_ids,
                }
            )
        )
    return absorbed_units


def _primary_measurement_flow_by_document(flow_units: list[FlowUnit]) -> dict[str, str]:
    by_document: dict[str, list[FlowUnit]] = defaultdict(list)
    for unit in flow_units:
        for document_id in unit.member_document_ids:
            if document_id:
                by_document[str(document_id)].append(unit)
    return {
        document_id: sorted(candidates, key=_flow_measurement_owner_priority)[0].unit_id
        for document_id, candidates in by_document.items()
        if candidates
    }


def _cross_ref_flow_ids_by_document(flow_units: list[FlowUnit]) -> dict[str, list[str]]:
    by_document: dict[str, set[str]] = defaultdict(set)
    for unit in flow_units:
        for document_id in unit.member_document_ids:
            if document_id:
                by_document[str(document_id)].add(unit.unit_id)
    return {document_id: sorted(flow_ids) for document_id, flow_ids in by_document.items()}


def _flow_measurement_owner_priority(unit: FlowUnit) -> tuple[int, int, str]:
    rule_ids = {hit.rule_id for hit in unit.evidence_rows}
    max_severity = max((SEVERITY_MAP.get(rule_id, 0) for rule_id in rule_ids), default=0)
    member_count = unit.member_count or len(unit.member_document_ids)
    return (-max_severity, member_count, unit.unit_id)


def _build_flow_units(
    df: pd.DataFrame,
    results: list[DetectionResult],
    *,
    engagement_salt: str = "",
) -> list[Phase1Unit]:
    units: list[Phase1Unit] = []
    for result in results:
        metadata = result.metadata or {}
        # IC(ic_pair_artifact)·GR(graph_result) flow unit 생성 제거(2026-06-21): IC/GR 은
        # PHASE1-2 family 귀속 — PHASE1-1 case 에 생성하지 않는다(완전 소멸).
        units.extend(
            _flow_units_from_duplicate_artifact(
                df,
                result,
                metadata.get("pair_artifact"),
                engagement_salt=engagement_salt,
            )
        )
        units.extend(
            _flow_units_from_l202_minimal_link_keys(
                df,
                result,
                engagement_salt=engagement_salt,
            )
        )
        units.extend(
            _flow_units_from_l205_minimal_link_keys(
                df,
                result,
                engagement_salt=engagement_salt,
            )
        )

    units.sort(key=lambda unit: (unit.unit_type, unit.unit_id))
    return units


def _flow_units_from_l202_minimal_link_keys(
    df: pd.DataFrame,
    result: DetectionResult,
    *,
    engagement_salt: str = "",
) -> list[FlowUnit]:
    row_positions = _positive_rule_positions(df, result, "L2-02")
    if not row_positions:
        return []
    annotation_units = _l202_flow_units_from_annotations(
        df,
        result,
        row_positions,
        engagement_salt=engagement_salt,
    )
    if annotation_units:
        return annotation_units
    doc_rows = _l202_document_rows(df, row_positions)
    if doc_rows.empty:
        return []

    units: list[FlowUnit] = []
    for _, group in doc_rows.groupby("_link_group", sort=True):
        member_document_ids = sorted(set(group["document_id"].astype(str)))
        if len(member_document_ids) < 2:
            continue
        if _l202_is_regular_repetition(group):
            continue
        if not (
            group["reference_norm"].astype(str).ne("").any()
            and group["reference_norm"].nunique(dropna=False) == 1
        ):
            continue
        link_key = {
            "rule_id": "L2-02",
            "partner_key": str(group["partner_key"].iloc[0]),
            "amount_bucket_minor": int(group["amount_bucket_minor"].iloc[0]),
            "period_bucket": str(group["period_bucket"].iloc[0]),
            "reference_norm": str(group["reference_norm"].iloc[0]),
            "document_type": str(group["document_type_norm"].iloc[0]),
        }
        flow_type = "duplicate_payment"
        flow_id = _deterministic_flow_id(
            company_id=_flow_company_scope(df),
            rule_id="L2-02",
            flow_type=flow_type,
            link_key=link_key,
            member_document_ids=member_document_ids,
        )
        positions = sorted({pos for values in group["row_positions"] for pos in values})
        units.append(
            FlowUnit(
                unit_id=flow_id,
                flow_id=flow_id,
                flow_type=flow_type,
                link_key=link_key,
                member_document_ids=member_document_ids,
                evidence_rows=_flow_evidence_rows(
                    df,
                    result,
                    rule_id="L2-02",
                    row_positions=positions,
                    engagement_salt=engagement_salt,
                ),
                artifact_completeness="complete",
                truncated=False,
                cap_reason=None,
                source_artifact_schema="l202_minimal_link_key.v1",
                candidate_count=1,
                retained_count=1,
                member_count=len(member_document_ids),
                measurement_eligible=True,
            )
        )
    return units


def _l202_flow_units_from_annotations(
    df: pd.DataFrame,
    result: DetectionResult,
    row_positions: list[int],
    *,
    engagement_salt: str = "",
) -> list[FlowUnit]:
    annotations_by_rule = (result.metadata or {}).get("row_annotations")
    if not isinstance(annotations_by_rule, dict):
        return []
    annotations = annotations_by_rule.get("L2-02")
    if not isinstance(annotations, dict) or not annotations:
        return []
    doc_positions = _document_positions_map(df)
    scoped_positions = set(row_positions)
    entries: list[dict[str, Any]] = []
    for row_label, annotation in annotations.items():
        if not isinstance(annotation, dict):
            continue
        row_pos = _position_from_index_label(df, row_label)
        if row_pos is None or row_pos not in scoped_positions:
            continue
        doc_id = _document_id_at_position(df, row_pos)
        matched_doc = _optional_string(annotation.get("matched_document_id"))
        if not doc_id or not matched_doc or matched_doc == doc_id:
            continue
        matched_positions = doc_positions.get(matched_doc, [])
        if not matched_positions:
            continue
        member_document_ids = sorted({doc_id, matched_doc})
        link_key = {
            "rule_id": "L2-02",
            "link_source": "detector_row_annotation",
            "reason_code": _optional_string(annotation.get("reason_code")) or "",
            "partner_key": _normalize_flow_token(annotation.get("partner_key")),
            "amount_bucket_minor": _amount_minor_bucket(annotation.get("amount")),
            "matched_amount_bucket_minor": _amount_minor_bucket(annotation.get("matched_amount")),
            "day_gap": _safe_int(annotation.get("day_gap")),
            "reference_norm": _normalize_flow_token(annotation.get("reference_norm")),
            "matched_reference_norm": _normalize_flow_token(
                annotation.get("matched_reference_norm")
            ),
        }
        entries.append(
            {
                "member_document_ids": member_document_ids,
                "row_positions": sorted({row_pos, *matched_positions}),
                "link_key": link_key,
            }
        )

    units: list[FlowUnit] = []
    seen: set[tuple[str, ...]] = set()
    for entry in entries:
        member_document_ids = entry["member_document_ids"]
        doc_key = tuple(member_document_ids)
        if doc_key in seen:
            continue
        seen.add(doc_key)
        flow_type = "duplicate_payment"
        flow_id = _deterministic_flow_id(
            company_id=_flow_company_scope(df),
            rule_id="L2-02",
            flow_type=flow_type,
            link_key=entry["link_key"],
            member_document_ids=member_document_ids,
        )
        units.append(
            FlowUnit(
                unit_id=flow_id,
                flow_id=flow_id,
                flow_type=flow_type,
                link_key=entry["link_key"],
                member_document_ids=member_document_ids,
                evidence_rows=_flow_evidence_rows(
                    df,
                    result,
                    rule_id="L2-02",
                    row_positions=entry["row_positions"],
                    engagement_salt=engagement_salt,
                ),
                artifact_completeness="complete",
                truncated=False,
                cap_reason=None,
                source_artifact_schema="l202_detector_annotation_link_key.v1",
                candidate_count=1,
                retained_count=1,
                member_count=len(member_document_ids),
                measurement_eligible=True,
            )
        )
    return units


def _l202_document_rows(df: pd.DataFrame, row_positions: list[int]) -> pd.DataFrame:
    required = {"document_id", "posting_date", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    scoped = df.iloc[row_positions].copy()
    if "business_process" in scoped.columns:
        scoped = scoped[scoped["business_process"].fillna("").astype(str).str.upper().eq("P2P")]
    if "document_type" in scoped.columns:
        scoped = scoped[
            scoped["document_type"].fillna("").astype(str).str.upper().isin({"KZ", "KR"})
        ]
    if scoped.empty:
        return pd.DataFrame()
    partner_key = _l202_partner_key(scoped)
    scoped = scoped.loc[partner_key.ne("")].copy()
    if scoped.empty:
        return pd.DataFrame()
    scoped["_partner_key"] = partner_key.loc[scoped.index]
    scoped["_base_amount"] = _base_amount_series(scoped)
    scoped["_row_position"] = [_position_from_index_label(df, index) for index in scoped.index]
    scoped = scoped[scoped["_row_position"].notna()]
    if scoped.empty:
        return pd.DataFrame()

    group_cols = ["document_id"]
    agg_spec: dict[str, Any] = {
        "posting_date": ("posting_date", "min"),
        "partner_key": ("_partner_key", "first"),
        "amount": ("_base_amount", "sum"),
        "row_positions": ("_row_position", lambda values: sorted(int(value) for value in values)),
    }
    for column in ("company_code", "reference", "document_type", "source", "business_process"):
        if column in scoped.columns:
            agg_spec[column] = (column, "first")
    docs = scoped.groupby(group_cols, sort=False).agg(**agg_spec).reset_index()
    docs["posting_date"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs = docs.dropna(subset=["posting_date"])
    docs["reference_norm"] = docs.get("reference", pd.Series("", index=docs.index)).map(
        _normalize_flow_token
    )
    docs["document_type_norm"] = docs.get("document_type", pd.Series("", index=docs.index)).map(
        _normalize_flow_token
    )
    docs["source_norm"] = docs.get("source", pd.Series("", index=docs.index)).map(
        lambda value: str(value or "").strip().lower()
    )
    docs["amount_bucket_minor"] = docs["amount"].map(_amount_minor_bucket)
    window_days = max(int(getattr(_FLOW_SETTINGS, "duplicate_payment_window_days", 90)), 1)
    docs["period_bucket"] = (
        (docs["posting_date"].astype("int64") // (window_days * 24 * 60 * 60 * 1_000_000_000))
        .astype("int64")
        .astype(str)
    )
    docs["_link_group"] = (
        docs[
            [
                "partner_key",
                "amount_bucket_minor",
                "period_bucket",
                "reference_norm",
                "document_type_norm",
            ]
        ]
        .astype(str)
        .agg("\x1f".join, axis=1)
    )
    return docs


def _l202_partner_key(df: pd.DataFrame) -> pd.Series:
    result = pd.Series("", index=df.index, dtype="object")
    for column in (
        "auxiliary_account_number",
        "trading_partner",
        "vendor_id",
        "vendor_name",
        "counterparty_code",
        "counterparty_name",
    ):
        if column not in df.columns:
            continue
        values = df[column].fillna("").astype(str).str.strip()
        result = result.where(result.ne(""), values)
    return result.map(_normalize_flow_token)


def _l202_is_regular_repetition(group: pd.DataFrame) -> bool:
    if len(group) < int(getattr(_FLOW_SETTINGS, "duplicate_recurring_min_series_length", 3)):
        return False
    if group["reference_norm"].nunique(dropna=False) <= 1:
        return False
    ordered = group.sort_values("posting_date")
    gaps = ordered["posting_date"].diff().dt.days.dropna()
    if len(gaps) < 2:
        return False
    min_days = int(getattr(_FLOW_SETTINGS, "duplicate_recurring_min_interval_days", 21))
    max_days = int(getattr(_FLOW_SETTINGS, "duplicate_recurring_max_interval_days", 100))
    if not bool(gaps.between(min_days, max_days).all()):
        return False
    mean_gap = float(gaps.mean())
    if mean_gap <= 0:
        return False
    cv = float(gaps.std(ddof=0) / mean_gap)
    threshold = float(getattr(_FLOW_SETTINGS, "duplicate_recurring_interval_cv_threshold", 0.20))
    return cv <= threshold


def _flow_units_from_l205_minimal_link_keys(
    df: pd.DataFrame,
    result: DetectionResult,
    *,
    engagement_salt: str = "",
) -> list[FlowUnit]:
    row_positions = _positive_rule_positions(df, result, "L2-05")
    if not row_positions:
        return []
    units: list[FlowUnit] = []
    seen_doc_sets: set[tuple[str, ...]] = set()
    # Why: 세 빌더(structural→one_to_one→rolling)가 같은 L2-05 역분개 문서를 각각 별도 flow로
    #      만들 수 있다. seen_doc_sets는 완전 동일 집합만 dedup하므로 부분 겹침(한 문서가 두 flow에)을
    #      못 막아 단위 disjoint를 깬다(예: one_to_one {A,B} + rolling {A,B,C} → A,B 중복). 문서 단위
    #      seen_documents로, 이미 다른 reversal flow에 흡수된 문서를 포함하는 후속 flow는 skip한다
    #      (우선순위: structural > one_to_one > rolling). 한 문서는 단일 primary flow로만 흡수.
    seen_documents: set[str] = set()
    for builder in (
        _l205_structural_pairs,
        _l205_one_to_one_pairs,
        _l205_rolling_zero_out_sets,
    ):
        for entry in builder(df, row_positions):
            doc_key = tuple(entry["member_document_ids"])
            if doc_key in seen_doc_sets:
                continue
            if set(entry["member_document_ids"]) & seen_documents:
                continue
            unit = _l205_flow_unit_from_entry(
                df,
                result,
                entry,
                engagement_salt=engagement_salt,
            )
            if unit is None:
                continue
            seen_doc_sets.add(tuple(unit.member_document_ids))
            seen_documents |= set(unit.member_document_ids)
            units.append(unit)
    return units


def _l205_structural_pairs(df: pd.DataFrame, row_positions: list[int]) -> list[dict[str, Any]]:
    if "document_id" not in df.columns:
        return []
    scoped_positions = set(row_positions)
    doc_positions = _document_positions_map(df)
    entries: list[dict[str, Any]] = []
    for row_pos in row_positions:
        doc_id = _document_id_at_position(df, row_pos)
        if not doc_id:
            continue
        for column in _REVERSAL_REFERENCE_COLUMNS:
            if column not in df.columns:
                continue
            ref_doc = _optional_string(df[column].iat[row_pos])
            if not ref_doc or ref_doc == doc_id or ref_doc not in doc_positions:
                continue
            other_positions = doc_positions[ref_doc]
            if not scoped_positions.intersection(other_positions):
                continue
            member_document_ids = sorted({doc_id, ref_doc})
            if len(member_document_ids) < 2:
                continue
            entries.append(
                {
                    "link_type": "structural_reference",
                    "member_document_ids": member_document_ids,
                    "row_positions": sorted({row_pos, *other_positions}),
                    "reference_column": column,
                    "reference_direction": f"{doc_id}->{ref_doc}",
                    "link_key": {
                        "rule_id": "L2-05",
                        "link_type": "structural_reference",
                        "reference_column": column,
                        "reference_document_pair": member_document_ids,
                    },
                }
            )
    return _dedupe_flow_entries(entries)


def _l205_one_to_one_pairs(df: pd.DataFrame, row_positions: list[int]) -> list[dict[str, Any]]:
    required = {"document_id", "gl_account", "posting_date", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        return []
    docs = _l205_document_rows(df, row_positions)
    if docs.empty:
        return []
    positives = docs[docs["net"].gt(0)]
    negatives = docs[docs["net"].lt(0)]
    if positives.empty or negatives.empty:
        return []
    window_days = int(getattr(_FLOW_SETTINGS, "reversal_mirror_window_days", 45))
    entries: list[dict[str, Any]] = []
    merged = positives.merge(
        negatives,
        on=["gl_account", "abs_amount"],
        suffixes=("_pos", "_neg"),
    )
    for row in merged.itertuples(index=False):
        pos_doc = str(row.document_id_pos)
        neg_doc = str(row.document_id_neg)
        if pos_doc == neg_doc:
            continue
        date_gap = abs((row.posting_date_pos - row.posting_date_neg).days)
        if date_gap > window_days:
            continue
        context_score = _l205_pair_context_score(row)
        if context_score < 2:
            continue
        member_document_ids = sorted({pos_doc, neg_doc})
        entries.append(
            {
                "link_type": "one_to_one_match",
                "member_document_ids": member_document_ids,
                "row_positions": sorted({*row.row_positions_pos, *row.row_positions_neg}),
                "link_key": {
                    "rule_id": "L2-05",
                    "link_type": "one_to_one_match",
                    "gl_account": str(row.gl_account),
                    "abs_amount_minor": int(row.abs_amount),
                    "date_gap_days": int(date_gap),
                    "context_score": int(context_score),
                    "reference_norm": str(row.reference_norm_pos)
                    if str(row.reference_norm_pos) == str(row.reference_norm_neg)
                    else "",
                },
            }
        )
    return _dedupe_flow_entries(entries)


def _l205_rolling_zero_out_sets(df: pd.DataFrame, row_positions: list[int]) -> list[dict[str, Any]]:
    required = {"document_id", "gl_account", "posting_date", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        return []
    docs = _l205_document_rows(df, row_positions)
    if docs.empty:
        return []
    threshold = float(getattr(_FLOW_SETTINGS, "reversal_zero_threshold", 1000.0))
    window_days = int(getattr(_FLOW_SETTINGS, "reversal_rolling_window_days", 7))
    entries: list[dict[str, Any]] = []
    group_cols = ["gl_account", "created_by_norm"]
    for _, group in docs.groupby(group_cols, sort=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date").reset_index(drop=True)
        for left in range(len(ordered)):
            for right in range(left + 1, len(ordered)):
                window = ordered.iloc[left : right + 1]
                day_span = int((window["posting_date"].max() - window["posting_date"].min()).days)
                if day_span > window_days:
                    break
                if window["document_id"].nunique() < 2:
                    continue
                if not (window["net"].gt(0).any() and window["net"].lt(0).any()):
                    continue
                net = float(window["net"].sum())
                gross = float(window["gross"].sum())
                if gross <= 0 or abs(net) > threshold or abs(net) / gross >= 0.05:
                    continue
                if _l205_window_context_score(window) < 2:
                    continue
                member_document_ids = sorted(set(window["document_id"].astype(str)))
                entries.append(
                    {
                        "link_type": "rolling_zero_out_set",
                        "member_document_ids": member_document_ids,
                        "row_positions": sorted(
                            {pos for values in window["row_positions"] for pos in values}
                        ),
                        "link_key": {
                            "rule_id": "L2-05",
                            "link_type": "rolling_zero_out_set",
                            "gl_account": str(window["gl_account"].iloc[0]),
                            "created_by_norm": str(window["created_by_norm"].iloc[0]),
                            "period_start": _date_string(window["posting_date"].min()),
                            "period_end": _date_string(window["posting_date"].max()),
                            "net_minor": _amount_minor_bucket(net),
                        },
                    }
                )
                break
    return _dedupe_flow_entries(entries)


def _l205_document_rows(df: pd.DataFrame, row_positions: list[int]) -> pd.DataFrame:
    scoped = df.iloc[row_positions].copy()
    scoped["_row_position"] = [_position_from_index_label(df, index) for index in scoped.index]
    scoped = scoped[scoped["_row_position"].notna()]
    if scoped.empty:
        return pd.DataFrame()
    scoped["_net"] = _net_amount_series(scoped)
    scoped["_gross"] = _gross_amount_series(scoped)
    agg_spec: dict[str, Any] = {
        "posting_date": ("posting_date", "min"),
        "net": ("_net", "sum"),
        "gross": ("_gross", "sum"),
        "row_positions": ("_row_position", lambda values: sorted(int(value) for value in values)),
    }
    for column in (
        "created_by",
        "reference",
        "document_type",
        "source",
        "line_text",
        "header_text",
    ):
        if column in scoped.columns:
            agg_spec[column] = (column, "first")
    docs = scoped.groupby(["document_id", "gl_account"], sort=False).agg(**agg_spec).reset_index()
    docs["posting_date"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs = docs.dropna(subset=["posting_date"])
    docs["abs_amount"] = docs["net"].abs().map(_amount_minor_bucket)
    docs["created_by_norm"] = docs.get("created_by", pd.Series("", index=docs.index)).map(
        _normalize_flow_token
    )
    docs["reference_norm"] = docs.get("reference", pd.Series("", index=docs.index)).map(
        _normalize_flow_token
    )
    docs["document_type_norm"] = docs.get("document_type", pd.Series("", index=docs.index)).map(
        _normalize_flow_token
    )
    docs["line_text_norm"] = docs.get("line_text", pd.Series("", index=docs.index)).map(
        _normalize_flow_text
    )
    docs["header_text_norm"] = docs.get("header_text", pd.Series("", index=docs.index)).map(
        _normalize_flow_text
    )
    return docs[docs["net"].ne(0.0)]


def _l205_pair_context_score(row: Any) -> int:
    score = 0
    if str(row.reference_norm_pos) and str(row.reference_norm_pos) == str(row.reference_norm_neg):
        score += 2
    if str(row.created_by_norm_pos) and str(row.created_by_norm_pos) == str(
        row.created_by_norm_neg
    ):
        score += 1
    if str(row.document_type_norm_pos) and str(row.document_type_norm_pos) == str(
        row.document_type_norm_neg
    ):
        score += 1
    if str(row.line_text_norm_pos) and str(row.line_text_norm_pos) == str(row.line_text_norm_neg):
        score += 1
    if str(row.header_text_norm_pos) and str(row.header_text_norm_pos) == str(
        row.header_text_norm_neg
    ):
        score += 1
    return score


def _l205_window_context_score(window: pd.DataFrame) -> int:
    score = 0
    for column, weight in (
        ("reference_norm", 2),
        ("created_by_norm", 1),
        ("document_type_norm", 1),
        ("line_text_norm", 1),
    ):
        values = {str(value) for value in window[column].tolist() if str(value)}
        if len(values) == 1:
            score += weight
    return score


def _l205_flow_unit_from_entry(
    df: pd.DataFrame,
    result: DetectionResult,
    entry: dict[str, Any],
    *,
    engagement_salt: str = "",
) -> FlowUnit | None:
    member_document_ids = sorted(str(value) for value in entry["member_document_ids"] if str(value))
    if len(member_document_ids) < 2:
        return None
    link_key = _json_stable(entry["link_key"])
    flow_type = "reversal"
    flow_id = _deterministic_flow_id(
        company_id=_flow_company_scope(df),
        rule_id="L2-05",
        flow_type=flow_type,
        link_key=link_key,
        member_document_ids=member_document_ids,
    )
    row_positions = sorted({pos for pos in entry["row_positions"] if 0 <= pos < len(df)})
    return FlowUnit(
        unit_id=flow_id,
        flow_id=flow_id,
        flow_type=flow_type,
        link_key=link_key,
        member_document_ids=member_document_ids,
        evidence_rows=_flow_evidence_rows(
            df,
            result,
            rule_id="L2-05",
            row_positions=row_positions,
            engagement_salt=engagement_salt,
        ),
        artifact_completeness="complete",
        truncated=False,
        cap_reason=None,
        source_artifact_schema="l205_minimal_link_key.v1",
        candidate_count=1,
        retained_count=1,
        member_count=len(member_document_ids),
        measurement_eligible=True,
    )


def _dedupe_flow_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    deduped: list[dict[str, Any]] = []
    for entry in entries:
        key = (str(entry.get("link_type")), tuple(entry.get("member_document_ids") or []))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _positive_rule_positions(df: pd.DataFrame, result: DetectionResult, rule_id: str) -> list[int]:
    flag_series = _rule_flag_series(result, rule_id)
    if flag_series is not None:
        flags = flag_series.reindex(df.index, fill_value=False).astype(bool)
        positions = [int(pos) for pos, value in enumerate(flags.tolist()) if bool(value)]
        if positions:
            return positions
    if result.details is None or rule_id not in result.details.columns:
        return []
    scores = pd.to_numeric(result.details[rule_id].reindex(df.index), errors="coerce").fillna(0.0)
    return [int(pos) for pos, value in enumerate(scores.tolist()) if float(value) > 0.0]


def _rule_flag_series(result: DetectionResult, rule_id: str) -> pd.Series | None:
    series_frame = (result.metadata or {}).get("rule_flag_series")
    if isinstance(series_frame, pd.DataFrame) and rule_id in series_frame.columns:
        return series_frame[rule_id]
    return None


def _rule_flag_at_position(result: DetectionResult, rule_id: str, row_pos: int) -> bool:
    flag_series = _rule_flag_series(result, rule_id)
    if flag_series is None:
        return False
    try:
        return bool(flag_series.iloc[row_pos])
    except IndexError:
        return False


def _flow_units_from_duplicate_artifact(
    df: pd.DataFrame,
    result: DetectionResult,
    artifact: Any,
    *,
    engagement_salt: str = "",
) -> list[FlowUnit]:
    if not isinstance(artifact, dict):
        return []
    top_pairs = artifact.get("top_pairs") or []
    if not isinstance(top_pairs, list) or not top_pairs:
        return []

    truncated = bool(artifact.get("truncated", False))
    cap_reason = _optional_string(artifact.get("truncation_reason"))
    completeness = "bounded" if truncated else "complete"
    measurement_eligible = completeness == "complete"

    units: list[FlowUnit] = []
    for pair in top_pairs:
        if not isinstance(pair, dict):
            continue
        left_doc = _optional_string(pair.get("left_document_id"))
        right_doc = _optional_string(pair.get("right_document_id"))
        member_document_ids = sorted({doc for doc in (left_doc, right_doc) if doc})
        if len(member_document_ids) < 2:
            continue
        row_positions = _artifact_positions_from_pair(df, pair)
        link_key = {
            "rule_id": "L2-03",
            "pair_rule_id": _optional_string(pair.get("rule_id")) or "L2-03",
            "rule_source": _optional_string(pair.get("rule_source")) or "",
            "pair_score": _safe_float(pair.get("pair_score")),
            "features": _json_stable(
                pair.get("features") if isinstance(pair.get("features"), dict) else {}
            ),
        }
        flow_type = "duplicate_entry"
        flow_id = _deterministic_flow_id(
            company_id=_flow_company_scope(df),
            rule_id="L2-03",
            flow_type=flow_type,
            link_key=link_key,
            member_document_ids=member_document_ids,
        )
        units.append(
            FlowUnit(
                unit_id=flow_id,
                flow_id=flow_id,
                flow_type=flow_type,
                link_key=link_key,
                member_document_ids=member_document_ids,
                evidence_rows=_flow_evidence_rows(
                    df,
                    result,
                    rule_id="L2-03",
                    row_positions=row_positions,
                    engagement_salt=engagement_salt,
                ),
                artifact_completeness=completeness,
                truncated=truncated,
                cap_reason=cap_reason,
                source_artifact_schema=f"duplicate_pair_artifact.v{artifact.get('schema_version', 1)}",
                candidate_count=1,
                retained_count=1,
                member_count=len(member_document_ids),
                measurement_eligible=measurement_eligible,
            )
        )
    return units


def _flow_evidence_rows(
    df: pd.DataFrame,
    result: DetectionResult,
    *,
    rule_id: str,
    row_positions: list[int],
    engagement_salt: str = "",
) -> list[RawRuleHitRef]:
    if not row_positions:
        return []
    details = result.details if result.details is not None else pd.DataFrame(index=df.index)
    detail_rule_ids = _flow_detail_rule_ids(rule_id, details)
    if not detail_rule_ids:
        return []
    severity = _rule_flag_severity(result, rule_id)
    evidence_type = _flow_evidence_type(rule_id)
    refs: list[RawRuleHitRef] = []
    has_salt = bool(engagement_salt and engagement_salt.strip())
    has_line_number = has_salt and "line_number" in df.columns
    has_company_code = has_salt and "company_code" in df.columns
    for row_pos in sorted({pos for pos in row_positions if 0 <= pos < len(df)}):
        score = max(
            _safe_float(details[detail_rule_id].iat[row_pos]) for detail_rule_id in detail_rule_ids
        )
        if score <= 0 and not _rule_flag_at_position(result, rule_id, row_pos):
            continue
        document_id = _document_id_at_position(df, row_pos) or f"row-{row_pos}"
        canonical_label_hash = ""
        doc_id_hash = ""
        company_code_hash = ""
        line_number_key: str | None = None
        if has_salt:
            canonical_label = canonicalize_ref_key(df.index[row_pos])
            canonical_label_hash = hash_ref_key(canonical_label, salt=engagement_salt)
            doc_id_hash = hash_ref_key(document_id, salt=engagement_salt)
            if has_company_code:
                company_code_value = df["company_code"].iat[row_pos]
                if company_code_value is not None and not pd.isna(company_code_value):
                    company_code_str = str(company_code_value)
                    if company_code_str:
                        company_code_hash = hash_ref_key(company_code_str, salt=engagement_salt)
            if has_line_number:
                candidate = canonicalize_ref_key(df["line_number"].iat[row_pos])
                line_number_key = None if candidate == "n:" else candidate
        refs.append(
            RawRuleHitRef(
                rule_id=rule_id,
                severity=severity,
                document_id=document_id,
                row_index=row_pos,
                record_id=_record_id_at_position(df, row_pos),
                score=score,
                signal_strength=score,
                normalized_score=score,
                evidence_strength="medium",
                scoring_role="primary",
                display_label="",
                signal_status="confirmed",
                detail=None,
                evidence_type=evidence_type,
                canonical_label_hash=canonical_label_hash,
                doc_id_hash=doc_id_hash,
                line_number_key=line_number_key,
                company_code_hash=company_code_hash,
            )
        )
    return refs


def _flow_detail_rule_ids(rule_id: str, details: pd.DataFrame) -> list[str]:
    if rule_id == "L2-03":
        return [
            candidate for candidate in _DUPLICATE_DETAIL_RULE_IDS if candidate in details.columns
        ]
    return [rule_id] if rule_id in details.columns else []


def _document_positions_map(df: pd.DataFrame) -> dict[str, list[int]]:
    mapping: dict[str, list[int]] = defaultdict(list)
    if "document_id" not in df.columns:
        return mapping
    for pos, value in enumerate(df["document_id"].tolist()):
        doc_id = _optional_string(value)
        if doc_id:
            mapping[doc_id].append(pos)
    return {key: sorted(values) for key, values in mapping.items()}


def _base_amount_series(df: pd.DataFrame) -> pd.Series:
    debit = pd.to_numeric(
        df.get("debit_amount", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    credit = pd.to_numeric(
        df.get("credit_amount", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    return pd.concat([debit.abs(), credit.abs()], axis=1).max(axis=1)


def _net_amount_series(df: pd.DataFrame) -> pd.Series:
    debit = pd.to_numeric(
        df.get("debit_amount", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    credit = pd.to_numeric(
        df.get("credit_amount", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    return debit - credit


def _gross_amount_series(df: pd.DataFrame) -> pd.Series:
    debit = pd.to_numeric(
        df.get("debit_amount", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    credit = pd.to_numeric(
        df.get("credit_amount", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    return debit.abs() + credit.abs()


def _amount_minor_bucket(value: Any) -> int:
    return int(round(_safe_float(value) * 100))


def _normalize_flow_token(value: Any) -> str:
    text = _string_value(value).lower()
    return "".join(char for char in text if char.isalnum())


def _normalize_flow_text(value: Any) -> str:
    text = _string_value(value).lower()
    compact = [" " if not char.isalnum() else char for char in text]
    return " ".join("".join(compact).split())


def _deterministic_flow_id(
    *,
    company_id: str,
    rule_id: str,
    flow_type: str,
    link_key: dict[str, Any],
    member_document_ids: list[str],
) -> str:
    payload = {
        "schema": _FLOW_ID_SCHEMA_VERSION,
        "company": company_id,
        "rule_id": rule_id,
        "flow_type": flow_type,
        "link_key": _json_stable(link_key),
        "member_document_ids": sorted(str(value) for value in member_document_ids),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"{_FLOW_ID_SCHEMA_VERSION}_{flow_type}_{digest}"


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _json_stable(value[key]) for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_json_stable(item) for item in value]
    if isinstance(value, tuple):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return None if value != value else float(value)
    if hasattr(value, "item"):
        try:
            return _json_stable(value.item())
        except Exception:
            return str(value)
    return str(value)


def _artifact_positions_from_pair(df: pd.DataFrame, pair: dict[str, Any]) -> list[int]:
    positions: list[int] = []
    for key in ("left_position", "right_position"):
        pos = _safe_int(pair.get(key), default=-1)
        if 0 <= pos < len(df):
            positions.append(pos)
    if positions:
        return positions
    for key in ("left_index", "right_index"):
        pos = _position_from_index_label(df, pair.get(key))
        if pos is not None:
            positions.append(pos)
    return sorted(set(positions))


def _position_from_index_label(df: pd.DataFrame, label: Any) -> int | None:
    if label in df.index:
        loc = df.index.get_loc(label)
        if isinstance(loc, int):
            return int(loc)
    try:
        pos = int(label)
    except (TypeError, ValueError):
        return None
    return pos if 0 <= pos < len(df) else None


def _member_documents_from_positions(df: pd.DataFrame, positions: list[int]) -> list[str]:
    docs = {_document_id_at_position(df, pos) for pos in positions if 0 <= pos < len(df)}
    return sorted(doc for doc in docs if doc)


def _document_id_at_position(df: pd.DataFrame, row_pos: int) -> str:
    if "document_id" not in df.columns or not (0 <= row_pos < len(df)):
        return ""
    return _optional_string(df["document_id"].iat[row_pos]) or ""


def _record_id_at_position(df: pd.DataFrame, row_pos: int) -> str | None:
    if "record_id" not in df.columns or not (0 <= row_pos < len(df)):
        return None
    return _optional_string(df["record_id"].iat[row_pos])


_FLOW_COMPANY_SCOPE_CACHE: tuple[Any, str] | None = None


def _flow_company_scope(df: pd.DataFrame) -> str:
    # Why(성능): 결과는 df의 company_code 에만 의존(group·호출처 무관). flow 빌더 루프들이 group/entry
    #      마다 이 함수를 호출해 910k 행 전체를 매번 스캔(O(groups×n) = 수십 분 병목, recall v42j_r3
    #      L2-02 21,572 hit 케이스에서 build_flow_units 30분+). 같은 df 객체면 1회만 계산해 재사용한다.
    #      weakref 키로 '동일 살아있는 객체'일 때만 캐시 히트 — df 가 GC 되면 ref()가 None 이 되어
    #      cross-build id 재사용에도 stale 값을 반환하지 않는다(동작 100% 보존).
    global _FLOW_COMPANY_SCOPE_CACHE
    import weakref as _weakref

    if _FLOW_COMPANY_SCOPE_CACHE is not None:
        _ref, _val = _FLOW_COMPANY_SCOPE_CACHE
        if _ref() is df:
            return _val
    if "company_code" not in df.columns or df.empty:
        result = ""
    else:
        values = sorted(
            {
                value
                for value in (_optional_string(item) for item in df["company_code"].tolist())
                if value
            }
        )
        result = "|".join(values[:10])
    try:
        _FLOW_COMPANY_SCOPE_CACHE = (_weakref.ref(df), result)
    except TypeError:
        _FLOW_COMPANY_SCOPE_CACHE = None
    return result


def _rule_flag_severity(result: DetectionResult, rule_id: str) -> int:
    for flag in result.rule_flags:
        if str(flag.rule_id) == rule_id:
            return int(flag.severity)
    return int(SEVERITY_MAP.get(rule_id, 3))


def _flow_evidence_type(rule_id: str) -> str:
    metadata = RULE_SCORING_REGISTRY.get(rule_id)
    if metadata is not None:
        return str(metadata.evidence_type)
    return "flow_evidence"


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if result != result else result


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [_safe_int(item, default=-1) for item in value]


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
                theme_label=_topic_label(theme_id),
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
    *,
    indices: list[int] | None = None,
    macro_index: dict[str, Any] | None = None,
    macro_row_context: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    if rows.empty or not macro_findings or "gl_account" not in rows.columns:
        return []
    if indices is not None and macro_index is not None and macro_row_context is not None:
        return _case_macro_contexts_from_index(indices, macro_index, macro_row_context)

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
        # GR01/GR03 제거(2026-06-21): graph macro finding 미생성이라 D01/D02 만 macro_context 부착.
        if rule_id not in {"D01", "D02"}:
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
        contexts.append(
            {
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
            }
        )
    contexts.sort(
        key=lambda item: (
            float(item.get("macro_priority_score") or 0.0),
            str(item.get("rule_id") or ""),
        ),
        reverse=True,
    )
    return contexts


def _build_macro_context_index(macro_findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in macro_findings:
        rule_id = str(finding.get("rule_id") or "")
        # macro_context 부착 대상은 D01/D02 만 (2026-06-14): GR01/GR03 제거(PHASE2 family),
        # L4-02(Benford)는 모집단 신호로 거래 case 부착 제외(부착 시 broad fan-out OOM).
        if rule_id not in {"D01", "D02"}:
            continue
        macro_account = _macro_key_part(finding.get("gl_account"))
        if not macro_account:
            continue
        context = _macro_context_from_finding(finding, rule_id, macro_account)
        for value in finding.get("document_ids", []) or []:
            document_id = _string_value(value)
            if document_id:
                by_doc[document_id].append(context)
        by_account[macro_account].append(context)
    return {"by_doc": by_doc, "by_account": by_account}


def _build_macro_row_context(df: pd.DataFrame) -> dict[str, list[str]]:
    def _column_values(column: str) -> list[str]:
        if column not in df.columns:
            return [""] * len(df)
        return [_macro_key_part(value) for value in df[column].tolist()]

    document_ids = (
        [_string_value(value) for value in df["document_id"].tolist()]
        if "document_id" in df.columns
        else [""] * len(df)
    )
    return {
        "document_id": document_ids,
        "year": _column_values("fiscal_year"),
        "company": _column_values("company_code"),
        "account": _column_values("gl_account"),
    }


def _case_macro_contexts_from_index(
    indices: list[int],
    macro_index: dict[str, Any],
    macro_row_context: dict[str, list[str]],
) -> list[dict[str, Any]]:
    by_doc = macro_index.get("by_doc", {})
    by_account = macro_index.get("by_account", {})
    documents = macro_row_context["document_id"]
    years = macro_row_context["year"]
    companies = macro_row_context["company"]
    accounts = macro_row_context["account"]

    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_index in indices:
        document_id = documents[row_index]
        if document_id:
            _append_macro_contexts(contexts, seen, by_doc.get(document_id, ()))
        row_key = (years[row_index], companies[row_index], accounts[row_index])
        if row_key[2]:
            for context in by_account.get(row_key[2], ()):
                macro_key = (
                    str(context.get("_macro_year") or ""),
                    str(context.get("_macro_company") or ""),
                    str(context.get("_macro_account") or ""),
                )
                if _macro_key_matches(row_key, macro_key):
                    _append_macro_contexts(contexts, seen, (context,))
    contexts.sort(
        key=lambda item: (
            float(item.get("macro_priority_score") or 0.0),
            str(item.get("rule_id") or ""),
        ),
        reverse=True,
    )
    return [_public_macro_context(context) for context in contexts]


def _append_macro_contexts(
    contexts: list[dict[str, Any]],
    seen: set[str],
    candidates,
) -> None:
    for context in candidates:
        context_id = str(context.get("finding_id") or "")
        if context_id in seen:
            continue
        seen.add(context_id)
        contexts.append(context)


def _macro_context_from_finding(
    finding: dict[str, Any],
    rule_id: str,
    macro_account: str,
) -> dict[str, Any]:
    context_id = str(finding.get("finding_id") or f"{rule_id}:{macro_account}")
    return {
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
        "_macro_year": _macro_key_part(finding.get("fiscal_year")),
        "_macro_company": _macro_key_part(finding.get("company_code")),
        "_macro_account": macro_account,
    }


def _public_macro_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if not str(key).startswith("_macro_")}


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


# Why: #20① — macro_context 의 scoring_effect 를 topic_scoring macro_context_score 의
# normalized_score 로 환산. confirmed=1.0(full), corroborated=0.67(weak), context_only=0
# (정보성 부착만). 가중치 0.03 과 곱해져 최대 기여 0.03 으로 bounded — macro 단독 seed 불가.
_MACRO_SCORING_EFFECT_SCORE: dict[str, float] = {
    "priority_booster": 1.0,
    "weak_priority_booster": 0.67,
}


def _macro_only_evidences(macro_contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """macro_context 를 compute_topic_scores 용 macro_only evidence 로 변환 (#20①).

    final_topic/secondary/standalone_rankable 은 RULE_SCORING_REGISTRY 에서 해소되도록
    rule_id 만 넘긴다. score 0(context_only) evidence 도 포함 — circular 콤보의 graph_cycle
    감지(#20③)가 점수 무관하게 GR01/GR03 존재를 보게 하기 위함.
    """
    evidences: list[dict[str, Any]] = []
    for context in macro_contexts:
        rule_id = str(context.get("rule_id") or "")
        if not rule_id:
            continue
        score = _MACRO_SCORING_EFFECT_SCORE.get(str(context.get("scoring_effect") or ""), 0.0)
        evidences.append(
            {
                "rule_id": rule_id,
                "scoring_role": "macro_only",
                "normalized_score": score,
            }
        )
    return evidences


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


def _build_case_key_context(
    df: pd.DataFrame,
    line_amounts: pd.Series,
    config: dict[str, Any],
    row_indices: list[int],
) -> dict[str, Any]:
    work = df.iloc[row_indices]
    row_pos = {row_index: pos for pos, row_index in enumerate(row_indices)}
    posting = (
        pd.to_datetime(work["posting_date"], errors="coerce")
        if "posting_date" in work.columns
        else None
    )
    posting_month = (
        posting.dt.strftime("%Y-%m").fillna("UNKNOWN_MONTH").tolist()
        if posting is not None
        else ["UNKNOWN_MONTH"] * len(work)
    )
    is_period_end = (
        bool_column(work, "is_period_end").tolist()
        if "is_period_end" in work.columns
        else [False] * len(work)
    )
    return {
        "_row_pos": row_pos,
        "posting_month": posting_month,
        "period_window": _period_end_window_values(
            posting,
            is_period_end,
            int(config.get("period_end_window_days", 5)),
            len(work),
        ),
        "near_period": _near_period_bucket_values(
            posting,
            int(config.get("near_period_days", 7)),
            len(work),
        ),
        "created_by": _string_column(work, "created_by"),
        "business_process": _string_column(work, "business_process"),
        "user_persona": _string_column(work, "user_persona"),
        "document_type": _string_column(work, "document_type"),
        "company_code": _string_column(work, "company_code"),
        "account_family": _account_family_values(work, config),
        "counterparty": _counterparty_values(work, config),
        "company_pair": _company_pair_values(work, config),
        "amount_band": _amount_band_values(line_amounts.iloc[row_indices]),
        "load_batch": _load_batch_values(work, config),
    }


def _make_case_key_parts_from_context(
    theme_id: str,
    row_index: int,
    context: dict[str, Any],
) -> dict[str, Any] | None:
    row_pos = context["_row_pos"].get(row_index)
    if row_pos is None:
        return None
    if theme_id == "control_failure":
        return {
            "created_by": context["created_by"][row_pos] or "UNKNOWN_USER",
            "business_process": context["business_process"][row_pos] or "UNKNOWN_PROCESS",
            "period_month": context["posting_month"][row_pos],
        }
    if theme_id == "access_scope_review":
        return {
            "created_by": context["created_by"][row_pos] or "UNKNOWN_USER",
            "user_persona": context["user_persona"][row_pos] or "UNKNOWN_PERSONA",
            "period_month": context["posting_month"][row_pos],
        }
    if theme_id == "timing_anomaly":
        return {
            "created_by": context["created_by"][row_pos] or "UNKNOWN_USER",
            "account_family": context["account_family"][row_pos],
            "period_window": context["period_window"][row_pos],
        }
    if theme_id == "duplicate_or_outflow":
        return {
            "counterparty": context["counterparty"][row_pos],
            "amount_band": context["amount_band"][row_pos],
            "near_period": context["near_period"][row_pos],
        }
    if theme_id == "intercompany_structure":
        return {
            "company_pair": context["company_pair"][row_pos],
            "counterparty": context["counterparty"][row_pos],
            "period_month": context["posting_month"][row_pos],
        }
    if theme_id == "statistical_outlier":
        return {
            "business_process": context["business_process"][row_pos] or "UNKNOWN_PROCESS",
            "account_family": context["account_family"][row_pos],
            "period_month": context["posting_month"][row_pos],
        }
    if theme_id == "logic_mismatch":
        return {
            "account_family": context["account_family"][row_pos],
            "document_type": context["document_type"][row_pos] or "UNKNOWN_DOCUMENT_TYPE",
            "period_month": context["posting_month"][row_pos],
        }
    return None


def _string_column(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns:
        return [""] * len(df)
    series = df[column]
    return series.astype(object).where(pd.notna(series), "").astype(str).str.strip().tolist()


def _period_end_window_values(
    posting: pd.Series | None,
    is_period_end: list[bool],
    days: int,
    length: int,
) -> list[str]:
    if posting is None:
        return ["UNKNOWN_PERIOD_WINDOW"] * length
    values: list[str] = []
    for pos, timestamp in enumerate(posting):
        if pd.isna(timestamp):
            values.append("UNKNOWN_PERIOD_WINDOW")
            continue
        if is_period_end[pos]:
            values.append(f"{timestamp.strftime('%Y-%m')}-period_end")
            continue
        month_end = timestamp + pd.offsets.MonthEnd(0)
        if abs((month_end - timestamp).days) <= days:
            values.append(f"{timestamp.strftime('%Y-%m')}-month_end_window")
        else:
            values.append(timestamp.strftime("%Y-%m"))
    return values


def _near_period_bucket_values(
    posting: pd.Series | None,
    days: int,
    length: int,
) -> list[str]:
    if posting is None:
        return ["UNKNOWN_NEAR_PERIOD"] * length
    bucket_days = max(days, 1)
    values: list[str] = []
    for timestamp in posting:
        if pd.isna(timestamp):
            values.append("UNKNOWN_NEAR_PERIOD")
            continue
        ordinal = timestamp.toordinal()
        bucket_start = ordinal - (ordinal % bucket_days)
        values.append(datetime.fromordinal(bucket_start).strftime("%Y-%m-%d"))
    return values


def _counterparty_values(df: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    fallback = str(config.get("counterparty_fallback", "UNKNOWN_COUNTERPARTY"))
    result = [""] * len(df)
    for field in config.get(
        "counterparty_columns",
        ("auxiliary_account_number", "vendor_name", "customer_name"),
    ):
        values = _string_column(df, str(field))
        for index, value in enumerate(values):
            if not result[index] and value:
                result[index] = value
    return [value or fallback for value in result]


def _account_family_values(df: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    fallback = str(config.get("account_family_fallback", "UNKNOWN_ACCOUNT_FAMILY"))
    result = [""] * len(df)
    gl_account = _string_column(df, "gl_account")
    for key in config.get(
        "account_family_fallback_order",
        ("account_family", "first_digit", "gl_account_prefix_2", "gl_account_prefix_3"),
    ):
        if key == "gl_account_prefix_2":
            values = [value[:2] if value else "" for value in gl_account]
        elif key == "gl_account_prefix_3":
            values = [value[:3] if value else "" for value in gl_account]
        else:
            values = _string_column(df, str(key))
        for index, value in enumerate(values):
            if not result[index] and value:
                result[index] = value
    return [value or fallback for value in result]


def _company_pair_values(df: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    fields = list(config.get("intercompany_pair_columns", ("company_code", "trading_partner")))
    first = _string_column(df, str(fields[0])) if fields else [""] * len(df)
    second = _string_column(df, str(fields[1])) if len(fields) > 1 else [""] * len(df)
    return [
        (left or f"UNKNOWN_{str(fields[0]).upper()}") + "+" + (right or "UNKNOWN_TRADING_PARTNER")
        for left, right in zip(first, second, strict=False)
    ]


def _amount_band_values(line_amounts: pd.Series) -> list[str]:
    values: list[str] = []
    for amount in line_amounts.to_numpy():
        if amount >= 1_000_000_000:
            values.append("1B+")
        elif amount >= 100_000_000:
            values.append("100M-1B")
        elif amount >= 10_000_000:
            values.append("10M-100M")
        else:
            values.append("<10M")
    return values


def _load_batch_values(df: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    result = [""] * len(df)
    for field in config.get("load_batch_columns", ("upload_batch_id",)):
        values = _string_column(df, str(field))
        for index, value in enumerate(values):
            if not result[index] and value:
                result[index] = value
    return [value or "UNKNOWN_BATCH" for value in result]


def _document_ref_columns(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """문서 ref 생성에 쓰는 전체 df 컬럼 캐시 — case 루프 밖에서 1회 만들어 재사용한다."""
    return {
        "posting_dates": (df["posting_date"].tolist() if "posting_date" in df.columns else None),
        "created_by": _string_column(df, "created_by"),
        "business_process": _string_column(df, "business_process"),
        "gl_account": _string_column(df, "gl_account"),
        "counterparty": _counterparty_values(df, config),
    }


def _build_document_refs(
    df: pd.DataFrame,
    hits: list[_RawHit],
    config: dict[str, Any],
    *,
    document_amounts: dict[str, float] | None = None,
    line_amounts: pd.Series | None = None,
    ref_cache: dict[tuple[str, tuple[tuple[str, int, str], ...]], CaseDocumentRef] | None = None,
    document_ref_columns: dict[str, Any] | None = None,
) -> list[CaseDocumentRef]:
    by_doc: dict[str, list[_RawHit]] = defaultdict(list)
    for hit in hits:
        by_doc[hit.document_id].append(hit)
    refs: list[CaseDocumentRef] = []
    # Why: 컬럼 캐시(전체 df 기준)는 case 루프 밖에서 1회 만들어 전달한다. case마다
    #      _build_document_refs가 전체 df를 tolist 하면 O(case 수 × 전체 행)로 폭증한다
    #      (2026-06-13 R-PERF 회귀). document_ref_columns 미전달 시에만 backward compat 생성.
    cols = (
        document_ref_columns
        if document_ref_columns is not None
        else _document_ref_columns(df, config)
    )
    posting_dates = cols["posting_dates"]
    created_by_values = cols["created_by"]
    business_process_values = cols["business_process"]
    gl_account_values = cols["gl_account"]
    counterparty_values = cols["counterparty"]
    for document_id, doc_hits in by_doc.items():
        cache_key = (
            document_id,
            tuple(sorted((hit.rule_id, hit.row_index, hit.evidence_type) for hit in doc_hits)),
        )
        if ref_cache is not None and cache_key in ref_cache:
            refs.append(ref_cache[cache_key])
            continue
        hit_positions = [hit.row_index for hit in doc_hits]
        first_pos = doc_hits[0].row_index
        ref = CaseDocumentRef(
            document_id=document_id,
            posting_date=(
                _date_string(posting_dates[first_pos]) if posting_dates is not None else None
            ),
            created_by=created_by_values[first_pos] or None,
            business_process=business_process_values[first_pos] or None,
            gl_account=gl_account_values[first_pos] or None,
            counterparty=counterparty_values[first_pos],
            amount=_document_amount(
                df,
                document_id,
                hit_positions,
                document_amounts=document_amounts,
                line_amounts=line_amounts,
            ),
            matched_rules=sorted({hit.rule_id for hit in doc_hits}),
            evidence_tags=sorted({hit.evidence_type for hit in doc_hits}),
        )
        if ref_cache is not None:
            ref_cache[cache_key] = ref
        refs.append(ref)
    refs.sort(key=lambda item: (item.posting_date or "", item.document_id))
    return refs


def _raw_rule_hit_refs(
    hits: list[_RawHit],
    cache: dict[tuple[str, int], RawRuleHitRef],
    *,
    df: pd.DataFrame | None = None,
    engagement_salt: str = "",
) -> list[RawRuleHitRef]:
    # Why: engagement_salt 가 빈 문자열 / whitespace-only 면 신규 hash 필드는
    # default(빈 값) 로 유지 — 기존 caller backward compat (invariant #71).
    # PHASE2 store 의 _is_valid_salt() 와 동일하게 strip() 후 truthy 검사 — 공백
    # 만 있는 salt 가 hash_ref_key 에 도달해 ValueError 던지는 것 차단.
    # salt 명시 시 PHASE2 row_ref_map 과 동일 공식 (invariant #70).
    has_salt = bool(engagement_salt and engagement_salt.strip())
    has_line_number = has_salt and df is not None and "line_number" in df.columns
    # Why (S6.next Phase 2): company_code_hash 산출 가드. df 에 company_code 컬럼이
    # 있어야 hit 의 회사 식별자를 동일 salt 로 hash. invariant #74.
    has_company_code = has_salt and df is not None and "company_code" in df.columns
    refs: list[RawRuleHitRef] = []
    for hit in hits:
        key = (hit.rule_id, hit.row_index)
        ref = cache.get(key)
        if ref is None:
            canonical_label_hash = ""
            doc_id_hash = ""
            company_code_hash = ""
            line_number_key: str | None = None
            if has_salt and df is not None:
                canonical_label = canonicalize_ref_key(df.index[hit.row_index])
                canonical_label_hash = hash_ref_key(canonical_label, salt=engagement_salt)
                if hit.document_id:
                    doc_id_hash = hash_ref_key(hit.document_id, salt=engagement_salt)
                if has_company_code:
                    company_code_value = df["company_code"].iat[hit.row_index]
                    # Why: NaN/None/빈 문자열은 hash 후보 제외 — PHASE2 store 의
                    # `_serialize_row_ref` 와 동일 정책 (None → row_ref_map 의
                    # company_code_hash=null).
                    if company_code_value is not None and not pd.isna(company_code_value):
                        company_code_str = str(company_code_value)
                        if company_code_str:
                            company_code_hash = hash_ref_key(company_code_str, salt=engagement_salt)
                if has_line_number:
                    raw_line = df["line_number"].iat[hit.row_index]
                    if raw_line is not None:
                        candidate = canonicalize_ref_key(raw_line)
                        line_number_key = None if candidate == "n:" else candidate
            ref = RawRuleHitRef(
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
                canonical_label_hash=canonical_label_hash,
                doc_id_hash=doc_id_hash,
                line_number_key=line_number_key,
                company_code_hash=company_code_hash,
            )
            cache[key] = ref
        refs.append(ref)
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


def _case_issue_queues(
    theme_id: str,
    case_hits: list[_RawHit],
    evidence_types: list[str],
) -> tuple[str, list[str]]:
    primary = _THEME_QUEUE_MAP.get(theme_id, "account_logic")
    queues: list[str] = [primary]
    for evidence_type in evidence_types:
        queue = _EVIDENCE_QUEUE_MAP.get(str(evidence_type))
        if queue and queue not in queues:
            queues.append(queue)
    for hit in case_hits:
        queue = _RULE_QUEUE_MAP.get(str(hit.rule_id))
        if queue and queue not in queues:
            queues.append(queue)
    domain_queues = [queue for queue in queues if queue != "manipulation_candidate"]
    if _is_composite_manipulation_candidate(case_hits, domain_queues):
        queues.append("manipulation_candidate")
    return primary, [queue for queue in queues if queue != primary]


def _is_composite_manipulation_candidate(case_hits: list[_RawHit], queues: list[str]) -> bool:
    domain_count = len(set(queues))
    if domain_count < 2:
        return False
    strong_hits = sum(1 for hit in case_hits if hit.rule_id in _STRONG_TRIAGE_RULES)
    direct_hits = sum(1 for hit in case_hits if hit.signal_status == "confirmed")
    review_only_hits = sum(1 for hit in case_hits if hit.signal_status == "review_candidate")
    if strong_hits >= 2 and direct_hits >= 2:
        return True
    if domain_count >= 3 and strong_hits >= 1 and direct_hits > review_only_hits:
        return True
    return False


def _triage_rank_score(
    *,
    primary_queue: str,
    secondary_queues: list[str],
    case_hits: list[_RawHit],
    evidence_types: list[str],
    document_count: int,
    amount_score: float,
    total_amount: float,
    has_repeat_pattern: bool,
) -> tuple[float, list[str]]:
    queues = {primary_queue, *secondary_queues}
    strong_count = sum(1 for hit in case_hits if hit.rule_id in _STRONG_TRIAGE_RULES)
    direct_count = sum(1 for hit in case_hits if hit.signal_status == "confirmed")
    review_count = sum(1 for hit in case_hits if hit.signal_status == "review_candidate")
    primary_count = sum(1 for hit in case_hits if hit.scoring_role == "primary")
    total_hits = max(len(case_hits), 1)
    review_ratio = review_count / total_hits

    score = 0.0
    reasons: list[str] = []

    if strong_count:
        score += min(strong_count, 4) * 0.12
        reasons.append(f"strong_rules={strong_count}")
    if direct_count:
        score += min(direct_count / total_hits, 1.0) * 0.18
        reasons.append(f"direct_ratio={direct_count}/{total_hits}")
    if primary_count:
        score += min(primary_count / total_hits, 1.0) * 0.10
    queue_overlap = len({queue for queue in queues if queue != "manipulation_candidate"})
    if queue_overlap > 1:
        score += min(queue_overlap - 1, 3) * 0.10
        reasons.append(f"queue_overlap={queue_overlap}")
    evidence_overlap = len(set(evidence_types))
    if evidence_overlap > 1:
        score += min(evidence_overlap - 1, 4) * 0.04
    if amount_score >= 0.75 or total_amount >= 100_000_000:
        score += 0.12
        reasons.append("material_amount")
    elif amount_score >= 0.40 or total_amount >= 10_000_000:
        score += 0.06
    if {"control_approval", "timing_close"}.issubset(queues):
        score += 0.10
        reasons.append("control_timing_combo")
    if {"control_approval", "amount_statistical"}.issubset(queues):
        score += 0.08
        reasons.append("control_amount_combo")
    if {"duplicate_outflow", "amount_statistical"}.issubset(queues):
        score += 0.08
        reasons.append("outflow_amount_combo")
    if "intercompany_cycle" in queues and queue_overlap > 1:
        score += 0.06
        reasons.append("ic_corroborated")
    if has_repeat_pattern:
        score += 0.05
        reasons.append("repeat_pattern")

    if document_count <= 10:
        score += 0.08
        reasons.append("small_review_set")
    elif document_count <= 50:
        score += 0.04
    elif document_count > 250:
        score -= 0.12
        reasons.append("large_review_set_penalty")
    elif document_count > 100:
        score -= 0.06

    if review_ratio >= 0.75:
        score -= 0.12
        reasons.append("review_context_heavy")
    elif review_ratio >= 0.50:
        score -= 0.06

    if primary_queue == "data_integrity" and queue_overlap == 1:
        score -= 0.10
        reasons.append("data_integrity_only")

    if "manipulation_candidate" in secondary_queues:
        score += 0.15
        reasons.append("composite_candidate")

    return round(max(min(score, 1.0), 0.0), 4), reasons


def _queue_label(queue_id: str) -> str:
    return _ISSUE_QUEUE_LABELS.get(queue_id, queue_id.replace("_", " "))


def _topic_label(topic_id: str) -> str:
    metadata = TOPIC_REGISTRY.get(topic_id)
    if metadata is not None:
        return metadata.label
    return topic_id.replace("_", " ")


def _legacy_theme_for_topic(topic_id: str) -> str:
    return _TOPIC_LEGACY_THEME_MAP.get(topic_id, topic_id)


def _topic_floor_policies(config: dict[str, Any]) -> dict[str, float]:
    topic_scoring = config.get("topic_scoring", {})
    if not isinstance(topic_scoring, dict):
        return {}
    floors = topic_scoring.get("topic_floors", {})
    if not isinstance(floors, dict):
        return {}
    return {str(policy_id): float(value) for policy_id, value in floors.items()}


def _combo_floor_policies(config: dict[str, Any]) -> dict[str, float]:
    topic_scoring = config.get("topic_scoring", {})
    if not isinstance(topic_scoring, dict):
        return {}
    floors = topic_scoring.get("combo_floors", {})
    if not isinstance(floors, dict):
        return {}
    return {str(policy_id): float(value) for policy_id, value in floors.items()}


def _case_secondary_topics(
    case_hits: list[_RawHit],
    topic_scores: dict[str, float],
) -> list[str]:
    topics: list[str] = []
    for topic_id in topic_scores:
        topics.append(topic_id)
    for hit in case_hits:
        if hit.normalized_score <= 0:
            continue
        topics.extend(topic for topic in hit.secondary_topics if topic in TOPIC_REGISTRY)
    return _ordered_unique(topics)


# PHASE1 tier → band 매핑 (PHASE1_TIER_SCORING_SPEC §2). band 결정은 가중합이 아니라 tier.
_TIER_TO_BAND: dict[str, str] = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "CONTEXT": "low",
}

# priority_score(deprecated) 호환 shim: tier 대표값. band 결정은 tier 가 하고, 이 값은
# [0,1] 을 가정하는 기존 소비처(export/phase2 linker)와의 호환을 위해서만 둔다.
_TIER_TO_PRIORITY_SCORE: dict[str, float] = {
    "HIGH": 0.90,
    "MEDIUM": 0.75,
    "LOW": 0.40,
    "CONTEXT": 0.0,
}


def _legacy_floor_tier(floor_only_score: float) -> str:
    """config priority_floors(명시 도메인 조건) 의 min_priority_score 를 tier 로 매핑.

    이 floor 들은 가중합이 아니라 명시 조건(SoD critical·승인생략·자기승인 material·핵심필드
    누락 등)이라 tier 트리거로 유효하다. band cut 관례(high>=0.90, medium>=0.75)를 따른다.
    """
    if floor_only_score >= 0.90:
        return "HIGH"
    if floor_only_score >= 0.75:
        return "MEDIUM"
    return "CONTEXT"


def _tier_sort_score(
    case_tier_value: str,
    case_hits: list[_RawHit],
    materiality_score: float,
) -> tuple[float, dict[str, float]]:
    """within-tier 순서형 정렬 (PHASE1_TIER_SCORING_SPEC §4, option 1 + 금액 최후 tiebreak).

    가중합이 아니라 (tier_rank, 독립 primary 수, rule_count, materiality) lexicographic
    순서를 단일 정렬 scalar 로 packing 한다. 금액(materiality)은 최후 tiebreak 로, 고액
    routine 이 신호 케이스를 묻지 않게 한다(§9.3 audit anti-burying lock 호환).
    이 scalar 는 정렬 전용이며 위험도 크기 아님.
    """
    tier_rank = TIER_RANK.get(case_tier_value, 0)
    independent_primary = len({hit.rule_id for hit in case_hits if hit.scoring_role == "primary"})
    rule_count = len({hit.rule_id for hit in case_hits})
    materiality = max(0.0, min(float(materiality_score), 1.0))
    score = (
        tier_rank * 1_000_000
        + min(independent_primary, 99) * 10_000
        + min(rule_count, 99) * 100
        + round(materiality * 99)
    )
    components = {
        "tier_rank": float(tier_rank),
        "independent_primary_count": float(independent_primary),
        "rule_count": float(rule_count),
        "materiality_score": materiality,
    }
    return float(score), components


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
            str(label).strip().lower() for label in floor.get("labels", []) if str(label).strip()
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
        str(rule_id).strip() for rule_id in floor.get("required_rules", []) if str(rule_id).strip()
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
        str(field).strip() for field in floor.get("missing_fields", []) if str(field).strip()
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
        "weak_evidence_bonus": 0.0,
        "l203_duplicate_bonus": 0.0,
    }
    if adjustments.get("enabled", True) is False:
        return priority_score, behavior_score, [], bonuses, []

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

    # batch_combo_bonus 제거(2026-06-21): L4-06 PHASE1-2 family 귀속이라 case priority/behavior
    # 가산 폐기 — bonuses dict 키·CaseGroupResult 필드·export/contract 키 모두 제거됨.

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

    rare_pair_cfg = adjustments.get("rare_account_pair", {})
    if rare_pair_cfg.get("enabled", True) and "L4-04" in rule_ids:
        non_l404_rules = rule_ids - {"L4-04"}
        if not non_l404_rules:
            penalty = float(rare_pair_cfg.get("l404_only_penalty", 0.10))
            adjusted_priority -= penalty
            reasons.append(f"l404_only_penalty=-{penalty:.2f}")

        recurring_ratio = _case_source_ratio(
            rows,
            rare_pair_cfg.get(
                "recurring_sources", ["recurring", "automated", "batch", "interface", "system"]
            ),
        )
        recurring_threshold = float(rare_pair_cfg.get("recurring_source_ratio", 0.60))
        if recurring_ratio >= recurring_threshold:
            penalty = float(rare_pair_cfg.get("recurring_source_penalty", 0.08))
            adjusted_priority -= penalty
            reasons.append(f"l404_recurring_source_penalty=-{penalty:.2f}")

    adjusted_priority += sum(bonuses.values())
    return max(0.0, min(adjusted_priority, 1.0)), adjusted_behavior, reasons, bonuses, weak_tags


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
            context_reasons.update(
                str(reason).strip() for reason in raw_reasons if str(reason).strip()
            )

    if not context_reasons:
        return 0.0, []

    per_context_bonus = float(config.get("per_context_bonus", 0.03))
    max_bonus = float(config.get("max_bonus", 0.12))
    bonus = min(len(context_reasons) * per_context_bonus, max_bonus)
    return bonus, ["l108_context=" + ",".join(sorted(context_reasons))]


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
    if config.get("require_strong_evidence", True) and not (strong_evidence & set(evidence_types)):
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
        config.get("derive_manual_period_end", True)
        and _case_has_true(rows, "is_manual_je")
        and (_case_has_true(rows, "is_period_end") or "L3-04" in rule_ids)
    ):
        tags.append("manual_period_end")

    return sorted(set(tags))


def _case_has_true(rows: pd.DataFrame, column: str) -> bool:
    if column not in rows.columns:
        return False
    return bool(bool_column(rows, column).any())


# PHASE1-2 배지 어휘 (표시·자기큐 전용, 점수 비병합).
_PARTNER_BADGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("is_first_seen_partner", "first_seen_partner"),
    ("is_rare_partner", "rare_partner"),
    ("is_dormant_partner", "dormant_partner"),
)
_RULE_BADGE_MAP: dict[str, str] = {
    "L4-06": "batch_posting_outlier",
    "L3-12": "work_scope_excess",
}


def _partner_badges_for_positions(
    partner_row_badges: pd.DataFrame | None, positions: list[int]
) -> set[str]:
    """positional 행집합의 거래처 배지 any() 집계. row_badges 는 df.index 정렬이라 .iloc 사용."""
    if partner_row_badges is None or partner_row_badges.empty or not positions:
        return set()
    sub = partner_row_badges.iloc[positions]
    return {
        tag for col, tag in _PARTNER_BADGE_COLUMNS if col in sub.columns and bool(sub[col].any())
    }


def _compose_badge_tags(
    *,
    partner_tags: set[str],
    time_severity_score: int,
    fired_rule_ids: set[str],
    weak_tags: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """배지 소스 통합(거래처 + off_time + L4-06/L3-12 + weak_evidence). 중복 제거·정렬. 점수 무영향."""
    tags: set[str] = set(partner_tags)
    if time_severity_score > 0:
        tags.add("off_time")
    for rule_id, tag in _RULE_BADGE_MAP.items():
        if rule_id in fired_rule_ids:
            tags.add(tag)
    tags.update(weak_tags or ())
    return sorted(tags)


def _unit_row_positions(unit: Phase1Unit, doc_positions: dict[str, list[int]]) -> list[int]:
    """unit 이 소유한 positional 행 위치. DocumentUnit=unit_id(=document_id), FlowUnit=member docs."""
    doc_ids = unit.member_document_ids if isinstance(unit, FlowUnit) else [unit.unit_id]
    return sorted({pos for d in doc_ids for pos in doc_positions.get(str(d), ())})


def _case_source_ratio(rows: pd.DataFrame, source_values: list[str]) -> float:
    if "source" not in rows.columns or rows.empty:
        return 0.0
    normalized = rows["source"].fillna("").astype(str).str.strip().str.lower()
    source_set = {str(value).strip().lower() for value in source_values if str(value).strip()}
    if not source_set:
        return 0.0
    return float(normalized.isin(source_set).mean())


def _priority_band(priority_score: float, config: dict[str, Any]) -> str:
    bands = config.get("priority_band", {})
    high = float(bands.get("high", 0.90))
    medium = float(bands.get("medium", 0.75))
    if priority_score >= high:
        return "high"
    if priority_score >= medium:
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
    l304_repeat_signatures: set[str] | None = None,
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
    # OFF-TIME(L3-05·L3-06·L4-05)은 priority/behavior 가산에서 제외 — within-tier 정렬·UI 전용이라
    # case 등급에 기여하지 않는다(rule_scoring.OFF_TIME_SET). 기간귀속·고액(L3-07·L3-11·L4-03)은 유지.
    has_combo_signal = bool(
        rule_ids & {"L3-07", "L3-11", "L4-03"}
        or {"control_failure", "duplicate_or_outflow"} & set(secondary_tags)
    )
    repeat_pattern = _is_l304_repeat_pattern_case(
        df,
        rows,
        case_hits,
        timing_cfg,
        l304_repeat_signatures=l304_repeat_signatures,
    )

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
    *,
    l304_repeat_signatures: set[str] | None = None,
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

    repeat_signatures = (
        l304_repeat_signatures
        if l304_repeat_signatures is not None
        else _l304_repeat_pattern_signatures(df, timing_cfg)
    )
    return dominant_signature in repeat_signatures


def _l304_repeat_pattern_signatures(
    df: pd.DataFrame,
    timing_cfg: dict[str, Any],
) -> set[str]:
    required = {"posting_date", "source", "document_type", "business_process", "gl_account"}
    if not required.issubset(df.columns):
        return set()

    all_rows = df.copy()
    all_posting = pd.to_datetime(all_rows["posting_date"], errors="coerce")
    all_rows = all_rows.loc[all_posting.notna()].copy()
    all_posting = all_posting.loc[all_posting.notna()]
    if all_rows.empty:
        return set()

    all_rows = _add_l304_repeat_signature_columns(all_rows, all_posting)
    monthly_amounts = all_rows.groupby(["pattern_signature", "period_month"])["amount"].median()
    if monthly_amounts.empty:
        return set()

    min_months = int(timing_cfg.get("l304_repeat_pattern_min_months", 3))
    max_cv = float(timing_cfg.get("l304_repeat_pattern_max_amount_cv", 0.35))
    repeat_signatures: set[str] = set()
    for signature, amounts in monthly_amounts.groupby(level=0, sort=False):
        values = amounts.droplevel(0)
        repeat_months = int(values.shape[0])
        if repeat_months < min_months:
            continue
        mean_amount = float(values.mean())
        if mean_amount <= 0:
            continue
        amount_cv = float(values.std(ddof=0) / mean_amount) if repeat_months > 1 else 0.0
        if amount_cv <= max_cv:
            repeat_signatures.add(str(signature))
    return repeat_signatures


def _add_l304_repeat_signature_columns(
    rows: pd.DataFrame,
    posting: pd.Series,
) -> pd.DataFrame:
    result = rows.copy()
    result["period_month"] = posting.dt.strftime("%Y-%m")
    result["period_side"] = posting.dt.day.map(
        lambda day: "month_start" if day <= 5 else "month_end"
    )
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
    result["amount"] = _line_amount_series(result)
    return result


def _repeat_months(rows: pd.DataFrame) -> int:
    if "posting_date" not in rows.columns:
        return 0
    series = pd.to_datetime(rows["posting_date"], errors="coerce").dt.strftime("%Y-%m").dropna()
    return int(series.nunique())


def _case_total_amount(
    df: pd.DataFrame,
    indices: set[int] | list[int],
    *,
    line_amounts: pd.Series | None = None,
) -> float:
    amounts = line_amounts if line_amounts is not None else _line_amount_series(df)
    return float(amounts.iloc[sorted(indices)].sum())


def _document_amount(
    df: pd.DataFrame,
    document_id: str,
    hit_positions: list[int],
    *,
    document_amounts: dict[str, float] | None = None,
    line_amounts: pd.Series | None = None,
) -> float:
    if document_id and document_amounts is not None and document_id in document_amounts:
        return float(document_amounts[document_id])
    amounts = line_amounts if line_amounts is not None else _line_amount_series(df)
    return float(amounts.iloc[hit_positions].sum())


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


def _annotation_can_seed_case(rule_id: str, row_annotation: dict[str, Any] | None) -> bool:
    if _annotation_score(row_annotation) <= 0:
        return False
    metadata = _safe_rule_detail_metadata(rule_id)
    if metadata is not None:
        return _metadata_allows_case_seed(metadata)
    metadata = RULE_SCORING_REGISTRY.get(str(rule_id))
    scoring_role = metadata.scoring_role if metadata is not None else "primary"
    return scoring_role not in {"booster", "combo_only", "macro_only"}


def _safe_rule_detail_metadata(rule_id: str):
    try:
        return get_rule_detail_metadata(str(rule_id))
    except KeyError:
        return None


def _metadata_allows_case_seed(metadata) -> bool:
    if not metadata.standalone_rankable or not metadata.allow_topic_seed:
        return False
    return metadata.presenter_surface in {
        PresenterSurface.TRANSACTION_DETAIL,
        PresenterSurface.INTERCOMPANY_SIDECAR,
    }


def _hit_can_seed_case(*, requested_rule_id: str, normalized: Any) -> bool:
    metadata = _safe_rule_detail_metadata(requested_rule_id)
    if metadata is not None:
        return (
            _metadata_allows_case_seed(metadata)
            and normalized.normalized_score > 0
            and normalized.scoring_role == "primary"
        )
    return (
        bool(normalized.standalone_rankable)
        and normalized.scoring_role == "primary"
        and normalized.normalized_score > 0
    )


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
        action for hit in ordered_hits for action in _rule_actions(hit.rule_id)
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
        return f"{label} 징후 관찰. 총금액 {total_amount:,.0f}. 관련 근거와 증빙 확인 요망."
    return f"{label} 징후 관찰. 관련 근거와 증빙 확인 요망."


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
        "requested_rule_id": hit.requested_rule_id,
        "canonical_rule_id": hit.canonical_rule_id,
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
        return f"{label} 징후 관찰. 총금액 {total_amount:,.0f}."
    return f"{label} 징후 관찰."


# Why: 위험 사유 텍스트는 case master 표의 '합계' 컬럼이 별도로 있어 동일한 금액을
#      문장에 또 적으면 중복이다. 모든 explanation 함수에서 'X입니다' 금액 문구를
#      제거하고 행동 가이드 위주의 한 줄로 단순화한다. total_amount 인자는
#      시그니처 호환을 위해 유지하되 본문에서 사용하지 않는다.


def _control_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _CONTROL_RULES) or ["승인 통제 위반"]
    lead = " + ".join(labels[:3])
    return f"{lead} 함께 관찰. 승인·권한 통제 적용과 예외 승인 근거 우선 확인 요망."


def _access_scope_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _LOGIC_RULES) or ["권한·업무 범위 집중"]
    lead = " + ".join(labels[:3])
    return (
        f"{lead} 신호 관찰. "
        "L1-06 은 명시적 직무분리 위반을 다루므로, 이 case 는 한 사용자의 광범위한 "
        "당기 활동 패턴과 보완 통제 검토 요망."
    )


def _outflow_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _OUTFLOW_RULES)
    lead = " + ".join(labels[:3]) if labels else "지급·중복 징후"
    return f"{lead} 관찰. 동일 지급·중복 처리 여부와 승인·증빙 대사 확인 요망."


def _logic_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _LOGIC_RULES)
    lead = " + ".join(labels[:3]) if labels else "회계 처리 논리 이상"
    return f"{lead} 관찰. 거래의 경제적 실질과 계정 사용 적정성 재검토 요망."


def _timing_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _TIMING_RULES)
    lead = " + ".join(labels[:3]) if labels else "기말·시점 이상"
    return f"{lead} 관찰. 결산 시점의 기간 귀속, 결산 조정 승인, 사후 보정 근거 확인 요망."


def _statistical_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _STAT_RULES)
    lead = " + ".join(labels[:3]) if labels else "통계적 이상치"
    return f"{lead} 관찰. 일반 분포에서 벗어난 예외 거래 여부 확인 요망."


def _intercompany_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _INTERCOMPANY_RULES)
    lead = " + ".join(labels[:3]) if labels else "관계사 거래 검토 신호"
    return f"{lead} 관찰. 거래 상대방, 계약 근거, 정상 가격 및 대사 여부 확인 요망."


def _integrity_explanation(rule_ids: list[str], total_amount: float) -> str:
    labels = _ordered_rule_labels(rule_ids, _INTEGRITY_RULES)
    lead = " + ".join(labels[:3]) if labels else "데이터 정합성 오류"
    return f"{lead} 관찰. 원천 데이터와 장부 반영 내역의 정합성 우선 점검 요망."


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

    parts: list[str] = []
    if match_type and matched_value:
        parts.append(f"{match_type}={matched_value}")
    if matched_group:
        parts.append(f"group={matched_group}")

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
    if coerce_bool_value(row.get("is_period_end", False)):
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


def _line_amount_series(df: pd.DataFrame) -> pd.Series:
    if "debit_amount" in df.columns:
        debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    else:
        debit = pd.Series(0.0, index=df.index)
    if "credit_amount" in df.columns:
        credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    else:
        credit = pd.Series(0.0, index=df.index)
    return pd.concat([debit, credit], axis=1).max(axis=1).astype(float)


def _document_amounts_by_id(df: pd.DataFrame, line_amounts: pd.Series) -> dict[str, float]:
    if "document_id" not in df.columns:
        return {}
    document_ids = df["document_id"].fillna("").astype(str).str.strip()
    valid = document_ids.ne("")
    if not bool(valid.any()):
        return {}
    return line_amounts.loc[valid].groupby(document_ids.loc[valid]).sum().to_dict()


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
