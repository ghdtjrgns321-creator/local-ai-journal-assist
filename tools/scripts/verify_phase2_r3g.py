"""r3g 재검증 — unrecognized_amount 파생 재현 + 작위 분개 r3f 동일(무수정) 회귀."""

import sys

import duckdb

R3F = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r3f"
OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r3g"
V33 = "data/journal/primary/datasynth_semantic_v1_normal_20260611_v33"

con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW base AS SELECT * FROM read_csv('{V33}/journal_entries.csv', all_varchar=true);
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW jf AS SELECT * FROM read_csv('{R3F}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    CREATE VIEW t AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_truth.csv', all_varchar=true);
    CREATE VIEW pf AS SELECT * FROM read_csv('{R3F}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


print("=== F1 unrecognized 값 (서로 다른가) ===")
print(
    q(
        "SELECT scheme_id, unrecognized_amount_krw FROM t WHERE unrecognized_amount_krw IS NOT NULL AND unrecognized_amount_krw<>'' AND CAST(unrecognized_amount_krw AS DOUBLE)>0 ORDER BY scheme_id"
    )
)
print(
    "148,750,000 동일상수 건수:",
    q("SELECT count(*) FROM t WHERE unrecognized_amount_krw='148750000'")[0][0],
)

print("\n=== F2 component basis 파생 재현 ===")
# FS10: fake_collection_refinance + receivable_reclass component 의 작위 금액 합 (debit+credit 중 의미있는 쪽)
for sc, roles in [
    ("FS10", ["fake_collection_refinance", "receivable_reclass"]),
    ("FS12", ["litigation_context_fees", "guarantee_fee_flow"]),
    ("FS13", ["investment_acquisition", "propping_injection"]),
]:
    rl = ", ".join("'" + r + "'" for r in roles)
    basis = q(f"""SELECT round(sum(CAST(j.debit_amount AS DOUBLE))), round(sum(CAST(j.credit_amount AS DOUBLE))),
                  round(sum(abs(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))))
              FROM p JOIN j USING(document_id) WHERE p.scheme_id='{sc}' AND p.component_role IN ({rl})""")
    decl = q(f"SELECT unrecognized_amount_krw FROM t WHERE scheme_id='{sc}'")
    print(
        f"{sc} roles={roles}: sum_dr={basis[0][0]} sum_cr={basis[0][1]} | 선언값={decl[0][0] if decl else None}"
    )

print("\n=== F3 작위 분개 r3f 동일 (분개 무수정) ===")
cols = [r[1] for r in q("PRAGMA table_info('jf')")]
cl = ", ".join(f'"{c}"' for c in cols)
print(
    "r3f→r3g journal 변경행:",
    q(f"SELECT count(*) FROM (SELECT {cl} FROM jf EXCEPT SELECT {cl} FROM j)")[0][0],
    "(0이면 분개 동일)",
)

print("\n=== 회귀 ===")
b = q("SELECT count(DISTINCT document_id) FROM base")[0][0]
o = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
fr = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
print(f"불변량: base={b} out={o} diff={o - b} fraud={fr}")
print(
    "base무수정:",
    q(f"SELECT count(*) FROM (SELECT {cl} FROM base EXCEPT SELECT {cl} FROM j)")[0][0],
)
print(
    "14 scheme 전수:",
    q("SELECT count(DISTINCT scheme_id) FROM p")[0][0],
    "/ 누락:",
    sorted(
        {f"FS{n:02d}" for n in range(1, 15)} - {r[0] for r in q("SELECT DISTINCT scheme_id FROM p")}
    ),
)
print(
    "자기상쇄:",
    q("""WITH l AS (SELECT j.document_id, j.gl_account, sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
    FROM p JOIN j USING(document_id) GROUP BY 1,2) SELECT count(DISTINCT document_id) FROM l WHERE dr>0 AND cr>0""")[
        0
    ][0],
)
print(
    "불균형 fraud:",
    q(
        "SELECT count(*) FROM (SELECT document_id FROM j WHERE is_fraud='true' GROUP BY 1 HAVING abs(sum(CAST(debit_amount AS DOUBLE))-sum(CAST(credit_amount AS DOUBLE)))>0.01)"
    )[0][0],
)
print(
    "라벨정합(prov없음/isfraud아님/prov빠짐):",
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

sys.stdout.flush()
