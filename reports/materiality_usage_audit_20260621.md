# 중요성·금액 임계 사용 룰 전수 조사 (2026-06-21)

질문: "회사 규모 대비 수행중요성(materiality) 기준은 L4-03만 쓰는가?"
방법: `src/detection` 전 파일에서 `materiality_amount`/`min_amount`/`_quantile`/절대금액 리터럴/`approval_threshold` 전수 grep → 각 사용 지점이 실제 발화·점수에 쓰이는지 확인(존재≠사용).
분모: rule_scoring `RULE_SCORING_METADATA` 37개(L1-01~D02) + family/macro(IC01~03·GR01/03·AA01·R02/R07/R08/R09·TS·D01/D02). 금액 패턴 매칭 파일 15개를 전부 확인.

## 결론

**회사 규모 대비 수행중요성을 발화 기준으로 쓰는 룰 = L4-03 단 하나.**
나머지 룰은 ① 금액을 아예 안 보거나, ② 본다면 분위수(모집단 상대) / 절대 리터럴·승인한도 / default 0 필터로 본다 — 수행중요성과 다른 방식이다.

## 금액 기준 사용 현황 (사용하는 것만; 미기재 룰은 금액 임계 미사용)

| 룰/로직                    | 함수·위치                                            | 금액 기준 종류                                                       | 사용처              | 비고                                                  |
| -------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------- | ------------------- | ----------------------------------------------------- |
| **L4-03**                  | `anomaly_rules_simple.c08`/`_compute_pbt_thresholds` | **수행중요성**(마감NI·매출 자동산출 + `materiality_amount` override) | **발화(binary)**    | 유일한 수행중요성 발화 룰                             |
| L2-01 승인한도             | `access_audit_rules`:196~224                         | 승인한도 절대금액(`approval_thresholds` 설정)                        | 발화                | 한도 직하·초과. 입력 설정                             |
| AA01 고액                  | `access_audit_rules`:19/70                           | 분위수 `high_amount_quantile`(0.90)                                  | 발화                | 모집단 상대(회사규모 비반영)                          |
| GR01 IC엣지                | `graph_rules`:181                                    | `min_amount` 1천만원 리터럴 default                                  | 사전필터            | 엣지 압축용. max_edges 초과 시 분위수 자동상향        |
| L2-04 비용자산화(B11)      | `fraud_rules_groupby`:992                            | `expense_capitalization_min_amount` default 0                        | 소액 제외           | default 0=미적용                                      |
| R02/R07 재활성화           | `relational_graph_features`:248                      | `min_amount` default 0                                               | 소액 스킵           | default 0=미적용                                      |
| R08 신규 거래처 고액       | `relational_rules`:47/72                             | 분위수 `large_quantile`(0.90)                                        | 발화                | 모집단 상대                                           |
| (case 정렬) `amount_score` | `phase1_case_builder`:4594                           | `materiality_amount`(있으면) / 모집단 상대 max                       | case 우선순위 정렬  | **룰 발화 아님**(case 공통 tiebreak)                  |
| (case 점수) priority       | `phase1_case_builder`:4411                           | `total_amount >= 1억` 절대 리터럴 (`amount_score`와 OR)              | case priority +0.12 | **§3 점검 후보**: 절대 1억 고정. 단 amount_score와 OR |
| (case 표시) band           | `phase1_case_builder`:4149/5619                      | 10M/100M/1B 리터럴                                                   | 드릴다운 라벨       | 표시용. 분석 비구동                                   |

## 죽은 코드 (호출처 0, 발화·점수 어디서도 안 씀)

| 항목                                                       | 위치                           | 원래 의도            | 상태                     |
| ---------------------------------------------------------- | ------------------------------ | -------------------- | ------------------------ |
| `_l107_component_scores`(amount_materiality 10M/100M/1B)   | `fraud_rules_access`:1661~1789 | L1-07 금액 버킷 점수 | 호출처 0                 |
| `_self_approval_immediate_override_mask`(materiality 10억) | `fraud_rules_access`:857       | L1-05 금액 격상      | 호출처 0                 |
| `_self_approval_review_mask`                               | `fraud_rules_access`:837       | L1-05 review 격상    | 호출처 0                 |
| `manual_override_signal_mask`                              | `fraud_rules_access`:1342      | 수기 override 신호   | 자기 캐시만, 외부 호출 0 |

→ 이 죽은 코드들이 "L1-05/L1-07이 금액 중요성을 쓴다"는 착시를 만들었으나, 실제 발화는 안 씀. 제거 대상.

## 금액 임계 미사용 룰 (대다수)

L1-01·02·03·04·06·08, L1-07·L1-07-02, L2-02·03(a~d)·05, L3-02·03·04·05·06·07·09·10·11·12, L4-01·02(Benford)·04·05·06, D01·D02 — 금액 절대임계를 발화·점수에 쓰지 않는다(시점·통제·계정논리·구조 신호).
