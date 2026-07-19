"""파일 카테고리 정의 — 확장자별 검증 전략과 크기 제한을 분류한다.

Excel/Text/Columnar 3개 카테고리로 나누고,
PDF/HWP는 구조화 데이터가 아니므로 사유와 함께 거부한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileCategory:
    """파일 카테고리 — 이름, 크기 제한, 소속 확장자를 묶는 불변 객체."""

    name: str  # "excel" | "text" | "columnar"
    max_size_mb: int
    extensions: frozenset[str]


# --- 카테고리 상수 ---
# 크기 제한은 파일 포맷의 물리적 특성에 따른 값
# Excel: 시트당 104만 행 → 꽉 채워도 ~80MB이므로 100MB 충분
# Text:  CSV 대용량 덤프 가능 → 800MB (16GB RAM 기준, Phase 2 ML/DL 병행 감안)
# Columnar: 압축 효율이 높아 1GB 원본이 메모리에서 훨씬 작음

EXCEL = FileCategory("excel", 100, frozenset({".xlsx", ".xls", ".xlsb"}))
TEXT = FileCategory("text", 800, frozenset({".csv", ".tsv", ".txt", ".dat"}))
COLUMNAR = FileCategory("columnar", 1000, frozenset({".parquet"}))

ALL_CATEGORIES = (EXCEL, TEXT, COLUMNAR)

# 비정형 문서 — 지원하지 않지만 "왜 안 되는지" 안내가 필요한 확장자
UNSUPPORTED_WITH_REASON: dict[str, str] = {
    ".pdf": (
        "PDF는 비정형 문서입니다. "
        "이 프로젝트는 구조화된 전표 데이터(Excel/CSV/Parquet) 기반 이상탐지에 집중합니다. "
        "데이터 추출이 필요하다면 별도 ETL 파이프라인을 구성해주세요."
    ),
    ".hwp": (
        "HWP는 비정형 문서입니다. "
        "이 프로젝트는 구조화된 전표 데이터(Excel/CSV/Parquet) 기반 이상탐지에 집중합니다. "
        "데이터 추출이 필요하다면 별도 ETL 파이프라인을 구성해주세요."
    ),
}


def classify_extension(ext: str) -> FileCategory | None:
    """확장자를 FileCategory로 분류한다. 해당 카테고리가 없으면 None."""
    ext_lower = ext.lower()
    for category in ALL_CATEGORIES:
        if ext_lower in category.extensions:
            return category
    return None
