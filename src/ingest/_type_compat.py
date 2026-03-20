"""타입 호환성 검증 모듈 — 소스 데이터 타입과 스키마 기대 타입 비교.

fuzzy match 후보의 타입 비호환을 사전 차단하여 오매핑을 방지한다.
성능 최적화: numeric fast path → 정규식 날짜 fast path → pd.to_datetime 폴백.
"""

from __future__ import annotations

import re

import pandas as pd

# 날짜 정규식 — pd.to_datetime 호출 최소화용
_DATE_PATTERN = re.compile(r"^\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}$|^\d{8}$")

# 타입 호환 매트릭스: target ← {허용 source 타입들}
_COMPAT_MATRIX: dict[str, set[str]] = {
    "float": {"float", "int", "unknown"},
    "date": {"date", "unknown"},
    "int": {"int", "float", "unknown"},
    "str": {"float", "int", "date", "str", "unknown"},  # str은 모든 타입 수용
    "bool": {"str", "unknown"},
}


def infer_column_type(series: pd.Series) -> str:
    """상위 100행 샘플에서 실제 데이터 타입을 추론.

    Returns: "int" | "float" | "date" | "str" | "unknown"
    """
    sample = series.dropna().head(100)
    if len(sample) == 0:
        return "unknown"

    # 1차: numeric fast path (가장 빠름)
    numeric = pd.to_numeric(sample, errors="coerce")
    numeric_rate = numeric.notna().sum() / len(sample)
    if numeric_rate > 0.5:
        non_null = numeric.dropna()
        # % 1 == 0 으로 정수 판별 — astype(int)는 큰 float에서 OverflowError 위험
        try:
            if len(non_null) > 0 and (non_null % 1 == 0).all():
                return "int"
        except (TypeError, OverflowError):
            pass
        return "float"

    # 2차: 정규식 날짜 fast path — pd.to_datetime보다 훨씬 빠름
    str_sample = sample.astype(str).str.strip()
    regex_date_rate = str_sample.str.match(_DATE_PATTERN).sum() / len(sample)
    if regex_date_rate > 0.5:
        return "date"

    # 3차: 정규식으로 일부만 날짜 패턴이면 pd.to_datetime 정밀 검사
    if regex_date_rate > 0.1:
        date_parsed = pd.to_datetime(str_sample, errors="coerce", format="mixed")
        if date_parsed.notna().sum() / len(sample) > 0.5:
            return "date"

    return "str"


def validate_type_compatibility(source_type: str, target_type: str) -> bool:
    """소스 타입이 타겟 타입과 호환되는지 검증.

    unknown은 모든 타입과 호환 (100% NaN 유령 컬럼 대응).
    """
    if source_type == "unknown":
        return True
    allowed = _COMPAT_MATRIX.get(target_type, set())
    return source_type in allowed
