# DB E2E 테스트 결과 (DataSynth 1,104,914행)

> 실행일: 2026-03-27 12:17 | **12/12 검증 통과**

---

## 1. 요약

| 항목                       |                    값 |
|:------------------------|--------------------:|
| 입력 행 수                   |            1,104,914 |
| GL 적재                    |            1,104,914 |
| AF 적재                    |              975,226 |
| Benford summary          |                    1 |
| Benford digits           |                    9 |
| 총 적재 행                   |            2,080,429 |
| 적재 소요                    |                3.81s |
| 전체 소요 (적재+쿼리)            |               51.03s |

---

## 2. 소요시간

```
단계                         소요(s)
────────────────────  ──────────
data_load                  5.785
feature                    9.681
detection                 28.640
db_load                    3.817
queries                    3.111
────────────────────  ──────────
합계                        51.034
```

---

## 3. 검증 결과

|  # | 검증 항목                            |                   기대 |                   실제 | 결과   |
|---:|:--------------------------------|--------------------:|--------------------:|:----:|
|  1 | GL 행 수 일치                        |              1105193 |              1105193 | PASS |
|  2 | AF 행 수 > 0                       |                  > 0 |               975226 | PASS |
|  3 | AF 적재 수 == 조회 수                  |               975226 |               975226 | PASS |
|  4 | Benford summary 1행               |                    1 |                    1 | PASS |
|  5 | Benford digits 9행                |                    9 |                    9 | PASS |
|  6 | Benford deviation 정합             |            obs - exp |                   일치 | PASS |
|  7 | VIEW 쿼리 행 > 0                    |                  > 0 |                   26 | PASS |
|  8 | VIEW flagged_count 합 == AF 행 수   |               975226 |               975226 | PASS |
|  9 | risk_level 분포                    |                1+ 등급 | {'High', 'Medium', 'Low', 'Normal'} | PASS |
| 10 | anomaly_score 범위 [0,1]           |           [0.0, 1.0] |     [0.0000, 0.7700] | PASS |
| 11 | 드릴다운 쿼리 결과 > 0                   | > 0 (doc=744d4109-a306-49fa-b6c0-30567899e060) |                  431 | PASS |
| 12 | 드릴다운 컬럼 정합                       | {'track_name', 'score', 'rule_code'} | {'track_name', 'score', 'rule_code'} | PASS |

---

## 4. 쿼리별 조회 결과

```
쿼리명                              행 수      컬럼 수
────────────────────────  ──────────  ────────
batch_ledger               1,104,914        29
batch_flags                  975,226         5
benford_summary                    1         9
benford_digits                     9         4
rule_violation_stats              26         5
document_rule_detail             431         3
```

---

## 5. risk_level 분포

| 등급         |         건수 |       비율 |
|:----------|----------:|--------:|
| High       |     12,575 |    1.14% |
| Medium     |     64,353 |    5.82% |
| Low        |    123,346 |   11.16% |
| Normal     |    904,919 |   81.88% |

---

## 6. anomaly_flags 트랙별 분포

| 트랙           |        행 수 |  avg_score |  max_score |
|:------------|----------:|----------:|----------:|
| benford      |    357,887 |     0.4000 |     0.4000 |
| layer_a      |     64,229 |     0.4716 |     1.0000 |
| layer_b      |    189,166 |     0.6828 |     1.0000 |
| layer_c      |    363,944 |     0.4762 |     0.8000 |

---

## 7. 룰별 위반 통계 (상위 10)

| 트랙         | 룰        |         건수 |  avg_score |  max_score |
|:----------|:--------|----------:|----------:|----------:|
| benford    | L4-02      |    357,887 |     0.4000 |     0.4000 |
| layer_c    | L3-05      |    154,259 |     0.4000 |     0.4000 |
| layer_c    | L3-04      |    145,645 |     0.6000 |     0.6000 |
| layer_b    | L2-03      |     54,433 |     0.6000 |     0.6000 |
| layer_b    | L1-04      |     50,144 |     0.6000 |     0.6000 |
| layer_b    | L1-06      |     44,072 |     0.8000 |     0.8000 |
| layer_a    | L1-02      |     42,001 |     0.4000 |     0.4000 |
| layer_c    | L3-08      |     25,110 |     0.2000 |     0.2000 |
| layer_a    | L1-03      |     21,845 |     0.6000 |     0.6000 |
| layer_c    | L3-06      |     18,846 |     0.4000 |     0.4000 |

---

## 8. Benford 분석 요약

| 항목                   |                값 |
|:--------------------|----------------:|
| sample_size          |        1,054,705 |
| MAD                  |         0.004087 |
| MAD conformity       |            close |
| Chi² statistic       |        1867.7993 |
| Chi² p-value         |           0.0000 |
| KS statistic         |           0.0181 |
| KS p-value           |           0.0000 |
| is_conforming        |            False |
| confidence           |             high |

---

## 9. 드릴다운 예시 (document_id=744d4109-a306-49fa-b6c0-30567899e060)

| 트랙           | 룰        |    score |
|:------------|:--------|--------:|
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_a      | L1-01      |   1.0000 |
| layer_b      | L3-03      |   0.8000 |
| layer_b      | L3-03      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L2-06      |   0.8000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_c      | L3-04      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_b      | L2-03      |   0.6000 |
| layer_a      | L1-03      |   0.6000 |
| layer_a      | L1-03      |   0.6000 |
| layer_a      | L1-03      |   0.6000 |
| layer_a      | L1-03      |   0.6000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| benford      | L4-02      |   0.4000 |
| layer_a      | L1-02      |   0.4000 |
| layer_a      | L1-02      |   0.4000 |
| layer_a      | L1-02      |   0.4000 |
| layer_a      | L1-02      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |
| layer_c      | L4-04      |   0.4000 |

---

## 10. 관련 문서

| 문서 | 내용 |
|:-----|:-----|
| [docs/archive/completed/raw-plan/06-db.md](../../../../docs/archive/completed/raw-plan/06-db.md) | DB 레이어 설계 |
| [db-all-results.md](db-all-results.md) | DB unit test 결과 (34 passed) |
| [e2e-detection-datasynth.md](../../test_detection/test-results/e2e-detection-datasynth.md) | Detection E2E 결과 |
