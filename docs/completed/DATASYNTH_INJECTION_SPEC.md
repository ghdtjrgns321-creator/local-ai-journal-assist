# DataSynth Anomaly Injection 수정 명세서

> 작성일: 2026-03-27
> 목적: DataSynth Rust 코드의 anomaly injection 전략 전면 수정 스펙
> 근거: 전수조사 결과 53개 anomaly_type 중 41개가 default fallback(금액×2~10배)으로 처리되어
>       라벨과 실제 데이터가 불일치. ML/DL 학습에 사용 불가.

## 1. 현황: strategies.rs 구조적 문제

```rust
// tools/datasynth/crates/datasynth-generators/src/anomaly/strategies.rs
fn apply_strategy(&self, entry: &mut JournalEntry, anomaly_type: AnomalyType, rng: &mut impl Rng) -> InjectionResult {
    match anomaly_type {
        // === 12개만 전용 전략 ===
        UnusuallyHighAmount    => self.amount_modification.apply(...),
        BackdatedEntry         => self.date_modification.apply(...),
        FutureDatedEntry       => self.date_modification.apply(...),
        WrongPeriod            => self.date_modification.apply(...),
        LatePosting            => self.date_modification.apply(...),
        JustBelowThreshold     => self.approval_anomaly.apply(...),
        ExceededApprovalLimit  => self.approval_anomaly.apply(...),
        VagueDescription       => self.description_anomaly.apply(...),
        BenfordViolation       => self.benford_violation.apply(...),
        SplitTransaction       => self.split_transaction.apply(...),
        SkippedApproval        => self.skipped_approval.apply(...),
        WeekendPosting         => self.weekend_posting.apply(...),

        // === 41개: 전부 금액 변경으로 빠짐 ===
        _ => self.amount_modification.apply(entry, anomaly_type, rng),
    }
}
```

## 2. 전수조사 결과 (audit_labels.py, 2026-03-27)

### OK (15개) — 라벨 = 데이터 일치

현재 정상 작동 중. 수정 불필요.

```
BackdatedEntry           9/9     diff>30d
ExceededApprovalLimit   20/20    threshold_match
ImproperCapitalization  11/11    15xx+6xx (Python 후처리로 수정된 상태 → Rust에서 해결 필요)
InvalidAccount           2/2     invalid_gl (Python 후처리 → Rust)
JustBelowThreshold      29/29    threshold_match
LatePosting             10/10    diff>30d
ManualOverride           3/3     manual+high
RevenueManipulation      7/7     4xxx+high (Python 후처리 → Rust)
ReversedAmount          11/11    reversal_pair (Python 후처리 → Rust)
SkippedApproval          6/6     no_approver (Python 후처리 → Rust)
UnbalancedEntry          2/2     imbalanced (Python 후처리 → Rust)
WeekendPosting           3/3     weekend
WrongPeriod              7/7     wrong_period
DormantAccountActivity 811/826   dormant_gl (15건 미일치)
```

**주의**: 기존 Python 후처리(fix_datasynth_anomalies.py)는 삭제됨.
모든 수정이 Rust 전략(strategies.rs)에 구현 완료.

### ALL_MISMATCH (6개) — 전수 수정 필요

| Type | 문서수 | 일치 | 문제 | Rust 수정 방법 |
|------|-------:|-----:|------|----------------|
| AfterHoursPosting | 12 | 0 | posting_time이 업무시간 내 | posting_date 시간을 22:00~05:00 분포로 샘플링 (LogNormal 또는 Uniform) |
| DuplicateEntry | 10 | 0 | 동일 GL+금액+날짜 쌍 없음 | DuplicationStrategy 활성화: 같은 GL+금액+posting_date로 2번째 entry 생성 |
| DuplicatePayment | 30 | 0 | vendor+금액 쌍 없음 | 같은 vendor + 같은 금액 + posting_date ±1~15일 entry 쌍 생성, business_process=P2P 보장 |
| ExactDuplicateAmount | 134 | 0 | 같은 금액 쌍 없음 | 같은 GL+금액으로 2번째 entry 생성 (날짜는 다를 수 있음) |
| FutureDatedEntry | 4 | 0 | document_date < posting_date | document_date를 posting_date보다 3~7일 뒤로 설정 |
| VagueDescription | 14 | 0 | line_text에 위험 키워드 없음 | DescriptionAnomalyStrategy에 한국어 키워드 추가: "기타", "확인중", "임시", "테스트", "추후정리" |

### PARTIAL (7개) — 미일치분 수정 필요

| Type | 문서수 | 일치 | 미일치 | Rust 수정 방법 |
|------|-------:|-----:|-------:|----------------|
| SelfApproval | 19 | 4 | 15 | approved_by = created_by 강제 설정. approval_date도 posting_date와 동일 |
| SegregationOfDutiesViolation | 10 | 3 | 7 | sod_violation=true, sod_conflict_type을 preparer_approver 등으로 설정 |
| MissingField | 28 | 6 | 22 | 필수필드(gl_account 또는 reference) 중 하나를 NULL로 설정. posting_date, document_id는 보존 |
| RushedPeriodEnd | 9 | 4 | 5 | posting_date를 해당 월 26~31일로 변경. month_end_spike 로직과 연동 |
| UnusuallyHighAmount | 110 | 6 | 104 | 금액을 해당 GL 그룹의 mean + Uniform(3σ, 6σ)로 설정. σ는 gl_account별 실제 std 사용 |
| StatisticalOutlier | 129 | 1 | 128 | UnusuallyHighAmount와 동일 로직 |
| UnusualTiming | 183 | 1 | 182 | AfterHoursPosting과 동일: 시간을 22:00~05:00으로 설정 |

### SKIP → Rust 수정 필요 (13개)

| Type | 문서수 | 현실 시나리오 | Rust 수정 방법 |
|------|-------:|---------------|----------------|
| TransposedDigits | 27 | 경리 수기입력 시 인접 자릿수 swap (123,456→132,456) | amount의 인접 2자리 swap. TransposedDigitsStrategy 이미 존재 → apply_strategy match에 추가 |
| DecimalError | 9 | 자릿수 착오 (만원을 천원으로, ×10 or ÷10) | amount를 ×10 또는 ÷10. rebalance_entry=false (차대변 불일치 유발이 현실적) |
| RoundingError | 29 | 반올림 오류 (끝자리 1~9원 추가/차감) | amount ± Uniform(1, 9). 소액이므로 차대변 1~9원 차이 허용 |
| CurrencyError | 7 | 원화↔달러 환산 실수 (÷1,100~1,300 또는 ×1,100~1,300) | amount를 ÷ Uniform(1100, 1300). 환율 적용 오류 시뮬레이션 |
| MisclassifiedAccount | 6 | 계정 분류 오류 (여비교통비→접대비, 같은 대분류 내) | gl_account를 같은 1st digit 다른 계정으로 교체. CoA에서 동일 그룹 내 랜덤 선택 |
| WrongCostCenter | 18 | 다른 법인/부서 코스트센터 입력 | cost_center를 다른 company_code의 CC로 교체 (예: CC-C001 → CC-C002) |
| RoundDollarManipulation | 28 | 가공 전표 특유의 정확한 round number (100만, 500만, 1억) | amount를 round_number_unit(100만)의 정확한 배수로 설정. 끝자리 000,000 보장 |
| UnusuallyLowAmount | 87 | 탐색적 소액 전기 (100~1,000원), 테스트 전표 | amount를 Uniform(100, 1000)으로 설정 |
| IncompleteApprovalChain | 4 | 승인 체인 불완전 (중간 승인자 누락) | approved_by=NULL, source='manual'. approval_date 미설정 |
| LateApproval | 5 | 전기 후 14~30일 뒤에야 승인 | approval_date = posting_date + Uniform(14, 30)일 |
| MissingDocumentation | 12 | 증빙 미첨부 (reference, header_text 비어있음) | reference=NULL, header_text=NULL. line_text는 유지 |
| BenfordViolation | 157 | 가공 금액의 첫째자릿수 분포 위반 (5~9 편중) | BenfordViolationStrategy 이미 존재 → apply_strategy match에 추가. 첫째자릿수를 Categorical([5,6,7,8,9], equal_weight)로 강제 |
| UnusualAccountPair | 30 | 업무상 만날 수 없는 계정 조합 (P2P 매입계정↔H2R 급여계정) | cross-process GL 쌍 강제 배정. 해당 조합이 전체 빈도 하위 1%가 되도록 보장 |

### Phase 2/3 — DataSynth 구조적 확장 필요 (12개, 4,888건)

CSV 후처리로 불가능한 것이 아니라, **해당 Phase의 탐지 모듈과 함께 설계해야 의미 있는 것들.**

| Type | 문서수 | 필요한 인프라 | 구현 시점 |
|------|-------:|---------------|-----------|
| NewCounterparty | 1,312 | auxiliary_account_number가 데이터에 1회만 등장하도록 보장 | Phase 2c |
| MissingRelationship | 896 | document flow 체인(PO→GR→Invoice→Payment)에서 한 단계 누락 | Phase 2c |
| CentralityAnomaly | 444 | 특정 entity가 비정상적으로 많은 거래에 관여 | Phase 2c (GNN) |
| CircularTransaction | 416 | trading_partner로 A→B→C→A 순환 체인 생성 | Phase 2c (그래프) |
| CircularIntercompany | 233 | company_code 간 IC 순환 생성 + trading_partner 채움 | Phase 2c |
| TransferPricingAnomaly | 472 | IC 쌍 생성 + arm's length 대비 20~30% 이탈 금액 | Phase 2c |
| UnmatchedIntercompany | 704 | IC 한쪽만 생성, 상대 전표 없음 | Phase 2c |
| RepeatingAmount | 90 | 동일 vendor + 동일 금액이 5회+ 반복 | Phase 2 (시계열) |
| UnusualFrequency | 131 | 동일 vendor 거래가 단기간(1주)에 집중 | Phase 2 |
| TransactionBurst | 104 | 특정 기간에 거래량 급증 (평소 대비 3σ+) | Phase 2 |
| TrendBreak | 77 | 월별 추세 대비 이탈 (예: 매출 급등/급락) | Phase 2 |
| FictitiousEntry | 7 | 실물 거래 없는 가공 전표 (vendor 미존재) | Phase 2 (ML) |
| FictitiousVendor | 2 | 가짜 거래처 (vendor master에 없는 ID) | Phase 2 (ML) |

## 3. 글로벌 데이터 버그

전수조사에서 발견된 anomaly injection 외 데이터 무결성 문제.

| # | 항목 | 건수 | 원인 | Rust 수정 |
|---|------|-----:|------|-----------|
| 1 | Negative credit_amount | 2 | 금액 생성 버그 | abs() 보장 또는 음수 방지 validation |
| 2 | fiscal_period ≠ posting_month | 174 | WrongPeriod 7건은 의도적. 나머지 167건은 날짜 변환 버그 | posting_date.month() == fiscal_period 보장 (WrongPeriod 제외) |
| 3 | trading_partner 99.9% NULL | ~1.1M | IC 모듈이 trading_partner 미생성 | IC 거래(intercompany.enabled=true) 시 trading_partner 채움 |
| 4 | DormantAccountActivity 15건 미일치 | 15 | dormant GL 교체 누락 | DormantAccountStrategy 적용 확인 |

## 4. 현실 시나리오 매핑 (DETECTION_REFERENCE.md 기반)

각 anomaly_type이 실제 감사에서 어떤 부정/오류 패턴에 대응하는지.

### 가공 전표 (FSS 50건, 53%)

```
FictitiousEntry          → 실물 없이 세금계산서 위조 후 매출/자산 분개 생성
DuplicatePayment         → 동일 건 이중 지급 (횡령 수단)
DuplicateEntry           → 같은 전표 반복 전기 (시스템 오류 또는 의도적)
ExactDuplicateAmount     → 정확히 같은 금액 반복 (라운드트립, 페이퍼컴퍼니)
RevenueManipulation      → 매출 계정에 비정상 고액 기장 (실물 없는 가공매출)
```

### 결산 수정 조작 (FSS 27건, 29%)

```
RushedPeriodEnd          → 월말 마감 직전 대량 전기 (밀어내기)
ImproperCapitalization   → 비용을 자산으로 이전 (이익 부풀리기)
UnusuallyHighAmount      → 비정상 고액 결산 조정
StatisticalOutlier       → 통계적으로 이상한 금액 (Z-score > 3σ)
BenfordViolation         → 가공 금액의 첫째자릿수 분포 위반
```

### 횡령 은폐 (FSS 24건, 26%)

```
SelfApproval             → 자기 결재 (내부통제 우회, 오스템임플란트 사례)
SegregationOfDutiesViolation → 1인 입력·승인·실행 (직무분리 위반)
SkippedApproval          → 승인 없이 한도 초과 전표 처리
ManualOverride           → 자동 프로세스 우회하여 수기 전기 (source='manual' + 고액)
IncompleteApprovalChain  → 승인 체인 불완전 (중간 승인자 누락)
```

### 순환거래 (FSS 10건, 11%)

```
CircularTransaction      → A→B→C→A 가공매출 순환 (페이퍼컴퍼니)
CircularIntercompany     → 그룹사 간 순환 내부거래
TransferPricingAnomaly   → arm's length 대비 이전가격 이탈
UnmatchedIntercompany    → IC 한쪽만 존재 (상대 전표 미생성)
```

### 비정상 시점 (FSS 4건, 4%)

```
AfterHoursPosting        → 심야(22:00~06:00) 전기 (퇴근 후 몰래 전기)
UnusualTiming            → 비정상 시간대 전기
WeekendPosting           → 주말 전기
BackdatedEntry           → 소급 전기 (30일+ 이전 날짜로 기록)
FutureDatedEntry         → 선일자 증빙 (아직 안 온 세금계산서 날짜)
LatePosting              → 거래 발생 후 30일+ 지연 전기
```

### 데이터 오류

```
MissingField             → ERP 미완료 전기 (필수필드 NULL)
InvalidAccount           → CoA에 없는 GL 코드 사용
TransposedDigits         → 수기 입력 자릿수 swap (123,456→132,456)
DecimalError             → 자릿수 착오 (만원↔천원, ×10/÷10)
RoundingError            → 반올림 오류 (끝자리 1~9원)
CurrencyError            → 원화↔달러 환산 실수 (÷1,100~1,300)
MisclassifiedAccount     → 계정 분류 오류 (여비→접대비)
WrongCostCenter          → CC 잘못 입력 (다른 법인/부서)
WrongPeriod              → 회계기간 불일치
UnbalancedEntry          → 차대변 불일치
MissingDocumentation     → 증빙 미첨부 (reference, header_text 없음)
VagueDescription         → 모호한 적요 ("기타", "확인중", "임시")
```

### 통계적 이상

```
UnusualAccountPair       → 업무상 만날 수 없는 계정 조합 (P2P↔H2R GL 쌍)
RoundDollarManipulation  → 가공 전표 특유의 정확한 round number
UnusuallyLowAmount       → 탐색적 소액 전기 (100~1,000원, 테스트 전표)
LateApproval             → 전기 후 14~30일 지연 승인
```

## 5. Rust 수정 우선순위

### P0: 기존 전략 match문 누락 (이미 Strategy 존재)

strategies.rs의 match문에 추가만 하면 됨. 코드 변경 최소.

```
TransposedDigits  → TransposedDigitsStrategy (이미 구현)
BenfordViolation  → BenfordViolationStrategy (이미 구현)
AfterHoursPosting → WeekendPostingStrategy 확장 (시간 변경 로직 추가)
UnusualTiming     → 위와 동일
```

### P1: 신규 전략 구현 필요

| 전략 | 대상 타입 | 예상 LOC | 핵심 로직 |
|------|-----------|:--------:|-----------|
| SelfApprovalStrategy | SelfApproval | ~50 | approved_by = created_by |
| MissingFieldStrategy | MissingField | ~40 | 필수필드 1개를 NULL |
| DuplicateEntryStrategy | DuplicateEntry, ExactDuplicateAmount, DuplicatePayment | ~150 | entry 복제 + new doc_id + date offset |
| FutureDateStrategy | FutureDatedEntry | ~40 | document_date = posting + 3~7일 |
| SoDViolationStrategy | SegregationOfDutiesViolation | ~60 | sod_violation=true + conflict_type |
| RushedPeriodEndStrategy | RushedPeriodEnd | ~40 | posting_date.day를 26~31로 |
| HighAmountStrategy | UnusuallyHighAmount, StatisticalOutlier | ~80 | amount = gl_mean + Uniform(3σ, 6σ) |
| LowAmountStrategy | UnusuallyLowAmount | ~30 | amount = Uniform(100, 1000) |
| FormatErrorStrategy | DecimalError, RoundingError, CurrencyError | ~80 | ×10/÷10, ±1~9, ÷1200 |
| AccountSwapStrategy | MisclassifiedAccount, WrongCostCenter | ~60 | GL/CC를 같은 그룹 내 다른 값으로 교체 |
| RoundDollarStrategy | RoundDollarManipulation | ~30 | amount를 round_unit의 정확한 배수로 |
| DocumentationStrategy | MissingDocumentation, IncompleteApprovalChain, LateApproval | ~60 | reference/header_text NULL, approval_date 지연 |
| RarePairStrategy | UnusualAccountPair | ~100 | cross-process GL 쌍 강제 배정 + 빈도 하위 1% 보장 |

### P2: 글로벌 버그 수정

```
1. negative credit 방지: amount 생성 시 abs() 보장
2. fiscal_period 정합성: posting_date.month() 동기화
3. trading_partner 채움: IC 거래에 한해 counterparty company_code 설정
4. DormantAccount 15건 미일치: strategy 적용 확인
```

### P3: Phase 2/3 전용 (탐지 모듈과 함께 구현)

```
CircularTransaction, CircularIntercompany → 그래프 모듈
TransferPricingAnomaly, UnmatchedIntercompany → IC 모듈
NewCounterparty, MissingRelationship, CentralityAnomaly → 관계 모듈
RepeatingAmount, UnusualFrequency, TransactionBurst, TrendBreak → 시계열 모듈
FictitiousEntry, FictitiousVendor → ML 분류기
```

## 6. 핵심 분포 파라미터 (현실적 분산 보장)

하드코딩 금지. 모든 수치는 분포에서 샘플링.

| 항목 | 분포 | 파라미터 | 근거 |
|------|------|----------|------|
| 승인한도 직하 비율 | Uniform | (0.88, 0.99) | 횡령범은 한도의 88~99%에서 분산 |
| 소급 일수 | LogNormal | mu=3.5, sigma=0.5 → 중앙값 33일, 범위 20~90일 | 실무 소급은 1~3개월 다양 |
| 심야 시간 | Uniform | (22.0, 29.0) mod 24 → 22:00~05:00 | 심야 전기 분포 |
| 차대변 불일치 | LogNormal | mu=4, sigma=2 → 중앙값 55원, 범위 1원~수천원 | 반올림/입력 오류 |
| 고액 Z-score | Uniform | (3.0, 6.0) × σ | 통계적 이상치 기준 |
| 자릿수 오류 배수 | Choice | [0.1, 10.0] equal weight | 한 자릿수 착오 |
| 역분개 시차 | Uniform | (0, 1)일 | SAP 역분개는 당일~익일 |
| 중복 지급 시차 | Uniform | (1, 15)일 | 동일 청구서 이중 처리 |

## 7. 검증 방법

Rust 수정 → 재생성 후:

```bash
# 1. 전수조사 실행
PYTHONPATH=. uv run python tools/audit_labels.py
# 목표: ALL_MISMATCH=0, PARTIAL의 미일치=0

# 2. E2E 라벨 검증
PYTHONPATH=. uv run python tests/phase1_rulebase/test_e2e_label_validation.py
# 목표: Phase 1 Recall > 95%

# 3. 분산 검증 — 동일 값 클러스터링 없는지 확인
# L2-01 amounts가 전부 같은 비율이면 실패
# L3-07 date diff가 전부 같은 일수이면 실패

# 4. 기존 테스트 회귀
uv run pytest tests/ -v --timeout=120
```

## 8. 폐기 대상

| 파일 | 사유 |
|------|------|
| `tools/fix_datasynth_anomalies.py` | **삭제됨** — Rust strategies.rs에 모든 전략 구현 완료 |
| `data/journal/primary/datasynth/journal_entries.csv.bak` | 원본으로 복원 완료. bak 삭제 가능 |
