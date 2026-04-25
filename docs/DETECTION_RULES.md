# Detection Rules — 전표 부정 탐지 룰 전체 목록

한국 감사기준서(240호, K-SOX, PCAOB AS 2401)를 근거로 도출한 전표 부정 탐지 룰의 단일 참조 문서.
법규·기준서 근거는 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) 참조.

탐지 파이프라인은 **PHASE 1 (전수 필터/Recall) → PHASE 2 (스코어 보정/Precision) → PHASE 3 (의미 해석/Explainability)** 순서로 이어진다.

- **PHASE 1**은 룰 기반 전수 필터다. 넓게 잡고, 개별 룰을 evidence/theme/case로 묶어 감사 검토 큐를 만든다.
- **PHASE 2**는 PHASE 1을 대체하지 않고, case 단위 우선순위를 구조적·통계적 모델로 보정한다. 룰 ID 자체를 예측 feature로 쓰지 않는다.
- **PHASE 3**는 전체 원천 전표를 무차별 분석하지 않고, 선별된 case에 대해 적요·계정·관계 맥락을 해석하고 감사인이 읽을 수 있는 근거 기반 narrative를 만든다.

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

### 1.3 52개 유형 → 채택 판정

DataSynth 52개 anomaly 유형을 3축 평가(법규 근거 × 실증 빈도 × 데이터 가용성)로 선별.
판정 방법론 상세는 [DETECTION_REFERENCE.md §4](DETECTION_REFERENCE.md#4-3축-평가-방법론) 참조.
아래의 `유형 수`는 DataSynth 원천 anomaly 유형 기준이며, 실제 Phase 1 구현 룰 수와 1:1로 대응하지 않는다. Phase 1은 Must 유형을 감사 검토 가능한 세부 룰로 확장해 현재 31개 룰로 운영한다.

```
판정     유형 수   적용 단계   구현/운영 단위                  FSS 6대 패턴 커버
────────────────────────────────────────────────────────────────────────────────
Must      20개    Phase 1    31개 룰 기반 즉시 탐지            6/6 (전부 커버)
Should    16개    Phase 2    ML/통계 확장                      가공전표·결산수정 정밀도↑
Could      5개    Phase 3    NLP/그래프 고급 탐지               순환거래 정밀도↑
Drop      11개    —          제외                              —
────────────────────────────────────────────────────────────────────────────────
합계      52개               Phase 3 누적: 41개 유형 커버
```

---

## 2. Phase 1: 룰 기반 탐지 (31개, 구현 완료)

이 절의 31개는 `L1~L4` 전표 행 단위 구현 룰 기준이다. 사용자 큐와 우선순위 해석은
[PHASE1_RULE_RELATIONSHIP_MAP.md](PHASE1_RULE_RELATIONSHIP_MAP.md)의 최신 관계도를 따른다.
따라서 `D01/D02` 같은 Variance macro-finding, `IC01~IC03` 관계사 대사 신호, `GR01/GR03`
그래프 신호는 31개 룰 수에는 넣지 않지만, Phase 1 결과 화면에서는 Account / Process Queue 또는
관계사·연결 구조 drill-down의 보조 finding으로 결합한다.

### 2.0 PHASE1 운영 기준

PHASE1은 **룰 기반 전수 필터**다. 개별 룰은 넓게 탐지하고, 사용자에게는 룰 결과표가 아니라 **감사 검토 큐 + 검토 이유 + 확인 절차**를 제공한다. 최신 관계도 기준은 [PHASE1_RULE_RELATIONSHIP_MAP.md](PHASE1_RULE_RELATIONSHIP_MAP.md)를 따른다.

#### 2.0.1 결과 표현 계층

PHASE1 결과는 아래 4층으로 만든다.

| 층 | 대상 | 역할 | 감사인에게 노출 |
|---|---|---|---|
| Rule Hit | `L1-05`, `L3-04` 등 | 원천 탐지 근거 | drill-down에서만 노출 |
| Evidence Type | `control_failure`, `timing_anomaly` 등 | 의미 축으로 정리 | 케이스 태그와 주요 근거 |
| Case Priority | `high`, `medium`, `low` | 먼저 볼 순서 | 큐 정렬 기준 |
| Auditor Insight | 검토 초점, 위험 설명, 권장 확인 절차 | 실제 감사 행동 유도 | 메인 설명 |

룰별 `severity`는 최종 사용자 등급이 아니라 `evidence_score`와 `evidence_strength`의 입력이다. 예를 들어 `L3-08 적요 결손/파손`은 단독 `Low`로 노출하지 않고, `기말 수기 고액 전표에 적요 결손/파손이 보조 신호로 결합됨`처럼 case-level 의미로 표현한다.

#### 2.0.2 출력 큐

PHASE1 결과 큐는 탐지 단위에 따라 두 갈래로 나눈다.

1. **Transaction Queue**
   - L1~L4의 전표 행 단위 룰을 Theme Queue와 Case Group으로 묶는다.
   - 감사인이 실제 전표를 열어 승인·계정·금액·시점 맥락을 확인하는 기본 검토 큐다.
2. **Account / Process Queue**
   - Benford, D01, D02처럼 계정·월·프로세스 단위에서 의미가 생기는 macro-finding을 보여준다.
   - 이상 계정/월을 클릭하면 해당 모집단 안에서 L1~L4 룰이 함께 걸린 전표를 drill-down으로 연결한다.

#### 2.0.3 레이어와 Evidence Type

| Evidence Type | 포함 룰 | 기본 Primary Theme |
|---|---|---|
| `data_integrity_failure` | L1-01, L1-02, L1-08 | 데이터 정합성 오류 |
| `control_failure` | L1-04, L1-05, L1-06, L1-07, L1-09, L3-02 | 승인·권한 통제 검토 |
| `duplicate_or_outflow` | L2-01, L2-02, L2-03, L2-05 | 지급·중복 거래 검토 |
| `timing_anomaly` | L3-04, L3-05, L3-06, L3-07, L3-08, L3-11, L4-05 | 결산·시점 검토 |
| `logic_mismatch` | L1-03, L2-04, L3-01, L3-09, L3-10, L4-04 | 계정 사용 논리 검토 |
| `statistical_outlier` | L4-01, L4-02, L4-03, L4-06 | 수익·금액·통계 예외 |
| `intercompany_structure` | L3-03, IC01, IC02, IC03 | 관계사·연결 거래 검토 |

`IC01~IC03`은 31개 L1~L4 룰 수에 포함하지 않는 관계사 보조 finding이다. `GR01/GR03`은 Phase 3 그래프 신호지만 `L3-03` 케이스와 결합될 때 관계사·연결 구조 이상 우선순위를 높이는 보조 증거로 사용한다.

구현상 `L2-03a~L2-03d`가 존재하더라도 외부 기준은 `L2-03 중복 전표` 하나로 본다. 세부 rule id는 정확 중복, 유사 중복, 분할 후보, 시차 중복을 구분하기 위한 내부 reason code이며 모두 `duplicate_or_outflow`에 속한다.

L2와 L3는 신호 성격으로 구분한다.

| 축 | L2 (강한 부정 정황) | L3 (검토 필요 이상징후) |
|----|-------------------|--------------------|
| 신호 성격 | 도메인 특화 패턴, 통제 우회, 중복·자금 유출 | 시간·텍스트·운영 맥락 이상 |
| 대표 룰 | L2-01, L2-02, L2-03, L2-05 | L3-04, L3-06, L3-08 |
| 해석 | 부정 시나리오 1순위 검토 | 정상 업무 변동 가능성까지 포함한 검토 후보 |

#### 2.0.4 룰별 표현 Metadata

룰마다 화면 문구를 직접 쓰지 않고, 아래 metadata로 표준화한다.

```yaml
L1-05:
  evidence_type: control_failure
  evidence_strength: strong
  focus: approval_control_bypass
  action:
    - 작성자와 승인자 동일 여부 확인
    - 승인권한 정책 확인

L3-08:
  evidence_type: timing_anomaly
  evidence_strength: weak
  focus: missing_or_corrupted_description
  action:
    - 적요 필드가 원천에서 누락되었는지 또는 깨져 들어왔는지 확인

L4-03:
  evidence_type: statistical_outlier
  evidence_strength: medium
  focus: high_amount
  action:
    - 금액 산정 근거 확인
    - 수행중요성 대비 영향 확인
```

Case builder는 hit된 룰의 `evidence_type`, `evidence_strength`, `focus`, `action`을 모아 중복을 제거하고, theme별 우선순위에 따라 `primary_theme`, `secondary_tags`, `risk_narrative`, `recommended_audit_actions`를 만든다.

#### 2.0.5 Case Group 기준

Theme별 case key는 전역 공통 키를 쓰지 않고 다르게 둔다.

| Primary Theme | 기본 Case Key |
|---|---|
| 데이터 정합성 오류 | `회사 / 전표유형 / 적재배치` |
| 승인·권한 통제 검토 | `사용자 / 프로세스 / 월` |
| 지급·중복 거래 검토 | `거래처 / 금액밴드 / 근접기간` |
| 결산·시점 검토 | `사용자 / 계정군 / 월말 윈도우` |
| 계정 사용 논리 검토 | `계정군 / 문서유형 / 월` |
| 수익·금액·통계 예외 | `프로세스 / 계정군 / 월` |
| 관계사·연결 거래 검토 | `회사쌍 / 거래상대 / 월` |

주요 스키마 매핑은 `사용자=created_by`, `프로세스=business_process`, `월=posting_date YYYY-MM`, `거래처=auxiliary_account_number/vendor_name/customer_name`, `계정군=gl_account prefix/account_family`, `회사쌍=company_code + trading_partner`를 사용한다.

#### 2.0.6 점수 기준

점수는 두 층으로 나눈다.

1. **Row-level anomaly score**
   - 전표 행 단위 내부 점수다.
   - `score_aggregator` 호환, 위험 등급 분류, 개발자 검증에 사용한다.
   - 기본 가중치: `layer_a 0.15 + layer_b 0.45 + layer_c 0.25 + benford 0.15`
2. **Case priority score**
   - 사용자 큐 정렬 기준이다.
   - 기본식: `0.35*control_score + 0.30*amount_score + 0.20*logic_score + 0.15*behavior_score`
   - band 기준: `high >= 0.75`, `medium >= 0.45`, 그 외 `low`

보정 신호:

| 보정값 | 반영 기준 |
|---|---|
| `topside_bonus` | 기말·승인 우회·비정상 계정 조합·고액·적요 결손/파손 결합 |
| `batch_combo_bonus` | L4-06 배치 신호에 2~3개 이상 독립 evidence 축 결합 |
| `weak_evidence_bonus` | round number, weak description, rare account 같은 약한 증거가 강한 룰과 결합 |

`repeat_score`는 기본 가중합에 직접 더하지 않고 band 상향과 동점 정렬에 사용한다. 같은 evidence type은 case당 최대 `1.0`까지만 반영하고, 같은 룰의 반복 발생은 `sqrt` 또는 `log` 스케일로 완화한다.

#### 2.0.7 최종 Auditor Insight 출력

최종 사용자 표현은 케이스마다 아래 4개 필드로 표준화한다.

```json
{
  "priority_band": "high",
  "review_focus": [
    "approval_control_bypass",
    "period_end_manual_adjustment",
    "high_amount"
  ],
  "risk_narrative": "기말 수기전표에서 자기승인과 고액 전표가 함께 나타났습니다. 승인 통제 적용과 금액 산정 근거를 우선 확인해야 합니다.",
  "recommended_audit_actions": [
    "작성자와 승인자 동일 여부 확인",
    "승인권한 및 승인일 로그 확인",
    "전표 금액 산정 근거와 증빙 대사",
    "결산조정 승인 문서 확인"
  ]
}
```

내부 추적과 drill-down을 위해 `primary_theme`, `secondary_tags`, `priority_score`, `source_rule_ids`, `rule_evidence_summary`, `raw_rule_hits`를 함께 저장한다. `representative_explanation`은 기존 export/화면 호환을 위한 legacy alias로 두고, 신규 화면과 리포트는 `risk_narrative`를 우선 사용한다.

#### 2.0.8 노출 기준

- 기본 화면: `priority_band`, `review_focus`, `risk_narrative`, `recommended_audit_actions`
- 케이스 목록: `case_priority` 기준 상위 N개 및 Theme별 상위 케이스
- Drill-down: 전표 목록, 증거 태그, `rule_evidence_summary`, raw rule hit
- 개발자/검증 모드: 원천 룰 출력, row-level score, detector detail

### 2.1 L1: 확정 오류/명시 위반 (9개)

전표테스트의 전제조건. 이 검증을 통과해야 이후 탐지가 의미있음.

#### L1-01 — 차대변 균형 (UnbalancedEntry) ✅

- **심각도**: 5
- **근거**: 240§32 복식부기 원칙. FSS 횡령은폐 수법(차대 불일치)
- **탐지 로직**: `sum(debit) ≠ sum(credit)` per document_id. 허용 오차 1.0 (float 안전)
- **구현**: `integrity_layer.py` → `_a01_unbalanced_entry()`
  - document_id별 groupby → diff 계산
  - NaN document_id는 개별 더미 키로 처리
- **필요 피처**: `debit_amount`, `credit_amount`, `document_id`

#### L1-02 — 필수필드 누락 (MissingField) ✅

- **심각도**: 2
- **근거**: 240-A45(d) 계정번호 없이 입력. K-SOX 전표기록 통제
- **탐지 로직**: 9개 필수 컬럼 NULL 검사
  - 필수: document_id, company_code, fiscal_year, fiscal_period, posting_date, document_date, document_type, gl_account, (debit_amount OR credit_amount)
- **구현**: `integrity_layer.py` → `_a02_missing_required()`
- **필요 피처**: `document_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_date`, `document_date`, `document_type`, `gl_account`, `debit_amount`, `credit_amount`
- **DataSynth 상태**: MCAR 2% 주입 추가됨, E2E 재검증 필요

#### L1-03 — 무효 계정 (InvalidAccount) ✅

- **심각도**: 3
- **근거**: 240-A45(a) 비경상·저사용 계정 + 315호 비정상계정. FSS 가공전표(미사용계정 악용)
- **탐지 로직**: `gl_account NOT IN chart_of_accounts`
  - CoA(계정과목표) 미제공 시 스킵
- **구현**: `integrity_layer.py` → `_a03_invalid_account()`
- **필요 피처**: `gl_account`

#### L1-04 — 승인한도 초과 (ExceededApprovalLimit) ✅

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

#### L1-05 — 자기 승인 (SelfApproval) ✅

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
    - 현재 `1,000,000,000`원은 임시 기본값이며, 실제 감사 착수 후 engagement별 수행중요성 금액으로 반드시 오버라이드한다.
  - **주말 또는 심야에 처리된 자기승인**
    - 결산조정이라도 주말, 공휴일, 심야 시간대에 자기승인이 발생하면 통제 회피 가능성이 커지므로 바로 즉시 위반으로 올린다.
    - 구현상 `is_weekend`, `is_holiday`, `is_after_hours`, `time_zone_category`, `posting_time` 중 사용 가능한 시간 신호를 함께 본다.
  - **민감한 고위험 계정을 건드린 자기승인**
    - 현금성 자산, 가지급금, 가수금처럼 자기승인이 특히 위험한 계정은 결산 프로세스 안에 있더라도 즉시 위반으로 본다.
    - 기본 예시는 `1190(가지급금)`, `2190(가수금)`, 그리고 현금/예금 계열로 자주 쓰이는 `111`, `112`, `113` 접두사다.
    - 계정체계는 회사마다 다르므로 실제 고객사 CoA에 맞게 수정한다.
- **어디서 수정하는가**
  - 시스템 자동처리 예외는 [config/audit_rules.yaml](../config/audit_rules.yaml)의 `patterns.self_approval_allow`에서 수정한다.
  - `즉시 위반`과 `검토 필요` 기본 구분은 같은 파일의 `patterns.self_approval_review`에서 수정한다.
  - 검토 대상을 다시 즉시 위반으로 승격시키는 조건은 `patterns.self_approval_immediate_override`에서 수정한다.
  - 여기서 수행중요성 금액(`materiality_amount`), 수기 소스(`manual_sources`), 고위험 계정(`high_risk_accounts`), 고위험 계정 접두사(`high_risk_account_prefixes`)를 바꿀 수 있다.
  - 회사별로 다르게 운영하려면 `data/companies/{company_id}/audit_rules.yaml`에서 같은 키를 오버라이드하면 된다.
- **구현**: `fraud_rules_access.py` → `b06_self_approval()`
- **필요 피처**: `created_by`, `approved_by`, `source`

#### L1-06 — 직무분리 위반 (SegregationOfDutiesViolation) ✅

- **심각도**: 4
- **근거**: K-SOX 직무분리. FSS 오스템: 동일인 전프로세스 수행
- **탐지 로직**: 하이브리드 3단계 SoD
  1. **Toxic Pair 즉시 탐지**: `sod_toxic_pairs` (audit_rules.yaml)에 정의된 프로세스 쌍
  2. **In-process conflict**: `sod_conflict_type` 컬럼 기반 충돌 검출
  3. **Role-based 프로세스 수 제한**: junior=1, senior=3 (역할별 한도)
- **결과 해석 방식**
  - **Candidate**: 사람 기준으로 SoD 구조 신호가 보이면 우선 후보로 계산한다. 여기에는 configured toxic pair, `sod_conflict_type`, 역할 과다 겸직, IT super-user 거래 개입 가능성이 모두 포함된다.
  - **즉시 위반**: `TRE + P2P`, `TRE + O2C`, `TRE + H2R`, `sod_conflict_type` 직접 충돌, IT super-user의 금액 전표 개입, 그리고 review 후보가 `L1-05/L1-07` 성격의 강한 보강 신호와 겹치는 경우다.
  - **검토 필요**: `R2R + TRE`, `R2R + P2P`, `R2R + O2C`, 역할 과다 겸직처럼 구조상 위험하지만 추가 증거 확인이 필요한 경우다.
- **운영 예외와 보완 통제**
  - **사람(Human) 전제 필터**: L1-06은 사람의 권한 남용을 보는 룰이므로 `automated_system` persona, `automated/interface/system/batch` source, `BATCH/SYSTEM/AUTO/IF_/SVC_`류 시스템 계정명은 기본적으로 제외한다.
  - **중요성 금액 적용 범위**: `검토 필요` 범주는 `exceeds_threshold == True`일 때만 유지한다. 즉시 위반은 금액과 무관하게 유지한다.
  - **기본 중요성 기준**: 별도 고객사 override가 없으면 `exceeds_threshold`는 승인한도 피처를 따르며, 기본 최소 승인한도는 `10,000,000원`이다. 승인자별 한도가 있으면 그 한도 초과 여부를 우선 사용한다.
  - **직급 기반 보완 통제 인정**: `controller`, `manager`는 업무 특성상 `R2R` 관련 review를 기본 면제한다. 다만 `TRE`가 얽힌 강한 충돌이나 `sod_conflict_type` 직접 충돌은 계속 즉시 위반으로 본다.
  - **IT Super-user 예외 처리**: IT 관리자 계정은 일반 SoD review에서 넓게 잡지 않고, 실제 금액 전표를 `TRE/P2P/O2C/H2R`에서 생성한 경우에만 고위험 즉시 위반으로 승격한다.
- **보강 신호**
  - `L1-05 SelfApproval`: `created_by == approved_by`
  - `L1-07 SkippedApproval`: `exceeds_threshold == True` 이면서 승인 흔적 없음
  - `L1-05`, `L1-07`은 review SoD를 즉시 위반으로 승격할 수 있다.
  - 수기전표, 승인일 누락, 고위험 계정 사용은 각각 `L3-02`, `L1-09`, `L3-10`에서 별도 표시한다.
  - SoD와 직접 상관없는 다른 Phase 1 룰이 많이 걸렸다는 이유만으로 자동 승격하지는 않는다.
- **구현**: `fraud_rules_access.py` → `b07_segregation_of_duties()`
- **필요 피처**: `created_by`, `business_process`
- **DataSynth**: 1,365명 규모 (마스터 1,422), SOD 위반률 3.32% (10,595건, 2026-04-14 실측)

#### L1-07 — 승인 생략 (SkippedApproval) ✅

- **심각도**: 4
- **근거**: K-SOX 승인절차(외감법§8②). FSS 오스템: 한도초과+승인없음 = §8② 직접 위반
- **탐지 로직**: 승인한도 초과 + 비자동(source != 'automated') + 승인 없음
- **판정 결과 구분**
  - **즉시위반**: 승인 한도 초과 + `source in {'manual', 'adjustment'}` + `approved_by` 없음
    - `approval_date`도 없으면 승인 흔적이 전혀 없는 것으로 보고 즉시위반 확신을 더 높인다.
    - 해석: 사람이 직접 넣은 고액 전표인데 승인 흔적이 없어, 승인 생략으로 바로 볼 근거가 충분한 경우.
  - **검토필요**: 승인 한도 초과 + `source != 'automated'` + `approved_by` 없음이지만 즉시위반 조건까지는 못 미치는 경우
    - 예: `recurring` 등 반복/배치 성격 source, `approved_by`는 없지만 `approval_date`는 있는 경우, source 의미가 애매한 경우
    - 해석: 승인 누락 가능성은 높지만 시스템 처리인지 실제 생략인지 추가 확인이 필요한 경우.
- **운영 원칙**
  - L1-07 룰 자체는 하나로 유지하되, 결과 표시는 `즉시위반`과 `검토필요`로 나눠 확실한 승인 생략과 추가 확인이 필요한 건을 구분한다.
- **구현**: `fraud_rules_access.py` → `b09_skipped_approval()`
- **필요 피처**: 금액, `source`, `created_by`, `approved_by`

#### L1-08 — 기간 불일치 (WrongPeriod) ✅

- **심각도**: 4
- **근거**: 240§32(b) 기간귀속 적정성
- **현재 코드 기준 탐지 로직**
  - 최종 룰은 `fiscal_period_mismatch == True`일 때만 `WrongPeriod`로 탐지한다.
  - 이 플래그는 단순히 `month(posting_date)`와 바로 비교하지 않고, 회사 회계연도 시작월 `fiscal_year_start`를 반영해 기대 기수를 먼저 계산한 뒤 비교한다.
  - 계산식은 `expected_period = (posting_month - fiscal_year_start) % 12 + 1` 이다.
  - 즉 표준 회계연도(`fiscal_year_start=1`)에서는 사실상 `fiscal_period ≠ month(posting_date)`와 같고, 4월 시작 회계연도처럼 비표준 회계연도에서는 4월=기수1, 5월=기수2, ..., 3월=기수12로 본다.
- **사람이 이해할 수 있는 판정 기준**
  - 전기일이 속한 달을 회사의 회계기간 체계로 환산했을 때, 그 전표에 적힌 `fiscal_period`와 다르면 기간 불일치다.
  - 예: `fiscal_year_start=1`에서 `posting_date=2025-01-15`, `fiscal_period=5`이면 불일치다.
  - 예: `fiscal_year_start=4`에서 `posting_date=2025-04-15`, `fiscal_period=1`이면 정상이다.
- **현재 코드가 실제로 잡는 것**
  - 잘못된 회계기간 귀속, 월경 전표 처리 오류, 회계연도 시작월 설정과 맞지 않는 period 기입을 잡는다.
  - 반대로 `posting_date` 또는 `fiscal_period`가 비어 있어 비교 자체가 불가능한 건은 `pd.NA`로 두고, 최종 룰에서는 탐지하지 않는다. 즉 "비교 불가"와 "불일치"를 구분한다.
- **예외 가능성과 현재 한계**
  - 실무에서는 결산조정 전표, 특수기수(`13~16`), reopen period, closing entry처럼 `posting_date`의 일반 월과 다른 period를 의도적으로 쓰는 경우가 있다.
  - 현재 Phase 1 구현은 이런 예외를 별도 컬럼으로 받지 않으므로, 결산/특수기수 상황까지 자동 면제하지는 않는다.
  - 따라서 이 룰은 현재 기준으로 "기본 기간귀속 이상 신호"로 해석하는 것이 맞고, 결산조정 여부는 후속 검토에서 확인해야 한다.
- **운영 원칙**
  - Phase 1에서는 룰을 단순하고 설명 가능하게 유지하기 위해 기본 불일치 신호만 잡는다.
  - 결산/특수기수 예외는 데이터에 `special_period`, `closing_entry`, `adjustment_type`, `posting_period_status` 같은 맥락 컬럼이 확보되면 후속 단계에서 분기하는 것이 맞다.
- **구현**: `anomaly_rules_simple.py` → `c05_fiscal_period_mismatch()`
- **피처 생성**: `time_features.py` → `add_fiscal_period_mismatch()`
- **필요 피처**: `fiscal_period`, `posting_date`
- **DataSynth 계약**: `v36_candidate`부터 결산/특수기수 negative control sidecar를 별도로 관리한다.

#### L1-09 — 승인일 누락 (ApprovalDateMissing) ✅

- **심각도**: 3
- **근거**: 승인자가 기록되어 있는데 승인일이 없으면 승인 추적성이 훼손된다.
- **탐지 로직**: `approved_by`가 있고 `approval_date`가 비어 있는 경우
- **구현**: `fraud_rules_access.py` → `b12_missing_approval_date()`
- **필요 피처**: `approved_by`, `approval_date`
- **DataSynth 상태**: `ApprovalDateMissing` 라벨과 sidecar를 관리한다.

---

### 2.2 L2: 강한 부정 정황 (5개)

#### L2-01 — 승인한도 직하 (JustBelowThreshold) ✅

- **심각도**: 3
- **근거**: 240-A45(e) 단수/끝자리, K-SOX 승인체계
- **의미**: 승인 대상 금액이 결재권자의 승인 한도에 근접해 있을 때, 우연한 분포라기보다 승인 기준을 의식해 금액이 맞춰졌을 가능성을 살펴보는 룰이다. 이 룰 하나만으로 우회라고 단정하지 않고, 승인 정책과 업무 맥락을 함께 본다.
- **판정 방식**
  - 같은 `document_id`의 차변 금액 합계로 전표 총액을 계산한다.
  - 전표의 `approved_by`를 직원 마스터(`employees.json`)와 연결해 해당 승인자의 `approval_limit`를 조회한다.
  - 전표 총액이 그 승인자의 한도에 충분히 가깝지만 아직 넘지 않은 경우, 즉 `approval_limit × near_threshold_ratio <= 전표 총액 < approval_limit` 이면 `JustBelowThreshold`로 본다.
  - 기본 `near_threshold_ratio`는 `0.90`이다. 실무 해석으로는 "승인 한도의 90% 이상 100% 미만 구간"이다.
- **Fallback 원칙**
  - fallback은 사용하지 않는다.
  - `approved_by`가 없거나 직원 마스터 조인에 실패해 실제 `approval_limit`를 알 수 없는 행은 `L2-01`로 판정하지 않는다.
  - 이런 행은 부정 탐지 결과가 아니라 "승인한도 검증 불가"라는 커버리지/데이터 품질 이슈로 별도 관리한다.
- **한 줄 규칙**: `approval_limit(approved_by) × 0.9 <= SUM(debit_amount) BY document_id < approval_limit(approved_by)`
- **구현**
  - 피처 생성: `src/feature/amount_features.py` → `add_is_near_threshold()`
  - 룰 적용: `src/detection/fraud_rules_feature.py` → `b02_near_threshold()`
- **필요 컬럼**: `document_id`, `debit_amount`, `approved_by`, `approval_limit`(직원 마스터), `is_near_threshold` (파생)
- **DataSynth 상태**: `v24_candidate`에서 `approved_by.approval_limit` 기준 라벨로 보정했다.

#### L2-02 — 중복 지급 (DuplicatePayment) ✅

- **심각도**: 3
- **근거**: 240§32 적정성. FSS 횡령은폐: 동일건 이중지급
- **한 줄 설명**: 같은 매입처에 같은 돈을 또 보냈는지 찾는 룰
- **현재 성격**: PHASE1 recall 우선 스크리닝 룰이다. 확정 부정 판정이 아니라 "검토해야 할 지급쌍"을 올린다.
- **PHASE1 탐지 순서**
  1. `business_process == 'P2P'` 이고, `document_type == 'KZ'` 인 지급성 전표만 본다.
  2. 거래처 키는 `auxiliary_account_number`를 우선 사용하고, 없으면 `trading_partner`, `vendor_name` 등 대체 컬럼으로 보완한다.
  3. 전표 라인 단위가 아니라 `document_id` 단위로 요약한다. 같은 전표 안의 차변/대변 라인은 중복 지급으로 보지 않는다.
  4. `reference`가 있으면 강한 신호로 본다.
     - 같은 회사/거래처 + 정규화한 `reference` + 거의 같은 금액 + 다른 `document_id`
     - 금액 허용오차는 `min(금액의 2%, 100,000원)`이다. 최소 허용오차는 1원이다.
     - 이 경로는 reference가 같은 청구/증빙을 다시 지급한 가능성을 잡기 위한 것이다.
  5. `reference`가 없으면 보수적으로 fallback 한다.
     - 같은 회사/거래처 + 같은 금액 + 45일 이내 재지급이면 후보로 올린다.
     - blank-reference fallback에는 2% 금액 허용오차를 적용하지 않는다.
  6. 단, 같은 거래처/같은 금액이 월 단위로 규칙적으로 3번 이상 반복되면 정기성 지급 가능성이 높다고 보고 fallback 과탐을 줄인다.
- **해석 기준**
  - `reference` 일치 케이스는 fallback 케이스보다 강한 중복 지급 신호다.
  - `reference`가 비어 있는 fallback 케이스는 근거가 약하므로 같은 금액 exact match만 후보로 올린다.
  - 따라서 결과 화면에서는 "중복 확정"이 아니라 "중복 지급 의심 후보"로 노출한다.
- **구현**: `fraud_rules_groupby.py` → `b04_duplicate_payment()`
- **필요 피처**: `document_id`, `business_process`, `document_type`, 거래처 식별자(`auxiliary_account_number` 우선, 없으면 거래처 대체 컬럼), `reference`, 금액, `posting_date`
- **DataSynth 상태**: `v23`에서 `P2P + KZ` 지급쌍 기준 라벨과 negative control을 관리한다.

#### L2-03 — 중복 전표 (DuplicateEntry) ✅

- **심각도**: 3
- **근거**: 240§32, FSS 가공전표: 동일 전표 반복 = 가공
- **해석**
  - 실무에서 "중복 전표"는 같은 행의 단순 중복뿐 아니라, 같은 거래의 재입력, 날짜·적요·금액을 조금 바꾼 재기표, 분할 입력 가능성까지 포함한다.
  - 따라서 L2-03은 확정 판정이 아니라 중복 가능성이 높은 전표 후보를 우선 추출하는 룰이다.
- **현재 구현**
  - `fraud_rules_groupby.py` → `b05_duplicate_entry()`
  - PHASE1의 `L2-03`은 exact-only가 아니며, 아래 reason code를 사용해 행 단위 confidence를 계산한다.
    - `exact_duplicate`: 같은 `gl_account + amount + posting_date`
    - `reference_duplicate`: 같은 거래처, 같은 `reference`, 유사 금액, 서로 다른 `document_id`
    - `near_duplicate`: 같은 거래처 또는 계정군에서 금액·날짜·적요가 가까운 후보
    - `split_duplicate`: 짧은 기간 내 여러 건의 합이 원래 금액과 가까운 분할 후보
  - 각 행은 가장 강한 신호 1개를 primary `reason_code`로 갖고, 함께 걸린 신호는 `matched_reason_codes`로 남긴다.
  - 최종 confidence는 행 단위로 계산되며 `high / medium / low` band로도 구분한다.
- **운영 원칙**
  - 외부 노출 라벨은 계속 `L2-03 중복 전표` 하나로 유지한다.
  - UI, export, review queue에는 `reason_code`, `confidence`, `matched_reason_codes`, 핵심 근거 필드(`reference`, 거래처, 금액, 날짜, 적요)를 함께 제공한다.
  - 정상 반복 전표, 내부거래, 정산성 전표는 탐지 제거보다 confidence 조정 또는 review queue 분리로 처리한다.
  - `P2P/KZ` 지급성 전표가 함께 걸리면 `L2-02 duplicate payment`와 병합 설명을 제공한다.
- **DataSynth 상태**
  - `v26_candidate`에서 `DuplicateEntry` / `ExactDuplicateAmount` 라벨을 실제 복제 결과 문서(`duplicate_document_id`) 기준으로 보정했다.
  - 현재 기준 recall은 확보했지만, unrelated false positive가 남아 있어 confidence와 review queue 운영으로 좁혀야 한다.
- **필요 피처**
  - 최소: `gl_account`, `debit_amount`, `credit_amount`, `posting_date`
  - 실무형 보강: `document_id`, `reference`, 거래처 식별자, `line_text`

#### L2-04 — 비용 자산화 (ExpenseCapitalization) ✅

- **심각도**: 4
- **근거**: 240§32, FSS 분식회계: 개발비 과대자산화
- **한 줄 설명**
  - 비용으로 나가야 할 금액이 자산으로 넘어간 것처럼 보이는 전표를 찾는 룰이다.
- **현재 판정 기준**
  - 회사 설정(`audit_rules.yaml`)의 `자산 계정 prefix`와 `비용 계정 prefix`를 사용한다.
  - 같은 `document_id` 안에서 `자산 차변`과 `비용 대변`이 금액상 거의 맞으면 탐지한다.
  - 1:1 매칭이 안 되어도 자산 차변 합계와 비용 대변 합계가 거의 같으면 분할 전표로 보고 탐지한다.
  - 전표 전체가 아니라 실제로 매칭된 자산/비용 라인만 올린다.
- **우선순위 조정 로직**
  - `개발`, `구축`, `software`, `project`처럼 정상 자산화 맥락이 강하면 감점한다.
  - `수선`, `복리후생`, `지급수수료`, `office`, `repair`처럼 일반 비용성 적요가 보이면 가점한다.
  - `manual`, `adjustment` 같은 수기성 source와 `P2P`, `O2C`, `R2R`, `H2R` 같은 일반 운영 프로세스는 가점한다.
  - `AA`, `FA` 같은 자산 관련 문서유형은 감점한다.
- **출력 방식**
  - `0.75 이상`은 `즉시 검토(immediate)`, `0.45 이상`은 `검토 필요(review)`로 본다.
  - 따라서 같은 L2-04라도 전표 맥락에 따라 우선순위가 달라질 수 있다.
- **해석**
  - 이 룰은 `비용 자산화 확정`이 아니라 `비용 자산화 가능성이 높은 전표 후보`를 먼저 보여주는 룰이다.
  - 즉 확정 판정용이 아니라 우선 검토 큐용이다.
- **실무 해석 시 주의점**
  - 회사마다 CoA가 다르므로 prefix는 회사 기준으로 조정해야 한다.
  - 정상적인 자산 취득/자본적 지출도 비슷한 모양이 나올 수 있으므로 적요, 문서유형, 프로세스를 함께 봐야 한다.
  - 현재 감점/가점 키워드는 시작점일 뿐이고, 회사별 자산화 정책을 반영해 계속 튜닝해야 한다.
- **합성데이터 평가**: family 라벨 기준 recall은 높지만 subtype 단독 기준 precision은 낮아, `비용 자산화 family`를 넓게 잡는 우선검토 룰로 해석한다. 상세는 `tests/phase1_rulebase/test-results/l2-04-synth-2022-2024.md` 참조.
- **구현**: `fraud_rules_groupby.py` → `b11_expense_capitalization()`
- **필요 피처**: `document_id`, `gl_account`, `debit_amount`, `credit_amount`

#### L2-05 — 역분개 패턴 (ReversalEntry) ✅

- **심각도**: 4
- **근거**: 240§32(a)(ii) 기말 재분개 중점 검사, FSS 분식회계·횡령은폐
- **설계 원칙**
  - Phase 1에서는 `역분개 확정`이 아니라 `역분개/상계/재분류 후보`를 먼저 넓게 보여준다.
  - 다만 실제 결과 화면과 후속 우선순위에서는 `확실한 역분개 신호`와 `후보성 신호`를 분리해야 한다.
  - 즉, recall 우선은 유지하되 FP를 대량으로 만드는 정상 상계/정산/재분류는 최대한 줄인다.
- **탐지 로직**
  1. S0(강신호) ERP 구조 참조: `original_document_id`, `reversal_document_id`, `reference_document_id`, `reversal_reason` 등 원전표/역전표 연결 필드
  2. S2b(강신호) 단일 라인 차대변 스왑 서명: 한 라인의 방향 오류가 전표 불균형을 설명하는 경우
  3. S1(후보신호) 1:1 매칭: 동일 `gl_account` + 동일 금액 + 반대 방향(차↔대) + 짧은 시차. 구현은 line-level Python 전수 비교가 아니라 `document_id × gl_account` 집계 후 DuckDB self-join으로 후보쌍을 먼저 만들고, 그 후보에만 `created_by`, `reference`, `document_type`, 적요 유사성 등 문맥 점수를 Python 후처리로 계산한다.
  4. S2(후보신호) N:M 분할 역분개: `gl_account × created_by` 그룹, 짧은 윈도우 내 순액 ≈ 0. 단, 정상적인 단일 전표 내부 차대 균형을 피하기 위해 최소 2개 이상 `document_id`가 포함된 윈도우만 인정하고, 임시계정 정리/차입 상환/재분류처럼 FP가 많은 계정군은 별도 예외 또는 약한 신호로 처리한다.
  5. S3(보정신호) 정상/수정 구분: `auto + 월초(D≤5)` = 위험점수 감점, `manual` = 가중
  6. S4(보정신호) 적요 키워드: config/audit_rules.yaml `reversal_keywords` 18개
  7. S5(보정신호) 기말 부스트: 12/20~12/31 + 1/1~1/5 결산 전후 15일
- **판정 방향**
  - `S0` 또는 `S2b`가 있으면 `high-confidence reversal` 후보로 본다.
  - `S1`, `S2`는 단독으로는 `candidate reversal / clearing / reclass`에 가깝고, 문맥 키가 같이 맞을 때만 강하게 본다.
  - 즉 `금액 반전`만으로 바로 역분개라고 단정하지 않고, `금액 + 문맥`이 함께 맞을 때 우선순위를 높인다.
- **출력 해석 분리**
  - 내부 플래그는 계속 `L2-05` 하나로 유지한다. 즉 탐지 엔진 계약은 바꾸지 않는다.
  - 대신 row-level annotation에는 아래 해석 값을 함께 저장해서 UI, export, phase1 case builder가 같은 문장을 재사용하게 한다.
  1. `high-confidence reversal`
     - 조건: `S0` 또는 `S2b`
     - 의미: ERP 구조 참조가 있거나, 단일 라인 차대변 스왑으로 전표 불균형이 직접 설명되는 경우
  2. `candidate reversal / clearing / reclass`
     - 조건: `S1` 또는 `S2` 이고 `S0`, `S2b`는 없음
     - 의미: 금액 반전이나 순액 0 패턴은 있으나, 정상 상계/정산/재분류와 경계가 겹치는 경우
  - 따라서 화면과 리포트는 `L2-05`를 단순히 "역분개"라고만 쓰지 않고, 위 두 해석 중 하나로 풀어서 보여준다.
- **실무 해석 시 주의점**
  - `9990`, 차입금, 선수금, 자금이체성 계정, 임시계정, 재분류성 계정은 순액 0 패턴이 정상적으로 자주 나오므로 별도 관리가 필요하다.
  - DataSynth 기준 `ReversedAmount` TP는 현재 대부분 `S2b` 계열이라, `S1/S2`를 문맥 강화로 좁히는 것은 비교적 안전한 보정이다.
- **DataSynth 계약**: `ReversedAmount` 라벨은 실제 `journal_entries*.csv`에 존재하는 `document_id`만 가리켜야 한다.
- **ERP 구조 필드 우선 원칙**: 실제 ERP에서 별도 역분개 문서형이 많으면 `S0/S1` coverage가 중요하므로, 구조 필드가 있으면 최우선으로 활용한다.
- **구현**: `anomaly_rules_reversal.py` → `c11_reversal_entry()`
  - S1 후보 생성: DuckDB self-join
  - S1 후보 해석: Python 문맥 점수 후처리
- **필요 피처**: `gl_account`, `debit_amount`, `credit_amount`, `posting_date`, `document_id`
  - 보조: `created_by`, `source`, `line_text`, `header_text`, `cost_center`, `trading_partner`
- **성능**: S1 self-merge 세분화 키(cost_center/trading_partner)로 Cartesian 폭발 방지

---

### 2.3 L3: 검토 필요 이상징후 (11개)

#### L3-01 — 계정 분류 불일치 (MisclassifiedAccount) ✅

- **심각도**: 3
- **근거**: 240-A45(c) 비정상 거래 특성, 315호 업무프로세스 이해와 위험평가
- **의미**
  - 특정 업무 프로세스에서 일반적으로 쓰이지 않는 계정이 사용된 경우를 검토 대상으로 올리는 룰이다.
  - 예를 들어 지급 프로세스(P2P)인데 매출성 계정이 쓰이거나, 인사/급여 프로세스(H2R)에서 무관한 자산·매출 계정이 쓰이는 식의 계정-프로세스 불일치를 본다.
- **감사인이 실제로 넣는 값**
  - `process_disallowed_categories`: "이 프로세스에서 원래 잘 안 쓰는 계정 종류"
  - `process_denied_accounts`: "이 프로세스에서 특히 위험하다고 보는 계정번호"
  - `process_allowed_keywords`: "계정은 어색해 보여도 정상 예외로 자주 나오는 적요"
- **판정 방식**
  - `IntegrityDetector(layer_a)`에서 `L1-01`, `L1-02`, `L1-03` 다음에 실행된다.
  - `process_denied_accounts`가 설정된 프로세스는 exact `gl_account` denylist를 우선 적용한다. 이 값은 회사별 CoA 기준으로 유지보수하는 것이 기본 운영 모델이다.
  - `process_denied_accounts`가 없는 프로세스만 `account_category` 또는 `account_group`을 사용한 category fallback을 적용한다. 해당 컬럼이 없으면 `gl_account` prefix를 `config/audit_rules.yaml`의 `l3_01_misclassified_account.account_category_prefixes`로 분류한다.
  - category fallback은 최소한의 금지 조합만 유지한다. 기본값은 `O2C->expense`, `P2P->revenue`, `H2R->revenue`, `TRE->inventory`, `A2R->payroll`이다.
  - 선택 옵션으로 `header_text` 또는 `line_text`에 `process_allowed_keywords`가 있으면 정상 예외로 보고 `L3-01`을 완화한다. 다만 기본값은 비워 둔다.
  - `L1-03`과 역할이 겹치지 않도록 CoA가 제공된 경우 유효 계정만 검사한다. CoA에 없는 계정은 `L1-03`이 담당한다.
  - 기본값은 `strict_allowed_categories: false`라서 명시적 금지 조합만 잡는다. 회사별 CoA/업무프로세스가 정리된 경우 `strict_allowed_categories: true`로 허용목록 방식 검사를 켤 수 있다.
- **해석**
  - 이 룰은 `L1-03 무효 계정`과 다르다. L1-03은 존재하지 않거나 사용할 수 없는 계정이고, L3-01은 계정 자체는 유효하지만 업무 맥락이 어색한 경우다.
  - 실무에서는 "대분류 mismatch 단독"보다 "프로세스별 위험 계정번호"가 더 잘 작동한다. 따라서 기본 category 룰은 review seed로 두고, 고객사별 deny-account override로 정밀도를 올리는 구조가 권장된다.
  - 정상 예외 적요는 많이 넣으면 운영이 무너지고 recall도 떨어질 수 있다. 그래서 기본값은 비워 두고, 감사인이 반복 확인한 정상 예외 표현만 짧게 추가하는 것이 원칙이다.
  - `R2R`은 마감/재분류/조정 전표가 많아서 이 룰의 기본 프로세스 범위에 넣지 않는다. `R2R`의 MisclassifiedAccount 성격은 별도 룰 또는 NLP/ML 보조 신호로 다루는 편이 낫다.
- **구현 상태**
  - 구현: `src/detection/integrity_layer.py` → `_l301_misclassified_account()`
  - 설정: `config/audit_rules.yaml` → `l3_01_misclassified_account`
  - 파이프라인: 회사별 `audit_rules.yaml` override가 `AuditPipeline` → `IntegrityDetector`로 전달된다.
  - 평가 매핑: `src/metrics/rule_mapping.py`에서 `L3-01 → MisclassifiedAccount`, `layer_a`, `review_needed`로 유지한다.
- **합성데이터 평가**: `v29_candidate`에서 기본 룰을 `보수적 category + process_denied_accounts 우선` 구조로 조정했다. 상세는 `tests/phase1_rulebase/test-results/l3-01-synth-2022-2024.md` 참조.
- **Phase 1 이후 사용 원칙**
  - `L3-01`은 단독 판정기가 아니라 "계정-프로세스 맥락이 어색하다"는 review seed로 사용한다.
  - `L1 통제 위반`, `수기 전표`, `기말 집중`, `고액`, `희소 계정쌍` 같은 다른 신호와 결합될 때 case priority를 높인다.
  - 단독 hit는 자동 결론을 내리지 않고, case grouping과 drill-down에서 적요, 문서유형, 반대 계정, 승인 흐름을 함께 확인한다.
- **필요 피처**: `business_process`, `gl_account`
  - 선택: `account_category`, `account_group`

#### L3-02 — 수기 전표 (Manual Entry Population) ✅

- **심각도**: 4
- **근거**: 240-A45(b) 비인가자 입력, K-SOX 우회금지(외감법§8②). FSS 가공전표: 자동 프로세스 우회
- **탐지 로직**: `is_manual_je == True`. `is_manual_je`가 없으면 `source`가 `manual_source_codes`에 포함되는지 본다.
- **구현**: `fraud_rules_feature.py` → `b08_manual_override()`
- **필요 피처**: `is_manual_je` 또는 `source`
- **처리 방식**: 수기 전표 자체를 독립 검토 신호로 표시한다. 승인누락, 승인일 누락, 비정상 시간, 기말, 가계정/민감계정, 적요 결손/파손은 각각 별도 룰 또는 케이스 우선순위에서 다룬다.
- **DataSynth truth 원칙**: `L3-02`는 수기전표 전체 모집단 coverage로 평가하고, 일부 조작성 시나리오 라벨인 `ManualOverride`와는 분리한다.

#### L3-03 — 관계사 거래 검토 신호 (RelatedPartyTransactionSignal) ✅

- **심각도**: 4
- **근거**: ISA 550 §23 특수관계자 거래의 사업상 합리성 검토. Phase 1에서는 순환 구조를 단정하지 않고 관계사 계정 사용 전표를 검토 후보로 올린다.
- **탐지 로직**: IC GL prefix 매칭
  - `intercompany_identifiers: ['1150', '2050', '4500', '2700']`
  - 관계사 채권/채무/매출/미지급 등 고객사 CoA상 IC 전용 계정 사용 여부만 판단
  - 실제 A→B→C→A N-hop 순환 탐지는 **GR01(GraphDetector)** 에서 담당 (§4.4 참조)
- **구현**: `fraud_rules_access.py` → `b10_intercompany_review_signal()`
- **필요 피처**: `is_intercompany` (`gl_account` prefix에서 생성), 보강 설명용 `company_code`, `trading_partner`, `reference`
- **실무 해석**: 단독 부정 적발이 아니라 특수관계자 거래 모집단/샘플링 후보. 계약서, 상대방, 정상가격, 대사 여부를 후속 확인한다.
- **PHASE1 제약**: 이 룰 계열은 recall 우선 스크리닝이다. 과탐을 줄이기 위해 IC prefix, 금액 차이, 시차, 그래프 가격 비대칭 조건을 임의로 좁혀 미탐을 늘리지 않는다. 정밀도 보정은 case priority, Phase 2 ranking, 감사인 검토 단계에서 처리한다.
- **평가 기준**: `L3-03`은 관계사 거래 모집단 룰이므로 `intercompany_population_truth`로 평가하고, 실제 비정상 순환거래 라벨인 `CircularIntercompany`/`CircularTransaction`과 혼동하지 않는다.
- **DataSynth 계약**: `v37_candidate`부터 IC GL prefix 기준 `intercompany_population_truth` sidecar를 별도로 관리한다.
- **DataSynth 예외 라벨**: `v38_candidate`부터 IC01/IC02/IC03/GR01/GR03 검증용 소량 truth를 `labels/intercompany_exception_cases*.csv/json`에 둔다. 이 라벨은 detector 결과를 역으로 채운 것이 아니라 정상 IC pair 일부에 거래상대 불일치, 금액 차이, 전기일 차이, 순환 seed, 가격 비대칭을 작게 주입한 scenario truth다. 정상 대조군은 `labels/intercompany_normal_controls*.csv/json`에 별도로 둔다.
- **GR01 평가 계약**: `v39_candidate`부터 GR01 hit 전체는 `labels/graph_gr01_review_population*.csv/json`에 review population으로 저장한다. 확정 이상은 기존 `CircularTransaction`/`CircularIntercompany` 라벨과 `labels/graph_gr01_confirmed_anomalies*.csv/json`만 사용하고, 정상 순환 대조군은 `labels/graph_gr01_normal_cycle_controls*.csv/json`로 분리한다. 따라서 GR01 raw hit 전체를 anomaly precision 분모로 쓰지 않는다.
- **IC01/IC02/IC03 평가 계약**: `intercompany_exception_cases` 전체를 한꺼번에 정답으로 쓰지 않는다. IC01은 `UnmatchedIntercompany`, IC02는 `IntercompanyAmountMismatch`, IC03은 `IntercompanyTimingMismatch`만 각각 평가한다. `target_document_id`가 주입 대상이며, counterpart 문서는 룰 성격에 따라 같이 flag될 수 있는 보조 문서다.
- **IC01 실무 기준**: 고객/벤더 코드(`C-000123`, `V-000123`)가 IC 계정에 들어온 경우는 DataSynth 현실성 노이즈로 보고 미대사 예외에서 제외한다. IC01은 명시적 회사 상대방 코드가 존재하지만 실제 회사코드와 대사되지 않는 고확신 케이스를 우선 flag한다.
- **표시 기준**:
  - `L3-03`: 관계사 거래 모집단
  - `IC01`: 고확신 미대사 예외 후보
  - `IC02`: 금액 불일치 검토 후보
  - `IC03`: 시차 불일치 검토 후보
  - `GR01`: 순환 구조 검토 후보. 확정 이상 평가는 `graph_gr01_confirmed_anomalies` 기준
  - `GR03`: 이전가격/금액 비대칭 검토 후보. 단독 확정 부정으로 표시하지 않음
- **실무 우선순위**
  - `L3-03` 단독: 낮음. 관계사 계정 사용 전표이므로 검토 모집단에 포함한다.
  - `L3-03 + IC01/IC02/IC03`: 미대사, 금액 차이, 기간 차이를 확인해야 하므로 우선순위를 높인다.
  - `L3-03 + GR01/GR03`: N-hop 순환 구조 또는 가격 비대칭이 확인된 경우로 매우 높은 우선순위로 본다.
- **한계**: 정상 내부거래도 많이 포함될 수 있으며, 이 룰만으로 순환거래나 부정을 단정하지 않는다. 고객사 CoA에서 관계사 계정 prefix가 다르면 `patterns.intercompany.pairs`를 먼저 보정해야 한다.

#### L3-04 — 기말/기초 대규모 (RushedPeriodEnd) ✅

- **심각도**: 3
- **근거**: 240§32(a)(ii)+A44 기말검사 의무. FSS 결산수정 27건(29%)
- **탐지 로직**: 월말 전 5일 또는 월초 5일 + (`금액 > Q3` 또는 `수기 전표`)
- **구현**: `anomaly_rules_simple.py` → `c01_period_end_large()`
- **필요 피처**: `posting_date`, 금액, `is_period_end` (파생), `is_manual_je` (선택)
- **Phase 1 적용 방침**
  - 결산 일정은 회사별로 다르므로 감사인/사용자가 `period_end_margin_days`와 회계연도 기준을 engagement 시작 시 확정해야 한다. 기본값 5일은 제품 기본값일 뿐 회사 결산일을 대체하지 않는다.
  - 금액 기준은 계정그룹별 Q3를 우선 사용한다. 계정그룹 표본이 `c01_min_group_size`보다 작으면 전체 Q3로 fallback하여 소규모 그룹 과탐을 줄인다.
  - 매출, 재고, 충당금, 미수/미지급, 손상 등 결산 민감 계정은 L3-04 단독 플래그를 늘리기보다 케이스 우선순위와 설명 가중치에서 상향한다.
- **운영 전제**
  - L3-04는 탐지 제외 룰이 아니라 결산 검토 후보군이다. 따라서 플래그는 유지하고 화면/리포트 우선순위만 조정한다.
  - L3-04 단독은 low priority로 두고, `민감 계정`, `고액`, `주말/심야`, `전기일-문서일 장기 괴리`, `승인/중복/역분개`, `적요 부실` 신호와 결합될 때 medium/high로 올린다.
  - 자동 반복 마감전표는 사용자 whitelist를 기본 전제로 두지 않는다. 대신 같은 `company + source + document_type + business_process + gl_account + 월말/월초 구간`이 여러 달 반복되고 금액 변동이 작으면 반복 패턴으로 보고 점수만 downgrade한다. hard exclude는 하지 않는다.

#### L3-05 — 주말/공휴일 전기 (WeekendPosting) ✅

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. FSS 비정상시점 4건
- **탐지 로직**: `weekday() >= 5` 또는 한국 공휴일 플래그
- **구현**: `anomaly_rules_simple.py` → `c02_weekend_entry()`
- **필요 피처**: `posting_date`, `is_weekend` (파생), `is_holiday` (파생)
- **실무 해석**: 단독 부정 신호가 아니라 비근무일 처리 여부를 넓게 잡는 캘린더 기반 보조 신호다. 24/7 운영, 월마감, 자동/반복 전기, 해외·공장·물류 프로세스에서는 정상 주말 전표가 많을 수 있으므로 다른 위험 신호와 결합될 때 우선순위를 높인다.
- **운영 전제**: `is_holiday`는 한국 법정공휴일과 `custom_holidays`를 함께 본다. 감사인은 해당 회사의 창립기념일, 전사 휴무일, 공장 셧다운, 노사 합의 휴일 등 회사별 휴일을 `custom_holidays`에 입력해야 회사 실제 근무 캘린더 기준으로 탐지된다.
- **DataSynth 계약**: `v36_candidate`부터 정상 주말 처리 배경을 `normal_weekend_context` sidecar로 분리 관리한다.
- **DataSynth 평가 계약**: `v41_candidate`부터 L3-05 hit 전체(`is_weekend OR is_holiday`)는 `labels/weekend_review_population*.csv/json`에 review population으로 저장한다. 확정 이상은 기존 `WeekendPosting` 라벨과 `labels/weekend_confirmed_anomalies*.csv/json`만 사용하고, 정상 비영업일 운영 대조군은 `labels/normal_weekend_context*.csv/json`로 분리한다. 따라서 L3-05 raw hit 전체를 anomaly precision 분모로 쓰지 않는다.
- **v41 실측 결과**: `data/journal/primary/datasynth_v41_candidate` 2022~2024 기준 L3-05 raw hit는 24,307건이고, `weekend_review_population`도 24,307건으로 1:1 일치한다. 확정 `WeekendPosting` 라벨은 29건이며 모두 탐지되어 FN=0, recall=100%다. `raw hit - confirmed labels = 24,278건`은 확정 이상 오탐이 아니라 리뷰 모집단이다.
- **과탐 해석 기준**: L3-05는 넓은 캘린더 스크리닝 룰이다. `WeekendPosting` 확정 라벨만 정답으로 두면 precision이 낮아 보이지만, 이는 룰 목적과 다른 평가다. 운영 평가는 (1) 확정 라벨 recall, (2) `weekend_review_population` coverage, (3) 정상 대조군(`normal_weekend_context`)과의 분리 여부를 본다.
- **운영 사용 원칙**: L3-05 단독 hit는 low-priority review candidate로 두고, 수기 전표, 고액, 기말/기초, 승인 생략·자기승인, 중복/역분개, 적요 결손/파손, 특정 사용자 집중(L4-05)과 결합될 때 triage 우선순위를 올린다.

#### L3-06 — 심야 전기 (AfterHoursPosting) ✅

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. KLCA IT 체크리스트
- **탐지 로직**: `midnight_start`~`midnight_end` 심야 구간. 기본값은 22시~06시 (`midnight_start: 22`, `midnight_end: 6`)
- **구현**: `anomaly_rules_simple.py` → `c03_after_hours_entry()`
- **필요 피처**: `posting_date` (시간 포함), `is_after_hours` (파생)
- **운영 전제**: 심야 시작/종료 시각은 회사 근무제, 교대근무, 해외법인 시간대, 마감 운영 정책에 맞게 조정한다. 주말/공휴일 전기는 L3-05, 사용자별 overtime·심야 집중은 L4-05에서 별도로 다룬다.
- **실무 해석**: L3-06 단독은 심야 전표 모집단 태그에 가깝다. 야간 배치, 해외/공유서비스 운영, 24시간 교대근무, 월마감 인터페이스가 있는 회사에서는 정상 심야 전표가 많으므로, `수기 전표`, `고액`, `기말/기초`, `승인 생략`, `자기승인`, `적요 결손/파손`, `특정 사용자 집중`과 결합될 때 우선순위를 올린다.
- **DataSynth 계약**: `AfterHoursPosting`을 L3-06 truth로 사용하고, 정상 심야 배경과 date-only/timezone 한계는 별도 sidecar로 분리 관리한다.

#### L3-07 — 전기일-문서일 장기 괴리 (Posting-Document Date Gap) ✅

- **심각도**: 3
- **근거**: 240-A45(c) 기말+설명없음. FSS 횡령은폐
- **탐지 로직**: `abs(posting_date - document_date) > N일` (기본 30일, 임계값 초과)
  - `posting_date - document_date > N`: 문서일 대비 장기 지연 전기
  - `posting_date - document_date < -N`: 선전기성 날짜 괴리 또는 미래 증빙 성격
- **구현**: `anomaly_rules_simple.py` → `c04_backdated_entry()`
- **필요 피처**: `posting_date`, `document_date`, `days_backdated` (파생)
- **운영 해석**: PHASE1에서는 설명 가능한 1차 스크리닝 룰로 사용한다. 이 룰은 `BackdatedEntry`와 `LatePosting` 성격을 모두 포착하는 날짜 괴리 신호이며, 단독으로 부정이나 소급 입력을 확정하지 않는다. 실무에서 진짜 마감 후 소급 입력을 보려면 `entry_date`/`created_at`과 `posting_date`의 차이를 별도 룰로 보강해야 한다.
- **DataSynth 계약**: `v33/v34_candidate`에서 `LatePosting` 라벨 정합성과 정상 업무 지연 negative control을 분리 관리한다.

#### L3-08 — 적요 결손/파손 신호 (MissingOrCorruptedDescription) ✅

- **심각도**: 1
- **근거**: 240-A45(c) 설명없음, K-SOX§8①1호 기록방법
- **탐지 로직**: `line_text + header_text`를 합쳐 본 뒤, 설명이 사실상 없거나 문자열이 깨진 경우만 포착한다.
  - `missing`: 공백 또는 누락
  - `corrupted`: 특수문자만 있거나, 같은 문자가 반복되는 등 명백한 garbage 문자열
- **Phase 1 범위**: 의미상 설명이 충분한지까지 판단하지 않고, **기록이 비어 있거나 망가진 상태**만 좁게 본다.
- **구현**: `anomaly_rules_simple.py` → `c06_missing_or_corrupted_description()`
- **필요 피처**: `line_text`, `header_text`, `description_quality` (파생)
  - 운영 진단용 보조 피처: `description_line_missing`, `description_header_missing`, `description_both_missing`, `description_line_missing_header_present`, `description_is_missing_or_corrupted`
- **실무 해석**: 이 룰은 강한 부정 신호가 아니라 **기록통제 품질 저하 신호**다. 자동전표, 인터페이스 전표, 레거시 적재 데이터에서는 빈 적요가 나올 수 있으므로, 단독으로는 우선순위를 높게 두지 않는다.
- **Phase 1 운영 진단**: L3-08 룰 자체를 더 복잡하게 만들지 않고, 결손이 어디서 발생하는지 별도 coverage profile로 본다.
  - `line_text`와 `header_text`가 모두 비었는지
  - `line_text`는 비었지만 `header_text`가 있어 설명이 보완되는지
  - `source`, `business_process`, `document_type`별 결손/파손률이 특정 입력 경로에 집중되는지
  - 구현: `text_features.py` → `build_description_quality_profile()`
- **위험도가 높아지는 결합 신호**
  - `L3-02 수기 전표`: 사람이 직접 입력했는데 설명이 없음
  - `L3-04 기말/기초 대규모`: 결산 조정성 전표인데 설명이 없음
  - `L1-05 자기승인`, `L1-07 승인 생략`: 통제 우회와 기록 결손이 함께 나타남
  - `L2-05 역분개 패턴`: 수정·취소 성격 전표인데 설명이 없음
  - `L3-10 고위험 계정 사용`, `L3-09 가수금 장기체류`: 민감 계정을 건드리는데 설명이 없음
  - `L3-05 주말 전기`, `L3-06 심야 전기`: 비정상 시점 처리와 설명 결손이 함께 나타남
- **운영 방침**: `L3-08` 단독 hit는 low priority로 두고, 위 신호와 결합될 때 `case_priority`를 올린다.
- **추가하지 않는 것**: Phase 1에서는 키워드 기반 위험 적요 판단, 회사별 whitelist/blacklist 운영, 적요 의미 충분성 판단, 계정-적요 의미 정합성 판단을 하지 않는다. 이들은 Phase 3 NLP/LLM 영역으로 둔다.
- **한계**: 말은 길지만 실질 설명이 없는 적요, 회사 내부 은어, 계정/프로세스와 어울리지 않는 적요는 Phase 1에서 판단하지 않는다. 이런 의미 기반 평가는 Phase 3 NLP/LLM 계층에서 다룬다.
- **DataSynth 평가 계약**: `v43_candidate`부터 Phase 1 L3-08 truth는 `MissingOrCorruptedDescription`과 `labels/missing_corrupted_description_truth*.csv/json`만 사용한다. 기존 `VagueDescription`은 보존하되 `labels/vague_or_risky_description_truth*.csv/json`를 통해 Phase 3 NLP/LLM용 의미상 모호/위험 적요 truth로 분리한다. 따라서 `VagueDescription` 전체를 L3-08 precision/recall 분모로 쓰지 않는다.
- **DataSynth 경계 대조군**: `v44_candidate`부터 `labels/description_boundary_normal_controls*.csv/json`에 짧지만 정상인 적요, 정상 시스템 코드형 적요, `line_text`는 비었지만 `header_text`가 충분한 케이스, Phase 3용 의미상 vague 케이스를 정상 control로 둔다. v43의 100% 정렬은 계약 테스트이며 실무 precision/recall로 해석하지 않는다.
- **이번 코드 반영 사항**
  - `description_quality` 판정값을 `missing / corrupted / normal`로 정리하고, 과거 `poor`는 legacy alias로만 허용한다.
  - `has_risk_keyword`는 계속 생성하지만 L3-08 판정에는 사용하지 않는다.
  - `description_line_missing`, `description_header_missing`, `description_both_missing`, `description_line_missing_header_present`, `description_is_missing_or_corrupted`를 추가해 원천 필드 결손 위치를 운영 진단할 수 있게 했다.
  - `build_description_quality_profile()`로 `source`, `business_process`, `document_type`별 결손/파손률을 볼 수 있게 했다. 이 profile은 룰 hit를 늘리는 용도가 아니라 데이터 품질 원인 분석용이다.

#### L3-09 — 가수금 장기체류 (SuspenseAccountAbuse) ✅

- **심각도**: 3
- **근거**: 외감법§8①2호 오류통제. FSS 횡령은폐: 가수금을 통한 자금 유용
- **탐지 로직**:
  - 모집단: `is_suspense_account == True`
  - 미정리 상태: `amount_open > suspense_min_open_amount` 또는 `is_cleared == False` 또는 `settlement_status ∉ {settled, cleared, closed, resolved, matched}`
  - fallback: 위 정산 정보가 없을 때만 `settlement_date IS NULL`, `lettrage_date IS NULL`, `lettrage IS NULL/blank`를 보조 신호로 사용
  - 체류 기간: `posting_date`부터 정산일(`settlement_date` 또는 `lettrage_date`)까지, 정산일이 없으면 데이터셋 기준일(max `posting_date`)까지의 경과일수
  - 최종 판정: `is_suspense_account == True` 이고 `unresolved == True` 이며 `aging_days >= suspense_aging_days`
- **구현**: `anomaly_rules_simple.py` → `c10_suspense_account()`
- **필요 피처**: `is_suspense_account`, `posting_date`, 그리고 가능하면 `amount_open` 또는 `is_cleared` 또는 `settlement_status`/`settlement_date`
- **운영 전제**:
  - 이 룰의 핵심은 `가계정 사용`이 아니라 `장기 미정리(open)`다.
  - `lettrage` 계열은 ERP/국가별 편차가 커서 보조 입력으로만 사용한다.
  - Phase 1에서는 계정별 적응형 grace 보정 없이, 정해진 `suspense_aging_days`를 공통 기준으로 사용한다.
  - 정상 clearing 계정 구분, 계정별 grace 추천, 예외 후보 자동 제안은 Phase 2/3 보조 분석으로 넘긴다.
- **DataSynth 평가 계약**: `v42_candidate`부터 `lettrage`, `lettrage_date`, `amount_open`, `is_cleared`, `settlement_status`, `settlement_date`를 원장에 포함한다. `labels/suspense_lifecycle_population*.csv/json`은 가계정 정산 lifecycle 모집단, `labels/suspense_aging_review_population*.csv/json`은 L3-09 raw review population, `labels/suspense_confirmed_anomalies*.csv/json`은 확정 `SuspenseAccountAbuse` truth, `labels/suspense_normal_controls*.csv/json`은 정상 clearing 대조군이다. L3-09 raw hit 전체를 확정 anomaly precision 분모로 쓰지 않는다.
- **Phase 3 이관**: 적요 의미 분석은 별도다. L3-09는 Phase 1에서 `정산상태 + 체류일수`를 본다.

#### L3-10 — 고위험 계정 사용 (HighRiskAccountUse) ✅

- **심각도**: 3
- **근거**: 현금성 계정, 가계정, 가지급금/대여금/선급금 등 감사인이 지정한 **민감 계정군** 사용은 별도 검토 대상이다.
- **탐지 로직**: `gl_account`가 `patterns.high_risk_account_use.accounts`와 일치하거나 `account_prefixes`로 시작하는 경우
- **구현**: `fraud_rules_access.py` → `b13_high_risk_account_use()`
- **필요 피처**: `gl_account`
- **Phase 1 적용 방침**
  - 이 룰은 강한 단독 적발 룰이 아니라 `logic_mismatch` 계열의 **민감 계정 접촉 신호**로 사용한다.
  - 기본 제품값(`1190`, `2190`, `111*`, `112*`, `113*`)은 starter default이며, 실제 운영에서는 고객사 CoA와 감사 범위에 맞게 조정한다.
  - 현금성/가계정/가지급금/대여금/선급금/상품권/임시정산 계정 등 민감 계정군을 engagement 초기에 확정하고, `L3-02`, `L1-05`, `L1-07`, `L3-04`, `L3-08`, `L4-04` 등과 결합될 때 우선순위를 높인다.
- **결과 제시 방식**
  - `raw_signal`: 민감 계정군을 건드린 전체 모집단이다. 단독 부정 경고가 아니라 review population으로 보여준다.
  - `priority_case`: `raw_signal` 중 수기/조정, 고액, 미정리, 승인일 누락, 기말/비정상시점 같은 보강 맥락이 있는 우선 검토 건이다.
  - `normal_control_candidate`: `raw_signal` 중 자동/반복/시스템 처리 등 정상 사용 맥락이 강한 건이다. 낮은 우선순위 또는 whitelist 후보로 본다.
  - 따라서 화면과 리포트는 `L3-10 전체 건수`와 `우선 검토 건수`를 분리해서 보여준다. `HighRiskAccountUse` confirmed label과 직접 precision을 비교할 때는 `priority_case`만 별도로 본다.
- **운영 전제**
  - 민감 계정 정의는 시스템이 자동 확정하지 않는다. 최종 계정군 정의와 예외 범위는 감사인 또는 사용자가 승인한다.
  - 회사별 CoA가 다르므로 같은 `111*` 계열이라도 어떤 회사에서는 현금성 계정이지만, 다른 회사에서는 전혀 다른 의미일 수 있다. 따라서 prefix 기본값을 그대로 쓰는 것은 임시 초기값으로만 본다.
  - UI/설정 문서에는 이 룰을 `고위험 계정 사용`보다는 `민감 계정군 접촉 신호`에 가깝게 설명하는 편이 실무 해석에 맞다.
- **DataSynth 평가 계약**: `v45`부터 L3-10은 라벨-only precision/recall로 평가하지 않는다. `labels/high_risk_account_review_population*.csv/json`가 L3-10 raw coverage truth이며, `HighRiskAccountUse` 및 `labels/high_risk_account_confirmed_anomalies*.csv/json`는 `priority_case` 성격의 일부 의심 케이스만 담는다. `labels/high_risk_account_normal_controls*.csv/json`에는 정상적인 민감 계정 사용 대조군을 둬서 “민감 계정이면 모두 부정”이라는 shortcut 학습을 막는다.
- **DataSynth 구현 주의**: CSV에서 `gl_account`가 `1190.0`처럼 읽히는 경우가 있으므로 L3-10 계정 비교는 trailing `.0`을 제거한 계정코드로 수행한다.

#### L3-11 — 매출 컷오프 불일치 (RevenueCutoffMismatch) ✅

- **심각도**: 3
- **근거**: 240§32(b), 315호, K-IFRS 15 수익 인식 기간귀속
- **성격**: Phase 1 review-needed 룰. 단독 부정 확정이 아니라, 수익 인식 시점과 근거 이벤트 시점이 맞는지 보는 cutoff 검토 신호다.
- **현재 탐지 로직**
  - `posting_date`와 `delivery_date`가 모두 존재하는 행만 검사한다.
  - 매출 계정(`is_revenue_account` 또는 `revenue_account_prefixes`)은 `ev_revenue_cutoff_days`를 적용한다.
  - 비용 계정(`expense_account_prefixes`)은 `ev_expense_cutoff_days`를 적용한다.
  - 차이가 허용일수를 초과하면 `day_diff / ev_cutoff_max_day_diff`로 점수화하고, 기말 전표(`is_period_end`)는 `ev_cutoff_period_end_weight`를 곱한다.
- **실무 해석**
  - `delivery_date`는 모든 거래의 정답 기준일이 아니라, Phase 1에서 사용할 수 있는 **인식 기준 이벤트의 proxy**다.
  - 제품/상품/O2C 출하 매출에서는 비교적 강한 신호로 본다.
  - 용역, 구독, 공사, 검수조건부, 설치조건부 거래는 `service_confirmation_date`, `service_end_date`, `acceptance_date`, `installation_complete_date`, `billing_plan` 같은 더 적합한 기준일이 있으면 그 날짜를 우선해야 한다.
  - 기준일 후보가 없으면 정상으로 판정하지 않고, cutoff 검증 불가로 해석한다.
- **한계**
  - ERP에 반품권, 검수조건, 설치조건, 기간용역 조건이 항상 구조화 필드로 존재하지 않는다.
  - 계약서/첨부/OCR/업무 모듈에만 있는 조건은 Phase 1 단순 룰로 확정하지 않는다.
  - `delivery_date`가 없는 거래를 0점으로 두는 것은 "정상"이 아니라 "이 룰로는 미검증"이라는 의미다.
- **조합 시 위험도 해석**
  - `L3-11 단독`: 기간귀속 검토 후보. Medium.
  - `L3-11 + L4-01`: 고액 매출과 cutoff 불일치가 결합된 강한 매출 검토 후보. High.
  - `L3-11 + L4-01 + L3-04`: 기말 고액 매출 cutoff 후보. High~Critical.
  - `L3-11 + L4-01 + L3-02/L1-07/L1-05`: 수기 또는 승인통제 우회가 붙은 고액 cutoff 후보. Critical.
- **구현**
  - 오케스트레이터: `evidence_detector.py` → registry rule id `L3-11`
  - 룰 함수: `evidence_rules.py` → `ev02_cutoff_violation()`
- **필요 피처/컬럼**
  - 필수 비교: `posting_date`, `delivery_date`
  - 계정 분류: `is_revenue_account` 또는 `gl_account`
  - 보강: `is_period_end`, `business_process`, `document_type`, 기준 이벤트 날짜(`acceptance_date`, `service_end_date`, `installation_complete_date` 등)

---

### 2.4 L4: 통계적 이상치 (6개, L4-02 Benford는 독립 트랙)

#### L4-01 — 매출 이상 변동 (RevenueManipulation)

- **심각도**: 5
- **근거**: 240보론2, §32(c) 비경상거래. **FSS 최다유형**: 매출 허위계상
- **탐지 로직**: 매출 계정(4xxx) 금액이 Z-score 임계값 초과
  - `patterns.revenue_account_prefixes: ['4']` (`config/audit_rules.yaml`)
  - `zscore_threshold: 3.0` (`config/settings.py`, 회사/engagement override 가능)
- **구현**: `fraud_rules_feature.py` → `b01_revenue_manipulation()`
- **필요 피처**: `is_revenue_account`, `amount_zscore` (파생)
- **실제 의미**
  - 현재 구현상 핵심은 **매출 계정 고액 이상치**다.
  - 매출 급감, 음수 조정, 환입, 취소, 후속 역분개를 직접 잡는 룰이 아니며, 그런 신호는 별도 reversal/cutoff/trend 룰에서 다룬다.
- **Phase 1 적용 방침**
  - `L4-01 단독 = 매출조작 확정`이 아니라 `금액적으로 튄 매출 라인`으로 보고, 다른 룰과의 동시 플래그 여부로 우선순위를 정한다.
- **한계**
  - 정상적인 대형 계약, 신규 고객, 신규 사업, 계절성 매출 집중도 플래그될 수 있다.
  - 여러 건으로 쪼갠 가공매출은 개별 라인의 z-score가 낮으면 놓칠 수 있다.
  - 회사별 CoA에서 매출 계정 prefix가 `4`가 아니면 `revenue_account_prefixes`를 조정하지 않는 한 누락된다.
  - `amount_zscore > threshold`만 보므로 큰 양의 이상치 중심이다. 음수 조정, 환입, 취소, 매출 감소 분석은 이 룰의 직접 목표가 아니다.
  - z-score는 모집단 통계에 의존하므로 극단값이 평균/표준편차를 같이 흔들 수 있다. 표본이 작을 때는 CoA 상위그룹/전체 분포 fallback을 사용하므로 해석 강도가 낮아진다.
- **조합 시 위험도 해석**
  - `L4-01 + L4-03`: 매출 계정 특화 이상치이면서 전체 금액 기준으로도 고액인 유의적 매출 거래 후보
  - `L4-01 + L3-04/L3-11`: 기말 집중 또는 cutoff 불일치가 붙은 고액 매출 후보
  - `L4-01 + L3-02/L1-05/L1-07/L1-09`: 수기·승인통제 우회가 붙은 고액 매출 후보
  - `L4-01 + L3-03/후속 취소·역분개`: 관계사 거래, 순환거래, 밀어넣기 후 되돌림 가능성을 후속 확인
  - 동일 전표 내 여러 라인이 L4-01에 걸리면 라인별 합산보다 전표 단위 최대점수와 동시 플래그 수를 함께 보여준다.

#### L4-02 — Benford 위반 (BenfordViolation) — 독립 트랙

- **심각도**: 2
- **근거**: 520§5 기대값-차이 분석, 240-A45(e) 단수/끝자리
- **판정 기준**:

  | 지표       | 적합     | 한계적 적합   | 부적합       | 부적합(강)  |
  |------------|---------|--------------|-------------|------------|
  | MAD        | < 0.006 | 0.006~0.012  | 0.012~0.015 | > 0.015    |
  | KS p-value | > 0.05  | 0.01~0.05    | < 0.01      | —          |

  > MAD 근거: Mark Nigrini, *Benford's Law* (Wiley, 2012). 감사/포렌식 분야 사실상 표준.

- **역할**: 개별 전표 적발 룰이 아니라 **모집단/계정 단위 분포 이상 finding**.
  - Benford는 분포 검정이므로 “이 전표가 위반”을 직접 증명하지 않는다.
  - 행별 전표 목록은 조사 후보(drill-down)로만 사용한다.
- **탐지 로직**:
  1. `gl_account`별 금액 첫째 자리 분포를 Benford 기대분포와 비교한다.
  2. 표본 100건 미만 계정은 계정별 검정에서 제외한다.
  3. 계정별 부적합 시 `MAD > threshold`인 자릿수만 후보 digit으로 선별한다.
  4. 전체 모집단 검정을 추가로 수행해 계정별 검정에서 놓친 전역 패턴을 보완한다.
  5. 결과는 `benford_findings` metadata에 `scope`, `gl_account`, `sample_size`, `mad`,
     `chi2_p_value`, `flagged_digits`, `candidate_rows`로 저장한다.
  6. 후보 digit 전표는 drill-down 후보로만 보관하며, 기본 행별 `L4-02` 점수는 0이다.
- **구현**: `benford_detector.py` → `BenfordDetector(BaseDetector)`
  - 내부적으로 `anomaly_rules_statistical.py` → `c07_benford_violation()`을 호출한다.
  - 분포 수준 검정이므로 L3/L4 묶음과 별도 가중치를 부여하고, 단독으로 대량 행 플래그를 만들지 않는다.
- **필요 피처**: `debit_amount`, `credit_amount`
- **DataSynth 상태**: `BenfordViolation` 라벨은 성능 평가용으로 존재할 수 있으나,
  이 룰의 1차 산출물은 라벨 전표 적발이 아니라 분포 finding이다.

  추가 검정 (Phase 2): Chi-square, Anderson-Darling

#### L4-03 — 이상 고액 (UnusuallyHighAmount)

- **심각도**: 3
- **근거**: 240§33(b), 315호. FSS 결산수정: 개발비 과대자산화
- **Phase1 탐지 로직**: 양의 금액 Z-score와 전역 상위 금액 가드를 함께 적용한다.
  - `amount_zscore > zscore_threshold` (기본 3.0)
  - `max(debit_amount, credit_amount) >= P90` (기본 `l403_min_amount_quantile: 0.90`)
  - 저액 방향 이상치는 `UnusuallyHighAmount`의 목적이 아니므로 `abs(zscore)`를 사용하지 않는다.
- **구현**: `anomaly_rules_simple.py` → `c08_amount_outlier()`
- **필요 피처**: `debit_amount`, `credit_amount`, `amount_zscore` (파생)
- **Phase1 범위**:
  - 계정별 금액 floor, 거래처별 기준, 대형거래 whitelist를 감사인이 직접 입력하게 하지 않는다.
  - Phase1에서는 설명 가능성과 유지보수성을 위해 전역 분위수 가드만 사용한다.
  - 반복 정상거래 자동 감점, 거래처/프로세스별 baseline, 계정별 P99 프로파일링은 Phase2 이상 고도화 대상으로 둔다.
- **한계**:
  - 정상 대형 자금 이동, 정기 결제, 선수금·미지급비용 같은 큰 정상거래도 후보에 포함될 수 있다.
  - 라인 단위 금액 기준이므로 전표 전체의 경제적 실질이나 차대변 구조까지 판단하지 않는다.
  - GL 표본이 작아 `amount_zscore`가 CoA/전체 fallback으로 계산되면 계정 고유 특성이 희석될 수 있다.
- **사용 방식**:
  - L4-03 단독 플래그는 "고액 검토 후보"로 보고, 단독으로 부정 또는 실무상 유의미한 finding으로 결론내리지 않는다.
  - 다음 룰과 결합될 때 Phase1 우선순위를 높인다.

  | 결합 | 의미 | 우선순위 |
  |---|---|---|
  | `L4-03 + L3-04` | 기말/기초에 발생한 고액 조정 전표 | High |
  | `L4-03 + L1-05/L1-07` | 고액 전표의 자가승인 또는 승인 누락 | High |
  | `L4-03 + L4-04` | 고액이면서 드문 차변-대변 계정 조합 | High |
  | `L4-03 + L3-08` | 고액인데 적요가 비어 있거나 깨져 있음 | Medium |
  | `L4-03 + L4-01` | 매출 계정 특화 이상치이면서 전체 금액 기준으로도 고액 | High |

#### L4-04 — 희소 차대 계정쌍 (RareDebitCreditAccountPair)

- **심각도**: 2
- **근거**: 240-A45(a) 비경상·저사용 계정, 315호
- **Phase 1 해석**: 비정상 확정 룰이 아니라, 해당 회사/기간 모집단에서 드물게 나타난 차변-대변 계정쌍을 검토 후보로 올리는 설명 가능한 약한 신호다.
- **탐지 로직**: 차변-대변 GL 계정쌍 빈도 하위 1%
  - Merge 기반 벡터화된 Cartesian product
  - 복합분개는 같은 전표의 모든 차변 행 × 모든 대변 행 조합을 생성
  - 희소쌍이 하나라도 포함된 전표는 전표 전체 라인을 플래그
  - 100-line limit per document (메모리 오버플로우 방지)
- **구현**: `anomaly_rules_statistical.py` → `c09_rare_account_pair()`
- **필요 피처**: `document_id`, `gl_account`, `debit_amount`, `credit_amount`
- **튜닝 파라미터**: `account_pair_rare_percentile` 기본 `0.01`
- **실무 사용 방식**
  - 단독으로 fraud 또는 회계처리 오류를 결론내리지 않는다.
  - `L3-04` 기말/기초, `L3-02` 수기전표, `L4-03` 고액, `L3-08` 적요 결손/파손, 승인/권한 룰과 겹칠 때 우선순위를 높인다.
  - 회사·업종·ERP별 계정체계가 다르므로 Phase 1에서 범용 whitelist/blacklist 조합을 직접 유지하지 않는다.
- **한계**
  - 도메인상 이상하지만 반복적으로 자주 등장한 조합은 희소하지 않으므로 놓칠 수 있다.
  - 정상적인 일회성 조정, 재분류, 연결조정, 시스템 전환 전표도 희소하다는 이유로 플래그될 수 있다.
  - 의미 기반 조합 이상은 Phase 2의 VAE/GNN/관계형 모델에서 보완한다.

#### L4-05 — 비정상 시간대 집중 (AbnormalHoursConcentration)

- **심각도**: 3
- **근거**: KLCA IT 체크리스트 — 특정 사용자가 감시 취약 시간대에 반복 입력하는 패턴은 단건 심야/주말 플래그보다 강한 행동 징후다.
- **탐지 로직**: 사용자별 비정상 시간대 입력 비율 이상치 + 심야 건수 + 급속 승인 신호
  1. `time_zone_category in {"midnight", "overtime"}` 또는 주말/공휴일을 비정상 시간대로 본다.
  2. `created_by`별 비정상 시간대 비율을 계산하고, 평균 대비 `abnormal_sigma_threshold` 이상인 사용자를 찾는다. 기본값은 Phase 1 후보 탐지 목적에 맞춰 `2.5σ`로 둔다.
  3. 절대 비율이 `min_abnormal_ratio` 미만이면 제외한다.
  4. 사용자 수가 적으면 sigma 대신 `min_midnight_entries`와 비율 기준으로 fallback하고, 최소 사용자 전표 수 미만이어도 심야 입력이 충분히 반복되면 해당 심야 전표만 후보로 올린다.
  5. 수기 전표가 비정상 시간대에 입력되고 `rapid_approval_minutes` 이내 승인되면 별도 플래그한다. 미탐을 줄이기 위해 금액 하한은 두지 않으며, 자동 전표 source와 `automated_system`은 과탐 방지를 위해 제외한다.
- **구현**: `anomaly_rules_simple.py` → `c12_abnormal_hours_concentration()`
- **필요 피처**: `created_by`, `posting_date`, `time_zone_category`, `is_weekend`, `is_holiday`, `approval_date`, `approved_by`, `is_manual_je` 또는 `source`
- **L3-05/L3-06과의 관계**: L3-05는 주말/공휴일 단건, L3-06은 감사인이 설정한 심야 구간 단건만 잡는다. L4-05는 사용자의 overtime·심야·비근무일 입력이 한 사람에게 집중되는지를 보는 상위 패턴 룰이다.
- **튜닝 파라미터**: `abnormal_sigma_threshold`, `rapid_approval_minutes`, `min_abnormal_ratio`, `min_midnight_entries`, `min_user_entries`, `auto_entry_sources`
- **DataSynth 계약**: `v32_candidate`부터 `AbnormalHoursConcentration` 라벨과 sidecar를 관리하며, 자동/반복 source와 `automated_system`은 라벨 주입 대상에서 제외한다.

#### L4-06 — 배치성 자동 전표 검토 신호 (BatchAnomaly) ✅

- **심각도**: 2
- **운영 성격**: 단독 고위험 적발 룰이 아니라 Phase 1 보조 검토 신호다. 과거 Phase 2 WU-09로 설계되었으나, 최신 PHASE1 관계도에서는 `statistical_outlier` evidence와 `batch_combo_bonus` 입력으로 운영한다.
- **근거**: 배치·인터페이스·시스템 전표는 정상 대량 처리도 많으므로, 단독 hit만으로 부정 가능성을 강하게 주장하지 않는다. 다만 개별 승인/검토가 약할 수 있어 기말·대량·금액 특이 패턴은 검토 후보로 남긴다.
- **배치성 source 기본값**: `batch`, `interface`, `system`, `auto`, `if`, `sys` 계열. 비교는 대소문자 무시.
- **탐지 로직**: 3가지 하위 패턴 OR 결합
  1. 기말 집중: 배치성 전표 중 기말 비율 > `batch_period_end_ratio` (기본 0.5)
  2. 대량 동시 생성: 동일 `posting_date` 배치성 전표 건수 ≥ `batch_simultaneous_threshold` (기본 50)
  3. 금액 이상: 배치성 전표 내 Z-score > `batch_amount_zscore` (기본 3.0), std=0 방어 포함
- **위험도가 높아지는 결합 신호**

  | 결합 | 의미 | 운영 우선순위 |
  |------|------|---------------|
  | `L4-06 + L3-04/L3-07/L1-08` | 자동 배치성 전표가 결산·cutoff·전기일 괴리와 결합 | Medium 이상 |
  | `L4-06 + L1-05/L1-06/L1-07` | 자동 처리와 승인/권한 통제 실패가 결합 | Medium 이상 |
  | `L4-06 + L4-03/L4-04/L3-10` | 배치성 전표가 고액·희소 계정쌍·민감 계정과 결합 | Medium 이상 |
  | `L4-06 + L3-08` | 자동 전표인데 적요가 비어 있거나 깨져 있음 | 보조 가점 |
  | `L4-06 + L2-05/L2-02` | 배치성 처리 후 역분개·중복 징후 동반 | High 후보 |

- **코드 반영**: `score_aggregator.py`는 L4-06 결합 신호를 `batch_combo_score`로 계산하며, L4-06 단독은 승격하지 않는다.
- **구현**: `anomaly_rules_batch.py` → `c13_batch_anomaly()`
- **필요 피처**: `source`, `is_period_end`, `posting_date`, `debit_amount`, `credit_amount`
- **한계**: 현재 동일 일자 판단은 `posting_date` 값을 그대로 사용한다. 시간이 포함된 timestamp면 같은 달력일이라도 다른 값으로 묶일 수 있으므로, 날짜 정규화는 별도 개선 과제다.
- **DataSynth 상태**: 과거 DataSynth는 `source='batch'` 전표가 부족했으며, `interface/system/auto` 계열까지 포함해 재검증이 필요하다.

---

### 2.5 Variance 독립 트랙: 전기 대비 변동 (2개, 기존회사 전용)

전기(fiscal_year - 1) engagement 데이터가 있는 기존회사에서만 실행.
신규회사(anonymous) 또는 전기 engagement 미존재 시 자동 스킵 (graceful degradation).

| Rule ID | 룰 이름                    | Severity | 감사기준서                    | 구현 파일                                |
|---------|----------------------------|:--------:|-------------------------------|------------------------------------------|
| D01     | 계정과목 거래 활동량 급변 | 4        | ISA 520 §5, PCAOB AS 2305    | `src/detection/variance_rules.py`        |
| D02     | 월별 분포 패턴 변화        | 3        | ISA 520 §5                    | `src/detection/variance_rules.py`        |

#### D01 — 계정과목 거래 활동량 급변 (AccountActivityVariance)

- **입력**: 당기 DataFrame + `PriorSummary.account_aggregates`
- **성격**: Phase 1 분석적 검토용 스크리닝 룰. 단독 부정 판정이 아니라 계정 레벨 attention signal로 사용한다.
- **판정 로직**:
  - 당기/전기 `gl_account`별 거래 활동량 집계 비교 (`debit_amount + credit_amount` 기준 total_amount, count, avg_amount)
  - 가중평균 변동률 = `total_var × 0.5 + count_var × 0.3 + avg_var × 0.2`
  - 임계값: `variance_threshold` (기본 0.5 = 50%) 초과 시 해당 계정의 모든 행 플래그
  - 신규 계정(전기 미존재): 자동 플래그 (변동률 = 1.0)
- **잡아내는 신호**: 전기 대비 계정의 총 거래 활동량, 전표 건수, 평균 전표 금액이 급변한 경우. 신규 계정 등장도 포함한다.
- **운영 해석**: D01 단독은 `검토 필요` 수준으로 보고, 고액 이상치·희귀 계정쌍·결산 전표·권한/승인 룰 등과 결합될 때 위험도를 높인다.
- **한계**: 이 룰은 기말 잔액 변동 탐지가 아니라 총 거래 활동량 변동 탐지다. 전기에는 있었지만 당기에 사라진 계정은 당기 행이 없어 직접 플래그하지 못한다.

#### D02 — 월별 분포 패턴 변화 (MonthlyPatternVariance)

- **입력**: 당기 DataFrame + `PriorSummary.monthly_patterns`
- **판정 로직**:
  - Jensen-Shannon Divergence(JSD)로 전기/당기 월별 금액 분포 비교
  - 임계값: `monthly_pattern_threshold` (기본 0.3) 초과 시 해당 계정의 모든 행 플래그
  - 전기/당기 모두 `min_monthly_data_months`개월 이상 데이터 존재해야 비교 수행, 미만이면 스킵
- **잡아내는 신호**: 전기에는 고르게 발생하던 계정이 당기에는 결산월, 특정 분기, 특정 프로젝트 월에 몰리는 경우.
- **위험도가 높아지는 결합 신호**

  | 결합 | 실무 해석 | 운영 우선순위 |
  |------|-----------|---------------|
  | `D02 + L3-04/L3-07/L1-08` | 월별 집중 변화가 기말 전표, 전기일 괴리, 회계기간 불일치와 결합 | High 후보 |
  | `D02 + L4-03/L4-04` | 패턴 변화 월에 고액 또는 희귀 계정 조합이 동반 | Medium 이상 |
  | `D02 + L3-08` | 패턴 변화 계정의 적요가 비어 있거나 깨져 있음 | 보조 가점 |
  | `D02 + L2-05` | 특정 월 집중 후 역분개·대체·정리 패턴이 동반 | High 후보 |
  | `D02 + D01` | 월별 배치뿐 아니라 계정 활동량 자체도 급변 | Medium 이상 |

- **한계**
  - 계정 단위 분석 신호이므로 특정 전표 1건을 확정 부정으로 지목하지 않는다.
  - 계절성, 사업 개편, 신규 프로젝트, ERP/계정체계 변경, 정상 결산 정책 변경도 동일한 신호를 만들 수 있다.
  - 전기 데이터 품질이 낮거나 `fiscal_period`가 누락/오류이면 비교 결과의 신뢰도가 낮다.
  - 신규 계정은 D02에서 스킵된다. 신규 계정 검토는 D01이 담당한다.

#### Phase 1 공통 운영 한계와 조합 해석

Phase 1은 실무에서 `1차 스크리닝`과 `감사 샘플링 우선순위화`에 사용한다. 단독 부정 판정, 감사 결론 자동화, 동일 임계값의 회사 간 일괄 적용에는 사용하지 않는다.

| 한계 | 단독 해석 | 조합되면 위험해지는 신호 |
|------|-----------|--------------------------|
| 룰 임계값이 초기 설계값 중심 | false positive가 많을 수 있음 | 동일 전표/계정에 금액, 시점, 승인, 계정 논리 신호가 2개 이상 결합 |
| 입력 품질 의존 | 컬럼 누락·매핑 오류가 미탐/과탐을 만든다 | `L1-02`, `L1-08` 같은 무결성 신호와 다른 탐지 룰이 동시에 발생 |
| 계정/월/사용자 단위 룰 | 개별 전표 이상을 직접 입증하지 않는다 | 계정 단위 신호(`D01/D02`)와 행 단위 신호(`L3-04`, `L4-03`, `L2-05`) 결합 |
| 정상 반복·시즌성 구분 한계 | 정기 지급, 결산 배부, 감가상각이 걸릴 수 있음 | 반복성인데도 승인 누락, 적요 결손/파손, 역분개, 기말 집중이 같이 존재 |
| 텍스트 룰의 의미 이해 한계 | Phase 1은 의미 부족·우회 표현을 판단하지 않는다 | `L3-08`이 고액, 수기전표, 기말, D02 패턴 변화와 결합 |

운영 원칙:
- 단일 룰 hit는 `검토 후보`로 둔다.
- 다른 성격의 신호가 2개 이상 결합되면 review queue 우선순위를 올린다.
- `통제 실패(L1-05/L1-06/L1-07) + 시점 이상(L3-04/L3-07/L1-08) + 금액/계정 이상(L4-03/L4-04/L3-10)` 조합은 Phase 1에서 가장 먼저 보는 고위험 축이다.
- D01/D02는 전기 대비 분석적 절차 신호이므로, 예산·TB 변동·사업 이벤트·계정체계 변경 확인 없이 결론으로 쓰지 않는다.

#### Variance 독립 트랙 가중치 (기존회사 전용)

기존회사에서는 Variance 트랙이 활성화되며, 아래 표가 개요의 row-level 기본 가중치를 대체한다.

| 레이어          | 신규회사 | 기존회사 |
|-----------------|:--------:|:--------:|
| A (무결성)      | 0.15     | 0.12     |
| B (부정)        | 0.45     | 0.38     |
| C (이상징후)    | 0.25     | 0.20     |
| Benford         | 0.15     | 0.12     |
| **D (전기 변동)** | **—**  | **0.18** |

---

## 3. Phase 2: ML / DL 보조 분석

Phase 2는 Phase 1의 룰 기반 탐지를 대체하는 단계가 아니라, **룰만으로 놓치기 쉬운 패턴형 이상거래를 보완**하는 계층이다.
특히 금액 분포, 시계열 패턴, 신규 거래관계, 중복·유사 반복, 법인 간 상호작용처럼 단일 룰로 정의하기 어려운 신호를 구조적으로 포착한다.

Phase 2의 운영 책임은 **PHASE1 case priority를 정밀 보정하는 것**이다. PHASE1의 `L1-05`, `L2-03` 같은 룰 ID 자체를 모델 feature로 넣어 다시 예측하게 만들면 target leakage/proxy 문제가 생기고, ML이 새로운 패턴을 찾는 대신 룰 복제기로 전락할 수 있다.

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

### 3.1.1 PHASE1 Case 입력 계약과 Leakage 방어

Phase 2는 row-level raw rule output을 직접 학습 입력으로 삼지 않고, PHASE1 case를 구조화 요약한 값을 입력으로 받는다. 입력은 두 종류로 분리한다.

#### Feature Firewall 정책

PHASE2 case-level ML overlay 입력은 allowlist 기반 feature firewall을 통과해야 한다.

- 모델 `fit`/`predict` 직전 최종 입력에는 `top_rule_ids`, `raw_rule_hits`, `primary_theme`, `secondary_tags`, `phase1_case_id` 같은 식별자·provenance 컬럼이 있으면 안 된다.
- 최종 feature는 숫자형 또는 boolean engineered feature만 허용한다.
- `document_id`, `company_code`, `gl_account` 같은 원천 식별 컬럼은 detector 내부 조인·관계 분석에 쓰일 수 있지만, case-level ML overlay feature로는 쓰지 않는다.
- 단순 keyword drop(`id`, `code`, `rule` 전면 금지)은 사용하지 않는다. `rule_diversity_count`처럼 안전한 집계 피처까지 제거할 수 있기 때문이다.
- 구현 기준: `src/services/phase2_case_contract.py`의 `PHASE2_CASE_FEATURE_COLUMNS`, `enforce_phase2_case_feature_firewall()`

#### ML feature로 사용할 수 있는 값

룰 이름이나 theme 이름 자체가 아니라, 밀도·분포·행동·관계형 특징으로 변환된 값만 feature로 사용한다.

- `rule_diversity_count`: 한 case 안에 섞인 룰 종류 수
- `evidence_type_count`: evidence type 종류 수
- `theme_entropy`: case 내 evidence/theme 분산도
- `cross_process_flag`: 여러 business process가 교차되는지 여부
- `cross_user_flag`: 여러 사용자 또는 승인자가 얽히는지 여부
- `cross_counterparty_flag`: 여러 거래처가 얽히는지 여부
- `repeat_months`, `repeat_score`: 반복 개월 수와 반복 강도
- `document_count`, `row_count`, `total_amount`
- `amount_score`, `control_score`, `logic_score`, `behavior_score`
- `has_control_failure`, `has_high_materiality`, `has_repeat_pattern`
- `historical_anomaly_percentile`: 동일 사용자/거래처/계정군의 과거 대비 현재 case score 백분위
- `user_case_frequency_percentile`: 동일 사용자의 최근 case 발생 빈도 백분위
- `counterparty_case_frequency_percentile`: 동일 거래처의 최근 case 발생 빈도 백분위
- `amount_percentile_within_user`: 사용자별 과거 금액 분포 대비 백분위
- `amount_percentile_within_counterparty`: 거래처별 과거 금액 분포 대비 백분위

위 목록 중 `historical_anomaly_percentile`, 사용자/거래처별 percentile 계열은 목표 설계 필드다. 현재 구현된 case contract는 기본 집계·교차·점수 피처를 먼저 제공하고, 과거 분포 기반 percentile은 engagement history 연결 후 확장한다.

#### Provenance/display 전용 값

아래 값은 모델 feature가 아니라, 디버깅·감사 추적·화면 설명·export provenance에만 사용한다.

- `phase1_case_id`
- `primary_theme`, `secondary_tags`
- `top_rule_ids`
- `raw_rule_hits`
- `representative_explanation`
- `phase1_case_priority`
- `phase1_base_priority`
- `phase1_priority_adjustments`

즉 Phase 2는 `L1-05가 있으면 위험`을 학습하는 것이 아니라, `통제 신호가 다양한 사용자·프로세스·시점·금액 분포 안에서 비정상적으로 밀집했는가`를 학습한다.

### 3.1.2 PHASE2 Case Overlay 출력 계약

Phase 2는 PHASE1 결과를 덮어쓰지 않고, case에 overlay를 붙인다.

```text
phase2_case_overlay =
  phase1_case_id
  phase2_family_scores
  phase2_adjusted_priority
  precision_adjustment_reason
  detector_statuses
  phase2_inference_contract
  phase2_training_report_id
```

운영 원칙:

- PHASE1 `case_priority`는 원본으로 보존한다.
- PHASE2는 `phase2_adjusted_priority` 또는 `review_priority_adjustment`를 별도 필드로 남긴다.
- 모델 family별 score와 provenance를 함께 저장해, 어떤 모델이 어떤 이유로 case를 올리거나 내렸는지 추적 가능하게 한다.
- dashboard/export는 `PHASE1 base + PHASE2 overlay`를 조합해 보여준다.

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
| MissingDocumentation    | ProcessIssue | 3  | NLP (설명 실질성 분석) | ⬜   |
| CircularTransaction     | Graph(GR01)  | 4  | Johnson N-hop 순환 (length_bound=5) | ✅ WU-22 |
| TransferPricingAnomaly  | Graph(GR03)  | 4  | 양방향 IC 엣지 price asymmetry      | ✅ WU-22 |
| TrendBreak (TL4-01/TL2-01)  | Statistical  | 4/3| 설정vs상각 분리     | ✅   |

### Phase 3 점수 체계 (7트랙)

```
rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + duplicate(0.15) + nlp(0.10) + graph(0.15)
```

**Phase 3 누적: Tier 1(20) + Tier 2(16) + Tier 3(5) = 41개 유형 커버**

### 4.1 PHASE3 입력 계약 — Selected Case 중심

Phase 3는 전체 전표 raw row를 일괄 LLM/NLP에 투입하지 않는다. PHASE1/2가 선별한 case 단위 입력만 사용한다.

Context limitation 정책:

- 자동 생성 기본값은 상위 `top_n=10` case다.
- `top_n`은 하드 리밋 `100`을 넘기지 않는다.
- `max_documents_per_case` 기본값은 `10`, 하드 리밋은 `20`이다.
- 전표는 랜덤 샘플링하지 않는다. 금액이 큰 전표 3건을 먼저 고르고, 그 다음 rule/evidence가 많이 붙은 대표 전표를 보강한다.
- warning/medium case는 기본 자동 생성 대상이 아니라 UI의 명시적 "설명 생성" 같은 on-demand 경로로 생성한다.
- 구현 기준: `src/llm/phase3_case_prompt.py`, `src/llm/case_narrative_generator.py`, `src/services/phase3_case_narrative_service.py`

기본 입력:

- `case_id`
- `primary_theme`
- `representative_explanation`
- `evidence_tags`
- `top_documents` 기본 10건, 최대 20건
- `top_rule_ids`와 rule 설명 metadata
- `phase1_case_priority`
- `phase2_family_scores`
- `phase2_inference_contract`
- `phase2_training_report_id`
- 사용 가능한 `line_text`, `header_text`, `gl_account`, `document_type`, `business_process`, `created_by`, `approved_by`, `counterparty`, `amount`, `posting_date`

`top_rule_ids`는 LLM 설명의 근거 표시와 provenance 연결용이며, 새로운 사실을 추론하는 재료가 아니다.

### 4.2 관계망 Context 주입 원칙

Graph/network context는 모든 case에 넣지 않고, 필요한 case에만 요약 형태로 넣는다.

주입 조건:

- `primary_theme`가 `duplicate_or_outflow`, `intercompany_structure`, `statistical_outlier` 중 하나
- `secondary_tags`에 `duplicate_or_outflow`, `intercompany_structure`, `statistical_outlier` 중 하나가 포함됨
- Phase 2의 `intercompany`, `relational`, `graph` family score가 높음
- `related_entity_risk.degree`, `graph_degree`, `distinct_process_count`, `department_count` 등 관계망 degree 요약값이 1보다 큼
- 동일 사용자·거래처·회사쌍 주변 case가 최근 기간에 반복 발생

권장 입력 필드:

```text
related_entity_risk:
  user_recent_case_count
  counterparty_recent_case_count
  company_pair_recent_case_count
  shared_counterparty_count
  degree
  distinct_process_count
  department_count
  graph_hop_summary
  related_high_priority_case_ids
```

운영 원칙:

- LLM에 raw graph edge 전체를 넘기지 않는다.
- graph detector나 relational detector가 계산한 요약값만 전달한다.
- LLM은 그래프 분석을 직접 수행하지 않고, 이미 계산된 관계망 신호를 감사 설명문으로 번역한다.

### 4.3 환각 방지와 표현 제약

Phase 3는 회계·법률 결론 생성기가 아니라 **근거 기반 감사 narrative generator**다. 제공된 PHASE1 evidence, PHASE2 provenance, case input 안에서만 서술한다.

프롬프트 제약:

- 제공된 입력에 없는 사실을 쓰지 않는다.
- 회계기준, 법규 조항, 회사 정책을 새로 추론해 덧붙이지 않는다.
- 부정, 위반, 조작을 단정하지 않는다.
- `가능성`, `검토 필요`, `확인 필요` 수준으로 표현한다.
- 근거가 부족하면 부족하다고 명시한다.
- 각 핵심 문장은 어떤 evidence 또는 model provenance에 기반했는지 추적 가능해야 한다.
- PHASE1의 `적요 결손/파손 신호`와 PHASE3의 `의미 기반 설명 부족 판단`을 구분해 표시한다.

### 4.4 Phase 3 적요/설명 분석 역할 정의

Phase 3는 Phase 1의 `L3-08`을 대체하기 위해 존재하는 것이 아니라, Phase 1이 의도적으로 단순화한 텍스트 판정을 **의미 이해 기반으로 보강**하기 위한 계층이다.

- **Phase 1 L3-08이 하는 일**
  - 공백/누락, 노이즈성 문자열처럼 원천 기록이 없거나 깨진 형식 신호만 수집
  - 설명 가능성과 재현성을 우선하는 저비용 스크리닝
- **Phase 1 L3-08이 하지 않는 일**
  - 지나치게 짧지만 정상일 수 있는 적요를 길이만으로 부실 판정
  - 명시 위험 키워드나 회사별 blacklist/whitelist 기반 위험 적요 판정
  - 말은 길지만 실질 설명이 없는 적요 판정
  - 회사 내부 은어, 완곡어, 우회 표현 해석
  - 계정/프로세스/금액/시점 대비 적요의 의미상 부자연스러움 판단

따라서 Phase 3 NLP 계층은 아래 역할을 담당한다.

1. **설명 실질성 부족 판정**
   - 예: `결산 반영`, `정리분`, `조정사항 반영`, `기타 대체`처럼 문장은 존재하지만 실질 설명이 부족한 경우
2. **계정-적요 의미 정합성 점검**
   - 계정, 업무 프로세스, 금액, 시점에 비해 적요가 부자연스럽거나 설명 책임을 회피하는 경우
3. **은어/우회 표현 탐지**
   - 회사 내부 표현, 완곡어, 책임 회피성 표현처럼 키워드 사전에 없는 문구 탐지

운영 원칙은 다음과 같다.

- Phase 1은 recall 우선 스크리닝을 유지한다.
- Phase 3는 LLM/NLP를 전체 전표에 일괄 적용하기보다, `L3-08`, `L3-02`, `L3-04`, `L3-11`, `L1-05`, `L1-07`, `L2-05`, `L3-10` 등과 결합된 고위험 후보 또는 애매한 후보에 우선 적용한다.
- 사용자 설명에서는 Phase 1의 `적요 결손/파손 신호`와 Phase 3의 `의미 기반 설명 부족 판단`을 구분해 보여준다.

---

### 4.5 Graph Detector (WU-22) — networkx 기반 순환·이전가격

> **근거**: ISA 550 §23 특수관계자 사업상 합리성 · FSS 순환거래 페이퍼컴퍼니 패턴.
> **차별화**: L3-03(관계사 거래 검토 후보) 및 R03(그룹 편차 통계)의 한계를 그래프 토폴로지로 보완.

#### GR01 — CircularTransaction (N-hop 순환)

- **심각도**: 4
- **알고리즘**: networkx `simple_cycles(G, length_bound=max_cycle_length)` (Johnson)
- **그래프 구성**:
  - 노드: `(company_code, trading_partner)` 튜플
  - 엣지: `credit > 0` → `company → partner`, `debit > 0` → `partner → company`
  - 자료구조: `MultiDiGraph` (다중 엣지 보존 → 원본 행 인덱스 역매핑)
- **`trading_partner` NULL fallback**: 동일 `document_id` 그룹의 다른 `company_code`로 implicit IC pair 추론 (DataSynth 640건 NULL 복구 목적)
- **점수화**: binary 1.0 × `severity_factor(0.8)` (연속 점수화는 튜닝 단계로 이연)
- **L3-03과의 관계**: L3-03은 `is_intercompany` 기반 관계사 거래 후보만 반환한다. GR01이 실제 N-hop 순환 탐지를 담당한다.
- **DataSynth truth 해석**: v39 기준 GR01은 두 층으로 평가한다. `graph_gr01_review_population`은 룰이 구조적 순환 후보를 올리는지 보는 coverage truth이고, `CircularTransaction`/`graph_gr01_confirmed_anomalies`는 확정 이상 truth다. `graph_gr01_normal_cycle_controls`는 정상 내부거래 순환도 존재한다는 negative-control이므로 raw GR01 hit를 전부 FP로 계산하지 않는다.

#### GR03 — TransferPricingAnomaly (양방향 price asymmetry)

- **심각도**: 4
- **알고리즘**: pandas groupby 기반 양방향 쌍 식별 + 차이율 계산
  1. IC 행만 필터
  2. `reference`가 있는 경우 같은 reference의 상호 회사쌍 문서를 먼저 비교한다. IC 채권/채무 GL이 서로 달라도 문서 최대금액 기준 비대칭을 계산한다.
  3. reference-pair 비교 후, 보조 신호로 `(src_company, dst_company, gl_account)` 그룹 평균 amount와 역방향 그룹을 비교한다.
  4. `deviation = |amount_fwd - amount_rev| / min(amount_fwd, amount_rev) > threshold(20%)`
  5. 점수 = `min(1.0, deviation / (threshold × 3))`
- **V39 보정**: `TransferPricingAnomaly` 라벨은 한쪽 문서의 전체 거래금액을 scaling하므로, IC 라인 금액만 비교하면 세금/손익 라인 때문에 미탐이 생긴다. GR03 reference-pair 경로는 문서 최대금액을 사용해 이 라벨 구조와 실제 대사 관점을 맞춘다.
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
3. **엣지 수 안전장치**: `len(edges_df) > graph_gr01_max_edges(50,000)` 시 `quantile` 기반 `min_amount` 자동 상향 + warning. 추가로 `weakly_connected_components`로 분리 후 컴포넌트별 `simple_cycles` 호출. 컴포넌트는 노드 수와 엣지 수가 모두 임계값을 넘을 때만 skip한다.

**벤치마크**: 100k 행 DataFrame에서 실행 시간 1.3초 (목표 15초 이내).

#### Settings 파라미터 (`config/settings.py`)

```python
graph_gr01_max_cycle_length: int = 5          # Johnson length_bound
graph_gr01_min_amount: float = 10_000_000.0   # 엣지 최소 금액 (materiality, 1천만원)
graph_gr01_max_edges: int = 50_000            # 엣지 수 상한 (초과 시 자동 상향)
graph_gr01_max_component_size: int = 500      # component 노드 임계
graph_gr01_max_component_edges: int = 5_000   # component 엣지 임계
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
| 100% Recall 룰 | 10개 (L1-01, L1-02, L1-03, L4-01, L2-02, L3-05, L3-06, L1-08, L3-08, L2-05) |
| L1-06 flagged | 1.9% (정상) |
| Normal 등급 | 85.2% |
| 구조적 한계 (ML 필요) | L2-03(10%), L3-03(4%), L4-04(9%), L4-02(29%) — Phase 2 대상 |

상세: [test-results/rule-label-gap-analysis.md](../tests/phase1_rulebase/test-results/rule-label-gap-analysis.md)

### 미해결 (경미 — Phase 2 이후)

| 항목 | 원인 | 현재 상태 | 대상 |
|:-----|:-----|:---------|:-----|
| L3-09 적요 키워드 부족 | 확률 체인(0.5%×5%×30%)으로 키워드 주입 건수 극소 — 정상 동작 | GL prefix 기반 탐지 정상 작동. 적요 의미 분석은 Phase 3 LLM 영역(#71, #84, #88) | Phase 3 이관 |
| trading_partner | 99.9% NULL (784건) | L3-03 IC GL prefix 매칭으로 대체 | DataSynth Rust |
| cost_center | 81.2% NULL | L2-05 세분화 키 활용도 제한 | DataSynth Rust |

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
RelatedPartyTransactionSignal     3     2     3      8    B       L3-03
ExpenseCapitalization              —     —     —      —    B       L2-04  *
RushedPeriodEnd                   3     3     3      9    C       L3-04
WeekendPosting                    3     1     3      7    C       L3-05
AfterHoursPosting                 3     1     3      7    C       L3-06
AbnormalHoursConcentration        2     2     3      7    C       L4-05
BackdatedEntry                    3     2     3      8    C       L3-07
WrongPeriod                       2     2     3      7    C       L1-08
VagueDescription                  3     3     3      9    C       L3-08
BenfordViolation                  3     2     2      7    Benford L4-02
UnusuallyHighAmount               2     3     3      8    C       L4-03
UnusualAccountPair                3     1     2      6    C       L4-04
SuspenseAccountAbuse              —     —     —      —    C       L3-09  *
```

운영 주의:
- 위 표의 `ManualOverride -> L3-02`는 원래 DataSynth anomaly taxonomy 기준 매핑이다.
- 실제 `L3-02` 운영/평가 truth는 `source in ('manual','adjustment')`인 수기전표 모집단 sidecar를 우선 사용한다.

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
| `document_id`    | str    | `belnr` | 전표 ID (UUID)    | L1-01, L2-02, L2-03(실무형 보강 시 중요)          |
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
