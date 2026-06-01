"""`make_phase2_case_id` 의 ID 합성 계약 검증.

Why: PHASE2 case 의 ID 는 (batch_id, family, unit_type, canonical_refs,
evidence_signature) 5축에 결정론적으로 의존한다. invariant #7 — ref 순서/임계
변경에 무관, signature/batch_id/family/unit_type 변경에 반응.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from src.services.phase2_case_id import make_phase2_case_id


def _base_kwargs(**overrides):
    base = dict(
        batch_id="batch001",
        family="duplicate",
        unit_type="pair",
        canonical_refs=("s:r1", "s:r2"),
        evidence_signature="sub_rule=L2-03a",
    )
    base.update(overrides)
    return base


def test_id_format_prefix_family_unit():
    # 형식: p2_{family}_{unit_type}_{sha1_10}
    case_id = make_phase2_case_id(**_base_kwargs())
    assert re.fullmatch(r"p2_duplicate_pair_[0-9a-f]{10}", case_id) is not None


def test_id_stable_under_ref_order_change():
    # ref 순서가 바뀌어도 동일 ID — invariant #7.
    id_a = make_phase2_case_id(**_base_kwargs(canonical_refs=("s:r1", "s:r2")))
    id_b = make_phase2_case_id(**_base_kwargs(canonical_refs=("s:r2", "s:r1")))
    assert id_a == id_b


def test_id_changes_with_evidence_signature():
    id_a = make_phase2_case_id(**_base_kwargs(evidence_signature="sub_rule=L2-03a"))
    id_b = make_phase2_case_id(**_base_kwargs(evidence_signature="sub_rule=L2-03b"))
    assert id_a != id_b


def test_id_changes_with_batch_id():
    id_a = make_phase2_case_id(**_base_kwargs(batch_id="batch001"))
    id_b = make_phase2_case_id(**_base_kwargs(batch_id="batch002"))
    assert id_a != id_b


def test_id_changes_with_family():
    id_a = make_phase2_case_id(**_base_kwargs(family="duplicate"))
    id_b = make_phase2_case_id(**_base_kwargs(family="intercompany"))
    assert id_a != id_b
    # 새 family prefix 가 반영된다.
    assert id_b.startswith("p2_intercompany_")


def test_id_changes_with_unit_type():
    id_a = make_phase2_case_id(**_base_kwargs(unit_type="pair"))
    id_b = make_phase2_case_id(**_base_kwargs(unit_type="edge"))
    assert id_a != id_b
    assert id_b.startswith("p2_duplicate_edge_")


def test_id_uses_sha1_truncated_10():
    # 동일 payload 로 sha1[:10] 을 직접 계산해 비교 — 알고리즘 고정.
    kwargs = _base_kwargs(canonical_refs=("s:r2", "s:r1"))
    sorted_refs = ",".join(sorted(kwargs["canonical_refs"]))
    payload = (
        f"{kwargs['batch_id']}|{kwargs['family']}|{kwargs['unit_type']}|"
        f"{sorted_refs}|{kwargs['evidence_signature']}"
    )
    expected_hash = hashlib.sha1(payload.encode()).hexdigest()[:10]
    case_id = make_phase2_case_id(**kwargs)
    assert case_id == f"p2_{kwargs['family']}_{kwargs['unit_type']}_{expected_hash}"


# ---------------------------------------------------------------------------
# canonical_refs 입력 검증 — raw 값 silent 통과 차단
# ---------------------------------------------------------------------------


def test_make_phase2_case_id_rejects_raw_string_ref():
    """raw 문자열 (예: "DOC001") 은 canonicalize_ref_key 결과가 아니므로 ValueError."""
    with pytest.raises(ValueError, match="canonicalize_ref_key"):
        make_phase2_case_id(**_base_kwargs(canonical_refs=("DOC001",)))


def test_make_phase2_case_id_rejects_empty_string_ref():
    """빈 문자열은 어떤 canonical prefix 도 만족하지 못함."""
    with pytest.raises(ValueError):
        make_phase2_case_id(**_base_kwargs(canonical_refs=("",)))


def test_make_phase2_case_id_rejects_unknown_prefix():
    """allowlist 외 prefix (예: 'x:foo') 거부."""
    with pytest.raises(ValueError):
        make_phase2_case_id(**_base_kwargs(canonical_refs=("x:foo",)))


def test_make_phase2_case_id_rejects_non_string_ref():
    """str 이 아닌 원소 (int 등) 도 거부 — type 안전."""
    with pytest.raises(ValueError):
        make_phase2_case_id(**_base_kwargs(canonical_refs=(42,)))  # type: ignore[arg-type]


def test_make_phase2_case_id_accepts_all_canonical_prefixes():
    """canonicalize_ref_key 의 모든 prefix (n:/b:/i:/f:/d:/ts:/t:/s:) 통과."""
    valid_refs = (
        "n:",
        "b:1",
        "i:42",
        "f:3.14",
        "f:+inf",
        "f:-inf",
        "d:1.5",
        "ts:2026-01-01T00:00:00",
        "t:(i:1|s:abc)",
        "s:abc",
    )
    for ref in valid_refs:
        case_id = make_phase2_case_id(**_base_kwargs(canonical_refs=(ref,)))
        assert case_id.startswith("p2_duplicate_pair_")


def test_make_phase2_case_id_validates_all_refs_in_tuple():
    """tuple 의 한 원소만 invalid 여도 ValueError — 부분 통과 금지."""
    with pytest.raises(ValueError):
        make_phase2_case_id(**_base_kwargs(canonical_refs=("s:valid", "RAW_INVALID")))
