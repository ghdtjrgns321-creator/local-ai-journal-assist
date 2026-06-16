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
from src.detection.duplicate_pair_features import (
    _select_large_input_candidate_frame,
    _select_top_pairs_with_evidence_diversity,
    _select_top_pairs_with_rule_balanced_evidence,
)
from src.services.phase2_duplicate_case_builder import build_duplicate_cases


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
                "reference": ["INV-001", "INV-001", "INV-003"],
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
                "reference": ["INV-001", "INV-001", "INV-003"],
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

    def test_exact_same_document_line_pair_is_dropped(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-1"],
                "gl_account": [1000, 1000],
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
                "line_text": ["매입", "매입"],
                "reference": ["INV-001", "INV-001"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))

        assert artifact["retained_pairs"] == 0
        assert _pairs_by_rule(artifact, "L2-03a") == []

    def test_exact_cross_document_pair_is_retained(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-2"],
                "gl_account": [1000, 1000],
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
                "line_text": ["매입", "매입"],
                "reference": ["INV-001", "INV-001"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))

        assert len(_pairs_by_rule(artifact, "L2-03a")) == 1

    def test_reversal_link_pair_is_excluded_from_duplicate_artifact(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["DOC-ORIG", "DOC-REV"],
                "gl_account": [1000, 1000],
                "debit_amount": [500.0, 500.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01"]),
                "line_text": ["monthly accrual", "monthly accrual reversal"],
                "reference": ["ACCR-001", "ACCR-001"],
                "original_document_id": ["", "DOC-ORIG"],
                "reversal_document_id": ["DOC-REV", ""],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))

        assert artifact["retained_pairs"] == 0
        assert artifact["top_pairs"] == []


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
                "reference": ["CARD-001", "CARD-001", "ETC-001"],
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
                "reference": ["CARD-001", "CARD-001", "ETC-001"],
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
                "reference": ["INV-SPLIT", "INV-SPLIT", "INV-SPLIT", "ETC"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        split = _pairs_by_rule(artifact, "L2-03c")
        assert len(split) >= 1
        pair = split[0]
        assert pair["rule_source"] == "split_transaction"
        assert pair["features"]["target_amount"] == pytest.approx(1_000_000.0)
        assert 0.0 < pair["pair_score"] <= 1.0

    def test_split_same_document_line_pair_is_dropped(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-1", "DOC-1"],
                "gl_account": [1000, 1000, 1000],
                "debit_amount": [1_000_000.0, 500_000.0, 500_000.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-02", "2025-03-02"]),
                "line_text": ["대금", "분할1", "분할2"],
                "reference": ["INV-SPLIT", "INV-SPLIT", "INV-SPLIT"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))

        assert _pairs_by_rule(artifact, "L2-03c") == []


class TestPairArtifactTimeShift:
    def test_timeshift_pair_recorded(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": [1000, 1000, 2000],
                "debit_amount": [500.0, 500.0, 300.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01", "2025-03-04", "2025-03-01"]),
                "line_text": ["매입", "매입", "기타"],
                "reference": ["INV-001", "INV-001", "ETC-001"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        timeshift = _pairs_by_rule(artifact, "L2-03d")
        assert len(timeshift) == 1
        pair = timeshift[0]
        assert pair["features"]["date_distance_days"] == 3
        assert pair["pair_score"] == pytest.approx(1.0 - 3 / 7)


class TestPairArtifactDocumentProfile:
    def test_document_profile_pair_recorded_for_p2p_time_shifted_documents(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-1", "DOC-2", "DOC-2"],
                "business_process": ["P2P", "P2P", "P2P", "P2P"],
                "gl_account": [1000, 2000, 1000, 2000],
                "debit_amount": [500.0, 0.0, 500.0, 0.0],
                "credit_amount": [0.0, 500.0, 0.0, 500.0],
                "posting_date": pd.to_datetime(
                    ["2025-03-01", "2025-03-01", "2025-03-03", "2025-03-03"]
                ),
                "line_text": ["invoice", "offset", "invoice", "offset"],
                "trading_partner": ["VEND-A", "VEND-A", "VEND-A", "VEND-A"],
                "reference": [
                    "EMP-CARD-DUP-01",
                    "EMP-CARD-DUP-01",
                    "EMP-CARD-DUP-01",
                    "EMP-CARD-DUP-01",
                ],
            }
        )

        artifact = _pair_artifact(DuplicateDetector().detect(df))
        profile = _pairs_by_rule(artifact, "L2-03e")

        assert profile
        pair = profile[0]
        assert pair["rule_source"] == "document_profile_duplicate"
        assert pair["features"]["same_partner"] is True
        assert pair["features"]["reference_similarity"] >= 0.9
        assert pair["features"]["amount_similarity"] >= 0.98


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
        assert artifact["rule_pair_counts"].get("L2-03a", 0) == 0
        assert artifact["coverage"]["recurring_ambiguous_dropped_pairs"] == 1

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
                "reference": ["INV-001", "INV-001"],
            }
        )
        artifact = _pair_artifact(DuplicateDetector().detect(df))
        exact = _pairs_by_rule(artifact, "L2-03a")
        assert exact[0]["features"]["same_partner"] is None


# ── cap / 정상 반복 거래 ──────────────────────────────────────


class TestPairArtifactCaps:
    def test_large_input_row_score_candidates_still_emit_joinable_pairs(self) -> None:
        """대용량 cap 상황에서도 row-score 후보가 있으면 pair evidence를 남긴다."""
        settings = AuditSettings(duplicate_pair_artifact_max_rows=2)
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-2", "DOC-3", "DOC-4"],
                "gl_account": [1000, 1000, 2000, 3000],
                "debit_amount": [500.0, 500.0, 300.0, 700.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(
                    ["2025-03-01", "2025-03-01", "2025-03-02", "2025-03-03"]
                ),
                "line_text": ["매입", "매입", "기타", "기타2"],
                "trading_partner": ["VEND-A", "VEND-A", "VEND-B", "VEND-C"],
                "reference": ["INV-001", "INV-001", "INV-003", "INV-004"],
            },
            index=pd.Index(["r0", "r1", "r2", "r3"]),
        )

        result = DuplicateDetector(settings).detect(df)
        artifact = _pair_artifact(result)

        assert artifact["coverage"]["bounded_from_large_input"] is True
        assert artifact["coverage"]["row_score_hit_count"] >= 2
        assert artifact["top_pairs"]
        for pair in artifact["top_pairs"]:
            assert pair["left_index"] in df.index
            assert pair["right_index"] in df.index

    def test_large_input_pair_artifact_builds_duplicate_case(self) -> None:
        """artifact pair가 strong evidence unit이면 DuplicateCase로 변환된다."""
        settings = AuditSettings(duplicate_pair_artifact_max_rows=2)
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-2", "DOC-3", "DOC-4"],
                "gl_account": [1000, 1000, 2000, 3000],
                "debit_amount": [500.0, 500.0, 300.0, 700.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(
                    ["2025-03-01", "2025-03-01", "2025-03-02", "2025-03-03"]
                ),
                "line_text": ["매입", "매입", "기타", "기타2"],
                "trading_partner": ["VEND-A", "VEND-A", "VEND-B", "VEND-C"],
                "reference": ["INV-001", "INV-001", "INV-003", "INV-004"],
            },
            index=pd.Index(["r0", "r1", "r2", "r3"]),
        )

        result = DuplicateDetector(settings).detect(df)
        cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)

        assert cases
        assert any(case.family == "duplicate" for case in cases)
        assert all(case.unit_type == "pair" for case in cases)
        assert any(case.pair_evidence_tier == "strong" for case in cases)

    def test_large_input_candidate_subset_reserves_observable_profile_supplement(
        self,
    ) -> None:
        """Lower-score duplicate-shaped P2P docs get a bounded route to pair evidence."""
        df = pd.DataFrame(
            {
                "document_id": ["DOC-H1", "DOC-H2", "DOC-S1", "DOC-S1"],
                "business_process": ["O2C", "O2C", "P2P", "P2P"],
                "gl_account": [1000, 1000, 2000, 2000],
                "debit_amount": [900.0, 900.0, 700.0, 700.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(
                    ["2025-03-01", "2025-03-01", "2025-03-02", "2025-03-04"]
                ),
                "line_text": ["high", "high", "supp", "supp"],
                "trading_partner": ["", "", "VEND-A", "VEND-A"],
                "reference": ["", "", "INV-1", "INV-1"],
            },
            index=pd.Index(["h0", "h1", "s0", "s1"]),
        )
        candidate_scores = pd.Series(
            [1.0, 0.9, 0.1, 0.1],
            index=df.index,
            dtype=float,
        )

        candidate_df, coverage = _select_large_input_candidate_frame(
            df,
            max_rows=3,
            candidate_scores=candidate_scores,
            candidate_details=None,
            candidate_supplement_strategy="observable_profile",
            candidate_supplement_max_docs=1,
        )

        assert candidate_df is not None
        assert set(candidate_df["document_id"]) >= {"DOC-S1"}
        assert len(candidate_df) <= 3
        assert coverage["candidate_supplement_strategy"] == "observable_profile"
        assert coverage["candidate_supplement_selected_docs"] == 1
        assert coverage["candidate_supplement_selected_rows"] == 2

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

    def test_top_n_no_longer_bounds_measurement_metadata(self) -> None:
        """P2-3: top_n은 measurement artifact를 자르지 않는다."""
        settings = AuditSettings(duplicate_pair_artifact_top_n=2)
        df = pd.DataFrame(
            {
                "gl_account": [1000] * 5,
                "debit_amount": [500.0] * 5,
                "credit_amount": [0.0] * 5,
                "posting_date": pd.to_datetime(["2025-03-01"] * 5),
                "line_text": ["매입"] * 5,
                "reference": ["INV-001"] * 5,
            }
        )
        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))
        assert len(artifact["top_pairs"]) > 2
        assert artifact["coverage"]["top_pair_selection"]["top_n_cap_applied"] is False

    def test_top_n_retention_uses_document_diversity(self) -> None:
        """동일 dense 문서군이 top_pairs 전체를 점유하지 않게 보존한다."""
        settings = AuditSettings(
            duplicate_pair_artifact_selection_strategy="document_diversity",
            duplicate_pair_artifact_top_n=6,
            duplicate_pair_artifact_max_pairs_per_document=1,
            duplicate_pair_artifact_max_pairs_per_document_pair=1,
        )
        df = pd.DataFrame(
            {
                "document_id": [f"DOC-{i}" for i in range(7)],
                "gl_account": [1000, 1000, 1000, 1000, 1000, 2000, 2000],
                "debit_amount": [500.0, 500.0, 500.0, 500.0, 500.0, 900.0, 900.0],
                "credit_amount": [0.0] * 7,
                "posting_date": pd.to_datetime(["2025-03-01"] * 7),
                "line_text": ["반복"] * 5 + ["별도", "별도"],
                "trading_partner": ["V-A"] * 5 + ["V-B", "V-B"],
                "reference": ["REF-A"] * 5 + ["REF-B", "REF-B"],
            }
        )

        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))
        docs = {
            doc
            for pair in artifact["top_pairs"]
            for doc in (pair.get("left_document_id"), pair.get("right_document_id"))
        }

        assert "DOC-5" in docs
        assert "DOC-6" in docs
        assert artifact["coverage"]["top_pair_selection"]["strategy"] == (
            "complete_measurement_population"
        )

    def test_document_diversity_soft_cap_fills_when_needed(self) -> None:
        """diversity pass가 top_n을 못 채우면 score 순 fill로 metadata를 채운다."""
        settings = AuditSettings(
            duplicate_pair_artifact_selection_strategy="document_diversity",
            duplicate_pair_artifact_top_n=3,
            duplicate_pair_artifact_max_pairs_per_document=1,
            duplicate_pair_artifact_max_pairs_per_document_pair=1,
        )
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-2", "DOC-3"],
                "gl_account": [1000, 1000, 1000],
                "debit_amount": [500.0, 500.0, 500.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01"] * 3),
                "line_text": ["반복"] * 3,
                "trading_partner": ["V-A"] * 3,
                "reference": ["REF-A"] * 3,
            }
        )

        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))
        selection = artifact["coverage"]["top_pair_selection"]

        assert len(artifact["top_pairs"]) == artifact["retained_pairs"]
        assert selection["strategy"] == "complete_measurement_population"
        assert selection["top_n_cap_applied"] is False


class TestEvidenceDiversityRetention:
    def _record(
        self,
        *,
        left_pos: int,
        right_pos: int,
        score: float,
        same_partner: bool,
        reference_similarity: float,
        text_similarity: float,
    ) -> dict:
        return {
            "left_pos": left_pos,
            "right_pos": right_pos,
            "pair_score": score,
            "rule_id": "L2-03a",
            "features": {
                "same_account": True,
                "same_partner": same_partner,
                "amount_similarity": 1.0,
                "reference_similarity": reference_similarity,
                "text_similarity": text_similarity,
            },
        }

    def test_evidence_diversity_selector_limits_dense_document_pair_monopoly(self) -> None:
        df = pd.DataFrame({"document_id": [f"DOC-{idx}" for idx in range(8)]})
        records = [
            self._record(
                left_pos=0,
                right_pos=1,
                score=1.0,
                same_partner=True,
                reference_similarity=0.95,
                text_similarity=0.95,
            )
            for _ in range(5)
        ]
        records.extend(
            [
                self._record(
                    left_pos=2,
                    right_pos=3,
                    score=0.98,
                    same_partner=True,
                    reference_similarity=0.95,
                    text_similarity=0.95,
                ),
                self._record(
                    left_pos=4,
                    right_pos=5,
                    score=0.97,
                    same_partner=True,
                    reference_similarity=0.95,
                    text_similarity=0.95,
                ),
            ]
        )

        selected, diagnostics = _select_top_pairs_with_evidence_diversity(records, df, top_n=3)
        doc_pairs = {
            tuple(
                sorted(
                    (
                        df["document_id"].iat[pair["left_pos"]],
                        df["document_id"].iat[pair["right_pos"]],
                    )
                )
            )
            for pair in selected
        }

        assert diagnostics["strategy"] == "evidence_diversity"
        assert len(doc_pairs) == 3
        assert diagnostics["truth_label_used"] is False

    def test_evidence_diversity_selector_prioritizes_case_grade_tier_over_weak(self) -> None:
        df = pd.DataFrame({"document_id": ["DOC-1", "DOC-2", "DOC-3", "DOC-4"]})
        weak_high_score = self._record(
            left_pos=0,
            right_pos=1,
            score=1.0,
            same_partner=False,
            reference_similarity=1.0,
            text_similarity=1.0,
        )
        strong_lower_score = self._record(
            left_pos=2,
            right_pos=3,
            score=0.9,
            same_partner=True,
            reference_similarity=0.95,
            text_similarity=0.95,
        )

        selected, diagnostics = _select_top_pairs_with_evidence_diversity(
            [weak_high_score, strong_lower_score],
            df,
            top_n=1,
        )

        assert selected == [strong_lower_score]
        assert diagnostics["weak_pair_count"] == 0

    def test_evidence_diversity_selector_keeps_high_score_when_evidence_tie(self) -> None:
        df = pd.DataFrame({"document_id": ["DOC-1", "DOC-2", "DOC-3", "DOC-4"]})
        lower = self._record(
            left_pos=0,
            right_pos=1,
            score=0.8,
            same_partner=True,
            reference_similarity=0.95,
            text_similarity=0.95,
        )
        higher = self._record(
            left_pos=2,
            right_pos=3,
            score=0.9,
            same_partner=True,
            reference_similarity=0.95,
            text_similarity=0.95,
        )

        selected, _diagnostics = _select_top_pairs_with_evidence_diversity(
            [lower, higher],
            df,
            top_n=1,
        )

        assert selected == [higher]

    def test_evidence_diversity_strategy_is_flag_gated(self) -> None:
        settings = AuditSettings(
            duplicate_pair_artifact_selection_strategy="evidence_diversity",
            duplicate_pair_artifact_top_n=2,
        )
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-2", "DOC-3"],
                "gl_account": [1000, 1000, 1000],
                "debit_amount": [500.0, 500.0, 500.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01"] * 3),
                "line_text": ["반복"] * 3,
                "trading_partner": ["V-A"] * 3,
                "reference": ["REF-A"] * 3,
            }
        )

        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))

        assert artifact["coverage"]["top_pair_selection"]["strategy"] == (
            "complete_measurement_population"
        )


class TestRuleBalancedEvidenceRetention:
    def _record(
        self,
        *,
        rule_id: str,
        left_pos: int,
        right_pos: int,
        score: float,
        same_partner: bool = True,
        reference_similarity: float = 0.95,
        text_similarity: float = 0.95,
    ) -> dict:
        return {
            "left_pos": left_pos,
            "right_pos": right_pos,
            "pair_score": score,
            "rule_id": rule_id,
            "features": {
                "same_account": True,
                "same_partner": same_partner,
                "amount_similarity": 1.0,
                "reference_similarity": reference_similarity,
                "text_similarity": text_similarity,
            },
        }

    def test_rule_balanced_selector_prevents_exact_rule_monopoly(self) -> None:
        df = pd.DataFrame({"document_id": [f"DOC-{idx}" for idx in range(20)]})
        records = [
            self._record(rule_id="L2-03a", left_pos=0, right_pos=1, score=1.0)
            for _ in range(10)
        ]
        records.extend(
            [
                self._record(rule_id="L2-03d", left_pos=2, right_pos=3, score=0.4),
                self._record(rule_id="L2-03d", left_pos=4, right_pos=5, score=0.3),
            ]
        )

        selected, diagnostics = _select_top_pairs_with_rule_balanced_evidence(
            records,
            df,
            top_n=4,
        )

        selected_rules = [record["rule_id"] for record in selected]
        assert diagnostics["strategy"] == "rule_balanced_evidence"
        assert diagnostics["truth_label_used"] is False
        assert selected_rules.count("L2-03d") == 2
        assert selected_rules.count("L2-03a") == 2

    def test_default_strategy_is_rule_balanced_evidence(self) -> None:
        settings = AuditSettings(duplicate_pair_artifact_top_n=2)
        df = pd.DataFrame(
            {
                "document_id": ["DOC-1", "DOC-2", "DOC-3"],
                "gl_account": [1000, 1000, 1000],
                "debit_amount": [500.0, 500.0, 500.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-03-01"] * 3),
                "line_text": ["반복"] * 3,
                "trading_partner": ["V-A"] * 3,
                "reference": ["REF-A"] * 3,
            }
        )

        artifact = _pair_artifact(DuplicateDetector(settings).detect(df))

        assert artifact["coverage"]["top_pair_selection"]["strategy"] == (
            "complete_measurement_population"
        )
