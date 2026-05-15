---
name: pandera-validation
description: "Pandera DataFrameSchema validation for local-ai-assist audit GL/TB/IC data. Use when Codex defines or changes schemas, ledger validation, L1/L2/L3 validation layers, chart-of-accounts mapping, opening_balance/closing_balance semantics, or GL-to-TB aggregation checks."
---

# Pandera Validation

Use this skill for audit data validation in `local-ai-assist`: GL/TB/IC schemas, validation layering, COA mapping, and GL-to-TB reconciliation. Use `local-ai-assist-testing` for verification scope and `local-ai-assist-review` for review checklist coverage.

## Core Principle

Separate audit validation into three layers. Do not put structure, accounting logic, and statistical anomaly logic into one large schema.

| Layer | Responsibility | Failure Meaning |
|-------|----------------|-----------------|
| L1 structure | Required columns, types, not-null checks, basic domains | Data cannot be loaded reliably |
| L2 accounting | Debit/credit balance, COA mapping, period consistency | Ledger accounting contract is broken |
| L3 statistics | Distribution, frequency, outlier sanity checks | Review candidate or analysis signal |

Run L1 before L2. Run L2 before L3. L3 findings are review signals, not confirmed violations.

## Trigger Contexts

- `pandera.DataFrameSchema` or `DataFrameModel` changes.
- Validation code in `src/validation/`, ingest contracts, or dashboard redetection paths.
- GL, TB, IC schemas or required/recommended column behavior.
- Chart-of-accounts mapping or account classification.
- `opening_balance`, `closing_balance`, `period_delta`, or `running_balance` semantics.
- GL-to-TB aggregation or reconciliation checks.

## Layering Pattern

```python
import pandera.pandas as pa

L1_GL_SCHEMA = pa.DataFrameSchema(
    {
        "doc_no": pa.Column(str, nullable=False),
        "account_code": pa.Column(str, nullable=False),
        "debit": pa.Column(float, checks=pa.Check.ge(0), nullable=False),
        "credit": pa.Column(float, checks=pa.Check.ge(0), nullable=False),
        "post_date": pa.Column("datetime64[ns]", nullable=False),
    },
    strict=False,
)

L2_GL_SCHEMA = L1_GL_SCHEMA.set_checks(
    [
        pa.Check(
            lambda df: (df["debit"] * df["credit"]).eq(0).all(),
            error="one line has both debit and credit",
        ),
        pa.Check(
            lambda df: (
                df.groupby("doc_no")[["debit", "credit"]]
                .sum()
                .pipe(lambda x: (x["debit"] - x["credit"]).abs().lt(0.01).all())
            ),
            error="document-level debit/credit imbalance",
        ),
    ]
)
```

Keep L3 distribution checks outside L1/L2 schemas unless the project already has a dedicated validator for them.

## Project-Specific Traps

### Do Not Hardcode COA Values

Account codes vary by company, year, ERP, and legal entity. Do not embed literals such as `"1101"`, `"1150"`, or `"매출"` inside schema or rule code.

```python
# Bad
is_cash = df["account_code"].eq("1101")

# Good
coa = context.settings.account_mapping
is_cash = df["account_code"].isin(coa.cash_accounts)
```

Prefer project configuration and context-aware settings. If the mapping is relational, model it structurally in YAML or settings, such as receivable/payable pairs, instead of using a flat string list.

### Distinguish Closing Balance Meanings

`closing_balance` is ambiguous:

- Period delta: current-period net movement from GL aggregation.
- Running balance: opening balance plus period delta.

Use explicit names when possible:

- `period_delta` for current-period net movement.
- `running_balance` for cumulative ending balance.

If an existing contract requires `closing_balance`, add a short docstring/comment and UI label clarifying whether it is current-period movement or ending balance. In this project, GL files may lack opening entries, so a GL-derived TB "closing" value can be only current-period movement.

### Validate Opening Balance Deliberately

Missing `opening_balance` can make running balances meaningless. Do not infer a true beginning balance from GL movement alone.

```python
pa.Check(
    lambda df: (
        df.groupby(["company_id", "fiscal_year", "account_code"])["opening_balance"]
        .first()
        .notna()
        .all()
    ),
    error="opening_balance missing for account/year",
)
```

If `opening_balance` is optional in a source, surface graceful degradation and label derived values as movement-only.

### GL-to-TB Reconciliation

For GL-to-TB checks:

- Aggregate by company, engagement/year, account, and currency when present.
- Compare debit/credit or net movement after monetary rounding; see `accounting-precision`.
- Treat optional TB inputs as validation coverage gaps, not code defects.
- Keep mixed-currency aggregates separated unless a configured FX normalization path exists.

## Anti-Patterns

| Avoid | Reason | Prefer |
|-------|--------|--------|
| One schema with L1+L2+L3 checks | One failure hides the next validation layer | Sequential schemas or validators |
| Regex-only account classification | COA changes silently break rules | Config/context-backed COA mapping |
| `closing_balance` as a catch-all | UI and export labels become misleading | Explicit `period_delta` / `running_balance` |
| Treating L3 outlier as violation | PHASE1 is a review queue | Review-only signal wording |

## Local Files To Check

- `src/validation/`
- `src/ingest/`
- `src/pipeline.py`
- `config/settings.py`
- `docs/pre-plan/04-validation.md`
