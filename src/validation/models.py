"""Validation 공용 데이터 모델 — L1/L2/L3 검증 결과 구조체.

Why: schema_validator → accounting_validator → statistical_validator → report_generator 간 데이터 계약.
JSON 직렬화 가능하도록 numpy 타입 대신 Python 네이티브만 사용.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchemaResult:
    """L1 구조 검증 결과 — schema_validator.validate_schema()가 반환.

    is_valid=False이면 파이프라인 중단 (필수 컬럼 누락/타입 불일치).
    is_valid=True + warnings이면 계속 진행 + 경고 누적.
    """

    is_valid: bool
    errors: list[dict] = field(default_factory=list)
    # [{column: str, check: str, failure_count: int}]
    warnings: list[dict] = field(default_factory=list)
    # [{column: str, issue: str, detail: str}]
    column_stats: dict[str, dict] = field(default_factory=dict)
    # {col_name: {dtype: str, null_rate: float, unique_count: int, total_count: int}}


@dataclass
class AccountingResult:
    """L2 회계 검증 결과 — accounting_validator.validate_accounting()가 반환."""

    balance_check: bool = True
    balance_diff: float = 0.0
    unbalanced_docs: list[str] = field(default_factory=list)
    date_continuity: bool = True
    missing_dates: list[str] = field(default_factory=list)
    duplicate_entries: int = 0


@dataclass
class ValidationReport:
    """L1+L2 종합 리포트 — report_generator.generate_report()가 반환.

    validation_score: 규칙 준수 품질 (0~100). EDA quality_score(현황 품질)와 구분.
    is_pipeline_ready: L1 치명적 에러 0건이면 True → detection 진행 가능.
    """

    total_rows: int
    total_documents: int
    valid_rows: int
    valid_documents: int
    schema_errors: list[dict] = field(default_factory=list)
    schema_warnings: list[dict] = field(default_factory=list)
    accounting_issues: list[dict] = field(default_factory=list)
    # [{check_type: str, severity: str, message: str, detail: dict | None}]
    statistical_flags: list[dict] = field(default_factory=list)
    # Phase 2: [{month: str, volatility: float, flag: str}]
    validation_score: float = 100.0
    is_pipeline_ready: bool = True
    generated_at: str = ""
    source_file: str | None = None
    date_range: tuple[str, str] | None = None
