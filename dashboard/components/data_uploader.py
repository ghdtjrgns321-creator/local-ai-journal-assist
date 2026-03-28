"""파일 업로드 + 데이터 미리보기 + Ingest 파이프라인 — 메인 영역 전용.

Why: 파일 업로드 후 데이터 미리보기(Top 10)를 표시하여
     감사인이 컬럼 구조를 파악한 뒤 매핑을 진행할 수 있게 한다.

스테이지 머신:
  UPLOAD   → 파일 업로드 + ingest 분석 + 미리보기
  REVIEW   → 매핑 확인 UI (needs_review=True일 때만)
  PIPELINE → 매핑 적용 + 파이프라인 실행
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_DEV_MODE,
    KEY_EDA_PROFILE,
    KEY_FEATURED_DATA,
    KEY_INGEST_DATA_DF,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_READ_RESULT,
    KEY_INGEST_SELECTED_SHEET,
    KEY_INGEST_SHEET_SCORES,
    KEY_INGEST_SOURCE_COLUMNS,
    KEY_INGEST_STAGE,
    KEY_PIPELINE_RESULT,
    KEY_SETTINGS,
    KEY_UPLOAD_COUNT,
)

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = ["csv", "xlsx", "xls", "xlsb"]


# ── Progress 팩토리 ──────────────────────────────────────


def _make_progress_cb(progress_bar):
    """ETA 계산 포함 progress callback 팩토리."""
    t0 = time.monotonic()

    def _update(pct: float, msg: str) -> None:
        pct = min(pct, 1.0)
        elapsed = time.monotonic() - t0
        if 0.02 < pct < 1.0 and elapsed > 1:
            remaining = elapsed / pct * (1 - pct)
            eta = f"약 {remaining / 60:.0f}분 남음" if remaining >= 60 else f"약 {remaining:.0f}초 남음"
            msg = f"{msg} ({eta})"
        progress_bar.progress(pct, text=msg)

    return _update


# ── 공개 API ──────────────────────────────────────────────


def render_uploader() -> None:
    """메인 영역에 스테이지별 UI 렌더링."""
    stage = st.session_state.get(KEY_INGEST_STAGE, "UPLOAD")

    if stage == "REVIEW":
        _render_review_with_preview()
    elif stage == "PIPELINE":
        _render_pipeline_stage()
    else:
        _render_upload_stage()


# ── UPLOAD 스테이지 ──────────────────────────────────────


def _render_upload_stage() -> None:
    """파일 업로드 위젯 + ingest 분석 + 미리보기."""
    st.title("AI Audit Assistant")
    st.markdown("감사 데이터를 업로드하면 자동으로 컬럼 매핑과 탐지 분석이 진행됩니다.")

    uploaded = st.file_uploader(
        "감사 데이터 업로드", type=_ALLOWED_TYPES,
        help="Excel(.xlsx/.xls/.xlsb) 또는 CSV 파일",
    )

    if uploaded is None:
        st.info("파일을 업로드하면 감사 분석이 시작됩니다.")
        return

    # Why: 파일명+크기 해시로 동일 파일 재업로드 방지
    file_key = f"{uploaded.name}_{uploaded.size}"
    if file_key == st.session_state.get(KEY_UPLOAD_COUNT, ""):
        return

    st.session_state["_ingest_file_key"] = file_key

    try:
        progress_bar = st.progress(0, text="파일 분석 중...")
        _run_ingest(uploaded, _make_progress_cb(progress_bar))
        progress_bar.empty()
        st.rerun()

    except Exception as e:
        logger.exception("인제스트 분석 실패")
        st.error(f"인제스트 분석 실패: {e}")
        if st.session_state.get(KEY_DEV_MODE):
            st.exception(e)


# ── REVIEW 스테이지 (미리보기 포함) ──────────────────────


def _render_review_with_preview() -> None:
    """왼쪽: 컬럼 매핑 확인 / 오른쪽: 데이터 미리보기(Top 10)."""
    data_df = st.session_state.get(KEY_INGEST_DATA_DF)
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])

    st.title("데이터 미리보기 & 컬럼 매핑")

    col_left, col_right = st.columns([1, 1])

    # ── 왼쪽: 매핑 리뷰 ──
    with col_left:
        from dashboard.components.mapping_review import render_mapping_review
        render_mapping_review()

    # ── 오른쪽: 미리보기 테이블 ──
    with col_right:
        if data_df is not None and len(source_columns) > 0:
            import pandas as pd
            n_preview = min(10, len(data_df))
            preview = data_df.head(n_preview).copy()
            preview.columns = source_columns[:preview.shape[1]]

            st.subheader(f"원본 데이터 (상위 {n_preview}행)")
            st.dataframe(
                preview,
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"전체 {len(data_df):,}행 × {len(source_columns)}열")
        else:
            st.info("미리보기 데이터가 없습니다.")


# ── PIPELINE 스테이지 ────────────────────────────────────


def _render_pipeline_stage() -> None:
    """매핑 적용 → 파이프라인 실행 → 결과 저장."""
    mapping_result = st.session_state.get(KEY_INGEST_MAPPING_RESULT)
    data_df = st.session_state.get(KEY_INGEST_DATA_DF)
    if mapping_result is None or data_df is None:
        st.warning("세션이 만료되었습니다. 파일을 다시 업로드해 주세요.")
        _clear_ingest_state()
        st.rerun()
        return

    file_key = st.session_state.get("_ingest_file_key", "")

    try:
        progress_bar = st.progress(0, text="파이프라인 시작...")
        result, warns = _run_pipeline_from_mapped(file_key, _make_progress_cb(progress_bar))
        progress_bar.empty()

        # 파이프라인 완료 → 결과 탭 화면으로 전환
        st.rerun()

    except Exception as e:
        logger.exception("파이프라인 실행 실패")
        st.error(f"파이프라인 실행 실패: {e}")
        if st.session_state.get(KEY_DEV_MODE):
            st.exception(e)
        _clear_ingest_state()


# ── Ingest 로직 ──────────────────────────────────────────


def _run_ingest(uploaded, progress_cb) -> None:
    """파일 → read_file → header detect → column map → 스테이지 결정."""
    from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
    from src.ingest.header_detector import detect_headers
    from src.ingest.mapping_profile import load_profile
    from src.ingest.sheet_scorer import score_sheets

    progress_cb(0.05, "파일 읽는 중...")
    read_result = _read_via_ingest(uploaded)

    if read_result.source_format == "parquet":
        sheet_name = read_result.active_sheet
        data_df = read_result.raw_data[sheet_name]
        source_columns = list(data_df.columns)
        matched_keywords: list[str] = []
        sheet_scores = []
    else:
        progress_cb(0.10, "헤더 탐지 중...")
        header_results = detect_headers(read_result)
        sheet_scores = score_sheets(read_result, header_results)

        recommended = next((s for s in sheet_scores if s.recommended), None)
        sheet_name = recommended.sheet_name if recommended else read_result.active_sheet

        header_result = header_results[sheet_name]
        raw_df = read_result.raw_data[sheet_name]

        if header_result.header_row is not None:
            source_columns, data_df = prepare_dataframe(raw_df, header_result.header_row)
            matched_keywords = header_result.matched_keywords
        else:
            source_columns = [str(c) for c in raw_df.columns]
            data_df = raw_df
            matched_keywords = []

    progress_cb(0.15, "컬럼 매핑 중...")

    profile = load_profile(source_columns)
    if profile is not None and not profile.needs_review:
        mapping_result = profile
    else:
        mapping_result = auto_map_columns(
            source_columns, matched_keywords, data_df=data_df,
        )

    st.session_state[KEY_INGEST_READ_RESULT] = read_result
    st.session_state[KEY_INGEST_SHEET_SCORES] = sheet_scores
    st.session_state[KEY_INGEST_SELECTED_SHEET] = sheet_name
    st.session_state[KEY_INGEST_SOURCE_COLUMNS] = source_columns
    st.session_state[KEY_INGEST_DATA_DF] = data_df
    st.session_state[KEY_INGEST_MAPPING_RESULT] = mapping_result

    if not mapping_result.needs_review and not mapping_result.missing_required:
        st.session_state[KEY_INGEST_STAGE] = "PIPELINE"
    else:
        st.session_state[KEY_INGEST_STAGE] = "REVIEW"


def _read_via_ingest(uploaded):
    """UploadedFile → ReadResult. tempfile 경유로 검증 + 읽기."""
    from src.ingest.file_validator import validate_file
    from src.ingest.reader_api import read_file

    suffix = Path(uploaded.name).suffix
    uploaded.seek(0)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(uploaded.read())
        tmp_path = Path(f.name)
    try:
        validation = validate_file(tmp_path)
        if not validation.is_valid:
            raise ValueError("; ".join(validation.errors))
        return read_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _run_pipeline_from_mapped(file_key: str, progress_cb):
    """확정 매핑 적용 → cast → AuditPipeline 실행 → 결과 저장."""
    from src.ingest.mapping_profile import save_profile
    from src.ingest.type_caster import cast_dataframe
    from src.pipeline import AuditPipeline

    mapping_result = st.session_state[KEY_INGEST_MAPPING_RESULT]
    data_df = st.session_state[KEY_INGEST_DATA_DF]
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    read_result = st.session_state.get(KEY_INGEST_READ_RESULT)

    df = data_df.rename(columns=mapping_result.mapping)

    progress_cb(0.20, "타입 캐스팅 중...")
    cast_result = cast_dataframe(df)
    df = cast_result.data
    warns = list(cast_result.warnings)
    if cast_result.errors:
        warns.extend(cast_result.errors)

    progress_cb(0.25, "파이프라인 시작...")
    settings = st.session_state.get(KEY_SETTINGS)
    result = AuditPipeline(
        settings=settings, progress_callback=progress_cb,
    ).run_from_dataframe(df)

    result.warnings = warns + result.warnings

    if source_columns:
        try:
            selected_sheet = st.session_state.get(KEY_INGEST_SELECTED_SHEET, "")
            header_results = {}
            if read_result and read_result.source_format != "parquet":
                from src.ingest.header_detector import detect_headers
                header_results = detect_headers(read_result)
            header_row = 0
            hr = header_results.get(selected_sheet)
            if hr and hr.header_row is not None:
                header_row = hr.header_row

            save_profile(
                mapping_result, source_columns,
                source_name=file_key.rsplit("_", 1)[0],
                source_format=read_result.source_format if read_result else "",
                header_row=header_row,
            )
        except Exception:
            logger.warning("프로파일 저장 실패", exc_info=True)

    st.session_state[KEY_PIPELINE_RESULT] = result
    st.session_state[KEY_BATCH_ID] = result.batch_id
    st.session_state[KEY_UPLOAD_COUNT] = file_key
    st.session_state.pop(KEY_EDA_PROFILE, None)
    st.session_state[KEY_FEATURED_DATA] = result.featured_data

    _clear_ingest_state()

    return result, warns


# ── 헬퍼 ────────────────────────────────────────────────


def _clear_ingest_state() -> None:
    """인제스트 중간 상태 정리."""
    for key in [
        KEY_INGEST_READ_RESULT, KEY_INGEST_MAPPING_RESULT,
        KEY_INGEST_SHEET_SCORES, KEY_INGEST_SELECTED_SHEET,
        KEY_INGEST_SOURCE_COLUMNS, KEY_INGEST_DATA_DF,
        "_ingest_file_key",
    ]:
        st.session_state.pop(key, None)
    st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
