# DataSynth 전수 품질검사 이력

> 5-Tier Quality Gate (115개 체크)를 통한 DataSynth 합성 데이터 반복 검증 기록.
> 도구: `tests/quality_gate/` | 실행: `uv run python -m tests.quality_gate --no-stop`

---

## Run #16 (2026-04-02 18:47) — FAIL 0 달성! 전체 통과

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   25 |    0 |    3 | WARNING |
| T3   |   19 |    0 |   11 | WARNING |
| T4   |   12 |    0 |    9 | WARNING |
| T5   |   15 |    0 |    6 | WARNING |

- **판정: WARNING (FAIL 0)** — 전체 통과!
- 행수: 1,106,056 | 라벨: 7,827 | CoA: 449
- **T1~T5 전 Tier FAIL 0건 달성** (Run#6~7 이후 재달성)

### Run#15 대비 해소된 FAIL

| 체크 | Run#15 | Run#16 | 변화 |
|------|--------|--------|------|
| T2-19 approval_date 역전 | 8건 | **0건 PASS** | 해소 |
| T3-04 persona 불일치 | 1,075K | **0건 PASS** | 해소 |
| T3-05 company 불일치 | 814K | **0건 PASS** | 해소 |
| T3-10 junior 다중프로세스 | 3명 | **0명 PASS** | 해소 |
| T3-12 approval_limit | 25,649 | **0건 PASS** | 해소 |
| T3-13 can_approve_je | 28,070 | **0건 PASS** | 해소 |

### 추가 개선

| 항목 | Run#15 | Run#16 | 비고 |
|------|--------|--------|------|
| T2-18 junior 1억 초과 | 1,053 | **0건 PASS** | |
| T3-11 controller R2R | 70.8% | **96.4% PASS** | |
| T4-09 persona automated | — | **72.3% PASS** | |
| T4-17 SoD 위반률 | 5.1% | 2.7% | 개선 |

### 잔존 WARNING (설계적 허용 또는 미구현)

- T2-21 GL prefix↔process: 75.5% (config 미세조정 영역)
- T2-23 Self-offsetting: 9,210쌍
- T4-02 LogNormal μ=9.85 (목표 14.0)
- T4-10~12 IC/round/nice 비율 미달
- T5-03 SelfApproval ALL_MISMATCH 1개
- T5-21 local_amount 불일치 22,138건

---

## Run #15 (2026-04-02 14:15) — 재생성, T3-03 해소

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   23 |    1 |    4 | FAIL    |
| T3   |   14 |    5 |   11 | FAIL    |
| T4   |   12 |    0 |    9 | WARNING |
| T5   |   16 |    0 |    5 | WARNING |

- **판정: FAIL (6건)**
- 행수: 1,106,570 | 라벨: 7,928 | CoA: 449
- **T3-03 employee FK orphan: FAIL→PASS** (33건→0건 해소)
- T2-19 approval_date 역전: 8건 유지
- T3-04 persona 불일치: 826K→1,075K (악화)
- T3-12 approval_limit: 1,670→25,649 (악화)
- T3-13 can_approve_je: 18,730→28,070 (악화)

### FAIL 항목

| 체크 | Run#14 | Run#15 | 변화 |
|------|--------|--------|------|
| T2-19 | 8건 | 8건 | 동일 |
| T3-03 | 33건 | **PASS** | **해소** |
| T3-04 | 826K | 1,075K | 악화 |
| T3-05 | 563K | 814K | 악화 |
| T3-10 | 3명 | 3명 | 동일 |
| T3-12 | 1,670 | 25,649 | 악화 |
| T3-13 | 18,730 | 28,070 | 악화 |

---

## Run #14 (2026-04-02 13:38) — 재생성, T2 FAIL 재발 + T3-03 신규

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   23 |    1 |    4 | FAIL    |
| T3   |   13 |    6 |   11 | FAIL    |
| T4   |   12 |    0 |    9 | WARNING |
| T5   |   17 |    0 |    4 | WARNING |

- **판정: FAIL (7건)**
- 행수: 1,106,572 (Run#13: 561K → 다시 1.1M 스케일 복귀)
- 라벨: 7,927 | CoA: 449

### Run#13 대비 변화

| 체크  | Run#13      | Run#14       | 변화              |
|-------|-------------|--------------|-------------------|
| T2-02 | PASS (0건)  | PASS (0건)   | 유지              |
| T2-19 | PASS        | **FAIL (8건)** | **신규 FAIL**    |
| T2-20 | PASS (0건)  | PASS         | 유지              |
| T3-03 | PASS        | **FAIL (33건)** | **신규 FAIL** (employee FK orphan) |
| T3-04 | 437K        | 826K         | 악화              |
| T3-05 | 367K        | 563K         | 악화              |
| T3-10 | 3명         | 3명          | 동일              |
| T3-11 | PASS (86%)  | WARNING (71%) | 악화             |
| T3-12 | 1,859       | 1,670        | 소폭 개선         |
| T3-13 | 23,399      | 18,730       | 소폭 개선         |
| T4-04 | WARNING     | **PASS**     | 개선              |
| T4-09 | WARNING     | **PASS**     | 개선 (persona 정보 없음) |
| T4-17 | 16.2%       | 5.1%         | 대폭 개선         |

### 신규/재발 FAIL

- **T2-19**: approval_date < posting_date 8건 (사전승인 위반)
- **T3-03**: employee FK orphan 33건 (employees.json에 없는 employee_id 참조)

---

## Run #13 (2026-04-02 12:52) — Rust 대폭 수정, T2 FAIL 0 달성

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   24 |    0 |    4 | WARNING |
| T3   |   14 |    5 |   11 | FAIL    |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   16 |    0 |    5 | WARNING |

- **판정: FAIL (5건)** — T3만 잔존
- 행수: 561,472 (이전 1.1M → 절반. 데이터 구조 변경으로 추정)
- 라벨: 7,993 | CoA: 449

### 주요 개선 (vs Run#8~12)

| 항목 | Run#12 | Run#13 | 변화 |
|------|--------|--------|------|
| **T2-02** debit/credit 동시양수 | FAIL (4건) | **PASS (0건)** | 해소 |
| **T2-14** trading_partner NULL | 98.9% | 53.6% | 대폭 개선 |
| **T2-20** automated 제3자승인 | 675K | **0** | 해소 |
| **T5-11** 대형전표 line>100 | 770건 | **0건** | 해소 |
| **T5-16** debit=credit=0 | 10,359건 | **3건** | 대폭 개선 |
| **T3-11** controller R2R | 0% (0/0) | **86.0%** | PASS 전환 |
| **T3-10** junior 다중프로세스 | 195명 | **3명** | 대폭 개선 (FAIL 유지) |
| T4-02 LogNormal μ | 9.88 | 11.90 | 개선 (14.0 목표) |
| T4-09 persona 분포 | automated 0.1% | 5개 persona 분산 | 구조 변경 |

### 잔존 T3 FAIL 5건

| 체크 | 수치 | 비고 |
|------|------|------|
| T3-04 persona 불일치 | 437,479건 | Run#12: 1,011 → **악화** (데이터 구조 변경 영향) |
| T3-05 company 불일치 | 367,278건 | Run#12: 729K → 비율적으로 유사 (절반 행수) |
| T3-10 junior 다중프로세스 | 3명 | Run#12: 195명 → **대폭 개선** |
| T3-12 approval_limit | 1,859건 | Run#12: 1,747 → 유사 |
| T3-13 can_approve_je | 23,399건 | Run#12: 7,123 → **악화** |

---

## Run #12 (2026-04-02 00:06) — 재생성, Run#10 수준 회귀

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   21 |    1 |    6 | FAIL    |
| T3   |   13 |    5 |   12 | FAIL    |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   16 |    1 |    4 | FAIL    |

- **판정: FAIL (7건)**
- 행수: 1,107,860 | 라벨: 7,933 | CoA: 449
- Run#10과 동일 패턴. T5-02 OK=7 (FAIL), T3-19/20 소폭 악화
- employee assignment FAIL 5건 + T2-02 + T5-02 = 7건, **5회 연속 동일**

### Run#11 대비 변화

| 체크  | Run#11  | Run#12  | 변화         |
|-------|---------|---------|-------------|
| T2-02 | 4건     | 4건     | 동일         |
| T3-04 | 1,012   | 1,011   | 동일 수준    |
| T3-05 | 729K    | 729K    | 동일         |
| T3-10 | 195명   | 195명   | 동일         |
| T3-12 | 1,747   | 1,747   | 동일         |
| T3-13 | 7,123   | 7,123   | 동일         |
| T3-19 | 2/60    | 4/61    | 소폭 악화    |
| T3-20 | PASS    | WARNING | 악화         |
| T5-02 | WARNING | FAIL    | 악화 (OK=8→7)|

---

## Run #11 (2026-04-01 23:23) — Rust 2차 수정, T5 개선

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   21 |    1 |    6 | FAIL    |
| T3   |   14 |    5 |   11 | FAIL    |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   16 |    0 |    5 | WARNING |

- **판정: FAIL (6건)**
- 행수: 1,107,861 | 라벨: 7,933 | CoA: 449
- **T5 개선**: T5-02 OK=7→8 (FAIL→WARNING). T5 전체 FAIL 0
- T2/T3 FAIL은 Run#8~10과 동일 패턴 유지 (employee assignment 미수정)

### Run#10 대비 변화

| 체크  | Run#10  | Run#11  | 변화         |
|-------|---------|---------|-------------|
| T2-02 | 4건     | 4건     | 동일         |
| T3-04 | 1,012   | 1,012   | 동일         |
| T3-05 | 729K    | 729K    | 동일         |
| T3-10 | 195명   | 195명   | 동일         |
| T3-12 | 1,747   | 1,747   | 동일         |
| T3-13 | 7,123   | 7,123   | 동일         |
| T3-20 | WARNING | PASS    | **개선**     |
| T5-02 | FAIL    | WARNING | **개선**     |

잔존 FAIL 6건은 전부 employee assignment + debit/credit 로직.

---

## Run #10 (2026-04-01 23:06) — Rust 수정 후 재생성, 회귀 미해소

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   21 |    1 |    6 | FAIL    |
| T3   |   13 |    5 |   12 | FAIL    |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   16 |    1 |    4 | FAIL    |

- **판정: FAIL (7건)**
- 행수: 1,107,861 | 라벨: 7,933 | CoA: 449
- Rust 수정 후 재생성이나 **Run#8/9와 동일한 FAIL 패턴 유지**
- T3-20 delivery COGS: PASS→WARNING (미포함 1/24), T3-19 GR/IR: 미포함 1→3 (소폭 악화)
- employee assignment 핵심 FAIL 5건 + T2-02 + T5-02 = 총 7건 변동 없음

### Run#9 대비 변화

| 체크  | Run#9   | Run#10  | 변화      |
|-------|---------|---------|-----------|
| T2-02 | 4건     | 4건     | 동일      |
| T3-04 | 1,009   | 1,012   | 동일 수준 |
| T3-05 | 729K    | 729K    | 동일      |
| T3-10 | 195명   | 195명   | 동일      |
| T3-12 | 1,747   | 1,747   | 동일      |
| T3-13 | 7,123   | 7,123   | 동일      |
| T3-19 | 1/60    | 3/61    | 소폭 악화 |
| T3-20 | PASS    | WARNING | 악화      |
| T5-02 | OK=7    | OK=7    | 동일      |

결론: Rust 수정이 employee assignment 로직에 반영되지 않은 것으로 판단.

---

## Run #9 (2026-04-01 23:06) — 재생성 2차, 동일 회귀

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   21 |    1 |    6 | FAIL    |
| T3   |   14 |    5 |   11 | FAIL    |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   16 |    1 |    4 | FAIL    |

- **판정: FAIL (7건)**
- 행수: 1,107,858 | 라벨: 7,931 | CoA: 449
- Run#8과 거의 동일한 결과 (난수 시드 차이 수준)
- **T5 악화**: T5-02 OK 타입 수 7개 (Run#8: 8개) → FAIL 전환
- T2/T3 FAIL 항목은 Run#8과 완전 동일 (employee assignment 회귀 미수정)

### Run#8 대비 변화

| 체크  | Run#8 | Run#9 | 변화 |
|-------|-------|-------|------|
| T2-02 | 4건   | 4건   | 동일 |
| T3-04 | 1,008 | 1,009 | 동일 |
| T3-05 | 729K  | 729K  | 동일 |
| T3-10 | 195명 | 195명 | 동일 |
| T3-12 | 1,747 | 1,747 | 동일 |
| T3-13 | 7,123 | 7,123 | 동일 |
| T5-02 | WARN  | **FAIL** | OK=8→7 |

결론: 재생성만으로는 해소 불가. Rust 코드 수정 필요.

---

## Run #8 (2026-04-01 22:56) — 재생성 후 회귀

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   21 |    1 |    6 | FAIL    |
| T3   |   14 |    5 |   11 | FAIL    |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   16 |    0 |    5 | WARNING |

- **판정: FAIL (6건)**
- 행수: 1,107,857 | 라벨: 7,932 | CoA: 449
- T1 PASS 유지 (구조적 무결성 양호)
- **T2 회귀**: T2-02 debit/credit 동시 양수 4건 재발
- **T3 회귀 (5건 FAIL)**:
  - T3-04: persona 불일치 1,008건 (Run#7에서 0)
  - T3-05: employee company 불일치 729,000건 (Run#7에서 0 — 심각한 회귀)
  - T3-10: junior 다중 프로세스 195명 (Run#7에서 0)
  - T3-12: approval_limit 초과 1,747건 (Run#7에서 0)
  - T3-13: can_approve_je 무권한 승인 7,123건 (Run#7에서 0)
- T4/T5 WARNING 수준은 Run#7과 유사

### 회귀 분석

Run#6~7에서 해소됐던 employee assignment 관련 FAIL이 전부 재발.
근본 원인: DataSynth 재생성 시 employee assignment 로직(persona/company/권한 매핑)이
이전 수정사항을 반영하지 못한 것으로 추정.

**Rust 측 수정 필요 항목:**
1. T2-02: debit/credit 동시 양수 방지
2. T3-04: employee persona ↔ JE user_persona 일치
3. T3-05: employee authorized_company_codes에 JE company_code 포함
4. T3-10: junior는 단일 business_process만 처리
5. T3-12: approval_limit 이하 금액만 승인
6. T3-13: can_approve_je=true인 employee만 승인자로 배정

---

## Run #7 (2026-04-01 13:03) — 최종 통과

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   20 |    0 |    8 | WARNING |
| T3   |   19 |    0 |   11 | WARNING |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   15 |    0 |    6 | WARNING |

- **판정: WARNING (FAIL 0)**
- 행수: 1,134,339 | 라벨: 8,091 | CoA: 449
- Run #6과 거의 동일. FAIL 없음 유지 확인.

---

## Run #6 (2026-04-01 10:54) — 최초 전체 통과

| Tier | Pass | Fail | Warn | 판정    |
|------|------|------|------|---------|
| T1   |   14 |    0 |    0 | PASS    |
| T2   |   20 |    0 |    8 | WARNING |
| T3   |   20 |    0 |   10 | WARNING |
| T4   |   11 |    0 |   10 | WARNING |
| T5   |   14 |    0 |    7 | WARNING |

- **판정: WARNING (FAIL 0)** — 최초 전체 통과
- 행수: 1,134,345 | 라벨: 8,090 | CoA: 449
- T3-04/05/09/10/12/13 전부 PASS 전환 (employee assignment 로직 수정 완료)

---

## Run #5 (2026-03-31 22:57) — T1 재발, T5 악화

| Tier | Pass | Fail | Warn | 판정 |
|------|------|------|------|------|
| T1   |   10 |    4 |    0 | FAIL |
| T2   |   17 |    4 |    7 | FAIL |
| T3   |   17 |    2 |   11 | FAIL |
| T4   |   12 |    0 |    9 | WARN |
| T5   |   13 |    2 |    6 | FAIL |

- **판정: FAIL (12건)**
- T1-04/05/07 재발 (이전 수정이 반영 안 된 빌드)
- T1-08: 라벨 orphan 30건 (신규)
- T5-02: OK=0, T5-03: ALL_MISMATCH=10 (라벨 품질 급락)
- T3-12: approval_limit 2,560건, T3-27: IC orphan 196건

---

## Run #4 (2026-03-30 21:47) — Employee assignment 개선

| Tier | Pass | Fail | Warn | 판정 |
|------|------|------|------|------|
| T1   |   14 |    0 |    0 | PASS |
| T2   |   18 |    3 |    7 | FAIL |
| T3   |   13 |    6 |   11 | FAIL |
| T4   |   11 |    0 |   10 | WARN |
| T5   |   16 |    1 |    4 | FAIL |

- **판정: FAIL (10건)**
- T1 전체 PASS 달성
- T3-04: 1,409,482 -> 1,493 (99.9% 개선)
- T3-12: 656K -> 57,009, T3-13: 718K -> 7,269 (대폭 개선)
- T3-05: 718,053 (authorized_company_codes 전부 빈 배열)
- T4-09: automated=0.1% (persona 분포 역전 — config 기대 60%)

---

## Run #3 (2026-03-29 12:04) — T3 최초 실행 (UUID 수정)

| Tier | Pass | Fail | Warn | 판정 |
|------|------|------|------|------|
| T1   |   11 |    3 |    0 | FAIL |
| T2   |   18 |    3 |    7 | FAIL |
| T3   |   16 |    4 |   10 | FAIL |
| T4   |   12 |    0 |    9 | WARN |
| T5   |   16 |    0 |    5 | WARN |

- **판정: FAIL (10건)**
- T3 UUID vs VARCHAR 타입 에러 수정 후 최초 실행
- T3-04: persona 불일치 1,409,482건 (거의 전체)
- T3-05: company 불일치 1,033,288건
- T3-12: approval_limit 104,591건, T3-13: can_approve_je 65,570건
- 근본 원인: DataSynth employee assignment 모듈이 persona/company/권한 무시

---

## Run #2 (2026-03-29 12:03) — T3 에러

| Tier | Pass | Fail | Warn | 판정 |
|------|------|------|------|------|
| T1   |   11 |    3 |    0 | FAIL |
| T2   |   18 |    3 |    7 | FAIL |
| T3   |    — |    — |    — | ERROR |
| T4   |   12 |    0 |    9 | WARN |
| T5   |   16 |    0 |    5 | WARN |

- **판정: FAIL + T3 ERROR**
- T3 UUID vs VARCHAR 비교 에러로 전체 스킵
- T1-04: 음수 1건, T1-05: 대차불일치 16건, T1-07: 기간 범위 (fy=4, date=3690)
- T2-04/07/19 FAIL

---

## Run #1 (최초 실행, 2026-03-28) — 기준선

| Tier | Pass | Fail | Warn | 판정 |
|------|------|------|------|------|
| T1   |   11 |    3 |    0 | FAIL |
| T2   |   18 |    3 |    7 | FAIL |
| T3   |    — |    — |    — | ERROR |
| T4   |   12 |    0 |    9 | WARN |
| T5   |   16 |    0 |    5 | WARN |

- **판정: FAIL + T3 ERROR**
- 최초 품질 게이트 실행. T3 UUID 에러 미수정 상태.
- T1-04/05/07, T2-04/07/19 FAIL (데이터 무결성 버그)

---

## FAIL 해소 추이

```
Run  T1  T2  T3  T4  T5  Total FAIL
#1    3   3   -   0   0   6+
#2    3   3   -   0   0   6+
#3    3   3   4   0   0  10
#4    0   3   6   0   1  10
#5    4   4   2   0   2  12
#6    0   0   0   0   0   0  <-- 최초 통과
#7    0   0   0   0   0   0  <-- 유지 확인
#8    0   1   5   0   0   6  <-- 재생성 회귀
#9    0   1   5   0   1   7  <-- 재생성 2차, 동일
#10   0   1   5   0   1   7  <-- Rust 수정 후, 동일
#11   0   1   5   0   0   6  <-- T5 개선, T2/T3 동일
#12   0   1   5   0   1   7  <-- 재생성, Run#10 수준
#13   0   0   5   0   0   5  <-- T2 FAIL 0! T3만 잔존
#14   0   1   6   0   0   7  <-- T2-19 재발, T3-03 신규
#15   0   1   5   0   0   6  <-- T3-03 해소, T3 수치 악화
#16   0   0   0   0   0   0  <-- FAIL 0! 전체 통과
```

## 주요 수정 사항 (DataSynth Rust 측)

| 버그                        | 발견  | 수정 확인 | 비고                                      |
|---------------------------|-------|----------|-------------------------------------------|
| 음수 금액                   | Run#1 | Run#6    | T1-04                                     |
| 대차불일치                   | Run#1 | Run#6    | T1-05                                     |
| 기간 범위 (fy/date)          | Run#1 | Run#6    | T1-07                                     |
| fiscal_period != month     | Run#2 | Run#6    | T2-04                                     |
| CoA 미등록 GL               | Run#2 | Run#6    | T2-07 (GL 4600)                           |
| approval_date 역전          | Run#2 | Run#6    | T2-19                                     |
| line_number 갭             | Run#3 | Run#6    | T2-17                                     |
| sod orphan                | Run#3 | Run#6    | T2-28                                     |
| employee FK orphan         | Run#1 | Run#3    | T3-03                                     |
| persona 불일치              | Run#3 | Run#6    | T3-04 (1.4M -> 0)                         |
| company 불일치              | Run#3 | Run#6    | T3-05 (1M -> 0)                           |
| junior TRE                | Run#4 | Run#6    | T3-09                                     |
| junior 다중 프로세스          | Run#4 | Run#6    | T3-10                                     |
| approval_limit 초과         | Run#3 | Run#6    | T3-12 (656K -> 0)                         |
| can_approve_je 무권한        | Run#3 | Run#6    | T3-13 (718K -> 0)                         |
| IC pair orphan             | Run#1 | Run#6    | T3-27                                     |
| 라벨 orphan                | Run#5 | Run#6    | T1-08                                     |
| ALL_MISMATCH 10개          | Run#5 | Run#6    | T5-03                                     |
| debit/credit 동시 양수       | Run#4 | Run#6    | T2-02 (**Run#8 재발: 4건**)               |
| persona 불일치 (회귀)        | Run#8 | —        | T3-04 (1,008건, Run#6에서 0)              |
| company 불일치 (회귀)        | Run#8 | —        | T3-05 (729K건, Run#6에서 0)               |
| junior 다중 프로세스 (회귀)    | Run#8 | —        | T3-10 (195명, Run#6에서 0)                |
| approval_limit 초과 (회귀)   | Run#8 | —        | T3-12 (1,747건, Run#6에서 0)              |
| can_approve_je 무권한 (회귀)  | Run#8 | —        | T3-13 (7,123건, Run#6에서 0)              |

## Quality Gate 프레임워크 수정 이력

| 수정                                    | Run   | 내용                                               |
|-----------------------------------------|-------|--------------------------------------------------|
| T3 UUID CAST                            | Run#3 | seller/buyer_document CAST(AS VARCHAR) 추가         |
| T3 BIGINT/DOUBLE CAST                   | Run#1 | approval_limit, net_amount 등 타입 캐스팅            |
| T1-13/14 MCAR 방식 변경                  | Run#2 | 라벨 제외 -> 비율 체크 (0.5~4%)                       |
| T2-18 FAIL->WARNING                     | Run#2 | 전결규정은 승인 한도, 작성 한도가 아님                  |
| Label exclusion 확장                     | Run#2 | T1-04/05, T2-04/05/06/19에 anomaly type 추가        |
| T2-08 document_type 추가                 | Run#2 | IC, WL, KZ 허용                                    |
| T2-11 LOWER() 비교                      | Run#2 | DataSynth 소문자 source 대응                         |
| Windows cp949 인코딩                     | Run#1 | Unicode 특수문자 -> ASCII 대체                       |
