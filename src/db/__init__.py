"""DuckDB 데이터베이스 레이어 — 커넥션·스키마·적재·쿼리."""

from src.db.audit_log import record_event
from src.db.connection import ConnectionManager, close_connection, get_connection
from src.db.loader import LoadResult, load_all
from src.db.loader_supplementary import load_supplementary
from src.db.migration import CURRENT_SCHEMA_VERSION, run_migrations
from src.db.queries import (
    QueryExecutionError,
    QueryNotFoundError,
    attached_engagement,
    compare_engagements,
    execute_preset,
    execute_write,
)
from src.db.schema import SCHEMA_DDL, initialize_schema
from src.db.schema_supplementary import SUPPLEMENTARY_DDL, initialize_supplementary_schema

__all__ = [
    "ConnectionManager",
    "get_connection",
    "close_connection",
    "CURRENT_SCHEMA_VERSION",
    "run_migrations",
    "SCHEMA_DDL",
    "SUPPLEMENTARY_DDL",
    "initialize_schema",
    "initialize_supplementary_schema",
    "load_all",
    "load_supplementary",
    "LoadResult",
    "execute_preset",
    "execute_write",
    "attached_engagement",
    "compare_engagements",
    "QueryNotFoundError",
    "QueryExecutionError",
    "record_event",
]
