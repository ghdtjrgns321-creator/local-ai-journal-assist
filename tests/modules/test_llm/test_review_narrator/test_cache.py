"""review_narratives 캐시 UPSERT — 스펙 §6.1 cache 표 케이스.

(1) 신규 UPSERT
(2) 동일 input_hash 재사용 (hit)
(3) input 변경 시 재호출 (UPDATE)
"""

from __future__ import annotations

import duckdb
import pytest

from src.db.schema import initialize_schema
from src.llm.review_narrator.cache import (
    compute_input_hash,
    read_audit_decision,
    read_narrative,
    update_audit_decision,
    upsert_narrative,
)
from src.llm.review_narrator.citation_validator import validate_citations
from src.llm.review_narrator.models import ReviewNarrative
from src.llm.review_narrator.narrator import NarratorResult


@pytest.fixture()
def rn_db_conn():
    """schema 초기화된 in-memory DuckDB."""
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def rn_narrator_result(rn_candidate) -> NarratorResult:
    """캐시 저장용 NarratorResult fixture."""
    narrative = ReviewNarrative(
        candidate_id=rn_candidate["candidate_id"],
        priority_rank=1,
        priority_score=0.92,
        summary="cache test summary",
        reasoning=[],
        suggested_actions=[],
        confidence="high",
    )
    citation = validate_citations(narrative, {"L1-01"}, {"amount_zscore"}, {"JE-2025-0001"})
    # 빈 reasoning이므로 강등되지만 cache 테스트엔 무관
    return NarratorResult(
        narrative=citation.narrative,
        citation_result=citation,
        model_tier="reasoning",
        call_status="ok",
    )


# ── compute_input_hash 결정성 ──


class TestComputeInputHash:
    def test_deterministic(self, rn_candidate):
        h1 = compute_input_hash(rn_candidate)
        h2 = compute_input_hash(rn_candidate)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_key_order_independent(self):
        a = {"x": 1, "y": 2}
        b = {"y": 2, "x": 1}
        assert compute_input_hash(a) == compute_input_hash(b)

    def test_changes_with_content(self, rn_candidate):
        h1 = compute_input_hash(rn_candidate)
        mutated = {**rn_candidate, "candidate_id": "CAND-DIFFERENT"}
        h2 = compute_input_hash(mutated)
        assert h1 != h2


# ── (1) 신규 UPSERT ──


class TestUpsertNew:
    def test_inserts_new_row(self, rn_db_conn, rn_candidate, rn_narrator_result):
        result = upsert_narrative(
            rn_db_conn, rn_candidate, rn_narrator_result, batch_id="B-2026-Q1"
        )
        assert result["created"] is True
        assert result["reused"] is False
        assert result["updated"] is False
        assert len(result["input_hash"]) == 64

        # DB에 1건 존재 확인
        count = rn_db_conn.execute("SELECT COUNT(*) FROM review_narratives").fetchone()[0]
        assert count == 1

    def test_read_back_matches(self, rn_db_conn, rn_candidate, rn_narrator_result):
        upsert_narrative(rn_db_conn, rn_candidate, rn_narrator_result, batch_id="B-2026-Q1")
        row = read_narrative(rn_db_conn, rn_candidate["candidate_id"])
        assert row is not None
        assert row["candidate_id"] == rn_candidate["candidate_id"]
        assert row["batch_id"] == "B-2026-Q1"
        assert row["journal_id"] == "JE-2025-0001"
        assert row["model_tier"] == "reasoning"
        assert row["narrative_json"]["summary"] == "cache test summary"

    def test_records_tokens_and_cost(self, rn_db_conn, rn_candidate, rn_narrator_result):
        upsert_narrative(
            rn_db_conn,
            rn_candidate,
            rn_narrator_result,
            batch_id="B",
            prompt_tokens=120,
            completion_tokens=80,
            cost_usd=0.0042,
        )
        row = read_narrative(rn_db_conn, rn_candidate["candidate_id"])
        assert row["prompt_tokens"] == 120
        assert row["completion_tokens"] == 80
        assert row["cost_usd"] == pytest.approx(0.0042)


# ── (2) 동일 input_hash 재사용 ──


class TestUpsertReuse:
    def test_same_hash_returns_reused(self, rn_db_conn, rn_candidate, rn_narrator_result):
        first = upsert_narrative(rn_db_conn, rn_candidate, rn_narrator_result, batch_id="B")
        second = upsert_narrative(rn_db_conn, rn_candidate, rn_narrator_result, batch_id="B")
        assert first["created"] is True
        assert second["reused"] is True
        assert second["created"] is False
        assert second["updated"] is False
        assert first["input_hash"] == second["input_hash"]

        # row 수 변동 없음
        count = rn_db_conn.execute("SELECT COUNT(*) FROM review_narratives").fetchone()[0]
        assert count == 1


# ── (3) input 변경 시 재호출 (UPDATE) ──


class TestUpsertUpdate:
    def test_different_hash_triggers_update(self, rn_db_conn, rn_candidate, rn_narrator_result):
        upsert_narrative(rn_db_conn, rn_candidate, rn_narrator_result, batch_id="B")
        # candidate 내용 변경 → hash 다름
        mutated = {
            **rn_candidate,
            "journal_meta": {**rn_candidate["journal_meta"], "amount_bucket": "1억~10억"},
        }
        result = upsert_narrative(rn_db_conn, mutated, rn_narrator_result, batch_id="B")
        assert result["updated"] is True
        assert result["created"] is False
        assert result["reused"] is False

        # row 수는 1 유지 (UPDATE)
        count = rn_db_conn.execute("SELECT COUNT(*) FROM review_narratives").fetchone()[0]
        assert count == 1


# ── read_narrative 안전성 ──


class TestReadNarrative:
    def test_missing_returns_none(self, rn_db_conn):
        assert read_narrative(rn_db_conn, "DOES-NOT-EXIST") is None


# ── invalid input 방어 ──


class TestUpsertGuard:
    def test_missing_candidate_id_raises(self, rn_db_conn, rn_narrator_result):
        with pytest.raises(ValueError, match="candidate_id"):
            upsert_narrative(rn_db_conn, {}, rn_narrator_result, batch_id="B")


# ── Sprint E2: update_audit_decision UPSERT 회귀 ─────────────


class TestUpdateAuditDecision:
    """감사인 분류·메모 저장 UPDATE 헬퍼 (Sprint E2)."""

    def _seed(self, conn, candidate, narrator_result):
        """공통 — review_narratives에 candidate row 1건 시드."""
        upsert_narrative(conn, candidate, narrator_result, batch_id="B-2026-Q1")

    def test_first_decision_persists_all_four_columns(
        self, rn_db_conn, rn_candidate, rn_narrator_result
    ):
        self._seed(rn_db_conn, rn_candidate, rn_narrator_result)
        result = update_audit_decision(
            rn_db_conn,
            candidate_id=rn_candidate["candidate_id"],
            decision="confirmed_high_risk",
            note="원인 증빙 + 임원 확인",
            user="auditor@example.com",
        )
        assert result["updated"] is True
        assert result["decision"] == "confirmed_high_risk"
        assert "reviewed_at" in result and len(result["reviewed_at"]) > 0

        stored = read_audit_decision(rn_db_conn, rn_candidate["candidate_id"])
        assert stored is not None
        assert stored["audit_decision"] == "confirmed_high_risk"
        assert stored["audit_note"] == "원인 증빙 + 임원 확인"
        assert stored["reviewed_by"] == "auditor@example.com"
        assert stored["reviewed_at"] is not None

    def test_overwrites_previous_decision(self, rn_db_conn, rn_candidate, rn_narrator_result):
        """동일 candidate에 분류 재지정 시 4컬럼 모두 새 값으로 덮어쓴다."""
        self._seed(rn_db_conn, rn_candidate, rn_narrator_result)
        update_audit_decision(
            rn_db_conn,
            candidate_id=rn_candidate["candidate_id"],
            decision="under_review",
            note="추가 확인 필요",
            user="auditor_a",
        )
        update_audit_decision(
            rn_db_conn,
            candidate_id=rn_candidate["candidate_id"],
            decision="false_positive",
            note="정상 결산 거래",
            user="auditor_b",
        )
        stored = read_audit_decision(rn_db_conn, rn_candidate["candidate_id"])
        assert stored is not None
        assert stored["audit_decision"] == "false_positive"
        assert stored["audit_note"] == "정상 결산 거래"
        assert stored["reviewed_by"] == "auditor_b"

    def test_clear_decision_with_none(self, rn_db_conn, rn_candidate, rn_narrator_result):
        """decision=None은 분류 해제 (NULL 저장)."""
        self._seed(rn_db_conn, rn_candidate, rn_narrator_result)
        update_audit_decision(
            rn_db_conn,
            candidate_id=rn_candidate["candidate_id"],
            decision="under_review",
            note="검토 중",
            user="auditor_a",
        )
        update_audit_decision(
            rn_db_conn,
            candidate_id=rn_candidate["candidate_id"],
            decision=None,
            note=None,
            user="auditor_a",
        )
        stored = read_audit_decision(rn_db_conn, rn_candidate["candidate_id"])
        assert stored is not None
        assert stored["audit_decision"] is None
        assert stored["audit_note"] is None

    def test_does_not_touch_narrative_columns(self, rn_db_conn, rn_candidate, rn_narrator_result):
        """분류 저장이 narrative_json·input_hash·model_tier 등 LLM 응답 컬럼을 변경하지 않음."""
        self._seed(rn_db_conn, rn_candidate, rn_narrator_result)
        before = read_narrative(rn_db_conn, rn_candidate["candidate_id"])
        assert before is not None
        update_audit_decision(
            rn_db_conn,
            candidate_id=rn_candidate["candidate_id"],
            decision="normal_exception",
            note="정상 예외",
            user="auditor_a",
        )
        after = read_narrative(rn_db_conn, rn_candidate["candidate_id"])
        assert after is not None
        assert before["narrative_json"] == after["narrative_json"]
        assert before["input_hash"] == after["input_hash"]
        assert before["model_tier"] == after["model_tier"]
        assert before["confidence"] == after["confidence"]

    def test_invalid_decision_raises(self, rn_db_conn, rn_candidate, rn_narrator_result):
        self._seed(rn_db_conn, rn_candidate, rn_narrator_result)
        with pytest.raises(ValueError, match="invalid audit_decision"):
            update_audit_decision(
                rn_db_conn,
                candidate_id=rn_candidate["candidate_id"],
                decision="approved",  # type: ignore[arg-type]
                note=None,
                user="auditor_a",
            )

    def test_empty_user_raises(self, rn_db_conn, rn_candidate, rn_narrator_result):
        self._seed(rn_db_conn, rn_candidate, rn_narrator_result)
        with pytest.raises(ValueError, match="reviewed_by"):
            update_audit_decision(
                rn_db_conn,
                candidate_id=rn_candidate["candidate_id"],
                decision="under_review",
                note="x",
                user="",
            )

    def test_missing_candidate_raises_keyerror(self, rn_db_conn):
        with pytest.raises(KeyError, match="candidate_id not found"):
            update_audit_decision(
                rn_db_conn,
                candidate_id="CAND-NONEXISTENT",
                decision="under_review",
                note=None,
                user="auditor_a",
            )


class TestReadAuditDecision:
    def test_returns_none_when_row_missing(self, rn_db_conn):
        assert read_audit_decision(rn_db_conn, "MISSING") is None

    def test_returns_nulls_before_any_decision(self, rn_db_conn, rn_candidate, rn_narrator_result):
        upsert_narrative(rn_db_conn, rn_candidate, rn_narrator_result, batch_id="B")
        stored = read_audit_decision(rn_db_conn, rn_candidate["candidate_id"])
        assert stored == {
            "audit_decision": None,
            "audit_note": None,
            "reviewed_by": None,
            "reviewed_at": None,
        }
