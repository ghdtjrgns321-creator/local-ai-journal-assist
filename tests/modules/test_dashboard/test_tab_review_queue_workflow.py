"""WU-31 Sprint E2 — Review Queue 워크플로우 단위 테스트.

검증 포커스:
1. 사이드바 6종 필터(`apply_filters`) — 빈 입력 통과, 다중 차원 누적, NULL 처리
2. candidate_id 검색(`apply_search`) — 부분일치, 대소문자 무시, 빈 query 통과
3. 실행 계획(`compute_run_plan`) — N 자동 축소(20→10→5), budget 미적용, ladder 초과
4. 분류 저장(`register_review_decision`) — UPDATE + AuditTrail 이벤트 묶음, trail 누락 흡수
5. tab_review_queue 진입점 — narratives 비어있을 때 안내, 필터 적용, 에러 표시

순수 함수는 Streamlit 의존 없이 검증, Streamlit UI는 함수 자체를 monkeypatch로 가로채 호출 인자만 검증.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd
import pytest

from dashboard.components.review_queue_workflow import (
    DEFAULT_N_LADDER,
    EST_COST_PER_CANDIDATE_USD,
    ReviewQueueFilters,
    apply_filters,
    apply_search,
    compute_run_plan,
    register_review_decision,
)
from src.db.schema import initialize_schema
from src.export.audit_trail import AuditEvent, AuditTrail
from src.llm.review_narrator.cache import read_audit_decision, upsert_narrative
from src.llm.review_narrator.citation_validator import validate_citations
from src.llm.review_narrator.models import ReviewNarrative
from src.llm.review_narrator.narrator import NarratorResult

# ── fixtures ─────────────────────────────────────────────────


@pytest.fixture()
def rq_db_conn():
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def rq_sample_df() -> pd.DataFrame:
    """필터·검색 단위 테스트용 합성 DataFrame 5행."""
    return pd.DataFrame(
        [
            {
                "candidate_id": "CAND-001",
                "priority_rank": 1,
                "confidence": "high",
                "batch_id": "B1",
                "process": "R2R",
                "audit_decision": "confirmed_high_risk",
                "audit_note": "x",
                "cited_rule_ids": ["L1-01", "NLP03"],
            },
            {
                "candidate_id": "CAND-002",
                "priority_rank": 2,
                "confidence": "medium",
                "batch_id": "B1",
                "process": "P2P",
                "audit_decision": None,
                "audit_note": None,
                "cited_rule_ids": ["L2-04"],
            },
            {
                "candidate_id": "CAND-003",
                "priority_rank": 5,
                "confidence": "low",
                "batch_id": "B2",
                "process": "R2R",
                "audit_decision": "false_positive",
                "audit_note": "정상",
                "cited_rule_ids": [],
            },
            {
                "candidate_id": "CAND-004",
                "priority_rank": 10,
                "confidence": "high",
                "batch_id": "B2",
                "process": "O2C",
                "audit_decision": None,
                "audit_note": None,
                "cited_rule_ids": ["L1-01"],
            },
            {
                "candidate_id": "TARGET-005",
                "priority_rank": None,
                "confidence": "low",
                "batch_id": "B2",
                "process": "P2P",
                "audit_decision": "under_review",
                "audit_note": "검토 중",
                "cited_rule_ids": ["GR01"],
            },
        ]
    )


@pytest.fixture()
def seeded_candidate(rq_db_conn) -> str:
    """review_narratives에 candidate 1건 시드. update_audit_decision 호출 대상."""
    candidate = {
        "candidate_id": "CAND-WF-001",
        "journal_ref": {"journal_id": "JE-2025-0001", "batch_id": "B-WF"},
    }
    narrative = ReviewNarrative(
        candidate_id="CAND-WF-001",
        priority_rank=1,
        priority_score=0.9,
        summary="test",
        reasoning=[],
        suggested_actions=[],
        confidence="high",
    )
    citation = validate_citations(narrative, set(), set(), set())
    result = NarratorResult(
        narrative=citation.narrative,
        citation_result=citation,
        model_tier="reasoning",
        call_status="ok",
    )
    upsert_narrative(rq_db_conn, candidate, result, batch_id="B-WF")
    return "CAND-WF-001"


# ── apply_filters ────────────────────────────────────────────


class TestApplyFilters:
    def test_empty_filters_pass_all(self, rq_sample_df):
        out = apply_filters(rq_sample_df, ReviewQueueFilters())
        assert len(out) == len(rq_sample_df)

    def test_confidence_filter(self, rq_sample_df):
        out = apply_filters(rq_sample_df, ReviewQueueFilters(confidence=["high"]))
        assert set(out["candidate_id"]) == {"CAND-001", "CAND-004"}

    def test_priority_rank_max_includes_null_as_high(self, rq_sample_df):
        """priority_rank가 NaN(=9999 sentinel)인 row는 상한 5 필터에서 제외된다."""
        out = apply_filters(rq_sample_df, ReviewQueueFilters(priority_rank_max=5))
        assert set(out["candidate_id"]) == {"CAND-001", "CAND-002", "CAND-003"}

    def test_batch_filter(self, rq_sample_df):
        out = apply_filters(rq_sample_df, ReviewQueueFilters(batch_id=["B1"]))
        assert set(out["candidate_id"]) == {"CAND-001", "CAND-002"}

    def test_process_filter(self, rq_sample_df):
        out = apply_filters(rq_sample_df, ReviewQueueFilters(process=["P2P"]))
        assert set(out["candidate_id"]) == {"CAND-002", "TARGET-005"}

    def test_audit_decision_includes_unassigned_sentinel(self, rq_sample_df):
        """audit_decision=unassigned는 NULL row만 매칭."""
        out = apply_filters(rq_sample_df, ReviewQueueFilters(audit_decision=["unassigned"]))
        assert set(out["candidate_id"]) == {"CAND-002", "CAND-004"}

    def test_audit_decision_mixed_with_unassigned(self, rq_sample_df):
        out = apply_filters(
            rq_sample_df,
            ReviewQueueFilters(audit_decision=["unassigned", "false_positive"]),
        )
        assert set(out["candidate_id"]) == {"CAND-002", "CAND-003", "CAND-004"}

    def test_rule_ids_filter_intersects_cited(self, rq_sample_df):
        out = apply_filters(rq_sample_df, ReviewQueueFilters(rule_ids=["L1-01"]))
        assert set(out["candidate_id"]) == {"CAND-001", "CAND-004"}

    def test_chained_filters(self, rq_sample_df):
        """여러 필터를 누적 적용해도 정합성 유지."""
        out = apply_filters(
            rq_sample_df,
            ReviewQueueFilters(confidence=["high"], rule_ids=["L1-01"]),
        )
        assert set(out["candidate_id"]) == {"CAND-001", "CAND-004"}

    def test_empty_df_returns_empty(self):
        empty = pd.DataFrame(
            columns=[
                "candidate_id",
                "priority_rank",
                "confidence",
                "batch_id",
                "process",
                "audit_decision",
                "cited_rule_ids",
            ]
        )
        out = apply_filters(empty, ReviewQueueFilters(confidence=["high"]))
        assert out.empty


# ── apply_search ─────────────────────────────────────────────


class TestApplySearch:
    def test_empty_query_returns_all(self, rq_sample_df):
        out = apply_search(rq_sample_df, "")
        assert len(out) == len(rq_sample_df)

    def test_whitespace_query_returns_all(self, rq_sample_df):
        out = apply_search(rq_sample_df, "   ")
        assert len(out) == len(rq_sample_df)

    def test_partial_match_case_insensitive(self, rq_sample_df):
        out = apply_search(rq_sample_df, "cand-00")
        assert set(out["candidate_id"]) == {"CAND-001", "CAND-002", "CAND-003", "CAND-004"}

    def test_unique_prefix_match(self, rq_sample_df):
        out = apply_search(rq_sample_df, "TARGET")
        assert set(out["candidate_id"]) == {"TARGET-005"}

    def test_no_match_returns_empty(self, rq_sample_df):
        out = apply_search(rq_sample_df, "DOES-NOT-EXIST")
        assert out.empty


# ── compute_run_plan ─────────────────────────────────────────


class TestComputeRunPlan:
    def test_no_budget_returns_requested_n(self):
        plan = compute_run_plan(20, budget_usd=None)
        assert plan.effective_n == 20
        assert plan.capped_by_budget is False
        assert plan.estimated_cost_usd == pytest.approx(20 * EST_COST_PER_CANDIDATE_USD)

    def test_zero_budget_treated_as_none(self):
        plan = compute_run_plan(20, budget_usd=0.0)
        assert plan.effective_n == 20
        assert plan.capped_by_budget is False

    def test_budget_caps_to_ladder_step(self):
        """예산이 N=20 비용을 못 감당하면 ladder 다음 단계(10)로 축소."""
        cap_for_20 = 20 * EST_COST_PER_CANDIDATE_USD
        plan = compute_run_plan(20, budget_usd=cap_for_20 - 0.001)
        assert plan.effective_n == 10
        assert plan.capped_by_budget is True

    def test_budget_too_small_returns_zero(self):
        plan = compute_run_plan(20, budget_usd=0.001)
        assert plan.effective_n == 0
        assert plan.capped_by_budget is True
        assert plan.estimated_cost_usd == 0.0

    def test_zero_request_is_no_op(self):
        plan = compute_run_plan(0, budget_usd=10.0)
        assert plan.effective_n == 0
        assert plan.estimated_cost_usd == 0.0

    def test_ladder_default_constant(self):
        """ladder는 큰 값부터 정렬되어 budget을 만족하는 첫 값 선택."""
        # budget이 5건만 감당 가능하면 effective_n=5
        cap_for_5 = 5 * EST_COST_PER_CANDIDATE_USD
        plan = compute_run_plan(20, budget_usd=cap_for_5)
        assert plan.effective_n == 5
        assert plan.capped_by_budget is True
        assert DEFAULT_N_LADDER == (20, 10, 5)


# ── register_review_decision ────────────────────────────────


class _FakeAuditTrail:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def log(self, event: AuditEvent) -> None:
        self.events.append(event)


class TestRegisterReviewDecision:
    def test_persists_decision_and_logs_event(self, rq_db_conn, seeded_candidate):
        trail = _FakeAuditTrail()
        result = register_review_decision(
            rq_db_conn,
            candidate_id=seeded_candidate,
            decision="confirmed_high_risk",
            note="원인 증빙",
            user="auditor_a",
            audit_trail=trail,
            company_id="C001",
            engagement_id="2026",
            batch_id="B-WF",
            previous_decision=None,
        )
        assert result["updated"] is True
        stored = read_audit_decision(rq_db_conn, seeded_candidate)
        assert stored is not None
        assert stored["audit_decision"] == "confirmed_high_risk"

        assert len(trail.events) == 1
        event = trail.events[0]
        assert event.event_type == "review_decision_change"
        assert event.details["candidate_id"] == seeded_candidate
        assert event.details["new_decision"] == "confirmed_high_risk"
        assert event.details["previous_decision"] is None
        assert event.batch_id == "B-WF"

    def test_missing_audit_trail_does_not_block_save(self, rq_db_conn, seeded_candidate):
        """audit_trail=None일 때도 분류 저장은 정상 동작."""
        result = register_review_decision(
            rq_db_conn,
            candidate_id=seeded_candidate,
            decision="under_review",
            note=None,
            user="auditor_b",
            audit_trail=None,
        )
        assert result["updated"] is True
        stored = read_audit_decision(rq_db_conn, seeded_candidate)
        assert stored is not None
        assert stored["audit_decision"] == "under_review"

    def test_trail_failure_is_absorbed(self, rq_db_conn, seeded_candidate):
        """AuditTrail.log가 예외를 던져도 분류 저장은 성공."""

        class _BrokenTrail:
            def log(self, event: AuditEvent) -> None:
                raise RuntimeError("intentional fail")

        result = register_review_decision(
            rq_db_conn,
            candidate_id=seeded_candidate,
            decision="normal_exception",
            note=None,
            user="auditor_a",
            audit_trail=_BrokenTrail(),  # type: ignore[arg-type]
        )
        assert result["updated"] is True
        stored = read_audit_decision(rq_db_conn, seeded_candidate)
        assert stored is not None
        assert stored["audit_decision"] == "normal_exception"

    def test_invalid_decision_raises_before_trail(self, rq_db_conn, seeded_candidate):
        trail = _FakeAuditTrail()
        with pytest.raises(ValueError, match="invalid audit_decision"):
            register_review_decision(
                rq_db_conn,
                candidate_id=seeded_candidate,
                decision="approved",  # invalid
                note=None,
                user="auditor_a",
                audit_trail=trail,
            )
        # decision UPDATE가 발생하지 않아야 함
        stored = read_audit_decision(rq_db_conn, seeded_candidate)
        assert stored is not None
        assert stored["audit_decision"] is None  # 시드 직후 NULL 그대로
        assert trail.events == []


# ── AuditTrail EventType 확장 회귀 ───────────────────────────


class TestAuditTrailNewEventTypes:
    """Sprint E2가 추가한 EventType Literal 2종이 거부되지 않음을 검증."""

    def test_analysis_run_accepted(self, rq_db_conn):
        AuditTrail(rq_db_conn).log(
            AuditEvent(
                event_type="analysis_run",
                user_action="review queue 분석 실행",
                details={"requested_n": 20, "effective_n": 20},
                batch_id="B-ANY",
            )
        )

    def test_review_decision_change_accepted(self, rq_db_conn):
        AuditTrail(rq_db_conn).log(
            AuditEvent(
                event_type="review_decision_change",
                user_action="review queue 분류",
                details={"candidate_id": "CAND-001", "new_decision": "under_review"},
                batch_id="B-ANY",
            )
        )

    def test_invalid_event_type_still_rejected(self, rq_db_conn):
        with pytest.raises(ValueError, match="invalid event_type"):
            AuditTrail(rq_db_conn).log(
                AuditEvent(
                    event_type="delete",  # type: ignore[arg-type]
                    user_action="x",
                    batch_id="B-ANY",
                )
            )


# ── tab_review_queue 진입점 — Streamlit monkeypatch ─────────


class _StubModule:
    """st.* 함수를 가로채는 stub. 호출은 모두 무시하고 인자만 기록."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def _f(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            # 위젯에 따라 기본 반환값 — 빈 입력 가정
            if name in {"multiselect"}:
                return []
            if name in {"text_input", "text_area", "radio"}:
                return ""
            if name in {"slider", "number_input"}:
                return 1
            if name in {"button", "checkbox", "toggle"}:
                return False
            if name in {"columns"}:
                # columns(n) 또는 columns([w1, w2, ...]) 모두 처리
                spec = args[0] if args else 2
                count = (
                    spec
                    if isinstance(spec, int)
                    else (len(spec) if hasattr(spec, "__len__") else 2)
                )
                return [_DummyCtx() for _ in range(int(count))]
            if name in {"tabs"}:
                return tuple(_DummyCtx() for _ in args[0])
            return _DummyCtx()

        return _f


class _DummyCtx:
    """st.container() / cols[i] / sidebar.expander() 등이 반환하는 컨텍스트 매니저.

    Why: streamlit 위젯이 컨텍스트 매니저 형태(`with st.expander(...)`)로 쓰일 때
        본 stub이 그 자리를 안전하게 차지하려면 __enter__가 다시 ctx를 돌려주고,
        getattr로 노출되는 함수도 다음 호출에서 또 ctx를 반환해야 한다.
    """

    def __enter__(self) -> _DummyCtx:
        return self

    def __exit__(self, *_args: Any) -> None:
        pass

    def __getattr__(self, _name: str) -> Any:
        def _f(*_args: Any, **_kwargs: Any) -> _DummyCtx:
            return _DummyCtx()

        return _f


def test_render_handles_empty_narratives_gracefully(monkeypatch):
    """narratives 비어있을 때 안내 메시지 호출만 발생하고 예외 없이 반환."""
    from dashboard import tab_review_queue

    stub_st = _StubModule()
    stub_session = {}
    stub_st.session_state = stub_session  # type: ignore[attr-defined]
    stub_st.sidebar = _DummyCtx()  # type: ignore[attr-defined]
    monkeypatch.setattr(tab_review_queue, "st", stub_st)
    # narratives 없음
    tab_review_queue.render(result=None)
    # st.info가 적어도 한 번 호출되어야 함 (empty 안내)
    info_calls = [c for c in stub_st.calls if c[0] == "info"]
    assert len(info_calls) >= 1
