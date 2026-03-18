"""Ingest 공용 데이터 모델 — 모든 리더가 반환하는 통합 타입.

순환참조 방지를 위해 별도 모듈로 분리.
excel_reader, text_reader, parquet_reader, reader_api 모두 여기서 import.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ReadResult:
    """파일 읽기 결과 — 포맷에 무관한 통합 인터페이스.

    엑셀은 실제 시트 구조를 반영하고,
    CSV/Parquet은 sheets=["Sheet1"]로 정규화하여
    다운스트림(header_detector, column_mapper)이 포맷을 신경 쓰지 않게 한다.
    """

    # 시트 정보 (엑셀: 실제 시트명, CSV/Parquet: ["Sheet1"])
    sheets: list[str] = field(default_factory=list)
    active_sheet: str = ""

    # 시트명 → raw DataFrame (header=None, 엑셀/텍스트는 dtype 미지정)
    raw_data: dict[str, pd.DataFrame] = field(default_factory=dict)

    # 텍스트 파일만 해당 — 감지된 인코딩 (예: "utf-8", "cp949")
    encoding: str | None = None

    # 원본 파일 포맷 (예: "xlsx", "csv", "parquet")
    source_format: str = ""
