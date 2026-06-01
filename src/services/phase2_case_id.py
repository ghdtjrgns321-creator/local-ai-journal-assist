"""PHASE2 native case 의 결정론적 case_id 합성.

Why: PHASE2 family-native case (duplicate / intercompany / relational /
unsupervised / timeseries) 는 (batch_id, family, unit_type, canonical_refs,
evidence_signature) 5축에만 의존하는 ID 가 필요하다. ref 순서·임계 변경에는
무관, signature/batch_id/family/unit_type 변경에는 반응해야 한다 (invariant #7).

`evidence_signature` 에는 raw 금액 / score / threshold 를 포함하면 안 된다.
case identity 에 해당하는 sub_rule, ic_role, edge keys 만 들어가야 score
drift 가 case_id 를 흔들지 않는다.
"""

from __future__ import annotations

import hashlib

# Why: sha1 truncated 10 — 10^12 case 까지 충돌 우려 낮음, ID 길이 합리적.
_HASH_LENGTH = 10

# Why: canonicalize_ref_key 의 출력 prefix allowlist. canonical_refs 입력이
# raw 값 (예: "DOC001") 으로 들어오면 ID 안정성·비식별화 계약이 조용히 깨진다.
# canonical 통과 결과만 받아 ValueError 로 즉시 차단한다.
# tuple 의 t:(...) 형식과 빈 None ("n:") 도 단일 prefix 로 표현됨.
_CANONICAL_PREFIX_ALLOWLIST: tuple[str, ...] = (
    "n:",
    "b:",
    "i:",
    "f:",
    "d:",
    "ts:",
    "t:",
    "s:",
)


def _validate_canonical_ref(ref: str) -> None:
    """canonical_refs 의 단일 원소가 canonicalize_ref_key 결과인지 검증."""
    if not isinstance(ref, str) or not ref.startswith(_CANONICAL_PREFIX_ALLOWLIST):
        raise ValueError(
            "make_phase2_case_id: canonical_refs entry must be canonicalize_ref_key "
            f"output (prefix in {_CANONICAL_PREFIX_ALLOWLIST}), got: {ref!r}"
        )


def make_phase2_case_id(
    *,
    batch_id: str,
    family: str,
    unit_type: str,
    canonical_refs: tuple[str, ...],
    evidence_signature: str,
) -> str:
    """`p2_{family}_{unit_type}_{sha1_10}` 형식의 결정론적 case_id 를 반환.

    Args:
        batch_id: 분석 배치 식별자.
        family: PHASE2 family — duplicate / intercompany / relational /
            unsupervised / timeseries.
        unit_type: pair / edge / row / window / no_candidate.
        canonical_refs: `canonicalize_ref_key` 결과 문자열의 tuple. 입력 순서는
            무관하다 (내부에서 sorted).
        evidence_signature: case identity 만 포함하는 짧은 시그니처 문자열.
            raw 금액·score·threshold 는 포함하지 않는다.

    Returns:
        `p2_{family}_{unit_type}_{sha1[:10]}` 문자열.
    """
    # Why: canonical 통과 입력만 허용 — raw 값 (예: "DOC001") 이 흘러들면
    # ID 안정성·비식별화 계약이 조용히 깨진다. allowlist prefix 위반 시 ValueError.
    for ref in canonical_refs:
        _validate_canonical_ref(ref)
    # Why: ref 순서 무관 invariant — sort 후 ',' join 으로 정규화.
    sorted_refs = ",".join(sorted(canonical_refs))
    payload = f"{batch_id}|{family}|{unit_type}|{sorted_refs}|{evidence_signature}"
    digest = hashlib.sha1(payload.encode()).hexdigest()[:_HASH_LENGTH]
    return f"p2_{family}_{unit_type}_{digest}"
