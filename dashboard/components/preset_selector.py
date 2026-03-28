"""프리셋 드롭다운 — 산업별/시즌별 설정 일괄 적용.

Why: 감사인이 개별 슬라이더 조작 없이 드롭다운만으로 적절한 기준값 세트를 전환.
     기본 3개 프리셋은 config/presets/ YAML, 커스텀은 session_state 전용 (디스크 미저장).
"""

from __future__ import annotations

import logging

import streamlit as st
import yaml

from config.settings import AuditSettings, CONFIG_DIR, get_settings
from dashboard._state import KEY_PRESET, KEY_SETTINGS, KEY_SETTINGS_DIRTY

logger = logging.getLogger(__name__)

# Why: 상대 경로(Path("config/presets"))는 CWD 의존 — 절대 경로로 안전하게 참조
_PRESETS_DIR = CONFIG_DIR / "presets"
# Why: "커스텀"은 슬라이더 수정 시 자동 전환되는 센티넬 값
_CUSTOM_KEY = "custom"
_CUSTOM_LABEL = "커스텀"


def load_preset(name: str) -> dict[str, object]:
    """config/presets/{name}.yaml → overrides dict 반환.

    Why: model_copy(update=)는 Pydantic validator를 우회하므로
         알려진 필드만 허용하여 오타/잘못된 타입 유입 방지.
    """
    path = _PRESETS_DIR / f"{name}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    overrides = data.get("overrides", {})
    valid_fields = set(AuditSettings.model_fields)
    unknown = set(overrides) - valid_fields
    if unknown:
        logger.warning("프리셋 '%s' — 알 수 없는 필드 무시: %s", name, unknown)
    return {k: v for k, v in overrides.items() if k in valid_fields}


def list_presets() -> dict[str, str]:
    """사용 가능한 프리셋 목록 {파일명(확장자 제외): 표시명}."""
    presets: dict[str, str] = {}
    if _PRESETS_DIR.exists():
        for p in sorted(_PRESETS_DIR.glob("*.yaml")):
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            presets[p.stem] = data.get("name", p.stem)
    presets[_CUSTOM_KEY] = _CUSTOM_LABEL
    return presets


def render_preset_selector() -> None:
    """사이드바에 프리셋 드롭다운 렌더링."""
    presets = list_presets()
    keys = list(presets.keys())
    labels = list(presets.values())

    current = st.session_state.get(KEY_PRESET, "default")
    idx = keys.index(current) if current in keys else 0

    selected_label = st.selectbox(
        "환경 프리셋",
        labels,
        index=idx,
        key="wu5_preset_select",
    )
    selected_key = keys[labels.index(selected_label)]

    # Why: 프리셋이 변경된 경우에만 설정 갱신 (불필요한 rerun 방지)
    if selected_key != current and selected_key != _CUSTOM_KEY:
        overrides = load_preset(selected_key)
        new_settings = get_settings().model_copy(update=overrides)
        st.session_state[KEY_SETTINGS] = new_settings
        st.session_state[KEY_PRESET] = selected_key
        st.session_state[KEY_SETTINGS_DIRTY] = True
    elif selected_key != current and selected_key == _CUSTOM_KEY:
        st.session_state[KEY_PRESET] = _CUSTOM_KEY
