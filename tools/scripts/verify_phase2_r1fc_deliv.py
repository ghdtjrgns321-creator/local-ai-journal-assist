"""control vs fraud 의 delivery_date↔posting_date 관계 — 역전이 FS09에만 있는지."""

import duckdb

BASE = "data/journal/primary/datasynth_semantic_v1_normal_20260610_v31c"
OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260610_v1_r1f_c"
con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW base_je AS SELECT * FROM read_csv('{BASE}/journal_entries.csv', all_varchar=true);
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


# delivery_date < posting_date(납품 후 인식=정상) vs delivery_date > posting_date(미래납품=cutoff 역전)
print("== control(신규 비-truth) delivery vs posting 관계 ==")
print(
    q("""
  SELECT CASE WHEN CAST(delivery_date AS DATE) > CAST(posting_date AS DATE) THEN 'deliv_after_post(역전)'
              WHEN CAST(delivery_date AS DATE) < CAST(posting_date AS DATE) THEN 'deliv_before_post(정상)'
              ELSE 'same' END rel,
         count(DISTINCT document_id)
  FROM j WHERE is_fraud='false' AND delivery_date IS NOT NULL AND delivery_date<>''
    AND document_id NOT IN (SELECT document_id FROM base_je)
  GROUP BY 1 ORDER BY 1""")
)

print("\n== fraud O2C delivery vs posting 관계 (scheme별) ==")
print(
    q("""
  SELECT p.scheme_id,
         CASE WHEN CAST(j.delivery_date AS DATE) > CAST(j.posting_date AS DATE) THEN 'deliv_after_post(역전)'
              WHEN CAST(j.delivery_date AS DATE) < CAST(j.posting_date AS DATE) THEN 'deliv_before_post(정상)'
              ELSE 'same' END rel,
         count(DISTINCT j.document_id)
  FROM p JOIN (SELECT DISTINCT document_id, delivery_date, posting_date FROM j) j USING(document_id)
  WHERE p.scheme_id IN ('FS01','FS05','FS09') AND j.delivery_date IS NOT NULL AND j.delivery_date<>''
  GROUP BY 1,2 ORDER BY 1,2""")
)

print("\n== control 금액 분포 vs fraud O2C 금액 분포 (local_amount 분위) ==")
print(
    "control:",
    q("""SELECT round(min(CAST(local_amount AS DOUBLE))), round(median(CAST(local_amount AS DOUBLE))),
         round(max(CAST(local_amount AS DOUBLE)))
  FROM j WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je)
    AND local_amount IS NOT NULL AND local_amount<>''"""),
)
print(
    "fraud O2C:",
    q("""SELECT round(min(CAST(j.local_amount AS DOUBLE))), round(median(CAST(j.local_amount AS DOUBLE))),
         round(max(CAST(j.local_amount AS DOUBLE)))
  FROM p JOIN j USING(document_id) WHERE p.scheme_id IN ('FS01','FS05','FS09')
    AND j.local_amount IS NOT NULL AND j.local_amount<>''"""),
)

print("\n== control 의 created_by / source / business_process (정상 문서처럼 보이나) ==")
print(
    "source:",
    q("""SELECT source, count(DISTINCT document_id) FROM j
  WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je) GROUP BY 1"""),
)
print(
    "business_process:",
    q("""SELECT business_process, count(DISTINCT document_id) FROM j
  WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je) GROUP BY 1"""),
)
print(
    "gl_account:",
    q("""SELECT gl_account, count(DISTINCT document_id) FROM j
  WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je) GROUP BY 1 ORDER BY 2 DESC LIMIT 10"""),
)
