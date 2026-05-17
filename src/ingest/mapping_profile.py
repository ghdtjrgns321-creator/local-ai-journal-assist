"""매핑 프로파일 모듈 — 컬럼 매핑 결과를 JSON으로 저장/로드.

동일 ERP 파일 재업로드 시 이전 매핑을 자동 적용하여 UX를 향상한다.
매칭 전략: 원본 컬럼명 집합의 SHA-256 해시(fingerprint)로 프로파일 식별.

2계층 저장 구조 (회사별 격리 지원):
  {profile_dir}/                       ← 회사별 또는 글로벌
  ├── {fingerprint}.json              ← 확정 매핑 프로파일
  └── logs/
      └── {fingerprint}_{ts}.json     ← 메타데이터 로그 (suggestions, unmapped)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
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


def _global_profile_dir() -> Path:
    """글로벌 프로파일 저장 디렉토리 경로 반환."""
    settings = get_settings()
    return PROJECT_ROOT / settings.profile_dir


def _resolve_dir(profile_dir: Path | None) -> Path:
    """외부 주입 profile_dir 우선, 없으면 글로벌 폴백.

    Why: RC-5-1 회사별 격리 — CompanyContext.profile_dir을 전달받으면
    회사 전용 디렉토리를 사용하고, None이면 기존 글로벌 경로로 폴백.
    """
    if profile_dir is not None:
        return Path(profile_dir)
    return _global_profile_dir()


def _resolve_log_dir(profile_dir: Path | None) -> Path:
    """프로파일 디렉토리 하위 logs/ 경로."""
    return _resolve_dir(profile_dir) / "logs"


def _resolve_profile_path(
    fingerprint: str,
    profile_dir: Path | None,
    fiscal_year: int | None = None,
) -> Path:
    """fingerprint(+fiscal_year) → 프로파일 JSON 경로.

    Why: 회계연도별 컬럼 구조가 동일(=같은 fingerprint)하면 과거에는 같은
    `{fp}.json` 파일에 덮어쓰여 직전 연도 프로파일이 사라졌다. fy 가 주어지면
    파일명에 `__fy{year}` suffix 를 붙여 연도별로 별도 저장. fy 가 None 이면
    기존 형식(`{fp}.json`)을 유지하여 비-회계 사용·과거 데이터와 호환.
    """
    base = _resolve_dir(profile_dir)
    if fiscal_year is None:
        return base / f"{fingerprint}.json"
    return base / f"{fingerprint}__fy{int(fiscal_year)}.json"


def _find_profile_files(
    fingerprint: str,
    profile_dir: Path | None,
) -> list[Path]:
    """동일 fingerprint 의 모든 변형(`{fp}.json`, `{fp}__fy*.json`) 경로 반환."""
    base = _resolve_dir(profile_dir)
    if not base.exists():
        return []
    return [p for p in base.glob(f"{fingerprint}*.json") if p.is_file()]


# ── save ─────────────────────────────────────────────────


def save_profile(
    result: MappingResult,
    source_columns: list[str],
    *,
    source_name: str = "",
    source_format: str = "",
    header_row: int = 0,
    fiscal_year: int | None = None,
    profile_dir: Path | None = None,
) -> Path:
    """확정 매핑 → JSON 프로파일 저장 + 메타데이터 로그 생성.

    Args:
        result: auto_map_columns() 반환 MappingResult
        source_columns: 원본 컬럼명 리스트 (fingerprint 생성용)
        source_name: 원본 파일명 (예: "gl_export.xlsx")
        source_format: 원본 포맷 (예: "xlsx")
        header_row: 헤더 행 인덱스
        fiscal_year: 회계연도 (작년 매칭 비교에 사용)
        profile_dir: 회사별 프로파일 디렉토리 (None이면 글로벌 폴백)

    Returns:
        저장된 프로파일 JSON 경로
    """
    fp = column_fingerprint(source_columns)
    now = datetime.now(UTC).isoformat(timespec="seconds")

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
        "fiscal_year": fiscal_year,
    }

    # 기존 프로파일이 있으면 created_at 유지, updated_at만 갱신.
    # fy 가 지정되면 연도별 파일(`{fp}__fy{year}.json`) 에 저장 — 동일 fingerprint
    # 다른 연도가 서로 덮어쓰는 사고 방지.
    dest = _resolve_profile_path(fp, profile_dir, fiscal_year)
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
        _save_mapping_log(result, fp, profile_dir=profile_dir)

    return dest


def _save_mapping_log(
    result: MappingResult,
    fingerprint: str,
    *,
    profile_dir: Path | None = None,
) -> Path:
    """suggestions/unmapped → 메타데이터 로그 저장.

    Why: 프로파일에는 확정 매핑만 넣고, 불확실한 정보는
    로그로 분리하여 Phase 1c에서 "수동 확인 필요" UI에 활용.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    # suggestion별 confidence 추출
    suggestion_confidence = {src: result.confidence.get(src, 0.0) for src in result.suggestions}

    log_data = {
        "fingerprint": fingerprint,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "suggestions": result.suggestions,
        "unmapped": result.unmapped,
        "missing_required": result.missing_required,
        "needs_review": result.needs_review,
        "suggestion_confidence": suggestion_confidence,
    }

    log_dir = _resolve_log_dir(profile_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{fingerprint}_{ts}.json"
    log_path.write_text(
        json.dumps(log_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.debug("매핑 로그 저장: %s", log_path.name)
    return log_path


# ── load ─────────────────────────────────────────────────


def load_profile(
    source_columns: list[str],
    *,
    fiscal_year: int | None = None,
    profile_dir: Path | None = None,
) -> MappingResult | None:
    """fingerprint(+fiscal_year)로 프로파일 검색 → MappingResult 복원.

    매핑 내용은 동일 fingerprint 라면 연도와 무관하게 사용 가능하므로,
    fy 가 주어지면 정확한 fy 매칭 → plain `{fp}.json` → 같은 fp 의 가장 최신
    fy 변형 순서로 fallback 한다. fy 가 None 이면 plain → 최신 fy 변형 순.

    Args:
        source_columns: 원본 컬럼명 리스트
        fiscal_year: 회계연도 (정확한 매칭이 있으면 우선 사용)
        profile_dir: 회사별 프로파일 디렉토리 (None이면 글로벌 폴백)

    Returns:
        저장된 프로파일이 있으면 MappingResult, 없으면 None
    """
    fp = column_fingerprint(source_columns)

    candidates: list[Path] = []
    if fiscal_year is not None:
        exact = _resolve_profile_path(fp, profile_dir, fiscal_year)
        if exact.exists():
            candidates.append(exact)
    plain = _resolve_profile_path(fp, profile_dir, fiscal_year=None)
    if plain.exists() and plain not in candidates:
        candidates.append(plain)
    for path in _find_profile_files(fp, profile_dir):
        if path not in candidates:
            candidates.append(path)

    for dest in candidates:
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("프로파일 로드 실패 (%s): %s", dest.name, e)
            continue
        if "mapping" not in data or "confidence" not in data:
            logger.warning("프로파일 필수 필드 누락: %s", dest.name)
            continue
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
    return None


# ── list / delete ────────────────────────────────────────


def list_profiles(*, profile_dir: Path | None = None) -> list[dict]:
    """저장된 프로파일 목록 반환.

    Args:
        profile_dir: 회사별 프로파일 디렉토리 (None이면 글로벌 폴백)

    Returns:
        각 프로파일의 핵심 메타데이터 리스트 (최신 updated_at 순)
    """
    resolved = _resolve_dir(profile_dir)
    if not resolved.exists():
        return []

    profiles: list[dict] = []
    for path in resolved.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # profile_version 없으면 프로파일이 아닌 파일 → 스킵
            if "profile_version" not in data:
                continue
            profiles.append(
                {
                    "fingerprint": data.get("fingerprint", path.stem),
                    "source_name": data.get("source_name", ""),
                    "source_format": data.get("source_format", ""),
                    "mapping_count": len(data.get("mapping", {})),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                }
            )
        except (json.JSONDecodeError, OSError):
            logger.warning("프로파일 읽기 실패: %s", path.name)

    # 최신 순 정렬
    profiles.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return profiles


def delete_profile(
    fingerprint: str,
    *,
    fiscal_year: int | None = None,
    profile_dir: Path | None = None,
) -> bool:
    """프로파일 + 관련 로그 삭제.

    Args:
        fingerprint: 삭제할 프로파일의 fingerprint
        fiscal_year: 특정 연도 변형만 삭제. None 이면 같은 fingerprint 의 모든
            연도 변형 + plain 파일을 모두 삭제 (기존 동작과 호환).
        profile_dir: 회사별 프로파일 디렉토리 (None이면 글로벌 폴백)

    Returns:
        하나 이상 삭제됐으면 True, 매칭 파일이 없으면 False.
    """
    if fiscal_year is not None:
        targets = [_resolve_profile_path(fingerprint, profile_dir, fiscal_year)]
        targets = [p for p in targets if p.exists()]
    else:
        targets = _find_profile_files(fingerprint, profile_dir)

    if not targets:
        return False

    for path in targets:
        path.unlink()

    # 관련 로그 삭제 — fy 별 분리 저장이 아니므로 fingerprint prefix 로 일괄 정리.
    log_dir = _resolve_log_dir(profile_dir)
    if log_dir.exists():
        for log_path in log_dir.glob(f"{fingerprint}_*.json"):
            log_path.unlink()

    logger.info("프로파일 삭제: %s (%d개)", fingerprint, len(targets))
    return True


# ── column diff ─────────────────────────────────────────


@dataclass
class ColumnDiff:
    """기존 프로파일 대비 컬럼 변경 정보."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str, float]] = field(default_factory=list)  # (old, new, score)
    prev_fingerprint: str = ""
    prev_source_name: str = ""


def load_latest_profile(*, profile_dir: Path | None = None) -> dict | None:
    """최신 프로파일 1개의 메타데이터(source_columns, fingerprint, source_name) 반환.

    Why: fingerprint 불일치 시 diff 계산을 위해 가장 최근 프로파일의
    컬럼 목록이 필요하다. 프로파일이 없으면 None(첫 업로드).
    """
    resolved = _resolve_dir(profile_dir)
    if not resolved.exists():
        return None

    latest: dict | None = None
    latest_ts = ""

    for path in resolved.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "profile_version" not in data or "source_columns" not in data:
                continue
            ts = data.get("updated_at", "")
            if ts > latest_ts:
                latest_ts = ts
                latest = data
        except (json.JSONDecodeError, OSError):
            continue

    if latest is None:
        return None

    return {
        "source_columns": latest["source_columns"],
        "fingerprint": latest.get("fingerprint", ""),
        "source_name": latest.get("source_name", ""),
        "fiscal_year": latest.get("fiscal_year"),
    }


def load_prior_year_profile(
    prior_fiscal_year: int,
    *,
    profile_dir: Path | None = None,
) -> dict | None:
    """fiscal_year == prior_fiscal_year 프로파일을 반환.

    Why: 라벨 "작년 컬럼매핑과 비교" 의도에 맞춰, 직전 업로드가 아닌
         **직전 회계연도** 프로파일과 컬럼 구조를 비교한다. 매칭 다수면
         updated_at 기준 최신 1개를 선택. 매칭 없으면 None(작년 분석 이력 없음).
    """
    resolved = _resolve_dir(profile_dir)
    if not resolved.exists():
        return None

    candidate: dict | None = None
    candidate_ts = ""

    for path in resolved.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if "profile_version" not in data or "source_columns" not in data:
            continue
        # fiscal_year 메타가 없는 구버전 프로파일은 매칭 대상에서 제외
        fy = data.get("fiscal_year")
        if fy is None or int(fy) != int(prior_fiscal_year):
            continue
        ts = data.get("updated_at", "")
        if ts > candidate_ts:
            candidate_ts = ts
            candidate = data

    if candidate is None:
        return None

    return {
        "source_columns": candidate["source_columns"],
        "fingerprint": candidate.get("fingerprint", ""),
        "source_name": candidate.get("source_name", ""),
        "fiscal_year": candidate.get("fiscal_year"),
    }


def delete_profiles_by_fiscal_year(
    fiscal_year: int,
    *,
    profile_dir: Path | None = None,
) -> int:
    """fiscal_year에 매칭되는 모든 프로파일 + 관련 로그 삭제. 삭제 개수 반환.

    Why: engagement 삭제 시 그 회계연도와 결합된 회사 매핑 프로파일도
         함께 정리해야 "남는 데이터"가 없다.
    """
    resolved = _resolve_dir(profile_dir)
    if not resolved.exists():
        return 0

    log_dir = _resolve_log_dir(profile_dir)
    deleted = 0
    for path in list(resolved.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if "profile_version" not in data:
            continue
        fy = data.get("fiscal_year")
        if fy is None or int(fy) != int(fiscal_year):
            continue

        fp = data.get("fingerprint", path.stem)
        try:
            path.unlink()
            deleted += 1
        except OSError:
            logger.warning("프로파일 삭제 실패: %s", path)
            continue
        # 관련 로그도 함께 정리
        if log_dir.exists():
            for log_path in log_dir.glob(f"{fp}_*.json"):
                try:
                    log_path.unlink()
                except OSError:
                    logger.warning("프로파일 로그 삭제 실패: %s", log_path)

    if deleted:
        logger.info("FY %s 프로파일 %d개 삭제", fiscal_year, deleted)
    return deleted


def compute_column_diff(
    prev_columns: list[str],
    curr_columns: list[str],
    *,
    rename_threshold: float = 75.0,
    prev_fingerprint: str = "",
    prev_source_name: str = "",
) -> ColumnDiff:
    """두 컬럼 리스트 간 추가/삭제/이름변경 diff 계산.

    Why: ERP 컬럼명은 접두사/접미사 변경이나 축약이 잦으므로
    ratio, partial_ratio, token_sort_ratio 3종 중 최대값으로 매칭.
    """
    from rapidfuzz import fuzz

    # 정규화: strip + lower
    prev_norm = {c.strip().lower(): c for c in prev_columns}
    curr_norm = {c.strip().lower(): c for c in curr_columns}

    prev_set = set(prev_norm.keys())
    curr_set = set(curr_norm.keys())

    only_prev = prev_set - curr_set  # 삭제 후보
    only_curr = curr_set - prev_set  # 추가 후보

    # 이름변경 추정: only_prev × only_curr 교차 매칭
    scores: list[tuple[str, str, float]] = []
    for old_k in only_prev:
        for new_k in only_curr:
            score = max(
                fuzz.ratio(old_k, new_k),
                fuzz.partial_ratio(old_k, new_k),
                fuzz.token_sort_ratio(old_k, new_k),
            )
            if score >= rename_threshold:
                scores.append((old_k, new_k, score))

    # 그리디 1:1 할당 (점수 내림차순)
    scores.sort(key=lambda x: x[2], reverse=True)
    used_old: set[str] = set()
    used_new: set[str] = set()
    renamed: list[tuple[str, str, float]] = []

    for old_k, new_k, score in scores:
        if old_k in used_old or new_k in used_new:
            continue
        renamed.append((prev_norm[old_k], curr_norm[new_k], score))
        used_old.add(old_k)
        used_new.add(new_k)

    added = [curr_norm[k] for k in sorted(only_curr - used_new)]
    removed = [prev_norm[k] for k in sorted(only_prev - used_old)]

    return ColumnDiff(
        added=added,
        removed=removed,
        renamed=renamed,
        prev_fingerprint=prev_fingerprint,
        prev_source_name=prev_source_name,
    )
