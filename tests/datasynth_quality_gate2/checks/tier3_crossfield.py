"""Tier 3: 필드 간 현실성 검증.

단일 필드가 아닌 필드 조합이 현실적인지 검사.
실무에서 존재할 수 없는 조합이 있으면 비현실적 합성 데이터.
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


def l3_01_persona_gl_correlation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L3-01: 작성자 persona와 GL 상관관계.

    실무에서 junior는 경비/소모품(5xxx/6xxx), controller는 세금/결산(2xxx/9xxx).
    persona별 GL 분포가 완전 균일하면 비현실적.
    persona별 상위 GL 1자리 집중도(HHI)가 모두 < 0.15면 너무 분산.
    """
    start = _timer()

    rows = con.execute("""
        SELECT user_persona, gl_group, cnt FROM (
            SELECT user_persona,
                LEFT(CAST(gl_account AS VARCHAR), 1) AS gl_group,
                COUNT(*) AS cnt
            FROM je
            WHERE is_fraud != 'true' AND is_anomaly != 'true'
                AND user_persona IS NOT NULL AND user_persona != ''
                AND gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) != ''
            GROUP BY user_persona, LEFT(CAST(gl_account AS VARCHAR), 1)
        )
    """).fetchall()

    # Why: persona별 HHI 계산 — 분산이 너무 균일하면 비현실적
    from collections import defaultdict
    persona_totals: dict[str, int] = defaultdict(int)
    persona_gl: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for persona, gl, cnt in rows:
        persona_totals[persona] += cnt
        persona_gl[persona][gl] += cnt

    low_hhi_personas = []
    for persona, total in persona_totals.items():
        if total < 1000:
            continue
        shares = [(cnt / total) ** 2 for cnt in persona_gl[persona].values()]
        hhi = sum(shares)
        if hhi < 0.15:
            low_hhi_personas.append({"persona": persona, "hhi": f"{hhi:.3f}", "total": total})

    # Why: 모든 persona의 HHI가 0.15 미만이면 모두 동일 분포 = 비현실적
    status = "WARNING" if len(low_hhi_personas) == len([p for p in persona_totals if persona_totals[p] >= 1000]) else "PASS"
    return CheckResult(
        check_id="L3-01", tier=3, name="persona-GL correlation",
        status=status,
        expected="persona별 GL 집중도 차이 존재",
        actual=f"저집중도 persona {len(low_hhi_personas)}개",
        detail={"low_hhi": low_hhi_personas} if low_hhi_personas else None,
        elapsed_ms=_elapsed(start),
    )


def l3_02_process_time_correlation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L3-02: 프로세스-시간대 상관관계.

    실무: AP(매입)는 오전 집중, AR(매출)은 오후 집중, R2R(결산)은 월말 저녁.
    프로세스별 시간 분포가 완전 동일하면 비현실적.
    """
    start = _timer()

    rows = con.execute("""
        SELECT business_process, period,
            COUNT(*) AS cnt
        FROM (
            SELECT business_process,
                CASE
                    WHEN CAST(SUBSTR(CAST(posting_date AS VARCHAR), 12, 2) AS INT) BETWEEN 6 AND 11 THEN 'morning'
                    WHEN CAST(SUBSTR(CAST(posting_date AS VARCHAR), 12, 2) AS INT) BETWEEN 12 AND 17 THEN 'afternoon'
                    ELSE 'evening'
                END AS period
            FROM je
            WHERE is_fraud != 'true' AND is_anomaly != 'true'
                AND business_process IS NOT NULL AND business_process != ''
                AND LENGTH(CAST(posting_date AS VARCHAR)) >= 13
        )
        GROUP BY business_process, period
    """).fetchall()

    from collections import defaultdict
    bp_periods: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for bp, period, cnt in rows:
        bp_periods[bp][period] = cnt

    # Why: 각 프로세스의 morning/afternoon/evening 비율 계산
    # 모든 프로세스가 같은 비율이면 비현실적
    ratios = []
    for bp, periods in bp_periods.items():
        total = sum(periods.values())
        if total < 1000:
            continue
        morning_ratio = periods.get("morning", 0) / total
        ratios.append({"process": bp, "morning_ratio": morning_ratio, "total": total})

    if len(ratios) < 2:
        return CheckResult(
            check_id="L3-02", tier=3, name="process-time correlation",
            status="SKIP", expected="2개 프로세스+ 필요", actual=f"{len(ratios)}개",
            elapsed_ms=_elapsed(start),
        )

    morning_vals = [r["morning_ratio"] for r in ratios]
    spread = max(morning_vals) - min(morning_vals)

    status = "PASS" if spread > 0.05 else "WARNING"
    return CheckResult(
        check_id="L3-02", tier=3, name="process-time correlation",
        status=status,
        expected="프로세스별 시간대 분포 차이 > 5%p",
        actual=f"morning 비율 spread={spread:.1%}",
        detail={"ratios": ratios},
        elapsed_ms=_elapsed(start),
    )


def l3_03_recurring_pattern(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L3-03: 반복 거래 패턴 존재 여부.

    실무에서 급여, 감가상각, 임대료 등 매월 동일 금액의 recurring 전표가 존재.
    동일 (gl_account, debit_amount)가 3개월+ 반복되는 전표가 없으면 비현실적.
    """
    start = _timer()

    recurring = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT gl_account, CAST(debit_amount AS DOUBLE) AS amt,
                COUNT(DISTINCT fiscal_period) AS months
            FROM je
            WHERE is_fraud != 'true' AND is_anomaly != 'true'
                AND CAST(debit_amount AS DOUBLE) > 0
                AND LOWER(source) = 'recurring'
            GROUP BY gl_account, CAST(debit_amount AS DOUBLE)
            HAVING months >= 3
        )
    """).fetchone()[0]

    # Why: source='Recurring' 전표 중 3개월+ 반복되는 GL+금액 쌍이 있어야 현실적
    recurring_total = con.execute("""
        SELECT COUNT(*) FROM je WHERE source = 'Recurring'
    """).fetchone()[0]

    status = "PASS" if recurring > 0 else "WARNING"
    return CheckResult(
        check_id="L3-03", tier=3, name="recurring pattern",
        status=status,
        expected="3개월+ 반복 GL+금액 쌍 > 0",
        actual=f"recurring 패턴 {recurring}건 (total recurring={recurring_total:,})",
        elapsed_ms=_elapsed(start),
    )


def l3_04_normal_data_completeness(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """L3-04: 정상 데이터 완전성 — 필수 비즈니스 시나리오 존재 여부.

    정상 전표에 다음 시나리오가 모두 존재해야 현실적:
    - 소액 + 대액 (금액 다양성)
    - 모든 document_type (SA/KR/DR/HR/AA 등)
    - 모든 business_process (P2P/O2C/R2R/H2R 등)
    - 심야 전표 (소량이지만 존재해야 — 결산 마감 야근)
    """
    start = _timer()

    missing: list[str] = []

    # 모든 주요 doc_type이 정상에 있는지
    for dt in ["SA", "KR", "DR", "HR", "AA"]:
        cnt = con.execute(f"""
            SELECT COUNT(*) FROM je
            WHERE is_fraud != 'true' AND is_anomaly != 'true'
            AND document_type = '{dt}'
        """).fetchone()[0]
        if cnt == 0:
            missing.append(f"document_type={dt}")

    # 모든 주요 process가 정상에 있는지
    for bp in ["P2P", "O2C", "R2R", "H2R"]:
        cnt = con.execute(f"""
            SELECT COUNT(*) FROM je
            WHERE is_fraud != 'true' AND is_anomaly != 'true'
            AND business_process = '{bp}'
        """).fetchone()[0]
        if cnt == 0:
            missing.append(f"business_process={bp}")

    # 심야(22~06시) 정상 전표 존재
    night = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE is_fraud != 'true' AND is_anomaly != 'true'
        AND (CAST(SUBSTR(CAST(posting_date AS VARCHAR), 12, 2) AS INT) >= 22
            OR CAST(SUBSTR(CAST(posting_date AS VARCHAR), 12, 2) AS INT) < 6)
    """).fetchone()[0]
    if night == 0:
        missing.append("night_posting(22~06)")

    status = "PASS" if len(missing) == 0 else "FAIL"
    return CheckResult(
        check_id="L3-04", tier=3, name="normal data completeness",
        status=status,
        expected="필수 시나리오 누락 0",
        actual=f"누락 {len(missing)}건: {', '.join(missing)}" if missing else "모두 존재",
        elapsed_ms=_elapsed(start),
    )


def run_tier3(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 3 전체 실행."""
    return [
        l3_01_persona_gl_correlation(con),
        l3_02_process_time_correlation(con),
        l3_03_recurring_pattern(con),
        l3_04_normal_data_completeness(con),
    ]
