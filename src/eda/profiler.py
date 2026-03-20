"""EDA 오케스트레이터 — DataFrame → EDAProfile 산출.

공통 통계(missing_rate, unique_count 등)는 원본 기준,
타입별 상세 통계는 샘플(100만행 초과 시) 기준으로 산출한다.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.eda.boolean_profiler import profile_boolean
from src.eda.category_profiler import profile_categorical
from src.eda.datetime_profiler import profile_datetime
from src.eda.models import ColumnProfile, EDAProfile
from src.eda.numeric_profiler import profile_numeric
from src.eda.type_classifier import classify_column

logger = logging.getLogger(__name__)

_SAMPLING_THRESHOLD = 1_000_000
_SAMPLE_SIZE = 100_000

# dtype_group → 서브 프로파일러 디스패치
_PROFILERS = {
    "numeric": profile_numeric,
    "categorical": profile_categorical,
    "datetime": profile_datetime,
    "boolean": profile_boolean,
}


def profile_dataframe(df: pd.DataFrame) -> EDAProfile:
    """DataFrame → EDAProfile 산출. 단일 진입점.

    1. 전체 통계 (원본 기준): rows, cols, memory, duplicates
    2. 샘플링 판정: 100만행 초과 시 10만행 샘플
    3. 컬럼별 루프: 공통(원본) + 타입별(샘플) 프로파일링
    """
    total_rows = len(df)
    total_columns = len(df.columns)
    memory_bytes = int(df.memory_usage(deep=True).sum())
    duplicate_rows = int(df.duplicated().sum()) if total_rows > 0 else 0

    # 샘플링 판정
    sampled = total_rows > _SAMPLING_THRESHOLD
    sample_size = _SAMPLE_SIZE if sampled else None
    sample_df = (
        df.sample(n=_SAMPLE_SIZE, random_state=42)
        if sampled
        else df
    )

    # 컬럼별 프로파일링
    columns: dict[str, ColumnProfile] = {}
    for col in df.columns:
        orig_series = df[col]
        sample_series = sample_df[col]

        dtype_group = classify_column(orig_series)

        # 공통 통계 (원본 기준)
        missing_rate = float(orig_series.isna().mean()) if total_rows > 0 else 0.0
        unique_count = int(orig_series.nunique())
        mode_val = _safe_mode(orig_series)

        # 타입별 상세 (샘플 기준)
        profiler_fn = _PROFILERS[dtype_group]
        type_stats = profiler_fn(sample_series)

        columns[col] = ColumnProfile(
            name=col,
            dtype=str(orig_series.dtype),
            dtype_group=dtype_group,
            missing_rate=round(missing_rate, 6),
            unique_count=unique_count,
            mode=mode_val,
            **type_stats,
        )

    logger.info(
        "EDA 프로파일링 완료: %d행 × %d열 (샘플링=%s)",
        total_rows, total_columns, sampled,
    )

    return EDAProfile(
        total_rows=total_rows,
        total_columns=total_columns,
        memory_bytes=memory_bytes,
        duplicate_rows=duplicate_rows,
        sampled=sampled,
        sample_size=sample_size,
        columns=columns,
    )


def profile_to_dict(profile: EDAProfile) -> dict:
    """EDAProfile → JSON-serializable dict 변환."""
    from dataclasses import asdict
    raw = asdict(profile)
    return _sanitize(raw)


def _sanitize(obj):
    """numpy/pandas 타입 → Python 네이티브 재귀 변환."""
    if isinstance(obj, dict):
        return {_sanitize(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(item) for item in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj


def _safe_mode(series: pd.Series) -> str | None:
    """최빈값 안전 추출. 빈 Series나 전체 NaN이면 None."""
    if len(series) == 0 or series.isna().all():
        return None
    modes = series.mode(dropna=True)
    if len(modes) == 0:
        return None
    return str(modes.iloc[0])
