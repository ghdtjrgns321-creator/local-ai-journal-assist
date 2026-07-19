# L3-08 Synthetic Evaluation — DataSynth v43 Candidate

> Rule: `MissingOrCorruptedDescription`  
> Dataset: `data/journal/primary/datasynth_v43_candidate`  
> Years: 2022, 2023, 2024

## Label Population

| label / sidecar | rows | docs |
|---|---:|---:|
| `MissingOrCorruptedDescription` | 428 | 428 |
| `VagueDescription` | 113 | 113 |
| `missing_corrupted_description_truth.csv` | 428 | 428 |

## Row Quality Counts

| year | normal rows | missing rows | corrupted rows |
|---:|---:|---:|---:|
| 2022 | 373,180 | 234 | 11 |
| 2023 | 366,279 | 171 | 15 |
| 2024 | 369,399 | 128 | 18 |

## Against `MissingOrCorruptedDescription` Labels

| year | docs | truth docs | flagged docs | TP | FP | FN | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 106,675 | 182 | 182 | 182 | 0 | 0 | 100.0% | 100.0% |
| 2023 | 105,525 | 134 | 134 | 134 | 0 | 0 | 100.0% | 100.0% |
| 2024 | 106,993 | 112 | 112 | 112 | 0 | 0 | 100.0% | 100.0% |
| **Total** | 319,193 | 428 | 428 | 428 | 0 | 0 | 100.0% | 100.0% |

## Against `missing_corrupted_description_truth.csv`

| year | docs | truth docs | flagged docs | TP | FP | FN | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 106,675 | 182 | 182 | 182 | 0 | 0 | 100.0% | 100.0% |
| 2023 | 105,525 | 134 | 134 | 134 | 0 | 0 | 100.0% | 100.0% |
| 2024 | 106,993 | 112 | 112 | 112 | 0 | 0 | 100.0% | 100.0% |
| **Total** | 319,193 | 428 | 428 | 428 | 0 | 0 | 100.0% | 100.0% |

## Against `VagueDescription` Labels

This is intentionally out-of-scope for Phase 1 L3-08 after the split. `VagueDescription` is now a separate vague/risky-description population for later NLP/LLM treatment.

| year | docs | truth docs | flagged docs | TP | FP | FN | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 106,675 | 24 | 182 | 5 | 177 | 19 | 2.7% | 20.8% |
| 2023 | 105,525 | 35 | 134 | 6 | 128 | 29 | 4.5% | 17.1% |
| 2024 | 106,993 | 54 | 112 | 8 | 104 | 46 | 7.1% | 14.8% |
| **Total** | 319,193 | 113 | 428 | 19 | 409 | 94 | 4.4% | 16.8% |

## Interpretation

- v43 correctly splits Phase 1 `MissingOrCorruptedDescription` from later-stage `VagueDescription`.
- L3-08 is now perfectly aligned with both the new label and the sidecar truth table on the candidate dataset.
- The low score against `VagueDescription` is expected and should not be used to evaluate Phase 1 L3-08.

