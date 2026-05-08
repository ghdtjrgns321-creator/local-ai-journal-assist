# PHASE1 Topic Scoring V1 Completion

Updated: 2026-05-08
Status: Complete

## Scope Summary

PHASE1 topic scoring v1 is complete against the lock document:

- Lock document: `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md`
- Topic scoring core: `src/detection/rule_scoring.py`, `src/detection/topic_scoring.py`
- Case builder, schema, and config: `src/detection/phase1_case_builder.py`, `src/models/phase1_case.py`, `config/phase1_case.yaml`
- Dashboard and export presentation: `dashboard/tab_phase1.py`, `dashboard/tab_summary.py`, `dashboard/tab_overview.py`, `src/export/phase1_case_view.py`
- Detection/export compatibility fixes: `src/detection/anomaly_layer.py`, `src/detection/duplicate_detector.py`, `src/detection/graph_detector.py`, `src/detection/score_aggregator.py`, `src/detection/constants.py`, `src/detection/sequence_detector.py`, `src/detection/explanations.py`, `src/export/audit_evidence.py`, `src/pipeline.py`, `tests/conftest.py`

## Locked Behavior Confirmed

- `L2-01` routes to `duplicate_outflow` as primary and `approval_control` as secondary.
- `L1-08` routes to `closing_timing` as primary and `ledger_integrity` as secondary.
- `L3-05` and `L3-06` are booster-only signals in v1 and cannot create standalone full-review queues.
- `macro_only` rules keep standalone row contribution at `0.0` and only contribute through macro context when a case has a primary row-level hit.
- `fraud_scenario_tags` are stored as tag/detail context, not as queue or ranking labels.
- Dashboard/export ranking labels use only the seven topic labels from `TOPIC_REGISTRY`.

## Verification Record

| Check | Command / Scope | Result |
|---|---|---|
| Detection suite | `.venv\Scripts\pytest.exe tests\modules\test_detection -q --basetemp=.tmp_pytest_detection_contract` | 976 passed, 2 warnings |
| Export suite | `.venv\Scripts\pytest.exe tests\modules\test_export -q --basetemp=.tmp_pytest_export_contract` | 101 passed |
| Dashboard suite | `.venv\Scripts\pytest.exe tests\modules\test_dashboard -q` | 145 passed |
| Lock regression | `test_rule_scoring.py`, `test_phase1_case_builder.py`, `test_tab_phase1.py`, `test_phase1_case_view.py` | 109 passed |
| Ruff | touched files | passed |

Warnings from the detection suite are non-blocking environment warnings:

- joblib core-count detection warning
- Windows cp949 thread decode warning

## Release Gate

Release gate status: passed.

There are no remaining detection/export/dashboard failures for this scope. The previous full-suite failures were classified as pre-existing contract mismatches, stale expectations, real compatibility bugs, or Windows temp setup issues, and were resolved or isolated before this completion record.

