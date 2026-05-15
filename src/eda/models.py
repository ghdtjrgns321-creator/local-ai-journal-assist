"""EDA 프로파일링 데이터 모델 — 컬럼별·전체 프로파일 구조체.

Why: profiler → report → dashboard/LLM 간 데이터 계약.
JSON 직렬화 가능하도록 numpy 타입 대신 Python 네이티브만 사용.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ColumnProfile:
    """단일 컬럼의 프로파일 결과."""

    name: str
    dtype: str                          # 원본 dtype 문자열 (예: "float64")
    dtype_group: str                    # "numeric" | "categorical" | "datetime" | "boolean"
    missing_rate: float                 # 0.0~1.0
    unique_count: int
    mode: str | None = None

    # ── 수치형 전용 ──
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    outlier_count: int | None = None
    min_val: float | None = None
    max_val: float | None = None

    # ── 범주형 전용 ──
    cardinality: int | None = None
    top_values: list[tuple[str, int]] | None = None

    # ── datetime 전용 ──
    min_date: str | None = None         # ISO 8601
    max_date: str | None = None
    date_range_days: int | None = None
    weekday_distribution: dict[int, int] | None = None   # 0(Mon)~6(Sun)
    monthly_distribution: dict[int, int] | None = None   # 1(Jan)~12(Dec)

    # ── boolean 전용 ──
    true_rate: float | None = None


@dataclass
class EDAProfile:
    """DataFrame 전체 프로파일 결과."""

    total_rows: int
    total_columns: int
    memory_bytes: int
    duplicate_rows: int
    duplicate_rows_estimated: bool = False
    duplicate_sample_size: int | None = None
    duplicate_rate_estimate: float | None = None
    sampled: bool = False
    sample_size: int | None = None
    columns: dict[str, ColumnProfile] = field(default_factory=dict)
