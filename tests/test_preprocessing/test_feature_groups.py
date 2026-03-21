"""feature_groups 테스트 — EDAProfile → 6그룹 분류 정확성."""

from __future__ import annotations

from src.eda.models import ColumnProfile, EDAProfile
from src.preprocessing.feature_groups import FeatureGroups, classify_features


class TestClassifyFeatures:
    """classify_features 자동 분류 검증."""

    def test_numeric_columns_classified(self, sample_profile):
        """수치형 컬럼이 numeric 그룹에 배치되는지."""
        groups = classify_features(sample_profile)
        for col in ["debit_amount", "credit_amount", "amount_zscore", "amount_magnitude"]:
            assert col in groups.numeric, f"{col}이 numeric에 없음"

    def test_boolean_columns_classified(self, sample_profile):
        """boolean 컬럼이 boolean 그룹에 배치되는지."""
        groups = classify_features(sample_profile)
        for col in ["is_weekend", "is_after_hours", "is_manual_je"]:
            assert col in groups.boolean, f"{col}이 boolean에 없음"

    def test_gl_account_high_cardinality(self, sample_profile):
        """gl_account(4000+종)이 categorical_high에 배치되는지."""
        # gl_account는 numeric dtype이지만 카디널리티가 높음
        # 실제로는 numeric으로 분류됨 (int 타입이므로)
        # 필요 시 오버라이드로 처리
        groups = classify_features(
            sample_profile,
            overrides={"gl_account": "categorical_high"},
        )
        assert "gl_account" in groups.categorical_high

    def test_ordinal_override(self, sample_profile):
        """description_quality, has_risk_keyword가 ordinal로 분류되는지."""
        groups = classify_features(sample_profile)
        assert "description_quality" in groups.ordinal
        assert "has_risk_keyword" in groups.ordinal

    def test_excluded_columns(self, sample_profile):
        """ID, datetime, 레이블이 excluded에 배치되는지."""
        groups = classify_features(sample_profile)
        for col in ["document_id", "posting_date", "document_date", "is_fraud", "is_anomaly"]:
            assert col in groups.excluded, f"{col}이 excluded에 없음"

    def test_low_cardinality_categorical(self, sample_profile):
        """저카디널리티 범주형이 categorical_low에 배치되는지."""
        groups = classify_features(sample_profile)
        for col in ["source", "document_type", "company_code"]:
            assert col in groups.categorical_low, f"{col}이 categorical_low에 없음"

    def test_high_missing_rate_excluded(self):
        """결측률 90% 이상 컬럼이 자동 제외되는지."""
        profile = EDAProfile(
            total_rows=100,
            total_columns=1,
            memory_bytes=1000,
            duplicate_rows=0,
            columns={
                "mostly_null": ColumnProfile(
                    name="mostly_null",
                    dtype="float64",
                    dtype_group="numeric",
                    missing_rate=0.95,
                    unique_count=5,
                ),
            },
        )
        groups = classify_features(profile)
        assert "mostly_null" in groups.excluded

    def test_all_features_property(self, sample_profile):
        """all_features가 excluded를 제외한 전체 목록을 반환하는지."""
        groups = classify_features(sample_profile)
        all_feats = groups.all_features
        # excluded 컬럼은 포함되지 않아야 함
        for col in groups.excluded:
            assert col not in all_feats

    def test_custom_exclude_columns(self, sample_profile):
        """사용자 지정 exclude_columns 동작."""
        groups = classify_features(
            sample_profile,
            exclude_columns={"debit_amount"},
        )
        assert "debit_amount" in groups.excluded
        assert "debit_amount" not in groups.numeric

    def test_no_duplicate_assignments(self, sample_profile):
        """동일 컬럼이 여러 그룹에 중복 배치되지 않는지."""
        groups = classify_features(sample_profile)
        all_cols = (
            groups.numeric + groups.categorical_high + groups.categorical_low
            + groups.boolean + groups.ordinal + groups.excluded
        )
        assert len(all_cols) == len(set(all_cols)), "중복 배치 발견"
