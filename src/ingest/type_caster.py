"""타입 캐스팅 모듈 — schema.yaml 기반으로 DataFrame 컬럼 dtype 변환.

column_mapper 이후 모든 컬럼이 object(str) 상태이므로,
감사 탐지 룰이 요구하는 float/datetime/int/bool로 변환한다.
Parquet 등 이미 올바른 타입이면 스킵(fast path).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import numpy as np
import pandas as pd

from config.settings import get_schema, get_settings
from src.ingest.models import CastingResult

logger = logging.getLogger(__name__)

# ── 정규식 패턴 ──────────────────────────────────────────────
# 통화 기호·단위 제거용 (₩, $, ¥, €, 원, USD, KRW 등)
_CURRENCY_RE = re.compile(r"[₩$¥€]|원|USD|KRW|JPY|EUR")
# 괄호 음수 표기: (1,234) → -1234
_PAREN_NEG_RE = re.compile(r"^\((.+)\)$")
# 한국어 날짜: 2025년 3월 19일
_KOREAN_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
# 8자리 숫자: 20250319
_COMPACT_DATE_RE = re.compile(r"^\d{8}$")


# ── 내부 헬퍼 ────────────────────────────────────────────────

def _is_already_correct_type(series: pd.Series, expected: str) -> bool:
    """이미 올바른 dtype이면 True — Parquet fast path."""
    dtype = series.dtype
    if expected == "float":
        return pd.api.types.is_float_dtype(dtype)
    if expected == "date":
        return pd.api.types.is_datetime64_any_dtype(dtype)
    if expected == "int":
        return pd.api.types.is_integer_dtype(dtype)
    if expected == "bool":
        return pd.api.types.is_bool_dtype(dtype)
    # str은 object 그대로 유지
    return expected == "str"


def _build_required_set(schema_columns: list[dict]) -> set[str]:
    """schema_columns에서 required=True인 컬럼명 집합을 한 번에 빌드."""
    return {col["name"] for col in schema_columns if col.get("required", False)}


# ── 공개 캐스터 함수 ─────────────────────────────────────────

def cast_amount(series: pd.Series) -> pd.Series:
    """금액 컬럼 → float64 변환.

    처리 순서: 통화기호 제거 → 대시/빈값 → 괄호음수 → 쉼표 제거 → to_numeric.
    """
    # 이미 numeric이면 float64로만 변환 (Parquet fast path)
    if pd.api.types.is_numeric_dtype(series.dtype):
        return series.astype("float64")

    s = series.astype(str)

    # 통화 기호·단위 제거
    s = s.str.replace(_CURRENCY_RE, "", regex=True)
    # 공백 제거
    s = s.str.strip()
    # 괄호 음수: (1,234) → -1,234
    s = s.str.replace(
        _PAREN_NEG_RE, lambda m: "-" + m.group(1), regex=True,
    )
    # 쉼표 제거
    s = s.str.replace(",", "", regex=False)
    # 빈 문자열, 대시(—, –, -), 'nan' → NaN (str 연산 완료 후 치환)
    null_mask = s.isin(["", "-", "—", "–", "nan", "None", "none"])
    s = s.where(~null_mask, np.nan)

    return pd.to_numeric(s, errors="coerce").astype("float64")


def cast_date(series: pd.Series) -> pd.Series:
    """날짜 컬럼 → datetime64[ns] 변환.

    시도 순서: 이미 datetime → ISO8601 → 한국어 → 8자리 → Excel serial → 폴백.
    """
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return series

    settings = get_settings()
    s = series.copy()

    # 1차: ISO8601 시도
    result = pd.to_datetime(s, format="ISO8601", errors="coerce")
    unconverted_mask = result.isna() & s.notna() & (s.astype(str).str.strip() != "")

    if unconverted_mask.sum() == 0:
        return result

    # 2차: 한국어 날짜 변환 (2025년 3월 19일 → 2025-03-19)
    remaining = s[unconverted_mask].astype(str)
    korean_replaced = remaining.str.replace(
        _KOREAN_DATE_RE, r"\1-\2-\3", regex=True,
    )
    korean_parsed = pd.to_datetime(korean_replaced, errors="coerce")
    result.loc[unconverted_mask] = korean_parsed.values
    unconverted_mask = result.isna() & s.notna() & (s.astype(str).str.strip() != "")

    if unconverted_mask.sum() == 0:
        return result

    # 3차: 8자리 숫자 (20250319)
    remaining = s[unconverted_mask].astype(str).str.strip()
    compact_mask_inner = remaining.str.match(_COMPACT_DATE_RE)
    if compact_mask_inner.any():
        compact_idx = remaining[compact_mask_inner].index
        compact_parsed = pd.to_datetime(
            remaining[compact_mask_inner], format="%Y%m%d", errors="coerce",
        )
        result.loc[compact_idx] = compact_parsed.values

    unconverted_mask = result.isna() & s.notna() & (s.astype(str).str.strip() != "")

    if unconverted_mask.sum() == 0:
        return result

    # 4차: Excel serial number
    # 범위: 30000 ≈ 1982-02-18, 60000 ≈ 2064-04-26
    # 이 범위 밖의 숫자(예: 2025, 1110 등 계정코드)가 날짜로 오인되는 것을 방지
    remaining = s[unconverted_mask]
    numeric_vals = pd.to_numeric(remaining, errors="coerce")
    excel_mask_inner = numeric_vals.between(30000, 60000)
    if excel_mask_inner.any():
        excel_idx = numeric_vals[excel_mask_inner].index
        excel_parsed = pd.to_datetime(
            numeric_vals[excel_mask_inner],
            origin="1899-12-30", unit="D", errors="coerce",
        )
        result.loc[excel_idx] = excel_parsed.values

    unconverted_mask = result.isna() & s.notna() & (s.astype(str).str.strip() != "")

    if unconverted_mask.sum() == 0:
        return result

    # 5차: 최종 폴백
    remaining = s[unconverted_mask]
    fallback = pd.to_datetime(
        remaining, errors="coerce", dayfirst=settings.casting_date_dayfirst,
    )
    result.loc[unconverted_mask] = fallback.values

    return result


def _cast_int(series: pd.Series) -> pd.Series:
    """정수 컬럼 → Int64(nullable) 변환."""
    if pd.api.types.is_integer_dtype(series.dtype):
        return series.astype("Int64")

    # 소수점 문자열("2025.0") 대응: float 경유
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.round().astype("Int64")


def _cast_bool(series: pd.Series) -> pd.Series:
    """불리언 컬럼 → boolean(nullable) 변환."""
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.astype("boolean")

    s = series.astype(str).str.strip().str.lower()
    true_vals = {"true", "1", "1.0", "yes", "y", "t"}
    false_vals = {"false", "0", "0.0", "no", "n", "f"}

    # 벡터화: isin으로 마스크 생성 후 일괄 할당 (1M행 성능 보장)
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    result = result.where(~s.isin(true_vals), True)
    result = result.where(~s.isin(false_vals), False)
    return result


# ── 차/대변 통합 ─────────────────────────────────────────────

def unify_debit_credit(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """차변/대변 분리 로직. 원본 df를 변경하지 않고 복사본 반환.

    Case A: debit_amount + credit_amount 이미 존재 → 통과
    Case B: amount + dc_indicator(D/C/S/H) → 분리
    Case C: amount만 (양수=차변, 음수=대변) → 분리
    해당 없음 → 원본 반환 + warning
    """
    warnings: list[str] = []
    cols = set(df.columns)

    # Case A: 이미 분리되어 있음
    if "debit_amount" in cols and "credit_amount" in cols:
        return df, warnings

    if "amount" not in cols:
        warnings.append("amount/debit_amount/credit_amount 컬럼 없음 — 차대변 통합 스킵")
        return df, warnings

    result = df.copy()
    amount = result["amount"].astype("float64")

    # Case B: amount + dc_indicator
    if "dc_indicator" in cols:
        indicator = result["dc_indicator"].astype(str).str.strip().str.upper()
        # D/S = 차변, C/H = 대변
        is_debit = indicator.isin(["D", "S"])
        is_credit = indicator.isin(["C", "H"])

        result["debit_amount"] = np.where(is_debit, amount.abs(), 0.0)
        result["credit_amount"] = np.where(is_credit, amount.abs(), 0.0)
        return result, warnings

    # Case C: 부호 기반 (양수=차변, 음수=대변)
    result["debit_amount"] = np.where(amount >= 0, amount, 0.0)
    result["credit_amount"] = np.where(amount < 0, amount.abs(), 0.0)
    warnings.append("amount 부호 기반 차대변 분리 — dc_indicator 없어 추정값")
    return result, warnings


# ── 퍼사드 ───────────────────────────────────────────────────

# schema type → 캐스터 디스패치 맵
_CASTER_MAP: dict[str, Callable[[pd.Series], pd.Series]] = {
    "float": cast_amount,
    "date": cast_date,
    "int": _cast_int,
    "bool": _cast_bool,
}


def cast_dataframe(
    df: pd.DataFrame,
    schema: dict | None = None,
) -> CastingResult:
    """DataFrame 전체를 schema.yaml 기반으로 타입 캐스팅.

    파이프라인 단일 진입점. column_mapper 이후 호출한다.
    """
    if schema is None:
        schema = get_schema()

    settings = get_settings()
    schema_columns: list[dict] = schema.get("columns", [])

    # {컬럼명: type문자열} 맵 생성
    type_map: dict[str, str] = {
        col["name"]: col["type"] for col in schema_columns
    }

    required_set = _build_required_set(schema_columns)
    result_df = df.copy()
    errors: list[str] = []
    warnings: list[str] = []
    cast_summary: dict[str, str] = {}
    skipped: list[str] = []

    for col_name in result_df.columns:
        expected_type = type_map.get(col_name)
        if expected_type is None or expected_type == "str":
            continue

        series = result_df[col_name]
        original_dtype = str(series.dtype)

        # 이미 올바른 타입이면 스킵
        if _is_already_correct_type(series, expected_type):
            skipped.append(col_name)
            continue

        caster = _CASTER_MAP.get(expected_type)
        if caster is None:
            warnings.append(f"알 수 없는 타입 '{expected_type}' — {col_name} 스킵")
            continue

        try:
            casted = caster(series)
            result_df[col_name] = casted

            new_dtype = str(casted.dtype)
            cast_summary[col_name] = f"{original_dtype}→{new_dtype}"

            # 결측률 경고 체크
            if len(casted) > 0:
                null_ratio = casted.isna().sum() / len(casted)
                if null_ratio > settings.casting_null_warn_threshold:
                    warnings.append(
                        f"{col_name}: 캐스팅 후 결측률 {null_ratio:.1%} "
                        f"(임계 {settings.casting_null_warn_threshold:.0%} 초과)"
                    )
        except Exception as exc:
            msg = f"{col_name} 캐스팅 실패 ({expected_type}): {exc}"
            if col_name in required_set:
                errors.append(msg)
            else:
                warnings.append(msg)

    # 차/대변 통합 (debit/credit 없고 amount 있을 때)
    if "debit_amount" not in result_df.columns and "amount" in result_df.columns:
        result_df, unify_warnings = unify_debit_credit(result_df)
        warnings.extend(unify_warnings)
        # 새로 생성된 debit/credit도 float64로 캐스팅
        for col in ("debit_amount", "credit_amount"):
            if col in result_df.columns:
                result_df[col] = result_df[col].astype("float64")

    success = len(errors) == 0

    if errors:
        logger.error("타입 캐스팅 실패: %s", errors)
    if warnings:
        logger.warning("타입 캐스팅 경고: %s", warnings)
    if cast_summary:
        logger.info("타입 캐스팅 완료: %s", cast_summary)

    return CastingResult(
        data=result_df,
        errors=errors,
        warnings=warnings,
        cast_summary=cast_summary,
        skipped_columns=skipped,
        success=success,
    )
