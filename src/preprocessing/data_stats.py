"""학습 데이터 분포 메타데이터 계산 — 모델 드리프트 감지의 베이스라인.

Why: 모델 학습 시점의 데이터 분포(mean/std/nunique 등)를 ModelMetadata에 보존하여
     향후 PSI(Population Stability Index) 계산·재학습 트리거의 입력으로 사용한다.
     본 모듈은 메타데이터 산출까지만 담당하며, 실제 PSI 계산·UI 알림은 다음 단계.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

# Why: 범주형 분포 저장 시 상위 N개만 보존 (전체 cardinality는 nunique로 별도 기록)
_TOP_CATEGORY_LIMIT = 10


def compute_training_stats(X: pd.DataFrame) -> dict:
    """학습 데이터 분포 통계 산출.

    수치형: mean / std / min / max / nunique / null_rate
    범주형: top10 카테고리 + 빈도 / nunique / null_rate

    Why: pandas describe()는 type별로 결과 형식이 다르므로 직접 분기하여
         JSON 직렬화 가능한 dict로 정리한다 (registry.json 저장용).
    """
    if X is None or len(X) == 0:
        return {"n_samples": 0, "columns": {}}

    columns: dict[str, dict] = {}
    for col in X.columns:
        series = X[col]
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(
            series,
        ):
            columns[col] = _numeric_stats(series)
        else:
            columns[col] = _categorical_stats(series)

    return {
        "n_samples": int(len(X)),
        "columns": columns,
    }


def _numeric_stats(series: pd.Series) -> dict:
    """수치형 컬럼 통계."""
    arr = series.to_numpy()
    finite = arr[np.isfinite(arr)] if arr.dtype.kind == "f" else arr[~pd.isna(arr)]
    if len(finite) == 0:
        return {
            "type": "numeric",
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "nunique": 0,
            "null_rate": 1.0,
        }
    return {
        "type": "numeric",
        "mean": float(np.mean(finite)),
        "std": float(np.std(finite)),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "nunique": int(series.nunique(dropna=True)),
        "null_rate": float(series.isna().mean()),
    }


def _categorical_stats(series: pd.Series) -> dict:
    """범주형 컬럼 통계 — 상위 N개 카테고리 + 빈도 보존."""
    value_counts = series.value_counts(dropna=True).head(_TOP_CATEGORY_LIMIT)
    return {
        "type": "categorical",
        "nunique": int(series.nunique(dropna=True)),
        "null_rate": float(series.isna().mean()),
        "top_categories": {str(k): int(v) for k, v in value_counts.items()},
    }


def compute_class_imbalance(y: np.ndarray | pd.Series | None) -> float:
    """이진 라벨의 양성 비율(class imbalance ratio)."""
    if y is None:
        return 0.0
    arr = np.asarray(y)
    if arr.size == 0:
        return 0.0
    return float(np.sum(arr == 1) / arr.size)


def compute_feature_schema_version(X: pd.DataFrame) -> int:
    """컬럼 스키마(이름 set)의 short hash → int.

    Why: 학습 시점과 추론 시점의 컬럼 set이 동일한지 빠르게 비교하기 위함.
         완전한 hash가 아닌 32-bit 정수로 축약 (registry.json 가독성).
    """
    if X is None or len(X.columns) == 0:
        return 0
    schema_str = ",".join(sorted(str(c) for c in X.columns))
    digest = hashlib.sha256(schema_str.encode("utf-8")).hexdigest()
    # 상위 8 hex char → 32-bit int
    return int(digest[:8], 16)
