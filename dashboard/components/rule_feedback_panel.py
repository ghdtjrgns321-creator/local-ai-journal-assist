"""WU-30: 감사규칙 피드백 루프 — Streamlit 승인 UI.

역할:
- "제안 생성" 버튼으로 LLM 호출 → RuleFeedbackReport → session_state 저장
- 카테고리별 expander + 제안마다 근거 전표 표 + 승인/거부 버튼
- 승인 시 RuleFeedbackEngine.apply() → 회사별 audit_rules.yaml 기록 + Context 재생성
- LLM 비가용/예외는 패널에서 잡아 메시지만 표시 (앱 중단 없음)
"""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from src.company.repository import CompanyRepository
from src.context import CompanyContext, ContextFactory
from src.db.connection import ConnectionManager
from src.llm.models import RuleCategory, RuleSuggestion

logger = logging.getLogger(__name__)

# session_state 키
_KEY_REPORT = "wu30_rule_feedback_report"
_KEY_APPLIED = "wu30_rule_feedback_applied"  # list[dict]: {category, value, ts}
_KEY_REJECTED = "wu30_rule_feedback_rejected"

# 카테고리별 한국어 라벨
_CATEGORY_LABELS: dict[RuleCategory, str] = {
    RuleCategory.MANUAL_SOURCE_CODES: "수기 전표 소스 코드",
    RuleCategory.SUSPENSE_KEYWORDS: "가계정 키워드 (적요)",
    RuleCategory.SUSPENSE_ACCOUNT_CODES: "가계정 GL 코드",
    RuleCategory.REVENUE_ACCOUNT_PREFIXES: "매출 계정 접두사",
    RuleCategory.INTERCOMPANY_IDENTIFIERS: "내부거래(IC) 계정 쌍",
}


def render(
    ctx: CompanyContext,
    factory: ContextFactory,
    conn_mgr: ConnectionManager,
    repo: CompanyRepository,
) -> None:
    """감사룰 피드백 루프 탭 메인 렌더러.

    Why repo를 명시 주입 — session_state["_company_repo"]에 의존하면
         호출자와 암묵적 계약이 생겨 리팩터링 시 무음 장애 가능.
    """
    st.subheader("감사룰 자동 제안 (WU-30)")
    st.caption(
        "LLM이 현재 회사 데이터에서 빈발 패턴을 분석해 audit_rules.yaml 개선안을 제안합니다. "
        "승인된 제안만 회사별 오버라이드에 기록됩니다 (전역 룰 불변)."
    )

    if ctx.is_anonymous:
        st.info("회사를 먼저 선택해 주세요. 피드백 루프는 회사별 오버라이드 저장이 필요합니다.")
        return

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        generate = st.button("제안 생성", width="stretch")
    with col_info:
        st.caption(f"회사: {ctx.company_id} / {ctx.engagement_id}")

    if generate:
        _run_propose(ctx, conn_mgr)

    report = st.session_state.get(_KEY_REPORT)
    if report is None:
        st.info("제안이 아직 생성되지 않았습니다. '제안 생성' 버튼을 눌러주세요.")
        return

    _render_summary(report)
    st.divider()
    _render_suggestions(report, ctx, factory, conn_mgr, repo)


# ── 내부 렌더 ───────────────────────────────────────────


def _run_propose(ctx: CompanyContext, conn_mgr: ConnectionManager) -> None:
    """LLM 호출 → session_state 저장. 예외는 사용자에게 메시지로만 표시."""
    try:
        from src.llm.rule_feedback import RuleFeedbackEngine
    except Exception as exc:
        st.error(f"LLM 모듈 로드 실패: {exc}")
        return

    try:
        conn = conn_mgr.get(str(ctx.db_path))
        with st.spinner("LLM이 데이터 패턴을 분석 중입니다 (수십 초 소요)..."):
            engine = RuleFeedbackEngine(conn, ctx.audit_rules)
            report = engine.propose()
        st.session_state[_KEY_REPORT] = report
        st.success(f"제안 {len(report.suggestions)}건 생성 완료")
    except RuntimeError as exc:
        # get_chat_client 비가용 (API 키 / 네트워크)
        st.error(f"LLM 서비스에 연결할 수 없습니다: {exc}")
    except Exception as exc:
        logger.exception("rule_feedback propose 실패")
        st.error(f"제안 생성 중 오류: {exc}")


def _render_summary(report) -> None:
    """샘플 수집량 + 생성 시각 메타 표시."""
    with st.expander("샘플 수집 요약", expanded=False):
        st.caption(f"생성 시각 (UTC): {report.generated_at}")
        if report.sample_summary:
            df = pd.DataFrame(
                [(k, v) for k, v in report.sample_summary.items()],
                columns=["category", "sample_count"],
            )
            st.dataframe(df, hide_index=True, width="stretch")


def _render_suggestions(
    report, ctx: CompanyContext, factory: ContextFactory,
    conn_mgr: ConnectionManager, repo: CompanyRepository,
) -> None:
    """카테고리별 5 expander + 제안 카드."""
    by_category: dict[RuleCategory, list[RuleSuggestion]] = {c: [] for c in RuleCategory}
    for s in report.suggestions:
        by_category[s.category].append(s)

    for category in RuleCategory:
        items = by_category[category]
        label = _CATEGORY_LABELS[category]
        with st.expander(f"{label} — {len(items)}건", expanded=len(items) > 0):
            if not items:
                st.caption("해당 카테고리에 유의미한 신규 제안이 없습니다.")
                continue
            for idx, suggestion in enumerate(items):
                _render_single_suggestion(
                    suggestion, idx, ctx, factory, conn_mgr, repo,
                )


def _render_single_suggestion(
    suggestion: RuleSuggestion,
    idx: int,
    ctx: CompanyContext,
    factory: ContextFactory,
    conn_mgr: ConnectionManager,
    repo: CompanyRepository,
) -> None:
    """제안 1건 카드 — 값·신뢰도·근거·승인/거부 버튼."""
    value_repr = _format_value(suggestion)
    st.markdown(f"**제안값**: `{value_repr}`  ·  신뢰도: **{suggestion.confidence}**")
    st.caption(suggestion.rationale)

    if suggestion.conflicts_with_existing:
        st.warning("충돌 가능성: " + ", ".join(suggestion.conflicts_with_existing))

    if suggestion.evidence_samples:
        df = pd.DataFrame([e.model_dump() for e in suggestion.evidence_samples])
        st.dataframe(df, hide_index=True, width="stretch")

    key_base = f"wu30_{suggestion.category.value}_{idx}"
    col_a, col_r, _ = st.columns([1, 1, 6])
    with col_a:
        if st.button("승인", key=f"{key_base}_approve", type="primary"):
            _apply_one(suggestion, ctx, factory, conn_mgr, repo)
    with col_r:
        if st.button("거부", key=f"{key_base}_reject"):
            _reject_one(suggestion, ctx, conn_mgr, repo)
    st.divider()


def _format_value(s: RuleSuggestion) -> str:
    """카테고리별 proposed_value 표시 포맷."""
    if s.category == RuleCategory.INTERCOMPANY_IDENTIFIERS and s.intercompany_pair:
        pair = s.intercompany_pair
        return f"receivable={pair.receivable}, payable={pair.payable}"
    return s.proposed_value or "(없음)"


def _apply_one(
    suggestion: RuleSuggestion,
    ctx: CompanyContext,
    factory: ContextFactory,
    conn_mgr: ConnectionManager,
    repo: CompanyRepository,
) -> None:
    """단일 제안을 즉시 저장 — UI 응답성 유지 (배치 승인은 추후 확장)."""
    try:
        from src.llm.rule_feedback import RuleFeedbackEngine
    except Exception as exc:
        st.error(f"모듈 로드 실패: {exc}")
        return

    try:
        conn = conn_mgr.get(str(ctx.db_path))
        engine = RuleFeedbackEngine(conn, ctx.audit_rules)
        result = engine.apply(
            [suggestion],
            ctx.company_id,
            repo,
            engagement_id=ctx.engagement_id,
        )
    except Exception as exc:
        logger.exception("rule_feedback apply 실패")
        st.error(f"저장 중 오류: {exc}")
        return

    # Context 캐시 무효화 → 다음 렌더에서 갱신된 audit_rules 반영
    factory.invalidate(ctx.company_id, ctx.engagement_id)
    st.session_state.pop("audit_company_context", None)

    applied = st.session_state.setdefault(_KEY_APPLIED, [])
    applied.append({
        "category": suggestion.category.value,
        "value": _format_value(suggestion),
    })
    if result.applied > 0:
        st.success(f"승인 완료: {_format_value(suggestion)}")
    else:
        st.info(f"이미 적용되어 있어 스킵됨: {_format_value(suggestion)}")
    st.rerun()


def _reject_one(
    suggestion: RuleSuggestion,
    ctx: CompanyContext,
    conn_mgr: ConnectionManager,
    repo: CompanyRepository,
) -> None:
    """거부 — yaml 변경 없이 감사 로그에만 기록 (LLM client 불필요)."""
    # Why: log_rejections는 staticmethod이므로 엔진/conn을 재생성하지 않는다.
    try:
        from src.llm.rule_feedback import RuleFeedbackEngine
        conn = conn_mgr.get(str(ctx.db_path))
        RuleFeedbackEngine.log_rejections(
            [suggestion],
            ctx.company_id,
            repo,
            conn=conn,
            engagement_id=ctx.engagement_id,
        )
    except Exception as exc:
        logger.exception("rule_feedback reject 로그 실패")
        st.warning(f"거부 로그 실패: {exc}")
        return

    rejected = st.session_state.setdefault(_KEY_REJECTED, [])
    rejected.append({
        "category": suggestion.category.value,
        "value": _format_value(suggestion),
    })
    st.info(f"거부 기록됨: {_format_value(suggestion)}")
