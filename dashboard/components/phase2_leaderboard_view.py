from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def build_leaderboard_frame(snapshot: dict[str, Any] | None) -> pd.DataFrame:
    rows = ((snapshot or {}).get("leaderboard_artifact") or {}).get("rows") or []
    return pd.DataFrame(
        [
            {
                "family": row.get("family"),
                "trial": row.get("trial"),
                "preset": row.get("preset"),
                "status": row.get("status"),
                "metric_name": (row.get("metric") or {}).get("name"),
                "metric_value": _format_metric((row.get("metric") or {}).get("value")),
                "elapsed_sec": row.get("elapsed_sec"),
                "schema_hash": _format_nullable(row.get("schema_hash")),
                "metric_interpretation": (row.get("metadata") or {}).get(
                    "metric_interpretation",
                    "-",
                ),
                "gate_reason": row.get("gate_reason") or "-",
            }
            for row in rows
            if isinstance(row, dict)
        ]
    )


def build_promotion_decision_frame(snapshot: dict[str, Any] | None) -> pd.DataFrame:
    decisions = (
        ((snapshot or {}).get("promotion_decision_artifact") or {}).get("family_decisions")
        or {}
    )
    return pd.DataFrame(
        [
            {
                "family": family,
                "eligible_for_promotion": "yes"
                if payload.get("eligible_for_promotion")
                else "no",
                "required_completed_trials": payload.get("required_completed_trials"),
                "family_min_metric": payload.get("family_min_metric"),
                "best_variant": payload.get("best_variant") or "-",
                "reasons": ", ".join(str(reason) for reason in payload.get("reasons") or [])
                or "-",
            }
            for family, payload in sorted(decisions.items())
            if isinstance(payload, dict)
        ]
    )


def render_leaderboard_view(snapshot: dict[str, Any] | None) -> None:
    leaderboard = build_leaderboard_frame(snapshot)
    decisions = build_promotion_decision_frame(snapshot)
    with st.container(border=True):
        st.markdown("**Leaderboard / promotion decision**")
        if leaderboard.empty:
            st.caption("leaderboard.json rows가 없습니다.")
        else:
            st.dataframe(_display_leaderboard_frame(leaderboard), width="stretch", hide_index=True)
        if decisions.empty:
            st.caption("promotion_decision.json 분석 영역 결정 정보가 없습니다.")
        else:
            st.dataframe(_display_decision_frame(decisions), width="stretch", hide_index=True)


def _display_leaderboard_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(
        columns={
            "family": "분석 영역 코드",
            "trial": "trial",
            "preset": "preset",
            "status": "상태",
            "metric_name": "metric",
            "metric_value": "metric 값",
            "elapsed_sec": "소요 시간(초)",
            "schema_hash": "schema hash",
            "metric_interpretation": "metric 해석",
            "gate_reason": "gate 사유",
        }
    )


def _display_decision_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(
        columns={
            "family": "분석 영역 코드",
            "eligible_for_promotion": "승격 가능",
            "required_completed_trials": "필요 trial",
            "family_min_metric": "최소 metric",
            "best_variant": "best variant",
            "reasons": "사유",
        }
    )


def _format_metric(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _format_nullable(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)
