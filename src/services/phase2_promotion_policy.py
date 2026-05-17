"""Auditable Phase 2 promotion decision artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.services.phase2_training_models import Phase2TrainingReport


def build_promotion_decision_payload(report: Phase2TrainingReport) -> dict[str, Any]:
    """Build the stable `promotion_decision.json` payload."""
    return {
        "schema_version": 1,
        "report_id": report.report_id,
        "company_id": report.company_id,
        "engagement_id": report.engagement_id,
        "policy": dict(report.metadata.get("promotion_policy", {})),
        "family_decisions": dict(report.metadata.get("family_promotion_decisions", {})),
        "promoted_models": [model.to_dict() for model in report.promoted_models],
    }


def save_promotion_decision_json(
    report: Phase2TrainingReport,
    reports_dir: Path,
) -> Path:
    """Persist `promotion_decision.json` below the report artifact directory."""
    path = Path(reports_dir) / "promotion_decision.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            build_promotion_decision_payload(report),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
