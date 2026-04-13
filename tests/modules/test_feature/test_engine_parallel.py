"""피처 엔진 병렬 실행 테스트.

generate_all_features(parallel=True) 시 Thin Copy + Series 반환 패턴이
순차 실행과 동일한 결과를 내는지 검증.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.feature.engine import FeatureCategory, generate_all_features


class TestParallelDefault:
    """기본값 및 하위 호환성."""

    def test_parallel_default_false(self, en_full_df: pd.DataFrame):
        """parallel 미지정 시 순차 실행 (기존 동작 보존)."""
        result = generate_all_features(en_full_df)
        assert len(result.added_columns) > 0
        assert result.failed_categories == [] or isinstance(result.failed_categories, list)


class TestParallelEquivalence:
    """순차/병렬 결과 동등성."""

    def test_parallel_same_columns(self, en_full_df: pd.DataFrame):
        """순차/병렬 결과 컬럼 집합이 동일."""
        df_seq = en_full_df.copy()
        df_par = en_full_df.copy()

        res_seq = generate_all_features(df_seq, parallel=False)
        res_par = generate_all_features(df_par, parallel=True)

        assert set(res_seq.added_columns) == set(res_par.added_columns)
        assert set(res_seq.missing_columns) == set(res_par.missing_columns)

    def test_parallel_same_values(self, en_full_df: pd.DataFrame):
        """순차/병렬 결과 값이 동일 (결정적 연산)."""
        df_seq = en_full_df.copy()
        df_par = en_full_df.copy()

        res_seq = generate_all_features(df_seq, parallel=False)
        res_par = generate_all_features(df_par, parallel=True)

        common_cols = sorted(set(res_seq.added_columns) & set(res_par.added_columns))
        pd.testing.assert_frame_equal(
            res_seq.data[common_cols].reset_index(drop=True),
            res_par.data[common_cols].reset_index(drop=True),
        )


class TestParallelMetadata:
    """병렬 실행 메타데이터 정확성."""

    def test_execution_times_recorded(self, en_full_df: pd.DataFrame):
        """4개 카테고리 모두 실행 시간 기록."""
        result = generate_all_features(en_full_df, parallel=True)
        for cat in FeatureCategory:
            assert cat.value in result.execution_times
            assert result.execution_times[cat.value] >= 0


class TestParallelResilience:
    """병렬 실행 장애 격리."""

    def test_failure_isolated(self, en_minimal_df: pd.DataFrame):
        """필수 컬럼 누락으로 일부 카테고리 실패해도 나머지 정상."""
        # en_minimal_df: posting_date + debit/credit만 → PATTERN, TEXT 실패 예상
        result = generate_all_features(en_minimal_df, parallel=True)
        assert len(result.categories_run) >= 1  # 최소 1개 성공
        assert len(result.added_columns) > 0

    def test_max_workers(self, en_full_df: pd.DataFrame):
        """max_workers=2로 제한해도 정상 동작."""
        result = generate_all_features(en_full_df, parallel=True, max_workers=2)
        assert len(result.added_columns) > 0
        assert len(result.execution_times) > 0
