# DataSynth E2E 테스트 결과 (ingest → feature)

> 역사 문서. 현재 실사용 기준본은 `data/journal/primary/datasynth/`의 `v20.3` freeze다. 아래 수치는 2026-03-30 당시의 DataSynth 상태를 기록한 것이다.

> 실행일: 2026-03-30 17:02

## 1. 요약

| 항목           | 값                          |
|:---------------|:----------------------------|
| 입력 행수      | 1,108,294               |
| 소요시간       | 10.34s              |
| 생성 피처      | 19/18 |
| 카테고리 실행  | time, amount, pattern, text |

## 2. 피처별 분포

| 피처                    | dtype   | null율(%) | unique | 비고          |
|:------------------------|:--------|----------:|-------:|:--------------|
| is_weekend              | bool    |      0.0 |      2 | True 9.0%     |
| is_after_hours          | bool    |      0.0 |      2 | True 1.3%     |
| is_period_end           | bool    |      0.0 |      2 | True 55.1%    |
| days_backdated          | Int64   |      0.0 |     48 | [-86, 60]     |
| fiscal_period_mismatch  | boolean |      0.0 |      2 |               |
| is_holiday              | bool    |      0.0 |      2 | True 6.5%     |
| time_zone_category      | object  |      0.0 |      3 |               |
| is_near_threshold       | bool    |      0.0 |      2 | True 0.1%     |
| exceeds_threshold       | bool    |      0.0 |      2 | True 0.8%     |
| amount_zscore           | float64 |      0.0 | 633410 | [-0.2626210502142634, 71.83238110288403] |
| amount_magnitude        | float64 |      0.0 | 103407 | [0.0, 10.989591920137462] |
| is_round_number         | bool    |      0.0 |      2 | True 0.2%     |
| is_manual_je            | bool    |      0.0 |      2 | True 24.3%    |
| is_intercompany         | bool    |      0.0 |      2 | True 1.3%     |
| is_revenue_account      | bool    |      0.0 |      2 | True 19.6%    |
| first_digit             | Int64   |      4.6 |      9 | [1, 9]        |
| is_suspense_account     | bool    |      0.0 |      2 | True 1.3%     |
| description_quality     | object  |      0.0 |      3 |               |
| has_risk_keyword        | object  |      0.0 |      1 |               |

## 3. 분석

### 코드 버그

없음.

## 4. 카테고리별 성능

| 카테고리 | 상태   | 소요시간(s) | 피처 수 |
|:---------|:------:|------------:|--------:|
| time     | 성공     |      1.312 |       7 |
| amount   | 성공     |      0.329 |       5 |
| pattern  | 성공     |      4.734 |       5 |
| text     | 성공     |      3.969 |       2 |
| **합계** |        |     10.344 |      19 |
> Historical report. Current production DataSynth baseline is `data/journal/primary/datasynth/` freeze `v23` as of 2026-04-22.
