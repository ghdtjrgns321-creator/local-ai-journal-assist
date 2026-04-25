"""L3-04~L3-08, L4-03, L3-09 피처 기반 이상 징후 룰 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c01_period_end_sensitive_account,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c05_fiscal_period_mismatch,
    c06_missing_or_corrupted_description,
    c08_amount_outlier,
    c10_suspense_account,
)


@pytest.fixture
def anomaly_feature_df() -> pd.DataFrame:
    """L3/L4 피처가 사전 포함된 테스트 DataFrame (8행)."""
    return pd.DataFrame({
        "debit_amount": [100e6, 50e6, 10e6, 300e6, 5e6, 200e6, 30e6, 60e6],
        "credit_amount": [0.0] * 8,
        "is_period_end": [True, False, True, False, True, True, False, False],
        "is_weekend": [True, False, False, True, False, False, True, False],
        "is_holiday": [False, False, True, False, False, False, False, False],
        "is_after_hours": [False, True, False, False, True, False, False, False],
        "days_backdated": [0, 45, -5, 31, 10, 0, -35, 29],
        "fiscal_period_mismatch": [False, False, True, False, False, True, False, False],
        "description_quality": [
            "normal", "missing", "corrupted", "normal", "normal", "missing", "normal", "corrupted",
        ],
        "has_risk_keyword": ["low", "high", "low", "medium", "low", "low", "low", "high"],
        "amount_zscore": [1.0, 2.5, 0.5, 3.5, -4.0, 2.0, 0.3, 1.5],
    })


# ── L3-04 기말 대규모 ──────────────────────────────────────────


class TestL3_04:
    def test_period_end_high_amount_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """월말 + 금액 > Q3 → flagged."""
        result = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        # 행5: is_period_end=True, amount=200e6 (최고액) → True
        assert result[5]

    def test_period_end_low_amount_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """월말이지만 금액 ≤ Q3 → not flagged."""
        result = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        # 행2: is_period_end=True, amount=10e6 (하위) → False
        assert not result[2]

    def test_period_end_manual_low_amount_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """Period-end manual entries are included even when not high amount."""
        anomaly_feature_df["is_manual_je"] = [
            False, False, True, False, False, False, False, False,
        ]
        result = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        assert result[2]

    def test_non_period_end_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """월말 아닌 행은 고액이어도 not flagged."""
        result = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        assert not result[3]  # is_period_end=False, amount=80e6

    def test_missing_feature_returns_false(self) -> None:
        """is_period_end 피처 미존재 시 모두 False."""
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        assert not c01_period_end_large(df).any()

    def test_grouped_q3_per_account_group(self) -> None:
        """account_group별 Q3 적용 — 그룹 내 상대적 고액만 플래그."""
        # Why: expense [10, 20, 30, 100] → Q3=47.5, revenue [1000, 2000, 3000, 10000] → Q3=4750
        df = pd.DataFrame({
            "debit_amount":  [10, 20, 30, 100, 1000, 2000, 3000, 10000],
            "credit_amount": [0] * 8,
            "is_period_end": [True] * 8,
            "account_group": ["expense"] * 4 + ["revenue"] * 4,
        })
        result = c01_period_end_large(df, quantile=0.75, min_group_size=3)
        # expense: 100 > Q3(47.5) → True
        assert result[3]
        # expense: 10, 20, 30 ≤ Q3 → False
        assert not result[0] and not result[1] and not result[2]
        # revenue: 10000 > Q3(4750) → True
        assert result[7]
        # revenue: 1000, 2000, 3000 ≤ Q3 → False
        assert not result[4] and not result[5]

    def test_small_group_fallback_to_global(self) -> None:
        """n < min_group_size인 그룹은 전체 Q3로 fallback."""
        df = pd.DataFrame({
            "debit_amount":  [10, 20, 80, 90, 9000],
            "credit_amount": [0] * 5,
            "is_period_end": [True] * 5,
            # Why: 'rare' 그룹은 1건뿐 → 전체 Q3 fallback
            "account_group": ["expense"] * 4 + ["rare"],
        })
        result = c01_period_end_large(df, quantile=0.75, min_group_size=3)
        # rare(idx=4): 9000 > 전체 Q3(≈86.25) → True
        assert result[4]

    def test_no_account_group_uses_global(self, anomaly_feature_df: pd.DataFrame) -> None:
        """account_group 미존재 시 기존 전체 Q3 동작과 동일."""
        result_with_param = c01_period_end_large(
            anomaly_feature_df, quantile=0.75, min_group_size=30,
        )
        result_without = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        pd.testing.assert_series_equal(result_with_param, result_without)

    def test_whitelist_excludes_approved_recurring_closing_pattern(self) -> None:
        """감사인이 승인한 자동 반복 마감전표 패턴은 L3-04에서 제외."""
        df = pd.DataFrame({
            "debit_amount": [1000.0, 1000.0, 10.0, 20.0],
            "credit_amount": [0.0, 0.0, 0.0, 0.0],
            "is_period_end": [True, True, True, True],
            "source": ["batch", "manual", "batch", "manual"],
            "created_by": ["SAP_BATCH", "USER01", "SAP_BATCH", "USER02"],
            "document_type": ["AF", "SA", "AF", "SA"],
            "account_group": ["fixed_assets", "revenue", "fixed_assets", "expense"],
            "line_text": ["monthly depreciation", "manual revenue adj", "monthly depreciation", ""],
        })
        whitelist = [{
            "source": ["batch"],
            "created_by": ["SAP_BATCH"],
            "document_type": ["AF"],
            "account_group": ["fixed_assets"],
            "description_contains": ["depreciation"],
        }]

        result = c01_period_end_large(
            df,
            quantile=0.5,
            min_group_size=30,
            whitelist_patterns=whitelist,
        )

        assert not result[0]
        assert result[1]

    def test_sensitive_account_mask_matches_group_and_prefix(self) -> None:
        """민감 계정 설정은 account_group과 gl_account prefix 둘 다 지원."""
        df = pd.DataFrame({
            "account_group": ["revenue", "expense", "other"],
            "gl_account": ["4000", "6200", "1205"],
        })
        result = c01_period_end_sensitive_account(
            df,
            {
                "account_groups": ["revenue"],
                "account_prefixes": ["12"],
            },
        )
        assert result.tolist() == [True, False, True]


# ── L3-05 주말 전기 ──────────────────────────────────────────


class TestL3_05:
    def test_weekend_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """토/일 → flagged."""
        result = c02_weekend_entry(anomaly_feature_df)
        assert result[0]  # is_weekend=True
        assert result[3]  # is_weekend=True

    def test_holiday_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """공휴일 → flagged."""
        result = c02_weekend_entry(anomaly_feature_df)
        assert result[2]  # is_holiday=True

    def test_weekday_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """평일 + 비공휴일 → not flagged."""
        result = c02_weekend_entry(anomaly_feature_df)
        assert not result[1]
        assert not result[7]


# ── L3-06 심야 전기 ──────────────────────────────────────────


class TestL3_06:
    def test_after_hours_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """업무시간 외 → flagged."""
        result = c03_after_hours_entry(anomaly_feature_df)
        assert result[1]
        assert result[4]

    def test_business_hours_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """업무시간 → not flagged."""
        result = c03_after_hours_entry(anomaly_feature_df)
        assert not result[0]

    def test_missing_feature_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c03_after_hours_entry(df).any()

    def test_time_zone_category_only_does_not_flag(self) -> None:
        """L3-06은 심야 전기만 보며 time_zone_category로 확장하지 않는다."""
        df = pd.DataFrame({
            "debit_amount": [100.0, 100.0, 100.0, 100.0],
            "time_zone_category": ["normal", "overtime", "midnight", "unknown"],
        })
        result = c03_after_hours_entry(df)
        # Why: overtime은 L4-05, 주말/공휴일은 L3-05가 담당한다.
        assert result.tolist() == [False, False, False, False]

    def test_time_zone_category_does_not_expand_after_hours(self) -> None:
        """time_zone_category가 있어도 L3-06은 is_after_hours만 따른다."""
        df = pd.DataFrame({
            "debit_amount": [100.0, 100.0, 100.0, 100.0],
            "is_after_hours": [True, False, False, False],
            "time_zone_category": ["normal", "normal", "midnight", "normal"],
        })
        result = c03_after_hours_entry(df)
        assert result.tolist() == [True, False, False, False]


# ── L3-07 전기일-문서일 장기 괴리 ─────────────────────────────


class TestL3_07:
    def test_backdated_over_threshold_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """abs(days_backdated) > 30 → flagged."""
        result = c04_backdated_entry(anomaly_feature_df, threshold_days=30)
        assert result[1]  # 45일
        assert result[3]  # 31일
        assert result[6]  # -35일 (abs=35)

    def test_backdated_under_threshold_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """abs(days_backdated) ≤ 30 → not flagged."""
        result = c04_backdated_entry(anomaly_feature_df, threshold_days=30)
        assert not result[0]  # 0일
        assert not result[7]  # 29일

    def test_missing_feature_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c04_backdated_entry(df).any()


# ── L1-08 기간 불일치 ────────────────────────────────────────


class TestL1_08:
    def test_mismatch_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert result[2]
        assert result[5]

    def test_match_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert not result[0]


# ── L3-08 적요 결손/파손 ─────────────────────────────────────


class TestL3_08:
    def test_missing_quality_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """description_quality=missing → flagged."""
        result = c06_missing_or_corrupted_description(anomaly_feature_df)
        assert result[1]  # missing
        assert result[5]  # missing

    def test_corrupted_quality_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """description_quality=corrupted → flagged."""
        result = c06_missing_or_corrupted_description(anomaly_feature_df)
        assert result[2]  # corrupted

    def test_risk_keyword_not_flagged_by_l3_08(self, anomaly_feature_df: pd.DataFrame) -> None:
        """위험 키워드는 L3-08 Phase 1 결손/파손 판정에 쓰지 않는다."""
        result = c06_missing_or_corrupted_description(anomaly_feature_df)
        assert not result[3]  # medium keyword only

    def test_legacy_poor_alias_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """기존 저장 데이터 호환을 위해 poor는 corrupted 별칭으로 인정."""
        anomaly_feature_df.loc[7, "description_quality"] = "poor"
        result = c06_missing_or_corrupted_description(anomaly_feature_df)
        assert result[7]

    def test_normal_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """quality=normal + risk=low → not flagged."""
        result = c06_missing_or_corrupted_description(anomaly_feature_df)
        assert not result[0]
        assert not result[4]


# ── L4-03 이상 고액 ──────────────────────────────────────────


class TestL4_03:
    def test_high_zscore_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """zscore > 3.0 and amount >= P90 → flagged."""
        result = c08_amount_outlier(
            anomaly_feature_df,
            zscore_threshold=3.0,
            min_amount_quantile=0.90,
        )
        assert result[3]  # z=3.5, amount=P90+ range

    def test_low_zscore_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """zscore ≤ 3.0 → not flagged."""
        result = c08_amount_outlier(
            anomaly_feature_df,
            zscore_threshold=3.0,
            min_amount_quantile=0.90,
        )
        assert not result[0]  # 1.0
        assert not result[1]  # 2.5

    def test_negative_zscore_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """negative outliers are not L4-03 unusually-high amounts."""
        result = c08_amount_outlier(
            anomaly_feature_df,
            zscore_threshold=3.0,
            min_amount_quantile=0.90,
        )
        assert not result[4]  # -4.0

    def test_high_zscore_below_amount_guard_not_flagged(self) -> None:
        """High z-score alone is insufficient below the Phase1 amount guard."""
        df = pd.DataFrame({
            "debit_amount": [10.0, 20.0, 30.0, 40.0, 1_000.0],
            "credit_amount": [0.0] * 5,
            "amount_zscore": [0.1, 0.2, 4.0, 0.3, 0.4],
        })
        result = c08_amount_outlier(df, zscore_threshold=3.0, min_amount_quantile=0.90)
        assert not result[2]

    def test_missing_feature_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c08_amount_outlier(df).any()


# ── L3-09 가수금 장기체류 ──────────────────────────────────────


class TestL3_09:
    def test_long_open_amount_flagged(self) -> None:
        """가계정 + 미정리금액 + 30일 이상 체류 → flagged."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25", "2025-03-25"]),
            "is_suspense_account": [True, True, False],
            "amount_open": [100000.0, 100000.0, 100000.0],
        })
        result = c10_suspense_account(df)
        assert result[0]
        assert not result[1]
        assert not result[2]

    def test_cleared_entry_not_flagged(self) -> None:
        """정산 완료 또는 clear status면 장기체류로 보지 않음."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "settlement_date": pd.to_datetime(["2025-01-15", "2025-03-20"]),
            "settlement_status": ["settled", "cleared"],
            "is_suspense_account": [True, True],
        })
        assert not c10_suspense_account(df).any()

    def test_is_cleared_false_fallback_flagged(self) -> None:
        """is_cleared=False를 미정리 상태로 사용."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25"]),
            "is_suspense_account": [True, True],
            "is_cleared": [False, False],
        })
        result = c10_suspense_account(df)
        assert result[0]
        assert not result[1]

    def test_no_resolution_signal_returns_false(self) -> None:
        """미정리 여부를 판단할 입력이 없으면 보수적으로 False."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01"]),
            "is_suspense_account": [True],
        })
        assert not c10_suspense_account(df).any()

    def test_lettrage_date_fallback_flagged(self) -> None:
        """정산 정보가 없을 때 lettrage_date 부재를 보조 신호로 사용."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25"]),
            "is_suspense_account": [True, True],
            "lettrage_date": [pd.NaT, pd.NaT],
        })
        result = c10_suspense_account(df)
        assert result[0]
        assert not result[1]

    def test_row_annotations_expose_threshold_days(self) -> None:
        """플래그 행에 aging과 고정 threshold를 남긴다."""
        df = pd.DataFrame({
            "gl_account": ["2190", "2190"],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25"]),
            "amount_open": [100000.0, 100000.0],
            "is_suspense_account": [True, True],
        })
        result = c10_suspense_account(df, threshold_days=30)
        ann = result.attrs["row_annotations"][0]
        assert ann["gl_account"] == "2190"
        assert ann["aging_days"] == 83
        assert ann["threshold_days"] == 30
        assert result.attrs["breakdown"]["base_threshold_days"] == 30

    def test_missing_prerequisites_returns_false(self) -> None:
        """필수 컬럼 부족 → 전체 False."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c10_suspense_account(df).any()
