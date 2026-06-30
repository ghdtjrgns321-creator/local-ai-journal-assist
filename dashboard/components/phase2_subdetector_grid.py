from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

SUB_DETECTORS = (
    ("timeseries", "TS01", "transaction_burst"),
    ("timeseries", "TS02", "unusual_frequency"),
    ("relational", "R01", "new_counterparty"),
    ("relational", "R02", "dormant_account_activity"),
    ("relational", "R03", "transfer_pricing_anomaly"),
    ("relational", "R04", "missing_relationship"),
    ("relational", "R05", "rare_account_partner_edge"),
    ("relational", "R06", "user_account_degree_spike"),
    ("relational", "R07", "dormant_partner_reactivation"),
    ("intercompany", "IC01", "unmatched_intercompany"),
    ("intercompany", "IC02", "amount_mismatch"),
    ("intercompany", "IC03", "timing_gap"),
    ("intercompany", "ic_reciprocal_flow_prob", "reciprocal_flow"),
    ("intercompany", "ic_amount_prob", "amount_mismatch_probability"),
    ("intercompany", "ic_unmatched_prob", "unmatched_probability"),
    ("intercompany", "ic_timing_prob", "timing_gap_probability"),
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
    if family != "intercompany":
        return "-"
    if code in set(ui_meta.get("active_sub_detectors") or []):
        return "active sidecar unmatched-reference"
    if code in {"IC02", "IC03"}:
        return "carry-over (matched-pair data 미보유)"
    return "-"
