"""WU-26 tab_chat 헬퍼 단위 테스트.

Streamlit 렌더 코드는 직접 테스트하지 않고(기존 컨벤션 준수),
함정 대응 로직 — preview 자르기, 히스토리 FIFO, AuditEvent 매핑 — 을 검증한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from dashboard.tab_chat import (
    CHAT_HISTORY_MAX,
    PREVIEW_ROWS,
    _append_exchange,
    _build_audit_event,
    _format_result_caption,
    _run_query,
    _trim_history,
    _truncate_preview,
)
from src.llm.text_to_sql import AuditTextToSQL, SQLResult


# ── _truncate_preview ──────────────────────────────────────────

def test_truncate_preview_none_returns_zero() -> None:
    preview, total = _truncate_preview(None)
    assert preview is None
    assert total == 0


def test_truncate_preview_keeps_small_df_intact() -> None:
    df = pd.DataFrame({"x": range(10)})
    preview, total = _truncate_preview(df)
    assert total == 10
    assert len(preview) == 10


def test_truncate_preview_caps_large_df_to_preview_rows() -> None:
    # Why: OOM 방지 — 10k 행 입력이라도 session에는 100행만 남아야 함
    df = pd.DataFrame({"x": range(10_000)})
    preview, total = _truncate_preview(df)
    assert total == 10_000
    assert len(preview) == PREVIEW_ROWS


def test_truncate_preview_returns_copy_not_view() -> None:
    """프리뷰 복사본이어야 원본 수정이 세션에 영향 주지 않음."""
    df = pd.DataFrame({"x": list(range(200))})
    preview, _ = _truncate_preview(df)
    df.iloc[0, 0] = -999
    assert preview.iloc[0, 0] == 0


# ── _trim_history ──────────────────────────────────────────────

def test_trim_history_noop_when_under_limit() -> None:
    history = [{"role": "user", "content": str(i)} for i in range(5)]
    assert _trim_history(history) == history


def test_trim_history_removes_oldest_fifo() -> None:
    # Why: 오래된 대화 먼저 제거되어야 최근 컨텍스트 유지
    history = [{"i": i} for i in range(CHAT_HISTORY_MAX + 3)]
    trimmed = _trim_history(history)
    assert len(trimmed) == CHAT_HISTORY_MAX
    assert trimmed[0] == {"i": 3}
    assert trimmed[-1] == {"i": CHAT_HISTORY_MAX + 2}


# ── _format_result_caption ─────────────────────────────────────

def test_format_caption_failed_shows_error() -> None:
    r = SQLResult(sql="", result_df=None, source="failed", error="SQL 검증 실패")
    assert "SQL 검증 실패" in _format_result_caption(r, 0)


def test_format_caption_preset_with_rows() -> None:
    r = SQLResult(sql="SELECT 1", result_df=pd.DataFrame({"x": [1]}),
                  source="preset", preset_key="high_risk_overview")
    msg = _format_result_caption(r, 1)
    assert "프리셋" in msg
    assert "1" in msg


def test_format_caption_truncated_indicates_cap() -> None:
    r = SQLResult(sql="SELECT 1", result_df=pd.DataFrame({"x": [1]}),
                  source="llm")
    msg = _format_result_caption(r, 5000)
    assert "5,000" in msg
    assert str(PREVIEW_ROWS) in msg


def test_format_caption_empty_result() -> None:
    r = SQLResult(sql="SELECT 1", result_df=pd.DataFrame(), source="preset")
    assert "결과 없음" in _format_result_caption(r, 0)


# ── _build_audit_event ─────────────────────────────────────────

def _fake_ctx(anonymous: bool = False):
    ctx = MagicMock()
    ctx.is_anonymous = anonymous
    ctx.company_id = "C001"
    ctx.engagement_id = "2024"
    return ctx


def test_build_audit_event_maps_fields() -> None:
    ctx = _fake_ctx()
    r = SQLResult(sql="SELECT * FROM general_ledger WHERE upload_batch_id=?",
                  result_df=pd.DataFrame(), source="preset",
                  preset_key="weekend_midnight")
    event = _build_audit_event("심야 전표?", r, ctx, batch_id="B1")
    assert event.event_type == "query"
    assert event.user_action == "chat:preset"
    assert event.batch_id == "B1"
    assert event.company_id == "C001"
    assert event.engagement_id == "2024"
    assert event.details["question"] == "심야 전표?"
    assert event.details["preset_key"] == "weekend_midnight"


def test_build_audit_event_excludes_dataframe_from_details() -> None:
    # Why: details는 JSON 직렬화되어 audit_log에 들어감 → DF 원본 들어가면 OOM/폭주
    ctx = _fake_ctx()
    big_df = pd.DataFrame({"x": range(10_000)})
    r = SQLResult(sql="SELECT 1", result_df=big_df, source="llm")
    event = _build_audit_event("질문", r, ctx, batch_id="B1")
    for value in event.details.values():
        assert not isinstance(value, pd.DataFrame)


def test_build_audit_event_omits_none_keys() -> None:
    # Why: audit_log details JSON에 None 키는 노이즈 → 의미 있는 값만 저장
    ctx = _fake_ctx()
    r_clean = SQLResult(sql="SELECT 1", result_df=pd.DataFrame(),
                        source="llm", preset_key=None, error=None)
    event = _build_audit_event("q", r_clean, ctx, batch_id="B1")
    assert "preset_key" not in event.details
    assert "error" not in event.details
    assert "question" in event.details
    assert "sql" in event.details


def test_build_audit_event_anonymous_ctx_no_ids() -> None:
    ctx = _fake_ctx(anonymous=True)
    r = SQLResult(sql="", result_df=None, source="failed", error="e")
    event = _build_audit_event("q", r, ctx, batch_id=None)
    assert event.company_id is None
    assert event.engagement_id is None


# ── _append_exchange (session_state 주입) ──────────────────────

def test_append_exchange_stores_preview_only(monkeypatch) -> None:
    """세션 쓰기 동작 — DataFrame 원본이 아닌 head(100) 프리뷰만 저장."""
    fake_state: dict = {"audit_chat_history": []}
    import dashboard.tab_chat as tc

    monkeypatch.setattr(tc.st, "session_state", fake_state)

    big_df = pd.DataFrame({"x": range(500)})
    r = SQLResult(sql="SELECT 1", result_df=big_df, source="preset",
                  preset_key="k")
    _append_exchange("질문", r)

    history = fake_state["audit_chat_history"]
    assert len(history) == 2  # user + assistant
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    # OOM 방어 검증
    assert len(history[1]["df_preview"]) == PREVIEW_ROWS
    assert history[1]["total_rows"] == 500


def test_append_exchange_triggers_fifo_trim(monkeypatch) -> None:
    fake_state: dict = {
        "audit_chat_history": [{"i": i} for i in range(CHAT_HISTORY_MAX)]
    }
    import dashboard.tab_chat as tc

    monkeypatch.setattr(tc.st, "session_state", fake_state)

    r = SQLResult(sql="SELECT 1", result_df=pd.DataFrame({"x": [1]}),
                  source="preset")
    _append_exchange("새 질문", r)

    history = fake_state["audit_chat_history"]
    assert len(history) == CHAT_HISTORY_MAX
    # 가장 오래된 항목은 밀려나야 함
    assert history[-1]["role"] == "assistant"


# ── _run_query (실제 AuditTextToSQL + in-memory DuckDB) ────────

@pytest.fixture
def real_engine_fixture(monkeypatch):
    """실제 AuditTextToSQL 인스턴스 + in-memory DuckDB.

    Why (review #7): MagicMock은 @property lazy init 재초기화 경로를 흉내내지
    못해 `engine._client = None` 우회의 실패를 검출할 수 없었다.
    실제 클래스로 `llm_enabled=False` 경로가 진짜로 LLM을 우회하는지 검증한다.
    """
    import duckdb

    import dashboard.tab_chat as tc

    # 최소 DDL — 프리셋 실행 경로 검증용
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE general_ledger (
            document_id VARCHAR, upload_batch_id VARCHAR,
            debit_amount DOUBLE DEFAULT 0, credit_amount DOUBLE DEFAULT 0,
            risk_level VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE audit_log (
            id INTEGER, action VARCHAR, batch_id VARCHAR,
            company_id VARCHAR, engagement_id VARCHAR,
            details JSON, created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # LLM 자동 생성 차단 — 키가 있어도 실제 OpenAI 호출 금지
    def _no_client(self):  # noqa: ANN001
        return None
    monkeypatch.setattr(AuditTextToSQL, "_try_get_client", _no_client)

    ctx = _fake_ctx()
    ctx.db_path = ":memory:"
    ctx.settings = MagicMock(openai_api_key="fake-key",
                             openai_light_model="gpt-test")

    engine = AuditTextToSQL(ctx=ctx, client=None, conn=conn)

    # ctx 기반 엔진 캐싱을 우회 — 방금 만든 인스턴스 주입
    monkeypatch.setattr(tc, "_get_or_create_engine", lambda _ctx: engine)

    # AuditTrail도 실제 커넥션 사용 (record_event graceful 실패 허용)
    return engine, ctx, conn


def test_run_query_llm_off_blocks_llm_generation(real_engine_fixture) -> None:
    """llm_enabled=False면 프리셋 미매칭 시 LLM 호출 없이 failed 반환."""
    engine, ctx, _conn = real_engine_fixture

    # 프리셋 키워드가 없는 질문 → LLM 경로 진입 시도
    result = _run_query(
        "완전히 매칭 안되는 이상한 질문 xyz",
        ctx, batch_id="B1", llm_enabled=False,
    )

    assert result.source == "failed"
    assert "LLM 비활성" in (result.error or "")


def test_run_query_llm_on_preset_match_skips_llm(real_engine_fixture) -> None:
    """프리셋 매칭되면 llm_enabled 여부와 무관하게 프리셋 실행."""
    engine, ctx, _conn = real_engine_fixture

    result = _run_query(
        "고위험 전표 보여줘",  # 키워드 '고위험' → high_risk_overview 매칭
        ctx, batch_id="B1", llm_enabled=True,
    )

    assert result.source == "preset"
    assert result.preset_key == "high_risk_overview"


def test_run_query_audit_failure_does_not_raise(real_engine_fixture, monkeypatch) -> None:
    """AuditTrail 실패는 graceful — 사용자 질의 결과는 반환되어야 함."""
    import dashboard.tab_chat as tc

    engine, ctx, _conn = real_engine_fixture

    fake_trail = MagicMock()
    fake_trail.log.side_effect = RuntimeError("DB 연결 실패")
    monkeypatch.setattr(tc, "AuditTrail", lambda _c: fake_trail)

    result = _run_query("고위험 전표?", ctx, batch_id="B1", llm_enabled=True)

    assert result.source == "preset"


# ── _get_or_create_engine (캐싱 동작) ──────────────────────────

def test_engine_cache_reuses_instance_for_same_ctx(monkeypatch) -> None:
    """동일 ctx.db_path에 대해 엔진 인스턴스를 재사용해야 함 (DDL 재계산 방지)."""
    import dashboard.tab_chat as tc

    fake_state: dict = {}
    monkeypatch.setattr(tc.st, "session_state", fake_state)
    monkeypatch.setattr("src.db.connection.get_connection", lambda _p: MagicMock())

    call_count = {"n": 0}

    def _factory(**kw):  # noqa: ANN001
        call_count["n"] += 1
        return MagicMock(name=f"engine_{call_count['n']}")

    monkeypatch.setattr(tc, "create_text_to_sql", _factory)

    ctx = _fake_ctx()
    ctx.db_path = "/tmp/a.db"

    e1 = tc._get_or_create_engine(ctx)
    e2 = tc._get_or_create_engine(ctx)
    assert e1 is e2
    assert call_count["n"] == 1


def test_engine_cache_rebuilds_on_ctx_change(monkeypatch) -> None:
    """ctx 변경(회사/연도 전환) 시 엔진 재생성 필요."""
    import dashboard.tab_chat as tc

    fake_state: dict = {}
    monkeypatch.setattr(tc.st, "session_state", fake_state)
    monkeypatch.setattr("src.db.connection.get_connection", lambda _p: MagicMock())
    monkeypatch.setattr(tc, "create_text_to_sql",
                        lambda **kw: MagicMock(name=f"engine_{kw}"))

    ctx1 = _fake_ctx()
    ctx1.db_path = "/tmp/company_A.db"
    ctx2 = _fake_ctx()
    ctx2.db_path = "/tmp/company_B.db"

    e1 = tc._get_or_create_engine(ctx1)
    e2 = tc._get_or_create_engine(ctx2)
    assert e1 is not e2
