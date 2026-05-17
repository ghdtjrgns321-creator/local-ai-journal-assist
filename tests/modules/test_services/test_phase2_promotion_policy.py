from __future__ import annotations

import json
from pathlib import Path

from src.services.phase2_promotion_policy import (
    build_promotion_decision_payload,
    save_promotion_decision_json,
)
from src.services.phase2_training_models import (
    Phase2PromotedModel,
    Phase2TrainingReport,
    Phase2TrainingStatus,
    Phase2TrialResult,
)


def test_build_promotion_decision_payload_contains_policy_and_reasons():
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
                metric_value=0.51,
            )
        ],
        promoted_models=[
            Phase2PromotedModel(
                model_name="unsupervised",
                source_trial_variant="baseline_core__balanced",
                metric_name="unsupervised_selection_score",
                metric_value=0.51,
                registry_version=3,
            )
        ],
        metadata={
            "promotion_policy": {
                "selection_mode": "best_per_family",
                "eligible_statuses": ["completed"],
            },
            "family_promotion_decisions": {
                "unsupervised": {
                    "eligible_for_promotion": True,
                    "reasons": [],
                }
            },
        },
    )

    payload = build_promotion_decision_payload(report)

    assert payload["schema_version"] == 1
    assert payload["report_id"] == "train_001"
    assert payload["policy"]["selection_mode"] == "best_per_family"
    assert payload["family_decisions"]["unsupervised"]["eligible_for_promotion"] is True
    assert payload["promoted_models"][0]["model_name"] == "unsupervised"
    assert payload["promoted_models"][0]["registry_version"] == 3


def test_save_promotion_decision_json_writes_valid_json(tmp_path: Path):
    report = Phase2TrainingReport(
        report_id="train_001",
        company_id=None,
        engagement_id=None,
        metadata={
            "promotion_policy": {"selection_mode": "best_per_family"},
            "family_promotion_decisions": {
                "supervised": {
                    "eligible_for_promotion": False,
                    "reasons": ["insufficient_completed_trials"],
                }
            },
        },
    )

    path = save_promotion_decision_json(report, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "promotion_decision.json"
    assert payload["family_decisions"]["supervised"]["reasons"] == [
        "insufficient_completed_trials"
    ]
