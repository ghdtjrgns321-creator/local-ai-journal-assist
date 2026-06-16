"""Groupby-based fraud rules for L2-02, L2-03, and L2-04."""

from __future__ import annotations

import re
from itertools import combinations

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from config.settings import AuditSettings, get_audit_rules

L202_REFERENCE_MATCH_CONFIDENCE = 0.90
L202_MIXED_REFERENCE_FALLBACK_CONFIDENCE = 0.70
L202_AMOUNT_PARTNER_FALLBACK_CONFIDENCE = 0.65
L202_BLANK_REFERENCE_FALLBACK_CONFIDENCE = 0.60


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
    """Flag exact same-day duplicates while suppressing same-document repeats."""

    result = pd.Series(0.0, index=work.index)
    target = work.loc[
        work["_document_id"].ne(""),
        ["gl_account", "_base_amt", "_posting_ts", "_document_id"],
    ]
    if target.empty:
        return result

    group_doc_counts = target.groupby(
        ["gl_account", "_base_amt", "_posting_ts"],
        sort=False,
    )["_document_id"].transform("nunique")
    result.loc[target.index[group_doc_counts >= 2]] = 0.95
    return result


def _flag_reference_duplicate_entries(
    work: pd.DataFrame,
    *,
    amount_tolerance: float,
    window_days: int,
) -> pd.Series:
    """Flag same-reference duplicates across different documents."""

    result = pd.Series(0.0, index=work.index)
    required = {"_partner_key", "_reference", "_document_id"}
    if not required.issubset(work.columns):
        return result

    target = work.loc[
        work["_partner_key"].ne("")
        & work["_reference"].ne("")
        & work["_document_id"].ne("")
        & work["_posting_ts"].notna()
    ].copy()
    if target.empty:
        return result

    window = pd.Timedelta(days=window_days)
    group_cols = ["_partner_key", "_reference", "gl_account"]
    group_sizes = target.groupby(group_cols, sort=False)["_document_id"].transform("size")
    target = target.loc[group_sizes >= 2]
    if target.empty:
        return result

    for _, group in target.groupby(group_cols, group_keys=False):
        if len(group) < 2 or group["_document_id"].nunique() < 2:
            continue
        ordered = group.sort_values("_posting_ts")
        amounts = ordered["_base_amt"]
        tolerance = amounts.max() * amount_tolerance
        if (amounts.max() - amounts.min()) > tolerance:
            continue
        if (ordered["_posting_ts"].max() - ordered["_posting_ts"].min()) > window:
            continue
        result.loc[group.index] = 0.90

    return result


def _flag_near_duplicate_entries(
    work: pd.DataFrame,
    *,
    amount_tolerance: float,
    fuzzy_threshold: int,
    window_days: int,
    max_group_size: int,
) -> pd.Series:
    """Flag near-duplicate entries using partner/date/amount/text evidence."""

    result = pd.Series(0.0, index=work.index)
    if "_line_text" not in work.columns or "_document_id" not in work.columns:
        return result
    if "_partner_key" not in work.columns:
        return result

    target = work.loc[
        work["_partner_key"].ne("")
        & work["_line_text"].ne("")
        & work["_document_id"].ne("")
        & work["_posting_ts"].notna()
    ].copy()
    if target.empty:
        return result

    group_cols = ["_partner_key", "gl_account"]
    group_sizes = target.groupby(group_cols, sort=False)["_document_id"].transform("size")
    target = target.loc[group_sizes.between(2, max_group_size)]
    if target.empty:
        return result

    ordered = target.sort_values([*group_cols, "_posting_ts"]).reset_index(names="_row_index")
    group_key = (
        ordered["_partner_key"].astype(str) + "\x1f" + ordered["gl_account"].astype(str)
    ).to_numpy()
    row_indices = ordered["_row_index"].to_numpy()
    posting_dates = ordered["_posting_ts"].to_numpy(dtype="datetime64[ns]")
    amounts = ordered["_base_amt"].to_numpy(dtype="float64")
    document_ids = ordered["_document_id"].astype(str).to_numpy()
    line_texts = ordered["_line_text"].astype(str).to_numpy()

    boundaries = [0]
    if len(group_key) > 1:
        boundaries.extend((np.flatnonzero(group_key[1:] != group_key[:-1]) + 1).tolist())
    boundaries.append(len(ordered))

    for start, end in zip(boundaries, boundaries[1:], strict=False):
        for left_pos in range(start, end):
            for right_pos in range(left_pos + 1, end):
                day_gap = int(
                    (posting_dates[right_pos] - posting_dates[left_pos]) / pd.Timedelta(days=1),
                )
                if day_gap > window_days:
                    break
                if document_ids[left_pos] == document_ids[right_pos]:
                    continue
                if not _is_amount_close(amounts[left_pos], amounts[right_pos], amount_tolerance):
                    continue
                similarity = fuzz.token_sort_ratio(line_texts[left_pos], line_texts[right_pos])
                if similarity < fuzzy_threshold:
                    continue
                pair_score = max(0.55, min(0.85, 0.60 + ((similarity - fuzzy_threshold) / 100.0)))
                pair_indices = [row_indices[left_pos], row_indices[right_pos]]
                result.loc[pair_indices] = result.loc[pair_indices].clip(lower=pair_score)

    return result


def _flag_split_duplicate_entries(
    work: pd.DataFrame,
    *,
    amount_tolerance: float,
    split_window_days: int,
    max_group_size: int,
) -> pd.Series:
    """Flag likely split re-entry patterns within a short window."""

    result = pd.Series(0.0, index=work.index)
    if "_document_id" not in work.columns or "_partner_key" not in work.columns:
        return result

    target = work.loc[
        work["_partner_key"].ne("") & work["_document_id"].ne("") & work["_posting_ts"].notna()
    ].copy()
    if target.empty:
        return result

    group_cols = ["_partner_key", "gl_account"]
    group_sizes = target.groupby(group_cols, sort=False)["_document_id"].transform("size")
    target = target.loc[group_sizes.between(3, max_group_size)]
    if target.empty:
        return result

    ordered = target.sort_values([*group_cols, "_posting_ts"]).reset_index(names="_row_index")
    group_key = (
        ordered["_partner_key"].astype(str) + "\x1f" + ordered["gl_account"].astype(str)
    ).to_numpy()
    row_indices = ordered["_row_index"].to_numpy()
    posting_dates = ordered["_posting_ts"].to_numpy(dtype="datetime64[ns]")
    amounts = ordered["_base_amt"].to_numpy(dtype="float64")
    document_ids = ordered["_document_id"].astype(str).to_numpy()

    boundaries = [0]
    if len(group_key) > 1:
        boundaries.extend((np.flatnonzero(group_key[1:] != group_key[:-1]) + 1).tolist())
    boundaries.append(len(ordered))
    window_ns = np.timedelta64(split_window_days, "D")

    for start, end in zip(boundaries, boundaries[1:], strict=False):
        dates_group = posting_dates[start:end]
        for target_pos in range(start, end):
            target_amount = amounts[target_pos]
            if target_amount <= 0:
                continue
            left_bound = start + int(
                np.searchsorted(
                    dates_group,
                    posting_dates[target_pos] - window_ns,
                    side="left",
                ),
            )
            right_bound = start + int(
                np.searchsorted(
                    dates_group,
                    posting_dates[target_pos] + window_ns,
                    side="right",
                ),
            )
            candidates = [
                pos
                for pos in range(left_bound, right_bound)
                if pos != target_pos
                and document_ids[pos] != document_ids[target_pos]
                and 0 < amounts[pos] < target_amount
            ]
            for left_pos, right_pos in combinations(candidates, 2):
                if (
                    len(
                        {
                            document_ids[target_pos],
                            document_ids[left_pos],
                            document_ids[right_pos],
                        }
                    )
                    < 3
                ):
                    continue
                combined = float(amounts[left_pos]) + float(amounts[right_pos])
                if not _is_amount_close(combined, float(target_amount), amount_tolerance):
                    continue
                split_indices = [
                    row_indices[target_pos],
                    row_indices[left_pos],
                    row_indices[right_pos],
                ]
                result.loc[split_indices] = result.loc[split_indices].clip(lower=0.75)

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


def _flag_ic_r2r_split_population(
    work: pd.DataFrame,
    df: pd.DataFrame,
    *,
    split_window_days: int,
) -> pd.Series:
    """Capture IC/R2R split-shaped documents across companies as zero-score population."""

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
        & source["business_process"].eq("R2R")
        & source["document_type"].eq("IC")
    ].copy()
    if target.empty:
        return result

    rows = list(
        target.sort_values("_posting_ts")
        .reset_index(names="_row_index")[
            ["_row_index", "_posting_ts", "_base_amt", "_document_id", "reference"]
        ]
        .itertuples(index=False, name=None)
    )
    max_gap = pd.Timedelta(days=max(split_window_days * 2, split_window_days))
    for target_row in rows:
        candidates = [
            row
            for row in rows
            if row[0] != target_row[0]
            and row[3] != target_row[3]
            and abs(row[1] - target_row[1]) <= max_gap
            and row[2] < target_row[2]
        ]
        for left_row, right_row in combinations(candidates, 2):
            if len({target_row[3], left_row[3], right_row[3]}) < 3:
                continue
            ref_numbers = [
                _trailing_reference_number(target_row[4]),
                _trailing_reference_number(left_row[4]),
                _trailing_reference_number(right_row[4]),
            ]
            if any(value is None for value in ref_numbers):
                continue
            ref_numbers_sorted = sorted(ref_numbers)
            if not (
                ref_numbers_sorted[2] - ref_numbers_sorted[1] == 1
                and 5 <= ref_numbers_sorted[1] - ref_numbers_sorted[0] <= 15
            ):
                continue
            if not _is_amount_close(
                float(left_row[2]) + float(right_row[2]),
                float(target_row[2]),
                0.02,
            ):
                continue
            indices = [target_row[0], left_row[0], right_row[0]]
            result.loc[indices] = result.loc[indices].clip(lower=0.01)

    return result


def _document_line_signature(group: pd.DataFrame) -> tuple[tuple[str, str, float], ...]:
    """Return a stable document-level GL/side/amount signature."""

    rows: list[tuple[str, str, float]] = []
    for row in group.itertuples(index=False):
        debit = float(getattr(row, "debit_amount", 0.0) or 0.0)
        credit = float(getattr(row, "credit_amount", 0.0) or 0.0)
        side = "D" if debit >= credit else "C"
        amount = max(abs(debit), abs(credit))
        rows.append((str(getattr(row, "gl_account", "")).strip(), side, amount))
    return tuple(sorted(rows))


def _amount_signatures_close(
    left: tuple[tuple[str, str, float], ...],
    right: tuple[tuple[str, str, float], ...],
    amount_tolerance: float,
) -> bool:
    """Compare same-shape document signatures with per-line amount tolerance."""

    if len(left) != len(right):
        return False
    for left_row, right_row in zip(left, right, strict=True):
        if left_row[:2] != right_row[:2]:
            return False
        if not _is_amount_close(left_row[2], right_row[2], amount_tolerance):
            return False
    return True


def _build_document_duplicate_signatures(work: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Build document-level signatures used by L2-03 document duplicate matching."""

    if "_document_id" not in work.columns:
        return pd.DataFrame()

    source = pd.DataFrame(
        {
            "_document_id": work["_document_id"],
            "_posting_ts": work["_posting_ts"],
            "_reference_norm": (
                work["_reference"].map(_normalize_reference)
                if "_reference" in work.columns
                else pd.Series("", index=work.index)
            ),
            "_partner_key": (
                work["_partner_key"]
                if "_partner_key" in work.columns
                else pd.Series("", index=work.index)
            ),
            "_line_text_norm": (
                work["_line_text"]
                if "_line_text" in work.columns
                else pd.Series("", index=work.index)
            ),
            "company_code": (
                df["company_code"].fillna("").astype(str).str.strip()
                if "company_code" in df.columns
                else pd.Series("", index=df.index)
            ),
            "business_process": (
                df["business_process"].fillna("").astype(str).str.strip()
                if "business_process" in df.columns
                else pd.Series("", index=df.index)
            ),
            "document_type": (
                df["document_type"].fillna("").astype(str).str.strip()
                if "document_type" in df.columns
                else pd.Series("", index=df.index)
            ),
            "gl_account": df["gl_account"].fillna("").astype(str).str.strip(),
            "debit_amount": df["debit_amount"].fillna(0.0),
            "credit_amount": df["credit_amount"].fillna(0.0),
        },
        index=df.index,
    )

    source = source.loc[source["_document_id"].ne("")].copy()
    if source.empty:
        return pd.DataFrame()

    source["_side"] = source["debit_amount"] >= source["credit_amount"]
    source["_side"] = source["_side"].map({True: "D", False: "C"})
    source["_line_amount"] = source[["debit_amount", "credit_amount"]].abs().max(axis=1)
    source["_line_signature_row"] = list(
        zip(
            source["gl_account"],
            source["_side"],
            source["_line_amount"],
        )
    )

    grouped = source.groupby("_document_id", sort=False)
    docs = grouped.agg(
        posting_date=("_posting_ts", "min"),
        company_code=("company_code", "first"),
        business_process=("business_process", "first"),
        document_type=("document_type", "first"),
        reference_norm=("_reference_norm", "first"),
        partner_key=("_partner_key", "first"),
        row_indices=("_document_id", lambda s: s.index.tolist()),
        text_parts=("_line_text_norm", list),
        line_signature_parts=("_line_signature_row", list),
        line_count=("_document_id", "size"),
    ).reset_index(names="document_id")

    docs["text_signature"] = docs["text_parts"].map(
        lambda parts: _normalize_duplicate_text(" ".join(str(part) for part in parts if str(part)))
    )
    docs["line_signature"] = docs["line_signature_parts"].map(lambda parts: tuple(sorted(parts)))
    return docs.drop(columns=["text_parts", "line_signature_parts"])


def _flag_document_duplicate_entries(
    work: pd.DataFrame,
    df: pd.DataFrame,
    *,
    amount_tolerance: float,
    fuzzy_threshold: int,
    window_days: int,
    max_group_size: int,
) -> pd.Series:
    """Flag duplicate documents using document-level shape, reference, and text evidence."""

    result = pd.Series(0.0, index=work.index)
    docs = _build_document_duplicate_signatures(work, df)
    if docs.empty:
        return result

    doc_window_days = max(window_days, 15)
    window = pd.Timedelta(days=doc_window_days)

    docs["_line_signature_key"] = docs["line_signature"].map(repr)
    ref_docs = docs.loc[docs["reference_norm"].astype(str).ne("")].copy()
    blank_docs = docs.loc[
        docs["reference_norm"].astype(str).eq("") & docs["partner_key"].astype(str).ne("")
    ].copy()

    ref_grouping_cols = ["company_code", "business_process", "document_type", "reference_norm"]
    if not ref_docs.empty:
        ref_sizes = ref_docs.groupby(
            ref_grouping_cols,
            dropna=False,
            sort=False,
        )["document_id"].transform("size")
        ref_docs = ref_docs.loc[ref_sizes.between(2, max_group_size)]

    blank_grouping_cols = [
        "company_code",
        "business_process",
        "document_type",
        "partner_key",
        "_line_signature_key",
    ]
    if not blank_docs.empty:
        blank_sizes = blank_docs.groupby(
            blank_grouping_cols,
            dropna=False,
            sort=False,
        )["document_id"].transform("size")
        blank_docs = blank_docs.loc[blank_sizes.between(2, max_group_size)]

    if not ref_docs.empty:
        _mark_document_duplicate_pairs(
            ref_docs,
            ref_grouping_cols,
            result,
            window=window,
            amount_tolerance=amount_tolerance,
            fuzzy_threshold=fuzzy_threshold,
            require_reference=True,
        )

    if not blank_docs.empty:
        for _, group in blank_docs.groupby(blank_grouping_cols, dropna=False, sort=False):
            ordered = group.sort_values("posting_date").reset_index(drop=True)
            records = list(ordered.itertuples(index=False))
            for left_pos, left in enumerate(records):
                for right in records[left_pos + 1 :]:
                    day_gap = right.posting_date - left.posting_date
                    if day_gap > window:
                        break
                    if left.document_id == right.document_id:
                        continue
                    if not _amount_signatures_close(
                        left.line_signature,
                        right.line_signature,
                        amount_tolerance,
                    ):
                        continue

                    same_partner = bool(left.partner_key) and left.partner_key == right.partner_key
                    text_similarity = fuzz.token_sort_ratio(
                        left.text_signature,
                        right.text_signature,
                    )
                    text_match = text_similarity >= max(70, fuzzy_threshold - 10)

                    if same_partner and text_match:
                        target_indices = list(left.row_indices) + list(right.row_indices)
                        result.loc[target_indices] = result.loc[target_indices].clip(lower=0.82)

    return result


def _mark_document_duplicate_pairs(
    docs: pd.DataFrame,
    group_cols: list[str],
    result: pd.Series,
    *,
    window: pd.Timedelta,
    amount_tolerance: float,
    fuzzy_threshold: int,
    require_reference: bool,
) -> None:
    """Mark duplicate document pairs using sorted arrays instead of group objects."""

    ordered = docs.sort_values([*group_cols, "posting_date"]).reset_index(drop=True)
    group_key = ordered[group_cols].astype(str).agg("\x1f".join, axis=1).to_numpy()
    posting_dates = ordered["posting_date"].to_numpy(dtype="datetime64[ns]")
    document_ids = ordered["document_id"].astype(str).to_numpy()
    reference_norms = ordered["reference_norm"].astype(str).to_numpy()
    partner_keys = ordered["partner_key"].astype(str).to_numpy()
    text_signatures = ordered["text_signature"].astype(str).to_numpy()
    line_signatures = ordered["line_signature"].to_numpy(dtype=object)
    row_indices = ordered["row_indices"].to_numpy(dtype=object)

    boundaries = [0]
    if len(group_key) > 1:
        boundaries.extend((np.flatnonzero(group_key[1:] != group_key[:-1]) + 1).tolist())
    boundaries.append(len(ordered))
    window_ns = np.timedelta64(int(window / pd.Timedelta(days=1)), "D")

    for start, end in zip(boundaries, boundaries[1:], strict=False):
        dates_group = posting_dates[start:end]
        for left_pos in range(start, end):
            right_bound = start + int(
                np.searchsorted(
                    dates_group,
                    posting_dates[left_pos] + window_ns,
                    side="right",
                ),
            )
            for right_pos in range(left_pos + 1, right_bound):
                if document_ids[left_pos] == document_ids[right_pos]:
                    continue
                left_signature = line_signatures[left_pos]
                right_signature = line_signatures[right_pos]
                if left_signature != right_signature and not _amount_signatures_close(
                    left_signature,
                    right_signature,
                    amount_tolerance,
                ):
                    continue

                same_reference = (
                    bool(reference_norms[left_pos])
                    and reference_norms[left_pos] == reference_norms[right_pos]
                )
                same_partner = (
                    bool(partner_keys[left_pos])
                    and partner_keys[left_pos] == partner_keys[right_pos]
                )
                if require_reference and not same_reference:
                    continue
                text_similarity = fuzz.token_sort_ratio(
                    text_signatures[left_pos],
                    text_signatures[right_pos],
                )
                text_match = text_similarity >= max(70, fuzzy_threshold - 10)

                if same_reference:
                    pair_score = 0.92 if text_match else 0.88
                elif same_partner and text_match:
                    pair_score = 0.82
                else:
                    continue

                target_indices = list(row_indices[left_pos]) + list(row_indices[right_pos])
                result.loc[target_indices] = result.loc[target_indices].clip(lower=pair_score)


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
    """Score duplicate candidates without removing the population capture.

    L2-03 should first capture duplicate-shaped entries. Routine system,
    batch, and recurring repeats are kept as detected candidates, but receive
    no fraud score unless the duplicate signal has a stronger risk shape.
    """

    score_series = confidence.astype(float).copy()
    source = _l203_source_series(df)
    routine_source = source.isin({"automated", "recurring", "batch", "interface", "system"})

    routine_reference = result & routine_source & score_frame["reference_duplicate"].gt(0)
    routine_split = result & routine_source & score_frame["split_duplicate"].gt(0)
    document_type = (
        df["document_type"]
        .where(df["document_type"].notna(), "")
        .astype(str)
        .str.strip()
        .str.upper()
        if "document_type" in df.columns
        else pd.Series("", index=df.index)
    )
    business_process = (
        df["business_process"]
        .where(df["business_process"].notna(), "")
        .astype(str)
        .str.strip()
        .str.upper()
        if "business_process" in df.columns
        else pd.Series("", index=df.index)
    )
    routine_ic_split = routine_split & document_type.eq("IC") & business_process.eq("R2R")
    routine_review = routine_reference | routine_split
    routine_population = result & routine_source & ~routine_review

    score_series.loc[routine_population] = 0.0
    score_series.loc[routine_review] = score_series.loc[routine_review].clip(upper=0.35)
    score_series.loc[routine_ic_split] = 0.0
    return score_series.where(result, 0.0)


def _l203_queue_label(score: float, source: str) -> str:
    if score <= 0:
        return "normal_duplicate_population"
    if source in {"automated", "recurring", "batch", "interface", "system"}:
        return "routine_duplicate_review"
    if score >= 0.85:
        return "priority_duplicate_review"
    return "duplicate_review"


def b04_duplicate_payment(
    df: pd.DataFrame,
    window_days: int = 45,
    reference_amount_tolerance: float = 0.02,
    reference_amount_cap: float = 100_000.0,
) -> pd.Series:
    """L2-02 duplicate payment rule for P2P disbursements.

    Phase 1 logic:
    - Scope to P2P transactions to avoid recurring O2C activity.
    - Strong signal: same partner + same reference + near-same amount across
      different document IDs. The default 2% amount tolerance catches small
      fee, rounding, or FX differences, capped at KRW 100,000 by default.
    - Fallback signal: same partner + same amount within the time window when
      reference is missing, while suppressing stable monthly recurring payments.
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
                if abs(amount - float(prev["amount"])) <= tolerance and day_gap <= window:
                    doc_id = str(row["document_id"])
                    flagged_doc_ids.add(doc_id)
                    doc_annotations[doc_id] = {
                        "reason_code": "reference_match",
                        "confidence": L202_REFERENCE_MATCH_CONFIDENCE,
                        "confidence_band": "high",
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
    fallback_confidence = {
        "mixed_reference_fallback": L202_MIXED_REFERENCE_FALLBACK_CONFIDENCE,
        "amount_partner_fallback": L202_AMOUNT_PARTNER_FALLBACK_CONFIDENCE,
        "blank_reference_fallback": L202_BLANK_REFERENCE_FALLBACK_CONFIDENCE,
    }
    fallback_band = {
        "mixed_reference_fallback": "medium",
        "amount_partner_fallback": "medium",
        "blank_reference_fallback": "low",
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
            if amount == prev_amount:
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
                if day_gap > window:
                    continue
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
                    "confidence": fallback_confidence[reason_code],
                    "confidence_band": fallback_band[reason_code],
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
                    "confidence": L202_AMOUNT_PARTNER_FALLBACK_CONFIDENCE,
                    "confidence_band": "medium",
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
) -> pd.Series:
    """L2-03 duplicate entry with exact, reference, near, and split signals."""

    required = ["document_id", "gl_account", "posting_date", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    work = _prepare_duplicate_entry_work(df)
    document_scores = _flag_document_duplicate_entries(
        work,
        df,
        amount_tolerance=amount_tolerance,
        fuzzy_threshold=fuzzy_threshold,
        window_days=window_days,
        max_group_size=max_group_size,
    )
    exact_scores = _flag_exact_duplicate_entries(work)
    reference_scores = _flag_reference_duplicate_entries(
        work,
        amount_tolerance=amount_tolerance,
        window_days=window_days,
    )
    near_scores = _flag_near_duplicate_entries(
        work,
        amount_tolerance=amount_tolerance,
        fuzzy_threshold=fuzzy_threshold,
        window_days=window_days,
        max_group_size=max_group_size,
    )
    split_scores = _flag_split_duplicate_entries(
        work,
        amount_tolerance=amount_tolerance,
        split_window_days=split_window_days,
        max_group_size=max_group_size,
    )
    o2c_offset_scores = _flag_o2c_offset_duplicate_entries(work, df)
    ic_split_population_scores = _flag_ic_r2r_split_population(
        work,
        df,
        split_window_days=split_window_days,
    )
    score_frame = pd.DataFrame(
        {
            "document_duplicate": document_scores,
            "exact_duplicate": exact_scores,
            "reference_duplicate": reference_scores,
            "near_duplicate": near_scores,
            "split_duplicate": split_scores,
            "o2c_offset_duplicate": o2c_offset_scores,
            "ic_split_duplicate": ic_split_population_scores,
        },
        index=df.index,
    )
    confidence = score_frame.max(axis=1).fillna(0.0)
    result = confidence > 0
    score_series = _score_l203_duplicate_entries(df, result, confidence, score_frame)

    reason_counts: dict[str, int] = {}
    confidence_band_counts = {"high": 0, "medium": 0, "low": 0, "population": 0}
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
        if score >= 0.85:
            confidence_band = "high"
        elif score >= 0.35:
            confidence_band = "medium"
        elif score > 0:
            confidence_band = "low"
        else:
            confidence_band = "population"
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
        "normal_keywords": tuple(
            str(v).strip().lower() for v in cfg.get("normal_capitalization_keywords", [])
        ),
        "suspicious_keywords": tuple(
            str(v).strip().lower() for v in cfg.get("suspicious_expense_keywords", [])
        ),
        "normal_document_types": tuple(
            str(v).strip().upper() for v in cfg.get("normal_document_types", ["AA", "FA"])
        ),
        "suspicious_sources": tuple(
            str(v).strip().lower() for v in cfg.get("suspicious_sources", ["manual", "adjustment"])
        ),
        "suspicious_processes": tuple(
            str(v).strip().upper()
            for v in cfg.get("suspicious_processes", ["P2P", "O2C", "R2R", "H2R"])
        ),
    }


def _row_text(df: pd.DataFrame) -> pd.Series:
    """Return combined searchable text for contextual L2-04 hints."""

    line = df["line_text"] if "line_text" in df.columns else pd.Series("", index=df.index)
    header = df["header_text"] if "header_text" in df.columns else pd.Series("", index=df.index)
    return (
        (line.fillna("").astype(str) + " " + header.fillna("").astype(str)).str.strip().str.lower()
    )


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """Return True when text contains any configured keyword."""

    if not text or not keywords:
        return False
    return any(keyword and keyword in text for keyword in keywords)


def b11_expense_capitalization(
    df: pd.DataFrame,
    *,
    audit_rules: dict | None = None,
    amount_tolerance: float = 0.02,
    min_amount: float = 0.0,
    review_threshold: float = 0.45,
    immediate_threshold: float = 0.75,
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
    text = _row_text(df)

    asset_mask = debit.gt(0) & gl.str.startswith(asset_prefixes)
    expense_mask = credit.gt(0) & gl.str.startswith(expense_prefixes)
    if min_amount > 0:
        asset_mask = asset_mask & debit.ge(min_amount)
        expense_mask = expense_mask & credit.ge(min_amount)

    score_series = pd.Series(0.0, index=df.index)
    review_score_series = pd.Series(0.0, index=df.index)
    flagged = pd.Series(False, index=df.index)
    row_annotations: dict[object, dict[str, object]] = {}
    immediate_rows = 0
    review_rows = 0
    low_score_rows = 0
    population_rows = 0
    reason_counts: dict[str, int] = {}
    confidence_band_counts = {"high": 0, "medium": 0, "low": 0, "population": 0}
    queue_counts = {"immediate": 0, "review": 0, "low_review": 0, "population": 0}
    immediate_doc_ids: set[str] = set()
    review_doc_ids: set[str] = set()
    low_score_doc_ids: set[str] = set()
    population_doc_ids: set[str] = set()
    reason_doc_ids: dict[str, set[str]] = {}
    modifier_row_counts: dict[str, int] = {}
    zero_score_doc_ids: set[str] = set()

    candidate_doc_ids = pd.Index(df.loc[asset_mask, "document_id"]).intersection(
        pd.Index(df.loc[expense_mask, "document_id"])
    )
    if candidate_doc_ids.empty:
        flagged.attrs["score_series"] = score_series
        flagged.attrs["review_score_series"] = review_score_series
        flagged.attrs["breakdown"] = {
            "immediate_rows": immediate_rows,
            "review_rows": review_rows,
            "low_score_rows": low_score_rows,
            "population_rows": population_rows,
            "queue_counts": queue_counts,
            "confidence_band_counts": confidence_band_counts,
            "immediate_docs": 0,
            "review_docs": 0,
            "low_score_docs": 0,
            "population_docs": 0,
            "reason_counts": reason_counts,
            "reason_doc_counts": {},
            "modifier_row_counts": modifier_row_counts,
            "normal_context_suppressed_docs": 0,
            "zero_score_docs": 0,
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
        primary_reason = "asset_expense_combo"
        confidence = 0.0

        for asset_idx, asset_row in asset_rows.iterrows():
            asset_amount = float(asset_row["debit_amount"])
            for expense_idx, expense_row in expense_rows.iterrows():
                expense_amount = float(expense_row["credit_amount"])
                if not _is_amount_close(asset_amount, expense_amount, amount_tolerance):
                    continue
                matched_asset.add(asset_idx)
                matched_expense.add(expense_idx)

        if matched_asset or matched_expense:
            primary_reason = "line_amount_match"
            confidence = 0.55
        else:
            asset_total = float(asset_rows["debit_amount"].sum())
            expense_total = float(expense_rows["credit_amount"].sum())
            if _is_amount_close(asset_total, expense_total, amount_tolerance):
                primary_reason = "subtotal_amount_match"
                confidence = 0.35

        target_indices = list(asset_rows.index) + list(expense_rows.index)

        doc_text = " ".join(text.loc[group.index].tolist()).strip().lower()
        doc_type = (
            group["document_type"].fillna("").astype(str).str.upper()
            if "document_type" in group.columns
            else pd.Series("", index=group.index)
        )
        source = (
            group["source"].fillna("").astype(str).str.lower()
            if "source" in group.columns
            else pd.Series("", index=group.index)
        )
        process = (
            group["business_process"].fillna("").astype(str).str.upper()
            if "business_process" in group.columns
            else pd.Series("", index=group.index)
        )

        matched_text = text.loc[target_indices]
        suspicious_keyword_hit = any(
            _contains_any_keyword(str(value), cfg["suspicious_keywords"])
            for value in matched_text.tolist()
        ) or _contains_any_keyword(doc_text, cfg["suspicious_keywords"])
        normal_keyword_hit = any(
            _contains_any_keyword(str(value), cfg["normal_keywords"])
            for value in matched_text.tolist()
        ) or _contains_any_keyword(doc_text, cfg["normal_keywords"])
        suspicious_source_hit = source.isin(cfg["suspicious_sources"]).any()
        suspicious_process_hit = process.isin(cfg["suspicious_processes"]).any()
        normal_doc_type_hit = doc_type.isin(cfg["normal_document_types"]).any()

        if suspicious_keyword_hit:
            confidence += 0.15
        if suspicious_source_hit:
            confidence += 0.10
        if suspicious_process_hit:
            confidence += 0.05
        if normal_keyword_hit:
            confidence -= 0.20
        if normal_doc_type_hit:
            confidence -= 0.10
        if normal_keyword_hit and normal_doc_type_hit:
            confidence = 0.0

        confidence = max(0.0, min(0.95, confidence))

        if confidence >= immediate_threshold:
            confidence_band = "high"
            queue_label = "immediate"
            immediate_rows += len(target_indices)
            confidence_band_counts["high"] += len(target_indices)
            queue_counts["immediate"] += len(target_indices)
            immediate_doc_ids.add(str(doc_id))
        elif confidence >= review_threshold:
            confidence_band = "medium"
            queue_label = "review"
            review_rows += len(target_indices)
            confidence_band_counts["medium"] += len(target_indices)
            queue_counts["review"] += len(target_indices)
            review_doc_ids.add(str(doc_id))
        elif confidence > 0:
            confidence_band = "low"
            queue_label = "low_review"
            low_score_rows += len(target_indices)
            confidence_band_counts["low"] += len(target_indices)
            queue_counts["low_review"] += len(target_indices)
            low_score_doc_ids.add(str(doc_id))
        else:
            confidence_band = "population"
            queue_label = "population"
            population_rows += len(target_indices)
            confidence_band_counts["population"] += len(target_indices)
            queue_counts["population"] += len(target_indices)
            population_doc_ids.add(str(doc_id))
            zero_score_doc_ids.add(str(doc_id))
            if normal_keyword_hit or normal_doc_type_hit:
                zero_score_doc_ids.add(str(doc_id))

        reason_counts[primary_reason] = reason_counts.get(primary_reason, 0) + len(target_indices)
        reason_doc_ids.setdefault(primary_reason, set()).add(str(doc_id))
        flagged.loc[target_indices] = True
        if queue_label == "immediate":
            score_series.loc[target_indices] = confidence
        elif queue_label in {"review", "low_review"}:
            review_score_series.loc[target_indices] = confidence
        matched_reasons = [primary_reason]
        if suspicious_keyword_hit:
            matched_reasons.append("suspicious_expense_keyword")
        if suspicious_source_hit:
            matched_reasons.append("manual_source")
        if suspicious_process_hit:
            matched_reasons.append("suspicious_process")
        if normal_keyword_hit:
            matched_reasons.append("normal_capex_keyword")
        if normal_doc_type_hit:
            matched_reasons.append("normal_document_type")

        for reason in matched_reasons:
            if reason == primary_reason:
                continue
            modifier_row_counts[reason] = modifier_row_counts.get(reason, 0) + len(target_indices)

        for idx in target_indices:
            annotation = {
                "reason_code": primary_reason,
                "matched_reason_codes": matched_reasons,
                "confidence": round(confidence, 4),
                "confidence_band": confidence_band,
                "queue_label": queue_label,
            }
            if queue_label == "immediate":
                annotation["score"] = round(confidence, 4)
            elif queue_label in {"review", "low_review"}:
                annotation["review_score"] = round(confidence, 4)
            row_annotations[idx] = annotation

    flagged.attrs["score_series"] = score_series
    flagged.attrs["review_score_series"] = review_score_series
    flagged.attrs["breakdown"] = {
        "immediate_rows": immediate_rows,
        "review_rows": review_rows,
        "low_score_rows": low_score_rows,
        "population_rows": population_rows,
        "queue_counts": queue_counts,
        "confidence_band_counts": confidence_band_counts,
        "immediate_docs": len(immediate_doc_ids),
        "review_docs": len(review_doc_ids),
        "low_score_docs": len(low_score_doc_ids),
        "population_docs": len(population_doc_ids),
        "reason_counts": reason_counts,
        "reason_doc_counts": {reason: len(doc_ids) for reason, doc_ids in reason_doc_ids.items()},
        "modifier_row_counts": modifier_row_counts,
        "normal_context_suppressed_docs": len(zero_score_doc_ids),
        "zero_score_docs": len(zero_score_doc_ids),
    }
    flagged.attrs["row_annotations"] = row_annotations
    return flagged
