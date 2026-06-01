"""PHASE2 row_ref / case_id payload 의 환경 무관 정규화 (canonicalize).

Why: PHASE2 native case 는 Windows / Linux, pandas / numpy 버전이 달라도
동일한 row 참조가 동일 문자열로 직렬화되어야 case_id / raw_hash 가 흔들리지
않는다. 본 모듈은 타입별 prefix(`n:` `b:` `i:` `f:` `d:` `ts:` `t:` `s:`) 로
원본 타입을 보존하면서 결정론적 문자열을 만든다.

타입별 규칙은 `dev/active/phase2-native-cases/v7-plan.md` 의 single source 다.
"""

from __future__ import annotations

import datetime as _dt
import math
from decimal import Decimal
from typing import Any

import pandas as pd


# Why: `bool` 은 `int` 의 subclass 라 isinstance(x, int) 가 True 가 된다.
#      bool 분기를 먼저 수행해야 b:0/b:1 코드로 수렴한다.
def canonicalize_ref_key(value: Any) -> str:
    """타입 prefix 가 붙은 결정론적 문자열을 반환한다.

    Args:
        value: row 식별자, 금액, 날짜 등 임의 스칼라/tuple 값.

    Returns:
        prefix + 정규화 본문 문자열. 동일 타입·동일 값이면 환경/버전에 무관하게
        동일 문자열을 보장한다.
    """
    # 1) Null 계열은 모두 단일 코드로 수렴 — None / NaN / NaT / pd.NA / Decimal NaN.
    if value is None:
        return "n:"
    # Decimal 의 NaN 은 pd.isna 가 ValueError 를 던지지 않지만 안전하게 우선 처리.
    if isinstance(value, Decimal):
        if value.is_nan():
            return "n:"
        return f"d:{value.normalize()}"

    # 2) bool 은 int subclass 이므로 int 보다 먼저 분기.
    if isinstance(value, (bool,)):
        return "b:1" if value else "b:0"
    # numpy.bool_ 도 동일 처리. (numpy.bool_ 는 np.generic 의 subclass)
    try:
        import numpy as np

        if isinstance(value, np.bool_):
            return "b:1" if bool(value) else "b:0"
    except ImportError:  # pragma: no cover — core 의존이라 사실상 발생 안 함.
        np = None  # type: ignore[assignment]

    # 3) tuple 은 재귀.
    if isinstance(value, tuple):
        inner = "|".join(canonicalize_ref_key(item) for item in value)
        return f"t:({inner})"

    # 4) pandas / datetime 류. pd.NaT, pd.NA 를 먼저 거른다.
    #    Why: pd.isna 는 array-like 입력에서 array 를 반환하므로 스칼라 가드 필요.
    if value is pd.NaT or value is pd.NA:
        return "n:"

    if isinstance(value, pd.Timestamp):
        # NaT 도 pd.Timestamp subclass 이므로 isna 로 한 번 더 확인.
        if pd.isna(value):
            return "n:"
        return f"ts:{value.isoformat()}"

    if isinstance(value, _dt.datetime):
        return f"ts:{value.isoformat()}"
    if isinstance(value, _dt.date):
        return f"ts:{value.isoformat()}"

    # 5) 정수: 파이썬 int + numpy 정수.
    if isinstance(value, int):
        return f"i:{int(value)}"
    if np is not None and isinstance(value, np.integer):
        return f"i:{int(value)}"

    # 6) 실수: 파이썬 float + numpy float.
    is_float = isinstance(value, float)
    if np is not None and not is_float and isinstance(value, np.floating):
        is_float = True
    if is_float:
        f_value = float(value)
        if math.isnan(f_value):
            return "n:"
        if math.isinf(f_value):
            return "f:+inf" if f_value > 0 else "f:-inf"
        return f"f:{f_value:.10g}"

    # 7) 나머지는 str() — 한글/이모지 포함 유니코드 보존.
    #    strict canonicalization: raw 문자열 "i:10" 도 "s:i:10" 로 prefix 부착.
    #    idempotency 는 호출자 책임 — Phase2RowRef.index_label invariant 에 의존.
    return "s:" + str(value)


# Why: 회계 도메인에서 "0001" 과 1 과 1.0 은 같은 line 의미. canonicalize_ref_key
# 가 보존하는 dtype prefix 차이를 흡수해 cross-reference 매칭률을 올린다.
# S4.next 의 doc_line key_mode (S4.next.2) 가 사용하지만, S4.next 본 단계는 helper 만 도입.
#
# domain prefix: line_number 가 실제로 가질 수 있는 타입.
# non-domain prefix: line_number 가 가질 수 없는 타입 (timestamp, tuple, bool, Decimal).
#   비도메인 입력은 분해하지 않고 원형 보존 — "ts:2026-01-01T00:00:00" 을 colon
#   기준으로 분해하면 "00" 같은 무의미한 결과가 나오는 것을 차단.
_DOMAIN_PREFIXES: frozenset[str] = frozenset({"n", "i", "f", "s"})


def normalize_line_number_key(canonical_key: str | None) -> str | None:
    """canonicalize_ref_key 결과를 line_number 도메인에 맞게 정규화.

    Args:
        canonical_key: ``canonicalize_ref_key`` 결과 (예: ``"s:0001"``, ``"i:1"``,
            ``"f:1.0"``, ``"n:"``) 또는 None.

    Returns:
        - None / ``""`` / ``"n:"`` → ``None``
        - ``"i:<int>"`` → ``"<int>"`` (예: ``"i:1"`` → ``"1"``)
        - ``"f:<float>"`` 정수형 → ``"<int>"`` (예: ``"f:1.0"`` → ``"1"``),
          비정수형 → ``value`` 그대로 (예: ``"f:1.5"`` → ``"1.5"``)
        - ``"s:<digits>"`` → ``"<int(digits)>"`` (선행 0 제거, 전체 0 은 ``"0"``)
        - ``"s:<non-digit>"`` → ``value`` 그대로 (colon 포함도 보존)
        - **비도메인 prefix** (``b:`` / ``d:`` / ``ts:`` / ``t:``) →
          line_number 가 가질 수 없는 타입. 원본 ``canonical_key`` 그대로 반환
          (분해하지 않음 — "ts:2026..." → "00" 같은 무의미한 cascade 차단).
        - ``":"`` 없는 입력 → 그대로 반환 (이미 정규화된 결과 또는 prefix 누락 raw).

    idempotency (invariant #43, **약화된 형태**):
        결과 문자열이 ``":"`` 를 포함하지 않으면 ``normalize(normalize(x)) == normalize(x)``
        가 보장된다. 결과에 ``":"`` 가 남는 경우 (s: prefix 제거 후 raw colon 문자열
        보존, 또는 비도메인 prefix 원형 보존) 는 두 번째 적용 시 다른 분기를 탈 수
        있어 idempotency 가 보장되지 않는다. **호출자는 결과를 한 번만 적용한다.**

    Examples:
        normalize_line_number_key("s:i:1")   == "i:1"   (raw colon-string 보존)
        normalize_line_number_key("ts:...")  == "ts:..." (비도메인 원형 보존)
        normalize_line_number_key("t:(...)") == "t:(...)" (비도메인 원형 보존)
    """
    if canonical_key is None or canonical_key == "" or canonical_key == "n:":
        return None
    # prefix 가 없으면 이미 정규화된 결과 — 그대로 반환.
    if ":" not in canonical_key:
        return canonical_key
    prefix, _, value = canonical_key.partition(":")
    # 비도메인 prefix — line_number 가 가질 수 없는 타입. 원본 그대로 반환.
    if prefix not in _DOMAIN_PREFIXES:
        return canonical_key
    if prefix == "n":
        return None
    if prefix == "i":
        # 정수 prefix — canonicalize 결과는 항상 colon 없는 정수 문자열.
        return value
    if prefix == "f":
        try:
            f_value = float(value)
        except ValueError:
            return value
        if f_value.is_integer():
            return str(int(f_value))
        return value
    # prefix == "s" — 문자열 prefix.
    # 숫자라면 int 변환으로 선행 0 제거. 그 외에는 value 원형 보존
    # (colon 포함 raw string 도 cascade 분해 없이 한 번에 처리).
    if value.isdigit():
        # 빈 문자열 lstrip 결과 보호 — 전체 0 은 "0" 유지.
        stripped = value.lstrip("0")
        return stripped if stripped else "0"
    return value
