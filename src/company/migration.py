"""레거시 DB 마이그레이션 — 단일 audit.duckdb → Company-Centric 구조.

Why: RC-0 이전에 생성된 data/audit.duckdb를 Company-Centric 디렉토리
     구조(data/companies/_legacy/engagements/unknown/)로 이동하여
     ConnectionManager가 일관되게 관리할 수 있도록 한다.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_LEGACY_COMPANY_ID = "_legacy"
_LEGACY_ENGAGEMENT_ID = "unknown"


def migrate_legacy_db(
    source: Path = Path("data/audit.duckdb"),
    target_base: Path = Path("data/companies"),
) -> Path | None:
    """레거시 audit.duckdb → _legacy engagement 디렉토리로 이동.

    Returns:
        이동된 DB 파일 경로. 소스가 없으면 None.

    Raises:
        FileExistsError: 마이그레이션 대상 경로에 이미 파일이 존재할 때.
    """
    if not source.exists():
        logger.info("레거시 DB 없음 — 마이그레이션 스킵: %s", source)
        return None

    target_dir = target_base / _LEGACY_COMPANY_ID / "engagements" / _LEGACY_ENGAGEMENT_ID
    target = target_dir / "audit.duckdb"

    if target.exists():
        raise FileExistsError(f"마이그레이션 대상 이미 존재: {target}")

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    logger.info("레거시 DB 이동: %s → %s", source, target)

    # Why: DuckDB WAL 파일이 남아있으면 데이터 불일치 발생
    wal = source.with_suffix(".duckdb.wal")
    if wal.exists():
        shutil.move(str(wal), str(target.with_suffix(".duckdb.wal")))
        logger.info("WAL 파일 동반 이동: %s", wal)

    # Why: CompanyRepository가 _legacy 회사를 인식하려면 YAML 스텁 필요
    _ensure_yaml_stubs(target_base / _LEGACY_COMPANY_ID, target_dir)

    return target


def migrate_legacy_profiles(
    source: Path = Path("data/profiles"),
    target_base: Path = Path("data/companies"),
) -> bool:
    """레거시 profiles 디렉토리 이동.

    Returns:
        이동 성공 여부. 소스가 없으면 False.
    """
    if not source.exists() or not any(source.iterdir()):
        logger.info("레거시 profiles 없음 — 스킵: %s", source)
        return False

    target = target_base / _LEGACY_COMPANY_ID / "profiles"
    if target.exists():
        logger.info("프로파일 대상 이미 존재 — 스킵: %s", target)
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    logger.info("레거시 profiles 이동: %s → %s", source, target)
    return True


def _ensure_yaml_stubs(company_dir: Path, engagement_dir: Path) -> None:
    """CompanyRepository 인식용 최소 YAML 스텁 생성."""
    company_yaml = company_dir / "company.yaml"
    if not company_yaml.exists():
        data = {
            "company_id": _LEGACY_COMPANY_ID,
            "display_name": "Legacy (마이그레이션됨)",
        }
        company_yaml.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    engagement_yaml = engagement_dir / "engagement.yaml"
    if not engagement_yaml.exists():
        data = {
            "engagement_id": _LEGACY_ENGAGEMENT_ID,
            "fiscal_year": None,
        }
        engagement_yaml.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
