"""Integration checks for the current DataSynth ingest pipeline."""

from __future__ import annotations

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
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_persona(value: str) -> str:
    return value.strip().lower()


@pytest.fixture(scope="module")
def schema() -> dict:
    return _load_schema()


@pytest.fixture(scope="module")
def pipeline_result():
    if not DATASYNTH_CSV.exists():
        pytest.skip("DataSynth CSV not found")

    vr = validate_file(DATASYNTH_CSV)
    assert vr.is_valid, f"validation failed: {vr.errors}"

    rr = read_file(DATASYNTH_CSV)
    raw_df = rr.raw_data[rr.active_sheet]

    hr = detect_header_row(raw_df)
    columns, data_df = prepare_dataframe(
        raw_df, hr.header_row if hr.header_row is not None else 0
    )

    mr = auto_map_columns(columns, matched_keywords=hr.matched_keywords, data_df=data_df)
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


class TestDataSynthValidation:
    def test_file_valid(self, pipeline_result):
        vr = pipeline_result["validation"]
        assert vr.is_valid
        assert vr.file_category == "text"


class TestDataSynthRead:
    def test_source_format(self, pipeline_result):
        rr = pipeline_result["read_result"]
        assert rr.source_format == "csv"

    def test_encoding(self, pipeline_result):
        rr = pipeline_result["read_result"]
        assert rr.encoding is not None

    def test_row_count(self, pipeline_result):
        data_df = pipeline_result["data_df"]
        assert data_df.shape[0] > 100_000, f"row count too small: {data_df.shape[0]}"


class TestDataSynthColumnMapping:
    def test_fast_path_activated(self, pipeline_result):
        mr = pipeline_result["mapping"]
        assert mr.needs_review is False

    def test_no_missing_required(self, pipeline_result):
        mr = pipeline_result["mapping"]
        assert mr.missing_required == []

    def test_non_label_columns_mapped(self, pipeline_result, schema):
        mr = pipeline_result["mapping"]
        non_label = {
            col["name"]
            for col in schema["columns"]
            if not col.get("is_label", col.get("type") == "bool")
        }
        mapped_standards = set(mr.mapping.values())
        missing = non_label - mapped_standards
        assert missing <= {"lettrage", "lettrage_date"}, f"unexpected unmapped columns: {missing}"

    def test_identity_mapping(self, pipeline_result):
        mr = pipeline_result["mapping"]
        for src, std in mr.mapping.items():
            assert src == std, f"non-identity mapping: {src} -> {std}"

    def test_column_count_matches_current_dataset(self, pipeline_result):
        columns = pipeline_result["columns"]
        assert len(columns) == 44


class TestDataSynthCasting:
    def test_casting_success(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert cr.success, f"casting failed: {cr.errors}"

    def test_no_casting_errors(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert cr.errors == []

    def test_debit_credit_float64(self, pipeline_result):
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
        cr = pipeline_result["casting"]
        assert cr.data["gl_account"].dtype == "object"

    def test_final_shape(self, pipeline_result):
        cr = pipeline_result["casting"]
        assert cr.data.shape[0] > 100_000, f"row count too small: {cr.data.shape[0]}"
        assert cr.data.shape[1] == 44


class TestDataSynthDataQuality:
    def test_company_codes(self, pipeline_result):
        cr = pipeline_result["casting"]
        codes = set(cr.data["company_code"].dropna().unique())
        assert codes == {"C001", "C002", "C003"}

    def test_document_types(self, pipeline_result):
        cr = pipeline_result["casting"]
        types = set(cr.data["document_type"].dropna().unique())
        core_types = {"SA", "KR", "KZ", "DR", "DZ", "WE", "AA", "HR", "IC"}
        assert core_types.issubset(types), f"missing core types: {core_types - types}"

    def test_business_processes(self, pipeline_result):
        cr = pipeline_result["casting"]
        processes = set(cr.data["business_process"].dropna().unique())
        expected = {"P2P", "O2C", "R2R", "H2R", "TRE", "A2R"}
        assert processes == expected

    def test_user_personas(self, pipeline_result):
        cr = pipeline_result["casting"]
        personas = {
            _normalize_persona(value)
            for value in cr.data["user_persona"].dropna().astype(str).unique()
        }
        expected = {
            "automated_system",
            "junior_accountant",
            "senior_accountant",
            "controller",
            "manager",
        }
        assert expected <= personas

    def test_document_count(self, pipeline_result):
        cr = pipeline_result["casting"]
        doc_count = cr.data["document_id"].nunique()
        assert doc_count > 10_000, f"document count too small: {doc_count}"

    def test_fraud_count(self, pipeline_result):
        cr = pipeline_result["casting"]
        total_docs = cr.data["document_id"].nunique()
        fraud_count = cr.data.loc[
            cr.data["is_fraud"] == True,  # noqa: E712
            "document_id",
        ].nunique()
        assert fraud_count > 0, "no fraud documents found"
        fraud_ratio = fraud_count / total_docs
        assert 0.01 <= fraud_ratio <= 0.05, f"fraud ratio out of range: {fraud_ratio:.2%}"

    def test_fiscal_year_includes_2022(self, pipeline_result):
        cr = pipeline_result["casting"]
        years = set(cr.data["fiscal_year"].dropna().unique())
        assert 2022 in years

    def test_currency_krw(self, pipeline_result):
        cr = pipeline_result["casting"]
        currencies = cr.data["currency"].dropna().unique()
        assert list(currencies) == ["KRW"]
