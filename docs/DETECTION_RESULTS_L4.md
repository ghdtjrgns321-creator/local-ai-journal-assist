# Detection Results

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
## Phase 1 L4 - DataSynth v126

대상 데이터는 `data/journal/primary/datasynth_v126_candidate`입니다.

이 문서는 L4 결과를 **세 가지 독립적인 검증 축**으로 나누어 봅니다. 세 축은 측정하는 대상이 다르므로 같은 표에 섞으면 의미를 잃습니다.

| 축  | 무엇을 검증하는가                                                   | 검증 데이터                                                                                                | 합격 기준                                     |
| :-- | :------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------------------- | :-------------------------------------------- |
| A   | 데이터 정합성 / 룰 계약사항이 문서대로 동작하는가                   | `rule_truth_L4_*.csv` (공식 정답)                                                                          | 정탐 100%, **과탐 0, 미탐 0**                 |
| B   | DETECTOR를 직접 참조하지 않고 "실제로 있을법한" sidecar를 분류하는가 | `sidecar_manifest.csv`, L4 sidecar 파일(`*_confirmed_anomalies.csv`, `*_normal_controls.csv`, boundary 등) | 책임/점수/검토/미포착 분리 타당성             |
| C   | 실제로 악의적으로 조작된 전표를 책임 영역 안에서 잡아내는가         | `manipulated_entry_truth.csv`                                                                              | L4 책임분량을 점수 또는 drilldown 신호로 포착 |

세 축의 관계:

- A축은 detector 사양과 데이터 생성기가 같은 정의를 공유하는지 보는 **계약 검증**입니다. 0/0이 합격선입니다.
- B축은 **detector 로직을 모르는 입장**에서 "현장에서 실제로 나올 만한 형태"를 sidecar로 만든 뒤 detector가 어떻게 반응하는지 봅니다. L4는 통계/행동 분석 신호이므로 "detector universe vs normal/boundary context vs confirmed subset" 분리가 핵심입니다.
- C축은 **fraud 시나리오 합성 데이터**가 L4 책임 영역(고액/Benford/희소 계정조합/비정상시간 집중/배치 이상)에 어떻게 걸리는지 봅니다.

L4는 Phase1 전체 점수에서 **단독 결론 신호가 아니라 분석/보조 신호**입니다. Phase1 집계는 L4 룰 점수를 단순 합산하지 않고 L4 family 안의 최대 normalized score에 L4 weight `0.15`를 곱합니다. L4가 잡은 건은 통계적 이상 또는 행동 이상 review queue로 올리고, L1/L2/L3 또는 다른 보강 증거와 결합될 때 우선순위가 올라가는 구조입니다.

실행 정보:

| 항목              | 값                                                                    |
| :---------------- | :-------------------------------------------------------------------- |
| 범위              | 2022, 2023, 2024 / L4-01 ~ L4-06                                      |
| 실행 방식         | 원본 CSV 직접 로드 후 L4 detector 함수 직접 호출                      |
| feature context   | 3년 통합 context에서 `TIME`, `AMOUNT`, `PATTERN` 생성 후 연도별 split |
| L4-02 평가 단위   | `fiscal_year + company_code + gl_account`                             |
| 전체 rows         | 1,109,435                                                             |
| feature 생성 시간 | 22.338초                                                              |
| 총 시간           | 224.011초                                                             |

## 요약

- **A축 결과**: 3개 연도 × 6개 룰 모두 **정탐 100%, 과탐 0, 미탐 0**. 룰 계약 정합성 합격.
- **B축 결과**: v126 기준 L4 sidecar는 `strict_truth_alias`, `confirmed_subset`, `normal_context`, `boundary_control`, `drilldown_candidate`로 분리됩니다. detector universe alias는 공식 truth와 일치하고, normal/boundary context는 독립 negative truth가 아니라 review 해석용입니다.
- **C축 결과**: 조작 전표 420건 중 L4가 포착한 전표는 32건입니다. L4-02 Benford drilldown 21건, L4-05 비정상시간 5건, L4-03 고액 4건, L4-04 희소 계정조합 2건입니다. L4 미포착 388건은 대부분 L1/L2/L3 책임 영역입니다.

세 축을 분리하는 이유:

- A축에서 차이가 작더라도 sidecar의 normal/boundary context를 과탐으로 오해하면 운영 문서가 흔들립니다.
- B축이 깨끗해도 fraud 합성 데이터에서 L4 책임분 포착이 빠지면 실제 감사에서 통계/행동 이상 신호의 효용을 설명할 수 없습니다.
- 세 축을 함께 봐야 L4가 분석/보조 신호로 의도대로 동작하는지 말할 수 있습니다.

또 "L4가 잡았다"와 "최종 위험점수에 강하게 반영한다"는 다릅니다. 예를 들어 L4-04는 희소 계정조합을 넓게 잡지만 `single_rare_pair`, `large_doc_distinct_pair`, `multiple_rare_pairs`로 점수 우선순위를 분리합니다. L4-02는 finding 단위와 drilldown 후보 전표를 분리합니다. 이 분기 자체는 B축과 C축에서 별도로 봐야 합니다.

---

## 검증 축 A — 데이터 정합성 / 룰 계약사항 (공식 truth, 미탐과탐 0건 검증)

`rule_truth_L4_*.csv`는 detector 사양에 맞추어 DataSynth가 의도적으로 만든 정답입니다. detector가 사양대로 동작한다면 **정탐 100%, 과탐 0, 미탐 0**이 나와야 합니다. 이 축은 룰 코드와 데이터 생성기 사이의 계약이 어긋나지 않는지 검증합니다.

### 룰 의미 매핑

| 룰    | 의미                | 평가 단위                               |
| :---- | :------------------ | :-------------------------------------- |
| L4-01 | 매출 조작 가능성    | document_id                             |
| L4-02 | Benford 법칙 위반   | fiscal_year + company_code + gl_account |
| L4-03 | 이상 고액 거래      | document_id                             |
| L4-04 | 비정상 계정조합     | document_id                             |
| L4-05 | 비정상시간 집중입력 | document_id                             |
| L4-06 | 배치 전표 이상      | document_id                             |

### 2022

| 룰    |  정답 |  탐지 |  정탐 | 과탐 | 미탐 |
| :---- | ----: | ----: | ----: | ---: | ---: |
| L4-01 |   331 |   331 |   331 |    0 |    0 |
| L4-02 |    35 |    35 |    35 |    0 |    0 |
| L4-03 | 1,361 | 1,361 | 1,361 |    0 |    0 |
| L4-04 | 1,564 | 1,564 | 1,564 |    0 |    0 |
| L4-05 | 1,622 | 1,622 | 1,622 |    0 |    0 |
| L4-06 |   234 |   234 |   234 |    0 |    0 |

### 2023

| 룰    |  정답 |  탐지 |  정탐 | 과탐 | 미탐 |
| :---- | ----: | ----: | ----: | ---: | ---: |
| L4-01 |   285 |   285 |   285 |    0 |    0 |
| L4-02 |    32 |    32 |    32 |    0 |    0 |
| L4-03 | 1,260 | 1,260 | 1,260 |    0 |    0 |
| L4-04 | 1,216 | 1,216 | 1,216 |    0 |    0 |
| L4-05 | 1,630 | 1,630 | 1,630 |    0 |    0 |
| L4-06 |   211 |   211 |   211 |    0 |    0 |

### 2024

| 룰    |  정답 |  탐지 |  정탐 | 과탐 | 미탐 |
| :---- | ----: | ----: | ----: | ---: | ---: |
| L4-01 |   348 |   348 |   348 |    0 |    0 |
| L4-02 |    32 |    32 |    32 |    0 |    0 |
| L4-03 | 1,394 | 1,394 | 1,394 |    0 |    0 |
| L4-04 | 1,311 | 1,311 | 1,311 |    0 |    0 |
| L4-05 | 1,712 | 1,712 | 1,712 |    0 |    0 |
| L4-06 |   247 |   247 |   247 |    0 |    0 |

### 3년 합계

| 룰    |  정답 |  탐지 |  정탐 | 과탐 | 미탐 |
| :---- | ----: | ----: | ----: | ---: | ---: |
| L4-01 |   964 |   964 |   964 |    0 |    0 |
| L4-02 |    99 |    99 |    99 |    0 |    0 |
| L4-03 | 4,015 | 4,015 | 4,015 |    0 |    0 |
| L4-04 | 4,091 | 4,091 | 4,091 |    0 |    0 |
| L4-05 | 4,964 | 4,964 | 4,964 |    0 |    0 |
| L4-06 |   692 |   692 |   692 |    0 |    0 |

**A축 결론**: 모든 룰/연도에서 과탐 0, 미탐 0. 룰 계약 정합성 합격.

---

## 검증 축 B — Sidecar 현실 케이스 포착력 (DETECTOR 비참조)

이 축은 **detector 코드를 직접 참조하지 않고** "현장에서 실제로 나올 만한 케이스" 또는 "정상/경계 context"를 sidecar로 만든 뒤 detector가 어떻게 분류하는지 봅니다. L4에서는 특히 sidecar 역할 구분이 중요합니다.

### Sidecar 평가 기준

| 항목                | 의미                                                                                    |
| :------------------ | :-------------------------------------------------------------------------------------- |
| strict_truth_alias  | 공식 truth와 같은 detector contract universe. A축 검증용이며 독립 sidecar 평가셋이 아님 |
| confirmed_subset    | L4가 직접 잡아야 하는 scenario/confirmed subset                                         |
| normal_context      | 합법적이거나 정상에 가까운 context. detector가 잡아도 무조건 과탐으로 보지 않음         |
| boundary_control    | 경계값/해석용 context. 점수 분리와 review 정책을 확인하는 용도                          |
| drilldown_candidate | finding을 설명하기 위한 후보 전표/그룹. strict truth와 평가 단위가 다를 수 있음         |

### Sidecar 역할 요약

| 룰    | 역할                | 파일 수 |   rows |   docs |
| :---- | :------------------ | ------: | -----: | -----: |
| L4-01 | boundary_control    |       2 |    424 |    424 |
| L4-01 | confirmed_subset    |       1 |     22 |     22 |
| L4-01 | strict_truth_alias  |       3 |  2,892 |  2,892 |
| L4-02 | adversarial_holdout |       2 |    187 |      0 |
| L4-02 | boundary_control    |       2 |     84 |      0 |
| L4-02 | contract_manifest   |       1 |  3,267 |      0 |
| L4-02 | drilldown_candidate |       2 | 24,166 | 18,914 |
| L4-02 | normal_context      |       4 |    381 |      0 |
| L4-02 | strict_truth_alias  |       2 |    198 |      0 |
| L4-03 | boundary_control    |       2 |    232 |    232 |
| L4-03 | confirmed_subset    |       1 |     41 |     41 |
| L4-03 | normal_context      |       2 |    354 |    354 |
| L4-03 | strict_truth_alias  |       3 | 12,045 | 12,045 |
| L4-04 | confirmed_subset    |       1 |     52 |     52 |
| L4-04 | contract_manifest   |       1 |    243 |    243 |
| L4-04 | normal_context      |       2 |    516 |    516 |
| L4-04 | strict_truth_alias  |       3 | 12,273 | 12,273 |
| L4-05 | confirmed_subset    |       1 |     27 |     27 |
| L4-05 | strict_truth_alias  |       3 | 14,892 | 14,892 |
| L4-06 | boundary_control    |       2 |    256 |    256 |
| L4-06 | confirmed_subset    |       1 |    175 |    175 |
| L4-06 | normal_context      |       2 |    500 |    500 |
| L4-06 | strict_truth_alias  |       3 |  2,058 |  2,058 |

### Sidecar 주요 결과

| Sidecar                                | 룰    | 역할                | 책임 | 단위          | 실제 잡음 | 점수/검토 | 미포착 |
| :------------------------------------- | :---- | :------------------ | :--- | :------------ | --------: | --------: | -----: |
| revenue_manipulation_l401_direct_truth | L4-01 | confirmed_subset    | 예   | document      |   22 / 22 |        22 |      0 |
| high_amount_confirmed_anomalies        | L4-03 | confirmed_subset    | 예   | document      |   41 / 41 |        41 |      0 |
| rare_account_pair_confirmed_anomalies  | L4-04 | confirmed_subset    | 예   | document      |   46 / 52 |        46 |      6 |
| abnormal_hours_concentration_cases     | L4-05 | confirmed_subset    | 예   | document      |   27 / 27 |        27 |      0 |
| batch_confirmed_anomalies              | L4-06 | confirmed_subset    | 예   | document      | 136 / 175 |       136 |     39 |
| benford_broad_digit_findings           | L4-02 | drilldown_candidate | 별도 | finding_group |   18 / 18 |        18 |      0 |
| benford_drilldown_candidates           | L4-02 | drilldown_candidate | 별도 | finding_group |   99 / 99 |        99 |      0 |
| batch_boundary_controls                | L4-06 | boundary_control    | 별도 | document      |  30 / 128 |        30 |     98 |
| batch_normal_controls                  | L4-06 | normal_context      | 별도 | document      |   0 / 250 |         0 |    250 |
| high_amount_boundary_controls          | L4-03 | boundary_control    | 별도 | document      |   7 / 116 |         7 |    109 |
| high_amount_normal_controls            | L4-03 | normal_context      | 별도 | document      |   7 / 177 |         7 |    170 |
| rare_account_pair_normal_controls      | L4-04 | normal_context      | 별도 | document      | 256 / 258 |       256 |      2 |
| revenue_outlier_boundary_controls      | L4-01 | boundary_control    | 별도 | document      |   9 / 212 |         9 |    203 |

요약 해석:

- L4-01, L4-03, L4-05 confirmed subset은 전부 포착됩니다.
- L4-04 confirmed subset 52건 중 46건이 현재 희소 계정조합 detector에 걸립니다. 6건은 confirmed scenario subset이지만 현재 `rare debit-credit pair` contract에는 들어오지 않습니다.
- L4-06 confirmed subset 175건 중 136건이 현재 batch detector에 걸립니다. 39건은 confirmed batch scenario이지만 현재 detector hard gate인 batch source + amount/simultaneous/period-end 조건에는 걸리지 않습니다.
- normal/boundary context의 detector hit는 무조건 과탐이 아닙니다. v126 정책상 이 파일들은 독립 negative truth가 아니라 점수 해석용 sidecar입니다.
- 특히 L4-04 normal context 258건 중 256건이 detector universe와 겹칩니다. 이는 "합법적 업무 context라도 희소한 계정조합이면 Phase1 review universe에 들어올 수 있다"는 L4-04 정책과 일치합니다.

### 점수 Bucket 분리

L4는 detector 기준을 넓게 유지하고, 운영 점수 bucket으로 우선순위를 나눕니다.

#### L4-03 이상 고액 거래

| 연도 | low_zscore | medium_zscore | high_zscore |  합계 |
| :--- | ---------: | ------------: | ----------: | ----: |
| 2022 |        647 |           445 |         269 | 1,361 |
| 2023 |        581 |           415 |         264 | 1,260 |
| 2024 |        681 |           436 |         277 | 1,394 |
| 합계 |      1,909 |         1,296 |         810 | 4,015 |

점수는 `low_zscore=0.25`, `medium_zscore=0.45`, `high_zscore=0.70`입니다.

#### L4-04 비정상 계정조합

| 연도 | single_rare_pair | large_doc_distinct_pair | multiple_rare_pairs |  합계 |
| :--- | ---------------: | ----------------------: | ------------------: | ----: |
| 2022 |            1,313 |                      90 |                 161 | 1,564 |
| 2023 |              995 |                      77 |                 144 | 1,216 |
| 2024 |            1,072 |                      76 |                 163 | 1,311 |
| 합계 |            3,380 |                     243 |                 468 | 4,091 |

점수는 `single_rare_pair=0.25`, `large_doc_distinct_pair=0.35`, `multiple_rare_pairs=0.45`입니다.

#### L4-05 비정상시간 집중입력

| 연도 | system_context_review | high_context_midnight | rapid_approval |  합계 |
| :--- | --------------------: | --------------------: | -------------: | ----: |
| 2022 |                 1,120 |                   496 |              6 | 1,622 |
| 2023 |                 1,099 |                   528 |              3 | 1,630 |
| 2024 |                 1,154 |                   553 |              5 | 1,712 |
| 합계 |                 3,373 |                 1,577 |             14 | 4,964 |

점수는 `system_context_review=0.25`, `high_context_midnight=0.55`, `rapid_approval=0.65`입니다. 이번 데이터에서는 `sigma_outlier`, `low_volume_midnight` bucket은 0건입니다.

#### L4-06 배치 전표 이상

| 연도 | amount_outlier_only | simultaneous_creation | multi_signal_batch | 합계 |
| :--- | ------------------: | --------------------: | -----------------: | ---: |
| 2022 |                 176 |                    48 |                 10 |  234 |
| 2023 |                 147 |                    56 |                  8 |  211 |
| 2024 |                 194 |                    42 |                 11 |  247 |
| 합계 |                 517 |                   146 |                 29 |  692 |

점수는 `amount_outlier_only=0.25`, `simultaneous_creation=0.45`, `multi_signal_batch=0.65`입니다. 이번 데이터에서 `period_end_concentration` bucket은 0건입니다.

#### L4-02 Benford

| 연도 | finding | drilldown candidate rows | drilldown candidate docs |
| :--- | ------: | -----------------------: | -----------------------: |
| 2022 |      35 |                   11,965 |                    9,051 |
| 2023 |      32 |                   11,874 |                    8,987 |
| 2024 |      32 |                   12,047 |                    9,395 |
| 합계 |      99 |                   35,886 |                   27,433 |

L4-02는 finding 단위가 공식 평가 단위입니다. drilldown candidate docs는 전표-level 검토 후보이지, 공식 truth의 정탐/과탐 단위가 아닙니다.

**B축 결론**: L4 sidecar는 `책임`, `별도 context`, `drilldown` 역할이 분리되어 있습니다. confirmed subset 중 일부 미포착은 현재 detector contract의 hard gate 밖에 있는 scenario coverage이며, A축 공식 truth 미탐으로 보지 않습니다.

---

## 검증 축 C — 악의적 조작 데이터 포착력 (`manipulated_entry_truth.csv`)

`manipulated_entry_truth.csv`는 **fraud 시나리오를 의도적으로 합성한 전체 조작 전표 표본**입니다. L4 특정 룰의 정답이 아니므로 L4가 전부 잡아야 하는 대상은 아닙니다. 다만 L4가 고액, Benford, 희소 계정조합, 비정상시간 집중, 배치 이상 같은 분석 신호를 통해 어느 정도 보강 포착하는지 확인합니다.

### 전체 요약

| 항목                | 건수 |
| :------------------ | ---: |
| 전체 조작 전표      |  420 |
| L4가 실제 잡은 전표 |   32 |
| L4 미포착 전표      |  388 |

해석:

- L4는 조작 전표 전체를 주 책임으로 잡는 레이어가 아닙니다.
- L4가 잡은 32건은 통계/행동/Benford drilldown 관점에서 보강 포착된 전표입니다.
- 대부분 조작 전표는 L1/L2/L3의 승인, 직무분리, 수기/기말/관계사/업무범위 책임 영역에서 포착되는 구조입니다.

### 조작 시나리오별 결과

| 시나리오                           | 전체 | L4 실제 잡음 | L4 미포착 |
| :--------------------------------- | ---: | -----------: | --------: |
| approval_sod_bypass                |   29 |            2 |        27 |
| circular_related_party_transaction |   34 |            3 |        31 |
| embezzlement_concealment           |   76 |           15 |        61 |
| fictitious_entry                   |  168 |            7 |       161 |
| period_end_adjustment_manipulation |   92 |            5 |        87 |
| unusual_timing_manipulation        |   21 |            0 |        21 |

해석:

- `embezzlement_concealment`에서 L4 포착이 가장 많습니다. Benford drilldown과 일부 고액/희소 조합 신호가 같이 걸립니다.
- `fictitious_entry`, `period_end_adjustment_manipulation`은 주로 L3 수기/기말/업무범위와 결합해서 봐야 하며, L4는 일부 고액/Benford 보강 신호만 제공합니다.
- `approval_sod_bypass`는 L1 승인/직무분리 책임 영역입니다. L4가 적게 잡는 것이 정상입니다.
- `unusual_timing_manipulation` 21건은 L3/L1 시점 신호 책임에 가깝고, 이번 L4-05 사용자 집중 detector에는 걸리지 않았습니다. L4-05는 단건 비업무시간이 아니라 사용자별 집중 행동을 보는 룰입니다.

### L4 룰별 조작 전표 포착

| 룰    | 실제 잡음 | 해석                                                            |
| :---- | --------: | :-------------------------------------------------------------- |
| L4-01 |         0 | 조작 전표 중 매출 계정 고액 z-score anchor에 해당하는 건 없음   |
| L4-02 |        21 | Benford finding의 drilldown 후보 전표로 포착                    |
| L4-03 |         4 | 고액 z-score + 금액 분위수 guard에 해당                         |
| L4-04 |         2 | 희소 차변-대변 계정조합에 해당                                  |
| L4-05 |         5 | 비정상시간 사용자 집중 행동 universe에 해당                     |
| L4-06 |         0 | 배치 source + batch anomaly hard gate에 해당하는 조작 전표 없음 |

조작 전표가 여러 L4 룰에 동시에 걸릴 수 있으므로 룰별 합계는 전체 포착 32건과 다를 수 있습니다.

**C축 결론**: L4는 조작 전표 420건 중 32건을 보강 포착합니다. 낮은 포착률은 실패가 아니라 L4의 책임 범위가 통계/행동 분석 신호로 제한되기 때문입니다. 조작 전표의 주 포착은 L1/L2/L3가 담당하고, L4는 고액/Benford/희소 조합/행동 집중이 결합된 케이스의 우선순위를 올립니다.

---

## Phase1 전체 점수 투입 관련

L4는 Phase1 전체 점수에서 `RULE_LEVEL_WEIGHTS["L4"] = 0.15`로 들어갑니다.

| 구성            | L4 weight |
| :-------------- | --------: |
| 기본 L1-L4      |      0.15 |
| ML 포함         |      0.10 |
| trendbreak 포함 |      0.13 |

L4 내부 점수는 단순 합산하지 않고 family-level 최대 normalized score로 집계됩니다. 따라서 L4 detector universe가 넓어도 L4 단독으로 전체 위험등급을 과하게 끌어올리지 않고, 다른 레이어 신호와 결합될 때 우선순위를 높입니다.

---

## 결론

| #   | 결론                                                                                                                                                              |
| :-- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **A축(룰 계약)**: v126 기준 L4 공식 정답은 모든 룰/연도에서 정탐 100%, 과탐 0, 미탐 0입니다.                                                                      |
| 2   | **B축(Sidecar 현실성)**: L4 sidecar는 strict truth, confirmed subset, normal/boundary context, drilldown candidate가 분리되어 있습니다. 정상/경계 context의 detector hit를 곧바로 과탐으로 해석하면 안 됩니다. |
| 3   | **C축(악의적 조작)**: 조작 전표 420건 중 L4가 32건을 보강 포착했습니다. L4 미포착 388건은 대부분 L1/L2/L3 책임 영역입니다.                                        |
| 4   | L4-02는 finding 단위가 공식 평가 단위이고, drilldown candidate 전표는 검토 후보입니다. 문서 단위 과탐/미탐 표와 섞으면 안 됩니다.                                 |
| 5   | L4-03/L4-04/L4-05/L4-06은 detector를 넓게 유지하되 점수 bucket으로 운영 우선순위를 분리합니다.                                                                    |
| 6   | L4는 Phase1에서 분석/보조 신호입니다. 단독 결론보다 다른 책임 신호와 결합해 review 우선순위를 올리는 역할로 보는 것이 맞습니다.                                   |
