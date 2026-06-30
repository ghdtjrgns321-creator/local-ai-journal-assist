# HIGH_COMBO_GROUNDING ↔ 코드 tier 반영 전수 대조 (2026-06-21)

목적: PHASE1-1 룰이 [HIGH_COMBO_GROUNDING.md](../../../docs/spec/HIGH_COMBO_GROUNDING.md) 명세대로 통합점수(tier)에 코드 반영되는지, 잡음(명세 없는 코드/죽은 config/tier 불일치)이 있는지 전수 대조.

대조 대상 코드: `topic_scoring.py` `_fraud_combo_floor_results`(조합 add) + `DEFAULT_COMBO_FLOORS` + `compute_topic_tiers`(has_rankable_primary 게이트) + `rule_scoring.py` `RULE_SCORING_REGISTRY` + `config/phase1_case.yaml`(topic_floors/combo_floors).

## 1. 명세 조합 ↔ 코드 N:N 대조 (구현 대상 13개)

| 명세                 | tier   | 명세 룰식                                                | 코드 policy_id (topic_scoring add) | 코드 룰식                                                     | 판정             |
| -------------------- | ------ | -------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------- | ---------------- |
| H1 가공전표          | HIGH   | (L4-01\|L4-03)&L3-02&{L4-04\|L2-03\|L3-03\|L1-05\|L3-11} | fictitious_entry_high              | 동일(_FICTITIOUS_SECONDARY=L4-04·L3-03·L1-05·L3-11·L2-03계열) | ✅ 일치          |
| H2 횡령은폐          | HIGH   | ((L2-02\|L2-03\|L2-05)&bypass)\|((…)&L3-02&L4-03)        | embezzlement_concealment_high      | 동일(outflow&(bypass\|(L3-02&L4-03)))                         | ✅ 일치          |
| H3 가수금            | HIGH   | L3-09&(L2-02\|L2-03\|L2-05)&L4-03                        | suspense_concealment_high          | 동일                                                          | ✅ 일치          |
| H4 결산조작          | HIGH   | (L3-04\|L3-11)&(L3-10\|L4-04\|L4-03)                     | period_end_adjustment_high         | 동일(timing_seed&period_end_corroborant)                      | ✅ 일치          |
| H5 승인우회          | HIGH   | bypass&(L4-03\|L2-02\|L2-03)                             | approval_bypass_high               | 동일                                                          | ✅ 일치          |
| H9 비용자산화        | HIGH   | L2-04&L3-02&(L4-03\|L3-04\|L1-06)                        | expense_capitalization_high        | 동일                                                          | ✅ 일치          |
| M1 희소+승인우회     | MEDIUM | L4-04&bypass                                             | rare_account_bypass_medium         | 동일                                                          | ✅ 일치          |
| M2 한도직하분할      | MEDIUM | L2-01&(L1-05\|L1-06\|L1-07\|L1-07-02)                    | embezzlement_concealment_medium    | 동일(L2-01&bypass(no L1-04))                                  | ✅ 일치          |
| M3 분할청구          | MEDIUM | split-invoice                                            | —                                  | (미구현)                                                      | ⚪ 명세도 미구현 |
| M4 관계사역분개      | MEDIUM | L3-03&L2-05                                              | related_party_reversal_medium      | 동일                                                          | ✅ 일치          |
| b1 약화형 가공전표   | MEDIUM | (L4-01\|L4-03)&L3-02 (2차0)                              | fictitious_entry_medium            | 동일                                                          | ✅ 일치          |
| b2 약화형 가수금     | MEDIUM | L3-09&(L2-02\|L2-03\|L2-05) (고액0)                      | suspense_concealment_medium        | 동일                                                          | ✅ 일치          |
| b3 약화형 비용자산화 | MEDIUM | L2-04&L3-02 (셋째0)                                      | expense_capitalization_medium      | 동일                                                          | ✅ 일치          |

**구현 12/12 일치** (M3 분할청구는 명세도 미구현 = 정합). HIGH-6/7/8/10은 명세상 범위 외/이관이라 코드 부재 정합.

## 2. tier 발화 재현 검증 (compute_topic_tiers, 2026-06-21)

| 조합                 | 입력 룰           | 기대 tier | 실측 tier |
| -------------------- | ----------------- | --------- | --------- |
| H1 fictitious_high   | L4-03·L3-02·L4-04 | HIGH      | HIGH ✅   |
| H2 embezzlement_high | L2-02·L1-05       | HIGH      | HIGH ✅   |
| H3 suspense_high     | L3-09·L2-02·L4-03 | HIGH      | HIGH ✅   |
| H4 period_end_high   | L3-04·L4-04       | HIGH      | HIGH ✅   |
| H5 approval_high     | L1-05·L4-03       | HIGH      | HIGH ✅   |
| H9 expense_high      | L2-04·L3-02·L4-03 | HIGH      | HIGH ✅   |
| M1 rare_bypass       | L4-04·L1-05       | MEDIUM    | MEDIUM ✅ |
| M2 threshold         | L2-01·L1-05       | MEDIUM    | MEDIUM ✅ |
| M4 related_party     | L2-05·L3-03       | MEDIUM    | MEDIUM ✅ |
| b1 fictitious_med    | L4-03·L3-02       | MEDIUM    | MEDIUM ✅ |
| b2 suspense_med      | L3-09·L2-02       | MEDIUM    | MEDIUM ✅ |
| b3 expense_med       | L2-04·L3-02       | MEDIUM    | MEDIUM ✅ |

→ **코드 _fraud_combo 자체는 명세대로 정확히 tier 발화. 코드측 잡음 0.**

## 3. 잡음 — config `phase1_case.yaml` 죽은 키 (tier 영향 0, 정리 권장)

코드가 참조하지 않는 죽은 config. `rule_scoring.RULE_SCORING_REGISTRY`에 floor_policy_ids/combo_policy_ids를 가진 룰이 0개라 `apply_topic_floors`·`apply_combo_floors`(policy_ids 경로)는 어떤 룰도 트리거하지 않으며, `_fraud_combo`는 아래 키를 add하지 않는다.

| 위치                | 죽은 키                      | 사유                                          | 코드 참조 |
| ------------------- | ---------------------------- | --------------------------------------------- | --------- |
| topic_floors        | approval_control_high        | registry에 floor_policy_id 보유 룰 0          | 없음      |
| topic_floors        | duplicate_reference_match    | 명세 §8.1(5) 근거없음→LOW 강등                | 없음      |
| topic_floors        | intercompany_exception       | IC PHASE1-2 이관(단계A corroboration 제거)    | 없음      |
| combo_floors        | period_end_adjustment_medium | 명세 §4b/§8 폐기                              | 없음      |
| combo_floors        | related_party_reversal_high  | 명세는 _medium(HIGH-7 이관). high는 틀린 tier | 없음      |
| combo_floors        | circular_transaction_medium  | IC/GR 순환 제거(2026-06-14)                   | 없음      |
| combo_floors        | circular_transaction_high    | IC/GR 순환 제거                               | 없음      |
| combo_floors        | approval_bypass_medium       | 명세 §4b 폐기(H5 약화형 폐지)                 | 없음      |
| topic_cap           | intercompany_cycle           | TOPIC_REGISTRY(6 topic)에 없음                | 없음      |
| anti_fitting_policy | weak_floor_handling 전체     | src 코드 참조 0(grep)                         | 없음      |

**죽은 config 무영향 재현 검증**:
- period_end_adjustment_medium(config 0.60): `L3-04` 단독 closing_timing → **LOW** (MEDIUM 아님 = config 무시 확인)
- approval_bypass_medium(config 0.60): `L1-05` 단독 approval_control → **LOW** (config 무시 확인)
- related_party_reversal_high(config 0.75): `L2-05·L3-03` duplicate_outflow → **MEDIUM** (config의 high 무시, 코드 _medium 0.60 적용 = 명세 정합)

## 결론

- **코드(topic_scoring tier 산출)는 HIGH_COMBO_GROUNDING 명세대로 정확히 반영**. 구현 12개 조합 명세 일치 + tier 발화 재현 일치. 코드측 잡음 0.
- **잡음은 전부 config `phase1_case.yaml`의 죽은 키**(폐기/이관된 조합의 floor/cap 값 잔존). 코드가 참조 안 해 **tier에 실제 영향 0**이나, 혼란 방지 위해 정리 권장(topic_floors 3 + combo_floors 5 + topic_cap 1 + weak_floor_handling 블록).

---

## 4. RULE_SCORING_REGISTRY 37항목 ↔ 명세 §2 묶음 (전수, 2026-06-21 보강)

registry 37항목(31 canonical + L2-03a~d alias + Benford alias) 전부 추출해 명세 §2 묶음의 tier 역할과 대조.

| 명세 §2 묶음 | 멤버(명세) | registry topic/role | 판정 |
| --- | --- | --- | --- |
| 데이터정합성(미산입) | L1-01·L1-02·L1-03 | ledger_integrity / primary | ✅ (registry primary지만 score_aggregator `_DATA_INTEGRITY_TRACK_RULES` 0강제 + case_builder topic 제외로 tier 미산입) |
| 승인우회 bypass(조합 leg) | L1-04·L1-05·L1-06·L1-07·L1-07-02 | approval_control / primary | ✅ |
| 자금유출 outflow(조합 leg) | L2-02·L2-03(+a~d)·L2-05 | duplicate_outflow / primary | ✅ |
| OFF-TIME(게이트 제외) | L3-05·L3-06·L4-05 | closing_timing / **booster**(standalone=False) | ✅ |
| booster·macro(CONTEXT) | L3-03 / D01·D02·L4-02·Benford | L3-03 booster / 나머지 macro_only(standalone=False) | ✅ |
| (조합 host 룰) | L1-08·L2-01·L2-04·L3-04·L3-07·L3-09·L3-11·L4-01·L4-03·L4-04 | 각 topic / primary | ✅ |
| PHASE1-2 이관 | L3-12·L4-06 | macro_only(role_factor 0) | ✅ |

- **registry 37항목 전부 floor_policy_ids=() · combo_policy_ids=()** — apply_topic_floors/apply_combo_floors의 policy_ids 경로를 트리거하는 룰 0개. ⇒ config topic_floors 3키 + combo_floors policy 키는 전부 죽은 config(§3 재확인).
- 경미: L3-02(수기)는 명세 §2 묶음에 미명시이나 registry topic=approval_control(수기=통제약화 신호 해석). 조합에서는 host topic에 floor되므로 무영향.

## 5. score_aggregator row-level floor ↔ 명세 tier (회색지대, 2026-06-21)

명세 SoT는 **case tier(전표 단위 band, §1)** = `topic_scoring.compute_topic_tiers`. score_aggregator의 row `anomaly_score`/`risk_level`은 별개 레거시 축(case 후보 진입 `risk!=Normal` 게이트용).

| 코드 floor (score_aggregator) | 대상 | row 결과 | case tier(명세 SoT) | 명세 §5.3 | 판정 |
| --- | --- | --- | --- | --- | --- |
| `_apply_policy_risk_floors` L1-04 ge0.8 | L1-04 단독 | risk_level **High** | approval_control **LOW** | LOW | ⚠️ row축 명세 초과(case tier는 정합) |
| `_apply_policy_risk_floors` L1-06 direct | L1-06 단독 | risk_level **High** | **LOW** | LOW | ⚠️ row축 명세 초과(case tier는 정합) |
| `_apply_policy_risk_floors` L1-05 label | L1-05 단독 | risk_level Low | LOW | LOW | ✅ |
| `_apply_auto_escalation` | 데이터정합성+2 | risk_level High | (tier 별도) | — | row축(case 후보 진입용) |

- **case tier(명세 band SoT)는 전부 명세 정합** — L1-04·L1-06 단독 case tier=LOW. 최종 review queue band는 case tier가 결정(§1)하므로 명세 위반 아님.
- **회색지대**: score_aggregator row `risk_level`은 명세 §5.3(승인우회 단독 LOW)을 초과해 L1-04·L1-06 단독을 row HIGH로 올린다. 명세 HIGH_COMBO_GROUNDING에 이 row-level policy floor의 근거가 없다. case tier에는 영향 0(topic_scoring만 band 결정)이나, row anomaly_score/risk_level을 직접 소비하는 화면/export가 있으면 명세 tier와 다른 등급이 표시될 수 있다. → row-level policy floor의 명세 근거 정리 또는 명세에 row축 정책 명문화 필요(별도 결정 사안).

## 종합 (전수 보강 후)
- 명세 ↔ 코드 case tier(통합점수 SoT): **완전 정합**. _fraud_combo 12조합 + registry 37룰 topic/role 전수 일치, 코드측 tier 잡음 0.
- 잡음: ① config phase1_case.yaml 죽은 키 10항목(tier 무영향) ② score_aggregator row-level policy floor(L1-04·L1-06 단독 row HIGH)는 명세 case tier와 별개 축·명세 근거 부재(회색지대).
