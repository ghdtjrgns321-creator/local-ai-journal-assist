# L3-05 WeekendPosting v40 Candidate Evaluation

Run date: 2026-04-25

Dataset:
- `data/journal/primary/datasynth_v40_candidate/journal_entries_2022.csv`
- `data/journal/primary/datasynth_v40_candidate/journal_entries_2023.csv`
- `data/journal/primary/datasynth_v40_candidate/journal_entries_2024.csv`
- Labels: `data/journal/primary/datasynth_v40_candidate/labels/anomaly_labels.csv`
- v40 sidecars:
  - `labels/weekend_review_population_YYYY.csv`
  - `labels/weekend_confirmed_anomalies_YYYY.csv`
  - `labels/normal_weekend_context_YYYY.csv`

Detector basis:
- Current implementation: `is_weekend OR is_holiday`
- v40 review sidecar actual contents: Saturday/Sunday only
- Confirmed anomaly truth: `WeekendPosting`
- Comparison unit: `document_id`

## Current Detector Scope

This uses the current L3-05 implementation, including Korean public holidays.

| year | rows | docs | confirmed label docs | raw L3-05 docs | TP | FP vs confirmed | FN | precision vs confirmed | recall |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022 | 373,425 | 106,675 | 6 | 6,023 | 6 | 6,017 | 0 | 0.10% | 100.00% |
| 2023 | 366,465 | 105,525 | 8 | 9,316 | 8 | 9,308 | 0 | 0.09% | 100.00% |
| 2024 | 369,545 | 106,993 | 15 | 8,968 | 15 | 8,953 | 0 | 0.17% | 100.00% |
| ALL | 1,109,435 | 319,193 | 29 | 24,307 | 29 | 24,278 | 0 | 0.12% | 100.00% |

## v40 Sidecar Contract

The sidecars correctly separate confirmed anomalies from normal weekend context. Confirmed anomalies are included in the review population, normal controls are also included as review candidates, and confirmed anomalies do not overlap normal controls.

| year | review population | confirmed anomalies | normal weekend context | review/confirmed overlap | review/normal overlap | confirmed/normal overlap |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022 | 3,197 | 6 | 640 | 6 | 640 | 0 |
| 2023 | 3,094 | 8 | 620 | 8 | 620 | 0 |
| 2024 | 2,995 | 15 | 600 | 15 | 600 | 0 |
| ALL | 9,286 | 29 | 1,860 | 29 | 1,860 | 0 |

## Pure Weekend Reference

This excludes weekday holidays and checks only Saturday/Sunday. It matches the v40 review sidecar counts exactly.

| year | confirmed label docs | weekend docs | TP | FP vs confirmed | FN |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2022 | 6 | 3,197 | 6 | 3,191 | 0 |
| 2023 | 8 | 3,094 | 8 | 3,086 | 0 |
| 2024 | 15 | 2,995 | 15 | 2,980 | 0 |
| ALL | 29 | 9,286 | 29 | 9,257 | 0 |

## Sidecar Coverage Check

The v40 `weekend_review_population` sidecars contain all Saturday/Sunday postings but do not contain weekday holiday postings. This is the main contract mismatch found.

| year | raw L3-05 minus review sidecar | review sidecar minus raw L3-05 | confirmed sidecar minus labels | labels minus confirmed sidecar |
| ---: | ---: | ---: | ---: | ---: |
| 2022 | 2,826 | 0 | 0 | 0 |
| 2023 | 6,222 | 0 | 0 | 0 |
| 2024 | 5,973 | 0 | 0 | 0 |
| ALL | 15,021 | 0 | 0 | 0 |

Breakdown of raw L3-05 candidates:

| year | weekend only | weekday holiday only | weekend and holiday | sidecar review docs |
| ---: | ---: | ---: | ---: | ---: |
| 2022 | 2,998 | 2,826 | 199 | 3,197 |
| 2023 | 2,939 | 6,222 | 155 | 3,094 |
| 2024 | 2,914 | 5,973 | 81 | 2,995 |
| ALL | 8,851 | 15,021 | 435 | 9,286 |

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
- v40 improvement: confirmed anomalies and normal weekend controls are now separated, so raw L3-05 hit volume should not be used as the confirmed-anomaly precision denominator.
- Remaining issue: current detector scope is `weekend OR holiday`, but v40 review sidecars only cover Saturday/Sunday. The 15,021 weekday-holiday raw hits are not represented in `weekend_review_population`, despite the v40 policy text saying weekend/holiday postings are review candidates.

## Recommendation

Choose one contract and make code/data/docs consistent:

1. If L3-05 is intended to be weekend-only, change rule/docs from `is_weekend OR is_holiday` to weekend-only, or move holiday handling to a separate rule.
2. If L3-05 is intended to remain weekend/holiday, add weekday holiday postings to `weekend_review_population` and normal holiday context sidecars.

Under either contract, keep confirmed `WeekendPosting` labels separate from review population. v40's sidecar design is the right evaluation shape; the remaining fix is the holiday scope mismatch.
