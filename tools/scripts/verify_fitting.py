"""fitting 방지 검증: 정상 전표에 가계정 GL + 키워드 존재 확인."""
import duckdb

con = duckdb.connect()
con.execute("CREATE TABLE je AS SELECT * FROM read_csv_auto('data/journal/primary/datasynth/journal_entries.csv', all_varchar=true)")

results = []

print("=" * 70)
print("1. Suspense GL이 정상 전표에도 존재하는지")
print("=" * 70)
for gl in ['1190', '2190', '1290', '9990', '4200']:
    normal = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
        AND gl_account = '{gl}'
    """).fetchone()[0]
    fraud = con.execute(f"""
        SELECT COUNT(*) FROM je WHERE is_fraud = 'true' AND gl_account = '{gl}'
    """).fetchone()[0]
    status = "PASS" if normal > 0 else "FAIL"
    results.append((f"GL {gl} 정상 전표", normal > 0))
    print(f"  GL {gl}: normal={normal:,}, fraud={fraud:,} -> {status}")

print()
print("=" * 70)
print("2. 키워드가 정상 전표에도 존재하는지")
print("=" * 70)
for kw in ['가수금', '가지급', '미결산', '임시', '선급', '단수', '가계정']:
    normal = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
        AND LOWER(COALESCE(line_text,'')) LIKE '%{kw}%'
    """).fetchone()[0]
    fraud = con.execute(f"""
        SELECT COUNT(*) FROM je WHERE is_fraud = 'true'
        AND LOWER(COALESCE(line_text,'')) LIKE '%{kw}%'
    """).fetchone()[0]
    status = "PASS" if normal > 0 else "FAIL"
    results.append((f"키워드 '{kw}' 정상", normal > 0))
    print(f"  '{kw}': normal={normal:,}, fraud={fraud:,} -> {status}")

print()
print("=" * 70)
print("3. 정상 가계정 비율 (~2% 기대)")
print("=" * 70)
normal_total = con.execute("""
    SELECT COUNT(DISTINCT document_id) FROM je
    WHERE is_fraud != 'true' AND is_anomaly != 'true'
    AND CAST(line_number AS INT) = 1
""").fetchone()[0]
normal_suspense = con.execute("""
    SELECT COUNT(DISTINCT document_id) FROM je
    WHERE is_fraud != 'true' AND is_anomaly != 'true'
    AND gl_account IN ('1190','2190','1290','9990','4200')
""").fetchone()[0]
pct = normal_suspense / normal_total * 100 if normal_total else 0
print(f"  정상 전표: {normal_total:,}")
print(f"  가계정 사용: {normal_suspense:,} ({pct:.1f}%)")
ok = 0.5 < pct < 5.0
results.append(("가계정 비율 0.5~5%", ok))
print(f"  -> {'PASS' if ok else 'FAIL'}")

print()
print("=" * 70)
print("4. 차대변 균형 유지 확인")
print("=" * 70)
unbal = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT document_id,
               ABS(SUM(CAST(debit_amount AS DOUBLE)) - SUM(CAST(credit_amount AS DOUBLE))) as diff
        FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
        GROUP BY document_id HAVING diff > 2
    )
""").fetchone()[0]
print(f"  불균형 정상 전표: {unbal} -> {'PASS' if unbal==0 else 'FAIL'}")
results.append(("차대변 균형", unbal == 0))

print()
print("=" * 70)
print("5. document_number 정합성 유지")
print("=" * 70)
null_dn = con.execute("SELECT COUNT(*) FROM je WHERE document_number IS NULL OR document_number = ''").fetchone()[0]
print(f"  NULL document_number: {null_dn} -> {'PASS' if null_dn==0 else 'FAIL'}")
results.append(("document_number 정합", null_dn == 0))

print()
print("=" * 70)
print("종합")
print("=" * 70)
for name, ok in results:
    mark = "[v]" if ok else "[X]"
    print(f"  {mark} {name}")
all_pass = all(ok for _, ok in results)
print(f"\n  -> {'ALL PASS' if all_pass else 'SOME FAILED'}")

con.close()
