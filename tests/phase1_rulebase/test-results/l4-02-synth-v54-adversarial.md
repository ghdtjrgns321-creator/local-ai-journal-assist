# L4-02 Benford v54 Adversarial Candidate Check

Source candidate: `data/journal/primary/datasynth_v54_candidate`

## Purpose

v54 does not replace the v52 Benford contract truth. It adds adversarial and holdout sidecars so L4-02 is not judged only by a rule-shaped answer key.

The intended split is:

- `v52` contract truth: confirms the detector can find known `fiscal_year + company_code + gl_account` Benford findings.
- `v54` robustness sidecars: checks boundary, small sample, normal skew, company-specific behavior, weak anomalies, and noisy digit findings.

## Sidecars

| sidecar stem | role |
|---|---|
| `benford_boundary_groups*` | MAD near 0.012 threshold; avoid brittle threshold fitting |
| `benford_small_sample_controls*` | sample size near 500; check minimum sample behavior |
| `benford_business_skew_normal_groups*` | normal operational digit skew |
| `benford_company_specific_normals*` | same GL can differ by company |
| `benford_weak_fraud_holdout*` | weak Benford anomaly holdout |
| `benford_high_mad_normal_controls*` | high MAD with potential normal explanation |
| `benford_broad_digit_findings*` | noisy findings with many flagged digits |
| `benford_adversarial_holdout*` | combined robustness set |

## v54 Counts

| dataset | 2022 | 2023 | 2024 | all |
|---|---:|---:|---:|---:|
| boundary groups | 12 | 12 | 12 | 36 |
| small sample controls | 16 | 16 | 16 | 48 |
| business skew normal groups | 10 | 10 | 10 | 30 |
| company specific normals | 8 | 8 | 8 | 24 |
| weak fraud holdout | 5 | 3 | 4 | 12 |
| high MAD normal controls | 0 | 4 | 4 | 8 |
| broad digit findings | 6 | 6 | 6 | 18 |
| combined adversarial holdout | 57 | 59 | 60 | 176 |

## Anti-Fitting Notes

- v54 keeps journal rows and v52 group-level truth unchanged.
- Weak fraud and high-MAD normal buckets are intentionally not padded to equal counts when the source data lacks qualifying groups.
- These sidecars should not be used to demand TP/FN/FP = 0. They are for robustness review and portfolio demonstration.
- Document-level `BenfordViolation` remains legacy reference only and should not be used as the L4-02 acceptance metric.
