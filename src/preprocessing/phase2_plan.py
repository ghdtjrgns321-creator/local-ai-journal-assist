"""Phase 2 preprocessing decision plan.

This module only records column decisions. Matrix transformation stays in the
training pipeline and is intentionally not implemented here.
"""

from __future__ import annotations

import re
from collections import Counter

from src.eda.models import ColumnProfile, EDAProfile
from src.preprocessing.constants import LABEL_COLUMNS, LEAKAGE_DENY_COLUMNS
from src.services.phase2_training_models import (
    Phase2ColumnDecision,
    Phase2PreprocessingPlan,
)

_ID_NAMES = {"document_id", "doc_id", "row_id", "id", "transaction_id", "journal_id"}
_LOW_CARD_DOMAIN_COLUMNS = {"user_persona"}
# 숫자로 저장돼 있지만 크기가 의미 없는 칸 — 이름표이지 수량이 아니다.
# Why: 계정과목 `4000`·`5000` 은 코드 체계이고, `fiscal_year` 2023·2024 는 연도 라벨,
#      `fiscal_period` 1~12 는 회계월이다. 수치형으로 표준화하면 "2024가 2022보다 크다",
#      "12월과 1월이 가장 멀다"를 학습한다. 회계에서 12월(결산)과 1월(기초)은 붙어 있고
#      감사에서 가장 중요한 구간이다. 원-핫이면 그 왜곡이 없고, 학습에 없던 연도가
#      들어와도 `__RARE__` 로 착지해 이상치로 잡힌다.
_CODE_CATEGORICAL_COLUMNS = {"account_code", "gl_account", "fiscal_year", "fiscal_period"}

# 이름·식별 성격 — 값이 몇 종이든 빈도로 본다.
# Why: 카디널리티 임계(50)는 두 질문을 뭉갠다 — "칸을 몇 개 쓸까"(계산)와
#      "무엇을 보게 할까"(의미). 앞의 질문은 희소 값 묶음(`__RARE__`)이 이미 푼다.
#      뒤의 질문은 컬럼이 무엇이냐로 갈린다: 승인자·거래처 같은 **이름** 칸은
#      "누가"보다 "얼마나 드문 사람·거래처인가"가 신호이고, 계정과목·전표유형 같은
#      **분류** 칸은 어느 분류인지 자체가 신호다.
#      임계에 맡기면 경계에서 뒤집힌다 — 실측 r9 `approved_by` 는 6만 행 표본에서
#      48종(원-핫 48칸), 전 행에서 60종(빈도 1칸)이었다. 승인자가 45명인 회사와
#      55명인 회사가 서로 다른 전처리를 받는다는 뜻이다.
_IDENTITY_COLUMNS = {
    "approved_by",
    "created_by",
    "cost_center",
    "trading_partner",
    "auxiliary_account_number",
    "auxiliary_account_label",
    "line_text",
    "header_text",
}

# 결측이 "해당 없음"을 뜻하는 칸 — 고결측 자동 제외에서 뺀다.
# Why: `is_cleared`(가계정 정리 여부)는 가계정이 아닌 전표에서는 물어볼 수 없는
#      질문이라 빈다. 실측 r9: 가계정 행 결측 0% / 그 외 100%, 전체 95%.
#      "90% 넘게 비면 고장난 칸"이라는 규칙은 이 모양을 구분하지 못한다.
#      값이 있는 것 중 미정리 649건이 L3-09(가수금·가지급금 미정리)가 보는 항목이다.
#      대신 결측을 0 으로 채우면 안 된다 — 매트릭스 빌더가 `__missing` 표식을 세워
#      "정리된 가계정 / 미정리 가계정 / 가계정 아님" 세 상황을 가른다.
STRUCTURAL_MISSING_COLUMNS = {"is_cleared"}

_HIGH_MISSING_THRESHOLD = 0.90

# DataSynth v3 S4 §3 measured `f_manual` as normal=0.41 vs manipulated=1.00.
# This is a synthetic shortcut until v4 noises the manual flag distribution;
# remove this guard in the matrix builder only after the v4 profile fixes it.
_SINGLE_USE_DENY = frozenset({"f_manual"})
_LEAKAGE_DENY_COLUMN_NAMES = frozenset(column.lower() for column in LEAKAGE_DENY_COLUMNS)

_LEAKAGE_PATTERNS = (
    ("label", "leakage_label"),
    ("target", "leakage_label"),
    ("fraud", "leakage_label"),
    ("anomaly", "leakage_label"),
    ("risk", "leakage_risk"),
    ("rule", "leakage_rule"),
    ("score", "leakage_score"),
    ("model", "leakage_model"),
    ("prediction", "leakage_model"),
    ("probability", "leakage_model"),
    ("export", "leakage_export"),
    ("dashboard", "leakage_dashboard"),
)

# Why: standalone contract — PHASE1/PHASE2/PHASE3 산출 중 위 토큰 패턴에
#      걸리지 않는 컬럼은 exact name 으로 명시 차단한다. broad token (예:
#      "priority", "narrative") 를 추가하면 raw ERP 컬럼인 payment_priority /
#      vendor_priority / transaction_narrative 같은 정상 비즈니스 필드까지
#      함께 막힌다 (2026-05-24 리뷰).
_PHASE_OUTPUT_DENY_EXACT = frozenset(
    {
        # PHASE1 case priority 분류 (token deny 매칭 없음)
        "priority_band",
        # PHASE3 narrator 재정렬 출력 (token deny 매칭 없음)
        "priority_rank",
        # PHASE3 narrator 출력 (token deny 매칭 없음)
        "review_narrative_text",
        "review_narrative_summary",
        "review_narrative_actions",
    }
)

# PHASE1/2/3 단계 산출 prefix — 재투입 차단. raw ERP 컬럼은 이 prefix 를
# 쓰지 않으므로 false positive 위험이 낮다.
_PHASE_OUTPUT_DENY_PREFIXES = (
    "phase1_",
    "phase2_",
    "phase3_",
    "review_narrative_",
)


def build_phase2_preprocessing_plan(
    profile: EDAProfile,
    *,
    high_card_threshold: int = 50,
) -> Phase2PreprocessingPlan:
    """Build a serializable Phase 2 column decision plan from capped EDA."""
    decisions = [
        _decide_column(name, column, high_card_threshold=high_card_threshold)
        for name, column in profile.columns.items()
    ]
    reason_counts = Counter(decision.reason_code for decision in decisions)
    action_counts = Counter(decision.action for decision in decisions)
    return Phase2PreprocessingPlan(
        row_count=profile.total_rows,
        profile_sampled=profile.sampled,
        profile_sample_size=profile.sample_size,
        duplicate_rows=profile.duplicate_rows,
        duplicate_rows_estimated=profile.duplicate_rows_estimated,
        duplicate_sample_size=profile.duplicate_sample_size,
        duplicate_rate_estimate=profile.duplicate_rate_estimate,
        decisions=decisions,
        metadata={
            "decision_count": len(decisions),
            "action_counts": dict(sorted(action_counts.items())),
            "reason_code_counts": dict(sorted(reason_counts.items())),
        },
    )


def _decide_column(
    name: str,
    column: ColumnProfile,
    *,
    high_card_threshold: int,
) -> Phase2ColumnDecision:
    normalized_name = _normalize_name(name)
    leakage_reason = _leakage_reason(normalized_name)

    if normalized_name in LABEL_COLUMNS:
        return _decision(name, column, "label", "exclude", "leakage_label")
    if normalized_name in _LEAKAGE_DENY_COLUMN_NAMES:
        return _decision(name, column, "leakage", "exclude", "leakage_deny_column")
    if normalized_name in _PHASE_OUTPUT_DENY_EXACT:
        return _decision(name, column, "leakage", "exclude", "phase_output_deny")
    if any(normalized_name.startswith(prefix) for prefix in _PHASE_OUTPUT_DENY_PREFIXES):
        return _decision(name, column, "leakage", "exclude", "phase_output_prefix")
    if leakage_reason is not None:
        return _decision(name, column, "leakage", "exclude", leakage_reason)
    if normalized_name in _ID_NAMES or normalized_name.endswith("_id"):
        return _decision(name, column, "identifier", "exclude", "identifier")
    if column.dtype_group == "datetime":
        return _decision(name, column, "datetime", "exclude", "datetime_raw")
    if (
        column.missing_rate >= _HIGH_MISSING_THRESHOLD
        and normalized_name not in STRUCTURAL_MISSING_COLUMNS
    ):
        return _decision(name, column, "feature", "exclude", "high_missing")
    if normalized_name in _IDENTITY_COLUMNS:
        return _decision(name, column, "categorical_high", "include", "domain_identity")
    if normalized_name in _CODE_CATEGORICAL_COLUMNS:
        if column.unique_count >= high_card_threshold:
            return _decision(
                name,
                column,
                "categorical_high",
                "include",
                "domain_code_categorical",
            )
        return _decision(
            name,
            column,
            "categorical_low",
            "include",
            "domain_code_categorical",
        )
    if normalized_name in _LOW_CARD_DOMAIN_COLUMNS:
        return _decision(name, column, "categorical_low", "include", "domain_low_card")
    if column.dtype_group == "boolean":
        return _decision(name, column, "boolean", "include", "boolean")
    if column.dtype_group == "numeric":
        return _decision(name, column, "numeric", "include", "numeric")
    if column.dtype_group == "categorical":
        if column.unique_count >= high_card_threshold:
            return _decision(
                name,
                column,
                "categorical_high",
                "include",
                "high_cardinality",
            )
        return _decision(name, column, "categorical_low", "include", "low_cardinality")
    return _decision(name, column, "feature", "include", "dtype_fallback")


def _decision(
    name: str,
    column: ColumnProfile,
    role: str,
    action: str,
    reason_code: str,
) -> Phase2ColumnDecision:
    return Phase2ColumnDecision(
        column=name,
        role=role,
        action=action,
        reason_code=reason_code,
        dtype_group=column.dtype_group,
        missing_rate=column.missing_rate,
        unique_count=column.unique_count,
    )


def _is_master_data_name_column(normalized_name: str) -> bool:
    """`X_label` 이 정답 라벨이 아니라 마스터 데이터의 '명칭'인 경우를 가려낸다.

    Why: 2026-07-29 발견. `auxiliary_account_label`(보조계정 명칭 — '기업다이렉트(유)',
         '내부부서')이 이름에 `label` 이 있다는 이유로 정답 라벨로 오인돼 잘렸다.
         짝인 `auxiliary_account_number`('V-000526')는 통과한다. 이 데이터에서는
         번호 칸이 같은 정보를 담아 손실이 없었지만, 실 ERP 의 `gl_account_label` ·
         `cost_center_label` · `vendor_label` 이 전부 같은 규칙에 걸린다.

         판정 어휘(fraud·anomaly·risk·target·score 등)가 접두어에 있으면 여전히
         차단된다 — `fraud_label` 은 `fraud` 토큰이, `risk_label` 은 `risk` 토큰이
         잡는다. 정확한 이름의 라벨(`label` · `target`)은 LABEL_COLUMNS 가 잡는다.
         여기서 통과시키는 것은 **판정 어휘가 없는 `*_label`** 뿐이다.
    """
    if not normalized_name.endswith("_label"):
        return False
    prefix_tokens = set(normalized_name[: -len("_label")].split("_"))
    judgment_tokens = {token for token, _ in _LEAKAGE_PATTERNS}
    return prefix_tokens.isdisjoint(judgment_tokens)


def _leakage_reason(normalized_name: str) -> str | None:
    if _is_master_data_name_column(normalized_name):
        return None
    tokens = set(normalized_name.split("_"))
    # Why: 단복수 모두 차단 (flagged_rules / review_rules / labels / scores 등).
    #      Phase 2 standalone contract 위반을 막기 위해 plural 도 매칭.
    for token, reason_code in _LEAKAGE_PATTERNS:
        if (
            token in tokens
            or f"{token}s" in tokens
            or normalized_name.endswith(f"_{token}")
            or normalized_name.endswith(f"_{token}s")
        ):
            return reason_code
    return None


def _validate_single_use_deny_columns(columns: list[str] | tuple[str, ...]) -> None:
    """Reject shortcut columns when they would enter the matrix as standalone inputs."""
    denied = [column for column in columns if _normalize_name(column) in _SINGLE_USE_DENY]
    if denied:
        denied_list = ", ".join(sorted(denied))
        raise ValueError(
            "Phase 2 feature matrix cannot include single-use denied feature(s): "
            f"{denied_list}. Use interaction features such as "
            "f_manual_x_amount_high or f_manual_x_weekend instead."
        )


def _normalize_name(name: str) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")
