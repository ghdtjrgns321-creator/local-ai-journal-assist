# DataSynth 양방향 품질 감사 결과

> 역사 문서. 현재 실사용 기준본은 `data/journal/primary/datasynth/`의 `v20.3` freeze다. 아래 수치는 2026-04-01 당시의 DataSynth 상태를 기록한 것이다.

> 실행일: 2026-04-01  
> 스크립트: `tools/dual_audit_v2.py`  
> 데이터: `data/journal/primary/datasynth/journal_entries.csv` (1,134,339행 / 106,547개 문서)  
> 라벨: `data/journal/primary/datasynth/labels/anomaly_labels.csv` (8,091건)  

---

## PART 1: 비정상 라벨 검증 (전수 검사)

라벨이 붙은 문서가 실제로 해당 이상 특성을 보이는지 100% 검증.

| 룰   | 총라벨(doc) | 검증됨 | 검증률   | anomaly_type 매핑                    | 검증 기준                                      |
|:-----|:----------:|:------:|:--------:|:-------------------------------------|:----------------------------------------------|
| L1-01  |           3 |      3 |  100.0%  | UnbalancedEntry                      | sum(debit) != sum(credit), 허용오차 0.01       |
| L1-02  |          21 |     21 |  100.0%  | MissingField                         | NULL in gl_account / document_type / posting_date |
| L1-03  |           5 |      5 |  100.0%  | InvalidAccount                       | GL not in CoA (449개)                          |
| L4-01  |           4 |      4 |  100.0%  | RevenueManipulation                  | GL starts with '4' (revenue)                  |
| L2-01  |          27 |     20 |   74.1%  | JustBelowThreshold                   | amount in 90~99.99% of label threshold        |
| L1-05  |           5 |      5 |  100.0%  | SelfApproval                         | created_by == approved_by                     |
| L1-06  |          12 |     12 |  100.0%  | SegregationOfDutiesViolation         | sod_violation == True                         |
| L1-07  |           1 |      1 |  100.0%  | SkippedApproval                      | approved_by is NULL                           |
| L2-04  |          12 |     12 |  100.0%  | ImproperCapitalization               | asset GL(15xx) AND expense GL(5-8xxx) co-exist |
| L3-05  |           5 |      5 |  100.0%  | WeekendPosting                       | posting_date 요일 = 토(5)/일(6)               |
| L3-06  |         213 |    213 |  100.0%  | AfterHoursPosting, UnusualTiming     | posting_hour in 22:00~06:59                   |
| L3-07  |          30 |     27 |   90.0%  | BackdatedEntry, LatePosting          | \|posting_date - document_date\| > 30일       |
| L1-08  |          12 |     11 |   91.7%  | WrongPeriod                          | fiscal_period != posting_date.month           |
| L3-08  |          19 |      9 |   47.4%  | VagueDescription                     | blank/≤2chars/vague keywords in line_text     |
| L2-06  |          20 |     10 |   50.0%  | ReversedAmount                       | intra-doc DR↔CR swap OR reversal-dup pair     |
| **합계** | **389** | **358** | **92.0%** |                                  |                                                |

### FN(미탐) 상세 분석

#### L2-01 — 검증률 74.1% (FN 7건)

FN 7건의 ratio가 0.9999 초과 (예: 0.99994, 0.99998...): 검증 상한을 0.9999로 설정했으나 DataSynth가 99.994~99.999% 구간 값도 주입함. 탐지기 설계상 상한을 `< 1.0`으로 완화하면 해소됨.

**L2-01 탐지기 FN 별도 원인 (27건 전수 미탐 — PART 3 참조):** `employees.json` `user_id`와 JE `created_by` 네이밍 불일치로 approval_limit 조회 자체가 불가능. 탐지기 recall 78%의 직접 원인.

#### L3-07 — 검증률 90.0% (FN 3건)

| 문서(앞8자) | posting_date | document_date | day_diff | 라벨 설명         | 원인                                                         |
|:----------:|:------------:|:-------------:|:--------:|:-----------------|:------------------------------------------------------------|
| f75e4f6d   | 2022-12-31   | 2022-12-31    |        0 | Late posting: 34d | DataSynth이 posting_date와 document_date를 동시 수정 → diff=0 |
| c234fa08   | 2022-01-01   | 2022-01-27    |      -26 | Backdated by 31d  | original_date=2022-01-27 → new_date=2021-12-27로 수정 의도였으나 JE에 반영된 document_date가 original 값(1월 27일)으로 남아 diff=26일 |
| 1cf90964   | 2022-12-31   | 2022-12-30    |        1 | Late posting: 48d | DataSynth이 날짜 주입 시 document_date도 함께 수정하여 diff 축소 |

**근본 원인:** DataSynth의 날짜 주입 전략이 `posting_date`와 `document_date`를 독립적으로 수정하지 않고 양쪽을 함께 변경하는 경우가 있어, 최종 JE에 기록된 두 날짜의 차이가 라벨의 delay_days와 불일치함.

#### L1-08 — 검증률 91.7% (FN 1건)

| 문서(앞8자) | fiscal_period | post_month | 라벨 설명           | 원인                                                       |
|:----------:|:-------------:|:----------:|:-------------------|:-----------------------------------------------------------|
| b5376b8f   |             1 |          1 | Posted to wrong period | DataSynth이 posting_date를 수정(원: 2022-01-31 → 2022-01-01)했으나 fiscal_period를 갱신하지 않음. 결과적으로 post_month=1, fiscal_period=1로 일치하여 탐지 기준에서 정상으로 분류. |

**근본 원인:** DataSynth가 날짜를 수정할 때 파생 컬럼인 fiscal_period를 재계산하지 않는 설계 결함.

#### L3-08 — 검증률 47.4% (FN 10건)

검증에 사용한 vague 키워드 목록에 한국 회계 실무 용어("가계정", "가수금", "잡이익")가 누락됨.

- 검증 FN이지만 코드 버그 아님 — vague_kw 사전 보완 필요
- DataSynth가 주입한 한국어 vague 텍스트: `가지급`, `임시`, `기타`, `가계정`, `가수금`, `잡이익`, `여유금`, `임의`
- L3-08 탐지기 `vague_keywords.yaml` 업데이트 시 recall 향상 가능

#### L2-06 — 검증률 50.0% (FN 10건)

DataSynth의 L2-06 주입 전략 2가지:

| 패턴                          | 건수 | 검증률 | 내용                                                         |
|:------------------------------|:----:|:------:|:------------------------------------------------------------|
| 패턴1: intra-doc DR↔CR swap   |   10 |    0%  | 동일 문서 내 특정 라인의 DR/CR 교환. 단, 교환 후 DR쪽만 양수로 남거나 반대가 되어 동일 GL의 DR-CR 교집합이 성립하지 않음. |
| 패턴2: reversal-duplicate 문서 |   10 |  100%  | DataSynth가 별도 복제 문서를 생성하여 역분개 쌍 구성. 라벨 존재 자체가 증거. |

**패턴1 탐지 실패 원인:** DataSynth가 특정 라인의 DR 값을 CR로 이동할 때 동일 GL에 대한 DR/CR 교집합이 발생하지 않는 구조(DR-only 라인을 CR-only로 교체하는 방식). 탐지기는 같은 GL에서 양수 DR과 양수 CR이 동시 존재하는 경우를 탐지하는데, 교환 후에는 어느 한쪽만 남음.

---

## PART 2: 정상 데이터 오염 검사

대상: `is_fraud=False AND is_anomaly=False` (1,030,799행 / 96,681개 문서)

### 오염 항목 (제거 또는 조사 필요)

| 검사 항목                  | 건수     | 비율   | 판정    | 비고                          |
|:---------------------------|:-------:|:------:|:-------:|:------------------------------|
| L1-01: 불균형 전표 (문서 기준) |       8 |  0.01% | ★ 오염  | 정상 문서에 차변≠대변이 존재   |
| L1-07: approved_by NULL (행)  |   1,005 |  0.10% | ★ 오염  | 488개 문서, 승인자 누락        |

### 허용 가능 패턴 (참고용)

| 검사 항목                  | 건수      | 비율   | 판정    | 비고                          |
|:---------------------------|:--------:|:------:|:-------:|:------------------------------|
| L1-06: sod_violation=True (행) | 111,668 | 10.83% | [참고] ★ 높음 | 10,374개 문서 — DataSynth 파라미터 점검 권장 |
| L1-05: 자기승인 (행)           |  98,909 |  9.60% | [참고]  | 내부 정책상 허용 가능         |
| L3-05: 주말 전기 (행)          |  82,877 |  8.04% | [참고]  | 24/7 운영 환경 허용            |
| L3-06: 야간(22-06) 전기 (행)   |  22,449 |  2.18% | [참고]  | 야간 배치 처리 허용            |

**L1-06 주의:** 정상 데이터의 10.83%가 `sod_violation=True`로 표시됨. 이는 DataSynth가 SoD 위반 플래그를 anomaly 주입과 독립적으로 생성하는 과정에서 발생한 것으로, 탐지기가 이 컬럼을 직접 사용하면 False Positive 폭발 위험이 있음. `sod_conflict_type` 기반 로직 보강 또는 임계치 적용 필요.

---

## PART 3: L2-01 FN 원인 분석

### 탐지 결과

- 전체 L2-01 라벨: 27건
- 탐지기로 검증 성공: **0건** (recall 0% — 탐지기가 approval_limit 조회 불가 상태)
- 라벨 설명 기준 검증: 27건 모두 90~100% 구간에 해당 (ratio 0.950~0.99999)

### 근본 원인

```
employees.json   user_id: IMENDO008, SSHAH062, ...  (197명)
journal_entries  created_by: TMITCH053, JBERNA063, ...  (교집합 없음)
```

DataSynth가 JE를 생성할 때 사용한 `created_by` 식별자 포맷이 `employees.json`의 `user_id` 포맷과 다름. 조회 시 매핑 실패로 `emp_limit = NaN` → 비율 계산 불가 → 전건 미탐.

### 해결 방안

1. **단기:** DataSynth 재생성 시 `created_by`를 `employees.json` `user_id`에 맞춰 생성
2. **중기:** `data/master_data/employees.json`에 `created_by` 역매핑 필드 추가 또는 별도 매핑 CSV 생성
3. **탐지기 방어:** `emp_limit` 조회 실패 시 default_limit 사용 또는 해당 문서를 "limit 조회 불가" 플래그로 별도 리포팅

---

## 요약 판정

| 항목                        | 결과                                                |
|:----------------------------|:----------------------------------------------------|
| 전체 라벨 검증률            | 92.0% (389건 중 358건)                             |
| 완전 검증 룰 (100%)         | L1-01, L1-02, L1-03, L4-01, L1-05, L1-06, L1-07, L2-04, L3-05, L3-06  |
| 부분 검증 룰 (<100%)        | L2-01(74%), L3-07(90%), L1-08(92%), L3-08(47%), L2-06(50%)   |
| 정상 데이터 오염            | L1-01 8건(문서), L1-07 1,005행(488 문서)               |
| 주요 DataSynth 설계 결함    | L2-01 user_id 불일치, L3-07/L1-08 날짜 동시수정, L2-06 패턴1 |
| L3-08/L2-06 낮은 검증률         | 코드 버그 아님 — DataSynth 주입 방식과 탐지 로직 간 갭 |
