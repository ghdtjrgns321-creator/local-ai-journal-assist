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


def _map_coa_category(
    gl_series: pd.Series,
    coa_prefixes: dict[str, list[str]] | None = None,
) -> pd.Series:
    """GL 계정 코드 → CoA 상위그룹(asset/liability/equity/revenue/expense) 매핑.

    Why: Z-score 소그룹(n<30) fallback 시, 전체 데이터 대신
    동일 CoA 카테고리 내 통계를 사용하여 왜곡 최소화.
    매핑 실패 시 "other" 반환. coa_prefixes가 None이면 전부 "other".
    """
    # Why: gl_account가 int64로 캐스팅되어 있을 수 있음 → 강제 문자열 변환
    gl_str = gl_series.astype(str).str.strip()
    result = pd.Series("other", index=gl_series.index)

    if not coa_prefixes:
        return result

    for category, prefixes in coa_prefixes.items():
        mask = gl_str.str.startswith(tuple(prefixes))
        result = result.where(~mask, category)

    return result


def _compute_base_amount(df: pd.DataFrame) -> pd.Series:
    """차변/대변 중 큰 값을 대표 금액으로 산출. 둘 다 NaN이면 0.

    Why: DataSynth가 int64 범위 초과 금액(예: 9.4e18)을 생성하면
    pandas가 전체 컬럼을 object로 추론. to_numeric으로 float64 보장.
    """
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0)
    return pd.concat([debit, credit], axis=1).max(axis=1)


def _zscore_with_fallback(
    base: pd.Series,
    group: pd.Series,
    coa_category: pd.Series | None = None,
) -> pd.Series:
    """gl_account 그룹별 Z-score + CoA 상위그룹 fallback.

    3단계 fallback:
    - n≥30 그룹: 그룹 내 Z-score (transform 벡터화)
    - n<30 그룹 + CoA 카테고리 n≥30: CoA 상위그룹(자산/부채/수익/비용) 통계
    - n<30 그룹 + CoA도 소그룹: 전체 데이터 mean/std
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

    # ── 작은 그룹: CoA 상위그룹 → 전체 데이터 3단계 fallback ──
    small_mask = ~large_mask
    if not small_mask.any():
        return result

    # CoA 카테고리가 주어지면 상위그룹별 fallback 시도
    if coa_category is not None:
        small_coa = coa_category[small_mask]
        # Why: .fillna(0)으로 NaN 카테고리(매핑 실패)가 비교에서 False 처리되도록 방어
        coa_sizes = small_coa.map(coa_category.value_counts()).fillna(0)
        coa_large_mask = coa_sizes >= _MIN_GROUP_SIZE

        # CoA 그룹 n≥30: 해당 카테고리 통계로 Z-score
        coa_resolved = pd.Series(False, index=base.index)
        if coa_large_mask.any():
            coa_large_idx = small_mask[small_mask].index[coa_large_mask.values]
            coa_base = base.loc[coa_large_idx]
            coa_grp = coa_category.loc[coa_large_idx]
            grouped_coa = coa_base.groupby(coa_grp)
            coa_means = grouped_coa.transform("mean")
            coa_stds = grouped_coa.transform("std")
            safe_coa_stds = coa_stds.replace(0, np.nan)
            z_coa = (coa_base - coa_means) / safe_coa_stds
            z_coa = z_coa.fillna(0.0)
            result.loc[coa_large_idx] = z_coa
            coa_resolved.loc[coa_large_idx] = True

        # CoA도 소그룹인 나머지 → 전체 데이터 fallback
        remaining = small_mask & ~coa_resolved
        if remaining.any():
            total_mean = base.mean()
            total_std = base.std()
            if total_std == 0:
                result.loc[remaining] = 0.0
            else:
                result.loc[remaining] = (base[remaining] - total_mean) / total_std
    else:
        # CoA 카테고리 미제공 → 기존 동작 (전체 데이터 fallback)
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
    """B03: 승인한도 초과 여부 + 해당 한도 레벨.

    Why: 6단계 한도(10M~50B) 중 최저 한도를 초과하면 True.
         이전 로직(max 전용)은 50B 이상만 4행 탐지 → 실무 무의미.
         approval_level은 초과한 가장 낮은 한도의 인덱스(1~6). 미초과=0.
    """
    if not thresholds:
        df["exceeds_threshold"] = False
        df["approval_level"] = 0
        return df

    sorted_t = sorted(thresholds)
    min_threshold = sorted_t[0]

    # Why: 최저 한도 미만이면 어떤 레벨도 초과하지 않음 → False
    df["exceeds_threshold"] = base >= min_threshold

    # Why: 행별로 초과한 가장 높은 한도의 레벨을 기록 (B09 등에서 활용 가능)
    level = pd.Series(0, index=df.index, dtype=int)
    for i, t in enumerate(sorted_t, 1):
        level = level.where(base < t, i)
    df["approval_level"] = level

    return df


def add_amount_zscore(
    df: pd.DataFrame,
    base: pd.Series,
    coa_prefixes: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """C08: 금액 Z-score. gl_account 컬럼이 없으면 NaN + 경고.

    coa_prefixes 전달 시 소그룹(n<30) fallback에 CoA 상위그룹 통계 사용.
    """
    if "gl_account" not in df.columns:
        logger.warning("gl_account 컬럼 누락 — amount_zscore를 NaN으로 설정")
        df["amount_zscore"] = np.nan
        return df

    coa_cat = _map_coa_category(df["gl_account"], coa_prefixes) if coa_prefixes else None
    df["amount_zscore"] = _zscore_with_fallback(base, df["gl_account"], coa_category=coa_cat)
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
    currency_decimals: dict[str, int] | None = None,
) -> pd.DataFrame:
    """B04: 라운드넘버 여부. 0원은 제외(False).

    Why: DataSynth 등 외부 생성 데이터에서 float 소수점 꼬리(예: 10000000.000001)가
    발생할 수 있으므로 round 후 나머지 연산으로 허용 오차 적용.
    currency_decimals 전달 + currency 컬럼 존재 시 통화별 소수점 자릿수 적용.
    (예: USD→round(2), KRW→round(0))
    """
    if currency_decimals and "currency" in df.columns:
        # Why: 행마다 통화가 다르므로 단일 round() 호출 불가.
        #      map으로 통화별 decimals를 벡터화 적용. NaN currency는 round(0) 폴백.
        dec_series = df["currency"].map(
            lambda c: currency_decimals.get(c, 0) if pd.notna(c) else 0
        ).astype(int)
        # Why: Series.round()는 int 스칼라만 받으므로 고유 decimals별 마스크 처리
        rounded = base.copy()
        for dec_val in dec_series.unique():
            mask = dec_series == dec_val
            rounded.loc[mask] = base.loc[mask].round(dec_val)
        df["is_round_number"] = (base > 0) & (rounded % unit == 0)
    else:
        df["is_round_number"] = (base > 0) & (base.round(0) % unit == 0)
    return df


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_amount_features(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
    audit_rules: dict | None = None,
) -> pd.DataFrame:
    """금액 파생변수 5개를 한번에 추가. engine.py 진입점.

    audit_rules: get_audit_rules() 반환값과 동일한 원본 dict.
                 {"patterns": {...}, "currency_decimals": {...}} 중첩 구조.
                 None이면 get_audit_rules()로 자동 로드.
    """
    s = settings or get_settings()
    base = _compute_base_amount(df)

    # Why: currency_decimals는 patterns 밖에 있으므로 원본 audit_rules에서 직접 접근
    if audit_rules is None:
        from config.settings import get_audit_rules
        audit_rules = get_audit_rules()
    currency_dec = audit_rules.get("currency_decimals")

    # Why: coa_category_prefixes는 patterns 밖에 있으므로 원본 audit_rules에서 직접 접근
    coa_prefixes = audit_rules.get("coa_category_prefixes")

    add_is_near_threshold(df, base, s.approval_thresholds, s.near_threshold_ratio)
    add_exceeds_threshold(df, base, s.approval_thresholds)
    add_amount_zscore(df, base, coa_prefixes=coa_prefixes)
    add_amount_magnitude(df, base)
    add_is_round_number(df, base, s.round_unit, currency_decimals=currency_dec)

    return df
