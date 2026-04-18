"""CompanyRepository — 파일시스템 기반 Company/Engagement CRUD.

디렉토리 구조:
  data/companies/{company_id}/
  ├── company.yaml
  ├── chart_of_accounts.csv (선택)
  ├── keywords.yaml (선택)
  ├── audit_rules.yaml (선택)
  ├── risk_keywords.yaml (선택)
  ├── profiles/
  └── engagements/{engagement_id}/
      ├── engagement.yaml
      ├── audit.duckdb
      ├── models/
      └── exports/
"""

from __future__ import annotations

import csv
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

import yaml

from src.company.models import CompanyProfile, EngagementProfile

logger = logging.getLogger(__name__)

_COMPANY_YAML = "company.yaml"
_ENGAGEMENT_YAML = "engagement.yaml"


# ── 공용 헬퍼 ────────────────────────────────────────


def parse_coa_csv(path: Path) -> set[str] | None:
    """chart_of_accounts.csv → set[str]. 파일 미존재/빈 파일이면 None."""
    if not path.exists():
        return None
    codes: set[str] = set()
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # 헤더 스킵
        for row in reader:
            if row and row[0].strip():
                codes.add(row[0].strip())
    return codes if codes else None


# ── Atomic Write 헬퍼 ────────────────────────────────


def _atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:
    """YAML 파일을 원자적으로 저장 (tmp → rename).

    Why: 앱 재시작/동시 세션에서 파일이 반쯤 쓰여 훼손되는 것을 방지.
    예외 발생 시 tmp 파일을 정리하여 잔류를 방지한다.
    """
    tmp = path.with_suffix(".yaml.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
            )
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── Repository ────────────────────────────────────────


class CompanyRepository:
    """파일시스템 기반 Company/Engagement CRUD."""

    def __init__(self, base_dir: Path) -> None:
        """base_dir: data/companies 루트 디렉토리."""
        self._base = Path(base_dir)

    # ── Company CRUD ─────────────────────────────────

    def create_company(self, profile: CompanyProfile) -> Path:
        """회사 디렉토리 + company.yaml 생성. 이미 존재 시 FileExistsError."""
        profile = CompanyProfile.model_validate(profile.model_dump(mode="json"))
        cdir = self.company_dir(profile.company_id)
        if cdir.exists():
            msg = f"회사 디렉토리가 이미 존재합니다: {profile.company_id}"
            raise FileExistsError(msg)

        cdir.mkdir(parents=True)
        self.profile_dir(profile.company_id).mkdir(exist_ok=True)

        yaml_path = cdir / _COMPANY_YAML
        _atomic_yaml_write(yaml_path, profile.model_dump(mode="json"))
        logger.info("회사 생성: %s → %s", profile.company_id, cdir)
        return yaml_path

    def get_company(self, company_id: str) -> CompanyProfile:
        """company.yaml 로드 → CompanyProfile. 미존재 시 FileNotFoundError."""
        yaml_path = self.company_dir(company_id) / _COMPANY_YAML
        if not yaml_path.exists():
            msg = f"회사를 찾을 수 없습니다: {company_id}"
            raise FileNotFoundError(msg)

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return CompanyProfile.model_validate(data)

    def list_companies(self) -> list[CompanyProfile]:
        """base_dir 하위의 모든 유효한 회사 프로파일 목록."""
        if not self._base.exists():
            return []

        results: list[CompanyProfile] = []
        for entry in sorted(self._base.iterdir()):
            if not entry.is_dir():
                continue
            yaml_path = entry / _COMPANY_YAML
            if not yaml_path.exists():
                continue
            try:
                with open(yaml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                results.append(CompanyProfile.model_validate(data))
            except Exception:
                logger.warning("회사 프로파일 로드 실패 (스킵): %s", entry.name)
        return results

    def update_company(self, profile: CompanyProfile) -> Path:
        """company.yaml 원자적 덮어쓰기. 미존재 시 FileNotFoundError."""
        profile = CompanyProfile.model_validate(profile.model_dump(mode="json"))
        cdir = self.company_dir(profile.company_id)
        if not cdir.exists():
            msg = f"회사를 찾을 수 없습니다: {profile.company_id}"
            raise FileNotFoundError(msg)

        yaml_path = cdir / _COMPANY_YAML
        _atomic_yaml_write(yaml_path, profile.model_dump(mode="json"))
        return yaml_path

    def delete_company(self, company_id: str) -> bool:
        """회사 디렉토리 전체 삭제. 미존재 시 False."""
        cdir = self.company_dir(company_id)
        if not cdir.exists():
            return False
        shutil.rmtree(cdir)
        logger.info("회사 삭제: %s", company_id)
        return True

    # ── Engagement CRUD ──────────────────────────────

    def create_engagement(
        self, company_id: str, profile: EngagementProfile
    ) -> Path:
        """engagements/{engagement_id}/ 디렉토리 + engagement.yaml 생성."""
        profile = EngagementProfile.model_validate(profile.model_dump(mode="json"))
        if not self.company_dir(company_id).exists():
            msg = f"회사를 찾을 수 없습니다: {company_id}"
            raise FileNotFoundError(msg)

        profile = EngagementProfile.model_validate(profile.model_dump(mode="json"))
        edir = self.engagement_dir(company_id, profile.engagement_id)
        if edir.exists():
            msg = f"Engagement가 이미 존재합니다: {profile.engagement_id}"
            raise FileExistsError(msg)

        edir.mkdir(parents=True)
        (edir / "models").mkdir(exist_ok=True)
        (edir / "exports").mkdir(exist_ok=True)

        yaml_path = edir / _ENGAGEMENT_YAML
        _atomic_yaml_write(yaml_path, profile.model_dump(mode="json"))
        logger.info("Engagement 생성: %s/%s", company_id, profile.engagement_id)
        return yaml_path

    def get_engagement(
        self, company_id: str, engagement_id: str
    ) -> EngagementProfile:
        """engagement.yaml 로드 → EngagementProfile."""
        yaml_path = (
            self.engagement_dir(company_id, engagement_id) / _ENGAGEMENT_YAML
        )
        if not yaml_path.exists():
            msg = f"Engagement를 찾을 수 없습니다: {company_id}/{engagement_id}"
            raise FileNotFoundError(msg)

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return EngagementProfile.model_validate(data)

    def list_engagements(self, company_id: str) -> list[EngagementProfile]:
        """회사의 모든 Engagement 프로파일 목록."""
        eng_root = self.company_dir(company_id) / "engagements"
        if not eng_root.exists():
            return []

        results: list[EngagementProfile] = []
        for entry in sorted(eng_root.iterdir()):
            if not entry.is_dir():
                continue
            yaml_path = entry / _ENGAGEMENT_YAML
            if not yaml_path.exists():
                continue
            try:
                with open(yaml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                results.append(EngagementProfile.model_validate(data))
            except Exception:
                logger.warning("Engagement 로드 실패 (스킵): %s", entry.name)
        return results

    def delete_engagement(self, company_id: str, engagement_id: str) -> bool:
        """Engagement 디렉토리 전체 삭제. 미존재 시 False."""
        edir = self.engagement_dir(company_id, engagement_id)
        if not edir.exists():
            return False
        shutil.rmtree(edir)
        logger.info("Engagement 삭제: %s/%s", company_id, engagement_id)
        return True

    def update_engagement(
        self, company_id: str, profile: EngagementProfile
    ) -> Path:
        """engagement.yaml 원자적 덮어쓰기."""
        edir = self.engagement_dir(company_id, profile.engagement_id)
        if not edir.exists():
            msg = f"Engagement를 찾을 수 없습니다: {company_id}/{profile.engagement_id}"
            raise FileNotFoundError(msg)

        yaml_path = edir / _ENGAGEMENT_YAML
        _atomic_yaml_write(yaml_path, profile.model_dump(mode="json"))
        return yaml_path

    # ── 리소스 로더 (회사별 커스텀 파일) ──────────────

    def load_company_coa(self, company_id: str) -> set[str] | None:
        """회사별 chart_of_accounts.csv → set[str]. 미존재 시 None."""
        path = self.company_dir(company_id) / "chart_of_accounts.csv"
        return parse_coa_csv(path)

    def load_company_yaml(
        self, company_id: str, filename: str
    ) -> dict[str, Any] | None:
        """회사별 YAML 파일 로드. 미존재 시 None."""
        # Why: filename에 경로 탈출 문자 방지 — RC-4 대시보드에서 호출될 수 있음
        safe_filename = Path(filename).name
        path = self.company_dir(company_id) / safe_filename
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save_company_yaml(
        self, company_id: str, filename: str, data: dict[str, Any],
    ) -> Path:
        """회사별 YAML 파일 원자적 저장.

        Why: RC-5-2 키워드 학습 등에서 회사별 설정 파일을 갱신할 때 사용.
        """
        safe_filename = Path(filename).name
        cdir = self.company_dir(company_id)
        if not cdir.exists():
            msg = f"회사를 찾을 수 없습니다: {company_id}"
            raise FileNotFoundError(msg)
        path = cdir / safe_filename
        _atomic_yaml_write(path, data)
        self._sync_custom_yaml_flag(company_id, safe_filename)
        return path

    def save_company_keywords(
        self, company_id: str, keywords: dict[str, Any],
    ) -> Path:
        """회사별 keywords.yaml 저장."""
        return self.save_company_yaml(company_id, "keywords.yaml", keywords)

    def load_company_keywords(self, company_id: str) -> dict[str, Any] | None:
        return self.load_company_yaml(company_id, "keywords.yaml")

    def load_company_audit_rules(self, company_id: str) -> dict[str, Any] | None:
        return self.load_company_yaml(company_id, "audit_rules.yaml")

    def load_company_risk_keywords(self, company_id: str) -> dict[str, Any] | None:
        return self.load_company_yaml(company_id, "risk_keywords.yaml")

    def _sync_custom_yaml_flag(self, company_id: str, filename: str) -> None:
        flag_map = {
            "keywords.yaml": "has_custom_keywords",
            "audit_rules.yaml": "has_custom_rules",
            "risk_keywords.yaml": "has_custom_risk_keywords",
        }
        flag_name = flag_map.get(filename)
        if flag_name is None:
            return

        profile = self.get_company(company_id)
        if getattr(profile, flag_name):
            return
        updated = profile.model_copy(update={flag_name: True})
        self.update_company(updated)

    # ── export / import ────────────────────────────────

    # ZIP에 포함할 설정 파일 (engagements 제외)
    _EXPORT_FILES = [
        "company.yaml",
        "chart_of_accounts.csv",
        "keywords.yaml",
        "audit_rules.yaml",
        "risk_keywords.yaml",
    ]

    def export_company(self, company_id: str, dest_dir: Path) -> Path:
        """회사 설정을 ZIP으로 내보내기.

        포함: company.yaml, CoA, keywords, rules, risk_keywords, profiles/
        제외: engagements/ (DB, 모델, 감사조서)

        Returns:
            생성된 ZIP 파일 경로
        """
        cdir = self.company_dir(company_id)
        if not cdir.exists():
            msg = f"회사를 찾을 수 없습니다: {company_id}"
            raise FileNotFoundError(msg)

        dest_dir.mkdir(parents=True, exist_ok=True)
        zip_path = dest_dir / f"{company_id}_export.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 설정 파일
            for fname in self._EXPORT_FILES:
                fpath = cdir / fname
                if fpath.exists():
                    zf.write(fpath, fname)

            # 매핑 프로파일
            pdir = self.profile_dir(company_id)
            if pdir.exists():
                for pfile in pdir.glob("*.json"):
                    zf.write(pfile, f"profiles/{pfile.name}")

        logger.info("회사 설정 내보내기: %s → %s", company_id, zip_path)
        return zip_path

    def import_company(
        self, zip_path: Path, *, overwrite: bool = False,
    ) -> str:
        """ZIP에서 회사 설정 가져오기.

        Args:
            zip_path: 가져올 ZIP 파일 경로
            overwrite: True면 기존 설정 파일만 덮어쓰기 (engagements 보존)

        Returns:
            가져온 company_id

        Raises:
            FileExistsError: overwrite=False인데 이미 존재
            ValueError: ZIP 구조 불량 또는 company.yaml 검증 실패
        """
        with zipfile.ZipFile(zip_path, "r") as zf:
            # path traversal 방어
            for name in zf.namelist():
                if ".." in name or name.startswith("/"):
                    msg = f"ZIP에 위험한 경로가 포함되어 있습니다: {name}"
                    raise ValueError(msg)

            # company.yaml 필수
            if "company.yaml" not in zf.namelist():
                msg = "ZIP에 company.yaml이 없습니다."
                raise ValueError(msg)

            # company.yaml 검증
            raw = yaml.safe_load(zf.read("company.yaml"))
            profile = CompanyProfile.model_validate(raw)
            company_id = profile.company_id

            cdir = self.company_dir(company_id)
            if cdir.exists() and not overwrite:
                msg = f"회사가 이미 존재합니다: {company_id}"
                raise FileExistsError(msg)

            # 설정 파일 추출 (engagements/ 제외, .duckdb 무시)
            cdir.mkdir(parents=True, exist_ok=True)
            cdir_resolved = cdir.resolve()
            for name in zf.namelist():
                if name.endswith(".duckdb"):
                    continue
                if name.startswith("engagements/"):
                    continue
                target = (cdir / name).resolve()
                # Why: .resolve() 후에도 cdir 하위인지 최종 확인 (방어적 검증)
                if not str(target).startswith(str(cdir_resolved)):
                    msg = f"ZIP 경로 탈출 시도: {name}"
                    raise ValueError(msg)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))

        logger.info("회사 설정 가져오기: %s", company_id)
        return company_id

    # ── 경로 헬퍼 ────────────────────────────────────

    def company_dir(self, company_id: str) -> Path:
        return self._base / company_id

    def engagement_dir(self, company_id: str, engagement_id: str) -> Path:
        return self._base / company_id / "engagements" / engagement_id

    def profile_dir(self, company_id: str) -> Path:
        return self._base / company_id / "profiles"

    def db_path(self, company_id: str, engagement_id: str) -> Path:
        return self.engagement_dir(company_id, engagement_id) / "audit.duckdb"

    def model_dir(self, company_id: str, engagement_id: str) -> Path:
        return self.engagement_dir(company_id, engagement_id) / "models"

    def list_feedback_events(
        self,
        company_id: str,
        engagement_id: str,
        *,
        batch_id: str | None = None,
        document_id: str | None = None,
    ):
        """Engagement DB에서 normalized feedback events를 읽는다."""
        from src.db.connection import get_connection
        from src.hitl.feedback_store import list_feedback_events

        conn = get_connection(str(self.db_path(company_id, engagement_id)))
        if batch_id is not None:
            return list_feedback_events(conn, batch_id=batch_id, document_id=document_id)
        return list_feedback_events(
            conn,
            company_id=company_id,
            engagement_id=engagement_id,
        )
