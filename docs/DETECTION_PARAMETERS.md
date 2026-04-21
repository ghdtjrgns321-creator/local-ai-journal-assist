# Detection Parameters

감사인이 룰 탐지 민감도, 예외 범위, 키워드, 승인 권한 기준을 조정할 때 참고하는 문서다.

## 어디서 고치나

`config/settings.py`
- 금액 기준
- 기간 기준
- 비율 기준
- Z-score
- 윈도우 크기

`config/audit_rules.yaml`
- 예외 허용
- review / immediate 분기
- 고위험 계정
- SoD 조합
- reversal keyword

`config/risk_keywords.yaml`
- 위험 적요 키워드

`data/.../master_data/employees.json`
- 승인권자별 승인 한도
- 승인 가능 여부

## 먼저 기억할 원칙

- 숫자 기준은 보통 `config/settings.py`에서 조정한다.
- 예외, 허용 범위, 키워드, 계정 목록은 보통 `config/audit_rules.yaml`에서 조정한다.
- `L1-04 승인한도 초과`는 공통 threshold보다 `approved_by`별 승인 한도가 더 중요하다.
- 회사별 차이는 전역 기본값을 직접 바꾸기보다 회사별/engagement별 override로 관리하는 게 맞다.

## L1 파라미터

### L1-01 차대변 불균형

- 감사인이 조정하는 값: 차대변 차이 허용 금액
  - 실제 키: `balance_tolerance`
  - 기본값: `1.0`
  - 의미: 차대변 차이가 몇 원까지면 정상으로 볼지
  - 수정 위치: `config/settings.py`

### L1-02 필수필드 누락

- 현재 감사인이 따로 조정하는 숫자형 파라미터는 없다.
- 필수 컬럼 집합이 고정된 룰이다.

### L1-03 무효 계정

- 감사인이 조정하는 값: 유효 계정 기준표
  - 실제 키: `chart_of_accounts_path`
  - 기본값: `config/chart_of_accounts.csv`
  - 의미: 어떤 CoA 파일을 기준으로 유효/무효 계정을 판단할지
  - 수정 위치: `config/settings.py`

### L1-04 승인한도 초과

- 감사인이 조정하는 값: 승인권자별 승인 금액 한도
  - 실제 필드: `approval_limit`
  - 의미: 각 승인자가 얼마까지 승인할 수 있는지 정하는 값
  - 수정 위치: `employees.json`

- 감사인이 조정하는 값: 승인 가능한 사용자 여부
  - 실제 필드: `can_approve_je`
  - 의미: 이 사용자를 승인권자로 인정할지 여부
  - 수정 위치: `employees.json`

- 해석
  - `L1-04`는 전표를 실제로 승인한 사람 `approved_by`의 한도를 본다.
  - 전표 총액이 그 승인자의 승인 금액 한도를 넘으면 탐지한다.

### L1-05 자기승인

- 감사인이 조정하는 값: 시스템 자동처리 self-approval 허용 대상
  - 실제 키: `patterns.self_approval_allow.user_personas`
  - 기본값: `automated_system`
  - 의미: 시스템 계정 self-approval를 예외로 허용할지
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 자동처리로 인정할 source
  - 실제 키: `patterns.self_approval_allow.sources`
  - 기본값: `automated`
  - 의미: 어떤 source를 자동처리로 볼지
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 검토 필요로 분류할 프로세스
  - 실제 키: `patterns.self_approval_review.business_processes`
  - 기본값: `R2R`, `A2R`
  - 의미: 즉시 위반이 아니라 review로 둘 프로세스
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 큰 금액 self-approval 승격 기준
  - 실제 키: `patterns.self_approval_immediate_override.materiality_amount`
  - 기본값: `1_000_000_000`
  - 의미: 이 금액 이상이면 review가 아니라 immediate로 승격
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 고액 self-approval에 적용할 수기 source
  - 실제 키: `patterns.self_approval_immediate_override.manual_sources`
  - 기본값: `manual`, `adjustment`
  - 의미: 어떤 source를 사람 직접 처리로 볼지
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 자기승인을 바로 위반으로 볼 고위험 계정
  - 실제 키: `patterns.self_approval_immediate_override.high_risk_accounts`
  - 기본값: `1190`, `2190`
  - 의미: 가수금, 가계정처럼 self-approval를 더 엄격히 볼 계정
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 자기승인을 바로 위반으로 볼 고위험 계정 접두사
  - 실제 키: `patterns.self_approval_immediate_override.high_risk_account_prefixes`
  - 기본값: `111`, `112`, `113`
  - 의미: 현금성 계정을 prefix 단위로 묶어서 관리할 때 사용
  - 수정 위치: `config/audit_rules.yaml`

### L1-06 직무분리 위반

- 감사인이 조정하는 값: 같이 맡으면 안 되는 프로세스 조합
  - 실제 키: `patterns.sod_toxic_pairs`
  - 기본값: YAML 기본 쌍
  - 의미: 같은 사용자가 동시에 맡으면 안 되는 프로세스 조합
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: junior가 동시에 맡을 수 있는 프로세스 수
  - 실제 키: `patterns.sod_role_thresholds.junior_accountant`
  - 기본값: `1`
  - 의미: junior 권한 상 허용 범위
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: senior가 동시에 맡을 수 있는 프로세스 수
  - 실제 키: `patterns.sod_role_thresholds.senior_accountant`
  - 기본값: `3`
  - 의미: senior 권한 상 허용 범위
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 프로세스 수 기준 fallback 임계
  - 실제 키: `sod_process_threshold`
  - 기본값: `3`
  - 의미: role별 상세 기준이 없을 때 몇 개 프로세스부터 위반으로 볼지
  - 수정 위치: `config/settings.py`

### L1-07 승인 생략

- 감사인이 조정하는 값: 사람 처리로 볼 source 코드
  - 실제 키: `patterns.manual_source_codes`
  - 기본값: `Manual`, `Adjustment`
  - 의미: 자동처리가 아닌 승인 필요 전표로 볼 source
  - 수정 위치: `config/audit_rules.yaml`

- 관련 마스터: 승인권자 한도와 승인 가능 여부
  - 실제 필드: `approval_limit`, `can_approve_je`
  - 의미: 승인 자체가 필요한지와 승인자가 적정한지에 간접 영향
  - 수정 위치: `employees.json`

### L1-08 기간 불일치

- 현재 감사인이 따로 조정하는 숫자형 파라미터는 없다.
- 회계기간과 전기일자 월이 맞는지만 고정 비교한다.

## L2 파라미터

### L2-01 승인한도 직하

- 감사인이 조정하는 값: 승인한도 단계
  - 실제 키: `approval_thresholds`
  - 기본값: `[10M, 100M, 1B, 5B, 10B, 50B]`
  - 의미: 어느 금액 구간을 기준으로 승인권한 단계를 나눌지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 얼마나 가까우면 직하로 볼지
  - 실제 키: `near_threshold_ratio`
  - 기본값: `0.90`
  - 의미: 한도의 몇 % 이상이면 `JustBelowThreshold`로 볼지
  - 수정 위치: `config/settings.py`

### L2-02 중복 지급

- 감사인이 조정하는 값: 며칠 안의 같은 지급을 중복으로 볼지
  - 실제 키: `duplicate_payment_window_days`
  - 기본값: `30`
  - 의미: 같은 거래처/금액 조합을 며칠 이내면 중복 지급으로 볼지
  - 수정 위치: `config/settings.py`

### L2-03 중복 전표

- 현재 감사인이 따로 조정하는 숫자형 파라미터는 없다.
- 같은 계정, 같은 금액, 같은 일자면 exact duplicate로 본다.

### L2-04 비용 자산화

- 현재 감사인이 따로 조정하는 숫자형 파라미터는 없다.
- `15xx` 차변 + `6xxx` 대변 조합을 기준으로 본다.

### L2-05 Top-side JE

- 감사인이 조정하는 값: High 승격 점수 기준
  - 실제 키: `topside_threshold`
  - 기본값: `2`
  - 의미: 가점 합계가 몇 점 이상이면 High로 올릴지
  - 수정 위치: `config/settings.py`

### L2-06 역분개

- 감사인이 조정하는 값: 1:1 역분개 매칭 허용 일수
  - 실제 키: `reversal_match_window_days`
  - 기본값: `1`
  - 의미: 며칠 차이까지 같은 reversal pair로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 분할 역분개 탐지 윈도우
  - 실제 키: `reversal_rolling_window_days`
  - 기본값: `7`
  - 의미: N:M reversal을 며칠 범위 안에서 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 순액 0 허용 오차
  - 실제 키: `reversal_zero_threshold`
  - 기본값: `1000.0`
  - 의미: reversal끼리 상계한 결과를 얼마까지 0으로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: reversal 최종 점수 기준
  - 실제 키: `reversal_score_threshold`
  - 기본값: `0.3`
  - 의미: reversal 종합 점수가 몇 점 이상이면 flag할지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: reversal에서 제외할 정상 정산 계정
  - 실제 키: `patterns.reversal_exclude_accounts`
  - 기본값: `2900`, `1150`, `2050`
  - 의미: 정상 clearing/IC 정산 계정은 오탐 방지 차원에서 제외
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: reversal 적요 키워드
  - 실제 키: `patterns.reversal_keywords`
  - 기본값: YAML 기본 목록
  - 의미: 정정, 취소, reversal 같은 표현을 얼마나 넓게 볼지
  - 수정 위치: `config/audit_rules.yaml`

## L3 파라미터

### L3-02 수기 전표

- 감사인이 조정하는 값: 수기로 볼 source 코드
  - 실제 키: `patterns.manual_source_codes`
  - 기본값: `Manual`, `Adjustment`
  - 의미: 어떤 source를 사람이 직접 입력한 전표로 볼지
  - 수정 위치: `config/audit_rules.yaml`

### L3-03 관계사 순환거래

- 감사인이 조정하는 값: 관계사 계정 쌍
  - 실제 키: `patterns.intercompany.pairs`
  - 기본값: `1150↔2050`, `4500↔2700`
  - 의미: 어떤 계정쌍을 관계사 receivable/payable, revenue/accrual로 볼지
  - 수정 위치: `config/audit_rules.yaml`

### L3-04 기말 대규모

- 감사인이 조정하는 값: 월말 전후 몇 일을 기말로 볼지
  - 실제 키: `period_end_margin_days`
  - 기본값: `5`
  - 의미: 기말 전표 범위를 얼마나 넓게 잡을지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 어느 분위수부터 고액으로 볼지
  - 실제 키: `period_end_amount_quantile`
  - 기본값: `0.75`
  - 의미: 계정그룹별 상위 몇 % 금액부터 기말 대규모로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 분위수 계산 최소 표본 수
  - 실제 키: `c01_min_group_size`
  - 기본값: `30`
  - 의미: 표본이 너무 적은 계정그룹에서 과탐이 나지 않게 하는 최소 기준
  - 수정 위치: `config/settings.py`

### L3-05 주말 전기

- 감사인이 조정하는 값: 회사 자체 휴일 목록
  - 실제 키: `custom_holidays`
  - 기본값: `[]`
  - 의미: 공휴일 외에 회사 휴무일도 같이 주말성 전기로 볼지
  - 수정 위치: `config/settings.py`

### L3-06 심야 전기

- 감사인이 조정하는 값: 심야 시작 시각
  - 실제 키: `midnight_start`
  - 기본값: `22`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 심야 종료 시각
  - 실제 키: `midnight_end`
  - 기본값: `6`
  - 수정 위치: `config/settings.py`

### L3-07 소급 전기

- 감사인이 조정하는 값: 전기일자와 문서일자가 며칠 이상 차이나면 소급으로 볼지
  - 실제 키: `backdated_threshold_days`
  - 기본값: `30`
  - 수정 위치: `config/settings.py`

### L3-08 위험 적요

- 감사인이 조정하는 값: 너무 짧다고 볼 적요 길이
  - 실제 키: `min_description_length`
  - 기본값: `3`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 어휘 다양성 하한
  - 실제 키: `ttr_threshold`
  - 기본값: `0.3`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 엔트로피 하한
  - 실제 키: `entropy_threshold`
  - 기본값: `1.0`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 고위험 / 중위험 적요 키워드
  - 실제 키: `high_risk`, `medium_risk`
  - 기본값: YAML 기본 목록
  - 의미: 어떤 단어를 위험 적요로 볼지
  - 수정 위치: `config/risk_keywords.yaml`

### L3-09 가수금 / 미결 계정

- 감사인이 조정하는 값: suspense로 볼 적요 키워드
  - 실제 키: `patterns.suspense_keywords`
  - 기본값: YAML 기본 목록
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: suspense로 볼 계정 코드
  - 실제 키: `patterns.suspense_account_codes`
  - 기본값: `1190`, `1290`, `2190`, `2900`, `9990`
  - 수정 위치: `config/audit_rules.yaml`

## L4 파라미터

### L4-01 매출 이상 변동

- 감사인이 조정하는 값: 매출 Z-score 기준
  - 실제 키: `zscore_threshold`
  - 기본값: `3.0`
  - 의미: 매출 계정에서 몇 sigma 이상을 이상치로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 매출 계정 접두사
  - 실제 키: `patterns.revenue_account_prefixes`
  - 기본값: `4`
  - 의미: 어떤 계정 prefix를 매출 계정으로 볼지
  - 수정 위치: `config/audit_rules.yaml`

### L4-02 Benford 위반

- 감사인이 조정하는 값: MAD 기준
  - 실제 키: `benford_mad_threshold`
  - 기본값: `0.012`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 최소 표본 수
  - 실제 키: `benford_min_sample`
  - 기본값: `100`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 카이제곱 유의수준
  - 실제 키: `benford_chi2_alpha`
  - 기본값: `0.05`
  - 수정 위치: `config/settings.py`

### L4-03 이상 고액

- 감사인이 조정하는 값: 금액 이상치 Z-score 기준
  - 실제 키: `zscore_threshold`
  - 기본값: `3.0`
  - 수정 위치: `config/settings.py`

### L4-04 비정상 계정조합

- 감사인이 조정하는 값: 얼마나 드문 조합이면 희소 조합으로 볼지
  - 실제 키: `account_pair_rare_percentile`
  - 기본값: `0.01`
  - 수정 위치: `config/settings.py`

### L4-05 비정상 시간대 집중

- 감사인이 조정하는 값: 사용자별 시간대 이상치 sigma
  - 실제 키: `abnormal_sigma_threshold`
  - 기본값: `3.0`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 너무 빨리 승인됐다고 볼 시간
  - 실제 키: `rapid_approval_minutes`
  - 기본값: `5`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 최소 비정상 비율
  - 실제 키: `min_abnormal_ratio`
  - 기본값: `0.1`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 최소 심야 건수
  - 실제 키: `min_midnight_entries`
  - 기본값: `3`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 사용자별 최소 표본 수
  - 실제 키: `min_user_entries`
  - 기본값: `10`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 자동 전표로 볼 source
  - 실제 키: `auto_entry_sources`
  - 기본값: `batch`, `interface`, `system`, `BATCH`, `IF`, `SYS`
  - 수정 위치: `config/settings.py`

### L4-06 배치 전표 이상

- 감사인이 조정하는 값: 배치 전표 source
  - 실제 키: `batch_source_values`
  - 기본값: `batch`, `BATCH`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 배치 전표 기말 집중 비율
  - 실제 키: `batch_period_end_ratio`
  - 기본값: `0.5`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 동일일자 동시 생성 건수 기준
  - 실제 키: `batch_simultaneous_threshold`
  - 기본값: `50`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 배치 내부 금액 이상치 Z-score
  - 실제 키: `batch_amount_zscore`
  - 기본값: `3.0`
  - 수정 위치: `config/settings.py`

## Variance / Trend / TimeSeries

### D01 계정 집계 변동

- 감사인이 조정하는 값: 전기 대비 변동률 기준
  - 실제 키: `variance_threshold`
  - 기본값: `0.5`
  - 수정 위치: `config/settings.py`

### D02 월별 패턴 변동

- 감사인이 조정하는 값: 월별 패턴 차이 기준
  - 실제 키: `monthly_pattern_threshold`
  - 기본값: `0.3`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 최소 비교 월 수
  - 실제 키: `min_monthly_data_months`
  - 기본값: `3`
  - 수정 위치: `config/settings.py`

### TB01 / TB02 추세 이탈

- 감사인이 조정하는 값: 최소 비교 기간 수
  - 실제 키: `trendbreak_min_periods`
  - 기본값: `2`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 같은 방향 추세 비율
  - 실제 키: `trendbreak_bias_ratio`
  - 기본값: `0.8`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 극단 구간 분위수
  - 실제 키: `trendbreak_extremity_quantile`
  - 기본값: `0.1`
  - 수정 위치: `config/settings.py`

### TS01 / TS02 시계열 집중

- 감사인이 조정하는 값: 거래 급증 윈도우
  - 실제 키: `burst_window_days`
  - 기본값: `7`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 급증 sigma 기준
  - 실제 키: `burst_sigma`
  - 기본값: `3.0`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 빈도 집중 윈도우
  - 실제 키: `frequency_window_days`
  - 기본값: `7`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 최소 거래 건수
  - 실제 키: `frequency_min_count`
  - 기본값: `5`
  - 수정 위치: `config/settings.py`

## Relational / IC / Graph / Evidence / Access Audit

### Relational

- 감사인이 조정하는 값: 신규 거래처 중 대액 기준
  - 실제 키: `rel_new_cp_large_quantile`
  - 기본값: `0.90`

- 감사인이 조정하는 값: 신규 거래처 lookback 기간
  - 실제 키: `rel_new_cp_lookback_days`
  - 기본값: `90`

- 감사인이 조정하는 값: 휴면 판정 기간
  - 실제 키: `rel_dormant_inactive_days`
  - 기본값: `180`

- 감사인이 조정하는 값: 재활성화 탐지 윈도우
  - 실제 키: `rel_dormant_reactivation_window_days`
  - 기본값: `7`

- 감사인이 조정하는 값: IC 가격 편차 허용 비율
  - 실제 키: `rel_tp_ic_deviation_threshold`
  - 기본값: `0.15`

- 수정 위치: `config/settings.py`

### IC Matching

- 감사인이 조정하는 값: 금액 허용 오차
  - 실제 키: `ic_amount_tolerance`
  - 기본값: `0.02`

- 감사인이 조정하는 값: 날짜 허용 범위
  - 실제 키: `ic_date_window_days`
  - 기본값: `5`

- 수정 위치: `config/settings.py`

### Graph

- 감사인이 조정하는 값: 최대 cycle 길이
  - 실제 키: `graph_gr01_max_cycle_length`
  - 기본값: `5`

- 감사인이 조정하는 값: 그래프에 올릴 최소 금액
  - 실제 키: `graph_gr01_min_amount`
  - 기본값: `10_000_000`

- 감사인이 조정하는 값: 최대 edge 수
  - 실제 키: `graph_gr01_max_edges`
  - 기본값: `50_000`

- 수정 위치: `config/settings.py`

### Evidence

- 감사인이 조정하는 값: 적격증빙 필요 금액
  - 실제 키: `ev_tax_threshold`
  - 기본값: `30_000`

- 감사인이 조정하는 값: 분할 의심 상한 금액
  - 실제 키: `ev_split_max_amount`
  - 기본값: `29_000`

- 감사인이 조정하는 값: 분할 의심 최소 건수
  - 실제 키: `ev_split_min_count`
  - 기본값: `3`

- 감사인이 조정하는 값: 매출 / 비용 cutoff 허용일수
  - 실제 키: `ev_revenue_cutoff_days`, `ev_expense_cutoff_days`
  - 기본값: `5`, `7`

- 수정 위치: `config/settings.py`

### Access Audit

- 감사인이 조정하는 값: 고액 수정 기준 분위수
  - 실제 키: `aa01_high_amount_quantile`
  - 기본값: `0.90`

- 감사인이 조정하는 값: 승인 지연 허용 일수
  - 실제 키: `aa04_max_delay_days`
  - 기본값: `3`

- 감사인이 조정하는 값: 접근감사 기준 승인 지연 일수
  - 실제 키: `access_audit.approval_delay_days`
  - 기본값: `3`
  - 수정 위치: `config/audit_rules.yaml`

## 자주 조정하는 항목

### 승인 룰이 너무 많이 뜰 때

- 승인권자별 승인 금액 한도
- 승인한도 단계
- 승인한도 직하 비율

### 주말 / 심야 룰이 과탐일 때

- 회사 휴일 목록
- 심야 시작 / 종료 시각
- 자동 전표 source 목록

### 중복 지급이 과탐일 때

- 중복으로 볼 날짜 범위
- 금액 허용 오차

### 적요 룰이 약할 때

- 고위험 적요 키워드
- 중위험 적요 키워드
- suspense keyword
- reversal keyword

### 기말 대규모가 너무 많을 때

- 기말 판단 범위
- 고액 분위수
- 최소 표본 수

### Benford가 과민할 때

- MAD 기준
- 최소 표본 수

## 변경 권장 방식

- 회사 고유 정책은 회사별 override로 관리한다.
- 계약별 튜닝은 engagement override로 관리한다.
- 임시 실험은 UI runtime override로 먼저 시험한다.
- 승인권자 한도 변경은 반드시 `employees.json` 또는 회사 마스터 기준으로 관리한다.
