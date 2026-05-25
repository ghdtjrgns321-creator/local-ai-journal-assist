"""3큐 분리 review queue 뷰어 컴포넌트.

PHASE1 단독 / PHASE2 단독 / 통합 큐 parquet 을 읽어 KPI + 표를 렌더한다.
정렬 알고리즘명은 UI 본문에 노출하지 않고 감사인 검토 언어만 표시한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.services.review_band_policy import (
    RANK_BAND_LABELS,
    rank_band_caption,
    rank_percentile_band,
)

QUEUE_FILENAME_BY_KIND: dict[str, str] = {
    "integrated": "queue_integrated.parquet",
    "phase1": "queue_phase1.parquet",
    "phase2": "queue_phase2.parquet",
}

COLUMNS_BY_KIND: dict[str, list[str]] = {
    "integrated": [
        "rrf_rank",
        "phase12_review_band",
        "phase1_review_band",
        "phase2_review_band",
        "primary_topic",
        "primary_theme",
        "total_amount",
        "document_count",
    ],
    "phase1": [
        "review_rank",
        "phase1_review_band",
        "primary_topic",
        "primary_theme",
        "phase1_priority_score",
        "total_amount",
        "document_count",
        "rule_count",
    ],
    "phase2": [
        "phase2_review_rank",
        "phase2_review_band",
        "primary_topic",
        "primary_theme",
        "total_amount",
        "document_count",
    ],
}

KPI_TOOLTIP_BY_KIND: dict[str, str] = {
    "integrated": "PHASE1 룰 신호와 PHASE2 분석 영역 신호를 함께 반영한 통합 검토 큐.",
    "phase1": "PHASE1 룰 기반 우선순위만 사용한 검토 큐.",
    "phase2": "PHASE2 분석 영역 신호만 사용한 검토 큐. PHASE1 룰 우선순위와 분리됩니다.",
}

BAND_LABELS: dict[str, str] = {
    **RANK_BAND_LABELS,
    # Stage7 cache stale 대비 backward compatibility:
    # phase1 priority_band raw 값이 직접 들어와도 사용자 언어로 표시한다.
    "high": "즉시검토",
    "medium": "검토대상",
    "low": "참고후보",
}

DISPLAY_RENAME_BY_KIND: dict[str, dict[str, str]] = {
    "integrated": {
        "rrf_rank": "순위",
        "phase12_review_band": "통합 등급",
        "phase1_review_band": "PHASE1 등급",
        "phase2_review_band": "PHASE2 등급",
        "primary_topic": "주요 관점",
        "primary_theme": "세부 관점",
        "total_amount": "합계 금액",
        "document_count": "전표 수",
    },
    "phase1": {
        "review_rank": "순위",
        "phase1_review_band": "PHASE1 등급",
        "primary_topic": "주요 관점",
        "primary_theme": "세부 관점",
        "phase1_priority_score": "PHASE1 점수",
        "total_amount": "합계 금액",
        "document_count": "전표 수",
        "rule_count": "룰 수",
    },
    "phase2": {
        "phase2_review_rank": "순위",
        "phase2_review_band": "PHASE2 등급",
        "primary_topic": "주요 관점",
        "primary_theme": "세부 관점",
        "total_amount": "합계 금액",
        "document_count": "전표 수",
    },
}


def load_queue(queue_dir: Path, kind: str) -> pd.DataFrame | None:
    """큐 parquet 로드. 파일 없으면 None."""
    path = queue_dir / QUEUE_FILENAME_BY_KIND[kind]
    if not path.exists():
        return None
    return pd.read_parquet(path)


def load_integration_report(report_path: Path | None) -> dict[str, Any] | None:
    """integration report JSON 로드. truth 라벨 있는 합성 데이터에서만 메인 KPI 표시 근거."""
    if report_path is None or not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _doc_recall_entry(
    report: dict[str, Any] | None,
    kind: str,
    top_n: int,
) -> dict[str, Any] | None:
    if not report:
        return None
    by_queue = report.get("informational_truth_signal", {}).get("doc_recall_by_queue", {})
    entries = by_queue.get(kind, [])
    return next((e for e in entries if int(e.get("top_n", -1)) == top_n), None)


def render_kpi(
    df: pd.DataFrame,
    *,
    kind: str,
    integration_report: dict[str, Any] | None,
    top_n_for_kpi: int = 500,
) -> None:
    """KPI 영역. 메인=truth doc recall(합성에서만), 보조=case 단위 정보."""
    tooltip = KPI_TOOLTIP_BY_KIND.get(kind, "")
    entry = _doc_recall_entry(integration_report, kind, top_n_for_kpi)
    if entry and int(entry.get("total_truth_docs", 0)) > 0:
        matched = int(entry["matched_truth_docs"])
        total = int(entry["total_truth_docs"])
        recall_pct = float(entry["recall"]) * 100.0
        st.markdown(
            f"#### 검증 라벨 매칭 전표 **{matched:,}건** / 기준 전체 {total:,}건 "
            f"(회수율 **{recall_pct:.1f}%**)",
            help=f"{tooltip} TOP {top_n_for_kpi:,} 검토 케이스 기준 개발 검증 지표입니다.",
        )
    case_count = len(df)
    avg_docs = (
        float(df["document_count"].astype(float).mean())
        if (not df.empty and "document_count" in df.columns)
        else 0.0
    )
    st.caption(f"검토 case {case_count:,}건 (case당 평균 {avg_docs:.2f} 전표)")


def _format_df_for_display(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    df = _with_rank_percentile_bands(df, kind)
    columns = COLUMNS_BY_KIND[kind]
    available = [c for c in columns if c in df.columns]
    frame = df[available].copy()
    for col in ("phase12_review_band", "phase1_review_band", "phase2_review_band"):
        if col in frame.columns:
            frame[col] = frame[col].map(lambda value: BAND_LABELS.get(str(value), str(value)))
    return frame.rename(columns=DISPLAY_RENAME_BY_KIND.get(kind, {}))


def _with_rank_percentile_bands(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Apply top-percentile review bands for user-facing queue display."""

    frame = df.copy()
    total_cases = len(frame)
    if total_cases <= 0:
        return frame
    if kind == "phase2" and "phase2_review_rank" in frame.columns:
        frame["phase2_review_band"] = [
            rank_percentile_band(rank, total_cases) for rank in frame["phase2_review_rank"]
        ]
    if kind == "integrated":
        rank_col = "rrf_rank" if "rrf_rank" in frame.columns else "review_rank"
        if rank_col in frame.columns:
            frame["phase12_review_band"] = [
                rank_percentile_band(rank, total_cases) for rank in frame[rank_col]
            ]
        phase2_rank_col = (
            "rank_phase2_internal_noisy_or"
            if "rank_phase2_internal_noisy_or" in frame.columns
            else "rank_phase2"
            if "rank_phase2" in frame.columns
            else None
        )
        if phase2_rank_col is not None:
            frame["phase2_review_band"] = [
                rank_percentile_band(rank, total_cases) for rank in frame[phase2_rank_col]
            ]
    return frame


def render_queue_browser(
    source: pd.DataFrame | Path | None,
    *,
    kind: str,
    integration_report: dict[str, Any] | None,
    head_n: int = 500,
) -> None:
    """탭 1개 분량의 뷰어 — KPI + 표(상위 head_n).

    Args:
        source: 우선순위 — DataFrame (in-memory, 사용자 batch 결과) > Path (queue parquet 디렉토리).
            None 이면 안내. 정적 baseline fallback 폐기 — 사용자 데이터만 표시한다.
    """
    if source is None:
        st.info("Phase 2 추론 결과가 없습니다. Phase 1 → Phase 2 분석을 먼저 실행하세요.")
        return
    if isinstance(source, pd.DataFrame):
        df = source
        if df.empty:
            st.info("Phase 2 추론 결과가 비어 있습니다. Phase 2 추론을 먼저 실행하세요.")
            return
    else:
        df = load_queue(source, kind)
        if df is None:
            st.warning(
                f"큐 파일 `{QUEUE_FILENAME_BY_KIND[kind]}` 가 없습니다. "
                "Phase 2 추론을 먼저 실행하세요."
            )
            return
    render_kpi(df, kind=kind, integration_report=integration_report)
    if kind in {"phase2", "integrated"}:
        st.caption(rank_band_caption(len(df)))
    display_df = _format_df_for_display(df.head(head_n), kind)
    st.dataframe(display_df, width="stretch", hide_index=True)
