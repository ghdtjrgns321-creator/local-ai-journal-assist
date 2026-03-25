"""텍스트 리더 — CSV/TSV/TXT/DAT 파일을 ReadResult로 변환.

DataSynth CSV(247MB)가 메인 데이터이므로 이 경로가 가장 빈번하게 사용된다.
인코딩 자동 감지(charset_normalizer) + 구분자 자동 감지(csv.Sniffer)를 수행하고,
모든 컬럼을 dtype=str로 읽어 type_caster에 타입 변환을 위임한다.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import pandas as pd

from src.ingest.models import ReadResult

logger = logging.getLogger(__name__)

_DEFAULT_SHEET = "Sheet1"

# 인코딩 감지용 샘플 크기 (한글이 후반부에 집중될 수 있으므로 64KB)
_ENCODING_SAMPLE_BYTES = 64 * 1024

# 구분자 감지용 샘플 크기
_SNIFFER_SAMPLE_BYTES = 8 * 1024

# 확장자 기반 구분자 폴백
_FALLBACK_SEPARATORS: dict[str, str] = {
    ".csv": ",",
    ".tsv": "\t",
    ".txt": ",",
    ".dat": ",",
}


def _detect_encoding(path: Path) -> tuple[str, float | None]:
    """charset_normalizer로 파일 인코딩을 감지한다.

    Returns:
        (encoding, confidence) — confidence는 1.0 - chaos (0.0~1.0).
        감지 실패 시 ("utf-8", None).

    Why: confidence를 ReadResult에 노출하여 UI에서 낮은 신뢰도(<0.7) 시
    수동 인코딩 선택을 유도한다.
    """
    import charset_normalizer

    raw = path.read_bytes()[:_ENCODING_SAMPLE_BYTES]
    detection = charset_normalizer.from_bytes(raw).best()

    if detection is None:
        logger.warning(
            "인코딩 감지 실패, utf-8로 폴백합니다: %s", path.name,
        )
        return "utf-8", None

    detected = detection.encoding
    # chaos: 0.0(완벽) ~ 1.0(혼돈) → confidence = 1.0 - chaos
    confidence = max(0.0, 1.0 - detection.chaos)

    # ascii → latin-1 폴백: ascii는 latin-1의 진부분집합(0x00~0x7F)이므로
    # 샘플에 0x80+ 바이트가 없으면 ascii로 오탐할 수 있다.
    # latin-1은 0x00~0xFF 전체 매핑이라 어떤 바이트든 에러 없이 읽힘.
    if detected == "ascii":
        return "latin-1", confidence

    return detected, confidence


def _detect_separator(path: Path, encoding: str) -> str:
    """csv.Sniffer로 실제 구분자를 감지한다.

    감지 실패 시 확장자 기반 폴백을 사용한다.
    """
    ext = path.suffix.lower()

    try:
        raw = path.read_bytes()[:_SNIFFER_SAMPLE_BYTES]
        text = raw.decode(encoding, errors="replace")
        dialect = csv.Sniffer().sniff(text)
        return dialect.delimiter
    except csv.Error:
        return _FALLBACK_SEPARATORS.get(ext, ",")


def read_text(path: Path, *, encoding_override: str | None = None) -> ReadResult:
    """텍스트 파일을 DataFrame으로 읽어 ReadResult를 반환한다.

    Args:
        path: 읽을 파일 경로.
        encoding_override: 수동 인코딩 지정. 지정하면 자동 감지 스킵.
            Why: CP949/EUC-KR 오인 등 실무 ERP 덤프에서 자동 감지가
            틀릴 때 사용자가 직접 교정할 수 있게 한다.

    Raises:
        OSError: 파일 읽기 실패 시.
        LookupError: encoding_override가 잘못된 인코딩명일 때.
    """
    if encoding_override is not None:
        # 수동 지정 시 자동 감지 스킵, confidence=None
        encoding = encoding_override
        encoding_confidence = None
    else:
        encoding, encoding_confidence = _detect_encoding(path)

    separator = _detect_separator(path, encoding)
    ext = path.suffix.lower()

    df = pd.read_csv(
        path,
        sep=separator,
        encoding=encoding,
        header=None,
        dtype=str,
        on_bad_lines="warn",
    )

    return ReadResult(
        sheets=[_DEFAULT_SHEET],
        active_sheet=_DEFAULT_SHEET,
        raw_data={_DEFAULT_SHEET: df},
        encoding=encoding,
        encoding_confidence=encoding_confidence,
        source_format=ext.lstrip("."),
    )
