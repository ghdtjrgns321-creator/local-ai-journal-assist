# Topic Scoring Antifit Calibration - Context & Decisions

## Status
- Phase: Implementation verification
- Progress: 17 / 20 tasks complete
- Last Updated: 2026-05-08

## Key Files
**Modified by future implementation**:
- `src/detection/topic_scoring.py` - combo floor logic and fraud scenario tag generation.
- `tests/modules/test_detection/test_rule_scoring.py` - rule-level anti-fitting and positive combo contracts.
- `tests/modules/test_detection/test_phase1_case_builder.py` - case-level topic score and fraud tag contracts.
- `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md` - locked policy wording.
- `docs/PHASE1_RULE_RELATIONSHIP_MAP.md` - rule relationship policy wording.
- `docs/DETECTION_RESULTS_MANIPULATION.md` - post-change datasynth profile summary.

**Reference**:
- `config/phase1_case.yaml` - current combo floor values.
- `docs/DETECTION_RESULTS_MANIPULATION.md` - current broad tag counts, including `fictitious_entry_risk` and `period_end_adjustment_risk`.

## Key Decisions
1. **Remove weak datasynth-shaped floors** (2026-05-08)
   - Rationale: `L3-02 + L3-04 + L3-12` is audit-relevant context but lacks strong evidence for fictitious entry or period-end manipulation floors.
   - Alternatives: Lower the floor to `0.45`; rejected as still allowing weak combinations to drive topic routing.
   - Trade-offs: Datasynth truth recall may drop, but real audit precision and policy defensibility improve.

2. **Make `L3-12` context-only for fraud floors** (2026-05-08)
   - Rationale: Work-scope concentration can strengthen an already suspicious case but should not be a primary fraud-pattern ingredient.
   - Alternatives: Keep `L3-12` as a combo-only rule; rejected for the listed weak combinations because it became a floor enabler.
   - Trade-offs: Some operationally suspicious cases become Medium control review or badge-only rather than fraud Medium.

3. **Restrict circular High to repeat/cycle or IC exception evidence** (2026-05-08)
   - Rationale: Related-party plus weekend/manual timing does not establish a circular transaction pattern under ISA 550/PCAOB related-party logic.
   - Alternatives: Convert the current weak circular condition to Medium; acceptable only if it is documented as related-party review context, not circular High.
   - Trade-offs: `circular_related_party_transaction` Top100 count may decrease.

4. **Separate approval High from approval Medium** (2026-05-08)
   - Rationale: Approval bypass plus manual entry is important, but High should require high amount, cutoff, abnormal time, or manual closing combination.
   - Alternatives: Keep existing High and rely on downstream review state; rejected because topic floors currently affect ranking directly.
   - Trade-offs: Approval/SOD High count may drop while Medium queue remains available.

5. **Datasynth recall becomes a secondary metric** (2026-05-08)
   - Rationale: The project already warns against fitting to datasynth. Verification must prioritize literature-backed floor hits and normal-case inflation.
   - Alternatives: Tune until datasynth truth coverage is restored; rejected as the source of the current risk.
   - Trade-offs: Reports must explicitly explain why lower synthetic recall can be a healthier result.

## Known Issues
- The existing documentation contains mojibake in several Korean sections. The implementation should edit only the relevant policy lines and avoid broad encoding churn.
- `topic_scoring.py` currently returns only floor-derived `fraud_combo_tags`; there may not be a separate badge-only mechanism. If no existing badge-only path fits, weak combinations should be omitted from fraud tags rather than added as floors.
- Some tests may assert current broad floors. Those tests should be updated to policy-aligned expectations, not deleted without replacement.
- Full `tests/modules/test_detection -q` did not finish within 300 seconds in this workspace. Focused topic scoring and phase1 case builder tests passed.
- `profile_phase1_v126.py` created `artifacts/phase1_manipulation_topic_antifit_profile.json`, but the command timed out during aggregate/case stages before post-change case counts were produced.
