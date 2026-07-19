"""K-IFRS 계정과목 카테고리 분류 헬퍼.

Why: chart_of_accounts.csv 의 gl_account 첫 자리수가 K-IFRS 표준 분류와 일치한다.
     전기 비교(분석적 절차, ISA 520)에서 자산/부채/자본/매출/원가/판관비 단위 변동을
     보여주기 위해 한 곳에서 매핑을 캐싱한다.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

# Why: 첫 자리수가 곧 한국 회계 계정과목 대분류. 9 는 가계정/임시계정으로 분리.
_CATEGORY_LABELS: dict[str, str] = {
    "1": "자산",
    "2": "부채",
    "3": "자본",
    "4": "매출/수익",
    "5": "매출원가",
    "6": "판매비와관리비",
    "7": "영업외/금융",
    "8": "법인세",
    "9": "가/임시 계정",
}

# Why: 자산·부채·자본은 잔액(stock), 손익은 흐름(flow). UI 색상도 두 그룹으로 분리.
_CATEGORY_KIND: dict[str, str] = {
    "1": "BS",
    "2": "BS",
    "3": "BS",
    "4": "PL",
    "5": "PL",
    "6": "PL",
    "7": "PL",
    "8": "PL",
    "9": "OTHER",
}

# Why: 카테고리별 시각 색상. BS = 슬레이트 계열, PL = 인디고-바이올렛 계열.
CATEGORY_COLORS: dict[str, str] = {
    "자산": "#0F766E",  # teal-700
    "부채": "#B91C1C",  # red-700
    "자본": "#1D4ED8",  # blue-700
    "매출/수익": "#7C3AED",  # violet-600
    "매출원가": "#C2410C",  # orange-700
    "판매비와관리비": "#A16207",  # amber-700
    "영업외/금융": "#0E7490",  # cyan-700
    "법인세": "#4338CA",  # indigo-700
    "당기순이익": "#111827",  # gray-900 — K-IFRS 손익 최종 단계 (derived)
    "가/임시 계정": "#6B7280",  # gray-500
}

# Why: 표시 순서 — BS 3종 → PL 손익단계 → 가/임시. 사용자 지시로 당기순이익을
#      법인세 위(영업외/금융 바로 밑)에 배치한다. 누락 카테고리는 자동 제외.
CATEGORY_ORDER: list[str] = [
    "자산",
    "부채",
    "자본",
    "매출/수익",
    "매출원가",
    "판매비와관리비",
    "영업외/금융",
    "당기순이익",
    "법인세",
    "가/임시 계정",
]

# Why: 당기순이익은 derived row — 다른 카테고리처럼 첫자리 매핑이 없다.
#      _aggregate_categories 에서 매출∼법인세 net 으로 계산해 별도 row 로 추가.
DERIVED_NET_INCOME_LABEL = "당기순이익"


def category_label(gl_account: str | int | None) -> str:
    """gl_account 의 첫 자리수로 K-IFRS 대분류 라벨을 반환.

    None / 공백 / 비숫자 시작 시 '미분류' 반환.
    """
    if gl_account is None:
        return "미분류"
    text = str(gl_account).strip()
    if not text or not text[0].isdigit():
        return "미분류"
    return _CATEGORY_LABELS.get(text[0], "미분류")


def category_kind(gl_account: str | int | None) -> str:
    """B/S vs P/L vs OTHER 구분. flux 차트 그룹화에 사용."""
    if gl_account is None:
        return "OTHER"
    text = str(gl_account).strip()
    if not text or not text[0].isdigit():
        return "OTHER"
    return _CATEGORY_KIND.get(text[0], "OTHER")


@lru_cache(maxsize=1)
def account_name_lookup() -> dict[str, str]:
    """gl_account → 한국어 계정명 매핑 (config/chart_of_accounts.csv 캐시).

    Why: tab_phase1 에 동일 함수가 있으나 그쪽은 cache_resource 라 모듈 외부에서
         재사용이 까다롭다. 비교 탭은 streamlit 없이도 호출되는 helper 가 필요.
    """
    coa_path = Path(__file__).resolve().parent.parent.parent / "config" / "chart_of_accounts.csv"
    if not coa_path.exists():
        return {}
    lookup: dict[str, str] = {}
    with open(coa_path, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = (row.get("gl_account") or "").strip()
            name = (row.get("account_name_kr") or "").strip()
            if code and name:
                lookup[code] = name
    return lookup


def account_display(gl_account: str | int | None) -> str:
    """`{코드} {한국어명}` 형식. 한국어명 없으면 코드만 반환."""
    if gl_account is None:
        return ""
    code = str(gl_account).strip()
    if not code:
        return ""
    name = account_name_lookup().get(code, "")
    return f"{code} {name}" if name else code
