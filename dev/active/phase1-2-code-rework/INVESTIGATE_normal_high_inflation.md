# 조사 메모 — 정상 데이터 high 밴드 양산 (PHASE1-1 tier 범위, PHASE1-2와 별개)

작성 2026-06-30. 별도 컨텍스트에서 조사할 것. 본 메모는 발견 사실만 기록(PHASE1-2 코드 작업과 분리).

## 무엇이 문제인가

정상 데이터셋(`datasynth_semantic_v1_normal_20260621_v46b`, C001 단일, 345,944행)에서
PHASE1 케이스 41,461개 중 **high 밴드가 31,683개(76%)**.

- 프로젝트 원칙·기존 HARD 가드: **정상 데이터 high = 0** (`tests/phase1_rulebase/kpi_baseline.json` → `layer_a_domain_integrity.a2_normal_high_medium_cases`: baseline_high 0 / max_high 0 / fail_mode HARD, v42j 기준).
- 31,683은 0에서의 구조적 이탈. 노이즈 아님.
- 측정 출처: `dev/active/phase1-2-code-rework/baseline_normal_v46b/summary.json` (`priority_band_cases`).
- 측정 도구: `tools/scripts/measure_phase1_current_p3_2.py` (full build, IC/graph/variance extra 트랙 포함).

## high를 끌어올린 룰 (priority_band_high_medium_rules, high 기여 상위)

```
L2-05   high 26,419      L3-12   high 26,042      L1-07   high 23,471
L3-04   high 21,576      L4-06   high 20,825      L3-02   high 15,600
L1-06   high 13,693      L3-05   high  7,603      L4-04   high  7,448
L3-06   high  6,851      L4-05   high  5,526      ...
```

## 왜 이상한가 (핵심 의심점)

- **L3-12(업무범위)·L4-06(배치)·L2-05는 설계상 macro/배지 = row 점수 0 기여** 여야 함.
  근거: PLAN/HANDOFF — macro 0기여 강제 지점 `src/detection/rule_scoring.py:38-43`,
  `src/detection/score_aggregator.py:251-254`. CLAUDE.md "band는 명명 tier가 직접 결정,
  macro_only는 0 기여."
- 그런데 이 0-기여 룰들이 high 밴드를 대량 생성 → **0 강제가 band/tier 결정 경로엔 안 먹히는 정황.**
- IC/graph extra 트랙 곁가지 아님 — 핵심 행단위 룰(L2-05/L3-12/L1-07/L3-04...)이 원인.

## 추정 원인

진행 중인 **PHASE1-1 tier 재설계(순서형 점수체계)** 미완 상태.
- 최근 커밋: `0b6ca70 refactor(detection): PHASE1 tier 순서형 점수체계·case builder·family 분리`,
  `bcd4cb7`, `96dc7be`, `9b7fa0d`, `31e23bc`.
- 작업트리에 `rule_scoring.py`·`score_aggregator.py`·`rule_labels.py`·`threshold_sidebar.py` 등 대량 수정 잔존(uncommitted).
- 명명 tier(HIGH/MEDIUM/LOW/CONTEXT)가 band를 직접 결정하도록 바뀌는 중 →
  macro/CONTEXT여야 할 룰이 HIGH tier로 매핑되는 미보정 구간일 가능성.

## 조사해야 할 것 (체크리스트)

1. **band 결정 경로 추적**: case의 `priority_band`가 어디서 정해지나.
   `phase1_case_builder.py` tier 산정 → `rule_scoring.py` / `score_aggregator.py` → band 매핑.
   macro_only 0-기여(rule_scoring.py:38-43)가 **tier/band 결정에도 적용되는지** vs row anomaly_score에만 적용되는지.
2. **L3-12·L4-06·L2-05의 tier 매핑 확인**: 이 룰들이 어떤 named tier로 분류되나.
   설계상 CONTEXT/배지여야 하는데 HIGH로 매핑됐는지 `config/phase1_case.yaml` + tier 정의에서 확인.
3. **kpi_baseline a2 가드 재측정**: v46b에서 정상 high가 정말 0이어야 하나, 아니면
   tier 재설계로 band 의미가 바뀌어 a2 기준 자체를 갱신해야 하나(기준 노후 v42j).
   `nightly_kpi_guard.py` 경로로 a2 HARD 가드가 현재 통과/실패 어느 상태인지.
4. **분모 확인**: 31,683 high가 case 단위. 같은 룰이 unit 단위(high 52,052)에서도 동일 패턴인지.
5. **음의 공간**: band를 결정하는 모든 경로(tier 산정 + floor + 직접 매핑)를 grep으로 전수 →
   0-기여 우회 경로가 어디서 생기는지.

## 조사 결론 (2026-06-30, 근본원인 확정)

**근본 원인: tier 재설계가 0.75 fraud-combo floor 를 HIGH tier 로 재분류했다.**

증거 체인:
1. **구동자**: HIGH 케이스 31,683 중 **27,665(87%)** 가 `embezzlement_concealment_high`
   콤보("outflow_or_duplicate + (approval_bypass or manual_with_high_amount)") 단독 구동.
   측정: 산출물 cases[].topic_score_breakdown 의 fraudcombo policy_ids 집계
   (scratchpad/analyze_high.py). 2위 period_end_adjustment_high 7,282.
2. **메커니즘**: `topic_scoring.py:97 _HIGH_FLOOR_MIN=0.75` + `_floor_value_tier` 가
   floor 값 ≥0.75 를 HIGH tier 로 분류. `DEFAULT_COMBO_FLOORS["embezzlement_concealment_high"]
   =0.75` → HIGH tier → `_TIER_TO_BAND["HIGH"]="high"`.
3. **회귀 증명**: tier 이전 원본(3584ada)은 band 를 `_priority_band(score, config)` 로 결정,
   config high컷 0.90. floor 0.75 → score 0.75 → `_priority_band` → **medium**(0.75≥medium 0.75,
   <high 0.90). 즉 동일 콤보가 옛 시스템에선 MEDIUM band 였다.
4. **baseline 정합**: kpi a2 (v42j) 정상 high=0 / medium=838. 현 v46b high=31,683 / medium=77.
   medium 이 말라 high 로 이동 — MEDIUM→HIGH 승격 패턴과 일치.
5. **broad seed**: L2-05(역분개)가 정상 케이스 31,196/41,461(**75%**)에 발화. 역분개+자기승인은
   중소 제조업 정상 회계(feedback_realistic_accounting). 이 정상 패턴이 콤보를 켠다.

**판정**: macro 0-기여(L3-12·L4-06)는 원인 아님(HIGH 케이스에 공발생할 뿐 tier 0 기여 정상).
진짜 원인은 0.75 콤보의 tier 매핑. 이건 코드 단순버그가 아니라 **콤보→tier 매핑 보정 누락**
(설계 결정 필요). 수정 옵션은 사용자 게이팅 대상.

## 기준 문서(HIGH_COMBO_GROUNDING.md) 대조 — 진짜 결함은 룰 발화율 (2026-06-30 보강)

기준 문서가 SoT 이며, 대조 결과 tier 코드는 문서와 **일치**한다:
- §1(line 33): "floor 0.75·0.45 = HIGH칸/MEDIUM칸 라벨" → `_HIGH_FLOOR_MIN=0.75` 의도대로.
- §3.0(line 110): `embezzlement_concealment_high = outflow & bypass` 는 **HIGH 로 정의됨**(설계 맞음).
- §8.6(line 556): 재설계 **후** 정상(v42j) HIGH 실측 **268/14,070=1.9%, 대부분 period_end**.
  → **설계조차 정상 HIGH 를 ~2% 로 예상.** 현 76% 는 설계 예상에서도 gross deviation.

**전표 단위 측정**(rule_hits.csv, 기준문서 §1 tier 단위=전표):
```
신호 전표 총     111,455
L1-07 승인생략   76,394 (69%)   ← 결함 핵심
L2-05 역분개     41,066 (37%)
L1-06 직무분리   22,560 (20%)
outflow&bypass 동일전표  34,307 (31%)  ← 콤보는 단일전표에서 진짜 겹침(묶음 아티팩트 아님)
```

**판정**: tier 임계도, 콤보 로직도, 묶음 단위도 버그 아님. **진짜 결함은 bypass 룰(특히
L1-07 승인생략)이 정상 전표의 69% 에 발화**하는 것. 기준문서 §2(2)는 L1-07 을 "비경상"으로
분류하나, 정상 데이터 69% 발화면 비경상이 아님 — 룰 발화조건 또는 v46b 정상 datasynth 가
정상 전표를 위반으로 만든다. 콤보 설계(outflow+bypass=HIGH)는 "두 신호가 정상에서 드물게
겹친다"는 전제인데(§2(2)(3)), L1-07 69% × L2-05 37% 면 교집합이 기계적으로 커진다.

→ 수정 타깃은 tier_scoring 이 아니라 **(a) bypass 룰 발화조건(특히 L1-07 승인생략의 정상
routine/자동 전표 제외) 또는 (b) v46b 정상 datasynth 의 무승인·역분개 과생성**. 의사결정 게이팅.

## 근본원인 확정 (2026-06-30, 진단 완료)

**L1-07(승인생략) 발화함수가 tier 리팩터에서 binary 로 퇴행 → 자동전표 제외 상실.**

1. **발화 코드**: `fraud_rules_access.py:1536 b09_skipped_approval` =
   `candidate = approved_by.eq("")`, score 1.0. **source 무시.** 빈칸이면 무조건 위반.
2. **config 의도와 충돌**: `audit_rules.yaml:145 skipped_approval_immediate.system_sources=
   [automated,batch,interface,system]` + 주석 "Automated/interface/batch/system context stays
   excluded". sibling `_skipped_approval_components` 는 `actionable = candidate & approval_required
   & ~system_source` 와 immediate/review/low_priority 등급을 **계산해두나 발화함수가 안 씀.**
3. **데이터 정합**: 정상 빈칸승인자 236,472(68.4%) 중 automated 195,037 + recurring 41,256 =
   **99% 자동·정기 전표.** 자동 배치 무승인은 현실 정상(feedback_realistic_accounting).
4. **회귀 commit**: tier 이전(6c49a9f) b09 는 components(system_source 제외·등급점수) 사용 →
   자동 무승인은 low_priority 저점수. tier 리팩터 **0b6ca70** 가 binary(빈칸→1.0)로 단순화하며
   제외 로직 삭제. 즉 **tier 코딩 커밋이 L1-07 을 함께 퇴행시킴.**
5. **연쇄**: 현실화 v46b(자동전표 82%) 가 잠복결함 노출 → L1-07 69% 과발화 → bypass leg 폭증
   → embezzlement_concealment_high 콤보(outflow&bypass) 31% → tier 재분류(0.75=HIGH, 의도대로)
   → HIGH band 76%. (tier 임계·콤보 정의·묶음단위는 기준문서와 일치 — 버그 아님.)

**수정 후보**(사용자 결정 대기):
- L1-07 발화함수를 `actionable`(approval_required & ~system_source) 기준으로 복원 — 최소 system_source
  제외. config·sibling 로직이 이미 있어 회귀 위험 낮음. (권장 1순위)
- 동류 점검: L1-06(직무분리 20%)·L2-05(역분개 37%)도 tier 리팩터에서 유사 단순화됐는지 ripple 확인.
- 복원 후 정상 high → ~2% 수렴 재측정 + kpi a2 HARD 가드 통과 확인.

## PHASE1-2와의 관계

- PHASE1-2 코드 rework(Phase 2 legacy 정리 등)는 **default-scope band 분포를 안 바꿈**
  (옛 family는 phase2_only scope에서만 실행, graph는 dead). 따라서 본 high 양산과 독립.
- 단 PHASE1-2 Phase 4(배지 통합)에서 L3-12·L4-06을 "배지 = 점수 0"로 재분류할 때,
  본 조사 결과(0-기여가 band에 왜 안 먹히나)와 **교차** 가능 — 그때 참조.
- baseline.md §3의 high 31,683은 frozen before-snapshot으로만 사용(건강한 baseline 아님).
