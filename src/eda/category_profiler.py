"""범주형 컬럼 프로파일링 — cardinality/top_values.

top_values는 NaN 제외 후 상위 10개만 추출하여 성능 확보.
"""

from __future__ import annotations

import pandas as pd


def _to_hashable(value):
    if isinstance(value, list):
        return tuple(_to_hashable(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k), _to_hashable(v)) for k, v in value.items()))
    if isinstance(value, set):
        return tuple(sorted(_to_hashable(item) for item in value))
    if isinstance(value, tuple):
        return tuple(_to_hashable(item) for item in value)
    return value


def profile_categorical(series: pd.Series) -> dict:
    """범주형 Series → 통계 dict."""
    normalized = series.map(_to_hashable) if series.dtype == "object" else series
    clean = normalized.dropna()
    cardinality = int(clean.nunique())

    if len(clean) == 0:
        return {"cardinality": 0, "top_values": []}

    # 상위 10개: (값, 빈도) 튜플 리스트 — JSON 직렬화 대비
    top = normalized.value_counts(dropna=True).head(10)
    top_values = [(str(k), int(v)) for k, v in top.items()]

    return {
        "cardinality": cardinality,
        "top_values": top_values,
    }
