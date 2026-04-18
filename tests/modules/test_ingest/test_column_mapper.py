"""컬럼 자동 매핑 모듈 테스트.

테스트 그룹:
  - prepare_dataframe: 헤더 행 → 컬럼명 + 데이터 추출
  - fast path: DataSynth 표준 컬럼 → 동일 매핑 즉시 반환
  - exact match: 한글 별칭, SAP 코드, matched_keywords 활용
  - fuzzy match: 유사 별칭, threshold 미달, 부분 매칭
  - 충돌 해결: 두 원본→같은 표준, greedy assign
  - auto_map_columns 통합: 전체 매칭, 혼합, 필수 누락, fast path, 빈 리스트
  - map_columns 퍼사드: 멀티시트, 단일시트 CSV
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ingest._type_compat import infer_column_type, validate_type_compatibility
from src.ingest.column_mapper import (
    _build_alias_map,
    _exact_match,
    _fuzzy_match,
    _get_required_columns,
    _greedy_assign,
    _is_standard_schema,
    _suggest_amount_split,
    auto_map_columns,
    map_columns,
    prepare_dataframe,
)
from src.ingest.models import HeaderDetectionResult, MappingResult, ReadResult, ReviewItem


# ── 공용 fixture ──────────────────────────────────────────


@pytest.fixture
def sample_keywords() -> dict:
    """테스트용 최소 keywords dict."""
    return {
        "document_id": ["전표번호", "belnr", "Doc No", "document_id"],
        "posting_date": ["전표일자", "budat", "posting_date"],
        "gl_account": ["계정코드", "racct", "hkont", "gl_account"],
        "debit_amount": ["차변금액", "차변", "debit", "debit_amount"],
        "credit_amount": ["대변금액", "대변", "credit", "credit_amount"],
        "line_text": ["적요", "sgtxt", "line_text"],
        "created_by": ["작성자", "usnam", "created_by"],
        "source": ["입력구분", "source"],
        "company_code": ["회사코드", "bukrs", "company_code"],
        "fiscal_year": ["회계연도", "gjahr", "fiscal_year"],
        "document_date": ["증빙일자", "bldat", "document_date"],
        "document_type": ["전표유형", "blart", "document_type"],
    }


@pytest.fixture
def sample_schema() -> dict:
    """테스트용 최소 schema dict."""
    return {
        "columns": [
            {"name": "document_id", "type": "str", "required": True},
            {"name": "company_code", "type": "str", "required": True},
            {"name": "fiscal_year", "type": "int", "required": True},
            {"name": "posting_date", "type": "date", "required": True},
            {"name": "document_date", "type": "date", "required": True},
            {"name": "gl_account", "type": "int", "required": True},
            {"name": "debit_amount", "type": "float", "required": True},
            {"name": "credit_amount", "type": "float", "required": True},
            {"name": "document_type", "type": "str", "required": True},
            {"name": "created_by", "type": "str", "required": False},
            {"name": "source", "type": "str", "required": False},
            {"name": "line_text", "type": "str", "required": False},
        ],
    }


# ── prepare_dataframe ──────────────────────────────────────


class TestPrepareDataframe:
    """헤더 행 → 컬럼명 + 데이터 추출."""

    def test_row_0_extraction(self):
        """row=0일 때 0행이 컬럼명, 1행부터 데이터."""
        raw = pd.DataFrame([
            ["전표번호", "금액", "적요"],
            ["001", 10000, "테스트"],
            ["002", 20000, "샘플"],
        ])
        cols, data = prepare_dataframe(raw, header_row=0)
        assert cols == ["전표번호", "금액", "적요"]
        assert len(data) == 2
        assert list(data.columns) == ["전표번호", "금액", "적요"]

    def test_row_2_extraction(self):
        """row=2일 때 2행이 컬럼명, 3행부터 데이터."""
        raw = pd.DataFrame([
            ["[보고서]", None, None],
            ["작성일: 2025-01-01", None, None],
            ["전표번호", "금액", "적요"],
            ["001", 10000, "테스트"],
        ])
        cols, data = prepare_dataframe(raw, header_row=2)
        assert cols == ["전표번호", "금액", "적요"]
        assert len(data) == 1

    def test_nan_column_filtered(self):
        """NaN 컬럼명은 제거."""
        raw = pd.DataFrame([
            ["전표번호", None, "금액"],
            ["001", "빈열", 10000],
        ])
        cols, data = prepare_dataframe(raw, header_row=0)
        assert "전표번호" in cols
        assert "금액" in cols
        assert "" not in cols
        assert len(cols) == 2


# ── fast path ──────────────────────────────────────────────


class TestFastPath:
    """필수 9컬럼 정확 일치 → fast path."""

    def test_standard_columns_fast_path(
        self, cm_standard_columns, sample_schema, sample_keywords,
    ):
        """DataSynth 표준 컬럼 → needs_review=False, 동일 매핑."""
        result = auto_map_columns(
            cm_standard_columns,
            schema=sample_schema,
            keywords=sample_keywords,
        )
        assert result.needs_review is False
        assert result.missing_required == []
        # 표준 컬럼은 자기 자신에 매핑
        for col in cm_standard_columns:
            if col in result.mapping:
                assert result.mapping[col] == col

    def test_erp_korean_not_fast_path(
        self, cm_korean_columns, sample_schema, sample_keywords,
    ):
        """한글 별칭은 fast path 아님 — 정확 일치 경로로 진행."""
        result = auto_map_columns(
            cm_korean_columns,
            schema=sample_schema,
            keywords=sample_keywords,
        )
        # 한글 별칭이지만 exact match로 매핑 성공
        assert "전표번호" in result.mapping
        assert result.mapping["전표번호"] == "document_id"


# ── exact match ──────────────────────────────────────────


class TestExactMatch:
    """정확 일치 매칭."""

    def test_korean_aliases(self, sample_keywords):
        """한글 별칭 정확 일치."""
        alias_map = _build_alias_map(sample_keywords)
        result = _exact_match(["전표번호", "차변금액"], alias_map, None)
        assert result["전표번호"][0] == "document_id"
        assert result["차변금액"][0] == "debit_amount"
        assert result["전표번호"][1] == 1.0

    def test_sap_codes(self, sample_keywords):
        """SAP 코드 정확 일치."""
        alias_map = _build_alias_map(sample_keywords)
        result = _exact_match(["belnr", "racct", "budat"], alias_map, None)
        assert result["belnr"][0] == "document_id"
        assert result["racct"][0] == "gl_account"
        assert result["budat"][0] == "posting_date"

    def test_matched_keywords_from_header_detector(self, sample_keywords):
        """header_detector matched_keywords 활용."""
        alias_map = _build_alias_map(sample_keywords)
        matched_kw = ["전표번호", "차변금액"]
        result = _exact_match(
            ["전표번호", "차변금액", "알수없는컬럼"],
            alias_map,
            matched_kw,
        )
        assert "전표번호" in result
        assert "알수없는컬럼" not in result


# ── fuzzy match ──────────────────────────────────────────


class TestFuzzyMatch:
    """퍼지 매칭."""

    def test_similar_alias(self, sample_keywords):
        """유사한 별칭 — 높은 스코어."""
        alias_map = _build_alias_map(sample_keywords)
        result = _fuzzy_match(["전표 번호"], alias_map)
        assert "전표 번호" in result
        std, score = result["전표 번호"]
        assert std == "document_id"
        assert score > 70  # 높은 유사도

    def test_low_score_column(self, sample_keywords):
        """전혀 다른 컬럼명 — 낮은 스코어."""
        alias_map = _build_alias_map(sample_keywords)
        result = _fuzzy_match(["XYZABC123"], alias_map)
        if "XYZABC123" in result:
            _, score = result["XYZABC123"]
            assert score < 80  # threshold 미달

    def test_partial_match(self, sample_keywords):
        """부분 매칭 — 중간 스코어."""
        alias_map = _build_alias_map(sample_keywords)
        result = _fuzzy_match(["GL코드"], alias_map)
        # GL코드 vs gl_account: 부분 일치
        assert "GL코드" in result


# ── 충돌 해결 ──────────────────────────────────────────────


class TestConflictResolution:
    """1:1 greedy assign 충돌 해결."""

    def test_two_sources_same_standard(self):
        """두 원본이 같은 표준 컬럼 → 스코어 높은 쪽 우선."""
        candidates = {
            "전표No": ("document_id", 90.0),
            "전표번호": ("document_id", 100.0),
        }
        mapping, suggestions, confidence, unmapped = _greedy_assign(
            candidates, threshold=80, low_threshold=40,
        )
        # 전표번호(100)가 우선, 전표No는 unmapped
        assert mapping["전표번호"] == "document_id"
        assert "전표No" in unmapped

    def test_score_threshold_boundary(self):
        """threshold 경계값 테스트 — 80 이상 mapping, 40~79 suggestions."""
        candidates = {
            "col_high": ("document_id", 85.0),
            "col_mid": ("posting_date", 60.0),
            "col_low": ("gl_account", 30.0),
        }
        mapping, suggestions, confidence, unmapped = _greedy_assign(
            candidates, threshold=80, low_threshold=40,
        )
        assert "col_high" in mapping
        assert "col_mid" in suggestions
        assert "col_low" in unmapped


# ── auto_map_columns 통합 ──────────────────────────────────


class TestAutoMapColumns:
    """auto_map_columns 통합 테스트."""

    def test_full_korean_match(
        self, cm_korean_columns, sample_schema, sample_keywords,
    ):
        """한글 별칭 전체 매핑 성공."""
        result = auto_map_columns(
            cm_korean_columns,
            schema=sample_schema,
            keywords=sample_keywords,
        )
        assert result.missing_required == []
        assert len(result.mapping) >= 9  # 필수 9개 이상 매핑

    def test_mixed_columns(
        self, cm_mixed_columns, sample_schema, sample_keywords,
    ):
        """혼합 컬럼 — 일부 매핑, 일부 추천, 일부 unmapped."""
        result = auto_map_columns(
            cm_mixed_columns,
            schema=sample_schema,
            keywords=sample_keywords,
        )
        # 전표번호, posting_date, 차변, Credit Amount는 매핑 성공 기대
        assert "전표번호" in result.mapping
        assert "posting_date" in result.mapping
        # XYZ_UNKNOWN은 unmapped 기대
        assert "XYZ_UNKNOWN" in result.unmapped or "XYZ_UNKNOWN" in result.suggestions

    def test_missing_required_detected(self, sample_schema, sample_keywords):
        """필수 컬럼 누락 시 missing_required 포함."""
        result = auto_map_columns(
            ["전표번호", "차변금액"],
            schema=sample_schema,
            keywords=sample_keywords,
        )
        assert len(result.missing_required) > 0
        assert result.needs_review is True

    def test_fast_path_identity(
        self, cm_standard_columns, sample_schema, sample_keywords,
    ):
        """fast path — 동일 매핑, missing_required 비어있음."""
        result = auto_map_columns(
            cm_standard_columns,
            schema=sample_schema,
            keywords=sample_keywords,
        )
        assert result.missing_required == []
        assert result.needs_review is False

    def test_empty_list(self, sample_schema, sample_keywords):
        """빈 리스트 → 필수 컬럼 전부 missing."""
        result = auto_map_columns(
            [],
            schema=sample_schema,
            keywords=sample_keywords,
        )
        assert result.mapping == {}
        assert len(result.missing_required) == 9
        assert result.needs_review is True


# ── map_columns 퍼사드 ──────────────────────────────────────


class TestMapColumns:
    """멀티시트 퍼사드 테스트."""

    def test_single_sheet_csv(self, sample_schema, sample_keywords):
        """CSV 단일시트 — Sheet1."""
        raw_df = pd.DataFrame([
            ["전표번호", "전표일자", "계정코드", "차변금액", "대변금액"],
            ["001", "2025-01-01", "1110", 10000, 0],
        ])
        read_result = ReadResult(
            sheets=["Sheet1"],
            active_sheet="Sheet1",
            raw_data={"Sheet1": raw_df},
            source_format="csv",
        )
        header_results = {
            "Sheet1": HeaderDetectionResult(
                header_row=0,
                confidence=0.9,
                matched_keywords=["전표번호", "전표일자", "계정코드", "차변금액", "대변금액"],
                total_columns=5,
                message="OK",
            ),
        }
        results = map_columns(
            read_result, header_results,
            schema=sample_schema, keywords=sample_keywords,
        )
        assert "Sheet1" in results
        assert isinstance(results["Sheet1"], MappingResult)
        assert "전표번호" in results["Sheet1"].mapping

    def test_multi_sheet_with_failed_header(self, sample_schema, sample_keywords):
        """멀티시트 — 하나는 성공, 하나는 헤더 탐지 실패."""
        raw_df1 = pd.DataFrame([
            ["전표번호", "차변금액"],
            ["001", 10000],
        ])
        raw_df2 = pd.DataFrame([
            [None, None],
            [1, 2],
        ])
        read_result = ReadResult(
            sheets=["매출", "빈시트"],
            active_sheet="매출",
            raw_data={"매출": raw_df1, "빈시트": raw_df2},
            source_format="xlsx",
        )
        header_results = {
            "매출": HeaderDetectionResult(
                header_row=0, confidence=0.8,
                matched_keywords=["전표번호", "차변금액"],
                total_columns=2, message="OK",
            ),
            "빈시트": HeaderDetectionResult(
                header_row=None, confidence=0.1,
                matched_keywords=[], total_columns=2,
                message="헤더 탐지 실패",
            ),
        }
        results = map_columns(
            read_result, header_results,
            schema=sample_schema, keywords=sample_keywords,
        )
        # 매출: 매핑 시도
        assert "전표번호" in results["매출"].mapping
        # 빈시트: 헤더 실패 → needs_review=True
        assert results["빈시트"].needs_review is True
        assert results["빈시트"].mapping == {}


# ── 내부 헬퍼 단위 테스트 ──────────────────────────────────


class TestBuildAliasMap:
    """_build_alias_map 단위 테스트."""

    def test_basic_mapping(self, sample_keywords):
        """기본 매핑 생성."""
        alias_map = _build_alias_map(sample_keywords)
        assert alias_map["전표번호"] == "document_id"
        assert alias_map["belnr"] == "document_id"
        assert alias_map["차변"] == "debit_amount"

    def test_case_insensitive(self, sample_keywords):
        """대소문자 무관."""
        alias_map = _build_alias_map(sample_keywords)
        assert alias_map["doc no"] == "document_id"


class TestGetRequiredColumns:
    """_get_required_columns 단위 테스트."""

    def test_required_count(self, sample_schema):
        """필수 9개 추출."""
        required = _get_required_columns(sample_schema)
        assert len(required) == 9
        assert "document_id" in required
        assert "created_by" not in required


class TestIsStandardSchema:
    """_is_standard_schema 단위 테스트."""

    def test_standard_true(self, sample_schema):
        """필수 컬럼 모두 포함 → True."""
        required = _get_required_columns(sample_schema)
        cols = list(required) + ["created_by", "extra_col"]
        assert _is_standard_schema(cols, required) is True

    def test_missing_one_required(self, sample_schema):
        """필수 1개 누락 → False."""
        required = _get_required_columns(sample_schema)
        cols = list(required)[:-1]  # 마지막 하나 제거
        assert _is_standard_schema(cols, required) is False


# ── 타입 호환성 검증 (B1) ──────────────────────────────────


class TestInferColumnType:
    """_infer_column_type 단위 테스트."""

    def test_numeric_int(self):
        """정수 컬럼 → 'int'."""
        s = pd.Series(["1000", "2000", "3000", "4000"])
        assert infer_column_type(s) == "int"

    def test_numeric_float(self):
        """실수 컬럼 → 'float'."""
        s = pd.Series(["1000.5", "2000.3", "3000.7"])
        assert infer_column_type(s) == "float"

    def test_date_regex_fast(self):
        """날짜 정규식 fast path → 'date'."""
        s = pd.Series(["2025-01-01", "2025-02-15", "2025-03-20"])
        assert infer_column_type(s) == "date"

    def test_string(self):
        """문자열 컬럼 → 'str'."""
        s = pd.Series(["hello", "world", "test", "foo"])
        assert infer_column_type(s) == "str"

    def test_all_nan(self):
        """100% NaN → 'unknown'."""
        s = pd.Series([None, None, None])
        assert infer_column_type(s) == "unknown"


class TestTypeCompatibility:
    """validate_type_compatibility 단위 테스트."""

    def test_str_to_float_blocked(self):
        """str → float 차단."""
        assert validate_type_compatibility("str", "float") is False

    def test_str_to_date_blocked(self):
        """str → date 차단."""
        assert validate_type_compatibility("str", "date") is False

    def test_int_to_float_allowed(self):
        """int → float 허용."""
        assert validate_type_compatibility("int", "float") is True

    def test_unknown_always_allowed(self):
        """unknown → 모든 타입 허용."""
        for target in ("float", "date", "int", "str", "bool"):
            assert validate_type_compatibility("unknown", target) is True

    def test_fuzzy_with_data_df_blocks_type_mismatch(self, sample_keywords, sample_schema):
        """drcrk(str) → debit_amount(float) 타입 비호환 차단 E2E."""
        data_df = pd.DataFrame({
            "drcrk": ["S", "H", "S", "H", "S"],
        })
        result = auto_map_columns(
            ["drcrk"],
            data_df=data_df,
            schema=sample_schema,
            keywords=sample_keywords,
        )
        # drcrk이 debit_amount로 오매핑되면 안 됨
        if "drcrk" in result.mapping:
            assert result.mapping["drcrk"] != "debit_amount"

    def test_dc_indicator_exact_match(self):
        """drcrk → dc_indicator 키워드 정확 일치."""
        from config.settings import get_keywords, get_schema
        keywords = get_keywords()
        schema = get_schema()
        result = auto_map_columns(
            ["drcrk", "debit_amount", "credit_amount"],
            schema=schema,
            keywords=keywords,
        )
        # drcrk은 dc_indicator에 정확 매칭되어야 함
        assert result.mapping.get("drcrk") == "dc_indicator"


class TestReviewItems:
    """ReviewItem 생성 테스트."""

    def test_review_items_generated(self, sample_schema, sample_keywords):
        """매핑 결과에 ReviewItem이 정상 생성되는지 확인."""
        result = auto_map_columns(
            ["전표번호", "차변금액", "XYZ_UNKNOWN"],
            schema=sample_schema,
            keywords=sample_keywords,
        )
        assert len(result.review_items) > 0
        # 전표번호 → auto
        auto_items = [r for r in result.review_items if r.action == "auto"]
        assert any(r.column == "전표번호" for r in auto_items)
        # XYZ_UNKNOWN → review 또는 unmapped
        review_items = [r for r in result.review_items if r.column == "XYZ_UNKNOWN"]
        assert len(review_items) > 0

    def test_review_items_with_data_df(self, sample_schema, sample_keywords):
        """data_df 전달 시 source_type 정보 포함."""
        data_df = pd.DataFrame({
            "전표번호": ["JE001", "JE002"],
            "XYZ_COL": [100, 200],
        })
        result = auto_map_columns(
            ["전표번호", "XYZ_COL"],
            data_df=data_df,
            schema=sample_schema,
            keywords=sample_keywords,
        )
        # XYZ_COL의 ReviewItem에 source_type 존재
        xyz_items = [r for r in result.review_items if r.column == "XYZ_COL"]
        assert len(xyz_items) > 0


# ── 중복 금액 퀵픽스 ──────────────────────────────────


class TestSuggestAmountSplit:
    """_suggest_amount_split — 인접 중복 금액 컬럼 추천."""

    def test_adjacent_duplicate_amount(self):
        """'금액' + '금액_2' 인접 → 차변/대변 추천 2건."""
        columns = ["전표번호", "금액", "금액_2", "적요"]
        items = _suggest_amount_split(columns)
        assert len(items) == 2
        assert items[0].column == "금액"
        assert items[0].target_type == "debit_amount"
        assert items[1].column == "금액_2"
        assert items[1].target_type == "credit_amount"
        # action=review (자동 적용 아님)
        assert all(i.action == "review" for i in items)

    def test_non_adjacent_ignored(self):
        """'금액'과 '금액_2'가 비인접 → 추천 안 함."""
        columns = ["금액", "적요", "금액_2"]
        items = _suggest_amount_split(columns)
        assert len(items) == 0

    def test_three_duplicates_ignored(self):
        """'금액' 3개 이상 중복 → 모호하므로 추천 안 함."""
        columns = ["금액", "금액_2", "금액_3"]
        items = _suggest_amount_split(columns)
        assert len(items) == 0

    def test_non_amount_keyword_ignored(self):
        """금액 키워드가 아닌 중복 → 추천 안 함."""
        columns = ["날짜", "날짜_2"]
        items = _suggest_amount_split(columns)
        assert len(items) == 0

    def test_english_amount_keyword(self):
        """영문 'amount' 키워드도 탐지."""
        columns = ["id", "amount", "amount_2"]
        items = _suggest_amount_split(columns)
        assert len(items) == 2

    def test_amt_keyword(self):
        """약어 'amt' 키워드도 탐지."""
        columns = ["amt", "amt_2"]
        items = _suggest_amount_split(columns)
        assert len(items) == 2

    def test_map_columns_integrates_amount_split(self, sample_schema, sample_keywords):
        """map_columns 퍼사드에서 금액 추천이 review_items에 병합되는지 E2E."""
        raw_df = pd.DataFrame([
            ["전표번호", "전표일자", "금액", "금액"],
            ["001", "2025-01-01", 10000, 5000],
        ])
        read_result = ReadResult(
            sheets=["Sheet1"],
            active_sheet="Sheet1",
            raw_data={"Sheet1": raw_df},
            source_format="csv",
        )
        header_results = {
            "Sheet1": HeaderDetectionResult(
                header_row=0,
                confidence=0.9,
                matched_keywords=["전표번호", "전표일자"],
                total_columns=4,
                message="OK",
            ),
        }
        with pytest.warns(UserWarning, match="중복 컬럼명 감지"):
            results = map_columns(
                read_result, header_results,
                schema=sample_schema, keywords=sample_keywords,
            )
        mr = results["Sheet1"]
        # 금액 추천 ReviewItem이 포함되어야 함
        amount_items = [r for r in mr.review_items if "인접 중복" in r.reason]
        assert len(amount_items) == 2
        assert mr.needs_review is True
