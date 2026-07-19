"""candidate_builder — 스펙 §6.1 표 6 케이스 + 회귀.

(1) 룰만 히트 / (2) ML만 히트 / (3) 둘 다 히트 /
(4) N=0 빈 큐 / (5) peer_context 결측 / (6) 후보 선정 우선순위
"""

from __future__ import annotations

import pytest

from src.llm.review_narrator.candidate_builder import build_candidates
from src.llm.review_narrator.sanitizer import Sanitizer


@pytest.fixture()
def rn_san() -> Sanitizer:
    return Sanitizer(salt="builder-test")


@pytest.fixture()
def rn_journal_metas() -> dict[str, dict]:
    """3개 journal의 메타."""
    return {
        "JE-001": {
            "batch_id": "B-2026-Q1",
            "posting_date": "2026-03-31",
            "period": "2026-03",
            "process": "R2R",
            "amount": 5_200_000_000,
            "gl_account": "1100",
            "counterparty": "거래처A",
            "approver": "홍길동",
            "description": "기말 결산 분개",
        },
        "JE-002": {
            "batch_id": "B-2026-Q1",
            "posting_date": "2026-02-15",
            "period": "2026-02",
            "process": "P2P",
            "amount": 35_000_000,
            "gl_account": "5200",
            "counterparty": "거래처B",
            "approver": "김감사",
            "description": "정상 매입",
        },
        "JE-003": {
            "batch_id": "B-2026-Q1",
            "posting_date": "2026-01-20",
            "period": "2026-01",
            "process": "O2C",
            "amount": 800_000,
            "gl_account": "4000",
            "counterparty": "고객C",
            "approver": "이대리",
            "description": "소액 매출",
        },
    }


# ── (1) 룰만 히트 ──


class TestRuleOnly:
    def test_case_only_no_ml(self, rn_san, rn_journal_metas):
        phase1_cases = [
            {
                "case_id": "CASE-01",
                "priority_score": 0.92,
                "journal_id": "JE-001",
                "rule_hits": [
                    {
                        "rule_id": "L1-01",
                        "severity": 3,
                        "score": 0.9,
                        "fields_triggered": ["amount", "approver"],
                        "rule_meta_ref": "L1",
                    },
                ],
            },
        ]
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores={},
            peer_contexts={},
            sanitizer=rn_san,
        )
        assert len(result) == 1
        cand = result[0]
        assert cand["candidate_id"] == "CAND-CASE-01"
        assert cand["journal_ref"]["journal_id"] == "JE-001"
        assert cand["journal_ref"]["process"] == "R2R"
        assert len(cand["rule_hits"]) == 1
        assert cand["rule_hits"][0]["rule_id"] == "L1-01"
        assert cand["ml_scores"] == []
        assert cand["journal_meta"]["amount_bucket"] == "10억~100억"


# ── (2) ML만 히트 ──


class TestMLOnly:
    def test_ml_only_high_percentile_included(self, rn_san, rn_journal_metas):
        ml_scores = {
            "JE-002": [
                {
                    "model_id": "vae_v1",
                    "score": 0.85,
                    "percentile": 0.995,
                    "top_features": [
                        {"feature_id": "amount_zscore", "value": 3.1, "contribution": 0.6}
                    ],
                },
            ],
        }
        result = build_candidates(
            phase1_cases=[],
            journal_metas=rn_journal_metas,
            ml_scores=ml_scores,
            peer_contexts={},
            sanitizer=rn_san,
        )
        assert len(result) == 1
        cand = result[0]
        assert cand["candidate_id"] == "CAND-ML-JE-002"
        assert cand["rule_hits"] == []
        assert len(cand["ml_scores"]) == 1
        assert cand["ml_scores"][0]["model_id"] == "vae_v1"
        assert cand["ml_scores"][0]["percentile"] == 0.995

    def test_ml_low_percentile_excluded(self, rn_san, rn_journal_metas):
        ml_scores = {
            "JE-002": [{"model_id": "vae_v1", "score": 0.2, "percentile": 0.5, "top_features": []}],
        }
        result = build_candidates(
            phase1_cases=[],
            journal_metas=rn_journal_metas,
            ml_scores=ml_scores,
            peer_contexts={},
            sanitizer=rn_san,
        )
        assert result == []

    def test_hold_out_scenario_journal_is_still_available_to_narrator(self, rn_san):
        metas = {
            "JE-HOLDOUT": {
                "batch_id": "B-2026-Q1",
                "posting_date": "2026-03-31",
                "period": "2026-03",
                "process": "R2R",
                "amount": 50_000_000,
                "gl_account": "5200",
                "counterparty": "거래처H",
                "approver": "승인자H",
                "description": "hold-out 평가 전표",
                "mutation_type": "approval_sod_bypass",
            }
        }
        ml_scores = {
            "JE-HOLDOUT": [
                {"model_id": "vae_v1", "score": 0.91, "percentile": 0.995, "top_features": []}
            ]
        }

        result = build_candidates(
            phase1_cases=[],
            journal_metas=metas,
            ml_scores=ml_scores,
            peer_contexts={},
            sanitizer=rn_san,
        )

        assert [candidate["journal_ref"]["journal_id"] for candidate in result] == [
            "JE-HOLDOUT"
        ]
        assert result[0]["ml_scores"][0]["model_id"] == "vae_v1"


# ── (3) 둘 다 히트 ──


class TestBothHit:
    def test_case_journal_includes_ml_scores(self, rn_san, rn_journal_metas):
        """case에 포함된 journal에 ML 점수가 있으면 함께 채워야 함."""
        phase1_cases = [
            {
                "case_id": "CASE-A",
                "priority_score": 0.9,
                "journal_id": "JE-001",
                "rule_hits": [
                    {
                        "rule_id": "L1-01",
                        "severity": 2,
                        "score": 0.7,
                        "fields_triggered": [],
                        "rule_meta_ref": "",
                    }
                ],
            },
        ]
        ml_scores = {
            "JE-001": [
                {
                    "model_id": "iforest_v1",
                    "score": 0.8,
                    "percentile": 0.97,
                    "top_features": [
                        {"feature_id": "amount_zscore", "value": 4.2, "contribution": 0.5}
                    ],
                }
            ],
        }
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores,
            peer_contexts={},
            sanitizer=rn_san,
        )
        assert len(result) == 1
        cand = result[0]
        assert cand["rule_hits"][0]["rule_id"] == "L1-01"
        assert len(cand["ml_scores"]) == 1
        assert cand["ml_scores"][0]["model_id"] == "iforest_v1"


# ── (4) 빈 큐 ──


class TestEmptyInputs:
    def test_n_zero_returns_empty(self, rn_san, rn_journal_metas):
        phase1_cases = [
            {"case_id": "C", "priority_score": 0.9, "journal_id": "JE-001", "rule_hits": []},
        ]
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores={},
            peer_contexts={},
            n=0,
            sanitizer=rn_san,
        )
        assert result == []

    def test_no_cases_no_ml_returns_empty(self, rn_san):
        assert build_candidates([], {}, {}, {}, sanitizer=rn_san) == []

    def test_negative_n_returns_empty(self, rn_san):
        assert build_candidates([], {}, {}, {}, n=-5, sanitizer=rn_san) == []


# ── (5) peer_context 결측 ──


class TestPeerContextMissing:
    def test_missing_peer_context_defaults_to_empty_dict(self, rn_san, rn_journal_metas):
        phase1_cases = [
            {"case_id": "C", "priority_score": 0.9, "journal_id": "JE-001", "rule_hits": []},
        ]
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores={},
            peer_contexts={},  # 비어있음
            sanitizer=rn_san,
        )
        assert result[0]["peer_context"] == {}

    def test_present_peer_context_attached(self, rn_san, rn_journal_metas):
        phase1_cases = [
            {"case_id": "C", "priority_score": 0.9, "journal_id": "JE-001", "rule_hits": []},
        ]
        peer = {"median": 1_000_000, "p95": 50_000_000}
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores={},
            peer_contexts={"JE-001": peer},
            sanitizer=rn_san,
        )
        assert result[0]["peer_context"] == peer


# ── (6) 후보 선정 우선순위 ──


class TestSelectionPriority:
    def test_sorted_by_priority_score_desc(self, rn_san, rn_journal_metas):
        phase1_cases = [
            {"case_id": "LOW", "priority_score": 0.3, "journal_id": "JE-003", "rule_hits": []},
            {"case_id": "HIGH", "priority_score": 0.95, "journal_id": "JE-001", "rule_hits": []},
            {"case_id": "MID", "priority_score": 0.7, "journal_id": "JE-002", "rule_hits": []},
        ]
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores={},
            peer_contexts={},
            sanitizer=rn_san,
        )
        candidate_ids = [c["candidate_id"] for c in result]
        assert candidate_ids == ["CAND-HIGH", "CAND-MID", "CAND-LOW"]

    def test_n_truncates_low_priority(self, rn_san, rn_journal_metas):
        phase1_cases = [
            {"case_id": "A", "priority_score": 0.9, "journal_id": "JE-001", "rule_hits": []},
            {"case_id": "B", "priority_score": 0.5, "journal_id": "JE-002", "rule_hits": []},
            {"case_id": "C", "priority_score": 0.2, "journal_id": "JE-003", "rule_hits": []},
        ]
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores={},
            peer_contexts={},
            n=2,
            sanitizer=rn_san,
        )
        assert len(result) == 2
        assert [c["candidate_id"] for c in result] == ["CAND-A", "CAND-B"]

    def test_hard_limit_clamps_n(self, rn_san):
        """n > hard_limit 시 hard_limit로 클램프."""
        # 많은 case를 생성 (200개)
        metas = {
            f"JE-{i:04d}": {
                "amount": 1_000_000,
                "gl_account": "1",
                "counterparty": "X",
                "approver": "Y",
                "description": "z",
                "batch_id": "B",
                "posting_date": "2026-01-01",
                "period": "2026-01",
                "process": "P",
            }
            for i in range(200)
        }
        cases = [
            {
                "case_id": f"C{i:04d}",
                "priority_score": 1.0 - i / 1000,
                "journal_id": f"JE-{i:04d}",
                "rule_hits": [],
            }
            for i in range(200)
        ]
        result = build_candidates(
            cases,
            metas,
            ml_scores={},
            peer_contexts={},
            n=500,
            hard_limit=50,
            sanitizer=rn_san,
        )
        assert len(result) == 50

    def test_ml_only_fills_remaining_slots(self, rn_san, rn_journal_metas):
        """case가 N개 미만일 때 ML 단독 후보로 빈 슬롯 채움."""
        phase1_cases = [
            {"case_id": "C1", "priority_score": 0.9, "journal_id": "JE-001", "rule_hits": []},
        ]
        ml_scores = {
            "JE-002": [
                {"model_id": "vae_v1", "score": 0.8, "percentile": 0.995, "top_features": []}
            ],
            "JE-003": [
                {"model_id": "vae_v1", "score": 0.7, "percentile": 0.99, "top_features": []}
            ],
        }
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores,
            peer_contexts={},
            n=3,
            sanitizer=rn_san,
        )
        assert len(result) == 3
        assert result[0]["candidate_id"] == "CAND-C1"
        # ML-only는 percentile 내림차순 정렬
        assert result[1]["candidate_id"] == "CAND-ML-JE-002"
        assert result[2]["candidate_id"] == "CAND-ML-JE-003"

    def test_ml_only_excludes_case_journals(self, rn_san, rn_journal_metas):
        """case에 이미 포함된 journal은 ML-only로 중복 포함되지 않음."""
        phase1_cases = [
            {"case_id": "C1", "priority_score": 0.9, "journal_id": "JE-001", "rule_hits": []},
        ]
        ml_scores = {
            "JE-001": [
                {"model_id": "vae_v1", "score": 0.99, "percentile": 0.999, "top_features": []}
            ],  # case에 포함 — 보충 대상 아님
            "JE-002": [
                {"model_id": "vae_v1", "score": 0.8, "percentile": 0.995, "top_features": []}
            ],
        }
        result = build_candidates(
            phase1_cases,
            rn_journal_metas,
            ml_scores,
            peer_contexts={},
            n=5,
            sanitizer=rn_san,
        )
        candidate_ids = [c["candidate_id"] for c in result]
        assert "CAND-C1" in candidate_ids
        assert "CAND-ML-JE-002" in candidate_ids
        assert "CAND-ML-JE-001" not in candidate_ids
