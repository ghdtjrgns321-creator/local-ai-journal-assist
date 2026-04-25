# Detection Parameters

감사인이 룰 탐지 민감도, 예외 범위, 키워드, 승인 권한 기준을 조정할 때 참고하는 문서다.
문서 저장 인코딩은 `UTF-8`을 기준으로 유지한다.

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

## 전수조사 기준과 남은 검증 계획

이 문서는 아래 네 가지를 기준으로 룰별 파라미터를 전수 대조한다.

- `docs/DETECTION_RULES.md`의 L1~L4, D01/D02 룰 목록
- `config/settings.py`의 `AuditSettings` 파라미터
- `config/audit_rules.yaml`, `config/risk_keywords.yaml`, `config/phase1_case.yaml`
- `src/detection/*`, `src/feature/*`에서 실제로 참조하는 설정 키

룰 확정 전 검증은 아래 순서로 진행한다.

| 단계 | 검증 내용 | 산출물 |
|---|---|---|
| 1 | 룰별 파라미터 누락 여부 대조 | 이 문서의 룰별 파라미터 표 보강 |
| 2 | 감사인 체크리스트 필수 항목 분리 | 온보딩 체크리스트 후보 |
| 3 | `auditor_tunable`과 `system_default` 분리 | UI 설정 화면 노출 정책 |
| 4 | 샘플 데이터로 룰별 hit와 case priority 검증 | High/Medium/Low 샘플 리뷰 |
| 5 | 과탐/미탐 원인별 튜닝 후보 정리 | Theme별 튜닝 가이드 |

이번 전수조사에서 보강/정리한 항목:

- `L1-09 승인일 누락` 파라미터/체크리스트 설명 추가
- `L2-03 중복 전표`의 fuzzy/split/time-window 세부 파라미터 추가
- `L2-04 비용 자산화`의 금액 허용오차, 최소금액, review/immediate threshold 추가
- `L3-10 고위험 계정 사용`을 L3 섹션 안으로 이동 또는 참조 정리
- `L3-11 매출 컷오프`의 cutoff 허용일수, 기말 가중, 최대 차이일수, 영업일 계산 여부 추가
- `L4-03 이상 고액`의 전역 금액 분위수 가드 `l403_min_amount_quantile` 추가
- `L4-05 비정상 시간대 집중`의 정상근무시간/결산 집중기간 파라미터 추가
- `IC01~IC03`, `GR01/GR03`, EV/AA/TB/TS 계열은 Phase 1 보조 finding 또는 후속 단계로 UI 노출 범위를 별도 확정

## 먼저 기억할 원칙

- 숫자 기준은 보통 `config/settings.py`에서 조정한다.
- 예외, 허용 범위, 키워드, 계정 목록은 보통 `config/audit_rules.yaml`에서 조정한다.
- `L1-04 승인한도 초과`는 공통 threshold보다 `approved_by`별 승인 한도가 더 중요하다.
- 회사별 차이는 전역 기본값을 직접 바꾸기보다 회사별/engagement별 override로 관리하는 게 맞다.

## 파라미터 UX 분류

모든 파라미터를 UI에 같은 방식으로 노출하지 않는다. 감사인이 engagement 시작 전에 확정해야 하는 값, 반복 결과를 보며 조정할 값, 시스템 내부값을 분리한다.

| 분류 | 의미 | UI 처리 |
|---|---|---|
| `auditor_checklist_required` | engagement 시작 전에 감사인이 체크리스트로 확정해야 하는 값 | 온보딩 체크리스트로 노출 |
| `auditor_tunable` | 기본값으로 실행 가능하지만 결과를 보며 감사인이 조정할 수 있는 값 | 설정 화면의 고급/룰별 튜닝으로 노출 |
| `system_default` | 제품 기본값 또는 개발자 검증용 값. 일반 감사인이 직접 만질 필요가 낮음 | 기본 숨김, 개발자/관리자 모드에서만 노출 |

필수 체크리스트 파라미터는 아래 원칙으로 관리한다.

- 회사 정책, 감사 범위, 마스터 데이터 없이는 시스템이 합리적으로 추정할 수 없는 값은 `auditor_checklist_required`로 둔다.
- 과탐/미탐 조정용 민감도 값은 기본값으로 먼저 실행하고, 결과 리뷰 후 `auditor_tunable`로 조정한다.
- 통계 모델 안정성, 성능 제한, 내부 fallback 값은 `system_default`로 둔다.

### 감사인 체크리스트 필수 항목

| 체크리스트 항목 | 연결 파라미터 | 필요한 이유 |
|---|---|---|
| 회사의 월마감/분기마감/연마감 기준일과 마감 후 허용 기간은? | `period_end_margin_days`, `phase1_case.period_end_window_days` | L3-04, 결산 Theme, Top-side 후보 기준 |
| 승인권자별 승인 한도와 승인 가능 사용자는? | `employees.json.approval_limit`, `can_approve_je` | L1-04, L1-05, L1-07 판단의 기준 |
| 자동/배치/수기 전표 source 코드는 무엇인가? | `patterns.manual_source_codes`, `auto_entry_sources`, `batch_source_values` | L3-02, L4-05, L4-06, self-approval 예외 판단 |
| 회사의 근무 캘린더, 휴무일, 교대/야간 근무 정책은? | `custom_holidays`, `midnight_start`, `midnight_end` | L3-05, L3-06, L4-05 오탐 관리 |
| 회사 CoA에서 매출, 현금성, 가계정, 민감 계정, 관계사 계정은 무엇인가? | `revenue_account_prefixes`, `high_risk_account_use`, `suspense_account_codes`, `intercompany.pairs` | L3-03, L3-09, L3-10, L4-01, 관계사 Theme |
| 수행중요성 또는 내부 검토 기준 금액은? | `self_approval_immediate_override.materiality_amount`, graph/evidence 최소 금액류 | 고액 self-approval, graph/evidence 후보 우선순위 |

### UI 노출 원칙

- 첫 실행 전 온보딩에서는 `auditor_checklist_required`만 체크리스트로 노출한다.
- 첫 실행 후 결과 화면에서는 과탐이 많은 Theme 기준으로 관련 `auditor_tunable`만 추천한다.
- 설정 화면은 `업무 정책`, `계정/마스터`, `기간/캘린더`, `민감도/통계`, `노출/큐` 탭으로 나눈다.
- 각 파라미터에는 “영향받는 룰”, “기본값”, “너무 낮출 때 위험”, “너무 높일 때 위험”을 함께 보여준다.

### 감사인 기본 UI에 남길 항목

감사인 기본 UI는 회사 정책과 업무 맥락을 입력하는 화면이어야 한다. 통계 임계값이나 알고리즘 세부값을 기본 화면에 노출하지 않는다.

#### 1. 감사인 체크리스트

| UI 그룹 | 감사인이 확인/입력할 항목 | 대표 파라미터 |
|---|---|---|
| 승인 정책 | 승인권자별 한도, 승인 가능 사용자 | `employees.json.approval_limit`, `can_approve_je` |
| 마감 일정 | 월마감/분기마감/연마감 기준일, 마감 후 허용 기간 | `period_end_margin_days`, `phase1_case.period_end_window_days` |
| 전표 source 코드 | 수기, 자동, 배치/interface source 코드 | `patterns.manual_source_codes`, `auto_entry_sources`, `batch_source_values` |
| 근무 캘린더 | 회사 휴일, 정상 근무시간, 심야 기준 | `custom_holidays`, `normal_hours_start`, `normal_hours_end`, `midnight_start`, `midnight_end` |
| 계정/CoA 정의 | 매출, 현금성, 가계정, 민감 계정, 관계사 계정 | `revenue_account_prefixes`, `high_risk_account_use.*`, `suspense_account_codes`, `intercompany.pairs` |
| SoD 정책 | 같이 맡으면 안 되는 프로세스 조합, role별 허용 범위 | `patterns.sod_toxic_pairs`, `patterns.sod_role_thresholds` |
| 적요/예외 키워드 | 위험 적요, 정상 예외, suspense/reversal 키워드 | `risk_keywords.yaml`, `suspense_keywords`, `reversal_keywords`, `process_allowed_keywords` |
| Cutoff 정책 | 매출 cutoff 허용일수, 영업일 기준 사용 여부 | `ev_revenue_cutoff_days`, `ev_cutoff_use_business_days` |
| 중요성 기준 | 고액 self-approval 승격 기준, graph/evidence 최소 금액 | `self_approval_immediate_override.materiality_amount`, 금액 floor류 |

#### 2. 결과를 보며 조정할 수 있는 설정

아래 값은 기본값으로 먼저 실행한 뒤, 결과 화면에서 과탐/미탐이 확인될 때만 조정한다.

| UI 그룹 | 조정 항목 | 대표 파라미터 |
|---|---|---|
| 중복/역분개 민감도 | 중복 지급 기간, 분할/시차 중복 기간, 역분개 매칭 기간 | `duplicate_payment_window_days`, `duplicate_split_window_days`, `duplicate_time_window_days`, `reversal_match_window_days`, `reversal_rolling_window_days` |
| 승인 직하 민감도 | 승인한도에 얼마나 가까우면 직하로 볼지 | `near_threshold_ratio` |
| 기말 대규모 민감도 | 고액 분위수, 최소 표본 수 | `period_end_amount_quantile`, `c01_min_group_size` |
| 적요 품질 민감도 | 최소 길이, 어휘 다양성, 엔트로피 | `min_description_length`, `ttr_threshold`, `entropy_threshold` |
| Benford 민감도 | MAD 기준, 최소 표본 수 | `benford_mad_threshold`, `benford_min_sample` |
| 큐 노출 | 전체 상위 case 수, theme별 case 수 | `phase1_case.top_n_cases`, `phase1_case.top_n_per_theme` |
| Priority band | High/Medium 경계 | `phase1_case.priority_band.high`, `phase1_case.priority_band.medium` |

#### 3. 감사인 기본 UI에서 숨길 항목

아래 값은 관리자/개발자 모드에 둔다. 감사인이 직접 조정하면 결과 재현성과 해석 일관성이 흔들릴 수 있다.

| 숨김 그룹 | 대표 파라미터 |
|---|---|
| 통계 내부 임계값 | `zscore_threshold`, `l403_min_amount_quantile`, `abnormal_sigma_threshold`, `min_abnormal_ratio`, `min_user_entries`, `variance_threshold`, `monthly_pattern_threshold`, `trendbreak_*`, `burst_sigma` |
| 내부 score threshold | `expense_capitalization_review_threshold`, `expense_capitalization_immediate_threshold`, `reversal_score_threshold`, `topside_threshold` |
| 성능/안전장치 | `duplicate_max_group_size`, `graph_gr01_max_edges`, `graph_gr01_max_component_size`, `graph_gr01_max_component_edges` |
| 알고리즘 세부값 | `ic_max_diff_ratio`, `ic_max_day_diff`, `ev_cutoff_period_end_weight`, `ev_cutoff_max_day_diff`, `nlp_*`, `shap_*`, `vae_*`, `if_*`, `bilstm_*` |
| Case scoring 내부 가중치 | `phase1_case.priority_weights.*`, `phase1_case.evidence_type_cap`, `phase1_case.rule_repeat_scale`, `phase1_case.priority_adjustments.*` |

정리하면 감사인 기본 UI는 **체크리스트 + 업무 설정 + 결과 기반 튜닝**만 제공한다. 통계/모델/성능/스코어 내부값은 기본 UI에서 숨기고, 관리자 모드에서 변경 이력과 함께 관리한다.

## PHASE1 리모델링 파라미터

이 섹션은 개별 룰 민감도와 별개로, **PHASE1 결과를 케이스 중심으로 묶고 우선순위화할 때 사람이 조정할 수 있는 값**을 정리한다.

### 설정 파일 소속 원칙

- PHASE1 케이스화와 우선순위화에 필요한 전용 설정은 **신설 예정인** `config/phase1_case.yaml` 소속으로 본다.
- 이유:
  - `config/settings.py`는 전역 수치 threshold와 공통 계산 파라미터에 가깝다.
  - `config/audit_rules.yaml`은 개별 탐지 룰의 허용/예외/분기 규칙에 가깝다.
  - `phase1_case.*`는 룰 계산 이후의 case grouping, scoring, exposure 정책이라 별도 파일로 분리하는 편이 가장 명확하다.
- 단, 기존 공통 키와 의미가 완전히 같은 값은 중복 신설하지 않고 기존 키를 재사용한다.

### 기존 키 재사용 vs PHASE1 전용 키

- `period_end_window_days`
  - 방침: **기존 `period_end_margin_days` 재사용**
  - 이유: 둘 다 월말/기말 윈도우를 뜻하므로 중복 정의를 피하는 편이 낫다.
  - 문서상 `phase1_case.period_end_window_days`는 개념 설명용 이름이며, 실제 구현은 기존 키를 우선 single source of truth로 둔다.

- `near_period_days`
  - 방침: **`phase1_case` 전용 키 신설**
  - 이유: 중복/유출 case grouping용 근접기간은 기존 공통 설정과 직접 대응되는 키가 없다.

- `top_n_cases`
  - 방침: **`phase1_case` 전용 키 신설**
  - 이유: 탐지 로직이 아니라 UI/리포트 노출 정책이므로 기존 룰 threshold와 분리하는 편이 맞다.

- `top_n_per_theme`
  - 방침: **`phase1_case` 전용 키 신설**
  - 이유: theme queue 노출 정책은 PHASE1 case presentation에만 해당한다.

### Theme / Secondary Tag

- 감사인이 조정하는 값: secondary tag 부여 최소 점수
  - 권장 키: `phase1_case.secondary_tag_min_score`
  - 기본값: `0.40`
  - 의미: primary가 아닌 evidence type score가 이 값 이상일 때만 secondary tag 부여
  - 현재 문서 기준값: [DETECTION_RULES.md](DETECTION_RULES.md) `2.0.2`

### Theme별 Case Key 템플릿

- 감사인이 조정하는 값: 거래처 식별 우선순위
  - 권장 키: `phase1_case.counterparty_columns`
  - 기본값: `auxiliary_account_number`, `vendor_name`, `customer_name`
  - 의미: 지급/중복/유출 테마에서 어떤 컬럼을 거래처 대표값으로 쓸지
  - fallback 순서:
    - `auxiliary_account_number`가 있으면 사용
    - 없으면 `vendor_name`
    - 없으면 `customer_name`
    - 전부 없으면 `UNKNOWN_COUNTERPARTY`

- 감사인이 조정하는 값: 계정군 파생 기준
  - 권장 키: `phase1_case.account_family_strategy`
  - 기본값: `first_digit`
  - 의미: `gl_account`를 어떤 규칙으로 계정군(account family)으로 묶을지
  - fallback 순서:
    - `account_family` 파생 컬럼이 있으면 우선 사용
    - 없으면 `gl_account`의 `first_digit`
    - 그것도 불가하면 `gl_account` prefix 2~3자리
    - 전부 불가하면 `UNKNOWN_ACCOUNT_FAMILY`

- 감사인이 조정하는 값: 근접기간 윈도우
  - 권장 키: `phase1_case.near_period_days`
  - 기본값: `7`
  - 의미: `posting_date ± n일`에서 같은 묶음으로 볼 기간 범위

- 감사인이 조정하는 값: 월말 윈도우
  - 권장 키: `phase1_case.period_end_window_days`
  - 기본값: `5`
  - 의미: 결산/기말 조정 테마에서 월말 ± 며칠을 같은 윈도우로 볼지
  - 실제 구현 우선 키: `period_end_margin_days` (`config/settings.py`)
  - 비고: 중복 키를 신설하지 않고 기존 공통 키를 재사용하는 것을 기본 방침으로 둔다.

- 감사인이 조정하는 값: 관계사 회사쌍 식별 컬럼
  - 권장 키: `phase1_case.intercompany_pair_columns`
  - 기본값: `company_code`, `trading_partner`
  - 의미: 관계사/연결 구조 이상 테마에서 회사쌍을 어떤 컬럼 조합으로 정의할지

- 감사인이 조정하는 값: 적재배치 식별 컬럼
  - 권장 키: `phase1_case.load_batch_columns`
  - 기본값: `upload_batch_id`
  - 의미: 데이터 무결성 붕괴 테마에서 적재배치를 어떤 컬럼으로 식별할지
  - fallback: 적재배치 컬럼이 없으면 실행 단위 배치 식별자를 사용

### Case Priority

- 감사인이 조정하는 값: control 가중치
  - 권장 키: `phase1_case.priority_weights.control`
  - 기본값: `0.35`

- 감사인이 조정하는 값: amount 가중치
  - 권장 키: `phase1_case.priority_weights.amount`
  - 기본값: `0.30`

- 감사인이 조정하는 값: logic 가중치
  - 권장 키: `phase1_case.priority_weights.logic`
  - 기본값: `0.20`

- 감사인이 조정하는 값: behavior 가중치
  - 권장 키: `phase1_case.priority_weights.behavior`
  - 기본값: `0.15`

- 원칙
  - 각 component score는 `0~1`로 정규화한다.
  - `repeat_score`는 직접 가산하지 않고 보정용으로만 쓴다.

### Priority Band

- 감사인이 조정하는 값: high cutoff
  - 권장 키: `phase1_case.priority_band.high`
  - 기본값: `0.75`

- 감사인이 조정하는 값: medium cutoff
  - 권장 키: `phase1_case.priority_band.medium`
  - 기본값: `0.45`

- 의미
  - `case_priority >= 0.75` → `high`
  - `case_priority >= 0.45` → `medium`
  - 그 외 → `low`

### Repeat 보정

- 감사인이 조정하는 값: repeat score 승격 기준
  - 권장 키: `phase1_case.repeat_score_promote`
  - 기본값: `0.70`
  - 의미: 이 값 이상이면 priority band를 한 단계 상향 가능

- 감사인이 조정하는 값: 반복 개월수 tie-breaker 기준
  - 권장 키: `phase1_case.repeat_months_tiebreak`
  - 기본값: `3`
  - 의미: 동일 case key가 3개월 이상 반복되면 같은 band 내 우선 정렬

### Evidence Type 상한

- 감사인이 조정하는 값: 동일 evidence type 최대 반영치
  - 권장 키: `phase1_case.evidence_type_cap`
  - 기본값: `1.0`
  - 의미: 한 케이스에서 같은 evidence type이 여러 번 나와도 최대 기여도는 1.0까지만 인정

- 감사인이 조정하는 값: 동일 룰 반복 완화 스케일
  - 권장 키: `phase1_case.rule_repeat_scale`
  - 기본값: `sqrt`
  - 의미: 동일 룰 반복을 선형 합산하지 않고 `sqrt` 또는 `log`로 완화

### 사용자 노출

- 감사인이 조정하는 값: 1차 화면 노출 case 수
  - 권장 키: `phase1_case.top_n_cases`
  - 기본값: `50`
  - 의미: 사용자 첫 화면에 보여줄 설정 가능한 상위 N개 케이스

- 감사인이 조정하는 값: theme별 노출 case 수
  - 권장 키: `phase1_case.top_n_per_theme`
  - 기본값: `10`
  - 의미: 각 theme queue에서 먼저 보여줄 case 개수

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

### L1-09 승인일 누락

- 현재 감사인이 따로 조정하는 숫자형 파라미터는 없다.
- 승인자가 있는데 승인일이 비어 있는지를 본다.

- 감사인 체크리스트
  - 승인일 로그가 ERP에서 별도 테이블로 관리되는지 확인한다.
  - `approved_by`와 `approval_date`가 같은 승인 workflow에서 나온 필드인지 확인한다.
  - 사후 승인 또는 일괄 승인 프로세스가 있다면 해당 프로세스의 정상 로그 위치를 확인한다.

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

- 감사인이 조정하는 값: 적요 유사도 기준
  - 실제 키: `duplicate_fuzzy_threshold`
  - 기본값: `80`
  - 의미: rapidfuzz 기준 몇 점 이상이면 유사 중복 후보로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 금액 허용 오차
  - 실제 키: `duplicate_amount_tolerance`
  - 기본값: `0.02`
  - 의미: 금액이 몇 % 이내로 가까우면 유사 중복/분할 후보로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 분할 거래 윈도우
  - 실제 키: `duplicate_split_window_days`
  - 기본값: `3`
  - 의미: 며칠 안에 쪼개진 전표를 분할 중복 후보로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 시차 중복 윈도우
  - 실제 키: `duplicate_time_window_days`
  - 기본값: `7`
  - 의미: 유사 전표가 며칠 안에 반복되면 시차 중복 후보로 볼지
  - 수정 위치: `config/settings.py`

- 시스템 내부값: 중복 그룹 최대 크기
  - 실제 키: `duplicate_max_group_size`
  - 기본값: `1000`
  - 의미: 너무 큰 그룹은 성능과 오탐 위험 때문에 스킵
  - UI 분류: `system_default`

### L2-04 비용 자산화

- 감사인이 조정하는 값: 자산 계정 prefix
  - 실제 키: `patterns.expense_capitalization.asset_account_prefixes`
  - 기본값: `15`
  - 의미: 어떤 계정 prefix를 자산 계정으로 볼지
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 비용 계정 prefix
  - 실제 키: `patterns.expense_capitalization.expense_account_prefixes`
  - 기본값: `5`, `6`, `7`, `8`
  - 의미: 어떤 계정 prefix를 비용 계정으로 볼지
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 정상 자산화 키워드
  - 실제 키: `patterns.expense_capitalization.normal_capitalization_keywords`
  - 의미: capex, project, construction처럼 정상 자산화 가능성을 낮추는 키워드
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 의심 비용 키워드
  - 실제 키: `patterns.expense_capitalization.suspicious_expense_keywords`
  - 의미: rent, repair, welfare처럼 비용 처리 성격이 강한 키워드
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값: 금액 허용 오차
  - 실제 키: `expense_capitalization_amount_tolerance`
  - 기본값: `0.02`
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 소액 제외 기준
  - 실제 키: `expense_capitalization_min_amount`
  - 기본값: `0.0`
  - 수정 위치: `config/settings.py`

- 시스템 내부값: review/immediate 점수 기준
  - 실제 키: `expense_capitalization_review_threshold`, `expense_capitalization_immediate_threshold`
  - 기본값: `0.45`, `0.75`
  - UI 분류: 기본 숨김, 관리자 모드에서만 노출

### L2-05 역분개

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

### L3-01 계정 분류 불일치

- 감사인이 조정하는 값 1: 이 프로세스에서 원래 잘 안 쓰는 계정 종류
  - 실제 키: `l3_01_misclassified_account.process_disallowed_categories`
  - 예: `P2P -> revenue`, `O2C -> expense`
  - 의미: "이 업무에서 이런 계정 성격이 나오면 한 번 보자"는 약한 안전망이다.
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값 2: 이 프로세스에서 특히 위험한 계정번호
  - 실제 키: `l3_01_misclassified_account.process_denied_accounts`
  - 예: `P2P -> 4100, 400650`, `TRE -> 1200, 1290`
  - 의미: 실무에서는 broad category보다 exact account가 더 잘 맞는 경우가 많다. 기본 운영에서는 이 값이 우선 판정 기준이다.
  - 수정 위치: `config/audit_rules.yaml`

- 감사인이 조정하는 값 3: 정상 예외로 자주 나오는 적요
  - 실제 키: `l3_01_misclassified_account.process_allowed_keywords`
  - 예: `O2C -> 매출에누리, 판매수수료, rebate`, `H2R -> 주식보상, 퇴직급여`, `TRE -> clearing, transfer`
  - 의미: 계정만 보면 어색하지만, `header_text`나 `line_text`에 이 표현이 있으면 정상 예외일 가능성이 높아 L3-01을 완화한다.
  - 기본값: 비움. 기본 세팅에서 recall을 깎으면 안 되기 때문에, engagement 중 반복 확인된 정상 예외만 선택적으로 넣는다.
  - 수정 위치: `config/audit_rules.yaml`

- 운영 원칙
  - 감사인이 실제로 관리할 값은 위 3개만 권장한다.
  - `process_denied_accounts`를 너무 넓게 넣으면 과탐이 급격히 늘어난다.
  - `process_allowed_keywords`는 길게 늘리지 말고, engagement 초기에 반복 확인된 정상 예외 표현만 짧게 유지하는 것이 맞다.
  - `R2R`은 기본 L3-01 범위에 억지로 넣지 않는 편이 낫다.

### L3-02 수기 전표

- 감사인이 조정하는 값: 수기로 볼 source 코드
  - 실제 키: `patterns.manual_source_codes`
  - 기본값: `Manual`, `Adjustment`
  - 의미: 어떤 source를 사람이 직접 입력한 전표로 볼지
  - 수정 위치: `config/audit_rules.yaml`

### L3-03 관계사 거래 검토 신호

- 감사인이 조정하는 값: 관계사 계정 쌍
  - 실제 키: `patterns.intercompany.pairs`
  - 기본값: `1150↔2050`, `4500↔2700`
  - 의미: 어떤 계정쌍을 관계사 receivable/payable, revenue/accrual로 보고 Phase 1 검토 후보로 올릴지
  - 수정 위치: `config/audit_rules.yaml`

### L3-04 기말/기초 대규모

- 운영 전제: 이 룰은 회사별 결산 일정이 정해져 있어야 실무적으로 쓸 수 있다. 시스템 기본값은 초안이며, 감사인/사용자가 engagement 시작 시 결산 윈도우를 확정해야 한다.

- 감사인이 조정하는 값: 월말 전후 몇 일을 기말로 볼지
  - 실제 키: `period_end_margin_days`
  - 기본값: `5`
  - 의미: 월말 전 며칠과 월초 며칠을 기말/기초 결산 전표 범위로 볼지
  - 수정 위치: `config/settings.py`
  - 감사인 체크리스트: 회사의 월마감/분기마감/연마감 일정에 맞춰 정한다. 예를 들어 D+3 마감 회사와 D+10 마감 회사는 같은 5일 기준을 쓰면 안 된다.

- 감사인이 조정하는 값: 어느 분위수부터 고액으로 볼지
  - 실제 키: `period_end_amount_quantile`
  - 기본값: `0.75`
  - 의미: 계정그룹별 상위 몇 % 금액부터 기말/기초 대규모로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 분위수 계산 최소 표본 수
  - 실제 키: `c01_min_group_size`
  - 기본값: `30`
  - 의미: 표본이 너무 적은 계정그룹에서 과탐이 나지 않게 하는 최소 기준
  - 수정 위치: `config/settings.py`

- 자동 반복 마감전표 downgrade
  - Phase 1 기본값은 사용자 whitelist가 아니라 자동 반복 패턴 downgrade다.
  - 같은 `company + source + document_type + business_process + gl_account + 월말/월초 구간`이 여러 달 반복되고 금액 변동이 작으면 반복 마감 패턴으로 보고 `L3-04` 플래그는 유지한 채 우선순위만 낮춘다.
  - hard exclude는 하지 않는다. 결산 반복전표에도 실제 오류·우회가 섞일 수 있기 때문이다.
  - 기존 DB `whitelist` 테이블은 `document_id + rule_code` 단위 사후 제외/검토 이력 저장용으로만 남겨 둔다. Phase 1 운영 기본전략은 아니다.

- Phase 1에서 유지/강화할 기준
  - 결산 일정 맞춤: `period_end_margin_days`를 회사 마감 캘린더에 맞춘다.
  - 자동 반복 마감전표 downgrade: 반복 패턴은 제외하지 않고 우선순위만 낮춘다.
  - 계정그룹별 금액 기준: `account_group`별 Q3를 우선 사용하고, 표본 부족 시 전체 Q3로 fallback한다.
  - 민감 계정군 우선순위: 매출, 재고, 충당금, 미수/미지급, 손상 계정은 L3-04 단독 판정보다 케이스 우선순위/설명 가중치에서 높게 본다.
  - 케이스 우선순위 기본값: `L3-04 only`는 low, `L3-04 + 민감 계정/고액`은 medium, `L3-04 + 주말/심야/장기괴리/승인·중복·역분개`는 high 검토 후보로 올린다.
  - 보류: `created_by`별 평소 패턴 대비 급증 탐지는 사용자별 baseline이 필요하므로 Phase 1 룰이 아니라 시계열/통계/ML 탐지에서 다룬다.

### L3-05 주말 전기

- 감사인이 조정하는 값: 회사 자체 휴일 목록
  - 실제 키: `custom_holidays`
  - 기본값: `[]`
  - 의미: 공휴일 외에 회사 휴무일도 같이 주말성 전기로 볼지
  - 수정 위치: `config/settings.py`
- 운영 해석
  - L3-05는 `posting_date`가 토요일, 일요일, 한국 법정공휴일, 또는 `custom_holidays`에 포함된 날짜인지 보는 캘린더 기반 보조 신호다.
  - 단독으로는 과탐 가능성이 높으므로 실무 alert에서는 수기 전표, 고액, 기말, 승인 통제 이슈, 적요 부실, 특정 작성자 집중 같은 다른 징후와 조합해 우선순위를 정한다.
  - 사용인은 해당 회사의 실제 근무 캘린더를 확인해 회사별 휴일을 `custom_holidays`에 직접 추가해야 한다. 창립기념일, 전사 휴무일, 공장 셧다운, 대체 근무일, 노사 합의 휴일 등을 입력하지 않으면 회사 휴무일 전표가 L3-05에서 빠질 수 있다.

### L3-06 심야 전기

- 운영 해석
  - L3-06은 `is_after_hours`가 True인 전표만 보는 심야 전기 룰이다. 기본 심야 구간은 22:00~06:00이며, 주말/공휴일 전기는 L3-05가 별도로 담당한다.
  - 감사인 또는 사용자는 회사 근무제, 교대근무, 해외법인 시간대, 마감 운영 정책에 맞춰 심야 시작/종료 시각을 조정할 수 있다.
  - 18:30~22:00 같은 야근 시간대나 사용자별 비정상 시간 집중은 L3-06이 아니라 L4-05에서 다룬다.

- 감사인이 조정하는 값: 심야 시작 시각
  - 실제 키: `midnight_start`
  - 기본값: `22`
  - 의미: 이 시각 이상부터 심야 전기로 본다. 예를 들어 `23`이면 23:00 이후가 심야 시작이다.
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 심야 종료 시각
  - 실제 키: `midnight_end`
  - 기본값: `6`
  - 의미: 이 시각 미만까지 심야 전기로 본다. 예를 들어 `5`이면 05:00 전까지만 심야다.
  - 수정 위치: `config/settings.py`

### L3-07 전기일-문서일 장기 괴리

- 감사인이 조정하는 값: 전기일자와 문서일자가 며칠 초과로 차이나면 장기 날짜 괴리로 볼지
  - 실제 키: `backdated_threshold_days`
  - 기본값: `30`
  - 수정 위치: `config/settings.py`
  - 해석: `posting_date - document_date`가 양수이면 지연 전기, 음수이면 선전기성 날짜 괴리다. L3-07은 절댓값 기준으로 둘 다 1차 검토 대상으로 잡는다.

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

- 감사인이 조정하는 값: 장기체류 판정 일수
  - 실제 키: `suspense_aging_days`
  - 기본값: `30`
  - 의미: suspense 계정이 미정리 상태로 몇 일 이상 남으면 L3-09로 볼지
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 최소 미정리 금액
  - 실제 키: `suspense_min_open_amount`
  - 기본값: `0`
  - 의미: `amount_open`이 이 값 이하여서 실무적으로 무의미한 소액이면 L3-09에서 제외
  - 수정 위치: `config/settings.py`

- 운영 메모
  - L3-09의 본질은 `가계정 사용`이 아니라 `장기 미정리`다.
  - 실무에서는 `amount_open`, `is_cleared`, `settlement_status`, `settlement_date`를 우선 사용하고,
    `lettrage`/`lettrage_date`는 보조로만 쓰는 것이 적절하다.
  - Phase 1에서는 계정별 자동 grace나 정상 clearing 계정 추정 없이, 고정 threshold로 단순하게 본다.
  - 계정별 예외 추천이나 정상 패턴 학습은 Phase 2/3 보조 분석으로 다루는 편이 적절하다.

### L3-10 고위험 계정 사용 / 민감 계정군 접촉

- 감사인/사용자가 조정하는 민감 계정 exact code 목록
  - 실제 키: `patterns.high_risk_account_use.accounts`
  - 기본값: `1190`, `2190`
  - 의미: 어떤 개별 GL 계정을 `L3-10` 민감 계정으로 직접 볼지 정의한다.
  - 수정 위치: `config/audit_rules.yaml`
  - UI 분류: `auditor_checklist_required`

- 감사인/사용자가 조정하는 민감 계정 prefix 목록
  - 실제 키: `patterns.high_risk_account_use.account_prefixes`
  - 기본값: `111`, `112`, `113`
  - 의미: 어떤 계정 접두사를 민감 계정군으로 넓게 볼지 정의한다.
  - 수정 위치: `config/audit_rules.yaml`
  - UI 분류: `auditor_checklist_required`

- 감사인이 조정하는 값: 민감 계정군 그룹
  - 실제 키: `patterns.high_risk_account_use.sensitive_account_groups`
  - 의미: cash equivalent, suspense/clearing, advance/loan, prepaid/deferred 등 사용자 설명용 계정군
  - 수정 위치: `config/audit_rules.yaml`
  - UI 분류: `auditor_tunable`

- 감사인 체크리스트
  - 고객사 CoA 기준 현금성 계정, 가계정, 가지급금, 대여금, 선급금, 상품권, 임시정산 계정을 확인한다.
  - exact account와 prefix를 섞어 쓸 때 prefix가 너무 넓어 정상 계정까지 과탐하지 않는지 확인한다.
  - 민감 계정은 단독 확정이 아니라 다른 통제/시점/금액 신호와 결합해 우선순위를 판단한다.

### L3-11 매출 컷오프 불일치

- 감사인이 조정하는 값: 매출 cutoff 허용일수
  - 실제 키: `ev_revenue_cutoff_days`
  - 기본값: `5`
  - 의미: 매출 인식일과 증빙/납품/검수일 차이를 며칠까지 허용할지
  - 수정 위치: `config/settings.py`
  - UI 분류: `auditor_checklist_required`

- 감사인이 조정하는 값: 비용 cutoff 허용일수
  - 실제 키: `ev_expense_cutoff_days`
  - 기본값: `7`
  - 의미: 비용 cutoff 검토에도 같은 evidence 계층을 사용할 때의 허용일수
  - 수정 위치: `config/settings.py`
  - UI 분류: `auditor_tunable`

- 시스템 내부값: 기말 가중 계수
  - 실제 키: `ev_cutoff_period_end_weight`
  - 기본값: `1.5`
  - 의미: 기말 근처 cutoff 신호를 더 강하게 보는 가중치
  - UI 분류: `system_default`

- 시스템 내부값: 최대 차이일수
  - 실제 키: `ev_cutoff_max_day_diff`
  - 기본값: `30`
  - 의미: cutoff 점수 정규화 상한
  - UI 분류: `system_default`

- 감사인이 조정하는 값: 영업일 기준 사용 여부
  - 실제 키: `ev_cutoff_use_business_days`
  - 기본값: `true`
  - 의미: 날짜 차이를 calendar day가 아니라 영업일 기준으로 볼지
  - 수정 위치: `config/settings.py`
  - UI 분류: `auditor_tunable`

- 감사인 체크리스트
  - 매출 인식 기준, 납품/검수/청구 조건, 반품 조건을 확인한다.
  - 회사가 calendar day와 business day 중 어떤 기준으로 cutoff를 관리하는지 확인한다.
  - 기말 전후 매출 취소, 환입, 관계사 매출이 함께 있는지 case drill-down에서 확인한다.

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

- 감사인이 조정하는 값: 전역 상위 금액 분위수 가드
  - 실제 키: `l403_min_amount_quantile`
  - 기본값: `0.90`
  - 의미: Z-score만으로 잡히는 소액 이상치를 줄이기 위해 전체 금액 상위 분위수도 함께 요구할지
  - 수정 위치: `config/settings.py`

### L4-04 희소 차대 계정쌍

- 감사인이 조정하는 값: 얼마나 드문 차변-대변 GL 계정쌍이면 검토 후보로 볼지
  - 실제 키: `account_pair_rare_percentile`
  - 기본값: `0.01`
  - 수정 위치: `config/settings.py`

### L4-05 비정상 시간대 집중

- 감사인이 조정하는 값: 정상 업무 시작 시각
  - 실제 키: `normal_hours_start`
  - 기본값: `8.5`
  - 의미: 정상 업무시간 시작을 08:30처럼 소수 시간으로 표현
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 정상 업무 종료 시각
  - 실제 키: `normal_hours_end`
  - 기본값: `18.5`
  - 의미: 정상 업무시간 종료를 18:30처럼 소수 시간으로 표현
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 결산 집중기간 시작일
  - 실제 키: `settlement_start_mmdd`
  - 기본값: `1220`
  - 의미: 결산 집중기간 시작일을 MMDD로 입력
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 결산 집중기간 종료일
  - 실제 키: `settlement_end_mmdd`
  - 기본값: `0115`
  - 의미: 결산 집중기간 종료일을 MMDD로 입력
  - 수정 위치: `config/settings.py`

- 감사인이 조정하는 값: 사용자별 시간대 이상치 sigma
  - 실제 키: `abnormal_sigma_threshold`
  - 기본값: `2.5`
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
  - 기본값: `batch`, `interface`, `system`, `auto`, `if`, `sys` 계열
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

### 기말/기초 대규모가 너무 많을 때

- 먼저 회사 결산 일정에 맞춰 `period_end_margin_days`를 줄이거나 늘린다.
- 정상 반복 마감전표 whitelist를 검토한다. 단, 사용자가 승인한 좁은 패턴만 제외한다.
- `period_end_amount_quantile`을 높여 고액 기준을 상향한다.
- `c01_min_group_size`를 조정해 표본이 작은 계정그룹에서 생기는 과탐을 줄인다.
- 민감 계정군이 아닌 정상 마감 계정은 우선순위를 낮추고, 매출/재고/충당금/미수·미지급/손상 계정은 우선순위를 유지한다.

### Benford가 과민할 때

- MAD 기준
- 최소 표본 수

## 변경 권장 방식

- 회사 고유 정책은 회사별 override로 관리한다.
- 계약별 튜닝은 engagement override로 관리한다.
- 임시 실험은 UI runtime override로 먼저 시험한다.
- 승인권자 한도 변경은 반드시 `employees.json` 또는 회사 마스터 기준으로 관리한다.
