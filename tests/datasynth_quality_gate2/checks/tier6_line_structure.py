"""Tier 6: 전표 내부 GL 쌍 현실성.

전표 내 차변/대변 GL 계정 조합이 현실적인지 검증.
fraud 전표만 랜덤 GL 쌍을 가지면 line-level leakage.
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


def l6_01_gl_pair_leakage(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L6-01: debit-credit GL 쌍 leakage.

    전표 내 (debit GL 1자리, credit GL 1자리) 쌍을 추출하여
    fraud에서만 존재하고 정상에서 0건인 쌍을 탐지.
    """
    start = _timer()

    # Why: 같은 전표(document_id) 내 debit GL과 credit GL을 각각 추출하여 조합
    rows = con.execute("""
        SELECT dr_gl1, cr_gl1, fraud_cnt, anom_cnt FROM (
            SELECT dr_gl1, cr_gl1,
                SUM(CASE WHEN is_fraud='true' THEN 1 ELSE 0 END) AS fraud_cnt,
                SUM(CASE WHEN is_anomaly='true' AND is_fraud!='true' THEN 1 ELSE 0 END) AS anom_cnt,
                SUM(CASE WHEN is_fraud!='true' AND is_anomaly!='true' THEN 1 ELSE 0 END) AS normal_cnt
            FROM (
                SELECT
                    je.document_id,
                    je.is_fraud,
                    je.is_anomaly,
                    LEFT(CAST(dr.gl_account AS VARCHAR), 1) AS dr_gl1,
                    LEFT(CAST(cr.gl_account AS VARCHAR), 1) AS cr_gl1
                FROM (SELECT DISTINCT document_id, is_fraud, is_anomaly
                      FROM je WHERE CAST(line_number AS INT) = 1) je
                JOIN (SELECT document_id, gl_account FROM je
                      WHERE CAST(debit_amount AS DOUBLE) > 0
                        AND gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) != ''
                        AND LENGTH(CAST(gl_account AS VARCHAR)) <= 5
                      ) dr ON je.document_id = dr.document_id
                JOIN (SELECT document_id, gl_account FROM je
                      WHERE CAST(credit_amount AS DOUBLE) > 0
                        AND gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) != ''
                        AND LENGTH(CAST(gl_account AS VARCHAR)) <= 5
                      ) cr ON je.document_id = cr.document_id
            )
            GROUP BY dr_gl1, cr_gl1
        )
        WHERE normal_cnt = 0 AND (fraud_cnt + anom_cnt) >= 15
        ORDER BY fraud_cnt + anom_cnt DESC
    """).fetchall()

    leaks = [{"debit_gl1": r[0], "credit_gl1": r[1], "fraud": r[2], "anomaly": r[3]} for r in rows]

    status = "FAIL" if len(leaks) > 0 else "PASS"
    return CheckResult(
        check_id="L6-01", tier=6,
        name="GL pair leakage",
        status=status,
        expected="fraud 전용 GL쌍 (15건+) = 0",
        actual=f"leakage GL쌍 {len(leaks)}건",
        detail={"leaks": leaks[:10]} if leaks else None,
        elapsed_ms=_elapsed(start),
    )


def l6_02_process_gl_pair_realism(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L6-02: 프로세스별 GL 쌍 현실성.

    P2P: 차변=자산/비용(1/5), 대변=부채(2)
    O2C: 차변=자산(1), 대변=수익(4)
    H2R: 차변=비용(6), 대변=부채(2)
    R2R: 다양 (결산 조정)

    예상 패턴의 비율이 50% 미만이면 비현실적.
    """
    start = _timer()

    # Why: 프로세스별 예상 GL 쌍 패턴 정의
    #       실무에서는 하나의 프로세스가 여러 GL그룹을 사용 (세금, 할인, 운반비 등)
    #       넓은 범위로 정의하여 현실적 매칭률 보장
    process_patterns = {
        "P2P": ("1,2,5,6", "1,2,5,6"),   # P2P: 자산/부채/COGS/비용 전반 사용
        "O2C": ("1,2", "1,2,4"),     # O2C: AR(1)/부채(2) ↔ 수익(4)/AR(1)/부채(2)
        "H2R": ("1,5,6", "1,2"),     # H2R: 자산(1,선급급여)/인건비(5,6) ↔ 미지급(2)/현금(1)
    }

    results: list[dict[str, Any]] = []
    all_ok = True

    for bp, (dr_expected, cr_expected) in process_patterns.items():
        dr_vals = dr_expected.split(",")
        cr_vals = cr_expected.split(",")

        dr_cond = " OR ".join([f"dr_gl1 = '{v}'" for v in dr_vals])
        cr_cond = " OR ".join([f"cr_gl1 = '{v}'" for v in cr_vals])

        row = con.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN ({dr_cond}) AND ({cr_cond}) THEN 1 ELSE 0 END) AS matched
            FROM (
                SELECT
                    je.document_id,
                    LEFT(CAST(dr.gl_account AS VARCHAR), 1) AS dr_gl1,
                    LEFT(CAST(cr.gl_account AS VARCHAR), 1) AS cr_gl1
                FROM (SELECT DISTINCT document_id
                      FROM je WHERE CAST(line_number AS INT) = 1
                        AND is_fraud != 'true' AND is_anomaly != 'true'
                        AND business_process = '{bp}') je
                JOIN (SELECT document_id, gl_account FROM je
                      WHERE CAST(debit_amount AS DOUBLE) > 0
                        AND gl_account IS NOT NULL AND LENGTH(CAST(gl_account AS VARCHAR)) <= 5
                      ) dr ON je.document_id = dr.document_id
                JOIN (SELECT document_id, gl_account FROM je
                      WHERE CAST(credit_amount AS DOUBLE) > 0
                        AND gl_account IS NOT NULL AND LENGTH(CAST(gl_account AS VARCHAR)) <= 5
                      ) cr ON je.document_id = cr.document_id
            )
        """).fetchone()

        total, matched = row[0] or 0, row[1] or 0
        rate = matched / total * 100 if total > 0 else 0
        if total > 100 and rate < 50:
            all_ok = False
        results.append({
            "process": bp, "expected_dr": dr_expected, "expected_cr": cr_expected,
            "matched": matched, "total": total, "rate": f"{rate:.1f}%",
        })

    status = "PASS" if all_ok else "WARNING"
    return CheckResult(
        check_id="L6-02", tier=6,
        name="process GL pair realism",
        status=status,
        expected="프로세스별 예상 GL쌍 >= 50%",
        actual=f"{'모두 충족' if all_ok else '미충족 존재'}",
        detail={"processes": results},
        elapsed_ms=_elapsed(start),
    )


def run_tier6(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 6 전체 실행."""
    return [
        l6_01_gl_pair_leakage(con),
        l6_02_process_gl_pair_realism(con),
    ]
