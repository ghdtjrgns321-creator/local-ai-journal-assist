"""Validation 패키지 — DataFrame 계층적 데이터 검증 (L1 구조 → L2 회계 → L3 통계).

사용법:
    from src.validation import validate_schema, validate_statistics, generate_report

    schema_result = validate_schema(df)
    accounting_result = validate_accounting(df)
    statistical_result = validate_statistics(df)
    report = generate_report(df, schema_result, accounting_result)
"""

from src.validation.accounting_validator import validate_accounting
from src.validation.models import (
    AccountingResult,
    AccountStats,
    BenfordResult,
    DistributionStats,
    MonthlyVolatility,
    SchemaResult,
    StatisticalResult,
    TemporalPatternStats,
    ValidationReport,
)
from src.validation.models import ReconciliationItem, ReconciliationResult
from src.validation.report_generator import generate_report, report_to_dict
from src.validation.schema_validator import validate_schema
from src.validation.statistical_validator import validate_statistics
from src.validation.tb_reconciliation import (
    build_trial_balance,
    validate_tb_reconciliation,
)

__all__ = [
    "AccountingResult",
    "AccountStats",
    "BenfordResult",
    "DistributionStats",
    "MonthlyVolatility",
    "SchemaResult",
    "StatisticalResult",
    "TemporalPatternStats",
    "ValidationReport",
    "generate_report",
    "report_to_dict",
    "validate_accounting",
    "validate_schema",
    "validate_statistics",
    "build_trial_balance",
    "validate_tb_reconciliation",
    "ReconciliationItem",
    "ReconciliationResult",
]
