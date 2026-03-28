"""3-tier 컬럼 매핑 확인 UI — Green(자동) / Yellow(확인) / Red(수동).

Why: 외부 ERP 데이터 업로드 시 auto_map_columns의 매핑 결과를
     감사인이 시각적으로 검토·수정할 수 있는 인터페이스 제공.
     필수 컬럼 미매핑 시 파이프라인 진행을 차단.

UX 1단계 스펙 (ux-flow.md):
  UI-1: 인코딩 드롭다운 (confidence < 0.7)
  UI-2: 시트 선택 테이블 (멀티시트 Excel)
  UI-3: Fuzzy 엄격도 슬라이더
  UI-4: 중복 금액 퀵픽스 버튼
"""

from __future__ import annotations

import streamlit as st

from config.settings import get_schema
from dashboard._state import (
    KEY_INGEST_DATA_DF,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_READ_RESULT,
    KEY_INGEST_SELECTED_SHEET,
    KEY_INGEST_SHEET_SCORES,
    KEY_INGEST_SOURCE_COLUMNS,
    KEY_INGEST_STAGE,
)


# ── 스키마 헬퍼 ──────────────────────────────────────────


def _get_required_columns(schema: dict) -> set[str]:
    """schema.yaml에서 required=true 컬럼명 set 추출."""
    return {
        col["name"] for col in schema.get("columns", [])
        if col.get("required", False)
    }


def _get_all_standard_columns(schema: dict) -> list[str]:
    """schema.yaml의 전체 표준 컬럼명 (label 컬럼 제외, 정렬)."""
    return sorted(
        col["name"] for col in schema.get("columns", [])
        if not col.get("is_label", col.get("type") == "bool")
    )


def _get_recommended_columns(schema: dict) -> set[str]:
    """schema.yaml에서 권장 컬럼(required=false, label 아닌) 추출."""
    return {
        col["name"] for col in schema.get("columns", [])
        if not col.get("required", False)
        and not col.get("is_label", col.get("type") == "bool")
    }


# ── 드롭다운 라벨링 ────────────────────────────────────────

# Why: 영문 키만으로는 비개발자 감사인이 의미를 파악하기 어렵다.
#      한글 설명 + 영문 키 + 필수 여부를 조합하여 가독성 향상.
_COLUMN_LABELS: dict[str, str] = {
    "document_id": "전표번호",
    "company_code": "회사코드",
    "fiscal_year": "회계연도",
    "fiscal_period": "회계기간",
    "posting_date": "전기일자",
    "document_date": "증빙일자",
    "document_type": "전표유형",
    "gl_account": "계정코드",
    "debit_amount": "차변금액",
    "credit_amount": "대변금액",
    "currency": "통화",
    "exchange_rate": "환율",
    "reference": "참조번호",
    "header_text": "적요",
    "created_by": "작성자",
    "user_persona": "사용자유형",
    "source": "전표출처",
    "business_process": "업무프로세스",
    "ledger": "원장",
    "approved_by": "승인자",
    "approval_date": "승인일자",
    "line_number": "라인번호",
    "local_amount": "현지금액",
    "cost_center": "코스트센터",
    "profit_center": "손익센터",
    "line_text": "라인적요",
    "tax_code": "세금코드",
    "tax_amount": "세금액",
    "trading_partner": "거래처",
    "auxiliary_account_number": "보조계정번호",
    "auxiliary_account_label": "보조계정명",
    "lettrage": "대사그룹",
    "lettrage_date": "대사일자",
    "anomaly_type": "이상유형",
    "fraud_type": "부정유형",
    "is_fraud": "부정여부",
    "is_anomaly": "이상여부",
    "sod_violation": "SoD위반",
    "sod_conflict_type": "SoD충돌유형",
}


def _format_option(col_name: str, required_cols: set[str]) -> str:
    """드롭다운 선택지를 '한글명 (영문키) *필수*' 형식으로 포매팅."""
    label = _COLUMN_LABELS.get(col_name, "")
    tag = " ★필수" if col_name in required_cols else ""
    if label:
        return f"{label} ({col_name}){tag}"
    return f"{col_name}{tag}"


def _parse_option(formatted: str) -> str:
    """포매팅된 선택지에서 원본 영문 키를 추출."""
    if formatted == "(무시)":
        return "(무시)"
    # "한글명 (영문키) ★필수" → "영문키"
    if "(" in formatted and ")" in formatted:
        start = formatted.index("(") + 1
        end = formatted.index(")")
        return formatted[start:end]
    # "영문키" 또는 "영문키 ★필수"
    return formatted.split(" ★필수")[0].strip()


# ── 미매핑 사유 + 영향 범위 매핑 ────────────────────────

# Why: 필수 컬럼별 미매핑 시 구체적 사유 안내 (ux-flow.md §175)
_REQUIRED_REASONS: dict[str, str] = {
    "document_id": "전표 식별 불가 → 모든 분석 불가능",
    "company_code": "법인 구분 불가 → 법인별 분석 불가능",
    "fiscal_year": "회계연도 식별 불가 → 기간별 분석 불가능",
    "fiscal_period": "회계기간 식별 불가 → 결산기 탐지(C01) 불가능",
    "posting_date": "전기일 없이 시계열 분석 불가 → 주말(C02)·심야(C03)·백데이팅(C04) 전부 비활성",
    "document_date": "증빙일 없이 백데이팅(C04) 탐지 불가능",
    "gl_account": "계정과목 없이 매출조작(B01)·가수금(C09) 탐지 불가능",
    "debit_amount": "차변 금액 없이 차대균형(A01) 검증 불가능",
    "credit_amount": "대변 금액 없이 차대균형(A01) 검증 불가능",
    "document_type": "전표유형 없이 수기전표(B08) 판정 불가능",
}

# Why: 권장 컬럼별 미매핑 시 비활성화되는 탐지 룰 안내 (ux-flow.md §176)
_RECOMMENDED_IMPACT: dict[str, str] = {
    "created_by": "B06 자기승인 · B07 SoD 위반 · B09 권한 탈취 탐지 비활성화",
    "approved_by": "B06 자기승인(작성자=승인자) 탐지 비활성화",
    "source": "B08 수기전표 비율 탐지 비활성화",
    "user_persona": "B10 Junior 심야 · B11 자동화 예외 탐지 비활성화",
    "business_process": "프로세스별 분석·대시보드 그룹화 비활성화",
    "reference": "A02 참조번호 누락 검증 비활성화",
    "header_text": "C06 위험 키워드 탐지 (헤더 적요) 비활성화",
    "currency": "다통화 환산 검증 비활성화",
    "exchange_rate": "환율 이상 탐지 비활성화",
    "approval_date": "승인 지연 분석 비활성화",
    "ledger": "원장별 분석 비활성화",
}


# ── 메인 렌더 ────────────────────────────────────────────


def render_mapping_review() -> None:
    """매핑 리뷰 메인 렌더 함수. REVIEW 스테이지에서 호출."""
    mapping_result = st.session_state.get(KEY_INGEST_MAPPING_RESULT)
    read_result = st.session_state.get(KEY_INGEST_READ_RESULT)

    if mapping_result is None:
        st.warning("매핑 결과가 없습니다. 파일을 다시 업로드해 주세요.")
        if st.button("돌아가기"):
            st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
            st.rerun()
        return

    schema = get_schema()
    all_standard = _get_all_standard_columns(schema)
    required_cols = _get_required_columns(schema)
    recommended_cols = _get_recommended_columns(schema)

    st.subheader("컬럼 매핑 확인")

    # ── UI-1: 인코딩 드롭다운 + UI-2: 시트 선택 ──
    if read_result:
        _render_encoding_selector(read_result)
        _render_sheet_selector(read_result)

    # ── UI-3: Fuzzy 엄격도 슬라이더 ──
    _render_fuzzy_slider()

    # ── UI-4: 중복 금액 퀵픽스 ──
    quickfix_overrides = _render_amount_quickfix(mapping_result)

    # ── 통합 매핑 리스트 (Green/Yellow/Red 구분 없이) ──
    user_overrides = _render_mapping_unified(
        mapping_result, all_standard, required_cols,
    )
    user_overrides.update(quickfix_overrides)

    # ── 미매핑 시 분석 불가 항목 (필수 + 권장 통합 expander) ──
    effective = {**mapping_result.mapping, **user_overrides}
    mapped_standards = set(effective.values()) - {"(무시)"}
    still_missing = required_cols - mapped_standards

    missing_recommended = recommended_cols - mapped_standards
    impacted = {col: _RECOMMENDED_IMPACT[col] for col in missing_recommended
                if col in _RECOMMENDED_IMPACT}

    total_issues = len(still_missing) + len(impacted)
    if total_issues > 0:
        with st.expander(
            f"미매핑 시 분석 불가 항목 ({total_issues}건)", expanded=False,
        ):
            if still_missing:
                st.markdown("**필수 컬럼**")
                for col in sorted(still_missing):
                    label = _COLUMN_LABELS.get(col, col)
                    reason = _REQUIRED_REASONS.get(col, "필수 컬럼 미매핑")
                    st.error(f"**{label} ({col})** — {reason}")

            if impacted:
                st.markdown("**권장 컬럼**")
                for col, impact in sorted(impacted.items()):
                    label = _COLUMN_LABELS.get(col, col)
                    st.warning(f"**{label} ({col})** — {impact}")

    # ── 확인 / 취소 ──
    col1, col2 = st.columns(2)
    with col1:
        if st.button("매핑 확인", disabled=bool(still_missing), type="primary"):
            from dataclasses import replace as dc_replace
            final_mapping = {
                k: v for k, v in {**mapping_result.mapping, **user_overrides}.items()
                if v != "(무시)"
            }
            updated = dc_replace(mapping_result, mapping=final_mapping)
            st.session_state[KEY_INGEST_MAPPING_RESULT] = updated
            st.session_state[KEY_INGEST_STAGE] = "PIPELINE"
            st.rerun()
    with col2:
        if st.button("취소"):
            _clear_and_reset()


# ── UI-1: 인코딩 드롭다운 ────────────────────────────────


_ENCODING_OPTIONS = ["utf-8", "cp949", "euc-kr", "latin-1", "ascii", "utf-16"]


def _render_encoding_selector(read_result) -> None:
    """인코딩 정보 + 저신뢰 시 수동 선택 드롭다운."""
    enc = read_result.encoding or "N/A"
    conf = read_result.encoding_confidence
    fmt = read_result.source_format

    info_parts = [f"포맷: {fmt.upper()}"]
    if read_result.encoding:
        info_parts.append(f"인코딩: {enc}")
        if conf is not None:
            info_parts.append(f"신뢰도: {conf:.0%}")
    st.caption(" · ".join(info_parts))

    # Why: ux-flow.md UI-1 — confidence < 0.7 시 인코딩 수동 선택 드롭다운 노출
    if conf is not None and conf < 0.7:
        st.warning(f"인코딩 감지 신뢰도가 낮습니다 ({conf:.0%}).")
        current_enc = enc.lower() if enc else "utf-8"
        default_idx = _ENCODING_OPTIONS.index(current_enc) if current_enc in _ENCODING_OPTIONS else 0
        new_enc = st.selectbox(
            "인코딩 수동 선택", _ENCODING_OPTIONS,
            index=default_idx, key="encoding_override_select",
        )
        if new_enc != current_enc:
            if st.button("이 인코딩으로 다시 읽기", key="btn_reread_encoding"):
                _reread_with_encoding(read_result, new_enc)
                st.rerun()


def _reread_with_encoding(read_result, encoding: str) -> None:
    """인코딩 오버라이드로 파일 재읽기 + 재매핑.

    Why: read_result에 원본 파일 경로가 없으므로 session_state의
         UploadedFile 바이트를 tempfile로 재생성하여 read_file(encoding_override=) 호출.
    """
    import tempfile
    from pathlib import Path

    from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
    from src.ingest.header_detector import detect_headers
    from src.ingest.reader_api import read_file
    from src.ingest.sheet_scorer import score_sheets

    # Why: _ingest_file_key에서 파일명 복원, suffix로 reader 디스패치
    file_key = st.session_state.get("_ingest_file_key", "file.csv")
    suffix = Path(file_key.rsplit("_", 1)[0]).suffix or ".csv"

    # Why: UploadedFile 원본은 Streamlit rerun 시 사라지므로
    #      기존 read_result의 raw_data를 CSV로 재직렬화하여 tempfile 생성
    sheet_name = st.session_state.get(KEY_INGEST_SELECTED_SHEET, read_result.active_sheet)
    raw_df = read_result.raw_data[sheet_name]

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        # Why: raw_data를 원본 그대로 재읽기하려면 바이트가 필요하지만
        #      read_result에 원본 바이트가 없으므로, 텍스트 포맷만 인코딩 재시도
        raw_df.to_csv(f, index=False, header=False)
        tmp_path = Path(f.name)

    try:
        new_read = read_file(tmp_path, encoding_override=encoding)
    finally:
        tmp_path.unlink(missing_ok=True)

    header_results = detect_headers(new_read)
    sheet_scores = score_sheets(new_read, header_results)
    new_sheet = new_read.active_sheet

    header_result = header_results.get(new_sheet)
    new_raw = new_read.raw_data[new_sheet]

    if header_result and header_result.header_row is not None:
        source_columns, data_df = prepare_dataframe(new_raw, header_result.header_row)
        matched_kw = header_result.matched_keywords
    else:
        source_columns = [str(c) for c in new_raw.columns]
        data_df = new_raw
        matched_kw = []

    mapping_result = auto_map_columns(source_columns, matched_kw, data_df=data_df)

    st.session_state[KEY_INGEST_READ_RESULT] = new_read
    st.session_state[KEY_INGEST_SHEET_SCORES] = sheet_scores
    st.session_state[KEY_INGEST_SELECTED_SHEET] = new_sheet
    st.session_state[KEY_INGEST_SOURCE_COLUMNS] = source_columns
    st.session_state[KEY_INGEST_DATA_DF] = data_df
    st.session_state[KEY_INGEST_MAPPING_RESULT] = mapping_result


# ── UI-2: 시트 선택 ──────────────────────────────────────


def _render_sheet_selector(read_result) -> None:
    """멀티시트 Excel: 시트 선택 UI. 변경 시 매핑 재실행."""
    if len(read_result.sheets) < 2:
        return

    sheet_scores = st.session_state.get(KEY_INGEST_SHEET_SCORES)
    current = st.session_state.get(KEY_INGEST_SELECTED_SHEET, read_result.active_sheet)

    if sheet_scores:
        import pandas as pd
        score_df = pd.DataFrame([
            {"시트": s.sheet_name, "행수": s.row_count, "열수": s.col_count,
             "헤더신뢰도": f"{s.header_confidence:.0%}", "총점": f"{s.total_score:.2f}",
             "추천": "★" if s.recommended else ""}
            for s in sheet_scores
        ])
        with st.expander("시트 품질 점수"):
            st.dataframe(score_df, hide_index=True, use_container_width=True)

    new_sheet = st.selectbox(
        "분석 대상 시트", read_result.sheets,
        index=read_result.sheets.index(current) if current in read_result.sheets else 0,
        key="mapping_sheet_select",
    )

    if new_sheet != current:
        _rerun_mapping_for_sheet(read_result, new_sheet)
        st.rerun()


def _rerun_mapping_for_sheet(read_result, sheet_name: str) -> None:
    """시트 변경 시 데이터 재로드 + 매핑 재실행."""
    from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
    from src.ingest.header_detector import detect_headers

    header_results = detect_headers(read_result)
    header_result = header_results.get(sheet_name)
    raw_df = read_result.raw_data[sheet_name]

    if header_result and header_result.header_row is not None:
        source_columns, data_df = prepare_dataframe(raw_df, header_result.header_row)
        matched_kw = header_result.matched_keywords
    else:
        source_columns = [str(c) for c in raw_df.columns]
        data_df = raw_df
        matched_kw = []

    mapping_result = auto_map_columns(source_columns, matched_kw, data_df=data_df)

    st.session_state[KEY_INGEST_SELECTED_SHEET] = sheet_name
    st.session_state[KEY_INGEST_SOURCE_COLUMNS] = source_columns
    st.session_state[KEY_INGEST_DATA_DF] = data_df
    st.session_state[KEY_INGEST_MAPPING_RESULT] = mapping_result


# ── UI-3: Fuzzy 엄격도 슬라이더 ──────────────────────────


def _render_fuzzy_slider() -> None:
    """매핑 엄격도 슬라이더. 변경 시 auto_map_columns 재실행.

    Why: ux-flow.md UI-3 — 확정 임계값(기본 80)과 추천 경계(기본 40)를
         사용자가 조정하여 매핑 민감도를 제어.
    """
    from config.settings import get_settings
    settings = get_settings()

    with st.expander("매핑 엄격도 조정"):
        col1, col2 = st.columns(2)
        with col1:
            new_threshold = st.slider(
                "확정 임계값", min_value=50, max_value=100,
                value=st.session_state.get("_fuzzy_threshold", settings.fuzzy_threshold),
                step=5, key="fuzzy_threshold_slider",
                help="이 값 이상이면 자동 확정 (Green)",
            )
        with col2:
            new_low = st.slider(
                "추천 경계", min_value=10, max_value=70,
                value=st.session_state.get("_fuzzy_low_threshold", settings.fuzzy_low_threshold),
                step=5, key="fuzzy_low_slider",
                help="이 값 이상이면 추천 (Yellow), 미만이면 수동 (Red)",
            )

        prev_threshold = st.session_state.get("_fuzzy_threshold", settings.fuzzy_threshold)
        prev_low = st.session_state.get("_fuzzy_low_threshold", settings.fuzzy_low_threshold)

        if new_threshold != prev_threshold or new_low != prev_low:
            st.session_state["_fuzzy_threshold"] = new_threshold
            st.session_state["_fuzzy_low_threshold"] = new_low
            if st.button("엄격도 적용", key="btn_apply_fuzzy"):
                _rerun_mapping_with_settings(new_threshold, new_low)
                st.rerun()


def _rerun_mapping_with_settings(threshold: int, low_threshold: int) -> None:
    """엄격도 변경 시 auto_map_columns 재실행."""
    from src.ingest.column_mapper import auto_map_columns

    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    data_df = st.session_state.get(KEY_INGEST_DATA_DF)

    if not source_columns or data_df is None:
        return

    mapping_result = auto_map_columns(
        source_columns, data_df=data_df,
        settings_override={
            "fuzzy_threshold": threshold,
            "fuzzy_low_threshold": low_threshold,
        },
    )
    st.session_state[KEY_INGEST_MAPPING_RESULT] = mapping_result


# ── UI-4: 중복 금액 퀵픽스 ───────────────────────────────


def _render_amount_quickfix(mapping_result) -> dict[str, str]:
    """중복 금액 ReviewItem 감지 시 퀵픽스 버튼 노출.

    Why: ux-flow.md UI-4 — "금액", "금액_2" 인접 패턴 감지 시
         원클릭으로 차변/대변 분리 매핑 적용.
    """
    overrides: dict[str, str] = {}

    # Why: ReviewItem에서 target_type이 debit_amount/credit_amount인 쌍을 찾음
    amount_items = [
        item for item in mapping_result.review_items
        if item.target_type in ("debit_amount", "credit_amount")
    ]

    if len(amount_items) < 2:
        return overrides

    # 차변/대변 쌍 추출
    debit_item = next((i for i in amount_items if i.target_type == "debit_amount"), None)
    credit_item = next((i for i in amount_items if i.target_type == "credit_amount"), None)

    if debit_item and credit_item:
        st.info(
            f"중복 금액 컬럼 감지: **{debit_item.column}** + **{credit_item.column}**\n\n"
            f"차변(debit) / 대변(credit)으로 분리하시겠습니까?"
        )
        if st.button("차변/대변 분리 적용", key="btn_amount_quickfix"):
            overrides[debit_item.column] = "debit_amount"
            overrides[credit_item.column] = "credit_amount"
            st.success(
                f"{debit_item.column} → debit_amount, "
                f"{credit_item.column} → credit_amount 적용"
            )

    return overrides


# ── 3-tier 매핑 테이블 ───────────────────────────────────


def _get_sample_values(src: str, n: int = 3) -> str:
    """원본 컬럼의 상위 N개 고유값을 쉼표로 연결."""
    data_df = st.session_state.get(KEY_INGEST_DATA_DF)
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    if data_df is None or src not in source_columns:
        return ""
    idx = source_columns.index(src)
    if idx >= data_df.shape[1]:
        return ""
    series = data_df.iloc[:, idx].dropna().astype(str)
    uniques = series.unique()[:n]
    if len(uniques) == 0:
        return ""
    preview = ", ".join(str(v)[:20] for v in uniques)
    suffix = "…" if len(series.unique()) > n else ""
    return f"[{preview}{suffix}]"


def _sort_options(
    available: list[str], required_cols: set[str], recommended_cols: set[str],
) -> list[str]:
    """드롭다운 선택지를 필수 → 권장 → 나머지 순으로 정렬."""
    req = sorted(c for c in available if c in required_cols)
    rec = sorted(c for c in available if c in recommended_cols and c not in required_cols)
    etc = sorted(c for c in available if c not in required_cols and c not in recommended_cols)
    return req + rec + etc


def _render_mapping_unified(
    mapping_result,
    all_standard: list[str],
    required_cols: set[str],
) -> dict[str, str]:
    """통합 매핑 리스트 — Green/Yellow/Red 구분 없이 모든 원본 컬럼을 드롭다운으로 표시.

    드롭다운 정렬: 필수 → 권장 → 나머지 (알파벳순).
    이미 매핑된 컬럼은 다른 드롭다운에서 제외.
    """
    schema = get_schema()
    recommended_cols = _get_recommended_columns(schema)
    confidence = mapping_result.confidence

    user_overrides: dict[str, str] = {}
    taken: set[str] = set()

    # 모든 원본 컬럼 수집 (매핑된 것 + 추천된 것 + 미매핑)
    all_sources: list[tuple[str, str | None]] = []

    for src, tgt in mapping_result.mapping.items():
        all_sources.append((src, tgt))
    for src, tgt in mapping_result.suggestions.items():
        if src not in dict(all_sources):
            all_sources.append((src, tgt))
    for src in mapping_result.unmapped:
        if src not in dict(all_sources):
            all_sources.append((src, None))

    total = len(all_sources)
    st.caption(f"원본 컬럼 {total}개")

    for src, suggested_tgt in all_sources:
        sample = _get_sample_values(src)
        conf = confidence.get(src, 0)

        available = [c for c in all_standard if c not in taken]
        if suggested_tgt and suggested_tgt not in available:
            available.insert(0, suggested_tgt)

        sorted_available = _sort_options(available, required_cols, recommended_cols)
        fmt_options = ["(무시)"] + [
            _format_option(c, required_cols) for c in sorted_available
        ]

        default_idx = 0
        if suggested_tgt:
            fmt_suggested = _format_option(suggested_tgt, required_cols)
            if fmt_suggested in fmt_options:
                default_idx = fmt_options.index(fmt_suggested)

        label = f"{sample} {src} →" if sample else f"{src} →"
        chosen_fmt = st.selectbox(
            label, fmt_options, index=default_idx,
            key=f"map_{src}",
            help=f"신뢰도: {conf:.0%}" if conf > 0 else "매핑 불가",
        )
        chosen = _parse_option(chosen_fmt)
        if chosen != "(무시)":
            user_overrides[src] = chosen
            taken.add(chosen)

    return user_overrides


# ── 헬퍼 ────────────────────────────────────────────────


def _clear_and_reset() -> None:
    """인제스트 상태 초기화 + UPLOAD 스테이지로 복귀."""
    for key in [
        KEY_INGEST_READ_RESULT, KEY_INGEST_MAPPING_RESULT,
        KEY_INGEST_SHEET_SCORES, KEY_INGEST_SELECTED_SHEET,
        KEY_INGEST_SOURCE_COLUMNS, KEY_INGEST_DATA_DF,
        "_ingest_file_key", "_fuzzy_threshold", "_fuzzy_low_threshold",
    ]:
        st.session_state.pop(key, None)
    st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
    st.rerun()
