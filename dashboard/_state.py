"""대시보드 session_state 키 상수 + FilterState 타입 + 초기화 헬퍼.

Why: session_state 키를 한 곳에서 관리하여 오타·충돌 방지.
     WU1~7 전체에서 import하여 일관성 유지.
"""

from __future__ import annotations

from typing import TypedDict

# ── session_state 키 상수 ──────────────────────────────────────
# Why: 'audit_' 접두사로 Streamlit 내장 위젯 키와 네임스페이스 분리.

KEY_PIPELINE_RESULT = "audit_pipeline_result"  # PipelineResult | None
KEY_PREP_RESULT = "audit_prep_result"  # PipelineResult | None
KEY_PHASE1_RESULT = "audit_phase1_result"  # PipelineResult | None
KEY_PHASE2_RESULT = "audit_phase2_result"  # PipelineResult | None
KEY_PHASE2_TRAINING_REPORT_ID = "audit_phase2_training_report_id"  # str | None
KEY_ACTIVE_RESULT_TAB = "audit_active_result_tab"  # str: dashboard result tab label
KEY_PENDING_RESULT_TAB = "audit_pending_result_tab"  # str | None: force next result tab
KEY_TOP_LEVEL_NAV = "audit_top_level_nav"  # str: st.tabs widget key for top-level page
KEY_FILTERS = "audit_filters"  # FilterState dict
KEY_DEV_MODE = "audit_dev_mode"  # bool
KEY_SETTINGS = "audit_settings"  # AuditSettings | None (WU5 슬라이더용)
KEY_BATCH_ID = "audit_batch_id"  # str | None
KEY_UPLOAD_COUNT = "audit_upload_count"  # str (file_key — 파일 변경 감지 + 파일명 표시)
KEY_SELECTED_DOC = "audit_selected_doc"  # str | None (Explorer 선택 행, rerun 복원용)
KEY_GRID_PAGE = "audit_grid_page"  # int (Explorer AgGrid 페이지, rerun 복원용)
KEY_WHITELIST_IDS = "audit_whitelist_ids"  # set[str] (현재 배치 whitelist document_id 집합)
KEY_EDA_PROFILE = "audit_eda_profile"  # EDAProfile | None

# WU5: 설정 컴포넌트 전용 키
KEY_PRESET = "audit_preset"  # str: 현재 프리셋 이름
KEY_DISABLED_RULES = "audit_disabled_rules"  # list[str]: 비활성화된 룰 코드
KEY_LAYER_WEIGHTS = "audit_layer_weights"  # dict[str, float] | None
KEY_RISK_THRESHOLDS = "audit_risk_thresholds"  # dict[str, float] | None
KEY_SETTINGS_DIRTY = "audit_settings_dirty"  # bool: 설정 변경됨 but 미적용
KEY_FEATURED_DATA = "audit_featured_data"  # pd.DataFrame | None (피처 완료 클린 DF)
KEY_PRE_ANALYSIS_SETTINGS_OPEN = "audit_pre_analysis_settings_open"  # bool

# RC-4: 회사/Engagement 컨텍스트
KEY_COMPANY_ID = "audit_company_id"  # str | None
KEY_ENGAGEMENT_ID = "audit_engagement_id"  # str | None
KEY_COMPANY_CONTEXT = "audit_company_context"  # CompanyContext | None

# Top-level dashboard pages.
PAGE_OVERVIEW = "개요"
PAGE_COMPANY_SETTINGS = "회사별 설정"
# Why: 3-surface 불변식(룰 / 분석적 검토 / VAE)을 상단 탭 라벨에 그대로 노출 (2026-07-20).
#      상수 값이 곧 탭 라벨이자 session_state 값이며, 모든 참조가 상수 import 경유라
#      값 변경이 라벨·라우팅에 일관 반영된다.
PAGE_PHASE1 = "룰 기반"
PAGE_ANALYTICAL = "분석적 검토"
PAGE_PHASE2 = "비지도(VAE)"
PAGE_PHASE_COMPARISON = "Phase1, 2 비교"
PAGE_COMPARISON = "전기 비교"
# Why: PAGE_REVIEW_QUEUE 상수는 legacy session_state / 직렬화 호환을 위해 보존하되,
# 대분류 라우팅(RESULT_PAGES)에서는 제거 — UX 가 phase1 → phase2 → 비교 → 전기 비교
# 단방향 흐름으로 통합 (사용자 결정, 2026-05-28).
PAGE_REVIEW_QUEUE = "Review Queue"
RESULT_PAGES = (
    PAGE_OVERVIEW,
    PAGE_COMPANY_SETTINGS,
    PAGE_PHASE1,
    PAGE_ANALYTICAL,
    PAGE_PHASE2,
    PAGE_PHASE_COMPARISON,
    PAGE_COMPARISON,
)

# WU7: Ingest 스테이지 관리
KEY_INGEST_STAGE = "audit_ingest_stage"  # "UPLOAD" | "REVIEW" | "PIPELINE"
KEY_INGEST_READ_RESULT = "audit_ingest_read_result"  # ReadResult | None
KEY_INGEST_MAPPING_RESULT = "audit_ingest_mapping"  # MappingResult | None
KEY_INGEST_SHEET_SCORES = "audit_ingest_sheets"  # list[SheetScore] | None
KEY_INGEST_SELECTED_SHEET = "audit_ingest_sheet"  # str | None
KEY_INGEST_SOURCE_COLUMNS = "audit_ingest_src_cols"  # list[str] | None
KEY_INGEST_DATA_DF = "audit_ingest_data_df"  # pd.DataFrame | None
KEY_INGEST_COLUMN_DIFF = "audit_ingest_column_diff"  # ColumnDiff | None
KEY_INGEST_CONFIRMED = "audit_ingest_confirmed"  # bool
KEY_INGEST_PREPARED_DF = "audit_ingest_prepared_df"  # pd.DataFrame | None
KEY_INGEST_PREP_WARNINGS = "audit_ingest_prep_warns"  # list[str]

# Batch History Loader: DB에서 로드한 결과 구분 (읽기 전용 모드)
KEY_LOADED_FROM_DB = "audit_loaded_from_db"  # bool

# WU-26: Chat UI
# Why: chat 결과를 rerun에도 유지 — DataFrame은 반드시 head(100) 프리뷰만 저장해 OOM 방지.
KEY_CHAT_HISTORY = "audit_chat_history"  # list[dict]
KEY_CHAT_LLM_ENABLED = "audit_chat_llm_enabled"  # legacy inactive Chat tab toggle
KEY_CHAT_ENGINE = "audit_chat_engine"  # AuditTextToSQL | None (ctx당 1개 캐싱)
KEY_CHAT_ENGINE_KEY = "audit_chat_engine_key"  # str: 캐시 무효화 키 (ctx.db_path)

# WU-27: Export 탭 (2-Step 캐싱)
# Why: st.download_button에 _export_to_bytes()를 직접 바인딩하면 위젯 재렌더마다
#      수십초 걸리는 Excel/PDF 생성이 헛돌아 메모리 폭주. "생성" 버튼 클릭 시에만
#      바이트를 굽고 세션에 캐싱하며, 다운로드 버튼은 캐시를 서빙한다.
#      설정(필터·옵션·포맷) 해시 불일치 시 캐시 무효화.
KEY_EXPORT_FORMAT = "audit_export_format"  # "Excel" | "PDF" | "CSV"
KEY_EXPORT_READY_DATA = "audit_export_ready_data"  # bytes | None (캐시된 생성물)
KEY_EXPORT_READY_NAME = "audit_export_ready_name"  # str | None (파일명)
KEY_EXPORT_READY_MIME = "audit_export_ready_mime"  # str | None (MIME 타입)
KEY_EXPORT_READY_HASH = "audit_export_ready_hash"  # str | None (stale 판정용)

# Legacy review queue workflow UI 상태
# Why: 분석 실행 트리거·재생성 여부·사이드바 필터·검색 박스 값을 rerun에도 유지.
#      input_hash 비교로 "재생성" 버튼을 활성/비활성 토글.
KEY_REVIEW_QUEUE_FILTERS = "audit_review_queue_filters"  # ReviewQueueFilters dict
KEY_REVIEW_QUEUE_SEARCH = "audit_review_queue_search"  # str (candidate_id 검색)
KEY_REVIEW_QUEUE_LAST_HASH = "audit_review_queue_hash"  # str | None (직전 실행 input hash)
KEY_REVIEW_QUEUE_RUN_STATUS = (
    "audit_review_queue_status"  # "idle"|"running"|"ok"|"error"|"budget_capped"
)
KEY_REVIEW_QUEUE_RUN_ERROR = "audit_review_queue_error"  # str | None (마지막 에러 메시지)
KEY_REVIEW_QUEUE_TARGET_N = "audit_review_queue_target_n"  # int (실행 대상 candidate 수)

# Legacy review queue detail state.
# Why: persisted queue rows and reviewer decision state can still be restored
#      when historical review_narratives rows exist.
KEY_REVIEW_QUEUE_NARRATIVES = "audit_review_queue_narratives"  # list[dict] | None
KEY_REVIEW_QUEUE_SELECTED_CANDIDATE = "audit_review_queue_selected_candidate"  # str | None
KEY_REVIEW_QUEUE_CITATION_TARGET = "audit_review_queue_citation_target"  # dict | None
KEY_REVIEW_QUEUE_INPUT_HASH = "audit_review_queue_input_hash"  # str | None
KEY_REVIEW_QUEUE_CANDIDATE_INDEX = "audit_review_queue_candidate_index"  # dict[str, dict]

# ── 필터 상태 타입 ──────────────────────────────────────────────


class FilterState(TypedDict, total=False):
    """사이드바 필터 상태. 빈 dict = 필터 미적용(전체 데이터).

    키가 없거나 빈 리스트이면 해당 차원 전체 통과.
    """

    # 기본 필터 4개
    date_range: tuple[str, str]  # ISO ("2022-01-01", "2022-12-31")
    risk_levels: list[str]  # ["High", "Medium", ...]
    amount_range: tuple[float, float]  # (min_amount, max_amount)
    rule_codes: list[str]  # ["L1-01", "L1-04", ...]

    # 차원 필터 6개 (st.expander 내부)
    business_processes: list[str]
    company_codes: list[str]
    user_personas: list[str]
    sources: list[str]
    document_types: list[str]
    gl_accounts: list[str]

    # 개발 모드 필터 2개 (dev_mode 활성 시)
    fraud_types: list[str]
    anomaly_types: list[str]


# ── 초기화 헬퍼 ────────────────────────────────────────────────

_DEFAULTS: dict[str, object] = {
    KEY_PIPELINE_RESULT: None,
    KEY_PREP_RESULT: None,
    KEY_PHASE1_RESULT: None,
    KEY_PHASE2_RESULT: None,
    KEY_PHASE2_TRAINING_REPORT_ID: None,
    KEY_ACTIVE_RESULT_TAB: "개요",
    KEY_PENDING_RESULT_TAB: None,
    KEY_FILTERS: {},
    KEY_DEV_MODE: False,
    KEY_SETTINGS: None,
    KEY_BATCH_ID: None,
    KEY_UPLOAD_COUNT: "",
    KEY_SELECTED_DOC: None,
    KEY_GRID_PAGE: 0,
    KEY_WHITELIST_IDS: set(),
    KEY_PRESET: "default",
    KEY_DISABLED_RULES: [],
    KEY_LAYER_WEIGHTS: None,
    KEY_RISK_THRESHOLDS: None,
    KEY_SETTINGS_DIRTY: False,
    KEY_FEATURED_DATA: None,
    KEY_PRE_ANALYSIS_SETTINGS_OPEN: False,
    KEY_EDA_PROFILE: None,
    # RC-4: Company/Engagement
    KEY_COMPANY_ID: None,
    KEY_ENGAGEMENT_ID: None,
    KEY_COMPANY_CONTEXT: None,
    # WU7: Ingest
    KEY_INGEST_STAGE: "UPLOAD",
    KEY_INGEST_READ_RESULT: None,
    KEY_INGEST_MAPPING_RESULT: None,
    KEY_INGEST_SHEET_SCORES: None,
    KEY_INGEST_SELECTED_SHEET: None,
    KEY_INGEST_SOURCE_COLUMNS: None,
    KEY_INGEST_DATA_DF: None,
    KEY_INGEST_COLUMN_DIFF: None,
    KEY_INGEST_CONFIRMED: False,
    KEY_INGEST_PREPARED_DF: None,
    KEY_INGEST_PREP_WARNINGS: [],
    # Batch History Loader
    KEY_LOADED_FROM_DB: False,
    # WU-26: Chat UI
    KEY_CHAT_HISTORY: [],
    KEY_CHAT_LLM_ENABLED: False,
    KEY_CHAT_ENGINE: None,
    KEY_CHAT_ENGINE_KEY: "",
    # WU-27: Export 탭
    KEY_EXPORT_FORMAT: "Excel",
    KEY_EXPORT_READY_DATA: None,
    KEY_EXPORT_READY_NAME: None,
    KEY_EXPORT_READY_MIME: None,
    KEY_EXPORT_READY_HASH: None,
    # Legacy review queue detail state
    KEY_REVIEW_QUEUE_NARRATIVES: None,
    KEY_REVIEW_QUEUE_SELECTED_CANDIDATE: None,
    KEY_REVIEW_QUEUE_CITATION_TARGET: None,
    KEY_REVIEW_QUEUE_INPUT_HASH: None,
    KEY_REVIEW_QUEUE_CANDIDATE_INDEX: {},
    # Legacy review queue workflow UI
    KEY_REVIEW_QUEUE_FILTERS: {},
    KEY_REVIEW_QUEUE_SEARCH: "",
    KEY_REVIEW_QUEUE_LAST_HASH: None,
    KEY_REVIEW_QUEUE_RUN_STATUS: "idle",
    KEY_REVIEW_QUEUE_RUN_ERROR: None,
    KEY_REVIEW_QUEUE_TARGET_N: 20,
}


def init_state() -> None:
    """session_state 기본값 초기화. app.py 최상단에서 1회 호출."""
    import streamlit as st

    # Why: mutable 기본값(set, list, dict)은 복사하여 세션 간 참조 공유 방지
    for key, default in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = (
                default.copy() if isinstance(default, (set, list, dict)) else default
            )
