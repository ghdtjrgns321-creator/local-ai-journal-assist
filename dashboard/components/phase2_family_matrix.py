from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

ACTIVE_FAMILIES = (
    "unsupervised",
    "timeseries",
    "relational",
    "intercompany",
)
DORMANT_FAMILIES = ("supervised", "transformer", "sequence", "stacking")
FAMILY_METRICS = {
    "unsupervised": "ECDF high q95 count",
    "timeseries": "burst_detection_rate",
    "relational": "new_counterparty_precision",
    "intercompany": "ic_match_completeness",
    "supervised": "f1_macro",
    "transformer": "f1_macro",
    "sequence": "f1_macro",
    "stacking": "f1_macro",
}
FAMILY_INTERPRETATIONS = {
    "unsupervised": "ECDF q95 tail review count, rule_proxy_score label only",
    "timeseries": "rule_proxy_score",
    "relational": "rule_proxy_score",
    "intercompany": "rule_proxy_score",
    "supervised": "dormant label-gated metric",
    "transformer": "dormant label-gated metric",
    "sequence": "dormant D047-gated metric",
    "stacking": "dormant base-output metric",
}
DORMANT_REASONS = {
    "supervised": "low_signal_fallback",
    "transformer": "low_signal_fallback",
    "sequence": "d047_gated",
    "stacking": "base_family_outputs_required",
}

_STATE_LABELS = {"active": "활성", "dormant": "대기"}
_INTERPRETATION_LABELS = {
    "ECDF q95 tail review count, rule_proxy_score label only": "ECDF 꼬리 검토 후보",
    "rule_proxy_score": "룰 기반 근사 점수",
    "dormant label-gated metric": "라벨 확보 후 활성화",
    "dormant D047-gated metric": "전표 순서 데이터 확보 후 활성화",
    "dormant base-output metric": "기본 분석 영역 출력 누적 후 활성화",
}
_BLOCK_REASON_LABELS = {
    "low_signal_fallback": "학습 신호 부족",
    "d047_gated": "전표 순서 데이터 필요",
    "base_family_outputs_required": "기본 분석 영역 출력 누적 필요",
}


def build_family_matrix_frame(
    snapshot: dict[str, Any] | None,
    partition_summary: dict[str, Any] | None,
) -> pd.DataFrame:
    contract = (snapshot or {}).get("inference_contract") or {}
    model_versions = contract.get("model_versions") or {}
    families_payload = (partition_summary or {}).get("families") or {}
    rows: list[dict[str, Any]] = []
    for family in (*ACTIVE_FAMILIES, *DORMANT_FAMILIES):
        family_payload = families_payload.get(family) or {}
        ui_meta = family_payload.get("ui_meta") or {}
        version_payload = model_versions.get(family) or {}
        rows.append(
            {
                "family": family,
                "state": "active" if family in ACTIVE_FAMILIES else "dormant",
                "metric": FAMILY_METRICS[family],
                "metric_value": _family_metric_value(family, family_payload),
                "metric_interpretation": family_payload.get("metric_interpretation")
                or FAMILY_INTERPRETATIONS[family],
                "rows_scored": _format_int(family_payload.get("rows_scored")),
                "model_version": _format_nullable(version_payload.get("model_version")),
                "schema_hash": _format_nullable(version_payload.get("schema_hash")),
                "block_reason": "" if family in ACTIVE_FAMILIES else DORMANT_REASONS[family],
                "metric_confidence": str(ui_meta.get("metric_confidence") or "-"),
                "note": _family_note(family, ui_meta),
            }
        )
    return pd.DataFrame(rows)


def render_family_matrix(
    snapshot: dict[str, Any] | None,
    partition_summary: dict[str, Any] | None,
) -> None:
    frame = build_family_matrix_frame(snapshot, partition_summary)
    if not frame.empty:
        frame = frame.copy()
        frame["state"] = frame["state"].map(_STATE_LABELS).fillna(frame["state"])
        frame["metric_interpretation"] = (
            frame["metric_interpretation"]
            .map(_INTERPRETATION_LABELS)
            .fillna(frame["metric_interpretation"])
        )
        frame["block_reason"] = (
            frame["block_reason"].map(_BLOCK_REASON_LABELS).fillna(frame["block_reason"])
        )
    display_frame = frame.rename(
        columns={
            "family": "분석 영역 코드",
            "state": "상태",
            "metric": "기준 metric",
            "metric_value": "metric 값",
            "metric_interpretation": "metric 해석",
            "rows_scored": "점수 산출 행",
            "model_version": "모델 버전",
            "schema_hash": "schema hash",
            "block_reason": "보류 사유",
            "metric_confidence": "metric 신뢰도",
            "note": "비고",
        }
    )
    with st.container(border=True):
        st.markdown("**PHASE2 분석 영역 매트릭스**")
        st.dataframe(display_frame, width="stretch", hide_index=True)


def _family_metric_value(family: str, payload: dict[str, Any]) -> str:
    if family == "unsupervised":
        return _format_int(payload.get("high_count_q95"))
    distribution = payload.get("score_distribution") or {}
    value = distribution.get("nonzero_count")
    return _format_int(value)


def _family_note(family: str, ui_meta: dict[str, Any]) -> str:
    if family == "intercompany" and ui_meta.get("active_sub_detectors") == ["IC01"]:
        return "active, IC01 only"
    return "-"


def _format_int(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _format_nullable(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)
