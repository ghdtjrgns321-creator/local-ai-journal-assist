"""타입 캐스팅 모듈 — schema.yaml 기반으로 DataFrame 컬럼 dtype 변환.

column_mapper 이후 모든 컬럼이 object(str) 상태이므로,
감사 탐지 룰이 요구하는 float/datetime/int/bool로 변환한다.
Parquet 등 이미 올바른 타입이면 스킵(fast path).

정규화 규칙(통화 기호, null 값, 불리언 등)은 config/cleaning.yaml에 정의.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import numpy as np
import pandas as pd

from config.settings import AuditSettings, get_cleaning_config, get_schema, get_settings
from src.ingest.models import CastingResult

logger = logging.getLogger(__name__)

# ── 정규식 패턴 (고정 — config 불필요) ───────────────────────
# 괄호 음수 표기: (1,234) → -1234
_PAREN_NEG_RE = re.compile(r"^\((.+)\)$")
# 제로 폭 문자 제거용 (ZWSP, ZWNJ, ZWJ, BOM 등)
# Why: Excel 복사-붙여넣기 시 눈에 보이지 않는 유니코드 문자가 삽입되어
# "350\u200B000"처럼 숫자 변환을 방해한다.
# \u00ad(Soft Hyphen)는 렌더링 아티팩트로 간주하여 제거함.
# 만약 "-금액" 패턴에서 음수 부호가 사라지는 오류 발생 시 이 라인을 먼저 의심할 것.
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]")
# 한국어 날짜: 2025년 3월 19일
_KOREAN_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
# 8자리 숫자: 20250319
_COMPACT_DATE_RE = re.compile(r"^\d{8}$")
# 과학적 표기법: 2E+11, 2.00001E+11 등
_SCI_NOTATION_RE = re.compile(r"^\d+\.?\d*[eE]\+?\d+$")


# ── config 기반 정규식 빌더 ──────────────────────────────────

def _build_currency_re(cleaning_config: dict | None = None) -> re.Pattern:
    """cleaning.yaml의 통화 기호·단위로 정규식 생성.

    Why: @lru_cache 제거 — dict 파라미터 해시 불가.
         cast_dataframe()에서 1회 호출 후 지역변수로 재사용.
    """
    cfg = cleaning_config or get_cleaning_config()
    amount_cfg = cfg["amount"]
    symbols = amount_cfg["currency_symbols"]
    words = amount_cfg["currency_words"]
    # 문자 클래스: [₩$¥€\\]
    char_class = "[" + re.escape("".join(symbols)) + "]"
    # 단어 OR: 원|USD|KRW|...
    word_alt = "|".join(re.escape(w) for w in words)
    return re.compile(f"{char_class}|{word_alt}")


def _get_amount_null_values(cleaning_config: dict | None = None) -> frozenset[str]:
    """cleaning.yaml에서 금액 null 값 목록 로드."""
    cfg = cleaning_config or get_cleaning_config()
    return frozenset(cfg["amount"]["null_values"])


# ── 내부 헬퍼 ────────────────────────────────────────────────

def _is_already_correct_type(series: pd.Series, expected: str) -> bool:
    """이미 올바른 dtype이면 True — Parquet fast path."""
    dtype = series.dtype
    if expected == "float":
        return pd.api.types.is_float_dtype(dtype)
    if expected in ("date", "datetime"):
        return pd.api.types.is_datetime64_any_dtype(dtype)
    if expected == "int":
        return pd.api.types.is_integer_dtype(dtype)
    if expected == "bool":
        return pd.api.types.is_bool_dtype(dtype)
    # str은 object/string dtype이면 이미 올바름
    if expected == "str":
        return pd.api.types.is_object_dtype(dtype) or pd.api.types.is_string_dtype(dtype)
    return False


def _build_required_set(schema_columns: list[dict]) -> set[str]:
    """schema_columns에서 required=True인 컬럼명 집합을 한 번에 빌드."""
    return {col["name"] for col in schema_columns if col.get("required", False)}


def _safe_sci_to_int(val: str) -> str:
    """과학적 표기법 → 정수 문자열 복원. 실패 시 원본 반환."""
    try:
        return str(int(float(val)))
    except (ValueError, OverflowError):
        return val


# ── 공개 캐스터 함수 ─────────────────────────────────────────

def cast_amount(series: pd.Series, cleaning_config: dict | None = None) -> pd.Series:
    """금액 컬럼 → float64 변환.

    처리 순서: 통화기호 제거 → 대시/빈값 → 괄호음수 → 천단위/소수점 정규화 → to_numeric.
    decimal_format 설정: "period"(미국/한국, 기본) | "comma"(유럽식 1.234,56).
    """
    # 이미 numeric이면 float64로만 변환 (Parquet fast path)
    if pd.api.types.is_numeric_dtype(series.dtype):
        return series.astype("float64")

    cfg = cleaning_config or get_cleaning_config()
    amount_cfg = cfg["amount"]

    s = series.astype(str)

    # 제로 폭 문자 제거 (ZWSP 등 — 눈에 안 보이지만 to_numeric 차단)
    s = s.str.replace(_ZERO_WIDTH_RE, "", regex=True)
    # 통화 기호·단위 제거 (cleaning.yaml 기반)
    s = s.str.replace(_build_currency_re(cleaning_config), "", regex=True)
    # 공백 제거
    s = s.str.strip()
    # 괄호 음수: (1,234) → -1,234
    s = s.str.replace(
        _PAREN_NEG_RE, lambda m: "-" + m.group(1), regex=True,
    )
    # 천단위 구분자·소수점 정규화 (locale별 분기)
    decimal_fmt = amount_cfg.get("decimal_format", "period")
    if decimal_fmt == "comma":
        # 유럽식: 점(천단위) 제거 → 쉼표(소수점)를 점으로 치환
        s = s.str.replace(".", "", regex=False)
        s = s.str.replace(",", ".", regex=False)
    else:
        # 미국/한국식 (기본): 쉼표(천단위) 제거
        s = s.str.replace(",", "", regex=False)
    # null 값 치환 (cleaning.yaml 기반)
    null_mask = s.isin(frozenset(amount_cfg["null_values"]))
    s = s.where(~null_mask, np.nan)

    return pd.to_numeric(s, errors="coerce").astype("float64")


def cast_date(
    series: pd.Series,
    settings: AuditSettings | None = None,
    cleaning_config: dict | None = None,
) -> pd.Series:
    """날짜 컬럼 → datetime64[ns] 변환.

    시도 순서: 이미 datetime → ISO8601 → 한국어 → 8자리 → Excel serial → 폴백.
    """
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return series

    settings = settings or get_settings()
    cfg = cleaning_config or get_cleaning_config()
    date_cfg = cfg["date"]
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

    # 4차: Excel serial number (cleaning.yaml 범위 기반)
    remaining = s[unconverted_mask]
    numeric_vals = pd.to_numeric(remaining, errors="coerce")
    excel_min = date_cfg["excel_serial_min"]
    excel_max = date_cfg["excel_serial_max"]
    excel_mask_inner = numeric_vals.between(excel_min, excel_max)
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


def _cast_str(series: pd.Series, cleaning_config: dict | None = None) -> pd.Series:
    """문자열 컬럼 → str 변환. Excel에서 int64로 읽힌 계정코드 등 대응.

    NaN/NA는 pd.NA로 유지하여 결측 정보를 보존한다.
    (빈 문자열 변환은 하지 않음 — L1 검증에서 처리)
    float64 중 정수값(1000.0)은 ".0" 제거하여 "1000"으로 변환.
    과학적 표기법(2E+11)은 감지 후 best-effort 복원 시도.
    """
    # NaN 마스크 먼저 확보 (astype(str) 시 "nan" 문자열로 변환되므로)
    null_mask = series.isna()

    # float64인데 실질적으로 정수인 경우 → Int64 경유하여 ".0" 방지
    # (예: NaN 혼합 int 컬럼이 float64로 승격된 경우)
    if pd.api.types.is_float_dtype(series.dtype):
        # 비결측값이 모두 정수이면 Int64 경유
        non_null = series.dropna()
        if len(non_null) == 0 or (non_null == non_null.astype(int)).all():
            int_series = series.astype("Int64")
            result = int_series.astype(str).str.strip()
            # Int64의 NA는 "<NA>" 문자열로 변환되므로 pd.NA로 복원
            result = result.where(~null_mask, pd.NA)
            return result

    result = series.astype(str).str.strip()
    # NaN이었던 위치를 pd.NA로 복원
    result = result.where(~null_mask, pd.NA)

    # 과학적 표기법 감지 + best-effort 복원 (cleaning.yaml 설정 기반)
    cfg = cleaning_config or get_cleaning_config()
    str_cfg = cfg.get("string", {})
    if str_cfg.get("detect_scientific_notation", False):
        non_null_vals = result.dropna()
        if len(non_null_vals) > 0:
            sci_mask = non_null_vals.str.match(_SCI_NOTATION_RE, na=False)
            if sci_mask.any():
                sci_count = int(sci_mask.sum())
                logger.warning(
                    "문자열 컬럼에서 과학적 표기법 %d건 감지 — "
                    "Excel에서 긴 숫자 ID가 손상되었을 수 있음 (정밀도 손실 가능)",
                    sci_count,
                )
                # best-effort 복원: "2E+11" → "200000000000" (벡터화)
                if str_cfg.get("recover_scientific_notation", False):
                    sci_idx = non_null_vals[sci_mask].index
                    result.loc[sci_idx] = result.loc[sci_idx].apply(_safe_sci_to_int)

    return result


def _cast_bool(series: pd.Series, cleaning_config: dict | None = None) -> pd.Series:
    """불리언 컬럼 → boolean(nullable) 변환."""
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.astype("boolean")

    cfg = cleaning_config or get_cleaning_config()
    bool_cfg = cfg["boolean"]
    true_vals = set(bool_cfg["true_values"])
    false_vals = set(bool_cfg["false_values"])

    s = series.astype(str).str.strip().str.lower()

    # 벡터화: isin으로 마스크 생성 후 일괄 할당 (1M행 성능 보장)
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    result = result.where(~s.isin(true_vals), True)
    result = result.where(~s.isin(false_vals), False)
    return result


# ── 차/대변 통합 ─────────────────────────────────────────────

def unify_debit_credit(
    df: pd.DataFrame,
    cleaning_config: dict | None = None,
) -> tuple[pd.DataFrame, list[str]]:
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

    cfg = cleaning_config or get_cleaning_config()
    dc_cfg = cfg["dc_indicator"]
    result = df.copy()
    amount = result["amount"].astype("float64")

    # Case B: amount + dc_indicator
    if "dc_indicator" in cols:
        indicator = result["dc_indicator"].astype(str).str.strip().str.upper()
        is_debit = indicator.isin(dc_cfg["debit"])
        is_credit = indicator.isin(dc_cfg["credit"])

        result["debit_amount"] = np.where(is_debit, amount.abs(), 0.0)
        result["credit_amount"] = np.where(is_credit, amount.abs(), 0.0)
        return result, warnings

    # Case C: 부호 기반 (양수=차변, 음수=대변)
    result["debit_amount"] = np.where(amount >= 0, amount, 0.0)
    result["credit_amount"] = np.where(amount < 0, amount.abs(), 0.0)
    warnings.append("amount 부호 기반 차대변 분리 — dc_indicator 없어 추정값")
    return result, warnings


# ── 퍼사드 ───────────────────────────────────────────────────

# Why: 외부 직접 호출 및 테스트용 폴백 디스패치 맵.
# cast_dataframe() 내부에서는 cleaning_config/settings를 주입하는 local caster_map을 사용한다.
_CASTER_MAP: dict[str, Callable[[pd.Series], pd.Series]] = {
    "float": cast_amount,
    "date": cast_date,
    "datetime": cast_date,  # schema.yaml posting_date 등 시분초 포함 날짜
    "int": _cast_int,
    "bool": _cast_bool,
    "str": _cast_str,
}


def cast_dataframe(
    df: pd.DataFrame,
    schema: dict | None = None,
    settings: AuditSettings | None = None,
    cleaning_config: dict | None = None,
) -> CastingResult:
    """DataFrame 전체를 schema.yaml 기반으로 타입 캐스팅.

    파이프라인 단일 진입점. column_mapper 이후 호출한다.
    """
    schema = schema or get_schema()
    settings = settings or get_settings()
    cleaning_config = cleaning_config or get_cleaning_config()
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
    high_null_columns: list[str] = []
    empty_columns: list[str] = []

    # Why: cleaning_config/settings 주입을 위해 local caster map 구성 (루프 밖 1회)
    caster_map: dict[str, Callable[[pd.Series], pd.Series]] = {
        "float": lambda s: cast_amount(s, cleaning_config=cleaning_config),
        "date": lambda s: cast_date(s, settings=settings, cleaning_config=cleaning_config),
        "datetime": lambda s: cast_date(s, settings=settings, cleaning_config=cleaning_config),
        "int": _cast_int,
        "bool": lambda s: _cast_bool(s, cleaning_config=cleaning_config),
        "str": lambda s: _cast_str(s, cleaning_config=cleaning_config),
    }

    for col_name in result_df.columns:
        expected_type = type_map.get(col_name)
        if expected_type is None:
            continue

        series = result_df[col_name]
        original_dtype = str(series.dtype)

        # 이미 올바른 타입이면 스킵
        if _is_already_correct_type(series, expected_type):
            skipped.append(col_name)
            continue

        caster = caster_map.get(expected_type)
        if caster is None:
            warnings.append(f"알 수 없는 타입 '{expected_type}' — {col_name} 스킵")
            continue

        try:
            casted = caster(series)
            result_df[col_name] = casted

            new_dtype = str(casted.dtype)
            cast_summary[col_name] = f"{original_dtype}→{new_dtype}"

            # 결측률 3단계 분기: 유령 컬럼 → 오매핑 의심 → 경고
            if len(casted) > 0:
                original_all_nan = series.isna().all()
                null_ratio = casted.isna().sum() / len(casted)

                if original_all_nan:
                    # 원본부터 100% NaN — 유령 컬럼, 조용히 분리 (경고 없음)
                    empty_columns.append(col_name)
                elif null_ratio > settings.casting_null_demote_threshold:
                    # 캐스팅 후 90%+ 결측 — 오매핑 의심
                    high_null_columns.append(col_name)
                    warnings.append(
                        f"{col_name}: 캐스팅 후 결측률 {null_ratio:.1%} — 오매핑 의심"
                    )
                elif null_ratio > settings.casting_null_warn_threshold:
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
        result_df, unify_warnings = unify_debit_credit(result_df, cleaning_config=cleaning_config)
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
        high_null_columns=high_null_columns,
        empty_columns=empty_columns,
        success=success,
    )
