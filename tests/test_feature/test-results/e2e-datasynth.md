# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-04-24 12:02

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,109,221               |
| 소요시간       | 51.30s              |
| 생성 피처      | 20/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 2.6%     |
| is_after_hours          | bool    |      0.0 |      2 | True 1.8%     |
| is_period_end           | bool    |      0.0 |      2 | True 44.4%    |
| days_backdated          | Int64   |      0.0 |     75 | [-7, 90]      |
| fiscal_period_mismatch  | boolean |      0.0 |      2 |               |
| is_holiday              | bool    |      0.0 |      2 | True 5.1%     |
| time_zone_category      | object  |      0.0 |      3 |               |
| is_near_threshold       | bool    |      0.0 |      1 | True 0.0%     |
| exceeds_threshold       | bool    |      0.0 |      2 | True 20.2%    |
| amount_zscore           | float64 |      0.0 | 1029797 | [-1.6078101053678107, 102.42109078259743] |
| amount_magnitude        | float64 |      0.0 | 501050 | [0.0, 11.000000000004343] |
| is_round_number         | bool    |      0.0 |      2 | True 0.1%     |
| is_manual_je            | bool    |      0.0 |      2 | True 69.4%    |
| is_intercompany         | bool    |      0.0 |      2 | True 1.2%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 17.0%    |
| first_digit             | Int64   |      0.0 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      2 | True 1.6%     |
| description_quality     | object  |      0.0 |      3 |               |
| has_risk_keyword        | object  |      0.0 |      3 |               |
| morpheme_tokens         | object  |      0.0 | 216446 |               |

## 3. 분석

### 코드 버그

없음.

### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)

- `is_near_threshold`: all-False

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      1.625 |       7 |
| amount   | 성공     |      3.344 |       5 |
| pattern  | 성공     |      4.734 |       5 |
| text     | 성공     |     41.594 |       3 |
| **합계** |        |     51.297 |      20 |