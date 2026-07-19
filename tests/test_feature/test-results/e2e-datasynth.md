# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-05-10 16:24

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,109,435               |
| 소요시간       | 37.91s              |
| 생성 피처      | 39/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 2.9%     |
| is_after_hours          | bool    |      0.0 |      2 | True 2.3%     |
| is_period_end           | bool    |      0.0 |      2 | True 45.5%    |
| days_backdated          | Int64   |      0.0 |    363 | [-274, 362]   |
| fiscal_period_mismatch  | boolean |      0.0 |      2 |               |
| is_holiday              | bool    |      0.0 |      2 | True 5.0%     |
| time_zone_category      | object  |      0.0 |      4 |               |
| is_near_threshold       | bool    |      0.0 |      2 | True 0.1%     |
| near_threshold_amount   | float64 |      0.0 | 260581 | [0.0, 100000000000.0] |
| near_threshold_limit_amount | float64 |     24.0 |      6 | [10000000.0, 50000000000.0] |
| near_threshold_limit_resolved | bool    |      0.0 |      2 | True 76.0%    |
| near_threshold_ratio_to_limit | float64 |     24.0 | 218113 | [0.0, 3.3]    |
| near_threshold_gap_amount | float64 |     24.0 | 218158 | [-50000000000.0, 50000000000.0] |
| near_threshold_gap_ratio | float64 |     24.0 | 218113 | [-2.3, 1.0]   |
| near_threshold_bucket   | object  |      0.0 |      5 |               |
| exceeds_threshold       | bool    |      0.0 |      2 | True 0.0%     |
| document_approval_amount | float64 |      0.0 | 260581 | [0.0, 100000000000.0] |
| approver_limit_amount   | float64 |     24.0 |      6 | [10000000.0, 50000000000.0] |
| approval_limit_resolved | bool    |      0.0 |      2 | True 76.0%    |
| approver_can_approve_je | boolean |     24.0 |      1 |               |
| approval_excess_amount  | float64 |      0.0 |     10 | [0.0, 50000000000.0] |
| approval_excess_ratio   | float64 |    100.0 |      6 | [0.1, 2.3]    |
| approval_excess_bucket  | object  |      0.0 |      5 |               |
| amount_zscore           | float64 |      0.0 | 1031658 | [-1.607810105367811, 103.09223464499284] |
| amount_magnitude        | float64 |      0.0 | 501479 | [0.0, 11.000000000004343] |
| is_round_number         | bool    |      0.0 |      2 | True 0.1%     |
| is_manual_je            | bool    |      0.0 |      2 | True 26.0%    |
| is_intercompany         | bool    |      0.0 |      2 | True 3.5%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 17.2%    |
| first_digit             | Int64   |      0.0 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      2 | True 1.6%     |
| description_quality     | object  |      0.0 |      3 |               |
| description_line_missing | bool    |      0.0 |      2 | True 2.2%     |
| description_header_missing | bool    |      0.0 |      2 | True 2.2%     |
| description_both_missing | bool    |      0.0 |      2 | True 0.0%     |
| description_line_missing_header_present | bool    |      0.0 |      2 | True 2.1%     |
| description_is_missing_or_corrupted | bool    |      0.0 |      2 | True 0.1%     |
| has_risk_keyword        | object  |      0.0 |      3 |               |
| morpheme_tokens         | object  |      0.0 | 214273 |               |

## 3. 분석

### 코드 버그

없음.

### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)

- `approver_can_approve_je`: all-<NA>

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      1.406 |       7 |
| amount   | 성공     |      4.016 |      19 |
| pattern  | 성공     |      3.984 |       5 |
| text     | 성공     |     28.500 |       8 |
| **합계** |        |     37.906 |      39 |