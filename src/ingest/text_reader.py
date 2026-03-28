"""텍스트 리더 — CSV/TSV/TXT/DAT 파일을 ReadResult로 변환.

DataSynth CSV(319MB)가 메인 데이터이므로 이 경로가 가장 빈번하게 사용된다.
인코딩 자동 감지(charset_normalizer) + 구분자 자동 감지(csv.Sniffer)를 수행하고,
모든 컬럼을 dtype=str로 읽어 type_caster에 타입 변환을 위임한다.
"""

from __future__ import annotations

import csv
import io
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

# prescan 전용 샘플 크기 (메타데이터 행이 길어도 데이터 행에 도달해야 함)
_PRESCAN_SAMPLE_BYTES = 64 * 1024

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


def _count_cols_csv(text_lines: list[str], sep: str) -> int:
    """csv.reader 기반 최대 컬럼 수 — 따옴표 내 구분자를 무시한다."""
    max_count = 1
    for line in text_lines:
        try:
            row = next(csv.reader(io.StringIO(line), delimiter=sep))
            max_count = max(max_count, len(row))
        except (StopIteration, csv.Error):
            pass
    return max_count


def _detect_separator(path: Path, encoding: str) -> str:
    """csv.Sniffer로 실제 구분자를 감지한다.

    감지 실패 시 확장자 기반 폴백을 사용한다.

    Why: (1) 메타데이터 행(제목, 작성일 등)이 파일 앞부분에 있으면
    Sniffer가 줄바꿈(\\r)이나 비데이터 문자를 구분자로 오판한다.
    (2) 감지된 구분자와 확장자 폴백을 비교하여 더 많은 컬럼을
    생성하는 쪽을 선택한다.
    """
    ext = path.suffix.lower()
    fallback = _FALLBACK_SEPARATORS.get(ext, ",")

    try:
        raw = path.read_bytes()[:_SNIFFER_SAMPLE_BYTES]
        text = raw.decode(encoding, errors="replace")
        dialect = csv.Sniffer().sniff(text)
        detected = dialect.delimiter

        # 줄바꿈 문자는 구분자가 될 수 없음
        if detected in ("\r", "\n"):
            logger.info(
                "Sniffer가 줄바꿈 '%s'를 구분자로 감지 — "
                "확장자 폴백 '%s' 사용: %s",
                repr(detected), fallback, path.name,
            )
            return fallback

        # 폴백과 다른 구분자를 감지했으면, 둘을 비교하여 더 나은 쪽 선택
        if detected != fallback:
            lines = text.strip().splitlines()[:20]
            non_empty = [ln.rstrip("\r") for ln in lines if ln.strip()]

            det_max = _count_cols_csv(non_empty, detected)
            fb_max = _count_cols_csv(non_empty, fallback)

            if fb_max > det_max:
                logger.info(
                    "Sniffer '%s'(최대 %d컬럼) < 폴백 '%s'(최대 %d컬럼) — "
                    "폴백 사용: %s",
                    repr(detected), det_max, fallback, fb_max, path.name,
                )
                return fallback

        return detected
    except csv.Error:
        return fallback


def _prescan_max_columns(path: Path, encoding: str, separator: str) -> int:
    """파일의 처음 50줄에서 최대 컬럼 수를 파악한다.

    Why: 메타데이터 행(제목 등)이 1컬럼이고 데이터 행이 11컬럼이면
    pd.read_csv(header=None)가 1컬럼 기준으로 나머지를 skip한다.
    최대 컬럼 수를 names 파라미터로 전달하면 모든 행이 파싱된다.
    """
    try:
        raw = path.read_bytes()[:_PRESCAN_SAMPLE_BYTES]
        text = raw.decode(encoding, errors="replace")
        lines = text.splitlines()[:50]
        non_empty = [ln.rstrip("\r") for ln in lines if ln.strip()]
        return _count_cols_csv(non_empty, separator)
    except Exception as exc:
        logger.warning(
            "prescan 실패, names 파라미터 없이 진행: %s (%s)", path.name, exc,
        )
        return 0


def read_text(path: Path, *, encoding_override: str | None = None) -> ReadResult:
    """텍스트 파일을 DataFrame으로 읽어 ReadResult를 반환한다.

    Args:
        path: 읽을 파일 경로.
        encoding_override: 수동 인코딩 지정. 지정하면 자동 감지 스킵.
            Why: CP949/EUC-KR 오인 등 실무 ERP 덤프에서 자동 감지가
            틀릴 때 사용자가 직접 교정할 수 있게 한다.

    Raises:
        OSError: 파일 읽기 실패 시, 또는 C/python 파서 모두 실패 시.
        LookupError: encoding_override가 잘못된 인코딩명일 때.
    """
    if encoding_override is not None:
        encoding = encoding_override
        encoding_confidence = None
    else:
        encoding, encoding_confidence = _detect_encoding(path)

    separator = _detect_separator(path, encoding)
    ext = path.suffix.lower()

    # Why: 메타데이터 행(제목, 작성일 등)이 있으면 첫 행의 컬럼 수가 1이고,
    # 실제 데이터 행(11컬럼 등)이 bad line으로 skip된다.
    # 사전에 최대 컬럼 수를 파악하여 names 파라미터로 전달하면 해결된다.
    max_cols = _prescan_max_columns(path, encoding, separator)
    names = list(range(max_cols)) if max_cols > 0 else None

    # C 파서는 EOF inside unclosed quote 등 토큰화 에러에서
    # ParserError를 던진다. python 엔진은 더 관대하므로 폴백.
    csv_kwargs: dict = dict(
        sep=separator,
        encoding=encoding,
        header=None,
        dtype=str,
        on_bad_lines="warn",
    )
    if names is not None:
        csv_kwargs["names"] = names

    try:
        df = pd.read_csv(path, **csv_kwargs)
    except pd.errors.ParserError:
        logger.warning(
            "C 파서 실패, python 엔진으로 재시도: %s", path.name,
        )
        csv_kwargs["engine"] = "python"
        try:
            df = pd.read_csv(path, **csv_kwargs)
        except pd.errors.ParserError as exc:
            raise OSError(
                f"C/python 파서 모두 실패: {path.name}",
            ) from exc

    return ReadResult(
        sheets=[_DEFAULT_SHEET],
        active_sheet=_DEFAULT_SHEET,
        raw_data={_DEFAULT_SHEET: df},
        encoding=encoding,
        encoding_confidence=encoding_confidence,
        source_format=ext.lstrip("."),
    )
