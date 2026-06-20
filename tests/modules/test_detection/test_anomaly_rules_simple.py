"""L3-04~L3-08, L4-03, L3-09 피처 기반 이상 징후 룰 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c05_fiscal_period_mismatch,
    c06_missing_or_corrupted_description,
    c08_amount_outlier,
    c10_suspense_account,
    c12_abnormal_hours_concentration,
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


# ── L3-04 기말/기초 결산 검토 후보군 ──────────────────────────


class TestL3_04:
    def test_period_end_flagged_binary(self, anomaly_feature_df: pd.DataFrame) -> None:
        """기말/기초 피처가 True면 금액과 무관하게 binary flagged."""
        result = c01_period_end_large(anomaly_feature_df)
        assert result.tolist() == [True, False, True, False, True, True, False, False]
        assert result.attrs["score_series"].tolist() == [
            1.0,
            0.0,
            1.0,
            0.0,
            1.0,
            1.0,
            0.0,
            0.0,
        ]

    def test_non_period_end_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """월말 아닌 행은 고액이어도 not flagged."""
        result = c01_period_end_large(anomaly_feature_df)
        assert not result[3]  # is_period_end=False, amount=80e6

    def test_missing_feature_returns_false(self) -> None:
        """is_period_end 피처 미존재 시 모두 False."""
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        assert not c01_period_end_large(df).any()

    def test_period_end_start_and_mid_month_toy_cases(self) -> None:
        """toy 3케이스: 기말=1, 기초=1, 월중=0."""
        df = pd.DataFrame({
            "document_id": ["END", "START", "MID"],
            "posting_date": pd.to_datetime(["2025-01-30", "2025-02-03", "2025-02-15"]),
            "debit_amount": [1.0, 2.0, 999999.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "is_period_end": [True, True, False],
            "source": ["manual", "manual", "manual"],
        })

        result = c01_period_end_large(df, period_end_margin_days=5)

        assert result.tolist() == [True, True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0]
        assert result.attrs["row_annotations"][0]["period_phase"] == "end"
        assert result.attrs["row_annotations"][1]["period_phase"] == "start"
        assert result.attrs["breakdown"]["period_end_rows"] == 1
        assert result.attrs["breakdown"]["period_start_rows"] == 1

    def test_period_start_column_is_used_before_date_inference(self) -> None:
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-02-15"]),
            "is_period_end": [False],
            "is_period_start": [True],
        })

        result = c01_period_end_large(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]
        assert result.attrs["row_annotations"][0]["period_phase"] == "start"

    def test_exposes_l304_binary_breakdown_and_annotations(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "posting_date": pd.to_datetime(["2025-01-31", "2025-02-01", "2025-02-10"]),
            "debit_amount": [1000.0, 100.0, 500.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "is_period_end": [True, True, False],
            "created_by": ["u1", "u2", "u3"],
            "approved_by": ["mgr", "mgr", "u3"],
            "source": ["manual", "batch", "manual"],
            "business_process": ["R2R", "R2R", "P2P"],
            "account_group": ["revenue", "expense", "expense"],
            "gl_account": ["4000", "5000", "5000"],
        })

        result = c01_period_end_large(df)

        assert set(result.attrs["score_series"].unique()) == {0.0, 1.0}
        assert result.attrs["breakdown"] == {
            "flagged_rows": 2,
            "period_end_rows": 1,
            "period_start_rows": 1,
            "source_counts": {"manual": 1, "batch": 1},
        }
        assert result.attrs["row_annotations"][0]["period_phase"] == "end"
        assert result.attrs["row_annotations"][0]["document_id"] == "D1"
        assert result.attrs["row_annotations"][1]["period_phase"] == "start"

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


    def test_weekend_entry_exposes_score_breakdown_and_annotations(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3", "D4"],
            "is_weekend": [True, False, True, False],
            "is_holiday": [False, True, True, False],
            "source": ["batch", "manual", "system", "manual"],
        })

        result = c02_weekend_entry(df)

        assert result.tolist() == [True, True, True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0, 0.0]
        breakdown = result.attrs["breakdown"]
        assert breakdown["flagged_docs"] == 3
        assert breakdown["weekend_rows"] == 2
        assert breakdown["holiday_rows"] == 2
        assert breakdown["source_counts"] == {"batch": 1, "manual": 1, "system": 1}
        annotations = result.attrs["row_annotations"]
        assert annotations[0]["score"] == 1.0
        assert annotations[0]["source"] == "batch"
        assert annotations[1]["is_holiday"] is True
        assert annotations[2]["is_weekend"] is True

    def test_weekend_entry_scores_automated_source_as_binary_hit(self) -> None:
        df = pd.DataFrame({
            "is_weekend": [True, True],
            "is_holiday": [False, False],
            "source": ["batch", "manual"],
        })

        result = c02_weekend_entry(df)

        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]


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

    def test_after_hours_metadata_is_binary_and_source_neutral(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "debit_amount": [100.0, 100.0, 100.0],
            "is_after_hours": [True, True, False],
            "posting_date": pd.to_datetime([
                "2025-01-01 23:30:00",
                "2025-01-02 02:15:00",
                "2025-01-02 14:00:00",
            ]),
            "source": ["manual", "batch", "manual"],
            "created_by": ["USR01", "BATCH_JOB", "USR02"],
        })

        result = c03_after_hours_entry(df)

        assert result.tolist() == [True, True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0]
        assert result.attrs["breakdown"]["flagged_rows"] == 2
        assert result.attrs["breakdown"]["after_hours_rows"] == 2
        assert "bucket" not in result.attrs["row_annotations"][0]
        assert "source_category" not in result.attrs["row_annotations"][1]
        assert result.attrs["row_annotations"][0]["score"] == 1.0
        assert result.attrs["row_annotations"][1]["score"] == 1.0

    def test_automated_source_after_hours_scores_one(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2"],
            "is_after_hours": [True, True],
            "posting_date": pd.to_datetime([
                "2025-01-02 23:30:00",
                "2025-01-03 02:30:00",
            ]),
            "source": ["automated", "manual"],
            "created_by": ["USR01", "USR02"],
        })

        result = c03_after_hours_entry(df)

        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]
        assert result.attrs["breakdown"]["source_counts"] == {"automated": 1, "manual": 1}

    def test_binary_scores_include_non_after_hours_zero(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2"],
            "is_after_hours": [True, False],
            "source": ["automated", "manual"],
        })

        result = c03_after_hours_entry(df)

        assert result.tolist() == [True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 0.0]


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

    def test_exposes_gap_direction_buckets_scores_and_annotations(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3", "D4", "D5", "D6"],
            "posting_date": pd.to_datetime([
                "2024-02-15", "2024-03-20", "2024-05-10",
                "2024-01-01", "2024-01-01", "2024-01-01",
            ]),
            "document_date": pd.to_datetime([
                "2024-01-01", "2024-01-01", "2024-01-01",
                "2024-02-15", "2024-03-20", "2024-05-10",
            ]),
            "days_backdated": [45, 79, 130, -45, -79, -130],
            "source": ["manual"] * 6,
        })

        result = c04_backdated_entry(df, threshold_days=30)

        assert result.tolist() == [True] * 6
        assert result.attrs["score_series"].tolist() == [0.45, 0.60, 0.75, 0.45, 0.60, 0.75]
        assert result.attrs["breakdown"]["direction_counts"] == {
            "late_posting": 3,
            "forward_date_gap": 3,
        }
        assert result.attrs["breakdown"]["bucket_counts"] == {
            "late_moderate_gap": 1,
            "late_large_gap": 1,
            "late_extreme_gap": 1,
            "forward_moderate_gap": 1,
            "forward_large_gap": 1,
            "forward_extreme_gap": 1,
        }
        assert result.attrs["row_annotations"][0]["bucket"] == "late_moderate_gap"
        assert result.attrs["row_annotations"][4]["direction"] == "forward_date_gap"
        assert result.attrs["row_annotations"][5]["abs_gap_days"] == 130
        assert result.attrs["row_annotations"][5]["score"] == 0.75


# ── L1-08 기간 불일치 ────────────────────────────────────────


class TestL1_08:
    def test_mismatch_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert result[2]
        assert result[5]

    def test_match_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert not result[0]

    def test_strict_mode_keeps_raw_mismatch(self) -> None:
        df = pd.DataFrame({
            "fiscal_period": [13],
            "posting_date": pd.to_datetime(["2025-12-31"]),
            "document_type": ["SA"],
            "source": ["adjustment"],
            "fiscal_period_mismatch": [True],
        })

        result = c05_fiscal_period_mismatch(
            df,
            policy={
                "strict_mode": True,
                "allow_special_periods": True,
                "special_periods": [13],
                "special_period_allowed_sources": ["adjustment"],
            },
        )

        assert result[0]
        assert result.attrs["policy_exempted_count"] == 0

    def test_special_period_policy_exempts_allowed_adjustment(self) -> None:
        df = pd.DataFrame({
            "fiscal_period": [13, 13],
            "posting_date": pd.to_datetime(["2025-12-31", "2025-12-31"]),
            "document_type": ["SA", "SA"],
            "source": ["adjustment", "manual"],
            "fiscal_period_mismatch": [True, True],
        })

        result = c05_fiscal_period_mismatch(
            df,
            policy={
                "strict_mode": False,
                "allow_special_periods": True,
                "special_periods": [13],
                "special_period_allowed_sources": ["adjustment"],
            },
        )

        assert not result[0]
        assert result[1]
        assert result.attrs["raw_fiscal_period_mismatch_count"] == 2
        assert result.attrs["policy_exempted_count"] == 1
        assert result.attrs["breakdown"]["final_l108_rows"] == 1

    def test_process_basis_policy_exempts_document_date_period(self) -> None:
        df = pd.DataFrame({
            "fiscal_period": [1, 1],
            "posting_date": pd.to_datetime(["2025-05-16", "2025-05-16"]),
            "document_date": pd.to_datetime(["2025-01-09", "2025-01-09"]),
            "business_process": ["H2R", "R2R"],
            "fiscal_period_mismatch": [True, True],
        })

        result = c05_fiscal_period_mismatch(
            df,
            policy={
                "strict_mode": False,
                "fiscal_year_start": 1,
                "period_basis_by_process": {"H2R": "document_date"},
            },
        )

        assert not result[0]
        assert result[1]
        assert result.attrs["policy_exempted_count"] == 1

    def test_confirmed_hit_keeps_boolean_result_and_surfaces_phase1_score_context(self) -> None:
        df = pd.DataFrame({
            "document_id": ["DOC-1", "DOC-2"],
            "fiscal_period": [1, 2],
            "posting_date": pd.to_datetime(["2025-03-31", "2025-02-15"]),
            "source": ["manual", "automated"],
            "is_period_end": [True, False],
            "is_manual_je": [True, False],
            "days_backdated": [45, 0],
            "exceeds_threshold": [True, False],
            "fiscal_period_mismatch": [True, False],
        })

        result = c05_fiscal_period_mismatch(df)

        assert result.tolist() == [True, False]
        # L1-08 is a binary PHASE1 rule; context reasons annotate, not score-escalate.
        assert result.attrs["score_series"].tolist() == [1.0, 0.0]
        assert result.attrs["breakdown"]["corroborated_rows"] == 1
        annotation = result.attrs["row_annotations"][0]
        assert annotation["bucket"] == "period_mismatch_corroborated"
        assert annotation["actual_period"] == 1
        assert annotation["expected_period"] == 3
        assert annotation["period_distance"] == 2
        assert annotation["score"] == 1.0
        assert set(annotation["context_reasons"]) == {
            "period_end",
            "manual_entry",
            "high_amount",
            "date_gap",
        }


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

    def test_description_quality_metadata_splits_quality_buckets(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3", "D4"],
            "description_quality": ["missing", "corrupted", "poor", "normal"],
            "description_line_missing": [True, False, False, False],
            "description_header_missing": [True, False, False, False],
            "description_both_missing": [True, False, False, False],
        })

        result = c06_missing_or_corrupted_description(df)

        assert result.attrs["score_series"].tolist() == [0.45, 0.55, 0.50, 0.0]
        assert result.attrs["breakdown"]["missing_rows"] == 1
        assert result.attrs["breakdown"]["corrupted_rows"] == 1
        assert result.attrs["breakdown"]["poor_legacy_rows"] == 1
        assert result.attrs["row_annotations"][0]["bucket"] == "missing"
        assert result.attrs["row_annotations"][2]["bucket"] == "corrupted_legacy_poor"

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
        assert result.attrs["score_series"].iloc[3] == 0.25
        assert result.attrs["breakdown"]["high_amount_review_rows"] == 1
        assert result.attrs["row_annotations"][3]["bucket"] == "low_zscore"

    def test_zscore_bands_only_change_priority_not_detection(self) -> None:
        df = pd.DataFrame({
            "debit_amount": [100.0, 120.0, 140.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "amount_zscore": [3.5, 6.0, 12.0],
        })
        result = c08_amount_outlier(
            df,
            zscore_threshold=3.0,
            min_amount_quantile=0.0,
        )

        assert result.tolist() == [True, True, True]
        assert result.attrs["score_series"].tolist() == [0.25, 0.45, 0.70]
        assert [result.attrs["row_annotations"][i]["bucket"] for i in range(3)] == [
            "low_zscore",
            "medium_zscore",
            "high_zscore",
        ]

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

    def test_exposes_aging_and_open_amount_buckets(self) -> None:
        """Flagged suspense rows carry aging/open amount buckets and row scores."""
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3", "D4"],
            "gl_account": ["2190", "2190", "2190", "2190"],
            "posting_date": pd.to_datetime(
                ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-15"]
            ),
            "is_suspense_account": [True, True, True, True],
            "amount_open": [1000.0, 500.0, 100.0, 1000.0],
        })

        result = c10_suspense_account(df, threshold_days=30)

        assert result.tolist() == [True, True, True, False]
        assert result.attrs["score_series"].tolist() == [0.80, 0.60, 0.45, 0.0]
        assert result.attrs["breakdown"]["aging_bucket_counts"] == {
            "aging_over_90": 1,
            "aging_60_90": 1,
            "aging_30_60": 1,
        }
        assert result.attrs["breakdown"]["open_amount_bucket_counts"] == {
            "open_amount_high": 1,
            "open_amount_medium": 1,
            "open_amount_low": 1,
        }
        assert result.attrs["breakdown"]["high_open_amount_rows"] == 1
        assert result.attrs["row_annotations"][0]["aging_bucket"] == "aging_over_90"
        assert result.attrs["row_annotations"][0]["open_amount_bucket"] == "open_amount_high"
        assert result.attrs["row_annotations"][0]["score"] == 0.8

    def test_missing_prerequisites_returns_false(self) -> None:
        """필수 컬럼 부족 → 전체 False."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c10_suspense_account(df).any()


class TestL4_05:
    def test_lone_automated_source_is_included_in_behavior_population(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "created_by": ["AUTOUSER"] * 3,
            "approved_by": ["MGR"] * 3,
            "posting_date": pd.to_datetime([
                "2025-01-02 00:01:00",
                "2025-01-02 00:02:00",
                "2025-01-02 00:03:00",
            ]),
            "approval_date": pd.to_datetime([
                "2025-01-02 00:20:00",
                "2025-01-02 00:20:00",
                "2025-01-02 00:20:00",
            ]),
            "time_zone_category": ["midnight"] * 3,
            "source": ["automated"] * 3,
            "batch_id": [None] * 3,
            "job_id": [None] * 3,
        })

        result = c12_abnormal_hours_concentration(df, auto_entry_sources=["automated"])

        assert result.tolist() == [True, True, True]
        assert result.attrs["breakdown"]["low_volume_midnight_rows"] == 3
        assert result.attrs["breakdown"]["manual_user_count"] == 1

    def test_partial_identity_automated_source_enters_behavior_population(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "created_by": ["AUTOUSER"] * 3,
            "approved_by": ["MGR"] * 3,
            "posting_date": pd.to_datetime([
                "2025-01-02 00:01:00",
                "2025-01-02 00:02:00",
                "2025-01-02 00:03:00",
            ]),
            "approval_date": pd.to_datetime([
                "2025-01-02 00:20:00",
                "2025-01-02 00:20:00",
                "2025-01-02 00:20:00",
            ]),
            "time_zone_category": ["midnight"] * 3,
            "source": ["automated"] * 3,
            "batch_id": ["BATCH-1"] * 3,
            "job_id": [None] * 3,
        })

        result = c12_abnormal_hours_concentration(df, auto_entry_sources=["automated"])

        assert result.tolist() == [True, True, True]
        assert result.attrs["breakdown"]["manual_user_count"] == 1

    def test_missing_identity_columns_use_lone_branch_for_behavior_population(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "created_by": ["AUTOUSER"] * 3,
            "approved_by": ["MGR"] * 3,
            "posting_date": pd.to_datetime([
                "2025-01-02 00:01:00",
                "2025-01-02 00:02:00",
                "2025-01-02 00:03:00",
            ]),
            "approval_date": pd.to_datetime([
                "2025-01-02 00:20:00",
                "2025-01-02 00:20:00",
                "2025-01-02 00:20:00",
            ]),
            "time_zone_category": ["midnight"] * 3,
            "source": ["automated"] * 3,
        })

        result = c12_abnormal_hours_concentration(df, auto_entry_sources=["automated"])

        assert result.tolist() == [True, True, True]
        assert result.attrs["breakdown"]["manual_user_count"] == 1
