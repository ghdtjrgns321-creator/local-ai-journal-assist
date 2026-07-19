"""r1f_c 독립 재검증 — N1~N6(결함수정) + 회귀 R1~R7."""

import json
import os
import sys

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


print("== R1 문서 불변량 ==")
b = q("SELECT count(DISTINCT document_id) FROM base_je")[0][0]
o = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
fr = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
print(f"base={b} out={o} diff={o - b} fraud_docs={fr} 비중={fr / o * 100:.4f}%")

print("\n== R2 base 무수정 ==")
cols = [r[1] for r in q("PRAGMA table_info('base_je')")]
cl = ", ".join(f'"{c}"' for c in cols)
print(
    "변경된 base 행:",
    q(f"SELECT count(*) FROM (SELECT {cl} FROM base_je EXCEPT SELECT {cl} FROM j)")[0][0],
)

print("\n== R3 라벨 정합 ==")
print(
    "prov doc 중 JE에 없음:",
    q(
        "SELECT count(*) FROM (SELECT DISTINCT document_id FROM p EXCEPT SELECT DISTINCT document_id FROM j)"
    )[0][0],
)
print(
    "prov doc 중 is_fraud!=true:",
    q(
        "SELECT count(DISTINCT p.document_id) FROM p JOIN j USING(document_id) WHERE j.is_fraud<>'true'"
    )[0][0],
)
print(
    "is_fraud doc 중 prov 없음:",
    q(
        "SELECT count(*) FROM (SELECT DISTINCT document_id FROM j WHERE is_fraud='true' EXCEPT SELECT DISTINCT document_id FROM p)"
    )[0][0],
)

print("\n== R5 정상쌍둥이 (부정 전용 계정) ==")
print(
    "부정전용 계정수:",
    q(
        "SELECT count(*) FROM (SELECT DISTINCT gl_account FROM j WHERE is_fraud='true' EXCEPT SELECT DISTINCT gl_account FROM j WHERE is_fraud='false')"
    )[0][0],
)

print("\n== N1 자기상쇄 (동일 계정 차/대 동시) ==")
print(
    q("""
  WITH lines AS (
    SELECT p.scheme_id, j.document_id, j.gl_account,
           sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
    FROM p JOIN j USING(document_id) GROUP BY 1,2,3)
  SELECT scheme_id, count(DISTINCT document_id)
  FROM lines WHERE dr>0 AND cr>0 GROUP BY 1 ORDER BY 1""")
)
print(
    "자기상쇄 총 문서:",
    q("""
  WITH lines AS (SELECT j.document_id, j.gl_account, sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
    FROM p JOIN j USING(document_id) GROUP BY 1,2)
  SELECT count(DISTINCT document_id) FROM lines WHERE dr>0 AND cr>0""")[0][0],
)

print("\n== N2 scheme별 계정 순효과 (sub_type 집계) ==")
print(
    q("""
  SELECT p.scheme_id, j.semantic_account_subtype,
         round(sum(CAST(j.debit_amount AS DOUBLE) - CAST(j.credit_amount AS DOUBLE))) net_debit
  FROM p JOIN j USING(document_id)
  GROUP BY 1,2 HAVING abs(net_debit)>0 ORDER BY 1,2""")
)

print("\n== N3 delivery_date 채움 (fraud O2C) ==")
print(
    q("""SELECT p.scheme_id,
            count(*) FILTER (WHERE j.delivery_date IS NOT NULL AND j.delivery_date<>'') with_d,
            count(*) total
         FROM p JOIN (SELECT DISTINCT document_id, delivery_date FROM j) j USING(document_id)
         GROUP BY 1 ORDER BY 1""")
)

print("\n== N4 component_role 집합 / scheme ==")
print(
    q(
        "SELECT scheme_id, list_sort(array_agg(DISTINCT component_role)) FROM p GROUP BY 1 ORDER BY 1"
    )
)

print("\n== N5 reversal/return 문서 링크 ==")
print(
    q("""SELECT p.component_role,
            count(DISTINCT p.document_id) docs,
            count(DISTINCT CASE WHEN (j.reversal_document_id IS NOT NULL AND j.reversal_document_id<>'')
                              OR (j.original_document_id IS NOT NULL AND j.original_document_id<>'')
                         THEN p.document_id END) linked
         FROM p JOIN j USING(document_id)
         WHERE p.component_role LIKE '%revers%' OR p.component_role LIKE '%return%'
         GROUP BY 1 ORDER BY 1""")
)

print("\n== N6 차대균형 + 연도경계 ==")
print(
    "불균형 fraud 문서:",
    q("""SELECT count(*) FROM (SELECT document_id FROM j WHERE is_fraud='true' GROUP BY 1
    HAVING abs(sum(CAST(debit_amount AS DOUBLE))-sum(CAST(credit_amount AS DOUBLE)))>0.01)""")[0][
        0
    ],
)
print(
    "scheme 연도수:",
    q(
        "SELECT p.scheme_id, count(DISTINCT j.fiscal_year) FROM p JOIN j USING(document_id) GROUP BY 1 ORDER BY 1"
    ),
)

print("\n== delivery control 864 — shortcut 여부 ==")
print("is_fraud 분포(delivery control 후보 = base 밖 비-truth 신규문서):")
print("  신규문서 총:", o - b)
print("  truth 문서:", q("SELECT count(DISTINCT document_id) FROM p")[0][0])
ctrl = q("""SELECT count(DISTINCT document_id) FROM j
            WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je)""")[0][
    0
]
print("  신규 비-truth(=control 추정):", ctrl)
print(
    "  control 중 is_fraud=true 인 것(누수면 >0):",
    q("""SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'
           AND document_id NOT IN (SELECT document_id FROM p)""")[0][0],
)

print("\n== FS09 시점 짝 (pulled_forward vs return 월) ==")
print(
    q("""SELECT p.component_role, min(j.posting_date), max(j.posting_date), count(DISTINCT j.document_id)
         FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS09' GROUP BY 1 ORDER BY 1""")
)

sys.stdout.flush()
