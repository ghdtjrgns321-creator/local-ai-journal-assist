"""scheme별 분개 실질 점검 — 같은 계정 dr/cr 자기상쇄(경제실질 0) 문서를 색출."""

import duckdb

OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260610_v1_r1e"
con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)


def q(sql):
    return con.execute(sql).fetchall()


# 각 문서의 debit 계정 집합 vs credit 계정 집합이 동일(자기상쇄)인 fraud 문서
print("== 같은 계정에서 dr·cr 동시 발생(자기상쇄 의심) 문서 수 / scheme ==")
print(
    q(
        """
    WITH lines AS (
      SELECT p.scheme_id, j.document_id, j.gl_account,
             sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
      FROM p JOIN j USING(document_id)
      GROUP BY 1,2,3
    ), selfcancel AS (
      SELECT scheme_id, document_id
      FROM lines
      WHERE dr > 0 AND cr > 0          -- 동일 계정에 차·대 동시
      GROUP BY 1,2
    )
    SELECT scheme_id, count(DISTINCT document_id) FROM selfcancel GROUP BY 1 ORDER BY 1
    """
    )
)

print("\n== scheme별 distinct 계정쌍(차변계정 -> 대변계정) 다양성 ==")
print(
    q(
        """
    WITH dr AS (SELECT p.scheme_id, j.document_id, j.gl_account a FROM p JOIN j USING(document_id) WHERE CAST(j.debit_amount AS DOUBLE)>0),
         cr AS (SELECT j.document_id, j.gl_account a FROM j WHERE CAST(j.credit_amount AS DOUBLE)>0)
    SELECT dr.scheme_id, dr.a AS debit_acct, cr.a AS credit_acct, count(DISTINCT dr.document_id) docs
    FROM dr JOIN cr ON dr.document_id=cr.document_id AND dr.a<>cr.a
    GROUP BY 1,2,3 ORDER BY 1,2,3
    """
    )
)

print("\n== delivery_date 채움 비율 (O2C scheme에서 cutoff 시그니처) ==")
print(
    q(
        """SELECT p.scheme_id,
                  count(*) FILTER (WHERE j.delivery_date IS NOT NULL AND j.delivery_date<>'') AS with_deliv,
                  count(*) AS total
           FROM p JOIN (SELECT DISTINCT document_id, delivery_date FROM j) j USING(document_id)
           GROUP BY 1 ORDER BY 1"""
    )
)
