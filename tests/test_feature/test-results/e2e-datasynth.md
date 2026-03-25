# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-03-22 14:07

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,101,677               |
| 소요시간       | 8.02s              |
| 생성 피처      | 18/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 0.1%     |
| is_after_hours          | bool    |      0.0 |      2 | True 42.8%    |
| is_period_end           | bool    |      0.0 |      2 | True 52.2%    |
| days_backdated          | Int64   |      0.0 |     22 | [-18, 32]     |
| fiscal_period_mismatch  | boolean |      0.0 |      1 |               |
| is_holiday              | bool    |      0.0 |      2 | True 4.9%     |
| is_near_threshold       | bool    |      0.0 |      1 | True 0.0%     |
| exceeds_threshold       | bool    |      0.0 |      2 | True 0.0%     |
| amount_zscore           | float64 |      0.0 | 774442 | [-0.6434518010690728, 64.58475157890368] |
| amount_magnitude        | float64 |      0.0 | 184093 | [0.0, 7.930564533306971] |
| is_round_number         | bool    |      0.0 |      1 | True 0.0%     |
| is_manual_je            | bool    |      0.0 |      2 | True 21.2%    |
| is_intercompany         | bool    |      0.0 |      1 | True 0.0%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 20.3%    |
| first_digit             | Int64   |      2.1 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      1 | True 0.0%     |
| description_quality     | object  |      0.0 |      2 |               |
| has_risk_keyword        | object  |      0.0 |      1 |               |

## 3. 분석

### 코드 버그

없음.

### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)

- `fiscal_period_mismatch`: all-True
- `is_near_threshold`: all-False
- `is_round_number`: all-False
- `is_intercompany`: all-False
- `is_suspense_account`: all-False

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      1.110 |       6 |
| amount   | 성공     |      0.328 |       5 |
| pattern  | 성공     |      2.953 |       5 |
| text     | 성공     |      3.625 |       2 |
| **합계** |        |      8.016 |      18 |