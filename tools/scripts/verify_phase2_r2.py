"""v32 base + r2 overlay 독립 재검증 — delivery 경계해소 + 회귀."""

import sys

import duckdb

V31C = "data/journal/primary/datasynth_semantic_v1_normal_20260610_v31c"
V32 = "data/journal/primary/datasynth_semantic_v1_normal_20260611_v32"
OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r2"

con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW v31c AS SELECT * FROM read_csv('{V31C}/journal_entries.csv', all_varchar=true);
    CREATE VIEW base AS SELECT * FROM read_csv('{V32}/journal_entries.csv', all_varchar=true);
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


print("=== V32 BASE ===")
print("문서수:", q("SELECT count(DISTINCT document_id) FROM base")[0][0])
print(
    "delivery_date 채운 문서:",
    q(
        "SELECT count(DISTINCT document_id) FROM base WHERE delivery_date IS NOT NULL AND delivery_date<>''"
    )[0][0],
)
print(
    "v31c delivery 채운 문서:",
    q(
        "SELECT count(DISTINCT document_id) FROM v31c WHERE delivery_date IS NOT NULL AND delivery_date<>''"
    )[0][0],
)

# v31c 대비 delivery_date 외 변경 컬럼 확인: 문서 수 동일 가정, 공통 컬럼 중 delivery_date 빼고 EXCEPT
print("\n-- v31c vs v32 변경 컬럼 검증 (delivery_date 제외 시 0행이어야) --")
cols = [r[1] for r in q("PRAGMA table_info('v31c')")]
nondeliv = [c for c in cols if c != "delivery_date"]
cl = ", ".join(f'"{c}"' for c in nondeliv)
diff = q(f"SELECT count(*) FROM (SELECT {cl} FROM v31c EXCEPT SELECT {cl} FROM base)")[0][0]
print(f"delivery_date 제외 v31c→v32 변경 행: {diff} (0이면 delivery_date만 바뀜)")

print("\n-- base delivery vs posting 자연분포 --")
print(
    q("""SELECT CASE WHEN CAST(delivery_date AS DATE)>CAST(posting_date AS DATE) THEN 'after(역전)'
                  WHEN CAST(delivery_date AS DATE)<CAST(posting_date AS DATE) THEN 'before(정상)' ELSE 'same' END,
              count(DISTINCT document_id)
       FROM base WHERE delivery_date IS NOT NULL AND delivery_date<>'' GROUP BY 1 ORDER BY 1""")
)
print(
    "base 차대불균형:",
    q(
        "SELECT count(*) FROM (SELECT document_id FROM base GROUP BY 1 HAVING abs(sum(CAST(debit_amount AS DOUBLE))-sum(CAST(credit_amount AS DOUBLE)))>0.01)"
    )[0][0],
)

print("\n=== R2 OVERLAY 회귀 ===")
b = q("SELECT count(DISTINCT document_id) FROM base")[0][0]
o = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
fr = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
print(f"R1 불변량: base={b} out={o} diff={o - b} fraud={fr}")
print(
    "R2 base무수정:",
    q(
        f"SELECT count(*) FROM (SELECT {', '.join(chr(34) + c + chr(34) for c in cols)} FROM base EXCEPT SELECT {', '.join(chr(34) + c + chr(34) for c in cols)} FROM j)"
    )[0][0],
    "(0이어야)",
)
print(
    "R3 라벨정합 (prov없음/is_fraud아님/prov빠짐):",
    q(
        "SELECT count(*) FROM (SELECT DISTINCT document_id FROM p EXCEPT SELECT DISTINCT document_id FROM j)"
    )[0][0],
    q(
        "SELECT count(DISTINCT p.document_id) FROM p JOIN j USING(document_id) WHERE j.is_fraud<>'true'"
    )[0][0],
    q(
        "SELECT count(*) FROM (SELECT DISTINCT document_id FROM j WHERE is_fraud='true' EXCEPT SELECT DISTINCT document_id FROM p)"
    )[0][0],
)
print(
    "R5 부정전용계정:",
    q(
        "SELECT count(*) FROM (SELECT DISTINCT gl_account FROM j WHERE is_fraud='true' EXCEPT SELECT DISTINCT gl_account FROM j WHERE is_fraud='false')"
    )[0][0],
)
print(
    "control 제거 확인 — 신규 비-truth 문서:",
    q(
        "SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base)"
    )[0][0],
    "(0이어야)",
)

print("\n-- N1 자기상쇄 --")
print(
    "자기상쇄 문서:",
    q("""WITH l AS (SELECT j.document_id, j.gl_account, sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
    FROM p JOIN j USING(document_id) GROUP BY 1,2) SELECT count(DISTINCT document_id) FROM l WHERE dr>0 AND cr>0""")[
        0
    ][0],
)
print("-- N4 role 집합 --")
print(
    q(
        "SELECT scheme_id, list_sort(array_agg(DISTINCT component_role)) FROM p GROUP BY 1 ORDER BY 1"
    )
)
print("-- N5 reversal 링크 --")
print(
    q("""SELECT p.component_role, count(DISTINCT p.document_id) docs,
        count(DISTINCT CASE WHEN (j.reversal_document_id IS NOT NULL AND j.reversal_document_id<>'')
                         OR (j.original_document_id IS NOT NULL AND j.original_document_id<>'') THEN p.document_id END) linked
     FROM p JOIN j USING(document_id) WHERE p.component_role LIKE '%revers%' OR p.component_role LIKE '%return%' GROUP BY 1 ORDER BY 1""")
)
print("-- N6 균형+연도 --")
print(
    "불균형 fraud:",
    q(
        "SELECT count(*) FROM (SELECT document_id FROM j WHERE is_fraud='true' GROUP BY 1 HAVING abs(sum(CAST(debit_amount AS DOUBLE))-sum(CAST(credit_amount AS DOUBLE)))>0.01)"
    )[0][0],
)
print(
    "scheme 연도수:",
    q(
        "SELECT p.scheme_id, count(DISTINCT j.fiscal_year) FROM p JOIN j USING(document_id) GROUP BY 1 ORDER BY 1"
    ),
)

print("\n=== D1~D3 경계해소 ===")
deliv_total = q(
    "SELECT count(DISTINCT document_id) FROM j WHERE delivery_date IS NOT NULL AND delivery_date<>''"
)[0][0]
deliv_fraud = q(
    "SELECT count(DISTINCT document_id) FROM j WHERE delivery_date IS NOT NULL AND delivery_date<>'' AND is_fraud='true'"
)[0][0]
print(
    f"D1 delivery 채운 문서 총 {deliv_total} (그중 fraud {deliv_fraud}, normal {deliv_total - deliv_fraud})"
)
print(
    f"D2 'delivery not null' 집단 fraud 비율: {deliv_fraud / deliv_total * 100:.3f}% (모집단 fraud율 {fr / o * 100:.3f}%)"
)
print("D3 fraud O2C delivery vs posting:")
print(
    q("""SELECT p.scheme_id, CASE WHEN CAST(j.delivery_date AS DATE)>CAST(j.posting_date AS DATE) THEN 'after(역전)'
              WHEN CAST(j.delivery_date AS DATE)<CAST(j.posting_date AS DATE) THEN 'before' ELSE 'same' END,
           count(DISTINCT j.document_id)
       FROM p JOIN (SELECT DISTINCT document_id, delivery_date, posting_date FROM j) j USING(document_id)
       WHERE p.scheme_id IN ('FS01','FS05','FS09') AND j.delivery_date IS NOT NULL AND j.delivery_date<>'' GROUP BY 1,2 ORDER BY 1,2""")
)

sys.stdout.flush()
