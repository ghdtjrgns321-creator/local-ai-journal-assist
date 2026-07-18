"""topic_scoring standalone 게이트 계약 (tier 자동 등급 폐지 후 — 2026-07-17).

SoT: docs/spec/PHASE1_COMBO_BUILDER_SPEC.md §6. HIGH/MEDIUM 생산 경로가 없다는 것
자체가 계약이다 — 구 combo floor 조합 evidence 를 넣어도 LOW 를 넘지 못해야 한다.
"""

from src.detection.topic_scoring import (
    TIER_RANK,
    case_tier,
    compute_topic_scores,
    compute_topic_tiers,
    pick_primary_topic,
)


def _ev(rule_id: str, score: float = 0.8) -> dict:
    return {"rule_id": rule_id, "normalized_score": score}


# ── standalone 게이트 (LOW/CONTEXT) ───────────────────────────


def test_single_primary_is_low():
    tiers = compute_topic_tiers([_ev("L2-02")])
    assert tiers["duplicate_outflow"].tier == "LOW"


def test_booster_only_is_context_not_low():
    # L3-03 관계사는 booster(standalone_rankable=False) — 단독으로 큐에 못 선다.
    tiers = compute_topic_tiers([_ev("L3-03")])
    assert all(breakdown.tier == "CONTEXT" for breakdown in tiers.values())


def test_macro_only_is_context():
    tiers = compute_topic_tiers([_ev("L3-12")])
    assert all(breakdown.tier == "CONTEXT" for breakdown in tiers.values())


def test_zero_score_evidence_does_not_open_gate():
    tiers = compute_topic_tiers([_ev("L2-02", score=0.0)])
    assert tiers["duplicate_outflow"].tier == "CONTEXT"


def test_case_tier_takes_max():
    tiers = compute_topic_tiers([_ev("L2-02"), _ev("L3-03")])
    assert case_tier(tiers) == "LOW"


def test_case_tier_all_context():
    tiers = compute_topic_tiers([_ev("L3-03")])
    assert case_tier(tiers) == "CONTEXT"


# ── 폐지 계약 — 구 HIGH/MEDIUM 조합이 더는 승격되지 않는다 ────


def test_tier_rank_has_no_high_or_medium():
    assert set(TIER_RANK) == {"LOW", "CONTEXT"}
    assert TIER_RANK["LOW"] > TIER_RANK["CONTEXT"]


def test_old_fictitious_entry_high_combo_stays_low():
    # 구 fictitious_entry_high: (L4-01|L4-03) & L3-02 & 2차정황 — 이제 승격 없음.
    tiers = compute_topic_tiers([_ev("L4-01"), _ev("L3-02"), _ev("L4-04")])
    assert all(breakdown.tier in {"LOW", "CONTEXT"} for breakdown in tiers.values())


def test_old_period_end_adjustment_high_combo_stays_low():
    tiers = compute_topic_tiers([_ev("L3-04"), _ev("L3-10")])
    assert all(breakdown.tier in {"LOW", "CONTEXT"} for breakdown in tiers.values())


def test_old_embezzlement_high_combo_stays_low():
    tiers = compute_topic_tiers([_ev("L2-05"), _ev("L3-02"), _ev("L4-03")])
    assert all(breakdown.tier in {"LOW", "CONTEXT"} for breakdown in tiers.values())


def test_old_approval_bypass_high_combo_stays_low():
    tiers = compute_topic_tiers([_ev("L1-05"), _ev("L4-03")])
    assert all(breakdown.tier in {"LOW", "CONTEXT"} for breakdown in tiers.values())


def test_old_suspense_concealment_combo_stays_low():
    tiers = compute_topic_tiers([_ev("L3-09"), _ev("L2-02"), _ev("L4-03")])
    assert all(breakdown.tier in {"LOW", "CONTEXT"} for breakdown in tiers.values())


def test_old_related_party_reversal_combo_stays_low():
    tiers = compute_topic_tiers([_ev("L2-05"), _ev("L3-03")])
    assert all(breakdown.tier in {"LOW", "CONTEXT"} for breakdown in tiers.values())


def test_old_expense_capitalization_high_combo_stays_low():
    tiers = compute_topic_tiers([_ev("L2-04"), _ev("L3-02"), _ev("L3-04")])
    assert all(breakdown.tier in {"LOW", "CONTEXT"} for breakdown in tiers.values())


# ── 점수 폐지 계약 ────────────────────────────────────────────


def test_topic_scores_are_always_zero():
    scores = compute_topic_scores([_ev("L4-01"), _ev("L3-02"), _ev("L4-04")])
    assert isinstance(scores, dict)
    assert all(value == 0.0 for value in scores.values())


def test_breakdown_carries_gate_only():
    breakdowns = compute_topic_scores([_ev("L2-02")], return_breakdown=True)
    assert breakdowns["duplicate_outflow"].has_rankable_primary is True
    assert breakdowns["duplicate_outflow"].score == 0.0


def test_pick_primary_topic_none_when_all_zero():
    # 점수 폐지 후 pick_primary_topic 입력은 호출부가 게이트 대표값으로 구성한다.
    assert pick_primary_topic({topic: 0.0 for topic in ("duplicate_outflow",)}) is None
    assert pick_primary_topic({"duplicate_outflow": 0.4}) == "duplicate_outflow"
