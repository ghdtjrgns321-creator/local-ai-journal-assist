"""`hash_ref_key` 의 salt 검증과 결정론적 출력 검증.

Why: PHASE2 row_ref 의 pseudonymize 출력은 (salt, canonical_key) 두 입력에
완전히 의존해야 한다. 빈/공백 salt 는 운영 사고를 유발하므로 즉시 거부한다.
invariant #2 보장.
"""

from __future__ import annotations

import re

import pytest

from src.services.phase2_ref_pseudonymize import hash_ref_key


def test_salt_empty_raises_value_error():
    with pytest.raises(ValueError, match="salt"):
        hash_ref_key("s:hello", salt="")


def test_salt_whitespace_only_raises():
    # 공백 4칸 — strip 후 비어있으므로 거부.
    with pytest.raises(ValueError, match="salt"):
        hash_ref_key("s:hello", salt="    ")


def test_salt_tab_newline_only_raises():
    # 탭/개행 조합도 공백전용으로 간주.
    with pytest.raises(ValueError, match="salt"):
        hash_ref_key("s:hello", salt="\t\n")


def test_same_input_same_hash():
    h1 = hash_ref_key("s:hello", salt="salt-a")
    h2 = hash_ref_key("s:hello", salt="salt-a")
    assert h1 == h2


def test_different_salt_different_hash():
    h1 = hash_ref_key("s:hello", salt="salt-a")
    h2 = hash_ref_key("s:hello", salt="salt-b")
    assert h1 != h2


def test_different_canonical_different_hash():
    h1 = hash_ref_key("s:hello", salt="salt-a")
    h2 = hash_ref_key("s:world", salt="salt-a")
    assert h1 != h2


def test_output_length_16():
    # truncated 16 hex chars.
    h = hash_ref_key("s:hello", salt="salt-a")
    assert len(h) == 16


def test_output_is_lowercase_hex():
    h = hash_ref_key("s:hello", salt="salt-a")
    assert re.fullmatch(r"[0-9a-f]{16}", h) is not None
