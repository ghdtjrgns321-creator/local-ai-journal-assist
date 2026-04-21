# DataSynth 3년치 전수조사 분석 리포트

> 역사 문서. 현재 실사용 기준본은 `data/journal/primary/datasynth/`의 `v20.3` freeze다. 아래 수치는 2026-04-14 당시 점검 기준을 기록한 것이다.

> **대상**: `data/journal/primary/datasynth/journal_entries.csv`
> **규모**: 1,107,734행 / 319,204전표 / 3법인 / 36개월
> **기간**: 2022-01-01 ~ 2024-12-31
> **실행일**: 2026-04-14
> **분석 범위**: S1 구조 / S2 정량 / S3 정성 / S4 탐지룰 / S5 품질 / S6 마스터

---

## Executive Summary

| 분류 | 판정 | 핵심 |
|------|:----:|------|
| **구조 무결성** | PASS | 차대변 균형 99.99%, PK 유니크, 연도별 합산 일치 |
| **회계 정합성** | PASS | K-IFRS 계정체계 정상, 거래유형별 차대변 방향 70%+ |
| **마스터 정합성** | PASS | vendor/customer 100% 매칭, 직원 100% 매칭 |
| **데이터 품질** | WARNING | reference 컬럼 MCAR 위반(정상 2.4% vs 비정상 10.6%) |
| **부정 주입률** | FAIL | fraud 0.11% (목표 2%의 1/18), anomaly 0.75% (목표 5%의 1/7) |
| **시간 분포** | WARNING | 12월 집중 1.49x (목표 1.5~3.0x 하한), 야근 12월 효과 없음 |
| **사용자 식별** | WARNING | user_persona/created_by에 대량 typo 변형 (SoD 분석 시 정규화 필수) |

### TOP 5 이슈

1. **부정/이상 주입률 심각한 미달**: 설정 vs 실측이 7~18배 차이. ML 학습 시 클래스 불균형 극심.
2. **reference 컬럼 MCAR 위반**: 비정상 데이터의 NULL률(10.55%)이 정상(2.40%)의 4.4배 → ML 지름길 학습 위험.
3. **L2-02(중복지급) 탐지 커버리지 41%**: auxiliary_account_number 59% NULL.
4. **DZ(수금) 50건 / WE(입고) 60건**: O2C·P2P 핵심 프로세스 데이터 부족.
5. **결산기 패턴 약함**: 12월 야근 비율(7.05%)이 평월(6.90%)과 거의 동일.

---

## S1. 구조적 검증

### S1-1. 컬럼 존재
- CSV 컬럼: **44개** (schema.yaml 정의 46개)
- 누락: `lettrage`, `lettrage_date` (현재 탐지 룰 미사용 → **WARNING**)

### S1-2. 필수 컬럼 NULL률
| 컬럼 | NULL | 비율 | 판정 |
|------|------|------|:----:|
| document_id, company_code, posting_date | 0 | 0.00% | PASS (보호) |
| fiscal_year, fiscal_period, document_date | 0 | 0.00% | PASS |
| debit_amount, credit_amount | 0 | 0.00% | PASS |
| document_type | 21,227 | 1.92% | PASS (MCAR) |
| gl_account | 21,973 | 1.98% | PASS (MCAR) |

### S1-3. 연도별 합산 = 통합
`372,087 + 373,054 + 362,593 = 1,107,734` → **PASS**

### S1-4. (document_id, line_number) 유니크
중복 0건 → **PASS**

### S1-5. 차대변 균형 (허용오차 1.0원)
- 총 전표 319,204 중 **불균형 25건 (0.008%)**
- 25건 모두 라벨됨: ReversedAmount(10) / TransposedDigits(6) / RoundingError(6) / CurrencyError(3)
- 정상 데이터의 차대변 균형: **100%** → **PASS**

### S1-6. generation_statistics.json 교차검증
| 항목 | 기대 | 실측 | 차이 | 판정 |
|------|------|------|------|:----:|
| total_line_items | 1,107,702 | 1,107,734 | 0.00% | PASS |
| total_entries | 319,193 | 319,204 | 0.00% | PASS |
| companies_count | 3 | 3 | 0.00% | PASS |
| accounts_count | 431 | 414 | 3.94% | WARNING (17개 미사용) |

---

## S2. 정량적 분석

### S2-1. 회사별 분포
| 회사 | 라인수 | 비율 | 전표수 |
|------|--------|------|--------|
| C001 | 685,241 | 61.9% | 199,073 |
| C002 | 213,940 | 19.3% | 60,108 |
| C003 | 208,553 | 18.8% | 60,023 |

- 실측 비율 62:19:19 (≈ 1:0.3:0.3 — config의 weight=0.3 정확히 반영)
- 기대(volume_weight 100K:10K:10K = 83:8.3:8.3)와 다르나, weight 파라미터 효과로 해석 → **WARNING**

### S2-2. 연도별 / 월별 분포
- 연도별 전표: 2022=106,163 / 2023=106,355 / 2024=106,686 (균등)
- 월별 변동계수 CV=0.173 → **PASS**
- 12월 비율 12.4% → **PASS** (10~30% 범위)
- 월별 최저 22,561건(2월) ~ 최고 39,514건(12월)

### S2-3. 금액 LogNormal 적합성
- 정상 데이터 표본: 1,098,623건
- ln(금액) μ=12.43 (목표 14.0, 차이 1.57) → **PASS**
- ln(금액) σ=3.35 (목표 2.5, 차이 0.85) → **PASS**
- 중앙값: 251,303원 (목표 1,200,000원의 21%, 다소 낮음)
- 범위: 1원 ~ 1,000억원

### S2-4. 시간 분포
| 항목 | 실측 | 기대 | 판정 |
|------|------|------|:----:|
| 주말 전기 | 30,756 (2.8%) | 1~10% | PASS |
| 심야(22-06) | 24,412건 | 50~1,000건 | **WARNING** (목표의 24배) |
| 월말(26일+) | 318,273 (28.7%) | 시즌 효과 | PASS |

**시간대별 피크**: 09시(128,722) > 10시(127,825) > 16시(122,264). 점심시간 dip(12시 18,158), 야근 시간대 정상(19~21시). 한국 근무 패턴 반영 우수.

### S2-5. Benford's Law (첫째 자릿수)
| 자릿수 | 실측% | Benford% | 차이 |
|:------:|------:|---------:|------|
| 1 | 30.73% | 30.10% | 0.63%p |
| 2 | 17.62% | 17.61% | 0.01%p |
| 3 | 12.50% | 12.49% | 0.01%p |
| ... | ... | ... | ... |
| **MAD** | **0.001450** | < 0.006 | **PASS (적합)** |

### S2-6. 부정/이상/SoD 주입률 ⚠️
| 항목 | 설정 | 실측 | 평가 |
|------|:----:|:----:|------|
| fraud (전표) | 2.0% | **0.11%** | **FAIL** — 1/18 미달 (339건) |
| anomaly (전표) | 5.0% | **0.75%** | **FAIL** — 1/7 미달 (2,394건) |
| SoD violation | 1.0% | **3.32%** | WARNING — 3.3배 초과 (10,595건) |
| fraud+anomaly 중복 | - | 44건 | - |

**해석**: `is_fraud=true`로 마킹된 전표가 매우 적음. anomaly_labels.csv에는 8,337건이 있어, 라벨과 데이터 컬럼 간 정합 확인 필요(아래 S4-2 참조).

### S2-7. fraud_type / anomaly_type 분포
- fraud_type: **15종** (RevenueManipulation 86 / UnauthorizedAccess 46 / FictitiousTransaction 45 / DuplicatePayment 36 등)
- anomaly_type: **46종** (NewCounterparty 413 / UnusualAccountPair 313 / MissingRelationship 271 / DormantAccountActivity 247 등)

### S2-8. document_type 분포
| Type | 전표 | 비율 |
|------|------|------|
| SA(일반) | 121,220 | 37.1% |
| DR(매출) | 62,040 | 20.0% |
| KR(매입) | 61,235 | 19.3% |
| HR(급여) | 24,150 | 7.6% |
| KZ(지급) | 22,293 | 7.0% |
| AA(자산) | 21,157 | 7.0% |
| NULL (MCAR) | 6,356 | 1.9% |
| IC(관계사) | 644 | 0.1% |
| **WE(입고)** | **60** | **0.0%** ⚠️ |
| **DZ(수금)** | **25** | **0.0%** ⚠️ |
| WL(외부) | 24 | 0.0% |

기대 9종 모두 존재하나 WE/DZ 극히 희소.

---

## S3. 정성적 분석 (회계 도메인)

### S3-1. K-IFRS 계정체계
| 접두사 | 분류 | 계정수 | 라인수 | 차변(억) | 대변(억) |
|:------:|------|:------:|--------|---------:|---------:|
| 1 | 자산 | 109 | 375,340 | 48,717 | 14,780 |
| 2 | 부채 | 86 | 312,237 | 9,372 | 45,111 |
| 3 | 자본 | 3 | 1,779 | 108 | 96 |
| 4 | 수익 | 91 | 181,063 | 629 | 30,739 |
| 5 | 매출원가 | 104 | 174,532 | 26,996 | 745 |
| 6 | 판관비 | 10 | 24,521 | 3,051 | 243 |
| 7 | 영업외 | 4 | 4,814 | 1,375 | 204 |
| 8 | 법인세 | 1 | 1,450 | 176 | 0 |
| 9 | 기타 | 6 | 10,025 | 2,402 | 368 |

→ 주요 계정군 모두 10개 이상 → **PASS**. 자산/부채/매출/매출원가/판관비 차대변 방향 정상.

### S3-2. 거래유형별 차대변 방향
| Type | 차변 기대 | 실측 | 대변 기대 | 실측 | 판정 |
|------|----------|------|----------|------|:----:|
| KR(매입) | 비용/자산(5/6/1) | 97% | 부채(2) | 55% | PASS |
| DR(매출) | 채권(1) | 70% | 수익(4) | 73% | PASS |
| KZ(지급) | 부채(2) | 50% | 현금(1) | **28%** | **WARNING** |
| HR(급여) | 비용(5/6) | 88% | 부채/현금(1/2) | 93% | PASS |
| AA(자산) | 자산(1) | 90% | 현금/부채(1/2) | 93% | PASS |
| IC(관계사) | 자산(1) | 43% | 부채(2) | 50% | **WARNING** |

### S3-3. IC 거래 대사
| 회사 | IC채권(1150) | IC채무(2050) | 건수 |
|------|-------------:|-------------:|-----:|
| C001 | 52,789,509,704 | 39,228,772,135 | 5,202 |
| C002 | 11,195,720,780 | 13,242,914,124 | 1,737 |
| C003 | 10,650,800,569 | 14,923,098,741 | 1,613 |

- 그룹 합계: 채권 **74.6B** vs 채무 **67.4B** → 순차이 **7.2B (9.7%)**
- 완전 대사되지 않음 → **WARNING** (소거조정 미반영 가능성)

### S3-4. 승인 프로세스
- 승인된 전표: 235,579 / 319,204 (73.8%)
- 자기승인(L1-05): 5,932건 (2.52%) — 합리적 범위
- **페르소나 분포 (정상 + typo 변형)**:
  - senior_accountant: 91,540 (정상 + 수십 종 typo)
  - automated_system: 78,855
  - junior_accountant: 77,881
  - manager: 32,420
  - controller: 32,050

⚠️ **typo 변형 대량 발생**: `junior_acountant`, `senoir_accountant`, `automatd_system` 등 수백 종. 페르소나 컬럼이 `data_quality.typos.protected_fields`에 포함되지 않은 듯. **L1-06(SoD) 분석 시 페르소나 정규화 필수**.

- **source 분포**:
  - manual: 70.1% ← 설정(automated 76.6%)과 큰 차이 → **WARNING**
  - automated: 18.8%
  - recurring: 7.4%
  - adjustment: 3.7%

### S3-5. 결산기 패턴
| 월 | 전표수 | 비고 |
|---:|-------:|------|
| 1 | 24,909 | |
| 2 | 22,561 | min |
| 3 | 29,864 | Q1말 spike |
| 6 | 29,077 | Q2말 spike |
| 9 | 29,112 | Q3말 spike |
| 12 | **39,514** | year-end max |

- 12월/평월 배율: **1.49x** (목표 1.5~3.0x 하한 미달) → **WARNING**
- 12월 야근 비율: 7.05% / 평월: 6.90% → **결산기 야근 효과 거의 없음** → **WARNING**

### S3-6. 비정상 데이터 회계적 타당성
| fraud_type | 건수 | 검증 결과 | 판정 |
|------------|-----:|----------|:----:|
| RevenueManipulation | 259 | 매출(4xxx) 49% | **WARNING** (절반만 매출계정) |
| ExpenseCapitalization | 40 | 자산차+비용대 100% | PASS |
| SplitTransaction | 29 | 평균 30M원, 최대 666M원 | PASS |
| DuplicatePayment | 36 | - | - |

---

## S4. 탐지 룰 커버리지

### S4-1. 룰별 필수 컬럼 NULL률
| 룰 | 상태 | 병목 컬럼 | NULL% |
|----|:----:|----------|------:|
| L1-01~L1-03, L4-01~L2-03, L1-06~L3-02, L3-03~L2-04, L3-04~L2-06 | PASS | - | < 5% |
| **L2-02(중복지급)** | **RISK** | auxiliary_account_number | **59.1%** |
| L1-05(자기승인) | WARNING | approved_by | 29.8% |
| L1-07(승인생략) | WARNING | approved_by | 29.8% |

### S4-2. anomaly_labels.csv 분포
- 총 라벨: **8,337건** (CSV의 is_anomaly=true 2,394건의 3.5배)
- 카테고리별:
  - Fraud: 5,968 (71.6%)
  - Relational: 1,917
  - Statistical: 360
  - Error: 66
  - ProcessIssue: 26

⚠️ **라벨 파일과 CSV의 is_fraud/is_anomaly 컬럼 간 큰 차이**: anomaly_labels.csv에는 Fraud 카테고리 라벨이 5,968건이나, CSV의 `is_fraud=true`는 339건. 라벨이 CSV에 동기화되지 않음 → **FAIL**.

### S4-3. 라벨-실제 패턴 일치
| 라벨 | 라벨 수 | 실제 패턴 일치 | 일치율 |
|------|--------:|--------------:|-------:|
| UnusualTiming | 76 | 76 (심야) | **100%** |
| StatisticalOutlier | 42 | 34 (Z>3) | 81% |
| 금액변형 4종 | 26 | 25 (불균형) | 96% |
| SelfApproval | **1** | 5,932 (created=approved) | 매우 적음 |

### S4-4. 탐지 위험 시나리오
1. **L2-02(중복지급)**: auxiliary_account_number 59% NULL → 41% 표본만 탐지 가능
2. **L3-03(IC거래)**: reference 2.5% NULL — 영향 미미
3. **L3-08/L2-06(적요 분석)**: line_text 2.1% NULL — 영향 미미
4. **DZ(수금) 25건 / WE(입고) 60건**: O2C 수금 + P2P 3-way matching 데이터 부족

---

## S5. 데이터 품질 교차검증

### S5-1. MCAR 정상/비정상 동일률 ⚠️
| 컬럼 | 정상 NULL% | 비정상 NULL% | 차이 | 판정 |
|------|-----------:|-------------:|-----:|:----:|
| document_type | 1.92% | 1.71% | 0.21%p | PASS |
| **reference** | **2.40%** | **10.55%** | **8.15%p** | **FAIL** |
| header_text | 1.93% | 2.16% | 0.23%p | PASS |
| cost_center | 82.04% | 80.95% | 1.10%p | PASS |
| line_text | 2.06% | 2.02% | 0.05%p | PASS |
| tax_code | 91.45% | 89.59% | 1.87%p | PASS |

**reference 컬럼 MCAR 위반**: 비정상 데이터에서 reference NULL률이 4.4배 높음 → ML 모델이 "reference NULL = 비정상"이라는 지름길 학습 가능. **CLAUDE.md DATASYNTH 생성 규칙 위반**.

### S5-2. 보호필드 도메인 무결성
- is_fraud, is_anomaly, sod_violation: 모두 `{true, false}` 만 → **PASS**

### S5-3. 라벨 논리적 정합 — 모두 PASS
- is_fraud=T but fraud_type=NULL: **0건**
- is_fraud=F but fraud_type!=NULL: **0건**
- is_anomaly=T but anomaly_type=NULL: **0건**
- sod_violation=T but sod_conflict_type=NULL: **0건**

### S5-4. 전체 컬럼 결측률 (상위)
| 컬럼 | NULL% | 비고 |
|------|------:|------|
| fraud_type | 99.90% | 0.1% fraud만 라벨 |
| anomaly_type | 99.27% | 0.7% anomaly만 라벨 |
| sod_conflict_type | 96.84% | 3.2% SoD 라벨 |
| tax_code/tax_amount | 91.44% | 부가세 거래 8.6% |
| cost_center | 82.04% | 18% 거래만 부서 할당 |
| auxiliary_account_number | 59.05% | L2-02 탐지 영향 |
| approved_by/approval_date | 29.75% | 무승인 거래 30% |
| supporting_doc_type | 18.75% | 증빙 81% |

---

## S6. 마스터데이터 & 보조원장 정합성

### S6-1. Vendor / Customer 마스터 ✅
- vendor: **798/798 매칭 (100%)**
- customer: **399/399 매칭 (100%)**

### S6-2. IC 매칭쌍
- ic_matched_pairs.json: **328쌍** (generation_statistics와 일치)
- 키: ic_reference, transaction_type, seller_company, buyer_company, amount
- buyer/seller_company 기반 — document_id 직접 참조 키 없음 (구조적 한계)

### S6-3. 직원 마스터 ✅
- 마스터: 1,422명 (user_id 키)
- JE 사용자: 1,365명
- **직접 매칭: 1,365/1,365 (100%)** (typo 변형은 별도 user 카운트로 분리됨)

### S6-4. CoA 대사
- CoA 정의: **431개** (chart_of_accounts.json → accounts 리스트)
- JE 계정: **414개**
- 매칭: **387/414 (93.5%)**
- 미매칭 27개 (예: 115001~115003, 1190, 1290, 1300, 1520~1560) — InvalidAccount 라벨 0건
- CoA에만 있는 (미사용) 계정: **44개**

→ **WARNING**: 27개 계정이 데이터에 등장하나 CoA에 미정의 (의도되지 않은 갭 가능성)

---

## 종합 판정

| 섹션 | PASS | WARNING | FAIL | 비고 |
|------|:----:|:-------:|:----:|------|
| S1. 구조 | 5 | 1 | 0 | 컬럼 2개 누락 |
| S2. 정량 | 4 | 2 | **1** | 부정 주입률 1/18 |
| S3. 정성 | 4 | 2 | 0 | KZ/IC 차대변 방향 |
| S4. 탐지 | 22 | 2 | **1** | 라벨↔CSV 미동기화, L2-02 RISK |
| S5. 품질 | 9 | 0 | **1** | reference MCAR 위반 |
| S6. 마스터 | 3 | 1 | 0 | CoA 27개 미정의 |

### 즉시 조치 권고사항

#### 🔴 Critical (Rust 수정 필요)
1. **부정/이상 주입률 정상화**: `is_fraud`/`is_anomaly` 컬럼이 anomaly_labels.csv와 동기화되도록 생성 로직 수정. 현재 라벨 8,337건 중 CSV 컬럼에는 일부만 반영.
2. **reference 컬럼 MCAR 보장**: data_quality.missing_values.protected_fields 또는 균등 적용 로직 점검. 비정상 그룹에 NULL이 4.4배 집중되어 ML 지름길 위험.

#### 🟡 Major (개선 권장)
3. **user_persona/created_by typo 보호**: data_quality.typos.protected_fields에 추가하거나, L1-06 SoD 탐지 측에서 정규화 매핑 적용.
4. **DZ(수금) / WE(입고) 거래 증량**: 현재 25/60건 → P2P 3-way matching 및 O2C 수금 탐지 룰 검증 불가.
5. **결산기 야근 패턴 강화**: intraday multiplier 또는 12월 overtime 가중치 상향. 현재 12월/평월 야근 비율 1.02배에 불과.

#### 🟢 Minor
6. lettrage / lettrage_date 컬럼 미생성 (현재 미사용)
7. CoA 미정의 계정 27개 / CoA 미사용 계정 44개 정리
8. KZ(지급) 대변 현금 비율 28% → 50%+ 지향
9. 12월 집중도 1.49x → 1.5x 이상 (year_end_multiplier 미세 조정)

#### 정상 작동 확인
- 차대변 균형 99.99% (불균형 25건 모두 라벨됨)
- Benford's Law 적합 (MAD=0.0015)
- 마스터데이터 100% 참조 무결성
- 라벨 논리적 정합성 (is_X=T → X_type 필수) 100% 만족
- 시간대별 한국 근무 패턴 (9-10시 피크, 점심 dip, 19시 야근) 우수

---

## 부록: 분석 스크립트
- `tools/tmp_s3.py` — S3/S5 분석
- `tools/tmp_s4s6.py` — S4/S6 분석
- 실행: `PYTHONIOENCODING=utf-8 uv run python tools/tmp_s3.py`

## 부록: 기존 품질게이트 비교
- `tests/datasynth_quality_gate/results/quality_report.md` (T1~T6, 2026-04-07): 본 리포트와 일관성 확인됨
- 본 리포트는 감사인 관점의 6개 영역(구조/정량/정성/탐지/품질/마스터) 종합 분석
