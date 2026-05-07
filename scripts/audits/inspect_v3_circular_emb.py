"""circular_RP의 amt=0 / embezzlement 1040억 페어 정밀 점검."""
from pathlib import Path
import duckdb

ROOT = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
DATA = ROOT / "data/journal/primary/datasynth_manipulation"
JE = (DATA / "journal_entries.csv").as_posix()
TRUTH = (DATA / "labels/manipulated_entry_truth.csv").as_posix()

con = duckdb.connect()
con.execute(f"""
  CREATE VIEW je    AS SELECT * FROM read_csv_auto('{JE}', header=True);
  CREATE VIEW truth AS SELECT * FROM read_csv_auto('{TRUTH}', header=True);
""")

def section(t): print("\n"+"="*88+"\n"+t+"\n"+"="*88)

section("1. circular_RP — local_amount 부호/합계 분석")
print(con.execute("""
  WITH t AS (
    SELECT je.document_id, je.local_amount,
           je.debit_amount, je.credit_amount, je.gl_account
    FROM je JOIN truth USING(document_id)
    WHERE truth.manipulation_scenario='circular_related_party_transaction'
  )
  SELECT
    COUNT(*)                              AS lines,
    SUM(CASE WHEN local_amount<0 THEN 1 ELSE 0 END) AS neg_lines,
    SUM(CASE WHEN local_amount>0 THEN 1 ELSE 0 END) AS pos_lines,
    SUM(CASE WHEN local_amount=0 THEN 1 ELSE 0 END) AS zero_lines,
    AVG(ABS(local_amount))::BIGINT       AS avg_abs_amt,
    SUM(debit_amount)::BIGINT             AS sum_dr,
    SUM(credit_amount)::BIGINT            AS sum_cr
  FROM t
""").fetchdf().to_string(index=False))

section("2. circular_RP — 회사간 매출/매입 매칭 패턴")
print(con.execute("""
  SELECT je.company_code,
         je.business_process,
         CASE WHEN je.gl_account < 2000 THEN 'asset'
              WHEN je.gl_account < 3000 THEN 'liab'
              WHEN je.gl_account < 4000 THEN 'eq'
              WHEN je.gl_account < 5000 THEN 'rev'
              WHEN je.gl_account < 6000 THEN 'cogs'
              WHEN je.gl_account < 7000 THEN 'exp'
              ELSE 'other' END AS cat,
         COUNT(*) AS lines,
         SUM(je.debit_amount)::BIGINT AS dr,
         SUM(je.credit_amount)::BIGINT AS cr
  FROM je JOIN truth USING(document_id)
  WHERE truth.manipulation_scenario='circular_related_party_transaction'
  GROUP BY 1,2,3 ORDER BY 1,2 LIMIT 30
""").fetchdf().to_string(index=False))

section("3. embezzlement — 1040억 페어 분개 표본")
print(con.execute("""
  SELECT je.document_id, je.gl_account, je.debit_amount, je.credit_amount,
         je.local_amount, je.line_text, je.posting_date
  FROM je JOIN truth USING(document_id)
  WHERE truth.manipulation_scenario='embezzlement_concealment'
    AND ABS(je.local_amount) > 1000000000
  ORDER BY ABS(je.local_amount) DESC LIMIT 15
""").fetchdf().to_string(index=False))

section("4. embezzlement — 금액 분포")
print(con.execute("""
  WITH t AS (
    SELECT je.document_id, SUM(ABS(je.local_amount)) AS abs_doc_amt,
           SUM(je.debit_amount) AS dr,
           SUM(je.credit_amount) AS cr
    FROM je JOIN truth USING(document_id)
    WHERE truth.manipulation_scenario='embezzlement_concealment'
    GROUP BY 1
  )
  SELECT
    COUNT(*)                                  AS docs,
    MIN(abs_doc_amt)::BIGINT                  AS min_amt,
    APPROX_QUANTILE(abs_doc_amt, 0.5)::BIGINT AS median_amt,
    APPROX_QUANTILE(abs_doc_amt, 0.9)::BIGINT AS p90,
    APPROX_QUANTILE(abs_doc_amt, 0.99)::BIGINT AS p99,
    MAX(abs_doc_amt)::BIGINT                  AS max_amt,
    AVG(abs_doc_amt)::BIGINT                  AS avg_amt,
    SUM(CASE WHEN abs_doc_amt > 1000000000 THEN 1 ELSE 0 END) AS docs_gt_1B,
    SUM(CASE WHEN abs_doc_amt > 10000000000 THEN 1 ELSE 0 END) AS docs_gt_10B
  FROM t
""").fetchdf().to_string(index=False))

section("5. embezzlement — line_text 다양성")
print(con.execute("""
  SELECT je.line_text, COUNT(*) AS lines
  FROM je JOIN truth USING(document_id)
  WHERE truth.manipulation_scenario='embezzlement_concealment'
    AND je.line_text IS NOT NULL
  GROUP BY 1 ORDER BY lines DESC LIMIT 20
""").fetchdf().to_string(index=False))

section("6. fictitious — 신규 self-approve/sod_violation 보강 확인")
print(con.execute("""
  WITH d AS (
    SELECT DISTINCT je.document_id,
           je.created_by, je.approved_by,
           ANY_VALUE(je.sod_violation) AS sodv
    FROM je JOIN truth USING(document_id)
    WHERE truth.manipulation_scenario='fictitious_entry'
    GROUP BY 1,2,3
  )
  SELECT
    COUNT(*)                                                    AS docs,
    SUM(CASE WHEN sodv THEN 1 ELSE 0 END)                        AS sodv_docs,
    SUM(CASE WHEN created_by=approved_by THEN 1 ELSE 0 END)      AS self_docs,
    SUM(CASE WHEN sodv AND created_by=approved_by THEN 1 ELSE 0 END) AS sodv_and_self
  FROM d
""").fetchdf().to_string(index=False))

section("7. circular_RP — 다회사가 같은 RP 공유 (확장 진단)")
print(con.execute("""
  SELECT
    COUNT(DISTINCT trading_partner)              AS unique_rp,
    COUNT(DISTINCT je.document_id)               AS docs,
    COUNT(DISTINCT CONCAT(je.company_code,'-',je.trading_partner)) AS pair_cnt
  FROM je JOIN truth USING(document_id)
  WHERE truth.manipulation_scenario='circular_related_party_transaction'
    AND je.trading_partner IS NOT NULL
""").fetchdf().to_string(index=False))

print(con.execute("""
  SELECT je.trading_partner,
         STRING_AGG(DISTINCT je.company_code ORDER BY je.company_code, ',') AS comp_list,
         COUNT(DISTINCT je.company_code)             AS comp_cnt,
         COUNT(DISTINCT je.document_id)              AS doc_cnt
  FROM je JOIN truth USING(document_id)
  WHERE truth.manipulation_scenario='circular_related_party_transaction'
    AND je.trading_partner IS NOT NULL
  GROUP BY 1 ORDER BY comp_cnt DESC, doc_cnt DESC LIMIT 15
""").fetchdf().to_string(index=False))
