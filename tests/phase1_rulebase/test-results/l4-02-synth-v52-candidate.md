# L4-02 Benford v52 Candidate Check

Source candidate: `data/journal/primary/datasynth_v52_candidate`

## Contract

Benford is a population/group-level rule. It should not be evaluated as document-level `BenfordViolation` recall/precision.

Correct truth unit:

- `fiscal_year`
- `company_code`
- `gl_account`

## Sidecars

- `labels/benford_finding_truth*`: group-level Benford findings
- `labels/benford_drilldown_candidates*`: candidate rows/documents inside anomalous groups
- `labels/benford_normal_groups*`: sufficiently large Benford-conforming normal groups
- `labels/benford_skipped_small_groups*`: groups below sample threshold

Existing `BenfordViolation` document labels are legacy references only.

## v52 Counts

| year | finding groups | drill-down candidates | normal groups | skipped small groups |
|---:|---:|---:|---:|---:|
| 2022 | 36 | 8,769 | 100 | 1,090 |
| 2023 | 32 | 7,793 | 116 | 1,080 |
| 2024 | 32 | 7,872 | 102 | 1,099 |
| all | 100 | 24,434 | 318 | 3,269 |

## Evaluation Policy

- Finding-level evaluation should compare detected `company_code + gl_account + year` findings against `benford_finding_truth`.
- Drill-down rows are audit candidates, not standalone confirmed fraud labels.
- Normal groups should be used to check false group findings.
- Document-level `BenfordViolation` precision/recall should not be used as the L4-02 acceptance metric.
