"""groupby 기반 부정 탐지 룰 — B04, B05, B11.

원본 컬럼에 직접 접근하는 연산 집약 룰.
B04는 양방향 diff로 첫 번째 거래 누락을 방지한다.
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
    """B04 중복 지급: 동일 거래처 + 금액 + 기간 내 2건 이상.

    Why: PCAOB AS 2401 §32 — 동일 건 이중 지급은 부정 은닉 수단.
    알고리즘: sort → groupby → 양방향 diff (forward + backward).
             첫 행 NaT 문제를 backward diff로 보완하여 모든 중복 행 포착.
    """
    required = ["auxiliary_account_number", "posting_date", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    base_amount = _compute_base_amount(df)
    # Why: 원본 인덱스 보존을 위해 임시 컬럼 사용
    work = df[["auxiliary_account_number", "posting_date"]].copy()
    work["_base_amt"] = base_amount
    work = work.sort_values(["auxiliary_account_number", "_base_amt", "posting_date"])

    grouped = work.groupby(["auxiliary_account_number", "_base_amt"])
    window = pd.Timedelta(days=window_days)

    # Why: 단방향 diff만 쓰면 그룹 첫 행(NaT)이 누락 → 양방향으로 보완
    diff_forward = grouped["posting_date"].diff()
    diff_backward = grouped["posting_date"].diff(-1).abs()
    is_dup = (diff_forward <= window) | (diff_backward <= window)

    # Why: sort로 인덱스 순서가 바뀌었으므로 원본 인덱스 기준으로 정렬 복원
    return is_dup.reindex(df.index).fillna(False)


def b05_duplicate_entry(df: pd.DataFrame) -> pd.Series:
    """B05 중복 전표: 동일 GL계정 + 금액 + 전기일 exact match.

    Why: 외감법 §8①4호 — 동일 전표 반복은 가공 전표(위조) 징후.
    B04와 차별점: B04=기간 내 유사, B05=정확 중복.
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
    """B11 비용 자산화: 동일 전표 내 차변=자산(15xx) + 대변=비용(6xxx) 조합.

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
