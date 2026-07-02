"""금액 기반 파생변수 5개 생성 모듈.

L2-01/L1-04(승인한도), L2-02(라운드넘버), L4-03(Z-score) 룰 대응 피처.
ingest 완료된 표준 DataFrame을 입력으로 받는다.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import AuditSettings, get_settings
from src.detection.boolean_utils import bool_column
from src.ingest.datasynth_labels import get_source_path

logger = logging.getLogger(__name__)

# -- Z-score fallback 기준 --
_MIN_GROUP_SIZE = 30  # 이상이면 그룹별 Z-score
_MIN_TOTAL_SIZE = 10  # 미만이면 Z-score 포기 → NaN


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


def _compute_document_amount(df: pd.DataFrame, base: pd.Series) -> pd.Series:
    """Return document-level approval amount when possible, else line-level base.

    Approval controls need the economic size of the whole journal entry. In balanced
    entries debit and credit totals match, but malformed synthetic or source data can
    have the larger side on credit. Use the larger document-side total so approval
    checks do not miss credit-heavy entries.
    """
    if (
        "document_id" not in df.columns
        or "debit_amount" not in df.columns
        or "credit_amount" not in df.columns
    ):
        return base

    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0)
    doc_debit = debit.groupby(df["document_id"]).transform("sum")
    doc_credit = credit.groupby(df["document_id"]).transform("sum")
    return pd.concat([doc_debit, doc_credit], axis=1).max(axis=1)


def _resolve_employee_master_path(
    df: pd.DataFrame,
    employee_master_path: str | Path | None = None,
) -> Path | None:
    """Resolve employees.json path.

    Why: df.attrs (source_path 자동 감지)는 merge/concat/parquet round-trip 등
    pandas 연산을 거치면 쉽게 유실된다. 호출자가 경로를 알고 있으면
    employee_master_path로 명시 전달해 attrs 유실과 무관하게 해소한다.
    """
    if employee_master_path is not None:
        candidate = Path(employee_master_path)
        return candidate if candidate.exists() else None

    source_path = get_source_path(df)
    if source_path is None:
        return None
    candidate = Path(source_path).parent / "master_data" / "employees.json"
    return candidate if candidate.exists() else None


@functools.lru_cache(maxsize=16)
def _load_employee_approval_map(path_str: str) -> dict[str, tuple[float | None, bool | None]]:
    records = json.loads(Path(path_str).read_text(encoding="utf-8"))
    result: dict[str, tuple[float | None, bool | None]] = {}
    for row in records:
        user_id = str(row.get("user_id", "")).strip()
        if not user_id:
            continue
        raw_limit = row.get("approval_limit")
        approval_limit = None if raw_limit in (None, "", "nan") else float(raw_limit)
        can_approve = row.get("can_approve_je")
        result[user_id] = (approval_limit, bool(can_approve) if can_approve is not None else None)
    return result


def _compute_approver_limit(df: pd.DataFrame) -> pd.Series | None:
    info = _compute_approver_info(df)
    if info is None:
        return None
    return info["approval_limit"]


def _compute_approver_info(
    df: pd.DataFrame,
    employee_master_path: str | Path | None = None,
) -> pd.DataFrame | None:
    if "approved_by" not in df.columns:
        return None

    master_path = _resolve_employee_master_path(df, employee_master_path)
    if master_path is None:
        return None

    try:
        approval_map = _load_employee_approval_map(str(master_path.resolve()))
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning("employees.json 로드 실패 — approver limit fallback", exc_info=True)
        return None

    approver = df["approved_by"].fillna("").astype(str).str.strip()
    limit_map = {
        user_id: (0.0 if can_approve_je is False else approval_limit)
        for user_id, (approval_limit, can_approve_je) in approval_map.items()
    }
    can_approve_map = {
        user_id: can_approve_je
        for user_id, (_, can_approve_je) in approval_map.items()
        if can_approve_je is not None
    }
    limits = pd.to_numeric(approver.map(limit_map), errors="coerce")
    can_approve = approver.map(can_approve_map).astype("boolean")
    approver_in_master = pd.Series(pd.NA, index=df.index, dtype="boolean")
    has_approver = approver.ne("")
    approver_in_master.loc[has_approver] = approver.loc[has_approver].isin(approval_map)
    return pd.DataFrame(
        {
            "approval_limit": limits,
            "can_approve_je": can_approve,
            "approver_in_master": approver_in_master,
        },
        index=df.index,
    )


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
                # base가 NaN인 행(예: log 불가한 0원 라인)은 z=0.0으로 마감.
                # 큰 그룹·CoA 경로와 동일하게 NaN↔0.0 처리를 대칭으로 맞춘다.
                result.loc[remaining] = ((base[remaining] - total_mean) / total_std).fillna(0.0)
    else:
        # CoA 카테고리 미제공 → 기존 동작 (전체 데이터 fallback)
        total_mean = base.mean()
        total_std = base.std()
        if total_std == 0:
            result.loc[small_mask] = 0.0
        else:
            result.loc[small_mask] = ((base[small_mask] - total_mean) / total_std).fillna(0.0)

    return result


# ── Public feature functions ─────────────────────────────────────


def add_is_near_threshold(
    df: pd.DataFrame,
    base: pd.Series,
    thresholds: list[int | float],
    ratio: float,
    employee_master_path: str | Path | None = None,
) -> pd.DataFrame:
    """L2-01: 승인권자 실제 한도 직하 여부.

    우선순위:
    1. 직원 마스터에서 approved_by의 approval_limit를 조회할 수 있으면
       document total 기준으로 approval_limit * ratio ≤ amount < approval_limit 판정
    2. approval_limit를 알 수 없으면 L2-01로 판정하지 않음
    """
    can_compute_document_amount = "document_id" in df.columns and "debit_amount" in df.columns
    threshold_amount = (
        _compute_document_amount(df, base)
        if can_compute_document_amount
        else pd.Series(np.nan, index=df.index, dtype="float64")
    )
    approver_info = _compute_approver_info(df, employee_master_path)
    approver_limit = approver_info["approval_limit"] if approver_info is not None else None

    near = pd.Series(False, index=df.index)
    limit = pd.Series(np.nan, index=df.index, dtype="float64")

    if approver_limit is not None:
        limit = approver_limit
        resolved = limit.notna() & can_compute_document_amount
        near = resolved & ((threshold_amount >= limit * ratio) & (threshold_amount < limit))
    else:
        resolved = pd.Series(False, index=df.index)

    ratio_denominator = limit.where(limit > 0)
    ratio_to_limit = threshold_amount / ratio_denominator
    gap_amount = (limit - threshold_amount).where(resolved)
    gap_ratio = (gap_amount / ratio_denominator).where(resolved)

    df["is_near_threshold"] = near.fillna(False)
    df["near_threshold_amount"] = threshold_amount
    df["near_threshold_limit_amount"] = limit
    df["near_threshold_limit_resolved"] = resolved
    df["near_threshold_ratio_to_limit"] = ratio_to_limit.where(resolved)
    df["near_threshold_gap_amount"] = gap_amount
    df["near_threshold_gap_ratio"] = gap_ratio
    df["near_threshold_bucket"] = _near_threshold_bucket(
        near=near.fillna(False),
        limit_resolved=resolved,
        ratio_to_limit=ratio_to_limit,
        lower_ratio=float(ratio),
    )
    return df


def _near_threshold_bucket(
    *,
    near: pd.Series,
    limit_resolved: pd.Series,
    ratio_to_limit: pd.Series,
    lower_ratio: float,
) -> pd.Series:
    """Classify L2-01 threshold proximity without changing the Boolean hit."""

    bucket = pd.Series("none", index=near.index, dtype="object")
    bucket.loc[~limit_resolved.astype(bool)] = "unresolved_limit"

    hit = near.astype(bool)
    ratio = ratio_to_limit.fillna(0.0)
    bucket.loc[hit & ratio.ge(lower_ratio) & ratio.lt(0.95)] = "lower_band"
    bucket.loc[hit & ratio.ge(0.95) & ratio.lt(0.98)] = "close_band"
    bucket.loc[hit & ratio.ge(0.98) & ratio.lt(1.00)] = "razor_band"
    return bucket


def add_exceeds_threshold(
    df: pd.DataFrame,
    base: pd.Series,
    thresholds: list[int | float],
    employee_master_path: str | Path | None = None,
) -> pd.DataFrame:
    """L1-04: 승인한도 초과 여부 + 해당 한도 레벨.

    Why: 6단계 한도(10M~50B) 중 최저 한도를 초과하면 True.
         이전 로직(max 전용)은 50B 이상만 4행 탐지 → 실무 무의미.
         approval_level은 초과한 가장 낮은 한도의 인덱스(1~6). 미초과=0.
    """
    if not thresholds:
        approver_info = _compute_approver_info(df, employee_master_path)
        df["exceeds_threshold"] = False
        df["approval_level"] = 0
        df["document_approval_amount"] = _compute_document_amount(df, base)
        df["approver_limit_amount"] = np.nan
        df["approval_limit_resolved"] = False
        df["approver_can_approve_je"] = pd.Series(pd.NA, index=df.index, dtype="boolean")
        if approver_info is not None:
            df["approver_in_master"] = approver_info["approver_in_master"]
        df["approval_excess_amount"] = 0.0
        df["approval_excess_ratio"] = np.nan
        df["approval_excess_bucket"] = "none"
        return df

    sorted_t = sorted(thresholds)
    threshold_amount = _compute_document_amount(df, base)
    approver_info = _compute_approver_info(df, employee_master_path)
    approver_limit = approver_info["approval_limit"] if approver_info is not None else None

    # Why: L1-04 is binary: amount above a resolved approver limit, or approval
    # by a user without JE approval authority / without a defined limit.
    if approver_limit is not None:
        resolved = approver_limit.notna()
        approver = (
            df["approved_by"].fillna("").astype(str).str.strip()
            if "approved_by" in df.columns
            else pd.Series("", index=df.index)
        )
        has_approver = approver.ne("")
        can_approve = approver_info["can_approve_je"].fillna(True).astype(bool)
        real_approver = approver_info["approver_in_master"].fillna(True).astype(bool)
        no_approval_authority = has_approver & real_approver & (can_approve.eq(False) | ~resolved)
        df["exceeds_threshold"] = has_approver & (
            (resolved & (threshold_amount > approver_limit)) | no_approval_authority
        )
    else:
        resolved = pd.Series(False, index=df.index)
        df["exceeds_threshold"] = False

    # Why: 행별로 초과한 가장 높은 한도의 레벨을 기록 (L1-07 등에서 활용 가능)
    level = pd.Series(0, index=df.index, dtype=int)
    for i, t in enumerate(sorted_t, 1):
        level = level.where(threshold_amount < t, i)
    df["approval_level"] = level
    _add_approval_excess_details(
        df,
        threshold_amount=threshold_amount,
        approver_info=approver_info,
    )

    return df


def _add_approval_excess_details(
    df: pd.DataFrame,
    *,
    threshold_amount: pd.Series,
    approver_info: pd.DataFrame | None,
) -> None:
    """Preserve L1-04 amount/limit context for banded reporting."""

    if approver_info is None:
        approver_limit = pd.Series(np.nan, index=df.index, dtype="float64")
        can_approve = pd.Series(pd.NA, index=df.index, dtype="boolean")
    else:
        approver_limit = approver_info["approval_limit"]
        can_approve = approver_info["can_approve_je"]
    effective_limit = approver_limit

    exceeds = bool_column(df, "exceeds_threshold")
    resolved = approver_limit.notna()
    excess_amount = (threshold_amount - effective_limit).where(exceeds, 0.0)
    ratio_denominator = effective_limit.where(effective_limit > 0)
    excess_ratio = (excess_amount / ratio_denominator).where(exceeds)

    df["document_approval_amount"] = threshold_amount
    df["approver_limit_amount"] = approver_limit
    df["approval_limit_resolved"] = resolved
    df["approver_can_approve_je"] = can_approve
    if approver_info is not None:
        df["approver_in_master"] = approver_info["approver_in_master"]
    df["approval_excess_amount"] = excess_amount.fillna(0.0)
    df["approval_excess_ratio"] = excess_ratio
    df["approval_excess_bucket"] = _approval_excess_bucket(
        exceeds=exceeds,
        limit_resolved=resolved,
        can_approve=can_approve,
        excess_ratio=excess_ratio,
    )


def _approval_excess_bucket(
    *,
    exceeds: pd.Series,
    limit_resolved: pd.Series,
    can_approve: pd.Series,
    excess_ratio: pd.Series,
) -> pd.Series:
    """Classify L1-04 hit severity while preserving the binary flag."""

    bucket = pd.Series("none", index=exceeds.index, dtype="object")
    hit = exceeds.astype(bool)
    resolved = limit_resolved.astype(bool)
    bucket.loc[hit & ~resolved] = "unresolved_limit"

    non_approver = hit & resolved & can_approve.fillna(True).eq(False)
    bucket.loc[non_approver] = "non_approver"

    ratio_hit = hit & resolved & ~non_approver
    ratio = excess_ratio.fillna(0.0)
    bucket.loc[ratio_hit & ratio.le(0.10)] = "boundary"
    bucket.loc[ratio_hit & ratio.gt(0.10) & ratio.le(0.50)] = "moderate"
    bucket.loc[ratio_hit & ratio.gt(0.50) & ratio.le(1.00)] = "severe"
    bucket.loc[ratio_hit & ratio.gt(1.00)] = "critical"
    return bucket


def add_amount_zscore(
    df: pd.DataFrame,
    base: pd.Series,
    coa_prefixes: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """L4-03: 금액 Z-score. gl_account 컬럼이 없으면 NaN + 경고.

    coa_prefixes 전달 시 소그룹(n<30) fallback에 CoA 상위그룹 통계 사용.
    """
    if "gl_account" not in df.columns:
        logger.warning("gl_account 컬럼 누락 — amount_zscore를 NaN으로 설정")
        df["amount_zscore"] = np.nan
        return df

    coa_cat = _map_coa_category(df["gl_account"], coa_prefixes) if coa_prefixes else None
    df["amount_zscore"] = _zscore_with_fallback(base, df["gl_account"], coa_category=coa_cat)
    return df


def add_amount_zscore_log(
    df: pd.DataFrame,
    base: pd.Series,
    coa_prefixes: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """L4-01: 로그변환 후 gl_account 그룹별 Z-score. gl_account 없으면 NaN + 경고.

    Why: 매출 금액은 우편향(right-skew)이라 원금액 평균/표준편차 z-score는
    극단값 하나가 표준편차를 부풀려 어지간히 큰 금액도 임계를 못 넘긴다(σ 팽창).
    log 변환은 곱셈적 차이를 덧셈 거리로 압축해 분포를 정규에 가깝게 만들어
    3σ 임계가 원 의도대로 작동한다(회계 금액의 log-normal 근사).
    base = max(차변,대변) ≥ 0 이라 음수는 구조상 없고, 0원 라인만 log 불가 →
    NaN 처리해 z-score 계산에서 제외·미발화한다.
    """
    if "gl_account" not in df.columns:
        logger.warning("gl_account 컬럼 누락 — amount_zscore_log를 NaN으로 설정")
        df["amount_zscore_log"] = np.nan
        return df

    # 양수만 로그 대상. 0원(및 구조상 없는 음수)은 NaN → 그룹 통계에서 제외되고 미발화.
    log_base = pd.Series(np.nan, index=df.index, dtype="float64")
    positive = base > 0
    log_base.loc[positive] = np.log(base.loc[positive].astype("float64"))

    coa_cat = _map_coa_category(df["gl_account"], coa_prefixes) if coa_prefixes else None
    df["amount_zscore_log"] = _zscore_with_fallback(
        log_base, df["gl_account"], coa_category=coa_cat
    )
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
    """L2-02: 라운드넘버 여부. 0원은 제외(False).

    Why: DataSynth 등 외부 생성 데이터에서 float 소수점 꼬리(예: 10000000.000001)가
    발생할 수 있으므로 round 후 나머지 연산으로 허용 오차 적용.
    currency_decimals 전달 + currency 컬럼 존재 시 통화별 소수점 자릿수 적용.
    (예: USD→round(2), KRW→round(0))
    """
    if currency_decimals and "currency" in df.columns:
        # Why: 행마다 통화가 다르므로 단일 round() 호출 불가.
        #      map으로 통화별 decimals를 벡터화 적용. NaN currency는 round(0) 폴백.
        dec_series = (
            df["currency"]
            .map(lambda c: currency_decimals.get(c, 0) if pd.notna(c) else 0)
            .astype(int)
        )
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
    employee_master_path: str | Path | None = None,
) -> pd.DataFrame:
    """금액 파생변수 5개를 한번에 추가. engine.py 진입점.

    audit_rules: get_audit_rules() 반환값과 동일한 원본 dict.
                 {"patterns": {...}, "currency_decimals": {...}} 중첩 구조.
                 None이면 get_audit_rules()로 자동 로드.
    employee_master_path: employees.json 경로. None이면 df.attrs의 source_path로
                 자동 해소(정식 ingest 파이프라인 기준 동작). df.attrs가 유실되는
                 호출부(ad-hoc 스크립트, thin-copy 등)는 명시적으로 전달한다.
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

    add_is_near_threshold(
        df, base, s.approval_thresholds, s.near_threshold_ratio, employee_master_path
    )
    add_exceeds_threshold(df, base, s.approval_thresholds, employee_master_path)
    add_amount_zscore(df, base, coa_prefixes=coa_prefixes)
    add_amount_zscore_log(df, base, coa_prefixes=coa_prefixes)
    add_amount_magnitude(df, base)
    add_is_round_number(df, base, s.round_unit, currency_decimals=currency_dec)

    return df
