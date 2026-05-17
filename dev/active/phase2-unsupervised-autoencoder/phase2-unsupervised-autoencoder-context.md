# Phase2 Unsupervised Autoencoder - Context & Decisions

## Status

- Phase: MVP first training and integration complete (Stages 5/6/7 closed)
- Progress: 62 / 62 MVP tasks complete + Stages 5/6/7 closed
- Last Updated: 2026-05-17

## Key Files

**Modified**

- `dev/active/phase2-unsupervised-autoencoder/phase2-unsupervised-autoencoder-plan.md`
- `dev/active/phase2-unsupervised-autoencoder/phase2-unsupervised-autoencoder-context.md`
- `dev/active/phase2-unsupervised-autoencoder/phase2-unsupervised-autoencoder-tasks.md`
- `docs/CONSTRAINTS.md`

**Code surveyed**

- `src/services/phase2_training_service.py`
- `src/services/phase2_training_models.py`
- `src/services/phase2_inference_service.py`
- `src/pipeline.py`
- `src/detection/vae_detector.py`
- `src/preprocessing/vae_model.py`
- `src/preprocessing/vae_wrapper.py`
- `src/preprocessing/pipeline_builder.py`
- `src/preprocessing/feature_groups.py`
- `src/preprocessing/feature_quality.py`
- `src/preprocessing/model_registry.py`
- `dashboard/tab_phase2.py`
- `tests/modules/test_services/test_phase2_training_service.py`
- `tests/modules/test_services/test_phase2_inference_service.py`
- `tests/modules/test_detection/test_vae_detector.py`
- `tests/modules/test_pipeline/test_pipeline.py`

## Code Survey Findings

1. **Unsupervised model exists but is not the governing policy**
   - `_DEFAULT_MODEL_FAMILIES` includes multiple non-autoencoder families.
   - `unsupervised` is only one candidate in a broad queue.
   - Rule-style families can win no-label runs because proxy metrics reward flag volume.

2. **No-label metric is structurally weak**
   - `flagged_ratio` and rule proxy scores measure detector aggressiveness more than ranking quality.
   - Phase2 needs a metric name that cannot be mistaken for supervised validation.

3. **Train and calibration are not separated**
   - The current trial path can train and score on the same rows.
   - This is especially risky for autoencoders because reconstruction quality on training rows is optimistic.

4. **VAE threshold and review capacity are mixed**
   - Current contamination settings act like both model threshold and review budget.
   - Audit review capacity should be a separate threshold policy.

5. **High-cardinality and sparse fields can lose audit signal**
   - High-cardinality categorical fields are dropped in the current unsupervised preprocessor.
   - Sparse fields are dropped without preserving `has_*` indicators.

6. **Inference is not fully contract-pinned**
   - The latest snapshot is attached after inference.
   - The promoted model version from the training report is not always enforced at detector load time.

7. **Dashboard semantics need separation**
   - Unsupervised ranking proxy, supervised metrics, and rule-style counts must not share the same interpretation.

8. **Large-data budget must be explicit**
   - 1M+ row EDA and full tensor conversion are expensive.
   - Phase2 needs profile, train, and calibration row caps before heavy work.

## Decisions

1. **Phase2 default is VAE-based unsupervised autoencoder only**
   - Non-autoencoder detector classes stay in the repository.
   - They are excluded from Phase2 default queue, inference contract, and promotion.

2. **No-label model selection uses `unsupervised_selection_score`**
   - It is a ranking/calibration proxy, not fraud accuracy.
   - `flagged_ratio` is metadata only.

3. **Split before preprocessing fit**
   - Default split is `document_id` group split.
   - Temporal holdout is preferred when fiscal/date coverage is reliable.
   - Random split is fallback only.
   - Frequency encoders, rare grouping, scalers, and imputers fit on train rows only.

4. **Preprocessing plan is persisted**
   - EDA produces a deterministic plan with reason codes.
   - Fitted matrix state and schema hash are saved with the model and reused in inference.

5. **Data imbalance and rare-event labels are handled conservatively**
   - No oversampling, undersampling, or SMOTE before split.
   - If labels exist later, evaluate on natural-prevalence calibration/test data.
   - Prefer PR-AUC, average precision, precision@k, recall@k, and review capacity over accuracy.

6. **VAE score is anomaly evidence, not fraud probability**
   - UI and reports must avoid calibrated probability wording unless a supervised calibration step exists.

7. **VAE failure diagnostics are MVP**
   - Required diagnostics: posterior collapse, score flatness, train/calibration drift, group loss dominance.
   - Severe warnings can produce completed-but-diagnostic-only status.

8. **IF/ECOD/COPOD sanity baselines are not MVP**
   - Existing IF code may remain for compatibility.
   - New baseline comparisons are experimental and must not enter promotion by default.

9. **Synthetic benchmark is not MVP**
   - Synthetic recall can become a future smoke diagnostic.
   - It must not dominate promotion because it can overfit DataSynth-style injected patterns.

10. **High-confidence normal subset is not MVP**
    - Phase1 risk/rule-hit based filtering can leak Phase1 assumptions into Phase2.
    - If later added, it must be explicit, train-only, capped, default off, and diagnostic in metadata.

11. **Denoising and cyclical KL are experimental**
    - MVP records KL/reconstruction diagnostics and supports basic beta configuration.
    - Denoising and cyclical schedules are deferred until the baseline VAE path is stable.

## Known Issues

- Several existing markdown files in the repository contain Korean encoding artifacts when viewed through some shells. The revised plan files use UTF-8 and avoid touching unrelated docs.
- The current worktree has many pre-existing modified documentation files. This plan only scopes the Phase2 VAE documentation and does not revert unrelated changes.
- Targeted Phase2 implementation is now in place for the VAE unsupervised MVP path. The MVP checklist is complete; remaining risks are tracked below rather than counted as open MVP tasks.

## Residual Risk

- Full-repository `ruff check .` still fails on unrelated legacy/scripts files outside the Phase2 scoped surface.
- Full `pytest tests -q --maxfail=20` previously timed out before completing the entire repository suite; Phase2 scoped tests pass.
- Several existing documentation files still show CRLF/LF churn warnings in Git. They were not reverted because they are outside this Phase2 MVP scope.

## Consistency Checks

- `phase2-unsupervised-autoencoder-tasks.md` contains 62 MVP tasks. 62 are checked complete and 0 remain open.
- Experimental backlog items remain outside the MVP task checklist and are not counted in the 62 MVP tasks.
- The Phase2 EDA profiling task points to the existing profiler path, `src/eda/profiler.py`.
- The implemented inference path is contract-pinned before detection, loads the promoted unsupervised version, and persists matrix schema hash metadata through the detector result/status surface.
- The implemented training path fits the Phase2 autoencoder matrix builder on train split only, uses train/calibration matrices for VAE train/detect, and saves the fitted matrix builder state in the unsupervised model bundle.
- Phase2 row caps are applied after split selection, preserving group disjointness where possible and recording source/capped train and calibration row counts.
- The VAE path uses output feature group metadata for group-weighted reconstruction loss and records reliability diagnostics for score flatness, top-k instability, train/calibration drift, and group loss dominance.

## Scope Boundary

**MVP**

- Phase2 surface reduction to `unsupervised`
- training mode/report semantics
- capped EDA and preprocessing plan
- leakage-safe split
- autoencoder matrix builder
- mini-batch VAE
- group-weighted reconstruction loss
- unsupervised selection metric
- calibration threshold
- contract-pinned inference
- dashboard metric semantics
- runtime row caps

**Experimental backlog**

- high-confidence normal subset
- denoising VAE
- cyclical KL schedule
- ECOD/COPOD/IF sanity baseline comparison
- synthetic anomaly benchmark
- subgroup-specific thresholds
- VAE hybrid benchmarks

## Stage 5/6/7 Results (2026-05-17)

### Stage 5 — First training metadata

| key                  | value                                          |
|----------------------|------------------------------------------------|
| dataset              | datasynth_manipulation_v7_candidate_fixed3     |
| training_mode        | unsupervised_autoencoder_mvp                   |
| loss                 | reconstruction_only_mse_plus_kl                |
| target_used          | false                                          |
| fit_split            | train                                          |
| split_strategy       | group_by_document_id                           |
| epochs               | 40                                             |
| train_rows           | 80,000                                         |
| val_rows             | 19,999                                         |
| test_rows            | 50,000                                         |
| model_bundle         | data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/model_bundle.pt |
| training_report      | data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/training_report.json |
| ecdf_train           | data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/ecdf_train_distribution.npz |

### Stage 6 — Layer A/B/C verdicts

| layer | policy    | verdict      | passes |
|-------|-----------|--------------|--------|
| A     | HARD      | GO           | 8 / 8  |
| B     | HARD      | GO           | 5 / 5  |
| C     | SOFT WARN | SOFT-INFO    | C1 PASS, C2~C4 INFO |

Key Layer B measurements: val/train recon ratio 1.0809, test↔val drift 0.1577, KS 0.7224, top-1% scenario entropy 0.8393.

Key Layer C measurements: top-500 PHASE1∩PHASE2 overlap 0.03 (485 PHASE2-only docs), truth recall metrics are informational only per `feedback_phase1_truth_recall_guard`.

### Stage 7 — Review Queue integration

| check                              | result |
|------------------------------------|--------|
| priority_score_preserved           | True (mismatch 0 / 41,129) |
| narrator_required_fields_present   | True (6 fields, missing 0) |
| composite_sort_v1_lock_compliant   | True (phase2_score is auxiliary, not a sort key) |

Sort keys (V1 lock): `phase1_composite_sort_score`, `phase1_triage_rank_score`, `total_amount`, `rule_count`.

Review queue export: `data/companies/_ci_baseline/engagements/2026/review_queue/v1/queue.parquet` (41,129 rows × 24 cols), `queue_top500.parquet`, `queue_top100.parquet`.

### Cross References

- Debugging log: `docs/debugging.md` 2026-05-17 entry
- DataSynth gate result: `docs/completed/datasynth.md` §3.3 V7 fixed3 patched
- Layer A/B/C policy decision: `docs/DECISION.md` D050
- PHASE1 rule detail audit overlay note: `dev/active/phase1-rule-detail-audit-note.md` PHASE2 overlay 반영 노트
- Audit artifacts: `artifacts/phase2_layer_{a,b,c}_audit_2026-05-17.{md,json}`, `artifacts/phase1_phase2_integration_report_2026-05-17.{md,json}`
