"""정상 분개 대비 비교 + 라벨 누수 점검."""
from __future__ import annotations

from pathlib import Path
import duckdb

ROOT = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
DATA = ROOT / "data/journal/primary/datasynth_manipulation"
JE = (DATA / "journal_entries.csv").as_posix()
TRUTH = (DATA / "labels/manipulated_entry_truth.csv").as_posix()


def section(title: str) -> None:
    print("\n" + "=" * 88 + "\n" + title + "\n" + "=" * 88)


con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW je    AS SELECT * FROM read_csv_auto('{JE}', header=True);
    CREATE VIEW truth AS SELECT * FROM read_csv_auto('{TRUTH}', header=True);
    CREATE VIEW jt AS
      SELECT je.*, t.manipulation_scenario
      FROM je LEFT JOIN truth t USING(document_id);
    """
)

# 1) 정상 vs 조작 - 핵심 지표 베이스라인
section("A. NORMAL vs MANIPULATED 베이스라인")
print(con.execute(
    """
    WITH base AS (
      SELECT document_id,
             ANY_VALUE(manipulation_scenario)        AS scenario,
             ANY_VALUE(document_type)                AS dt,
             ANY_VALUE(business_process)             AS bp,
             ANY_VALUE(source)                       AS src,
             ANY_VALUE(sod_violation)                AS sodv,
             ANY_VALUE(has_attachment)               AS att,
             ANY_VALUE(created_by)                   AS cb,
             ANY_VALUE(approved_by)                  AS ab,
             EXTRACT(MONTH FROM CAST(ANY_VALUE(posting_date) AS TIMESTAMP)) AS pmonth,
             EXTRACT(HOUR  FROM CAST(ANY_VALUE(posting_date) AS TIMESTAMP)) AS phour,
             EXTRACT(DOW   FROM CAST(ANY_VALUE(posting_date) AS TIMESTAMP)) AS pdow,
             SUM(local_amount)                       AS amt
      FROM jt GROUP BY document_id
    )
    SELECT
      CASE WHEN scenario IS NULL THEN 'NORMAL' ELSE 'MANIP' END AS grp,
      COUNT(*)                                                          AS docs,
      AVG(CASE WHEN dt='AA' THEN 1 ELSE 0 END)::DECIMAL(6,3)             AS pct_AA,
      AVG(CASE WHEN src='manual' OR src='adjustment' THEN 1 ELSE 0 END)::DECIMAL(6,3) AS pct_man_adj,
      AVG(CASE WHEN sodv THEN 1 ELSE 0 END)::DECIMAL(6,3)                 AS pct_sodv,
      AVG(CASE WHEN cb=ab THEN 1 ELSE 0 END)::DECIMAL(6,3)                AS pct_self,
      AVG(CASE WHEN att THEN 1 ELSE 0 END)::DECIMAL(6,3)                  AS pct_attach,
      AVG(CASE WHEN pmonth=12 THEN 1 ELSE 0 END)::DECIMAL(6,3)            AS pct_dec,
      AVG(CASE WHEN phour NOT BETWEEN 8 AND 18 THEN 1 ELSE 0 END)::DECIMAL(6,3) AS pct_offhour,
      AVG(CASE WHEN pdow IN (0,6) THEN 1 ELSE 0 END)::DECIMAL(6,3)        AS pct_weekend,
      AVG(amt)::BIGINT                                                    AS avg_amt
    FROM base GROUP BY 1
    """
).fetchdf().to_string(index=False))

# 2) 시나리오별 동일 지표
section("B. 시나리오별 핵심 지표")
print(con.execute(
    """
    WITH base AS (
      SELECT document_id,
             ANY_VALUE(manipulation_scenario)        AS scenario,
             ANY_VALUE(document_type)                AS dt,
             ANY_VALUE(source)                       AS src,
             ANY_VALUE(sod_violation)                AS sodv,
             ANY_VALUE(has_attachment)               AS att,
             ANY_VALUE(created_by)                   AS cb,
             ANY_VALUE(approved_by)                  AS ab,
             EXTRACT(MONTH FROM CAST(ANY_VALUE(posting_date) AS TIMESTAMP)) AS pmonth,
             EXTRACT(HOUR  FROM CAST(ANY_VALUE(posting_date) AS TIMESTAMP)) AS phour,
             EXTRACT(DOW   FROM CAST(ANY_VALUE(posting_date) AS TIMESTAMP)) AS pdow,
             SUM(local_amount)                       AS amt
      FROM jt WHERE manipulation_scenario IS NOT NULL
      GROUP BY document_id
    )
    SELECT scenario,
           COUNT(*)                                                          AS docs,
           AVG(CASE WHEN sodv THEN 1 ELSE 0 END)::DECIMAL(6,3)                AS pct_sodv,
           AVG(CASE WHEN cb=ab THEN 1 ELSE 0 END)::DECIMAL(6,3)               AS pct_self,
           AVG(CASE WHEN att THEN 1 ELSE 0 END)::DECIMAL(6,3)                 AS pct_attach,
           AVG(CASE WHEN pmonth=12 THEN 1 ELSE 0 END)::DECIMAL(6,3)           AS pct_dec,
           AVG(CASE WHEN pmonth IN (12,1) THEN 1 ELSE 0 END)::DECIMAL(6,3)    AS pct_dec_jan,
           AVG(CASE WHEN phour NOT BETWEEN 8 AND 18 THEN 1 ELSE 0 END)::DECIMAL(6,3) AS pct_offhour,
           AVG(CASE WHEN pdow IN (0,6) THEN 1 ELSE 0 END)::DECIMAL(6,3)       AS pct_weekend,
           AVG(amt)::BIGINT                                                   AS avg_amt
    FROM base GROUP BY 1 ORDER BY docs DESC
    """
).fetchdf().to_string(index=False))

# 3) embezzlement 라벨 누수 가능성 — line_text 'advance settlement clearing'
section("C. embezzlement 마커 'advance settlement clearing' 라벨 누수 점검")
print(con.execute(
    """
    SELECT
      SUM(CASE WHEN manipulation_scenario='embezzlement_concealment' THEN 1 ELSE 0 END) AS emb_lines,
      SUM(CASE WHEN line_text LIKE '%advance settlement clearing%' THEN 1 ELSE 0 END) AS marker_total,
      SUM(CASE WHEN manipulation_scenario='embezzlement_concealment'
             AND line_text LIKE '%advance settlement clearing%' THEN 1 ELSE 0 END) AS emb_with_marker,
      SUM(CASE WHEN manipulation_scenario IS NULL
             AND line_text LIKE '%advance settlement clearing%' THEN 1 ELSE 0 END) AS normal_with_marker,
      SUM(CASE WHEN manipulation_scenario IS NOT NULL AND manipulation_scenario<>'embezzlement_concealment'
             AND line_text LIKE '%advance settlement clearing%' THEN 1 ELSE 0 END) AS otherman_with_marker
    FROM jt
    """
).fetchdf().to_string(index=False))

# 4) circular RP — 다회사 순환 패턴이 실제로 있는가?
section("D. circular_related_party — 회사 순환 사이클 검출")
print("(a) 한 document_id의 trading_partner 분포 vs company_code")
print(con.execute(
    """
    SELECT je.document_id, je.company_code,
           STRING_AGG(DISTINCT je.trading_partner, ', ') AS partners,
           COUNT(DISTINCT je.trading_partner) AS partner_cnt,
           COUNT(*) AS lines
    FROM je JOIN truth USING(document_id)
    WHERE truth.manipulation_scenario='circular_related_party_transaction'
    GROUP BY 1,2 ORDER BY lines DESC LIMIT 10
    """
).fetchdf().to_string(index=False))

print("\n(b) 같은 trading_partner를 여러 company_code가 사용 (역순환 신호)")
print(con.execute(
    """
    SELECT je.trading_partner,
           STRING_AGG(DISTINCT je.company_code, ', ') AS companies,
           COUNT(DISTINCT je.company_code) AS comp_cnt,
           COUNT(DISTINCT je.document_id)  AS doc_cnt
    FROM je JOIN truth USING(document_id)
    WHERE truth.manipulation_scenario='circular_related_party_transaction'
      AND je.trading_partner IS NOT NULL
    GROUP BY 1
    HAVING COUNT(DISTINCT je.company_code) > 1
    ORDER BY comp_cnt DESC, doc_cnt DESC
    """
).fetchdf().to_string(index=False))

# 5) period_end — 분기말 집중도
section("E. period_end_adjustment 분기말 집중")
print(con.execute(
    """
    WITH base AS (
      SELECT je.document_id,
             EXTRACT(MONTH FROM CAST(je.posting_date AS TIMESTAMP)) AS m
      FROM je JOIN truth USING(document_id)
      WHERE truth.manipulation_scenario='period_end_adjustment_manipulation'
      GROUP BY 1,2
    )
    SELECT
      SUM(CASE WHEN m IN (3,6,9,12) THEN 1 ELSE 0 END)::DECIMAL(8,3) /COUNT(*) AS quarterend_ratio,
      SUM(CASE WHEN m=12 THEN 1 ELSE 0 END)::DECIMAL(8,3) /COUNT(*)            AS dec_ratio,
      SUM(CASE WHEN m IN (1,2) THEN 1 ELSE 0 END)::DECIMAL(8,3) /COUNT(*)      AS jan_feb_ratio
    FROM base
    """
).fetchdf().to_string(index=False))

# 6) 시나리오별 description_quality
section("F. description_quality 분포 (시나리오별)")
print(con.execute(
    """
    SELECT manipulation_scenario, description_quality, COUNT(*) AS lines
    FROM jt WHERE manipulation_scenario IS NOT NULL
    GROUP BY 1,2 ORDER BY 1, lines DESC
    """
).fetchdf().to_string(index=False))

# 7) 가공 분개 — 매출/자산/비용 계정 분포 (FSS 의도와 일치?)
section("G. fictitious_entry — 계정 카테고리 분포")
print(con.execute(
    """
    SELECT
      CASE
        WHEN gl_account < 2000 THEN '1xxxx 자산'
        WHEN gl_account < 3000 THEN '2xxxx 부채'
        WHEN gl_account < 4000 THEN '3xxxx 자본'
        WHEN gl_account < 5000 THEN '4xxxx 매출'
        WHEN gl_account < 6000 THEN '5xxxx 매출원가'
        WHEN gl_account < 7000 THEN '6xxxx 비용'
        ELSE '기타'
      END AS cat,
      COUNT(*) AS lines,
      SUM(local_amount)::BIGINT AS amt
    FROM je JOIN truth USING(document_id)
    WHERE truth.manipulation_scenario='fictitious_entry'
    GROUP BY 1 ORDER BY lines DESC
    """
).fetchdf().to_string(index=False))
