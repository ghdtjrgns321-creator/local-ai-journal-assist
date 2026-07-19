# PHASE1-1 combo/tier 발화 매트릭스 (HIGH_COMBO_GROUNDING 전수)

목적: high/medium/low combo·tier datasynth를 만들기 **전에**, `HIGH_COMBO_GROUNDING.md`의 모든 combo/scheme이 실제 코드(`topic_scoring.py`)의 tier 발화 조건과 어떻게 연결되는지 전수로 못박는 사전 설계. 개별 룰 발화 recall은 r11(`phase1-rule-firing-matrix.md`, N=26)에서 이미 닫힘 — 이 문서는 "켜진 룰 조합이 올바른 tier로 조립되는가"만 본다.

> 본 작업은 설계/분석 문서만. Rust/DataSynth 생성·수정·재생성 없음.

## 모집단 (population-first)

- **doc scheme N = 19**: HIGH 10(HIGH-1~10) + MEDIUM 7(§4a 4 + §4b 3) + LOW 1 + CONTEXT 1. 권위: `docs/spec/HIGH_COMBO_GROUNDING.md` §3/§4/§5/§6.
- **code combo M = 12** policy_id: 권위 `src/detection/topic_scoring.py::_fraud_combo_floor_results` + `DEFAULT_COMBO_FLOORS`(14~27줄).

약어: bypass = `{L1-04,L1-05,L1-06,L1-07,L1-07-02}` · outflow = `{L2-02,L2-05}∪L2-03*` · L2-03* = `{L2-03,L2-03a~d}`.

## 핵심 결론 (3층 정합 상태)

| 층                  | 출처                                          | 상태                                                     |
| ------------------- | --------------------------------------------- | -------------------------------------------------------- |
| 설계 의도           | HIGH_COMBO_GROUNDING.md §3.0/§6               | 권위                                                     |
| 실제 코드           | topic_scoring.py `_fraud_combo_floor_results` | **§3.0과 일치** (코드 주석이 §3.0·§8(5)(6)(7) 직접 인용) |
| 코드 서술(중간문서) | tier-scoring-and-firing.md "현재 trigger"     | **STALE** (§8 이전 코드 서술)                            |

**즉 grounding 설계 = 코드는 이미 일치하고**, 정작 낡은 건 (a) `tier-scoring-and-firing.md`의 trigger 표, (b) grounding 129·509줄의 "코드 후속 일괄 반영 예정" 메모(코드는 이미 반영됨)다. 부록 A.

## combo 평가 단위 (datasynth 조립 제약)

- combo는 **단일 document가 아니라 case 그룹 `(theme_id, case_key)` 단위**로 발화한다(`phase1_case_builder.py` 1497·1682·1690줄). seedable hit가 theme별 case_key로 묶이고, 그 그룹의 hit 집합(`case_hits`)의 rule_id set에 combo 조건이 매치되면 floor가 적용된다.
- **has_rankable_primary 게이트**: combo floor가 tier로 승격하려면 host topic에 **standalone primary 룰이 그 case에서 발화**해야 한다(topic_scoring 367줄). booster/macro만으론 CONTEXT로 죽는다.
- **datasynth 함의**: combo를 발화시키려면 member 룰들이 **같은 case_key 그룹에 떨어지도록** 엮고, host topic의 primary seed 룰을 반드시 포함해야 한다. flow-theme combo(중복·역분개·가수금)는 flow 링크 문서들이 같은 case로 묶이고 거기에 document-leg가 얹혀야 한다(아래 cross-unit 표).

---

## 매트릭스 1 — code combo 12개 전수 (권위: topic_scoring.py)

```text
policy_id                        floor tier   host_topic          코드 조건(rule_id set)                                  doc scheme
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
fictitious_entry_high            0.75  HIGH   revenue_statistical (L4-01|L4-03) & L3-02 & (L4-04|L3-03|L1-05|L3-11|L2-03*)   HIGH-1
fictitious_entry_medium          0.60  MEDIUM revenue_statistical (L4-01|L4-03) & L3-02  [secondary 없음]                    §4b-1
period_end_adjustment_high       0.75  HIGH   closing_timing      (L3-04|L3-11) & (L3-10|L4-03|(L4-04&{L4-01|L2-05|L2-02|L2-03}))  HIGH-4
embezzlement_concealment_high    0.75  HIGH   duplicate_outflow   outflow & (bypass | (L3-02 & L4-03))                     HIGH-2
embezzlement_concealment_medium  0.60  MEDIUM duplicate_outflow   L2-01 & (L1-05|L1-06|L1-07|L1-07-02)                     §4a-2 한도분할
suspense_concealment_high        0.75  HIGH   duplicate_outflow   L3-09 & outflow & L4-03                                  HIGH-3
suspense_concealment_medium      0.60  MEDIUM duplicate_outflow   L3-09 & outflow  [L4-03 없음]                            §4b-2
related_party_reversal_medium    0.60  MEDIUM duplicate_outflow   L2-05 & L3-03                                            §4a-4 (HIGH-7 이관)
expense_capitalization_high      0.75  HIGH   account_logic       L2-04 & L3-02 & (L4-03|L3-04|L1-06)                      HIGH-9
expense_capitalization_medium    0.60  MEDIUM account_logic       L2-04 & L3-02  [셋째다리 없음]                          §4b-3
rare_account_bypass_medium       0.60  MEDIUM account_logic       L4-04 & bypass                                           §4a-1
approval_bypass_high             0.75  HIGH   approval_control    bypass & (L4-03|L2-02|L2-03*)                            HIGH-5
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

floor 0.75 → HIGH 컷, 0.60 → MEDIUM 컷(`_floor_value_tier`, topic_scoring 309·331~332줄). LOW/CONTEXT는 combo가 아니라 tier cascade(standalone primary만=LOW / booster만=CONTEXT, 366~385줄).

### has_rankable_primary host seed (C2-7, 12/12)

각 combo의 host topic에 그 topic의 standalone primary seed가 trigger rule 안에 포함됨(=combo가 죽지 않음). 권위: `rule_scoring.py` final_topic+scoring_role.

```text
host_topic           standalone primary seed 룰              combo가 쓰는 seed
─────────────────────────────────────────────────────────────────────────────────────
revenue_statistical  L4-01, L4-03                            L4-01|L4-03 (trigger 자체)
closing_timing       L3-04, L3-07, L3-11, L1-08              L3-04|L3-11 (timing seed)
duplicate_outflow    L2-01, L2-02, L2-03, L2-05              outflow/L2-01/L2-05 (trigger 자체)
account_logic        L2-04, L3-09, L4-04                     L2-04/L4-04 (trigger 자체)
approval_control     L1-04,05,06,07,07-02, L3-02             bypass (trigger 자체)
```

related_party_reversal_medium만 host 주의: L3-03은 booster(standalone_rankable=False)라 seed 불가 → host를 duplicate_outflow로 두어 **L2-05가 primary seed** 역할(topic_scoring 567~573줄 주석). closing_timing에 두면 seed 없어 CONTEXT로 죽음.

---

## 매트릭스 2 — doc scheme 19개 전수 → code 매핑 + GL-only

```text
scheme              tier    code combo / 상태                doc_vs_code        gl_only          datasynth_buildable
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
HIGH-1 가공전표      HIGH    fictitious_entry_high            match              in_scope         buildable (cross-unit)
HIGH-2 횡령은폐      HIGH    embezzlement_concealment_high    match              in_scope         buildable (cross-unit)
HIGH-3 가수금        HIGH    suspense_concealment_high        match              in_scope         buildable (cross-unit)
HIGH-4 충당금결산    HIGH    period_end_adjustment_high       match              in_scope         buildable (document)
HIGH-5 승인우회      HIGH    approval_bypass_high             match              in_scope         buildable (cross-unit)
HIGH-6 가공거래처    HIGH    (없음)                            out_of_scope       out_of_scope     N/A (마스터 비보유)
HIGH-7 역분개+관계사 MEDIUM  related_party_reversal_medium    match(이관 반영)    in_scope         buildable (cross-unit)
HIGH-8 재고과대      HIGH    (없음)                            out_of_scope       out_of_scope     N/A (보조원장 비보유)
HIGH-9 비용자산화    HIGH    expense_capitalization_high      match              in_scope         buildable (document/cross)
HIGH-10 topside     HIGH    (없음)                            out_of_scope       out_of_scope     N/A (연결ledger 밖)
§4a-1 희소+승인우회  MEDIUM  rare_account_bypass_medium       match              in_scope         buildable (document)
§4a-2 한도분할       MEDIUM  embezzlement_concealment_medium  match              in_scope         buildable (flow/cross)
§4a-3 분할청구       MEDIUM  (없음·룰 부재)                    unimplemented      gap(거래레벨)     not_buildable (룰 없음)
§4a-4 관계사역분개   MEDIUM  related_party_reversal_medium    match              in_scope         buildable (cross-unit)
§4b-1 약화형 가공전표 MEDIUM  fictitious_entry_medium          match              in_scope         buildable (document)
§4b-2 약화형 가수금  MEDIUM  suspense_concealment_medium      match              in_scope         buildable (flow)
§4b-3 약화형 비용자산화 MEDIUM expense_capitalization_medium   match              in_scope         buildable (document)
LOW   단일신호       LOW     tier cascade(standalone primary) match(구조)        in_scope         buildable (single rule)
CONTEXT 보조축/macro CONTEXT tier cascade(booster only)       match(구조)        in_scope         buildable (negative=비승격)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

집계: **match 13 + out_of_scope_gl_only 3 + unimplemented 1 + 구조match 2 = 19.** doc 설계와 충돌(divergent)·코드낡음(code-stale)인 scheme **0건** — grounding 설계와 코드는 일치한다.

### GL-only 범위 외 3건 (억지 생성 금지)

- **HIGH-6 가공거래처**: 강신호(사업자번호·공유계좌·직원-거래처 연결)는 거래처 마스터에 있고 GL-only는 마스터 비보유. PHASE1-1 primary 룰 신설 안 함. 등급 HIGH 유지(도구경계≠감사경계). SoT: CONSTRAINTS.md §GL-only.
- **HIGH-8 재고 과대평가**: 자연단위가 전표 아닌 자재·재고잔액(수량×단가·NRV), 입력도 GL 아닌 재고 보조원장. material 조인키·NRV 필드 부재. 의도적 미구현. 등급 HIGH 유지.
- **HIGH-10 topside/연결조정**: 연결제거 전표는 별도 산출물(`eliminations`)에만 있고 PHASE1 입력(개별법인 `journal_entries.csv`)에 물리적 부재(확정 사실). 의도적 미구현. 등급 HIGH 유지.
- **§4a-3 분할청구(split-invoice)**: 한 거래를 여러 송장으로 쪼개는 거래레벨 행동. GL은 document 단위라 송장 분할을 분리할 룰 부재 → unimplemented gap(L2-01 한도직하와 구분되는 별도 탐지갭).

→ 이 4건은 combo/tier datasynth에서 **생성 시도 안 함**. 나머지 13 in-scope combo만 datasynth 대상.

---

## 매트릭스 3 — datasynth buildability (member 룰 r11 발화 + cross-unit weaving)

### member 룰 ∈ r11 26 발화룰 (C2-5, 분모 명시)

in-scope combo가 참조하는 고유 member 룰 = `{L1-04,L1-05,L1-06,L1-07,L1-07-02, L2-01,L2-02,L2-03,L2-04,L2-05, L3-02,L3-03,L3-04,L3-09,L3-10,L3-11, L4-01,L4-03,L4-04}` = **19개**. 전부 r11 발화검증 매트릭스(`phase1-rule-firing-matrix.md`)의 26 발화룰에 포함 → **19/19 발화 가능**. 미포함 멤버 0 → 모든 in-scope combo의 member-leg는 GL-only로 켤 수 있다.

### cross-unit weaving 주의 (C2-6) — member 자연단위 혼합

r11 매트릭스의 truth_unit 기준. combo는 member 룰이 **같은 case_key 그룹**에 떨어져야 발화하는데, member의 자연단위가 다르면 단일 case 조립에 설계가 필요하다.

```text
combo                          member 단위 구성                                   조립 난이도/주의
──────────────────────────────────────────────────────────────────────────────────────────────────────────
period_end_adjustment_high     L3-04(doc)·L3-11(doc)·L3-10(doc)·L4-04(doc)·L4-03(doc)  쉬움 — 전부 document, 한 전표에 다 얹힘
rare_account_bypass_medium     L4-04(doc) & bypass(doc/L1-06=user)                 보통 — L1-06 외 bypass면 한 전표
fictitious_entry_medium/§4b-1  L4-01(macro)·L3-02(doc)                             보통 — L4-01은 배경 모집단 필요(스파이크 전표)
expense_capitalization_*       L2-04(doc)·L3-02(doc)·(L4-03 doc|L3-04 doc|L1-06 user)  보통 — 셋째다리 L1-06이면 작성자 toxic span 필요
suspense_concealment_*         L3-09(open_item_flow)·outflow(dup/reversal_flow)·L4-03(doc) 어려움 — 두 flow가 같은 case_key로 묶여야
embezzlement_concealment_high  outflow(flow)·bypass(doc/user)                      어려움 — flow 문서에 bypass leg가 같이 얹혀야
embezzlement_concealment_medium L2-01(flow)·(L1-05|L1-06|L1-07|L1-07-02)           보통~어려움 — L1-06이면 user-flow 동반
related_party_reversal_medium  L2-05(reversal_flow)·L3-03(doc IC태그)              보통 — 역분개 거울쌍이 IC 계정 사용
approval_bypass_high           bypass(doc/user)·(L4-03 doc|L2-02 flow|L2-03 flow)   어려움 — bypass 문서가 중복 flow의 leg
fictitious_entry_high          L4-01(macro)·L3-02(doc)·secondary(L2-03 flow 등)    어려움 — macro 배경 + flow secondary 동시
```

**조립 설계 원칙(datasynth 사전작업 결론)**:
1. **document-only combo는 한 전표에 leg를 모두 얹어** 바로 같은 case로 묶인다(period_end·rare+bypass·expense·약화형). 우선 생성.
2. **flow-포함 combo는 flow 링크 문서(중복쌍·역분개 거울쌍·가수금 정산)에 document-leg를 함께 주입**해야 같은 case_key로 묶인다. 예: HIGH-3은 가수금 전표가 동시에 중복지급 flow의 한 leg이고 고액이어야 한다.
3. **macro-포함 combo(L4-01)는 정상 배경 모집단 + 스파이크 전표**를 만들고 그 스파이크 전표에 L3-02·secondary를 얹는다(r11 L4-01 단위 macro_account_group 이슈는 phase1-rule-firing-matrix L4-01 참조 — combo에선 스파이크 document에 leg를 얹어 해소).
4. **user-leg(L1-06)** 셋째다리는 그 전표 작성자가 회기 내 toxic process 쌍을 span하도록 별도 전표를 깔아야 한다(r11 L1-06 참조).
5. **has_rankable_primary**: 각 case에 host topic primary seed(매트릭스1)를 반드시 포함. 예: related_party는 L2-05(역분개)가 seed라 반드시 발화해야 L3-03 단독 CONTEXT 죽음을 면한다.
6. **boundary(비승격) 대조군**: combo 조건에서 leg 1개를 뺀 case는 약화형(MEDIUM) 또는 LOW로 떨어져야 한다. 예: HIGH-3에서 L4-03 빼면 suspense_concealment_medium, outflow 빼면 L3-09 단독 LOW.

---

## 부록 A — stale 문서 식별 (코드 실제값과 대조, C2-8)

코드(topic_scoring.py)가 grounding §3.0과 일치하므로, 아래는 **문서가 코드보다 낡은** 항목이다. (별건 description-update 대상, 본 작업은 분석만)

| stale 위치                           | 낡은 서술                                                                                      | 코드 실제(권위)                                                    |                                |                          |         |         |               |       |                                        |
| ------------------------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------ | ------------------------ | ------- | ------- | ------------- | ----- | -------------------------------------- |
| tier-scoring-and-firing.md 114줄     | `related_party_reversal_high` `L2-05+L3-03+L3-04` HIGH                                         | `related_party_reversal_medium` `L2-05&L3-03` MEDIUM (이관됨)      |                                |                          |         |         |               |       |                                        |
| tier-scoring-and-firing.md 117줄     | `approval_control_high` (L1-04 critical/non_approver)                                          | 코드·DEFAULT_COMBO_FLOORS에 **없음** (L1-04는 bypass leg로만 참여) |                                |                          |         |         |               |       |                                        |
| tier-scoring-and-firing.md 116줄     | `approval_bypass_high` = bypass+L3-11 / L3-04+L3-02 / L3-06+L3-02                              | `bypass & (L4-03                                                   | L2-02                          | L2-03*)` (§8(5)(6) 반영) |         |         |               |       |                                        |
| tier-scoring-and-firing.md 111줄     | `period_end_adjustment_high` = `(L3-04                                                         | L3-07                                                              | L3-11                          | L1-08)&(L3-10            | L4-04)` | `(L3-04 | L3-11)&(L3-10 | L4-04 | L4-03)` (L3-07·L1-08 삭제, L4-03 복원) |
| tier-scoring-and-firing.md 131줄     | `fictitious_entry_medium` = `L4-01+L3-04` 또는 `L4-03+L4-06+L3-02`                             | `(L4-01                                                            | L4-03)&L3-02` (secondary 없음) |                          |         |         |               |       |                                        |
| tier-scoring-and-firing.md 133~136줄 | MEDIUM에 `batch_combo`·`work_scope_combo`·`duplicate_reference_match`·`approval_bypass_medium` | 코드에 **없음** (§8(5) LOW로 강등)                                 |                                |                          |         |         |               |       |                                        |
| HIGH_COMBO_GROUNDING.md 129·509줄    | "코드(topic_scoring.py)는 본 변경 후속 일괄 반영 예정"                                         | **이미 반영됨** — 코드 주석이 §3.0·§8(5)(6)(7) 인용, 조건 일치     |                                |                          |         |         |               |       |                                        |

→ 권고: tier-scoring-and-firing.md "현재 trigger" 표를 코드 기준으로 갱신, grounding 129·509줄 메모 삭제. (본 작업 범위 밖 — 후속 description-update)

## 부록 B — ripple 교차검증 (combo 조건 코드 재현, C2-9, 3/3)

topic_scoring.py 코드 라인으로 직접 조건 재현:

1. **fictitious_entry_high** (489~499줄): `has_revenue_or_amount`(`rule_ids & {L4-01,L4-03}`, 483줄) AND `"L3-02" in rule_ids` AND `rule_ids & _FICTITIOUS_SECONDARY_RULES`(46~51줄 = `{L4-04,L3-03,L1-05,L3-11}∪L2-03*`). → `(L4-01|L4-03)&L3-02&{L4-04|L3-03|L1-05|L3-11|L2-03*}`. doc §3.0 HIGH-1 일치(L3-10은 §8(5) 헛다리로 제외 — 코드 44~45줄 주석 확인).
2. **period_end_adjustment_high**: `has_timing_seed`(`rule_ids & {L3-04,L3-11}`) AND `has_period_end_corroborant`(`rule_ids & {L3-10,L4-03}` OR (`L4-04` in rule_ids AND `rule_ids & _RARE_PAIR_ESCALATION_RULES`={L4-01,L2-05,L2-02,L2-03})). → `(L3-04|L3-11)&(L3-10|L4-03|(L4-04&강신호))`. doc §3.0 HIGH-4 일치(L4-04 강신호 게이트 §8.4).
3. **related_party_reversal_medium** (573~579줄): `{"L2-05","L3-03"}.issubset(rule_ids)` → floor 0.60(MEDIUM, DEFAULT_COMBO_FLOORS 24줄). host=duplicate_outflow(L2-05 seed). doc §4a-4 일치(HIGH-7 MEDIUM 이관 §8(4) — 코드 567~572줄 주석 확인). tier-scoring-firing.md의 `_high` 서술은 stale.

3개 combo 모두 doc 조건과 코드 조건이 라인 단위로 일치. divergent 0건.
