"""Header detection tests for representative workbook shapes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from config.settings import get_keywords
from src.ingest._header_scoring import (
    null_density_score,
    type_diversity_score,
    uniqueness_score,
)
from src.ingest.header_detector import detect_header_row, detect_headers
from src.ingest.reader_api import read_file


@pytest.fixture
def keywords() -> dict:
    return get_keywords()


def _read_first_sheet(xlsx_path: Path) -> pd.DataFrame:
    result = read_file(xlsx_path)
    first_sheet = result.sheets[0]
    return result.raw_data[first_sheet]


class TestDetectHeaderRow:
    def test_standard_header(self, hd_standard_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_standard_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.8
        assert len(result.matched_keywords) >= 5
        assert "인식" in result.message

    def test_erp_style_header(self, hd_erp_style_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_erp_style_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 2
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) >= 3
        if result.confidence < 0.7:
            assert ("확인해 주세요" in result.message) or ("직접 헤더 행을 지정해 주세요" in result.message)
        else:
            assert "인식" in result.message

    def test_merged_header(self, hd_merged_header_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_merged_header_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 1
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) >= 4

    def test_empty_dataframe(self, keywords: dict):
        df = pd.DataFrame()
        result = detect_header_row(df, keywords)

        assert result.header_row is None
        assert result.confidence == 0.0
        assert result.matched_keywords == []
        assert result.total_columns == 0
        assert "직접" in result.message

    def test_no_keyword_match(self, hd_non_accounting_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_non_accounting_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) == 0
        assert ("구조" in result.message) or ("인식" in result.message)

    def test_dirty_columns_defense(self, hd_dirty_columns_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_dirty_columns_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) >= 3

    def test_trick_data_interference(self, hd_trick_data_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_trick_data_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.8

    def test_i18n_sap_keywords(self, hd_sap_style_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_sap_style_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.3
        matched_lower = [kw.lower() for kw in result.matched_keywords]
        assert any(kw in matched_lower for kw in ["belnr", "budat", "hkont"])


class TestMessageTiers:
    def test_high_confidence_auto_pass(self, hd_standard_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_standard_xlsx)
        result = detect_header_row(df, keywords)

        assert result.confidence >= 0.7
        assert "인식" in result.message

    def test_mid_confidence_warning(self, hd_mid_confidence_xlsx: Path, keywords: dict):
        df = _read_first_sheet(hd_mid_confidence_xlsx)
        result = detect_header_row(df, keywords)

        assert 0.3 <= result.confidence < 0.7
        assert ("확인해 주세요" in result.message) or ("직접 헤더 행을 지정해 주세요" in result.message)

    def test_low_confidence_manual(self, keywords: dict):
        df = pd.DataFrame([[None, None], [None, None]])
        result = detect_header_row(df, keywords)

        assert result.confidence < 0.3
        assert result.header_row is None
        assert "직접" in result.message


class TestStructuralScoring:
    def test_type_diversity_string_row(self):
        row = pd.Series(["전표번호", "전표일자", "계정코드", "차변금액"])
        assert type_diversity_score(row) == 1.0

    def test_type_diversity_mixed_row(self):
        row = pd.Series(["JE001", "2025-01-01", 10000, 0])
        assert type_diversity_score(row) < 0.5

    def test_uniqueness_unique_row(self):
        row = pd.Series(["A", "B", "C", "D"])
        assert uniqueness_score(row) == 1.0

    def test_uniqueness_repeated_row(self):
        row = pd.Series(["KRW", "KRW", "KRW", "KRW"])
        assert uniqueness_score(row) == 0.25

    def test_null_density_full_row(self):
        row = pd.Series(["A", "B", "C", "D"])
        assert null_density_score(row, 4) == 1.0

    def test_null_density_sparse_row(self):
        row = pd.Series(["A", None, None, None])
        assert null_density_score(row, 4) == 0.25

    def test_structural_no_keywords(self, keywords: dict):
        df = pd.DataFrame(
            [
                ["Name", "Department", "Title", "Phone", "Email"],
                ["John", "Engineering", "Manager", "010-1234", "a@b.com"],
                ["Jane", "Sales", "Director", "010-5678", "c@d.com"],
            ]
        )
        result = detect_header_row(df, keywords)
        assert result.header_row == 0
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) == 0

    def test_message_structural(self, keywords: dict):
        df = pd.DataFrame(
            [
                ["Name", "Department", "Title", "Phone"],
                ["John", "Engineering", "Manager", "010-1234"],
            ]
        )
        result = detect_header_row(df, keywords)
        assert "구조" in result.message


class TestDetectHeaders:
    def test_multi_sheet_facade(self, hd_standard_xlsx: Path, keywords: dict):
        read_result = read_file(hd_standard_xlsx)
        results = detect_headers(read_result, keywords)

        assert len(results) == len(read_result.raw_data)
        for sheet_name, det in results.items():
            assert sheet_name in read_result.raw_data
            assert det.header_row is not None or det.confidence == 0.0
