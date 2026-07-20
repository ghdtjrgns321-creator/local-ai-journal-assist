"""L3-04~L3-07, L4-03, L3-09 피처 기반 이상 징후 룰 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c05_fiscal_period_mismatch,
    c08_amount_outlier,
    c10_suspense_account,
    c12_abnormal_hours_concentration,
)


@pytest.fixture
def anomaly_feature_df() -> pd.DataFrame:
    """L3/L4 피처가 사전 포함된 테스트 DataFrame (8행)."""
    return pd.DataFrame(
        {
            "debit_amount": [100e6, 50e6, 10e6, 300e6, 5e6, 200e6, 30e6, 60e6],
            "credit_amount": [0.0] * 8,
            "is_period_end": [True, False, True, False, True, True, False, False],
            "is_weekend": [True, False, False, True, False, False, True, False],
            "is_holiday": [False, False, True, False, False, False, False, False],
            "is_after_hours": [False, True, False, False, True, False, False, False],
            "days_backdated": [0, 45, -5, 31, 10, 0, -35, 29],
            "fiscal_period_mismatch": [False, False, True, False, False, True, False, False],
            "description_quality": [
                "normal",
                "missing",
                "corrupted",
                "normal",
                "normal",
                "missing",
                "normal",
                "corrupted",
            ],
            "has_risk_keyword": ["low", "high", "low", "medium", "low", "low", "low", "high"],
            "amount_zscore": [1.0, 2.5, 0.5, 3.5, -4.0, 2.0, 0.3, 1.5],
        }
    )


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
        df = pd.DataFrame(
            {
                "document_id": ["END", "START", "MID"],
                "posting_date": pd.to_datetime(["2025-01-30", "2025-02-03", "2025-02-15"]),
                "debit_amount": [1.0, 2.0, 999999.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "is_period_end": [True, True, False],
                "source": ["manual", "manual", "manual"],
            }
        )

        result = c01_period_end_large(df, period_end_margin_days=5)

        assert result.tolist() == [True, True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0]
        assert result.attrs["row_annotations"][0]["period_phase"] == "end"
        assert result.attrs["row_annotations"][1]["period_phase"] == "start"
        assert result.attrs["breakdown"]["period_end_rows"] == 1
        assert result.attrs["breakdown"]["period_start_rows"] == 1

    def test_period_start_column_is_used_before_date_inference(self) -> None:
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2025-02-15"]),
                "is_period_end": [False],
                "is_period_start": [True],
            }
        )

        result = c01_period_end_large(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]
        assert result.attrs["row_annotations"][0]["period_phase"] == "start"

    def test_exposes_l304_binary_breakdown_and_annotations(self) -> None:
        df = pd.DataFrame(
            {
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
            }
        )

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
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "is_weekend": [True, False, True, False],
                "is_holiday": [False, True, True, False],
                "source": ["batch", "manual", "system", "manual"],
            }
        )

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
        df = pd.DataFrame(
            {
                "is_weekend": [True, True],
                "is_holiday": [False, False],
                "source": ["batch", "manual"],
            }
        )

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
        df = pd.DataFrame(
            {
                "debit_amount": [100.0, 100.0, 100.0, 100.0],
                "time_zone_category": ["normal", "overtime", "midnight", "unknown"],
            }
        )
        result = c03_after_hours_entry(df)
        # Why: overtime은 L4-05, 주말/공휴일은 L3-05가 담당한다.
        assert result.tolist() == [False, False, False, False]

    def test_time_zone_category_does_not_expand_after_hours(self) -> None:
        """time_zone_category가 있어도 L3-06은 is_after_hours만 따른다."""
        df = pd.DataFrame(
            {
                "debit_amount": [100.0, 100.0, 100.0, 100.0],
                "is_after_hours": [True, False, False, False],
                "time_zone_category": ["normal", "normal", "midnight", "normal"],
            }
        )
        result = c03_after_hours_entry(df)
        assert result.tolist() == [True, False, False, False]

    def test_after_hours_metadata_is_binary_and_source_neutral(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "debit_amount": [100.0, 100.0, 100.0],
                "is_after_hours": [True, True, False],
                "posting_date": pd.to_datetime(
                    [
                        "2025-01-01 23:30:00",
                        "2025-01-02 02:15:00",
                        "2025-01-02 14:00:00",
                    ]
                ),
                "source": ["manual", "batch", "manual"],
                "created_by": ["USR01", "BATCH_JOB", "USR02"],
            }
        )

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
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "is_after_hours": [True, True],
                "posting_date": pd.to_datetime(
                    [
                        "2025-01-02 23:30:00",
                        "2025-01-03 02:30:00",
                    ]
                ),
                "source": ["automated", "manual"],
                "created_by": ["USR01", "USR02"],
            }
        )

        result = c03_after_hours_entry(df)

        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]
        assert result.attrs["breakdown"]["source_counts"] == {"automated": 1, "manual": 1}

    def test_binary_scores_include_non_after_hours_zero(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "is_after_hours": [True, False],
                "source": ["automated", "manual"],
            }
        )

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

    def test_exposes_binary_scores_breakdown_and_annotations(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4", "D5", "D6", "D7"],
                "posting_date": pd.to_datetime(
                    [
                        "2024-02-15",
                        "2024-03-20",
                        "2024-05-10",
                        "2024-01-01",
                        "2024-01-01",
                        "2024-01-01",
                        "2024-01-20",
                    ]
                ),
                "document_date": pd.to_datetime(
                    [
                        "2024-01-01",
                        "2024-01-01",
                        "2024-01-01",
                        "2024-02-15",
                        "2024-03-20",
                        "2024-05-10",
                        "2024-01-01",
                    ]
                ),
                "days_backdated": [45, 79, 130, -45, -79, -130, 19],
                "source": ["manual"] * 7,
                "created_by": ["USR1", "USR2", "USR3", "USR4", "USR5", "USR6", "USR7"],
                "business_process": ["R2R", "R2R", "P2P", "P2P", "O2C", "O2C", "R2R"],
                "document_type": ["SA", "SA", "KR", "KR", "DR", "DR", "SA"],
            }
        )

        result = c04_backdated_entry(df, threshold_days=30)

        assert result.tolist() == [True, True, True, True, True, True, False]
        assert set(result.attrs["score_series"].unique()) == {0.0, 1.0}
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0]
        assert result.attrs["breakdown"] == {
            "flagged_rows": 6,
            "threshold_days": 30,
        }
        assert "bucket_" + "counts" not in result.attrs["breakdown"]
        assert "direction_" + "counts" not in result.attrs["breakdown"]
        assert "bucket" not in result.attrs["row_annotations"][0]
        assert "direction" not in result.attrs["row_annotations"][4]
        assert result.attrs["row_annotations"][0]["score"] == 1.0
        assert result.attrs["row_annotations"][0]["days_backdated"] == 45
        assert result.attrs["row_annotations"][5]["abs_gap_days"] == 130
        assert result.attrs["row_annotations"][5]["threshold_days"] == 30
        assert result.attrs["row_annotations"][5]["document_id"] == "D6"
        assert result.attrs["row_annotations"][5]["source"] == "manual"
        assert result.attrs["row_annotations"][5]["created_by"] == "USR6"
        assert result.attrs["row_annotations"][5]["business_process"] == "O2C"
        assert result.attrs["row_annotations"][5]["document_type"] == "DR"


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
        df = pd.DataFrame(
            {
                "fiscal_period": [13],
                "posting_date": pd.to_datetime(["2025-12-31"]),
                "document_type": ["SA"],
                "source": ["adjustment"],
                "fiscal_period_mismatch": [True],
            }
        )

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
        df = pd.DataFrame(
            {
                "fiscal_period": [13, 13],
                "posting_date": pd.to_datetime(["2025-12-31", "2025-12-31"]),
                "document_type": ["SA", "SA"],
                "source": ["adjustment", "manual"],
                "fiscal_period_mismatch": [True, True],
            }
        )

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
        df = pd.DataFrame(
            {
                "fiscal_period": [1, 1],
                "posting_date": pd.to_datetime(["2025-05-16", "2025-05-16"]),
                "document_date": pd.to_datetime(["2025-01-09", "2025-01-09"]),
                "business_process": ["H2R", "R2R"],
                "fiscal_period_mismatch": [True, True],
            }
        )

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
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-2"],
                "fiscal_period": [1, 2],
                "posting_date": pd.to_datetime(["2025-03-31", "2025-02-15"]),
                "source": ["manual", "automated"],
                "is_period_end": [True, False],
                "is_manual_je": [True, False],
                "days_backdated": [45, 0],
                "exceeds_threshold": [True, False],
                "fiscal_period_mismatch": [True, False],
            }
        )

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


# ── L4-03 이상 고액 (수행중요성 절대임계 binary) ─────────────


def _l403_mc(
    pbt_pct: float = 0.05,
    rev_pct: float = 0.005,
    pm_ratio: float = 0.75,
    materiality_amount: float = 0,
) -> dict:
    """테스트용 l403_materiality config 헬퍼."""
    return {
        "revenue_subtype_patterns": ["REVENUE"],
        "expense_subtype_patterns": ["COGS", "OPEX"],
        "exclude_subtype_patterns": ["ACCUMULATED", "ACCRUED", "PAYABLE", "RECEIVABLE"],
        "closing_subtype": "income_statement_close",
        "closing_header_patterns": ["손익 마감"],
        "pbt_pct": pbt_pct,
        "rev_pct": rev_pct,
        "pm_ratio": pm_ratio,
        "materiality_amount": materiality_amount,
    }


class TestL4_03:
    def test_above_threshold_flagged_binary(self) -> None:
        """PBT > 0 회사에서 PM 초과 고액 라인은 score=1.0으로 발화한다."""
        # PBT = rev(10_000) - exp(6_000) = 4_000
        # threshold = 4_000 * 0.05 * 0.75 = 150
        df = pd.DataFrame(
            {
                "company_code": ["C001"] * 5,
                "fiscal_year": [2024] * 5,
                "debit_amount": [0.0, 6_000.0, 200.0, 50.0, 10.0],
                "credit_amount": [10_000.0, 0.0, 0.0, 0.0, 0.0],
                "semantic_account_subtype": [
                    "REVENUE",
                    "COGS",
                    "OTHER",  # 발화 대상 (base_amount=200 >= 150)
                    "OTHER",  # 미발화 (base_amount=50 < 150)
                    "OTHER",  # 미발화
                ],
            }
        )
        result = c08_amount_outlier(df, materiality_config=_l403_mc())
        score = result.attrs["score_series"]

        # binary: 0.0 / 1.0 두 값만
        assert set(score.unique()).issubset({0.0, 1.0})
        # 발화: index 2 (base=200 >= threshold 150). numpy bool 이라 identity(is) 대신 truthy 검사.
        assert bool(result.iloc[2]) is True
        assert score.iloc[2] == 1.0
        # 미발화: index 3, 4
        assert not result.iloc[3]
        assert not result.iloc[4]
        # breakdown에 bucket 키 없어야 함
        bkd = result.attrs["breakdown"]
        for k in bkd:
            assert "zscore" not in k, f"구 bucket 키 잔존: {k}"
        # annotation에 threshold_basis 존재, bucket 키 없음
        ann = result.attrs["row_annotations"]
        for idx_key, v in ann.items():
            assert "bucket" not in v, f"annotation에 bucket 키 잔존: idx={idx_key}"
            assert "threshold_basis" in v

    def test_below_threshold_not_flagged(self) -> None:
        """PM 미만 라인은 발화 0이다."""
        # threshold = (10_000 - 6_000) * 0.05 * 0.75 = 150
        df = pd.DataFrame(
            {
                "company_code": ["C001"] * 3,
                "fiscal_year": [2024] * 3,
                "debit_amount": [6_000.0, 100.0, 50.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "semantic_account_subtype": ["COGS", "OTHER", "OTHER"],
            }
        )
        # revenue 없으면 PBT 음수 → revenue=0 → threshold=unset → 발화 0
        result = c08_amount_outlier(df, materiality_config=_l403_mc())
        assert not result.any()
        assert set(result.attrs["score_series"].unique()).issubset({0.0})

    def test_score_unique_values_binary(self) -> None:
        """score_series 고유값은 {0.0, 1.0} 부분집합이어야 한다. 0.25/0.45/0.70 금지."""
        df = pd.DataFrame(
            {
                "company_code": ["C001"] * 4,
                "fiscal_year": [2024] * 4,
                "debit_amount": [0.0, 500.0, 200.0, 10.0],
                "credit_amount": [10_000.0, 0.0, 0.0, 0.0],
                "semantic_account_subtype": ["REVENUE", "OPEX", "OTHER", "OTHER"],
            }
        )
        result = c08_amount_outlier(df, materiality_config=_l403_mc())
        unique = set(result.attrs["score_series"].unique())
        forbidden = {0.25, 0.45, 0.70}
        assert unique.issubset({0.0, 1.0}), f"binary 외 score 발생: {unique}"
        assert not unique & forbidden, f"구 bucket score 잔존: {unique & forbidden}"

    def test_threshold_unset_when_no_revenue(self) -> None:
        """매출/비용 데이터가 없으면 threshold=unset → 발화 0."""
        df = pd.DataFrame(
            {
                "company_code": ["C001"] * 3,
                "fiscal_year": [2024] * 3,
                "debit_amount": [1_000_000.0, 500_000.0, 200_000.0],
                "credit_amount": [0.0] * 3,
                "semantic_account_subtype": ["OTHER", "OTHER", "OTHER"],
            }
        )
        result = c08_amount_outlier(df, materiality_config=_l403_mc())
        assert not result.any()
        bkd = result.attrs["breakdown"]
        assert bkd["threshold_unset_company_years"] == 1

    def test_missing_required_columns_returns_false(self) -> None:
        """필수 컬럼(debit_amount, credit_amount) 미존재 시 모두 False."""
        df = pd.DataFrame({"company_code": ["C001"], "fiscal_year": [2024]})
        result = c08_amount_outlier(df, materiality_config=_l403_mc())
        assert not result.any()

    def test_closing_entries_excluded_from_revenue_benchmark(self) -> None:
        """연말 손익 마감 분개는 매출/비용 벤치마크 집계에서 제외돼야 한다.

        DataSynth는 마감분개를 income_statement_close subtype이 아니라 원래 손익
        subtype(REVENUE/COGS 등)으로 태깅하고 header_text에만 "손익 마감"을 남긴다.
        이를 제외하지 않으면 마감 차변이 매출 대변을 상쇄해 매출≈0 → 중요성 붕괴.
        """
        # 매출 인식(대변 10_000) + 같은 금액 마감분개(차변 10_000, "손익 마감" 헤더)
        # + COGS 6_000. 마감 제외 시 PBT = 10_000 - 6_000 = 4_000
        # threshold = 4_000 * 0.05 * 0.75 = 150 → 고액 라인(base 200) 발화
        df = pd.DataFrame(
            {
                "company_code": ["C001"] * 4,
                "fiscal_year": [2024] * 4,
                "debit_amount": [0.0, 10_000.0, 6_000.0, 200.0],
                "credit_amount": [10_000.0, 0.0, 0.0, 0.0],
                "semantic_account_subtype": ["REVENUE", "REVENUE", "COGS", "OTHER"],
                "header_text": [
                    "매출 인식",
                    "연말 손익 마감 - 2024",
                    "원가 인식",
                    "고액 전표",
                ],
            }
        )
        result = c08_amount_outlier(df, materiality_config=_l403_mc())
        # 마감분개가 제외되면 매출 10_000이 살아 threshold=150 → index 3(base 200) 발화
        assert bool(result.iloc[3]) is True, (
            "마감분개가 매출에서 제외되지 않아 매출이 상쇄됨 → threshold 산출 실패"
        )
        ann = result.attrs["row_annotations"].get(3, {})
        assert ann.get("threshold_basis") not in {"unset", None}


# ── L3-09 가수금 장기체류 ──────────────────────────────────────


class TestL3_09:
    def test_long_open_amount_flagged(self) -> None:
        """가계정 + 미정리금액 + 30일 이상 체류 → flagged."""
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25", "2025-03-25"]),
                "is_suspense_account": [True, True, False],
                "amount_open": [100000.0, 100000.0, 100000.0],
            }
        )
        result = c10_suspense_account(df)
        assert result[0]
        assert not result[1]
        assert not result[2]

    def test_cleared_entry_not_flagged(self) -> None:
        """정산 완료 또는 clear status면 장기체류로 보지 않음."""
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
                "settlement_date": pd.to_datetime(["2025-01-15", "2025-03-20"]),
                "settlement_status": ["settled", "cleared"],
                "is_suspense_account": [True, True],
            }
        )
        assert not c10_suspense_account(df).any()

    def test_is_cleared_false_fallback_flagged(self) -> None:
        """is_cleared=False를 미정리 상태로 사용."""
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25"]),
                "is_suspense_account": [True, True],
                "is_cleared": [False, False],
            }
        )
        result = c10_suspense_account(df)
        assert result[0]
        assert not result[1]

    def test_no_resolution_signal_returns_false(self) -> None:
        """미정리 여부를 판단할 입력이 없으면 보수적으로 False."""
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2025-01-01"]),
                "is_suspense_account": [True],
            }
        )
        assert not c10_suspense_account(df).any()

    def test_lettrage_date_fallback_flagged(self) -> None:
        """정산 정보가 없을 때 lettrage_date 부재를 보조 신호로 사용."""
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25"]),
                "is_suspense_account": [True, True],
                "lettrage_date": [pd.NaT, pd.NaT],
            }
        )
        result = c10_suspense_account(df)
        assert result[0]
        assert not result[1]

    def test_row_annotations_expose_threshold_days(self) -> None:
        """플래그 행에 aging과 고정 threshold를 남긴다."""
        df = pd.DataFrame(
            {
                "gl_account": ["2190", "2190"],
                "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25"]),
                "amount_open": [100000.0, 100000.0],
                "is_suspense_account": [True, True],
            }
        )
        result = c10_suspense_account(df, threshold_days=30)
        ann = result.attrs["row_annotations"][0]
        assert ann["gl_account"] == "2190"
        assert ann["aging_days"] == 83
        assert ann["threshold_days"] == 30
        assert result.attrs["breakdown"]["base_threshold_days"] == 30

    def test_exposes_binary_scores_breakdown_and_annotations(self) -> None:
        """Flagged suspense rows carry binary scores and factual aging/open amount evidence."""
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "gl_account": ["2190", "2190", "2190", "2190"],
                "posting_date": pd.to_datetime(
                    ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-15"]
                ),
                "is_suspense_account": [True, True, True, True],
                "amount_open": [1000.0, 500.0, 100.0, 1000.0],
            }
        )

        result = c10_suspense_account(df, threshold_days=30)

        assert result.tolist() == [True, True, True, False]
        assert set(result.attrs["score_series"].unique()) == {0.0, 1.0}
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0, 0.0]
        assert result.attrs["breakdown"] == {
            "base_threshold_days": 30,
            "flagged_rows": 3,
        }
        assert result.attrs["row_annotations"][0]["aging_days"] == 104
        assert result.attrs["row_annotations"][0]["open_amount"] == 1000.0
        assert result.attrs["row_annotations"][0]["score"] == 1.0
        assert result.attrs["row_annotations"][0]["document_id"] == "D1"
        assert result.attrs["row_annotations"][0]["posting_date"] == pd.Timestamp("2025-01-01")
        assert result.attrs["row_annotations"][0]["amount_open"] == 1000.0
        assert "aging_" + "bucket" not in result.attrs["row_annotations"][0]
        assert "open_amount_" + "bucket" not in result.attrs["row_annotations"][0]

    def test_missing_prerequisites_returns_false(self) -> None:
        """필수 컬럼 부족 → 전체 False."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c10_suspense_account(df).any()


class TestL4_05:
    def test_lone_automated_source_is_included_in_behavior_population(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "created_by": ["AUTOUSER"] * 3,
                "approved_by": ["MGR"] * 3,
                "posting_date": pd.to_datetime(
                    [
                        "2025-01-02 00:01:00",
                        "2025-01-02 00:02:00",
                        "2025-01-02 00:03:00",
                    ]
                ),
                "approval_date": pd.to_datetime(
                    [
                        "2025-01-02 00:20:00",
                        "2025-01-02 00:20:00",
                        "2025-01-02 00:20:00",
                    ]
                ),
                "time_zone_category": ["midnight"] * 3,
                "source": ["automated"] * 3,
                "batch_id": [None] * 3,
                "job_id": [None] * 3,
            }
        )

        result = c12_abnormal_hours_concentration(df, auto_entry_sources=["automated"])

        assert result.tolist() == [True, True, True]
        assert result.attrs["breakdown"]["low_volume_midnight_rows"] == 3
        assert result.attrs["breakdown"]["manual_user_count"] == 1

    def test_partial_identity_automated_source_enters_behavior_population(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "created_by": ["AUTOUSER"] * 3,
                "approved_by": ["MGR"] * 3,
                "posting_date": pd.to_datetime(
                    [
                        "2025-01-02 00:01:00",
                        "2025-01-02 00:02:00",
                        "2025-01-02 00:03:00",
                    ]
                ),
                "approval_date": pd.to_datetime(
                    [
                        "2025-01-02 00:20:00",
                        "2025-01-02 00:20:00",
                        "2025-01-02 00:20:00",
                    ]
                ),
                "time_zone_category": ["midnight"] * 3,
                "source": ["automated"] * 3,
                "batch_id": ["BATCH-1"] * 3,
                "job_id": [None] * 3,
            }
        )

        result = c12_abnormal_hours_concentration(df, auto_entry_sources=["automated"])

        assert result.tolist() == [True, True, True]
        assert result.attrs["breakdown"]["manual_user_count"] == 1

    def test_missing_identity_columns_use_lone_branch_for_behavior_population(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "created_by": ["AUTOUSER"] * 3,
                "approved_by": ["MGR"] * 3,
                "posting_date": pd.to_datetime(
                    [
                        "2025-01-02 00:01:00",
                        "2025-01-02 00:02:00",
                        "2025-01-02 00:03:00",
                    ]
                ),
                "approval_date": pd.to_datetime(
                    [
                        "2025-01-02 00:20:00",
                        "2025-01-02 00:20:00",
                        "2025-01-02 00:20:00",
                    ]
                ),
                "time_zone_category": ["midnight"] * 3,
                "source": ["automated"] * 3,
            }
        )

        result = c12_abnormal_hours_concentration(df, auto_entry_sources=["automated"])

        assert result.tolist() == [True, True, True]
        assert result.attrs["breakdown"]["manual_user_count"] == 1
