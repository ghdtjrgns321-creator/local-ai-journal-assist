"""Tier 2: 정량 벤치마크 — 한국 중견 제조업 실무 기대값 비교."""
from __future__ import annotations

import time

import duckdb

from ..models import CheckResult


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _in_range(val: float, lo: float, hi: float) -> str:
    """범위 내면 PASS, 아니면 WARNING."""
    return "PASS" if lo <= val <= hi else "WARNING"


def r2_01_doc_total_median(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-01: 전표 총액 중앙값 (50만~300만원)."""
    start = _timer()
    med = con.execute("""
        SELECT MEDIAN(doc_total) FROM (
            SELECT document_id, SUM(CAST(debit_amount AS DOUBLE)) AS doc_total
            FROM je GROUP BY document_id
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="R2-01", tier=2,
        name="전표 총액 중앙값",
        status=_in_range(med, 500_000, 3_000_000),
        expected="50만~300만원",
        actual=f"{med:,.0f}원",
        elapsed_ms=_elapsed(start),
    )


def r2_02_doc_total_mean(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-02: 전표 총액 평균 (1,000만~8,000만원)."""
    start = _timer()
    avg = con.execute("""
        SELECT AVG(doc_total) FROM (
            SELECT document_id, SUM(CAST(debit_amount AS DOUBLE)) AS doc_total
            FROM je GROUP BY document_id
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="R2-02", tier=2,
        name="전표 총액 평균",
        status=_in_range(avg, 10_000_000, 80_000_000),
        expected="1,000만~8,000만원",
        actual=f"{avg:,.0f}원",
        elapsed_ms=_elapsed(start),
    )


def r2_03_lines_per_doc(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-03: 전표당 평균 라인 수 (2~5 정상, 5~15 경고)."""
    start = _timer()
    avg = con.execute("""
        SELECT AVG(line_cnt) FROM (
            SELECT document_id, COUNT(*) AS line_cnt
            FROM je GROUP BY document_id
        )
    """).fetchone()[0]
    if 2 <= avg <= 5:
        status = "PASS"
    elif avg <= 15:
        status = "WARNING"
    else:
        status = "FAIL"
    return CheckResult(
        check_id="R2-03", tier=2,
        name="전표당 평균 라인 수",
        status=status,
        expected="2~5: PASS, 5~15: WARNING",
        actual=f"{avg:.1f}",
        elapsed_ms=_elapsed(start),
    )


def r2_04_dec_spike(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-04: 12월/평월 배수 (≥2.5x)."""
    start = _timer()
    rows = con.execute("""
        SELECT EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) AS m,
               COUNT(DISTINCT document_id) AS cnt
        FROM je
        GROUP BY m ORDER BY m
    """).fetchall()
    monthly = {int(r[0]): r[1] for r in rows}
    avg_month = sum(monthly.values()) / len(monthly) if monthly else 1
    dec = monthly.get(12, 0)
    ratio = dec / avg_month if avg_month > 0 else 0
    return CheckResult(
        check_id="R2-04", tier=2,
        name="12월/평월 배수",
        status="PASS" if ratio >= 2.5 else "FAIL",
        expected=">=2.5x",
        actual=f"{ratio:.2f}x",
        elapsed_ms=_elapsed(start),
    )


def r2_05_weekend_ratio(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-05: 주말 전표 비율 (3~20%)."""
    start = _timer()
    total, weekend = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE
                WHEN EXTRACT(DOW FROM CAST(posting_date AS TIMESTAMP)) IN (0, 6)
                THEN document_id END)
        FROM je
    """).fetchone()
    pct = weekend / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-05", tier=2,
        name="주말 전표 비율",
        status=_in_range(pct, 3, 20),
        expected="3~20%",
        actual=f"{pct:.1f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_06_late_night_ratio(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-06: 심야(22-06) 전표 비율 (<5%)."""
    start = _timer()
    total, late = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE
                WHEN EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) >= 22
                  OR EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) < 6
                THEN document_id END)
        FROM je
    """).fetchone()
    pct = late / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-06", tier=2,
        name="심야(22-06) 비율",
        status="PASS" if pct < 5 else "WARNING",
        expected="<5%",
        actual=f"{pct:.2f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_07_fraud_ratio(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-07: fraud 비율 (0.5~5%)."""
    start = _timer()
    total, fraud = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE WHEN is_fraud = 'true' THEN document_id END)
        FROM je
    """).fetchone()
    pct = fraud / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-07", tier=2,
        name="fraud 비율",
        status=_in_range(pct, 0.5, 5),
        expected="0.5~5%",
        actual=f"{pct:.2f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_08_fraud_cv(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-08: 월별 fraud율 변동계수 (>0.05)."""
    start = _timer()
    rows = con.execute("""
        SELECT
            EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) AS m,
            COUNT(DISTINCT CASE WHEN is_fraud='true' THEN document_id END) * 1.0
                / COUNT(DISTINCT document_id) AS rate
        FROM je GROUP BY m
    """).fetchall()
    rates = [r[1] for r in rows]
    import statistics
    mean_r = statistics.mean(rates) if rates else 0
    std_r = statistics.stdev(rates) if len(rates) > 1 else 0
    cv = std_r / mean_r if mean_r > 0 else 0
    return CheckResult(
        check_id="R2-08", tier=2,
        name="fraud CV (월별)",
        status="PASS" if cv > 0.05 else "WARNING",
        expected=">0.05",
        actual=f"{cv:.3f}",
        elapsed_ms=_elapsed(start),
    )


def r2_09_sod_ratio(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-09: SoD 위반률 (≤3%)."""
    start = _timer()
    total, sod = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE WHEN sod_violation = 'true' THEN document_id END)
        FROM je
    """).fetchone()
    pct = sod / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-09", tier=2,
        name="SoD 위반률",
        status="PASS" if pct <= 3 else "WARNING",
        expected="<=3%",
        actual=f"{pct:.2f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_10_balance(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-10: 정상 전표 차대변 불균형 = 0건."""
    start = _timer()
    # Why: 비정상(fraud/anomaly) 전표의 불균형은 의도된 것이므로 제외
    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN ABS(d - c) > 1 THEN 1 ELSE 0 END) AS unbal_all,
            SUM(CASE WHEN ABS(d - c) > 1
                      AND is_fraud != 'true' AND is_anomaly != 'true'
                     THEN 1 ELSE 0 END) AS unbal_normal
        FROM (
            SELECT document_id,
                   SUM(CAST(debit_amount AS DOUBLE)) AS d,
                   SUM(CAST(credit_amount AS DOUBLE)) AS c,
                   MAX(is_fraud) AS is_fraud,
                   MAX(is_anomaly) AS is_anomaly
            FROM je GROUP BY document_id
        )
    """).fetchone()
    total, unbal_all, unbal_normal = row
    return CheckResult(
        check_id="R2-10", tier=2,
        name="정상전표 차대변 불균형",
        status="PASS" if unbal_normal == 0 else "FAIL",
        expected="정상전표 불균형 0건",
        actual=f"정상 {unbal_normal:,}건, 비정상 {unbal_all - unbal_normal:,}건 (전체 {unbal_all:,}건)",
        elapsed_ms=_elapsed(start),
    )


def r2_11_round_number(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-11: 만원 단위 round number 비율 (15~35% 정상, 10~40% 경고)."""
    start = _timer()
    total, round_cnt = con.execute("""
        SELECT COUNT(*), SUM(CASE WHEN amt % 10000 = 0 THEN 1 ELSE 0 END)
        FROM (
            SELECT CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END AS amt
            FROM je
            WHERE CAST(debit_amount AS DOUBLE) > 0
               OR CAST(credit_amount AS DOUBLE) > 0
        )
    """).fetchone()
    pct = round_cnt / total * 100 if total > 0 else 0
    if 15 <= pct <= 35:
        status = "PASS"
    elif 10 <= pct <= 40:
        status = "WARNING"
    else:
        status = "FAIL"
    return CheckResult(
        check_id="R2-11", tier=2,
        name="round number(만원) 비율",
        status=status,
        expected="15~35%: PASS, 10~40%: WARNING",
        actual=f"{pct:.1f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_12_trillion_check(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-12: 1조원 초과 전표 = 0건."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id
            FROM je
            GROUP BY document_id
            HAVING SUM(CAST(debit_amount AS DOUBLE)) > 1e12
        )
    """).fetchone()[0]
    return CheckResult(
        check_id="R2-12", tier=2,
        name="1조원 초과 전표",
        status="PASS" if cnt == 0 else "FAIL",
        expected="0건",
        actual=f"{cnt:,}건",
        elapsed_ms=_elapsed(start),
    )


def r2_13_line_amount_median(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-13: 라인 레벨 금액 중앙값 ≈ 전표 중앙값 / 평균 라인 수."""
    start = _timer()
    # Why: 전표 총액이 LogNormal이고 라인으로 분할되므로
    #      기대 라인 중앙값 ≈ 전표 중앙값 / 평균 라인 수
    row = con.execute("""
        SELECT
            MEDIAN(amt) AS line_med,
            (SELECT MEDIAN(doc_total) FROM (
                SELECT SUM(CAST(debit_amount AS DOUBLE)) AS doc_total
                FROM je GROUP BY document_id
            )) AS doc_med,
            (SELECT AVG(cnt) FROM (
                SELECT COUNT(*)::DOUBLE AS cnt FROM je GROUP BY document_id
            )) AS avg_lines
        FROM (
            SELECT CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END AS amt
            FROM je
            WHERE CAST(debit_amount AS DOUBLE) > 0
               OR CAST(credit_amount AS DOUBLE) > 0
        )
    """).fetchone()
    line_med, doc_med, avg_lines = row
    expected = doc_med / avg_lines if avg_lines > 0 else 0
    ratio = line_med / expected if expected > 0 else 0
    if 0.3 <= ratio <= 3.0:
        status = "PASS"
    elif 0.1 <= ratio <= 5.0:
        status = "WARNING"
    else:
        status = "FAIL"
    return CheckResult(
        check_id="R2-13", tier=2,
        name="라인 금액 중앙값 (전표/라인수 기준)",
        status=status,
        expected=f"~{expected:,.0f}원 (전표{doc_med:,.0f}/라인{avg_lines:.1f}), 0.3~3x: PASS",
        actual=f"{line_med:,.0f}원 ({ratio:.2f}x)",
        elapsed_ms=_elapsed(start),
    )


def r2_14_line_amount_mean(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-14: 라인 레벨 금액 평균 (LogNormal(14,2.5) 기대 ~2,900만원)."""
    start = _timer()
    import math
    # Why: LogNormal mean = exp(mu + sigma^2/2) = exp(14 + 3.125) ≈ 27,372,667
    expected_mean = math.exp(14.0 + 2.5**2 / 2)
    avg = con.execute("""
        SELECT AVG(amt) FROM (
            SELECT CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END AS amt
            FROM je
            WHERE CAST(debit_amount AS DOUBLE) > 0
               OR CAST(credit_amount AS DOUBLE) > 0
        )
    """).fetchone()[0]
    ratio = avg / expected_mean if expected_mean > 0 else 0
    if 0.5 <= ratio <= 2.0:
        status = "PASS"
    elif 0.2 <= ratio <= 3.0:
        status = "WARNING"
    else:
        status = "FAIL"
    return CheckResult(
        check_id="R2-14", tier=2,
        name="라인 레벨 금액 평균",
        status=status,
        expected=f"~{expected_mean:,.0f}원 (0.5~2x: PASS)",
        actual=f"{avg:,.0f}원 ({ratio:.2f}x)",
        elapsed_ms=_elapsed(start),
    )


def r2_15_nice_number(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-15: 천원 단위 nice number 비율 (10~25% 정상, 5~40% 경고)."""
    start = _timer()
    total, nice_cnt = con.execute("""
        SELECT COUNT(*), SUM(CASE WHEN amt % 1000 = 0 THEN 1 ELSE 0 END)
        FROM (
            SELECT CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END AS amt
            FROM je
            WHERE CAST(debit_amount AS DOUBLE) > 0
               OR CAST(credit_amount AS DOUBLE) > 0
        )
    """).fetchone()
    pct = nice_cnt / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-15", tier=2,
        name="nice number(천원) 비율",
        status="PASS" if 10 <= pct <= 25 else ("WARNING" if 5 <= pct <= 40 else "FAIL"),
        expected="10~25%: PASS, 5~40%: WARNING",
        actual=f"{pct:.1f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_16_yearend_daily(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-16: 기말(12/25~31) vs 비기말 일평균 배수 (>=2x)."""
    start = _timer()
    row = con.execute("""
        SELECT
            COUNT(DISTINCT CASE
                WHEN EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) = 12
                 AND EXTRACT(DAY FROM CAST(posting_date AS TIMESTAMP)) >= 25
                THEN document_id END) * 1.0 / 7 AS ye_daily,
            COUNT(DISTINCT CASE
                WHEN NOT (EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) = 12
                     AND EXTRACT(DAY FROM CAST(posting_date AS TIMESTAMP)) >= 25)
                THEN document_id END) * 1.0 / 358 AS non_ye_daily
        FROM je
    """).fetchone()
    ye, non_ye = row[0] or 0, row[1] or 0
    ratio = ye / non_ye if non_ye > 0 else 0
    return CheckResult(
        check_id="R2-16", tier=2,
        name="기말/비기말 일평균 배수",
        status="PASS" if ratio >= 2 else "WARNING",
        expected=">=2x",
        actual=f"{ratio:.2f}x (기말 {ye:.0f}/일, 비기말 {non_ye:.0f}/일)",
        elapsed_ms=_elapsed(start),
    )


def r2_17_company_distribution(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-15: 회사별 전표 비율 (C001이 50%+, C002/C003이 각 10%+)."""
    start = _timer()
    rows = con.execute("""
        SELECT company_code,
               COUNT(DISTINCT document_id) AS cnt
        FROM je GROUP BY company_code ORDER BY company_code
    """).fetchall()
    total = sum(r[1] for r in rows)
    dist = {r[0]: r[1] / total * 100 for r in rows}
    c001 = dist.get("C001", 0)
    c002 = dist.get("C002", 0)
    c003 = dist.get("C003", 0)
    ok = c001 >= 50 and c002 >= 10 and c003 >= 10
    detail_str = ", ".join(f"{k}={v:.1f}%" for k, v in dist.items())
    return CheckResult(
        check_id="R2-17", tier=2,
        name="회사별 전표 비율",
        status="PASS" if ok else "WARNING",
        expected="C001>=50%, C002/C003>=10%",
        actual=detail_str,
        elapsed_ms=_elapsed(start),
    )


def r2_18_process_distribution(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-16: 프로세스별 전표 비율 (R2R/O2C/P2P 각 10%+)."""
    start = _timer()
    rows = con.execute("""
        SELECT business_process, COUNT(DISTINCT document_id) AS cnt
        FROM je GROUP BY business_process ORDER BY cnt DESC
    """).fetchall()
    total = sum(r[1] for r in rows)
    dist = {r[0]: r[1] / total * 100 for r in rows}
    major = all(dist.get(p, 0) >= 10 for p in ["R2R", "O2C", "P2P"])
    detail_str = ", ".join(f"{k}={v:.1f}%" for k, v in dist.items())
    return CheckResult(
        check_id="R2-18", tier=2,
        name="프로세스별 비율",
        status="PASS" if major else "WARNING",
        expected="R2R/O2C/P2P 각 >=10%",
        actual=detail_str,
        elapsed_ms=_elapsed(start),
    )


def r2_19_persona_distribution(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-17: user_persona별 비율 (automated>=50%, 사람 합계>=10%)."""
    start = _timer()
    rows = con.execute("""
        SELECT user_persona, COUNT(DISTINCT document_id) AS cnt
        FROM je GROUP BY user_persona ORDER BY cnt DESC
    """).fetchall()
    total = sum(r[1] for r in rows)
    dist = {r[0]: r[1] / total * 100 for r in rows}
    auto = dist.get("automated_system", 0)
    human = 100 - auto
    detail_str = ", ".join(f"{k}={v:.1f}%" for k, v in dist.items())
    return CheckResult(
        check_id="R2-19", tier=2,
        name="user_persona별 비율",
        status="PASS" if auto >= 50 and human >= 10 else "WARNING",
        expected="automated>=50%, 사람>=10%",
        actual=detail_str,
        elapsed_ms=_elapsed(start),
    )


def r2_20_source_distribution(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-18: source별 비율 (automated/manual 각 10%+)."""
    start = _timer()
    rows = con.execute("""
        SELECT source, COUNT(DISTINCT document_id) AS cnt
        FROM je GROUP BY source ORDER BY cnt DESC
    """).fetchall()
    total = sum(r[1] for r in rows)
    dist = {r[0]: r[1] / total * 100 for r in rows}
    ok = dist.get("automated", 0) >= 10 and dist.get("manual", 0) >= 10
    detail_str = ", ".join(f"{k}={v:.1f}%" for k, v in dist.items())
    return CheckResult(
        check_id="R2-20", tier=2,
        name="source별 비율",
        status="PASS" if ok else "WARNING",
        expected="automated/manual 각 >=10%",
        actual=detail_str,
        elapsed_ms=_elapsed(start),
    )


def r2_21_anomaly_ratio(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-19: anomaly 비율 (5~30%)."""
    start = _timer()
    total, anom = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE WHEN is_anomaly = 'true' THEN document_id END)
        FROM je
    """).fetchone()
    pct = anom / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-21", tier=2,
        name="anomaly 비율",
        status=_in_range(pct, 5, 30),
        expected="5~30%",
        actual=f"{pct:.2f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_22_fraud_type_diversity(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-20: fraud_type 다양성 (>=5종)."""
    start = _timer()
    rows = con.execute("""
        SELECT fraud_type, COUNT(DISTINCT document_id) AS cnt
        FROM je
        WHERE is_fraud = 'true'
          AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) != ''
          AND CAST(fraud_type AS VARCHAR) != 'nan'
        GROUP BY fraud_type ORDER BY cnt DESC
    """).fetchall()
    n_types = len(rows)
    detail_str = ", ".join(f"{r[0]}={r[1]}" for r in rows[:10])
    return CheckResult(
        check_id="R2-22", tier=2,
        name="fraud_type 다양성",
        status="PASS" if n_types >= 5 else "WARNING",
        expected=">=5종",
        actual=f"{n_types}종 ({detail_str})",
        elapsed_ms=_elapsed(start),
    )


def r2_23_anomaly_type_diversity(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-21: anomaly_type 다양성 (>=5종)."""
    start = _timer()
    rows = con.execute("""
        SELECT anomaly_type, COUNT(DISTINCT document_id) AS cnt
        FROM je
        WHERE is_anomaly = 'true'
          AND anomaly_type IS NOT NULL
          AND CAST(anomaly_type AS VARCHAR) != ''
          AND CAST(anomaly_type AS VARCHAR) != 'nan'
        GROUP BY anomaly_type ORDER BY cnt DESC
    """).fetchall()
    n_types = len(rows)
    detail_str = ", ".join(f"{r[0]}={r[1]}" for r in rows[:10])
    return CheckResult(
        check_id="R2-23", tier=2,
        name="anomaly_type 다양성",
        status="PASS" if n_types >= 5 else "WARNING",
        expected=">=5종",
        actual=f"{n_types}종 ({detail_str})",
        elapsed_ms=_elapsed(start),
    )


def r2_24_approver_concentration(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-22: 승인자 상위 1명 편중도 (<10%)."""
    start = _timer()
    row = con.execute("""
        SELECT
            MAX(cnt) * 100.0 / SUM(cnt) AS top1_pct
        FROM (
            SELECT approved_by, COUNT(DISTINCT document_id) AS cnt
            FROM je
            WHERE approved_by IS NOT NULL
              AND CAST(approved_by AS VARCHAR) != ''
              AND CAST(approved_by AS VARCHAR) != 'nan'
            GROUP BY approved_by
        )
    """).fetchone()
    pct = row[0] or 0
    return CheckResult(
        check_id="R2-24", tier=2,
        name="승인자 상위1명 편중도",
        status="PASS" if pct < 10 else "WARNING",
        expected="<10%",
        actual=f"{pct:.2f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_25_intraday_distribution(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-23: 시간대별 분포 — 업무시간(9-18) 비율 (>=50%)."""
    start = _timer()
    total, biz_hour = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE
                WHEN EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) >= 9
                 AND EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) < 18
                THEN document_id END)
        FROM je
    """).fetchone()
    pct = biz_hour / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-25", tier=2,
        name="업무시간(9-18) 비율",
        status="PASS" if pct >= 50 else "WARNING",
        expected=">=50%",
        actual=f"{pct:.1f}%",
        elapsed_ms=_elapsed(start),
    )


def r2_26_dow_distribution(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-24: 요일별 분포 — 월요일 편중도 확인."""
    start = _timer()
    rows = con.execute("""
        SELECT EXTRACT(DOW FROM CAST(posting_date AS TIMESTAMP)) AS dow,
               COUNT(DISTINCT document_id) AS cnt
        FROM je GROUP BY dow ORDER BY dow
    """).fetchall()
    total = sum(r[1] for r in rows)
    dist = {int(r[0]): r[1] / total * 100 for r in rows}
    dow_names = {0: "일", 1: "월", 2: "화", 3: "수", 4: "목", 5: "금", 6: "토"}
    detail_str = ", ".join(f"{dow_names.get(d,'?')}={p:.1f}%" for d, p in sorted(dist.items()))
    max_pct = max(dist.values()) if dist else 0
    return CheckResult(
        check_id="R2-26", tier=2,
        name="요일별 분포 (최대 편중)",
        status="PASS" if max_pct < 40 else "WARNING",
        expected="단일 요일 <40%",
        actual=detail_str,
        elapsed_ms=_elapsed(start),
    )


def r2_27_gl_category_distribution(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-25: GL 대분류별 비율 (자산/부채/비용 각 10%+)."""
    start = _timer()
    rows = con.execute("""
        SELECT
            CASE WHEN gl_account IS NULL OR CAST(gl_account AS VARCHAR) = '' THEN 'NaN'
                 WHEN CAST(gl_account AS VARCHAR)[1] = '1' THEN '자산'
                 WHEN CAST(gl_account AS VARCHAR)[1] = '2' THEN '부채'
                 WHEN CAST(gl_account AS VARCHAR)[1] = '3' THEN '자본'
                 WHEN CAST(gl_account AS VARCHAR)[1] = '4' THEN '수익'
                 WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '비용'
                 ELSE '기타' END AS cat,
            COUNT(*) AS cnt
        FROM je GROUP BY cat ORDER BY cnt DESC
    """).fetchall()
    total = sum(r[1] for r in rows)
    dist = {r[0]: r[1] / total * 100 for r in rows}
    ok = all(dist.get(c, 0) >= 10 for c in ["자산", "부채", "비용"])
    detail_str = ", ".join(f"{k}={v:.1f}%" for k, v in dist.items())
    return CheckResult(
        check_id="R2-27", tier=2,
        name="GL 대분류별 비율",
        status="PASS" if ok else "WARNING",
        expected="자산/부채/비용 각 >=10%",
        actual=detail_str,
        elapsed_ms=_elapsed(start),
    )


def r2_28_self_approval(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R2-26: 자기승인 비율 (<3%)."""
    start = _timer()
    total, self_appr = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE
                WHEN created_by = approved_by
                 AND created_by IS NOT NULL
                 AND approved_by IS NOT NULL
                THEN document_id END)
        FROM je
    """).fetchone()
    pct = self_appr / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R2-28", tier=2,
        name="자기승인 비율",
        status="PASS" if pct < 3 else "WARNING",
        expected="<3%",
        actual=f"{self_appr:,}/{total:,} ({pct:.2f}%)",
        elapsed_ms=_elapsed(start),
    )


def run_tier2(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 2 전체 실행."""
    return [
        r2_01_doc_total_median(con),
        r2_02_doc_total_mean(con),
        r2_03_lines_per_doc(con),
        r2_04_dec_spike(con),
        r2_05_weekend_ratio(con),
        r2_06_late_night_ratio(con),
        r2_07_fraud_ratio(con),
        r2_08_fraud_cv(con),
        r2_09_sod_ratio(con),
        r2_10_balance(con),
        r2_11_round_number(con),
        r2_12_trillion_check(con),
        r2_13_line_amount_median(con),
        r2_14_line_amount_mean(con),
        r2_15_nice_number(con),
        r2_16_yearend_daily(con),
        r2_17_company_distribution(con),
        r2_18_process_distribution(con),
        r2_19_persona_distribution(con),
        r2_20_source_distribution(con),
        r2_21_anomaly_ratio(con),
        r2_22_fraud_type_diversity(con),
        r2_23_anomaly_type_diversity(con),
        r2_24_approver_concentration(con),
        r2_25_intraday_distribution(con),
        r2_26_dow_distribution(con),
        r2_27_gl_category_distribution(con),
        r2_28_self_approval(con),
    ]
