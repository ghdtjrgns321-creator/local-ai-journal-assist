"""drift_detector — PSI 기반 모델 드리프트 감지.

Why: ModelMetadata에 보존한 학습 시점 분포(baseline_stats)와
     현재 데이터 분포를 비교하여 PSI(Population Stability Index)를 계산한다.
     PSI > 0.1 → 약한 드리프트, > 0.25 → 재학습 필요 (감사 도메인 관습).

PSI 공식: Σ (current_pct - baseline_pct) * ln(current_pct / baseline_pct)

감사 도메인 해석 (SOC 2 대응):
- PSI < 0.1: 분포 안정 — 재학습 불필요
- 0.1 ≤ PSI < 0.25: 약한 드리프트 — 모니터링 강화
- PSI ≥ 0.25: 강한 드리프트 — 재학습 필수
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Why: log(0) 방지 + 0-bin 안정화용 smoothing
_EPS = 1e-6

# Why: 감사 도메인 관습 — PSI 임계값
DRIFT_THRESHOLD_WARN = 0.1
DRIFT_THRESHOLD_CRITICAL = 0.25


@dataclass
class DriftReport:
    """단일 모델의 드리프트 리포트."""

    model_name: str
    version: int
    column_psi: dict[str, float]  # 컬럼별 PSI
    max_psi: float  # 최대 PSI (가장 드리프트 심한 컬럼)
    max_psi_column: str  # 최대 PSI 컬럼명
    overall_status: str  # "stable" | "warn" | "critical"
    schema_mismatch: bool  # 컬럼 set 변경 여부


def compute_psi_numeric(
    baseline_mean: float,
    baseline_std: float,
    current_values: np.ndarray,
    n_bins: int = 10,
) -> float:
    """수치형 컬럼의 PSI 계산 (N(mean, std) 가정 bin 분할).

    Why: baseline 통계만으로는 분포 모양을 완전히 복원할 수 없다.
         가우시안 가정 하에 z-score 기반 10개 bin으로 근사하여
         baseline_pct vs current_pct를 비교한다.
         baseline 원본 데이터가 없어도 작동 — registry 메타만으로 충분.
    """
    current = np.asarray(current_values, dtype=np.float64)
    current = current[np.isfinite(current)]
    if len(current) == 0 or baseline_std < _EPS:
        return 0.0

    # Why: z-score -3 ~ +3 범위를 10-bin으로 분할 (가우시안 99.7% 커버)
    bin_edges = np.linspace(-3.0, 3.0, n_bins + 1)
    z_current = (current - baseline_mean) / baseline_std
    # 양 끝 무한대 포함으로 outlier도 극단 bin에 흡수
    bin_edges_full = np.concatenate([[-np.inf], bin_edges[1:-1], [np.inf]])

    current_counts, _ = np.histogram(z_current, bins=bin_edges_full)
    current_pct = current_counts / max(len(current), 1)

    # Why: 가우시안 분포의 각 bin 이론 확률 (baseline 대체)
    from scipy.stats import norm

    baseline_cdf = norm.cdf(bin_edges_full[1:]) - norm.cdf(bin_edges_full[:-1])
    baseline_pct = baseline_cdf / baseline_cdf.sum()

    # Why: log(0) 회피 smoothing
    current_pct = np.clip(current_pct, _EPS, None)
    baseline_pct = np.clip(baseline_pct, _EPS, None)
    psi_terms = (current_pct - baseline_pct) * np.log(current_pct / baseline_pct)
    return float(np.sum(psi_terms))


def compute_psi_categorical(
    baseline_top_categories: dict[str, int],
    current_values: pd.Series,
) -> float:
    """범주형 컬럼의 PSI 계산 — baseline top 카테고리 기준.

    Why: data_stats.compute_training_stats는 범주형에 대해 top-10 카테고리만
         저장한다. current에서 각 카테고리 비율을 계산 후 baseline과 비교.
         baseline에 없던 새 카테고리는 "_OTHER_" 버킷으로 합산.
    """
    if not baseline_top_categories:
        return 0.0
    current = current_values.dropna()
    if len(current) == 0:
        return 0.0

    baseline_total = sum(baseline_top_categories.values())
    if baseline_total == 0:
        return 0.0
    baseline_pct = {k: v / baseline_total for k, v in baseline_top_categories.items()}

    current_counts = current.astype(str).value_counts()
    current_total = int(current_counts.sum())
    current_pct_map: dict[str, float] = {}
    other_count = 0
    for cat, cnt in current_counts.items():
        cat_str = str(cat)
        if cat_str in baseline_pct:
            current_pct_map[cat_str] = cnt / current_total
        else:
            other_count += int(cnt)

    all_keys = set(baseline_pct) | set(current_pct_map) | {"_OTHER_"}
    psi_total = 0.0
    for key in all_keys:
        b = baseline_pct.get(key, 0.0) if key != "_OTHER_" else 0.0
        c = current_pct_map.get(key, 0.0)
        if key == "_OTHER_":
            c = other_count / current_total if current_total else 0.0
        b = max(b, _EPS)
        c = max(c, _EPS)
        psi_total += (c - b) * np.log(c / b)
    return float(psi_total)


def compute_drift_report(
    model_metadata,
    current_df: pd.DataFrame,
) -> DriftReport:
    """ModelMetadata + 현재 DataFrame → DriftReport 산출.

    Args:
        model_metadata: ModelMetadata (training_data_stats + feature_schema_version 포함)
        current_df: 현재 데이터

    Returns:
        DriftReport — 컬럼별 PSI + 최대값 + 전체 상태
    """
    stats = model_metadata.training_data_stats or {}
    columns_stats = stats.get("columns", {})

    # Why: 스키마 불일치 감지 — 컬럼 set 완전 비교는 느리므로 baseline 컬럼만 체크
    baseline_cols = set(columns_stats.keys())
    current_cols = set(current_df.columns)
    schema_mismatch = bool(baseline_cols - current_cols)

    column_psi: dict[str, float] = {}
    for col, col_stats in columns_stats.items():
        if col not in current_df.columns:
            # Why: 누락 컬럼은 스키마 변경 사유 → PSI는 무한대 대신 critical 값 할당
            column_psi[col] = DRIFT_THRESHOLD_CRITICAL * 2
            continue
        col_type = col_stats.get("type", "numeric")
        try:
            if col_type == "numeric":
                column_psi[col] = compute_psi_numeric(
                    baseline_mean=float(col_stats.get("mean", 0.0)),
                    baseline_std=float(col_stats.get("std", 1.0)),
                    current_values=current_df[col].values,
                )
            else:
                column_psi[col] = compute_psi_categorical(
                    baseline_top_categories=col_stats.get("top_categories", {}),
                    current_values=current_df[col],
                )
        except Exception:
            # Why: 단일 컬럼 실패가 전체 리포트를 막지 않도록 격리
            column_psi[col] = 0.0

    if column_psi:
        max_col = max(column_psi, key=lambda k: column_psi[k])
        max_psi = column_psi[max_col]
    else:
        max_col, max_psi = "", 0.0

    if max_psi >= DRIFT_THRESHOLD_CRITICAL:
        status = "critical"
    elif max_psi >= DRIFT_THRESHOLD_WARN:
        status = "warn"
    else:
        status = "stable"

    return DriftReport(
        model_name=model_metadata.model_name,
        version=model_metadata.version,
        column_psi=column_psi,
        max_psi=max_psi,
        max_psi_column=max_col,
        overall_status=status,
        schema_mismatch=schema_mismatch,
    )
