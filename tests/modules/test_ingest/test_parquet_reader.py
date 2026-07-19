"""parquet_reader 테스트 — 기본 읽기, 타입 보존."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingest.models import ReadResult
from src.ingest.parquet_reader import read_parquet


class TestReadParquet:
    """Parquet 리더 기본 기능."""

    def test_basic_read(self, valid_parquet: Path) -> None:
        """정상 parquet → ReadResult with DataFrame."""
        result = read_parquet(valid_parquet)

        assert isinstance(result, ReadResult)
        assert result.sheets == ["Sheet1"]
        assert result.active_sheet == "Sheet1"
        assert result.source_format == "parquet"
        assert result.encoding is None

        df = result.raw_data["Sheet1"]
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    def test_type_preservation(self, valid_parquet: Path) -> None:
        """Parquet은 타입 보존 — int/float이 str로 변환되지 않아야 함."""
        result = read_parquet(valid_parquet)
        df = result.raw_data["Sheet1"]

        # journal_id는 int, amount는 float 유지
        assert pd.api.types.is_integer_dtype(df["journal_id"])
        assert pd.api.types.is_float_dtype(df["amount"])

    def test_normalized_sheets(self, valid_parquet: Path) -> None:
        """시트 정규화 — sheets=["Sheet1"]."""
        result = read_parquet(valid_parquet)
        assert result.sheets == ["Sheet1"]
        assert "Sheet1" in result.raw_data
