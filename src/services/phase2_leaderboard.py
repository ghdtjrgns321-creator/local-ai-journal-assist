"""Serializable Phase 2 AutoML leaderboard artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.services.phase2_training_models import Phase2TrainingReport, Phase2TrialResult


def build_leaderboard_payload(report: Phase2TrainingReport) -> dict[str, Any]:
    """Build the stable `leaderboard.json` payload for one training report."""
    return {
        "schema_version": 1,
        "report_id": report.report_id,
        "company_id": report.company_id,
        "engagement_id": report.engagement_id,
        "rows": [_trial_to_row(trial) for trial in report.leaderboard],
    }


def save_leaderboard_json(report: Phase2TrainingReport, reports_dir: Path) -> Path:
    """Persist `leaderboard.json` below the report artifact directory."""
    path = Path(reports_dir) / "leaderboard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_leaderboard_payload(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _trial_to_row(trial: Phase2TrialResult) -> dict[str, Any]:
    trial_name, preset = _split_trial_variant(trial.variant)
    return {
        "family": trial.model_family,
        "trial": trial_name,
        "preset": preset,
        "variant": trial.variant,
        "status": trial.status.value,
        "metric": {
            "name": trial.metric_name,
            "value": trial.metric_value,
        },
        "elapsed_sec": trial.elapsed_sec,
        "gate_reason": trial.gate_reason,
        "artifact_path": trial.artifact_path,
        "model_version": trial.metadata.get("registry_version"),
        "schema_hash": _trial_schema_hash(trial),
        "metadata": dict(trial.metadata),
    }


def _split_trial_variant(variant: str) -> tuple[str, str]:
    trial, sep, preset = str(variant).partition("__")
    return trial, preset if sep else ""


def _trial_schema_hash(trial: Phase2TrialResult) -> str | None:
    matrix = trial.metadata.get("matrix_builder")
    if isinstance(matrix, dict):
        value = matrix.get("schema_hash")
        return None if value is None else str(value)
    return None
