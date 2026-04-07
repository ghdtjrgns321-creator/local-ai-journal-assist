"""report_generator 단위 테스트 — L1+L2 종합 리포트 생성 검증.

정상 동작, is_pipeline_ready, validation_score,
accounting_issues 구조, 직렬화, edge case (빈 DataFrame, NaT).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.validation.models import AccountingResult, SchemaResult, ValidationReport
from src.validation.report_generator import generate_report, report_to_dict


# ── 1. 정상 동작 ──────────────────────────────────────────────


class TestNormalOperation:
    """L1+L2 모두 통과 시 정상 리포트 생성."""

    def test_all_pass(self, vr_sample_df, vr_schema_valid, vr_accounting_clean):
        """#1: L1+L2 모두 통과 → valid_rows == total_rows, score == 100."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_clean)

        assert report.total_rows == 10
        assert report.valid_rows == 10
        assert report.total_documents == 3
        assert report.valid_documents == 3
        assert report.validation_score == 100.0
        assert report.is_pipeline_ready is True
        assert report.schema_errors == []
        assert report.accounting_issues == []

    def test_source_file_passed(self, vr_sample_df, vr_schema_valid, vr_accounting_clean):
        """#15: source_file 전달 시 리포트에 포함."""
        report = generate_report(
            vr_sample_df, vr_schema_valid, vr_accounting_clean,
            source_file="datasynth.csv",
        )
        assert report.source_file == "datasynth.csv"


# ── 2. is_pipeline_ready 판정 ─────────────────────────────────


class TestPipelineReady:
    """L1 치명적 에러 → is_pipeline_ready=False."""

    def test_l1_critical_error(self, vr_sample_df, vr_schema_invalid, vr_accounting_clean):
        """#2: L1 치명적 에러 → pipeline 중단."""
        report = generate_report(vr_sample_df, vr_schema_invalid, vr_accounting_clean)
        assert report.is_pipeline_ready is False

    def test_l1_warnings_only(self, vr_sample_df, vr_schema_warnings_only, vr_accounting_clean):
        """#3: L1 경고만 → pipeline 계속 진행."""
        report = generate_report(vr_sample_df, vr_schema_warnings_only, vr_accounting_clean)
        assert report.is_pipeline_ready is True
        assert report.validation_score < 100.0


# ── 3. accounting_issues 구조 ─────────────────────────────────


class TestAccountingIssues:
    """L2 위반 시 표준화된 이슈 목록 생성."""

    def test_balance_issue(self, vr_sample_df, vr_schema_valid, vr_accounting_issues):
        """#4: 대차불일치 → check_type='balance'."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_issues)
        types = [i["check_type"] for i in report.accounting_issues]
        assert "balance" in types

        balance_issue = next(i for i in report.accounting_issues if i["check_type"] == "balance")
        assert balance_issue["severity"] == "error"
        assert "detail" in balance_issue

    def test_date_continuity_issue(self, vr_sample_df, vr_schema_valid, vr_accounting_issues):
        """#5: 일자 불연속 → check_type='date_continuity'."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_issues)
        types = [i["check_type"] for i in report.accounting_issues]
        assert "date_continuity" in types

    def test_duplicate_issue(self, vr_sample_df, vr_schema_valid, vr_accounting_issues):
        """#6: 중복행 → check_type='duplicate'."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_issues)
        types = [i["check_type"] for i in report.accounting_issues]
        assert "duplicate" in types

    def test_valid_documents_calculation(self, vr_sample_df, vr_schema_valid, vr_accounting_issues):
        """#9: valid_documents = total_documents - len(unbalanced_docs)."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_issues)
        # 3 전표 중 2건 불일치 → valid_documents = 1
        assert report.valid_documents == 1


# ── 4. validation_score 산출 ──────────────────────────────────


class TestValidationScore:
    """비율 기반 감점 + 클리핑 검증."""

    def test_all_violations_score_clipped(self, vr_sample_df, vr_schema_invalid, vr_accounting_issues):
        """#7: 모든 위반 → score >= 0 (클리핑)."""
        report = generate_report(vr_sample_df, vr_schema_invalid, vr_accounting_issues)
        assert report.validation_score >= 0.0

    def test_l1_critical_penalty(self, vr_sample_df, vr_schema_invalid, vr_accounting_clean):
        """#8: L1 치명적 에러 → 최소 50점 감점."""
        report = generate_report(vr_sample_df, vr_schema_invalid, vr_accounting_clean)
        assert report.validation_score <= 50.0


# ── 5. JSON 직렬화 ────────────────────────────────────────────


class TestSerialization:
    """report_to_dict + JSON 직렬화 검증."""

    def test_json_serializable(self, vr_sample_df, vr_schema_valid, vr_accounting_issues):
        """#10: report_to_dict → json.dumps 성공."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_issues)
        d = report_to_dict(report)
        # Why: TypeError 발생 시 json.dumps 실패
        serialized = json.dumps(d, ensure_ascii=False)
        assert isinstance(serialized, str)

    def test_numpy_conversion(self, vr_schema_valid, vr_accounting_clean):
        """#11: numpy int64/float64 → Python 네이티브 변환."""
        # Why: numpy 타입이 포함된 DataFrame으로 생성 후 직렬화 검증
        df = pd.DataFrame({
            "document_id": ["D001"],
            "posting_date": pd.to_datetime(["2025-01-06"]),
            "debit_amount": np.array([100_000.0], dtype=np.float64),
        })
        report = generate_report(df, vr_schema_valid, vr_accounting_clean)
        d = report_to_dict(report)

        assert isinstance(d["total_rows"], int)
        assert isinstance(d["validation_score"], float)
        # JSON 직렬화 성공 확인 (numpy 타입이면 TypeError)
        json.dumps(d, ensure_ascii=False)


# ── 6. 메타데이터 ─────────────────────────────────────────────


class TestMetadata:
    """generated_at, date_range 등 메타데이터 검증."""

    def test_generated_at_utc(self, vr_sample_df, vr_schema_valid, vr_accounting_clean):
        """#12: generated_at이 ISO 8601 + UTC 타임존."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_clean)
        parsed = datetime.fromisoformat(report.generated_at)
        assert parsed.tzinfo is not None

    def test_date_range(self, vr_sample_df, vr_schema_valid, vr_accounting_clean):
        """posting_date min/max 추출 검증."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_clean)
        assert report.date_range is not None
        assert report.date_range[0] == "2025-01-06"
        assert report.date_range[1] == "2025-01-08"


# ── 7. Edge cases ─────────────────────────────────────────────


class TestEdgeCases:
    """빈 DataFrame, 전체 NaT, Phase 2 호환 등."""

    def test_empty_dataframe(self, vr_empty_df, vr_schema_valid, vr_accounting_clean):
        """#13: 0행 DataFrame → 에러 없이 동작, date_range=None."""
        report = generate_report(vr_empty_df, vr_schema_valid, vr_accounting_clean)
        assert report.total_rows == 0
        assert report.date_range is None

    def test_statistical_result_none(self, vr_sample_df, vr_schema_valid, vr_accounting_clean):
        """#14: statistical_result 미전달 → statistical_flags 빈 리스트."""
        report = generate_report(vr_sample_df, vr_schema_valid, vr_accounting_clean)
        assert report.statistical_flags == []

    def test_all_nat_posting_date(self, vr_nat_df, vr_schema_valid, vr_accounting_clean):
        """#16: posting_date 전체 NaT → date_range=None."""
        report = generate_report(vr_nat_df, vr_schema_valid, vr_accounting_clean)
        assert report.date_range is None
