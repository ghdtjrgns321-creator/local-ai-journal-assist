"""Groupby-based fraud rules for L2-02, L2-03, and L2-04."""

from __future__ import annotations

import re
from itertools import combinations

import pandas as pd
from rapidfuzz import fuzz

from config.settings import get_audit_rules


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


_RE_SPECIAL = re.compile(r"[^\w\s]", re.UNICODE)
_RE_ALNUM = re.compile(r"[^A-Za-z0-9]", re.UNICODE)


def _normalize_text(value: object) -> str:
    """Normalize free-text fields for conservative fuzzy matching."""

    normalized = _RE_SPECIAL.sub("", str(value).lower())
    return " ".join(normalized.split())


def _normalize_reference(value: object) -> str:
    """Normalize payment references across small punctuation/spacing changes."""

    return _RE_ALNUM.sub("", str(value).upper())


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
    work["_base_amt"] = _compute_base_amount(df)

    if "document_id" in df.columns:
        work["_document_id"] = df["document_id"].fillna("").astype(str).str.strip()

    if "reference" in df.columns:
        work["_reference"] = df["reference"].fillna("").astype(str).str.strip()

    partner_key = _resolve_b04_partner_key(df)
    if partner_key is not None:
        work["_partner_key"] = partner_key.fillna("").astype(str).str.strip()

    if "line_text" in df.columns:
        work["_line_text"] = df["line_text"].fillna("").map(_normalize_text)

    return work


def _flag_exact_duplicate_entries(work: pd.DataFrame) -> pd.Series:
    """Flag exact same-day duplicates while suppressing same-document repeats."""

    result = pd.Series(0.0, index=work.index)
    grouped = work.groupby(["gl_account", "_base_amt", "posting_date"], group_keys=False)
    for _, group in grouped:
        if len(group) < 2:
            continue
        doc_mask = _documents_differ(group)
        if bool(doc_mask.iloc[0]):
            result.loc[group.index] = 0.95
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
    ].copy()
    if target.empty:
        return result

    window = pd.Timedelta(days=window_days)
    for _, group in target.groupby(["_partner_key", "_reference", "gl_account"], group_keys=False):
        if len(group) < 2 or group["_document_id"].nunique() < 2:
            continue
        ordered = group.sort_values("posting_date")
        amounts = ordered["_base_amt"]
        tolerance = amounts.max() * amount_tolerance
        if (amounts.max() - amounts.min()) > tolerance:
            continue
        if (ordered["posting_date"].max() - ordered["posting_date"].min()) > window:
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
    ].copy()
    if target.empty:
        return result

    for _, group in target.groupby(["_partner_key", "gl_account"], group_keys=False):
        if len(group) < 2 or len(group) > max_group_size:
            continue

        ordered = group.sort_values("posting_date").reset_index(names="_row_index")
        rows = ordered.to_dict("records")
        for left_idx, left_row in enumerate(rows):
            for right_row in rows[left_idx + 1:]:
                day_gap = abs((right_row["posting_date"] - left_row["posting_date"]).days)
                if day_gap > window_days:
                    break
                if left_row["_document_id"] == right_row["_document_id"]:
                    continue
                if not _is_amount_close(left_row["_base_amt"], right_row["_base_amt"], amount_tolerance):
                    continue
                similarity = fuzz.token_sort_ratio(left_row["_line_text"], right_row["_line_text"])
                if similarity < fuzzy_threshold:
                    continue
                pair_score = max(0.55, min(0.85, 0.60 + ((similarity - fuzzy_threshold) / 100.0)))
                result.loc[[left_row["_row_index"], right_row["_row_index"]]] = result.loc[
                    [left_row["_row_index"], right_row["_row_index"]]
                ].clip(lower=pair_score)

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
        work["_partner_key"].ne("")
        & work["_document_id"].ne("")
    ].copy()
    if target.empty:
        return result

    for _, group in target.groupby(["_partner_key", "gl_account"], group_keys=False):
        if len(group) < 3 or len(group) > max_group_size:
            continue

        ordered = group.sort_values("posting_date").reset_index(names="_row_index")
        rows = ordered.to_dict("records")
        for target_row in rows:
            if target_row["_base_amt"] <= 0:
                continue

            candidates: list[dict[str, object]] = []
            for candidate_row in rows:
                if candidate_row["_row_index"] == target_row["_row_index"]:
                    continue
                if candidate_row["_document_id"] == target_row["_document_id"]:
                    continue
                if candidate_row["_base_amt"] <= 0 or candidate_row["_base_amt"] >= target_row["_base_amt"]:
                    continue
                day_gap = abs((candidate_row["posting_date"] - target_row["posting_date"]).days)
                if day_gap > split_window_days:
                    continue
                candidates.append(candidate_row)

            for left_row, right_row in combinations(candidates, 2):
                if len({target_row["_document_id"], left_row["_document_id"], right_row["_document_id"]}) < 3:
                    continue
                combined = float(left_row["_base_amt"]) + float(right_row["_base_amt"])
                if not _is_amount_close(combined, float(target_row["_base_amt"]), amount_tolerance):
                    continue
                result.loc[
                    [target_row["_row_index"], left_row["_row_index"], right_row["_row_index"]]
                ] = result.loc[
                    [target_row["_row_index"], left_row["_row_index"], right_row["_row_index"]]
                ].clip(lower=0.75)

    return result


def b04_duplicate_payment(
    df: pd.DataFrame,
    window_days: int = 45,
    reference_amount_tolerance: float = 0.01,
) -> pd.Series:
    """L2-02 duplicate payment rule for P2P disbursements.

    Phase 1 logic:
    - Scope to P2P transactions to avoid recurring O2C activity.
    - Strong signal: same partner + same reference + near-same amount across
      different document IDs.
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

    if "business_process" in df.columns:
        p2p_mask = df["business_process"] == "P2P"
    else:
        p2p_mask = pd.Series(True, index=df.index)

    if "document_type" in df.columns:
        p2p_mask = p2p_mask & df["document_type"].eq("KZ")

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

    agg_spec: dict[str, str] = {
        "_partner_key": "first",
        "posting_date": "min",
        "_base_amt": "max",
        "_reference": "first",
    }
    if "company_code" in target.columns:
        agg_spec["company_code"] = "first"

    doc_target = (
        target.groupby("_document_id", as_index=False)
        .agg(agg_spec)
        .rename(columns={"_document_id": "document_id"})
    )
    if doc_target.empty:
        return result

    doc_target["_reference_norm"] = doc_target["_reference"].map(_normalize_reference)
    window = pd.Timedelta(days=window_days)
    flagged_doc_ids: set[str] = set()

    ref_cols = ["_partner_key", "_reference_norm"]
    if "company_code" in doc_target.columns:
        ref_cols.insert(0, "company_code")

    ref_target = doc_target.loc[doc_target["_reference_norm"].ne("")]
    for _, group in ref_target.groupby(ref_cols, group_keys=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date")
        seen: list[tuple[pd.Timestamp, float]] = []
        for _, row in ordered.iterrows():
            amount = float(row["_base_amt"])
            tolerance = max(abs(amount) * reference_amount_tolerance, 1.0)
            if any(
                abs(amount - prev_amount) <= tolerance and (row["posting_date"] - prev_date) <= window
                for prev_date, prev_amount in seen
            ):
                flagged_doc_ids.add(str(row["document_id"]))
            seen.append((row["posting_date"], amount))

    blank_target = doc_target.loc[doc_target["_reference_norm"].eq("")].copy()
    if not blank_target.empty:
        recurring_mask = pd.Series(False, index=blank_target.index)
        null_cols = ["_partner_key", "_base_amt"]
        if "company_code" in blank_target.columns:
            null_cols.insert(0, "company_code")
        for _, group in blank_target.groupby(null_cols, group_keys=False):
            recurring_mask.loc[group.index] = _is_recurring_payment_series(group[["posting_date"]])
        blank_target = blank_target.loc[~recurring_mask]

        all_null_cols = list(null_cols)
        for _, group in doc_target.groupby(all_null_cols, group_keys=False):
            blank_ids = set(blank_target.loc[blank_target.index.intersection(group.index), "document_id"].astype(str))
            if not blank_ids:
                continue
            ordered = group.sort_values("posting_date")
            prev_date: pd.Timestamp | None = None
            for _, row in ordered.iterrows():
                if str(row["document_id"]) in blank_ids and prev_date is not None and (row["posting_date"] - prev_date) <= window:
                    flagged_doc_ids.add(str(row["document_id"]))
                prev_date = row["posting_date"]

    if flagged_doc_ids:
        result.loc[target.loc[target["_document_id"].isin(flagged_doc_ids)].index] = True

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

    required = ["gl_account", "posting_date", "debit_amount", "credit_amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    work = _prepare_duplicate_entry_work(df)
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
    score_frame = pd.DataFrame({
        "exact_duplicate": exact_scores,
        "reference_duplicate": reference_scores,
        "near_duplicate": near_scores,
        "split_duplicate": split_scores,
    }, index=df.index)
    confidence = score_frame.max(axis=1).fillna(0.0)
    result = confidence > 0

    reason_counts: dict[str, int] = {}
    confidence_band_counts = {"high": 0, "medium": 0, "low": 0}
    row_annotations: dict[int, dict[str, object]] = {}
    for idx in confidence[confidence > 0].index:
        row_scores = score_frame.loc[idx]
        matched = row_scores[row_scores > 0].sort_values(ascending=False)
        primary_reason = str(matched.index[0])
        primary_confidence = float(matched.iloc[0])
        if primary_confidence >= 0.85:
            confidence_band = "high"
        elif primary_confidence >= 0.70:
            confidence_band = "medium"
        else:
            confidence_band = "low"
        reason_counts[primary_reason] = reason_counts.get(primary_reason, 0) + 1
        confidence_band_counts[confidence_band] += 1
        row_annotations[int(idx)] = {
            "reason_code": primary_reason,
            "matched_reason_codes": matched.index.tolist(),
            "confidence": round(primary_confidence, 4),
            "confidence_band": confidence_band,
        }

    result.attrs["score_series"] = confidence
    result.attrs["breakdown"] = {
        "flagged_rows": int(result.sum()),
        "reason_counts": reason_counts,
        "confidence_band_counts": confidence_band_counts,
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
        "asset_prefixes": tuple(str(v).strip() for v in cfg.get("asset_account_prefixes", ["15"])),
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
    return (line.fillna("").astype(str) + " " + header.fillna("").astype(str)).str.strip().str.lower()


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
    flagged = pd.Series(False, index=df.index)
    row_annotations: dict[int, dict[str, object]] = {}
    immediate_rows = 0
    review_rows = 0
    reason_counts: dict[str, int] = {}

    for _, group in df.groupby("document_id", sort=False):
        asset_rows = group.loc[asset_mask.loc[group.index]]
        expense_rows = group.loc[expense_mask.loc[group.index]]
        if asset_rows.empty or expense_rows.empty:
            continue

        matched_asset: set[int] = set()
        matched_expense: set[int] = set()
        primary_reason = "line_amount_match"
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
            target_indices = list(matched_asset | matched_expense)
            confidence = 0.65
        else:
            asset_total = float(asset_rows["debit_amount"].sum())
            expense_total = float(expense_rows["credit_amount"].sum())
            if not _is_amount_close(asset_total, expense_total, amount_tolerance):
                continue
            target_indices = list(asset_rows.index) + list(expense_rows.index)
            primary_reason = "subtotal_amount_match"
            confidence = 0.55

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
            _contains_any_keyword(str(value), cfg["suspicious_keywords"]) for value in matched_text.tolist()
        ) or _contains_any_keyword(doc_text, cfg["suspicious_keywords"])
        normal_keyword_hit = any(
            _contains_any_keyword(str(value), cfg["normal_keywords"]) for value in matched_text.tolist()
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

        confidence = max(0.0, min(0.95, confidence))
        if confidence < review_threshold:
            continue

        if confidence >= immediate_threshold:
            confidence_band = "high"
            queue_label = "immediate"
            immediate_rows += len(target_indices)
        else:
            confidence_band = "medium"
            queue_label = "review"
            review_rows += len(target_indices)

        reason_counts[primary_reason] = reason_counts.get(primary_reason, 0) + len(target_indices)
        flagged.loc[target_indices] = True
        score_series.loc[target_indices] = confidence
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

        for idx in target_indices:
            row_annotations[int(idx)] = {
                "reason_code": primary_reason,
                "matched_reason_codes": matched_reasons,
                "confidence": round(confidence, 4),
                "confidence_band": confidence_band,
                "queue_label": queue_label,
            }

    flagged.attrs["score_series"] = score_series
    flagged.attrs["breakdown"] = {
        "immediate_rows": immediate_rows,
        "review_rows": review_rows,
        "reason_counts": reason_counts,
    }
    flagged.attrs["row_annotations"] = row_annotations
    return flagged
