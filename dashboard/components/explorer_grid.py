"""AgGrid 컬럼 정의 + 조건부 서식 — Tab 3 Explorer용.

Why: AgGrid 설정이 ~100줄이므로 오케스트레이터(tab_explorer.py)와 분리.
     JsCode 렌더러 4종 + 컬럼 그룹 정의 + build_grid() 공개 함수.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from dashboard.components.ml_tooltips import ML_TOOLTIPS

if TYPE_CHECKING:
    pass

# ── JsCode 조건부 서식 ────────────────────────────────────────

# Why: RISK_COLORS를 JS 내부에 하드코딩 (JsCode는 Python 변수 참조 불가)
#      _theme.py RISK_COLORS와 동일한 muted 톤 유지.
RISK_CELL_STYLE = JsCode("""
function(params) {
    var colors = {High:'#EF4444', Medium:'#F59E0B', Low:'#60A5FA', Normal:'#CBD5E1'};
    var textColors = {High:'#fff', Medium:'#fff', Low:'#1E293B', Normal:'#475569'};
    var bg = colors[params.value] || 'transparent';
    var fg = textColors[params.value] || '#111827';
    return {backgroundColor: bg, color: fg, fontWeight: '600', textAlign: 'center',
            borderRadius: '4px', margin: '2px 0'};
}
""")

SCORE_RENDERER = JsCode("""
class ScoreRenderer {
    init(params) {
        this.eGui = document.createElement('div');
        this.eGui.style.position = 'relative';
        this.eGui.style.width = '100%';
        this.eGui.style.height = '100%';
        var val = params.value || 0;
        var bar = document.createElement('div');
        bar.style.width = (val * 100) + '%';
        bar.style.height = '100%';
        bar.style.position = 'absolute';
        bar.style.backgroundColor = 'rgba(255, 75, 75, ' + val + ')';
        var text = document.createElement('span');
        text.style.position = 'relative';
        text.style.zIndex = '1';
        text.textContent = val.toFixed(3);
        this.eGui.appendChild(bar);
        this.eGui.appendChild(text);
    }
    getGui() { return this.eGui; }
}
""")

MANUAL_ROW_STYLE = JsCode("""
function(params) {
    if (params.data && params.data.source === 'Manual') {
        return {backgroundColor: '#FFF3CD'};
    }
    if (params.data && params.data._whitelisted) {
        return {backgroundColor: '#F0F0F0'};
    }
    return null;
}
""")

SOD_RENDERER = JsCode("""
class SodRenderer {
    init(params) {
        this.eGui = document.createElement('span');
        this.eGui.textContent = params.value ? '⚠' : '';
        this.eGui.style.fontSize = '16px';
    }
    getGui() { return this.eGui; }
}
""")

# ── 컬럼 그룹 정의 ──────────────────────────────────────────

_PINNED_COLS = ["document_id", "risk_level", "anomaly_score"]

# Why: ML 점수 컬럼을 최상단 visible에 배치 → 감사인이 룰 기반 점수와 ML 점수를
#      한눈에 비교 가능. DataFrame에 없으면 available 필터로 자동 제외.
_ML_SCORE_COLS = ["supervised_score", "unsupervised_score"]

_VISIBLE_COLS = [
    *_ML_SCORE_COLS,
    "company_code", "posting_date", "document_type", "business_process",
    "gl_account", "debit_amount", "credit_amount", "created_by",
    "user_persona", "source", "flagged_rules",
]

_HIDDEN_COLS = [
    "fiscal_year", "fiscal_period", "document_date", "line_number",
    "header_text", "line_text", "reference", "approved_by",
    "sod_violation", "sod_conflict_type",
]

_DEV_COLS = ["is_fraud", "fraud_type", "is_anomaly", "anomaly_type"]

# ── 한글 헤더 매핑 ──────────────────────────────────────────

_HEADER_KR: dict[str, str] = {
    "document_id": "전표번호", "risk_level": "위험등급",
    "anomaly_score": "이상점수",
    "supervised_score": "ML(지도)",
    "unsupervised_score": "ML(비지도)",
    "company_code": "회사코드",
    "posting_date": "전기일", "document_type": "전표유형",
    "business_process": "업무프로세스", "gl_account": "계정코드",
    "debit_amount": "차변", "credit_amount": "대변",
    "created_by": "작성자", "user_persona": "직무",
    "source": "소스", "flagged_rules": "탐지룰",
    "fiscal_year": "회계연도", "fiscal_period": "회계기간",
    "document_date": "증빙일", "line_number": "행번호",
    "header_text": "헤더적요", "line_text": "행적요",
    "reference": "참조", "approved_by": "승인자",
    "sod_violation": "SoD위반", "sod_conflict_type": "SoD유형",
    "is_fraud": "부정여부", "fraud_type": "부정유형",
    "is_anomaly": "이상여부", "anomaly_type": "이상유형",
}


# ── 공개 API ────────────────────────────────────────────────


_GRID_MAX_ROWS = 10_000


def build_grid(
    df: pd.DataFrame,
    dev_mode: bool,
    whitelist_docs: set[str] | None = None,
    selected_doc: str | None = None,
) -> object:
    """AgGrid 렌더링 후 응답 객체 반환.

    Args:
        df: 필터 적용 완료된 DataFrame.
        dev_mode: True이면 is_fraud 등 개발 컬럼 표시.
        whitelist_docs: whitelist에 등록된 document_id 집합 (행 회색 처리).
        selected_doc: rerun 후 복원할 document_id.
    """
    # Why: 브라우저 성능 보호 — 대량 데이터 시 anomaly_score 상위 N건만 전송
    import streamlit as st

    total = len(df)
    if total > _GRID_MAX_ROWS:
        df = df.nlargest(_GRID_MAX_ROWS, "anomaly_score") if "anomaly_score" in df.columns else df.head(_GRID_MAX_ROWS)
        st.caption(f"전체 {total:,}건 중 이상점수 상위 {_GRID_MAX_ROWS:,}건 표시 (필터로 범위를 좁혀보세요)")

    # Why: whitelist 행에 시각 표시용 임시 컬럼 추가
    show_df = df.copy()
    if whitelist_docs:
        show_df["_whitelisted"] = show_df["document_id"].isin(whitelist_docs)
    else:
        show_df["_whitelisted"] = False

    # 표시 대상 컬럼 결정
    cols = _PINNED_COLS + _VISIBLE_COLS + _HIDDEN_COLS
    if dev_mode:
        cols += _DEV_COLS
    cols.append("_whitelisted")

    # Why: DataFrame에 존재하는 컬럼만 선택 (누락 방어)
    available = [c for c in cols if c in show_df.columns]
    show_df = show_df[available].reset_index(drop=True)

    gb = GridOptionsBuilder.from_dataframe(show_df)

    # 공통 설정
    gb.configure_default_column(sortable=True, filterable=True, resizable=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=100)

    # pinned 컬럼
    for col in _PINNED_COLS:
        if col not in show_df.columns:
            continue
        opts: dict = {"pinned": "left", "headerName": _HEADER_KR.get(col, col)}
        # Why: 핵심 지표 컬럼은 headerTooltip으로 한글 설명 제공
        if col in ML_TOOLTIPS:
            opts["headerTooltip"] = ML_TOOLTIPS[col]
        if col == "risk_level":
            opts["cellStyle"] = RISK_CELL_STYLE
            opts["width"] = 100
        elif col == "anomaly_score":
            opts["cellRenderer"] = SCORE_RENDERER
            opts["sort"] = "desc"
            opts["width"] = 120
        elif col == "document_id":
            opts["width"] = 140
        gb.configure_column(col, **opts)

    # visible 컬럼
    for col in _VISIBLE_COLS:
        if col not in show_df.columns:
            continue
        # Why: ML 점수 컬럼은 anomaly_score와 동일한 바 렌더러로 시각 일관성 유지.
        #      headerTooltip에 한글 설명을 넣어 감사인 친화적 UX 제공.
        if col in _ML_SCORE_COLS:
            gb.configure_column(
                col,
                headerName=_HEADER_KR.get(col, col),
                headerTooltip=ML_TOOLTIPS.get(col, ""),
                cellRenderer=SCORE_RENDERER,
                width=110,
            )
        else:
            gb.configure_column(col, headerName=_HEADER_KR.get(col, col))

    # hidden 컬럼
    for col in _HIDDEN_COLS:
        if col not in show_df.columns:
            continue
        opts = {"hide": True, "headerName": _HEADER_KR.get(col, col)}
        if col == "sod_violation":
            opts["cellRenderer"] = SOD_RENDERER
            opts["width"] = 80
        gb.configure_column(col, **opts)

    # dev 컬럼 (dev_mode=False이면 이미 cols에 미포함)
    if dev_mode:
        for col in _DEV_COLS:
            if col not in show_df.columns:
                continue
            gb.configure_column(col, headerName=_HEADER_KR.get(col, col))

    # _whitelisted 컬럼은 숨김 (getRowStyle에서만 사용)
    gb.configure_column("_whitelisted", hide=True)

    grid_options = gb.build()
    grid_options["getRowStyle"] = MANUAL_ROW_STYLE

    # Why: rerun 후 이전 선택 행 복원
    pre_selected = None
    if selected_doc and "document_id" in show_df.columns:
        idx = show_df.index[show_df["document_id"] == selected_doc].tolist()
        if idx:
            pre_selected = [idx[0]]

    return AgGrid(
        show_df,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        height=500,
        theme="streamlit",
        pre_selected_rows=pre_selected,
    )
