# Stage 0 — Column Catalog & Leakage Classification

- dataset: `data/journal/primary/datasynth_manipulation_v3/journal_entries.csv`
- truth join: `labels/manipulated_entry_truth.csv` (document_id 기준 행 라벨링)
- 총 행수: **1,077,767**, 컬럼수: **53**
- manipulated 행: **1,111** (0.10%)

분류 규약: 도메인 우선 분류 → AUROC ≥ 0.95 자동 (A) → null_rate 가 정상행 비율과 ±2%p 이내면 보수적으로 (A) → 식별자/상수는 (D) → 그 외 (C).
AUROC 는 대칭화(`max(auroc, 1-auroc)`)하여 분별력 방향과 무관하게 평가.

## (A) 라벨/누수 의심
- 컬럼 수: **18**

| column | dtype | null_rate | distinct | AUROC | sample | reasoning |
|---|---|---:|---:|---:|---|---|
| `detection_surface_hints` | `object` | 0.9990 | 6 | 1.0000 | embezzlement_concealment, fictitious_entry, period_end_adjustment_ma… | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `document_id` | `object` | 0.0000 | 317,997 | 1.0000 | 39d5140b-8aa0-49e7-a1b1-…, 188b2500-81d9-4ec8-988e-…, 7b69f320-9c2e-4f25-b3f5-… | AUROC=1.0000 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심 |
| `document_number` | `object` | 0.0000 | 317,997 | 1.0000 | C001-2022-005804, C002-2023-016713, C003-2022-015356 | AUROC=1.0000 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심 |
| `header_text` | `object` | 0.0213 | 4,584 | 1.0000 | 고객 대금 수금 - legacy batch, 상각비 계상, 고객 매출 청구 / C003 | AUROC=1.0000 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심 |
| `mutation_mutated_field` | `object` | 0.9942 | 5 | 1.0000 | semantic_surface, substantive_cash_leakage, substantive_fictitious_r… | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `mutation_mutated_value` | `object` | 0.9942 | 50 | 1.0000 | RoundDollarManipulation, LatePosting, ReversedAmount | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `mutation_original_value` | `object` | 0.9942 | 13 | 1.0000 | R2R_ACCRUAL, R2R_REVERSAL, O2C_CUSTOMER_INVOICE | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `mutation_reason` | `object` | 0.9942 | 50 | 1.0000 | Legacy abnormal injectio…, Legacy abnormal injectio…, Legacy abnormal injectio… | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `mutation_type` | `object` | 0.9942 | 50 | 1.0000 | RoundDollarManipulation, LatePosting, ReversedAmount | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `reference` | `object` | 0.0189 | 70,653 | 0.9990 | SO-C001-2022-000001, FA-C002-2023-000001, SO-C003-2022-000002 | AUROC=0.9990 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심 |
| `ip_address` | `object` | 0.0000 | 150,707 | 0.9824 | 10.1.202.228, 10.2.230.210, 10.3.170.55 | AUROC=0.9824 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심 |
| `mutation_base_event_type` | `object` | 0.0000 | 12 | 0.6289 | O2C_CASH_RECEIPT, A2R_DEPRECIATION, O2C_CUSTOMER_INVOICE | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `semantic_scenario_id` | `object` | 0.0000 | 12 | 0.6289 | O2C_CASH_RECEIPT, A2R_DEPRECIATION, O2C_CUSTOMER_INVOICE | 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카 |
| `delivery_date` | `datetime64[us]` | 0.9999 | 24 | 0.5000 | 2022-06-07 00:00:00, 2023-10-02 00:00:00, 2024-06-17 00:00:00 | null_rate=0.9999 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류) |
| `settlement_status` | `object` | 1.0000 | 1 | 0.5000 | open | null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류) |
| `sod_conflict_type` | `object` | 1.0000 | 1 | 0.5000 | CompatibilitySidecarOnly | null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류) |
| `amount_open` | `Int64` | 1.0000 | 12 | 0.5000 | 20120555, 2440000, 6372008 | null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류) |
| `is_cleared` | `boolean` | 1.0000 | 1 | 0.5000 | False | null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류) |

## (B) 라벨 메타데이터
- 컬럼 수: **0**

_(해당 컬럼 없음)_

## (C) ML 피처 후보
- 컬럼 수: **27**

| column | dtype | null_rate | distinct | AUROC | sample | reasoning |
|---|---|---:|---:|---:|---|---|
| `source` | `object` | 0.0000 | 4 | 0.9198 | adjustment, recurring, automated | AUROC=0.9198, null_rate=0.0000, distinct=4 → 일반 피처 후보 |
| `supply_amount` | `int64` | 0.0000 | 267,427 | 0.8936 | 2993623, 38000, 7474000 | AUROC=0.8936, null_rate=0.0000, distinct=267427 → 일반 피처 후보 |
| `invoice_amount` | `int64` | 0.0000 | 269,638 | 0.8932 | 2993623, 38000, 8221400 | AUROC=0.8932, null_rate=0.0000, distinct=269638 → 일반 피처 후보 |
| `created_by` | `object` | 0.0000 | 200 | 0.8199 | PMARTI050, NSILVA044, FESPIN033 | AUROC=0.8199, null_rate=0.0000, distinct=200 → 일반 피처 후보 |
| `auxiliary_account_number` | `object` | 0.1370 | 3,450 | 0.8093 | C-000212, DEPT-001, C-000378 | AUROC=0.8093, null_rate=0.1370, distinct=3450 → 일반 피처 후보 |
| `trading_partner` | `object` | 0.1358 | 3,526 | 0.8021 | C-000212, DEPT-001, C-000378 | AUROC=0.8021, null_rate=0.1358, distinct=3526 → 일반 피처 후보 |
| `counterparty_type` | `object` | 0.0000 | 13 | 0.7972 | Customer, InternalDepartment, VendorRawMaterial | AUROC=0.7972, null_rate=0.0000, distinct=13 → 일반 피처 후보 |
| `auxiliary_account_label` | `object` | 0.1370 | 2,720 | 0.7909 | (주)부동산개발 제3, 내부부서, (유)유틸리티서비스 제3 | AUROC=0.7909, null_rate=0.1370, distinct=2720 → 일반 피처 후보 |
| `local_amount` | `int64` | 0.0000 | 503,365 | 0.7889 | 2993623, 9836, 28164 | AUROC=0.7889, null_rate=0.0000, distinct=503365 → 일반 피처 후보 |
| `document_type` | `object` | 0.0000 | 10 | 0.7401 | BK, AF, DR | AUROC=0.7401, null_rate=0.0000, distinct=10 → 일반 피처 후보 |
| `approved_by` | `object` | 0.0000 | 113 | 0.7401 | JSCOTT049, RCHATT034, NDAVIS006 | AUROC=0.7401, null_rate=0.0000, distinct=113 → 일반 피처 후보 |
| `business_process` | `object` | 0.0000 | 7 | 0.6937 | O2C, A2R, R2R | AUROC=0.6937, null_rate=0.0000, distinct=7 → 일반 피처 후보 |
| `gl_account` | `Int64` | 0.0001 | 281 | 0.6823 | 100070, 100190, 500800 | AUROC=0.6823, null_rate=0.0001, distinct=281 → 일반 피처 후보 |
| `profit_center` | `object` | 0.0000 | 18 | 0.6316 | PC-C001-O2C, PC-C002-A2R, PC-C003-O2C | AUROC=0.6316, null_rate=0.0000, distinct=18 → 일반 피처 후보 |
| `supporting_doc_type` | `object` | 0.4112 | 8 | 0.5894 | 기타증빙, 세금계산서, 내부결의서 | AUROC=0.5894, null_rate=0.4112, distinct=8 → 일반 피처 후보 |
| `user_persona` | `object` | 0.0000 | 13 | 0.5824 | junior_accountant, controller, junior accountant | AUROC=0.5824, null_rate=0.0000, distinct=13 → 일반 피처 후보 |
| `debit_amount` | `int64` | 0.0000 | 355,926 | 0.5519 | 2993623, 0, 9836 | AUROC=0.5519, null_rate=0.0000, distinct=355926 → 일반 피처 후보 |
| `credit_amount` | `int64` | 0.0000 | 373,444 | 0.5494 | 0, 2993623, 24944 | AUROC=0.5494, null_rate=0.0000, distinct=373444 → 일반 피처 후보 |
| `has_attachment` | `bool` | 0.0000 | 2 | 0.5474 | True, False | AUROC=0.5474, null_rate=0.0000, distinct=2 → 일반 피처 후보 |
| `posting_date` | `datetime64[us]` | 0.0000 | 315,988 | 0.5302 | 2022-03-11 16:51:08, 2023-06-28 13:29:55, 2022-06-22 15:26:36 | AUROC=0.5302, null_rate=0.0000, distinct=315988 → 일반 피처 후보 |
| `document_date` | `datetime64[us]` | 0.0000 | 1,099 | 0.5297 | 2022-03-11 00:00:00, 2023-06-28 00:00:00, 2022-06-22 00:00:00 | AUROC=0.5297, null_rate=0.0000, distinct=1099 → 일반 피처 후보 |
| `tax_amount` | `float64` | 0.9163 | 69,651 | 0.5276 | 747400.0, 547436.1, 218983.1 | AUROC=0.5276, null_rate=0.9163, distinct=69651 → 일반 피처 후보 |
| `cost_center` | `object` | 0.6740 | 273 | 0.5232 | CC1000, CC2000, CC3000 | AUROC=0.5232, null_rate=0.6740, distinct=273 → 일반 피처 후보 |
| `tax_code` | `object` | 0.9163 | 2 | 0.5122 | TC-C001-0001, TC-C001-0002 | AUROC=0.5122, null_rate=0.9163, distinct=2 → 일반 피처 후보 |
| `approval_date` | `datetime64[us]` | 0.0001 | 1,105 | 0.5025 | 2023-06-28 00:00:00, 2022-06-23 00:00:00, 2023-11-01 00:00:00 | AUROC=0.5025, null_rate=0.0001, distinct=1105 → 일반 피처 후보 |
| `is_suspense_account` | `bool` | 0.0000 | 2 | 0.5000 | False, True | AUROC=0.5000, null_rate=0.0000, distinct=2 → 일반 피처 후보 |
| `sod_violation` | `bool` | 0.0000 | 2 | 0.5000 | False, True | AUROC=0.5000, null_rate=0.0000, distinct=2 → 일반 피처 후보 |

## (D) 식별자/구조 컬럼
- 컬럼 수: **8**

| column | dtype | null_rate | distinct | AUROC | sample | reasoning |
|---|---|---:|---:|---:|---|---|
| `line_text` | `object` | 0.0208 | 5,701 | 0.7052 | 매출채권 회수 [BK], 고객 입금 반제, C002:감가상각누계액 | 도메인: PK/FK/fiscal 좌표/free-form 텍스트는 ML 피처가 아닌 구조 컬럼 |
| `line_number` | `int64` | 0.0000 | 998 | 0.6107 | 1, 2, 3 | 도메인: PK/FK/fiscal 좌표/free-form 텍스트는 ML 피처가 아닌 구조 컬럼 |
| `fiscal_period` | `int64` | 0.0000 | 12 | 0.5338 | 3, 6, 11 | 도메인: PK/FK/fiscal 좌표/free-form 텍스트는 ML 피처가 아닌 구조 컬럼 |
| `fiscal_year` | `int64` | 0.0000 | 3 | 0.5305 | 2022, 2023, 2024 | 도메인: PK/FK/fiscal 좌표/free-form 텍스트는 ML 피처가 아닌 구조 컬럼 |
| `company_code` | `object` | 0.0000 | 3 | 0.5227 | C001, C002, C003 | 도메인: PK/FK/fiscal 좌표/free-form 텍스트는 ML 피처가 아닌 구조 컬럼 |
| `currency` | `object` | 0.0000 | 1 | 0.5000 | KRW | distinct=1 → 상수 컬럼, 피처 가치 없음 |
| `exchange_rate` | `int64` | 0.0000 | 1 | 0.5000 | 1 | distinct=1 → 상수 컬럼, 피처 가치 없음 |
| `ledger` | `object` | 0.0000 | 1 | 0.5000 | 0L | 도메인: PK/FK/fiscal 좌표/free-form 텍스트는 ML 피처가 아닌 구조 컬럼 |

## 누수 의심 컬럼 reasoning (요약)

- **`document_id`** — AUROC=1.0000, null_rate=0.0000 — AUROC=1.0000 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심
- **`header_text`** — AUROC=1.0000, null_rate=0.0213 — AUROC=1.0000 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심
- **`mutation_type`** — AUROC=1.0000, null_rate=0.9942 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`mutation_mutated_field`** — AUROC=1.0000, null_rate=0.9942 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`mutation_original_value`** — AUROC=1.0000, null_rate=0.9942 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`mutation_mutated_value`** — AUROC=1.0000, null_rate=0.9942 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`mutation_reason`** — AUROC=1.0000, null_rate=0.9942 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`detection_surface_hints`** — AUROC=1.0000, null_rate=0.9990 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`document_number`** — AUROC=1.0000, null_rate=0.0000 — AUROC=1.0000 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심
- **`reference`** — AUROC=0.9990, null_rate=0.0189 — AUROC=0.9990 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심
- **`ip_address`** — AUROC=0.9824, null_rate=0.0000 — AUROC=0.9824 ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심
- **`semantic_scenario_id`** — AUROC=0.6289, null_rate=0.0000 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`mutation_base_event_type`** — AUROC=0.6289, null_rate=0.0000 — 도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카
- **`delivery_date`** — AUROC=0.5000, null_rate=0.9999 — null_rate=0.9999 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류)
- **`settlement_status`** — AUROC=0.5000, null_rate=1.0000 — null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류)
- **`sod_conflict_type`** — AUROC=0.5000, null_rate=1.0000 — null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류)
- **`amount_open`** — AUROC=0.5000, null_rate=1.0000 — null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류)
- **`is_cleared`** — AUROC=0.5000, null_rate=1.0000 — null_rate=1.0000 가 정상행 비율 0.9990 와 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류)
