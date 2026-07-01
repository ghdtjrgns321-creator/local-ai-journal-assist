from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from dashboard._state import (
    KEY_ACTIVE_RESULT_TAB,
    KEY_LOADED_FROM_DB,
    KEY_PENDING_RESULT_TAB,
    KEY_PHASE2_TRAINING_REPORT_ID,
    PAGE_PHASE1,
    PAGE_PHASE2,
)
from dashboard.components.phase2_family_matrix import (
    ACTIVE_FAMILIES,
    DORMANT_FAMILIES,
    DORMANT_REASONS,
    FAMILY_INTERPRETATIONS,
    FAMILY_METRICS,
)
from dashboard.components.phase2_subdetector_grid import (
    SUB_DETECTORS,
)
from src.detection.constants import get_track_display_label

if TYPE_CHECKING:
    from src.metrics.models import PerformanceReport
    from src.pipeline import PipelineResult
    from src.preprocessing.model_registry import ModelMetadata


def _resolve_active_partition() -> str | None:
    """현재 engagement 의 fiscal_year 를 partition 문자열로 반환.

    Why: Phase 2 추론/요약은 사용자가 회사 화면에서 고른 engagement 의 연도를
    그대로 따라야 한다. fiscal_year 가 없으면 None → inference 서비스가 "전체" 로 처리.
    """
    from dashboard._state import KEY_COMPANY_CONTEXT

    ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    fiscal_year = getattr(ctx, "fiscal_year", None)
    if fiscal_year is None:
        return None
    return str(int(fiscal_year))


def render(prep_result, result: PipelineResult | None) -> None:
    st.subheader("Phase2 결과")

    # Why: phase2 는 phase1 batch_id 를 재사용한다. phase1 결과가 없으면 phase2 추론
    #      자체가 의미 없고 데이터 모델도 깨지므로, phase2 탭에서 phase1 분석 시작 버튼만
    #      노출해 사용자를 명확하게 phase1 분석으로 안내한다.
    from dashboard._state import KEY_PHASE1_RESULT

    if st.session_state.get(KEY_PHASE1_RESULT) is None:
        st.info("Phase 1 분석을 먼저 실행해야 Phase 2 추론을 시작할 수 있습니다.")
        if prep_result is None:
            st.caption("준비 데이터가 없습니다. 먼저 데이터 업로드/매핑을 완료하세요.")
        elif st.button("Phase 1 분석 시작", type="primary", key="phase2_gate_run_phase1"):
            from dashboard.tab_phase1 import _start_phase1_analysis

            _start_phase1_analysis()
        return

    snapshot = _load_current_training_snapshot()
    user_state = _determine_phase2_user_state(snapshot, result)

    # Why: partition 은 현재 선택된 engagement 의 fiscal_year 를 따른다.
    #      None 이면 inference service 가 "전체" 로 처리.
    active_partition = _resolve_active_partition()

    if result is None:
        # Why: 학습 → 추론을 한 버튼으로 통합. spinner는 단계별 예상 시간을 표시한다.
        if user_state == "not_trained":
            st.info("저장된 모델 부재: 먼저 Phase 2 학습 리포트를 생성하세요.")
            if st.button("Phase 2 학습 + 추론 실행", type="primary", key="run_phase2_pipeline"):
                _start_phase2_pipeline(partition=active_partition, train=True)
        else:
            st.success("저장된 학습 기준이 있습니다. 추론을 바로 실행하거나 재학습할 수 있습니다.")
            run_inference_clicked = False
            rerun_pipeline_clicked = False
            with st.container(horizontal=True, gap="small"):
                run_inference_clicked = st.button(
                    "저장된 모델로 Phase 2 추론",
                    type="primary",
                    key="run_phase2",
                )
                rerun_pipeline_clicked = st.button(
                    "Phase 2 재학습 + 추론",
                    key="rerun_phase2_pipeline",
                )
            if run_inference_clicked:
                _start_phase2_pipeline(partition=active_partition, train=False)
            if rerun_pipeline_clicked:
                _start_phase2_pipeline(partition=active_partition, train=True)
        return

    # Why: 결과 화면도 현재 engagement 의 fiscal_year 기준으로 partition_summary 를
    #      읽는다. fiscal_year 가 없거나 reference artifact 가 없는 연도면 "전체" 로
    #      자연스럽게 fallback 된다 (_load_phase2_partition_summary).
    partition = active_partition or _DEFAULT_PARTITION
    partition_summary = _load_phase2_partition_summary(partition)

    family_tab_order = (
        "unsupervised",
        "timeseries",
    )
    sub_tabs = st.tabs(
        ["전체 요약", *(_FAMILY_LABELS_KR.get(family, family) for family in family_tab_order)]
    )
    with sub_tabs[0]:
        _render_overview_tab(user_state, snapshot, result, partition, partition_summary)
    for tab, family in zip(sub_tabs[1:], family_tab_order, strict=True):
        with tab:
            _render_phase2_family_tab(snapshot, partition, partition_summary, family)


# ── partition 기본값 ─────────────────────────────────────────
# Why: 결과 화면에서 partition selector 는 노출하지 않는다. 실행 partition 은
#      현재 선택된 engagement 의 fiscal_year 로 결정되고, 결과 화면은 그 partition
#      에 맞춰 summary 를 읽는다. fiscal_year 가 없으면 "전체" 로 fallback.
_DEFAULT_PARTITION = "전체"
_PARTITION_OPTIONS = ("2022", "2023", "2024", "전체")


# ── sub-tab placeholders (B/C/D/E 단계에서 채움) ───────────────


def _render_overview_tab(
    user_state: str,
    snapshot: dict | None,
    result: PipelineResult,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """① 전체 요약 — 분석 영역 중심 감사 관점 요약.

    Why: 감사인이 결과 첫 화면에서 필요한 것은 실행 계약 상태가 아니라 "어떤 분석
         분석 영역이 무엇을 보며, 이번 데이터에서 어떤 관점이 반응했는지"다. 내부
         모델 수치와 case-overlay 상태는 요약/분석 영역 탭의 보조 정보로 두고,
         전체 요약은 분석 영역 해석과 현재 반응도에 집중한다.
    """
    del user_state, result, partition

    st.markdown(_PHASE2_FAMILY_OVERVIEW_CSS, unsafe_allow_html=True)

    st.markdown("#### 1. PHASE 2 실행 요약")

    # P3: Phase 1 case basis 분류 상태가 canonical 이 아니면 fallback / unavailable
    #     사유를 1 줄 caption 으로 노출. canonical_* 은 메시지 없음.
    _render_phase1_case_basis_caption()
    # P4: DB load / inference mode / partition fallback / context 4 axis 진단 caption.
    _render_phase2_status_captions()
    # P7: family detector 실행 결과 진단 — 어떤 family 가 executed/skipped/failed 인지
    #      한 줄 caption 으로 즉시 노출. 활성 분석 영역 0/1 같은 비정상 결과의 원인을
    #      별도 내부 진단 화면 없이도 확인할 수 있게 한다.
    _render_phase2_family_dispatch_caption()
    # R-H2: 통합 empty_state 를 한 번 계산해 ribbon / distribution / actions 가 모두
    #       동일 객체를 사용하도록 한다. 자체 분류 시 phase1_basis_unavailable /
    #       placeholder / partition_mismatch 같은 상위 원인이 KPI/차트에서 누락된다.
    empty_state = _current_phase2_empty_state()

    # P5-4: empty state 별 next action 버튼 (있는 경우만).
    _render_phase2_empty_state_actions(empty_state)

    # P6-3: 분석 영역 데이터의 source (회사 scoped vs 정적 reference preview) 명시.
    _render_phase2_signal_source_caption(partition_summary)

    _render_phase2_summary_ribbon(partition_summary, empty_state=empty_state)

    _render_phase2_active_distribution(partition_summary, empty_state=empty_state)

    overlays = _resolve_phase2_overlays_from_state()
    all_families = _build_all_family_summary(partition_summary, snapshot, overlays=overlays)
    if all_families:
        st.markdown("#### 2. 분석 영역 요약")
        _render_phase2_family_summary_card(all_families)


# ── Phase 2 empty-state resolver (P5) ──────────────────────────


@dataclass(frozen=True)
class Phase2EmptyState:
    """전체 요약 / case-level 상세 빈 상태 표시 결정.

    Attributes:
        state_id: 분류 (phase2_not_run / phase1_basis_unavailable /
            overlay_missing / valid_no_hit / available).
        severity: streamlit 알림 톤 (info / warning / error / caption).
        title: 안내 1줄 (필수).
        body: 부가 설명 (1~2 문장).
        next_action_label: 사용자 행동 안내 (없으면 None).
        show_charts: 활성 분석 분포 차트를 그릴지.
        show_lanes: case-level 상세 표를 그릴지.
    """

    state_id: str
    severity: str
    title: str
    body: str
    next_action_label: str | None
    show_charts: bool
    show_lanes: bool


_PHASE2_STATE_AVAILABLE = "available"
_PHASE2_STATE_NOT_RUN = "phase2_not_run"
_PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE = "phase1_basis_unavailable"
_PHASE2_STATE_OVERLAY_MISSING = "overlay_missing"
_PHASE2_STATE_VALID_NO_HIT = "valid_no_hit"


def _resolve_phase2_empty_state(
    *,
    phase2_result,
    overlays: list[dict],
    phase1_basis_status: str | None,
    overlay_status: str | None,
) -> Phase2EmptyState:
    """현재 입력으로 표시 결정 반환.

    Why: KPI 카드 / Active Distribution 차트 / case-level 상세가 같은 분기를 반복하지 않게
    한 곳에서 분류한다. 표시 레이어 전용 — service 로직과 분리.

    분기 우선순위:
        1. phase2_result is None         → phase2_not_run
        2. phase1_basis == unavailable    → phase1_basis_unavailable
        3. overlay_status 가 store-level 진단 (missing/mismatch/error/…) → overlay_missing
        4. overlays 존재하지만 hit 없음   → valid_no_hit (정상 결과)
        5. 그 외                           → available
    """
    if phase2_result is None:
        return Phase2EmptyState(
            state_id=_PHASE2_STATE_NOT_RUN,
            severity="info",
            title="Phase 2 추론 결과가 없습니다.",
            body=(
                "저장된 모델로 추론하거나 학습 + 추론을 실행하세요. "
                "추론 완료 후 케이스별 추가 신호를 볼 수 있습니다."
            ),
            next_action_label="Phase 2 추론 실행",
            show_charts=False,
            show_lanes=False,
        )

    if (phase1_basis_status or "") == "unavailable":
        return Phase2EmptyState(
            state_id=_PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE,
            severity="warning",
            title="Phase 1 검토 케이스가 없습니다.",
            body=(
                "Phase 2 case overlay 는 Phase 1 케이스를 기준으로 만들어집니다. "
                "Phase 1 분석을 먼저 실행하면 Phase 2 결과가 케이스 단위로 정렬됩니다."
            ),
            next_action_label="Phase 1 결과 탭으로 이동",
            show_charts=False,
            show_lanes=False,
        )

    # Why: "placeholder" 도 overlay 가 case-level attribution 까지 채워지지 않은 상태로,
    # KPI 를 "0건" 으로 표시하면 D8 (valid_no_hit) 정상 결과와 구분되지 않는다. P2 의
    # store-level 진단과 같은 분기 (overlay_missing) 로 묶어 사용자가 재추론을 안내받게 한다.
    # "partition_mismatch" 는 별도 분기 (선택 연도 결과 미일치) 라 caption 으로만 노출하고
    # overlay_missing 으로 묶지 않는다 — 자세한 사유는 _overlay_status_message 가 담는다.
    overlay_problem_statuses = {
        "missing",
        "placeholder",
        "schema_mismatch",
        "batch_id_mismatch",
        "training_report_mismatch",
        "invalid_payload",
        "parse_error",
        "unsafe_batch_id",
        "ctx_missing",
    }
    if (overlay_status or "") in overlay_problem_statuses:
        return Phase2EmptyState(
            state_id=_PHASE2_STATE_OVERLAY_MISSING,
            severity="warning",
            title="Phase 2 overlay 를 표시할 수 없습니다.",
            body=(
                "overlay 파일이 없거나 case-level attribution 이 채워지지 않았습니다. "
                "사유는 위 진단 메시지를 참조하세요."
            ),
            next_action_label="Phase 2 재추론",
            show_charts=True,
            show_lanes=False,
        )

    has_overlays = bool(overlays)
    has_any_hit = has_overlays and any(
        overlay.get("top_family")
        or overlay.get("max_evidence_tier")
        or overlay.get("family_contributions")
        for overlay in overlays
    )
    if has_overlays and not has_any_hit:
        # R-M1: valid_no_hit 은 Phase 2 에 표시할 적중 case 가 없는 상태다.
        # show_lanes=True 로 두고 fallback 표를 띄우지 않을 거면 사용자에게
        # 잘못된 기대를 준다. Phase 1 결과 탭으로 안내하는
        # 것이 정합. 따라서 show_lanes=False + next_action_label 도 일치.
        return Phase2EmptyState(
            state_id=_PHASE2_STATE_VALID_NO_HIT,
            severity="info",
            title="Phase 2 가 Phase 1 케이스에 추가 적중 신호를 부여하지 않았습니다.",
            body=(
                "정상 분석 결과입니다. Phase 1 결과 탭의 우선순위 기준으로 검토를 "
                "계속하세요. Phase 2 재실행은 필요하지 않습니다."
            ),
            next_action_label="Phase 1 결과 탭에서 계속 검토",
            show_charts=True,
            show_lanes=False,
        )

    return Phase2EmptyState(
        state_id=_PHASE2_STATE_AVAILABLE,
        severity="info",
        title="",
        body="",
        next_action_label=None,
        show_charts=True,
        show_lanes=True,
    )


def _current_phase2_empty_state() -> Phase2EmptyState:
    """tab_phase2 내부에서 호출하는 wrapper — session_state 에서 입력 모음."""
    from dashboard._state import KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    overlays = _resolve_phase2_overlays_from_state()
    partition = _DEFAULT_PARTITION
    _overlay_list, overlay_status = _resolve_display_overlays(phase2_result, partition)
    del _overlay_list
    phase1_basis_status = str(getattr(phase2_result, "phase1_case_basis_status", "") or "") or None
    return _resolve_phase2_empty_state(
        phase2_result=phase2_result,
        overlays=overlays,
        phase1_basis_status=phase1_basis_status,
        overlay_status=overlay_status,
    )


# ── Phase 1 case basis caption (P3) ────────────────────────────


# Why: ``_inherit_phase1_case_result`` 가 attach 하는 status 별 한국어 1줄 안내.
#      canonical_* 은 정상 상태이므로 화면에는 노출하지 않는다. 그 외에는 사유 +
#      next action 을 한 문장으로.
#      P5 본격 UX 개편 전, 가장 임팩트 큰 fallback / unavailable 만 경고 톤으로 노출한다.
_PHASE1_CASE_BASIS_CAPTIONS: dict[str, tuple[str, str]] = {
    # status: (streamlit caption type "silent" | "warning" | "error", message)
    "canonical_in_memory": ("silent", ""),
    "canonical_artifact": ("silent", ""),
    "fallback_redetect": (
        "warning",
        "저장된 Phase 1 케이스를 읽지 못해 Phase 2 재생성 케이스 기준으로 표시합니다. "
        "Phase 1 분석을 다시 실행하면 정렬됩니다.",
    ),
    "metadata_only": (
        "warning",
        "Phase 1 메타데이터만 있고 케이스 본체가 없어 Phase 2 case overlay 가 정상 "
        "생성되지 않을 수 있습니다. Phase 1 분석을 다시 실행하세요.",
    ),
    "artifact_error": (
        "error",
        "Phase 1 case artifact 로드에 실패했습니다. Phase 1 분석을 다시 실행하거나 "
        "artifact 파일을 확인하세요.",
    ),
    "unavailable": (
        "warning",
        "Phase 1 검토 케이스가 없어 Phase 2 case overlay 를 만들 수 없습니다. "
        "Phase 1 분석을 먼저 실행하세요.",
    ),
}


# ── P4 status axes (DB load / inference mode / partition / context) ────


# Why: 4 independent status axis 각각 (severity, 한국어 message) 매핑.
#      매핑이 비어있으면 silent (caption 미노출). 새 status 추가 시 여기 갱신.
_PHASE2_DB_LOAD_CAPTIONS: dict[str, tuple[str, str]] = {
    # "saved": silent — 정상 동작
    "skipped_no_conn": (
        "caption",
        "DB 연결 없이 추론을 실행했습니다. 분석 결과는 메모리에만 보존되며 "
        "새로고침 후 사라질 수 있습니다.",
    ),
    "skipped_no_load_result": (
        "caption",
        "Phase 2 메타데이터를 DB 에 기록하지 않았습니다 (이전 batch 산출물 없음).",
    ),
    "failed": (
        "warning",
        "Phase 2 분석은 완료됐지만 DB 메타데이터 저장이 일부 실패했습니다. "
        "현재 화면은 세션 결과 기준이며, 새로고침 시 복원이 제한됩니다.",
    ),
}

_PHASE2_INFERENCE_MODE_CAPTIONS: dict[str, tuple[str, str]] = {
    # "training_contract": silent — 정상 동작
    "untrained_contract_only": (
        "warning",
        "저장된 학습 기준 없이 기본 추론 기준으로 Phase 2 를 실행했습니다. "
        "정확한 결과를 위해 Phase 2 학습을 먼저 실행하세요.",
    ),
    "cold_start_bootstrap": (
        "warning",
        "임시 cold-start 기준으로 추론했습니다. Phase 2 학습 완료 후 재추론하세요.",
    ),
}

_PHASE2_PARTITION_FALLBACK_CAPTIONS: dict[str, str] = {
    "selected_year_zero_rows": ("선택 연도에 데이터가 없어 전체 데이터로 Phase 2 를 실행했습니다."),
}

_PHASE2_CONTEXT_CAPTIONS: dict[str, tuple[str, str]] = {
    # "company_context": silent — 정상 동작
    "missing_context": (
        "warning",
        "회사/engagement 컨텍스트가 없어 Phase 2 결과가 메모리에만 저장됩니다. "
        "새로고침 시 복원되지 않습니다.",
    ),
    "missing_db_path": (
        "warning",
        "회사 컨텍스트는 있지만 DB 경로가 비어 있습니다. overlay 영속화가 제한됩니다.",
    ),
}


def _render_phase2_status_captions() -> None:
    """4 axis status caption 을 일관 순서로 노출.

    순서: DB load → inference mode → partition fallback → context.
    `_render_overview_tab` 의 ``del result`` 정책 유지를 위해 session_state 에서
    KEY_PHASE2_RESULT 를 직접 read.
    """
    from dashboard._state import KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    if phase2_result is None:
        return

    _emit_status_caption(
        _PHASE2_DB_LOAD_CAPTIONS,
        getattr(phase2_result, "phase2_db_load_status", None),
    )
    _emit_status_caption(
        _PHASE2_INFERENCE_MODE_CAPTIONS,
        getattr(phase2_result, "phase2_inference_mode", None),
    )
    fallback_reason = getattr(phase2_result, "phase2_partition_fallback_reason", None)
    if fallback_reason:
        text = _PHASE2_PARTITION_FALLBACK_CAPTIONS.get(
            str(fallback_reason),
            f"선택 연도가 변경되어 전체 데이터로 실행되었습니다 (사유: {fallback_reason}).",
        )
        requested = getattr(phase2_result, "phase2_requested_partition", "?")
        executed = getattr(phase2_result, "phase2_executed_partition", "?")
        st.warning(f"{text} (요청: {requested} → 실행: {executed})")
    _emit_status_caption(
        _PHASE2_CONTEXT_CAPTIONS,
        getattr(phase2_result, "phase2_context_status", None),
    )


_PHASE2_FAMILY_TRACK_LABELS: dict[str, str] = {
    "ml_unsupervised": "VAE Deep Learning",
    "timeseries": "시점",
}


def _render_phase2_family_dispatch_caption() -> None:
    """내부 family detector 실행 진단은 사용자 화면에 노출하지 않는다."""
    return


def _emit_status_caption(
    mapping: dict[str, tuple[str, str]],
    status_value,
) -> None:
    """status → (severity, message) 매핑에서 일치 항목이 있으면 표시."""
    if not status_value:
        return
    entry = mapping.get(str(status_value))
    if entry is None:
        return
    severity, message = entry
    if severity == "silent":
        return
    if severity == "warning":
        st.warning(message)
    elif severity == "error":
        st.error(message)
    elif severity == "info":
        st.info(message)
    else:
        st.caption(message)


def _render_phase2_empty_state_actions(
    empty_state: Phase2EmptyState | None = None,
) -> None:
    """state 별 next action 버튼.

    Why: P3 caption + P4 status 메시지가 사유를 알려주지만, 사용자가 다음 행동을
    바로 취할 수 있도록 탭 이동/안내 버튼을 노출. 기존 추론 버튼이 이미 위쪽에
    있는 ``phase2_not_run`` / ``overlay_missing`` 분기는 중복 회피로 버튼 생략.

    R-H2: 호출자가 empty_state 를 전달하면 ribbon/distribution 과 동일 객체 사용.
    """
    if empty_state is None:
        empty_state = _current_phase2_empty_state()
    if empty_state.state_id == _PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE:
        if st.button(
            "Phase 1 결과 탭으로 이동",
            key="p5_action_goto_phase1",
            type="primary",
        ):
            st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
            st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE1
            st.rerun()
    elif empty_state.state_id == _PHASE2_STATE_VALID_NO_HIT:
        # R-M1: valid_no_hit 은 Phase 2 적중 case 없는 상태라 표시할 fallback 표가 없다.
        # Phase 1 결과 탭으로 안내해야 사용자가 헛걸음하지 않는다.
        if st.button(
            "Phase 1 결과 탭에서 계속 검토",
            key="p5_action_goto_phase1_no_hit",
        ):
            st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
            st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE1
            st.rerun()
        st.caption("Phase 2 가 추가 적중을 잡지 못한 정상 결과입니다. Phase 2 재추론은 불필요.")


def _render_phase1_case_basis_caption() -> None:
    """phase2_result.phase1_case_basis_status 에 따라 1줄 caption 표시.

    canonical 분류는 silent (caption 생략 가능). fallback / error / unavailable 은 사유와
    next action 을 강조 톤으로 노출.

    Why: 화면 별 코드 중복을 피하기 위해 session_state 에서 KEY_PHASE2_RESULT 를 직접
    read. _render_overview_tab 의 ``del result`` 정책을 깨지 않는다.
    """
    from dashboard._state import KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    if phase2_result is None:
        return
    status = str(getattr(phase2_result, "phase1_case_basis_status", "") or "")
    entry = _PHASE1_CASE_BASIS_CAPTIONS.get(status)
    if entry is None:
        return
    severity, message = entry
    if severity == "warning":
        st.warning(message)
    elif severity == "error":
        st.error(message)
    else:
        # canonical_* 은 정보성 — UI 가 과도하게 시끄러워지지 않게 caption 으로 작게.
        st.caption(message)


# ── PHASE2 실행 요약 KPI 리본 (Phase1 패턴 차용) ───────────────


_PHASE2_TOTAL_FAMILY_COUNT = 9

# 표시용 lane 총 수: 활성 5 + 대기 4. "활성 Lane" KPI 는 몇 개 lane 이 깨어 있는지를
# 전체 분석 영역 9개 기준으로 보여준다.
_PHASE2_TOTAL_LANE_COUNT = len(ACTIVE_FAMILIES) + len(DORMANT_FAMILIES)


def _classify_ribbon_state_from_overlays(overlays: list[dict]) -> Phase2EmptyState:
    """ribbon 전용 분류 — overlays 만 보고 available / valid_no_hit / overlay_missing.

    Why: ribbon 은 ``result is None`` 분기 이후 호출되므로 phase2_not_run 분류는
    여기서 발생하지 않는다. resolver 풀버전(_resolve_phase2_empty_state) 은 phase2
    탭 전체에서 사용되며 ribbon 도 호출자가 명시 전달하면 그것을 사용한다.
    """
    if not overlays:
        return _resolve_phase2_empty_state(
            phase2_result=object(),
            overlays=[],
            phase1_basis_status=None,
            overlay_status="missing",
        )
    return _resolve_phase2_empty_state(
        phase2_result=object(),
        overlays=overlays,
        phase1_basis_status=None,
        overlay_status=None,
    )


def _build_kpi_value_and_sub(
    *,
    empty_state: Phase2EmptyState,
    value: int,
    denom: int,
    available_sub: str,
    no_hit_sub: str,
    missing_sub_template: str,
    sub_style: str,
) -> tuple[str, str]:
    """state_id 별 KPI value text / sub html 분기.

    - ``available``: 정상 N건 + 비율/맥락
    - ``valid_no_hit``: 0건 + "추가 적중 없음" (실패 아님)
    - 기타 (missing / not_run / basis_unavailable): "-" + 사유 라벨
    """
    del denom  # 호출자가 미리 available_sub 에 비율을 계산해 넣었으므로 미사용.
    if empty_state.state_id == _PHASE2_STATE_AVAILABLE:
        return f"{value:,}", available_sub
    if empty_state.state_id == _PHASE2_STATE_VALID_NO_HIT:
        return "0", no_hit_sub
    if empty_state.state_id == _PHASE2_STATE_NOT_RUN:
        label = "추론 후 표시"
    elif empty_state.state_id == _PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE:
        label = "Phase 1 케이스 필요"
    elif empty_state.state_id == _PHASE2_STATE_OVERLAY_MISSING:
        label = "overlay 미생성"
    else:
        label = "확인 필요"
    del sub_style  # 호출자가 template 에 미리 적용.
    return "-", missing_sub_template.format(label=label)


# P6-3: KPI sub 에 붙는 source 라벨. 회사 scoped 결과는 정상 (빈 라벨),
#       결과 없음만 명시.
_PHASE2_SOURCE_KPI_LABELS: dict[str, str] = {
    "runtime_company_scoped": "",
    "missing_reference": " · 결과 없음",
}


# P6-4: 차트/지도 헤더 옆에 붙는 source suffix. KPI sub 라벨과 다르게 짧게.
_PHASE2_SOURCE_HEADER_SUFFIX: dict[str, str] = {
    "runtime_company_scoped": "",
    "missing_reference": " (결과 없음)",
}


def _phase2_signal_source_suffix(partition_summary: dict | None) -> str:
    """차트/지도 헤더 뒤에 붙일 source suffix. 회사 scoped 면 빈 문자열."""
    status, _ = _resolve_phase2_signal_source_status(partition_summary)
    return _PHASE2_SOURCE_HEADER_SUFFIX.get(status, "")


def _render_phase2_summary_ribbon(
    partition_summary: dict | None,
    *,
    empty_state: Phase2EmptyState | None = None,
) -> None:
    """PHASE 2 실행 요약 — PHASE2 native case 중심 4 KPI 카드 flex 배너.

    카드 4 (사용자 결정 2026-05-28, native case 기준):
      1) 분석 대상 케이스    — Phase2CaseSet 의 5 family case 총 수
      2) Phase 2 신호 케이스 — evidence_tier ∈ {strong, moderate} 인 case 수 + 비율
      3) 활성 Lane          — case > 0 인 active family 수 / 9 (active 5 + dormant 4)
      4) 최상위 Lane        — case 수 최대 family 한국어 라벨 + 건수 (VAE 제외)

    Why: 기존 KPI 는 PHASE1 case 에 PHASE2 가 attach 한 overlay 의 카운트였다.
         사용자 요청에 따라 PHASE2 가 별도로 산출한 native case (Phase2CaseSet) 의
         5 family 집계로 전환. overlay 는 PHASE1 case 1:1 mapping 이라 native
         case 와 정의가 다르다.
    """
    from dashboard.components.phase2_native_case_metrics import (
        count_active_native_families,
        count_native_cases_signaled,
        count_native_cases_total,
        resolve_phase2_case_set_from_state,
        top_native_case_family,
    )

    case_set = resolve_phase2_case_set_from_state()
    overlays = _resolve_phase2_overlays_from_state()  # empty_state 분기 호환
    if empty_state is None:
        empty_state = _classify_ribbon_state_from_overlays(overlays)

    # 카드 ① 분석 대상 케이스 — native case set 의 5 family 합산
    base_case_count = count_native_cases_total(case_set)

    # 카드 ② Phase 2 신호 케이스 — evidence_tier ∈ {strong, moderate}
    signaled_count = count_native_cases_signaled(case_set)
    signal_ratio = (signaled_count / base_case_count) if base_case_count else 0.0

    # 카드 ③ 활성 Lane — case > 0 인 active family 수 / 9 (사용자 결정: dormant 4 유지)
    active_family_count = count_active_native_families(case_set)

    # 카드 ④ 최상위 Lane — case 수 최대 family (VAE 제외)
    top_family = top_native_case_family(case_set)
    if top_family is None:
        top_family_kr = ""
        top_family_count = 0
    else:
        family_key, top_family_count = top_family
        top_family_kr = _FAMILY_LABELS_KR.get(family_key, family_key)

    sub_style = "color:#9CA3AF; font-size:0.72rem; margin-top:3px;"
    block_style = "text-align:center; flex:1; padding:0 1rem; border-right:1px solid #E5E7EB;"
    last_block_style = "text-align:center; flex:1; padding:0 1rem;"
    label_style = (
        "color:#6B7280; font-size:0.78rem; margin-bottom:6px; "
        "font-weight:500; letter-spacing:0.01em;"
    )
    value_base = "font-size:1.7rem; font-weight:700; letter-spacing:-0.02em; line-height:1.2;"
    unit_style = "font-size:0.95rem; font-weight:500; color:#6B7280;"

    base_value_text, base_sub_html = _build_kpi_value_and_sub(
        empty_state=empty_state,
        value=base_case_count,
        denom=base_case_count,
        available_sub=f"<div style='{sub_style}'>Phase 2 가 분석한 case 모집단</div>",
        no_hit_sub=f"<div style='{sub_style}'>분석할 case 가 없습니다.</div>",
        missing_sub_template=f"<div style='{sub_style}'>{{label}}</div>",
        sub_style=sub_style,
    )
    signaled_value_text, signaled_sub_html = _build_kpi_value_and_sub(
        empty_state=empty_state,
        value=signaled_count,
        denom=base_case_count,
        available_sub=(
            f"<div style='{sub_style}'>전체 case 의 {signal_ratio:.1%}</div>"
            if base_case_count
            else f"<div style='{sub_style}'>Phase 2 신호가 있는 case 수</div>"
        ),
        no_hit_sub=f"<div style='{sub_style}'>추가 신호 없음 (정상 결과)</div>",
        missing_sub_template=f"<div style='{sub_style}'>{{label}}</div>",
        sub_style=sub_style,
    )

    source_status, _source_message = _resolve_phase2_signal_source_status(partition_summary)
    source_label = _PHASE2_SOURCE_KPI_LABELS.get(source_status, "")
    active_source_text = source_label.strip(" ·")
    active_sub_html = (
        f"<div style='{sub_style}'>{active_source_text}</div>" if active_source_text else ""
    )

    if top_family_kr:
        if top_family_count:
            top_value_text = f"{top_family_kr} ({top_family_count:,}건)"
        else:
            top_value_text = top_family_kr
        top_sub_parts = [part for part in (source_label.strip(" ·"),) if part]
        top_sub_html = (
            f"<div style='{sub_style}'>{' · '.join(top_sub_parts)}</div>" if top_sub_parts else ""
        )
    else:
        top_value_text = "-"
        top_sub_html = f"<div style='{sub_style}'>신호가 잡힌 lane 이 없습니다.{source_label}</div>"

    top_value_style = (
        "font-size:1.05rem; font-weight:700; letter-spacing:-0.02em; "
        "line-height:1.3; color:#111827;"
    )

    ribbon_html = f"""
<div style="display:flex; justify-content:space-around; align-items:center;
            background:#F9FAFB; padding:0.6rem 1rem;
            border-radius:12px; border:1px solid #F3F4F6;
            box-shadow:0 1px 2px rgba(15,23,42,0.04);
            margin:0.25rem 0 1rem;">
    <div style="{block_style}">
        <div style="{label_style}">분석 대상 케이스</div>
        <div style="color:#111827; {value_base}">
            {base_value_text} <span style="{unit_style}">건</span>
        </div>
        {base_sub_html}
    </div>
    <div style="{block_style}">
        <div style="{label_style}"
             title="자체 q95 threshold 이상 진입한 family 가 1개 이상인 case 수">
            Phase 2 신호 케이스
        </div>
        <div style="color:#EA580C; {value_base}">
            {signaled_value_text} <span style="{unit_style}">건</span>
        </div>
        {signaled_sub_html}
    </div>
    <div style="{block_style}">
        <div style="{label_style}">활성 Lane</div>
        <div style="color:#111827; {value_base}">
            {active_family_count}
            <span style="{unit_style}">/ {_PHASE2_TOTAL_LANE_COUNT} 개</span>
        </div>
        {active_sub_html}
    </div>
    <div style="{last_block_style}">
        <div style="{label_style}">최상위 Lane</div>
        <div style="{top_value_style}">{top_value_text}</div>
        {top_sub_html}
    </div>
</div>
"""
    ribbon_html = "\n".join(line.strip() for line in ribbon_html.splitlines() if line.strip())
    st.markdown(ribbon_html, unsafe_allow_html=True)


def _resolve_phase1_case_count_from_state() -> int:
    """session_state phase1_result 에서 case 총 개수 추출."""
    from dashboard._state import KEY_PHASE1_RESULT
    from src.export.phase1_case_view import resolve_phase1_case_result

    pr = st.session_state.get(KEY_PHASE1_RESULT)
    if pr is None:
        return 0
    case_result = resolve_phase1_case_result(pr)
    if case_result is None:
        return int(getattr(pr, "phase1_case_count", 0) or 0)
    return len(case_result.cases)


def _resolve_top_active_family(
    partition_summary: dict | None,
    *,
    overlays: list[dict] | None = None,
) -> tuple[str, str, int]:
    """nonzero hit 가 가장 큰 active lane 의 한국어 라벨/힌트/건수 반환.

    VAE/unsupervised 는 별도 분포 패널에서 다루므로 '최상위 Lane' 후보에서 제외한다.
    모든 case 에 VAE 점수가 매겨져 항상 최상위로 잡혀 다른 lane 비교가 무의미해진다.
    """
    case_counts = {
        family: count
        for family, count in _family_case_contribution_counts(overlays).items()
        if family != "unsupervised"
    }
    if any(case_counts.values()):
        best_family, best_count = max(case_counts.items(), key=lambda item: item[1])
        return (
            _FAMILY_LABELS_KR.get(best_family, best_family),
            _FAMILY_HINT_KR.get(best_family, ""),
            best_count,
        )

    if not partition_summary:
        return "", "", 0
    families = partition_summary.get("families") or {}
    best_family: str | None = None
    best_count = 0
    for family in ACTIVE_FAMILIES:
        if family == "unsupervised":
            continue
        payload = families.get(family) or {}
        if not isinstance(payload, dict):
            continue
        distribution = payload.get("score_distribution") or {}
        count = int(distribution.get("nonzero_count") or 0)
        if count > best_count:
            best_count = count
            best_family = family
    if best_family is None:
        return "", "", 0
    return (
        _FAMILY_LABELS_KR.get(best_family, best_family),
        _FAMILY_HINT_KR.get(best_family, ""),
        best_count,
    )


# ── 활성 분석 분포 섹션 (lane × evidence_tier matrix + family hit bar) ──


def _render_phase2_active_distribution(
    partition_summary: dict | None,
    *,
    empty_state: Phase2EmptyState | None = None,
) -> None:
    """카드 밑 활성 분석 분포 — lane matrix + 가로 막대 2열.

    좌: Phase 2 lane × evidence_tier case-family contribution matrix.
    우: Phase 2 family 별 case-family contribution hit 수 (중복 포함).

    Why: state_id 가 ``available`` 또는 ``valid_no_hit`` 일 때만 차트 컨테이너를
    그린다. 그 외(overlay_missing / phase2_not_run / phase1_basis_unavailable)는
    상단 안내가 이미 사유를 노출하므로 차트 자체를 생략해 화면 잡음을 줄인다.

    R-H2: 호출자가 empty_state 를 전달하면 ribbon/actions 와 동일 객체 사용.
    """
    overlays = _resolve_phase2_overlays_from_state()
    if empty_state is None:
        empty_state = _current_phase2_empty_state()
    if empty_state.state_id not in (
        _PHASE2_STATE_AVAILABLE,
        _PHASE2_STATE_VALID_NO_HIT,
    ):
        reason = _PHASE2_DISTRIBUTION_EMPTY_REASONS.get(empty_state.state_id, "표시 불가")
        st.caption(f"활성 분석 분포: {reason}")
        return

    st.markdown(
        "<div style='color:#18181B; font-size:1rem; font-weight:600; "
        "margin:1.5rem 0 0.75rem;'>활성 분석 분포</div>",
        unsafe_allow_html=True,
    )
    # Why: 2x2 그리드. 1행은 rule-based 4 lane 의 tier matrix(좌) + family bar(우).
    #      2행은 VAE 전용 — 본질적 측정 단위(ml_quantile)가 달라 분리한다.
    #      1행 카드는 heatmap/bar (height 380) + 헤더에 맞춰 440.
    #      2행 VAE 카드는 contents 크기에 맞춰 360 (가운데 정렬 효과).
    chart_card_height = 440
    vae_card_height = 360
    row1_left, row1_right = st.columns([1, 1], gap="small")
    with row1_left, st.container(border=True, height=chart_card_height):
        _render_phase2_lane_matrix(overlays, empty_state=empty_state)
    with row1_right, st.container(border=True, height=chart_card_height):
        _render_phase2_family_case_bar(overlays, empty_state=empty_state)

    row2_left, row2_right = st.columns([1, 1], gap="small")
    with row2_left, st.container(border=True, height=vae_card_height):
        _render_phase2_vae_distribution(overlays, empty_state=empty_state)
    with row2_right, st.container(border=True, height=vae_card_height):
        _render_phase2_vae_meta(overlays, empty_state=empty_state)


_PHASE2_DISTRIBUTION_EMPTY_REASONS: dict[str, str] = {
    _PHASE2_STATE_NOT_RUN: "Phase 2 추론 후 표시됩니다.",
    _PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE: "Phase 1 케이스 기준이 있어야 분포를 그릴 수 있습니다.",
    _PHASE2_STATE_OVERLAY_MISSING: "overlay 가 없어 분포를 그릴 수 없습니다.",
}


def _resolve_phase1_case_lookup_from_state() -> dict:
    """session_state phase1_result 에서 case_id → CaseGroupResult lookup."""
    from dashboard._state import KEY_PHASE1_RESULT
    from src.export.phase1_case_view import resolve_phase1_case_result

    pr = st.session_state.get(KEY_PHASE1_RESULT)
    if pr is None:
        return {}
    case_result = resolve_phase1_case_result(pr)
    if case_result is None:
        return {}
    return {str(case.case_id): case for case in case_result.cases}


def _is_phase1_immediate_case(case) -> bool:
    """Phase1 UI 기준으로 즉시검토 case 여부를 판정."""
    from dashboard.phase1_display import display_priority_band_from_score

    band = display_priority_band_from_score(
        getattr(case, "priority_score", None),
        getattr(case, "priority_band", "low"),
    )
    return band == "high"


# Lane matrix 표시용 lane 그룹 — 결정 9 정합으로 active 와 supporting 분리.
# supporting = timeseries (결산·시점 보조 lane).
# Lane matrix 전용 family 그룹. unsupervised(VAE) 는 ml_quantile 단위라 strong/
# moderate/weak 축과 측정 단위가 달라 lane matrix 에서 제외하고 별도 VAE 패널
# (_render_phase2_vae_distribution / meta) 로 분리한다.
_PHASE2_ACTIVE_LANES: tuple[str, ...] = ()
_PHASE2_SUPPORTING_LANES: tuple[str, ...] = ("timeseries",)


def _lane_tier_counts(overlays: list[dict]) -> dict[str, dict[str, int]]:
    """family → evidence tier 카운트 (case-family contribution 단위).

    Why: lane matrix 좌측에 lane × evidence_tier 분포를 그릴 base 데이터. case 가
         여러 lane 에 걸리면 각 lane row 의 tier 카운트에 모두 1 씩 들어간다 (우측
         막대와 같은 case-family contribution 단위).
    """
    # lane matrix 표시용 — unsupervised(VAE) 는 별도 VAE 패널로 분리되므로 제외.
    counts: dict[str, dict[str, int]] = {}
    for family in (*_PHASE2_ACTIVE_LANES, *_PHASE2_SUPPORTING_LANES):
        counts[family] = {"strong": 0, "moderate": 0, "weak": 0, "ml_quantile": 0}
    for overlay in overlays or []:
        for entry in overlay.get("family_contributions") or []:
            family = str(entry.get("family") or "")
            if family not in counts:
                continue
            if not _family_contribution_has_positive_signal(entry):
                continue
            tier = str(entry.get("evidence_tier") or "").strip().lower()
            if tier in counts[family]:
                counts[family][tier] += 1
    return counts


def _render_phase2_lane_matrix(
    overlays: list[dict],
    *,
    empty_state: Phase2EmptyState | None = None,
) -> None:
    """Phase 2 family lane × evidence_tier 매트릭스 (활성 4 + 보조 1 분리).

    각 lane row 는 Strong / Moderate / Weak/Context 셀의 case 카운트를 표시한다.
    timing context 는 결정 9 (PHASE2_TIMESERIES_ROLE_LOCK) 정합으로 보조 lane 섹션에
    분리해 표시하며, strong/moderate 셀은 "-" 로 비워 단독 ranker 가 아닌 점을
    시각적으로 강제한다.
    """
    color_text = "#111827"  # gray-900
    color_text_strong = "#0F172A"  # slate-900
    typography = "Pretendard, Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    # native case 기준으로 전환 (사용자 결정 2026-05-28).
    # ``overlays`` 시그니처는 호환 유지하되 본문은 phase2_case_set 만 사용.
    from dashboard.components.phase2_native_case_metrics import (
        count_native_cases_by_family_tier,
        resolve_phase2_case_set_from_state,
    )

    del overlays
    case_set = resolve_phase2_case_set_from_state()
    tier_counts = count_native_cases_by_family_tier(case_set)
    total_cells = sum(sum(row.values()) for row in tier_counts.values())

    st.markdown(
        f"<div style='font-family:{typography};'>"
        f"<div style='color:{color_text_strong}; font-size:0.875rem; "
        f"font-weight:700; letter-spacing:-0.01em;'>Phase 2 Family Lanes</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    if total_cells == 0:
        state_id = empty_state.state_id if empty_state else _PHASE2_STATE_OVERLAY_MISSING
        if state_id == _PHASE2_STATE_VALID_NO_HIT:
            st.info("분석 완료 — Lane 적중 없음 (정상 결과)")
        else:
            st.info(
                "PHASE2 native case 가 없어 Lane 분포를 표시할 수 없습니다. Phase 2 재추론하세요."
            )
        return

    # X = Lane (좌→우), Y = evidence tier (위→아래: Strong → Weak).
    # ml_quantile 행은 VAE 분리 후 사용처가 없으므로 매트릭스에서 제외.
    import plotly.graph_objects as go

    lanes_order: tuple[str, ...] = (*_PHASE2_ACTIVE_LANES, *_PHASE2_SUPPORTING_LANES)
    tiers_order: tuple[str, ...] = ("strong", "moderate", "weak")
    tier_labels: list[str] = ["Strong", "Moderate", "Weak"]
    _tier_zero: dict[str, int] = {"strong": 0, "moderate": 0, "weak": 0}

    x_labels: list[str] = []
    for family in lanes_order:
        label = _FAMILY_LABELS_KR.get(family, family)
        if family in _PHASE2_SUPPORTING_LANES:
            label = f"{label} (보조)"
        x_labels.append(label)

    z_matrix: list[list[int]] = []
    text_matrix: list[list[str]] = []
    for tier in tiers_order:
        row_z: list[int] = []
        row_text: list[str] = []
        for family in lanes_order:
            counts = tier_counts.get(family, _tier_zero)
            is_supporting = family in _PHASE2_SUPPORTING_LANES
            # 결정 9: 보조 lane (timing) 은 weak 행만 사용 — 나머지 셀은 "-".
            if is_supporting and tier != "weak":
                row_z.append(0)
                row_text.append("-")
                continue
            value = int(counts.get(tier, 0) or 0)
            row_z.append(value)
            row_text.append(f"{value:,}" if value > 0 else "")
        z_matrix.append(row_z)
        text_matrix.append(row_text)

    # Phase 1 stats heatmap 과 동일 설정 (height 320 + Phase1 margin/colorbar).
    heat = go.Figure(
        go.Heatmap(
            z=z_matrix,
            x=x_labels,
            y=tier_labels,
            text=text_matrix,
            texttemplate="%{text}",
            textfont={"size": 12, "family": typography},
            colorscale="Purples",
            hovertemplate="Lane: %{x}<br>Tier: %{y}<br>케이스: %{z:,}<extra></extra>",
            colorbar={"title": "케이스", "thickness": 10, "len": 0.55, "x": 0.92},
        )
    )
    # Plot area 를 카드 가운데로 강제 — xaxis/yaxis domain 명시.
    # plot 가로 = figure 의 12%~80% (좌측 yaxis 라벨 12%, 우측 20% 영역에 colorbar).
    # plot 세로 = figure 의 5%~80% (xaxis 라벨 회전 자리 아래 20%).
    heat.update_layout(
        height=380,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": typography, "color": color_text},
        xaxis_title="",
        yaxis_title="",
    )
    heat.update_xaxes(
        tickangle=-30,
        tickfont={"size": 10},
        domain=[0.12, 0.80],
    )
    heat.update_yaxes(
        tickfont={"size": 11},
        autorange="reversed",
        domain=[0.20, 0.95],
    )
    st.plotly_chart(
        heat,
        width="stretch",
        key="phase2_lane_matrix_heatmap",
        config={"displayModeBar": False},
    )


def _collect_docs_of_cases(case_ids: set[str], case_lookup: dict) -> set[str]:
    """case_id set → case.documents union."""
    docs: set[str] = set()
    for case_id in case_ids:
        case = case_lookup.get(case_id)
        if case is None:
            continue
        for doc in getattr(case, "documents", None) or []:
            doc_id = str(getattr(doc, "document_id", "") or "")
            if doc_id:
                docs.add(doc_id)
    return docs


# VAE 전용 분포 패널 ─────────────────────────────────────────


def _unsupervised_scores_from_overlays(overlays: list[dict] | None) -> list[float]:
    """family_contributions 에서 unsupervised entry 의 raw score 수집 (score > 0)."""
    scores: list[float] = []
    for overlay in overlays or []:
        for entry in overlay.get("family_contributions") or []:
            if str(entry.get("family") or "") != "unsupervised":
                continue
            try:
                value = float(entry.get("score") or 0.0)
            except (TypeError, ValueError):
                continue
            if value > 0.0:
                scores.append(value)
    return scores


def _count_vae_only_q95_discovery(
    overlays: list[dict] | None,
    *,
    score_threshold: float,
) -> int:
    """Phase 1 즉시검토 외 case 중 VAE score ≥ q95 인 case 수.

    Why: PHASE2 의 본질 가치 = Phase 1 룰로 못 잡는 새 anomaly 패턴.
         Phase 1 priority_band 가 "high" 가 아닌데 VAE 가 q95+ 신호를 잡은 case 를
         VAE 단독 발견으로 카운트한다.
    """
    case_lookup = _resolve_phase1_case_lookup_from_state()
    phase1_immediate_ids = {
        str(case_id) for case_id, case in case_lookup.items() if _is_phase1_immediate_case(case)
    }
    vae_q95_ids: set[str] = set()
    for overlay in overlays or []:
        case_id = str(overlay.get("phase1_case_id") or "").strip()
        if not case_id:
            continue
        for entry in overlay.get("family_contributions") or []:
            if str(entry.get("family") or "") != "unsupervised":
                continue
            try:
                value = float(entry.get("score") or 0.0)
            except (TypeError, ValueError):
                continue
            if value >= score_threshold:
                vae_q95_ids.add(case_id)
                break
    return len(vae_q95_ids - phase1_immediate_ids)


def _render_phase2_vae_distribution(
    overlays: list[dict],
    *,
    empty_state: Phase2EmptyState | None = None,
    chart_key: str = "phase2_vae_distribution",
    show_description: bool = True,
) -> None:
    """VAE/Isolation Forest score 분포 히스토그램 + q95 cutoff line."""
    import numpy as np
    import plotly.graph_objects as go

    color_text = "#18181B"
    color_muted = "#71717A"
    typography = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    if show_description:
        st.markdown(
            f"<div style='font-family:{typography};'>"
            f"<div style='color:{color_text}; font-size:0.875rem; font-weight:600;'>"
            "VAE Deep Learning score 분포</div>"
            f"<ul style='color:{color_muted}; font-size:0.74rem; margin:6px 0 0; "
            "padding-left:1.1rem; line-height:1.6;'>"
            "<li><b>VAE</b>(Variational Autoencoder) + <b>Isolation Forest</b> 두 비지도 "
            "ML 모델이 정상 전표 분포를 학습합니다.</li>"
            "<li>각 case 의 <b>statistical outlier score</b> = 정상 분포에서 떨어진 정도.</li>"
            "<li><b>score 가 클수록</b> 정상 분포에서 멀리 떨어진 이상 패턴 case.</li>"
            "<li>점선 <b>q95 cutoff</b>(상위 5%) — 이 위쪽 꼬리가 감사인 우선 검토 후보.</li>"
            "<li>하위 score 영역은 정상 분포에 가까운 case → 검토 우선순위 <b>제외</b>.</li>"
            "</ul>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("##### VAE Deep Learning score 분포")

    # native case 기준 (사용자 결정 2026-05-28).
    from dashboard.components.phase2_native_case_metrics import (
        iter_unsupervised_cases,
        resolve_phase2_case_set_from_state,
    )

    del overlays
    case_set = resolve_phase2_case_set_from_state()
    scores = [
        float(c.anomaly_score)
        for c in iter_unsupervised_cases(case_set)
        if c.anomaly_score is not None and float(c.anomaly_score) > 0.0
    ]
    if not scores:
        state_id = empty_state.state_id if empty_state else _PHASE2_STATE_OVERLAY_MISSING
        if state_id == _PHASE2_STATE_VALID_NO_HIT:
            st.info("분석 완료 — VAE 점수 0 (정상 결과)")
        else:
            st.info("PHASE2 unsupervised native case 가 없어 분포를 표시할 수 없습니다.")
        return

    q95 = float(np.percentile(scores, 95))

    fig = go.Figure(
        go.Histogram(
            x=scores,
            nbinsx=40,
            marker={"color": "#7C3AED", "line": {"width": 0}},
            hovertemplate="score: %{x:.3f}<br>case 수: %{y:,}<extra></extra>",
        )
    )
    fig.add_vline(
        x=q95,
        line={"color": "#DC2626", "width": 1.5, "dash": "dash"},
        annotation_text=f"q95={q95:.3f}",
        annotation_position="top right",
        annotation_font={"size": 11, "color": "#DC2626"},
    )
    fig.update_layout(
        height=240,
        margin={"l": 50, "r": 10, "t": 20, "b": 35},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.05,
        font={"family": typography, "color": color_text},
        xaxis_title="VAE score",
        yaxis_title="case 수",
        showlegend=False,
    )
    fig.update_xaxes(tickfont={"size": 11})
    fig.update_yaxes(tickfont={"size": 11})
    st.plotly_chart(
        fig,
        width="stretch",
        key=chart_key,
        config={"displayModeBar": False},
    )


def _render_phase2_vae_meta(
    overlays: list[dict],
    *,
    empty_state: Phase2EmptyState | None = None,
) -> None:
    """VAE 분포 요약 — Vercel/Linear analytics 스타일 KPI 카드 grid.

    Layout:
      [Row 1] 강조 KPI 2 카드 (q95+ / q99+) — 보라색 액센트 + 큰 숫자 + 작은 sub-text
      [Row 2] 보조 stat 3 카드 (median / max / 신호 비율) — 슬레이트 톤 미니 카드
    """
    import numpy as np

    typography = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    st.markdown(
        f"<div style='font-family:{typography};'>"
        "<div style='color:#0F172A; font-size:0.875rem; font-weight:600;'>"
        "VAE 분포 요약</div>"
        "<div style='color:#64748B; font-size:0.72rem; margin-top:2px;'>"
        "statistical outlier score 분포의 핵심 cutoff 와 분위 통계</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # native case 기준 (사용자 결정 2026-05-28).
    from dashboard.components.phase2_native_case_metrics import (
        iter_unsupervised_cases,
        resolve_phase2_case_set_from_state,
    )

    del overlays
    case_set = resolve_phase2_case_set_from_state()
    unsupervised_cases = tuple(iter_unsupervised_cases(case_set))
    total_cases = len(unsupervised_cases)
    scores = [
        float(c.anomaly_score)
        for c in unsupervised_cases
        if c.anomaly_score is not None and float(c.anomaly_score) > 0.0
    ]
    if not scores:
        state_id = empty_state.state_id if empty_state else _PHASE2_STATE_OVERLAY_MISSING
        if state_id == _PHASE2_STATE_VALID_NO_HIT:
            st.info("분석 완료 — VAE 점수 0 (정상 결과)")
        else:
            st.info("PHASE2 unsupervised native case 가 없어 VAE 메타를 계산할 수 없습니다.")
        return

    arr = np.array(scores, dtype=float)
    q90 = float(np.percentile(arr, 90))
    q95 = float(np.percentile(arr, 95))
    q99 = float(np.percentile(arr, 99))
    high_q90 = int((arr >= q90).sum())
    high_q95 = int((arr >= q95).sum())
    high_q99 = int((arr >= q99).sum())
    # VAE 단독 발견 case — PHASE1 case 와 cross-reference 안 된 unsupervised native case.
    # native 기준: phase1_case_refs 가 비어 있으면 rule 이 못 잡은 신호 (PHASE2 단독 가치).
    vae_only_discovery = sum(1 for c in unsupervised_cases if not c.phase1_case_refs)
    # ── Row 1: 강조 KPI 2 카드 (q95+ / q99+)
    primary_card_css = (
        "background:linear-gradient(135deg, #FAF5FF 0%, #F3E8FF 100%); "
        "border:1px solid #E9D5FF; border-radius:14px; "
        "padding:1rem 1.1rem; position:relative;"
    )

    def _primary_card(label: str, value: int, hint: str, badge: str) -> str:
        return (
            f"<div style='{primary_card_css}'>"
            "<div style='display:flex; justify-content:space-between; "
            "align-items:flex-start; gap:0.5rem;'>"
            "<div style='min-width:0;'>"
            "<div style='color:#7C3AED; font-size:0.65rem; font-weight:700; "
            "letter-spacing:0.08em; text-transform:uppercase;'>"
            f"{label}</div>"
            "<div style='color:#3B0764; font-size:1.85rem; font-weight:800; "
            "line-height:1.1; margin-top:0.4rem; letter-spacing:-0.02em; "
            "font-variant-numeric:tabular-nums;'>"
            f"{value:,}"
            "<span style='font-size:0.85rem; font-weight:500; color:#7C3AED; "
            "margin-left:0.25rem;'>건</span>"
            "</div>"
            "<div style='color:#7C3AED; font-size:0.72rem; margin-top:0.35rem; "
            "opacity:0.85; font-variant-numeric:tabular-nums;'>"
            f"{hint}</div>"
            "</div>"
            "<div style='background:rgba(124,58,237,0.12); border-radius:8px; "
            "padding:0.3rem 0.55rem; white-space:nowrap;'>"
            f"<span style='color:#7C3AED; font-size:0.65rem; font-weight:700; "
            "letter-spacing:0.05em;'>"
            f"{badge}</span>"
            "</div>"
            "</div>"
            "</div>"
        )

    primary_html = (
        "<div style='display:grid; grid-template-columns:1fr 1fr; gap:0.65rem; "
        "margin-top:0.65rem;'>"
        + _primary_card(
            "q95 진입 case",
            high_q95,
            f"score ≥ {q95:.3f} · 전체 {total_cases:,} 건",
            "TOP 5%",
        )
        + _primary_card(
            "q99 진입 case",
            high_q99,
            f"score ≥ {q99:.3f} · 전체 {total_cases:,} 건",
            "TOP 1%",
        )
        + "</div>"
    )

    # ── Row 2: 보조 stat 3 카드 (전체 모집단 / q90+ / 꼬리 평균)
    secondary_card_css = (
        "background:#FAFAFA; border:1px solid #F1F5F9; border-radius:10px; padding:0.7rem 0.85rem;"
    )

    def _secondary_card(label: str, value: str, sub: str = "") -> str:
        sub_html = (
            "<div style='color:#94A3B8; font-size:0.66rem; margin-top:0.15rem; "
            "font-variant-numeric:tabular-nums;'>"
            f"{sub}</div>"
            if sub
            else ""
        )
        return (
            f"<div style='{secondary_card_css}'>"
            "<div style='color:#94A3B8; font-size:0.62rem; font-weight:700; "
            "letter-spacing:0.06em; text-transform:uppercase;'>"
            f"{label}</div>"
            "<div style='color:#0F172A; font-size:1.15rem; font-weight:700; "
            "margin-top:0.25rem; letter-spacing:-0.02em; "
            "font-variant-numeric:tabular-nums;'>"
            f"{value}</div>"
            f"{sub_html}"
            "</div>"
        )

    secondary_html = (
        "<div style='display:grid; grid-template-columns:1fr 1fr 1fr; "
        "gap:0.5rem; margin-top:0.5rem;'>"
        + _secondary_card(
            "전체 분석 case",
            f"{total_cases:,}",
            "VAE 점수 부여된 모집단",
        )
        + _secondary_card(
            "q90 진입 case",
            f"{high_q90:,}",
            f"TOP 10% · score ≥ {q90:.3f}",
        )
        + _secondary_card(
            "VAE 단독 발견",
            f"{vae_only_discovery:,}",
            "Phase 1 즉시검토 외 ∩ VAE q95+",
        )
        + "</div>"
    )

    st.markdown(
        f"<div style='font-family:{typography};'>{primary_html}{secondary_html}</div>",
        unsafe_allow_html=True,
    )


def _render_phase2_family_case_bar(
    overlays: list[dict],
    *,
    empty_state: Phase2EmptyState | None = None,
    chart_key: str = "phase2_family_bar",
) -> None:
    """Phase 2 family 별 적중 case 수 (중복 포함) 가로 막대.

    Why: Phase1 `_render_risk_pie` 우측 막대와 동일한 typography/축/마진 적용.
         색상은 그라데이션이 아닌 family 별 다른 hue 를 700 톤으로 통일해
         튀지 않으면서 영역 구분이 가능하게 한다.
    """
    import plotly.graph_objects as go

    # native case 기준 (사용자 결정 2026-05-28). overlay 인자는 시그니처 호환용.
    from dashboard.components.phase2_native_case_metrics import (
        count_native_cases_by_family,
        count_native_cases_total,
        resolve_phase2_case_set_from_state,
    )

    del overlays
    case_set = resolve_phase2_case_set_from_state()
    counter = dict(count_native_cases_by_family(case_set))
    # VAE/unsupervised 는 별도 VAE 분포 패널로 분리해 노출하므로 막대 차트에서 제외.
    counter.pop("unsupervised", None)

    active_rows = sorted(counter.items(), key=lambda kv: -kv[1])
    dormant_rows = [(family, 0) for family in DORMANT_FAMILIES]
    rows = active_rows + dormant_rows
    # Why: 비활성 family 의 y축 라벨은 HTML span 으로 색을 옅게 깎아 활성 라벨과 시각적
    #      위계를 분리한다. plotly tickfont 은 축 전체 일괄이라 per-tick 색은 HTML 로 처리.
    labels = [
        _FAMILY_LABELS_KR.get(family, family)
        if family in ACTIVE_FAMILIES
        else f"<span style='color:#CBD5E1'>{_FAMILY_LABELS_KR.get(family, family)}</span>"
        for family, _ in rows
    ]
    values = [count for _, count in rows]
    # Why: 활성은 family 별 700 톤, 비활성은 slate-300 으로 채도를 죽이고 opacity 도
    #      낮춰 살짝 투명 처리. 카드의 비활성 row 와 동일한 톤.
    colors = [
        _PHASE2_FAMILY_BAR_COLORS.get(family, "#475569") if family in ACTIVE_FAMILIES else "#CBD5E1"
        for family, _ in rows
    ]
    opacities = [1.0 if family in ACTIVE_FAMILIES else 0.45 for family, _ in rows]

    color_text = "#18181B"
    color_muted = "#71717A"
    typography = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    st.markdown(
        f"<div style='font-family:{typography};'>"
        f"<div style='color:{color_text}; font-size:0.875rem; "
        f"font-weight:600;'>Phase 2 분석 영역별 case-family 적중 수</div>"
        f"<div style='color:{color_muted}; font-size:0.72rem; margin-top:2px;'>"
        "한 case 가 여러 영역에 걸리면 중복 집계 · 전체 case 대비 비율</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    if sum(values) == 0:
        state_id = empty_state.state_id if empty_state else _PHASE2_STATE_OVERLAY_MISSING
        if state_id == _PHASE2_STATE_VALID_NO_HIT:
            st.info("분석 완료 — Phase 2 분석 영역별 적중 없음. 정상 결과입니다.")
        else:
            st.info(
                "PHASE2 native case 가 없어 분석 영역별 적중을 표시할 수 없습니다. "
                "Phase 2 재추론하세요."
            )
        return

    # case_total = native case 총수 (5 family 합). family 별 % 의 분모.
    case_total = count_native_cases_total(case_set)
    bar_pcts = [v / case_total * 100 if case_total else 0.0 for v in values]
    bar_text = [
        f"  {v:,} 건  ·  {p:.1f}%" if family in ACTIVE_FAMILIES else "  현재 미실행중"
        for (family, _), v, p in zip(rows, values, bar_pcts, strict=False)
    ]
    # Why: 활성 row 는 muted gray, 비활성 row 는 slate-300 으로 한 단계 더 옅게.
    bar_text_colors = [
        color_muted if family in ACTIVE_FAMILIES else "#CBD5E1" for family, _ in rows
    ]

    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker={"color": colors, "opacity": opacities, "line": {"width": 0}},
            text=bar_text,
            textposition="outside",
            textfont={"size": 11, "color": bar_text_colors, "family": typography},
            cliponaxis=False,
            hovertemplate="%{y}: %{x:,} case-family hit<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=380,
        margin={"l": 6, "r": 120, "t": 30, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.42,
        font={"family": typography},
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(
        autorange="reversed",
        tickfont={"size": 12, "color": color_text, "family": typography},
        showgrid=False,
        zeroline=False,
        showline=False,
        ticks="",
        automargin=True,
    )
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displayModeBar": False},
        key=chart_key,
    )


# Why: 활성 분포 막대 전용 색상 — 기존 _FAMILY_ACCENT(600 톤, 카드 액센트용)와 별도로
#      막대 차트는 면적이 크므로 700 톤으로 채도를 한 단계 낮춰 본문 톤과 정렬한다.
_PHASE2_FAMILY_BAR_COLORS: dict[str, str] = {
    "timeseries": "#0F766E",  # teal-700
    "unsupervised": "#B45309",  # amber-700
}


# ── compact 헤더 패널 (상단 상태 + 모델 strip 통합) ──────────

_PHASE2_HEADER_CSS = """
<style>
.p2-header-panel { display:flex; flex-wrap:wrap; gap:0.45rem 1.0rem;
                   align-items:center; padding:0.55rem 0.9rem;
                   background:#F9FAFB; border:1px solid #F3F4F6;
                   border-radius:10px; margin:0.25rem 0 0.7rem; }
.p2-chip { display:flex; align-items:baseline; gap:0.35rem; }
.p2-chip-label { color:#6B7280; font-size:0.72rem; font-weight:500;
                 letter-spacing:0.02em; }
.p2-chip-value { color:#111827; font-size:0.85rem; font-weight:600; }
.p2-chip-badge { display:inline-block; padding:1px 8px; border-radius:999px;
                 font-size:0.72rem; font-weight:600; letter-spacing:0.02em; }
.p2-chip-badge-ok   { background:#DCFCE7; color:#15803D; }
.p2-chip-badge-wait { background:#FEF3C7; color:#92400E; }
.p2-chip-badge-off  { background:#F3F4F6; color:#4B5563; }
.p2-empty-card { background:#EFF6FF; border:1px solid #DBEAFE;
                 border-left:4px solid #2563EB; border-radius:10px;
                 padding:0.85rem 1.0rem; color:#1E3A8A; font-size:0.86rem;
                 line-height:1.5; margin:0.25rem 0 0.85rem; }
.p2-empty-hint { display:block; color:#475569; font-size:0.76rem;
                 margin-top:0.45rem; }
.p2-family-mini-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
                       gap:0.45rem; margin:0.2rem 0 0.6rem; }
.p2-family-mini { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px;
                  padding:0.55rem 0.75rem; border-left:3px solid var(--accent,#9CA3AF); }
.p2-family-mini-title { color:#111827; font-size:0.82rem; font-weight:600; }
.p2-family-mini-stat { color:#111827; font-size:1.1rem; font-weight:700;
                       letter-spacing:-0.02em; margin-top:2px; }
.p2-family-mini-unit { color:#6B7280; font-size:0.7rem; font-weight:500; margin-left:2px; }
</style>
"""

_USER_STATE_BADGE: dict[str, tuple[str, str]] = {
    "not_trained": ("학습 전", "off"),
    "training_report_available": ("학습 기준 있음", "wait"),
    "inference_complete": ("추론 완료", "ok"),
}


def _render_phase2_compact_header(
    user_state: str,
    snapshot: dict | None,
    result: PipelineResult | None,
) -> None:
    """상태/학습 리포트/추론 방식/모델 후보·확정/Partition 을 단일 chip 패널로.

    Why: 기존에는 상단 metric strip(상태/리포트/추론 방식/계약 family)과 하단 strip
         (모델 기준/실행 방식/사용 후보/확정 모델)이 중복 정보를 두 번 표시했다.
         단일 chip row 로 압축한다.
    """
    st.markdown(_PHASE2_HEADER_CSS, unsafe_allow_html=True)

    badge_text, badge_kind = _USER_STATE_BADGE.get(user_state, (user_state, "off"))
    contract = (
        getattr(result, "phase2_inference_contract", None)
        if result is not None
        else (snapshot or {}).get("inference_contract")
    ) or {}
    report_id = (
        getattr(result, "phase2_training_report_id", None)
        if result is not None
        else (snapshot or {}).get("report_id")
    )
    inference_mode = _format_inference_mode(
        getattr(result, "phase2_inference_mode", None) if result is not None else None
    )
    promoted_count = len(contract.get("promoted_versions") or {})
    candidate_count = len(contract.get("required_models") or [])

    chips: list[str] = [
        f"<span class='p2-chip'>"
        f"<span class='p2-chip-label'>상태</span>"
        f"<span class='p2-chip-badge p2-chip-badge-{badge_kind}'>{badge_text}</span>"
        f"</span>",
        _chip_html("학습 리포트", str(report_id or "-")),
        _chip_html("추론 방식", inference_mode),
        _chip_html("사용 모델", f"{promoted_count} / {candidate_count}"),
    ]
    st.markdown(
        "<div class='p2-header-panel'>" + "".join(chips) + "</div>",
        unsafe_allow_html=True,
    )


def _chip_html(label: str, value: str) -> str:
    return (
        f"<span class='p2-chip'>"
        f"<span class='p2-chip-label'>{label}</span>"
        f"<span class='p2-chip-value'>{value}</span>"
        f"</span>"
    )


# ── 빈 상태 (overlay missing/placeholder/partition_mismatch) ──


def _render_phase2_empty_overview(
    status: str,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """KPI 카드 대신 안내 + 활성 영역 preview chip 만 표시."""
    msg = _overlay_status_message(status, partition)
    hint = "분석 영역 단위 집계는 상단 family 탭에서 확인할 수 있습니다."
    st.markdown(
        f"<div class='p2-empty-card'>{msg}<span class='p2-empty-hint'>{hint}</span></div>",
        unsafe_allow_html=True,
    )

    chips = _build_family_mini_chips(partition_summary)
    if chips:
        st.markdown("##### 분석 영역별 집계 preview")
        st.markdown(
            "<div class='p2-family-mini-grid'>" + "".join(chips) + "</div>",
            unsafe_allow_html=True,
        )


def _build_family_mini_chips(partition_summary: dict | None) -> list[str]:
    """active family 미니 카드 (overlay 미생성 상태에서도 보여줄 수 있는 집계)."""
    families_payload = (partition_summary or {}).get("families") or {}
    chips: list[str] = []
    for family in ACTIVE_FAMILIES:
        payload = families_payload.get(family) or {}
        accent = _FAMILY_ACCENT.get(family, "#9CA3AF")
        label = _FAMILY_LABELS_KR.get(family, family)
        if family == "unsupervised":
            value = int(payload.get("high_count_q95") or 0)
            stat_label = "검토 후보(q95)"
        else:
            distribution = payload.get("score_distribution") or {}
            value = int(distribution.get("nonzero_count") or 0)
            stat_label = "신호 건수"
        chips.append(
            f"<div class='p2-family-mini' style='--accent:{accent};'>"
            f"<div class='p2-family-mini-title'>{label}</div>"
            f"<div class='p2-family-mini-stat'>{value:,}"
            f"<span class='p2-family-mini-unit'>건 · {stat_label}</span></div>"
            f"</div>"
        )
    return chips


def _build_active_family_focus(partition_summary: dict | None) -> list[dict]:
    """전체 요약 상단에 보여줄 active family 우선순위."""
    rows = [_build_family_overview_row(family, partition_summary) for family in ACTIVE_FAMILIES]
    return sorted(
        rows,
        key=lambda row: (
            int(row["signal_value"]),
            int(row["active_subdetectors"]),
            str(row["family"]),
        ),
        reverse=True,
    )


def _phase2_family_badge_style(signal_value: int) -> tuple[str, str, str]:
    """signal_value → (icon, bg, fg) — Phase1 `_badge_style_for_count` 와 동일 구간."""
    if signal_value <= 0:
        return "✓", "#DCFCE7", "#15803D"
    if signal_value < 100:
        return "⚠", "#FEF3C7", "#A16207"
    if signal_value < 10_000:
        return "⚠", "#FECACA", "#991B1B"
    return "🔥", "#FFE4D6", "#C2410C"


def _family_contribution_has_positive_signal(entry: dict) -> bool:
    """Count family candidate signals used by the overview bar/summary.

    일반 family 는 양수 score/ECDF 를 후보 신호로 본다. review-only 신호처럼
    confirmed score 로 승격하지 않는 신호는 review_only_count 메타가 있을 때만
    후보 신호로 집계한다.
    """

    try:
        if int(entry.get("review_only_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass

    checked = False
    for key in ("score", "ecdf", "raw_score", "normalized_score"):
        if key not in entry:
            continue
        checked = True
        try:
            if float(entry.get(key) or 0.0) > 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return not checked


def _family_case_contribution_counts(overlays: list[dict] | None) -> dict[str, int]:
    """overlays 의 양수 family_contributions 기반 case 카운트."""
    counter: dict[str, int] = dict.fromkeys(ACTIVE_FAMILIES, 0)
    for overlay in overlays or []:
        for entry in overlay.get("family_contributions") or []:
            family = str(entry.get("family") or "")
            if family in counter and _family_contribution_has_positive_signal(entry):
                counter[family] += 1
    return counter


def _family_subdetector_case_counts(overlays: list[dict] | None, family: str) -> dict[str, int]:
    """family 내 subdetector 별 고유 Phase1 case 수."""
    case_ids_by_code: dict[str, set[str]] = {}
    for overlay in overlays or []:
        case_id = str(overlay.get("phase1_case_id") or "").strip()
        if not case_id:
            continue
        entry = _find_family_contribution(overlay, family)
        if entry is None or not _family_contribution_has_positive_signal(entry):
            continue
        for sub in entry.get("sub_detectors") or []:
            if not isinstance(sub, dict):
                continue
            code = str(sub.get("code") or sub.get("label") or "").strip()
            if not code:
                continue
            case_ids_by_code.setdefault(code, set()).add(case_id)
    return {code: len(case_ids) for code, case_ids in case_ids_by_code.items()}


def _build_all_family_summary(
    partition_summary: dict | None,
    snapshot: dict | None = None,
    *,
    overlays: list[dict] | None = None,
) -> list[dict]:
    """active(신호 desc) + dormant 순서로 모두 반환.

    Why: 신호 카운트를 PHASE2 native case (Phase2CaseSet) 의 family 별 case 수로
         통일 (사용자 결정 2026-05-28). 기존 overlay 기반 case-family contribution
         카운트는 PHASE1 case 단위라 PHASE2 가 산출한 case 와 정의가 달랐다.
         overlay 인자는 시그니처 호환을 위해 받되 본문에서는 사용하지 않는다.
    """
    from dashboard.components.phase2_native_case_metrics import (
        count_native_cases_by_family,
        resolve_phase2_case_set_from_state,
    )

    del overlays
    case_set = resolve_phase2_case_set_from_state()
    case_counts = count_native_cases_by_family(case_set)
    active_rows = [
        _build_family_overview_row(family, partition_summary, snapshot=snapshot)
        for family in ACTIVE_FAMILIES
    ]
    for row in active_rows:
        family = str(row.get("family") or "")
        if family not in ACTIVE_FAMILIES:
            continue
        case_value = int(case_counts.get(family, 0) or 0)
        row["signal_value"] = case_value
        row["이번 데이터 반응"] = f"{case_value:,}건 신호"
    active_rows.sort(
        key=lambda row: (
            int(row["signal_value"]),
            int(row["active_subdetectors"]),
            str(row["family"]),
        ),
        reverse=True,
    )
    dormant_rows = [
        _build_family_overview_row(family, partition_summary, snapshot=snapshot)
        for family in DORMANT_FAMILIES
    ]
    return active_rows + dormant_rows


_DORMANT_REASON_DETAIL_KR: dict[str, str] = {
    "supervised": (
        "감사인 검토 라벨 또는 신뢰 가능한 ground truth 가 확보되지 않아 합성 데이터 "
        "shortcut 학습 위험이 있어 비활성화. golden set 또는 실데이터 trusted positive "
        "확보 후 재검토."
    ),
    "transformer": (
        "라벨 품질과 텍스트/범주 데이터 정합성이 확보되지 않아 비활성화. 라벨과 텍스트/"
        "범주 데이터 품질, 개인정보 마스킹 정책이 확보되면 활성화."
    ),
    "sequence": (
        "전표 변경 이력·승인 흐름·이벤트 시퀀스의 contract 가 고정되지 않아 비활성화. "
        "document/user/account/time window 단위 시퀀스 정의와 leakage-safe temporal "
        "validation 이 확보되면 활성화."
    ),
    "stacking": (
        "라벨 없는 proxy score 로 복잡한 모델을 승격하면 false confidence 위험이 있어 "
        "비활성화. 활성 분석 영역의 안정적인 출력 누적과 out-of-fold/temporal validation "
        "라벨이 확보되면 활성화."
    ),
}


def _phase2_family_summary_row_html(item: dict) -> str:
    family_key = str(item["family"])
    family = html.escape(family_key)
    is_timeseries = family_key == "timeseries"
    is_dormant = str(item.get("상태", "")) == "대기"
    label_text = str(item["분석 영역"])
    if is_timeseries and not label_text.endswith("(보조)"):
        label_text = f"{label_text} (보조)"
    label = html.escape(label_text)
    purpose = html.escape(str(item["무엇을 잡나"]))
    # 시나리오는 활성 row 에만 노출. 비활성은 신호가 없어 시나리오 매칭 의미 없음.
    scenario = str(item.get("주요 감사 시나리오", "") or "")
    support_note_html = ""

    if is_dormant:
        opacity = "0.55"
        badge_html = (
            "<span style='background:#F3F4F6; color:#6B7280; "
            "font-size:0.72rem; font-weight:600; padding:2px 8px; "
            "border-radius:999px; white-space:nowrap;'>현재 미실행중</span>"
        )
        title_html = (
            f"<span style='color:#6B7280; font-size:0.875rem; font-weight:600;'>{label}</span>"
        )
        scenario_html = ""
    else:
        opacity = "1"
        is_unsupervised = family_key == "unsupervised"
        signal_value = int(item.get("signal_value", 0) or 0)
        signal_label = html.escape(str(item["이번 데이터 반응"]))
        icon, badge_bg, badge_color = _phase2_family_badge_style(signal_value)
        # VAE 는 별도 분포 패널(_render_phase2_vae_distribution / meta) 에서 카운트
        # 와 분위 통계를 노출한다. 모든 case 에 score 가 매겨져 100% 신호로 잡혀
        # 의미 없는 row 헤더 배지는 제거.
        badge_html = (
            ""
            if is_unsupervised
            else (
                f"<span style='background:{badge_bg}; color:{badge_color}; "
                "font-size:0.72rem; font-weight:600; padding:2px 8px; "
                f"border-radius:999px; white-space:nowrap;'>{icon} {signal_label}</span>"
            )
        )
        title_html = (
            f"<span style='color:#111827; font-size:0.875rem; font-weight:600;'>{label}</span>"
        )
        scenario_html = _phase2_audit_scenario_chips_html(scenario)
        support_note_html = _phase2_timeseries_support_note_html() if is_timeseries else ""

    return (
        f"<div data-family='{family}' "
        f"style='border-top:1px solid #F3F4F6; padding:10px 0; opacity:{opacity};'>"
        "<div style='display:flex; justify-content:space-between; "
        "align-items:center; gap:0.75rem;'>"
        f"<div>{title_html}</div>"
        f"{badge_html}"
        "</div>"
        "<div style='color:#6B7280; font-size:0.78rem; "
        f"line-height:1.55; margin-top:4px;'>{purpose}</div>"
        f"{scenario_html}"
        f"{support_note_html}"
        "</div>"
    )


def _phase2_audit_scenario_chips_html(scenario: str, *, max_items: int = 3) -> str:
    """주요 감사 시나리오를 row 안에서 눈에 띄는 chip 묶음으로 표시."""
    parts = [part.strip() for part in str(scenario or "").split(",") if part.strip()]
    if not parts:
        return ""
    chips = "".join(
        "<span style='display:inline-flex; align-items:center; "
        "background:#FFF7ED; color:#9A3412; border:1px solid #FED7AA; "
        "border-radius:999px; padding:2px 8px; font-size:0.72rem; "
        "font-weight:600; line-height:1.35; white-space:nowrap;'>"
        f"{html.escape(part)}</span>"
        for part in parts[:max_items]
    )
    return (
        "<div style='display:flex; align-items:flex-start; gap:0.45rem; "
        "margin-top:7px; flex-wrap:wrap;'>"
        "<span style='color:#6B7280; font-size:0.74rem; font-weight:700; "
        "line-height:1.6; white-space:nowrap;'>주요 감사 시나리오</span>"
        f"{chips}"
        "</div>"
    )


def _phase2_timeseries_support_note_html() -> str:
    """시점 이상 lane 이 보조 신호인 이유를 짧게 표시."""
    return (
        "<div style='color:#64748B; font-size:0.74rem; line-height:1.5; "
        "margin-top:5px;'>"
        "결산·시점 신호는 정상 업무에서도 자주 발생하므로 단독 판단보다 "
        "다른 영역 신호를 해석하는 보조 맥락으로 봅니다."
        "</div>"
    )


_PHASE2_DORMANT_SECTION_NOTE = (
    "합성 데이터로는 학습 품질을 장담할 수 없어 비활성화. 감사인 검토 라벨 또는 신뢰 "
    "가능한 ground truth, 실제 운영 데이터가 확보되면 활성화 가능."
)


def _phase2_family_subsection_html(title: str, rows: list[dict], *, note: str | None = None) -> str:
    """활성/비활성 소제목 + (선택) 설명 + row 묶음."""
    if not rows:
        return ""
    rows_html = "".join(_phase2_family_summary_row_html(it) for it in rows)
    note_html = (
        "<span style='color:#94A3B8; font-size:0.72rem; font-weight:500; "
        "margin-left:0.5rem; letter-spacing:0; text-transform:none;'>"
        f"— {html.escape(note)}</span>"
        if note
        else ""
    )
    return (
        "<div style='padding:0.6rem 0 0.2rem;'>"
        "<div style='color:#475569; font-size:0.78rem; font-weight:700; "
        "letter-spacing:0.02em; text-transform:uppercase; "
        "padding:0 0 0.25rem;'>"
        f"{html.escape(title)}{note_html}</div>"
        f"{rows_html}"
        "</div>"
    )


def _render_phase2_family_summary_card(items: list[dict]) -> None:
    """Phase1 L1 박스 스타일 — 단일 full-width 카드, 분석 영역별 row.

    활성 / 비활성 소제목으로 분리해 보여준다. 각 row 는 제목 + 신호 배지(헤더)와
    `무엇을 잡나` 설명(본문)을 항상 표시. 비활성은 투명도 0.55 + "현재 미실행중"
    배지 + 비활성 사유 라인 추가.
    """
    active_rows = [it for it in items if str(it.get("상태", "")) != "대기"]
    dormant_rows = [it for it in items if str(it.get("상태", "")) == "대기"]
    total_signal = sum(int(it.get("signal_value", 0) or 0) for it in active_rows)
    sections_html = _phase2_family_subsection_html(
        "활성", active_rows
    ) + _phase2_family_subsection_html("비활성", dormant_rows, note=_PHASE2_DORMANT_SECTION_NOTE)
    card_html = (
        "<div class='phase2-family-summary' style='margin:0.25rem 0 1rem;'>"
        "<div style='background:#FFFFFF; border:1px solid #E5E7EB; "
        "border-radius:12px; box-shadow:0 1px 2px rgba(15,23,42,0.04); "
        "overflow:hidden;'>"
        "<div style='display:flex; justify-content:space-between; align-items:center; "
        "background:#F1F5F9; padding:0.7rem 1.5rem; border-bottom:1px solid #E5E7EB;'>"
        "<div style='color:#0F172A; font-size:0.92rem; font-weight:600;'>"
        "분석 영역</div>"
        "<div style='color:#1D4ED8; font-size:0.82rem; font-weight:600;'>"
        f"총 {total_signal:,}건</div>"
        "</div>"
        "<div style='padding:0.4rem 1.5rem 0.6rem;'>"
        f"{sections_html}"
        "</div>"
        "</div>"
        "</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


def _build_family_focus_card_html(item: dict) -> str:
    accent = _FAMILY_ACCENT.get(str(item["family"]), "#9CA3AF")
    return (
        f"<div class='p2-focus-card' style='--accent:{accent};'>"
        f"<div class='p2-focus-rank'>우선 확인 관점</div>"
        f"<div class='p2-focus-title'>{item['분석 영역']}</div>"
        f"<div class='p2-focus-purpose'>{item['무엇을 잡나']}</div>"
        f"<div class='p2-focus-meta'>"
        f"<span class='p2-focus-chip'>이번 반응 {item['이번 데이터 반응']}</span>"
        f"<span class='p2-focus-chip'>세부 {item['세부 탐지']}</span>"
        f"</div>"
        f"</div>"
    )


def _build_family_signal_chart_frame(partition_summary: dict | None) -> pd.DataFrame:
    """family별 상대 반응도 차트용 frame."""
    rows = [
        _build_family_overview_row(family, partition_summary)
        for family in (*ACTIVE_FAMILIES, *DORMANT_FAMILIES)
    ]
    max_signal = max((int(row["signal_value"]) for row in rows), default=0)
    chart_rows: list[dict] = []
    for row in rows:
        signal_value = int(row["signal_value"])
        reaction = round(signal_value / max_signal * 100.0, 1) if max_signal else 0.0
        chart_rows.append(
            {
                "분석 영역": row["분석 영역"],
                "상태": row["상태"],
                "반응도": reaction,
            }
        )
    return pd.DataFrame(chart_rows)


def _build_family_overview_frame(
    snapshot: dict | None,
    partition_summary: dict | None,
) -> pd.DataFrame:
    """active + dormant family를 감사인이 읽는 목적 중심 표로 구성."""
    rows = [
        _build_family_overview_row(family, partition_summary, snapshot=snapshot)
        for family in (*ACTIVE_FAMILIES, *DORMANT_FAMILIES)
    ]
    display_rows: list[dict] = []
    for row in rows:
        display_rows.append(
            {
                "상태": row["상태"],
                "분석 영역": row["분석 영역"],
                "무엇을 잡나": row["무엇을 잡나"],
                "이번 데이터 반응": row["이번 데이터 반응"],
                "감사인이 확인할 것": row["감사인이 확인할 것"],
                "활성 조건/비고": row["활성 조건/비고"],
            }
        )
    return pd.DataFrame(display_rows)


def _build_family_overview_row(
    family: str,
    partition_summary: dict | None,
    *,
    snapshot: dict | None = None,
) -> dict:
    families_payload = (partition_summary or {}).get("families") or {}
    payload = families_payload.get(family) or {}
    signal_value, signal_label = _family_signal_value_and_label(family, payload)
    active_subs, total_subs = _family_subdetector_counts(family, payload)
    is_active = family in ACTIVE_FAMILIES
    status = "활성" if is_active else "대기"
    note = (
        f"{active_subs}/{total_subs} 세부 탐지 반응"
        if is_active
        else _dormant_activation_note(family, snapshot)
    )
    return {
        "family": family,
        "상태": status,
        "분석 영역": _FAMILY_LABELS_KR.get(family, family),
        "무엇을 잡나": _FAMILY_AUDIT_PURPOSE_KR.get(family, "-"),
        "주요 감사 시나리오": _FAMILY_AUDIT_SCENARIO_KR.get(family, "-"),
        "이번 데이터 반응": signal_label,
        "감사인이 확인할 것": _FAMILY_AUDIT_CHECK_KR.get(family, "-"),
        "활성 조건/비고": note,
        "세부 탐지": f"{active_subs}/{total_subs}",
        "signal_value": signal_value,
        "active_subdetectors": active_subs,
    }


def _family_signal_value_and_label(family: str, payload: dict) -> tuple[int, str]:
    if family == "unsupervised":
        value = int(payload.get("high_count_q95") or 0)
        return value, f"{value:,}건 q95 후보"
    if family in ACTIVE_FAMILIES:
        distribution = payload.get("score_distribution") or {}
        value = int(distribution.get("nonzero_count") or 0)
        return value, f"{value:,}건 신호"
    return 0, "조건 충족 전"


def _family_subdetector_counts(family: str, payload: dict) -> tuple[int, int]:
    family_subs = [code for fam, code, _label in SUB_DETECTORS if fam == family]
    if not family_subs:
        return 0, 0
    sub_lookup = payload.get("sub_detectors") or {}
    active = sum(
        1 for code in family_subs if int((sub_lookup.get(code) or {}).get("hit_count") or 0) > 0
    )
    return active, len(family_subs)


def _dormant_activation_note(family: str, snapshot: dict | None) -> str:
    contract = (snapshot or {}).get("inference_contract") or {}
    model_versions = contract.get("model_versions") or {}
    version_payload = model_versions.get(family) or {}
    version = version_payload.get("model_version")
    base = _DORMANT_ACTIVATION_KR.get(family) or DORMANT_REASONS.get(family, "-")
    if version is None:
        return base
    return f"{base} · 준비된 기준 v{version}"


def _count_active_families(
    partition_summary: dict | None,
    *,
    overlays: list[dict] | None = None,
) -> int:
    """신호가 있는 표시 lane 수.

    overlay 가 있으면 ribbon / lane matrix / family hit bar 모두 같은 case-family
    contribution 단위를 사용한다. partition_summary 는 overlay 가 없을 때만 row-level
    fallback 으로 사용한다.
    """
    active = {"unsupervised", "timeseries"}
    case_counts = _family_case_contribution_counts(overlays)
    if overlays:
        return sum(1 for family in active if int(case_counts.get(family, 0) or 0) > 0)

    if not partition_summary:
        return 0
    families = partition_summary.get("families") or {}
    count = 0
    for name, payload in families.items():
        if name not in active or not isinstance(payload, dict):
            continue
        distribution = payload.get("score_distribution") or {}
        nonzero = int(distribution.get("nonzero_count") or 0)
        high = int(payload.get("high_count_q95") or 0)
        if nonzero > 0 or high > 0:
            count += 1
    return count


def _count_evidence_tiers(overlays: list[dict]) -> dict[str, int]:
    """overlay 의 max_evidence_tier 분포 집계 (strong/moderate/weak)."""
    counts: dict[str, int] = {"strong": 0, "moderate": 0, "weak": 0}
    for overlay in overlays:
        tier = str(overlay.get("max_evidence_tier") or "").strip().lower()
        if tier in counts:
            counts[tier] += 1
    return counts


def _resolve_display_overlays(
    result: PipelineResult | None,
    partition: str,
) -> tuple[list[dict], str]:
    """Return overlays only when they are meaningful for the selected partition.

    Production inference can currently attach placeholder overlays where case ids
    exist but family contributions / lanes are not wired yet. In that state the UI
    must not render "0 signal" as if Phase 2 found nothing.

    Why: overlay 가 비어있을 때 ``loaded.phase2_overlay_status`` 가 있으면 그 진단
    status(``schema_mismatch`` / ``batch_id_mismatch`` / ``training_report_mismatch``
    /...) 를 사용해 UI 에 정확한 사유를 표시한다. 기존 ``missing`` 은 그 외 일반
    fallback.
    """
    overlays = _resolve_phase2_overlays_from_state()
    if not overlays:
        store_status = (
            getattr(result, "phase2_overlay_status", None) if result is not None else None
        )
        if store_status and store_status != "loaded":
            return [], str(store_status)
        return [], "missing"
    result_partition = _normalize_display_partition(getattr(result, "phase2_partition", None))
    if result_partition != "전체" and partition != result_partition:
        return [], "partition_mismatch"
    if not _has_case_level_phase2_details(overlays):
        return overlays, "placeholder"
    return overlays, "available"


def _has_case_level_phase2_details(overlays: list[dict]) -> bool:
    """Whether overlays contain case-level family attribution, not just case ids."""
    for overlay in overlays:
        if overlay.get("top_family") or overlay.get("max_evidence_tier"):
            return True
        if overlay.get("lane_membership") or overlay.get("family_contributions"):
            return True
    return False


def _normalize_display_partition(value) -> str:
    text = str(value or "전체").strip()
    return text if text in _PARTITION_OPTIONS else "전체"


def _overlay_status_short_text(status: str) -> str:
    """KPI 카드 sub-text 용 짧은 라벨 — 9 store-level status + in-memory 4 분기."""
    labels = {
        # in-memory 분기 (_resolve_display_overlays)
        "available": "분포 없음",
        "missing": "overlay 없음",
        "placeholder": "case-level overlay 미생성",
        "partition_mismatch": "선택 연도와 추론 결과 불일치",
        # overlay_store 진단 (loaded.phase2_overlay_status)
        "loaded": "분포 없음",
        "schema_mismatch": "overlay 형식 불일치",
        "batch_id_mismatch": "batch 불일치",
        "training_report_mismatch": "재학습 후 stale",
        "invalid_payload": "overlay payload 손상",
        "parse_error": "overlay 파일 파싱 실패",
        "unsafe_batch_id": "batch_id 안전성 문제",
        "ctx_missing": "회사 컨텍스트 없음",
    }
    return labels.get(status, "확인 필요")


def _overlay_status_message(status: str, partition: str) -> str:
    """안내 메시지 — 사유 + next action 을 한 문장으로.

    분기별 메시지는 P2-3 에서 9 store-level status 와 4 in-memory status 를 모두 다룬다.
    """
    if status == "partition_mismatch":
        return (
            f"선택한 partition({partition})과 현재 Phase 2 추론 결과의 partition이 다릅니다. "
            "상단 family 탭의 집계는 선택 연도 기준으로 볼 수 있지만, case-level KPI는 "
            "현재 추론 결과와 일치할 때만 표시합니다."
        )
    if status == "placeholder":
        return (
            "현재 Phase 2 결과에는 case-level 분석 영역 attribution이 아직 연결되지 않았습니다. "
            "상단 family 탭의 aggregate hit는 확인할 수 있지만, 신호 케이스 수는 "
            "0건으로 해석하면 안 됩니다."
        )
    if status == "missing":
        return (
            "현재 Phase 2 결과에 case-level overlay가 없습니다. "
            "Phase 2 를 다시 추론하면 케이스별 결과가 저장됩니다."
        )
    if status == "schema_mismatch":
        return (
            "저장된 overlay 형식이 현재 버전과 맞지 않습니다. "
            "Phase 2 를 다시 추론하면 최신 형식으로 갱신됩니다."
        )
    if status == "batch_id_mismatch":
        return (
            "저장된 overlay 가 현재 batch 와 일치하지 않아 사용하지 않았습니다. "
            "현재 batch 로 Phase 2 를 다시 추론하세요."
        )
    if status == "training_report_mismatch":
        return (
            "재학습 이후 이전 overlay 가 무효화되었습니다. "
            "새 학습 기준으로 Phase 2 를 다시 추론하세요."
        )
    if status == "invalid_payload":
        return (
            "Overlay payload 형식이 손상되어 케이스 결과를 표시할 수 없습니다. "
            "Phase 2 를 다시 추론하세요."
        )
    if status == "parse_error":
        return "Overlay 파일을 읽지 못했습니다. Phase 2 를 다시 추론하면 파일이 재생성됩니다."
    if status == "unsafe_batch_id":
        return (
            "Batch ID 검증에 실패해 overlay 를 불러오지 않았습니다. "
            "관리자에게 batch ID 형식을 확인하세요."
        )
    if status == "ctx_missing":
        return "회사/engagement 컨텍스트가 없어 overlay 복원이 제한됩니다. 회사를 다시 선택하세요."
    return ""


# ──────────────────────────────────────────────────────────────
# 새 sub-tab skeleton: 전체 요약 + family별 독립 tab.
# Why: Phase 2는 통합 점수/검토등급 tab이 아니라 family lane별 보조 분석으로 노출한다.
# ──────────────────────────────────────────────────────────────


def _render_phase2_family_tab(
    snapshot: dict | None,
    partition: str,
    partition_summary: dict | None,
    family: str,
) -> None:
    """단일 Phase2 family 탭 — 영역 카드 + family case 상세."""
    del snapshot

    families_payload = (partition_summary or {}).get("families") or {}
    from dashboard._state import KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    overlays, overlay_status = _resolve_display_overlays(phase2_result, partition)
    case_counts = _family_case_contribution_counts(overlays)
    subdetector_case_counts = _family_subdetector_case_counts(overlays, family)

    source_suffix = _phase2_signal_source_suffix(partition_summary)
    st.markdown(f"#### {_FAMILY_LABELS_KR.get(family, family)}{source_suffix}")
    _render_phase2_signal_source_caption(partition_summary)
    with st.container(border=True):
        _render_phase2_family_section_card(
            family,
            families_payload.get(family) or {},
            case_count=int(case_counts.get(family, 0) or 0),
            subdetector_case_counts=subdetector_case_counts,
        )
    if family == "unsupervised":
        with st.container(border=True):
            _render_phase2_vae_distribution(
                overlays,
                empty_state=None,
                chart_key="phase2_vae_distribution_family_tab",
                show_description=False,
            )
    _render_phase2_family_case_section(
        family,
        overlays,
        overlay_status=overlay_status,
        partition=partition,
        phase2_result=phase2_result,
    )


def _render_phase2_analysis_area_tab(
    snapshot: dict | None,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """② 분석 영역별 — Phase 1 데이터 정합성 패턴 차용.

    Why: 5개 활성 family 를 영역별 카드로 펼쳐, 각 영역의 신호 케이스 수와
         세부 탐지 항목 적중 현황을 한 카드 안에 모은다. 비활성 4개는 expander 로 보조 정보.
    """
    del partition

    families_payload = (partition_summary or {}).get("families") or {}
    overlays = _resolve_phase2_overlays_from_state()
    case_counts = _family_case_contribution_counts(overlays)
    subdetector_case_counts_by_family = {
        family: _family_subdetector_case_counts(overlays, family) for family in ACTIVE_FAMILIES
    }

    source_suffix = _phase2_signal_source_suffix(partition_summary)
    st.markdown(f"#### 활성 분석 영역{source_suffix}")
    st.caption("Phase 2 에서 신호를 잡은 분석 영역 5개 — 영역별 세부 탐지 항목 적중 현황")
    _render_phase2_signal_source_caption(partition_summary)

    for family in ACTIVE_FAMILIES:
        payload = families_payload.get(family) or {}
        with st.container(border=True):
            _render_phase2_family_section_card(
                family,
                payload,
                case_count=int(case_counts.get(family, 0) or 0),
                subdetector_case_counts=subdetector_case_counts_by_family.get(family, {}),
            )

    st.markdown("#### 추가 분석 영역 (대기)")
    st.caption(
        "데이터 부족 또는 기준 미충족으로 보류된 4개 영역. 활성 조건이 갖춰지면 추후 활성화."
    )
    with st.expander("대기 분석 영역 상세 보기", expanded=False):
        st.dataframe(
            _build_dormant_family_frame(snapshot, partition_summary),
            width="stretch",
            hide_index=True,
        )


def _render_phase2_family_section_card(
    family: str,
    payload: dict,
    *,
    case_count: int,
    subdetector_case_counts: dict[str, int] | None = None,
) -> None:
    """단일 family 영역 카드 — 헤더(라벨/케이스 수) + 설명 + subdetector 표."""
    label_kr = _FAMILY_LABELS_KR.get(family, family)
    if family == "timeseries":
        label_kr = f"{label_kr} (보조)"
    accent = _FAMILY_ACCENT.get(family, "#9CA3AF")
    if family == "unsupervised":
        purpose = (
            "정해진 룰로 설명하기 어려운 금액·계정·거래속성 조합이 정상 전표 분포에서 "
            "얼마나 벗어났는지 봅니다."
        )
        scenario_html = ""
        support_note_html = _phase2_vae_family_note_html()
    else:
        purpose = _FAMILY_AUDIT_PURPOSE_KR.get(family, "-")
        scenario_html = _phase2_audit_scenario_chips_html(_FAMILY_AUDIT_SCENARIO_KR.get(family, ""))
        support_note_html = _phase2_timeseries_support_note_html() if family == "timeseries" else ""

    st.markdown(
        f"<div style='border-left:4px solid {accent}; padding:2px 0 4px 12px;"
        f" margin-bottom:0.4rem;'>"
        f"<div style='display:flex; justify-content:space-between;"
        f" align-items:baseline; gap:0.5rem;'>"
        f"<div style='color:#111827; font-size:1rem; font-weight:700;'>{label_kr}"
        f"<span style='color:#9CA3AF; font-size:0.72rem; font-weight:500; margin-left:6px;'>"
        f"({family})</span></div>"
        f"<div style='color:#1D4ED8; font-size:0.85rem; font-weight:600;'>"
        f"신호 케이스 {case_count:,}건</div>"
        f"</div>"
        f"<div style='color:#374151; font-size:0.82rem; margin-top:4px; line-height:1.5;'>"
        f"{purpose}</div>"
        f"{scenario_html}"
        f"{support_note_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    sub_lookup = payload.get("sub_detectors") or {}
    count_column = "적중 case 수" if subdetector_case_counts is not None else "탐지 hit 수"
    rows: list[dict] = []
    for fam, code, label in SUB_DETECTORS:
        if fam != family:
            continue
        sub_payload = sub_lookup.get(code) or {}
        if subdetector_case_counts is not None:
            signal_count = int(subdetector_case_counts.get(code, 0) or 0)
        else:
            signal_count = int(sub_payload.get("hit_count") or 0)
        rows.append(
            {
                "코드": code,
                "세부 탐지 내용": _phase2_subdetector_display_label(
                    code,
                    str(sub_payload.get("label") or label),
                    include_code=False,
                    include_tier=False,
                ),
                count_column: signal_count,
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if subdetector_case_counts is not None:
            st.caption(
                "위 숫자는 세부 탐지별 고유 Phase1 case 수입니다. 한 case가 여러 세부 탐지에 "
                "걸리면 각 세부 탐지에 중복 집계됩니다."
            )
        else:
            st.caption(
                "위 숫자는 세부 탐지기의 모집단 hit 수입니다. 감사인이 실제로 검토할 대상은 "
                "아래 Case 목록에서 우선순위로 추린 case입니다."
            )
        _render_phase2_subdetector_descriptions(family, rows)


def _phase2_vae_family_note_html() -> str:
    return (
        "<div style='margin-top:0.45rem; padding:0.6rem 0.7rem; "
        "border:1px solid #E5E7EB; border-radius:8px; background:#F9FAFB;'>"
        "<div style='color:#475569; font-size:0.78rem; line-height:1.55;'>"
        "<div><b style='color:#111827;'>VAE Deep Learning score</b>는 VAE와 "
        "Isolation Forest가 학습한 정상 전표 분포에서 각 case가 얼마나 멀리 "
        "떨어져 있는지를 봅니다.</div>"
        "<div style='margin-top:4px;'>점수가 클수록 정상 분포의 꼬리에 있는 case이며, "
        "q95 cutoff 위쪽 꼬리를 감사인 우선 검토 후보로 봅니다.</div>"
        "<div style='margin-top:4px;'>하위 score 영역은 정상 분포에 가까운 case로 보아 "
        "검토 우선순위에서 제외합니다.</div>"
        "</div>"
        "</div>"
    )


def _render_phase2_family_case_section(
    family: str,
    overlays: list[dict],
    *,
    overlay_status: str,
    partition: str,
    phase2_result=None,
) -> None:
    """Family 탭 하단 case 목록 — PHASE2 native case 우선, 부재 시 안내.

    S7 변경: 기존 overlay 기반 PHASE1 case master 대신 ``phase2_case_set`` 의
    family 별 native case row 를 표시. 사용자 lock 결정 5에 따라 case_set 부재
    시 명시적 안내 + "PHASE2 추론 실행" 버튼만 노출한다.
    overlays / overlay_status / partition 은 신규 panel 에서 사용하지 않지만,
    호출부 시그니처 호환을 위해 유지한다.
    """
    del overlays, overlay_status, partition  # 신규 panel 는 case_set 직접 사용

    from dashboard._state import KEY_PHASE1_RESULT
    from dashboard.components.phase2_native_case_panel import (
        render_phase2_native_case_panel,
    )

    case_set = getattr(phase2_result, "phase2_case_set", None) if phase2_result else None
    phase1_lookup = _build_phase2_phase1_priority_lookup(phase2_result)
    # Why: Phase 1 의 case drilldown 과 같은 "Case 설명 → document_id master →
    #      원장 라인" 구성을 위해 원장 데이터를 보유한 pr 을 전달.
    pr = st.session_state.get(KEY_PHASE1_RESULT) or phase2_result

    st.markdown("#### Case 목록")
    render_phase2_native_case_panel(
        family,
        case_set=case_set,
        phase1_case_lookup=phase1_lookup,
        pr=pr,
    )


def _build_phase2_family_case_frame(
    family: str,
    overlays: list[dict],
    *,
    phase2_result=None,
    max_rows: int = 1_000,
) -> pd.DataFrame:
    """Family contribution 이 있는 Phase1 case 목록."""
    priority_lookup = _build_phase2_phase1_priority_lookup(phase2_result)
    rows: list[dict] = []
    for overlay in overlays or []:
        entry = _find_family_contribution(overlay, family)
        if entry is None or not _family_contribution_has_positive_signal(entry):
            continue
        case_id = str(overlay.get("phase1_case_id") or "").strip()
        if not case_id:
            continue
        phase1_meta = priority_lookup.get(case_id, {})
        priority_score = phase1_meta.get("priority_score")
        tier_token = str(entry.get("evidence_tier") or "").strip().lower()
        sub_codes = ", ".join(
            str(sub.get("code") or sub.get("label") or "")
            for sub in (entry.get("sub_detectors") or [])
            if isinstance(sub, dict) and (sub.get("code") or sub.get("label"))
        )
        row = {
            "case_id": case_id,
            "Phase1 등급": str(phase1_meta.get("priority_band", "미확인")).upper(),
            "Phase1 점수": _format_phase2_numeric(priority_score, digits=3),
            "ECDF": _format_phase2_numeric(entry.get("ecdf"), digits=4),
            "대표 영역": _FAMILY_LABELS_KR.get(str(overlay.get("top_family") or ""), "-"),
            "_phase2_tier_rank": _phase2_tier_rank(tier_token),
            "_phase1_sort_score": float(priority_score) if priority_score is not None else -1.0,
            "_ecdf_sort_score": _coerce_float(entry.get("ecdf")),
            "_tail_score_sort": _coerce_float(entry.get("score")),
        }
        if family == "unsupervised":
            row["꼬리점수"] = _format_phase2_numeric(entry.get("score"), digits=4)
        else:
            row["Phase2 강도"] = _PHASE2_EVIDENCE_TIER_KR.get(tier_token, tier_token or "-")
            row["세부 탐지 내용"] = _phase2_subdetector_codes_to_display(
                sub_codes,
                include_code=False,
                include_tier=False,
            )
        rows.append(row)
    if family == "unsupervised":
        rows.sort(
            key=lambda row: (
                float(row.get("_tail_score_sort") or 0.0),
                float(row.get("_phase1_sort_score") or -1.0),
                float(row.get("_ecdf_sort_score") or 0.0),
            ),
            reverse=True,
        )
    else:
        rows.sort(
            key=lambda row: (
                int(row.get("_phase2_tier_rank") or 0),
                float(row.get("_phase1_sort_score") or -1.0),
                float(row.get("_ecdf_sort_score") or 0.0),
            ),
            reverse=True,
        )
    frame = pd.DataFrame(rows[:max_rows])
    hidden = [
        col
        for col in (
            "_phase2_tier_rank",
            "_phase1_sort_score",
            "_ecdf_sort_score",
            "_tail_score_sort",
        )
        if col in frame.columns
    ]
    if hidden:
        frame = frame.drop(columns=hidden)
    return frame


def _render_phase2_family_case_drilldown(
    family: str,
    case_frame: pd.DataFrame,
    *,
    phase2_result=None,
) -> None:
    """선택된 Phase2 family case 를 Phase1 검토 케이스 상세로 표시."""
    if case_frame.empty or "case_id" not in case_frame.columns:
        return

    from dashboard._state import KEY_PHASE1_RESULT
    from dashboard.tab_phase1 import _render_case_drilldown
    from src.export.phase1_case_view import build_phase1_case_drilldown

    pr = st.session_state.get(KEY_PHASE1_RESULT) or phase2_result
    if pr is None:
        st.caption("Phase 1 case 상세를 표시할 기준 결과가 없습니다.")
        return

    options = _phase2_family_case_options(case_frame)
    if not options:
        return

    st.markdown("#### Case 상세")
    selected_label = st.selectbox(
        "Case 선택",
        options=list(options.keys()),
        key=f"phase2_family_case_select_{family}",
    )
    selected_case_id = options[selected_label]
    drilldown = build_phase1_case_drilldown(pr, selected_case_id)
    if drilldown is None:
        st.info("선택한 case 의 Phase 1 상세 근거를 찾지 못했습니다.")
        return
    _render_case_drilldown(
        drilldown,
        pr=pr,
        key_suffix=f"phase2_{family}_{selected_case_id}",
    )


def _render_phase2_family_case_master(
    family: str,
    case_frame: pd.DataFrame,
    *,
    phase2_result=None,
) -> None:
    """Phase1 검토 케이스와 같은 AgGrid master/detail UI."""
    if case_frame.empty or "case_id" not in case_frame.columns:
        return

    from dashboard._state import KEY_PHASE1_RESULT
    from dashboard.tab_phase1 import _render_case_drilldown, _render_rule_case_master
    from src.export.phase1_case_view import build_phase1_case_drilldown

    pr = st.session_state.get(KEY_PHASE1_RESULT) or phase2_result
    if pr is None:
        st.caption("Phase 1 case 상세를 표시할 기준 결과가 없습니다.")
        return

    case_rows = _phase2_family_case_master_rows(
        case_frame,
        family=family,
        phase2_result=phase2_result,
    )
    hide_columns = {"전표 수", "Band"}
    if family == "unsupervised":
        hide_columns.update({"세부 탐지 내용", "Phase2 강도"})
    selected_case_id = _render_rule_case_master(
        f"phase2_{family}",
        case_rows,
        key_suffix=f"phase2_{family}",
        hide_columns=hide_columns,
        caption_override="",
        show_header=False,
        preserve_order=True,
        rank_column=True,
    )
    if not selected_case_id:
        st.caption("위 case 목록에서 한 줄을 선택하세요.")
        return

    drilldown = build_phase1_case_drilldown(pr, selected_case_id)
    if drilldown is None:
        st.info("선택한 case 의 Phase 1 상세 근거를 찾지 못했습니다.")
        return
    _render_case_drilldown(
        drilldown,
        pr=pr,
        key_suffix=f"phase2_{family}_{selected_case_id}",
    )


def _phase2_family_case_master_rows(
    case_frame: pd.DataFrame,
    *,
    family: str = "",
    phase2_result=None,
) -> list[dict]:
    """Phase1 `_render_rule_case_master` 입력 형태로 변환."""
    from dashboard._state import KEY_PHASE1_RESULT
    from dashboard.tab_phase1 import _compact_case_reason, _violation_natural_label
    from src.export.phase1_case_view import resolve_phase1_case_result

    pr = st.session_state.get(KEY_PHASE1_RESULT) or phase2_result
    phase1 = resolve_phase1_case_result(pr) if pr is not None else None
    case_lookup = {
        str(getattr(case, "case_id", "") or ""): case for case in getattr(phase1, "cases", []) or []
    }

    rows: list[dict] = []
    for _index, row in case_frame.iterrows():
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            continue
        case = case_lookup.get(case_id)
        if case is None:
            out = {
                "case_id": case_id,
                "natural_label": case_id,
                "priority_band": str(row.get("Phase1 등급") or "low").lower(),
                "priority_score": _coerce_float(row.get("Phase1 점수")),
                "document_count": 0,
                "total_amount": 0.0,
                "why": "",
            }
            if family == "unsupervised":
                out["꼬리점수"] = str(row.get("꼬리점수") or "-")
            else:
                out["세부 탐지 내용"] = str(row.get("세부 탐지 내용") or "-")
                out["Phase2 강도"] = str(row.get("Phase2 강도") or "-")
            rows.append(out)
            continue
        why = getattr(case, "risk_narrative", "") or getattr(case, "representative_explanation", "")
        compact_why = _compact_case_reason(why)
        out = {
            "case_id": case_id,
            "natural_label": _violation_natural_label(case),
            "priority_band": str(getattr(case, "priority_band", "") or "low"),
            "priority_score": float(getattr(case, "priority_score", 0.0) or 0.0),
            "document_count": int(getattr(case, "document_count", 0) or 0),
            "total_amount": float(getattr(case, "total_amount", 0.0) or 0.0),
            "why": compact_why,
        }
        if family == "unsupervised":
            out["꼬리점수"] = str(row.get("꼬리점수") or "-")
        else:
            out["세부 탐지 내용"] = str(row.get("세부 탐지 내용") or "-")
            out["Phase2 강도"] = str(row.get("Phase2 강도") or "-")
        rows.append(out)
    return rows


def _phase2_family_case_options(case_frame: pd.DataFrame) -> dict[str, str]:
    """Family case 상세 selectbox 용 label → case_id map."""
    options: dict[str, str] = {}
    for _index, row in case_frame.iterrows():
        case_id = str(row.get("case_id") or "").strip()
        if not case_id or case_id in options.values():
            continue
        rank = len(options) + 1
        band = str(row.get("Phase1 등급") or "미확인").strip()
        tier = str(row.get("Phase2 강도") or "-").strip()
        detector = str(row.get("세부 탐지 내용") or "-").strip()
        detector = detector if len(detector) <= 34 else f"{detector[:31]}..."
        label = f"{rank}. {band} · {tier} · {detector} · {case_id}"
        options[label] = case_id
    return options


_PHASE2_SUBDETECTOR_LABEL_KR: dict[str, str] = {
    "VAE-01": "VAE 분포 꼬리",
    "TS01": "단기간 거래 폭증",
    "TS02": "비정상 빈도",
    "L2-03a": "정확 중복",
    "L2-03b": "유사 중복",
    "L2-03c": "분할 거래",
    "L2-03d": "시차 중복",
}

_PHASE2_SUBDETECTOR_TIER: dict[str, str] = {
    "VAE-01": "ml_quantile",
    "TS01": "moderate",
    "TS02": "weak",
    "L2-03a": "strong",
    "L2-03b": "moderate",
    "L2-03c": "moderate",
    "L2-03d": "weak",
}


def _phase2_subdetector_display_label(
    code: str,
    fallback: str = "",
    *,
    include_code: bool = True,
    include_tier: bool = True,
) -> str:
    code_text = str(code or "").strip()
    label = _PHASE2_SUBDETECTOR_LABEL_KR.get(code_text) or str(fallback or code_text)
    tier = _phase2_subdetector_tier_label(code_text)
    parts = []
    if include_code and code_text:
        parts.append(code_text)
    parts.append(label)
    text = " · ".join(parts)
    return f"{text} ({tier})" if include_tier and tier != "-" else text


def _phase2_subdetector_codes_to_display(
    codes: str,
    *,
    include_code: bool = True,
    include_tier: bool = True,
) -> str:
    tokens = [token.strip() for token in str(codes or "").split(",") if token.strip()]
    if not tokens:
        return "-"
    return ", ".join(
        _phase2_subdetector_display_label(
            token,
            include_code=include_code,
            include_tier=include_tier,
        )
        for token in tokens
    )


def _phase2_subdetector_tier_label(code: str) -> str:
    tier = _PHASE2_SUBDETECTOR_TIER.get(str(code or "").strip(), "")
    return _PHASE2_EVIDENCE_TIER_KR.get(tier, tier or "-")


_PHASE2_SUBDETECTOR_DESCRIPTION_KR: dict[str, str] = {
    "VAE-01": "금액, 계정, 사용자, 거래 속성 조합이 전체 분포의 꼬리에 있는 case를 잡습니다.",
    "TS01": "짧은 기간에 같은 작성자, 프로세스, 계정 조합 거래가 몰리는 case를 잡습니다.",
    "TS02": "평소보다 반복 빈도나 발생 패턴이 튀는 case를 잡습니다.",
    "L2-03a": "같은 날짜, 계정, 금액 등 핵심 조건이 정확히 겹치는 중복 후보를 잡습니다.",
    "L2-03b": "거래 조건이 완전히 같지는 않지만 금액과 참조 정보가 유사한 중복 후보를 잡습니다.",
    "L2-03c": "승인한도 회피나 분할 처리 가능성이 있는 금액 쪼개기 후보를 잡습니다.",
    "L2-03d": "일자만 조금 다른 동일 또는 유사 금액 반복 거래 후보를 잡습니다.",
}


def _render_phase2_subdetector_descriptions(family: str, rows: list[dict]) -> None:
    """세부 탐지 표 아래에 각 탐지 내용 설명을 별도 블록으로 표시."""
    if family == "unsupervised":
        st.markdown(
            "<div style='margin-top:0.45rem; margin-bottom:0.9rem; padding:0.6rem 0.75rem; "
            "border:1px solid #E5E7EB; border-radius:8px; background:#F9FAFB; "
            "color:#475569; font-size:0.78rem; line-height:1.55;'>"
            "<div><b style='color:#111827;'>VAE Deep Learning score</b>는 VAE와 "
            "Isolation Forest가 학습한 정상 전표 분포에서 각 case가 얼마나 멀리 "
            "떨어져 있는지를 봅니다.</div>"
            "<div style='margin-top:4px;'>점수가 클수록 정상 분포의 꼬리에 있는 case이며, "
            "q95 cutoff 위쪽 꼬리를 감사인 우선 검토 후보로 봅니다.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.write("")
        return

    descriptions: list[str] = []
    for row in rows:
        code = str(row.get("코드") or "").strip()
        label = _PHASE2_SUBDETECTOR_LABEL_KR.get(code) or str(row.get("세부 탐지 내용") or code)
        desc = _PHASE2_SUBDETECTOR_DESCRIPTION_KR.get(code)
        if not desc:
            continue
        descriptions.append(
            "<div style='padding:3px 0; color:#475569; font-size:0.78rem; line-height:1.45;'>"
            f"<b style='color:#111827;'>{html.escape(label)}</b> — {html.escape(desc)}"
            "</div>"
        )
    if not descriptions:
        return
    st.markdown(
        "<div style='margin-top:0.45rem; margin-bottom:0.9rem; padding:0.55rem 0.7rem; "
        "border:1px solid #E5E7EB; border-radius:8px; background:#F9FAFB;'>"
        + "".join(descriptions)
        + "</div>",
        unsafe_allow_html=True,
    )
    st.write("")


def _build_phase2_phase1_priority_lookup(phase2_result=None) -> dict[str, dict]:
    """phase1_result.cases 에서 case_id → priority metadata."""
    from dashboard._state import KEY_PHASE1_RESULT
    from src.export.phase1_case_view import resolve_phase1_case_result

    pr = st.session_state.get(KEY_PHASE1_RESULT) or phase2_result
    if pr is None:
        return {}
    case_result = resolve_phase1_case_result(pr)
    if case_result is None:
        return {}
    lookup: dict[str, dict] = {}
    for case in case_result.cases:
        case_id = str(getattr(case, "case_id", "") or "").strip()
        if not case_id:
            continue
        lookup[case_id] = {
            "priority_band": str(getattr(case, "priority_band", "") or "low"),
            "priority_score": float(getattr(case, "priority_score", 0.0) or 0.0),
        }
    return lookup


def _find_family_contribution(overlay: dict, family: str) -> dict | None:
    for entry in overlay.get("family_contributions") or []:
        if entry.get("family") == family:
            return entry
    return None


_PHASE2_EVIDENCE_TIER_KR: dict[str, str] = {
    "strong": "Strong",
    "moderate": "Moderate",
    "weak": "Weak",
    "ml_quantile": "ML",
}

_PHASE2_TIER_RANK: dict[str, int] = {
    "strong": 3,
    "moderate": 2,
    "weak": 1,
    "ml_quantile": 0,
}


def _format_phase2_numeric(value, *, digits: int) -> float | str:
    if value is None:
        return "-"
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return "-"


def _coerce_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _phase2_tier_rank(tier: str) -> int:
    return _PHASE2_TIER_RANK.get(str(tier or "").strip().lower(), -1)


def _render_phase2_stats_tab(
    snapshot: dict | None,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """③ 통계결과 — lane-local Phase 2 분포.

    Why: active product path 에서는 PHASE2 global/integrated score 를 노출하지 않는다.
         통계 화면은 family별 case-family hit, lane × evidence tier, subdetector 분포만
         보여준다.
    """
    del snapshot, partition

    overlays = _resolve_phase2_overlays_from_state()
    if not overlays:
        st.info("통계를 계산할 Phase 2 overlay 가 없습니다. Phase 2 추론을 실행하세요.")
        return

    with st.container(border=True):
        st.markdown("##### 1. 분석 영역별 case-family 적중 분포")
        st.caption("한 case 가 여러 영역에 걸리면 중복 집계")
        _render_phase2_family_case_bar(overlays, chart_key="phase2_stats_family_bar")

    with st.container(border=True):
        st.markdown("##### 2. Lane × 근거 강도 matrix")
        st.caption("표시 lane 별 strong / moderate / weak case-family contribution 수")
        _render_phase2_lane_matrix(overlays)

    with st.container(border=True):
        st.markdown("##### 3. 세부 탐지 항목별 적중 분포")
        st.dataframe(
            _build_subdetector_kr_frame(partition_summary),
            width="stretch",
            hide_index=True,
        )


# ── 분석 영역 카드 디자인 ─────────────────────────────────────

_FAMILY_LABELS_KR: dict[str, str] = {
    "timeseries": "시점 이상",
    "unsupervised": "VAE Deep Learning",
    "supervised": "지도 학습",
    "transformer": "트랜스포머",
    "sequence": "시퀀스",
    "stacking": "스태킹",
}

_FAMILY_ACCENT: dict[str, str] = {
    "timeseries": "#0D9488",  # teal-600
    "unsupervised": "#D97706",  # amber-600
}

_FAMILY_HINT_KR: dict[str, str] = {
    "timeseries": "거래 빈도·집중 등 시계열 이상",
    "unsupervised": "ML 모델이 분포 꼬리로 분류한 케이스",
    "supervised": "감사 라벨로 학습한 전표 위험 패턴",
    "transformer": "텍스트·범주 조합의 복합 이상 패턴",
    "sequence": "전표 흐름 순서와 반복 경로 이상",
    "stacking": "여러 분석 영역 결과를 결합한 종합 신호",
}

_FAMILY_AUDIT_PURPOSE_KR: dict[str, str] = {
    "timeseries": "결산기 집중, 짧은 기간 폭증, 비정상 시간대처럼 발생 시점이 튀는 거래를 봅니다.",
    "unsupervised": "정해진 룰로 설명하기 어려운 금액·계정·거래속성 조합의 분포 꼬리를 봅니다.",
    "supervised": "검토 완료 라벨이 충분할 때 과거 감사인이 문제 삼은 패턴과 유사한 후보를 봅니다.",
    "transformer": "적요, 거래처, 계정, 사용자 등 범주 조합의 문맥상 이상한 후보를 봅니다.",
    "sequence": "승인-기표-수정-상계처럼 사건 순서가 일반 흐름과 다른 후보를 봅니다.",
    "stacking": "여러 분석 영역이 동시에 약하게 반응한 후보를 한 번 더 모아 봅니다.",
}

_FAMILY_AUDIT_CHECK_KR: dict[str, str] = {
    "timeseries": "cutoff, 결산 조정, 승인일과 기표일 차이 확인",
    "unsupervised": "Phase1 근거와 함께 금액·계정 조합의 업무상 설명 가능성 확인",
    "supervised": "라벨 품질과 holdout 성능이 확보된 뒤 검토 후보로 사용",
    "transformer": "텍스트/범주 데이터 품질과 개인정보 마스킹 정책 확인",
    "sequence": "이벤트 로그 또는 전표 변경 이력이 있을 때 순서 기반으로 확인",
    "stacking": "기본 분석 영역 결과가 충분히 쌓인 뒤 종합 우선순위 보조로 사용",
}

# family 별 강한 부정/감사 시나리오. _FAMILY_AUDIT_PURPOSE_KR(거래 패턴 일반 묘사)와는
# 다른 정보로, 도메인 매칭(PCAOB AS 2401 / ISA 240 / 금감원 실증 사례)을 한 줄로 표현한다.
_FAMILY_AUDIT_SCENARIO_KR: dict[str, str] = {
    "timeseries": "결산기 매출 인식 조작, cutoff 조작, 백데이팅 (ISA 240 §A41 period-end)",
    "unsupervised": "정해진 룰로 잡히지 않는 신종 패턴, 분포 꼬리 비정형 거래",
    "supervised": "감사인 과거 검토 라벨과 유사한 패턴 (라벨 확보 후 활성)",
    "transformer": "적요·거래처·계정·사용자 범주 조합의 문맥 이상",
    "sequence": "승인-기표-수정-상계 등 전표 흐름 순서 이상",
    "stacking": "여러 영역이 동시에 약하게 반응한 종합 후보",
}

_DORMANT_ACTIVATION_KR: dict[str, str] = {
    "supervised": "감사인 검토 라벨 또는 신뢰 가능한 ground truth가 충분할 때 활성화",
    "transformer": "라벨과 텍스트/범주 데이터 품질이 충분할 때 활성화",
    "sequence": "전표 변경 이력, 승인 흐름, 이벤트 시퀀스가 들어오면 활성화",
    "stacking": "활성 분석 영역의 안정적인 출력이 누적되면 활성화",
}

_DORMANT_REASON_KR: dict[str, str] = {
    "low_signal_fallback": "학습 신호 부족",
    "d047_gated": "전표 순서 데이터 필요",
    "base_family_outputs_required": "기본 분석 영역 출력 누적 필요",
}

_METRIC_INTERPRETATION_KR: dict[str, str] = {
    "rule_proxy_score": "룰 기반 근사 점수 (정확도 아님)",
    "ECDF q95 tail review count, rule_proxy_score label only": ("ECDF 꼬리 검토 후보 (라벨 아님)"),
}

_PHASE2_FAMILY_OVERVIEW_CSS = """
<style>
.p2-focus-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
                 gap:0.6rem; margin:0.25rem 0 0.8rem; }
.p2-focus-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px;
                 padding:0.8rem 0.95rem; border-left:4px solid var(--accent,#9CA3AF);
                 box-shadow:0 1px 2px rgba(15,23,42,0.04); }
.p2-focus-rank { color:#6B7280; font-size:0.72rem; font-weight:600; margin-bottom:0.25rem; }
.p2-focus-title { color:#111827; font-size:0.98rem; font-weight:700; margin-bottom:0.3rem; }
.p2-focus-purpose { color:#374151; font-size:0.78rem; line-height:1.45; margin-bottom:0.55rem; }
.p2-focus-meta { display:flex; flex-wrap:wrap; gap:0.35rem; }
.p2-focus-chip { background:#F3F4F6; color:#374151; border-radius:999px;
                 padding:2px 8px; font-size:0.7rem; font-weight:600; }
</style>
"""

_FAMILY_CARD_CSS = """
<style>
.p2-family-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
                  gap:0.55rem; margin:0.25rem 0 0.8rem; }
.p2-family-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:10px;
                  padding:0.75rem 0.95rem; border-left:3px solid var(--accent,#E5E7EB);
                  box-shadow:0 1px 2px rgba(15,23,42,0.04); }
.p2-family-title { color:#111827; font-size:0.95rem; font-weight:600;
                   margin-bottom:0.2rem; }
.p2-family-title-en { color:#9CA3AF; font-size:0.7rem; font-weight:500;
                      margin-left:4px; }
.p2-family-sub { color:#6B7280; font-size:0.72rem; margin-bottom:0.55rem; }
.p2-family-stat-row { display:flex; align-items:baseline; gap:0.5rem; }
.p2-family-stat-value { color:#111827; font-size:1.4rem; font-weight:700;
                        letter-spacing:-0.02em; line-height:1.1; }
.p2-family-stat-unit { font-size:0.78rem; font-weight:500; color:#6B7280; margin-left:2px; }
.p2-family-stat-label { color:#6B7280; font-size:0.7rem; font-weight:500; }
.p2-family-detail { color:#4B5563; font-size:0.74rem; margin-top:0.55rem;
                    border-top:1px dashed #F1F3F5; padding-top:0.4rem; }
.p2-family-note { color:#9CA3AF; font-size:0.7rem; margin-top:0.3rem; font-style:italic; }
</style>
"""


def _build_family_card_html(family: str, payload: dict) -> str:
    """단일 active family 카드 HTML."""
    accent = _FAMILY_ACCENT.get(family, "#9CA3AF")
    label_kr = _FAMILY_LABELS_KR.get(family, family)
    hint = _FAMILY_HINT_KR.get(family, "")

    if family == "unsupervised":
        stat_value = int(payload.get("high_count_q95") or 0)
        stat_label = "검토 후보 (q95)"
    else:
        distribution = payload.get("score_distribution") or {}
        stat_value = int(distribution.get("nonzero_count") or 0)
        stat_label = "신호 케이스"

    sub_lookup = payload.get("sub_detectors") or {}
    family_subs = [code for fam, code, _label in SUB_DETECTORS if fam == family]
    active_subs = [
        code for code in family_subs if int((sub_lookup.get(code) or {}).get("hit_count") or 0) > 0
    ]
    total_subs = len(family_subs)

    metric_raw = str(
        payload.get("metric_interpretation") or FAMILY_INTERPRETATIONS.get(family, "-")
    )
    metric_text = _METRIC_INTERPRETATION_KR.get(metric_raw, metric_raw)

    return (
        f"<div class='p2-family-card' style='--accent:{accent};'>"
        f"<div class='p2-family-title'>{label_kr}"
        f"<span class='p2-family-title-en'>({family})</span></div>"
        f"<div class='p2-family-sub'>{hint}</div>"
        f"<div class='p2-family-stat-row'>"
        f"<div class='p2-family-stat-value'>{stat_value:,}"
        f"<span class='p2-family-stat-unit'>건</span></div>"
        f"<div class='p2-family-stat-label'>{stat_label}</div>"
        f"</div>"
        f"<div class='p2-family-detail'>활성 세부 탐지 "
        f"<b>{len(active_subs)}</b> / {total_subs} 개</div>"
        f"<div class='p2-family-note'>{metric_text}</div>"
        f"</div>"
    )


def _build_subdetector_kr_frame(partition_summary: dict | None) -> pd.DataFrame:
    """세부 탐지 한국어 컬럼: 분석 영역 / 코드 / 내용 / 적중 / 비고."""
    families_payload = (partition_summary or {}).get("families") or {}
    rows: list[dict] = []
    for family, code, label in SUB_DETECTORS:
        family_payload = families_payload.get(family) or {}
        sub_payload = (family_payload.get("sub_detectors") or {}).get(code) or {}
        hit = int(sub_payload.get("hit_count") or 0)
        note = "-"
        rows.append(
            {
                "분석 영역": _FAMILY_LABELS_KR.get(family, family),
                "코드": code,
                "내용": str(sub_payload.get("label") or label),
                "적중 건수": hit,
                "비고": note,
            }
        )
    return pd.DataFrame(rows)


def _build_dormant_family_frame(
    snapshot: dict | None,
    partition_summary: dict | None,
) -> pd.DataFrame:
    """대기 중인 4개 분석 영역 — 한국어 사유 표."""
    contract = (snapshot or {}).get("inference_contract") or {}
    model_versions = contract.get("model_versions") or {}
    rows: list[dict] = []
    for family in DORMANT_FAMILIES:
        version_payload = model_versions.get(family) or {}
        rows.append(
            {
                "분석 영역": _FAMILY_LABELS_KR.get(family, family),
                "영역 코드": family,
                "보류 사유": _DORMANT_REASON_KR.get(
                    DORMANT_REASONS.get(family, "-"),
                    DORMANT_REASONS.get(family, "-"),
                ),
                "기준 metric": FAMILY_METRICS.get(family, "-"),
                "모델 버전": str(version_payload.get("model_version") or "-"),
            }
        )
    return pd.DataFrame(rows)


def _render_phase2_current_state(result: PipelineResult | None) -> None:
    cards = _build_phase2_provenance_cards(result)
    if not cards:
        return
    columns = st.columns(len(cards))
    for column, (label, value) in zip(columns, cards):
        column.metric(label, value)


def _render_phase2_state_header(
    user_state: str,
    snapshot: dict | None,
    result: PipelineResult | None,
) -> None:
    """상단 상태 카드만 표시 (partition selector 는 phase2 결과 탭에서 노출하지 않음)."""
    cards = _build_phase2_state_cards(user_state, snapshot, result)
    columns = st.columns(len(cards))
    for column, (label, value) in zip(columns, cards):
        column.metric(label, value)


def _render_phase2_action_panel(
    user_state: str,
    prep_result,
    snapshot: dict | None,
    partition: str,
) -> None:
    if prep_result is None:
        st.info("분석 준비 결과가 없어서 Phase 2 학습/추론을 실행할 수 없습니다.")
        return
    if st.session_state.get(KEY_LOADED_FROM_DB):
        st.info("DB에서 불러온 결과입니다. 저장된 provenance만 표시합니다.")
        return
    if user_state == "not_trained":
        st.info("저장된 모델 부재: 먼저 Phase 2 학습 리포트를 생성하세요.")
        if st.button("Phase 2 학습 실행", type="primary", key="run_phase2_training"):
            _start_phase2_training()
        return
    st.success("저장된 학습 기준이 있습니다. 추론을 바로 실행하거나 재학습할 수 있습니다.")
    run_analysis_clicked = False
    rerun_training_clicked = False
    with st.container(horizontal=True, gap="small"):
        run_analysis_clicked = st.button(
            "저장된 모델로 Phase 2 추론",
            type="primary",
            key="run_phase2_action_panel",
        )
        rerun_training_clicked = st.button(
            "Phase 2 재학습",
            key="rerun_phase2_training_action_panel",
        )
    if run_analysis_clicked:
        _start_phase2_analysis(partition)
    if rerun_training_clicked:
        _start_phase2_training()
    if snapshot and snapshot.get("report_path"):
        st.caption(f"사용 report: {snapshot.get('report_path')}")


def _resolve_phase2_overlays_from_state() -> list[dict]:
    """session_state 의 phase2 result 에서 overlay 리스트 추출."""
    from dashboard._state import KEY_PHASE2_RESULT

    state = st.session_state if hasattr(st, "session_state") else {}
    phase2_result = state.get(KEY_PHASE2_RESULT) if hasattr(state, "get") else None
    overlays = getattr(phase2_result, "phase2_case_overlays", None)
    return list(overlays) if isinstance(overlays, list) else []


def _resolve_family_roles_from_snapshot(
    snapshot: dict | None,
    partition_summary: dict | None,
) -> dict[str, str]:
    """training snapshot 또는 partition summary 에서 family role dict 추출.

    1순위: snapshot.training_report.metadata.family_diagnostics.roles (Phase B pin).
    2순위: partition_summary.families[*].ui_meta.role (legacy).
    """
    if isinstance(snapshot, dict):
        report = snapshot.get("training_report") or {}
        metadata = report.get("metadata") or {}
        diagnostics_block = metadata.get("family_diagnostics") or {}
        roles = diagnostics_block.get("roles")
        if isinstance(roles, dict) and roles:
            return {str(k): str(v) for k, v in roles.items()}
    if isinstance(partition_summary, dict):
        families_payload = partition_summary.get("families") or {}
        fallback = {
            family: str((payload or {}).get("ui_meta", {}).get("role") or "active-ranker")
            for family, payload in families_payload.items()
            if isinstance(payload, dict)
        }
        if fallback:
            return fallback
    return {}


def _render_training_snapshot_summary(snapshot: dict | None = None) -> None:
    if snapshot is None:
        snapshot = _load_current_training_snapshot()
    if not snapshot:
        st.caption("저장된 Phase 2 모델 기준이 없습니다.")
        return
    st.markdown("**저장된 Phase 2 모델 기준**")
    st.caption(f"기준 ID: {snapshot.get('report_id') or '-'}")
    frame = _build_promoted_model_frame(snapshot)
    if not frame.empty:
        st.dataframe(frame, width="stretch", hide_index=True)
        caption = _build_unsupervised_metric_caption(snapshot)
        if caption:
            st.caption(caption)
    plan_summary = _build_preprocessing_plan_summary(snapshot)
    if plan_summary:
        st.caption(plan_summary)
    diagnostics = _build_phase2_training_diagnostics(snapshot)
    if not diagnostics.empty:
        st.dataframe(diagnostics, width="stretch", hide_index=True)


def _load_current_training_snapshot() -> dict | None:
    from dashboard._state import KEY_COMPANY_CONTEXT
    from src.services.phase2_inference_service import load_latest_phase2_training_snapshot

    return load_latest_phase2_training_snapshot(st.session_state.get(KEY_COMPANY_CONTEXT))


def _determine_phase2_user_state(snapshot: dict | None, result: PipelineResult | None) -> str:
    if result is not None:
        return "inference_complete"
    if snapshot:
        return "training_report_available"
    return "not_trained"


def _build_phase2_state_cards(
    user_state: str,
    snapshot: dict | None,
    result: PipelineResult | None,
) -> list[tuple[str, str]]:
    labels = {
        "not_trained": "Not trained",
        "training_report_available": "Training report available",
        "inference_complete": "Inference complete",
    }
    contract = (
        getattr(result, "phase2_inference_contract", None)
        if result is not None
        else (snapshot or {}).get("inference_contract")
    ) or {}
    if not contract.get("required_models") and snapshot:
        contract = (snapshot or {}).get("inference_contract") or contract
    report_id = (
        getattr(result, "phase2_training_report_id", None)
        if result is not None
        else (snapshot or {}).get("report_id")
    )
    return [
        ("상태", labels.get(user_state, user_state)),
        ("학습 리포트", str(report_id or "-")),
        ("추론 방식", _format_inference_mode(getattr(result, "phase2_inference_mode", None))),
        ("계약 분석 영역", str(len(contract.get("required_models") or []))),
    ]


# ── P6: Phase 2 signal source status ──────────────────────────


# Why: 분석 영역 차트/카드는 현재 회사 추론 결과(runtime_company_scoped) 만 사용한다.
#      추론 결과가 없으면 missing_reference 로 표시.
class _Phase2SignalSourceStatus:
    RUNTIME_COMPANY_SCOPED = "runtime_company_scoped"
    MISSING_REFERENCE = "missing_reference"


def _resolve_phase2_signal_source_status(
    partition_summary: dict | None,
) -> tuple[str, str]:
    """partition_summary 에서 source status / 한국어 메시지 반환.

    payload 가 None 이면 missing_reference. ``_source`` key 가 있으면 그것을 우선 사용.
    """
    if partition_summary is None:
        return (
            _Phase2SignalSourceStatus.MISSING_REFERENCE,
            "Phase 2 추론 결과가 없습니다.",
        )
    source = partition_summary.get("_source") or {}
    status = str(source.get("status") or _Phase2SignalSourceStatus.RUNTIME_COMPANY_SCOPED)
    message = str(source.get("message") or "현재 회사 Phase 2 추론 결과 기반")
    return status, message


def _load_phase2_partition_summary(partition: str) -> dict | None:
    """현재 회사 추론 결과(``KEY_PHASE2_RESULT``) 로부터 partition summary 생성.

    Why: 글로벌 정적 V7 fixed3 artifact 가 아니라, 사용자가 방금 돌린 회사 scoped
    Phase 2 추론 결과를 사용한다. 결과가 없으면 None 반환 (정적 fallback 제거 —
    사용자 요구).
    """
    from dashboard._state import KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    if phase2_result is None:
        return None
    return _build_company_partition_summary(phase2_result, partition)


# Why: AuditPipeline.redetect 의 track_name → reference family 매핑. aggregator 와
#      동일 정의를 재사용하면 import 순환 위험이 있어 같은 값만 복제. 변경 시 두 곳을
#      동시에 갱신할 것 (src/services/phase2_case_family_aggregator.py:_TRACK_TO_FAMILY).
_PHASE2_TRACK_TO_FAMILY: dict[str, str] = {
    "ml_unsupervised": "unsupervised",
    "timeseries": "timeseries",
}


def _build_company_partition_summary(phase2_result, partition: str) -> dict | None:
    """phase2 추론 결과로부터 partition summary 형식의 dict 를 생성.

    Why: 분석 영역 차트·KPI 가 회사 데이터 기반 수치를 보여주도록 한다. 출력 스키마는
    기존 정적 artifact 와 호환 (families.*.rows_scored / score_distribution / high_count_q95 /
    sub_detectors / documents / _source).

    데이터 소스 우선순위:
        1) ``phase2_result.results`` (DetectionResult 객체들) — 갓 분석된 메모리 상태.
           score 분포 / q95·q99 / sub_detector hit_count 까지 정확히 산출.
        2) ``phase2_result.phase2_case_overlays`` — DB restore 후 detection_results 가
           복원되지 않을 때 fallback. overlay 의 ``family_contributions`` 로부터
           family 별 적중 case 수 / sub_detector 카운트만 복원 (q95/q99 는 정보 부족).
    """
    import numpy as np
    import pandas as pd

    data = getattr(phase2_result, "data", None)
    featured = getattr(phase2_result, "featured_data", None)
    base_df = featured if isinstance(featured, pd.DataFrame) else data
    detection_results = list(getattr(phase2_result, "results", None) or [])
    overlays = list(getattr(phase2_result, "phase2_case_overlays", None) or [])
    if (base_df is None or base_df.empty) and not overlays:
        return None

    requested = str(partition)
    df = base_df if base_df is not None else pd.DataFrame()
    if not df.empty and requested != "전체" and "fiscal_year" in df.columns:
        try:
            year_int = int(requested)
        except ValueError:
            year_int = None
        if year_int is not None:
            filtered = df[df["fiscal_year"].astype("Int64") == year_int]
            if not filtered.empty:
                df = filtered
    rows = int(len(df))
    if not df.empty and "document_id" in df.columns:
        doc_series = pd.Series(df["document_id"]).astype(str)
        documents = int(doc_series.nunique())
    else:
        documents = rows

    families: dict[str, dict] = {}
    target_index = df.index
    for result in detection_results:
        family = _PHASE2_TRACK_TO_FAMILY.get(getattr(result, "track_name", ""))
        if not family:
            continue
        raw_scores = getattr(result, "scores", None)
        if raw_scores is None:
            continue
        scores_series = pd.Series(pd.to_numeric(raw_scores, errors="coerce"))
        scores = scores_series.reindex(target_index).fillna(0.0).astype(float)
        nonzero_count = int((scores > 0).sum())
        family_payload = families.setdefault(
            family,
            {
                "family": family,
                "sub_detectors": {},
                "rows_scored": 0,
                "score_distribution": {"nonzero_count": 0},
            },
        )
        family_payload["rows_scored"] = max(int(family_payload["rows_scored"]), int(len(scores)))
        family_payload["score_distribution"]["nonzero_count"] += nonzero_count

        if family == "unsupervised" and len(scores) > 0:
            positive = pd.Series(scores[scores > 0])
            q95 = float(np.quantile(positive.to_numpy(), 0.95)) if len(positive) > 0 else 0.0
            q99 = float(np.quantile(positive.to_numpy(), 0.99)) if len(positive) > 0 else 0.0
            family_payload["high_count_q95"] = int((scores >= q95).sum()) if q95 > 0 else 0
            family_payload["high_count_q99"] = int((scores >= q99).sum()) if q99 > 0 else 0

        details = getattr(result, "details", None)
        if isinstance(details, pd.DataFrame) and not details.empty:
            details = details.reindex(target_index)
            for column in details.columns:
                code = str(column)
                column_numeric = pd.Series(pd.to_numeric(details[column], errors="coerce")).fillna(
                    0.0
                )
                hit_count = int((column_numeric > 0).sum())
                sub_entry = family_payload["sub_detectors"].setdefault(
                    code,
                    {"label": code, "hit_count": 0},
                )
                sub_entry["hit_count"] = int(sub_entry.get("hit_count", 0)) + hit_count

    # Why: DB restore 직후엔 detection_results 가 비어있다 (raw DetectionResult 객체는
    #      DB 에 영속화되지 않음). overlay 본체는 engagement 폴더에서 복원되므로
    #      family_contributions 로 family summary 를 재구성한다.
    if not families and overlays:
        for overlay in overlays:
            for entry in overlay.get("family_contributions") or []:
                family = str(entry.get("family") or "")
                if family not in _PHASE2_TRACK_TO_FAMILY.values():
                    continue
                family_payload = families.setdefault(
                    family,
                    {
                        "family": family,
                        "sub_detectors": {},
                        "rows_scored": 0,
                        "score_distribution": {"nonzero_count": 0},
                    },
                )
                family_payload["score_distribution"]["nonzero_count"] += 1
                family_payload["rows_scored"] = max(
                    int(family_payload["rows_scored"]),
                    int(family_payload["score_distribution"]["nonzero_count"]),
                )
                for sub in entry.get("sub_detectors") or []:
                    code = str(sub.get("code") or sub.get("label") or sub)
                    if not code:
                        continue
                    sub_entry = family_payload["sub_detectors"].setdefault(
                        code,
                        {"label": code, "hit_count": 0},
                    )
                    sub_entry["hit_count"] = int(sub_entry.get("hit_count", 0)) + 1

    if not families:
        return None

    return {
        "year": requested,
        "rows": rows,
        "documents": documents,
        "families": families,
        "_source": {
            "status": _Phase2SignalSourceStatus.RUNTIME_COMPANY_SCOPED,
            "message": "현재 회사 Phase 2 추론 결과 기반",
            "is_static_reference": False,
            "missing_years": [],
            "partition": requested,
        },
    }


def _render_phase2_signal_source_caption(partition_summary: dict | None) -> None:
    """분석 영역 차트/카드 데이터의 출처를 사용자에게 명시.

    Why: 현재 시스템은 회사 scoped phase 2 inference summary 가 없어 글로벌 정적
    artifact 를 보여준다. 사용자가 "내 회사 분석 결과" 로 오해하지 않게 source status
    를 항상 노출한다. ``runtime_company_scoped`` 일 때만 caption 생략.
    """
    status, message = _resolve_phase2_signal_source_status(partition_summary)
    if status == _Phase2SignalSourceStatus.RUNTIME_COMPANY_SCOPED:
        return
    if status == _Phase2SignalSourceStatus.MISSING_REFERENCE:
        st.caption(message)
        return
    # static_reference_preview / mixed_reference 는 사용자가 "내 회사 결과" 로 오해할
    # 가능성이 가장 크다 — warning 톤으로 노출.
    st.warning(f"⚠️ {message}")


def _build_phase2_provenance_cards(result: PipelineResult | None) -> list[tuple[str, str]]:
    if result is None:
        return []
    contract = getattr(result, "phase2_inference_contract", None) or {}
    return [
        ("모델 기준", str(getattr(result, "phase2_training_report_id", None) or "-")),
        ("실행 방식", _format_inference_mode(getattr(result, "phase2_inference_mode", None))),
        ("사용 후보", str(len(contract.get("required_models") or []))),
        ("확정 모델", str(len(contract.get("promoted_versions") or {}))),
    ]


def _build_promoted_model_frame(snapshot: dict | None) -> pd.DataFrame:
    if not snapshot:
        return pd.DataFrame(
            columns=[
                "분석 기준",
                "버전",
                "세부 점검",
                "metric_name",
                "metric_value",
                "evaluation_policy",
            ]
        )
    contract = snapshot.get("inference_contract") or {}
    required = [str(model) for model in contract.get("required_models") or []]
    versions = dict(contract.get("promoted_versions") or {})
    sub_detectors = dict(contract.get("family_sub_detectors") or {})
    promoted = {
        str(model.get("model_name")): model
        for model in list(snapshot.get("promoted_models") or [])
        if isinstance(model, dict)
    }
    unsup_policy = (snapshot.get("promotion_policy") or {}).get("unsupervised_metric_policy") or {}
    rows = [
        {
            "분석 기준": model,
            "버전": str(versions.get(model, "-")),
            "세부 점검": ", ".join(str(item) for item in sub_detectors.get(model, [])) or "-",
            "metric_name": str(promoted.get(model, {}).get("metric_name") or "-"),
            "metric_value": _format_metric_value(promoted.get(model, {}).get("metric_value")),
            "evaluation_policy": _format_model_evaluation_policy(
                model,
                promoted.get(model, {}),
                unsup_policy,
            ),
        }
        for model in required
    ]
    return pd.DataFrame(rows)


def _build_unsupervised_metric_caption(snapshot: dict | None) -> str:
    if not snapshot:
        return ""
    metric_names = {
        str(model.get("metric_name"))
        for model in list(snapshot.get("promoted_models") or [])
        if isinstance(model, dict)
    }
    if "unsupervised_selection_score" not in metric_names:
        return ""
    return (
        "unsupervised_selection_score is a ranking/calibration proxy for review "
        "prioritization, not fraud accuracy, precision, recall, or F1."
    )


def _build_preprocessing_plan_summary(snapshot: dict | None) -> str:
    if not snapshot:
        return ""
    plan = snapshot.get("preprocessing_plan") or {}
    metadata = plan.get("metadata") or {}
    decisions = list(plan.get("decisions") or [])
    excluded = sum(1 for decision in decisions if decision.get("action") == "exclude")
    profile_mode = (
        f"sampled({int(plan.get('profile_sample_size')):,})"
        if plan.get("profile_sampled") and plan.get("profile_sample_size")
        else "full"
    )
    return (
        "Preprocessing plan: "
        f"rows={plan.get('row_count', '-')} | profile={profile_mode} | "
        f"decisions={metadata.get('decision_count', len(decisions))} | "
        f"excluded={excluded}"
    )


def _build_phase2_training_diagnostics(snapshot: dict | None) -> pd.DataFrame:
    if not snapshot:
        return pd.DataFrame(
            columns=["split_policy", "profile_cap", "schema_hash", "reliability_warnings"]
        )
    trials = list(snapshot.get("leaderboard") or [])
    first_trial = next((trial for trial in trials if isinstance(trial, dict)), {})
    split = first_trial.get("metadata", {}).get("train_calibration_split", {})
    plan = snapshot.get("preprocessing_plan") or {}
    warnings = []
    for trial in trials:
        metric = (trial.get("metadata") or {}).get("unsupervised_metric") or {}
        warnings.extend(metric.get("reliability_warnings") or [])
    schema_hash = snapshot.get("metadata", {}).get("schema_hash") or snapshot.get("schema_hash")
    return pd.DataFrame(
        [
            {
                "split_policy": split.get("split_strategy") or "-",
                "profile_cap": plan.get("profile_sample_size") or "-",
                "schema_hash": schema_hash or "-",
                "reliability_warnings": ", ".join(sorted(set(warnings))) or "-",
            }
        ]
    )


def _render_prep_metrics(prep_result) -> None:
    data = prep_result.featured_data if prep_result.featured_data is not None else prep_result.data
    c1, c2, c3 = st.columns(3)
    c1.metric("분석 행 수", f"{len(data):,}")
    c2.metric("분석 컬럼 수", f"{len(data.columns):,}")
    c3.metric("준비 경고", f"{len(prep_result.warnings):,}")


def _render_status_grid(result: PipelineResult) -> None:
    statuses = result.detector_statuses or []
    executed = sum(1 for row in statuses if row.get("run_status") == "executed")
    skipped = sum(1 for row in statuses if row.get("run_status") == "skipped")
    experimental = sum(1 for row in statuses if row.get("maturity") == "experimental")
    c1, c2, c3 = st.columns(3)
    c1.metric("실행 항목", executed)
    c2.metric("건너뜀", skipped)
    c3.metric("실험 단계", experimental)


def _render_performance_report(result: PipelineResult) -> None:
    report = result.performance_report
    if report is None:
        return

    st.markdown("**탐지 성능 요약**")
    cards = _build_performance_cards(report)
    if cards:
        columns = st.columns(len(cards))
        for column, (label, value) in zip(columns, cards):
            column.metric(label, value)

    rule_frame = _build_performance_rule_frame(report)
    if not rule_frame.empty:
        st.dataframe(rule_frame, width="stretch", hide_index=True)


def _build_performance_cards(report: PerformanceReport) -> list[tuple[str, str]]:
    cards = [
        ("Flagged Docs", f"{report.flagged_docs:,}"),
        ("High Risk Docs", f"{report.high_risk_docs:,}"),
        ("High Risk Ratio", _format_pct(report.high_risk_ratio)),
        ("False Positives", f"{report.false_positive_docs:,}"),
        ("Confirmed Issues", f"{report.confirmed_issue_docs:,}"),
    ]
    if _has_ground_truth_metrics(report) and report.precision is not None:
        cards.append(("Precision", _format_pct(report.precision)))
    if _has_ground_truth_metrics(report) and report.recall is not None:
        cards.append(("Recall", _format_pct(report.recall)))
    if _has_ground_truth_metrics(report) and report.f1 is not None:
        cards.append(("F1", _format_pct(report.f1)))
    return cards


def _build_performance_rule_frame(report: PerformanceReport) -> pd.DataFrame:
    rows = [
        {
            "rule_group": get_track_display_label(metric.track_name, metric.rule_code),
            "rule_code": metric.rule_code,
            "status": metric.evaluation_status,
            "note": metric.evaluation_reason or "-",
            "objective": metric.rule_objective or "-",
            "broad_fraud_type": metric.broad_fraud_type or "-",
            "expected_coverage": metric.expected_coverage or "-",
            "label_docs": metric.label_docs,
            "flagged_docs": metric.flagged_docs,
            "tp_docs": metric.tp_docs,
            "fp_docs": metric.fp_docs,
            "fn_docs": metric.fn_docs,
            "overlap_docs": metric.overlap_docs,
            "standalone_docs": metric.standalone_docs,
            "review_queue_docs": metric.review_queue_docs,
            "precision": (
                _format_pct(metric.precision) if _has_ground_truth_metrics(report) else "-"
            ),
            "recall": _format_pct(metric.recall) if _has_ground_truth_metrics(report) else "-",
            "f1": _format_pct(metric.f1) if _has_ground_truth_metrics(report) else "-",
        }
        for metric in report.rule_metrics
    ]
    return pd.DataFrame(rows)


def _build_model_evaluation_frame(models: list[ModelMetadata]) -> pd.DataFrame:
    rows = []
    for model in models:
        rows.append(
            {
                "model": model.model_name,
                "version": model.version,
                "eval_policy": model.evaluation_policy or "-",
                "eval_grade": model.evaluation_confidence or "-",
                "train_years": _format_years(model.train_years),
                "test_years": _format_years(model.test_years),
                "mean_f1": model.mean_f1,
            }
        )
    return pd.DataFrame(rows)


def _build_feature_quality_frame(models: list[ModelMetadata]) -> pd.DataFrame:
    rows = []
    for model in models:
        profile = model.feature_quality_profile or {}
        family_statuses = profile.get("family_statuses") or {}
        active_families = [name for name, config in family_statuses.items() if config.get("active")]
        ablation_plan = profile.get("ablation_plan") or []
        rows.append(
            {
                "model": model.model_name,
                "version": model.version,
                "persona_normalized": "yes" if profile.get("normalized_persona") else "no",
                "unknown_persona_count": int(profile.get("unknown_persona_count") or 0),
                "sparse_dropped": ", ".join(profile.get("sparse_dropped_columns") or []),
                "active_families": ", ".join(active_families),
                "ablation_variants": ", ".join(
                    str(item.get("variant")) for item in ablation_plan if item.get("variant")
                ),
            }
        )
    return pd.DataFrame(rows)


def _render_track_status(result: PipelineResult) -> None:
    rows = list(result.detector_statuses or [])
    if not rows:
        st.caption("이번 배치에는 추가 탐지 상태 정보가 없습니다.")
        return

    df = pd.DataFrame(rows)
    if "activation_requirements" in df.columns:
        df["activation_requirements"] = df["activation_requirements"].apply(
            lambda value: ", ".join(value) if isinstance(value, list) else (value or "-")
        )
    if "default_enabled" in df.columns:
        df["default_enabled"] = df["default_enabled"].map({True: "on", False: "off"})
    if "reason" in df.columns:
        df["reason"] = df["reason"].fillna("-")
    if "track_name" in df.columns:
        df["rule_group"] = df["track_name"].map(get_track_display_label)

    visible_cols = [
        col
        for col in [
            "rule_group",
            "display_name",
            "maturity",
            "default_enabled",
            "run_status",
            "reason",
            "flagged_docs",
            "rules_run",
            "elapsed_sec",
            "activation_requirements",
        ]
        if col in df.columns
    ]
    st.dataframe(df[visible_cols], width="stretch", hide_index=True)


def _start_phase2_analysis(partition: str = "전체") -> None:
    """Run Phase 2 inference from the empty-result placeholder.

    Why: KEY_TOP_LEVEL_NAV 는 widget key — _consume_pending_page 가 다음 run 의
         widget 렌더 전에 KEY_PENDING_RESULT_TAB 를 옮긴다.
    """
    from src.services.phase2_inference_service import run_phase2_inference_analysis

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2

    with st.spinner("Phase 2 추가 분석 실행 중..."):
        try:
            run_phase2_inference_analysis(st.session_state, partition=partition)
        except Exception as e:
            st.error(f"Phase 2 추가 분석 실패: {e}")
            return
    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2
    st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE2
    st.rerun()


def _start_phase2_training() -> None:
    """Run Phase 2 training and keep the user on the Phase 2 tab."""
    from src.services.phase2_training_service import run_phase2_training_analysis

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2

    with st.spinner("Phase 2 모델 기준 준비 중..."):
        try:
            report = run_phase2_training_analysis(st.session_state)
        except Exception as e:
            import traceback

            st.error(f"Phase 2 모델 기준 준비 실패: {e}")
            st.exception(e)
            st.code(traceback.format_exc(), language="text")
            return
    st.session_state[KEY_PHASE2_TRAINING_REPORT_ID] = report.report_id
    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2
    st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE2
    st.rerun()


def _start_phase2_pipeline(*, partition: str | None = None, train: bool = True) -> None:
    """Phase2 학습 → 추론을 한 흐름으로 실행 + 단계별 spinner/터미널 timing.

    Why: 사용자 요청 — 학습/추론 두 단계를 단일 버튼으로 통합. spinner는 단계별 라벨로
         예상 소요 시간을 안내한다. 터미널에는 phase1과 동일한 `[TIMING] phase2.<stage>: %.1fs`
         포맷으로 로그를 남겨 retrospective 비교가 가능하다.
    """
    import time
    import traceback

    from src.services._phase_timing import log_timing, now_str
    from src.services.phase2_inference_service import run_phase2_inference_analysis
    from src.services.phase2_training_service import run_phase2_training_analysis

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2
    total_t0 = time.perf_counter()
    total_ts0 = now_str()
    train_elapsed = 0.0

    if train:
        with st.spinner("학습 중... (약 5분 소요)"):
            t0 = time.perf_counter()
            ts0 = now_str()
            try:
                report = run_phase2_training_analysis(st.session_state)
            except Exception as e:
                train_elapsed = time.perf_counter() - t0
                log_timing("phase2.training_failed", train_elapsed, start_ts=ts0)
                st.error(f"Phase 2 학습 실패: {e}")
                st.exception(e)
                st.code(traceback.format_exc(), language="text")
                return
            train_elapsed = time.perf_counter() - t0
            log_timing("phase2.training", train_elapsed, start_ts=ts0)
        st.session_state[KEY_PHASE2_TRAINING_REPORT_ID] = report.report_id

    with st.spinner("추론 중... (약 1분 소요)"):
        t0 = time.perf_counter()
        ts0 = now_str()
        try:
            run_phase2_inference_analysis(st.session_state, partition=partition)
        except Exception as e:
            infer_elapsed = time.perf_counter() - t0
            log_timing("phase2.inference_failed", infer_elapsed, start_ts=ts0)
            st.error(f"Phase 2 추론 실패: {e}")
            st.exception(e)
            st.code(traceback.format_exc(), language="text")
            return
        infer_elapsed = time.perf_counter() - t0
        log_timing("phase2.inference", infer_elapsed, start_ts=ts0)

    total_elapsed = time.perf_counter() - total_t0
    log_timing("phase2.total", total_elapsed, start_ts=total_ts0)
    if train:
        st.toast(
            f"학습 {train_elapsed:.1f}s + 추론 {infer_elapsed:.1f}s = 총 {total_elapsed:.1f}s",
            icon="✅",
        )
    else:
        st.toast(f"추론 {infer_elapsed:.1f}s", icon="✅")

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2
    st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE2
    st.rerun()


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _format_metric_value(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _format_model_evaluation_policy(
    model_name: str,
    promoted: dict,
    unsup_policy: dict,
) -> str:
    metric_name = str(promoted.get("metric_name") or "")
    if model_name == "unsupervised" or metric_name == "unsupervised_selection_score":
        return str(
            unsup_policy.get("interpretation") or "ranking/calibration proxy, not fraud accuracy"
        )
    return str(promoted.get("evaluation_policy") or "-")


def _has_ground_truth_metrics(report: PerformanceReport) -> bool:
    return str(getattr(report, "source_kind", "")) == "ground_truth"


def _format_inference_mode(value: str | None) -> str:
    labels = {
        "training_contract": "저장된 기준 사용",
        "untrained_contract_only": "모델 기준 없음",
        "cold_start_bootstrap": "임시 기준 사용",
    }
    if value is None:
        return "-"
    return labels.get(str(value), str(value))


def _format_years(years) -> str:
    if not years:
        return "-"
    return ", ".join(str(year) for year in years)
