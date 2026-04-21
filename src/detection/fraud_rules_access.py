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
    gl = _normalized_text(df["gl_account"])
    mask = pd.Series(False, index=df.index)
    if exact_accounts:
        mask = mask | gl.isin(exact_accounts)
    if account_prefixes:
        mask = mask | gl.str.startswith(account_prefixes)
    return mask


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
    review = review_base & ~override_immediate
    immediate = flagged & ~review

    flagged.attrs["score_series"] = flagged.astype(float) * 0.6
    flagged.attrs["breakdown"] = {
        "immediate_rows": int(immediate.sum()),
        "review_rows": int(review.sum()),
        "immediate_indices": [int(idx) for idx in immediate[immediate].index],
        "review_indices": [int(idx) for idx in review[review].index],
        "immediate_label": "immediate",
        "review_label": "review",
        "override_counts": override_counts,
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


def b07_segregation_of_duties(
    df: pd.DataFrame,
    sod_threshold: int = 3,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L1-06 segregation-of-duties signal with immediate/review split.

    Immediate violation:
      - direct within-process SoD conflict markers
      - configured toxic pairs outside R2R review scope
      - IT super-user monetary postings in protected processes

    Review required:
      - configured R2R-related SoD pairs
      - role-threshold excess by persona
    """

    required = ["created_by", "business_process"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    toxic_pairs, role_thresholds = _get_sod_config(audit_rules)
    it_admin_cfg = _get_sod_it_admin_config(audit_rules)
    immediate_pairs, review_pairs = _split_sod_pairs(toxic_pairs)
    result = pd.Series(False, index=df.index)

    if "user_persona" in df.columns:
        persona_norm = _normalized_persona(df["user_persona"])
        human_mask = persona_norm != "automated_system"
    else:
        persona_norm = pd.Series("", index=df.index)
        human_mask = pd.Series(True, index=df.index)

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
        immediate_mask = df["created_by"].isin(immediate_users)
    if review_users:
        review_mask = df["created_by"].isin(review_users)

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
            review_mask = review_mask | df["created_by"].isin(role_violators)
    else:
        counts = human_df.groupby("created_by")["business_process"].nunique()
        violators = counts[counts >= sod_threshold].index
        review_mask = review_mask | df["created_by"].isin(violators)

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
    }
    return result


def b09_skipped_approval(df: pd.DataFrame) -> pd.Series:
    """L1-07 skipped approval: approval required but approver missing."""

    if "exceeds_threshold" not in df.columns or "source" not in df.columns:
        return pd.Series(False, index=df.index)

    exceeds = df["exceeds_threshold"].fillna(False)
    not_automated = df["source"].astype(str).str.lower() != "automated"
    no_approval = pd.Series(True, index=df.index)
    if "approved_by" in df.columns:
        no_approval = df["approved_by"].isna() | (df["approved_by"].astype(str).str.strip() == "")
    return exceeds & not_automated & no_approval


def b10_circular_intercompany(df: pd.DataFrame) -> pd.Series:
    """L3-03 intercompany circularity signal (MVP)."""

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
