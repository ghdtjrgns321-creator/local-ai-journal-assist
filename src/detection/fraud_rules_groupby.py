"""Groupby-based fraud rules for L2-02, L2-03, and L2-04."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from config.settings import AuditSettings, get_audit_rules

L202_BINARY_FLAG_SCORE = 1.0


def _compute_base_amount(df: pd.DataFrame) -> pd.Series:
    """Use the larger of debit/credit as the representative amount."""

    return df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)


def _resolve_b04_partner_key(df: pd.DataFrame) -> pd.Series | None:
    """Resolve the best available counterparty key for L2-02 coverage checks."""

    candidate_columns = [
        "auxiliary_account_number",
        "trading_partner",
        "auxiliary_account_label",
        "vendor_name",
        "customer_name",
        "counterparty_code",
        "counterparty_name",
    ]

    resolved: pd.Series | None = None
    for column in candidate_columns:
        if column not in df.columns:
            continue
        current = df[column].copy()
        if resolved is None:
            resolved = current
            continue
        empty_mask = resolved.isna()
        if resolved.dtype == "O":
            empty_mask = empty_mask | resolved.astype(str).str.strip().eq("")
        resolved.loc[empty_mask] = current.loc[empty_mask]

    return resolved


def _non_empty_mask(series: pd.Series) -> pd.Series:
    """Return a mask for populated values."""

    if series.dtype == "O":
        return series.notna() & series.astype(str).str.strip().ne("")
    return series.notna()


def _is_recurring_payment_series(group: pd.DataFrame) -> pd.Series:
    """Identify stable monthly recurring payments to suppress fallback noise."""

    if len(group) < 3:
        return pd.Series(False, index=group.index)

    ordered = group.sort_values("posting_date")
    day_gaps = ordered["posting_date"].diff().dt.days.dropna()
    if len(day_gaps) < 2:
        return pd.Series(False, index=group.index)

    if day_gaps.between(25, 35).all() and (day_gaps.max() - day_gaps.min()) <= 5:
        return pd.Series(True, index=group.index)

    return pd.Series(False, index=group.index)


def _l202_recurring_profile(
    group: pd.DataFrame,
    *,
    min_len: int,
    min_interval_days: int,
    max_interval_days: int,
    cv_threshold: float,
    require_reference_variation: bool = True,
) -> dict[str, float] | None:
    if len(group) < min_len:
        return None
    dates = pd.to_datetime(group["posting_date"], errors="coerce").dropna().sort_values()
    if len(dates) < min_len:
        return None
    intervals = dates.diff().dropna().dt.days.astype(float)
    intervals = intervals[intervals > 0]
    regular_intervals = intervals[
        (intervals >= float(min_interval_days)) & (intervals <= float(max_interval_days))
    ]
    if len(regular_intervals) < max(min_len - 2, 1):
        return None
    median = float(regular_intervals.median())
    if median <= 0:
        return None
    cv = float(regular_intervals.std(ddof=0) / median)
    if cv > cv_threshold:
        return None
    if require_reference_variation:
        refs = group.get("_reference_norm", pd.Series("", index=group.index)).astype(str)
        if refs.nunique(dropna=False) <= 1:
            return None
    return {"median_interval_days": median, "interval_cv": cv}


def _l202_is_manual_off_cycle(row: pd.Series, *, settings: AuditSettings) -> bool:
    source = _normalize_text(row.get("source", ""))
    allowed_sources = {
        _normalize_text(value)
        for value in settings.duplicate_recurring_near_extra_allowed_sources
        if _normalize_text(value)
    }
    suppressed_sources = {
        _normalize_text(value)
        for value in settings.duplicate_recurring_near_extra_suppressed_sources
        if _normalize_text(value)
    }
    if source in suppressed_sources:
        return False
    if allowed_sources and source not in allowed_sources:
        return False

    process = _normalize_text(row.get("business_process", ""))
    suppressed_processes = {
        _normalize_text(value)
        for value in settings.duplicate_recurring_near_extra_suppressed_processes
        if _normalize_text(value)
    }
    if process in suppressed_processes:
        return False
    context_text = " ".join(
        str(row.get(column, ""))
        for column in ("business_process", "line_text", "header_text", "source", "document_type")
    )
    normalized_context = _normalize_text(context_text)
    suppressed_tokens = {
        _normalize_text(value)
        for value in settings.duplicate_recurring_near_extra_suppressed_process_tokens
        if _normalize_text(value)
    }
    return not any(token in normalized_context for token in suppressed_tokens)


_RE_SPECIAL = re.compile(r"[^\w\s]", re.UNICODE)
_RE_ALNUM = re.compile(r"[^A-Za-z0-9]", re.UNICODE)
_REFERENCE_TOKEN_RE = re.compile(
    r"\b(?P<prefix>PAY|PO|INV|VI)[\s:_/-]*"
    r"(?:(?:PAY|PO|INV|VI)[\s:_/-]*)?"
    r"(?P<company>[A-Z0-9]{4})[\s:_/-]+"
    r"(?:(?P<year>20\d{2})[\s:_/-]+)?"
    r"(?P<number>\d{1,12})"
    r"(?:[\s:_/-]*R)?\b",
    re.IGNORECASE,
)


def _normalize_text(value: object) -> str:
    """Normalize free-text fields for conservative fuzzy matching."""

    normalized = _RE_SPECIAL.sub("", str(value).lower())
    return " ".join(normalized.split())


def _normalize_reference(value: object) -> str:
    """Normalize payment references across small punctuation/spacing changes."""

    normalized = str(value or "").upper().strip()
    canonical = _canonical_payment_reference(normalized)
    if canonical:
        return canonical
    normalized = re.sub(r"[-_\s]+R$", "", normalized)
    return _RE_ALNUM.sub("", normalized)


def _canonical_company_token(value: str) -> str:
    """Canonicalize small OCR/typing variants in synthetic payment references."""

    token = value.upper().strip()
    if len(token) != 4:
        return token
    if token[0] in {"C", "X"}:
        token = "C" + token[1:]
    replacements = str.maketrans({"O": "0", "Q": "0", "Z": "2", "I": "1", "L": "1"})
    return token[0] + token[1:].translate(replacements)


def _canonical_payment_reference(value: object) -> str:
    """Return a stable key for PAY/PO/INV-style references when recognizable."""

    text = str(value or "").upper().strip()
    for match in _REFERENCE_TOKEN_RE.finditer(text):
        company = _canonical_company_token(match.group("company"))
        if not re.fullmatch(r"C\d{3}", company):
            continue
        number = str(int(match.group("number")))
        year = match.group("year") or ""
        return f"{match.group('prefix').upper()}{company}{year}{number}"
    return ""


def _normalize_duplicate_text(value: object) -> str:
    """Normalize line text for duplicate-entry document signature matching."""

    text = _normalize_text(value)
    for token in ("재전기", "재기표", "duplicate", "dup"):
        text = text.replace(token, " ")
    return " ".join(text.split())


def _trailing_reference_number(value: object) -> int | None:
    matches = re.findall(r"(\d+)", str(value or ""))
    if not matches:
        return None
    return int(matches[-1])


def _documents_differ(group: pd.DataFrame) -> pd.Series:
    """Return rows that belong to a group with at least two document IDs."""

    if "_document_id" not in group.columns:
        return pd.Series(True, index=group.index)
    return pd.Series(group["_document_id"].nunique() >= 2, index=group.index)


def _is_amount_close(left: float, right: float, tolerance: float) -> bool:
    """Check whether two amounts are within the configured relative tolerance."""

    max_amt = max(abs(left), abs(right))
    if max_amt == 0:
        return False
    return abs(left - right) / max_amt <= tolerance


def _prepare_duplicate_entry_work(df: pd.DataFrame) -> pd.DataFrame:
    """Build a normalized working frame for L2-03 matching."""

    work = df[["gl_account", "posting_date"]].copy()
    work["_posting_ts"] = pd.to_datetime(df["posting_date"], errors="coerce")
    work["_base_amt"] = _compute_base_amount(df)
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    work["_entry_side"] = np.where(debit >= credit, "D", "C")

    if "company_code" in df.columns:
        work["company_code"] = df["company_code"].fillna("").astype(str).str.strip()

    if "document_id" in df.columns:
        work["_document_id"] = df["document_id"].fillna("").astype(str).str.strip()

    if "reference" in df.columns:
        work["_reference"] = df["reference"].fillna("").astype(str).str.strip()

    partner_key = _resolve_b04_partner_key(df)
    if partner_key is not None:
        work["_partner_key"] = partner_key.fillna("").astype(str).str.strip()

    if "line_text" in df.columns:
        work["_line_text"] = df["line_text"].fillna("").map(_normalize_duplicate_text)

    return work


def _flag_exact_duplicate_entries(work: pd.DataFrame) -> pd.Series:
    """Flag full row clones across different documents."""

    result = pd.Series(0.0, index=work.index)
    exact_cols = ["gl_account", "_base_amt", "_posting_ts", "_entry_side"]
    for optional_col in ("_partner_key", "_line_text"):
        if optional_col in work.columns:
            exact_cols.append(optional_col)

    populated_mask = (
        work["_document_id"].ne("")
        & work["_posting_ts"].notna()
        & work["_base_amt"].gt(0)
    )
    for optional_col in ("_partner_key", "_line_text"):
        if optional_col in work.columns:
            populated_mask &= work[optional_col].ne("")

    target = work.loc[
        populated_mask,
        [*exact_cols, "_document_id"],
    ]
    if target.empty:
        return result

    group_doc_counts = target.groupby(
        exact_cols,
        sort=False,
    )["_document_id"].transform("nunique")
    result.loc[target.index[group_doc_counts >= 2]] = 1.0
    return result


def _flag_reference_duplicate_entries(
    work: pd.DataFrame,
    *,
    amount_tolerance: float,
    reference_max_frequency_ratio: float,
    reference_min_unique_ratio: float,
    reference_nonunique_min_count: int,
) -> pd.Series:
    """Flag same-reference re-postings across different documents."""

    result = pd.Series(0.0, index=work.index)
    required = {"_reference", "_document_id", "_entry_side"}
    if not required.issubset(work.columns):
        return result

    target = work.loc[
        work["_reference"].ne("")
        & work["_document_id"].ne("")
        & work["_base_amt"].gt(0)
    ].copy()
    if target.empty:
        return result

    reference_counts = target["_reference"].value_counts(dropna=False)
    min_count = max(int(reference_nonunique_min_count), 2)
    max_ratio = max(float(reference_max_frequency_ratio), 0.0)
    min_unique_ratio = max(float(reference_min_unique_ratio), 0.0)
    unique_ratio = float(target["_reference"].nunique(dropna=False) / len(target))
    if len(target) >= min_count and unique_ratio < min_unique_ratio:
        return result
    overused_references = reference_counts[
        (reference_counts >= min_count) & ((reference_counts / len(target)) > max_ratio)
    ].index
    if len(overused_references) > 0:
        target = target.loc[~target["_reference"].isin(overused_references)]
    if target.empty:
        return result

    group_cols = ["_reference", "gl_account", "_entry_side"]
    group_sizes = target.groupby(group_cols, sort=False)["_document_id"].transform("size")
    target = target.loc[group_sizes >= 2]
    if target.empty:
        return result

    for _, group in target.groupby(group_cols, group_keys=False):
        if len(group) < 2 or group["_document_id"].nunique() < 2:
            continue
        ordered = group.sort_values("_posting_ts")
        amounts = ordered["_base_amt"]
        if not _is_amount_close(float(amounts.max()), float(amounts.min()), amount_tolerance):
            continue
        result.loc[group.index] = 1.0

    return result


def _flag_o2c_offset_duplicate_entries(work: pd.DataFrame, df: pd.DataFrame) -> pd.Series:
    """Capture routine O2C receipt/invoice offset duplicates as zero-score population."""

    result = pd.Series(0.0, index=work.index)
    required = {"_document_id", "_posting_ts", "_base_amt"}
    if not required.issubset(work.columns):
        return result
    if not {"business_process", "document_type"}.issubset(df.columns):
        return result

    source = pd.DataFrame(
        {
            "_document_id": work["_document_id"],
            "_posting_ts": work["_posting_ts"],
            "_base_amt": work["_base_amt"],
            "company_code": (
                df["company_code"].fillna("").astype(str).str.strip()
                if "company_code" in df.columns
                else pd.Series("", index=df.index)
            ),
            "business_process": df["business_process"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper(),
            "document_type": df["document_type"].fillna("").astype(str).str.strip().str.upper(),
            "reference": (
                df["reference"].fillna("").astype(str)
                if "reference" in df.columns
                else pd.Series("", index=df.index)
            ),
        },
        index=df.index,
    )
    target = source.loc[
        source["_document_id"].ne("")
        & source["_posting_ts"].notna()
        & source["_base_amt"].gt(0)
        & source["business_process"].eq("O2C")
        & source["document_type"].isin({"DR", "DZ"})
    ].copy()
    if target.empty:
        return result

    docs = target.groupby("_document_id", sort=False).agg(
        posting_date=("_posting_ts", "min"),
        amount=("_base_amt", "max"),
        company_code=("company_code", "first"),
        document_type=("document_type", "first"),
        reference=("reference", "first"),
        row_indices=("_document_id", lambda s: s.index.tolist()),
    )
    docs = docs.loc[docs["amount"].gt(0)]
    if docs.empty:
        return result

    for _, group in docs.groupby(["company_code", "amount"], dropna=False, sort=False):
        if group["document_type"].nunique() < 2 or len(group) < 2:
            continue
        ordered = group.sort_values("posting_date")
        records = list(ordered.itertuples())
        for left_pos, left in enumerate(records):
            for right in records[left_pos + 1 :]:
                if right.posting_date - left.posting_date > pd.Timedelta(days=1):
                    break
                if left.document_type == right.document_type:
                    continue
                left_ref_num = _trailing_reference_number(left.reference)
                right_ref_num = _trailing_reference_number(right.reference)
                if left_ref_num is None or right_ref_num is None:
                    continue
                if abs(left_ref_num - right_ref_num) > 1:
                    continue
                indices = list(left.row_indices) + list(right.row_indices)
                result.loc[indices] = result.loc[indices].clip(lower=0.01)

    return result


def _l203_source_series(df: pd.DataFrame) -> pd.Series:
    """Return normalized source values for L2-03 score separation."""

    if "source" not in df.columns:
        return pd.Series("", index=df.index)
    return df["source"].where(df["source"].notna(), "").astype(str).str.strip().str.lower()


def _score_l203_duplicate_entries(
    df: pd.DataFrame,
    result: pd.Series,
    confidence: pd.Series,
    score_frame: pd.DataFrame,
) -> pd.Series:
    """Return binary L2-03 scores for explicit re-posting evidence."""

    return pd.Series(1.0, index=df.index).where(result, 0.0)


def _l203_queue_label(score: float, source: str) -> str:
    if score <= 0:
        return "normal_duplicate_population"
    return "duplicate_review"


def b04_duplicate_payment(
    df: pd.DataFrame,
    window_days: int = 90,
    reference_amount_tolerance: float = 0.02,
    reference_amount_cap: float = 100_000.0,
) -> pd.Series:
    """L2-02 duplicate payment rule for P2P disbursements.

    Phase 1 logic:
    - Scope to P2P transactions to avoid recurring O2C activity.
    - Strong signal: same partner + same reference + near-same amount across
      different document IDs. The default 2% amount tolerance catches small
      fee, rounding, or FX differences, capped at KRW 100,000 by default.
    - Fallback signal: same partner + near-same amount within the time window
      when reference is missing, while suppressing stable monthly recurring
      payments.
    """

    required = ["posting_date", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    partner_key = _resolve_b04_partner_key(df)
    if partner_key is None:
        return result
    settings = AuditSettings()

    if "business_process" in df.columns:
        p2p_mask = df["business_process"] == "P2P"
    else:
        p2p_mask = pd.Series(True, index=df.index)

    if "document_type" in df.columns:
        p2p_mask = p2p_mask & df["document_type"].isin({"KZ", "KR"})

    target = df[p2p_mask].copy()
    if target.empty:
        return result

    target_partner = partner_key.loc[target.index]
    populated_partner = _non_empty_mask(target_partner)
    target = target.loc[populated_partner].copy()
    if target.empty:
        return result

    target["_partner_key"] = target_partner.loc[target.index].astype(str).str.strip()
    target["_base_amt"] = _compute_base_amount(target)
    target["_debit_abs"] = pd.to_numeric(target["debit_amount"], errors="coerce").fillna(0).abs()
    target["_credit_abs"] = pd.to_numeric(target["credit_amount"], errors="coerce").fillna(0).abs()
    target["_document_id"] = (
        target["document_id"].fillna("").astype(str).str.strip()
        if "document_id" in target.columns
        else target.index.astype(str)
    )
    target["_reference"] = (
        target["reference"].fillna("").astype(str).str.strip()
        if "reference" in target.columns
        else ""
    )
    text_reference_parts = pd.Series("", index=target.index)
    for text_col in ("line_text", "header_text"):
        if text_col in target.columns:
            text_reference_parts = text_reference_parts.astype(str).str.cat(
                target[text_col].fillna("").astype(str),
                sep=" ",
            )
    target["_reference_text"] = text_reference_parts.map(_canonical_payment_reference)

    agg_spec: dict[str, str] = {
        "_partner_key": "first",
        "posting_date": "min",
        "_debit_abs": "sum",
        "_credit_abs": "sum",
        "_reference": "first",
        "_reference_text": "first",
    }
    if "company_code" in target.columns:
        agg_spec["company_code"] = "first"
    for context_col in ("source", "business_process", "line_text", "header_text"):
        if context_col in target.columns:
            agg_spec[context_col] = "first"

    doc_target = (
        target.groupby("_document_id", as_index=False)
        .agg(agg_spec)
        .rename(columns={"_document_id": "document_id"})
    )
    if doc_target.empty:
        return result

    doc_target["posting_date"] = pd.to_datetime(doc_target["posting_date"], errors="coerce")
    doc_target["_base_amt"] = doc_target[["_debit_abs", "_credit_abs"]].max(axis=1)
    doc_target["_reference_field_norm"] = doc_target["_reference"].map(_canonical_payment_reference)
    doc_target["_reference_norm"] = doc_target["_reference_field_norm"].where(
        doc_target["_reference_field_norm"].ne(""),
        doc_target["_reference_text"],
    )
    doc_target["_reference_norm"] = doc_target["_reference_norm"].where(
        doc_target["_reference_norm"].ne(""),
        doc_target["_reference"].map(_normalize_reference),
    )
    window = pd.Timedelta(days=window_days)
    flagged_doc_ids: set[str] = set()
    doc_annotations: dict[str, dict[str, object]] = {}
    suppressed_doc_ids: set[str] = set()
    ambiguous_fallback_dropped = 0
    near_extra_docs = 0
    near_extra_context_suppressed_docs = 0

    ref_cols = ["_partner_key", "_reference_norm"]
    if "company_code" in doc_target.columns:
        ref_cols.insert(0, "company_code")

    ref_target = doc_target.loc[doc_target["_reference_norm"].ne("")]
    for _, group in ref_target.groupby(ref_cols, group_keys=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date")
        seen: list[dict[str, object]] = []
        for _, row in ordered.iterrows():
            if pd.isna(row["posting_date"]):
                continue
            amount = float(row["_base_amt"])
            ratio_tolerance = abs(amount) * reference_amount_tolerance
            tolerance = max(min(ratio_tolerance, reference_amount_cap), 1.0)
            for prev in reversed(seen):
                day_gap = row["posting_date"] - prev["posting_date"]
                if abs(amount - float(prev["amount"])) <= tolerance:
                    doc_id = str(row["document_id"])
                    flagged_doc_ids.add(doc_id)
                    doc_annotations[doc_id] = {
                        "reason_code": "reference_match",
                        "confidence": L202_BINARY_FLAG_SCORE,
                        "confidence_band": "binary",
                        "matched_document_id": str(prev["document_id"]),
                        "partner_key": str(row["_partner_key"]),
                        "reference_norm": str(row["_reference_norm"]),
                        "amount": amount,
                        "matched_amount": float(prev["amount"]),
                        "day_gap": int(day_gap.days),
                    }
                    break
            seen.append(
                {
                    "document_id": str(row["document_id"]),
                    "posting_date": row["posting_date"],
                    "amount": amount,
                }
            )

    amount_cols = ["_partner_key"]
    if "company_code" in doc_target.columns:
        amount_cols.insert(0, "company_code")
    amount_target = doc_target.loc[doc_target["_base_amt"].gt(0)].copy()
    recurring_suppressed_doc_ids: set[str] = set()
    recurring_cols = [*amount_cols, "_base_amt"]
    for _, group in amount_target.groupby(recurring_cols, group_keys=False):
        recurring_profile = _l202_recurring_profile(
            group.sort_values("posting_date"),
            min_len=max(int(settings.duplicate_recurring_min_series_length), 3),
            min_interval_days=max(int(settings.duplicate_recurring_min_interval_days), 1),
            max_interval_days=max(
                int(settings.duplicate_recurring_max_interval_days),
                int(settings.duplicate_recurring_min_interval_days),
            ),
            cv_threshold=max(float(settings.duplicate_recurring_interval_cv_threshold), 0.0),
            require_reference_variation=False,
        )
        if recurring_profile is not None:
            recurring_suppressed_doc_ids.update(group["document_id"].astype(str))

    fallback_rank = {
        "mixed_reference_fallback": 0,
        "amount_partner_fallback": 1,
        "blank_reference_fallback": 2,
    }
    def _fallback_reason(
        prev_ref: str,
        row_ref: str,
        amount: float,
        prev_amount: float,
        tolerance: float,
    ) -> str | None:
        if prev_ref and not row_ref and abs(amount - prev_amount) <= tolerance:
            return "mixed_reference_fallback"
        if not prev_ref and not row_ref:
            if abs(amount - prev_amount) <= tolerance:
                return "blank_reference_fallback"
            return None
        if prev_ref != row_ref and abs(amount - prev_amount) <= tolerance:
            return "amount_partner_fallback"
        return None

    for _, group in amount_target.groupby(amount_cols, group_keys=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date")
        seen: list[dict[str, object]] = []
        for _, row in ordered.iterrows():
            if pd.isna(row["posting_date"]):
                continue
            doc_id = str(row["document_id"])
            amount = float(row["_base_amt"])
            row_ref = str(row["_reference_norm"])
            if doc_id in doc_annotations:
                seen.append(
                    {
                        "document_id": doc_id,
                        "posting_date": row["posting_date"],
                        "amount": amount,
                        "reference_norm": row_ref,
                    }
                )
                continue
            ratio_tolerance = abs(amount) * reference_amount_tolerance
            tolerance = max(min(ratio_tolerance, reference_amount_cap), 1.0)
            best_match: dict[str, object] | None = None
            for prev in reversed(seen):
                day_gap = row["posting_date"] - prev["posting_date"]
                prev_ref = str(prev["reference_norm"])
                if row_ref and prev_ref and row_ref == prev_ref:
                    continue
                reason_code = _fallback_reason(
                    prev_ref,
                    row_ref,
                    amount,
                    float(prev["amount"]),
                    tolerance,
                )
                if reason_code is None:
                    continue
                if reason_code in {
                    "amount_partner_fallback",
                    "blank_reference_fallback",
                } and day_gap > window:
                    continue
                if doc_id in recurring_suppressed_doc_ids:
                    break
                candidate = {
                    "reason_code": reason_code,
                    "matched_document_id": str(prev["document_id"]),
                    "matched_amount": float(prev["amount"]),
                    "matched_reference_norm": prev_ref,
                    "day_gap": int(day_gap.days),
                }
                if best_match is None or fallback_rank[reason_code] < fallback_rank[
                    str(best_match["reason_code"])
                ]:
                    best_match = candidate
                    if fallback_rank[reason_code] == 0:
                        break
            if doc_id in recurring_suppressed_doc_ids:
                seen.append(
                    {
                        "document_id": doc_id,
                        "posting_date": row["posting_date"],
                        "amount": amount,
                        "reference_norm": row_ref,
                    }
                )
                continue
            if best_match is not None:
                reason_code = str(best_match["reason_code"])
                flagged_doc_ids.add(doc_id)
                doc_annotations[doc_id] = {
                    "reason_code": reason_code,
                    "confidence": L202_BINARY_FLAG_SCORE,
                    "confidence_band": "binary",
                    "matched_document_id": str(best_match["matched_document_id"]),
                    "partner_key": str(row["_partner_key"]),
                    "reference_norm": row_ref,
                    "matched_reference_norm": str(best_match["matched_reference_norm"]),
                    "amount": amount,
                    "matched_amount": float(best_match["matched_amount"]),
                    "day_gap": int(best_match["day_gap"]),
                }
            seen.append(
                {
                    "document_id": doc_id,
                    "posting_date": row["posting_date"],
                    "amount": amount,
                    "reference_norm": row_ref,
                }
            )

    for _, group in amount_target.groupby(amount_cols, group_keys=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date")
        recurring_profile = _l202_recurring_profile(
            ordered,
            min_len=max(int(settings.duplicate_recurring_min_series_length), 3),
            min_interval_days=max(int(settings.duplicate_recurring_min_interval_days), 1),
            max_interval_days=max(
                int(settings.duplicate_recurring_max_interval_days),
                int(settings.duplicate_recurring_min_interval_days),
            ),
            cv_threshold=max(float(settings.duplicate_recurring_interval_cv_threshold), 0.0),
        )
        seen: list[dict[str, object]] = []
        for _, row in ordered.iterrows():
            if pd.isna(row["posting_date"]):
                continue
            amount = float(row["_base_amt"])
            ratio_tolerance = abs(amount) * reference_amount_tolerance
            tolerance = max(min(ratio_tolerance, reference_amount_cap), 1.0)
            row_ref = str(row["_reference_norm"])
            for prev in reversed(seen):
                day_gap = row["posting_date"] - prev["posting_date"]
                if day_gap > window:
                    continue
                if abs(amount - float(prev["amount"])) > tolerance:
                    continue
                prev_ref = str(prev["reference_norm"])
                if row_ref and prev_ref and row_ref == prev_ref:
                    continue
                doc_id = str(row["document_id"])
                if doc_id in suppressed_doc_ids:
                    continue
                if doc_id in doc_annotations:
                    break
                keep_near_extra = False
                if recurring_profile is not None:
                    near_threshold = max(
                        1.0,
                        float(recurring_profile["median_interval_days"])
                        * max(float(settings.duplicate_recurring_near_extra_ratio), 0.0),
                    )
                    if int(day_gap.days) <= near_threshold:
                        if _l202_is_manual_off_cycle(row, settings=settings):
                            keep_near_extra = True
                        else:
                            near_extra_context_suppressed_docs += 1
                            break
                    else:
                        suppressed_doc_ids.add(doc_id)
                        break
                if not keep_near_extra:
                    ambiguous_fallback_dropped += 1
                    break
                flagged_doc_ids.add(doc_id)
                doc_annotations[doc_id] = {
                    "reason_code": "near_extra",
                    "confidence": L202_BINARY_FLAG_SCORE,
                    "confidence_band": "binary",
                    "matched_document_id": str(prev["document_id"]),
                    "partner_key": str(row["_partner_key"]),
                    "reference_norm": row_ref,
                    "matched_reference_norm": prev_ref,
                    "amount": amount,
                    "matched_amount": float(prev["amount"]),
                    "day_gap": int(day_gap.days),
                    "recurring_series_median_interval_days": float(
                        recurring_profile["median_interval_days"]
                    ),
                }
                near_extra_docs += 1
                break
            seen.append(
                {
                    "document_id": str(row["document_id"]),
                    "posting_date": row["posting_date"],
                    "amount": amount,
                    "reference_norm": row_ref,
                }
            )

    if flagged_doc_ids:
        result.loc[target.loc[target["_document_id"].isin(flagged_doc_ids)].index] = True

    score_series = pd.Series(0.0, index=df.index)
    row_annotations: dict[object, dict[str, object]] = {}
    reason_counts = {
        "reference_match": 0,
        "mixed_reference_fallback": 0,
        "blank_reference_fallback": 0,
        "amount_partner_fallback": 0,
        "near_extra": 0,
    }
    for doc_id, annotation in doc_annotations.items():
        doc_row_indices = target.loc[target["_document_id"].eq(doc_id)].index
        if doc_row_indices.empty:
            continue
        score = float(annotation["confidence"])
        score_series.loc[doc_row_indices] = score
        reason_code = str(annotation["reason_code"])
        reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1
        for idx in doc_row_indices:
            row_annotations[idx] = annotation.copy()

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "flagged_rows": int(result.sum()),
        "flagged_docs": int(len(flagged_doc_ids)),
        "reason_counts": {key: value for key, value in reason_counts.items() if value > 0},
        "reference_match_docs": int(reason_counts.get("reference_match", 0)),
        "mixed_reference_fallback_docs": int(reason_counts.get("mixed_reference_fallback", 0)),
        "blank_reference_fallback_docs": int(reason_counts.get("blank_reference_fallback", 0)),
        "amount_partner_fallback_docs": int(reason_counts.get("amount_partner_fallback", 0)),
        "near_extra_docs": int(reason_counts.get("near_extra", 0)),
        "ambiguous_fallback_dropped_docs": int(ambiguous_fallback_dropped),
        "near_extra_context_suppressed_docs": int(near_extra_context_suppressed_docs),
        "recurring_suppressed_docs": int(
            len(suppressed_doc_ids | recurring_suppressed_doc_ids)
        ),
        "partner_key_coverage_ratio": float(populated_partner.mean()),
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def b05_duplicate_entry(
    df: pd.DataFrame,
    *,
    amount_tolerance: float = 0.02,
    fuzzy_threshold: int = 80,
    window_days: int = 7,
    split_window_days: int = 3,
    max_group_size: int = 1000,
    reference_max_frequency_ratio: float = 0.10,
    reference_min_unique_ratio: float = 0.20,
    reference_nonunique_min_count: int = 10,
) -> pd.Series:
    """L2-03 duplicate entry with binary exact/reference re-posting signals."""

    required = ["document_id", "gl_account", "posting_date", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    work = _prepare_duplicate_entry_work(df)
    exact_scores = _flag_exact_duplicate_entries(work)
    reference_scores = _flag_reference_duplicate_entries(
        work,
        amount_tolerance=amount_tolerance,
        reference_max_frequency_ratio=reference_max_frequency_ratio,
        reference_min_unique_ratio=reference_min_unique_ratio,
        reference_nonunique_min_count=reference_nonunique_min_count,
    )
    score_frame = pd.DataFrame(
        {
            "exact_duplicate": exact_scores,
            "reference_duplicate": reference_scores,
        },
        index=df.index,
    )
    confidence = score_frame.max(axis=1).fillna(0.0)
    result = confidence > 0
    score_series = _score_l203_duplicate_entries(df, result, confidence, score_frame)

    reason_counts: dict[str, int] = {}
    confidence_band_counts = {"binary": 0}
    queue_counts: dict[str, int] = {}
    row_annotations: dict[object, dict[str, object]] = {}
    source_series = _l203_source_series(df)
    for idx in confidence[confidence > 0].index:
        row_scores = score_frame.loc[idx]
        matched = row_scores[row_scores > 0].sort_values(ascending=False)
        primary_reason = str(matched.index[0])
        primary_confidence = float(matched.iloc[0])
        score = float(score_series.loc[idx])
        source = source_series.loc[idx]
        queue_label = _l203_queue_label(score, source)
        confidence_band = "binary"
        reason_counts[primary_reason] = reason_counts.get(primary_reason, 0) + 1
        confidence_band_counts[confidence_band] += 1
        queue_counts[queue_label] = queue_counts.get(queue_label, 0) + 1
        row_annotations[idx] = {
            "reason_code": primary_reason,
            "matched_reason_codes": matched.index.tolist(),
            "raw_confidence": round(primary_confidence, 4),
            "confidence": round(score, 4),
            "confidence_band": confidence_band,
            "queue_label": queue_label,
        }

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "flagged_rows": int(result.sum()),
        "scored_rows": int(score_series.gt(0).sum()),
        "zero_score_rows": int((result & score_series.eq(0)).sum()),
        "reason_counts": reason_counts,
        "confidence_band_counts": confidence_band_counts,
        "queue_counts": queue_counts,
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def _get_expense_capitalization_config(
    audit_rules: dict | None = None,
) -> dict[str, tuple[str, ...]]:
    """Load editable account prefixes for L2-04."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    cfg = patterns.get("expense_capitalization", {})

    return {
        "asset_prefixes": tuple(
            str(v).strip() for v in cfg.get("asset_account_prefixes", ["12", "15"])
        ),
        "expense_prefixes": tuple(
            str(v).strip() for v in cfg.get("expense_account_prefixes", ["5", "6", "7", "8"])
        ),
    }


def b11_expense_capitalization(
    df: pd.DataFrame,
    *,
    audit_rules: dict | None = None,
    amount_tolerance: float = 0.02,
    min_amount: float = 0.0,
) -> pd.Series:
    """L2-04 expense capitalization within the same document."""

    required = ["document_id", "gl_account", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    cfg = _get_expense_capitalization_config(audit_rules)
    asset_prefixes = cfg["asset_prefixes"]
    expense_prefixes = cfg["expense_prefixes"]
    gl = df["gl_account"].fillna("").astype(str).str.strip()
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)

    asset_mask = debit.gt(0) & gl.str.startswith(asset_prefixes)
    expense_mask = credit.gt(0) & gl.str.startswith(expense_prefixes)
    if min_amount > 0:
        asset_mask = asset_mask & debit.ge(min_amount)
        expense_mask = expense_mask & credit.ge(min_amount)

    score_series = pd.Series(0.0, index=df.index)
    review_score_series = pd.Series(0.0, index=df.index)
    flagged = pd.Series(False, index=df.index)
    row_annotations: dict[object, dict[str, object]] = {}
    matched_doc_ids: set[str] = set()

    candidate_doc_ids = pd.Index(df.loc[asset_mask, "document_id"]).intersection(
        pd.Index(df.loc[expense_mask, "document_id"])
    )
    if candidate_doc_ids.empty:
        flagged.attrs["score_series"] = score_series
        flagged.attrs["review_score_series"] = review_score_series
        flagged.attrs["breakdown"] = {
            "flagged_rows": 0,
            "matched_docs": 0,
        }
        flagged.attrs["row_annotations"] = row_annotations
        return flagged

    candidate_df = df.loc[df["document_id"].isin(candidate_doc_ids)]
    for doc_id, group in candidate_df.groupby("document_id", sort=False):
        asset_rows = group.loc[asset_mask.loc[group.index]]
        expense_rows = group.loc[expense_mask.loc[group.index]]
        if asset_rows.empty or expense_rows.empty:
            continue

        matched_asset: set[object] = set()
        matched_expense: set[object] = set()
        match_type = ""
        asset_total = float(asset_rows["debit_amount"].sum())
        expense_total = float(expense_rows["credit_amount"].sum())

        for asset_idx, asset_row in asset_rows.iterrows():
            asset_amount = float(asset_row["debit_amount"])
            for expense_idx, expense_row in expense_rows.iterrows():
                expense_amount = float(expense_row["credit_amount"])
                if not _is_amount_close(asset_amount, expense_amount, amount_tolerance):
                    continue
                matched_asset.add(asset_idx)
                matched_expense.add(expense_idx)

        if matched_asset or matched_expense:
            match_type = "line_amount_match"
            target_indices = [
                *[idx for idx in asset_rows.index if idx in matched_asset],
                *[idx for idx in expense_rows.index if idx in matched_expense],
            ]
        else:
            if _is_amount_close(asset_total, expense_total, amount_tolerance):
                match_type = "subtotal_amount_match"
                target_indices = list(asset_rows.index) + list(expense_rows.index)
            else:
                continue

        flagged.loc[target_indices] = True
        score_series.loc[target_indices] = 1.0
        matched_doc_ids.add(str(doc_id))

        for idx in target_indices:
            row_annotations[idx] = {
                "match_type": match_type,
                "document_id": doc_id,
                "asset_debit_total": asset_total,
                "expense_credit_total": expense_total,
                "amount_difference": abs(asset_total - expense_total),
                "amount_tolerance": amount_tolerance,
                "score": 1.0,
            }

    flagged.attrs["score_series"] = score_series
    flagged.attrs["review_score_series"] = review_score_series
    flagged.attrs["breakdown"] = {
        "flagged_rows": int(flagged.sum()),
        "matched_docs": len(matched_doc_ids),
    }
    flagged.attrs["row_annotations"] = row_annotations
    return flagged
