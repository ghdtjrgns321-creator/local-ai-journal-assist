"""L1+L2 검증 결과 종합 리포트 생성.

Why: schema_validator(L1) + accounting_validator(L2) 결과를
단일 ValidationReport로 병합하여 대시보드 Tab 1과 detection 게이트 역할.

EDA report.py(현황 요약)와 역할 구분:
- EDA quality_score: 결측률·중복률 기반 데이터 현황 품질
- validation_score: 스키마·회계 규칙 준수 품질
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.validation.models import (
    AccountingResult,
    SchemaResult,
    ValidationReport,
)

# ── 감점 가중치 상수 ──────────────────────────────────────────

_L1_CRITICAL_PENALTY = 50.0  # L1 치명적 에러 시 일괄 감점
_L1_WARNING_WEIGHT = 20.0  # 경고 비율 × 20 (cap 20)
_L2_BALANCE_WEIGHT = 15.0  # 불일치 전표 비율 × 15
_L2_DATE_PENALTY = 5.0  # 일자 불연속 시 고정 감점
_L2_DUPLICATE_WEIGHT = 10.0  # 중복 비율 × 10


# ── 퍼블릭 API ────────────────────────────────────────────────


def generate_report(
    df: pd.DataFrame,
    schema_result: SchemaResult,
    accounting_result: AccountingResult,
    *,
    source_file: str | None = None,
) -> ValidationReport:
    """L1+L2 검증 결과를 종합하여 ValidationReport 생성.

    Parameters
    ----------
    df : 검증 대상 DataFrame
    schema_result : L1 구조 검증 결과
    accounting_result : L2 회계 검증 결과
    source_file : 원본 파일명 (파이프라인에서 전달)
    """
    total_rows = len(df)

    # Why: document_id가 없는 DataFrame도 방어 (전표 단위 산출 불가 시 0)
    total_documents = df["document_id"].nunique() if "document_id" in df.columns else 0

    valid_rows = _compute_valid_rows(total_rows, schema_result)
    valid_documents = _compute_valid_documents(total_documents, accounting_result)
    accounting_issues = _build_accounting_issues(accounting_result)
    total_cols = len(df.columns)

    score = _calculate_validation_score(
        schema_result,
        accounting_result,
        total_rows,
        total_documents,
        total_cols,
    )

    return ValidationReport(
        total_rows=total_rows,
        total_documents=total_documents,
        valid_rows=valid_rows,
        valid_documents=valid_documents,
        schema_errors=list(schema_result.errors),
        schema_warnings=list(schema_result.warnings),
        accounting_issues=accounting_issues,
        statistical_flags=[],
        validation_score=score,
        is_pipeline_ready=schema_result.is_valid,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_file=source_file,
        date_range=_compute_date_range(df),
    )


def report_to_dict(report: ValidationReport) -> dict:
    """ValidationReport → JSON-serializable dict 변환."""
    raw = asdict(report)
    return _sanitize(raw)


# ── 프라이빗 헬퍼 ─────────────────────────────────────────────


def _compute_valid_rows(total_rows: int, schema_result: SchemaResult) -> int:
    """L1 통과 시 total_rows, 실패 시 failure_count 합산 차감 (근사치)."""
    if schema_result.is_valid:
        return total_rows
    # Why: 한 행에 여러 에러 가능 → 과소 추정될 수 있으나, detection 전 게이트 용도로 충분
    failure_sum = sum(e.get("failure_count", 0) for e in schema_result.errors)
    return max(0, total_rows - failure_sum)


def _compute_valid_documents(
    total_documents: int,
    accounting_result: AccountingResult,
) -> int:
    """전체 전표 수에서 대차불일치 전표 수 차감."""
    return max(0, total_documents - len(accounting_result.unbalanced_docs))


def _build_accounting_issues(result: AccountingResult) -> list[dict]:
    """AccountingResult → 표준화된 이슈 목록 변환.

    각 dict: {check_type, severity, message, detail}
    """
    issues: list[dict] = []

    if not result.balance_check:
        issues.append(
            {
                "check_type": "balance",
                "severity": "error",
                "message": f"대차불일치 {len(result.unbalanced_docs)}건, "
                f"차이 {result.balance_diff:,.2f}",
                "detail": {
                    "unbalanced_docs": result.unbalanced_docs,
                    "balance_diff": result.balance_diff,
                },
            }
        )

    if not result.date_continuity:
        issues.append(
            {
                "check_type": "date_continuity",
                "severity": "warning",
                "message": f"영업일 누락 {len(result.missing_dates)}건",
                "detail": {"missing_dates": result.missing_dates},
            }
        )

    if result.duplicate_entries > 0:
        issues.append(
            {
                "check_type": "duplicate",
                "severity": "warning",
                "message": f"완전 중복 행 {result.duplicate_entries}건",
                "detail": {"duplicate_count": result.duplicate_entries},
            }
        )

    return issues


def _calculate_validation_score(
    schema_result: SchemaResult,
    accounting_result: AccountingResult,
    total_rows: int,
    total_documents: int,
    total_columns: int,
) -> float:
    """비율 기반 감점 → 0~100 클리핑.

    Why: 에러 수 × 고정 가중치는 에러 다수 시 음수 가능 → 비율 기반으로 상한 보장.
    """
    score = 100.0

    # L1: 치명적 에러 일괄 감점
    if not schema_result.is_valid:
        score -= _L1_CRITICAL_PENALTY

    # L1: 경고 비율 감점 (컬럼 대비)
    if total_columns > 0:
        warning_rate = min(len(schema_result.warnings) / total_columns, 1.0)
        score -= warning_rate * _L1_WARNING_WEIGHT

    # L2: 대차불일치 비율 감점
    if total_documents > 0:
        balance_rate = min(
            len(accounting_result.unbalanced_docs) / total_documents,
            1.0,
        )
        score -= balance_rate * _L2_BALANCE_WEIGHT

    # L2: 일자 불연속 고정 감점
    if not accounting_result.date_continuity:
        score -= _L2_DATE_PENALTY

    # L2: 중복 비율 감점
    if total_rows > 0:
        dup_rate = min(accounting_result.duplicate_entries / total_rows, 1.0)
        score -= dup_rate * _L2_DUPLICATE_WEIGHT

    return max(0.0, min(100.0, round(score, 1)))


def _compute_date_range(df: pd.DataFrame) -> tuple[str, str] | None:
    """posting_date min/max 추출. 0행·전체 NaT·컬럼 미존재 시 None.

    Why: type_caster 미경유 경로에서도 안전하도록 pd.to_datetime 방어 적용.
    """
    if "posting_date" not in df.columns:
        return None
    dates = pd.to_datetime(df["posting_date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return (dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d"))


def _sanitize(obj):
    """numpy/pandas 타입 → Python 네이티브 재귀 변환.

    Why: json.dumps 시 numpy int64/float64 → TypeError 방지.
    TODO(Phase 1b): src/utils/serialization.py로 EDA profiler와 통합 추출.
    """
    if isinstance(obj, dict):
        return {_sanitize(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        sanitized = [_sanitize(item) for item in obj]
        return tuple(sanitized) if isinstance(obj, tuple) else sanitized
    if isinstance(obj, np.ndarray):
        return _sanitize(obj.tolist())
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj
