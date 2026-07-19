"""수치형 컬럼 프로파일링 — mean/std/IQR/outlier 등.

이상치 기준: Tukey's fence (IQR × 1.5) — 감사 도메인 표준.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def profile_numeric(series: pd.Series) -> dict:
    """수치형 Series → 통계 dict. 전체 NaN이면 모든 값 None."""
    clean = series.dropna()
    if len(clean) == 0:
        return _empty_numeric()

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1

    # 이상치: std=0 (모든 값 동일)이면 이상치 없음
    std_val = float(clean.std())
    if std_val == 0.0 or iqr == 0.0:
        outlier_count = 0
    else:
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outlier_count = int(((clean < lower) | (clean > upper)).sum())

    return {
        "mean": _to_native(clean.mean()),
        "median": _to_native(clean.median()),
        "std": _to_native(std_val),
        "skewness": _to_native(clean.skew()),
        "kurtosis": _to_native(clean.kurtosis()),
        "q1": _to_native(q1),
        "q3": _to_native(q3),
        "iqr": _to_native(iqr),
        "outlier_count": outlier_count,
        "min_val": _to_native(clean.min()),
        "max_val": _to_native(clean.max()),
    }


def _empty_numeric() -> dict:
    """전체 NaN일 때 반환할 빈 dict."""
    return {
        k: None
        for k in (
            "mean",
            "median",
            "std",
            "skewness",
            "kurtosis",
            "q1",
            "q3",
            "iqr",
            "outlier_count",
            "min_val",
            "max_val",
        )
    }


def _to_native(val):
    """numpy 스칼라 → Python 네이티브 변환."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return val
