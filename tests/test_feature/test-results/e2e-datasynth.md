# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-03-25 23:14

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,106,356               |
| 소요시간       | 8.23s              |
| 생성 피처      | 18/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 10.0%    |
| is_after_hours          | bool    |      0.0 |      2 | True 1.1%     |
| is_period_end           | bool    |      0.0 |      2 | True 52.6%    |
| days_backdated          | Int64   |      0.0 |     26 | [-32, 32]     |
| fiscal_period_mismatch  | boolean |      0.0 |      2 |               |
| is_holiday              | bool    |      0.0 |      2 | True 5.6%     |
| is_near_threshold       | bool    |      0.0 |      2 | True 0.4%     |
| exceeds_threshold       | bool    |      0.0 |      2 | True 0.0%     |
| amount_zscore           | float64 |      0.0 | 1007950 | [-0.9806420054242793, 63.898432039477] |
| amount_magnitude        | float64 |      0.0 | 362039 | [0.0, 10.897607243342696] |
| is_round_number         | bool    |      0.0 |      2 | True 0.0%     |
| is_manual_je            | bool    |      0.0 |      2 | True 25.8%    |
| is_intercompany         | bool    |      0.0 |      2 | True 1.3%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 20.2%    |
| first_digit             | Int64   |      0.0 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      2 | True 0.4%     |
| description_quality     | object  |      0.0 |      2 |               |
| has_risk_keyword        | object  |      0.0 |      1 |               |

## 3. 분석

### 코드 버그

없음.

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      0.735 |       6 |
| amount   | 성공     |      0.328 |       5 |
| pattern  | 성공     |      3.937 |       5 |
| text     | 성공     |      3.235 |       2 |
| **합계** |        |      8.235 |      18 |