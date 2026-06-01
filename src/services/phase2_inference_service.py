"""Service helpers for Phase 2 inference-only execution.

Phase 2 standalone contract
---------------------------

Phase 2 추론은 **원본/featured 회계 CSV 전체** 를 primary input 으로 받는
standalone anomaly layer 다. PHASE1 case priority, rule hit, review queue,
composite_sort_score 는 Phase 2 의 ML/통계 family detector 입력 또는 gate
로 들어가지 않는다.

- primary input  : ``featured_df`` (또는 raw GL DataFrame) — 전수 모집단.
- optional context: PHASE1 ``Phase1CaseResult`` — 추론 **이후** overlay
  attach (``_inherit_phase1_case_result`` → ``_attach_phase2_case_overlays``)
  로만 사용. 누락돼도 family score 산출에는 영향 없음.
- batch_id        : PHASE1 batch row 를 같은 DB row 로 UPDATE 하기 위한
  **DB 영속화 키**. ML 입력 gating 과 무관하다. PHASE1 분석 없이 phase2
  단독 실행을 위해서는 별도 batch_id 발급 경로가 필요 (현재는 dashboard
  workflow 가 PHASE1 batch_id 재사용을 강제).

따라서 PHASE1 결과는 "감사인 화면 문맥" 과 "case-level overlay" 의 source
이지, PHASE2 가 무엇을 보고 점수를 매길지 결정하는 입력이 아니다. 본 모듈
의 모든 helper 는 이 계약을 따른다.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.services._phase_timing import TimingBlock, log_timing, now_str
from src.services.phase2_case_contract import build_phase2_case_overlays
from src.services.phase2_case_family_aggregator import (
    build_phase2_case_family_overlay_inputs,
)

logger = logging.getLogger(__name__)


def run_phase2_inference(
    featured_df,
    *,
    batch_id: str,
    file_name: str = "",
    reference_df=None,
    ctx=None,
    settings=None,
    repo=None,
    conn=None,
    pipeline_cls=None,
):
    """Run Phase 2 standalone inference using the current promoted-model pipeline.

    primary input: ``featured_df`` (전수 모집단). PHASE1 결과는 본 함수의
    detection 입력이나 gate 로 사용되지 않는다. PHASE1 case overlay 는 호출
    이후 ``_attach_phase2_case_overlays`` / ``_inherit_phase1_case_result`` 가
    optional post-step 으로 attach 한다.

    Args:
        batch_id: phase1 분석이 만든 batch_id. phase2 추론은 같은 batch row 의
            phase2 컬럼만 update 하므로 phase1 batch_id 재사용이 필수.
            **DB 영속화 키**일 뿐 ML 입력 gating 과는 무관하다.
    """
    if not batch_id:
        raise RuntimeError(
            "phase2 추론에는 phase1 batch_id 가 반드시 필요합니다. Phase 1 분석을 먼저 실행하세요."
        )
    t0 = time.perf_counter()
    ts0 = now_str()
    snapshot = load_latest_phase2_training_snapshot(ctx)
    log_timing(
        "phase2.inference.load_training_snapshot",
        time.perf_counter() - t0,
        start_ts=ts0,
    )
    if pipeline_cls is None:
        from src.pipeline import AuditPipeline

        pipeline_cls = AuditPipeline

    if ctx is not None:
        pipeline = pipeline_cls(context=ctx, skip_db=False, repo=repo, conn=conn)
    else:
        pipeline = pipeline_cls(settings=settings, skip_db=False)

    phase2_inference_mode = _determine_phase2_inference_mode(snapshot=snapshot)

    # Why: AuditPipeline.redetect 시그니처에 reference_df 파라미터가 없음 — 제거.
    #      reference_df 흐름은 prior-period 비교용으로 redetect 내부에서 직접 사용하지 않음.
    _ = reference_df  # 호출자 호환 — 현재 redetect에서 사용되지 않음
    result = pipeline.redetect(
        featured_df,
        batch_id=batch_id,
        file_name=file_name,
        detection_scope="phase2_only",
        phase2_inference_contract=(
            snapshot.get("inference_contract") if snapshot is not None else None
        ),
        phase2_training_report_id=(snapshot or {}).get("report_id"),
        phase2_promotion_policy=(snapshot or {}).get("promotion_policy"),
        phase2_inference_mode=phase2_inference_mode,
    )
    _attach_phase2_training_contract(result, ctx=ctx, snapshot=snapshot)
    setattr(result, "phase2_inference_mode", phase2_inference_mode)
    t0 = time.perf_counter()
    ts0 = now_str()
    _attach_phase2_case_overlays(result)
    log_timing(
        "phase2.inference.attach_phase2_case_overlays",
        time.perf_counter() - t0,
        start_ts=ts0,
    )
    # S3.next Phase B — orchestrator + linker hook (invariant #84~87).
    # PHASE1 가용 + engagement_salt 가용 시 cross-reference 까지 완성한다.
    t0 = time.perf_counter()
    ts0 = now_str()
    _attach_phase2_case_set(result, ctx=ctx, snapshot=snapshot)
    log_timing(
        "phase2.inference.attach_phase2_case_set",
        time.perf_counter() - t0,
        start_ts=ts0,
    )
    t0 = time.perf_counter()
    ts0 = now_str()
    persist_warning = _persist_phase2_batch_snapshot(conn=conn, result=result)
    log_timing(
        "phase2.inference.persist_batch_meta",
        time.perf_counter() - t0,
        start_ts=ts0,
    )
    if persist_warning:
        _append_result_warning(result, persist_warning)
    result.file_name = file_name
    return result


def run_phase2_inference_analysis(
    state,
    *,
    partition: str | int | None = None,
    inference_runner: Callable[..., Any] | None = None,
    settings_factory: Callable[[], Any] | None = None,
):
    """Execute Phase 2 standalone inference from dashboard/session state.

    primary input  : ``prep_result.featured_data`` (없으면 ``prep_result.data``).
                     Phase 2 family detector 는 이 frame 전체에서 score 를 만든다.
    optional overlay context: ``state[KEY_PHASE1_RESULT]`` — 추론 완료 후
                     ``_inherit_phase1_case_result`` 가 case overlay 를 attach 한다.
    batch_id       : PHASE1 batch row 재사용 (DB 영속화 키). PHASE1 분석이 없으면
                     RuntimeError. ML 입력 gating 과는 무관.
    """
    from dashboard._state import (
        KEY_BATCH_ID,
        KEY_COMPANY_CONTEXT,
        KEY_PHASE1_RESULT,
        KEY_PHASE2_RESULT,
        KEY_PIPELINE_RESULT,
        KEY_PREP_RESULT,
        KEY_SETTINGS,
    )
    from src.services.analysis_service import make_phase_settings

    if inference_runner is None:
        inference_runner = run_phase2_inference

    prep_result = state.get(KEY_PREP_RESULT)
    if prep_result is None:
        raise RuntimeError("준비 결과가 없습니다.")

    # Why: phase2 는 phase1 batch_id 를 그대로 재사용해 같은 row 의 phase2 컬럼만
    #      UPDATE 한다. phase1 결과가 없으면 phase2 자체가 의미 없고, batch_id 가
    #      없으면 redetect 가 orphan row 를 만들 위험이 있어 명시적 에러.
    phase1_result = state.get(KEY_PHASE1_RESULT)
    phase1_batch_id = str(getattr(phase1_result, "batch_id", "") or "") if phase1_result else ""
    if not phase1_batch_id:
        raise RuntimeError(
            "Phase 1 분석이 완료되지 않았습니다. "
            "Phase 2 추론은 Phase 1 결과의 batch_id 를 재사용합니다."
        )

    featured_df = (
        prep_result.featured_data if prep_result.featured_data is not None else prep_result.data
    )
    # P4: featured_df 의 partition 필터 결과를 status 로 추적해 result 에 attach.
    #     reference_df 는 prior period 용이라 같은 status 를 따로 노출할 필요 없음.
    featured_df, partition_status = _apply_partition_filter_with_status(featured_df, partition)
    reference_df = _resolve_reference_df(state, prep_result)
    reference_df = _apply_partition_filter(reference_df, partition)
    ctx = state.get(KEY_COMPANY_CONTEXT)
    repo = state.get("_company_repo")
    conn_mgr = state.get("_conn_mgr")
    settings = make_phase_settings(
        state.get(KEY_SETTINGS),
        phase="phase2",
        settings_factory=settings_factory,
    )

    conn = None
    if ctx is not None:
        ctx = ctx.clone_with_settings(settings)
        conn = conn_mgr.get(str(ctx.db_path)) if conn_mgr is not None else None

    result = inference_runner(
        featured_df,
        batch_id=phase1_batch_id,
        file_name=prep_result.file_name,
        reference_df=reference_df,
        ctx=ctx,
        settings=settings if ctx is None else None,
        repo=repo,
        conn=conn,
    )
    setattr(result, "phase2_partition", _normalize_partition_label(partition))
    # P4-2: partition execution status — UI 가 fallback 사유를 명시할 수 있도록 attach.
    setattr(result, "phase2_requested_partition", partition_status.get("requested"))
    setattr(result, "phase2_executed_partition", partition_status.get("executed"))
    setattr(
        result,
        "phase2_partition_fallback_reason",
        partition_status.get("fallback_reason"),
    )
    # P4-3: context status — overlay/snapshot 영속화가 ctx 의존이라 attach 해서 UI 분기.
    _attach_phase2_context_status(result, ctx)
    t0 = time.perf_counter()
    ts0 = now_str()
    _inherit_phase1_case_result(result, state.get(KEY_PHASE1_RESULT))
    log_timing(
        "phase2.inference.inherit_phase1_case",
        time.perf_counter() - t0,
        start_ts=ts0,
    )

    state[KEY_PHASE2_RESULT] = result
    state[KEY_BATCH_ID] = result.batch_id
    state[KEY_PIPELINE_RESULT] = result

    # Why: overlay 본체를 engagement 폴더 JSON 으로 영속화.
    #      새로고침 / 같은 batch 재로드 시 KPI · case-level attribution 이 빈 상태가 되지 않도록.
    t0 = time.perf_counter()
    ts0 = now_str()
    _persist_phase2_overlays_to_disk(state, result)
    log_timing(
        "phase2.inference.persist_overlays",
        time.perf_counter() - t0,
        start_ts=ts0,
    )
    t0 = time.perf_counter()
    ts0 = now_str()
    _store_featured_data_best_effort(
        state,
        result.featured_data if getattr(result, "featured_data", None) is not None else featured_df,
        result=result,
    )
    log_timing(
        "phase2.inference.store_featured_data",
        time.perf_counter() - t0,
        start_ts=ts0,
    )
    return result


def _store_featured_data_best_effort(state, featured_df, *, result) -> None:
    """Keep Phase 2 inference success even if dashboard cache write fails.

    Phase 2 inference already stores the authoritative result in `KEY_PHASE2_RESULT`.
    The featured-data session slot is a dashboard cache inherited from earlier phases,
    so write failures here must be warnings, not inference failures.
    """
    from dashboard._state import KEY_FEATURED_DATA

    try:
        state[KEY_FEATURED_DATA] = featured_df
    except RuntimeError as exc:
        _append_result_warning(
            result,
            f"Phase 2 featured_data 세션 저장 스킵: {exc}",
        )


def _append_result_warning(result, warning: str) -> None:
    warnings = list(getattr(result, "warnings", []) or [])
    warnings.append(warning)
    setattr(result, "warnings", warnings)


def _inherit_phase1_case_result(result, phase1_result) -> None:
    """Phase 2 추론 결과에 PHASE1 case overlay 를 **post-inference attach** 한다.

    본 함수는 standalone Phase 2 추론이 끝난 뒤에만 호출되는 overlay join
    step 이다. Phase 2 detection 입력이나 score 산출에는 영향이 없으며,
    PHASE1 결과가 없으면 status 만 attach 하고 그대로 return 한다.

    Phase 1 case basis 를 분류하고 ``result`` 에 status + canonical case 를 attach.

    명시적 단계:
        1. ``classify_phase1_case_basis(phase1_result, redetect_result=result)`` 로
           canonical/fallback/unavailable 등을 분류.
        2. status / message / metadata 를 ``result.phase1_case_basis_*`` 에 attach
           (UI 가 분기 표시할 수 있게).
        3. phase1_result 가 가진 메타(path/run_id/macro/top_themes) 를 result 로 복사.
        4. basis.status 가 canonical_* 이면 ``result.phase1_case_result`` 를 canonical
           로 강제 교체 후 ``_attach_phase2_case_overlays(result)`` 로 overlay 재생성.
        5. fallback_redetect 면 redetect 가 만든 phase1_case_result 그대로 두고
           overlay 도 그대로 (overlay 는 inference 직후 이미 만들어진 상태).

    Why: 기존에는 "canonical 있으면 덮고 overlay 재생성, 없으면 무동작" 흐름이라
    fallback / artifact_error / unavailable 의미가 흐릿했다. 본 함수는 결과를 status
    객체로 노출해 UI / 감사 조서가 phase 2 overlay 의 근거를 명확히 알 수 있게 한다.
    """
    from src.export.phase1_case_view import (
        Phase1CaseBasisStatus,
        classify_phase1_case_basis,
    )

    with TimingBlock("phase2.inference.inherit.classify"):
        basis = classify_phase1_case_basis(phase1_result, redetect_result=result)

    # (2) status attach — 모든 경로에서 일관되게.
    setattr(result, "phase1_case_basis_status", basis.status)
    setattr(result, "phase1_case_basis_message", basis.message)
    setattr(result, "phase1_case_basis_metadata", dict(basis.metadata))

    if phase1_result is None:
        return

    # (3) phase1 메타 복사 (가벼움)
    overridden = False
    for attr in (
        "phase1_case_path",
        "phase1_case_run_id",
        "phase1_case_count",
        "phase1_macro_finding_count",
        "phase1_top_theme_ids",
    ):
        if hasattr(phase1_result, attr):
            setattr(result, attr, getattr(phase1_result, attr))
            overridden = True

    # (4) canonical 일 때만 case_result 덮어쓰기 + overlay 재생성
    canonical_statuses = (
        Phase1CaseBasisStatus.CANONICAL_IN_MEMORY,
        Phase1CaseBasisStatus.CANONICAL_ARTIFACT,
    )
    if basis.status in canonical_statuses and basis.case_result is not None:
        setattr(result, "phase1_case_result", basis.case_result)
        setattr(
            result,
            "phase1_case_count",
            len(getattr(basis.case_result, "cases", []) or []),
        )
        try:
            phase1_result.phase1_case_result = basis.case_result
        except Exception:
            pass
        with TimingBlock("phase2.inference.inherit.attach_overlays_canonical"):
            _attach_phase2_case_overlays(result)
    elif overridden:
        with TimingBlock("phase2.inference.inherit.attach_overlays_meta"):
            _attach_phase2_case_overlays(result)


def _resolve_reference_df(state, prep_result):
    reference_df = getattr(prep_result, "reference_data", None)
    if reference_df is not None:
        return reference_df
    return state.get("reference_data")


def _apply_partition_filter(df, partition: str | int | None):
    """기존 호출자 호환 — fallback 발생해도 silent. status 가 필요한 호출자는
    ``_apply_partition_filter_with_status`` 를 사용한다.
    """
    filtered, _status = _apply_partition_filter_with_status(df, partition)
    return filtered


def _apply_partition_filter_with_status(
    df,
    partition: str | int | None,
) -> tuple[Any, dict[str, Any]]:
    """``_apply_partition_filter`` 의 명시 버전. fallback 사유까지 함께 반환.

    Returns:
        (df, status) — status keys: ``requested`` (정규화된 partition), ``executed``
        (실제 사용된 partition), ``fallback_reason`` (fallback 시 사유 문자열, 그 외 None).
    """
    requested = _normalize_partition_label(partition)
    if df is None:
        return None, {
            "requested": requested,
            "executed": requested,
            "fallback_reason": None,
        }
    if requested == "전체" or "fiscal_year" not in getattr(df, "columns", []):
        return df, {
            "requested": requested,
            "executed": requested,
            "fallback_reason": None,
        }
    year = int(requested)
    filtered = df[df["fiscal_year"].astype("Int64") == year].copy()
    if filtered.empty:
        import logging

        logging.getLogger(__name__).warning(
            "phase2 partition '%s' produced 0 rows — falling back to full dataset",
            requested,
        )
        return df, {
            "requested": requested,
            "executed": "전체",
            "fallback_reason": "selected_year_zero_rows",
        }
    return filtered, {
        "requested": requested,
        "executed": requested,
        "fallback_reason": None,
    }


def _normalize_partition_label(partition: str | int | None) -> str:
    if partition is None:
        return "전체"
    text = str(partition)
    return text if text in {"2022", "2023", "2024"} else "전체"


def _attach_phase2_training_contract(result, *, ctx=None, snapshot=None) -> None:
    if snapshot is None:
        snapshot = load_latest_phase2_training_snapshot(ctx)
    if not snapshot:
        return
    setattr(result, "phase2_training_report_id", snapshot.get("report_id"))
    setattr(result, "phase2_inference_contract", snapshot.get("inference_contract"))
    setattr(result, "phase2_promotion_policy", snapshot.get("promotion_policy"))


def _attach_phase2_case_overlays(result) -> None:
    """PHASE1 case 별 PHASE2 overlay 부착 — Phase 2 standalone 결과의 post-step.

    Row-level detector scores are aggregated into PHASE1 cases for display and
    narrator attribution only. This is **overlay join after standalone Phase 2
    inference** and must not rewrite PHASE1 priority or queue ordering.
    """
    phase1 = getattr(result, "phase1_case_result", None)
    overlay_inputs = build_phase2_case_family_overlay_inputs(
        getattr(result, "data", None),
        list(getattr(result, "results", []) or []),
        phase1,
    )
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case=overlay_inputs.family_scores_by_case,
        family_ecdf_by_case=overlay_inputs.family_ecdf_by_case,
        family_top_subdetectors_by_case=overlay_inputs.family_top_subdetectors_by_case,
        family_review_only_by_case=overlay_inputs.family_review_only_by_case,
        family_roles=overlay_inputs.family_roles,
        family_q95_thresholds=overlay_inputs.family_q95_thresholds,
        detector_statuses=getattr(result, "detector_statuses", None) or [],
        phase2_inference_contract=getattr(result, "phase2_inference_contract", None),
        phase2_training_report_id=getattr(result, "phase2_training_report_id", None),
        duplicate_pair_evidence_by_case=overlay_inputs.duplicate_pair_evidence_by_case,
        family_explanation_features_by_case=(overlay_inputs.family_explanation_features_by_case),
        relational_continuity_depth_by_case=(overlay_inputs.relational_continuity_depth_by_case),
    )
    setattr(result, "phase2_case_overlays", overlays)


def _attach_phase2_case_set(result, *, ctx=None, snapshot=None) -> None:
    """S3.next Phase B — orchestrator + linker hook (invariant #84~87).

    Why: PHASE2 detection 산출 후 5 family native case set 을 조립해 ``result`` 에
    부착한다. PHASE1 가용 + engagement_salt 가용 시 linker 호출하여
    cross-reference 까지 완성한다.

    호출자 책임 (attach 정책 lock):
    - ``result.results`` / ``data`` / ``batch_id`` 부재 → graceful skip (#84).
    - ``engagement_salt = ctx.engagement_id + batch_id`` (없으면 ``salt=None`` —
      linker auto resolve 가 position fallback) (#85).
    - PHASE1 부재 → linker skip, case_set 만 부착 (linked=False) (#86).
    - unsupervised ``model_id`` / ``schema_hash`` 는 snapshot 에서 도출, 부재 시
      빈 문자열 (#87).
    """
    # circular import 방어 — function-level lazy import (orchestrator / linker 가
    # 본 모듈을 import 하지는 않지만, 추후 PHASE1 builder 가 inference service 를
    # 참조할 때를 대비해 한 방향성을 유지한다).
    from src.services.phase2_case_phase1_linker import link_phase2_to_phase1
    from src.services.phase2_case_set_orchestrator import build_phase2_case_set

    detection_results = getattr(result, "results", None)
    df = getattr(result, "data", None)
    batch_id = getattr(result, "batch_id", "") or ""
    # invariant #84 — graceful skip. ValueError 던지지 않는다.
    if not detection_results or df is None or not batch_id:
        return

    # invariant #87 — snapshot 에서 model_id / schema_hash 도출. 부재 시 빈 문자열.
    model_id = ""
    schema_hash = ""
    if isinstance(snapshot, dict):
        model_id = str(snapshot.get("report_id") or "")
        contract = snapshot.get("inference_contract") or {}
        if isinstance(contract, dict):
            schema_hash = str(contract.get("schema_hash") or "")

    case_set = build_phase2_case_set(
        batch_id=batch_id,
        detection_results=list(detection_results),
        df=df,
        unsupervised_model_id=model_id,
        unsupervised_schema_hash=schema_hash,
    )

    # invariant #85 — engagement_salt = ctx.engagement_id + batch_id.
    engagement_id = ""
    if ctx is not None:
        engagement_id = str(getattr(ctx, "engagement_id", "") or "")
    engagement_salt: str | None = f"{engagement_id}|{batch_id}" if engagement_id else None

    # invariant #86 — PHASE1 가용 시 linker 호출. 부재면 case_set 만 부착.
    phase1 = getattr(result, "phase1_case_result", None)
    if phase1 is not None:
        try:
            linker_result = link_phase2_to_phase1(
                case_set=case_set,
                phase1=phase1,
                row_ref_map=None,  # hit hash direct path (S6.next Phase 2)
                salt=engagement_salt,
                key_mode="auto",
            )
            case_set = linker_result.case_set
            setattr(result, "phase2_linker_diagnostics", linker_result.diagnostics)
        except ValueError as exc:
            # hash 기반 mode 가 salt 필요한데 도출 실패한 경우의 안전 가드 —
            # 실제로는 key_mode="auto" 가 salt 부재 시 position 으로 fallback 하므로
            # 거의 발생하지 않지만, 예기치 못한 ValueError 가 inference 전체를
            # 막지 않도록 warning 누적 후 case_set 만 부착한다.
            _append_result_warning(result, f"phase2_case_set linker skipped: {exc}")

    setattr(result, "phase2_case_set", case_set)
    _attach_phase2_family_policy_summary(result, case_set)

    # invariant #88 (S3.next Phase B Followup) — case_set artifact 영속화.
    # Why: in-memory PipelineResult 만으로는 dashboard refresh / reload 시 손실.
    # linker 통과한 linked case_set 을 저장 — manifest.linked_case_hash 가 자연스러움.
    # ctx / salt 부재 시 store 가 graceful skip (CTX_MISSING / SALT_MISSING) — 본 hook
    # 은 그 결과를 warning 으로만 기록하고 inference 전체는 계속 진행.
    if ctx is not None and engagement_salt:
        try:
            from src.services.phase2_case_store import save_phase2_case_set

            # Why: store manifest key_mode 는 linker resolved capability 와 정합 (#49).
            # linker 가 호출돼서 diagnostics 가 있으면 그 값 사용. 아니면 "position".
            diagnostics = getattr(result, "phase2_linker_diagnostics", None) or {}
            resolved_key_mode = str(diagnostics.get("key_mode_used") or "position")
            store_result = save_phase2_case_set(
                ctx=ctx,
                batch_id=batch_id,
                case_set=case_set,
                salt=engagement_salt,
                key_mode=resolved_key_mode,
                phase2_training_report_id=model_id or None,
            )
            if store_result.status != "saved":
                _append_result_warning(
                    result,
                    f"phase2_case_set persist skipped: status={store_result.status}",
                )
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            _append_result_warning(result, f"phase2_case_set persist failed: {exc}")


def _attach_phase2_family_policy_summary(result, case_set) -> None:
    """Attach aggregate-only native family role metadata.

    This metadata lets dashboard/session consumers preserve the IC product role
    without reading fixed5 diagnostic artifacts or changing UI layout. It is not
    consumed by detectors, gates, ranking, fusion, or PHASE1 priority logic.
    """
    if result is None or case_set is None:
        return
    from src.services.phase2_family_policy import (
        INTERCOMPANY_BROAD_RECALL_EXPANSION_FAMILY,
        INTERCOMPANY_PRODUCT_ROLE,
        build_duplicate_policy_summary,
        build_relational_policy_summary,
        build_timeseries_policy_summary,
        build_unsupervised_policy_summary,
    )

    duplicate_cases = tuple(getattr(case_set, "duplicate_cases", ()) or ())
    intercompany_cases = tuple(getattr(case_set, "intercompany_cases", ()) or ())
    relational_cases = tuple(getattr(case_set, "relational_cases", ()) or ())
    timeseries_cases = tuple(getattr(case_set, "timeseries_cases", ()) or ())
    unsupervised_cases = tuple(getattr(case_set, "unsupervised_cases", ()) or ())
    reciprocal_count = sum(
        1 for case in intercompany_cases if str(getattr(case, "ic_role", "")) == "reciprocal_flow"
    )
    mismatch_count = sum(
        1 for case in intercompany_cases if str(getattr(case, "ic_role", "")) == "amount_mismatch"
    )
    summary = dict(getattr(result, "phase2_family_policy_summary", None) or {})
    summary["intercompany"] = {
        "primary_product_role": INTERCOMPANY_PRODUCT_ROLE,
        "broad_recall_expansion_family": INTERCOMPANY_BROAD_RECALL_EXPANSION_FAMILY,
        "production_adoption": False,
        "production_ranking_changed": False,
        "new_policy_adopted": False,
        "ic_gate_changed": False,
        "phase2_fusion_changed": False,
        "phase1_ranking_changed": False,
        "case_count": len(intercompany_cases),
        "reciprocal_flow_case_count": reciprocal_count,
        "amount_mismatch_case_count": mismatch_count,
        "interpretation": (
            "Intercompany native cases strengthen PHASE1 review candidates with "
            "IC-specific reciprocal/pair evidence; production_adoption=false means "
            "no new ranking or gate policy was adopted, not that IC is disabled."
        ),
    }
    summary["relational"] = build_relational_policy_summary(relational_cases)
    summary["duplicate"] = build_duplicate_policy_summary(duplicate_cases)
    summary["timeseries"] = build_timeseries_policy_summary(timeseries_cases)
    summary["unsupervised"] = build_unsupervised_policy_summary(unsupervised_cases)
    setattr(result, "phase2_family_policy_summary", summary)


# P4: DB load status axis 상수. UI 가 4 status 별 caption 을 분기 표시한다.
class _Phase2DbLoadStatus:
    SAVED = "saved"
    SKIPPED_NO_CONN = "skipped_no_conn"
    SKIPPED_NO_LOAD_RESULT = "skipped_no_load_result"
    FAILED = "failed"


# P4-3: context status axis 상수. overlay/snapshot 영속화가 ctx 에 의존하므로 attach.
class _Phase2ContextStatus:
    COMPANY_CONTEXT = "company_context"
    MISSING_CONTEXT = "missing_context"
    MISSING_DB_PATH = "missing_db_path"


def _attach_phase2_context_status(result, ctx) -> None:
    """ctx 유효성을 분류해 result 에 status/message attach.

    상태:
        - ``company_context``: ctx 존재 + ``ctx.db_path`` 유효.
        - ``missing_db_path``: ctx 는 있지만 ``db_path`` 가 없거나 빈 값.
        - ``missing_context``: ctx 자체가 None.

    Why: 새로고침 후 overlay 복원 / 모델 snapshot 로드가 모두 ``ctx.db_path`` 와
    ``ctx.model_dir`` 에 의존한다. ctx 가 없으면 in-memory 분석은 가능하지만
    재진입 시 결과가 사라진다. UI 가 사용자에게 그 사실을 미리 안내해야 한다.
    """
    if result is None:
        return
    if ctx is None:
        status = _Phase2ContextStatus.MISSING_CONTEXT
        message = "no company/engagement context — Phase 2 persistence is disabled"
    elif not getattr(ctx, "db_path", None):
        status = _Phase2ContextStatus.MISSING_DB_PATH
        message = "company context present but db_path is empty"
    else:
        status = _Phase2ContextStatus.COMPANY_CONTEXT
        message = "company context active"
    try:
        setattr(result, "phase2_context_status", status)
        setattr(result, "phase2_context_message", message)
    except (AttributeError, TypeError):
        return


def _persist_phase2_batch_snapshot(*, conn=None, result=None) -> str | None:
    """batch_meta 에 phase2 메타 컬럼 update 후 status 를 result 에 attach.

    Why: 호출자가 단순히 warning string 만 받으면 DB 저장 실패 vs skip vs 성공을 구분
    못 한다. 본 함수가 status / message 를 ``result.phase2_db_load_status`` 와
    ``phase2_db_load_message`` 에 attach 해 UI 분기에 사용된다.

    Backward compat: 기존 호출자는 warning string (failed 일 때) 또는 None (그 외) 반환을
    그대로 받는다.
    """
    batch_id = getattr(result, "batch_id", "") if result is not None else ""

    if conn is None:
        _attach_db_load_status(
            result,
            _Phase2DbLoadStatus.SKIPPED_NO_CONN,
            "no DB connection — Phase 2 DB metadata persistence skipped",
        )
        return None
    # Why: phase2_only 추론은 _load_db 를 스킵하므로 load_result 가 None 이다. 그래도
    #      phase1 batch row 가 이미 DB 에 존재하므로 batch_id 만으로 UPDATE 가능하다.
    #      batch_id 자체가 비어 있을 때만 skip.
    if not batch_id:
        _attach_db_load_status(
            result,
            _Phase2DbLoadStatus.SKIPPED_NO_LOAD_RESULT,
            "no batch_id — Phase 2 DB metadata persistence skipped",
        )
        return None
    try:
        from src.db.loader import update_upload_batch_meta

        update_upload_batch_meta(
            conn,
            batch_id,
            phase2_training_report_id=getattr(result, "phase2_training_report_id", None),
            phase2_inference_contract=getattr(result, "phase2_inference_contract", None),
            phase2_promotion_policy=getattr(result, "phase2_promotion_policy", None),
            phase2_inference_mode=getattr(result, "phase2_inference_mode", None),
            detector_statuses=getattr(result, "detector_statuses", None),
        )
    except Exception as exc:
        message = f"Phase 2 DB 메타 저장 실패: {exc}"
        _attach_db_load_status(result, _Phase2DbLoadStatus.FAILED, message)
        return message
    _attach_db_load_status(result, _Phase2DbLoadStatus.SAVED, "saved")
    return None


def _attach_db_load_status(result, status: str, message: str) -> None:
    if result is None:
        return
    try:
        setattr(result, "phase2_db_load_status", status)
        setattr(result, "phase2_db_load_message", message)
    except (AttributeError, TypeError):
        return


def _persist_phase2_overlays_to_disk(state, result) -> None:
    """Engagement 폴더에 phase2_case_overlays JSON 저장 (best-effort).

    Why: ``_persist_phase2_batch_snapshot`` 은 메타데이터(report_id/contract/mode)
    만 DB 에 기록한다. overlay 본체(family_contributions/lane/tier)는 메모리에만
    존재해 새로고침 시 사라진다. engagement 폴더의 JSON 파일로 영속화해
    ``batch_service.load_batch_into_state`` 에서 다시 attach 한다.
    """
    from dashboard._state import KEY_COMPANY_CONTEXT
    from src.services.phase2_overlay_store import save_phase2_overlays

    ctx = state.get(KEY_COMPANY_CONTEXT)
    batch_id = str(getattr(result, "batch_id", "") or "")
    if ctx is None or not batch_id:
        return
    overlays = list(getattr(result, "phase2_case_overlays", None) or [])
    save_phase2_overlays(
        ctx=ctx,
        batch_id=batch_id,
        overlays=overlays,
        phase2_training_report_id=getattr(result, "phase2_training_report_id", None),
        phase2_partition=getattr(result, "phase2_partition", None),
    )


def _determine_phase2_inference_mode(*, snapshot: dict[str, Any] | None, result=None) -> str:
    if snapshot is not None:
        return "training_contract"
    return "untrained_contract_only"


def load_latest_phase2_training_snapshot(ctx=None) -> dict[str, Any] | None:
    model_dir = getattr(ctx, "model_dir", None) if ctx is not None else None
    if model_dir is None:
        return None
    reports_root = Path(model_dir) / "phase2_train"
    if not reports_root.exists():
        return None
    report_paths = sorted(
        reports_root.glob("*/reports/training_report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for report_path in report_paths:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        metadata = payload.get("metadata", {}) or {}
        reports_dir = report_path.parent
        return {
            "report_id": payload.get("report_id"),
            "inference_contract": metadata.get("inference_contract"),
            "promotion_policy": metadata.get("promotion_policy"),
            "report_path": str(report_path),
            "leaderboard_artifact": _read_json_artifact(reports_dir / "leaderboard.json"),
            "promotion_decision_artifact": _read_json_artifact(
                reports_dir / "promotion_decision.json",
            ),
        }
    return None


def _read_json_artifact(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
