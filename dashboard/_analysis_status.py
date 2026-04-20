from __future__ import annotations

import streamlit as st


def get_batch_analysis_status(result) -> str:
    statuses = list(getattr(result, "detector_statuses", []) or [])
    if any(row.get("run_status") == "failed" for row in statuses):
        return "failed"
    if any(row.get("run_status") == "degraded" for row in statuses):
        return "degraded"
    if any(row.get("run_status") == "executed" for row in statuses):
        return "executed"
    return "unknown"


def format_phase2_provenance(result) -> str | None:
    report_id = getattr(result, "phase2_training_report_id", None)
    inference_mode = getattr(result, "phase2_inference_mode", None)
    contract = getattr(result, "phase2_inference_contract", None) or {}
    selection_mode = contract.get("selection_mode")

    parts: list[str] = []
    if report_id:
        parts.append(f"train={report_id}")
    if inference_mode:
        parts.append(f"mode={inference_mode}")
    if selection_mode:
        parts.append(f"select={selection_mode}")
    if not parts:
        return None
    return "Phase 2 provenance: " + " | ".join(parts)


def render_batch_status_banner(result) -> None:
    status = get_batch_analysis_status(result)
    warnings = list(getattr(result, "warnings", []) or [])

    if status == "degraded":
        st.warning(
            f"배치 상태: 부분 분석. 일부 detector에 coverage 제한이 있어 경고 {len(warnings)}건과 실행 상세를 함께 확인해야 합니다.",
            icon=":material/warning:",
        )
    elif status == "failed":
        st.error("배치 상태: 실패. detector 실행 상세와 경고를 확인하세요.")
    elif status == "executed":
        st.success("배치 상태: 실행 완료")
    else:
        st.info("배치 상태: 실행 상태 정보 없음")

    provenance = format_phase2_provenance(result)
    if provenance:
        st.caption(provenance)
