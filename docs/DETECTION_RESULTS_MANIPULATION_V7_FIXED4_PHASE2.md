# Phase2 family lane 결과 — V7 fixed5_normalcal5 최신 재측정

> **문서 상태 (2026-05-26)**: 파일명은 과거 fixed4 문서명을 유지하지만, 본문은 `fixed5_normalcal5` 데이터와 2026-05-25 현재 PHASE2 family 수정 상태를 기준으로 갱신했다. 과거 fixed4 수치는 본문 기준선으로 사용하지 않는다.

> **역할 원칙**: PHASE1/PHASE2는 fraud 확정기가 아니다. 본 문서의 truth 기반 recall은 DataSynth 합성 데이터에 대한 개발 검증용 지표이며, 실제 운영 부정 탐지 성능으로 주장하지 않는다.

> **측정 단위**: recall은 synthetic truth document 620건 기준이다. review queue는 PHASE1 case 단위로 정렬하지만, recall은 TOP-N case 안에 포함된 unique truth document 수로 계산한다.

> **측정 계약 고정**: family 단독 recall은 canonical case-level family queue로 측정한다. 구현 단일 출처는 `tools/scripts/phase1_phase2_integration_stage7.py::measure_phase2_family_single_recall`이다. raw document-level family score 정렬은 `family_single`으로 부르지 않는다.

---

## 1. 입력과 산출물

| 항목 | 값 |
|---|---:|
| 데이터셋 | `datasynth_manipulation_v7_candidate_fixed5_normalcal5` |
| 전체 document | 318,653 |
| synthetic truth document | 620 |
| PHASE1 case | 23,166 |
| PHASE2 family | unsupervised, timeseries, relational, duplicate, intercompany |
| 공식 평가 범위 | PHASE2 family 단독 lane |

주요 산출물:

- `artifacts/stage7_fixed5_current_family_after_all_20260525_report.json`
- `artifacts/stage7_fixed5_current_family_after_all_20260525_phase2_family_by_doc.parquet`

현재 제품 해석은 단일 score가 아니라 family별 독립 review lane이다.

---

## 2. 한눈에 보는 결론

PHASE2 family들은 하나의 단일 점수로 해석할 때보다 family lane별로 해석할 때 의미가 더 분명하다.

| Family | TOP100 matched | TOP100 주력 유형 | 해석 |
|---|---:|---|---|
| `unsupervised` | 79 | `fictitious_entry` | VAE 기반 통계적 이상치 lane. TOP100은 사실상 fictitious entry에 특화된다. |
| `timeseries` | 12 | `suspense_account_abuse` | 결산·시점 context lane. TOP100 precision ranker가 아니라 깊은 검토 범위에서 coverage를 보조한다. |
| `relational` | 24 | `embezzlement_concealment` | 관계/사용자/거래처 구조 lane. TOP100은 embezzlement 쪽에 치우치고, TOP500부터 분산된다. |
| `duplicate` | 221 | `suspense_account_abuse`, `expense_capitalization` | TOP100에서도 가장 강하고 가장 넓게 잡는 family다. |
| `intercompany` | 26 | `circular_related_party_transaction` | 관계사 reciprocal/circular 구조에 특화된다. |

판단:

1. PHASE2 family들은 마구잡이로 truth를 잡는 구조가 아니다.
2. TOP100에서는 각 family의 전문성이 강하게 드러난다.
3. TOP500부터는 `relational`, `duplicate`, `intercompany`가 여러 scenario로 확장된다.
4. PHASE2는 단일 순위보다 family별 review lane으로 노출하는 것이 더 방어 가능하다.

---

## 3. Family 단독 recall

아래 표는 canonical case-level family queue 기준이다. 각 family별로 `phase2_<family>_score_max`, `total_amount`, `rule_count` 순으로 case를 정렬한 뒤 TOP-N 안의 unique truth document를 센다.

| Family | TOP100 | TOP500 | TOP1000 | TOP2000 | TOP5000 | TOP10000 |
|---|---:|---:|---:|---:|---:|---:|
| unsupervised | 79 / 12.74% | 198 / 31.94% | 283 / 45.65% | 361 / 58.23% | 455 / 73.39% | 503 / 81.13% |
| timeseries | 12 / 1.94% | 53 / 8.55% | 53 / 8.55% | 397 / 64.03% | 468 / 75.48% | 509 / 82.10% |
| relational | 24 / 3.87% | 289 / 46.61% | 295 / 47.58% | 298 / 48.06% | 334 / 53.87% | 514 / 82.90% |
| duplicate | 221 / 35.65% | 255 / 41.13% | 273 / 44.03% | 277 / 44.68% | 294 / 47.42% | 386 / 62.26% |
| intercompany | 26 / 4.19% | 60 / 9.68% | 136 / 21.94% | 417 / 67.26% | 487 / 78.55% | 525 / 84.68% |

관찰:

- `duplicate`는 TOP100에서 가장 강한 family다.
- `unsupervised`는 TOP100에서 fictitious entry에 강하게 특화된다.
- `intercompany`는 TOP100에서는 circular/reciprocal 유형에 특화되고, 깊은 구간에서 coverage가 확장된다.
- `timeseries`는 TOP100/TOP500에서 약하다. 이 family는 결산·시점 context lane으로 고정한다.
- `relational`은 TOP500부터 여러 유형으로 퍼지며, 중간 깊이 review lane으로 해석한다.

---

## 4. TOP100 specialization

TOP100 기준으로 보면 family별 주력 scenario가 뚜렷하다.

| Family | TOP100 matched | 잡은 유형 수 | 1위 유형 | 1위 비중 | TOP100 구성 |
|---|---:|---:|---|---:|---|
| `unsupervised` | 79 | 2 | `fictitious_entry` | 98.7% | fictitious 78, unusual_timing 1 |
| `timeseries` | 12 | 2 | `suspense_account_abuse` | 83.3% | suspense 10, fictitious 2 |
| `relational` | 24 | 3 | `embezzlement_concealment` | 75.0% | embezzlement 18, circular 5, fictitious 1 |
| `duplicate` | 221 | 6 | `suspense_account_abuse` | 45.2% | suspense 100, expense 91, fictitious 18, circular 5, approval 4 |
| `intercompany` | 26 | 3 | `circular_related_party_transaction` | 92.3% | circular 24, expense 1, suspense 1 |

해석:

- TOP100에서는 `unsupervised`, `intercompany`가 거의 전용 lane처럼 동작한다.
- `duplicate`는 TOP100에서도 여러 scenario를 동시에 잡는다. 이 family가 PHASE2에서 가장 강한 상단 lane이다.
- `timeseries`는 TOP100에서 약하지만 무작위가 아니다. suspense 계열 시점/context를 일부 포착한다.
- `relational`은 embezzlement 계열에 강하게 반응한다.

---

## 5. TOP500 scenario matrix

TOP500으로 확장하면 family별 분산이 더 분명해진다. 괄호 안은 해당 scenario truth 중 family TOP500에 포함된 비율이다.

| Scenario | truth_n | unsupervised | timeseries | relational | duplicate | intercompany |
|---|---:|---:|---:|---:|---:|---:|
| `fictitious_entry` | 168 | 99 (59%) | 2 (1%) | 53 (32%) | 18 (11%) | 0 (0%) |
| `expense_capitalization` | 100 | 93 (93%) | 0 (0%) | 90 (90%) | 91 (91%) | 8 (8%) |
| `suspense_account_abuse` | 100 | 0 (0%) | 34 (34%) | 100 (100%) | 100 (100%) | 8 (8%) |
| `period_end_adjustment_manipulation` | 92 | 0 (0%) | 4 (4%) | 0 (0%) | 12 (13%) | 2 (2%) |
| `embezzlement_concealment` | 76 | 0 (0%) | 0 (0%) | 37 (49%) | 0 (0%) | 8 (11%) |
| `circular_related_party_transaction` | 34 | 0 (0%) | 7 (21%) | 5 (15%) | 24 (71%) | 33 (97%) |
| `approval_sod_bypass` | 29 | 2 (7%) | 6 (21%) | 4 (14%) | 10 (34%) | 1 (3%) |
| `unusual_timing_manipulation` | 21 | 4 (19%) | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) |

family별 해석:

- `unsupervised`: `fictitious_entry`, `expense_capitalization`에 강하다.
- `timeseries`: TOP500에서는 약하지만 `suspense_account_abuse`, `circular_related_party_transaction`, `approval_sod_bypass` 일부를 포착한다.
- `relational`: `suspense_account_abuse`, `expense_capitalization`, `embezzlement_concealment`에 강하다.
- `duplicate`: `suspense_account_abuse`, `expense_capitalization`, `circular_related_party_transaction`을 동시에 포착한다.
- `intercompany`: `circular_related_party_transaction`에 매우 강하다.

---

## 6. Family별 분산 지표

| Family | TOP500 matched | 잡은 유형 수 | 1위 유형 비중 | HHI | 유효 유형 수 | 해석 |
|---|---:|---:|---:|---:|---:|---|
| `unsupervised` | 198 | 4 | 50.0% | 0.471 | 2.29 | 두 유형 중심의 통계적 이상치 lane |
| `timeseries` | 53 | 5 | 64.2% | 0.449 | 3.06 | 약한 context lane, 상단 recall 목적 아님 |
| `relational` | 289 | 6 | 34.6% | 0.267 | 4.20 | 가장 균형적인 구조적 family 중 하나 |
| `duplicate` | 255 | 6 | 39.2% | 0.299 | 4.12 | 상단 성능과 분산을 동시에 보유 |
| `intercompany` | 60 | 6 | 55.0% | 0.357 | 3.73 | circular 중심이지만 TOP500에서는 일부 확장 |

`유효 유형 수`는 scenario 비중의 entropy를 기준으로 계산한 값이다. 값이 클수록 한 유형에 덜 쏠린다.

---

## 7. 포트폴리오용 해석

현재 가장 방어 가능한 설명은 다음과 같다.

1. PHASE1은 deterministic rule/evidence 기반의 1차 review queue다.
2. PHASE2는 PHASE1 결과 CSV에 의존하지 않고 원본 CSV에서 독립적으로 family score를 계산한다.
3. PHASE2는 family별 독립 review lane이다.
4. `duplicate`, `unsupervised`, `intercompany`는 TOP100에서 각자의 specialization이 뚜렷하다.
5. `relational`, `duplicate`는 TOP500에서 여러 scenario로 확장된다.
6. `timeseries`는 단독 precision ranker가 아니라 결산·시점 context lane이다.
7. DataSynth truth 기반 recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.

금지 표현:

- “부정을 탐지했다”
- “실무 운영 성능 검증 완료”
- “Phase2 단독 fraud detector”
- “recall이 높으므로 실제 감사 적용 가능”

권장 표현:

- “synthetic anomaly review queue 농축”
- “family별 독립 review lane”
- “review-worthy candidate 우선순위화”
- “PHASE1 deterministic evidence와 PHASE2 statistical/structural evidence의 분리 운영”
