# HIGH-4 결산조작 과탐 규명·수정 — 최종 결과

작성 2026-07-03. 정상 데이터 case priority band에서 HIGH가 29.73%로 과탐되던 문제를 원인 규명부터
수정·재측정까지 정리한다. 실행은 개별 룰 재구현이 아니라 실제 프로덕션 `AuditPipeline(skip_db=True).run()`
+ detector 직접 호출. 현재 NORMAL 기준: `datasynth_semantic_v1_normal_20260703_v53_account_determination_r6`.

관련 산출물(상세):
- `reports/normal_v52_high4_l404_root_cause_20260703.md` — HIGH 5,571 전건 귀속 + L4-04 파편화 규명
- `reports/normal_v52_high4_fss_origin_trace_20260703.md` — FSS 474건 원천 역추적
- `reports/normal_v52_datasynth_fix_and_rule_looseness_20260703.md` — 데이터 수정 이유·도달점 + 룰 심층분석
- `reports/normal_v52_high4_b_option_remeasure_20260703.md` — 룰 B안 반영 후 v52 재측정
- `reports/normal_v53_high4_full_remeasure_20260703.md` — v53(데이터+룰+L2-05) 최종 재측정

---

## 1. 핵심 결론

| 항목                      | 상태      | 한 줄                                                                      |
| ------------------------- | --------- | -------------------------------------------------------------------------- |
| HIGH band 과탐            | ✅ 해결   | 29.73%(5,571/18,741) → **6.47%(1,010/15,611)**                             |
| L4-04 희소계정쌍 발화     | ✅ 정상화 | 6.94% → **0.148%** (데이터 계정배정 안정화)                                |
| HIGH-4 룰 과승격          | ✅ 수정   | L4-04 단독 HIGH 트리거 제외 → 강신호 동반 시에만 (B안)                     |
| HIGH-4 L4-04 단독leg 버그 | ✅ 0건    | HIGH 중 L4-04 단독 16건은 전부 account_logic(비용자산화), closing_timing 0 |
| FSS 부정 recall           | ✅ 무손실 | FSS-HIGH 147/158 유지(변경 전과 동일, 손실 0)                              |
| L2-05 역분개 OOM          | ✅ 수정   | 계정배정 안정화 부작용 카테시안 폭발 → 금액키 블로킹                       |
| 부정 데이터셋 실제 recall | ⏳ 미실행 | FSS 태깅표(권위 출처) 기준만 검증 — 병합 전 별도 실행 권장                 |

---

## 2. 문제 — 정상 데이터인데 HIGH 29.73%

v52 정상 데이터에서 case의 29.73%(5,571/18,741)가 HIGH band였다. review queue 최상위에 정상 전표가
30% 들어가면 "감사인이 먼저 볼 우선순위"라는 PHASE1 목적의 변별력이 무너진다(hollow queue).

HIGH 5,571 전건 귀속(표본 아님): **98.5%(5,487)가 HIGH-4(period_end_adjustment_high) 경유**,
그중 **83.8%(4,597)는 둘째 leg가 희소계정쌍(L4-04) 단독**이었다.

## 3. 원인 — 2트랙(데이터 아티팩트 + 룰 과승격)

### 3-1. 데이터: 계정 랜덤 배정으로 L4-04 뻥튀기

L4-04(희소 차대 계정쌍)는 "의미상 드문 계정 조합"을 잡으려는 룰인데, 생성기가 계정을 subtype만
맞추고 구체 번호를 균등 랜덤 배정(`je_generator.rs`)해 의미상 흔한 쌍이 구체번호 수준에서 희소로
오판됐다.

- 희소 구체쌍 59,790개 중 **99.9%(59,725)가 부모 subtype 쌍은 흔한(>3)** 쌍 — 파편화 기인.
- subtype 수준 재집계 시 L4-04 발화 6.94% → **0.04%**.
- 내적 모순: 계정이 고정돼야 할 recurring 전표의 9.6%·automated 5.6%가 희소쌍 발화(실제 ERP 불가).

### 3-2. 룰: L4-04를 HIGH 단독 트리거로 과승격 (FSS 원천 위배)

HIGH-4는 L4-04를 추정계정(L3-10)·고액(L4-03)과 동급의 HIGH 단독 leg로 취급했다. FSS 감리 474건
원천(`fss_case_combo_tagging.md`) 재대조:

- 결산시점 주제 140건 중 HIGH는 15.7%뿐(LOW/MEDIUM 77%).
- "기말 + 희소계정쌍" 순수형 9건은 **전부 MEDIUM/LOW**(`2012-나`·`FSS1912-14-1` 등). 특히 `2012-나`는
  룰조합이 `수기+기말+희소쌍`으로 정상 데이터에서 HIGH를 1,908건 만든 바로 그 조합인데 FSS는 MEDIUM.
- HIGH를 받은 사례는 예외 없이 매출조작(L4-01)·역분개(L2-05)·중복(L2-02/L2-03) 강신호를 동반.
- 룰 HIGH-4 매칭 92건 중 **46%(42건)가 FSS 실제 MEDIUM/LOW** — 원천 등급 과승격.

즉 L4-04의 도메인 근거 자체는 실증에 있으나(실제 부정은 가공자산에 이상계정 동원), FSS에선 강신호의
동반 신호였지 단독 HIGH 트리거가 아니었다.

## 4. 수정 3건

### 4-1. 룰 B안 (`src/detection/topic_scoring.py`)

HIGH-4 둘째 leg에서 L4-04를 단독 트리거에서 제외, 강신호 동반 시에만 인정:

```
변경 전: (L3-04|L3-11) & (L3-10 | L4-04 | L4-03)
변경 후: (L3-04|L3-11) & (L3-10 | L4-03 | (L4-04 & {L4-01|L2-05|L2-02|L2-03}))
```

`_PERIOD_END_CORROBORANT_RULES`에서 L4-04 제거 + `_RARE_PAIR_ESCALATION_RULES` 신설 +
`has_period_end_corroborant` 게이트 확장. 추정계정(L3-10)·고액(L4-03)은 단독 유지.

- FSS recall: 158 HIGH 재대입 147/158 유지(손실 0). L4-04 완전제거(A안)는 `FSS2505-06-가`
  1건 손실이라 B안(강신호 동반 인정) 채택.
- 문서: HIGH_COMBO_GROUNDING.md §HIGH-4·§3.0 표·§8.4, DETECTION_RULES.md, phase1-combo-tier-firing-matrix.md,
  verify_phase1_combo_tier_gate.py 동기화.

### 4-2. 데이터 계정배정 안정화 (DataSynth Rust, v53)

같은 의미 거래의 구체 계정쌍을 재사용하는 ERP account determination 방식으로 보정. NORMAL realism
gate에 C06_ACCOUNT_PAIR_REUSE 신설. 결과: L4-04-like rare doc rate 7.59%→0.129%, fragmentation
98.1%→0.0%. gate PASS 44 / MONITOR 1 / INFO 3 / FAIL 0.

### 4-3. L2-05 OOM (`src/detection/anomaly_rules_reversal.py`)

계정배정 안정화가 같은 계정 역분개를 집중시켜 거울쌍 매칭 카테시안이 259M행(16,094²)으로 폭발,
L2-05가 v53에서 미실행됐다. 거울쌍은 금액이 정확일치해야 하므로 **금액키(센트) 블로킹**으로 same-
account·same-amount 후보만 매칭하게 수정(tolerance>0은 정렬 밴드조인). v52 발화율 2.52% 불변(무손실),
v53 OOM 없이 실행.

## 5. v53 최종 재측정 (데이터+룰+L2-05 모두 반영)

| 지표                      | v52 원본                | v53 최종                   |
| ------------------------- | ----------------------- | -------------------------- |
| L4-04 발화율(문서)        | 6.94%                   | **0.148%** (165)           |
| L2-05 발화율(문서)        | 2.52%                   | 2.705% (3,016)             |
| L3-10 발화율(문서)        | 0.694%                  | 0.694% (774)               |
| case band HIGH            | 5,571 / 18,741 = 29.73% | **1,010 / 15,611 = 6.47%** |
| HIGH-4 충족               | 5,487                   | 816                        |
| HIGH-4 L4-04 단독leg 버그 | (해당없음)              | **0** (전건 확인)          |
| 실행 룰 수                | 30                      | 30                         |

- HIGH top 조합이 v52의 "L4-04 단독 leg"에서 v53는 **전부 L3-10(추정계정) 포함**으로 전환. HIGH-4가
  본래 시나리오(결산 추정조작=충당금·손상)에 정확히 부합한다. 역분개(L2-05)는 강신호로 정상 합류.
- HIGH-4 무결성: HIGH 중 L4-04는 있으나 추정·고액·강신호가 전부 없는 16건을 전건 `primary_topic`
  확인 → 16/16 account_logic(비용자산화), closing_timing 0. L4-04 단독 HIGH-4 승격 버그 없음.

## 6. 미해결·한계

1. **부정 데이터셋 실제 recall 미실행**: recall 무손실은 FSS 태깅표(권위 출처) 기준 재대입만.
   실제 fraud overlay 데이터셋 파이프라인 재실행은 미수행 — 병합 전 확인 권장. L2-05 OOM이 부정
   데이터셋에도 재현되면 recall에 영향 가능.
2. **L3-10(추정계정) 적정성**: v53 HIGH의 몸통은 이제 `수기+기말+추정계정`이다. L3-10은 도메인상
   정당한 강신호이나(계정배정 안정화에서 추정계정은 의도적 정규화 제외), 정상 결산에 과발화하는지는
   별도 점검 대상(이번 범위 밖).
3. **HIGH 6.47%는 오염 제거 후에도 5% 초과**: 다만 구성이 아티팩트가 아닌 정당한 신호이며, 추가
   하락은 L3-10 검토에서 나올 여지가 있다.

## 7. 분모·검증 방식

- HIGH 귀속: 5,571·92 전건 재대입(표본 아님). L4-04 분포: 전표 111,529·쌍 152,451 전수.
- FSS: 474건 전수 파싱(230파일, 누락 0). 결산시점 140·L4-04 등장 38·HIGH-4 매칭 92 전건 열람.
- pytest: test_topic_tiers/test_rule_scoring/test_phase1_case_builder 158 passed,
  test_anomaly_rules_reversal 27 passed(OOM 가드 2건 신규), verify_phase1_combo_tier_gate matrix-only PASS.
- L2-05 동치성: v52 c11 직접호출 2.52% = 수정 전 파이프라인 값 동일.
