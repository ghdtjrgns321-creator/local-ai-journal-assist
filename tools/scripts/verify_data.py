"""DataSynth 데이터 정합성 전수 검증 스크립트."""
import duckdb

con = duckdb.connect()
con.execute("CREATE TABLE je AS SELECT * FROM read_csv_auto('data/journal/primary/datasynth/journal_entries.csv', all_varchar=true)")

con.execute("""CREATE TABLE doc AS
    SELECT *,
        CAST(fiscal_year AS INT) AS fy,
        CAST(fiscal_period AS INT) AS fp,
        CAST(debit_amount AS DOUBLE) AS dr,
        CAST(credit_amount AS DOUBLE) AS cr,
        CAST(line_number AS INT) AS ln,
        CASE WHEN is_fraud='true' THEN true ELSE false END AS fraud,
        CASE WHEN is_anomaly='true' THEN true ELSE false END AS anom,
        CASE WHEN sod_violation='true' THEN true ELSE false END AS sod
    FROM je WHERE CAST(line_number AS INT) = 1
""")

con.execute("""CREATE TABLE je2 AS SELECT *,
    CAST(debit_amount AS DOUBLE) AS dr2, CAST(credit_amount AS DOUBLE) AS cr2
    FROM je""")

# ====================================================================
print("=" * 70)
print("1. 정상 vs 비정상 분리")
print("=" * 70)
for cat, cnt, pct in con.execute("""
    SELECT CASE WHEN fraud THEN 'fraud' WHEN anom THEN 'anomaly' ELSE 'normal' END,
           COUNT(*), ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(),1)
    FROM doc GROUP BY 1 ORDER BY 1
""").fetchall():
    print(f"  {cat}: {cnt:,} ({pct}%)")

# ====================================================================
print()
print("=" * 70)
print("2. 정상 데이터 무결성")
print("=" * 70)

# 차대변 균형
unbal = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT document_id, ABS(SUM(dr2) - SUM(cr2)) as diff
        FROM je2 WHERE document_id IN (SELECT document_id FROM doc WHERE NOT fraud AND NOT anom)
        GROUP BY document_id HAVING diff > 2
    )
""").fetchone()[0]
print(f"  차대변 불균형: {unbal} -> {'PASS' if unbal==0 else 'FAIL'}")

# 음수 금액
neg = con.execute("""
    SELECT COUNT(*) FROM je2
    WHERE document_id IN (SELECT document_id FROM doc WHERE NOT fraud AND NOT anom)
    AND (dr2 < 0 OR cr2 < 0)
""").fetchone()[0]
print(f"  음수 금액: {neg} -> {'PASS' if neg==0 else 'FAIL'}")

# 기간 범위
out = con.execute("""
    SELECT COUNT(*) FROM doc WHERE NOT fraud AND NOT anom
    AND (CAST(posting_date AS DATE) < '2022-01-01' OR CAST(posting_date AS DATE) >= '2025-01-01')
""").fetchone()[0]
print(f"  기간 범위 벗어남: {out} -> {'PASS' if out==0 else 'FAIL'}")

# fiscal_year
fym = con.execute("""
    SELECT COUNT(*) FROM doc WHERE NOT fraud AND NOT anom
    AND fy != YEAR(CAST(posting_date AS DATE))
""").fetchone()[0]
print(f"  fiscal_year 불일치: {fym} -> {'PASS' if fym==0 else 'FAIL'}")

# fiscal_period
fpm = con.execute("""
    SELECT COUNT(*) FROM doc WHERE NOT fraud AND NOT anom
    AND fp != MONTH(CAST(posting_date AS DATE))
""").fetchone()[0]
print(f"  fiscal_period 불일치: {fpm} -> {'PASS' if fpm==0 else 'FAIL'}")

# 자기승인
sa_auto = con.execute("""
    SELECT COUNT(*) FROM doc WHERE NOT fraud AND NOT anom
    AND created_by = approved_by AND approved_by IS NOT NULL AND approved_by != ''
    AND (user_persona = 'automated_system' OR source IN ('Automated','Recurring'))
""").fetchone()[0]
sa_human = con.execute("""
    SELECT COUNT(*) FROM doc WHERE NOT fraud AND NOT anom
    AND created_by = approved_by AND approved_by IS NOT NULL AND approved_by != ''
    AND user_persona != 'automated_system' AND source NOT IN ('Automated','Recurring')
""").fetchone()[0]
print(f"  자기승인 (시스템): {sa_auto:,} (정상)")
print(f"  자기승인 (사람): {sa_human:,} -> {'PASS' if sa_human==0 else 'WARNING'}")
if sa_human > 0:
    for p, c in con.execute("""
        SELECT user_persona, COUNT(*) FROM doc WHERE NOT fraud AND NOT anom
        AND created_by = approved_by AND approved_by IS NOT NULL AND approved_by != ''
        AND user_persona != 'automated_system' AND source NOT IN ('Automated','Recurring')
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall():
        print(f"    {p}: {c}")

# ====================================================================
print()
print("=" * 70)
print("3. 비정상 데이터 -라벨 존재")
print("=" * 70)

ft = con.execute("SELECT COUNT(*) FROM doc WHERE fraud AND (fraud_type IS NULL OR fraud_type = '')").fetchone()[0]
print(f"  fraud인데 type 없음: {ft} -> {'PASS' if ft==0 else 'FAIL'}")

at = con.execute("SELECT COUNT(*) FROM doc WHERE anom AND (anomaly_type IS NULL OR anomaly_type = '')").fetchone()[0]
print(f"  anomaly인데 type 없음: {at} -> {'PASS' if at==0 else 'FAIL'}")

print()
print("  fraud_type 분포:")
for ft, cnt in con.execute("SELECT fraud_type, COUNT(*) FROM doc WHERE fraud GROUP BY 1 ORDER BY 2 DESC").fetchall():
    print(f"    {ft}: {cnt:,}")

print()
print("  anomaly_type 분포 (상위 20):")
for at, cnt in con.execute("SELECT anomaly_type, COUNT(*) FROM doc WHERE anom GROUP BY 1 ORDER BY 2 DESC LIMIT 20").fetchall():
    print(f"    {at}: {cnt:,}")

# ====================================================================
print()
print("=" * 70)
print("4. 비정상 데이터 -실제 이상 수치 검증")
print("=" * 70)

# SelfApproval: created_by == approved_by
sa_ok = con.execute("""
    SELECT COUNT(*) FROM doc WHERE fraud_type = 'SelfApproval' AND created_by = approved_by
""").fetchone()[0]
sa_all = con.execute("SELECT COUNT(*) FROM doc WHERE fraud_type = 'SelfApproval'").fetchone()[0]
print(f"  SelfApproval 실제 자기승인: {sa_ok}/{sa_all} -> {'PASS' if sa_ok==sa_all else 'FAIL'}")

# UnauthorizedAccess: 심야 시간
ua_night = con.execute("""
    SELECT COUNT(*) FROM doc WHERE fraud_type = 'UnauthorizedAccess'
    AND (CAST(SUBSTR(posting_date, 12, 2) AS INT) >= 22 OR CAST(SUBSTR(posting_date, 12, 2) AS INT) < 6)
""").fetchone()[0]
ua_all = con.execute("SELECT COUNT(*) FROM doc WHERE fraud_type = 'UnauthorizedAccess'").fetchone()[0]
print(f"  UnauthorizedAccess 심야: {ua_night}/{ua_all} ({ua_night*100//max(ua_all,1)}%)")

# TimingAnomaly: posting vs document date 차이
timing = con.execute("""
    SELECT ROUND(AVG(ABS(DATEDIFF('day', CAST(posting_date AS DATE), CAST(document_date AS DATE)))),1)
    FROM doc WHERE fraud_type = 'TimingAnomaly'
""").fetchone()[0]
print(f"  TimingAnomaly 평균 날짜차이: {timing}일")

# RevenueManipulation: 수익 관련 GL (4xxx)
rev_gl = con.execute("""
    SELECT COUNT(*) FROM doc WHERE fraud_type = 'RevenueManipulation'
    AND gl_account LIKE '4%'
""").fetchone()[0]
rev_all = con.execute("SELECT COUNT(*) FROM doc WHERE fraud_type = 'RevenueManipulation'").fetchone()[0]
print(f"  RevenueManipulation 수익GL 사용: {rev_gl}/{rev_all} ({rev_gl*100//max(rev_all,1)}%)")

# ExpenseCapitalization: 비용 계정 → 자산 계정
ec_all = con.execute("SELECT COUNT(*) FROM doc WHERE fraud_type = 'ExpenseCapitalization'").fetchone()[0]
print(f"  ExpenseCapitalization: {ec_all}건")

# SuspenseAccountAbuse: 가수금/가지급 GL 사용
sus_gl = con.execute("""
    SELECT COUNT(*) FROM doc WHERE fraud_type = 'SuspenseAccountAbuse'
""").fetchone()[0]
print(f"  SuspenseAccountAbuse: {sus_gl}건")

# DuplicatePayment: vendor+금액 중복 존재
dup_pairs = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT trading_partner, dr FROM doc
        WHERE fraud_type = 'DuplicatePayment' AND dr > 0 AND trading_partner IS NOT NULL AND trading_partner != ''
        GROUP BY 1, 2 HAVING COUNT(*) >= 2
    )
""").fetchone()[0]
dup_all = con.execute("SELECT COUNT(*) FROM doc WHERE fraud_type = 'DuplicatePayment'").fetchone()[0]
print(f"  DuplicatePayment 중복 쌍: {dup_pairs}쌍 (전체 {dup_all}건)")

# SplitTransaction: 금액 분포 확인
split_stats = con.execute("""
    SELECT ROUND(AVG(dr),0), ROUND(MAX(dr),0), COUNT(*)
    FROM doc WHERE fraud_type = 'SplitTransaction' AND dr > 0
""").fetchone()
print(f"  SplitTransaction: avg={split_stats[0]:,.0f} max={split_stats[1]:,.0f} ({split_stats[2]}건)")

# ====================================================================
print()
print("=" * 70)
print("5. 비정상 데이터 -anomaly 실제 이상 수치")
print("=" * 70)

# UnusualTiming: 주말/공휴일/심야
ut_weekend = con.execute("""
    SELECT COUNT(*) FROM doc WHERE anomaly_type = 'UnusualTiming'
    AND DAYOFWEEK(CAST(posting_date AS DATE)) IN (0, 6)
""").fetchone()[0]
ut_all = con.execute("SELECT COUNT(*) FROM doc WHERE anomaly_type = 'UnusualTiming'").fetchone()[0]
print(f"  UnusualTiming 주말: {ut_weekend}/{ut_all}")

# DormantAccountActivity
da = con.execute("SELECT COUNT(*) FROM doc WHERE anomaly_type = 'DormantAccountActivity'").fetchone()[0]
print(f"  DormantAccountActivity: {da:,}건")

# CircularTransaction
ct = con.execute("SELECT COUNT(*) FROM doc WHERE anomaly_type = 'CircularTransaction'").fetchone()[0]
print(f"  CircularTransaction: {ct:,}건")

# ExceededApprovalLimit
eal = con.execute("SELECT COUNT(*) FROM doc WHERE anomaly_type = 'ExceededApprovalLimit'").fetchone()[0]
print(f"  ExceededApprovalLimit: {eal:,}건")

# UnbalancedEntry: 차대변 불균형
ub_real = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT document_id, ABS(SUM(dr2) - SUM(cr2)) as diff
        FROM je2 WHERE document_id IN (SELECT document_id FROM doc WHERE anomaly_type = 'UnbalancedEntry')
        GROUP BY document_id HAVING diff > 2
    )
""").fetchone()[0]
ub_all = con.execute("SELECT COUNT(*) FROM doc WHERE anomaly_type = 'UnbalancedEntry'").fetchone()[0]
print(f"  UnbalancedEntry 실제 불균형: {ub_real}/{ub_all} -> {'PASS' if ub_real == ub_all or ub_all == 0 else 'CHECK'}")

# WrongPeriod: fiscal_period != month(posting_date)
wp_real = con.execute("""
    SELECT COUNT(*) FROM doc WHERE anomaly_type = 'WrongPeriod'
    AND fp != MONTH(CAST(posting_date AS DATE))
""").fetchone()[0]
wp_all = con.execute("SELECT COUNT(*) FROM doc WHERE anomaly_type = 'WrongPeriod'").fetchone()[0]
print(f"  WrongPeriod 실제 불일치: {wp_real}/{wp_all} -> {'PASS' if wp_real == wp_all or wp_all == 0 else 'CHECK'}")

# ====================================================================
print()
print("=" * 70)
print("6. 정상 데이터 -금액 분포")
print("=" * 70)
stats = con.execute("""
    SELECT ROUND(AVG(dr),0), ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dr),0),
           ROUND(MIN(dr),0), ROUND(MAX(dr),0), ROUND(STDDEV(dr),0)
    FROM doc WHERE NOT fraud AND NOT anom AND dr > 0
""").fetchone()
print(f"  정상 debit: avg={stats[0]:,.0f} med={stats[1]:,.0f} min={stats[2]:,.0f} max={stats[3]:,.0f} std={stats[4]:,.0f}")

stats2 = con.execute("""
    SELECT ROUND(AVG(cr),0), ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cr),0),
           ROUND(MIN(cr),0), ROUND(MAX(cr),0)
    FROM doc WHERE NOT fraud AND NOT anom AND cr > 0
""").fetchone()
print(f"  정상 credit: avg={stats2[0]:,.0f} med={stats2[1]:,.0f} min={stats2[2]:,.0f} max={stats2[3]:,.0f}")

# ====================================================================
print()
print("=" * 70)
print("종합")
print("=" * 70)
total = con.execute("SELECT COUNT(*) FROM doc").fetchone()[0]
print(f"  전체 전표: {total:,}")
print(f"  정상: {total - con.execute('SELECT COUNT(*) FROM doc WHERE fraud OR anom').fetchone()[0]:,}")
print(f"  비정상: {con.execute('SELECT COUNT(*) FROM doc WHERE fraud OR anom').fetchone()[0]:,}")

con.close()
