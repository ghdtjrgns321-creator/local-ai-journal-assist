"""DB 레이어 public API.

Usage:
    from src.db import get_connection, close_connection
    from src.db import GENERAL_LEDGER_COLUMNS, initialize_schema
    from src.db import execute_preset, QueryNotFoundError
    from src.db import load_all, LoadResult
"""

from src.db.connection import close_connection, get_connection
from src.db.loader import LoadResult, load_all
from src.db.queries import (
    PRESET_QUERIES,
    QueryExecutionError,
    QueryNotFoundError,
    execute_preset,
)
from src.db.schema import (
    ANOMALY_FLAGS_COLUMNS,
    BENFORD_DIGITS_COLUMNS,
    BENFORD_SUMMARY_COLUMNS,
    GENERAL_LEDGER_COLUMNS,
    SCHEMA_DDL,
    initialize_schema,
)

__all__ = [
    "get_connection",
    "close_connection",
    "load_all",
    "LoadResult",
    "initialize_schema",
    "SCHEMA_DDL",
    "GENERAL_LEDGER_COLUMNS",
    "ANOMALY_FLAGS_COLUMNS",
    "BENFORD_SUMMARY_COLUMNS",
    "BENFORD_DIGITS_COLUMNS",
    "execute_preset",
    "PRESET_QUERIES",
    "QueryNotFoundError",
    "QueryExecutionError",
]
