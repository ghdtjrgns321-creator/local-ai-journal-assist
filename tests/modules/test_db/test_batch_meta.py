"""Tests for persisted upload_batches metadata."""

from __future__ import annotations

import duckdb
import pytest

from src.db.loader import load_all, update_upload_batch_meta


class TestUploadBatchesMeta:
    def test_meta_inserted_after_load(self, db_conn, db_sample_df):
        lr = load_all(db_conn, db_sample_df, "batch_meta_01", file_name="test.xlsx")

        meta = db_conn.execute(
            "SELECT * FROM upload_batches WHERE upload_batch_id = 'batch_meta_01'"
        ).fetchdf()

        assert len(meta) == 1
        row = meta.iloc[0]
        assert row["file_name"] == "test.xlsx"
        assert row["row_count"] == lr.general_ledger_rows
        assert row["high_risk_count"] == 0

    def test_duplicate_batch_id_raises(self, db_conn, db_sample_df):
        load_all(db_conn, db_sample_df, "batch_dup_01", file_name="a.csv")

        with pytest.raises(duckdb.ConstraintException):
            load_all(db_conn, db_sample_df, "batch_dup_01", file_name="b.csv")

    def test_empty_file_name(self, db_conn, db_sample_df):
        load_all(db_conn, db_sample_df, "batch_empty_fn")

        meta = db_conn.execute(
            "SELECT file_name FROM upload_batches WHERE upload_batch_id = 'batch_empty_fn'"
        ).fetchdf()

        assert len(meta) == 1
        assert meta.iloc[0]["file_name"] == ""

    def test_phase2_meta_update_persists_contract_snapshot(self, db_conn, db_sample_df):
        load_all(db_conn, db_sample_df, "batch_phase2_meta", file_name="phase2.csv")

        update_upload_batch_meta(
            db_conn,
            "batch_phase2_meta",
            phase2_training_report_id="train_001",
            phase2_inference_contract={
                "required_models": ["unsupervised", "timeseries"],
                "family_sub_detectors": {
                    "timeseries": ["transaction_burst", "unusual_frequency"],
                },
            },
            phase2_promotion_policy={"selection_mode": "best_per_family"},
            phase2_inference_mode="training_contract",
            detector_statuses=[
                {
                    "track_name": "timeseries",
                    "run_status": "executed",
                    "reason": None,
                    "flagged_docs": 1,
                    "rules_run": 2,
                    "elapsed_sec": 0.12,
                },
            ],
        )

        meta = db_conn.execute(
            """
            SELECT phase2_training_report_id, phase2_inference_contract,
                   phase2_promotion_policy, phase2_inference_mode, detector_statuses_json
            FROM upload_batches
            WHERE upload_batch_id = 'batch_phase2_meta'
            """
        ).fetchdf()

        assert len(meta) == 1
        row = meta.iloc[0]
        assert row["phase2_training_report_id"] == "train_001"
        assert "timeseries" in row["phase2_inference_contract"]
        assert "best_per_family" in row["phase2_promotion_policy"]
        assert row["phase2_inference_mode"] == "training_contract"
        assert "timeseries" in row["detector_statuses_json"]
