# D01 Account Activity Variance v57 Production Check

Source dataset: `data/journal/primary/datasynth`

Production freeze: `v57`

## Contract

D01 is an account-level analytical review rule. It should not be evaluated by document-level `is_anomaly` or `anomaly_type` precision/recall.

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
| `account_activity_variance_truth*` | confirmed D01 account-level truth |
| `account_activity_variance_normal_controls*` | expected D01 raw flag but normal business/control explanation |
| `account_activity_variance_review_population*` | full D01 account-level review population |

Important columns:

- `expected_d01_flag`: raw D01 account activity flag.
- `is_true_positive_account`: whether this account group is D01 truth.
- `scenario_type`: abnormal or normal-control scenario classification.
- `business_event_type`: reporting-friendly business event or anomaly context.
- `evaluation_bucket`: separates confirmed truth, normal business controls, review queue, and auxiliary non-D01 context.
- `normal_reason`: why a raw D01 flag should not be treated as confirmed anomaly.
- `precision_policy`: how the row should be handled in D01 precision interpretation.
- `related_document_ids`: sample documents supporting the account group.

## v57 Counts

| dataset | 2023 | 2024 | all |
|---|---:|---:|---:|
| truth | 145 | 191 | 336 |
| normal controls | 247 | 257 | 504 |
| review population | 392 | 448 | 840 |

Truth scenarios:

| scenario | count |
|---|---:|
| target_anomaly_concentrated_account | 227 |
| anomaly_supported_activity_shift | 87 |
| suspicious_new_or_bypass_account | 18 |
| revenue_expense_activity_surge | 4 |

Normal-control scenarios:

| scenario | count |
|---|---:|
| normal_business_volume_or_price_change | 155 |
| normal_investment_or_working_capital_change | 107 |
| review_only_activity_variance | 102 |
| non_d01_anomaly_not_account_variance_truth | 76 |
| normal_high_volume_operational_change | 64 |

v57 evaluation buckets:

| bucket | count | interpretation |
|---|---:|---|
| confirmed_truth | 336 | D01 account-level truth |
| normal_business_control | 326 | expected raw D01 flag, but normal business explanation |
| review_queue | 102 | D01 analytical review queue, not a confirmed FP |
| auxiliary_non_d01_context | 76 | document-level anomaly context, separated from D01 precision denominator |

v57 normal business event types:

| business_event_type | count |
|---|---:|
| price_increase | 126 |
| high_volume_operations | 64 |
| capex_investment_event | 58 |
| working_capital_timing | 35 |
| recurring_or_system_volume_shift | 19 |
| working_capital_or_investment_timing | 14 |
| entity_process_expansion | 7 |
| volume_growth | 3 |

## Evaluation Policy

- D01 evaluation should compare detected account groups against `account_activity_variance_truth`.
- `account_activity_variance_normal_controls` should be used to check whether the review UI and scorer explain normal high-variance accounts instead of calling all of them fraud.
- `review_queue` should not be treated as a hard FP. It is the intended analytical review queue for D01.
- `auxiliary_non_d01_context` should be reported separately from the D01 precision denominator.
- TP/FP/FN = 0 is not a valid acceptance goal for D01 because it is an analytical review signal.
- Row-level flags may be used for drill-down only after an account group is selected.
