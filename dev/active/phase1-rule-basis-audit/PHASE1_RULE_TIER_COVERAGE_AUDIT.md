# PHASE1 룰 ↔ tier 커버리지 감사 — 탐지갭 + 잉여룰

작성일: 2026-06-17
목적: PHASE1 룰을 전수 조사해 (A) 룰로 못 잡는 HIGH/MEDIUM/LOW scheme, (B) tier 판정에 기여하지 않는 잉여 룰을 코드 근거로 식별.
근거 SoT: [HIGH_COMBO_GROUNDING.md](../../docs/spec/HIGH_COMBO_GROUNDING.md)(tier 등급), `topic_scoring.py`(combo/floor 경로), `rule_scoring.py`(룰 메타).

## tier 기여 경로 정의

한 룰이 HIGH/MEDIUM/LOW 판정에 기여하는 길은 셋뿐이다:
- **SEED-P** = primary + standalone_rankable → topic을 seed(LOW) + HIGH/MEDIUM의 `has_rankable_primary` 게이트 충족
- **FLOOR** = `floor_policy_ids` 보유 → topic floor로 MEDIUM/HIGH 승격
- **COMBO** = `_fraud_combo_floor_results`의 조합 조건에 rule_id가 등장 → MEDIUM/HIGH 승격

셋 중 어디에도 안 닿으면 그 룰은 **tier에 기여하지 않는다**(row anomaly_score엔 보탤 수 있어도 band는 못 바꿈).

---

## §1. 룰 전수 인벤토리 (33 + Benford + L2-03 내부코드)

```
룰     scoring_role  topic              tier 기여 경로                 비고
──────────────────────────────────────────────────────────────────────────────
L1-01  primary       ledger_integrity   [분리] 데이터정합성            tier 제외(의도)
L1-02  primary       ledger_integrity   [분리] 데이터정합성            tier 제외(의도)
L1-03  primary       account_logic†     [분리] 데이터정합성            †registry는 account_logic이나 case_builder가 분리(아래)
L1-04  strong primary approval_control  FLOOR(approval_control_high)+COMBO  HIGH 경로
L1-05  strong primary approval_control  SEED-P + COMBO(승인우회·가공2차)
L1-06  strong primary approval_control  SEED-P + COMBO(승인우회)
L1-07  strong primary approval_control  SEED-P + COMBO(승인우회)
L1-08  primary       closing_timing     SEED-P + COMBO(timing_seed)
L1-09  primary       approval_control   SEED-P + COMBO(approval_medium)  근거약함·과발화(아래)
L2-01  primary       duplicate_outflow  SEED-P + COMBO(한도분할 medium)
L2-02  strong primary duplicate_outflow SEED-P + FLOOR(dup_reference)+COMBO
L2-03  primary       duplicate_outflow  SEED-P + COMBO(유출·가공2차)
 └L2-03a~d  internal  duplicate_outflow COMBO(_DUPLICATE_ENTRY_RULES)   드릴다운 내부코드
L2-04  primary       account_logic      SEED-P 만 → LOW 전용            ★HIGH 갭(비용자산화)
L2-05  primary       duplicate_outflow  SEED-P + COMBO(유출·역분개은폐)
L3-01  primary       account_logic      SEED-P 만 → LOW 전용
L3-02  primary       approval_control   SEED-P + COMBO(핵심·다수)        가장 많이 쓰이는 combo 재료
L3-03  booster       account_logic      COMBO(가공2차)                  standalone 불가
L3-04  primary       closing_timing     SEED-P + COMBO(timing_seed)
L3-05  booster       closing_timing     COMBO(approval_medium 주말)
L3-06  booster       closing_timing     COMBO(approval_medium 야간)
L3-07  primary       closing_timing     SEED-P + COMBO(timing_seed)
L3-08  booster       ledger_integrity   COMBO(period_end weak_desc)
L3-09  primary       account_logic      SEED-P + COMBO(가수금은폐)
L3-10  booster       account_logic      COMBO(period_end·가공2차)       근거약함(§2)·과발화 아님
L3-11  primary       closing_timing     SEED-P + COMBO(timing_seed·가공2차)
L3-12  combo_only    approval_control   COMBO(work_scope_combo)         standalone 불가
L4-01  primary       revenue_statistical SEED-P + COMBO(매출·금액)
L4-02  macro_only    ledger_integrity   [중화] role_factor=0 → 기여 0   PHASE1-2 귀속
L4-03  primary       revenue_statistical SEED-P + COMBO(핵심·다수)
L4-04  primary       account_logic      SEED-P + COMBO(가공2차·weak_desc)
L4-05  booster       closing_timing     없음 → 기여 0                   ★잉여(아래)
L4-06  combo_only    revenue_statistical COMBO(batch_combo·가공medium)
Benford macro_only   ledger_integrity   [중화] 기여 0                   PHASE1-2 귀속
D01    macro_only    account_logic      [중화] 기여 0                   PHASE1-2 귀속
D02    macro_only    closing_timing     [중화] 기여 0                   PHASE1-2 귀속
```

---

## §2. (A) 룰로 못 잡는 tier — 탐지 갭

HIGH_COMBO_GROUNDING의 각 band를 룰 커버리지로 판정한다.

### HIGH — 10개 중 5개에 갭

```
조합                     룰 커버리지        갭 종류
──────────────────────────────────────────────────────────────
HIGH-1 가공전표           ✅ 완전           없음
HIGH-2 횡령은폐           ✅ 완전           없음
HIGH-3 가수금             ✅ 완전           없음
HIGH-4 충당금·손상(결산)   ✅ 완전           없음
HIGH-5 승인우회           ✅ 완전           없음(단 결정2 미해결)
HIGH-6 가공거래처         ❌ 룰 없음         거래처 마스터 탐지룰 부재 → 신규 룰
HIGH-7 역분개+관계사+기말  ◐ 룰O 조합X       L2-05·L3-03·L3-04 있으나 조합 floor 없음 → 조합 추가
HIGH-8 재고 과대평가      ❌ 룰 없음         재고 수량·단가·NRV 측정룰 부재 → 신규 룰
HIGH-9 비용자산화         ◐ 룰O 조합X       L2-04 있으나 LOW seed만, HIGH 조합 없음 → 조합 추가
HIGH-10 topside          ❌ 룰 없음+데이터    식별룰 부재 + 단일법인 GL 관측범위 → 데이터단위 확인 선행
```

- **신규 룰 필요(2)**: 가공거래처(거래처 마스터), 재고 과대평가(재고 평가). 둘 다 측정 대상 자체(vendor master, 수량×단가)가 현재 룰에 없다.
- **조합만 추가하면 됨(2)**: 역분개+관계사+기말, 비용자산화. 재료 룰(L2-05·L3-03·L3-04·L2-04)은 이미 있고 `_fraud_combo_floor_results`에 floor 분기만 없다.
- **선행 확인 필요(1)**: topside. 룰 이전에 "연결조정 전표가 PHASE1 데이터(단일법인 GL)에 들어오는가"부터.

### MEDIUM — 3개 중 1개 갭

```
MEDIUM-1 희소계정쌍+승인생략  ✅ L4-04·L1-07 존재(현재 HIGH-1 2차정황으로 흡수)
MEDIUM-2 한도직하 분할        ✅ L2-01 razor_band 존재
MEDIUM-3 분할청구(split-invoice) ❌ 전용 룰 없음 (L2-01은 '한도직하'지 '송장분할'이 아님)
```

### LOW — 1개 갭

```
휴면계정 활성화        ❌ 휴면→활성 전이 탐지룰 없음
단순추정누락(충당금/재고NRV)  ◐ L3-10·L3-04로 LOW는 잡힘(부분)
단일 primary 신호      ✅ 각 SEED-P가 커버
```

**탐지갭 종합**: 신규 룰 3종(가공거래처·재고평가·휴면계정/+split-invoice 4종), 조합만 추가 2종(역분개관계사·비용자산화), 선행확인 1종(topside).

---

## §3. (B) tier 판정에 불필요한 룰

### 진짜 잉여 — L4-05 (비정상시간 집중)

- scoring_role = **booster** (standalone_rankable=False) → 단독 seed 불가.
- `topic_scoring.py` 어떤 combo/floor 조건에도 **미등장**(grep 확인: 0건).
- 결론: **tier(HIGH/MEDIUM/LOW)에 0 기여.** row anomaly_score에만 0.65 배수로 보탤 뿐 band를 못 바꾼다.
- 게다가 HIGH_COMBO_GROUNDING §2에서 발화근거 가장 빈약(KLCA 체크리스트 해당 항목 없음)으로 이미 표시됨.
- **처분 권고**: tier 관점에서 삭제 후보. 행동기반 시점신호로 살리려면 PHASE1-2 behavioral lane으로 이관(PHASE1-1 tier에선 제거).

### 중화된 macro — L4-02 · Benford · D01 · D02

- 전부 `macro_only` → `SCORING_ROLE_FACTOR=0` → 점수·tier 기여 0.
- registry 주석상 **의도적 중화**(삭제하면 `normalize_rule_evidence`가 primary로 폴백해 오히려 점수가 붙음). PHASE1-2 family(계정/월 모집단) 귀속.
- **처분 권고**: PHASE1-1 tier 관점에선 이미 죽은 가중치. PHASE1-2 surface로 정식 이관 시 PHASE1-1 registry에서 제거. 그 전엔 폴백 방지 위해 유지.

### LOW 전용 (잉여 아님, 단 제한적) — L2-04 · L3-01

- 둘 다 primary지만 combo/floor 미참여 → **LOW만 만든다.**
- L2-04는 잉여가 아니라 **갭의 반대편**: 비용자산화(HIGH 자격)를 LOW로만 표시 중 → 조합 추가로 HIGH 승격 대상(§2 HIGH-9).
- L3-01(계정·프로세스 불일치)은 정상적 account_logic LOW 신호. 유지.

### 근거 약하나 tier 기여 중 — 점검 대상 L1-09

- approval_bypass_medium combo(`{L1-09,L4-03,L3-02}`)로 MEDIUM에 기여하나, §2에서 근거 약함 + A안 wide 측정에서 정상 결산전표에 과발화(334/738)로 확인됨.
- **처분 권고**: 삭제는 아니나 medium combo에서의 가중을 재검토. (가공전표 2차정황에선 이미 제외됨)

---

## §4. 종합 권고 (다음 코드 단계 입력)

```
[신규 룰 필요]        가공거래처(vendor master) · 재고평가(수량·단가·NRV) · 휴면계정활성화
                      (+ split-invoice 송장분할)
[조합 floor만 추가]    역분개+관계사+기말(L2-05+L3-03+L3-04) · 비용자산화(L2-04+L3-02+고액)
[선행 확인]           topside — 연결조정 전표의 PHASE1 데이터 포함 여부
[삭제/이관 후보]       L4-05(tier 0기여·근거약함) → 제거 또는 PHASE1-2
                      L4-02·Benford·D01·D02(중화 macro) → PHASE1-2 이관
[재검토]              L1-09(근거약함·과발화) medium combo 가중
```

### 보고용 정합 메모 (해소됨)
- **L1-03 라우팅(확인 완료)**: `rule_scoring.py`는 L1-03을 `account_logic` primary로 두지만, `phase1_case_builder.py`의 `_DATA_INTEGRITY_TRACK_RULES = {L1-01, L1-02, L1-03}`가 L1-03을 데이터정합성 트랙으로 분리한다 → **운영상 tier 제외가 맞고, registry의 account_logic은 죽은 값(moot).** 코드 정리 시 registry final_topic을 분리 트랙과 일치시키면 혼선 제거.
- **L3-08 이중성(참고)**: L3-08은 tier에선 booster+COMBO(period_end weak_desc)로 기여하나, 동시에 데이터정합성 패널(`data_integrity_policy` 문자열에 L3-08 포함)에도 표시된다. tier 경로 자체는 정상이므로 본 감사 결론에 영향 없음.
