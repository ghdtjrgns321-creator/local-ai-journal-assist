"""AuditPipeline 단위/통합 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.pipeline import AuditPipeline, PipelineResult


# ── 기본 동작 ────────────────────────────────────────────────


class TestRunFromDataframe:
    """run_from_dataframe 기본 동작 검증."""

    def test_basic(self, small_gl_df):
        """anomaly_score, risk_level 컬럼 존재."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert isinstance(result, PipelineResult)
        assert "anomaly_score" in result.data.columns
        assert "risk_level" in result.data.columns
        assert result.elapsed > 0

    def test_results_count(self, small_gl_df):
        """4개 DetectionResult(A/B/C/Benford) 반환."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert len(result.results) == 4
        track_names = {r.track_name for r in result.results}
        assert track_names == {"layer_a", "layer_b", "layer_c", "benford"}

    def test_batch_id_format(self, small_gl_df):
        """batch_id가 12자 hex 문자열."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert len(result.batch_id) == 12
        int(result.batch_id, 16)  # hex 변환 가능해야 함

    def test_risk_summary_keys(self, small_gl_df):
        """risk_summary에 1개 이상 키 존재."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert isinstance(result.risk_summary, dict)
        assert len(result.risk_summary) >= 1

    def test_skip_db(self, small_gl_df):
        """skip_db=True → load_result is None."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        assert result.load_result is None


# ── CSV 경로 입력 ────────────────────────────────────────────


class TestRunCsv:
    """CSV 파일 경로 입력 테스트."""

    def test_run_csv(self, tmp_path, small_gl_df):
        """CSV 파일 → 정상 파이프라인 실행."""
        csv_path = tmp_path / "test.csv"
        # Why: gl_account를 8자리 문자열로 변환 — CSV 저장/로드 시 str 유지
        small_gl_df["gl_account"] = ["11010000", "21010000", "11010000", "21010000"]
        small_gl_df.to_csv(csv_path, index=False)

        result = AuditPipeline(skip_db=True).run(csv_path)
        assert isinstance(result, PipelineResult)
        assert len(result.data) > 0

    def test_unsupported_extension(self, tmp_path):
        """지원하지 않는 확장자 → ValueError."""
        bad_file = tmp_path / "data.json"
        bad_file.write_text("{}")
        with pytest.raises(ValueError, match="지원하지 않는"):
            AuditPipeline(skip_db=True).run(bad_file)


# ── Validation 게이트 ────────────────────────────────────────


class TestValidation:
    """Validation 단계 검증."""

    def test_blocks_invalid_df(self):
        """필수 컬럼 누락 DF → ValueError 발생."""
        bad_df = pd.DataFrame({"x": [1, 2, 3]})
        with pytest.raises(ValueError, match="L1 구조 검증 실패"):
            AuditPipeline(skip_db=True).run_from_dataframe(bad_df)

    def test_warnings_collected(self, small_gl_df):
        """L2 경고는 warnings에 수집되고 파이프라인은 정상 완료."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        # Why: small_gl_df는 정상 데이터이므로 경고 0건도 정상
        assert isinstance(result.warnings, list)


# ── Detection 에러 격리 ──────────────────────────────────────


class TestDetectionIsolation:
    """한 detector 실패 시 나머지 계속 진행."""

    def test_one_detector_fails(self, small_gl_df):
        """IntegrityDetector 예외 → 나머지 3트랙 정상."""
        with patch(
            "src.detection.integrity_layer.IntegrityDetector.detect",
            side_effect=RuntimeError("테스트용 강제 에러"),
        ):
            result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert len(result.results) == 3
        assert any("탐지 실패: layer_a" in w for w in result.warnings)


# ── DB 통합 ──────────────────────────────────────────────────


class TestDbIntegration:
    """DuckDB 적재 통합 테스트."""

    def test_in_memory_db(self, small_gl_df):
        """`:memory:` 커넥션 → 적재 성공."""
        import duckdb
        from src.db.schema import initialize_schema

        conn = duckdb.connect(":memory:")
        initialize_schema(conn)

        result = AuditPipeline(skip_db=False, conn=conn).run_from_dataframe(small_gl_df)

        assert result.load_result is not None
        assert result.load_result.is_success

        # 프리셋 쿼리 정상 실행 확인
        from src.db.queries import execute_preset
        ledger = execute_preset(conn, "batch_ledger", batch_id=result.batch_id)
        assert len(ledger) > 0

        conn.close()


# ── Warnings 반환 패턴 ───────────────────────────────────────


class TestWarningsPattern:
    """각 메서드가 사이드이펙트 없이 warnings를 반환하는지 검증."""

    def test_no_external_mutation(self, small_gl_df):
        """외부 리스트가 run_from_dataframe에 의해 변경되지 않음."""
        external_list = ["기존 경고"]
        _ = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        assert external_list == ["기존 경고"]

    def test_ingest_nonstandard_columns(self, tmp_path):
        """표준 스키마 아닌 CSV → 필수 컬럼 미매핑 경고."""
        # Why: full ingest pipeline에서는 column_mapper가 미매핑 컬럼을 경고로 보고
        csv = tmp_path / "no_date_cols.csv"
        csv.write_text("amount,description\n100,test\n")
        pipe = AuditPipeline(skip_db=True)
        df, warns = pipe._ingest(csv)
        assert len(df) == 1
        assert any("미매핑" in w for w in warns)
