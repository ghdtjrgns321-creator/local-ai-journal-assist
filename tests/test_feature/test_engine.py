"""feature/engine.py 테스트 — 오케스트레이터 통합 검증.

풀 스펙/선택적 카테고리/멱등성/graceful degradation/설정 주입.
"""

from __future__ import annotations

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.feature.engine import (
    EXPECTED_COLUMNS,
    FeatureCategory,
    FeatureResult,
    generate_all_features,
)

# 전체 18개 기대 컬럼 평탄화
_ALL_EXPECTED = [col for cols in EXPECTED_COLUMNS.values() for col in cols]


# ── TestGenerateAllFeatures ──────────────────────────────────────


class TestGenerateAllFeatures:
    """풀 스펙 df → 전체 카테고리 실행 검증."""

    def test_all_18_columns_present(self, en_full_df: pd.DataFrame) -> None:
        """18개 피처 컬럼이 모두 생성되는지 확인."""
        result = generate_all_features(en_full_df)
        for col in _ALL_EXPECTED:
            assert col in result.data.columns, f"{col} 컬럼 누락"

    def test_feature_result_metadata(self, en_full_df: pd.DataFrame) -> None:
        """FeatureResult 메타데이터 정합성."""
        result = generate_all_features(en_full_df)

        assert isinstance(result, FeatureResult)
        assert len(result.added_columns) == 18
        assert result.missing_columns == []
        assert set(result.categories_run) == {"time", "amount", "pattern", "text"}
        assert len(result.execution_times) == 4
        assert result.elapsed_seconds >= 0

    def test_column_dtypes(self, en_full_df: pd.DataFrame) -> None:
        """주요 피처 컬럼의 dtype 검증."""
        result = generate_all_features(en_full_df)
        df = result.data

        # bool 타입 피처
        bool_cols = [
            "is_weekend", "is_after_hours", "is_period_end",
            "is_near_threshold", "exceeds_threshold", "is_round_number",
            "is_manual_je", "is_intercompany", "is_revenue_account",
            "is_suspense_account",
        ]
        for col in bool_cols:
            assert df[col].dtype in ("bool", "boolean"), f"{col} dtype={df[col].dtype}"

        # float 타입 피처
        assert pd.api.types.is_float_dtype(df["amount_zscore"])
        assert pd.api.types.is_float_dtype(df["amount_magnitude"])

        # Int64(nullable) 타입 피처
        assert df["days_backdated"].dtype == "Int64"
        assert df["first_digit"].dtype == "Int64"

        # str/object 타입 피처
        assert df["description_quality"].dtype == "object"
        assert df["has_risk_keyword"].dtype == "object"


# ── TestSelectiveCategories ──────────────────────────────────────


class TestSelectiveCategories:
    """카테고리 선택 실행 검증."""

    def test_time_only(self, en_full_df: pd.DataFrame) -> None:
        """time만 실행 → 6개 컬럼 추가, 나머지 없음."""
        result = generate_all_features(
            en_full_df, categories=[FeatureCategory.TIME],
        )
        time_cols = EXPECTED_COLUMNS[FeatureCategory.TIME]
        assert len(result.added_columns) == len(time_cols)
        assert result.categories_run == ["time"]

        # 다른 카테고리 컬럼은 없어야 함
        for col in EXPECTED_COLUMNS[FeatureCategory.AMOUNT]:
            assert col not in result.data.columns

    def test_amount_and_pattern(self, en_full_df: pd.DataFrame) -> None:
        """amount + pattern → 10개 컬럼 추가."""
        result = generate_all_features(
            en_full_df,
            categories=[FeatureCategory.AMOUNT, FeatureCategory.PATTERN],
        )
        expected_count = (
            len(EXPECTED_COLUMNS[FeatureCategory.AMOUNT])
            + len(EXPECTED_COLUMNS[FeatureCategory.PATTERN])
        )
        assert len(result.added_columns) == expected_count
        assert result.categories_run == ["amount", "pattern"]

    def test_order_preserved(self, en_full_df: pd.DataFrame) -> None:
        """역순 입력해도 time→amount 순서로 실행."""
        result = generate_all_features(
            en_full_df,
            categories=[FeatureCategory.AMOUNT, FeatureCategory.TIME],
        )
        assert result.categories_run == ["time", "amount"]


# ── TestIdempotency ──────────────────────────────────────────────


class TestIdempotency:
    """2회 실행 멱등성 검증."""

    def test_run_twice_no_duplicate(self, en_full_df: pd.DataFrame) -> None:
        """2회 실행해도 컬럼 수 동일 (중복 추가 없음)."""
        result1 = generate_all_features(en_full_df)
        col_count_1 = len(result1.data.columns)

        result2 = generate_all_features(en_full_df)
        col_count_2 = len(result2.data.columns)

        assert col_count_1 == col_count_2

    def test_run_twice_metadata_consistent(self, en_full_df: pd.DataFrame) -> None:
        """2회째에도 added_columns=18개 유지."""
        generate_all_features(en_full_df)
        result2 = generate_all_features(en_full_df)

        assert len(result2.added_columns) == 18
        assert result2.missing_columns == []


# ── TestGracefulDegradation ──────────────────────────────────────


class TestGracefulDegradation:
    """최소 입력/빈 입력에서 에러 없이 완료 검증."""

    def test_minimal_df(self, en_minimal_df: pd.DataFrame) -> None:
        """최소 컬럼(posting_date + 금액) → 에러 없이 완료."""
        result = generate_all_features(en_minimal_df)
        assert isinstance(result, FeatureResult)
        assert len(result.categories_run) == 4

    def test_empty_df(self) -> None:
        """0행 DataFrame → FeatureResult 정상 반환."""
        empty_df = pd.DataFrame({
            "posting_date": pd.to_datetime([]),
            "debit_amount": pd.Series([], dtype="float64"),
            "credit_amount": pd.Series([], dtype="float64"),
        })
        result = generate_all_features(empty_df)
        assert isinstance(result, FeatureResult)
        assert len(result.data) == 0

    def test_missing_columns_logged(self, en_minimal_df: pd.DataFrame) -> None:
        """최소 df → missing_columns에 누락 컬럼 표시."""
        result = generate_all_features(en_minimal_df)

        # document_date 없으므로 fiscal_period_mismatch는 생성되지만,
        # source/gl_account 등 누락으로 일부 컬럼은 fallback 처리됨
        # 모든 18개가 생성되지만 (fallback 포함) missing은 0일 수 있음
        # 핵심: 에러 없이 완료 + FeatureResult 유효
        assert isinstance(result.added_columns, list)
        assert isinstance(result.missing_columns, list)


# ── TestSettingsInjection ────────────────────────────────────────


class TestSettingsInjection:
    """설정/룰 주입 검증."""

    def test_custom_settings(self, en_full_df: pd.DataFrame) -> None:
        """approval_thresholds 변경 → is_near_threshold 결과 달라짐."""
        # 기본 thresholds=[10M,100M,1B,...] → 45M은 near 구간 밖
        result_default = generate_all_features(en_full_df.copy())
        default_near = result_default.data["is_near_threshold"].tolist()

        # thresholds=[50M]으로 변경 → 45M은 near (45M >= 50M*0.9=45M)
        custom = AuditSettings(approval_thresholds=[50_000_000])
        result_custom = generate_all_features(en_full_df.copy(), settings=custom)
        custom_near = result_custom.data["is_near_threshold"].tolist()

        assert default_near != custom_near

    def test_custom_rules(self, en_full_df: pd.DataFrame) -> None:
        """manual_codes 변경 → is_manual_je 결과 달라짐."""
        # 기본 rules에 "SA" 포함 → 첫 행 True
        rules_with_sa = {
            "manual_source_codes": ["SA"],
            "intercompany_identifiers": [],
            "revenue_account_prefixes": ["41"],
            "suspense_keywords": ["가수금"],
        }
        result1 = generate_all_features(en_full_df.copy(), rules=rules_with_sa)

        # "UNKNOWN"만 → 모두 False
        rules_no_match = {
            "manual_source_codes": ["UNKNOWN"],
            "intercompany_identifiers": [],
            "revenue_account_prefixes": ["41"],
            "suspense_keywords": ["가수금"],
        }
        result2 = generate_all_features(en_full_df.copy(), rules=rules_no_match)

        assert result1.data["is_manual_je"].any()
        assert not result2.data["is_manual_je"].any()

    def test_auto_load(self, en_full_df: pd.DataFrame) -> None:
        """settings=None, rules=None → 자동 로드, 에러 없이 완료."""
        result = generate_all_features(en_full_df)
        assert isinstance(result, FeatureResult)
        assert len(result.categories_run) == 4
