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


# =====================================================================================
# §3-1. HIGH_COMBO_GROUNDING.md §3.0 발화표(L116~137) 13행 정합 게이트.
#   기대 tier 의 원천은 코드 출력이 아니라 §3.0 발화표 문서다(stage4 지시서 §3-1 인용).
#   각 행마다 "조합 충족 → 기대 tier" 1케이스 + "한 다리 빠짐 → 강등/미발화" 1케이스.
#   픽스처는 룰 발화 플래그(rule_id)만 쓴다 — 연도·corp_code·절대 금액을 박지 않는다.
#   약어: bypass = (L1-04|L1-05|L1-06|L1-07|L1-07-02).
# =====================================================================================


# --- 행1: HIGH fictitious_entry_high  (L4-01|L4-03)&L3-02&{L4-04|L2-03|L3-03|L1-05|L3-11} ---
def test_row01_fictitious_entry_high_fires_high():
    # 조합 충족: L4-01(매출급변) + L3-02(수기) + L4-04(희소계정쌍, 2차정황) → HIGH.
    tiers = compute_topic_tiers([_ev("L4-01"), _ev("L3-02"), _ev("L4-04")])
    assert tiers["revenue_statistical"].tier == "HIGH"


def test_row01_fictitious_entry_high_demotes_without_manual_leg():
    # 한 다리 빠짐: L3-02(수기) 제거 → HIGH 미발화(가공전표 조합 깨짐).
    tiers = compute_topic_tiers([_ev("L4-01"), _ev("L4-04")])
    assert tiers["revenue_statistical"].tier != "HIGH"


# --- 행2: HIGH embezzlement_concealment_high  (outflow&bypass)|(outflow&L3-02&L4-03) ---
def test_row02_embezzlement_concealment_high_fires_high():
    # 조합 충족(첫째 분기): L2-02(중복지급, outflow) + L1-05(자기승인, bypass) → HIGH.
    tiers = compute_topic_tiers([_ev("L2-02", 0.9), _ev("L1-05", 0.8)])
    assert tiers["duplicate_outflow"].tier == "HIGH"
    assert "embezzlement_concealment_high" in tiers["duplicate_outflow"].fired_triggers


def test_row02_embezzlement_concealment_high_demotes_without_bypass():
    # 한 다리 빠짐: bypass·고액수기 둘 다 없이 outflow(L2-02) 단독 → HIGH 미발화(LOW).
    tiers = compute_topic_tiers([_ev("L2-02", 0.9)])
    assert tiers["duplicate_outflow"].tier != "HIGH"


# --- 행3: HIGH suspense_concealment_high  L3-09&(L2-02|L2-03|L2-05)&L4-03 ---
def test_row03_suspense_concealment_high_fires_high():
    # 조합 충족: L3-09(가수금장기체류) + L2-02(outflow) + L4-03(이상고액) → HIGH.
    #   host=duplicate_outflow (L2-02 가 primary seed 제공).
    tiers = compute_topic_tiers([_ev("L3-09", 0.8), _ev("L2-02", 0.9), _ev("L4-03", 0.9)])
    assert tiers["duplicate_outflow"].tier == "HIGH"
    assert "suspense_concealment_high" in tiers["duplicate_outflow"].fired_triggers


def test_row03_suspense_concealment_high_demotes_to_medium_without_high_amount():
    # 한 다리 빠짐: L4-03(고액) 제거 → 약화형 suspense_concealment_medium 으로 강등(MEDIUM).
    tiers = compute_topic_tiers([_ev("L3-09", 0.8), _ev("L2-02", 0.9)])
    assert tiers["duplicate_outflow"].tier == "MEDIUM"
    assert "suspense_concealment_medium" in tiers["duplicate_outflow"].fired_triggers


# --- 행4: HIGH period_end_adjustment_high  (L3-04|L3-11)&(L3-10|L4-04|L4-03) ---
def test_row04_period_end_adjustment_high_fires_high():
    # 조합 충족: L3-04(기말결산) + L4-04(corroborant) → HIGH. host=closing_timing.
    tiers = compute_topic_tiers([_ev("L3-04", 0.8), _ev("L4-04", 0.8)])
    assert tiers["closing_timing"].tier == "HIGH"
    assert "period_end_adjustment_high" in tiers["closing_timing"].fired_triggers


def test_row04_period_end_adjustment_high_demotes_without_corroborant():
    # 한 다리 빠짐: corroborant(L3-10|L4-04|L4-03) 없이 L3-04 단독 → HIGH 미발화(LOW).
    tiers = compute_topic_tiers([_ev("L3-04", 0.8)])
    assert tiers["closing_timing"].tier != "HIGH"


# --- 행5: HIGH approval_bypass_high  bypass&(L4-03|L2-02|L2-03) ---
def test_row05_approval_bypass_high_fires_high():
    # 조합 충족: L1-05(bypass) + L4-03(고액 corroborant) → HIGH. host=approval_control.
    tiers = compute_topic_tiers([_ev("L1-05", 0.8), _ev("L4-03", 0.9)])
    assert tiers["approval_control"].tier == "HIGH"
    assert "approval_bypass_high" in tiers["approval_control"].fired_triggers


def test_row05_approval_bypass_high_demotes_without_corroborant():
    # 한 다리 빠짐: corroborant(L4-03|L2-02|L2-03) 없이 bypass(L1-05) 단독 → HIGH 미발화(LOW).
    tiers = compute_topic_tiers([_ev("L1-05", 0.8)])
    assert tiers["approval_control"].tier != "HIGH"


# --- 행6: HIGH expense_capitalization_high  L2-04&L3-02&(L4-03|L3-04|L1-06) ---
def test_row06_expense_capitalization_high_fires_high():
    # 조합 충족: L2-04(비용자산화) + L3-02(수기) + L1-06(직무분리, 셋째다리) → HIGH.
    #   host=account_logic (L2-04 primary seed).
    tiers = compute_topic_tiers([_ev("L2-04", 0.8), _ev("L3-02", 0.8), _ev("L1-06", 0.8)])
    assert tiers["account_logic"].tier == "HIGH"
    assert "expense_capitalization_high" in tiers["account_logic"].fired_triggers


def test_row06_expense_capitalization_high_demotes_to_medium_without_third_leg():
    # 한 다리 빠짐: 셋째다리(L4-03|L3-04|L1-06) 없이 L2-04&L3-02 만 → 약화형 MEDIUM.
    tiers = compute_topic_tiers([_ev("L2-04", 0.8), _ev("L3-02", 0.8)])
    assert tiers["account_logic"].tier == "MEDIUM"
    assert "expense_capitalization_medium" in tiers["account_logic"].fired_triggers


# --- 행7: MEDIUM rare_account_bypass_medium  L4-04&bypass ---
def test_row07_rare_account_bypass_medium_fires_medium():
    # 조합 충족: L4-04(희소계정쌍) + L1-05(bypass) → MEDIUM. host=account_logic.
    tiers = compute_topic_tiers([_ev("L4-04", 0.8), _ev("L1-05", 0.8)])
    assert tiers["account_logic"].tier == "MEDIUM"
    assert "rare_account_bypass_medium" in tiers["account_logic"].fired_triggers


def test_row07_rare_account_bypass_medium_demotes_without_bypass():
    # 한 다리 빠짐: bypass 없이 L4-04 단독 → MEDIUM 미발화(account_logic LOW).
    tiers = compute_topic_tiers([_ev("L4-04", 0.8)])
    assert tiers["account_logic"].tier == "LOW"


# --- 행8: MEDIUM embezzlement_concealment_medium  L2-01&(L1-05|L1-06|L1-07|L1-07-02) ---
def test_row08_embezzlement_concealment_medium_fires_medium():
    # 조합 충족: L2-01(한도직하 분할) + L1-06(bypass, L1-04 제외 세트) → MEDIUM.
    #   host=duplicate_outflow (L2-01 primary seed).
    tiers = compute_topic_tiers([_ev("L2-01", 0.6), _ev("L1-06", 0.8)])
    assert tiers["duplicate_outflow"].tier == "MEDIUM"
    assert "embezzlement_concealment_medium" in tiers["duplicate_outflow"].fired_triggers


def test_row08_embezzlement_concealment_medium_demotes_without_bypass():
    # 한 다리 빠짐: bypass 없이 L2-01 단독 → MEDIUM 미발화(duplicate_outflow LOW).
    tiers = compute_topic_tiers([_ev("L2-01", 0.6)])
    assert tiers["duplicate_outflow"].tier == "LOW"


# --- 행9: MEDIUM related_party_reversal_medium  L3-03&L2-05 (host=duplicate_outflow) ---
def test_row09_related_party_reversal_medium_fires_medium():
    # 조합 충족: L2-05(역분개, primary seed) + L3-03(관계사 booster) → MEDIUM.
    #   설계자 확인(지시서): host=duplicate_outflow, L3-04 passenger 미사용.
    tiers = compute_topic_tiers([_ev("L2-05", 0.8), _ev("L3-03", 0.8)])
    assert tiers["duplicate_outflow"].tier == "MEDIUM"
    assert "related_party_reversal_medium" in tiers["duplicate_outflow"].fired_triggers


def test_row09_related_party_reversal_medium_demotes_without_reversal():
    # 한 다리 빠짐: L2-05(역분개 seed) 없이 L3-03(booster) 단독 → 미발화.
    #   L3-03 은 account_logic booster(standalone_rankable=False)라 primary seed 불가 → CONTEXT.
    tiers = compute_topic_tiers([_ev("L3-03", 0.8)])
    assert tiers["duplicate_outflow"].tier != "MEDIUM"
    assert tiers["account_logic"].tier == "CONTEXT"


# --- 행10: MEDIUM fictitious_entry_medium  (L4-01|L4-03)&L3-02  (2차정황 없음) ---
def test_row10_fictitious_entry_medium_fires_medium():
    # 조합 충족: L4-03(이상고액) + L3-02(수기), 2차정황 없음 → 약화형 MEDIUM.
    tiers = compute_topic_tiers([_ev("L4-03", 0.9), _ev("L3-02", 0.8)])
    assert tiers["revenue_statistical"].tier == "MEDIUM"
    assert "fictitious_entry_medium" in tiers["revenue_statistical"].fired_triggers


def test_row10_fictitious_entry_medium_demotes_without_manual_leg():
    # 한 다리 빠짐: L3-02(수기) 없이 L4-03 단독 → MEDIUM 미발화(revenue_statistical LOW).
    tiers = compute_topic_tiers([_ev("L4-03", 0.9)])
    assert tiers["revenue_statistical"].tier == "LOW"


# --- 행11: MEDIUM suspense_concealment_medium  L3-09&(L2-02|L2-03|L2-05)  (고액 없음) ---
def test_row11_suspense_concealment_medium_fires_medium():
    # 조합 충족: L3-09(가수금) + L2-05(outflow), 고액(L4-03) 없음 → 약화형 MEDIUM.
    #   host=duplicate_outflow (L2-05 primary seed).
    tiers = compute_topic_tiers([_ev("L3-09", 0.8), _ev("L2-05", 0.8)])
    assert tiers["duplicate_outflow"].tier == "MEDIUM"
    assert "suspense_concealment_medium" in tiers["duplicate_outflow"].fired_triggers


def test_row11_suspense_concealment_medium_demotes_without_outflow():
    # 한 다리 빠짐: outflow(L2-02|L2-03|L2-05) 없이 L3-09 단독 → 미발화.
    #   L3-09 는 account_logic primary 라 그 토픽은 LOW, duplicate_outflow 는 primary 없어 CONTEXT.
    tiers = compute_topic_tiers([_ev("L3-09", 0.8)])
    assert tiers["duplicate_outflow"].tier != "MEDIUM"
    assert tiers["account_logic"].tier == "LOW"


# --- 행12: MEDIUM expense_capitalization_medium  L2-04&L3-02  (셋째다리 없음) ---
def test_row12_expense_capitalization_medium_fires_medium():
    # 조합 충족: L2-04(비용자산화) + L3-02(수기), 셋째다리 없음 → 약화형 MEDIUM.
    tiers = compute_topic_tiers([_ev("L2-04", 0.8), _ev("L3-02", 0.8)])
    assert tiers["account_logic"].tier == "MEDIUM"
    assert "expense_capitalization_medium" in tiers["account_logic"].fired_triggers


def test_row12_expense_capitalization_medium_demotes_without_manual_leg():
    # 한 다리 빠짐: L3-02(수기) 없이 L2-04 단독 → MEDIUM 미발화(account_logic LOW).
    tiers = compute_topic_tiers([_ev("L2-04", 0.8)])
    assert tiers["account_logic"].tier == "LOW"


# --- 행13: LOW  standalone primary 1개 단독 (조합 매치 없음) ---
def test_row13_standalone_primary_is_low():
    # 조합 매치 없이 primary 1개 단독 → LOW(큐 포함, coverage 집계). 한 다리 더 없으면 그대로 LOW.
    tiers = compute_topic_tiers([_ev("L4-01")])
    assert tiers["revenue_statistical"].tier == "LOW"
    assert tiers["revenue_statistical"].has_rankable_primary is True


def test_row13_no_primary_is_context_not_low():
    # 강등측: primary seed 가 전혀 없는 booster 단독 → LOW 도 못 되고 CONTEXT(큐 제외).
    tiers = compute_topic_tiers([_ev("L3-03", 0.8)])
    assert tiers["account_logic"].tier == "CONTEXT"
    assert tiers["account_logic"].has_rankable_primary is False


# =====================================================================================
# §3-2. 폐기 combo 부재 단정.
#   approval_bypass_medium · period_end_adjustment_medium · batch_combo ·
#   work_scope_combo · related_party_reversal_high 는 어떤 입력으로도 tier combo 로
#   발화하지 않는다(DEFAULT_COMBO_FLOORS·_fraud_combo_floor_results 에 미등록).
# =====================================================================================

_RETIRED_COMBO_POLICY_IDS = (
    "approval_bypass_medium",
    "period_end_adjustment_medium",
    "batch_combo",
    "work_scope_combo",
    "related_party_reversal_high",
)


def _all_fired_triggers(tiers) -> set[str]:
    fired: set[str] = set()
    for breakdown in tiers.values():
        fired.update(breakdown.fired_triggers)
    return fired


def test_retired_approval_bypass_medium_never_fires():
    # 구 approval_bypass_medium 발화 경로(bypass 단독·약화형)였던 입력들 → 폐기 id 미발화.
    for evidences in (
        [_ev("L1-05", 0.8)],
        [_ev("L1-04", 0.8), _ev("L3-02", 0.8)],
        [_ev("L1-07", 0.8), _ev("L4-04", 0.8)],
    ):
        fired = _all_fired_triggers(compute_topic_tiers(evidences))
        assert "approval_bypass_medium" not in fired


def test_retired_period_end_adjustment_medium_never_fires():
    # 구 period_end_adjustment_medium(약화형 기말) 후보 입력 → 폐기 id 미발화.
    for evidences in (
        [_ev("L3-04", 0.8)],
        [_ev("L3-11", 0.8)],
        [_ev("L3-04", 0.8), _ev("L3-02", 0.8)],
    ):
        fired = _all_fired_triggers(compute_topic_tiers(evidences))
        assert "period_end_adjustment_medium" not in fired


def test_retired_batch_combo_never_fires_as_tier():
    # L4-06(batch_combo combo_only)은 standalone_rankable=False·DEFAULT_COMBO_FLOORS 미등록
    #   → 단독·동반 모두 tier combo 로 발화하지 않는다(별도 macro corroboration 경로일 뿐).
    for evidences in (
        [_ev("L4-06", 0.8)],
        [_ev("L4-06", 0.8), _ev("L4-01", 0.8)],
        [_ev("L4-06", 0.8), _ev("L4-03", 0.9), _ev("L3-02", 0.8)],
    ):
        fired = _all_fired_triggers(compute_topic_tiers(evidences))
        assert "batch_combo" not in fired


def test_retired_work_scope_combo_never_fires_as_tier():
    # L3-12(work_scope_combo combo_only)도 동일하게 tier combo 로 발화하지 않는다.
    for evidences in (
        [_ev("L3-12", 0.8)],
        [_ev("L3-12", 0.8), _ev("L1-05", 0.8)],
        [_ev("L3-12", 0.8), _ev("L2-02", 0.9)],
    ):
        fired = _all_fired_triggers(compute_topic_tiers(evidences))
        assert "work_scope_combo" not in fired


def test_retired_related_party_reversal_high_never_fires():
    # HIGH-7 → MEDIUM 이관(§8(4)) 후 related_party_reversal_high 는 폐기. 어떤 입력도 발화 금지.
    for evidences in (
        [_ev("L2-05", 0.8), _ev("L3-03", 0.8)],
        [_ev("L2-05", 0.8), _ev("L3-03", 0.8), _ev("L3-04", 0.8)],
        [_ev("L2-05", 0.8), _ev("L3-03", 0.8), _ev("L4-03", 0.9)],
    ):
        fired = _all_fired_triggers(compute_topic_tiers(evidences))
        assert "related_party_reversal_high" not in fired
