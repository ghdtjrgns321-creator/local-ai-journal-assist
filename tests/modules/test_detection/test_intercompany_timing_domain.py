"""IC timing_prob 도메인 분리 테스트.

target: compute_probabilistic_pair_scores 의 ic_timing_prob 가 audit evidence 의미로
        구분되는지 검증.
        - 정상 결산 close lag (월말 ↔ 다음달 초) → grace = 0
        - amount/cp/ref 모두 strong + 큰 시차 → weak_cap 이하
        - timing-only large gap → strong evidence 차단 (raw)
        - timing 단독 high 금지

핵심 가설 (artifacts/ic_timing_prob_diagnosis_20260524.md):
- 합성 데이터의 정상 IC timing_prob 1.0 normal 2,432 docs 중 36% 가 월말±7일 / 월초±7일
  close lag 패턴.
- amount 는 매우 잘 일치 (amount_prob mean 0.04 → amount_sim ≈ 0.96).
- match_score 0.60 (unmatched_prob mean 0.40) — 다른 component 도 양호.
- 즉 timing 단독 strong evidence 로 박는 게 false-positive 원인.
"""

from __future__ import annotations

import pandas as pd

from config.settings import AuditSettings
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.intercompany_rules import (
    _domain_timing_prob,
    _is_month_close_lag,
    compute_probabilistic_pair_scores,
    load_candidate_blocking,
    load_contract_score_caps,
    load_matching_weights,
    load_timing_domain,
)

AUDIT_RULES = {
    "patterns": {
        "intercompany": {
            "pairs": [
                {"receivable": "1150", "payable": "2050"},
                {"receivable": "4500", "payable": "2700"},
            ],
            "partner_format": {
                "ic_partner_regex": r"^[A-Za-z]\d{3}$|^[A-Za-z]$|^IC-[A-Z]\d{3}$",
            },
        },
    },
}


def _settings(**overrides) -> AuditSettings:
    base = {"ic_min_ic_rows": 1}
    base.update(overrides)
    return AuditSettings(**base)


def _prob_call(df: pd.DataFrame, settings: AuditSettings, audit_rules: dict):
    weights = load_matching_weights(audit_rules, settings)
    blocking = load_candidate_blocking(audit_rules, settings)
    caps = load_contract_score_caps(audit_rules, settings)
    timing_domain = load_timing_domain(audit_rules, settings)
    pair_map = {"1150": "2050", "2050": "1150", "4500": "2700", "2700": "4500"}
    return compute_probabilistic_pair_scores(
        df,
        pair_map,
        weights=weights,
        blocking=blocking,
        max_day_diff=settings.ic_max_day_diff,
        caps=caps,
        timing_domain=timing_domain,
    )


def _wrap_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["posting_date"] = pd.to_datetime(df["posting_date"])
    df["is_intercompany"] = (
        df["gl_account"].astype(str).str.startswith(("1150", "2050", "4500", "2700"))
    )
    if "currency" not in df.columns:
        df["currency"] = "KRW"
    return df


def _ic_row(
    *,
    doc: str,
    company: str,
    partner: str,
    gl: str,
    debit: float = 0.0,
    credit: float = 0.0,
    posting_date: str,
    reference: str = "",
) -> dict:
    return {
        "document_id": doc,
        "company_code": company,
        "trading_partner": partner,
        "gl_account": gl,
        "debit_amount": debit,
        "credit_amount": credit,
        "posting_date": posting_date,
        "reference": reference,
    }


# ── helper unit tests ──────────────────────────────────────────────


class TestMonthCloseLag:
    """_is_month_close_lag 단위."""

    def test_rec_eom_pay_bom_within_grace_true(self):
        # rec 6/30 + pay 7/3 (3일 차이)
        rec = pd.Timestamp("2024-06-30")
        pay = pd.Timestamp("2024-07-03")
        assert _is_month_close_lag(rec, pay, grace_window_days=14, month_end_window_days=7)

    def test_pay_eom_rec_bom_within_grace_true(self):
        # pay 5/31 + rec 6/2 (2일)
        rec = pd.Timestamp("2024-06-02")
        pay = pd.Timestamp("2024-05-31")
        assert _is_month_close_lag(rec, pay, grace_window_days=14, month_end_window_days=7)

    def test_mid_month_pair_false(self):
        rec = pd.Timestamp("2024-06-15")
        pay = pd.Timestamp("2024-06-25")
        assert not _is_month_close_lag(rec, pay, grace_window_days=14, month_end_window_days=7)

    def test_over_grace_window_false(self):
        rec = pd.Timestamp("2024-06-30")
        pay = pd.Timestamp("2024-07-20")
        assert not _is_month_close_lag(rec, pay, grace_window_days=14, month_end_window_days=7)

    def test_grace_disabled_false(self):
        rec = pd.Timestamp("2024-06-30")
        pay = pd.Timestamp("2024-07-03")
        assert not _is_month_close_lag(rec, pay, grace_window_days=0, month_end_window_days=7)


class TestDomainTimingProb:
    """_domain_timing_prob 단위."""

    PARAMS = {
        "grace_window_days": 14,
        "month_end_window_days": 7,
        "amount_strong_min": 0.95,
        "cp_strong_min": 0.5,
        "ref_strong_min": 0.7,
        "only_weak_cap": 0.3,
    }

    def test_close_lag_returns_zero(self):
        v = _domain_timing_prob(
            raw_timing=1.0,
            amount_sim=0.98,
            cp_score=1.0,
            reference_sim=0.8,
            pair_ref_active=True,
            rec_date=pd.Timestamp("2024-06-30"),
            pay_date=pd.Timestamp("2024-07-03"),
            timing_params=self.PARAMS,
        )
        assert v == 0.0

    def test_all_strong_match_caps_to_weak(self):
        v = _domain_timing_prob(
            raw_timing=0.9,
            amount_sim=0.99,
            cp_score=1.0,
            reference_sim=0.85,
            pair_ref_active=True,
            rec_date=pd.Timestamp("2024-03-15"),  # mid-month → no grace
            pay_date=pd.Timestamp("2024-05-15"),
            timing_params=self.PARAMS,
        )
        assert v == self.PARAMS["only_weak_cap"]

    def test_amount_mismatch_keeps_raw_strong(self):
        v = _domain_timing_prob(
            raw_timing=0.9,
            amount_sim=0.5,
            cp_score=1.0,
            reference_sim=0.9,
            pair_ref_active=True,
            rec_date=pd.Timestamp("2024-03-15"),
            pay_date=pd.Timestamp("2024-05-15"),
            timing_params=self.PARAMS,
        )
        assert v == 0.9

    def test_weak_counterparty_keeps_raw_strong(self):
        v = _domain_timing_prob(
            raw_timing=0.9,
            amount_sim=0.99,
            cp_score=0.0,
            reference_sim=0.85,
            pair_ref_active=True,
            rec_date=pd.Timestamp("2024-03-15"),
            pay_date=pd.Timestamp("2024-05-15"),
            timing_params=self.PARAMS,
        )
        assert v == 0.9

    def test_inactive_reference_not_treated_as_strong(self):
        # pair_ref_active=False → reference 강한 매칭 판정 불가 → raw 유지
        v = _domain_timing_prob(
            raw_timing=0.9,
            amount_sim=0.99,
            cp_score=1.0,
            reference_sim=0.0,
            pair_ref_active=False,
            rec_date=pd.Timestamp("2024-03-15"),
            pay_date=pd.Timestamp("2024-05-15"),
            timing_params=self.PARAMS,
        )
        assert v == 0.9

    def test_raw_zero_returns_zero(self):
        v = _domain_timing_prob(
            raw_timing=0.0,
            amount_sim=0.99,
            cp_score=1.0,
            reference_sim=0.85,
            pair_ref_active=True,
            rec_date=pd.Timestamp("2024-06-30"),
            pay_date=pd.Timestamp("2024-07-03"),
            timing_params=self.PARAMS,
        )
        assert v == 0.0


# ── integration with compute_probabilistic_pair_scores ────────────


class TestProbabilisticTimingIntegration:
    """compute_probabilistic_pair_scores 통합 — settings 기본값 적용."""

    def test_normal_close_lag_high_match_timing_zero(self):
        """receivable 6/30 + payable 7/03, amount/partner/ref 모두 강한 매칭 → timing 0."""
        rows = [
            _ic_row(
                doc="D-rec",
                company="C001",
                partner="C002",
                gl="1150",
                debit=100_000_000,
                posting_date="2024-06-30",
                reference="INV-001",
            ),
            _ic_row(
                doc="D-pay",
                company="C002",
                partner="C001",
                gl="2050",
                credit=100_000_000,
                posting_date="2024-07-03",
                reference="INV-001",
            ),
        ]
        df = _wrap_df(rows)
        scores, summary = _prob_call(df, _settings(), AUDIT_RULES)
        # 두 row 모두 timing_prob 0
        assert (scores["ic_timing_prob"] == 0.0).all()
        assert summary["timing_grace_hits"] >= 1

    def test_mid_month_large_gap_strong_match_capped_to_weak(self):
        """mid-month large timing gap + amount/cp/ref 강한 매칭 → weak_cap.

        Why: blocking join 이 day_diff > max_day_diff (30 일) 인 candidate 를 prune
             하므로 timing 계산이 발생하는 최대 시차는 max_day_diff. 25 일 시차로
             설정해 candidate matching 후 timing_prob 가 산출되도록 한다.
        """
        rows = [
            _ic_row(
                doc="D-rec",
                company="C001",
                partner="C002",
                gl="1150",
                debit=100_000_000,
                posting_date="2024-03-15",
                reference="INV-002",
            ),
            _ic_row(
                doc="D-pay",
                company="C002",
                partner="C001",
                gl="2050",
                credit=100_000_000,
                posting_date="2024-04-09",  # 25일 시차 — max_day_diff 30 이하라 candidate 유지
                reference="INV-002",
            ),
        ]
        df = _wrap_df(rows)
        scores, summary = _prob_call(df, _settings(), AUDIT_RULES)
        cap = _settings().ic_timing_only_weak_cap
        # 모든 timing > 0 row 가 cap 이하
        nonzero = scores[scores["ic_timing_prob"] > 0]
        assert (nonzero["ic_timing_prob"] <= cap + 1e-9).all()
        assert summary["timing_weak_cap_hits"] >= 1

    def test_large_gap_with_amount_mismatch_keeps_raw(self):
        """timing + amount mismatch → raw timing (strong evidence)."""
        rows = [
            _ic_row(
                doc="D-rec",
                company="C001",
                partner="C002",
                gl="1150",
                debit=100_000_000,
                posting_date="2024-03-15",
                reference="INV-003",
            ),
            _ic_row(
                doc="D-pay",
                company="C002",
                partner="C001",
                gl="2050",
                credit=60_000_000,  # 40% mismatch
                posting_date="2024-04-09",  # 25일 시차 — candidate 유지
                reference="INV-003",
            ),
        ]
        df = _wrap_df(rows)
        scores, _ = _prob_call(df, _settings(), AUDIT_RULES)
        # weak_cap 0.3 이하로 떨어지지 않는다 (raw 유지)
        cap = _settings().ic_timing_only_weak_cap
        nonzero = scores[scores["ic_timing_prob"] > 0]
        assert (nonzero["ic_timing_prob"] > cap).all()

    def test_no_candidate_timing_remains_zero(self):
        """receivable 만 있고 payable 없음 → no_candidate, timing_prob = 0."""
        rows = [
            _ic_row(
                doc="D-rec",
                company="C001",
                partner="C002",
                gl="1150",
                debit=100_000_000,
                posting_date="2024-03-15",
                reference="INV-004",
            ),
        ]
        df = _wrap_df(rows)
        scores, _ = _prob_call(df, _settings(), AUDIT_RULES)
        assert (scores["ic_timing_prob"] == 0.0).all()

    def test_phase1_columns_do_not_influence(self):
        """flagged_rules / priority_score / review_rules 주입해도 timing_prob 동일."""
        rows = [
            _ic_row(
                doc="D-rec",
                company="C001",
                partner="C002",
                gl="1150",
                debit=100_000_000,
                posting_date="2024-03-15",
                reference="INV-005",
            ),
            _ic_row(
                doc="D-pay",
                company="C002",
                partner="C001",
                gl="2050",
                credit=60_000_000,
                posting_date="2024-05-15",
                reference="INV-005",
            ),
        ]
        df_base = _wrap_df(rows)
        df_inj = df_base.copy()
        df_inj["flagged_rules"] = "L3-03,L4-05"
        df_inj["priority_score"] = 0.85
        df_inj["review_rules"] = "IC01"
        df_inj["is_fraud"] = True
        df_inj["is_anomaly"] = True
        df_inj["mutation_type"] = "circular"
        df_inj["manipulation_scenario"] = "x"

        s_base, _ = _prob_call(df_base, _settings(), AUDIT_RULES)
        s_inj, _ = _prob_call(df_inj, _settings(), AUDIT_RULES)
        pd.testing.assert_series_equal(s_base["ic_timing_prob"], s_inj["ic_timing_prob"])


class TestMatcherTimingDomain:
    """IntercompanyMatcher 통합 — timing_domain 자동 로드 + metadata."""

    def test_summary_timing_metadata_present(self):
        rows = [
            _ic_row(
                doc="D-r",
                company="C001",
                partner="C002",
                gl="1150",
                debit=100_000_000,
                posting_date="2024-06-30",
                reference="INV-1",
            ),
            _ic_row(
                doc="D-p",
                company="C002",
                partner="C001",
                gl="2050",
                credit=100_000_000,
                posting_date="2024-07-03",
                reference="INV-1",
            ),
        ]
        df = _wrap_df(rows)
        det = IntercompanyMatcher(settings=_settings(), audit_rules=AUDIT_RULES)
        result = det.detect(df)
        prob_summary = result.metadata.get("probabilistic_reconciliation", {})
        assert "timing_domain" in prob_summary
        assert "timing_grace_hits" in prob_summary
        assert "timing_weak_cap_hits" in prob_summary

    def test_timing_legacy_passthrough_when_settings_disabled(self):
        """settings 임계값을 비활성화하면 raw timing 으로 복귀 가능."""
        # grace 비활성 (window=0) + cap 1.0 → legacy 동작
        s = _settings(
            ic_timing_grace_window_days=0,
            ic_timing_month_end_window_days=0,
            ic_timing_only_weak_cap=1.0,
            ic_timing_amount_strong_min=2.0,  # 절대 만족 안 됨
        )
        rows = [
            _ic_row(
                doc="D-r",
                company="C001",
                partner="C002",
                gl="1150",
                debit=100_000_000,
                posting_date="2024-06-30",
                reference="INV-1",
            ),
            _ic_row(
                doc="D-p",
                company="C002",
                partner="C001",
                gl="2050",
                credit=100_000_000,
                posting_date="2024-07-29",  # 29일 시차 (max_day_diff 30 이하 candidate 유지)
                reference="INV-1",
            ),
        ]
        df = _wrap_df(rows)
        scores, _ = _prob_call(df, s, AUDIT_RULES)
        # legacy 동작 = raw timing 유지 (29/30 = 0.967)
        assert scores["ic_timing_prob"].max() >= 0.9
