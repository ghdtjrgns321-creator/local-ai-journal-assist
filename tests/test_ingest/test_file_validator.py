"""file_validator 통합 + 단위 테스트.

카테고리 분류, 5단계 검증, 확장자별 무결성 검사를 커버한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.file_categories import (
    ALL_CATEGORIES,
    COLUMNAR,
    EXCEL,
    TEXT,
    classify_extension,
)
from src.ingest.file_validator import validate_file

# ── 카테고리 분류 테스트 ──


class TestClassifyExtension:
    """classify_extension 단위 테스트."""

    @pytest.mark.parametrize(
        "ext,expected_name",
        [
            (".xlsx", "excel"),
            (".xls", "excel"),
            (".xlsb", "excel"),
            (".csv", "text"),
            (".tsv", "text"),
            (".txt", "text"),
            (".dat", "text"),
            (".parquet", "columnar"),
        ],
    )
    def test_supported_extensions(self, ext: str, expected_name: str):
        """지원되는 모든 확장자가 올바른 카테고리로 분류되어야 한다."""
        cat = classify_extension(ext)
        assert cat is not None
        assert cat.name == expected_name

    @pytest.mark.parametrize("ext", [".json", ".xml", ".zip", ".docx"])
    def test_unknown_extensions_return_none(self, ext: str):
        """미지원 확장자는 None을 반환해야 한다."""
        assert classify_extension(ext) is None

    def test_case_insensitive(self):
        """대소문자 구분 없이 분류되어야 한다."""
        assert classify_extension(".XLSX") is not None
        assert classify_extension(".Csv") is not None

    def test_all_categories_have_max_size(self):
        """모든 카테고리에 크기 제한이 설정되어야 한다."""
        for cat in ALL_CATEGORIES:
            assert cat.max_size_mb > 0

    def test_category_size_limits(self):
        """카테고리별 크기 제한이 올바르게 설정되어야 한다."""
        assert EXCEL.max_size_mb == 100
        assert TEXT.max_size_mb == 500
        assert COLUMNAR.max_size_mb == 1000


# ── 1단계: 경로 존재 테스트 ──


class TestPathValidation:
    """파일 존재/경로 검증."""

    def test_file_not_found(self, tmp_path: Path):
        """존재하지 않는 경로 → error."""
        result = validate_file(tmp_path / "nonexistent.xlsx")
        assert not result.is_valid
        assert any("찾을 수 없습니다" in e for e in result.errors)

    def test_directory_path(self, tmp_path: Path):
        """디렉토리 경로 → error."""
        result = validate_file(tmp_path)
        assert not result.is_valid
        assert any("파일이 아닙니다" in e for e in result.errors)


# ── 2단계: 확장자 테스트 ──


class TestExtensionValidation:
    """확장자 분류 및 미지원 확장자 검증."""

    def test_unknown_extension(self, tmp_path: Path):
        """미등록 확장자 → error."""
        filepath = tmp_path / "data.json"
        filepath.write_text("{}")
        result = validate_file(filepath)
        assert not result.is_valid
        assert any("지원하지 않는 확장자" in e for e in result.errors)

    def test_unsupported_pdf(self, pdf_file: Path):
        """.pdf → unsupported 카테고리 + 사유 메시지."""
        result = validate_file(pdf_file)
        assert not result.is_valid
        assert result.file_category == "unsupported"
        assert any("비정형 문서" in e for e in result.errors)

    def test_unsupported_hwp(self, hwp_file: Path):
        """.hwp → unsupported 카테고리 + 사유 메시지."""
        result = validate_file(hwp_file)
        assert not result.is_valid
        assert result.file_category == "unsupported"
        assert any("비정형 문서" in e for e in result.errors)


# ── 3단계: 빈 파일 테스트 ──


class TestEmptyFile:
    """빈 파일 검증."""

    def test_empty_file(self, empty_file: Path):
        """0바이트 파일 → error."""
        result = validate_file(empty_file)
        assert not result.is_valid
        assert any("빈 파일" in e for e in result.errors)


# ── 4단계: 크기 테스트 ──


class TestSizeValidation:
    """카테고리별 파일 크기 검증."""

    def test_excel_size_exceeds_limit(self, valid_xlsx: Path, monkeypatch):
        """Excel 파일이 100MB 초과 → error."""
        import os

        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if str(path) == str(valid_xlsx):
                # os.stat_result는 불변이므로 named tuple trick 사용
                return os.stat_result((
                    result.st_mode, result.st_ino, result.st_dev,
                    result.st_nlink, result.st_uid, result.st_gid,
                    101 * 1024 * 1024,  # st_size = 101MB
                    result.st_atime, result.st_mtime, result.st_ctime,
                ))
            return result

        monkeypatch.setattr(os, "stat", fake_stat)
        result = validate_file(valid_xlsx)
        assert not result.is_valid
        assert any("초과" in e for e in result.errors)

    def test_size_warning_at_80_percent(self, valid_xlsx: Path, monkeypatch):
        """Excel 파일이 80MB+ → warning, 여전히 is_valid=True."""
        import os

        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if str(path) == str(valid_xlsx):
                return os.stat_result((
                    result.st_mode, result.st_ino, result.st_dev,
                    result.st_nlink, result.st_uid, result.st_gid,
                    82 * 1024 * 1024,  # st_size = 82MB (80%+ of 100MB)
                    result.st_atime, result.st_mtime, result.st_ctime,
                ))
            return result

        monkeypatch.setattr(os, "stat", fake_stat)
        result = validate_file(valid_xlsx)
        assert result.is_valid
        assert any("80%" in w for w in result.warnings)


# ── 5단계: 무결성 테스트 ──


class TestIntegrityValidation:
    """확장자별 파일 무결성 검증."""

    def test_valid_xlsx(self, valid_xlsx: Path):
        """정상 .xlsx → is_valid=True, category=excel."""
        result = validate_file(valid_xlsx)
        assert result.is_valid
        assert result.file_category == "excel"

    def test_valid_csv(self, valid_csv: Path):
        """정상 UTF-8 .csv → is_valid=True, category=text."""
        result = validate_file(valid_csv)
        assert result.is_valid
        assert result.file_category == "text"
        # UTF-8이면 인코딩 경고 없어야 함
        assert not any("인코딩" in w for w in result.warnings)

    def test_valid_tsv(self, valid_tsv: Path):
        """정상 .tsv → is_valid=True, category=text."""
        result = validate_file(valid_tsv)
        assert result.is_valid
        assert result.file_category == "text"

    def test_valid_parquet(self, valid_parquet: Path):
        """정상 .parquet → is_valid=True, category=columnar."""
        result = validate_file(valid_parquet)
        assert result.is_valid
        assert result.file_category == "columnar"

    def test_corrupted_xlsx(self, corrupted_xlsx: Path):
        """손상된 .xlsx → error."""
        result = validate_file(corrupted_xlsx)
        assert not result.is_valid
        assert any("손상" in e for e in result.errors)

    def test_csv_cp949_encoding_warning(self, valid_csv_cp949: Path):
        """CP949 CSV → is_valid=True + 인코딩 경고."""
        result = validate_file(valid_csv_cp949)
        assert result.is_valid
        assert any("인코딩" in w or "UTF-8" in w for w in result.warnings)

    def test_corrupted_parquet(self, tmp_path: Path):
        """손상된 .parquet → error."""
        filepath = tmp_path / "bad.parquet"
        filepath.write_bytes(b"NOT_PARQUET_DATA")
        result = validate_file(filepath)
        assert not result.is_valid
        assert any("손상" in e for e in result.errors)


# ── ValidationResult 표현 테스트 ──


class TestValidationResultStr:
    """ValidationResult.__str__ 출력 검증."""

    def test_pass_result(self, valid_xlsx: Path):
        """정상 파일 → [PASS] 출력."""
        result = validate_file(valid_xlsx)
        assert "[PASS]" in str(result)

    def test_fail_result(self, corrupted_xlsx: Path):
        """실패 파일 → [FAIL] + ERROR 출력."""
        result = validate_file(corrupted_xlsx)
        output = str(result)
        assert "[FAIL]" in output
        assert "ERROR" in output
