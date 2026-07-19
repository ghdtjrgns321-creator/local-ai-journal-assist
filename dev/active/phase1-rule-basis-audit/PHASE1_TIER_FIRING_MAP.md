# PHASE1 tier 발화 맵 — 현재 ↔ 목표 (Step 1a)

작성일: 2026-06-17
역할: "어떤 룰 레드플래그 집합이 켜지면 HIGH/MEDIUM/LOW가 발화하는가"의 기준 스펙. 이후 모든 룰 추가/수정이 이 맵을 만족해야 한다.
코드 근거: `src/detection/topic_scoring.py`(발화 로직), `src/detection/rule_scoring.py`(룰 메타).

## 발화 아키텍처 (확정 모델)

```
① 각 룰: 조건 충족 → normalized_score > 0 (레드플래그 on)
② 켜진 rule_id 집합을 combo 정의(_fraud_combo_floor_results)와 대조 → policy_id 발화
③ compute_topic_tiers: policy_id의 분류값(≥0.75 HIGH / ≥0.45 MEDIUM)으로 tier 결정
   단, 게이트: 그 주제에 has_rankable_primary(=standalone primary 룰이 같이 켜짐)가 있어야 승격
       primary 단독(조합 매치 없음)              → LOW
       primary 없이 booster/macro/combo_only만   → CONTEXT (큐 제외)
```
게이트 근거: `compute_topic_tiers` topic_scoring.py:367 (`if breakdown.has_rankable_primary:`),
분류값→tier: `_floor_value_tier` topic_scoring.py:309-315.

룰 집합 약어 (topic_scoring.py:31-36):
```
_REVENUE_OR_AMOUNT = {L4-01, L4-03}
_TIMING_SEED       = {L3-04, L3-07, L3-11, L1-08}
_OUTFLOW           = {L2-02, L2-05} ∪ _DUPLICATE_ENTRY
_DUPLICATE_ENTRY   = {L2-03, L2-03a~d}
_APPROVAL_BYPASS   = {L1-04, L1-05, L1-06, L1-07}
_WEAK_DESC_OR_SENS = {L3-08, L3-10, L4-04}
_FICTITIOUS_2ND    = {L4-04, L3-03, L3-10, L1-05, L3-11} ∪ _DUPLICATE_ENTRY   (line 45-51)
```

---

## §1. 현재 발화 맵 (코드 그대로)

### HIGH 발화 (분류값 0.75)

```
tier  topic               policy_id                     켜지는 조건(레드플래그 집합)                              코드
────────────────────────────────────────────────────────────────────────────────────────────────────────────
HIGH  revenue_statistical fictitious_entry_high         (L4-01|L4-03) & L3-02 & (∩_FICTITIOUS_2ND ≠∅)             :491
HIGH  closing_timing      period_end_adjustment_high    (∩_TIMING_SEED) & L4-03 & (∩_WEAK_DESC_OR_SENS)           :512
HIGH  closing_timing      period_end_adjustment_high    L3-11 & (L4-01|L4-03)                                     :519
HIGH  duplicate_outflow   embezzlement_concealment_high (∩_OUTFLOW) & ( (∩_APPROVAL_BYPASS) | {L2-05,L3-02,L4-03} ) :531
HIGH  duplicate_outflow   suspense_concealment_high     L3-09 & (∩_OUTFLOW) & L4-03                               :551
HIGH  approval_control    approval_bypass_high          (∩_APPROVAL_BYPASS) & (L4-03|L3-11|{L3-04,L3-02}|{L3-06,L3-02}) :562
HIGH  approval_control    approval_control_high(floor)  L1-04 발화 + 라벨 critical|non_approver                    rule_scoring:191 / topic_scoring:14
```

### MEDIUM 발화 (분류값 0.45~0.60)

```
MEDIUM revenue_statistical fictitious_entry_medium       (L4-01 & L3-04) | (L4-03 & L4-06 & L3-02)                 :502
MEDIUM duplicate_outflow   embezzlement_concealment_medium L2-01 & {L1-04,L1-05}                                   :539
MEDIUM approval_control    approval_bypass_medium        {L1-09,L4-03,L3-02} | (∩BYPASS & L3-02) | (&L3-06)|(&L3-05) | (L3-12 & {L1-05,L1-07}) :575
MEDIUM revenue_statistical batch_combo (0.45)            L4-06 (combo_only)                                        rule_scoring:465
MEDIUM approval_control    work_scope_combo (0.45)       L3-12 (combo_only)                                        rule_scoring:399
MEDIUM duplicate_outflow   duplicate_reference_match(floor 0.45) L2-02 발화 + 라벨 reference_match                  rule_scoring:246 / topic_scoring:15
```

### LOW 발화

```
LOW  (해당 topic)  primary seed 1개가 단독 발화(조합 매치 없음). standalone_rankable primary:
     L1-04~07·L1-08·L1-09·L2-01·L2-02·L2-03·L2-04·L2-05·L3-01·L3-02·L3-04·L3-07·L3-09·L3-11·L4-01·L4-03·L4-04
```

### CONTEXT (큐 제외 — primary 없이 보조만)

```
CONTEXT  booster: L3-03·L3-05·L3-06·L3-08·L3-10·L4-05   (standalone_rankable=False)
         macro_only: L4-02·Benford·D01·D02              (role_factor=0, 점수·tier 0기여)
         combo_only: L3-12·L4-06                        (조합에서만 의미)
```

---

## §2. 목표 발화 맵 (탐지갭 반영 — 추가/이관)

HIGH_COMBO_GROUNDING의 HIGH 10·MEDIUM 3·LOW와 1:1로 맞춘다. ★=신규.

### 추가 ① 조합만 추가 (재료 룰 이미 존재) [✅ 구현 완료 2026-06-17 — §1 HIGH로 승격됨]

> 구현됨: `related_party_reversal_high`·`expense_capitalization_high` (topic_scoring.py). HIGH_COMBO_GROUNDING §3.0 발화표·§3 HIGH-7/9 참조. 고액 제거 4곳도 반영 완료.

```
HIGH ★ closing_timing
        related_party_reversal_high (0.75)
        조건: L2-05(역분개) & L3-03(관계사) & L3-04(기말)
        host topic: closing_timing (L3-04 primary seed 보유) — 사용자 결정
        고액(L4-03): 미포함 — ISA550 RPT·ISA240 §32(c)·기말 역분개가 근거이고 금액은 근거 아님
        → HIGH-7 구현.

HIGH ★ account_logic
        expense_capitalization_high (0.75)
        조건: L2-04(비용자산화) & L3-02(수기) & L3-04(기말)
        host topic: account_logic (L2-04 primary seed 보유)
        고액(L4-03): 미포함 — 외감법 기록방법·WorldCom 근거는 분류조작이지 금액 아님
        → HIGH-9 구현. L2-04가 현재 LOW seed만 → 이 조합으로 HIGH 승격.
```

### 추가 ①' 고액(L4-03) 게이트 제거 [결정 확정 2026-06-17]

근거: AS 2401 §61 부정전표 특성 목록에 "고액"이 없음(라운드넘버는 있으나 금액크기는 아님).
고액은 중요성(ISA320)·이상치(ISA520) 렌즈이지 부정 특성이 아니다 → combo 게이트에서 제거,
tier 내부 랭킹(materiality tiebreak)으로만 사용.

```
제거  :512 period_end_adjustment_high  → (∩_TIMING_SEED) & (∩_WEAK_DESC_OR_SENS)  [L4-03 삭제]
제거  :531 embezzlement reversal분기    → {L2-05, L3-02}  [L4-03 삭제]
제거  :563 approval_bypass_high OR옵션   → (L3-11 | {L3-04,L3-02} | {L3-06,L3-02})  [L4-03 옵션 삭제]
제거  :575 approval_bypass_medium       → {L1-09, L3-02}  [L4-03 삭제]
유지  :32/:503/:524 수익통계 anchor (L4-01|L4-03)  — 주제 자체 신호(ISA520 이상치)
유지  :551 suspense_concealment_high L3-09&outflow&L4-03 — FSS 실측 8/9 동반(상관근거)
```

> ⚠️ 제거 시 정상데이터 HIGH 비율 재측정 필수(KPI 가드 ≤2%). 과탐이 오르면 combo 패딩이 아니라
> 해당 룰의 발화조건(레드플래그 임계)을 step 3에서 손본다 — 고액으로 되막지 않는다.

### 추가 ② 신규 룰 필요 (데이터 컬럼 확인 선행 — step 1c 이후)

```
HIGH ★ 가공거래처   신규룰(거래처 마스터: 신규/유사명/계좌=직원) → 자체로 HIGH seed + 조합
                    → HIGH-6. 측정 대상이 현재 룰에 없음(거래처 식별).
HIGH ★ 재고 과대평가 신규룰(재고 수량×단가·NRV·감모) → HIGH seed + 조합
                    → HIGH-8. L3-10은 계정코드만 봄, 평가 미측정.
HIGH ★ topside      신규룰(연결조정 전표 식별) — 단 PHASE1 데이터(단일법인 GL)에
                    연결조정 전표 포함 여부 확인이 선행 → HIGH-10.
MEDIUM ★ split-invoice 신규룰(한 거래 다중 송장 분할) — L2-01(한도직하)와 구분 → MEDIUM-3.
LOW    ★ 휴면계정    신규룰(장기 무거래 계정의 갑작스런 고액 활성화) → LOW.
```

### 이관 — L4-05 (step 2)

```
L4-05 (비정상시간 집중)  현재 booster·tier 0기여 → PHASE1-2 behavioral lane 이관.
                         D01·D02·L4-02·Benford 와 동일 처리(macro/behavioral는 PHASE1-2 소관).
                         PHASE1-1 registry/whitelist에서 제거(이관 md 작성 후).
```

---

## §3. 검증 규칙 (이 맵이 코드와 어긋나면 안 됨)

- §1의 모든 행은 `topic_scoring.py`의 실제 분기와 1:1. 코드 변경 시 본 맵 동기 갱신.
- §2 추가분은 step 1b/1c에서 TDD(RED-GREEN)로 구현하며, 구현 후 §1로 승격 이동.
- KPI 가드(feedback_phase1_truth_recall_guard): 조합 추가는 도메인 정합으로 정당화하고
  정상데이터 HIGH 비율 가드(≤2%) 재측정 필수(가공전표 A안 narrowed 0.334% 선례).

---

## §4. 진행 체크리스트 (사용자 5-step 매핑)

- [x] step 1a: 발화 맵 정리 (본 문서)
- [ ] step 1b: 조합 2종 추가(related_party_reversal_high·expense_capitalization_high) + TDD + KPI가드
- [ ] step 1c: 신규 룰 3~4종(거래처·재고·휴면·split-invoice) — 데이터 컬럼 확인 선행
- [ ] step 2: L4-05 PHASE1-2 이관 + 신규 PHASE1-2 md
- [ ] step 3: 룰별 점수체계·레드플래그 임계 재설계(33룰, 도메인 결정 다수 — 청크 분할)
- [ ] step 4: DETECTION_RULES.md 총정리 + 이관룰 PHASE1-2 md
- [ ] step 5: L1-03 데이터정합성 코드 정리(registry final_topic 일치)
