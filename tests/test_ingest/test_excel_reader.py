"""excel_reader 테스트 — xlsx 단일/멀티시트, 병합셀, 빈시트."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ingest.excel_reader import read_excel
from src.ingest.models import ReadResult


class TestReadXlsx:
    """xlsx 리더 기본 기능."""

    def test_single_sheet(self, valid_xlsx: Path) -> None:
        """단일 시트 xlsx → sheets 1개, raw_data에 DataFrame 포함."""
        result = read_excel(valid_xlsx)

        assert isinstance(result, ReadResult)
        assert len(result.sheets) == 1
        assert result.active_sheet == result.sheets[0]
        assert result.source_format == "xlsx"

        df = result.raw_data[result.sheets[0]]
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2  # 헤더행 + 데이터행 (header=None이므로 둘 다 행)

    def test_multi_sheet(self, xlsx_multi_sheet: Path) -> None:
        """멀티시트 xlsx → 3개 시트 모두 raw_data에 포함."""
        result = read_excel(xlsx_multi_sheet)

        assert result.sheets == ["매출", "매입", "빈시트"]
        assert result.active_sheet == "매출"
        assert len(result.raw_data) == 3

        # 데이터 시트: 헤더 + 데이터 = 2행
        assert len(result.raw_data["매출"]) == 2
        assert len(result.raw_data["매입"]) == 2

        # 빈 시트: 빈 DataFrame
        assert result.raw_data["빈시트"].empty

    def test_source_format(self, valid_xlsx: Path) -> None:
        """source_format이 "xlsx"로 설정되는지 확인."""
        result = read_excel(valid_xlsx)
        assert result.source_format == "xlsx"

    def test_encoding_is_none(self, valid_xlsx: Path) -> None:
        """엑셀은 encoding=None."""
        result = read_excel(valid_xlsx)
        assert result.encoding is None


class TestMergedCells:
    """xlsx 병합셀 해제 + 값 복제."""

    def test_horizontal_merge(self, xlsx_with_merged_cells: Path) -> None:
        """가로 병합(A1:B1) 해제 후 양쪽 셀에 동일 값 복제."""
        result = read_excel(xlsx_with_merged_cells)
        df = result.raw_data[result.sheets[0]]

        # A1, B1 모두 "회사정보"여야 함
        assert df.iloc[0, 0] == "회사정보"
        assert df.iloc[0, 1] == "회사정보"

    def test_vertical_merge(self, xlsx_with_merged_cells: Path) -> None:
        """세로 병합(A3:A4) 해제 후 양쪽 행에 동일 값 복제."""
        result = read_excel(xlsx_with_merged_cells)
        df = result.raw_data[result.sheets[0]]

        # A3, A4 모두 "C001"이어야 함
        assert df.iloc[2, 0] == "C001"
        assert df.iloc[3, 0] == "C001"

    def test_non_merged_cells_preserved(self, xlsx_with_merged_cells: Path) -> None:
        """병합되지 않은 셀의 값은 그대로 유지."""
        result = read_excel(xlsx_with_merged_cells)
        df = result.raw_data[result.sheets[0]]

        assert df.iloc[0, 2] == "금액"
        assert df.iloc[2, 2] == 20000
        assert df.iloc[3, 1] == "지사"


class TestUnsupportedExtension:
    """지원하지 않는 확장자."""

    def test_raises_value_error(self, tmp_path: Path) -> None:
        """미지원 확장자 → ValueError."""
        fake = tmp_path / "test.docx"
        fake.write_bytes(b"dummy")
        with pytest.raises(ValueError, match="지원하지 않는 엑셀 확장자"):
            read_excel(fake)
