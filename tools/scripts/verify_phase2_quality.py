"""r3g 3대 품질 — 정상/부정 noise 동일비율 + TB/보조원장 정합 + fraud 금액분포 겹침."""

import json
import os
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


print("=== 자연 NOISE: 정상 vs 부정 동일 비율인가 ===")
# 문서 단위로 noise 보유 여부 비교 (결측/오타 흔적). 부정 전용 토큰 누수 방지 핵심.
for label, cond in [("정상", "is_fraud='false'"), ("부정", "is_fraud='true'")]:
    total = q(f"SELECT count(DISTINCT document_id) FROM j WHERE {cond}")[0][0]
    miss_ct = q(
        f"SELECT count(DISTINCT document_id) FROM j WHERE {cond} AND (cost_center IS NULL OR cost_center='' OR header_text IS NULL OR header_text='' OR line_text IS NULL OR line_text='')"
    )[0][0]
    ref_miss = q(
        f"SELECT count(DISTINCT document_id) FROM j WHERE {cond} AND (reference IS NULL OR reference='')"
    )[0][0]
    print(
        f"  {label}: 문서 {total} / 결측흔적 보유 {miss_ct} ({miss_ct / total * 100:.1f}%) / reference결측 {ref_miss} ({ref_miss / total * 100:.1f}%)"
    )

print("\n=== fraud 금액분포가 정상과 겹치나 (억지 금액 아님) ===")
print(
    "정상 금액분위(min/p25/median/p75/max):",
    q("""SELECT round(min(CAST(local_amount AS DOUBLE))), round(quantile_cont(CAST(local_amount AS DOUBLE),0.25)),
    round(median(CAST(local_amount AS DOUBLE))), round(quantile_cont(CAST(local_amount AS DOUBLE),0.75)), round(max(CAST(local_amount AS DOUBLE)))
    FROM j WHERE is_fraud='false' AND local_amount IS NOT NULL AND local_amount<>'' AND CAST(local_amount AS DOUBLE)>0"""),
)
print(
    "부정 금액분위:",
    q("""SELECT round(min(CAST(local_amount AS DOUBLE))), round(quantile_cont(CAST(local_amount AS DOUBLE),0.25)),
    round(median(CAST(local_amount AS DOUBLE))), round(quantile_cont(CAST(local_amount AS DOUBLE),0.75)), round(max(CAST(local_amount AS DOUBLE)))
    FROM j WHERE is_fraud='true' AND local_amount IS NOT NULL AND local_amount<>'' AND CAST(local_amount AS DOUBLE)>0"""),
)

print("\n=== fraud round-number(끝자리 0 과다) 억지 흔적 점검 ===")
for label, cond in [("정상", "is_fraud='false'"), ("부정", "is_fraud='true'")]:
    rn = q(f"""SELECT count(*) FILTER (WHERE CAST(local_amount AS DOUBLE) % 1000000 = 0),
                      count(*) FROM j WHERE {cond} AND local_amount IS NOT NULL AND local_amount<>'' AND CAST(local_amount AS DOUBLE)>0""")
    print(
        f"  {label}: 백만단위 라운드 {rn[0][0]}/{rn[0][1]} ({rn[0][0] / max(rn[0][1], 1) * 100:.2f}%)"
    )

print("\n=== NORMAL 회계정합성: TB 대사 ===")
tb_path = os.path.join(OUT, "period_close", "trial_balances.json")
if os.path.exists(tb_path):
    with open(tb_path, encoding="utf-8") as f:
        tb = json.load(f)
    print(f"trial_balances 항목수: {len(tb) if isinstance(tb, list) else 'dict'}")
    sample = tb[0] if isinstance(tb, list) else tb
    if isinstance(sample, dict):
        print("TB 키:", list(sample.keys())[:15])
else:
    print("trial_balances.json 없음")

bv_path = os.path.join(OUT, "balance", "subledger_reconciliation.json")
if os.path.exists(bv_path):
    with open(bv_path, encoding="utf-8") as f:
        rec = json.load(f)
    print(f"subledger_reconciliation: {json.dumps(rec, ensure_ascii=False)[:400]}")
else:
    print("subledger_reconciliation.json 위치 확인 필요")

print("\n=== fraud 표면 누수 재확인 (전용 값) ===")
for col in ["source", "document_type", "user_persona", "batch_type"]:
    fr = q(
        f'SELECT DISTINCT "{col}" FROM j WHERE is_fraud=\'true\' AND "{col}" IS NOT NULL AND "{col}"<>\'\' ORDER BY 1'
    )
    vals = [r[0] for r in fr]
    if vals:
        inlist = ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)
        only_fraud = q(
            f"SELECT count(*) FROM j WHERE is_fraud='false' AND \"{col}\" IN ({inlist})"
        )[0][0]
        print(f"  {col}={vals[:6]} → 같은값 정상행 {only_fraud}")

sys.stdout.flush()
