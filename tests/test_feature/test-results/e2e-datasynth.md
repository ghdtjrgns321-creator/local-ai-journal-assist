# DataSynth E2E 테스트 결과 (ingest → feature)

> 실행일: 2026-03-21 11:44

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,068,119               |
| 소요시간       | 6.14s              |
| 생성 피처      | 18/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 0.1%     |
| is_after_hours          | bool    |      0.0 |      1 | True 0.0%     |
| is_period_end           | bool    |      0.0 |      2 | True 51.9%    |
| days_backdated          | Int64   |      0.0 |     47 | [-32, 32]     |
| fiscal_period_mismatch  | boolean |      0.0 |      1 |               |
| is_holiday              | bool    |      0.0 |      2 | True 4.6%     |
| is_near_threshold       | bool    |      0.0 |      1 | True 0.0%     |
| exceeds_threshold       | bool    |      0.0 |      2 | True 0.0%     |
| amount_zscore           | float64 |      0.0 | 757580 | [-1.3900268842458892, 64.30380650567724] |
| amount_magnitude        | float64 |      0.0 | 176412 | [0.0, 8.792844160878836] |
| is_round_number         | bool    |      0.0 |      1 | True 0.0%     |
| is_manual_je            | bool    |      0.0 |      2 | True 21.6%    |
| is_intercompany         | bool    |      0.0 |      1 | True 0.0%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 20.3%    |
| first_digit             | Int64   |      2.1 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      1 | True 0.0%     |
| description_quality     | object  |      0.0 |      3 |               |
| has_risk_keyword        | object  |      0.0 |      1 |               |

## 3. 분석

### 코드 버그

없음.

### 데이터 특성 (코드 정상, 데이터에 해당 패턴 부재)

- `is_after_hours`: all-False
- `fiscal_period_mismatch`: all-True
- `is_near_threshold`: all-False
- `is_round_number`: all-False
- `is_intercompany`: all-False
- `is_suspense_account`: all-False

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      0.828 |       6 |
| amount   | 성공     |      0.203 |       5 |
| pattern  | 성공     |      2.125 |       5 |
| text     | 성공     |      2.984 |       2 |
| **합계** |        |      6.140 |      18 |