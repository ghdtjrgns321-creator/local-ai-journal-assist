"""DuckDB 프리셋 쿼리 — 대시보드·드릴다운용 Raw 데이터 추출.

Why: 대시보드(07-dashboard)에서 batch_id 기반으로 Raw 데이터를 추출한다.
     SQL 단 집계 대신 Raw 데이터를 반환하여, 대시보드 필터 적용 후
     pandas groupby로 재집계할 수 있도록 한다.
     Benford 통계와 드릴다운은 고정 분석이므로 SQL에서 직접 반환.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# ── 프리셋 쿼리 카탈로그 (6종) ─────────────────────────────────

PRESET_QUERIES: dict[str, str] = {
    # Why: 대시보드 진입 시 1회 호출 → session_state 캐싱
    #      pandas 필터/groupby로 KPI·차트·히트맵 직접 계산
    "batch_ledger": """
        SELECT document_id, company_code, fiscal_year,
               posting_date, document_date, document_type,
               line_number, gl_account, debit_amount, credit_amount,
               line_text, header_text, created_by, source,
               anomaly_score, risk_level, flagged_rules
        FROM general_ledger
        WHERE upload_batch_id = ?
        ORDER BY anomaly_score DESC
    """,

    # Why: 룰별 위반 통계를 대시보드에서 pandas groupby로 집계
    #      Explorer 탭 드릴다운 시에도 document_id 필터링 소스
    "batch_flags": """
        SELECT document_id, line_number, track_name, rule_code, score
        FROM anomaly_flags
        WHERE upload_batch_id = ?
        ORDER BY document_id, score DESC
    """,

    # Why: 배치 전체 대상 고정 분석 (요약 통계)
    "benford_summary": """
        SELECT sample_size, mad, mad_conformity,
               chi2_statistic, chi2_p_value,
               ks_statistic, ks_p_value,
               is_conforming, confidence
        FROM benford_summary
        WHERE upload_batch_id = ?
    """,

    # Why: 배치 전체 대상 고정 분석 (자릿수별 분포)
    "benford_digits": """
        SELECT digit, observed_freq, expected_freq, deviation
        FROM benford_digits
        WHERE upload_batch_id = ?
        ORDER BY digit
    """,

    # Why: 룰별 위반 통계를 VIEW로 간결하게 조회
    "rule_violation_stats": """
        SELECT track_name, rule_code, flagged_count, avg_score, max_score
        FROM anomaly_flag_summary
        WHERE upload_batch_id = ?
        ORDER BY flagged_count DESC
    """,

    # Why: Explorer 탭에서 행 클릭 시 on-demand 호출
    #      파라미터 2개 (batch_id, document_id)
    "document_rule_detail": """
        SELECT track_name, rule_code, score
        FROM anomaly_flags
        WHERE upload_batch_id = ? AND document_id = ?
        ORDER BY score DESC
    """,
}


# ── 커스텀 예외 ────────────────────────────────────────────────


class QueryNotFoundError(KeyError):
    """존재하지 않는 프리셋 쿼리명."""


class QueryExecutionError(RuntimeError):
    """SQL 실행 중 오류."""


# ── public API ─────────────────────────────────────────────────


def execute_preset(
    conn: duckdb.DuckDBPyConnection,
    query_name: str,
    params: tuple | None = None,
    *,
    batch_id: str | None = None,
) -> pd.DataFrame:
    """프리셋 쿼리 실행 후 DataFrame 반환.

    Args:
        conn: DuckDB 커넥션.
        query_name: PRESET_QUERIES 키.
        params: SQL 파라미터 바인딩 튜플. None이면 (batch_id,) 자동 구성.
        batch_id: params가 None일 때 사용하는 편의 파라미터.

    Raises:
        QueryNotFoundError: query_name이 PRESET_QUERIES에 없을 때.
        QueryExecutionError: SQL 실행 중 오류 발생 시.

    Returns:
        결과 DataFrame. 0행이면 빈 DataFrame (컬럼 스키마 유지).
    """
    if query_name not in PRESET_QUERIES:
        raise QueryNotFoundError(f"프리셋 쿼리 '{query_name}' 없음. 사용 가능: {list(PRESET_QUERIES.keys())}")

    sql = PRESET_QUERIES[query_name]

    # Why: params 우선. batch_id는 단일 파라미터 쿼리의 편의 인터페이스.
    if params is None:
        if batch_id is None:
            raise ValueError("params 또는 batch_id 중 하나는 필수")
        params = (batch_id,)

    # Why: document_rule_detail처럼 ?가 2개인 쿼리에 batch_id=만 전달하는 실수를
    #      DuckDB 런타임 에러보다 먼저 명확한 메시지로 차단
    expected = sql.count("?")
    if len(params) != expected:
        raise ValueError(
            f"쿼리 '{query_name}'은 {expected}개 파라미터가 필요하지만 "
            f"{len(params)}개가 전달됨"
        )

    try:
        result = conn.execute(sql, params)
        df = result.df()
    except duckdb.Error as e:
        raise QueryExecutionError(
            f"쿼리 '{query_name}' 실행 실패: {e}"
        ) from e

    logger.debug("쿼리 실행: %s → %d행", query_name, len(df))
    return df
