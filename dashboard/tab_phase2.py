from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from dashboard._state import (
    KEY_ACTIVE_RESULT_TAB,
    KEY_LOADED_FROM_DB,
    KEY_PENDING_RESULT_TAB,
    KEY_PHASE2_TRAINING_REPORT_ID,
    PAGE_PHASE2,
)
from src.detection.constants import get_track_display_label

if TYPE_CHECKING:
    from src.metrics.models import PerformanceReport
    from src.pipeline import PipelineResult
    from src.preprocessing.model_registry import ModelMetadata


def render(prep_result, result: PipelineResult | None) -> None:
    from dashboard.components.scroll_anchor import preserve_scroll_position

    preserve_scroll_position("phase2")

    st.subheader("Phase 2 추가 분석")

    if result is None:
        st.info("아직 Phase 2 추가 분석 결과가 없습니다.")
        if prep_result is None:
            return
        if st.session_state.get(KEY_LOADED_FROM_DB):
            return
        # Why: spinner 는 _start_phase2_analysis 내부에 한 번만 띄운다.
        #      호출부에서 또 감싸면 동일 메시지가 두 줄로 표시된다.
        if st.button("Phase 2 분석 시작", type="primary", key="run_phase2"):
            _start_phase2_analysis()
        return

    st.caption(
        "Phase 1에서 찾은 의심 거래를 바탕으로, 저장된 모델 기준이 있으면 "
        "그 기준으로 패턴을 한 번 더 점검합니다."
    )
    _render_phase2_current_state(result)
    st.caption("어떤 기준으로 추가 분석했는지와 실행된 탐지 항목을 확인한 뒤 결과를 검토하세요.")
    _render_status_grid(result)
    st.divider()
    _render_performance_report(result)
    st.divider()
    _render_track_status(result)


def _render_phase2_current_state(result: PipelineResult | None) -> None:
    cards = _build_phase2_provenance_cards(result)
    if not cards:
        return
    columns = st.columns(len(cards))
    for column, (label, value) in zip(columns, cards):
        column.metric(label, value)


def _render_training_snapshot_summary() -> None:
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


def _start_phase2_analysis() -> None:
    """Run Phase 2 inference from the empty-result placeholder.

    Why: KEY_TOP_LEVEL_NAV 는 widget key — _consume_pending_page 가 다음 run 의
         widget 렌더 전에 KEY_PENDING_RESULT_TAB 를 옮긴다.
    """
    from src.services.phase2_inference_service import run_phase2_inference_analysis

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2

    with st.spinner("Phase 2 추가 분석 실행 중..."):
        try:
            run_phase2_inference_analysis(st.session_state)
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
            st.error(f"Phase 2 모델 기준 준비 실패: {e}")
            return
    st.session_state[KEY_PHASE2_TRAINING_REPORT_ID] = report.report_id
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
