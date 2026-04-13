"""전수 데이터 프로파일 추출 — LLM 판정용.

규칙/임계값 없이 집계만 수행. 결과를 JSON으로 저장하면
Claude Code가 읽고 "실제 기업과 뭐가 다른지" 판정한다.

실행: uv run python -m tests.datasynth_quality_gate3.extract_profile
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb

_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "data" / "journal" / "primary" / "datasynth"
)
_CSV = _DATA_DIR / "journal_entries.csv"
_OUT = Path(__file__).parent / "results" / "data_profile.json"


def _q(con, sql):
    """쿼리 실행 후 결과 반환."""
    return con.execute(sql).fetchall()


def _q1(con, sql):
    """단일 값 반환."""
    return con.execute(sql).fetchone()[0]


def extract(con: duckdb.DuckDBPyConnection) -> dict:
    """전수 프로파일 추출."""
    p = {}

    # ── 1. 기본 현황 ──
    p["total_rows"] = _q1(con, "SELECT COUNT(*) FROM je")
    p["total_docs"] = _q1(con, "SELECT COUNT(DISTINCT document_id) FROM je")
    p["lines_per_doc_avg"] = round(_q1(con, """
        SELECT AVG(cnt) FROM (SELECT COUNT(*) cnt FROM je GROUP BY document_id)
    """), 2)
    p["lines_per_doc_percentiles"] = dict(_q(con, """
        SELECT unnest(['P25','P50','P75','P90','P99']) AS pct,
               unnest(quantile_cont(cnt, [0.25,0.5,0.75,0.9,0.99])) AS val
        FROM (SELECT COUNT(*)::DOUBLE cnt FROM je GROUP BY document_id)
    """))

    # ── 2. 회사별 ──
    p["by_company"] = {r[0]: {"docs": r[1], "rows": r[2]} for r in _q(con, """
        SELECT company_code, COUNT(DISTINCT document_id), COUNT(*)
        FROM je GROUP BY company_code ORDER BY company_code
    """)}

    # ── 3. 금액 분포 (라인 레벨) ──
    p["line_amount"] = dict(_q(con, """
        SELECT unnest(['min','P1','P5','P25','median','P75','P95','P99','max','mean','std']) AS stat,
               unnest([
                   MIN(amt), PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY amt),
                   PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY amt),
                   PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY amt),
                   MEDIAN(amt),
                   PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY amt),
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY amt),
                   PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY amt),
                   MAX(amt), AVG(amt), STDDEV(amt)
               ]) AS val
        FROM (
            SELECT CASE WHEN CAST(debit_amount AS DOUBLE)>0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END AS amt
            FROM je WHERE CAST(debit_amount AS DOUBLE)>0 OR CAST(credit_amount AS DOUBLE)>0
        )
    """))

    # ── 4. 금액 분포 (전표 단위) ──
    p["doc_amount"] = dict(_q(con, """
        SELECT unnest(['median','mean','P95','P99','max']) AS stat,
               unnest([
                   MEDIAN(t), AVG(t),
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY t),
                   PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY t),
                   MAX(t)
               ]) AS val
        FROM (SELECT SUM(CAST(debit_amount AS DOUBLE)) t FROM je GROUP BY document_id)
    """))

    # ── 5. 차대변 균형 ──
    p["balance"] = dict(_q(con, """
        SELECT unnest(['total_docs','unbalanced','max_diff']) AS k,
               unnest([
                   COUNT(*)::DOUBLE,
                   SUM(CASE WHEN ABS(d-c)>1 THEN 1 ELSE 0 END)::DOUBLE,
                   MAX(ABS(d-c))
               ]) AS v
        FROM (SELECT SUM(CAST(debit_amount AS DOUBLE)) d,
                     SUM(CAST(credit_amount AS DOUBLE)) c
              FROM je GROUP BY document_id)
    """))

    # ── 6. 월별 전표 건수 ──
    p["monthly_docs"] = {int(r[0]): r[1] for r in _q(con, """
        SELECT EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) m,
               COUNT(DISTINCT document_id) FROM je GROUP BY m ORDER BY m
    """)}

    # ── 7. 요일별 ──
    dow_names = {0: "일", 1: "월", 2: "화", 3: "수", 4: "목", 5: "금", 6: "토"}
    p["dow_docs"] = {dow_names[int(r[0])]: r[1] for r in _q(con, """
        SELECT EXTRACT(DOW FROM CAST(posting_date AS TIMESTAMP)) d,
               COUNT(DISTINCT document_id) FROM je GROUP BY d ORDER BY d
    """)}

    # ── 8. 시간대별 ──
    p["hourly_docs"] = {int(r[0]): r[1] for r in _q(con, """
        SELECT EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) h,
               COUNT(DISTINCT document_id) FROM je GROUP BY h ORDER BY h
    """)}

    # ── 9. GL 대분류 ──
    p["gl_category"] = {r[0]: r[1] for r in _q(con, """
        SELECT CASE WHEN gl_account IS NULL OR CAST(gl_account AS VARCHAR)='' THEN 'NaN'
                    WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '1_자산'
                    WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '2_부채'
                    WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '3_자본'
                    WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '4_수익'
                    WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '5_비용'
                    ELSE '9_기타' END AS cat, COUNT(*) FROM je GROUP BY cat ORDER BY cat
    """)}

    # ── 10. 상위 GL 계정 ──
    p["top_gl_accounts"] = {r[0]: r[1] for r in _q(con, """
        SELECT CAST(gl_account AS VARCHAR), COUNT(*) cnt
        FROM je WHERE gl_account IS NOT NULL GROUP BY 1 ORDER BY cnt DESC LIMIT 30
    """)}

    # ── 11. 프로세스별 ──
    p["by_process"] = {r[0]: r[1] for r in _q(con, """
        SELECT business_process, COUNT(DISTINCT document_id)
        FROM je GROUP BY 1 ORDER BY 2 DESC
    """)}

    # ── 12. user_persona별 ──
    p["by_persona"] = {r[0]: r[1] for r in _q(con, """
        SELECT user_persona, COUNT(DISTINCT document_id)
        FROM je GROUP BY 1 ORDER BY 2 DESC
    """)}

    # ── 13. source별 ──
    p["by_source"] = {r[0]: r[1] for r in _q(con, """
        SELECT source, COUNT(DISTINCT document_id)
        FROM je GROUP BY 1 ORDER BY 2 DESC
    """)}

    # ── 14. document_type별 ──
    p["by_doc_type"] = {r[0]: r[1] for r in _q(con, """
        SELECT document_type, COUNT(DISTINCT document_id)
        FROM je GROUP BY 1 ORDER BY 2 DESC
    """)}

    # ── 15. fraud / anomaly ──
    p["fraud_total"] = _q1(con, "SELECT COUNT(DISTINCT document_id) FROM je WHERE is_fraud='true'")
    p["anomaly_total"] = _q1(con, "SELECT COUNT(DISTINCT document_id) FROM je WHERE is_anomaly='true'")
    p["fraud_by_type"] = {r[0]: r[1] for r in _q(con, """
        SELECT fraud_type, COUNT(DISTINCT document_id) FROM je
        WHERE is_fraud='true' AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1 ORDER BY 2 DESC
    """)}
    p["anomaly_by_type"] = {r[0]: r[1] for r in _q(con, """
        SELECT anomaly_type, COUNT(DISTINCT document_id) FROM je
        WHERE is_anomaly='true' AND anomaly_type IS NOT NULL
          AND CAST(anomaly_type AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """)}
    p["fraud_by_month"] = {int(r[0]): {"total": r[1], "fraud": r[2], "rate": round(r[3], 4)} for r in _q(con, """
        SELECT EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) m,
               COUNT(DISTINCT document_id),
               COUNT(DISTINCT CASE WHEN is_fraud='true' THEN document_id END),
               COUNT(DISTINCT CASE WHEN is_fraud='true' THEN document_id END)*1.0
                   / COUNT(DISTINCT document_id)
        FROM je GROUP BY m ORDER BY m
    """)}

    # ── 16. 내부통제 ──
    p["sod_violations"] = _q1(con, "SELECT COUNT(DISTINCT document_id) FROM je WHERE sod_violation='true'")
    p["sod_types"] = {r[0]: r[1] for r in _q(con, """
        SELECT sod_conflict_type, COUNT(DISTINCT document_id) FROM je
        WHERE sod_violation='true' AND sod_conflict_type IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
    """)}
    p["self_approval"] = _q1(con, """
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE created_by = approved_by AND created_by IS NOT NULL
    """)

    # ── 17. 승인자 편중도 ──
    p["top_approvers"] = {r[0]: r[1] for r in _q(con, """
        SELECT approved_by, COUNT(DISTINCT document_id) cnt FROM je
        WHERE approved_by IS NOT NULL AND CAST(approved_by AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1 ORDER BY cnt DESC LIMIT 10
    """)}

    # ── 18. 사용자 ID 패턴 ──
    p["user_id_sample"] = _q(con, """
        SELECT DISTINCT created_by FROM je
        WHERE created_by NOT LIKE 'SYSTEM-%' AND created_by IS NOT NULL
        LIMIT 20
    """)
    p["user_id_sample"] = [r[0] for r in p["user_id_sample"]]

    # ── 19. header_text 상위 ──
    p["top_headers"] = {r[0]: r[1] for r in _q(con, """
        SELECT header_text, COUNT(DISTINCT document_id) cnt
        FROM je WHERE header_text IS NOT NULL
        GROUP BY 1 ORDER BY cnt DESC LIMIT 30
    """)}

    # ── 20. line_text 상위 ──
    p["top_line_texts"] = {r[0]: r[1] for r in _q(con, """
        SELECT line_text, COUNT(*) cnt FROM je
        WHERE line_text IS NOT NULL AND CAST(line_text AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1 ORDER BY cnt DESC LIMIT 30
    """)}

    # ── 21. reference 접두사 ──
    p["reference_prefixes"] = {r[0]: r[1] for r in _q(con, """
        SELECT REGEXP_EXTRACT(reference, '^([A-Z]+-)', 1) AS pfx, COUNT(DISTINCT document_id)
        FROM je WHERE reference IS NOT NULL GROUP BY pfx
        HAVING pfx IS NOT NULL ORDER BY 2 DESC
    """)}

    # ── 22. supporting_doc_type ──
    p["supporting_doc_types"] = {r[0]: r[1] for r in _q(con, """
        SELECT supporting_doc_type, COUNT(DISTINCT document_id) FROM je
        WHERE supporting_doc_type IS NOT NULL GROUP BY 1 ORDER BY 2 DESC
    """)}

    # ── 23. IP 대역 ──
    p["ip_prefixes_by_company"] = {r[0]: {r[1]: r[2]} for r in _q(con, """
        SELECT company_code,
               SPLIT_PART(ip_address,'.',1)||'.'||SPLIT_PART(ip_address,'.',2) AS pfx,
               COUNT(DISTINCT document_id) FROM je
        WHERE ip_address IS NOT NULL GROUP BY 1,2 ORDER BY 1,3 DESC
    """)}

    # ── 24. 거래처 ──
    p["top_trading_partners"] = {r[0]: r[1] for r in _q(con, """
        SELECT auxiliary_account_label, COUNT(*) cnt FROM je
        WHERE auxiliary_account_label IS NOT NULL
          AND CAST(auxiliary_account_label AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1 ORDER BY cnt DESC LIMIT 15
    """)}

    # ── 25. 필드 채움률 ──
    all_cols = [r[0] for r in _q(con, "SELECT column_name FROM (DESCRIBE je)")]
    fill = {}
    for col in all_cols:
        filled = _q1(con, f"""
            SELECT COUNT(*) FROM je
            WHERE {col} IS NOT NULL
              AND CAST({col} AS VARCHAR) NOT IN ('','nan')
        """)
        fill[col] = round(filled / p["total_rows"] * 100, 2)
    p["field_fill_rate"] = fill

    # ── 26. local_amount vs debit/credit ──
    p["local_amount_mismatch"] = _q1(con, """
        SELECT COUNT(*) FROM je
        WHERE CAST(local_amount AS DOUBLE) IS NOT NULL
          AND ABS(CAST(local_amount AS DOUBLE)
              - CASE WHEN CAST(debit_amount AS DOUBLE)>0
                     THEN CAST(debit_amount AS DOUBLE)
                     ELSE CAST(credit_amount AS DOUBLE) END) > 1
          AND (CAST(debit_amount AS DOUBLE)>0 OR CAST(credit_amount AS DOUBLE)>0)
    """)
    p["local_amount_negative"] = _q1(con, """
        SELECT COUNT(*) FROM je WHERE CAST(local_amount AS DOUBLE) < 0
    """)

    # ── 27. invoice/supply 비율 ──
    p["invoice_supply_ratio"] = dict(_q(con, """
        SELECT unnest(['vat10','tax_free','other']) AS k,
               unnest([
                   COUNT(*) FILTER (WHERE ABS(inv/sup - 1.1)<0.01),
                   COUNT(*) FILTER (WHERE ABS(inv/sup - 1.0)<0.01),
                   COUNT(*) FILTER (WHERE ABS(inv/sup - 1.1)>=0.01 AND ABS(inv/sup - 1.0)>=0.01)
               ]::BIGINT[]) AS v
        FROM (
            SELECT CAST(invoice_amount AS DOUBLE) inv, CAST(supply_amount AS DOUBLE) sup
            FROM je WHERE CAST(supply_amount AS DOUBLE)>0
                AND invoice_amount IS NOT NULL AND supply_amount IS NOT NULL
        ) sub
    """))

    # ── 28. GL 자릿수 ──
    p["gl_digit_distribution"] = {r[0]: r[1] for r in _q(con, """
        SELECT LENGTH(CAST(gl_account AS VARCHAR)) AS digits, COUNT(*)
        FROM je WHERE gl_account IS NOT NULL
          AND CAST(gl_account AS VARCHAR) NOT IN ('','nan')
        GROUP BY digits ORDER BY digits
    """)}

    # ── 29. process × GL 대분류 교차표 ──
    p["process_gl_cross"] = {}
    for r in _q(con, """
        SELECT business_process,
               CASE WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                    WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                    WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                    WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '수익'
                    WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '비용'
                    ELSE '기타' END AS cat,
               COUNT(*) FROM je
        WHERE gl_account IS NOT NULL GROUP BY 1,2 ORDER BY 1,2
    """):
        p["process_gl_cross"].setdefault(r[0], {})[r[1]] = r[2]

    # ── 30. persona × source 교차표 ──
    p["persona_source_cross"] = {}
    for r in _q(con, """
        SELECT user_persona, source, COUNT(DISTINCT document_id)
        FROM je GROUP BY 1,2 ORDER BY 1,2
    """):
        p["persona_source_cross"].setdefault(r[0], {})[r[1]] = r[2]

    # ── 31. 적요 키워드별 GL 대분류 분포 ──
    keywords = ["매출채권","매입채무","급여","감가상각","배당","리스","재고","미지급","선급","차입금","법인세"]
    p["linetext_gl_cross"] = {}
    for kw in keywords:
        rows = _q(con, f"""
            SELECT CASE WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                        WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                        WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                        WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '수익'
                        WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '비용'
                        ELSE '기타' END AS cat, COUNT(*)
            FROM je WHERE line_text LIKE '%{kw}%' AND gl_account IS NOT NULL
            GROUP BY cat ORDER BY 2 DESC
        """)
        if rows:
            p["linetext_gl_cross"][kw] = {r[0]: r[1] for r in rows}

    # ── 32. header 키워드별 전표 내 GL 존재 여부 ──
    header_kws = ["감가상각","자산손상","매출채권 회수","급여","외화평가","이연수익","법인세"]
    p["header_gl_presence"] = {}
    for kw in header_kws:
        row = _q(con, f"""
            WITH target AS (
                SELECT DISTINCT document_id FROM je
                WHERE header_text LIKE '%{kw}%'
            ),
            doc_cats AS (
                SELECT document_id, LIST(DISTINCT
                    CASE WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                         WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                         WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                         WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '수익'
                         WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '비용'
                         ELSE '기타' END
                ) AS cats FROM je GROUP BY document_id
            )
            SELECT COUNT(*),
                   SUM(CASE WHEN list_contains(dc.cats,'비용') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN list_contains(dc.cats,'자산') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN list_contains(dc.cats,'부채') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN list_contains(dc.cats,'수익') THEN 1 ELSE 0 END)
            FROM target t JOIN doc_cats dc ON t.document_id = dc.document_id
        """)
        if row:
            r = row[0]
            p["header_gl_presence"][kw] = {
                "total": r[0], "has_비용": r[1], "has_자산": r[2],
                "has_부채": r[3], "has_수익": r[4],
            }

    # ── 33. 전표 샘플 (프로세스별 2건씩) ──
    p["sample_entries"] = {}
    for proc in ["P2P", "O2C", "R2R", "H2R", "TRE", "A2R"]:
        docs = _q(con, f"""
            SELECT DISTINCT document_id FROM je
            WHERE business_process='{proc}' AND is_fraud!='true'
            LIMIT 2
        """)
        for (doc_id,) in docs:
            lines = _q(con, f"""
                SELECT header_text, CAST(gl_account AS VARCHAR),
                       CAST(debit_amount AS DOUBLE), CAST(credit_amount AS DOUBLE),
                       line_text, created_by, user_persona, source
                FROM je WHERE document_id='{doc_id}' ORDER BY CAST(line_number AS INT)
            """)
            entry = {
                "process": proc,
                "header": lines[0][0] if lines else "",
                "created_by": lines[0][5] if lines else "",
                "persona": lines[0][6] if lines else "",
                "source": lines[0][7] if lines else "",
                "lines": [
                    {"gl": r[1], "debit": r[2], "credit": r[3], "text": r[4]}
                    for r in lines
                ],
            }
            p["sample_entries"].setdefault(proc, []).append(entry)

    # ── 34. fraud 전표 샘플 (타입별 1건) ──
    p["fraud_samples"] = {}
    fraud_types = _q(con, """
        SELECT DISTINCT fraud_type FROM je
        WHERE is_fraud='true' AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) NOT IN ('','nan')
        LIMIT 8
    """)
    for (ft,) in fraud_types:
        doc_id = _q1(con, f"""
            SELECT document_id FROM je WHERE fraud_type='{ft}' LIMIT 1
        """)
        lines = _q(con, f"""
            SELECT header_text, CAST(gl_account AS VARCHAR),
                   CAST(debit_amount AS DOUBLE), CAST(credit_amount AS DOUBLE),
                   line_text
            FROM je WHERE document_id='{doc_id}' ORDER BY CAST(line_number AS INT)
        """)
        p["fraud_samples"][ft] = {
            "header": lines[0][0] if lines else "",
            "lines": [
                {"gl": r[1], "debit": r[2], "credit": r[3], "text": r[4]}
                for r in lines
            ],
        }

    return p


def main():
    start = time.perf_counter()
    print("=" * 60)
    print("데이터 프로파일 추출 (LLM 판정용)")
    print("=" * 60)

    con = duckdb.connect()
    print(f"\n  CSV 로드: {_CSV}")
    con.execute(f"""
        CREATE TABLE je AS
        SELECT * FROM read_csv_auto('{_CSV.as_posix()}', all_varchar=true)
    """)
    rows = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    print(f"  -> {rows:,}행 로드 완료")

    print("\n  프로파일 추출 중...")
    profile = extract(con)
    con.close()

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2, default=str)

    elapsed = time.perf_counter() - start
    print(f"  -> {_OUT} 저장 완료 ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
