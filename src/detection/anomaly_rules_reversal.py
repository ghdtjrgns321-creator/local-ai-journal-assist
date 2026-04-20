"""Reversal-pattern rule helpers for L2-06."""

from __future__ import annotations

import logging
import re
import time

import numpy as np
import pandas as pd

from config.settings import get_audit_rules

logger = logging.getLogger(__name__)

_W_S1 = 0.35
_W_S2 = 0.25
_W_S2B = _W_S1
_W_S3 = 0.15
_W_S4 = 0.10
_S5_BOOST = 1.5
_NET_GROSS_RATIO_THRESHOLD = 0.05
_LINE_SWAP_TOLERANCE = 1.0
_LARGE_GROUP_WARN = 500
_CORE_COLUMNS = ["gl_account", "debit_amount", "credit_amount", "posting_date", "document_id"]

_FALLBACK_REVERSAL_KEYWORDS = [
    "reversal",
    "reverse",
    "cancel",
    "correct",
    "adjust",
    "restatement",
    "error",
    "void",
    "write off",
    "write-off",
    "writeoff",
    "correction",
    "reclass",
    "reclassification",
    "reverse entry",
    "reversing entry",
    "수정",
    "정정",
    "오류",
    "취소",
    "역분개",
    "조정",
]

_FALLBACK_EXCLUDE_ACCOUNTS = ["2900", "1150", "2050"]


def _load_reversal_keywords() -> list[str]:
    """Load reversal keywords from audit rules with a safe fallback."""

    try:
        rules = get_audit_rules()
        keywords = rules.get("patterns", {}).get("reversal_keywords", [])
        return [str(keyword) for keyword in keywords] or _FALLBACK_REVERSAL_KEYWORDS
    except Exception:
        return _FALLBACK_REVERSAL_KEYWORDS


def _load_exclude_accounts() -> list[str]:
    """Load GL-account prefixes excluded from reversal logic."""

    try:
        rules = get_audit_rules()
        prefixes = rules.get("patterns", {}).get("reversal_exclude_accounts", [])
        return [str(prefix) for prefix in prefixes] or _FALLBACK_EXCLUDE_ACCOUNTS
    except Exception:
        return _FALLBACK_EXCLUDE_ACCOUNTS


_REVERSAL_KEYWORDS = _load_reversal_keywords()
_REVERSAL_PATTERN = re.compile(
    "|".join(keyword for keyword in _REVERSAL_KEYWORDS),
    re.IGNORECASE,
)
_EXCLUDE_ACCOUNTS = _load_exclude_accounts()


def _s1_one_to_one_match(
    df: pd.DataFrame,
    match_window_days: int = 1,
) -> pd.Series:
    """Return True for rows that form a one-to-one reversal pair."""

    required = ["document_id", "gl_account", "debit_amount", "credit_amount", "posting_date"]
    if any(column not in df.columns for column in required):
        return pd.Series(False, index=df.index)

    work = pd.DataFrame(index=df.index)
    work["document_id"] = df["document_id"].astype(str)
    work["gl_account"] = df["gl_account"].astype(str)
    work["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    work["net"] = (
        pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
        - pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    )
    work["abs_amt"] = work["net"].abs().round(2)
    work["orig_idx"] = df.index

    nonzero_mask = work["net"].ne(0.0)
    if _EXCLUDE_ACCOUNTS:
        nonzero_mask &= ~work["gl_account"].apply(
            lambda value: any(value.startswith(prefix) for prefix in _EXCLUDE_ACCOUNTS)
        )
    work = work.loc[nonzero_mask].dropna(subset=["posting_date"])
    if len(work) < 2:
        return pd.Series(False, index=df.index)

    group_sizes = work.groupby(["gl_account", "abs_amt"]).size()
    large_groups = int((group_sizes > _LARGE_GROUP_WARN).sum())
    if large_groups:
        logger.warning(
            "L2-06 S1 found %d large groups above %d rows",
            large_groups,
            _LARGE_GROUP_WARN,
        )

    matched_indices: set[int] = set()
    for (_, _), group in work.groupby(["gl_account", "abs_amt"], sort=False):
        positives = group[group["net"] > 0].sort_values("posting_date")
        negatives = group[group["net"] < 0].sort_values("posting_date")
        if positives.empty or negatives.empty:
            continue

        negative_rows = list(negatives.itertuples(index=False))
        for pos in positives.itertuples(index=False):
            for neg in negative_rows:
                if pos.document_id == neg.document_id:
                    continue
                day_gap = abs((pos.posting_date - neg.posting_date).days)
                if day_gap > match_window_days:
                    continue
                matched_indices.add(int(pos.orig_idx))
                matched_indices.add(int(neg.orig_idx))

    return pd.Series(df.index.isin(matched_indices), index=df.index)


def _s2_rolling_zero_out(
    df: pd.DataFrame,
    rolling_window_days: int = 7,
    zero_threshold: float = 1000.0,
) -> pd.Series:
    """Return True when a user/account group nets close to zero inside a rolling window."""

    required = ["gl_account", "debit_amount", "credit_amount", "posting_date", "created_by"]
    if any(column not in df.columns for column in required):
        return pd.Series(False, index=df.index)

    work = pd.DataFrame(index=df.index)
    work["gl_account"] = df["gl_account"].astype(str)
    work["created_by"] = df["created_by"].astype(str)
    work["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    work["net"] = (
        pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
        - pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    )
    work["gross"] = (
        pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
        + pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    )
    if _EXCLUDE_ACCOUNTS:
        work = work[
            ~work["gl_account"].apply(lambda value: any(value.startswith(prefix) for prefix in _EXCLUDE_ACCOUNTS))
        ]
    work = work.dropna(subset=["posting_date"])
    if len(work) < 2:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    delta = pd.Timedelta(days=rolling_window_days)

    for (_, _), group in work.groupby(["gl_account", "created_by"], sort=False):
        group = group.sort_values("posting_date")
        if len(group) < 2:
            continue
        if not ((group["net"] > 0).any() and (group["net"] < 0).any()):
            continue

        dates = group["posting_date"].tolist()
        rows = list(group.index)
        left = 0
        for right in range(len(group)):
            while dates[right] - dates[left] > delta:
                left += 1
            window = group.iloc[left : right + 1]
            if len(window) < 2:
                continue
            window_net = float(window["net"].sum())
            window_gross = float(window["gross"].sum())
            if window_gross <= 0:
                continue
            if abs(window_net) < zero_threshold and abs(window_net) / window_gross < _NET_GROSS_RATIO_THRESHOLD:
                result.loc[rows[left : right + 1]] = True

    return result


def _s2b_line_swap_signature(
    df: pd.DataFrame,
    tolerance: float = _LINE_SWAP_TOLERANCE,
) -> pd.Series:
    """Return True when a single swapped line explains the document imbalance."""

    if "document_id" not in df.columns:
        return pd.Series(False, index=df.index)

    work = pd.DataFrame(index=df.index)
    work["document_id"] = df["document_id"].astype(str)
    work["debit_amount"] = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    work["credit_amount"] = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    work["net"] = work["debit_amount"] - work["credit_amount"]
    work["abs_line_amt"] = work[["debit_amount", "credit_amount"]].max(axis=1)

    result = pd.Series(False, index=df.index)
    for _, group in work.groupby("document_id", sort=False):
        if len(group) < 2:
            continue
        doc_net = float(group["net"].sum())
        if abs(doc_net) <= tolerance:
            continue
        if np.any(np.abs((group["abs_line_amt"] * 2.0) - abs(doc_net)) <= tolerance):
            result.loc[group.index] = True

    return result


def _s3_reversal_type(df: pd.DataFrame) -> pd.Series:
    """Return a positive or negative adjustment based on entry type."""

    if "source" not in df.columns or "posting_date" not in df.columns:
        return pd.Series(0.0, index=df.index)

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    source = df["source"].astype(str).str.lower()
    is_auto = source.isin(["auto", "automated", "recurring"])
    is_month_start = posting_date.dt.day <= 5
    is_january = posting_date.dt.month == 1

    result = pd.Series(0.0, index=df.index)
    result[is_auto & is_month_start & is_january] = -_W_S3
    result[is_auto & is_month_start & ~is_january] = -(_W_S3 * 0.67)
    result[~is_auto] = _W_S3
    return result


def _s4_keyword_match(df: pd.DataFrame) -> pd.Series:
    """Return True when the line text includes a reversal keyword."""

    if "line_text" not in df.columns:
        return pd.Series(False, index=df.index)
    text = df["line_text"].fillna("").astype(str)
    return text.str.contains(_REVERSAL_PATTERN, na=False)


def _s5_period_end_boost(df: pd.DataFrame) -> pd.Series:
    """Return a year-end boost multiplier."""

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    month = posting_date.dt.month
    day = posting_date.dt.day
    boost_mask = ((month == 12) & (day >= 20)) | ((month == 1) & (day <= 5))
    result = pd.Series(1.0, index=df.index)
    result[boost_mask] = _S5_BOOST
    return result


def c11_reversal_entry(
    df: pd.DataFrame,
    *,
    match_window_days: int = 1,
    rolling_window_days: int = 7,
    zero_threshold: float = 1000.0,
    score_threshold: float = 0.3,
) -> pd.Series:
    """Composite reversal-pattern detector used for rule L2-06."""

    missing = [column for column in _CORE_COLUMNS if column not in df.columns]
    if missing or len(df) < 2:
        if missing:
            logger.warning("L2-06 missing required columns: %s", missing)
        return pd.Series(False, index=df.index)

    start = time.perf_counter()
    s1 = _s1_one_to_one_match(df, match_window_days=match_window_days)
    logger.warning("[TIMING] layer_c.L2-06.S1: %.2fs (rows=%d)", time.perf_counter() - start, len(df))

    start = time.perf_counter()
    s2 = _s2_rolling_zero_out(
        df,
        rolling_window_days=rolling_window_days,
        zero_threshold=zero_threshold,
    )
    logger.warning("[TIMING] layer_c.L2-06.S2: %.2fs (rows=%d)", time.perf_counter() - start, len(df))

    start = time.perf_counter()
    s2b = _s2b_line_swap_signature(df)
    logger.warning("[TIMING] layer_c.L2-06.S2b: %.2fs (rows=%d)", time.perf_counter() - start, len(df))

    start = time.perf_counter()
    s3 = _s3_reversal_type(df)
    logger.warning("[TIMING] layer_c.L2-06.S3: %.2fs (rows=%d)", time.perf_counter() - start, len(df))

    start = time.perf_counter()
    s4 = _s4_keyword_match(df)
    logger.warning("[TIMING] layer_c.L2-06.S4: %.2fs (rows=%d)", time.perf_counter() - start, len(df))

    start = time.perf_counter()
    s5 = _s5_period_end_boost(df)
    logger.warning("[TIMING] layer_c.L2-06.S5: %.2fs (rows=%d)", time.perf_counter() - start, len(df))

    s1_contextual = s1 & s4
    base_score = (
        s1_contextual.astype(float) * _W_S1
        + s2.astype(float) * _W_S2
        + s2b.astype(float) * _W_S2B
        + s4.astype(float) * _W_S4
    )
    adjusted = (base_score + s3) * s5
    final_score = adjusted.clip(0.0, 1.0)

    has_amount_pattern = s1_contextual | s2.astype(bool) | s2b.astype(bool)
    return (final_score >= score_threshold) & has_amount_pattern
