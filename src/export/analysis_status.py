"""Export용 배치 분석 상태 요약 헬퍼."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

_STATUS_LABELS = {
    "failed": "실패",
    "degraded": "부분 분석",
    "executed": "실행 완료",
    "unknown": "상태 미확인",
}


def summarize_export_analysis_status(pr: PipelineResult) -> dict[str, Any]:
    """Export 문서에 표시할 배치 상태와 근거를 계산한다."""
    raw_statuses = getattr(pr, "detector_statuses", None) or []
    counts = Counter()
    for item in raw_statuses:
        status = str(item.get("run_status") or item.get("status") or "unknown")
        counts[status] += 1

    if counts["failed"] > 0:
        status = "failed"
        detail = "실패 detector가 있어 결과 신뢰성 검토가 필요합니다."
    elif counts["degraded"] > 0:
        status = "degraded"
        detail = "coverage 제한 detector가 있어 일부 분석 범위가 축소되었습니다."
    elif counts["executed"] > 0:
        status = "executed"
        detail = "저장된 detector 기준으로 정상 실행이 확인되었습니다."
    else:
        status = "unknown"
        detail = "detector 상태 정보가 없어 실행 범위를 확인할 수 없습니다."

    phase2_contract = getattr(pr, "phase2_inference_contract", None) or {}
    promoted_versions = dict(phase2_contract.get("promoted_versions") or {})
    required_models = list(phase2_contract.get("required_models") or [])
    family_sub_detectors = {
        str(key): [str(item) for item in value]
        for key, value in dict(phase2_contract.get("family_sub_detectors") or {}).items()
    }
    phase2_summary = {
        "training_report_id": getattr(pr, "phase2_training_report_id", None),
        "inference_mode": getattr(pr, "phase2_inference_mode", None),
        "contract_version": phase2_contract.get(
            "contract_version",
            "phase2_unsupervised_mvp_v1",
        ),
        "selection_mode": phase2_contract.get("selection_mode"),
        "required_model_count": len(required_models),
        "promoted_model_count": len(promoted_versions),
        "required_models": required_models,
        "promoted_versions": promoted_versions,
        "family_sub_detectors": family_sub_detectors,
        "metric_semantics": phase2_contract.get(
            "metric_semantics",
            {
                "metric_name": "unsupervised_selection_score",
                "interpretation": "ranking/calibration proxy, not fraud accuracy",
                "precision_recall_f1_policy": "ground_truth_only",
                "flagged_ratio_role": "metadata_only",
            },
        ),
    }
    phase3_insight = getattr(pr, "phase3_insight", None)
    phase3_case_narratives = list(getattr(pr, "phase3_case_narratives", []) or [])
    phase2_case_overlays = list(getattr(pr, "phase2_case_overlays", []) or [])
    phase3_summary = {
        "available": phase3_insight is not None or bool(phase3_case_narratives),
        "top_risk_count": len(getattr(phase3_insight, "top_risks", []) or []),
        "significant_tx_count": len(
            getattr(phase3_insight, "significant_tx_opinions", []) or []
        ),
        "case_narrative_count": len(phase3_case_narratives),
        "phase2_linked": bool(
            getattr(phase3_insight, "phase2_context", {}) or phase2_case_overlays
        ),
    }

    return {
        "status": status,
        "label": _STATUS_LABELS[status],
        "detail": detail,
        "counts": dict(counts),
        "warning_count": len(getattr(pr, "warnings", None) or []),
        "phase2_contract": phase2_summary,
        "phase3_insight": phase3_summary,
    }


def build_phase_provenance_lines(pr: PipelineResult) -> list[str]:
    """Return human-readable provenance lines for export surfaces."""
    summary = summarize_export_analysis_status(pr)
    phase2 = summary["phase2_contract"]
    phase3 = summary["phase3_insight"]

    lines: list[str] = []
    if phase2.get("training_report_id") or phase2.get("inference_mode"):
        sub_detector_count = sum(
            len(items) for items in phase2.get("family_sub_detectors", {}).values()
        )
        lines.append(
            "Phase 2 provenance: "
            f"train={phase2.get('training_report_id') or '-'} | "
            f"mode={phase2.get('inference_mode') or '-'} | "
            f"contract={phase2.get('contract_version') or '-'} | "
            f"select={phase2.get('selection_mode') or '-'} | "
            f"metric={phase2.get('metric_semantics', {}).get('metric_name') or '-'} | "
            f"promoted={phase2.get('promoted_model_count', 0)} | "
            f"families={phase2.get('required_model_count', 0)} | "
            f"subdetectors={sub_detector_count}"
        )
    if phase3.get("available"):
        lines.append(
            "Phase 3 provenance: "
            f"insight=yes | top_risks={phase3.get('top_risk_count', 0)} | "
            f"significant_tx={phase3.get('significant_tx_count', 0)} | "
            f"case_narratives={phase3.get('case_narrative_count', 0)} | "
            f"phase2_linked={'yes' if phase3.get('phase2_linked') else 'no'}"
        )
    return lines
