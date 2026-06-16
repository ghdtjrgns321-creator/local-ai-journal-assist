"""
audit_amounts_tax.py — 금액·세금·통화 정합 측정 (측정만, 수정 없음)
기본 대상: datasynth_semantic_v1_normal_20260613_v42j/journal_entries.csv
"""

import math
import sys
from pathlib import Path

import duckdb

BASE = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
DEFAULT_DATASET = BASE / "data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j"
DATASET = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else DEFAULT_DATASET
)
CSV = DATASET / "journal_entries.csv"

if not CSV.exists():
    raise SystemExit(f"journal_entries.csv not found: {CSV}")

con = duckdb.connect(":memory:")

print("=== 데이터 로드 중 ===")
con.execute(f"""
CREATE TABLE je AS SELECT * FROM read_csv_auto('{CSV}', sample_size=200000, ignore_errors=true)
""")
total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
print(f"총 행: {total:,}\n")
print(f"대상 데이터셋: {DATASET}\n")

sep = "=" * 60

# ─────────────────────────────────────────────
# 1. Benford 1st digit (local_amount 절댓값 양수)
# ─────────────────────────────────────────────
print(sep)
print("【1】 Benford 1st Digit — local_amount")
print(sep)

benford_expected = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

rows = con.execute("""
    SELECT
        CAST(LEFT(CAST(CAST(ABS(local_amount) AS BIGINT) AS VARCHAR), 1) AS INTEGER) AS d,
        COUNT(*) AS cnt
    FROM je
    WHERE local_amount IS NOT NULL
      AND ABS(local_amount) >= 1
      AND LEFT(CAST(CAST(ABS(local_amount) AS BIGINT) AS VARCHAR), 1) BETWEEN '1' AND '9'
    GROUP BY 1
    ORDER BY 1
""").fetchall()

total_benford = sum(r[1] for r in rows)
dist = {r[0]: r[1] / total_benford for r in rows}

print(f"{'Digit':>6} {'Observed%':>10} {'Expected%':>10} {'AbsDiff':>9}")
mad_sum = 0.0
for d in range(1, 10):
    obs = dist.get(d, 0.0)
    exp = benford_expected[d]
    diff = abs(obs - exp)
    mad_sum += diff
    print(f"  {d:>4}   {obs * 100:9.2f}   {exp * 100:9.2f}   {diff * 100:8.3f}%")

mad = mad_sum / 9
verdict = "PASS" if mad < 0.015 else "FAIL"
print(f"\nMAD = {mad:.5f}  → {verdict} (기준 <0.015)")
print(f"[분류] {'데이터 특성' if verdict == 'PASS' else '코드버그 또는 데이터 특성'}")

# ─────────────────────────────────────────────
# 2. 분포 단절 & 반복 금액
# ─────────────────────────────────────────────
print(f"\n{sep}")
print("【2】 금액 분포 단절 & 반복 금액")
print(sep)

# log-scale 구간 분포 (양수 local_amount)
buckets = con.execute("""
    SELECT
        FLOOR(LOG10(ABS(local_amount))) AS log_bucket,
        COUNT(*) AS cnt
    FROM je
    WHERE local_amount IS NOT NULL AND ABS(local_amount) >= 1
    GROUP BY 1
    ORDER BY 1
""").fetchall()

print("log10 구간 분포 (0=1~9원, 1=10~99원, ...):")
prev_bucket = None
gap_flags = []
for b, c in buckets:
    if b is None:
        continue
    if prev_bucket is not None and b - prev_bucket > 1:
        gap_flags.append((prev_bucket, b))
        print(f"  *** 구간 단절: {prev_bucket:.0f} → {b:.0f} ***")
    print(f"  10^{b:.0f} 구간: {c:>10,} 행")
    prev_bucket = b

if gap_flags:
    print(f"단절 구간 {len(gap_flags)}개 → FAIL (코드버그 가능성)")
else:
    print("단절 없음 → PASS")

# 동일 금액 반복 top 10
print("\n동일 금액 반복 Top10 (생성기 티 탐지):")
top_repeat = con.execute("""
    SELECT local_amount, COUNT(*) AS cnt
    FROM je
    WHERE local_amount IS NOT NULL AND local_amount > 0
    GROUP BY local_amount
    ORDER BY cnt DESC
    LIMIT 10
""").fetchall()

for amt, cnt in top_repeat:
    pct = cnt / total * 100
    flag = " ← ⚠ 과반복" if pct > 0.5 else ""
    print(f"  {amt:>15,.0f} : {cnt:>8,} 회  ({pct:.3f}%){flag}")

# 완전 중복 금액(전체의 0.5% 초과) 건수
suspicious = sum(1 for _, cnt in top_repeat if cnt / total > 0.005)
print(
    f"\n0.5% 초과 반복 금액 종류: {suspicious}개 → {'FAIL (생성기 티)' if suspicious > 0 else 'PASS'}"
)
print(f"[분류] {'코드버그' if suspicious > 0 else '데이터 특성'}")

# ─────────────────────────────────────────────
# 3. 세금 정합
# ─────────────────────────────────────────────
print(f"\n{sep}")
print("【3】 세금 정합")
print(sep)

# 3a. taxable_10: tax_amount ≈ supply_amount * 10%
taxable_total = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE tax_treatment = 'taxable_10'
      AND supply_amount IS NOT NULL AND supply_amount > 0
      AND tax_amount IS NOT NULL
""").fetchone()[0]

taxable_mismatch = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE tax_treatment = 'taxable_10'
      AND supply_amount IS NOT NULL AND supply_amount > 0
      AND tax_amount IS NOT NULL
      AND ABS(tax_amount - supply_amount * 0.1) > 1
""").fetchone()[0]

pct_mismatch = taxable_mismatch / taxable_total * 100 if taxable_total > 0 else 0
verdict_3a = "PASS" if pct_mismatch < 1 else "FAIL"
print("3a. taxable_10 tax_amount 정합")
print(f"    대상: {taxable_total:,}행  불일치(>1원): {taxable_mismatch:,}행  ({pct_mismatch:.2f}%)")
print(f"    → {verdict_3a}")
if taxable_mismatch > 0:
    sample = con.execute("""
        SELECT supply_amount, tax_amount, ROUND(supply_amount*0.1,2) AS expected,
               ABS(tax_amount - supply_amount*0.1) AS diff
        FROM je
        WHERE tax_treatment = 'taxable_10'
          AND supply_amount > 0 AND tax_amount IS NOT NULL
          AND ABS(tax_amount - supply_amount * 0.1) > 1
        ORDER BY diff DESC LIMIT 5
    """).fetchall()
    print("    불일치 샘플 (supply, tax_actual, tax_expected, diff):")
    for row in sample:
        print(
            f"      supply={row[0]:>12,.1f}  tax={row[1]:>12,.1f}  exp={row[2]:>12,.1f}  diff={row[3]:,.1f}"
        )
print(f"[분류] {'코드버그' if verdict_3a == 'FAIL' else '데이터 특성'}")

# 3b. invoice_amount = supply_amount + tax_amount (taxable_10)
inv_total = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE tax_treatment = 'taxable_10'
      AND invoice_amount IS NOT NULL AND supply_amount IS NOT NULL AND tax_amount IS NOT NULL
      AND line_number = 1
""").fetchone()[0]

inv_mismatch = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE tax_treatment = 'taxable_10'
      AND invoice_amount IS NOT NULL AND supply_amount IS NOT NULL AND tax_amount IS NOT NULL
      AND line_number = 1
      AND ABS(invoice_amount - (supply_amount + tax_amount)) > 1
""").fetchone()[0]

pct_inv = inv_mismatch / inv_total * 100 if inv_total > 0 else 0
verdict_3b = "PASS" if pct_inv < 1 else "FAIL"
print("\n3b. invoice = supply + tax 정합 (line_number=1 기준)")
print(f"    대상: {inv_total:,}행  불일치: {inv_mismatch:,}행  ({pct_inv:.2f}%)")
print(f"    → {verdict_3b}")
print(f"[분류] {'코드버그' if verdict_3b == 'FAIL' else '데이터 특성'}")

# 3c. 면세/영세율 처리 일관성
print("\n3c. 면세/영세율 tax_amount=0 or NULL 일관성")
exempt_rows = con.execute("""
    SELECT tax_treatment, COUNT(*) AS total,
           SUM(CASE WHEN tax_amount IS NULL OR tax_amount = 0 THEN 1 ELSE 0 END) AS zero_null,
           SUM(CASE WHEN tax_amount > 0 THEN 1 ELSE 0 END) AS nonzero
    FROM je
    WHERE tax_treatment IN ('exempt','zero_rated','tax_exempt','tax_free','영세율','면세')
       OR tax_treatment ILIKE '%exempt%' OR tax_treatment ILIKE '%zero%'
    GROUP BY tax_treatment
    ORDER BY tax_treatment
""").fetchall()

all_tax_treatments = con.execute("""
    SELECT DISTINCT tax_treatment FROM je ORDER BY 1
""").fetchall()
print(f"    전체 tax_treatment 종류: {[r[0] for r in all_tax_treatments]}")

if exempt_rows:
    for tt, tot, zn, nz in exempt_rows:
        verdict_c = "PASS" if nz == 0 else "FAIL"
        print(f"    {tt}: 총 {tot:,}  zero/null={zn:,}  nonzero={nz:,} → {verdict_c}")
else:
    # 정확한 값 확인
    tt_dist = con.execute("""
        SELECT tax_treatment, COUNT(*) AS cnt,
               SUM(CASE WHEN tax_amount IS NULL OR tax_amount = 0 THEN 1 ELSE 0 END) AS zero_null,
               SUM(CASE WHEN tax_amount > 0 THEN 1 ELSE 0 END) AS nonzero
        FROM je
        GROUP BY tax_treatment ORDER BY cnt DESC
    """).fetchall()
    print("    tax_treatment 전체 분포:")
    for tt, cnt, zn, nz in tt_dist:
        verdict_c = "PASS" if (tt in ("taxable_10",) or nz == 0 or zn == 0) else "관찰"
        print(f"    {str(tt):<20} 총={cnt:>8,}  zero/null={zn:>8,}  nonzero={nz:>8,} → {verdict_c}")
print("[분류] Graceful Degradation (면세 처리 일관성은 생성기 설계 의도)")

# ─────────────────────────────────────────────
# 4. 통화·환율
# ─────────────────────────────────────────────
print(f"\n{sep}")
print("【4】 통화·환율 정합")
print(sep)

curr_dist = con.execute("""
    SELECT currency, COUNT(*) AS cnt,
           ROUND(cnt * 100.0 / SUM(cnt) OVER (), 2) AS pct
    FROM je
    GROUP BY currency ORDER BY cnt DESC
""").fetchall()
print("currency 분포:")
for cur, cnt, pct in curr_dist:
    print(f"  {str(cur):<8} {cnt:>10,}  ({pct:.2f}%)")

# KRW인데 exchange_rate != 1
krw_bad = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE currency = 'KRW' AND (exchange_rate IS NULL OR ABS(exchange_rate - 1) > 0.001)
""").fetchone()[0]
krw_total = con.execute("SELECT COUNT(*) FROM je WHERE currency = 'KRW'").fetchone()[0]
verdict_4a = "PASS" if krw_bad == 0 else "FAIL"
print(f"\nKRW exchange_rate≠1: {krw_bad:,} / {krw_total:,} → {verdict_4a}")
print(f"[분류] {'코드버그' if verdict_4a == 'FAIL' else '데이터 특성'}")

# 외화: local_amount = 외화금액 × 환율 (debit_amount 또는 credit_amount 비영 기준)
fcy_rows = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE currency != 'KRW'
      AND exchange_rate IS NOT NULL AND exchange_rate > 0
      AND (debit_amount > 0 OR credit_amount > 0)
      AND local_amount IS NOT NULL
""").fetchone()[0]

fcy_mismatch = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE currency != 'KRW'
      AND exchange_rate IS NOT NULL AND exchange_rate > 0
      AND (debit_amount > 0 OR credit_amount > 0)
      AND local_amount IS NOT NULL
      AND ABS(local_amount -
              GREATEST(debit_amount, credit_amount) * exchange_rate) > 1
""").fetchone()[0]

pct_fcy = fcy_mismatch / fcy_rows * 100 if fcy_rows > 0 else 0
verdict_4b = "PASS" if pct_fcy < 1 else "FAIL"
print(
    f"\n외화 local = 외화×환율 정합: 대상 {fcy_rows:,}  불일치 {fcy_mismatch:,} ({pct_fcy:.2f}%) → {verdict_4b}"
)
if fcy_mismatch > 0:
    fcy_sample = con.execute("""
        SELECT currency, exchange_rate,
               GREATEST(debit_amount, credit_amount) AS fcy_amt,
               local_amount,
               ABS(local_amount - GREATEST(debit_amount, credit_amount)*exchange_rate) AS diff
        FROM je
        WHERE currency != 'KRW' AND exchange_rate > 0
          AND (debit_amount > 0 OR credit_amount > 0)
          AND local_amount IS NOT NULL
          AND ABS(local_amount - GREATEST(debit_amount, credit_amount)*exchange_rate) > 1
        ORDER BY diff DESC LIMIT 5
    """).fetchall()
    print("    불일치 샘플 (cur, rate, fcy, local, diff):")
    for row in fcy_sample:
        print(
            f"      {row[0]}  rate={row[1]:.4f}  fcy={row[2]:,.0f}  local={row[3]:,.0f}  diff={row[4]:,.1f}"
        )
print(f"[분류] {'코드버그' if verdict_4b == 'FAIL' else '데이터 특성'}")

# ─────────────────────────────────────────────
# 5. 음수·0 금액
# ─────────────────────────────────────────────
print(f"\n{sep}")
print("【5】 음수·0 금액")
print(sep)

neg_debit = con.execute("SELECT COUNT(*) FROM je WHERE debit_amount < 0").fetchone()[0]
neg_credit = con.execute("SELECT COUNT(*) FROM je WHERE credit_amount < 0").fetchone()[0]
both_zero = con.execute(
    "SELECT COUNT(*) FROM je WHERE (debit_amount = 0 OR debit_amount IS NULL) AND (credit_amount = 0 OR credit_amount IS NULL)"
).fetchone()[0]
neg_local = con.execute("SELECT COUNT(*) FROM je WHERE local_amount < 0").fetchone()[0]

verdict_5a = "PASS" if neg_debit == 0 else "FAIL"
verdict_5b = "PASS" if neg_credit == 0 else "FAIL"
verdict_5c = "PASS" if both_zero == 0 else "관찰"
print(f"debit_amount < 0: {neg_debit:,} → {verdict_5a}")
print(f"credit_amount < 0: {neg_credit:,} → {verdict_5b}")
print(f"local_amount < 0: {neg_local:,} (역분개 정상 포함 가능)")
print(f"debit=0 AND credit=0: {both_zero:,} → {verdict_5c}")
print(f"[분류] {'코드버그' if neg_debit > 0 or neg_credit > 0 else 'Graceful Degradation'}")

# ─────────────────────────────────────────────
# 6. 자릿수·끝자리 0 집중
# ─────────────────────────────────────────────
print(f"\n{sep}")
print("【6】 자릿수·끝자리 0 집중 (라운드 금액 비율)")
print(sep)

# 끝자리 0: 10 단위, 100 단위, 1000 단위
amt_base = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE local_amount IS NOT NULL AND ABS(local_amount) >= 10
""").fetchone()[0]

round_10 = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE local_amount IS NOT NULL AND ABS(local_amount) >= 10
      AND MOD(CAST(ABS(local_amount) AS BIGINT), 10) = 0
""").fetchone()[0]
round_100 = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE local_amount IS NOT NULL AND ABS(local_amount) >= 100
      AND MOD(CAST(ABS(local_amount) AS BIGINT), 100) = 0
""").fetchone()[0]
round_1000 = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE local_amount IS NOT NULL AND ABS(local_amount) >= 1000
      AND MOD(CAST(ABS(local_amount) AS BIGINT), 1000) = 0
""").fetchone()[0]

pct_10 = round_10 / amt_base * 100 if amt_base > 0 else 0
pct_100 = round_100 / amt_base * 100 if amt_base > 0 else 0
pct_1000 = round_1000 / amt_base * 100 if amt_base > 0 else 0

# 현실 기준: 10단위 끝자리 50~70% 정상 범위 (VAT 계산 전표는 단수 많음)
verdict_6 = "PASS" if pct_10 < 80 else "FAIL"
print(f"끝자리 ÷10=0 : {round_10:>10,} / {amt_base:,}  = {pct_10:.1f}%")
print(f"끝자리 ÷100=0: {round_100:>10,} / {amt_base:,}  = {pct_100:.1f}%")
print(f"끝자리 ÷1000=0:{round_1000:>10,} / {amt_base:,}  = {pct_1000:.1f}%")
print(f"\n10단위 라운드 비율 {pct_10:.1f}% → {verdict_6} (기준 <80%)")
print(
    f"[분류] {'코드버그 — 생성기가 단수를 생략했을 가능성' if verdict_6 == 'FAIL' else '데이터 특성'}"
)

# 단수(1원 단위) 건수
penny = con.execute("""
    SELECT COUNT(*) FROM je
    WHERE local_amount IS NOT NULL AND ABS(local_amount) >= 1
      AND MOD(CAST(ABS(local_amount) AS BIGINT), 10) != 0
""").fetchone()[0]
print(f"단수(1원 단위) 행: {penny:,}  ({penny / amt_base * 100:.1f}%)")

# ─────────────────────────────────────────────
# 최종 판정
# ─────────────────────────────────────────────
print(f"\n{sep}")
print("【최종 요약】")
print(sep)

results = [
    ("Benford MAD", "PASS" if mad < 0.015 else "FAIL", f"MAD={mad:.5f}"),
    ("금액 분포 단절", "PASS" if not gap_flags else "FAIL", f"단절구간={len(gap_flags)}"),
    ("반복금액(생성기 티)", "PASS" if suspicious == 0 else "FAIL", f"{suspicious}종 0.5%초과"),
    ("taxable_10 세율 정합", verdict_3a, f"{pct_mismatch:.2f}% 불일치"),
    ("invoice=supply+tax", verdict_3b, f"{pct_inv:.2f}% 불일치"),
    ("KRW exchange_rate", verdict_4a, f"{krw_bad:,} 건"),
    ("외화 local 정합", verdict_4b, f"{pct_fcy:.2f}% 불일치"),
    (
        "음수 debit/credit",
        verdict_5a if neg_debit == 0 else "FAIL",
        f"debit음수={neg_debit} credit음수={neg_credit}",
    ),
    ("라운드금액 비율", verdict_6, f"10단위={pct_10:.1f}%"),
]

fail_count = sum(1 for _, v, _ in results if v == "FAIL")
for name, verdict, detail in results:
    print(f"  {'✓' if verdict == 'PASS' else '✗'} {name:<25} {verdict:<8} {detail}")

print(f"\nFAIL 항목: {fail_count}/{len(results)}")
print()
print("PHASE2 금액 피처 학습 걸림 판정:")
if fail_count == 0:
    print("  → 걸림 없음. 금액·세금·통화 모두 정합, PHASE2 피처 학습에 바로 투입 가능.")
elif fail_count <= 2:
    print("  → 경미한 걸림. FAIL 항목 확인 후 단순 보정이면 허용 가능, 피처 생성 시 오염 없음.")
else:
    print(
        f"  → 걸림 있음. {fail_count}개 FAIL — 생성기 금액 엔진 결함이 피처 분포를 왜곡할 수 있음. 수정 후 재생성 권장."
    )

con.close()
sys.exit(1 if fail_count else 0)
