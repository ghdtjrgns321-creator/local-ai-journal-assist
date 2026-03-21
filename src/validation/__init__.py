"""Validation 패키지 — DataFrame 계층적 데이터 검증 (L1 구조 → L2 회계 → L3 통계).

사용법:
    from src.validation import validate_schema, generate_report

    schema_result = validate_schema(df)
    report = generate_report(df, schema_result, accounting_result)
"""

from src.validation.accounting_validator import validate_accounting
from src.validation.models import AccountingResult, SchemaResult, ValidationReport
from src.validation.report_generator import generate_report, report_to_dict
from src.validation.schema_validator import validate_schema

__all__ = [
    "AccountingResult",
    "SchemaResult",
    "ValidationReport",
    "generate_report",
    "report_to_dict",
    "validate_accounting",
    "validate_schema",
]
