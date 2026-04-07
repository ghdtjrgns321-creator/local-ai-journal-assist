"""전기 데이터 로더 — Layer D(전기 대비 변동 탐지)의 비교 기준 생성.

Why: 전기 원장 전체를 메모리에 올리지 않고,
     DuckDB GROUP BY 집계만 가져와서 비교 기준(PriorSummary)으로 사용.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from src.company.models import EngagementProfile, EngagementStatus
from src.company.repository import CompanyRepository
from src.db.queries import attached_engagement

logger = logging.getLogger(__name__)


# ── 데이터 모델 ─────────────────────────────────────────────


@dataclass(frozen=True)
class PriorSummary:
    """전기 집계 결과 — 변동 탐지 룰의 비교 기준.

    Why: 전기 원장 전체를 메모리에 올리지 않고,
         DuckDB GROUP BY 집계만 가져와서 비교 기준으로 사용.
    """

    # D01용: {gl_account: {"total_amount": float, "count": int, "avg_amount": float}}
    account_aggregates: dict[str, dict[str, float]]

    # D02용: {gl_account: {1: ratio, 2: ratio, ..., 12: ratio}}
    #   ratio = month_amount / annual_total (확률분포, 합=1.0)
    monthly_patterns: dict[str, dict[int, float]]

    prior_total_rows: int
    prior_fiscal_year: int


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
    candidates = [
        e for e in engagements
        if e.fiscal_year == current_fiscal_year - 1
    ]
    if not candidates:
        return None

    # Why: COMPLETED > IN_PROGRESS > DRAFT 순 신뢰도.
    #      ARCHIVED 등 비교 기준으로 부적절한 상태는 제외.
    _TRUSTED = (
        EngagementStatus.COMPLETED,
        EngagementStatus.IN_PROGRESS,
        EngagementStatus.DRAFT,
    )
    for status in _TRUSTED:
        match = next((e for e in candidates if e.status == status), None)
        if match:
            return match
    return None


# ── 전기 데이터 로딩 ────────────────────────────────────────


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
        # Why: alias는 attached_engagement()의 re.sub 정제를 거쳐 반환됨.
        #      DuckDB 스키마 접두사는 파라미터 바인딩 불가 → sanitize 완료된 alias만 f-string 삽입.
        with attached_engagement(conn, abs_path, "prior") as alias:
            # Why: 빈 테이블에서 GROUP BY 집계해도 의미 없음 — 조기 반환
            total_rows = conn.execute(
                f"SELECT COUNT(*) FROM {alias}.general_ledger"
            ).fetchone()[0]

            if total_rows == 0:
                logger.info("전기 general_ledger 빈 테이블 — Layer D 스킵")
                return None

            # D01용: 계정별 집계
            agg_df = conn.execute(f"""
                SELECT gl_account,
                       SUM(debit_amount + credit_amount) AS total_amount,
                       COUNT(*)                          AS count,
                       AVG(debit_amount + credit_amount) AS avg_amount
                FROM {alias}.general_ledger
                GROUP BY gl_account
            """).fetchdf()

            # D02용: 계정×월별 금액 + 연간 합계 대비 비율
            # Why: SQL NULLIF → DB에서 NULL 반환 → pandas fetchdf()가 NaN으로 변환.
            #      파이썬 float() 변환 전 pd.isna() 필터링 필수.
            monthly_df = conn.execute(f"""
                SELECT m.gl_account,
                       m.month,
                       m.month_amount / NULLIF(a.annual_total, 0) AS ratio
                FROM (
                    SELECT gl_account,
                           fiscal_period                     AS month,
                           SUM(debit_amount + credit_amount) AS month_amount
                    FROM {alias}.general_ledger
                    GROUP BY gl_account, fiscal_period
                ) m
                JOIN (
                    SELECT gl_account,
                           SUM(debit_amount + credit_amount) AS annual_total
                    FROM {alias}.general_ledger
                    GROUP BY gl_account
                ) a ON m.gl_account = a.gl_account
            """).fetchdf()

        # dict 변환: account_aggregates
        account_agg = {}
        for _, row in agg_df.iterrows():
            account_agg[row["gl_account"]] = {
                "total_amount": float(row["total_amount"]),
                "count": int(row["count"]),
                "avg_amount": float(row["avg_amount"]),
            }

        # dict 변환: monthly_patterns
        monthly_patterns: dict[str, dict[int, float]] = {}
        for _, row in monthly_df.iterrows():
            acct = row["gl_account"]
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
