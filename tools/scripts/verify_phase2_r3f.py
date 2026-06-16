"""v33 base + r3f overlay (14 scheme 전수) 독립 재검증."""

import sys

import duckdb

V32 = "data/journal/primary/datasynth_semantic_v1_normal_20260611_v32"
V33 = "data/journal/primary/datasynth_semantic_v1_normal_20260611_v33"
OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r3f"

con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW v32 AS SELECT * FROM read_csv('{V32}/journal_entries.csv', all_varchar=true);
    CREATE VIEW base AS SELECT * FROM read_csv('{V33}/journal_entries.csv', all_varchar=true);
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    CREATE VIEW t AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_truth.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


print("=== V33 BASE (sidecar 보강이 journal 안 건드렸나) ===")
print("v33 문서수:", q("SELECT count(DISTINCT document_id) FROM base")[0][0])
cols = [r[1] for r in q("PRAGMA table_info('v32')")]
cl = ", ".join(f'"{c}"' for c in cols)
print(
    "v32 vs v33 journal 변경행:",
    q(f"SELECT count(*) FROM (SELECT {cl} FROM v32 EXCEPT SELECT {cl} FROM base)")[0][0],
    "(0이어야 — sidecar만 추가)",
)
print(
    "v33 delivery_date 채운 문서:",
    q(
        "SELECT count(DISTINCT document_id) FROM base WHERE delivery_date IS NOT NULL AND delivery_date<>''"
    )[0][0],
)

print("\n=== R1~R5 회귀 ===")
b = q("SELECT count(DISTINCT document_id) FROM base")[0][0]
o = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
fr = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
print(f"R1 불변량: base={b} out={o} diff={o - b} fraud={fr} 비중={fr / o * 100:.4f}%")
print(
    "R2 base무수정:",
    q(f"SELECT count(*) FROM (SELECT {cl} FROM base EXCEPT SELECT {cl} FROM j)")[0][0],
)
print(
    "R3 라벨정합(prov없음/isfraud아님/prov빠짐):",
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
    "   신규 비-truth 문서(control 없어야):",
    q(
        "SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base)"
    )[0][0],
)

print("\n=== C1 14 scheme 전수 ===")
schemes = q(
    "SELECT scheme_id, count(DISTINCT scheme_instance_id) inst, count(DISTINCT document_id) docs FROM p GROUP BY 1 ORDER BY 1"
)
print("scheme별 (instance/docs):")
for s in schemes:
    print(f"  {s[0]}: inst={s[1]} docs={s[2]}")
present = {s[0] for s in schemes}
expected = {f"FS{n:02d}" for n in range(1, 15)}
print(
    "누락 scheme:",
    sorted(expected - present),
    "| 총 docs:",
    q("SELECT count(DISTINCT document_id) FROM p")[0][0],
)

print("\n=== C2 회사·기간 분산 ===")
print(
    "scheme별 회사:",
    q(
        "SELECT p.scheme_id, list_sort(array_agg(DISTINCT j.company_code)) FROM p JOIN j USING(document_id) GROUP BY 1 ORDER BY 1"
    ),
)
print(
    "회사별 fraud 문서수:",
    q(
        "SELECT j.company_code, count(DISTINCT j.document_id) FROM p JOIN j USING(document_id) GROUP BY 1 ORDER BY 1"
    ),
)

print("\n=== C3 FS10/FS13 부작위 메타 ===")
tcols = [r[1] for r in q("PRAGMA table_info('t')")]
print("truth columns:", tcols)
for sc in ["FS10", "FS13", "FS12"]:
    print(
        f"  {sc}:",
        q(
            f"SELECT scheme_id, evaluation_stratum, unrecognized_amount_krw FROM t WHERE scheme_id='{sc}'"
        ),
    )

print("\n=== N1 자기상쇄 ===")
print(
    "자기상쇄 문서:",
    q("""WITH l AS (SELECT j.document_id, j.gl_account, sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
    FROM p JOIN j USING(document_id) GROUP BY 1,2) SELECT count(DISTINCT document_id) FROM l WHERE dr>0 AND cr>0""")[
        0
    ][0],
)

print("\n=== N4 신규 scheme role 집합 (카탈로그 일치 육안) ===")
print(
    q(
        "SELECT scheme_id, list_sort(array_agg(DISTINCT component_role)) FROM p WHERE scheme_id IN ('FS02','FS04','FS06','FS08','FS10','FS13','FS14') GROUP BY 1 ORDER BY 1"
    )
)

print("\n=== N2 신규 scheme 경제효과 (sub_type 순효과) ===")
print(
    q("""SELECT p.scheme_id, j.semantic_account_subtype, round(sum(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))) net_debit
    FROM p JOIN j USING(document_id) WHERE p.scheme_id IN ('FS02','FS04','FS06','FS08','FS10','FS13','FS14')
    GROUP BY 1,2 HAVING abs(net_debit)>0 ORDER BY 1,2""")
)

print("\n=== N5 reversal 링크 ===")
print(
    q("""SELECT p.component_role, count(DISTINCT p.document_id) docs,
    count(DISTINCT CASE WHEN (j.reversal_document_id IS NOT NULL AND j.reversal_document_id<>'') OR (j.original_document_id IS NOT NULL AND j.original_document_id<>'') THEN p.document_id END) linked
    FROM p JOIN j USING(document_id) WHERE p.component_role LIKE '%revers%' OR p.component_role LIKE '%return%' OR p.component_role LIKE '%rebook%' OR p.component_role LIKE '%period_start%' OR p.component_role LIKE '%removal%' GROUP BY 1 ORDER BY 1""")
)

print("\n=== N6 균형 + 연도 ===")
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

print("\n=== flow sidecar 멤버십 (truth doc journal_exposed) ===")
print("journal_exposed 분포:", q("SELECT journal_exposed, count(*) FROM p GROUP BY 1"))

sys.stdout.flush()
