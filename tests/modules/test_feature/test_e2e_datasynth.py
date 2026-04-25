"""Tier A E2E: datasynth(1M건) → ingest → feature 전체 검증.

journal_entries.csv는 표준 컬럼명과 동일 → identity mapping fast path.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.feature.engine import FeatureResult, generate_all_features
from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
from src.ingest.file_validator import validate_file
from src.ingest.header_detector import detect_header_row
from src.ingest.reader_api import read_file
from src.ingest.type_caster import cast_dataframe

DATASYNTH_CSV = Path("data/journal/primary/datasynth/journal_entries.csv")

# datasynth 1M건에서 반드시 True/False 모두 존재해야 하는 피처
MUST_HAVE_VARIATION = {"is_weekend", "is_period_end", "is_manual_je", "is_revenue_account"}


def _run_ingest_pipeline(filepath: Path) -> pd.DataFrame:
    """ingest 6단계 실행 → 표준 DataFrame 반환."""
    vr = validate_file(filepath)
    assert vr.is_valid, f"파일 검증 실패: {vr.errors}"

    rr = read_file(filepath)
    raw_df = rr.raw_data[rr.active_sheet]

    hr = detect_header_row(raw_df)
    hr_row = hr.header_row if hr.header_row is not None else 0
    columns, data_df = prepare_dataframe(raw_df, hr_row)

    mr = auto_map_columns(columns, matched_keywords=hr.matched_keywords, data_df=data_df)
    renamed_df = data_df.rename(columns=mr.mapping)

    cr = cast_dataframe(renamed_df)
    assert cr.success, f"캐스팅 실패: {cr.errors}"
    return cr.data


class TestDataSynthE2E:
    """datasynth 1M건 ingest → feature 전체 파이프라인."""

    @pytest.fixture(scope="class")
    def pipeline_result(self) -> tuple[pd.DataFrame, FeatureResult, int]:
        """ingest → feature 1회 실행, 클래스 내 재사용.

        Returns: (feature_df, result, row_count_before)
        """
        if not DATASYNTH_CSV.exists():
            pytest.skip(f"데이터 파일 없음: {DATASYNTH_CSV}")

        ingested_df = _run_ingest_pipeline(DATASYNTH_CSV)
        row_count_before = len(ingested_df)
        result = generate_all_features(ingested_df)
        return (ingested_df, result, row_count_before)

    def test_all_expected_features_generated(self, pipeline_result):
        """기대 피처 전부 생성되어야 한다."""
        _, result, _ = pipeline_result
        from src.feature.engine import EXPECTED_COLUMNS

        expected_count = sum(len(cols) for cols in EXPECTED_COLUMNS.values())
        assert len(result.added_columns) == expected_count, (
            f"생성: {len(result.added_columns)}, missing: {result.missing_columns}"
        )
        assert result.missing_columns == []
        assert result.failed_categories == []

    def test_no_all_null_features(self, pipeline_result):
        """각 피처의 null율이 100% 미만 — 전부 NaN이면 구현 오류."""
        df, result, _ = pipeline_result
        all_null = [col for col in result.added_columns if df[col].isna().all()]
        assert all_null == [], f"전체 NaN 피처: {all_null}"

    def test_bool_features_have_variation(self, pipeline_result):
        """핵심 bool 피처는 반드시 True/False 모두 존재해야 함.

        Why: 1M건 합성 데이터에서 is_weekend, is_period_end 등은
        반드시 True 케이스가 있어야 정상. all-False면 구현 오류.
        """
        df, _, _ = pipeline_result
        for col in MUST_HAVE_VARIATION:
            if col in df.columns:
                assert df[col].nunique() == 2, f"{col}: 변동 없음 — 구현 오류 의심"

    def test_dtype_consistency(self, pipeline_result):
        """dtype 규칙: bool→bool, float→float64, Int64→Int64, str→object."""
        df, _, _ = pipeline_result
        expected_bool = {"is_weekend", "is_after_hours", "is_period_end",
                         "fiscal_period_mismatch", "is_holiday",
                         "is_near_threshold", "exceeds_threshold", "is_round_number",
                         "is_manual_je", "is_intercompany", "is_revenue_account",
                         "is_suspense_account",
                         "description_line_missing", "description_header_missing",
                         "description_both_missing",
                         "description_line_missing_header_present",
                         "description_is_missing_or_corrupted"}
        expected_float = {"amount_zscore", "amount_magnitude"}
        # Why: days_backdated는 정수 일수(Int64), first_digit도 Int64
        expected_int = {"first_digit", "days_backdated"}
        # Why: keyword/description/time-zone labels are categorical strings.
        expected_str = {"has_risk_keyword", "description_quality", "time_zone_category"}

        for col in expected_bool:
            if col in df.columns:
                # Why: pandas nullable BooleanDtype("boolean")도 허용
                assert str(df[col].dtype) in ("bool", "boolean"), (
                    f"{col} dtype={df[col].dtype}, expected bool/boolean"
                )
        for col in expected_float:
            if col in df.columns:
                assert str(df[col].dtype).startswith("float"), f"{col} dtype={df[col].dtype}"
        for col in expected_int:
            if col in df.columns:
                assert str(df[col].dtype) in ("Int64", "int64"), f"{col} dtype={df[col].dtype}"
        for col in expected_str:
            if col in df.columns:
                assert df[col].dtype == "object", f"{col} dtype={df[col].dtype}, expected object"

    def test_first_digit_range(self, pipeline_result):
        """first_digit는 1~9 범위 + NaN만 허용 (Benford 기반)."""
        df, _, _ = pipeline_result
        if "first_digit" not in df.columns:
            pytest.skip("first_digit 미생성")
        valid = df["first_digit"].dropna()
        assert valid.between(1, 9).all(), f"범위 밖: {valid[~valid.between(1, 9)].unique()}"

    def test_time_zone_category_valid_values(self, pipeline_result):
        """time_zone_category는 4가지 값만 허용."""
        df, _, _ = pipeline_result
        if "time_zone_category" not in df.columns:
            pytest.skip("time_zone_category 미생성")
        valid_values = {"normal", "overtime", "midnight", "unknown"}
        actual = set(df["time_zone_category"].dropna().unique())
        assert actual.issubset(valid_values), f"허용 외 값: {actual - valid_values}"

    def test_time_zone_category_has_variation(self, pipeline_result):
        """DataSynth 1M건에서 normal/overtime/midnight 모두 존재해야 함."""
        df, _, _ = pipeline_result
        if "time_zone_category" not in df.columns:
            pytest.skip("time_zone_category 미생성")
        actual = set(df["time_zone_category"].unique())
        # Why: DataSynth temporal_patterns에 심야·야근·정상 모두 포함
        assert {"normal", "overtime", "midnight"}.issubset(actual), (
            f"시간대 분류 변동 부족: {actual}"
        )

    def test_row_count_preserved(self, pipeline_result):
        """피처 생성 후 행 수 불변."""
        df, _, row_count_before = pipeline_result
        assert len(df) == row_count_before

    def test_performance(self, pipeline_result):
        """1M건 기준 60초 이내 완료."""
        _, result, _ = pipeline_result
        # Why: elapsed_seconds는 카테고리별 execution_times 합산 프로퍼티
        assert result.elapsed_seconds < 60, (
            f"소요시간 {result.elapsed_seconds:.1f}s > 60s 제한"
        )


class TestGenerateDataSynthReport:
    """MD 리포트 생성 (slow 마커)."""

    @pytest.mark.slow
    def test_generate_report(self):
        """datasynth E2E 결과를 MD 리포트로 저장."""
        if not DATASYNTH_CSV.exists():
            pytest.skip(f"데이터 파일 없음: {DATASYNTH_CSV}")

        from tests.modules.test_feature.e2e_report_builder import build_report

        ingested_df = _run_ingest_pipeline(DATASYNTH_CSV)
        row_count = len(ingested_df)
        result = generate_all_features(ingested_df)

        report = build_report(ingested_df, result, row_count, result.elapsed_seconds)

        out_dir = Path("tests/test_feature/test-results")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "e2e-datasynth.md"
        out_path.write_text(report, encoding="utf-8")

        assert out_path.exists()
        assert out_path.stat().st_size > 512
