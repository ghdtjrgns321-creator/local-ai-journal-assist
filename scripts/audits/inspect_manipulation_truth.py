"""조작 시나리오 데이터 무결성 검사

manipulated_entry_truth 라벨이 실제 journal_entries 데이터에서
역할에 맞게 조작되어 있는지(실무에서 발생할 법한 패턴인지) 검증한다.

검사 시나리오:
  1) fictitious_entry         - 가공 분개
  2) period_end_adjustment_*  - 기말 조정 조작
  3) embezzlement_concealment - 횡령 은닉
  4) circular_related_party_* - 순환 특수관계자 거래
  5) approval_sod_bypass      - 승인 SoD 우회
  6) unusual_timing_*         - 비정상 타이밍
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

ROOT = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
DATA = ROOT / "data/journal/primary/datasynth_manipulation"
JE = (DATA / "journal_entries.csv").as_posix()
TRUTH = (DATA / "labels/manipulated_entry_truth.csv").as_posix()


def section(title: str) -> None:
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def main() -> None:
    con = duckdb.connect()

    con.execute(
        f"""
        CREATE VIEW je   AS SELECT * FROM read_csv_auto('{JE}', header=True);
        CREATE VIEW truth AS SELECT * FROM read_csv_auto('{TRUTH}', header=True);
        """
    )

    section("0. 라벨 분포 (시나리오 x 연도)")
    print(con.execute(
        """
        SELECT manipulation_scenario,
               fiscal_year,
               COUNT(*) AS doc_cnt
        FROM truth
        GROUP BY 1,2
        ORDER BY 1,2
        """
    ).fetchdf().to_string(index=False))

    # 모든 truth 문서가 실제 journal entries에 존재하는가?
    section("1. truth -> journal join 정합성")
    print(con.execute(
        """
        WITH j AS (SELECT DISTINCT document_id FROM je)
        SELECT COUNT(*) AS truth_docs,
               COUNT(j.document_id) AS matched_in_je,
               COUNT(*) - COUNT(j.document_id) AS missing
        FROM truth t LEFT JOIN j USING(document_id)
        """
    ).fetchdf().to_string(index=False))

    # ---------------------------------------------------------------- #
    section("2. fictitious_entry — 가공 분개 패턴")
    print("(a) document_type / source / business_process 분포")
    print(con.execute(
        """
        SELECT je.document_type, je.source, je.business_process,
               COUNT(DISTINCT je.document_id) AS doc_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='fictitious_entry'
        GROUP BY 1,2,3 ORDER BY doc_cnt DESC LIMIT 20
        """
    ).fetchdf().to_string(index=False))

    print("\n(b) 차대변 균형 / 라인 수 / 금액 분포")
    print(con.execute(
        """
        WITH bal AS (
          SELECT je.document_id,
                 SUM(je.debit_amount)  AS dr,
                 SUM(je.credit_amount) AS cr,
                 COUNT(*)              AS lines,
                 SUM(je.local_amount)  AS amt
          FROM je JOIN truth USING(document_id)
          WHERE truth.manipulation_scenario='fictitious_entry'
          GROUP BY 1
        )
        SELECT COUNT(*) AS docs,
               SUM(CASE WHEN ABS(dr-cr)<1 THEN 1 ELSE 0 END) AS balanced,
               MIN(lines) AS min_lines,
               MAX(lines) AS max_lines,
               AVG(lines)::DECIMAL(8,2) AS avg_lines,
               MIN(amt)::BIGINT AS min_amt,
               MAX(amt)::BIGINT AS max_amt,
               AVG(amt)::BIGINT AS avg_amt
        FROM bal
        """
    ).fetchdf().to_string(index=False))

    print("\n(c) 사용 GL 계정 TOP 15 (fictitious 매출/자산/비용?)")
    print(con.execute(
        """
        SELECT je.gl_account,
               COUNT(*) AS line_cnt,
               SUM(je.debit_amount)::BIGINT  AS sum_dr,
               SUM(je.credit_amount)::BIGINT AS sum_cr
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='fictitious_entry'
        GROUP BY 1 ORDER BY line_cnt DESC LIMIT 15
        """
    ).fetchdf().to_string(index=False))

    print("\n(d) approver / created_by 동일성, 첨부 보유")
    print(con.execute(
        """
        SELECT
          SUM(CASE WHEN je.created_by = je.approved_by THEN 1 ELSE 0 END) AS self_approve,
          SUM(CASE WHEN je.has_attachment THEN 1 ELSE 0 END) AS with_attach,
          COUNT(*) AS line_total
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='fictitious_entry'
        """
    ).fetchdf().to_string(index=False))

    # ---------------------------------------------------------------- #
    section("3. period_end_adjustment_manipulation — 기말 조정 조작")
    print("(a) 월별 분포 (12월 집중 여부)")
    print(con.execute(
        """
        SELECT EXTRACT(MONTH FROM CAST(je.posting_date AS TIMESTAMP)) AS pmonth,
               COUNT(DISTINCT je.document_id) AS doc_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='period_end_adjustment_manipulation'
        GROUP BY 1 ORDER BY 1
        """
    ).fetchdf().to_string(index=False))

    print("\n(b) document_type / source")
    print(con.execute(
        """
        SELECT je.document_type, je.source,
               COUNT(DISTINCT je.document_id) AS doc_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='period_end_adjustment_manipulation'
        GROUP BY 1,2 ORDER BY doc_cnt DESC LIMIT 15
        """
    ).fetchdf().to_string(index=False))

    print("\n(c) 야간/주말/익월 승인 비율")
    print(con.execute(
        """
        WITH d AS (
          SELECT DISTINCT je.document_id,
                 CAST(je.posting_date AS TIMESTAMP)  AS pd,
                 CAST(je.approval_date AS TIMESTAMP) AS ad
          FROM je JOIN truth USING(document_id)
          WHERE truth.manipulation_scenario='period_end_adjustment_manipulation'
        )
        SELECT COUNT(*) AS docs,
               SUM(CASE WHEN EXTRACT(HOUR FROM pd) NOT BETWEEN 8 AND 18 THEN 1 ELSE 0 END) AS off_hours,
               SUM(CASE WHEN EXTRACT(DOW FROM pd) IN (0,6) THEN 1 ELSE 0 END) AS weekend,
               SUM(CASE WHEN ad > pd + INTERVAL 7 DAY THEN 1 ELSE 0 END) AS approval_lag_gt7
        FROM d
        """
    ).fetchdf().to_string(index=False))

    # ---------------------------------------------------------------- #
    section("4. embezzlement_concealment — 횡령 은닉")
    print("(a) 사용 계정 / 거래파트너 / 텍스트 패턴")
    print(con.execute(
        """
        SELECT je.gl_account,
               COUNT(*) AS line_cnt,
               SUM(je.debit_amount)::BIGINT AS sum_dr,
               SUM(je.credit_amount)::BIGINT AS sum_cr
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='embezzlement_concealment'
        GROUP BY 1 ORDER BY line_cnt DESC LIMIT 15
        """
    ).fetchdf().to_string(index=False))

    print("\n(b) trading_partner / line_text 표본")
    print(con.execute(
        """
        SELECT je.trading_partner, je.line_text, je.local_amount
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='embezzlement_concealment'
        LIMIT 15
        """
    ).fetchdf().to_string(index=False))

    print("\n(c) sod_violation / self-approve 비율")
    print(con.execute(
        """
        SELECT
          COUNT(*) AS line_total,
          SUM(CASE WHEN je.sod_violation THEN 1 ELSE 0 END) AS sod_v,
          SUM(CASE WHEN je.created_by = je.approved_by THEN 1 ELSE 0 END) AS self_approve
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='embezzlement_concealment'
        """
    ).fetchdf().to_string(index=False))

    # ---------------------------------------------------------------- #
    section("5. circular_related_party_transaction — 순환 특수관계자")
    print("(a) trading_partner 분포 (P, RP, IC 등)")
    print(con.execute(
        """
        SELECT je.trading_partner,
               COUNT(*) AS line_cnt,
               COUNT(DISTINCT je.document_id) AS doc_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='circular_related_party_transaction'
        GROUP BY 1 ORDER BY line_cnt DESC LIMIT 20
        """
    ).fetchdf().to_string(index=False))

    print("\n(b) 회사간 분포 / business_process")
    print(con.execute(
        """
        SELECT je.company_code, je.business_process,
               COUNT(DISTINCT je.document_id) AS doc_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='circular_related_party_transaction'
        GROUP BY 1,2 ORDER BY doc_cnt DESC LIMIT 15
        """
    ).fetchdf().to_string(index=False))

    # ---------------------------------------------------------------- #
    section("6. approval_sod_bypass — SoD 우회")
    print("(a) sod_violation 컬럼 / 자기승인 비율")
    print(con.execute(
        """
        SELECT
          COUNT(DISTINCT je.document_id) AS docs,
          SUM(CASE WHEN je.sod_violation THEN 1 ELSE 0 END) AS sod_v_lines,
          SUM(CASE WHEN je.created_by = je.approved_by THEN 1 ELSE 0 END) AS self_approve_lines,
          COUNT(*) AS line_total
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='approval_sod_bypass'
        """
    ).fetchdf().to_string(index=False))

    print("\n(b) sod_conflict_type 종류")
    print(con.execute(
        """
        SELECT je.sod_conflict_type, COUNT(*) AS line_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='approval_sod_bypass'
        GROUP BY 1 ORDER BY line_cnt DESC
        """
    ).fetchdf().to_string(index=False))

    print("\n(c) 금액 / approver / created_by 표본")
    print(con.execute(
        """
        SELECT DISTINCT je.document_id, je.created_by, je.approved_by,
               je.sod_violation, je.sod_conflict_type,
               (SELECT SUM(local_amount) FROM je je2 WHERE je2.document_id=je.document_id) AS amt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='approval_sod_bypass'
        LIMIT 15
        """
    ).fetchdf().to_string(index=False))

    # ---------------------------------------------------------------- #
    section("7. unusual_timing_manipulation — 비정상 타이밍")
    print("(a) 시간대 분포")
    print(con.execute(
        """
        SELECT EXTRACT(HOUR FROM CAST(je.posting_date AS TIMESTAMP)) AS phour,
               COUNT(DISTINCT je.document_id) AS doc_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='unusual_timing_manipulation'
        GROUP BY 1 ORDER BY 1
        """
    ).fetchdf().to_string(index=False))

    print("\n(b) 요일 분포 (0=일,6=토)")
    print(con.execute(
        """
        SELECT EXTRACT(DOW FROM CAST(je.posting_date AS TIMESTAMP)) AS dow,
               COUNT(DISTINCT je.document_id) AS doc_cnt
        FROM je JOIN truth USING(document_id)
        WHERE truth.manipulation_scenario='unusual_timing_manipulation'
        GROUP BY 1 ORDER BY 1
        """
    ).fetchdf().to_string(index=False))

    # ---------------------------------------------------------------- #
    section("8. 시나리오별 평균 금액 / persona / SoD 위반")
    print(con.execute(
        """
        SELECT t.manipulation_scenario,
               COUNT(DISTINCT t.document_id)             AS docs,
               AVG(t.line_amount)::BIGINT                 AS avg_doc_amt,
               COUNT(DISTINCT t.user_persona)             AS distinct_persona,
               STRING_AGG(DISTINCT t.user_persona, ', ')  AS personas
        FROM truth t
        GROUP BY 1 ORDER BY docs DESC
        """
    ).fetchdf().to_string(index=False))

    section("DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED: {exc!r}", file=sys.stderr)
        raise
