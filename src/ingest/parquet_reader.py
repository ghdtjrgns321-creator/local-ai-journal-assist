"""Parquet 리더 — .parquet 파일을 ReadResult로 변환.

pyarrow 백엔드로 읽으며, Parquet은 타입 정보가 정확하므로
str 변환 없이 원본 타입을 보존한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingest.models import ReadResult

# CSV/Parquet처럼 시트 개념이 없는 포맷의 기본 시트명
_DEFAULT_SHEET = "Sheet1"


def read_parquet(path: Path) -> ReadResult:
    """Parquet 파일을 DataFrame으로 읽어 ReadResult를 반환한다.

    Raises:
        OSError: 파일 읽기 실패 시.
    """
    df = pd.read_parquet(path)

    return ReadResult(
        sheets=[_DEFAULT_SHEET],
        active_sheet=_DEFAULT_SHEET,
        raw_data={_DEFAULT_SHEET: df},
        encoding=None,
        source_format="parquet",
    )
