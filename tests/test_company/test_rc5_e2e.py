"""RC-5-5: B회사 3년차 E2E 시나리오 테스트.

1년차: 최초 매핑 + 프로파일 저장 + 키워드 학습
2년차: 동일 ERP → 프로파일 자동 적용 (needs_review=False)
3년차: 새 컬럼 추가 → fingerprint 변경 → 기존 컬럼은 keyword exact match

완료 기준: B회사 1년차 매핑이 3년차에서 자동 적용.
새 컬럼만 review 분류. 키워드 학습 덕분에 기존 컬럼은 즉시 매칭.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.company.models import CompanyProfile, EngagementProfile
from src.company.repository import CompanyRepository
from src.context import ContextFactory
from src.ingest.column_mapper import auto_map_columns
from src.ingest.keyword_learner import learn_from_mapping
from src.ingest.mapping_profile import (
    column_fingerprint,
    load_profile,
    save_profile,
)
from src.ingest.models import MappingResult


# ── fixture ──────────────────────────────────────────────


# SAP ERP 스타일 컬럼명 (1~2년차 공통)
SAP_COLUMNS_Y1_Y2 = [
    "BELNR", "BUDAT", "BLDAT", "RACCT",
    "WRBTR_D", "WRBTR_C", "BLART", "BUKRS",
]

# 3년차: ERP 업그레이드로 새 컬럼 2개 추가
SAP_COLUMNS_Y3 = SAP_COLUMNS_Y1_Y2 + ["KOSTL", "PRCTR"]

# 글로벌 keywords (최소 세트)
GLOBAL_KEYWORDS = {
    "document_id": ["전표번호", "belnr", "doc_no"],
    "posting_date": ["전표일자", "budat"],
    "document_date": ["증빙일자", "bldat"],
    "gl_account": ["계정코드", "racct", "hkont"],
    "debit_amount": ["차변금액", "wrbtr_d"],
    "credit_amount": ["대변금액", "wrbtr_c"],
    "document_type": ["전표유형", "blart"],
    "company_code": ["회사코드", "bukrs"],
}


@pytest.fixture()
def b_repo(tmp_path: Path) -> CompanyRepository:
    """B회사 Repository 인프라."""
    base = tmp_path / "companies"
    base.mkdir()
    repo = CompanyRepository(base)

    profile = CompanyProfile(
        company_id="b_corp",
        display_name="B Corporation",
        erp_system="SAP",
    )
    repo.create_company(profile)

    # 3개년 engagement 생성
    for year in [2023, 2024, 2025]:
        eng = EngagementProfile(
            engagement_id=f"b_corp_{year}",
            company_id="b_corp",
            fiscal_year=year,
        )
        repo.create_engagement("b_corp", eng)

    return repo


@pytest.fixture()
def b_profile_dir(b_repo: CompanyRepository) -> Path:
    """B회사 프로파일 디렉토리."""
    return b_repo.profile_dir("b_corp")


# ── 1년차: 최초 매핑 ────────────────────────────────────


class TestYear1InitialMapping:
    """1년차: 최초 업로드 → 수동 매핑 → 프로파일 저장 → 키워드 학습."""

    def test_auto_map_sap_columns(self):
        """SAP 컬럼이 글로벌 keywords로 자동 매핑된다."""
        result = auto_map_columns(
            SAP_COLUMNS_Y1_Y2,
            matched_keywords=[],
            keywords=GLOBAL_KEYWORDS,
        )
        # SAP 별칭이 글로벌 keywords에 있으므로 대부분 자동 매핑
        assert "BELNR" in result.mapping or "BELNR" in result.suggestions

    def test_save_profile_creates_file(self, b_profile_dir: Path):
        """프로파일 저장 → 파일 생성."""
        result = MappingResult(
            mapping={
                "BELNR": "document_id",
                "BUDAT": "posting_date",
                "BLDAT": "document_date",
                "RACCT": "gl_account",
                "WRBTR_D": "debit_amount",
                "WRBTR_C": "credit_amount",
                "BLART": "document_type",
                "BUKRS": "company_code",
            },
            suggestions={},
            confidence={col: 1.0 for col in SAP_COLUMNS_Y1_Y2},
            unmapped=[],
            missing_required=[],
            needs_review=False,
        )

        path = save_profile(
            result, SAP_COLUMNS_Y1_Y2,
            source_name="b_corp_gl_2023.xlsx",
            profile_dir=b_profile_dir,
        )
        assert path.exists()

    def test_keyword_learning(self, b_repo: CompanyRepository):
        """수동 매핑에서 글로벌에 없는 별칭이 학습된다."""
        # 사용자가 수동으로 매핑한 컬럼 (글로벌에 없는 별칭)
        user_overrides = {"전표구분": "document_type"}

        company_kw = b_repo.load_company_keywords("b_corp")
        new_kw = learn_from_mapping(
            user_overrides, company_kw, GLOBAL_KEYWORDS,
        )

        assert new_kw is not None
        assert "전표구분" in new_kw["document_type"]

        # 학습 결과 저장
        b_repo.save_company_keywords("b_corp", new_kw)

        # 저장 확인
        saved_kw = b_repo.load_company_keywords("b_corp")
        assert "전표구분" in saved_kw["document_type"]


# ── 2년차: 프로파일 자동 적용 ────────────────────────────


class TestYear2AutoProfile:
    """2년차: 동일 ERP 구조 → 프로파일 자동 적용. 수동 매핑 불필요."""

    def test_same_fingerprint(self):
        """1~2년차 동일 컬럼 → 동일 fingerprint."""
        fp1 = column_fingerprint(SAP_COLUMNS_Y1_Y2)
        fp2 = column_fingerprint(SAP_COLUMNS_Y1_Y2)
        assert fp1 == fp2

    def test_profile_auto_loaded(self, b_profile_dir: Path):
        """1년차에 저장한 프로파일이 2년차에서 자동 로드."""
        # 1년차 프로파일 저장
        y1_result = MappingResult(
            mapping={
                "BELNR": "document_id",
                "BUDAT": "posting_date",
                "BLDAT": "document_date",
                "RACCT": "gl_account",
                "WRBTR_D": "debit_amount",
                "WRBTR_C": "credit_amount",
                "BLART": "document_type",
                "BUKRS": "company_code",
            },
            suggestions={},
            confidence={col: 1.0 for col in SAP_COLUMNS_Y1_Y2},
            unmapped=[],
            missing_required=[],
            needs_review=False,
        )
        save_profile(y1_result, SAP_COLUMNS_Y1_Y2, profile_dir=b_profile_dir)

        # 2년차 — 동일 컬럼으로 로드
        loaded = load_profile(SAP_COLUMNS_Y1_Y2, profile_dir=b_profile_dir)

        assert loaded is not None
        assert loaded.needs_review is False
        assert loaded.mapping["BELNR"] == "document_id"
        assert loaded.mapping["BUDAT"] == "posting_date"
        assert len(loaded.mapping) == 8


# ── 3년차: 새 컬럼 + 키워드 학습 효과 ───────────────────


class TestYear3NewColumnReview:
    """3년차: 새 컬럼 추가 → fingerprint 변경 → 기존은 keyword match."""

    def test_new_columns_change_fingerprint(self):
        """새 컬럼 추가 → fingerprint 변경."""
        fp_y2 = column_fingerprint(SAP_COLUMNS_Y1_Y2)
        fp_y3 = column_fingerprint(SAP_COLUMNS_Y3)
        assert fp_y2 != fp_y3

    def test_profile_not_found_for_new_structure(self, b_profile_dir: Path):
        """fingerprint 변경 → 기존 프로파일 로드 실패."""
        # 1~2년차 프로파일 저장
        y1_result = MappingResult(
            mapping={"BELNR": "document_id"},
            suggestions={},
            confidence={"BELNR": 1.0},
            unmapped=[],
            missing_required=[],
            needs_review=False,
        )
        save_profile(y1_result, SAP_COLUMNS_Y1_Y2, profile_dir=b_profile_dir)

        # 3년차 — 새 컬럼 포함 → 다른 fingerprint
        loaded = load_profile(SAP_COLUMNS_Y3, profile_dir=b_profile_dir)
        assert loaded is None

    def test_existing_columns_matched_by_keywords(self):
        """키워드 학습 덕분에 기존 8개 컬럼은 Phase 1에서 즉시 매칭."""
        # 1년차에 학습한 회사 keywords를 시뮬레이션
        company_keywords = {
            "document_type": ["전표구분"],  # 1년차에 학습된 별칭
        }
        # 글로벌 + 회사 keywords 머지 (resolve_yaml_config 시뮬레이션)
        merged_keywords = {}
        for col, aliases in GLOBAL_KEYWORDS.items():
            merged_keywords[col] = list(aliases)
        for col, aliases in company_keywords.items():
            if col in merged_keywords:
                merged_keywords[col].extend(aliases)
            else:
                merged_keywords[col] = list(aliases)

        # 3년차 매핑 — 기존 컬럼은 keywords로 매칭
        result = auto_map_columns(
            SAP_COLUMNS_Y3,
            matched_keywords=[],
            keywords=merged_keywords,
        )

        # 기존 8개 컬럼은 확정 매핑 (Green)에 있어야 함
        for col in SAP_COLUMNS_Y1_Y2:
            assert col in result.mapping, f"{col}이 매핑에 없음"

    def test_new_columns_need_review(self):
        """새 컬럼(KOSTL, PRCTR)은 review 대상."""
        result = auto_map_columns(
            SAP_COLUMNS_Y3,
            matched_keywords=[],
            keywords=GLOBAL_KEYWORDS,
        )

        # KOSTL, PRCTR은 글로벌 keywords에 없으므로
        # suggestions 또는 unmapped에 있어야 함
        new_cols = {"KOSTL", "PRCTR"}
        in_suggestions = new_cols & set(result.suggestions.keys())
        in_unmapped = new_cols & set(result.unmapped)
        # 둘 중 하나에라도 있으면 정상 (review 대상)
        assert in_suggestions | in_unmapped == new_cols


# ── 전체 시나리오 통합 ───────────────────────────────────


class TestFullScenario:
    """1~3년차 전체 시나리오를 순차 실행."""

    def test_3year_workflow(self, b_repo: CompanyRepository, b_profile_dir: Path):
        """1년차 매핑 → 2년차 자동적용 → 3년차 새 컬럼만 review."""
        # ── 1년차: 최초 매핑 + 프로파일 저장 + 키워드 학습 ──
        y1_mapping = {
            "BELNR": "document_id",
            "BUDAT": "posting_date",
            "BLDAT": "document_date",
            "RACCT": "gl_account",
            "WRBTR_D": "debit_amount",
            "WRBTR_C": "credit_amount",
            "BLART": "document_type",
            "BUKRS": "company_code",
        }
        y1_result = MappingResult(
            mapping=y1_mapping,
            suggestions={},
            confidence={col: 1.0 for col in SAP_COLUMNS_Y1_Y2},
            unmapped=[],
            missing_required=[],
            needs_review=False,
        )
        save_profile(
            y1_result, SAP_COLUMNS_Y1_Y2,
            source_name="b_corp_gl_2023.xlsx",
            profile_dir=b_profile_dir,
        )

        # 수동 매핑 키워드 학습
        user_manual = {"전표구분": "document_type"}
        company_kw = b_repo.load_company_keywords("b_corp")
        new_kw = learn_from_mapping(user_manual, company_kw, GLOBAL_KEYWORDS)
        if new_kw:
            b_repo.save_company_keywords("b_corp", new_kw)

        # ── 2년차: 동일 ERP → 프로파일 자동 적용 ──
        loaded_y2 = load_profile(SAP_COLUMNS_Y1_Y2, profile_dir=b_profile_dir)
        assert loaded_y2 is not None, "2년차: 프로파일 자동 로드 실패"
        assert loaded_y2.needs_review is False, "2년차: 불필요한 review 발생"
        assert loaded_y2.mapping == y1_mapping, "2년차: 매핑 불일치"

        # ── 3년차: 새 컬럼 추가 → fingerprint 변경 ──
        loaded_y3 = load_profile(SAP_COLUMNS_Y3, profile_dir=b_profile_dir)
        assert loaded_y3 is None, "3년차: fingerprint 변경인데 프로파일 로드됨"

        # 키워드 학습 효과 — 기존 컬럼은 exact match
        saved_kw = b_repo.load_company_keywords("b_corp")
        merged = {}
        for col, aliases in GLOBAL_KEYWORDS.items():
            merged[col] = list(aliases)
        if saved_kw:
            for col, aliases in saved_kw.items():
                if col in merged:
                    merged[col].extend(aliases)
                else:
                    merged[col] = list(aliases)

        y3_result = auto_map_columns(
            SAP_COLUMNS_Y3,
            matched_keywords=[],
            keywords=merged,
        )

        # 기존 8개 컬럼 → 확정 매핑 (Green)
        for col in SAP_COLUMNS_Y1_Y2:
            assert col in y3_result.mapping, f"3년차: {col} 매핑 실패"

        # 새 컬럼 → review 대상
        new_cols = {"KOSTL", "PRCTR"}
        reviewed = (new_cols & set(y3_result.suggestions.keys())) | \
                   (new_cols & set(y3_result.unmapped))
        assert reviewed == new_cols, "3년차: 새 컬럼이 review 대상이 아님"
