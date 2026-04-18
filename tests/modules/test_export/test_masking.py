"""PII 마스킹 유틸리티 테스트."""

from __future__ import annotations

import re

import pandas as pd

from src.export.masking import mask_dataframe


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["D001", "D002", "D003"],
            "created_by": ["alice", "bob", "alice"],
            "approved_by": ["manager1", None, "manager2"],
            "auxiliary_account_number": ["1234567890", "ABC", None],
            "auxiliary_account_label": ["거래처A코드", "단명", ""],
            "amount": [100, 200, 300],
        }
    )


class TestMaskDataframe:
    def test_original_dataframe_unchanged(self) -> None:
        # Why: Streamlit session_state 공유 시 원본 오염을 막는 핵심 보장.
        df = _sample_df()
        snapshot = df.copy()
        _ = mask_dataframe(df)
        pd.testing.assert_frame_equal(df, snapshot)

    def test_hash_method_produces_8_hex(self) -> None:
        df = _sample_df()
        masked = mask_dataframe(df)
        for value in masked["created_by"]:
            assert re.fullmatch(r"[0-9a-f-]{8}", value), value

    def test_hash_is_deterministic(self) -> None:
        # Why: 같은 입력은 같은 출력 → 다른 보고서 간 동일 인물 매칭 가능.
        df = _sample_df()
        m1 = mask_dataframe(df)
        m2 = mask_dataframe(df)
        pd.testing.assert_series_equal(m1["created_by"], m2["created_by"])

    def test_hash_handles_none(self) -> None:
        df = _sample_df()
        masked = mask_dataframe(df)
        # approved_by의 None 값이 sentinel("--------")로 치환되었는지 확인
        assert masked["approved_by"].iloc[1] == "--------"

    def test_partial_mask_preserves_last_4(self) -> None:
        df = _sample_df()
        masked = mask_dataframe(df)
        assert masked["auxiliary_account_number"].iloc[0] == "****7890"

    def test_partial_mask_short_value_fully_masked(self) -> None:
        # Why: 원본 길이 ≤ visible(4)이면 의미 있는 마스킹이 불가하므로 ****.
        df = _sample_df()
        masked = mask_dataframe(df)
        assert masked["auxiliary_account_number"].iloc[1] == "****"

    def test_partial_mask_handles_none_and_empty(self) -> None:
        df = _sample_df()
        masked = mask_dataframe(df)
        assert masked["auxiliary_account_number"].iloc[2] == "****"
        assert masked["auxiliary_account_label"].iloc[2] == "****"

    def test_non_target_columns_unchanged(self) -> None:
        df = _sample_df()
        masked = mask_dataframe(df)
        pd.testing.assert_series_equal(masked["amount"], df["amount"])
        pd.testing.assert_series_equal(masked["document_id"], df["document_id"])

    def test_no_target_columns_returns_copy(self) -> None:
        # Why: 마스킹 대상 컬럼이 하나도 없으면 안전한 복사본을 반환해야 함.
        df = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})
        masked = mask_dataframe(df)
        assert masked is not df
        pd.testing.assert_frame_equal(masked, df)

    def test_custom_columns_argument(self) -> None:
        df = pd.DataFrame({"user_id": ["u1", "u2"]})
        masked = mask_dataframe(df, columns={"user_id": "hash"})
        assert all(re.fullmatch(r"[0-9a-f]{8}", v) for v in masked["user_id"])
