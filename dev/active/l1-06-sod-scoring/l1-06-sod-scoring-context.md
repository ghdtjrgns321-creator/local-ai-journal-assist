# L1-06 SoD Scoring - Context & Decisions

## Status
- Phase: Planning
- Progress: 0 / 13 tasks complete
- Last Updated: 2026-04-29

## Key Files
**Modified During Implementation**:
- `config/audit_rules.yaml` - Add configurable L1-06 score bands and high-risk conflict/process settings.
- `config/phase1_case.yaml` - Keep L1-06 priority floors limited to high/critical raw scores.
- `src/detection/fraud_rules_access.py` - Compute graduated L1-06 direct scores.
- `src/detection/score_aggregator.py` - Verify row-level floor interaction with L1-06 bands.
- `tests/modules/test_detection/test_fraud_rules_access.py` - Cover direct SoD band scoring and L1-06/L3-12 boundary.
- `tests/modules/test_detection/test_score_aggregator.py` - Cover aggregation and floor behavior for graduated L1-06 scores.

**Reference Only**:
- `src/detection/rule_scoring.py` - L1-06 is severity 4, `control_failure`, `strong`; this can remain unchanged unless aggregation math needs explicit metadata.
- `docs/DETECTION_PARAMETERS.md` - Current L1-06 rule boundary states direct-only and no review band.
- `docs/TROUBLESHOOT.md` - Historical reason for avoiding broad L1-06 SoD scoring.

## Key Decisions
1. **Keep L1-06 Direct-Only** (2026-04-29)
   - Rationale: Existing docs and tests intentionally moved user work-scope breadth out of L1-06 and into L3-12.
   - Alternatives: Add low review scores to L1-06 for toxic pairs and role thresholds.
   - Trade-offs: Direct-only keeps precision clean but requires L3-12 and work-scope combo scoring to carry access-scope review value.

2. **Use Four Non-Zero Direct Bands** (2026-04-29)
   - Rationale: The current 0.80-only direct score cannot distinguish weak direct metadata from critical control override.
   - Alternatives: Use only 0.40 and 0.80, or use continuous formula based on amount percentile.
   - Trade-offs: Four bands are auditable and testable; continuous scoring can be added later if amount calibration is reliable.

3. **Risk Floors Must Match Row Scoring Math** (2026-04-29)
   - Rationale: L1 row weight is 0.40, so raw L1-06 scores below 0.80 do not naturally reach Medium row risk and raw 0.80 reaches High only because of the current floor.
   - Alternatives: Increase L1 global weight or treat all direct L1-06 hits as High.
   - Trade-offs: Targeted L1-06 floors preserve the global L1/L2/L3/L4 scoring model while allowing Direct-Medium to become Medium and Direct-High/Critical to become High.

4. **Configurable Thresholds, Fixed Code Shape** (2026-04-29)
   - Rationale: Conflict types and protected processes are audit-policy data and belong in YAML.
   - Alternatives: Hardcode all band rules in Python.
   - Trade-offs: YAML keeps policy tunable; Python still owns deterministic precedence and input normalization.

## Known Issues
- The existing `score_series` tests assert exact 0.80 for all immediate L1-06 paths and must be rewritten to assert band-specific behavior.
- `src/detection/score_aggregator.py` currently floors L1-06 only to High when raw details are at least 0.80. Direct-Medium requires a new Medium row floor if the risk label is expected to match the proposed band name.
- Current documentation states "L1-06 has no review band"; this remains true, but wording must clarify "no review band" does not mean "no direct severity bands."
