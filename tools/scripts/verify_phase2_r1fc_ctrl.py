"""delivery control 864 가 fraud O2C 와 분포가 겹치는지 (delivery_date 존재 자체가 shortcut 되는지)."""

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


print("== base normal 자체의 delivery_date 채운 문서 수 ==")
print("base 전체 문서:", q("SELECT count(DISTINCT document_id) FROM base_je")[0][0])
print(
    "base delivery_date 채운 문서:",
    q(
        "SELECT count(DISTINCT document_id) FROM base_je WHERE delivery_date IS NOT NULL AND delivery_date<>''"
    )[0][0],
)

print("\n== output 에서 delivery_date 채운 문서 — fraud/control/base 구분 ==")
print(
    "전체 delivery 채운 문서:",
    q(
        "SELECT count(DISTINCT document_id) FROM j WHERE delivery_date IS NOT NULL AND delivery_date<>''"
    )[0][0],
)
print(
    "  그중 fraud:",
    q(
        "SELECT count(DISTINCT document_id) FROM j WHERE delivery_date IS NOT NULL AND delivery_date<>'' AND is_fraud='true'"
    )[0][0],
)
print(
    "  그중 신규 비-truth(control):",
    q("""SELECT count(DISTINCT document_id) FROM j
    WHERE delivery_date IS NOT NULL AND delivery_date<>'' AND is_fraud='false'
    AND document_id NOT IN (SELECT document_id FROM base_je)""")[0][0],
)
print(
    "  그중 base 원래분:",
    q("""SELECT count(DISTINCT document_id) FROM j
    WHERE delivery_date IS NOT NULL AND delivery_date<>'' AND document_id IN (SELECT document_id FROM base_je)""")[
        0
    ][0],
)

print("\n== delivery 채운 문서의 is_fraud 비율 (shortcut이면 fraud 쪽으로 쏠림) ==")
print(
    q("""SELECT is_fraud, count(DISTINCT document_id)
    FROM j WHERE delivery_date IS NOT NULL AND delivery_date<>'' GROUP BY 1""")
)

print("\n== control vs fraud 분포 비교 (회사/연도/document_type) ==")
print(
    "fraud O2C 회사분포:",
    q("""SELECT j.company_code, count(DISTINCT j.document_id) FROM p JOIN j USING(document_id)
    WHERE p.scheme_id IN ('FS01','FS05','FS09') GROUP BY 1 ORDER BY 1"""),
)
print(
    "control 회사분포:",
    q("""SELECT company_code, count(DISTINCT document_id) FROM j
    WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je) GROUP BY 1 ORDER BY 1"""),
)
print(
    "fraud O2C 연도분포:",
    q("""SELECT j.fiscal_year, count(DISTINCT j.document_id) FROM p JOIN j USING(document_id)
    WHERE p.scheme_id IN ('FS01','FS05','FS09') GROUP BY 1 ORDER BY 1"""),
)
print(
    "control 연도분포:",
    q("""SELECT fiscal_year, count(DISTINCT document_id) FROM j
    WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je) GROUP BY 1 ORDER BY 1"""),
)
print(
    "control document_type:",
    q("""SELECT document_type, count(DISTINCT document_id) FROM j
    WHERE is_fraud='false' AND document_id NOT IN (SELECT document_id FROM base_je) GROUP BY 1 ORDER BY 1"""),
)
print(
    "fraud O2C document_type:",
    q("""SELECT j.document_type, count(DISTINCT j.document_id) FROM p JOIN j USING(document_id)
    WHERE p.scheme_id IN ('FS01','FS05','FS09') GROUP BY 1 ORDER BY 1"""),
)
