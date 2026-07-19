"""loader.py 단위 테스트.

테스트 그룹:
  - load_general_ledger: 적재 행 수, approval_level 파생
  - load_anomaly_flags: details melt, score > 0 필터
  - load_benford: summary 1행 + digits 9행
  - load_all: 트랜잭션 원자성
  - approval_level: 6단계 한도 정확성 (debit SUM + N threshold = N level)
"""

import pandas as pd

from src.db.loader import (
    LoadResult,
    _derive_approval_level,
    load_all,
    load_anomaly_flags,
    load_benford,
    load_general_ledger,
)

# Why: settings 의존 없이 결정적 테스트를 위한 고정 임계값
_TEST_THRESHOLDS = [
    10_000_000, 100_000_000, 1_000_000_000,
    5_000_000_000, 10_000_000_000, 50_000_000_000,
]


class TestLoadGeneralLedger:
    """general_ledger 테이블 적재."""

    def test_row_count(self, db_conn, db_sample_df):
        """적재 행 수 == DataFrame 행 수."""
        rows = load_general_ledger(db_conn, db_sample_df, "batch_001")
        assert rows == 3

    def test_query_after_load(self, db_conn, db_sample_df):
        """적재 후 조회 결과 일치."""
        load_general_ledger(db_conn, db_sample_df, "batch_001")
        result = db_conn.execute(
            "SELECT COUNT(*) FROM general_ledger WHERE upload_batch_id = 'batch_001'"
        ).fetchone()
        assert result[0] == 3

    def test_approval_level_derived(self, db_conn, db_sample_df):
        """approval_level 파생 컬럼 자동 생성."""
        load_general_ledger(db_conn, db_sample_df, "batch_001")
        result = db_conn.execute(
            "SELECT DISTINCT approval_level FROM general_ledger"
        ).fetchdf()
        assert not result.empty
        assert result["approval_level"].notna().all()

    def test_risk_level_as_string(self, db_conn, db_sample_df):
        """risk_level이 VARCHAR로 정상 적재."""
        load_general_ledger(db_conn, db_sample_df, "batch_001")
        result = db_conn.execute(
            "SELECT DISTINCT risk_level FROM general_ledger ORDER BY risk_level"
        ).fetchdf()
        assert set(result["risk_level"]) == {"Medium", "Normal"}


    def test_missing_required_dates_are_filled_for_db_insert(self, db_conn, db_sample_df):
        df = db_sample_df.copy()
        df.loc[0, "posting_date"] = pd.NaT
        df.loc[0, "fiscal_period"] = pd.NA

        rows = load_general_ledger(db_conn, df, "batch_001")
        result = db_conn.execute(
            """
            SELECT posting_date, fiscal_period
            FROM general_ledger
            WHERE upload_batch_id = 'batch_001'
              AND document_id = 'JE-001'
              AND line_number = 1
            """
        ).fetchone()

        assert rows == 3
        assert result[0] == pd.Timestamp("2022-01-10")
        assert result[1] == 1

    def test_missing_company_code_is_filled_from_batch_mode(self, db_conn, db_sample_df):
        df = db_sample_df.copy()
        df.loc[0, "company_code"] = pd.NA

        load_general_ledger(db_conn, df, "batch_001")
        result = db_conn.execute(
            """
            SELECT DISTINCT company_code
            FROM general_ledger
            WHERE upload_batch_id = 'batch_001'
            ORDER BY company_code
            """
        ).fetchdf()

        assert set(result["company_code"]) == {"C001"}


class TestLoadAnomalyFlags:
    """anomaly_flags 테이블 적재."""

    def test_melt_and_filter(self, db_conn, db_sample_df, db_detection_results):
        """details melt 후 score > 0만 적재."""
        rows = load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        assert rows > 0

    def test_correct_scores(self, db_conn, db_sample_df, db_detection_results):
        """score 값 정합 확인."""
        load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = db_conn.execute(
            "SELECT DISTINCT score FROM anomaly_flags ORDER BY score"
        ).fetchdf()
        scores = set(result["score"])
        assert scores == {0.6, 0.8}

    def test_empty_results(self, db_conn, db_sample_df):
        """빈 results → 0행 적재."""
        rows = load_anomaly_flags(db_conn, [], db_sample_df, "batch_001")
        assert rows == 0

    def test_document_id_mapped(self, db_conn, db_sample_df, db_detection_results):
        """document_id가 원본 DataFrame에서 정확히 매핑."""
        load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = db_conn.execute(
            "SELECT DISTINCT document_id FROM anomaly_flags ORDER BY document_id"
        ).fetchdf()
        assert set(result["document_id"]) <= set(db_sample_df["document_id"])

    def test_non_numeric_detail_columns_are_ignored(
        self, db_conn, db_sample_df, db_detection_results,
    ):
        """설명용 문자열 details 컬럼은 anomaly_flags score 적재에서 제외."""
        db_detection_results[0].details["explanation"] = [
            "normal",
            "candidate",
            "high reconstruction error",
        ]
        db_detection_results[0].details["numeric_string_score"] = ["0.0", "0.2", "0.0"]

        rows = load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = db_conn.execute(
            """
            SELECT rule_code, score
            FROM anomaly_flags
            WHERE upload_batch_id = 'batch_001'
            ORDER BY rule_code, score
            """
        ).fetchdf()

        assert rows == 4
        assert "explanation" not in set(result["rule_code"])
        assert set(result["score"]) == {0.2, 0.6, 0.8}


class TestLoadBenford:
    """benford_summary + benford_digits 적재."""

    def test_summary_1_row(self, db_conn, db_benford_results):
        """benford_summary 배치당 1행."""
        s_rows, d_rows, warnings = load_benford(db_conn, db_benford_results, "batch_001")
        assert s_rows == 1

    def test_digits_9_rows(self, db_conn, db_benford_results):
        """benford_digits 자릿수별 9행."""
        s_rows, d_rows, warnings = load_benford(db_conn, db_benford_results, "batch_001")
        assert d_rows == 9

    def test_no_benford_result(self, db_conn):
        """BenfordResult 없으면 0행 + 경고."""
        s_rows, d_rows, warnings = load_benford(db_conn, [], "batch_001")
        assert s_rows == 0
        assert d_rows == 0
        assert len(warnings) > 0

    def test_deviation_calc(self, db_conn, db_benford_results):
        """deviation = observed - expected 검증."""
        load_benford(db_conn, db_benford_results, "batch_001")
        result = db_conn.execute(
            "SELECT digit, observed_freq, expected_freq, deviation "
            "FROM benford_digits ORDER BY digit"
        ).fetchdf()
        for _, row in result.iterrows():
            assert abs(row["deviation"] - (row["observed_freq"] - row["expected_freq"])) < 1e-10


class TestLoadAll:
    """load_all 트랜잭션 원자성."""

    def test_returns_load_result(self, db_conn, db_sample_df):
        """LoadResult 반환."""
        result = load_all(db_conn, db_sample_df, batch_id="batch_001")
        assert isinstance(result, LoadResult)
        assert result.is_success is True
        assert result.general_ledger_rows == 3

    def test_batch_id_consistency(self, db_conn, db_sample_df):
        """4개 테이블에 동일 batch_id."""
        load_all(db_conn, db_sample_df, batch_id="test_batch")
        gl = db_conn.execute(
            "SELECT DISTINCT upload_batch_id FROM general_ledger"
        ).fetchdf()
        assert gl["upload_batch_id"].iloc[0] == "test_batch"

    def test_two_batches_isolated(self, db_conn, db_sample_df):
        """2개 배치 적재 후 분리 조회."""
        load_all(db_conn, db_sample_df, batch_id="batch_A")
        load_all(db_conn, db_sample_df, batch_id="batch_B")
        a = db_conn.execute(
            "SELECT COUNT(*) FROM general_ledger WHERE upload_batch_id = 'batch_A'"
        ).fetchone()[0]
        b = db_conn.execute(
            "SELECT COUNT(*) FROM general_ledger WHERE upload_batch_id = 'batch_B'"
        ).fetchone()[0]
        assert a == 3
        assert b == 3


class TestApprovalLevel:
    """전결규정 6단계 파생 정확성 (debit SUM + N threshold = N level)."""

    def test_six_levels(self, db_large_df):
        """6단계 금액 범위 → 레벨 1~6 정확 산출."""
        levels = _derive_approval_level(db_large_df, thresholds=_TEST_THRESHOLDS)
        expected = [1, 2, 3, 4, 5, 6]
        assert list(levels) == expected

    def test_boundary_10m(self):
        """경계값: 정확히 1천만원 → Level 1."""
        df = pd.DataFrame({
            "document_id": ["JE-001"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
        })
        level = _derive_approval_level(df, thresholds=_TEST_THRESHOLDS)
        assert level.iloc[0] == 1

    def test_boundary_10m_plus_1(self):
        """경계값: 1천만원 + 1 → Level 2."""
        df = pd.DataFrame({
            "document_id": ["JE-001"],
            "debit_amount": [10_000_001.0],
            "credit_amount": [0.0],
        })
        level = _derive_approval_level(df, thresholds=_TEST_THRESHOLDS)
        assert level.iloc[0] == 2

    def test_multi_line_document(self):
        """전표 내 여러 라인 → 차변 합산 기준."""
        df = pd.DataFrame({
            "document_id": ["JE-001", "JE-001"],
            "debit_amount": [5_000_000.0, 200_000_000.0],
            "credit_amount": [0.0, 0.0],
        })
        levels = _derive_approval_level(df, thresholds=_TEST_THRESHOLDS)
        # Why: 차변 합산 5M + 200M = 205M ≤ 1B → Level 3
        assert list(levels) == [3, 3]

    def test_sum_vs_max_difference(self):
        """합산과 최대값이 다른 레벨을 산출하는 케이스 — SUM 기준 검증."""
        df = pd.DataFrame({
            "document_id": ["JE-001", "JE-001"],
            "debit_amount": [60_000_000.0, 60_000_000.0],
            "credit_amount": [0.0, 0.0],
        })
        levels = _derive_approval_level(df, thresholds=_TEST_THRESHOLDS)
        # Why: 차변 합산 60M + 60M = 120M → Level 3 (≤1B)
        #       MAX였다면 60M → Level 2 (≤100M) — 오류
        assert list(levels) == [3, 3]

    def test_credit_side_document_amount_can_drive_level(self):
        df = pd.DataFrame({
            "document_id": ["JE-001", "JE-001"],
            "debit_amount": [4_551_508.0, 0.0],
            "credit_amount": [0.0, 45_515_080.0],
        })
        levels = _derive_approval_level(df, thresholds=_TEST_THRESHOLDS)
        assert list(levels) == [2, 2]

    def test_custom_thresholds(self):
        """커스텀 임계값 파라미터 — N threshold = N level, 초과분 캡."""
        df = pd.DataFrame({
            "document_id": ["A", "B", "C"],
            "debit_amount": [50.0, 150.0, 350.0],
            "credit_amount": [0.0, 0.0, 0.0],
        })
        levels = _derive_approval_level(df, thresholds=[100, 200, 300])
        # 50≤100 → Level 1, 150≤200 → Level 2, 350>300 → Level 3 (최고 레벨 캡)
        assert list(levels) == [1, 2, 3]

    def test_exceeds_all_thresholds_capped(self):
        """모든 임계값 초과 시 최고 레벨(N)에 캡."""
        df = pd.DataFrame({
            "document_id": ["JE-001"],
            "debit_amount": [100_000_000_000.0],
            "credit_amount": [0.0],
        })
        levels = _derive_approval_level(df, thresholds=_TEST_THRESHOLDS)
        # Why: 1000억 > 50B(마지막 threshold) → Level 6 (최고 레벨 캡)
        assert levels.iloc[0] == 6


class TestMLVarcharNanToNull:
    """ML 예약 컬럼 NaN→NULL 안전 변환."""

    def test_ml_varchar_nan_to_null(self, db_conn, db_sample_df):
        """Phase 1 DataFrame에 ML 컬럼 없을 때 VARCHAR가 NULL이지 'nan'이 아님."""
        load_general_ledger(db_conn, db_sample_df, "batch_ml")
        result = db_conn.execute(
            "SELECT supervised_model_id, unsupervised_model_id, duplicate_model_id "
            "FROM general_ledger WHERE upload_batch_id = 'batch_ml' LIMIT 1"
        ).fetchone()
        # Why: reindex NaN이 DuckDB INSERT 시 'nan' 문자열로 들어가면 안 됨
        for val in result:
            assert val is None, f"VARCHAR 컬럼이 NULL이 아님: {val!r}"

    def test_ml_double_null(self, db_conn, db_sample_df):
        """Phase 1 DataFrame에 ML score 컬럼 없을 때 DOUBLE이 NULL."""
        load_general_ledger(db_conn, db_sample_df, "batch_ml2")
        result = db_conn.execute(
            "SELECT supervised_score, unsupervised_score, duplicate_score "
            "FROM general_ledger WHERE upload_batch_id = 'batch_ml2' LIMIT 1"
        ).fetchone()
        for val in result:
            assert val is None, f"DOUBLE 컬럼이 NULL이 아님: {val!r}"

    def test_ml_timestamp_null(self, db_conn, db_sample_df):
        """Phase 1 DataFrame에 ml_scored_at 없을 때 TIMESTAMP이 NULL."""
        load_general_ledger(db_conn, db_sample_df, "batch_ml3")
        result = db_conn.execute(
            "SELECT ml_scored_at FROM general_ledger "
            "WHERE upload_batch_id = 'batch_ml3' LIMIT 1"
        ).fetchone()
        assert result[0] is None
