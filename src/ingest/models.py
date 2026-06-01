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

    # 인코딩 감지 신뢰도 (0.0~1.0, 1-chaos 기반)
    # Why: UI에서 낮은 신뢰도(< 0.7) 시 수동 인코딩 선택 유도
    encoding_confidence: float | None = None

    # 원본 파일 포맷 (예: "xlsx", "csv", "parquet")
    source_format: str = ""

    # 데이터 품질 경고 — 자동 복구 가능한 문제 목록
    # Why: 사용자에게 문제를 보여주고 "자동 복구" 확인을 받기 위해 분리
    data_warnings: list[str] = field(default_factory=list)


@dataclass
class SheetScore:
    """멀티시트 Excel에서 시트 품질 순위를 매기는 스코어.

    Why: 메모/표지 시트 오탐 방지 — 데이터 시트를 자동 추천하고,
    UI에서 스코어 테이블로 시트 선택 근거를 투명하게 보여준다.

    가중치: 행 수(0.3) + 열 수(0.2) + 헤더 신뢰도(0.5)
    """

    sheet_name: str
    row_count: int  # 빈 행 제외 실제 행 수
    col_count: int  # 비어있지 않은 열 수
    header_confidence: float  # header_detector 신뢰도
    total_score: float  # 가중 합산
    recommended: bool  # 최고 점수 여부


@dataclass
class HeaderDetectionResult:
    """헤더 행 탐지 결과 — detect_header_row()가 반환하는 통합 타입.

    header_row가 None이면 자동 탐지 실패 → UI에서 사용자 개입 필요.
    llm_assisted가 True면 구조 스코어 미달 상태에서 WU-28 LLM 보조로 복원된 결과.
    """

    header_row: int | None  # None = 탐지 실패, UI 개입 필요
    confidence: float  # 0.0~1.0 스코어
    matched_keywords: list[str]  # 매칭된 키워드 원본명 (예: ["전표일자", "차변"])
    total_columns: int  # 해당 행의 전체 컬럼 수
    message: str  # 사용자 안내 메시지
    llm_assisted: bool = False  # WU-28: LLM 보조로 복원되었는지 (UI 메시지 구분용)


@dataclass
class ReviewItem:
    """파이프라인 각 단계의 판단 근거 — UI 투명성 레이어.

    80/20 원칙: action="auto"는 자동 처리, "review"는 사용자 확인 필요.
    """

    column: str  # 대상 컬럼명
    action: str  # "auto" | "review" | "blocked" | "empty"
    confidence: float  # 0.0~1.0
    reason: str  # 사람이 읽는 판단 근거
    source_type: str | None = None  # 추론된 소스 타입 (B1 결과)
    target_type: str | None = None  # 스키마 기대 타입


@dataclass
class MappingResult:
    """컬럼 매핑 결과. mapping 방향: {원본컬럼명: 표준컬럼명}.

    3-tier 분류:
      - mapping: confidence >= threshold (확정)
      - suggestions: low_threshold <= confidence < threshold (추천, UI 확인 필요)
      - unmapped: confidence < low_threshold (매핑 불가)
    """

    mapping: dict[str, str]  # 확정 매핑 {원본: 표준}
    suggestions: dict[str, str]  # 추천 매핑 {원본: 표준} — UI 확인 대기
    confidence: dict[str, float]  # mapping+suggestions 전체 (0.0~1.0)
    unmapped: list[str]  # 매핑 불가 원본 컬럼명
    missing_required: list[str]  # 필수 표준 컬럼 중 미매핑
    needs_review: bool  # suggestions 있거나 missing_required 있으면 True
    review_items: list[ReviewItem] = field(default_factory=list)  # 판단 근거 리스트


@dataclass
class CastingResult:
    """타입 캐스팅 결과 — cast_dataframe()이 반환하는 통합 타입.

    errors가 있으면 파이프라인 중단, warnings는 로깅 후 계속 진행.
    """

    data: pd.DataFrame  # 캐스팅 완료 DataFrame
    errors: list[str] = field(default_factory=list)  # 필수 컬럼 캐스팅 실패
    warnings: list[str] = field(default_factory=list)  # 부분 결측, 권장 컬럼 실패
    cast_summary: dict[str, str] = field(default_factory=dict)  # {"col": "object→float64"}
    skipped_columns: list[str] = field(default_factory=list)  # 이미 올바른 dtype
    high_null_columns: list[str] = field(
        default_factory=list
    )  # 캐스팅 후 결측률 90%+ (오매핑 의심)
    empty_columns: list[str] = field(default_factory=list)  # 원본부터 100% NaN (유령 컬럼)
    success: bool = True  # len(errors) == 0
