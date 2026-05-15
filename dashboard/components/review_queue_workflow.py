"""Sprint E2 — Review Queue 워크플로우 순수 함수 모듈.

Streamlit 비의존 비즈니스 로직만 담는다 (필터·검색·실행 계획·분류 저장 래퍼).
탭 진입점(`dashboard/tab_review_queue.py`)이 본 모듈을 호출해 UI에서 분리한다.

목적:
- pytest 단위 테스트에서 Streamlit 의존 없이 검증 가능.
- 비즈니스 규칙 (예산 가드, 필터 의미) 변경 시 1지점만 수정.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.export.audit_trail import AuditEvent
from src.llm.review_narrator.cache import update_audit_decision

if TYPE_CHECKING:
    import duckdb

    from src.export.audit_trail import AuditTrailProtocol


# Why: candidate N 자동 축소 시 사용할 단계. 스펙 §4 (PHASE3_REWORK_PLAN) 비용 가드와 일치.
DEFAULT_N_LADDER: tuple[int, ...] = (20, 10, 5)
# Why: candidate 1건당 평균 비용 추정(USD). 운영 평가 결과로 갱신 가능.
EST_COST_PER_CANDIDATE_USD: float = 0.012


@dataclass
class ReviewQueueFilters:
    """사이드바 필터 상태. 빈 값/None은 해당 차원 전체 통과."""

    confidence: list[str] = field(default_factory=list)
    priority_rank_max: int | None = None
    process: list[str] = field(default_factory=list)
    batch_id: list[str] = field(default_factory=list)
    audit_decision: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)


@dataclass
class RunPlan:
    """실행 트리거가 결정한 candidate 수·비용 추정·축소 단계."""

    requested_n: int
    effective_n: int
    estimated_cost_usd: float
    capped_by_budget: bool


def load_review_queue_rows(
    conn: duckdb.DuckDBPyConnection,
    batch_id: str | None,
) -> pd.DataFrame:
    """review_narratives + cited rule_id 집계 1건/행 DataFrame.

    Why: 필터·검색·렌더에 공통 쓰이는 1차 데이터셋. batch_id가 None이면 전체.
        cited_rule_ids는 narrative_json에서 rule_hit evidence rule_id를 추출.
    """
    where = "WHERE batch_id = ?" if batch_id else ""
    params: list[Any] = [batch_id] if batch_id else []
    sql = f"""
        SELECT candidate_id, batch_id, journal_id, priority_rank, priority_score,
               confidence, citation_valid, narrative_json, model_tier, cost_usd,
               audit_decision, audit_note, reviewed_by, reviewed_at
        FROM review_narratives
        {where}
        ORDER BY COALESCE(priority_rank, 9999), candidate_id
    """
    df = conn.execute(sql, params).df()
    if df.empty:
        df["cited_rule_ids"] = []
        df["process"] = []
        df["summary"] = []
        return df

    df["cited_rule_ids"] = df["narrative_json"].apply(_extract_cited_rule_ids)
    df["summary"] = df["narrative_json"].apply(_extract_summary)
    # journal_meta가 candidate dict 단계에서 sanitize되었으므로 process는 별도 컬럼이 아님.
    # 향후 process를 review_narratives에 별도 컬럼으로 추가하기 전까지는 빈값으로 둔다.
    df["process"] = ""
    return df


def _extract_cited_rule_ids(narrative_json: Any) -> list[str]:
    """narrative_json(dict|str) → rule_hit evidence의 rule_id 리스트."""
    import json

    if isinstance(narrative_json, str):
        try:
            narrative_json = json.loads(narrative_json)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(narrative_json, dict):
        return []
    rule_ids: list[str] = []
    for item in narrative_json.get("reasoning") or []:
        for ev in item.get("evidence") or []:
            if ev.get("type") == "rule_hit" and ev.get("rule_id"):
                rule_ids.append(ev["rule_id"])
    return sorted(set(rule_ids))


def _extract_summary(narrative_json: Any) -> str:
    """narrative_json에서 summary 추출 (없으면 빈 문자열)."""
    import json

    if isinstance(narrative_json, str):
        try:
            narrative_json = json.loads(narrative_json)
        except (json.JSONDecodeError, TypeError):
            return ""
    if not isinstance(narrative_json, dict):
        return ""
    return str(narrative_json.get("summary") or "")


def apply_filters(df: pd.DataFrame, filters: ReviewQueueFilters) -> pd.DataFrame:
    """6종 필터를 in-memory로 차례 적용한다. 빈 입력은 통과."""
    if df.empty:
        return df
    out: pd.DataFrame = df
    if filters.confidence:
        confidence_col = pd.Series(out["confidence"])
        out = out.loc[confidence_col.isin(filters.confidence)]
    if filters.priority_rank_max is not None:
        rank_col = pd.Series(out["priority_rank"]).fillna(9999).astype(int)
        out = out.loc[rank_col <= int(filters.priority_rank_max)]
    if filters.process:
        process_col = pd.Series(out["process"])
        out = out.loc[process_col.isin(filters.process)]
    if filters.batch_id:
        batch_col = pd.Series(out["batch_id"])
        out = out.loc[batch_col.isin(filters.batch_id)]
    if filters.audit_decision:
        # NULL(미분류)도 명시적으로 선택 가능하도록 sentinel 'unassigned' 처리.
        wanted = set(filters.audit_decision)
        decision_col = pd.Series(out["audit_decision"])
        mask = decision_col.isin(list(wanted - {"unassigned"}))
        if "unassigned" in wanted:
            mask = mask | decision_col.isna()
        out = out.loc[mask]
    if filters.rule_ids:
        wanted_rules = set(filters.rule_ids)
        cited_col = pd.Series(out["cited_rule_ids"])
        mask = cited_col.apply(lambda xs: bool(set(xs) & wanted_rules))
        out = out.loc[mask.astype(bool)]
    return out


def apply_search(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """candidate_id 부분일치(대소문자 무시). 빈 query는 통과."""
    if df.empty or not query:
        return df
    q = query.strip().lower()
    if not q:
        return df
    id_col = pd.Series(df["candidate_id"]).astype(str).str.lower()
    return df.loc[id_col.str.contains(q, na=False)]


def compute_run_plan(
    requested_n: int,
    *,
    budget_usd: float | None = None,
    n_ladder: tuple[int, ...] = DEFAULT_N_LADDER,
) -> RunPlan:
    """실행 트리거의 N 자동 축소 + 비용 추정.

    Why: 스펙 §4 비용 가드 — budget 초과 시 N=20 → 10 → 5로 점진 축소. budget=None이면
        축소 없이 요청 N 그대로 사용. hard_limit는 호출자가 candidate_builder에서 적용.
    """
    if requested_n <= 0:
        return RunPlan(
            requested_n=requested_n, effective_n=0, estimated_cost_usd=0.0, capped_by_budget=False
        )
    if budget_usd is None or budget_usd <= 0:
        return RunPlan(
            requested_n=requested_n,
            effective_n=requested_n,
            estimated_cost_usd=requested_n * EST_COST_PER_CANDIDATE_USD,
            capped_by_budget=False,
        )

    # ladder를 큰 값부터 내려가며 budget 안에 들어오는 첫 값 채택.
    sorted_ladder = sorted({requested_n, *n_ladder}, reverse=True)
    for n in sorted_ladder:
        cost = n * EST_COST_PER_CANDIDATE_USD
        if cost <= budget_usd:
            return RunPlan(
                requested_n=requested_n,
                effective_n=n,
                estimated_cost_usd=cost,
                capped_by_budget=(n < requested_n),
            )
    # ladder 전부 초과 → 0건 (실행 보류 신호)
    return RunPlan(
        requested_n=requested_n,
        effective_n=0,
        estimated_cost_usd=0.0,
        capped_by_budget=True,
    )


def register_review_decision(
    conn: duckdb.DuckDBPyConnection,
    *,
    candidate_id: str,
    decision: str | None,
    note: str | None,
    user: str,
    audit_trail: AuditTrailProtocol | None,
    company_id: str | None = None,
    engagement_id: str | None = None,
    batch_id: str | None = None,
    previous_decision: str | None = None,
) -> dict[str, Any]:
    """분류 저장 + AuditTrail 'review_decision_change' 이벤트 1건 기록.

    Why: 분류 UPDATE와 감사증적 기록을 한 호출로 묶어 부분 성공(UPDATE는 됐는데 trail은
        실패)이 발생해도 호출부에서 별도 분기할 필요 없게 만든다. AuditTrail이 None이면
        trail 기록은 생략하지만 분류 자체는 저장한다.
    """
    result = update_audit_decision(
        conn,
        candidate_id=candidate_id,
        decision=decision,
        note=note,
        user=user,
    )
    if audit_trail is not None:
        try:
            audit_trail.log(
                AuditEvent(
                    event_type="review_decision_change",
                    user_action=(
                        f"review queue 분류: {previous_decision or '미분류'} → "
                        f"{decision or '미분류'}"
                    ),
                    details={
                        "candidate_id": candidate_id,
                        "previous_decision": previous_decision,
                        "new_decision": decision,
                        "has_note": bool(note),
                    },
                    batch_id=batch_id,
                    company_id=company_id,
                    engagement_id=engagement_id,
                )
            )
        except Exception:  # noqa: BLE001 — 감사증적 실패가 분류 저장을 막지 않도록.
            # AuditTrail.log는 자체적으로 record_event를 재시도하므로 여기서는 흡수만 한다.
            pass
    return result
