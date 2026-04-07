"""피처 엔진 — 4개 서브모듈 오케스트레이터.

generate_all_features() 하나로 18개 파생변수를 일괄 생성.
후행 모듈(validation, detection, pipeline)의 단일 진입점.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from config.settings import AuditSettings, get_settings
from src.feature.amount_features import add_all_amount_features
from src.feature.pattern_features import add_all_pattern_features
from src.feature.text_features import add_all_text_features
from src.feature.time_features import add_all_time_features

logger = logging.getLogger(__name__)


# ── 카테고리 열거형 & 기대 컬럼 ─────────────────────────────────


class FeatureCategory(StrEnum):
    """피처 카테고리 — 실행 순서이기도 하다."""
    TIME = "time"
    AMOUNT = "amount"
    PATTERN = "pattern"
    TEXT = "text"


# 고정 실행 순서: 의존성 없지만 디버깅 재현성을 위해 순서 보장
_EXECUTION_ORDER: list[FeatureCategory] = [
    FeatureCategory.TIME,
    FeatureCategory.AMOUNT,
    FeatureCategory.PATTERN,
    FeatureCategory.TEXT,
]

# 카테고리별 기대 컬럼 — 서브모듈이 추가하는 컬럼명과 1:1 대응
EXPECTED_COLUMNS: dict[FeatureCategory, list[str]] = {
    FeatureCategory.TIME: [
        "is_weekend",
        "is_after_hours",
        "is_period_end",
        "days_backdated",
        "fiscal_period_mismatch",
        "is_holiday",
        "time_zone_category",
    ],
    FeatureCategory.AMOUNT: [
        "is_near_threshold",
        "exceeds_threshold",
        "amount_zscore",
        "amount_magnitude",
        "is_round_number",
    ],
    FeatureCategory.PATTERN: [
        "is_manual_je",
        "is_intercompany",
        "is_revenue_account",
        "first_digit",
        "is_suspense_account",
    ],
    FeatureCategory.TEXT: [
        "description_quality",
        "has_risk_keyword",
    ],
}


# ── 결과 데이터클래스 ───────────────────────────────────────────


@dataclass
class FeatureResult:
    """피처 생성 결과 — 데이터 + 메타데이터."""

    data: pd.DataFrame
    added_columns: list[str]                   # df에 존재하는 피처 컬럼 전체
    missing_columns: list[str]                 # 기대했지만 df에 없는 컬럼
    execution_times: dict[str, float] = field(default_factory=dict)
    categories_run: list[str] = field(default_factory=list)
    failed_categories: list[str] = field(default_factory=list)  # KeyError로 스킵된 카테고리
    warnings: dict[str, list[str]] = field(default_factory=dict)  # 카테고리별 경고/스킵 사유

    @property
    def elapsed_seconds(self) -> float:
        """총 소요 시간 (편의 프로퍼티)."""
        return sum(self.execution_times.values())


# ── 메인 함수 ───────────────────────────────────────────────────


def generate_all_features(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
    rules: dict | None = None,
    risk_keywords: dict | None = None,
    categories: list[FeatureCategory] | None = None,
) -> FeatureResult:
    """18개 파생변수를 일괄 생성하는 단일 진입점.

    Parameters
    ----------
    df : 입력 DataFrame (in-place 수정)
    settings : AuditSettings 주입. None이면 자동 로드.
    rules : audit_rules dict. {"patterns": {...}} 또는 평탄 dict 모두 허용.
    risk_keywords : 위험 키워드 dict. None이면 자동 로드.
    categories : 실행할 카테고리 목록. None이면 전체 4개.
    """
    s = settings or get_settings()

    # Why: get_audit_rules()는 {"patterns": {...}} 중첩 구조를 반환하지만
    #      pattern_features는 평탄 dict를 기대. 호출자가 어느 형태로 넘기든 안전 처리.
    if rules is not None and "patterns" in rules:
        rules = rules["patterns"]

    # 실행 대상 결정: 사용자 지정 or 전체, 항상 고정 순서로 실행
    target_set = set(categories) if categories else set(_EXECUTION_ORDER)
    ordered_targets = [c for c in _EXECUTION_ORDER if c in target_set]

    execution_times: dict[str, float] = {}
    categories_run: list[str] = []
    failed_categories: list[str] = []
    warnings_map: dict[str, list[str]] = {}

    # 카테고리별 실행 + 소요 시간 측정 + 경고 수집
    for cat in ordered_targets:
        t0 = time.monotonic()
        cat_warnings: list[str] = []
        success = _run_category(df, cat, settings=s, rules=rules, risk_keywords=risk_keywords, warnings_out=cat_warnings)
        elapsed = time.monotonic() - t0
        execution_times[cat.value] = round(elapsed, 6)
        if success:
            categories_run.append(cat.value)
        else:
            failed_categories.append(cat.value)
        if cat_warnings:
            warnings_map[cat.value] = cat_warnings

    # 메타데이터 산출: 실행 대상 카테고리의 기대 컬럼만 검사
    all_expected = [
        col
        for cat in ordered_targets
        for col in EXPECTED_COLUMNS[cat]
    ]
    added = [col for col in all_expected if col in df.columns]
    missing = [col for col in all_expected if col not in df.columns]

    if missing:
        logger.warning("기대 컬럼 중 미생성: %s", missing)

    logger.info(
        "피처 생성 완료: %d/%d 컬럼, %.3fs",
        len(added), len(all_expected), sum(execution_times.values()),
    )

    return FeatureResult(
        data=df,
        added_columns=added,
        missing_columns=missing,
        execution_times=execution_times,
        categories_run=categories_run,
        failed_categories=failed_categories,
        warnings=warnings_map,
    )


def _run_category(
    df: pd.DataFrame,
    cat: FeatureCategory,
    *,
    settings: AuditSettings,
    rules: dict | None,
    risk_keywords: dict | None = None,
    warnings_out: list[str] | None = None,
) -> bool:
    """카테고리별 서브모듈 디스패치. 성공 시 True, 실패 시 False.

    Why: 필수 컬럼이 누락된 데이터셋에서도 나머지 카테고리는 정상 실행해야 한다.
    KeyError(컬럼 미존재)만 잡고, 로직 버그(TypeError 등)는 전파시킨다.
    warnings_out: 카테고리 실행 중 발생한 경고/스킵 사유를 수집하는 리스트.
    """
    try:
        if cat == FeatureCategory.TIME:
            add_all_time_features(df, settings=settings)
        elif cat == FeatureCategory.AMOUNT:
            add_all_amount_features(df, settings=settings)
        elif cat == FeatureCategory.PATTERN:
            add_all_pattern_features(df, rules=rules)
        elif cat == FeatureCategory.TEXT:
            add_all_text_features(df, settings=settings, risk_kw=risk_keywords)
    except KeyError as e:
        msg = f"필수 컬럼 누락으로 스킵: {e}"
        logger.warning("카테고리 %s 스킵 — %s", cat.value, msg)
        if warnings_out is not None:
            warnings_out.append(msg)
        return False

    # 기대 컬럼 중 미생성된 컬럼을 경고로 수집
    if warnings_out is not None:
        for col in EXPECTED_COLUMNS[cat]:
            if col not in df.columns:
                warnings_out.append(f"기대 컬럼 미생성: {col}")

    return True
