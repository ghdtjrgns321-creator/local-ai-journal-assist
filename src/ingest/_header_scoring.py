"""구조적 헤더 스코어링 함수 — 데이터 자체의 구조 신호를 활용.

키워드 의존도를 80% → 15%로 낮추고,
타입 다양성·고유값·null 밀도 등 구조적 신호로 헤더 행을 판별한다.
"""

from __future__ import annotations

import re

import pandas as pd

# 숫자/날짜 파싱 정규식 — 순수 문자열 여부 판별용
_NUMERIC_RE = re.compile(r"^[+-]?[\d,]+\.?\d*$")
_DATE_RE = re.compile(r"^\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}$|^\d{8}$")


def _is_pure_string(val: str) -> bool:
    """값이 숫자나 날짜가 아닌 순수 문자열인지 판별."""
    stripped = val.strip()
    if not stripped:
        return False
    if _NUMERIC_RE.match(stripped):
        return False
    if _DATE_RE.match(stripped):
        return False
    # float 파싱 시도 (과학적 표기법 등 정규식으로 못 잡는 경우)
    try:
        float(stripped)
        return False
    except (ValueError, OverflowError):
        pass
    return True


def type_diversity_score(row: pd.Series) -> float:
    """헤더 행 = 100% 순수 문자열, 데이터 행 = 숫자/날짜 혼재.

    반환: 순수문자열 셀 수 / 유효 셀 수.
    """
    valid = row.dropna()
    if len(valid) == 0:
        return 0.0

    pure_str_count = sum(1 for val in valid if isinstance(val, str) and _is_pure_string(val))
    return pure_str_count / len(valid)


def uniqueness_score(row: pd.Series) -> float:
    """헤더 행 = 각 셀이 고유, 데이터 행 = 반복값 존재.

    반환: 고유값 수 / 유효 셀 수.
    """
    valid = row.dropna()
    if len(valid) == 0:
        return 0.0

    # 문자열 정규화 후 고유값 계산
    normalized = [str(v).strip().lower() for v in valid]
    return len(set(normalized)) / len(normalized)


def null_density_score(row: pd.Series, total_cols: int) -> float:
    """헤더 행 = NaN 거의 없음.

    반환: notna 수 / 전체 컬럼 수.
    """
    if total_cols <= 0:
        return 0.0
    return row.notna().sum() / total_cols
