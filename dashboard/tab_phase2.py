from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from src.detection.constants import get_track_display_label

if TYPE_CHECKING:
    from src.metrics.models import PerformanceReport
    from src.pipeline import PipelineResult
    from src.preprocessing.model_registry import ModelMetadata


def render(prep_result, result: PipelineResult | None) -> None:
    st.subheader("Phase 2 이상 탐지")
    st.caption(
        "Phase 1 이후에 보는 보조 심화 단계입니다. 룰 기반 탐지에서 "
        "놓칠 수 있는 패턴 기반 이상 징후를 추가로 점검합니다."
    )

    if result is None:
        st.info(
            "아직 Phase 2 분석을 실행하지 않았습니다. 필요할 때만 "
            "추가 실행해서 패턴 기반 이상 징후를 보강하세요."
        )
        _render_prep_metrics(prep_result)
        if st.button("Phase 2 분석 시작", type="primary", key="run_phase2"):
            from dashboard.components.analysis_runner import run_phase_analysis

            with st.spinner("Phase 2 분석 중..."):
                run_phase_analysis(phase="phase2")
            st.rerun()
        return

    st.caption(
        "실행된 추가 탐지 트랙의 상태와 결과 범위를 먼저 확인한 뒤, 운영 상태 표를 검토하세요."
    )
    _render_status_grid(result)
    st.divider()
    _render_performance_report(result)
    st.divider()
    _render_track_status(result)


def _render_prep_metrics(prep_result) -> None:
    data = prep_result.featured_data if prep_result.featured_data is not None else prep_result.data
    c1, c2, c3 = st.columns(3)
    c1.metric("준비 행 수", f"{len(data):,}")
    c2.metric("준비 컬럼 수", f"{len(data.columns):,}")
    c3.metric("준비 경고", f"{len(prep_result.warnings):,}")


def _render_status_grid(result: PipelineResult) -> None:
    statuses = result.detector_statuses or []
    executed = sum(1 for row in statuses if row.get("run_status") == "executed")
    skipped = sum(1 for row in statuses if row.get("run_status") == "skipped")
    experimental = sum(1 for row in statuses if row.get("maturity") == "experimental")
    c1, c2, c3 = st.columns(3)
    c1.metric("실행 트랙", executed)
    c2.metric("건너뜀", skipped)
    c3.metric("실험 단계", experimental)


def _render_performance_report(result: PipelineResult) -> None:
    report = result.performance_report
    if report is None:
        return

    st.markdown("**성능 평가 리포트**")
    cards = _build_performance_cards(report)
    if cards:
        columns = st.columns(len(cards))
        for column, (label, value) in zip(columns, cards):
            column.metric(label, value)

    rule_frame = _build_performance_rule_frame(report)
    if not rule_frame.empty:
        st.dataframe(rule_frame, use_container_width=True, hide_index=True)


def _build_performance_cards(report: PerformanceReport) -> list[tuple[str, str]]:
    cards = [
        ("Flagged Docs", f"{report.flagged_docs:,}"),
        ("High Risk Docs", f"{report.high_risk_docs:,}"),
        ("High Risk Ratio", _format_pct(report.high_risk_ratio)),
        ("False Positives", f"{report.false_positive_docs:,}"),
        ("Confirmed Issues", f"{report.confirmed_issue_docs:,}"),
    ]
    if report.precision is not None:
        cards.append(("Precision", _format_pct(report.precision)))
    if report.recall is not None:
        cards.append(("Recall", _format_pct(report.recall)))
    if report.f1 is not None:
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
            "precision": _format_pct(metric.precision),
            "recall": _format_pct(metric.recall),
            "f1": _format_pct(metric.f1),
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
        active_families = [
            name for name, config in family_statuses.items() if config.get("active")
        ]
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
                    str(item.get("variant"))
                    for item in ablation_plan
                    if item.get("variant")
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
    st.dataframe(df[visible_cols], use_container_width=True, hide_index=True)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _format_years(years) -> str:
    if not years:
        return "-"
    return ", ".join(str(year) for year in years)
