"""Review Narrator 테스트 공용 fixture.

prefix: rn_ (review_narrator)
"""

from __future__ import annotations

import pytest

from src.llm.review_narrator.models import (
    EvidenceType,
    ReasoningEvidence,
    ReasoningItem,
    ReviewNarrative,
    SuggestedAction,
    SuggestedActionType,
)


@pytest.fixture()
def rn_known_rule_ids() -> set[str]:
    """PHASE1 룰 카탈로그 가짜 — citation_validator 입력."""
    return {"L1-01", "L2-04", "NLP03"}


@pytest.fixture()
def rn_known_feature_ids() -> set[str]:
    """PHASE2 feature 카탈로그 가짜."""
    return {"amount_zscore", "approval_excess_ratio", "vae_recon_error"}


@pytest.fixture()
def rn_known_journal_ids() -> set[str]:
    """전표 ID 가짜."""
    return {"JE-2025-0001", "JE-2025-0002", "JE-2025-0050"}


class FakeChatClient:
    """ChatClient Protocol 만족 — 미리 정해둔 응답을 순서대로 반환.

    `responses`에 문자열을 넣으면 chat() 호출 시마다 pop. 빈 큐가 되면 빈 문자열 반환.
    `raise_on_call=True`면 모든 chat 호출에서 예외 발생.
    """

    provider = "fake"

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        model: str = "fake-model",
        raise_on_call: bool = False,
    ) -> None:
        self.responses = list(responses or [])
        self.model = model
        self.calls: list[dict] = []
        self.raise_on_call = raise_on_call

    def is_available(self) -> bool:
        return True

    def chat(self, messages, temperature=None, format=None):  # type: ignore[no-untyped-def]
        self.calls.append({"messages": messages, "temperature": temperature, "format": format})
        if self.raise_on_call:
            raise RuntimeError("simulated provider failure")
        if not self.responses:
            return ""
        return self.responses.pop(0)

    def stream_chat(self, messages, temperature=None):  # type: ignore[no-untyped-def]
        raise NotImplementedError


@pytest.fixture()
def rn_chat_client_cls():
    """FakeChatClient 클래스 노출용 fixture — 테스트에서 인스턴스 생성."""
    return FakeChatClient


@pytest.fixture()
def rn_valid_narrative() -> ReviewNarrative:
    """모든 인용이 valid한 ReviewNarrative — 강등되지 않아야 함."""
    return ReviewNarrative(
        candidate_id="CAND-001",
        priority_rank=1,
        priority_score=0.92,
        summary="기말 자정 직후 승인 한도 초과 수기 전표 — 우선 검토 필요",
        reasoning=[
            ReasoningItem(
                claim="승인 한도를 초과한 수기 전표가 자정 직후에 발생",
                evidence=[
                    ReasoningEvidence(type=EvidenceType.RULE_HIT, rule_id="L1-01"),
                    ReasoningEvidence(
                        type=EvidenceType.ML_FEATURE,
                        model_id="vae_v1",
                        feature_id="amount_zscore",
                    ),
                    ReasoningEvidence(
                        type=EvidenceType.ROW,
                        journal_id="JE-2025-0001",
                        line_no=2,
                    ),
                ],
            ),
        ],
        suggested_actions=[
            SuggestedAction(
                action_type=SuggestedActionType.REQUEST_EVIDENCE,
                description="원인 증빙 + 승인자 권한 한도 사본 요청",
                target="JE-2025-0001",
            ),
        ],
        confidence="high",
    )


@pytest.fixture()
def rn_candidate() -> dict:
    """narrator/cache 테스트용 표준 candidate dict."""
    return {
        "candidate_id": "CAND-CASE-01",
        "journal_ref": {
            "batch_id": "B-2026-Q1",
            "journal_id": "JE-2025-0001",
            "posting_date": "2026-03-31",
            "period": "2026-03",
            "process": "R2R",
        },
        "rule_hits": [
            {
                "rule_id": "L1-01",
                "severity": 3,
                "score": 0.9,
                "fields_triggered": ["amount"],
                "rule_meta_ref": "L1",
            },
        ],
        "ml_scores": [
            {
                "model_id": "vae_v1",
                "score": 0.85,
                "percentile": 0.995,
                "top_features": [
                    {"feature_id": "amount_zscore", "value": 3.1, "contribution": 0.6},
                ],
            },
        ],
        "journal_meta": {
            "amount_bucket": "10억~100억",
            "gl_account": "1100",
            "counterparty_masked": "MASKED_NAME_abcd1234",
            "approver_masked": "MASKED_NAME_efgh5678",
            "description_masked": "기말 결산",
        },
        "peer_context": {"median": 100_000_000, "p95": 1_000_000_000},
    }


@pytest.fixture()
def rn_valid_llm_response(rn_candidate) -> str:
    """LLM이 정상 응답할 ReviewNarrative JSON 문자열 (입력 ID 만 인용)."""
    payload = {
        "candidate_id": rn_candidate["candidate_id"],
        "priority_rank": 1,
        "priority_score": 0.92,
        "summary": "기말 자정 직후 승인 한도 초과 수기 전표 — 우선 검토 필요",
        "reasoning": [
            {
                "claim": "승인 한도 초과 수기 전표가 자정 직후에 발생",
                "evidence": [
                    {
                        "type": "rule_hit",
                        "rule_id": "L1-01",
                        "model_id": "",
                        "feature_id": "",
                        "journal_id": "",
                        "line_no": 0,
                    },
                    {
                        "type": "ml_feature",
                        "rule_id": "",
                        "model_id": "vae_v1",
                        "feature_id": "amount_zscore",
                        "journal_id": "",
                        "line_no": 0,
                    },
                    {
                        "type": "row",
                        "rule_id": "",
                        "model_id": "",
                        "feature_id": "",
                        "journal_id": "JE-2025-0001",
                        "line_no": 2,
                    },
                ],
            },
        ],
        "suggested_actions": [
            {
                "action_type": "request_evidence",
                "description": "승인 한도 사본 요청",
                "target": "JE-2025-0001",
            },
        ],
        "confidence": "high",
    }
    import json as _json

    return _json.dumps(payload, ensure_ascii=False)
