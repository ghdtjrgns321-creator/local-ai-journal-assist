"""DuplicateDetector 서브룰 — Exact / Fuzzy / Split / TimeShift.

Why: 기존 B05 exact match recall 9%. 유사 금액, 분할 거래, 시차 중복을 잡기 위해
     4가지 전략을 독립 함수로 분리. 각 함수는 pd.Series[float] (0.0~1.0) 반환.
"""

from __future__ import annotations

import re
from itertools import combinations

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process as rfprocess

# ── 공용 유틸 ────────────────────────────────────────────────


def _base_amount(df: pd.DataFrame) -> pd.Series:
    """행별 대표 금액 = max(debit, credit). NaN → 0."""
    return df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)


_RE_SPECIAL = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize_text(s: str) -> str:
    """적요 정규화: 소문자 + 괄호/특수문자 제거 + 공백 정규화."""
    s = _RE_SPECIAL.sub("", str(s).lower())
    return " ".join(s.split())


# ── B05a: Exact Duplicate ────────────────────────────────────


def b05a_exact_duplicate(df: pd.DataFrame) -> pd.Series:
    """gl_account + 금액 + posting_date 정확 일치 → 1.0, 아니면 0.0.

    Why: 기존 B05 로직 재사용. keep=False로 원본·중복 양쪽 모두 플래그.
    """
    required = ["gl_account", "posting_date", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return pd.Series(0.0, index=df.index)

    work = df[["gl_account", "posting_date"]].copy()
    work["_amt"] = _base_amount(df)
    duped = work.duplicated(subset=["gl_account", "_amt", "posting_date"], keep=False)
    return duped.astype(float)


# ── B05b: Fuzzy Duplicate ────────────────────────────────────


def b05b_fuzzy_duplicate(
    df: pd.DataFrame,
    *,
    fuzzy_threshold: int = 80,
    amount_tolerance: float = 0.02,
    max_group_size: int = 1000,
) -> pd.Series:
    """같은 gl_account 내에서 적요 유사도 × 금액 근접도로 연속 점수 산출.

    Why: exact match가 놓치는 유사 금액 + 유사 적요 중복을 포착.
    Blocking: gl_account 그룹 내에서만 비교 (N² 방지).
    """
    scores = pd.Series(0.0, index=df.index)

    # Why: line_text 없으면 fuzzy 비교 불가 → 스킵
    if "line_text" not in df.columns or "gl_account" not in df.columns:
        return scores
    if not {"debit_amount", "credit_amount"}.issubset(df.columns):
        return scores

    amt = _base_amount(df)
    texts = df["line_text"].fillna("").map(_normalize_text)

    for _gl, grp in df.groupby("gl_account"):
        if len(grp) < 2:
            continue
        if len(grp) > max_group_size:
            continue  # warning은 오케스트레이터에서 처리

        idx = grp.index
        grp_texts = texts.loc[idx].values
        grp_amts = amt.loc[idx].values

        # Why: rapidfuzz cdist로 그룹 내 모든 쌍의 유사도 행렬 일괄 계산
        sim_matrix = rfprocess.cdist(
            grp_texts, grp_texts, scorer=fuzz.token_sort_ratio,
        ) / 100.0  # 0~100 → 0.0~1.0

        n = len(idx)
        for i in range(n):
            for j in range(i + 1, n):
                text_sim = sim_matrix[i][j]
                if text_sim < fuzzy_threshold / 100.0:
                    continue

                # Why: 금액 근접도 = 1 - 상대 차이. 차이 > tolerance면 스킵
                max_amt = max(grp_amts[i], grp_amts[j])
                if max_amt == 0:
                    continue
                rel_diff = abs(grp_amts[i] - grp_amts[j]) / max_amt
                if rel_diff > amount_tolerance:
                    continue

                amt_sim = 1.0 - rel_diff
                pair_score = text_sim * amt_sim

                # Why: 쌍 중 높은 점수를 양쪽에 부여 (원본·중복 모두 플래그)
                scores.at[idx[i]] = max(scores.at[idx[i]], pair_score)
                scores.at[idx[j]] = max(scores.at[idx[j]], pair_score)

    return scores


# ── B05c: Split Transaction ──────────────────────────────────


def b05c_split_transaction(
    df: pd.DataFrame,
    *,
    window_days: int = 3,
    amount_tolerance: float = 0.02,
    max_group_size: int = 1000,
) -> pd.Series:
    """분할 거래 탐지: 동일 gl_account 내 2건 합이 다른 단건과 근접.

    Why: 승인한도 회피 목적으로 100만→50만+50만 분할하는 패턴 포착.
    Pre-filter: 후보 금액 > 타겟 금액이면 조합에서 제외.
    """
    scores = pd.Series(0.0, index=df.index)

    required = ["gl_account", "posting_date", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return scores

    amt = _base_amount(df)

    for _gl, grp in df.groupby("gl_account"):
        if len(grp) < 3:  # Why: 최소 3건 (타겟 1 + 분할 2)
            continue
        if len(grp) > max_group_size:
            continue

        idx = grp.index
        grp_amts = amt.loc[idx].values
        grp_dates = pd.to_datetime(grp["posting_date"]).values

        for t_pos, t_idx in enumerate(idx):
            target = grp_amts[t_pos]
            if target <= 0:
                continue

            # Why: 타겟보다 큰 금액은 합산 후보가 될 수 없으므로 사전 제외
            candidates = [
                (c_pos, c_idx)
                for c_pos, c_idx in enumerate(idx)
                if c_pos != t_pos
                and grp_amts[c_pos] < target
                and grp_amts[c_pos] > 0
                and abs(
                    (grp_dates[c_pos] - grp_dates[t_pos])
                    / np.timedelta64(1, "D")
                ) <= window_days
            ]

            # Why: 2-way split만 검사 — 3-way는 O(n³)이고 승인한도 회피 주요 패턴은 2-way
            for (p1, i1), (p2, i2) in combinations(candidates, 2):
                pair_sum = grp_amts[p1] + grp_amts[p2]
                rel_diff = abs(pair_sum - target) / target
                if rel_diff <= amount_tolerance:
                    scores.at[t_idx] = max(scores.at[t_idx], 0.7)
                    scores.at[i1] = max(scores.at[i1], 0.7)
                    scores.at[i2] = max(scores.at[i2], 0.7)

    return scores


# ── B05d: Time-Shifted Duplicate ─────────────────────────────


def b05d_time_shifted_duplicate(
    df: pd.DataFrame,
    *,
    window_days: int = 7,
) -> pd.Series:
    """시차 중복: gl_account + 금액 동일, posting_date만 다른 경우.

    Why: 같은 거래를 다른 날짜에 중복 입력하는 패턴 포착.
    점수: 1 - (day_diff / window_days). 가까울수록 높은 점수.
    B05a(같은 날짜)와 겹치는 건은 제외.
    """
    scores = pd.Series(0.0, index=df.index)

    required = ["gl_account", "posting_date", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return scores

    amt = _base_amount(df)
    dates = pd.to_datetime(df["posting_date"])

    for _gl, grp in df.groupby("gl_account"):
        if len(grp) < 2:
            continue

        idx = grp.index
        grp_amts = amt.loc[idx].values
        grp_dates = dates.loc[idx].values

        n = len(idx)
        for i in range(n):
            for j in range(i + 1, n):
                # Why: 부동소수점 오차 방지 — 1원 이내 차이는 동일 금액으로 취급 (KRW 실무)
                if abs(grp_amts[i] - grp_amts[j]) > 1.0:
                    continue

                day_diff = abs(
                    (grp_dates[i] - grp_dates[j]) / np.timedelta64(1, "D")
                )
                # Why: 같은 날짜(day_diff=0)는 B05a에서 처리 → 여기선 제외
                if day_diff == 0 or day_diff > window_days:
                    continue

                pair_score = 1.0 - (day_diff / window_days)
                scores.at[idx[i]] = max(scores.at[idx[i]], pair_score)
                scores.at[idx[j]] = max(scores.at[idx[j]], pair_score)

    return scores
