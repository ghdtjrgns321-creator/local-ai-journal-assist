"""journal_entries.csv를 fiscal_year 기준으로 3개년치로 분할.

Why: DataSynth의 Rust output_writer는 단일 CSV만 생성.
     프로젝트 분석·학습에서 연도별 분할된 파일이 필요할 때 사용.

출력:
    - journal_entries_2022.csv
    - journal_entries_2023.csv
    - journal_entries_2024.csv

원본은 유지 (journal_entries.csv).

실행: uv run python -m tests.phase2_data_analysis.split_by_year
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb

_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "data" / "journal" / "primary" / "datasynth"
)
_SRC = _DATA_DIR / "journal_entries.csv"


def split_by_year() -> None:
    start = time.perf_counter()
    print("=" * 60)
    print("연도별 CSV 분할")
    print("=" * 60)
    print(f"\n  Source: {_SRC}")

    con = duckdb.connect()
    con.execute(f"""
        CREATE TABLE je AS
        SELECT * FROM read_csv_auto('{_SRC.as_posix()}', all_varchar=true)
    """)
    total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    print(f"  Total rows: {total:,}")

    years = [r[0] for r in con.execute(
        "SELECT DISTINCT fiscal_year FROM je WHERE fiscal_year IS NOT NULL ORDER BY 1"
    ).fetchall()]
    print(f"  Years found: {years}")

    for year in years:
        dst = _DATA_DIR / f"journal_entries_{year}.csv"
        con.execute(f"""
            COPY (SELECT * FROM je WHERE fiscal_year = '{year}')
            TO '{dst.as_posix()}' WITH (HEADER, DELIMITER ',')
        """)
        cnt = con.execute(
            f"SELECT COUNT(*) FROM je WHERE fiscal_year = '{year}'"
        ).fetchone()[0]
        size_mb = dst.stat().st_size / (1024 * 1024)
        print(f"  -> journal_entries_{year}.csv: {cnt:,} rows, {size_mb:.1f} MB")

    con.close()
    elapsed = time.perf_counter() - start
    print(f"\n  Done in {elapsed:.1f}s")


if __name__ == "__main__":
    split_by_year()
