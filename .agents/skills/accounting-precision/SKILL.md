---
name: accounting-precision
description: "Float precision and rounding rules for local-ai-assist audit calculations. Use when Codex compares amounts to materiality, rounds monetary values, handles float64 aggregation drift, processes mixed currencies, or validates VAT/tax_amount including exempt and zero-rated transactions."
---

# Accounting Precision

Use this skill for monetary calculations in `local-ai-assist`. Keep it focused on audit amount comparisons, rounding boundaries, mixed-currency behavior, and VAT false-positive prevention. For test selection, use `local-ai-assist-testing`.

## Core Principle

`float64` aggregation creates small residuals. Monetary comparisons must round at the comparison boundary, currency handling must be explicit, and VAT checks must exclude legitimate exempt or zero-rated transactions.

## Trigger Contexts

- Comparing an amount, difference, or aggregate with materiality.
- Calling `round`, `Series.round`, `np.isclose`, or direct float comparisons.
- Aggregating GL/TB amounts across many rows.
- Handling `currency`, `transaction_currency`, or base/foreign amount columns.
- Validating `vat`, `tax_amount`, `tax_rate`, or `supply_amount`.
- Writing dashboard KPIs, exports, detection thresholds, or GL-to-TB reconciliation.

## Materiality Comparison

Round immediately before comparing against materiality. Choose decimals from accounting policy or currency, not from convenience.

```python
# Bad
if abs(actual - expected) > materiality:
    flag_as_difference()

# Good
diff = round(abs(actual - expected), amount_decimals)
limit = round(materiality, amount_decimals)
if diff > limit:
    flag_as_difference()
```

Typical defaults:

- KRW-only ledgers: `amount_decimals = 0` if the source is integer won.
- Foreign currency or mixed ledgers: use the currency-specific minor unit, often `2`.
- Internal normalized analytics: document the chosen precision in a module constant.

Boundary cases matter. A residual such as `0.00000000000014` must not become a false exception when materiality is zero or near zero.

## Pandas `Series.round()` Trap

`Series.round(decimals)` accepts a scalar integer, not row-level decimals. This fails for mixed-currency rows:

```python
# Bad
df["rounded_amount"] = df["amount"].round(df["currency"].map(DECIMALS))
```

Use group-level rounding:

```python
DECIMALS = {"KRW": 0, "USD": 2, "EUR": 2}

def _round_currency(group: pd.Series) -> pd.Series:
    return group.round(DECIMALS.get(group.name, 2))

df["rounded_amount"] = (
    df.groupby("currency", dropna=False)["amount"].transform(_round_currency)
)
```

If exact decimal arithmetic is required, use `Decimal` in a narrow boundary layer. Avoid converting entire large GL populations to `Decimal` unless correctness requires it and performance is measured.

## Mixed-Currency Rules

Do not aggregate different currencies unless one of these is true:

- You group by currency and compare within each currency.
- You use a configured base currency amount already provided by the source.
- You apply a documented FX normalization path with rate source, date, and precision.

For GL-to-TB reconciliation, include currency in the grouping key when the source has it. If the source lacks currency but the engagement is known to be single-currency, make that assumption explicit near the validator or setting.

## VAT / Tax False Positives

Do not apply a 10% VAT expectation to every row. Tax-exempt and zero-rated transactions can legitimately have `tax_amount = 0` or missing tax amount.

```python
exempt_or_zero_mask = (
    df["tax_amount"].fillna(0).eq(0)
    | df["tax_code"].isin(EXEMPT_TAX_CODES)
    | df["tax_rate"].fillna(-1).eq(0)
)

target = df.loc[~exempt_or_zero_mask].copy()
ratio = target["tax_amount"] / target["supply_amount"]
violations = target[(ratio - 0.10).abs() > 0.001]
```

Use configured tax codes for:

- Exempt transactions, such as some medical, education, book, or agricultural cases.
- Zero-rated transactions, such as export sales.
- Special regimes that are not simple 10% VAT.

Rows with zero or missing `tax_amount` are not automatically suspicious. Decide whether they are excluded, reviewed separately, or flagged only when tax code and account context contradict the zero tax.

## Anti-Patterns

| Avoid | Problem | Prefer |
|-------|---------|--------|
| `if diff > 0` after float sums | Residuals become false positives | Rounded materiality comparison |
| Row-wise decimals passed to `Series.round()` | Pandas expects scalar decimals | `groupby("currency").transform(...)` |
| Aggregating all currencies together | Materiality and balances lose meaning | Currency grouping or FX normalization |
| VAT check on all rows | Exempt/zero-rated rows become false positives | Tax-code-aware target mask |
| `np.isclose` without domain precision | Tolerance becomes arbitrary | Named monetary precision constant |

## Local Files To Check

- `src/validation/`
- `src/detection/`
- `src/feature/`
- `dashboard/`
- `src/export/`
- `docs/archive/completed/raw-plan/04-validation.md`
- `docs/spec/DETECTION_RULES.md` when thresholds or tax rules change
