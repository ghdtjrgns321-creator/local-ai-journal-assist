# L4-04 Rare Account Pair v49 Candidate Check

Source candidate: `data/journal/primary/datasynth_v49_candidate`

## Contract

L4-04 is a rare debit-credit account-pair review anchor, not an exhaustive fraud classifier.

- Confirmed anomaly truth: `labels/rare_account_pair_confirmed_anomalies*`
- Review coverage population: `labels/rare_account_pair_review_population*`
- Normal rare-pair controls: `labels/rare_account_pair_normal_controls*`
- Cartesian guardrail exclusions: `labels/rare_account_pair_excluded_large_docs*`

Do not treat every rare account-pair document as a confirmed anomaly.

## Rare Pair Profile

| metric | value |
|---|---:|
| percentile | 0.01 |
| threshold count | 1.0 |
| distinct debit-credit pairs | 51,342 |
| rare pair types | 4,967 |
| review candidate documents | 3,561 |
| >100-line excluded documents | 243 |

## Truth And Controls

| year | review population | confirmed anomalies | normal rare-pair controls |
|---:|---:|---:|---:|
| 2022 | 1,159 | 17 | 80 |
| 2023 | 1,143 | 19 | 86 |
| 2024 | 1,259 | 16 | 92 |
| all | 3,561 | 52 | 258 |

## Anti-Fitting Check

This patch is not designed to make L4-04 precision perfect.

- Confirmed anomalies are a small subset of rare account-pair documents.
- Normal rare-pair business events remain as controls.
- The review population is broader than `UnusualAccountPair` labels by design.
- Large documents excluded by the detector's Cartesian guardrail are tracked separately.
