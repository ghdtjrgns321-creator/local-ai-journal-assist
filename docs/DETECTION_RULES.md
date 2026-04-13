# Detection Rules — 전표 부정 탐지 룰 전체 목록

한국 감사기준서(240호, K-SOX, PCAOB AS 2401)를 근거로 도출한 전표 부정 탐지 룰의 단일 참조 문서.
법규·기준서 근거는 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) 참조.

---

## 1. 개요

### 1.1 프로젝트 목적

ERP에서 추출한 전표 CSV 데이터에 대한 **전수 검사(CAATs)** 자동화.
감사인이 후속 수작업을 수행할 때의 우선순위 추천을 제공한다.

### 1.2 탐지 아키텍처 — 4레이어 + Benford

```
Layer A (데이터 무결성)     ─ 전표 품질 게이트, 이 검증 통과 후 이후 탐지가 의미있음
Layer B (부정 탐지)         ─ 핵심 탐지 레이어, 부정 시나리오 직접 대응
Layer C (이상 징후)         ─ 보조 징후, 부정의 간접 지표
Benford (독립 트랙)         ─ C07을 별도 가중치로 분리, 분포 수준 검정
Layer D (전기 대비 변동)    ─ 기존회사 전용, 전기 engagement 대비 급변 탐지
```

#### 1.2.1 B vs C 경계 정의 (직교성)

Layer B와 Layer C는 의도(intent)와 신호 성격(signal type)으로 구분한다. 같은 전표가 양쪽에서 플래그될 수 있으나, 각 레이어가 잡는 의미는 다르다.

| 축 | Layer B (부정 탐지) | Layer C (이상 징후) |
|----|-------------------|--------------------|
| **의도** | 의도적 부정 의심 (악의·은폐) | 오류·관행 이탈 (선의 포함) |
| **신호 성격** | 도메인 특화 패턴 (계정·승인·중복·SoD) | 통계·시간·텍스트 일반 이상 |
| **트리거 근거** | 부정 시나리오의 *수단* (어떻게 했는가) | 부정의 *흔적* (어디서 의심이 가는가) |
| **대표 룰** | B01 매출 이상 변동, B02 승인한도 직하, B05 중복 전표, B07 SoD | C01 기말 집중, C03 심야 전기, C08 이상 고액, C09 희소 계정쌍 |
| **오탐 비용** | 낮음 (실제 부정 가능성 시사) | 높음 (단순 업무 변동도 잡힘) |

**중복 플래그 처리 방침**:
- 동일 전표가 B와 C 양쪽에 플래그되면 `score_aggregator`의 레이어 가중합으로 자연스럽게 가산 효과 발생 (B 가중치 + C 가중치 → 종합 점수 상승). 별도 보너스 로직 없음.
- "B만 단독 플래그"는 부정 의심도가 강함, "C만 단독 플래그"는 검토 대상 표시. "B+C 동시"는 가장 강한 신호로 간주.

**해석 가이드** (감사인 검토 순서):
1. Layer A flagged → 데이터 자체 의심 (이전 단계에서 차단되었어야 함)
2. Layer B flagged → 부정 시나리오 1순위 검토 (계정·승인·SoD 맥락)
3. B+C 동시 → 가장 우선 검토 (부정 의도 + 통계 이상이 함께 발현)
4. C 단독 → 정상 영업 변동 가능성 확인 후 잔여만 추적

**중복 가능 사례** (혼선 방지를 위한 명시):
- B01 매출 이상 변동 ↔ C08 이상 고액: 매출 대규모 전표는 양쪽 모두 플래그 가능. B01은 "매출 계정 특화 맥락", C08은 "전체 통계 z-score". 분석 의도가 다르므로 양립 가능.
- B05 중복 전표 ↔ (없음): C 레이어에는 중복 룰이 없으므로 직접 충돌 없음.
- B19 (Top-side JE 복합) ↔ C01/C09: B19는 "기말+우회+비정상" 복합 점수라 C01·C09 신호를 *입력*으로 받음. 동일 전표 양쪽 플래그는 설계상 의도된 동작.

### 1.3 52개 유형 → 채택 판정

DataSynth 52개 anomaly 유형을 3축 평가(법규 근거 × 실증 빈도 × 데이터 가용성)로 선별.
판정 방법론 상세는 [DETECTION_REFERENCE.md §4](DETECTION_REFERENCE.md#4-3축-평가-방법론) 참조.

```
판정     유형 수   Phase    커버 범위                         FSS 6대 패턴 커버
──────────────────────────────────────────────────────────────────────────────
Must      20개    Phase 1   룰 기반 즉시 탐지                 6/6 (전부 커버)
Should    16개    Phase 2   ML/통계 확장                      가공전표·결산수정 정밀도↑
Could      5개    Phase 3   NLP/그래프 고급 탐지               순환거래 정밀도↑
Drop      11개    —         제외                              —
──────────────────────────────────────────────────────────────────────────────
합계      52개              Phase 3 누적: 41개 유형 커버
```

---

## 2. Phase 1: 룰 기반 탐지 (24개, 구현 완료)

### 2.1 Layer A: 데이터 무결성 (3개)

전표테스트의 전제조건. 이 검증을 통과해야 이후 탐지가 의미있음.

#### A01 — 차대변 균형 (UnbalancedEntry)

- **심각도**: 5
- **근거**: 240§32 복식부기 원칙. FSS 횡령은폐 수법(차대 불일치)
- **탐지 로직**: `sum(debit) ≠ sum(credit)` per document_id. 허용 오차 1.0 (float 안전)
- **구현**: `integrity_layer.py` → `_a01_unbalanced_entry()`
  - document_id별 groupby → diff 계산
  - NaN document_id는 개별 더미 키로 처리
- **필요 피처**: `debit_amount`, `credit_amount`, `document_id`

#### A02 — 필수필드 누락 (MissingField)

- **심각도**: 2
- **근거**: 240-A45(d) 계정번호 없이 입력. K-SOX 전표기록 통제
- **탐지 로직**: 9개 필수 컬럼 NULL 검사
  - 필수: document_id, company_code, fiscal_year, fiscal_period, posting_date, document_date, document_type, gl_account, (debit_amount OR credit_amount)
- **구현**: `integrity_layer.py` → `_a02_missing_required()`
- **DataSynth 상태**: MCAR 2% 주입 추가됨, E2E 재검증 필요

#### A03 — 무효 계정 (InvalidAccount)

- **심각도**: 3
- **근거**: 240-A45(a) 비경상·저사용 계정 + 315호 비정상계정. FSS 가공전표(미사용계정 악용)
- **탐지 로직**: `gl_account NOT IN chart_of_accounts`
  - CoA(계정과목표) 미제공 시 스킵
- **구현**: `integrity_layer.py` → `_a03_invalid_account()`
- **필요 피처**: `gl_account`

---

### 2.2 Layer B: 부정 탐지 (11개)

#### B01 — 매출 이상 변동 (RevenueManipulation)

- **심각도**: 5
- **근거**: 240보론2, §32(c) 비경상거래. **FSS 최다유형**: 매출 허위계상
- **탐지 로직**: 매출 계정(4xxx) 금액이 Z-score 임계값 초과
  - `revenue_account_prefixes: ['4']` (settings.py)
- **구현**: `fraud_rules_feature.py` → `b01_revenue_manipulation()`
- **필요 피처**: `gl_account`, `debit_amount`, `is_revenue_account` (파생)

#### B02 — 승인한도 직하 (JustBelowThreshold)

- **심각도**: 3
- **근거**: 240-A45(e) 단수/끝자리, K-SOX 승인체계
- **탐지 로직**: `금액 ∈ [threshold × 0.9, threshold)` — 6단계 승인한도
  - `approval_thresholds: [10M, 100M, 1B, 5B, 10B, 50B]` (KRW)
- **구현**: `fraud_rules_feature.py` → `b02_near_threshold()`
  - 피처 엔진에서 `is_near_threshold` 사전 계산
- **필요 피처**: `debit_amount`, `credit_amount`, `is_near_threshold` (파생)

#### B03 — 승인한도 초과 (ExceededApprovalLimit)

- **심각도**: 3
- **근거**: K-SOX 승인체계, 240§32
- **탐지 로직**: `금액 > threshold` — B02의 보완 룰
- **구현**: `fraud_rules_feature.py` → `b03_exceeds_threshold()`
- **필요 피처**: `debit_amount`, `credit_amount`, `exceeds_threshold` (파생)

#### B04 — 중복 지급 (DuplicatePayment)

- **심각도**: 3
- **근거**: 240§32 적정성. FSS 횡령은폐: 동일건 이중지급
- **탐지 로직**: 동일 벤더 + 동일 금액 + 기간 내 2건 이상
  - Bilateral diff (forward + backward)로 first-in-group도 포착
- **구현**: `fraud_rules_groupby.py` → `b04_duplicate_payment()`
- **필요 피처**: `auxiliary_account_number`, 금액, 날짜
- **DataSynth 상태**: ✅ auxiliary_account_number 59% 유효 (652K건, V-000xxx 형식)

#### B05 — 중복 전표 (DuplicateEntry)

- **심각도**: 3
- **근거**: 240§32, FSS 가공전표: 동일 전표 반복 = 가공
- **탐지 로직**: 동일 금액 + 계정 + 일자 매칭
  - `keep=False`로 원본·복제 양쪽 모두 플래그
- **구현**: `fraud_rules_groupby.py` → `b05_duplicate_entry()`
- **필요 피처**: `gl_account`, 금액, `posting_date`

#### B06 — 자기 승인 (SelfApproval)

- **심각도**: 3
- **근거**: K-SOX 직무분리(외감법§8①5호). **FSS 오스템임플란트** — 1인 입력·승인·이체, 2,215억 횡령
- **탐지 로직**: 2가지 케이스
  - Case A: `approved_by == created_by` (직접 비교)
  - Case B: `source='manual'` + 사용자 = 자기승인 추정
- **구현**: `fraud_rules_access.py` → `b06_self_approval()`
- **필요 피처**: `created_by`, `approved_by`, `source`

#### B07 — 직무분리 위반 (SegregationOfDutiesViolation)

- **심각도**: 4
- **근거**: K-SOX 직무분리. FSS 오스템: 동일인 전프로세스 수행
- **탐지 로직**: 하이브리드 3단계 SoD
  1. **Toxic Pair 즉시 탐지**: `sod_toxic_pairs` (audit_rules.yaml)에 정의된 프로세스 쌍
  2. **In-process conflict**: `sod_conflict_type` 컬럼 기반 충돌 검출
  3. **Role-based 프로세스 수 제한**: junior=1, senior=3 (역할별 한도)
- **구현**: `fraud_rules_access.py` → `b07_segregation_of_duties()`
- **필요 피처**: `created_by`, `business_process`
- **DataSynth**: 150명 규모, SOD 위반률 11.7% (preparer_approver 87%, v1.2.0)

#### B08 — 수기 전표 (ManualOverride)

- **심각도**: 4
- **근거**: 240-A45(b) 비인가자 입력, K-SOX 우회금지(외감법§8②). FSS 가공전표: 자동 프로세스 우회
- **탐지 로직**: `source == 'manual'` + 승인한도 초과
- **구현**: `fraud_rules_feature.py` → `b08_manual_override()`
- **필요 피처**: `source`, 금액, `exceeds_threshold` (파생)

#### B09 — 승인 생략 (SkippedApproval)

- **심각도**: 4
- **근거**: K-SOX 승인절차(외감법§8②). FSS 오스템: 한도초과+승인없음 = §8② 직접 위반
- **탐지 로직**: 승인한도 초과 + 비자동(source != 'automated') + 승인 없음
- **구현**: `fraud_rules_access.py` → `b09_skipped_approval()`
- **필요 피처**: 금액, `source`, `created_by`, `approved_by`

#### B10 — 관계사 순환거래 (CircularIntercompany)

- **심각도**: 4
- **근거**: 550§23 특수관계자 합리성. FSS 순환거래: 페이퍼컴퍼니 A→B→C→A 가공매출
- **탐지 로직**: (MVP) IC GL prefix 매칭
  - `intercompany_identifiers: ['1150', '2050', '4500', '2700']`
  - Phase 3 WU-22 완료: 실제 N-hop 순환 탐지는 **GR01(GraphDetector)** 에서 담당 (§4.4 참조)
- **구현**: `fraud_rules_access.py` → `b10_circular_intercompany()`
  - 3법인(C001/C002/C003) 간 IC 거래 식별
- **필요 피처**: `company_code`, `gl_account`, `reference`
- **중복 점수화 주의**: B10(Layer B)과 GR01(Graph track)이 동일 IC 전표에 각각 flag 가능. 현재 MAX 패턴으로 흡수되나 Phase 3 Stacking 단계에서 B10 deprecation 또는 skip 플래그 결정 필요 (별도 이슈).

#### B11 — 비용 자산화 (ExpenseCapitalization)

- **심각도**: 4
- **근거**: 240§32, FSS 분식회계: 개발비 과대자산화
- **탐지 로직**: 동일 document 내 차변=자산(15xx) + 대변=비용(6xxx)
  - Cartesian product 로직으로 N:M 전표 처리
- **구현**: `fraud_rules_groupby.py` → `b11_expense_capitalization()`
- **필요 피처**: `gl_account`, `debit_amount`, `credit_amount`

---

### 2.3 Layer C: 이상 징후 (12개 + Benford 독립 트랙)

#### C01 — 기말 대규모 (RushedPeriodEnd)

- **심각도**: 3
- **근거**: 240§32(a)(ii)+A44 기말검사 의무. FSS 결산수정 27건(29%)
- **탐지 로직**: 월말 5일 이내 + 금액 > Q3 (3사분위수)
- **구현**: `anomaly_rules_simple.py` → `c01_period_end_large()`
- **필요 피처**: `posting_date`, 금액, `is_period_end` (파생)

#### C02 — 주말 전기 (WeekendPosting)

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. FSS 비정상시점 4건
- **탐지 로직**: `weekday() >= 5` 또는 한국 공휴일 플래그
- **구현**: `anomaly_rules_simple.py` → `c02_weekend_entry()`
- **필요 피처**: `posting_date`, `is_weekend` (파생), `is_holiday` (파생)

#### C03 — 심야 전기 (AfterHoursPosting)

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. KLCA IT 체크리스트
- **탐지 로직**: 22시~06시 (midnight_start: 22, midnight_end: 6)
- **구현**: `anomaly_rules_simple.py` → `c03_after_hours_entry()`
- **필요 피처**: `posting_date` (시간 포함), `is_after_hours` (파생)
- **DataSynth**: v1.2.0에서 datetime 포함으로 해결

#### C04 — 소급 전기 (BackdatedEntry)

- **심각도**: 3
- **근거**: 240-A45(c) 기말+설명없음. FSS 횡령은폐
- **탐지 로직**: `posting_date - document_date > N일` (임계값 초과)
- **구현**: `anomaly_rules_simple.py` → `c04_backdated_entry()`
- **필요 피처**: `posting_date`, `document_date`, `days_between` (파생)

#### C05 — 기간 불일치 (WrongPeriod)

- **심각도**: 4
- **근거**: 240§32(b) 기간귀속 적정성
- **탐지 로직**: `fiscal_period ≠ month(posting_date)`
- **구현**: `anomaly_rules_simple.py` → `c05_fiscal_period_mismatch()`
- **필요 피처**: `fiscal_period`, `posting_date`

#### C06 — 위험 적요 (VagueDescription)

- **심각도**: 1
- **근거**: 240-A45(c) 설명없음, K-SOX§8①1호 기록방법
- **탐지 로직**: `line_text` 공백/누락 또는 위험 키워드 매칭
  - 품질 키워드: 3자 미만, 공백만, 숫자만
  - 위험 키워드: config/keywords.yaml 기반 (수정, 정정, 오류, adjust 등)
- **구현**: `anomaly_rules_simple.py` → `c06_risky_description()`
- **필요 피처**: `line_text`, `header_text`, `is_vague_description` (파생), `has_risk_keyword` (파생)

#### C07 — Benford 위반 (BenfordViolation) — 독립 트랙

- **심각도**: 2
- **근거**: 520§5 기대값-차이 분석, 240-A45(e) 단수/끝자리
- **판정 기준**:

  | 지표       | 적합     | 한계적 적합   | 부적합       | 부적합(강)  |
  |------------|---------|--------------|-------------|------------|
  | MAD        | < 0.006 | 0.006~0.012  | 0.012~0.015 | > 0.015    |
  | KS p-value | > 0.05  | 0.01~0.05    | < 0.01      | —          |

  > MAD 근거: Mark Nigrini, *Benford's Law* (Wiley, 2012). 감사/포렌식 분야 사실상 표준.

- **탐지 로직**:
  1. 전체 금액에 대해 Benford 분포 적합 검정 (분포 수준)
  2. 적합 시 → 전원 False 반환
  3. 부적합 시 → MAD > threshold인 특정 숫자(digit) 선별
  4. 해당 digit으로 시작하는 행만 플래그 (행 수준)
- **구현**: `benford_detector.py` → `BenfordDetector(BaseDetector)`
  - C07은 분포 수준 검정이므로 Layer C와 별도 가중치(0.15) 부여
  - 내부적으로 `anomaly_rules_statistical.py` → `c07_benford_violation()` 호출
- **필요 피처**: `debit_amount`, `credit_amount`
- **DataSynth 상태**: ⚠️ 위반 금액 미주입 (자연스러운 Benford 분포)

  추가 검정 (Phase 2): Chi-square, Anderson-Darling

#### C08 — 이상 고액 (UnusuallyHighAmount)

- **심각도**: 3
- **근거**: 240§33(b), 315호. FSS 결산수정: 개발비 과대자산화
- **탐지 로직**: Z-score > 3 (임계값)
- **구현**: `anomaly_rules_simple.py` → `c08_amount_outlier()`
- **필요 피처**: `debit_amount`, `credit_amount`, `amount_zscore` (파생)

#### C09 — 비정상 계정조합 (UnusualAccountPair)

- **심각도**: 2
- **근거**: 240-A45(a) 비경상·저사용 계정, 315호
- **탐지 로직**: 차변-대변 GL 계정 쌍 빈도 하위 1%
  - Merge 기반 벡터화된 Cartesian product
  - 100-line limit per document (메모리 오버플로우 방지)
- **구현**: `anomaly_rules_statistical.py` → `c09_rare_account_pair()`
- **필요 피처**: `gl_account` (차변/대변 행 쌍)

#### C10 — 가수금 장기체류 (SuspenseAccountAbuse)

- **심각도**: 3
- **근거**: 외감법§8①2호 오류통제. FSS 횡령은폐: 가수금을 통한 자금 유용
- **탐지 로직**: `is_suspense_account == True` (하이브리드 — 텍스트 키워드 OR GL 코드 prefix)
- **구현**: `anomaly_rules_simple.py` → `c10_suspense_account()`
- **필요 피처**: `is_suspense_account` (파생)
- **DataSynth 상태**: GL 코드 강제 배정으로 탐지 정상 작동. 적요 키워드 주입은 30% 확률이나 전체 확률 체인(0.5%×5%×30%) 상 극소수만 생성됨 — 이는 정상 동작.
- **Phase 3 이관**: 적요 의미 분석은 키워드 매칭의 근본 한계(우회 표현, 동의어, 은어)로 인해 Phase 3 LLM(#71 적요 NLP + #84 kiwipiepy + #88 semantic_similarity)에서 해결

#### C11 — 역분개 패턴 (ReversalEntry)

- **심각도**: 4
- **근거**: 240§32(a)(ii) 기말 재분개 중점 검사, FSS 분식회계·횡령은폐
- **탐지 로직**: 5개 서브 신호 가중 합산 (임계값 0.3 이상 플래그)
  1. S1(0.35) 1:1 매칭: 동일 gl_account + 동일 금액 + 반대 방향(차↔대) + ±1일
  2. S2(0.25) N:M 분할 역분개: gl_account × created_by 그룹, 7일 롤링 윈도우 순액 ≈ 0 + 금액 대칭 쌍 확인
  3. S3(±0.15) 정상/수정 구분: auto + 월초(D≤5) = 감점, manual = 가중
  4. S4(0.10) 적요 키워드: config/audit_rules.yaml `reversal_keywords` 18개
  5. S5(×1.5) 기말 부스트: 12/20~12/31 + 1/1~1/5 결산 전후 15일
- **구현**: `anomaly_rules_reversal.py` → `c11_reversal_entry()`
- **필요 피처**: `gl_account`, `debit_amount`, `credit_amount`, `posting_date`, `document_id`
  - 보조: `created_by`, `source`, `line_text`, `header_text`, `cost_center`, `trading_partner`
- **성능**: S1 self-merge 세분화 키(cost_center/trading_partner)로 Cartesian 폭발 방지

#### C13 — 배치 전표 이상 (BatchAnomaly) — Phase 2 WU-09

- **심각도**: 3
- **근거**: 금융권 IT 감사 가이드라인 — 배치 전표는 대량 자동 처리로 개별 검토 부재
- **탐지 로직**: 3가지 하위 패턴 OR 결합
  1. 기말 집중: 배치 전표 중 기말 비율 > `batch_period_end_ratio` (기본 0.5)
  2. 대량 동시 생성: 동일 일자 배치 건수 ≥ `batch_simultaneous_threshold` (기본 50)
  3. 금액 이상: 배치 내 Z-score > `batch_amount_zscore` (기본 3.0), std=0 방어 포함
- **구현**: `anomaly_rules_batch.py` → `c13_batch_anomaly()`
- **필요 피처**: `source`, `is_period_end`, `posting_date`, `debit_amount`, `credit_amount`
- **DataSynth 상태**: ⚠️ source='batch' 전표 미생성

---

### 2.5 Layer D: 전기 대비 변동 (2개, 기존회사 전용)

전기(fiscal_year - 1) engagement 데이터가 있는 기존회사에서만 실행.
신규회사(anonymous) 또는 전기 engagement 미존재 시 자동 스킵 (graceful degradation).

| Rule ID | 룰 이름                    | Severity | 감사기준서                    | 구현 파일                                |
|---------|----------------------------|:--------:|-------------------------------|------------------------------------------|
| D01     | 계정과목 집계 급변         | 4        | ISA 520 §5, PCAOB AS 2305    | `src/detection/variance_rules.py`        |
| D02     | 월별 분포 패턴 변화        | 3        | ISA 520 §5                    | `src/detection/variance_rules.py`        |

#### D01 — 계정과목 집계 급변 (AccountAggregateVariance)

- **입력**: 당기 DataFrame + `PriorSummary.account_aggregates`
- **판정 로직**:
  - 당기/전기 `gl_account`별 집계 비교 (total_amount, count, avg_amount)
  - 가중평균 변동률 = `total_var × 0.5 + count_var × 0.3 + avg_var × 0.2`
  - 임계값: `variance_threshold` (기본 0.5 = 50%) 초과 시 해당 계정의 모든 행 플래그
  - 신규 계정(전기 미존재): 자동 플래그 (변동률 = 1.0)

#### D02 — 월별 분포 패턴 변화 (MonthlyPatternVariance)

- **입력**: 당기 DataFrame + `PriorSummary.monthly_patterns`
- **판정 로직**:
  - Jensen-Shannon Divergence(JSD)로 전기/당기 월별 금액 분포 비교
  - 임계값: `monthly_pattern_threshold` (기본 0.3) 초과 시 해당 계정의 모든 행 플래그
  - 전기/당기 모두 3개월 이상 데이터 존재해야 비교 수행, 미만이면 스킵

#### Layer D 가중치 (기존회사 트랙)

Layer D가 활성화되면 전체 가중치가 재배분된다.

| 레이어          | 신규회사 | 기존회사 |
|-----------------|:--------:|:--------:|
| A (무결성)      | 0.15     | 0.12     |
| B (부정)        | 0.45     | 0.38     |
| C (이상징후)    | 0.25     | 0.20     |
| Benford         | 0.15     | 0.12     |
| **D (전기 변동)** | **—**  | **0.18** |

---

### 2.4 점수 체계

> **⚠️ 근거 없음 — 프로젝트 자체 설계안.**
> 아래 가중치와 임계값은 공식 기준서·학술 논문 근거가 아닌 초기 설계값이다.
> 실제 데이터 기반 튜닝(Phase 1 완료 후 back-testing)을 거쳐 조정될 예정.

#### 가중치

```
anomaly_score = Layer_A × W_A + Layer_B × W_B + Layer_C × W_C + Benford × W_Benford

  W_A (무결성) = 0.15    ← 위반 시 다른 점수의 신뢰도 자체가 떨어짐
  W_B (부정)   = 0.45    ← 핵심 탐지 레이어
  W_C (징후)   = 0.25    ← 보조 징후
  W_Benford    = 0.15    ← 통계적 배경
```

#### 위험 등급

```
High:   anomaly_score > 0.7  또는  Layer_A 위반 + Layer_B 2개 이상
Medium: anomaly_score > 0.4
Low:    anomaly_score > 0.2
Normal: anomaly_score ≤ 0.2
```

#### 자동 에스컬레이션

- (Layer A flagged ≥1) AND (Layer B flagged ≥2) → Risk = **High** (점수 무관 강제 상향)

#### 심각도(Severity) 맵

```
A01: 5  A02: 2  A03: 3
B01: 5  B02: 3  B03: 3  B04: 3  B05: 3  B06: 3  B07: 4  B08: 4  B09: 4  B10: 4  B11: 4
C01: 3  C02: 2  C03: 2  C04: 3  C05: 4  C06: 1  C07: 2  C08: 3  C09: 2  C10: 3
```

#### 행별 점수 계산

```
per-rule:  (severity / 5) × flagged     → [0.0, 1.0]
per-row:   max(all_rules_for_row)       → 최대값 (합산 아님)
per-track: 행별 점수 × LAYER_WEIGHT     → 가중합
```

#### 구현 파일

- `src/detection/constants.py` — RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS
- `src/detection/score_aggregator.py` — aggregate_scores(), classify_risk_level()

---

## 3. Phase 2: ML 확장 (16개 유형, 미구현)

### 3.1 ML 모델 전략

- **지도학습 (분류)**: 다수 모델 후보군 → GridSearchCV로 최적 모델·하이퍼파라미터 선택
- **비지도학습 (이상탐지)**: VAE (+ Isolation Forest 앙상블)
- **별도 로직**: DuplicateDetector, 시계열 분석, 내부거래 매칭 등은 전용 로직 유지

Phase 1의 24개 룰 결과를 pseudo-label로, DataSynth `is_fraud`/`is_anomaly`를 ground truth로 활용.

상세 설계: [pre-plan/05a-detection-ml.md](pre-plan/05a-detection-ml.md) 참조.

### 3.2 추가 탐지 유형 (16개)

| DataSynth 유형           | 카테고리    | Sev | ML 활용 방식                                       | 상태 |
|--------------------------|------------|-----|----------------------------------------------------|------|
| ImproperCapitalization   | Fraud      | 4   | GridSearch 지도학습 (비용→자산 계정 전환 패턴)       | ⬜   |
| FictitiousEntry          | Fraud      | 4   | VAE 이상탐지 (비경상 패턴)                           | ⬜   |
| FictitiousVendor         | Fraud      | 5   | GridSearch 지도학습 (마스터 데이터 교차 검증)         | ⬜   |
| RoundDollarManipulation  | Fraud      | 2   | GridSearch 지도학습 (금액 끝자리 분포)               | ⬜   |
| MisclassifiedAccount     | Error      | 3   | GridSearch 지도학습 (계정-프로세스 불일치)            | ⬜   |
| ReversedAmount           | Error      | 3   | VAE (차대 반전 쌍)                                   | ⬜   |
| TransposedDigits         | Error      | 2   | VAE (금액 자릿수 이상)                               | ⬜   |
| FutureDatedEntry         | Error      | 3   | GridSearch 지도학습 (날짜 이상)                      | ⬜   |
| CurrencyError            | Error      | 4   | GridSearch 지도학습 (환율 불일치)                     | ⬜   |
| StatisticalOutlier       | Statistical | 3  | VAE + IF 앙상블                                      | ⬜   |
| ExactDuplicateAmount     | Statistical | 3  | DuplicateDetector                                    | ⬜   |
| TransactionBurst         | Statistical | 4  | 시계열 밀도 분석                                     | ⬜   |
| UnusualFrequency         | Statistical | 2  | 시계열 분석                                          | ⬜   |
| DormantAccountActivity   | Relational | 2   | GridSearch 지도학습 (계정 사용 이력)                  | ⬜   |
| NewCounterparty          | Relational | 1   | GridSearch 지도학습 (신규 거래처 패턴)                | ⬜   |
| UnmatchedIntercompany    | Relational | 3   | 내부거래 매칭 로직                                   | ⬜   |

### 3.3 신규 컬럼 기반 룰 (DataSynth 확장 후 구현)

현재 39개 컬럼에는 없지만, DataSynth에 컬럼 추가 시 구현 가능한 18건.

#### 3.3.1 역분개(Reversal) 패턴 탐지

→ **C11로 구현 완료** (§2.3 참조)

- **기준서**: 감사기준서 240호
- **현재 상태**: 도메인 용어에 `is_reversal` 매핑만 있고 룰 없음
- **구현 로직** (Audit Sight/Arbutus 표준):
  1. **1:1 매칭**: 동일 `gl_account` + 동일 금액 + 반대 방향(차↔대) ±1일 이내
  2. **N:M 분할 역분개 (Rolling Sum Zero-Out)**: 특정 `gl_account` + `created_by` 조합에서 일정 기간(7일/30일) 내 `SUM(debit) - SUM(credit) ≈ 0`에 수렴하는 부분합을 DuckDB 윈도우 함수로 탐지
     ```sql
     SELECT gl_account, created_by, posting_date,
            SUM(debit_amount - credit_amount)
              OVER (PARTITION BY gl_account, created_by
                    ORDER BY posting_date
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS rolling_net
     FROM journal_entries
     WHERE ABS(rolling_net) < threshold
     ```
  3. **Reversing vs Correcting 구분** (SAP Reversal Reason Code):
     - RRC 05(Accrual Reversal) + 기초(1월) + `source='auto'` = 정상 역분개
     - RRC 01(당기 역분개) + `source='manual'` + 임의 시점 = 수정 전표 → 검토 대상
     - RRC 02(타 기간 역분개) = 결산 후 수정 → 고위험
  4. 적요 키워드 탐지: "수정", "정정", "오류", "역분개", "결산조정" 등
  5. 기말 30일 이내 역분개 집중도 가중
- **필요 컬럼**: 현재 39컬럼으로 구현 가능

#### 3.3.2 Top-side Journal Entries (경영진 조정 전표) — B19 ✅

- **룰 ID**: B19, 심각도 5
- **기준서**: 감사기준서 240호 §32(a)(ii), PCAOB AS 2401
- **구현 파일**: `src/detection/score_aggregator.py` (후처리 복합 탐지)
- **구현 로직** (게이트키퍼 + 가점):
  - **게이트키퍼**: `is_manual_je == True` 필수 (자동 전표 원천 차단)
  - **가점** (각 1점, 최대 5점):

    | # | 조건           | 참조 소스                            |
    |---|----------------|--------------------------------------|
    | 1 | 기말 시점       | `layer_c.details["C01"] > 0`        |
    | 2 | 자기승인/승인누락 | `layer_b.details["B06"or"B09"] > 0` |
    | 3 | 비정상 계정     | `layer_a["A03"] or layer_c["C09"]`   |
    | 4 | 이상 고액       | `layer_c.details["C08"] > 0`        |
    | 5 | 위험 적요       | `layer_c.details["C06"] > 0`        |

  - **판정**: 수기 AND 가점 ≥ `topside_threshold`(기본 2) → B19 플래그, High 승격
  - **정규화**: `topside_score = raw / 5.0` (0.0~1.0)
- **설정**: `config/settings.py::AuditSettings.topside_threshold`
- **테스트**: 9개 (`tests/test_detection/test_score_aggregator.py::TestTopsideDetection`)

#### 3.3.3 비정상 시간대 입력자 집중 분석

- **기준서**: KLCA IT 체크리스트
- **현재 상태**: 구현 완료 (`anomaly_rules_simple.py::c12_abnormal_hours_concentration`)
- **구현 로직** (Greenskies Analytics):
  1. 비정상 시간대 정의 (한국 실무 반영):
     - 정상: 08:30~18:30 (`hour_frac = hour + minute/60 + second/3600`, `>=/<` 일관)
     - 야근(저위험): 18:30~22:00 — 결산 집중기간(12/20~1/15, `settings.py` 설정 가능)에는 정상 취급
     - 심야(고위험): 22:00~06:00 — 감사 플래그 대상
  2. 사용자별 심야/비근무일 전표 비율 산출 (`min_user_entries` 미만 사용자 제외)
  3. 전체 사용자 평균 대비 3σ 이상 → 이상치 (단순 비율 0~1로 판정, 가중치는 별도 위험점수)
  4. 이상치 사용자의 **비정상 시간대 행만** 플래그 (정상 시간 전표 미포함)
  5. 입력자-승인자 간 시간 차이가 극히 짧은 경우 (부실 검토 의심, 자동 전표 제외)
- **설계 원칙 — 2계층 분리**:
  - Layer 1 (통계 판정): 단순 비율(0~1)로 3σ 수행 → 분포 가정 위반 방지
  - Layer 2 (위험 점수): 이상치에 대해 심야 가중 등을 적용 → score_aggregator severity 조정
  - 심야 가중 weighted_ratio(최대 2.0)를 3σ에 직접 대입하면 통계적 왜곡 발생하므로 분리 필수
- **DataSynth 시간대 multiplier**:
  ```
  심야(00~06)=0.02 / 이른출근(06~08:30)=0.15 / 오전피크(08:30~11:30)=1.8
  점심(11:30~13)=0.3 / 오후(13~16)=1.2 / 마감러시(16~18:30)=1.5
  야근(18:30~22)=0.3(평상시), 0.7(결산기) / 심야야근(22~24)=0.05
  ```

#### 3.3.4 승인 프로세스·승인자 계층

- **기준서**: 감사기준서 315호/330호 (ITGC 통제)
- **현재 상태**: B06/B09가 결과만 추론. 승인 컬럼 없음
- **구현 로직**:
  - 승인 누락률: `approved_by` IS NULL + 한도 초과 전표 비율
  - 승인 지연: `approval_date - posting_date` > N일
  - 레벨 건너뜀: 금액 대비 `required_approval_level` (DuckDB CASE WHEN 전결규정 6단계)
  - 자기승인 정밀화: `created_by == approved_by` (B06 개선)
- **DataSynth 수정 필요**: approval.rs 활성화 + 원화 기준 전환

#### 3.3.5 증빙 존재 확인

- **기준서**: 감사기준서 240호, 500호
- **구현 로직**:
  - `has_attachment=False` + 수기 + 고액 → 증빙 누락 의심
  - 한국 세법 적격증빙: 3만원 초과 → 세금계산서/카드/현금영수증 필요
  - 3만원 직하 분할 탐지: 동일 거래처 + 동일일 + 29,000원 이하 × N건
- **DataSynth 확장**: `has_attachment`(bool), `supporting_doc_type`(str)

#### 3.3.6 컷오프 (납품일 vs 전기일)

- **기준서**: 감사기준서 315호, 330호 (K-IFRS 15 수익인식)
- **구현 로직**:
  - 매출: `|posting_date - delivery_date|` > N 영업일 → 조기/지연 인식 의심
  - 비용: `|posting_date - invoice_date|` > N 영업일 → 기간귀속 오류 의심
  - 기말 전후 5~10 영업일 구간 집중 분석
- **DataSynth 확장**: `delivery_date`(date), `invoice_amount`(float), `tax_amount`(float), `supply_amount`(float)

#### 3.3.7 증빙 금액 불일치

- **기준서**: 감사기준서 500호
- **구현 로직**: 3-way matching 간소화
  - `|debit_amount - invoice_amount|` > 허용오차(1% 또는 절대금액) → 불일치 플래그
  - 부가세 검증: `tax_amount ≠ round(supply_amount × 0.1)` → 부가세 오류
- **DataSynth 확장**: `invoice_amount`, `invoice_date`, `tax_amount`, `supply_amount`

#### 3.3.8 전표 수정/삭제 이력

- **기준서**: KLCA IT 체크리스트 (변경관리 4.3~4.5)
- **구현 로직** (SAP CDHDR/CDPOS):
  - 한국 SAP: 전기된 전표는 직접 수정 불가 → 역분개(FB08) + 재전기 방식
  - 텍스트 변경: `change_type='UPDATE'` + `changed_field IN ('line_text','header_text')` + 기말 → 적요 수정 의심
  - `created_by ≠ changed_by` + 고액 → 무단 수정 의심
  - 상법 제33조: 장부 10년, 전표류 5년 보존 의무. 삭제 원칙적 불가
- **DataSynth 확장**: `changed_by`, `change_date`, `changed_field`, `old_value`, `new_value`

#### 3.3.9 IP 주소 추적

- **기준서**: KLCA IT 체크리스트
- **구현 로직**: 사용자별 평소 IP 풀 대비 이탈 IP + 고액/심야 → 비정상 접근 의심
- **DataSynth 확장**: `ip_address`(str). 한국 대기업 IP 구조 반영:
  ```
  사내(본사): 10.1.x.x    사내(공장): 10.2.x.x
  VPN/재택:   10.10.x.x   외부(공인): 203.x.x.x 등
  ```
  - VPN 접속 자체는 정상 (재택근무 ~34%). 심야+VPN+고액은 가중

#### 3.3.10 전표번호 연속성

- **기준서**: 감사기준서 240호, 315호
- **현재 상태**: document_id가 UUID이므로 불가
- **구현 로직** (zapliance SAP 표준):
  - 회사코드 + 회계연도 + 전표유형별 분할하여 번호범위 내 갭 탐지
  - `LEAD(document_number) - document_number > 1` → 갭
  - 갭의 적법 사유(취소 전표, 마이그레이션) 제외 필터
- **DataSynth 확장**: UUID와 별도로 순차 `document_number`(int). SAP 표준 Document Type:
  ```
  SA=일반분개  KR=매입전표  KZ=매입지급  DR=매출전표  DZ=매출수취  AA=자산전기
  ```

#### 3.3.11 기타 (8건)

| 항목 | 내용 | 기준서 |
|------|------|--------|
| 통제테스트(TOE) 데이터 기반 검증 | 승인 누락률, 평균 승인 지연, 레벨 우회율 | 330호, 1100호 |
| 계정분류 적정성 (K-IFRS) | 계정-거래유형 매핑 마스터 → ML 접근 | 315호, 330호 |
| 경제적 실질 (실질우선) | 계정-거래유형 불일치 + NLP(적요) → Phase 2~3 | 315호, 240호 |
| 회계추정치 편의(bias) | 전기 추정치 vs 실제 차이 시계열, 이익 방향 편향 | 240§32(b), ISA 540 |
| 재무제표-장부 대사 | GL 잔액 vs 보조원장 합계, Trial Balance 교차검증 | 330호 |
| 배치 전표 이상 패턴 | `source='batch'` 기말 집중, 대량 동시 생성 | 금융권 IT 감사 가이드라인 |
| 유의적 거래 합리성 | 탐지된 이상 전표를 LLM 분석 → 보조 의견 | 240§32(c) |
| 비정상 시간대 입력자 집중 | 사용자별 심야/비근무일 비율 통계 | KLCA IT 체크리스트 |

### 3.4 Phase 2 점수 체계 — Stacking Meta-Learner (D034)

**기존 고정 가중합 → Stacking 앙상블로 대체** (D034, 2026-03-30 결정)

```
Level 0 (6개 Base Models):
  [1] 룰 기반 24개 aggregate    → 1개 점수 (0~1)
  [2] XGBoost (cv_selector)     → predict_proba (0~1)
  [3] VAE 재구성 오차           → normalized (0~∞ → 0~1)
  [4] Isolation Forest          → normalized (-0.5~0.5 → 0~1)
  [5] FT-Transformer (D033)    → predict_proba (0~1)
  [6] BiLSTM+Attention (D032)  → predict_proba (0~1)

Level 1 (Meta-Learner):
  Logistic Regression (L2 Ridge)
  Input: 6개 확률값 → 최종 anomaly_score
  계수 = 데이터 기반 가중치 (고정 비율 대체)

Leakage 방지: 5-fold out-of-fold prediction
Fallback: 라벨 부족 시 Percentile Ranking 가중합
```

각 모델의 원시 점수 단위가 다르므로, fallback 시 Percentile Ranking으로 0~1 정규화.

```
정규화: scipy.stats.rankdata → 백분위수 0~1 변환
  → 분포 무관, 극단값에 강건 (Min-Max/Z-score 대비 우수)
```

---

## 4. Phase 3: NLP + 그래프 (5개 유형, 미구현)

| DataSynth 유형          | 카테고리     | Sev | 방법               | 상태 |
|-------------------------|-------------|-----|--------------------|------|
| LatePosting             | ProcessIssue | 2  | 시계열 NLP 복합     | ⬜   |
| MissingDocumentation    | ProcessIssue | 3  | NLP (적요 분석)     | ⬜   |
| CircularTransaction     | Graph(GR01)  | 4  | Johnson N-hop 순환 (length_bound=5) | ✅ WU-22 |
| TransferPricingAnomaly  | Graph(GR03)  | 4  | 양방향 IC 엣지 price asymmetry      | ✅ WU-22 |
| TrendBreak (TB01/TB02)  | Statistical  | 4/3| 설정vs상각 분리     | ✅   |

### Phase 3 점수 체계 (7트랙)

```
rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + duplicate(0.15) + nlp(0.10) + graph(0.15)
```

**Phase 3 누적: Tier 1(20) + Tier 2(16) + Tier 3(5) = 41개 유형 커버**

---

### 4.4 Graph Detector (WU-22) — networkx 기반 순환·이전가격

> **근거**: ISA 550 §23 특수관계자 사업상 합리성 · FSS 순환거래 페이퍼컴퍼니 패턴.
> **차별화**: B10(관계사 전표 존재 flag) 및 R03(그룹 편차 통계)의 한계를 그래프 토폴로지로 보완.

#### GR01 — CircularTransaction (N-hop 순환)

- **심각도**: 4
- **알고리즘**: networkx `simple_cycles(G, length_bound=max_cycle_length)` (Johnson)
- **그래프 구성**:
  - 노드: `(company_code, trading_partner)` 튜플
  - 엣지: `credit > 0` → `company → partner`, `debit > 0` → `partner → company`
  - 자료구조: `MultiDiGraph` (다중 엣지 보존 → 원본 행 인덱스 역매핑)
- **`trading_partner` NULL fallback**: 동일 `document_id` 그룹의 다른 `company_code`로 implicit IC pair 추론 (DataSynth 640건 NULL 복구 목적)
- **점수화**: binary 1.0 × `severity_factor(0.8)` (연속 점수화는 튜닝 단계로 이연)
- **B10과의 관계**: B10은 `is_intercompany` 플래그만 반환(recall 7%). GR01이 실제 N-hop 순환 탐지. Phase 3 Stacking 단계에서 B10 deprecation 여부 결정.

#### GR03 — TransferPricingAnomaly (양방향 price asymmetry)

- **심각도**: 4
- **알고리즘**: pandas groupby 기반 양방향 쌍 식별 + 차이율 계산
  1. IC 행만 필터
  2. `(src_company, dst_company, gl_account)` 그룹 평균 amount 계산
  3. 역방향 그룹과 inner join → 양방향 쌍 추출
  4. `deviation = |mean_fwd - mean_rev| / min(mean_fwd, mean_rev) > threshold(20%)`
  5. 점수 = `min(1.0, deviation / (threshold × 3))`
- **R03과의 차별화**:

| 항목       | R03 (Relational)                      | GR03 (Graph)                         |
|-----------|---------------------------------------|--------------------------------------|
| 접근       | `(partner, account)` 그룹 편차 통계   | **방향성 + 양방향성** 엣지 분석      |
| 수식       | `\|x - μ\| / μ > 15%`                 | `\|mean_fwd - mean_rev\| / min > 20%`|
| 포착 대상  | 단일 그룹 내 outlier 금액             | 매출/매입 가격 **비대칭** 패턴       |
| 중복 플래그 | MAX 패턴으로 severity 동일(4) 흡수    | 동일                                 |

#### OOM 방어 3중 장치 ⚠️

회계 장부 100만+ 행에서 `iterrows() + add_edge` 루프는 **수십 분 지연 + RAM OOM**. 필수 방어:

1. **사전 필터 (pandas 벡터화)**: `is_intercompany == True AND max(debit, credit) ≥ min_amount(1천만원)` → 목표 ≤ 50,000 행
2. **`nx.from_pandas_edgelist`로 C-레벨 변환**: `np.where`로 `src`/`dst` 컬럼을 먼저 생성. `for ... add_edge()` 루프/`apply`/`iterrows` 금지
3. **엣지 수 안전장치**: `len(edges_df) > graph_gr01_max_edges(50,000)` 시 `quantile` 기반 `min_amount` 자동 상향 + warning. 추가로 `weakly_connected_components`로 분리 후 컴포넌트별 `simple_cycles` 호출, 노드 수 > `graph_gr01_max_component_size(500)` 컴포넌트는 skip

**벤치마크**: 100k 행 DataFrame에서 실행 시간 1.3초 (목표 15초 이내).

#### Settings 파라미터 (`config/settings.py`)

```python
graph_gr01_max_cycle_length: int = 5          # Johnson length_bound
graph_gr01_min_amount: float = 10_000_000.0   # 엣지 최소 금액 (materiality, 1천만원)
graph_gr01_max_edges: int = 50_000            # 엣지 수 상한 (초과 시 자동 상향)
graph_gr01_max_component_size: int = 500     # 대형 component skip 임계
graph_gr03_min_path_length: int = 2           # 경로 최소 노드 수
graph_gr03_price_deviation_threshold: float = 0.20  # 양방향 가격 편차 허용
```

#### Metadata 출력

`DetectionResult.metadata`에 관측 지표 누적:
- `gr01_edges_prefiltered`, `gr01_edges_built`, `gr01_min_amount_effective`, `gr01_max_edges_raised`
- `gr01_implicit_edges` (document_id fallback 복구 건수)
- `gr01_cycles_found`, `gr01_skipped_components`
- `gr03_bidirectional_pairs`, `gr03_flagged_pairs`

#### 제외된 룰

**GR02 (CentralityAnomaly)**: DataSynth 그래프 규모(회사 3개, 거래처 수십 개)에서 betweenness centrality 분석이 통계적으로 무의미. 실데이터 유입 후 재검토.

---

## 5. 제외 유형

### 5.1 Drop — 11개 DataSynth 유형

| 유형                     | 합계 | 제외 사유                                         |
|--------------------------|------|---------------------------------------------------|
| RoundingError            | 3    | 실무 중요성 sev1, false positive 과다              |
| WrongCostCenter          | 0    | 코스트센터 마스터 없이 정합성 판단 불가             |
| DecimalError             | 0    | 소수점 오류는 시스템 레벨에서 방지                  |
| LateApproval             | 1    | 승인 로그 데이터 없음                              |
| IncompleteApprovalChain  | 1    | 승인 체인 데이터 없음                              |
| UnusualTiming            | 7    | C02/C03과 완전 중복 → 별도 유형 불필요             |
| RepeatingAmount          | 5    | ExactDuplicateAmount와 중복                        |
| UnusuallyLowAmount       | 3    | false positive 과다                                |
| MissingRelationship      | 1    | document_flows 데이터 의존                         |
| CentralityAnomaly        | 0    | 그래프 분석 범위 초과                              |
| AnomalousRatio           | 2    | StatisticalOutlier에 포섭                          |

> **제외 원칙**: ① 한국 법규 매핑 불가(축1=0), ② 현재 스키마로 탐지 불가(축3=0),
> ③ 기채택 유형과 완전 중복 중 하나 이상 해당.

### 5.2 불필요 5건 + 범위 밖 2건

상세 사유는 [DETECTION_REFERENCE.md §7](DETECTION_REFERENCE.md#7-프로젝트-범위와-한계) 참조.

---

## 6. DataSynth 갭 현황

> 갱신일: 2026-04-02 | DataSynth v21 확정 | 1,106,056행 | Phase 1 Recall 91.4% | Normal 85.2%

### 의존 관계

```
DETECTION_RULES.md (이 문서, 뿌리)
  ↓ 도출
settings.py + audit_rules.yaml (설정)
  ↓ 참조
detection 코드 (구현)
  ↓ 테스트
DataSynth 데이터 (검증)
```

### 갭 대조표

| 항목           | 이 문서 정의              | settings.py 현재값                                                          | DataSynth v1.2.0 실태                         | 해결 상태 |
|:---------------|:-------------------------|:---------------------------------------------------------------------------|:----------------------------------------------|:----------|
| 매출 계정      | "4xxx" (K-IFRS 기준)     | `revenue_account_prefixes: ['4']`                                          | gl_account 4xxx 존재 (20%)                     | ✅ 해결   |
| 승인 한도      | 명시 없음 (회사별)        | `approval_thresholds: [10M, 100M, 1B, 5B, 10B, 50B]` (6단계)              | lognormal mu=14.0 (중앙값 ~120만, 최대 1,000억) | ✅ 해결   |
| 거래처 식별    | `auxiliary_account_number` | B04에서 사용                                                               | 59% 유효 (652K건)                               | ✅ 해결   |
| 심야 기준      | 22시~06시                | `midnight_start: 22`                                                       | posting_date datetime (시분초 포함)             | ✅ 해결   |
| 관계사 식별    | GL 계정 prefix 매칭       | `intercompany_identifiers: ['1150', '2050', '4500', '2700']`               | IC GL 1150/2050/4500/2700 존재                  | ✅ 해결   |
| 직무분리 임계  | 하이브리드 3단계 SoD      | `sod_toxic_pairs` + `sod_role_thresholds`                                   | 152명, automated 제외 + Toxic Pair + Role-based | ✅ 해결   |
| Benford 위반   | MAD > 0.012              | `benford_mad_threshold: 0.012`                                              | BenfordViolation 157건 라벨 주입                | ✅ 해결   |
| 필수필드 누락  | 9컬럼 NULL 검사           | schema.yaml 참조                                                           | MCAR 2% (gl_account, document_type)             | ✅ 해결   |

### 해결 완료 (v1.2.0)

| 항목 | 원인 | 조치 | 파일 |
|:-----|:-----|:-----|:-----|
| B02/B08 승인한도 불일치 | 단일 한도 + USD 금액 범위 | KRW 6단계 승인한도 + lognormal mu=14.0 | `settings.py`, `datasynth.yaml` |
| B07 SOD 과탐 | 41명 소규모 시뮬레이션 | 150명 확대, SOD 위반률 11.7% | `datasynth.yaml` |
| B10 관계사 미식별 | `intercompany_identifiers: []` | IC GL prefix 4개 등록 | `audit_rules.yaml` |
| C03 심야 미탐지 | posting_date 시간정보 없음 | datetime 전환 | `schema.yaml`, DataSynth |
| `is_suspense_account` all-False | 한글 키워드만 매칭 | 하이브리드: 텍스트 키워드 OR GL 코드 prefix | `pattern_features.py`, `audit_rules.yaml` |
| `is_round_number` all-False | float 소수점 꼬리 | `base.round(0) % unit` 허용 | `amount_features.py` |

### v21 확정 결과 (2026-04-02)

| 항목 | 값 |
|:-----|:---|
| Phase 1 Recall | 91.4% (2,408 / 2,636) |
| 전체 Recall | 92.0% (7,197 / 7,827) |
| 100% Recall 룰 | 10개 (A01, A02, A03, B01, B04, C02, C03, C05, C06, C11) |
| B07 flagged | 1.9% (정상) |
| Normal 등급 | 85.2% |
| 구조적 한계 (ML 필요) | B05(10%), B10(4%), C09(9%), C07(29%) — Phase 2 대상 |

상세: [test-results/rule-label-gap-analysis.md](../tests/phase1_rulebase/test-results/rule-label-gap-analysis.md)

### 미해결 (경미 — Phase 2 이후)

| 항목 | 원인 | 현재 상태 | 대상 |
|:-----|:-----|:---------|:-----|
| C10 적요 키워드 부족 | 확률 체인(0.5%×5%×30%)으로 키워드 주입 건수 극소 — 정상 동작 | GL prefix 기반 탐지 정상 작동. 적요 의미 분석은 Phase 3 LLM 영역(#71, #84, #88) | Phase 3 이관 |
| trading_partner | 99.9% NULL (784건) | B10 IC GL prefix 매칭으로 대체 | DataSynth Rust |
| cost_center | 81.2% NULL | C11 세분화 키 활용도 제한 | DataSynth Rust |

---

## 7. 성능 평가 지표 체계

| 계층           | 지표            | 용도                                          |
|:---------------|:----------------|:----------------------------------------------|
| 1차 (메인)     | AUPRC (PR-AUC)  | threshold-free, 불균형에 강건. 지도/비지도 공통 |
| 1차 (메인)     | F2-score        | Recall 가중 (부정 놓치는 비용 > 오탐 비용)     |
| 2차 (보조)     | MCC             | 불균형에서도 신뢰할 수 있는 단일 지표           |
| 2차 (보조)     | DR@FAR=5%       | "오탐 5% 허용 시 탐지율" — 실무 의사결정용      |
| 3차 (참고)     | ROC-AUC         | 모델 간 비교용 (불균형 caveat 명시)             |
| 보고용         | Precision/Recall/F1 | 대시보드 표시 + 감사인 소통용               |

> F2를 사용하는 이유: 감사에서 부정을 놓치는 비용(FN)이 오탐 비용(FP)보다 크므로
> Recall에 2배 가중하는 F2가 F1보다 적합.

---

## 부록 A: 52개 유형 3축 평가 전체 목록

### Tier 1 — Must: Phase 1 (20개)

```
DataSynth 유형                   법규  실증  데이터  합계  레이어  룰 ID
─────────────────────────────────────────────────────────────────────────
UnbalancedEntry                   3     2     3      8    A       A01
MissingField                      3     1     3      7    A       A02
InvalidAccount                    3     1     3      7    A       A03
RevenueManipulation               3     3     3      9    B       B01
JustBelowThreshold                3     2     3      8    B       B02
ExceededApprovalLimit             1     2     3      6    B       B03
DuplicatePayment                  2     3     3      8    B       B04
DuplicateEntry                    2     3     3      8    B       B05
SelfApproval                      1     3     3      7    B       B06
SegregationOfDutiesViolation      1     3     3      7    B       B07
ManualOverride                    3     3     3      9    B       B08
SkippedApproval                   1     3     3      7    B       B09
CircularIntercompany              3     2     3      8    B       B10
ExpenseCapitalization              —     —     —      —    B       B11  *
RushedPeriodEnd                   3     3     3      9    C       C01
WeekendPosting                    3     1     3      7    C       C02
AfterHoursPosting                 3     1     3      7    C       C03
BackdatedEntry                    3     2     3      8    C       C04
WrongPeriod                       2     2     3      7    C       C05
VagueDescription                  3     3     3      9    C       C06
BenfordViolation                  3     2     2      7    Benford C07
UnusuallyHighAmount               2     3     3      8    C       C08
UnusualAccountPair                3     1     2      6    C       C09
SuspenseAccountAbuse              —     —     —      —    C       C10  *
```

> \* B11, C10은 DataSynth 52개 유형 외 프로젝트 자체 도출 룰이므로 3축 평가 대상 외.

### Tier 2 — Should: Phase 2 (16개)

```
DataSynth 유형              법규  실증  데이터  합계
────────────────────────────────────────────────────
ImproperCapitalization       2     3     2      7
FictitiousEntry              2     3     2      7
FictitiousVendor             2     3     1      6
RoundDollarManipulation      3     1     2      6
MisclassifiedAccount         2     2     2      6
ReversedAmount               2     1     2      5
TransposedDigits             2     0     2      4
FutureDatedEntry             2     1     2      5
CurrencyError                2     1     1      4
StatisticalOutlier           2     1     2      5
ExactDuplicateAmount         2     2     2      6
TransactionBurst             2     2     2      6
UnusualFrequency             2     1     2      5
DormantAccountActivity       3     2     2      7
NewCounterparty              1     2     1      4
UnmatchedIntercompany        2     2     1      5
```

### Tier 3 — Could: Phase 3 (5개)

```
DataSynth 유형             법규  실증  데이터  합계
───────────────────────────────────────────────────
LatePosting                 1     1     1      3
MissingDocumentation        2     2     1      5
CircularTransaction         3     2     1      6
TransferPricingAnomaly      2     2     1      5
TrendBreak                  2     1     1      4
```

### Drop — 제외 (11개)

```
DataSynth 유형              법규  실증  데이터  합계  제외 사유
──────────────────────────────────────────────────────────────────────
RoundingError                0     0     3      3    실무 중요성 sev1
WrongCostCenter              0     0     0      0    마스터 부재
DecimalError                 0     0     0      0    시스템 레벨 방지
LateApproval                 1     0     0      1    데이터 없음
IncompleteApprovalChain      1     0     0      1    데이터 없음
UnusualTiming                3     1     3      7    C02/C03 중복
RepeatingAmount              2     1     2      5    ExactDuplicateAmount 중복
UnusuallyLowAmount           1     0     2      3    false positive 과다
MissingRelationship          1     0     0      1    스키마 외
CentralityAnomaly            0     0     0      0    ROI 낮음
AnomalousRatio               1     0     1      2    StatisticalOutlier 포섭
```

---

## 부록 B: 표준 컬럼 스키마

DataSynth `journal_entries.csv` 39개 컬럼 기준.

### 필수 컬럼 (9개)

| 컬럼명           | 타입   | ACDOCA  | 설명             | 탐지 활용              |
|------------------|--------|---------|------------------|------------------------|
| `document_id`    | str    | `belnr` | 전표 ID (UUID)    | A01, B04, B05          |
| `company_code`   | str    | `rbukrs`| 회사코드          | B10                    |
| `fiscal_year`    | int    | `gjahr` | 회계연도          | C05                    |
| `posting_date`   | date   | `budat` | 전기일            | C01~C05                |
| `document_date`  | date   | `bldat` | 전표일            | C04                    |
| `gl_account`     | int    | `racct` | G/L 계정코드      | A03, B01, C09          |
| `debit_amount`   | float  | `wsl(S)`| 차변 금액         | A01, B02~B05, C07~C08  |
| `credit_amount`  | float  | `wsl(H)`| 대변 금액         | A01, B02~B05, C07~C08  |
| `document_type`  | str    | `blart` | 전표유형          | B01                    |

### 권장 컬럼 (10개)

| 컬럼명             | 타입   | ACDOCA  | 설명              | 탐지 활용   |
|--------------------|--------|---------|--------------------|------------|
| `created_by`       | str    | `usnam` | 입력자             | B06~B09    |
| `source`           | str    | —       | 입력소스           | B08, B09   |
| `business_process` | str    | —       | 비즈니스 프로세스   | B07        |
| `line_number`      | int    | `docln` | 라인번호           | A01        |
| `local_amount`     | float  | `hsl`   | 현지통화 금액      | 환율 검증   |
| `currency`         | str    | `rwcur` | 통화               | 환율 검증   |
| `cost_center`      | str    | `rcntr` | 코스트센터         | —          |
| `profit_center`    | str    | `prctr` | 손익센터           | —          |
| `line_text`        | str    | `sgtxt` | 적요               | C06        |
| `header_text`      | str    | `bktxt` | 헤더 텍스트        | C06        |

### 레이블 컬럼 (2개)

| 컬럼명       | 타입 | 설명          | 분포                    |
|-------------|------|---------------|-------------------------|
| `is_fraud`  | bool | fraud 여부     | True 1.9%, False 98.1%  |
| `is_anomaly`| bool | anomaly 여부   | True 7.5%, False 92.5%  |

### DataSynth 확장 예정 컬럼

| 컬럼명              | 타입     | 용도                      |
|---------------------|----------|---------------------------|
| `has_attachment`     | bool     | 증빙 첨부 여부             |
| `supporting_doc_type`| str     | 세금계산서/카드/현금영수증 등 |
| `delivery_date`      | date    | 납품일 (컷오프 검증)       |
| `invoice_amount`     | float   | 세금계산서 금액            |
| `tax_amount`         | float   | 부가세 금액               |
| `supply_amount`      | float   | 공급가액                  |
| `changed_by`         | str     | 변경자                    |
| `change_date`        | datetime| 변경 일시                  |
| `changed_field`      | str     | 변경 필드명               |
| `ip_address`         | str     | 접속 IP                   |
| `document_number`    | int     | 순차 전표번호 (UUID 별도)  |
| `approval_level`     | int     | 승인 레벨                  |

---

## 부록 C: 도메인 용어 ↔ 코드 매핑

| 감사 용어      | 영문              | DataSynth 컬럼         | 코드 변수              |
|---------------|-------------------|------------------------|------------------------|
| 전표          | Journal Entry      | `document_id`          | `journal_entry`, `je`  |
| 전기일        | Posting Date       | `posting_date`         | `posting_date`         |
| 전표일        | Document Date      | `document_date`        | `document_date`        |
| 적요          | Line Text          | `line_text`            | `line_text`            |
| 차변          | Debit              | `debit_amount`         | `debit_amount`         |
| 대변          | Credit             | `credit_amount`        | `credit_amount`        |
| 역분개        | Reversal           | `xstov` flag           | `is_reversal`          |
| 수기전표      | Manual JE          | `source='manual'`      | `is_manual_je`         |
| 관계사 거래   | Intercompany       | `company_code` 쌍      | `is_intercompany`      |
| 총계정원장    | General Ledger     | `gl_account`           | `gl_account`           |
| 이상징후      | Anomaly            | `is_anomaly`           | `anomaly`              |
| 입력자        | Created By         | `created_by`           | `created_by`           |
| 전표유형      | Document Type      | `document_type`        | `document_type`        |

---

## 부록 D: Fraud Red Flags (참고)

정상 전표에 부여된 의심 징후 (211건, 전부 is_fraudulent=False).
Phase 2 ML에서 **False Positive 내성 훈련**에 활용.

| pattern_name                      | 건수 | category    | strength | confidence |
|-----------------------------------|------|-------------|----------|------------|
| month_end_timing                  | 32   | Timing      | Weak     | 0.10       |
| round_dollar_amount               | 31   | Transaction | Weak     | 0.15       |
| vague_description                 | 20   | Document    | Weak     | 0.15       |
| after_hours_posting               | 18   | Timing      | Weak     | 0.15       |
| repeat_amount_pattern             | 15   | Transaction | Weak     | 0.18       |
| benford_first_digit_deviation     | 12   | Transaction | Weak     | 0.12       |
| weekend_transaction               | 12   | Timing      | Weak     | 0.12       |
| unusual_account_combination       | 11   | Account     | Weak     | 0.20       |
| invoice_without_purchase_order    | 11   | Document    | Moderate | 0.30       |
| employee_vacation_fraud_pattern   | 10   | Employee    | Moderate | 0.45       |
| amount_just_below_threshold       | 10   | Transaction | Moderate | 0.35       |
| missing_supporting_documentation  | 9    | Document    | Moderate | 0.30       |
| dormant_vendor_reactivation       | 7    | Vendor      | Moderate | 0.35       |
| new_vendor_large_first_payment    | 5    | Vendor      | Moderate | 0.40       |
| unusual_vendor_payment_pattern    | 4    | Vendor      | Moderate | 0.30       |
| vendor_no_physical_address        | 2    | Vendor      | Strong   | 0.15       |
| po_box_only_vendor                | 2    | Vendor      | Strong   | —          |

---

## 관련 문서

- [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) — 법규·기준서·도메인 지식 근거
- [pre-plan/05-detection.md](pre-plan/05-detection.md) — detection 구현 가이드
- [pre-plan/05a-detection-ml.md](pre-plan/05a-detection-ml.md) — Phase 2b ML 탐지기 설계
- [debugging.md](debugging.md) — engine.py rules 버그 기록
- [E2E 테스트 결과](../tests/test_detection/test-results/e2e-detection-datasynth.md)
