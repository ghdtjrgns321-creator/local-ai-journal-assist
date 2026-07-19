"""r3g 총검사 — (A) 대차 계정조합 회계 논리 정합성, (B) 전 컬럼 shortcut lift 전수."""

import sys

import duckdb

OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r3g"
con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


TOTAL = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
FRAUD = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
BASE_RATE = FRAUD / TOTAL
print(f"모집단 {TOTAL} / 부정 {FRAUD} / base fraud rate {BASE_RATE * 100:.4f}%\n")

# ===== A. 대차 계정조합 회계 논리 =====
# 문서별 차변 sub_type 집합 × 대변 sub_type 집합 → pair. 정상 화이트리스트 대비 부정.
con.execute("""
CREATE VIEW pairs AS
WITH dr AS (SELECT document_id, is_fraud, semantic_account_subtype st FROM j WHERE CAST(debit_amount AS DOUBLE)>0 AND semantic_account_subtype IS NOT NULL AND semantic_account_subtype<>''),
     cr AS (SELECT document_id, semantic_account_subtype st FROM j WHERE CAST(credit_amount AS DOUBLE)>0 AND semantic_account_subtype IS NOT NULL AND semantic_account_subtype<>'')
SELECT DISTINCT dr.document_id, dr.is_fraud, dr.st AS debit_st, cr.st AS credit_st
FROM dr JOIN cr USING(document_id) WHERE dr.st<>cr.st
""")

print("=== A1. 부정 전용 계정조합 (정상에 없는 debit→credit pair) ===")
orphan = q("""
SELECT debit_st, credit_st, count(DISTINCT document_id) docs FROM pairs WHERE is_fraud='true'
  AND (debit_st, credit_st) NOT IN (SELECT debit_st, credit_st FROM pairs WHERE is_fraud='false')
GROUP BY 1,2 ORDER BY 3 DESC""")
if orphan:
    for r in orphan:
        print(f"  [부정전용] {r[0]} → {r[1]} : {r[2]}docs")
else:
    print("  없음 — 모든 부정 조합이 정상에도 존재 (억지조합 아님)")

print("\n=== A2. 명시 안티패턴 (회계적으로 말 안되는 조합) — 정상/부정 ===")
ANTI = [
    (
        "비용→AP(매입채무)",
        "debit_st IN ('operating_expenses','OPEX_OFFICE_SUPPLIES','SALARIES','payroll_expense','interest_expense') AND credit_st='AP'",
    ),
    ("비용 차변 ↔ 수익 대변", "debit_st LIKE '%expense%' AND credit_st LIKE '%REVENUE%'"),
    ("수익 차변 ↔ 비용 대변", "debit_st LIKE '%REVENUE%' AND credit_st LIKE '%expense%'"),
    ("급여비용 → AR", "debit_st='payroll_expense' AND credit_st='AR'"),
    ("재고 → 수익", "debit_st='INVENTORY' AND credit_st LIKE '%REVENUE%'"),
]
for name, cond in ANTI:
    r = q(
        f"SELECT is_fraud, count(DISTINCT document_id) FROM pairs WHERE {cond} GROUP BY 1 ORDER BY 1"
    )
    d = {x[0]: x[1] for x in r}
    print(f"  {name}: 정상 {d.get('false', 0)} / 부정 {d.get('true', 0)}")

print("\n=== A3. 부정 계정조합 분포 (육안 회계 타당성) ===")
for r in q("""SELECT p.scheme_id, pr.debit_st, pr.credit_st, count(DISTINCT pr.document_id) docs
    FROM pairs pr JOIN p ON pr.document_id=p.document_id WHERE pr.is_fraud='true'
    GROUP BY 1,2,3 ORDER BY 1,4 DESC"""):
    print(f"  {r[0]}: {r[1]} → {r[2]} ({r[3]})")

# ===== B. 전 컬럼 shortcut lift =====
print("\n\n=== B. 전 컬럼 shortcut lift (부정이 특정 값에 집중되나) ===")
print(
    f"(lift = P(fraud|value)/base_rate. lift 높고 docs 충분 = shortcut 후보. base={BASE_RATE * 100:.4f}%)\n"
)
CAT_COLS = [
    "created_by",
    "approved_by",
    "cost_center",
    "profit_center",
    "currency",
    "exchange_rate",
    "document_type",
    "source",
    "business_process",
    "batch_type",
    "sod_violation",
    "has_attachment",
    "tax_treatment",
    "counterparty_type",
    "ledger",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "is_intercompany",
    "tax_code",
    "supporting_doc_type",
    "approval_date",
]
for col in CAT_COLS:
    # 부정이 보유한 값별로, 그 값의 fraud rate
    rows = q(f"""
      WITH docval AS (SELECT DISTINCT document_id, is_fraud, "{col}" v FROM j WHERE "{col}" IS NOT NULL AND "{col}"<>'')
      SELECT v, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot
      FROM docval GROUP BY v HAVING count(*) FILTER (WHERE is_fraud='true')>0
    """)
    flagged = []
    for v, fd, tot in rows:
        rate = fd / tot
        lift = rate / BASE_RATE
        # shortcut 후보: lift>=5 이고 부정문서 절반이상이 이 값 영역이거나 분리력 큼
        if lift >= 5 and tot >= 3:
            flagged.append((str(v)[:30], fd, tot, rate, lift))
    if flagged:
        flagged.sort(key=lambda x: -x[4])
        print(f"[{col}] 분리력 높은 값:")
        for v, fd, tot, rate, lift in flagged[:8]:
            print(f"    '{v}': 부정 {fd}/{tot} (fraud율 {rate * 100:.1f}%, lift {lift:.0f}x)")

# 부정 문서의 line 수 (분개 라인 개수)가 정상과 다른가
print("\n=== B2. 분개 라인수 분포 (정상 vs 부정) ===")
print(
    q("""WITH lc AS (SELECT document_id, is_fraud, count(*) lines FROM j GROUP BY 1,2)
    SELECT is_fraud, round(avg(lines),2), min(lines), max(lines), median(lines) FROM lc GROUP BY 1 ORDER BY 1""")
)

# 부정 문서당 고유 gl_account 수, 특정 계정 집중
print("\n=== B3. 부정이 특정 gl_account에 집중? (계정별 fraud lift top) ===")
for r in q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, gl_account FROM j)
    SELECT gl_account, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot,
           round(count(*) FILTER (WHERE is_fraud='true')*1.0/count(*)/{BASE_RATE},1) lift
    FROM dv GROUP BY 1 HAVING fd>0 AND tot>=3 AND count(*) FILTER (WHERE is_fraud='true')*1.0/count(*)/{BASE_RATE}>=5
    ORDER BY lift DESC LIMIT 15"""):
    print(f"    계정 {r[0]}: 부정 {r[1]}/{r[2]} (lift {r[3]}x)")

sys.stdout.flush()
