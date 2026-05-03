"""Reversal-pattern rule helpers for L2-05."""

from __future__ import annotations

import logging
import re
import time

import numpy as np
import pandas as pd

from config.settings import get_audit_rules

logger = logging.getLogger(__name__)

_W_S1 = 0.35
_W_S0 = 0.60
_W_S2 = 0.30
_W_S2B = _W_S1
_W_S3 = 0.15
_W_S4 = 0.10
_S5_BOOST = 1.5
_NET_GROSS_RATIO_THRESHOLD = 0.05
_LINE_SWAP_TOLERANCE = 1.0
_LARGE_GROUP_WARN = 500
_CORE_COLUMNS = ["gl_account", "debit_amount", "credit_amount", "posting_date", "document_id"]
_STRUCTURAL_REFERENCE_COLUMNS = [
    "original_document_id",
    "reversal_document_id",
    "reference_document_id",
    "reversed_document_id",
    "reverse_document_id",
]
_REVERSAL_REASON_COLUMNS = ["reversal_reason", "reversal_reason_code"]
_CONTEXT_TEXT_PATTERN = re.compile(r"[^0-9A-Za-z가-힣]+")

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

_SIGNAL_PRIORITY = ("S0", "S2b", "S1", "S2")


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


def _has_value(series: pd.Series) -> pd.Series:
    """Return True for meaningful non-empty ERP reference values."""

    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.ne("") & ~normalized.isin(["nan", "none", "null"])


def _normalize_value(value: object) -> str:
    """Return a lowercase stripped string for context comparisons."""

    normalized = str(value).strip().lower() if value is not None else ""
    return "" if normalized in {"", "nan", "none", "null"} else normalized


def _normalize_text(value: object) -> str:
    """Return a compact normalized text string for similarity checks."""

    normalized = _normalize_value(value)
    if not normalized:
        return ""
    normalized = _CONTEXT_TEXT_PATTERN.sub(" ", normalized)
    return " ".join(normalized.split())


def _first_nonempty_group_values(
    work: pd.DataFrame,
    group_cols: list[str],
    value_col: str,
    *,
    normalizer,
) -> pd.Series:
    """Return first meaningful group value without groupby Python callbacks."""

    subset = work[group_cols + [value_col]].copy()
    subset["_norm"] = subset[value_col].map(normalizer)
    subset = subset.loc[subset["_norm"].ne("")]
    if subset.empty:
        empty_index = pd.MultiIndex.from_arrays(
            [[] for _ in group_cols],
            names=group_cols,
        )
        return pd.Series(index=empty_index, dtype=object)
    return subset.drop_duplicates(group_cols).set_index(group_cols)[value_col]


def _pair_context_score(left: dict[str, object], right: dict[str, object]) -> int:
    """Score contextual consistency between two candidate reversal rows."""

    score = 0

    left_created_by = str(left.get("created_by_norm", ""))
    right_created_by = str(right.get("created_by_norm", ""))
    if left_created_by and left_created_by == right_created_by:
        score += 1

    left_reference = str(left.get("reference_norm", ""))
    right_reference = str(right.get("reference_norm", ""))
    if left_reference and left_reference == right_reference:
        score += 2

    left_doc_type = str(left.get("document_type_norm", ""))
    right_doc_type = str(right.get("document_type_norm", ""))
    if left_doc_type and left_doc_type == right_doc_type:
        score += 1

    left_line = str(left.get("line_text_norm", ""))
    right_line = str(right.get("line_text_norm", ""))
    if left_line and left_line == right_line:
        score += 1

    left_header = str(left.get("header_text_norm", ""))
    right_header = str(right.get("header_text_norm", ""))
    if left_header and left_header == right_header:
        score += 1

    left_keyword = bool(left.get("line_keyword", False))
    right_keyword = bool(right.get("line_keyword", False))
    if left_keyword or right_keyword:
        score += 1

    return score


def _window_context_score(window: pd.DataFrame) -> int:
    """Score whether a rolling zero-out window looks like a reversal context."""

    score = 0

    if "reference" in window.columns:
        references = window["reference"].map(_normalize_value)
        references = references[references.ne("")]
        if not references.empty and references.nunique() < len(references):
            score += 2

    if "document_type" in window.columns:
        doc_types = window["document_type"].map(_normalize_value)
        doc_types = doc_types[doc_types.ne("")]
        if not doc_types.empty and doc_types.nunique() == 1:
            score += 1

    if "source" in window.columns:
        sources = window["source"].map(_normalize_value)
        if sources.isin(["manual", "adjustment"]).any():
            score += 1

    if "line_text" in window.columns:
        line_text = window["line_text"].map(_normalize_text)
        line_text = line_text[line_text.ne("")]
        if not line_text.empty and line_text.nunique() < len(line_text):
            score += 1
        if (
            window["line_text"]
            .fillna("")
            .astype(str)
            .str.contains(_REVERSAL_PATTERN, na=False)
            .any()
        ):
            score += 1

    return score


def _window_context_score_prepared(window: pd.DataFrame) -> int:
    """Score a rolling zero-out window using pre-normalized S2 columns."""

    score = 0

    references = window["reference_norm"]
    references = references[references.ne("")]
    if not references.empty and references.nunique() < len(references):
        score += 2

    doc_types = window["document_type_norm"]
    doc_types = doc_types[doc_types.ne("")]
    if not doc_types.empty and doc_types.nunique() == 1:
        score += 1

    if window["source_norm"].isin(["manual", "adjustment"]).any():
        score += 1

    line_text = window["line_text_norm"]
    line_text = line_text[line_text.ne("")]
    if not line_text.empty and line_text.nunique() < len(line_text):
        score += 1
    if window["line_keyword"].any():
        score += 1

    return score


def _has_possible_s1_context(positives: pd.DataFrame, negatives: pd.DataFrame) -> bool:
    """Return True when a group has any plausible contextual bridge for S1."""

    def _shared_nonempty(column: str) -> bool:
        left = set(positives[column]) - {""}
        right = set(negatives[column]) - {""}
        return bool(left & right)

    if _shared_nonempty("reference_norm"):
        return True

    shared_count = sum(
        [
            _shared_nonempty("created_by_norm"),
            _shared_nonempty("document_type_norm"),
            _shared_nonempty("line_text_norm"),
            _shared_nonempty("header_text_norm"),
        ]
    )
    if shared_count >= 2:
        return True

    keyword_any = bool(positives["line_keyword"].any() or negatives["line_keyword"].any())
    return keyword_any and shared_count >= 1


def _group_context_upper_bound(group: pd.DataFrame) -> int:
    """Return a cheap upper-bound context score for an S2 group."""

    score = 0

    if "reference" in group.columns:
        references = group["reference"].map(_normalize_value)
        references = references[references.ne("")]
        if not references.empty and references.nunique() < len(references):
            score += 2

    if "document_type" in group.columns:
        doc_types = group["document_type"].map(_normalize_value)
        doc_types = doc_types[doc_types.ne("")]
        if not doc_types.empty and doc_types.nunique() == 1:
            score += 1

    if "source" in group.columns:
        sources = group["source"].map(_normalize_value)
        if sources.isin(["manual", "adjustment"]).any():
            score += 1

    if "line_text" in group.columns:
        line_text = group["line_text"].map(_normalize_text)
        line_text = line_text[line_text.ne("")]
        if not line_text.empty and line_text.nunique() < len(line_text):
            score += 1
        if (
            group["line_text"]
            .fillna("")
            .astype(str)
            .str.contains(_REVERSAL_PATTERN, na=False)
            .any()
        ):
            score += 1

    return score


def _s0_structural_reversal_reference(df: pd.DataFrame) -> pd.Series:
    """Return True when ERP fields explicitly link original/reversal documents."""

    if "document_id" not in df.columns:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    doc_ids = df["document_id"].fillna("").astype(str).str.strip()
    referenced_ids: set[str] = set()

    for column in _STRUCTURAL_REFERENCE_COLUMNS:
        if column not in df.columns:
            continue
        values = df[column].fillna("").astype(str).str.strip()
        value_mask = _has_value(values)
        result |= value_mask
        referenced_ids.update(values[value_mask].tolist())

    for column in _REVERSAL_REASON_COLUMNS:
        if column in df.columns:
            result |= _has_value(df[column])

    referenced_ids.discard("")
    if referenced_ids:
        result |= doc_ids.isin(referenced_ids)

    return result


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
    for column in ["created_by", "reference", "document_type", "line_text", "header_text"]:
        work[column] = df[column] if column in df.columns else ""

    group_cols = ["document_id", "gl_account"]
    doc_work = (
        work.groupby(group_cols, sort=False)
        .agg(
            posting_date=("posting_date", "min"),
            net=("net", "sum"),
        )
        .reset_index()
    )
    for column, normalizer in {
        "created_by": _normalize_value,
        "reference": _normalize_value,
        "document_type": _normalize_value,
        "line_text": _normalize_text,
        "header_text": _normalize_text,
    }.items():
        first_values = _first_nonempty_group_values(
            work,
            group_cols,
            column,
            normalizer=normalizer,
        )
        doc_work = doc_work.join(first_values.rename(column), on=group_cols)
        doc_work[column] = doc_work[column].fillna("")
    doc_work["abs_amt"] = doc_work["net"].abs().round(2)
    doc_work["created_by_norm"] = doc_work["created_by"].map(_normalize_value)
    doc_work["reference_norm"] = doc_work["reference"].map(_normalize_value)
    doc_work["document_type_norm"] = doc_work["document_type"].map(_normalize_value)
    doc_work["line_text_norm"] = doc_work["line_text"].map(_normalize_text)
    doc_work["header_text_norm"] = doc_work["header_text"].map(_normalize_text)
    doc_work["line_keyword"] = doc_work["line_text"].fillna("").astype(str).str.contains(
        _REVERSAL_PATTERN,
        na=False,
    )

    nonzero_mask = doc_work["net"].ne(0.0)
    if _EXCLUDE_ACCOUNTS:
        nonzero_mask &= ~doc_work["gl_account"].apply(
            lambda value: any(value.startswith(prefix) for prefix in _EXCLUDE_ACCOUNTS)
        )
    doc_work = doc_work.loc[nonzero_mask].dropna(subset=["posting_date"])
    if len(doc_work) < 2:
        return pd.Series(False, index=df.index)

    group_sizes = doc_work.groupby(["gl_account", "abs_amt"]).size()
    large_groups = int((group_sizes > _LARGE_GROUP_WARN).sum())
    if large_groups:
        logger.warning(
            "L2-05 S1 found %d large groups above %d rows",
            large_groups,
            _LARGE_GROUP_WARN,
        )
    positives = doc_work.loc[doc_work["net"] > 0]
    negatives = doc_work.loc[doc_work["net"] < 0]
    if positives.empty or negatives.empty:
        return pd.Series(False, index=df.index)

    candidate_pairs = positives.merge(
        negatives,
        on=["gl_account", "abs_amt"],
        suffixes=("_pos", "_neg"),
    )
    if candidate_pairs.empty:
        return pd.Series(False, index=df.index)

    day_gap = (
        candidate_pairs["posting_date_pos"] - candidate_pairs["posting_date_neg"]
    ).abs().dt.days
    context_score = (
        (
            candidate_pairs["reference_norm_pos"].ne("")
            & candidate_pairs["reference_norm_pos"].eq(candidate_pairs["reference_norm_neg"])
        ).astype(int) * 2
        + (
            candidate_pairs["created_by_norm_pos"].ne("")
            & candidate_pairs["created_by_norm_pos"].eq(candidate_pairs["created_by_norm_neg"])
        ).astype(int)
        + (
            candidate_pairs["document_type_norm_pos"].ne("")
            & candidate_pairs["document_type_norm_pos"].eq(
                candidate_pairs["document_type_norm_neg"],
            )
        ).astype(int)
        + (
            candidate_pairs["line_text_norm_pos"].ne("")
            & candidate_pairs["line_text_norm_pos"].eq(candidate_pairs["line_text_norm_neg"])
        ).astype(int)
        + (
            candidate_pairs["header_text_norm_pos"].ne("")
            & candidate_pairs["header_text_norm_pos"].eq(candidate_pairs["header_text_norm_neg"])
        ).astype(int)
        + (candidate_pairs["line_keyword_pos"] | candidate_pairs["line_keyword_neg"]).astype(int)
    )
    candidate_pairs = candidate_pairs.loc[
        candidate_pairs["document_id_pos"].lt(candidate_pairs["document_id_neg"])
        & day_gap.le(int(match_window_days))
        & context_score.ge(2)
    ]
    if candidate_pairs.empty:
        return pd.Series(False, index=df.index)

    matched_doc_ids: set[str] = set()
    for pair in candidate_pairs.itertuples(index=False):
        matched_doc_ids.add(str(pair.document_id_pos))
        matched_doc_ids.add(str(pair.document_id_neg))

    return pd.Series(df["document_id"].astype(str).isin(matched_doc_ids), index=df.index)


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
    work["document_id"] = df.get("document_id", pd.Series("", index=df.index)).astype(str)
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
    for column in ["reference", "document_type", "source", "line_text"]:
        work[column] = df[column] if column in df.columns else ""
    if _EXCLUDE_ACCOUNTS:
        work = work[
            ~work["gl_account"].apply(
                lambda value: any(value.startswith(prefix) for prefix in _EXCLUDE_ACCOUNTS)
            )
        ]
    work = work.dropna(subset=["posting_date"])
    if len(work) < 2:
        return pd.Series(False, index=df.index)

    group_cols = ["gl_account", "created_by", "document_id"]
    doc_work = (
        work.groupby(group_cols, sort=False)
        .agg(
            posting_date=("posting_date", "min"),
            net=("net", "sum"),
            gross=("gross", "sum"),
        )
        .reset_index()
    )
    for column, normalizer in {
        "reference": _normalize_value,
        "document_type": _normalize_value,
        "source": _normalize_value,
        "line_text": _normalize_text,
    }.items():
        first_values = _first_nonempty_group_values(
            work,
            group_cols,
            column,
            normalizer=normalizer,
        )
        doc_work = doc_work.join(first_values.rename(column), on=group_cols)
        doc_work[column] = doc_work[column].fillna("")
    doc_work["reference_norm"] = doc_work["reference"].map(_normalize_value)
    doc_work["document_type_norm"] = doc_work["document_type"].map(_normalize_value)
    doc_work["source_norm"] = doc_work["source"].map(_normalize_value)
    doc_work["line_text_norm"] = doc_work["line_text"].map(_normalize_text)
    doc_work["line_keyword"] = doc_work["line_text"].fillna("").astype(str).str.contains(
        _REVERSAL_PATTERN,
        na=False,
    )
    if len(doc_work) < 2:
        return pd.Series(False, index=df.index)

    matched_doc_ids: set[str] = set()
    delta = pd.Timedelta(days=rolling_window_days)

    for (_, _), group in doc_work.groupby(["gl_account", "created_by"], sort=False):
        group = group.sort_values("posting_date")
        if len(group) < 2:
            continue
        if not ((group["net"] > 0).any() and (group["net"] < 0).any()):
            continue
        if _group_context_upper_bound(group) < 2:
            continue

        dates = group["posting_date"].tolist()
        net_values = group["net"].to_numpy(dtype="float64")
        gross_values = group["gross"].to_numpy(dtype="float64")
        net_prefix = np.concatenate(([0.0], np.cumsum(net_values)))
        gross_prefix = np.concatenate(([0.0], np.cumsum(gross_values)))
        left = 0
        for right in range(len(group)):
            while dates[right] - dates[left] > delta:
                left += 1
            if (right - left + 1) < 2:
                continue
            window_net = float(net_prefix[right + 1] - net_prefix[left])
            window_gross = float(gross_prefix[right + 1] - gross_prefix[left])
            if window_gross <= 0:
                continue
            if (
                abs(window_net) < zero_threshold
                and abs(window_net) / window_gross < _NET_GROSS_RATIO_THRESHOLD
            ):
                window = group.iloc[left : right + 1]
                if window["document_id"].nunique() < 2:
                    continue
                if _window_context_score_prepared(window) < 2:
                    continue
                matched_doc_ids.update(window["document_id"].astype(str).tolist())

    if not matched_doc_ids:
        return pd.Series(False, index=df.index)
    return pd.Series(df["document_id"].astype(str).isin(matched_doc_ids), index=df.index)


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

    grouped = work.groupby("document_id", sort=False)
    doc_net = grouped["net"].transform("sum")
    doc_size = grouped["net"].transform("size")
    match = (
        doc_size.ge(2)
        & doc_net.abs().gt(tolerance)
        & ((work["abs_line_amt"] * 2.0) - doc_net.abs()).abs().le(tolerance)
    )
    doc_hit = match.groupby(work["document_id"], sort=False).transform("any")
    return pd.Series(doc_hit.to_numpy(dtype=bool), index=df.index)


def _s3_reversal_type(df: pd.DataFrame) -> pd.Series:
    """Return a positive or negative adjustment based on entry type."""

    if "source" not in df.columns or "posting_date" not in df.columns:
        return pd.Series(0.0, index=df.index)

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    source = df["source"].astype(str).str.lower()
    is_auto = source.isin(["auto", "automated", "recurring", "batch", "interface", "system"])
    is_manual = source.isin(["manual", "adjustment"])
    is_month_start = posting_date.dt.day <= 5
    is_january = posting_date.dt.month == 1

    result = pd.Series(0.0, index=df.index)
    result[is_auto & is_month_start & is_january] = -_W_S3
    result[is_auto & is_month_start & ~is_january] = -(_W_S3 * 0.67)
    result[is_manual] = _W_S3
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


def _build_row_annotations(
    flagged: pd.Series,
    *,
    s0: pd.Series,
    s1: pd.Series,
    s2: pd.Series,
    s2b: pd.Series,
    s4: pd.Series,
) -> dict[int, dict[str, object]]:
    """Build row-level interpretation metadata for surfaced L2-05 hits."""

    annotations: dict[int, dict[str, object]] = {}
    signal_series = {
        "S0": s0,
        "S1": s1,
        "S2": s2,
        "S2b": s2b,
    }
    signal_text = {
        "S0": "ERP reversal reference fields link the original and reversal entries",
        "S2b": "a single swapped line can explain the document imbalance",
        "S1": "an opposite-signed document pair matched on account and amount",
        "S2": "multiple documents net to near zero in a short rolling window",
    }

    for index in flagged[flagged].index.tolist():
        trigger_signals = [
            signal for signal in _SIGNAL_PRIORITY if bool(signal_series[signal].loc[index])
        ]
        if not trigger_signals:
            continue

        high_confidence = "S0" in trigger_signals or "S2b" in trigger_signals
        interpretation_code = (
            "high_confidence_reversal"
            if high_confidence
            else "candidate_reversal_clearing_reclass"
        )
        interpretation_label = (
            "High-confidence reversal"
            if high_confidence
            else "Candidate reversal / clearing / reclass"
        )
        primary_signal = next(
            (signal for signal in _SIGNAL_PRIORITY if signal in trigger_signals),
            trigger_signals[0],
        )
        reason_parts = [signal_text[primary_signal]]
        if bool(s4.loc[index]):
            reason_parts.append("line text includes a reversal keyword")

        annotations[index] = {
            "interpretation_code": interpretation_code,
            "interpretation_label": interpretation_label,
            "primary_signal": primary_signal,
            "trigger_signals": trigger_signals,
            "reason_text": "; ".join(reason_parts),
        }

    return annotations


def _source_norm_series(df: pd.DataFrame) -> pd.Series:
    if "source" not in df.columns:
        return pd.Series("", index=df.index)
    return df["source"].fillna("").astype(str).str.strip().str.lower()


def _score_reversal_candidates(
    df: pd.DataFrame,
    flagged: pd.Series,
    score_basis: pd.Series,
    *,
    s0: pd.Series,
    s2b: pd.Series,
    s4: pd.Series,
) -> pd.Series:
    """Separate L2-05 population capture from risk priority."""

    score_series = score_basis.where(flagged, 0.0).fillna(0.0).astype(float)
    high_confidence = flagged & (s0.astype(bool) | s2b.astype(bool))
    candidate = flagged & ~high_confidence
    source = _source_norm_series(df)
    routine = source.isin(["auto", "automated", "recurring", "batch", "interface", "system"])
    manual = source.isin(["manual", "adjustment"])
    keyword = s4.astype(bool)

    routine_population = candidate & routine & ~keyword
    routine_review = candidate & routine & keyword
    manual_plain_review = candidate & manual & ~keyword
    manual_keyword_review = candidate & manual & keyword
    other_candidate = candidate & ~(routine | manual)

    score_series.loc[routine_population] = 0.0
    score_series.loc[routine_review] = score_series.loc[routine_review].clip(upper=0.20)
    score_series.loc[manual_plain_review] = score_series.loc[manual_plain_review].clip(upper=0.35)
    score_series.loc[manual_keyword_review] = score_series.loc[manual_keyword_review].clip(
        lower=0.45,
        upper=0.60,
    )
    score_series.loc[other_candidate] = score_series.loc[other_candidate].clip(upper=0.30)
    return score_series.where(flagged, 0.0)


def _l205_queue_label(score: float, interpretation_code: str) -> str:
    if interpretation_code == "high_confidence_reversal":
        return "high_confidence_reversal"
    if score <= 0:
        return "normal_clearing_reclass_population"
    if score < 0.45:
        return "low_reversal_review"
    return "reversal_review"


def c11_reversal_entry(
    df: pd.DataFrame,
    *,
    match_window_days: int = 1,
    rolling_window_days: int = 7,
    zero_threshold: float = 1000.0,
    score_threshold: float = 0.3,
) -> pd.Series:
    """Composite reversal-pattern detector used for rule L2-05."""

    missing = [column for column in _CORE_COLUMNS if column not in df.columns]
    if missing or len(df) < 2:
        if missing:
            logger.warning("L2-05 missing required columns: %s", missing)
        return pd.Series(False, index=df.index)

    start = time.perf_counter()
    s0 = _s0_structural_reversal_reference(df)

    s1 = _s1_one_to_one_match(df, match_window_days=match_window_days)
    logger.warning(
        "[TIMING] layer_c.L2-05.S1: %.2fs (rows=%d)",
        time.perf_counter() - start,
        len(df),
    )

    start = time.perf_counter()
    s2 = _s2_rolling_zero_out(
        df,
        rolling_window_days=rolling_window_days,
        zero_threshold=zero_threshold,
    )
    logger.warning(
        "[TIMING] layer_c.L2-05.S2: %.2fs (rows=%d)",
        time.perf_counter() - start,
        len(df),
    )

    start = time.perf_counter()
    s2b = _s2b_line_swap_signature(df)
    logger.warning(
        "[TIMING] layer_c.L2-05.S2b: %.2fs (rows=%d)",
        time.perf_counter() - start,
        len(df),
    )

    start = time.perf_counter()
    s3 = _s3_reversal_type(df)
    logger.warning(
        "[TIMING] layer_c.L2-05.S3: %.2fs (rows=%d)",
        time.perf_counter() - start,
        len(df),
    )

    start = time.perf_counter()
    s4 = _s4_keyword_match(df)
    logger.warning(
        "[TIMING] layer_c.L2-05.S4: %.2fs (rows=%d)",
        time.perf_counter() - start,
        len(df),
    )

    start = time.perf_counter()
    s5 = _s5_period_end_boost(df)
    logger.warning(
        "[TIMING] layer_c.L2-05.S5: %.2fs (rows=%d)",
        time.perf_counter() - start,
        len(df),
    )

    base_score = (
        s0.astype(float) * _W_S0
        + s1.astype(float) * _W_S1
        + s2.astype(float) * _W_S2
        + s2b.astype(float) * _W_S2B
        + s4.astype(float) * _W_S4
    )
    evidence_score = (base_score * s5).clip(0.0, 1.0)
    adjusted = (base_score + s3) * s5
    final_score = adjusted.clip(0.0, 1.0)

    has_reversal_pattern = s0.astype(bool) | s1.astype(bool) | s2.astype(bool) | s2b.astype(bool)
    flagged = (
        (final_score >= score_threshold) | (evidence_score >= score_threshold)
    ) & has_reversal_pattern
    score_basis = pd.concat(
        [final_score.rename("final_score"), evidence_score.rename("evidence_score")],
        axis=1,
    ).max(axis=1)
    score_series = _score_reversal_candidates(
        df,
        flagged,
        score_basis,
        s0=s0,
        s2b=s2b,
        s4=s4,
    )
    high_confidence = flagged & (s0 | s2b)
    candidate = flagged & ~high_confidence
    flagged.attrs["breakdown"] = {
        "high_confidence_count": int(high_confidence.sum()),
        "candidate_count": int(candidate.sum()),
        "scored_count": int(score_series.gt(0).sum()),
        "zero_score_count": int((flagged & score_series.eq(0)).sum()),
        "queue_counts": {
            "high_confidence_reversal": int(high_confidence.sum()),
            "reversal_review": int((candidate & score_series.ge(0.45)).sum()),
            "low_reversal_review": int(
                (candidate & score_series.gt(0) & score_series.lt(0.45)).sum(),
            ),
            "normal_clearing_reclass_population": int((candidate & score_series.eq(0)).sum()),
        },
    }
    flagged.attrs["score_series"] = score_series
    row_annotations = _build_row_annotations(
        flagged,
        s0=s0,
        s1=s1,
        s2=s2,
        s2b=s2b,
        s4=s4,
    )
    for index, annotation in row_annotations.items():
        score = float(score_series.loc[index])
        interpretation_code = str(annotation.get("interpretation_code", ""))
        annotation["score"] = round(score, 4)
        annotation["queue_label"] = _l205_queue_label(score, interpretation_code)
    flagged.attrs["row_annotations"] = row_annotations
    return flagged
