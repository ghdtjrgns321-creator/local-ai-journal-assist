# SAP-Merged (Graceful Degradation) E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-05-08 19:22

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 331,934               |
| 소요시간       | 1.92s              |
| 생성 피처      | 20/18 |
| 성공 카테고리  | time, pattern, text |
| 실패 카테고리  | amount |
| 필수 미매핑    | credit_amount |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 19.6%    |
| is_after_hours          | bool    |      0.0 |      1 | True 0.0%     |
| is_period_end           | bool    |      0.0 |      2 | True 36.7%    |
| days_backdated          | Int64   |      0.0 |     31 | [-730, 365]   |
| fiscal_period_mismatch  | boolean |      0.0 |      1 |               |
| is_holiday              | bool    |      0.0 |      2 | True 2.8%     |
| time_zone_category      | object  |      0.0 |      1 |               |
| is_near_threshold       | —       |       — |    — | 의도된 스킵   |
| near_threshold_amount   | —       |       — |    — | 의도된 스킵   |
| near_threshold_limit_amount | —       |       — |    — | 의도된 스킵   |
| near_threshold_limit_resolved | —       |       — |    — | 의도된 스킵   |
| near_threshold_ratio_to_limit | —       |       — |    — | 의도된 스킵   |
| near_threshold_gap_amount | —       |       — |    — | 의도된 스킵   |
| near_threshold_gap_ratio | —       |       — |    — | 의도된 스킵   |
| near_threshold_bucket   | —       |       — |    — | 의도된 스킵   |
| exceeds_threshold       | —       |       — |    — | 의도된 스킵   |
| document_approval_amount | —       |       — |    — | 의도된 스킵   |
| approver_limit_amount   | —       |       — |    — | 의도된 스킵   |
| approval_limit_resolved | —       |       — |    — | 의도된 스킵   |
| approver_can_approve_je | —       |       — |    — | 의도된 스킵   |
| approval_excess_amount  | —       |       — |    — | 의도된 스킵   |
| approval_excess_ratio   | —       |       — |    — | 의도된 스킵   |
| approval_excess_bucket  | —       |       — |    — | 의도된 스킵   |
| amount_zscore           | —       |       — |    — | 의도된 스킵   |
| amount_magnitude        | —       |       — |    — | 의도된 스킵   |
| is_round_number         | —       |       — |    — | 의도된 스킵   |
| is_manual_je            | bool    |      0.0 |      1 | True 0.0%     |
| is_intercompany         | bool    |      0.0 |      1 | True 0.0%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 7.1%     |
| first_digit             | Int64   |    100.0 |      0 | 전체 NaN        |
| is_suspense_account     | bool    |      0.0 |      1 | True 0.0%     |
| description_quality     | object  |      0.0 |      2 |               |
| description_line_missing | bool    |      0.0 |      2 | True 100.0%   |
| description_header_missing | bool    |      0.0 |      1 | True 100.0%   |
| description_both_missing | bool    |      0.0 |      2 | True 100.0%   |
| description_line_missing_header_present | bool    |      0.0 |      1 | True 0.0%     |
| description_is_missing_or_corrupted | bool    |      0.0 |      2 | True 100.0%   |
| has_risk_keyword        | object  |      0.0 |      1 |               |
| morpheme_tokens         | object  |      0.0 |      1 |               |

## 3. 분석

### 코드 버그

없음.

### Graceful Degradation (정상 — 필수 컬럼 미매핑)

원인: `credit_amount` 미매핑 → 의존 피처 생성 불가

- `is_near_threshold`: 미생성 (amount 카테고리 스킵)
- `near_threshold_amount`: 미생성 (amount 카테고리 스킵)
- `near_threshold_limit_amount`: 미생성 (amount 카테고리 스킵)
- `near_threshold_limit_resolved`: 미생성 (amount 카테고리 스킵)
- `near_threshold_ratio_to_limit`: 미생성 (amount 카테고리 스킵)
- `near_threshold_gap_amount`: 미생성 (amount 카테고리 스킵)
- `near_threshold_gap_ratio`: 미생성 (amount 카테고리 스킵)
- `near_threshold_bucket`: 미생성 (amount 카테고리 스킵)
- `exceeds_threshold`: 미생성 (amount 카테고리 스킵)
- `document_approval_amount`: 미생성 (amount 카테고리 스킵)
- `approver_limit_amount`: 미생성 (amount 카테고리 스킵)
- `approval_limit_resolved`: 미생성 (amount 카테고리 스킵)
- `approver_can_approve_je`: 미생성 (amount 카테고리 스킵)
- `approval_excess_amount`: 미생성 (amount 카테고리 스킵)
- `approval_excess_ratio`: 미생성 (amount 카테고리 스킵)
- `approval_excess_bucket`: 미생성 (amount 카테고리 스킵)
- `amount_zscore`: 미생성 (amount 카테고리 스킵)
- `amount_magnitude`: 미생성 (amount 카테고리 스킵)
- `is_round_number`: 미생성 (amount 카테고리 스킵)
- `first_digit`: 전체 NaN (금액 컬럼 부재)

> Phase 1c 매핑 리뷰 UI에서 수동 조정 시 해결됩니다.

### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)

- `is_after_hours`: all-False
- `fiscal_period_mismatch`: all-False
- `is_manual_je`: all-False
- `is_intercompany`: all-False
- `is_suspense_account`: all-False
- `description_header_missing`: all-True
- `description_line_missing_header_present`: all-False

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      0.250 |       7 |
| amount   | 스킵     |      0.000 |      19 |
| pattern  | 성공     |      0.453 |       5 |
| text     | 성공     |      1.218 |       8 |
| **합계** |        |      1.921 |      20 |