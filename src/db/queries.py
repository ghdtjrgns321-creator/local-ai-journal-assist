"""프리셋 쿼리 — 대시보드·드릴다운용 Raw 데이터 추출.

Why: SQL 사전 집계는 대시보드 필터와 충돌.
     Raw 데이터를 DB에서 퍼온 뒤 pandas로 집계한다.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# ── 프리셋 쿼리 (6종) ────────────────────────────────────────

PRESET_QUERIES: dict[str, str] = {
    "batch_ledger": """
        SELECT document_id, company_code, fiscal_year, fiscal_period,
               posting_date, document_date, document_type,
               line_number, gl_account, debit_amount, credit_amount,
               line_text, header_text, created_by, source,
               business_process, user_persona, approved_by,
               approval_level, reference,
               is_fraud, fraud_type, is_anomaly, anomaly_type,
               sod_violation, sod_conflict_type,
               anomaly_score, risk_level, flagged_rules
        FROM general_ledger
        WHERE upload_batch_id = ?
        ORDER BY anomaly_score DESC
    """,
    "batch_flags": """
        SELECT document_id, line_number, track_name, rule_code, score
        FROM anomaly_flags
        WHERE upload_batch_id = ?
        ORDER BY document_id, score DESC
    """,
    "benford_summary": """
        SELECT sample_size, mad, mad_conformity,
               chi2_statistic, chi2_p_value,
               ks_statistic, ks_p_value,
               is_conforming, confidence
        FROM benford_summary
        WHERE upload_batch_id = ?
    """,
    "benford_digits": """
        SELECT digit, observed_freq, expected_freq, deviation
        FROM benford_digits
        WHERE upload_batch_id = ?
        ORDER BY digit
    """,
    "rule_violation_stats": """
        SELECT track_name, rule_code, flagged_count, avg_score, max_score
        FROM anomaly_flag_summary
        WHERE upload_batch_id = ?
        ORDER BY flagged_count DESC
    """,
    "document_rule_detail": """
        SELECT track_name, rule_code, score
        FROM anomaly_flags
        WHERE upload_batch_id = ? AND document_id = ?
        ORDER BY score DESC
    """,
    # ── Whitelist (HITL 예외 처리) ──
    "insert_whitelist": """
        INSERT INTO whitelist (batch_id, document_id, rule_code, reason, created_by)
        VALUES (?, ?, ?, ?, ?)
    """,
    "batch_whitelist": """
        SELECT id, document_id, rule_code, reason, created_by, created_at
        FROM whitelist
        WHERE batch_id = ?
        ORDER BY created_at DESC
    """,
    "delete_whitelist": """
        DELETE FROM whitelist WHERE id = ?
    """,
}


# ── 에러 클래스 ──────────────────────────────────────────────


class QueryNotFoundError(KeyError):
    """존재하지 않는 프리셋 쿼리명."""


class QueryExecutionError(RuntimeError):
    """SQL 실행 중 오류."""


# ── 공개 API ─────────────────────────────────────────────────


def execute_preset(
    conn: duckdb.DuckDBPyConnection,
    query_name: str,
    params: tuple | None = None,
    *,
    batch_id: str | None = None,
) -> pd.DataFrame:
    """프리셋 쿼리 실행 후 DataFrame 반환.

    Args:
        query_name: PRESET_QUERIES 키.
        params: SQL 파라미터 바인딩 튜플.
        batch_id: params가 None일 때 (batch_id,) 자동 구성.

    Raises:
        QueryNotFoundError: query_name이 PRESET_QUERIES에 없을 때.
        QueryExecutionError: SQL 실행 중 오류.
        ValueError: params와 batch_id 모두 None일 때.
    """
    if query_name not in PRESET_QUERIES:
        raise QueryNotFoundError(
            f"존재하지 않는 쿼리: '{query_name}'. "
            f"사용 가능: {sorted(PRESET_QUERIES.keys())}"
        )

    if params is None:
        if batch_id is None:
            raise ValueError("params 또는 batch_id 중 하나는 필수")
        params = (batch_id,)

    sql = PRESET_QUERIES[query_name]

    try:
        result = conn.execute(sql, params)
        return result.fetchdf()
    except duckdb.Error as exc:
        raise QueryExecutionError(
            f"쿼리 '{query_name}' 실행 실패: {exc}"
        ) from exc


def execute_write(
    conn: duckdb.DuckDBPyConnection,
    query_name: str,
    params: tuple,
    *,
    max_retries: int = 3,
) -> None:
    """INSERT/DELETE/UPDATE 프리셋 쿼리 실행 (반환값 없음).

    Why: execute_preset()은 fetchdf()를 호출하므로 DML에 사용 불가.
         DuckDB single-writer 제약 대응으로 쓰기 락 시 재시도.
    """
    import time

    if query_name not in PRESET_QUERIES:
        raise QueryNotFoundError(
            f"존재하지 않는 쿼리: '{query_name}'. "
            f"사용 가능: {sorted(PRESET_QUERIES.keys())}"
        )

    sql = PRESET_QUERIES[query_name]

    # Why: DuckDB single-writer 락 충돌은 IOException 외에
    #      TransactionException으로도 발생할 수 있음
    _retryable = (duckdb.IOException, duckdb.TransactionException)

    for attempt in range(max_retries):
        try:
            conn.execute(sql, params)
            return
        except _retryable:
            # Why: 짧은 대기 후 재시도 (exponential: 0.1s → 0.2s → 0.3s)
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise
        except duckdb.Error as exc:
            raise QueryExecutionError(
                f"쿼리 '{query_name}' 실행 실패: {exc}"
            ) from exc
