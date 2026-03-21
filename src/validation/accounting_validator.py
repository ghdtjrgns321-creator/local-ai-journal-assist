"""L2 회계 검증 — 대차일치·일자 연속성·중복 행 탐지.

Why: L1(구조) 통과 후, 회계 규칙 준수 여부를 검증하여
detection 진입 전 데이터 무결성을 보장한다.
PCAOB AS 2401 / ISA 240 §32 (복식부기 원칙) 근거.
"""

from __future__ import annotations

import logging

import pandas as pd

from config.settings import get_schema
from src.validation.models import AccountingResult

logger = logging.getLogger(__name__)


# ── 서브함수 ──────────────────────────────────────────────────


def check_balance(
    df: pd.DataFrame, tolerance: float = 0.01
) -> tuple[bool, float, list[str]]:
    """document_id별 + 전체 대차일치 검증.

    Returns:
        (일치 여부, 전체 차이 금액, 불일치 document_id 목록)
        document_id 컬럼 부재 시 전체 합계만으로 판정, 목록은 빈 리스트.
    """
    # Why: 필수 컬럼 부재 시 crash 방지 — L1에서 이미 경고됨
    if "debit_amount" not in df.columns or "credit_amount" not in df.columns:
        logger.warning("debit_amount/credit_amount 컬럼 부재 — 대차일치 검증 건너뜀")
        return True, 0.0, []

    if df.empty:
        return True, 0.0, []

    # Why: 단일 차액 컬럼으로 groupby 1회 처리 — 2컬럼 sum 대비 성능 최적화
    diff_series = df["debit_amount"].fillna(0.0) - df["credit_amount"].fillna(0.0)
    total_diff = float(abs(diff_series.sum()))

    # Why: document_id 유무에 따라 판정 기준을 명시적으로 분기
    # - document_id 있음 → 전표 단위 불균형이 핵심 (total_diff는 참고용)
    # - document_id 없음 → 전체 합계만으로 판정
    if "document_id" in df.columns:
        grouped_diff = diff_series.groupby(df["document_id"]).sum()
        unbalanced = grouped_diff[grouped_diff.abs() >= tolerance]
        unbalanced_docs = unbalanced.index.astype(str).tolist()
        balance_ok = len(unbalanced_docs) == 0
    else:
        unbalanced_docs = []
        balance_ok = total_diff < tolerance

    return balance_ok, total_diff, unbalanced_docs


def check_date_continuity(
    df: pd.DataFrame,
) -> tuple[bool, list[str]]:
    """영업일 기준 일자 연속성 검증.

    Returns:
        (연속 여부, 누락 영업일 ISO 8601 목록)
    """
    if "posting_date" not in df.columns:
        logger.warning("posting_date 컬럼 부재 — 일자 연속성 검증 건너뜀")
        return True, []

    dates = pd.to_datetime(df["posting_date"], errors="coerce").dropna()
    if len(dates) < 2:
        return True, []

    min_date, max_date = dates.min(), dates.max()
    # Why: bdate_range = 월~금 영업일. 한국 공휴일은 Phase 2에서 custom_holidays 연동
    expected = set(pd.bdate_range(min_date, max_date))
    actual = set(dates.dt.normalize().unique())
    missing = sorted(expected - actual)

    missing_strs = [d.strftime("%Y-%m-%d") for d in missing]
    return len(missing) == 0, missing_strs


def check_duplicates(df: pd.DataFrame) -> int:
    """완전 중복 행 탐지 — 피처 컬럼 제외, 원본 컬럼만 비교.

    Returns:
        중복 행 수 (첫 번째 등장 제외한 나머지)
    """
    if df.empty:
        return 0

    # Why: schema.yaml 기준 원본 컬럼만 추출 — 피처 컬럼(is_weekend 등) 제외
    # schema 로드 실패 시 전체 컬럼으로 fallback (테스트 환경, 파일 누락 등)
    try:
        schema = get_schema()
        schema_cols = {c["name"] for c in schema.get("columns", [])}
    except Exception:
        logger.warning("schema.yaml 로드 실패 — 전체 컬럼 기준으로 중복 탐지")
        schema_cols = set()
    original_cols = sorted(schema_cols & set(df.columns))

    # Why: 표준 컬럼이 하나도 없으면 전체 컬럼으로 fallback
    if not original_cols:
        original_cols = list(df.columns)

    return int(df[original_cols].duplicated().sum())


# ── 오케스트레이터 ────────────────────────────────────────────


def validate_accounting(
    df: pd.DataFrame, tolerance: float = 0.01
) -> AccountingResult:
    """L2 회계 규칙 검증 — 3개 서브함수 일괄 실행.

    Args:
        df: L1 검증 통과된 DataFrame
        tolerance: 대차일치 허용오차 (부동소수점 안전장치, 기본 0.01)

    Returns:
        AccountingResult: 대차일치 + 일자 연속성 + 중복 행 종합 결과
    """
    bal_ok, bal_diff, unbal_docs = check_balance(df, tolerance=tolerance)
    cont_ok, missing = check_date_continuity(df)
    dup_count = check_duplicates(df)

    result = AccountingResult(
        balance_check=bal_ok,
        balance_diff=bal_diff,
        unbalanced_docs=unbal_docs,
        date_continuity=cont_ok,
        missing_dates=missing,
        duplicate_entries=dup_count,
    )

    # Why: 운영자가 L2 결과를 한눈에 파악하도록 요약 로깅
    if bal_ok and cont_ok and dup_count == 0:
        logger.info("L2 회계 검증 통과 — %d행", len(df))
    else:
        issues = []
        if not bal_ok:
            issues.append(f"대차불일치 {len(unbal_docs)}건")
        if not cont_ok:
            issues.append(f"영업일 누락 {len(missing)}일")
        if dup_count > 0:
            issues.append(f"중복 {dup_count}행")
        logger.warning("L2 회계 검증 이슈: %s", ", ".join(issues))

    return result
