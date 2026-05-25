"""Artifact persistence helpers for PHASE1 case results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT
from src.detection.base import DetectionResult
from src.models.phase1_case import Phase1CaseResult


def phase1_case_artifact_path(company_id: str, run_id: str) -> Path:
    return PROJECT_ROOT / "artifacts" / "phase1_cases" / company_id / f"{run_id}.json"


def save_phase1_case_result(result: Phase1CaseResult) -> Path:
    path = phase1_case_artifact_path(result.company_id, result.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_phase1_case_result(path: str | Path) -> Phase1CaseResult:
    artifact_path = Path(path)
    return Phase1CaseResult.model_validate_json(artifact_path.read_text(encoding="utf-8"))


def annotate_detection_results_with_phase1_refs(
    results: list[DetectionResult],
    phase1_result: Phase1CaseResult,
    artifact_path: Path,
) -> None:
    reference = build_phase1_case_reference(phase1_result, artifact_path)
    for result in results:
        result.metadata["phase1_case_run_id"] = reference["phase1_case_run_id"]
        result.metadata["phase1_case_path"] = reference["phase1_case_path"]
        result.metadata["phase1_case_count"] = reference["phase1_case_count"]
        result.metadata["phase1_macro_finding_count"] = reference["phase1_macro_finding_count"]
        result.metadata["top_theme_ids"] = reference["top_theme_ids"]
        result.metadata["phase1_case_schema_version"] = reference["phase1_case_schema_version"]


def build_phase1_case_reference(
    phase1_result: Phase1CaseResult,
    artifact_path: str | Path,
) -> dict[str, Any]:
    return {
        "phase1_case_run_id": phase1_result.run_id,
        "phase1_case_path": str(artifact_path),
        "phase1_case_count": len(phase1_result.cases),
        "phase1_macro_finding_count": int(
            phase1_result.metadata.get("macro_finding_count", 0) or 0
        ),
        "top_theme_ids": [summary.theme_id for summary in phase1_result.theme_summaries[:3]],
        "phase1_case_schema_version": phase1_result.schema_version,
    }
