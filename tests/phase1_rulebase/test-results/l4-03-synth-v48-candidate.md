# L4-03 High Amount v48 Candidate Check

Source candidate: `data/journal/primary/datasynth_v48_candidate`

## Contract

L4-03 is a high-amount review anchor, not an exhaustive fraud classifier.

- Confirmed anomaly truth: `labels/high_amount_confirmed_anomalies*`
- Review coverage population: `labels/high_amount_review_population*`
- Normal large-transaction controls: `labels/high_amount_normal_controls*`
- Near-threshold controls: `labels/high_amount_boundary_controls*`

Do not treat every large normal business event as a confirmed false positive.

## Added Truth And Controls

| year | confirmed anomalies | review population | normal high-amount controls | boundary controls |
|---:|---:|---:|---:|---:|
| 2022 | 14 | 69 | 55 | 35 |
| 2023 | 13 | 77 | 64 | 42 |
| 2024 | 14 | 72 | 58 | 39 |
| all | 41 | 218 | 177 | 116 |

The confirmed subset adds both `UnusuallyHighAmount` and `StatisticalOutlier` labels. Normal high-amount controls remain unlabeled as anomalies.

## Anti-Fitting Check

This patch is not designed to make L4-03 precision perfect.

- Confirmed anomalies are only a small subset of high amount candidates.
- Normal high-amount business events remain in the review population.
- Boundary controls sit near the z-score threshold and should not be forced into positive labels.
- Precision against confirmed labels is therefore limited by design; coverage and prioritization should be evaluated separately.
