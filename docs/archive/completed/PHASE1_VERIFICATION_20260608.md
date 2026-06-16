# PHASE1 완성 검증 결과 (2026-06-08, 정상 데이터 v32 갱신 2026-06-11)

대상 데이터셋: overlay `datasynth_semantic_v1_p3_2_overlay_20260608_v23`, normal `..._normal_20260607_v29`.
범위: Tier 0·1·2·3·5 (Tier4 교차 데이터셋은 데이터 품질 사유로 제외).
방법: 보고 수치를 곧이곧대로 받지 않고 직접 재현(§9). 각 검사에 바닥 기대치(hollow-PASS 차단).

> **정상 데이터 갱신(2026-06-11).** 정상 베이스가 v29 → **v32**(PHASE2용, 신규 14계정 + delivery_date
> 백필)로 이동했다. 정상 과탐 측정은 [PHASE1_NORMAL_FP.md](PHASE1_NORMAL_FP.md)로 분리·갱신.
> v32 정상 측정 핵심: L3-01 정상 발화 **0 유지**(아래 2b 갱신), L1-03 무효계정 과탐은 글로벌 CoA 17계정
> 추가로 **0 해소**, delivery_date 백필로 L3-11 cutoff 룰이 비로소 작동(1.21%, 검토모집단). overlay/catch
> 검증(2a·2c·Tier0/3/5)은 v23 시점 그대로 유효.

## 요약 (검증 축 5개)

| 축 | Tier | 상태 | 한 줄 |
|----|------|------|------|
| 탐지(catch) | 2 | (진행) | v23 주입 위반 catch |
| 정밀(과탐) | 1,2 | (진행) | normal 과탐율 / 우선순위 분포 |
| 단위 정합 | 3 | (진행) | 전표/흐름 disjoint, 중복카운트 0 |
| 회귀 | 0,5 | (진행) | 테스트 green / lock invariant |
| 일반화 | 4 | 제외 | 사용자 결정 (데이터 품질) |

---

## Tier 1 — 기존 KPI 가드 (canonical 게이트)

명령: `pytest tests/phase1_rulebase/nightly_kpi_guard.py`
결과: **16 passed, 1 skipped, 1 FAILED**

- Layer A (도메인 정합 HARD): PASS — normal FP, rule truth 과탐/미탐 검사 통과
- Layer B (운영 부하 HARD): PASS — case 수, priority_band 분포, floor 비율 통과
- Layer C (truth 회귀 SOFT): PASS — 포착률/high/Top500 truth 모두 baseline 대비 통과
- **Meta freshness: HARD FAIL** — 아티팩트가 2026-05-14 생성(25일 경과 > 7일 윈도). 가드 자신이 "profile_phase1_v126.py 재실행 필요" 요구.

### 해석 (중요 사각)
- KPI 가드는 raw 데이터가 아니라 **사전 산출 아티팩트(2026-05-14 스냅샷)** 를 검증한다.
- Layer A/B/C "통과"는 **5/14 스냅샷 기준** — 우리 6/8 코드 변경(L3-01, IC01, overlay v23, 단위통일)을 **반영하지 않음**.
- 아티팩트 재생성에 필요한 `manipulation_v2`/`contract_v2` raw 데이터셋이 **로컬에 부재** → 가드를 현재 코드로 재검증 불가.
- 결론: **canonical KPI 가드는 현재 코드에 대해 미작동 상태.** 현재 코드 검증은 Tier 0/2/3/5가 담당.
- 후속(권장): manipulation_v2/contract_v2 재확보 또는 신규 데이터(v23/v29)로 baseline 재정의 + 도메인 사유 명시.

---

## Tier 2 — 최근 변경(overlay v23 · L3-01 · IC01) 정합 (현재 코드 실측)

### 2a. overlay v23 누수/catch (독립 재현)
- `scan_overlay_shortcuts.py v23`: **FINDINGS 0** (동일 코드가 v17엔 16건 검출). PHASE2 학습 누수 닫힘.
- `measure_phase1_detector_catch.py v23 --expect-truth-units 156`: **detector-expected std 62/62 (miss 0)**,
  population 0/16, evasion 0/78. 전건 positive_rows>0 (hollow 아님).
- IC01/IC02/IC03 std 전부 caught(positive_rows=2): v23 overlay가 IC 주입을 detector 확정 경로로 재구성.

### 2b. L3-01 (죽은 category 경로 활성화)
- 정상 v29 **전수 983,028행 L3-01 발화 0건** (실 detector, 과탐 0 — KPI Layer A 정신 충족).
- **v32 갱신: 전수 992,764행 L3-01 발화 0건 유지** (신규 14계정 도입에도 category 과탐 0).
- 5개 process×disallowed-category(O2C-expense 등) 정상 위반 사전측정 0건.
- v23 주입 O2C+expense standard 2/2 catch. integrity 테스트 34 passed(신규 잠금 2).

### 2c. IC01 timing-조건부 (review_stale)
- v23 IC01 std는 high 경로(미지 상대)로 catch → review_stale 변경과 직접 무관.
- review_stale(아는 그룹사 미대사, 결산 이탈→Medium)는 단위 테스트로 검증:
  결산근접→review(Low)/결산이탈→review_stale(Medium), 둘 다 details score 0(D065). 1420 passed.
- 구조적 과탐 가드: 새 flag 추가 없음 — 기존 review 신호의 Low→Medium 재배정만. 과탐 볼륨 불변.

판정: 최근 3개 변경 모두 catch 유지 + 과탐/회귀 0.

---

## Tier 0 — 전체 테스트 회귀 (현재 코드)

명령: `pytest tests/ --continue-on-collection-errors`
결과: **4459 passed, 37 failed, 133 skipped, 1 collection error** (259s)

### 회귀 baseline 판정: 신규 실패 0 (§9 가드 충족)
37 실패 + 1 에러를 전건 분류 → **전부 pre-existing(내 L3-01/IC01 변경 무관)**:

| 분류 | 건수 | 근거 |
|------|------|------|
| 데이터셋 부재 | ~32 | `datasynth_manipulation_v7_*/fixed5_*` truth csv 부재. test_services PHASE2 진단/leak-guard 류 (FileNotFoundError) |
| stale 설정 테스트 | 2 | test_rule_count(`70==67`), test_phase1_case priority_band(`0.9==0.75`) — SoT가 이동, 테스트가 옛 값 단언 |
| stale dashboard 테스트 | 2 | `render_candidate_card` 속성 제거(진행 중 dashboard 리팩터), narrator 메시지 변경 |
| collection 에러 | 1 | test_header_llm: 제거된 `_serialize_context` import (LLM 제거 잔재) |

- 내 변경 영역 테스트는 전부 green: detection 1420 / integrity 34(신규 잠금 2) / intercompany+score_aggregator 156.
- known-fail baseline = 37(+1 error). 신규 0. 모두 데이터 부재 또는 SoT-lag stale.

## Tier 5 — Lock invariant 정합

- 단위/스코어링 lock 테스트(rule_detail_metadata, rule_scoring, phase1_document_units, phase1_flow_units)
  는 detection 1420 passed에 포함되어 **통과**.
- 단 lock 관련 stale 2건: rule count SoT 70(코드)인데 test 67 단언, priority_band high SoT 0.90인데 test 0.75 단언.
  → lock 위반이 아니라 **테스트가 SoT 갱신을 못 따라간 것**. 권장: 두 테스트 SoT 재조정(별도, 도메인 확인 후).

---

## Tier 3 — 단위 disjoint denominator 정합

목표: UNIT_MEASUREMENT_POLICY — 각 문서는 최대 하나의 자연 단위(document XOR flow). flow 구성 문서는
흐름 단위로 흡수(R1)되어 중복 카운트 금지.

### 결과: 불변식 PASS (단위 테스트), 전수 빌드는 perf 블록 [~]
- **disjoint/R1 흡수 불변식 = 단위 테스트로 확인(현재 코드)**: `test_phase1_flow_units.py`+`test_phase1_document_units.py` **20 passed**.
  - `test_eligible_flow_absorbs_member_document_rule_hits`: flow가 구성 문서 hit 흡수.
  - `test_document_hits_absorb_into_one_primary_flow_when_document_has_multiple_flows`: 문서가 여러 flow에
    걸쳐도 **단일 primary flow로만 흡수**(absorbing_flows==1), 흡수 hit 총량 보존(중복 0).
- **전수 빌드(v23 984k행) 미완 [~]**: `measure_phase1_current_p3_2.py`(build_phase1_case_result) 20분+ 무출력(0바이트)
  → 16GB RAM에 ~9.8GB 미튜닝 unit/flow 빌드 스왑 스톨(핸드오프가 경고한 O(n²)/메모리 perf 갭). 중단함.
  - 검증 도구 `tools/scripts/check_unit_disjoint.py` 준비완료 — unit 빌드 perf 개선 후 v23 artifact에 실행하면 전수 disjoint 실측 가능.
- 판정: 불변식은 코드+테스트로 보장. 전수 실측은 perf 블록(별도 perf 과제). hollow-PASS 아님(불변식 직접 테스트됨).

---

## 종합 판정

| Tier | 항목 | 결과 |
|------|------|------|
| 0 | 전체 회귀 | 4459 passed, 신규 실패 0 (37+1 전건 pre-existing) |
| 1 | KPI 가드 | Layer A/B/C pass(옛 스냅샷), meta freshness FAIL(아티팩트 노후+raw 부재) |
| 2 | 최근 변경 | L3-01 정상 FP 0 / v23 catch 62/62 / scan 0 / IC01 단위검증 |
| 3 | 단위 disjoint | 불변식 PASS(단위테스트 20), 전수 빌드 perf 블록[~] |
| 5 | lock 정합 | PASS (stale 단언 2건은 SoT-lag, 위반 아님) |

### 결론
- **현재 코드 PHASE1은 회귀 0, 최근 변경(L3-01/IC01/overlay v23) 정합, 단위 불변식 유지.** PHASE2 진행 가능.
- **단, 신뢰도를 완성하려면 잔여 사각 처리 필요(아래).**

---

## 사각 해소 (A) — 단위빌드 perf (Phase A)

### 근본 원인: O(cases × units) 준-이차
`_derive_case_scores_from_units`(phase1_case_builder.py:2286)가 **case마다 전체 units를 스캔**해 ref 교집합 →
40k행서 8405 cases × 6287 units ≈ 5300만 교집합. 984k선 cases·units 둘 다 ~25배 → ~625배 폭발 →
전수 빌드 20분+ 무진행 스톨(스왑 아닌 CPU 준-이차).

### 수정: (rule_id,row_index) → unit 역인덱스
case당 실제 공유 ref를 가진 unit만 수집(근사선형). unit_index로 원래 순서 복원해 동작 불변.

### 측정 (프로파일러 tools/scripts/profile_unit_build.py)
| rows | 수정 전 build | 수정 후 build | per-row 배율 |
|------|--------------|--------------|-------------|
| 40k | ~95s | ~65s | — |
| 80k | 418.8s | 248.7s | **1.00 (선형화)** |

- 수정 전 per-row 배율 1.16(super-linear) → 후 1.00(선형). `_derive_case_scores`가 핫스팟에서 소거됨.
- 전수(984k) 추정: 선형 ~25분(features+detectors 포함 ~35분), 메모리 선형 → 16GB 완주 가능.
- 회귀: case builder 99 + detection 1407 passed (동작 불변).
- 잔여 상수배(후속, perf 추가): bool_column 5만회 재coercion(~10s), compute_topic_scores 14692회(~12s) —
  boolean 컬럼 1회 사전 coercion으로 ~20% 추가 단축 가능(dtype 부작용 검증 후, 별도).

### 전수 빌드 완주 (perf 수정 효과 확정)
- O(n²) 수정 후 v23 984k 전수 빌드 **완주**(이전엔 스톨). cases 32,155 / units 92,221 / raw_hits 661,240 / truth catch 62.
- artifact: artifacts/phase1_cases/_anonymous/phase1case__..._v23_current_phase1_*.json

### Tier3 disjoint 전수 실측 (check_unit_disjoint.py) — 진짜 위반 1건 발견
- document↔flow 겹침: **0** (R1 흡수 정상 — 92,111 document units vs 110 flow units 분리).
- **그러나 8개 문서가 reversal flow 2개에 중복 소속** → disjoint_pass=**false**.
  - 예: doc 019e9dbc-...-49f044000e00 ∈ {reversal_0bd91.., reversal_ec6b1..}.
  - 전부 overlay 주입 L2-05 역분개 문서. 8/92,327 = 0.0087%.
- 의미: **단위 테스트(소형 fixture)는 통과했지만 전수에서 reversal flow 구성의 disjoint 버그가 드러남.**
  전수 실측의 가치. → reversal flow 그룹핑이 한 문서를 2개 역분개 흐름에 넣음(소규모, L2-05 한정).
- **해결(2026-06-11):** 원인은 `_flow_units_from_l205_minimal_link_keys`가 세 L2-05 빌더를 합칠 때 부분
  겹침(one_to_one ∩ rolling)을 못 막은 것. `seen_documents` 문서 단위 dedup으로 단일 primary 흡수 보장.
  v23 재빌드 실측 **8→0, disjoint_pass true** 확정. 상세: [PHASE1_OPEN_ISSUES.md](PHASE1_OPEN_ISSUES.md).

---

## 사각 해소 — 잔재/일회용 스크립트 정리

옛 쓰레기 데이터(manipulation_v2/v7/fixed5/contract_v2/v3/v126) 의존 일회용 자산 정리.
- 삭제: garbage-data 일회용 스크립트 **185개**(tools/scripts/·scripts/), 죽은 테스트 **14개**(삭제 스크립트 import +
  stale LLM 테스트). git-tracked는 reversible.
- 보존: 현재 검증 도구 7종(profile_phase1_v126 등 live 의존) + materialize_* 생성기 + 제품(src/) + KPI 가드.
- 안전 확인: 제품 import smoke OK, 전체 테스트 **collection 에러 0**(정리 전 1 → 0), 4495 collected.
- 잔여(별도): phase2_family_policy.py가 fixed5 아티팩트 로드(PHASE2 재설계 때 교체), tests/datasynth_quality_gate*/results/ 옛 결과물.

---

### 잔여 사각 / 후속 (정직)
1. **KPI 가드 미작동(가장 중요)**: 아티팩트 25일 노후 + manipulation_v2/contract_v2 raw 부재로 현재 코드 재검증 불가.
   → 데이터 재확보 또는 v23/v29 기반 baseline 재정의(도메인 사유 명시).
2. **단위 빌드 perf**: 9.8GB/15분+ 미튜닝 → 16GB RAM서 전수 빌드 불가. O(n²)/메모리 프로파일링 필요.
3. **stale 테스트 2건**: rule_count(67→70), priority_band(0.75→0.90) SoT 재조정.
4. **dashboard 테스트 2건**: render_candidate_card 등 리팩터 정합(진행 중 dashboard 작업 소관).
5. **부재 데이터셋 의존 테스트 ~32건**: v7/fixed5 truth csv 부재 — 데이터 재확보 또는 skip 처리.
6. **L2-04 측정도구**, **IC01 review detector-only 미집계**(PHASE2 핸드오프 의미 확정).
