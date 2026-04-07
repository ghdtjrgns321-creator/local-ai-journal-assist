"""DuckDB 데이터베이스 레이어 — 커넥션·스키마·적재·쿼리."""

from src.db.connection import ConnectionManager, close_connection, get_connection
from src.db.loader import LoadResult, load_all
from src.db.queries import (
    QueryExecutionError,
    QueryNotFoundError,
    attached_engagement,
    compare_engagements,
    execute_preset,
    execute_write,
)
from src.db.schema import SCHEMA_DDL, initialize_schema

__all__ = [
    "ConnectionManager",
    "get_connection",
    "close_connection",
    "SCHEMA_DDL",
    "initialize_schema",
    "load_all",
    "LoadResult",
    "execute_preset",
    "execute_write",
    "attached_engagement",
    "compare_engagements",
    "QueryNotFoundError",
    "QueryExecutionError",
]
