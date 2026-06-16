"""r4e 심층 shortcut 스캔 — 기존 게이트 미커버 차원 전수.

차원: 라벨인접 컬럼 / 거래처 / 시간(시각·요일·일자·lag) / 금액(Benford·자릿수) /
텍스트 토큰 / 식별자 패턴 / 다컬럼 조합.
"""

import sys

import duckdb

OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4h"
con = duckdb.connect()
con.execute(
    f"CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true)"
)


def q(sql):
    return con.execute(sql).fetchall()


TOTAL = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
FRAUD = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
BASE = FRAUD / TOTAL
print(f"base {BASE * 100:.4f}%  (precision>=25% 또는 recall>=25%&lift>=5 = shortcut 후보)\n")


def scan_col(col, min_support=5):
    """컬럼 값별 fraud precision/recall 스캔 + fraud 전용값."""
    hits = []
    rows = q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, "{col}" v FROM j)
        SELECT v, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot FROM dv
        GROUP BY v HAVING count(*) FILTER (WHERE is_fraud='true')>={min_support}""")
    for v, fd, tot in rows:
        prec, recall = fd / tot, fd / FRAUD
        lift = prec / BASE
        if prec >= 0.25 or (recall >= 0.25 and lift >= 5):
            hits.append(
                f"{col}='{str(v)[:24]}'[prec{prec * 100:.0f}% rec{recall * 100:.0f}% {fd}/{tot}]"
            )
    return hits


print("=== A. 라벨인접/미커버 범주형 컬럼 ===")
flagged = []
for col in [
    "semantic_scenario_id",
    "scenario_id",
    "event_type",
    "line_text_family",
    "tax_code",
    "header_text",
    "supporting_doc_type",
    "reversal_type",
    "reversal_reason_code",
    "currency",
    "exchange_rate",
    "user_persona",
    "ip_address",
]:
    flagged += scan_col(col)
print("\n".join(flagged) if flagged else "  깨끗 — 분리값 없음")

print("\n=== B. 거래처(trading_partner) fraud-only 여부 ===")
fo = q("""WITH f AS (SELECT DISTINCT trading_partner FROM j WHERE is_fraud='true' AND trading_partner IS NOT NULL AND trading_partner<>''),
    n AS (SELECT DISTINCT trading_partner FROM j WHERE is_fraud='false' AND trading_partner IS NOT NULL AND trading_partner<>'')
    SELECT (SELECT count(*) FROM f), (SELECT count(*) FROM f WHERE trading_partner NOT IN (SELECT trading_partner FROM n))""")
print(f"  부정 거래처 {fo[0][0]}개 중 부정 전용(정상거래 0건): {fo[0][1]}개")
if fo[0][1]:
    for r in q("""WITH n AS (SELECT DISTINCT trading_partner FROM j WHERE is_fraud='false')
        SELECT trading_partner, count(DISTINCT document_id) FROM j WHERE is_fraud='true'
        AND trading_partner NOT IN (SELECT trading_partner FROM n) GROUP BY 1 ORDER BY 2 DESC LIMIT 10"""):
        print(f"    부정전용 거래처: {r[0]} ({r[1]}docs)")

print("\n=== C. 시간 차원 ===")
print("  시각(hour) 분포 — 부정이 몰린 시간대:")
for (
    r
) in q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, substr(posting_date,12,2) h FROM j)
    SELECT h, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot FROM dv GROUP BY 1
    HAVING count(*) FILTER (WHERE is_fraud='true')>=5
    AND (count(*) FILTER (WHERE is_fraud='true')*1.0/count(*) >= 0.25
         OR (count(*) FILTER (WHERE is_fraud='true')*1.0/{FRAUD} >= 0.25 AND count(*) FILTER (WHERE is_fraud='true')*1.0/count(*)/{BASE} >= 5)) ORDER BY 1"""):
    print(f"    hour={r[0]}: {r[1]}/{r[2]}")
print("  (출력 없으면 깨끗)")
print("  요일/월내일자/lag 평균 비교:")
print(
    "   ",
    q("""WITH dv AS (SELECT DISTINCT document_id, is_fraud, posting_date, document_date FROM j)
    SELECT is_fraud, round(avg(dayofweek(CAST(substr(posting_date,1,10) AS DATE))),2) wd,
           round(avg(day(CAST(substr(posting_date,1,10) AS DATE))),2) dom,
           round(avg(datediff('day', CAST(substr(document_date,1,10) AS DATE), CAST(substr(posting_date,1,10) AS DATE))),3) lag
    FROM dv GROUP BY 1 ORDER BY 1"""),
)
print(
    "  말일(28+) 집중:",
    q("""WITH dv AS (SELECT DISTINCT document_id, is_fraud, day(CAST(substr(posting_date,1,10) AS DATE)) d FROM j)
    SELECT is_fraud, round(count(*) FILTER (WHERE d>=28)*100.0/count(*),1) FROM dv GROUP BY 1 ORDER BY 1"""),
)

print("\n=== D. 금액 분포 ===")
print("  Benford 첫자리 (정상% vs 부정%):")
ben = q("""WITH amt AS (SELECT is_fraud, substr(CAST(CAST(local_amount AS DOUBLE) AS BIGINT)::VARCHAR,1,1) d1
    FROM j WHERE local_amount IS NOT NULL AND local_amount<>'' AND CAST(local_amount AS DOUBLE)>=1)
    SELECT d1, round(count(*) FILTER (WHERE is_fraud='false')*100.0/sum(count(*) FILTER (WHERE is_fraud='false')) OVER (),1),
           round(count(*) FILTER (WHERE is_fraud='true')*100.0/sum(count(*) FILTER (WHERE is_fraud='true')) OVER (),1)
    FROM amt GROUP BY 1 ORDER BY 1""")
print("    " + " | ".join(f"{r[0]}:{r[1]}/{r[2]}" for r in ben))
print("  자릿수 분포 (정상% vs 부정%):")
dig = q("""WITH amt AS (SELECT is_fraud, length(CAST(CAST(local_amount AS DOUBLE) AS BIGINT)::VARCHAR) ln
    FROM j WHERE local_amount IS NOT NULL AND local_amount<>'' AND CAST(local_amount AS DOUBLE)>=1)
    SELECT ln, round(count(*) FILTER (WHERE is_fraud='false')*100.0/sum(count(*) FILTER (WHERE is_fraud='false')) OVER (),1),
           round(count(*) FILTER (WHERE is_fraud='true')*100.0/sum(count(*) FILTER (WHERE is_fraud='true')) OVER (),1)
    FROM amt GROUP BY 1 ORDER BY 1""")
print("    " + " | ".join(f"{r[0]}자리:{r[1]}/{r[2]}" for r in dig))

print("\n=== E. 텍스트 토큰 누수 (line_text 값이 정상에 존재?) ===")
tx = q("""WITH f AS (SELECT DISTINCT line_text FROM j WHERE is_fraud='true' AND line_text IS NOT NULL AND line_text<>''),
    n AS (SELECT DISTINCT line_text FROM j WHERE is_fraud='false')
    SELECT (SELECT count(*) FROM f), (SELECT count(*) FROM f WHERE line_text NOT IN (SELECT line_text FROM n))""")
print(f"  부정 line_text 고유값 {tx[0][0]}개 중 정상에 없는 값: {tx[0][1]}개")
if tx[0][1]:
    for r in q("""WITH n AS (SELECT DISTINCT line_text FROM j WHERE is_fraud='false')
        SELECT line_text, count(*) FROM j WHERE is_fraud='true' AND line_text NOT IN (SELECT line_text FROM n)
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10"""):
        print(f"    부정전용 텍스트: '{str(r[0])[:50]}' ({r[1]}행)")
hx = q("""WITH f AS (SELECT DISTINCT header_text FROM j WHERE is_fraud='true' AND header_text IS NOT NULL AND header_text<>''),
    n AS (SELECT DISTINCT header_text FROM j WHERE is_fraud='false')
    SELECT (SELECT count(*) FROM f), (SELECT count(*) FROM f WHERE header_text NOT IN (SELECT header_text FROM n))""")
print(f"  부정 header_text 고유값 {hx[0][0]}개 중 정상에 없는 값: {hx[0][1]}개")

print("\n=== F. 식별자 패턴 ===")
print(
    "  document_number prefix(앞 9자) 부정전용:",
    q("""WITH f AS (SELECT DISTINCT substr(document_number,1,9) p FROM j WHERE is_fraud='true' AND document_number IS NOT NULL AND document_number<>''),
    n AS (SELECT DISTINCT substr(document_number,1,9) p FROM j WHERE is_fraud='false')
    SELECT count(*) FROM f WHERE p NOT IN (SELECT p FROM n)""")[0][0],
)
print(
    "  document_id 길이 분포 동일?:",
    q("""WITH dv AS (SELECT DISTINCT document_id, is_fraud FROM j)
    SELECT is_fraud, list_sort(array_agg(DISTINCT length(document_id))) FROM dv GROUP BY 1 ORDER BY 1"""),
)
print(
    "  batch_id 부정전용:",
    q("""WITH f AS (SELECT DISTINCT batch_id FROM j WHERE is_fraud='true' AND batch_id IS NOT NULL AND batch_id<>''),
    n AS (SELECT DISTINCT batch_id FROM j WHERE is_fraud='false')
    SELECT count(*) FROM f WHERE batch_id NOT IN (SELECT batch_id FROM n)""")[0][0],
)

print("\n=== G. 다컬럼 조합 (3개 조합 확장) ===")
for combo in [
    ("company_code", "source", "document_type"),
    ("business_process", "fiscal_year", "company_code"),
    ("source", "user_persona", "document_type"),
    ("currency", "company_code", "business_process"),
]:
    c = "||'|'||".join(f'"{x}"' for x in combo)
    rows = q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, {c} v FROM j)
        SELECT v, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot FROM dv GROUP BY v
        HAVING count(*) FILTER (WHERE is_fraud='true')>=10 AND count(*) FILTER (WHERE is_fraud='true')*1.0/count(*)>=0.25
        ORDER BY fd DESC LIMIT 3""")
    print(f"  {'×'.join(combo)}: {[(r[0], f'{r[1]}/{r[2]}') for r in rows] or '깨끗'}")

sys.stdout.flush()

