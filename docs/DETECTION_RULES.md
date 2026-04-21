# Detection Rules — 전표 부정 탐지 룰 전체 목록

한국 감사기준서(240호, K-SOX, PCAOB AS 2401)를 근거로 도출한 전표 부정 탐지 룰의 단일 참조 문서.
법규·기준서 근거는 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) 참조.

---

## 1. 개요

### 1.1 프로젝트 목적

ERP에서 추출한 전표 CSV 데이터에 대한 **전수 검사(CAATs)** 자동화.
감사인이 후속 수작업을 수행할 때의 우선순위 추천을 제공한다.

### 1.2 탐지 아키텍처 — L1/L2/L3/L4 + 독립 트랙

```
L1 (확정 오류/명시 위반)     ─ 전표 품질 게이트, 즉시 정정·차단 가능한 항목
L2 (강한 부정 정황)         ─ 구체적인 부정 시나리오·통제 우회 패턴
L3 (검토 필요 이상징후)     ─ 사람 검토가 필요한 운영·맥락형 수상 신호
L4 (통계적 이상치)          ─ 분포·희소성·통계 기반 이탈 신호
Benford (독립 트랙)         ─ L4-02을 별도 가중치로 분리한 분포 수준 검정
Variance (독립 트랙)        ─ 기존회사 전용, 전기 engagement 대비 급변 탐지
```

#### 1.2.1 L2 vs L3 경계 정의 (직교성)

L2와 L3는 의도(intent)와 신호 성격(signal type)으로 구분한다. 같은 전표가 양쪽에서 플래그될 수 있으나, 각 레이어가 잡는 의미는 다르다.

| 축 | L2 (강한 부정 정황) | L3 (검토 필요 이상징후) |
|----|-------------------|--------------------|
| **의도** | 의도적 부정 의심 (악의·은폐) | 오류·관행 이탈 (선의 포함) |
| **신호 성격** | 도메인 특화 패턴 (계정·승인·중복·SoD) | 통계·시간·텍스트 일반 이상 |
| **트리거 근거** | 부정 시나리오의 *수단* (어떻게 했는가) | 부정의 *흔적* (어디서 의심이 가는가) |
| **대표 룰** | L4-01 매출 이상 변동, L2-01 승인한도 직하, L2-03 중복 전표, L1-06 SoD | L3-04 기말 집중, L3-06 심야 전기, L4-03 이상 고액, L4-04 희소 계정쌍 |
| **오탐 비용** | 낮음 (실제 부정 가능성 시사) | 높음 (단순 업무 변동도 잡힘) |

**중복 플래그 처리 방침**:
- 동일 전표가 B와 C 양쪽에 플래그되면 `score_aggregator`의 레이어 가중합으로 자연스럽게 가산 효과 발생 (B 가중치 + C 가중치 → 종합 점수 상승). 별도 보너스 로직 없음.
- "L2만 단독 플래그"는 부정 의심도가 강함, "L3만 단독 플래그"는 검토 대상 표시. "L2+L3 동시"는 가장 강한 신호로 간주.

**해석 가이드** (감사인 검토 순서):
1. L1 flagged → 데이터 자체 오류 또는 명시 위반 의심
2. L2 flagged → 부정 시나리오 1순위 검토 (계정·승인·SoD 맥락)
3. L2+L3 동시 → 가장 우선 검토 (부정 의도 + 운영 이상이 함께 발현)
4. L3 단독 → 정상 영업 변동 가능성 확인 후 잔여만 추적

**중복 가능 사례** (혼선 방지를 위한 명시):
- L4-01 매출 이상 변동 ↔ L4-03 이상 고액: 매출 대규모 전표는 양쪽 모두 플래그 가능. L4-01은 "매출 계정 특화 맥락", L4-03은 "전체 통계 z-score". 분석 의도가 다르므로 양립 가능.
- L2-03 중복 전표 ↔ (없음): L3/L4 그룹에는 중복 룰이 없으므로 직접 충돌 없음.
- L2-05 (Top-side JE 복합) ↔ L3-04/L4-04: L2-05는 "기말+우회+비정상" 복합 점수라 L3-04·L4-04 신호를 *입력*으로 받음. 동일 전표 양쪽 플래그는 설계상 의도된 동작.

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

### 2.1 L1: 확정 오류/명시 위반 (8개)

전표테스트의 전제조건. 이 검증을 통과해야 이후 탐지가 의미있음.

#### L1-01 — 차대변 균형 (UnbalancedEntry)

- **심각도**: 5
- **근거**: 240§32 복식부기 원칙. FSS 횡령은폐 수법(차대 불일치)
- **탐지 로직**: `sum(debit) ≠ sum(credit)` per document_id. 허용 오차 1.0 (float 안전)
- **구현**: `integrity_layer.py` → `_a01_unbalanced_entry()`
  - document_id별 groupby → diff 계산
  - NaN document_id는 개별 더미 키로 처리
- **필요 피처**: `debit_amount`, `credit_amount`, `document_id`

#### L1-02 — 필수필드 누락 (MissingField)

- **심각도**: 2
- **근거**: 240-A45(d) 계정번호 없이 입력. K-SOX 전표기록 통제
- **탐지 로직**: 9개 필수 컬럼 NULL 검사
  - 필수: document_id, company_code, fiscal_year, fiscal_period, posting_date, document_date, document_type, gl_account, (debit_amount OR credit_amount)
- **구현**: `integrity_layer.py` → `_a02_missing_required()`
- **DataSynth 상태**: MCAR 2% 주입 추가됨, E2E 재검증 필요

#### L1-03 — 무효 계정 (InvalidAccount)

- **심각도**: 3
- **근거**: 240-A45(a) 비경상·저사용 계정 + 315호 비정상계정. FSS 가공전표(미사용계정 악용)
- **탐지 로직**: `gl_account NOT IN chart_of_accounts`
  - CoA(계정과목표) 미제공 시 스킵
- **구현**: `integrity_layer.py` → `_a03_invalid_account()`
- **필요 피처**: `gl_account`

---

#### 추가 L1 룰

#### L1-04 — 승인한도 초과 (ExceededApprovalLimit)

- **심각도**: 3
- **의미**: 전표 총액이 실제 승인자(`approved_by`)의 승인한도(`approval_limit`)를 초과한 경우를 탐지한다.
- **근거**: K-SOX 승인체계, ISA 240 §32. 승인권자가 자기 권한 범위를 넘는 금액을 승인했다면 통제 실패 또는 승인권한 위반 가능성이 있다.
- **판정 방식**
  - 같은 `document_id`의 차변 금액 합계로 전표 총액을 계산한다.
  - 전표의 `approved_by`를 직원 마스터(`employees.json`)와 연결해 해당 승인자의 `approval_limit`를 조회한다.
  - `전표 총액 > approved_by의 approval_limit`이면 `ExceededApprovalLimit`로 판정한다.
- **한 줄 규칙**: `SUM(debit_amount) BY document_id > approval_limit(approved_by)`
- **구현**
  - 피처 생성: `src/feature/amount_features.py` → `add_exceeds_threshold()`
  - 직원 한도 조회: `employees.json`의 `user_id`, `approval_limit`, `can_approve_je`
- **필요 컬럼**: `document_id`, `debit_amount`, `approved_by`, `approval_limit`(직원 마스터), `exceeds_threshold`(파생)

#### L1-05 — 자기 승인 (SelfApproval)

- **심각도**: 3
- **근거**: K-SOX 직무분리(외감법 §8①5호). FSS 오스템임플란트 사례처럼 1인이 입력, 승인, 자금 집행까지 이어서 수행하는 통제 우회 패턴을 직접 포착한다.
- **탐지 로직**
  - `created_by`와 `approved_by`가 모두 있을 때만 L1-05를 판정한다.
  - `approved_by == created_by`이면 자기승인으로 탐지한다.
  - `approved_by`가 없을 때는 `source='manual'`이라는 이유만으로 자기승인으로 추정하지 않는다.
  - 승인 누락이나 승인 생략은 **L1-07**에서 별도로 탐지한다.
- **기본 예외는 시스템 자동처리만 둔다**
  - 배치, 인터페이스, 반복 분개, 자동전표처럼 시스템이 스스로 생성하고 승인 로그까지 남긴 전표는 L1-05에서 제외한다.
  - 이것은 사람이 자기 전표를 자기 승인한 경우가 아니라 시스템 자동 처리로 보기 때문이다.
  - 기본 설정은 `user_persona == automated_system` 또는 `source == automated`일 때 제외하는 방식이다.
- **사람의 자기승인은 전부 탐지하되 결과를 두 단계로 나눈다**
  - **즉시 위반**: 원칙적으로 바로 통제 위반으로 볼 수 있는 자기승인
  - **검토 필요**: 자기승인 자체는 맞지만, 결산 조정이나 자산 조정처럼 회사 운영 방식에 따라 예외 전결이나 책임자 직접 처리 가능성이 있어 추가 확인이 필요한 경우
- **기본 분류 기준**
  - `R2R`, `A2R` 업무의 자기승인은 기본적으로 **검토 필요**로 둔다.
  - 그 외 사람 자기승인은 기본적으로 **즉시 위반**으로 둔다.
- **검토 필요라도 바로 즉시 위반으로 올리는 경우**
  - **금액이 너무 큰 수기 전표**
    - 결산(R2R)이나 자산조정(A2R)이라도, 사람이 직접 처리한 자기승인 전표가 수행중요성 금액을 넘으면 단순 검토 대상으로 두지 않는다.
    - 현재 `1,000,000,000`원은 어디까지나 **임시 기본값**이다. 모든 회사에 공통으로 맞는 적정값이 아니라, 실제 감사 착수 후 정한 **수행중요성 금액**으로 반드시 바꿔야 한다.
    - 즉 이 숫자는 "정답"이 아니라, 고객사별 중요성 산정 전까지 고위험 전표를 너무 늦게 보지 않기 위한 임시 안전장치에 가깝다.
    - 실제로는 회사 규모, 매출액, 자산 규모, 손익 변동성, 감사 목적에 따라 적정 금액이 크게 달라진다. 그래서 engagement별로 따로 관리하는 것이 맞다.
  - **주말 또는 심야에 처리된 자기승인**
    - 결산조정이라도 주말, 공휴일, 심야 시간대에 자기승인이 발생하면 통제 회피 가능성이 커지므로 바로 즉시 위반으로 올린다.
    - 구현상 `is_weekend`, `is_holiday`, `is_after_hours`, `time_zone_category`, `posting_time` 중 사용 가능한 시간 신호를 함께 본다.
  - **민감한 고위험 계정을 건드린 자기승인**
    - 현금성 자산, 가지급금, 가수금처럼 자기승인이 특히 위험한 계정은 결산 프로세스 안에 있더라도 즉시 위반으로 본다.
    - 기본 예시는 `1190(가지급금)`, `2190(가수금)`, 그리고 현금/예금 계열로 자주 쓰이는 `111`, `112`, `113` 접두사다.
    - 다만 계정체계는 회사마다 다르므로 실제 고객사 CoA에 맞게 반드시 수정해야 한다.
- **왜 이렇게 설계했는가**
  - 사람 기반 예외를 세세하게 많이 넣기 시작하면 룰 의미가 흐려지고, 나중에는 무엇을 잡는 룰인지 불명확해진다.
  - 그래서 L1-05는 먼저 사람 자기승인 사실을 빠짐없이 포착하고, 그 다음 단계에서 결과를 `즉시 위반`과 `검토 필요`로 나눠 보여주는 구조로 단순화했다.
  - 그리고 검토 대상으로 남겨도 안 되는 고위험 상황은 위 세 가지 승격 조건으로 다시 즉시 위반으로 끌어올리도록 했다.
- **어디서 수정하는가**
  - 시스템 자동처리 예외는 [config/audit_rules.yaml](/abs/path/C:/Users/ghdtj/workspace/portfolio/local-ai-assist/config/audit_rules.yaml)의 `patterns.self_approval_allow`에서 수정한다.
  - `즉시 위반`과 `검토 필요` 기본 구분은 같은 파일의 `patterns.self_approval_review`에서 수정한다.
  - 검토 대상을 다시 즉시 위반으로 승격시키는 조건은 `patterns.self_approval_immediate_override`에서 수정한다.
  - 여기서 수행중요성 금액(`materiality_amount`), 수기 소스(`manual_sources`), 고위험 계정(`high_risk_accounts`), 고위험 계정 접두사(`high_risk_account_prefixes`)를 바꿀 수 있다.
  - 회사별로 다르게 운영하려면 `data/companies/{company_id}/audit_rules.yaml`에서 같은 키를 오버라이드하면 된다.
  - 특히 `materiality_amount`는 전역 고정값으로 오래 두지 말고, 감사 계약별 수행중요성 금액이 정해지는 즉시 engagement 기준으로 덮어쓰는 것이 맞다.
- **구현**: `fraud_rules_access.py` → `b06_self_approval()`
- **필요 피처**: `created_by`, `approved_by`, `source`

#### L1-06 — 직무분리 위반 (SegregationOfDutiesViolation)

- **심각도**: 4
- **근거**: K-SOX 직무분리. FSS 오스템: 동일인 전프로세스 수행
- **탐지 로직**: 하이브리드 3단계 SoD
  1. **Toxic Pair 즉시 탐지**: `sod_toxic_pairs` (audit_rules.yaml)에 정의된 프로세스 쌍
  2. **In-process conflict**: `sod_conflict_type` 컬럼 기반 충돌 검출
  3. **Role-based 프로세스 수 제한**: junior=1, senior=3 (역할별 한도)
- **구현**: `fraud_rules_access.py` → `b07_segregation_of_duties()`
- **필요 피처**: `created_by`, `business_process`
- **DataSynth**: 1,365명 규모 (마스터 1,422), SOD 위반률 3.32% (10,595건, 2026-04-14 실측)

#### L1-07 — 승인 생략 (SkippedApproval)

- **심각도**: 4
- **근거**: K-SOX 승인절차(외감법§8②). FSS 오스템: 한도초과+승인없음 = §8② 직접 위반
- **탐지 로직**: 승인한도 초과 + 비자동(source != 'automated') + 승인 없음
- **구현**: `fraud_rules_access.py` → `b09_skipped_approval()`
- **필요 피처**: 금액, `source`, `created_by`, `approved_by`

#### L1-08 — 기간 불일치 (WrongPeriod)

- **심각도**: 4
- **근거**: 240§32(b) 기간귀속 적정성
- **탐지 로직**: `fiscal_period ≠ month(posting_date)`
- **구현**: `anomaly_rules_simple.py` → `c05_fiscal_period_mismatch()`
- **필요 피처**: `fiscal_period`, `posting_date`

---

### 2.2 L2: 강한 부정 정황 (5개)

#### L2-01 — 승인한도 직하 (JustBelowThreshold)

- **심각도**: 3
- **근거**: 240-A45(e) 단수/끝자리, K-SOX 승인체계
- **탐지 로직**: `금액 ∈ [threshold × 0.9, threshold)` — 6단계 승인한도
  - `approval_thresholds: [10M, 100M, 1B, 5B, 10B, 50B]` (KRW)
- **구현**: `fraud_rules_feature.py` → `b02_near_threshold()`
  - 피처 엔진에서 `is_near_threshold` 사전 계산
- **필요 피처**: `debit_amount`, `credit_amount`, `is_near_threshold` (파생)

#### L2-02 — 중복 지급 (DuplicatePayment)

- **심각도**: 3
- **근거**: 240§32 적정성. FSS 횡령은폐: 동일건 이중지급
- **탐지 로직**: 동일 벤더 + 동일 금액 + 기간 내 2건 이상
  - Bilateral diff (forward + backward)로 first-in-group도 포착
- **구현**: `fraud_rules_groupby.py` → `b04_duplicate_payment()`
- **필요 피처**: `auxiliary_account_number`, 금액, 날짜
- **DataSynth 상태**: ✅ auxiliary_account_number 59% 유효 (652K건, V-000xxx 형식)

#### L2-03 — 중복 전표 (DuplicateEntry)

- **심각도**: 3
- **근거**: 240§32, FSS 가공전표: 동일 전표 반복 = 가공
- **탐지 로직**: 동일 금액 + 계정 + 일자 매칭
  - `keep=False`로 원본·복제 양쪽 모두 플래그
- **구현**: `fraud_rules_groupby.py` → `b05_duplicate_entry()`
- **필요 피처**: `gl_account`, 금액, `posting_date`

#### L2-04 — 비용 자산화 (ExpenseCapitalization)

- **심각도**: 4
- **근거**: 240§32, FSS 분식회계: 개발비 과대자산화
- **탐지 로직**: 동일 document 내 차변=자산(15xx) + 대변=비용(6xxx)
  - Cartesian product 로직으로 N:M 전표 처리
- **구현**: `fraud_rules_groupby.py` → `b11_expense_capitalization()`
- **필요 피처**: `gl_account`, `debit_amount`, `credit_amount`

#### L2-06 — 역분개 패턴 (ReversalEntry)

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

---

### 2.3 L3: 검토 필요 이상징후 (6개)

#### L3-02 — 수기 전표 (ManualOverride)

- **심각도**: 4
- **근거**: 240-A45(b) 비인가자 입력, K-SOX 우회금지(외감법§8②). FSS 가공전표: 자동 프로세스 우회
- **탐지 로직**: `source == 'manual'` + 승인한도 초과
- **구현**: `fraud_rules_feature.py` → `b08_manual_override()`
- **필요 피처**: `source`, 금액, `exceeds_threshold` (파생)

#### L3-03 — 관계사 순환거래 (CircularIntercompany)

- **심각도**: 4
- **근거**: 550§23 특수관계자 합리성. FSS 순환거래: 페이퍼컴퍼니 A→B→C→A 가공매출
- **탐지 로직**: (MVP) IC GL prefix 매칭
  - `intercompany_identifiers: ['1150', '2050', '4500', '2700']`
  - Phase 3 WU-22 완료: 실제 N-hop 순환 탐지는 **GR01(GraphDetector)** 에서 담당 (§4.4 참조)
- **구현**: `fraud_rules_access.py` → `b10_circular_intercompany()`
  - 3법인(C001/C002/C003) 간 IC 거래 식별
- **필요 피처**: `company_code`, `gl_account`, `reference`
- **중복 점수화 주의**: L3-03(L3 그룹)과 GR01(Graph track)이 동일 IC 전표에 각각 flag 가능. 현재 MAX 패턴으로 흡수되나 Phase 3 Stacking 단계에서 L3-03 deprecation 또는 skip 플래그 결정 필요 (별도 이슈).

#### L3-04 — 기말 대규모 (RushedPeriodEnd)

- **심각도**: 3
- **근거**: 240§32(a)(ii)+A44 기말검사 의무. FSS 결산수정 27건(29%)
- **탐지 로직**: 월말 5일 이내 + 금액 > Q3 (3사분위수)
- **구현**: `anomaly_rules_simple.py` → `c01_period_end_large()`
- **필요 피처**: `posting_date`, 금액, `is_period_end` (파생)

#### L3-05 — 주말 전기 (WeekendPosting)

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. FSS 비정상시점 4건
- **탐지 로직**: `weekday() >= 5` 또는 한국 공휴일 플래그
- **구현**: `anomaly_rules_simple.py` → `c02_weekend_entry()`
- **필요 피처**: `posting_date`, `is_weekend` (파생), `is_holiday` (파생)

#### L3-06 — 심야 전기 (AfterHoursPosting)

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. KLCA IT 체크리스트
- **탐지 로직**: 22시~06시 (midnight_start: 22, midnight_end: 6)
- **구현**: `anomaly_rules_simple.py` → `c03_after_hours_entry()`
- **필요 피처**: `posting_date` (시간 포함), `is_after_hours` (파생)
- **DataSynth**: v1.2.0에서 datetime 포함으로 해결

#### L3-07 — 소급 전기 (BackdatedEntry)

- **심각도**: 3
- **근거**: 240-A45(c) 기말+설명없음. FSS 횡령은폐
- **탐지 로직**: `posting_date - document_date > N일` (임계값 초과)
- **구현**: `anomaly_rules_simple.py` → `c04_backdated_entry()`
- **필요 피처**: `posting_date`, `document_date`, `days_between` (파생)

#### L3-08 — 위험 적요 (VagueDescription)

- **심각도**: 1
- **근거**: 240-A45(c) 설명없음, K-SOX§8①1호 기록방법
- **탐지 로직**: `line_text` 공백/누락 또는 위험 키워드 매칭
  - 품질 키워드: 3자 미만, 공백만, 숫자만
  - 위험 키워드: config/keywords.yaml 기반 (수정, 정정, 오류, adjust 등)
- **구현**: `anomaly_rules_simple.py` → `c06_risky_description()`
- **필요 피처**: `line_text`, `header_text`, `is_vague_description` (파생), `has_risk_keyword` (파생)

#### L3-09 — 가수금 장기체류 (SuspenseAccountAbuse)

- **심각도**: 3
- **근거**: 외감법§8①2호 오류통제. FSS 횡령은폐: 가수금을 통한 자금 유용
- **탐지 로직**: `is_suspense_account == True` (하이브리드 — 텍스트 키워드 OR GL 코드 prefix)
- **구현**: `anomaly_rules_simple.py` → `c10_suspense_account()`
- **필요 피처**: `is_suspense_account` (파생)
- **DataSynth 상태**: GL 코드 강제 배정으로 탐지 정상 작동. 적요 키워드 주입은 30% 확률이나 전체 확률 체인(0.5%×5%×30%) 상 극소수만 생성됨 — 이는 정상 동작.
- **Phase 3 이관**: 적요 의미 분석은 키워드 매칭의 근본 한계(우회 표현, 동의어, 은어)로 인해 Phase 3 LLM(#71 적요 NLP + #84 kiwipiepy + #88 semantic_similarity)에서 해결

---

### 2.4 L4: 통계적 이상치 (5개 + Benford 독립 트랙)

#### L4-01 — 매출 이상 변동 (RevenueManipulation)

- **심각도**: 5
- **근거**: 240보론2, §32(c) 비경상거래. **FSS 최다유형**: 매출 허위계상
- **탐지 로직**: 매출 계정(4xxx) 금액이 Z-score 임계값 초과
  - `revenue_account_prefixes: ['4']` (settings.py)
- **구현**: `fraud_rules_feature.py` → `b01_revenue_manipulation()`
- **필요 피처**: `gl_account`, `debit_amount`, `is_revenue_account` (파생)

#### L4-02 — Benford 위반 (BenfordViolation) — 독립 트랙

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
  - L4-02은 분포 수준 검정이므로 L3/L4 묶음과 별도 가중치(0.15) 부여
  - 내부적으로 `anomaly_rules_statistical.py` → `c07_benford_violation()` 호출
- **필요 피처**: `debit_amount`, `credit_amount`
- **DataSynth 상태**: ⚠️ 위반 금액 미주입 (자연스러운 Benford 분포)

  추가 검정 (Phase 2): Chi-square, Anderson-Darling

#### L4-03 — 이상 고액 (UnusuallyHighAmount)

- **심각도**: 3
- **근거**: 240§33(b), 315호. FSS 결산수정: 개발비 과대자산화
- **탐지 로직**: Z-score > 3 (임계값)
- **구현**: `anomaly_rules_simple.py` → `c08_amount_outlier()`
- **필요 피처**: `debit_amount`, `credit_amount`, `amount_zscore` (파생)

#### L4-04 — 비정상 계정조합 (UnusualAccountPair)

- **심각도**: 2
- **근거**: 240-A45(a) 비경상·저사용 계정, 315호
- **탐지 로직**: 차변-대변 GL 계정 쌍 빈도 하위 1%
  - Merge 기반 벡터화된 Cartesian product
  - 100-line limit per document (메모리 오버플로우 방지)
- **구현**: `anomaly_rules_statistical.py` → `c09_rare_account_pair()`
- **필요 피처**: `gl_account` (차변/대변 행 쌍)

#### L4-06 — 배치 전표 이상 (BatchAnomaly) — Phase 2 WU-09

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

### 2.5 Variance 독립 트랙: 전기 대비 변동 (2개, 기존회사 전용)

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

#### Variance 독립 트랙 가중치 (기존회사 전용)

Variance 트랙이 활성화되면 전체 가중치가 재배분된다.

| 레이어          | 신규회사 | 기존회사 |
|-----------------|:--------:|:--------:|
| A (무결성)      | 0.15     | 0.12     |
| B (부정)        | 0.45     | 0.38     |
| C (이상징후)    | 0.25     | 0.20     |
| Benford         | 0.15     | 0.12     |
| **D (전기 변동)** | **—**  | **0.18** |

---

### 2.6 점수 체계

> **⚠️ 근거 없음 — 프로젝트 자체 설계안.**
> 아래 가중치와 임계값은 공식 기준서·학술 논문 근거가 아닌 초기 설계값이다.
> 실제 데이터 기반 튜닝(Phase 1 완료 후 back-testing)을 거쳐 조정될 예정.

#### 가중치

```
anomaly_score = L1_track × W_L1 + L2_track × W_L2 + L3L4_track × W_L3L4 + Benford × W_Benford

  W_A (무결성) = 0.15    ← 위반 시 다른 점수의 신뢰도 자체가 떨어짐
  W_B (부정)   = 0.45    ← 핵심 탐지 레이어
  W_C (징후)   = 0.25    ← 보조 징후
  W_Benford    = 0.15    ← 통계적 배경
```

#### 위험 등급

```
High:   anomaly_score > 0.7  또는  L1 위반 + L2 2개 이상
Medium: anomaly_score > 0.4
Low:    anomaly_score > 0.2
Normal: anomaly_score ≤ 0.2
```

#### 자동 에스컬레이션

- (L1 flagged ≥1) AND (L2 flagged ≥2) → Risk = **High** (점수 무관 강제 상향)

#### 심각도(Severity) 맵

```
L1-01: 5  L1-02: 2  L1-03: 3
L4-01: 5  L2-01: 3  L1-04: 3  L2-02: 3  L2-03: 3  L1-05: 3  L1-06: 4  L3-02: 4  L1-07: 4  L3-03: 4  L2-04: 4
L3-04: 3  L3-05: 2  L3-06: 2  L3-07: 3  L1-08: 4  L3-08: 1  L4-02: 2  L4-03: 3  L4-04: 2  L3-09: 3
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

## 3. Phase 2: ML / DL 보조 분석

Phase 2는 Phase 1의 룰 기반 탐지를 대체하는 단계가 아니라, **룰만으로 놓치기 쉬운 패턴형 이상거래를 보완**하는 계층이다.
특히 금액 분포, 시계열 패턴, 신규 거래관계, 중복·유사 반복, 법인 간 상호작용처럼 단일 룰로 정의하기 어려운 신호를 구조적으로 포착한다.

구현은 두 단계로 분리한다.

- `phase2-train`: 전처리, feature variant 생성, family별 trial 실행, leaderboard 정리, promoted model 선정
- `phase2-infer`: 학습 결과에서 승격된 모델과 계약 정보를 읽어 실제 배치에 추론 적용

핵심 구현 파일:
- `src/services/phase2_training_service.py`
- `src/services/phase2_inference_service.py`
- `src/pipeline.py`
- `src/db/loader.py`, `src/db/batch_reader.py`

### 3.1 목적

Phase 2의 목적은 다음 네 가지다.

1. **룰 기반 정탐 보완**: L2/L3/L4 규칙만으로는 설명되지 않는 거래 패턴을 확장 포착
2. **구조적 이상 탐지**: 연속 발생, 군집 발생, 관계형 이상, 신규성 이상 탐지
3. **모델 계약 기반 운영**: 어떤 모델이 학습되고 승격되었는지 추적 가능하게 운영
4. **Phase 3 입력 강화**: 이후 요약·설명 단계가 어떤 모델과 어떤 계약 위에서 생성됐는지 남김

즉 Phase 2는 “DataSynth 유형을 1:1로 각각 분리 구현하는 단계”가 아니라, **여러 이상 신호를 family 단위 모델 계층으로 흡수하는 구조**를 목표로 한다.

### 3.2 전처리

Phase 2는 공통 feature frame을 만든 뒤, 여러 family가 이를 공유해서 사용한다.

#### 공통 전처리

- 금액 컬럼 정규화: 차변·대변·절대금액·로그금액 기반 수치화
- 날짜/시간 파생: 월말 여부, 주말 여부, 심야 여부, posting 간격, 문서 생성 순서
- 사용자/조직 컨텍스트: `created_by`, `approved_by`, `company_code`, `business_process`
- 텍스트/레퍼런스 보조: `line_text`, `header_text`, `reference`, 거래처·계정 관련 reference feature
- 품질 프로파일: 결측률, cardinality, usable ratio를 요약하여 family별 사용 가능 feature를 판정

#### Feature Variant

동일 데이터셋에 대해 여러 전처리 variant를 만든다.

- `baseline_core`: 금액, 계정, 날짜, 기본 사용자 정보 중심
- `plus_persona`: 사용자·승인자·프로세스·회사/부문 맥락 추가
- `plus_reference`: reference, 적요, counterparty, auxiliary 식별자 등 확장 feature 포함

이 variant들은 단순 편의 기능이 아니라, **같은 모델 family라도 어떤 feature 묶음이 실제로 더 잘 작동하는지 비교**하기 위한 탐색 단위다.

#### Rule-Style Family용 입력

일부 family는 일반 tabular embedding보다 구조화 집계 입력이 더 중요하다.

- `timeseries`: 사용자/계정/거래처 단위 빈도, burst, 간격, 직전 대비 변화량
- `relational`: 신규 거래쌍, dormant 재활성, 희귀 관계 조합
- `duplicate`: exact duplicate, near duplicate, 반복 금액/설명 패턴
- `intercompany`: 법인 간 쌍방향, unmatched pair, 비정상 offset 패턴

### 3.3 모델 Family 구성

Phase 2는 하나의 모델이 아니라 여러 family를 병렬로 비교하고, 각 family에서 가장 나은 trial만 승격 대상으로 삼는다.

#### 1. Unsupervised Family

- 목적: 라벨 부족 환경에서 전반적 이상 score 생성
- 대표 모델: VAE 계열 + Isolation Forest 조합
- 강점:
  - 금액 분포가 유난히 튀는 거래
  - 기존 군집과 멀리 떨어진 전표
  - 여러 feature가 동시에 약하게 이상한 복합 신호
- 잘 잡는 예시:
  - 비정상 고액 전표
  - 평소 거의 안 쓰던 조합으로 입력된 전표
  - 여러 약한 red flag가 겹친 전표

#### 2. Supervised Family

- 목적: 신뢰 가능한 라벨이 있을 때 명시적 fraud/anomaly 구분 성능 강화
- 대표 모델: 기존 지도학습 detector와 CV 기반 후보 선택기
- 강점:
  - 이미 관측된 부정 패턴의 재발 탐지
  - feature importance 기반 설명 가능성 확보
- 잘 잡는 예시:
  - 승인 우회 + 특정 사용자 + 특정 금액대 조합
  - 과거 확정 라벨과 유사한 분식/은폐 패턴

#### 3. Transformer Family

- 목적: tabular feature 간 비선형 상호작용 포착
- 대표 모델: FT-Transformer 계열
- 강점:
  - 계정, 사용자, 회사, 프로세스가 복합적으로 얽힌 패턴
  - 단일 룰로 표현하기 어려운 조건 결합
- 잘 잡는 예시:
  - 특정 회사·특정 사용자·특정 계정대에서만 발생하는 복합 이상
  - reference와 금액, 시점이 함께 이상한 경우

#### 4. Sequence Family

- 목적: 시간 순서와 사용자의 연속 행동 패턴 반영
- 대표 모델: sequence detector / BiLSTM 계열
- 강점:
  - 직전 거래와의 연속성, burst, reversal-like 흐름 탐지
  - 시계열 문맥이 있어야 드러나는 이상 포착
- 잘 잡는 예시:
  - 짧은 시간에 같은 사용자가 반복 입력한 전표 묶음
  - 직전 패턴과 급격히 다른 posting 흐름
  - 월말·마감 직전의 비정상 연쇄 입력

#### 5. Timeseries Family

- 목적: burst, frequency, cadence 이상을 명시적으로 포착
- 대표 탐지 축:
  - `TransactionBurst`
  - `UnusualFrequency`
- 강점:
  - 평소 드문 사용자가 특정 시점에 갑자기 몰아서 입력하는 패턴
  - 특정 계정/거래처 조합의 빈도 급등
- 잘 잡는 예시:
  - 결산 직전 이례적으로 같은 사용자가 동일 유형 전표를 집중 입력
  - 평소 월 1~2건이던 거래가 며칠 내 수십 건으로 급증

#### 6. Relational / Novelty Family

- 목적: 관계 기반 신규성, 휴면 후 재활성, 익숙하지 않은 counterpart를 탐지
- 대표 탐지 축:
  - `DormantAccountActivity`
  - `NewCounterparty`
- 강점:
  - 과거 맥락을 기준으로 새롭거나 오래 쉬었다가 다시 나타난 상대방 탐지
- 잘 잡는 예시:
  - 장기간 사용하지 않던 계정/거래처가 갑자기 큰 금액으로 재등장
  - 기존 거래 이력이 거의 없는 counterparty와의 최초 대규모 거래

#### 7. Duplicate Family

- 목적: exact/near duplicate 패턴을 ML 계약 안에서 운영
- 대표 탐지 축:
  - `ExactDuplicateAmount`
  - 반복 금액·적요·사용자 조합
- 강점:
  - 단순 룰 중복 탐지를 학습/계약 체계와 연결
  - duplicate 관련 family도 leaderboard와 promoted contract에 포함
- 잘 잡는 예시:
  - 같은 금액·같은 상대방·유사 적요로 반복된 전표
  - 약간의 시차만 두고 재발행된 동일 패턴 전표

#### 8. Intercompany Family

- 목적: 법인 간 거래의 비대칭, 미정합, 비정상 상계 흐름 탐지
- 대표 탐지 축:
  - `UnmatchedIntercompany`
- 강점:
  - 한쪽 법인엔 있는데 반대편 법인엔 정합되는 거래가 없는 경우 포착
  - 상계 타이밍과 금액 불일치 탐지
- 잘 잡는 예시:
  - C001→C002 거래는 있는데 반대 기록이 누락된 경우
  - 유사 거래가 상호 법인에 비대칭 금액으로 반복되는 경우

#### 9. Stacking Family

- 목적: 여러 family score를 다시 메타 레벨에서 결합
- 대표 모델: OOF 기반 ensemble detector
- 강점:
  - 개별 family가 놓친 약한 신호를 결합해 최종 score 안정화
  - unsupervised + supervised + transformer + sequence + rule-style family를 함께 활용

### 3.4 어떤 부정을 잡는가

Phase 2는 특정 유형 이름을 1:1로 직접 매핑하기보다, 다음과 같은 부정 패턴군을 포착한다.

#### 금액·분포 이상

- 비정상 고액
- 분포상 극단치
- 평소와 다른 금액대의 반복 입력
- 특정 digit/round pattern이 비정상적으로 몰린 거래군

#### 반복·빈도 이상

- 짧은 시간에 몰아 입력된 거래
- 비정상적 반복 빈도
- exact/near duplicate 전표
- reversal 또는 cancel-repost처럼 보이는 연쇄 흐름

#### 관계·신규성 이상

- 처음 등장한 counterparty와의 큰 거래
- 장기간 휴면 후 재활성된 계정 또는 관계
- 평소 쓰지 않던 관계 조합
- 회사 간 비정상 상호작용 또는 미정합

#### 복합 조건형 이상

- 특정 사용자 + 특정 계정 + 특정 시점이 겹칠 때만 드러나는 패턴
- 룰 단독으론 약하지만 여러 신호가 겹치며 강해지는 거래
- Phase 1에서 약하게 표시된 전표 중, ML score가 추가로 높게 나오는 경우

### 3.5 하이퍼파라미터와 탐색 방식

Phase 2는 “모든 모델 × 모든 하이퍼파라미터의 exhaustive search”를 수행하지 않는다.
대신 **family별 preset search + variant 비교 + 승격 정책**으로 운영 가능한 탐색 구조를 만든다.

#### 탐색 단위

- feature variant
- search preset
- model family

즉 하나의 trial은 대략 다음 조합으로 정의된다.

- `family × feature_variant × search_preset`

#### Family별 조정 예시

- `unsupervised`
  - contamination
  - latent dimension
  - hidden width
  - epoch / learning rate
- `supervised`
  - class weight
  - sampling 정책(SMOTE 여부 등)
  - estimator 후보와 CV 설정
- `transformer`
  - hidden size
  - head 수
  - dropout
  - epoch / batch size
- `sequence`
  - sequence length
  - hidden size
  - recurrent depth
  - stride / context column 사용 여부
- `timeseries / relational / duplicate / intercompany`
  - window size
  - min frequency
  - tolerance
  - matching threshold
  - proxy scoring weight
- `stacking`
  - base family selection
  - OOF 사용 여부
  - meta learner 입력 조합

#### 승격 정책

각 family의 최고 점수 trial을 무조건 승격하지 않고, 다음 조건을 함께 본다.

- 최소 completed trial 수
- 최소 metric 기준
- 최소 search 다양성
- 최대 failed trial 비율
- registry version 또는 artifact 존재 여부

즉 “한 번 우연히 잘 나온 trial”은 승격에서 제외될 수 있다.

Rule-style family는 일반 AUC 대신 `rule_proxy_score` 성격의 정규화 점수를 사용해 leaderboard에 올린다.

### 3.6 Train / Infer 계약

#### Train (`phase2-train`)

1. 라벨 가용성 판정
2. feature frame 생성
3. feature variant 생성
4. family별 trial queue 구성
5. trial 실행
6. leaderboard 정렬
7. promoted model 선정
8. training report / promotion policy / inference contract 저장

#### Infer (`phase2-infer`)

1. 최신 또는 지정된 training report 확인
2. promoted model 및 required family 확인
3. family별 detector 실행
4. detector status, registry version, sub detector 정보 기록
5. 최종 phase2 score 생성

이 구조 덕분에 추론 시점에는 “그때그때 가장 최근 모델을 대충 불러오는 방식”이 아니라, **학습 리포트에서 승격된 정확한 버전**을 기준으로 운영할 수 있다.

### 3.7 Provenance

Phase 2는 결과만 남기지 않고, 어떤 계약으로 돌았는지까지 남긴다.

핵심 메타데이터:
- `phase2_training_report_id`
- `phase2_inference_contract`
- `phase2_promotion_policy`
- `phase2_inference_mode`
- `detector_statuses_json`

추론 모드 예시:
- `training_contract`: 승격 모델 기반 정상 운영
- `cold_start_bootstrap`: 초기 모델 부재 시 예외적 cold-start 실행
- `untrained_contract_only`: 학습 계약은 있으나 실제 추론 승격 모델이 없는 상태

이 provenance는 DB 저장, 복원, export, Phase 3 insight prompt까지 연결된다.

### 3.8 해석 기준

Phase 2 결과는 “유형 A detector가 유형 A만 잡는다”는 의미로 해석하지 않는다.
대신 다음처럼 해석한다.

- 특정 family가 높다: 그 family가 잘 포착하는 구조적 이상 신호가 강하다
- 여러 family가 동시에 높다: 단일 룰보다 더 강한 복합 이상 정황일 수 있다
- stacking이 높다: 개별 family 신호가 메타 레벨에서 일관되게 위험하다고 본 경우다

즉 Phase 2는 **룰 기반 판단을 보완하는 모델 계층**이며, 감사인의 후속 검토 우선순위를 정밀화하는 역할을 한다.

### 3.9 후속 고도화

향후 확장 방향은 다음과 같다.

- family 내부 탐색 공간 확대
- feature variant 세분화
- promotion policy 추가 강화
- 도메인 특화 reference / counterparty feature 확장
- 실제 운영 데이터 기준 재학습 정책 고도화

현재 구현의 목표는 “완전 탐색 AutoML”이 아니라, **설명 가능하고 추적 가능한 Phase 2 운영 구조**를 만드는 데 있다.

## 4. Phase 3: NLP + 그래프 (5개 유형, 미구현)

| DataSynth 유형          | 카테고리     | Sev | 방법               | 상태 |
|-------------------------|-------------|-----|--------------------|------|
| LatePosting             | ProcessIssue | 2  | 시계열 NLP 복합     | ⬜   |
| MissingDocumentation    | ProcessIssue | 3  | NLP (적요 분석)     | ⬜   |
| CircularTransaction     | Graph(GR01)  | 4  | Johnson N-hop 순환 (length_bound=5) | ✅ WU-22 |
| TransferPricingAnomaly  | Graph(GR03)  | 4  | 양방향 IC 엣지 price asymmetry      | ✅ WU-22 |
| TrendBreak (TL4-01/TL2-01)  | Statistical  | 4/3| 설정vs상각 분리     | ✅   |

### Phase 3 점수 체계 (7트랙)

```
rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + duplicate(0.15) + nlp(0.10) + graph(0.15)
```

**Phase 3 누적: Tier 1(20) + Tier 2(16) + Tier 3(5) = 41개 유형 커버**

---

### 4.4 Graph Detector (WU-22) — networkx 기반 순환·이전가격

> **근거**: ISA 550 §23 특수관계자 사업상 합리성 · FSS 순환거래 페이퍼컴퍼니 패턴.
> **차별화**: L3-03(관계사 전표 존재 flag) 및 R03(그룹 편차 통계)의 한계를 그래프 토폴로지로 보완.

#### GR01 — CircularTransaction (N-hop 순환)

- **심각도**: 4
- **알고리즘**: networkx `simple_cycles(G, length_bound=max_cycle_length)` (Johnson)
- **그래프 구성**:
  - 노드: `(company_code, trading_partner)` 튜플
  - 엣지: `credit > 0` → `company → partner`, `debit > 0` → `partner → company`
  - 자료구조: `MultiDiGraph` (다중 엣지 보존 → 원본 행 인덱스 역매핑)
- **`trading_partner` NULL fallback**: 동일 `document_id` 그룹의 다른 `company_code`로 implicit IC pair 추론 (DataSynth 640건 NULL 복구 목적)
- **점수화**: binary 1.0 × `severity_factor(0.8)` (연속 점수화는 튜닝 단계로 이연)
- **L3-03과의 관계**: L3-03은 `is_intercompany` 플래그만 반환(recall 7%). GR01이 실제 N-hop 순환 탐지. Phase 3 Stacking 단계에서 L3-03 deprecation 여부 결정.

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
| UnusualTiming            | 7    | L3-05/L3-06과 완전 중복 → 별도 유형 불필요             |
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
| 거래처 식별    | `auxiliary_account_number` | L2-02에서 사용                                                               | 59% 유효 (652K건)                               | ✅ 해결   |
| 심야 기준      | 22시~06시                | `midnight_start: 22`                                                       | posting_date datetime (시분초 포함)             | ✅ 해결   |
| 관계사 식별    | GL 계정 prefix 매칭       | `intercompany_identifiers: ['1150', '2050', '4500', '2700']`               | IC GL 1150/2050/4500/2700 존재                  | ✅ 해결   |
| 직무분리 임계  | 하이브리드 3단계 SoD      | `sod_toxic_pairs` + `sod_role_thresholds`                                   | 1,365명, automated 제외 + Toxic Pair + Role-based | ✅ 해결   |
| Benford 위반   | MAD > 0.012              | `benford_mad_threshold: 0.012`                                              | BenfordViolation 157건 라벨 주입                | ✅ 해결   |
| 필수필드 누락  | 9컬럼 NULL 검사           | schema.yaml 참조                                                           | MCAR 2% (gl_account, document_type)             | ✅ 해결   |

### 해결 완료 (v1.2.0)

| 항목 | 원인 | 조치 | 파일 |
|:-----|:-----|:-----|:-----|
| L2-01/L3-02 승인한도 불일치 | 단일 한도 + USD 금액 범위 | KRW 6단계 승인한도 + lognormal mu=14.0 | `settings.py`, `datasynth.yaml` |
| L1-06 SOD 과탐 | 41명 소규모 시뮬레이션 | 1,365명 확대, SOD 위반률 3.32% (2026-04-14 실측) | `datasynth.yaml` |
| L3-03 관계사 미식별 | `intercompany_identifiers: []` | IC GL prefix 4개 등록 | `audit_rules.yaml` |
| L3-06 심야 미탐지 | posting_date 시간정보 없음 | datetime 전환 | `schema.yaml`, DataSynth |
| `is_suspense_account` all-False | 한글 키워드만 매칭 | 하이브리드: 텍스트 키워드 OR GL 코드 prefix | `pattern_features.py`, `audit_rules.yaml` |
| `is_round_number` all-False | float 소수점 꼬리 | `base.round(0) % unit` 허용 | `amount_features.py` |

### v21 확정 결과 (2026-04-02)

| 항목 | 값 |
|:-----|:---|
| Phase 1 Recall | 91.4% (2,408 / 2,636) |
| 전체 Recall | 92.0% (7,197 / 7,827) |
| 100% Recall 룰 | 10개 (L1-01, L1-02, L1-03, L4-01, L2-02, L3-05, L3-06, L1-08, L3-08, L2-06) |
| L1-06 flagged | 1.9% (정상) |
| Normal 등급 | 85.2% |
| 구조적 한계 (ML 필요) | L2-03(10%), L3-03(4%), L4-04(9%), L4-02(29%) — Phase 2 대상 |

상세: [test-results/rule-label-gap-analysis.md](../tests/phase1_rulebase/test-results/rule-label-gap-analysis.md)

### 미해결 (경미 — Phase 2 이후)

| 항목 | 원인 | 현재 상태 | 대상 |
|:-----|:-----|:---------|:-----|
| L3-09 적요 키워드 부족 | 확률 체인(0.5%×5%×30%)으로 키워드 주입 건수 극소 — 정상 동작 | GL prefix 기반 탐지 정상 작동. 적요 의미 분석은 Phase 3 LLM 영역(#71, #84, #88) | Phase 3 이관 |
| trading_partner | 99.9% NULL (784건) | L3-03 IC GL prefix 매칭으로 대체 | DataSynth Rust |
| cost_center | 81.2% NULL | L2-06 세분화 키 활용도 제한 | DataSynth Rust |

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
UnbalancedEntry                   3     2     3      8    A       L1-01
MissingField                      3     1     3      7    A       L1-02
InvalidAccount                    3     1     3      7    A       L1-03
RevenueManipulation               3     3     3      9    B       L4-01
JustBelowThreshold                3     2     3      8    B       L2-01
ExceededApprovalLimit             1     2     3      6    B       L1-04
DuplicatePayment                  2     3     3      8    B       L2-02
DuplicateEntry                    2     3     3      8    B       L2-03
SelfApproval                      1     3     3      7    B       L1-05
SegregationOfDutiesViolation      1     3     3      7    B       L1-06
ManualOverride                    3     3     3      9    B       L3-02
SkippedApproval                   1     3     3      7    B       L1-07
CircularIntercompany              3     2     3      8    B       L3-03
ExpenseCapitalization              —     —     —      —    B       L2-04  *
RushedPeriodEnd                   3     3     3      9    C       L3-04
WeekendPosting                    3     1     3      7    C       L3-05
AfterHoursPosting                 3     1     3      7    C       L3-06
BackdatedEntry                    3     2     3      8    C       L3-07
WrongPeriod                       2     2     3      7    C       L1-08
VagueDescription                  3     3     3      9    C       L3-08
BenfordViolation                  3     2     2      7    Benford L4-02
UnusuallyHighAmount               2     3     3      8    C       L4-03
UnusualAccountPair                3     1     2      6    C       L4-04
SuspenseAccountAbuse              —     —     —      —    C       L3-09  *
```

> \* L2-04, L3-09은 DataSynth 52개 유형 외 프로젝트 자체 도출 룰이므로 3축 평가 대상 외.

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
UnusualTiming                3     1     3      7    L3-05/L3-06 중복
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
| `document_id`    | str    | `belnr` | 전표 ID (UUID)    | L1-01, L2-02, L2-03          |
| `company_code`   | str    | `rbukrs`| 회사코드          | L3-03                    |
| `fiscal_year`    | int    | `gjahr` | 회계연도          | L1-08                    |
| `posting_date`   | date   | `budat` | 전기일            | L3-04~L1-08                |
| `document_date`  | date   | `bldat` | 전표일            | L3-07                    |
| `gl_account`     | int    | `racct` | G/L 계정코드      | L1-03, L4-01, L4-04          |
| `debit_amount`   | float  | `wsl(S)`| 차변 금액         | L1-01, L2-01~L2-03, L4-02~L4-03  |
| `credit_amount`  | float  | `wsl(H)`| 대변 금액         | L1-01, L2-01~L2-03, L4-02~L4-03  |
| `document_type`  | str    | `blart` | 전표유형          | L4-01                    |

### 권장 컬럼 (10개)

| 컬럼명             | 타입   | ACDOCA  | 설명              | 탐지 활용   |
|--------------------|--------|---------|--------------------|------------|
| `created_by`       | str    | `usnam` | 입력자             | L1-05~L1-07    |
| `source`           | str    | —       | 입력소스           | L3-02, L1-07   |
| `business_process` | str    | —       | 비즈니스 프로세스   | L1-06        |
| `line_number`      | int    | `docln` | 라인번호           | L1-01        |
| `local_amount`     | float  | `hsl`   | 현지통화 금액      | 환율 검증   |
| `currency`         | str    | `rwcur` | 통화               | 환율 검증   |
| `cost_center`      | str    | `rcntr` | 코스트센터         | —          |
| `profit_center`    | str    | `prctr` | 손익센터           | —          |
| `line_text`        | str    | `sgtxt` | 적요               | L3-08        |
| `header_text`      | str    | `bktxt` | 헤더 텍스트        | L3-08        |

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
