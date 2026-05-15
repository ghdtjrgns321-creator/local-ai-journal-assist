# DataSynth Text and Document Family Design

## Purpose
Header text and line text must be generated from the selected accounting event scenario's allowed text families. Normal generation must not select text directly from broad account subtype pools such as `CostOfGoodsSold` or `OperatingExpenses`.

This prevents:
- `CostOfGoodsSold` causing direct labor text on any process.
- `OperatingExpenses` causing payroll text on P2P vendor invoices.

## Current Problem
`tools/datasynth/crates/datasynth-core/src/templates/descriptions.rs` currently exposes `generate_line_text(gl_account, sub_type, context, rng)`. When `sub_type` is present, the method selects from `sub_type_line_pool(sub_type)`. Because `AccountSubType::CostOfGoodsSold` and `AccountSubType::OperatingExpenses` contain incompatible business meanings, this lets normal data combine valid GL classes with invalid text semantics.

## Required Normal Flow
1. `JournalEntryGenerator` selects `AccountingEventScenario`.
2. The scenario supplies `allowed_header_families` and `allowed_line_text_families`.
3. Account selection resolves a `SemanticAccountSubtype`.
4. Text generation receives `(event_type, semantic_subtype, line_text_family, document_type, counterparty_type)`.
5. Text generation picks from the matching family pool only.
6. Semantic validator confirms `line_text_family` is allowed for both the scenario and semantic account subtype.

## Required API Direction
Add scenario-aware methods in `descriptions.rs`:
- `generate_header_text_for_family(header_family, context, rng)`
- `generate_line_text_for_family(line_text_family, semantic_subtype, context, rng)`

Normal `JournalEntryGenerator` must not call the old subtype-global `generate_line_text()` path. Keep the old method only for legacy tests, explicit fallback tests, or abnormal mutation support.

## LineTextFamily Pools

| LineTextFamily | Allowed examples | Forbidden contexts |
| --- | --- | --- |
| `OFFICE_SUPPLIES_PURCHASE` | `사무용품`, `문구류`, `복사용지`, `토너`, `프린터 소모품` | payroll accrual, direct labor, depreciation |
| `MATERIAL_PURCHASE` | `원재료 매입`, `자재 입고`, `부품 매입` | payroll accrual, customer invoice |
| `RAW_MATERIAL_PURCHASE` | `원재료 입고`, `철강 소재 매입`, `화학 원료 매입` | payroll accrual, office supplier invoice |
| `PROFESSIONAL_FEES` | `전문용역비`, `회계 자문료`, `법률 자문료`, `컨설팅 비용` | payroll salary, direct labor |
| `UTILITIES` | `전기요금`, `가스요금`, `수도요금`, `통신요금` | payroll salary, customer invoice |
| `REPAIRS` | `수선비`, `설비 정비`, `시설 유지보수` | payroll salary, direct labor |
| `VENDOR_PAYMENT` | `매입채무 지급`, `거래처 대금 지급`, `지급 실행` | payroll register, customer receipt |
| `PAYROLL_SALARY` | `급여`, `상여`, `미지급급여`, `급여 충당` | P2P vendor invoice, office supplier, raw material vendor |
| `DIRECT_LABOR_PAYROLL` | `직접노무비`, `생산직 급여`, `현장 인건비`, `제조 노무비` | P2P vendor invoice, office supplier, purchase tax invoice |
| `PAYROLL_TAX` | `근로소득세`, `4대보험`, `원천세`, `급여세 미지급` | ordinary vendor invoice, office supplier |
| `EMPLOYEE_BENEFITS` | `복리후생비`, `퇴직급여`, `건강보험료`, `연금 부담금` | office supplier invoice, customer invoice |
| `CUSTOMER_BILLING` | `매출 세금계산서`, `고객 청구`, `제품 매출`, `용역 매출` | non-O2C process, non-customer counterparty |
| `CUSTOMER_RECEIPT` | `매출대금 입금`, `고객 수금`, `채권 회수` | vendor payment, payroll payment |
| `ACCRUAL` | `미지급비용 설정`, `월말 발생액`, `비용 발생분 계상` | source purchase invoice unless scenario explicitly allows vendor accrual |
| `REVERSAL` | `전표 역분개`, `발생액 취소`, `전월 accrual reversal` | independent random account selection |
| `ASSET_ACQUISITION` | `유형자산 취득`, `설비 취득`, `CAPEX 계상` | payroll accrual, customer invoice |
| `DEPRECIATION` | `감가상각비`, `감가상각누계액`, `월차 감가상각`, `상각비 계상` | AP vendor invoice, purchase invoice, payroll register |
| `LOAN_DRAWDOWN` | `차입금 실행`, `대출금 입금`, `은행 차입` | ordinary purchase vendor |
| `INTEREST_PAYMENT` | `이자비용 지급`, `차입금 이자`, `금융비용 지급` | office supplier, payroll provider |
| `INTERCOMPANY_SALE` | `관계사 매출`, `내부거래 청구`, `IC invoice` | external customer/vendor |
| `INTERCOMPANY_SETTLEMENT` | `관계사 정산`, `IC settlement`, `내부채권 정리` | employee, ordinary vendor |

## Explicit Allowed Examples
- `P2P_VENDOR_INVOICE + OPEX_OFFICE_SUPPLIES -> OFFICE_SUPPLIES_PURCHASE -> 사무용품, 문구류, 복사용지`
- `H2R_PAYROLL_ACCRUAL + OPEX_PAYROLL -> PAYROLL_SALARY -> 급여, 상여, 미지급급여`
- `H2R_PAYROLL_ACCRUAL + COGS_DIRECT_LABOR -> DIRECT_LABOR_PAYROLL -> 직접노무비, 생산직 급여`
- `A2R_DEPRECIATION -> DEPRECIATION -> 감가상각비, 감가상각누계액`

## Header Families
Header text follows the same scenario rule. It must describe the scenario, not only the business process.

| Header family | Valid scenarios | Examples |
| --- | --- | --- |
| `PURCHASE_INVOICE_HEADER` | `P2P_VENDOR_INVOICE` | `매입 세금계산서`, `구매 송장`, `입고 정산` |
| `VENDOR_PAYMENT_HEADER` | `P2P_PAYMENT` | `거래처 대금 지급`, `매입채무 지급` |
| `PAYROLL_ACCRUAL_HEADER` | `H2R_PAYROLL_ACCRUAL` | `급여 발생액`, `미지급급여 설정`, `급여 배부` |
| `PAYROLL_PAYMENT_HEADER` | `H2R_PAYROLL_PAYMENT` | `급여 지급`, `원천세 납부`, `4대보험 납부` |
| `CUSTOMER_INVOICE_HEADER` | `O2C_CUSTOMER_INVOICE` | `매출 세금계산서`, `고객 청구` |
| `CUSTOMER_RECEIPT_HEADER` | `O2C_CASH_RECEIPT` | `매출대금 입금`, `채권 회수` |
| `ACCRUAL_HEADER` | `R2R_ACCRUAL` | `월말 발생액`, `미지급비용 설정` |
| `REVERSAL_HEADER` | `R2R_REVERSAL` | `역분개`, `전월 발생액 취소` |
| `ASSET_ACQUISITION_HEADER` | `A2R_ASSET_ACQUISITION` | `자산 취득`, `CAPEX 계상` |
| `DEPRECIATION_HEADER` | `A2R_DEPRECIATION` | `감가상각 실행`, `월차 상각` |
| `TREASURY_HEADER` | Treasury events | `차입금 실행`, `이자 지급`, `은행 거래` |
| `INTERCOMPANY_HEADER` | Intercompany events | `관계사 거래`, `IC 정산` |

## Validator Rules
- `line_text_family` must be one of `scenario.allowed_line_text_families`.
- `header_family` must be one of `scenario.allowed_header_families`.
- `CostOfGoodsSold` alone never authorizes `DIRECT_LABOR_PAYROLL`.
- `OperatingExpenses` alone never authorizes `PAYROLL_SALARY`.
- `DIRECT_LABOR_PAYROLL` requires semantic subtype `COGS_DIRECT_LABOR` and an H2R/R2R/manufacturing scenario.
- `PAYROLL_SALARY` requires semantic subtype `OPEX_PAYROLL` and an H2R/R2R scenario.
- `OFFICE_SUPPLIES_PURCHASE` requires semantic subtype `OPEX_OFFICE_SUPPLIES`, P2P process, office supplier counterparty, and AP/GRIR credit.
- `DEPRECIATION` requires A2R depreciation or R2R depreciation adjustment, and must not use AP vendor invoice documents.

## Rust Work Items
- Add `HeaderTextFamily` enum alongside `LineTextFamily`.
- Add family-specific text pools in `descriptions.rs`.
- Add scenario-aware text generation methods.
- Change `JournalEntryGenerator` normal path to pass scenario text families into `DescriptionGenerator`.
- Deprecate normal use of `sub_type_line_pool()` for broad COGS/OPEX accounts.
- Add unit tests proving the four explicit allowed examples and the two forbidden global-pool cases.
