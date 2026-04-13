"""feature 테스트용 공통 fixture.

prefix: af_ (amount features), tf_ (time features), pf_ (pattern), xt_ (text)
"""

import numpy as np
import pandas as pd
import pytest


# ── Time features fixtures (tf_) ────────────────────────────────


@pytest.fixture()
def tf_base_df() -> pd.DataFrame:
    """시간 피처 기본 테스트용 — 주말/평일, 심야/주간, 월초/월말, 공휴일 등."""
    return pd.DataFrame({
        "posting_date": pd.to_datetime([
            "2025-01-01 10:00",   # 수요일, 신정(공휴일), 월초 1일
            "2025-01-04 23:30",   # 토요일, 심야
            "2025-01-05 03:00",   # 일요일, 심야
            "2025-01-06 14:00",   # 월요일, 평일 주간, 월초 6일(margin 밖)
            "2025-01-28 09:00",   # 화요일, 월말 3일전
            "2025-01-31 17:00",   # 금요일, 월말 당일
            "2025-02-28 12:00",   # 금요일, 2월 말(평년)
            "2025-03-01 08:00",   # 토요일, 3월 1일(삼일절 공휴일), 익월초
        ]),
        "document_date": pd.to_datetime([
            "2025-01-01",         # 당일 → 0
            "2024-12-30",         # 5일 지연 → +5
            "2025-01-10",         # 선전기 → -5
            "2025-01-06",         # 당일 → 0
            "2025-01-28",         # 당일 → 0
            "2025-01-25",         # 6일 지연 → +6
            None,                 # NaT → NaN
            "2025-03-01",         # 당일 → 0
        ]),
        "fiscal_period": pd.array([1, 1, 1, 1, 1, 1, 2, 3], dtype="Int64"),
    })


@pytest.fixture()
def tf_no_time_df() -> pd.DataFrame:
    """시간정보 없는 DataFrame (날짜만, 00:00:00)."""
    return pd.DataFrame({
        "posting_date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
    })


@pytest.fixture()
def tf_nat_df() -> pd.DataFrame:
    """posting_date가 전부 NaT인 DataFrame."""
    return pd.DataFrame({
        "posting_date": pd.to_datetime([None, None]),
        "document_date": pd.to_datetime([None, None]),
        "fiscal_period": pd.array([pd.NA, pd.NA], dtype="Int64"),
    })


# ── Amount features fixtures (af_) ──────────────────────────────


@pytest.fixture
def af_basic_df() -> pd.DataFrame:
    """5건, 다양한 금액 — 기본 기능 검증용."""
    return pd.DataFrame({
        "debit_amount": [45_000_000, 0, 1_000_000, 0, 10_000_000],
        "credit_amount": [0, 55_000_000, 0, 0, 0],
        "gl_account": ["1000", "1000", "2000", "2000", "1000"],
    })


@pytest.fixture
def af_zscore_df() -> pd.DataFrame:
    """35건(큰 그룹) + 5건(작은 그룹) — Z-score fallback 테스트."""
    rng = np.random.default_rng(42)
    # 큰 그룹: gl_account "A", 35건, 평균 10M 부근
    large = pd.DataFrame({
        "debit_amount": rng.normal(10_000_000, 2_000_000, 35).clip(0),
        "credit_amount": np.zeros(35),
        "gl_account": ["A"] * 35,
    })
    # 작은 그룹: gl_account "B", 5건
    small = pd.DataFrame({
        "debit_amount": [5_000_000, 6_000_000, 7_000_000, 8_000_000, 9_000_000],
        "credit_amount": np.zeros(5),
        "gl_account": ["B"] * 5,
    })
    return pd.concat([large, small], ignore_index=True)


@pytest.fixture
def af_edge_df() -> pd.DataFrame:
    """NaN, 0, 둘다NaN 등 엣지케이스."""
    return pd.DataFrame({
        "debit_amount": [np.nan, 0, np.nan, 1_000_000],
        "credit_amount": [5_000_000, 0, np.nan, np.nan],
        "gl_account": ["X", "X", "X", "X"],
    })


@pytest.fixture
def af_uniform_df() -> pd.DataFrame:
    """모든 금액 동일 (std=0) — ZeroDivisionError 방지 테스트."""
    n = 35
    return pd.DataFrame({
        "debit_amount": [10_000_000.0] * n,
        "credit_amount": [0.0] * n,
        "gl_account": ["U"] * n,
    })


@pytest.fixture
def af_coa_fallback_df() -> pd.DataFrame:
    """CoA fallback 테스트: 큰 그룹 A(35건, 1xxx=자산), 작은 그룹 B(5건, 1xxx=자산), 작은 그룹 C(5건, 4xxx=수익).

    B그룹은 A그룹과 같은 CoA(자산, 총 40건) → CoA 통계 fallback.
    C그룹은 CoA(수익) 내에서도 5건뿐 → 전체 데이터 fallback.
    """
    rng = np.random.default_rng(42)
    large_a = pd.DataFrame({
        "debit_amount": rng.normal(10_000_000, 2_000_000, 35).clip(0),
        "credit_amount": np.zeros(35),
        "gl_account": ["1000"] * 35,
    })
    small_b = pd.DataFrame({
        "debit_amount": [5_000_000, 6_000_000, 7_000_000, 8_000_000, 9_000_000],
        "credit_amount": np.zeros(5),
        "gl_account": ["1200"] * 5,
    })
    small_c = pd.DataFrame({
        "debit_amount": [50_000_000, 60_000_000, 70_000_000, 80_000_000, 90_000_000],
        "credit_amount": np.zeros(5),
        "gl_account": ["4100"] * 5,
    })
    return pd.concat([large_a, small_b, small_c], ignore_index=True)


# ── Pattern features fixtures (pf_) ─────────────────────────────


@pytest.fixture
def pf_basic_df() -> pd.DataFrame:
    """패턴 피처 기본 테스트용 — source, gl_account, company_code, 텍스트 컬럼."""
    return pd.DataFrame({
        "source": ["SA", "AUTO", "Manual", "수기", None],
        "gl_account": pd.array([4100, 1200, 4200, 9100, None], dtype="Int64"),
        "company_code": ["HQ", "SUB01", "HQ", "INTER", "HQ"],
        "debit_amount": [1500.0, 200.0, 0.005, 0.0, -3000.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
        "line_text": ["가수금 정리", "매출 입금", "가지급금 반환", "일반 전표", "미결산 항목"],
        "header_text": ["월말 정리", "정상 거래", "임시 처리", "일반", "결산"],
    })


@pytest.fixture
def pf_minimal_df() -> pd.DataFrame:
    """최소 컬럼 — source, gl_account 등이 없는 DataFrame."""
    return pd.DataFrame({
        "debit_amount": [1000.0, 2000.0],
        "credit_amount": [0.0, 0.0],
    })


# ── Text features fixtures (xt_) ────────────────────────────────


@pytest.fixture
def xt_base_df() -> pd.DataFrame:
    """텍스트 피처 기본 케이스 — high/medium/low, missing/poor/normal, concat 구제."""
    return pd.DataFrame({
        "line_text": [
            "상품권 구매",       # high risk, normal quality
            "잡손실 처리",       # medium risk, normal quality
            "일반 매출",         # low risk, normal quality
            None,               # missing (header로 구제)
            None,               # missing (둘 다 None)
            "AB",               # poor (len=2 < 3)
            "식대",             # line만 있으면 poor(len=2), header와 concat→normal
        ],
        "header_text": [
            "월말 정리",
            "결산 조정",
            None,
            "3월 영업부 법인카드",  # header로 구제 → normal
            None,
            None,
            "3월 영업부 법인카드",  # concat → "식대 3월 영업부 법인카드" → normal
        ],
    })


@pytest.fixture
def xt_noise_df() -> pd.DataFrame:
    """노이즈 패턴 — 자음만, 특수문자만, 반복문자."""
    return pd.DataFrame({
        "line_text": ["ㅋㅋㅋ", "...", "aaa", "ㅎㅎ", "정상 적요"],
        "header_text": [None, None, None, None, None],
    })


@pytest.fixture
def xt_obfuscated_df() -> pd.DataFrame:
    """은폐 패턴 — 공백·특수문자로 키워드 위장."""
    return pd.DataFrame({
        "line_text": ["상 품 권", "[상품권]", "상품/권", "가 수 금", "일반매출"],
        "header_text": [None, None, None, None, None],
    })


@pytest.fixture
def xt_no_text_cols_df() -> pd.DataFrame:
    """텍스트 컬럼 없는 DataFrame."""
    return pd.DataFrame({
        "debit_amount": [1000.0, 2000.0],
        "credit_amount": [0.0, 0.0],
    })


# ── Engine fixtures (en_) ────────────────────────────────────────


@pytest.fixture
def en_full_df() -> pd.DataFrame:
    """엔진 풀 스펙 — 모든 서브모듈에 필요한 10개 입력 컬럼 (3행)."""
    return pd.DataFrame({
        "posting_date": pd.to_datetime([
            "2025-01-04 23:30",   # 토요일, 심야
            "2025-01-06 14:00",   # 월요일, 평일
            "2025-01-31 17:00",   # 금요일, 월말
        ]),
        "document_date": pd.to_datetime([
            "2024-12-30",         # 5일 지연
            "2025-01-06",         # 당일
            "2025-01-25",         # 6일 지연
        ]),
        "fiscal_period": pd.array([1, 1, 1], dtype="Int64"),
        "debit_amount": [45_000_000.0, 1_000_000.0, 10_000_000.0],
        "credit_amount": [0.0, 0.0, 0.0],
        "gl_account": pd.array([4100, 1200, 9100], dtype="Int64"),
        "source": ["SA", "AUTO", "Manual"],
        "company_code": ["HQ", "SUB01", "INTER"],
        "line_text": ["가수금 정리", "매출 입금", "일반 전표"],
        "header_text": ["월말 정리", "정상 거래", "일반"],
    })


@pytest.fixture
def en_minimal_df() -> pd.DataFrame:
    """엔진 최소 컬럼 — posting_date + 금액만 (1행). graceful 처리 검증."""
    return pd.DataFrame({
        "posting_date": pd.to_datetime(["2025-01-06 14:00"]),
        "debit_amount": [5_000_000.0],
        "credit_amount": [0.0],
    })
