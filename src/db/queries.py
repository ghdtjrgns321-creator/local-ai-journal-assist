"""프리셋 쿼리 — 대시보드·드릴다운용 Raw 데이터 추출.

Why: SQL 사전 집계는 대시보드 필터와 충돌.
     Raw 데이터를 DB에서 퍼온 뒤 pandas로 집계한다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

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
               approval_date, approval_level, reference,
               is_fraud, fraud_type, is_anomaly, anomaly_type,
               sod_violation, sod_conflict_type,
               anomaly_score, risk_level, flagged_rules,
               first_digit,
               supervised_score, unsupervised_score, duplicate_score,
               supervised_model_id, unsupervised_model_id, duplicate_model_id,
               ml_scored_at
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
    # ── 배치 이력 (Batch History Loader) ──
    "list_batches": """
        SELECT upload_batch_id, file_name, row_count,
               anomaly_count, high_risk_count, created_at
        FROM upload_batches
        ORDER BY created_at DESC
    """,
    "batch_meta": """
        SELECT upload_batch_id, file_name, row_count,
               anomaly_count, high_risk_count,
               phase2_training_report_id, phase2_inference_contract,
               phase2_promotion_policy, phase2_inference_mode,
               detector_statuses_json,
               phase1_case_run_id, phase1_case_path, phase1_case_count,
               phase1_macro_finding_count, phase1_top_theme_ids,
               phase1_case_schema_version,
               created_at, warnings
        FROM upload_batches
        WHERE upload_batch_id = ?
    """,
    # ── Whitelist (HITL 예외 처리) ──
    "performance_reports_by_batch": """
        SELECT report_id, upload_batch_id, source_kind, phase_scope,
               metric_confidence, total_docs, flagged_docs, high_risk_docs,
               high_risk_ratio, precision, recall, f1,
               whitelist_removed_docs, false_positive_docs,
               confirmed_issue_docs, created_at
        FROM performance_reports
        WHERE upload_batch_id = ?
        ORDER BY created_at DESC
    """,
    "latest_performance_report": """
        SELECT report_id, upload_batch_id, source_kind, phase_scope,
               metric_confidence, total_docs, flagged_docs, high_risk_docs,
               high_risk_ratio, precision, recall, f1,
               whitelist_removed_docs, false_positive_docs,
               confirmed_issue_docs, created_at
        FROM performance_reports
        WHERE upload_batch_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """,
    "performance_rule_metrics_by_report": """
        SELECT report_id, track_name, rule_code, label_docs, flagged_docs,
               tp_docs, fp_docs, fn_docs, precision, recall, f1,
               breakdown_json, score_bands_json, created_at
        FROM performance_rule_metrics
        WHERE report_id = ?
        ORDER BY track_name, rule_code
    """,
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
    # ── Audit Log (감사증적) ──
    "insert_audit_log": """
        INSERT INTO audit_log
        (action, actor, company_id, engagement_id, batch_id, target_id, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "list_audit_log": """
        SELECT id, action, actor, company_id, engagement_id,
               batch_id, target_id, details, created_at
        FROM audit_log
        ORDER BY created_at DESC
        LIMIT ?
    """,
    "audit_log_by_batch": """
        SELECT id, action, actor, target_id, details, created_at
        FROM audit_log
        WHERE batch_id = ?
        ORDER BY created_at DESC
    """,
    "audit_log_by_engagement": """
        SELECT id, action, actor, batch_id, target_id, details, created_at
        FROM audit_log
        WHERE company_id = ? AND engagement_id = ?
        ORDER BY created_at DESC
    """,
    "insert_feedback_event": """
        INSERT INTO feedback_events (
            company_id, engagement_id, batch_id, document_id,
            track_name, rule_code, event_type, decision,
            reason, payload_json, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "feedback_events_by_batch": """
        SELECT id, company_id, engagement_id, batch_id, document_id,
               track_name, rule_code, event_type, decision,
               reason, payload_json, created_by, created_at
        FROM feedback_events
        WHERE batch_id = ?
        ORDER BY created_at DESC, id DESC
    """,
    "feedback_events_by_document": """
        SELECT id, company_id, engagement_id, batch_id, document_id,
               track_name, rule_code, event_type, decision,
               reason, payload_json, created_by, created_at
        FROM feedback_events
        WHERE batch_id = ? AND document_id = ?
        ORDER BY created_at DESC, id DESC
    """,
    "feedback_events_by_engagement": """
        SELECT id, company_id, engagement_id, batch_id, document_id,
               track_name, rule_code, event_type, decision,
               reason, payload_json, created_by, created_at
        FROM feedback_events
        WHERE company_id = ? AND engagement_id = ?
        ORDER BY created_at DESC, id DESC
    """,
    # ── Document Flow 조회 ──
    "document_flow_chain": """
        SELECT source_doc_type, source_doc_id,
               target_doc_type, target_doc_id,
               reference_type, reference_amount, reference_date
        FROM document_references
        WHERE upload_batch_id = ?
        ORDER BY reference_date
    """,
    "three_way_match": """
        WITH batch AS (SELECT ? AS bid)
        SELECT
            poh.document_id   AS po_id,
            grh.document_id   AS gr_id,
            vih.document_id   AS vi_id,
            poh.vendor_id,
            pol.material_id,
            pol.net_amount    AS po_amount,
            grl.net_amount    AS gr_amount,
            vil.net_amount    AS vi_amount,
            ABS(pol.net_amount - vil.net_amount) AS price_variance
        FROM batch, purchase_order_headers poh
        JOIN purchase_order_lines pol
          ON poh.document_id = pol.document_id
        LEFT JOIN goods_receipt_headers grh
          ON grh.purchase_order_id = poh.document_id
          AND grh.upload_batch_id = batch.bid
        LEFT JOIN goods_receipt_lines grl
          ON grh.document_id = grl.document_id
          AND pol.line_number = grl.line_number
        LEFT JOIN vendor_invoice_headers vih
          ON vih.purchase_order_id = poh.document_id
          AND vih.upload_batch_id = batch.bid
        LEFT JOIN vendor_invoice_lines vil
          ON vih.document_id = vil.document_id
          AND pol.line_number = vil.line_number
        WHERE poh.upload_batch_id = batch.bid
    """,
    "gl_document_link": """
        SELECT gl.document_id AS journal_entry_id,
               gl.posting_date, gl.debit_amount, gl.credit_amount,
               dr.source_doc_type, dr.source_doc_id
        FROM general_ledger gl
        JOIN document_references dr
          ON gl.document_id = dr.target_doc_id
          AND gl.upload_batch_id = dr.upload_batch_id
        WHERE gl.upload_batch_id = ?
    """,
    # ── Master Data 조회 ──
    "vendor_details": """
        SELECT vendor_id, name, vendor_type, is_one_time,
               is_intercompany, payment_terms, is_active, country
        FROM vendors
        WHERE upload_batch_id = ?
    """,
    "employee_details": """
        SELECT employee_id, user_id, display_name, persona,
               job_level, approval_limit, status, company_code,
               can_approve_je, can_approve_po, can_release_payment
        FROM employees
        WHERE upload_batch_id = ?
    """,
    # ── Labels 검증 ──
    "anomaly_label_stats": """
        SELECT anomaly_category, anomaly_subtype,
               COUNT(*) AS cnt, AVG(confidence) AS avg_conf,
               AVG(severity) AS avg_sev
        FROM anomaly_labels
        WHERE upload_batch_id = ?
        GROUP BY anomaly_category, anomaly_subtype
        ORDER BY cnt DESC
    """,
    "detection_accuracy": """
        SELECT al.anomaly_subtype,
               COUNT(DISTINCT al.document_id) AS labeled,
               COUNT(DISTINCT af.document_id) AS detected
        FROM anomaly_labels al
        LEFT JOIN anomaly_flags af
          ON al.document_id = af.document_id
          AND al.upload_batch_id = af.upload_batch_id
        WHERE al.upload_batch_id = ?
        GROUP BY al.anomaly_subtype
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
