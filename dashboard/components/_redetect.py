"""설정 변경 후 탐지 재실행 헬퍼 + "적용" 버튼.

Why: 임계값/가중치/룰 변경 후 detection+aggregate만 재실행하여
     _generate_features 중복 실행으로 인한 데이터 오염 방지.
"""

from __future__ import annotations

import re

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_DISABLED_RULES,
    KEY_FEATURED_DATA,
    KEY_LAYER_WEIGHTS,
    KEY_PIPELINE_RESULT,
    KEY_RISK_THRESHOLDS,
    KEY_SETTINGS,
    KEY_SETTINGS_DIRTY,
)
from src.detection.constants import LAYER_WEIGHTS


def _filter_disabled_rules(result, disabled: list[str]) -> None:
    """비활성 룰 완전 제거: details 0 마스킹 + flagged_rules 문자열 정리.

    Why: details만 0으로 마스킹하면 flagged_rules에 비활성 룰이 계속 노출됨.
         2단계 처리로 대시보드 전체 일관성 보장.
         copy()로 새 details를 만들어 원본 DetectionResult 보호 — 룰 재활성화 시 복원 가능.
    """
    from copy import deepcopy

    # 1단계: DetectionResult.details 복사본에서 비활성 룰 컬럼 0 마스킹
    new_results = []
    for dr in result.results:
        new_dr = deepcopy(dr)
        for code in disabled:
            if code in new_dr.details.columns:
                new_dr.details[code] = 0.0
        new_results.append(new_dr)
    result.results = new_results

    # 2단계: flagged_rules 문자열에서 비활성 룰 코드 제거
    if "flagged_rules" in result.data.columns and disabled:
        pattern = "|".join(re.escape(r) for r in disabled)
        result.data["flagged_rules"] = (
            result.data["flagged_rules"]
            .str.replace(rf"\b({pattern})\b,?\s*", "", regex=True)
            .str.strip(",")
            .str.strip()
        )


def rerun_detection() -> bool:
    """KEY_FEATURED_DATA에서 클린 DF 추출 → detection+aggregate 재실행."""
    # Why: 순환 임포트 방지 — dashboard → pipeline → dashboard 경로 차단
    from src.pipeline import AuditPipeline

    featured_df = st.session_state.get(KEY_FEATURED_DATA)
    if featured_df is None:
        st.error("피처 데이터 없음 — 파일을 먼저 업로드하세요.")
        return False

    settings = st.session_state.get(KEY_SETTINGS)
    weights = st.session_state.get(KEY_LAYER_WEIGHTS)
    thresholds = st.session_state.get(KEY_RISK_THRESHOLDS)
    batch_id = st.session_state.get(KEY_BATCH_ID, "")

    pipeline = AuditPipeline(settings=settings, skip_db=True)
    result = pipeline.redetect(
        featured_df,
        batch_id=batch_id,
        weights=weights,
        thresholds=thresholds,
    )

    # Why: 비활성 룰 필터링은 재탐지 후 post-hoc 처리
    disabled = st.session_state.get(KEY_DISABLED_RULES, [])
    if disabled:
        _filter_disabled_rules(result, disabled)

    st.session_state[KEY_PIPELINE_RESULT] = result
    st.session_state[KEY_SETTINGS_DIRTY] = False
    return True


def render_apply_button() -> None:
    """'적용' 버튼. 가중치 합≠1.0이면 disabled."""
    dirty = st.session_state.get(KEY_SETTINGS_DIRTY, False)
    if not dirty:
        return

    weights = st.session_state.get(KEY_LAYER_WEIGHTS)
    if weights is None:
        weights = {k.value: v for k, v in LAYER_WEIGHTS.items()}
    total = sum(weights.values())
    valid = abs(total - 1.0) <= 0.01

    # Why: 에러 메시지는 rule_panel.py에서 이미 표시 — 여기서는 버튼 disabled만 처리
    if st.button("🔄 설정 적용", disabled=not valid, use_container_width=True):
        with st.spinner("탐지 재실행 중..."):
            ok = rerun_detection()
        if ok:
            st.rerun()
