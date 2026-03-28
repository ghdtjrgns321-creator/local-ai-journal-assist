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


_MIN_GROUP_FOR_BENFORD = 100  # 계정별 최소 표본 수 (미만이면 검정 무의미)


def c07_benford_violation(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """C07 Benford 위반: 계정별 분리 검정 + 전체 검정 하이브리드.

    Why: 감사기준서 520호 §5, PCAOB AS 240 A45(e).
         전체 데이터에서는 정상이지만 특정 계정(여비교통비, 접대비 등)에서만
         Benford 위반이 발생할 수 있다 — 계정별 분리 검정으로 정밀 탐지.

    전략:
      1단계: gl_account별 분리 검정 (n >= 100인 계정만)
             → 위반 계정의 편차 큰 자릿수 행만 플래그
      2단계: 전체 데이터 검정 (기존 로직) → 계정별에서 놓친 전역 패턴 보완

    Returns:
        (bool Series, metadata dict) — metadata에 benford_results 포함.
    """
    s = settings or get_settings()
    meta: dict[str, Any] = {}

    if "first_digit" not in df.columns:
        return pd.Series(False, index=df.index), meta

    flagged = pd.Series(False, index=df.index)

    # ── 1단계: 계정별 분리 검정 ──
    # Why: 특정 계정에서만 찌그러진 분포를 잡아내는 정밀 탐지
    group_results: dict[str, Any] = {}
    if "gl_account" in df.columns:
        gl_groups = df.groupby("gl_account")["first_digit"]
        for gl_account, group_digits in gl_groups:
            if len(group_digits) < _MIN_GROUP_FOR_BENFORD:
                continue
            result, _ = analyze_benford(group_digits, settings=s)
            if not result.is_conforming:
                # Why: 위반 계정 내에서 편차 큰 자릿수만 선별 (전체 행 플래그 방지)
                bad_digits = {
                    d for d in range(1, 10)
                    if abs(result.observed.get(d, 0.0) - BENFORD_EXPECTED[d]) > s.benford_mad_threshold
                }
                if bad_digits:
                    mask = (df["gl_account"] == gl_account) & df["first_digit"].isin(bad_digits)
                    flagged = flagged | mask
                    group_results[str(gl_account)] = {
                        "mad": result.mad,
                        "flagged_digits": sorted(bad_digits),
                        "sample_size": len(group_digits),
                    }

    meta["benford_group_results"] = group_results

    # ── 2단계: 전체 검정 (기존 로직) ──
    # Why: 계정별 검정에서 놓친 전역 패턴 보완
    result, _warnings = analyze_benford(df["first_digit"], settings=s)
    meta["benford_result"] = result

    if not result.is_conforming:
        flagged_digits = {
            d for d in range(1, 10)
            if abs(result.observed.get(d, 0.0) - BENFORD_EXPECTED[d]) > s.benford_mad_threshold
        }
        if flagged_digits:
            flagged = flagged | df["first_digit"].isin(flagged_digits).fillna(False)

    return flagged, meta


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
