"""reader_api 테스트 — 확장자별 디스패치, 미지원 확장자."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.models import ReadResult
from src.ingest.reader_api import read_file


class TestDispatch:
    """확장자 기반 리더 디스패치."""

    def test_dispatch_xlsx(self, valid_xlsx: Path) -> None:
        """xlsx → excel_reader 경유."""
        result = read_file(valid_xlsx)
        assert isinstance(result, ReadResult)
        assert result.source_format == "xlsx"

    def test_dispatch_csv(self, valid_csv: Path) -> None:
        """csv → text_reader 경유."""
        result = read_file(valid_csv)
        assert isinstance(result, ReadResult)
        assert result.source_format == "csv"

    def test_dispatch_tsv(self, valid_tsv: Path) -> None:
        """tsv → text_reader 경유."""
        result = read_file(valid_tsv)
        assert isinstance(result, ReadResult)
        assert result.source_format == "tsv"

    def test_dispatch_parquet(self, valid_parquet: Path) -> None:
        """parquet → parquet_reader 경유."""
        result = read_file(valid_parquet)
        assert isinstance(result, ReadResult)
        assert result.source_format == "parquet"

    def test_dispatch_str_path(self, valid_csv: Path) -> None:
        """str 경로도 정상 처리."""
        result = read_file(str(valid_csv))
        assert isinstance(result, ReadResult)


class TestUnsupported:
    """미지원 확장자."""

    def test_unsupported_raises_value_error(self, tmp_path: Path) -> None:
        """미지원 확장자 → ValueError."""
        fake = tmp_path / "data.json"
        fake.write_text("{}")
        with pytest.raises(ValueError, match="지원하지 않는 파일 형식"):
            read_file(fake)
