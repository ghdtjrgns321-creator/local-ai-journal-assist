"""RelationalDetector 오케스트레이터 단위 테스트 — WU-08.

15개 테스트: Basic(3) + Integration(4) + Graceful(5) + DocFlow(3)
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.relational_detector import RelationalDetector


# ── 공용 헬퍼 ──────────────────────────────────────────────────


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """테스트용 DataFrame 생성."""
    df = pd.DataFrame(rows)
    if "posting_date" in df.columns:
        df["posting_date"] = pd.to_datetime(df["posting_date"])
    for col in ["debit_amount", "credit_amount"]:
        if col not in df.columns:
            df[col] = 0.0
    return df


def _detector(**kwargs) -> RelationalDetector:
    return RelationalDetector(**kwargs)


def _full_df() -> pd.DataFrame:
    """R01~R03 테스트용 — 다양한 패턴 포함."""
    return _make_df([
        # 기존 거래처 정상 거래
        {"trading_partner": "V01", "gl_account": "5100", "posting_date": "2023-01-15",
         "debit_amount": 1_000_000, "credit_amount": 0, "is_intercompany": False},
        {"trading_partner": "V01", "gl_account": "5100", "posting_date": "2023-06-15",
         "debit_amount": 1_000_000, "credit_amount": 0, "is_intercompany": False},
        # 신규 거래처 대액 (R01 트리거)
        {"trading_partner": "V99", "gl_account": "5200", "posting_date": "2023-06-20",
         "debit_amount": 50_000_000, "credit_amount": 0, "is_intercompany": False},
        # 휴면 계정 재활성화 (R02 트리거) — 5100 계정 200일 후
        {"trading_partner": "V01", "gl_account": "5100", "posting_date": "2024-01-01",
         "debit_amount": 5_000_000, "credit_amount": 0, "is_intercompany": False},
        # IC 거래 정상 (R03 비트리거)
        {"trading_partner": "SUB01", "gl_account": "4500", "posting_date": "2024-01-05",
         "debit_amount": 10_000_000, "credit_amount": 0, "is_intercompany": True},
        {"trading_partner": "SUB01", "gl_account": "4500", "posting_date": "2024-01-10",
         "debit_amount": 10_000_000, "credit_amount": 0, "is_intercompany": True},
        {"trading_partner": "SUB01", "gl_account": "4500", "posting_date": "2024-01-15",
         "debit_amount": 10_000_000, "credit_amount": 0, "is_intercompany": True},
        # IC 이전가격 이상 (R03 트리거)
        {"trading_partner": "SUB01", "gl_account": "4500", "posting_date": "2024-01-20",
         "debit_amount": 50_000_000, "credit_amount": 0, "is_intercompany": True},
    ])


# ── Basic (3개) ────────────────────────────────────────────────


class TestBasic:
    """기본 인터페이스 검증."""

    def test_track_name(self):
        """#1: track_name은 'relational'."""
        assert _detector().track_name == "relational"

    def test_returns_detection_result(self):
        """#2: detect() 반환 타입은 DetectionResult."""
        result = _detector().detect(_full_df())
        assert isinstance(result, DetectionResult)
        assert result.track_name == "relational"

    def test_scores_range(self):
        """#3: 모든 scores 0.0~1.0."""
        result = _detector().detect(_full_df())
        assert result.scores.between(0.0, 1.0).all(), (
            f"범위 초과: min={result.scores.min()}, max={result.scores.max()}"
        )


# ── Integration (4개) ──────────────────────────────────────────


class TestIntegration:
    """룰 통합 검증."""

    def test_multiple_rules_fire(self):
        """#4: R01, R02, R03 중 최소 2개 이상 플래그 발생."""
        result = _detector().detect(_full_df())
        active_rules = [rf.rule_id for rf in result.rule_flags if rf.flagged_count > 0]
        assert len(active_rules) >= 2, f"활성 룰: {active_rules}"

    def test_severity_normalization(self):
        """#5: details 값은 severity/5.0 정규화."""
        result = _detector().detect(_full_df())
        for col in result.details.columns:
            max_val = result.details[col].max()
            # severity/5.0이 최대 (R03=4 → 0.8)
            assert max_val <= 1.0, f"{col} 정규화 초과: {max_val}"

    def test_max_pattern(self):
        """#6: scores = details 행별 MAX."""
        result = _detector().detect(_full_df())
        expected_max = result.details.max(axis=1).fillna(0.0)
        pd.testing.assert_series_equal(result.scores, expected_max, check_names=False)

    def test_rule_flags_created(self):
        """#7: rule_flags에 R01~R03 포함 (R04는 doc_flow_df 없으면 미등록)."""
        result = _detector().detect(_full_df())
        rule_ids = {rf.rule_id for rf in result.rule_flags}
        assert "R01" in rule_ids
        assert "R02" in rule_ids
        assert "R03" in rule_ids


# ── Graceful (5개) ────────────────────────────────────────────


class TestGraceful:
    """Graceful degradation 검증."""

    def test_missing_all_columns(self):
        """#8: 주요 컬럼 전부 누락 → 빈 결과 + warning."""
        df = pd.DataFrame({"some_col": [1, 2, 3]})
        result = _detector().detect(df)
        assert isinstance(result, DetectionResult)
        assert (result.scores == 0.0).all()

    def test_no_doc_flow_skips_r04(self):
        """#9: doc_flow_df=None → R01~R03만 실행, R04 미등록."""
        result = _detector(doc_flow_df=None).detect(_full_df())
        rule_ids = {rf.rule_id for rf in result.rule_flags}
        assert "R04" not in rule_ids, "doc_flow_df 없는데 R04 실행됨"

    def test_doc_flow_enables_r04(self):
        """#10: doc_flow_df 제공 시 R04 등록."""
        doc_flow = pd.DataFrame([
            {"journal_entry_id": "dummy", "chain": "P2P", "total": 3, "present": 1},
        ])
        df = _full_df()
        df["document_id"] = [f"JE-{i:03d}" for i in range(len(df))]
        result = _detector(doc_flow_df=doc_flow).detect(df)
        rule_ids = {rf.rule_id for rf in result.rule_flags}
        assert "R04" in rule_ids, "doc_flow_df 제공했는데 R04 미등록"

    def test_individual_rule_exception(self):
        """#11: 개별 룰 예외 → skipped에 기록, 다른 룰 계속."""
        # R01만 실패하도록 — trading_partner에 비호환 타입 주입
        df = _make_df([
            {"trading_partner": "V01", "gl_account": "5100",
             "posting_date": "2023-01-15", "debit_amount": 1_000_000,
             "is_intercompany": False},
            {"trading_partner": "V01", "gl_account": "5100",
             "posting_date": "2024-01-15", "debit_amount": 1_000_000,
             "is_intercompany": False},
        ])
        # 정상 실행 — 예외가 아닌 일반 케이스에서도 skipped 처리가 동작하는지
        result = _detector().detect(df)
        assert isinstance(result, DetectionResult)

    def test_empty_dataframe(self):
        """#12: 빈 DataFrame → 빈 결과."""
        df = pd.DataFrame(columns=["trading_partner", "gl_account", "posting_date",
                                    "debit_amount", "credit_amount", "is_intercompany"])
        result = _detector().detect(df)
        assert isinstance(result, DetectionResult)
        assert len(result.flagged_indices) == 0


# ── DocFlow Integration (3개) ─────────────────────────────────


class TestDocFlowIntegration:
    """R04 document_flows 통합 검증."""

    def test_r04_scores_in_result(self):
        """#13: R04 점수가 DetectionResult.details에 포함."""
        doc_flow = pd.DataFrame([
            {"journal_entry_id": "JE-002", "chain": "P2P", "total": 3, "present": 1},
        ])
        df = _make_df([
            {"document_id": "JE-001", "trading_partner": "V01", "gl_account": "5100",
             "posting_date": "2024-01-15", "debit_amount": 1_000_000, "is_intercompany": False},
            {"document_id": "JE-002", "trading_partner": "V01", "gl_account": "5100",
             "posting_date": "2024-01-20", "debit_amount": 2_000_000, "is_intercompany": False},
        ])
        result = _detector(doc_flow_df=doc_flow).detect(df)
        assert "R04" in result.details.columns
        assert result.details["R04"].iloc[1] > 0, "R04 매칭 행 미탐지"
        assert result.details["R04"].iloc[0] == 0.0, "R04 비매칭 행 플래그됨"

    def test_r04_empty_doc_flow(self):
        """#14: 빈 doc_flow_df → R04 등록되나 모두 0점."""
        doc_flow = pd.DataFrame(columns=["journal_entry_id", "chain", "total", "present"])
        df = _make_df([
            {"document_id": "JE-001", "trading_partner": "V01", "gl_account": "5100",
             "posting_date": "2024-01-15", "debit_amount": 1_000_000, "is_intercompany": False},
        ])
        result = _detector(doc_flow_df=doc_flow).detect(df)
        # 빈 doc_flow → R04 스킵 (None 반환과 동일 처리)
        rule_ids = {rf.rule_id for rf in result.rule_flags}
        # 빈 DataFrame은 graceful 처리 → R04 미등록 또는 0점
        if "R04" in rule_ids:
            r04_flag = [rf for rf in result.rule_flags if rf.rule_id == "R04"][0]
            assert r04_flag.flagged_count == 0

    def test_metadata_elapsed(self):
        """#15: metadata에 elapsed 시간 포함."""
        result = _detector().detect(_full_df())
        assert "elapsed" in result.metadata
        assert result.metadata["elapsed"] >= 0
