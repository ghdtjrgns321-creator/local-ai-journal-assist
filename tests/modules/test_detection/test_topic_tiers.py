"""PHASE1 tier scoring (PHASE1_TIER_SCORING_SPEC §2-§4) tests."""

from __future__ import annotations

from src.detection.topic_scoring import (
    TIER_RANK,
    case_tier,
    compute_topic_tiers,
    pick_primary_topic_by_tier,
)


def _ev(rule_id: str, score: float = 0.8) -> dict:
    return {"rule_id": rule_id, "normalized_score": score}


def test_single_primary_is_low():
    tiers = compute_topic_tiers([_ev("L4-01")])
    assert tiers["revenue_statistical"].tier == "LOW"
    assert tiers["revenue_statistical"].has_rankable_primary is True


def test_booster_only_is_context_not_low():
    # L3-03 booster (standalone_rankable=False) → 단독 seed 불가
    tiers = compute_topic_tiers([_ev("L3-03")])
    assert tiers["account_logic"].tier == "CONTEXT"
    assert tiers["account_logic"].has_rankable_primary is False


def test_macro_only_is_context():
    tiers = compute_topic_tiers([_ev("Benford")])
    assert tiers["ledger_integrity"].tier == "CONTEXT"


def test_duplicate_reference_match_single_primary_is_low():
    tiers = compute_topic_tiers([_ev("L2-02", 0.6)])
    assert tiers["duplicate_outflow"].tier == "LOW"
    assert "duplicate_reference_match" not in tiers["duplicate_outflow"].fired_triggers


def test_outflow_plus_approval_bypass_is_high():
    # 횡령은폐 HIGH: 자금유출(L2-02) + 승인우회(L1-05)
    tiers = compute_topic_tiers([_ev("L2-02", 0.9), _ev("L1-05", 0.8)])
    assert tiers["duplicate_outflow"].tier == "HIGH"
    assert "embezzlement_concealment_high" in tiers["duplicate_outflow"].fired_triggers


def test_fictitious_entry_high():
    # 가공전표 HIGH: (L4-01) + L3-02 + L4-04
    tiers = compute_topic_tiers([_ev("L4-01"), _ev("L3-02"), _ev("L4-04")])
    assert tiers["revenue_statistical"].tier == "HIGH"


# --- A안 셋째 다리 확장 (DECISION D075 / HIGH_COMBO_GROUNDING §5b) ---


def test_fictitious_not_high_via_closing_leg_excluded():
    # 과탐 가드: 기말(L3-04)은 정상 결산전표에 흔해(734/738) 가공전표 2차정황에서 제외됐다.
    # 고액+수기+기말 만으로는 가공전표 HIGH 가 되지 않는다 (기말 fraud 는 closing_timing 영역).
    tiers = compute_topic_tiers([_ev("L4-03", 0.9), _ev("L3-02", 0.8), _ev("L3-04", 0.8)])
    assert tiers["revenue_statistical"].tier != "HIGH"


def test_fictitious_high_via_self_approval_third_leg():
    # 가공전표 + 자기승인(L1-05) 2차정황 → HIGH
    tiers = compute_topic_tiers([_ev("L4-03", 0.9), _ev("L3-02", 0.8), _ev("L1-05", 0.8)])
    assert tiers["revenue_statistical"].tier == "HIGH"


def test_fictitious_high_via_related_party_third_leg():
    # 가공전표 + 관계사(L3-03, booster) 2차정황 → HIGH. primary seed 는 L4-01 이 제공.
    tiers = compute_topic_tiers([_ev("L4-01", 0.9), _ev("L3-02", 0.8), _ev("L3-03", 0.8)])
    assert tiers["revenue_statistical"].tier == "HIGH"


def test_fictitious_not_high_via_sensitive_account_leg_excluded():
    # §3.0 HIGH-1 2차정황 풀 {L4-04|L2-03|L3-03|L1-05|L3-11}에 민감계정(L3-10) 없음.
    # §8(5) HIGH-1 2차정황 L3-10(0/67) 헛다리 삭제 → L3-10 만으로는 HIGH 불가, 약화형 MEDIUM.
    tiers = compute_topic_tiers([_ev("L4-03", 0.9), _ev("L3-02", 0.8), _ev("L3-10", 0.8)])
    assert tiers["revenue_statistical"].tier == "MEDIUM"


def test_embezzlement_high_via_manual_and_high_amount():
    # §3.0 HIGH-2 둘째 분기: (L2-02|L2-03|L2-05) & L3-02 & L4-03 → HIGH.
    # §8(6) 자금유출+수기+고액 일반형. 역분개(L2-05)+수기(L3-02)+고액(L4-03)으로 검증.
    tiers = compute_topic_tiers([_ev("L2-05", 0.9), _ev("L3-02", 0.8), _ev("L4-03", 0.9)])
    assert tiers["duplicate_outflow"].tier == "HIGH"
    assert "embezzlement_concealment_high" in tiers["duplicate_outflow"].fired_triggers


def test_embezzlement_not_high_reversal_manual_without_bypass_or_high_amount():
    # §3.0 HIGH-2: bypass 없고 L4-03(고액) 없으면 역분개+수기만으로는 HIGH 불가.
    # §8(1) 고액 L4-03 복원 — 둘째 분기는 고액을 AND 로 요구한다.
    tiers = compute_topic_tiers([_ev("L2-05", 0.9), _ev("L3-02", 0.8)])
    assert tiers["duplicate_outflow"].tier != "HIGH"


def test_fictitious_not_high_without_secondary_red_flag():
    # 음성: 고액(L4-03) + 수기(L3-02) 뿐, 2차정황 0개 → HIGH 아님 (과탐 방지)
    tiers = compute_topic_tiers([_ev("L4-03", 0.9), _ev("L3-02", 0.8)])
    assert tiers["revenue_statistical"].tier != "HIGH"
    assert case_tier(tiers) != "HIGH"


def test_high_trigger_without_primary_does_not_escalate():
    # 승인우회 조합 신호가 있어도 해당 토픽 primary seed 가 없으면 승격 불가.
    # L3-12(combo_only, standalone_rankable=False) + L1-05 → approval_control 은
    # L1-05 가 primary seed 이므로 has_rankable_primary True. gate 검증을 위해
    # primary 가 전혀 없는 booster/macro 조합을 본다.
    tiers = compute_topic_tiers([_ev("L3-05"), _ev("L3-06")])
    for breakdown in tiers.values():
        assert breakdown.tier == "CONTEXT"


def test_case_tier_takes_max():
    # L2-02 + L1-05 → duplicate_outflow HIGH(outflow&bypass), approval_control 도
    # HIGH(§3.0 bypass & L2-02 corroborant) → case HIGH(최고 tier).
    tiers = compute_topic_tiers([_ev("L2-02", 0.9), _ev("L1-05", 0.8)])
    assert case_tier(tiers) == "HIGH"


def test_pick_primary_topic_by_tier():
    # §3.0 HIGH-2: 역분개(L2-05, outflow) + 자기승인(L1-05, bypass) → duplicate_outflow HIGH.
    # approval_control 은 corroborant(L4-03|L2-02|L2-03) 부재로 LOW → duplicate_outflow 가 primary.
    tiers = compute_topic_tiers([_ev("L2-05", 0.9), _ev("L1-05", 0.8)])
    assert tiers["duplicate_outflow"].tier == "HIGH"
    assert pick_primary_topic_by_tier(tiers) == "duplicate_outflow"


def test_no_signal_returns_no_primary():
    tiers = compute_topic_tiers([])
    assert pick_primary_topic_by_tier(tiers) is None
    assert case_tier(tiers) == "CONTEXT"


def test_tier_rank_ordering():
    assert TIER_RANK["HIGH"] > TIER_RANK["MEDIUM"] > TIER_RANK["LOW"] > TIER_RANK["CONTEXT"]
