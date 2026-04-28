"""Layer D rule functions: D01 account activity shift, D02 monthly pattern shift.

Why: These pure functions compare current-period journal activity against prior-period
     summaries without depending directly on PriorSummary objects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon

# Why: Avoid division by zero when prior-period values are zero.
_EPSILON = 1.0

# Why: D01 weights total activity most, then count, then average amount.
_W_TOTAL = 0.5
_W_COUNT = 0.3
_W_AVG = 0.2

# Why: D02 needs enough active months for a meaningful distribution comparison.
_MIN_MONTHS = 3
_MIN_ACCOUNT_DOCS = 100
_MIN_ANNUAL_AMOUNT = 0.0
_MIN_TOP_MONTH_DELTA = 0.25
_MISSING_ACCOUNT_TOKENS = {"", "nan", "none", "null", "<na>"}
_ACCOUNT_KEY_SEP = "::"
_D02_DEFAULT_GROUP_KEYS = ("company_code", "gl_account")


def _valid_account_mask(series: pd.Series) -> pd.Series:
    """Return rows with a usable GL account identifier."""

    return series.notna() & ~series.astype(str).str.strip().str.lower().isin(
        _MISSING_ACCOUNT_TOKENS
    )


def _company_account_key(company_code: object, gl_account: object) -> str:
    """Return the stable D01 key used when company_code is available."""

    return (
        f"{_normalise_key_part(company_code)}"
        f"{_ACCOUNT_KEY_SEP}"
        f"{_normalise_key_part(gl_account)}"
    )


def _normalise_key_part(value: object) -> str:
    """Return a stable string key part for cross-source account comparisons."""

    if pd.isna(value):
        return ""

    text = str(value).strip()
    try:
        numeric = float(text)
    except ValueError:
        return text

    if numeric.is_integer():
        return str(int(numeric))
    return text


def _d02_effective_group_keys(
    df: pd.DataFrame,
    group_keys: list[str] | tuple[str, ...] | None,
) -> list[str]:
    """Return D02 grouping columns available in the current DataFrame."""

    requested = list(group_keys or _D02_DEFAULT_GROUP_KEYS)
    if "gl_account" not in requested:
        requested.append("gl_account")

    effective = [key for key in requested if key in df.columns]
    return effective or ["gl_account"]


def _d02_group_key(row: pd.Series, group_keys: list[str]) -> str:
    """Build the D02 prior-pattern key for the selected evaluation unit."""

    return _ACCOUNT_KEY_SEP.join(_normalise_key_part(row[key]) for key in group_keys)


def _lookup_prior_pattern(
    prior_patterns: dict[str, dict[int, float]],
    group_key: str,
    gl_account: object,
) -> dict[int, float] | None:
    """Find prior D02 pattern, preferring company/account keys."""

    acct = _normalise_key_part(gl_account)
    return (
        prior_patterns.get(group_key)
        or prior_patterns.get(str(group_key))
        or prior_patterns.get(gl_account)
        or prior_patterns.get(acct)
    )


def _lookup_prior_account(
    prior_aggregates: dict[str, dict[str, float]],
    gl_account: object,
    company_code: object | None = None,
) -> dict[str, float] | None:
    """Find prior D01 aggregates, preferring company-aware keys."""

    acct = _normalise_key_part(gl_account)
    if company_code is not None:
        company_key = _company_account_key(company_code, acct)
        prior = prior_aggregates.get(company_key)
        if prior is not None:
            return prior

    return (
        prior_aggregates.get(gl_account)
        or prior_aggregates.get(str(gl_account))
        or prior_aggregates.get(acct)
    )


def d01_account_activity_variance(
    df: pd.DataFrame,
    prior_aggregates: dict[str, dict[str, float]],
    variance_threshold: float = 0.5,
) -> pd.Series:
    """D01 account activity shift: flag accounts with large YoY activity changes.

    Why: This is an ISA 520 analytical-procedure screening signal. It compares
         debit+credit activity by account, using total amount, count, and average amount.
    """
    if "gl_account" not in df.columns:
        return pd.Series(False, index=df.index)
    if not prior_aggregates:
        return pd.Series(False, index=df.index)

    valid_accounts = _valid_account_mask(df["gl_account"])
    if not valid_accounts.any():
        return pd.Series(False, index=df.index)

    analysis_df = df.loc[valid_accounts].copy()
    amount = analysis_df[["debit_amount", "credit_amount"]].fillna(0).sum(axis=1)
    has_company_code = "company_code" in analysis_df.columns
    group_cols = ["company_code", "gl_account"] if has_company_code else ["gl_account"]
    current_agg = (
        analysis_df.assign(_amount=amount)
        .groupby(group_cols, dropna=False)["_amount"]
        .agg(total_amount="sum", count="count", avg_amount="mean")
    )

    flagged_accounts: set[str] = set()
    flagged_company_accounts: set[tuple[str, str]] = set()
    for account_key, row in current_agg.iterrows():
        if has_company_code:
            company_code, acct = account_key
        else:
            company_code, acct = None, account_key

        prior = _lookup_prior_account(prior_aggregates, acct, company_code)
        if prior is None:
            if has_company_code:
                flagged_company_accounts.add((
                    _normalise_key_part(company_code),
                    _normalise_key_part(acct),
                ))
            else:
                flagged_accounts.add(_normalise_key_part(acct))
            continue

        total_var = abs(row["total_amount"] - prior["total_amount"]) / max(
            prior["total_amount"], _EPSILON
        )
        count_var = abs(row["count"] - prior["count"]) / max(prior["count"], _EPSILON)
        avg_var = abs(row["avg_amount"] - prior["avg_amount"]) / max(
            prior["avg_amount"], _EPSILON
        )

        weighted = total_var * _W_TOTAL + count_var * _W_COUNT + avg_var * _W_AVG
        if weighted > variance_threshold:
            if has_company_code:
                flagged_company_accounts.add((
                    _normalise_key_part(company_code),
                    _normalise_key_part(acct),
                ))
            else:
                flagged_accounts.add(_normalise_key_part(acct))

    if has_company_code:
        current_keys = pd.Series(
            list(zip(
                df["company_code"].map(_normalise_key_part),
                df["gl_account"].map(_normalise_key_part),
            )),
            index=df.index,
        )
        return current_keys.isin(flagged_company_accounts) & valid_accounts

    return df["gl_account"].map(_normalise_key_part).isin(flagged_accounts) & valid_accounts


# Backward-compatible alias for older imports/tests. The rule compares account-level
# debit+credit activity, not ending balances.
d01_account_aggregate_variance = d01_account_activity_variance


def d02_monthly_pattern_variance(
    df: pd.DataFrame,
    prior_patterns: dict[str, dict[int, float]],
    jsd_threshold: float = 0.3,
    min_months: int = _MIN_MONTHS,
    min_account_docs: int = _MIN_ACCOUNT_DOCS,
    min_annual_amount: float = _MIN_ANNUAL_AMOUNT,
    min_top_month_delta: float = _MIN_TOP_MONTH_DELTA,
    group_keys: list[str] | tuple[str, ...] | None = _D02_DEFAULT_GROUP_KEYS,
) -> pd.Series:
    """D02 monthly pattern shift: compare prior/current distributions with JSD."""
    diagnostics = d02_monthly_pattern_diagnostics(
        df,
        prior_patterns,
        jsd_threshold=jsd_threshold,
        min_months=min_months,
        min_account_docs=min_account_docs,
        min_annual_amount=min_annual_amount,
        min_top_month_delta=min_top_month_delta,
        group_keys=group_keys,
    )
    if diagnostics.empty:
        return pd.Series(False, index=df.index)

    flagged_groups = set(diagnostics.loc[diagnostics["flagged"], "d02_group_key"])
    effective_group_keys = _d02_effective_group_keys(df, group_keys)
    current_group_keys = df[effective_group_keys].apply(
        lambda row: _d02_group_key(row, effective_group_keys),
        axis=1,
    )
    return current_group_keys.isin(flagged_groups) & _valid_account_mask(df["gl_account"])


def d02_monthly_pattern_diagnostics(
    df: pd.DataFrame,
    prior_patterns: dict[str, dict[int, float]],
    jsd_threshold: float = 0.3,
    min_months: int = _MIN_MONTHS,
    min_account_docs: int = _MIN_ACCOUNT_DOCS,
    min_annual_amount: float = _MIN_ANNUAL_AMOUNT,
    min_top_month_delta: float = _MIN_TOP_MONTH_DELTA,
    group_keys: list[str] | tuple[str, ...] | None = _D02_DEFAULT_GROUP_KEYS,
) -> pd.DataFrame:
    """Return account-level D02 evidence and eligibility decisions."""
    columns = [
        "d02_group_key",
        "d02_group_columns",
        "company_code",
        "gl_account",
        "jsd",
        "flagged",
        "prior_months",
        "current_months",
        "current_doc_count",
        "current_annual_amount",
        "prior_top_month",
        "current_top_month",
        "prior_top_ratio",
        "current_top_ratio",
        "top_month_delta",
        "skip_reason",
    ]
    if "gl_account" not in df.columns or "fiscal_period" not in df.columns:
        return pd.DataFrame(columns=columns)
    if not prior_patterns:
        return pd.DataFrame(columns=columns)

    min_months = max(int(min_months), 1)
    min_account_docs = max(int(min_account_docs), 1)
    min_annual_amount = max(float(min_annual_amount), 0.0)
    min_top_month_delta = max(float(min_top_month_delta), 0.0)

    valid_accounts = _valid_account_mask(df["gl_account"])
    if not valid_accounts.any():
        return pd.DataFrame(columns=columns)

    analysis_df = df.loc[valid_accounts].copy()
    effective_group_keys = _d02_effective_group_keys(analysis_df, group_keys)
    analysis_df["_d02_group_key"] = analysis_df[effective_group_keys].apply(
        lambda row: _d02_group_key(row, effective_group_keys),
        axis=1,
    )
    amount = analysis_df[["debit_amount", "credit_amount"]].fillna(0).sum(axis=1)
    monthly = (
        analysis_df.assign(_amount=amount)
        .groupby(["_d02_group_key", "fiscal_period"])["_amount"]
        .sum()
    )
    if "document_id" in analysis_df.columns:
        account_doc_counts = analysis_df.groupby("_d02_group_key")["document_id"].nunique()
    else:
        account_doc_counts = analysis_df.groupby("_d02_group_key").size()
    group_identity = (
        analysis_df.groupby("_d02_group_key", dropna=False)
        .agg(
            gl_account=("gl_account", "first"),
            company_code=(
                "company_code",
                "first",
            )
            if "company_code" in analysis_df.columns
            else ("gl_account", lambda _series: None),
        )
    )

    rows: list[dict[str, object]] = []

    for group_key in monthly.index.get_level_values("_d02_group_key").unique():
        identity = group_identity.loc[group_key]
        acct = identity["gl_account"]
        company_code = identity["company_code"]
        prior_dist_dict = _lookup_prior_pattern(prior_patterns, str(group_key), acct)
        if prior_dist_dict is None:
            continue

        prior_vec = np.array([prior_dist_dict.get(m, 0.0) for m in range(1, 13)])
        current_amounts = monthly.loc[group_key]
        current_vec = np.zeros(12)
        for period, amt in current_amounts.items():
            try:
                month_idx = int(period) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= month_idx < 12:
                current_vec[month_idx] = amt

        prior_months = int(np.count_nonzero(prior_vec))
        current_months = int(np.count_nonzero(current_vec))
        current_doc_count = int(account_doc_counts.get(group_key, 0))
        current_sum = float(current_vec.sum())
        skip_reason = ""

        if prior_months < min_months:
            skip_reason = "insufficient_prior_months"
        elif current_months < min_months:
            skip_reason = "insufficient_current_months"
        elif current_doc_count < min_account_docs:
            skip_reason = "insufficient_current_docs"
        elif current_sum < min_annual_amount:
            skip_reason = "insufficient_current_amount"

        prior_sum = prior_vec.sum()
        if prior_sum == 0 or current_sum == 0:
            continue

        prior_norm = prior_vec / prior_sum
        current_norm = current_vec / current_sum
        prior_top_month = int(np.argmax(prior_norm) + 1)
        current_top_month = int(np.argmax(current_norm) + 1)
        prior_top_ratio = float(prior_norm.max())
        current_top_ratio = float(current_norm.max())
        top_month_delta = abs(current_top_ratio - prior_top_ratio)
        if not skip_reason and top_month_delta < min_top_month_delta:
            skip_reason = "small_top_month_delta"

        jsd = float(jensenshannon(prior_norm, current_norm))
        rows.append({
            "d02_group_key": str(group_key),
            "d02_group_columns": list(effective_group_keys),
            "company_code": None if pd.isna(company_code) else str(company_code),
            "gl_account": _normalise_key_part(acct),
            "jsd": jsd,
            "flagged": (not skip_reason) and jsd > jsd_threshold,
            "prior_months": prior_months,
            "current_months": current_months,
            "current_doc_count": current_doc_count,
            "current_annual_amount": current_sum,
            "prior_top_month": prior_top_month,
            "current_top_month": current_top_month,
            "prior_top_ratio": prior_top_ratio,
            "current_top_ratio": current_top_ratio,
            "top_month_delta": top_month_delta,
            "skip_reason": skip_reason,
        })

    return pd.DataFrame(rows, columns=columns)
