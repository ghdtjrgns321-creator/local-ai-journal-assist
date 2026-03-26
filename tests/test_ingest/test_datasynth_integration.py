"""DataSynth v1.2.0 CSV × ingest 파이프라인 통합 검증.

data/journal/primary/datasynth/journal_entries.csv (319MB, 39컬럼)를
실제 파이프라인에 통과시켜 schema.yaml 정합성을 검증한다.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
from src.ingest.file_validator import validate_file
from src.ingest.header_detector import detect_header_row
from src.ingest.reader_api import read_file
from src.ingest.type_caster import cast_dataframe

DATASYNTH_CSV = Path("data/journal/primary/datasynth/journal_entries.csv")
SCHEMA_PATH = Path("config/schema.yaml")


def _load_schema() -> dict:
    """schema.yaml 로드."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def schema() -> dict:
    return _load_schema()


@pytest.fixture(scope="module")
def pipeline_result():
    """DataSynth CSV 전체 파이프라인 실행 (모듈 스코프 — 1회만 실행).

    Why: 319MB CSV 반복 로드 방지. slow 마커로 일반 실행 시 건너뜀.
    """
    if not DATASYNTH_CSV.exists():
        pytest.skip("DataSynth CSV 없음")

    # ① 파일 검증
    vr = validate_file(DATASYNTH_CSV)
    assert vr.is_valid, f"파일 검증 실패: {vr.errors}"

    # ② 파일 읽기
    rr = read_file(DATASYNTH_CSV)
    raw_df = rr.raw_data[rr.active_sheet]

    # ③ 헤더 탐지 — text_reader는 header=None으로 읽으므로 헤더 행 탐지 필요
    hr = detect_header_row(raw_df)
    columns, data_df = prepare_dataframe(raw_df, hr.header_row if hr.header_row is not None else 0)

    # ④ 컬럼 매핑 (schema.yaml 기반)
    mr = auto_map_columns(columns, matched_keywords=hr.matched_keywords, data_df=data_df)

    # ⑤ rename + 캐스팅
    renamed_df = data_df.rename(columns=mr.mapping)
    cr = cast_dataframe(renamed_df)

    return {
        "validation": vr,
        "read_result": rr,
        "raw_df": raw_df,
        "data_df": data_df,
        "header": hr,
        "columns": columns,
        "mapping": mr,
        "casting": cr,
    }


# ── 테스트 ─────────────────────────────────────────────────


class TestDataSynthValidation:
    """① 파일 검증."""

    def test_file_valid(self, pipeline_result):
        vr = pipeline_result["validation"]
        assert vr.is_valid
        assert vr.file_category == "text"


class TestDataSynthRead:
    """② 파일 읽기."""

    def test_source_format(self, pipeline_result):
        rr = pipeline_result["read_result"]
        assert rr.source_format == "csv"

    def test_encoding(self, pipeline_result):
        rr = pipeline_result["read_result"]
        assert rr.encoding is not None

    def test_row_count(self, pipeline_result):
        """PREVIEW.md 기준 1,106,356 라인아이템 (data_df = 헤더 제외)."""
        data_df = pipeline_result["data_df"]
        assert data_df.shape[0] == 1_106_356


class TestDataSynthColumnMapping:
    """④ 컬럼 매핑 — fast path 검증."""

    def test_fast_path_activated(self, pipeline_result):
        """필수 10컬럼 모두 포함 → fast path → needs_review=False."""
        mr = pipeline_result["mapping"]
        assert mr.needs_review is False

    def test_no_missing_required(self, pipeline_result):
        mr = pipeline_result["mapping"]
        assert mr.missing_required == []

    def test_non_label_columns_mapped(self, pipeline_result, schema):
        """schema.yaml 비레이블 컬럼이 모두 매핑.

        Why: bool 타입(is_fraud, is_anomaly, sod_violation)은 DataSynth 전용 레이블로
        _get_all_standard_columns에서 제외됨 → 매핑 대상 아님 (의도된 동작).
        """
        mr = pipeline_result["mapping"]
        # 레이블(bool) 제외한 표준 컬럼
        non_label = {
            col["name"] for col in schema["columns"]
            if not col.get("is_label", col.get("type") == "bool")
        }
        mapped_standards = set(mr.mapping.values())
        missing = non_label - mapped_standards
        assert missing == set(), f"비레이블 컬럼 중 미매핑: {missing}"

    def test_identity_mapping(self, pipeline_result):
        """fast path에서 표준 컬럼은 자기 자신에 매핑."""
        mr = pipeline_result["mapping"]
        for src, std in mr.mapping.items():
            assert src == std, f"비동일 매핑: {src} → {std}"

    def test_column_count_39(self, pipeline_result):
        """DataSynth CSV가 정확히 39개 컬럼."""
        columns = pipeline_result["columns"]
        assert len(columns) == 39


class TestDataSynthCasting:
    """⑤ 타입 캐스팅."""

    def test_casting_success(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert cr.success, f"캐스팅 실패: {cr.errors}"

    def test_no_casting_errors(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert cr.errors == []

    def test_debit_credit_float64(self, pipeline_result):
        """금액 컬럼이 float64로 캐스팅."""
        cr = pipeline_result["casting"]
        assert cr.data["debit_amount"].dtype == "float64"
        assert cr.data["credit_amount"].dtype == "float64"

    def test_posting_date_datetime(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert pd.api.types.is_datetime64_any_dtype(cr.data["posting_date"])

    def test_is_fraud_bool(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert cr.data["is_fraud"].dtype == "boolean"

    def test_fiscal_period_int(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert cr.data["fiscal_period"].dtype == "Int64"

    def test_gl_account_str(self, pipeline_result):
        """gl_account이 str로 유지 (선행 0 보존)."""
        cr = pipeline_result["casting"]
        assert cr.data["gl_account"].dtype == "object"

    def test_final_shape(self, pipeline_result):
        """최종 shape: 1,106,356행 × 39열."""
        cr = pipeline_result["casting"]
        assert cr.data.shape[0] == 1_106_356
        assert cr.data.shape[1] == 39


class TestDataSynthDataQuality:
    """데이터 품질 검증 — generation_principles.md 기준."""

    def test_company_codes(self, pipeline_result):
        """3개 법인: C001, C002, C003."""
        cr = pipeline_result["casting"]
        codes = set(cr.data["company_code"].dropna().unique())
        assert codes == {"C001", "C002", "C003"}

    def test_document_types(self, pipeline_result):
        """전표유형 — 최소 9개 핵심 유형 포함."""
        cr = pipeline_result["casting"]
        types = set(cr.data["document_type"].dropna().unique())
        core_types = {"SA", "KR", "KZ", "DR", "DZ", "WE", "AA", "HR", "IC"}
        assert core_types.issubset(types), f"누락 유형: {core_types - types}"

    def test_business_processes(self, pipeline_result):
        """6개 비즈니스 프로세스."""
        cr = pipeline_result["casting"]
        processes = set(cr.data["business_process"].dropna().unique())
        expected = {"P2P", "O2C", "R2R", "H2R", "TRE", "A2R"}
        assert processes == expected

    def test_user_personas(self, pipeline_result):
        """5개 페르소나."""
        cr = pipeline_result["casting"]
        personas = set(cr.data["user_persona"].dropna().unique())
        expected = {"automated_system", "junior_accountant", "senior_accountant", "controller", "manager"}
        assert personas == expected

    def test_document_count(self, pipeline_result):
        """106,489건 전표 (document_id 기준)."""
        cr = pipeline_result["casting"]
        doc_count = cr.data["document_id"].nunique()
        assert doc_count == 106_489

    def test_fraud_count(self, pipeline_result):
        """부정 전표 2,008건."""
        cr = pipeline_result["casting"]
        fraud_count = cr.data.loc[cr.data["is_fraud"] == True, "document_id"].nunique()  # noqa: E712
        assert fraud_count == 2_008

    def test_fiscal_year_includes_2022(self, pipeline_result):
        """주 회계연도 2022 포함."""
        cr = pipeline_result["casting"]
        years = set(cr.data["fiscal_year"].dropna().unique())
        assert 2022 in years

    def test_currency_krw(self, pipeline_result):
        cr = pipeline_result["casting"]
        currencies = cr.data["currency"].dropna().unique()
        assert list(currencies) == ["KRW"]
