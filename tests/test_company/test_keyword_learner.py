"""RC-5-2: 키워드 학습 모듈 테스트.

새 별칭 추출, 중복 스킵, 충돌(Collision) Overwrite,
글로벌 키워드 중복 무시 등을 검증한다.
"""

from __future__ import annotations

import pytest

from src.ingest.keyword_learner import learn_from_mapping


# ── fixture ──────────────────────────────────────────────


@pytest.fixture()
def global_keywords() -> dict[str, list[str]]:
    """글로벌 keywords.yaml 모사 (최소 세트)."""
    return {
        "document_id": ["전표번호", "belnr", "doc_no"],
        "posting_date": ["전표일자", "budat"],
        "gl_account": ["계정코드", "racct", "hkont"],
        "debit_amount": ["차변금액"],
        "credit_amount": ["대변금액"],
    }


# ── 새 별칭 추출 테스트 ──────────────────────────────────


class TestNewAliasExtraction:
    """사용자 수동 매핑에서 새 별칭을 추출."""

    def test_extracts_new_alias(self, global_keywords):
        """글로벌에 없는 별칭이 추출된다."""
        overrides = {"증빙No": "document_id"}
        result = learn_from_mapping(overrides, None, global_keywords)

        assert result is not None
        assert "증빙no" in result["document_id"]

    def test_multiple_new_aliases(self, global_keywords):
        """복수 별칭이 한 번에 추출된다."""
        overrides = {
            "증빙No": "document_id",
            "기표날짜": "posting_date",
        }
        result = learn_from_mapping(overrides, None, global_keywords)

        assert result is not None
        assert "증빙no" in result["document_id"]
        assert "기표날짜" in result["posting_date"]

    def test_empty_overrides_returns_none(self, global_keywords):
        """빈 오버라이드 → None."""
        result = learn_from_mapping({}, None, global_keywords)
        assert result is None

    def test_merges_with_existing_company_keywords(self, global_keywords):
        """기존 회사 keywords에 새 별칭이 추가된다."""
        existing = {"document_id": ["슬립번호"]}
        overrides = {"증빙No": "document_id"}

        result = learn_from_mapping(overrides, existing, global_keywords)

        assert result is not None
        assert "슬립번호" in result["document_id"]
        assert "증빙no" in result["document_id"]


# ── 중복 스킵 테스트 ────────────────────────────────────


class TestDuplicateSkip:
    """이미 등록된 별칭은 스킵."""

    def test_skip_global_existing(self, global_keywords):
        """글로벌 keywords에 이미 있는 별칭 → 스킵."""
        overrides = {"전표번호": "document_id"}  # 이미 글로벌에 있음
        result = learn_from_mapping(overrides, None, global_keywords)
        assert result is None

    def test_skip_company_existing(self, global_keywords):
        """회사 keywords에 이미 있는 별칭 → 스킵."""
        existing = {"document_id": ["증빙no"]}
        overrides = {"증빙No": "document_id"}  # 이미 회사에 있음
        result = learn_from_mapping(overrides, existing, global_keywords)
        assert result is None

    def test_all_duplicates_returns_none(self, global_keywords):
        """모든 별칭이 중복이면 None."""
        overrides = {
            "전표번호": "document_id",
            "전표일자": "posting_date",
        }
        result = learn_from_mapping(overrides, None, global_keywords)
        assert result is None


# ── 충돌 해결 (Overwrite) 테스트 ─────────────────────────


class TestCollisionOverwrite:
    """동일 별칭이 다른 표준 컬럼에 등록 → 기존 삭제 + 새 위치에 추가."""

    def test_overwrite_existing_mapping(self, global_keywords):
        """회사 keywords에서 '부서코드'가 department_code → cost_center로 재매핑."""
        existing = {"department_code": ["부서코드", "부서cd"]}
        overrides = {"부서코드": "cost_center"}

        result = learn_from_mapping(overrides, existing, global_keywords)

        assert result is not None
        # 기존 위치에서 제거
        assert "부서코드" not in result.get("department_code", [])
        # 새 위치에 추가
        assert "부서코드" in result["cost_center"]
        # 다른 별칭은 유지
        assert "부서cd" in result["department_code"]

    def test_no_1_to_n_after_overwrite(self, global_keywords):
        """Overwrite 후 동일 별칭이 두 곳에 존재하지 않음."""
        existing = {"posting_date": ["기표일"]}
        overrides = {"기표일": "document_date"}

        result = learn_from_mapping(overrides, existing, global_keywords)

        assert result is not None
        # 전체 keywords에서 '기표일'이 정확히 1곳에만 존재
        locations = [
            col for col, aliases in result.items()
            if "기표일" in [a.strip().lower() for a in aliases]
        ]
        assert len(locations) == 1
        assert locations[0] == "document_date"


# ── 엣지 케이스 ─────────────────────────────────────────


class TestEdgeCases:
    """엣지 케이스 검증."""

    def test_whitespace_alias(self, global_keywords):
        """공백만 있는 별칭은 무시."""
        overrides = {"  ": "document_id"}
        result = learn_from_mapping(overrides, None, global_keywords)
        assert result is None

    def test_empty_standard_col(self, global_keywords):
        """빈 표준 컬럼명은 무시."""
        overrides = {"증빙No": ""}
        result = learn_from_mapping(overrides, None, global_keywords)
        assert result is None

    def test_case_insensitive_dedup(self, global_keywords):
        """대소문자 무시하여 중복 판별."""
        overrides = {"BELNR": "document_id"}  # 글로벌에 'belnr' 존재
        result = learn_from_mapping(overrides, None, global_keywords)
        assert result is None

    def test_does_not_mutate_input(self, global_keywords):
        """입력 dict를 변경하지 않음."""
        existing = {"department_code": ["부서코드"]}
        original_existing = {"department_code": ["부서코드"]}
        overrides = {"부서코드": "cost_center"}

        learn_from_mapping(overrides, existing, global_keywords)

        # 원본 existing이 변경되지 않아야 함
        assert existing == original_existing
