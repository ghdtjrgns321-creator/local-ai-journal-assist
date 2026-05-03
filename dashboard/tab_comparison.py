"""연도 비교 탭 (RC-4-7).

두 Engagement의 탐지 결과를 ATTACH 교차 쿼리로 비교한다.
함정3 방어: 집계 연산은 DuckDB SQL에 위임, Pandas에는 요약표만 전달.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard._state import KEY_BATCH_ID, KEY_COMPANY_CONTEXT, KEY_COMPANY_ID
from src.db.queries import attached_engagement

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb

    from src.company.repository import CompanyRepository
    from src.db.connection import ConnectionManager
    from src.pipeline import PipelineResult


def render(
    result: PipelineResult,
    repo: CompanyRepository,
    conn_mgr: ConnectionManager,
) -> None:
    """연도 비교 탭 진입점.

    Args:
        repo: app.py에서 주입받은 CompanyRepository (인스턴스 중복 방지)
        conn_mgr: app.py에서 주입받은 ConnectionManager
    """
    ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    if ctx is None or ctx.is_anonymous:
        st.info("연도 비교는 회사를 선택한 후 사용할 수 있습니다.")
        return

    company_id = st.session_state.get(KEY_COMPANY_ID)
    if not company_id:
        return

    prior = _select_prior_engagement(company_id, ctx.engagement_id, repo)
    if prior is None:
        return

    current_batch = st.session_state.get(KEY_BATCH_ID, "")
    if not current_batch:
        st.warning("현재 연도의 분석 결과가 없습니다.")
        return

    prior_db = repo.db_path(company_id, prior)
    if not prior_db.exists():
        st.warning(f"전기({prior}) DB 파일이 존재하지 않습니다. 먼저 분석을 실행하세요.")
        return

    conn = conn_mgr.get(ctx.db_path)
    _render_comparison(conn, current_batch, prior_db, prior)


def _select_prior_engagement(
    company_id: str, current_eid: str, repo: CompanyRepository,
) -> str | None:
    """비교 대상 연도 선택 selectbox."""
    engagements = repo.list_engagements(company_id)
    # Why: 현재 연도를 제외한 목록만 표시
    others = [e for e in engagements if e.engagement_id != current_eid]

    if not others:
        st.info("비교 가능한 다른 연도가 없습니다.")
        return None

    labels = {e.engagement_id: f"FY {e.fiscal_year} ({e.engagement_id})" for e in others}
    selected = st.selectbox("비교 대상 연도", list(labels.keys()),
                            format_func=lambda x: labels[x])
    return selected


def _render_comparison(
    conn: duckdb.DuckDBPyConnection,
    current_batch: str,
    prior_db_path: Path,
    prior_eid: str,
) -> None:
    """ATTACH 교차 쿼리 → 비교 차트 5종 렌더링."""
    from dashboard.components.charts.comparison_charts import (
        new_accounts_table,
        risk_distribution_comparison,
        rule_violation_delta,
        yoy_amount_bar,
        yoy_count_bar,
    )

    try:
        with attached_engagement(conn, prior_db_path, f"prior_{prior_eid}") as alias:
            # Why: 함정3 방어 — 모든 집계를 SQL에서 수행
            overview = _query_overview(conn, current_batch, alias)
            cur_risk = _query_risk_dist(conn, current_batch, schema=None)
            pri_risk = _query_risk_dist(conn, current_batch=None, schema=alias)
            cur_rules = _query_rule_counts(conn, current_batch, schema=None)
            pri_rules = _query_rule_counts(conn, current_batch=None, schema=alias)
            cur_accounts = _query_accounts(conn, current_batch, schema=None)
            pri_accounts = _query_accounts(conn, current_batch=None, schema=alias)
    except Exception as e:
        st.error(f"비교 쿼리 실패: {e}")
        return

    # Why: overview에서 건수/금액 추출
    cur_row = overview[overview["period"] == "current"].iloc[0] if len(overview) > 0 else None
    pri_row = overview[overview["period"] == "prior"].iloc[0] if len(overview) > 1 else None

    if cur_row is None and pri_row is None:
        st.warning("비교할 데이터가 없습니다.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            yoy_count_bar(
                int(cur_row["row_count"]) if cur_row is not None else 0,
                int(pri_row["row_count"]) if pri_row is not None else 0,
            ),
            use_container_width=True,
        )
    with col2:
        st.plotly_chart(
            yoy_amount_bar(
                float(cur_row["total_debit"]) if cur_row is not None else 0,
                float(pri_row["total_debit"]) if pri_row is not None else 0,
            ),
            use_container_width=True,
        )

    st.plotly_chart(
        risk_distribution_comparison(cur_risk, pri_risk),
        use_container_width=True,
    )

    st.plotly_chart(
        rule_violation_delta(cur_rules, pri_rules),
        use_container_width=True,
    )

    st.subheader("신규/제거 계정과목")
    accounts_df = new_accounts_table(cur_accounts, pri_accounts)
    if accounts_df.empty:
        st.info("계정과목 변동 없음")
    else:
        st.dataframe(accounts_df, use_container_width=True, hide_index=True)


# ── SQL 헬퍼 (집계는 DuckDB에서 수행) ────────────────────────────


def _query_overview(conn, current_batch: str, alias: str):
    """건수/금액/평균 anomaly_score 비교 — compare_engagements 대체."""

    # Why: prior DB의 최신 batch_id를 자동 검색 (사용자가 모를 수 있으므로)
    prior_batch_sql = f"""
        SELECT upload_batch_id FROM {alias}.general_ledger
        GROUP BY upload_batch_id ORDER BY MAX(created_at) DESC LIMIT 1
    """
    prior_batch_row = conn.execute(prior_batch_sql).fetchone()
    prior_batch = prior_batch_row[0] if prior_batch_row else ""

    sql = f"""
        SELECT 'current' AS period,
               COUNT(*)           AS row_count,
               COALESCE(SUM(debit_amount), 0)  AS total_debit,
               COALESCE(AVG(anomaly_score), 0)  AS avg_anomaly
        FROM general_ledger WHERE upload_batch_id = ?
        UNION ALL
        SELECT 'prior',
               COUNT(*),
               COALESCE(SUM(debit_amount), 0),
               COALESCE(AVG(anomaly_score), 0)
        FROM {alias}.general_ledger WHERE upload_batch_id = ?
    """
    return conn.execute(sql, [current_batch, prior_batch]).fetchdf()


def _query_risk_dist(conn, current_batch: str | None, schema: str | None):
    """위험등급 분포 — GROUP BY risk_level."""
    table = f"{schema}.general_ledger" if schema else "general_ledger"

    if current_batch:
        sql = f"""
            SELECT risk_level, COUNT(*) AS cnt
            FROM {table} WHERE upload_batch_id = ?
            GROUP BY risk_level ORDER BY risk_level
        """
        return conn.execute(sql, [current_batch]).fetchdf()

    # Why: prior DB는 최신 batch 자동 선택
    sql = f"""
        SELECT risk_level, COUNT(*) AS cnt
        FROM {table}
        WHERE upload_batch_id = (
            SELECT upload_batch_id FROM {table}
            GROUP BY upload_batch_id ORDER BY MAX(created_at) DESC LIMIT 1
        )
        GROUP BY risk_level ORDER BY risk_level
    """
    return conn.execute(sql).fetchdf()


def _query_rule_counts(conn, current_batch: str | None, schema: str | None):
    """룰별 위반 건수 — flagged_rules 파싱."""
    table = f"{schema}.general_ledger" if schema else "general_ledger"

    # Why: 파라미터 바인딩으로 SQL injection 방지 (_query_overview와 일관)
    if current_batch:
        sql = f"""
            SELECT TRIM(rule_code) AS rule_code, COUNT(*) AS cnt
            FROM (
                SELECT UNNEST(STRING_SPLIT(flagged_rules, ',')) AS rule_code
                FROM {table}
                WHERE upload_batch_id = ?
                  AND flagged_rules IS NOT NULL AND flagged_rules != ''
            )
            WHERE TRIM(rule_code) != ''
            GROUP BY TRIM(rule_code) ORDER BY cnt DESC
        """
        return conn.execute(sql, [current_batch]).fetchdf()

    sql = f"""
        SELECT TRIM(rule_code) AS rule_code, COUNT(*) AS cnt
        FROM (
            SELECT UNNEST(STRING_SPLIT(flagged_rules, ',')) AS rule_code
            FROM {table}
            WHERE upload_batch_id = (
                SELECT upload_batch_id FROM {table}
                GROUP BY upload_batch_id ORDER BY MAX(created_at) DESC LIMIT 1
            )
              AND flagged_rules IS NOT NULL AND flagged_rules != ''
        )
        WHERE TRIM(rule_code) != ''
        GROUP BY TRIM(rule_code) ORDER BY cnt DESC
    """
    return conn.execute(sql).fetchdf()


def _query_accounts(conn, current_batch: str | None, schema: str | None) -> set[str]:
    """계정과목 고유 목록 → set[str]."""
    table = f"{schema}.general_ledger" if schema else "general_ledger"

    # Why: 파라미터 바인딩으로 SQL injection 방지
    if current_batch:
        sql = f"""
            SELECT DISTINCT gl_account FROM {table}
            WHERE upload_batch_id = ? AND gl_account IS NOT NULL
        """
        rows = conn.execute(sql, [current_batch]).fetchall()
    else:
        sql = f"""
            SELECT DISTINCT gl_account FROM {table}
            WHERE upload_batch_id = (
                SELECT upload_batch_id FROM {table}
                GROUP BY upload_batch_id ORDER BY MAX(created_at) DESC LIMIT 1
            ) AND gl_account IS NOT NULL
        """
        rows = conn.execute(sql).fetchall()
    return {r[0] for r in rows}
