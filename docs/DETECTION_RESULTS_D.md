# Detection Results

## Phase 1 D - DataSynth v126

대상 데이터는 `data/journal/primary/datasynth_v126_candidate`입니다.

이 문서는 D01/D02 결과를 **세 가지 독립적인 검증 축**으로 나누어 봅니다. 세 축은 측정하는 대상이 다르므로 같은 표에 섞으면 의미를 잃습니다.

| 축  | 무엇을 검증하는가                                                   | 검증 데이터                                                                                                       | 합격 기준                                |
| :-- | :------------------------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------- | :--------------------------------------- |
| A   | 데이터 정합성 / 룰 계약사항이 문서대로 동작하는가                   | `labels/rule_truth_D01.csv`, `labels/rule_truth_D02.csv`, macro truth sidecar                                     | confirmed truth 기준 **미탐 0건**        |
| B   | DETECTOR를 직접 참조하지 않고 "실제로 있을법한" 케이스를 잡아내는가 | sidecar 파일 (`account_activity_variance_*`, `monthly_pattern_shift_*` 등 detector 코드를 보지 않은 macro 모집단) | 책임/점수/검토/미포착 분리 타당성        |
| C   | Phase1 운영 흐름에서 D01/D02 macro hit을 책임 영역 안에서 잡아내는가 | `macro_priority_score`, `queue_bucket`, `normal_likelihood`, `macro_contexts`                                     | D 책임분량을 점수 또는 review 신호로 포착 |

세 축의 관계:

- A축은 detector 사양과 데이터 생성기가 같은 정의를 공유하는지 보는 **계약 검증**입니다. D01/D02는 PHASE1 recall-first contract이므로 confirmed truth 기준 미탐 0건이 합격선입니다.
- B축은 **detector 로직을 모르는 입장**에서 "현장에서 실제로 나올 만한 형태"를 sidecar로 만든 뒤 detector가 어떻게 반응하는지 봅니다. D 계열은 macro review signal이므로 "위험점수 직접 반영 vs review/normal context 분리"가 핵심입니다.
- C축은 **D01/D02 macro hit이 곧 위험 alert가 아니라는 점**을 봅니다. detector는 macro 이상 후보를 먼저 넓게 잡고 `macro_priority_score`/`queue_bucket`/`normal_likelihood`로 우선순위를 나눕니다.

D01/D02는 Phase1 전체 점수에서 **transaction row 확정 점수 단독 결론 신호가 아니라 macro review signal**입니다. 계정/월/법인 단위 macro 이상을 먼저 넓게 포착한 뒤, transaction case의 priority 보강과 `macro_contexts` 첨부에 활용됩니다. raw flag 자체가 아니라 점수 체계와 함께 노출하는 조건에서만 실무 사용 가능성이 성립합니다.

실행 정보:

| 항목         | 값                                                                          |
| :----------- | :-------------------------------------------------------------------------- |
| 범위         | 2022, 2023, 2024 / D01 ~ D02                                                |
| 기준 데이터  | `data/journal/primary/datasynth_v126_candidate`                             |
| Freeze 문서  | `data/journal/primary/datasynth_v126_candidate/FREEZE_V126_CANDIDATE.md`    |
| Sidecar 목록 | `data/journal/primary/datasynth_v126_candidate/labels/sidecar_manifest.csv` |

## 요약

- **A축 결과**: D01 confirmed truth 336건, D02 confirmed truth 346건 모두 **미탐 0건**. PHASE1 recall-first contract 합격. 단순 review universe 기준 과탐처럼 보이는 D01 504건, D02 151건은 정상/검토 macro context이며 확정 과탐으로 보지 않습니다.
- **B축 결과**: D01/D02 sidecar 기준 confirmed truth, normal-review context, stable/near/guardrail controls, exclusions 역할이 분리됨. 과탐·미탐 없이 점수/검토 분기 정합.
- **C축 결과**: D01/D02 macro hit은 Phase1에서 직접 alert가 아니라 `macro_priority_score`, `queue_bucket`, `normal_likelihood`, `macro_contexts`로 분리됨. D01 504건, D02 151건의 정상/검토 context는 낮은 priority 또는 review-only로 유입.

세 축을 분리하는 이유:

- A축이 깨끗해도 sidecar처럼 detector 코드를 보지 않은 모집단에서 분류가 어긋나면 현장에서 과탐이 터집니다.
- B축이 깨끗해도 Phase1 운영 흐름에서 raw positive가 그대로 확정 alert로 흘러가면 macro rule의 목적과 달라집니다.
- 세 축이 모두 통과해야 D01/D02가 macro review 신호로 의도대로 동작한다고 말할 수 있습니다.

또 "D01/D02가 잡았다"와 "최종 위험점수에 강하게 반영한다"는 다릅니다. D 계열은 Phase1 원칙상 후보는 넓게 잡지만, 실제 운영에서는 confirmed/corroborated macro context만 priority를 보강하고 정상 가능성이 높은 context는 review/normal로 분리합니다.

---

## 검증 축 A — 데이터 정합성 / 룰 계약사항 (공식 truth, 미탐과탐 0건 검증)

`rule_truth_D*.csv`와 macro truth sidecar는 detector 사양에 맞추어 DataSynth가 의도적으로 만든 정답입니다. detector가 사양대로 동작한다면 **confirmed truth 정탐 100%, 미탐 0**이 나와야 합니다. 이 축은 룰 코드와 데이터 생성기 사이의 계약이 어긋나지 않는지 검증합니다.

다만 D01/D02의 review universe는 정상/검토 macro context를 의도적으로 포함합니다. 따라서 아래 표의 `과탐`은 L3의 확정 과탐과 같은 의미가 아니라, B축에서 review/normal context로 분리되어야 하는 raw-positive context입니다.

### 룰 의미 매핑

| 룰  | 의미             |
| :-- | :--------------- |
| D01 | 계정 활동 변동률 |
| D02 | 월별 패턴 shift  |

### 2022

| 룰  | 정답 | 탐지 | 정탐 | 과탐 | 미탐 |
| :-- | ---: | ---: | ---: | ---: | ---: |
| D01 |    0 |    0 |    0 |    0 |    0 |
| D02 |    0 |    0 |    0 |    0 |    0 |

### 2023

| 룰  | 정답 | 탐지 | 정탐 | 과탐 | 미탐 |
| :-- | ---: | ---: | ---: | ---: | ---: |
| D01 |  145 |  392 |  145 |  247 |    0 |
| D02 |  170 |  262 |  170 |   92 |    0 |

### 2024

| 룰  | 정답 | 탐지 | 정탐 | 과탐 | 미탐 |
| :-- | ---: | ---: | ---: | ---: | ---: |
| D01 |  191 |  448 |  191 |  257 |    0 |
| D02 |  176 |  235 |  176 |   59 |    0 |

### 3년 합계

| 룰  | 정답 | 탐지 | 정탐 | 과탐 | 미탐 |
| :-- | ---: | ---: | ---: | ---: | ---: |
| D01 |  336 |  840 |  336 |  504 |    0 |
| D02 |  346 |  497 |  346 |  151 |    0 |

**A축 결론**: 모든 룰·연도에서 confirmed truth 기준 미탐 0. 룰 계약 정합성 합격. 단, D01/D02의 `과탐` 열은 확정 false positive가 아니라 정상/검토 macro context이며 B축에서 분리합니다.

---

## 검증 축 B — Sidecar 현실 케이스 포착력 (DETECTOR 비참조)

이 축은 **detector 코드를 직접 참조하지 않고** "현장에서 실제로 나올 만한 케이스"를 sidecar로 만들어 둔 뒤 detector가 그것을 어떻게 분기하는지 봅니다. D01/D02는 Phase1 전체 점수에서 macro 보조/검토 신호이므로 B축의 핵심은 "잡힌 결과를 위험점수에 직접 넣을지 review-only 또는 normal context로 뺄지"의 분기가 detector 동작과 정합한지입니다.

### Sidecar 평가 기준

| 항목    | 의미                                                                      |
| :------ | :------------------------------------------------------------------------ |
| 책임    | 해당 sidecar가 D01/D02가 직접 잡아야 하는 대상인지 여부 (예/아니오/별도)  |
| 문서    | sidecar의 문서/평가 단위 수. D01/D02는 법인-연도-계정 단위                |
| 잡음    | D01/D02 macro detector가 실제로 포착한 단위 수                            |
| 점수    | confirmed/corroborated macro context로 priority 보강해야 하는 단위 수     |
| 검토    | 잡혔지만 위험점수에서 약하게 반영하거나 후보/정상 context로 보여줄 단위 수 |
| 미포착  | 해당 D 룰이 잡지 않은 단위 수                                             |

D 책임 값의 의미:

| 값     | 의미                                                                                   |
| :----- | :------------------------------------------------------------------------------------- |
| 예     | D01/D02가 직접 잡아야 하는 confirmed truth. 잡으면 priority 보강 또는 검토 점수에 반영 |
| 아니오 | D01/D02 책임 영역이 아님. 잡지 않는 것이 정상                                          |
| 별도   | 형식상 잡히지만 확정 위험으로 보지 않고 검토/정상/제외 context로 분리                  |

### Sidecar 전체 요약

D01/D02 sidecar는 detector 코드를 보지 않고 "계정 활동 변동이 크거나 월별 패턴이 달라 보이는 계정-year"를 모은 macro 모집단입니다. detector가 이 중 무엇을 confirmed truth로 보고 무엇을 정상/검토 context로 빼는지가 B축 검증 포인트입니다. 단위는 법인-연도-계정 macro evaluation unit입니다.

| Sidecar                                                | 룰  | 책임   |  문서 |  잡음 | 점수 | 검토 | 미포착 |
| :----------------------------------------------------- | :-- | :----- | ----: | ----: | ---: | ---: | -----: |
| account_activity_variance_truth.csv                    | D01 | 예     |   336 |   336 |  336 |    0 |      0 |
| account_activity_variance_normal_controls.csv          | D01 | 별도   |   504 |   504 |    0 |  504 |      0 |
| account_activity_variance_stable_controls.csv          | D01 | 아니오 |   240 |     0 |    0 |    0 |      0 |
| account_activity_variance_near_threshold_controls.csv  | D01 | 아니오 |   120 |     0 |    0 |    0 |      0 |
| account_activity_variance_exclusions.csv               | D01 | 아니오 |    10 |     0 |    0 |    0 |      0 |
| monthly_pattern_shift_confirmed_anomalies.csv          | D02 | 예     |   346 |   346 |  346 |    0 |      0 |
| monthly_pattern_shift_raw_positive_normal_contexts.csv | D02 | 별도   |   151 |   151 |    0 |  151 |      0 |
| monthly_pattern_shift_guardrail_negative_controls.csv  | D02 | 아니오 |    43 |     0 |    0 |    0 |      0 |
| monthly_pattern_shift_exclusions.csv                   | D02 | 아니오 | 1,982 |     0 |    0 |    0 |      0 |

요약 해석:

| 책임 구분 | 파일 수 |  문서 | 잡음 | 점수 | 검토 | 미포착 |
| :-------- | ------: | ----: | ---: | ---: | ---: | -----: |
| 예        |       2 |   682 |  682 |  682 |    0 |      0 |
| 별도      |       2 |   655 |  655 |    0 |  655 |      0 |
| 아니오    |       5 | 2,395 |    0 |    0 |    0 |      0 |

D01의 검토 504건은 정상 가격 인상, 대량 운영, capex/working capital timing, auxiliary context 같은 raw-positive macro context입니다. D02의 검토 151건은 recurring/interface batch, seasonal timing, quarter/year-end concentration 같은 raw-positive normal context입니다. 두 분기 모두 detector 비참조 sidecar 기준으로 점수/검토 분류가 일치합니다.

### Sidecar 기준 결과 (룰별 상세)

#### D01 계정 활동 변동률

계정 활동 변동률이 큰 법인-연도-계정입니다. confirmed truth는 D01이 잡아야 하고, 정상 가격 인상/대량 운영/투자성 이벤트/working capital timing은 raw positive로 잡히더라도 확정 위험이 아니라 검토 또는 정상 context로 분리합니다.

| Sidecar                                               | 책임   | 문서 | 잡음 | 점수 | 검토 | 미포착 | 해석                                              |
| :---------------------------------------------------- | :----- | ---: | ---: | ---: | ---: | -----: | :------------------------------------------------ |
| account_activity_variance_truth.csv                   | 예     |  336 |  336 |  336 |    0 |      0 | 공식 정답 전부 탐지                               |
| account_activity_variance_normal_controls.csv         | 별도   |  504 |  504 |    0 |  504 |      0 | raw positive 전부 탐지, 정상/검토 context로 분리  |
| account_activity_variance_stable_controls.csv         | 아니오 |  240 |    0 |    0 |    0 |      0 | 안정 control은 confirmed truth와 분리             |
| account_activity_variance_near_threshold_controls.csv | 아니오 |  120 |    0 |    0 |    0 |      0 | 경계 control은 confirmed truth와 분리             |
| account_activity_variance_exclusions.csv              | 아니오 |   10 |    0 |    0 |    0 |      0 | blank GL account 등 평가 제외                     |

#### D02 월별 패턴 shift

월별 분포가 전년 대비 크게 바뀐 법인-연도-계정입니다. confirmed monthly pattern shift는 D02가 잡아야 하고, recurring/interface batch나 계절성·분기말·연말 집중은 raw positive로 잡히더라도 normal context로 분리합니다.

| Sidecar                                                | 책임   |  문서 | 잡음 | 점수 | 검토 | 미포착 | 해석                                          |
| :----------------------------------------------------- | :----- | ----: | ---: | ---: | ---: | -----: | :-------------------------------------------- |
| monthly_pattern_shift_confirmed_anomalies.csv          | 예     |   346 |  346 |  346 |    0 |      0 | 공식 정답 전부 탐지                           |
| monthly_pattern_shift_raw_positive_normal_contexts.csv | 별도   |   151 |  151 |    0 |  151 |      0 | raw positive 전부 탐지, 정상 context로 분리   |
| monthly_pattern_shift_guardrail_negative_controls.csv  | 아니오 |    43 |    0 |    0 |    0 |      0 | guardrail negative는 confirmed truth와 분리   |
| monthly_pattern_shift_exclusions.csv                   | 아니오 | 1,982 |    0 |    0 |    0 |      0 | 소표본·small delta·blank GL 등 평가 제외      |

**B축 결론**: detector 비참조 sidecar 기준으로도 점수/검토 분기가 detector 동작과 일치. D01 raw-positive 840건 중 336건은 점수, 504건은 검토/정상 context로 분리되고, D02 raw-positive 497건 중 346건은 점수, 151건은 검토/정상 context로 분리됨.

### Phase1 전체 점수 유입 관점

D01/D02는 Phase1 전체 결과에서 transaction row 점수와 다르게 들어갑니다. macro finding은 그대로 확정 alert가 아니라, 같은 법인/계정/연도 transaction case에 `macro_contexts`로 붙고 priority를 제한적으로 보강합니다.

v126은 D01/D02 macro sidecar semantics를 `labels/` 아래에 유지한 후보이며, D01/D02 journal row와 rule truth membership은 바꾸지 않았습니다. 따라서 D01/D02 종합 점수의 동작은 다음과 같습니다.

| 항목                                  | D01 | D02 |
| :------------------------------------ | --: | --: |
| confirmed macro truth                 | 336 | 346 |
| raw-positive normal/review context    | 504 | 151 |
| confirmed truth 미탐                  |   0 |   0 |
| 확정 alert로 보내면 안 되는 context   | 504 | 151 |

상위 priority driver는 confirmed/corroborated macro context입니다. 반대로 normal/auxiliary/analytical context는 설명력은 제공하지만 단독 high-risk 확정 근거로 쓰지 않습니다.

대표 상위 조합:

| 조합                                  | 해석                                                        |
| :------------------------------------ | :---------------------------------------------------------- |
| D01 confirmed + transaction anomaly   | 계정 활동 변동과 전표 이상이 같은 법인/계정/연도에서 결합   |
| D02 confirmed + period-end transaction | 월별 패턴 shift와 기말/월말 전표 집중이 결합               |
| D01 review + D02 confirmed            | 계정 활동 변동은 정상 가능성이 있으나 월별 패턴 shift는 confirmed |
| D01 normal + D02 normal               | raw positive지만 정상/검토 macro context로 낮은 priority 유지 |

---

## 검증 축 C — Phase1 운영 흐름 포착력 (`macro_priority_score`, `queue_bucket`, `macro_contexts`)

D01/D02에는 L3의 `manipulated_entry_truth.csv`와 같은 transaction-level 조작 전표 C축 파일을 그대로 적용하지 않습니다. D 계열은 계정/월/법인 단위 macro review signal이므로, C축은 실제 운영에서 macro hit이 D 책임 영역 안에서 점수 또는 review 신호로 흘러가는지를 봅니다.

따라서 C축은 A축/B축과 보는 기준이 다릅니다.

| 축   | 기준 파일/필드                                                | 평가 질문                                            | 숫자의 의미                                  |
| :--- | :------------------------------------------------------------ | :--------------------------------------------------- | :------------------------------------------- |
| A축  | `rule_truth_D*.csv`, macro truth sidecar                      | 각 D 룰 계약을 정확히 맞추는가                       | 룰별 정답/탐지/과탐/미탐                     |
| B축  | D sidecar population                                          | 현실적인 후보를 점수/검토로 잘 분리하는가            | 후보 모집단의 점수/검토 분기                 |
| C축  | `macro_priority_score`, `queue_bucket`, `macro_contexts`      | macro hit이 Phase1 운영 흐름에서 확정/검토/정상으로 분리되는가 | macro context가 transaction case에 붙는 방식 |

C축의 `D 책임`, `실제 잡음`, `책임 밖`은 서로 더해서 전체가 되는 값이 아닙니다. 한 transaction case가 D01 confirmed context와 D02 review context를 동시에 받을 수 있으므로, 직접점수와 review는 서로 겹칠 수 있습니다.

D01/D02가 모든 raw-positive macro context를 확정 위험점수로 잡아야 하는 것은 아닙니다. 다만 D 계열은 계정 활동 변동, 월별 패턴 shift 같은 macro 이상 후보를 넓게 포착해야 하므로, C축에서는 "macro hit이 Phase1 후보·점수·review 신호에 어떻게 들어가는지"를 봅니다.

### 전체 요약

| 항목                          | 건수 | 의미                                                |
| :---------------------------- | ---: | :-------------------------------------------------- |
| 전체 D confirmed macro truth  |  682 | D01 336건 + D02 346건                               |
| D 책임                        |  682 | D01/D02가 confirmed macro로 책임져야 하는 수        |
| 실제 잡음                     |  682 | confirmed truth 기준 전부 포착                      |
| 미포착                        |    0 | D 책임인데 잡지 못한 confirmed macro truth 없음     |
| 책임 밖                       |  655 | 확정 D 책임은 아니지만 review/normal context로 잡힌 수 |

v126 기준으로는 D confirmed macro truth 682건 중 682건이 포착됩니다. 책임 밖 655건은 확정 과탐이 아니라 정상/검토 context로 유지됩니다. 직접점수와 review는 같은 transaction case에 동시에 붙을 수 있으므로 `682 + 655`로 합산하지 않습니다.

### 조작 시나리오별 결과

D01/D02의 C축은 transaction fraud scenario가 아니라 macro business scenario별 결과로 봅니다.

| 시나리오                            | 전체 | D 책임 | 실제 잡음 | 미포착 | 책임 밖 |
| :---------------------------------- | ---: | -----: | --------: | -----: | ------: |
| D01 confirmed account variance      |  336 |    336 |       336 |      0 |       0 |
| D01 normal/review macro context     |  504 |      0 |       504 |      0 |     504 |
| D02 confirmed monthly pattern shift |  346 |    346 |       346 |      0 |       0 |
| D02 raw-positive normal context     |  151 |      0 |       151 |      0 |     151 |

`책임 밖`은 D01/D02가 잘못 잡은 false positive가 아니라, 확정 D 책임은 아니지만 PHASE1에서 review/normal context로 유지하는 macro signal입니다.

해석:

- `D01 confirmed account variance`는 target anomaly concentration, anomaly-supported shift, suspicious bypass account 등 confirmed macro context로 priority 보강 대상입니다.
- `D01 normal/review macro context`는 정상 가격 인상, 대량 운영, capex, working capital timing 등으로 잡히지만 확정 위험이 아니라 review/normal context입니다.
- `D02 confirmed monthly pattern shift`는 target anomaly monthly shift, manual monthly shift with target anomaly 등 confirmed macro context입니다.
- `D02 raw-positive normal context`는 recurring/interface batch, seasonal timing, quarter-end concentration 등으로 잡히지만 확정 위험이 아니라 normal context입니다.

### D 룰별 macro 포착

| 룰  | 전체 | D 책임 | 실제 잡음 | 미포착 | 책임 밖 |
| :-- | ---: | -----: | --------: | -----: | ------: |
| D01 |  840 |    336 |       840 |      0 |     504 |
| D02 |  497 |    346 |       497 |      0 |     151 |

한 transaction case가 여러 D macro context에 동시에 걸릴 수 있으므로 위 표의 룰별 합계는 전체 transaction case 수와 다를 수 있습니다. 특히 D01/D02는 계정-year 단위 macro 신호라서 전표 직접 위험점수에는 그대로 들어가지 않고 `macro_contexts`와 priority 보강으로 들어갑니다.

**C축 결론**: D01/D02 confirmed macro truth 682건 중 682건이 포착됩니다. 책임 밖 655건은 확정 과탐이 아니라 review/정상 context입니다. 정상/검토 context를 확정 alert로 보내지 않는 것이 PHASE1 원칙에 맞습니다.

---

## 결론

| #   | 결론                                                                                                                                                                                                                |
| :-- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | **A축(룰 계약)**: v126 D01/D02 모두 confirmed truth 기준 미탐 0건. PHASE1 recall-first 목표 충족.                                                                                                                   |
| 2   | **B축(Sidecar 현실성)**: confirmed truth, raw-positive normal/review context, stable/near/guardrail controls, exclusions 역할이 분리. precision 분모에서 정상 macro context가 정확히 빠짐.                          |
| 3   | **C축(운영 점수 분리)**: D 계열의 C축은 `manipulated_entry_truth.csv`가 아니라 `macro_priority_score`/`queue_bucket`/`normal_likelihood`/`macro_contexts` 기반 우선순위 분리 검증. raw flag가 단독 alert로 흐르지 않음. |

최종 판단:

- D01/D02는 confirmed truth 기준 미탐이 없으므로 PHASE1의 "잡을 건 모두 잡는다"는 목적에 맞습니다.
- D01 504건, D02 151건의 과탐성 맥락은 삭제 대상이 아니라 정상/검토 macro context입니다.
- 실무 사용 가능성은 raw positive를 그대로 확정 alert로 내보내지 않고, priority/queue/context와 함께 보여주는 조건에서 성립합니다.
