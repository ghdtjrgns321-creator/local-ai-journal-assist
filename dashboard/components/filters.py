"""사이드바 필터 — 기본4 + 차원6 + 개발2 = 12개 필터 + apply_filters.

Why: 필터 상태를 FilterState dict로 관리하여 모든 탭에 동기 적용.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard._state import KEY_DEV_MODE, KEY_FILTERS, FilterState
from src.detection.constants import RULE_CODES

# Why: 컬럼명 → 필터 키 매핑. 루프 처리로 6개 차원 필터 중복 코드 제거.
_DIMENSION_FILTERS: list[tuple[str, str, str]] = [
    ("business_processes", "business_process", "업무 프로세스"),
    ("company_codes", "company_code", "법인"),
    ("user_personas", "user_persona", "사용자 유형"),
    ("sources", "source", "소스"),
    ("document_types", "document_type", "전표 유형"),
    ("gl_accounts", "gl_account", "계정과목"),
]

_DEV_FILTERS: list[tuple[str, str, str]] = [
    ("fraud_types", "fraud_type", "부정 유형"),
    ("anomaly_types", "anomaly_type", "이상 유형"),
]


def _get_filter_options(df: pd.DataFrame) -> dict[str, list]:
    """DataFrame에서 각 차원의 고유값 추출 (NaN 제거, 정렬)."""
    cols = [c for _, c, _ in _DIMENSION_FILTERS + _DEV_FILTERS]
    # Why: key=str로 혼합 타입(int/str) 정렬 시 TypeError 방지.
    return {
        col: sorted(df[col].dropna().unique().tolist(), key=str)
        for col in cols if col in df.columns
    }


def render_filters(df: pd.DataFrame) -> None:
    """사이드바에 결과 탐색용 필터 위젯 렌더링 → session_state[KEY_FILTERS] 갱신."""
    options = _get_filter_options(df)
    filters: FilterState = {}

    # ── 기본 필터 4개 (항상 노출) ──────────────────────────
    if "posting_date" in df.columns:
        dates = pd.to_datetime(df["posting_date"], errors="coerce").dropna()
        if not dates.empty:
            min_d, max_d = dates.min().date(), dates.max().date()
            col1, col2 = st.columns(2)
            start = col1.date_input("시작일", value=min_d, min_value=min_d, max_value=max_d)
            end = col2.date_input("종료일", value=max_d, min_value=min_d, max_value=max_d)
            filters["date_range"] = (str(start), str(end))

    risk_opts = ["High", "Medium", "Low", "Normal"]
    selected_risks = st.multiselect("위험 등급", risk_opts, default=risk_opts)
    if selected_risks and len(selected_risks) < len(risk_opts):
        filters["risk_levels"] = selected_risks

    if "debit_amount" in df.columns:
        amt_min = float(df["debit_amount"].min())
        amt_max = float(df["debit_amount"].max())
        if amt_min < amt_max:
            amount = st.slider(
                "금액 범위", min_value=amt_min, max_value=amt_max,
                value=(amt_min, amt_max), format="%.0f",
            )
            if amount != (amt_min, amt_max):
                filters["amount_range"] = amount

    rule_opts = [f"{k} ({v})" for k, v in RULE_CODES.items()]
    selected_rules = st.multiselect("위반 룰", rule_opts)
    if selected_rules:
        # Why: "A01 (차대변 균형)" → "A01" 추출.
        filters["rule_codes"] = [r.split(" ")[0] for r in selected_rules]

    # ── 차원 필터 6개 (st.expander) ───────────────────────
    with st.expander("상세 필터"):
        for filter_key, col_name, label in _DIMENSION_FILTERS:
            if col_name in options:
                selected = st.multiselect(label, options[col_name])
                if selected:
                    filters[filter_key] = selected  # type: ignore[literal-required]

    # ── 개발 모드 필터 2개 ────────────────────────────────
    if st.session_state.get(KEY_DEV_MODE, False):
        st.caption("개발 모드 전용 필터")
        for filter_key, col_name, label in _DEV_FILTERS:
            if col_name in options:
                selected = st.multiselect(label, options[col_name])
                if selected:
                    filters[filter_key] = selected  # type: ignore[literal-required]

    st.session_state[KEY_FILTERS] = filters


def apply_filters(df: pd.DataFrame, filters: FilterState) -> pd.DataFrame:
    """FilterState dict → boolean mask → 필터된 DataFrame 반환.

    빈 dict이면 전체 데이터 반환.
    """
    if not filters or df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    # 날짜 범위
    if "date_range" in filters and "posting_date" in df.columns:
        start, end = filters["date_range"]
        dates = pd.to_datetime(df["posting_date"], errors="coerce")
        mask &= (dates >= start) & (dates <= end)

    # 위험 등급
    if "risk_levels" in filters and "risk_level" in df.columns:
        mask &= df["risk_level"].isin(filters["risk_levels"])

    # 금액 범위
    if "amount_range" in filters and "debit_amount" in df.columns:
        lo, hi = filters["amount_range"]
        mask &= df["debit_amount"].between(lo, hi)

    # 위반 룰 (벡터화 정규식 매칭)
    if "rule_codes" in filters and "flagged_rules" in df.columns:
        # Why: .apply(lambda) 루프는 1M행에서 느림. str.contains 벡터화가 ~10× 빠름.
        import re
        pattern = "|".join(re.escape(code) for code in filters["rule_codes"])
        mask &= df["flagged_rules"].fillna("").str.contains(pattern, regex=True)

    # 차원 필터 6개 + 개발 필터 2개 (동일 패턴 루프)
    _all_filters = _DIMENSION_FILTERS + _DEV_FILTERS
    for filter_key, col_name, _ in _all_filters:
        if filter_key in filters and col_name in df.columns:
            mask &= df[col_name].isin(filters[filter_key])  # type: ignore[arg-type]

    return df[mask]
