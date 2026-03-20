"""boolean 컬럼 프로파일링 — true_rate.

Why: feature 모듈의 10개 bool 파생변수 분포 확인용.
NaN 제외 기준으로 true 비율을 산출한다.
"""

from __future__ import annotations

import pandas as pd


def profile_boolean(series: pd.Series) -> dict:
    """boolean Series → 통계 dict. 전체 NaN이면 true_rate=None."""
    clean = series.dropna()
    if len(clean) == 0:
        return {"true_rate": None}

    # Why: nullable BooleanDtype의 sum()이 pd.NA를 반환할 수 있어 float() 변환 방어
    total = clean.sum()
    if pd.isna(total):
        return {"true_rate": None}
    true_rate = float(total) / len(clean)
    return {"true_rate": round(true_rate, 6)}
