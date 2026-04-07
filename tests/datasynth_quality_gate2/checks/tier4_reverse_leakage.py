"""Tier 4: 역방향 Leakage (정상 데이터 완벽도).

정상 전표가 너무 깨끗하면 ML이 "불완전=fraud"로 학습.
실제 데이터는 결측, 지연, 반복, 노이즈가 자연스럽게 존재.
"""
from __future__ import annotations

import time
from typing import Any

import duckdb

from ..models import CheckResult


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def l4_01_normal_text_missing(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L4-01: 정상 line_text 결측률.

    실무 ERP에서 적요(line_text)는 10~20% 결측이 흔함.
    정상이 0% 결측이면 "결측=fraud" 학습 위험.
    """
    start = _timer()

    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN line_text IS NULL OR CAST(line_text AS VARCHAR) = '' THEN 1 ELSE 0 END) AS missing
        FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
    """).fetchone()

    total, missing = row[0], row[1]
    rate = missing / total * 100 if total > 0 else 0

    # Why: 5~25%가 현실적. 0%면 비현실적, 30%+ 면 DQ 과다
    if rate < 2:
        status = "WARNING"
    elif rate > 30:
        status = "WARNING"
    else:
        status = "PASS"

    return CheckResult(
        check_id="L4-01", tier=4,
        name="normal text missing rate",
        status=status,
        expected="정상 line_text 결측 2~30%",
        actual=f"{rate:.1f}% ({missing:,}/{total:,})",
        elapsed_ms=_elapsed(start),
    )


def l4_02_normal_approval_delay(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L4-02: 정상 approval 지연 비율.

    모든 정상 전표가 즉시 승인이면 비현실적.
    실무에서 5~30%는 1일+ 지연 (결재선 다단계, 출장 등).
    """
    start = _timer()

    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN CAST(approval_date AS DATE) > CAST(posting_date AS DATE) THEN 1 ELSE 0 END) AS delayed
        FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
            AND CAST(line_number AS INT) = 1
            AND approval_date IS NOT NULL AND CAST(approval_date AS VARCHAR) != ''
            AND posting_date IS NOT NULL
    """).fetchone()

    total, delayed = row[0], row[1]
    rate = delayed / total * 100 if total > 0 else 0

    status = "PASS" if rate >= 3 else "WARNING"
    return CheckResult(
        check_id="L4-02", tier=4,
        name="normal approval delay",
        status=status,
        expected="approval 지연(>0일) >= 3%",
        actual=f"{rate:.1f}% ({delayed:,}/{total:,})",
        elapsed_ms=_elapsed(start),
    )


def l4_03_normal_recurring_amounts(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L4-03: 정상 동일금액 반복 존재 여부.

    급여, 임대료, 감가상각 등은 매월 동일 금액 반복.
    동일 (gl_account, amount) 쌍이 3회+ 반복되는 건이 없으면 비현실적.
    """
    start = _timer()

    recurring = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT gl_account, CAST(debit_amount AS DOUBLE) AS amt,
                COUNT(*) AS cnt
            FROM je
            WHERE is_fraud != 'true' AND is_anomaly != 'true'
                AND CAST(debit_amount AS DOUBLE) > 10000
                AND gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) != ''
            GROUP BY gl_account, CAST(debit_amount AS DOUBLE)
            HAVING cnt >= 3
        )
    """).fetchone()[0]

    status = "PASS" if recurring > 0 else "WARNING"
    return CheckResult(
        check_id="L4-03", tier=4,
        name="normal recurring amounts",
        status=status,
        expected="동일 GL+금액 3회+ 반복 > 0",
        actual=f"반복 패턴 {recurring:,}건",
        elapsed_ms=_elapsed(start),
    )


def l4_04_normal_description_diversity(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L4-04: 정상 적요 다양성.

    동일 line_text가 70%+ 반복이면 template artifact.
    실무 적요는 다양해야 함 (고유 비율 30%+).
    """
    start = _timer()

    row = con.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(DISTINCT CAST(line_text AS VARCHAR)) AS distinct_cnt
        FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
            AND line_text IS NOT NULL AND CAST(line_text AS VARCHAR) != ''
    """).fetchone()

    total, distinct = row[0], row[1]
    diversity = distinct / total * 100 if total > 0 else 0

    status = "PASS" if diversity >= 20 else "WARNING"
    return CheckResult(
        check_id="L4-04", tier=4,
        name="normal description diversity",
        status=status,
        expected="고유 적요 비율 >= 20%",
        actual=f"{diversity:.1f}% ({distinct:,}/{total:,})",
        elapsed_ms=_elapsed(start),
    )


def run_tier4(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 4 전체 실행."""
    return [
        l4_01_normal_text_missing(con),
        l4_02_normal_approval_delay(con),
        l4_03_normal_recurring_amounts(con),
        l4_04_normal_description_diversity(con),
    ]
