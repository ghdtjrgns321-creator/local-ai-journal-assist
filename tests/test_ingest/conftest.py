"""test_ingest 공용 fixture — 테스트용 임시 파일 생성."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def valid_xlsx(tmp_path: Path) -> Path:
    """최소 데이터가 포함된 정상 .xlsx 파일."""
    filepath = tmp_path / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["journal_id", "entry_date", "debit_amount"])
    ws.append([1, "2025-01-01", 10000])
    wb.save(filepath)
    return filepath


@pytest.fixture
def valid_csv(tmp_path: Path) -> Path:
    """UTF-8 인코딩 정상 .csv 파일."""
    filepath = tmp_path / "test.csv"
    filepath.write_text(
        "journal_id,entry_date,debit_amount\n1,2025-01-01,10000\n",
        encoding="utf-8",
    )
    return filepath


@pytest.fixture
def valid_csv_cp949(tmp_path: Path) -> Path:
    """CP949 인코딩 .csv 파일 — 인코딩 경고 테스트용."""
    filepath = tmp_path / "test_cp949.csv"
    filepath.write_text(
        "전표번호,일자,차변금액\n1,2025-01-01,10000\n",
        encoding="cp949",
    )
    return filepath


@pytest.fixture
def valid_tsv(tmp_path: Path) -> Path:
    """정상 .tsv 파일."""
    filepath = tmp_path / "test.tsv"
    filepath.write_text(
        "journal_id\tentry_date\tdebit_amount\n1\t2025-01-01\t10000\n",
        encoding="utf-8",
    )
    return filepath


@pytest.fixture
def valid_parquet(tmp_path: Path) -> Path:
    """정상 .parquet 파일."""
    filepath = tmp_path / "test.parquet"
    table = pa.table({"journal_id": [1], "amount": [10000.0]})
    pq.write_table(table, filepath)
    return filepath


@pytest.fixture
def xlsx_multi_sheet(tmp_path: Path) -> Path:
    """3개 시트(데이터2 + 빈1) .xlsx 파일."""
    filepath = tmp_path / "multi.xlsx"
    wb = openpyxl.Workbook()

    # Sheet1 (활성 시트) — 데이터 있음
    ws1 = wb.active
    ws1.title = "매출"
    ws1.append(["id", "date", "amount"])
    ws1.append([1, "2025-01-01", 5000])

    # Sheet2 — 데이터 있음
    ws2 = wb.create_sheet("매입")
    ws2.append(["id", "date", "amount"])
    ws2.append([2, "2025-02-01", 3000])

    # Sheet3 — 빈 시트
    wb.create_sheet("빈시트")

    wb.save(filepath)
    return filepath


@pytest.fixture
def xlsx_with_merged_cells(tmp_path: Path) -> Path:
    """병합셀이 포함된 .xlsx 파일."""
    filepath = tmp_path / "merged.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active

    # 행1: 병합 헤더 (A1:B1 병합 = "회사정보")
    ws["A1"] = "회사정보"
    ws.merge_cells("A1:B1")
    ws["C1"] = "금액"

    # 행2: 실제 데이터
    ws["A2"] = "코드"
    ws["B2"] = "이름"
    ws["C2"] = 10000

    # 행3: 세로 병합 테스트 (A3:A4 병합 = "C001")
    ws["A3"] = "C001"
    ws.merge_cells("A3:A4")
    ws["B3"] = "본사"
    ws["C3"] = 20000
    ws["B4"] = "지사"
    ws["C4"] = 30000

    wb.save(filepath)
    return filepath


@pytest.fixture
def csv_with_bom(tmp_path: Path) -> Path:
    """BOM(UTF-8-SIG) 포함 .csv 파일."""
    filepath = tmp_path / "bom.csv"
    filepath.write_text(
        "id,name,amount\n1,테스트,10000\n",
        encoding="utf-8-sig",
    )
    return filepath


@pytest.fixture
def corrupted_xlsx(tmp_path: Path) -> Path:
    """확장자는 .xlsx이지만 내용이 랜덤 바이트인 손상 파일."""
    filepath = tmp_path / "corrupted.xlsx"
    filepath.write_bytes(b"\x00\x01\x02\x03NOTANEXCELFILE")
    return filepath


@pytest.fixture
def empty_file(tmp_path: Path) -> Path:
    """0바이트 빈 파일."""
    filepath = tmp_path / "empty.xlsx"
    filepath.write_bytes(b"")
    return filepath


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    """.pdf 확장자 파일 (내용 무관)."""
    filepath = tmp_path / "report.pdf"
    filepath.write_bytes(b"%PDF-1.4 dummy")
    return filepath


@pytest.fixture
def hwp_file(tmp_path: Path) -> Path:
    """.hwp 확장자 파일 (내용 무관)."""
    filepath = tmp_path / "report.hwp"
    filepath.write_bytes(b"\xd0\xcf\x11\xe0 dummy")
    return filepath
