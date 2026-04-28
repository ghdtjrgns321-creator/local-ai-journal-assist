"""룰 컨트롤 패널.

Why: 감사인 기본 UI에는 룰 활성/비활성만 노출하고,
     레이어 가중치와 위험등급 임계값은 개발 모드에서만 조정한다.
"""

from __future__ import annotations

import streamlit as st

from dashboard._state import (
    KEY_DISABLED_RULES,
    KEY_LAYER_WEIGHTS,
    KEY_RISK_THRESHOLDS,
    KEY_SETTINGS_DIRTY,
)
from src.detection.constants import (
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    RULE_CODES,
    SEVERITY_MAP,
    Layer,
    RiskLevel,
)

_TRACK_LABELS = {
    Layer.LAYER_A: "L1/L3 Data Quality",
    Layer.LAYER_B: "L1-L4 Fraud Rules",
    Layer.LAYER_C: "L1-L4 Anomaly Rules",
    Layer.BENFORD: "L4-02 Benford",
}

# Why: 내부 detector track은 유지하되, 사용자 패널에서는 L1/L2/L3/L4 기준으로 그룹핑한다.
_RULE_GROUPS = ("L1", "L2", "L3", "L4")


def _render_layer_weights() -> None:
    """레이어 가중치 4개 슬라이더 + 합계 검증."""
    st.subheader("레이어 가중치")
    current = st.session_state.get(KEY_LAYER_WEIGHTS)
    if current is None:
        current = {k.value: v for k, v in LAYER_WEIGHTS.items()}

    weights: dict[str, float] = {}
    for layer, label in _TRACK_LABELS.items():
        weights[layer.value] = st.slider(
            label, 0.0, 1.0,
            value=current.get(layer.value, LAYER_WEIGHTS[layer]),
            step=0.05,
            key=f"rp_w_{layer.value}",
        )

    total = sum(weights.values())
    st.metric("합계", f"{total:.2f}")
    if abs(total - 1.0) > 0.01:
        st.error(f"가중치 합계 {total:.2f} ≠ 1.0 — 적용 불가")

    if weights != current:
        st.session_state[KEY_LAYER_WEIGHTS] = weights
        st.session_state[KEY_SETTINGS_DIRTY] = True


def _render_risk_thresholds() -> None:
    """위험등급 임계값 3개 슬라이더."""
    st.subheader("위험등급 임계값")
    current = st.session_state.get(KEY_RISK_THRESHOLDS)
    if current is None:
        current = dict(RISK_THRESHOLDS)

    high = st.slider(
        "High", 0.50, 0.95,
        value=current.get(RiskLevel.HIGH, 0.7), step=0.05, key="rp_t_high",
    )
    medium = st.slider(
        "Medium", 0.20, high - 0.05,
        value=min(current.get(RiskLevel.MEDIUM, 0.4), high - 0.05),
        step=0.05, key="rp_t_medium",
    )
    low = st.slider(
        "Low", 0.05, medium - 0.05,
        value=min(current.get(RiskLevel.LOW, 0.2), medium - 0.05),
        step=0.05, key="rp_t_low",
    )

    new_t = {RiskLevel.HIGH: high, RiskLevel.MEDIUM: medium, RiskLevel.LOW: low}
    if new_t != current:
        st.session_state[KEY_RISK_THRESHOLDS] = new_t
        st.session_state[KEY_SETTINGS_DIRTY] = True


def _render_rule_toggles() -> None:
    """27개 룰 활성/비활성 체크박스 (L1~L4 그룹)."""
    st.subheader("룰 활성/비활성")
    disabled: list[str] = list(st.session_state.get(KEY_DISABLED_RULES, []))
    new_disabled: list[str] = []

    cols = st.columns(4)
    for i, prefix in enumerate(_RULE_GROUPS):
        with cols[i]:
            st.caption(prefix)
            for code, name in RULE_CODES.items():
                if not code.startswith(prefix):
                    continue
                severity = SEVERITY_MAP.get(code, 0)
                enabled = st.checkbox(
                    f"{code} {name} ({'★' * severity})",
                    value=code not in disabled,
                    key=f"rp_rule_{code}",
                )
                if not enabled:
                    new_disabled.append(code)

    if sorted(new_disabled) != sorted(disabled):
        st.session_state[KEY_DISABLED_RULES] = new_disabled
        st.session_state[KEY_SETTINGS_DIRTY] = True


def render_rule_panel(*, show_admin: bool = False) -> None:
    """룰 설정 패널 렌더링."""
    with st.expander("📋 룰 선택", expanded=False):
        _render_rule_toggles()

    if not show_admin:
        return

    with st.expander("🛠 룰 관리자 설정", expanded=False):
        _render_layer_weights()
        st.divider()
        _render_risk_thresholds()
