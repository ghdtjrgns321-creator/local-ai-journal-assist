# Phase1 Detection 결과 - datasynth_manipulation

> **실행일**: 2026-05-07 (fresh run)
> **데이터셋 성격**: contract 검증용이 아니라 조작/주입 truth 기반 평가용
> **평가 기준**: `anomaly_labels`, `manipulated_entry_truth`, `revenue_manipulation_*` label family (`rule_truth.csv` 아님)
> 이전 `phase1_manipulation_profile.json`은 재사용하지 않았고, 새로 생성한 `phase1_manipulation_fresh_*` 산출물 기준이다.

---

## 핵심 요약

**한 줄 결론**: Phase1은 조작 신호를 **감지(score)**는 잘 하지만, 조작 truth를 case 상단으로 **정렬(ranking)**하는 것은 별도 과제다.

| 평가 축 | manipulated_entry_truth (420건) | 평가 |
|---|---|---|
| Score 포착 (`anomaly_score > 0`) | 404건 / **96.2%** | 양호 |
| Case 진입 | 238건 / 56.7% | 중간 |
| Top1000 case 진입 | 64건 / **15.2%** | 약함 |

가장 약한 시나리오 (case 진입 기준):

- `approval_sod_bypass`: 6.9% (29건 중 2건)
- `manual_revenue_entry`: 23.5% (17건 중 4건)
- `unusual_timing_manipulation`: 23.8% (21건 중 5건)

---

## 1. 입력 / 출력 / 산출 파일

### 1.1 입력 데이터

| 항목 | 값 |
|---|---:|
| 저장 row | 1,095,158 |
| document | 317,505 |
| journal columns | 49 |
| label 파일 수 | 38 |
| 제거된 contract-only fixture docs | 1,688 |
| 제거된 직접 라벨 컬럼 | `is_fraud`, `fraud_type`, `is_anomaly`, `anomaly_type` |

### 1.2 Phase1 출력

| 항목 | 값 |
|---|---:|
| 전체 소요 시간 | 536.439초 |
| 생성된 case 수 | 20,369 |
| macro finding 수 | 100 |
| High row | 12,545 |
| Medium row | 158,181 |
| Low row | 1,326 |
| Normal row | 923,106 |

### 1.3 산출 파일

- checkpoint: `artifacts/phase1_manipulation_fresh_profile.json`
- case input cache: `artifacts/phase1_manipulation_fresh_case_input.pkl`
- case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260507T070451Z.json`
- truth 평가 JSON: `artifacts/manipulation_truth_eval_fresh.json`
- truth 평가 CSV: `artifacts/manipulation_truth_eval_fresh.csv`

---

## 2. 실행 시간

| 단계 | 소요 시간 |
|---|---:|
| CSV load | 8.807초 |
| feature.time | 1.761초 |
| feature.amount | 38.398초 |
| feature.pattern | 4.836초 |
| feature.text | 11.554초 |
| detector.layer_a | 16.990초 |
| detector.layer_b | 121.912초 |
| detector.layer_c | 164.153초 |
| detector.benford | 6.538초 |
| aggregate | 34.219초 |
| Phase1 case builder | 111.047초 |
| **합계** | **536.439초** |

**병목 순서**: `layer_c` (164초) > `layer_b` (122초) > `case builder` (111초) > `feature.amount` (38초). `layer_c` 안에서는 `L2-05`가 54.629초로 가장 크고, S1/S2가 대부분을 차지했다.

---

## 3. Truth family별 score 포착 결과

문서 단위 매칭 — 한 document에 truth label이 붙어 있는지 vs Phase1 score/case가 그 document에 hit했는지.

| truth file | truth docs | score > 0 | score % | case docs | case % | Top100 | Top1000 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `anomaly_labels` | 2,992 | 2,966 | 99.1% | 1,597 | 53.4% | 650 | 879 |
| `manipulated_entry_truth` | 420 | 404 | 96.2% | 238 | 56.7% | 12 | 64 |
| `revenue_manipulation_l401_direct_truth` | 22 | 22 | 100.0% | 19 | 86.4% | 3 | 3 |
| `revenue_manipulation_subtypes` | 137 | 136 | 99.3% | 80 | 58.4% | 6 | 17 |
| `revenue_manipulation_combination_coverage` | 115 | 114 | 99.1% | 61 | 53.0% | 3 | 14 |

**해석**:

- Score 포착은 96~100%로 일관되게 높다. 조작 신호 자체는 거의 다 잡힌다.
- Case 진입률은 53~58% 수준. L4-01 직접 truth만 86.4%로 두드러진다.
- Top100/Top1000 진입은 낮다. 즉 탐지는 되지만 case 상단으로는 잘 안 올라간다.
- 결과적으로 "신호가 있는가"와 "감사자가 먼저 보는 case에 들어오는가"는 별개의 질문이다.

---

## 4. manipulated_entry scenario별 결과

`labels/manipulated_entry_truth.csv` 기준. L1~L4 조합이 조작 entry를 얼마나 드러내는지 보는 truth (특정 rule 정답이 아님).

| scenario | truth | score % | case % | Top1000 |
|---|---:|---:|---:|---:|
| `fictitious_entry` | 168 | **100.0%** | 60.1% | 18 |
| `period_end_adjustment_manipulation` | 92 | **100.0%** | 66.3% | 22 |
| `embezzlement_concealment` | 76 | **100.0%** | 67.1% | 19 |
| `circular_related_party_transaction` | 34 | 91.2% | 52.9% | 2 |
| `approval_sod_bypass` | 29 | 69.0% | **6.9%** | 2 |
| `unusual_timing_manipulation` | 21 | 81.0% | 23.8% | 1 |

**잘 잡히는 영역** (score 100% + case 60% 이상):

- `fictitious_entry`, `period_end_adjustment_manipulation`, `embezzlement_concealment`

**약한 영역**:

- `approval_sod_bypass` — case 6.9%. 승인 우회·위임·긴급 승인 같은 정책·워크플로우 맥락이 강한데, 현재 rule은 명시적 SoD 위반 필드 위주라 단서가 부족하다.
- `unusual_timing_manipulation` — case 23.8%. 시간 단서만으로는 row-level 강도가 약해 case 상단으로 승격되지 않는다.

---

## 5. Revenue manipulation 결과

### 5.1 L4-01 직접 truth

대상: `high_value_revenue_outlier`만 담은 L4-01 직접 정답 subset.

| 항목 | 값 |
|---|---:|
| truth docs | 22 |
| score > 0 | 22 (**100.0%**) |
| case docs | 19 (86.4%) |
| Top1000 | 3 |

직접 정답은 모두 score로 포착되고 22건 중 19건이 case에 진입한다. 다만 Top1000 안에는 3건만 들어간다. **포착은 되지만 ranking 최상단으로 일관되게 밀어올리지는 않는다.**

### 5.2 Revenue subtype coverage

`labels/revenue_manipulation_subtypes.csv` 기준. `high_value_revenue_outlier` 외 subtype은 L4-01 단독 정답이 아니라 조합/후속 평가 coverage다.

| subtype | truth | score % | case % | Top1000 |
|---|---:|---:|---:|---:|
| `cutoff_mismatch` | 28 | 100.0% | 53.6% | 2 |
| `high_value_revenue_outlier` | 22 | 100.0% | 86.4% | 3 |
| `period_end_push` | 20 | 100.0% | 75.0% | 5 |
| `reversal_return_credit` | 20 | 95.0% | 45.0% | 2 |
| `process_account_mismatch` | 18 | 100.0% | 50.0% | 2 |
| `manual_revenue_entry` | 17 | 100.0% | **23.5%** | 0 |
| `composite_low_amount_dispersion` | 12 | 100.0% | 75.0% | 3 |

**핵심**: revenue subtype 전체 score 포착률 99.3%. case 진입률은 subtype별로 23.5~86.4%로 격차가 크다. `manual_revenue_entry`는 score는 다 잡지만 case 진입은 23.5%에 그친다 — 수기 수익 entry가 항상 high-priority case로 올라가지는 않는다.

---

## 6. Case ranking 분석

`manipulated_entry_truth` 420건이 case 목록 상단에 얼마나 들어오는지 본 결과다.

### 6.1 Top N 기준

| 범위 | case docs | manipulated truth |
|---|---:|---:|
| Top 10 | 429 | 8 |
| Top 50 | 1,466 | 9 |
| Top 100 | 2,746 | 12 |
| Top 500 | 10,356 | 47 |
| Top 1000 | 13,942 | 64 |

### 6.2 Priority band 기준

| band | case 수 | case docs | manipulated truth |
|---|---:|---:|---:|
| high | 3,660 | 39,903 | 159 |
| medium | 7,580 | 48,306 | 204 |
| low | 9,129 | 9,806 | 53 |

**해석**:

- manipulated truth는 High/Medium에 분산되어 있고 low band에도 53건 존재.
- Top100 안에는 12건뿐. 즉 현재 ranking은 "조작 truth 최우선"이 아니라 **"Phase1 전반 위험 case 정렬"**에 가깝다.
- 조작 평가 목적이면 case 상단만 보지 말고 score, rule/review hit, scenario별 case 진입률을 함께 봐야 한다.

---

## 7. 미포착 분석 (16건)

`manipulated_entry_truth` 420건 중 score 기준으로 못 잡은 문서는 **16건**이다.

**기준**:

- 포착: `anomaly_score > 0` 또는 `flagged_rules`/`review_rules` 존재
- 미포착: 위 셋이 모두 없음

### 7.1 시나리오별 분포

| scenario | 미포착 수 | 주요 stealth profile |
|---|---:|---|
| `approval_sod_bypass` | 9 | `workflow_owner`, `delegated_route`, `urgent_approval` |
| `unusual_timing_manipulation` | 4 | `weekend_posting`, `backlog_release`, `late_night_close` |
| `circular_related_party_transaction` | 3 | `intercompany_settlement` |

> 16건 모두 `not_rule_targeted=True` truth다 — 특정 룰에 맞춘 정답이 아니라 L1~L4 조합이 stealth/context형 조작을 드러내는지 보는 평가 샘플.

### 7.2 미포착 문서 상세

#### `approval_sod_bypass` (9건)

| document_id | year | 회사 | stealth | 금액 | lines |
|---|---:|---|---|---:|---:|
| `01ca7875-ec4b-45ef-a162-ef6ade13ff1d` | 2022 | C001 | workflow_owner | 75,140,002 | 2 |
| `02acf1e6-81d6-4bcb-b30b-d3520d453f32` | 2022 | C003 | urgent_approval | 69,700,000 | 4 |
| `041c02a8-aa1d-48d7-8780-696c7348a886` | 2022 | C001 | workflow_owner | 63,269,916 | 2 |
| `025166a4-5fbf-4b77-9e6d-823a7506ffd9` | 2023 | C002 | delegated_route | 41,084,810 | 6 |
| `09b8007f-52d5-4c2b-b327-8e30175e2720` | 2023 | C003 | urgent_approval | 92,960,000 | 2 |
| `09bace1b-b59d-402f-8c25-57c3b7603558` | 2023 | C003 | urgent_approval | 21,434,848 | 2 |
| `06c9bce7-1e6a-4bcb-ae4d-0ba1554fefda` | 2024 | C002 | delegated_route | 597,231,650 | 2 |
| `08f658a6-58ff-4179-887f-7872035256cb` | 2024 | C002 | delegated_route | 68,050,080 | 4 |
| `02f36bb8-b095-492f-9f9e-96b8e58150a6` | 2024 | C003 | urgent_approval | 28,840,000 | 3 |

공통 패턴: automated A2R 전표 + 승인 우회·위임·긴급 승인 맥락. 현재 Phase1 rule은 명시적 SoD/self/skipped/delay 필드를 보기 때문에 위임 경로나 긴급 승인 자체는 신호로 표현되지 않는다.

#### `unusual_timing_manipulation` (4건)

| document_id | year | 회사 | stealth | 금액 | lines |
|---|---:|---|---|---:|---:|
| `00e02d6d-af71-4255-8ca0-df3dd6358f1d` | 2023 | C002 | weekend_posting | 440,000 | 4 |
| `0050129f-41e0-43ff-8cd0-7376064424c0` | 2023 | C003 | backlog_release | 10,568 | 3 |
| `07a0a106-a106-464c-a3fc-82c2eb6ba91f` | 2023 | C001 | late_night_close | 59,208 | 2 |
| `0789c53d-8b21-461c-9258-e8c06357151a` | 2024 | C002 | weekend_posting | 319,590 | 4 |

공통 패턴: automated A2R + 소액 + weekend/late-night/backlog 시간 단서. 시간 단서만으로는 case seed로 승격되지 않는다.

#### `circular_related_party_transaction` (3건)

| document_id | year | 회사 | stealth | 금액 | lines |
|---|---:|---|---|---:|---:|
| `001e865b-086d-4dc4-b744-240a89aaa095` | 2022 | C001 | intercompany_settlement | 507,370 | 2 |
| `0010a650-c4f5-44b5-ae7c-93c491e1268f` | 2023 | C001 | intercompany_settlement | 57,726 | 3 |
| `001ddd9d-3846-4487-a2a9-3bca3f75d75e` | 2024 | C001 | intercompany_settlement | 33,972 | 4 |

공통 패턴: 소액 O2C 자동 정산. 순환·관계망은 row-level이 아니라 graph 기반 분석이 필요한데, 본 실행에서는 graph/relational 계열이 inference path에 없다.

### 7.3 원인 정리

| 시나리오 | 핵심 원인 |
|---|---|
| `approval_sod_bypass` | 위임·긴급·owner 우회 등 **워크플로우 맥락**을 현재 rule이 직접 표현하지 못함 |
| `unusual_timing_manipulation` | 시간 단서만으로는 약함. automated + 소액 + 평범한 계정이면 묻힘 |
| `circular_related_party_transaction` | row-level rule의 한계. **graph/relational 분석 필요** |

---

## 8. Top ranking에서 조작 truth가 밀리는 이유

`manipulated_entry_truth` 420건 중 score 포착은 404건이지만 Top100에는 12건, Top1000에는 64건만 들어간다. 이는 탐지 실패가 아니라 ranking 목적 함수와 case builder 정책의 결과다.

| # | 이유 | 영향 |
|---|---|---|
| 1 | Phase1 ranking은 조작 전용이 아니라 **전체 감사 위험 정렬** | 정합성·cutoff·outlier·통제·수기 신호와 같은 큐에서 경쟁 |
| 2 | Score 포착 ≠ case 승격 | score 있는 404건 중 case 진입은 238건. 약신호·context-only는 medium/low로 남음 |
| 3 | 일부 truth는 의도적 `not_rule_targeted=True` | approval bypass, delegated route, intercompany settlement는 직접 hit가 약함 |
| 4 | automated/background 전표는 priority 가중치가 낮음 | 미포착·후순위 truth 상당수가 `source=automated` |
| 5 | Top ranking은 case 규모와 복합 신호 선호 | 단일 약신호 조작 전표는 다중-rule 통제·통계 case에 밀림 |
| 6 | 관계사·순환은 graph 없이 row-level만으로는 약함 | relational/graph 계열이 inference path에 없음 |

**결론**: "조작 신호 감지" 기준에는 양호. "조작 truth 최상단 정렬" 기준에는 약함. 조작 평가 ranking을 별도로 두려면 `manipulation_candidate` queue 또는 truth-oriented ranking feature를 분리해야 한다.

---

## 9. Theme별 case 분포

| theme | case 수 | high | medium | low |
|---|---:|---:|---:|---:|
| `timing_anomaly` | 7,988 | 2,765 | 3,758 | 1,465 |
| `intercompany_structure` | 5,568 | 41 | 98 | 5,429 |
| `control_failure` | 3,953 | 467 | 2,967 | 519 |
| `logic_mismatch` | 1,536 | 327 | 496 | 713 |
| `statistical_outlier` | 1,054 | 40 | 219 | 795 |
| `duplicate_or_outflow` | 251 | 3 | 42 | 206 |
| `data_integrity_failure` | 19 | 17 | 0 | 2 |

- 가장 큰 theme은 `timing_anomaly`.
- `control_failure`는 manipulation truth와 연결되지만 `approval_sod_bypass` 자체는 case 우선순위로 강하게 올라오지 않는다.
- `data_integrity_failure`가 19건뿐인 것은 contract-only fixture 1,688건을 제거한 효과다 (contract dataset에서는 상단을 지배했음).

---

## 10. 결론 및 다음 단계

### 10.1 종합 판단

| 평가 관점 | 결과 |
|---|---|
| 조작 신호 감지 (score) | **양호** |
| 조작 truth case 진입 | 중간 |
| 조작 truth 상단 ranking | **약함** |

### 10.2 강한 영역

- `fictitious_entry`, `period_end_adjustment_manipulation`, `embezzlement_concealment`: score 100% + case 60% 이상
- `revenue_manipulation_l401_direct_truth`: score 100% + case 86.4%

### 10.3 개선 후보

- `approval_sod_bypass`: 워크플로우 context를 표현하는 feature/rule 필요
- `unusual_timing_manipulation`: 시간 단서를 case 승격 신호로 강화
- `manual_revenue_entry`: case 우선순위 가중치 조정
- `circular_related_party_transaction`: graph/relational 분석 도입
- 전반: **조작 평가 전용 ranking** (`manipulation_candidate` queue) 분리 검토

### 10.4 해석 주의

`datasynth_manipulation`은 fraud-label ML/DL 실험과 manipulation scenario 평가용 데이터셋이다. `datasynth_contract`처럼 rule contract 100% 통과 여부를 보는 데이터셋이 아니다.
