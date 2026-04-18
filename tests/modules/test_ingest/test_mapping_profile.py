"""매핑 프로파일 모듈 테스트.

fingerprint 해싱, save/load 왕복, list/delete,
메타데이터 로그 분리, 손상 JSON 처리 등을 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingest.mapping_profile import (
    ColumnDiff,
    _save_mapping_log,
    column_fingerprint,
    compute_column_diff,
    delete_profile,
    list_profiles,
    load_latest_profile,
    load_profile,
    save_profile,
)
from src.ingest.models import MappingResult


# ── fixture ──────────────────────────────────────────────


@pytest.fixture
def _use_tmp_profile_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """프로파일 디렉토리를 tmp_path로 교체.

    _log_dir는 _profile_dir() / "logs"를 반환하므로 별도 패치 불필요.
    """
    monkeypatch.setattr(
        "src.ingest.mapping_profile._global_profile_dir",
        lambda: tmp_path,
    )


@pytest.fixture
def sample_columns() -> list[str]:
    """테스트용 원본 컬럼명 리스트."""
    return ["전표번호", "전표일자", "계정코드", "차변금액", "대변금액", "적요"]


@pytest.fixture
def sample_result() -> MappingResult:
    """확정 매핑 + suggestions + unmapped 모두 포함된 MappingResult."""
    return MappingResult(
        mapping={"전표번호": "document_id", "전표일자": "posting_date"},
        suggestions={"계정코드": "gl_account"},
        confidence={"전표번호": 1.0, "전표일자": 1.0, "계정코드": 0.65},
        unmapped=["XYZ_UNKNOWN"],
        missing_required=["currency"],
        needs_review=True,
    )


@pytest.fixture
def clean_result() -> MappingResult:
    """suggestions/unmapped 없는 깨끗한 MappingResult."""
    return MappingResult(
        mapping={"전표번호": "document_id", "전표일자": "posting_date"},
        suggestions={},
        confidence={"전표번호": 1.0, "전표일자": 1.0},
        unmapped=[],
        missing_required=[],
        needs_review=False,
    )


# ── fingerprint 테스트 ──────────────────────────────────


class TestColumnFingerprint:
    """컬럼명 집합 → SHA-256 해시 테스트."""

    def test_same_columns_same_hash(self):
        """동일 컬럼 → 동일 해시."""
        cols = ["전표번호", "전표일자", "차변금액"]
        assert column_fingerprint(cols) == column_fingerprint(cols)

    def test_order_invariant(self):
        """순서가 달라도 동일 해시."""
        a = column_fingerprint(["전표번호", "전표일자", "차변금액"])
        b = column_fingerprint(["차변금액", "전표번호", "전표일자"])
        assert a == b

    def test_different_columns_different_hash(self):
        """다른 컬럼 → 다른 해시."""
        a = column_fingerprint(["전표번호", "전표일자"])
        b = column_fingerprint(["이름", "부서"])
        assert a != b

    def test_hash_length(self):
        """해시 길이 = 12자."""
        fp = column_fingerprint(["a", "b", "c"])
        assert len(fp) == 12

    def test_strip_normalization(self):
        """공백 포함 컬럼명도 정규화."""
        a = column_fingerprint(["전표번호", " 전표일자 "])
        b = column_fingerprint(["전표번호", "전표일자"])
        assert a == b

    def test_case_insensitive(self):
        """대소문자 무관 동일 해시."""
        a = column_fingerprint(["DocNo", "Amount"])
        b = column_fingerprint(["docno", "amount"])
        assert a == b


# ── save_profile 테스트 ─────────────────────────────────


@pytest.mark.usefixtures("_use_tmp_profile_dir")
class TestSaveProfile:
    """프로파일 저장 테스트."""

    def test_creates_file(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """JSON 파일이 생성된다."""
        path = save_profile(
            sample_result, sample_columns,
            source_name="test.xlsx", source_format="xlsx",
        )
        assert path.exists()
        assert path.suffix == ".json"

    def test_json_structure(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """JSON에 필수 필드가 모두 포함된다."""
        path = save_profile(
            sample_result, sample_columns,
            source_name="gl.xlsx", source_format="xlsx", header_row=2,
        )
        data = json.loads(path.read_text(encoding="utf-8"))

        assert data["profile_version"] == "1.0"
        assert data["fingerprint"] == column_fingerprint(sample_columns)
        assert data["mapping"] == sample_result.mapping
        assert data["confidence"] == sample_result.confidence
        assert data["source_name"] == "gl.xlsx"
        assert data["source_format"] == "xlsx"
        assert data["header_row"] == 2
        assert data["source_columns"] == sample_columns
        assert "created_at" in data
        assert "updated_at" in data

    def test_profile_excludes_suggestions(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """프로파일에는 suggestions/unmapped가 포함되지 않는다."""
        path = save_profile(sample_result, sample_columns)
        data = json.loads(path.read_text(encoding="utf-8"))

        assert "suggestions" not in data
        assert "unmapped" not in data

    def test_auto_creates_directory(
        self, sample_columns: list[str], clean_result: MappingResult,
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """존재하지 않는 디렉토리도 자동 생성."""
        nested = tmp_path / "deep" / "nested"
        monkeypatch.setattr(
            "src.ingest.mapping_profile._global_profile_dir", lambda: nested,
        )
        path = save_profile(clean_result, sample_columns)
        assert path.exists()

    def test_update_preserves_created_at(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """재저장 시 created_at은 유지, updated_at만 갱신."""
        path1 = save_profile(sample_result, sample_columns)
        data1 = json.loads(path1.read_text(encoding="utf-8"))

        path2 = save_profile(sample_result, sample_columns)
        data2 = json.loads(path2.read_text(encoding="utf-8"))

        assert data2["created_at"] == data1["created_at"]


# ── _save_mapping_log 테스트 ────────────────────────────


@pytest.mark.usefixtures("_use_tmp_profile_dir")
class TestSaveMappingLog:
    """메타데이터 로그 저장 테스트."""

    def test_log_created_with_suggestions(
        self, sample_result: MappingResult, tmp_path: Path,
    ):
        """suggestions가 있으면 로그 파일이 생성된다."""
        log_path = _save_mapping_log(sample_result, "abc123def456")
        assert log_path.exists()
        assert log_path.parent.name == "logs"

    def test_log_contains_suggestions_and_unmapped(
        self, sample_result: MappingResult, tmp_path: Path,
    ):
        """로그에 suggestions, unmapped, missing_required가 포함된다."""
        log_path = _save_mapping_log(sample_result, "abc123def456")
        data = json.loads(log_path.read_text(encoding="utf-8"))

        assert data["suggestions"] == sample_result.suggestions
        assert data["unmapped"] == sample_result.unmapped
        assert data["missing_required"] == sample_result.missing_required
        assert data["needs_review"] is True
        assert "suggestion_confidence" in data

    def test_no_log_for_clean_result(
        self, sample_columns: list[str], clean_result: MappingResult, tmp_path: Path,
    ):
        """suggestions/unmapped 없으면 로그가 생성되지 않는다."""
        save_profile(clean_result, sample_columns)
        log_dir = tmp_path / "logs"
        if log_dir.exists():
            assert list(log_dir.glob("*.json")) == []


# ── load_profile 테스트 ─────────────────────────────────


@pytest.mark.usefixtures("_use_tmp_profile_dir")
class TestLoadProfile:
    """프로파일 로드 테스트."""

    def test_roundtrip(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """save → load 왕복 시 mapping/confidence 필드 일치."""
        save_profile(sample_result, sample_columns)
        loaded = load_profile(sample_columns)

        assert loaded is not None
        assert loaded.mapping == sample_result.mapping
        assert loaded.confidence == sample_result.confidence

    def test_loaded_has_empty_suggestions(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """로드된 결과의 suggestions/unmapped는 빈 상태."""
        save_profile(sample_result, sample_columns)
        loaded = load_profile(sample_columns)

        assert loaded is not None
        assert loaded.suggestions == {}
        assert loaded.unmapped == []
        assert loaded.needs_review is False

    def test_not_found_returns_none(self, tmp_path: Path):
        """존재하지 않는 프로파일 → None."""
        result = load_profile(["없는", "컬럼"])
        assert result is None

    def test_corrupted_json_returns_none(
        self, sample_columns: list[str], tmp_path: Path,
    ):
        """손상된 JSON → None + 경고 로그."""
        fp = column_fingerprint(sample_columns)
        corrupt_path = tmp_path / f"{fp}.json"
        corrupt_path.write_text("{ invalid json", encoding="utf-8")

        result = load_profile(sample_columns)
        assert result is None

    def test_missing_fields_returns_none(
        self, sample_columns: list[str], tmp_path: Path,
    ):
        """필수 필드 누락 JSON → None."""
        fp = column_fingerprint(sample_columns)
        path = tmp_path / f"{fp}.json"
        path.write_text(json.dumps({"source_name": "test"}), encoding="utf-8")

        result = load_profile(sample_columns)
        assert result is None


# ── list_profiles 테스트 ────────────────────────────────


@pytest.mark.usefixtures("_use_tmp_profile_dir")
class TestListProfiles:
    """프로파일 목록 조회 테스트."""

    def test_empty_directory(self, tmp_path: Path):
        """빈 디렉토리 → 빈 리스트."""
        assert list_profiles() == []

    def test_multiple_profiles(self, tmp_path: Path):
        """복수 프로파일 목록 반환."""
        cols_a = ["전표번호", "전표일자"]
        cols_b = ["DocNo", "Amount", "Date"]
        result_a = MappingResult(
            mapping={"전표번호": "document_id"},
            suggestions={}, confidence={"전표번호": 1.0},
            unmapped=[], missing_required=[], needs_review=False,
        )
        result_b = MappingResult(
            mapping={"DocNo": "document_id"},
            suggestions={}, confidence={"DocNo": 1.0},
            unmapped=[], missing_required=[], needs_review=False,
        )

        save_profile(result_a, cols_a, source_name="a.xlsx")
        save_profile(result_b, cols_b, source_name="b.csv")

        profiles = list_profiles()
        assert len(profiles) == 2
        names = {p["source_name"] for p in profiles}
        assert names == {"a.xlsx", "b.csv"}

    def test_profile_metadata_fields(
        self, sample_columns: list[str], clean_result: MappingResult, tmp_path: Path,
    ):
        """목록의 각 항목에 필수 메타데이터가 포함된다."""
        save_profile(clean_result, sample_columns, source_name="test.xlsx")
        profiles = list_profiles()
        assert len(profiles) == 1

        p = profiles[0]
        assert "fingerprint" in p
        assert "source_name" in p
        assert "mapping_count" in p
        assert p["mapping_count"] == 2


# ── delete_profile 테스트 ───────────────────────────────


@pytest.mark.usefixtures("_use_tmp_profile_dir")
class TestDeleteProfile:
    """프로파일 삭제 테스트."""

    def test_delete_existing(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """존재하는 프로파일 삭제 → True + 파일 제거."""
        save_profile(sample_result, sample_columns)
        fp = column_fingerprint(sample_columns)

        assert delete_profile(fp) is True
        assert load_profile(sample_columns) is None

    def test_delete_nonexistent(self, tmp_path: Path):
        """존재하지 않는 fingerprint → False."""
        assert delete_profile("nonexistent12") is False

    def test_delete_removes_logs(
        self, sample_columns: list[str], sample_result: MappingResult, tmp_path: Path,
    ):
        """프로파일 삭제 시 관련 로그도 함께 삭제된다."""
        save_profile(sample_result, sample_columns)
        fp = column_fingerprint(sample_columns)

        # 로그가 생성되었는지 확인
        log_dir = tmp_path / "logs"
        logs_before = list(log_dir.glob(f"{fp}_*.json")) if log_dir.exists() else []
        assert len(logs_before) > 0

        delete_profile(fp)

        logs_after = list(log_dir.glob(f"{fp}_*.json")) if log_dir.exists() else []
        assert len(logs_after) == 0


# ── 통합 테스트 ─────────────────────────────────────────


@pytest.mark.usefixtures("_use_tmp_profile_dir")
class TestIntegration:
    """save → load → 필드 일치 통합 검증."""

    def test_full_roundtrip(self, tmp_path: Path):
        """전체 워크플로우: save → load → 매핑 결과 일치."""
        columns = ["전표번호", "전표일자", "계정코드", "차변금액", "대변금액"]
        result = MappingResult(
            mapping={
                "전표번호": "document_id",
                "전표일자": "posting_date",
                "계정코드": "gl_account",
                "차변금액": "debit_amount",
                "대변금액": "credit_amount",
            },
            suggestions={},
            confidence={
                "전표번호": 1.0, "전표일자": 1.0, "계정코드": 1.0,
                "차변금액": 1.0, "대변금액": 1.0,
            },
            unmapped=[],
            missing_required=[],
            needs_review=False,
        )

        # save
        path = save_profile(
            result, columns,
            source_name="erp_export.xlsx", source_format="xlsx", header_row=3,
        )
        assert path.exists()

        # load
        loaded = load_profile(columns)
        assert loaded is not None
        assert loaded.mapping == result.mapping
        assert loaded.confidence == result.confidence

        # list
        profiles = list_profiles()
        assert len(profiles) == 1
        assert profiles[0]["source_name"] == "erp_export.xlsx"
        assert profiles[0]["mapping_count"] == 5

        # delete
        fp = column_fingerprint(columns)
        assert delete_profile(fp) is True
        assert load_profile(columns) is None
        assert list_profiles() == []


# ── load_latest_profile 테스트 ─────────────────────────


@pytest.mark.usefixtures("_use_tmp_profile_dir")
class TestLoadLatestProfile:
    """최신 프로파일 메타데이터 로드 테스트."""

    def test_no_profiles_returns_none(self, tmp_path: Path):
        """프로파일 없으면 None."""
        assert load_latest_profile() is None

    def test_returns_latest(self, tmp_path: Path):
        """복수 프로파일 중 최신 updated_at 반환."""
        cols_a = ["전표번호", "전표일자"]
        cols_b = ["DocNo", "Amount", "Date"]
        res_a = MappingResult(
            mapping={"전표번호": "document_id"}, suggestions={},
            confidence={"전표번호": 1.0}, unmapped=[],
            missing_required=[], needs_review=False,
        )
        res_b = MappingResult(
            mapping={"DocNo": "document_id"}, suggestions={},
            confidence={"DocNo": 1.0}, unmapped=[],
            missing_required=[], needs_review=False,
        )
        save_profile(res_a, cols_a, source_name="old.xlsx")
        save_profile(res_b, cols_b, source_name="new.csv")

        # Why: 같은 초에 저장되면 updated_at 동일 → 정렬 불안정
        # 명시적으로 new.csv의 updated_at을 미래로 패치
        fp_b = column_fingerprint(cols_b)
        path_b = tmp_path / f"{fp_b}.json"
        data_b = json.loads(path_b.read_text(encoding="utf-8"))
        data_b["updated_at"] = "2099-01-01T00:00:00+00:00"
        path_b.write_text(json.dumps(data_b, ensure_ascii=False, indent=2), encoding="utf-8")

        latest = load_latest_profile()
        assert latest is not None
        assert latest["source_name"] == "new.csv"
        assert latest["source_columns"] == cols_b

    def test_returns_source_columns(
        self, sample_columns: list[str], clean_result: MappingResult, tmp_path: Path,
    ):
        """source_columns 필드가 정확히 반환된다."""
        save_profile(clean_result, sample_columns, source_name="test.xlsx")
        latest = load_latest_profile()
        assert latest is not None
        assert latest["source_columns"] == sample_columns


# ── compute_column_diff 테스트 ─────────────────────────


class TestComputeColumnDiff:
    """컬럼 diff 계산 테스트."""

    def test_no_changes(self):
        """동일 컬럼 → 변경 없음."""
        cols = ["전표번호", "전표일자", "차변금액"]
        diff = compute_column_diff(cols, cols)
        assert diff.added == []
        assert diff.removed == []
        assert diff.renamed == []

    def test_added_columns(self):
        """신규 컬럼 감지."""
        prev = ["전표번호", "전표일자"]
        curr = ["전표번호", "전표일자", "승인자"]
        diff = compute_column_diff(prev, curr)
        assert diff.added == ["승인자"]
        assert diff.removed == []
        assert diff.renamed == []

    def test_removed_columns(self):
        """삭제된 컬럼 감지."""
        prev = ["전표번호", "전표일자", "참조번호"]
        curr = ["전표번호", "전표일자"]
        diff = compute_column_diff(prev, curr)
        assert diff.added == []
        assert diff.removed == ["참조번호"]
        assert diff.renamed == []

    def test_renamed_column_suffix(self):
        """접미사 추가 패턴 감지 (공급가액 → 공급가액(원화))."""
        prev = ["전표번호", "공급가액"]
        curr = ["전표번호", "공급가액(원화)"]
        diff = compute_column_diff(prev, curr)
        assert len(diff.renamed) == 1
        assert diff.renamed[0][0] == "공급가액"
        assert diff.renamed[0][1] == "공급가액(원화)"
        assert diff.added == []
        assert diff.removed == []

    def test_renamed_column_abbreviation(self):
        """영문 축약 패턴 감지 (vendor_name → vndr_name)."""
        prev = ["doc_id", "vendor_name"]
        curr = ["doc_id", "vndr_name"]
        diff = compute_column_diff(prev, curr)
        # partial_ratio나 token_sort_ratio로 75% 이상이면 renamed
        if diff.renamed:
            assert diff.renamed[0][0] == "vendor_name"
            assert diff.renamed[0][1] == "vndr_name"
        else:
            # 유사도가 임계값 미만이면 added+removed로 분류됨
            assert "vndr_name" in diff.added
            assert "vendor_name" in diff.removed

    def test_mixed_changes(self):
        """추가+삭제+이름변경 복합 시나리오."""
        prev = ["전표번호", "전표일자", "공급가액", "참조번호"]
        curr = ["전표번호", "전표일자", "공급가액(원화)", "승인자"]
        diff = compute_column_diff(prev, curr)
        # 공급가액→공급가액(원화) renamed, 참조번호 removed, 승인자 added
        renamed_olds = [r[0] for r in diff.renamed]
        assert "공급가액" in renamed_olds
        assert "참조번호" in diff.removed
        assert "승인자" in diff.added

    def test_case_insensitive(self):
        """대소문자 무관하게 동일 컬럼 인식."""
        prev = ["DocNo", "Amount"]
        curr = ["docno", "AMOUNT"]
        diff = compute_column_diff(prev, curr)
        assert diff.added == []
        assert diff.removed == []
        assert diff.renamed == []

    def test_prev_metadata_passthrough(self):
        """prev_fingerprint, prev_source_name이 ColumnDiff에 전달."""
        diff = compute_column_diff(
            ["a"], ["a"],
            prev_fingerprint="abc123",
            prev_source_name="test.xlsx",
        )
        assert diff.prev_fingerprint == "abc123"
        assert diff.prev_source_name == "test.xlsx"
