# Phase2 UI Resiliency Context

## Purpose

Phase2 Streamlit UI has repeatedly failed around inference result visibility, overlay persistence, batch reload, and unclear empty-state messages. This sprint traces the full UI path before further patching:

UI action -> session_state -> service -> DB/file persistence -> reload -> display branch.

The goal is not to make Phase2 look successful when contracts are broken. The goal is to show auditors the right available result, explain missing evidence clearly, and prevent stale or cross-batch overlays.

## Scope

Primary files to inspect:

- `dashboard/tab_phase2.py`
- `dashboard/app.py`
- `dashboard/components/*phase2*`
- `src/services/phase2_inference_service.py`
- `src/services/phase2_training_service.py`
- `src/services/batch_service.py`
- `src/services/session_service.py`
- `src/services/phase2_overlay_store.py`
- `src/db/loader.py`
- `src/db/batch_reader.py`
- `src/detection/phase1_case_builder.py`
- `src/export/phase1_case_view.py`

## UI Actions To Trace

Phase2-specific:

- Saved model Phase2 inference
- Phase2 retrain + inference
- Phase2 training without inference
- Partition selector
- Sub-tabs: overview, analysis-area signals, review lane, model basis

Cross-phase and navigation:

- Phase1 analysis rerun
- Analysis preparation / mapping finalize
- Company selection autoload via `_batch_autoloaded_for_{engagement_id}`
- Saved batch load
- Data upload again, creating a new batch id
- Return to first screen

## Session State Keys

Core keys:

- `KEY_PREP_RESULT`
- `KEY_PHASE1_RESULT`
- `KEY_PHASE2_RESULT`
- `KEY_PIPELINE_RESULT`
- `KEY_BATCH_ID`
- `KEY_COMPANY_CONTEXT`
- `KEY_FEATURED_DATA`

Additional keys:

- `KEY_LOADED_FROM_DB`
- `KEY_ACTIVE_RESULT_TAB`
- `KEY_PENDING_RESULT_TAB`
- `KEY_PHASE2_TRAINING_REPORT_ID`
- `_batch_autoloaded_for_{engagement_id}`

## Persistence Contracts

| Artifact | Save point | Read point | Missing impact |
| --- | --- | --- | --- |
| `upload_batches` / `general_ledger` / `anomaly_flags` | ingest + detection DB load | `batch_reader.load_batch` | No restored analysis output |
| `batch_meta` Phase2 metadata | `_persist_phase2_batch_snapshot` | `load_batch` | Phase2 artifact not detected, `KEY_PHASE2_RESULT` may be `None` |
| `models/phase2_train/.../training_report.json` | Phase2 training | `load_latest_phase2_training_snapshot` | Inference falls back to `untrained_contract_only` |
| `models/phase2_train/.../leaderboard.json` / `promotion_decision.json` | Phase2 training | snapshot/model-basis loaders | Model basis tab may be empty |
| Phase1 case artifact | Phase1 analysis | `resolve_phase1_case_result(pr)` | Canonical Phase1 case restore fails; fallback path must be explicit |
| `phase2_overlays/{batch_id}.json` | After Phase2 inference | `batch_service.load_batch_into_state` | Overlay missing UI and empty review lanes |
| `artifacts/phase2_inference_v7_fixed3_year_{year}.json` | static/reference measurement | Phase2 overview / analysis-area cards | Analysis-area signal display may be unavailable |

## Known Failure Classes

- Phase2 detection succeeds, DB load fails.
- DB load succeeds, Phase2 metadata is missing.
- Phase2 metadata exists, overlay JSON is missing.
- Overlay JSON exists, schema mismatch.
- Overlay JSON exists, payload batch_id mismatch.
- Phase1 result is metadata-only and artifact lazy load is not performed.
- Phase1 artifact is missing or unreadable.
- Canonical Phase1 case is unavailable; redetect fallback must be preserved.
- Company context is anonymous or cloned incorrectly.
- Overlay from another company/engagement is attached.
- Retraining creates stale overlays with an older `phase2_training_report_id`.
- Partition selector picks a year with zero rows and silently falls back to full dataset.

## UI Empty-State Contract

Every empty state must answer:

1. What is missing?
2. Which layer failed or is unavailable?
3. What can the user do next?

Target branches:

- Phase1 cases missing
- Phase1 artifact missing
- Phase2 inference not run
- Phase2 DB load failed
- Phase2 overlay missing
- Overlay schema mismatch
- Overlay batch_id mismatch
- Overlay present but no hit cases
- Training snapshot missing / cold-start inference
- Partition zero-row fallback to full data
- Anonymous or missing company context
- Old batch without overlay persistence

