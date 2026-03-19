"""매핑 프로파일 모듈 — 컬럼 매핑 결과를 JSON으로 저장/로드.

동일 ERP 파일 재업로드 시 이전 매핑을 자동 적용하여 UX를 향상한다.
매칭 전략: 원본 컬럼명 집합의 SHA-256 해시(fingerprint)로 프로파일 식별.

2계층 저장 구조:
  data/profiles/
  ├── {fingerprint}.json              ← 확정 매핑 프로파일
  └── logs/
      └── {fingerprint}_{ts}.json     ← 메타데이터 로그 (suggestions, unmapped)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config.settings import PROJECT_ROOT, get_settings
from src.ingest.models import MappingResult

logger = logging.getLogger(__name__)


# ── fingerprint ──────────────────────────────────────────


def column_fingerprint(columns: list[str]) -> str:
    """컬럼명 집합 → SHA-256 앞 12자 해시.

    Why: 순서가 달라도 같은 ERP면 동일 프로파일을 사용해야 하므로
    정렬 + 소문자 정규화 후 해싱한다.
    """
    # 정규화: strip + lower + 정렬 → 순서 무관 동일 해시
    normalized = sorted(col.strip().lower() for col in columns)
    raw = "|".join(normalized)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# ── 내부 경로 헬퍼 ──────────────────────────────────────


def _profile_dir() -> Path:
    """프로파일 저장 디렉토리 경로 반환."""
    settings = get_settings()
    return PROJECT_ROOT / settings.profile_dir


def _log_dir() -> Path:
    """메타데이터 로그 저장 디렉토리 경로 반환."""
    return _profile_dir() / "logs"


def _profile_path(fingerprint: str) -> Path:
    """fingerprint → 프로파일 JSON 경로."""
    return _profile_dir() / f"{fingerprint}.json"


# ── save ─────────────────────────────────────────────────


def save_profile(
    result: MappingResult,
    source_columns: list[str],
    *,
    source_name: str = "",
    source_format: str = "",
    header_row: int = 0,
) -> Path:
    """확정 매핑 → JSON 프로파일 저장 + 메타데이터 로그 생성.

    Args:
        result: auto_map_columns() 반환 MappingResult
        source_columns: 원본 컬럼명 리스트 (fingerprint 생성용)
        source_name: 원본 파일명 (예: "gl_export.xlsx")
        source_format: 원본 포맷 (예: "xlsx")
        header_row: 헤더 행 인덱스

    Returns:
        저장된 프로파일 JSON 경로
    """
    fp = column_fingerprint(source_columns)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 프로파일 JSON — 확정 매핑만 포함
    profile_data = {
        "profile_version": "1.0",
        "fingerprint": fp,
        "created_at": now,
        "updated_at": now,
        "source_columns": source_columns,
        "header_row": header_row,
        "mapping": result.mapping,
        "confidence": result.confidence,
        "source_format": source_format,
        "source_name": source_name,
    }

    # 기존 프로파일이 있으면 created_at 유지, updated_at만 갱신
    dest = _profile_path(fp)
    if dest.exists():
        try:
            existing = json.loads(dest.read_text(encoding="utf-8"))
            profile_data["created_at"] = existing.get("created_at", now)
        except (json.JSONDecodeError, KeyError):
            pass  # 손상 파일 → 덮어쓰기

    # 디렉토리 자동 생성
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("프로파일 저장: %s (%d개 매핑)", fp, len(result.mapping))

    # 메타데이터 로그 — suggestions/unmapped 등 별도 저장
    if result.suggestions or result.unmapped or result.missing_required:
        _save_mapping_log(result, fp)

    return dest


def _save_mapping_log(
    result: MappingResult,
    fingerprint: str,
) -> Path:
    """suggestions/unmapped → 메타데이터 로그 저장.

    Why: 프로파일에는 확정 매핑만 넣고, 불확실한 정보는
    로그로 분리하여 Phase 1c에서 "수동 확인 필요" UI에 활용.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # suggestion별 confidence 추출
    suggestion_confidence = {
        src: result.confidence.get(src, 0.0)
        for src in result.suggestions
    }

    log_data = {
        "fingerprint": fingerprint,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "suggestions": result.suggestions,
        "unmapped": result.unmapped,
        "missing_required": result.missing_required,
        "needs_review": result.needs_review,
        "suggestion_confidence": suggestion_confidence,
    }

    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{fingerprint}_{ts}.json"
    log_path.write_text(
        json.dumps(log_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.debug("매핑 로그 저장: %s", log_path.name)
    return log_path


# ── load ─────────────────────────────────────────────────


def load_profile(source_columns: list[str]) -> MappingResult | None:
    """fingerprint로 프로파일 검색 → MappingResult 복원.

    Why: 동일 ERP 재업로드 시 이전 확정 매핑을 자동 적용하여
    사용자가 반복 매핑 작업을 하지 않아도 된다.

    Returns:
        저장된 프로파일이 있으면 MappingResult, 없으면 None
    """
    fp = column_fingerprint(source_columns)
    dest = _profile_path(fp)

    if not dest.exists():
        return None

    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("프로파일 로드 실패 (%s): %s", fp, e)
        return None

    # 필수 필드 검증
    if "mapping" not in data or "confidence" not in data:
        logger.warning("프로파일 필수 필드 누락: %s", fp)
        return None

    # MappingResult 복원 — 프로파일에는 확정 매핑만 저장되어 있으므로
    # suggestions/unmapped는 빈 상태로 생성
    return MappingResult(
        mapping=data["mapping"],
        suggestions={},
        confidence=data["confidence"],
        unmapped=[],
        missing_required=[],
        needs_review=False,
    )


# ── list / delete ────────────────────────────────────────


def list_profiles() -> list[dict]:
    """저장된 프로파일 목록 반환.

    Returns:
        각 프로파일의 핵심 메타데이터 리스트 (최신 updated_at 순)
    """
    profile_dir = _profile_dir()
    if not profile_dir.exists():
        return []

    profiles: list[dict] = []
    for path in profile_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profiles.append({
                "fingerprint": data.get("fingerprint", path.stem),
                "source_name": data.get("source_name", ""),
                "source_format": data.get("source_format", ""),
                "mapping_count": len(data.get("mapping", {})),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            })
        except (json.JSONDecodeError, OSError):
            logger.warning("프로파일 읽기 실패: %s", path.name)

    # 최신 순 정렬
    profiles.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return profiles


def delete_profile(fingerprint: str) -> bool:
    """프로파일 + 관련 로그 삭제.

    Returns:
        삭제 성공 여부 (프로파일이 존재하지 않으면 False)
    """
    dest = _profile_path(fingerprint)
    if not dest.exists():
        return False

    # 프로파일 삭제
    dest.unlink()

    # 관련 로그 삭제
    log_dir = _log_dir()
    if log_dir.exists():
        for log_path in log_dir.glob(f"{fingerprint}_*.json"):
            log_path.unlink()

    logger.info("프로파일 삭제: %s", fingerprint)
    return True
