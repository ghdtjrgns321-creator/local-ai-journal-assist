"""분석적 검토 탭 — 거래처 신호 빈 목록 문구가 '0건'과 '미판정'을 구분하는지 검증.

Why: 둘을 같은 문장으로 뭉개면 감사인이 "신규 거래처 없음"으로 오독한다(2026-07-25).
"""

from __future__ import annotations

from dashboard.tab_analytical import _PARTNER_SIGNAL_LABELS, _empty_partner_message


def _diag(**overrides):
    base = {
        "observed_years": [2023, 2024],
        "first_seen_evaluated": True,
        "rare_evaluated": True,
        "dormant_evaluated": True,
        "warnings": [],
    }
    base.update(overrides)
    return base


def test_first_seen_unevaluated_says_not_judged():
    msg = _empty_partner_message("first_seen", _diag(first_seen_evaluated=False))
    assert "판정하지 않았습니다" in msg
    assert "0건이라는 뜻이 아닙니다" in msg


def test_first_seen_evaluated_but_empty_says_zero():
    msg = _empty_partner_message("first_seen", _diag())
    assert "0건" in msg
    assert "판정하지 않" not in msg


def test_dormant_unevaluated_explains_year_requirement():
    msg = _empty_partner_message("dormant", _diag(dormant_evaluated=False))
    assert "직전 연도" in msg


def test_rare_unevaluated_explains_population():
    msg = _empty_partner_message("rare", _diag(rare_evaluated=False))
    assert "모집단" in msg


def test_all_filter_lists_unevaluated_signals():
    msg = _empty_partner_message(None, _diag(first_seen_evaluated=False, dormant_evaluated=False))
    assert "첫 등장" in msg
    assert "휴면재활성" in msg
    assert "나머지 신호는 0건" in msg


def test_all_filter_fully_evaluated_says_zero():
    assert "0건" in _empty_partner_message(None, _diag())


def test_missing_diagnostics_falls_back():
    """구 아티팩트(진단 필드 없음) 호환 — 단정하지 않는 중립 문구."""
    msg = _empty_partner_message("first_seen", {})
    assert "거래처 신호가 없습니다" in msg


def test_signal_labels_cover_diagnostic_keys():
    """필터 라벨과 진단 사유 표가 같은 signal 문자열을 쓴다."""
    from dashboard.tab_analytical import _PARTNER_UNEVALUATED_REASON

    signals = {v for v in _PARTNER_SIGNAL_LABELS.values() if v}
    assert signals == set(_PARTNER_UNEVALUATED_REASON)
