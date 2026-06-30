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


def _nunique_documents(df: pd.DataFrame, mask: pd.Series) -> int:
    if "document_id" not in df.columns:
        return int(mask.sum())
    return int(df.loc[mask.reindex(df.index, fill_value=False), "document_id"].dropna().nunique())


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
        qualified_doc_types = ["tax_invoice", "credit_card", "cash_receipt", "electronic_invoice"]

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
        tmp = pd.DataFrame(
            {
                "partner": partner,
                "date": pd.to_datetime(df["posting_date"], errors="coerce").dt.date,
                "amount": amount,
            }
        )
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


# ── L3-11: 컷오프 검증 (legacy function name: ev02_cutoff_violation) ─────────────


def ev02_cutoff_violation(
    df: pd.DataFrame,
    *,
    revenue_account_prefixes: list[str] | None = None,
    expense_account_prefixes: list[str] | None = None,
) -> pd.Series:
    """L3-11 기말 컷오프 불일치 (binary).

    Why: 감사기준서 315호/330호 — K-IFRS 15 수익인식 기간귀속.
         통제이전 시점(delivery_date)이 속한 회계연도와 인식 회계연도(fiscal_year,
         없으면 posting_date 연도로 폴백)가 다르면 결산일 경계를 넘긴 기간귀속
         의심 → 발화 1.0. 같은 연도 안의 처리지연은 일수가 커도 0.0.
         일수 차이·기말 가중·강도 차등은 폐기(정황·조합은 통합점수체계 소관).
    """
    if revenue_account_prefixes is None:
        revenue_account_prefixes = ["4"]
    if expense_account_prefixes is None:
        expense_account_prefixes = ["5"]

    scores = pd.Series(0.0, index=df.index)
    if len(df) == 0 or "delivery_date" not in df.columns or "posting_date" not in df.columns:
        scores.attrs["breakdown"] = {}
        scores.attrs["row_annotations"] = {}
        return scores

    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    delivery = pd.to_datetime(df["delivery_date"], errors="coerce")

    # ── 인식 회계연도 해소: fiscal_year 우선, 없으면 posting_date 연도로 폴백 ──
    posting_year = posting.dt.year
    if "fiscal_year" in df.columns:
        fiscal_year = pd.Series(pd.to_numeric(df["fiscal_year"], errors="coerce"), index=df.index)
        recognition_year = fiscal_year.where(fiscal_year.notna(), posting_year)
    else:
        recognition_year = posting_year
    delivery_year = delivery.dt.year

    # Why: 통제이전일·인식연도가 모두 있어야 경계 판정 가능 (없으면 미검증)
    testable = delivery.notna() & recognition_year.notna()

    # ── 매출/비용 분류 (동일 판정식, account_type 구분용) ──
    if "is_revenue_account" in df.columns:
        is_revenue = df["is_revenue_account"].fillna(False).astype(bool)
    elif "gl_account" in df.columns:
        is_revenue = df["gl_account"].astype(str).str[:1].isin(revenue_account_prefixes)
    else:
        is_revenue = pd.Series(False, index=df.index)

    if "gl_account" in df.columns:
        is_expense = df["gl_account"].astype(str).str[:1].isin(expense_account_prefixes)
    else:
        is_expense = pd.Series(False, index=df.index)
    # Why: 동일 행이 양쪽으로 분류되면 매출 우선
    is_expense = is_expense & ~is_revenue
    in_scope = is_revenue | is_expense

    # ── 판정: 회계연도 경계 넘김 = binary 발화 ──
    boundary_cross = (testable & in_scope & (delivery_year != recognition_year)).fillna(False)
    scores.loc[boundary_cross] = 1.0

    revenue_flag = boundary_cross & is_revenue
    expense_flag = boundary_cross & is_expense
    missing_event_date = delivery.isna() | recognition_year.isna()

    reason_counts = {
        "revenue_cutoff_gap": int(revenue_flag.sum()),
        "expense_cutoff_gap": int(expense_flag.sum()),
    }
    reason_counts = {key: value for key, value in reason_counts.items() if value > 0}
    breakdown = {
        "cutoff_review_rows": int(boundary_cross.sum()),
        "revenue_cutoff_rows": int(revenue_flag.sum()),
        "expense_cutoff_rows": int(expense_flag.sum()),
        "missing_event_date_rows": int(missing_event_date.sum()),
        "reason_counts": reason_counts,
    }
    if "document_id" in df.columns:
        breakdown.update(
            {
                "cutoff_review_docs": _nunique_documents(df, boundary_cross),
                "revenue_cutoff_docs": _nunique_documents(df, revenue_flag),
                "expense_cutoff_docs": _nunique_documents(df, expense_flag),
                "missing_event_date_docs": _nunique_documents(df, missing_event_date),
            }
        )

    # Why: 달력일 차는 참고 사실값으로만 기록 — 점수·우선순위를 구동하지 않는다
    day_diff_ref = (posting - delivery).dt.days.abs()

    row_annotations: dict[int, dict[str, object]] = {}
    for idx in df.index[boundary_cross]:
        if bool(revenue_flag.loc[idx]):
            reason_code = "revenue_cutoff_gap"
            account_type = "revenue"
        else:
            reason_code = "expense_cutoff_gap"
            account_type = "expense"
        diff_val = day_diff_ref.loc[idx]
        row_annotations[int(idx)] = {
            "reason_code": reason_code,
            "account_type": account_type,
            "delivery_year": int(delivery_year.loc[idx]),
            "recognition_year": int(recognition_year.loc[idx]),
            "day_diff": float(diff_val) if pd.notna(diff_val) else None,
        }

    scores.attrs["breakdown"] = breakdown
    scores.attrs["row_annotations"] = row_annotations
    return scores


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
