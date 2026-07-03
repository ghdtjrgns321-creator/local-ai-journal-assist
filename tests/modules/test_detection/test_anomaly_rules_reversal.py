"""Unit tests for the L2-05 binary reversal-pattern helpers."""

from __future__ import annotations

import pandas as pd

from src.detection.anomaly_rules_reversal import (
    _s0_structural_reversal_reference,
    _s1_one_to_one_match,
    c11_reversal_entry,
)


def _core_df(**overrides: object) -> pd.DataFrame:
    data: dict[str, object] = {
        "document_id": ["D001", "D002"],
        "gl_account": ["1000", "1000"],
        "debit_amount": [1_000_000.0, 0.0],
        "credit_amount": [0.0, 1_000_000.0],
        "posting_date": pd.to_datetime(
            ["2025-01-01", "2025-02-10"]
        ),  # 40일 시차 (기본 45일 윈도우 내)
        "source": ["manual", "manual"],
    }
    data.update(overrides)
    return pd.DataFrame(data)


class TestS0StructuralReversalReference:
    def test_reversal_reference_field_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "original_document_id": ["", "D001"],
                "reversal_document_id": ["D002", ""],
            }
        )
        result = _s0_structural_reversal_reference(df)
        assert result.tolist() == [True, True]

    def test_reversal_reason_field_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "reversal_reason": ["", "01"],
            }
        )
        result = _s0_structural_reversal_reference(df)
        assert result.tolist() == [False, True]

    def test_missing_reference_columns_returns_false(self) -> None:
        df = pd.DataFrame({"document_id": ["D001"]})
        result = _s0_structural_reversal_reference(df)
        assert not result.any()


class TestS1OneToOneMatch:
    def test_same_account_opposite_side_within_default_window_flagged(self) -> None:
        result = _s1_one_to_one_match(_core_df())  # 40일 시차, 기본 45일 윈도우
        assert result.tolist() == [True, True]
        assert result.attrs["pair_details"][0]["counterpart_document_id"] == "D002"
        assert result.attrs["pair_details"][0]["gl_account"] == "1000"

    def test_gap_between_45_and_90_days_not_matched_by_default(self) -> None:
        # 60일 시차: 구 90일 윈도우에선 발화했으나 45일로 좁힌 기본 윈도우에선 미발화
        df = _core_df(posting_date=pd.to_datetime(["2025-01-01", "2025-03-02"]))
        assert not _s1_one_to_one_match(df).any()
        # 명시적으로 90일 윈도우를 주면 여전히 발화 (윈도우 파라미터 동작 검증)
        assert _s1_one_to_one_match(df, match_window_days=90).tolist() == [True, True]

    def test_same_document_not_flagged(self) -> None:
        df = _core_df(document_id=["D001", "D001"], posting_date=pd.to_datetime(["2025-01-01"] * 2))
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_different_account_not_matched(self) -> None:
        df = _core_df(gl_account=["1000", "2000"])
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_amount_mismatch_not_matched(self) -> None:
        df = _core_df(credit_amount=[0.0, 700_000.0])
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_near_but_not_exact_amount_not_matched_by_default(self) -> None:
        # 역분개는 exact reverse가 본질 → 기본 tolerance 0.0(±0%)에서 ±1% 미세차는 미발화.
        # 구 ±2%였다면 발화했을 케이스(정상 순환거래 우연 동액 오탐의 전형).
        df = _core_df(credit_amount=[0.0, 990_000.0])  # 원전표 1,000,000 대비 -1%
        assert not _s1_one_to_one_match(df).any()
        # 명시적으로 ±2%를 주면 발화 (tolerance 파라미터 동작 검증)
        assert _s1_one_to_one_match(df, amount_tolerance=0.02).tolist() == [True, True]

    def test_exact_amount_matched_at_zero_tolerance(self) -> None:
        # 정확일치는 기본 tolerance 0.0에서 발화(recall 유지).
        assert _s1_one_to_one_match(_core_df(), amount_tolerance=0.0).tolist() == [True, True]

    def test_multiline_float_sum_matched_at_zero_tolerance(self) -> None:
        # 다중 라인 전표 groupby-sum의 부동소수 오차(7×0.07=0.49000000000000005 vs 0.49,
        # 차이 5.5e-17)를 floor epsilon이 흡수해 tolerance=0.0에서도 정확일치로 발화해야 한다.
        # floor epsilon 없으면 [False]로 미탐(진짜 역분개 놓침).
        df = pd.DataFrame(
            {
                "document_id": ["D001"] * 7 + ["D002"],
                "gl_account": ["1000"] * 8,
                "debit_amount": [0.07] * 7 + [0.0],
                "credit_amount": [0.0] * 7 + [0.49],
                "posting_date": pd.to_datetime(["2025-01-01"] * 7 + ["2025-02-10"]),
            }
        )
        result = _s1_one_to_one_match(df, amount_tolerance=0.0)
        assert result.tolist() == [True] * 8

    def test_real_amount_difference_still_not_matched_with_floor(self) -> None:
        # floor epsilon(0.005)은 부동소수 오차만 흡수하고, 실제 금액 차이(0.5원)는 여전히 미발화.
        df = _core_df(
            debit_amount=[1_000_000.0, 0.0],
            credit_amount=[0.0, 1_000_000.5],  # 0.5원 실제 차이 (floor 0.005 초과)
        )
        assert not _s1_one_to_one_match(df, amount_tolerance=0.0).any()

    def test_date_outside_window_not_matched(self) -> None:
        df = _core_df(posting_date=pd.to_datetime(["2025-01-01", "2025-04-02"]))
        result = _s1_one_to_one_match(df, match_window_days=90)
        assert not result.any()

    def test_clearing_account_excluded(self) -> None:
        df = _core_df(gl_account=["2900", "2900"])
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_automated_source_mirror_pair_is_flagged(self) -> None:
        df = _core_df(source=["automated", "automated"])
        result = _s1_one_to_one_match(df)
        assert result.tolist() == [True, True]

    def test_missing_source_is_graceful(self) -> None:
        df = _core_df().drop(columns=["source"])
        result = _s1_one_to_one_match(df)
        assert result.tolist() == [True, True]


class TestC11ReversalEntry:
    def test_mirror_pair_scores_binary(self) -> None:
        result = c11_reversal_entry(_core_df())
        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]
        assert result.attrs["breakdown"] == {
            "flagged_rows": 2,
            "erp_rows": 0,
            "mirror_pair_rows": 2,
            "matched_docs": 2,
        }
        assert result.attrs["row_annotations"][0]["path"] == "B"
        assert result.attrs["row_annotations"][0]["score"] == 1.0

    def test_different_account_offset_is_not_reversal(self) -> None:
        df = _core_df(gl_account=["1000", "2000"])
        result = c11_reversal_entry(df)
        assert not result.any()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0]

    def test_single_document_debit_credit_is_not_reversal(self) -> None:
        df = _core_df(document_id=["D001", "D001"], posting_date=pd.to_datetime(["2025-01-01"] * 2))
        result = c11_reversal_entry(df)
        assert not result.any()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0]

    def test_automated_recurring_mirror_pair_scores_binary(self) -> None:
        df = _core_df(source=["recurring", "recurring"])
        result = c11_reversal_entry(df)
        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]

    def test_structural_reference_flagged_even_100_days_apart(self) -> None:
        df = _core_df(
            gl_account=["1000", "2000"],
            debit_amount=[123.0, 456.0],
            credit_amount=[0.0, 0.0],
            posting_date=pd.to_datetime(["2025-01-01", "2025-04-11"]),
            original_document_id=["", "D001"],
            reversal_document_id=["D002", ""],
            source=["automated", "automated"],
        )
        result = c11_reversal_entry(df)
        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]
        assert result.attrs["row_annotations"][0]["path"] == "A"

    def test_s2b_shaped_single_unbalanced_document_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D001", "D001", "D001"],
                "gl_account": ["500260", "500530", "2100", "2000"],
                "debit_amount": [72_000.0, 3_523.0, 51_421.0, 0.0],
                "credit_amount": [0.0, 0.0, 0.0, 24_102.0],
                "posting_date": pd.to_datetime(["2025-12-27"] * 4),
                "source": ["manual"] * 4,
            }
        )
        result = c11_reversal_entry(df)
        assert not result.any()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0, 0.0]

    def test_missing_core_columns_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_single_row_returns_false(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001"],
                "gl_account": ["1000"],
                "debit_amount": [100.0],
                "credit_amount": [0.0],
                "posting_date": pd.to_datetime(["2025-06-01"]),
            }
        )
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_annotations_preserve_non_integer_index(self) -> None:
        df = _core_df()
        df.index = ["row-a", "row-b"]
        result = c11_reversal_entry(df)
        assert result["row-a"]
        assert result.attrs["row_annotations"]["row-a"]["counterpart_document_id"] == "D002"
