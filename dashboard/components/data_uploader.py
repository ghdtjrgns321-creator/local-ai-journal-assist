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
from pathlib import Path

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_DEV_MODE,
    KEY_EDA_PROFILE,
    KEY_FEATURED_DATA,
    KEY_INGEST_COLUMN_DIFF,
    KEY_INGEST_CONFIRMED,
    KEY_INGEST_DATA_DF,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_PREP_WARNINGS,
    KEY_INGEST_PREPARED_DF,
    KEY_INGEST_READ_RESULT,
    KEY_INGEST_SELECTED_SHEET,
    KEY_INGEST_SHEET_SCORES,
    KEY_INGEST_SOURCE_COLUMNS,
    KEY_INGEST_STAGE,
    KEY_PIPELINE_RESULT,
    KEY_SETTINGS,
    KEY_UPLOAD_COUNT,
)
from src.services.analysis_service import build_audit_trail

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = ["csv", "xlsx", "xls", "xlsb", "tsv", "txt", "dat", "parquet"]


# ── Progress 팩토리 ──────────────────────────────────────


def _make_progress_cb(progress_bar):
    """progress callback 팩토리. 퍼센트 + 단계 메시지만 표시."""

    def _update(pct: float, msg: str) -> None:
        pct = min(pct, 1.0)
        progress_bar.progress(pct, text=msg)

    return _update


def _open_native_file_dialog() -> str | None:
    """OS 네이티브 파일 다이얼로그를 띄워 절대 경로를 반환.

    Why: 브라우저 file_uploader는 보안상 실제 경로를 노출하지 않고 임시 폴더에
         바이트를 복사하므로 대용량 파일에서 HTTP 전송 지연이 크다. 이 도구는
         로컬 단일 사용자 전용이므로 tkinter 다이얼로그로 절대 경로를 받아
         디스크에서 바로 읽는다.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    # 다이얼로그가 다른 창 뒤로 숨지 않도록 강제 전면
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    try:
        path = filedialog.askopenfilename(
            title="감사 데이터 파일 선택",
            filetypes=[
                ("All supported", "*.csv *.xlsx *.xls *.xlsb *.tsv *.txt *.dat *.parquet"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx *.xls *.xlsb"),
                ("Parquet", "*.parquet"),
                ("All files", "*.*"),
            ],
        )
    finally:
        root.destroy()
    return path or None


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
    """Browse files 버튼 → 네이티브 다이얼로그 → ingest 분석 → 미리보기."""
    st.title("AI Audit Assistant")
    st.markdown("감사 데이터를 선택하면 자동으로 컬럼 매핑과 탐지 분석이 진행됩니다.")

    st.caption(
        f"지원 형식: {', '.join(_ALLOWED_TYPES).upper()} · "
        "로컬 파일을 직접 읽어 업로드 지연이 없습니다."
    )

    if not st.button("📂 Browse files", type="primary"):
        st.info("**Browse files** 버튼을 눌러 분석할 파일을 선택하세요.")
        return

    picked = _open_native_file_dialog()
    if not picked:
        st.info("파일 선택이 취소되었습니다.")
        return

    local_path = Path(picked)
    if not local_path.exists():
        st.error(f"파일을 찾을 수 없습니다: {local_path}")
        return
    ext = local_path.suffix.lower()
    if ext.lstrip(".") not in _ALLOWED_TYPES:
        st.error(f"지원하지 않는 형식: {ext}")
        return

    file_key = f"{local_path.name}_{local_path.stat().st_size}"
    if file_key == st.session_state.get(KEY_UPLOAD_COUNT, ""):
        return

    st.session_state["_ingest_file_key"] = file_key
    st.session_state["_ingest_source_hint"] = str(local_path)

    try:
        progress_bar = st.progress(0, text="파일 분석 중...")
        _run_ingest_from_path(local_path, _make_progress_cb(progress_bar))
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
    from dashboard.components.scroll_anchor import preserve_scroll_position

    # Why: "매핑 확인" 버튼 등으로 st.rerun()이 발생하면 페이지가 맨 위로 튕긴다.
    #      페이지별 키로 scrollY를 sessionStorage에 영구 보존하여 위치를 복원.
    preserve_scroll_position("mapping_review")

    data_df = st.session_state.get(KEY_INGEST_DATA_DF)
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    read_result = st.session_state.get(KEY_INGEST_READ_RESULT)

    st.title("데이터 미리보기 & 컬럼 매핑")

    # ── 상단: 작년 컬럼매핑과 비교 ──
    _render_column_diff_section()

    # ── 데이터 품질 경고 + 자동 복구 버튼 ──
    _render_data_warnings(read_result, data_df, source_columns)

    # ── 좌우 분할: 왼쪽 매핑 에디터 / 오른쪽 sticky 미리보기 ──
    # Why: 단일 컬럼 내 position:sticky는 Streamlit DOM 구조상 안정적이지 않다.
    #      column 레이아웃에서는 우측 컬럼 내부의 element가 확실히 sticky로 작동.
    col_map, col_preview = st.columns([4, 6], gap="large")

    with col_preview:
        if data_df is not None and len(source_columns) > 0:
            n_preview = min(5, len(data_df))
            preview = data_df.head(n_preview).copy()
            preview.columns = source_columns[: preview.shape[1]]

            # Why: 매핑 selectbox에서 자동 숨김되는 컬럼은 미리보기에도 노이즈일 뿐
            #      이므로 동일 기준(AUTO_HIDDEN_SOURCE_COLUMNS)으로 가린다.
            #      포함 범위: (a) DataSynth 합성 라벨/sidecar, (b) clearing·suspense
            #      lifecycle 메타(amount_open/is_cleared/settlement_status 등),
            #      (c) 파이프라인 derived feature, (d) 분석/DB metadata.
            # 늦은 import: mapping_review→data_uploader 순환을 회피.
            from dashboard.components.mapping_review import AUTO_HIDDEN_SOURCE_COLUMNS

            visible_cols = [
                col
                for col in preview.columns
                if str(col).strip().lower() not in AUTO_HIDDEN_SOURCE_COLUMNS
                and not str(col).startswith("_")
            ]
            hidden_count = preview.shape[1] - len(visible_cols)
            preview = preview[visible_cols]

            # marker는 sticky 타겟 식별용 (CSS :has에서 사용)
            st.markdown(
                '<div class="sticky-preview-marker"></div>',
                unsafe_allow_html=True,
            )
            st.subheader(f"원본 데이터 (상위 {n_preview}행)")
            st.dataframe(
                preview,
                use_container_width=True,
                hide_index=True,
                height=min(240, (n_preview + 1) * 38),
            )
            caption = f"{len(data_df):,}행 × {len(visible_cols)}열"
            if hidden_count:
                caption += f" (시스템 컬럼 {hidden_count}열 숨김)"
            st.caption(caption)
        else:
            st.info("미리보기 데이터가 없습니다.")

    with col_map:
        from dashboard.components.mapping_review import render_mapping_review

        render_mapping_review()

    # ── 풀 폭 푸터: 매핑 요약 + 확인/취소 + 준비 단계 progress ──
    st.divider()
    from dashboard.components.mapping_review import render_mapping_footer

    render_mapping_footer()


def _render_column_diff_section() -> None:
    """작년 컬럼매핑 프로파일과의 컬럼 변경 요약을 렌더링한다.

    세 가지 상태를 구분한다:
      1) 이전 프로파일 없음 → "첫 업로드" 안내
      2) 프로파일 있음 + 컬럼 동일 → "변경 없음" 안내
      3) 프로파일 있음 + 변경 발생 → 추가/삭제/이름변경 상세
    """
    diff = st.session_state.get(KEY_INGEST_COLUMN_DIFF)
    current_fy = st.session_state.get("_ingest_current_fy")
    prior_fy = st.session_state.get("_ingest_prior_fy")

    st.subheader("작년 컬럼매핑과 비교")

    if diff is None:
        if current_fy is None:
            st.info("회사/감사연도(Engagement)가 선택되지 않아 작년 비교를 생략했습니다.")
        elif prior_fy is not None:
            # Why: profile_dir 가 회사별 격리이므로 "분석 이력 없음" 의 실제 원인은
            #      다른 회사에서 FY{prior_fy} 를 분석했거나, 같은 회사에서도 아직
            #      FY{prior_fy} 를 분석하지 않은 두 가지. 회사명을 같이 노출.
            company_id = st.session_state.get("audit_company_id") or "(선택 없음)"
            st.info(
                f"회사 **{company_id}** 의 작년(FY {prior_fy}) 분석 이력이 없습니다. "
                f"같은 회사에서 FY {prior_fy} 데이터를 먼저 분석해야 다음 연도부터 컬럼 구성 "
                "변화(추가/삭제/이름변경)를 자동으로 비교해 표시합니다. "
                "(다른 회사의 FY 프로파일은 회사 격리로 비교 대상이 아닙니다.)"
            )
        else:
            st.info("작년 분석 이력이 없습니다.")
        return

    total = len(diff.added) + len(diff.removed) + len(diff.renamed)
    prev_label = diff.prev_source_name or f"FY {prior_fy} 업로드"

    if total == 0:
        st.success(f"작년(FY {prior_fy}) 컬럼매핑과 구성이 동일합니다. (비교 기준: {prev_label})")
        return

    # 변경 요약 KPI
    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric("추가", len(diff.added))
    with k2:
        st.metric("삭제", len(diff.removed))
    with k3:
        st.metric("이름 변경", len(diff.renamed))

    st.caption(f"비교 기준: {prev_label}")

    # 상세: 각 카테고리 expander
    if diff.renamed:
        with st.expander(f"이름 변경 {len(diff.renamed)}건", expanded=True):
            for old, new, sim in diff.renamed:
                st.markdown(f"- `{old}` → `{new}`  (유사도 {sim:.0f}%)")
            st.caption(
                "ERP 접미사/약어 변경으로 추정되는 컬럼입니다. "
                "매핑이 이전과 동일한지 왼쪽 패널에서 확인해 주세요."
            )

    if diff.added:
        with st.expander(f"추가된 컬럼 {len(diff.added)}건", expanded=False):
            for col in diff.added:
                st.markdown(f"- `{col}`")
            st.caption("이전에 없던 새 컬럼입니다. 표준 컬럼으로 매핑 가능한지 검토하세요.")

    if diff.removed:
        with st.expander(f"사라진 컬럼 {len(diff.removed)}건", expanded=False):
            for col in diff.removed:
                st.markdown(f"- `{col}`")
            st.caption(
                "이전 업로드에 있었지만 이번엔 제공되지 않은 컬럼입니다. "
                "관련 감사 검사가 누락될 수 있습니다."
            )


def _detect_column_mismatch(read_result) -> str | None:
    """헤더 이후 데이터 행만 대상으로 열 수 불일치를 재계산한다.

    Why: raw_df 전체를 진단하면 메타데이터 행이 오탐으로 잡힌다.
    헤더 이후 행만 검사. 대용량(10만행+)은 상위 1000행 샘플 사용.
    인크리멘탈 진단에서 이미 전체 검사했으므로 여기서는 UI 보충용.
    """

    if read_result is None:
        return None
    sheet = read_result.active_sheet
    raw_df = read_result.raw_data.get(sheet)
    if raw_df is None or raw_df.shape[0] <= 1:
        return None

    from src.ingest.header_detector import detect_headers

    header_results = detect_headers(read_result)
    hr = header_results.get(sheet)
    header_row = hr.header_row if hr and hr.header_row is not None else 0

    data_slice = raw_df.iloc[header_row + 1 :].reset_index(drop=True)
    if data_slice.shape[0] <= 1:
        return None

    header_cols = int(raw_df.iloc[header_row].notna().sum())

    if data_slice.shape[1] <= header_cols:
        return None

    # Why: 1.1M행에서 .notna().sum(axis=1)은 33초 소요.
    # 상위 1000행 샘플로 충분 (인크리멘탈 진단이 전체 커버)
    sample = data_slice.head(1000)

    non_null_counts = sample.notna().sum(axis=1)
    non_empty = non_null_counts[non_null_counts > 0]
    if len(non_empty) <= 1:
        return None

    mode_cols = int(non_empty.mode().iloc[0])
    short_mask = non_empty < mode_cols
    long_mask = non_empty > mode_cols
    if not short_mask.any() and not long_mask.any():
        return None

    lines = [f"열 수 불일치 (기준 {mode_cols}열) — 원본 파일 확인 필요"]
    problem_idxs = non_null_counts.index[short_mask | long_mask]
    for row_idx in problem_idxs:
        cnt = int(non_null_counts.loc[row_idx])
        row_id = sample.iloc[row_idx, 0]
        if cnt < mode_cols:
            missing = mode_cols - cnt
            lines.append(f"  행 {row_idx + 1} ({row_id}): {cnt}열만 존재 → {missing}열 누락(NaN)")
        elif cnt > mode_cols:
            extra_vals = [str(v) for v in sample.iloc[row_idx, mode_cols:].dropna()]
            lines.append(
                f"  행 {row_idx + 1} ({row_id}): {cnt}열 → 초과 값 [{', '.join(extra_vals)}] 버려짐"
            )
    return "\n".join(lines)


def _detect_scientific_notation(data_df, source_columns: list[str]) -> str | None:
    """지수 표기법(Excel 손상) 셀을 감지한다.

    Why: Excel에서 CSV를 열었다 저장하면 긴 숫자가 "2E+11",
    큰 금액이 "1.5E+07" 등으로 변환된다.
    대용량 파일은 상위 1000행 샘플로 검사 (패턴이 있다면 상위에서 발견됨).
    """
    import re

    pattern = re.compile(r"^\d+\.?\d*[eE]\+\d+$")
    hits: list[str] = []

    # Why: 1.1M행 전체에 regex.apply() → 수 분 소요. 상위 1000행이면 즉시.
    sample = data_df.head(1000)

    col_names = list(source_columns[: data_df.shape[1]])
    for col_idx, col in enumerate(sample.columns):
        col_name = col_names[col_idx] if col_idx < len(col_names) else str(col)
        if sample[col].dtype != object:
            continue
        matches = sample[col].dropna().apply(lambda v: bool(pattern.match(str(v))))
        cnt = int(matches.sum())
        if cnt > 0:
            examples = sample[col][matches.values[: len(sample[col])]].head(2).tolist()
            hits.append(f"{col_name}: {cnt}건 (예: {', '.join(str(e) for e in examples)})")

    if not hits:
        return None
    return "\n".join(hits)


def _render_data_warnings(read_result, data_df, source_columns) -> None:
    """데이터 품질 경고를 2그룹(복구 가능 / 정보 제공)으로 분리하여 표시한다.

    Why: 모든 경고에 "무엇이 문제 → 어떻게 처리됨 → 사용자가 할 일"
    3요소를 갖춰야 감사인이 상황을 이해하고 판단할 수 있다.
    """
    if read_result is None or data_df is None:
        return

    _render_datasynth_metadata_notice(data_df)

    # ── 1) 경고 수집: action(복구 가능) vs info(자동 처리) ──
    action_warnings: list[str] = []
    info_warnings: list[str] = []

    # 복구 가능 여부를 먼저 확인 (dry-run) — 샘플로 수행
    from src.ingest.text_reader import repair_dataframe

    tmp_path = st.session_state.get("_ingest_tmp_path")
    _repair_path = Path(tmp_path) if tmp_path else None
    # Why: repair dry-run에 1.1M행 복사본을 넘기면 느리다.
    # 상위 1000행 샘플로 복구 가능 여부만 판단.
    _sample_for_repair = data_df.head(1000).copy()
    _, _dry_repairs = repair_dataframe(_sample_for_repair, read_result, path=_repair_path)
    _has_repairs = len(_dry_repairs) > 0

    # 빈 행 — read_result.data_warnings에서 이미 진단된 결과 활용
    raw_warnings = getattr(read_result, "data_warnings", [])
    _empty_row_warning = next((w for w in raw_warnings if "빈 행" in w), None)
    if _empty_row_warning:
        if _has_repairs:
            action_warnings.append(_empty_row_warning)
        else:
            info_warnings.append(_empty_row_warning)

    # raw_df 기준 경고 — repair가 하나라도 가능하면 action 그룹
    _ACTION_KEYWORDS = ("혼합 구분자", "미닫힌 따옴표")
    for w in raw_warnings:
        if any(kw in w for kw in _ACTION_KEYWORDS):
            if _has_repairs:
                action_warnings.append(w)
            else:
                info_warnings.append(w)

    # 열 수 불일치 → 헤더 이후 행 기준 재계산 (오탐 방지)
    # Why: 혼합 구분자/미닫힌 따옴표 복구 시 열 수 문제도 함께 해소되므로
    # action 경고가 있으면 info 경고를 숨긴다
    if not action_warnings:
        mismatch = _detect_column_mismatch(read_result)
        if mismatch:
            info_warnings.append(mismatch)

    # 지수 표기법 감지 (Excel 손상)
    sci_notation = _detect_scientific_notation(data_df, source_columns)
    if sci_notation:
        info_warnings.append(f"__sci_notation__\n{sci_notation}")

    total = len(action_warnings) + len(info_warnings)
    if total == 0:
        return

    # ── 2) 렌더링 ──
    with st.expander(f"데이터 품질 경고 ({total}건)", expanded=True):
        # 복구 가능 경고 (사용자 액션 필요) — 먼저 표시
        for w in action_warnings:
            if "빈 행" in w:
                st.warning(f"{w} — 자동 복구로 제거할 수 있습니다.")
            elif "혼합 구분자" in w:
                st.warning(f"{w}\n\n자동 복구로 구분자를 통일할 수 있습니다.")
            elif "미닫힌 따옴표" in w:
                st.warning(f"{w}\n\n자동 복구로 따옴표를 무시하고 재파싱을 시도할 수 있습니다.")

        # 복구 미리보기 + 버튼
        if action_warnings:
            has_repairs = _render_repair_preview(
                read_result,
                data_df,
                source_columns,
            )
            if has_repairs:
                if st.button("자동 복구", type="primary"):
                    _apply_auto_repair(read_result, data_df, source_columns)

        # 정보 경고 (자동 처리됨 또는 복구 불가, 참고용)
        for w in info_warnings:
            if "열 수 불일치" in w:
                _render_column_mismatch_warning(w, read_result, source_columns)
            elif w.startswith("__sci_notation__"):
                _render_scientific_notation_warning(w.removeprefix("__sci_notation__\n"))
            elif "미닫힌 따옴표" in w:
                st.info(
                    f"{w}\n\n"
                    "정상 멀티라인 필드가 포함되어 있어 자동 복구가 불가능합니다. "
                    "원본 파일을 직접 확인하세요."
                )
            elif "혼합 구분자" in w:
                st.info(f"{w}\n\n자동 복구가 불가능합니다. 원본 파일을 확인하세요.")
            elif "빈 행" in w:
                st.info(f"{w}")
            else:
                st.info(w)


def _build_datasynth_metadata_notice_lines(data_df) -> list[str]:
    """Extract validated DataSynth metadata notice lines from dataframe attrs."""
    if data_df is None:
        return []

    status = data_df.attrs.get("datasynth_metadata_status")
    critical = list(data_df.attrs.get("datasynth_metadata_critical_mismatches", []))
    warning = list(data_df.attrs.get("datasynth_metadata_warning_mismatches", []))
    metadata_path = data_df.attrs.get("datasynth_metadata_path")
    if not status:
        return []

    lines = [f"DataSynth metadata status: `{status}`"]
    if metadata_path:
        lines.append(f"validated file: `{metadata_path}`")
    if critical:
        lines.append("critical: " + "; ".join(critical[:3]))
    if warning:
        lines.append("warning: " + "; ".join(warning[:3]))
    return lines


def _render_datasynth_metadata_notice(data_df) -> None:
    """Render validated DataSynth metadata status near ingest warnings."""
    lines = _build_datasynth_metadata_notice_lines(data_df)
    if not lines:
        return

    status = data_df.attrs.get("datasynth_metadata_status", "unknown")
    message = "\n\n".join(lines)
    if status == "fail":
        st.error(message)
    elif status == "warning":
        st.warning(message)
    else:
        st.info(message)


def _render_column_mismatch_warning(
    warning_text: str,
    read_result,
    source_columns: list[str],
) -> None:
    """열 수 불일치 경고: 설명 + 접힌 상세 테이블(하이라이트).

    Why: raw_data에서 초과 열까지 포함한 원본을 가져와야 "여분" 값이 보인다.
    data_df는 prepare_dataframe에서 빈 컬럼명 열을 제거하므로 초과 열이 누락됨.
    """
    import re

    import pandas as pd

    lines = warning_text.strip().split("\n")
    summary_line = lines[0]

    # 경고 텍스트에서 문제 행 인덱스 파싱 (1-based → 0-based)
    problem_rows: list[int] = []
    short_count, long_count = 0, 0
    for line in lines[1:]:
        m = re.match(r"\s*행 (\d+)", line)
        if not m:
            continue
        problem_rows.append(int(m.group(1)) - 1)
        if "누락" in line:
            short_count += 1
        elif "초과" in line:
            long_count += 1

    m_mode = re.search(r"기준 (\d+)열", summary_line)
    mode_cols = int(m_mode.group(1)) if m_mode else len(source_columns)

    # ── 설명 블록: 무엇이 문제 + 어떻게 처리됨 + 사용자 액션 ──
    desc_parts = [f"일부 행의 열 수가 기준({mode_cols}열)과 다릅니다."]
    if short_count:
        desc_parts.append(f"  · 누락 {short_count}건: 부족한 열은 빈 값으로 채워집니다")
    if long_count:
        desc_parts.append(f"  · 초과 {long_count}건: 넘치는 값은 자동으로 무시됩니다")
    desc_parts.append("별도 조치가 필요하지 않습니다.")
    st.info("\n\n".join(desc_parts))

    # ── 상세 테이블 (접힌 상태, 참고용) ──
    if not problem_rows or read_result is None:
        return

    sheet = read_result.active_sheet
    raw_df = read_result.raw_data.get(sheet)
    if raw_df is None:
        return

    from src.ingest.header_detector import detect_headers

    header_results = detect_headers(read_result)
    hr = header_results.get(sheet)
    header_offset = (hr.header_row + 1) if hr and hr.header_row is not None else 0

    raw_idxs = [i + header_offset for i in problem_rows if (i + header_offset) < len(raw_df)]
    if not raw_idxs:
        return

    with st.expander("상세 내역", expanded=False):
        subset = raw_df.iloc[raw_idxs].copy()

        # 컬럼명: 기준 열은 source_columns, 초과 열은 "여분N"
        col_labels = list(source_columns[:mode_cols])
        for i in range(mode_cols, subset.shape[1]):
            col_labels.append(f"여분{i - mode_cols + 1}")
        subset.columns = col_labels[: subset.shape[1]]

        subset.index = [f"행 {i + 1}" for i in problem_rows[: len(raw_idxs)]]

        # NaN(누락) → 노란 배경, 초과 열 → 빨간 배경
        yellow = "background-color: #fff3cd"
        red = "background-color: #f8d7da"

        def _highlight_issues(row: pd.Series) -> list[str]:
            return [
                yellow if pd.isna(val) else red if col_idx >= mode_cols else ""
                for col_idx, val in enumerate(row)
            ]

        styled = subset.style.apply(_highlight_issues, axis=1)
        st.dataframe(styled, use_container_width=True)


def _render_scientific_notation_warning(detail: str) -> None:
    """지수 표기법(Excel 손상) 경고를 렌더링한다."""
    st.warning(
        "지수 표기법이 감지되었습니다.\n\n"
        "Excel에서 CSV를 열었다 저장하면 긴 숫자가 `2E+11`, "
        "큰 금액이 `1.5E+07` 등으로 변환됩니다.\n\n"
        "  · **금액 컬럼**: 파이프라인에서 자동 변환됩니다 (`1.5E+07` → `15,000,000`)\n\n"
        "  · **전표번호 등 텍스트 컬럼**: 원본 값 복구가 불가능합니다. "
        "원본 ERP 데이터를 다시 추출하세요.",
    )
    with st.expander("상세 내역", expanded=False):
        for line in detail.strip().split("\n"):
            st.text(f"  {line}")


def _render_repair_preview(read_result, data_df, source_columns) -> bool:
    """현재 모습(왼쪽) vs 복구 후 모습(오른쪽) 비교. 복구 가능 여부를 반환."""
    from src.ingest.text_reader import repair_dataframe

    if data_df is None or len(source_columns) == 0:
        return False

    tmp_path = st.session_state.get("_ingest_tmp_path")
    path = Path(tmp_path) if tmp_path else None
    repaired_df, repairs = repair_dataframe(data_df.copy(), read_result, path=path)
    if not repairs:
        return False

    n = min(5, len(data_df), len(repaired_df))
    col_before, col_after = st.columns(2)

    with col_before:
        st.caption("현재")
        preview = data_df.head(n).copy()
        preview.columns = source_columns[: preview.shape[1]]
        st.dataframe(preview, use_container_width=True, hide_index=True)
        st.caption(f"{len(data_df):,}행 × {data_df.shape[1]}열")

    with col_after:
        st.caption("복구 후")
        cols_after = source_columns[: repaired_df.shape[1]]
        if len(cols_after) < repaired_df.shape[1]:
            cols_after = [str(c) for c in repaired_df.columns]
        preview_r = repaired_df.head(n).copy()
        preview_r.columns = cols_after[: preview_r.shape[1]]
        st.dataframe(preview_r, use_container_width=True, hide_index=True)
        st.caption(f"{len(repaired_df):,}행 × {repaired_df.shape[1]}열")

    return True


def _apply_auto_repair(read_result, data_df, source_columns) -> None:
    """사용자가 자동 복구를 승인한 경우 실행."""
    from src.ingest.column_mapper import auto_map_columns
    from src.ingest.text_reader import repair_dataframe

    tmp_path = st.session_state.get("_ingest_tmp_path")
    path = Path(tmp_path) if tmp_path else None
    repaired_df, repairs = repair_dataframe(data_df, read_result, path=path)

    if not repairs:
        st.info("복구할 항목이 없습니다.")
        return

    # 복구 후 헤더 재탐지 + 매핑 재실행
    source_columns_new = [str(c) for c in repaired_df.columns]

    st.session_state[KEY_INGEST_DATA_DF] = repaired_df
    st.session_state[KEY_INGEST_SOURCE_COLUMNS] = source_columns_new

    # 매핑 재실행
    mapping_result = auto_map_columns(
        source_columns_new,
        data_df=repaired_df,
    )
    st.session_state[KEY_INGEST_MAPPING_RESULT] = mapping_result

    # 경고 갱신 (복구 완료 표시)
    read_result.data_warnings = [f"[복구됨] {r}" for r in repairs]

    st.rerun()


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
        st.info("분석을 시작합니다. 데이터 크기에 따라 수십 초가 소요될 수 있습니다.")
        progress_bar = st.progress(0, text="파이프라인 시작...")
        result, warns = _run_pipeline_from_mapped(file_key, _make_progress_cb(progress_bar))
        progress_bar.empty()

        # 파이프라인 완료 → 결과 탭 화면으로 전환
        st.rerun()

    except ValueError as e:
        # Why: L1/L2 검증 fatal — 회계 근본 위반(대차불일치 등)은 일반 예외와 분리하여
        #      사용자에게 명확한 차단 사유를 표시. 감사조서 추적은 audit_log에 이미 기록됨.
        logger.warning("파이프라인 검증 차단: %s", e)
        st.error(f"검증 단계 차단: {e}")
        st.warning(
            "데이터 무결성 위반(예: 차변 ≠ 대변)이 임계를 초과했습니다. "
            "원본 GL 파일을 확인 후 다시 업로드해 주세요."
        )
        _clear_ingest_state()
    except Exception as e:
        logger.exception("파이프라인 실행 실패")
        st.error(f"파이프라인 실행 실패: {e}")
        if st.session_state.get(KEY_DEV_MODE):
            st.exception(e)
        _clear_ingest_state()


# ── Ingest 로직 ──────────────────────────────────────────


def _run_ingest_common(read_result, progress_cb) -> None:
    """ReadResult → header detect → column map → 세션 저장. 공통 로직."""
    from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
    from src.ingest.header_detector import detect_headers
    from src.ingest.mapping_profile import load_profile
    from src.ingest.sheet_scorer import score_sheets

    if read_result.source_format == "parquet":
        sheet_name = read_result.active_sheet
        data_df = read_result.raw_data[sheet_name]
        source_columns = list(data_df.columns)
        matched_keywords: list[str] = []
        sheet_scores = []
    else:
        progress_cb(0.88, "헤더 탐지 중...")
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

    progress_cb(0.94, "컬럼 매핑 중...")

    # Why: RC-5-1 — 회사별 프로파일 디렉토리 우선, 없으면 글로벌 폴백
    _ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    _pdir = _ctx.profile_dir if _ctx and not _ctx.is_anonymous else None

    profile = load_profile(source_columns, profile_dir=_pdir)
    if profile is not None and not profile.needs_review:
        mapping_result = profile
    else:
        mapping_result = auto_map_columns(
            source_columns,
            matched_keywords,
            data_df=data_df,
        )

    # Why: 라벨 "작년 컬럼매핑과 비교"에 맞춰, **직전 회계연도(current_fy - 1)**
    #      프로파일과 비교한다. ctx.fiscal_year가 없으면(anonymous) 비교 생략.
    from src.ingest.mapping_profile import (
        ColumnDiff,
        column_fingerprint,
        compute_column_diff,
        load_prior_year_profile,
    )

    current_fy = getattr(_ctx, "fiscal_year", None) if _ctx is not None else None
    st.session_state["_ingest_current_fy"] = current_fy
    st.session_state["_ingest_prior_fy"] = (current_fy - 1) if current_fy else None

    prev = (
        load_prior_year_profile(current_fy - 1, profile_dir=_pdir)
        if current_fy is not None
        else None
    )
    if prev is not None and prev.get("fingerprint") != column_fingerprint(source_columns):
        st.session_state[KEY_INGEST_COLUMN_DIFF] = compute_column_diff(
            prev["source_columns"],
            source_columns,
            prev_fingerprint=prev["fingerprint"],
            prev_source_name=prev["source_name"],
        )
    elif prev is not None:
        # 같은 fingerprint — 빈 diff로 "변경 없음" 명시
        st.session_state[KEY_INGEST_COLUMN_DIFF] = ColumnDiff(
            prev_fingerprint=prev.get("fingerprint", ""),
            prev_source_name=prev.get("source_name", ""),
        )
    else:
        st.session_state[KEY_INGEST_COLUMN_DIFF] = None

    st.session_state[KEY_INGEST_READ_RESULT] = read_result
    st.session_state[KEY_INGEST_SHEET_SCORES] = sheet_scores
    st.session_state[KEY_INGEST_SELECTED_SHEET] = sheet_name
    st.session_state[KEY_INGEST_SOURCE_COLUMNS] = source_columns
    st.session_state[KEY_INGEST_DATA_DF] = data_df
    st.session_state[KEY_INGEST_MAPPING_RESULT] = mapping_result
    st.session_state[KEY_INGEST_CONFIRMED] = False
    st.session_state[KEY_INGEST_PREPARED_DF] = None
    st.session_state[KEY_INGEST_PREP_WARNINGS] = []

    st.session_state[KEY_INGEST_STAGE] = "REVIEW"


def _run_ingest_from_path(local_path: Path, progress_cb) -> None:
    """로컬 파일 경로 → 검증 → ingest. 브라우저 업로드를 건너뛴다.

    Why: 321MB 파일을 Streamlit file_uploader로 올리면 브라우저→서버
    HTTP 전송에 수 분이 소요. 로컬 경로 직접 읽기는 디스크 I/O만으로 즉시 시작.
    """
    from src.ingest.file_validator import validate_file

    progress_cb(0.02, "파일 검증 중...")
    validation = validate_file(local_path)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))

    # 원본 파일 경로를 세션에 보관 (복구 시 재읽기용)
    st.session_state["_ingest_tmp_path"] = str(local_path)
    st.session_state["_ingest_is_user_path"] = True  # 사용자 파일은 삭제 방지

    def _file_read_cb(pct: float, msg: str) -> None:
        overall = 0.05 + pct * 0.80
        progress_cb(overall, msg)

    progress_cb(0.05, "파일 읽는 중...")
    from src.ingest.reader_api import read_file

    read_result = read_file(local_path, progress_cb=_file_read_cb)

    # 이후 로직은 _run_ingest와 동일
    _run_ingest_common(read_result, progress_cb)


def _build_audit_trail(ctx):
    """CompanyContext로부터 AuditTrail 생성. 조건 불충족 시 None.

    Why: WU-27 — 파이프라인 각 단계(upload/validate/analysis/DB load)를
         engagement DB의 audit_log에 기록. anonymous ctx나 DB 미연결 시에는
         None을 반환하고 AuditPipeline은 _NullAuditTrail 폴백으로 동작.
    """
    if ctx is None or ctx.is_anonymous:
        return None
    try:
        from src.db.connection import get_connection
        from src.export.audit_trail import AuditTrail

        conn = get_connection(str(ctx.db_path))
        return AuditTrail(conn)
    except Exception:  # pragma: no cover — 방어적
        logger.warning("AuditTrail 생성 실패 — 증적 기록 없이 진행", exc_info=True)
        return None


def _build_mapped_dataframe(mapping_result, data_df):
    """확정 매핑을 현재 DataFrame 컬럼에 반영."""
    rename_map = {}
    for src, tgt in mapping_result.mapping.items():
        if src in data_df.columns:
            rename_map[src] = tgt
        else:
            try:
                int_key = int(src)
                if int_key in data_df.columns:
                    rename_map[int_key] = tgt
            except (ValueError, TypeError):
                rename_map[src] = tgt
    return data_df.rename(columns=rename_map)


def _run_pipeline_from_mapped(file_key: str, progress_cb, *, prepare_only: bool = False):
    """확정 매핑 적용 → cast → AuditPipeline 실행 → 결과 저장."""
    from src.ingest.mapping_profile import save_profile
    from src.ingest.type_caster import cast_dataframe
    from src.pipeline import AuditPipeline

    mapping_result = st.session_state[KEY_INGEST_MAPPING_RESULT]
    data_df = st.session_state[KEY_INGEST_DATA_DF]
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    read_result = st.session_state.get(KEY_INGEST_READ_RESULT)

    # Why: 헤더 없는 파일은 columns가 정수(0,1,2)인데 mapping 키는 문자열("0","1","2").
    #      rename 전에 키 타입을 DataFrame의 실제 컬럼 타입에 맞춘다.
    rename_map = {}
    for src, tgt in mapping_result.mapping.items():
        if src in data_df.columns:
            rename_map[src] = tgt
        else:
            # 문자열 키 → 정수 컬럼 변환 시도
            try:
                int_key = int(src)
                if int_key in data_df.columns:
                    rename_map[int_key] = tgt
            except (ValueError, TypeError):
                rename_map[src] = tgt
    df = data_df.rename(columns=rename_map)

    progress_cb(0.20, "타입 캐스팅 중...")
    cast_result = cast_dataframe(df)
    df = cast_result.data
    warns = list(cast_result.warnings)
    if cast_result.errors:
        warns.extend(cast_result.errors)

    progress_cb(0.25, "파이프라인 시작...")
    # Why: RC-4-5 — CompanyContext 우선, 없으면 settings 폴백
    ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    settings = st.session_state.get(KEY_SETTINGS)
    repo = st.session_state.get("_company_repo")
    # Why: DB upload_batches 메타에 파일명 기록 (PipelineResult.file_name 경유)
    fname = st.session_state.get("_ingest_source_hint") or (
        file_key.rsplit("_", 1)[0] if file_key else ""
    )
    source_path = st.session_state.get("_ingest_tmp_path")
    if source_path and not st.session_state.get("_ingest_source_hint"):
        fname = source_path
    # Why: WU-27 — engagement DB 커넥션으로 AuditTrail 생성하여 각 단계 증적 기록.
    #      ctx 없는 폴백 경로(anonymous)에서는 AuditTrail 연결 대상 DB가 없으므로 생략.
    audit_trail = build_audit_trail(ctx)
    if ctx is not None:
        pipeline = AuditPipeline(
            context=ctx,
            progress_callback=progress_cb,
            repo=repo,
            audit_trail=audit_trail,
        )
    else:
        pipeline = AuditPipeline(
            settings=settings,
            progress_callback=progress_cb,
            audit_trail=audit_trail,
        )
    if prepare_only:
        result = pipeline.prepare_from_dataframe(df, file_name=fname)
    else:
        result = pipeline.run_from_dataframe(df, file_name=fname)
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

            # Why: RC-5-1 — 회사별 프로파일 디렉토리로 저장 + fiscal_year 메타로
            #      다음 연도에서 "작년 컬럼매핑 비교"가 작동.
            _pdir = ctx.profile_dir if ctx and not ctx.is_anonymous else None
            _fy = getattr(ctx, "fiscal_year", None) if ctx else None
            save_profile(
                mapping_result,
                source_columns,
                source_name=file_key.rsplit("_", 1)[0],
                source_format=read_result.source_format if read_result else "",
                header_row=header_row,
                fiscal_year=_fy,
                profile_dir=_pdir,
            )
        except Exception:
            logger.warning("프로파일 저장 실패", exc_info=True)

    if not prepare_only:
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
    # tempfile 삭제 (경로 모드에서 직접 지정한 파일은 삭제하지 않음)
    tmp = st.session_state.pop("_ingest_tmp_path", None)
    is_user_file = st.session_state.pop("_ingest_is_user_path", False)
    if tmp and not is_user_file:
        Path(tmp).unlink(missing_ok=True)

    for key in [
        KEY_INGEST_READ_RESULT,
        KEY_INGEST_MAPPING_RESULT,
        KEY_INGEST_SHEET_SCORES,
        KEY_INGEST_SELECTED_SHEET,
        KEY_INGEST_SOURCE_COLUMNS,
        KEY_INGEST_DATA_DF,
        KEY_INGEST_CONFIRMED,
        KEY_INGEST_PREPARED_DF,
        KEY_INGEST_PREP_WARNINGS,
        "_ingest_file_key",
        "_ingest_source_hint",
        "_ingest_current_fy",
        "_ingest_prior_fy",
    ]:
        st.session_state.pop(key, None)
    st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
