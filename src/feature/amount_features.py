"""금액 기반 파생변수 5개 생성 모듈.

B02/B03(승인한도), B04(라운드넘버), C08(Z-score) 룰 대응 피처.
ingest 완료된 표준 DataFrame을 입력으로 받는다.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config.settings import AuditSettings, get_settings

logger = logging.getLogger(__name__)

# -- Z-score fallback 기준 --
_MIN_GROUP_SIZE = 30   # 이상이면 그룹별 Z-score
_MIN_TOTAL_SIZE = 10   # 미만이면 Z-score 포기 → NaN


# ── Private helpers ──────────────────────────────────────────────


def _compute_base_amount(df: pd.DataFrame) -> pd.Series:
    """차변/대변 중 큰 값을 대표 금액으로 산출. 둘 다 NaN이면 0."""
    return df[["debit_amount", "credit_amount"]].max(axis=1).fillna(0)


def _zscore_with_fallback(
    base: pd.Series,
    group: pd.Series,
) -> pd.Series:
    """gl_account 그룹별 Z-score + 소그룹 전체 fallback.

    - n≥30 그룹: 그룹 내 Z-score (transform 벡터화)
    - n<30 그룹: 전체 데이터의 mean/std로 계산
    - 전체 n<10: NaN
    - std==0: 0.0 반환 (ZeroDivisionError 방지)
    """
    result = pd.Series(np.nan, index=base.index)

    # 전체 데이터가 너무 적으면 Z-score 무의미
    if len(base) < _MIN_TOTAL_SIZE:
        return result

    # 그룹 크기 계산
    group_sizes = group.map(group.value_counts())
    large_mask = group_sizes >= _MIN_GROUP_SIZE

    # ── 큰 그룹: gl_account별 Z-score (transform으로 벡터화) ──
    if large_mask.any():
        large_base = base[large_mask]
        large_group = group[large_mask]
        grouped = large_base.groupby(large_group)
        means = grouped.transform("mean")
        stds = grouped.transform("std")
        # std==0 → z=0.0 (모두 같은 금액)
        safe_stds = stds.replace(0, np.nan)
        z_large = (large_base - means) / safe_stds
        z_large = z_large.fillna(0.0)
        result.loc[large_mask] = z_large

    # ── 작은 그룹: 전체 데이터 기준 Z-score ──
    # Why: 큰 그룹 분포에 의해 왜곡 가능 → Phase 2에서 CoA 상위그룹 fallback으로 개선 예정
    small_mask = ~large_mask
    if small_mask.any():
        total_mean = base.mean()
        total_std = base.std()
        if total_std == 0:
            result.loc[small_mask] = 0.0
        else:
            result.loc[small_mask] = (base[small_mask] - total_mean) / total_std

    return result


# ── Public feature functions ─────────────────────────────────────


def add_is_near_threshold(
    df: pd.DataFrame,
    base: pd.Series,
    thresholds: list[int | float],
    ratio: float,
) -> pd.DataFrame:
    """B02: 다단계 승인한도 직하 여부.

    각 레벨별 threshold * ratio ≤ base < threshold 구간에 하나라도 해당하면 True.
    예: thresholds=[10M, 100M, 1B] → 9M~10M, 90M~100M, 900M~1B 중 하나에 속하면 플래그.
    """
    if not thresholds:
        df["is_near_threshold"] = False
        return df
    near = pd.Series(False, index=df.index)
    for t in sorted(thresholds):
        lower = t * ratio
        near = near | ((base >= lower) & (base < t))
    df["is_near_threshold"] = near
    return df


def add_exceeds_threshold(
    df: pd.DataFrame,
    base: pd.Series,
    thresholds: list[int | float],
) -> pd.DataFrame:
    """B03: 최고 승인한도 초과 여부. base >= max(thresholds)."""
    max_threshold = max(thresholds) if thresholds else 0
    df["exceeds_threshold"] = base >= max_threshold
    return df


def add_amount_zscore(
    df: pd.DataFrame,
    base: pd.Series,
) -> pd.DataFrame:
    """C08: 금액 Z-score. gl_account 컬럼이 없으면 NaN + 경고."""
    if "gl_account" not in df.columns:
        logger.warning("gl_account 컬럼 누락 — amount_zscore를 NaN으로 설정")
        df["amount_zscore"] = np.nan
        return df
    df["amount_zscore"] = _zscore_with_fallback(base, df["gl_account"])
    return df


def add_amount_magnitude(
    df: pd.DataFrame,
    base: pd.Series,
) -> pd.DataFrame:
    """금액 규모 (log10 스케일). 0→0.0, 음수→abs, NaN→NaN."""
    df["amount_magnitude"] = np.log10(base.abs() + 1)
    return df


def add_is_round_number(
    df: pd.DataFrame,
    base: pd.Series,
    unit: int,
) -> pd.DataFrame:
    """B04: 라운드넘버 여부. 0원은 제외(False).

    Why: DataSynth 등 외부 생성 데이터에서 float 소수점 꼬리(예: 10000000.000001)가
    발생할 수 있으므로 round(0) 후 나머지 연산으로 허용 오차 적용.
    허용 범위: 0.5원 미만 (원 단위 감사에서 실무적으로 무의미한 차이).
    """
    df["is_round_number"] = (base > 0) & (base.round(0) % unit == 0)
    return df


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_amount_features(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
) -> pd.DataFrame:
    """금액 파생변수 5개를 한번에 추가. engine.py 진입점."""
    s = settings or get_settings()
    base = _compute_base_amount(df)

    add_is_near_threshold(df, base, s.approval_thresholds, s.near_threshold_ratio)
    add_exceeds_threshold(df, base, s.approval_thresholds)
    add_amount_zscore(df, base)
    add_amount_magnitude(df, base)
    add_is_round_number(df, base, s.round_unit)

    return df
