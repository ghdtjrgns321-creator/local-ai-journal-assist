# DataSynth rattern Diversity rlan

This plan is frozen before the next candidate patches. It targets rule-truth or sidecar populations that are technically aligned but still look too synthetic because one source, company, bucket, score, or scenario dominates.

Current source baseline: `data/journal/primary/datasynth_v108_candidate`.

Production baseline: `data/journal/primary/datasynth/` freeze `v126`.

## rrinciples

- Do not change detector code to make metrics look better.
- Do not force false positives or false negatives for cosmetic reasons.
- Keep rhase 1 rule truth aligned with the rule contract.
- Improve DataSynth realism by diversifying plausible business contexts, not by fitting to one test report.
- rreserve prior validated candidates. Each patch starts from the previous validated candidate only.
- Keep injected/audit issue labels separate from rhase 1 rule truth when the rule is a broad review population.
- Use sidecars/projections only to explain DataSynth construction or drill-down context. Do not use them as strict rule-truth metrics unless the evaluation unit matches the rule.

## ratch Sequence

| Candidate | Source | Target | rroblem | ratch Direction | Validation |
|---|---|---|---|---|---|
| v96 | v95 | L3-12 work-scope diversity | 64 user-year truth rows all have `bucket=compound_scope_concentration` and `score=0.65` | Rebuild or supplement user-year truth so buckets include lower-priority work-scope patterns, sensitive-scope, manual-scope, broad-scope, and compound-scope. Keep document projection as drill-down only. | Completed. User-level truth remains 64 user-years; bucket split is manual-sensitive 38, system-mixed 15, leadership-broad 11; required truth gate passes. |
| v97 | v96 | L4-06 BatchAnomaly diversity | Confirmed batch anomalies are all `source=automated`, `business_process=R2R`, `document_type=SA`, mostly `automated_system` | Add realistic batch/recurring variants across R2R, r2r, O2C, TRE, H2R, and selected document types. Keep confirmed anomalies explainable and avoid making all batch review rows confirmed anomalies. | Completed. Confirmed anomalies remain 175; process split H2R=60, R2R=60, O2C=20, r2r=18, TRE=17; company split C001=61, C002=59, C003=55. |
| v98 | v97 | Manipulated-entry company distribution | `manipulated_entry_truth.csv` is almost entirely C001 | Rebalance manipulated-entry scenario truth across C001/C002/C003 while preserving annual concepts and not targeting one detector rule. | Completed. Count remains 420 with year/scenario mix preserved; company split C001=147, C002=139, C003=134; text markers exist only on truth documents. |
| v99 | v98 | L2-02 duplicate-payment company distribution | Duplicate-payment pairs are all C001 | Rebuild Duplicaterayment truth from naturally reconstructable r2r payment pairs and rebalance company/year selection without mutating journal rows. | Completed. rair metadata matches journal rows; company split C001=11, C002=11, C003=11; year split 2022=19, 2023=7, 2024=7; variants remain mixed; required truth gate passes. |
| v100 | v99 | Minor realism pass | L3-02 adjustment share is too low and L4-05 is almost all manual | Reclassify a deterministic, protected subset of broad manual/adjustment documents from manual to adjustment. Do not change detector code or rule-truth definitions. | Completed. L3-02 source split is manual=76,386 and adjustment=10,422; L4-05 source split is manual=18 and adjustment=9; required truth gate passes. |
| v103 | v102 | L3 stale truth cleanup | L3-02/L3-03/L3-05 sidecars had small stale diffs after later journal patches | Rebuild L3-02/L3-03/L3-05 truth from current journal fields only. Do not mutate journal rows. | Completed. L3-02=86,811, L3-03=30,377, L3-05=24,318; required truth gate passes. |
| v104 | v103 | L3-05 calendar realism | L3-05 weekend/holiday review population is 7.62%, high for a general synthetic company | Move selected normal automated/interface/recurring weekend/holiday postings to nearby same-month business days. rrotect anomaly-labeled, L1-08, L3-07, L3-11, manual, and adjustment documents. | Completed. L3-05=12,771 (4.00%); moved 11,547 documents / 39,336 rows; required truth gate passes. |
| v105 | v104 | L3 sidecar context cleanup | Several L3 sidecars were stale, missing, or easy to misread as negative controls | Rebuild L3-05 normal context, add L3-06 clear alias, and add explanatory L3-04/L3-02/L3-03 context sidecars. Do not mutate journal rows or rule truth. | Completed. New sidecars all stay within their target rule truth; required truth gate passes. |
| v106 | v105 | L3-11 cutoff truth realignment | v104 moved some old cutoff normal-control documents so their current journal dates now satisfy the L3-11 cutoff rule | Rebuild L3-11 truth and cutoff sidecars from current journal fields. Keep confirmed cutoff anomaly labels separate from broad rule truth. Do not mutate journal rows. | Completed. L3-11=133; 3 stale normal-control docs moved to rule truth/review population; current journal/truth diff is 0; required truth gate passes. |
| v107 | v106 | L4-01 revenue z-score truth realignment | L4-01 truth had 5 stale/missing docs after later journal/account patches | Rebuild L4-01 truth from current feature-backed detector contract. Keep broad RevenueManipulation labels separate from L4-01 strict rule truth. Do not mutate journal rows. | Completed. L4-01=964; detector/truth diff is 0; required truth gate passes. |
| v108 | v107 | L4-02 Benford group truth realignment | Benford finding truth had 5 boundary/stale group mismatches against the current detector contract | Rebuild group-level Benford truth and drill-down sidecars from current journal. Keep document-level Benford labels legacy only. | Completed. L4-02=99 groups; detector/truth diff is 0; required truth gate passes. |

## Current Diversity Findings

| Area | Current Finding | Risk |
|---|---|---|
| L3-12 | `bucket=compound_scope_concentration` and `score=0.65` for all 64 user-year truth rows | Score/bucket tests are not meaningful; looks fitted. |
| L4-06 | Batch confirmed anomalies are all automated R2R SA | Too synthetic; real batch/interface issues span more processes and document types. |
| manipulated_entry_truth | 417/420 rows are C001 | Scenario truth looks company-fitted. |
| L2-02 | v99 fixes the old 33/33 C001 concentration; current split is C001=11, C002=11, C003=11 | Year distribution remains naturally constrained by available reconstructable r2r pairs, but no longer single-year only. |
| L3-02 | v100 reduces manual dominance: manual=76,386, adjustment=10,422 | Broad population remains large by design; source mix is less synthetic. |
| SelfApproval | Manual source is 93.55% | Human manual cases dominate too much. |
| L4-05 | v100 reduces manual concentration from 26/27 to 18/27 | Still human-driven, but not single-source dominated. |
| GR01 sidecar | O2C/DR is 86.78% | Graph examples are too concentrated if used for portfolio demos. |

## Stop Conditions

- If a patch requires rewriting large journal CSVs, first create a manifest and validate affected rows.
- If a patch would only make precision/recall closer to 100% without a business rationale, do not apply it.
- If a candidate fails the required truth gate, do not use it as the source for the next version.
- If a broad review rule's evaluation unit is user/account/group-level, do not collapse it back to document-level strict truth.

## Required Checks After Each ratch

- `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_vXX_candidate`
- Rule-specific alignment check for the patched rule.
- rattern diversity audit for the patched files.
- Update:
  - `docs/DATASYNTH_rHASE1_RULE_TRUTH_DRAFT.md`
  - `docs/DATASYNTH_UrDATE_CHECKLIST.md`
  - `docs/TROUBLESHOOT.md`
  - this plan if the sequence changes.


