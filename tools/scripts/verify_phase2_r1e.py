"""r1e overlay 독립 재검증 — 보고 수치 재계산 (라벨/균형/base 무수정/연도경계/정상쌍둥이)."""

import sys

import duckdb

BASE = "data/journal/primary/datasynth_semantic_v1_normal_20260610_v31c"
OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260610_v1_r1e"

con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW base_je AS SELECT * FROM read_csv('{BASE}/journal_entries.csv', all_varchar=true);
    CREATE VIEW out_je  AS SELECT * FROM read_csv('{OUT}/journal_entries.csv',  all_varchar=true);
    CREATE VIEW truth   AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_truth.csv', all_varchar=true);
    CREATE VIEW prov    AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


print("== 2. scheme별 집계 (provenance 기준) ==")
print("문서수:", q("SELECT scheme_id, count(DISTINCT document_id) FROM prov GROUP BY 1 ORDER BY 1"))
print(
    "instance수:",
    q("SELECT scheme_id, count(DISTINCT scheme_instance_id) FROM prov GROUP BY 1 ORDER BY 1"),
)
print("journal_exposed 분포:", q("SELECT journal_exposed, count(*) FROM prov GROUP BY 1"))

print("\n== 3. 라벨 <-> JE 정합 ==")
print(
    "prov doc(journal_exposed=true) 중 JE에 없는 것:",
    q(
        """SELECT count(*) FROM (
           SELECT DISTINCT document_id FROM prov WHERE journal_exposed='true'
           EXCEPT SELECT DISTINCT document_id FROM out_je)"""
    )[0][0],
)
print(
    "prov doc 중 JE is_fraud!=true:",
    q(
        """SELECT count(DISTINCT p.document_id) FROM prov p
           JOIN out_je j USING(document_id) WHERE j.is_fraud<>'true'"""
    )[0][0],
)
print(
    "JE is_fraud doc 중 prov에 없는 것:",
    q(
        """SELECT count(*) FROM (
           SELECT DISTINCT document_id FROM out_je WHERE is_fraud='true'
           EXCEPT SELECT DISTINCT document_id FROM prov)"""
    )[0][0],
)
print(
    "prov doc 중 JE에 아예 없는 것(전체):",
    q(
        """SELECT count(*) FROM (
           SELECT DISTINCT document_id FROM prov
           EXCEPT SELECT DISTINCT document_id FROM out_je)"""
    )[0][0],
)

print("\n== 4. 차대 균형 (fraud 문서) ==")
bad_bal = q(
    """SELECT count(*) FROM (
       SELECT document_id FROM out_je WHERE is_fraud='true'
       GROUP BY document_id
       HAVING abs(sum(CAST(debit_amount AS DOUBLE)) - sum(CAST(credit_amount AS DOUBLE))) > 0.01)"""
)[0][0]
print(f"불균형 fraud 문서: {bad_bal}")

print("\n== 5. base 무수정 (전 컬럼 EXCEPT) ==")
common = [r[1] for r in q("PRAGMA table_info('base_je')")]
collist = ", ".join(f'"{c}"' for c in common)
changed = q(
    f"SELECT count(*) FROM (SELECT {collist} FROM base_je EXCEPT SELECT {collist} FROM out_je)"
)[0][0]
print(f"base 행 중 output에 동일하게 없는 행: {changed}")

print("\n== 6. 다기간 scheme 연도 경계 ==")
print(
    q(
        """SELECT p.scheme_id, count(DISTINCT j.fiscal_year) AS yrs
       FROM prov p JOIN out_je j USING(document_id)
       GROUP BY 1 ORDER BY 1"""
    )
)

print("\n== 7. 정상 쌍둥이 — fraud 사용 계정이 정상에 없는 경우 ==")
orphan = q(
    """SELECT count(*) FROM (
       SELECT DISTINCT gl_account FROM out_je WHERE is_fraud='true'
       EXCEPT
       SELECT DISTINCT gl_account FROM out_je WHERE is_fraud='false')"""
)[0][0]
print(f"부정 전용 계정 수: {orphan}")

print("\n== 8. component_role 구성 ==")
print(q("SELECT scheme_id, component_role, count(*) FROM prov GROUP BY 1,2 ORDER BY 1,2"))

print("\n== 9. FS12 메타 ==")
print(
    q(
        "SELECT scheme_id, evaluation_stratum, unrecognized_amount_krw FROM truth WHERE scheme_id='FS12'"
    )
)

sys.stdout.flush()
