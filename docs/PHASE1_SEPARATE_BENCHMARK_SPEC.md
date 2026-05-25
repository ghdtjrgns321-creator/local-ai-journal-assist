# PHASE1 별도 검증 스펙

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> Current PHASE1 scoring note (2026-04-27): 별도 benchmark 대상 룰 중 `L4-02`는 transaction queue에서 `macro_only`로 정규화된다. 즉 row-level `normalized_score`는 case priority에 직접 기여하지 않고, Account / Process Queue 또는 macro-finding drill-down에서 평가한다. `L4-03`, `L4-04`, `L4-05`는 transaction queue에 남지만 `rule_scoring.py`의 `evidence_strength`와 `scoring_role`을 거친 `normalized_score`만 evidence type score에 합산된다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

PHASE1 룰 중 일부는 `document_labels.csv`의 전표 단위 정답만으로 검증하면 룰의 본질을 왜곡한다. 이 문서는 그런 룰에 대해 별도 benchmark 단위, 입력 산출물, acceptance 기준을 정의한다.

관련 문서:

- [DETECTION_RULES.md](DETECTION_RULES.md)
- [DETECTION_PORTFOLIO_REFRAME.md](DETECTION_PORTFOLIO_REFRAME.md)
- [metrics.md](metrics.md)

## 1. 목적

- 전표 단위 precision / recall만으로 검증하면 안 되는 PHASE1 룰을 분리한다.
- 룰별로 맞는 평가 단위(document / population / cohort / user)를 명시한다.
- 이후 pytest 또는 quality gate 구현 시 그대로 옮길 수 있는 benchmark contract를 정의한다.

## 2. 적용 범위

본 스펙의 직접 대상은 다음 5개 룰이다.

| 룰 | 현재 성격 | 별도 검증 단위 | 비고 |
| --- | --- | --- | --- |
| `L4-02` | 분포 이상 | dataset / segment | Benford는 전형적인 population-level anomaly |
| `L4-03` | 통계적 이상치 | account-group population | 개별 전표 정답보다 집단 내 outlier coverage가 중요 |
| `L4-04` | 정의 재정렬 필요 | special-account population | 현재 저장소 정의와 재분류 요구가 충돌 가능 |
| `L3-09` | 정의 재정렬 필요 | document 또는 cohort | 룰 정의 확정 전까지 평가 방식 고정 금지 |
| `L4-05` | 사용자 행동 이상 | user / user-day | user concentration, rapid approval coverage 중심 |

## 3. 핵심 원칙

### 3.1 금지 사항

- 위 5개 룰에 대해 `document_labels.csv` 한 줄 라벨만으로 최종 성능을 선언하지 않는다.
- 전표 단위 TP/FP/FN 수치만으로 룰 유지/폐기를 결정하지 않는다.
- population/user anomaly를 억지로 문서 단위 정답으로 환산하지 않는다.

### 3.2 허용 사항

- 문서 단위 리포트에는 `참고용 proxy`로만 표시할 수 있다.
- 최종 acceptance는 이 문서의 separate benchmark 결과를 우선한다.
- 필요 시 `ground_truth + benchmark + operational_proxy`를 함께 제시한다.

## 4. 결과 상태 분류

별도 benchmark 대상 룰은 아래 4개 상태 중 하나로 보고한다.

| 상태 | 의미 |
| --- | --- |
| `benchmark_pass` | 별도 benchmark 기준 충족 |
| `benchmark_fail` | 별도 benchmark 기준 미충족 |
| `proxy_only` | 문서 라벨 지표만 존재, 별도 benchmark 미구축 |
| `definition_pending` | 룰 정의가 고정되지 않아 benchmark 판정 불가 |

## 5. 공통 산출물 계약

별도 benchmark는 아래 산출물을 기준으로 동작한다.

| 파일 | 역할 |
| --- | --- |
| `benchmark_manifest.yaml` | 룰 ID, 평가 단위, segment 키, 기준값 정의 |
| `expected_dataset_metrics.json` | dataset-level 기대치 저장 |
| `expected_segment_metrics.csv` | 계정군/코호트/기간별 기대치 저장 |
| `expected_user_metrics.csv` | 사용자 단위 기대치 저장 |
| `benchmark_notes.md` | fixture 생성 이유와 예외 규칙 설명 |

필수 필드:

- `benchmark_id`
- `rule_id`
- `evaluation_unit`
- `population_key`
- `expected_positive_scope`
- `expected_negative_scope`
- `acceptance_metric`
- `acceptance_threshold`

## 6. 룰별 스펙

### 6.1 L4-02 - Benford MAD/SSD 기준

#### 평가 단위

- 1차: dataset-level
- 2차: segment-level
  - `gl_account_group`
  - 필요 시 `company_code`, `fiscal_year`, `document_type`

#### 입력

- 전체 금액 분포
- segment별 첫 유효 숫자 분포
- benchmark fixture에 저장된 기대 MAD/SSD

#### 핵심 지표

- `mad`
- `ssd`
- `violating_digits`
- `flagged_segment_count / expected_positive_segment_count`

#### acceptance

- 음성 fixture:
  - `mad`가 설정 임계값 이하
  - `ssd`가 baseline band 이내
  - detector가 segment를 과도하게 positive로 만들지 않을 것
- 양성 fixture:
  - 왜곡된 segment를 detector가 식별할 것
  - `mad` 기준 위반 segment recall이 목표치 이상일 것
  - `ssd`는 회귀 방지용 보조 지표로 기록할 것

#### 판정 메모

- L4-02은 "어떤 전표 하나가 Benford 위반인가"보다 "어떤 모집단 분포가 왜곡되었는가"를 검증한다.
- 문서 단위 flag는 drill-down 편의용 보조 산출물로 본다.

### 6.2 L4-03 - 계정군별 outlier population

#### 평가 단위

- `gl_account_group`
- 필요 시 `gl_account_group x fiscal_period`

#### 입력

- 계정군별 금액 분포
- 계정군별 outlier 주입 population
- detector의 flagged row / doc 결과

#### 핵심 지표

- `positive_group_recall`
- `negative_group_false_alarm_rate`
- `outlier_capture_rate_within_positive_group`
- `lift_vs_baseline`

#### acceptance

- 양성 계정군에서 outlier population을 충분히 커버할 것
- 음성 계정군에서는 flagged rate가 허용치 이내일 것
- 개별 전표 몇 건을 맞혔는지보다, 주입된 집단의 이상치 population을 분리해내는지를 본다.

#### 판정 메모

- L4-03은 단건 정답 여부보다 "같은 계정군 안에서 극단값을 끌어내는 능력"이 중요하다.
- 정상 대형거래와 혼재될 수 있으므로 전체 precision만으로 해석하지 않는다.

### 6.3 L4-04 - suspense / 가계정 / 특수 계정군 비율

#### 정의 전제

- 사용자가 제안한 separate benchmark는 `suspense/가계정 또는 특수 계정군 비율` 기준이다.
- 현재 저장소의 `L4-04`는 `UnusualAccountPair`, `L3-09`은 `SuspenseAccountAbuse`이므로 번호 체계 충돌 가능성이 있다.
- 따라서 구현 전 먼저 "비율형 benchmark를 L4-04에 붙일지 L3-09에 붙일지"를 확정해야 한다.

#### 평가 단위

- `special_account_group`
- `special_account_group x fiscal_period`

#### 입력

- 특수 계정군 분모/분자 집계
- fixture의 기대 비율
- detector 또는 rule aggregation 결과

#### 핵심 지표

- `special_account_ratio_gap`
- `positive_group_detection_rate`
- `negative_group_overflag_rate`

#### acceptance

- 양성 fixture에서 특수 계정군 비율 상승을 감지할 것
- 음성 fixture에서 정상 계정군 비율 변동을 과탐하지 않을 것
- 전표 몇 건을 맞혔는지가 아니라, 비정상 계정군 비중 상승이라는 현상을 포착해야 한다.

### 6.4 L3-09 - 전표형 / 집단형 재분류 필요

#### 정의 전제

- L3-09은 정의에 따라 평가 단위가 달라진다.
- 문서형 룰이면 전표 단위 benchmark를 사용한다.
- 체류, 잔존, 누적, 계정군 집중 같은 성격이면 cohort benchmark를 사용한다.

#### 분류 규칙

- 아래 중 하나라도 만족하면 `cohort rule`로 분류한다.
  - 기간 경과가 의미의 핵심이다.
  - 동일 계정군의 누적 잔존이 핵심이다.
  - 단일 전표보다 전표군의 패턴이 중요하다.
- 위 조건을 만족하지 않으면 `document rule`로 분류한다.

#### acceptance

- `document rule`:
  - 기존 문서 benchmark + 보조 benchmark 사용 가능
- `cohort rule`:
  - `cohort coverage`
  - `duration threshold hit rate`
  - `resolved vs unresolved separation`

#### 판정 메모

- 정의 확정 전까지는 `definition_pending` 상태로 보고한다.
- 현재 저장소의 `SuspenseAccountAbuse`는 이름상 cohort 평가가 더 자연스럽다.

### 6.5 L4-05 - user-level abnormal concentration + rapid approval coverage

#### 평가 단위

- `user`
- `user x posting_date`
- 필요 시 `user x hour_bucket`

#### 입력

- 사용자별 입력 건수
- 사용자별 심야/비정상 시간 비중
- 사용자별 rapid approval 이벤트
- fixture의 abnormal user 목록

#### 핵심 지표

- `abnormal_user_recall`
- `normal_user_false_alarm_rate`
- `rapid_approval_coverage`
- `top_k_user_concentration_precision`

#### acceptance

- 이상 사용자 집합을 일정 수준 이상 커버할 것
- rapid approval가 동반된 사용자 이벤트를 놓치지 않을 것
- 정상 사용자를 대량으로 이상 사용자로 만들지 않을 것

#### 판정 메모

- L4-05는 전표 하나의 정답보다 사용자 행동 프로파일의 이상 여부가 본질이다.
- 문서 단위 라벨은 보조 evidence로만 사용한다.

## 7. 기존 문서 라벨 검증과의 관계

| 룰 | `document_labels.csv` 지표 사용 방식 |
| --- | --- |
| `L4-02` | 참고용 proxy만 허용 |
| `L4-03` | 보조 지표로 허용, 최종 acceptance 아님 |
| `L4-04` | 정의 확정 전까지 사용 보류 |
| `L3-09` | 정의 확정 후 제한적 사용 |
| `L4-05` | 참고용 proxy만 허용 |

보고서 문구 규칙:

- `ground_truth only`라고 쓰지 않는다.
- `separate benchmark required` 또는 `benchmark basis`를 함께 표기한다.
- precision / recall 표에 넣더라도 `최종 판정 아님`을 명시한다.

## 8. 구현 순서

1. 룰 ID와 benchmark ID를 1:1로 매핑하는 manifest를 만든다.
2. L4-02, L4-05부터 separate benchmark를 우선 구현한다.
3. L4-03은 계정군 population fixture를 추가한다.
4. L4-04, L3-09은 번호 체계와 정의를 먼저 정렬한다.
5. UI / 리포트 / DB 저장 시 `benchmark_status`와 `evaluation_unit` 컬럼을 추가한다.

## 9. 최종 기준

PHASE1에서 아래 문장을 만족해야 한다.

- `L4-02`과 `L4-05`는 문서 라벨 recall이 아니라 separate benchmark pass로 본다.
- `L4-03`은 계정군 population 분리 성능으로 본다.
- `L4-04`, `L3-09`은 정의가 고정되기 전까지 숫자만 좋은 문서 benchmark를 정답처럼 쓰지 않는다.
