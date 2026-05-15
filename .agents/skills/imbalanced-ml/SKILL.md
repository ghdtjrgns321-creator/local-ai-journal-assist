---
name: imbalanced-ml
description: "Imbalanced classification and unsupervised anomaly detection patterns for local-ai-assist Phase 2 ML. Use when Codex applies SMOTE or imblearn Pipeline, cross-validates rare-event classifiers, tunes thresholds, trains VAE/IsolationForest/LOF without labels, or ensembles anomaly scores with ECDF."
---

# Imbalanced ML

Use this skill for Phase 2 ML and anomaly detection in `local-ai-assist`. Keep it focused on rare audit events, leakage prevention, threshold selection, unsupervised training boundaries, and score ensembling. For verification scope, use `local-ai-assist-testing`; for audit semantics and leakage review, use `local-ai-assist-review`.

## Core Principle

Audit anomalies are rare and labels are often synthetic, weak, or review-oriented. Avoid leakage, do not treat PHASE1 review signals as ground-truth fraud, and keep supervised and unsupervised workflows separate.

## Trigger Contexts

- `SMOTE`, `RandomOverSampler`, `imblearn`, or class balancing.
- Cross-validation for rare-event classifiers.
- `predict_proba`, classification threshold tuning, F1/recall/precision tradeoffs.
- `IsolationForest`, `LocalOutlierFactor`, VAE, autoencoder, or other unsupervised detectors.
- Combining anomaly scores from multiple models.
- DataSynth labels used for development validation.

## SMOTE Must Stay Inside CV

Never run oversampling before the train/validation split. Synthetic samples can leak across folds and inflate metrics.

```python
# Bad
X_resampled, y_resampled = SMOTE().fit_resample(X, y)
scores = cross_val_score(model, X_resampled, y_resampled, cv=5)

# Good
from imblearn.pipeline import Pipeline as ImbPipeline
from imblearn.over_sampling import SMOTE

pipe = ImbPipeline(
    [
        ("smote", SMOTE(random_state=0)),
        ("clf", RandomForestClassifier(random_state=0)),
    ]
)
scores = cross_val_score(pipe, X, y, cv=5, scoring="f1")
```

Use `imblearn.pipeline.Pipeline`, not `sklearn.pipeline.Pipeline`, when samplers are in the pipeline. The sampler must run only during `fit` on each training fold.

## Threshold Tuning

Default `0.5` thresholds usually fail on rare classes. Tune thresholds on validation folds, then store the selected operating point with the model.

```python
from sklearn.metrics import precision_recall_curve

def best_threshold(y_true, y_proba) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, y_proba)
    f1 = 2 * precision * recall / (precision + recall + 1e-12)
    return float(thresholds[f1[:-1].argmax()])
```

Use the median of fold-level thresholds when folds are unstable. Choose the metric by audit workflow, not only leaderboard score:

- Higher recall for broad review queue generation.
- Higher precision for expensive manual review queues.
- Cost-sensitive score when false positives and false negatives have explicit costs.

## Do Not Train Unsupervised Models With `y`

`IsolationForest`, `LocalOutlierFactor`, and VAE-style detectors must fit on `X` only. Labels are for evaluation and calibration after scoring.

```python
# Bad
IsolationForest(contamination=0.01).fit(X_train, y_train)

# Good
iso = IsolationForest(contamination="auto", random_state=0).fit(X_train)
score = -iso.score_samples(X_test)
```

Do not pre-filter training data using PHASE1 pseudo-labels unless the design explicitly becomes semi-supervised and the docs/tests say so. Otherwise the ML detector inherits the rule engine's bias and stops being an independent signal.

## VAE / IsolationForest / ECDF Ensemble

Raw anomaly scores have incompatible scales:

- IsolationForest score samples often need sign inversion so higher means more anomalous.
- VAE reconstruction error may be heavy-tailed.
- LOF and distance-based scores vary by feature scaling and neighborhood size.

Prefer ECDF conversion based on the training score distribution:

```python
import numpy as np
from collections.abc import Callable

def ecdf_transform(train_scores: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    sorted_train = np.sort(train_scores)
    n = len(sorted_train)

    def _apply(scores: np.ndarray) -> np.ndarray:
        return np.searchsorted(sorted_train, scores, side="right") / n

    return _apply
```

Fit and persist each model's ECDF distribution during training. At inference, transform new scores against the stored training distribution, then average or weight the normalized percentiles.

Do not use `scipy.stats.rankdata` on each inference batch for persisted thresholds. Batch-local rank changes with batch size; a 10-row inference batch can make normal rows look top-ranked.

## Anti-Patterns

| Avoid | Problem | Prefer |
|-------|---------|--------|
| `SMOTE().fit_resample(X, y)` before CV | Fold leakage | `imblearn` pipeline inside CV |
| `predict_proba > 0.5` by default | Rare-class recall collapse | Fold-tuned threshold |
| Passing `y` into unsupervised `fit` | Label leakage or design confusion | `fit(X)`, evaluate with `y` later |
| Filtering "normal" rows using PHASE1 labels for unsupervised training | Rule bias becomes model bias | Train on intended population or document semi-supervised design |
| `MinMaxScaler` for score ensemble | Extreme outliers distort scale | Training-distribution ECDF |
| Batch-local `rankdata` at inference | Thresholds drift by batch | Persist train ECDF arrays |

## Local Files To Check

- `src/ml/` or any new Phase 2 ML module.
- `src/detection/` when ML scores enter review queues.
- `config/settings.py` for thresholds and contamination settings.
- `docs/pre-plan/05a-detection-ml.md`
- `docs/TASKS.md` for current Phase 2 status.
