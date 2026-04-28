# L3-11 Synthetic Evaluation — DataSynth v46 Candidate

Dataset: `data/journal/primary/datasynth_v46_candidate`

## Summary

v46 adds source-event dates and truth sidecars for L3-11 cutoff review. This is not a perfect benchmark: it intentionally includes normal boundary controls, reasonable long-delay controls, and untestable missing-event-date controls.

| year | confirmed truth | raw L3-11 hit docs | TP | FN | reasonable-delay raw hits | normal-boundary hits | other FP |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 34 | 40 | 34 | 0 | 6 | 0 | 0 |
| 2023 | 43 | 52 | 43 | 0 | 9 | 0 | 0 |
| 2024 | 33 | 38 | 33 | 0 | 5 | 0 | 0 |
| all | 110 | 130 | 110 | 0 | 20 | 0 | 0 |

## Rerun Metrics

Re-run date: 2026-04-26

Command path: direct call to `src.detection.evidence_rules.ev02_cutoff_violation()` using current `config.settings`.

| year | docs | flagged rows | flagged docs | confirmed truth | TP | FP | FN | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 106,675 | 51 | 40 | 34 | 34 | 6 | 0 | 85.0% | 100.0% |
| 2023 | 105,525 | 72 | 52 | 43 | 43 | 9 | 0 | 82.7% | 100.0% |
| 2024 | 106,993 | 43 | 38 | 33 | 33 | 5 | 0 | 86.8% | 100.0% |
| all | 319,193 | 166 | 130 | 110 | 110 | 20 | 0 | 84.6% | 100.0% |

All 20 FP documents are `cutoff_reasonable_delay_controls`. There are no hits in `cutoff_normal_controls`, `cutoff_untestable_controls`, or outside the cutoff sidecars.

## Sidecars

| sidecar | total | 2022 | 2023 | 2024 |
|---|---:|---:|---:|---:|
| `cutoff_confirmed_anomalies` | 110 | 34 | 43 | 33 |
| `cutoff_review_population` | 130 | 40 | 52 | 38 |
| `cutoff_normal_controls` | 253 | 78 | 91 | 84 |
| `cutoff_reasonable_delay_controls` | 20 | 6 | 9 | 5 |
| `cutoff_untestable_controls` | 383 | 120 | 135 | 128 |

## FP/FN Findings

- FN: 0. Every confirmed `RevenueCutoffMismatch` / `ExpenseCutoffMismatch` document is detected.
- FP: 20 against confirmed-anomaly truth. These are intentional long-delay controls, not random spillover.
- Review-population recall: 100.0%. The detector hits all 130 `cutoff_review_population` documents.
- Normal-boundary control FP: 0.
- Untestable-control FP: 0.

Sample FP documents:

| year | document_id | account | process | posting_date | delivery_date | business-day diff | score | sidecar |
|---:|---|---|---|---|---|---:|---:|---|
| 2022 | `53e1b363-81e4-4900-971d-06d9f5c2e8b0` | `400260.0` | O2C | 2022-01-03 | 2021-12-15 | 13 | 0.433 | reasonable delay |
| 2022 | `f370cb16-6ffb-4538-98ee-49f1da732bd2` | `500150.0` | P2P | 2022-01-03 | 2022-01-18 | 11 | 0.367 | reasonable delay |
| 2023 | `b2de49c1-2563-41b5-8381-7de7945357a9` | `500370.0` | H2R | 2023-01-02 | 2023-01-19 | 13 | 0.433 | reasonable delay |
| 2023 | `38f38dd6-0f09-4683-a0c0-5f94bc65cf93` | `400340.0` | O2C | 2023-01-02 | 2022-12-21 | 8 | 0.267 | reasonable delay |
| 2024 | `7afa8c53-77d1-40db-b24b-8791cacde19c` | `400130.0` | H2R | 2024-01-01 | 2023-12-13 | 13 | 0.433 | reasonable delay |
| 2024 | `e02c9a47-91e4-43ba-8ef2-fdab0ba3bea5` | `500240.0` | P2P | 2024-01-01 | 2024-01-11 | 8 | 0.267 | reasonable delay |

## Interpretation

- `RevenueCutoffMismatch` labels: 71
- `ExpenseCutoffMismatch` labels: 39
- `cutoff_reasonable_delay_controls` are expected raw L3-11 hits but are not confirmed anomaly labels.
- `cutoff_untestable_controls` preserve the real-world case where no recognition-basis event date exists.
- This avoids the synthetic shortcut where every `delivery_date` gap is automatically a confirmed anomaly.

## Caveat

v46 is a candidate patch. It has not been promoted to `data/journal/primary/datasynth/` yet.
