"""Evidence 트랙 룰 함수 — EV01~EV03 (WU-14).

Why: 감사기준서 240호/500호/315호/330호 근거.
     증빙 누락·컷오프 위반·금액 불일치를 데이터 기반으로 탐지.
     각 함수는 0.0~1.0 연속 점수 Series를 반환 (bool이 아님).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass  # pragma: no cover


def _np_max(a: pd.Series, b: pd.Series) -> pd.Series:
    """np.maximum 기반 행별 max — pd.concat.max() 대비 18배 빠름."""
    return pd.Series(np.maximum(a.values, b.values), index=a.index)

logger = logging.getLogger(__name__)

# ── 헬퍼 ────────────────────────────────────────────────────


def _max_amount(df: pd.DataFrame) -> pd.Series:
    """차변/대변 중 큰 금액 반환. 두 컬럼 모두 없으면 0."""
    debit = df["debit_amount"].fillna(0) if "debit_amount" in df.columns else 0
    credit = df["credit_amount"].fillna(0) if "credit_amount" in df.columns else 0
    return pd.DataFrame({"d": debit, "c": credit}).max(axis=1)


def _resolve_partner_column(df: pd.DataFrame) -> pd.Series | None:
    """거래처 식별 컬럼 해소: trading_partner → auxiliary_account_number fallback."""
    if "trading_partner" in df.columns:
        col = df["trading_partner"].copy()
        # Why: trading_partner가 null인 행은 auxiliary_account_number로 보완
        if "auxiliary_account_number" in df.columns:
            mask = col.isna()
            col.loc[mask] = df.loc[mask, "auxiliary_account_number"]
        return col
    if "auxiliary_account_number" in df.columns:
        return df["auxiliary_account_number"]
    return None


# ── EV01: 증빙 존재 확인 ────────────────────────────────────


def ev01_missing_evidence(
    df: pd.DataFrame,
    *,
    qualified_doc_types: list[str] | None = None,
    tax_threshold: float = 30_000,
    split_max_amount: float = 29_000,
    split_min_count: int = 3,
) -> pd.Series:
    """EV01 증빙 존재 확인.

    Why: 감사기준서 500호 — 감사증거의 충분성·적합성.
         한국 세법: 3만원 초과 거래는 적격증빙(세금계산서/카드/현금영수증) 필수.

    S1: 증빙 미첨부 + 수기 + 고액 → 0.6
    S2: 고액인데 적격증빙 유형 아님 → 0.5
    S3: 동일 거래처·동일일 분할 의심 → 0.8
    """
    if qualified_doc_types is None:
        qualified_doc_types = ["tax_invoice", "credit_card", "cash_receipt",
                               "electronic_invoice"]

    n = len(df)
    scores = pd.Series(0.0, index=df.index)
    if n == 0:
        return scores

    amount = _max_amount(df)

    # ── S1: 증빙 미첨부 + 수기 + 고액 ──
    if "has_attachment" in df.columns:
        no_attach = df["has_attachment"].fillna(True).eq(False)
        is_manual = (
            df["is_manual_je"].fillna(False)
            if "is_manual_je" in df.columns
            else pd.Series(True, index=df.index)  # 피처 부재 시 보수적 판정
        )
        high_amount = amount > tax_threshold
        s1 = (no_attach & is_manual & high_amount).astype(float) * 0.6
        scores = _np_max(scores, s1)

    # ── S2: 적격증빙 유형 부재 ──
    if "supporting_doc_type" in df.columns:
        high_amount = amount > tax_threshold
        # Why: null이거나 적격증빙 목록에 없으면 부적격
        not_qualified = ~df["supporting_doc_type"].isin(qualified_doc_types)
        s2 = (high_amount & not_qualified).astype(float) * 0.5
        scores = _np_max(scores, s2)

    # ── S3: 분할 거래 탐지 ──
    partner = _resolve_partner_column(df)
    if partner is not None and "posting_date" in df.columns:
        # Why: 거래처+일자 그룹 내 건수 ≥ N 이고 건당 금액 ≤ split_max_amount → 회피 의심
        tmp = pd.DataFrame({
            "partner": partner,
            "date": pd.to_datetime(df["posting_date"], errors="coerce").dt.date,
            "amount": amount,
        })
        # partner가 null인 행은 그룹핑 불가 → 제외
        valid = tmp["partner"].notna()
        if valid.any():
            grp = tmp.loc[valid].groupby(["partner", "date"])
            count_map = grp["amount"].transform("count")
            max_amt_map = grp["amount"].transform("max")
            split_flag = (count_map >= split_min_count) & (max_amt_map <= split_max_amount)
            s3 = pd.Series(0.0, index=df.index)
            s3.loc[split_flag.index] = split_flag.astype(float) * 0.8
            scores = _np_max(scores, s3)

    return scores.fillna(0.0)


# ── EV02: 컷오프 검증 ────────────────────────────────────────


def ev02_cutoff_violation(
    df: pd.DataFrame,
    *,
    revenue_cutoff_days: int = 5,
    expense_cutoff_days: int = 7,
    period_end_weight: float = 1.5,
    max_day_diff: int = 30,
    use_business_days: bool = True,
    custom_holidays: list[str] | None = None,
    revenue_account_prefixes: list[str] | None = None,
    expense_account_prefixes: list[str] | None = None,
) -> pd.Series:
    """EV02 컷오프 검증.

    Why: 감사기준서 315호/330호 — K-IFRS 15 수익인식 기준.
         posting_date와 delivery_date 간 차이가 임계 초과 시 기간귀속 오류 의심.
    """
    if revenue_account_prefixes is None:
        revenue_account_prefixes = ["4"]
    if expense_account_prefixes is None:
        expense_account_prefixes = ["5"]

    scores = pd.Series(0.0, index=df.index)
    if len(df) == 0:
        return scores

    if "delivery_date" not in df.columns or "posting_date" not in df.columns:
        return scores

    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    delivery = pd.to_datetime(df["delivery_date"], errors="coerce")

    # Why: np.busday_count는 NaT 1개라도 있으면 ValueError → 유효 행만 필터링
    valid_mask = posting.notna() & delivery.notna()
    if not valid_mask.any():
        return scores

    posting_valid = posting[valid_mask]
    delivery_valid = delivery[valid_mask]

    # ── 날짜 차이 계산 ──
    if use_business_days:
        try:
            # Why: busday_count는 numpy datetime64 필요
            p_np = posting_valid.values.astype("datetime64[D]")
            d_np = delivery_valid.values.astype("datetime64[D]")
            # Why: holidays=None은 ValueError → 빈 배열 또는 파라미터 생략
            kwargs: dict = {}
            if custom_holidays:
                kwargs["holidays"] = np.array(
                    [np.datetime64(h) for h in custom_holidays],
                    dtype="datetime64[D]",
                )
            day_diff = np.abs(np.busday_count(d_np, p_np, **kwargs))
        except Exception:
            # Why: busday_count 실패 시 달력일로 fallback
            logger.warning("np.busday_count 실패 — 달력일로 fallback")
            day_diff = (posting_valid - delivery_valid).dt.days.abs().values
    else:
        day_diff = (posting_valid - delivery_valid).dt.days.abs().values

    day_diff_series = pd.Series(0.0, index=df.index)
    day_diff_series.loc[valid_mask] = day_diff

    # ── 매출/비용 분류 ──
    if "is_revenue_account" in df.columns:
        is_revenue = df["is_revenue_account"].fillna(False)
    elif "gl_account" in df.columns:
        is_revenue = df["gl_account"].astype(str).str[:1].isin(revenue_account_prefixes)
    else:
        is_revenue = pd.Series(False, index=df.index)

    if "gl_account" in df.columns:
        is_expense = df["gl_account"].astype(str).str[:1].isin(expense_account_prefixes)
    else:
        is_expense = pd.Series(False, index=df.index)

    # ── 임계 초과 시 점수 부여 ──
    # Why: max_day_diff를 분모로 정규화 → 0.0~1.0
    max_dd = max(max_day_diff, 1)
    revenue_score = (
        (day_diff_series > revenue_cutoff_days) & is_revenue & valid_mask
    ).astype(float) * (day_diff_series / max_dd)

    expense_score = (
        (day_diff_series > expense_cutoff_days) & is_expense & valid_mask
    ).astype(float) * (day_diff_series / max_dd)

    scores = _np_max(revenue_score, expense_score)

    # ── 기말 가중 ──
    if "is_period_end" in df.columns:
        period_end = df["is_period_end"].fillna(False)
        scores.loc[period_end] *= period_end_weight

    return scores.clip(0.0, 1.0).fillna(0.0)


# ── EV03: 증빙 금액 불일치 ────────────────────────────────────


def ev03_amount_mismatch(
    df: pd.DataFrame,
    *,
    amount_tolerance: float = 1.0,
    vat_rate: float = 0.10,
    vat_tolerance: float = 1.0,
) -> pd.Series:
    """EV03 증빙 금액 불일치.

    Why: 감사기준서 500호 — 3-way matching 간소화.
         전기 금액과 세금계산서 금액의 차이, 부가세 계산 오류 탐지.
    """
    scores = pd.Series(0.0, index=df.index)
    if len(df) == 0:
        return scores

    amount = _max_amount(df)

    # ── S1: 3-way matching (전기 금액 vs 세금계산서 금액) ──
    if "invoice_amount" in df.columns:
        inv = df["invoice_amount"]
        has_invoice = inv.notna() & (inv > 0)
        if has_invoice.any():
            diff = (amount - inv).abs()
            # Why: 분모가 0이면 나눗셈 오류 → clip(1.0)으로 방어
            inv_safe = inv.clip(lower=1.0)
            # Why: 허용 오차 초과분을 invoice 대비 10% 기준으로 정규화
            raw_score = diff / (inv_safe * 0.1)
            s1 = pd.Series(0.0, index=df.index)
            exceed = has_invoice & (diff > amount_tolerance)
            s1.loc[exceed] = raw_score.loc[exceed].clip(upper=1.0)
            scores = _np_max(scores, s1)

    # ── S2: 부가세 검증 ──
    if "supply_amount" in df.columns and "tax_amount" in df.columns:
        supply = df["supply_amount"]
        tax = df["tax_amount"]
        # Why: 면세/영세율 거래(tax_amount=0 또는 NaN)는 검증 대상 제외
        #      정상적인 면세·수출 거래가 오탐되는 것을 방지
        taxable_mask = tax.notna() & (tax > 0) & supply.notna() & (supply > 0)
        if taxable_mask.any():
            expected_tax = (supply * vat_rate).round(0)
            tax_diff = (tax - expected_tax).abs()
            s2 = pd.Series(0.0, index=df.index)
            exceed = taxable_mask & (tax_diff > vat_tolerance)
            s2.loc[exceed] = 0.7
            scores = _np_max(scores, s2)

    return scores.fillna(0.0)
