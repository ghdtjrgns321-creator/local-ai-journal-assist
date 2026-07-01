from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

SUB_DETECTORS = (
    ("timeseries", "TS01", "transaction_burst"),
    ("timeseries", "TS02", "unusual_frequency"),
)


def build_subdetector_grid_frame(partition_summary: dict[str, Any] | None) -> pd.DataFrame:
    families_payload = (partition_summary or {}).get("families") or {}
    rows: list[dict[str, Any]] = []
    for family, code, label in SUB_DETECTORS:
        family_payload = families_payload.get(family) or {}
        sub_payload = (family_payload.get("sub_detectors") or {}).get(code) or {}
        rows.append(
            {
                "family": family,
                "sub_detector": code,
                "label": str(sub_payload.get("label") or label),
                "hit_count": int(sub_payload.get("hit_count") or 0),
                "meta": _subdetector_meta(family, code, family_payload.get("ui_meta") or {}),
            }
        )
    return pd.DataFrame(rows)


def render_subdetector_grid(partition_summary: dict[str, Any] | None) -> None:
    frame = build_subdetector_grid_frame(partition_summary)
    display_frame = frame.rename(
        columns={
            "family": "분석 영역 코드",
            "sub_detector": "세부 탐지 코드",
            "label": "탐지 내용",
            "hit_count": "적중 건수",
            "meta": "비고",
        }
    )
    with st.container(border=True):
        st.markdown("**세부 탐지 적중 현황**")
        st.dataframe(display_frame, width="stretch", hide_index=True)


def _subdetector_meta(family: str, code: str, ui_meta: dict[str, Any]) -> str:
    return "-"
