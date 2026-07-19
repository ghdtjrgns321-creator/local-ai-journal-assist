"""report 단위 테스트 — summarize_for_dashboard."""

import numpy as np
import pandas as pd
import pytest

from src.eda.profiler import profile_dataframe
from src.eda.report import summarize_for_dashboard


class TestSummarizeForDashboard:
    """summarize_for_dashboard() 함수 테스트."""

    def test_overview_keys(self, ed_mixed_df):
        """overview dict 키 구조 검증."""
        profile = profile_dataframe(ed_mixed_df)
        result = summarize_for_dashboard(profile)

        overview = result["overview"]
        assert "total_rows" in overview
        assert "total_columns" in overview
        assert "memory_mb" in overview
        assert "duplicate_rows" in overview
        assert "sampled" in overview

    def test_quality_score_range(self, ed_mixed_df):
        """quality_score가 0~100 범위."""
        profile = profile_dataframe(ed_mixed_df)
        result = summarize_for_dashboard(profile)

        assert 0 <= result["quality_score"] <= 100

    def test_quality_score_perfect(self):
        """결측/중복 없는 데이터 → 100점."""
        df = pd.DataFrame({
            "a": [1.0, 2.0, 3.0],
            "b": ["X", "Y", "Z"],
        })
        profile = profile_dataframe(df)
        result = summarize_for_dashboard(profile)

        assert result["quality_score"] == 100.0

    def test_quality_score_empty(self, ed_empty_df):
        """빈 DataFrame → 0점."""
        profile = profile_dataframe(ed_empty_df)
        result = summarize_for_dashboard(profile)

        assert result["quality_score"] == 0.0

    def test_warnings_high_missing(self):
        """결측률 10%+ → 경고 생성."""
        df = pd.DataFrame({
            "a": [1.0, np.nan, np.nan, 4.0, np.nan],  # 60% 결측
        })
        profile = profile_dataframe(df)
        result = summarize_for_dashboard(profile)

        assert any("결측률" in w for w in result["warnings"])

    def test_warnings_high_cardinality(self):
        """카디널리티 100+ → 경고 생성."""
        df = pd.DataFrame({
            "codes": [f"code_{i}" for i in range(200)],
        })
        profile = profile_dataframe(df)
        result = summarize_for_dashboard(profile)

        assert any("카디널리티" in w for w in result["warnings"])

    def test_warnings_duplicates(self):
        """중복률 5%+ → 경고 생성."""
        df = pd.DataFrame({
            "a": [1] * 10 + list(range(10)),  # 50% 중복
        })
        profile = profile_dataframe(df)
        result = summarize_for_dashboard(profile)

        assert any("중복행" in w for w in result["warnings"])

    def test_column_summaries_structure(self, ed_mixed_df):
        """column_summaries 리스트 구조."""
        profile = profile_dataframe(ed_mixed_df)
        result = summarize_for_dashboard(profile)

        summaries = result["column_summaries"]
        assert len(summaries) == len(ed_mixed_df.columns)
        for s in summaries:
            assert "name" in s
            assert "dtype_group" in s
            assert "missing_rate" in s
            assert "highlights" in s

    def test_missing_heatmap_data(self, ed_mixed_df):
        """missing_heatmap_data 키가 컬럼명."""
        profile = profile_dataframe(ed_mixed_df)
        result = summarize_for_dashboard(profile)

        heatmap = result["missing_heatmap_data"]
        assert set(heatmap.keys()) == set(ed_mixed_df.columns)

    def test_numeric_stats_table(self, ed_numeric_df):
        """numeric_stats_table — 수치형 컬럼만 포함."""
        profile = profile_dataframe(ed_numeric_df)
        result = summarize_for_dashboard(profile)

        table = result["numeric_stats_table"]
        assert len(table) == 2  # amount, count
        assert all("mean" in row for row in table)
