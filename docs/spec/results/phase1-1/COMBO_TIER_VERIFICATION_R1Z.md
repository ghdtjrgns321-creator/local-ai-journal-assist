# PHASE1-1 통합점수체계(tier 조합) 정합 검증 결과 — r1z

> **범위**: PHASE1-1 **통합점수체계가 `HIGH_COMBO_GROUNDING.md`(조합→tier 근거 SoT)와 정합한지**를 검증한다. 개별 룰 발화(r11, 별도 문서 `RULE_FIRING_VERIFICATION_R11.md`)와 달리, 여기서는 켜진 룰 **조합**이 올바른 HIGH/MEDIUM tier를 만드는지 본다.

- 데이터셋: `data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z`
- spec(SoT): `docs/spec/HIGH_COMBO_GROUNDING.md` §3.0 발화조건표 / §6 종합분류표
- 코드: `src/detection/topic_scoring.py` (`_fraud_combo_floor_results`, `DEFAULT_COMBO_FLOORS`)
- 구조 게이트: `tools/scripts/verify_phase1_combo_tier_gate.py`
- 실측: `tools/scripts/measure_phase1_combo_tier.py` → `<dataset>/reports/phase1_combo_tier_case_measurement/`
- 검증일: 2026-06-22

## 1. 검증 설계 — 4개 축

| 축              | 무엇                                                                   | 도구           |
| --------------- | ---------------------------------------------------------------------- | -------------- |
| C1 구조 게이트  | spec(EXPECTED_POLICIES) ↔ code(DEFAULT_COMBO_FLOORS) ↔ truth 구조 일치 | verify gate    |
| C2 doc↔코드 leg | doc §3.0 발화조건(AND/OR leg) ↔ 코드 실제 조합식                       | 직접 코드 읽기 |
| C4 실측         | 각 조합 case가 expected tier floor 도달                                | measure script |
| C5 음의공간     | 범위외/폐기 조합이 코드 floor에 잔존 0건                               | grep           |

## 2. 모집단 권위 + 음의 공간

- **모집단(권위)**: `HIGH_COMBO_GROUNDING.md` §3.0/§6이 **구현 combo policy 12개**를 선언(HIGH 6 + MEDIUM 6). 코드 `DEFAULT_COMBO_FLOORS`도 정확히 12개(grep count=12). truth dataset = 13 buildable scheme(12 policy, `related_party_reversal_medium`이 HIGH-7·M-4A-4 두 scheme으로 등장) + LOW + CONTEXT = 15행.
- **범위외/폐기(음의 공간, 코드 floor 0건 확인)**:
  - 범위외(GL-only): HIGH-6 가공거래처·HIGH-8 재고과대·HIGH-10 topside — 마스터/재고원장/연결원장 비보유로 의도적 미구현(doc §3·§7, CONSTRAINTS.md). 코드 floor 없음.
  - 미구현: MEDIUM-3 split-invoice(거래레벨).
  - 폐기: `period_end_adjustment_medium`·`approval_bypass_medium`·`batch_combo`·`work_scope_combo`·`duplicate_reference_match`·`related_party_reversal_high` — 코드에 **주석으로만**("폐기 확정") 존재, 활성 floor 0건.
  - grep 결과: 폐기/범위외 policy가 `DEFAULT_COMBO_FLOORS`에 잔존 **0건**.

## 3. C2 — doc §3.0 ↔ 코드 leg 전수 대조 (12/12)

코드 rule set: `_REVENUE_OR_AMOUNT={L4-01,L4-03}` · `_TIMING_SEED={L3-04,L3-11}` · `_OUTFLOW={L2-02,L2-05}∪_DUPLICATE_ENTRY{L2-03*}` · `_APPROVAL_BYPASS={L1-04,L1-05,L1-06,L1-07,L1-07-02}` · `_PERIOD_END_CORROBORANT={L3-10,L4-04,L4-03}` · `_FICTITIOUS_SECONDARY={L4-04,L3-03,L1-05,L3-11}∪_DUPLICATE_ENTRY`.

| policy_id                       | tier   | doc §3.0 발화조건                                                     | 코드 조합식(topic_scoring.py L)                            | 일치               |
| ------------------------------- | ------ | --------------------------------------------------------------------- | ---------------------------------------------------------- | ------------------ |
| fictitious_entry_high           | HIGH   | (L4-01\|L4-03) & L3-02 & {L4-04\|L2-03\|L3-03\|L1-05\|L3-11}          | `revenue_or_amount & L3-02 & FICTITIOUS_SECONDARY` (L489)  | 일치               |
| fictitious_entry_medium         | MEDIUM | (L4-01\|L4-03) & L3-02 (2차정황 0)                                    | else `revenue_or_amount & L3-02` (L500)                    | 일치               |
| period_end_adjustment_high      | HIGH   | (L3-04\|L3-11) & (L3-10\|L4-04\|L4-03)                                | `timing_seed & period_end_corroborant` (L515)              | 일치               |
| embezzlement_concealment_high   | HIGH   | ((L2-02\|L2-03\|L2-05)&bypass) \| ((L2-02\|L2-03\|L2-05)&L3-02&L4-03) | `outflow & (approval_bypass \| (L3-02 & L4-03))` (L530)    | 일치               |
| embezzlement_concealment_medium | MEDIUM | (M2 한도직하분할) L2-01 & (L1-05\|L1-06\|L1-07\|L1-07-02)             | else `L2-01 & {L1-05,L1-06,L1-07,L1-07-02}` (L537)         | 일치 (명명주의 §5) |
| suspense_concealment_high       | HIGH   | L3-09 & (L2-02\|L2-03\|L2-05) & L4-03                                 | `L3-09 & outflow & L4-03` (L551)                           | 일치               |
| suspense_concealment_medium     | MEDIUM | L3-09 & (L2-02\|L2-03\|L2-05) (고액 없음)                             | else `L3-09 & outflow` (L558)                              | 일치               |
| related_party_reversal_medium   | MEDIUM | L3-03 & L2-05 (기말 필수 제외)                                        | `{L2-05,L3-03}.issubset` (L573)                            | 일치               |
| expense_capitalization_high     | HIGH   | L2-04 & L3-02 & (L4-03\|L3-04\|L1-06)                                 | `{L2-04,L3-02}.issubset & {L4-03,L3-04,L1-06}` (L583)      | 일치               |
| expense_capitalization_medium   | MEDIUM | L2-04 & L3-02 (셋째다리 없음)                                         | else `{L2-04,L3-02}.issubset` (L590)                       | 일치               |
| rare_account_bypass_medium      | MEDIUM | L4-04 & bypass                                                        | `L4-04 & approval_bypass` (L601)                           | 일치               |
| approval_bypass_high            | HIGH   | bypass & (L4-03\|L2-02\|L2-03)                                        | `approval_bypass & (L4-03\|L2-02\|DUPLICATE_ENTRY)` (L614) | 일치               |
| **합계**                        |        |                                                                       |                                                            | **12/12 일치**     |

floor 값(코드 `DEFAULT_COMBO_FLOORS`): `_high`=0.75, `_medium`=0.60. doc §1 "0.75=HIGH 칸 / 0.45=MEDIUM 칸 라벨"과 정합(MEDIUM 0.60 ∈ [0.45,0.75)). host topic도 doc과 일치(fictitious=revenue_statistical, embezzlement/suspense/related_party=duplicate_outflow, period_end=closing_timing, expense_cap/rare_account=account_logic, approval_bypass=approval_control).

## 4. C1·C4 — 구조 게이트 + 실측

- **C1 구조 게이트 PASS**: `verify_phase1_combo_tier_gate.py` status=PASS. 코드 `DEFAULT_COMBO_FLOORS`(12) == 게이트 EXPECTED_POLICIES, floor 값 유효, combo 멤버 룰 전부 R11(26) 내, truth 13 buildable + 2 control scheme/tier/topic/rule 매칭.
- **C4 실측 PASS (15/15)**: `measure_phase1_combo_tier.py` status=PASS, passed_rows=15/15.
  - 13 standard 조합: 전부 expected_case_tier(HIGH 6/MEDIUM 7) floor 도달 → `matched`.
  - LOW 경계통제(단일 L3-10): `priority_band=low`, combo floor 미발화 → `matched_low_control`.
  - CONTEXT 음성통제(단일 L3-03, booster·standalone_rankable=False): rankable case 미생성 → `matched_context_no_rankable_case`.
  - **한계(정직 표기)**: 이 측정은 case가 document GROUP BY 집계라 **한 case에 복수 조합이 섞인다**(예: HIGH-1·HIGH-5·M-4B-1이 동일 case `revenue_statistical_18250`). 측정은 "truth 문서가 든 case에서 expected_topic이 floor 도달"만 보고 **expected_policy_id가 그 조합으로 발화했는지는 직접 안 본다**. 따라서 per-combo 격리가 약하며, 조합 정합의 **주증거는 C2(코드 leg 직접 대조)**, C4는 회귀 보조 확인이다.

## 5. 불일치·주의 목록

**조합 로직 결함 0건.** 12개 policy의 코드 조합식이 doc §3.0 발화조건과 정확히 일치. 아래는 명명/도구 주의(정합성 무영향).

| #   | 대상                                                | 차원   | 내용                                                                                                                                                                                                                 | 영향                        |
| --- | --------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| 1   | embezzlement_concealment_medium                     | 명명   | 이 policy_id는 실제로 doc §4a-2 "한도직하 분할(M2)" scheme(`L2-01 & bypass-no-L1-04`)을 구현. "embezzlement medium"이라는 이름이 횡령 약화형으로 오해 소지. truth M-4A-2도 이 policy_id에 매핑. 로직은 doc M2와 일치 | 무영향(명명)                |
| 2   | embezzlement_concealment_high                       | 게이트 | 게이트 EXPECTED_POLICIES의 `rules_any`가 `{outflow},{bypass∪L3-02}`로 인코딩 — 실제 코드/doc은 L3-02 분기에서 L4-03도 요구. 게이트는 truth 검증용 느슨한 proxy이지 scoring 로직 아님                                 | 무영향(게이트는 구조검증용) |
| 3   | topside_or_outflow_pattern                          | code   | `rule_scoring.py:250` scenario tag 문자열. combo floor policy 아님(HIGH-10 topside는 범위외). `DEFAULT_COMBO_FLOORS` 미포함                                                                                          | 무영향                      |
| 4   | period_end_adjustment_medium·approval_bypass_medium | code   | 코드에 "폐기 확정" 주석으로만 존재, 활성 분기 없음                                                                                                                                                                   | 무영향(폐기 명시)           |

## 6. 결론

- **doc §3.0 ↔ 코드 leg 12/12 일치** (조합식·floor·host topic 전수 확인) — `HIGH_COMBO_GROUNDING.md`의 조합→tier 설계가 코드 `_fraud_combo_floor_results`에 그대로 반영됨.
- **구조 게이트 PASS** (spec↔code↔truth), **실측 PASS 15/15** (각 조합 tier 도달, LOW/CONTEXT 통제 정상).
- **음의 공간**: 범위외(HIGH-6/8/10)·미구현(split-invoice)·폐기 조합이 코드 floor에 **0건 잔존**. 구현 12 policy가 완전 모집단.
- 조합 로직 결함 0건. 주의 4건은 명명/게이트 proxy/폐기주석으로 정합성 무영향.
- **한계**: 실측(C4)은 case 집계 오염으로 per-combo 격리가 약해 보조 증거다. 조합 정합의 주증거는 C2 코드 leg 직접 대조다.
