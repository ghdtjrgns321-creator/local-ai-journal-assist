from __future__ import annotations

import pandas as pd

PHASE2_NEW_ACCOUNTS = {
    "131100": "intangible_assets",
    "681100": "amortization_expense",
    "151900": "construction_in_progress",
    "116100": "contract_assets",
    "231100": "contract_liabilities",
    "123100": "inventory_wip",
    "117100": "loans_receivable",
    "117900": "employee_advances",
    "106100": "short_term_investments",
    "119100": "allowance_for_doubtful_accounts",
    "469100": "allowance_reversal",
    "237100": "provisions",
    "160100": "investments",
    "682100": "impairment_loss",
}

WOVEN_REQUIRED = {
    "131100",
    "681100",
    "151900",
    "117100",
    "117900",
    "119100",
    "469100",
    "237100",
    "106100",
    "160100",
    "682100",
}

WOVEN_ARCHETYPES = {
    "P2P_VENDOR_INVOICE",
    "P2P_PAYMENT",
    "A2R_ASSET_ACQUISITION",
    "A2R_DEPRECIATION",
    "H2R_PAYROLL_PAYMENT",
    "H2R_PAYROLL_ACCRUAL",
    "R2R_ACCRUAL",
    "R2R_CLOSING_ENTRY",
    "TRE_LOAN_DRAWDOWN",
    "TRE_INTEREST_PAYMENT",
}

BASELINE_ACCOUNTS = {"1000", "1100", "5000", "1230"}
SCHEDULED_EVERY_PERIOD_ACCOUNTS = {"681100"}
SINGLE_COUNTERPARTY_TYPE_ALLOWED = {"116100", "231100"}


def _verdict(gate, test_id, status, metric, notes):
    return {"gate": gate, "test_id": test_id, "verdict": status, "metric": metric, "notes": notes}


def _top_share(series):
    values = series.fillna("").astype(str).str.strip()
    values = values.where(values.ne(""), "BLANK")
    counts = values.value_counts()
    if counts.empty:
        return "", 0, 0.0, 0
    top_value = str(counts.index[0])
    top_count = int(counts.iloc[0])
    total = int(counts.sum())
    return top_value, top_count, float(top_count / max(total, 1)), int(len(counts))


def new_account_findings(df):
    required = {
        "gl_account",
        "company_code",
        "fiscal_year",
        "fiscal_period",
        "document_id",
        "trading_partner",
        "counterparty_type",
        "semantic_scenario_id",
        "debit_amount",
        "credit_amount",
        "is_fraud",
        "is_anomaly",
        "fraud_type",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        return [
            _verdict(
                "Gate 2",
                test_id,
                "BLOCKED",
                {"missing_required_columns": missing},
                "PHASE2 new-account normal realism inputs required",
            )
            for test_id in ["N07", "N08", "N09", "N10", "N11"]
        ]
    work = df[df["gl_account"].astype(str).isin(PHASE2_NEW_ACCOUNTS)].copy()
    cells = pd.MultiIndex.from_product(
        [
            sorted(df["company_code"].astype(str).unique()),
            sorted(df["fiscal_year"].astype(str).unique()),
            sorted(df["fiscal_period"].astype(str).unique()),
        ],
        names=["company_code", "fiscal_year", "fiscal_period"],
    )
    n07_metric = {}
    n08_metric = {}
    n09_metric = {}
    n10_metric = {}
    n11_metric = {}
    n07_bad = []
    n08_bad = []
    n09_bad = []
    n10_bad = []
    n11_bad = []
    for account, name in PHASE2_NEW_ACCOUNTS.items():
        sub = work[work["gl_account"].astype(str).eq(account)].copy()
        count_by_cell = (
            sub.groupby(["company_code", "fiscal_year", "fiscal_period"], dropna=False)[
                "document_id"
            ]
            .nunique()
            .reindex(cells, fill_value=0)
        )
        std = float(count_by_cell.std(ddof=0))
        empty_cells = int((count_by_cell == 0).sum())
        n07_metric[account] = {
            "name": name,
            "docs": int(sub["document_id"].nunique()),
            "rows": int(len(sub)),
            "cell_count_std": std,
            "empty_cells": empty_cells,
            "cell_count_min": int(count_by_cell.min()),
            "cell_count_max": int(count_by_cell.max()),
        }
        allowed_full_calendar = account in SCHEDULED_EVERY_PERIOD_ACCOUNTS and std > 0.0
        if std <= 0.0 or (empty_cells == 0 and not allowed_full_calendar):
            n07_bad.append(account)
        top_partner, partner_count, partner_share, partner_unique = _top_share(
            sub["trading_partner"]
        )
        top_type, type_count, type_share, type_unique = _top_share(sub["counterparty_type"])
        n08_metric[account] = {
            "name": name,
            "top_trading_partner": top_partner,
            "top_trading_partner_count": partner_count,
            "top_trading_partner_share": partner_share,
            "trading_partner_unique": partner_unique,
            "top_counterparty_type": top_type,
            "top_counterparty_type_count": type_count,
            "top_counterparty_type_share": type_share,
            "counterparty_type_unique": type_unique,
        }
        full_partner = partner_share == 1.0
        full_type = type_share == 1.0 and account not in SINGLE_COUNTERPARTY_TYPE_ALLOWED
        if full_partner or full_type:
            n08_bad.append(account)
        amount = sub[["debit_amount", "credit_amount"]].max(axis=1)
        amount = amount[amount.gt(0)]
        if amount.empty:
            amount_metric = {"rows": 0, "max_p50_ratio": None}
            n09_bad.append(account)
        else:
            p50 = float(amount.quantile(0.50))
            p95 = float(amount.quantile(0.95))
            max_value = float(amount.max())
            ratio = None if p50 <= 0 else float(max_value / p50)
            amount_metric = {
                "rows": int(len(amount)),
                "p50": p50,
                "p95": p95,
                "max": max_value,
                "max_p50_ratio": ratio,
                "p95_p50_ratio": None if p50 <= 0 else float(p95 / p50),
                "unique_amounts": int(amount.nunique()),
            }
            if ratio is None or ratio < 10.0:
                n09_bad.append(account)
        n09_metric[account] = {"name": name, **amount_metric}
        scenarios = sub["semantic_scenario_id"].fillna("").astype(str).str.strip()
        scenario_counts = scenarios.value_counts().head(10)
        woven_docs = int(
            sub[sub["semantic_scenario_id"].isin(WOVEN_ARCHETYPES)]["document_id"].nunique()
        )
        n10_metric[account] = {
            "name": name,
            "scenario_unique": int(scenarios.nunique()),
            "top_scenarios": {str(k): int(v) for k, v in scenario_counts.items()},
            "woven_docs": woven_docs,
            "woven_required": account in WOVEN_REQUIRED,
        }
        if account in WOVEN_REQUIRED and woven_docs == 0:
            n10_bad.append(account)
        mutation_cols = [
            col
            for col in df.columns
            if col.startswith("mutation_") or col == "detection_surface_hints"
        ]
        label_counts = {
            "is_fraud_true": int(
                sub["is_fraud"].fillna("").astype(str).str.lower().eq("true").sum()
            ),
            "is_anomaly_true": int(
                sub["is_anomaly"].fillna("").astype(str).str.lower().eq("true").sum()
            ),
            "fraud_type_nonblank": int(
                sub["fraud_type"].fillna("").astype(str).str.strip().ne("").sum()
            ),
        }
        for col in mutation_cols:
            label_counts[col] = int(sub[col].fillna("").astype(str).str.strip().ne("").sum())
        n11_metric[account] = {"name": name, **label_counts}
        if any(value != 0 for value in label_counts.values()):
            n11_bad.append(account)
    baseline_metric = {}
    present_accounts = set(df["gl_account"].astype(str))
    for account in sorted(BASELINE_ACCOUNTS):
        if account not in present_accounts:
            continue
        sub = df[df["gl_account"].astype(str).eq(account)]
        amount = sub[["debit_amount", "credit_amount"]].max(axis=1)
        amount = amount[amount.gt(0)]
        if amount.empty:
            baseline_metric[account] = {"rows": 0}
        else:
            p50 = float(amount.quantile(0.50))
            max_value = float(amount.max())
            baseline_metric[account] = {
                "rows": int(len(amount)),
                "p50": p50,
                "max": max_value,
                "max_p50_ratio": None if p50 <= 0 else float(max_value / p50),
            }
    n09_metric["_baseline_accounts"] = baseline_metric
    return [
        _verdict(
            "Gate 2",
            "N07",
            "PASS" if not n07_bad else "FAIL",
            {"bad_accounts": n07_bad, "accounts": n07_metric},
            "new-account company/year/month count variance and empty-cell realism",
        ),
        _verdict(
            "Gate 2",
            "N08",
            "PASS" if not n08_bad else "FAIL",
            {"bad_accounts": n08_bad, "accounts": n08_metric},
            "new-account counterparty diversity",
        ),
        _verdict(
            "Gate 2",
            "N09",
            "PASS" if not n09_bad else "FAIL",
            {"bad_accounts": n09_bad, "min_required_max_p50_ratio": 10.0, "accounts": n09_metric},
            "new-account amount heavy-tail realism",
        ),
        _verdict(
            "Gate 2",
            "N10",
            "PASS" if not n10_bad else "FAIL",
            {
                "bad_accounts": n10_bad,
                "allowed_woven_archetypes": sorted(WOVEN_ARCHETYPES),
                "accounts": n10_metric,
            },
            "new-account woven archetype membership",
        ),
        _verdict(
            "Gate 2",
            "N11",
            "PASS" if not n11_bad else "FAIL",
            {"bad_accounts": n11_bad, "accounts": n11_metric},
            "new-account normal-only label and provenance guard",
        ),
    ]
