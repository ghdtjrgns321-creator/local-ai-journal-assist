# Contract V2 B-axis Case Readability Review

- artifact: `artifacts\phase1_cases\_anonymous\phase1case__anonymous_datasynth_v126_profiled_phase1_20260514T050639Z.json`
- total cases: `17011`
- reviewed cases: `120`
- recommendation: `WARN`

## Flag Counts

- `action_overload`: 67
- `duplicate_evidence_rows`: 81
- `evidence_overload`: 76
- `multi_theme_summary_too_generic`: 71
- `unknown_counterparty_context`: 12

## Theme Summary

| primary_theme          |   reviewed_cases |   high_cases |   avg_rule_count |   avg_evidence_rows |   avg_action_count |   avg_unknown_counterparty_doc_ratio |   cases_with_flags |
|:-----------------------|-----------------:|-------------:|-----------------:|--------------------:|-------------------:|-------------------------------------:|-------------------:|
| control_failure        |               20 |           20 |             7.75 |              382.45 |              15.45 |                                0.154 |                 20 |
| data_integrity_failure |               20 |           16 |             7.15 |               66.4  |              14.3  |                                0.14  |                 19 |
| duplicate_or_outflow   |               20 |            6 |             5.05 |               67.15 |              10.1  |                                0.1   |                 19 |
| logic_mismatch         |               20 |            4 |             5.35 |              196.75 |              10.7  |                                0.038 |                 20 |
| statistical_outlier    |               20 |            3 |             7.3  |               18.45 |              14.6  |                                0.042 |                 17 |
| timing_anomaly         |               20 |           20 |             7.65 |               36.15 |              15.3  |                                0.124 |                 20 |

## Flagged Sample Cases

| case_id                           | primary_theme          | priority_band   |   rule_count |   evidence_rows |   recommended_action_count |   unknown_counterparty_doc_ratio | flags                                                                                     |
|:----------------------------------|:-----------------------|:----------------|-------------:|----------------:|---------------------------:|---------------------------------:|:------------------------------------------------------------------------------------------|
| case_timing_anomaly_05438         | timing_anomaly         | high            |            9 |              39 |                         18 |                            0.286 | evidence_overload,action_overload,multi_theme_summary_too_generic                         |
| case_timing_anomaly_05572         | timing_anomaly         | high            |            7 |              47 |                         14 |                            0.143 | evidence_overload,action_overload                                                         |
| case_timing_anomaly_06832         | timing_anomaly         | high            |            7 |              49 |                         14 |                            0.167 | evidence_overload,duplicate_evidence_rows,action_overload                                 |
| case_timing_anomaly_10543         | timing_anomaly         | high            |            7 |              37 |                         14 |                            0     | evidence_overload,duplicate_evidence_rows,action_overload                                 |
| case_control_failure_02134        | control_failure        | high            |            6 |             630 |                         12 |                            0     | evidence_overload,duplicate_evidence_rows,multi_theme_summary_too_generic                 |
| case_timing_anomaly_05453         | timing_anomaly         | high            |           10 |              45 |                         20 |                            0.222 | evidence_overload,action_overload,multi_theme_summary_too_generic                         |
| case_control_failure_00211        | control_failure        | high            |            8 |              68 |                         16 |                            0     | evidence_overload,duplicate_evidence_rows,action_overload,multi_theme_summary_too_generic |
| case_data_integrity_failure_00008 | data_integrity_failure | high            |           11 |             272 |                         22 |                            0     | evidence_overload,duplicate_evidence_rows,action_overload,multi_theme_summary_too_generic |
| case_timing_anomaly_05328         | timing_anomaly         | high            |            7 |              25 |                         14 |                            0.25  | action_overload                                                                           |
| case_timing_anomaly_05037         | timing_anomaly         | high            |            6 |              36 |                         12 |                            0.429 | evidence_overload,unknown_counterparty_context,multi_theme_summary_too_generic            |
| case_timing_anomaly_06240         | timing_anomaly         | high            |            9 |              46 |                         18 |                            0     | evidence_overload,action_overload,multi_theme_summary_too_generic                         |
| case_control_failure_02561        | control_failure        | high            |            7 |              67 |                         14 |                            0     | evidence_overload,duplicate_evidence_rows,action_overload,multi_theme_summary_too_generic |
| case_timing_anomaly_12279         | timing_anomaly         | high            |            8 |              35 |                         16 |                            0     | evidence_overload,action_overload,multi_theme_summary_too_generic                         |
| case_timing_anomaly_14544         | timing_anomaly         | high            |            7 |              14 |                         14 |                            0     | action_overload,multi_theme_summary_too_generic                                           |
| case_timing_anomaly_07895         | timing_anomaly         | high            |            8 |              21 |                         16 |                            0     | action_overload,multi_theme_summary_too_generic                                           |
| case_control_failure_00208        | control_failure        | high            |           10 |              53 |                         20 |                            0     | evidence_overload,duplicate_evidence_rows,action_overload,multi_theme_summary_too_generic |
| case_timing_anomaly_08231         | timing_anomaly         | high            |            9 |              76 |                         18 |                            0.231 | evidence_overload,action_overload,multi_theme_summary_too_generic                         |
| case_control_failure_02252        | control_failure        | high            |            6 |            2326 |                         12 |                            0     | evidence_overload,duplicate_evidence_rows,multi_theme_summary_too_generic                 |
| case_timing_anomaly_07252         | timing_anomaly         | high            |            5 |              33 |                         10 |                            0     | evidence_overload                                                                         |
| case_control_failure_00759        | control_failure        | high            |            8 |              42 |                         16 |                            0.286 | evidence_overload,duplicate_evidence_rows,action_overload,multi_theme_summary_too_generic |

## Interpretation

- A-axis truth alignment is not retested here.
- B-axis passes structural completeness: sampled cases have narratives, review focus, actions, documents, and rule evidence.
- WARN remains because top cases often contain duplicated row-level evidence and too many suggested actions for a compact auditor review surface.