# DB E2E 테스트 결과 (DataSynth 1,103,464행)

> 실행일: 2026-03-22 13:14 | **12/12 검증 통과**

---

## 1. 요약

| 항목                       |                    값 |
|:------------------------|--------------------:|
| 입력 행 수                   |            1,103,464 |
| GL 적재                    |            1,103,464 |
| AF 적재                    |            3,193,095 |
| Benford summary          |                    1 |
| Benford digits           |                    9 |
| 총 적재 행                   |            4,296,569 |
| 적재 소요                    |                3.17s |
| 전체 소요 (적재+쿼리)            |               22.43s |

---

## 2. 소요시간

```
단계                         소요(s)
────────────────────  ──────────
data_load                  3.463
feature                    6.739
detection                  5.721
db_load                    3.180
queries                    3.324
────────────────────  ──────────
합계                        22.427
```

---

## 3. 검증 결과

|  # | 검증 항목                            |                   기대 |                   실제 | 결과   |
|---:|:--------------------------------|--------------------:|--------------------:|:----:|
|  1 | GL 행 수 일치                        |              1103464 |              1103464 | PASS |
|  2 | AF 행 수 > 0                       |                  > 0 |              3193095 | PASS |
|  3 | AF 적재 수 == 조회 수                  |              3193095 |              3193095 | PASS |
|  4 | Benford summary 1행               |                    1 |                    1 | PASS |
|  5 | Benford digits 9행                |                    9 |                    9 | PASS |
|  6 | Benford deviation 정합             |            obs - exp |                   일치 | PASS |
|  7 | VIEW 쿼리 행 > 0                    |                  > 0 |                   17 | PASS |
|  8 | VIEW flagged_count 합 == AF 행 수   |              3193095 |              3193095 | PASS |
|  9 | risk_level 분포                    |                1+ 등급 | {'Low', 'Medium', 'High'} | PASS |
| 10 | anomaly_score 범위 [0,1]           |           [0.0, 1.0] |     [0.3600, 0.7500] | PASS |
| 11 | 드릴다운 쿼리 결과 > 0                   | > 0 (doc=d99f8271-0e72-4d84-a82b-a7c50c87b1a7) |                   15 | PASS |
| 12 | 드릴다운 컬럼 정합                       | {'rule_code', 'track_name', 'score'} | {'rule_code', 'track_name', 'score'} | PASS |

---

## 4. 쿼리별 조회 결과

```
쿼리명                              행 수      컬럼 수
────────────────────────  ──────────  ────────
batch_ledger               1,103,464        17
batch_flags                3,193,095         5
benford_summary                    1         9
benford_digits                     9         4
rule_violation_stats              17         5
document_rule_detail              15         3
```

---

## 5. risk_level 분포

| 등급         |         건수 |       비율 |
|:----------|----------:|--------:|
| High       |         64 |    0.01% |
| Medium     |    591,780 |   53.63% |
| Low        |    511,620 |   46.36% |
| Normal     |          0 |    0.00% |

---

## 6. anomaly_flags 트랙별 분포

| 트랙           |        행 수 |  avg_score |  max_score |
|:------------|----------:|----------:|----------:|
| layer_a      |         64 |     1.0000 |     1.0000 |
| layer_b      |  2,492,550 |     0.7772 |     1.0000 |
| layer_c      |    700,481 |     0.4357 |     0.8000 |

---

## 7. 룰별 위반 통계 (상위 10)

| 트랙         | 룰        |         건수 |  avg_score |  max_score |
|:----------|:--------|----------:|----------:|----------:|
| layer_b    | B10      |  1,103,464 |     0.8000 |     0.8000 |
| layer_b    | B07      |  1,103,041 |     0.8000 |     0.8000 |
| layer_c    | C03      |    470,530 |     0.4000 |     0.4000 |
| layer_b    | B06      |    236,442 |     0.6000 |     0.6000 |
| layer_c    | C01      |    143,341 |     0.6000 |     0.6000 |
| layer_c    | C02      |     51,903 |     0.4000 |     0.4000 |
| layer_b    | B05      |     48,615 |     0.6000 |     0.6000 |
| layer_c    | C06      |     25,404 |     0.2000 |     0.2000 |
| layer_c    | C08      |      4,741 |     0.6000 |     0.6000 |
| layer_c    | C09      |      3,421 |     0.4000 |     0.4000 |

---

## 8. Benford 분석 요약

| 항목                   |                값 |
|:--------------------|----------------:|
| sample_size          |        1,080,205 |
| MAD                  |         0.001411 |
| MAD conformity       |            close |
| Chi² statistic       |         240.7119 |
| Chi² p-value         |           0.0000 |
| KS statistic         |           0.0061 |
| KS p-value           |           0.0000 |
| is_conforming        |            False |
| confidence           |             high |

---

## 9. 드릴다운 예시 (document_id=d99f8271-0e72-4d84-a82b-a7c50c87b1a7)

| 트랙           | 룰        |    score |
|:------------|:--------|--------:|
| layer_a      | A01      |   1.0000 |
| layer_a      | A01      |   1.0000 |
| layer_b      | B01      |   1.0000 |
| layer_b      | B10      |   0.8000 |
| layer_b      | B10      |   0.8000 |
| layer_b      | B07      |   0.8000 |
| layer_b      | B07      |   0.8000 |
| layer_c      | C08      |   0.6000 |
| layer_c      | C08      |   0.6000 |
| layer_b      | B06      |   0.6000 |
| layer_b      | B06      |   0.6000 |
| layer_c      | C01      |   0.6000 |
| layer_c      | C01      |   0.6000 |
| layer_c      | C06      |   0.2000 |
| layer_c      | C06      |   0.2000 |

---

## 10. 관련 문서

| 문서 | 내용 |
|:-----|:-----|
| [docs/pre-plan/06-db.md](../../../docs/pre-plan/06-db.md) | DB 레이어 설계 |
| [db-all-results.md](db-all-results.md) | DB unit test 결과 (34 passed) |
| [e2e-detection-datasynth.md](../../test_detection/test-results/e2e-detection-datasynth.md) | Detection E2E 결과 |
