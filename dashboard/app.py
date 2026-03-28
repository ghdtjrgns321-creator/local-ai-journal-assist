"""AI Audit Assistant — Streamlit 대시보드 메인 앱.

Usage: uv run streamlit run dashboard/app.py

레이아웃:
  - 결과 없음: 메인 영역에 업로드 + 미리보기 + 매핑 UI
  - 결과 있음: 사이드바(필터/설정) + 메인(4탭)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from dashboard._state import (
    KEY_DEV_MODE,
    KEY_INGEST_STAGE,
    KEY_PIPELINE_RESULT,
    KEY_UPLOAD_COUNT,
    init_state,
)

st.set_page_config(
    page_title="AI Audit Assistant",
    layout="wide",
    page_icon="🔍",
)
init_state()

# ── Sidebar: 설정 전용 ──────────────────────────────────────────

with st.sidebar:
    st.title("AI Audit Assistant")

    dev_mode = st.toggle(
        "개발 모드",
        value=st.session_state.get(KEY_DEV_MODE, False),
        help="활성화 시 상세 오류 표시",
    )
    st.session_state[KEY_DEV_MODE] = dev_mode

    result = st.session_state.get(KEY_PIPELINE_RESULT)

    # 결과 있을 때만 필터/설정 표시
    if result is not None:
        upload_key = st.session_state.get(KEY_UPLOAD_COUNT, "")
        file_label = upload_key.rsplit("_", 1)[0] if upload_key else "데이터"
        st.caption(f"{file_label} | {len(result.data):,}행 | {result.elapsed:.1f}초")

        with st.expander("데이터 필터", expanded=False):
            from dashboard.components.filters import render_filters
            render_filters(result.data)

        with st.expander("탐지 설정", expanded=False):
            from dashboard.components.preset_selector import render_preset_selector
            render_preset_selector()

            from dashboard.components.threshold_sidebar import render_threshold_sidebar
            render_threshold_sidebar()

            from dashboard.components.rule_panel import render_rule_panel
            render_rule_panel()

        from dashboard.components._redetect import render_apply_button
        render_apply_button()

# ── Main ─────────────────────────────────────────────────────────

result = st.session_state.get(KEY_PIPELINE_RESULT)
stage = st.session_state.get(KEY_INGEST_STAGE, "UPLOAD")

if result is None:
    # 파이프라인 미완료 → 메인 영역에 업로드 + 매핑 UI
    from dashboard.components.data_uploader import render_uploader
    render_uploader()
    st.stop()

# 파이프라인 완료 → 파일 변경 버튼 + 4탭
col_info, col_btn = st.columns([4, 1])
with col_info:
    upload_key = st.session_state.get(KEY_UPLOAD_COUNT, "")
    file_label = upload_key.rsplit("_", 1)[0] if upload_key else "데이터"
    risk = result.risk_summary
    st.markdown(
        f"**{file_label}** — {len(result.data):,}행 · "
        f"High {risk.get('High', 0)} · Medium {risk.get('Medium', 0)} · "
        f"Low {risk.get('Low', 0)} · Normal {risk.get('Normal', 0)}"
    )
with col_btn:
    if st.button("다른 파일 분석"):
        # 업로드 상태 리셋
        st.session_state.pop(KEY_PIPELINE_RESULT, None)
        st.session_state.pop(KEY_UPLOAD_COUNT, None)
        st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
        st.rerun()

from dashboard import tab_benford, tab_eda
from dashboard.tab_explorer import render as render_explorer
from dashboard.tab_summary import render as render_summary

tabs = st.tabs(["📊 EDA", "📋 요약", "🔔 Benford", "🔍 탐색기"])

with tabs[0]:
    tab_eda.render(result)
with tabs[1]:
    render_summary(result)
with tabs[2]:
    tab_benford.render(result)
with tabs[3]:
    render_explorer(result)
