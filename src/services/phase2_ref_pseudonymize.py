"""PHASE2 row_ref 의 pseudonymize — salt 기반 단방향 해시.

Why: PHASE2 row_ref 가 외부 산출물(JSON manifest 등)에 노출될 때 원본
identifier 를 직접 드러내지 않기 위한 결정론적 단방향 매핑. 운영에서 salt 가
누락되면 동일 input 이 동일 해시로 떨어져 가명화 효과가 사라지므로,
공백전용 salt 까지 모두 거부한다 (invariant #2).
"""

from __future__ import annotations

import hashlib

# Why: sha256 hex 64자 중 앞 16자만 사용 — case_id sha1[:10] 과 충돌 가능성을
#      낮게 유지하면서, JSON / 파일명에 부담 없는 길이. 보안 keyed-hash 목적이
#      아니라 가명화이므로 truncation 으로 정보 노출 우려는 매우 낮음.
_OUTPUT_LENGTH = 16


def hash_ref_key(canonical_key: str, *, salt: str) -> str:
    """salt + canonical_key 의 sha256 앞 16자(lowercase hex)를 반환한다.

    Args:
        canonical_key: `canonicalize_ref_key` 의 결과 문자열.
        salt: 회사/engagement 단위로 분리된 임의 문자열. 빈 문자열·공백전용 거부.

    Returns:
        16자 lowercase hex 문자열.

    Raises:
        ValueError: salt 가 None / 빈 문자열 / 공백전용 일 때.
    """
    if not salt or not salt.strip():
        raise ValueError("hash_ref_key: salt must be non-empty and non-whitespace")
    digest = hashlib.sha256(f"{salt}|{canonical_key}".encode()).hexdigest()
    return digest[:_OUTPUT_LENGTH]
