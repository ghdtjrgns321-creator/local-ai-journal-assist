"""partner_signals — 거래처 단위 첫등장/희소/휴면재활성 3배지 검증.

Why: 옛 PHASE2 relational(R01/R05/R07) 삭제 후 base 경로 신규 구현. 배지 3종 독립·점수
     비병합·다년 전제(단일 연도 가드)·null 거래처 제외를 회귀로 잠근다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from src.detection.partner_signals import (
    BADGE_COLUMNS,
    compute_partner_signals,
)


def _settings(**overrides):
    base = {
        "partner_rare_quantile": 0.10,
        "partner_signal_min_population": 3,  # 테스트 소표본 허용
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _row(partner, year, date, gl="4000", doc="SA", debit=100.0, credit=0.0):
    return {
        "trading_partner": partner,
        "fiscal_year": year,
        "posting_date": date,
        "gl_account": gl,
        "document_type": doc,
        "debit_amount": debit,
        "credit_amount": credit,
    }


def _multi_year_df():
    """2022·2023·2024 3년. P_OLD=전 연도, P_NEW=2024만, P_DORM=2022후 공백→2024."""
    rows = [
        # P_OLD: 매년 등장 (first-seen 아님, dormant 아님)
        _row("P_OLD", 2022, "2022-03-01"),
        _row("P_OLD", 2023, "2023-03-01"),
        _row("P_OLD", 2024, "2024-03-01"),
        _row("P_OLD", 2024, "2024-06-01"),
        _row("P_OLD", 2024, "2024-09-01"),
        # P_NEW: 2024 최초 등장 (first-seen)
        _row("P_NEW", 2024, "2024-05-01"),
        # P_DORM: 2022 활동 후 2023 결번 → 2024 재등장 (직전 연도 결번)
        _row("P_DORM", 2022, "2022-01-10"),
        _row("P_DORM", 2024, "2024-02-01"),
        # 채움용 다수 거래처 (min_population 통과 + rare 분모)
        *[_row(f"P_FILL{i}", 2024, "2024-04-01") for i in range(6)],
        _row("P_FILL0", 2024, "2024-07-01"),
        _row("P_FILL0", 2024, "2024-08-01"),
    ]
    return pd.DataFrame(rows)


def test_first_seen_absent_in_prior_years():
    res = compute_partner_signals(_multi_year_df(), _settings())
    assert "P_NEW" in res.first_seen_partners
    assert "P_OLD" not in res.first_seen_partners  # 전 연도 등장
    assert "P_DORM" not in res.first_seen_partners  # 2022 등장 이력 有
    assert 0 < len(res.first_seen_partners) < 30  # 0도 전부도 아님


def test_dormant_prior_year_skipped():
    res = compute_partner_signals(_multi_year_df(), _settings())
    assert "P_DORM" in res.dormant_partners  # 2022 有·2023 결번·2024 재등장
    assert "P_OLD" not in res.dormant_partners  # 매년 활동 → 직전 연도 결번 아님


def test_dormant_reactivation_from_distant_past():
    """직직전보다 더 이전(2020)에만 활동 → 오래 결번 → 2024 재등장도 휴면재활성.

    '과거 어느 해든 활동 有' 조건이라 직직전에 국한되지 않는다(사용자 회귀).
    """
    rows = [
        _row("P_FAR", 2020, "2020-05-01"),
        _row("P_FAR", 2024, "2024-05-01"),
        *[_row(f"P_FILL{i}", 2024, "2024-04-01") for i in range(5)],
    ]
    res = compute_partner_signals(pd.DataFrame(rows), _settings())
    assert "P_FAR" in res.dormant_partners
    assert "P_FAR" not in res.first_seen_partners  # 2020 이력 有 → 첫등장 아님


def test_first_seen_and_dormant_are_disjoint():
    res = compute_partner_signals(_multi_year_df(), _settings())
    assert res.first_seen_partners.isdisjoint(res.dormant_partners)


def test_rare_below_quantile():
    res = compute_partner_signals(_multi_year_df(), _settings(partner_rare_quantile=0.5))
    # P_OLD(3건)·P_FILL0(3건)은 상위, 1건짜리(P_NEW·P_DORM·P_FILL1~5)가 rare 쪽
    assert "P_NEW" in res.rare_partners
    assert "P_OLD" not in res.rare_partners


def test_rare_empty_when_below_min_population():
    small = pd.DataFrame([_row("A", 2024, "2024-01-01"), _row("B", 2024, "2024-02-01")])
    res = compute_partner_signals(small, _settings(partner_signal_min_population=50))
    assert res.rare_partners == set()
    assert any("min_population" in w for w in res.warnings)


def test_single_year_guard_no_first_seen_or_dormant():
    single = pd.DataFrame([_row(f"P{i}", 2024, "2024-01-01") for i in range(10)])
    res = compute_partner_signals(single, _settings())
    assert res.first_seen_partners == set()
    assert res.dormant_partners == set()
    assert any("단일 연도" in w for w in res.warnings)


def test_row_badges_three_independent_columns():
    res = compute_partner_signals(_multi_year_df(), _settings())
    assert list(res.row_badges.columns) == list(BADGE_COLUMNS)
    assert res.row_badges.dtypes.apply(lambda d: d == bool).all()
    # 3 컬럼은 독립 — 한 컬럼이 다른 컬럼을 강제하지 않음
    assert res.row_badges["is_first_seen_partner"].any()


def test_null_partner_excluded():
    df = _multi_year_df()
    df = pd.concat(
        [df, pd.DataFrame([_row(None, 2024, "2024-01-01"), _row("", 2024, "2024-01-02")])],
        ignore_index=True,
    )
    res = compute_partner_signals(df, _settings())
    assert None not in res.first_seen_partners
    assert "" not in res.first_seen_partners
    # null/'' 행은 어떤 배지도 True 아님
    null_mask = df["trading_partner"].isna() | (df["trading_partner"].astype("string") == "")
    assert not res.row_badges[null_mask].to_numpy().any()


def test_partner_summary_sorted_by_amount_desc():
    df = _multi_year_df()
    res = compute_partner_signals(df, _settings())
    amounts = [r["total_amount"] for r in res.partner_summary]
    assert amounts == sorted(amounts, reverse=True)
    assert all("content_groups" in r and "signals" in r for r in res.partner_summary)


def test_missing_trading_partner_column_graceful():
    df = pd.DataFrame({"fiscal_year": [2024], "debit_amount": [1.0]})
    res = compute_partner_signals(df, _settings())
    assert res.first_seen_partners == set()
    assert list(res.row_badges.columns) == list(BADGE_COLUMNS)
    assert any("trading_partner" in w for w in res.warnings)
