# DataSynth 2022~2024 전수조사 메모

> 현재 운영 기준본은 `data/journal/primary/datasynth/` freeze `v45`(2026-04-25)다. 이 문서의 초기 전수조사 수치 중 일부는 과거 기준본 분석 기록이며, 최신 운영 수치는 `data/journal/primary/datasynth/PREVIEW.md`와 `data/journal/primary/datasynth/FREEZE_V45.md`를 우선한다.

작성일: 2026-04-16
대상 경로: `data/journal/primary/datasynth`
분석 범위: `journal_entries_2022.csv`, `journal_entries_2023.csv`, `journal_entries_2024.csv`, 라벨/메타 파일

## 1. 결론 요약

- Phase 1: 실사용 가능
- Phase 2: 조건부 사용 가능
- Phase 3: 프로토타입/통합 테스트용은 가능, 일반화 검증용은 약함
- 가장 큰 리스크는 `정답 컬럼 누수`와 `생성 규칙 기반 test fitting`이다.

즉, 현재 셋은 회귀 테스트와 파이프라인 검증에는 유용하지만, 이 결과만으로 실데이터 일반화 성능을 주장하면 과대해석 위험이 크다.

## 2. 분석 대상 실데이터 기준 현황

실제 CSV 3개년 합산 기준:

- 총 row 수: `1,107,720`
- 총 document 수: `319,204`
- 연도별 row 수
  - 2022: `372,083`
  - 2023: `373,052`
  - 2024: `362,585`
- 연도별 document 수
  - 2022: `106,163`
  - 2023: `106,355`
  - 2024: `106,686`
- 문서당 평균 line 수: `3.47`
- 문서당 line 수 P99: `9`
- 최대 line 수: `998`

참고:

- `generation_statistics.json`: `1,107,688` line items
- 문서화된 v21 기준: `1,106,056` rows

즉 현재 작업 디렉터리의 실제 CSV는 문서상 v21 기준셋과 완전히 동일하지 않다. 이후 테스트/리포트 해석 시 "문서 기준셋"과 "현재 실셋"을 분리해야 한다.

## 3. 정량 점검 결과

### 3.1 중복/기초 무결성

- exact row duplicate: `0`
- `document_id + line_number` duplicate: `0`
- 연도 간 exact line signature 중복: `0`
- 불균형 전표: `51`
- 불균형 전표 중 차이 `100` 초과: `18`
- 최대 imbalance: `47,704,160`

전반적으로 중복 품질은 양호하지만, 소수의 불균형 전표는 감사/학습 전 사전 정리 후보로 봐야 한다.

### 3.2 플래그 문서 규모

- fraud 문서: `6,262`
- anomaly 문서: `8,294`
- SoD 위반 문서: `10,595`
- 총 문서 대비 비율
  - fraud: 약 `1.96%`
  - anomaly: 약 `2.60%`
  - SoD: 약 `3.32%`

### 3.3 주요 결측률

핵심 컬럼 결측률:

- `document_type`: `1.98%`
- `gl_account`: `2.00%`
- `approved_by`: `29.75%`
- `line_text`: `2.06%`
- `cost_center`: `82.02%`
- `profit_center`: `0.18%`
- `tax_code`: `91.44%`
- `tax_amount`: `91.44%`
- `auxiliary_account_number`: `59.05%`
- `trading_partner`: `58.95%`
- `supporting_doc_type`: `18.75%`

해석:

- Phase 1 핵심 룰 컬럼은 대체로 사용 가능하다.
- Phase 2/3에서 의미 있는 피처가 될 `cost_center`, `tax_*`, `trading_partner`, `auxiliary_*`는 매우 성기다.

### 3.4 텍스트 커버리지

- `header_text` non-null: `98.17%`
- `line_text` non-null: `97.94%`
- `reference` non-null: `98.02%`
- `supporting_doc_type` non-null: `81.25%`

텍스트 컬럼 자체는 충분히 채워져 있어 Phase 3 UI/리포트/설명 체인 테스트에는 활용 가능하다.

## 4. 정성 점검 결과

### 4.1 직접 누수 컬럼 존재

원장 본문에 아래 컬럼이 포함되어 있다.

- `is_fraud`
- `fraud_type`
- `is_anomaly`
- `anomaly_type`
- `sod_violation`
- `sod_conflict_type`

이 상태로 모델 학습 또는 feature engineering을 수행하면 정답 누수가 바로 발생한다. 따라서 Phase 2 학습셋 생성 시 반드시 제거해야 한다.

### 4.2 생성 규칙 기반 test fitting 위험

프로젝트 문서에도 명시되어 있듯, DataSynth 이상치는 Phase 1 룰과 구조적으로 유사한 규칙으로 생성된다. 따라서 다음 위험이 크다.

- Phase 1 룰 평가가 낙관적으로 나옴
- Phase 2 지도학습이 실제로는 "Phase 1 룰 재발견"이 됨
- 실데이터 적용 시 distribution shift로 성능이 크게 하락할 수 있음

즉 이 셋은 "실제 일반화 성능 벤치마크"보다 "개발/회귀/통합 검증용"에 더 적합하다.

### 4.3 메타 품질 파일 신뢰성 문제

`data_quality_stats.json`은 다음과 같이 실집계와 맞지 않는다.

- `total_records = 0`
- `missing_values.total_missing = 0`
- `duplicates.total_duplicates = 0`
- `records_with_issues = 29459`

즉 메타 품질 파일은 현재 상태에서 품질 근거로 직접 인용하기 어렵다. 실제 CSV 재계산값을 우선해야 한다.

### 4.4 범주형 노이즈

`user_persona`는 고유값이 `984`개까지 늘어나 있다. 정상 카테고리는 사실상 5개 수준인데, 오탈자 주입 때문에 다음과 같은 변형이 다수 존재한다.

- `senior_accoutant`
- `utomated_system`
- `senor_accountant`
- `maanger`
- 기타 수백 개 변형

이 노이즈는 강건성 테스트에는 의미가 있지만, 그대로 One-Hot/Embedding 학습에 넣으면 쓸데없는 희소성이 커진다.

## 5. Phase별 사용 적합성

## 5.1 Phase 1

판정: 사용 가능

근거:

- 핵심 회계/룰 컬럼 대부분 존재
- 데이터 규모 충분
- 연도별 물량도 균형적
- duplicate 품질 양호

주의:

- Phase 1 acceptance 성능을 이 데이터 하나로 증명하면 안 된다.
- 생성 규칙이 룰과 가까워 recall/precision이 과대평가될 수 있다.

적합한 용도:

- 회귀 테스트
- 대용량 처리/성능 테스트
- 결측/오탈자 robustness 테스트
- 룰 엔진 smoke/e2e 검증

부적합한 용도:

- 실제 고객 데이터 대응력의 최종 근거

## 5.2 Phase 2

판정: 조건부 사용 가능

장점:

- 데이터량 충분
- 연도 홀드아웃 실험 가능
- 라벨 파일 조인 가능
- 연도 간 exact 중복은 사실상 없음

리스크:

- 정답 컬럼이 원장에 포함되어 있음
- 생성 라벨이 룰 기반이라 지도학습이 룰 재발견으로 흐르기 쉬움
- 일부 중요 피처 결측이 심함
- 범주형 오탈자 노이즈가 큼

권장 조건:

- feature에서 `is_*`, `*_type`, `sod_*` 전부 제거
- split은 반드시 `document_id` 단위
- 가능하면 `2024` 전체를 holdout으로 사용
- `user_persona` 정규화 전처리 추가
- `cost_center`, `tax_*`, `trading_partner`, `auxiliary_*`는 ablation 후 사용

결론:

- 비지도/약지도 실험용: 가능
- 지도학습 benchmark용: 부적합
- 실데이터 일반화 주장용: 부적합

## 5.3 Phase 3

판정: 부분 사용 가능

장점:

- 텍스트 컬럼 커버리지가 높음
- reference/header/supporting doc 정보 존재
- 리포트, 설명, prompt chain, case summarization 테스트 가능

한계:

- 텍스트가 템플릿 반복 성향이 강함
- `header_text`가 여러 해에 걸쳐 재사용되는 값이 `3,505`개
- 실제 현업 서술의 자유도, 우회 표현, 은어, 오탈자 다양성은 부족

결론:

- Phase 3 UI/리포트/설명 가능성 테스트: 가능
- 실제 한국어 회계 텍스트 이해력 benchmark: 약함

## 6. test fitting 판정

최종 판정: test fitting 위험이 있다.

다만 종류를 구분해야 한다.

### 6.1 직접 누수

있음.

정답 컬럼이 본문에 포함되어 있어, 전처리 실수만 나도 평가가 무의미해진다.

### 6.2 분할 누수

통제 가능.

- 연도 간 exact line signature 중복: `0`
- 연도 간 near-pattern overlap: 약 `0.05%` 수준

즉 `document_id` 단위 split + 연도 홀드아웃을 쓰면 분할 누수는 상당 부분 제어 가능하다.

### 6.3 생성 규칙 과적합

큼.

이게 현재 셋의 가장 본질적인 문제다. 모델이 실질적으로 DataSynth 생성 규칙을 학습할 가능성이 높다.

## 7. 권장 사용 정책

### 7.1 즉시 가능한 운영 원칙

- Phase 1: 그대로 사용 가능
- Phase 2: 누수 컬럼 제거 후 제한적으로 사용
- Phase 3: 통합 테스트용으로 사용

### 7.2 학습/평가 규칙

- 학습 전 제거 컬럼
  - `is_fraud`
  - `fraud_type`
  - `is_anomaly`
  - `anomaly_type`
  - `sod_violation`
  - `sod_conflict_type`
- split 기준
  - row 단위 금지
  - `document_id` 단위 split 필수
  - 권장: `2022~2023 train`, `2024 test`

### 7.3 DataSynth 자체 개선 우선순위

상:

- 메타 파일과 실제 CSV row count 일치시키기
- 품질 집계 파일(`data_quality_stats.json`) 정상화
- 원장 본문에서 정답 컬럼 분리
- tax/cost_center/trading_partner coverage 보강

중:

- `user_persona` 등 보호 범주 오탈자 정책 재조정
- 연도별 process/source 분산 확대
- Phase 3용 자유 서술 텍스트 다양성 확대

하:

- 문서 템플릿 반복도 감소
- 불균형 전표 51건 정리

## 8. 최종 판단

현재 datasynth 2022~2024 셋은 다음처럼 보는 것이 가장 정확하다.

- "Phase 1 회귀/개발 검증 데이터"로는 강함
- "Phase 2 연구/실험 데이터"로는 제한적으로 유효
- "Phase 3 프로토타입 데이터"로는 충분
- "실데이터 일반화 성능을 증명하는 벤치마크"로 쓰기에는 약함

따라서 이 데이터는 폐기 대상은 아니지만, 사용 목적을 명확히 제한해야 한다. 특히 Phase 2 이상에서는 누수 제거, 문서 단위 split, 연도 홀드아웃, 실데이터 보완 검증이 전제되어야 한다.


## 9. 그래서?

 1. 정답 누수부터 막아야 합니다. ✅
     is_fraud, fraud_type, is_anomaly, anomaly_type, sod_violation, sod_conflict_type가 원장 본문에 같이 들어가 있으니, Phase 2 학습/평가에서
     는 이 컬럼들을 입력 피처에서 완전히 제거해야 합니다. 가능하면 아예 원천 데이터 구조를 원장 본문과 라벨로 물리적으로 분리하는 게 맞습니
     다.
  2. 평가 방식을 바꿔야 합니다. ✅
     지금 데이터는 생성 규칙이 Phase 1 룰과 너무 가까워서, 성능이 잘 나와도 실제 일반화 성능이라고 보기 어렵습니다. 그래서 row 단위 split은
     금지하고, 반드시 document_id 단위로 나누고, 권장안대로 2022~2023 train / 2024 test로 연도 홀드아웃 평가를 써야 합니다.
  3. 메타 파일 신뢰성을 복구해야 합니다. ✅
     문서상 실제 CSV 집계와 generation_statistics.json, data_quality_stats.json 숫자가 맞지 않습니다. 이건 리포트나 품질 근거를 바로 깨뜨리는
     문제라서 우선순위가 높습니다. 실제 CSV 기준으로 row 수, 결측, 중복, issue count를 다시 계산해서 메타 파일을 재생성해야 합니다.
  4. 피처 품질을 정리해야 합니다. ✅
     cost_center, tax_*, trading_partner, auxiliary_*는 결측이 너무 많고, user_persona는 오탈자 변형이 과도합니다. 그래서 학습 전에
     user_persona 정규화 규칙을 넣고, 결측 심한 컬럼들은 바로 다 쓰지 말고 ablation으로 유효성 확인 후 채택해야 합니다.

  우선순위로 줄이면 이렇습니다.

  - 상: 누수 컬럼 분리, document_id/연도 기준 평가로 변경, 메타 파일 재집계
  - 중: user_persona 정규화, 결측 심한 피처 사용 여부 재검토
  - 하: 템플릿 반복 감소, 불균형 전표 51건 정리

  용도 판정도 같이 보면 됩니다.

  - Phase 1: 회귀 테스트/룰 엔진 검증용으로 그대로 사용 가능
  - Phase 2: 누수 제거 + 올바른 split 전제일 때만 제한적으로 사용
  - Phase 3: UI/리포트/설명 체인 테스트용으로 사용 가능
  - 부적합: “실데이터 일반화 성능 증명용 벤치마크”

   이제 진짜 남은 것: DataSynth 수정 필요

  1. 희소 피처 coverage를 올려야 함
     지금 cost_center, tax_code, tax_amount, trading_partner, auxiliary_*가 너무 비어 있습니다.
     이건 프로젝트에서 자동 제외는 가능하지만, 원천적으로는 생성기에서 더 자주, 더 자연스럽게 채워줘야 합니다.
  2. user_persona 오탈자 정책을 줄여야 함
     현재는 typo 주입이 너무 강해서 사실상 같은 역할이 수백 개 값으로 찢어집니다.
     테스트용 노이즈는 일부 필요하지만, 생성기 단계에서 “보호된 canonical 값”과 “허용 typo 강도”를 분리하는 게 맞습니다.
  3. 템플릿 반복을 줄여야 함
     header_text, line_text, 설명성 텍스트가 반복 패턴에 너무 기대고 있습니다.
     Phase 3 UI 테스트는 되지만, 실제 설명/요약 품질 검증용으로는 다양성이 부족합니다.
  4. 불균형 전표 같은 품질 오류를 upstream에서 제거해야 함
     현재는 프로젝트에서 감지/경고는 가능하지만, 생성기에서 애초에 이상 전표를 만들지 않거나 의도적 anomaly와 일반 품질 오류를 분리해야 합니
     다.
  5. 생성 규칙이 Phase 1 룰과 너무 가까운 문제를 완화해야 함
     이게 제일 본질적입니다.
     지금 DataSynth는 룰 기반 탐지와 너무 비슷한 규칙으로 이상치를 만들기 때문에, Phase 2 성능이 잘 나와도 일반화 성능이라고 보기 어렵습니다.
     즉 anomaly/fraud 생성 로직을 더 다양화하고, 룰에 바로 걸리는 패턴 말고도 “애매하지만 수상한” 케이스를 늘려야 합니다.
