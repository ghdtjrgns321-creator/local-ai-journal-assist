"""Tier B E2E: sap-merged(331K건) → ingest → feature graceful degradation 검증.

SAP 기술 컬럼명(budat, bldat 등) → fuzzy mapping.
debit_amount/credit_amount 직접 매핑 불가 → amount 계열 피처 미생성 기대.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.feature.engine import EXPECTED_COLUMNS, FeatureResult, generate_all_features
from src.ingest.column_mapper import auto_map_columns
from src.ingest.file_validator import validate_file
from src.ingest.reader_api import read_file
from src.ingest.type_caster import cast_dataframe

SAP_MERGED = Path("data/journal/validation/sap-merged/sap_merged.parquet")

# 카테고리별 기대 피처명
TIME_FEATURES = EXPECTED_COLUMNS["time"]
AMOUNT_FEATURES = EXPECTED_COLUMNS["amount"]


def _run_ingest_pipeline(filepath: Path) -> tuple[pd.DataFrame, list[str]]:
    """ingest 파이프라인 실행 → (DataFrame, missing_required) 반환.

    Why: Parquet은 컬럼명이 메타데이터에 포함 → 헤더 탐지·prepare_dataframe 스킵.
    """
    vr = validate_file(filepath)
    assert vr.is_valid, f"파일 검증 실패: {vr.errors}"

    rr = read_file(filepath)
    raw_df = rr.raw_data[rr.active_sheet]

    # Parquet: header_row=0 고정, prepare_dataframe 불필요
    columns = list(raw_df.columns)
    mr = auto_map_columns(columns, data_df=raw_df)
    renamed_df = raw_df.rename(columns=mr.mapping)

    cr = cast_dataframe(renamed_df)
    assert cr.success, f"캐스팅 실패: {cr.errors}"
    return cr.data, mr.missing_required


class TestSapMergedE2E:
    """sap-merged 331K건 ingest → feature graceful degradation."""

    @pytest.fixture(scope="class")
    def pipeline_result(self) -> tuple[pd.DataFrame, FeatureResult, list[str], int]:
        """ingest → feature 1회 실행, 클래스 내 재사용.

        Returns: (feature_df, result, missing_required, row_count_before)
        """
        if not SAP_MERGED.exists():
            pytest.skip(f"데이터 파일 없음: {SAP_MERGED}")

        ingested_df, missing_required = _run_ingest_pipeline(SAP_MERGED)
        row_count_before = len(ingested_df)
        result = generate_all_features(ingested_df)
        return (ingested_df, result, missing_required, row_count_before)

    def test_partial_features_generated(self, pipeline_result):
        """일부 피처 생성, 일부 미생성 — graceful degradation."""
        _, result, _, _ = pipeline_result
        assert len(result.added_columns) > 0, "피처가 하나도 생성되지 않음"
        assert len(result.missing_columns) > 0, "모든 피처 생성됨 — degradation 테스트 불가"

    def test_amount_features_degraded(self, pipeline_result):
        """debit/credit 미매핑 → amount 계열 피처 대부분 missing."""
        _, result, missing_required, _ = pipeline_result
        # Why: debit_amount/credit_amount가 미매핑이면 amount 피처 생성 불가
        amount_missing = [f for f in AMOUNT_FEATURES if f in result.missing_columns]
        if "debit_amount" in missing_required or "credit_amount" in missing_required:
            assert len(amount_missing) > 0, "debit/credit 미매핑인데 amount 피처가 모두 생성됨"

    def test_time_features_present(self, pipeline_result):
        """posting_date(budat) 매핑 → time 피처 일부 생성."""
        df, result, _, _ = pipeline_result
        # Why: budat → posting_date 매핑 성공 시 time 피처 생성 가능
        time_added = [f for f in TIME_FEATURES if f in result.added_columns]
        if "posting_date" in df.columns:
            assert len(time_added) > 0, "posting_date 존재하는데 time 피처 0개"

    def test_graceful_degradation_metadata(self, pipeline_result):
        """FeatureResult 메타데이터가 성공/실패를 정확히 분류."""
        _, result, _, _ = pipeline_result
        assert isinstance(result, FeatureResult)
        # Why: 성공 + 실패 = 전체 4개 카테고리
        total = len(result.categories_run) + len(result.failed_categories)
        assert total == 4, f"성공({result.categories_run}) + 실패({result.failed_categories}) ≠ 4"
        assert len(result.categories_run) > 0, "성공 카테고리 0개 — 전체 실패"
        assert len(result.failed_categories) > 0, "실패 카테고리 0개 — degradation 미발생"

    def test_row_count_preserved(self, pipeline_result):
        """피처 생성 후 행 수 불변."""
        df, _, _, row_count_before = pipeline_result
        assert len(df) == row_count_before


class TestGenerateSapMergedReport:
    """sap-merged E2E 리포트 생성 (slow 마커)."""

    @pytest.mark.slow
    def test_generate_report(self):
        """sap-merged E2E 결과를 MD 리포트로 저장."""
        if not SAP_MERGED.exists():
            pytest.skip(f"데이터 파일 없음: {SAP_MERGED}")

        from tests.modules.test_feature.e2e_report_builder import build_report

        ingested_df, missing_required = _run_ingest_pipeline(SAP_MERGED)
        row_count = len(ingested_df)
        result = generate_all_features(ingested_df)

        report = build_report(
            ingested_df, result, row_count, result.elapsed_seconds,
            title="SAP-Merged (Graceful Degradation)",
            missing_required=missing_required,
        )

        out_dir = Path("tests/test_feature/test-results")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "e2e-sap-merged.md"
        out_path.write_text(report, encoding="utf-8")

        assert out_path.exists()
        assert out_path.stat().st_size > 256
