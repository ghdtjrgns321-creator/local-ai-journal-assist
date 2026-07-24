# ruff: noqa: E501
"""shadcn/Linear 스타일 대시보드 CSS - 모던 프로페셔널 UI.

Color System (Tailwind slate + neutral):
  #FFFFFF  Background — 페이지 배경
  #F8F9FA  Surface — 카드, 사이드바, 패널
  #F1F3F5  Surface Elevated — 호버, 선택
  #E2E5E9  Border — 구분선, 테두리
  #111827  Text Primary & CTA — 제목, 핵심 수치, 기본 버튼
  #6B7280  Text Secondary — 부가 설명
  #9CA3AF  Text Muted — 비활성, 힌트
  #2563EB  Accent — 링크, 포커스 링, 파일업로더 강조(최소 사용)
"""

CUSTOM_CSS = """
<style>
:root {
    /* CTA — Tailwind slate 700/800 (부드러운 회색끼 dark) */
    --c-primary: #374151;       /* slate-700, 차분한 중간 톤 */
    --c-primary-hover: #1F2937; /* slate-800, 살짝 진하게 */
    --c-primary-active: #111827;/* slate-900 */
    /* Accent — 링크/포커스에서만 최소 사용 */
    --c-accent: #2563EB;
    --c-accent-subtle: #EFF6FF;
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
    --s-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
    --s-md: 0 2px 6px rgba(15, 23, 42, 0.08);
    --s-btn: 0 1px 2px rgba(15, 23, 42, 0.10);
    --s-btn-hover: 0 4px 10px rgba(15, 23, 42, 0.14);
    --font: 'Pretendard Variable', 'Pretendard', 'Inter',
            -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');

html, body, [class*="css"] {
    font-family: var(--font) !important;
}

/* Streamlit이 rerun 중 stale 요소에 data-stale="true"를 붙여 dim 처리한다.
   display:none 으로 숨기면 레이아웃 공간까지 사라져 빈 박스/스크롤 점프가
   생기므로 opacity 만 유지해 레이아웃은 그대로 두고 새 콘텐츠로 부드럽게 교체. */
[data-testid="stElementContainer"][data-stale="true"] {
    opacity: 1 !important;
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

/* ── Metric (flat) ─────────────────────────────────── */
/* Why: 카드형 박스 제거 → shadcn 톤의 flat 디자인.
       border=True 인자로 명시적으로 카드를 원하는 경우만 Streamlit 기본 동작 사용. */
[data-testid="stMetric"] {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    box-shadow: none;
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

/* 대분류 nav 전용 */
.st-key-audit_top_level_nav {
    margin: 0.25rem 0 0.9rem;
}
.st-key-audit_top_level_nav .stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    padding: 3px !important;
    border: 1px solid var(--c-border) !important;
    border-radius: var(--r-sm) !important;
    background: var(--c-surface) !important;
}
.st-key-audit_top_level_nav .stTabs [data-baseweb="tab"] {
    min-height: 38px !important;
    padding: 0.45rem 1.1rem !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
    border-radius: var(--r-sm) !important;
}
.st-key-audit_top_level_nav .stTabs [aria-selected="true"] {
    background: var(--c-bg) !important;
    color: var(--c-text) !important;
    font-weight: 600 !important;
    box-shadow: var(--s-sm) !important;
}

/* nested st.tabs 는 기본 톤으로 reset */
/* Why: 소분류 탭이 다닥다닥 붙어 보여 gap 을 10px 로 키우고 좌우 패널 패딩도
   넉넉히 확보. 9개까지 가로 배치할 때 wrap 이 일어나지 않도록 min-width 는
   기존 96px 유지(전체 폭 1400px 기준 96 × 9 + gap = 1004px 로 여유). */
.st-key-audit_top_level_nav .stTabs .stTabs [data-baseweb="tab-list"] {
    gap: 10px !important;
    padding: 4px 6px !important;
}
.st-key-audit_top_level_nav .stTabs .stTabs [data-baseweb="tab"] {
    min-height: auto !important;
    min-width: 96px !important;
    padding: 0.5rem 1.25rem !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    border-radius: var(--r-sm) !important;
    text-align: center !important;
    justify-content: center !important;
}

/* Phase1 section segmented navigation: selected section only is rendered in Python. */
.st-key-phase1_section_nav {
    margin: 0.6rem 0 2rem;
}
.st-key-phase1_section_nav [data-testid="stSegmentedControl"] > div {
    display: flex;
    gap: 12px;
    width: 100%;
}
.st-key-phase1_section_nav [data-testid="stSegmentedControl"] label {
    flex: 1 1 0;
    justify-content: center;
    min-height: 48px;
    border-radius: var(--r-md) !important;
    border: 1px solid var(--c-border) !important;
    background: var(--c-surface) !important;
    color: var(--c-text-secondary) !important;
    box-shadow: none !important;
}
.st-key-phase1_section_nav [data-testid="stSegmentedControl"] label:has(input:checked) {
    background: var(--c-primary) !important;
    border-color: var(--c-primary) !important;
    color: #FFFFFF !important;
    box-shadow: var(--s-btn) !important;
}
.st-key-phase1_section_nav [data-testid="stSegmentedControl"] label:has(input:checked) * {
    color: #FFFFFF !important;
}

/* 거래처 신호 필터 — 선택 chip을 primary로 확실히 채워 상태를 강조.
   label / button 두 DOM 형태를 모두 커버해 Streamlit 버전 차이에 견고하게. */
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] label,
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] button {
    border: 1px solid var(--c-border) !important;
    background: var(--c-bg) !important;
    color: var(--c-text-secondary) !important;
    border-radius: var(--r-sm) !important;
    padding: 0.4rem 1.05rem !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    box-shadow: none !important;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] label:hover,
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] button:hover {
    border-color: var(--c-text-muted) !important;
    color: var(--c-text) !important;
    background: var(--c-surface) !important;
}
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] label:has(input:checked),
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] button[aria-pressed="true"] {
    background: var(--c-primary) !important;
    border-color: var(--c-primary) !important;
    color: #FFFFFF !important;
    box-shadow: var(--s-btn) !important;
}
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] label:has(input:checked) *,
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] button[aria-checked="true"] *,
.st-key-analytical_partner_signal_filter [data-testid="stSegmentedControl"] button[aria-pressed="true"] * {
    color: #FFFFFF !important;
}

/* 거래처 신호 판정 기준 범례 — 카드형 정의 목록(rule-audit-note 톤). */
.signal-legend {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px 14px;
    margin: 4px 0 14px;
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: var(--r-md);
}
.signal-legend__item {
    font-size: 0.78rem;
    line-height: 1.5;
    color: var(--c-text-secondary);
}
.signal-legend__term {
    display: inline-block;
    min-width: 92px;
    margin-right: 8px;
    padding: 1px 8px;
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--c-text);
    background: var(--c-bg);
    border: 1px solid var(--c-border);
    border-radius: 999px;
    text-align: center;
}

/* ── Buttons ───────────────────────────────────────── */
.stMainBlockContainer .stButton > button {
    border-radius: var(--r-sm) !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    padding: 0.45rem 1rem !important;
    border: 1px solid var(--c-border) !important;
    background: var(--c-bg) !important;
    color: var(--c-text) !important;
    transition: background 0.15s ease, border-color 0.15s ease,
                box-shadow 0.15s ease, transform 0.1s ease;
    box-shadow: var(--s-sm);
    letter-spacing: -0.01em;
}
.stMainBlockContainer .stButton > button:hover {
    background: var(--c-surface) !important;
    border-color: var(--c-text-muted) !important;
}
.stMainBlockContainer .stButton > button:active {
    transform: translateY(0.5px);
}
/* Primary CTA — shadcn/Linear neutral dark */
.stMainBlockContainer .stButton > button[kind="primary"],
.stMainBlockContainer .stButton > button[data-testid="stFormSubmitButton"],
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: var(--c-primary) !important;
    color: #FFFFFF !important;
    border: 1px solid var(--c-primary) !important;
    box-shadow: var(--s-btn) !important;
    font-weight: 500 !important;
}
.stMainBlockContainer .stButton > button[kind="primary"]:hover,
.stMainBlockContainer .stButton > button[data-testid="stFormSubmitButton"]:hover,
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background: var(--c-primary-hover) !important;
    border-color: var(--c-primary-hover) !important;
    box-shadow: var(--s-btn-hover) !important;
    transform: translateY(-1px);
}
.stMainBlockContainer .stButton > button[kind="primary"]:active,
.stMainBlockContainer .stButton > button[data-testid="stFormSubmitButton"]:active {
    background: var(--c-primary-active) !important;
    transform: translateY(0);
    box-shadow: var(--s-btn) !important;
}
.stMainBlockContainer .stButton > button[kind="primary"]:disabled,
.stMainBlockContainer .stButton > button[data-testid="stFormSubmitButton"]:disabled {
    background: var(--c-text-muted) !important;
    border-color: var(--c-text-muted) !important;
    color: #FFFFFF !important;
    box-shadow: none !important;
    transform: none !important;
    opacity: 0.65;
    cursor: not-allowed;
}
.stMainBlockContainer .stButton > button:focus-visible,
.stMainBlockContainer .stButton > button[kind="primary"]:focus-visible {
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25), var(--s-btn) !important;
}

/* ── Sticky preview (우측 column 내부) ──────────────
   Why: st.columns로 좌우 분할하면 오른쪽 stColumn 내부의 stVerticalBlock은
        부모 stMain을 scroll container로 가지는 flex item이므로, 내부 요소에
        position:sticky가 안정적으로 작동한다. marker를 포함한 stColumn을
        통째로 sticky하게 만들어 헤더+테이블+캡션이 함께 고정된다. */
[data-testid="stHorizontalBlock"]
    > [data-testid="stColumn"]:has(.sticky-preview-marker) {
    position: sticky;
    top: 5rem; /* stHeader(≈3.75rem) + 여유. 제목이 헤더에 잘리지 않게 충분히 내림 */
    align-self: flex-start;
    z-index: 40;
    background: var(--c-bg);
    padding: 1rem 0.75rem 0.75rem;
    border-radius: var(--r-md);
    border: 1px solid var(--c-border);
    box-shadow: 0 8px 18px -12px rgba(15, 23, 42, 0.15);
    max-height: calc(100vh - 7rem);
    overflow-y: auto;
}
.sticky-preview-marker { display: none; }

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
/* Why: Streamlit container(border=True) 내부의 wrapper padding·margin을 완전
   제거해 내 HTML이 카드 전체를 직접 차지하게 한다. 이래야 "flex center가
   실제 카드 중앙에" 오고, Streamlit 기본 수직 gap에 무력화되지 않는다. */
/* Why: 기존에는 이 규칙을 전역으로 적용했으나, engagement selector 같이
   container(border=True)를 쓰는 다른 페이지 레이아웃을 망가뜨렸다.
   marker `.tab-overview-scoped`를 포함한 카드에만 scoped로 적용한다. */
[data-testid="stVerticalBlock"][data-has-border="true"]:has(.tab-overview-scoped) {
    padding: 0 !important;
    gap: 0 !important;
    overflow: hidden !important;
    display: flex !important;
    flex-direction: column !important;
}
[data-testid="stVerticalBlock"][data-has-border="true"]:has(.tab-overview-scoped) > [data-testid="stElementContainer"] {
    padding: 0 !important;
    margin: 0 !important;
    min-height: 0 !important;
}
[data-testid="stVerticalBlock"][data-has-border="true"]:has(.tab-overview-scoped) > [data-testid="stElementContainer"]:only-child {
    flex: 1 !important;
    height: 100% !important;
}
[data-testid="stVerticalBlock"][data-has-border="true"]:has(.tab-overview-scoped) [data-testid="stMarkdown"],
[data-testid="stVerticalBlock"][data-has-border="true"]:has(.tab-overview-scoped) [data-testid="stMarkdownContainer"] {
    padding: 0 !important;
    margin: 0 !important;
    height: 100% !important;
}
[data-testid="stVerticalBlock"][data-has-border="true"]:has(.tab-overview-scoped) [data-testid="stMarkdownContainer"] > div {
    height: 100% !important;
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
    border-color: var(--c-accent) !important;
    background: var(--c-accent-subtle) !important;
}

/* ── Plotly charts ─────────────────────────────────── */
/* Why: Plotly 기본에 border/padding을 주면 container(border=True)와 중첩돼
        이중 테두리가 생긴다. 전역으로 투명 + 테두리 없음으로 설정하고,
        카드 효과가 필요한 곳에서만 바깥 container(border=True)로 감싼다. */
[data-testid="stPlotlyChart"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
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
.ag-theme-streamlit .ag-row:hover { background: var(--c-surface-hover) !important; }
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

/* ── Rule audit note (분석 룰 요약 안내 카드) ─────── */
.rule-audit-note {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 8px 12px;
    margin: 4px 0 14px 0;
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-left: 3px solid var(--c-primary);
    border-radius: var(--r-md);
}
.rule-audit-note__icon {
    flex: 0 0 auto;
    width: 14px;
    height: 14px;
    margin-top: 2px;
    color: var(--c-primary);
    opacity: 0.7;
}
.rule-audit-note__body {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.rule-audit-note__line {
    margin: 0;
    font-size: 0.74rem;
    line-height: 1.45;
    color: var(--c-text-secondary);
}
.rule-audit-note__tag {
    display: inline-block;
    padding: 0px 6px;
    margin: 0 1px;
    font-size: 0.66rem;
    font-weight: 600;
    line-height: 1.5;
    color: var(--c-text);
    background: var(--c-bg);
    border: 1px solid var(--c-border);
    border-radius: 4px;
    vertical-align: 1px;
}

/* ── Benford 통계 패널 (오버레이 차트 우측) ────────── */
/* Why: 좌측 차트와 상·하단을 맞추기 위해 고정 높이 + 세로 분산. 차트 높이(380px)와
       동일하게 두고 stat-grid가 남는 공간을 채워 바닥선을 정렬한다. */
.bf-panel {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    height: 320px;
}
.bf-verdict {
    padding: 0.7rem 0.85rem;
    border-radius: var(--r-md);
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-left-width: 3px;
}
.bf-verdict__label {
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--c-text-secondary);
    margin-bottom: 3px;
}
.bf-verdict__value {
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.1;
}
.bf-verdict__note {
    margin-top: 4px;
    font-size: 0.72rem;
    line-height: 1.4;
    color: var(--c-text-secondary);
}
.bf-verdict--good { border-left-color: #16A34A; }
.bf-verdict--good .bf-verdict__value { color: #15803D; }
.bf-verdict--warn { border-left-color: #D97706; }
.bf-verdict--warn .bf-verdict__value { color: #B45309; }
.bf-verdict--bad { border-left-color: #DC2626; }
.bf-verdict--bad .bf-verdict__value { color: #B91C1C; }

/* Why: 남는 세로 공간에 rows를 space-around로 흩뿌리면 칸 간격이 벌어져 가독성이
       나쁘다. rows는 붙여서 위쪽에 정렬하고, 아래 여백은 그대로 둔다. */
.bf-stat-grid {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
}
.bf-stat {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 0.55rem 0;
    border-bottom: 1px solid var(--c-border);
}
.bf-stat:last-child { border-bottom: none; }
.bf-stat__label {
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--c-text-secondary);
    display: inline-flex;
    align-items: center;
    gap: 5px;
}
/* Why: Streamlit HTML sanitizer가 title 속성을 제거해 네이티브 툴팁이 안 뜬다.
       class 기반 nested span은 살아남으므로 CSS 툴팁으로 구현한다. */
.bf-stat__hint {
    position: relative;
    font-size: 0.62rem;
    font-weight: 600;
    color: var(--c-text-muted);
    border: 1px solid var(--c-border);
    border-radius: 50%;
    width: 14px;
    height: 14px;
    line-height: 13px;
    text-align: center;
    cursor: help;
    flex: 0 0 auto;
}
.bf-stat__hint .bf-tip {
    visibility: hidden;
    opacity: 0;
    position: absolute;
    z-index: 1000;
    top: 150%;
    left: -4px;
    width: 230px;
    padding: 8px 10px;
    background: var(--c-primary-active);
    color: #FFFFFF;
    border-radius: var(--r-sm);
    box-shadow: var(--s-md);
    font-size: 0.72rem;
    font-weight: 400;
    line-height: 1.5;
    text-align: left;
    letter-spacing: 0;
    white-space: normal;
    transition: opacity 0.12s ease;
    pointer-events: none;
}
.bf-stat__hint:hover .bf-tip { visibility: visible; opacity: 1; }
.bf-stat__value {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--c-text);
    letter-spacing: -0.01em;
    white-space: nowrap;
}
.bf-stat__value .bf-unit {
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--c-text-secondary);
    margin-left: 1px;
}
</style>
"""


def inject_css() -> None:
    """앱 시작 시 1회 호출하여 커스텀 CSS 주입."""
    import streamlit as st

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
