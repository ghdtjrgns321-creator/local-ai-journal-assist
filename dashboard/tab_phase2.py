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
from dashboard.components.phase2_family_lanes import render_lane_view
from dashboard.components.phase2_family_matrix import (
    ACTIVE_FAMILIES,
    DORMANT_FAMILIES,
    DORMANT_REASONS,
    FAMILY_INTERPRETATIONS,
    FAMILY_METRICS,
    render_family_matrix,
)
from dashboard.components.phase2_leaderboard_view import render_leaderboard_view
from dashboard.components.phase2_subdetector_grid import (
    SUB_DETECTORS,
    render_subdetector_grid,
)
from src.detection.constants import get_track_display_label
from src.services.review_band_policy import rank_band_caption, rank_percentile_band

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

    sub_tabs = st.tabs(["전체 요약", "분석 영역별", "위험 신호별", "통계결과"])
    with sub_tabs[0]:
        _render_overview_tab(user_state, snapshot, result, partition, partition_summary)
    with sub_tabs[1]:
        _render_phase2_analysis_area_tab(snapshot, partition, partition_summary)
    with sub_tabs[2]:
        _render_phase2_risk_signal_tab(snapshot, partition, partition_summary)
    with sub_tabs[3]:
        _render_phase2_stats_tab(snapshot, partition, partition_summary)


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
         모델 수치와 case-overlay 상태는 모델 기준/검토 Lane으로 밀고, 전체 요약은
         분석 영역 해석과 현재 반응도에 집중한다.
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
    #      모델 기준 탭까지 가지 않고도 확인할 수 있게 한다.
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
    """전체 요약 / 검토 Lane 빈 상태 표시 결정.

    Attributes:
        state_id: 분류 (phase2_not_run / phase1_basis_unavailable /
            overlay_missing / valid_no_hit / available).
        severity: streamlit 알림 톤 (info / warning / error / caption).
        title: 안내 1줄 (필수).
        body: 부가 설명 (1~2 문장).
        next_action_label: 사용자 행동 안내 (없으면 None).
        show_charts: 활성 분석 분포 차트를 그릴지.
        show_lanes: 검토 Lane 표를 그릴지.
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

    Why: KPI 카드 / Active Distribution 차트 / 검토 Lane 이 같은 분기를 반복하지 않게
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
                "추론 완료 후 케이스별 추가 신호와 검토 Lane 을 볼 수 있습니다."
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
        # R-M1: valid_no_hit 은 Phase 2 Lane 에 표시할 적중 case 가 없는 상태다.
        # show_lanes=True 로 두고 Lane 탭에서 fallback 표를 띄우지 않을 거면 사용자에게
        # 잘못된 기대(검토 Lane 에 무언가 보임)를 준다. Phase 1 결과 탭으로 안내하는
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
    "relational": "관계망",
    "duplicate": "중복",
    "intercompany": "관계사",
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
        # R-M1: valid_no_hit 은 Phase 2 적중 case 없는 상태라 검토 Lane 에 표시할
        # fallback 표가 없다. Phase 1 결과 탭으로 안내해야 사용자가 헛걸음하지 않는다.
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
    """PHASE 2 실행 요약 — Phase1 ribbon 패턴의 4 KPI 카드 flex 배너.

    카드 4:
      1) Phase 1+2 중복 탐지 케이스 — phase1 case 중 phase2 신호가 붙은 수
      2) Phase 2 즉시검토 케이스    — case rank 상위 1.25% 케이스 수
      3) 활성 분석 영역             — nonzero hit family 수 / 9
      4) 최상위 분석 영역           — nonzero_count 최대 family 한국어 라벨
    """
    overlays = _resolve_phase2_overlays_from_state()
    phase1_case_count = _resolve_phase1_case_count_from_state()
    # Why: ribbon 은 result is None 분기 이후 호출되므로 phase2_result 존재를 가정.
    #      overlays 만 보고 available / valid_no_hit / overlay_missing 분류하면 충분.
    #      empty_state 가 명시 전달되면 그것을 우선 (overview 탭이 통합 분류한 경우).
    if empty_state is None:
        empty_state = _classify_ribbon_state_from_overlays(overlays)

    case_lookup = _resolve_phase1_case_lookup_from_state()
    p1_review_bands, p2_rank_bands, _integrated_bands, total_rank_cases = (
        _phase12_rank_percentile_band_maps(case_lookup, overlays)
    )
    p1_high_case_ids = {case_id for case_id, band in p1_review_bands.items() if band == "immediate"}
    cross_detect_count = sum(
        1
        for case_id, band in p2_rank_bands.items()
        if case_id in p1_high_case_ids and band == "immediate"
    )
    review_band_counts = _count_review_bands(p2_rank_bands)
    immediate_count = review_band_counts["immediate"]
    review_count = review_band_counts["review"]
    candidate_count = review_band_counts["candidate"]

    active_family_count = _count_active_families(partition_summary)
    # Why: top family 는 우측 막대 차트(_render_phase2_family_case_bar)와 동일한
    #      case-level family_contributions 카운트를 사용해야 카드와 막대가 어긋나
    #      보이지 않는다. partition_summary 의 row-level nonzero_count / unsupervised
    #      high_count_q95 는 단위가 달라 비교 시 순위가 뒤집힌다.
    top_family_kr, top_family_hint, top_family_count = _resolve_top_active_family(
        partition_summary, overlays=overlays
    )

    sub_style = "color:#9CA3AF; font-size:0.72rem; margin-top:3px;"
    block_style = "text-align:center; flex:1; padding:0 1rem; border-right:1px solid #E5E7EB;"
    last_block_style = "text-align:center; flex:1; padding:0 1rem;"
    label_style = (
        "color:#6B7280; font-size:0.78rem; margin-bottom:6px; "
        "font-weight:500; letter-spacing:0.01em;"
    )
    value_base = "font-size:1.7rem; font-weight:700; letter-spacing:-0.02em; line-height:1.2;"
    unit_style = "font-size:0.95rem; font-weight:500; color:#6B7280;"

    # P5-2: state_id 별 KPI value / sub 분기 — missing 은 "-", valid_no_hit 은 "0".
    cross_value_text, cross_sub_html = _build_kpi_value_and_sub(
        empty_state=empty_state,
        value=cross_detect_count,
        denom=phase1_case_count,
        available_sub=(
            f"<div style='{sub_style}'>전체 케이스의 "
            f"{(cross_detect_count / phase1_case_count if phase1_case_count else 0.0):.1%}"
            "만 남김</div>"
            if phase1_case_count
            else f"<div style='{sub_style}'>Phase 1 즉시검토 ∩ Phase 2 즉시검토</div>"
        ),
        no_hit_sub=f"<div style='{sub_style}'>양쪽 즉시검토 등급 교집합 0건</div>",
        missing_sub_template=f"<div style='{sub_style}'>{{label}}</div>",
        sub_style=sub_style,
    )
    immediate_value_text, immediate_sub_html = _build_kpi_value_and_sub(
        empty_state=empty_state,
        value=immediate_count,
        denom=phase1_case_count,
        available_sub=(
            f"<div style='{sub_style}'>검토대상 {review_count:,}건 · 참고후보 "
            f"{candidate_count:,}건 · 전체 케이스의 "
            f"{(1.0 - immediate_count / total_rank_cases if total_rank_cases else 0.0):.1%}"
            " 제거</div>"
            if total_rank_cases
            else f"<div style='{sub_style}'>case 순위 상위 1.25%</div>"
        ),
        no_hit_sub=f"<div style='{sub_style}'>추가 적중 없음 (즉시 검토 후보 0건)</div>",
        missing_sub_template=f"<div style='{sub_style}'>{{label}}</div>",
        sub_style=sub_style,
    )
    # P6-3: 활성/최상위 영역은 partition_summary (정적 reference) 기반이라 source
    #       label 을 sub 에 명시. 회사 scoped overlay 기반 KPI(중복/즉시검토) 와 출처
    #       다르다는 점을 카드 단위로 구분.
    source_status, _source_message = _resolve_phase2_signal_source_status(partition_summary)
    source_label = _PHASE2_SOURCE_KPI_LABELS.get(source_status, "")
    # Why: "총 9개 영역 중 신호 잡힌 수" 문구는 라벨/값으로 자명해서 sub 를 비운다.
    #      결과 없음 같은 source 경고만 남아 있을 때는 노출.
    active_source_text = source_label.strip(" ·")
    active_sub_html = (
        f"<div style='{sub_style}'>{active_source_text}</div>" if active_source_text else ""
    )
    # Why: 최상위 분석 영역은 family 이름 + 건수를 한 토큰처럼 한 줄에 표시.
    #      "시점 이상 (891,464건)" 형식. 폰트는 다른 카드보다 살짝 작게.
    if top_family_kr:
        if top_family_count:
            top_value_text = f"{top_family_kr} ({top_family_count:,}건)"
        else:
            top_value_text = top_family_kr
        hint_html = top_family_hint or ""
        sub_parts = [part for part in (hint_html, source_label.strip(" ·")) if part]
        top_sub_html = (
            f"<div style='{sub_style}'>{' · '.join(sub_parts)}</div>" if sub_parts else ""
        )
    else:
        top_value_text = "-"
        top_sub_html = f"<div style='{sub_style}'>신호가 잡힌 영역이 없습니다.{source_label}</div>"

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
        <div style="{label_style}">Phase 1+2 중복 탐지 케이스</div>
        <div style="color:#DC2626; {value_base}">
            {cross_value_text} <span style="{unit_style}">건</span>
        </div>
        {cross_sub_html}
    </div>
    <div style="{block_style}">
        <div style="{label_style}"
             title="case rank 기준: PHASE2 5-family Noisy-OR 상위 1.25%">
            Phase 2 즉시검토 케이스
        </div>
        <div style="color:#EA580C; {value_base}">
            {immediate_value_text} <span style="{unit_style}">건</span>
        </div>
        {immediate_sub_html}
    </div>
    <div style="{block_style}">
        <div style="{label_style}">활성 분석 영역</div>
        <div style="color:#111827; {value_base}">
            {active_family_count}
            <span style="{unit_style}">/ {_PHASE2_TOTAL_FAMILY_COUNT} 개</span>
        </div>
        {active_sub_html}
    </div>
    <div style="{last_block_style}">
        <div style="{label_style}">최상위 분석 영역</div>
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
    """nonzero hit 가 가장 큰 active family 의 한국어 라벨/힌트/건수 반환."""
    case_counts = _family_case_contribution_counts(overlays)
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
        payload = families.get(family) or {}
        if not isinstance(payload, dict):
            continue
        if family == "unsupervised":
            count = int(payload.get("high_count_q95") or 0)
        else:
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


# ── 활성 분석 분포 섹션 (case rank band matrix + family hit bar) ──


def _render_phase2_active_distribution(
    partition_summary: dict | None,
    *,
    empty_state: Phase2EmptyState | None = None,
) -> None:
    """카드 밑 활성 분석 분포 — 우선순위 matrix + 가로 막대 2열.

    좌: Phase 1 / Phase 2 / 공통 우선순위 band 비교.
    우: Phase 2 family 별 case-family 적중 수 (중복 포함).

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

    case_lookup = _resolve_phase1_case_lookup_from_state()

    st.markdown(
        "<div style='color:#18181B; font-size:1rem; font-weight:600; "
        "margin:1.5rem 0 0.75rem;'>활성 분석 분포</div>",
        unsafe_allow_html=True,
    )
    # Why: 우측 막대가 9 family(active 5 + dormant 4) 라서 Phase1(7 topic) 보다
    #      slot 개수가 많다. Phase1 의 slot 당 픽셀(약 43px) 을 유지해 막대 두께를
    #      같게 맞추려면 카드 높이를 380 → 470 으로 확장한다. 좌측은 동일 높이의
    #      matrix 카드로 맞춰 두 카드의 시각 무게를 비슷하게 둔다.
    chart_card_height = 470
    left, right = st.columns([1, 1.5], gap="small")
    with left, st.container(border=True, height=chart_card_height):
        _render_phase12_priority_matrix(
            overlays, case_lookup, partition_summary, empty_state=empty_state
        )
    with right, st.container(border=True, height=chart_card_height):
        _render_phase2_family_case_bar(overlays, empty_state=empty_state)


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


def _rank_positions_desc(scores_by_case: dict[str, float]) -> dict[str, int]:
    """Return deterministic 1-based ranks for descending score order."""

    ranked = sorted(scores_by_case.items(), key=lambda item: (-item[1], item[0]))
    return {case_id: idx for idx, (case_id, _score) in enumerate(ranked, start=1)}


def _phase2_scores_by_case(overlays: list[dict], case_ids: set[str]) -> dict[str, float]:
    """PHASE2 5-family Noisy-OR display score by case id."""

    scores = {case_id: 0.0 for case_id in case_ids}
    for overlay in overlays:
        case_id = str(overlay.get("phase1_case_id") or "").strip()
        if not case_id:
            continue
        scores[case_id] = max(scores.get(case_id, 0.0), _phase2_overlay_rank_score(overlay))
    return scores


def _phase12_rank_percentile_band_maps(
    case_lookup: dict, overlays: list[dict]
) -> tuple[dict[str, str], dict[str, str], dict[str, str], int]:
    """PHASE1 priority band + PHASE2 rank-percentile band + PHASE1∩PHASE2 band maps.

    PHASE1 keeps its existing priority_score band contract. PHASE2 is ranked
    by 5-family zero-preserving Noisy-OR rank-percentile. PHASE1+2 통합은
    동일 case 가 양쪽에서 같은 band 에 속할 때만 그 band 에 카운트한다
    (예: PHASE1 즉시검토 ∩ PHASE2 즉시검토 → 통합 즉시검토).
    """

    normalized_case_lookup = {
        str(case_id or "").strip(): case
        for case_id, case in case_lookup.items()
        if str(case_id or "").strip()
    }
    case_ids = set(normalized_case_lookup)
    for overlay in overlays:
        case_ids.add(str(overlay.get("phase1_case_id") or "").strip())
    case_ids.discard("")
    total_cases = len(case_ids)
    if total_cases == 0:
        return {}, {}, {}, 0

    phase2_scores = _phase2_scores_by_case(overlays, case_ids)
    phase2_ranks = _rank_positions_desc(phase2_scores)

    phase1_bands = _phase1_priority_bands_by_case(normalized_case_lookup, case_ids)
    phase2_bands = {
        case_id: rank_percentile_band(
            phase2_ranks.get(case_id), total_cases, has_signal=phase2_scores[case_id] > 0.0
        )
        for case_id in case_ids
    }

    # PHASE1 band ∩ PHASE2 band per case. 두 phase 모두 같은 review band 인
    # case 만 통합 band 에 카운트. 한 쪽만 immediate 면 통합 immediate 비포함.
    intersect_scope = {"immediate", "review", "candidate"}
    integrated_bands = {
        case_id: phase1_bands.get(case_id, "none")
        if phase1_bands.get(case_id) == phase2_bands.get(case_id)
        and phase1_bands.get(case_id) in intersect_scope
        else "none"
        for case_id in case_ids
    }
    return phase1_bands, phase2_bands, integrated_bands, total_cases


def _phase12_rank_percentile_review_bands(
    case_lookup: dict, overlays: list[dict]
) -> tuple[dict[str, int], dict[str, int], dict[str, int], int]:
    """Exclusive counts for PHASE1 priority bands and PHASE2/integrated rank bands."""

    phase1_bands, phase2_bands, integrated_bands, total_cases = _phase12_rank_percentile_band_maps(
        case_lookup, overlays
    )
    return (
        _count_review_bands(phase1_bands),
        _count_review_bands(phase2_bands),
        _count_review_bands(integrated_bands),
        total_cases,
    )


def _render_phase12_priority_matrix(
    overlays: list[dict],
    case_lookup: dict,
    partition_summary: dict | None,
    *,
    empty_state: Phase2EmptyState | None = None,
) -> None:
    """Phase1 priority band + Phase2 / Phase1+2 rank-percentile review-band matrix.

    PHASE1 follows the existing priority_score band contract. PHASE2 uses
    5-family Noisy-OR rank, and PHASE1+2 uses RRF rank.
    """
    del partition_summary

    p1_counts, p2_counts, integrated_counts, total_cases = _phase12_rank_percentile_review_bands(
        case_lookup, overlays
    )

    # Why: 슬레이트 모노톤 히트맵. 셀 배경 alpha 농도가 비율 시각화 역할을 하므로
    #      카드 border/progress track 톤은 더 이상 필요하지 않다.
    color_text = "#111827"  # gray-900
    color_text_strong = "#0F172A"  # slate-900
    color_muted = "#6B7280"  # gray-500
    color_chip_bg = "#F8FAFC"
    color_chip_border = "#E2E8F0"
    typography = "Pretendard, Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    st.markdown(
        f"<div style='font-family:{typography}; display:flex; align-items:center; "
        "justify-content:space-between; gap:0.75rem;'>"
        f"<div style='color:{color_text_strong}; font-size:0.875rem; "
        f"font-weight:700; letter-spacing:-0.01em;'>검토 우선순위 구성</div>"
        f"<div style='display:inline-flex; align-items:center; gap:0.4rem; "
        f"background:{color_chip_bg}; border:1px solid {color_chip_border}; "
        "border-radius:999px; padding:0.2rem 0.65rem;'>"
        f"<span style='color:{color_muted}; font-size:0.65rem; "
        "font-weight:600; letter-spacing:0.04em; text-transform:uppercase;'>"
        "Total</span>"
        f"<span style='color:{color_text_strong}; font-size:0.78rem; "
        f"font-weight:700;'>{total_cases:,}</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    # P5-3: valid_no_hit (정상 결과, 추가 적중 없음) 와 데이터 부재(missing) 구분.
    if total_cases == 0 or not overlays:
        state_id = empty_state.state_id if empty_state else _PHASE2_STATE_OVERLAY_MISSING
        if state_id == _PHASE2_STATE_VALID_NO_HIT:
            st.info("분석 완료 — 추가 적중 없음. Phase 1 우선순위 기준 검토를 계속하세요.")
        else:
            st.info("overlay 가 없어 분포를 표시할 수 없습니다. Phase 2 재추론하세요.")
        return

    # Phase 별 row accent — _theme.LAYER_COLORS 와 같은 indigo/teal/violet 700 톤.
    rows = [
        ("Phase 1", p1_counts, "#4338CA"),  # indigo-700
        ("Phase 2", p2_counts, "#0D9488"),  # teal-600
        ("Phase 1+2 통합", integrated_counts, "#7C3AED"),  # violet-600
    ]
    # band 축 — 셀 배경(slate alpha 농도) 자체가 비율 시각화 역할을 하므로 hue 분리 제거.
    bands = [
        ("immediate", "즉시검토"),
        ("review", "검토대상"),
        ("candidate", "참고후보"),
    ]
    band_dot = "#64748B"  # slate-500 — 헤더 dot 만 통일된 모노톤

    # Why: 히트맵 농도 정규화. 전체 9 셀 max ratio 기준으로 alpha 를 0.04~0.42 범위에
    #      선형 매핑. 행 단위 정규화는 작은 행(예: Phase1+2 공통 174건)이 큰 행과
    #      동일 농도로 보여 잘못된 비교를 유발 → 전체 정규화 유지.
    all_ratios = [
        (counts.get(band, 0) / total_cases if total_cases else 0.0)
        for _, counts, _ in rows
        for band, _label in bands
    ]
    max_ratio = max(all_ratios) if all_ratios else 0.0
    alpha_min, alpha_max = 0.04, 0.42

    def _cell_alpha(ratio: float) -> float:
        if max_ratio <= 0:
            return alpha_min
        return alpha_min + (alpha_max - alpha_min) * (ratio / max_ratio)

    header_cells = "".join(
        "<div style='display:flex; align-items:center; justify-content:center; "
        f"gap:6px; padding-bottom:0.55rem;'>"
        f"<span style='width:6px; height:6px; border-radius:999px; "
        f"background:{band_dot};'></span>"
        f"<span style='color:{color_muted}; font-size:0.7rem; "
        "font-weight:600; letter-spacing:0.04em; text-transform:uppercase;'>"
        f"{label}</span>"
        "</div>"
        for _, label in bands
    )

    row_html = ""
    for row_label, counts, accent in rows:
        cells = ""
        for band, _label in bands:
            count = counts.get(band, 0)
            ratio = count / total_cases if total_cases else 0.0
            alpha = _cell_alpha(ratio)
            cells += (
                # slate-900 (15,23,42) 단일 hue 에 alpha 만 비율 매핑 → 히트맵 셀.
                f"<div style='background:rgba(15,23,42,{alpha:.3f}); "
                "border-radius:8px; padding:0.6rem 0.95rem; "
                "display:flex; flex-direction:column; gap:3px; min-height:58px; "
                "justify-content:center;'>"
                f"<div style='color:{color_text_strong}; font-size:1.2rem; "
                "font-weight:700; letter-spacing:-0.02em; line-height:1.1; "
                "font-variant-numeric:tabular-nums;'>"
                f"{count:,}</div>"
                f"<div style='color:{color_muted}; font-size:0.72rem; "
                "font-weight:500; font-variant-numeric:tabular-nums;'>"
                f"{ratio:.1%}</div>"
                "</div>"
            )
        row_html += (
            "<div style='display:grid; grid-template-columns:120px repeat(3, 1fr); "
            "gap:6px; align-items:stretch; margin-top:6px;'>"
            f"<div style='border-left:3px solid {accent}; padding-left:10px; "
            "display:flex; align-items:center;'>"
            f"<span style='color:{color_text}; font-size:0.82rem; "
            "font-weight:600; line-height:1.3;'>"
            f"{row_label}</span></div>"
            f"{cells}"
            "</div>"
        )

    # 매트릭스 wrapper 에 min-height 와 flex centering 을 적용해 카드 안 가운데로.
    # 카드 470px - 헤더/streamlit gap 합 ≈ 60-80px → wrapper min-height 약 380px 가
    # 안전. wrapper 안에서 매트릭스 contents 가 자연 크기로 vertical center 정렬되어
    # 카드 상·하 여백이 균등하게 보인다.
    st.markdown(
        f"<div style='margin-top:0.5rem; font-family:{typography}; "
        "min-height:380px; display:flex; flex-direction:column; "
        "justify-content:center;'>"
        "<div style='display:grid; grid-template-columns:120px repeat(3, 1fr); "
        "gap:6px; align-items:end;'>"
        "<div></div>"
        f"{header_cells}"
        "</div>"
        f"{row_html}"
        "</div>",
        unsafe_allow_html=True,
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

    counter = _family_case_contribution_counts(overlays)

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
            st.info("overlay 가 없어 분석 영역별 적중을 표시할 수 없습니다. Phase 2 재추론하세요.")
        return

    case_total = len({str(o.get("phase1_case_id") or "").strip() for o in overlays if o})
    case_total = case_total or len(overlays)
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
        height=400,
        margin={"l": 6, "r": 120, "t": 40, "b": 20},
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
    "duplicate": "#B91C1C",  # red-700
    "relational": "#6D28D9",  # violet-700
    "timeseries": "#0F766E",  # teal-700
    "intercompany": "#0369A1",  # sky-700
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
    hint = (
        "분석 영역 단위 집계는 <b>분석 영역 신호</b> 탭에서, "
        "학습 기준은 <b>모델 기준</b> 탭에서 확인할 수 있습니다."
    )
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

    일반 family 는 양수 score/ECDF 를 후보 신호로 본다. IC01 review-only 처럼
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


def _build_all_family_summary(
    partition_summary: dict | None,
    snapshot: dict | None = None,
    *,
    overlays: list[dict] | None = None,
) -> list[dict]:
    """active(신호 desc) + dormant 순서로 모두 반환.

    Why: 신호 카운트는 상단 막대 차트와 동일하게 overlays 의 family_contributions
         기반 case 카운트(중복 포함)로 모든 active family 에 통일. partition_summary
         의 row-level nonzero_count(또는 unsupervised high_count_q95)와 case-level
         집계가 단위가 다른데 같은 '건' 라벨로 노출돼 막대와 어긋나 보였다.
    """
    case_counts = _family_case_contribution_counts(overlays)
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
    is_dormant = str(item.get("상태", "")) == "대기"
    label = html.escape(str(item["분석 영역"]))
    purpose = html.escape(str(item["무엇을 잡나"]))

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
        activation_html = ""
    else:
        opacity = "1"
        signal_value = int(item.get("signal_value", 0) or 0)
        signal_label = html.escape(str(item["이번 데이터 반응"]))
        icon, badge_bg, badge_color = _phase2_family_badge_style(signal_value)
        badge_html = (
            f"<span style='background:{badge_bg}; color:{badge_color}; "
            "font-size:0.72rem; font-weight:600; padding:2px 8px; "
            f"border-radius:999px; white-space:nowrap;'>{icon} {signal_label}</span>"
        )
        title_html = (
            f"<span style='color:#111827; font-size:0.875rem; font-weight:600;'>{label}</span>"
        )
        activation_html = ""

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
        f"{activation_html}"
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


# ── KPI 카드 디자인 (전기 비교 탭 _KPI_CARD_CSS 차용) ──────────

_PHASE2_KPI_CSS = """
<style>
.p2-kpi-section { margin:0.25rem 0 0.8rem; }
.p2-kpi-section-header { display:flex; align-items:center; gap:0.5rem;
                         margin:0 0 0.45rem 0.15rem; }
.p2-kpi-section-dot { width:6px; height:6px; border-radius:999px; }
.p2-kpi-section-title { color:#374151; font-size:0.78rem; font-weight:600;
                        letter-spacing:0.06em; text-transform:uppercase; }
.p2-kpi-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:0.55rem; }
.p2-kpi-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:10px;
               padding:0.75rem 0.95rem; box-shadow:0 1px 2px rgba(15,23,42,0.04);
               border-left:3px solid var(--accent,#E5E7EB); }
.p2-kpi-label { color:#6B7280; font-size:0.75rem; font-weight:500;
                letter-spacing:0.01em; margin-bottom:0.35rem; }
.p2-kpi-row { display:flex; align-items:baseline; justify-content:space-between;
              gap:0.4rem; }
.p2-kpi-value { color:#111827; font-size:1.4rem; font-weight:700;
                letter-spacing:-0.02em; line-height:1.15; }
.p2-kpi-unit { font-size:0.8rem; font-weight:500; color:#6B7280; margin-left:2px; }
.p2-kpi-sub { color:#9CA3AF; font-size:0.72rem; margin-top:0.4rem;
              border-top:1px dashed #F1F3F5; padding-top:0.35rem; }
</style>
"""

_PHASE2_KPI_COLORS: dict[str, str] = {
    "scale": "#2563EB",  # blue-600 — 분석 규모
    "evidence": "#7C3AED",  # violet-600 — 근거 강도
}

_TIER_LABELS: dict[str, str] = {
    "strong": "강 (Strong)",
    "moderate": "중 (Moderate)",
    "weak": "약 (Weak)",
}

_REVIEW_BAND_LABELS: dict[str, str] = {
    "immediate": "즉시검토",
    "review": "검토대상",
    "candidate": "참고후보",
    "none": "후순위",
}

_PHASE1_PRIORITY_BAND_TO_REVIEW_BAND: dict[str, str] = {
    "high": "immediate",
    "medium": "review",
    "low": "candidate",
}


def _is_phase1_immediate_case(case: object) -> bool:
    """Match Phase 1 UI immediate rule: priority_score >= 0.90."""

    try:
        return float(getattr(case, "priority_score", 0.0) or 0.0) >= 0.90
    except (TypeError, ValueError):
        return str(getattr(case, "priority_band", "") or "").lower() == "high"


def _phase1_rank_score(case: object) -> float:
    """Phase1 display rank score used for rank-percentile banding."""

    for attr in ("composite_sort_score", "priority_score", "base_priority_score"):
        if not hasattr(case, attr):
            continue
        raw_value = getattr(case, attr)
        if raw_value in (None, ""):
            continue
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _phase1_priority_bands_by_case(
    case_lookup: dict[str, object], case_ids: set[str] | None = None
) -> dict[str, str]:
    """Case id -> PHASE1 review band from existing priority_band."""

    ids = case_ids if case_ids is not None else set(case_lookup)
    bands: dict[str, str] = {}
    for case_id in ids:
        normalized_case_id = str(case_id or "").strip()
        if not normalized_case_id:
            continue
        case = case_lookup.get(normalized_case_id)
        raw_band = (
            str(getattr(case, "priority_band", "") if case is not None else "").strip().lower()
        )
        bands[normalized_case_id] = _PHASE1_PRIORITY_BAND_TO_REVIEW_BAND.get(raw_band, "candidate")
    return bands


def _phase2_overlay_rank_score(overlay: dict) -> float:
    """Approximate PHASE2 Noisy-OR score from overlay family ECDF values."""

    contributions = overlay.get("family_contributions") or []
    survival = 1.0
    has_signal = False
    for entry in contributions:
        try:
            ecdf = float(entry.get("ecdf") or 0.0)
        except (TypeError, ValueError):
            ecdf = 0.0
        ecdf = max(0.0, min(ecdf, 1.0))
        if ecdf > 0.0:
            has_signal = True
        survival *= 1.0 - ecdf
    if has_signal:
        return 1.0 - survival
    try:
        return float(overlay.get("max_family_ecdf") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _phase2_rank_bands_by_case(overlays: list[dict]) -> dict[str, str]:
    """Case id -> rank-percentile PHASE2 band, based on overlay Noisy-OR score."""

    scored: list[tuple[float, str]] = []
    for overlay in overlays:
        case_id = str(overlay.get("phase1_case_id") or "").strip()
        if not case_id:
            continue
        scored.append((_phase2_overlay_rank_score(overlay), case_id))
    scored.sort(key=lambda item: item[0], reverse=True)
    total_cases = len(scored)
    bands: dict[str, str] = {}
    for idx, (score, case_id) in enumerate(scored, start=1):
        bands[case_id] = rank_percentile_band(idx, total_cases, has_signal=score > 0.0)
    return bands


def _count_review_bands(bands_by_case: dict[str, str]) -> dict[str, int]:
    """Exclusive count for immediate / review / candidate bands."""

    counts = {"immediate": 0, "review": 0, "candidate": 0}
    for band in bands_by_case.values():
        if band in counts:
            counts[band] += 1
    return counts


_REVIEW_BAND_LEVEL: dict[str, int] = {
    "immediate": 1,
    "review": 2,
    "candidate": 3,
}


def _count_common_review_bands(
    left_bands_by_case: dict[str, str],
    right_bands_by_case: dict[str, str],
) -> dict[str, int]:
    """Exclusive common band counts from two rank-band mappings.

    A case is common at level N when both sources rank it within that cumulative
    level. Exclusive cells subtract the previous cumulative level so matrix
    columns do not double count.
    """

    common_case_ids = set(left_bands_by_case) & set(right_bands_by_case)

    def cumulative_count(max_level: int) -> int:
        count = 0
        for case_id in common_case_ids:
            left_level = _REVIEW_BAND_LEVEL.get(left_bands_by_case.get(case_id, "none"), 99)
            right_level = _REVIEW_BAND_LEVEL.get(right_bands_by_case.get(case_id, "none"), 99)
            if left_level <= max_level and right_level <= max_level:
                count += 1
        return count

    immediate = cumulative_count(1)
    review_cumulative = cumulative_count(2)
    candidate_cumulative = cumulative_count(3)
    return {
        "immediate": immediate,
        "review": max(review_cumulative - immediate, 0),
        "candidate": max(candidate_cumulative - review_cumulative, 0),
    }


def _build_scale_kpi_cards(
    overlays: list[dict],
    partition_summary: dict | None,
    *,
    overlay_status: str = "available",
) -> list[str]:
    """분석 규모 3 KPI 카드: 분석 대상 케이스 / Phase2 신호 케이스 / 활성 분석 영역."""
    accent = _PHASE2_KPI_COLORS["scale"]
    total_cases = len(overlays)
    signaled = sum(1 for o in overlays if o.get("top_family"))
    signal_ratio = (signaled / total_cases * 100.0) if total_cases else 0.0
    active_family_count = _count_active_families(partition_summary)
    signaled_value = f"{signaled:,}" if overlay_status == "available" else "-"
    signaled_sub = (
        f"전체의 {signal_ratio:.1f}%"
        if overlay_status == "available" and total_cases
        else _overlay_status_short_text(overlay_status)
    )
    return [
        _build_phase2_kpi_card(
            label="분석 대상 케이스",
            value_text=f"{total_cases:,}",
            unit="건",
            sub_text="Phase 1 검토 케이스 전체",
            accent=accent,
        ),
        _build_phase2_kpi_card(
            label="Phase 2 신호 케이스",
            value_text=signaled_value,
            unit="건",
            sub_text=signaled_sub,
            accent=accent,
        ),
        _build_phase2_kpi_card(
            label="활성 분석 영역",
            value_text=f"{active_family_count}",
            unit="개",
            sub_text="신호가 잡힌 분석 영역 수 (max 5)",
            accent=accent,
        ),
    ]


def _build_evidence_tier_kpi_cards(
    overlays: list[dict],
    *,
    overlay_status: str = "available",
) -> list[str]:
    """PHASE2 검토 등급 3 KPI 카드: 즉시검토 / 검토대상 / 후보."""
    accent = _PHASE2_KPI_COLORS["evidence"]
    band_counts = _count_phase2_review_bands(overlays)
    total_tagged = sum(band_counts.values()) or 0
    cutoff_caption = rank_band_caption(len(overlays)) if overlays else ""
    cards: list[str] = []
    for band in ("immediate", "review", "candidate"):
        count = band_counts.get(band, 0)
        ratio = (count / total_tagged * 100.0) if total_tagged else 0.0
        value = f"{count:,}" if overlay_status == "available" else "-"
        sub = (
            f"{cutoff_caption} · 현재 {ratio:.1f}%"
            if overlay_status == "available" and total_tagged
            else _overlay_status_short_text(overlay_status)
        )
        cards.append(
            _build_phase2_kpi_card(
                label=_REVIEW_BAND_LABELS[band],
                value_text=value,
                unit="건",
                sub_text=sub,
                accent=accent,
            )
        )
    return cards


def _count_active_families(partition_summary: dict | None) -> int:
    """partition_summary 에서 nonzero hit 가 있는 active family 수."""
    if not partition_summary:
        return 0
    families = partition_summary.get("families") or {}
    active = {"unsupervised", "timeseries", "relational", "duplicate", "intercompany"}
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


def _count_phase2_review_bands(overlays: list[dict]) -> dict[str, int]:
    """Rank-percentile PHASE2 review band distribution."""

    counts: dict[str, int] = {"immediate": 0, "review": 0, "candidate": 0, "none": 0}
    for band in _phase2_rank_bands_by_case(overlays).values():
        if band not in counts:
            band = "none"
        counts[band] += 1
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
            "분석 영역 신호 탭의 집계는 선택 연도 기준으로 볼 수 있지만, case-level KPI와 Lane은 "
            "현재 추론 결과와 일치할 때만 표시합니다."
        )
    if status == "placeholder":
        return (
            "현재 Phase 2 결과에는 case-level 분석 영역 attribution이 아직 연결되지 않았습니다. "
            "분석 영역 신호 탭의 aggregate hit는 확인할 수 있지만, 신호 케이스 수와 Lane은 "
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


def _render_kpi_section(title: str, color: str, cards: list[str]) -> None:
    """카테고리 헤더 + 카드 그리드 한 섹션."""
    html = (
        "<div class='p2-kpi-section'>"
        "<div class='p2-kpi-section-header'>"
        f"<span class='p2-kpi-section-dot' style='background:{color};'></span>"
        f"<span class='p2-kpi-section-title'>{title}</span>"
        "</div>"
        "<div class='p2-kpi-grid'>" + "".join(cards) + "</div>"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _build_phase2_kpi_card(
    *,
    label: str,
    value_text: str,
    unit: str | None,
    sub_text: str,
    accent: str,
) -> str:
    """단일 KPI 카드 HTML — 전기 비교 카드와 동일한 마크업."""
    unit_html = f"<span class='p2-kpi-unit'>{unit}</span>" if unit else ""
    return (
        f"<div class='p2-kpi-card' style='--accent:{accent};'>"
        f"<div class='p2-kpi-label'>{label}</div>"
        f"<div class='p2-kpi-row'>"
        f"<div class='p2-kpi-value'>{value_text}{unit_html}</div>"
        f"</div>"
        f"<div class='p2-kpi-sub'>{sub_text}</div>"
        f"</div>"
    )


# ──────────────────────────────────────────────────────────────
# 새 sub-tab skeleton: 분석 영역별 / 위험 신호별 / 통계결과
# Why: Phase 1 결과 탭(데이터 정합성 / 검토 케이스 / 통계결과)과 일관된 구조로
#      Phase 2 결과 화면을 재구성. 기존 분석 영역 신호 / 검토 Lane / 모델 기준은
#      더이상 호출하지 않는다.
# ──────────────────────────────────────────────────────────────


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
) -> None:
    """단일 family 영역 카드 — 헤더(라벨/케이스 수) + 설명 + subdetector 표."""
    label_kr = _FAMILY_LABELS_KR.get(family, family)
    accent = _FAMILY_ACCENT.get(family, "#9CA3AF")
    purpose = _FAMILY_AUDIT_PURPOSE_KR.get(family, "-")
    audit_check = _FAMILY_AUDIT_CHECK_KR.get(family, "-")

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
        f"<div style='color:#6B7280; font-size:0.74rem; margin-top:2px;'>"
        f"감사인 확인 포인트: {audit_check}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    sub_lookup = payload.get("sub_detectors") or {}
    rows: list[dict] = []
    for fam, code, label in SUB_DETECTORS:
        if fam != family:
            continue
        sub_payload = sub_lookup.get(code) or {}
        rows.append(
            {
                "코드": code,
                "세부 탐지": str(sub_payload.get("label") or label),
                "적중 건수": int(sub_payload.get("hit_count") or 0),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("세부 탐지 항목 정보가 없습니다.")


def _render_phase2_risk_signal_tab(
    snapshot: dict | None,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """③ 위험 신호별 — Phase 1 검토 케이스 패턴 차용.

    Why: Phase 2 가 5-family Noisy-OR rank 로 평가한 케이스를 우선순위 desc 로
         정렬해 Top N master 로 보여준다. 즉시검토/검토대상/참고후보 등급은 보조 컬럼.
    """
    del snapshot, partition_summary
    from dashboard._state import KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    overlays, overlay_status = _resolve_display_overlays(phase2_result, partition)
    empty_state = _resolve_phase2_empty_state(
        phase2_result=phase2_result,
        overlays=overlays,
        phase1_basis_status=str(getattr(phase2_result, "phase1_case_basis_status", "") or "")
        or None,
        overlay_status=overlay_status,
    )
    if empty_state.state_id != _PHASE2_STATE_AVAILABLE:
        st.info(empty_state.title or "Phase 2 케이스를 표시할 수 없습니다.")
        if empty_state.body:
            st.caption(empty_state.body)
        return

    st.markdown(
        """
<div style="background:#F3F4F6; border:1px solid #E5E7EB; border-radius:8px;
            padding:0.75rem 1rem; margin:0.25rem 0 1rem; color:#374151;">
  <div style="font-weight:600; margin-bottom:0.45rem; color:#111827;">
    ℹ 위험 신호 우선순위 안내
  </div>
  <ul style="margin:0; padding-left:1.2rem; font-size:0.88rem; line-height:1.6;">
    <li><strong>즉시검토 (rank 상위 1.25%)</strong>
        — Phase 2 가 5개 분석 영역을 종합해 가장 높이 평가한 케이스</li>
    <li><strong>검토대상 / 참고후보</strong> — rank percentile 기준 차순위 그룹</li>
    <li>Phase 1 등급과 함께 보면 두 단계 모두에서 잡힌 case 를 빠르게 식별 가능</li>
  </ul>
</div>
""",
        unsafe_allow_html=True,
    )

    case_lookup = _resolve_phase1_case_lookup_from_state()
    case_rows = _phase2_risk_signal_master_rows(overlays, case_lookup, top_n=200)
    if not case_rows:
        st.info("표시할 Phase 2 위험 신호 케이스가 없습니다.")
        return

    frame = pd.DataFrame(case_rows)
    st.dataframe(frame, width="stretch", hide_index=True)
    st.caption(
        "표는 Phase 2 5-family Noisy-OR 점수 desc 로 정렬되어 있습니다. "
        "Top 200 까지 노출 (행 클릭 시 case drilldown 은 추후 연결)."
    )


def _phase2_risk_signal_master_rows(
    overlays: list[dict],
    case_lookup: dict,
    *,
    top_n: int = 200,
) -> list[dict]:
    """Phase 2 위험 신호 master row — overlay + Phase 1 case 메타 join."""
    rank_bands = _phase2_rank_bands_by_case(overlays)
    rows: list[dict] = []
    for overlay in overlays:
        case_id = str(overlay.get("phase1_case_id") or "").strip()
        if not case_id:
            continue
        rank_score = _phase2_overlay_rank_score(overlay)
        if rank_score <= 0.0:
            continue
        case = case_lookup.get(case_id)
        top_family = str(overlay.get("top_family") or "")
        contributions = overlay.get("family_contributions") or []
        signal_families = ", ".join(
            _FAMILY_LABELS_KR.get(str(c.get("family")), str(c.get("family")))
            for c in contributions
            if _family_contribution_has_positive_signal(c)
        )
        phase1_band = str(getattr(case, "priority_band", "-") or "-").upper() if case else "-"
        phase1_score = round(float(getattr(case, "priority_score", 0.0) or 0.0), 3) if case else 0.0
        rows.append(
            {
                "case_id": case_id,
                "Phase2 점수": round(rank_score, 4),
                "Phase2 등급": _REVIEW_BAND_LABELS.get(rank_bands.get(case_id, "none"), "후순위"),
                "대표 영역": _FAMILY_LABELS_KR.get(top_family, top_family or "-"),
                "신호 영역 조합": signal_families or "-",
                "Phase1 등급": phase1_band,
                "Phase1 점수": phase1_score,
                "전표 수": int(getattr(case, "document_count", 0) or 0) if case else 0,
                "금액": float(getattr(case, "total_amount", 0.0) or 0.0) if case else 0.0,
            }
        )
    rows.sort(key=lambda r: -float(r.get("Phase2 점수") or 0.0))
    return rows[:top_n]


def _render_phase2_stats_tab(
    snapshot: dict | None,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """④ 통계결과 — Phase 2 분포 4종.

    Why: Phase 2 가 만든 점수·등급·영역·세부 탐지 분포만 모은다. 학습 리포트나
         리더보드는 별도 화면(모델 기준)에서 다루지 않고 운영 관점에 집중.
    """
    del snapshot, partition

    overlays = _resolve_phase2_overlays_from_state()
    if not overlays:
        st.info("통계를 계산할 Phase 2 overlay 가 없습니다. Phase 2 추론을 실행하세요.")
        return

    with st.container(border=True):
        st.markdown("##### 1. Phase 2 Noisy-OR 점수 분포")
        st.caption("5-family ECDF 를 zero-preserving Noisy-OR 로 결합한 점수")
        _render_phase2_score_distribution(overlays)

    with st.container(border=True):
        st.markdown("##### 2. 검토 등급 분포 (rank percentile)")
        st.caption("즉시검토(상위 1.25%) / 검토대상 / 참고후보 / 후순위 케이스 수")
        _render_phase2_band_distribution(overlays)

    with st.container(border=True):
        st.markdown("##### 3. 분석 영역별 case-family 적중 분포")
        st.caption("한 case 가 여러 영역에 걸리면 중복 집계")
        _render_phase2_family_case_bar(overlays, chart_key="phase2_stats_family_bar")

    with st.container(border=True):
        st.markdown("##### 4. 세부 탐지 항목별 적중 분포")
        st.dataframe(
            _build_subdetector_kr_frame(partition_summary),
            width="stretch",
            hide_index=True,
        )


def _render_phase2_score_distribution(overlays: list[dict]) -> None:
    """Phase 2 Noisy-OR 점수 히스토그램."""
    import plotly.graph_objects as go

    scores = [s for s in (_phase2_overlay_rank_score(o) for o in overlays) if s > 0.0]
    if not scores:
        st.caption("0 점 초과 신호가 없습니다.")
        return
    fig = go.Figure(
        go.Histogram(
            x=scores,
            nbinsx=40,
            marker={"color": "#7C3AED", "line": {"width": 0}},
        )
    )
    fig.update_layout(
        height=240,
        margin={"l": 30, "r": 20, "t": 10, "b": 30},
        xaxis_title="Phase 2 Noisy-OR 점수",
        yaxis_title="케이스 수",
        bargap=0.05,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displayModeBar": False},
        key="phase2_stats_score_hist",
    )


def _render_phase2_band_distribution(overlays: list[dict]) -> None:
    """검토 등급별 case 수 막대."""
    import plotly.graph_objects as go

    counts = _count_phase2_review_bands(overlays)
    order = ["immediate", "review", "candidate", "none"]
    labels = [_REVIEW_BAND_LABELS[b] for b in order]
    values = [int(counts.get(b, 0) or 0) for b in order]
    colors = ["#EA580C", "#D97706", "#9CA3AF", "#E5E7EB"]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker={"color": colors, "line": {"width": 0}},
            text=[f"{v:,}" for v in values],
            textposition="outside",
            hovertemplate="%{x}: %{y:,}건<extra></extra>",
        )
    )
    fig.update_layout(
        height=240,
        margin={"l": 30, "r": 20, "t": 10, "b": 30},
        yaxis_title="케이스 수",
        bargap=0.4,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displayModeBar": False},
        key="phase2_stats_band_bar",
    )


# ──────────────────────────────────────────────────────────────
# Deprecated: 기존 분석 영역 신호 / 검토 Lane / 모델 기준 — 호출 제거됨.
# Why: 새 sub-tab 구조(분석 영역별 / 위험 신호별 / 통계결과)로 대체. 헬퍼는
#      신규 함수에서 재사용하므로 함수 본체는 cleanup 전까지 유지.
# ──────────────────────────────────────────────────────────────


def _render_family_signal_tab(
    snapshot: dict | None,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """② 분석 영역 신호 — 활성 영역 카드 + 세부 탐지 한국어 표 + 대기 영역 expander."""
    families_payload = (partition_summary or {}).get("families") or {}

    source_suffix = _phase2_signal_source_suffix(partition_summary)
    st.markdown(f"##### 활성 분석 영역{source_suffix}")
    _render_phase2_signal_source_caption(partition_summary)
    st.caption("Phase 2 에서 신호를 잡은 분석 영역 (총 5개)")
    st.markdown(_FAMILY_CARD_CSS, unsafe_allow_html=True)
    cards = [
        _build_family_card_html(family, families_payload.get(family) or {})
        for family in ACTIVE_FAMILIES
    ]
    st.markdown(
        "<div class='p2-family-grid'>" + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown("**세부 탐지 항목별 적중 현황**")
        st.dataframe(
            _build_subdetector_kr_frame(partition_summary),
            width="stretch",
            hide_index=True,
        )

    with st.expander("대기 중인 분석 영역 보기", expanded=False):
        st.caption("현재 활성화되지 않은 분석 영역 — 데이터 부족 또는 기준 미충족으로 보류된 영역")
        st.dataframe(
            _build_dormant_family_frame(snapshot, partition_summary),
            width="stretch",
            hide_index=True,
        )


# ── 분석 영역 카드 디자인 ─────────────────────────────────────

_FAMILY_LABELS_KR: dict[str, str] = {
    "duplicate": "중복 전표",
    "relational": "관계망 이상",
    "timeseries": "시점 이상",
    "intercompany": "관계사 매칭",
    "unsupervised": "VAE Deep Learning",
    "supervised": "지도 학습",
    "transformer": "트랜스포머",
    "sequence": "시퀀스",
    "stacking": "스태킹",
}

_FAMILY_ACCENT: dict[str, str] = {
    "duplicate": "#DC2626",  # red-600
    "relational": "#7C3AED",  # violet-600
    "timeseries": "#0D9488",  # teal-600
    "intercompany": "#0EA5E9",  # sky-500
    "unsupervised": "#D97706",  # amber-600
}

_FAMILY_HINT_KR: dict[str, str] = {
    "duplicate": "같은 거래가 여러 번 기표된 패턴",
    "relational": "신규 거래처·휴면계정 등 관계 이상",
    "timeseries": "거래 빈도·집중 등 시계열 이상",
    "intercompany": "관계사 거래의 미매칭 신호",
    "unsupervised": "ML 모델이 분포 꼬리로 분류한 케이스",
    "supervised": "감사 라벨로 학습한 전표 위험 패턴",
    "transformer": "텍스트·범주 조합의 복합 이상 패턴",
    "sequence": "전표 흐름 순서와 반복 경로 이상",
    "stacking": "여러 분석 영역 결과를 결합한 종합 신호",
}

_FAMILY_AUDIT_PURPOSE_KR: dict[str, str] = {
    "duplicate": "중복 지급, 반복 기표, 분할 처리처럼 같은 경제 사건이 여러 번 잡힌 후보를 봅니다.",
    "relational": (
        "신규 거래처, 휴면 계정, 낮은 빈도의 조합처럼 거래 관계가 평소와 달라진 지점을 봅니다."
    ),
    "timeseries": "결산기 집중, 짧은 기간 폭증, 비정상 시간대처럼 발생 시점이 튀는 거래를 봅니다.",
    "intercompany": "관계사 거래에서 대응 전표나 참조가 맞지 않는 후보를 봅니다.",
    "unsupervised": "정해진 룰로 설명하기 어려운 금액·계정·거래속성 조합의 분포 꼬리를 봅니다.",
    "supervised": "검토 완료 라벨이 충분할 때 과거 감사인이 문제 삼은 패턴과 유사한 후보를 봅니다.",
    "transformer": "적요, 거래처, 계정, 사용자 등 범주 조합의 문맥상 이상한 후보를 봅니다.",
    "sequence": "승인-기표-수정-상계처럼 사건 순서가 일반 흐름과 다른 후보를 봅니다.",
    "stacking": "여러 분석 영역이 동시에 약하게 반응한 후보를 한 번 더 모아 봅니다.",
}

_FAMILY_AUDIT_CHECK_KR: dict[str, str] = {
    "duplicate": "원전표, 지급 참조, 금액·거래처·일자 근접성을 같이 확인",
    "relational": "거래처 마스터 변경, 신규 등록 승인, 계정 사용 이력 확인",
    "timeseries": "cutoff, 결산 조정, 승인일과 기표일 차이 확인",
    "intercompany": "상대 법인 전표, 상계 계정, 참조 번호 매칭 확인",
    "unsupervised": "Phase1 근거와 함께 금액·계정 조합의 업무상 설명 가능성 확인",
    "supervised": "라벨 품질과 holdout 성능이 확보된 뒤 검토 후보로 사용",
    "transformer": "텍스트/범주 데이터 품질과 개인정보 마스킹 정책 확인",
    "sequence": "이벤트 로그 또는 전표 변경 이력이 있을 때 순서 기반으로 확인",
    "stacking": "기본 분석 영역 결과가 충분히 쌓인 뒤 종합 우선순위 보조로 사용",
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
        ui_meta = family_payload.get("ui_meta") or {}
        hit = int(sub_payload.get("hit_count") or 0)
        note = "-"
        if family == "intercompany":
            active_codes = set(ui_meta.get("active_sub_detectors") or [])
            if code in active_codes:
                note = "active (sidecar)"
            elif code in {"IC02", "IC03"}:
                note = "데이터 미보유"
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


def _render_review_lane_tab(
    snapshot: dict | None,
    partition: str,
    partition_summary: dict | None,
) -> None:
    """③ 검토 Lane — Phase1 priority 병기 + 한국어 lane 라벨.

    Why: PHASE1 역할 원칙(PHASE2는 PHASE1 우선순위를 대체하지 않는다)에 따라,
         표는 Phase1 priority desc로 정렬하고 추가 신호(evidence_tier)는 보조 컬럼
         으로 노출한다.
    """
    from src.services.phase2_lane_sort import lane_summary, list_active_lanes

    family_roles = _resolve_family_roles_from_snapshot(snapshot, partition_summary)
    from dashboard._state import KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    overlays, overlay_status = _resolve_display_overlays(phase2_result, partition)
    # P5-3: phase2_not_run / phase1_basis_unavailable / overlay_missing / valid_no_hit
    #       각각 다른 빈 상태 메시지 + 차트/Lane 표시 여부.
    empty_state = _resolve_phase2_empty_state(
        phase2_result=phase2_result,
        overlays=overlays,
        phase1_basis_status=str(getattr(phase2_result, "phase1_case_basis_status", "") or "")
        or None,
        overlay_status=overlay_status,
    )
    if not family_roles:
        st.info("Phase 2 분석 영역 role 정보가 없습니다. 학습 리포트를 확인하세요.")
        return
    if empty_state.state_id == _PHASE2_STATE_NOT_RUN:
        st.info("Phase 2 추론 후 검토 Lane 이 표시됩니다.")
        return
    if empty_state.state_id == _PHASE2_STATE_PHASE1_BASIS_UNAVAILABLE:
        st.warning(
            "Phase 1 검토 케이스가 없어 검토 Lane 을 만들 수 없습니다. "
            "Phase 1 분석을 먼저 실행하세요."
        )
        return
    if empty_state.state_id == _PHASE2_STATE_OVERLAY_MISSING:
        st.info(_overlay_status_message(overlay_status or "missing", partition))
        return
    if empty_state.state_id == _PHASE2_STATE_VALID_NO_HIT:
        # R-M1: Phase 2 적중 case 가 없어 Lane 표를 만들 수 없다. fallback 표를
        # Phase 2 탭에서 노출하면 책임 경계 위반 (Phase 1 우선순위 view 중복) —
        # Phase 1 결과 탭으로 안내한다.
        st.info(
            "분석 완료 — Phase 2 가 어떤 Lane 에도 추가 적중 case 를 부여하지 "
            "않았습니다. 정상 결과이며, 검토는 Phase 1 결과 탭에서 우선순위 기준으로 "
            "계속하세요."
        )
        if st.button(
            "Phase 1 결과 탭에서 계속 검토",
            key="p5_lane_action_goto_phase1_no_hit",
        ):
            st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
            st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE1
            st.rerun()
        return

    st.caption(
        "Phase 1 검토 큐의 보조 view 입니다. Phase 1 우선순위를 변경하지 않습니다. "
        "Lane 은 추가 신호의 출처(중복 / 관계망 / 시점 / 관계사 / VAE Deep Learning)를 설명합니다."
    )

    available = list_active_lanes(family_roles)
    if not available:
        st.warning("진입한 lane 이 없습니다.")
        return

    summary_rows: list[dict] = []
    for family in available:
        role = family_roles.get(family, "unknown")
        summary = lane_summary(family, overlays, family_role=role)
        tier_counts = summary.get("tier_counts") or {}
        summary_rows.append(
            {
                "Lane": _LANE_LABELS_KR.get(family, family),
                "성격": _LANE_HINTS.get(family, "-"),
                "케이스 수": int(summary.get("case_count") or 0),
                "강": int(tier_counts.get("strong") or 0),
                "중": int(tier_counts.get("moderate") or 0),
                "약": int(tier_counts.get("weak") or 0),
                "상태": str(summary.get("badge") or "-"),
            }
        )
    st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

    selected = st.selectbox(
        "Lane 선택",
        options=available,
        format_func=lambda f: _LANE_LABELS_KR.get(f, str(f)),
        key="phase2_review_lane_selector",
    )
    if not isinstance(selected, str):
        return
    selected_role = family_roles.get(selected, "unknown")
    if selected_role == "near-dormant":
        st.warning(
            f"`{_LANE_LABELS_KR.get(selected, selected)}` lane 은 대기 상태입니다 (데이터 미보유)."
        )
        return

    content_frame = _build_review_lane_frame(selected, overlays, phase2_result=phase2_result)
    if content_frame.empty:
        st.info(f"`{_LANE_LABELS_KR.get(selected, selected)}` lane 에 진입한 case 가 없습니다.")
        return

    st.dataframe(content_frame, width="stretch", hide_index=True)
    st.caption(
        "표는 **Phase 1 우선순위(점수 desc)** 로 정렬되어 있습니다. "
        "근거 강도는 추가 신호의 강/중/약 분류이며 정렬 기준이 아닙니다."
    )


# ── Lane 한국어 라벨 / 힌트 / 배지 ────────────────────────────

_LANE_LABELS_KR: dict[str, str] = {
    "duplicate": "중복 전표",
    "relational": "관계망 이상",
    # 결정 9 (docs/PHASE2_TIMESERIES_ROLE_LOCK.md): timeseries 는 단독 ranker 가 아닌
    # 결산·시점 컨텍스트 보조 lane.
    "timeseries": "결산·시점 컨텍스트",
    "intercompany": "관계사 매칭",
    "unsupervised": "VAE Deep Learning",
}

_LANE_HINTS: dict[str, str] = {
    "duplicate": "같은 거래가 여러 번 기표되었을 가능성",
    "relational": "신규 거래처·휴면계정 등 관계 이상",
    # 결정 9: 단독 ranker 가 아닌 결산·시점 맥락 보강 lane (제품 언어, 내부 지표 미노출).
    "timeseries": (
        "결산·시점 맥락을 보강하는 보조 lane. 상단 정밀 ranker 가 아니라 "
        "깊은 검토 범위에서 coverage 보조 용도로 해석하세요."
    ),
    "intercompany": "관계사 거래의 미매칭 신호",
    "unsupervised": "ML 모델이 분포 꼬리로 분류한 케이스",
}

_EVIDENCE_TIER_BADGE: dict[str, str] = {
    "strong": "강",
    "moderate": "중",
    "weak": "약",
}


def _build_phase1_priority_lookup(phase2_result=None) -> dict[str, dict]:
    """phase1_result.cases 에서 case_id → priority_band/score lookup."""
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


def _build_review_lane_frame(
    family: str,
    overlays: list[dict],
    *,
    max_rows: int = 50,
    phase2_result=None,
) -> pd.DataFrame:
    """선택된 lane 의 케이스 표 — Phase 1 priority desc 정렬, 한국어 컬럼.

    Why: lane_membership 으로 1차 필터한 후 Phase 1 priority desc 로 정렬한다.
         (sort_lane 의 evidence_tier 정렬을 쓰면 상위 N 자르기에서 Phase 1
         high priority 가 누락될 수 있다.)
    """
    priority_lookup = _build_phase1_priority_lookup(phase2_result)
    rank_bands = _phase2_rank_bands_by_case(overlays)
    rows: list[dict] = []
    for overlay in overlays:
        membership = overlay.get("lane_membership") or []
        if family not in membership:
            continue
        entry = next(
            (c for c in (overlay.get("family_contributions") or []) if c.get("family") == family),
            None,
        )
        if entry is None:
            continue
        case_id = str(overlay.get("phase1_case_id", "") or "")
        phase1_meta = priority_lookup.get(case_id, {})
        priority_score = phase1_meta.get("priority_score")
        sub_codes = ", ".join(
            str(sub.get("code", ""))
            for sub in (entry.get("sub_detectors") or [])
            if isinstance(sub, dict) and sub.get("code")
        )
        tier_token = str(entry.get("evidence_tier") or "").strip().lower()
        top_family = str(overlay.get("top_family") or "")
        review_band = rank_bands.get(case_id, "none")
        rows.append(
            {
                "case_id": case_id,
                "Phase1 등급": str(phase1_meta.get("priority_band", "미확인")).upper(),
                "Phase1 점수": _format_phase1_priority_score(priority_score),
                "Phase2 구간": _REVIEW_BAND_LABELS.get(review_band, "후순위"),
                "근거 강도": _EVIDENCE_TIER_BADGE.get(tier_token, tier_token or "-"),
                "ECDF": _round_lane_value(entry.get("ecdf")),
                "세부 탐지": sub_codes or "-",
                "대표 영역": _LANE_LABELS_KR.get(top_family, top_family or "-"),
                "_phase1_sort_score": float(priority_score) if priority_score is not None else -1.0,
            }
        )
    rows.sort(key=lambda r: -float(r.get("_phase1_sort_score") or -1.0))
    frame = pd.DataFrame(rows[:max_rows])
    if "_phase1_sort_score" in frame.columns:
        frame = frame.drop(columns=["_phase1_sort_score"])
    return frame


def _format_phase1_priority_score(value) -> float | str:
    if value is None:
        return "-"
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return "-"


def _round_lane_value(value, digits: int = 4) -> float | str:
    if value is None:
        return "-"
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return "-"


def _render_model_basis_tab(snapshot: dict | None, result: PipelineResult) -> None:
    """④ 모델 기준 — 감사 조서·재현성 목적의 상세 정보를 expander로 정리.

    Why: 학습 기준·리더보드·실행 현황·성능 리포트는 일반 감사 사용자에게는
         보조 정보이고, 리뷰/재현/감사조서 사용자에게 중요하다. 기본은 접힌 상태로
         두되 첫 항목(확정 모델)만 펼쳐 두어 빠른 접근성을 보장한다.
    """
    st.caption(
        "감사 조서·재현 검증을 위한 상세 정보입니다. 평소에는 접혀 있으며, "
        "필요할 때 펼쳐 확인하세요."
    )

    with st.expander("확정 모델 및 학습 진단", expanded=True):
        _render_training_snapshot_summary(snapshot)

    with st.expander("리더보드 및 승격 결정", expanded=False):
        render_leaderboard_view(snapshot)

    with st.expander("탐지기 실행 현황", expanded=False):
        _render_status_grid(result)
        st.divider()
        _render_track_status(result)

    with st.expander("성능 리포트", expanded=False):
        _render_performance_report(result)


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


def _render_phase2_contract_views(
    snapshot: dict | None,
    partition_summary: dict | None,
) -> None:
    render_family_matrix(snapshot, partition_summary)
    render_subdetector_grid(partition_summary)
    render_leaderboard_view(snapshot)
    _render_phase2_lane_view(snapshot, partition_summary)


def _render_phase2_lane_view(
    snapshot: dict | None,
    partition_summary: dict | None,
) -> None:
    """Phase E — primary queue 보조 lane view.

    snapshot 의 family_diagnostics roles + 현재 inference 의 case overlay 를
    조회해 lane 별 sort + tier badge 를 표시한다. lane 은 primary queue 의 순위를
    변경하지 않으며 family signal attribution 용도다.
    (docs/PHASE2_GOVERNANCE_DESIGN.md 결정 8)
    """
    overlays = _resolve_phase2_overlays_from_state()
    family_roles = _resolve_family_roles_from_snapshot(snapshot, partition_summary)
    if not family_roles:
        return
    render_lane_view(overlays, family_roles)


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
    "relational": "relational",
    "duplicate": "duplicate",
    "intercompany": "intercompany",
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
