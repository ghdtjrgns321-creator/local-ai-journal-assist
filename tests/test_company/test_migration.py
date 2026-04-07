"""migration.py 단위 테스트.

테스트 그룹:
  - 레거시 DB 이동
  - 소스 없음 → None
  - 대상 존재 → FileExistsError
  - WAL 파일 동반 이동
  - YAML 스텁 생성
  - 레거시 profiles 이동
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.company.migration import (
    migrate_legacy_db,
    migrate_legacy_profiles,
)


# ── 레거시 DB 이동 ──────────────────────────────────────────


class TestMigrateLegacyDb:
    """레거시 audit.duckdb 마이그레이션."""

    def test_migrate_moves_file(self, tmp_path):
        """소스 DB → _legacy/engagements/unknown/ 이동."""
        source = tmp_path / "audit.duckdb"
        source.write_text("fake db")
        target_base = tmp_path / "companies"

        result = migrate_legacy_db(source=source, target_base=target_base)

        assert result is not None
        assert result.exists()
        assert not source.exists()
        # Why: Windows는 \ 경로 구분자 → Path 비교로 OS 무관하게 검증
        expected_suffix = Path("companies") / "_legacy" / "engagements" / "unknown" / "audit.duckdb"
        assert str(expected_suffix) in str(result)

    def test_no_source_returns_none(self, tmp_path):
        """소스 파일 없으면 None 반환."""
        source = tmp_path / "nonexistent.duckdb"
        result = migrate_legacy_db(source=source, target_base=tmp_path / "companies")
        assert result is None

    def test_target_exists_raises(self, tmp_path):
        """대상 경로에 이미 파일 존재 → FileExistsError."""
        source = tmp_path / "audit.duckdb"
        source.write_text("fake db")
        target_base = tmp_path / "companies"
        target = target_base / "_legacy" / "engagements" / "unknown" / "audit.duckdb"
        target.parent.mkdir(parents=True)
        target.write_text("existing")

        with pytest.raises(FileExistsError):
            migrate_legacy_db(source=source, target_base=target_base)

    def test_wal_file_moved(self, tmp_path):
        """WAL 파일이 있으면 동반 이동."""
        source = tmp_path / "audit.duckdb"
        source.write_text("fake db")
        wal = tmp_path / "audit.duckdb.wal"
        wal.write_text("fake wal")
        target_base = tmp_path / "companies"

        result = migrate_legacy_db(source=source, target_base=target_base)

        assert result is not None
        assert not wal.exists()
        assert (result.parent / "audit.duckdb.wal").exists()

    def test_yaml_stubs_created(self, tmp_path):
        """마이그레이션 후 company.yaml + engagement.yaml 스텁 생성."""
        source = tmp_path / "audit.duckdb"
        source.write_text("fake db")
        target_base = tmp_path / "companies"

        migrate_legacy_db(source=source, target_base=target_base)

        company_yaml = target_base / "_legacy" / "company.yaml"
        assert company_yaml.exists()
        data = yaml.safe_load(company_yaml.read_text(encoding="utf-8"))
        assert data["company_id"] == "_legacy"

        eng_yaml = target_base / "_legacy" / "engagements" / "unknown" / "engagement.yaml"
        assert eng_yaml.exists()
        data = yaml.safe_load(eng_yaml.read_text(encoding="utf-8"))
        assert data["engagement_id"] == "unknown"


# ── 레거시 profiles 이동 ────────────────────────────────────


class TestMigrateLegacyProfiles:
    """레거시 profiles 디렉토리 마이그레이션."""

    def test_profiles_moved(self, tmp_path):
        """profiles 디렉토리 이동."""
        source = tmp_path / "profiles"
        source.mkdir()
        (source / "test.json").write_text("{}")
        target_base = tmp_path / "companies"

        result = migrate_legacy_profiles(source=source, target_base=target_base)

        assert result is True
        assert not source.exists()
        assert (target_base / "_legacy" / "profiles" / "test.json").exists()

    def test_no_source_returns_false(self, tmp_path):
        """소스 없으면 False."""
        result = migrate_legacy_profiles(
            source=tmp_path / "nonexistent",
            target_base=tmp_path / "companies",
        )
        assert result is False

    def test_target_exists_skips(self, tmp_path):
        """대상 이미 존재하면 False (스킵)."""
        source = tmp_path / "profiles"
        source.mkdir()
        (source / "test.json").write_text("{}")
        target = tmp_path / "companies" / "_legacy" / "profiles"
        target.mkdir(parents=True)

        result = migrate_legacy_profiles(source=source, target_base=tmp_path / "companies")
        assert result is False
