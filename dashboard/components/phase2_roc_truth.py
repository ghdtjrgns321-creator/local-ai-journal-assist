"""VAE ROC 평가용 정답 라벨(is_fraud) 해소 — 전표 단위 Series.

Why: 파이프라인은 `datasynth_label_mode="hidden"` 정책으로 라벨 컬럼을 초입에서 제거한다
     (라벨이 피처로 새어 학습에 쓰이는 것을 막는 정책 — 유지해야 한다). 그래서 DB·세션
     데이터에는 is_fraud 가 없거나 전부 NULL 이고, fraud 데이터셋을 넣어도 ROC 가 "부정
     라벨 없음"으로 떨어졌다(2026-07-25 실측: general_ledger 238,672행 전부 NULL).

     ROC 는 평가 전용 지표이므로, 학습 경로를 건드리지 않고 원본 DataSynth CSV 의 문서
     단위 라벨만 따로 읽어 쓴다. 라벨은 이 함수 밖으로 나가지 않는다(피처·점수에 미참여).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.ingest.datasynth_labels import (
    get_source_path,
    load_document_labels,
    resolve_datasynth_source_hint,
)

_NO_LABEL_MSG = (
    "정답 라벨(is_fraud)이 없어 ROC를 그릴 수 없습니다. 원본 DataSynth CSV 를 찾지 못했습니다 — "
    "라벨은 파이프라인에서 제거되므로(datasynth_label_mode=hidden) 평가에는 원본 파일이 필요합니다."
)


def resolve_roc_truth(pr: Any) -> tuple[pd.Series | None, str]:
    """전표 단위 정답 라벨 Series(index=document_id, value=bool) + 출처 문구.

    해소 순서: ① 파이프라인 데이터에 살아있는 라벨 → ② 원본 CSV 문서 라벨.
    둘 다 실패하면 (None, 사유 문구).
    """
    data = _pipeline_frame(pr)
    inline = _truth_from_frame(data)
    if inline is not None:
        return inline, "정답 라벨 출처: 분석 데이터"

    source = _resolve_source_path(pr, data)
    if source is None:
        return None, _NO_LABEL_MSG

    labels = _load_labels_cached(str(source), _mtime(source))
    if labels is None or labels.empty:
        return None, (
            f"원본 파일({Path(source).name})에서 전표 단위 정답 라벨을 찾지 못해 "
            "ROC를 그릴 수 없습니다."
        )
    truth = _truth_from_frame(labels)
    if truth is None:
        return None, (
            f"원본 파일({Path(source).name})에 is_fraud 라벨이 없어 ROC를 그릴 수 없습니다."
        )
    return truth, f"정답 라벨 출처: {Path(source).name} (평가 전용, 학습·점수에 미사용)"


def _pipeline_frame(pr: Any) -> pd.DataFrame | None:
    data = getattr(pr, "featured_data", None)
    if data is None:
        data = getattr(pr, "data", None)
    return data if isinstance(data, pd.DataFrame) else None


def _truth_from_frame(df: pd.DataFrame | None) -> pd.Series | None:
    """document_id × is_fraud → 전표 단위 bool. 값이 전부 결측이면 라벨 없음으로 본다."""
    if df is None or "document_id" not in df.columns or "is_fraud" not in df.columns:
        return None
    label = df["is_fraud"]
    if isinstance(label, pd.DataFrame):  # 동명 컬럼 중복 방어
        label = label.iloc[:, 0]
    if bool(label.isna().all()):
        # Why: DB general_ledger 는 스키마상 컬럼이 늘 존재한다 — 전부 NULL 이면 "라벨 있음"이
        #      아니라 "라벨이 적재되지 않음"이다. 여기서 걸러야 원본 조회로 넘어간다.
        return None
    truth = label.fillna(False).astype(bool).groupby(df["document_id"].astype(str)).any()
    return truth if len(truth) else None


def _resolve_source_path(pr: Any, data: pd.DataFrame | None) -> Path | None:
    """원본 CSV 경로 후보 — df attrs → PipelineResult.file_name → 세션 ingest 힌트."""
    candidates: list[Any] = []
    if data is not None:
        candidates.append(get_source_path(data))
    candidates.append(getattr(pr, "file_name", None))
    state = st.session_state if hasattr(st, "session_state") else {}
    for key in ("_ingest_source_hint", "_ingest_tmp_path"):
        candidates.append(state.get(key) if hasattr(state, "get") else None)

    for candidate in candidates:
        if not candidate:
            continue
        resolved = resolve_datasynth_source_hint(candidate)
        if resolved.is_file():
            return resolved
    return None


@st.cache_data(show_spinner=False)
def _load_labels_cached(source: str, _mtime_key: float) -> pd.DataFrame | None:
    """원본에서 문서 라벨 추출 — 전체 CSV 스캔이라 경로+mtime 로 캐시한다."""
    try:
        return load_document_labels(source)
    except (OSError, ValueError):
        return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
