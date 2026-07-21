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


@lru_cache(maxsize=1)
def _vocab():
    return load_combo_vocabulary()


_EDITOR_KEYS = ("combo_editor_body", "combo_editor_feat")


def _apply_preset(preset: dict[str, Any]) -> None:
    """프리셋 = 저장된 체크 상태(등급 선언 아님). 선택 목록 세팅 + data_editor 상태 리셋."""
    st.session_state[_BODY_KEY] = list(preset["bodies"])
    st.session_state[_FEATURE_KEY] = list(preset["features"])
    # data_editor 내부 편집 상태가 남으면 df 초기 '선택' 열을 덮어써 프리셋이 반영 안 된다 → 리셋.
    for k in _EDITOR_KEYS:
        st.session_state.pop(k, None)


def _clear_selection() -> None:
    st.session_state[_BODY_KEY] = []
    st.session_state[_FEATURE_KEY] = []
    for k in _EDITOR_KEYS:
        st.session_state.pop(k, None)


def _rule_selector_table(items, sel_key: str, editor_key: str) -> None:
    """룰 선택 표 — 룰·이름을 펼쳐 보여주고 체크박스로 복수선택. 선택 결과를 sel_key 에 저장."""
    selected = set(st.session_state.get(sel_key) or [])
    df = pd.DataFrame(
        [
            {"선택": it["rule_id"] in selected, "룰": str(it["rule_id"]), "이름": str(it["label"])}
            for it in items
        ]
    )
    cfg: dict[str, Any] = {
        "선택": st.column_config.CheckboxColumn("선택", width="small"),
        "룰": st.column_config.TextColumn("룰", width="small"),
        "이름": st.column_config.TextColumn("이름", width="large"),
    }
    edited = st.data_editor(
        df,
        key=editor_key,
        hide_index=True,
        width="stretch",
        height=38 + 35 * len(df),
        column_config=cfg,
        disabled=["룰", "이름"],
    )
    st.session_state[sel_key] = edited.loc[edited["선택"], "룰"].tolist()


def _rule_group_expr(rule_ids: list[str], name_of: dict[str, str]) -> str:
    """룰 묶음을 `L3-10 추정계정 or L3-03 관계사` 형태의 OR 논리식으로. 2개 이상이면 괄호."""
    parts = [f"{r} {name_of.get(r, '')}".strip() for r in rule_ids]
    joined = " <span style='color:#9CA3AF'>or</span> ".join(parts)
    return f"({joined})" if len(parts) > 1 else joined


def _render_preset_cards(vocab) -> None:
    """금감원 적발 유형 = 어떤 룰 조합인지 논리식으로 명시한 선택 카드. 클릭 시 몸통·특징을 세팅한다."""
    # 몸통·특징 라벨을 한 사전으로 합쳐 논리식에 직접 룰ID+이름을 박는다(추상 라벨 폐기).
    name_of = {r["rule_id"]: str(r["label"]) for r in (*vocab.bodies, *vocab.features)}
    # Why: 4칸에 쑤셔넣으면 특징 목록이 세로로 접혀 못 읽는다 → 프리셋을 전체 폭 카드로 세로로 쌓고,
    #   논리식은 가로로 넉넉히 흐르게(엔진 결합 의미론: 그룹 내 OR / 그룹 간 AND 그대로).
    #   아래 '직접 조합'과 동일하게 expander 로 접었다 펴게 한다.
    with st.expander("금감원 사례 조합 — 실제 감리 적발 수법", expanded=True):
        for preset in vocab.presets:
            _render_preset_card(preset, name_of)


def _render_preset_card(preset: dict[str, Any], name_of: dict[str, str]) -> None:
    body_expr = _rule_group_expr(preset["bodies"], name_of)
    feat_expr = _rule_group_expr(preset["features"], name_of)
    with st.container(border=True):
        text_col, btn_col = st.columns([5, 1], vertical_alignment="center")
        # 대상 / and / 수법 을 각각 독립 줄로 고정 → 카드마다 동일한 3단 구조(들쭉날쭉 제거).
        #   and 위아래 여백으로 두 그룹을 시각적으로 분리.
        text_col.markdown(
            "<div style='font-size:0.82rem; line-height:1.7;'>"
            f"<div style='font-weight:700; font-size:0.95rem; color:#111827; "
            f"margin-bottom:8px;'>{preset['label']}</div>"
            f"<div style='color:#374151;'>{body_expr}</div>"
            "<div style='color:#B91C1C; font-weight:700; margin:6px 0; "
            "letter-spacing:0.08em;'>and</div>"
            f"<div style='color:#374151;'>{feat_expr}</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        btn_col.button(
            "이 유형으로 검토",
            key=f"combo_preset_{preset['preset_id']}",
            on_click=_apply_preset,
            args=(preset,),
            use_container_width=True,
            type="primary",
        )


def render_combo_builder_panel(pr, *, build_result: Callable[..., dict] | None = None) -> None:
    vocab = _vocab()

    st.markdown("#### 검토 조합")

    _render_preset_cards(vocab)

    with st.expander("직접 조합 - 조작 대상 x 조작 수법", expanded=False):
        st.caption("복수 선택 가능")
        col_target, col_method = st.columns(2)
        with col_target:
            st.markdown("**조작 대상**")
            _rule_selector_table(vocab.bodies, _BODY_KEY, _EDITOR_KEYS[0])
        with col_method:
            st.markdown("**조작 방법**")
            _rule_selector_table(vocab.features, _FEATURE_KEY, _EDITOR_KEYS[1])

    bodies = list(st.session_state.get(_BODY_KEY) or [])
    features = list(st.session_state.get(_FEATURE_KEY) or [])

    if not bodies and not features:
        st.info("위 금감원 적발 유형을 고르거나, '직접 조합하기'에서 몸통·특징을 선택하세요.")
        return

    # 선택 요약 + 초기화 — 프리셋이 접힌 expander 안 pills 를 세팅해도 무엇이 선택됐는지 보이게.
    sel_col, clear_col = st.columns([5, 1])
    sel_body = ", ".join(vocab_label(vocab.bodies, bodies)) or "—"
    sel_feat = ", ".join(vocab_label(vocab.features, features)) or "—"
    sel_col.markdown(f"**선택된 조합** · 몸통: {sel_body} · 특징: {sel_feat}")
    clear_col.button(
        "초기화", key="combo_clear", on_click=_clear_selection, use_container_width=True
    )

    build = build_result or (lambda **kw: build_combo_builder_result(pr, **kw))
    result = build(
        bodies=tuple(sorted(bodies)),
        features=tuple(sorted(features)),
        top_n=_RESULT_CAP,
    )
    if not result.get("available"):
        st.info("PHASE1 case 결과가 없어 조합을 실행할 수 없습니다.")
        return

    matched = int(result.get("matched", 0))
    rows = result.get("rows") or []
    st.caption(
        f"일치 전표·흐름 **{matched:,}건**"
        + (f" (상위 {len(rows)}건 표시)" if matched > len(rows) else "")
    )
    if not rows:
        st.info("선택한 조합에 걸리는 전표가 없습니다.")
        return
    render_unit_result_grid(rows, pr, key_prefix="combo_builder")


def vocab_label(items, selected: list[str]) -> list[str]:
    """선택된 rule_id 를 한국어 라벨로 (선택 요약용)."""
    label_of = {item["rule_id"]: str(item["label"]) for item in items}
    return [label_of[rid] for rid in selected if rid in label_of]


def render_unit_result_grid(
    rows: list[dict[str, Any]], pr: Any, *, key_prefix: str = "combo_builder"
) -> None:
    """전표/흐름 결과 그리드 + 행 클릭 시 실제 분개 라인 드릴다운.

    조합 빌더와 룰별 커버리지가 동일한 표면을 공유하도록 재사용한다. key_prefix 로
    같은 페이지의 두 그리드 상태(선택·분개)를 분리한다.
    """
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    from dashboard.tab_phase1 import _BADGE_LABELS_KR, _format_amount_short

    # unit_id → 구성 문서ID(흐름은 복수). 선택 후 원장 라인 조회에 사용.
    doc_ids_by_unit = {
        str(row["unit_id"]): [str(d) for d in (row.get("document_ids") or [])] for row in rows
    }
    grid_rows = [
        {
            "unit_id": row["unit_id"],
            "순위": idx,
            "작성자": str(row.get("created_by") or "-") or "-",
            "전기일": str(row.get("posting_date") or "-") or "-",
            "거래처": str(row.get("counterparty") or "-") or "-",
            "합계": _format_amount_short(float(row.get("total_amount") or 0.0)),
            "발화 룰": " · ".join(row.get("fired_rule_labels") or []) or "-",
            # PHASE1-2 분석적 검토 배지(점수 비병합) — 한국어 라벨로 오버레이.
            "배지": " · ".join(
                sorted(
                    {_BADGE_LABELS_KR.get(str(t), str(t)) for t in (row.get("badge_tags") or [])}
                )
            )
            or "-",
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
    gb.configure_column("작성자", minWidth=90, maxWidth=140, tooltipField="작성자")
    gb.configure_column("전기일", minWidth=96, maxWidth=120)
    gb.configure_column("거래처", minWidth=110, maxWidth=200, tooltipField="거래처")
    gb.configure_column("합계", minWidth=80, maxWidth=110)
    gb.configure_column("발화 룰", minWidth=260, flex=1, tooltipField="발화 룰")
    gb.configure_column("배지", minWidth=120, maxWidth=240, tooltipField="배지")

    response = AgGrid(
        unit_df,
        gridOptions=gb.build(),
        height=320,
        theme="streamlit",
        key=f"phase1_{key_prefix}_grid",
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        reload_data=False,
        fit_columns_on_grid_load=False,
    )
    _render_selected_journal(response, doc_ids_by_unit, pr, key_prefix=key_prefix)


def _render_selected_journal(
    response: Any, doc_ids_by_unit: dict[str, list[str]], pr: Any, *, key_prefix: str
) -> None:
    """선택된 행의 전표(흐름이면 구성 전표들) 분개 라인을 그리드 아래 펼친다."""
    from dashboard.tab_phase1 import _case_document_raw_lines, _render_raw_lines_table

    selected = response.get("selected_rows", [])
    if hasattr(selected, "to_dict"):
        selected = selected.to_dict("records")
    if not selected:
        st.caption("행을 클릭하면 해당 전표의 실제 분개(차변·대변) 라인이 아래에 펼쳐집니다.")
        return

    unit_id = str(selected[0].get("unit_id") or "")
    document_ids = doc_ids_by_unit.get(unit_id) or ([unit_id] if unit_id else [])
    raw_lines: list[dict[str, Any]] = []
    for document_id in document_ids:
        raw_lines.extend(_case_document_raw_lines(pr, document_id))

    st.markdown(f"##### 분개 라인 · `{unit_id}`")
    if not raw_lines:
        # featured_data/data 가 메모리에 없는 폴백 로드 세션 — 원장 원천이 없다.
        st.info(
            "이 세션에 원장 데이터가 없어 분개 라인을 표시할 수 없습니다. Phase 1 분석을 다시 실행하면 표시됩니다."
        )
        return
    _render_raw_lines_table("", raw_lines, key_suffix=f"{key_prefix}_{unit_id}")
