"""헤더 행 자동 탐지 테스트 — 8개 핵심 케이스.

reader_api로 header=None 읽기 → detect_header_row 스코어링 검증.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from config.settings import get_keywords
from src.ingest.header_detector import detect_header_row, detect_headers
from src.ingest.models import ReadResult
from src.ingest.reader_api import read_file


# ── 공용 헬퍼 ─────────────────────────────────────────────


@pytest.fixture
def keywords() -> dict:
    """keywords.yaml 로드 — 모든 테스트에서 공유."""
    return get_keywords()


def _read_first_sheet(xlsx_path: Path) -> pd.DataFrame:
    """xlsx를 reader_api로 읽어 첫 시트 DataFrame 반환."""
    result = read_file(xlsx_path)
    first_sheet = result.sheets[0]
    return result.raw_data[first_sheet]


# ── 테스트 케이스 ──────────────────────────────────────────


class TestDetectHeaderRow:
    """단일 시트 헤더 탐지 — 7개 케이스."""

    def test_standard_header(self, hd_standard_xlsx: Path, keywords: dict):
        """표준 1행 헤더 → row=0, 높은 신뢰도, 자동 패스 메시지."""
        df = _read_first_sheet(hd_standard_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.8
        assert len(result.matched_keywords) >= 5
        assert "완벽히 인식" in result.message

    def test_erp_style_header(self, hd_erp_style_xlsx: Path, keywords: dict):
        """ERP 스타일(제목2행 + 헤더) → row=2, 중간 신뢰도 경고 메시지."""
        df = _read_first_sheet(hd_erp_style_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 2
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) >= 3
        # 0.3~0.7 구간이면 경고 메시지, >= 0.7이면 자동 패스
        if result.confidence < 0.7:
            assert "확인해 주세요" in result.message
        else:
            assert "완벽히 인식" in result.message

    def test_merged_header(self, hd_merged_header_xlsx: Path, keywords: dict):
        """병합셀 상위 행 + 실제 헤더 row=1."""
        df = _read_first_sheet(hd_merged_header_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 1
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) >= 4

    def test_empty_dataframe(self, keywords: dict):
        """빈 DataFrame → 탐지 실패."""
        df = pd.DataFrame()
        result = detect_header_row(df, keywords)

        assert result.header_row is None
        assert result.confidence == 0.0
        assert result.matched_keywords == []
        assert result.total_columns == 0
        assert "직접" in result.message

    def test_no_keyword_match(self, hd_non_accounting_xlsx: Path, keywords: dict):
        """비회계 데이터 → 신뢰도 미달, 수동 입력 대기 메시지."""
        df = _read_first_sheet(hd_non_accounting_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row is None
        assert result.confidence < 0.3
        assert "직접" in result.message

    def test_dirty_columns_defense(self, hd_dirty_columns_xlsx: Path, keywords: dict):
        """유효 키워드 + 대량 빈 컬럼 → row=0, 0/0 방어."""
        df = _read_first_sheet(hd_dirty_columns_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.3
        assert len(result.matched_keywords) >= 3

    def test_trick_data_interference(self, hd_trick_data_xlsx: Path, keywords: dict):
        """데이터 행에 키워드 간섭 → 진짜 헤더(row=0)만 선택."""
        df = _read_first_sheet(hd_trick_data_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.8
        # 데이터 행(적요 컬럼에 "전표일자" 포함)이 헤더보다 높은 스코어를 받으면 안 됨

    def test_i18n_sap_keywords(self, hd_sap_style_xlsx: Path, keywords: dict):
        """SAP 영문 키워드(belnr, budat 등) 매칭 확인."""
        df = _read_first_sheet(hd_sap_style_xlsx)
        result = detect_header_row(df, keywords)

        assert result.header_row == 0
        assert result.confidence >= 0.3
        # belnr, budat, hkont 등이 매칭되어야 함
        matched_lower = [kw.lower() for kw in result.matched_keywords]
        assert any(kw in matched_lower for kw in ["belnr", "budat", "hkont"])


class TestMessageTiers:
    """신뢰도 3단계 메시지 분기 검증."""

    def test_high_confidence_auto_pass(self, hd_standard_xlsx: Path, keywords: dict):
        """confidence >= 0.7 → '완벽히 인식' 자동 패스 메시지."""
        df = _read_first_sheet(hd_standard_xlsx)
        result = detect_header_row(df, keywords)

        assert result.confidence >= 0.7
        assert "완벽히 인식" in result.message

    def test_mid_confidence_warning(self, hd_mid_confidence_xlsx: Path, keywords: dict):
        """0.3 <= confidence < 0.7 → '확인해 주세요' 경고 메시지."""
        df = _read_first_sheet(hd_mid_confidence_xlsx)
        result = detect_header_row(df, keywords)

        assert 0.3 <= result.confidence < 0.7
        assert "확인해 주세요" in result.message

    def test_low_confidence_manual(self, hd_non_accounting_xlsx: Path, keywords: dict):
        """confidence < 0.3 → '직접 헤더 행을 지정' 수동 입력 메시지."""
        df = _read_first_sheet(hd_non_accounting_xlsx)
        result = detect_header_row(df, keywords)

        assert result.confidence < 0.3
        assert result.header_row is None
        assert "직접" in result.message


class TestDetectHeaders:
    """멀티시트 퍼사드 테스트."""

    def test_multi_sheet_facade(self, hd_standard_xlsx: Path, keywords: dict):
        """ReadResult 전체를 한 번에 처리."""
        read_result = read_file(hd_standard_xlsx)
        results = detect_headers(read_result, keywords)

        assert len(results) == len(read_result.raw_data)
        for sheet_name, det in results.items():
            assert sheet_name in read_result.raw_data
            assert det.header_row is not None or det.confidence == 0.0
