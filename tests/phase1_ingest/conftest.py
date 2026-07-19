"""Shared fixtures for phase1 ingest stress/system tests.

Why:
    The phase1 dataset bundle is optional in lightweight checkouts and CI jobs.
    We keep that policy explicit instead of silently treating every missing file
    as acceptable by default.
"""

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "test" / "ingest"

# Files below are large or externally managed fixtures. When they are absent,
# the related scenario tests are skipped intentionally.
OPTIONAL_PHASE1_DATA = {
    "stress_01_k_corp.xlsx",
    "stress_02_alien_encoding.dat",
    "stress_03_type_hell.csv",
    "stress_04_mapping_breaker.csv",
    "stress_05a_fake_excel.xlsx",
    "stress_05b_empty.csv",
    "stress_06_excel_curse.csv",
    "stress_07_memo_rebellion.csv",
    "stress_08_frankenstein_date.csv",
    "stress_09_invisible_assassin.csv",
    "stress_10_ghost_pipeline.csv",
    "sys_01_csv_utf8_clean.csv",
    "sys_02_csv_semicolon.csv",
    "sys_03_csv_header_late.csv",
    "sys_04_csv_pipe_noheader.csv",
    "sys_05_csv_mixed_delimiter.csv",
    "sys_06_csv_high_null.csv",
    "sys_07_csv_corrupted_quotes.csv",
    "sys_08_csv_empty_cols_rows.csv",
    "sys_09_csv_latin1.csv",
    "sys_10_tsv_header_row5.tsv",
    "sys_11_txt_inconsistent_cols.txt",
    "sys_12_dat_sparse.dat",
    "sys_13_parquet_fastpath.parquet",
    "sys_14_wrong_sheet_first.xlsx",
    "sys_15_blank_rows_merged.xlsx",
}


def _phase1_data(filename: str) -> Path:
    path = DATA_DIR / filename
    if path.exists():
        return path
    if filename in OPTIONAL_PHASE1_DATA:
        pytest.skip(f"optional phase1 test data missing: {path}")
    pytest.fail(f"required phase1 test data missing: {path}")


@pytest.fixture
def stress_01():
    return _phase1_data("stress_01_k_corp.xlsx")


@pytest.fixture
def stress_02():
    return _phase1_data("stress_02_alien_encoding.dat")


@pytest.fixture
def stress_03():
    return _phase1_data("stress_03_type_hell.csv")


@pytest.fixture
def stress_04():
    return _phase1_data("stress_04_mapping_breaker.csv")


@pytest.fixture
def stress_05a():
    return _phase1_data("stress_05a_fake_excel.xlsx")


@pytest.fixture
def stress_05b():
    return _phase1_data("stress_05b_empty.csv")


@pytest.fixture
def stress_06():
    return _phase1_data("stress_06_excel_curse.csv")


@pytest.fixture
def stress_07():
    return _phase1_data("stress_07_memo_rebellion.csv")


@pytest.fixture
def stress_08():
    return _phase1_data("stress_08_frankenstein_date.csv")


@pytest.fixture
def stress_09():
    return _phase1_data("stress_09_invisible_assassin.csv")


@pytest.fixture
def stress_10():
    return _phase1_data("stress_10_ghost_pipeline.csv")


@pytest.fixture
def sys_01():
    return _phase1_data("sys_01_csv_utf8_clean.csv")


@pytest.fixture
def sys_02():
    return _phase1_data("sys_02_csv_semicolon.csv")


@pytest.fixture
def sys_03():
    return _phase1_data("sys_03_csv_header_late.csv")


@pytest.fixture
def sys_04():
    return _phase1_data("sys_04_csv_pipe_noheader.csv")


@pytest.fixture
def sys_05():
    return _phase1_data("sys_05_csv_mixed_delimiter.csv")


@pytest.fixture
def sys_06():
    return _phase1_data("sys_06_csv_high_null.csv")


@pytest.fixture
def sys_07():
    return _phase1_data("sys_07_csv_corrupted_quotes.csv")


@pytest.fixture
def sys_08():
    return _phase1_data("sys_08_csv_empty_cols_rows.csv")


@pytest.fixture
def sys_09():
    return _phase1_data("sys_09_csv_latin1.csv")


@pytest.fixture
def sys_10():
    return _phase1_data("sys_10_tsv_header_row5.tsv")


@pytest.fixture
def sys_11():
    return _phase1_data("sys_11_txt_inconsistent_cols.txt")


@pytest.fixture
def sys_12():
    return _phase1_data("sys_12_dat_sparse.dat")


@pytest.fixture
def sys_13():
    return _phase1_data("sys_13_parquet_fastpath.parquet")


@pytest.fixture
def sys_14():
    return _phase1_data("sys_14_wrong_sheet_first.xlsx")


@pytest.fixture
def sys_15():
    return _phase1_data("sys_15_blank_rows_merged.xlsx")
