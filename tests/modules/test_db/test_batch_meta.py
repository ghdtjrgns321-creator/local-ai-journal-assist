"""upload_batches 메타 적재 단위 테스트.

테스트 그룹:
  - load_all → upload_batches에 메타 삽입 + 필드값 검증
  - 동일 batch_id 중복 삽입 시 PK 위반
  - file_name 빈 문자열 시 정상 동작
"""

import duckdb
import pytest

from src.db.loader import load_all


class TestUploadBatchesMeta:
    """upload_batches 테이블 메타 적재."""

    def test_meta_inserted_after_load(self, db_conn, db_sample_df):
        """load_all() 후 upload_batches에 1행 삽입, 필드값 정확."""
        lr = load_all(db_conn, db_sample_df, "batch_meta_01", file_name="test.xlsx")

        meta = db_conn.execute(
            "SELECT * FROM upload_batches WHERE upload_batch_id = 'batch_meta_01'"
        ).fetchdf()

        assert len(meta) == 1
        row = meta.iloc[0]
        assert row["file_name"] == "test.xlsx"
        assert row["row_count"] == lr.general_ledger_rows
        # Why: db_sample_df에 risk_level="Medium" 2행, "Normal" 1행 → High 0건
        assert row["high_risk_count"] == 0

    def test_duplicate_batch_id_raises(self, db_conn, db_sample_df):
        """동일 batch_id 재삽입 시 PK 위반."""
        load_all(db_conn, db_sample_df, "batch_dup_01", file_name="a.csv")

        with pytest.raises(duckdb.ConstraintException):
            load_all(db_conn, db_sample_df, "batch_dup_01", file_name="b.csv")

    def test_empty_file_name(self, db_conn, db_sample_df):
        """file_name 빈 문자열 — 정상 동작."""
        load_all(db_conn, db_sample_df, "batch_empty_fn")

        meta = db_conn.execute(
            "SELECT file_name FROM upload_batches WHERE upload_batch_id = 'batch_empty_fn'"
        ).fetchdf()

        assert len(meta) == 1
        assert meta.iloc[0]["file_name"] == ""
