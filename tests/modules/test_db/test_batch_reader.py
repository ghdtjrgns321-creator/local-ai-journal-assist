"""batch_reader 단위 테스트.

테스트 그룹:
  - load_batch: 파이프라인 적재 후 복원 → 행수/risk_summary 일치
  - list_batches: 적재한 배치가 목록에 포함
  - load_batch 존재하지 않는 batch_id → ValueError
  - results 리스트: anomaly_flags → Pseudo DetectionResult 역산
"""

import pandas as pd
import pytest

from src.db.batch_reader import _build_detector_statuses, list_batches, load_batch
from src.detection.base import DetectionResult
from src.db.loader import load_all


class TestLoadBatch:
    """DB에서 배치 복원."""

    def test_restore_row_count(self, db_conn, db_sample_df, db_detection_results):
        """적재 → 복원 → 행 수 일치."""
        load_all(db_conn, db_sample_df, "batch_restore_01",
                 db_detection_results, file_name="data.csv")

        result = load_batch(db_conn, "batch_restore_01")

        assert len(result.data) == len(db_sample_df)
        assert result.batch_id == "batch_restore_01"
        assert result.file_name == "data.csv"
        assert result.featured_data is None

    def test_restore_risk_summary(self, db_conn, db_sample_df, db_detection_results):
        """risk_summary 키가 원본 데이터와 일치."""
        load_all(db_conn, db_sample_df, "batch_risk_01", db_detection_results)

        result = load_batch(db_conn, "batch_risk_01")

        # Why: db_sample_df에 "Medium" 2행, "Normal" 1행
        assert "Medium" in result.risk_summary
        assert "Normal" in result.risk_summary

    def test_restore_performance_report(self, db_conn, db_sample_df, db_detection_results):
        """복원 배치에 performance_report가 연결된다."""
        load_all(db_conn, db_sample_df, "batch_perf_01", db_detection_results)

        result = load_batch(db_conn, "batch_perf_01")

        assert result.performance_report is not None
        assert result.performance_report.upload_batch_id == "batch_perf_01"

    def test_not_found_raises(self, db_conn):
        """존재하지 않는 batch_id → ValueError."""
        with pytest.raises(ValueError, match="배치를 찾을 수 없습니다"):
            load_batch(db_conn, "nonexistent_batch")


class TestListBatches:
    """배치 목록 조회."""

    def test_list_includes_loaded(self, db_conn, db_sample_df):
        """적재 후 list_batches에 배치 포함."""
        load_all(db_conn, db_sample_df, "batch_list_01", file_name="test.xlsx")

        batches = list_batches(db_conn)

        assert not batches.empty
        assert "batch_list_01" in batches["upload_batch_id"].values

    def test_empty_db(self, db_conn):
        """빈 DB → 빈 DataFrame."""
        batches = list_batches(db_conn)
        assert batches.empty


class TestPseudoDetectionResults:
    """anomaly_flags → DetectionResult 역산."""

    def test_results_not_empty(self, db_conn, db_sample_df, db_detection_results):
        """적재 후 복원 시 results 리스트가 비어있지 않음."""
        load_all(db_conn, db_sample_df, "batch_det_01", db_detection_results)

        result = load_batch(db_conn, "batch_det_01")

        assert len(result.results) > 0

    def test_rule_flags_match(self, db_conn, db_sample_df, db_detection_results):
        """역산된 RuleFlag의 rule_id가 원본 anomaly_flags와 일치."""
        load_all(db_conn, db_sample_df, "batch_det_02", db_detection_results)

        result = load_batch(db_conn, "batch_det_02")

        # Why: db_detection_results에 layer_b → L4-01, L1-04 룰
        all_rule_ids = set()
        for dr in result.results:
            for rf in dr.rule_flags:
                all_rule_ids.add(rf.rule_id)

        assert "L4-01" in all_rule_ids or "L1-04" in all_rule_ids

    def test_flagged_indices_not_empty(self, db_conn, db_sample_df, db_detection_results):
        """역산된 DetectionResult의 flagged_indices가 비어있지 않음."""
        load_all(db_conn, db_sample_df, "batch_det_03", db_detection_results)

        result = load_batch(db_conn, "batch_det_03")

        any_flagged = any(len(dr.flagged_indices) > 0 for dr in result.results)
        assert any_flagged, "DB 복원 후 flagged_indices가 모두 비어 있음"

    def test_details_scores_populated(self, db_conn, db_sample_df, db_detection_results):
        """역산된 details DataFrame에 실제 점수가 채워져 있음."""
        load_all(db_conn, db_sample_df, "batch_det_04", db_detection_results)

        result = load_batch(db_conn, "batch_det_04")

        for dr in result.results:
            if not dr.details.empty:
                # Why: 최소 1개 셀은 0보다 커야 함
                assert (dr.details > 0).any().any(), (
                    f"{dr.track_name} details에 0보다 큰 점수가 없음"
                )


class TestDetectorStatuses:
    """DB 복원용 detector_statuses 생성."""

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
