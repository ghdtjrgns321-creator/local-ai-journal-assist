# Validation 데이터셋 Ingest 파이프라인 검증 결과

> 실행일: 2026-03-25 21:31 | 5종 실데이터셋

## 1. 테스트 요약

| 데이터셋            | 검증 | 읽기 | 헤더 | 매핑 | 캐스팅 | 최종 shape        |
|:--------------------|:----:|:----:|:----:|:----:|:------:|:------------------|
| bpi2019             | ✅   | ✅   | ✅   | ✅   | ✅     | 1,595,923 × 22    |
| financial-anomaly   | ✅   | ✅   | ✅   | ✅   | ✅     | 217,441 × 7       |
| general-ledger      | ✅   | ✅   | ✅   | ✅   | ✅     | 27,909 × 6        |
| sap-merged          | ✅   | ✅   | ✅   | ✅   | ✅     | 331,934 × 60      |
| schreyer-fraud      | ✅   | ✅   | ✅   | ✅   | ✅     | 533,009 × 10      |

---

## 2. 발견된 문제점

| 데이터셋 | 문제 | 상세 |
|:---------|:-----|:-----|
| bpi2019 | ③ 헤더 키워드 0개 | 구조 기반 탐지 (keywords.yaml 미등록 컬럼) |
| bpi2019 | ④ 필수 미매핑 9개 | credit_amount, debit_amount, document_date, document_id, document_type... |
| financial-anomaly | ③ 헤더 키워드 0개 | 구조 기반 탐지 (keywords.yaml 미등록 컬럼) |
| financial-anomaly | ④ 필수 미매핑 8개 | company_code, credit_amount, document_date, document_id, document_type... |
| general-ledger | ③ 헤더 키워드 0개 | 구조 기반 탐지 (keywords.yaml 미등록 컬럼) |
| general-ledger | ④ 필수 미매핑 9개 | company_code, credit_amount, document_date, document_id, document_type... |
| sap-merged | ④ 필수 미매핑 2개 | credit_amount, debit_amount |
| schreyer-fraud | ④ 필수 미매핑 7개 | credit_amount, debit_amount, document_date, document_type, fiscal_period... |

---

## 3. v2 개선 결과

| 항목 | v1 | v2 | 상태 |
|:-----|:---|:---|:----:|
| 헤더 탐지 (키워드 의존 80%) | 미등록 컬럼 → 실패 | 구조적 신호 기반 (키워드 15%) | 해결 |
| Fuzzy 오매핑 (drcrk→debit) | 타입 무시 → 100% NaN | 타입 호환성 검증 + dc_indicator 등록 | 해결 |
| 캐스팅 null 무감지 | 단일 warning | 3단계 분기 (유령/오매핑/일반) | 해결 |
| 판단 근거 불투명 | 없음 | ReviewItem 모델 (action/reason) | 해결 |

---

## 4. 남은 문제점

| 문제 | 현상 | 해결 시점 |
|:-----|:-----|:----------|
| Parquet 헤더 탐지 스킵 | 불필요한 탐지 시도 (동작 무영향) | Phase 1c |
| 멀티시트 UI 선택 | active_sheet가 데이터 양 무관 | Phase 1c |
| 일부 Fuzzy 추천 부정확 | monat→debit_amount 등 | Phase 1c~3 |

---

## 5. 데이터셋별 상세

### bpi2019

**SAP ERP P2P 이벤트 로그 (527MB, latin-1)**

**✅ ① 파일 검증** (0.22s)
  category=text

**✅ ② 파일 읽기** (5.08s)
  sheets=['Sheet1'], selected=Sheet1, rows=1595924, cols=22, format=csv, encoding=latin-1

**✅ ③ 헤더 탐지** (0.01s)
  header_row=0, confidence=0.85, matched=[]

**✅ ④ 컬럼 매핑** (1.56s)
  mapping=3개, suggestions=5개, unmapped=14개, needs_review=True
  WARN: 필수 컬럼 미매핑: ['credit_amount', 'debit_amount', 'document_date', 'document_id', 'document_type', 'fiscal_period', 'fiscal_year', 'gl_account', 'posting_date']

**✅ ⑤ 타입 캐스팅** (0.13s)
  cast=0개, skipped=3개

| 원본 | 표준 | 구분 |
|:-----|:-----|:----:|
| case Company | company_code | 확정 |
| case Source | source | 확정 |
| event User | created_by | 확정 |
| case Document Type | document_type | 추천 |
| case GR-Based Inv. Verif. | gl_account | 추천 |
| case Item | credit_amount | 추천 |
| case Purchasing Document | document_id | 추천 |
| case Spend classification text | line_text | 추천 |

미매핑: event org:resource, case Purch. Doc. Category name, eventID, case Spend area text, case Sub spend area text, case concept:name, event concept:name, case Item Category, case Vendor, case Item Type 외 4개

필수 미매핑: credit_amount, debit_amount, document_date, document_id, document_type, fiscal_period, fiscal_year, gl_account, posting_date

최종: 1,595,923행 × 22열

---

### financial-anomaly

**금융 트랜잭션 이상치 데이터 (15MB, UTF-8)**

**✅ ① 파일 검증** (0.01s)
  category=text

**✅ ② 파일 읽기** (0.28s)
  sheets=['Sheet1'], selected=Sheet1, rows=217442, cols=7, format=csv, encoding=latin-1

**✅ ③ 헤더 탐지** (0.01s)
  header_row=0, confidence=0.85, matched=[]

**✅ ④ 컬럼 매핑** (0.09s)
  mapping=2개, suggestions=1개, unmapped=4개, needs_review=True
  WARN: 필수 컬럼 미매핑: ['company_code', 'credit_amount', 'document_date', 'document_id', 'document_type', 'fiscal_period', 'fiscal_year', 'posting_date']

**✅ ⑤ 타입 캐스팅** (0.33s)
  cast=1개, skipped=1개

| 원본 | 표준 | 구분 |
|:-----|:-----|:----:|
| AccountID | gl_account | 확정 |
| Amount | debit_amount | 확정 |
| Timestamp | created_by | 추천 |

미매핑: TransactionType, TransactionID, Merchant, Location

필수 미매핑: company_code, credit_amount, document_date, document_id, document_type, fiscal_period, fiscal_year, posting_date

| 컬럼 | 변환 |
|:-----|:-----|
| debit_amount | object→float64 |

최종: 217,441행 × 7열

---

### general-ledger

**교육용 총계정원장 (2MB, xlsx)**

**✅ ① 파일 검증** (0.04s)
  category=excel

**✅ ② 파일 읽기** (2.47s)
  sheets=['GL', 'Chart of Accounts', 'Calendar', 'Territory', 'CashFlow_St', 'SoCE_St'], selected=GL, rows=27910, cols=12, format=xlsx

**✅ ③ 헤더 탐지** (0.00s)
  header_row=0, confidence=0.77, matched=[]

**✅ ④ 컬럼 매핑** (0.01s)
  mapping=1개, suggestions=2개, unmapped=3개, needs_review=True
  WARN: 필수 컬럼 미매핑: ['company_code', 'credit_amount', 'document_date', 'document_id', 'document_type', 'fiscal_period', 'fiscal_year', 'gl_account', 'posting_date']

**✅ ⑤ 타입 캐스팅** (0.04s)
  cast=1개, skipped=0개

| 원본 | 표준 | 구분 |
|:-----|:-----|:----:|
| Amount | debit_amount | 확정 |
| Account_key | gl_account | 추천 |
| EntryNo | document_id | 추천 |

미매핑: Territory_key, Date, Details

필수 미매핑: company_code, credit_amount, document_date, document_id, document_type, fiscal_period, fiscal_year, gl_account, posting_date

| 컬럼 | 변환 |
|:-----|:-----|
| debit_amount | object→float64 |

최종: 27,909행 × 6열

---

### sap-merged

**SAP ERP 통합 전표 (8.5MB, parquet)**

**✅ ① 파일 검증** (0.02s)
  category=columnar

**✅ ② 파일 읽기** (0.19s)
  sheets=['Sheet1'], selected=Sheet1, rows=331934, cols=60, format=parquet

**✅ ③ 헤더 탐지** (0.00s)
  Parquet — 컬럼명이 메타데이터에 포함, 헤더 탐지 불필요

**✅ ④ 컬럼 매핑** (0.24s)
  mapping=16개, suggestions=6개, unmapped=38개, needs_review=True
  WARN: 필수 컬럼 미매핑: ['credit_amount', 'debit_amount']

**✅ ⑤ 타입 캐스팅** (0.35s)
  cast=4개, skipped=11개

| 원본 | 표준 | 구분 |
|:-----|:-----|:----:|
| belnr | document_id | 확정 |
| blart | document_type | 확정 |
| bldat | document_date | 확정 |
| budat | posting_date | 확정 |
| bukrs | company_code | 확정 |
| drcrk | dc_indicator | 확정 |
| gjahr | fiscal_year | 확정 |
| hsl | local_amount | 확정 |
| mwskz | tax_code | 확정 |
| poper | fiscal_period | 확정 |
| prctr | profit_center | 확정 |
| racct | gl_account | 확정 |
| rcntr | cost_center | 확정 |
| rwcur | currency | 확정 |
| sgtxt | line_text | 확정 |
| usnam | created_by | 확정 |
| IF_Label | auxiliary_account_label | 추천 |
| LOF_Score | source | 추천 |
| buzei | business_process | 추천 |
| valut | lettrage_date | 추천 |
| waers | header_text | 추천 |
| wrbtr | debit_amount | 추천 |

미매핑: monat, shkzg, hkont, usnam_bkpf, FE_UserPostingFrequency, FE_UserAvgLogAmount, FE_AmountDeviationFromUserMean, FE_IsRareTCodeForUser, FE_IsMissingCostCenterForExpense, tcode 외 28개

필수 미매핑: credit_amount, debit_amount

| 컬럼 | 변환 |
|:-----|:-----|
| document_date | object→datetime64[ns] |
| document_id | int64→object |
| gl_account | int64→object |
| posting_date | object→datetime64[ns] |

최종: 331,934행 × 60열

---

### schreyer-fraud

**SAP FICO 합성 전표 벤치마크 (27MB, UTF-8)**

**✅ ① 파일 검증** (0.01s)
  category=text

**✅ ② 파일 읽기** (0.53s)
  sheets=['Sheet1'], selected=Sheet1, rows=533010, cols=10, format=csv, encoding=latin-1

**✅ ③ 헤더 탐지** (0.00s)
  header_row=0, confidence=1.00, matched=['belnr', 'bukrs', 'prctr', 'hkont']

**✅ ④ 컬럼 매핑** (0.16s)
  mapping=5개, suggestions=2개, unmapped=3개, needs_review=True
  WARN: 필수 컬럼 미매핑: ['credit_amount', 'debit_amount', 'document_date', 'document_type', 'fiscal_period', 'fiscal_year', 'posting_date']

**✅ ⑤ 타입 캐스팅** (0.03s)
  cast=0개, skipped=5개

| 원본 | 표준 | 구분 |
|:-----|:-----|:----:|
| BELNR | document_id | 확정 |
| BUKRS | company_code | 확정 |
| HKONT | gl_account | 확정 |
| PRCTR | profit_center | 확정 |
| label | auxiliary_account_label | 확정 |
| WAERS | header_text | 추천 |
| WRBTR | debit_amount | 추천 |

미매핑: DMBTR, KTOSL, BSCHL

필수 미매핑: credit_amount, debit_amount, document_date, document_type, fiscal_period, fiscal_year, posting_date

최종: 533,009행 × 10열

---

## 6. 실행 명령어

```bash
uv run pytest tests/test_ingest/test_validation_datasets.py -v -k 'not slow'  # 빠른 (bpi2019 제외)
uv run pytest tests/test_ingest/test_validation_datasets.py -v               # 전체
uv run pytest tests/test_ingest/test_validation_datasets.py -v -k slow        # 리포트 재생성
```
