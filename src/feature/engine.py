"""피처 엔진 — 4개 서브모듈 오케스트레이터.

generate_all_features() 하나로 감사 파생변수 + NLP 임시 컬럼(morpheme_tokens)을 일괄 생성.
후행 모듈(validation, detection, pipeline)의 단일 진입점.

Why: 일부 텍스트 coverage 컬럼은 Phase 1 운영 진단용이며, morpheme_tokens는 WU-21
     NLP 전처리용 임시 리스트라 DB 저장 대상이 아님.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

PHASE1_CORE_RULE_IDS: tuple[str, ...] = (
    "L1",
    "L2",
    "L3",
    "L4",
    "D01",
    "D02",
)

_RULE_FEATURE_CATEGORIES: dict[str, set[FeatureCategory]] = {
    # Integrity rules use source columns only.
    "L1-01": set(),
    "L1-02": set(),
    "L1-03": set(),
    # Approval / amount-control rules.
    "L2-01": {FeatureCategory.AMOUNT},
    "L1-04": {FeatureCategory.AMOUNT},
    "L1-05": set(),
    "L1-06": set(),
    "L1-07": {FeatureCategory.AMOUNT},
    "L1-08": {FeatureCategory.TIME},
    "L1-07-02": {FeatureCategory.AMOUNT},
    # Fraud and review signals.
    "L2-02": set(),
    "L2-03": set(),
    "L2-04": set(),
    "L2-05": {FeatureCategory.TIME, FeatureCategory.PATTERN, FeatureCategory.TEXT},
    "L3-02": {FeatureCategory.PATTERN},
    "L3-03": {FeatureCategory.PATTERN},
    "L3-04": {FeatureCategory.TIME},
    "L3-05": {FeatureCategory.TIME},
    "L3-06": {FeatureCategory.TIME},
    "L3-07": {FeatureCategory.TIME},
    "L3-08": {FeatureCategory.TEXT},
    "L3-09": {FeatureCategory.PATTERN},
    "L3-10": set(),
    "L3-11": {FeatureCategory.TIME, FeatureCategory.PATTERN},
    "L4-01": {FeatureCategory.AMOUNT, FeatureCategory.PATTERN},
    "L4-02": {FeatureCategory.PATTERN},
    "L4-03": {FeatureCategory.AMOUNT},
    "L4-04": set(),
    "L4-05": {FeatureCategory.TIME},
    "L4-06": {FeatureCategory.TIME, FeatureCategory.AMOUNT},
    # Analytical review rules use raw account/amount/month columns.
    "D01": set(),
    "D02": set(),
}


def feature_categories_for_rules(rule_ids: list[str] | tuple[str, ...]) -> list[FeatureCategory]:
    """Return the minimal feature categories needed by the requested rule IDs.

    Rule-level filtering is intentionally conservative: family IDs such as
    ``L1``/``L2`` expand to the currently registered PHASE1 rules in that family.
    """

    requested = {str(rule_id).upper() for rule_id in rule_ids}
    categories: set[FeatureCategory] = set()
    for rule_id, rule_categories in _RULE_FEATURE_CATEGORIES.items():
        family = rule_id.split("-", 1)[0]
        if rule_id in requested or family in requested:
            categories.update(rule_categories)
    return [category for category in _EXECUTION_ORDER if category in categories]


# Why: 병렬 실행 시 전체 df.copy() 대신 필요 컬럼만 thin copy (OOM 방지)
_INPUT_COLUMNS: dict[FeatureCategory, list[str]] = {
    FeatureCategory.TIME: ["posting_date", "document_date", "fiscal_period", "fiscal_year"],
    FeatureCategory.AMOUNT: [
        "document_id",
        "debit_amount",
        "credit_amount",
        "gl_account",
        "currency",
        "approved_by",
    ],
    FeatureCategory.PATTERN: [
        "source",
        "gl_account",
        "line_text",
        "header_text",
        "debit_amount",
        "credit_amount",
    ],
    FeatureCategory.TEXT: ["line_text", "header_text"],
}

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
        "near_threshold_amount",
        "near_threshold_limit_amount",
        "near_threshold_limit_resolved",
        "near_threshold_ratio_to_limit",
        "near_threshold_gap_amount",
        "near_threshold_gap_ratio",
        "near_threshold_bucket",
        "exceeds_threshold",
        "document_approval_amount",
        "approver_limit_amount",
        "approval_limit_resolved",
        "approver_can_approve_je",
        "approval_excess_amount",
        "approval_excess_ratio",
        "approval_excess_bucket",
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
        "description_line_missing",
        "description_header_missing",
        "description_both_missing",
        "description_line_missing_header_present",
        "description_is_missing_or_corrupted",
        "has_risk_keyword",
        "morpheme_tokens",  # WU-19: kiwipiepy 형태소 토큰 리스트 (WU-21 전처리)
    ],
}


# ── 결과 데이터클래스 ───────────────────────────────────────────


@dataclass
class FeatureResult:
    """피처 생성 결과 — 데이터 + 메타데이터."""

    data: pd.DataFrame
    added_columns: list[str]  # df에 존재하는 피처 컬럼 전체
    missing_columns: list[str]  # 기대했지만 df에 없는 컬럼
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
    parallel: bool = False,
    max_workers: int | None = None,
    include_morpheme_tokens: bool = True,
) -> FeatureResult:
    """감사 파생변수와 NLP 임시 컬럼을 일괄 생성하는 단일 진입점.

    Parameters
    ----------
    df : 입력 DataFrame (in-place 수정)
    settings : AuditSettings 주입. None이면 자동 로드.
    rules : audit_rules dict. {"patterns": {...}} 또는 평탄 dict 모두 허용.
    risk_keywords : 위험 키워드 dict. None이면 자동 로드.
    categories : 실행할 카테고리 목록. None이면 전체 4개.
    parallel : True이면 ThreadPoolExecutor로 카테고리 병렬 실행.
    max_workers : 병렬 실행 시 최대 스레드 수. None이면 카테고리 수.
    """
    s = settings or get_settings()

    # Why: get_audit_rules()는 {"patterns": {...}, "currency_decimals": {...}} 중첩 구조.
    #      pattern_features는 평탄 dict를 기대. amount_features는 원본(currency_decimals)이 필요.
    raw_rules = rules  # 원본 보존 (currency_decimals 등 비-patterns 키 접근용)
    if rules is not None and "patterns" in rules:
        rules = rules["patterns"]

    # 실행 대상 결정: 사용자 지정 or 전체, 항상 고정 순서로 실행
    target_set = set(categories) if categories else set(_EXECUTION_ORDER)
    ordered_targets = [c for c in _EXECUTION_ORDER if c in target_set]

    if parallel:
        execution_times, categories_run, failed_categories, warnings_map = _run_categories_parallel(
            df,
            ordered_targets,
            settings=s,
            rules=rules,
            raw_rules=raw_rules,
            risk_keywords=risk_keywords,
            max_workers=max_workers,
            include_morpheme_tokens=include_morpheme_tokens,
        )
    else:
        execution_times, categories_run, failed_categories, warnings_map = (
            _run_categories_sequential(
                df,
                ordered_targets,
                settings=s,
                rules=rules,
                raw_rules=raw_rules,
                risk_keywords=risk_keywords,
                include_morpheme_tokens=include_morpheme_tokens,
            )
        )

    # 메타데이터 산출: 실행 대상 카테고리의 기대 컬럼만 검사
    all_expected: list[str] = []
    for cat in ordered_targets:
        columns = EXPECTED_COLUMNS[cat]
        if cat == FeatureCategory.TEXT and not include_morpheme_tokens:
            columns = [col for col in columns if col != "morpheme_tokens"]
        all_expected.extend(columns)
    added = [col for col in all_expected if col in df.columns]
    missing = [col for col in all_expected if col not in df.columns]

    if missing:
        logger.warning("기대 컬럼 중 미생성: %s", missing)

    logger.info(
        "피처 생성 완료: %d/%d 컬럼, %.3fs (parallel=%s)",
        len(added),
        len(all_expected),
        sum(execution_times.values()),
        parallel,
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


def _run_categories_sequential(
    df: pd.DataFrame,
    targets: list[FeatureCategory],
    *,
    settings: AuditSettings,
    rules: dict | None,
    raw_rules: dict | None,
    risk_keywords: dict | None,
    include_morpheme_tokens: bool = True,
) -> tuple[dict[str, float], list[str], list[str], dict[str, list[str]]]:
    """순차 실행 — 기존 로직을 함수로 분리."""
    execution_times: dict[str, float] = {}
    categories_run: list[str] = []
    failed_categories: list[str] = []
    warnings_map: dict[str, list[str]] = {}

    for cat in targets:
        t0 = time.monotonic()
        cat_warnings: list[str] = []
        success = _run_category(
            df,
            cat,
            settings=settings,
            rules=rules,
            raw_rules=raw_rules,
            risk_keywords=risk_keywords,
            include_morpheme_tokens=include_morpheme_tokens,
            warnings_out=cat_warnings,
        )
        elapsed = time.monotonic() - t0
        execution_times[cat.value] = round(elapsed, 6)
        if success:
            categories_run.append(cat.value)
        else:
            failed_categories.append(cat.value)
        if cat_warnings:
            warnings_map[cat.value] = cat_warnings

    return execution_times, categories_run, failed_categories, warnings_map


def _run_categories_parallel(
    df: pd.DataFrame,
    targets: list[FeatureCategory],
    *,
    settings: AuditSettings,
    rules: dict | None,
    raw_rules: dict | None,
    risk_keywords: dict | None,
    max_workers: int | None = None,
    include_morpheme_tokens: bool = True,
) -> tuple[dict[str, float], list[str], list[str], dict[str, list[str]]]:
    """병렬 실행 — Thin Copy + Series 반환 패턴으로 OOM 방지.

    Why: 전체 df.copy() × N 대신, 각 카테고리가 필요한 입력 컬럼만 thin copy.
         실행 후 새로 생성된 컬럼(Series)만 추출하여 원본에 일괄 병합.
         GIL 환경에서 CPU-bound pandas 연산은 실질적 속도 향상이 제한적.
         주 목적: 카테고리 독립 실행 + 타임아웃 격리. 순수 속도 목적이면
         ProcessPoolExecutor 검토 필요 (단 DataFrame pickle 비용 발생).
    """
    execution_times: dict[str, float] = {}
    categories_run: list[str] = []
    failed_categories: list[str] = []
    warnings_map: dict[str, list[str]] = {}

    def _run_one(cat: FeatureCategory):
        # 필요 입력 컬럼만 thin copy (OOM 방지)
        input_cols = [c for c in _INPUT_COLUMNS.get(cat, []) if c in df.columns]
        thin_df = df[input_cols].copy()

        t0 = time.monotonic()
        cat_warnings: list[str] = []
        success = _run_category(
            thin_df,
            cat,
            settings=settings,
            rules=rules,
            raw_rules=raw_rules,
            risk_keywords=risk_keywords,
            include_morpheme_tokens=include_morpheme_tokens,
            warnings_out=cat_warnings,
        )
        elapsed = time.monotonic() - t0

        # 새로 생성된 컬럼만 추출
        expected_columns = EXPECTED_COLUMNS[cat]
        if cat == FeatureCategory.TEXT and not include_morpheme_tokens:
            expected_columns = [c for c in expected_columns if c != "morpheme_tokens"]
        new_cols = {c: thin_df[c] for c in expected_columns if c in thin_df.columns}
        return cat, success, new_cols, round(elapsed, 6), cat_warnings

    with ThreadPoolExecutor(max_workers=max_workers or len(targets)) as pool:
        futures = {pool.submit(_run_one, cat): cat for cat in targets}
        all_new_cols: dict[str, pd.Series] = {}

        for future in as_completed(futures):
            try:
                cat, success, new_cols, elapsed, cat_warnings = future.result()
            except Exception as exc:
                cat = futures[future]
                logger.warning("카테고리 %s 병렬 실행 예외: %s", cat.value, exc)
                failed_categories.append(cat.value)
                execution_times[cat.value] = 0.0
                continue
            execution_times[cat.value] = elapsed
            if success:
                categories_run.append(cat.value)
            else:
                failed_categories.append(cat.value)
            if cat_warnings:
                warnings_map[cat.value] = cat_warnings
            all_new_cols.update(new_cols)

    # 새 컬럼 일괄 병합 (.values로 index 정렬 이슈 방지)
    for col_name, series in all_new_cols.items():
        df[col_name] = series.values

    return execution_times, categories_run, failed_categories, warnings_map


def _run_category(
    df: pd.DataFrame,
    cat: FeatureCategory,
    *,
    settings: AuditSettings,
    rules: dict | None,
    raw_rules: dict | None = None,
    risk_keywords: dict | None = None,
    include_morpheme_tokens: bool = True,
    warnings_out: list[str] | None = None,
) -> bool:
    """카테고리별 서브모듈 디스패치. 성공 시 True, 실패 시 False.

    Why: 필수 컬럼이 누락된 데이터셋에서도 나머지 카테고리는 정상 실행해야 한다.
    KeyError(컬럼 미존재)만 잡고, 로직 버그(TypeError 등)는 전파시킨다.
    raw_rules: 평탄화 전 원본 audit_rules (currency_decimals 등 비-patterns 키 접근).
    warnings_out: 카테고리 실행 중 발생한 경고/스킵 사유를 수집하는 리스트.
    """
    try:
        if cat == FeatureCategory.TIME:
            add_all_time_features(df, settings=settings)
        elif cat == FeatureCategory.AMOUNT:
            add_all_amount_features(df, settings=settings, audit_rules=raw_rules)
        elif cat == FeatureCategory.PATTERN:
            add_all_pattern_features(df, rules=rules)
        elif cat == FeatureCategory.TEXT:
            add_all_text_features(
                df,
                settings=settings,
                risk_kw=risk_keywords,
                include_morpheme_tokens=include_morpheme_tokens,
            )
    except KeyError as e:
        msg = f"필수 컬럼 누락으로 스킵: {e}"
        logger.warning("카테고리 %s 스킵 — %s", cat.value, msg)
        if warnings_out is not None:
            warnings_out.append(msg)
        return False

    # 기대 컬럼 중 미생성된 컬럼을 경고로 수집
    if warnings_out is not None:
        expected_columns = EXPECTED_COLUMNS[cat]
        if cat == FeatureCategory.TEXT and not include_morpheme_tokens:
            expected_columns = [col for col in expected_columns if col != "morpheme_tokens"]
        for col in expected_columns:
            if col not in df.columns:
                warnings_out.append(f"기대 컬럼 미생성: {col}")

    return True
