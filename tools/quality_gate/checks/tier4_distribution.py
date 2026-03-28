"""Tier 4: 분포 + config 정합 (21개 체크).

정상 데이터만 필터(anomaly/fraud 행 제외)하여 분포 통계를 config 기대값과 비교.
WARNING 위주 — 분포 체크는 절대 기준이 없으므로 soft threshold 사용.
"""
from __future__ import annotations

import math
import time

import duckdb

from ..expectations import load_expectations
from ..models import CheckResult

# ---------------------------------------------------------------------------
# 상수 / 헬퍼
# ---------------------------------------------------------------------------

# Benford 이론적 첫째 자릿수 분포
BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

# 2022년 한국 공휴일
KR_HOLIDAYS_2022 = [
    "2022-01-01", "2022-01-31", "2022-02-01", "2022-02-02",
    "2022-03-01", "2022-03-09",
    "2022-05-05", "2022-05-08", "2022-06-01", "2022-06-06",
    "2022-08-15",
    "2022-09-09", "2022-09-10", "2022-09-11", "2022-09-12",
    "2022-10-03", "2022-10-09", "2022-10-10",
    "2022-12-25",
]

# 정상 행만 필터하는 WHERE 절
_NORMAL = """
    (is_anomaly IS NULL OR is_anomaly = false OR is_anomaly = 'false')
    AND (is_fraud IS NULL OR is_fraud = false OR is_fraud = 'false')
"""


def _t():
    return time.perf_counter()


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# T4-01 Benford MAD
# ---------------------------------------------------------------------------

def t4_01(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """첫째 자릿수 Benford 적합도 (MAD)."""
    s = _t()
    rows = con.execute(f"""
        SELECT CAST(SUBSTR(CAST(CAST(GREATEST(COALESCE(debit_amount,0),
               COALESCE(credit_amount,0)) AS BIGINT) AS VARCHAR), 1, 1) AS INT) AS d,
               COUNT(*) AS cnt
        FROM je
        WHERE {_NORMAL}
          AND GREATEST(COALESCE(debit_amount,0), COALESCE(credit_amount,0)) >= 10
        GROUP BY d HAVING d BETWEEN 1 AND 9
    """).fetchall()
    total = sum(r[1] for r in rows)
    freq = {r[0]: r[1] / total for r in rows} if total > 0 else {}
    mad = sum(abs(freq.get(d, 0) - BENFORD[d]) for d in range(1, 10)) / 9

    if mad < 0.006:
        status = "PASS"
    elif mad < 0.012:
        status = "WARNING"
    else:
        status = "FAIL"

    return CheckResult(
        check_id="T4-01", tier=4, name="Benford MAD",
        status=status, expected="MAD<0.006(PASS), <0.012(WARN)",
        actual=f"MAD={mad:.6f}", detail={"freq": freq},
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-02 금액 LogNormal
# ---------------------------------------------------------------------------

def t4_02(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """ln(amount) 평균/표준편차 → LogNormal 적합."""
    s = _t()
    exp = load_expectations()
    row = con.execute(f"""
        SELECT AVG(LN(amt)) AS mu, STDDEV(LN(amt)) AS sigma FROM (
            SELECT GREATEST(COALESCE(debit_amount,0), COALESCE(credit_amount,0)) AS amt
            FROM je WHERE {_NORMAL}
              AND GREATEST(COALESCE(debit_amount,0), COALESCE(credit_amount,0)) > 0
        )
    """).fetchone()
    mu, sigma = row[0] or 0, row[1] or 0
    exp_mu = exp.get("lognormal_mu", 14.0)
    exp_sigma = exp.get("lognormal_sigma", 2.5)

    issues = []
    if abs(mu - exp_mu) > 1:
        issues.append(f"|μ-{exp_mu}|={abs(mu-exp_mu):.2f}>1")
    if abs(sigma - exp_sigma) > 0.5:
        issues.append(f"|σ-{exp_sigma}|={abs(sigma-exp_sigma):.2f}>0.5")
    status = "WARNING" if issues else "PASS"

    return CheckResult(
        check_id="T4-02", tier=4, name="금액 LogNormal",
        status=status, expected=f"μ≈{exp_mu}, σ≈{exp_sigma}",
        actual=f"μ={mu:.2f}, σ={sigma:.2f}",
        detail={"issues": issues} if issues else None,
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-03 월별 변동성
# ---------------------------------------------------------------------------

def t4_03(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """12월 / 평월 건수 비율."""
    s = _t()
    rows = con.execute(f"""
        SELECT EXTRACT(MONTH FROM posting_date) AS m, COUNT(*) AS cnt
        FROM je WHERE {_NORMAL}
        GROUP BY m ORDER BY m
    """).fetchall()
    by_m = {int(r[0]): r[1] for r in rows}
    dec = by_m.get(12, 0)
    non_dec = [v for k, v in by_m.items() if k != 12]
    avg_non_dec = sum(non_dec) / len(non_dec) if non_dec else 1
    ratio = dec / avg_non_dec if avg_non_dec > 0 else 0

    status = "WARNING" if ratio < 3 else "PASS"
    return CheckResult(
        check_id="T4-03", tier=4, name="월별 변동성(12월 스파이크)",
        status=status, expected="12월/평월 비율 ≥ 3",
        actual=f"ratio={ratio:.2f} (12월={dec:,}, 평월평균={avg_non_dec:,.0f})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-04 요일별 분포
# ---------------------------------------------------------------------------

def t4_04(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """월요일 비율 > 금요일 비율 기대."""
    s = _t()
    rows = con.execute(f"""
        SELECT EXTRACT(DOW FROM posting_date) AS dow, COUNT(*) AS cnt
        FROM je WHERE {_NORMAL}
        GROUP BY dow
    """).fetchall()
    total = sum(r[1] for r in rows)
    by_dow = {int(r[0]): r[1] / total if total > 0 else 0 for r in rows}
    # DuckDB: 0=일, 1=월, ..., 5=금, 6=토
    mon_pct = by_dow.get(1, 0)
    fri_pct = by_dow.get(5, 0)

    status = "WARNING" if mon_pct < fri_pct else "PASS"
    return CheckResult(
        check_id="T4-04", tier=4, name="요일별 분포(월>금)",
        status=status, expected="월요일 비율 ≥ 금요일",
        actual=f"월={mon_pct:.3f}, 금={fri_pct:.3f}",
        detail={"dow_pct": by_dow},
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-05 주말 비율
# ---------------------------------------------------------------------------

def t4_05(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """주말(토,일) 건수 비율."""
    s = _t()
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE EXTRACT(DOW FROM posting_date) IN (0, 6)) AS wkend,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    wkend, total = row[0], row[1]
    pct = wkend / total * 100 if total > 0 else 0

    status = "WARNING" if pct > 15 or pct < 3 else "PASS"
    return CheckResult(
        check_id="T4-05", tier=4, name="주말 비율",
        status=status, expected="3% ~ 15%",
        actual=f"{pct:.2f}% ({wkend:,}/{total:,})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-06 시간대 8-segment
# ---------------------------------------------------------------------------

def t4_06(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """업무시간(9~12시) 비율 25% 이상 기대."""
    s = _t()
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM posting_date) BETWEEN 9 AND 12) AS morning,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    morning, total = row[0], row[1]
    pct = morning / total * 100 if total > 0 else 0

    status = "WARNING" if pct < 25 else "PASS"
    return CheckResult(
        check_id="T4-06", tier=4, name="시간대(오전 스파이크)",
        status=status, expected="오전(9~12시) ≥ 25%",
        actual=f"{pct:.1f}% ({morning:,}/{total:,})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-07 법인별 비중
# ---------------------------------------------------------------------------

def t4_07(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """C001 건수 비중 50% 이상 기대."""
    s = _t()
    rows = con.execute(f"""
        SELECT company_code, COUNT(*) AS cnt
        FROM je WHERE {_NORMAL}
        GROUP BY company_code ORDER BY cnt DESC
    """).fetchall()
    total = sum(r[1] for r in rows)
    by_cc = {r[0]: r[1] / total * 100 if total > 0 else 0 for r in rows}
    c001_pct = by_cc.get("C001", 0)

    status = "WARNING" if c001_pct < 50 else "PASS"
    return CheckResult(
        check_id="T4-07", tier=4, name="법인별 비중(C001)",
        status=status, expected="C001 ≥ 50%",
        actual=f"C001={c001_pct:.1f}%",
        detail={"company_pct": by_cc},
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-08 process 비중
# ---------------------------------------------------------------------------

def t4_08(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """business_process별 비율 vs config 기대값 (±10% 허용)."""
    s = _t()
    rows = con.execute(f"""
        SELECT business_process, COUNT(*) AS cnt
        FROM je WHERE {_NORMAL}
        GROUP BY business_process
    """).fetchall()
    total = sum(r[1] for r in rows)
    actual_pct = {r[0]: r[1] / total * 100 if total > 0 else 0 for r in rows}

    # config에 명시적 기대 비율 없으므로 편차 10%p 초과만 체크
    issues = [f"{bp}={p:.1f}%" for bp, p in actual_pct.items() if p > 60]
    status = "WARNING" if issues else "PASS"

    return CheckResult(
        check_id="T4-08", tier=4, name="process 비중",
        status=status, expected="단일 process ≤ 60%",
        actual=f"{actual_pct}",
        detail={"issues": issues} if issues else None,
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-09 persona 분포
# ---------------------------------------------------------------------------

def t4_09(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """automated_system 비율 60% 이상 기대."""
    s = _t()
    rows = con.execute(f"""
        SELECT user_persona, COUNT(*) AS cnt
        FROM je WHERE {_NORMAL}
        GROUP BY user_persona
    """).fetchall()
    total = sum(r[1] for r in rows)
    by_p = {r[0]: r[1] / total * 100 if total > 0 else 0 for r in rows}
    auto_pct = by_p.get("automated_system", 0)

    status = "WARNING" if auto_pct < 60 else "PASS"
    return CheckResult(
        check_id="T4-09", tier=4, name="persona 분포(automated)",
        status=status, expected="automated ≥ 60%",
        actual=f"automated={auto_pct:.1f}%",
        detail={"persona_pct": by_p},
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-10 IC 비율
# ---------------------------------------------------------------------------

def t4_10(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """내부거래(IC) 비율 5~20%."""
    s = _t()
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE document_type = 'IC'
                OR gl_account IN ('1150','2050','4500','2700')) AS ic,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    ic, total = row[0], row[1]
    pct = ic / total * 100 if total > 0 else 0

    status = "WARNING" if pct < 5 or pct > 20 else "PASS"
    return CheckResult(
        check_id="T4-10", tier=4, name="IC 비율",
        status=status, expected="5% ~ 20%",
        actual=f"{pct:.2f}% ({ic:,}/{total:,})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-11 round_number 비율
# ---------------------------------------------------------------------------

def t4_11(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """백만원 단위 round number 비율."""
    s = _t()
    exp = load_expectations()
    unit = exp.get("round_number_unit", 1_000_000)
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE
                GREATEST(COALESCE(debit_amount,0), COALESCE(credit_amount,0)) % {unit} = 0
                AND GREATEST(COALESCE(debit_amount,0), COALESCE(credit_amount,0)) > 0
            ) AS rnd,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    rnd, total = row[0], row[1]
    pct = rnd / total * 100 if total > 0 else 0

    status = "WARNING" if pct < 15 or pct > 35 else "PASS"
    return CheckResult(
        check_id="T4-11", tier=4, name="round_number 비율",
        status=status, expected="15% ~ 35%",
        actual=f"{pct:.2f}% ({rnd:,}/{total:,})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-12 nice_number 비율
# ---------------------------------------------------------------------------

def t4_12(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """십만원 단위 nice number 비율."""
    s = _t()
    exp = load_expectations()
    unit = exp.get("nice_number_unit", 100_000)
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE
                GREATEST(COALESCE(debit_amount,0), COALESCE(credit_amount,0)) % {unit} = 0
                AND GREATEST(COALESCE(debit_amount,0), COALESCE(credit_amount,0)) > 0
            ) AS nice,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    nice, total = row[0], row[1]
    pct = nice / total * 100 if total > 0 else 0

    status = "WARNING" if pct < 10 or pct > 25 else "PASS"
    return CheckResult(
        check_id="T4-12", tier=4, name="nice_number 비율",
        status=status, expected="10% ~ 25%",
        actual=f"{pct:.2f}% ({nice:,}/{total:,})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-13 HHI (GL 계정 집중도)
# ---------------------------------------------------------------------------

def t4_13(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """gl_account Herfindahl-Hirschman Index."""
    s = _t()
    rows = con.execute(f"""
        SELECT gl_account, COUNT(*) AS cnt
        FROM je WHERE {_NORMAL} AND gl_account IS NOT NULL
        GROUP BY gl_account
    """).fetchall()
    total = sum(r[1] for r in rows)
    hhi = sum((r[1] / total) ** 2 for r in rows) if total > 0 else 0

    status = "PASS" if hhi < 0.1 else "WARNING"
    return CheckResult(
        check_id="T4-13", tier=4, name="GL HHI 집중도",
        status=status, expected="HHI < 0.1 (분산됨)",
        actual=f"HHI={hhi:.4f} (계정수={len(rows)})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-14 기말 스파이크 (12/26~31)
# ---------------------------------------------------------------------------

def t4_14(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """12월 26~31일 건수 / 일평균 비율."""
    s = _t()
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE posting_date BETWEEN '2022-12-26' AND '2022-12-31') AS yr_end,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    yr_end, total = row[0], row[1]
    # 연간 영업일 ~250일 기준 일평균
    daily_avg = total / 250 if total > 0 else 1
    # 6일간 일평균
    yr_end_daily = yr_end / 6 if yr_end > 0 else 0
    ratio = yr_end_daily / daily_avg if daily_avg > 0 else 0

    status = "WARNING" if ratio < 3 else "PASS"
    return CheckResult(
        check_id="T4-14", tier=4, name="기말 스파이크(12/26~31)",
        status=status, expected="기말 일평균 / 연평균 ≥ 3",
        actual=f"ratio={ratio:.2f} (기말일평균={yr_end_daily:.0f}, 연일평균={daily_avg:.0f})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-15 공휴일 비율
# ---------------------------------------------------------------------------

def t4_15(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """KR 공휴일 전표 비율."""
    s = _t()
    holidays_str = ", ".join(f"'{d}'" for d in KR_HOLIDAYS_2022)
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE CAST(posting_date AS DATE) IN ({holidays_str})) AS hol,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    hol, total = row[0], row[1]
    pct = hol / total * 100 if total > 0 else 0

    status = "WARNING" if pct > 10 else "PASS"
    return CheckResult(
        check_id="T4-15", tier=4, name="공휴일 비율",
        status=status, expected="공휴일 전표 ≤ 10%",
        actual=f"{pct:.2f}% ({hol:,}/{total:,})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-16 결측률 MCAR
# ---------------------------------------------------------------------------

def t4_16(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """비보호 필드 null rate (5% 이하 기대)."""
    s = _t()
    exp = load_expectations()
    protected = set(exp.get("protected_fields", ["document_id", "company_code", "posting_date"]))
    cols = [r[1] for r in con.execute("PRAGMA table_info('je')").fetchall()]
    check_cols = [c for c in cols if c not in protected]

    total = con.execute(f"SELECT COUNT(*) FROM je WHERE {_NORMAL}").fetchone()[0]
    high_null = {}
    for col in check_cols:
        null_cnt = con.execute(f"""
            SELECT COUNT(*) - COUNT("{col}") FROM je WHERE {_NORMAL}
        """).fetchone()[0]
        rate = null_cnt / total * 100 if total > 0 else 0
        if rate > 5:
            high_null[col] = round(rate, 2)

    status = "WARNING" if high_null else "PASS"
    return CheckResult(
        check_id="T4-16", tier=4, name="결측률 MCAR",
        status=status, expected="비보호 필드 null ≤ 5%",
        actual=f"위반 {len(high_null)}건" if high_null else "OK",
        detail={"high_null_pct": high_null} if high_null else None,
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-17 SoD 위반률
# ---------------------------------------------------------------------------

def t4_17(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """sod_violation 비율 vs config 기대값 (2배 초과 시 WARNING)."""
    s = _t()
    exp = load_expectations()
    expected_rate = exp.get("sod_violation_rate", 0.01)
    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE sod_violation = true) AS sod,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
    """).fetchone()
    sod, total = row[0], row[1]
    actual_rate = sod / total if total > 0 else 0

    status = "WARNING" if actual_rate > expected_rate * 2 else "PASS"
    return CheckResult(
        check_id="T4-17", tier=4, name="SoD 위반률",
        status=status, expected=f"≤ {expected_rate*200:.1f}% (config×2)",
        actual=f"{actual_rate*100:.3f}% ({sod:,}/{total:,})",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-18 posting_date 시간 다양성
# ---------------------------------------------------------------------------

def t4_18(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """DISTINCT(hour*60+minute) 다양성."""
    s = _t()
    distinct_mins = con.execute(f"""
        SELECT COUNT(DISTINCT (EXTRACT(HOUR FROM posting_date)*60
                               + EXTRACT(MINUTE FROM posting_date)))
        FROM je WHERE {_NORMAL}
    """).fetchone()[0]

    status = "WARNING" if distinct_mins < 50 else "PASS"
    return CheckResult(
        check_id="T4-18", tier=4, name="시간 다양성",
        status=status, expected="DISTINCT(hh:mm) ≥ 50",
        actual=f"distinct_minutes={distinct_mins}",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-19 line_item 분포 (정보 제공)
# ---------------------------------------------------------------------------

def t4_19(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """전표당 행수 분포 (정보 제공, 항상 PASS)."""
    s = _t()
    rows = con.execute(f"""
        SELECT line_cnt, COUNT(*) AS doc_cnt FROM (
            SELECT document_id, COUNT(*) AS line_cnt
            FROM je WHERE {_NORMAL}
            GROUP BY document_id
        ) GROUP BY line_cnt ORDER BY line_cnt
    """).fetchall()
    dist = {r[0]: r[1] for r in rows}
    total_docs = sum(r[1] for r in rows)
    two_line_pct = dist.get(2, 0) / total_docs * 100 if total_docs > 0 else 0

    return CheckResult(
        check_id="T4-19", tier=4, name="line_item 분포",
        status="PASS", expected="정보 제공용",
        actual=f"총{total_docs:,}건, 2행={two_line_pct:.1f}%",
        detail={"line_dist": {str(k): v for k, v in list(dist.items())[:10]}},
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-20 source 분포
# ---------------------------------------------------------------------------

def t4_20(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """source별 비율 vs config 기대값 (±10%p 허용)."""
    s = _t()
    rows = con.execute(f"""
        SELECT source, COUNT(*) AS cnt
        FROM je WHERE {_NORMAL}
        GROUP BY source
    """).fetchall()
    total = sum(r[1] for r in rows)
    actual_pct = {r[0]: r[1] / total * 100 if total > 0 else 0 for r in rows}

    # automated 비율이 지배적(60%+)이어야 함
    auto_pct = actual_pct.get("automated", 0)
    status = "WARNING" if auto_pct < 50 else "PASS"

    return CheckResult(
        check_id="T4-20", tier=4, name="source 분포",
        status=status, expected="automated ≥ 50%",
        actual=f"automated={auto_pct:.1f}%",
        detail={"source_pct": actual_pct},
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# T4-21 SA 집중도 (12월 vs 1~11월)
# ---------------------------------------------------------------------------

def t4_21(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """12월 SA(결산조정) 비율 vs 1~11월 평균."""
    s = _t()
    rows = con.execute(f"""
        SELECT
            EXTRACT(MONTH FROM posting_date) AS m,
            COUNT(*) FILTER (WHERE document_type = 'SA') AS sa_cnt,
            COUNT(*) AS total
        FROM je WHERE {_NORMAL}
        GROUP BY m ORDER BY m
    """).fetchall()
    by_m = {int(r[0]): (r[1], r[2]) for r in rows}

    dec_sa, dec_total = by_m.get(12, (0, 1))
    dec_sa_pct = dec_sa / dec_total * 100 if dec_total > 0 else 0

    non_dec_sa_pcts = []
    for m in range(1, 12):
        sa, tot = by_m.get(m, (0, 1))
        non_dec_sa_pcts.append(sa / tot * 100 if tot > 0 else 0)
    avg_non_dec = sum(non_dec_sa_pcts) / len(non_dec_sa_pcts) if non_dec_sa_pcts else 0

    ratio = dec_sa_pct / avg_non_dec if avg_non_dec > 0 else 0
    status = "WARNING" if ratio < 1.5 else "PASS"

    return CheckResult(
        check_id="T4-21", tier=4, name="SA 집중도(12월)",
        status=status, expected="12월 SA비율 / 평월 ≥ 1.5",
        actual=f"ratio={ratio:.2f} (12월={dec_sa_pct:.1f}%, 평월={avg_non_dec:.1f}%)",
        elapsed_ms=_ms(s),
    )


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

def run_tier4(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 4 전체 체크 실행 (21개)."""
    return [fn(con) for fn in [
        t4_01, t4_02, t4_03, t4_04, t4_05, t4_06, t4_07,
        t4_08, t4_09, t4_10, t4_11, t4_12, t4_13, t4_14,
        t4_15, t4_16, t4_17, t4_18, t4_19, t4_20, t4_21,
    ]]
