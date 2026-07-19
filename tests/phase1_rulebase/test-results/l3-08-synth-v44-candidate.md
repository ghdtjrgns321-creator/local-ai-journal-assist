# L3-08 Synthetic Evaluation — DataSynth v44 Candidate

> Rule: `MissingOrCorruptedDescription`  
> Dataset: `data/journal/primary/datasynth_v44_candidate`  
> Years: 2022, 2023, 2024

## Label Population

| label / sidecar | rows | docs |
|---|---:|---:|
| `MissingOrCorruptedDescription` | 428 | 428 |
| `VagueDescription` | 113 | 113 |
| `missing_corrupted_description_truth.csv` | 428 | 428 |
| `description_boundary_normal_controls.csv` | 530 | 530 |

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

## Boundary Normal Controls

The v44 candidate adds boundary normal controls for description text that should **not** trigger Phase 1 L3-08.

| year | boundary docs | flagged docs | flagged boundary docs |
|---:|---:|---:|---:|
| 2022 | 169 | 182 | 0 |
| 2023 | 174 | 134 | 0 |
| 2024 | 187 | 112 | 0 |
| **Total** | 530 | 428 | 0 |

## Against `VagueDescription` Labels

This population is out-of-scope for Phase 1 L3-08 after the v43/v44 split. It should be evaluated under later NLP/LLM description analysis.

| year | docs | truth docs | flagged docs | TP | FP | FN | precision | recall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 106,675 | 24 | 182 | 5 | 177 | 19 | 2.7% | 20.8% |
| 2023 | 105,525 | 35 | 134 | 6 | 128 | 29 | 4.5% | 17.1% |
| 2024 | 106,993 | 54 | 112 | 8 | 104 | 46 | 7.1% | 14.8% |
| **Total** | 319,193 | 113 | 428 | 19 | 409 | 94 | 4.4% | 16.8% |

## Interpretation

- v44 preserves the v43 truth split: Phase 1 L3-08 aligns exactly with `MissingOrCorruptedDescription`.
- The new boundary normal controls do not trigger L3-08, so the detector is not overfiring on the added edge-case normal population.
- `VagueDescription` remains out-of-scope for Phase 1 and should not be used to judge L3-08 precision/recall.

