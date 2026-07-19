# L4-05 Abnormal Hours v53 Candidate Cleanup

Source candidate: `data/journal/primary/datasynth_v53_candidate`

## Patch Goal

Previous DataSynth candidates had overlap between confirmed `AbnormalHoursConcentration` labels and `normal_after_hours_context`.

That makes evaluation invalid because the same document is both positive truth and normal background.

## Contract

L4-05 confirmed truth is human user behavior only.

- Exclude automated/system/recurring/batch/interface sources from confirmed labels.
- Exclude `automated_system`, `SYSTEM`, and `IC_GENERATOR` style system identities.
- `normal_after_hours_context` must contain only normal background documents without any anomaly label.
- Sidecars must store detector threshold context.

## v53 Result

| item | count |
|---|---:|
| `AbnormalHoursConcentration` labels | 27 |
| `abnormal_hours_concentration_cases` | 27 |
| `normal_after_hours_context` | 6,734 |
| L4-05 / normal overlap | 0 |
| any anomaly / normal overlap | 0 |

## Year Split

| year | confirmed | normal context |
|---:|---:|---:|
| 2022 | 8 | 2,368 |
| 2023 | 10 | 2,197 |
| 2024 | 9 | 2,169 |

## Confirmed Label Shape

- sources: `manual` 26, `adjustment` 1
- users: 5 distinct human users
- personas: `manager`, `controller`, `junior_accountant`, `senior_accountant`
- selection metadata includes detector sigma threshold, user ratio, population mean/std, threshold, midnight docs, and excluded auto sources

## Anti-Fitting Note

Most labels are high-context human abnormal-hours cases, not all guaranteed sigma outliers. This keeps L4-05 as a behavior-review signal and avoids turning normal after-hours/system processing into confirmed anomalies.
