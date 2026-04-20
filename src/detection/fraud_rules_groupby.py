"""groupby 기반 부정 탐지 룰 — L2-02, L2-03, L2-04.

원본 컬럼에 직접 접근하는 연산 집약 룰.
L2-02는 양방향 diff로 첫 번째 거래 누락을 방지한다.
"""

from __future__ import annotations

import pandas as pd


def _compute_base_amount(df: pd.DataFrame) -> pd.Series:
    """행별 대표 금액 = max(debit, credit). NaN → 0."""
    return (
        df[["debit_amount", "credit_amount"]]
        .fillna(0)
        .max(axis=1)
    )


def b04_duplicate_payment(
    df: pd.DataFrame,
    window_days: int = 30,
) -> pd.Series:
    """L2-02 중복 지급: P2P 내 동일 거래처 + 금액 + 기간 내 정밀 탐지.

    Why: PCAOB AS 2401 §32 — 동일 건 이중 지급은 부정 은닉 수단.

    하이브리드 전략 (A+B):
      A) 프로세스 필터: P2P만 대상. O2C 반복 매출, TRE 정기 이체는 제외.
      B) 고유키 대조: 같은 reference인데 document_id가 다르면 이중 지급 의심.
         reference가 NULL이면 금액+거래처+기간으로 fallback (송장번호 은닉 의심).
    """
    required = ["auxiliary_account_number", "posting_date", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)

    # ── A) 프로세스 필터: P2P만 대상 ──
    # Why: O2C 반복 매출(82K건), TRE 정기 이체(37K건)는 정상 반복거래
    if "business_process" in df.columns:
        p2p_mask = df["business_process"] == "P2P"
    else:
        p2p_mask = pd.Series(True, index=df.index)

    target = df[p2p_mask]
    if target.empty:
        return result

    base_amount = _compute_base_amount(target)

    # ── B-1) 고유키 대조: 같은 reference + 같은 금액 + 다른 document_id ──
    # Why: 횡령범이 같은 송장으로 두 번 지급할 때 reference가 동일
    if "reference" in target.columns and "document_id" in target.columns:
        has_ref = target["reference"].notna() & (target["reference"] != "")
        ref_target = target[has_ref].copy()

        if not ref_target.empty:
            ref_target["_base_amt"] = base_amount[has_ref]
            # Why: 같은 reference+금액인데 document_id가 다르면 이중 지급
            ref_groups = ref_target.groupby(["auxiliary_account_number", "reference", "_base_amt"])
            n_unique_docs = ref_groups["document_id"].transform("nunique")
            ref_dups = n_unique_docs > 1
            result.loc[ref_dups[ref_dups].index] = True

    # ── B-2) NULL reference fallback: 금액 + 거래처 + 기간 ──
    # Why: 송장번호를 슬쩍 비우거나 바꿔서 탐지를 회피하는 패턴
    if "reference" in target.columns:
        has_null_ref = target["reference"].isna() | (target["reference"] == "")
        null_ref_target = target[has_null_ref]
    else:
        # Why: reference 컬럼 자체가 없으면 전체를 fallback 대상으로
        null_ref_target = target
    if not null_ref_target.empty:
        work = null_ref_target[["auxiliary_account_number", "posting_date"]].copy()
        work["_base_amt"] = _compute_base_amount(null_ref_target)
        work = work.sort_values(["auxiliary_account_number", "_base_amt", "posting_date"])

        grouped = work.groupby(["auxiliary_account_number", "_base_amt"])
        window = pd.Timedelta(days=window_days)

        diff_forward = grouped["posting_date"].diff()
        diff_backward = grouped["posting_date"].diff(-1).abs()
        is_dup = (diff_forward <= window) | (diff_backward <= window)
        is_dup = is_dup.reindex(null_ref_target.index).fillna(False)
        result.loc[is_dup[is_dup].index] = True

    return result


def b05_duplicate_entry(df: pd.DataFrame) -> pd.Series:
    """L2-03 중복 전표: 동일 GL계정 + 금액 + 전기일 exact match.

    Why: 외감법 §8①4호 — 동일 전표 반복은 가공 전표(위조) 징후.
    L2-02와 차별점: L2-02=기간 내 유사, L2-03=정확 중복.
    """
    required = ["gl_account", "posting_date", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    base_amount = _compute_base_amount(df)
    work = df[["gl_account", "posting_date"]].copy()
    work["_base_amt"] = base_amount

    # Why: keep=False → 원본·중복 모두 flag (한쪽만 flag하면 감사 누락)
    return work.duplicated(subset=["gl_account", "_base_amt", "posting_date"], keep=False)


def b11_expense_capitalization(df: pd.DataFrame) -> pd.Series:
    """L2-04 비용 자산화: 동일 전표 내 차변=자산(15xx) + 대변=비용(6xxx) 조합.

    Why: 240호 §32, FSS 분식회계 사례 — 비용을 자산으로 이전하여 이익을 부풀리는 패턴.
    알고리즘: 차변 자산 뷰 × 대변 비용 뷰를 document_id 기준 inner merge.
    """
    required = ["document_id", "gl_account", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    gl = df["gl_account"].astype(str)

    # Why: 차변에 자산계정(15xx), 대변에 비용계정(6xxx)이 동일 전표에 공존하면 의심
    debit_asset = df.loc[
        (df["debit_amount"].fillna(0) > 0) & gl.str.startswith("15"),
        "document_id",
    ]
    credit_expense = df.loc[
        (df["credit_amount"].fillna(0) > 0) & gl.str.startswith("6"),
        "document_id",
    ]

    # Why: 두 조건을 동시에 만족하는 document_id 집합
    flagged_docs = set(debit_asset) & set(credit_expense)

    if not flagged_docs:
        return pd.Series(False, index=df.index)

    return df["document_id"].isin(flagged_docs)
