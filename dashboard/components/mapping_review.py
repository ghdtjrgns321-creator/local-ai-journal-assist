from __future__ import annotations

import logging
from dataclasses import replace as dc_replace

import streamlit as st

from config.settings import get_keywords, get_schema
from dashboard._state import (
    KEY_COMPANY_CONTEXT,
    KEY_INGEST_COLUMN_DIFF,
    KEY_INGEST_CONFIRMED,
    KEY_INGEST_DATA_DF,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_PREP_WARNINGS,
    KEY_INGEST_READ_RESULT,
    KEY_INGEST_SELECTED_SHEET,
    KEY_INGEST_SHEET_SCORES,
    KEY_INGEST_SOURCE_COLUMNS,
    KEY_INGEST_STAGE,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_UPLOAD_COUNT,
)
from src.preprocessing.constants import LABEL_COLUMNS, SYNTHETIC_ONLY_COLUMNS
from src.services.session_service import close_dashboard_connections

logger = logging.getLogger(__name__)

# Why: SYNTHETIC_ONLY_COLUMNS는 실제 고객 CSV에 존재하지 않는 DataSynth 합성 전용 컬럼.
#      여기에 (a) 파이프라인이 만들어 내는 derived feature, (b) 라벨/메타 컬럼을 합쳐
#      mapping selectbox · 권장 컬럼 누락 경고 · 원본 데이터 미리보기에서 모두 제외한다.
#      (data_uploader._render_review_with_preview에서 import하여 동일 기준으로 필터)
AUTO_HIDDEN_SOURCE_COLUMNS = SYNTHETIC_ONLY_COLUMNS | frozenset(
    {
        # Derived feature columns created by the pipeline. They are not mapping inputs.
        "amount_open",
        "is_cleared",
        "settlement_status",
        "settlement_date",
        "description_quality",
        "exceeds_threshold",
        "is_near_threshold",
        "near_threshold_amount",
        "near_threshold_limit_amount",
        "near_threshold_limit_resolved",
        "near_threshold_ratio_to_limit",
        "near_threshold_gap_amount",
        "near_threshold_gap_ratio",
        "near_threshold_bucket",
        "document_approval_amount",
        "approver_limit_amount",
        "approval_limit_resolved",
        "approver_can_approve_je",
        "approval_excess_amount",
        "approval_excess_ratio",
        "approval_excess_bucket",
        "amount_zscore",
        "amount_zscore_log",
        "amount_magnitude",
        "is_round_number",
        "is_manual_je",
        "is_intercompany",
        "is_revenue_account",
        "first_digit",
        "is_suspense_account",
        "description_line_missing",
        "description_header_missing",
        "description_both_missing",
        "description_line_missing_header_present",
        "description_is_missing_or_corrupted",
        "has_risk_keyword",
        "morpheme_tokens",
        # Analysis/database metadata columns that may appear after re-export.
        "anomaly_score",
        "risk_level",
        "flagged_rules",
        "review_rules",
        "supervised_score",
        "unsupervised_score",
        "duplicate_score",
        "supervised_model_id",
        "unsupervised_model_id",
        "duplicate_model_id",
        "ml_scored_at",
        "upload_batch_id",
    }
)

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
    "header_text": "전표헤더적요",
    "created_by": "작성자",
    "user_persona": "사용자유형",
    "source": "전표출처",
    "business_process": "업무프로세스",
    "ledger": "원장",
    "approved_by": "승인자",
    "approval_date": "승인일자",
    "line_number": "라인번호",
    "local_amount": "원화금액",
    "cost_center": "코스트센터",
    "profit_center": "이익센터",
    "line_text": "라인적요",
    "tax_code": "세금코드",
    "tax_amount": "세금금액",
    "trading_partner": "거래처",
    "auxiliary_account_number": "보조계정번호",
    "auxiliary_account_label": "보조계정명",
    "lettrage": "반제그룹",
    "lettrage_date": "반제일자",
    "anomaly_type": "이상유형",
    "fraud_type": "부정유형",
    "is_fraud": "부정여부",
    "is_anomaly": "이상여부",
    "sod_violation": "SoD위반",
    "sod_conflict_type": "SoD충돌유형",
    "has_attachment": "증빙첨부여부",
    "supporting_doc_type": "증빙유형",
    "delivery_date": "납품일",
    "invoice_amount": "세금계산서금액",
    "supply_amount": "공급가액",
    "ip_address": "접근IP",
    "document_number": "문서번호",
}

# Why: 권장 컬럼 미매핑 시 어떤 감사 검사가 누락되는지 사용자가 바로 알 수 있도록
#      schema.yaml 주석 + DETECTION_RULES.md를 기반으로 요약한다.
_COLUMN_IMPACT: dict[str, str] = {
    "currency": "다통화 전표·환율 이상 탐지 불가",
    "exchange_rate": "환율 검증·재환산 정합성 확인 불가",
    "reference": "매입/매출 매칭·순환 거래 탐지 약화",
    "header_text": "위험 적요 키워드·취소 전표 탐지 약화 (L3-09)",
    "created_by": "자기승인·SoD·권한 위반 탐지 불가 (L1-05/L1-06/L3-02)",
    "user_persona": "Junior 권한 초과·수기전표 판정 약화 (L3-02)",
    "source": "수기/자동 전표 구분 불가 → L3-02 수기전표 탐지 약화",
    "business_process": "프로세스별(P2P/O2C/R2R) 위험 룰 적용 불가",
    "ledger": "원장 구분 없이 전체 집계 → 보조원장 분리 불가",
    "approved_by": "자기승인·승인자 SoD 충돌 탐지 불가 (L1-05)",
    "approval_date": "승인 지연·야간 승인 이상 탐지 불가",
    "line_number": "라인 단위 검증(부분 분개) 약화",
    "local_amount": "외화 전표 재환산 정합성 검증 불가",
    "cost_center": "부서별 권한·집계 이상 탐지 약화",
    "profit_center": "세그먼트 분석·이익센터 간 거래 탐지 불가",
    "line_text": "위험 적요·키워드 탐지(L3-09) 불가",
    "tax_code": "부가세·면세/영세율 구분 검증 불가",
    "tax_amount": "부가세 정합성(공급가액 ×10%) 검증 불가",
    "trading_partner": "관계사 거래 검토(L3-03)·그래프 순환 탐지 약화",
    "auxiliary_account_number": "보조원장 대사·세부 계정 분석 불가",
    "auxiliary_account_label": "보조원장 라벨 분석 불가",
    "lettrage": "반제(대사) 미완결 거래 탐지 불가",
    "lettrage_date": "반제 지연 이상 탐지 불가",
    "has_attachment": "증빙 누락 전표 탐지 불가 (WU-14)",
    "supporting_doc_type": "증빙 유형별(세금계산서/발주서 등) 검증 불가",
    "delivery_date": "컷오프(기말 매출/매입) 검증 약화",
    "invoice_amount": "세금계산서 금액 정합성 검증 불가",
    "supply_amount": "공급가액-부가세 정합성 검증 불가",
    "ip_address": "접근 IP 이상·비인가 접속 탐지 불가 (WU-15)",
    "document_number": "전표번호 순서·누락 검사 불가",
    "document_date": "증빙일-전기일 시간차 이상 탐지 불가",
    "fiscal_period": "회계기간 집계·기말 분개 탐지 약화",
}


def _get_required_columns(schema: dict) -> set[str]:
    return {col["name"] for col in schema.get("columns", []) if col.get("required", False)}


def _get_recommended_columns(schema: dict) -> set[str]:
    # Why: 권장 컬럼은 (1) 실제 고객 CSV에 존재할 수 있고 (2) 미매핑 시 약화되는
    #      구체적인 감사 검사가 정의된 컬럼만 의미가 있다. _COLUMN_IMPACT에 영향
    #      문구가 등록되지 않은 optional 컬럼(amount_open, settlement_status 등
    #      "연관 검사 정보 없음"으로 노출되던 항목)은 권장에서 제외한다.
    return {
        col["name"]
        for col in schema.get("columns", [])
        if not col.get("required", False)
        and not col.get("is_label", col.get("type") == "bool")
        and col["name"] not in SYNTHETIC_ONLY_COLUMNS
        and col["name"] in _COLUMN_IMPACT
    }


def _get_all_standard_columns(schema: dict) -> list[str]:
    # Why: selectbox 후보에서도 합성 전용 컬럼을 제외해 실제 CSV에 없는 타깃 매핑을 막는다.
    return sorted(
        col["name"]
        for col in schema.get("columns", [])
        if not col.get("is_label", col.get("type") == "bool")
        and col["name"] not in SYNTHETIC_ONLY_COLUMNS
    )


def _split_visible_and_hidden_mappings(
    source_columns: list[str],
    mapping_result,
) -> tuple[dict[str, str], dict[str, str]]:
    """Split editable mappings from auto-preserved label mappings."""
    combined = {**mapping_result.mapping, **mapping_result.suggestions}
    visible: dict[str, str] = {}
    hidden: dict[str, str] = {}

    for source in source_columns:
        target = combined.get(source)
        if target is None:
            continue
        if str(target) in LABEL_COLUMNS:
            hidden[source] = target
        else:
            visible[source] = target

    return visible, hidden


def _is_auto_hidden_source_column(column_name: str) -> bool:
    normalized = str(column_name).strip().lower()
    return normalized in AUTO_HIDDEN_SOURCE_COLUMNS or normalized.startswith("_")


def _display_name(column_name: str) -> str:
    label = _COLUMN_LABELS.get(column_name)
    if label:
        return f"{label} ({column_name})"
    return column_name


def _refresh_taken(
    source_columns: list[str],
    selected_map: dict[str, str],
    current_source: str,
) -> set[str]:
    return {
        target
        for source, target in selected_map.items()
        if source != current_source and source in source_columns and target != "(무시)"
    }


# Why: 컬럼 diff 렌더링은 data_uploader._render_column_diff_section()으로 이동.
#      매핑 리뷰 UI는 "지금 매핑" 상태에만 집중하고, 이전 업로드와의 비교는
#      데이터 미리보기 아래 별도 섹션으로 분리한다.


def render_mapping_review() -> None:
    """왼쪽 column 전용 — 제목 + selectbox 에디터만 렌더링.

    요약/버튼/진행률은 좌우 분할 바깥 풀 폭에서 render_mapping_footer()가 담당.
    """
    mapping_result = st.session_state.get(KEY_INGEST_MAPPING_RESULT)
    read_result = st.session_state.get(KEY_INGEST_READ_RESULT)
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])

    if mapping_result is None or not source_columns:
        st.warning("매핑 결과가 없습니다. 파일을 다시 업로드해 주세요.")
        if st.button("업로드로 돌아가기"):
            _clear_and_reset()
        return

    schema = get_schema()
    required_cols = _get_required_columns(schema)
    recommended_cols = _get_recommended_columns(schema)
    all_standard = _get_all_standard_columns(schema)

    st.subheader("컬럼 매핑 확인")
    if read_result is not None:
        selected_sheet = (
            st.session_state.get(KEY_INGEST_SELECTED_SHEET, read_result.active_sheet) or "-"
        )
        st.caption(f"형식: {read_result.source_format.upper()} | 시트: {selected_sheet}")

    visible_map, hidden_label_map = _split_visible_and_hidden_mappings(
        source_columns,
        mapping_result,
    )
    editable_sources = [
        src
        for src in source_columns
        if src not in hidden_label_map and not _is_auto_hidden_source_column(src)
    ]
    selected_map = {src: visible_map.get(src, "(무시)") for src in editable_sources}

    _render_mapping_editor(
        source_columns=editable_sources,
        selected_map=selected_map,
        all_standard=all_standard,
        required_cols=required_cols,
        recommended_cols=recommended_cols,
    )

    # footer가 동일 rerun 사이클 내에서 읽어 요약·버튼을 렌더
    st.session_state["_pending_mapping_selection"] = selected_map
    st.session_state["_pending_hidden_label_map"] = hidden_label_map


def render_mapping_footer() -> None:
    """풀 폭 영역 — 매핑 요약 + 확인/취소 버튼 + 준비 단계 progress.

    Why: 좌우 분할의 왼쪽 column(30%)은 좁아 요약/버튼/spinner 텍스트가 두 줄로
         잘린다. 좌우 분할 바깥 풀 폭 영역에서 렌더하여 한 줄에 담기도록 한다.
    """
    mapping_result = st.session_state.get(KEY_INGEST_MAPPING_RESULT)
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    selected_map = st.session_state.get("_pending_mapping_selection")
    hidden_label_map = st.session_state.get("_pending_hidden_label_map", {}) or {}
    if mapping_result is None or not source_columns or selected_map is None:
        return

    schema = get_schema()
    required_cols = _get_required_columns(schema)
    recommended_cols = _get_recommended_columns(schema)

    final_mapping = {
        source: target for source, target in selected_map.items() if target != "(무시)"
    }
    final_mapping.update(hidden_label_map)
    mapped_targets = set(final_mapping.values())
    still_missing = sorted(required_cols - mapped_targets)
    missing_recommended = sorted(recommended_cols - mapped_targets)

    _render_mapping_summary(
        final_mapping=final_mapping,
        still_missing=still_missing,
        missing_recommended=missing_recommended,
    )

    prep_warns = st.session_state.get(KEY_INGEST_PREP_WARNINGS, [])
    btn_confirm, btn_cancel, _spacer = st.columns([1, 1, 6])

    with btn_confirm:
        confirm_clicked = st.button(
            "매핑 확인",
            type="primary",
            disabled=bool(still_missing),
            width="stretch",
            key="mapping_confirm_btn",
        )

    with btn_cancel:
        if st.button("취소", width="stretch", key="mapping_cancel_btn"):
            _clear_and_reset()

    if confirm_clicked:
        updated = dc_replace(mapping_result, mapping=final_mapping)
        st.session_state[KEY_INGEST_MAPPING_RESULT] = updated
        _save_mapping_profile(updated)
        _try_learn_keywords(final_mapping)

        file_key = st.session_state.get("_ingest_file_key", "")
        # Why: spinner/progress 를 버튼 column(1/8 폭) 안에서 렌더하면 텍스트가
        #      여러 줄로 잘린다. 풀 폭 placeholder 를 클릭 시점에만 만들고 그 안에
        #      그린다. 클릭 전에 미리 깔면 빈 박스 잔상이 남는다.
        progress_area = st.empty()
        with progress_area.container():
            with st.spinner("매핑 확인 후 준비 단계를 실행하는 중..."):
                from dashboard.components.mapping_finalize import prepare_mapped_data

                progress = st.progress(0, text="준비 작업 시작...")

                def _progress_cb(pct: float, msg: str) -> None:
                    progress.progress(int(max(0.0, min(pct, 1.0)) * 100), text=msg)

                prepare_mapped_data(file_key, progress_cb=_progress_cb)
                progress.progress(100, text="준비 완료")
        # Why: prepare_mapped_data 가 stage 를 "UPLOAD" 로 리셋하고 KEY_PREP_RESULT
        #      를 채운 직후 즉시 rerun 해 _render_main 이 결과 페이지로 자동 전환
        #      되게 한다. 별도 "결과 보기" 클릭을 강제하지 않는다.
        st.toast("매핑이 확정되었습니다.", icon="✅")
        st.rerun()
    for warn in prep_warns:
        st.caption(f"- {warn}")


def _render_mapping_editor(
    *,
    source_columns: list[str],
    selected_map: dict[str, str],
    all_standard: list[str],
    required_cols: set[str],
    recommended_cols: set[str],
) -> None:
    """원본 컬럼별 selectbox를 1열로 나열. 샘플값은 우측 sticky 미리보기에서 참조."""
    st.caption(f"원본 컬럼 {len(source_columns)}개")

    for source in source_columns:
        taken = _refresh_taken(source_columns, selected_map, source)
        current_value = selected_map.get(source, "(무시)")
        candidates = [
            column for column in all_standard if column not in taken or column == current_value
        ]
        ordered_candidates = _sort_candidates(candidates, required_cols, recommended_cols)
        options = ["(무시)"] + ordered_candidates
        if current_value not in options:
            options.append(current_value)

        default_index = options.index(current_value) if current_value in options else 0
        chosen = st.selectbox(
            source,
            options,
            index=default_index,
            format_func=_display_name,
            key=f"mapping_select_{source}",
        )
        selected_map[source] = chosen


def _sort_candidates(
    candidates: list[str],
    required_cols: set[str],
    recommended_cols: set[str],
) -> list[str]:
    req = sorted(col for col in candidates if col in required_cols)
    rec = sorted(col for col in candidates if col in recommended_cols and col not in required_cols)
    etc = sorted(
        col for col in candidates if col not in required_cols and col not in recommended_cols
    )
    return req + rec + etc


def _sample_values(source: str, limit: int = 3) -> str:
    data_df = st.session_state.get(KEY_INGEST_DATA_DF)
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    if data_df is None or source not in source_columns:
        return ""

    idx = source_columns.index(source)
    if idx >= data_df.shape[1]:
        return ""

    series = data_df.iloc[:, idx].dropna()
    if series.empty:
        return ""

    values = [str(value)[:30] for value in series.astype(str).unique()[:limit]]
    return ", ".join(values)


def _render_mapping_summary(
    *,
    final_mapping: dict[str, str],
    still_missing: list[str],
    missing_recommended: list[str],
) -> None:
    """매핑 요약 — 확정 개수 1줄 + 상태 배지 + 접기식 상세.

    Why: 필수/권장이 모두 충족된 경우에도 metric 3개가 나열되어 UI가 지저분했다.
         상태는 하나의 배지로, 세부 누락은 expander로 모아 시각적 잡음을 줄인다.
    """
    st.caption(f"확정 매핑 **{len(final_mapping)}개**")

    # ── 상태 배지: 필수 누락 > 권장 미매핑 > 완벽 ──
    if still_missing:
        st.error(f"필수 컬럼 누락 {len(still_missing)}건 — 매핑 후 진행해 주세요")
        with st.expander(f"필수 누락 {len(still_missing)}건", expanded=True):
            _render_missing_columns_with_impact(still_missing, level="required")
    elif missing_recommended:
        st.info(f"필수 컬럼 모두 매핑 완료 · 권장 컬럼 미매핑 {len(missing_recommended)}건")
        with st.expander(f"권장 컬럼 미매핑 {len(missing_recommended)}건", expanded=False):
            st.caption(
                "미매핑 시 아래 검사가 누락/약화됩니다. "
                "원본에 해당 컬럼이 있다면 좌측에서 매핑해 주세요."
            )
            _render_missing_columns_with_impact(missing_recommended, level="recommended")
    else:
        st.success("필수·권장 컬럼이 모두 매핑되었습니다.")


def _render_missing_columns_with_impact(
    columns: list[str],
    *,
    level: str = "recommended",
) -> None:
    """누락 컬럼을 "컬럼명 | 영향 검사" 2열 표 형태로 렌더링."""
    if not columns:
        return

    # Why: st.dataframe은 폭을 맞춰 주지만 개별 셀 강조가 어렵고,
    #      markdown 표는 컬럼명 특수문자(`_`) 이스케이프 번거로움.
    #      columns([2, 3])로 그리드처럼 정렬 + 가독성 확보.
    header_col, impact_col = st.columns([2, 3])
    with header_col:
        st.markdown("**컬럼**")
    with impact_col:
        st.markdown("**영향받는 검사**")

    for column in columns:
        left, right = st.columns([2, 3])
        with left:
            st.markdown(f"- {_display_name(column)}")
        with right:
            impact = _COLUMN_IMPACT.get(column, "연관 검사 정보 없음")
            st.caption(impact)


def _save_mapping_profile(mapping_result) -> None:
    source_columns = st.session_state.get(KEY_INGEST_SOURCE_COLUMNS, [])
    read_result = st.session_state.get(KEY_INGEST_READ_RESULT)
    if not source_columns:
        return

    try:
        from src.ingest.mapping_profile import save_profile

        ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
        profile_dir = ctx.profile_dir if ctx and not ctx.is_anonymous else None
        fiscal_year = getattr(ctx, "fiscal_year", None) if ctx else None
        save_profile(
            mapping_result,
            source_columns,
            source_name=st.session_state.get(KEY_UPLOAD_COUNT, "")
            or st.session_state.get("_ingest_file_key", ""),
            source_format=read_result.source_format if read_result is not None else "",
            header_row=0,
            fiscal_year=fiscal_year,
            profile_dir=profile_dir,
        )
    except Exception:
        logger.warning("mapping profile save failed", exc_info=True)


def _try_learn_keywords(final_mapping: dict[str, str]) -> None:
    if not final_mapping:
        return

    ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    if ctx is None or ctx.is_anonymous:
        return

    try:
        from src.ingest.keyword_learner import learn_from_mapping

        repo = st.session_state.get("_company_repo")
        if repo is None:
            return

        company_keywords = repo.load_company_keywords(ctx.company_id)
        updated_keywords = learn_from_mapping(final_mapping, company_keywords, get_keywords())
        if updated_keywords is None:
            return

        repo.save_company_keywords(ctx.company_id, updated_keywords)
        profile = repo.get_company(ctx.company_id)
        if not profile.has_custom_keywords:
            profile.has_custom_keywords = True
            repo.update_company(profile)
    except Exception:
        logger.warning("keyword learning failed", exc_info=True)


def _clear_and_reset() -> None:
    close_dashboard_connections(st.session_state)

    for key in [
        KEY_INGEST_READ_RESULT,
        KEY_INGEST_MAPPING_RESULT,
        KEY_INGEST_SHEET_SCORES,
        KEY_INGEST_SELECTED_SHEET,
        KEY_INGEST_SOURCE_COLUMNS,
        KEY_INGEST_DATA_DF,
        KEY_INGEST_COLUMN_DIFF,
        KEY_INGEST_CONFIRMED,
        KEY_INGEST_PREP_WARNINGS,
        KEY_PREP_RESULT,
        KEY_PHASE1_RESULT,
        KEY_PHASE2_RESULT,
        KEY_PIPELINE_RESULT,
        "_ingest_file_key",
        "_ingest_tmp_path",
        "_ingest_is_user_path",
    ]:
        st.session_state.pop(key, None)
    st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
    st.rerun()
