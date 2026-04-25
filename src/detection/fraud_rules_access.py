"""Access-control-based fraud rules: L1-05, L1-06, L1-07, L3-03."""

from __future__ import annotations

import pandas as pd

from config.settings import get_audit_rules


def _normalized_text(series: pd.Series) -> pd.Series:
    """Return trimmed lowercase strings with NA handled as empty."""

    return series.fillna("").astype(str).str.strip().str.lower()


def _normalized_persona(series: pd.Series) -> pd.Series:
    """Return normalized persona values with spaces collapsed to underscores."""

    return _normalized_text(series).str.replace(" ", "_", regex=False)


def _normalized_process(series: pd.Series) -> pd.Series:
    """Return normalized business-process codes."""

    return series.fillna("").astype(str).str.strip().str.upper()


def _normalized_actor(series: pd.Series) -> pd.Series:
    """Return normalized actor/account identifiers."""

    return _normalized_text(series).str.replace(" ", "_", regex=False)


def _normalized_account_code(series: pd.Series) -> pd.Series:
    """Return normalized account codes while preserving leading zeroes."""

    return _normalized_text(series).str.replace(r"\.0+$", "", regex=True)


def _get_self_approval_allow_config(audit_rules: dict | None = None) -> dict[str, tuple[str, ...]]:
    """Load editable allowlist defaults for system-approved self-approval."""

    rules = audit_rules or get_audit_rules()
    allow = rules.get("patterns", {}).get("self_approval_allow", {})
    return {
        "user_personas": tuple(
            str(v).strip().lower() for v in allow.get("user_personas", ["automated_system"])
        ),
        "company_codes": tuple(str(v).strip().lower() for v in allow.get("company_codes", [])),
        "sources": tuple(str(v).strip().lower() for v in allow.get("sources", ["automated"])),
    }


def _get_self_approval_review_config(audit_rules: dict | None = None) -> dict[str, tuple[str, ...]]:
    """Load editable defaults for self-approval review classification."""

    rules = audit_rules or get_audit_rules()
    review = rules.get("patterns", {}).get("self_approval_review", {})
    return {
        "company_codes": tuple(str(v).strip().lower() for v in review.get("company_codes", [])),
        "document_types": tuple(str(v).strip().lower() for v in review.get("document_types", [])),
        "business_processes": tuple(
            str(v).strip().lower() for v in review.get("business_processes", ["r2r", "a2r"])
        ),
    }


def _get_self_approval_immediate_override_config(
    audit_rules: dict | None = None,
) -> dict[str, object]:
    """Load escalation conditions that upgrade review-required rows to immediate."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    override = patterns.get("self_approval_immediate_override", {})
    manual_sources = override.get("manual_sources", patterns.get("manual_source_codes", ["manual", "adjustment"]))
    return {
        "materiality_amount": float(override.get("materiality_amount", 1_000_000_000)),
        "manual_sources": tuple(str(v).strip().lower() for v in manual_sources),
        "high_risk_accounts": tuple(
            str(v).strip().lower() for v in override.get("high_risk_accounts", ["1190", "2190"])
        ),
        "high_risk_account_prefixes": tuple(
            str(v).strip().lower()
            for v in override.get("high_risk_account_prefixes", ["111", "112", "113"])
        ),
    }


def _get_skipped_approval_immediate_config(
    audit_rules: dict | None = None,
) -> dict[str, tuple[str, ...] | int]:
    """Load immediate-violation corroboration policy for L1-07."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    cfg = patterns.get("skipped_approval_immediate", {})
    manual_sources = cfg.get("manual_sources", patterns.get("manual_source_codes", ["manual", "adjustment"]))
    return {
        "manual_sources": tuple(str(v).strip().lower() for v in manual_sources),
        "business_processes": tuple(
            str(v).strip().upper()
            for v in cfg.get("business_processes", ["TRE", "P2P", "O2C", "H2R"])
        ),
        "min_evidence_count": int(cfg.get("min_evidence_count", 2)),
    }


def _line_amount(df: pd.DataFrame) -> pd.Series:
    """Return per-row representative amount for threshold checks."""

    debit_raw = df["debit_amount"] if "debit_amount" in df.columns else pd.Series(0.0, index=df.index)
    credit_raw = df["credit_amount"] if "credit_amount" in df.columns else pd.Series(0.0, index=df.index)
    debit = pd.to_numeric(debit_raw, errors="coerce").fillna(0.0)
    credit = pd.to_numeric(credit_raw, errors="coerce").fillna(0.0)
    return pd.concat([debit, credit], axis=1).max(axis=1)


def _is_manual_source(df: pd.DataFrame, manual_sources: tuple[str, ...]) -> pd.Series:
    """Return rows treated as human/manual entries."""

    if "source" not in df.columns:
        return pd.Series(True, index=df.index)
    if not manual_sources:
        return pd.Series(True, index=df.index)
    return _normalized_text(df["source"]).isin(manual_sources)


def _is_abnormal_self_approval_time(df: pd.DataFrame) -> pd.Series:
    """Return rows posted during weekend/holiday/after-hours windows."""

    abnormal = pd.Series(False, index=df.index)
    if "is_weekend" in df.columns:
        abnormal = abnormal | df["is_weekend"].fillna(False).astype(bool)
    if "is_holiday" in df.columns:
        abnormal = abnormal | df["is_holiday"].fillna(False).astype(bool)
    if "is_after_hours" in df.columns:
        abnormal = abnormal | df["is_after_hours"].fillna(False).astype(bool)
    if "time_zone_category" in df.columns:
        abnormal = abnormal | _normalized_text(df["time_zone_category"]).isin(("overtime", "midnight"))
    if "posting_time" in df.columns:
        posting_hour = pd.to_numeric(df["posting_time"], errors="coerce")
        abnormal = abnormal | posting_hour.between(23, 24, inclusive="left") | posting_hour.between(0, 6, inclusive="left")
    return abnormal


def _is_high_risk_account(
    df: pd.DataFrame,
    *,
    exact_accounts: tuple[str, ...],
    account_prefixes: tuple[str, ...],
) -> pd.Series:
    """Return rows touching configured high-risk accounts."""

    if "gl_account" not in df.columns:
        return pd.Series(False, index=df.index)
    gl = _normalized_account_code(df["gl_account"])
    mask = pd.Series(False, index=df.index)
    if exact_accounts:
        mask = mask | gl.isin(exact_accounts)
    if account_prefixes:
        mask = mask | gl.str.startswith(account_prefixes)
    return mask


def _high_risk_account_match_annotations(
    df: pd.DataFrame,
    *,
    exact_accounts: tuple[str, ...],
    account_prefixes: tuple[str, ...],
    sensitive_account_groups: dict[str, dict[str, tuple[str, ...]]],
) -> tuple[pd.Series, dict[int, dict[str, str]], dict[str, object]]:
    """Return L3-10 mask plus per-row match annotations."""

    if "gl_account" not in df.columns:
        return pd.Series(False, index=df.index), {}, {"exact": 0, "prefix": 0}

    gl = _normalized_account_code(df["gl_account"])
    exact_mask = gl.isin(exact_accounts) if exact_accounts else pd.Series(False, index=df.index)
    prefix_mask = (
        gl.str.startswith(account_prefixes) if account_prefixes else pd.Series(False, index=df.index)
    )
    mask = exact_mask | prefix_mask

    annotations: dict[int, dict[str, str]] = {}
    for row_index in df.index[mask]:
        gl_value = gl.loc[row_index]
        row = df.loc[row_index]
        matched_group = _matched_high_risk_group(
            gl_value,
            exact_accounts=exact_accounts,
            account_prefixes=account_prefixes,
            sensitive_account_groups=sensitive_account_groups,
        )
        signal_category, category_reason = _high_risk_account_signal_category(row)
        if exact_mask.loc[row_index]:
            matched_value = next((account for account in exact_accounts if gl_value == account), "")
            annotations[int(row_index)] = {
                "match_type": "exact",
                "matched_value": matched_value,
                "matched_group": matched_group,
                "signal_category": signal_category,
                "category_reason": category_reason,
            }
            continue

        matched_prefix = next(
            (prefix for prefix in account_prefixes if gl_value.startswith(prefix)),
            "",
        )
        annotations[int(row_index)] = {
            "match_type": "prefix",
            "matched_value": matched_prefix,
            "matched_group": matched_group,
            "signal_category": signal_category,
            "category_reason": category_reason,
        }

    breakdown = {
        "exact": int(exact_mask.sum()),
        "prefix": int((prefix_mask & ~exact_mask).sum()),
    }
    category_counts: dict[str, int] = {}
    for annotation in annotations.values():
        category = annotation.get("signal_category", "raw_signal")
        category_counts[category] = category_counts.get(category, 0) + 1
    breakdown["category_counts"] = category_counts
    return mask, annotations, breakdown


def _high_risk_account_signal_category(row: pd.Series) -> tuple[str, str]:
    """Classify L3-10 output without narrowing the raw signal."""

    priority_reasons: list[str] = []

    source = str(row.get("source", "")).strip().lower()
    if source in {"manual", "adjustment"}:
        priority_reasons.append("manual_or_adjustment")
    if bool(row.get("is_manual_je", False)):
        priority_reasons.append("manual_entry")

    if bool(row.get("exceeds_threshold", False)):
        priority_reasons.append("high_amount")
    if bool(row.get("is_uncleared", False)):
        priority_reasons.append("uncleared")
    if "is_cleared" in row.index and not bool(row.get("is_cleared")):
        priority_reasons.append("uncleared")

    settlement_status = str(row.get("settlement_status", "")).strip().lower()
    if settlement_status and settlement_status not in {"settled", "cleared", "closed", "resolved", "matched"}:
        priority_reasons.append("uncleared")

    if bool(row.get("has_missing_approval_date", False)):
        priority_reasons.append("missing_approval_date")
    if _row_missing_approval_date(row):
        priority_reasons.append("missing_approval_date")

    for column, reason in (
        ("is_period_end", "period_end"),
        ("is_after_hours", "after_hours"),
        ("is_weekend", "weekend"),
        ("is_holiday", "holiday"),
    ):
        if bool(row.get(column, False)):
            priority_reasons.append(reason)

    if priority_reasons:
        return "priority_case", ",".join(sorted(set(priority_reasons)))

    if source in {"automated", "recurring", "batch", "interface", "system"}:
        return "normal_control_candidate", "routine_source"
    return "raw_signal", "sensitive_account_touch"


def _row_missing_approval_date(row: pd.Series) -> bool:
    approved_by = str(row.get("approved_by", "")).strip().lower()
    approval_date = str(row.get("approval_date", "")).strip().lower()
    if approved_by in {"", "nan", "nat", "none"}:
        return False
    if approval_date in {"", "nan", "nat", "none"}:
        return True
    return False


def _matched_high_risk_group(
    gl_value: str,
    *,
    exact_accounts: tuple[str, ...],
    account_prefixes: tuple[str, ...],
    sensitive_account_groups: dict[str, dict[str, tuple[str, ...]]],
) -> str:
    """Return configured sensitive-account group name for a matched account."""

    for group_name, group_cfg in sensitive_account_groups.items():
        if gl_value in group_cfg.get("accounts", ()):
            return group_name
        prefixes = group_cfg.get("account_prefixes", ())
        if prefixes and gl_value.startswith(prefixes):
            return group_name

    if gl_value in exact_accounts:
        return "custom_exact_accounts"
    if account_prefixes and gl_value.startswith(account_prefixes):
        return "custom_prefix_accounts"
    return ""


def _get_high_risk_account_config(
    audit_rules: dict | None = None,
) -> dict[str, object]:
    """Load standalone high-risk account policy, falling back to legacy config."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    standalone = patterns.get("high_risk_account_use", {})
    legacy = patterns.get("self_approval_immediate_override", {})
    groups_raw = standalone.get("sensitive_account_groups", {})
    groups: dict[str, dict[str, tuple[str, ...]]] = {}
    for group_name, group_cfg in groups_raw.items():
        if not isinstance(group_cfg, dict):
            continue
        groups[str(group_name).strip().lower()] = {
            "accounts": tuple(str(v).strip().lower() for v in group_cfg.get("accounts", [])),
            "account_prefixes": tuple(
                str(v).strip().lower() for v in group_cfg.get("account_prefixes", [])
            ),
        }
    return {
        "accounts": tuple(
            str(v).strip().lower()
            for v in standalone.get("accounts", legacy.get("high_risk_accounts", ["1190", "2190"]))
        ),
        "account_prefixes": tuple(
            str(v).strip().lower()
            for v in standalone.get(
                "account_prefixes",
                legacy.get("high_risk_account_prefixes", ["111", "112", "113"]),
            )
        ),
        "sensitive_account_groups": groups,
    }


def b12_missing_approval_date(df: pd.DataFrame) -> pd.Series:
    """L1-09 approval date missing while an approver is present."""

    if "approved_by" not in df.columns or "approval_date" not in df.columns:
        return pd.Series(False, index=df.index)
    has_approver = _normalized_text(df["approved_by"]).ne("")
    missing_date = _normalized_text(df["approval_date"]).eq("")
    return has_approver & missing_date


def b13_high_risk_account_use(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L3-10 standalone high-risk account usage."""

    cfg = _get_high_risk_account_config(audit_rules)
    result, annotations, reason_counts = _high_risk_account_match_annotations(
        df,
        exact_accounts=cfg["accounts"],
        account_prefixes=cfg["account_prefixes"],
        sensitive_account_groups=cfg["sensitive_account_groups"],
    )
    result.attrs["row_annotations"] = annotations
    result.attrs["breakdown"] = {"reason_counts": reason_counts}
    return result


def _self_approval_review_mask(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """Return rows that should be surfaced as review-required self-approval."""

    review = _get_self_approval_review_config(audit_rules)
    mask = pd.Series(False, index=df.index)

    if "business_process" in df.columns and review["business_processes"]:
        mask = mask | _normalized_text(df["business_process"]).isin(review["business_processes"])
    if "document_type" in df.columns and review["document_types"]:
        mask = mask | _normalized_text(df["document_type"]).isin(review["document_types"])
    if "company_code" in df.columns and review["company_codes"]:
        mask = mask | _normalized_text(df["company_code"]).isin(review["company_codes"])

    return mask


def _self_approval_immediate_override_mask(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> tuple[pd.Series, dict[str, int]]:
    """Return review-to-immediate escalation mask and reason counts."""

    override = _get_self_approval_immediate_override_config(audit_rules)
    materiality_amount = float(override["materiality_amount"])
    manual_mask = _is_manual_source(df, override["manual_sources"])

    materiality_mask = pd.Series(False, index=df.index)
    if materiality_amount > 0:
        materiality_mask = manual_mask & (_line_amount(df) >= materiality_amount)

    abnormal_time_mask = _is_abnormal_self_approval_time(df)
    high_risk_account_mask = _is_high_risk_account(
        df,
        exact_accounts=override["high_risk_accounts"],
        account_prefixes=override["high_risk_account_prefixes"],
    )

    escalated = materiality_mask | abnormal_time_mask | high_risk_account_mask
    reason_counts = {
        "materiality_rows": int(materiality_mask.sum()),
        "abnormal_time_rows": int(abnormal_time_mask.sum()),
        "high_risk_account_rows": int(high_risk_account_mask.sum()),
        "escalated_rows": int(escalated.sum()),
    }
    return escalated, reason_counts


def _posting_month(df: pd.DataFrame) -> pd.Series:
    """Return posting month in YYYY-MM form, or 'unknown' when unavailable."""

    if "posting_date" not in df.columns:
        return pd.Series("unknown", index=df.index)
    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    return posting_date.dt.strftime("%Y-%m").fillna("unknown")


def _display_text(series: pd.Series, fallback: str = "unknown") -> pd.Series:
    """Return stripped strings for display, replacing blanks with fallback."""

    text = series.fillna("").astype(str).str.strip()
    return text.mask(text.eq(""), fallback)


def _build_self_approval_group_summary(
    df: pd.DataFrame,
    *,
    flagged: pd.Series,
    immediate: pd.Series,
    review: pd.Series,
    high_amount: pd.Series,
    abnormal_time: pd.Series,
    high_risk_account: pd.Series,
    sensitive_process: pd.Series,
) -> dict[str, object]:
    """Build grouped L1-05 output for queue-style review without narrowing recall."""

    if not flagged.any():
        return {
            "group_key": ["created_by", "business_process", "posting_month"],
            "queue_counts": {},
            "top_groups": [],
        }

    doc_key = (
        _display_text(df["document_id"], fallback="row")
        if "document_id" in df.columns
        else df.index.astype(str).to_series(index=df.index)
    )
    created_by = _display_text(df["created_by"], fallback="unknown")
    business_process = (
        _display_text(df["business_process"], fallback="UNKNOWN")
        if "business_process" in df.columns
        else pd.Series("UNKNOWN", index=df.index)
    )
    posting_month = _posting_month(df)
    amount = _line_amount(df)

    grouped = pd.DataFrame({
        "document_id": doc_key,
        "created_by": created_by,
        "business_process": business_process,
        "posting_month": posting_month,
        "amount": amount,
        "level": pd.Series("review", index=df.index).mask(immediate, "immediate"),
        "high_amount": high_amount,
        "abnormal_time": abnormal_time,
        "high_risk_account": high_risk_account,
        "sensitive_process": sensitive_process,
    }, index=df.index).loc[flagged].copy()

    grouped["additional_signal_count"] = grouped[
        ["high_amount", "abnormal_time", "high_risk_account", "sensitive_process"]
    ].astype(int).sum(axis=1)
    grouped["multi_signal_2plus"] = grouped["additional_signal_count"] >= 2
    grouped["other_self_approval"] = grouped["additional_signal_count"] == 0

    doc_level = grouped.groupby(
        ["created_by", "business_process", "posting_month", "document_id"],
        as_index=False,
        dropna=False,
    ).agg(
        level=("level", lambda s: "immediate" if (s == "immediate").any() else "review"),
        amount=("amount", "max"),
        high_amount=("high_amount", "max"),
        abnormal_time=("abnormal_time", "max"),
        high_risk_account=("high_risk_account", "max"),
        sensitive_process=("sensitive_process", "max"),
        multi_signal_2plus=("multi_signal_2plus", "max"),
        other_self_approval=("other_self_approval", "max"),
    )

    immediate_sensitive = doc_level["level"].eq("immediate") & doc_level["sensitive_process"]
    review_closing = doc_level["level"].eq("review") & doc_level["business_process"].isin(["R2R", "A2R"])
    doc_level["queue_bucket"] = "general_review"
    doc_level.loc[doc_level["level"].eq("immediate"), "queue_bucket"] = "general_immediate"
    doc_level.loc[review_closing, "queue_bucket"] = "closing_review"
    doc_level.loc[immediate_sensitive, "queue_bucket"] = "operational_immediate"

    group_summary = doc_level.groupby(
        ["created_by", "business_process", "posting_month", "queue_bucket"],
        as_index=False,
        dropna=False,
    ).agg(
        total_docs=("document_id", "nunique"),
        total_amount=("amount", "sum"),
        immediate_docs=("level", lambda s: int((s == "immediate").sum())),
        review_docs=("level", lambda s: int((s == "review").sum())),
        multi_signal_2plus=("multi_signal_2plus", "sum"),
        high_amount=("high_amount", "sum"),
        abnormal_time=("abnormal_time", "sum"),
        high_risk_account=("high_risk_account", "sum"),
        sensitive_process=("sensitive_process", "sum"),
        other_self_approval=("other_self_approval", "sum"),
    )
    group_summary = group_summary.sort_values(
        ["total_docs", "total_amount", "immediate_docs"],
        ascending=[False, False, False],
    )

    queue_counts = (
        group_summary.groupby("queue_bucket")["total_docs"]
        .sum()
        .sort_values(ascending=False)
        .to_dict()
    )
    top_groups = group_summary.head(20).to_dict(orient="records")
    return {
        "group_key": ["created_by", "business_process", "posting_month"],
        "queue_counts": queue_counts,
        "top_groups": top_groups,
    }


def b06_self_approval(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L1-05 self approval: same person prepared and approved the entry.

    L1-05 only evaluates observed self-approval facts. Missing approval is handled by
    L1-07, so this rule never infers self-approval from manual source alone.
    System-driven entries can be allowed, while human self-approval is always surfaced
    as either immediate violation or review-required.
    """

    required = {"created_by", "approved_by"}
    if not required.issubset(df.columns):
        return pd.Series(False, index=df.index)

    creator = _normalized_text(df["created_by"])
    approver = _normalized_text(df["approved_by"])
    same_person = creator.ne("") & approver.ne("") & creator.eq(approver)

    allow = _get_self_approval_allow_config(audit_rules)
    allowed = pd.Series(False, index=df.index)

    if "user_persona" in df.columns and allow["user_personas"]:
        allowed = allowed | _normalized_text(df["user_persona"]).isin(allow["user_personas"])
    if "source" in df.columns and allow["sources"]:
        allowed = allowed | _normalized_text(df["source"]).isin(allow["sources"])
    if "company_code" in df.columns and allow["company_codes"]:
        allowed = allowed | _normalized_text(df["company_code"]).isin(allow["company_codes"])

    flagged = same_person & ~allowed
    review_base = flagged & _self_approval_review_mask(df, audit_rules)
    override_immediate, override_counts = _self_approval_immediate_override_mask(df, audit_rules)
    high_amount = pd.Series(False, index=df.index)
    if float(_get_self_approval_immediate_override_config(audit_rules)["materiality_amount"]) > 0:
        override_cfg = _get_self_approval_immediate_override_config(audit_rules)
        high_amount = _is_manual_source(df, override_cfg["manual_sources"]) & (
            _line_amount(df) >= float(override_cfg["materiality_amount"])
        )
        abnormal_time = _is_abnormal_self_approval_time(df)
        high_risk_account = _is_high_risk_account(
            df,
            exact_accounts=override_cfg["high_risk_accounts"],
            account_prefixes=override_cfg["high_risk_account_prefixes"],
        )
    else:
        override_cfg = _get_self_approval_immediate_override_config(audit_rules)
        abnormal_time = _is_abnormal_self_approval_time(df)
        high_risk_account = _is_high_risk_account(
            df,
            exact_accounts=override_cfg["high_risk_accounts"],
            account_prefixes=override_cfg["high_risk_account_prefixes"],
        )
    review = review_base & ~override_immediate
    immediate = flagged & ~review
    process_series = (
        _normalized_process(df["business_process"])
        if "business_process" in df.columns
        else pd.Series("", index=df.index)
    )
    sensitive_process = process_series.isin(["TRE", "P2P", "H2R"])
    observed_summary = _build_self_approval_group_summary(
        df,
        flagged=flagged,
        immediate=immediate,
        review=review,
        high_amount=high_amount,
        abnormal_time=abnormal_time,
        high_risk_account=high_risk_account,
        sensitive_process=sensitive_process,
    )

    flagged.attrs["score_series"] = flagged.astype(float) * 0.6
    flagged.attrs["breakdown"] = {
        "immediate_rows": int(immediate.sum()),
        "review_rows": int(review.sum()),
        "immediate_indices": [int(idx) for idx in immediate[immediate].index],
        "review_indices": [int(idx) for idx in review[review].index],
        "immediate_label": "immediate",
        "review_label": "review",
        "override_counts": override_counts,
        "observed_summary": observed_summary,
    }
    return flagged


def _get_sod_config(audit_rules: dict | None = None) -> tuple[list[frozenset[str]], dict[str, int]]:
    """Load SoD config: toxic pairs + role thresholds."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})

    raw_pairs = patterns.get(
        "sod_toxic_pairs",
        [
            ["TRE", "P2P"],
            ["TRE", "O2C"],
            ["TRE", "H2R"],
            ["R2R", "TRE"],
            ["R2R", "P2P"],
            ["R2R", "O2C"],
        ],
    )
    toxic_pairs = [
        frozenset(str(v).strip().upper() for v in pair if str(v).strip())
        for pair in raw_pairs
    ]

    role_thresholds = patterns.get(
        "sod_role_thresholds",
        {
            "junior_accountant": 1,
            "senior_accountant": 3,
        },
    )

    return toxic_pairs, role_thresholds


def _get_sod_it_admin_config(audit_rules: dict | None = None) -> dict[str, tuple[str, ...] | float]:
    """Load IT super-user high-risk posting policy for L1-06."""

    rules = audit_rules or get_audit_rules()
    cfg = rules.get("patterns", {}).get("sod_it_admin", {})
    return {
        "user_personas": tuple(
            str(v).strip().lower()
            for v in cfg.get(
                "user_personas",
                ["it_admin", "system_admin", "admin", "super_user", "superuser", "it_super_user"],
            )
        ),
        "business_processes": tuple(
            str(v).strip().upper()
            for v in cfg.get("business_processes", ["TRE", "P2P", "O2C", "H2R"])
        ),
        "materiality_amount": float(cfg.get("materiality_amount", 0.0)),
    }


def _get_sod_human_filter_config(audit_rules: dict | None = None) -> dict[str, tuple[str, ...]]:
    """Load system-account filters that should be excluded from human SoD logic."""

    rules = audit_rules or get_audit_rules()
    cfg = rules.get("patterns", {}).get("sod_human_filter", {})
    return {
        "system_sources": tuple(
            str(v).strip().lower()
            for v in cfg.get("system_sources", ["automated", "interface", "system", "batch"])
        ),
        "system_actor_tokens": tuple(
            str(v).strip().lower()
            for v in cfg.get(
                "system_actor_tokens",
                ["batch", "system", "auto", "interface", "if_", "svc_", "_svc"],
            )
        ),
    }


def _get_sod_mitigating_roles(audit_rules: dict | None = None) -> tuple[str, ...]:
    """Load roles that mitigate review-only R2R SoD findings."""

    rules = audit_rules or get_audit_rules()
    cfg = rules.get("patterns", {}).get("sod_mitigating_roles", {})
    return tuple(
        str(v).strip().lower()
        for v in cfg.get("user_personas", ["controller", "manager"])
    )


def _human_sod_mask(df: pd.DataFrame, audit_rules: dict | None = None) -> pd.Series:
    """Return rows treated as human activity for SoD analysis."""

    mask = pd.Series(True, index=df.index)
    cfg = _get_sod_human_filter_config(audit_rules)

    if "user_persona" in df.columns:
        persona_norm = _normalized_persona(df["user_persona"])
        mask = mask & (persona_norm != "automated_system")

    if "source" in df.columns and cfg["system_sources"]:
        mask = mask & ~_normalized_text(df["source"]).isin(cfg["system_sources"])

    if "created_by" in df.columns and cfg["system_actor_tokens"]:
        actor_norm = _normalized_actor(df["created_by"])
        system_actor = pd.Series(False, index=df.index)
        for token in cfg["system_actor_tokens"]:
            if token:
                system_actor = system_actor | actor_norm.str.contains(token, regex=False)
        mask = mask & ~system_actor

    return mask


def _split_sod_pairs(
    toxic_pairs: list[frozenset[str]],
) -> tuple[list[frozenset[str]], list[frozenset[str]]]:
    """Split configured SoD pairs into immediate-violation vs review buckets.

    Current policy:
      - pairs involving R2R are review-required signals
      - all other configured pairs are immediate violations
    """

    immediate_pairs: list[frozenset[str]] = []
    review_pairs: list[frozenset[str]] = []
    for pair in toxic_pairs:
        if "R2R" in pair:
            review_pairs.append(pair)
        else:
            immediate_pairs.append(pair)
    return immediate_pairs, review_pairs


def _self_approval_mask(df: pd.DataFrame) -> pd.Series:
    """Return rows where preparer and approver are the same human user."""

    if "created_by" not in df.columns or "approved_by" not in df.columns:
        return pd.Series(False, index=df.index)
    created = _normalized_actor(df["created_by"])
    approved = _normalized_actor(df["approved_by"])
    return (created != "") & (created == approved)


def manual_override_signal_mask(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """Return manual-entry control-circumvention rows used as L1-06 corroboration."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    manual_sources = tuple(
        str(v).strip().lower()
        for v in patterns.get("manual_source_codes", ["manual", "adjustment"])
    )

    if "is_manual_je" in df.columns:
        manual_entry = df["is_manual_je"].fillna(False).astype(bool)
    elif "source" in df.columns:
        manual_entry = _is_manual_source(df, manual_sources)
    else:
        return pd.Series(False, index=df.index)

    no_approver = pd.Series(False, index=df.index)
    if "approved_by" in df.columns:
        no_approver = _normalized_text(df["approved_by"]).eq("")

    no_approval_date = pd.Series(False, index=df.index)
    if "approval_date" in df.columns:
        no_approval_date = _normalized_text(df["approval_date"]).eq("")

    abnormal_time = _is_abnormal_self_approval_time(df)
    period_end = (
        df["is_period_end"].fillna(False).astype(bool)
        if "is_period_end" in df.columns
        else pd.Series(False, index=df.index)
    )
    suspense_account = (
        df["is_suspense_account"].fillna(False).astype(bool)
        if "is_suspense_account" in df.columns
        else pd.Series(False, index=df.index)
    )
    missing_or_corrupted_description = (
        _normalized_text(df["description_quality"]).isin(("missing", "corrupted", "poor"))
        if "description_quality" in df.columns
        else pd.Series(False, index=df.index)
    )
    override_cfg = _get_self_approval_immediate_override_config(audit_rules)
    high_risk_account = _is_high_risk_account(
        df,
        exact_accounts=override_cfg["high_risk_accounts"],
        account_prefixes=override_cfg["high_risk_account_prefixes"],
    )

    corroborating_signal = (
        no_approver
        | no_approval_date
        | abnormal_time
        | period_end
        | suspense_account
        | missing_or_corrupted_description
        | high_risk_account
    )
    return manual_entry & corroborating_signal


def b07_segregation_of_duties(
    df: pd.DataFrame,
    sod_threshold: int = 3,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L1-06 segregation-of-duties signal with candidate/review/immediate split.

    Immediate violation:
      - direct within-process SoD conflict markers
      - configured toxic pairs outside R2R review scope
      - IT super-user monetary postings in protected processes
      - review signals corroborated by self-approval or skipped approval

    Review required:
      - configured R2R-related SoD pairs
      - role-threshold excess by persona
      - manual-override overlap as a supporting signal only
    """

    required = ["created_by", "business_process"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    toxic_pairs, role_thresholds = _get_sod_config(audit_rules)
    it_admin_cfg = _get_sod_it_admin_config(audit_rules)
    immediate_pairs, review_pairs = _split_sod_pairs(toxic_pairs)
    result = pd.Series(False, index=df.index)

    persona_norm = (
        _normalized_persona(df["user_persona"])
        if "user_persona" in df.columns
        else pd.Series("", index=df.index)
    )
    human_mask = _human_sod_mask(df, audit_rules)

    human_df = df[human_mask]
    if human_df.empty:
        return result

    normalized_process = _normalized_process(human_df["business_process"])
    user_processes = normalized_process.groupby(human_df["created_by"]).apply(
        lambda x: frozenset(v for v in x.unique() if v)
    )

    immediate_users: set[str] = set()
    for user, procs in user_processes.items():
        for pair in immediate_pairs:
            if pair.issubset(procs):
                immediate_users.add(user)
                break

    review_users: set[str] = set()
    for user, procs in user_processes.items():
        for pair in review_pairs:
            if pair.issubset(procs):
                review_users.add(user)
                break

    immediate_mask = pd.Series(False, index=df.index)
    review_mask = pd.Series(False, index=df.index)
    if immediate_users:
        immediate_mask = human_mask & df["created_by"].isin(immediate_users)
    if review_users:
        review_mask = human_mask & df["created_by"].isin(review_users)

    within_process_conflict = pd.Series(False, index=df.index)
    if "sod_conflict_type" in df.columns:
        within_process_conflict = (
            human_mask
            & df["sod_conflict_type"].notna()
            & (df["sod_conflict_type"].astype(str).str.strip() != "")
        )
        immediate_mask = immediate_mask | within_process_conflict

    it_admin_high_risk = pd.Series(False, index=df.index)
    if "user_persona" in df.columns:
        protected_processes = set(it_admin_cfg["business_processes"])
        if protected_processes:
            process_norm = _normalized_process(df["business_process"])
            protected_mask = process_norm.isin(protected_processes)
        else:
            protected_mask = pd.Series(True, index=df.index)

        amount_mask = _line_amount(df) > 0
        materiality_amount = float(it_admin_cfg["materiality_amount"])
        if materiality_amount > 0:
            amount_mask = amount_mask & (_line_amount(df) >= materiality_amount)

        it_admin_persona = persona_norm.isin(it_admin_cfg["user_personas"])
        it_admin_high_risk = human_mask & it_admin_persona & protected_mask & amount_mask
        immediate_mask = immediate_mask | it_admin_high_risk

    if "user_persona" in df.columns and role_thresholds:
        counts = human_df.groupby("created_by")["business_process"].nunique()
        persona_map = _normalized_persona(
            human_df.drop_duplicates("created_by").set_index("created_by")["user_persona"]
        )

        role_violators: set[str] = set()
        for user, count in counts.items():
            persona = persona_map.get(user)
            if persona and persona in role_thresholds and count > role_thresholds[persona]:
                role_violators.add(user)
        if role_violators:
            review_mask = review_mask | (human_mask & df["created_by"].isin(role_violators))
    else:
        counts = human_df.groupby("created_by")["business_process"].nunique()
        violators = counts[counts >= sod_threshold].index
        review_mask = review_mask | (human_mask & df["created_by"].isin(violators))

    if "exceeds_threshold" in df.columns:
        review_mask = review_mask & df["exceeds_threshold"].fillna(False).astype(bool)

    mitigating_roles = _get_sod_mitigating_roles(audit_rules)
    if mitigating_roles and "user_persona" in df.columns:
        review_mask = review_mask & ~persona_norm.isin(mitigating_roles)

    self_approval = human_mask & _self_approval_mask(df)
    skipped_approval = human_mask & b09_skipped_approval(df, audit_rules=audit_rules)
    manual_override = human_mask & manual_override_signal_mask(df, audit_rules=audit_rules)
    corroboration_mask = self_approval | skipped_approval | manual_override
    corroborated_review = review_mask & corroboration_mask

    immediate_mask = immediate_mask | corroborated_review
    review_mask = review_mask & ~immediate_mask
    result = immediate_mask | review_mask
    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[review_mask] = 0.4
    score_series.loc[immediate_mask] = 0.8

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "immediate_rows": int(immediate_mask.sum()),
        "review_rows": int(review_mask.sum()),
        "immediate_users": len(immediate_users),
        "review_users": len(review_users),
        "immediate_pairs": [sorted(pair) for pair in immediate_pairs],
        "review_pairs": [sorted(pair) for pair in review_pairs],
        "within_process_conflict_rows": int(within_process_conflict.sum()),
        "it_admin_high_risk_rows": int(it_admin_high_risk.sum()),
        "corroborated_review_rows": int(corroborated_review.sum()),
        "self_approval_rows": int(self_approval.sum()),
        "skipped_approval_rows": int(skipped_approval.sum()),
        "manual_override_rows": int(manual_override.sum()),
    }
    return result


def b09_skipped_approval(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L1-07 skipped approval: approval required but approver missing."""

    if "exceeds_threshold" not in df.columns or "source" not in df.columns:
        return pd.Series(False, index=df.index)

    cfg = _get_skipped_approval_immediate_config(audit_rules)
    exceeds = df["exceeds_threshold"].fillna(False).astype(bool)
    source_norm = _normalized_text(df["source"])
    not_automated = source_norm.ne("automated")
    no_approval = pd.Series(True, index=df.index, dtype=bool)
    if "approved_by" in df.columns:
        no_approval = df["approved_by"].isna() | (df["approved_by"].astype(str).str.strip() == "")
    candidate = exceeds & not_automated & no_approval

    manual_source = source_norm.isin(cfg["manual_sources"])
    no_approval_date = pd.Series(False, index=df.index, dtype=bool)
    if "approval_date" in df.columns:
        no_approval_date = df["approval_date"].isna() | (
            df["approval_date"].astype(str).str.strip() == ""
        )
    manual_entry = (
        df["is_manual_je"].fillna(False).astype(bool)
        if "is_manual_je" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )
    abnormal_time = _is_abnormal_self_approval_time(df)
    high_risk_process = (
        _normalized_process(df["business_process"]).isin(cfg["business_processes"])
        if "business_process" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )
    high_approval_level = (
        pd.to_numeric(df["approval_level"], errors="coerce").fillna(0).astype(int).ge(2)
        if "approval_level" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )

    evidence_count = (
        manual_source.astype(int)
        + no_approval_date.astype(int)
        + manual_entry.astype(int)
        + abnormal_time.astype(int)
        + high_risk_process.astype(int)
        + high_approval_level.astype(int)
    )
    immediate = candidate & manual_source & evidence_count.ge(int(cfg["min_evidence_count"]))
    review = candidate & ~immediate

    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[review] = 0.4
    score_series.loc[immediate] = 0.8

    candidate.attrs["score_series"] = score_series
    candidate.attrs["breakdown"] = {
        "immediate_rows": int(immediate.sum()),
        "review_rows": int(review.sum()),
        "immediate_indices": [int(idx) for idx in immediate[immediate].index],
        "review_indices": [int(idx) for idx in review[review].index],
        "immediate_label": "immediate",
        "review_label": "review",
        "manual_source_rows": int((candidate & manual_source).sum()),
        "no_approval_date_rows": int((candidate & no_approval_date).sum()),
        "manual_entry_rows": int((candidate & manual_entry).sum()),
        "abnormal_time_rows": int((candidate & abnormal_time).sum()),
        "high_risk_process_rows": int((candidate & high_risk_process).sum()),
        "high_approval_level_rows": int((candidate & high_approval_level).sum()),
        "min_evidence_count": int(cfg["min_evidence_count"]),
    }
    return candidate


def b10_intercompany_review_signal(df: pd.DataFrame) -> pd.Series:
    """L3-03 related-party transaction review signal.

    Phase 1 only identifies entries posted to configured intercompany account
    prefixes. It does not prove a circular transaction; N-hop circular flow is
    handled by GR01 in GraphDetector.
    """

    if "is_intercompany" not in df.columns:
        return pd.Series(False, index=df.index)

    ic_mask = df["is_intercompany"].fillna(False)
    if not ic_mask.any():
        return pd.Series(False, index=df.index)

    if "company_code" in df.columns:
        ic_companies = set(df.loc[ic_mask, "company_code"].dropna().unique())
        if len(ic_companies) < 2:
            return ic_mask

    return ic_mask


# Backward-compatible name retained for existing imports/tests.
b10_circular_intercompany = b10_intercompany_review_signal
