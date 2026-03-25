"""DuckDB 테이블 DDL 정의 및 초기화.

Why: 4개 테이블 + 1 VIEW의 DDL을 정의하고 일괄 실행하는 초기화 함수를 제공한다.
     connection.py에서 최초 커넥션 생성 시 호출.
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

# ── DDL 정의 ─────────────────────────────────────────────────────
# Why: ORM 없이 경량 구현. DuckDB DDL은 단순하므로 Python dict + SQL 문자열로 충분.
#      VIEW는 테이블 생성 후 실행해야 하므로 dict 순서(Python 3.7+ 보장)에 의존.

SCHEMA_DDL: dict[str, str] = {
    # ── 테이블 ──
    "general_ledger": """
        CREATE TABLE IF NOT EXISTS general_ledger (
            -- 원본 (schema.yaml 기준 20개 + fiscal_period 1개)
            document_id       VARCHAR NOT NULL,
            company_code      VARCHAR,
            fiscal_year       INTEGER,
            fiscal_period     INTEGER,
            posting_date      TIMESTAMP NOT NULL,
            document_date     TIMESTAMP,
            document_type     VARCHAR,
            line_number       INTEGER,
            gl_account        VARCHAR NOT NULL,
            debit_amount      DOUBLE DEFAULT 0,
            credit_amount     DOUBLE DEFAULT 0,
            local_amount      DOUBLE,
            currency          VARCHAR,
            cost_center       VARCHAR,
            profit_center     VARCHAR,
            dc_indicator      VARCHAR,
            line_text         VARCHAR,
            header_text       VARCHAR,
            created_by        VARCHAR,
            source            VARCHAR,
            business_process  VARCHAR,
            -- 파생변수 (18종, feature/engine.py EXPECTED_COLUMNS)
            is_weekend              BOOLEAN,
            is_after_hours          BOOLEAN,
            is_period_end           BOOLEAN,
            days_backdated          INTEGER,
            fiscal_period_mismatch  BOOLEAN,
            is_holiday              BOOLEAN,
            is_near_threshold       BOOLEAN,
            exceeds_threshold       BOOLEAN,
            amount_zscore           DOUBLE,
            amount_magnitude        DOUBLE,
            is_round_number         BOOLEAN,
            is_manual_je            BOOLEAN,
            is_intercompany         BOOLEAN,
            is_revenue_account      BOOLEAN,
            first_digit             INTEGER,
            is_suspense_account     BOOLEAN,
            description_quality     VARCHAR,
            has_risk_keyword        VARCHAR,
            -- 탐지 결과 (3종, score_aggregator)
            anomaly_score   DOUBLE,
            risk_level      VARCHAR,
            flagged_rules   VARCHAR,
            -- 메타
            upload_batch_id  VARCHAR,
            created_at       TIMESTAMP DEFAULT current_timestamp
        )
    """,

    "anomaly_flags": """
        CREATE TABLE IF NOT EXISTS anomaly_flags (
            upload_batch_id  VARCHAR,
            document_id      VARCHAR NOT NULL,
            line_number      INTEGER,
            track_name       VARCHAR NOT NULL,
            rule_code        VARCHAR NOT NULL,
            score            DOUBLE NOT NULL,
            created_at       TIMESTAMP DEFAULT current_timestamp
        )
    """,

    "benford_summary": """
        CREATE TABLE IF NOT EXISTS benford_summary (
            upload_batch_id  VARCHAR NOT NULL,
            sample_size      INTEGER,
            mad              DOUBLE,
            mad_conformity   VARCHAR,
            chi2_statistic   DOUBLE,
            chi2_p_value     DOUBLE,
            ks_statistic     DOUBLE,
            ks_p_value       DOUBLE,
            is_conforming    BOOLEAN,
            confidence       VARCHAR,
            created_at       TIMESTAMP DEFAULT current_timestamp
        )
    """,

    "benford_digits": """
        CREATE TABLE IF NOT EXISTS benford_digits (
            upload_batch_id  VARCHAR NOT NULL,
            digit            INTEGER NOT NULL,
            observed_freq    DOUBLE,
            expected_freq    DOUBLE,
            deviation        DOUBLE,
            created_at       TIMESTAMP DEFAULT current_timestamp
        )
    """,

    # ── VIEW (테이블 생성 후 실행) ──
    "anomaly_flag_summary": """
        CREATE VIEW IF NOT EXISTS anomaly_flag_summary AS
        SELECT
            upload_batch_id,
            track_name,
            rule_code,
            COUNT(*)   AS flagged_count,
            AVG(score) AS avg_score,
            MAX(score) AS max_score
        FROM anomaly_flags
        GROUP BY upload_batch_id, track_name, rule_code
    """,
}


# ── 컬럼 목록 상수 ──────────────────────────────────────────────
# Why: loader에서 DataFrame → DuckDB 적재 시 컬럼 순서 정합성 보장용.
#      DDL 컬럼 순서와 100% 동기화 필수. created_at은 DEFAULT이므로 제외.

GENERAL_LEDGER_COLUMNS: list[str] = [
    # 원본
    "document_id", "company_code", "fiscal_year", "fiscal_period",
    "posting_date", "document_date", "document_type", "line_number",
    "gl_account", "debit_amount", "credit_amount",
    "local_amount", "currency", "cost_center", "profit_center", "dc_indicator",
    "line_text", "header_text", "created_by", "source", "business_process",
    # 파생변수 (18종)
    "is_weekend", "is_after_hours", "is_period_end",
    "days_backdated", "fiscal_period_mismatch", "is_holiday",
    "is_near_threshold", "exceeds_threshold", "amount_zscore",
    "amount_magnitude", "is_round_number",
    "is_manual_je", "is_intercompany", "is_revenue_account",
    "first_digit", "is_suspense_account",
    "description_quality", "has_risk_keyword",
    # 탐지 결과
    "anomaly_score", "risk_level", "flagged_rules",
    # 메타
    "upload_batch_id",
]

ANOMALY_FLAGS_COLUMNS: list[str] = [
    "upload_batch_id", "document_id", "line_number",
    "track_name", "rule_code", "score",
]

BENFORD_SUMMARY_COLUMNS: list[str] = [
    "upload_batch_id", "sample_size", "mad", "mad_conformity",
    "chi2_statistic", "chi2_p_value", "ks_statistic", "ks_p_value",
    "is_conforming", "confidence",
]

BENFORD_DIGITS_COLUMNS: list[str] = [
    "upload_batch_id", "digit", "observed_freq", "expected_freq", "deviation",
]


# ── 초기화 ───────────────────────────────────────────────────────

def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """모든 테이블 DDL + VIEW를 실행한다.

    CREATE TABLE/VIEW IF NOT EXISTS로 멱등성 보장.
    SCHEMA_DDL dict 순서대로 실행하므로, VIEW는 테이블 뒤에 위치해야 한다.
    """
    for name, ddl in SCHEMA_DDL.items():
        conn.execute(ddl)
        logger.debug("DDL 실행 완료: %s", name)

    logger.info(
        "스키마 초기화 완료: %d개 오브젝트 (%s)",
        len(SCHEMA_DDL),
        ", ".join(SCHEMA_DDL.keys()),
    )
