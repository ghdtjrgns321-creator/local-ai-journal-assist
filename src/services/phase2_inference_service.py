"""Service helpers for Phase 2 inference-only execution."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.services.phase2_case_contract import build_phase2_case_overlays


def run_phase2_inference(
    featured_df,
    *,
    file_name: str = "",
    reference_df=None,
    ctx=None,
    settings=None,
    repo=None,
    conn=None,
    pipeline_cls=None,
):
    """Run Phase 2 inference using the current promoted-model aware pipeline."""
    snapshot = load_latest_phase2_training_snapshot(ctx)
    if pipeline_cls is None:
        from src.pipeline import AuditPipeline

        pipeline_cls = AuditPipeline

    if ctx is not None:
        pipeline = pipeline_cls(context=ctx, skip_db=False, repo=repo, conn=conn)
    else:
        pipeline = pipeline_cls(settings=settings, skip_db=False)

    result = pipeline.redetect(
        featured_df,
        batch_id="",
        file_name=file_name,
        reference_df=reference_df,
        detection_scope="phase2_only",
        phase2_inference_contract=(
            snapshot.get("inference_contract") if snapshot is not None else None
        ),
    )
    _attach_phase2_training_contract(result, ctx=ctx, snapshot=snapshot)
    setattr(
        result,
        "phase2_inference_mode",
        _determine_phase2_inference_mode(snapshot=snapshot, result=result),
    )
    _attach_phase2_case_overlays(result)
    _persist_phase2_batch_snapshot(conn=conn, result=result)
    result.file_name = file_name
    return result


def run_phase2_inference_analysis(
    state,
    *,
    inference_runner: Callable[..., Any] | None = None,
    settings_factory: Callable[[], Any] | None = None,
):
    """Execute Phase 2 inference from dashboard/session state and persist the result."""
    from dashboard._state import (
        KEY_BATCH_ID,
        KEY_COMPANY_CONTEXT,
        KEY_FEATURED_DATA,
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

    featured_df = (
        prep_result.featured_data
        if prep_result.featured_data is not None
        else prep_result.data
    )
    reference_df = _resolve_reference_df(state, prep_result)
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
        file_name=prep_result.file_name,
        reference_df=reference_df,
        ctx=ctx,
        settings=settings if ctx is None else None,
        repo=repo,
        conn=conn,
    )
    _inherit_phase1_case_result(result, state.get(KEY_PHASE1_RESULT))

    if getattr(result, "load_result", None) is None:
        warnings = getattr(result, "warnings", None) or []
        detail = "; ".join(str(w) for w in warnings) if warnings else "DB 적재 실패"
        raise RuntimeError(detail)

    state[KEY_PHASE2_RESULT] = result
    state[KEY_BATCH_ID] = result.batch_id
    state[KEY_PIPELINE_RESULT] = result
    state[KEY_FEATURED_DATA] = (
        result.featured_data
        if getattr(result, "featured_data", None) is not None
        else featured_df
    )
    return result


def _inherit_phase1_case_result(result, phase1_result) -> None:
    if phase1_result is None or getattr(result, "phase1_case_result", None) is not None:
        return
    for attr in (
        "phase1_case_result",
        "phase1_case_path",
        "phase1_case_run_id",
        "phase1_case_count",
        "phase1_macro_finding_count",
        "phase1_top_theme_ids",
    ):
        if hasattr(phase1_result, attr):
            setattr(result, attr, getattr(phase1_result, attr))
    _attach_phase2_case_overlays(result)


def _resolve_reference_df(state, prep_result):
    reference_df = getattr(prep_result, "reference_data", None)
    if reference_df is not None:
        return reference_df
    return state.get("reference_data")


def _attach_phase2_training_contract(result, *, ctx=None, snapshot=None) -> None:
    if snapshot is None:
        snapshot = load_latest_phase2_training_snapshot(ctx)
    if not snapshot:
        return
    setattr(result, "phase2_training_report_id", snapshot.get("report_id"))
    setattr(result, "phase2_inference_contract", snapshot.get("inference_contract"))
    setattr(result, "phase2_promotion_policy", snapshot.get("promotion_policy"))


def _attach_phase2_case_overlays(result) -> None:
    phase1 = getattr(result, "phase1_case_result", None)
    overlays = build_phase2_case_overlays(
        phase1,
        detector_statuses=getattr(result, "detector_statuses", None) or [],
        phase2_inference_contract=getattr(result, "phase2_inference_contract", None),
        phase2_training_report_id=getattr(result, "phase2_training_report_id", None),
    )
    setattr(result, "phase2_case_overlays", overlays)


def _persist_phase2_batch_snapshot(*, conn=None, result=None) -> None:
    batch_id = getattr(result, "batch_id", "") if result is not None else ""
    load_result = getattr(result, "load_result", None) if result is not None else None
    if conn is None or not batch_id or load_result is None:
        return
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
    except Exception:
        # Persisted provenance is best-effort and must not break inference.
        return


def _determine_phase2_inference_mode(*, snapshot: dict[str, Any] | None, result) -> str:
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
        return {
            "report_id": payload.get("report_id"),
            "inference_contract": metadata.get("inference_contract"),
            "promotion_policy": metadata.get("promotion_policy"),
        }
    return None
