"""Artifact persistence helpers for PHASE1 case results."""

from __future__ import annotations

import json
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


# 모델에서 사라졌지만 예전 아티팩트에는 남아 있는 case 키.
#
# Why: CaseGroupResult 는 extra="forbid" 라 모르는 키가 하나라도 있으면 로드가 통째로
#      실패한다. 필드를 지운 그날부터 저장돼 있던 결과를 못 읽게 되는 셈이라, 읽는
#      쪽에서 명시적으로 걷어낸다. forbid 는 그대로 둬서 오타·신규 오염은 계속 막는다.
#      macro_contexts: 2026-07-25 삭제. D01/D02 꼬리표 폐지로 공급자가 사라진 필드.
_LEGACY_CASE_KEYS: frozenset[str] = frozenset({"macro_contexts"})


def load_phase1_case_result(path: str | Path) -> Phase1CaseResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    _strip_legacy_case_keys(payload)
    return Phase1CaseResult.model_validate(payload)


def _strip_legacy_case_keys(payload: Any) -> None:
    """구버전 아티팩트의 폐기된 case 키를 제자리에서 제거."""
    if not isinstance(payload, dict):
        return
    for case in payload.get("cases") or []:
        if isinstance(case, dict):
            for key in _LEGACY_CASE_KEYS:
                case.pop(key, None)


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
