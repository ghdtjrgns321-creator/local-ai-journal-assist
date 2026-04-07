"""Tier 1: Feature Leakage 자동 탐지.

ML이 단일 피처로 정상/비정상을 완벽 분류할 수 있는 패턴을 전수 스캔.
"이 값이 있으면 100% fraud" 같은 치팅 경로를 차단.
"""
from __future__ import annotations

import time
from typing import Any

import duckdb

from ..models import CheckResult

# Why: GL 계정은 DQ injection으로 NULL/빈값이 생길 수 있음 — 제외
_NULL_FILTER = "AND {col} IS NOT NULL AND CAST({col} AS VARCHAR) != ''"

# Why: 최소 건수 임계값 — 15건 미만은 통계적으로 무의미하므로 무시.
#      seed 변경으로 10~14건 경계에서 flaky해지는 것 방지.
_MIN_COUNT = 15


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def l1_01_categorical_leakage(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L1-01: 카테고리 컬럼 전수 스캔 — 비정상 전용 값 탐지.

    모든 카테고리형 컬럼에서 '정상 전표에는 0건인데 fraud/anomaly에만 존재하는 값'을 찾음.
    """
    start = _timer()

    # Why: 숫자/날짜/boolean/라벨 컬럼은 제외, 텍스트형 카테고리만 검사
    # Why: sod_conflict_type은 anomaly 분류 라벨 — 비정상에만 존재하는 것이 정상
    cat_cols = [
        "document_type", "source", "user_persona", "business_process",
        "currency", "ledger", "approved_by", "created_by",
        "cost_center", "profit_center", "trading_partner",
        "supporting_doc_type",
    ]

    # Why: 실제 존재하는 컬럼만 검사
    all_cols = [r[0] for r in con.execute("SELECT column_name FROM (DESCRIBE je)").fetchall()]
    cat_cols = [c for c in cat_cols if c in all_cols]

    leaks: list[dict[str, Any]] = []

    for col in cat_cols:
        # Why: 정상에서 0건이고 fraud+anomaly에서 MIN_COUNT 이상인 값 = leakage
        rows = con.execute(f"""
            SELECT val, fraud_cnt, anom_cnt FROM (
                SELECT CAST({col} AS VARCHAR) AS val,
                    SUM(CASE WHEN is_fraud='true' THEN 1 ELSE 0 END) AS fraud_cnt,
                    SUM(CASE WHEN is_anomaly='true' AND is_fraud!='true' THEN 1 ELSE 0 END) AS anom_cnt,
                    SUM(CASE WHEN is_fraud!='true' AND is_anomaly!='true' THEN 1 ELSE 0 END) AS normal_cnt
                FROM je
                WHERE {col} IS NOT NULL AND CAST({col} AS VARCHAR) != ''
                GROUP BY CAST({col} AS VARCHAR)
            )
            WHERE normal_cnt = 0 AND (fraud_cnt + anom_cnt) >= {_MIN_COUNT}
            ORDER BY fraud_cnt + anom_cnt DESC
        """).fetchall()

        for val, f_cnt, a_cnt in rows:
            leaks.append({
                "column": col, "value": str(val)[:50],
                "fraud": f_cnt, "anomaly": a_cnt, "normal": 0,
            })

    status = "FAIL" if len(leaks) > 0 else "PASS"
    return CheckResult(
        check_id="L1-01", tier=1,
        name="categorical leakage scan",
        status=status,
        expected="비정상 전용 카테고리 값 = 0",
        actual=f"leakage {len(leaks)}건",
        detail={"leaks": leaks[:30]} if leaks else None,
        elapsed_ms=_elapsed(start),
    )


def l1_02_gl_account_leakage(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L1-02: GL 계정 코드 leakage — prefix 단위 스캔.

    GL 계정의 1자리/2자리/3자리 prefix별로
    정상에서 0건이고 비정상에서만 존재하는 prefix를 탐지.
    Why: 6자리 무효 코드(999999, 777777 등)는 의도적 InvalidAccount 마커이므로 제외.
         이런 코드는 GL 자체가 탐지 대상이 맞음 (CoA 미등록 = 무조건 이상).
    """
    start = _timer()

    leaks: list[dict[str, Any]] = []

    for prefix_len in [1, 2, 3]:
        rows = con.execute(f"""
            SELECT gl_prefix, fraud_cnt, anom_cnt FROM (
                SELECT LEFT(CAST(gl_account AS VARCHAR), {prefix_len}) AS gl_prefix,
                    SUM(CASE WHEN is_fraud='true' THEN 1 ELSE 0 END) AS fraud_cnt,
                    SUM(CASE WHEN is_anomaly='true' AND is_fraud!='true' THEN 1 ELSE 0 END) AS anom_cnt,
                    SUM(CASE WHEN is_fraud!='true' AND is_anomaly!='true' THEN 1 ELSE 0 END) AS normal_cnt
                FROM je
                WHERE gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) != ''
                  AND LENGTH(CAST(gl_account AS VARCHAR)) <= 5
                GROUP BY LEFT(CAST(gl_account AS VARCHAR), {prefix_len})
            )
            WHERE normal_cnt = 0 AND (fraud_cnt + anom_cnt) >= {_MIN_COUNT}
            ORDER BY fraud_cnt + anom_cnt DESC
        """).fetchall()

        for prefix, f_cnt, a_cnt in rows:
            leaks.append({
                "prefix_len": prefix_len, "gl_prefix": prefix,
                "fraud": f_cnt, "anomaly": a_cnt,
            })

    status = "FAIL" if len(leaks) > 0 else "PASS"
    return CheckResult(
        check_id="L1-02", tier=1,
        name="GL account prefix leakage",
        status=status,
        expected="비정상 전용 GL prefix = 0",
        actual=f"leakage {len(leaks)}건",
        detail={"leaks": leaks[:20]} if leaks else None,
        elapsed_ms=_elapsed(start),
    )


def l1_03_keyword_leakage(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L1-03: 적요 키워드 leakage — 비정상에만 등장하는 키워드.

    risk_keywords.yaml + suspense_keywords의 키워드가
    정상 전표에는 0건이고 비정상에서만 존재하면 leakage.
    """
    start = _timer()

    keywords = [
        "가수금", "가지급", "가계정", "미결산", "임시",
        "suspense", "clearing", "temporary", "unallocated",
        "상품권", "대여금", "선급금",
        "정산 대기", "오류 정정", "단수 차이",
        "잡손실", "잡이익",
    ]

    leaks: list[dict[str, Any]] = []
    for kw in keywords:
        row = con.execute(f"""
            SELECT
                SUM(CASE WHEN is_fraud='true' THEN 1 ELSE 0 END),
                SUM(CASE WHEN is_anomaly='true' AND is_fraud!='true' THEN 1 ELSE 0 END),
                SUM(CASE WHEN is_fraud!='true' AND is_anomaly!='true' THEN 1 ELSE 0 END)
            FROM je
            WHERE LOWER(COALESCE(CAST(line_text AS VARCHAR),'')
                || ' ' || COALESCE(CAST(header_text AS VARCHAR),''))
                LIKE '%{kw.lower()}%'
        """).fetchone()

        f_cnt, a_cnt, n_cnt = row[0] or 0, row[1] or 0, row[2] or 0
        if n_cnt == 0 and (f_cnt + a_cnt) >= _MIN_COUNT:
            leaks.append({"keyword": kw, "fraud": f_cnt, "anomaly": a_cnt, "normal": 0})

    status = "FAIL" if len(leaks) > 0 else "PASS"
    return CheckResult(
        check_id="L1-03", tier=1,
        name="keyword leakage",
        status=status,
        expected="비정상 전용 키워드 = 0",
        actual=f"leakage {len(leaks)}건",
        detail={"leaks": leaks} if leaks else None,
        elapsed_ms=_elapsed(start),
    )


def l1_04_amount_range_separation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L1-04: 금액 구간 분리도 — 특정 구간에 비정상이 극단적으로 집중.

    금액을 10개 구간으로 나누고, 각 구간에서 비정상 비율이
    전체 평균의 7배 이상이면 금액만으로 분류 가능 = leakage.
    Why: 대규모 거래(10억+)는 실무에서도 감사 대상이므로 비정상 비율이 자연스럽게 높음.
         5x는 과민, 7x가 실무적 임계값.
    """
    start = _timer()

    # Why: debit_amount를 기준으로 구간 분석 (credit도 유사 분포)
    rows = con.execute("""
        SELECT amount_bucket,
            SUM(CASE WHEN is_fraud='true' OR is_anomaly='true' THEN 1 ELSE 0 END) AS abnormal,
            COUNT(*) AS total
        FROM (
            SELECT
                CASE
                    WHEN CAST(debit_amount AS DOUBLE) <= 0 THEN 'zero'
                    WHEN CAST(debit_amount AS DOUBLE) < 100000 THEN '<10만'
                    WHEN CAST(debit_amount AS DOUBLE) < 1000000 THEN '10만~100만'
                    WHEN CAST(debit_amount AS DOUBLE) < 10000000 THEN '100만~1000만'
                    WHEN CAST(debit_amount AS DOUBLE) < 100000000 THEN '1000만~1억'
                    WHEN CAST(debit_amount AS DOUBLE) < 1000000000 THEN '1억~10억'
                    WHEN CAST(debit_amount AS DOUBLE) < 10000000000 THEN '10억~100억'
                    ELSE '100억+'
                END AS amount_bucket,
                is_fraud, is_anomaly
            FROM je
            WHERE CAST(debit_amount AS DOUBLE) > 0
        )
        GROUP BY amount_bucket
    """).fetchall()

    # Why: 전체 비정상 비율 대비 5배 이상 집중된 구간 = 분리 위험
    total_all = sum(r[2] for r in rows)
    total_abn = sum(r[1] for r in rows)
    avg_rate = total_abn / total_all if total_all > 0 else 0

    separated: list[dict[str, Any]] = []
    for bucket, abn, total in rows:
        if total < 100:
            continue
        rate = abn / total if total > 0 else 0
        ratio = rate / avg_rate if avg_rate > 0 else 0
        if ratio >= 7.0:
            separated.append({
                "bucket": bucket, "abnormal_rate": f"{rate:.1%}",
                "avg_rate": f"{avg_rate:.1%}", "ratio": f"{ratio:.1f}x",
                "abnormal": abn, "total": total,
            })

    status = "FAIL" if len(separated) > 0 else "PASS"
    return CheckResult(
        check_id="L1-04", tier=1,
        name="amount range separation",
        status=status,
        expected="금액 구간별 비정상 비율 < 평균의 7배",
        actual=f"과집중 구간 {len(separated)}건",
        detail={"separated": separated} if separated else None,
        elapsed_ms=_elapsed(start),
    )


def l1_05_time_separation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L1-05: 시간대 분리도 — 특정 시간에 비정상 과집중.

    시간대별 비정상 비율이 전체 평균의 3배 이상이면
    시간 피처 하나로 분류 가능 = leakage.
    """
    start = _timer()

    rows = con.execute("""
        SELECT hour_val,
            SUM(CASE WHEN is_fraud='true' OR is_anomaly='true' THEN 1 ELSE 0 END) AS abnormal,
            COUNT(*) AS total
        FROM (
            SELECT CAST(SUBSTR(CAST(posting_date AS VARCHAR), 12, 2) AS INT) AS hour_val,
                is_fraud, is_anomaly
            FROM je
            WHERE LENGTH(CAST(posting_date AS VARCHAR)) >= 13
        )
        GROUP BY hour_val
        ORDER BY hour_val
    """).fetchall()

    total_all = sum(r[2] for r in rows)
    total_abn = sum(r[1] for r in rows)
    avg_rate = total_abn / total_all if total_all > 0 else 0

    separated: list[dict[str, Any]] = []
    for hour, abn, total in rows:
        if total < 100:
            continue
        rate = abn / total if total > 0 else 0
        ratio = rate / avg_rate if avg_rate > 0 else 0
        if ratio >= 3.0:
            separated.append({
                "hour": hour, "abnormal_rate": f"{rate:.1%}",
                "avg_rate": f"{avg_rate:.1%}", "ratio": f"{ratio:.1f}x",
            })

    status = "WARNING" if len(separated) > 3 else "PASS"
    return CheckResult(
        check_id="L1-05", tier=1,
        name="time separation",
        status=status,
        expected="시간대별 비정상 비율 < 평균의 3배 (3개 초과 시 WARNING)",
        actual=f"과집중 시간대 {len(separated)}건",
        detail={"separated": separated} if separated else None,
        elapsed_ms=_elapsed(start),
    )


def l1_06_extreme_values(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L1-06: 비현실적 극단값 — KRW 기준 비현실적 금액.

    KRW 단일 전표 금액이 1조원을 초과하면 비현실적.
    한국 중견 제조업 기준 단일 전표 최대 ~수천억이 한계.
    """
    start = _timer()

    threshold = 1_000_000_000_000  # 1조원

    extreme = con.execute(f"""
        SELECT COUNT(*),
            MAX(CAST(debit_amount AS DOUBLE)) AS max_dr,
            MAX(CAST(credit_amount AS DOUBLE)) AS max_cr
        FROM je
        WHERE CAST(debit_amount AS DOUBLE) > {threshold}
           OR CAST(credit_amount AS DOUBLE) > {threshold}
    """).fetchone()

    cnt = extreme[0] or 0
    max_dr = extreme[1] or 0
    max_cr = extreme[2] or 0

    status = "FAIL" if cnt > 0 else "PASS"
    return CheckResult(
        check_id="L1-06", tier=1,
        name="extreme values",
        status=status,
        expected=f"1조원 초과 금액 = 0",
        actual=f"{cnt}건 (max_dr={max_dr:.0e}, max_cr={max_cr:.0e})",
        elapsed_ms=_elapsed(start),
    )


def run_tier1(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 1 전체 실행."""
    return [
        l1_01_categorical_leakage(con),
        l1_02_gl_account_leakage(con),
        l1_03_keyword_leakage(con),
        l1_04_amount_range_separation(con),
        l1_05_time_separation(con),
        l1_06_extreme_values(con),
    ]
