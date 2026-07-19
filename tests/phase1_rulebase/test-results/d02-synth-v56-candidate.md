# D02 Monthly Pattern Shift v57 Production Check

Source dataset: `data/journal/primary/datasynth`

Production freeze: `v57`

## Contract

D02 is an account-level monthly distribution review rule. It should not be evaluated by document-level `is_anomaly` or nearby anomaly labels.

Correct truth unit:

- `fiscal_year`
- `company_code`
- `gl_account`

Comparison windows:

- 2023 vs 2022
- 2024 vs 2023
- 2022 is excluded unless a 2021 baseline is added.

## Sidecars

| sidecar stem | role |
|---|---|
| `monthly_pattern_shift_confirmed_anomalies*` | confirmed D02 account-level truth |
| `monthly_pattern_shift_normal_controls*` | normal seasonal/project/batch/stable monthly profile controls |
| `monthly_pattern_shift_review_population*` | D02 raw review population |
| `monthly_pattern_shift_exclusions*` | groups/rows excluded from D02 evaluation |

Important columns:

- `jsd`: Jensen-Shannon distance between prior/current monthly distributions.
- `expected_d02_flag`: raw D02 flag after JSD and guardrails.
- `is_true_positive_account`: whether this account group is D02 truth.
- `scenario_type`: confirmed or normal-control monthly shift scenario.
- `normal_reason`: why a raw D02 flag should not be treated as confirmed anomaly.
- `prior_distribution_json`, `current_distribution_json`: 12-month profile snapshots.
- `related_document_ids`: sample documents supporting the current-year account group.

## v57 Counts

| dataset | 2022 | 2023 | 2024 | all |
|---|---:|---:|---:|---:|
| confirmed anomalies | 0 | 170 | 176 | 346 |
| normal controls | 0 | 112 | 82 | 194 |
| review population | 0 | 262 | 235 | 497 |
| exclusions | 24 | 996 | 1,039 | 2,059 |

Confirmed scenarios:

| scenario | count |
|---|---:|
| target_anomaly_monthly_shift | 212 |
| manual_monthly_shift_with_target_anomaly | 104 |
| revenue_period_end_push | 16 |
| expense_deferral_or_yearend_concentration | 14 |

Normal-control scenarios:

| scenario | count |
|---|---:|
| normal_recurring_or_interface_batch | 130 |
| stable_monthly_profile | 43 |
| normal_project_or_bonus_expense_concentration | 12 |
| normal_seasonal_or_quarter_end_revenue | 9 |

Exclusion reasons:

| reason | count |
|---|---:|
| small_top_month_delta | 1,593 |
| insufficient_current_docs | 334 |
| blank_gl_account | 86 |
| no_prior_account_group_use_d01 | 18 |
| insufficient_prior_months | 15 |
| missing_current_account_group | 11 |
| insufficient_current_months | 2 |

## Evaluation Policy

- D02 evaluation should compare detected account groups against `monthly_pattern_shift_confirmed_anomalies`.
- `monthly_pattern_shift_normal_controls` should be used to check whether the UI/scorer explains normal seasonal, project, recurring, and stable-profile accounts.
- `monthly_pattern_shift_exclusions` should not be counted as FN. They are outside the D02 evaluation contract.
- TP/FP/FN = 0 is not a valid acceptance goal for D02 because it is an analytical review signal.
- Row-level flags are drill-down only after an account group is selected.
