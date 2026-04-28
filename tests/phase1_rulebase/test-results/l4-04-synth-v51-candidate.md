# L4-04 Rare Account Pair v51 Candidate Cleanup

Source candidate: `data/journal/primary/datasynth_v51_candidate`

## Patch Goal

v50 had invalid L4-04 confirmed labels where one side of the debit-credit pair was blank, for example `500060->`.

That is not an unusual account-pair case. It belongs to missing-field / missing-account validation, not L4-04.

## Contract

L4-04 `UnusualAccountPair` truth requires both sides of the pair:

- debit account is non-empty
- credit account is non-empty
- pair format is `debit_account->credit_account`
- blank-account documents may remain in MissingField-style labels, but not in L4-04 confirmed truth

## v51 Result

| item | count |
|---|---:|
| `UnusualAccountPair` labels | 52 |
| `BatchAnomaly` labels preserved from v50 | 175 |
| `rare_account_pair_review_population` | 3,503 |
| `rare_account_pair_confirmed_anomalies` | 52 |
| `rare_account_pair_normal_controls` | 258 |
| blank pairs in review population | 0 |
| blank pairs in confirmed anomalies | 0 |
| blank pairs in normal controls | 0 |

## Year Split

| year | review population | confirmed anomalies | normal controls |
|---:|---:|---:|---:|
| 2022 | 1,145 | 17 | 80 |
| 2023 | 1,124 | 19 | 86 |
| 2024 | 1,234 | 16 | 92 |

## Anti-Fitting Note

This patch only fixes invalid blank-account L4-04 truth. It does not label every rare pair as an anomaly. Normal rare-pair controls and the broad review population remain separate.
