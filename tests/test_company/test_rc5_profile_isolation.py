"""RC-5-1: 매핑 프로파일 회사별 격리 테스트.

두 회사가 동일 fingerprint를 가져도 각각 독립 저장/로드되는지,
profile_dir=None 폴백이 정상 동작하는지 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingest.mapping_profile import (
    column_fingerprint,
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)
from src.ingest.models import MappingResult


# ── fixture ──────────────────────────────────────────────


@pytest.fixture()
def shared_columns() -> list[str]:
    """두 회사가 동일하게 사용하는 ERP 컬럼명."""
    return ["전표번호", "전표일자", "계정코드", "차변금액", "대변금액"]


@pytest.fixture()
def company_a_dir(tmp_path: Path) -> Path:
    """A회사 프로파일 디렉토리."""
    d = tmp_path / "companies" / "company_a" / "profiles"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def company_b_dir(tmp_path: Path) -> Path:
    """B회사 프로파일 디렉토리."""
    d = tmp_path / "companies" / "company_b" / "profiles"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def result_a() -> MappingResult:
    """A회사의 매핑 결과."""
    return MappingResult(
        mapping={"전표번호": "document_id", "전표일자": "posting_date"},
        suggestions={},
        confidence={"전표번호": 1.0, "전표일자": 0.95},
        unmapped=[],
        missing_required=[],
        needs_review=False,
    )


@pytest.fixture()
def result_b() -> MappingResult:
    """B회사의 매핑 결과 (동일 컬럼이지만 다른 매핑)."""
    return MappingResult(
        mapping={"전표번호": "document_id", "전표일자": "document_date"},
        suggestions={},
        confidence={"전표번호": 1.0, "전표일자": 0.90},
        unmapped=[],
        missing_required=[],
        needs_review=False,
    )


# ── 회사별 격리 테스트 ───────────────────────────────────


class TestProfileIsolation:
    """동일 fingerprint의 프로파일이 회사별로 독립 저장/로드."""

    def test_same_fingerprint_different_companies(
        self,
        shared_columns: list[str],
        result_a: MappingResult,
        result_b: MappingResult,
        company_a_dir: Path,
        company_b_dir: Path,
    ):
        """동일 컬럼이라도 회사별로 별도 프로파일 저장."""
        save_profile(result_a, shared_columns, profile_dir=company_a_dir)
        save_profile(result_b, shared_columns, profile_dir=company_b_dir)

        loaded_a = load_profile(shared_columns, profile_dir=company_a_dir)
        loaded_b = load_profile(shared_columns, profile_dir=company_b_dir)

        assert loaded_a is not None
        assert loaded_b is not None
        # A회사: posting_date, B회사: document_date로 각각 다르게 저장
        assert loaded_a.mapping["전표일자"] == "posting_date"
        assert loaded_b.mapping["전표일자"] == "document_date"

    def test_delete_one_company_preserves_other(
        self,
        shared_columns: list[str],
        result_a: MappingResult,
        result_b: MappingResult,
        company_a_dir: Path,
        company_b_dir: Path,
    ):
        """A회사 프로파일 삭제가 B회사에 영향 없음."""
        save_profile(result_a, shared_columns, profile_dir=company_a_dir)
        save_profile(result_b, shared_columns, profile_dir=company_b_dir)

        fp = column_fingerprint(shared_columns)
        delete_profile(fp, profile_dir=company_a_dir)

        assert load_profile(shared_columns, profile_dir=company_a_dir) is None
        assert load_profile(shared_columns, profile_dir=company_b_dir) is not None

    def test_list_profiles_per_company(
        self,
        shared_columns: list[str],
        result_a: MappingResult,
        result_b: MappingResult,
        company_a_dir: Path,
        company_b_dir: Path,
    ):
        """list_profiles()는 해당 회사의 프로파일만 반환."""
        save_profile(result_a, shared_columns, source_name="a.xlsx", profile_dir=company_a_dir)
        save_profile(result_b, shared_columns, source_name="b.xlsx", profile_dir=company_b_dir)

        profiles_a = list_profiles(profile_dir=company_a_dir)
        profiles_b = list_profiles(profile_dir=company_b_dir)

        assert len(profiles_a) == 1
        assert profiles_a[0]["source_name"] == "a.xlsx"
        assert len(profiles_b) == 1
        assert profiles_b[0]["source_name"] == "b.xlsx"


# ── 글로벌 폴백 테스트 ──────────────────────────────────


class TestGlobalFallback:
    """profile_dir=None이면 글로벌 경로 사용 (하위 호환)."""

    def test_none_uses_global(
        self,
        shared_columns: list[str],
        result_a: MappingResult,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """profile_dir=None → 글로벌 디렉토리로 폴백."""
        global_dir = tmp_path / "global_profiles"
        monkeypatch.setattr(
            "src.ingest.mapping_profile._global_profile_dir",
            lambda: global_dir,
        )

        save_profile(result_a, shared_columns)
        loaded = load_profile(shared_columns)

        assert loaded is not None
        assert loaded.mapping == result_a.mapping
        # 파일이 글로벌 디렉토리에 저장되었는지 확인
        fp = column_fingerprint(shared_columns)
        assert (global_dir / f"{fp}.json").exists()

    def test_explicit_dir_ignores_global(
        self,
        shared_columns: list[str],
        result_a: MappingResult,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """profile_dir 명시 시 글로벌 디렉토리를 사용하지 않음."""
        global_dir = tmp_path / "global_profiles"
        explicit_dir = tmp_path / "explicit_profiles"
        monkeypatch.setattr(
            "src.ingest.mapping_profile._global_profile_dir",
            lambda: global_dir,
        )

        save_profile(result_a, shared_columns, profile_dir=explicit_dir)

        fp = column_fingerprint(shared_columns)
        assert (explicit_dir / f"{fp}.json").exists()
        assert not (global_dir / f"{fp}.json").exists()


# ── 로그 격리 테스트 ────────────────────────────────────


class TestLogIsolation:
    """메타데이터 로그도 회사별로 격리."""

    def test_logs_saved_under_company_dir(
        self, shared_columns: list[str], company_a_dir: Path,
    ):
        """suggestions가 있는 결과의 로그가 회사 디렉토리 하위에 저장."""
        result = MappingResult(
            mapping={"전표번호": "document_id"},
            suggestions={"전표일자": "posting_date"},
            confidence={"전표번호": 1.0, "전표일자": 0.6},
            unmapped=["계정코드"],
            missing_required=["gl_account"],
            needs_review=True,
        )

        save_profile(result, shared_columns, profile_dir=company_a_dir)

        log_dir = company_a_dir / "logs"
        assert log_dir.exists()
        logs = list(log_dir.glob("*.json"))
        assert len(logs) >= 1

        log_data = json.loads(logs[0].read_text(encoding="utf-8"))
        assert log_data["suggestions"] == {"전표일자": "posting_date"}
        assert "계정코드" in log_data["unmapped"]
