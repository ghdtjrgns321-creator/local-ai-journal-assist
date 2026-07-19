"""RC-5-4: 회사 설정 export/import 테스트.

export → import 왕복 검증, 충돌 방어, path traversal 방어 등을 검증한다.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

from src.company.models import CompanyProfile, EngagementProfile
from src.company.repository import CompanyRepository


# ── fixture ──────────────────────────────────────────────


@pytest.fixture()
def repo(tmp_path: Path) -> CompanyRepository:
    """임시 디렉토리 기반 Repository."""
    base = tmp_path / "companies"
    base.mkdir()
    return CompanyRepository(base)


@pytest.fixture()
def populated_repo(repo: CompanyRepository) -> CompanyRepository:
    """회사 + CoA + keywords가 구성된 Repository."""
    profile = CompanyProfile(
        company_id="test_corp",
        display_name="Test Corporation",
        erp_system="SAP",
        has_custom_coa=True,
        has_custom_keywords=True,
    )
    repo.create_company(profile)

    # CoA 파일 생성
    coa_path = repo.company_dir("test_corp") / "chart_of_accounts.csv"
    coa_path.write_text("account_code\n1000\n2000\n3000\n", encoding="utf-8")

    # keywords.yaml 생성
    repo.save_company_keywords("test_corp", {
        "document_id": ["증빙no", "슬립번호"],
        "posting_date": ["기표날짜"],
    })

    # 매핑 프로파일 생성
    pdir = repo.profile_dir("test_corp")
    pdir.mkdir(exist_ok=True)
    (pdir / "abc123def456.json").write_text(
        '{"profile_version": "1.0", "mapping": {}}',
        encoding="utf-8",
    )

    # engagement 생성 (export에서 제외 대상)
    eng = EngagementProfile(
        engagement_id="test_corp_2025", company_id="test_corp", fiscal_year=2025,
    )
    repo.create_engagement("test_corp", eng)

    return repo


# ── export 테스트 ────────────────────────────────────────


class TestExportCompany:
    """회사 설정 ZIP 내보내기 검증."""

    def test_creates_zip(self, populated_repo, tmp_path):
        """ZIP 파일이 생성된다."""
        dest = tmp_path / "export"
        zip_path = populated_repo.export_company("test_corp", dest)
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

    def test_zip_contains_config_files(self, populated_repo, tmp_path):
        """ZIP에 설정 파일이 포함된다."""
        zip_path = populated_repo.export_company("test_corp", tmp_path / "export")

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "company.yaml" in names
            assert "chart_of_accounts.csv" in names
            assert "keywords.yaml" in names

    def test_zip_contains_profiles(self, populated_repo, tmp_path):
        """ZIP에 매핑 프로파일이 포함된다."""
        zip_path = populated_repo.export_company("test_corp", tmp_path / "export")

        with zipfile.ZipFile(zip_path, "r") as zf:
            profile_files = [n for n in zf.namelist() if n.startswith("profiles/")]
            assert len(profile_files) == 1
            assert "profiles/abc123def456.json" in profile_files

    def test_zip_excludes_engagements(self, populated_repo, tmp_path):
        """ZIP에서 engagements 디렉토리가 제외된다."""
        zip_path = populated_repo.export_company("test_corp", tmp_path / "export")

        with zipfile.ZipFile(zip_path, "r") as zf:
            eng_files = [n for n in zf.namelist() if "engagement" in n.lower()]
            assert eng_files == []

    def test_export_nonexistent_raises(self, populated_repo, tmp_path):
        """존재하지 않는 회사 → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            populated_repo.export_company("nonexistent", tmp_path / "export")


# ── import 테스트 ────────────────────────────────────────


class TestImportCompany:
    """회사 설정 ZIP 가져오기 검증."""

    def test_roundtrip(self, populated_repo, tmp_path):
        """export → import 왕복 시 설정이 일치."""
        # export
        zip_path = populated_repo.export_company("test_corp", tmp_path / "export")

        # 다른 repo에 import
        new_base = tmp_path / "new_companies"
        new_base.mkdir()
        new_repo = CompanyRepository(new_base)

        company_id = new_repo.import_company(zip_path)
        assert company_id == "test_corp"

        # 설정 일치 검증
        profile = new_repo.get_company("test_corp")
        assert profile.display_name == "Test Corporation"
        assert profile.erp_system == "SAP"

        # CoA 일치
        coa = new_repo.load_company_coa("test_corp")
        assert coa == {"1000", "2000", "3000"}

        # keywords 일치
        kw = new_repo.load_company_keywords("test_corp")
        assert "document_id" in kw
        assert "증빙no" in kw["document_id"]

    def test_import_existing_raises(self, populated_repo, tmp_path):
        """overwrite=False + 이미 존재 → FileExistsError."""
        zip_path = populated_repo.export_company("test_corp", tmp_path / "export")

        with pytest.raises(FileExistsError):
            populated_repo.import_company(zip_path, overwrite=False)

    def test_import_overwrite_preserves_engagements(
        self, populated_repo, tmp_path,
    ):
        """overwrite=True → 설정 파일만 교체, engagements 유지."""
        zip_path = populated_repo.export_company("test_corp", tmp_path / "export")

        # engagement가 존재하는 상태에서 overwrite
        populated_repo.import_company(zip_path, overwrite=True)

        # engagement가 여전히 존재
        engagements = populated_repo.list_engagements("test_corp")
        assert len(engagements) == 1
        assert engagements[0].engagement_id == "test_corp_2025"

    def test_import_profiles_restored(self, populated_repo, tmp_path):
        """import 후 매핑 프로파일이 복원된다."""
        zip_path = populated_repo.export_company("test_corp", tmp_path / "export")

        new_base = tmp_path / "new_companies"
        new_base.mkdir()
        new_repo = CompanyRepository(new_base)
        new_repo.import_company(zip_path)

        pdir = new_repo.profile_dir("test_corp")
        profiles = list(pdir.glob("*.json"))
        assert len(profiles) == 1


# ── 보안 테스트 ──────────────────────────────────────────


class TestImportSecurity:
    """ZIP import 보안 검증."""

    def test_path_traversal_blocked(self, tmp_path):
        """../가 포함된 경로 → ValueError."""
        zip_path = tmp_path / "malicious.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("company.yaml", "company_id: evil")
            zf.writestr("../../../etc/passwd", "root:x:0")

        repo = CompanyRepository(tmp_path / "companies")
        with pytest.raises(ValueError, match="위험한 경로"):
            repo.import_company(zip_path)

    def test_missing_company_yaml_rejected(self, tmp_path):
        """company.yaml 없는 ZIP → ValueError."""
        zip_path = tmp_path / "incomplete.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("keywords.yaml", "document_id: [test]")

        repo = CompanyRepository(tmp_path / "companies")
        with pytest.raises(ValueError, match="company.yaml"):
            repo.import_company(zip_path)

    def test_invalid_company_yaml_rejected(self, tmp_path):
        """유효하지 않은 company.yaml → ValueError."""
        zip_path = tmp_path / "invalid.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # company_id 누락 → Pydantic 검증 실패
            zf.writestr("company.yaml", yaml.dump({"display_name": "No ID"}))

        repo = CompanyRepository(tmp_path / "companies")
        (tmp_path / "companies").mkdir(exist_ok=True)
        with pytest.raises(Exception):
            repo.import_company(zip_path)

    def test_duckdb_files_ignored(self, tmp_path):
        """ZIP 내 .duckdb 파일은 무시된다."""
        zip_path = tmp_path / "with_db.zip"
        company_data = {
            "company_id": "safe_corp",
            "display_name": "Safe Corp",
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("company.yaml", yaml.dump(company_data))
            zf.writestr("audit.duckdb", "fake db content")

        base = tmp_path / "companies"
        base.mkdir()
        repo = CompanyRepository(base)
        repo.import_company(zip_path)

        # .duckdb 파일이 추출되지 않았는지 확인
        assert not (repo.company_dir("safe_corp") / "audit.duckdb").exists()
