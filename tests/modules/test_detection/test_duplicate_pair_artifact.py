"""DuplicateDetector pair similarity artifact 테스트.

Why: row-level scores 회귀 없이 pair_artifact metadata가 정확히 산출되는지 검증.
     기존 함수 시그니처/contract는 손대지 않고, helper에서 만들어지는 artifact가
     bounded·sanitized 상태로 metadata에 들어가야 한다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.duplicate_detector import DuplicateDetector


def _pair_artifact(result) -> dict:
    artifact = result.metadata.get("pair_artifact")
    assert artifact is not None, "pair_artifact metadata가 비어 있음"
    return artifact


def _pairs_by_rule(artifact: dict, rule_id: str) -> list[dict]:
    return [pair for pair in artifact["top_pairs"] if pair["rule_id"] == rule_id]


# ── 기본 contract ─────────────────────────────────────────────


class TestPairArtifactContract:
    def test_schema_keys_present(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000],
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
                "line_text": ["매입", "매입"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        for key in (
            "schema_version",
            "total_candidate_pairs",
            "candidate_pairs_after_caps",
            "retained_pairs",
            "truncated",
            "truncation_reason",
            "rule_pair_counts",
            "top_pairs",
            "coverage",
        ):
            assert key in artifact, f"missing key {key}"
        assert artifact["schema_version"] == 1
        # retained_pairs는 sanitize 후 metadata 에 보존된 top_pairs 수와 일치
        assert artifact["retained_pairs"] == len(artifact["top_pairs"])

    def test_no_text_leak_in_top_pairs(self) -> None:
        """top_pairs에는 원문 line_text/reference가 포함되면 안 됨."""
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000],
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
                "line_text": ["매우 민감한 적요 원문", "매우 민감한 적요 원문"],
                "reference": ["REF-SECRET-001", "REF-SECRET-001"],
                "document_id": ["DOC-1", "DOC-2"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        assert artifact["top_pairs"], "exact pair는 산출되어야 함"
        for pair in artifact["top_pairs"]:
            payload = repr(pair)
            assert "매우 민감한" not in payload, "line_text 원문이 노출됨"
            assert "REF-SECRET" not in payload, "reference 원문이 노출됨"
            assert "document_id" not in pair["features"], "features에 document_id 누설"

    def test_row_score_contract_unchanged(self) -> None:
        """artifact 도입 후에도 기존 details/scores shape는 그대로."""
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000, 2000],
                "debit_amount": [500.0, 500.0, 300.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01", "2025-03-01"]),
                "line_text": ["매입", "매입", "기타"],
            }
        )
        result = DuplicateDetector().detect(df)
        assert list(result.details.columns) == ["L2-03a", "L2-03b", "L2-03c", "L2-03d"]
        assert (result.scores.min(), result.scores.max()) >= (0.0, 0.0)
        assert result.scores.max() <= 1.0


# ── sub-rule별 pair ───────────────────────────────────────────


class TestPairArtifactExact:
    def test_exact_pair_recorded(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000, 2000],
                "debit_amount": [500.0, 500.0, 300.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01", "2025-03-01"]),
                "line_text": ["매입", "매입", "기타"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        exact_pairs = _pairs_by_rule(artifact, "L2-03a")
        assert len(exact_pairs) == 1
        pair = exact_pairs[0]
        assert pair["pair_score"] == pytest.approx(1.0)
        assert pair["features"]["amount_similarity"] == pytest.approx(1.0)
        assert pair["features"]["same_account"] is True
        assert pair["rule_source"] == "exact_duplicate_amount"


class TestPairArtifactFuzzy:
    def test_fuzzy_pair_score_in_range(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000, 2000],
                "debit_amount": [1_000_000.0, 998_000.0, 500.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-02", "2025-03-01"]),
                "line_text": [
                    "삼성전자 법인카드 결제",
                    "삼성전자 법인카드 결제건",
                    "기타",
                ],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        fuzzy = _pairs_by_rule(artifact, "L2-03b")
        assert len(fuzzy) == 1
        pair = fuzzy[0]
        assert 0.0 < pair["pair_score"] <= 1.0
        assert pair["features"]["amount_similarity"] > 0.97
        assert pair["features"]["text_similarity"] > 0.7
        # date_similarity 는 fuzzy 에 정의되지 않으므로 None 으로 남겨야 한다.
        assert pair["features"]["date_similarity"] is None
        assert pair["features"]["date_distance_days"] == 1

    def test_fuzzy_far_date_distance_reported_accurately(self) -> None:
        """fuzzy pair 가 100일 떨어져 있어도 date_distance_days 는 정확하고,
        date_similarity 가 임의 분모로 왜곡되지 않는다."""
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000, 2000],
                "debit_amount": [1_000_000.0, 998_000.0, 500.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-01-01", "2025-04-11", "2025-03-01"]),
                "line_text": [
                    "삼성전자 법인카드 결제",
                    "삼성전자 법인카드 결제건",
                    "기타",
                ],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        fuzzy = _pairs_by_rule(artifact, "L2-03b")
        assert len(fuzzy) == 1
        pair = fuzzy[0]
        assert pair["features"]["date_distance_days"] == 100
        assert pair["features"]["date_similarity"] is None


class TestPairArtifactSplit:
    def test_split_pairs_recorded(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000, 1000, 2000],
                "debit_amount": [1_000_000.0, 500_000.0, 500_000.0, 800.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(
                    ["2025-03-01", "2025-03-02", "2025-03-02", "2025-03-01"]
                ),
                "line_text": ["대금", "분할1", "분할2", "기타"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        split = _pairs_by_rule(artifact, "L2-03c")
        assert len(split) >= 1
        pair = split[0]
        assert pair["rule_source"] == "split_transaction"
        assert pair["features"]["target_amount"] == pytest.approx(1_000_000.0)
        assert 0.0 < pair["pair_score"] <= 1.0


class TestPairArtifactTimeShift:
    def test_timeshift_pair_recorded(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000, 2000],
                "debit_amount": [500.0, 500.0, 300.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-04", "2025-03-01"]),
                "line_text": ["매입", "매입", "기타"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        timeshift = _pairs_by_rule(artifact, "L2-03d")
        assert len(timeshift) == 1
        pair = timeshift[0]
        assert pair["features"]["date_distance_days"] == 3
        assert pair["pair_score"] == pytest.approx(1.0 - 3 / 7)


# ── graceful degradation ─────────────────────────────────────


class TestPairArtifactDegradation:
    def test_missing_line_text_skips_fuzzy_only(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000],
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        assert artifact["coverage"]["has_line_text"] is False
        assert artifact["rule_pair_counts"].get("L2-03b", 0) == 0
        assert artifact["rule_pair_counts"].get("L2-03a", 0) == 1

    def test_missing_gl_account_empty_artifact(self) -> None:
        df = pd.DataFrame(
            {
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        assert artifact["coverage"]["skip_all"] is True
        assert artifact["top_pairs"] == []
        assert artifact["total_candidate_pairs"] == 0

    def test_missing_partner_keeps_score_unchanged(self) -> None:
        """trading_partner 없어도 row score는 변동 없음 (NaN feature만)."""
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000],
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
                "line_text": ["매입", "매입"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        exact = _pairs_by_rule(artifact, "L2-03a")
        assert exact[0]["features"]["same_partner"] is None


# ── cap / 정상 반복 거래 ──────────────────────────────────────


class TestPairArtifactCaps:
    def test_per_row_cap_marks_truncated(self) -> None:
        """정상 반복 거래(월세 12건)에서 max_pairs_per_row 발동."""
        settings = AuditSettings(
            duplicate_max_pairs_per_row=3,
            duplicate_max_total_pairs=200_000,
        )
        rows = 12
        df = pd.DataFrame(
            {
                "gl_account": [1000] * rows,
                "debit_amount": [1_000_000.0] * rows,
                "credit_amount": [0.0] * rows,
                "posting_date": pd.date_range("2025-01-01", periods=rows, freq="MS"),
                "line_text": ["월세 지급"] * rows,
            }
        )
        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))
        assert artifact["truncated"] is True
        assert artifact["truncation_reason"] == "max_pairs_per_row"

    def test_global_total_cap_marks_truncated(self) -> None:
        settings = AuditSettings(
            duplicate_max_pairs_per_row=500,
            duplicate_max_total_pairs=5,
        )
        df = pd.DataFrame(
            {
                "gl_account": [1000] * 20,
                "debit_amount": [500.0] * 20,
                "credit_amount": [0.0] * 20,
                "posting_date": pd.to_datetime(["2025-03-01"] * 20),
                "line_text": ["매입"] * 20,
            }
        )
        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))
        assert artifact["truncated"] is True
        assert artifact["truncation_reason"] in {
            "max_total_pairs",
            "max_pairs_per_row",
            "max_group_size",
        }

    def test_top_n_cap_bounds_metadata(self) -> None:
        """top_n=2 → metadata에는 score 상위 2개만."""
        settings = AuditSettings(duplicate_pair_artifact_top_n=2)
        df = pd.DataFrame(
            {
                "gl_account": [1000] * 5,
                "debit_amount": [500.0] * 5,
                "credit_amount": [0.0] * 5,
                "posting_date": pd.to_datetime(["2025-03-01"] * 5),
                "line_text": ["매입"] * 5,
            }
        )
        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))
        assert len(artifact["top_pairs"]) <= 2
