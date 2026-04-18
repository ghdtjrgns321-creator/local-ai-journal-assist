# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-04-16 22:29

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,107,720               |
| 소요시간       | 51.97s              |
| 생성 피처      | 20/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 2.8%     |
| is_after_hours          | bool    |      0.0 |      2 | True 2.2%     |
| is_period_end           | bool    |      0.0 |      2 | True 44.1%    |
| days_backdated          | Int64   |      0.0 |     23 | [0, 73]       |
| fiscal_period_mismatch  | boolean |      0.0 |      2 |               |
| is_holiday              | bool    |      0.0 |      2 | True 5.0%     |
| time_zone_category      | object  |      0.0 |      3 |               |
| is_near_threshold       | bool    |      0.0 |      2 | True 1.0%     |
| exceeds_threshold       | bool    |      0.0 |      2 | True 12.7%    |
| amount_zscore           | float64 |      0.0 | 1032013 | [-1.818538411029885, 128.45848289645343] |
| amount_magnitude        | float64 |      0.0 | 502380 | [0.0, 11.000000000004343] |
| is_round_number         | bool    |      0.0 |      2 | True 0.0%     |
| is_manual_je            | bool    |      0.0 |      2 | True 70.2%    |
| is_intercompany         | bool    |      0.0 |      2 | True 1.1%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 16.3%    |
| first_digit             | Int64   |      0.0 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      2 | True 1.7%     |
| description_quality     | object  |      0.0 |      2 |               |
| has_risk_keyword        | object  |      0.0 |      3 |               |
| morpheme_tokens         | object  |      0.0 | 177299 |               |

## 3. 분석

### 코드 버그

없음.

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      1.344 |       7 |
| amount   | 성공     |      1.906 |       5 |
| pattern  | 성공     |      7.625 |       5 |
| text     | 성공     |     41.094 |       3 |
| **합계** |        |     51.969 |      20 |