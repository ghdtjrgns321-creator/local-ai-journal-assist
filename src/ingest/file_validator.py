"""파일 안전성 검증 모듈 — ingest 파이프라인의 첫 번째 관문.

사용자가 업로드한 전표 파일이 파이프라인에 진입하기 전에
존재 → 확장자 → 빈파일 → 크기 → 무결성 5단계를 검증한다.
확장자 카테고리(excel/text/columnar)에 따라 크기 제한과 검증 전략이 달라진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.ingest.file_categories import (
    UNSUPPORTED_WITH_REASON,
    classify_extension,
)
from src.ingest.integrity_checkers import INTEGRITY_CHECKERS


@dataclass
class ValidationResult:
    """파일 검증 결과.

    is_valid=False면 errors에 사유가 담기고 파이프라인이 중단된다.
    is_valid=True여도 warnings가 있을 수 있다 (레거시 형식, 인코딩 등).
    """

    is_valid: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_category: str = "unknown"

    def __str__(self) -> str:
        status = "PASS" if self.is_valid else "FAIL"
        lines = [f"[{status}] category={self.file_category}"]
        for err in self.errors:
            lines.append(f"  ERROR: {err}")
        for warn in self.warnings:
            lines.append(f"  WARN:  {warn}")
        return "\n".join(lines)


# 크기 경고 임계치 — 카테고리 제한의 80% 이상이면 경고
_SIZE_WARNING_RATIO = 0.8


def validate_file(path: Path | str) -> ValidationResult:
    """파일 검증 5단계를 순차적으로 수행한다.

    각 단계에서 치명적 오류 발견 시 즉시 반환(early return)한다.
    """
    path = Path(path)
    result = ValidationResult()

    # 1단계: 경로 존재 + 파일 여부
    if not path.exists():
        result.errors.append(f"파일을 찾을 수 없습니다: {path}")
        return result
    if not path.is_file():
        result.errors.append(f"파일이 아닙니다 (디렉토리 등): {path}")
        return result

    ext = path.suffix.lower()

    # 2단계: 확장자 분류
    # 2a. 미지원이지만 안내가 필요한 확장자 (.pdf, .hwp)
    if ext in UNSUPPORTED_WITH_REASON:
        result.file_category = "unsupported"
        result.errors.append(UNSUPPORTED_WITH_REASON[ext])
        return result

    # 2b. 카테고리 매핑
    category = classify_extension(ext)
    if category is None:
        result.errors.append(f"지원하지 않는 확장자입니다: {ext}")
        return result

    result.file_category = category.name

    # 3단계: 빈 파일 검사
    file_size = path.stat().st_size
    if file_size == 0:
        result.errors.append("빈 파일입니다 (0 bytes).")
        return result

    # 4단계: 카테고리별 크기 제한
    size_mb = file_size / (1024 * 1024)
    if size_mb > category.max_size_mb:
        result.errors.append(
            f"파일 크기({size_mb:.1f}MB)가 "
            f"{category.name} 카테고리 제한({category.max_size_mb}MB)을 초과합니다."
        )
        return result

    if size_mb > category.max_size_mb * _SIZE_WARNING_RATIO:
        result.warnings.append(
            f"파일 크기({size_mb:.1f}MB)가 "
            f"제한({category.max_size_mb}MB)의 80%를 초과합니다. "
            f"기간을 좁혀 추출하면 처리 성능이 향상됩니다."
        )

    # 5단계: 무결성 — 확장자별 검증 함수로 실제 열기 시도
    checker = INTEGRITY_CHECKERS.get(ext)
    if checker:
        integrity_errors, integrity_warnings = checker(path)
        result.errors.extend(integrity_errors)
        result.warnings.extend(integrity_warnings)

    result.is_valid = len(result.errors) == 0
    return result
