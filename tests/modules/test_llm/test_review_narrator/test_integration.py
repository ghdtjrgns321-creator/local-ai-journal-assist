"""Review Narrator E2E 통합 테스트 (mock LLM).

스펙 §흐름:
    Candidate Builder → Sanitizer → Narrator(mock) → Citation Validator → Cache → DB read

본 테스트는 실제 OpenAI 호출 없이 mock ChatClient로 회왕복 전체를 검증한다.
회귀 항목:
- PII 비식별이 candidate dict에 반영되어 LLM 입력에 도달
- 캐시 hit/miss 동작
- citation 강등이 cache citation_valid 플래그에 반영
"""

from __future__ import annotations

import json

import duckdb
import pytest

from src.db.schema import initialize_schema
from src.llm.review_narrator.cache import read_narrative, upsert_narrative
from src.llm.review_narrator.candidate_builder import build_candidates
from src.llm.review_narrator.narrator import narrate
from src.llm.review_narrator.sanitizer import Sanitizer


@pytest.fixture()
def rn_int_db():
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _make_llm_response(candidate: dict, confidence: str = "high") -> str:
    """candidate에 맞춰 valid한 LLM 응답 JSON 생성."""
    rule_id = candidate["rule_hits"][0]["rule_id"] if candidate["rule_hits"] else ""
    feature_id = ""
    model_id = ""
    if candidate["ml_scores"]:
        ml = candidate["ml_scores"][0]
        model_id = ml["model_id"]
        if ml.get("top_features"):
            feature_id = ml["top_features"][0]["feature_id"]
    journal_id = candidate["journal_ref"]["journal_id"]
    evidence = []
    if rule_id:
        evidence.append(
            {
                "type": "rule_hit",
                "rule_id": rule_id,
                "model_id": "",
                "feature_id": "",
                "journal_id": "",
                "line_no": 0,
            }
        )
    if feature_id:
        evidence.append(
            {
                "type": "ml_feature",
                "rule_id": "",
                "model_id": model_id,
                "feature_id": feature_id,
                "journal_id": "",
                "line_no": 0,
            }
        )
    evidence.append(
        {
            "type": "row",
            "rule_id": "",
            "model_id": "",
            "feature_id": "",
            "journal_id": journal_id,
            "line_no": 1,
        }
    )
    payload = {
        "candidate_id": candidate["candidate_id"],
        "priority_rank": 1,
        "priority_score": 0.9,
        "summary": "E2E mock 결과",
        "reasoning": [{"claim": "근거 종합", "evidence": evidence}],
        "suggested_actions": [
            {"action_type": "request_evidence", "description": "증빙 요청", "target": journal_id},
        ],
        "confidence": confidence,
    }
    return json.dumps(payload, ensure_ascii=False)


def _make_journal_metas() -> dict[str, dict]:
    return {
        "JE-001": {
            "batch_id": "B-INT",
            "posting_date": "2026-03-31",
            "period": "2026-03",
            "process": "R2R",
            "amount": 5_200_000_000,
            "gl_account": "1100",
            "counterparty": "주식회사 ABC상사",
            "approver": "홍길동",
            "description": "사업자번호 123-45-67890 정상 매출",
        },
        "JE-002": {
            "batch_id": "B-INT",
            "posting_date": "2026-02-15",
            "period": "2026-02",
            "process": "P2P",
            "amount": 35_000_000,
            "gl_account": "5200",
            "counterparty": "거래처B",
            "approver": "김감사",
            "description": "정상 매입",
        },
    }


def _make_phase1_cases() -> list[dict]:
    return [
        {
            "case_id": "CASE-1",
            "priority_score": 0.95,
            "journal_id": "JE-001",
            "rule_hits": [
                {
                    "rule_id": "L1-01",
                    "severity": 3,
                    "score": 0.9,
                    "fields_triggered": ["amount"],
                    "rule_meta_ref": "L1",
                }
            ],
        },
        {
            "case_id": "CASE-2",
            "priority_score": 0.7,
            "journal_id": "JE-002",
            "rule_hits": [
                {
                    "rule_id": "L2-04",
                    "severity": 2,
                    "score": 0.6,
                    "fields_triggered": [],
                    "rule_meta_ref": "L2",
                }
            ],
        },
    ]


def _make_ml_scores() -> dict[str, list[dict]]:
    return {
        "JE-001": [
            {
                "model_id": "vae_v1",
                "score": 0.85,
                "percentile": 0.99,
                "top_features": [
                    {"feature_id": "amount_zscore", "value": 3.1, "contribution": 0.6}
                ],
            }
        ],
    }


# ── E2E 회왕복 ──


class TestEndToEnd:
    def test_full_roundtrip(self, rn_int_db, rn_chat_client_cls):
        # 1) Builder + Sanitizer
        sanitizer = Sanitizer(salt="integration-v1")
        candidates = build_candidates(
            phase1_cases=_make_phase1_cases(),
            journal_metas=_make_journal_metas(),
            ml_scores=_make_ml_scores(),
            peer_contexts={"JE-001": {"median": 100_000_000, "p95": 1_000_000_000}},
            sanitizer=sanitizer,
            n=20,
        )
        assert len(candidates) == 2

        # 2) Sanitizer 결과 확인: PII가 평문으로 노출되지 않음
        first = candidates[0]
        assert "주식회사 ABC상사" not in json.dumps(first, ensure_ascii=False)
        assert "홍길동" not in json.dumps(first, ensure_ascii=False)
        assert "123-45-67890" not in json.dumps(first, ensure_ascii=False)
        assert first["journal_meta"]["amount_bucket"] == "10억~100억"

        # 3) Narrator (mock LLM)
        results = []
        for cand in candidates:
            reasoning = rn_chat_client_cls([_make_llm_response(cand)])
            light = rn_chat_client_cls([])
            result = narrate(cand, reasoning, light)
            assert result.call_status == "ok"
            assert result.citation_result.is_valid is True
            results.append((cand, result))

        # 4) Cache (UPSERT)
        for cand, res in results:
            outcome = upsert_narrative(
                rn_int_db,
                cand,
                res,
                batch_id="B-INT",
                prompt_tokens=100,
                completion_tokens=60,
                cost_usd=0.003,
            )
            assert outcome["created"] is True

        # 5) DB read 회왕복
        for cand, _ in results:
            row = read_narrative(rn_int_db, cand["candidate_id"])
            assert row is not None
            assert row["batch_id"] == "B-INT"
            assert row["citation_valid"] is True
            assert row["narrative_json"]["summary"] == "E2E mock 결과"

        # 6) 동일 입력 재호출 → 캐시 hit
        cand, res = results[0]
        outcome2 = upsert_narrative(rn_int_db, cand, res, batch_id="B-INT")
        assert outcome2["reused"] is True

    def test_sanitizer_omitted_uses_default(self, rn_int_db, rn_chat_client_cls):
        """sanitizer 인자 미지정 시 기본 Sanitizer 사용 — 빈 candidate metas로도 안전."""
        candidates = build_candidates(
            phase1_cases=_make_phase1_cases(),
            journal_metas=_make_journal_metas(),
            ml_scores={},
            peer_contexts={},
            n=20,
        )
        assert len(candidates) == 2
        for cand in candidates:
            # description에 사업자번호 있던 케이스도 마스킹되어 평문 없음
            assert "123-45-67890" not in json.dumps(cand, ensure_ascii=False)

    def test_citation_downgrade_persists_to_db(self, rn_int_db, rn_chat_client_cls):
        """citation_validator 강등(False)이 cache citation_valid 컬럼에 기록되는지."""
        candidates = build_candidates(
            phase1_cases=_make_phase1_cases(),
            journal_metas=_make_journal_metas(),
            ml_scores=_make_ml_scores(),
            peer_contexts={},
            sanitizer=Sanitizer(salt="ds-v1"),
            n=1,
        )
        cand = candidates[0]
        # LLM이 존재하지 않는 rule_id를 응답하도록 만든다
        bad_payload = {
            "candidate_id": cand["candidate_id"],
            "priority_rank": 1,
            "priority_score": 0.9,
            "summary": "환각 rule_id 인용",
            "reasoning": [
                {
                    "claim": "x",
                    "evidence": [
                        {
                            "type": "rule_hit",
                            "rule_id": "GHOST-XYZ",
                            "model_id": "",
                            "feature_id": "",
                            "journal_id": "",
                            "line_no": 0,
                        },
                    ],
                }
            ],
            "suggested_actions": [],
            "confidence": "high",
        }
        reasoning = rn_chat_client_cls([json.dumps(bad_payload, ensure_ascii=False)])
        light = rn_chat_client_cls([])
        result = narrate(cand, reasoning, light)
        assert result.citation_result.is_valid is False
        assert result.narrative.confidence == "low"

        upsert_narrative(rn_int_db, cand, result, batch_id="B-INT")
        row = read_narrative(rn_int_db, cand["candidate_id"])
        assert row["citation_valid"] is False
        assert row["confidence"] == "low"

    def test_llm_failure_persists_low_confidence(self, rn_int_db, rn_chat_client_cls):
        """LLM 2회 모두 실패 → cache에 confidence=low + model_tier=failed 저장."""
        candidates = build_candidates(
            phase1_cases=_make_phase1_cases(),
            journal_metas=_make_journal_metas(),
            ml_scores={},
            peer_contexts={},
            n=1,
        )
        cand = candidates[0]
        reasoning = rn_chat_client_cls([], raise_on_call=True)
        light = rn_chat_client_cls([], raise_on_call=True)
        result = narrate(cand, reasoning, light)
        assert result.call_status == "failed"

        upsert_narrative(rn_int_db, cand, result, batch_id="B-INT")
        row = read_narrative(rn_int_db, cand["candidate_id"])
        assert row["confidence"] == "low"
        assert row["model_tier"] == "failed"
        assert row["priority_rank"] == 999
