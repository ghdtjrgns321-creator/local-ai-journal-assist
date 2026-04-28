# L4-01 RevenueManipulation v47 Candidate Check

Source candidate: `data/journal/primary/datasynth_v47_candidate`

## Contract

`RevenueManipulation` remains a broad fraud type. L4-01 is only the high-value revenue z-score anchor:

- Direct L4-01 truth: `labels/revenue_manipulation_l401_direct_truth*`
- Broad subtype coverage: `labels/revenue_manipulation_subtypes*`
- Combination/downstream coverage: `labels/revenue_manipulation_combination_coverage*`

Do not score L4-01 against every `RevenueManipulation` label.

## Added Subtype Labels

| year | high value | cutoff | reversal | period end | manual | process mismatch | low amount dispersion | total added |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 7 | 8 | 5 | 6 | 4 | 5 | 3 | 38 |
| 2023 | 9 | 11 | 7 | 5 | 8 | 6 | 4 | 50 |
| 2024 | 6 | 9 | 8 | 9 | 5 | 7 | 5 | 49 |
| all | 22 | 28 | 20 | 20 | 17 | 18 | 12 | 137 |

Existing broad `RevenueManipulation` labels remain in the dataset. Total `RevenueManipulation` labels after v47: 154.

## Anti-Fitting Check

| subtype | z-score behavior | evaluation meaning |
|---|---|---|
| `high_value_revenue_outlier` | all above L4-01 threshold | direct L4-01 truth |
| `cutoff_mismatch` | mixed, includes low and high z-score | L3-11 + revenue review coverage |
| `reversal_return_credit` | mostly low or moderate z-score | reversal/return coverage, not L4-01 direct truth |
| `period_end_push` | around z-score 2, below direct threshold | L3-04 + revenue coverage |
| `manual_revenue_entry` | around z-score 1.5 | L3-02 + revenue coverage |
| `process_account_mismatch` | around z-score 1.5 | L3-01 + revenue coverage |
| `composite_low_amount_dispersion` | below direct threshold | Phase 2/3 weak-signal coverage |

This is not a zero-FP/zero-FN fitting dataset. It makes only the high-value subtype directly friendly to L4-01 and keeps the other revenue-manipulation scenarios as combination or downstream coverage.
