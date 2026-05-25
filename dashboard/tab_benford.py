"""Tab 2: Benford 분석 — 첫째 자릿수 분포 검정 + 분리 분석.

Why: 07-dashboard.md §270-302 스펙 구현.
     사이드바 필터에 반응하도록 analyze_benford()를 실시간 재계산.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from config.settings import get_settings
from dashboard._state import KEY_FILTERS, FilterState
from dashboard.components.charts import benford_overlay
from dashboard.components.charts.benford_charts import benford_facet
from dashboard.components.filters import apply_filters
from src.validation.benford import BENFORD_EXPECTED, analyze_benford

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

# ── 분리 기준 옵션 ──────────────────────────────────────────
_SPLIT_OPTIONS: dict[str, str] = {
    "업무 프로세스": "business_process",
    "법인": "company_code",
    "소스": "source",
}

# Why: 감사기준서상 recurring·payroll(H2R) 소스는 Benford 검정 대상에서 제외
_BENFORD_EXCLUDE_WARNING = (
    "Recurring(자동반복) 및 H2R(급여) 전표는 Benford 분석 대상에서 "
    "제외하는 것이 감사 실무상 권장됩니다."
)

_DRILL_COLUMNS = [
    "document_id", "gl_account", "debit_amount", "credit_amount",
    "posting_date", "source", "business_process",
]


def render(result: PipelineResult) -> None:
    """Benford 분석 탭 렌더링 — 필터 연동 실시간 재계산."""
    if "first_digit" not in result.data.columns:
        st.info("first_digit 피처가 없어 Benford 분석을 수행할 수 없습니다.")
        return

    # Why: 메타데이터는 Batch 전체 정적 결과 → 필터 적용 후 재계산해야 UX 일관성 유지
    filters: FilterState = st.session_state.get(KEY_FILTERS, {})
    filtered_df = apply_filters(result.data, filters)
    digits = filtered_df["first_digit"].dropna()

    if len(digits) < 30:
        st.info(f"유효 표본 {len(digits)}건 — Benford 분석에 충분하지 않습니다.")
        return

    settings = get_settings()
    br, _warnings = analyze_benford(digits, settings=settings)

    # ── Row 1: 전체 Benford 결과 ──────────────────────────────
    _render_overview(br, settings.benford_mad_threshold)

    # ── Row 2: 분리 분석 + Spike Drill ────────────────────────
    _render_split_analysis(filtered_df, settings.benford_mad_threshold)


def _render_overview(br, mad_threshold: float) -> None:
    """Row 1: 오버레이 차트 + 통계 메트릭 카드."""
    # Why: BenfordResult.observed/expected dict → benford_overlay 입력용 DataFrame 변환
    digits_df = pd.DataFrame({
        "digit": range(1, 10),
        "observed_freq": [br.observed.get(d, 0.0) for d in range(1, 10)],
        "expected_freq": [BENFORD_EXPECTED[d] for d in range(1, 10)],
    })
    digits_df["deviation"] = (digits_df["observed_freq"] - digits_df["expected_freq"]).abs()

    col_chart, col_metrics = st.columns([2, 1])

    with col_chart:
        fig = benford_overlay(digits_df, mad_threshold=mad_threshold)
        st.plotly_chart(fig, width="stretch")

    with col_metrics:
        st.metric("표본 크기", f"{br.sample_size:,}건", help=f"신뢰도: {br.confidence}")
        st.metric("MAD", f"{br.mad:.4f}" if br.mad is not None else "N/A")

        # Why: 판정 텍스트에 색상 힌트를 위해 조건부 delta 사용
        conformity_label = {
            "close": "Close (적합)",
            "acceptable": "Acceptable (수용)",
            "marginally": "Marginal (경계)",
            "nonconforming": "Nonconformity (부적합)",
        }.get(br.mad_conformity, br.mad_conformity)
        st.metric("MAD 판정", conformity_label)

        chi2_display = f"{br.chi2_p_value:.4f}" if br.chi2_p_value is not None else "N/A"
        st.metric("Chi-sq p-value", chi2_display)

        ks_display = f"{br.ks_p_value:.4f}" if br.ks_p_value is not None else "N/A"
        st.metric("KS p-value", ks_display, help="보조 지표 (이산 분포 한계)")


def _render_split_analysis(filtered_df: pd.DataFrame, mad_threshold: float) -> None:
    """Row 2: 분리 분석 facet 차트 + Spike Drill."""
    with st.expander("분리 분석 (Spike Drill)", expanded=False):
        # Why: recurring/H2R 데이터 포함 시 감사 실무 경고
        _show_exclusion_warning(filtered_df)

        split_label = st.selectbox("분리 기준", list(_SPLIT_OPTIONS.keys()))
        group_col = _SPLIT_OPTIONS[split_label]

        if group_col in filtered_df.columns:
            fig = benford_facet(filtered_df, group_col, mad_threshold=mad_threshold)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info(f"'{group_col}' 컬럼이 데이터에 없습니다.")

        # Spike Drill: digit 선택 → 해당 전표 테이블
        st.divider()
        selected_digit = st.selectbox("조회할 시작 숫자(Digit)", range(1, 10))
        drill_df = filtered_df[filtered_df["first_digit"] == selected_digit]

        if drill_df.empty:
            st.info(f"digit {selected_digit}에 해당하는 전표가 없습니다.")
        else:
            show_cols = [c for c in _DRILL_COLUMNS if c in drill_df.columns]
            st.dataframe(drill_df[show_cols], width="stretch", height=300)
            st.caption(f"digit {selected_digit} 전표: {len(drill_df):,}건")


def _show_exclusion_warning(df: pd.DataFrame) -> None:
    """Recurring/H2R 소스 포함 시 경고."""
    has_recurring = ("source" in df.columns and (df["source"] == "Recurring").any())
    has_h2r = ("business_process" in df.columns and (df["business_process"] == "H2R").any())
    if has_recurring or has_h2r:
        st.warning(_BENFORD_EXCLUDE_WARNING)
