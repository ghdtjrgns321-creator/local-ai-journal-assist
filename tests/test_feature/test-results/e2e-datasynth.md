# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-03-28 14:08

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 565,867               |
| 소요시간       | 6.61s              |
| 생성 피처      | 19/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 7.5%     |
| is_after_hours          | bool    |      0.0 |      2 | True 1.8%     |
| is_period_end           | bool    |      0.0 |      2 | True 51.9%    |
| days_backdated          | Int64   |      0.0 |     20 | [-21, 32]     |
| fiscal_period_mismatch  | boolean |      0.0 |      2 |               |
| is_holiday              | bool    |      0.0 |      2 | True 5.5%     |
| time_zone_category      | object  |      0.0 |      3 |               |
| is_near_threshold       | bool    |      0.0 |      2 | True 0.4%     |
| exceeds_threshold       | bool    |      0.0 |      2 | True 4.4%     |
| amount_zscore           | float64 |      0.0 | 492973 | [-1.4883722454350288, 55.9440816488279] |
| amount_magnitude        | float64 |      0.0 | 207363 | [0.0, 10.324021449547121] |
| is_round_number         | bool    |      0.0 |      2 | True 1.5%     |
| is_manual_je            | bool    |      0.0 |      2 | True 25.5%    |
| is_intercompany         | bool    |      0.0 |      2 | True 1.3%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 19.8%    |
| first_digit             | Int64   |      3.9 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      2 | True 0.4%     |
| description_quality     | object  |      0.0 |      3 |               |
| has_risk_keyword        | object  |      0.0 |      1 |               |

## 3. 분석

### 코드 버그

없음.

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      0.922 |       7 |
| amount   | 성공     |      0.250 |       5 |
| pattern  | 성공     |      3.031 |       5 |
| text     | 성공     |      2.406 |       2 |
| **합계** |        |      6.609 |      19 |