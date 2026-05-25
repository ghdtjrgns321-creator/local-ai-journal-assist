"""PHASE2 sub-detector evidence_tier YAML schema 강제 테스트.

config/phase2_subdetector_tiers.yaml 변경 시 본 테스트가 통과해야 한다.
- 21 sub-detector cover
  (1 unsupervised + 2 timeseries + 7 relational + 4 duplicate + 7 intercompany).
  relational R05~R07은 graph/entity anomaly 보강 (2026-05-24).
  intercompany ic_reciprocal_flow_prob / ic_amount_prob / ic_unmatched_prob /
  ic_timing_prob 는 PHASE2 internal probability surface evidence_role 노출용
  (2026-05-25 등록, lane sort ic_role_priority 차원).
- tier ∈ {strong, moderate, weak, ml_quantile}
- source_type ∈ {standard, distribution}
- source_citation, distribution_metric, rationale 비어 있지 않음
- 중복 entry 차단

본 파일은 truth recall 향상 목적 가드와 관계 없다. tier 정의 일관성만 검증한다.
"""

from __future__ import annotations

import pytest

from src.services.subdetector_tiers import (
    TIER_ORDER,
    SubdetectorTier,
    load_subdetector_tiers,
    max_tier_weight,
)

REQUIRED_KEYS: frozenset[tuple[str, str]] = frozenset(
    {
        ("unsupervised", "VAE-01"),
        ("timeseries", "TS01"),
        ("timeseries", "TS02"),
        ("relational", "R01"),
        ("relational", "R02"),
        ("relational", "R03"),
        ("relational", "R04"),
        ("relational", "R05"),
        ("relational", "R06"),
        ("relational", "R07"),
        ("duplicate", "L2-03a"),
        ("duplicate", "L2-03b"),
        ("duplicate", "L2-03c"),
        ("duplicate", "L2-03d"),
        ("intercompany", "IC01"),
        ("intercompany", "IC02"),
        ("intercompany", "IC03"),
        ("intercompany", "ic_reciprocal_flow_prob"),
        ("intercompany", "ic_amount_prob"),
        ("intercompany", "ic_unmatched_prob"),
        ("intercompany", "ic_timing_prob"),
    }
)


@pytest.fixture(scope="module")
def tier_index() -> dict[tuple[str, str], SubdetectorTier]:
    return load_subdetector_tiers()


class TestCoverage:
    def test_all_21_sub_detectors_present(self, tier_index):
        actual = set(tier_index.keys())
        missing = REQUIRED_KEYS - actual
        extra = actual - REQUIRED_KEYS
        assert not missing, f"missing sub_detectors: {sorted(missing)}"
        assert not extra, f"extra sub_detectors not allowed: {sorted(extra)}"

    def test_no_duplicate_keys(self, tier_index):
        assert len(tier_index) == 21


class TestTierValues:
    def test_all_tiers_in_allowed_set(self, tier_index):
        allowed = set(TIER_ORDER)
        for key, item in tier_index.items():
            assert item.tier in allowed, f"{key} invalid tier={item.tier}"

    def test_vae_01_is_ml_quantile(self, tier_index):
        assert tier_index[("unsupervised", "VAE-01")].tier == "ml_quantile"

    def test_rule_style_uses_only_rule_tiers(self, tier_index):
        rule_tiers = {"strong", "moderate", "weak"}
        for key, item in tier_index.items():
            if key == ("unsupervised", "VAE-01"):
                continue
            assert item.tier in rule_tiers, (
                f"{key} rule-style must use {rule_tiers}, got {item.tier}"
            )


class TestSourceFields:
    def test_source_type_allowed(self, tier_index):
        allowed = {"standard", "distribution"}
        for key, item in tier_index.items():
            assert item.source_type in allowed, f"{key} invalid source_type={item.source_type}"

    def test_source_citation_non_empty(self, tier_index):
        for key, item in tier_index.items():
            assert item.source_citation, f"{key} source_citation empty"
            assert len(item.source_citation) >= 20, f"{key} source_citation too short"

    def test_distribution_metric_non_empty(self, tier_index):
        for key, item in tier_index.items():
            assert item.distribution_metric, f"{key} distribution_metric empty"

    def test_rationale_non_empty(self, tier_index):
        for key, item in tier_index.items():
            assert item.rationale, f"{key} rationale empty"


class TestStrongTierStandardBacking:
    def test_strong_tier_must_have_standard_or_explicit_distribution(self, tier_index):
        """strong tier 는 기준서 인용 또는 명시적 분포 근거 필수."""
        for key, item in tier_index.items():
            if item.tier == "strong":
                has_standard = item.source_type == "standard"
                has_distribution = (
                    "AUROC" in item.source_citation
                    or "AUROC" in item.distribution_metric
                    or "row_nonzero" in item.distribution_metric
                    or "hit=" in item.distribution_metric
                )
                assert has_standard or has_distribution, (
                    f"{key} strong tier 는 standard 인용 또는 명시적 분포 근거 필요"
                )


class TestTimeseriesRoleLock:
    """결정 9 (2026-05-25): timeseries family 는 context lane 으로 역할 고정.

    TS01/TS02 단독 ranker 추격(특히 TOP100/500 recall 튜닝)을 yaml 단에서 차단.
    docs/PHASE2_TIMESERIES_ROLE_LOCK.md 변경 절차 통과 없이 수정 금지.
    """

    def test_ts01_role_lock_is_context_lane(self, tier_index):
        ts01 = tier_index[("timeseries", "TS01")]
        assert ts01.role_lock == "context_lane"
        assert ts01.is_context_lane_locked

    def test_ts02_role_lock_is_context_lane(self, tier_index):
        ts02 = tier_index[("timeseries", "TS02")]
        assert ts02.role_lock == "context_lane"
        assert ts02.is_context_lane_locked

    def test_ts01_do_not_tune_for_top_recall(self, tier_index):
        assert tier_index[("timeseries", "TS01")].do_not_tune_for_top_recall is True

    def test_ts02_do_not_tune_for_top_recall(self, tier_index):
        assert tier_index[("timeseries", "TS02")].do_not_tune_for_top_recall is True

    def test_ts_ranker_use_top2000_plus(self, tier_index):
        for code in ("TS01", "TS02"):
            assert tier_index[("timeseries", code)].ranker_use == "top2000_plus_context"

    def test_ts_coverage_profile_present(self, tier_index):
        for code in ("TS01", "TS02"):
            profile = tier_index[("timeseries", code)].coverage_profile
            assert profile and len(profile) >= 20, f"TS {code} coverage_profile 누락/짧음"

    def test_ts_batch_local_ecdf_caveat_present(self, tier_index):
        for code in ("TS01", "TS02"):
            caveat = tier_index[("timeseries", code)].batch_local_ecdf_caveat
            assert caveat and "baseline" in caveat, (
                f"TS {code} batch_local_ecdf_caveat 에 baseline 한계 명시 필요"
            )

    def test_non_timeseries_families_have_no_role_lock(self, tier_index):
        """결정 9 lock 은 timeseries 한정 — 다른 family 는 None 이어야 함."""
        for key, item in tier_index.items():
            if key[0] == "timeseries":
                continue
            assert item.role_lock is None, (
                f"{key} role_lock 은 timeseries 외 family 에서 설정 금지 (결정 9 범위)"
            )
            assert item.do_not_tune_for_top_recall is False


class TestTierWeightHelper:
    def test_tier_order_monotonic(self):
        assert TIER_ORDER["strong"] > TIER_ORDER["moderate"]
        assert TIER_ORDER["moderate"] > TIER_ORDER["weak"]
        assert TIER_ORDER["weak"] > TIER_ORDER["ml_quantile"]

    def test_max_tier_weight_picks_strong(self):
        codes = [("duplicate", "L2-03a"), ("duplicate", "L2-03d"), ("timeseries", "TS02")]
        assert max_tier_weight(codes) == TIER_ORDER["strong"]

    def test_max_tier_weight_empty(self):
        assert max_tier_weight([]) == 0

    def test_max_tier_weight_unknown_codes_ignored(self):
        codes = [("phantom", "FAKE-99"), ("duplicate", "L2-03c")]
        assert max_tier_weight(codes) == TIER_ORDER["moderate"]
