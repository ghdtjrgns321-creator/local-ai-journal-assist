from __future__ import annotations

from src.evidence.local_evidence_brief import build_local_evidence_brief


def _drilldown() -> dict:
    return {
        "case": {
            "case_id": "CASE-1",
            "risk_narrative": "작성자와 승인자가 같은 검토 후보입니다.",
            "review_focus": ["승인 근거 확인"],
            "recommended_audit_actions": ["원천 증빙과 승인 로그를 대조합니다."],
        },
        "documents": [
            {
                "document_id": "DOC-1",
                "created_by": "user_a",
                "approved_by": "user_a",
                "matched_rules": ["L1-05"],
            }
        ],
        "raw_rule_hits": [{"rule_id": "L1-05", "document_id": "DOC-1"}],
    }


def test_local_evidence_brief_uses_existing_case_rule_and_document_evidence() -> None:
    brief = build_local_evidence_brief(_drilldown())

    joined = "\n".join(brief.key_evidence + brief.audit_actions + brief.limitations)
    assert "작성자와 승인자가 같은 검토 후보" in joined
    assert "승인 근거 확인" in joined
    assert "L1-05" in joined
    assert "DOC-1" in joined
    assert "원천 증빙과 승인 로그" in joined


def test_local_evidence_brief_graceful_fallback_for_empty_input() -> None:
    brief = build_local_evidence_brief({})

    assert brief.key_evidence
    assert brief.audit_actions
    assert brief.limitations


def test_local_evidence_brief_does_not_use_conclusive_forbidden_wording() -> None:
    brief = build_local_evidence_brief(_drilldown())

    joined = "\n".join(brief.key_evidence + brief.audit_actions + brief.limitations)
    forbidden = ["부정 확정", "위반 확정", "fraud 확정", "OpenAI", "LLM"]
    assert not any(term in joined for term in forbidden)
