"""DuplicateDetector 서브룰 — Exact / Fuzzy / Split / TimeShift.

Why: 기존 L2-03 exact match recall 9%. 유사 금액, 분할 거래, 시차 중복을 잡기 위해
     4가지 전략을 독립 함수로 분리. 각 함수는 pd.Series[float] (0.0~1.0) 반환.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz import process as rfprocess

# ── 공용 유틸 ────────────────────────────────────────────────


def _base_amount(df: pd.DataFrame) -> pd.Series:
    """행별 대표 금액 = max(debit, credit). NaN → 0."""
    return df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)


_RE_SPECIAL = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize_text(s: str) -> str:
    """적요 정규화: 소문자 + 괄호/특수문자 제거 + 공백 정규화."""
    s = _RE_SPECIAL.sub("", str(s).lower())
    return " ".join(s.split())


def _normalize_text_series(series: pd.Series) -> pd.Series:
    """반복 적요가 많은 원장 데이터에서 정규화 결과를 재사용한다."""
    raw = series.fillna("").astype(str)
    unique_values = raw.unique()
    normalized = {value: _normalize_text(value) for value in unique_values}
    return raw.map(normalized)


# ── L2-03a: Exact Duplicate ────────────────────────────────────


def b05a_exact_duplicate(df: pd.DataFrame) -> pd.Series:
    """gl_account + 금액 + posting_date 정확 일치 → 1.0, 아니면 0.0.

    Why: 기존 L2-03 로직 재사용. keep=False로 원본·중복 양쪽 모두 플래그.
    """
    required = ["gl_account", "posting_date", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return pd.Series(0.0, index=df.index)

    work = df[["gl_account", "posting_date"]].copy()
    work["_amt"] = _base_amount(df)
    duped = work.duplicated(subset=["gl_account", "_amt", "posting_date"], keep=False)
    return duped.astype(float)


# ── L2-03b: Fuzzy Duplicate ────────────────────────────────────


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
    texts = _normalize_text_series(df["line_text"])
    threshold = fuzzy_threshold / 100.0
    score_values = np.zeros(len(df), dtype=float)
    positions = pd.Series(np.arange(len(df)), index=df.index)

    work = pd.DataFrame(
        {
            "gl_account": df["gl_account"],
            "amount": amt,
            "text": texts,
            "_pos": positions,
        },
        index=df.index,
    )

    for _gl, grp in work.groupby("gl_account", sort=False):
        if len(grp) < 2:
            continue
        if len(grp) > max_group_size:
            continue  # warning은 오케스트레이터에서 처리

        ordered = grp.sort_values("amount", kind="mergesort")
        grp_texts = ordered["text"].to_numpy(dtype=object)
        grp_amts = ordered["amount"].to_numpy(dtype=float)
        grp_pos = ordered["_pos"].to_numpy(dtype=int)

        n = len(ordered)
        upper = 1
        for i in range(n):
            base_amt = grp_amts[i]
            if base_amt <= 0:
                continue
            if upper < i + 1:
                upper = i + 1
            max_candidate_amt = base_amt / max(1.0 - amount_tolerance, 1e-12)
            while upper < n and grp_amts[upper] <= max_candidate_amt:
                upper += 1
            if upper <= i + 1:
                continue

            candidate_texts = grp_texts[i + 1 : upper]
            text_sims = (
                rfprocess.cdist(
                    [grp_texts[i]],
                    candidate_texts,
                    scorer=fuzz.token_sort_ratio,
                    dtype=np.float32,
                )[0]
                / 100.0
            )
            candidate_offsets = np.flatnonzero(text_sims >= threshold)
            if len(candidate_offsets) == 0:
                continue

            candidate_idx = i + 1 + candidate_offsets
            rel_diff = np.abs(grp_amts[candidate_idx] - base_amt) / np.maximum(
                grp_amts[candidate_idx], base_amt
            )
            valid = rel_diff <= amount_tolerance
            if not np.any(valid):
                continue

            valid_idx = candidate_idx[valid]
            pair_scores = text_sims[candidate_offsets[valid]] * (1.0 - rel_diff[valid])
            base_score = float(pair_scores.max())
            score_values[grp_pos[i]] = max(score_values[grp_pos[i]], base_score)
            np.maximum.at(score_values, grp_pos[valid_idx], pair_scores)

    return pd.Series(score_values, index=df.index)


# ── L2-03c: Split Transaction ──────────────────────────────────


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
    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    score_values = np.zeros(len(df), dtype=float)
    positions = pd.Series(np.arange(len(df)), index=df.index)
    day_ns = np.timedelta64(1, "D").astype("timedelta64[ns]").astype(np.int64)
    window_ns = int(window_days * day_ns)

    work = pd.DataFrame(
        {
            "gl_account": df["gl_account"],
            "posting_date": dates,
            "amount": amt,
            "_pos": positions,
        },
        index=df.index,
    ).dropna(subset=["posting_date"])

    for _gl, grp in work.groupby("gl_account", sort=False):
        if len(grp) < 3:  # Why: 최소 3건 (타겟 1 + 분할 2)
            continue
        if len(grp) > max_group_size:
            continue

        ordered = grp.sort_values("posting_date", kind="mergesort")
        grp_amts = ordered["amount"].to_numpy(dtype=float)
        grp_dates = ordered["posting_date"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
        grp_pos = ordered["_pos"].to_numpy(dtype=int)

        n = len(ordered)
        for t_pos in range(n):
            target = grp_amts[t_pos]
            if target <= 0:
                continue

            left = np.searchsorted(grp_dates, grp_dates[t_pos] - window_ns, side="left")
            right = np.searchsorted(grp_dates, grp_dates[t_pos] + window_ns, side="right")
            if right - left < 3:
                continue

            window_positions = np.arange(left, right)
            mask = (
                (window_positions != t_pos)
                & (grp_amts[window_positions] > 0)
                & (grp_amts[window_positions] < target)
            )
            candidate_positions = window_positions[mask]
            if len(candidate_positions) < 2:
                continue

            candidate_amounts = grp_amts[candidate_positions]
            order = np.argsort(candidate_amounts, kind="mergesort")
            sorted_amounts = candidate_amounts[order]
            sorted_positions = candidate_positions[order]
            low = target * (1.0 - amount_tolerance)
            high = target * (1.0 + amount_tolerance)

            target_hit = False
            for left_pos, left_amount in enumerate(sorted_amounts[:-1]):
                lo_idx = np.searchsorted(
                    sorted_amounts, low - left_amount, side="left", sorter=None
                )
                hi_idx = np.searchsorted(
                    sorted_amounts, high - left_amount, side="right", sorter=None
                )
                lo_idx = max(lo_idx, left_pos + 1)
                if hi_idx <= lo_idx:
                    continue
                target_hit = True
                score_values[grp_pos[sorted_positions[left_pos]]] = max(
                    score_values[grp_pos[sorted_positions[left_pos]]], 0.7
                )
                hit_positions = sorted_positions[lo_idx:hi_idx]
                score_values[grp_pos[hit_positions]] = np.maximum(
                    score_values[grp_pos[hit_positions]], 0.7
                )

            if target_hit:
                score_values[grp_pos[t_pos]] = max(score_values[grp_pos[t_pos]], 0.7)

    return pd.Series(score_values, index=df.index)


# ── L2-03d: Time-Shifted Duplicate ─────────────────────────────


def b05d_time_shifted_duplicate(
    df: pd.DataFrame,
    *,
    window_days: int = 7,
) -> pd.Series:
    """시차 중복: gl_account + 금액 동일, posting_date만 다른 경우.

    Why: 같은 거래를 다른 날짜에 중복 입력하는 패턴 포착.
    점수: 1 - (day_diff / window_days). 가까울수록 높은 점수.
    L2-03a(같은 날짜)와 겹치는 건은 제외.
    """
    scores = pd.Series(0.0, index=df.index)

    required = ["gl_account", "posting_date", "debit_amount", "credit_amount"]
    if any(c not in df.columns for c in required):
        return scores

    amt = _base_amount(df)
    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    score_values = np.zeros(len(df), dtype=float)
    positions = pd.Series(np.arange(len(df)), index=df.index)
    day_ns = np.timedelta64(1, "D").astype("timedelta64[ns]").astype(np.int64)
    window_ns = int(window_days * day_ns)

    valid = dates.notna().to_numpy()
    if not np.any(valid):
        return scores

    gl_codes = pd.factorize(df["gl_account"], sort=False)[0][valid]
    amounts = amt.to_numpy(dtype=float)[valid]
    floors = np.floor(amounts).astype(np.int64, copy=False)
    date_ns = dates.to_numpy(dtype="datetime64[ns]").astype(np.int64)[valid]
    pos = positions.to_numpy(dtype=int)[valid]

    order = np.lexsort((floors, gl_codes))
    gl_codes = gl_codes[order]
    floors = floors[order]
    amounts = amounts[order]
    date_ns = date_ns[order]
    pos = pos[order]

    group_breaks = np.flatnonzero(
        (gl_codes[1:] != gl_codes[:-1]) | (floors[1:] != floors[:-1])
    ) + 1
    starts = np.r_[0, group_breaks]
    ends = np.r_[group_breaks, len(order)]

    def score_window(
        group_dates: np.ndarray,
        group_pos: np.ndarray,
    ) -> None:
        if len(group_pos) < 2:
            return
        date_order = np.argsort(group_dates, kind="mergesort")
        grp_dates = group_dates[date_order]
        grp_pos = group_pos[date_order]
        n = len(grp_pos)
        upper = 1
        for i in range(n):
            if upper < i + 1:
                upper = i + 1
            while upper < n and grp_dates[upper] - grp_dates[i] <= window_ns:
                upper += 1
            if upper <= i + 1:
                continue
            valid_idx = np.arange(i + 1, upper)
            day_diff = (grp_dates[i + 1 : upper] - grp_dates[i]) / day_ns
            nonzero_day = day_diff != 0
            if not np.any(nonzero_day):
                continue
            valid_idx = valid_idx[nonzero_day]
            pair_scores = 1.0 - (day_diff[nonzero_day] / window_days)
            base_score = float(pair_scores.max())
            score_values[grp_pos[i]] = max(score_values[grp_pos[i]], base_score)
            np.maximum.at(score_values, grp_pos[valid_idx], pair_scores)

    for start, end in zip(starts, ends, strict=True):
        if end - start >= 2:
            score_window(date_ns[start:end], pos[start:end])

    return pd.Series(score_values, index=df.index)
