# L3-05 WeekendPosting v41 Candidate Evaluation

Run date: 2026-04-25

Dataset:
- `data/journal/primary/datasynth_v41_candidate/journal_entries_2022.csv`
- `data/journal/primary/datasynth_v41_candidate/journal_entries_2023.csv`
- `data/journal/primary/datasynth_v41_candidate/journal_entries_2024.csv`
- Labels: `data/journal/primary/datasynth_v41_candidate/labels/anomaly_labels.csv`
- v41 sidecars:
  - `labels/weekend_review_population_YYYY.csv`
  - `labels/weekend_confirmed_anomalies_YYYY.csv`
  - `labels/normal_weekend_context_YYYY.csv`

Detector basis:
- Current implementation: `is_weekend OR is_holiday`
- Confirmed anomaly truth: `WeekendPosting`
- Review population truth: all weekend/holiday postings
- Comparison unit: `document_id`

## Current Detector Scope

This uses the current L3-05 implementation, including Korean public holidays.

| year | rows | docs | confirmed label docs | raw L3-05 docs | TP | FP vs confirmed | FN | precision vs confirmed | recall |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022 | 373,425 | 106,675 | 6 | 6,023 | 6 | 6,017 | 0 | 0.10% | 100.00% |
| 2023 | 366,465 | 105,525 | 8 | 9,316 | 8 | 9,308 | 0 | 0.09% | 100.00% |
| 2024 | 369,545 | 106,993 | 15 | 8,968 | 15 | 8,953 | 0 | 0.17% | 100.00% |
| ALL | 1,109,435 | 319,193 | 29 | 24,307 | 29 | 24,278 | 0 | 0.12% | 100.00% |

## v41 Sidecar Contract

The v41 sidecars correctly separate confirmed anomalies from normal non-business-day context. Confirmed anomalies are included in the review population, normal controls are also included as review candidates, and confirmed anomalies do not overlap normal controls.

| year | review population | confirmed anomalies | normal weekend context | review/confirmed overlap | review/normal overlap | confirmed/normal overlap |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022 | 6,023 | 6 | 1,100 | 6 | 1,100 | 0 |
| 2023 | 9,316 | 8 | 1,080 | 8 | 1,080 | 0 |
| 2024 | 8,968 | 15 | 1,060 | 15 | 1,060 | 0 |
| ALL | 24,307 | 29 | 3,240 | 29 | 3,240 | 0 |

## Sidecar Coverage Check

The v41 `weekend_review_population` sidecars match the current raw L3-05 condition exactly.

| year | raw L3-05 minus review sidecar | review sidecar minus raw L3-05 | confirmed sidecar minus labels | labels minus confirmed sidecar |
| ---: | ---: | ---: | ---: | ---: |
| 2022 | 0 | 0 | 0 | 0 |
| 2023 | 0 | 0 | 0 | 0 |
| 2024 | 0 | 0 | 0 | 0 |
| ALL | 0 | 0 | 0 | 0 |

Breakdown of raw L3-05 candidates:

| year | weekend only | weekday holiday only | weekend and holiday | sidecar review docs |
| ---: | ---: | ---: | ---: | ---: |
| 2022 | 2,998 | 2,826 | 199 | 6,023 |
| 2023 | 2,939 | 6,222 | 155 | 9,316 |
| 2024 | 2,914 | 5,973 | 81 | 8,968 |
| ALL | 8,851 | 15,021 | 435 | 24,307 |

## Pure Weekend Reference

This excludes weekday holidays and checks only Saturday/Sunday.

| year | confirmed label docs | weekend docs | TP | FP vs confirmed | FN |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2022 | 6 | 3,197 | 6 | 3,191 | 0 |
| 2023 | 8 | 3,094 | 8 | 3,086 | 0 |
| 2024 | 15 | 2,995 | 15 | 2,980 | 0 |
| ALL | 29 | 9,286 | 29 | 9,257 | 0 |

## Label Date Check

All confirmed `WeekendPosting` labels in 2022~2024 are Saturday/Sunday.

| year | Saturday | Sunday | weekday holiday only | weekday non-holiday |
| ---: | ---: | ---: | ---: | ---: |
| 2022 | 4 | 2 | 0 | 0 |
| 2023 | 4 | 4 | 0 | 0 |
| 2024 | 7 | 8 | 0 | 0 |
| ALL | 15 | 14 | 0 | 0 |

## Judgment

- Misses: none. Current L3-05 catches all 29 confirmed `WeekendPosting` labels.
- Confirmed label quality: good. All confirmed labels land on Saturday/Sunday.
- v41 contract: fixed. `weekend_review_population` now covers the full current detector scope: `is_weekend OR is_holiday`.
- False positives vs confirmed labels: 24,278 documents are not confirmed `WeekendPosting` anomalies, but under the v41 contract they are review population, not confirmed-anomaly false positives.
- Normal controls: 3,240 routine weekend/holiday contexts are explicitly separated and do not overlap confirmed anomalies.

## Conclusion

v41 resolves the v40 holiday sidecar mismatch. L3-05 should be evaluated as:

- recall against confirmed `WeekendPosting` labels: 100%;
- review-population coverage against `weekend_review_population`: 100%;
- raw hit volume not used as confirmed-anomaly precision denominator.

No L3-05 label miss or sidecar coverage defect remains in v41.
