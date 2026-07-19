from __future__ import annotations

import json
from pathlib import Path

from src.services.phase2_leaderboard import (
    build_leaderboard_payload,
    save_leaderboard_json,
)
from src.services.phase2_training_models import (
    Phase2TrainingReport,
    Phase2TrainingStatus,
    Phase2TrialResult,
)


def test_build_leaderboard_payload_splits_family_preset_and_trial():
    report = Phase2TrainingReport(
        report_id="train_001",
        company_id="acme",
        engagement_id="2025",
        status=Phase2TrainingStatus.COMPLETED,
        leaderboard=[
            Phase2TrialResult(
                model_family="unsupervised",
                variant="baseline_core__balanced",
                status=Phase2TrainingStatus.COMPLETED,
                metric_name="unsupervised_selection_score",
                metric_value=0.42,
                artifact_path="trials/unsupervised__baseline_core__balanced.json",
                metadata={"registry_version": 7, "matrix_builder": {"schema_hash": "abc"}},
            )
        ],
    )

    payload = build_leaderboard_payload(report)

    assert payload["schema_version"] == 1
    assert payload["report_id"] == "train_001"
    assert payload["rows"][0]["family"] == "unsupervised"
    assert payload["rows"][0]["trial"] == "baseline_core"
    assert payload["rows"][0]["preset"] == "balanced"
    assert payload["rows"][0]["metric"]["name"] == "unsupervised_selection_score"
    assert payload["rows"][0]["metric"]["value"] == 0.42
    assert payload["rows"][0]["model_version"] == 7
    assert payload["rows"][0]["schema_hash"] == "abc"


def test_save_leaderboard_json_writes_valid_json(tmp_path: Path):
    report = Phase2TrainingReport(
        report_id="train_001",
        company_id=None,
        engagement_id=None,
        leaderboard=[
            Phase2TrialResult(
                model_family="supervised",
                variant="full_active__baseline",
                status=Phase2TrainingStatus.SKIPPED,
                gate_reason="insufficient_positive_count",
            )
        ],
    )

    path = save_leaderboard_json(report, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "leaderboard.json"
    assert payload["rows"][0]["status"] == "skipped"
    assert payload["rows"][0]["gate_reason"] == "insufficient_positive_count"
