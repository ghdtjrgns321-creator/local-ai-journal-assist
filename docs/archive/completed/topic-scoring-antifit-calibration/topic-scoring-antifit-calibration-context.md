# Topic Scoring Antifit Calibration - Context & Decisions

## Status
- Phase: Complete
- Progress: 20 / 20 tasks complete
- Last Updated: 2026-05-17

## Key Files
**Modified by future implementation**:
- `src/detection/topic_scoring.py` - combo floor logic and fraud scenario tag generation.
- `tests/modules/test_detection/test_rule_scoring.py` - rule-level anti-fitting and positive combo contracts.
- `tests/modules/test_detection/test_phase1_case_builder.py` - case-level topic score and fraud tag contracts.
- `docs/spec/PHASE1_TOPIC_SCORING_V1_LOCK.md` - locked policy wording.
- `docs/spec/PHASE1_RULE_RELATIONSHIP_MAP.md` - rule relationship policy wording.
- `docs/archive/completed/DETECTION_RESULTS_MANIPULATION.md` - post-change datasynth profile summary.

**Reference**:
- `config/phase1_case.yaml` - current combo floor values.
- `docs/archive/completed/DETECTION_RESULTS_MANIPULATION.md` - current broad tag counts, including `fictitious_entry_risk` and `period_end_adjustment_risk`.

## Key Decisions
1. **Remove weak datasynth-shaped floors** (2026-05-08)
   - Rationale: `L3-02 + L3-04 + L3-12` is audit-relevant context but lacks strong evidence for fictitious entry or period-end manipulation floors.
   - Alternatives: Lower the floor to `0.45`; rejected as still allowing weak combinations to drive topic routing.
   - Trade-offs: Synthetic truth coverage may drop, while audit precision and policy defensibility become stronger.

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
- Earlier full `tests/modules/test_detection -q` runs exceeded a shorter timeout, but the final D1 verification completed successfully.
- Earlier profile attempts against the legacy `datasynth_manipulation` path were blocked by missing labels or cache references; the final D1 profile uses the available `datasynth_manipulation_v2` dataset and is recorded below.

## Sprint D1 Results (2026-05-17)

### Status

Sprint D1 completed. The weak auxiliary floor policy is now encoded in `topic_scoring.py`, `config/phase1_case.yaml`, the topic scoring lock docs, and regression tests. PHASE1 dashboard files and PHASE2 paths were not modified.

### Code and policy result

- `approval_bypass + L3-02`, `approval_bypass + L3-05`, and `approval_bypass + L3-06` now produce approval-control Medium context only.
- `approval_bypass_high` remains reserved for stronger evidence: high amount, cutoff, manual closing, manual after-hours, or explicit override context.
- `L3-02 + L3-04 + L3-12`, `approval_bypass + L3-02 + L3-12`, and `L3-03 + L3-05 + (L3-02 or L3-12)` remain excluded from fraud-pattern High/Medium floors.
- `phase1_case.topic_scoring.anti_fitting_policy` records the domain policy and marks truth recall as `informational_only`.

### Verification

| Check | Result |
| --- | --- |
| `uv run pytest tests/modules/test_detection/test_rule_scoring.py -q` | 60 passed |
| `uv run pytest tests/modules/test_detection/test_rule_scoring.py tests/modules/test_detection/test_phase1_case_builder.py -q` | 128 passed |
| `uv run pytest tests/modules/test_detection -q` | 1099 passed, 3 skipped |
| `uv run pytest tests/modules/test_detection/test_phase1_case_builder.py -q -k "composite_sort_score"` | 4 passed, 64 deselected |
| `uv run ruff check src/detection/topic_scoring.py tests/modules/test_detection/test_rule_scoring.py` | passed |

### Profile artifact

Current available manipulation v2 profile was rerun with:

`uv run python tools/scripts/profile_phase1_v126.py --data-dir data/journal/primary/datasynth_manipulation_v2 --checkpoint artifacts/phase1_manipulation_v2_topic_antifit_profile_20260517.json --cache-path artifacts/phase1_manipulation_v2_topic_antifit_case_input_20260517.pkl`

The run produced `case_count=11116`, `macro_finding_count=20`, and retained score/rule/review hit coverage for the 420 truth documents. These truth metrics are informational only and were not used as the justification for the D1 change.
