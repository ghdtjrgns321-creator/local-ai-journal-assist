# Audit Domain Reference

감사 도메인 지식. 코드 변수명·룰 ID 일관성 유지용.

> **기준 출처: EY-ASU DataSynth v1.2.0** (tools/datasynth/)
> EY Switzerland Assurance R&D + ASU 공동 개발 합성 전표 생성기의 소스 코드에서
> fraud 유형, anomaly 분류, ACDOCA 필드 정의를 추출하여 프로젝트 기준으로 채택.
> 근거 파일: `crates/datasynth-core/src/models/anomaly.rs`, `crates/datasynth-config/src/schema.rs`

## 감사 기준

- **PCAOB AS 2401**: 부정 감사 기준 (미국)
- **ISA 240**: 부정 관련 감사인 책임 (국제)
- **ISA 520**: 분석적 절차 (Benford 근거)
- **COSO 2013**: 내부통제 통합 프레임워크 (DataSynth에서 17개 원칙 구현)
- **SOX 302/404**: 재무보고 내부통제 (DataSynth에서 DeficiencyMatrix 구현)

## 감사 룰 (R001~R008)

DataSynth의 `FraudType`, `ProcessIssueType`, `StatisticalAnomalyType` enum에서
프로젝트에 적용할 8개 룰을 매핑했다.

| ID   | 룰명         | DataSynth 근거                                   | 코드 변수           |
|------|--------------|--------------------------------------------------|---------------------|
| R001 | 승인한도 직하 | `FraudType::JustBelowThreshold` (severity 3)     | `is_near_threshold` |
| R002 | 주말 거래    | `ProcessIssueType::WeekendPosting` (severity 2)  | `is_weekend`        |
| R003 | 심야 거래    | `ProcessIssueType::AfterHoursPosting` (severity 2)| `is_after_hours`    |
| R004 | 기말 대규모  | `ProcessIssueType::RushedPeriodEnd` (severity 3) | `is_period_end`     |
| R005 | 역분개       | `FraudType::TimingAnomaly` (severity 4)          | `is_reversal`       |
| R006 | 수기 전표    | `ProcessIssueType::ManualOverride` (severity 4)  | `is_manual_je`      |
| R007 | 위험 적요    | `ProcessIssueType::VagueDescription` (severity 1)| `has_risk_keyword`  |
| R008 | 관계사 거래  | `RelationalAnomalyType::CircularIntercompany` (severity 4) | `is_intercompany` |

> DataSynth는 이 외에도 49개 fraud + 28개 error + 22개 process issue + 18개 statistical + 15개 relational = **총 132개 anomaly 유형**을 정의한다.
> Phase 2에서 ML 모델 구축 시 확장 가능.

## DataSynth Fraud 유형 (8종 — 설정 가능)

`crates/datasynth-config/src/schema.rs` FraudTypeDistribution에서 정의.
`config/datasynth.yaml`에서 비율 조절 가능.

| fraud_type              | 설명                    | 기본 비율 | 프로젝트 설정 |
|-------------------------|------------------------|:---------:|:-------------:|
| suspense_account_abuse  | 가수금 계정 남용        |    25%    |      5%       |
| fictitious_transaction  | 가공 거래               |    15%    |     20%       |
| revenue_manipulation    | 매출 조작               |    10%    |     15%       |
| expense_capitalization  | 비용의 자산화           |    10%    |      5%       |
| split_transaction       | 분할 거래 (승인 한도 우회)|   15%    |     15%       |
| timing_anomaly          | 기간 귀속 조작          |    10%    |     10%       |
| unauthorized_access     | 권한 우회               |    10%    |     10%       |
| duplicate_payment       | 중복 지급               |     5%    |     20%       |

## Benford's Law 판정 기준

DataSynth는 금액 분포를 Benford's Law에 맞춰 생성하며,
검증 시 MAD 0.015 이하를 기본 임계값으로 사용한다.
(`crates/datasynth-config/src/schema.rs` — `benford_first_digit` threshold_mad: 0.015)

| 지표       | 적합    | 의심        | 부적합  |
|------------|---------|-------------|---------|
| MAD        | < 0.006 | 0.006~0.012 | > 0.012 |
| KS p-value | > 0.05  | 0.01~0.05   | < 0.01  |

추가 검정: Chi-square, Anderson-Darling (DataSynth eval 모듈에서 지원)

## 표준 컬럼 스키마

DataSynth `journal_entries.csv` 출력 컬럼 기준.
ACDOCA 71개 필드 중 프로젝트에서 사용하는 29개 컬럼.

### 필수 컬럼

| 컬럼명             | 타입     | DataSynth 컬럼       | ACDOCA 매핑 | 설명             |
|--------------------|----------|-----------------------|-------------|------------------|
| `document_id`      | str      | `document_id`         | `belnr`     | 전표 ID (UUID)   |
| `company_code`     | str      | `company_code`        | `rbukrs`    | 회사코드         |
| `fiscal_year`      | int      | `fiscal_year`         | `gjahr`     | 회계연도         |
| `posting_date`     | date     | `posting_date`        | `budat`     | 전기일           |
| `document_date`    | date     | `document_date`       | `bldat`     | 전표일           |
| `gl_account`       | int      | `gl_account`          | `racct`     | G/L 계정코드     |
| `debit_amount`     | float    | `debit_amount`        | `wsl`(S)    | 차변 금액        |
| `credit_amount`    | float    | `credit_amount`       | `wsl`(H)    | 대변 금액        |
| `document_type`    | str      | `document_type`       | `blart`     | 전표유형         |

### 권장 컬럼

| 컬럼명             | 타입     | DataSynth 컬럼       | ACDOCA 매핑 | 설명             |
|--------------------|----------|-----------------------|-------------|------------------|
| `created_by`       | str      | `created_by`          | `usnam`     | 입력자           |
| `source`           | str      | `source`              | -           | 입력소스 (auto/manual) |
| `business_process` | str      | `business_process`    | -           | 비즈니스 프로세스|
| `line_number`      | int      | `line_number`         | `docln`     | 라인번호         |
| `local_amount`     | float    | `local_amount`        | `hsl`       | 현지통화 금액    |
| `currency`         | str      | `currency`            | `rwcur`     | 통화             |
| `cost_center`      | str      | `cost_center`         | `rcntr`     | 코스트센터       |
| `profit_center`    | str      | `profit_center`       | `prctr`     | 손익센터         |
| `line_text`        | str      | `line_text`           | `sgtxt`     | 적요             |
| `header_text`      | str      | `header_text`         | `bktxt`     | 헤더 텍스트      |

### 레이블 컬럼

| 컬럼명             | 타입     | DataSynth 컬럼       | 설명                 |
|--------------------|----------|----------------------|----------------------|
| `is_fraud`         | bool     | `is_fraud`           | fraud 여부           |
| `is_anomaly`       | bool     | `is_anomaly`         | anomaly 여부         |

## 도메인 용어 ↔ 코드 매핑

| 감사 용어   | 영문              | DataSynth 컬럼/필드            | 코드 변수            |
|-------------|-------------------|-------------------------------|----------------------|
| 전표        | Journal Entry     | `document_id`                 | `journal_entry`, `je`|
| 전기일      | Posting Date      | `posting_date` / `budat`      | `posting_date`       |
| 전표일      | Document Date     | `document_date` / `bldat`     | `document_date`      |
| 적요        | Line Text         | `line_text` / `sgtxt`         | `line_text`          |
| 차변        | Debit             | `debit_amount` / `drcrk='S'`  | `debit_amount`       |
| 대변        | Credit            | `credit_amount` / `drcrk='H'` | `credit_amount`      |
| 역분개      | Reversal          | `xstov` flag in ACDOCA        | `is_reversal`        |
| 수기전표    | Manual JE         | `source='manual'`             | `is_manual_je`       |
| 관계사 거래 | Intercompany      | `pbukrs` (partner company)    | `is_intercompany`    |
| 총계정원장  | General Ledger    | `gl_account` / `racct`        | `gl_account`         |
| 이상징후    | Anomaly           | `is_anomaly`, `is_fraud`      | `anomaly`            |
| 입력자      | Created By        | `created_by` / `usnam`        | `created_by`         |
| 전표유형    | Document Type     | `document_type` / `blart`     | `document_type`      |
| 비즈니스 프로세스 | Business Process | `business_process`       | `business_process`   |
