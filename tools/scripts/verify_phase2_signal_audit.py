"""r4h 14 scheme 핵심 탐지신호 전수 — 카탈로그 (e) 기준 구조신호 잔존 측정."""

import sys

import duckdb

OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4h"
con = duckdb.connect()
con.execute(f"""
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
""")


def q(s):
    return con.execute(s).fetchall()


def docs(sc, role=None):
    rc = f" AND p.component_role='{role}'" if role else ""
    return q(
        f"SELECT count(DISTINCT j.document_id) FROM p JOIN j USING(document_id) WHERE p.scheme_id='{sc}'{rc}"
    )[0][0]


print("=== scheme별 핵심 탐지신호 측정 ===\n")

# FS01 가공매출: 동일고객 반복 + AR 미회수
fs01_cust = q(
    "SELECT count(DISTINCT trading_partner), count(DISTINCT document_id) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS01' AND p.component_role='fictitious_sale'"
)[0]
fs01_maxrep = q(
    "SELECT max(c) FROM (SELECT trading_partner, count(DISTINCT document_id) c FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS01' GROUP BY 1)"
)[0][0]
print(
    f"FS01 가공매출: 가공판매 고객 {fs01_cust[0]}명/{fs01_cust[1]}건, 한 고객 최대 {fs01_maxrep}건 → 반복신호 {'있음' if fs01_maxrep >= 3 else '약함/없음'}"
)

# FS02 진행기준: 계약자산 누적
fs02 = q(
    "SELECT round(sum(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS02' AND j.semantic_account_subtype='contract_asset'"
)[0][0]
print(
    f"FS02 진행기준: 계약자산(미청구) 순증 {fs02:,.0f} → {'있음' if fs02 and fs02 > 0 else '없음'}"
)

# FS03 횡령: 작성자 집중 + 은닉이전 + 직원계좌
fs03_top = q(
    "SELECT max(c) FROM (SELECT created_by, count(DISTINCT document_id) c FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS03' GROUP BY 1)"
)[0][0]
fs03_inst = q(
    "SELECT count(DISTINCT created_by) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS03'"
)[0][0]
print(
    f"FS03 횡령: 작성자 {fs03_inst}명, 최다 {fs03_top}건 → 작성자반복 {'강함' if fs03_top >= 5 else '약함(분산)' if fs03_top <= 2 else '중간'}"
)

# FS04 횡령은폐: 거래처 편중 + 정산부재
fs04_top = q(
    "SELECT max(c) FROM (SELECT trading_partner, count(DISTINCT document_id) c FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS04' AND trading_partner IS NOT NULL AND trading_partner<>'' GROUP BY 1)"
)
print(
    f"FS04 횡령은폐: 거래처 최다 {fs04_top[0][0] if fs04_top and fs04_top[0][0] else 0}건 → 편중 {'있음' if fs04_top and fs04_top[0][0] and fs04_top[0][0] >= 3 else '약함'}"
)

# FS05 순환: 회사 다양성(원환) + 거래처
fs05_co = q(
    "SELECT count(DISTINCT company_code) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS05'"
)[0][0]
print(
    f"FS05 순환: 관여 회사 {fs05_co}개 → 3사원환 {'있음' if fs05_co >= 3 else '없음(단일회사, cycle 부재)'}"
)

# FS06 부채누락: 기말제거↔기초원복 짝
fs06_rm = docs("FS06", "liability_removal")
fs06_rb = docs("FS06", "period_start_rebooking")
print(
    f"FS06 부채누락: 기말제거 {fs06_rm}건 ↔ 기초원복 {fs06_rb}건 → 짝 {'있음' if fs06_rm > 0 and fs06_rb > 0 else '없음'}"
)

# FS07 재고과대: 재고증가+COGS과소
fs07_inv = q(
    "SELECT round(sum(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS07' AND j.semantic_account_subtype='INVENTORY'"
)[0][0]
print(
    f"FS07 재고과대: 재고 순증 {fs07_inv:,.0f} → {'있음' if fs07_inv and fs07_inv > 0 else '없음'}"
)

# FS08 자본화: 무형자산 증가
fs08 = q(
    "SELECT round(sum(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS08' AND j.semantic_account_subtype='intangible_development_cost'"
)[0][0]
print(f"FS08 자본화: 무형자산 순증 {fs08:,.0f} → {'있음' if fs08 and fs08 > 0 else '없음'}")

# FS09 cutoff: 12월매출/1월반품 시점짝 + delivery역전
fs09_pf = q(
    "SELECT count(DISTINCT document_id) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS09' AND p.component_role='pulled_forward_sale' AND substr(posting_date,6,2)='12'"
)[0][0]
fs09_ret = q(
    "SELECT count(DISTINCT document_id) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS09' AND p.component_role='next_period_return' AND substr(posting_date,6,2)='01'"
)[0][0]
print(
    f"FS09 cutoff: 12월 조기인식 {fs09_pf}건 ↔ 1월 반품 {fs09_ret}건 → 시점짝 {'있음' if fs09_pf > 0 and fs09_ret > 0 else '없음'}"
)

# FS10 대손회피: 위장입금↔차환 + 충당금
fs10_ref = docs("FS10", "fake_collection_refinance")
fs10_all = q(
    "SELECT list_sort(array_agg(DISTINCT semantic_account_subtype)) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS10'"
)[0][0]
print(
    f"FS10 대손회피: 위장입금/차환 {fs10_ref}건, 계정 {fs10_all} → {'있음' if fs10_ref > 0 else '약함'}"
)

# FS11 IC: 비대칭 잔액
fs11 = q(
    "SELECT round(sum(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS11' AND j.semantic_account_subtype='IC_RECEIVABLE'"
)[0][0]
print(f"FS11 IC: IC채권 순증(비대칭) {fs11:,.0f} → {'있음' if fs11 and fs11 > 0 else '없음'}")

# FS12 충당부채(부작위 low-trace)
fs12 = docs("FS12")
print(f"FS12 충당부채: 작위 컨텍스트 {fs12}건 (부작위=메타) → low-trace stratum (탐지 목표 아님)")

# FS13 손상미인식(부작위)
fs13 = q(
    "SELECT round(sum(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS13' AND j.semantic_account_subtype='investments'"
)[0][0]
print(f"FS13 손상미인식: 투자자산 순증 {fs13:,.0f} (손상 부작위=메타) → low-trace")

# FS14 유령직원: 동일계좌 중복 + 월급여 반복
fs14_doc = docs("FS14")
fs14_emp = q(
    "SELECT count(DISTINCT created_by) FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS14'"
)[0][0]
print(
    f"FS14 유령직원: {fs14_doc}건/{fs14_emp}작성자 → 반복급여 {'있음' if fs14_doc >= 12 else '약함'} (계좌중복은 employees.json 교차 필요)"
)

print("\n=== 표본 통계력 ===")
print("scheme별 (instance/문서):")
for r in q(
    "SELECT scheme_id, count(DISTINCT scheme_instance_id), count(DISTINCT document_id) FROM p GROUP BY 1 ORDER BY 1"
):
    print(f"  {r[0]}: inst={r[1]} docs={r[2]}")
print(
    f"\n  총 instance: {q('SELECT count(DISTINCT scheme_instance_id) FROM p')[0][0]}, 총 부정문서: {q('SELECT count(DISTINCT document_id) FROM p')[0][0]}"
)

sys.stdout.flush()
