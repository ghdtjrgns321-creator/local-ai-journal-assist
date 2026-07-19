"""r1e 후속 검증 — 표면 누수/flow 멤버십/연도 배치/business_process 구성."""

import json
import sys

import duckdb

BASE = "data/journal/primary/datasynth_semantic_v1_normal_20260610_v31c"
OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260610_v1_r1e"

con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW out_je AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW prov   AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


print("== A. 표면 컬럼 누수 후보 — fraud vs normal 값 분포 ==")
for col in [
    "mutation_reason",
    "detection_surface_hints",
    "source",
    "batch_type",
    "is_synthetic",
    "is_mutated",
]:
    fr = q(f"SELECT DISTINCT \"{col}\" FROM out_je WHERE is_fraud='true' ORDER BY 1")
    print(f"fraud {col}: {[r[0] for r in fr]}")
    vals = [r[0] for r in fr if r[0] is not None]
    if vals:
        inlist = ", ".join("'" + v.replace("'", "''") + "'" for v in vals)
        n = q(f"SELECT count(*) FROM out_je WHERE is_fraud='false' AND \"{col}\" IN ({inlist})")[0][
            0
        ]
        print(f"  -> 같은 값을 가진 normal 행 수: {n}")

print("\n== B. scheme별 business_process 구성 ==")
print(
    q("""SELECT p.scheme_id, j.business_process, count(DISTINCT j.document_id)
           FROM prov p JOIN out_je j USING(document_id) GROUP BY 1,2 ORDER BY 1,2""")
)

print("\n== C. component_role별 posting_date 범위 (FS07/FS09 익기 확인) ==")
print(
    q("""SELECT p.scheme_id, p.component_role, min(j.posting_date), max(j.posting_date)
           FROM prov p JOIN out_je j USING(document_id)
           WHERE p.scheme_id IN ('FS07','FS09') GROUP BY 1,2 ORDER BY 1,2""")
)

print("\n== D. flow 멤버십 — flow 파일 문서 수 base vs out ==")
import os

for f in [
    "sales_orders",
    "deliveries",
    "customer_invoices",
    "purchase_orders",
    "goods_receipts",
    "vendor_invoices",
    "payments",
]:
    with open(os.path.join(BASE, "document_flows", f + ".json"), encoding="utf-8") as fh:
        b = len(json.load(fh))
    with open(os.path.join(OUT, "document_flows", f + ".json"), encoding="utf-8") as fh:
        o = len(json.load(fh))
    print(f"{f}: base={b} out={o} diff={o - b}")

print("\n== E. IC pairs base vs out ==")
with open(os.path.join(BASE, "intercompany", "ic_matched_pairs.json"), encoding="utf-8") as fh:
    b = len(json.load(fh))
with open(os.path.join(OUT, "intercompany", "ic_matched_pairs.json"), encoding="utf-8") as fh:
    o = len(json.load(fh))
print(f"ic_matched_pairs: base={b} out={o} diff={o - b}")

print("\n== F. fraud JE -> flow 역참조 (reference 채움 비율) ==")
print(
    q("""SELECT p.scheme_id, count(*) FILTER (WHERE j.reference IS NOT NULL AND j.reference<>'') AS with_ref,
                  count(*) AS total
           FROM prov p JOIN (SELECT DISTINCT document_id, reference FROM out_je) j USING(document_id)
           GROUP BY 1 ORDER BY 1""")
)

sys.stdout.flush()
