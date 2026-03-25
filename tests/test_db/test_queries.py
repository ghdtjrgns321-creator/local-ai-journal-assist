"""queries.py 단위 테스트.

테스트 항목:
  1. batch_ledger — 적재 건수 == 조회 건수
  2. batch_flags — 룰 플래그 전수 조회, score 정합
  3. benford_summary — 배치당 1행, 통계 필드 정합
  4. benford_digits — 9행, deviation = observed - expected
  5. rule_violation_stats — VIEW 집계 정합
  6. document_rule_detail — document_id 필터링 정확성
  7. 빈 테이블 → 빈 DataFrame (에러 아님)
  8. 존재하지 않는 query_name → QueryNotFoundError
  9. 2개 배치 → batch_id 필터링 교차 없음
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.db.queries import (
    PRESET_QUERIES,
    QueryNotFoundError,
    execute_preset,
)


# ── 테스트 데이터 픽스처 ───────────────────────────────────────


@pytest.fixture()
def loaded_batch(db_conn):
    """general_ledger + anomaly_flags + benford 테이블에 테스트 데이터를 적재한다."""
    batch_id = "test-batch-001"

    # general_ledger 3행
    # Why: general_ledger는 44컬럼이므로 INSERT 시 컬럼 명시 필수
    gl_cols = [
        "document_id", "company_code", "fiscal_year",
        "posting_date", "document_date", "document_type",
        "line_number", "gl_account", "debit_amount", "credit_amount",
        "line_text", "header_text", "created_by", "source",
        "anomaly_score", "risk_level", "flagged_rules",
        "upload_batch_id",
    ]
    gl_data = pd.DataFrame({
        "document_id": ["JE-001", "JE-002", "JE-003"],
        "company_code": ["1000", "1000", "1000"],
        "fiscal_year": [2025, 2025, 2025],
        "posting_date": pd.to_datetime(["2025-01-15", "2025-02-20", "2025-03-10"]),
        "document_date": pd.to_datetime(["2025-01-15", "2025-02-20", "2025-03-10"]),
        "document_type": ["SA", "SA", "SA"],
        "line_number": [1, 1, 1],
        "gl_account": ["110000", "210000", "310000"],
        "debit_amount": [1000.0, 0.0, 5000.0],
        "credit_amount": [0.0, 2000.0, 0.0],
        "line_text": ["매출", "매입", "급여"],
        "header_text": ["1월 매출", "2월 매입", "3월 급여"],
        "created_by": ["USER01", "USER01", "USER02"],
        "source": ["SAP", "SAP", "SAP"],
        "anomaly_score": [0.8, 0.3, 0.6],
        "risk_level": ["High", "Low", "Medium"],
        "flagged_rules": ["A01,B03", "", "B05"],
        "upload_batch_id": [batch_id] * 3,
    })
    col_list = ", ".join(gl_cols)
    db_conn.execute(f"INSERT INTO general_ledger ({col_list}) SELECT * FROM gl_data")

    # anomaly_flags 4행 (created_at은 DEFAULT이므로 제외)
    af_cols = ["upload_batch_id", "document_id", "line_number",
               "track_name", "rule_code", "score"]
    flags_data = pd.DataFrame({
        "upload_batch_id": [batch_id] * 4,
        "document_id": ["JE-001", "JE-001", "JE-003", "JE-003"],
        "line_number": [1, 1, 1, 1],
        "track_name": ["layer_a", "layer_b", "layer_b", "layer_b"],
        "rule_code": ["A01", "B03", "B05", "B03"],
        "score": [0.6, 0.8, 0.4, 0.6],
    })
    af_col_list = ", ".join(af_cols)
    db_conn.execute(f"INSERT INTO anomaly_flags ({af_col_list}) SELECT * FROM flags_data")

    # benford_summary 1행
    bs_cols = ["upload_batch_id", "sample_size", "mad", "mad_conformity",
               "chi2_statistic", "chi2_p_value", "ks_statistic", "ks_p_value",
               "is_conforming", "confidence"]
    summary_data = pd.DataFrame({
        "upload_batch_id": [batch_id],
        "sample_size": [100],
        "mad": [0.015],
        "mad_conformity": ["close"],
        "chi2_statistic": [5.2],
        "chi2_p_value": [0.73],
        "ks_statistic": [0.08],
        "ks_p_value": [0.85],
        "is_conforming": [True],
        "confidence": ["high"],
    })
    bs_col_list = ", ".join(bs_cols)
    db_conn.execute(f"INSERT INTO benford_summary ({bs_col_list}) SELECT * FROM summary_data")

    # benford_digits 9행
    bd_cols = ["upload_batch_id", "digit", "observed_freq", "expected_freq", "deviation"]
    digits_rows = []
    for d in range(1, 10):
        obs = round(0.301 / d, 4)
        exp = round(0.301 / d, 4)
        digits_rows.append({
            "upload_batch_id": batch_id,
            "digit": d,
            "observed_freq": obs,
            "expected_freq": exp,
            "deviation": 0.0,
        })
    digits_data = pd.DataFrame(digits_rows)
    bd_col_list = ", ".join(bd_cols)
    db_conn.execute(f"INSERT INTO benford_digits ({bd_col_list}) SELECT * FROM digits_data")

    return batch_id


# ── 쿼리 실행 테스트 ──────────────────────────────────────────


class TestBatchLedger:
    """batch_ledger 쿼리 검증."""

    def test_row_count_matches(self, db_conn, loaded_batch):
        """적재 건수와 조회 건수가 일치한다."""
        df = execute_preset(db_conn, "batch_ledger", batch_id=loaded_batch)
        assert len(df) == 3

    def test_columns_present(self, db_conn, loaded_batch):
        """필수 컬럼이 존재한다."""
        df = execute_preset(db_conn, "batch_ledger", batch_id=loaded_batch)
        for col in ["document_id", "anomaly_score", "risk_level", "flagged_rules"]:
            assert col in df.columns

    def test_ordered_by_score_desc(self, db_conn, loaded_batch):
        """anomaly_score 내림차순 정렬."""
        df = execute_preset(db_conn, "batch_ledger", batch_id=loaded_batch)
        scores = df["anomaly_score"].tolist()
        assert scores == sorted(scores, reverse=True)


class TestBatchFlags:
    """batch_flags 쿼리 검증."""

    def test_all_flags_returned(self, db_conn, loaded_batch):
        """4개 플래그 전수 조회."""
        df = execute_preset(db_conn, "batch_flags", batch_id=loaded_batch)
        assert len(df) == 4

    def test_score_values(self, db_conn, loaded_batch):
        """score 값 정합성."""
        df = execute_preset(db_conn, "batch_flags", batch_id=loaded_batch)
        assert set(df["score"].tolist()) == {0.4, 0.6, 0.8}


class TestBenfordSummary:
    """benford_summary 쿼리 검증."""

    def test_single_row(self, db_conn, loaded_batch):
        """배치당 1행."""
        df = execute_preset(db_conn, "benford_summary", batch_id=loaded_batch)
        assert len(df) == 1

    def test_fields_match(self, db_conn, loaded_batch):
        """통계 필드 정합."""
        df = execute_preset(db_conn, "benford_summary", batch_id=loaded_batch)
        row = df.iloc[0]
        assert row["sample_size"] == 100
        assert row["mad_conformity"] == "close"
        assert row["is_conforming"] == True  # noqa: E712 — np.True_ is not True
        assert row["confidence"] == "high"


class TestBenfordDigits:
    """benford_digits 쿼리 검증."""

    def test_nine_rows(self, db_conn, loaded_batch):
        """9행 반환."""
        df = execute_preset(db_conn, "benford_digits", batch_id=loaded_batch)
        assert len(df) == 9

    def test_deviation_calculation(self, db_conn, loaded_batch):
        """deviation = observed - expected."""
        df = execute_preset(db_conn, "benford_digits", batch_id=loaded_batch)
        for _, row in df.iterrows():
            expected_dev = row["observed_freq"] - row["expected_freq"]
            assert abs(row["deviation"] - expected_dev) < 1e-10


class TestRuleViolationStats:
    """rule_violation_stats (VIEW) 쿼리 검증."""

    def test_aggregation(self, db_conn, loaded_batch):
        """VIEW 집계가 anomaly_flags 원본과 정합한다."""
        df = execute_preset(db_conn, "rule_violation_stats", batch_id=loaded_batch)
        # B03 룰: 2건, avg_score = (0.8 + 0.6) / 2 = 0.7
        b03 = df[df["rule_code"] == "B03"].iloc[0]
        assert b03["flagged_count"] == 2
        assert abs(b03["avg_score"] - 0.7) < 1e-10


class TestDocumentRuleDetail:
    """document_rule_detail 드릴다운 쿼리 검증."""

    def test_filter_by_document_id(self, db_conn, loaded_batch):
        """특정 document_id 필터링."""
        df = execute_preset(
            db_conn, "document_rule_detail",
            params=(loaded_batch, "JE-001"),
        )
        assert len(df) == 2
        assert set(df["rule_code"].tolist()) == {"A01", "B03"}

    def test_nonexistent_document(self, db_conn, loaded_batch):
        """존재하지 않는 document_id → 빈 DataFrame."""
        df = execute_preset(
            db_conn, "document_rule_detail",
            params=(loaded_batch, "NONEXISTENT"),
        )
        assert len(df) == 0


# ── 에러·경계 케이스 ──────────────────────────────────────────


class TestErrorCases:
    """에러 및 경계 케이스 검증."""

    def test_empty_table_returns_empty_df(self, db_conn):
        """빈 테이블 → 빈 DataFrame (에러 아님)."""
        df = execute_preset(db_conn, "batch_ledger", batch_id="no-such-batch")
        assert len(df) == 0
        assert isinstance(df, pd.DataFrame)

    def test_unknown_query_raises(self, db_conn):
        """존재하지 않는 query_name → QueryNotFoundError."""
        with pytest.raises(QueryNotFoundError):
            execute_preset(db_conn, "nonexistent_query", batch_id="x")

    def test_missing_both_params_raises(self, db_conn):
        """params와 batch_id 모두 None → ValueError."""
        with pytest.raises(ValueError):
            execute_preset(db_conn, "batch_ledger")

    def test_param_count_mismatch_raises(self, db_conn):
        """파라미터 개수 불일치 → ValueError (document_rule_detail에 batch_id만 전달)."""
        with pytest.raises(ValueError, match="2개 파라미터가 필요"):
            execute_preset(db_conn, "document_rule_detail", batch_id="x")


class TestBatchIsolation:
    """배치 간 데이터 격리 검증."""

    def test_two_batches_no_cross(self, db_conn, loaded_batch):
        """2개 배치 적재 후 batch_id 필터링이 정확하다."""
        # 두 번째 배치 적재
        batch2 = "test-batch-002"
        gl2_cols = [
            "document_id", "company_code", "fiscal_year",
            "posting_date", "document_date", "document_type",
            "line_number", "gl_account", "debit_amount", "credit_amount",
            "line_text", "header_text", "created_by", "source",
            "anomaly_score", "risk_level", "flagged_rules",
            "upload_batch_id",
        ]
        gl2 = pd.DataFrame({
            "document_id": ["JE-999"],
            "company_code": ["2000"],
            "fiscal_year": [2025],
            "posting_date": pd.to_datetime(["2025-06-01"]),
            "document_date": pd.to_datetime(["2025-06-01"]),
            "document_type": ["SA"],
            "line_number": [1],
            "gl_account": ["999000"],
            "debit_amount": [9999.0],
            "credit_amount": [0.0],
            "line_text": ["테스트"],
            "header_text": ["배치2"],
            "created_by": ["USER99"],
            "source": ["SAP"],
            "anomaly_score": [0.9],
            "risk_level": ["High"],
            "flagged_rules": ["A01"],
            "upload_batch_id": [batch2],
        })
        col_list = ", ".join(gl2_cols)
        db_conn.execute(f"INSERT INTO general_ledger ({col_list}) SELECT * FROM gl2")

        # 배치1 조회 → 3행만
        df1 = execute_preset(db_conn, "batch_ledger", batch_id=loaded_batch)
        assert len(df1) == 3

        # 배치2 조회 → 1행만
        df2 = execute_preset(db_conn, "batch_ledger", batch_id=batch2)
        assert len(df2) == 1
        assert df2.iloc[0]["document_id"] == "JE-999"


class TestPresetQueriesDict:
    """PRESET_QUERIES dict 무결성."""

    def test_six_queries(self):
        """6종 쿼리가 정의되어 있다."""
        assert len(PRESET_QUERIES) == 6

    def test_all_queries_have_where_clause(self):
        """모든 쿼리에 WHERE upload_batch_id = ? 가 포함된다."""
        for name, sql in PRESET_QUERIES.items():
            assert "upload_batch_id = ?" in sql, f"{name}에 batch_id 바인딩 누락"
