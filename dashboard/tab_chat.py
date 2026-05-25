"""WU-26 Chat UI 탭 — Text-to-SQL 자연어 질의 + 프리셋 12종.

하이브리드 플로우:
  1) 프리셋 버튼 클릭 → 키워드 매칭 → 즉시 SQL 실행
  2) chat_input 자유 질의 → AuditTextToSQL.ask() → preset/LLM 폴백

Streamlit 함정 대응:
  - st.write_stream 반환값을 반드시 history에 append (rerun 유실 방지)
  - DataFrame은 head(PREVIEW_ROWS)만 저장 (session OOM 방지)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_CHAT_ENGINE,
    KEY_CHAT_ENGINE_KEY,
    KEY_CHAT_HISTORY,
    KEY_CHAT_LLM_ENABLED,
    KEY_COMPANY_CONTEXT,
)
from src.export.audit_trail import AuditEvent, AuditTrail
from src.llm.prompt_presets import AUDIT_PRESETS, get_presets_by_category
from src.llm.text_to_sql import AuditTextToSQL, SQLResult, create_text_to_sql

if TYPE_CHECKING:
    from src.context import CompanyContext
    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────
PREVIEW_ROWS = 100          # Why: session_state OOM 방지 — 프리뷰 상한
CHAT_HISTORY_MAX = 20       # Why: 히스토리 무제한 누적 방지, FIFO


# ── 헬퍼 (테스트 대상) ─────────────────────────────────────────

def _truncate_preview(df: pd.DataFrame | None) -> tuple[pd.DataFrame | None, int]:
    """결과 DataFrame을 프리뷰 크기로 자르고 원본 행수 반환.

    Why: session_state에 전체 DF를 쌓으면 수회 질의만에 OOM.
    """
    if df is None:
        return None, 0
    total_rows = len(df)
    if total_rows <= PREVIEW_ROWS:
        return df.copy(), total_rows
    return df.head(PREVIEW_ROWS).copy(), total_rows


def _trim_history(history: list[dict]) -> list[dict]:
    """CHAT_HISTORY_MAX 초과 시 오래된 항목 FIFO 제거."""
    if len(history) <= CHAT_HISTORY_MAX:
        return history
    return history[-CHAT_HISTORY_MAX:]


def _format_result_caption(result: SQLResult, total_rows: int) -> str:
    """SQLResult source별 결과 설명 캡션."""
    if result.source == "failed":
        return f"실행 실패: {result.error or '알 수 없는 오류'}"
    src_label = {"preset": "프리셋", "llm": "LLM"}.get(result.source, result.source)
    if total_rows == 0:
        return f"{src_label} 실행 완료 — 결과 없음"
    if total_rows > PREVIEW_ROWS:
        return f"{src_label} 실행 완료 — {total_rows:,}건 중 상위 {PREVIEW_ROWS}건 표시"
    return f"{src_label} 실행 완료 — {total_rows:,}건"


def _build_audit_event(
    question: str,
    result: SQLResult,
    ctx: CompanyContext,
    batch_id: str | None,
) -> AuditEvent:
    """질의 1건 → AuditEvent. details에는 DF 원본 저장 금지."""
    # Why: None 값은 audit_log details JSON에서 노이즈 → 의미 있는 키만 저장
    details: dict[str, Any] = {"question": question, "sql": result.sql}
    if result.preset_key:
        details["preset_key"] = result.preset_key
    if result.error:
        details["error"] = result.error
    return AuditEvent(
        event_type="query",
        user_action=f"chat:{result.source}",
        details=details,
        batch_id=batch_id,
        company_id=ctx.company_id if not ctx.is_anonymous else None,
        engagement_id=ctx.engagement_id if not ctx.is_anonymous else None,
    )


def _append_exchange(
    question: str,
    result: SQLResult,
) -> None:
    """사용자 질문 + 어시스턴트 응답을 history에 append (OOM-safe)."""
    preview, total_rows = _truncate_preview(result.result_df)
    ss = st.session_state
    history: list[dict] = ss.get(KEY_CHAT_HISTORY, [])
    history.append({"role": "user", "content": question})
    history.append({
        "role": "assistant",
        "content": _format_result_caption(result, total_rows),
        "sql": result.sql,
        "source": result.source,
        "preset_key": result.preset_key,
        "df_preview": preview,
        "total_rows": total_rows,
        "error": result.error,
    })
    ss[KEY_CHAT_HISTORY] = _trim_history(history)


# ── 실행 로직 ──────────────────────────────────────────────────

def _get_or_create_engine(ctx: CompanyContext) -> AuditTextToSQL:
    """ctx.db_path 키로 AuditTextToSQL을 session_state에 캐싱.

    Why: `create_text_to_sql()` 생성자는 `_build_ddl_context()`로 DDL 문자열을
    매번 조립한다. 12개 프리셋 버튼 연속 클릭 시 12회 반복 → 엔진을 세션에 1회만 생성.
    ctx 변경(회사/연도 전환) 시 cache_key 불일치로 자동 재생성된다.
    """
    from src.db.connection import get_connection

    ss = st.session_state
    cache_key = str(ctx.db_path)
    if ss.get(KEY_CHAT_ENGINE_KEY) != cache_key or ss.get(KEY_CHAT_ENGINE) is None:
        conn = get_connection(cache_key)
        ss[KEY_CHAT_ENGINE] = create_text_to_sql(ctx=ctx, conn=conn)
        ss[KEY_CHAT_ENGINE_KEY] = cache_key
    return ss[KEY_CHAT_ENGINE]


def _run_query(
    question: str,
    ctx: CompanyContext,
    batch_id: str | None,
    *,
    llm_enabled: bool,
) -> SQLResult:
    """자연어 질문 → SQLResult. llm_enabled=False면 프리셋 전용 모드.

    Note: engine과 AuditTrail은 `get_connection(ctx.db_path)` 싱글턴 커넥션을
    공유한다. ask()→log() 순차 실행이 보장되므로 현재는 안전하지만, 추후 비동기
    도입 시 별도 커넥션 주입 필요.
    """
    engine = _get_or_create_engine(ctx)
    result = engine.ask(question, batch_id=batch_id, llm_enabled=llm_enabled)

    # AuditTrail 기록 (graceful — 실패해도 상위 흐름 차단하지 않음)
    try:
        AuditTrail(engine.conn).log(
            _build_audit_event(question, result, ctx, batch_id),
        )
    except Exception as exc:  # pragma: no cover — 방어적
        logger.warning("AuditTrail.log 실패: %s", exc)

    return result


# ── 렌더 컴포넌트 ──────────────────────────────────────────────

def _render_header(ctx: CompanyContext, llm_available: bool) -> None:
    """상단 상태 바: LLM 상태 배지 + toggle + 히스토리 초기화."""
    col_badge, col_toggle, col_clear = st.columns([2, 2, 1])
    with col_badge:
        if llm_available:
            st.success("LLM 사용 가능 (gpt-5.4-mini)", icon="🤖")
        else:
            st.warning("프리셋 전용 모드 — API 키 미설정", icon="🔒")
    with col_toggle:
        current = st.session_state.get(KEY_CHAT_LLM_ENABLED, False)
        new_val = st.toggle(
            "자유 질의 LLM 사용",
            value=current and llm_available,
            disabled=not llm_available,
            help="OFF: 프리셋 매칭만 / ON: 매칭 실패 시 LLM으로 SQL 생성",
        )
        st.session_state[KEY_CHAT_LLM_ENABLED] = new_val
    with col_clear:
        if st.button("히스토리 지우기", width="stretch"):
            st.session_state[KEY_CHAT_HISTORY] = []
            st.rerun()


def _render_preset_panel(ctx: CompanyContext, batch_id: str | None) -> None:
    """프리셋 12종 — 기본/프로세스 서브탭 × 3열 2행 버튼."""
    sub_basic, sub_process = st.tabs(["기본 분석", "프로세스별"])
    llm_enabled = st.session_state.get(KEY_CHAT_LLM_ENABLED, False)

    def _render_buttons(presets) -> None:
        # Why: columns(3)×2행 — 버튼 레이블이 긴 한글이라 3열이 가독성 최적
        for row_start in range(0, len(presets), 3):
            cols = st.columns(3)
            for i, preset in enumerate(presets[row_start : row_start + 3]):
                with cols[i]:
                    # Why: render() 진입 전 batch_id 검증을 거치므로 여기서는
                    # disabled 방어 불필요 — UX 일관성 위해 info 패턴으로 통일
                    if st.button(
                        preset.label,
                        key=f"preset_{preset.key}",
                        help=preset.question,
                        width="stretch",
                    ):
                        result = _run_query(
                            preset.question, ctx, batch_id,
                            llm_enabled=llm_enabled,
                        )
                        _append_exchange(preset.question, result)
                        st.rerun()

    with sub_basic:
        _render_buttons(get_presets_by_category("basic"))
    with sub_process:
        _render_buttons(get_presets_by_category("process"))


def _render_history() -> None:
    """저장된 대화 재현 — df_preview로 즉시 복원 (재쿼리 없음)."""
    history = st.session_state.get(KEY_CHAT_HISTORY, [])
    for msg in history:
        role = msg.get("role", "assistant")
        with st.chat_message(role):
            st.markdown(msg.get("content", ""))
            sql = msg.get("sql")
            if sql:
                with st.expander("실행된 SQL", expanded=False):
                    st.code(sql, language="sql")
            df_preview = msg.get("df_preview")
            if isinstance(df_preview, pd.DataFrame) and not df_preview.empty:
                st.dataframe(df_preview, width="stretch", hide_index=True)
            error = msg.get("error")
            if error and role == "assistant":
                st.error(error)


def _render_input(ctx: CompanyContext, batch_id: str) -> None:
    """chat_input 자유 질의 — 엔터 시 실행. batch_id는 render()에서 검증됨."""
    question = st.chat_input("자연어로 질문하세요 (예: 심야에 입력된 전표는?)")
    if question:
        llm_enabled = st.session_state.get(KEY_CHAT_LLM_ENABLED, False)
        with st.spinner("SQL 생성·실행 중..."):
            result = _run_query(question, ctx, batch_id, llm_enabled=llm_enabled)
        _append_exchange(question, result)
        st.rerun()


# ── 엔트리 포인트 ──────────────────────────────────────────────

def render(result: PipelineResult) -> None:  # noqa: ARG001 — 시그니처 통일
    """Chat 탭 메인 렌더. PipelineResult는 시그니처 통일을 위해만 받음."""
    ctx: CompanyContext | None = st.session_state.get(KEY_COMPANY_CONTEXT)
    batch_id: str | None = st.session_state.get(KEY_BATCH_ID)

    if ctx is None or ctx.is_anonymous:
        st.warning("회사/연도를 먼저 선택하세요.")
        return

    # Why: 배치 미선택 시 프리셋/입력 모두 의미 없음 → 패널 전체를 info로 대체해 UX 통일
    if batch_id is None:
        st.info("먼저 배치를 업로드·선택하세요.")
        return

    # Why: ctx.settings.openai_api_key 존재 여부로 LLM 가용성 표시.
    llm_available = bool(getattr(ctx.settings, "openai_api_key", None))

    _render_header(ctx, llm_available)
    st.divider()
    st.caption(f"프리셋 {len(AUDIT_PRESETS)}종 — 버튼 클릭 또는 아래에 직접 입력")
    _render_preset_panel(ctx, batch_id)
    st.divider()
    _render_history()
    _render_input(ctx, batch_id)
