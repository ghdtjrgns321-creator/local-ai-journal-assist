"""파일 읽기 퍼사드 — 확장자 기반으로 적절한 리더를 디스패치한다.

외부에서는 이 모듈의 read_file()만 호출하면 된다.
file_validator 통과 후 호출되므로 확장자/무결성은 이미 검증된 상태.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.ingest.excel_reader import read_excel
from src.ingest.models import ReadResult
from src.ingest.parquet_reader import read_parquet
from src.ingest.text_reader import read_text

# 확장자 → 리더 함수 매핑
_READERS: dict[str, Callable[[Path], ReadResult]] = {
    ".xlsx": read_excel,
    ".xls": read_excel,
    ".xlsb": read_excel,
    ".csv": read_text,
    ".tsv": read_text,
    ".txt": read_text,
    ".dat": read_text,
    ".parquet": read_parquet,
}


def read_file(path: Path | str) -> ReadResult:
    """검증 통과된 파일을 읽어 ReadResult로 반환한다.

    file_validator.validate_file()로 먼저 검증한 뒤 호출해야 한다.
    확장자를 기반으로 적절한 리더(excel/text/parquet)를 자동 선택한다.

    Raises:
        ValueError: 지원하지 않는 확장자일 때 (정상적으로는 file_validator에서 걸림).
        OSError: 파일 읽기 실패 시.
    """
    path = Path(path)
    ext = path.suffix.lower()

    reader = _READERS.get(ext)
    if reader is None:
        msg = f"지원하지 않는 파일 형식입니다: {ext}"
        raise ValueError(msg)

    return reader(path)
