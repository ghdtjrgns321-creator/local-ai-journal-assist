from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from src.llm.phase1_case_brief import (
    Phase1BriefEvidence,
    Phase1BriefReasoning,
    Phase1CaseBrief,
    build_phase1_case_brief_payload,
    generate_phase1_case_brief,
    validate_phase1_case_brief,
)


class _FakeClient:
    provider = "fake"
    model = "fake-model"

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        format: dict | str | None = None,
    ) -> str:
        self.calls.append({"messages": messages, "temperature": temperature, "format": format})
        return json.dumps(self.response, ensure_ascii=False)

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
    ) -> Iterator[str]:
        yield from ()


def _drilldown() -> dict[str, Any]:
    return {
        "case": {
            "case_id": "CASE-1",
            "topic_label": "권한·통제",
            "priority_band": "high",
            "risk_narrative": "작성자와 승인자가 같은 검토 후보입니다.",
        },
        "documents": [
            {
                "document_id": "DOC-1",
                "created_by": "user_a",
                "approved_by": "user_a",
                "gl_account": "Revenue",
                "amount": 1200,
                "matched_rules": ["L1-05"],
            }
        ],
        "raw_rule_hits": [
            {
                "rule_id": "L1-05",
                "document_id": "DOC-1",
                "severity": 4,
                "signal_type": "direct_risk",
            }
        ],
    }


def test_payload_is_phase1_only() -> None:
    payload = build_phase1_case_brief_payload(_drilldown())

    assert payload["case_id"] == "CASE-1"
    assert "phase2_case_overlays" not in payload
    assert "ml_scores" not in json.dumps(payload, ensure_ascii=False)


def test_generate_uses_rule_and_row_schema_only() -> None:
    response = {
        "summary": "승인 통제 신호가 있는 검토 후보입니다.",
        "reasoning": [
            {
                "claim": "작성자와 승인자가 같습니다.",
                "evidence": [{"type": "rule_hit", "rule_id": "L1-05"}],
            }
        ],
        "suggested_actions": [
            {"action_type": "request_evidence", "description": "승인 근거 문서를 확인합니다."}
        ],
        "limitations": "자동 생성 초안이며 제공된 rule evidence 외 사실은 포함하지 않습니다.",
    }
    client = _FakeClient(response)

    result = generate_phase1_case_brief(
        _drilldown(),
        reasoning_client=client,
        light_client=client,
    )

    assert result.is_valid
    evidence_schema = client.calls[0]["format"]["$defs"]["Phase1BriefEvidence"]
    assert evidence_schema["properties"]["type"]["enum"] == ["rule_hit", "row"]
    assert evidence_schema["properties"]["rule_id"]["enum"] == ["", "L1-05"]
    assert evidence_schema["properties"]["document_id"]["enum"] == ["", "DOC-1"]


def test_invalid_rule_citation_is_downgraded_in_limitations() -> None:
    brief = Phase1CaseBrief(
        summary="요약",
        reasoning=[
            Phase1BriefReasoning(
                claim="입력에 없는 룰을 인용했습니다.",
                evidence=[Phase1BriefEvidence(type="rule_hit", rule_id="L9-99")],
            )
        ],
        suggested_actions=[],
        limitations="자동 생성 초안.",
    )

    result = validate_phase1_case_brief(brief, {"L1-05"}, {"DOC-1"})

    assert not result.is_valid
    assert "unknown rule_id" in result.invalid_citations[0]
    assert "검토 신뢰도가 낮습니다" in result.brief.limitations
