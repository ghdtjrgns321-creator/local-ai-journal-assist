"""Tests for restoring persisted batches from DuckDB."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

import src.db.batch_reader as batch_reader
from src.db.batch_reader import _build_detector_statuses, list_batches, load_batch
from src.db.loader import load_all, update_upload_batch_meta
from src.detection.base import DetectionResult


class TestLoadBatch:
    def test_restore_row_count(self, db_conn, db_sample_df, db_detection_results):
        load_all(
            db_conn,
            db_sample_df,
            "batch_restore_01",
            db_detection_results,
            file_name="data.csv",
        )

        result = load_batch(db_conn, "batch_restore_01")

        assert len(result.data) == len(db_sample_df)
        assert result.batch_id == "batch_restore_01"
        assert result.file_name == "data.csv"
        assert result.featured_data is None

    def test_restore_risk_summary(self, db_conn, db_sample_df, db_detection_results):
        load_all(db_conn, db_sample_df, "batch_risk_01", db_detection_results)

        result = load_batch(db_conn, "batch_risk_01")

        assert "Medium" in result.risk_summary
        assert "Normal" in result.risk_summary

    def test_restore_approval_date_for_l109(self, db_conn, db_sample_df, db_detection_results):
        df = db_sample_df.copy()
        df["approval_date"] = pd.to_datetime(["2022-01-11", "2022-01-11", None])
        load_all(db_conn, df, "batch_l109_restore", db_detection_results)

        result = load_batch(db_conn, "batch_l109_restore")

        assert "approval_date" in result.data.columns
        assert result.data["approval_date"].notna().sum() == 2

    def test_restore_performance_report(self, db_conn, db_sample_df, db_detection_results):
        load_all(db_conn, db_sample_df, "batch_perf_01", db_detection_results)

        result = load_batch(db_conn, "batch_perf_01")

        assert result.performance_report is not None
        assert result.performance_report.upload_batch_id == "batch_perf_01"

    def test_restore_phase2_contract_snapshot(self, db_conn, db_sample_df, db_detection_results):
        load_all(db_conn, db_sample_df, "batch_phase2_restore", db_detection_results)
        update_upload_batch_meta(
            db_conn,
            "batch_phase2_restore",
            phase2_training_report_id="train_777",
            phase2_inference_contract={
                "required_models": ["timeseries", "unsupervised"],
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
                    "flagged_docs": 2,
                    "rules_run": 2,
                    "elapsed_sec": 0.21,
                },
                {
                    "track_name": "ml_unsupervised",
                    "run_status": "skipped",
                    "reason": "missing_promoted_model",
                    "flagged_docs": 0,
                    "rules_run": 0,
                    "elapsed_sec": 0.0,
                },
            ],
        )

        result = load_batch(db_conn, "batch_phase2_restore")

        assert result.phase2_training_report_id == "train_777"
        assert result.phase2_inference_contract["required_models"] == [
            "timeseries",
            "unsupervised",
        ]
        assert result.phase2_promotion_policy["selection_mode"] == "best_per_family"
        assert result.phase2_inference_mode == "training_contract"
        status_map = {row["track_name"]: row for row in result.detector_statuses}
        assert status_map["timeseries"]["run_status"] == "executed"
        assert status_map["timeseries"]["flagged_docs"] == 2
        assert status_map["ml_unsupervised"]["reason"] == "missing_promoted_model"

    def test_restore_phase1_case_artifact_reference(
        self, db_conn, db_sample_df, db_detection_results,
    ):
        load_all(
            db_conn,
            db_sample_df,
            "batch_phase1_case_restore",
            db_detection_results,
            phase1_case_ref={
                "phase1_case_run_id": "phase1_run_001",
                "phase1_case_path": "artifacts/phase1_cases/phase1_run_001.json",
                "phase1_case_count": 7,
                "phase1_macro_finding_count": 2,
                "top_theme_ids": ["settlement_timing", "approval_control"],
                "phase1_case_schema_version": "1.0",
            },
        )

        result = load_batch(db_conn, "batch_phase1_case_restore")

        assert result.phase1_case_run_id == "phase1_run_001"
        assert result.phase1_case_path == "artifacts/phase1_cases/phase1_run_001.json"
        assert result.phase1_case_count == 7
        assert result.phase1_macro_finding_count == 2
        assert result.phase1_top_theme_ids == ["settlement_timing", "approval_control"]
        assert result.phase1_case_schema_version == "1.0"

    def test_restore_legacy_phase1_case_reference_from_artifact(
        self, monkeypatch, tmp_path, db_conn, db_sample_df, db_detection_results,
    ):
        batch_id = "batch_phase1_legacy"
        load_all(db_conn, db_sample_df, batch_id, db_detection_results)
        artifact_dir = tmp_path / "artifacts" / "phase1_cases" / "kr01"
        artifact_dir.mkdir(parents=True)
        artifact_path = artifact_dir / f"phase1case_kr01_{batch_id}_20260503T010000Z.json"
        artifact_path.write_text(
            json.dumps({
                "schema_version": "1.0",
                "run_id": f"phase1case_kr01_{batch_id}_20260503T010000Z",
                "company_id": "kr01",
                "dataset_id": batch_id,
                "batch_id": batch_id,
                "cases": [{"case_id": "case_001"}],
                "theme_summaries": [{"theme_id": "settlement_timing"}],
                "metadata": {"macro_finding_count": 3},
            }),
            encoding="utf-8",
        )
        monkeypatch.setattr(batch_reader, "PROJECT_ROOT", tmp_path)

        result = load_batch(db_conn, batch_id)

        assert result.phase1_case_path == str(artifact_path)
        assert result.phase1_case_count == 1
        assert result.phase1_macro_finding_count == 3
        assert result.phase1_top_theme_ids == ["settlement_timing"]

    def test_not_found_raises(self, db_conn):
        with pytest.raises(ValueError, match="배치를 찾을 수 없습니다"):
            load_batch(db_conn, "nonexistent_batch")


class TestListBatches:
    def test_list_includes_loaded(self, db_conn, db_sample_df):
        load_all(db_conn, db_sample_df, "batch_list_01", file_name="test.xlsx")

        batches = list_batches(db_conn)

        assert not batches.empty
        assert "batch_list_01" in batches["upload_batch_id"].values

    def test_empty_db(self, db_conn):
        batches = list_batches(db_conn)
        assert batches.empty


class TestPseudoDetectionResults:
    def test_results_not_empty(self, db_conn, db_sample_df, db_detection_results):
        load_all(db_conn, db_sample_df, "batch_det_01", db_detection_results)

        result = load_batch(db_conn, "batch_det_01")

        assert len(result.results) > 0

    def test_rule_flags_match(self, db_conn, db_sample_df, db_detection_results):
        load_all(db_conn, db_sample_df, "batch_det_02", db_detection_results)

        result = load_batch(db_conn, "batch_det_02")

        all_rule_ids = set()
        for dr in result.results:
            for rf in dr.rule_flags:
                all_rule_ids.add(rf.rule_id)

        assert "L4-01" in all_rule_ids or "L1-04" in all_rule_ids

    def test_flagged_indices_not_empty(self, db_conn, db_sample_df, db_detection_results):
        load_all(db_conn, db_sample_df, "batch_det_03", db_detection_results)

        result = load_batch(db_conn, "batch_det_03")

        any_flagged = any(len(dr.flagged_indices) > 0 for dr in result.results)
        assert any_flagged

    def test_details_scores_populated(self, db_conn, db_sample_df, db_detection_results):
        load_all(db_conn, db_sample_df, "batch_det_04", db_detection_results)

        result = load_batch(db_conn, "batch_det_04")

        for dr in result.results:
            if not dr.details.empty:
                assert (dr.details > 0).any().any()

    def test_restored_flags_preserve_line_number_row_position(self, db_conn):
        df = pd.DataFrame({
            "document_id": ["JE-LINE", "JE-LINE", "JE-LINE"],
            "company_code": ["C001", "C001", "C001"],
            "fiscal_year": [2022, 2022, 2022],
            "fiscal_period": [1, 1, 1],
            "posting_date": pd.to_datetime(["2022-01-10"] * 3),
            "document_date": pd.to_datetime(["2022-01-10"] * 3),
            "document_type": ["SA", "SA", "SA"],
            "gl_account": ["1000", "2000", "9999"],
            "debit_amount": [100.0, 0.0, 777.0],
            "credit_amount": [0.0, 100.0, 0.0],
            "line_number": [1, 2, 3],
            "created_by": ["USR"] * 3,
            "source": ["Manual"] * 3,
            "business_process": ["R2R"] * 3,
            "anomaly_score": [0.0, 0.0, 0.9],
            "risk_level": ["Normal", "Normal", "High"],
            "flagged_rules": ["", "", "L1-03"],
            "review_rules": ["", "", ""],
        })
        details = pd.DataFrame({"L1-03": [0.0, 0.0, 0.9]}, index=df.index)
        load_all(
            db_conn,
            df,
            "batch_line_number_restore",
            [SimpleNamespace(track_name="layer_a", details=details, metadata={})],
        )

        result = load_batch(db_conn, "batch_line_number_restore")
        layer_a = next(dr for dr in result.results if dr.track_name == "layer_a")

        assert len(layer_a.flagged_indices) == 1
        flagged_index = layer_a.flagged_indices[0]
        assert result.data.iloc[flagged_index]["line_number"] == 3
        assert result.data.iloc[flagged_index]["gl_account"] == "9999"
        assert layer_a.details.loc[flagged_index, "L1-03"] == 0.9
        unflagged_indices = [
            idx
            for idx, line_number in enumerate(result.data["line_number"])
            if int(line_number) != 3
        ]
        assert (layer_a.details.loc[unflagged_indices, "L1-03"] == 0.0).all()


class TestDetectorStatuses:
    def test_restored_core_tracks_default_to_executed(self):
        statuses = _build_detector_statuses(results=[])
        status_map = {row["track_name"]: row for row in statuses}

        assert status_map["layer_a"]["run_status"] == "executed"
        assert status_map["layer_a"]["reason"] == "restored_without_flag_rows"
        assert status_map["duplicate"]["run_status"] == "executed"

    def test_optional_tracks_remain_unknown_without_snapshot(self):
        statuses = _build_detector_statuses(results=[])
        status_map = {row["track_name"]: row for row in statuses}

        assert status_map["nlp"]["run_status"] == "unknown"
        assert status_map["graph"]["run_status"] == "unknown"

    def test_existing_result_is_preserved(self):
        result = DetectionResult(
            track_name="layer_b",
            flagged_indices=[0],
            scores=pd.Series([0.8]),
            rule_flags=[],
            details=pd.DataFrame({"L4-01": [0.8]}),
            metadata={"elapsed": 0.0, "run_status": "executed"},
        )
        statuses = _build_detector_statuses(results=[result])
        status_map = {row["track_name"]: row for row in statuses}

        assert status_map["layer_b"]["run_status"] == "executed"
        assert status_map["layer_b"]["flagged_docs"] == 1

    def test_snapshot_overrides_default_unknown_statuses(self):
        statuses = _build_detector_statuses(
            results=[],
            detector_statuses_snapshot=[
                {
                    "track_name": "timeseries",
                    "run_status": "executed",
                    "reason": None,
                    "flagged_docs": 3,
                    "rules_run": 2,
                    "elapsed_sec": 0.25,
                },
            ],
        )
        status_map = {row["track_name"]: row for row in statuses}

        assert set(status_map) == {"timeseries"}
        assert status_map["timeseries"]["flagged_docs"] == 3
