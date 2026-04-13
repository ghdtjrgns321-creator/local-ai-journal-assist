"""Tier 4: 교차 필드 정합성 — 프로세스↔GL, persona↔source 등."""
from __future__ import annotations

import time

import duckdb

from ..models import CheckResult


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def r4_01_o2c_revenue(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-01: O2C 대변 중 수익(4xxx) GL 비율 (>=40%)."""
    start = _timer()
    total, revenue = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN CAST(gl_account AS VARCHAR)[1] = '4' THEN 1 ELSE 0 END)
        FROM je
        WHERE business_process = 'O2C'
          AND CAST(credit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
    """).fetchone()
    pct = revenue / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-01", tier=4,
        name="O2C 대변 수익 GL 비율",
        status="PASS" if pct >= 40 else "FAIL",
        expected=">=40%",
        actual=f"{revenue:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_02_h2r_expense(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-02: H2R 차변 중 비용(5-6xxx) GL 비율 (>=80%)."""
    start = _timer()
    total, expense = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6')
                     THEN 1 ELSE 0 END)
        FROM je
        WHERE business_process = 'H2R'
          AND CAST(debit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
    """).fetchone()
    pct = expense / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-02", tier=4,
        name="H2R 차변 비용 GL 비율",
        status="PASS" if pct >= 80 else "WARNING",
        expected=">=80%",
        actual=f"{expense:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_03_p2p_wrong_debit(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-03: P2P 차변에 수익/자본 GL 비율 (<=3%)."""
    start = _timer()
    total, wrong = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN CAST(gl_account AS VARCHAR)[1] IN ('3','4')
                     THEN 1 ELSE 0 END)
        FROM je
        WHERE business_process = 'P2P'
          AND CAST(debit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
    """).fetchone()
    pct = wrong / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-03", tier=4,
        name="P2P 차변에 수익/자본 GL",
        status="PASS" if pct <= 3 else "WARNING",
        expected="<=3%",
        actual=f"{wrong:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_04_auto_manual(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-04: automated_system + source=manual 비율 (<=5%)."""
    start = _timer()
    # Why: 시스템 계정이 수동 입력하는 건 논리적 모순
    total, wrong = con.execute("""
        SELECT
            COUNT(DISTINCT document_id),
            COUNT(DISTINCT CASE
                WHEN user_persona = 'automated_system' AND source = 'manual'
                THEN document_id END)
        FROM je
    """).fetchone()
    pct = wrong / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-04", tier=4,
        name="automated_system + manual",
        status="PASS" if pct <= 5 else "WARNING",
        expected="<=5%",
        actual=f"{wrong:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_05_sod_type_complete(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-05: SoD 위반 + conflict_type 누락 = 0건."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE sod_violation = 'true'
          AND (sod_conflict_type IS NULL
               OR CAST(sod_conflict_type AS VARCHAR) = ''
               OR CAST(sod_conflict_type AS VARCHAR) = 'nan')
    """).fetchone()[0]
    return CheckResult(
        check_id="R4-05", tier=4,
        name="SoD 위반 + type 누락",
        status="PASS" if cnt == 0 else "FAIL",
        expected="0건",
        actual=f"{cnt:,}건",
        elapsed_ms=_elapsed(start),
    )


def r4_06_fraud_type_complete(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-06: fraud=true + fraud_type 누락 = 0건."""
    start = _timer()
    cnt = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE is_fraud = 'true'
          AND (fraud_type IS NULL
               OR CAST(fraud_type AS VARCHAR) = ''
               OR CAST(fraud_type AS VARCHAR) = 'nan')
    """).fetchone()[0]
    # Why: 라벨 오염 역방향도 체크 — 정상인데 fraud_type 있는 건
    contaminated = con.execute("""
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE (is_fraud IS NULL OR is_fraud != 'true')
          AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) != ''
          AND CAST(fraud_type AS VARCHAR) != 'nan'
    """).fetchone()[0]
    total_bad = cnt + contaminated
    return CheckResult(
        check_id="R4-06", tier=4,
        name="fraud 라벨 정합성",
        status="PASS" if total_bad == 0 else "FAIL",
        expected="누락 0건, 오염 0건",
        actual=f"누락 {cnt:,}건, 오염 {contaminated:,}건",
        elapsed_ms=_elapsed(start),
    )


def r4_07_ip_company_isolation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-07: IP 대역-회사 분리 (교차 사용 0건)."""
    start = _timer()
    # Why: 10.1=C001, 10.2=C002, 10.3=C003, 172.16=VPN(공용)
    cross = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT
                company_code,
                SPLIT_PART(ip_address, '.', 1) || '.' ||
                SPLIT_PART(ip_address, '.', 2) AS prefix
            FROM je
            WHERE ip_address IS NOT NULL
              AND SPLIT_PART(ip_address, '.', 1) != '172'
        )
        WHERE (company_code = 'C001' AND prefix != '10.1')
           OR (company_code = 'C002' AND prefix != '10.2')
           OR (company_code = 'C003' AND prefix != '10.3')
    """).fetchone()[0]
    return CheckResult(
        check_id="R4-07", tier=4,
        name="IP-회사 분리",
        status="PASS" if cross == 0 else "FAIL",
        expected="교차 0건",
        actual=f"교차 {cross:,}건",
        elapsed_ms=_elapsed(start),
    )


def r4_08_expense_cost_center(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-08: 비용GL(5-6xxx)에 cost_center 누락 비율 (<=10%)."""
    start = _timer()
    total, missing = con.execute("""
        SELECT
            COUNT(*),
            SUM(CASE
                WHEN cost_center IS NULL
                  OR CAST(cost_center AS VARCHAR) = ''
                  OR CAST(cost_center AS VARCHAR) = 'nan'
                THEN 1 ELSE 0 END)
        FROM je
        WHERE gl_account IS NOT NULL
          AND CAST(gl_account AS VARCHAR)[1] IN ('5', '6')
    """).fetchone()
    pct = missing / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-08", tier=4,
        name="비용GL + cost_center 누락",
        status="PASS" if pct <= 10 else "WARNING",
        expected="<=10%",
        actual=f"{missing:,}/{total:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def r4_09_korean_user_id(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R4-09: 사람 사용자 ID에 한국식 이름 비율 (한글 + 로마자)."""
    start = _timer()
    # Why: 한국 기업인데 NRODRI032 등 서양식 ID만 있으면 비현실적
    #       DataSynth는 로마자 한국이름(MKIM001, JPARK042) 형태로 생성하므로
    #       한글 유니코드뿐 아니라 로마자 한국 성씨 패턴도 탐지해야 함
    # 로마자 한국 성씨 목록 (대소문자 무시, user_id에서 첫 1글자 이니셜 + 성씨 + 숫자 패턴)
    korean_surnames_pattern = "|".join([
        "KIM", "LEE", "PARK", "CHOI", "JUNG", "KANG", "CHO", "YOON",
        "JANG", "LIM", "HAN", "OH", "SEO", "SHIN", "KWON", "HWANG",
        "AHN", "SONG", "RYU", "JEON",
    ])
    row = con.execute(f"""
        SELECT
            COUNT(DISTINCT created_by) AS total,
            COUNT(DISTINCT CASE
                WHEN created_by NOT LIKE 'SYSTEM-%'
                 AND (
                    REGEXP_MATCHES(created_by, '[가-힣]')
                    OR REGEXP_MATCHES(UPPER(created_by),
                       '^[A-Z]({korean_surnames_pattern})[0-9]')
                 )
                THEN created_by END) AS korean
        FROM je
        WHERE created_by NOT LIKE 'SYSTEM-%'
          AND created_by IS NOT NULL
    """).fetchone()
    total, korean = row[0] or 0, row[1] or 0
    pct = korean / total * 100 if total > 0 else 0
    return CheckResult(
        check_id="R4-09", tier=4,
        name="한국식 사용자 ID 비율",
        status="PASS" if pct > 0 else "WARNING",
        expected="한국식 ID 존재 (한글 또는 로마자 한국 성씨)",
        actual=f"한국식 {korean:,}/{total:,}명 ({pct:.0f}%)",
        elapsed_ms=_elapsed(start),
    )


def run_tier4(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 4 전체 실행."""
    return [
        r4_01_o2c_revenue(con),
        r4_02_h2r_expense(con),
        r4_03_p2p_wrong_debit(con),
        r4_04_auto_manual(con),
        r4_05_sod_type_complete(con),
        r4_06_fraud_type_complete(con),
        r4_07_ip_company_isolation(con),
        r4_08_expense_cost_center(con),
        r4_09_korean_user_id(con),
    ]
