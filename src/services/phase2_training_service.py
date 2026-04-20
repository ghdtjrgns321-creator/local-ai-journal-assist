"""Foundation helpers for the Phase 2 AutoML training pipeline."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import f1_score

from config.settings import PROJECT_ROOT, get_settings
from src.detection.ensemble_detector import EnsembleDetector
from src.detection.sequence_detector import SequenceDetector
from src.detection.supervised_detector import SupervisedDetector
from src.detection.tabular_transformer import TransformerDetector
from src.detection.vae_detector import UnsupervisedDetector
from src.eda.profiler import profile_dataframe
from src.preprocessing.feature_groups import classify_features
from src.preprocessing.feature_quality import (
    FEATURE_FAMILIES,
    apply_feature_quality_policy,
)
from src.preprocessing.label_strategy import create_labels, create_labels_from_feedback
from src.preprocessing.model_registry import ModelRegistry
from src.services.phase2_training_models import (
    Phase2LabelSummary,
    Phase2PromotedModel,
    Phase2TrainingReport,
    Phase2TrainingStatus,
    Phase2TrialResult,
)

_DEFAULT_PHASE2_TRAIN_DIR = PROJECT_ROOT / "data" / "phase2_train"
_DEFAULT_MODEL_FAMILIES = (
    "unsupervised",
    "supervised",
    "transformer",
    "sequence",
    "stacking",
)
_SUPERVISED_FAMILIES = {"supervised", "transformer", "sequence", "stacking"}
_SEQUENCE_CONTEXT_COLUMNS = ("document_id", "created_by", "posting_date", "posting_time")
_DEFAULT_DETECTOR_FACTORIES = {
    "unsupervised": UnsupervisedDetector,
    "supervised": SupervisedDetector,
    "transformer": TransformerDetector,
    "sequence": SequenceDetector,
    "stacking": EnsembleDetector,
}
_PROMOTED_TRACK_MAP = {
    "supervised": "ml_supervised",
    "unsupervised": "ml_unsupervised",
    "ft_transformer": "ml_transformer",
    "bilstm_sequence": "ml_sequence",
    "stacking_meta": "ensemble",
}
_FAMILY_TO_CANONICAL_MODEL = {
    "unsupervised": "unsupervised",
    "supervised": "supervised",
    "transformer": "ft_transformer",
    "sequence": "bilstm_sequence",
    "stacking": "stacking_meta",
}
_DEFAULT_SEARCH_PRESETS = {
    "unsupervised": (
        {
            "name": "balanced",
            "settings_updates": {
                "vae_latent_dim": 32,
                "vae_epochs": 30,
                "if_contamination": 0.01,
            },
        },
        {
            "name": "sensitive",
            "settings_updates": {
                "vae_latent_dim": 64,
                "vae_epochs": 50,
                "if_contamination": 0.02,
            },
        },
    ),
    "supervised": (
        {
            "name": "baseline",
            "settings_updates": {},
            "detector_kwargs": {"use_smote": False},
        },
        {
            "name": "smote",
            "settings_updates": {},
            "detector_kwargs": {"use_smote": True},
        },
    ),
    "transformer": (
        {
            "name": "compact",
            "settings_updates": {
                "ft_d_token": 32,
                "ft_n_layers": 2,
                "ft_n_heads": 4,
                "ft_d_ff": 128,
            },
        },
        {
            "name": "wide",
            "settings_updates": {
                "ft_d_token": 64,
                "ft_n_layers": 3,
                "ft_n_heads": 8,
                "ft_d_ff": 256,
            },
        },
    ),
    "sequence": (
        {
            "name": "short_window",
            "settings_updates": {
                "bilstm_seq_len": 8,
                "bilstm_hidden_size": 64,
            },
        },
        {
            "name": "long_window",
            "settings_updates": {
                "bilstm_seq_len": 16,
                "bilstm_hidden_size": 128,
            },
        },
    ),
    "stacking": (
        {
            "name": "ridge_light",
            "settings_updates": {
                "stacking_alpha": 0.5,
            },
        },
        {
            "name": "ridge_strict",
            "settings_updates": {
                "stacking_alpha": 2.0,
            },
        },
    ),
}


def resolve_phase2_training_dir(ctx=None, base_dir: Path | None = None) -> Path:
    """Return the root directory for Phase 2 training artifacts."""
    if base_dir is not None:
        return Path(base_dir)
    model_dir = getattr(ctx, "model_dir", None)
    if model_dir is not None:
        return Path(model_dir) / "phase2_train"
    return _DEFAULT_PHASE2_TRAIN_DIR


def build_phase2_training_paths(
    ctx=None,
    *,
    report_id: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Path]:
    """Build report/trial/promoted directories for one training run."""
    root = resolve_phase2_training_dir(ctx, base_dir=base_dir)
    training_id = report_id or uuid.uuid4().hex[:12]
    run_root = root / training_id
    return {
        "root": root,
        "run_root": run_root,
        "trials_dir": run_root / "trials",
        "reports_dir": run_root / "reports",
        "promoted_dir": run_root / "promoted",
        "report_path": run_root / "reports" / "training_report.json",
    }


def ensure_phase2_training_dirs(paths: dict[str, Path]) -> dict[str, Path]:
    """Create required artifact directories and return the same path map."""
    for key in ("trials_dir", "reports_dir", "promoted_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def save_phase2_training_report(
    report: Phase2TrainingReport,
    *,
    ctx=None,
    base_dir: Path | None = None,
) -> Path:
    """Persist a Phase 2 training report as JSON."""
    paths = ensure_phase2_training_dirs(
        build_phase2_training_paths(
            ctx,
            report_id=report.report_id,
            base_dir=base_dir,
        ),
    )
    report.status = (
        report.status
        if report.status != Phase2TrainingStatus.PENDING
        else Phase2TrainingStatus.COMPLETED
    )
    report_path = paths["report_path"]
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def initialize_phase2_training_report(
    *,
    ctx=None,
    report_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Phase2TrainingReport:
    """Create the minimal training report skeleton for a new AutoML run."""
    return Phase2TrainingReport(
        report_id=report_id or uuid.uuid4().hex[:12],
        company_id=getattr(ctx, "company_id", None),
        engagement_id=getattr(ctx, "engagement_id", None),
        status=Phase2TrainingStatus.PENDING,
        metadata=metadata or {},
    )


def build_phase2_label_summary(
    df,
    *,
    detection_scores=None,
    feedback_labels=None,
    strategy: str = "hybrid",
) -> tuple[Phase2LabelSummary, Any]:
    """Resolve the training label gate summary from feedback or dataset labels."""
    feedback_result = create_labels_from_feedback(df, feedback_labels)
    label_result = feedback_result or create_labels(
        df,
        detection_scores=detection_scores,
        strategy=strategy,
    )
    summary = Phase2LabelSummary(
        strategy=str(label_result.strategy),
        label_source=str(label_result.label_source),
        gate_status=str(label_result.gate_status),
        gate_reason=label_result.gate_reason,
        is_supervised_eligible=bool(label_result.is_supervised_eligible),
        positive_count=int(label_result.positive_count),
        positive_rate=float(label_result.positive_rate),
    )
    return summary, label_result


def prepare_phase2_feature_inputs(df) -> tuple[Any, Any, dict[str, Any]]:
    """Build cleaned training features, groups, and quality metadata once."""
    profile = profile_dataframe(df)
    raw_groups = classify_features(profile)
    cleaned_df, adjusted_groups, feature_quality = apply_feature_quality_policy(
        df,
        raw_groups,
        for_training=True,
    )
    payload = {
        "raw_groups": _feature_groups_to_dict(raw_groups),
        "adjusted_groups": _feature_groups_to_dict(adjusted_groups),
        "feature_quality_profile": feature_quality.to_dict(),
        "feature_variants": build_phase2_feature_variants(cleaned_df, adjusted_groups),
    }
    return cleaned_df, adjusted_groups, payload


def build_phase2_feature_variants(df, groups) -> list[dict[str, Any]]:
    """Expand feature-family ablations into concrete variant column sets."""
    if groups is None:
        return []
    all_columns = [col for col in groups.all_features if col in df.columns]
    optional_columns = {
        family: [col for col in columns if col in all_columns]
        for family, columns in FEATURE_FAMILIES.items()
    }
    optional_active = {
        family: cols
        for family, cols in optional_columns.items()
        if cols
    }
    baseline_columns = [
        col
        for col in all_columns
        if not any(col in cols for cols in optional_active.values())
    ]

    variants: list[dict[str, Any]] = [
        {
            "variant": "baseline_core",
            "include_families": [],
            "feature_columns": baseline_columns,
            "feature_count": len(baseline_columns),
            "description": "Core stable features only",
        }
    ]
    for family, columns in optional_active.items():
        merged = _merge_feature_columns(baseline_columns, columns)
        variants.append(
            {
                "variant": f"plus_{family}",
                "include_families": [family],
                "feature_columns": merged,
                "feature_count": len(merged),
                "description": f"Baseline + {family} family",
            }
        )
    if optional_active:
        variants.append(
            {
                "variant": "full_active",
                "include_families": list(optional_active.keys()),
                "feature_columns": all_columns,
                "feature_count": len(all_columns),
                "description": "All currently active optional families",
            }
        )
    return variants


def build_phase2_training_report(
    df,
    *,
    ctx=None,
    report_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    detection_scores=None,
    feedback_labels=None,
    strategy: str = "hybrid",
    model_families: list[str] | tuple[str, ...] | None = None,
) -> Phase2TrainingReport:
    """Create the initial Phase 2 training orchestration report."""
    report = initialize_phase2_training_report(
        ctx=ctx,
        report_id=report_id,
        metadata=metadata,
    )
    label_summary, _label_result = build_phase2_label_summary(
        df,
        detection_scores=detection_scores,
        feedback_labels=feedback_labels,
        strategy=strategy,
    )
    cleaned_df, _groups, feature_payload = prepare_phase2_feature_inputs(df)

    families = list(model_families or _DEFAULT_MODEL_FAMILIES)
    variants = feature_payload["feature_variants"]
    search_presets = build_phase2_search_presets(families)
    report.label_summary = label_summary
    report.status = Phase2TrainingStatus.RUNNING
    report.metadata.update(
        {
            "candidate_families": families,
            "feature_row_count": int(len(cleaned_df)),
            "feature_column_count": int(len(cleaned_df.columns)),
            "feature_variant_count": len(variants),
            "search_preset_count": sum(len(presets) for presets in search_presets.values()),
            "feature_quality_profile": feature_payload["feature_quality_profile"],
            "adjusted_feature_groups": feature_payload["adjusted_groups"],
            "search_presets": search_presets,
        }
    )
    report.leaderboard.extend(
        _build_trial_queue(
            families=families,
            variants=variants,
            label_summary=label_summary,
            search_presets=search_presets,
        ),
    )
    return report


def run_phase2_training(
    df,
    *,
    ctx=None,
    report_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    detection_scores=None,
    feedback_labels=None,
    strategy: str = "hybrid",
    model_families: list[str] | tuple[str, ...] | None = None,
    detector_factories: dict[str, Any] | None = None,
    base_dir: Path | None = None,
    save_report: bool = True,
) -> Phase2TrainingReport:
    """Execute Phase 2 training trials and persist a training report."""
    report = initialize_phase2_training_report(
        ctx=ctx,
        report_id=report_id,
        metadata=metadata,
    )
    paths = ensure_phase2_training_dirs(
        build_phase2_training_paths(
            ctx=ctx,
            report_id=report.report_id,
            base_dir=base_dir,
        )
    )
    settings = getattr(ctx, "settings", None) or get_settings()
    registry_dir = getattr(ctx, "model_dir", None) or paths["promoted_dir"]
    registry = ModelRegistry(registry_dir=registry_dir)
    factories = dict(_DEFAULT_DETECTOR_FACTORIES)
    if detector_factories:
        factories.update(detector_factories)

    label_summary, label_result = build_phase2_label_summary(
        df,
        detection_scores=detection_scores,
        feedback_labels=feedback_labels,
        strategy=strategy,
    )
    cleaned_df, groups, feature_payload = prepare_phase2_feature_inputs(df)
    families = list(model_families or _DEFAULT_MODEL_FAMILIES)
    variants = feature_payload["feature_variants"]
    search_presets = build_phase2_search_presets(families)

    report.label_summary = label_summary
    report.status = Phase2TrainingStatus.RUNNING
    report.metadata.update(
        {
            "candidate_families": families,
            "feature_row_count": int(len(cleaned_df)),
            "feature_column_count": int(len(cleaned_df.columns)),
            "feature_variant_count": len(variants),
            "search_preset_count": sum(len(presets) for presets in search_presets.values()),
            "feature_quality_profile": feature_payload["feature_quality_profile"],
            "adjusted_feature_groups": feature_payload["adjusted_groups"],
            "registry_dir": str(registry_dir),
            "search_presets": search_presets,
        }
    )
    report.leaderboard = _build_trial_queue(
        families=families,
        variants=variants,
        label_summary=label_summary,
        search_presets=search_presets,
    )

    trained_results: dict[str, list[dict[str, Any]]] = {}
    for trial in report.leaderboard:
        if trial.status != Phase2TrainingStatus.PENDING:
            _write_trial_artifact(paths["trials_dir"], trial)
            continue
        family = trial.model_family
        variant_df = _build_variant_frame(cleaned_df, trial, family)
        variant_groups = _subset_feature_groups(groups, variant_df.columns)
        if family == "stacking":
            _execute_stacking_trial(
                trial=trial,
                trial_df=variant_df,
                label_result=label_result,
                groups=variant_groups,
                registry=registry,
                settings=settings,
                detector_factory=factories[family],
                trained_results=trained_results,
            )
        else:
            _execute_model_trial(
                trial=trial,
                trial_df=variant_df,
                label_result=label_result,
                groups=variant_groups,
                registry=registry,
                settings=settings,
                detector_factory=factories[family],
                family=family,
                trained_results=trained_results,
            )
        _write_trial_artifact(paths["trials_dir"], trial)

    report.leaderboard = _sort_trials(report.leaderboard)
    promotion_policy = _build_promotion_policy(report.leaderboard)
    report.promoted_models = _select_promoted_models(
        report.leaderboard,
        policy=promotion_policy,
    )
    if report.promoted_models:
        report.metadata["best_overall_model"] = report.promoted_models[0].to_dict()
    report.metadata.update(_build_trial_report_metadata(report.leaderboard))
    report.metadata["promotion_policy"] = promotion_policy
    report.metadata["inference_contract"] = _build_inference_contract(
        report_id=report.report_id,
        promoted_models=report.promoted_models,
        promotion_policy=promotion_policy,
    )
    report.status = _finalize_report_status(report.leaderboard)
    if save_report:
        save_phase2_training_report(report, ctx=ctx, base_dir=base_dir)
    return report


def _build_trial_queue(
    *,
    families: list[str],
    variants: list[dict[str, Any]],
    label_summary: Phase2LabelSummary,
    search_presets: dict[str, list[dict[str, Any]]],
) -> list[Phase2TrialResult]:
    queue: list[Phase2TrialResult] = []
    for family in families:
        for variant in variants:
            for preset in search_presets.get(family, []):
                is_supervised_family = family in _SUPERVISED_FAMILIES
                allowed = (not is_supervised_family) or label_summary.is_supervised_eligible
                status = (
                    Phase2TrainingStatus.PENDING
                    if allowed
                    else Phase2TrainingStatus.SKIPPED
                )
                queue.append(
                    Phase2TrialResult(
                        model_family=family,
                        variant=f"{variant['variant']}__{preset['name']}",
                        status=status,
                        params={
                            "feature_variant": str(variant["variant"]),
                            "search_name": str(preset["name"]),
                            "include_families": list(variant["include_families"]),
                            "feature_columns": list(variant["feature_columns"]),
                            "feature_count": int(variant["feature_count"]),
                            "settings_updates": dict(preset.get("settings_updates", {})),
                            "detector_kwargs": dict(preset.get("detector_kwargs", {})),
                        },
                        gate_reason=None if allowed else label_summary.gate_reason,
                        metadata={
                            "description": variant["description"],
                            "family_role": (
                                "core"
                                if family == "unsupervised"
                                else "optional"
                            ),
                            "search_name": str(preset["name"]),
                        },
                    )
                )
    return queue


def _execute_model_trial(
    *,
    trial: Phase2TrialResult,
    trial_df,
    label_result,
    groups,
    registry: ModelRegistry,
    settings,
    detector_factory,
    family: str,
    trained_results: dict[str, list[dict[str, Any]]],
) -> None:
    start = time.perf_counter()
    trial_settings = _build_trial_settings(settings, trial)
    detector = _build_detector(
        detector_factory,
        settings=trial_settings,
        registry=registry,
        detector_kwargs=trial.params.get("detector_kwargs", {}),
    )
    try:
        if family == "unsupervised":
            train_info = detector.train(trial_df, groups, y=label_result.y)
        else:
            train_info = detector.train(trial_df, label_result, groups)
        detect_result = detector.detect(trial_df)
        metric_name, metric_value = _compute_trial_metric(detect_result, label_result.y)
        save_meta = detector.save_model(metric_value or 0.0)
        trial.status = Phase2TrainingStatus.COMPLETED
        trial.metric_name = metric_name
        trial.metric_value = metric_value
        trial.params.update(_compact_train_info(train_info))
        trial.metadata.update(
            {
                "settings_updates": dict(trial.params.get("settings_updates", {})),
                "saved_model_name": getattr(save_meta, "model_name", family),
                "registry_version": getattr(save_meta, "version", None),
                "registry_path": getattr(save_meta, "file_path", None),
            }
        )
        trained_results.setdefault(family, []).append(
            {
                "trial_variant": trial.variant,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "detector": detector,
                "detect_result": detect_result,
                "save_meta": save_meta,
                "train_info": train_info,
            }
        )
    except Exception as exc:
        trial.status = Phase2TrainingStatus.FAILED
        trial.gate_reason = trial.gate_reason or type(exc).__name__
        trial.warnings.append(str(exc))
    finally:
        trial.elapsed_sec = time.perf_counter() - start


def _execute_stacking_trial(
    *,
    trial: Phase2TrialResult,
    trial_df,
    label_result,
    groups,
    registry: ModelRegistry,
    settings,
    detector_factory,
    trained_results: dict[str, list[dict[str, Any]]],
) -> None:
    start = time.perf_counter()
    required = ("unsupervised", "supervised", "transformer", "sequence")
    missing = [family for family in required if not trained_results.get(family)]
    if missing:
        trial.status = Phase2TrainingStatus.SKIPPED
        trial.gate_reason = "missing_base_models"
        trial.warnings.append("missing trained base models: " + ", ".join(missing))
        trial.elapsed_sec = time.perf_counter() - start
        return

    trial_settings = _build_trial_settings(settings, trial)
    detector = _build_detector(
        detector_factory,
        settings=trial_settings,
        registry=registry,
        detector_kwargs=trial.params.get("detector_kwargs", {}),
    )
    try:
        best_inputs = {
            family: _select_best_trained_entry(trained_results[family])
            for family in required
        }
        oof_ready = (
            hasattr(detector, "train_oof")
            and groups is not None
            and "created_by" in trial_df.columns
            and trial_df["created_by"].nunique(dropna=True) >= 2
        )
        if oof_ready:
            base_results = [best_inputs["unsupervised"]["detect_result"]]
            train_info = detector.train_oof(
                trial_df,
                label_result,
                user_ids=trial_df["created_by"].astype(str).to_numpy(),
                df_index=trial_df.index,
                non_leakage_results=base_results,
                groups=groups,
            )
            inference_results = [
                best_inputs["unsupervised"]["detect_result"],
                best_inputs["supervised"]["detect_result"],
                best_inputs["transformer"]["detect_result"],
                best_inputs["sequence"]["detect_result"],
            ]
            detect_result = detector.detect_from_results(inference_results, trial_df.index)
        else:
            base_results = [
                best_inputs["unsupervised"]["detect_result"],
                best_inputs["supervised"]["detect_result"],
                best_inputs["transformer"]["detect_result"],
                best_inputs["sequence"]["detect_result"],
            ]
            train_info = detector.train_from_results(base_results, label_result.y, trial_df.index)
            detect_result = detector.detect_from_results(base_results, trial_df.index)
        metric_name, metric_value = _compute_trial_metric(detect_result, label_result.y)
        save_meta = detector.save_model(metric_value or 0.0)
        trial.status = Phase2TrainingStatus.COMPLETED
        trial.metric_name = metric_name
        trial.metric_value = metric_value
        trial.params.update(_compact_train_info(train_info))
        trial.metadata.update(
            {
                "settings_updates": dict(trial.params.get("settings_updates", {})),
                "stacking_mode": str(train_info.get("mode", "stacking")),
                "base_input_variants": (
                    {
                        "unsupervised": best_inputs["unsupervised"]["trial_variant"],
                        "supervised": trial.variant,
                        "transformer": trial.variant,
                        "sequence": trial.variant,
                    }
                    if oof_ready
                    else {
                        family: best_inputs[family]["trial_variant"] for family in required
                    }
                ),
                "saved_model_name": getattr(save_meta, "model_name", "stacking"),
                "registry_version": getattr(save_meta, "version", None),
                "registry_path": getattr(save_meta, "file_path", None),
            }
        )
    except Exception as exc:
        trial.status = Phase2TrainingStatus.FAILED
        trial.gate_reason = trial.gate_reason or type(exc).__name__
        trial.warnings.append(str(exc))
    finally:
        trial.elapsed_sec = time.perf_counter() - start


def _compute_trial_metric(detect_result, y_true) -> tuple[str, float | None]:
    if len(y_true) == 0:
        return "flagged_ratio", None
    positives = int((pd.Series(y_true) == 1).sum())
    if positives > 0:
        flagged = set(int(idx) for idx in detect_result.flagged_indices)
        y_pred = [1 if int(idx) in flagged else 0 for idx in detect_result.scores.index]
        return "f1_macro", float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    flagged_ratio = float(len(detect_result.flagged_indices) / max(len(detect_result.scores), 1))
    return "flagged_ratio", flagged_ratio


def _compact_train_info(train_info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in dict(train_info or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, (list, tuple)) and len(value) <= 10:
            compact[key] = list(value)
    return compact


def build_phase2_search_presets(
    families: list[str] | tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    return {
        family: [dict(preset) for preset in _DEFAULT_SEARCH_PRESETS.get(family, ({"name": "default"},))]
        for family in families
    }


def _build_variant_frame(cleaned_df, trial: Phase2TrialResult, family: str):
    selected = list(trial.params.get("feature_columns", []))
    required = list(selected)
    if family in {"sequence", "stacking"}:
        for col in _SEQUENCE_CONTEXT_COLUMNS:
            if col in cleaned_df.columns and col not in required:
                required.append(col)
    return cleaned_df.loc[:, [col for col in required if col in cleaned_df.columns]].copy()


def _build_trial_settings(settings, trial: Phase2TrialResult):
    updates = dict(trial.params.get("settings_updates", {}))
    if not updates:
        return settings
    if hasattr(settings, "model_copy"):
        return settings.model_copy(update=updates)
    cloned = dict(getattr(settings, "__dict__", {}))
    cloned.update(updates)
    return type(settings)(**cloned)


def _build_detector(detector_factory, *, settings, registry, detector_kwargs: dict[str, Any]):
    kwargs = dict(detector_kwargs or {})
    try:
        return detector_factory(settings=settings, model_registry=registry, **kwargs)
    except TypeError:
        return detector_factory(settings=settings, model_registry=registry)


def _subset_feature_groups(groups, columns) -> Any:
    if groups is None:
        return None
    selected = set(columns)
    return type(groups)(
        numeric=[col for col in groups.numeric if col in selected],
        categorical_high=[col for col in groups.categorical_high if col in selected],
        categorical_low=[col for col in groups.categorical_low if col in selected],
        boolean=[col for col in groups.boolean if col in selected],
        ordinal=[col for col in groups.ordinal if col in selected],
        excluded=[col for col in groups.excluded if col in selected],
    )


def _write_trial_artifact(trials_dir: Path, trial: Phase2TrialResult) -> Path:
    artifact_path = trials_dir / f"{trial.model_family}__{trial.variant}.json"
    artifact_path.write_text(
        json.dumps(trial.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trial.artifact_path = str(artifact_path)
    return artifact_path


def _finalize_report_status(trials: list[Phase2TrialResult]) -> Phase2TrainingStatus:
    statuses = {trial.status for trial in trials}
    if statuses and statuses <= {Phase2TrainingStatus.SKIPPED}:
        return Phase2TrainingStatus.SKIPPED
    if Phase2TrainingStatus.FAILED in statuses:
        completed = any(status == Phase2TrainingStatus.COMPLETED for status in statuses)
        return Phase2TrainingStatus.COMPLETED if completed else Phase2TrainingStatus.FAILED
    if any(status == Phase2TrainingStatus.COMPLETED for status in statuses):
        return Phase2TrainingStatus.COMPLETED
    return Phase2TrainingStatus.RUNNING


def _select_best_trained_entry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        entries,
        key=lambda item: (
            item.get("metric_value") if item.get("metric_value") is not None else float("-inf"),
            item.get("trial_variant", ""),
        ),
    )


def _sort_trials(trials: list[Phase2TrialResult]) -> list[Phase2TrialResult]:
    status_rank = {
        Phase2TrainingStatus.COMPLETED: 0,
        Phase2TrainingStatus.RUNNING: 1,
        Phase2TrainingStatus.PENDING: 2,
        Phase2TrainingStatus.SKIPPED: 3,
        Phase2TrainingStatus.FAILED: 4,
    }
    return sorted(
        trials,
        key=lambda trial: (
            status_rank.get(trial.status, 99),
            -(trial.metric_value if trial.metric_value is not None else float("-inf")),
            trial.model_family,
            trial.variant,
        ),
    )


def _select_promoted_models(
    trials: list[Phase2TrialResult],
    *,
    policy: dict[str, Any] | None = None,
) -> list[Phase2PromotedModel]:
    winners: list[Phase2PromotedModel] = []
    promotion_policy = dict(policy or {})
    completed = _eligible_promotion_trials(trials, promotion_policy)
    by_family: dict[str, list[Phase2TrialResult]] = {}
    for trial in completed:
        by_family.setdefault(trial.model_family, []).append(trial)

    for family, family_trials in by_family.items():
        best = max(family_trials, key=_promotion_sort_key)
        winners.append(
            Phase2PromotedModel(
                model_name=_canonical_phase2_model_name(family),
                source_trial_variant=best.variant,
                metric_name=best.metric_name,
                metric_value=float(best.metric_value or 0.0),
                registry_version=best.metadata.get("registry_version"),
                registry_path=best.metadata.get("registry_path"),
            )
        )

    winners.sort(key=lambda item: item.metric_value, reverse=True)
    return winners


def _build_trial_report_metadata(
    trials: list[Phase2TrialResult],
) -> dict[str, Any]:
    return {
        "trial_status_counts": _count_trial_statuses(trials),
        "family_summaries": _build_family_summaries(trials),
        "search_summaries": _build_search_summaries(trials),
        "feature_variant_summaries": _build_feature_variant_summaries(trials),
    }


def _build_promotion_policy(trials: list[Phase2TrialResult]) -> dict[str, Any]:
    completed = [trial for trial in trials if trial.status == Phase2TrainingStatus.COMPLETED]
    family_completed_counts: dict[str, int] = {}
    for trial in completed:
        family_completed_counts[trial.model_family] = (
            family_completed_counts.get(trial.model_family, 0) + 1
        )
    metric_names = sorted({trial.metric_name for trial in completed if trial.metric_name})
    return {
        "selection_mode": "best_per_family",
        "eligible_statuses": [Phase2TrainingStatus.COMPLETED.value],
        "requires_registry_version": True,
        "requires_metric_value": True,
        "min_completed_trials_per_family": 1,
        "sort_priority": [
            "metric_value_desc",
            "elapsed_sec_asc",
            "variant_asc",
        ],
        "tie_break_policy": {
            "primary": "metric_value_desc",
            "secondary": "elapsed_sec_asc",
            "tertiary": "variant_asc",
        },
        "metric_names_seen": metric_names,
        "completed_trial_count": len(completed),
        "family_completed_counts": family_completed_counts,
    }


def _build_inference_contract(
    *,
    report_id: str,
    promoted_models: list[Phase2PromotedModel],
    promotion_policy: dict[str, Any],
) -> dict[str, Any]:
    promoted_versions = {
        model.model_name: model.registry_version
        for model in promoted_models
        if model.registry_version is not None
    }
    return {
        "source_report_id": report_id,
        "selection_mode": promotion_policy.get("selection_mode", "best_per_family"),
        "required_models": [model.model_name for model in promoted_models],
        "promoted_versions": promoted_versions,
        "track_map": {
            model_name: track_name
            for model_name, track_name in _PROMOTED_TRACK_MAP.items()
            if model_name in promoted_versions
        },
    }


def _count_trial_statuses(trials: list[Phase2TrialResult]) -> dict[str, int]:
    counts = {status.value: 0 for status in Phase2TrainingStatus}
    for trial in trials:
        counts[trial.status.value] = counts.get(trial.status.value, 0) + 1
    return counts


def _build_family_summaries(
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Phase2TrialResult]] = {}
    for trial in trials:
        grouped.setdefault(trial.model_family, []).append(trial)
    return {
        family: _build_group_summary(group_trials)
        for family, group_trials in grouped.items()
    }


def _build_search_summaries(
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, list[Phase2TrialResult]]] = {}
    for trial in trials:
        search_name = str(trial.metadata.get("search_name") or trial.params.get("search_name") or "-")
        grouped.setdefault(trial.model_family, {}).setdefault(search_name, []).append(trial)
    return {
        family: {
            search_name: _build_group_summary(search_trials)
            for search_name, search_trials in search_groups.items()
        }
        for family, search_groups in grouped.items()
    }


def _build_feature_variant_summaries(
    trials: list[Phase2TrialResult],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Phase2TrialResult]] = {}
    for trial in trials:
        feature_variant = str(trial.params.get("feature_variant") or _split_trial_variant(trial.variant)[0])
        grouped.setdefault(feature_variant, []).append(trial)
    return {
        feature_variant: _build_group_summary(variant_trials)
        for feature_variant, variant_trials in grouped.items()
    }


def _build_group_summary(trials: list[Phase2TrialResult]) -> dict[str, Any]:
    status_counts = _count_trial_statuses(trials)
    best = _select_best_metric_trial(trials)
    return {
        "trial_count": len(trials),
        "status_counts": status_counts,
        "best_variant": best.variant if best is not None else None,
        "best_metric_name": best.metric_name if best is not None else None,
        "best_metric_value": best.metric_value if best is not None else None,
        "best_search_name": (
            str(best.metadata.get("search_name") or best.params.get("search_name"))
            if best is not None
            else None
        ),
        "best_model_family": best.model_family if best is not None else None,
    }


def _select_best_metric_trial(
    trials: list[Phase2TrialResult],
) -> Phase2TrialResult | None:
    completed = [trial for trial in trials if trial.status == Phase2TrainingStatus.COMPLETED]
    if not completed:
        return None
    return max(
        completed,
        key=lambda trial: (
            trial.metric_value if trial.metric_value is not None else float("-inf"),
            trial.variant,
        ),
    )


def _eligible_promotion_trials(
    trials: list[Phase2TrialResult],
    policy: dict[str, Any],
) -> list[Phase2TrialResult]:
    eligible_statuses = {
        str(value)
        for value in policy.get("eligible_statuses", [Phase2TrainingStatus.COMPLETED.value])
    }
    requires_registry_version = bool(policy.get("requires_registry_version", True))
    requires_metric_value = bool(policy.get("requires_metric_value", True))
    min_completed_trials_per_family = int(policy.get("min_completed_trials_per_family", 1) or 1)
    completed_by_family: dict[str, int] = {}
    for trial in trials:
        if trial.status == Phase2TrainingStatus.COMPLETED:
            completed_by_family[trial.model_family] = (
                completed_by_family.get(trial.model_family, 0) + 1
            )
    eligible: list[Phase2TrialResult] = []
    for trial in trials:
        if trial.status.value not in eligible_statuses:
            continue
        if completed_by_family.get(trial.model_family, 0) < min_completed_trials_per_family:
            continue
        if requires_metric_value and trial.metric_value is None:
            continue
        if requires_registry_version and trial.metadata.get("registry_version") is None:
            continue
        eligible.append(trial)
    return eligible


def _promotion_sort_key(trial: Phase2TrialResult) -> tuple[float, float, str]:
    metric_value = trial.metric_value if trial.metric_value is not None else float("-inf")
    elapsed_sec = float(trial.elapsed_sec or 0.0)
    return (
        metric_value,
        -elapsed_sec,
        trial.variant,
    )


def _canonical_phase2_model_name(family: str) -> str:
    return _FAMILY_TO_CANONICAL_MODEL.get(str(family), str(family))


def _split_trial_variant(variant: str) -> tuple[str, str]:
    feature_variant, _, search_name = str(variant).partition("__")
    return feature_variant or str(variant), search_name or "-"


def _feature_groups_to_dict(groups) -> dict[str, list[str]]:
    if groups is None:
        return {}
    return {
        "numeric": list(groups.numeric),
        "categorical_high": list(groups.categorical_high),
        "categorical_low": list(groups.categorical_low),
        "boolean": list(groups.boolean),
        "ordinal": list(groups.ordinal),
        "excluded": list(groups.excluded),
    }


def _merge_feature_columns(base: list[str], extras: list[str]) -> list[str]:
    merged: list[str] = []
    for col in list(base) + list(extras):
        if col not in merged:
            merged.append(col)
    return merged
