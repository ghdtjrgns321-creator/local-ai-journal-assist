"""Mojibake repair tests."""

from __future__ import annotations

import pandas as pd

from src.ingest.text_mojibake import repair_dataframe_text_mojibake


def _ptcp154_mojibake(text: str) -> str:
    return text.encode("utf-8").decode("ptcp154")


def test_repairs_korean_utf8_decoded_as_ptcp154() -> None:
    df = pd.DataFrame({
        "document_id": ["D1"],
        "line_text": [_ptcp154_mojibake("수기 분개 우회, 기초·기말")],
    })

    repaired = repair_dataframe_text_mojibake(df)

    assert repaired.loc[0, "line_text"] == "수기 분개 우회, 기초·기말"


def test_leaves_normal_korean_and_english_unchanged() -> None:
    df = pd.DataFrame({
        "line_text": ["정상 적요", "manual accrual", "R2R close"],
    })

    repaired = repair_dataframe_text_mojibake(df)

    assert repaired.equals(df)
