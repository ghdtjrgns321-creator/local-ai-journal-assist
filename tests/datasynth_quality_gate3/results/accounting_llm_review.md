# DataSynth semantic-v1 accounting LLM review

- Dataset: `data\journal\primary\datasynth_semantic_v1`
- Unique reviewed docs: 395
- Sample assignments: 408
- Sample seed: 20260512

## Verdict Counts

- PASS: 308
- INTENDED_ABNORMAL: 87

## Acceptance Criteria

- random/scenario normal FAIL rate: 0.00% (PASS)
- abnormal mutation INTENDED_ABNORMAL explained: 100.00% (PASS)
- L3/L4 hit generator contamination: 0.00% (LOW)

## Notes

- `PASS` means normal synthetic accounting logic is acceptable for testing.
- `WARN` means plausible enough for synthetic tests but stylistically or document-type-wise imperfect.
- `FAIL` means a normal entry has a semantic accounting contradiction.
- `INTENDED_ABNORMAL` means mutation provenance explains the abnormal state.

## Output Files

- `accounting_llm_review_samples.csv`: stratified sample membership
- `accounting_llm_review_reviews.csv`: document-level review judgments
- `accounting_llm_review_bucket_summary.csv`: bucket/verdict cross-tab
- `accounting_llm_review_phase1_hits.csv`: Phase1 L3/L4/top-case sampling support
