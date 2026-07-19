"""컬럼 dtype → 4분류 매핑.

Why: 프로파일러 디스패치 기준. boolean을 numeric보다 먼저 체크해야
pandas의 bool → numeric 암시적 변환 오분류를 방지한다.
"""

from __future__ import annotations

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

# 유효한 dtype_group 값
DTYPE_GROUPS = frozenset({"numeric", "categorical", "datetime", "boolean"})


def classify_column(series: pd.Series) -> str:
    """Series의 dtype을 4분류 중 하나로 매핑.

    분류 우선순위:
    1. boolean  — is_bool_dtype (bool, boolean, BooleanDtype)
    2. datetime — is_datetime64_any_dtype
    3. numeric  — is_numeric_dtype (int, float, Int64 등)
    4. categorical — 그 외 전부 (object, string, category 등)
    """
    if is_bool_dtype(series):
        return "boolean"
    if is_datetime64_any_dtype(series):
        return "datetime"
    if is_numeric_dtype(series):
        return "numeric"
    return "categorical"
