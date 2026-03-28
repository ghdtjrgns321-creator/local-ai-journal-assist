"""phase1_ingest 스트레스/체계적 테스트 공통 fixture."""

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "test" / "ingest"


# ── 스트레스 테스트 파일 ──────────────────────────────────────
@pytest.fixture
def stress_01():
    return DATA_DIR / "stress_01_k_corp.xlsx"


@pytest.fixture
def stress_02():
    return DATA_DIR / "stress_02_alien_encoding.dat"


@pytest.fixture
def stress_03():
    return DATA_DIR / "stress_03_type_hell.csv"


@pytest.fixture
def stress_04():
    return DATA_DIR / "stress_04_mapping_breaker.csv"


@pytest.fixture
def stress_05a():
    return DATA_DIR / "stress_05a_fake_excel.xlsx"


@pytest.fixture
def stress_05b():
    return DATA_DIR / "stress_05b_empty.csv"


@pytest.fixture
def stress_06():
    return DATA_DIR / "stress_06_excel_curse.csv"


@pytest.fixture
def stress_07():
    return DATA_DIR / "stress_07_memo_rebellion.csv"


@pytest.fixture
def stress_08():
    return DATA_DIR / "stress_08_frankenstein_date.csv"


@pytest.fixture
def stress_09():
    return DATA_DIR / "stress_09_invisible_assassin.csv"


@pytest.fixture
def stress_10():
    return DATA_DIR / "stress_10_ghost_pipeline.csv"


# ── 체계적 테스트 파일 ──────────────────────────────────────
@pytest.fixture
def sys_01():
    return DATA_DIR / "sys_01_csv_utf8_clean.csv"


@pytest.fixture
def sys_02():
    return DATA_DIR / "sys_02_csv_semicolon.csv"


@pytest.fixture
def sys_03():
    return DATA_DIR / "sys_03_csv_header_late.csv"


@pytest.fixture
def sys_04():
    return DATA_DIR / "sys_04_csv_pipe_noheader.csv"


@pytest.fixture
def sys_05():
    return DATA_DIR / "sys_05_csv_mixed_delimiter.csv"


@pytest.fixture
def sys_06():
    return DATA_DIR / "sys_06_csv_high_null.csv"


@pytest.fixture
def sys_07():
    return DATA_DIR / "sys_07_csv_corrupted_quotes.csv"


@pytest.fixture
def sys_08():
    return DATA_DIR / "sys_08_csv_empty_cols_rows.csv"


@pytest.fixture
def sys_09():
    return DATA_DIR / "sys_09_csv_latin1.csv"


@pytest.fixture
def sys_10():
    return DATA_DIR / "sys_10_tsv_header_row5.tsv"


@pytest.fixture
def sys_11():
    return DATA_DIR / "sys_11_txt_inconsistent_cols.txt"


@pytest.fixture
def sys_12():
    return DATA_DIR / "sys_12_dat_sparse.dat"


@pytest.fixture
def sys_13():
    return DATA_DIR / "sys_13_parquet_typed.parquet"


@pytest.fixture
def sys_14():
    return DATA_DIR / "sys_14_xlsx_wrong_sheet.xlsx"


@pytest.fixture
def sys_15():
    return DATA_DIR / "sys_15_xlsx_blank_rows_merged.xlsx"
