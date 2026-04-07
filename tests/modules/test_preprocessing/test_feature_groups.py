"""피처 그룹 자동 분류 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.eda.models import ColumnProfile, EDAProfile
from src.preprocessing.feature_groups import FeatureGroups, classify_features


class TestClassifyFeatures:
    """EDAProfile → 6그룹 자동 분류 검증."""

    def test_numeric_columns_classified(self, pp_sample_profile):
        groups = classify_features(pp_sample_profile)
        for col in ("debit_amount", "credit_amount", "amount_zscore"):
            assert col in groups.numeric, f"{col} not in numeric"

    def test_boolean_columns_classified(self, pp_sample_profile):
        groups = classify_features(pp_sample_profile)
        expected = {"is_weekend", "is_after_hours", "is_round_number", "has_risk_keyword"}
        assert expected.issubset(set(groups.boolean))

    def test_gl_account_high_cardinality(self, pp_sample_profile):
        # gl_account는 Int64(numeric) → domain_overrides로 categorical_high 배치
        groups = classify_features(
            pp_sample_profile,
            domain_overrides={"gl_account": "categorical_high"},
        )
        assert "gl_account" in groups.categorical_high

    def test_ordinal_override(self, pp_sample_profile):
        groups = classify_features(
            pp_sample_profile,
            domain_overrides={"description_quality": "ordinal"},
        )
        assert "description_quality" in groups.ordinal

    def test_excluded_columns(self, pp_sample_profile):
        groups = classify_features(pp_sample_profile)
        assert "document_id" in groups.excluded
        assert "posting_date" in groups.excluded

    def test_low_cardinality_categorical(self, pp_sample_profile):
        groups = classify_features(pp_sample_profile)
        for col in ("source", "company_code"):
            assert col in groups.categorical_low, f"{col} not in categorical_low"

    def test_high_missing_rate_excluded(self):
        """결측률 95% 컬럼 → excluded 자동 배치."""
        profile = EDAProfile(total_rows=100, total_columns=2, memory_bytes=1000, duplicate_rows=0)
        profile.columns["sparse_col"] = ColumnProfile(
            name="sparse_col", dtype="float64", dtype_group="numeric",
            missing_rate=0.95, unique_count=3,
        )
        profile.columns["normal_col"] = ColumnProfile(
            name="normal_col", dtype="float64", dtype_group="numeric",
            missing_rate=0.05, unique_count=50,
        )
        groups = classify_features(profile)
        assert "sparse_col" in groups.excluded
        assert "normal_col" in groups.numeric

    def test_all_features_property(self, pp_sample_profile):
        groups = classify_features(pp_sample_profile)
        all_feats = groups.all_features
        for col in groups.excluded:
            assert col not in all_feats

    def test_custom_exclude_columns(self, pp_sample_profile):
        groups = classify_features(pp_sample_profile, exclude_columns=["debit_amount"])
        assert "debit_amount" in groups.excluded
        assert "debit_amount" not in groups.numeric

    def test_no_duplicate_assignments(self, pp_sample_profile):
        groups = classify_features(pp_sample_profile)
        all_lists = [
            groups.numeric, groups.categorical_high, groups.categorical_low,
            groups.boolean, groups.ordinal, groups.excluded,
        ]
        all_cols = [col for lst in all_lists for col in lst]
        assert len(all_cols) == len(set(all_cols)), "중복 배치 발견"
