"""shadcn/Tailwind 기반 대시보드 CSS — 모던 프로페셔널 UI.

Color System (Tailwind gray + blue-600):
  #FFFFFF  Background — 페이지 배경
  #F8F9FA  Surface — 카드, 사이드바, 패널
  #F1F3F5  Surface Elevated — 호버, 선택
  #E2E5E9  Border — 구분선, 테두리
  #111827  Text Primary — 제목, 핵심 수치
  #6B7280  Text Secondary — 부가 설명
  #9CA3AF  Text Muted — 비활성, 힌트
  #2563EB  Primary — CTA 버튼, 링크, 강조
"""

CUSTOM_CSS = """
<style>
:root {
    --c-primary: #2563EB;
    --c-primary-hover: #1D4ED8;
    --c-primary-subtle: #EFF6FF;
    --c-surface: #F8F9FA;
    --c-surface-hover: #F1F3F5;
    --c-border: #E2E5E9;
    --c-bg: #FFFFFF;
    --c-text: #111827;
    --c-text-secondary: #6B7280;
    --c-text-muted: #9CA3AF;
    --r-sm: 6px;
    --r-md: 8px;
    --r-lg: 12px;
    --s-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
    --s-md: 0 2px 6px rgba(0, 0, 0, 0.06);
    --font: 'Pretendard Variable', 'Pretendard', 'Inter',
            -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');

html, body, [class*="css"] {
    font-family: var(--font) !important;
}

/* ── Layout ────────────────────────────────────────── */
.stMain > .block-container {
    padding-top: 3.5rem;
    padding-bottom: 2rem;
    max-width: 1400px;
}

/* Why: 제목(h1)과 그 아래 요소(탭 등) 사이 여백 확보 */
.stMainBlockContainer h1 { margin-bottom: 1.2rem !important; }
.stMainBlockContainer h2 { margin-bottom: 0.8rem !important; }

/* Why: Streamlit 상단 헤더가 콘텐츠를 가리는 문제 해결 */
header[data-testid="stHeader"] {
    height: auto !important;
}

/* ── Sidebar ───────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: var(--c-surface) !important;
    border-right: 1px solid var(--c-border) !important;
}
section[data-testid="stSidebar"] * { color: var(--c-text) !important; }
section[data-testid="stSidebar"] .stCaption,
section[data-testid="stSidebar"] label { color: var(--c-text-secondary) !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: var(--c-text) !important;
    font-weight: 600 !important;
}
section[data-testid="stSidebar"] .stButton > button {
    background: var(--c-bg) !important;
    border: 1px solid var(--c-border) !important;
    color: var(--c-text) !important;
    border-radius: var(--r-sm) !important;
    transition: all 0.15s ease;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: var(--c-surface-hover) !important;
    border-color: var(--c-text-muted) !important;
}
section[data-testid="stSidebar"] .streamlit-expanderHeader {
    background: var(--c-bg) !important;
    border: 1px solid var(--c-border) !important;
    border-radius: var(--r-sm) !important;
}

/* ── Metric Cards ──────────────────────────────────── */
[data-testid="stMetric"] {
    background: var(--c-bg);
    border: 1px solid var(--c-border);
    border-radius: var(--r-md);
    padding: 1rem 1.25rem;
    box-shadow: var(--s-sm);
    transition: box-shadow 0.15s ease;
}
[data-testid="stMetric"]:hover {
    box-shadow: var(--s-md);
}
[data-testid="stMetric"] label {
    color: var(--c-text-secondary) !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: var(--c-text) !important;
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
}
[data-testid="stMetric"] [data-testid="stMetricDelta"] {
    color: var(--c-text-secondary) !important;
    font-size: 0.75rem !important;
}

/* ── Tabs ──────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: var(--c-surface);
    border-radius: var(--r-md);
    border: 1px solid var(--c-border);
    padding: 3px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: var(--r-sm);
    padding: 0.45rem 1rem;
    font-weight: 500;
    font-size: 0.85rem;
    color: var(--c-text-secondary);
    border: none !important;
    background: transparent;
    transition: all 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover {
    color: var(--c-text);
    background: var(--c-surface-hover);
}
.stTabs [aria-selected="true"] {
    background: var(--c-bg) !important;
    color: var(--c-text) !important;
    font-weight: 600 !important;
    box-shadow: var(--s-sm);
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none !important; }

/* ── Buttons ───────────────────────────────────────── */
.stMainBlockContainer .stButton > button {
    border-radius: var(--r-sm) !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    padding: 0.4rem 0.9rem !important;
    border: 1px solid var(--c-border) !important;
    background: var(--c-bg) !important;
    color: var(--c-text) !important;
    transition: all 0.15s ease;
    box-shadow: var(--s-sm);
}
.stMainBlockContainer .stButton > button:hover {
    background: var(--c-surface) !important;
    border-color: var(--c-text-muted) !important;
}
.stMainBlockContainer .stButton > button[kind="primary"],
.stMainBlockContainer .stButton > button[data-testid="stFormSubmitButton"] {
    background: var(--c-primary) !important;
    color: var(--c-bg) !important;
    border-color: var(--c-primary) !important;
}
.stMainBlockContainer .stButton > button[kind="primary"]:hover {
    background: var(--c-primary-hover) !important;
}

/* ── Expander ──────────────────────────────────────── */
.stMainBlockContainer .streamlit-expanderHeader {
    background: var(--c-surface) !important;
    border: 1px solid var(--c-border) !important;
    border-radius: var(--r-md) !important;
    font-weight: 500;
    font-size: 0.875rem;
}
.stMainBlockContainer details[open] .streamlit-expanderHeader {
    border-bottom-left-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
}
.stMainBlockContainer .streamlit-expanderContent {
    border: 1px solid var(--c-border) !important;
    border-top: none !important;
    border-bottom-left-radius: var(--r-md) !important;
    border-bottom-right-radius: var(--r-md) !important;
    background: var(--c-bg) !important;
}

/* ── Container (border=True) ───────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"][data-has-border="true"]) {
    border: 1px solid var(--c-border) !important;
    border-radius: var(--r-md) !important;
    box-shadow: var(--s-sm);
    background: var(--c-bg);
}

/* ── Alerts ────────────────────────────────────────── */
.stAlert { border-radius: var(--r-md) !important; }
[data-testid="stNotification"] { border-radius: var(--r-md) !important; }

/* ── Divider ───────────────────────────────────────── */
hr { border-color: var(--c-border) !important; opacity: 0.6; }

/* ── Headers ───────────────────────────────────────── */
.stMainBlockContainer h1 {
    color: var(--c-text) !important;
    font-weight: 700 !important;
    letter-spacing: -0.025em;
    font-size: 1.875rem !important;
}
.stMainBlockContainer h2 {
    color: var(--c-text) !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em;
    font-size: 1.375rem !important;
}
.stMainBlockContainer h3 {
    color: var(--c-text) !important;
    font-weight: 600 !important;
}

/* ── Caption ───────────────────────────────────────── */
.stCaption, .stMainBlockContainer .stCaption {
    color: var(--c-text-secondary) !important;
    font-size: 0.78rem !important;
}

/* ── Form inputs — Streamlit 기본 스타일 유지 (통일) ── */
/* selectbox — Streamlit 기본 스타일 유지 (커스텀 CSS 제거) */

/* ── File Uploader ─────────────────────────────────── */
[data-testid="stFileUploader"] section {
    border: 2px dashed var(--c-border) !important;
    border-radius: var(--r-md) !important;
    background: var(--c-surface) !important;
    padding: 2rem !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: var(--c-primary) !important;
    background: var(--c-primary-subtle) !important;
}

/* ── Plotly charts ─────────────────────────────────── */
[data-testid="stPlotlyChart"] {
    background: var(--c-bg);
    border: 1px solid var(--c-border);
    border-radius: var(--r-md);
    padding: 0.5rem;
}

/* ── AgGrid ────────────────────────────────────────── */
.ag-theme-streamlit {
    border-radius: var(--r-md) !important;
    border: 1px solid var(--c-border) !important;
    overflow: hidden;
}
.ag-theme-streamlit .ag-header {
    background: var(--c-surface) !important;
    border-bottom: 1px solid var(--c-border) !important;
}
.ag-theme-streamlit .ag-header-cell {
    color: var(--c-text) !important;
    font-weight: 600 !important;
    font-size: 0.8rem !important;
}
.ag-theme-streamlit .ag-row-even { background: var(--c-bg) !important; }
.ag-theme-streamlit .ag-row-odd { background: var(--c-surface) !important; }
.ag-theme-streamlit .ag-row:hover { background: var(--c-primary-subtle) !important; }
.ag-theme-streamlit .ag-paging-panel {
    background: var(--c-surface) !important;
    border-top: 1px solid var(--c-border) !important;
    color: var(--c-text-secondary) !important;
    font-size: 0.8rem !important;
}

/* ── Scrollbar ─────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--c-text-muted); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--c-text-secondary); }

/* ── Top bar ───────────────────────────────────────── */
/* header[data-testid="stHeader"] 스타일은 Layout 섹션에서 관리 */

/* ── Misc ──────────────────────────────────────────── */
[data-testid="stTooltipIcon"] { color: var(--c-text-muted) !important; }
.stMainBlockContainer [data-testid="stToggle"] label span {
    color: var(--c-text) !important;
    font-size: 0.85rem !important;
}
</style>
"""


def inject_css() -> None:
    """앱 시작 시 1회 호출하여 커스텀 CSS 주입."""
    import streamlit as st
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
