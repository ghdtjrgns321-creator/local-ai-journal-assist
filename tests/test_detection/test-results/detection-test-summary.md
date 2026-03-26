# Detection 테스트 결과 통합 리포트

> 실행일: 2026-03-26 | 단위 143 passed, 0 failed | E2E 1,106,356행 완료 (24개 룰, B07 하이브리드 SoD)

---

## 1. 단위 테스트 요약

```
모듈                                      테스트 수   결과     소요시간
──────────────────────────────────────────────────────────────
base.py                                         7   PASS     0.02s
integrity_layer.py (A01~A03)                   18   PASS     0.08s
fraud_rules_feature.py (B01~B03,B08)           12   PASS     0.04s
fraud_rules_groupby.py (B04,B05,B11)           16   PASS     0.06s
fraud_rules_access.py (B06~B10)                12   PASS     0.04s
fraud_layer.py (오케스트레이터)                  8   PASS     0.10s
anomaly_rules_simple.py (C01~C08,C10)          26   PASS     0.03s
anomaly_rules_statistical.py (C07,C09)          9   PASS     0.05s
anomaly_layer.py (오케스트레이터)               10   PASS     0.08s
benford_detector.py (C07 독립)                  8   PASS     0.04s
score_aggregator.py                            12   PASS     0.03s
──────────────────────────────────────────────────────────────
합계                                          138   ALL PASS  1.30s
```

---

## 2. E2E 테스트 (DataSynth v1.2.0, 1,106,356행)

```
입력: 1,106,356행 | 39컬럼 | 피처 생성: 8.26s | 탐지: 5.56s | 총: 19.37s
```

### 룰별 탐지 결과

```
Layer A (무결성)
  A01  차대변 균형        140건   0.01%   sev=5
  A02  필수필드 누락        0건   0.00%   sev=2   ← 패턴 미주입 (정상)
  A03  무효 계정        skipped          ← CoA 미제공 (Graceful Degradation)

Layer B (부정)
  B01  매출 이상 변동      966건   0.09%   sev=5
  B02  승인한도 직하     4,351건   0.39%   sev=3   ← 6단계 한도 반영 (이전 0건)
  B03  승인한도 초과         4건   0.00%   sev=3
  B04  중복 지급       184,460건  16.67%   sev=3
  B05  중복 전표        15,945건   1.44%   sev=3
  B06  자기 승인       111,569건  10.08%   sev=3
  B07  직무분리 위반     5,990건   0.54%   sev=4   ← 하이브리드 SoD (이전 99.96% → 0.54%)
  B08  수기 전표             2건   0.00%   sev=4
  B09  승인 생략             2건   0.00%   sev=4
  B10  관계사 순환거래  14,504건   1.31%   sev=4
  B11  비용 자산화           0건   0.00%   sev=4   ← 패턴 미주입 (정상)

Layer C (이상 징후)
  C01  기말 대규모     143,612건  12.98%   sev=3
  C02  주말 전기       167,626건  15.15%   sev=2
  C03  심야 전기        11,636건   1.05%   sev=2   ← 이전 42.83% → 1.05% (시간정보 정상화)
  C04  소급 전기           126건   0.01%   sev=3
  C05  기간 불일치         185건   0.02%   sev=4
  C06  위험 적요        25,077건   2.27%   sev=1
  C08  이상 고액         5,047건   0.46%   sev=3
  C09  비정상 계정조합   3,570건   0.32%   sev=2
  C10  가수금 장기체류   4,282건   0.39%   sev=3   ← 신규 룰, 정상 탐지

Benford (독립 트랙)
  C07  Benford 위반   349,925건  31.63%   sev=2
```

### 위험등급 분포

```
High:     38건  ( 0.00%)
Medium: 429,013건  (38.78%)
Low:    473,631건  (42.81%)
Normal: 203,674건  (18.41%)
```

### Label 대조 (Ground Truth)

```
실제 anomaly(문서):  7,959건
탐지 flagged(문서): 103,483건
True Positive:       7,824건
Recall:              98.3%
Precision:            7.6%
```

| 카테고리     | 실제   | 탐지   | Recall |
|:------------|-------:|-------:|-------:|
| Error       |    180 |    179 |  99.4% |
| Fraud       |    155 |    152 |  98.1% |
| ProcessIssue|     74 |     71 |  95.9% |
| Relational  |  6,328 |  6,219 |  98.3% |
| Statistical |  1,222 |  1,203 |  98.4% |

### 레이어별 소요시간

```
Layer A:          0.52s (2 룰, A03 skip)
Layer B:          1.68s (11 룰)
Layer C:          2.14s (9 룰)
Benford:          0.07s (1 룰)
Score Aggregator: 1.26s
```

---

## 3. DataSynth v1.0 → v1.2.0 비교

| 지표               | v1.0 (이전)          | v1.2.0 (현재)        | 변화       |
|:-------------------|:--------------------|:--------------------|:-----------|
| B07 과탐률         | 99.96%              | 0.54%               | 99.42%p 개선 (하이브리드 SoD) |
| C03 과탐률         | 42.83%              | 1.05%               | 시간정보 정상화 |
| B02 탐지 건수      | 0건                 | 4,351건             | 6단계 한도 반영 |
| 검증 가능 룰       | 14/22               | 21/24               | 개선       |
| Recall             | 100%                | 98.3%               | 미세 하락  |
| 실행 룰 수         | 22개                | 24개 (C10, B11 추가) | +2         |

---

## 4. 문제점 분류

### 과탐 (flagged > 50%)

해당 없음. B07 하이브리드 SoD 적용으로 과탐 해소 (99.96% → 0.54%).

### 데이터 특성 (코드 정상, 패턴 미주입)

| 룰  | 비율  | 설명                                |
|:----|:------|:------------------------------------|
| A02 | 0.00% | DataSynth에 필수필드 누락 패턴 미주입 |
| B11 | 0.00% | DataSynth에 비용 자산화 패턴 미주입   |

### Graceful Degradation (정상)

| 룰  | 설명                          |
|:----|:------------------------------|
| A03 | chart_of_accounts 미제공 → skip |

---

## 5. 모듈별 단위 테스트 상세

### Layer A: 데이터 무결성 (18 tests)

```
TestA01UnbalancedEntry   — 6개 (균형/불균형/tolerance경계/NaN처리/skip)
TestA02MissingRequired   — 3개 (정상/NULL/다중NULL)
TestA03InvalidAccount    — 4개 (유효/무효/CoA미제공/int-str호환)
TestDetectIntegration    — 5개 (반환타입/max scoring/skipped/elapsed/빈DF)
```

### Layer B: 부정 탐지 (48 tests)

```
TestB01 — 4개 (매출+고zscore/저zscore/비매출/피처미존재)
TestB02 — 3개 (near_threshold/not/미존재)
TestB03 — 2개 (exceeds/not)
TestB04 — 6개 (윈도우내/초과/다른거래처/컬럼미존재/3건중복/30일경계)
TestB05 — 4개 (exact match/날짜다름/GL다름/컬럼미존재)
TestB06 — 4개 (동일승인자/fallback/created_by미존재/NaN)
TestB07 — 3개 (위반자/미달/컬럼미존재)
TestB08 — 3개 (수기+초과/수기만/초과만)
TestB09 — 2개 (초과+비자동/컬럼미존재)
TestB10 — 3개 (관계사/단일회사/컬럼미존재)
TestB11 — 6개 (자산↔비용/no_match/asset_only/expense_only/missing/partial)
FraudLayer통합 — 8개 (반환타입/scores max/minimal/빈DF/rule_flags/B01상세/컬럼명/flagged정합)
```

### Layer C: 이상 징후 (53 tests)

```
TestC01 — 4개 (기말+고액/기말+저액/비기말/피처미존재)
TestC02 — 3개 (주말/공휴일/평일)
TestC03 — 3개 (심야/업무시간/피처미존재)
TestC04 — 3개 (abs>30양방향/abs≤30/피처미존재)
TestC05 — 2개 (불일치/일치)
TestC06 — 4개 (missing/poor/high risk/normal)
TestC07 — 4개 (적합/비적합선별/피처미존재/튜플반환)
TestC08 — 3개 (abs>3/≤3/피처미존재)
TestC09 — 5개 (희소쌍/빈번쌍/N:M복합/컬럼미존재/빈차변)
TestC10 — 4개 (suspense flagged/all_false/NaN/피처미존재)
BenfordDetector — 8개 (track_name/반환타입/scores범위/적합0점/metadata/C07/graceful/빈DF)
AnomalyLayer통합 — 10개 (반환타입/scores범위/NaN없음/C prefix/rule_flags 9개/flagged정합/elapsed/minimal/빈DF/C07미포함)
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

| 항목 | 대상 | 우선순위 |
|------|------|---------|
| constants 테스트 갱신 | RULE_CODES 24개, SEVERITY_MAP 24개 검증 | 중간 |
