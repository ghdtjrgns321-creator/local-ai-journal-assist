"""Ingest 패키지 — 외부 전표 파일을 표준 DataFrame으로 변환."""

from src.ingest.file_validator import ValidationResult, validate_file
from src.ingest.models import ReadResult
from src.ingest.reader_api import read_file

__all__ = ["ReadResult", "ValidationResult", "read_file", "validate_file"]
