"""전기 데이터 로더 — Layer D(전기 대비 변동 탐지)의 비교 기준 생성.

Why: 전기 원장 전체를 메모리에 올리지 않고,
     DuckDB GROUP BY 집계만 가져와서 비교 기준(PriorSummary)으로 사용.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from src.company.models import EngagementProfile, EngagementStatus
from src.company.repository import CompanyRepository
from src.db.queries import attached_engagement
from src.detection.variance_rules import _normalise_key_part

logger = logging.getLogger(__name__)

# Why: COMPLETED > IN_PROGRESS > DRAFT 순 신뢰도.
#      ARCHIVED 등 비교 기준으로 부적절한 상태는 제외.
_TRUSTED_STATUSES = (
    EngagementStatus.COMPLETED,
    EngagementStatus.IN_PROGRESS,
    EngagementStatus.DRAFT,
)


# ── 데이터 모델 ─────────────────────────────────────────────


@dataclass(frozen=True)
class PriorSummary:
    """전기 집계 결과 — 변동 탐지 룰의 비교 기준.

    Why: 전기 원장 전체를 메모리에 올리지 않고,
         DuckDB GROUP BY 집계만 가져와서 비교 기준으로 사용.
    """

    # D01용: {gl_account: {...}} or {"company_code::gl_account": {...}}
    account_aggregates: dict[str, dict[str, float]]

    # D02용: {gl_account: {1: ratio, 2: ratio, ..., 12: ratio}}
    #   ratio = month_amount / annual_total (확률분포, 합=1.0)
    monthly_patterns: dict[str, dict[int, float]]

    prior_total_rows: int
    prior_fiscal_year: int


def _prior_key(row: pd.Series) -> str:
    """Return the same company/account key shape used by Layer D rules."""

    account = _normalise_key_part(row["gl_account"])
    if "company_code" in row:
        return f"{_normalise_key_part(row['company_code'])}::{account}"
    return account


# ── 전기 engagement 탐색 ────────────────────────────────────


def find_prior_engagement(
    repo: CompanyRepository,
    company_id: str,
    current_fiscal_year: int,
) -> EngagementProfile | None:
    """직전 연도 engagement 탐색.

    Why: 동일 회사의 fiscal_year == current - 1인 engagement 중
         가장 신뢰도 높은 것(completed > in_progress > 기타)을 반환.
    """
    engagements = repo.list_engagements(company_id)
    candidates = [e for e in engagements if e.fiscal_year == current_fiscal_year - 1]
    if not candidates:
        return None

    for status in _TRUSTED_STATUSES:
        match = next((e for e in candidates if e.status == status), None)
        if match:
            return match
    return None


def find_past_engagements(
    repo: CompanyRepository,
    company_id: str,
    current_fiscal_year: int,
    *,
    max_years: int = 5,
) -> list[EngagementProfile]:
    """당기 이전 engagement 를 연도별 1개씩, 최근 연도부터 ``max_years`` 개 반환.

    Why: 거래처 첫등장/휴면재활성은 직전 연도 하나로는 부족하다(휴면 판정에 직전+그 이전
         연도가 모두 필요). Layer D 의 단수 탐색과 달리 과거 여러 해를 모은다.
    """
    engagements = [
        e
        for e in repo.list_engagements(company_id)
        if e.fiscal_year is not None and e.fiscal_year < current_fiscal_year
    ]
    if not engagements:
        return []

    best_by_year: dict[int, EngagementProfile] = {}
    for status in _TRUSTED_STATUSES:
        for engagement in engagements:
            if engagement.status == status:
                best_by_year.setdefault(int(engagement.fiscal_year), engagement)
    return [best_by_year[y] for y in sorted(best_by_year, reverse=True)[:max_years]]


# Why: find_prior_engagement 의 지역 상수와 동일 정책 — 두 탐색이 같은 신뢰 순서를 쓴다.
# ── 전기 데이터 로딩 ────────────────────────────────────────


@contextmanager
def engagement_query_scope(
    conn: duckdb.DuckDBPyConnection,
    db_path: Path,
    alias_hint: str,
) -> Generator[tuple[duckdb.DuckDBPyConnection, str], None, None]:
    """(조회 커넥션, general_ledger 참조) 제공 — ATTACH 충돌을 우회한다.

    Why: DuckDB는 한 프로세스에서 같은 파일을 서로 다른 핸들로 열지 못한다. 연도 전환
         후에도 ConnectionManager 캐시에 과거 연도 커넥션이 남아 있으면 READ_ONLY
         ATTACH가 "Unique file handle conflict"로 실패하고, 그 예외가 호출부의
         except에 삼켜져 Layer D가 통째로 조용히 스킵된다.
         이미 열린 커넥션이 있으면 ATTACH 없이 그 커넥션에서 직접 조회한다 — 여기
         쿼리들은 과거 DB 단독 집계라 당기 DB와의 JOIN이 필요 없다.
    """
    from src.db.connection import get_connection_manager  # noqa: PLC0415 — 순환 import 방지

    cached = get_connection_manager().peek(db_path)
    if cached is not None:
        logger.info("과거 DB가 이미 열려 있어 캐시 커넥션으로 직접 조회: %s", db_path)
        yield cached, "general_ledger"
        return

    # Why: alias는 attached_engagement()의 re.sub 정제를 거쳐 반환됨.
    #      DuckDB 스키마 접두사는 파라미터 바인딩 불가 → sanitize 완료된 alias만 f-string 삽입.
    with attached_engagement(conn, db_path, alias_hint) as alias:
        yield conn, f"{alias}.general_ledger"


def load_partner_years(
    conn: duckdb.DuckDBPyConnection,
    engagement_db_paths: dict[int, Path],
) -> dict[int, set[str]]:
    """과거 engagement DB 들에서 {회계연도: 등장 거래처 집합} 을 로드.

    Why: 연도별 engagement 격리(RC-3) 탓에 당기 원장만으로는 "작년에 없던 거래처"를
         판정할 수 없다. 원장 전체가 아니라 DISTINCT trading_partner 만 ATTACH 로 읽는다.
         DB 별 실패는 해당 연도만 건너뛴다 — 한 해가 깨져도 나머지 비교는 유효하다.
    """
    partner_years: dict[int, set[str]] = {}
    for fiscal_year, db_path in engagement_db_paths.items():
        abs_path = Path(db_path).resolve()
        if not abs_path.exists():
            logger.warning("과거 DB 파일 미존재: %s", abs_path)
            continue
        try:
            with engagement_query_scope(conn, abs_path, f"past_{int(fiscal_year)}") as (
                query,
                past_gl,
            ):
                columns = {
                    col[0] for col in query.execute(f"SELECT * FROM {past_gl} LIMIT 0").description
                }
                if "trading_partner" not in columns:
                    logger.info("과거 DB %s 에 trading_partner 부재 — 스킵", fiscal_year)
                    continue
                rows = query.execute(f"""
                    SELECT DISTINCT trading_partner
                    FROM {past_gl}
                    WHERE trading_partner IS NOT NULL
                      AND TRIM(CAST(trading_partner AS VARCHAR)) <> ''
                """).fetchall()
            partners = {str(row[0]).strip() for row in rows}
            if partners:
                partner_years[int(fiscal_year)] = partners
        except Exception:
            logger.warning("과거 거래처 로드 실패 — %s 스킵", fiscal_year, exc_info=True)
    return partner_years


def load_prior_summary(
    conn: duckdb.DuckDBPyConnection,
    prior_db_path: Path,
    prior_fiscal_year: int,
) -> PriorSummary | None:
    """전기 DB에서 계정별 집계 + 월별 분포를 로드.

    Why: DuckDB ATTACH READ_ONLY로 전기 DB에 접근하여
         GROUP BY 집계만 가져옴 (전체 원장을 메모리에 올리지 않음).
    """
    # Why: RC-3 교훈 — Streamlit CWD에서 상대 경로 ATTACH 시 DB 미발견 가능
    abs_path = Path(prior_db_path).resolve()

    if not abs_path.exists():
        logger.warning("전기 DB 파일 미존재: %s", abs_path)
        return None

    try:
        with engagement_query_scope(conn, abs_path, "prior") as (query, prior_gl):
            # Why: 빈 테이블에서 GROUP BY 집계해도 의미 없음 — 조기 반환
            total_rows = query.execute(f"SELECT COUNT(*) FROM {prior_gl}").fetchone()[0]

            if total_rows == 0:
                logger.info("전기 general_ledger 빈 테이블 — Layer D 스킵")
                return None

            columns = {
                col[0] for col in query.execute(f"SELECT * FROM {prior_gl} LIMIT 0").description
            }
            has_company_code = "company_code" in columns

            # D01용: 계정별 집계. company_code가 있으면 회사별 계정으로 비교한다.
            d01_select = "company_code, gl_account" if has_company_code else "gl_account"
            d01_group_by = "company_code, gl_account" if has_company_code else "gl_account"
            agg_df = query.execute(f"""
                SELECT {d01_select},
                       SUM(debit_amount + credit_amount) AS total_amount,
                       COUNT(*)                          AS count,
                       AVG(debit_amount + credit_amount) AS avg_amount
                FROM {prior_gl}
                GROUP BY {d01_group_by}
            """).fetchdf()

            # D02용: 계정×월별 금액 + 연간 합계 대비 비율
            # Why: SQL NULLIF → DB에서 NULL 반환 → pandas fetchdf()가 NaN으로 변환.
            #      파이썬 float() 변환 전 pd.isna() 필터링 필수.
            d02_select = "company_code, gl_account" if has_company_code else "gl_account"
            d02_group_by = "company_code, gl_account" if has_company_code else "gl_account"
            d02_selected_columns = ", ".join(f"m.{col.strip()}" for col in d02_select.split(","))
            d02_join = (
                "m.company_code = a.company_code AND m.gl_account = a.gl_account"
                if has_company_code
                else "m.gl_account = a.gl_account"
            )
            monthly_df = query.execute(f"""
                SELECT {d02_selected_columns},
                       m.month,
                       m.month_amount / NULLIF(a.annual_total, 0) AS ratio
                FROM (
                    SELECT {d02_select},
                           fiscal_period                     AS month,
                           SUM(debit_amount + credit_amount) AS month_amount
                    FROM {prior_gl}
                    GROUP BY {d02_group_by}, fiscal_period
                ) m
                JOIN (
                    SELECT {d02_select},
                           SUM(debit_amount + credit_amount) AS annual_total
                    FROM {prior_gl}
                    GROUP BY {d02_group_by}
                ) a ON {d02_join}
            """).fetchdf()

        # dict 변환: account_aggregates
        account_agg = {}
        for _, row in agg_df.iterrows():
            key = _prior_key(row)
            account_agg[key] = {
                "total_amount": float(row["total_amount"]),
                "count": int(row["count"]),
                "avg_amount": float(row["avg_amount"]),
            }

        # dict 변환: monthly_patterns
        monthly_patterns: dict[str, dict[int, float]] = {}
        for _, row in monthly_df.iterrows():
            acct = _prior_key(row)
            month = int(row["month"])
            ratio = 0.0 if pd.isna(row["ratio"]) else float(row["ratio"])
            monthly_patterns.setdefault(acct, {})[month] = ratio

        return PriorSummary(
            account_aggregates=account_agg,
            monthly_patterns=monthly_patterns,
            prior_total_rows=int(total_rows),
            prior_fiscal_year=prior_fiscal_year,
        )

    except Exception:
        logger.warning("전기 데이터 로드 실패 — Layer D 스킵", exc_info=True)
        return None
