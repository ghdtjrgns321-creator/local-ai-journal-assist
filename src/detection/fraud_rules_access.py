"""Access-control-based fraud rules: L1-05, L1-06, L1-07, L3-03."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config.settings import get_audit_rules


@dataclass
class AccessRuleCache:
    """Reusable normalized Series and masks for access-control rules."""

    text: dict[str, pd.Series] = field(default_factory=dict)
    persona: dict[str, pd.Series] = field(default_factory=dict)
    process: dict[str, pd.Series] = field(default_factory=dict)
    actor: dict[str, pd.Series] = field(default_factory=dict)
    account: dict[str, pd.Series] = field(default_factory=dict)
    bool_masks: dict[str, pd.Series] = field(default_factory=dict)
    objects: dict[str, object] = field(default_factory=dict)


def build_access_rule_cache(df: pd.DataFrame) -> AccessRuleCache:
    """Create a cache shared by L1-05/L1-06/L1-07 during a FraudLayer run."""

    return AccessRuleCache()


def _normalized_text(series: pd.Series) -> pd.Series:
    """Return trimmed lowercase strings with NA handled as empty."""

    normalized = series.where(series.notna(), "").astype(str).str.strip().str.lower()
    return normalized.mask(normalized.isin({"nan", "nat", "none"}), "")


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


def _cached_text(df: pd.DataFrame, column: str, cache: AccessRuleCache | None) -> pd.Series:
    if cache is None:
        return _normalized_text(df[column])
    if column not in cache.text:
        cache.text[column] = _normalized_text(df[column])
    return cache.text[column]


def _cached_persona(df: pd.DataFrame, column: str, cache: AccessRuleCache | None) -> pd.Series:
    if cache is None:
        return _normalized_persona(df[column])
    if column not in cache.persona:
        cache.persona[column] = _cached_text(df, column, cache).str.replace(" ", "_", regex=False)
    return cache.persona[column]


def _cached_process(df: pd.DataFrame, column: str, cache: AccessRuleCache | None) -> pd.Series:
    if cache is None:
        return _normalized_process(df[column])
    if column not in cache.process:
        cache.process[column] = df[column].fillna("").astype(str).str.strip().str.upper()
    return cache.process[column]


def _cached_actor(df: pd.DataFrame, column: str, cache: AccessRuleCache | None) -> pd.Series:
    if cache is None:
        return _normalized_actor(df[column])
    if column not in cache.actor:
        cache.actor[column] = _cached_text(df, column, cache).str.replace(" ", "_", regex=False)
    return cache.actor[column]


def _cached_account(df: pd.DataFrame, column: str, cache: AccessRuleCache | None) -> pd.Series:
    if cache is None:
        return _normalized_account_code(df[column])
    if column not in cache.account:
        cache.account[column] = _cached_text(df, column, cache).str.replace(
            r"\.0+$",
            "",
            regex=True,
        )
    return cache.account[column]


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
    manual_sources = override.get(
        "manual_sources",
        patterns.get("manual_source_codes", ["manual", "adjustment"]),
    )
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
    manual_sources = cfg.get(
        "manual_sources",
        patterns.get("manual_source_codes", ["manual", "adjustment"]),
    )
    return {
        "manual_sources": tuple(str(v).strip().lower() for v in manual_sources),
        "system_sources": tuple(
            str(v).strip().lower()
            for v in cfg.get("system_sources", ["automated", "batch", "interface", "system"])
        ),
        "business_processes": tuple(
            str(v).strip().upper()
            for v in cfg.get("business_processes", ["TRE", "P2P", "O2C", "H2R"])
        ),
        "min_evidence_count": int(cfg.get("min_evidence_count", 2)),
    }


def _get_missing_approval_date_config(
    audit_rules: dict | None = None,
) -> dict[str, tuple[str, ...]]:
    """Load L1-09 queue split policy."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    cfg = patterns.get("missing_approval_date_immediate", {})
    manual_sources = cfg.get(
        "manual_sources",
        patterns.get("manual_source_codes", ["manual", "adjustment"]),
    )
    return {
        "manual_sources": tuple(str(v).strip().lower() for v in manual_sources),
        "system_sources": tuple(
            str(v).strip().lower()
            for v in cfg.get(
                "system_sources",
                ["automated", "batch", "interface", "system", "recurring"],
            )
        ),
        "business_processes": tuple(
            str(v).strip().upper()
            for v in cfg.get("business_processes", ["TRE", "P2P", "O2C", "H2R"])
        ),
    }


def _line_amount(df: pd.DataFrame, cache: AccessRuleCache | None = None) -> pd.Series:
    """Return per-row representative amount for threshold checks."""

    if cache is not None and "line_amount" in cache.bool_masks:
        return cache.bool_masks["line_amount"]
    debit_raw = (
        df["debit_amount"] if "debit_amount" in df.columns else pd.Series(0.0, index=df.index)
    )
    credit_raw = (
        df["credit_amount"] if "credit_amount" in df.columns else pd.Series(0.0, index=df.index)
    )
    debit = pd.to_numeric(debit_raw, errors="coerce").fillna(0.0)
    credit = pd.to_numeric(credit_raw, errors="coerce").fillna(0.0)
    amount = pd.concat([debit, credit], axis=1).max(axis=1)
    if cache is not None:
        cache.bool_masks["line_amount"] = amount
    return amount


def _document_amount(df: pd.DataFrame, cache: AccessRuleCache | None = None) -> pd.Series:
    """Return document-level representative amount when document_id is available."""

    if cache is not None and "document_amount" in cache.bool_masks:
        return cache.bool_masks["document_amount"]

    line_amount = _line_amount(df, cache=cache)
    if "document_id" not in df.columns:
        amount = line_amount
    else:
        doc_id = df["document_id"].fillna("").astype(str)
        amount = line_amount.groupby(doc_id, dropna=False).transform("sum")
    if cache is not None:
        cache.bool_masks["document_amount"] = amount
    return amount


def _is_manual_source(
    df: pd.DataFrame,
    manual_sources: tuple[str, ...],
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """Return rows treated as human/manual entries."""

    if "source" not in df.columns:
        return pd.Series(True, index=df.index)
    if not manual_sources:
        return pd.Series(True, index=df.index)
    key = f"manual_source:{manual_sources!r}"
    if cache is not None and key in cache.bool_masks:
        return cache.bool_masks[key]
    result = _cached_text(df, "source", cache).isin(manual_sources)
    if cache is not None:
        cache.bool_masks[key] = result
    return result


def _is_abnormal_self_approval_time(
    df: pd.DataFrame,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """Return rows posted during weekend/holiday/after-hours windows."""

    if cache is not None and "abnormal_self_approval_time" in cache.bool_masks:
        return cache.bool_masks["abnormal_self_approval_time"]
    abnormal = pd.Series(False, index=df.index)
    if "is_weekend" in df.columns:
        abnormal = abnormal | df["is_weekend"].fillna(False).astype(bool)
    if "is_holiday" in df.columns:
        abnormal = abnormal | df["is_holiday"].fillna(False).astype(bool)
    if "is_after_hours" in df.columns:
        abnormal = abnormal | df["is_after_hours"].fillna(False).astype(bool)
    if "time_zone_category" in df.columns:
        abnormal = abnormal | _cached_text(df, "time_zone_category", cache).isin(
            ("overtime", "midnight")
        )
    if "posting_time" in df.columns:
        posting_hour = pd.to_numeric(df["posting_time"], errors="coerce")
        abnormal = (
            abnormal
            | posting_hour.between(23, 24, inclusive="left")
            | posting_hour.between(0, 6, inclusive="left")
        )
    if cache is not None:
        cache.bool_masks["abnormal_self_approval_time"] = abnormal
    return abnormal


def _is_high_risk_account(
    df: pd.DataFrame,
    *,
    exact_accounts: tuple[str, ...],
    account_prefixes: tuple[str, ...],
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """Return rows touching configured high-risk accounts."""

    if "gl_account" not in df.columns:
        return pd.Series(False, index=df.index)
    key = f"high_risk_account:{exact_accounts!r}:{account_prefixes!r}"
    if cache is not None and key in cache.bool_masks:
        return cache.bool_masks[key]
    gl = _cached_account(df, "gl_account", cache)
    mask = pd.Series(False, index=df.index)
    if exact_accounts:
        mask = mask | gl.isin(exact_accounts)
    if account_prefixes:
        mask = mask | gl.str.startswith(account_prefixes)
    if cache is not None:
        cache.bool_masks[key] = mask
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
        gl.str.startswith(account_prefixes)
        if account_prefixes
        else pd.Series(False, index=df.index)
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
    if settlement_status and settlement_status not in {
        "settled",
        "cleared",
        "closed",
        "resolved",
        "matched",
    }:
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


def _get_work_scope_excess_config(audit_rules: dict | None = None) -> dict[str, object]:
    """Load L3-12 user work-scope concentration policy."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    cfg = patterns.get("work_scope_excess_review", {})
    high_risk = _get_high_risk_account_config(audit_rules)
    manual_sources = cfg.get("manual_sources", patterns.get("manual_source_codes", []))
    if not manual_sources:
        manual_sources = ["manual", "adjustment"]
    system_sources = cfg.get("system_sources", ["automated", "batch", "interface", "system"])
    automated_personas = cfg.get("automated_personas", ["automated_system", "batch_user"])
    admin_personas = cfg.get("admin_personas", ["admin", "superuser", "system_admin"])
    thresholds = cfg.get("persona_thresholds", {})
    return {
        "persona_thresholds": {
            "junior": {"process": 3, "company": 2},
            "staff": {"process": 3, "company": 2},
            "clerk": {"process": 3, "company": 2},
            "senior": {"process": 4, "company": 3},
            "accountant": {"process": 4, "company": 3},
            "manager": {"process": 5, "company": 4},
            "controller": {"process": 5, "company": 4},
            "default": {"process": 4, "company": 3},
            **{
                str(key).strip().lower(): {
                    "process": int(value.get("process", 4)),
                    "company": int(value.get("company", 3)),
                }
                for key, value in thresholds.items()
                if isinstance(value, dict)
            },
        },
        "min_process_info": int(cfg.get("min_process_info", 3)),
        "min_company_combo": int(cfg.get("min_company_combo", 2)),
        "manual_sources": tuple(str(v).strip().lower() for v in manual_sources),
        "system_sources": tuple(str(v).strip().lower() for v in system_sources),
        "automated_personas": tuple(
            str(v).strip().lower().replace(" ", "_") for v in automated_personas
        ),
        "admin_personas": tuple(str(v).strip().lower().replace(" ", "_") for v in admin_personas),
        "sensitive_accounts": high_risk["accounts"],
        "sensitive_account_prefixes": high_risk["account_prefixes"],
    }


def _work_scope_threshold_for_persona(
    persona: str,
    thresholds: dict[str, dict[str, int]],
) -> tuple[int, int, str]:
    """Return process/company thresholds for a normalized persona."""

    for key, values in thresholds.items():
        if key != "default" and key in persona:
            return int(values["process"]), int(values["company"]), key
    default = thresholds["default"]
    return int(default["process"]), int(default["company"]), "default"


def b14_work_scope_excess_review(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L3-12 review signal for one user-year spanning many work areas."""

    if "created_by" not in df.columns or "business_process" not in df.columns:
        return pd.Series(False, index=df.index)

    cfg = _get_work_scope_excess_config(audit_rules)
    user = _normalized_actor(df["created_by"])
    process = _normalized_process(df["business_process"])
    valid = user.ne("") & process.ne("")
    if not valid.any():
        return pd.Series(False, index=df.index)

    persona = (
        _normalized_persona(df["user_persona"])
        if "user_persona" in df.columns
        else pd.Series("", index=df.index)
    )
    company = (
        _normalized_text(df["company_code"])
        if "company_code" in df.columns
        else pd.Series("", index=df.index)
    )
    document_type = (
        _normalized_text(df["document_type"])
        if "document_type" in df.columns
        else pd.Series("", index=df.index)
    )
    source = (
        _normalized_text(df["source"])
        if "source" in df.columns
        else pd.Series("", index=df.index)
    )
    manual_source = source.isin(cfg["manual_sources"])
    system_source = source.isin(cfg["system_sources"])

    gl = (
        _normalized_account_code(df["gl_account"])
        if "gl_account" in df.columns
        else pd.Series("", index=df.index)
    )
    account_group = gl.str[:1].where(gl.ne(""), "")
    sensitive_account = pd.Series(False, index=df.index)
    exact_accounts = tuple(cfg["sensitive_accounts"])
    prefixes = tuple(cfg["sensitive_account_prefixes"])
    if "gl_account" in df.columns:
        if exact_accounts:
            sensitive_account = sensitive_account | gl.isin(exact_accounts)
        if prefixes:
            sensitive_account = sensitive_account | gl.str.startswith(prefixes)

    period_end = (
        df["is_period_end"].fillna(False).astype(bool)
        if "is_period_end" in df.columns
        else pd.Series(False, index=df.index)
    )
    high_amount = (
        df["exceeds_threshold"].fillna(False).astype(bool)
        if "exceeds_threshold" in df.columns
        else pd.Series(False, index=df.index)
    )
    if "amount_zscore" in df.columns:
        high_amount = high_amount | pd.to_numeric(
            df["amount_zscore"],
            errors="coerce",
        ).fillna(0.0).gt(3.0)
    fiscal_year = (
        pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64").astype(str)
        if "fiscal_year" in df.columns
        else pd.Series("", index=df.index)
    )
    fiscal_year = fiscal_year.replace("<NA>", "")

    work = pd.DataFrame(
        {
            "user": user,
            "fiscal_year": fiscal_year,
            "persona": persona,
            "process": process,
            "company": company,
            "document_type": document_type,
            "account_group": account_group,
            "source": source,
            "manual_source": manual_source,
            "system_source": system_source,
            "sensitive_account": sensitive_account,
            "period_end": period_end,
            "high_amount": high_amount,
        },
        index=df.index,
    )

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    review_score_series = pd.Series(0.0, index=df.index, dtype="float64")
    bucket = pd.Series("none", index=df.index, dtype="object")
    raw_candidate = pd.Series(False, index=df.index, dtype="bool")
    row_annotations: dict[int, dict[str, object]] = {}
    user_summaries: dict[str, dict[str, object]] = {}
    bucket_counts: dict[str, int] = {}

    group_keys: str | list[str] = ["fiscal_year", "user"] if "fiscal_year" in df.columns else "user"
    grouped = work.loc[valid].groupby(group_keys, sort=False, dropna=False)
    for group_key, group in grouped:
        if isinstance(group_key, tuple):
            year_value = str(group_key[0])
            user_id = str(group_key[1])
            summary_key = f"{year_value}:{user_id}" if year_value else user_id
        else:
            year_value = ""
            user_id = str(group_key)
            summary_key = user_id
        persona_values = group["persona"][group["persona"].ne("")]
        persona_value = str(persona_values.mode().iloc[0]) if not persona_values.empty else ""
        process_threshold, company_threshold, threshold_key = _work_scope_threshold_for_persona(
            persona_value,
            cfg["persona_thresholds"],
        )
        process_count = int(group["process"][group["process"].ne("")].nunique())
        company_count = int(group["company"][group["company"].ne("")].nunique())
        document_type_count = int(group["document_type"][group["document_type"].ne("")].nunique())
        account_group_count = int(group["account_group"][group["account_group"].ne("")].nunique())
        source_count = int(group["source"][group["source"].ne("")].nunique())
        has_manual = bool(group["manual_source"].any())
        has_sensitive = bool(group["sensitive_account"].any())
        has_period_end = bool(group["period_end"].any())
        has_high_amount = bool(group["high_amount"].any())
        has_system_only = bool(group["system_source"].all()) if len(group) else False
        is_admin = persona_value in cfg["admin_personas"]
        is_automated = persona_value in cfg["automated_personas"] or has_system_only

        reasons: list[str] = []
        if process_count >= cfg["min_process_info"]:
            reasons.append("multi_process")
        if process_count >= process_threshold:
            reasons.append("process_threshold")
        if company_count >= company_threshold:
            reasons.append("company_threshold")
        if process_count >= cfg["min_process_info"] and company_count >= cfg["min_company_combo"]:
            reasons.append("process_company_breadth")
        if has_manual:
            reasons.append("manual_source")
        if has_sensitive:
            reasons.append("sensitive_account")
        if has_period_end:
            reasons.append("period_end")
        if has_high_amount:
            reasons.append("high_amount")

        broad_scope = (
            process_count >= process_threshold
            or company_count >= company_threshold
            or (
                process_count >= cfg["min_process_info"]
                and company_count >= cfg["min_company_combo"]
            )
        )
        info_only = process_count >= cfg["min_process_info"] and not broad_scope
        corroborating_count = int(has_manual) + int(has_sensitive) + int(has_period_end) + int(
            has_high_amount
        )

        is_candidate_user = broad_scope or info_only

        if is_automated and is_candidate_user:
            user_score = 0.30 if has_manual and corroborating_count >= 2 else 0.0
            user_bucket = (
                "system_mixed_scope_review"
                if user_score > 0
                else "system_scope_observation"
            )
        elif is_automated:
            user_score = 0.0
            user_bucket = "none"
        elif is_admin and is_candidate_user and corroborating_count < 2:
            user_score = 0.0
            user_bucket = "admin_scope_observation"
        elif is_admin and not is_candidate_user:
            user_score = 0.0
            user_bucket = "none"
        elif broad_scope and process_count >= 4 and company_count >= 3 and has_manual:
            user_score = 0.55
            user_bucket = "broad_scope_manual"
        elif broad_scope and has_sensitive:
            user_score = 0.50
            user_bucket = "sensitive_scope_concentration"
        elif broad_scope and has_manual:
            user_score = 0.45
            user_bucket = "manual_scope_concentration"
        elif process_count >= 4 or company_count >= 3:
            user_score = 0.35
            user_bucket = "broad_scope_concentration"
        elif broad_scope:
            user_score = 0.30
            user_bucket = "process_company_concentration"
        elif info_only:
            user_score = 0.20
            user_bucket = "scope_observation"
        else:
            user_score = 0.0
            user_bucket = "none"

        if user_score > 0 and not is_automated and not is_admin and corroborating_count >= 2:
            user_score = max(user_score, 0.65)
            user_bucket = "compound_scope_concentration"

        if is_candidate_user:
            user_index = group.index
        else:
            user_index = group.index[:0]

        raw_candidate.loc[user_index] = True
        review_score_series.loc[user_index] = user_score
        bucket.loc[user_index] = user_bucket
        if user_bucket != "none" and len(user_index) > 0:
            bucket_counts[user_bucket] = bucket_counts.get(user_bucket, 0) + len(user_index)
            user_summaries[summary_key] = {
                "fiscal_year": year_value,
                "persona": persona_value,
                "threshold_profile": threshold_key,
                "process_count": process_count,
                "company_count": company_count,
                "document_type_count": document_type_count,
                "account_group_count": account_group_count,
                "source_count": source_count,
                "score": round(float(user_score), 4),
                "bucket": user_bucket,
                "raw_candidate": bool(is_candidate_user),
                "reasons": reasons,
            }
            for idx in user_index:
                row_annotations[int(idx)] = {
                    "user": user_id,
                    "fiscal_year": year_value,
                    "persona": persona_value,
                    "bucket": user_bucket,
                    "score": 0.0,
                    "review_score": round(float(user_score), 4),
                    "process_count": process_count,
                    "company_count": company_count,
                    "document_type_count": document_type_count,
                    "account_group_count": account_group_count,
                    "source_count": source_count,
                    "reasons": reasons,
                    "rule_boundary": (
                        "L1-06 handles direct SoD conflict; L3-12 handles work scope"
                    ),
                }

    result = raw_candidate
    result.attrs["score_series"] = score_series
    result.attrs["review_score_series"] = review_score_series
    result.attrs["breakdown"] = {
        "scoring_unit": "user_year" if "fiscal_year" in df.columns else "user",
        "row_projection_policy": "project_user_year_score_to_current_period_activity_rows"
        if "fiscal_year" in df.columns
        else "project_user_score_to_current_period_activity_rows",
        "candidate_rows": int(result.sum()),
        "candidate_users": int(len(user_summaries)),
        "scored_rows": int(review_score_series.gt(0).sum()),
        "review_scored_rows": int(review_score_series.gt(0).sum()),
        "scored_users": int(sum(1 for item in user_summaries.values() if item["score"] > 0)),
        "bucket_counts": bucket_counts,
        "user_summaries": user_summaries,
        "zero_score_system_rows": int((result & bucket.eq("system_scope_observation")).sum()),
        "zero_score_admin_rows": int((result & bucket.eq("admin_scope_observation")).sum()),
        "excluded_system_rows": 0,
        "excluded_admin_rows": 0,
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def b12_missing_approval_date(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """L1-09 approval date missing, with score split by approval context."""

    if "approval_date" not in df.columns:
        return pd.Series(False, index=df.index)
    cfg = _get_missing_approval_date_config(audit_rules)
    missing_date = _cached_text(df, "approval_date", cache).eq("")
    candidate = missing_date
    if not candidate.any():
        return candidate
    has_approver = (
        _cached_text(df, "approved_by", cache).ne("")
        if "approved_by" in df.columns
        else pd.Series(False, index=df.index)
    )

    if "source" in df.columns:
        source_norm = _cached_text(df, "source", cache)
        system_source = source_norm.isin(cfg["system_sources"])
        manual_source = source_norm.isin(cfg["manual_sources"])
    else:
        source_norm = pd.Series("", index=df.index)
        system_source = pd.Series(False, index=df.index)
        manual_source = pd.Series(True, index=df.index)

    high_risk_process = (
        _cached_process(df, "business_process", cache).isin(cfg["business_processes"])
        if "business_process" in df.columns
        else pd.Series(False, index=df.index)
    )
    high_amount = (
        df["exceeds_threshold"].fillna(False).astype(bool)
        if "exceeds_threshold" in df.columns
        else pd.Series(False, index=df.index)
    )
    manual_entry = (
        df["is_manual_je"].fillna(False).astype(bool)
        if "is_manual_je" in df.columns
        else pd.Series(False, index=df.index)
    )
    manual_context = manual_source | manual_entry
    abnormal_time = _is_abnormal_self_approval_time(df, cache=cache)
    period_end = (
        df["is_period_end"].fillna(False).astype(bool)
        if "is_period_end" in df.columns
        else pd.Series(False, index=df.index)
    )
    high_risk_cfg = _get_high_risk_account_config(audit_rules)
    high_risk_account = _is_high_risk_account(
        df,
        exact_accounts=high_risk_cfg["accounts"],
        account_prefixes=high_risk_cfg["account_prefixes"],
        cache=cache,
    )

    primary_evidence = manual_context | high_risk_process | high_amount
    immediate = candidate & has_approver & ~system_source & primary_evidence
    review = candidate & has_approver & ~immediate
    low_priority = candidate & ~has_approver
    system_review = review & system_source
    weak_review = review & ~system_source

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[immediate] = 0.55
    score_series.loc[immediate & high_amount] = 0.65
    score_series.loc[immediate & manual_context & high_risk_process] = 0.65
    score_series.loc[immediate & high_amount & (manual_context | high_risk_process)] = 0.70
    corroborated = immediate & (
        (high_amount & (period_end | abnormal_time | high_risk_account))
        | (manual_context & high_risk_process & (high_amount | period_end | abnormal_time))
    )
    score_series.loc[corroborated] = 0.80
    review_score_series = pd.Series(0.0, index=df.index, dtype="float64")
    review_score_series.loc[system_review] = 0.25
    review_score_series.loc[
        system_review & (high_amount | high_risk_process | high_risk_account)
    ] = 0.35
    review_score_series.loc[weak_review] = 0.35
    review_score_series.loc[low_priority] = 0.1

    queue_label = pd.Series("none", index=df.index, dtype="object")
    queue_label.loc[low_priority] = "low_priority"
    queue_label.loc[review] = "review"
    queue_label.loc[immediate] = "immediate"

    row_annotations: dict[int, dict[str, object]] = {}
    for idx in candidate[candidate].index:
        evidence_reasons: list[str] = []
        if bool(manual_source.loc[idx]):
            evidence_reasons.append("manual_source")
        if bool(manual_entry.loc[idx]):
            evidence_reasons.append("manual_entry")
        if bool(high_risk_process.loc[idx]):
            evidence_reasons.append("high_risk_process")
        if bool(high_amount.loc[idx]):
            evidence_reasons.append("high_amount")
        if bool(period_end.loc[idx]):
            evidence_reasons.append("period_end")
        if bool(abnormal_time.loc[idx]):
            evidence_reasons.append("abnormal_time")
        if bool(high_risk_account.loc[idx]):
            evidence_reasons.append("high_risk_account")

        if bool(low_priority.loc[idx]):
            score_bucket = "missing_approver"
        elif bool(system_review.loc[idx]):
            score_bucket = "system_review"
        elif bool(weak_review.loc[idx]):
            score_bucket = "weak_review"
        elif float(score_series.loc[idx]) >= 0.80:
            score_bucket = "corroborated_material"
        elif float(score_series.loc[idx]) >= 0.70:
            score_bucket = "material_control_gap"
        elif float(score_series.loc[idx]) >= 0.65:
            score_bucket = "corroborated_control_gap"
        else:
            score_bucket = "single_control_gap"

        annotation: dict[str, object] = {
            "queue_label": str(queue_label.loc[idx]),
            "bucket": score_bucket,
            "score": round(float(score_series.loc[idx]), 4),
            "review_score": round(float(review_score_series.loc[idx]), 4),
            "evidence_count": len(set(evidence_reasons)),
            "evidence_reasons": evidence_reasons,
            "source_category": (
                "missing_approver"
                if not bool(has_approver.loc[idx])
                else "system_review"
                if bool(system_source.loc[idx])
                else "manual"
                if bool(manual_source.loc[idx])
                else "non_system_review"
            ),
        }
        for column in (
            "document_id",
            "source",
            "approved_by",
            "approval_date",
            "business_process",
            "exceeds_threshold",
            "is_manual_je",
            "is_period_end",
            "is_after_hours",
            "is_weekend",
            "is_holiday",
            "time_zone_category",
            "gl_account",
        ):
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        row_annotations[int(idx)] = annotation

    candidate.attrs["score_series"] = score_series
    candidate.attrs["review_score_series"] = review_score_series
    candidate.attrs["breakdown"] = {
        "candidate_rows": int(candidate.sum()),
        "immediate_rows": int(immediate.sum()),
        "review_rows": int(review.sum()),
        "system_review_rows": int(system_review.sum()),
        "weak_review_rows": int(weak_review.sum()),
        "low_priority_rows": int(low_priority.sum()),
        "missing_approver_rows": int((candidate & ~has_approver).sum()),
        "has_approver_rows": int((candidate & has_approver).sum()),
        "manual_source_rows": int((candidate & manual_source).sum()),
        "manual_entry_rows": int((candidate & manual_entry).sum()),
        "system_source_review_rows": int((candidate & system_source).sum()),
        "high_risk_process_rows": int((candidate & high_risk_process).sum()),
        "high_amount_rows": int((candidate & high_amount).sum()),
        "period_end_rows": int((candidate & period_end).sum()),
        "abnormal_time_rows": int((candidate & abnormal_time).sum()),
        "high_risk_account_rows": int((candidate & high_risk_account).sum()),
        "score_bands": {
            f"{float(score):.2f}": int((score_series.eq(score) & candidate).sum())
            for score in sorted(score_series.loc[candidate].unique())
            if float(score) > 0
        },
        "source_counts": source_norm.loc[candidate].value_counts().to_dict(),
    }
    candidate.attrs["row_annotations"] = row_annotations
    return candidate


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
    score_series = pd.Series(0.0, index=df.index)
    category_counts = reason_counts.get("category_counts", {})
    raw_signal_rows = 0
    priority_case_rows = 0
    normal_control_candidate_rows = 0
    for row_index, annotation in annotations.items():
        category = annotation.get("signal_category", "raw_signal")
        if category == "priority_case":
            score_series.loc[row_index] = 0.65
            priority_case_rows += 1
        elif category == "normal_control_candidate":
            score_series.loc[row_index] = 0.20
            normal_control_candidate_rows += 1
        else:
            score_series.loc[row_index] = 0.35
            raw_signal_rows += 1

    result.attrs["score_series"] = score_series
    result.attrs["row_annotations"] = annotations
    result.attrs["breakdown"] = {
        "reason_counts": reason_counts,
        "raw_signal_rows": raw_signal_rows,
        "priority_case_rows": priority_case_rows,
        "normal_control_candidate_rows": normal_control_candidate_rows,
        "category_counts": dict(category_counts) if isinstance(category_counts, dict) else {},
    }
    return result


def _self_approval_review_mask(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """Return rows that should be surfaced as review-required self-approval."""

    review = _get_self_approval_review_config(audit_rules)
    mask = pd.Series(False, index=df.index)

    if "business_process" in df.columns and review["business_processes"]:
        mask = mask | _cached_text(df, "business_process", cache).isin(review["business_processes"])
    if "document_type" in df.columns and review["document_types"]:
        mask = mask | _cached_text(df, "document_type", cache).isin(review["document_types"])
    if "company_code" in df.columns and review["company_codes"]:
        mask = mask | _cached_text(df, "company_code", cache).isin(review["company_codes"])

    return mask


def _self_approval_immediate_override_mask(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> tuple[pd.Series, dict[str, int]]:
    """Return review-to-immediate escalation mask and reason counts."""

    override = _get_self_approval_immediate_override_config(audit_rules)
    materiality_amount = float(override["materiality_amount"])
    manual_mask = _is_manual_source(df, override["manual_sources"], cache=cache)

    materiality_mask = pd.Series(False, index=df.index)
    if materiality_amount > 0:
        materiality_mask = manual_mask & (_line_amount(df, cache=cache) >= materiality_amount)

    abnormal_time_mask = _is_abnormal_self_approval_time(df, cache=cache)
    high_risk_account_mask = _is_high_risk_account(
        df,
        exact_accounts=override["high_risk_accounts"],
        account_prefixes=override["high_risk_account_prefixes"],
        cache=cache,
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
    cache: AccessRuleCache | None = None,
) -> dict[str, object]:
    """Build grouped L1-05 output for queue-style review without narrowing recall."""

    if not flagged.any():
        return {
            "group_key": ["created_by", "business_process", "posting_month"],
            "queue_counts": {},
            "top_groups": [],
        }

    flagged_index = flagged[flagged].index
    doc_key = (
        _display_text(df.loc[flagged_index, "document_id"], fallback="row")
        if "document_id" in df.columns
        else flagged_index.astype(str).to_series(index=flagged_index)
    )
    created_by = _display_text(df.loc[flagged_index, "created_by"], fallback="unknown")
    business_process = (
        _display_text(df.loc[flagged_index, "business_process"], fallback="UNKNOWN")
        if "business_process" in df.columns
        else pd.Series("UNKNOWN", index=flagged_index)
    )
    posting_month = _posting_month(df).loc[flagged_index]
    amount = _line_amount(df, cache=cache).loc[flagged_index]

    grouped = pd.DataFrame({
        "document_id": doc_key,
        "created_by": created_by,
        "business_process": business_process,
        "posting_month": posting_month,
        "amount": amount,
        "level": pd.Series("review", index=flagged_index).mask(
            immediate.loc[flagged_index],
            "immediate",
        ),
        "high_amount": high_amount.loc[flagged_index],
        "abnormal_time": abnormal_time.loc[flagged_index],
        "high_risk_account": high_risk_account.loc[flagged_index],
        "sensitive_process": sensitive_process.loc[flagged_index],
    }, index=flagged_index).copy()

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
    review_closing = doc_level["level"].eq("review") & doc_level["business_process"].isin(
        ["R2R", "A2R"]
    )
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
    cache: AccessRuleCache | None = None,
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

    creator = _cached_text(df, "created_by", cache)
    approver = _cached_text(df, "approved_by", cache)
    same_person = creator.ne("") & approver.ne("") & creator.eq(approver)

    allow = _get_self_approval_allow_config(audit_rules)
    allowed = pd.Series(False, index=df.index)

    if "user_persona" in df.columns and allow["user_personas"]:
        allowed = allowed | _cached_text(df, "user_persona", cache).isin(allow["user_personas"])
    if "source" in df.columns and allow["sources"]:
        allowed = allowed | _cached_text(df, "source", cache).isin(allow["sources"])
    if "company_code" in df.columns and allow["company_codes"]:
        allowed = allowed | _cached_text(df, "company_code", cache).isin(allow["company_codes"])

    # L1-05 first captures every observed self-approval fact. Allowed system
    # cases are retained as candidates/evidence but scored as 0 below.
    flagged = same_person
    actionable = flagged & ~allowed
    review_base = actionable & _self_approval_review_mask(df, audit_rules, cache=cache)
    override_immediate, override_counts = _self_approval_immediate_override_mask(
        df,
        audit_rules,
        cache=cache,
    )
    high_amount = pd.Series(False, index=df.index)
    if float(_get_self_approval_immediate_override_config(audit_rules)["materiality_amount"]) > 0:
        override_cfg = _get_self_approval_immediate_override_config(audit_rules)
        high_amount = _is_manual_source(df, override_cfg["manual_sources"], cache=cache) & (
            _line_amount(df, cache=cache) >= float(override_cfg["materiality_amount"])
        )
        abnormal_time = _is_abnormal_self_approval_time(df, cache=cache)
        high_risk_account = _is_high_risk_account(
            df,
            exact_accounts=override_cfg["high_risk_accounts"],
            account_prefixes=override_cfg["high_risk_account_prefixes"],
            cache=cache,
        )
    else:
        override_cfg = _get_self_approval_immediate_override_config(audit_rules)
        abnormal_time = _is_abnormal_self_approval_time(df, cache=cache)
        high_risk_account = _is_high_risk_account(
            df,
            exact_accounts=override_cfg["high_risk_accounts"],
            account_prefixes=override_cfg["high_risk_account_prefixes"],
            cache=cache,
        )
    review = review_base & ~override_immediate
    immediate = actionable & ~review
    process_series = (
        _cached_process(df, "business_process", cache)
        if "business_process" in df.columns
        else pd.Series("", index=df.index)
    )
    sensitive_process = process_series.isin(["TRE", "P2P", "H2R"])
    observed_summary = _build_self_approval_group_summary(
        df,
        flagged=actionable,
        immediate=immediate,
        review=review,
        high_amount=high_amount,
        abnormal_time=abnormal_time,
        high_risk_account=high_risk_account,
        sensitive_process=sensitive_process,
        cache=cache,
    )

    materiality_escalated = flagged & review_base & high_amount
    abnormal_time_escalated = flagged & review_base & abnormal_time
    high_risk_account_escalated = flagged & review_base & high_risk_account

    bucket = pd.Series("none", index=df.index, dtype="object")
    bucket.loc[same_person & allowed] = "allowed_system"
    bucket.loc[review] = "review"
    bucket.loc[immediate] = "immediate"
    bucket.loc[materiality_escalated] = "escalated_materiality"
    bucket.loc[abnormal_time_escalated] = "escalated_abnormal_time"
    bucket.loc[high_risk_account_escalated] = "escalated_high_risk_account"

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[immediate] = 0.8
    review_score_series = pd.Series(0.0, index=df.index, dtype="float64")
    review_score_series.loc[review] = 0.4

    row_annotations: dict[int, dict[str, object]] = {}
    annotation_columns = (
        "document_id",
        "created_by",
        "approved_by",
        "business_process",
        "source",
        "user_persona",
        "gl_account",
    )
    for idx in flagged[flagged].index:
        override_reasons: list[str] = []
        if bool(high_amount.loc[idx]):
            override_reasons.append("materiality")
        if bool(abnormal_time.loc[idx]):
            override_reasons.append("abnormal_time")
        if bool(high_risk_account.loc[idx]):
            override_reasons.append("high_risk_account")

        annotation: dict[str, object] = {
            "bucket": str(bucket.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
            "review_score": round(float(review_score_series.loc[idx]), 4),
            "override_reasons": override_reasons,
        }
        for column in annotation_columns:
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        row_annotations[int(idx)] = annotation

    flagged.attrs["score_series"] = score_series
    flagged.attrs["review_score_series"] = review_score_series
    flagged.attrs["breakdown"] = {
        "immediate_rows": int(immediate.sum()),
        "review_rows": int(review.sum()),
        "candidate_rows": int(flagged.sum()),
        "actionable_rows": int(actionable.sum()),
        "allowed_system_rows": int((same_person & allowed).sum()),
        "bucket_counts": bucket[bucket.ne("none")].value_counts().to_dict(),
        "immediate_indices": [int(idx) for idx in immediate[immediate].index],
        "review_indices": [int(idx) for idx in review[review].index],
        "immediate_label": "immediate",
        "review_label": "review",
        "override_counts": override_counts,
        "observed_summary": observed_summary,
    }
    flagged.attrs["row_annotations"] = row_annotations
    return flagged


def _get_sod_config(audit_rules: dict | None = None) -> tuple[list[frozenset[str]], dict[str, int]]:
    """Load work-scope review pairs + role thresholds for L3-12 sidecar metadata."""

    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})

    configured_pairs = patterns.get("sod_review_pairs")
    if isinstance(configured_pairs, dict):
        raw_pairs = [
            *configured_pairs.get("strong", []),
            *configured_pairs.get("weak", []),
        ]
    elif configured_pairs:
        raw_pairs = configured_pairs
    else:
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


def _get_l106_sod_scoring_config(audit_rules: dict | None = None) -> dict[str, object]:
    """Load direct-only L1-06 score band policy."""

    rules = audit_rules or get_audit_rules()
    cfg = rules.get("patterns", {}).get("l1_06_sod_scoring", {})
    return {
        "direct_low": float(cfg.get("direct_low", 0.50)),
        "direct_medium": float(cfg.get("direct_medium", 0.70)),
        "direct_high": float(cfg.get("direct_high", 0.80)),
        "direct_critical": float(cfg.get("direct_critical", 0.95)),
        "protected_processes": tuple(
            str(v).strip().upper()
            for v in cfg.get("protected_processes", ["TRE", "P2P", "O2C", "R2R", "H2R"])
        ),
        "high_risk_conflict_types": tuple(
            str(v).strip().lower()
            for v in cfg.get(
                "high_risk_conflict_types",
                [
                    "cash_disbursement",
                    "purchase_payment",
                    "treasury_payment",
                    "payroll_payment",
                    "revenue_collection",
                ],
            )
        ),
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


def _human_sod_mask(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """Return rows treated as human activity for SoD analysis."""

    if cache is not None and "human_sod_mask" in cache.bool_masks:
        return cache.bool_masks["human_sod_mask"]
    mask = pd.Series(True, index=df.index)
    cfg = _get_sod_human_filter_config(audit_rules)

    if "user_persona" in df.columns:
        persona_norm = _cached_persona(df, "user_persona", cache)
        mask = mask & (persona_norm != "automated_system")

    if "source" in df.columns and cfg["system_sources"]:
        mask = mask & ~_cached_text(df, "source", cache).isin(cfg["system_sources"])

    if "created_by" in df.columns and cfg["system_actor_tokens"]:
        actor_norm = _cached_actor(df, "created_by", cache)
        system_actor = pd.Series(False, index=df.index)
        for token in cfg["system_actor_tokens"]:
            if token:
                system_actor = system_actor | actor_norm.str.contains(token, regex=False)
        mask = mask & ~system_actor

    if cache is not None:
        cache.bool_masks["human_sod_mask"] = mask
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


def _self_approval_mask(
    df: pd.DataFrame,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """Return rows where preparer and approver are the same human user."""

    if "created_by" not in df.columns or "approved_by" not in df.columns:
        return pd.Series(False, index=df.index)
    if cache is not None and "self_approval_mask" in cache.bool_masks:
        return cache.bool_masks["self_approval_mask"]
    created = _cached_actor(df, "created_by", cache)
    approved = _cached_actor(df, "approved_by", cache)
    result = (created != "") & (created == approved)
    if cache is not None:
        cache.bool_masks["self_approval_mask"] = result
    return result


def manual_override_signal_mask(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """Return manual-entry control-circumvention rows for non-L1-06 access review context."""

    if cache is not None and "manual_override_signal_mask" in cache.bool_masks:
        return cache.bool_masks["manual_override_signal_mask"]
    rules = audit_rules or get_audit_rules()
    patterns = rules.get("patterns", {})
    manual_sources = tuple(
        str(v).strip().lower()
        for v in patterns.get("manual_source_codes", ["manual", "adjustment"])
    )

    if "is_manual_je" in df.columns:
        manual_entry = df["is_manual_je"].fillna(False).astype(bool)
    elif "source" in df.columns:
        manual_entry = _is_manual_source(df, manual_sources, cache=cache)
    else:
        return pd.Series(False, index=df.index)

    no_approver = pd.Series(False, index=df.index)
    if "approved_by" in df.columns:
        no_approver = _cached_text(df, "approved_by", cache).eq("")

    no_approval_date = pd.Series(False, index=df.index)
    if "approval_date" in df.columns:
        no_approval_date = _cached_text(df, "approval_date", cache).eq("")

    abnormal_time = _is_abnormal_self_approval_time(df, cache=cache)
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
        _cached_text(df, "description_quality", cache).isin(("missing", "corrupted", "poor"))
        if "description_quality" in df.columns
        else pd.Series(False, index=df.index)
    )
    override_cfg = _get_self_approval_immediate_override_config(audit_rules)
    high_risk_account = _is_high_risk_account(
        df,
        exact_accounts=override_cfg["high_risk_accounts"],
        account_prefixes=override_cfg["high_risk_account_prefixes"],
        cache=cache,
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
    result = manual_entry & corroborating_signal
    if cache is not None:
        cache.bool_masks["manual_override_signal_mask"] = result
    return result


def _score_l106_sod_rows(
    df: pd.DataFrame,
    *,
    immediate_mask: pd.Series,
    direct_sod_violation: pd.Series,
    within_process_conflict: pd.Series,
    it_admin_high_risk: pd.Series,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> tuple[pd.Series, pd.Series, dict[int, dict[str, object]]]:
    """Return direct-only L1-06 score bands and row annotations."""

    cfg = _get_l106_sod_scoring_config(audit_rules)
    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    bucket = pd.Series("none", index=df.index, dtype="object")
    reason = pd.Series("", index=df.index, dtype="object")
    if not immediate_mask.any():
        return score_series, bucket, {}

    process_norm = (
        _cached_process(df, "business_process", cache)
        if "business_process" in df.columns
        else pd.Series("", index=df.index)
    )
    conflict_norm = (
        _cached_text(df, "sod_conflict_type", cache)
        if "sod_conflict_type" in df.columns
        else pd.Series("", index=df.index)
    )
    protected_process = process_norm.isin(cfg["protected_processes"])
    high_risk_conflict = conflict_norm.isin(cfg["high_risk_conflict_types"])
    threshold_excess = (
        df["exceeds_threshold"].fillna(False).astype(bool)
        if "exceeds_threshold" in df.columns
        else pd.Series(False, index=df.index)
    )
    has_amount = _line_amount(df, cache=cache).gt(0)

    direct_low = immediate_mask
    direct_medium = immediate_mask & (
        direct_sod_violation | (within_process_conflict & (protected_process | has_amount))
    )
    direct_high = immediate_mask & (high_risk_conflict | threshold_excess)
    direct_critical = immediate_mask & it_admin_high_risk

    score_series.loc[direct_low] = float(cfg["direct_low"])
    bucket.loc[direct_low] = "direct_low"
    reason.loc[direct_low] = "direct_conflict_marker"

    score_series.loc[direct_medium] = float(cfg["direct_medium"])
    bucket.loc[direct_medium] = "direct_medium"
    reason.loc[direct_medium] = "direct_conflict_with_process_or_amount"

    score_series.loc[direct_high] = float(cfg["direct_high"])
    bucket.loc[direct_high] = "direct_high"
    reason.loc[direct_high] = "high_risk_direct_sod"

    score_series.loc[direct_critical] = float(cfg["direct_critical"])
    bucket.loc[direct_critical] = "direct_critical"
    reason.loc[direct_critical] = "it_admin_protected_business_posting"

    row_annotations: dict[int, dict[str, object]] = {}
    annotation_columns = (
        "document_id",
        "created_by",
        "approved_by",
        "business_process",
        "source",
        "user_persona",
        "sod_conflict_type",
    )
    for idx in immediate_mask[immediate_mask].index:
        annotation: dict[str, object] = {
            "bucket": str(bucket.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
            "score_reason": str(reason.loc[idx]),
            "direct_sod_violation": bool(direct_sod_violation.loc[idx]),
            "within_process_conflict": bool(within_process_conflict.loc[idx]),
            "it_admin_high_risk": bool(it_admin_high_risk.loc[idx]),
            "protected_process": bool(protected_process.loc[idx]),
            "high_risk_conflict": bool(high_risk_conflict.loc[idx]),
            "threshold_excess": bool(threshold_excess.loc[idx]),
        }
        for column in annotation_columns:
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        row_annotations[int(idx)] = annotation

    return score_series, bucket, row_annotations


def b07_segregation_of_duties(
    df: pd.DataFrame,
    sod_threshold: int = 3,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """L1-06 direct segregation-of-duties violations.

    L1-06 is restricted to document-level SoD conflicts:
      - direct within-process SoD conflict markers
      - source-provided document-level SoD violation markers
      - IT super-user monetary postings in protected processes

    User history, configured review pairs, and role-threshold excess are work
    scope review signals. They are reported in breakdown metadata only and
    must not produce L1-06 score or review score.
    """

    required = ["created_by", "business_process"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    toxic_pairs, role_thresholds = _get_sod_config(audit_rules)
    it_admin_cfg = _get_sod_it_admin_config(audit_rules)
    strong_review_pairs, weak_review_pairs = _split_sod_pairs(toxic_pairs)
    result = pd.Series(False, index=df.index)

    persona_norm = (
        _cached_persona(df, "user_persona", cache)
        if "user_persona" in df.columns
        else pd.Series("", index=df.index)
    )
    human_mask = _human_sod_mask(df, audit_rules, cache=cache)

    human_df = df[human_mask]

    toxic_pair_users: set[str] = set()
    review_users: set[str] = set()
    role_violators: set[str] = set()
    fallback_scope_users: set[str] = set()
    if not human_df.empty:
        normalized_process = _cached_process(df, "business_process", cache).loc[human_df.index]
        user_processes = normalized_process.groupby(human_df["created_by"]).apply(
            lambda x: frozenset(v for v in x.unique() if v)
        )

        for user, procs in user_processes.items():
            for pair in strong_review_pairs:
                if pair.issubset(procs):
                    toxic_pair_users.add(user)
                    break

        for user, procs in user_processes.items():
            for pair in weak_review_pairs:
                if pair.issubset(procs):
                    review_users.add(user)
                    break

        if "user_persona" in df.columns and role_thresholds:
            counts = human_df.groupby("created_by")["business_process"].nunique()
            persona_map = _normalized_persona(
                human_df.drop_duplicates("created_by").set_index("created_by")["user_persona"]
            )

            for user, count in counts.items():
                persona = persona_map.get(user)
                if persona and persona in role_thresholds and count > role_thresholds[persona]:
                    role_violators.add(user)
        else:
            counts = human_df.groupby("created_by")["business_process"].nunique()
            fallback_scope_users = set(counts[counts >= sod_threshold].index)

    immediate_mask = pd.Series(False, index=df.index)

    direct_sod_violation = pd.Series(False, index=df.index)
    if "sod_violation" in df.columns:
        if pd.api.types.is_bool_dtype(df["sod_violation"]):
            direct_sod_violation = human_mask & df["sod_violation"].fillna(False).astype(bool)
        else:
            direct_sod_violation = human_mask & _cached_text(
                df,
                "sod_violation",
                cache,
            ).isin({"true", "1", "yes", "y"})
    direct_sod_violation_observed = direct_sod_violation.copy()

    within_process_conflict = pd.Series(False, index=df.index)
    if "sod_conflict_type" in df.columns:
        within_process_conflict = (
            human_mask
            & df["sod_conflict_type"].notna()
            & (df["sod_conflict_type"].astype(str).str.strip() != "")
        )
        direct_sod_violation = direct_sod_violation & within_process_conflict

    immediate_mask = immediate_mask | direct_sod_violation | within_process_conflict

    it_admin_high_risk = pd.Series(False, index=df.index)
    if "user_persona" in df.columns:
        protected_processes = set(it_admin_cfg["business_processes"])
        if protected_processes:
            process_norm = _cached_process(df, "business_process", cache)
            protected_mask = process_norm.isin(protected_processes)
        else:
            protected_mask = pd.Series(True, index=df.index)

        amount_mask = _line_amount(df, cache=cache) > 0
        materiality_amount = float(it_admin_cfg["materiality_amount"])
        if materiality_amount > 0:
            amount_mask = amount_mask & (_line_amount(df, cache=cache) >= materiality_amount)

        it_admin_persona = persona_norm.isin(it_admin_cfg["user_personas"])
        it_admin_high_risk = human_mask & it_admin_persona & protected_mask & amount_mask
        immediate_mask = immediate_mask | it_admin_high_risk

    mitigating_roles = _get_sod_mitigating_roles(audit_rules)
    scope_review_mask = pd.Series(False, index=df.index)
    scope_review_users = toxic_pair_users | review_users | role_violators | fallback_scope_users
    if scope_review_users:
        scope_review_mask = human_mask & df["created_by"].isin(scope_review_users)
        if "exceeds_threshold" in df.columns:
            scope_review_mask = (
                scope_review_mask & df["exceeds_threshold"].fillna(False).astype(bool)
            )
        else:
            scope_review_mask = pd.Series(False, index=df.index)
        if mitigating_roles and "user_persona" in df.columns:
            scope_review_mask = scope_review_mask & ~persona_norm.isin(mitigating_roles)
        scope_review_mask = scope_review_mask & ~immediate_mask

    result = immediate_mask
    score_series, score_bucket, row_annotations = _score_l106_sod_rows(
        df,
        immediate_mask=immediate_mask,
        direct_sod_violation=direct_sod_violation,
        within_process_conflict=within_process_conflict,
        it_admin_high_risk=it_admin_high_risk,
        audit_rules=audit_rules,
        cache=cache,
    )
    review_score_series = pd.Series(0.0, index=df.index)

    result.attrs["score_series"] = score_series
    result.attrs["review_score_series"] = review_score_series
    result.attrs["breakdown"] = {
        "immediate_rows": int(immediate_mask.sum()),
        "review_rows": 0,
        "immediate_users": 0,
        "review_users": 0,
        "toxic_pair_review_users": len(toxic_pair_users),
        "work_scope_review_rows_excluded": int(scope_review_mask.sum()),
        "work_scope_review_users_excluded": len(scope_review_users),
        "role_threshold_review_users_excluded": len(role_violators),
        "fallback_scope_review_users_excluded": len(fallback_scope_users),
        "strong_review_pairs": [sorted(pair) for pair in strong_review_pairs],
        "weak_review_pairs": [sorted(pair) for pair in weak_review_pairs],
        "direct_sod_violation_rows": int(direct_sod_violation_observed.sum()),
        "within_process_conflict_rows": int(within_process_conflict.sum()),
        "it_admin_high_risk_rows": int(it_admin_high_risk.sum()),
        "corroborated_review_rows": 0,
        "self_approval_rows": 0,
        "skipped_approval_rows": 0,
        "manual_override_rows": 0,
        "score_bucket_counts": score_bucket[score_bucket.ne("none")].value_counts().to_dict(),
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def _skipped_approval_components(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> dict[str, object]:
    """Compute reusable L1-07 masks without row-level annotation construction."""

    if cache is not None and "b09_skipped_approval_components" in cache.objects:
        return cache.objects["b09_skipped_approval_components"]  # type: ignore[return-value]

    if "approved_by" not in df.columns:
        false_mask = pd.Series(False, index=df.index, dtype=bool)
        zero_count = pd.Series(0, index=df.index, dtype="int64")
        cfg = _get_skipped_approval_immediate_config(audit_rules)
        components: dict[str, object] = {
            "cfg": cfg,
            "exceeds": false_mask,
            "level_review_required": false_mask,
            "approval_required": false_mask,
            "system_source": false_mask,
            "no_approval": false_mask,
            "candidate": false_mask,
            "manual_source": false_mask,
            "no_approval_date": false_mask,
            "manual_entry": false_mask,
            "abnormal_time": false_mask,
            "high_risk_process": false_mask,
            "high_approval_level": false_mask,
            "evidence_count": zero_count,
            "immediate": false_mask,
            "review": false_mask,
            "low_priority": false_mask,
        }
        if cache is not None:
            cache.objects["b09_skipped_approval_components"] = components
        return components

    cfg = _get_skipped_approval_immediate_config(audit_rules)
    no_approval = _cached_text(df, "approved_by", cache).eq("")
    exceeds = (
        df["exceeds_threshold"].fillna(False).astype(bool)
        if "exceeds_threshold" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )
    if "source" in df.columns:
        source_norm = _cached_text(df, "source", cache)
        system_source = source_norm.isin(cfg["system_sources"])
    else:
        source_norm = pd.Series("", index=df.index)
        system_source = pd.Series(False, index=df.index, dtype=bool)
    high_approval_level = (
        pd.to_numeric(df["approval_level"], errors="coerce").fillna(0).astype(int).ge(1)
        if "approval_level" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )
    level_review_required = no_approval & high_approval_level
    approval_required = exceeds | level_review_required
    candidate = no_approval

    manual_source = source_norm.isin(cfg["manual_sources"])
    no_approval_date = pd.Series(False, index=df.index, dtype=bool)
    if "approval_date" in df.columns:
        no_approval_date = _cached_text(df, "approval_date", cache).eq("")
    manual_entry = (
        df["is_manual_je"].fillna(False).astype(bool)
        if "is_manual_je" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )
    abnormal_time = _is_abnormal_self_approval_time(df, cache=cache)
    high_risk_process = (
        _cached_process(df, "business_process", cache).isin(cfg["business_processes"])
        if "business_process" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )
    high_approval_level_evidence = high_approval_level & (
        pd.to_numeric(df["approval_level"], errors="coerce").fillna(0).astype(int).ge(2)
        if "approval_level" in df.columns
        else False
    )

    evidence_count = (
        manual_source.astype(int)
        + no_approval_date.astype(int)
        + manual_entry.astype(int)
        + abnormal_time.astype(int)
        + high_risk_process.astype(int)
        + high_approval_level_evidence.astype(int)
    )
    actionable = candidate & approval_required & ~system_source
    immediate = actionable & manual_source & evidence_count.ge(int(cfg["min_evidence_count"]))
    review = actionable & ~immediate
    low_priority = candidate & ~immediate & ~review
    components: dict[str, object] = {
        "cfg": cfg,
        "exceeds": exceeds,
        "level_review_required": level_review_required,
        "approval_required": approval_required,
        "system_source": system_source,
        "no_approval": no_approval,
        "candidate": candidate,
        "manual_source": manual_source,
        "no_approval_date": no_approval_date,
        "manual_entry": manual_entry,
        "abnormal_time": abnormal_time,
        "high_risk_process": high_risk_process,
        "high_approval_level": high_approval_level_evidence,
        "evidence_count": evidence_count,
        "immediate": immediate,
        "review": review,
        "low_priority": low_priority,
    }
    if cache is not None:
        cache.objects["b09_skipped_approval_components"] = components
    return components


def _bounded_score(series: pd.Series | float, index: pd.Index) -> pd.Series:
    if isinstance(series, pd.Series):
        return series.reindex(index).fillna(0.0).astype(float).clip(0.0, 1.0)
    return pd.Series(float(series), index=index, dtype="float64").clip(0.0, 1.0)


def _l107_component_scores(
    df: pd.DataFrame,
    components: dict[str, object],
    cache: AccessRuleCache | None = None,
) -> dict[str, pd.Series]:
    """Score L1-07 severity components without changing queue-label semantics."""

    index = df.index
    exceeds = components["exceeds"]
    approval_required = components["approval_required"]
    system_source = components["system_source"]
    manual_source = components["manual_source"]
    no_approval = components["no_approval"]
    no_approval_date = components["no_approval_date"]
    manual_entry = components["manual_entry"]
    abnormal_time = components["abnormal_time"]
    high_risk_process = components["high_risk_process"]
    high_approval_level = components["high_approval_level"]

    approval_level = (
        pd.to_numeric(df["approval_level"], errors="coerce").fillna(0).astype(int)
        if "approval_level" in df.columns
        else pd.Series(0, index=index, dtype="int64")
    )
    approval_requirement = pd.Series(0.0, index=index)
    approval_requirement.loc[approval_required] = 0.55
    approval_requirement.loc[approval_level.ge(1)] = approval_requirement.loc[
        approval_level.ge(1)
    ].clip(lower=0.65)
    approval_requirement.loc[approval_level.ge(2)] = approval_requirement.loc[
        approval_level.ge(2)
    ].clip(lower=0.75)
    approval_requirement.loc[exceeds] = 1.0

    amount = _document_amount(df, cache=cache)
    amount_materiality = pd.Series(0.0, index=index)
    amount_materiality.loc[amount.gt(0)] = 0.35
    amount_materiality.loc[amount.ge(10_000_000)] = 0.60
    amount_materiality.loc[amount.ge(100_000_000)] = 0.80
    amount_materiality.loc[amount.ge(1_000_000_000)] = 1.00
    amount_materiality.loc[approval_level.ge(1)] = amount_materiality.loc[
        approval_level.ge(1)
    ].clip(lower=0.60)
    amount_materiality.loc[approval_level.ge(2)] = amount_materiality.loc[
        approval_level.ge(2)
    ].clip(lower=0.75)
    amount_materiality.loc[approval_level.ge(3)] = amount_materiality.loc[
        approval_level.ge(3)
    ].clip(lower=0.90)

    control_bypass = (
        manual_source.astype(float) * 0.40
        + no_approval_date.astype(float) * 0.25
        + high_risk_process.astype(float) * 0.20
        + high_approval_level.astype(float) * 0.15
    ).clip(0.0, 1.0)

    period_end = (
        df["is_period_end"].fillna(False).astype(bool)
        if "is_period_end" in df.columns
        else pd.Series(False, index=index, dtype=bool)
    )
    weekend = (
        df["is_weekend"].fillna(False).astype(bool)
        if "is_weekend" in df.columns
        else pd.Series(False, index=index, dtype=bool)
    )
    timing_manual = (
        manual_entry.astype(float) * 0.35
        + abnormal_time.astype(float) * 0.35
        + period_end.astype(float) * 0.20
        + weekend.astype(float) * 0.10
    ).clip(0.0, 1.0)

    if {"created_by", "business_process"}.issubset(df.columns):
        repeat_key = (
            df["created_by"].fillna("").astype(str).str.strip()
            + "|"
            + df["business_process"].fillna("").astype(str).str.strip()
        )
        repeat_count = repeat_key.groupby(repeat_key, dropna=False).transform("size")
    elif "created_by" in df.columns:
        repeat_key = df["created_by"].fillna("").astype(str).str.strip()
        repeat_count = repeat_key.groupby(repeat_key, dropna=False).transform("size")
    else:
        repeat_count = pd.Series(1, index=index)
    repeat_concentration = pd.Series(0.0, index=index)
    repeat_concentration.loc[repeat_count.ge(2)] = 0.50
    repeat_concentration.loc[repeat_count.ge(3)] = 0.80
    repeat_concentration.loc[repeat_count.ge(5)] = 1.00
    repeat_concentration = repeat_concentration.where(no_approval, 0.0)

    if "document_id" in df.columns:
        doc_id = df["document_id"].fillna("").astype(str)
        all_lines_missing_approver = no_approval.groupby(doc_id, dropna=False).transform("all")
    else:
        all_lines_missing_approver = no_approval
    data_trace = (
        no_approval_date.astype(float) * 0.70
        + all_lines_missing_approver.astype(float) * 0.30
    ).clip(0.0, 1.0)

    source_norm = (
        _cached_text(df, "source", cache)
        if "source" in df.columns
        else pd.Series("", index=index, dtype="object")
    )
    recurring_source = source_norm.eq("recurring")
    has_approval_date = (
        ~no_approval_date
        if "approval_date" in df.columns
        else pd.Series(False, index=index)
    )
    mitigation = (
        system_source.astype(float) * 1.00
        + recurring_source.astype(float) * 0.55
        + has_approval_date.astype(float) * 0.25
        + (~approval_required).astype(float) * 0.65
    ).clip(0.0, 1.0)

    raw_score = (
        0.25 * approval_requirement
        + 0.25 * amount_materiality
        + 0.20 * control_bypass
        + 0.15 * timing_manual
        + 0.10 * repeat_concentration
        + 0.05 * data_trace
        - 0.15 * mitigation
    ).clip(0.0, 1.0)

    return {
        "approval_requirement_confidence": _bounded_score(approval_requirement, index),
        "amount_materiality": _bounded_score(amount_materiality, index),
        "control_bypass_context": _bounded_score(control_bypass, index),
        "timing_and_manual_context": _bounded_score(timing_manual, index),
        "repeat_or_concentration": _bounded_score(repeat_concentration, index),
        "data_trace_quality": _bounded_score(data_trace, index),
        "mitigation_likelihood": _bounded_score(mitigation, index),
        "raw_score": _bounded_score(raw_score, index),
    }


def b09_skipped_approval(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
    cache: AccessRuleCache | None = None,
) -> pd.Series:
    """L1-07 skipped approval: approval required but approver missing."""

    if "approved_by" not in df.columns:
        return pd.Series(False, index=df.index)
    if cache is not None and "b09_skipped_approval_result" in cache.bool_masks:
        return cache.bool_masks["b09_skipped_approval_result"]

    components = _skipped_approval_components(df, audit_rules=audit_rules, cache=cache)
    cfg = components["cfg"]
    exceeds = components["exceeds"]
    approval_required = components["approval_required"]
    level_review_required = components["level_review_required"]
    system_source = components["system_source"]
    no_approval = components["no_approval"]
    candidate = components["candidate"]
    manual_source = components["manual_source"]
    no_approval_date = components["no_approval_date"]
    manual_entry = components["manual_entry"]
    abnormal_time = components["abnormal_time"]
    high_risk_process = components["high_risk_process"]
    high_approval_level = components["high_approval_level"]
    evidence_count = components["evidence_count"]
    immediate = components["immediate"]
    review = components["review"]
    low_priority = components["low_priority"]
    queue_label = pd.Series("none", index=df.index, dtype="object")
    queue_label.loc[low_priority] = "low_priority"
    queue_label.loc[review] = "review"
    queue_label.loc[immediate] = "immediate"

    component_scores = _l107_component_scores(df, components, cache=cache)
    raw_l107_score = component_scores["raw_score"]
    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[immediate] = raw_l107_score.loc[immediate].clip(lower=0.70)
    review_score_series = pd.Series(0.0, index=df.index)
    review_score_series.loc[review] = raw_l107_score.loc[review].clip(lower=0.45, upper=0.69)
    review_score_series.loc[low_priority] = raw_l107_score.loc[low_priority].clip(
        lower=0.10,
        upper=0.44,
    )
    effective_score = pd.concat([score_series, review_score_series], axis=1).max(axis=1)

    evidence_reasons_by_row: dict[int, list[str]] = {}
    row_annotations: dict[int, dict[str, object]] = {}
    for idx in candidate[candidate].index:
        reasons: list[str] = []
        if bool(manual_source.loc[idx]):
            reasons.append("manual_source")
        if bool(no_approval_date.loc[idx]):
            reasons.append("no_approval_date")
        if bool(manual_entry.loc[idx]):
            reasons.append("manual_entry")
        if bool(abnormal_time.loc[idx]):
            reasons.append("abnormal_time")
        if bool(high_risk_process.loc[idx]):
            reasons.append("high_risk_process")
        if bool(high_approval_level.loc[idx]):
            reasons.append("high_approval_level")
        evidence_reasons_by_row[int(idx)] = reasons

        annotation: dict[str, object] = {
            "queue_label": str(queue_label.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
            "review_score": round(float(review_score_series.loc[idx]), 4),
            "severity_score": round(float(raw_l107_score.loc[idx]), 4),
            "score_components": {
                key: round(float(series.loc[idx]), 4)
                for key, series in component_scores.items()
                if key != "raw_score"
            },
            "evidence_count": int(evidence_count.loc[idx]),
            "evidence_reasons": reasons,
            "source_category": (
                "system_exception"
                if bool(system_source.loc[idx])
                else "not_approval_required"
                if not bool(approval_required.loc[idx])
                else "manual"
                if bool(manual_source.loc[idx])
                else "non_system_review"
            ),
            "has_approval_date": not bool(no_approval_date.loc[idx]),
            "min_evidence_count": int(cfg["min_evidence_count"]),
        }
        annotation["score_reason_summary"] = [
            key
            for key, value in annotation["score_components"].items()
            if key != "mitigation_likelihood" and float(value) >= 0.5
        ]
        if annotation["score_components"]["mitigation_likelihood"] >= 0.5:
            annotation["score_reason_summary"].append("mitigation_likelihood")
        for column in (
            "document_id",
            "source",
            "approved_by",
            "approval_date",
            "business_process",
            "approval_level",
            "created_by",
        ):
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        row_annotations[int(idx)] = annotation

    evidence_count_bands = {
        str(int(count)): int(((candidate) & evidence_count.eq(count)).sum())
        for count in sorted(evidence_count[candidate].dropna().unique())
    }
    evidence_reason_counts: dict[str, int] = {}
    for reasons in evidence_reasons_by_row.values():
        for reason in reasons:
            evidence_reason_counts[reason] = evidence_reason_counts.get(reason, 0) + 1

    candidate.attrs["score_series"] = score_series
    candidate.attrs["review_score_series"] = review_score_series
    candidate.attrs["breakdown"] = {
        "immediate_rows": int(immediate.sum()),
        "review_rows": int(review.sum()),
        "low_priority_rows": int(low_priority.sum()),
        "confirmed_rows": int(immediate.sum()),
        "candidate_rows": int(candidate.sum()),
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
        "approval_level_review_rows": int((candidate & level_review_required & ~exceeds).sum()),
        "missing_approver_rows": int(candidate.sum()),
        "actionable_missing_approver_rows": int(
            (approval_required & ~system_source & no_approval).sum()
        ),
        "no_approval_required_rows": int((candidate & ~approval_required).sum()),
        "no_approval_trace_rows": int((candidate & no_approval_date).sum()),
        "allowed_system_rows": int((candidate & system_source).sum()),
        "evidence_count_bands": evidence_count_bands,
        "evidence_reason_counts": evidence_reason_counts,
        "min_evidence_count": int(cfg["min_evidence_count"]),
        "score_bands": {
            "critical": int((candidate & effective_score.ge(0.85)).sum()),
            "high": int((candidate & effective_score.ge(0.70) & effective_score.lt(0.85)).sum()),
            "review": int((candidate & effective_score.ge(0.45) & effective_score.lt(0.70)).sum()),
            "low": int((candidate & effective_score.gt(0.0) & effective_score.lt(0.45)).sum()),
        },
    }
    candidate.attrs["row_annotations"] = row_annotations
    immediate.attrs = candidate.attrs.copy()
    if cache is not None:
        cache.bool_masks["b09_skipped_approval_result"] = candidate
    return candidate


def b10_intercompany_review_signal(df: pd.DataFrame) -> pd.Series:
    """L3-03 related-party transaction review signal.

    Phase 1 only identifies entries posted to configured intercompany account
    prefixes. It does not prove a circular transaction; N-hop circular flow is
    handled by GR01 in GraphDetector.
    """

    if "is_intercompany" not in df.columns:
        return pd.Series(False, index=df.index)

    ic_mask = df["is_intercompany"].fillna(False).astype(bool)
    if not ic_mask.any():
        return pd.Series(False, index=df.index)

    breakdown: dict[str, object] = {
        "ic_population_rows": int(ic_mask.sum()),
        "ic_population_docs": (
            int(df.loc[ic_mask, "document_id"].dropna().nunique())
            if "document_id" in df.columns
            else int(ic_mask.sum())
        ),
    }
    if "company_code" in df.columns:
        breakdown["ic_company_count"] = int(df.loc[ic_mask, "company_code"].dropna().nunique())
    if "trading_partner" in df.columns:
        partner_populated = _normalized_text(df.loc[ic_mask, "trading_partner"]).ne("")
        breakdown["trading_partner_coverage_ratio"] = (
            float(partner_populated.mean()) if len(partner_populated) else 0.0
        )

    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[ic_mask] = 0.4
    ic_mask.attrs["score_series"] = score_series
    ic_mask.attrs["breakdown"] = breakdown
    ic_mask.attrs["row_annotations"] = {
        idx: {
            "signal_category": "ic_population",
            "score": 0.4,
            "company_code": (
                str(df.at[idx, "company_code"]) if "company_code" in df.columns else ""
            ),
            "trading_partner": (
                str(df.at[idx, "trading_partner"]) if "trading_partner" in df.columns else ""
            ),
        }
        for idx in df.index[ic_mask]
    }

    if "company_code" in df.columns:
        ic_companies = set(df.loc[ic_mask, "company_code"].dropna().unique())
        if len(ic_companies) < 2:
            return ic_mask

    return ic_mask


# Backward-compatible name retained for existing imports/tests.
b10_circular_intercompany = b10_intercompany_review_signal
