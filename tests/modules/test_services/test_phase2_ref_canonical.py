"""`canonicalize_ref_key` 의 타입별 정규화 계약 검증.

Why: PHASE2 native case 의 row_ref / case_id payload 는 환경(Windows/Linux,
pandas/numpy 버전) 에 따라 표현이 흔들리면 안 된다. 본 테스트는 invariant #1
(canonicalize 결과 환경 무관) 와 v7-plan §Module signatures 의 prefix 규약을
강제한다.
"""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal

import numpy as np
import pandas as pd

from src.services.phase2_ref_canonical import (
    canonicalize_ref_key,
    normalize_line_number_key,
)


def test_canonicalize_none_returns_n():
    assert canonicalize_ref_key(None) == "n:"


def test_canonicalize_float_nan_returns_n():
    assert canonicalize_ref_key(float("nan")) == "n:"


def test_canonicalize_pd_nat_returns_n():
    assert canonicalize_ref_key(pd.NaT) == "n:"


def test_canonicalize_pd_na_returns_n():
    assert canonicalize_ref_key(pd.NA) == "n:"


def test_canonicalize_decimal_nan_returns_n():
    assert canonicalize_ref_key(Decimal("NaN")) == "n:"


def test_canonicalize_bool_true_returns_b1():
    assert canonicalize_ref_key(True) == "b:1"
    # numpy bool 도 동일 코드로 수렴해야 한다.
    assert canonicalize_ref_key(np.bool_(True)) == "b:1"


def test_canonicalize_bool_false_returns_b0():
    assert canonicalize_ref_key(False) == "b:0"
    assert canonicalize_ref_key(np.bool_(False)) == "b:0"


def test_canonicalize_int_returns_i_prefix():
    assert canonicalize_ref_key(0) == "i:0"
    assert canonicalize_ref_key(42) == "i:42"
    assert canonicalize_ref_key(-7) == "i:-7"


def test_canonicalize_np_int64_returns_i_prefix():
    # Why: numpy.int64 도 파이썬 int 와 동일 prefix 로 수렴 → 환경 무관.
    assert canonicalize_ref_key(np.int64(42)) == "i:42"
    assert canonicalize_ref_key(np.int32(-1)) == "i:-1"


def test_canonicalize_float_normal_returns_f_prefix():
    # 10g 포맷이므로 trailing zero 가 제거된다.
    assert canonicalize_ref_key(1.5) == "f:1.5"
    assert canonicalize_ref_key(0.0) == "f:0"
    assert canonicalize_ref_key(-3.14) == "f:-3.14"


def test_canonicalize_float_pos_inf_returns_f_plus_inf():
    assert canonicalize_ref_key(math.inf) == "f:+inf"
    assert canonicalize_ref_key(float("inf")) == "f:+inf"


def test_canonicalize_float_neg_inf_returns_f_minus_inf():
    assert canonicalize_ref_key(-math.inf) == "f:-inf"


def test_canonicalize_decimal_normal_returns_d_prefix():
    # Decimal.normalize() 결과가 그대로 직렬화되어야 한다.
    assert canonicalize_ref_key(Decimal("1.50")) == f"d:{Decimal('1.50').normalize()}"
    assert canonicalize_ref_key(Decimal("0")) == f"d:{Decimal('0').normalize()}"


def test_canonicalize_pd_timestamp_returns_ts_prefix():
    ts = pd.Timestamp("2026-05-27 10:30:00")
    assert canonicalize_ref_key(ts) == f"ts:{ts.isoformat()}"


def test_canonicalize_python_datetime_returns_ts_prefix():
    value = dt.datetime(2026, 5, 27, 10, 30, 0)
    assert canonicalize_ref_key(value) == f"ts:{value.isoformat()}"


def test_canonicalize_python_date_returns_ts_prefix():
    value = dt.date(2026, 5, 27)
    assert canonicalize_ref_key(value) == f"ts:{value.isoformat()}"


def test_canonicalize_tuple_returns_t_prefix():
    result = canonicalize_ref_key((1, 2, 3))
    assert result == "t:(i:1|i:2|i:3)"


def test_canonicalize_nested_tuple():
    # 재귀적으로 정규화되어야 한다.
    result = canonicalize_ref_key((1, (2, 3), None))
    assert result == "t:(i:1|t:(i:2|i:3)|n:)"


def test_canonicalize_string_returns_s_prefix():
    assert canonicalize_ref_key("hello") == "s:hello"
    # 빈 문자열도 None 과 구분되어야 한다.
    assert canonicalize_ref_key("") == "s:"


def test_canonicalize_unicode_string():
    # 한국어/이모지 등 유니코드도 str() 그대로 보존.
    assert canonicalize_ref_key("계정-1001") == "s:계정-1001"


# ---------------------------------------------------------------------------
# Strict canonicalization — canonical-prefix 형태의 raw 문자열도 's:' 부착
# ---------------------------------------------------------------------------


def test_canonicalize_strict_does_not_skip_prefix_like_raw_string():
    """raw 문자열 'i:10' 은 canonical int 10 과 구분되어야 한다 — 's:' 부착.

    이전 idempotency 버전에서는 raw 'i:10' 이 canonical 로 잘못 인식되어
    int 10 과 충돌. 현재는 strict — Phase2RowRef.index_label 의 idempotency 는
    dataclass invariant 로 보장 (make_row_ref 진입 단계 canonicalize, 이후 재호출 없음).
    """
    # 문자열 "i:10" 은 raw 입력이므로 's:i:10' 으로 prefix 부착 → int 10 ("i:10") 과 구분.
    assert canonicalize_ref_key("i:10") == "s:i:10"
    assert canonicalize_ref_key("ts:custom") == "s:ts:custom"
    assert canonicalize_ref_key("s:nested") == "s:s:nested"
    # canonical 이 아닌 일반 문자열도 동일하게 's:' 부착.
    assert canonicalize_ref_key("DOC001") == "s:DOC001"
    assert canonicalize_ref_key("id:042") == "s:id:042"


# ---------------------------------------------------------------------------
# normalize_line_number_key — S4.next dtype-agnostic 정규화 (invariant #43)
# ---------------------------------------------------------------------------


def test_normalize_line_number_key_string_zero_padded():
    """``"s:0001"`` 처럼 선행 0 이 붙은 문자열은 int 변환으로 "1" 로 수렴."""
    assert normalize_line_number_key("s:0001") == "1"


def test_normalize_line_number_key_string_zero_padded_double_digit():
    """``"s:0010"`` → "10" — 두 자리 이상 선행 0 도 동일하게 정리."""
    assert normalize_line_number_key("s:0010") == "10"


def test_normalize_line_number_key_int_prefix():
    """``"i:1"`` → "1" — int prefix 는 선행 0 없으므로 값 그대로."""
    assert normalize_line_number_key("i:1") == "1"


def test_normalize_line_number_key_float_one_point_zero():
    """``"f:1.0"`` 처럼 정수형 float 는 ``"1"`` 로 수렴해 int prefix 와 매칭."""
    assert normalize_line_number_key("f:1.0") == "1"
    # 비정수 float 는 원형 보존 — line_number 가 1.5 인 비정상 입력은 그대로 노출.
    assert normalize_line_number_key("f:1.5") == "1.5"


def test_normalize_line_number_key_null_canonical_returns_none():
    """``"n:"`` (canonicalize NaN/NaT/None 결과) 는 None."""
    assert normalize_line_number_key("n:") is None


def test_normalize_line_number_key_none_passthrough():
    """입력 자체가 None 이면 그대로 None."""
    assert normalize_line_number_key(None) is None


def test_normalize_line_number_key_non_numeric_string_keeps_value():
    """``"s:abc"`` 처럼 숫자 아닌 문자열은 prefix 만 제거하고 값 보존."""
    assert normalize_line_number_key("s:abc") == "abc"


def test_normalize_line_number_key_empty_canonical_returns_none():
    """빈 문자열 입력도 None (방어적) — 정상 호출 경로에서는 발생하지 않지만 보호."""
    assert normalize_line_number_key("") is None


# ---------------------------------------------------------------------------
# normalize_line_number_key — domain-only idempotency (invariant #43 약화)
# ---------------------------------------------------------------------------


def test_normalize_line_number_key_is_idempotent_for_colon_free_results():
    """결과에 ":" 가 남지 않으면 ``normalize(normalize(x)) == normalize(x)``.

    line_number 도메인 정상 입력 (n:/i:/f:/s:<digits or non-colon>) 에서 보장.
    """
    for canonical_key in ("s:0001", "i:1", "f:1.0", "f:1.5", "s:abc"):
        first = normalize_line_number_key(canonical_key)
        second = normalize_line_number_key(first)
        assert first == second
        assert first is None or ":" not in first
    # None / "n:" 도 idempotent.
    assert normalize_line_number_key(normalize_line_number_key("n:")) is None
    assert normalize_line_number_key(normalize_line_number_key(None)) is None


# ---------------------------------------------------------------------------
# normalize_line_number_key — 비도메인 prefix 는 원형 보존 (cascade 분해 차단)
# ---------------------------------------------------------------------------


def test_normalize_line_number_key_timestamp_prefix_returns_original():
    """``"ts:2026-01-01T00:00:00"`` 같은 timestamp 는 line_number 가 아니므로 원형 보존.

    이전 재귀 cascade 는 colon 기준 분해로 "00" 같은 무의미한 결과를 만들었다.
    line_number 도메인이 아닌 prefix 입력은 한 번에 원본 그대로 반환.
    """
    ts_canonical = "ts:2026-01-01T00:00:00"
    assert normalize_line_number_key(ts_canonical) == ts_canonical


def test_normalize_line_number_key_tuple_prefix_returns_original():
    """``"t:(i:1|s:2)"`` 도 tuple 표현 — line_number 가 아니므로 원형 보존."""
    tuple_canonical = "t:(i:1|s:2)"
    assert normalize_line_number_key(tuple_canonical) == tuple_canonical


def test_normalize_line_number_key_bool_prefix_returns_original():
    """``"b:1"`` 도 boolean 표현 — line_number 가 아니므로 원형 보존."""
    assert normalize_line_number_key("b:1") == "b:1"
    assert normalize_line_number_key("b:0") == "b:0"


def test_normalize_line_number_key_decimal_prefix_returns_original():
    """``"d:1.5"`` 는 Decimal 표현 — float 와 의미 분리, 원형 보존."""
    assert normalize_line_number_key("d:1.5") == "d:1.5"


def test_normalize_line_number_key_non_domain_prefix_does_not_cascade():
    """비도메인 prefix 입력의 cascade 분해 차단 회귀 가드.

    이전 구현에서는 result 에 ":" 가 남으면 재귀 호출 → ``"ts:2026..."`` 가 결국
    ``"00"`` 같은 의미없는 결과로 분해됨. 현재는 비도메인 prefix 발견 즉시 원형 반환.
    """
    inputs_with_multiple_colons = (
        "ts:2026-01-01T00:00:00",
        "t:(i:1|t:(i:2|i:3))",
        "d:0.000001",
    )
    for canonical_key in inputs_with_multiple_colons:
        assert normalize_line_number_key(canonical_key) == canonical_key


# ---------------------------------------------------------------------------
# normalize_line_number_key — s: prefix raw colon-string 도 cascade 없이 한 번에
# ---------------------------------------------------------------------------


def test_normalize_line_number_key_raw_canonical_prefix_string_preserves_value():
    """raw line_number = ``"i:1"`` (사용자 문자열) → canonicalize = ``"s:i:1"`` →
    normalize = ``"i:1"`` (prefix s 만 제거, colon-string 보존, cascade 없음).

    int 1 의 canonical ``"i:1"`` 과 raw string ``"i:1"`` 은 의미가 다른 line_number
    이므로 두 값을 서로 다르게 표현하는 것이 정합. raw "i:1" 은 한 번 normalize 후
    그대로 보존되며, 두 번째 normalize 호출은 도메인 외 동작이라 idempotency 비보장
    (호출자는 한 번만 적용한다 — docstring lock).
    """
    assert normalize_line_number_key("s:i:1") == "i:1"
    assert normalize_line_number_key("s:s:abc") == "s:abc"
    assert normalize_line_number_key("s:ts:custom") == "ts:custom"
