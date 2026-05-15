"""Review Queue Narrator 탭 — Sprint E1 (렌더링) + Sprint E2 (워크플로우).

세션에 적재된 Narrator 출력(`KEY_REVIEW_QUEUE_NARRATIVES`)을 priority_rank 순으로
카드 렌더하고, 우측에 citation 점프 패널을 함께 그린다(E1). 본 탭은 Sprint E2에서
사이드바 필터, 검색, 실행 트리거(예산 가드 포함), 분류 라디오·메모 저장, AuditTrail
이벤트 기록을 추가로 처리한다.

캐시 무효화:
- 호출부에서 candidate 입력 해시(`KEY_REVIEW_QUEUE_INPUT_HASH`)를 갱신하면 카드
  자체는 자연 재렌더된다.
- 본 모듈은 해시가 바뀐 시점에 한해 selected_candidate / citation_target 세션
  키를 비워 직전 점프 표적이 새 데이터에 매달려 있지 않도록 보장한다.
- 재생성 버튼은 직전 실행 해시(`KEY_REVIEW_QUEUE_LAST_HASH`)와 비교해 활성/비활성.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_REVIEW_QUEUE_CITATION_TARGET,
    KEY_REVIEW_QUEUE_FILTERS,
    KEY_REVIEW_QUEUE_INPUT_HASH,
    KEY_REVIEW_QUEUE_LAST_HASH,
    KEY_REVIEW_QUEUE_NARRATIVES,
    KEY_REVIEW_QUEUE_RUN_ERROR,
    KEY_REVIEW_QUEUE_RUN_STATUS,
    KEY_REVIEW_QUEUE_SEARCH,
    KEY_REVIEW_QUEUE_SELECTED_CANDIDATE,
    KEY_REVIEW_QUEUE_TARGET_N,
)
from dashboard.components.review_narrator import render_candidate_card
from dashboard.components.review_narrator_jump import render_citation_jump_panel
from dashboard.components.review_queue_workflow import (
    ReviewQueueFilters,
    apply_filters,
    apply_search,
    compute_run_plan,
    register_review_decision,
)
from src.export.audit_trail import AuditEvent, AuditTrail
from src.llm.review_narrator.cache import read_audit_decision

if TYPE_CHECKING:
    import duckdb

    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)

_PRIOR_HASH_KEY = "_review_queue_prior_hash"

DECISION_OPTIONS: list[tuple[str | None, str]] = [
    (None, "미분류"),
    ("confirmed_high_risk", "고위험 확정"),
    ("under_review", "검토 중"),
    ("normal_exception", "정상 예외"),
    ("false_positive", "오탐 (FP)"),
]
CONFIDENCE_OPTIONS: list[str] = ["high", "medium", "low"]


# ── 보조: hash 변화 시 점프 표적 리셋 ─────────────────────────


def _invalidate_jump_on_hash_change(current_hash: str | None) -> None:
    """input_hash 변경 시 점프 표적·선택 candidate 리셋.

    Why: 직전 batch의 citation 표적이 새 narratives에는 존재하지 않을 수 있다.
        해시가 바뀐 첫 렌더에서만 비우고 이후엔 사용자 선택을 유지.
    """
    prior = st.session_state.get(_PRIOR_HASH_KEY)
    if current_hash == prior:
        return
    st.session_state[_PRIOR_HASH_KEY] = current_hash
    st.session_state[KEY_REVIEW_QUEUE_CITATION_TARGET] = None
    st.session_state[KEY_REVIEW_QUEUE_SELECTED_CANDIDATE] = None


def _sorted_narratives(narratives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """priority_rank 오름차순 → 동률 시 priority_score 내림차순 → candidate_id."""
    return sorted(
        narratives,
        key=lambda n: (
            int(n.get("priority_rank") or 999),
            -float(n.get("priority_score") or 0.0),
            str(n.get("candidate_id") or ""),
        ),
    )


# ── narratives → DataFrame (필터·검색 적용용) ──────────────────


def _extract_rule_ids(narrative: dict[str, Any]) -> list[str]:
    """narrative.reasoning[].evidence에서 rule_hit 인용 rule_id 추출."""
    rule_ids: list[str] = []
    for item in narrative.get("reasoning") or []:
        for ev in item.get("evidence") or []:
            if ev.get("type") == "rule_hit" and ev.get("rule_id"):
                rule_ids.append(str(ev["rule_id"]))
    return sorted(set(rule_ids))


def _narratives_to_dataframe(
    narratives: list[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection | None,
) -> pd.DataFrame:
    """list[dict] → DataFrame + DB에서 audit_decision 4컬럼 보충.

    Why: 필터·검색은 DataFrame 연산이 단순하고 회귀 테스트가 쉽다. conn이 None이면
        분류 컬럼은 NaN으로 채워 in-memory 동작을 유지.
    """
    rows: list[dict[str, Any]] = []
    for n in narratives:
        cid = str(n.get("candidate_id") or "")
        stored: dict[str, Any] | None = None
        if conn is not None and cid:
            try:
                stored = read_audit_decision(conn, cid)
            except Exception:  # noqa: BLE001 — DB 미연결 환경 안전 처리
                stored = None
        stored = stored or {}
        rows.append(
            {
                "candidate_id": cid,
                "priority_rank": n.get("priority_rank"),
                "priority_score": n.get("priority_score"),
                "confidence": n.get("confidence") or "low",
                "summary": n.get("summary") or "",
                "batch_id": n.get("batch_id") or "",
                "process": n.get("process") or "",
                "cited_rule_ids": _extract_rule_ids(n),
                "narrative_json": n,
                "audit_decision": stored.get("audit_decision"),
                "audit_note": stored.get("audit_note"),
                "reviewed_by": stored.get("reviewed_by"),
                "reviewed_at": stored.get("reviewed_at"),
            }
        )
    return pd.DataFrame(rows)


# ── 사이드바 필터 ─────────────────────────────────────────────


def _render_sidebar_filters(df: pd.DataFrame) -> ReviewQueueFilters:
    """6종 필터 위젯. 빈 df에서도 안전(빈 옵션)."""
    ss = st.session_state
    stored = ss.get(KEY_REVIEW_QUEUE_FILTERS) or {}
    with st.sidebar.expander("Review Queue 필터", expanded=False):
        confidence = st.multiselect(
            "confidence",
            options=CONFIDENCE_OPTIONS,
            default=[c for c in stored.get("confidence", []) if c in CONFIDENCE_OPTIONS],
            key="rqf_confidence",
        )
        if not df.empty and bool(pd.Series(df["priority_rank"]).notna().any()):
            max_rank = int(pd.Series(df["priority_rank"]).fillna(999).max())
        else:
            max_rank = 100
        max_rank = max(max_rank, 1)
        priority_rank_max = st.slider(
            "priority_rank 상한",
            min_value=1,
            max_value=max_rank,
            value=min(stored.get("priority_rank_max") or max_rank, max_rank),
            key="rqf_rank",
        )
        batch_options = (
            sorted(p for p in df["batch_id"].dropna().unique() if p) if not df.empty else []
        )
        batch_id = st.multiselect(
            "batch_id",
            options=batch_options,
            default=[b for b in stored.get("batch_id", []) if b in batch_options],
            key="rqf_batch",
        )
        process_options = (
            sorted(p for p in df["process"].dropna().unique() if p) if not df.empty else []
        )
        process = st.multiselect(
            "process",
            options=process_options,
            default=[p for p in stored.get("process", []) if p in process_options],
            key="rqf_process",
        )
        decision_options = ["unassigned"] + [v for v, _ in DECISION_OPTIONS if v]
        audit_decision = st.multiselect(
            "audit_decision",
            options=decision_options,
            default=[d for d in stored.get("audit_decision", []) if d in decision_options],
            key="rqf_decision",
        )
        if df.empty:
            rule_pool: list[str] = []
        else:
            rule_pool = sorted({rid for rids in df["cited_rule_ids"] for rid in rids})
        rule_ids = st.multiselect(
            "인용된 rule_id",
            options=rule_pool,
            default=[r for r in stored.get("rule_ids", []) if r in rule_pool],
            key="rqf_rule_ids",
        )
    filters = ReviewQueueFilters(
        confidence=confidence,
        priority_rank_max=priority_rank_max,
        process=process,
        batch_id=batch_id,
        audit_decision=audit_decision,
        rule_ids=rule_ids,
    )
    ss[KEY_REVIEW_QUEUE_FILTERS] = filters.__dict__
    return filters


# ── 실행 트리거 ───────────────────────────────────────────────


def _render_run_trigger(input_hash: str | None) -> None:
    """분석 실행 + 재생성 + 진행률 + budget 안내."""
    ss = st.session_state
    target_n = int(ss.get(KEY_REVIEW_QUEUE_TARGET_N) or 20)
    last_hash = ss.get(KEY_REVIEW_QUEUE_LAST_HASH)
    status = ss.get(KEY_REVIEW_QUEUE_RUN_STATUS) or "idle"

    with st.container(border=True):
        cols = st.columns([2, 1, 1, 2])
        with cols[0]:
            target_n_input = st.number_input(
                "분석 후보 수 (N)",
                min_value=1,
                max_value=100,
                value=target_n,
                step=5,
                key="rq_target_n_input",
            )
            ss[KEY_REVIEW_QUEUE_TARGET_N] = int(target_n_input)
        with cols[1]:
            budget = st.number_input(
                "예산(USD)",
                min_value=0.0,
                value=0.0,
                step=0.5,
                help="0이면 미적용",
                key="rq_budget_input",
            )
        plan = compute_run_plan(int(target_n_input), budget_usd=budget or None)
        with cols[2]:
            st.metric("예상 비용", f"${plan.estimated_cost_usd:.3f}")
            if plan.capped_by_budget:
                st.caption(f"budget으로 N={plan.effective_n}로 자동 축소")
        with cols[3]:
            run_clicked = st.button(
                "분석 실행",
                disabled=plan.effective_n == 0,
                key="rq_run_btn",
                use_container_width=True,
            )
            regen_disabled = (input_hash is None) or (last_hash == input_hash)
            regen_clicked = st.button(
                "재생성",
                disabled=regen_disabled,
                key="rq_regen_btn",
                use_container_width=True,
            )

    if run_clicked or regen_clicked:
        _trigger_analysis_run(plan, input_hash, regen=regen_clicked)

    _render_run_status(status, ss.get(KEY_REVIEW_QUEUE_RUN_ERROR))


def _trigger_analysis_run(plan: Any, input_hash: str | None, *, regen: bool) -> None:
    """실제 LLM 파이프라인 연결은 Sprint F. 본 함수는 상태·AuditTrail만 기록."""
    ss = st.session_state
    ss[KEY_REVIEW_QUEUE_RUN_STATUS] = "running"
    progress = st.progress(0, text="Narrator 실행 준비...")
    try:
        progress.progress(30, text=f"후보 {plan.effective_n}건 조립 중...")
        if plan.effective_n == 0:
            ss[KEY_REVIEW_QUEUE_RUN_STATUS] = "budget_capped"
            st.warning("예산 한도로 실행 N이 0건. 예산을 늘리거나 N을 줄여 다시 시도하세요.")
            return
        progress.progress(100, text="완료")
        ss[KEY_REVIEW_QUEUE_RUN_STATUS] = "ok"
        ss[KEY_REVIEW_QUEUE_RUN_ERROR] = None
        ss[KEY_REVIEW_QUEUE_LAST_HASH] = input_hash
        _log_analysis_run(plan, regen=regen)
        st.success(
            f"실행 완료 — N={plan.effective_n} (요청 {plan.requested_n}, "
            f"비용 ${plan.estimated_cost_usd:.3f})"
        )
    except Exception as exc:  # noqa: BLE001 — UI는 예외 흡수 후 사용자 알림
        ss[KEY_REVIEW_QUEUE_RUN_STATUS] = "error"
        ss[KEY_REVIEW_QUEUE_RUN_ERROR] = str(exc)
        st.error(f"분석 실행 실패: {exc}")
        logger.exception("review queue run failed")
    finally:
        progress.empty()


def _render_run_status(status: str, error: str | None) -> None:
    if status == "ok":
        st.caption("직전 실행: 성공")
    elif status == "budget_capped":
        st.caption("직전 실행: 예산 한도 도달")
    elif status == "error":
        st.error(f"직전 실행 실패: {error or '알 수 없는 오류'}")


def _log_analysis_run(plan: Any, *, regen: bool) -> None:
    """AuditTrail에 analysis_run 이벤트 기록 (engagement DB 연결이 있을 때만)."""
    ss = st.session_state
    ctx = ss.get(KEY_COMPANY_CONTEXT)
    if ctx is None or getattr(ctx, "is_anonymous", True):
        return
    try:
        from src.db.connection import get_connection

        conn = get_connection(str(ctx.db_path))
        AuditTrail(conn).log(
            AuditEvent(
                event_type="analysis_run",
                user_action=("review queue 재생성" if regen else "review queue 분석 실행"),
                details={
                    "requested_n": plan.requested_n,
                    "effective_n": plan.effective_n,
                    "estimated_cost_usd": plan.estimated_cost_usd,
                    "capped_by_budget": plan.capped_by_budget,
                    "regenerate": regen,
                },
                batch_id=ss.get(KEY_BATCH_ID),
                company_id=ctx.company_id,
                engagement_id=ctx.engagement_id,
            )
        )
    except Exception:  # noqa: BLE001 — 감사증적 실패가 UI를 막지 않도록
        logger.warning("AuditTrail 'analysis_run' 기록 실패", exc_info=True)


# ── 분류 위젯 ────────────────────────────────────────────────


def _render_decision_widget(
    candidate_id: str,
    *,
    prev_decision: str | None,
    prev_note: str | None,
    batch_id: str | None,
    conn: duckdb.DuckDBPyConnection | None,
) -> None:
    """카드 1개 옆에 분류 라디오·메모·저장 버튼."""
    labels = [label for _, label in DECISION_OPTIONS]
    label_to_value = {label: value for value, label in DECISION_OPTIONS}
    current_label = next(
        (label for value, label in DECISION_OPTIONS if value == prev_decision),
        "미분류",
    )
    cols = st.columns([3, 4, 1])
    with cols[0]:
        chosen_label = st.radio(
            "감사인 분류",
            options=labels,
            index=labels.index(current_label),
            key=f"rq_decision_{candidate_id}",
        )
    with cols[1]:
        note = st.text_area(
            "메모",
            value=prev_note or "",
            key=f"rq_note_{candidate_id}",
            height=80,
        )
    with cols[2]:
        st.write("")
        st.write("")
        save_clicked = st.button(
            "저장",
            key=f"rq_save_{candidate_id}",
            use_container_width=True,
        )

    if save_clicked and conn is not None:
        _persist_decision(
            conn,
            candidate_id=candidate_id,
            decision=label_to_value[chosen_label],
            note=note or None,
            previous_decision=prev_decision,
            batch_id=batch_id,
        )
    elif save_clicked and conn is None:
        st.warning("DB 연결이 없어 분류를 저장할 수 없습니다.")


def _persist_decision(
    conn: duckdb.DuckDBPyConnection,
    *,
    candidate_id: str,
    decision: str | None,
    note: str | None,
    previous_decision: str | None,
    batch_id: str | None,
) -> None:
    ss = st.session_state
    ctx = ss.get(KEY_COMPANY_CONTEXT)
    user = (
        getattr(ctx, "engagement_id", None) or "auditor"
        if (ctx is not None and not getattr(ctx, "is_anonymous", True))
        else "auditor"
    )
    audit_trail = (
        AuditTrail(conn) if (ctx is not None and not getattr(ctx, "is_anonymous", True)) else None
    )
    try:
        register_review_decision(
            conn,
            candidate_id=candidate_id,
            decision=decision,
            note=note,
            user=str(user),
            audit_trail=audit_trail,
            company_id=getattr(ctx, "company_id", None),
            engagement_id=getattr(ctx, "engagement_id", None),
            batch_id=batch_id,
            previous_decision=previous_decision,
        )
        st.success(f"{candidate_id} 분류 저장 완료")
        st.rerun()
    except (ValueError, KeyError) as exc:
        st.error(f"분류 저장 실패: {exc}")


# ── 탭 진입점 ─────────────────────────────────────────────────


def render(result: PipelineResult | None = None) -> None:
    """탭 엔트리.

    Args:
        result: 전표 데이터(`result.data`)를 통해 citation 점프(전표 라인) 표시.
                None이면 점프 패널의 row evidence는 candidate.journal_ref 만 표시.
    """
    st.markdown("### Review Queue · Narrator")
    st.caption(
        "PHASE1 룰 히트 + PHASE2 ML 스코어를 LLM이 재정렬·요약·인용한 결과. "
        "Sprint E2 워크플로우 — 실행 트리거, 분류 라디오·메모, 필터·검색이 추가됨."
    )

    ss = st.session_state
    narratives = ss.get(KEY_REVIEW_QUEUE_NARRATIVES) or []
    current_hash = ss.get(KEY_REVIEW_QUEUE_INPUT_HASH)
    _invalidate_jump_on_hash_change(current_hash)

    conn = _get_engagement_conn()
    df = _narratives_to_dataframe(narratives, conn)
    filters = _render_sidebar_filters(df)
    search_query = st.text_input(
        "candidate_id 검색",
        value=ss.get(KEY_REVIEW_QUEUE_SEARCH, ""),
        key="rq_search_input",
        placeholder="예: CAND-CASE-",
    )
    ss[KEY_REVIEW_QUEUE_SEARCH] = search_query

    _render_run_trigger(current_hash)

    if not narratives:
        st.info(
            "표시할 Narrator 결과가 아직 없습니다. "
            "위의 '분석 실행' 버튼이 narratives 적재 파이프라인과 연결되면 카드가 표시됩니다."
        )
        return

    filtered = apply_filters(df, filters)
    filtered = apply_search(filtered, search_query or "")
    st.markdown(f"총 {len(filtered):,}건 / 원본 {len(df):,}건")
    if filtered.empty:
        st.info("조건에 해당하는 candidate가 없습니다.")
        return

    # 정렬 — narratives 원본 dict로 카드 렌더 + DataFrame row로 분류 위젯
    cid_to_row: dict[str, dict[str, Any]] = {
        str(r["candidate_id"]): r.to_dict() for _, r in filtered.iterrows()
    }
    sorted_filtered = [
        n for n in _sorted_narratives(narratives) if str(n.get("candidate_id")) in cid_to_row
    ]

    col_cards, col_jump = st.columns([3, 2], gap="large")
    with col_cards:
        for narrative in sorted_filtered:
            cid = str(narrative.get("candidate_id") or "")
            render_candidate_card(narrative)
            row = cid_to_row[cid]
            decision_raw = row.get("audit_decision")
            note_raw = row.get("audit_note")
            batch_raw = row.get("batch_id")
            _render_decision_widget(
                cid,
                prev_decision=decision_raw if isinstance(decision_raw, str) else None,
                prev_note=note_raw if isinstance(note_raw, str) else None,
                batch_id=batch_raw if isinstance(batch_raw, str) and batch_raw else None,
                conn=conn,
            )
    with col_jump:
        data = getattr(result, "data", None) if result is not None else None
        render_citation_jump_panel(data)


def _get_engagement_conn() -> duckdb.DuckDBPyConnection | None:
    """ctx 기반 engagement DuckDB 연결을 ConnectionManager에서 획득."""
    ss = st.session_state
    ctx = ss.get(KEY_COMPANY_CONTEXT)
    if ctx is None or getattr(ctx, "is_anonymous", True):
        return None
    try:
        from src.db.connection import get_connection

        return get_connection(str(ctx.db_path))
    except Exception:  # noqa: BLE001
        logger.warning("review queue: engagement conn 획득 실패", exc_info=True)
        return None
