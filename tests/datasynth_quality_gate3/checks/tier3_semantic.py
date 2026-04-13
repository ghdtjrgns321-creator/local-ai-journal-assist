"""Tier 3: 의미 정합성 — 적요↔GL, header↔GL 매핑 전수 검증."""
from __future__ import annotations

import time
from typing import Any

import duckdb

from ..models import CheckResult


def _timer() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


# Why: GL 대분류 CASE문 — 첫 자리 기준
_GL_CAT_EXPR = """
    CASE WHEN gl_account IS NULL OR gl_account = '' THEN 'NaN'
         WHEN gl_account[1] = '1' THEN '자산'
         WHEN gl_account[1] = '2' THEN '부채'
         WHEN gl_account[1] = '3' THEN '자본'
         WHEN gl_account[1] = '4' THEN '수익'
         WHEN gl_account[1] IN ('5','6') THEN '비용'
         ELSE '기타' END
"""


def _check_linetext_gl(
    con: duckdb.DuckDBPyConnection,
    check_id: str,
    keyword: str,
    expected_cats: list[str],
    fail_threshold: float = 15.0,
    warn_threshold: float = 5.0,
) -> CheckResult:
    """적요 키워드 → GL 대분류 일치율 체크."""
    start = _timer()

    cats_sql = ", ".join(f"'{c}'" for c in expected_cats + ["NaN"])
    row = con.execute(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN gl_cat NOT IN ({cats_sql}) THEN 1 ELSE 0 END) AS mismatch
        FROM (
            SELECT {_GL_CAT_EXPR} AS gl_cat
            FROM je
            WHERE line_text LIKE '%{keyword}%'
              AND line_text IS NOT NULL
        )
    """).fetchone()

    total = row[0] or 0
    mismatch = row[1] or 0
    pct = mismatch / total * 100 if total > 0 else 0

    if total == 0:
        status = "SKIP"
    elif pct <= warn_threshold:
        status = "PASS"
    elif pct <= fail_threshold:
        status = "WARNING"
    else:
        status = "FAIL"

    return CheckResult(
        check_id=check_id, tier=3,
        name=f'적요 "{keyword}" -> GL {"/".join(expected_cats)}',
        status=status,
        expected=f"불일치 <={warn_threshold}%: PASS, <={fail_threshold}%: WARNING",
        actual=f"{mismatch:,}/{total:,} ({pct:.1f}%)",
        detail={"keyword": keyword, "expected_gl": expected_cats, "mismatch_pct": round(pct, 2)},
        elapsed_ms=_elapsed(start),
    )


def _check_header_gl(
    con: duckdb.DuckDBPyConnection,
    check_id: str,
    keyword: str,
    required_cats: list[str],
    fail_threshold: float = 60.0,
    warn_threshold: float = 30.0,
) -> CheckResult:
    """header 키워드 → 전표 내 기대 GL 대분류 존재 여부."""
    start = _timer()

    cats_sql = ", ".join(f"'{c}'" for c in required_cats)

    row = con.execute(f"""
        WITH doc_cats AS (
            SELECT document_id,
                   LIST(DISTINCT {_GL_CAT_EXPR}) AS cats
            FROM je
            GROUP BY document_id
        ),
        target_docs AS (
            SELECT DISTINCT document_id
            FROM je
            WHERE header_text LIKE '%{keyword}%'
              AND header_text IS NOT NULL
        )
        SELECT
            COUNT(*) AS total,
            SUM(CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM UNNEST(dc.cats) AS t(cat)
                    WHERE t.cat IN ({cats_sql})
                ) THEN 1 ELSE 0 END) AS missing
        FROM target_docs td
        JOIN doc_cats dc ON td.document_id = dc.document_id
    """).fetchone()

    total = row[0] or 0
    missing = row[1] or 0
    pct = missing / total * 100 if total > 0 else 0

    if total == 0:
        status = "SKIP"
    elif pct <= warn_threshold:
        status = "PASS"
    elif pct <= fail_threshold:
        status = "WARNING"
    else:
        status = "FAIL"

    return CheckResult(
        check_id=check_id, tier=3,
        name=f'header "{keyword}" -> GL {"/".join(required_cats)} 존재',
        status=status,
        expected=f"미존재 <={warn_threshold}%: PASS, <={fail_threshold}%: WARNING",
        actual=f"{missing:,}/{total:,} ({pct:.1f}%)",
        detail={"keyword": keyword, "required_gl": required_cats, "missing_pct": round(pct, 2)},
        elapsed_ms=_elapsed(start),
    )


def r3_09_aggregate_linetext(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """R3-09: 21개 키워드 적요-GL 종합 불일치율."""
    start = _timer()

    # Why: 전수 검증에서 확인한 21개 키워드-기대GL 매핑
    rules = [
        ("매출채권", ["자산"]),
        ("매입채무", ["부채"]),
        ("급여", ["비용", "부채"]),
        ("감가상각", ["비용", "자산"]),
        ("이자 수익", ["수익", "자산"]),
        ("법인세", ["비용", "부채", "자산"]),
        ("퇴직", ["비용", "부채"]),
        ("임차료", ["비용"]),
        ("보험료", ["비용", "자산"]),
        ("광고", ["비용"]),
        ("대손", ["비용", "자산"]),
        ("배당", ["자본", "부채", "비용", "수익"]),
        ("리스", ["자산", "부채", "비용"]),
        ("재고", ["자산", "비용"]),
        ("원재료", ["자산", "비용"]),
        ("완제품", ["자산", "비용"]),
        ("미지급", ["부채"]),
        ("선수금", ["부채"]),
        ("선급", ["자산"]),
        ("차입금", ["부채"]),
        ("충당부채", ["부채"]),
    ]

    total_rows = 0
    total_mismatch = 0

    for keyword, expected_cats in rules:
        cats_sql = ", ".join(f"'{c}'" for c in expected_cats + ["NaN"])
        row = con.execute(f"""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN gl_cat NOT IN ({cats_sql}) THEN 1 ELSE 0 END)
            FROM (
                SELECT {_GL_CAT_EXPR} AS gl_cat
                FROM je WHERE line_text LIKE '%{keyword}%' AND line_text IS NOT NULL
            )
        """).fetchone()
        total_rows += row[0] or 0
        total_mismatch += row[1] or 0

    avg_pct = total_mismatch / total_rows * 100 if total_rows > 0 else 0

    return CheckResult(
        check_id="R3-09", tier=3,
        name="적요-GL 종합 불일치율 (21개 키워드)",
        status="PASS" if avg_pct <= 10 else ("WARNING" if avg_pct <= 20 else "FAIL"),
        expected="평균 <=10%: PASS, <=20%: WARNING",
        actual=f"{total_mismatch:,}/{total_rows:,} ({avg_pct:.1f}%)",
        detail={"total_keywords": 21, "weighted_avg_mismatch_pct": round(avg_pct, 2)},
        elapsed_ms=_elapsed(start),
    )


def run_tier3(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 3 전체 실행."""
    return [
        # 적요 → GL (R3-01 ~ R3-05)
        _check_linetext_gl(con, "R3-01", "매출채권", ["자산"]),
        _check_linetext_gl(con, "R3-02", "미지급", ["부채"]),
        _check_linetext_gl(con, "R3-03", "급여", ["비용", "부채"]),
        _check_linetext_gl(con, "R3-04", "감가상각", ["비용", "자산"]),
        # Why: "배당"은 배당금 수익(4xxx) 수취도 포함 → 수익도 기대GL에 포함
        _check_linetext_gl(con, "R3-05", "배당", ["자본", "부채", "비용", "수익"]),
        # header → GL (R3-06 ~ R3-08)
        _check_header_gl(con, "R3-06", "감가상각", ["비용"]),
        _check_header_gl(con, "R3-07", "자산손상", ["비용"]),
        _check_header_gl(con, "R3-08", "매출채권 회수", ["자산"]),
        # 종합 (R3-09)
        r3_09_aggregate_linetext(con),
    ]
