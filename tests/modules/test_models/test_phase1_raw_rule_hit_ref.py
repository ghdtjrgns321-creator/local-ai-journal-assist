"""RawRuleHitRef schema 확장 (S6.next Phase 1) 테스트.

v7-plan §S6.next Phase 1 의 단일 출처 사양에 대응한다. 신규 hash 필드 3개
(canonical_label_hash / doc_id_hash / line_number_key) 의 기본값과
``model_config(extra="forbid")`` 유지를 확인한다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.phase1_case import RawRuleHitRef

# ---------------------------------------------------------------------------
# Why: 기존 PHASE1 산출물(JSON)이 신규 필드 없이 로드되더라도 회귀가 없어야 함.
#      신규 필드는 모두 default 값을 가진다 (invariant #71).
# ---------------------------------------------------------------------------


def _legacy_kwargs() -> dict:
    return {
        "rule_id": "L1-05",
        "severity": 4,
        "document_id": "DOC-1",
        "row_index": 0,
        "evidence_type": "control_failure",
    }


def test_raw_rule_hit_ref_legacy_fields_unchanged() -> None:
    """기존 필수 필드만 넘기는 호출이 그대로 동작 (회귀 가드)."""
    ref = RawRuleHitRef(**_legacy_kwargs())
    assert ref.rule_id == "L1-05"
    assert ref.severity == 4
    assert ref.document_id == "DOC-1"
    assert ref.row_index == 0
    assert ref.evidence_type == "control_failure"
    # 기존 default 값 보존
    assert ref.record_id is None
    assert ref.score == 0.0
    assert ref.signal_strength == 0.0
    assert ref.normalized_score == 0.0
    assert ref.evidence_strength == ""
    assert ref.scoring_role == "primary"
    assert ref.display_label == ""
    assert ref.signal_status == "confirmed"
    assert ref.detail is None


def test_raw_rule_hit_ref_new_hash_fields_default_empty_or_none() -> None:
    """신규 hash 필드 default — 빈 문자열 / None (invariant #71, #74)."""
    ref = RawRuleHitRef(**_legacy_kwargs())
    assert ref.canonical_label_hash == ""
    assert ref.doc_id_hash == ""
    assert ref.line_number_key is None
    # S6.next Phase 2 — company_code_hash 도 default 빈 문자열 (invariant #74).
    assert ref.company_code_hash == ""


def test_raw_rule_hit_ref_new_hash_fields_explicit_assignment() -> None:
    """salt 가용 caller 가 신규 필드를 명시 전달하면 그대로 보존된다."""
    ref = RawRuleHitRef(
        **_legacy_kwargs(),
        canonical_label_hash="abcd1234deadbeef",
        doc_id_hash="0123456789abcdef",
        line_number_key="i:1",
        company_code_hash="aabbccdd00112233",
    )
    assert ref.canonical_label_hash == "abcd1234deadbeef"
    assert ref.doc_id_hash == "0123456789abcdef"
    assert ref.line_number_key == "i:1"
    assert ref.company_code_hash == "aabbccdd00112233"


def test_raw_rule_hit_ref_extra_forbid_still_enforced() -> None:
    """model_config(extra='forbid') 유지 — unknown 필드는 거부 (invariant #73)."""
    with pytest.raises(ValidationError):
        RawRuleHitRef(
            **_legacy_kwargs(),
            unknown_field="boom",  # type: ignore[call-arg]
        )


def test_raw_rule_hit_ref_round_trip_json_with_new_fields() -> None:
    """직렬화/역직렬화 라운드트립 — 신규 필드 포함하여 손실 없음."""
    original = RawRuleHitRef(
        **_legacy_kwargs(),
        canonical_label_hash="cafebabedeadbeef",
        doc_id_hash="feedfacecafebabe",
        line_number_key=None,
        company_code_hash="1234567890abcdef",
    )
    payload = original.model_dump_json()
    restored = RawRuleHitRef.model_validate_json(payload)
    assert restored == original


def test_raw_rule_hit_ref_company_code_hash_default_when_legacy_payload_loaded() -> None:
    """S6.next Phase 1 시점의 JSON 산출물 (company_code_hash 부재) 로드 시 default.

    Why: backward compat — 기존 Phase 1 결과 JSON 에는 company_code_hash 키가
    없으므로 default 빈 문자열로 채워져 회귀가 없어야 한다 (invariant #74).
    """
    legacy_json = (
        '{"rule_id":"L1-05","severity":4,"document_id":"DOC-1","row_index":0,'
        '"record_id":null,"score":0.0,"signal_strength":0.0,"normalized_score":0.0,'
        '"evidence_strength":"","scoring_role":"primary","display_label":"",'
        '"signal_status":"confirmed","detail":null,"evidence_type":"control_failure",'
        '"canonical_label_hash":"deadbeefcafe0000","doc_id_hash":"0000cafe0000beef",'
        '"line_number_key":null}'
    )
    restored = RawRuleHitRef.model_validate_json(legacy_json)
    assert restored.company_code_hash == ""
    assert restored.canonical_label_hash == "deadbeefcafe0000"
