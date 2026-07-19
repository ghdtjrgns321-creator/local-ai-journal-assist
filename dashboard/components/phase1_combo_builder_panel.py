"""PHASE1-1 조합 빌더 패널 — tier 폐지 후 주 검토 표면.

SoT: docs/spec/PHASE1_COMBO_BUILDER_SPEC.md. 어휘·프리셋은 config/combo_builder.yaml
(src.export.phase1_combo_builder 경유). 시스템은 등급을 매기지 않는다 — 조합 선택 = 감사인 판단.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import pandas as pd
import streamlit as st

from src.export.phase1_combo_builder import build_combo_builder_result, load_combo_vocabulary

_RESULT_CAP = 200  # 그리드 표시 상한. matched 집계는 절단 전 전체 수를 유지한다.
_BODY_KEY = "combo_builder_bodies"
_FEATURE_KEY = "combo_builder_features"
_STRICT_KEY = "combo_builder_strict"
_UNIT_TYPE_LABELS = {"document": "전표", "flow": "흐름"}


@lru_cache(maxsize=1)
def _vocab():
    return load_combo_vocabulary()


def _apply_preset(preset: dict[str, Any]) -> None:
    """프리셋 = 저장된 체크 상태(등급 선언 아님). pills 위젯 키에 직접 주입."""
    st.session_state[_BODY_KEY] = list(preset["bodies"])
    st.session_state[_FEATURE_KEY] = list(preset["features"])


def render_combo_builder_panel(pr, *, build_result: Callable[..., dict] | None = None) -> None:
    vocab = _vocab()
    body_label = {b["rule_id"]: f"{b['label']} ({b['fss_confirmed']})" for b in vocab.bodies}
    feature_label = {f["rule_id"]: str(f["label"]) for f in vocab.features}

    st.markdown("#### 조합 빌더 — 몸통(조작 대상) × 특징(전표 모양)")
    st.caption(
        "몸통 = 금감원 감리 반복 적발 대상(괄호 = 확정 태깅 건수), "
        "특징 = 감사기준서 240이 명시한 부정 분개의 모양. "
        "조합 선택은 감사인의 판단이며 시스템은 등급을 매기지 않습니다."
    )

    preset_cols = st.columns(len(vocab.presets))
    for col, preset in zip(preset_cols, vocab.presets):
        col.button(
            str(preset["label"]),
            key=f"combo_preset_{preset['preset_id']}",
            help=str(preset.get("rationale", "")),
            on_click=_apply_preset,
            args=(preset,),
            use_container_width=True,
        )

    bodies = st.pills(
        "몸통 (조작 대상)",
        options=[b["rule_id"] for b in vocab.bodies],
        format_func=lambda rid: body_label[rid],
        selection_mode="multi",
        key=_BODY_KEY,
    )
    features = st.pills(
        "특징 (전표 모양)",
        options=[f["rule_id"] for f in vocab.features],
        format_func=lambda rid: feature_label[rid],
        selection_mode="multi",
        key=_FEATURE_KEY,
    )
    strict = st.toggle("선택한 룰을 전부 발화한 전표만 (엄격 모드)", key=_STRICT_KEY)

    with st.expander("선택 항목의 근거 보기", expanded=False):
        for item in vocab.bodies:
            if item["rule_id"] in set(bodies or []):
                st.markdown(f"- **{item['label']}** ({item['rule_id']}) — {item['basis']}")
        for item in vocab.features:
            if item["rule_id"] in set(features or []):
                st.markdown(f"- **{item['label']}** ({item['rule_id']}) — {item['basis']}")

    if not bodies and not features:
        st.info("몸통·특징에서 1개 이상 선택하거나 프리셋 버튼을 누르세요.")
        return

    build = build_result or (lambda **kw: build_combo_builder_result(pr, **kw))
    result = build(
        bodies=tuple(sorted(bodies or [])),
        features=tuple(sorted(features or [])),
        strict=bool(strict),
        top_n=_RESULT_CAP,
    )
    if not result.get("available"):
        st.info("PHASE1 case 결과가 없어 빌더를 실행할 수 없습니다.")
        return

    matched = int(result.get("matched", 0))
    rows = result.get("rows") or []
    st.caption(
        f"일치 전표·흐름 **{matched:,}건**"
        + (f" (상위 {len(rows)}건 표시)" if matched > len(rows) else "")
    )
    if not rows:
        return
    _render_result_grid(rows)


def _render_result_grid(rows: list[dict[str, Any]]) -> None:
    """빌더 결과 그리드 — 기존 unit 큐 AgGrid 패턴 재사용, Band 컬럼 없음(tier 폐지)."""
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    from dashboard.tab_phase1 import _format_amount_short

    grid_rows = [
        {
            "unit_id": row["unit_id"],
            "순위": idx,
            "단위": _UNIT_TYPE_LABELS.get(row["unit_type"], row["unit_type"]),
            "시점심각도": int(row.get("time_severity_score") or 0),
            "합계": _format_amount_short(float(row.get("total_amount") or 0.0)),
            "발화 룰": " · ".join(row.get("fired_rule_labels") or []) or "-",
        }
        for idx, row in enumerate(rows, start=1)
    ]
    unit_df = pd.DataFrame(grid_rows)
    gb = GridOptionsBuilder.from_dataframe(unit_df)
    gb.configure_default_column(resizable=True, filter=True, sortable=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=50)
    gb.configure_grid_options(rowHeight=34, rowBuffer=10, suppressCellFocus=True)
    gb.configure_column("unit_id", hide=True)
    gb.configure_column("순위", type=["numericColumn"], minWidth=44, maxWidth=56, pinned="left")
    gb.configure_column("단위", minWidth=64, maxWidth=88)
    gb.configure_column("시점심각도", type=["numericColumn"], minWidth=84, maxWidth=110)
    gb.configure_column("합계", minWidth=80, maxWidth=110)
    gb.configure_column("발화 룰", minWidth=360, flex=1, tooltipField="발화 룰")

    AgGrid(
        unit_df,
        gridOptions=gb.build(),
        height=320,
        theme="streamlit",
        key="phase1_combo_builder_grid",
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        reload_data=False,
        fit_columns_on_grid_load=False,
    )
