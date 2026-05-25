"""PHASE2 family lane view — Phase E dashboard 컴포넌트.

primary PHASE1+VAE 2-way RRF queue 옆에 family lane 보조 큐를 노출한다.
각 lane 은 evidence_tier 와 family ECDF 로 정렬된다 (Phase C 측정에서
hierarchical RRF reject 후 lane/overlay 구조로 전환).

본 컴포넌트는 primary queue 의 순위를 변경하지 않는다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.services.phase2_lane_sort import (
    lane_summary,
    list_active_lanes,
    sort_lane,
)

LANE_LABELS: dict[str, str] = {
    "duplicate": "Duplicate (중복 전표)",
    "relational": "Relational (관계망)",
    # 결정 9 (docs/PHASE2_TIMESERIES_ROLE_LOCK.md): timeseries 는 단독 ranker 가 아닌
    # 결산·시점 컨텍스트 보조 lane 으로 역할 고정.
    "timeseries": "Timing Context (결산·시점 보조)",
    "intercompany": "Intercompany (관계사)",
    "unsupervised": "Unsupervised (ML backbone)",
}

# lane 별 한계·역할 안내. timeseries 는 결정 9 락 정합 문구 (제품 언어).
# 내부 개발 지표(TOP100/500 recall 등)는 본 캡션에 노출하지 않는다.
# 내부 락 표현은 docs/PHASE2_TIMESERIES_ROLE_LOCK.md + PHASE2_GOVERNANCE_DESIGN 결정 9 참조.
LANE_ROLE_CAPTIONS: dict[str, str] = {
    "timeseries": (
        "상단 정밀 ranker 가 아니라 결산·시점 맥락을 보강하는 lane 입니다. "
        "깊은 검토 범위에서 coverage 보조 용도로 해석하세요. "
        "primary queue 순위에는 영향을 주지 않습니다."
    ),
}


def build_lane_summary_frame(
    family_overlays: list[dict[str, Any]],
    family_roles: dict[str, str],
) -> pd.DataFrame:
    """family 별 lane 배지·count 를 한 표로 표시."""
    lanes = list_active_lanes(family_roles)
    rows = []
    for family in lanes:
        role = family_roles.get(family, "unknown")
        summary = lane_summary(family, family_overlays, family_role=role)
        rows.append(
            {
                "lane": LANE_LABELS.get(family, family),
                "family": family,
                "role": role,
                "case_count": summary["case_count"],
                "strong": summary["tier_counts"]["strong"],
                "moderate": summary["tier_counts"]["moderate"],
                "weak": summary["tier_counts"]["weak"],
                "review_only": summary.get("review_only_count", 0),
                "badge": summary["badge"],
            }
        )
    return pd.DataFrame(rows)


def build_lane_content_frame(
    family: str,
    family_overlays: list[dict[str, Any]],
    *,
    max_rows: int = 50,
) -> pd.DataFrame:
    """선택된 lane 의 case 목록 표.

    정렬: evidence_tier desc → family ECDF desc → score desc.
    """
    sorted_overlays = sort_lane(family, family_overlays)[:max_rows]
    rows = []
    for overlay in sorted_overlays:
        entry = next(
            (c for c in (overlay.get("family_contributions") or []) if c.get("family") == family),
            None,
        )
        if entry is None:
            continue
        sub_codes = ", ".join(
            sub.get("code", "")
            for sub in (entry.get("sub_detectors") or [])
            if isinstance(sub, dict)
        )
        rows.append(
            {
                "case_id": overlay.get("phase1_case_id", ""),
                "evidence_tier": entry.get("evidence_tier") or "-",
                "ecdf": _round(entry.get("ecdf")),
                "score": _round(entry.get("score")),
                "review_only_count": int(entry.get("review_only_count") or 0),
                "review_reasons": ", ".join(entry.get("review_reasons") or []) or "-",
                "sub_detectors": sub_codes or "-",
                "coverage_breadth_q95": int(overlay.get("coverage_breadth_q95") or 0),
                "top_family": overlay.get("top_family") or "-",
            }
        )
    return pd.DataFrame(rows)


def render_lane_view(
    family_overlays: list[dict[str, Any]],
    family_roles: dict[str, str],
) -> None:
    """Streamlit lane view — lane selector + 선택된 lane 의 case 목록."""
    if not family_roles:
        st.info("PHASE2 분석 영역 role 정보가 없습니다. 학습 리포트를 확인하세요.")
        return

    with st.container(border=True):
        st.markdown(
            "**PHASE2 분석 영역 Lane** — primary queue 보조 view &nbsp;`primary queue 영향 없음`",
            unsafe_allow_html=True,
        )
        st.caption(
            "primary PHASE1+VAE queue 의 순위는 변경되지 않습니다. "
            "lane 은 분석 영역 신호의 audit attribution 용도입니다."
        )
        summary_frame = build_lane_summary_frame(family_overlays, family_roles)
        st.dataframe(_display_lane_summary_frame(summary_frame), width="stretch", hide_index=True)

        available_lanes = list_active_lanes(family_roles)
        if not available_lanes:
            st.warning("진입한 분석 영역 lane 이 없습니다.")
            return
        selected = st.selectbox(
            "Lane 선택",
            options=available_lanes,
            format_func=lambda f: LANE_LABELS.get(f, str(f)),
            key="phase2_lane_selector",
        )
        if not isinstance(selected, str):  # selectbox return type guard
            return
        selected_role = family_roles.get(selected, "unknown")
        # 결정 9: timeseries lane 선택 시 역할 한계 caption 노출
        role_caption = LANE_ROLE_CAPTIONS.get(selected)
        if role_caption:
            st.caption(role_caption)
        content_frame = build_lane_content_frame(selected, family_overlays)
        if selected_role == "near-dormant" and content_frame.empty:
            st.warning(
                f"`{selected}` lane 은 대기 상태입니다 (데이터 미보유). "
                "IC02/IC03 enrichment 후 재평가 권장."
            )
            return
        if content_frame.empty:
            st.info(f"`{selected}` lane 에 진입한 case 가 없습니다.")
            return
        st.dataframe(_display_lane_content_frame(content_frame), width="stretch", hide_index=True)


def _display_lane_summary_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(
        columns={
            "lane": "Lane",
            "family": "분석 영역 코드",
            "role": "역할",
            "case_count": "케이스 수",
            "strong": "강",
            "moderate": "중",
            "weak": "약",
            "review_only": "검토-only",
            "badge": "상태",
        }
    )


def _display_lane_content_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(
        columns={
            "case_id": "case_id",
            "evidence_tier": "근거 강도",
            "ecdf": "ECDF",
            "score": "점수",
            "review_only_count": "검토-only 건수",
            "review_reasons": "검토 사유",
            "sub_detectors": "세부 탐지",
            "coverage_breadth_q95": "q95 진입 영역 수",
            "top_family": "대표 분석 영역",
        }
    )


def _round(value: Any, digits: int = 4) -> float | str:
    if value is None:
        return "-"
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return "-"
