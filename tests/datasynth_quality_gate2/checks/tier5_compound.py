"""Tier 5: 복합 피처 Leakage.

단일 컬럼은 통과해도 2개 컬럼 조합이 정상/비정상을 완벽 분리할 수 있음.
(gl_prefix, amount_bucket) 같은 주요 2-피처 조합을 자동 스캔.
"""
from __future__ import annotations

import time
from typing import Any

import duckdb

from ..models import CheckResult

_MIN_COUNT = 15  # Why: 10건 경계에서 seed 변경 시 flaky. Tier 1과 동일 기준.


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def l5_01_two_feature_scan(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L5-01: 2-피처 조합 leakage 스캔.

    주요 피처 쌍에서 fraud 비율이 90%+ 인 조합을 탐지.
    단일 피처는 통과해도 2개 조합이 완벽 분리되면 ML 치팅 가능.
    """
    start = _timer()

    # Why: 주요 피처 쌍 정의 — ML이 실제로 사용할 가능성 높은 조합
    feature_pairs = [
        ("LEFT(CAST(gl_account AS VARCHAR), 1)", "amount_bucket", "gl1 x amount"),
        ("LEFT(CAST(gl_account AS VARCHAR), 1)", "hour_val", "gl1 x hour"),
        ("source", "hour_val", "source x hour"),
        ("source", "amount_bucket", "source x amount"),
        ("user_persona", "amount_bucket", "persona x amount"),
    ]

    # Why: 먼저 amount_bucket과 hour_val 파생 컬럼을 만들어둠
    try:
        con.execute("DROP VIEW IF EXISTS je_features")
    except Exception:
        pass

    con.execute("""
        CREATE VIEW je_features AS
        SELECT *,
            CASE
                WHEN CAST(debit_amount AS DOUBLE) <= 0 THEN 'zero'
                WHEN CAST(debit_amount AS DOUBLE) < 1000000 THEN '<100만'
                WHEN CAST(debit_amount AS DOUBLE) < 100000000 THEN '100만~1억'
                WHEN CAST(debit_amount AS DOUBLE) < 10000000000 THEN '1억~100억'
                ELSE '100억+'
            END AS amount_bucket,
            CASE
                WHEN LENGTH(CAST(posting_date AS VARCHAR)) >= 13
                    THEN CAST(SUBSTR(CAST(posting_date AS VARCHAR), 12, 2) AS INT)
                ELSE -1
            END AS hour_val
        FROM je
        WHERE CAST(line_number AS INT) = 1
    """)

    high_fraud_combos: list[dict[str, Any]] = []

    for feat_a_expr, feat_b, pair_name in feature_pairs:
        rows = con.execute(f"""
            SELECT combo_a, combo_b, fraud_cnt, total_cnt FROM (
                SELECT
                    CAST({feat_a_expr} AS VARCHAR) AS combo_a,
                    CAST({feat_b} AS VARCHAR) AS combo_b,
                    SUM(CASE WHEN is_fraud='true' THEN 1 ELSE 0 END) AS fraud_cnt,
                    COUNT(*) AS total_cnt
                FROM je_features
                WHERE {feat_a_expr} IS NOT NULL AND CAST({feat_b} AS VARCHAR) IS NOT NULL
                    AND CAST({feat_a_expr} AS VARCHAR) != '' AND CAST({feat_b} AS VARCHAR) != ''
                GROUP BY CAST({feat_a_expr} AS VARCHAR), CAST({feat_b} AS VARCHAR)
            )
            WHERE total_cnt >= {_MIN_COUNT} AND fraud_cnt * 1.0 / total_cnt >= 0.90
            ORDER BY fraud_cnt DESC
            LIMIT 5
        """).fetchall()

        for a, b, f_cnt, total in rows:
            high_fraud_combos.append({
                "pair": pair_name, "value_a": str(a), "value_b": str(b),
                "fraud": f_cnt, "total": total,
                "fraud_rate": f"{f_cnt/total:.1%}",
            })

    status = "FAIL" if len(high_fraud_combos) > 0 else "PASS"
    return CheckResult(
        check_id="L5-01", tier=5,
        name="2-feature combo leakage",
        status=status,
        expected="90%+ fraud 조합 = 0",
        actual=f"고위험 조합 {len(high_fraud_combos)}건",
        detail={"combos": high_fraud_combos[:15]} if high_fraud_combos else None,
        elapsed_ms=_elapsed(start),
    )


def l5_02_gl_amount_separation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L5-02: (GL 1자리, 금액 구간) 조합에서 정상=0 탐지.

    특정 GL+금액 조합이 fraud/anomaly에만 존재하면
    이 2-피처 조합이 완벽 분리기가 됨.
    """
    start = _timer()

    rows = con.execute(f"""
        SELECT gl1, amount_bucket, fraud_cnt, anom_cnt FROM (
            SELECT
                LEFT(CAST(gl_account AS VARCHAR), 1) AS gl1,
                CASE
                    WHEN CAST(debit_amount AS DOUBLE) < 1000000 THEN '<100만'
                    WHEN CAST(debit_amount AS DOUBLE) < 100000000 THEN '100만~1억'
                    WHEN CAST(debit_amount AS DOUBLE) < 10000000000 THEN '1억~100억'
                    ELSE '100억+'
                END AS amount_bucket,
                SUM(CASE WHEN is_fraud='true' THEN 1 ELSE 0 END) AS fraud_cnt,
                SUM(CASE WHEN is_anomaly='true' AND is_fraud!='true' THEN 1 ELSE 0 END) AS anom_cnt,
                SUM(CASE WHEN is_fraud!='true' AND is_anomaly!='true' THEN 1 ELSE 0 END) AS normal_cnt
            FROM je
            WHERE gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) != ''
                AND CAST(debit_amount AS DOUBLE) > 0
                AND LENGTH(CAST(gl_account AS VARCHAR)) <= 5
            GROUP BY LEFT(CAST(gl_account AS VARCHAR), 1),
                CASE
                    WHEN CAST(debit_amount AS DOUBLE) < 1000000 THEN '<100만'
                    WHEN CAST(debit_amount AS DOUBLE) < 100000000 THEN '100만~1억'
                    WHEN CAST(debit_amount AS DOUBLE) < 10000000000 THEN '1억~100억'
                    ELSE '100억+'
                END
        )
        WHERE normal_cnt = 0 AND (fraud_cnt + anom_cnt) >= {_MIN_COUNT}
        ORDER BY fraud_cnt + anom_cnt DESC
    """).fetchall()

    leaks = [{"gl1": r[0], "bucket": r[1], "fraud": r[2], "anomaly": r[3]} for r in rows]

    status = "FAIL" if len(leaks) > 0 else "PASS"
    return CheckResult(
        check_id="L5-02", tier=5,
        name="GL x amount separation",
        status=status,
        expected="정상=0 GL+금액 조합 = 0",
        actual=f"분리 조합 {len(leaks)}건",
        detail={"leaks": leaks[:10]} if leaks else None,
        elapsed_ms=_elapsed(start),
    )


def run_tier5(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 5 전체 실행."""
    return [
        l5_01_two_feature_scan(con),
        l5_02_gl_amount_separation(con),
    ]
