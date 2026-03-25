"""통계 기반 이상 징후 룰 — C07 Benford, C09 비정상 계정조합.

C07: validation/benford.py의 analyze_benford() 재사용. 편차 큰 자릿수만 선별 플래그.
C09: merge 기반 Cartesian Product로 복합 분개(N:M) 계정 쌍 빈도 분석.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

from config.settings import AuditSettings, get_settings
from src.validation.benford import BENFORD_EXPECTED, analyze_benford


def c07_benford_violation(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """C07 Benford 위반: 첫째자리 분포가 Benford 법칙에서 벗어난 행 플래그.

    Why: 감사기준서 520호 §5, PCAOB AS 240 A45(e).
         전체 분포가 비적합일 때만 트리거 → 편차 큰 자릿수의 행만 선별.
         전체 행 플래그는 과탐이므로, 기여도 높은 자릿수만 표본 추출.

    Returns:
        (bool Series, metadata dict) — metadata에 benford_result 포함.
    """
    s = settings or get_settings()
    meta: dict[str, Any] = {}

    if "first_digit" not in df.columns:
        return pd.Series(False, index=df.index), meta

    result, _warnings = analyze_benford(df["first_digit"], settings=s)
    meta["benford_result"] = result

    if result.is_conforming:
        return pd.Series(False, index=df.index), meta

    # Why: 개별 자릿수 편차가 MAD 임계값 초과인 자릿수만 선별
    flagged_digits = {
        d for d in range(1, 10)
        if abs(result.observed.get(d, 0.0) - BENFORD_EXPECTED[d]) > s.benford_mad_threshold
    }

    if not flagged_digits:
        return pd.Series(False, index=df.index), meta

    return df["first_digit"].isin(flagged_digits).fillna(False), meta


def c09_rare_account_pair(
    df: pd.DataFrame,
    percentile: float = 0.01,
) -> pd.Series:
    """C09 비정상 계정조합: 차변-대변 계정 쌍 빈도 하위 N%.

    Why: PCAOB AS 240 A49(a), ISA 315 — 희소한 계정 조합은 비정상 거래 의심.
         복합 분개(N:M)를 merge 기반 Cartesian Product로 처리하여
         반복문 없이 벡터화 연산으로 모든 (차변, 대변) 쌍 생성.
    """
    required = ["document_id", "gl_account", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return pd.Series(False, index=df.index)

    # 1. 차변/대변 뷰 분리
    debit_amt = df["debit_amount"].fillna(0)
    credit_amt = df["credit_amount"].fillna(0)

    debits = df.loc[debit_amt > 0, ["document_id", "gl_account"]]
    credits = df.loc[credit_amt > 0, ["document_id", "gl_account"]]

    if debits.empty or credits.empty:
        return pd.Series(False, index=df.index)

    # Why: 단일 전표 내 행 수가 과다하면 Cartesian Product로 메모리 폭발 가능
    #      (차변 50 × 대변 50 = 2,500행/전표) — 임계 초과 전표는 제외
    _MAX_LINES_PER_DOC = 100
    doc_sizes = df.groupby("document_id").size()
    bloated = doc_sizes[doc_sizes > _MAX_LINES_PER_DOC].index
    if not bloated.empty:
        logger.warning(
            "C09: %d개 전표가 %d행 초과 — Cartesian Product 제한으로 제외",
            len(bloated), _MAX_LINES_PER_DOC,
        )
        debits = debits[~debits["document_id"].isin(bloated)]
        credits = credits[~credits["document_id"].isin(bloated)]

    if debits.empty or credits.empty:
        return pd.Series(False, index=df.index)

    # 2. document_id 기준 inner join → N:M 복합 분개의 모든 쌍 생성
    pairs = debits.merge(credits, on="document_id", suffixes=("_dr", "_cr"))

    if pairs.empty:
        return pd.Series(False, index=df.index)

    # 3. 쌍별 빈도 계산 → 하위 percentile 임계값
    pair_counts = pairs.groupby(["gl_account_dr", "gl_account_cr"]).size()
    # Why: quantile이 0을 반환하면 모든 쌍이 희소로 분류되는 것을 방지
    threshold = max(pair_counts.quantile(percentile), 1)

    # 4. 희소 쌍 → merge 기반 벡터화 판별 (tuple isin 대비 성능 우수)
    rare_idx = pair_counts[pair_counts <= threshold].reset_index()
    rare_idx.columns = ["gl_account_dr", "gl_account_cr", "_count"]
    rare_idx["_rare"] = True
    pairs = pairs.merge(
        rare_idx[["gl_account_dr", "gl_account_cr", "_rare"]],
        on=["gl_account_dr", "gl_account_cr"],
        how="left",
    )
    rare_docs = set(pairs.loc[pairs["_rare"] == True, "document_id"])  # noqa: E712

    # 5. 원본 df에 매핑 → 해당 document의 모든 행 플래그
    return df["document_id"].isin(rare_docs)
