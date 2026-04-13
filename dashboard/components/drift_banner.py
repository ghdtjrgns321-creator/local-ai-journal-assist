"""drift_banner — 모델 드리프트 상태 시각적 경고 배너.

Why: 감사 사이클은 연 1회라 학습 모델이 1년 이상 재사용되는 경우가 많다.
     `src/preprocessing/drift_detector`의 PSI 결과를 대시보드 상단에 고정 배너로
     표시하여 감사인에게 "재학습이 필요한 모델" 신호를 즉시 전달한다.

의존:
- `src.preprocessing.drift_detector.compute_drift_report(meta, df) -> DriftReport`
- `src.preprocessing.model_registry.ModelRegistry.list_models()` (등록 모델 목록)
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.preprocessing.drift_detector import (
    DRIFT_THRESHOLD_CRITICAL,
    DRIFT_THRESHOLD_WARN,
    DriftReport,
    compute_drift_report,
)
from src.preprocessing.model_registry import ModelMetadata


def render_drift_banner(
    current_df: pd.DataFrame,
    model_metadatas: list[ModelMetadata],
    max_show: int = 5,
) -> None:
    """등록 모델들에 대한 드리프트 상태 배너 렌더링.

    Args:
        current_df: 현재 분석 중인 DataFrame
        model_metadatas: ModelRegistry.list_models() 결과
        max_show: 배너에 표시할 최대 모델 개수 (critical 우선)

    Why: 스키마 불일치 / critical / warn / stable 4단계 분류하여
         상단에 간결한 배너로 표시. 상세는 expander로 접기.
    """
    if not model_metadatas:
        return

    reports: list[DriftReport] = []
    for meta in model_metadatas:
        if not meta.training_data_stats:
            continue  # Why: 구버전(메타 없음) 모델은 스킵
        try:
            reports.append(compute_drift_report(meta, current_df))
        except Exception:
            # Why: 단일 모델 실패가 배너 자체를 막지 않도록 격리
            continue

    if not reports:
        return

    critical = [r for r in reports if r.overall_status == "critical"]
    warn = [r for r in reports if r.overall_status == "warn"]

    if critical:
        _render_critical(critical, max_show)
    elif warn:
        _render_warn(warn, max_show)
    else:
        _render_stable(len(reports))


def _render_critical(reports: list[DriftReport], max_show: int) -> None:
    # Why: 가장 심각한 reports 먼저 표시
    reports = sorted(reports, key=lambda r: r.max_psi, reverse=True)[:max_show]
    names = ", ".join(f"{r.model_name} v{r.version}" for r in reports)
    st.error(
        f"🚨 **모델 재학습 필요** — {len(reports)}개 모델에서 강한 드리프트 감지 "
        f"(PSI ≥ {DRIFT_THRESHOLD_CRITICAL}). 대상: {names}",
        icon="🚨",
    )
    with st.expander("드리프트 상세 보기"):
        _render_report_table(reports)


def _render_warn(reports: list[DriftReport], max_show: int) -> None:
    reports = sorted(reports, key=lambda r: r.max_psi, reverse=True)[:max_show]
    names = ", ".join(f"{r.model_name} v{r.version}" for r in reports)
    st.warning(
        f"⚠️ **드리프트 경고** — {len(reports)}개 모델에서 약한 분포 변화 감지 "
        f"(PSI ≥ {DRIFT_THRESHOLD_WARN}). 모니터링 강화 권장: {names}",
        icon="⚠️",
    )
    with st.expander("드리프트 상세 보기"):
        _render_report_table(reports)


def _render_stable(n_models: int) -> None:
    st.success(
        f"✅ 모델 분포 안정 — {n_models}개 등록 모델 모두 PSI < {DRIFT_THRESHOLD_WARN}",
        icon="✅",
    )


def _render_report_table(reports: list[DriftReport]) -> None:
    """DriftReport 목록을 DataFrame 표로 시각화."""
    rows = []
    for r in reports:
        rows.append({
            "모델": r.model_name,
            "버전": r.version,
            "상태": r.overall_status,
            "최대 PSI": round(r.max_psi, 4),
            "최대 PSI 컬럼": r.max_psi_column,
            "스키마 불일치": "O" if r.schema_mismatch else "X",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
