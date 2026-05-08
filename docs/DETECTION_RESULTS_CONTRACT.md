# Phase1 Detection 결과 - datasynth_contract

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
## 요약

이 문서는 `data/journal/primary/datasynth_contract/` 데이터셋을 Phase1로 실행한 결과를 정리한다.

이 데이터셋은 **부정전표를 잡아내는 성능 평가용이 아니다**. 룰이 정의된 약속대로 동작하는지(데이터 정합성 / 룰 약속 / sidecar·review 신호 처리)를 확인하기 위한 fixture 데이터셋이다.

### 입력 데이터

| 항목            | 값          |
| --------------- | ----------: |
| 원장 row        | 1,109,435   |
| document        |   319,193   |
| label 누수 컬럼 | 제거됨      |
| label 파일 수   |     1,442   |

### Phase1 출력

| 항목           | 값          |
| -------------- | ----------: |
| 전체 소요 시간 |   517.851초 |
| 생성된 case 수 |      20,753 |
| High row       |      12,828 |
| Medium row     |     161,821 |
| Low row        |       2,297 |
| Normal row     |     932,489 |

### 산출 파일

- checkpoint: `artifacts/phase1_contract_profile.json`
- case input cache: `artifacts/phase1_contract_case_input.pkl`
- case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260503T035532Z.json`
- truth family 평가: `artifacts/contract_truth_family_eval.csv`
- 룰별 평가: `artifacts/contract_truth_rule_eval.csv`
- Top case truth mix: `artifacts/contract_top_case_truth_mix.csv`

## 실행 시간 분포

| 단계                | 소요 시간     |
| ------------------- | ------------: |
| CSV load            |       9.340초 |
| feature.time        |       1.816초 |
| feature.amount      |      40.355초 |
| feature.pattern     |       5.225초 |
| feature.text        |      10.517초 |
| detector.layer_a    |      17.108초 |
| detector.layer_b    |     107.235초 |
| detector.layer_c    |     163.589초 |
| detector.benford    |       6.248초 |
| aggregate           |      30.463초 |
| Phase1 case builder |      96.360초 |
| **합계**            | **517.851초** |

병목은 `layer_c → layer_b → case builder → feature.amount` 순서다.

## A. 데이터 정합성 룰이 약속대로 동작했는지

데이터 정합성 계열은 contract 데이터셋에서 **반드시 가장 먼저 잡혀야 하는** 영역이다.

결과 요약

- 점수 부여(score)와 같은 룰의 flag(same-rule flag)는 **모든 truth 문서에 100% 부여**됐다.
- 다만 일부는 case 목록까지 올라가지 않았다. 이는 **detector가 못 잡은 게 아니라**, `risk_level=Normal` 또는 검토(review) 성격이라 case builder가 시드(시작 후보)로 잡지 않았기 때문이다.

| contract subclass                          | truth | score | flag | case | Top100 | 표시 queue          |
| ------------------------------------------ | ----: | ----: | ---: | ---: | -----: | ------------------- |
| data_integrity_exception                   |   688 |   688 |  688 |  588 |    501 | 데이터 정합성       |
| hard_period_mapping_error                  |   227 |   227 |  227 |  227 |    219 | 데이터 정합성       |
| hard_data_quality_or_interface_error       |    71 |    71 |   71 |   33 |     21 | 데이터 정합성       |
| hard_data_quality_or_posting_error         |    13 |    13 |   13 |   13 |      6 | 데이터 정합성       |
| possible_period_cutoff_or_late_close       |   202 |   202 |  202 |  202 |    180 | 데이터 정합성       |
| reviewable_data_quality_gap                |    34 |    34 |   34 |   11 |      5 | 데이터 정합성/시점  |

해석

- `L1-01 / L1-02 / L1-03 / L1-08` 계열의 **탐지 자체는 약속대로 동작**한다.
- `hard_period_mapping_error`, `possible_period_cutoff_or_late_close`는 case 목록에서도 거의 그대로 보인다.
- `data_integrity_exception` 688건은 전부 점수화됐지만 case는 588건만 올라왔다(나머지 100건은 Normal로 남음).
- `reviewable_data_quality_gap`은 34건 중 11건만 case로 올라왔다. 이름 그대로 **검토 후보(reviewable)**라 우선순위를 낮게 둔다.

**A축 결론**: 룰의 탐지 약속은 통과. case 목록 승격 정책은 hard error와 reviewable gap을 분리해서 봐야 한다.

## B. 정답군 분류별 결과

`contract_rule_truth_taxonomy.csv` 기준으로 정답은 성격별로 나뉘어 있다. **모든 truth가 같은 의미의 "위험 전표"가 아니라는 점**이 핵심이다.

| 정답군                       |   truth |   score |    case | 해석                                              |
| ---------------------------- | ------: | ------: | ------: | ------------------------------------------------- |
| data_integrity_contract      |   1,235 |   1,235 |   1,074 | 정합성 오류. 대부분 case 상단에 올라옴            |
| control_contract             |     462 |     446 |     326 | 승인/통제 약속. hard exception은 잘 올라옴        |
| timing_cutoff_contract       |   2,076 |   2,075 |     992 | cutoff 계열. 강한 cutoff만 case로 올라옴          |
| transaction_pattern_contract |   2,101 |   2,032 |     676 | 거래 패턴 검토 후보. 점수는 다 있으나 선별 승격   |
| high_review_contract         |  16,498 |  16,498 |   7,304 | 넓은 검토 후보. 전부 올리면 과탐                  |
| broad_population_contract    | 184,889 | 178,760 |  58,836 | detector 모집단. 전체를 case로 올리는 대상 아님   |
| unclassified_contract        |     428 |     428 |     102 | 보조 검토 성격                                    |
| macro_analytical_contract    |       - |       - |       - | 문서 단위 없음. D01/D02 그룹 finding으로 별도 평가|

### 잘 끌어올려진 영역

| 정답군 / 룰                            | 근거                                       |
| -------------------------------------- | ------------------------------------------ |
| hard_period_mapping_error              | 227/227 점수, 227/227 case, Top100에 219개 |
| possible_period_cutoff_or_late_close   | 202/202 점수, 202/202 case, Top100에 180개 |
| hard_data_quality_or_posting_error     | 13/13 점수, 13/13 case                     |
| L1-08                                  | 731/731 점수, 731/731 case                 |
| L1-03                                  | 32/32 점수, 32/32 case                     |
| L1-06                                  | 19/19 점수, 19/19 case                     |

### 의도적으로 case 목록에서 낮게 남겨둔 영역

검토 후보 / 정책 확인 대상 / 넓은 검토 모집단은 case 우선순위를 일부러 낮춘다. 전부 case로 올리면 감사자가 봐야 할 양이 비현실적으로 커지기 때문이다.

| 정답군 / 룰                                | 관찰                                              | 이유                                          |
| ------------------------------------------ | ------------------------------------------------- | --------------------------------------------- |
| possible_system_exception_but_needs_policy | 8건 중 5건 점수, case 0건                         | 정책 확인 전까지 case에 안 올림               |
| realistic_but_must_review                  | 1,019건 점수, case 186건                          | 업무상 가능한 cutoff. 전수 case는 과탐        |
| cutoff_review_needed                       | 20건 중 18건 점수, case 4건                       | 검토 후보로만 남김                            |
| broad_review_population                    | 184,889건 중 178,760건 점수, case 58,836건        | detector 모집단. 전수 case는 부적절           |
| L2-01                                      | 457건 중 392건 점수, flag 111건, case 99건        | 임계값 근접 후보는 일부만 직접 flag           |
| L3-05                                      | 24,318건 점수, case 4,650건                       | 수기/민감계정 모집단이 넓음                   |
| L3-09                                      | 1,091건 점수, case 207건                          | 업무로직/계정사용 검토 후보가 넓음            |

이는 "못 잡았다"가 아니라, contract taxonomy가 **hard exception / 검토 필요 / 넓은 검토 모집단 / 정책 확인 대상**을 분리한 결과다.

## Top 10 case 표시 순서

Phase1 case 목록 상단은 데이터 정합성 case가 차지한다. contract 데이터셋에서는 이게 정상이다(강한 정합성/계약 fixture가 의도적으로 들어간 데이터셋이기 때문).

| rank | case_id                           | queue         | band | docs | truth | 주요 truth mix                  |
| ---: | --------------------------------- | ------------- | ---- | ---: | ----: | ------------------------------- |
|    1 | case_data_integrity_failure_00004 | 데이터 정합성 | high |  103 |   103 | broad/integrity/high-review 혼합 |
|    2 | case_data_integrity_failure_00007 | 데이터 정합성 | high |   86 |    86 | broad/integrity/high-review 혼합 |
|    3 | case_data_integrity_failure_00005 | 데이터 정합성 | high |   96 |    96 | broad/integrity/high-review 혼합 |
|    4 | case_data_integrity_failure_00001 | 데이터 정합성 | high |   92 |    92 | broad/integrity/high-review 혼합 |
|    5 | case_data_integrity_failure_00011 | 데이터 정합성 | high |  107 |   107 | high-review/integrity 혼합       |
|    6 | case_data_integrity_failure_00010 | 데이터 정합성 | high |   45 |    45 | broad/integrity 혼합             |
|    7 | case_data_integrity_failure_00002 | 데이터 정합성 | high |   67 |    67 | broad/integrity 혼합             |
|    8 | case_data_integrity_failure_00003 | 데이터 정합성 | high |   51 |    51 | broad/integrity 혼합             |
|    9 | case_data_integrity_failure_00012 | 데이터 정합성 | high |   54 |    54 | broad/integrity 혼합             |
|   10 | case_data_integrity_failure_00014 | 데이터 정합성 | high |   64 |    64 | broad/integrity 혼합             |

Top 10이 데이터 정합성으로 채워지는 것은 contract 평가 맥락에서 맞는 동작이다. **이 결과를 실제 부정전표 탐지 성능으로 해석하면 안 된다.**

## 룰별 주요 결과

| rule  |  truth | score % |   flag | review | case % | 해석                                        |
| ----- | -----: | ------: | -----: | -----: | -----: | ------------------------------------------- |
| L1-08 |    731 |  100.0% |    731 |      0 | 100.0% | 기간/정합성 핵심 통과                       |
| L1-01 |    316 |  100.0% |    316 |      0 |  77.5% | 차대변/정합성 통과. 일부 Normal은 case 미승격|
| L1-02 |    156 |  100.0% |    156 |      0 |  42.3% | 인터페이스 gap은 점수화, case는 선별         |
| L1-03 |     32 |  100.0% |     32 |      0 | 100.0% | 무효 계정 통과                              |
| L1-05 |    244 |   95.1% |    116 |    101 |  88.9% | 시스템 예외를 직접점수와 review로 분리       |
| L1-07 |     96 |  100.0% |     17 |     79 |  54.2% | skipped approval은 review 비중 큼            |
| L1-09 |    122 |  100.0% |     12 |    110 |  53.3% | 승인일/증적 gap은 review 비중 큼             |
| L2-01 |    457 |   85.8% |    111 |      0 |  21.7% | 임계값 근접 후보는 일부만 직접 flag          |
| L2-02 |    384 |  100.0% |    384 |      0 |  44.3% | 중복/분할은 점수화, case는 선별              |
| L2-03 |    111 |  100.0% |     15 |      0 |  64.0% | duplicate 구조 일부만 직접 flag              |
| L3-02 | 86,808 |  100.0% | 75,810 | 11,061 |  60.9% | 수기/통제우회 모집단이 넓음                  |
| L4-01 |    964 |  100.0% |    964 |      0 |  93.3% | 고액/통계 outlier 양호                       |

## Sidecar / review-only 신호 처리

sidecar 분류는 `contract_truth`, `sidecar_context`, `manifest_log`로 나뉜다. 검증 포인트는 **sidecar가 본 위험점수를 오염시키지 않으면서, 필요할 때만 case 맥락(context)으로 붙는지**다.

이번 실행에서 `L3-12`는 다음과 같이 처리됐다.

| 항목                          | 값      |
| ----------------------------- | ------: |
| L3-12 candidate label 수      | 175,924 |
| seed 후보 (case 신규 생성)    |       0 |
| context 후보 (기존 case 보강) | 175,924 |
| context evidence 추가 수      | 175,924 |

→ `L3-12`는 case를 **새로 만들지 않고**, 이미 시드가 있는 case에 **context 증거로만 붙는다**. "검토용 신호가 case를 대량 생성하는 문제"가 contract 실행에서도 막혀 있다는 뜻이다.

## 결론

`datasynth_contract` 기준 Phase1은 **계약 검증 데이터셋으로는 정상 동작한다**.

**잘 동작한 부분**

- 데이터 정합성 hard error는 전부 점수화됐다.
- 핵심 L1 정합성 룰은 same-rule flag 기준 100% 부여.
- Top case 목록은 데이터 정합성/계약 오류가 먼저 차지한다.
- 넓은 검토 모집단과 현실적 검토 후보는 일부만 case로 올라간다(과탐 방지 의도).
- L3-12 같은 review-only 신호는 case를 새로 만들지 않고 context로만 붙는다.

**추가 정책 결정이 필요한 부분**

- `possible_system_exception_but_needs_policy`: case 0건. 정책 검토용 별도 보조 queue가 필요하면 분리 신설 검토.
- `realistic_but_must_review`, `cutoff_review_needed`, `broad_review_population`: 점수는 있으나 case 승격률 낮음. 본 case에 다 올리면 감사 부담 증가.
- `L2-01`: truth 457개 중 case 99개로 보수적. 임계값 근접 후보 특성상 의도된 결과.

**해석 주의**

이 결과는 **악의적 조작 탐지 성능 평가가 아니라** contract/integrity 동작 검증 결과다. 실제 부정전표 탐지 성능은 별도 평가 데이터셋으로 측정해야 한다.
