# DataSynth Rule-Contract Risk Audit

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
기준 데이터: `data/journal/primary/datasynth/` freeze `v126`

작성일: `2026-05-03`

## 질문

현재 실제 조작/주입 데이터 외에, 룰 계약 검사용으로 들어간 데이터 중 실무에서 그냥 넘기면 안 되는 후보가 있는지 전수 조사한다.

## 조사 기준

제외한 실제 조작/주입 데이터:

- `labels/anomaly_labels.csv`에 존재하는 문서: `2,992` documents
- `labels/manipulated_entry_truth.csv` 및 revenue manipulation sidecar 문서: `557` documents
- 둘의 중복: `137` documents
- 조작/주입 제외 기준 전체: `3,412` unique documents

조사 대상:

- `labels/rule_truth.csv`에 존재하지만 위 조작/주입 기준에는 없는 문서
- 즉, “조작으로 심은 정답”은 아니지만 Phase 1 룰 계약상 잡히는 전표

## 결론

있다. 특히 아래 두 부류는 실무에서 그냥 정상으로 넘기면 안 된다.

1. `hard_exception`: 실제 필드/통제/회계정합성 자체가 깨진 항목
2. `high_review`: 단독으로 부정 확정은 아니지만 감사인이 근거 확인 없이 넘기면 안 되는 항목

반대로 `broad_review`는 실무상 전부 문제가 아니라 넓은 모집단 플래그다. 예: 수기전표, 관계사거래, 월초/월말 전표, 주말/심야 전표. 이들은 전표가 많아도 “전부 위험”으로 해석하면 안 되고, score/case layer에서 우선순위를 나눠야 한다.

## 전체 요약

| 분류 | 의미 | 조작/주입 제외 후 고유 전표 |
|---|---|---:|
| `hard_exception` | 실제라면 원장/통제/회계정합성 문제로 바로 확인 필요 | 1,688 |
| `high_review` | 정상 사유가 있을 수 있지만 감사 검토 없이 넘기면 안 됨 | 17,060 |
| `broad_review` | 넓은 review 모집단. 자체만으로 위반 확정 아님 | 182,142 |

## Hard Exception

이 그룹은 “룰 계약 검사용”으로 들어갔더라도, 실제 회사 데이터에 있으면 그냥 넘기면 안 된다.

| 룰 | 의미 | rule truth docs | 조작/주입 overlap | 조작/주입 제외 후 남는 문서 |
|---|---|---:|---:|---:|
| L1-01 | 차대변 불일치 | 316 | 303 | 13 |
| L1-02 | 필수필드 누락 | 156 | 51 | 105 |
| L1-04 | 승인한도 초과 | 56 | 43 | 13 |
| L1-05 | 자기승인 | 244 | 231 | 13 |
| L1-07 | 승인 생략 | 96 | 65 | 31 |
| L1-08 | 회계기간 불일치 | 731 | 302 | 429 |
| L1-09 | 승인일 누락 | 122 | 76 | 46 |
| L3-07 | 전기일/증빙일 괴리 | 657 | 396 | 261 |
| L3-09 | 장기 미정리 가계정/미결 | 1,091 | 72 | 1,019 |
| L3-11 | 매출/비용 cutoff mismatch | 130 | 110 | 20 |

해석:

- 이들은 “조작 라벨이 없으니 정상”이 아니다.
- DataSynth에서는 Phase 1 계약 검사용 field/rule truth로 남아 있지만, 실제 감사에서는 예외 사유 확인이 필요한 항목이다.
- 특히 `L3-09` 1,019건, `L1-08` 429건, `L3-07` 261건은 조작 라벨 없이도 실무 검토 대상으로 봐야 한다.

## High Review

이 그룹은 실무에서 무조건 위반이라고 단정하면 안 된다. 하지만 감사인이 근거 확인 없이 넘기면 안 되는 후보군이다.

| 룰 | 의미 | rule truth docs | 조작/주입 overlap | 조작/주입 제외 후 남는 문서 |
|---|---|---:|---:|---:|
| L2-01 | 승인한도 근접 | 457 | 105 | 352 |
| L2-02 | 중복 지급 후보 | 384 | 40 | 344 |
| L2-03 | 중복 전표 후보 | 111 | 13 | 98 |
| L2-04 | 비용 자본화 후보 | 1,098 | 55 | 1,043 |
| L2-05 | 역분개/상계/재분류 후보 | 80 | 54 | 26 |
| L3-01 | 업무 프로세스-계정 불일치 | 2,419 | 46 | 2,373 |
| L3-10 | 고위험 계정 사용 | 1,601 | 85 | 1,516 |
| L4-01 | 매출 이상 후보 | 964 | 159 | 805 |
| L4-03 | 고액 이상 후보 | 4,015 | 557 | 3,458 |
| L4-04 | 희소 계정조합 | 4,091 | 151 | 3,940 |
| L4-05 | 비정상 시간대 사용자 집중 | 4,964 | 138 | 4,826 |
| L4-06 | 배치/동시생성 이상 후보 | 692 | 316 | 376 |

해석:

- `L2-04`, `L3-01`, `L3-10`, `L4-03`, `L4-04`, `L4-05`는 조작 라벨이 없어도 실무 검토 큐에 남기는 게 맞다.
- 다만 이것을 `anomaly_labels.csv`에 모두 넣으면 “확정 조작”과 “검토 후보”가 섞이므로 안 된다.
- 현재 구조처럼 `rule_truth`에는 남기고, score/case layer에서 정상 사유·위험 사유를 나누는 방향이 맞다.

## Broad Review

이 그룹은 숫자가 매우 크지만, “위험 후보”라기보다 Phase 1이 넓게 잡는 모집단이다.

| 룰 | 의미 | rule truth docs | 조작/주입 overlap | 조작/주입 제외 후 남는 문서 |
|---|---|---:|---:|---:|
| L3-02 | 수기/조정 전표 모집단 | 86,808 | 1,600 | 85,208 |
| L3-03 | 관계사 거래 모집단 | 30,377 | 373 | 30,004 |
| L3-04 | 월초/월말 전표 모집단 | 141,375 | 2,052 | 139,323 |
| L3-05 | 주말/휴일 전표 모집단 | 24,318 | 437 | 23,881 |
| L3-06 | 심야/비업무시간 전표 모집단 | 7,507 | 524 | 6,983 |

해석:

- 이들은 “실무에서 전부 허용 안 됨”이 아니다.
- 다만 PHASE1의 review anchor로는 필요하다.
- 위험 여부는 금액, 승인, 계정, 사용자, 반복성, 설명, 조합룰로 후단에서 판단해야 한다.

## Macro Findings

전표 단위가 아니라 `fiscal_year + company_code + gl_account` 단위 finding이다.

| 룰 | 단위 | rows | 해석 |
|---|---|---:|---|
| L4-02 | 회사-연도-계정 Benford group | 99 | 개별 전표 정답이 아니라 분포 이상 계정 그룹 |
| D01 | 회사-연도-계정 활동량 변동 | 840 | 계정 활동량 review universe. confirmed subset은 336 |
| D02 | 회사-연도-계정 월별 패턴 변동 | 497 | 월별 패턴 review universe. confirmed subset은 346 |

이들은 조작 라벨과 직접 비교하면 안 된다. 계정 단위 분석 finding으로 봐야 한다.

## 복합 위험 문서

조작/주입 라벨이 없는데 hard/high rule이 여러 개 동시에 걸리는 문서도 있다.

상위 예시:

| document_id | rule count | rules |
|---|---:|---|
| `20cfcba5-b08d-44eb-8231-c13f76db8675` | 6 | L1-08,L2-03,L3-07,L3-10,L4-04,L4-05 |
| `6ba5bc74-678b-4843-ab98-b44ebd1c7c45` | 6 | L1-08,L3-07,L3-09,L4-03,L4-04,L4-05 |
| `94e6909b-32b6-46b2-b565-57c8c82c06ba` | 6 | L1-08,L2-01,L2-03,L3-07,L4-04,L4-05 |
| `0539dc40-74b0-4cff-944d-328d7d079f7c` | 5 | L1-07,L1-08,L1-09,L2-02,L2-03 |
| `13f219da-4cf0-4c8f-8f37-341f1fc4661f` | 5 | L1-07,L1-09,L2-02,L2-03,L4-05 |

이런 문서는 조작 라벨이 없어도 실제 감사 UI에서는 상단에 올라와야 한다.

## 판단

DataSynth v126에는 “조작으로 심은 건 아니지만 실무에서 그냥 넘기면 안 되는 룰 계약 후보”가 존재한다.

권장 처리:

- `anomaly_labels.csv`에 추가하지 않는다. 조작/주입 truth와 review truth가 섞인다.
- `rule_truth.csv`에는 유지한다. PHASE1 계약 검증 대상이기 때문이다.
- 대시보드/평가에서는 다음처럼 분리한다.
- `hard_exception`: 원장/통제 정합성 issue로 별도 count 및 우선 검토.
- `high_review`: case priority와 정상 사유로 분류.
- `broad_review`: 모집단 anchor로 유지하되 단독 고위험으로 표시하지 않음.
- 복합 rule hit는 조작 라벨 여부와 무관하게 case priority에서 상향한다.

## Hard Exception 재분류

추가 질문: 위 `hard_exception` 1,688개가 전부 “실제 회사에서는 허용 불가한 데이터 품질 오류”인가?

답: 아니다. 실제 회사에서도 발생 가능한 review 항목이 섞여 있다. 다만 “그냥 정상으로 넘기면 안 되는 항목”이라는 점은 유지된다.

상세 결과 파일:

`docs/datasynth_hard_exception_reclassification_v126.csv`

### 재분류 요약

| 재분류 | 고유 전표 | 판단 |
|---|---:|---|
| `realistic_but_must_review` | 1,018 | 실제 회사에서도 있을 수 있음. 하지만 장기 미결/가계정은 해소계획 확인 필요 |
| `hard_period_mapping_error` | 227 | 회계기간 매핑 오류 가능성이 커서 DataSynth/ERP 품질 이슈로 보는 게 맞음 |
| `possible_period_cutoff_or_late_close` | 201 | 실제 마감/전기 지연에서 가능. 설명 필요 |
| `hard_data_quality_or_interface_error` | 58 | 핵심 필드 누락. 실제 ERP 원장이라면 데이터 품질 문제 |
| `possible_late_invoice_or_cutoff_review` | 57 | 증빙 수취 지연/마감 차이 가능. review 필요 |
| `possible_system_or_recurring_exception` | 34 | 자동/반복 전표의 승인자/승인일 공백. 시스템 정책 확인 필요 |
| `reviewable_data_quality_gap` | 32 | 보조/계약 필드 누락. 즉시 부정은 아니지만 품질 gap |
| `cutoff_review_needed` | 20 | 수익/비용 귀속 확인 필요 |
| `control_exception_review` | 15 | 승인한도 초과/자기승인 등 통제 예외 검토 |
| `hard_data_quality_or_posting_error` | 13 | 차대변 불일치. 실제라면 거의 허용 불가 |
| `possible_system_exception_but_needs_policy` | 8 | 시스템성 자기승인 가능. 정책 확인 필요 |
| `control_evidence_gap` | 5 | 승인 증적 미비 |

### 룰별 재분류

| 룰 | 재분류 | 건수 |
|---|---|---:|
| L1-01 | `hard_data_quality_or_posting_error` | 13 |
| L1-02 | `hard_data_quality_or_interface_error` | 71 |
| L1-02 | `reviewable_data_quality_gap` | 34 |
| L1-04 | `control_exception_review` | 13 |
| L1-05 | `control_exception_review` | 5 |
| L1-05 | `possible_system_exception_but_needs_policy` | 8 |
| L1-07 | `possible_system_or_recurring_exception` | 31 |
| L1-08 | `hard_period_mapping_error` | 227 |
| L1-08 | `possible_period_cutoff_or_late_close` | 202 |
| L1-09 | `control_evidence_gap` | 6 |
| L1-09 | `possible_system_or_recurring_exception` | 40 |
| L3-07 | `high_cutoff_or_backdating_risk` | 182 |
| L3-07 | `possible_late_invoice_or_cutoff_review` | 79 |
| L3-09 | `realistic_but_must_review` | 1,019 |
| L3-11 | `cutoff_review_needed` | 20 |

### 해석

- `L3-09` 1,019건은 “허용불가 데이터 품질 오류”라기보다 장기 미결/가계정 체류다. 실제 회사에서도 존재할 수 있지만, 감사에서는 해소계획·잔액 성격·반제 예정일을 확인해야 한다.
- `L1-08` 227건은 회계기간과 전기월이 크게 어긋나는 케이스다. 이건 정상 업무 사유보다는 DataSynth/ERP period mapping 품질 이슈에 가깝다.
- `L1-01` 13건은 차대변 합계가 실제로 안 맞는 문서다. 이건 실제 회사 원장이라면 거의 허용 불가다.
- `L1-02` 핵심 필드 누락 71건도 실제 ERP 원장 기준으로는 품질 오류다.
- `L1-07`, `L1-09`의 상당수는 자동/반복 전표라 실제 시스템 정책에 따라 정상일 수 있다. 다만 승인 워크플로우 정책 확인 없이는 그냥 정상 처리하면 안 된다.

### 결론 업데이트

`hard_exception` 1,688개를 모두 같은 강도로 보면 과하다.

실무형 해석은 다음이 맞다.

- 명백한 데이터 품질/전표 오류: 약 `369`건 수준
- 실제 발생 가능하지만 review 필요한 항목: 약 `1,200+`건 수준
- 시스템/반복 정책 확인이 필요한 항목: 약 `80`건 수준

따라서 DataSynth를 고칠 방향은 “전부 삭제”가 아니라:

- 명백한 DataSynth 품질 오류는 줄이거나 원인 sidecar를 붙인다.
- 실제 가능 항목은 `normal_reason`, `exception_reason`, `review_reason`을 더 명확히 붙인다.
- UI에서는 `hard_error`, `control_gap`, `review_required`, `system_policy_exception`으로 나눠 보여준다.

## 저장된 분류 Sidecar

운영 DataSynth labels 아래에 다음 sidecar를 추가했다.

| 파일 | 의미 | rows | unique docs |
|---|---|---:|---:|
| `rule_contract_exception_context.csv` | hard exception 전체 재분류 | 1,950 | 1,688 |
| `rule_contract_hard_error.csv` | 명백한 데이터 품질/전표 오류 | 311 | 298 |
| `rule_contract_control_gap.csv` | 승인/통제 예외 | 24 | 23 |
| `rule_contract_review_required.csv` | 실제 가능하지만 review 필요 | 1,536 | 1,513 |
| `rule_contract_system_policy_exception.csv` | 시스템/반복 정책 확인 필요 | 79 | 48 |
| `rule_contract_exception_context_summary.csv` | 위 분류 요약 | 4 | 4 |

별도 분석 CSV:

- `docs/datasynth_hard_exception_reclassification_v126.csv`

## High/Broad Review 규모 재평가

추가 질문: `high_review=17,060`, `broad_review=182,142`는 너무 많은가?

답: `broad_review`는 위험 건수로 보면 너무 많지만, 모집단 anchor로 보면 가능한 구조다. `high_review`는 전체 문서의 `5.34%`라 “감사 검토 큐”로는 많고, 일부 룰은 DataSynth가 과다한 편이다.

전체 문서 수: `319,193`

| 분류 | unique docs | 전체 문서 대비 | 판단 |
|---|---:|---:|---|
| `high_review` | 17,060 | 5.34% | 많다. 모두 상위 위험으로 올리면 안 됨 |
| `broad_review` | 182,142 | 57.06% | 위험 수치가 아니라 모집단 flag로만 해석해야 함 |

상세 요약 파일:

- `labels/rule_contract_review_population_risk_summary.csv`
- `docs/datasynth_review_population_risk_summary_v126.csv`

### Broad Review

| 룰 | 조작/주입 제외 후 문서 | 전체 대비 | 판단 |
|---|---:|---:|---|
| L3-04 월초/월말 | 139,323 | 43.65% | `±5일` window라 구조적으로 큼. 위험이 아니라 마감 모집단 |
| L3-02 수기/조정 | 85,208 | 26.69% | 회사/ERP에 따라 가능. 위험이 아니라 수기 모집단 |
| L3-03 관계사 | 30,004 | 9.40% | 그룹사면 가능 |
| L3-05 주말/휴일 | 23,881 | 7.48% | 높은 편. 자동 배치가 많으면 가능하지만 일반 회사 기준 큼 |
| L3-06 심야 | 6,983 | 2.19% | 배치/해외/교대근무 있으면 가능 |

Broad review 결론:

- 실제 회사에서도 수기, 관계사, 월말/월초, 주말/심야 전표는 많이 나올 수 있다.
- 하지만 이걸 “위험 182,142건”으로 표현하면 안 된다.
- UI에서는 `review anchor population` 또는 `screening population`으로만 표시해야 한다.

### High Review

| 룰 | 조작/주입 제외 후 문서 | 전체 대비 | 판단 |
|---|---:|---:|---|
| L4-05 비정상 시간대 사용자 집중 | 4,826 | 1.51% | high-review로는 많은 편. 과다 가능성 |
| L4-04 희소 계정조합 | 3,940 | 1.23% | 기준이 넓으면 가능하지만 많은 편 |
| L4-03 고액 이상 | 3,458 | 1.08% | 대기업/제조업이면 가능하지만 많은 편 |
| L3-01 업무-계정 불일치 | 2,373 | 0.74% | DataSynth가 많은 편 |
| L3-10 고위험 계정 | 1,516 | 0.47% | 계정정책 따라 가능하나 단독 위험 아님 |
| L2-04 비용 자산화 | 1,043 | 0.33% | 정상 CAPEX context 없으면 많은 편 |
| L4-01 매출 이상 | 805 | 0.25% | 가능한 수준 |
| L4-06 배치 이상 | 376 | 0.12% | 가능한 수준 |
| L2-01 한도 근접 | 352 | 0.11% | 가능하지만 승인자/금액 쏠림 확인 필요 |
| L2-02 중복 지급 | 344 | 0.11% | 실제 AP에서 가능하지만 검토 큐로는 많은 편 |
| L2-03 중복 전표 | 98 | 0.03% | 가능한 수준 |
| L2-05 역분개/정정 | 26 | 0.01% | 가능한 수준 |

High review 결론:

- `L2-03`, `L2-05`, `L4-01`, `L4-06`은 규모가 과하다고 보기 어렵다.
- `L2-01`, `L2-02`, `L2-04`, `L3-01`은 DataSynth가 다소 많은 편이다.
- `L4-03`, `L4-04`, `L4-05`는 high-review로 직접 노출하면 너무 많다. score/case priority로 상위 일부만 올리는 게 맞다.

### 실무 감각

보통 회사에서 나올 수 있는가?

- Broad review: 가능하다. 단, 위험 건수로 보면 안 된다.
- High review: 일부 가능하지만 v126은 검토 후보가 많은 편이다.
- Hard exception: 전부 허용불가 오류는 아니지만, 명백한 품질 오류는 더 줄이거나 별도 표시해야 한다.

따라서 v126은 “룰 계약 검증용”으로는 맞지만, 실무형 UI에서는 `rule_truth` 전체를 위험 건수처럼 보여주면 안 된다.

## Contract 세부 Taxonomy

contract/manipulation 분리 전에 contract 내부 truth를 먼저 세분화했다.

생성 파일:

- `labels/contract_rule_truth_taxonomy.csv`
- `labels/contract_rule_truth_taxonomy_summary.csv`
- `labels/contract_sidecar_taxonomy.csv`
- `labels/contract_sidecar_taxonomy_summary.csv`
- `docs/datasynth_contract_rule_truth_taxonomy_v126.csv`
- `docs/datasynth_contract_rule_truth_taxonomy_summary_v126.csv`
- `docs/datasynth_contract_sidecar_taxonomy_v126.csv`
- `docs/datasynth_contract_sidecar_taxonomy_summary_v126.csv`

### Rule Truth Taxonomy

`rule_truth.csv`를 다음 기준으로 나눴다.

| contract bucket | 의미 |
|---|---|
| `hard_error` | 데이터 정합성/전표 품질 오류. 실제 원장이면 별도 정리 필요 |
| `control_gap` | 승인/SoD/통제 예외 |
| `system_policy_exception` | 시스템/반복 전표 정책 확인 필요 |
| `review_required` | 실제로 있을 수 있지만 감사 검토 필요 |
| `high_review` | 정상 사유가 있을 수 있지만 score/case priority로 검토해야 하는 후보 |
| `broad_review` | 넓은 모집단 anchor. 단독 위험으로 해석 금지 |
| `macro_finding` | 전표가 아니라 회사-연도-계정 단위 분석 finding |

요약:

| contract family | bucket | rows | unique documents | actual issue overlap docs |
|---|---|---:|---:|---:|
| `broad_population_contract` | `broad_review` | 290,388 | 184,889 | 2,747 |
| `high_review_contract` | `high_review` | 18,746 | 16,498 | 931 |
| `transaction_pattern_contract` | `high_review` | 2,130 | 2,101 | 256 |
| `macro_analytical_contract` | `macro_finding` | 1,436 | 0 | 0 |
| `timing_cutoff_contract` | `review_required` | 1,878 | 1,876 | 576 |
| `data_integrity_contract` | `hard_error` | 999 | 999 | 688 |
| `data_integrity_contract` | `review_required` | 236 | 236 | 0 |
| `control_contract` | `control_gap` | 458 | 374 | 350 |
| `control_contract` | `system_policy_exception` | 79 | 48 | 0 |
| `unclassified_contract` | `review_required` | 428 | 428 | 428 |

해석:

- `actual issue overlap docs`가 있다는 것은 같은 문서가 실제 조작/주입 라벨과도 겹친다는 뜻이다.
- contract 데이터셋을 만들 때는 이 문서들을 남길 수 있지만, manipulation 데이터셋에서는 manipulation truth로만 평가해야 한다.
- `unclassified_contract` 428건은 현재 L3-08 계열 `MissingOrCorruptedDescription` 성격이다. 다음 라운드에서 `description_quality_contract`로 별도 family를 부여하는 게 낫다.

### Sidecar Taxonomy

sidecar 파일도 다음처럼 분류했다.

| contract layer | sidecar truth kind | files | 해석 |
|---|---|---:|---|
| `contract_truth` | `detector_contract_or_rule_truth` | 22 | 룰 계약/정합성 검증용 truth |
| `contract_truth` | `contract_context` | 5 | 계약 truth 보조 context |
| `contract_truth` | `field_contract_context` | 1 | L1 field-only 계약 context |
| `contract_truth` | `system_policy_contract_context` | 3 | 시스템/반복 정책 계약 context |
| `sidecar_context` | `review_population_or_detector_universe` | 32 | detector universe 또는 넓은 review 모집단 |
| `sidecar_context` | `normal_or_legitimate_context` | 33 | 정상/합리적 사유 context |
| `sidecar_context` | `confirmed_issue_subset` | 17 | confirmed subset. 단, 조작 truth와 동일하다고 보면 안 됨 |
| `sidecar_context` | `boundary_or_holdout_context` | 13 | 경계값/holdout/adversarial context |
| `sidecar_context` | `case_or_drilldown_context` | 11 | drilldown/case-level context |
| `sidecar_context` | `negative_control` | 8 | detector가 낮은 점수 또는 미탐이어야 할 정상 대조군 |
| `sidecar_context` | `cross_rule_labeled_context` | 1 | 다른 라벨과 겹치는 cross-rule context |
| `sidecar_context` | `document_projection_context` | 2 | user/group finding을 document로 투영한 context |
| `sidecar_context` | `boundary_or_master_data_context` | 1 | master data 경계 context |
| `sidecar_context` | `boundary_or_downstream_control_context` | 1 | 후속 통제 경계 context |
| `sidecar_context` | `limitation_or_untestable_context` | 1 | 증거 부족/평가 제한 context |
| `sidecar_context` | `priority_review_context` | 1 | 우선순위 review context |
| `sidecar_context` | `review_context` | 1 | 일반 review context |
| `sidecar_context` | `drilldown_candidate` | 1 | drilldown 후보 |
| `manipulation_truth` | `actual_issue_truth` | 6 | 실제 조작/주입 truth |
| `manifest_log` | `diagnostic_or_lineage_manifest` | 19 | lineage/diagnostic. 평가 truth 아님 |
| `manifest_log` | `exclusion_manifest` | 1 | 제외 사유 manifest |

### 정리 완료 및 다음 단계

완료:

- `sidecar_context/unclassified_context` 33개 파일을 모두 재분류했다. 남은 unclassified sidecar는 `0`개다.
- `confirmed_issue_subset`은 contract confirmed subset으로 분류하고, 실제 조작 truth는 `manipulation_truth/actual_issue_truth`로 분리했다.
- `review_population_or_detector_universe`는 위험 카운트가 아니라 모집단 카운트로 표시해야 한다.
- `normal_or_legitimate_context`, `negative_control`, `boundary_or_holdout_context`는 score calibration/경계 검증용으로 표시해야 한다.

두 벌 분리용 manifest:

- `labels/contract_dataset_split_manifest.json`
- `docs/datasynth_contract_dataset_split_manifest_v126.json`

다음 단계:

- `data/journal/primary/datasynth_contract/` 생성 완료
- `data/journal/primary/datasynth_manipulation/` 생성 완료
- 기존 `data/journal/primary/datasynth/`는 downstream loader 마이그레이션이 끝날 때까지 호환용으로 유지

## Physical Split 완료

`v126` 운영본을 기준으로 실제 데이터 폴더를 두 벌로 분리했다.

| dataset | rows | documents | columns | labels policy |
|---|---:|---:|---:|---|
| `datasynth_contract` | 1,109,435 | 319,193 | 49 | contract truth, sidecar context, manifest log만 포함 |
| `datasynth_manipulation` | 1,095,158 | 317,505 | 49 | manipulation truth만 포함 |

공통 처리:

- 원장 본문에서 직접 라벨 컬럼 제거: `is_fraud`, `fraud_type`, `is_anomaly`, `anomaly_type`
- 기존 `datasynth`는 compatibility baseline으로 유지

`datasynth_contract`:

- 원장 문서는 제거하지 않고 전체 유지
- `anomaly_labels.csv`, `manipulated_entry_truth*`, `revenue_manipulation_*` 같은 manipulation truth는 제외
- `rule_truth*`, `contract_*taxonomy*`, `rule_contract_*`, normal/boundary/negative/review sidecar 유지
- 목적: 데이터 정합성, 룰 계약, sidecar behavior 검증

`datasynth_manipulation`:

- contract-only hard/control/review fixture 문서 `1,688`개 제거
- `rule_truth*`, contract taxonomy, contract sidecar는 제외
- `anomaly_labels.csv`, `manipulated_entry_truth*`, `revenue_manipulation_*`만 유지
- 목적: 실제 조작/주입 시나리오 분석 및 synthetic ML/DL 실험

검증:

- `datasynth_contract` 원장 직접 라벨 컬럼: `0`
- `datasynth_manipulation` 원장 직접 라벨 컬럼: `0`
- `datasynth_contract/labels/anomaly_labels.csv`: 없음
- `datasynth_manipulation/labels/rule_truth.csv`: 없음
- manipulation label document reference missing: `0`

Manifest:

- `data/journal/primary/datasynth_contract/CONTRACT_DATASET_MANIFEST.json`
- `data/journal/primary/datasynth_manipulation/MANIPULATION_DATASET_MANIFEST.json`
