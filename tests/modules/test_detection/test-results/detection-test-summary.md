# Detection 테스트 결과 통합 리포트

> 실행일: 2026-03-26 | 단위 235 passed, 0 failed | E2E 1,104,914행 완료 (27개 룰, DataSynth v2 L1-02/L2-04/L2-06 패턴 주입)

---

## 1. 단위 테스트 요약

```
모듈                                      테스트 수   결과     소요시간
──────────────────────────────────────────────────────────────
base.py                                         7   PASS     0.02s
integrity_layer.py (L1-01~L1-03)                   18   PASS     0.08s
fraud_rules_feature.py (L4-01~L1-04,L3-02)           12   PASS     0.04s
fraud_rules_groupby.py (L2-02,L2-03,L2-04)           16   PASS     0.06s
fraud_rules_access.py (L1-05~L3-03)                16   PASS     0.04s
fraud_layer.py (오케스트레이터)                  8   PASS     0.10s
anomaly_rules_simple.py (L3-04~L4-03,L3-09)          26   PASS     0.03s
anomaly_rules_statistical.py (L4-02,L4-04)          9   PASS     0.05s
anomaly_layer.py (오케스트레이터)               10   PASS     0.08s
benford_detector.py (L4-02 독립)                  8   PASS     0.04s
score_aggregator.py                            12   PASS     0.03s
c12_abnormal_hours.py (피처+룰+E2E)            49   PASS     54.4s
constants.py                                   15   PASS     0.02s
──────────────────────────────────────────────────────────────
합계                                          206   ALL PASS  55.1s
  (+ DataSynth E2E 3건: L4-05 skip 없음/플래그율/비정상시간 검증)
```

---

## 2. E2E 테스트 (DataSynth v2, 1,104,914행)

```
입력: 1,104,914행 | 39컬럼 | 피처 생성: 9.12s | 탐지: 25.10s | 총: 39.76s
```

### 룰별 탐지 결과

```
L1 (확정 오류/위반)
  L1-01  차대변 균형        263건   0.02%   sev=5
  L1-02  필수필드 누락   41,993건   3.80%   sev=2   ← DataSynth v2 NULL 주입 (이전 0건)
  L1-03  무효 계정        skipped          ← CoA 미제공 (Graceful Degradation)

L2 (강한 부정 정황)
  L4-01  매출 이상 변동    1,075건   0.10%   sev=5
  L2-01  승인한도 직하     4,542건   0.41%   sev=3   ← 6단계 한도 반영 (이전 0건)
  L1-04  승인한도 초과         4건   0.00%   sev=3
  L2-02  중복 지급           965건   0.09%   sev=3   ← P2P 필터 + 고유키 대조 (이전 16.67%)
  L2-03  중복 전표        54,201건   4.91%   sev=3
  L1-05  자기 승인         1,429건   0.13%   sev=3   ← automated+소액 제외 (이전 10.08%)
  L1-06  직무분리 위반    31,240건   2.83%   sev=4   ← 하이브리드 SoD (이전 99.96% → 0.54%)
  L3-02  수기 전표             2건   0.00%   sev=4
  L1-07  승인 생략             2건   0.00%   sev=4
  L3-03  관계사 순환거래  14,157건   1.28%   sev=4
  L2-04  비용 자산화       2,199건   0.20%   sev=4   ← DataSynth v2 6xxx→15xx 주입 (이전 0건)

L3/L4 (검토·통계)
  L3-04  기말 대규모     145,577건  13.18%   sev=3
  L3-05  주말 전기       154,204건  13.96%   sev=2
  L3-06  심야 전기        18,843건   1.71%   sev=2   ← 이전 42.83% → 1.05% (시간정보 정상화)
  L3-07  소급 전기            20건   0.00%   sev=3
  L1-08  기간 불일치          90건   0.01%   sev=4
  L3-08  위험 적요        25,106건   2.27%   sev=1
  L4-03  이상 고액         4,862건   0.44%   sev=3
  L4-04  비정상 계정조합   2,886건   0.26%   sev=2
  L3-09  가수금 장기체류   4,635건   0.42%   sev=3
  L2-06  역분개 패턴         819건   0.07%   sev=4   ← DataSynth v2 상계쌍 생성 (이전 2건)
  L4-05  비정상시간 집중   6,395건   0.58%   sev=3   ← 사용자별 3σ + 급속승인

Benford (독립 트랙)
  L4-02  Benford 위반   357,472건  32.35%   sev=2   ← 계정별 분리 검정 (이전 31.63%)
```

### 위험등급 분포

```
High:      11,322건  ( 1.02%)
Medium:    29,705건  ( 2.69%)
Low:      115,961건  (10.50%)
Normal:   947,926건  (85.79%)
```

### Label 대조 (Ground Truth)

```
실제 anomaly(문서):  8,001건
탐지 flagged(문서): 90,622건
Recall:              87.7%
Precision:            7.7%
```

### 레이어별 소요시간

```
L1:          0.56s (2 룰, L1-03 skip)
L2:          1.92s (11 룰)
L3/L4:         14.86s (11 룰, L2-06 역분개 + L4-05 비정상시간 집중)
Benford:          6.30s (1 룰, 계정별 분리 검정)
Score Aggregator: 1.46s
총: ~40s
```

---

## 3. DataSynth 버전별 비교

| 지표         | v1.0       | L1-06 하이브리드 | L2-02+L4-02 정밀화 | L1-05 정밀화   | DataSynth v2 (현재) |
|:-------------|:-----------|:--------------|:--------------|:------------|:-------------------|
| L1-02          | 0.00%      | 0.00%         | 0.00%         | 0.00%       | **3.80%**          |
| L2-02          | 16.67%     | 16.67%        | **0.20%**     | 0.20%       | 0.09%              |
| L1-05          | 10.08%     | 10.08%        | 10.08%        | **0.14%**   | 0.13%              |
| L1-06          | 99.96%     | 0.54%         | 0.54%         | 0.54%       | 2.83%              |
| L2-04          | 0.00%      | 0.00%         | 0.00%         | 0.00%       | **0.20%**          |
| L4-02          | 31.63%     | 31.63%        | **33.17%**    | 33.17%      | 32.35%             |
| L2-06          | 0.00%      | 0.00%         | 0.00%         | 0.13%       | **0.07%**          |
| Normal       | 18.4%      | 70.5%         | 83.2%         | 91.4%       | **85.8%**          |
| Recall       | 100%       | 94.1%         | 90.1%         | 89.0%       | **87.7%**          |
| Precision    | 7.5%       | 7.8%          | 8.1%          | 8.2%        | **7.7%**           |

---

## 4. 문제점 분류

### 과탐 (flagged > 50%)

해당 없음. L1-06 하이브리드 SoD 적용으로 과탐 해소 (99.96% → 0.54%).

### 데이터 특성 (코드 정상, 패턴 미주입)

해당 없음. DataSynth v2에서 L1-02/L2-04/L2-06 패턴 모두 주입 완료 — 전 룰 1건 이상 탐지.

### Graceful Degradation (정상)

| 룰  | 설명                          |
|:----|:------------------------------|
| L1-03 | chart_of_accounts 미제공 → skip |

---

## 5. 모듈별 단위 테스트 상세

### L1: 데이터 무결성 (18 tests)

```
TestA01UnbalancedEntry   — 6개 (균형/불균형/tolerance경계/NaN처리/skip)
TestA02MissingRequired   — 3개 (정상/NULL/다중NULL)
TestA03InvalidAccount    — 4개 (유효/무효/CoA미제공/int-str호환)
TestDetectIntegration    — 5개 (반환타입/max scoring/skipped/elapsed/빈DF)
```

### L2: 부정 탐지 (48 tests)

```
TestL4-01 — 4개 (매출+고zscore/저zscore/비매출/피처미존재)
TestL2-01 — 3개 (near_threshold/not/미존재)
TestL1-04 — 2개 (exceeds/not)
TestL2-02 — 9개 (윈도우내/초과/다른거래처/컬럼미존재/3건중복/30일경계/O2C제외/같은ref다른doc/같은ref같은doc)
TestL2-03 — 4개 (exact match/날짜다름/GL다름/컬럼미존재)
TestL1-05 — 7개 (인간고액TP/automated제외TN/소액제외TN/대변금액평가/fallback/created_by미존재/NaN persona)
TestL1-06 — 8개 (toxic pair/in-process/junior초과/controller safe/controller toxic/fallback/automated제외/컬럼미존재)
TestL3-02 — 3개 (수기+초과/수기만/초과만)
TestL1-07 — 2개 (초과+비자동/컬럼미존재)
TestL3-03 — 3개 (관계사/단일회사/컬럼미존재)
TestL2-04 — 6개 (자산↔비용/no_match/asset_only/expense_only/missing/partial)
FraudLayer통합 — 8개 (반환타입/scores max/minimal/빈DF/rule_flags/L4-01상세/컬럼명/flagged정합)
```

### L3/L4: 이상 징후 (102 tests)

```
TestL3-04 — 4개 (기말+고액/기말+저액/비기말/피처미존재)
TestL3-05 — 3개 (주말/공휴일/평일)
TestL3-06 — 3개 (심야/업무시간/피처미존재)
TestL3-07 — 3개 (abs>30양방향/abs≤30/피처미존재)
TestL1-08 — 2개 (불일치/일치)
TestL3-08 — 4개 (missing/poor/high risk/normal)
TestL4-02 — 4개 (적합/비적합선별/피처미존재/튜플반환)
TestL4-03 — 3개 (abs>3/≤3/피처미존재)
TestL4-04 — 5개 (희소쌍/빈번쌍/N:M복합/컬럼미존재/빈차변)
TestL3-09 — 4개 (suspense flagged/all_false/NaN/피처미존재)
TestL4-05 — 49개:
  피처(time_zone_category) — 21개 (normal/overtime/midnight/경계값6개/결산기보정5개/주말3개/시간없음2개/초정밀2개)
  사용자 집중도 — 5개 (3σ 이상치/std=0/저비율/컬럼누락2개)
  소수 인원 폴백 — 2개 (건수미달/건수+비율충족)
  급속 승인 — 7개 (수기심야/자동심야/수기정상/자기승인/automated/approval없음/source대체3개)
  플래그 대상 — 2개 (비정상행만/정상행 미포함)
  min_user_entries — 3개 (소수표본제외/충분건수/임계변경)
  DataSynth E2E — 3개 (skip없음/플래그율범위/비정상시간검증)
  통합 — 2개 (레지스트리등록/detect실행)
BenfordDetector — 8개 (track_name/반환타입/scores범위/적합0점/metadata/L4-02/graceful/빈DF)
AnomalyLayer통합 — 10개 (반환타입/scores범위/NaN없음/C prefix/rule_flags/flagged정합/elapsed/minimal/빈DF/L4-02미포함)
```

### Score Aggregator (12 tests)

```
TestAggregateScores   — 3개 (기본가중합/누락레이어/커스텀가중치)
TestClassifyRiskLevel — 4개 (High/Medium/Low/Normal 경계값)
TestAutoEscalation    — 2개 (승격발동/미발동)
TestFlaggedRules      — 1개 (comma-separated 형식)
TestEdgeCases         — 2개 (score clamp/비연속 인덱스 보존)
```

---

## 6. 후속 작업

| 항목 | 대상 | 상태 |
|------|------|------|
| constants 테스트 | 27개 룰 RULE_CODES/SEVERITY_MAP 검증 15 passed | 해결 |
| L4-05 단위+E2E | 49 passed (피처 21 + 룰 17 + DataSynth E2E 3 + 통합 8) | 해결 |
| L4-05 DataSynth 결과 | 25,342건 (2.29%), 비정상 시간대 행만 플래그 확인 | 해결 |
| Relational 8유형 | Phase 2 ML/그래프 모듈 (TASKS Phase 2c) | Phase 2 |
