# Phase 0 — 회귀 baseline 고정

측정 2026-06-30. 이후 모든 단계의 회귀 가드 기준값. PLAN §3 Phase 0.

## 1. pytest 통과 수 (HARD 가드)

```
uv run pytest tests/phase1_rulebase/ -q
→ 25 passed in 7.14s
```

- 통과 = **25** / 실패 = **0** / 스킵 = **0**
- **알려진 실패 = 0건.** 이후 단계 가드: "알려진 실패 0, 신규 0" 유지.
- collect 정상(0개 수집 아님). 대상 파일 6개 중 test_ 4종(batch_reader_row_mapping / case_natural_label / e2e_label_validation / rule_documents_amount).

## 2. 데이터 회사 구성 실측 (Phase 1 전제 검증)

active 데이터셋 3종 전부 **C001 단일 회사** — 계획서의 "3개사 혼합" 전제는 현재 데이터에 없음.

| 데이터셋                 | 행 수   | 회사 수 | company_codes |
| ------------------------ | ------- | ------- | ------------- |
| normal v46b              | 345,944 | 1       | C001          |
| combo_tier v46b r1z      | 328,030 | 1       | C001          |
| recall v46b phase1_1 r11 | 325,120 | 1       | C001          |

근거: `run_manifest.json` → `company_count: 1`, `company_codes: ["C001"]`, `single_rule_only: true`.
config/datasynth.yaml에는 3법인(C001/C002/C003)이 남아있으나 v46b 생성은 단일 회사로 실행됨.
→ Phase 1(회사별 루프)은 현재 no-op. 처리 방향 사용자 결정 대기(컨트랙트).

## 3. PHASE1 분포 캡처 (normal v46b)

도구: `tools/scripts/measure_phase1_current_p3_2.py` (full build: base+evidence+IC+graph+variance 트랙).
출력: `dev/active/phase1-2-code-rework/baseline_normal_v46b/summary.json`.

측정 완료(case builder 373.3s). 출력 `baseline_normal_v46b/summary.json`.

| 지표                   | 값                                      |
| ---------------------- | --------------------------------------- |
| rows                   | 345,944                                 |
| case_count             | 41,461                                  |
| unit_count             | 107,473                                 |
| priority_band_cases    | high **31,683** / medium 77 / low 9,701 |
| priority_band_units    | high 52,052 / medium 1,559 / low 53,862 |
| high/medium 기여 룰 수 | 21                                      |

(주의: 측정도구 `_priority_band_summary`는 high/medium/low 3밴드만 집계. CONTEXT 밴드는 별도 추적 안 함 — low에 포함 추정.)

### ⚠️ 이상징후 — high 31,683건 (정상 데이터 원칙 위반)

정상 데이터인데 케이스의 **76%(31,683/41,461)가 high**다. kpi_baseline.json a2 HARD 가드는 "정상 high = 0"(v42j 기준)이었다. 31,683은 0에서의 구조적 이탈이며 노이즈가 아니다.

high를 끌어올린 상위 룰(`priority_band_high_medium_rules`):

```
L2-05   high 26,419   L3-12 high 26,042   L1-07 high 23,471
L3-04   high 21,576   L4-06 high 20,825   L3-02 high 15,600
L1-06   high 13,693   ...
```

- **L3-12·L4-06·L2-05는 설계상 macro/배지 = 점수 0 기여**여야 하는데 high 밴드를 대량 생성. 0기여 강제(rule_scoring.py:38-43 / score_aggregator.py:251-254)가 band 결정에 안 먹히는 상태로 보임.
- 측정도구 곁가지(IC/graph/variance extra 트랙) 탓 아님 — 핵심 행단위 룰이 원인.
- **추정 원인**: 진행 중인 PHASE1-1 tier 재설계(순서형 점수체계, 최근 커밋 0b6ca70) 미완 상태. 작업트리에 rule_scoring·score_aggregator·rule_labels 등 대량 수정 잔존.
- **PHASE1-2 범위 밖**(이건 PHASE1-1 tier 점수 문제). 단 본 분포를 "건강한 baseline"으로 신뢰하면 안 됨. **frozen before-snapshot으로만** 사용(Phase 2 정리가 default-scope 밴드를 안 바꾸는지 회귀 확인용). 정상 high 0 회복은 PHASE1-1 workstream에서 별도 처리.
- 사용자 판단 필요: PHASE1-2 진행 전 이 high 양산을 먼저 조사할지, 아니면 PHASE1-2(밴드 무관 정리)를 먼저 진행할지.
