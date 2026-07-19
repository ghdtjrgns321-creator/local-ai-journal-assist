"""text_reader 테스트 — CSV/TSV 읽기, 인코딩·구분자 감지, 인코딩 오버라이드."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ingest.models import ReadResult
from src.ingest.text_reader import _detect_encoding, read_text


class TestReadCsv:
    """CSV 기본 읽기."""

    def test_utf8_csv(self, valid_csv: Path) -> None:
        """UTF-8 CSV → 정상 ReadResult."""
        result = read_text(valid_csv)

        assert isinstance(result, ReadResult)
        assert result.sheets == ["Sheet1"]
        assert result.active_sheet == "Sheet1"
        assert result.source_format == "csv"

        df = result.raw_data["Sheet1"]
        assert isinstance(df, pd.DataFrame)
        # header=None이므로 헤더행도 데이터행으로 포함
        assert len(df) == 2

    def test_dtype_is_str(self, valid_csv: Path) -> None:
        """모든 컬럼이 str 타입으로 읽히는지 확인."""
        result = read_text(valid_csv)
        df = result.raw_data["Sheet1"]

        for col in df.columns:
            assert df[col].dtype == object  # pandas에서 str = object


class TestEncoding:
    """인코딩 감지."""

    def test_cp949_csv(self, valid_csv_cp949: Path) -> None:
        """CP949 인코딩 CSV → 한글 데이터 정상 읽기."""
        result = read_text(valid_csv_cp949)

        assert result.encoding is not None
        # charset_normalizer가 cp949 또는 euc-kr로 감지
        assert result.encoding.lower() in ("cp949", "euc-kr", "euckr")

        df = result.raw_data["Sheet1"]
        # 한글 헤더가 첫 행에 포함되어야 함 (header=None)
        assert "전표번호" in df.iloc[0].values

    def test_bom_csv(self, csv_with_bom: Path) -> None:
        """BOM(UTF-8-SIG) 포함 CSV → 정상 처리."""
        result = read_text(csv_with_bom)

        df = result.raw_data["Sheet1"]
        assert len(df) == 2
        # BOM이 데이터를 오염시키지 않아야 함
        first_cell = str(df.iloc[0, 0])
        assert "\ufeff" not in first_cell

    def test_encoding_in_result(self, valid_csv: Path) -> None:
        """encoding 필드에 감지된 인코딩이 포함."""
        result = read_text(valid_csv)
        assert result.encoding is not None

    def test_encoding_confidence_returned(self, valid_csv: Path) -> None:
        """자동 감지 시 encoding_confidence가 0~1 범위로 반환."""
        result = read_text(valid_csv)
        assert result.encoding_confidence is not None
        assert 0.0 <= result.encoding_confidence <= 1.0

    def test_cp949_confidence(self, valid_csv_cp949: Path) -> None:
        """CP949 감지 시에도 confidence 반환."""
        result = read_text(valid_csv_cp949)
        assert result.encoding_confidence is not None
        assert result.encoding_confidence > 0.0


class TestEncodingOverride:
    """인코딩 수동 오버라이드."""

    def test_override_skips_detection(self, valid_csv_cp949: Path) -> None:
        """encoding_override 지정 시 자동 감지 스킵, 해당 인코딩으로 읽기."""
        result = read_text(valid_csv_cp949, encoding_override="cp949")
        assert result.encoding == "cp949"
        # 수동 지정 시 confidence는 None
        assert result.encoding_confidence is None

    def test_override_wrong_encoding_raises(self, valid_csv_cp949: Path) -> None:
        """CP949 파일에 UTF-8 오버라이드 → UnicodeDecodeError."""
        with pytest.raises(UnicodeDecodeError):
            read_text(valid_csv_cp949, encoding_override="utf-8")

    def test_override_none_uses_auto(self, valid_csv: Path) -> None:
        """override=None → 기존 자동 감지 동작 유지."""
        result = read_text(valid_csv, encoding_override=None)
        assert result.encoding is not None
        assert result.encoding_confidence is not None


class TestDetectEncoding:
    """_detect_encoding 내부 함수 직접 테스트."""

    def test_returns_tuple(self, valid_csv: Path) -> None:
        """(encoding, confidence) 튜플 반환."""
        enc, conf = _detect_encoding(valid_csv)
        assert isinstance(enc, str)
        assert conf is None or isinstance(conf, float)

    def test_ascii_becomes_latin1(self, valid_csv: Path) -> None:
        """ASCII 감지 시 latin-1로 폴백."""
        enc, _ = _detect_encoding(valid_csv)
        assert enc != "ascii"  # ascii → latin-1 폴백

    def test_valid_utf8_korean_prefers_utf8(self, tmp_path: Path) -> None:
        """UTF-8 한글 CSV는 legacy 인코딩 오탐 없이 UTF-8로 읽는다."""
        path = tmp_path / "korean.csv"
        path.write_text(
            "document_id,line_text\nD1,고객 대금 수금\n",
            encoding="utf-8",
        )

        enc, conf = _detect_encoding(path)

        assert enc == "utf-8"
        assert conf == 1.0


class TestSeparatorDetection:
    """구분자 자동 감지."""

    def test_tsv_separator(self, valid_tsv: Path) -> None:
        """TSV 파일 → 탭 구분자 자동 감지."""
        result = read_text(valid_tsv)

        df = result.raw_data["Sheet1"]
        # 탭으로 분리되었으므로 3개 컬럼이어야 함
        assert df.shape[1] == 3

    def test_tsv_source_format(self, valid_tsv: Path) -> None:
        """TSV의 source_format = "tsv"."""
        result = read_text(valid_tsv)
        assert result.source_format == "tsv"
