# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-04-26 11:10

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,109,435               |
| 소요시간       | 26.14s              |
| 생성 피처      | 39/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 2.9%     |
| is_after_hours          | bool    |      0.0 |      2 | True 2.2%     |
| is_period_end           | bool    |      0.0 |      2 | True 45.5%    |
| days_backdated          | Int64   |      0.0 |    104 | [-30, 90]     |
| fiscal_period_mismatch  | boolean |      0.0 |      2 |               |
| is_holiday              | bool    |      0.0 |      2 | True 4.9%     |
| time_zone_category      | object  |      0.0 |      3 |               |
| is_near_threshold       | bool    |      0.0 |      1 | True 0.0%     |
| near_threshold_amount   | float64 |      0.0 | 260637 | [0.0, 100000000000.0] |
| near_threshold_limit_amount | float64 |    100.0 |      0 | 전체 NaN        |
| near_threshold_limit_resolved | bool    |      0.0 |      1 | True 0.0%     |
| near_threshold_ratio_to_limit | float64 |    100.0 |      0 | 전체 NaN        |
| near_threshold_gap_amount | float64 |    100.0 |      0 | 전체 NaN        |
| near_threshold_gap_ratio | float64 |    100.0 |      0 | 전체 NaN        |
| near_threshold_bucket   | object  |      0.0 |      1 |               |
| exceeds_threshold       | bool    |      0.0 |      2 | True 19.7%    |
| document_approval_amount | float64 |      0.0 | 260637 | [0.0, 100000000000.0] |
| approver_limit_amount   | float64 |    100.0 |      0 | 전체 NaN        |
| approval_limit_resolved | bool    |      0.0 |      1 | True 0.0%     |
| approver_can_approve_je | boolean |    100.0 |      0 |               |
| approval_excess_amount  | float64 |      0.0 |  60367 | [0.0, 99990000000.0] |
| approval_excess_ratio   | float64 |     80.3 |  60367 | [0.0, 9999.0] |
| approval_excess_bucket  | object  |      0.0 |      2 |               |
| amount_zscore           | float64 |      0.0 | 1031590 | [-1.607810105367811, 103.1286737174288] |
| amount_magnitude        | float64 |      0.0 | 501564 | [0.0, 11.000000000004343] |
| is_round_number         | bool    |      0.0 |      2 | True 0.1%     |
| is_manual_je            | bool    |      0.0 |      2 | True 69.8%    |
| is_intercompany         | bool    |      0.0 |      2 | True 3.5%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 17.2%    |
| first_digit             | Int64   |      0.0 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      2 | True 1.4%     |
| description_quality     | object  |      0.0 |      3 |               |
| description_line_missing | bool    |      0.0 |      2 | True 2.2%     |
| description_header_missing | bool    |      0.0 |      2 | True 2.2%     |
| description_both_missing | bool    |      0.0 |      2 | True 0.0%     |
| description_line_missing_header_present | bool    |      0.0 |      2 | True 2.1%     |
| description_is_missing_or_corrupted | bool    |      0.0 |      2 | True 1.8%     |
| has_risk_keyword        | object  |      0.0 |      1 |               |
| morpheme_tokens         | object  |      0.0 |      1 |               |

## 3. 분석

### 코드 버그 (조사 필요)

- **near_threshold_limit_amount**: 전체 NaN — 입력 데이터 또는 로직 확인 필요
- **near_threshold_ratio_to_limit**: 전체 NaN — 입력 데이터 또는 로직 확인 필요
- **near_threshold_gap_amount**: 전체 NaN — 입력 데이터 또는 로직 확인 필요
- **near_threshold_gap_ratio**: 전체 NaN — 입력 데이터 또는 로직 확인 필요
- **approver_limit_amount**: 전체 NaN — 입력 데이터 또는 로직 확인 필요
- **approver_can_approve_je**: 전체 NaN — 입력 데이터 또는 로직 확인 필요

### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)

- `is_near_threshold`: all-False
- `near_threshold_limit_resolved`: all-False
- `approval_limit_resolved`: all-False

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      1.250 |       7 |
| amount   | 성공     |      2.688 |      19 |
| pattern  | 성공     |      4.797 |       5 |
| text     | 성공     |     17.406 |       8 |
| **합계** |        |     26.141 |      39 |