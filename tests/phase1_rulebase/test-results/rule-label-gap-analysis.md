# Phase 1 Detection Rules vs DataSynth Labels: Gap Analysis (v8)

> 최종 검증: 2026-03-28 | DataSynth 1,105,110행 | 26개 룰 | 라벨 7,899건

## 1. 현재 상태

```
Phase 1 Recall: 91.4% (2,386 / 2,610)
전체    Recall: 90.8% (7,171 / 7,899)
Precision:       7.7% (7,171 / 92,663)
```

**코드 버그 의심 0건.** 라벨 데이터 전수조사 완료.

| 분류                 | 룰 수 | 룰 목록                                                    |
|----------------------|-------:|-------------------------------------------------------------|
| Recall 100%          |     15 | A01, A02, A03, B01, B06, B07, B08, B09, B11, C04, C05, C08, C10(없음), C12(없음) |
| Recall 80~99%        |      6 | B02(84%), B03(91%), B04(88%), C01(80%), C03(86%), C06(93%) |
| Recall 30~79%        |      1 | C07(33%), C11(91%)                                          |
| Recall 1~29%         |      3 | B05(9%), B10(7%), C09(10%)                                  |
| 라벨 없음 (정상)      |      3 | C02, C10, C12 — 대응 라벨 타입 미존재                        |

## 2. 데이터 품질 전수조사 결과

### 2.1 이상(abnormal) 라벨 검증 — 라벨이 진짜 이상 데이터인가

| 룰   | 라벨 | 검증OK | 비율  | 검증 기준                                    |
|------|-----:|-------:|------:|----------------------------------------------|
| A01  |    1 |      1 | 100%  | sum(DR) != sum(CR)                           |
| A02  |   21 |     21 | 100%  | 최소 1개 필수필드 NULL                        |
| A03  |    7 |      7 | 100%  | 최소 1행 무효 GL (CoA 미등록)                 |
| B01  |    8 |      8 | 100%  | 최소 1행 4xxx GL                              |
| B06  |    1 |      1 | 100%  | created_by == approved_by                    |
| B07  |    3 |      3 | 100%  | sod_violation=true                           |
| B08  |    1 |      1 | 100%  | source=manual                                |
| B09  |    2 |      2 | 100%  | approved_by=NULL                             |
| B11  |   12 |     12 | 100%  | 자산GL(15xx) + 비용GL(5~8xxx) 공존           |
| C03  |  196 |    196 | 100%  | posting_time 22~06시                         |
| C04  |   10 |     10 | 100%  | posting_date - document_date < -30일         |
| C06  |   14 |     14 | 100%  | 공백/누락/3자미만 적요 또는 위험 키워드       |
| C11  |   11 |     11 | 100%  | 동일 GL+금액 DR/CR 반전 쌍 존재              |

**결론: 검증 대상 전 룰 100% 통과. 라벨된 문서는 모두 실제 이상 특성 보유.**

### 2.2 정상(normal) 데이터 오염 검사 — 정상 데이터에 이상이 섞여있는가

정상 데이터(is_fraud=false AND is_anomaly=false) 1,003,624행 대상.

| 검사 항목           |      건수 | 판정     | 설명                                              |
|---------------------|----------:|----------|---------------------------------------------------|
| A01 차대변 불일치   |         3 | 점검필요 | 정상 문서인데 DR != CR. float 반올림 또는 데이터 오류 |
| A03 무효 GL         |         0 | OK       | 정상 데이터에 무효 GL 없음                         |
| A02 NULL GL         |    19,955 | 허용     | nullable 스키마. A02 탐지 대상이지만 라벨 미부여   |
| B06 자기승인        |    90,658 | 허용     | DataSynth 설계상 자기승인 비율 ~9%. 라벨은 1건만   |
| B07 SoD 위반        |   102,596 | 허용     | DataSynth sod_violation=true ~10%. 라벨은 3건만    |
| B08 수기+고액       |    11,732 | 허용     | 수기+고액 자체는 탐지 조건. 라벨과 무관하게 플래그됨 |
| B09 승인생략        |         0 | OK       | 정상 데이터에 승인생략 없음                        |
| C02 주말전기        |    96,327 | 허용     | DataSynth 주말 전기 ~9.6%. 탐지는 정상 작동(154K행) |
| C03 심야전기        |    26,175 | 허용     | DataSynth 심야 비율 ~2.6%. 탐지는 정상 작동(20K행) |
| C04 소급전기        |         0 | OK       | 정상 데이터에 소급전기 없음                        |

**핵심 발견:**
- **A01 3건**: 정상 데이터에 차대변 불일치 존재. DataSynth 생성 오류 가능성.
- **B06/B07/B08/C02/C03**: 정상 데이터에 다수 존재하지만, 이는 **탐지 조건 ≠ 라벨 조건**. 탐지 룰은 이 행들을 플래그하고, 라벨은 "의도적 부정/이상"인 건에만 부여. 정상 데이터의 자기승인은 업무상 허용된 건이므로 오염이 아님.
- **A02 NULL GL 19,955행**: nullable 허용 후 A02 룰이 탐지하지만 라벨 미부여. DataSynth가 A02 라벨을 21건만 부여한 것은 "의도적 NULL 주입" 문서에만 한정한 것.

## 3. 룰별 Recall / Precision 전체

```
룰    sev  라벨타입 *                   라벨   탐지행    탐지문서    TP      FP     FN  Recall  Prec
──── ──── ──────────────────────────── ───── ──────── ──────── ───── ─────── ───── ────── ─────
A01    5   UnbalancedEntry                1      580       85     1      84     0   100%    1%
A02    2   MissingField                  21   49,429   11,811    21  11,790     0   100%    0%
A03    3   InvalidAccount                 7   22,047    9,892     7   9,885     0   100%    0%
B01    5   RevenueManipulation            8      933      882     8     874     0   100%    1%
B02    3   JustBelowThreshold            31    4,530    2,812    26   2,786     5    84%    1%
B03    3   ExceededApprovalLimit         23   49,821   20,058    21  20,037     2    91%    0%
B04    3   DuplicatePayment               8    1,182      302     7     295     1    88%    2%
B05    3   DuplicateEntry *             134   54,486      878    12     866   122     9%    1%
B06    3   SelfApproval                   1    1,412      594     1     593     0   100%    0%
B07    4   SegregationOfDutiesViolation   3   31,252    4,569     3   4,566     0   100%    0%
B08    4   ManualOverride                 1   15,023    6,494     1   6,493     0   100%    0%
B09    4   SkippedApproval                2        9        4     2       2     0   100%   50%
B10    4   CircularIntercompany *       643   14,170    7,107    48   7,059   595     7%    1%
B11    4   ImproperCapitalization        12    2,288      114    12     102     0   100%   11%
C01    3   RushedPeriodEnd               10  145,552   39,230     8  39,222     2    80%    0%
C02    2   WeekendPosting                 0  154,100   15,732     0  15,732     0     --    0%
C03    2   AfterHoursPosting *          196   20,674    1,755   169   1,586    27    86%   10%
C04    3   BackdatedEntry *              28      196       38    28      10     0   100%   74%
C05    4   WrongPeriod                   10      196       38    10      28     0   100%   26%
C06    1   VagueDescription              14   25,278   12,615    13  12,602     1    93%    0%
C07    2   BenfordViolation             154  362,437   59,280    51  59,229   103    33%    0%
C08    3   UnusuallyHighAmount *        253    4,445    2,599   253   2,346     0   100%   10%
C09    2   UnusualAccountPair          1039    6,205      385   104     281   935    10%   27%
C10    3   (없음)                          0    4,644    2,883     0   2,883     0     --    0%
C11    4   ReversedAmount                11    1,041      552    10     542     1    91%    2%
C12    3   (없음)                          0    6,397      183     0     183     0     --    0%
```

\* 복수 라벨타입 매핑 룰: B05(+ExactDuplicateAmount), B10(+CircularTransaction),
C03(+UnusualTiming), C04(+LatePosting), C08(+StatisticalOutlier). 전체 매핑은 e2e-label-validation.md 참조.

## 4. 잔존 갭 분석

### 4.1 DataSynth 라벨-데이터 불일치 (소수 FN, 수정 가능)

| 룰   | Recall | 라벨 | FN | 근본 원인                                                  |
|------|-------:|-----:|---:|-------------------------------------------------------------|
| B02  |    84% |   31 |  5 | 금액이 한도x0.90~0.99 범위 밖                                |
| B03  |    91% |   23 |  2 | 금액이 최소 한도 미초과                                      |
| C01  |    80% |   10 |  2 | posting_date가 월말 5일 이내 아니거나 금액 < Q3              |
| C03  |    86% |  196 | 27 | 라벨은 "야간"이나 posting_time이 업무시간 내                  |
| B04  |    88% |    8 |  1 | 동일 vendor+금액 쌍 미형성                                   |
| C06  |    93% |   14 |  1 | line_text에 위험 키워드 미포함 (공백/누락 아닌 경우)          |
| C11  |    91% |   11 |  1 | dr<->cr 반전 쌍 미형성                                       |

### 4.2 구조적 한계 → ML/DL 필요

| 룰   | Recall | 라벨 | FN  | 룰 한계                                   | Phase |
|------|-------:|-----:|----:|---------------------------------------------|:------|
| B05  |     9% |  134 | 122 | exact match만 → 유사/분할 거래 미탐        | 2 (WU-05) |
| B10  |     7% |  643 | 595 | 2-hop만, 640건 trading_partner NULL         | 3 (#72) |
| C09  |    10% | 1039 | 935 | 빈도 기반만 → 도메인상 이상 조합 미탐(~56%) | 2 (WU-02) |
| C07  |    33% |  154 | 103 | 행 단위 탐지 vs 문서 단위 라벨 기준 불일치  | 2 (WU-09) |

### 4.3 라벨 미존재 (탐지는 정상 작동)

| 룰   | 탐지행    | 상태                                              |
|------|----------:|---------------------------------------------------|
| C02  |   154,100 | WeekendPosting 라벨 0건. 탐지 정상, 검증 불가     |
| C10  |     4,644 | SuspenseAccountAbuse 라벨 0건. 탐지 정상           |
| C12  |     6,397 | AbnormalHoursConcentration 라벨 0건. 탐지 정상     |

## 5. 레이어별 탐지 현황

### 위험등급 분포

| 등급   |      건수 |    비율 |
|--------|----------:|--------:|
| High   |    12,856 |   1.2%  |
| Medium |    57,711 |   5.2%  |
| Low    |   118,493 |  10.7%  |
| Normal |   916,050 |  82.9%  |

### 레이어별 성능

| 단계               |   소요(s) | 룰 수 |
|--------------------|----------:|------:|
| Layer A (무결성)    |     0.879 |     3 |
| Layer B (부정)      |     1.978 |    11 |
| Layer C (이상징후)  |    16.013 |    11 |
| Benford (독립)      |     7.014 |     1 |
| Score Aggregator   |     1.493 |     0 |

## 6. Phase 1 미커버 라벨 (Phase 2/3 대상)

| anomaly_type              |   건수 | 대상      |
|---------------------------|-------:|-----------|
| NewCounterparty           |  1,317 | Phase 2/3 |
| MissingRelationship       |    877 | Phase 2/3 |
| DormantAccountActivity    |    834 | Phase 2/3 |
| UnmatchedIntercompany     |    711 | Phase 2/3 |
| CentralityAnomaly         |    447 | Phase 2/3 |
| TransferPricingAnomaly    |    446 | Phase 2/3 |
| UnusualFrequency          |    131 | Phase 2/3 |
| RepeatingAmount           |    112 | Phase 2/3 |
| TransactionBurst          |    106 | Phase 2/3 |
| UnusuallyLowAmount        |     76 | Phase 2/3 |
| TrendBreak                |     65 | Phase 2/3 |
| 기타 13종                 |    167 | Phase 2/3 |

## 7. 변경 이력

### 7.1 탐지 엔진 수정 (2026-03-26)

| 수정                        | 파일                              | 효과                     |
|-----------------------------|-----------------------------------|--------------------------|
| exceeds_threshold multi-tier| `src/feature/amount_features.py`  | B03: 4->50,144, B08: 2->15,101 |
| B09 approved_by NULL 조건   | `src/detection/fraud_rules_access.py` | 승인 있는 전표 오탐 제거 |
| A03 CoA 자동 로딩           | `src/detection/integrity_layer.py`| A03 SKIP->21,845행 탐지    |

### 7.2 인프라 수정 (2026-03-27)

| 파일                                 | 변경                                         |
|--------------------------------------|------------------------------------------------|
| `src/validation/schema_validator.py` | gl_account, document_type nullable=True 전환    |
| `src/db/schema.py`                   | gl_account NOT NULL -> VARCHAR (nullable)       |
| `src/db/loader.py`                   | _extract_benford: benford 독립 트랙 지원 추가   |

### 7.3 int64 오버플로 방어 (2026-03-28)

| 파일                                 | 변경                                         |
|--------------------------------------|------------------------------------------------|
| `src/feature/amount_features.py`     | `_compute_base_amount`: to_numeric 방어 추가    |
| `src/feature/pattern_features.py`    | `add_first_digit`: to_numeric 방어 추가         |
| `tests/phase1_rulebase/test_e2e_label_validation.py` | load_data: dtype 명시           |

### 7.4 DataSynth 재생성 + 전수조사 (2026-03-28, v8)

1,105,110행, 7,899 라벨. v7 대비 주요 변화:
- B01: 88% -> **100%** (GL NaN 수정)
- 라벨 데이터 전수조사: 검증 대상 13개 룰 **전부 100% 통과**
- 정상 데이터 오염: A01 3건(차대변 불일치) 발견. 나머지는 DataSynth 설계 의도 내.

## 8. 전체 테스트 결과 (2026-03-28)

| 테스트                    | 결과       | 비고                        |
|---------------------------|------------|-----------------------------|
| E2E 라벨 검증 (26룰)      | PASS       | Phase 1 Recall 91.4%        |
| 라벨 데이터 전수조사       | PASS       | 13룰 검증 전부 100%         |
| 정상 데이터 오염검사       | PASS(주의) | A01 3건 점검필요            |
