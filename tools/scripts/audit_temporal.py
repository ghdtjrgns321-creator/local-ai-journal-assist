"""
audit_temporal.py — 시계열·달력 현실성 측정 (수정 없이 측정·보고만)
PHASE2 TS lane 입력 신호 건강성 점검
"""

import sys

import duckdb

DATASET_PATH = (
    sys.argv[1].rstrip("/\\")
    if len(sys.argv) > 1
    else r"data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j"
)
CSV_PATH = f"{DATASET_PATH}/journal_entries.csv"

con = duckdb.connect()

# ── 기본 로드 확인 ──────────────────────────────────────────────────────────
print("=" * 70)
print("audit_temporal.py — 시계열·달력 현실성 측정")
print("=" * 70)

total = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{CSV_PATH}')").fetchone()[0]
print(f"\n[기본] 총 문서 수: {total:,}")
print(f"[기본] 대상 데이터셋: {DATASET_PATH}")

# ── 공통 테이블 생성 (VIEW는 WINDOW 함수에서 CSV 직접 참조 시 직렬화 오류 발생) ──
con.execute(f"""
CREATE OR REPLACE TABLE je AS
SELECT *,
    TRY_CAST(posting_date AS TIMESTAMP) AS ts_posting,
    TRY_CAST(document_date AS DATE)     AS dt_doc,
    YEAR(TRY_CAST(posting_date AS TIMESTAMP))  AS yr,
    MONTH(TRY_CAST(posting_date AS TIMESTAMP)) AS mo,
    DAY(TRY_CAST(posting_date AS TIMESTAMP))   AS dy,
    HOUR(TRY_CAST(posting_date AS TIMESTAMP))  AS hr,
    DAYOFWEEK(TRY_CAST(posting_date AS TIMESTAMP)) AS dow  -- 0=Sun,6=Sat
FROM read_csv_auto('{CSV_PATH}')
""")

# NULL timestamp 체크
null_ts = con.execute("SELECT COUNT(*) FROM je WHERE ts_posting IS NULL").fetchone()[0]
print(f"[기본] posting_date 파싱 실패(NULL): {null_ts:,}  ({'%.2f' % (null_ts / total * 100)}%)")

# ── 연도 범위 자동 추출 (리터럴 연도 하드코딩 금지) ───────────────────────
yr_range = con.execute("SELECT MIN(yr), MAX(yr) FROM je WHERE ts_posting IS NOT NULL").fetchone()
YR_MIN, YR_MAX = int(yr_range[0]), int(yr_range[1])
print(f"[기본] 데이터 연도 범위: {YR_MIN} ~ {YR_MAX}")
# SQL 주입용 범위 조건 — 모든 WHERE 절에서 이 변수를 사용
YR_FILTER = f"yr BETWEEN {YR_MIN} AND {YR_MAX}"

# ── 1. 월별 문서량 분포 ──────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[1] 월별 문서량 분포 — 결산월 스파이크·공백 확인")
print("=" * 70)

monthly = con.execute(f"""
SELECT yr, mo,
       COUNT(*) AS cnt,
       ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER (PARTITION BY yr), 2) AS pct_yr
FROM je
WHERE ts_posting IS NOT NULL AND {YR_FILTER}
GROUP BY yr, mo
ORDER BY yr, mo
""").fetchall()

print(f"{'YR':>4} {'MO':>3} {'CNT':>10} {'%/YR':>7}  결산월")
closing_months = {3, 6, 9, 12}
prev_yr = None
for yr, mo, cnt, pct in monthly:
    if yr != prev_yr:
        print(f"  --- {yr} ---")
        prev_yr = yr
    flag = "★" if mo in closing_months else " "
    print(f"  {yr:>4} {mo:>3} {cnt:>10,} {pct:>6.2f}%  {flag}")

# 결산월 평균 vs 비결산월 평균
closing_avg = con.execute(f"""
SELECT AVG(cnt) FROM (
    SELECT mo, COUNT(*) cnt FROM je
    WHERE {YR_FILTER} AND mo IN (3,6,9,12)
    GROUP BY yr, mo
)
""").fetchone()[0]

non_closing_avg = con.execute(f"""
SELECT AVG(cnt) FROM (
    SELECT mo, COUNT(*) cnt FROM je
    WHERE {YR_FILTER} AND mo NOT IN (3,6,9,12)
    GROUP BY yr, mo
)
""").fetchone()[0]

ratio = closing_avg / non_closing_avg if non_closing_avg else 0
print(
    f"\n결산월 평균: {closing_avg:,.0f}  /  비결산월 평균: {non_closing_avg:,.0f}  → 배율 {ratio:.2f}x"
)
if ratio >= 1.15:
    verdict1 = "PASS — 결산월 스파이크 존재"
elif ratio >= 0.9:
    verdict1 = "관찰 — 결산월 스파이크 미약 (배율 < 1.15x)"
else:
    verdict1 = "FAIL — 비결산월이 오히려 높음"
print(f"판정: {verdict1}")

# ── 2. 월말 집중도 ────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[2] 월말 집중도 (D-3~말일 vs 전체)")
print("=" * 70)

# 말일 계산: dy >= DAYOFMONTH(LAST_DAY)
monthend = con.execute(f"""
SELECT
    COUNT(*) FILTER (WHERE dy >= DAY(LAST_DAY(DATE_TRUNC('month', ts_posting::DATE))) - 2) AS last3,
    COUNT(*) FILTER (WHERE dy <= 3) AS first3,
    COUNT(*) AS total
FROM je
WHERE ts_posting IS NOT NULL AND {YR_FILTER}
""").fetchone()

last3, first3, tot = monthend
pct_last3 = last3 / tot * 100
pct_first3 = first3 / tot * 100
print(f"월말 D-3~말일: {last3:,}  ({pct_last3:.1f}%)")
print(f"월초 1~3일:    {first3:,}  ({pct_first3:.1f}%)")

# 주별 분포 (1~7일, 8~14일, 15~21일, 22~말일)
week_dist = con.execute(f"""
SELECT
    CASE WHEN dy BETWEEN 1 AND 7   THEN '01-07'
         WHEN dy BETWEEN 8 AND 14  THEN '08-14'
         WHEN dy BETWEEN 15 AND 21 THEN '15-21'
         ELSE '22-말일' END AS week_band,
    COUNT(*) AS cnt,
    ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER(), 2) AS pct
FROM je
WHERE ts_posting IS NOT NULL AND {YR_FILTER}
GROUP BY 1 ORDER BY 1
""").fetchall()

print("\n주별 분포:")
for band, cnt, pct in week_dist:
    print(f"  {band}: {cnt:>10,}  ({pct:.2f}%)")

if pct_last3 >= 20:
    verdict2 = "PASS — 월말 집중 실재 (≥20%)"
elif pct_last3 >= 13:
    verdict2 = "관찰 — 월말 집중 보통 수준 (13~20%)"
else:
    verdict2 = "FAIL — 월말 집중 미약 (<13%), 균등 분포 의심"
print(f"판정: {verdict2}")

# ── 3. 요일 분포 ──────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[3] 요일 분포 (0=일, 1=월 ... 6=토)")
print("=" * 70)

dow_dist = con.execute(f"""
SELECT dow,
       CASE dow WHEN 0 THEN '일' WHEN 1 THEN '월' WHEN 2 THEN '화'
                WHEN 3 THEN '수' WHEN 4 THEN '목' WHEN 5 THEN '금'
                WHEN 6 THEN '토' END AS label,
       COUNT(*) AS cnt,
       ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER(), 2) AS pct
FROM je
WHERE ts_posting IS NOT NULL AND {YR_FILTER}
GROUP BY dow ORDER BY dow
""").fetchall()

weekend_cnt = 0
total_dow = 0
for dow, label, cnt, pct in dow_dist:
    print(f"  {label}요일: {cnt:>10,}  ({pct:.2f}%)")
    if dow in (0, 6):
        weekend_cnt += cnt
    total_dow += cnt

pct_weekend = weekend_cnt / total_dow * 100 if total_dow else 0
print(f"\n주말(토·일) 합계: {weekend_cnt:,}  ({pct_weekend:.2f}%)")

if pct_weekend <= 5:
    verdict3 = "PASS — 주말 비중 현실적 (≤5%)"
elif pct_weekend <= 10:
    verdict3 = "관찰 — 주말 비중 약간 높음 (5~10%)"
else:
    verdict3 = "FAIL — 주말 비중 과다 (>10%), 생성기 균등 분포 의심"
print(f"판정: {verdict3}")

# ── 4. 시간대 분포 ────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[4] 시간대 분포")
print("=" * 70)

hr_dist = con.execute(f"""
SELECT hr,
       COUNT(*) AS cnt,
       ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER(), 3) AS pct
FROM je
WHERE ts_posting IS NOT NULL AND {YR_FILTER}
GROUP BY hr ORDER BY hr
""").fetchall()

biz_cnt = 0
night_cnt = 0
total_hr = 0
print(f"{'HR':>4}  {'CNT':>10}  {'%':>7}  구간")
for hr, cnt, pct in hr_dist:
    if 9 <= hr <= 18:
        zone = "업무"
        biz_cnt += cnt
    elif hr >= 22 or hr <= 6:
        zone = "심야"
        night_cnt += cnt
    else:
        zone = "저녁"
    total_hr += cnt
    print(f"  {hr:>2}시  {cnt:>10,}  {pct:>6.3f}%  {zone}")

pct_biz = biz_cnt / total_hr * 100
pct_night = night_cnt / total_hr * 100
print(f"\n업무시간(09~18): {biz_cnt:,} ({pct_biz:.1f}%)")
print(f"심야(22~06):    {night_cnt:,} ({pct_night:.1f}%)")

# 최다 시간대
peak_hr = max(hr_dist, key=lambda x: x[1])
print(f"피크 시간: {peak_hr[0]}시 ({peak_hr[2]:.3f}%)")

if pct_biz >= 55 and pct_night <= 10:
    verdict4 = "PASS — 업무시간 집중, 심야 낮음"
elif pct_biz >= 40:
    verdict4 = "관찰 — 업무시간 비중 보통"
else:
    verdict4 = "FAIL — 업무시간 집중 미약, 24시간 균등 의심"
print(f"판정: {verdict4}")

# ── 5. posting vs document lag ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[5] posting_date vs document_date 래그")
print("=" * 70)

lag_stats = con.execute(f"""
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE dt_doc IS NOT NULL AND ts_posting IS NOT NULL) AS both_valid,
    COUNT(*) FILTER (WHERE DATE_DIFF('day', dt_doc, ts_posting::DATE) = 0) AS lag0,
    COUNT(*) FILTER (WHERE DATE_DIFF('day', dt_doc, ts_posting::DATE) < 0)  AS neg_lag,
    COUNT(*) FILTER (WHERE DATE_DIFF('day', dt_doc, ts_posting::DATE) BETWEEN 1 AND 7) AS lag1_7,
    COUNT(*) FILTER (WHERE DATE_DIFF('day', dt_doc, ts_posting::DATE) > 30) AS lag_over30,
    AVG(DATE_DIFF('day', dt_doc, ts_posting::DATE)) AS avg_lag,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY DATE_DIFF('day', dt_doc, ts_posting::DATE)) AS median_lag,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY DATE_DIFF('day', dt_doc, ts_posting::DATE)) AS p95_lag,
    MAX(DATE_DIFF('day', dt_doc, ts_posting::DATE)) AS max_lag,
    MIN(DATE_DIFF('day', dt_doc, ts_posting::DATE)) AS min_lag
FROM je
WHERE dt_doc IS NOT NULL AND ts_posting IS NOT NULL AND {YR_FILTER}
""").fetchone()

total_l, both_v, lag0, neg_lag, lag1_7, lag_over30, avg_lag, med_lag, p95_lag, max_lag, min_lag = (
    lag_stats
)
print(f"유효 쌍: {both_v:,} / {total_l:,}")
print(f"lag=0 (당일): {lag0:,}  ({lag0 / both_v * 100:.1f}%)")
print(f"lag<0 (음수, 문서일 이후 먼저 기표): {neg_lag:,}  ({neg_lag / both_v * 100:.2f}%)")
print(f"lag 1~7일:  {lag1_7:,}  ({lag1_7 / both_v * 100:.1f}%)")
print(f"lag >30일:  {lag_over30:,}  ({lag_over30 / both_v * 100:.1f}%)")
print(
    f"평균 lag: {avg_lag:.1f}일  중앙값: {med_lag:.0f}일  P95: {p95_lag:.0f}일  최대: {max_lag}일  최소: {min_lag}일"
)

if neg_lag / both_v > 0.02:
    verdict5 = f"FAIL — 음수 lag {neg_lag / both_v * 100:.2f}% (>2%), 생성 오류 의심"
elif neg_lag > 0:
    verdict5 = f"관찰 — 음수 lag 소수 존재 ({neg_lag:,}건), 허용 범위 내"
else:
    verdict5 = "PASS — 음수 lag 없음"
print(f"판정: {verdict5}")

# ── 6. 연도 간 drift ──────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[6] 연도 간 drift (거래량·금액·계정 구성)")
print("=" * 70)

yr_stats = con.execute(f"""
SELECT yr,
       COUNT(*) AS doc_cnt,
       ROUND(SUM(COALESCE(TRY_CAST(debit_amount AS DOUBLE), 0))) AS total_debit_amt,
       ROUND(AVG(COALESCE(TRY_CAST(debit_amount AS DOUBLE), 0)), 2) AS avg_debit_amt,
       COUNT(DISTINCT gl_account) AS uniq_accounts
FROM je
WHERE ts_posting IS NOT NULL AND {YR_FILTER}
GROUP BY yr ORDER BY yr
""").fetchall()

print(f"{'YR':>4}  {'문서수':>10}  {'총차변금액':>18}  {'평균차변금액':>14}  {'GL계정수':>8}")
cnts = []
amts = []
account_sets = {}
for yr, doc_cnt, tot_amt, avg_amt, uniq_acc in yr_stats:
    print(f"  {yr}  {doc_cnt:>10,}  {tot_amt:>18,.0f}  {avg_amt:>12,.2f}  {uniq_acc:>7,}")
    cnts.append(doc_cnt)
    amts.append(tot_amt)
    account_sets[yr] = {
        row[0]
        for row in con.execute(
            f"""
            SELECT DISTINCT CAST(gl_account AS VARCHAR)
            FROM je
            WHERE ts_posting IS NOT NULL AND yr = {int(yr)}
              AND gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) <> ''
            """
        ).fetchall()
    }

if len(cnts) >= 2:
    cnt_cv = (max(cnts) - min(cnts)) / (sum(cnts) / len(cnts)) * 100
    amt_cv = (max(amts) - min(amts)) / (sum(amts) / len(amts)) * 100
    identical_account_sets = len({tuple(sorted(v)) for v in account_sets.values()}) == 1
    print(f"\n문서수 편차(max-min/avg): {cnt_cv:.1f}%")
    print(f"총금액 편차(max-min/avg): {amt_cv:.1f}%")
    print(f"연도별 GL 계정 집합 완전 동일 여부: {identical_account_sets}")
    if cnt_cv < 3 or identical_account_sets:
        verdict6 = "FAIL — 연도별 거래량 drift 부족 또는 GL 계정 집합 완전 동일"
    elif cnt_cv <= 10 and amt_cv <= 10:
        verdict6 = "관찰 — 연도 간 변동 미약 (<10%), 약한 drift"
    else:
        verdict6 = "PASS — 연도 간 자연스러운 변동 존재"
    print(f"판정: {verdict6}")
else:
    verdict6 = "관찰 — 연도 데이터 부족"
    print(f"판정: {verdict6}")

# ── 7. 완전 중복 timestamp 비율 ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[7] 완전 중복 timestamp (같은 posting_date 초 단위 다건)")
print("=" * 70)

dup_stats = con.execute(f"""
WITH ts_cnt AS (
    SELECT ts_posting, COUNT(*) AS n
    FROM je
    WHERE ts_posting IS NOT NULL AND {YR_FILTER}
    GROUP BY ts_posting
)
SELECT
    SUM(n) FILTER (WHERE n > 1) AS dup_rows,
    COUNT(*) FILTER (WHERE n > 1) AS dup_timestamps,
    SUM(n) AS total_rows,
    COUNT(*) AS total_timestamps,
    MAX(n) AS max_dup
FROM ts_cnt
""").fetchone()

dup_rows, dup_ts, tot_rows, tot_ts, max_dup = dup_stats
pct_dup = dup_rows / tot_rows * 100 if tot_rows else 0
print(f"중복 timestamp 수: {dup_ts:,}  (최대 {max_dup}건 동시 발생)")
print(f"중복에 포함된 행: {dup_rows:,}  ({pct_dup:.2f}%)")
print(f"고유 timestamp: {tot_ts:,} / {tot_rows:,}")

if max_dup and max_dup >= 50:
    verdict7 = f"FAIL — 동일 timestamp 최대 {max_dup:,}행, v42 기준(<50) 초과"
elif pct_dup >= 30:
    verdict7 = "FAIL — 중복 timestamp 30%+ 과다, 생성기 균등 배치 의심"
elif pct_dup >= 10:
    verdict7 = f"관찰 — 중복 timestamp {pct_dup:.1f}%, 일부 배치 기표 패턴"
else:
    verdict7 = f"PASS — 중복 timestamp {pct_dup:.1f}% (낮음)"
print(f"판정: {verdict7}")

# ── 최종 판정 ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("■ 종합 판정")
print("=" * 70)
verdicts = [
    ("1 월별분포", verdict1),
    ("2 월말집중", verdict2),
    ("3 요일분포", verdict3),
    ("4 시간대", verdict4),
    ("5 래그", verdict5),
    ("6 연도drift", verdict6),
    ("7 중복TS", verdict7),
]
fails = [v for k, v in verdicts if v.startswith("FAIL")]
obs = [v for k, v in verdicts if v.startswith("관찰")]
for k, v in verdicts:
    mark = "❌" if v.startswith("FAIL") else ("⚠" if v.startswith("관찰") else "✅")
    print(f"  {mark} [{k}] {v}")

print(f"\nFAIL {len(fails)}건 / 관찰 {len(obs)}건 / PASS {7 - len(fails) - len(obs)}건")

# 한 줄 판정
if len(fails) >= 3:
    final = "PHASE2 시계열 학습에 걸림 있음 — 생성기 패턴 다수 잔존, 모델이 아티팩트를 피처로 학습할 위험"
elif len(fails) >= 1:
    final = "PHASE2 시계열 학습에 부분 걸림 — FAIL 항목 수정 권장, 나머지 신호는 사용 가능"
else:
    final = "PHASE2 시계열 학습에 걸림 없음 — 달력·시계열 신호 건강"
print(f"\n[최종] {final}")
print("=" * 70)

con.close()
sys.exit(1 if fails else 0)
