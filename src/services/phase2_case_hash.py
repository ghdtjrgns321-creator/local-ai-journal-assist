"""PHASE2 case set 직렬화·해시 계산.

raw_hash 와 linked_hash 를 완전 분리한다.
raw_hash 는 phase1_case_refs 키 자체를 payload 에서 제외 (default () 라도),
linked_hash 는 phase1_case_refs 를 정렬된 list 로 포함한다.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

from src.models.phase2_case import Phase2CaseBase, Phase2CaseSet

# raw hash payload 에서 제외할 필드 — linked 와 raw 의 분리 키
_RAW_HASH_EXCLUDED_FIELDS: frozenset[str] = frozenset({"phase1_case_refs"})


def _case_to_canonical_dict(
    case: Phase2CaseBase,
    *,
    exclude: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """case 를 dict 로 변환 후 exclude 적용.

    Phase2RowRef.index_label 은 dataclass invariant 에 의해 항상 canonical
    문자열이므로 hash 단계에서 추가 canonicalize 가 불필요하다 (make_row_ref
    가 진입 시점에 canonicalize 보장).

    phase1_case_refs 가 포함된 경우 정렬된 list 로 변환 — linked hash 의
    입력 순서 무관성 보장.
    """
    case_dict = dataclasses.asdict(case)
    for excluded_field in exclude:
        case_dict.pop(excluded_field, None)
    if "phase1_case_refs" in case_dict:
        case_dict["phase1_case_refs"] = sorted(case_dict["phase1_case_refs"])
    return case_dict


def _canonical_json(payload: list[dict[str, Any]]) -> str:
    """결정적 JSON 직렬화 — sort_keys + 압축 separator + default=str (Decimal 등)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_raw_case_hash(case_set: Phase2CaseSet) -> str:
    """raw hash — phase1_case_refs 키 자체를 payload 에서 제외 (default () 포함).

    linked 와 sub-routine 관계 없이 독립적으로 payload 를 만든다.
    """
    payload = [
        _case_to_canonical_dict(case, exclude=_RAW_HASH_EXCLUDED_FIELDS)
        for case in case_set.iter_all_cases_sorted()
    ]
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def compute_linked_case_hash(case_set: Phase2CaseSet) -> str:
    """linked hash — phase1_case_refs 를 정렬된 list 로 payload 에 포함.

    raw 와 sub-routine 관계 없이 독립적으로 payload 를 만든다.
    """
    payload = [_case_to_canonical_dict(case) for case in case_set.iter_all_cases_sorted()]
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


__all__ = [
    "_RAW_HASH_EXCLUDED_FIELDS",
    "compute_raw_case_hash",
    "compute_linked_case_hash",
]
