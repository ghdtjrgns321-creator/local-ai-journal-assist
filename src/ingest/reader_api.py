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


# 텍스트 파일 확장자 — encoding_override 전달 대상
# Why: _READERS에서 동적 계산하면 새 바이너리 포맷 추가 시 자동으로 텍스트 분류될 위험.
# 명시적 집합으로 관리. 새 텍스트 형식 추가 시 _READERS와 함께 이 집합도 업데이트 필요.
_TEXT_EXTENSIONS: frozenset[str] = frozenset({".csv", ".tsv", ".txt", ".dat"})


def read_file(
    path: Path | str,
    *,
    encoding_override: str | None = None,
) -> ReadResult:
    """검증 통과된 파일을 읽어 ReadResult로 반환한다.

    Args:
        path: 읽을 파일 경로.
        encoding_override: 텍스트 파일 인코딩 수동 지정.
            Excel/Parquet은 인코딩 개념이 없으므로 무시된다.

    Raises:
        ValueError: 지원하지 않는 확장자일 때.
        OSError: 파일 읽기 실패 시.
    """
    path = Path(path)
    ext = path.suffix.lower()

    reader = _READERS.get(ext)
    if reader is None:
        msg = f"지원하지 않는 파일 형식입니다: {ext}"
        raise ValueError(msg)

    # 텍스트 파일일 때만 encoding_override 전달
    if encoding_override is not None and ext in _TEXT_EXTENSIONS:
        return read_text(path, encoding_override=encoding_override)

    return reader(path)
