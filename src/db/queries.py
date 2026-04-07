"""프리셋 쿼리 — 대시보드·드릴다운용 Raw 데이터 추출.

Why: SQL 사전 집계는 대시보드 필터와 충돌.
     Raw 데이터를 DB에서 퍼온 뒤 pandas로 집계한다.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

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


# ── ATTACH 헬퍼 (RC-3: 연도 비교) ──────────────────────────


@contextmanager
def attached_engagement(
    conn: duckdb.DuckDBPyConnection,
    other_db_path: str | Path,
    alias: str = "other",
) -> Generator[str, None, None]:
    """DuckDB ATTACH로 다른 engagement DB를 READ_ONLY 연결.

    Why: 연도 비교(YoY) 시 현재 DB에서 이전 연도 DB를 참조해야 한다.
         컨텍스트 매니저로 DETACH를 강제하여 파일 락 누수를 방지.

    Usage::

        with attached_engagement(conn, "path/to/prior.duckdb", "y2024") as alias:
            conn.execute(f"SELECT * FROM {alias}.general_ledger")

    Yields:
        sanitize된 alias 문자열 (SQL 스키마 접두사로 사용).
    """
    # Why: alias에 특수문자가 들어가면 SQL injection 위험
    safe_alias = re.sub(r"[^a-zA-Z0-9_]", "_", alias)

    # Why: 상대 경로를 넘기면 Streamlit CWD에 따라 파일을 못 찾거나
    #      빈 DB를 엉뚱한 곳에 생성하는 참사 발생 — 절대 경로 강제
    # Why: Windows에서 resolve()가 \\?\ 접두사를 붙일 수 있으므로 as_posix()는 사용하지 않고
    #      str()로 변환 후 DuckDB가 처리하도록 함
    abs_path = str(Path(other_db_path).resolve())
    # Why: 경로에 single-quote가 포함되면 SQL 문법이 깨짐 (UNC 경로 등)
    safe_path = abs_path.replace("'", "''")

    conn.execute(f"ATTACH '{safe_path}' AS {safe_alias} (READ_ONLY)")
    try:
        yield safe_alias
    finally:
        try:
            conn.execute(f"DETACH {safe_alias}")
        except duckdb.Error:
            logger.warning("DETACH 실패: %s", safe_alias, exc_info=True)


def compare_engagements(
    conn: duckdb.DuckDBPyConnection,
    current_batch: str,
    prior_batch: str,
    alias: str,
) -> pd.DataFrame:
    """연도 비교 통계 — 건수·금액·위험 분포.

    Why: 감사인이 전기 대비 당기의 이상치 증감을 한눈에 파악할 수 있어야 한다.
         ATTACH된 상태에서 호출해야 함 (attached_engagement 내부에서 사용).
    """
    sql = f"""
        SELECT 'current' AS period,
               COUNT(*)           AS row_count,
               SUM(debit_amount)  AS total_debit,
               AVG(anomaly_score) AS avg_anomaly_score
        FROM general_ledger
        WHERE upload_batch_id = ?
        UNION ALL
        SELECT 'prior',
               COUNT(*),
               SUM(debit_amount),
               AVG(anomaly_score)
        FROM {alias}.general_ledger
        WHERE upload_batch_id = ?
    """
    return conn.execute(sql, [current_batch, prior_batch]).fetchdf()
