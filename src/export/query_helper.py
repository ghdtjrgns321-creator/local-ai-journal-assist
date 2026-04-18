"""WU-24 ExportFilter → SQL WHERE 변환 + 안전 쿼리 실행 헬퍼.

Why:
    Excel/PDF Exporter 모두 동일한 ``_build_where_clause``와 ``_safe_query``
    로직이 필요했다. 두 곳에 복붙하면 필터 필드 추가 시 한쪽만 수정해
    Excel/PDF 결과가 달라지는 불일치 버그가 발생할 위험이 있어 단일 모듈로 추출.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import duckdb
import pandas as pd

from src.export.models import ExportFilter

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def build_where_clause(
    filters: ExportFilter, batch_id: str
) -> tuple[str, list[Any]]:
    """ExportFilter → ``AND ...`` SQL 조각 + 파라미터 리스트.

    Why:
        general_ledger 쿼리에서 batch_id는 모든 호출에 공통이므로 항상 포함하고,
        사용자 필터(회사·프로세스·위험·날짜·문서유형)만 옵션으로 조립한다.
        DuckDB 파라미터 바인딩을 사용해 SQL Injection을 원천 차단한다.
    """
    clauses: list[str] = ["AND upload_batch_id = ?"]
    params: list[Any] = [batch_id]

    if filters.company_codes:
        placeholders = ",".join("?" * len(filters.company_codes))
        clauses.append(f"AND company_code IN ({placeholders})")
        params.extend(filters.company_codes)
    if filters.business_processes:
        placeholders = ",".join("?" * len(filters.business_processes))
        clauses.append(f"AND business_process IN ({placeholders})")
        params.extend(filters.business_processes)
    if filters.risk_levels:
        placeholders = ",".join("?" * len(filters.risk_levels))
        clauses.append(f"AND risk_level IN ({placeholders})")
        params.extend(filters.risk_levels)
    if filters.document_types:
        placeholders = ",".join("?" * len(filters.document_types))
        clauses.append(f"AND document_type IN ({placeholders})")
        params.extend(filters.document_types)
    if filters.date_from:
        clauses.append("AND posting_date >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("AND posting_date <= ?")
        params.append(filters.date_to)
    return " ".join(clauses), params


def safe_query(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any]
) -> pd.DataFrame:
    """쿼리 실패를 분류하여 graceful 처리 또는 상위 전파.

    Why:
        - CatalogException(테이블/컬럼 부재): 과거 배치·미실행 분석 등 정상 시나리오.
          빈 DataFrame을 반환해 보고서 생성을 계속한다.
        - IOException/ConnectionException(커넥션 단절): 비정상. 상위로 전파해
          모든 시트가 빈 보고서가 되는 것을 막는다 (사용자가 원인을 인지 가능).
        - 그 외 일반 예외: WARNING 로그 + 빈 DataFrame (보고서 자체는 살림).
    """
    try:
        return conn.execute(sql, params).df()
    except duckdb.CatalogException as exc:
        logger.warning("쿼리 대상 부재 (graceful): %s", exc)
        return pd.DataFrame()
    except (duckdb.IOException, duckdb.ConnectionException) as exc:
        # Why: 커넥션 레벨 오류는 모든 시트에 영향 → 상위로 전파해야 사용자가 인지.
        raise RuntimeError(f"DuckDB 연결 오류: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("쿼리 실패 (graceful): %s | SQL=%s", exc, sql[:120])
        return pd.DataFrame()


__all__ = ["build_where_clause", "safe_query"]
