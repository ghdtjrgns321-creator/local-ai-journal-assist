"""Service-layer orchestration around pipeline execution."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

import pandas as pd

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_DISABLED_RULES,
    KEY_FEATURED_DATA,
    KEY_LAYER_WEIGHTS,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_RISK_THRESHOLDS,
    KEY_SETTINGS,
    KEY_SETTINGS_DIRTY,
)


def make_phase_settings(
    base_settings,
    *,
    phase: str,
    settings_factory: Callable[[], Any] | None = None,
):
    """Build phase-specific detector settings from the current baseline settings."""
    settings = base_settings
    if settings is None:
        factory = settings_factory
        if factory is None:
            from config.settings import get_settings

            factory = get_settings
        settings = factory()

    updates = {
        "enable_variance_detection": True,
        "enable_relational_detection": False,
        "enable_graph_detection": False,
        "enable_nlp_detection": False,
        "enable_access_audit_detection": False,
        "enable_evidence_detection": True,
        "enable_trendbreak_detection": False,
        "enable_ml_detection": False,
    }
    if phase == "phase2":
        updates["enable_ml_detection"] = True
    return settings.model_copy(update=updates)


def build_phase1_core_feature_frame(prep_result, settings, ctx=None) -> pd.DataFrame:
    """Build only the feature categories required by PHASE1 L1-L4 + L3-11 + D01/D02."""

    from config.settings import get_audit_rules, get_risk_keywords
    from src.feature.engine import (
        PHASE1_CORE_RULE_IDS,
        feature_categories_for_rules,
        generate_all_features,
    )

    base_df = prep_result.data.copy()
    rules = getattr(ctx, "audit_rules", None) if ctx is not None else None
    risk_keywords = getattr(ctx, "risk_keywords", None) if ctx is not None else None
    feat = generate_all_features(
        base_df,
        settings=settings,
        rules=rules or get_audit_rules(),
        risk_keywords=risk_keywords or get_risk_keywords(),
        categories=feature_categories_for_rules(PHASE1_CORE_RULE_IDS),
        include_morpheme_tokens=False,
    )
    return feat.data


def build_audit_trail(ctx):
    """Create an engagement-bound AuditTrail if the current context supports it."""
    if ctx is None or getattr(ctx, "is_anonymous", True):
        return None
    try:
        from src.db.connection import get_connection
        from src.export.audit_trail import AuditTrail

        return AuditTrail(get_connection(str(ctx.db_path)))
    except Exception:  # pragma: no cover - defensive UI fallback
        import logging

        logging.getLogger(__name__).warning(
            "AuditTrail 생성 실패 -> 증적 기록 없이 진행", exc_info=True,
        )
        return None


def run_phase_analysis(
    state: MutableMapping[str, Any],
    *,
    phase: str,
    pipeline_cls=None,
    settings_factory: Callable[[], Any] | None = None,
):
    """Execute a phase-specific redetect flow and persist the result into state."""
    import time
    from datetime import datetime

    _t_start = time.perf_counter()
    print(
        f"[TIMING] {phase} START at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}",
        flush=True,
    )

    if pipeline_cls is None:
        from src.pipeline import AuditPipeline

        pipeline_cls = AuditPipeline

    prep_result = state.get(KEY_PREP_RESULT)
    if prep_result is None:
        raise RuntimeError("준비 결과가 없습니다.")

    ctx = state.get(KEY_COMPANY_CONTEXT)
    repo = state.get("_company_repo")
    conn_mgr = state.get("_conn_mgr")
    settings = make_phase_settings(
        state.get(KEY_SETTINGS),
        phase=phase,
        settings_factory=settings_factory,
    )

    _t_feat = time.perf_counter()
    if phase == "phase1":
        featured_df = build_phase1_core_feature_frame(prep_result, settings, ctx)
    else:
        featured_df = (
            prep_result.featured_data
            if prep_result.featured_data is not None
            else prep_result.data
        )
    _t_feat_end = time.perf_counter()
    print(
        f"[TIMING] {phase} feature_build = {_t_feat_end - _t_feat:.2f}s "
        f"(rows={len(featured_df):,}, cols={len(featured_df.columns):,})",
        flush=True,
    )

    if ctx is not None:
        ctx = ctx.clone_with_settings(settings)
        conn = conn_mgr.get(str(ctx.db_path)) if conn_mgr is not None else None
        pipeline = pipeline_cls(context=ctx, skip_db=False, repo=repo, conn=conn)
    else:
        pipeline = pipeline_cls(settings=settings, skip_db=False)

    _t_det = time.perf_counter()
    result = pipeline.redetect(
        featured_df,
        batch_id="",
        file_name=prep_result.file_name,
        detection_scope="phase1_core" if phase == "phase1" else "default",
    )
    _t_det_end = time.perf_counter()
    print(
        f"[TIMING] {phase} redetect = {_t_det_end - _t_det:.2f}s",
        flush=True,
    )
    result.file_name = prep_result.file_name

    if phase == "phase1":
        state[KEY_PHASE1_RESULT] = result
    else:
        state[KEY_PHASE2_RESULT] = result

    state[KEY_BATCH_ID] = result.batch_id
    state[KEY_PIPELINE_RESULT] = result
    state[KEY_FEATURED_DATA] = featured_df

    _t_total = time.perf_counter() - _t_start
    result.elapsed = _t_total
    print(
        f"[TIMING] {phase} TOTAL = {_t_total:.2f}s ({_t_total / 60:.2f}min)",
        flush=True,
    )
    return result


def rerun_detection(
    state: MutableMapping[str, Any],
    *,
    pipeline_cls=None,
) -> bool:
    """Rerun detection from featured data using current interactive dashboard settings."""
    if pipeline_cls is None:
        from src.pipeline import AuditPipeline

        pipeline_cls = AuditPipeline

    featured_df = state.get(KEY_FEATURED_DATA)
    if featured_df is None:
        return False

    settings = state.get(KEY_SETTINGS)
    weights = state.get(KEY_LAYER_WEIGHTS)
    thresholds = state.get(KEY_RISK_THRESHOLDS)
    batch_id = state.get(KEY_BATCH_ID, "")

    ctx = state.get(KEY_COMPANY_CONTEXT)
    repo = state.get("_company_repo")
    audit_trail = build_audit_trail(ctx)
    if ctx is not None and settings is not None:
        ctx = ctx.clone_with_settings(settings)
        pipeline = pipeline_cls(
            context=ctx, skip_db=True, repo=repo, audit_trail=audit_trail,
        )
    elif ctx is not None:
        pipeline = pipeline_cls(
            context=ctx, skip_db=True, repo=repo, audit_trail=audit_trail,
        )
    else:
        pipeline = pipeline_cls(
            settings=settings, skip_db=True, audit_trail=audit_trail,
        )
    result = pipeline.redetect(
        featured_df,
        batch_id=batch_id,
        weights=weights,
        thresholds=thresholds,
    )

    disabled = state.get(KEY_DISABLED_RULES, [])
    if disabled:
        _filter_disabled_rules(result, disabled)

    state[KEY_PIPELINE_RESULT] = result
    state[KEY_SETTINGS_DIRTY] = False
    return True


def _filter_disabled_rules(result, disabled: list[str]) -> None:
    """Remove disabled rule effects from result details and aggregate strings."""
    from copy import deepcopy

    new_results = []
    for detection_result in result.results:
        new_result = deepcopy(detection_result)
        for code in disabled:
            if code in new_result.details.columns:
                new_result.details[code] = 0.0
        new_results.append(new_result)
    result.results = new_results

    if disabled and {"flagged_rules", "review_rules"}.intersection(result.data.columns):
        import re

        pattern = "|".join(re.escape(rule_code) for rule_code in disabled)
        for column in ("flagged_rules", "review_rules"):
            if column in result.data.columns:
                result.data[column] = (
                    result.data[column]
                    .str.replace(rf"\b({pattern})\b,?\s*", "", regex=True)
                    .str.strip(",")
                    .str.strip()
                )
