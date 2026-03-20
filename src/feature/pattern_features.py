"""전표 속성 기반 패턴 매칭 파생변수 5개 생성 모듈.

B01(매출계정), B08(수기전표), B10(관계사), B11/C06(가계정), C07(Benford) 룰 대응.
감사 업무 룰(키워드/코드)은 config/audit_rules.yaml에서 로드 — 함수 인자로 주입.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

# 가계정 키워드 검색 대상 텍스트 컬럼
# gl_account_name: Phase 2 스키마 확장 시 자동 반영 (existing_cols 필터로 안전)
_SUSPENSE_TEXT_COLS = ["line_text", "header_text", "gl_account_name"]


# ── Public feature functions ─────────────────────────────────────


def add_is_manual_je(
    df: pd.DataFrame,
    manual_codes: list[str],
) -> pd.DataFrame:
    """B08: source 컬럼이 수기 전표 코드와 매칭되면 True.

    감사 관점: 수기 전표는 자동화 통제 우회 — 부정 전표 가능성.
    manual_codes는 ERP마다 다름 (SAP: SA, Oracle: Manual 등).
    """
    if "source" not in df.columns:
        logger.warning("source 컬럼 누락 — is_manual_je를 전체 False로 설정")
        df["is_manual_je"] = False
        return df

    if not manual_codes:
        logger.warning("manual_source_codes 비어있음 — is_manual_je를 전체 False로 설정")
        df["is_manual_je"] = False
        return df

    # 정규화: 대소문자·공백 무시
    normalized = df["source"].astype(str).str.strip().str.lower()
    codes_lower = [c.strip().lower() for c in manual_codes]
    df["is_manual_je"] = normalized.isin(codes_lower).where(df["source"].notna(), False)
    return df


def add_is_intercompany(
    df: pd.DataFrame,
    identifiers: list[str],
) -> pd.DataFrame:
    """B10: 관계사 거래 여부. gl_account 또는 company_code에서 식별자 매칭.

    감사 관점: 관계사 거래는 순환거래·이전가격 위험.
    identifiers는 회사별 관계사 코드 목록 — UI에서 입력.
    """
    if not identifiers:
        logger.warning("intercompany_identifiers 비어있음 — is_intercompany를 전체 False로 설정")
        df["is_intercompany"] = False
        return df

    has_gl = "gl_account" in df.columns
    has_cc = "company_code" in df.columns

    if not has_gl and not has_cc:
        logger.warning(
            "gl_account, company_code 컬럼 모두 없음 — is_intercompany를 전체 False로 설정",
        )
        df["is_intercompany"] = False
        return df

    result = pd.Series(False, index=df.index)
    prefix_tuple = tuple(identifiers)

    # gl_account(Int64 가능) → str 변환 후 startswith 매칭
    if has_gl:
        gl_str = df["gl_account"].astype(str).str.strip()
        result = result | gl_str.str.startswith(prefix_tuple).fillna(False)

    # company_code(str)에서도 startswith 매칭 (contains는 오탐 위험)
    if has_cc:
        cc_str = df["company_code"].astype(str).str.strip()
        result = result | cc_str.str.startswith(prefix_tuple).fillna(False)

    df["is_intercompany"] = result
    return df


def add_is_revenue_account(
    df: pd.DataFrame,
    prefixes: list[str],
) -> pd.DataFrame:
    """B01: gl_account가 매출 계정(prefix 매칭)이면 True.

    감사 관점: 매출 계정 이상 변동 탐지의 기준 필터.
    K-IFRS 기준 4xxx가 표준이나, 회사마다 다를 수 있음.
    """
    if "gl_account" not in df.columns:
        logger.warning("gl_account 컬럼 누락 — is_revenue_account를 전체 False로 설정")
        df["is_revenue_account"] = False
        return df

    if not prefixes:
        logger.warning("revenue_account_prefixes 비어있음 — is_revenue_account를 전체 False로 설정")
        df["is_revenue_account"] = False
        return df

    gl_str = df["gl_account"].astype(str).str.strip()
    df["is_revenue_account"] = gl_str.str.startswith(tuple(prefixes)).fillna(False)
    return df


def add_first_digit(df: pd.DataFrame) -> pd.DataFrame:
    """C07: 금액의 첫 번째 유효숫자(1~9) 추출 — Benford 분석 입력.

    str.extract(r"([1-9])") 사용 — 과학표기법, 소수, 음수 모두 안전 처리.
    0원 → NaN (Benford 분석 대상 외).
    """
    # 금액 컬럼 부재 시 NaN fallback (다른 함수와 패턴 일관성)
    required = ["debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("%s 컬럼 누락 — first_digit를 전체 NaN으로 설정", missing)
        df["first_digit"] = pd.array([pd.NA] * len(df), dtype="Int64")
        return df

    # 차변/대변 중 큰 절대값을 대표 금액으로
    amount = df[["debit_amount", "credit_amount"]].fillna(0).abs().max(axis=1)

    # 0원 마스킹: Benford 분석에서 0은 의미 없음
    amount = amount.where(amount > 0)

    # 문자열 변환 후 첫 번째 1~9 숫자 추출 (과학표기법·소수 안전)
    digits = amount.astype(str).str.extract(r"([1-9])", expand=False)
    df["first_digit"] = pd.to_numeric(digits, errors="coerce").astype("Int64")
    return df


def add_is_suspense_account(
    df: pd.DataFrame,
    keywords: list[str],
) -> pd.DataFrame:
    """B11/C06: 가계정·미결산 계정 키워드 매칭.

    감사 관점: 가수금/가지급/미결산 등은 장기 미정리 시 부정 은폐 수단.
    keywords를 단일 정규식으로 컴파일하여 성능 최적화.
    """
    if not keywords:
        logger.warning("suspense_keywords 비어있음 — is_suspense_account를 전체 False로 설정")
        df["is_suspense_account"] = False
        return df

    # 키워드 → 정규식 컴파일 (실패 시 escape 폴백)
    safe_patterns = []
    for kw in keywords:
        try:
            re.compile(kw)
            safe_patterns.append(kw)
        except re.error:
            escaped = re.escape(kw)
            logger.warning("정규식 컴파일 실패: '%s' → re.escape 폴백: '%s'", kw, escaped)
            safe_patterns.append(escaped)

    combined = "|".join(safe_patterns)

    # 존재하는 텍스트 컬럼에서만 매칭 (OR 결합)
    existing_cols = [c for c in _SUSPENSE_TEXT_COLS if c in df.columns]
    if not existing_cols:
        logger.warning(
            "검사 대상 컬럼(%s) 없음 — is_suspense_account를 전체 False로 설정",
            _SUSPENSE_TEXT_COLS,
        )
        df["is_suspense_account"] = False
        return df

    result = pd.Series(False, index=df.index)
    for col in existing_cols:
        result = result | df[col].astype(str).str.contains(combined, na=False, regex=True)

    df["is_suspense_account"] = result
    return df


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_pattern_features(
    df: pd.DataFrame,
    rules: dict | None = None,
) -> pd.DataFrame:
    """패턴 파생변수 5개를 한번에 추가. engine.py 진입점.

    rules: audit_rules.yaml["patterns"] dict. None이면 자동 로드.
    """
    if rules is None:
        from config.settings import get_audit_rules
        rules = get_audit_rules()["patterns"]

    add_is_manual_je(df, rules.get("manual_source_codes", []))
    add_is_intercompany(df, rules.get("intercompany_identifiers", []))
    add_is_revenue_account(df, rules.get("revenue_account_prefixes", []))
    add_first_digit(df)
    add_is_suspense_account(df, rules.get("suspense_keywords", []))

    return df
