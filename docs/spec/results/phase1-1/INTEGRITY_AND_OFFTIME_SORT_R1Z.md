# 데이터정합성 분리 + OFF-TIME within-tier 정렬 검증 결과

> HIGH_COMBO_GROUNDING.md §2(1) 데이터정합성 트랙·§2(5) OFF-TIME 보조축의 **통합점수체계 실제 구현**을 코드 사용지점으로 검증. r11(룰 발화)·r1z(조합 tier) truth가 직접 겨냥하지 않은 두 동작이라 코드 경로 직접 추적 + r1z 실측 보조.

- 검증일: 2026-06-22
- 코드: `src/detection/phase1_case_builder.py`, `score_aggregator.py`, `dashboard/tab_phase1.py`
- 결론: **Q1(데이터정합성 분리) 정상 / Q2(OFF-TIME within-tier 정렬) 미작동(gap)**

## Q1. 데이터정합성(L1-01·L1-02·L1-03) — 부정 tier와 분리되나? → 정상

doc §2(1): L1-01 차대불일치·L1-02 필수필드·L1-03 무효계정은 부정 tier 미산입, `data_integrity_findings`로만 노출.

| 검증           | 코드 사용지점                                                                                                                              | 결과                                    |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------- |
| 부정 큐 기여 0 | `phase1_case_builder.py:1297` `if canonical_rule_id in _DATA_INTEGRITY_TRACK_RULES: continue` (topic/tier/priority 할당 **이전** continue) | 부정 topic/tier/priority 기여 0         |
| 트랙 집합 정의 | `_DATA_INTEGRITY_TRACK_RULES = {"L1-01","L1-02","L1-03"}` (case_builder:142, score_aggregator:59)                                          | L1-08 미포함(=dual track, 부정 큐 잔류) |
| 별도 산출      | `_build_data_integrity_findings`(L867) → `data_integrity_findings`(L785), `track="data_integrity"`(L954)                                   | 데이터 품질 트랙으로만 노출             |

→ **L1-01/02/03은 부정 tier(HIGH/MEDIUM/LOW review queue)에 들어가지 않고 데이터정합성으로만 분류된다.** doc §2(1)과 정합. (L1-08은 의도대로 dual-track으로 부정 closing_timing에 잔류 — `_DATA_INTEGRITY_TRACK_RULES`에 없음.)

## Q2. OFF-TIME(L3-05·L3-06·L4-05) within-HIGH 정렬 — 작동하나? → ❌ 미작동 (존재≠사용)

doc §2(5): OFF-TIME은 ① tier 게이트 제외 ② within-tier 정렬(`time_severity_score` desc, `independent_primary` 다음·금액보다 위) ③ UI 표시 ④ severity 등급(주말+공휴일/L4-05=2, 주말·심야=1).

| 역할                   | 코드 상태                                                                                                                                                                                                                                                                                                                                                      | 판정                       |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| ① 게이트 제외          | `phase1_case_builder.py:4933-4934` OFF-TIME을 priority/behavior 가산에서 제외                                                                                                                                                                                                                                                                                  | ✅ 작동 (tier 승격 미참여) |
| ④ severity 등급 계산   | `_TIME_SEVERITY_WEIGHTS={L3-05:2,L4-05:2,L3-06:1}`(L81) + `compute_time_severity_score`(L87), OFF_TIME_SET assert 동기화                                                                                                                                                                                                                                       | ✅ 계산됨                  |
| ③ UI 표시              | `dashboard/tab_phase1.py:3424` "시점심각도" 컬럼                                                                                                                                                                                                                                                                                                               | ✅ 표시됨                  |
| ② **within-tier 정렬** | 실제 정렬 scalar `_tier_sort_score`(L4540) 시그니처=`(case_tier_value, case_hits, materiality_score)` — **time_severity 인자 없음**. 본문(L4556)=`tier_rank·independent_primary·rule_count·materiality`. 최종 case sort 튜플(L1883)=`(composite_sort_score, triage_rank_score, total_amount, rule_count)`. **time_severity_score가 두 sort key 어디에도 없음** | ❌ **미작동**              |

**핵심**: `compute_time_severity_score`는 계산되어 case/unit 메타데이터(`time_severity_score`)에 저장되고 대시보드 컬럼으로 보이지만, **실제 within-tier 정렬 키에는 들어가지 않는다**(존재≠사용). 따라서 같은 HIGH 안에서 OFF-TIME(주말·심야·작성자집중)이 높은 전표가 위로 정렬되지 **않는다**. 현재 within-HIGH 순서는 `독립 primary 수 → rule_count → 금액 → triage → 금액 → rule_count`로 결정되며 시간 정황은 무시된다.

### spec 내부 모순 (gap의 배경)
- `PHASE1_TIER_SCORING_SPEC.md §4` L95-98: `sort_key = (tier_rank, independent_primary, **time_severity desc**, rule_count, materiality)` — time_severity **포함**.
- 같은 문서 §4 L142 "확정": `(tier_rank, independent_primary_count, materiality_score, rule_count)` — time_severity **미포함**.
- 코드 `_tier_sort_score`: `(tier_rank, independent_primary, rule_count, materiality)` — time_severity **미포함**, 게다가 L142와도 materiality·rule_count 순서가 뒤바뀜.
- `HIGH_COMBO_GROUNDING.md §2(5).3`: time_severity within-tier 정렬을 명시(L82).

→ doc(HIGH_COMBO §2(5).3 + TIER_SCORING §4 L95-98)이 약속한 OFF-TIME within-tier 정렬이 **코드에 미구현**. 정합성 결함.

## 불일치 목록

| #   | 대상                        | 차원         | 내용                                                                             | 증거                                                                                                        | 심각도         |
| --- | --------------------------- | ------------ | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------- |
| 1   | OFF-TIME within-tier 정렬   | doc↔code     | `time_severity_score`가 sort key에 부재. 계산·UI표시만, 정렬 미반영(존재≠사용)   | `_tier_sort_score`(case_builder:4540,4556) + sort 튜플(1883) vs HIGH_COMBO §2(5).3 / TIER_SCORING §4 L95-98 | **실제 gap**   |
| 2   | PHASE1_TIER_SCORING_SPEC §4 | doc 내부모순 | L95-98(time_severity 포함) vs L142(미포함), materiality/rule_count 순서도 불일치 | 동 문서 §4                                                                                                  | 문서 정합 필요 |

> Q1(데이터정합성)은 결함 0. Q2(OFF-TIME 정렬)는 게이트 제외·계산·표시는 정상이나 **정렬 반영만 미구현** — 등급(HIGH/MEDIUM)에는 영향 없고 within-tier 순서(어느 HIGH를 먼저 보여줄지)에만 영향.

## 결론

- **Q1 데이터정합성 분리: 정상.** L1-01/02/03은 부정 tier 기여 0, `data_integrity_findings` 별도 트랙으로만 분류(코드 L1297 continue + 별도 빌더).
- **Q2 OFF-TIME within-tier 정렬: 현행 미반영 — 결정으로 확정(2026-06-22).** time_severity는 계산·뱃지 표시(대시보드 "시점심각도" 컬럼)되나 sort key에 미포함이라 같은 HIGH 안에서 시간 정황 순 정렬은 안 된다.
- **결정(사용자, 2026-06-22)**: time_severity **정렬 반영을 두지 않고 뱃지 표시로 유지**하며, **within-tier 정렬 반영은 PHASE1-2 구현 시 함께 구현**한다(L4-05가 PHASE1-2 family 작성자 집계 단위라 묶어 구현). 따라서 코드(`_tier_sort_score`)는 **무수정**이 맞다(이미 정렬 미반영). 문서를 코드에 맞춰 정정 완료:
  - `PHASE1_TIER_SCORING_SPEC.md §4`: sort_key에서 `time_severity_score` 제거 → `(tier_rank, independent_primary, rule_count, materiality)`로 코드와 일치, 내부모순(L95-98 vs L142) 해소, 뱃지/PHASE1-2 deferral 명시.
  - `HIGH_COMBO_GROUNDING.md §2(5).3`: role을 "뱃지 표시 전용 + 정렬은 PHASE1-2 예정"으로 정정.
  - `phase1_case_builder.py:77` 주석: "정렬 가중치" → "뱃지/UI 표시 전용(정렬 미참여, PHASE1-2 예정)"로 정정(로직 무변경).
