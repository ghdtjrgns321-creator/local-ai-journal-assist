"""Tier 2: 분포 현실성 검증.

정상 vs 비정상의 분포가 너무 깔끔하게 분리되어 있으면 ML artifact.
실제 데이터는 분포가 겹쳐야(overlap) 정상.
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


def l2_01_amount_overlap(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L2-01: 금액 분포 겹침도 — 정상과 비정상의 IQR이 겹치는지.

    정상 전표의 금액 [Q1, Q3]과 비정상 전표의 [Q1, Q3]이
    전혀 겹치지 않으면 금액만으로 완벽 분류 가능 = fitting.
    """
    start = _timer()

    stats = con.execute("""
        SELECT category,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY amt) AS q1,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY amt) AS q3
        FROM (
            SELECT
                CASE WHEN is_fraud='true' OR is_anomaly='true' THEN 'abnormal' ELSE 'normal' END AS category,
                CAST(debit_amount AS DOUBLE) AS amt
            FROM je WHERE CAST(debit_amount AS DOUBLE) > 0
        )
        GROUP BY category
    """).fetchall()

    if len(stats) < 2:
        return CheckResult(
            check_id="L2-01", tier=2, name="amount overlap",
            status="SKIP", expected="2개 그룹 필요", actual="그룹 부족",
            elapsed_ms=_elapsed(start),
        )

    # Why: IQR이 겹치는지 확인 — overlap = max(0, min(q3_a, q3_b) - max(q1_a, q1_b))
    d = {r[0]: (r[1], r[2]) for r in stats}
    n_q1, n_q3 = d.get("normal", (0, 0))
    a_q1, a_q3 = d.get("abnormal", (0, 0))

    overlap = max(0, min(n_q3, a_q3) - max(n_q1, a_q1))
    n_range = n_q3 - n_q1 if n_q3 > n_q1 else 1
    overlap_ratio = overlap / n_range

    status = "PASS" if overlap_ratio > 0.3 else ("WARNING" if overlap_ratio > 0 else "FAIL")
    return CheckResult(
        check_id="L2-01", tier=2, name="amount overlap",
        status=status,
        expected="IQR 겹침 > 30%",
        actual=f"겹침 {overlap_ratio:.1%} (normal=[{n_q1:,.0f},{n_q3:,.0f}], abnormal=[{a_q1:,.0f},{a_q3:,.0f}])",
        elapsed_ms=_elapsed(start),
    )


def l2_02_fraud_rate_temporal(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L2-02: fraud율 시간 균일성 — 전 기간 균일 분산이면 비현실적.

    실제 부정은 결산기(3/6/9/12월)에 집중됨.
    월별 fraud율의 변동계수(CV)가 너무 낮으면 비현실적 균일 분산.
    """
    start = _timer()

    rows = con.execute("""
        SELECT month_val,
            SUM(CASE WHEN is_fraud='true' THEN 1.0 ELSE 0 END) / COUNT(*) AS fraud_rate
        FROM (
            SELECT CAST(fiscal_period AS INT) AS month_val, is_fraud
            FROM je WHERE CAST(line_number AS INT) = 1
        )
        GROUP BY month_val ORDER BY month_val
    """).fetchall()

    if len(rows) < 6:
        return CheckResult(
            check_id="L2-02", tier=2, name="fraud rate temporal",
            status="SKIP", expected="6개월+ 필요", actual=f"{len(rows)}개월",
            elapsed_ms=_elapsed(start),
        )

    rates = [r[1] for r in rows]
    mean_rate = sum(rates) / len(rates)
    # Why: 표준편차 / 평균 = 변동계수. 0.1 미만이면 거의 균일 → 비현실적
    import math
    std = math.sqrt(sum((r - mean_rate) ** 2 for r in rates) / len(rates))
    cv = std / mean_rate if mean_rate > 0 else 0

    status = "PASS" if cv > 0.1 else "WARNING"
    return CheckResult(
        check_id="L2-02", tier=2, name="fraud rate temporal variation",
        status=status,
        expected="월별 fraud율 변동계수(CV) > 0.1",
        actual=f"CV={cv:.3f}, mean={mean_rate:.4f}, std={std:.4f}",
        elapsed_ms=_elapsed(start),
    )


def l2_03_gl_amount_joint(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L2-03: GL-금액 결합분포 — 계정군별 금액 분포가 차이 나는지.

    실무에서 급여(6xxx)는 300~800만원, 매출(4xxx)은 넓은 범위.
    모든 GL에 동일 분포가 적용되면 비현실적.
    """
    start = _timer()

    rows = con.execute("""
        SELECT gl_group,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY amt) AS median_amt,
            COUNT(*) AS cnt
        FROM (
            SELECT LEFT(CAST(gl_account AS VARCHAR), 1) AS gl_group,
                CAST(debit_amount AS DOUBLE) AS amt
            FROM je
            WHERE CAST(debit_amount AS DOUBLE) > 0
                AND is_fraud != 'true' AND is_anomaly != 'true'
                AND gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) != ''
        )
        GROUP BY gl_group HAVING COUNT(*) >= 100
        ORDER BY gl_group
    """).fetchall()

    if len(rows) < 3:
        return CheckResult(
            check_id="L2-03", tier=2, name="GL-amount joint distribution",
            status="SKIP", expected="3개 GL그룹+ 필요", actual=f"{len(rows)}개",
            elapsed_ms=_elapsed(start),
        )

    medians = [r[1] for r in rows]
    # Why: 중앙값의 최대/최소 비율이 2배 미만이면 모든 계정이 비슷한 분포 = 비현실적
    max_med = max(medians)
    min_med = min(m for m in medians if m > 0) if any(m > 0 for m in medians) else 1
    ratio = max_med / min_med if min_med > 0 else 0

    groups_detail = [{"gl": r[0], "median": f"{r[1]:,.0f}", "count": r[2]} for r in rows]

    status = "PASS" if ratio >= 2.0 else "WARNING"
    return CheckResult(
        check_id="L2-03", tier=2, name="GL-amount joint distribution",
        status=status,
        expected="GL그룹별 중앙값 최대/최소 비율 >= 2",
        actual=f"비율={ratio:.1f}x (max={max_med:,.0f}, min={min_med:,.0f})",
        detail={"groups": groups_detail},
        elapsed_ms=_elapsed(start),
    )


def l2_04_has_attachment_fraud_bias(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L2-04: has_attachment fraud 편향 — fraud에서 false 비율 과다.

    fraud 전표에서 has_attachment=false 비율이
    정상 대비 3배 이상 높으면 이 피처 하나로 분류 힌트.
    """
    start = _timer()

    rows = con.execute("""
        SELECT category,
            SUM(CASE WHEN has_attachment='false' THEN 1.0 ELSE 0 END) / COUNT(*) AS false_rate
        FROM (
            SELECT
                CASE WHEN is_fraud='true' THEN 'fraud'
                     WHEN is_anomaly='true' THEN 'anomaly'
                     ELSE 'normal' END AS category,
                has_attachment
            FROM je WHERE CAST(line_number AS INT) = 1
        )
        GROUP BY category
    """).fetchall()

    d = {r[0]: r[1] for r in rows}
    normal_rate = d.get("normal", 0)
    fraud_rate = d.get("fraud", 0)
    ratio = fraud_rate / normal_rate if normal_rate > 0 else 0

    status = "PASS" if ratio < 3.0 else "WARNING"
    return CheckResult(
        check_id="L2-04", tier=2, name="has_attachment fraud bias",
        status=status,
        expected="fraud false비율 < normal의 3배",
        actual=f"fraud={fraud_rate:.1%}, normal={normal_rate:.1%}, ratio={ratio:.1f}x",
        elapsed_ms=_elapsed(start),
    )


def run_tier2(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 2 전체 실행."""
    return [
        l2_01_amount_overlap(con),
        l2_02_fraud_rate_temporal(con),
        l2_03_gl_amount_joint(con),
        l2_04_has_attachment_fraud_bias(con),
    ]
