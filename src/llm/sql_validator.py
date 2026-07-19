"""LLM 생성 SQL 검증기 — 5단계 보안 파이프라인.

Text-to-SQL에서 LLM이 생성한 SQL을 실행 전에 검증한다.
DML 차단, 테이블 화이트리스트, 서브쿼리 깊이 제한, 배치 격리 키 확인, LIMIT 자동 추가.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import duckdb

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────

# Why: Text-to-SQL은 분석용 core 테이블만 조회 허용
TABLE_WHITELIST: frozenset[str] = frozenset(
    {
        "general_ledger",
        "anomaly_flags",
        "anomaly_flag_summary",
        "benford_summary",
        "benford_digits",
        "trial_balance",
    }
)

MAX_SUBQUERY_DEPTH = 3
DEFAULT_LIMIT = 1000

# Why: 단어 경계(\b)로 문자열 상수 내 단어 오탐 방지
_DML_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b",
    re.IGNORECASE,
)

# Why: 문자열 리터럴을 제거해야 'UPDATE_REQUIRED' 같은 상수 오탐 방지
_STRING_LITERAL_PATTERN = re.compile(r"'[^']*'")

# Why: FROM/JOIN 절 뒤의 테이블명 추출
_TABLE_REF_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+(\w+)",
    re.IGNORECASE,
)

# Why: CTE 별칭은 테이블이 아니므로 화이트리스트 검사에서 제외
_CTE_ALIAS_PATTERN = re.compile(
    r"\bWITH\s+(\w+)\s+AS\b",
    re.IGNORECASE,
)

_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)


# ── 결과 모델 ────────────────────────────────────────────────


@dataclass(frozen=True)
class ValidationResult:
    """SQL 검증 결과."""

    is_valid: bool
    sql: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


# ── 검증 함수 ────────────────────────────────────────────────


def validate_sql(
    sql: str,
    conn: duckdb.DuckDBPyConnection | None = None,
    *,
    require_batch_filter: bool = True,
) -> ValidationResult:
    """5단계 SQL 검증 파이프라인.

    Args:
        sql: 검증 대상 SQL 문자열.
        conn: DuckDB 커넥션 (EXPLAIN 검증용, 없으면 건너뜀).
        require_batch_filter: upload_batch_id 포함 강제 여부.

    Returns:
        ValidationResult with is_valid, 정규화된 sql, errors, warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []
    normalized = sql.strip().rstrip(";")

    # Step 1: DML 차단 — 문자열 리터럴 제거 후 검사
    sql_without_strings = _STRING_LITERAL_PATTERN.sub("", normalized)
    if _DML_PATTERN.search(sql_without_strings):
        errors.append("DML/DDL 구문 감지 — SELECT만 허용")

    # Step 2: 테이블 화이트리스트 (CTE 별칭 제외)
    tables = {m.group(1).lower() for m in _TABLE_REF_PATTERN.finditer(normalized)}
    cte_aliases = {m.group(1).lower() for m in _CTE_ALIAS_PATTERN.finditer(normalized)}
    unauthorized = tables - TABLE_WHITELIST - cte_aliases
    if unauthorized:
        errors.append(f"비허용 테이블: {', '.join(sorted(unauthorized))}")

    # Step 3: 서브쿼리 깊이
    depth = _measure_subquery_depth(sql_without_strings)
    if depth > MAX_SUBQUERY_DEPTH:
        errors.append(f"서브쿼리 깊이 {depth} — 최대 {MAX_SUBQUERY_DEPTH}단계 허용")

    # Step 4: 배치 격리 키 확인
    if require_batch_filter and "upload_batch_id" not in normalized.lower():
        errors.append("upload_batch_id 조건 누락 — 배치 격리 필수")

    # Step 5: LIMIT 자동 추가
    if not _LIMIT_PATTERN.search(normalized):
        normalized = f"{normalized}\nLIMIT {DEFAULT_LIMIT}"
        warnings.append(f"LIMIT {DEFAULT_LIMIT} 자동 추가")

    # Step 6 (선택): EXPLAIN 문법 검증
    if conn is not None and not errors:
        explain_err = _explain_check(conn, normalized)
        if explain_err:
            errors.append(f"SQL 문법 오류: {explain_err}")

    return ValidationResult(
        is_valid=len(errors) == 0,
        sql=normalized,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


# ── 내부 헬퍼 ────────────────────────────────────────────────


def _measure_subquery_depth(sql: str) -> int:
    """괄호 중첩 내 SELECT 키워드로 서브쿼리 깊이 측정."""
    max_depth = 0
    # Why: 괄호 진입 시 SELECT가 있으면 서브쿼리로 카운트
    tokens = re.split(r"(\(|\))", sql)
    paren_depth = 0
    for token in tokens:
        if token == "(":
            paren_depth += 1
        elif token == ")":
            paren_depth = max(0, paren_depth - 1)
        elif paren_depth > 0 and re.search(r"\bSELECT\b", token, re.IGNORECASE):
            max_depth = max(max_depth, paren_depth)
    return max_depth


def _explain_check(conn: duckdb.DuckDBPyConnection, sql: str) -> str | None:
    """EXPLAIN으로 SQL 문법 검증. 오류 시 메시지 반환.

    Why: ? 플레이스홀더가 있으면 DuckDB EXPLAIN이 파라미터 미제공 오류를 발생시킨다.
    플레이스홀더를 더미값('__placeholder__')으로 치환 후 EXPLAIN 실행.
    """
    explain_sql = sql.replace("?", "'__placeholder__'")
    try:
        conn.execute(f"EXPLAIN {explain_sql}")
        return None
    except duckdb.Error as e:
        return str(e)
