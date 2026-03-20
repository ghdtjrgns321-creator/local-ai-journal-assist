"""profiler 통합 테스트 — profile_dataframe + profile_to_dict."""

import json

import numpy as np
import pandas as pd
import pytest

from src.eda.models import EDAProfile
from src.eda.profiler import profile_dataframe, profile_to_dict


class TestProfileDataframe:
    """profile_dataframe() 통합 테스트."""

    def test_full_spec(self, ed_full_df):
        """풀 스펙 DataFrame 프로파일링 — 모든 dtype 커버."""
        profile = profile_dataframe(ed_full_df)

        assert isinstance(profile, EDAProfile)
        assert profile.total_rows == 10
        assert profile.total_columns == len(ed_full_df.columns)
        assert profile.sampled is False

    def test_column_dtype_groups(self, ed_mixed_df):
        """4개 dtype 분류 정확성."""
        profile = profile_dataframe(ed_mixed_df)

        assert profile.columns["num"].dtype_group == "numeric"
        assert profile.columns["cat"].dtype_group == "categorical"
        assert profile.columns["dt"].dtype_group == "datetime"
        assert profile.columns["flag"].dtype_group == "boolean"

    def test_empty_df(self, ed_empty_df):
        """0행 DataFrame — 에러 없이 처리."""
        profile = profile_dataframe(ed_empty_df)

        assert profile.total_rows == 0
        assert profile.duplicate_rows == 0
        for cp in profile.columns.values():
            assert cp.missing_rate == 0.0

    def test_all_null_columns(self, ed_all_null_df):
        """전체 NaN/NaT 컬럼 안전 처리."""
        profile = profile_dataframe(ed_all_null_df)

        # all_nan: 수치형, 모든 통계 None
        nan_col = profile.columns["all_nan"]
        assert nan_col.missing_rate == pytest.approx(1.0)
        assert nan_col.mean is None

        # all_nat: datetime, 모든 통계 None
        nat_col = profile.columns["all_nat"]
        assert nat_col.min_date is None

    def test_sampling_trigger(self, ed_large_df):
        """110만행 → sampled=True, sample_size=100_000."""
        profile = profile_dataframe(ed_large_df)

        assert profile.sampled is True
        assert profile.sample_size == 100_000
        assert profile.total_rows == 1_100_000

    def test_duplicate_rows(self):
        """중복행 카운트."""
        df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
        profile = profile_dataframe(df)

        assert profile.duplicate_rows == 1  # 1건 중복

    def test_memory_bytes(self, ed_mixed_df):
        """메모리 사용량이 0보다 큰지 확인."""
        profile = profile_dataframe(ed_mixed_df)

        assert profile.memory_bytes > 0

    def test_missing_rate(self):
        """결측률 정확도."""
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0, np.nan]})
        profile = profile_dataframe(df)

        assert profile.columns["a"].missing_rate == pytest.approx(0.5)

    def test_unique_count(self):
        """유니크 수 정확도."""
        df = pd.DataFrame({"a": ["A", "B", "A", "C"]})
        profile = profile_dataframe(df)

        assert profile.columns["a"].unique_count == 3

    def test_mode_value(self):
        """최빈값 산출."""
        df = pd.DataFrame({"a": ["X", "Y", "X", "Z", "X"]})
        profile = profile_dataframe(df)

        assert profile.columns["a"].mode == "X"


class TestProfileToDict:
    """profile_to_dict() JSON 직렬화 테스트."""

    def test_json_serializable(self, ed_mixed_df):
        """json.dumps()가 에러 없이 성공."""
        profile = profile_dataframe(ed_mixed_df)
        data = profile_to_dict(profile)

        # numpy 타입이 남아있으면 json.dumps 실패
        json_str = json.dumps(data, ensure_ascii=False)
        assert isinstance(json_str, str)

    def test_dict_structure(self, ed_mixed_df):
        """반환 dict 구조 검증."""
        profile = profile_dataframe(ed_mixed_df)
        data = profile_to_dict(profile)

        assert "total_rows" in data
        assert "columns" in data
        assert "num" in data["columns"]
        assert data["columns"]["num"]["dtype_group"] == "numeric"

    def test_no_numpy_types(self, ed_numeric_df):
        """수치형 프로파일 결과에 numpy 타입이 없는지 검증."""
        profile = profile_dataframe(ed_numeric_df)
        data = profile_to_dict(profile)

        def _check_native(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _check_native(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _check_native(v, f"{path}[{i}]")
            elif obj is not None:
                assert isinstance(obj, (int, float, str, bool)), \
                    f"numpy type at {path}: {type(obj)}"

        _check_native(data)
