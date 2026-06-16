"""PHASE2 fraud 회계 회귀 + 게이트 사각 검증 (경로 인자형, 재사용).

사용: uv run python tools/scripts/verify_phase2_regression.py <fraud_dir> <base_normal_dir>
게이트(shortcut)가 안 보는 회계 내용 보존 + 라인 구성 타당성 + 2컬럼 조합 shortcut 점검.
"""

import sys

import duckdb

if len(sys.argv) < 3:
    print("usage: verify_phase2_regression.py <fraud_dir> <base_normal_dir>")
    sys.exit(2)
OUT, BASE = sys.argv[1].rstrip("/\\"), sys.argv[2].rstrip("/\\")

con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW base AS SELECT * FROM read_csv('{BASE}/journal_entries.csv', all_varchar=true);
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    CREATE VIEW t AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_truth.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


cols = [r[1] for r in q("PRAGMA table_info('base')")]
cl = ", ".join(f'"{c}"' for c in cols)

print("=== 불변량/무수정 ===")
b = q("SELECT count(DISTINCT document_id) FROM base")[0][0]
o = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
fr = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
print(f"base={b} out={o} diff={o - b} fraud={fr}")
print(
    "base무수정(0이어야):",
    q(f"SELECT count(*) FROM (SELECT {cl} FROM base EXCEPT SELECT {cl} FROM j)")[0][0],
)
print(
    "라벨정합(0/0/0):",
    q(
        "SELECT count(*) FROM (SELECT DISTINCT document_id FROM p EXCEPT SELECT DISTINCT document_id FROM j)"
    )[0][0],
    q(
        "SELECT count(DISTINCT p.document_id) FROM p JOIN j USING(document_id) WHERE j.is_fraud<>'true'"
    )[0][0],
    q(
        "SELECT count(*) FROM (SELECT DISTINCT document_id FROM j WHERE is_fraud='true' EXCEPT SELECT DISTINCT document_id FROM p)"
    )[0][0],
)

print("\n=== 회계 회귀 ===")
print("14 scheme:", q("SELECT count(DISTINCT scheme_id) FROM p")[0][0])
print(
    "자기상쇄:",
    q("""WITH l AS (SELECT j.document_id, j.gl_account, sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
    FROM p JOIN j USING(document_id) GROUP BY 1,2) SELECT count(DISTINCT document_id) FROM l WHERE dr>0 AND cr>0""")[
        0
    ][0],
)
print(
    "부정 불균형:",
    q(
        "SELECT count(*) FROM (SELECT document_id FROM j WHERE is_fraud='true' GROUP BY 1 HAVING abs(sum(CAST(debit_amount AS DOUBLE))-sum(CAST(credit_amount AS DOUBLE)))>0.01)"
    )[0][0],
)

print("\n=== 경제효과 방향 (계정분산 후에도 scheme 메커니즘 유지?) ===")
for r in q("""SELECT p.scheme_id, j.semantic_account_subtype, round(sum(CAST(j.debit_amount AS DOUBLE)-CAST(j.credit_amount AS DOUBLE))) net
    FROM p JOIN j USING(document_id)
    WHERE p.scheme_id IN ('FS01','FS03','FS07','FS14') GROUP BY 1,2 HAVING abs(net)>0 ORDER BY 1,2"""):
    print(f"  {r[0]}: {r[1]} net_debit={r[2]}")

print("\n=== 라인 구성 타당성 (3+라인 부정이 회계적으로 정상인가) ===")
# 같은 계정이 한 문서에서 차/대 양쪽 또는 더미 분할 의심
print(
    "3+라인 부정 문서수:",
    q(
        "WITH lc AS (SELECT document_id, count(*) n FROM j WHERE is_fraud='true' GROUP BY 1) SELECT count(*) FROM lc WHERE n>=3"
    )[0][0],
)
print(
    "동일계정 한문서 중복(분할 의심):",
    q("""WITH dup AS (SELECT document_id, gl_account, count(*) c FROM j WHERE is_fraud='true' GROUP BY 1,2 HAVING count(*)>1)
    SELECT count(DISTINCT document_id) FROM dup""")[0][0],
)
# 3+라인 문서 표본 구조
print("3+라인 부정 표본(계정조합):")
for r in q("""WITH big AS (SELECT document_id FROM j WHERE is_fraud='true' GROUP BY 1 HAVING count(*)>=3 LIMIT 3)
    SELECT j.document_id, j.gl_account, j.debit_amount, j.credit_amount, j.semantic_account_subtype
    FROM j JOIN big USING(document_id) ORDER BY j.document_id, j.line_number"""):
    print(f"    {r[0][:8]} acct={r[1]} dr={r[2]} cr={r[3]} st={r[4]}")

print("\n=== 부작위 금액 파생 유지(FS10/12/13 서로 다른가) ===")
print(
    q(
        "SELECT scheme_id, unrecognized_amount_krw FROM t WHERE CAST(unrecognized_amount_krw AS DOUBLE)>0 ORDER BY scheme_id"
    )
)

print("\n=== 게이트 사각: 2-컬럼 조합 분리력 ===")
# (company_code, fiscal_period) 조합이 부정을 정밀 분리하나
for combo in [("company_code", "fiscal_period"), ("business_process", "company_code")]:
    c1, c2 = combo
    rows = q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, "{c1}"||'|'||"{c2}" v FROM j)
        SELECT v, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot FROM dv GROUP BY v
        HAVING count(*) FILTER (WHERE is_fraud='true')>=10 AND count(*) FILTER (WHERE is_fraud='true')*1.0/count(*)>=0.25
        ORDER BY fd DESC LIMIT 5""")
    print(
        f"  {c1}×{c2} precision>=25%&부정>=10:", [(r[0], f"{r[1]}/{r[2]}") for r in rows] or "없음"
    )

sys.stdout.flush()
