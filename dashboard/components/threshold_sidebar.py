"""감사인용 탐지 설정 패널.

Why: 감사인 기본 UI에는 업무 정책/결과 기반 튜닝만 노출하고,
     통계·스코어 내부값은 개발 모드에서만 조정한다.
"""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from config.settings import AuditSettings, get_settings
from dashboard._state import KEY_PRESET, KEY_SETTINGS, KEY_SETTINGS_DIRTY

# ── 카테고리별 필드 정의 ───────────────────────────────────────
# (field_name, label, widget_type, kwargs)
# Why: 위젯 타입·범위를 선언적으로 관리하여 100줄 이내 유지

_FIELD_DEFS: dict[str, list[tuple[str, str, str, dict]]] = {
    "감사인 체크리스트": [
        ("approval_thresholds", "승인 한도", "data_editor", {}),
        ("period_end_margin_days", "마감 허용일", "slider", {"min_value": 1, "max_value": 15}),
        (
            "normal_hours_start",
            "업무 시작",
            "slider",
            {"min_value": 6.0, "max_value": 12.0, "step": 0.5},
        ),
        (
            "normal_hours_end",
            "업무 종료",
            "slider",
            {"min_value": 15.0, "max_value": 22.0, "step": 0.5},
        ),
        ("midnight_start", "심야 시작(시)", "slider", {"min_value": 0, "max_value": 24}),
        ("midnight_end", "심야 종료(시)", "slider", {"min_value": 0, "max_value": 8}),
        ("settlement_start_mmdd", "결산 시작(MMDD)", "text_input", {}),
        ("settlement_end_mmdd", "결산 종료(MMDD)", "text_input", {}),
    ],
    "결과 기반 튜닝": [
        (
            "near_threshold_ratio",
            "승인 직하 비율",
            "slider",
            {"min_value": 0.80, "max_value": 0.99, "step": 0.01},
        ),
        (
            "duplicate_payment_window_days",
            "중복지급(일)",
            "slider",
            {"min_value": 7, "max_value": 90},
        ),
        (
            "backdated_threshold_days",
            "날짜괴리 허용일",
            "slider",
            {"min_value": 7, "max_value": 90},
        ),
        ("round_unit", "정수 단위", "selectbox", {"options": [100_000, 1_000_000, 10_000_000]}),
        (
            "period_end_amount_quantile",
            "기말 고액 분위수",
            "slider",
            {"min_value": 0.50, "max_value": 0.95, "step": 0.05},
        ),
        (
            "benford_mad_threshold",
            "Benford MAD",
            "slider",
            {"min_value": 0.006, "max_value": 0.025, "step": 0.001, "format": "%.3f"},
        ),
    ],
}

_ADMIN_FIELD_DEFS: dict[str, list[tuple[str, str, str, dict]]] = {
    "내부 통계/스코어": [
        (
            "zscore_threshold",
            "Z-score 기준",
            "slider",
            {"min_value": 2.0, "max_value": 5.0, "step": 0.1},
        ),
        (
            "abnormal_sigma_threshold",
            "σ 이상치",
            "slider",
            {"min_value": 2.0, "max_value": 5.0, "step": 0.1},
        ),
        ("sod_process_threshold", "SoD 임계", "slider", {"min_value": 2, "max_value": 5}),
        (
            "rare_account_pair_cadence_per_quarter",
            "희소쌍 cadence(분기당)",
            "slider",
            {"min_value": 0.5, "max_value": 4.0, "step": 0.5, "format": "%.1f"},
        ),
        ("rapid_approval_minutes", "부실검토(분)", "slider", {"min_value": 1, "max_value": 30}),
        (
            "min_abnormal_ratio",
            "최소이상비율",
            "slider",
            {"min_value": 0.05, "max_value": 0.30, "step": 0.01},
        ),
        ("min_midnight_entries", "최소심야건수", "slider", {"min_value": 1, "max_value": 10}),
        ("min_user_entries", "최소사용자건수", "slider", {"min_value": 5, "max_value": 50}),
        (
            "reversal_score_threshold",
            "역분개 임계",
            "slider",
            {"min_value": 0.1, "max_value": 0.9, "step": 0.05},
        ),
    ],
}

_MMDD_RE = re.compile(r"^(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$")


def _get_current_settings() -> AuditSettings:
    """session_state에서 현재 설정 반환. 없으면 기본 생성."""
    s = st.session_state.get(KEY_SETTINGS)
    if s is None:
        s = get_settings()
        st.session_state[KEY_SETTINGS] = s
    return s


def _render_widget(field: str, label: str, wtype: str, kwargs: dict, val: object) -> object:
    """필드 정의에 따라 적절한 위젯을 렌더링하고 새 값 반환."""
    key = f"ts_{field}"
    if wtype == "slider":
        return st.slider(label, value=val, key=key, **kwargs)
    if wtype == "selectbox":
        opts = kwargs["options"]
        idx = opts.index(val) if val in opts else 0
        return st.selectbox(label, opts, index=idx, key=key, format_func=lambda x: f"{x:,}")
    if wtype == "text_input":
        new_val = st.text_input(label, value=str(val), key=key)
        if not _MMDD_RE.match(new_val):
            st.caption("MMDD 형식 (예: 1220)")
            return val  # Why: 유효하지 않으면 기존 값 유지
        return new_val
    if wtype == "data_editor":
        # Why: approval_thresholds는 6단계 리스트 → 편집 가능 테이블
        df = pd.DataFrame({"Level": range(1, len(val) + 1), "금액": list(val)})
        edited = st.data_editor(df, key=key, hide_index=True, num_rows="fixed")
        # Why: pandas가 float64로 추론할 수 있으므로 int 강제 변환
        return edited["금액"].astype(int).tolist()
    return val


def _field_names(defs: dict[str, list[tuple[str, str, str, dict]]]) -> set[str]:
    return {field for fields in defs.values() for field, _, _, _ in fields}


def auditor_field_names() -> set[str]:
    """감사인 기본 UI에 노출되는 설정 필드."""
    return _field_names(_FIELD_DEFS)


def admin_field_names() -> set[str]:
    """개발/관리자 모드에만 노출되는 설정 필드."""
    return _field_names(_ADMIN_FIELD_DEFS)


def _render_field_tabs(
    defs: dict[str, list[tuple[str, str, str, dict]]],
    settings: AuditSettings,
) -> dict[str, object]:
    overrides: dict[str, object] = {}
    tabs = st.tabs(list(defs.keys()))

    for tab, (_cat, fields) in zip(tabs, defs.items()):
        with tab:
            for field, label, wtype, kwargs in fields:
                current_val = getattr(settings, field)
                new_val = _render_widget(field, label, wtype, kwargs, current_val)
                if new_val != current_val:
                    overrides[field] = new_val
    return overrides


def render_threshold_sidebar(*, show_admin: bool = False) -> None:
    """감사인 설정과 관리자 설정을 분리해 렌더링."""
    with st.expander("⚙️ 감사인 설정", expanded=False):
        settings = _get_current_settings()
        overrides = _render_field_tabs(_FIELD_DEFS, settings)

        # Why: 변경 사항이 있을 때만 session_state 갱신
        if overrides:
            st.session_state[KEY_SETTINGS] = settings.model_copy(update=overrides)
            st.session_state[KEY_PRESET] = "custom"
            st.session_state[KEY_SETTINGS_DIRTY] = True

    if not show_admin:
        return

    with st.expander("🛠 관리자 설정", expanded=False):
        settings = _get_current_settings()
        overrides = _render_field_tabs(_ADMIN_FIELD_DEFS, settings)
        if overrides:
            st.session_state[KEY_SETTINGS] = settings.model_copy(update=overrides)
            st.session_state[KEY_PRESET] = "custom"
            st.session_state[KEY_SETTINGS_DIRTY] = True
