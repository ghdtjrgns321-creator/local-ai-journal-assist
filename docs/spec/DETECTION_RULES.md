# Detection Rules — 감사 검토 후보 선별 룰 전체 목록

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

한국 감사기준서(240호, K-SOX, PCAOB AS 2401)를 근거로 도출한 전표 검토 후보 선별 룰의 단일 참조 문서.
법규·기준서 근거는 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md) 참조.

탐지 파이프라인은 **PHASE1-1(룰 기반 전수 필터) · PHASE1-2(family 전용 탐지기) · PHASE2(VAE companion surface)** 3개 surface로 운영한다. 세 surface는 독립 큐로 두고 단일 점수로 병합하지 않는다(3-surface 불변식).

- **PHASE1-1**은 전표/행 단위 결정론 룰 기반 전수 필터다. 목적은 정답 확정이 아니라 규칙·정책 위반·이상 징후를 1차로 누락 없이 올리는 것이고, 켜진 룰 조합으로 HIGH/MEDIUM/LOW/CONTEXT 순서형 tier를 직접 결정한다(가중합·band컷 폐기). 이후 중요성·증거 강도·정상 예외 가능성·조합 신호로 예외 처리 대상·리뷰 대상·고위험 후보로 2차 분류한다.
- **PHASE1-2**는 graph·relational·시계열 같은 구조 단위 전용 탐지기다(순환거래·직원-거래처 쌍·Benford(L4-02)·D01/D02 macro·L4-05 비정상시간 집중). PHASE1-1을 대체하지 않고 별도 surface로 결합한다.
- **PHASE2**는 정상 분포 비지도 학습(VAE) 단독 surface다. 학습된 정상 밖 비정형을 추가 검토 후보로 올린다(부정 확정 아님). 룰 ID 자체를 예측 feature로 쓰지 않는다.
- **PHASE3 LLM Narrator**는 active detector layer가 아니다. Detection rules are PHASE1/PHASE2 only. Any future semantic description analysis must be local-first and must not transmit ledger evidence to external APIs. 단일 출처: [LOCAL_FIRST_EVIDENCE_POLICY.md](LOCAL_FIRST_EVIDENCE_POLICY.md), deprecated spec [PHASE3_REVIEW_NARRATOR_SPEC.md](../archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md).

---

## 1. 개요

이 문서는 **PHASE1-1 룰 카탈로그**다 — 전표/행 단위 결정론 룰(L1~L4)의 정의·근거·구현·필요 컬럼을 룰별 카드(§2.1~§2.4)로 싣는다. 운영 프레임워크(tier 발화·점수·큐·단위·묶음)는 본 문서가 보유하지 않고 아래 SoT에 위임한다.

| 주제                                        | SoT                                                                |
| ------------------------------------------- | ------------------------------------------------------------------ |
| HIGH/MEDIUM/LOW/CONTEXT tier 발화 조합·근거 | [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md)                 |
| tier 단위(전표=document)·분모/분자 측정     | [UNIT_MEASUREMENT_POLICY.md](UNIT_MEASUREMENT_POLICY.md)           |
| 점수 정규화·sort_key·band 매핑              | [PHASE1_TIER_SCORING_SPEC.md](PHASE1_TIER_SCORING_SPEC.md)         |
| 룰 수(29 canonical)·canonical ID            | [RULE_DETAIL_METADATA_V1_LOCK.md](RULE_DETAIL_METADATA_V1_LOCK.md) |

### 1.1 룰 레이어 — L1/L2/L3/L4

PHASE1-1 룰은 전표/행 단위로 L1~L4로 분류한다(내부 분류이며 사용자 노출 등급은 순서형 tier).

- **L1** 확정 오류/명시 위반 — 전표 품질·통제·시점 게이트
- **L2** 강한 검토 신호 — 통제 우회·중복·자금 유출
- **L3** 검토 필요 이상징후 — 시간·텍스트·운영 맥락
- **L4** 통계적 이상치 — 분포·희소성

Benford(L4-02)·D01/D02·L4-05는 PHASE1-2 family/macro로 이관(별도 문서, §3). 데이터정합성(L1-01·L1-02·L1-03)은 부정 tier에 미산입하고 `data_integrity_findings`로만 노출한다.

---

## 2. PHASE1-1 룰 카드 (L1~L4)

### 2.1 L1: 확정 오류/명시 위반 (9개)

전표테스트의 전제조건. 이 검증을 통과해야 이후 탐지가 의미있음.

> **번호 ≠ 분류**: `L1~L4`는 탐지 레이어의 **내부 안정 키**(코드·DB·DataSynth 라벨에서 불변)일 뿐, 감사인에게 보이는 분류가 아니다. 의미 분류는 `evidence_type/topic/theme`와 트랙(§2.0.3·§2.0.5)이 담당한다. 따라서 같은 `L1` 안에도 성격이 다른 두 묶음이 있다:
> - **L1-01·L1-02·L1-03 = 데이터정합성 트랙** — 부정 tier가 아니라 데이터 품질 게이트. case queue/priority 미산입, `data_integrity_findings`로만 노출.
> - **L1-04~L1-08 = 통제·시점 신호** — 승인우회(L1-04/05/06/07/07-02)는 `control_failure`, 기간불일치(L1-08)는 `closing_timing`(+정합성 dual) topic으로 흐른다.
> rule_id 자체를 재명명하지 않는 이유: 키 변경은 15개 모듈·config·테스트·DataSynth 라벨·DB를 깨뜨리고 탐지상 이득이 없다(분류는 theme/track 레이어가 이미 수행).

#### L1-01 — 차대변 균형 (UnbalancedEntry) ✅ 【데이터정합성 트랙】

- **심각도**: 5
- **근거**: 240§32 복식부기 원칙. FSS 횡령은폐 수법(차대 불일치)
- **탐지 로직**: `abs(sum(debit) - sum(credit)) > tolerance` per document_id. 기본 허용 오차 1.0 (float 안전)
- **평가/라벨 기준**: L1-01은 원인 라벨이 아니라 구조 게이트다. DataSynth truth와 성능 평가는 `UnbalancedEntry` 라벨명만이 아니라 실제 전표 합계 불균형 여부를 L1-01 positive 기준으로 삼는다. 원인 라벨(`RoundingError`, `TransposedDigits`, `DecimalError`, `CurrencyError`, `ReversedAmount` 등)은 별도 audit issue로 유지할 수 있다.
- **row score**: flagged 행은 모두 `score_series = 1.0`이다. L1-01은 부정 tier 세기차등이 아니라 데이터 정합성 트랙이므로 이 값은 발화/표시용 uniform flag이며 row `HIGH/MEDIUM/LOW` tier와 case priority에는 병합하지 않는다.
- **정렬/표시 메타**:
  - `imbalance_amount = abs(sum(debit_amount) - sum(credit_amount))`
  - `debit_sum = sum(debit_amount)`
  - `credit_sum = sum(credit_amount)`
  - `_build_data_integrity_findings`는 L1-01을 `imbalance_amount` 내림차순 기준으로 노출한다.

- **구현**: `integrity_layer.py` → `_a01_unbalanced_entry()`
  - document_id별 groupby → diff 계산
  - NaN document_id는 개별 더미 키로 처리
  - `score_series`는 uniform `1.0`
  - `row_annotations`에는 `imbalance_amount`, `debit_sum`, `credit_sum`만 저장한다.
- **필요 피처**: `debit_amount`, `credit_amount`, `document_id`

#### L1-02 — 필수필드 누락 (MissingField) ✅ 【데이터정합성 트랙】

- **심각도**: 2
- **근거**: 240-A45(d) 계정번호 없이 입력. K-SOX 전표기록 통제
- **탐지 로직**: 필수(cat1∪cat2) 컬럼 중 하나라도 NULL 또는 공백 문자열이면 행 단위로 플래그한다.

| 카테고리 | 의미                     | 컬럼                                                                             | L1-02 플래그 |
| -------- | ------------------------ | -------------------------------------------------------------------------------- | ------------ |
| `cat1`   | 없으면 저널 성립 불가    | `document_id`, `gl_account`, `debit_amount`, `credit_amount`, `posting_date`     | 예           |
| `cat2`   | 없으면 일부 룰 실행 불가 | `company_code`, `fiscal_year`, `fiscal_period`, `document_date`, `document_type` | 예           |
| `cat3`   | 없어도 무방              | 위 10개 외 모든 컬럼                                                             | 아니오       |

- **row score**: flagged 행은 모두 `score_series = 1.0`이다. 누락 필드 수나 필드별 가중치로 세기차등하지 않는다.
- **row annotation**:
  - `missing_fields`: 누락된 cat1/cat2 필드 리스트
  - `missing_category`: cat1 누락이 하나라도 있으면 `1`, 아니면 `2`
- **PHASE1 case priority 반영**: L1-02는 데이터 정합성 트랙이다. 단독 hit는 위험 큐/floor 대상이 아니며, `_build_data_integrity_findings`에서 `missing_category` 오름차순(cat1 먼저)으로 노출한다.

- **구현**: `integrity_layer.py` → `_a02_missing_required()`
- **필요 피처**: `document_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_date`, `document_date`, `document_type`, `gl_account`, `debit_amount`, `credit_amount`
- **DataSynth 상태**: MCAR 2% 주입 추가됨, E2E 재검증 필요

#### L1-03 — 무효 계정 (InvalidAccount) ✅ 【데이터정합성 트랙】

- **심각도**: 3
- **근거**: 240-A45(a) 비경상·저사용 계정 + 315호 비정상계정. FSS 가공전표(미사용계정 악용)
- **탐지 로직**: `gl_account NOT IN chart_of_accounts`
  - CoA(계정과목표) 미제공 시 스킵
  - 공란/NULL 계정은 L1-03이 아니라 L1-02 필수필드 누락이 소유한다.
- **row score**: CoA에 없으면 flagged 행 모두 `score_series = 1.0`이다. 계정 코드 형태, placeholder 여부, 금액, 수기/기말 맥락으로 세기차등하지 않는다.
- **출력**: `row_annotations`에는 `gl_account`만 남긴다. `bucket`, `reason_code`, `context_reasons`, `document_amount`, `score_bands`는 사용하지 않는다.
- **구현**: `integrity_layer.py` → `_a03_invalid_account()`
- **필요 피처**: `gl_account`
- **DataSynth 상태**: `v126` 기준 CoA 밖 GL은 `InvalidAccount`가 소유한다. `MisclassifiedAccount`가 CoA 밖 GL을 사용해 L1-03을 오염시키는 케이스는 `0`건이며, `check_datasynth_required_truth.py`에서 승격 전 검증한다.

#### L1-04 — 승인한도 초과 (ExceededApprovalLimit) ✅ 【승인우회 트랙】

- **심각도**: 3
- **의미**: 승인자가 **자기 권한을 벗어나 승인**한 전표를 잡는다. 두 경우를 **모두** 본다:
  1. **한도 초과** — 승인자에게 한도가 있는데 전표 총액이 그 한도를 넘음
  2. **비승인권자 승인** — 직원 마스터에 **있는 실재 직원**인데 승인 권한이 없거나(`can_approve_je=false`) 한도가 설정되지 않은 사람이 승인함
  > 즉 "한도를 넘긴 승인"뿐 아니라 **"애초에 승인할 자격(한도)이 없는 실재 직원이 승인한 경우"도 L1-04가 잡는다.**
  > 단, **승인자 ID가 직원 마스터에 아예 없는(가짜·유령) 경우는 L1-04 아님 → L1-07-02 유령 승인자** 소관(실재 직원의 권한초과와 존재하지 않는 ID는 구분, 2026-06-19).
- **근거**: K-SOX 승인체계, ISA 240 §32. 승인권자가 권한 범위를 벗어나 승인하면 통제 실패·승인권한 위반.
- **판정 (binary flag — 점수 단계 없음)**
  - 전표 총액 = `max(SUM(debit_amount), SUM(credit_amount)) BY document_id`.
  - `approved_by`를 직원 마스터(`employees.json`)에 연결해 `approval_limit`·`can_approve_je`를 조회.
  - 아래 중 하나면 flag(균일):
    - ① 승인자 한도 존재 **AND** 전표 총액 > 한도
    - ② **명부에 있는 실재 직원**인데 승인 권한 없음(`can_approve_je=false`) **또는** 한도가 설정되지 않음 (= **한도 없는 사람의 승인**)
  - **`approved_by` 공란**이면 L1-04 아님 → **L1-07 승인 생략** 소관(승인자 부재와 권한초과는 구분).
  - **승인자 ID가 직원 마스터에 없음**(`approver_in_master=false`)이면 L1-04 아님 → **L1-07-02 유령 승인자** 소관. (구 L1-04 `approver_in_master` 가지는 L1-07-02로 이관 — 2026-06-19)
- **tier로 흐르는 길**: L1-04 단독은 통합점수에서 **LOW**(검토). 다른 행위신호(고액·역분개·수기·결산 등)와 **조합될 때만 HIGH**. (구 버킷 점수·단독 HIGH floor `approval_control_high` 폐기 — 2026-06-17)
- **파생 컬럼**: `document_approval_amount`(전표 총액), `approver_limit_amount`(한도, 미조회 시 null), `approval_limit_resolved`(조회 성공 여부), `approver_can_approve_je`(승인권한 여부), `approval_excess_amount`(초과액)
- **구현**: `src/feature/amount_features.py::add_exceeds_threshold` + `src/detection/fraud_rules_feature.py::b03_exceeds_threshold`. 직원 한도: `employees.json`의 `user_id`/`approval_limit`/`can_approve_je`.
- **필요 컬럼**: `document_id`, `debit_amount`, `credit_amount`, `approved_by`, `approval_limit`(마스터), `can_approve_je`(마스터)

#### L1-05 — 자기 승인 (SelfApproval) ✅ 【승인우회 트랙】

- **심각도**: 3
- **근거**: K-SOX 직무분리(외감법 §8①5호). 1인이 입력+승인을 모두 수행하면 통제가 뚫린다(FSS 오스템임플란트 사례).
- **판정 (binary flag — 점수 단계 없음)**
  - `created_by`·`approved_by`가 모두 있고 `created_by == approved_by`이면 자기승인 → flag(균일).
  - `approved_by` 공란이면 자기승인으로 추정하지 않음(승인 누락은 → **L1-07**).
  - 시스템 자동처리는 제외하되 **위장 의심 행은 제외하지 않는다**(아래 특별룰).
- **tier로 흐르는 길**: L1-05 단독은 통합점수에서 **LOW**(검토). 다른 행위신호와 **조합될 때만 HIGH**. (구 review/immediate/escalated 점수 분리·금액/시점/민감계정 승격 로직 폐기 — 그 신호들은 통합점수체계에서 각자의 룰 L4-03·L3-05/06·L3-10이 담당하므로 L1-05 안에서 중복 판단하지 않음)

- **특별룰 — 위장 시스템 전표 잡아내기 (`source_trust.lone_automated_mask`)**
  - 누군가 `source`를 'system/automated'로 적어 자기승인을 빠져나가려는 **위장**을 막는 안전장치. 다음이면 **위장 의심**으로 보고, 시스템 자동 예외(allowlist)를 적용하지 않고 일반 사람 자기승인으로 평가한다:
    - **자동 계열**(`patterns.self_approval_allow.sources` — 기본 `automated`·`recurring`) **AND** [ `batch_id` **또는** `job_id`가 비어 있음 **OR** 같은 날 같은 부류(자동) 전표가 **10건 이하로 외톨이** ]
  - 발상: **정상 자동 전표는 항상 무리지어 다닌다** — 시스템 배치는 `batch_id`/`job_id`를 달고 한 번에 대량으로 쏟아진다. 식별자도 없고 무리도 없는 외톨이 자동 전표 = 사람이 손으로 'system'이라 적은 위장 의심.
- **시스템 제외 (위장이 아닐 때만)**: `user_persona==automated_system` 또는 `source` allowlist(`patterns.self_approval_allow.sources`)면 점수 0(큐 제외). 위 위장 의심이면 이 제외가 취소된다.
- **구현**: `src/detection/fraud_rules_access.py::b06_self_approval` (+ `src/detection/source_trust.py::lone_automated_mask`)
- **필요 컬럼**: `created_by`, `approved_by`, `source`, (위장 판정용 `batch_id`/`job_id`/`posting_date`)

#### L1-06 — 직무분리 위반 (SegregationOfDutiesViolation) ✅ 【승인우회 트랙】

- **심각도**: 4
- **근거**: K-SOX 직무분리 / COSO·내부회계관리제도 원칙10. 양립불가능한 통제 기능이 한 사람에게 모이면 부정 기회·은폐 위험이 커진다.
- **무엇을 잡나 — 주입 라벨 폐기, 데이터에서 도출 (2026-06-17 재설계)**
  - **(구) 폐기**: `sod_violation`·`sod_conflict_type` 주입 컬럼을 그대로 읽던 방식. 실데이터엔 그 컬럼이 없어 0건, 합성데이터엔 정답 베끼기(순환)였다.
  - **(신)**: 전표 본래 3컬럼 — `created_by`(기표자)·`approved_by`(승인자)·`business_process`(업무) — 만으로 도출한다. 한 사람이 한 회기 내에 손댄 업무 집합이 **toxic 업무쌍**을 포함하면 발화.
  - 어떤 쌍이 toxic이고 왜인지(3축 근거 포함)는 **단일 출처** → [SOD_TOXIC_COMBINATIONS_GROUNDING.md](SOD_TOXIC_COMBINATIONS_GROUNDING.md). 데이터(SoT) = `config/sod_toxic_combinations.yaml`.
- **무엇이 RED인가 — 빼돌리기 + 숨기기**
  - 부정이 완성되려면 두 능력이 동시에 필요하다: **빼돌리기(custody — 현금·자산을 직접 만짐)** + **숨기기(recording/reconciliation — 그걸 장부에서 가림)**.
  - **RED = 한 사람이 빼돌리기 + 숨기기를 둘 다 가짐.** 가져가고 동시에 덮을 수 있어 통제 결함이 중대 → L1-06 **정식 발화(primary)**. 단독은 통합점수 **LOW**(검토), 행위신호와 **조합 시 HIGH**.
  - **YELLOW = 둘 중 하나만**(자산 못 만짐 / 못 숨김 / 저유동 자산). 반쪽 결함이라 **점수 미참여 — 리뷰 노트로만 기록**(단독으로 큐에 안 뜸).
  - 분류: **RED 8** (TRE+P2P·TRE+R2R·TRE+O2C·O2C+R2R·H2R+TRE·A2R+R2R·P2P단독·TRE단독), **YELLOW 4** (P2P+R2R·H2R+R2R·A2R+TRE·MFG+R2R). 각 쌍의 빼돌리기/숨기기 분해는 SOD doc의 RED/YELLOW 절.
  - ⚠️ **추정 단정 금지**: toxic 쌍 발화는 "이 사람이 가짜 거래를 만들었다"는 부정 확정이 아니라 **"빼돌리고 숨길 수 있는 통제 결함이 있다 → 감사인이 봐야 한다"** 는 신호다.
- **탐지 단위**: person = `created_by`(자기승인 `created_by==approved_by`면 승인자도 동일인 집합). 회기 내 `business_process` 집합이 toxic 쌍 포함 시 해당 프로세스 행 flag.
- **자동/시스템 계정 제외 (사람 행위만 SoD 대상)**
  - 직무분리는 **사람**에 대한 통제다. 자동 배치·인터페이스는 분리할 직무 자체가 없으므로(프로그래밍된 전기일 뿐) SoD 모집단에서 제외한다. 시스템 계정을 포함하면 "한 배치 계정이 모든 업무를 찍음 → 전 프로세스 toxic"으로 **전수 오탐**이 난다.
  - 제외 기준(`patterns.sod_human_filter`): ① `user_persona == automated_system`, ② `source`가 시스템 계열(`automated`/`interface`/`system`/`batch`), ③ `created_by`가 시스템 actor 토큰 포함(`batch`/`system`/`auto`/`interface`/`if_`/`svc_`/`_svc`). 셋 중 하나라도 해당하면 toxic 쌍 판정에서 빠진다.
  - 사람 식별 컬럼(`user_persona`/`source`)이 없으면 보수적으로 사람 행위로 본다(필터는 있는 신호로만 좁힌다). 식별자 표기 정규화·예외는 향후 과제.
- **경계 (다른 룰과 중복 금지)**
  - 단순히 한 사람이 여러 업무를 본다(업무범위 넓음)는 것은 L1-06 아님 → **L3-12 업무범위 집중**.
  - 자기승인(L1-05)·승인생략(L1-07)·수기(L3-02)를 근거로 L1-06을 발화하지 않는다(각자 소관). L1-06은 독립적 toxic 쌍 구조만 본다.
- **구현**: `src/detection/fraud_rules_access.py::b07_segregation_of_duties` — YAML toxic pair를 데이터에서 도출. RED → `score_series=1.0`(primary). YELLOW → `score_series=0.0` + `row_annotation`에 `toxic_pair`·`signal_class` 기록(노트).
- **필요 컬럼**: `created_by`, `approved_by`, `business_process` (+ `config/sod_toxic_combinations.yaml`)

#### L1-07 — 승인 생략 (SkippedApproval) ✅ 【승인우회 트랙】

- **심각도**: 4
- **근거**: K-SOX 승인절차(외감법 §8②). FSS 오스템임플란트: 한도초과+승인없음 = §8② 직접 위반.
- **판정 (binary flag — 점수 단계 없음)**
  - `approved_by`가 **공란**이면 flag(균일). 승인 도장 없이 장부에 들어온 전표.
  - `approved_by` 컬럼 자체가 없으면 승인 생략으로 추정하지 않고 skip/coverage degraded로 본다(컬럼 부재 ≠ 승인자 누락).
  - 공란이면 **무조건** flag한다 — 시스템·반복 전표의 공란까지 포함. 승인불요·사전승인·대체승인 가능성으로 룰 안에서 점수를 차등하지 않고, 단독은 통합점수 LOW로 흡수되게 둔다(구 7컴포넌트 가중합·즉시/검토/낮음 밴드·critical/high/review/low score band·case floor 전부 폐기 — 2026-06-19).
- **tier로 흐르는 길**: L1-07 단독은 통합점수에서 **LOW**(검토). 승인우회 그룹의 primary로서 다른 행위신호와 **조합될 때만 HIGH** — `approval_bypass_high`·`embezzlement_concealment_high`의 bypass seed `(L1-04|L1-05|L1-06|L1-07|L1-07-02)`에 속한다.
- **구현**: `src/detection/fraud_rules_access.py::b09_skipped_approval`
- **필요 컬럼**: `approved_by`

#### L1-07-02 — 유령 승인자 (UnknownApprover) ✅ 【승인우회 트랙】

- **심각도**: 4
- **무엇을 잡나**: `approved_by`가 **비공란인데 그 ID가 직원 마스터(`employees.json`)에 없는** 행. 존재하지 않거나 퇴사한, 또는 가짜로 적힌 ID를 승인자로 기입해 승인통제를 회피한 전표.
- **L1-07과의 차이**: L1-07(공란)은 승인을 **빠뜨린 것**(omission), L1-07-02(가짜 ID)는 없는 이름을 **적어 넣은 것**(fabrication) — "숨기기" 성격이 강한 위조 신호다. 그래서 별도 rule_id로 분리해 위조 전용 조합에 쓸 수 있게 한다(2026-06-19 신설, 구 L1-07 `unknown_approver` 서브패턴 승격).
- **판정 (binary flag — 점수 단계 없음)**: feature `approver_in_master`(`amount_features._compute_approver_info` — `employees.json`의 `user_id` 멤버십; 공란→NA, 비공란인데 미존재→False)가 False **∧** `approved_by` 비공란이면 flag(균일). 구 고정 `0.55` 검토점수 폐기. 직원 마스터가 없으면 컬럼 미생성으로 graceful 비활성(L1-07 공란 경로는 불변).
- **tier로 흐르는 길**: 단독은 통합점수 **LOW**(검토). 승인우회 그룹의 primary로 `(L1-04|L1-05|L1-06|L1-07|L1-07-02)`에 합류 → 다른 행위신호와 **조합 시 HIGH**. 위조 성격상 역분개(L2-05)·가공거래·기말조정과 결합될 때 우선한다.
- **L1-04와의 경계 (중복 발화 방지)**: 한도검사(L1-04)는 **명부에 있는 실재 직원**의 권한/한도 위반만 본다. **명부에 아예 없는** 가짜 ID는 L1-04가 아니라 L1-07-02 소관이다. L1-04의 `approver_in_master` 가지는 L1-07-02로 이관한다(2026-06-19).
- **운영 해석**: 부정 확정이 아니라 승인권자 명부와 대조할 검토 후보다. 퇴사자·외부 컨설턴트·표기 차이(대소문자)·마스터 부분추출로 정상일 수 있으므로 annotation에 승인자 값을 노출해 감사인이 대조·종결하게 한다(합성데이터에선 0건). 시점 정합(마스터 유효기간)·표기 정규화는 향후 과제(OPEN_ISSUES #19).
- **구현**: `src/detection/fraud_rules_access.py` → `b09b_unknown_approver()` (L1-07 `b09_skipped_approval`에서 분리). 파생: `src/feature/amount_features.py::_compute_approver_info`의 `approver_in_master`.
- **필요 컬럼**: `approved_by`, 파생 `approver_in_master`(`employees.json` 필요)

#### L1-08 — 기간 불일치 (WrongPeriod) ✅

- **심각도**: 4
- **근거**: 240§32(b) 기간귀속 적정성
- **이중 트랙 (정합성 + 부정)** — L1-08만 양 트랙에 싣는다
  - 같은 표면신호(`fiscal_period_mismatch=True`)가 두 원인을 가린다: ① 오타·ERP 매핑 오류(의도 없음) ② 의도적 기간 조작(cutoff). 플래그만으로는 구분 불가하므로 한 플래그를 두 surface가 다르게 소비한다. L1-01(차대불일치)·L1-02(필수필드)는 부정 조합 의미가 약해 정합성 단독이지만, 기간불일치는 cutoff fraud의 정통 수법이라 L1-08만 dual이 정당하다.
  - **정합성 트랙 (raw 전수)**: 결산조정·특수기수 포함 **raw mismatch 전부**를 데이터 품질·coverage 지표로 집계한다. "기간 귀속 점검 필요" 경고이며 **부정 priority_score에는 합산하지 않는다**(별도 surface·집계). `Integrity / Coverage Blockers`(L1-01·L1-02와 동일 묶음)로 표시.
  - **부정 트랙 (정책예외 제외 final)**: 결산조정·특수기수(`13~16`)처럼 정책으로 확인된 합법 예외를 제외한 **final mismatch만** `closing_timing` topic의 seed로 쓴다. `period_end_adjustment_high (L3-04|L3-07|L3-11|L1-08) & (L3-10|L4-04)`의 seed이며, **단독으로는 HIGH/MEDIUM을 만들지 못하고**(조합 없으면 부정 LOW), 반드시 2차신호(`L3-10|L4-04`) 동반 시에만 HIGH로 발화한다.
  - **이중계산 아님**: 정합성=전수 행 집계(품질지표, priority_score 미유입), 부정=per-case 조합 기여. 플래그는 한 번 켜지고 소비자 둘이 다른 입도로 읽을 뿐 같은 점수를 두 번 더하지 않는다.
  - **라벨 분리 가드**: "데이터 품질: 기간귀속 점검"(정합성)과 "부정후보: cutoff 조작"(부정)을 같은 화면에서 섞지 않는다. 감사인이 오타를 조작으로 오인하지 않도록 surface·큐 라벨을 분리한다.
  - **binary 정합**: L1-08은 이미 `True/False` 단일 플래그라 점수 버킷이 없다. dual-track은 "점수를 나눈다"가 아니라 "같은 binary 플래그를 두 surface가 다르게 소비한다"이므로 binary 원칙과 충돌하지 않는다. raw/final의 차이는 점수 차등이 아니라 **정책예외 필터 적용 여부**다.
- **현재 코드 기준 탐지 로직**
  - 기본 최종 룰은 `fiscal_period_mismatch == True`일 때 `WrongPeriod`로 탐지한다.
  - 이 플래그는 단순히 `month(posting_date)`와 바로 비교하지 않고, 회사 회계연도 시작월 `fiscal_year_start`를 반영해 기대 기수를 먼저 계산한 뒤 비교한다.
  - 계산식은 `expected_period = (posting_month - fiscal_year_start) % 12 + 1` 이다.
  - 즉 표준 회계연도(`fiscal_year_start=1`)에서는 사실상 `fiscal_period ≠ month(posting_date)`와 같고, 4월 시작 회계연도처럼 비표준 회계연도에서는 4월=기수1, 5월=기수2, ..., 3월=기수12로 본다.
  - `config/audit_rules.yaml`의 `patterns.fiscal_period_mismatch_policy.strict_mode`가 `true`이면 예외 없이 raw mismatch를 그대로 최종 탐지한다.
  - `strict_mode`가 `false`이면 감사인이 허용한 특수기수, source/document_type/business_process 조건, 업무유형/source별 기준일 예외를 적용한 뒤 남은 건만 최종 L1-08로 탐지한다.
- **사람이 이해할 수 있는 판정 기준**
  - 전기일이 속한 달을 회사의 회계기간 체계로 환산했을 때, 그 전표에 적힌 `fiscal_period`와 다르면 기간 불일치다.
  - 예: `fiscal_year_start=1`에서 `posting_date=2025-01-15`, `fiscal_period=5`이면 불일치다.
  - 예: `fiscal_year_start=4`에서 `posting_date=2025-04-15`, `fiscal_period=1`이면 정상이다.
- **현재 코드가 실제로 잡는 것**
  - 잘못된 회계기간 귀속, 월경 전표 처리 오류, 회계연도 시작월 설정과 맞지 않는 period 기입을 잡는다.
  - 반대로 `posting_date` 또는 `fiscal_period`가 비어 있어 비교 자체가 불가능한 건은 `pd.NA`로 두고, 최종 룰에서는 탐지하지 않는다. 즉 "비교 불가"와 "불일치"를 구분한다.
- **예외 가능성과 정책 처리**
  - 실무에서는 결산조정 전표, 특수기수(`13~16`), reopen period, closing entry처럼 `posting_date`의 일반 월과 다른 period를 의도적으로 쓰는 경우가 있다.
  - 현재 Phase 1 구현은 원칙적으로 raw mismatch를 보존하고, 고객사 정책으로 확인된 예외만 설정 기반으로 제외한다.
  - 예외 적용 시에도 raw mismatch 건수와 정책 예외 건수는 룰 결과 metadata에 남겨 감사 trail로 확인할 수 있게 한다.
- **운영 원칙**
  - Phase 1에서는 룰을 단순하고 설명 가능하게 유지하기 위해 기본 불일치 신호만 잡는다.
  - 결산/특수기수 예외는 고객사가 회계정책 또는 ERP 운영정책으로 문서화한 경우에만 `fiscal_period_mismatch_policy`에서 허용한다.
  - 예외를 조용히 삭제하지 않고 raw signal과 final signal을 분리해서 해석한다.
- **구현**: `anomaly_rules_simple.py` → `c05_fiscal_period_mismatch()`
- **피처 생성**: `time_features.py` → `add_fiscal_period_mismatch()`
- **필요 피처**: `fiscal_period`, `posting_date`
  - 피처 생성 후 최종 룰은 `fiscal_period_mismatch`를 사용한다.
  - 예외 정책을 쓰려면 선택적으로 `document_date`, `source`, `document_type`, `business_process`가 필요하다.
  - 현재 `AnomalyDetector` 레이어 실행 전제상 `debit_amount`, `credit_amount`가 없으면 레이어 전체가 실행되지 않는다. 이는 L1-08 판정 로직 자체의 입력이 아니라 레이어 공통 실행 조건이다.
- **튜닝 파라미터**: `patterns.fiscal_period_mismatch_policy`
  - `fiscal_year_start`
  - `strict_mode`
  - `allow_special_periods`, `special_periods`
  - `special_period_allowed_sources`, `special_period_allowed_document_types`, `special_period_allowed_business_processes`
  - `period_basis_by_process`, `period_basis_by_source`
- **DataSynth 계약**: `v36_candidate`부터 결산/특수기수 negative control sidecar를 별도로 관리한다.

---

### 2.2 L2: 강한 통제우회·자금유출 검토 신호 (5개)

#### L2-01 — 승인한도 직하 (JustBelowThreshold) ✅

- **심각도**: 3
- **근거**: 240-A45(e) 단수/끝자리, K-SOX 승인체계
- **의미**: 승인 대상 금액이 결재권자의 승인 한도에 근접해 있을 때, 우연한 분포라기보다 승인 기준을 의식해 금액이 맞춰졌을 가능성을 살펴보는 룰이다. 이 룰 하나만으로 우회라고 단정하지 않고, 승인 정책과 업무 맥락을 함께 본다.
- **임계값 성격 (정직 표기)**: `near_threshold_ratio` 기본값 `0.90`은 **감사기준이 정한 회귀 기준이 아니라 튜닝 가능한 스크리닝 휴리스틱**이다. 원리(한도 직전 금액 맞춤 = 구조화 회피)는 ISA 240 A45(e)·ACFE 패턴에 근거하지만 "90%"라는 컷 자체는 임의값이며, engagement 승인한도 구조에 맞춰 조정한다. 더 통계적인 **"한도 직하 거래 밀집도(density spike) 검정"**(기대 분포 대비 한도 직하 구간 건수 스파이크)은 전표 단위 flag가 아니라 모집단 단위 분석이므로 **PHASE1-2 MACRO에 추후 반영 예정**이다(SoT [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD)).
- **판정 방식**
  - 같은 `document_id`의 `max(SUM(debit_amount), SUM(credit_amount))`로 전표 승인 대상 금액을 계산한다.
  - 전표의 `approved_by`를 직원 마스터(`employees.json`)와 연결해 해당 승인자의 `approval_limit`를 조회한다.
  - 전표 총액이 그 승인자의 한도에 충분히 가깝지만 아직 넘지 않은 경우, 즉 `approval_limit × near_threshold_ratio <= 전표 총액 < approval_limit` 이면 `JustBelowThreshold`로 본다.
  - 기본 `near_threshold_ratio`는 `0.90`이다. 실무 해석으로는 "승인 한도의 90% 이상 100% 미만 구간"이다.
- **Fallback 원칙**
  - fallback은 사용하지 않는다.
  - `approved_by`가 없거나 직원 마스터 조인에 실패해 실제 `approval_limit`를 알 수 없는 행은 `L2-01`로 판정하지 않는다.
  - `document_id`, `debit_amount`, `credit_amount` 중 하나가 없어 전표 단위 승인 대상 금액을 계산할 수 없는 행도 line-level 금액으로 대체하지 않는다.
  - 이런 행은 부정 판정 결과가 아니라 "승인한도 검증 불가"라는 커버리지/데이터 품질 이슈로 별도 관리한다.
- **판정 (binary flag — 점수 단계 없음)**
  - `한도 × near_threshold_ratio ≤ 전표총액 < 한도`이면 **flag 1.0**(균일). 구 3밴드(`lower_band 0.45`/`close_band 0.60`/`razor_band 0.75`)와 전용 정규화(`0.60/0.80/1.00`)는 **폐기**한다 — 한도의 90%든 99%든 "한도 의식해 맞춤"이라는 신호는 동질이고, 근접도 차이는 같은 tier 내부 tiebreak(연속 점수)로만 본다.
  - **자동/배치 전표도 한도 직하면 flag 1.0으로 발화한다.** "source가 automated/batch라서 정상"이라는 정상성 판단은 룰이 하지 않는다 — source/수기 차원은 `L3-02`(수기 전용 룰)와 통합점수체계 소관이고, 통합점수가 `한도직하 + 자동 source`를 정상으로 다운웨이트한다(룰은 멍청하게).
  - 한도 조회 실패 행은 hit 아님(아래 Fallback 원칙).
  - 단독은 통합점수 **LOW**(검토). 동일 거래처·근접기간 반복, L2-03 분할 후보, L1 승인통제 이슈, 수기·기말 신호와 **조합 시 HIGH**.

- **추가 파생 컬럼**
  - `near_threshold_amount`: 전표 단위 승인 대상 금액. `max(SUM(debit_amount), SUM(credit_amount)) BY document_id`로 계산한다.
  - `near_threshold_limit_amount`: 승인자의 실제 승인한도. 조회 실패 시 null
  - `near_threshold_limit_resolved`: 승인자 한도 조회 성공 여부
  - `near_threshold_ratio_to_limit`: 승인 대상 금액 / 승인한도
  - `near_threshold_gap_amount`: 승인한도까지 남은 금액
  - `near_threshold_gap_ratio`: 승인한도까지 남은 비율
- **한 줄 규칙**: `approval_limit(approved_by) × 0.9 <= max(SUM(debit_amount), SUM(credit_amount)) BY document_id < approval_limit(approved_by)`
- **구현**
  - 피처 생성: `src/feature/amount_features.py` → `add_is_near_threshold()`
  - 룰 적용: `src/detection/fraud_rules_feature.py` → `b02_near_threshold()`
    - `score_series`: flag 1.0 (binary, 밴드 점수 폐기)
    - `breakdown`: flagged rows, unresolved limit rows
    - `row_annotations`: amount, limit, ratio, gap
- **필요 컬럼**
  - 피처 생성: `document_id`, `debit_amount`, `credit_amount`, `approved_by`, 직원 마스터 `approval_limit`
  - 룰 적용: `is_near_threshold`
  - 설명 출력: `near_threshold_amount`, `near_threshold_limit_amount`, `near_threshold_ratio_to_limit`, `near_threshold_gap_amount`, `near_threshold_gap_ratio`
- **DataSynth 상태**: `v24_candidate`에서 `approved_by.approval_limit` 기준 라벨로 보정했다.

#### L2-02 — 중복 지급 (DuplicatePayment) ✅

- **심각도**: 3
- **근거**: 240§32 적정성. FSS 횡령은폐: 동일건 이중지급
- **한 줄 설명**: 같은 매입처에 같은 돈을 또 보냈는지 찾는 룰
- **현재 성격**: PHASE1 recall 우선 스크리닝 룰이다. 확정 부정 판정이 아니라 "검토해야 할 지급쌍"을 올린다.
- **PHASE1 탐지 순서**
  1. 지급성 전표 범위를 좁힐 수 있는 컬럼이 있으면 사용한다. `business_process`가 있으면 `P2P`만 보고, `document_type`이 있으면 `KZ` 또는 `KR`만 본다. 둘 다 있으면 `P2P + (KZ/KR)`만 본다. 둘 다 없으면 입력 coverage degraded 상태로 보고 가능한 지급 후보 모집단을 넓게 스크리닝한다.
  2. 거래처 키는 `auxiliary_account_number`를 우선 사용하고, 없으면 `trading_partner`, `vendor_name` 등 대체 컬럼으로 보완한다.
  3. 전표 라인 단위가 아니라 `document_id` 단위로 요약한다. 같은 전표 안의 차변/대변 라인은 중복 지급으로 보지 않는다.
  4. `reference`가 있으면 강한 신호로 본다.
     - 같은 회사/거래처 + 정규화한 `reference` + 거의 같은 금액 + 다른 `document_id`
     - 금액 허용오차는 `min(금액의 2%, 100,000원)`이다. 최소 허용오차는 1원이다.
     - 이 경로는 reference가 같은 청구/증빙을 다시 지급한 가능성을 잡기 위한 것이다.
  5. `reference`가 없으면 게이트를 걸어 fallback 한다.
     - 같은 회사/거래처 + 유사 금액(`min(2%, 100,000원)` 허용오차) + 다른 `document_id` + **90일 이내** 재지급이면 후보로 올린다.
     - (구) blank fallback의 정확 금액(±0) 제약은 **폐기** — 부분지급·수수료 차이로 살짝 다른 재지급도 잡기 위해 강신호와 동일한 ±2% 허용오차를 쓴다.
  6. 단, 같은 거래처/유사 금액이 월 단위로 규칙적으로 3번 이상 반복되면 정기성 지급(균등 분할 시리즈 포함) 가능성이 높다고 보고 fallback에서 제외한다.
- **해석 기준 (강/약 — 점수는 동일 1.0, 게이트만 다름)**
  - **강신호**(`reference` 연결): 같은 청구서를 다시 지급한 가능성에 가까운 강한 중복 신호. **같은 송장 재지급은 시점과 무관하므로 윈도우를 적용하지 않는다.**
  - **약신호**(`reference` 연결 없음): 우연 동액·정기지급 가능성이 있어 90일 윈도우 + 비정기 게이트로 좁힌다.
  - 결과 화면에서는 "중복 확정"이 아니라 "중복 지급 의심 후보"로 노출한다.
- **출력 방식**
  - `L2-02`는 Boolean hit 외에 행 단위 `score_series`, `breakdown`, `row_annotations`를 함께 제공한다.
  - `row_annotations`에는 `reason_code`, `confidence`, `confidence_band`, `matched_document_id`, `partner_key`, `reference_norm`, `amount`, `matched_amount`, `day_gap`을 기록한다.
  - `breakdown`에는 `reference_match_docs`, `mixed_reference_fallback_docs`, `blank_reference_fallback_docs`, `amount_partner_fallback_docs`, `recurring_suppressed_docs`, `partner_key_coverage_ratio`를 기록한다.
  - 거래처 식별자 coverage가 낮으면 `FraudLayer.metadata["coverage_issues"]`에 `partial_input_coverage`로 남기며, 결과 해석은 degraded 상태로 본다.
- **판정 (binary flag — confidence band 폐기)**
  - 아래 경로 중 하나면 모두 **flag 1.0**(균일). 구 5단계 confidence(`reference_match 0.90`/`mixed 0.70`/`amount_partner 0.65`/`blank 0.60`)는 **폐기**한다.
  - **강신호 (송장번호 연결, 윈도우 무관)**: `reference_match`(양쪽 같은 reference + 유사금액 + 다른 전표) 또는 `mixed`(원지급 reference 有 + 재지급 비움).
  - **약신호 (송장번호 연결 없음, 게이트 적용)**: `amount_partner`(reference 서로 다름) 또는 `blank`(둘 다 없음). 같은 회사/거래처 + 유사금액(±2%) + 다른 전표 + **90일 이내** + **비정기**(recurring 아님) 를 모두 충족할 때만 발화.
  - `recurring_suppressed`: 월 3회+ 규칙 반복(균등 분할 포함)은 정기지급으로 보고 **제외(flag 0)**.
  - reason code(reference_match/mixed/amount_partner/blank)는 내부 근거·화면 표시용으로 유지하되 **점수는 1.0 단일**(단일 primary, 역할 충돌 없음).
- **tier로 흐르는 길**
  - L2-02 단독은 통합점수 **LOW**(중복지급 검토 후보). 구 confidence 정규화·`reference_match` Medium floor(`0.45`)는 **폐기** — band별 점수 차등 대신 binary flag 후 **조합으로 tier 결정**.
  - 다른 신호(L1 승인통제·수기·역분개·동일 거래처 근접기간 반복)와 **조합 시 HIGH**(`duplicate_or_outflow`/`embezzlement_concealment` 경로).
  - **구현 반영**: fallback 발화 경로는 통합 루프(`b04_duplicate_payment` 내). 같은 (회사·거래처)에서 document_id가 다르고 **90일 이내**인 후행 문서를 선행 reference 상태로 분기 — 선행 ref 有+후행 공백=`mixed`, 두 ref 다름=`amount_partner`, 둘 다 공백=`blank`(모두 `min(2%,10만원)` 허용오차). 정기 반복(`_l202_recurring_profile`)은 `recurring_suppressed`로 제외. 모든 발화 경로 score 1.0.
- **구현**: `fraud_rules_groupby.py` → `b04_duplicate_payment()`
- **필수 실행 입력**: `posting_date`, `debit_amount`, `credit_amount`
- **필수 판정 키**: 거래처 식별자(`auxiliary_account_number` 우선, 없으면 거래처 대체 컬럼). 거래처 키가 전혀 없으면 hit를 만들지 않고 coverage issue로 남긴다.
- **보강 피처**: `document_id`, `business_process`, `document_type`, `reference`, `company_code`
- **DataSynth 상태**: v113 후보 기준 `rule_truth_L2_02.csv`와 `duplicate_payment_review_population.csv`는 현재 detector raw duplicate-payment review universe다. `DuplicatePayment` 라벨과 `duplicate_payment_pairs*`는 확정 중복 지급 pair subset으로 유지한다. `duplicate_payment_negative_controls*`는 정상 반복/대조군 sidecar이며 strict rule truth에 섞지 않는다.
- **평가 계약**
  - `rule_truth_L2_02`는 Phase 1 후보 모집단이다. reference match, mixed-reference fallback, blank-reference fallback, amount-partner fallback 후보를 모두 포함한다.
  - `DuplicatePayment` 라벨은 확정 중복 지급 subset이다.
  - 탐지기는 지급쌍 후보를 문서 단위로 노출하므로, `reference_match_docs`, `mixed_reference_fallback_docs`, `blank_reference_fallback_docs`를 분리해 해석한다.
  - fallback 후보는 confirmed duplicate payment가 아니라 review candidate지만, Phase 1 strict rule truth에는 포함한다.

#### L2-03 — 중복 전표 (DuplicateEntry) ✅

- **심각도**: 3
- **근거**: 240§32, FSS 가공전표: 동일 전표 반복 = 가공
- **해석 (재정의 2026-06-19 — 명백한 재기표만)**
  - L2-03은 "같은 거래가 두 번 장부에 들어온 **명백한 재기표**"만 잡는다. 정상 영업에서 **드문** 패턴만 남기고, fuzzy 유사·분할처럼 정상이 흔한 패턴은 제외한다(아래).
  - 판별 원칙: 정상에서 흔한 신호(near/분할)는 부정도 쓰지만 정상이 압도적이라 단독 primary 불가 → 폐기/이관. 정상에서 드문 신호(증빙 재기표·완전 복제)만 단독 발화한다.
- **판정 (binary flag — confidence band 폐기)**
  - `fraud_rules_groupby.py` → `b05_duplicate_entry()`. 아래 둘 중 하나면 **flag 1.0**. 구 5종 reason code 중 near/document/split 제거.
    - **(가) 증빙 재기표**: 다른 `document_id` + 같은 `reference` + 같은 `gl_account` + **같은 부호** + 유사 금액(±2%). = 같은 송장을 두 번 기표.
    - **(나) 완전 복제**: 다른 `document_id` + `gl_account`·금액·`posting_date`·거래처·적요·**부호**가 **전부 동일**. = 전표 행을 통째로 복제.
  - **가드(reference 비고유 데이터)**: `reference`가 송장번호가 아니라 배치ID·거래일 등 비고유 값이면 같은 번호가 대량 반복돼 (가)가 폭발한다. reference 반복률이 비정상으로 높으면 (가) 경로를 비활성한다.
  - **폐기**: `near_duplicate`(fuzzy "비슷함" — 정상 거래가 천지라 단독 불가), `document_duplicate`(구조 유사 — 정형 반복 전표와 혼동; reference 일치 시 (가)에 흡수되므로 별도 불필요).
  - **PHASE1-2 이관**: `split_duplicate`(분할 회피)는 한 건만 보면 정상이고 **여러 전표를 묶어 합산해야** 패턴이 드러나는 **구조 단위** 신호다. PHASE1-1 행 단위 결정론 룰이 아니므로 **PHASE1-2 구조화(structuring) 후보로 이관**한다 — 한도 직하 밀집도 macro와 같은 계열(SoT [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD)).
- **tier로 흐르는 길**
  - L2-03 단독은 통합점수 **LOW**(재기표 검토 후보). 구 high/medium/low confidence band, `l203_high_confidence_corroborated` 보정, `priority_adjustments.duplicate_entry` floor(`0.85`/`0.08`/`0.45`)는 **폐기** — band별 점수 차등 대신 binary flag 후 **조합으로 tier 결정**.
  - 통제 실패(L1)·결산/시점 이상(L3)·계정 논리 이상·관계사 구조 같은 독립 신호와 **조합 시 HIGH**(`duplicate_or_outflow`/`embezzlement_concealment` 경로).
- **운영 원칙**
  - 외부 노출 라벨은 계속 `L2-03 중복 전표` 하나로 유지한다.
  - UI, export, review queue에는 `reason_code`((가)/(나)), 핵심 근거 필드(`reference`, 거래처, 금액, 날짜, 적요)를 함께 제공한다(구 confidence 표기 폐기).
  - 정상 반복 전표·내부거래·정산성 전표는 (가)(나) 정의(같은 부호·전부 동일·증빙 일치)상 대부분 자연 배제된다.
  - `P2P/KZ` 지급성 전표가 함께 걸리면 `L2-02 duplicate payment`와 병합 설명을 제공한다.
- **Phase 2 pair similarity artifact**
  - `DuplicateDetector.detect()`는 row scoring 후 [`build_duplicate_pair_artifact`](../../src/detection/duplicate_pair_features.py)를 호출해 `result.metadata["pair_artifact"]`에 bounded·sanitized pair payload를 주입한다. row score 식과 `details`/`rule_flags`/`scores` contract는 변동 없음 (KPI baseline 회귀 0).
  - 대용량 입력이 `duplicate_pair_artifact_max_rows`를 초과하면 artifact를 전부 비우지 않고, duplicate row score가 실제로 발생한 review candidate row를 bounded subset으로 잡아 동일 pair generator를 다시 실행한다. 이 경로도 left/right pair evidence가 생성된 경우에만 native DuplicateCase 후보가 된다.
  - metadata top-N 보존은 document diversity cap을 적용한다. 동일 문서 또는 동일 문서쌍의 반복 pair가 감사인 review surface를 독점하지 않게 하기 위한 artifact-only 정책이며, row score, PHASE1 priority, PHASE2 family ranking은 변경하지 않는다.
  - `duplicate_pair_artifact_selection_strategy` 기본값은 `document_diversity`다. Phase 4 후보 `evidence_diversity`와 retention candidate script의 추가 selector들은 pair score, strong/moderate evidence tier, same-partner/reference/text support, 반복 document/document-pair 완화를 사용해 artifact retention만 비교한다. truth label, scenario, PHASE1 priority/composite/ranking, PHASE2 family fusion은 입력으로 쓰지 않는다.
  - Phase 4 후보들은 diagnostic-only이며 production default selector가 아니다. candidate weight는 fixed exploratory diagnostic weight로 기록하고, cross-batch/fixture validation 전까지 product ranking policy로 적용하지 않는다.
  - case-order companion surface 후보도 diagnostic/export sidecar 비교에 한정한다. fixed4/fixed5 cross-batch 진단에서 UI TOP100 안정성과 broader pair evidence export를 분리하는 방향은 유지됐지만, 별도 승인 전 production case ordering이나 family fusion으로 적용하지 않는다. schema 후보는 raw document_id/row_id/index_label/phase2_case_id를 저장하지 않고 tier/rule 분포와 coverage count만 저장한다.
  - export sidecar burden 진단상 개별 case 필터보다 rule/tier 또는 rule/tier/similarity grouped summary가 더 안정적인 후보다. grouped summary는 raw pair/document id를 저장하지 않고 aggregate group count와 coverage count만 저장하며, drilldown 대표 evidence unit은 별도 bounded contract가 필요하다.
  - raw row score hit가 있으나 `top_pairs`가 비거나 case-grade pair가 없으면 `pair_artifact.coverage`와 `duplicate_case_builder_diagnostics`에 원인을 남긴다. 예: 후보 subset 부재, size cap, weak pair evidence tier, df index join 실패.
  - 한계는 [`phase2_reorgani.md` §3 duplicate](phase2_reorgani.md) 참조. pair_artifact는 evidence/attribution 보강용이며 row score 가중치로 사용하지 않는다.
- **DataSynth 상태**
  - `v26_candidate`에서 `DuplicateEntry` / `ExactDuplicateAmount` 라벨을 실제 복제 결과 문서(`duplicate_document_id`) 기준으로 보정했다.
  - 현재 기준 recall은 확보했지만, unrelated false positive가 남아 있어 confidence와 review queue 운영으로 좁혀야 한다.
- **필요 피처**
  - 최소: `document_id`, `gl_account`, `debit_amount`, `credit_amount`, `posting_date`
  - 실무형 보강: `reference`, 거래처 식별자, `line_text`, `business_process`, `document_type`, `company_code`
  - `document_id`는 같은 전표 내부 라인을 중복으로 보지 않고, 서로 다른 전표끼리만 비교하기 위한 필수 식별자다.
- **평가 계약**
  - `DuplicateEntry` / `ExactDuplicateAmount` 라벨은 confirmed duplicate subset이다.
  - `v115_candidate`부터 `rule_truth_L2_03*`와 `duplicate_entry_review_population*`은 현재 `b05_duplicate_entry()` detector output으로 재생성한 raw candidate universe다. 현재 문서 수는 `105`건이다.
  - `v118_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v118`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
  - L2-03 raw candidate에는 score 0의 정상/루틴 중복 형태도 포함될 수 있다. 이들은 `queue_label=normal_duplicate_population` 또는 `routine_duplicate_review`로 구분하고, confirmed fraud label과 동일하게 해석하지 않는다.
  - `duplicate_entry_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `duplicate_entry_confirmed_scenarios*`와 `duplicate_entry_negative_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - (구) high/medium/low confidence band 해석은 binary 재정의(2026-06-19)로 폐기. raw candidate는 (가)증빙 재기표·(나)완전 복제 발화 여부로만 본다.
  - 따라서 L2-03 raw hit 전체를 단일 precision/recall 합불격으로 해석하지 않는다.

#### L2-04 — 비용 자산화 (ExpenseCapitalization) ✅

- **심각도**: 4
- **근거**: 240§32, FSS 분식회계: 개발비 과대자산화
- **한 줄 설명**
  - 비용으로 나가야 할 금액이 자산으로 넘어간 것처럼 보이는 전표를 찾는 룰이다.
- **판정 (binary flag — 점수 단계·자동 제외 폐기, 2026-06-19 재정의)**
  - 회사 설정(`audit_rules.yaml`)의 `자산 계정 prefix`·`비용 계정 prefix`로, 같은 `document_id` 안에서 **자산 차변 합 ≈ 비용 대변 합**(1:1 또는 분할 합계, ±오차)이면 **flag 1.0**. 매칭된 자산/비용 라인만 올린다.
  - = 비용을 자산으로 옮긴(재분류) 모양. 정상 자산 취득(`자산 차변 / 현금 대변`)은 비용 대변이 아니라 안 걸린다.
- **자동 제외·가감 폐기 (핵심)**
  - 구 적요 키워드 가감(개발/구축/software 감점, 수선/복리후생/수수료 가점, 수기 source 가점, AA/FA 문서유형 감점)과 `immediate/review/low/population` 밴드를 **전부 폐기**한다.
  - 이유 ①: 적요·계정·문서유형은 **회사마다 제멋대로** 써서 거를 근거가 못 된다(L2-01 90% 휴리스틱과 같은 한계).
  - 이유 ②(중요): "개발/구축 감점"은 이 룰의 **핵심 부정 타깃인 개발비 과대자산화(근거: FSS 분식회계)를 단어 보고 자동으로 숨기던 역설**이었다. 거르려다 진짜 부정을 가렸다.
  - 따라서 매칭이면 무조건 띄우고(검토 트리거), **자본화가 옳은지는 감사인이 증빙으로 판단**한다. 룰은 자동 분류를 시도하지 않는다.
- **성격·tier**
  - 검토 트리거(부정 확정 아님). 감사인은 외부인이라 전표만으로 자본화 정당성을 확정 못 한다 → "이거 봐라"까지만.
  - 단독이 LOW냐, 다른 신호와 조합해 HIGH냐는 **통합점수체계가 결정**한다(룰은 binary flag만 내고 조합에 관여하지 않는다).
  - `row_annotations`에는 매칭된 자산/비용 라인·금액 근거를 남긴다.
- **합성데이터 평가**: family 라벨 기준 recall은 높지만 subtype 단독 기준 precision은 낮아, `비용 자산화 family`를 넓게 잡는 우선검토 룰로 해석한다. 상세는 `tests/phase1_rulebase/test-results/l2-04-synth-2022-2024.md` 참조.
- **평가 계약**
  - `src/metrics/rule_mapping.py`의 primary label family는 `ExpenseCapitalization + ImproperCapitalization`이다.
  - `v115_candidate`부터 `rule_truth_L2_04*`와 `expense_capitalization_review_population*`은 현재 `b11_expense_capitalization()` detector output으로 재생성한 raw candidate universe다. 현재 문서 수는 `1,098`건이다.
  - (구) `immediate/review/low/population` band 분류는 binary 재정의(2026-06-19)로 폐기. raw candidate는 자산↔비용 매칭 발화 여부로만 본다. 확정 비용 자산화처럼 강하게 볼 대상은 confirmed label subset과 함께 본다.
  - `expense_capitalization_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `expense_capitalization_plausible_cases*`와 `expense_capitalization_normal_capex_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - `v117_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v117`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
  - strict `ImproperCapitalization`은 확정 subtype 참고값이며, 단독 precision을 L2-04 전체 성능으로 보지 않는다.
  - 리포트 상태는 coverage anchor로 표시한다(band 분류 폐기).
- **구현**: `fraud_rules_groupby.py` → `b11_expense_capitalization()`
- **필요 피처**: `document_id`, `gl_account`, `debit_amount`, `credit_amount`

#### L2-05 — 역분개 패턴 (ReversalEntry) ✅

- **심각도**: 4
- **근거**: 240§32(a)(ii) 기말 재분개 중점 검사, FSS 분식회계·횡령은폐
- **설계 원칙 (백지 재정의 2026-06-19)**
  - 역분개 = 원래 전표를 거꾸로 되받아 무효화하는 것. 같은 계정이 차변↔대변으로 뒤집혀 상쇄되는 **거울 쌍**.
  - 정상 영업에 역분개가 압도적으로 많다(자동 결산 역분개·실수 정정). 구조만으로는 부정/정상이 구별되지 않으므로 **부정 확정이 아니라 검토 트리거**다. 기말·수기·관계사 같은 정황 판단은 룰이 하지 않고 통합점수체계 조합이 한다.
- **판정 (binary flag — 점수 가감·밴드 폐기)**
  - 아래 둘 중 하나면 **flag 1.0**.
    - **(A) ERP 연결**: `original_document_id`/`reversal_document_id`/`reference_document_id`/`reversal_reason` 등 원전표↔역전표 연결 필드로 역분개임이 명시됨. (확정 식별, 시점 무관)
    - **(B) 1:1 거울 쌍**: 같은 `gl_account` + 반대 방향(한쪽 차변 X / 다른쪽 대변 X) + 금액 일치(±오차) + 다른 `document_id`. 시간 윈도우(config `reversal_mirror_window_days`, 기본 45일) 내.
      - **윈도우 45일 근거 (2026-07-02 시차 분포 분석)**: 거울 쌍 전수 44,836건의 시차(원전표↔역전표 posting_date 차이)를 측정한 결과 중간값 44일, 1~91일 구간에 거의 평평하게 분포하고 창 상한(구 90일)까지 계속 누적됐다. 진짜 결산 역분개라면 월차 결산 주기(25~35일)에 뾰족하게 몰려야 하는데 그렇지 않아, 넓은 창 안에서 "같은 계정·유사 금액·반대 방향"이 우연히 맞아떨어진 쌍이 상당수 섞인다고 판단해 90일 → 45일로 좁혔다. (30일 이내 35.3% / 45일 이내가 결산 신호의 주 구간)
  - **"같은 계정"이 정상 상계를 거른다**: 역분개는 **같은 계정**을 되돌리고, 정상 상계/정산은 **다른 계정** 간(받을 돈↔줄 돈, AR↔AP)이다. 같은 계정 거울 쌍이면 상계가 아니라 되돌림이다. 이 조건의 **미탐 위험은 작다** — 진짜 역분개는 수학적으로 같은 계정을 뒤집으므로 정의상 매칭된다(놓치는 건 다른 계정으로 우회한 "가짜전표+커버"로, 역분개가 아닌 별개 패턴).
- **자동 source도 발화 (정상성 판단은 통합점수)**
  - 자동/시스템/배치 source의 정기 결산 역분개(발생주의 미수·미지급 자동 역분개 등)도 거울 쌍/ERP 연결이면 **flag 1.0으로 발화한다.** "자동 정기 역분개라 정상"은 source/수기 차원의 정상성 판단이므로 룰이 하지 않고, `L3-02`(수기 전용 룰)와 통합점수체계가 `역분개 + 자동 source`를 정상으로 다운웨이트한다(룰은 멍청하게). 단 "같은 계정 되돌림"·"다른 document_id"는 역분개 정의 자체라 유지(intrinsic).
- **폐기 (구 신호 정리)**
  - **S2b(단일 라인 차대변 스왑) 폐기**: 전표 하나가 불균형(차변≠대변)인 **입력 오류**이지 역분개(균형 전표 두 개로 되돌림)가 아니다. 불균형은 이미 **L1-01(차대불일치)**이 잡는다.
  - **S2(N:M 순액 ≈ 0) 폐기**: 가수금·가지급금·미결제 같은 청산계정은 본질적으로 윈도우 내 0으로 수렴 = 정상이라 **과탐이 압도적**이고 거를 내재 기준이 없다. 분할·우회 역분개는 niche이며 L3-09(가수금 장기체류)·조합이 보완한다.
  - **점수 가감(구 S3 가점·S4 키워드·S5 기말 부스트)과 high-confidence/candidate 밴드 폐기.** 모든 발화 경로 score 1.0.
- **tier로 흐르는 길**
  - L2-05 단독은 통합점수 **LOW**(역분개 검토 후보). 기말(L3-04)·수기(L3-02)·관계사(L3-03)·가수금(L3-09)과 **조합 시 HIGH**(`related_party_reversal_high`·`embezzlement_concealment` 등). 정황 가중은 룰이 아니라 통합점수체계가 한다.
- **평가/리포트 표시 방식**
  - (구) `high-confidence reversal`/`candidate clearing-reclass` 밴드 분리는 binary 재정의(2026-06-19)로 폐기. 발화는 (A)ERP 연결·(B)1:1 거울 쌍 여부로만 본다.
  - `c11_reversal_entry()`는 Boolean hit 외에 행 단위 `score_series`(1.0/0.0), `breakdown`, `row_annotations`(거울 쌍 상대 전표·금액 근거)를 제공한다.
- **실무 해석 시 주의점**
  - N:M 순액 0을 폐기했으므로 청산계정(`9990`·차입금·선수금·자금이체성·임시계정) 과탐은 구조적으로 제거된다(1:1 거울 쌍은 같은 계정 되돌림만 보므로).
  - S2b 제거로 단일 전표 불균형(입력 오류)은 L2-05에서 빠지고 L1-01이 담당한다.
- **DataSynth 계약**: `ReversedAmount` 라벨은 실제 `journal_entries*.csv`에 존재하는 `document_id`만 가리켜야 한다.
- **평가 계약**
  - `ReversedAmount`는 confirmed reversal subset이다. binary 재정의 후 (A)ERP 연결·(B)1:1 거울 쌍 발화와 대조한다.
  - `v115_candidate`부터 `rule_truth_L2_05*`와 `reversal_entry_review_population*`은 현재 `c11_reversal_entry()` detector output으로 재생성한 raw candidate universe다. (현행 82건은 구 신호 기준 — S2b/N:M 폐기 반영 후 재생성 대상. 자동 source 제외 폐기로 자동 역분개도 모집단에 포함.)
  - (구) high_confidence/candidate band 구분은 폐기. raw candidate는 거울 쌍/ERP 연결 발화 여부로만 본다.
  - `reversal_entry_review_population*`은 detector output snapshot이다. 독립 검증 sidecar가 아니다.
  - `v117_candidate`부터 독립 행동 검증용 sidecar는 `reversal_pattern_plausible_cases*`와 `reversal_pattern_normal_clearing_controls*`를 사용한다. 이 파일들은 detector output을 읽지 않고 anomaly label 또는 journal 업무 필드로만 선정한다.
  - `v117_candidate`부터 활성 `rule_truth_*`의 `source_candidate` 메타데이터는 모두 `v117`로 정리되어, 과거 후보 버전 기준이 활성 truth처럼 남지 않는다.
- **ERP 구조 필드 우선 원칙**: 실제 ERP에서 별도 역분개 문서형이 많으면 `(A)` ERP 연결 coverage가 중요하므로, 구조 필드가 있으면 최우선으로 활용한다.
- **구현**: `anomaly_rules_reversal.py` → `c11_reversal_entry()`
  - (B) 1:1 거울 쌍 후보 생성: DuckDB self-join (`document_id × gl_account` 집계 후)
- **필요 피처**: `gl_account`, `debit_amount`, `credit_amount`, `posting_date`, `document_id`
  - 보조: `created_by`, `source`, `reference`, `document_type`, `line_text`, `header_text`
- **성능**: S1은 `document_id × gl_account` 집계 후 `gl_account + 금액 + 시차` 기준으로 후보쌍을 먼저 만들고, reference/작성자/문서유형/적요 문맥 점수로 후보를 좁혀 Cartesian 폭발을 줄인다.

### Sidecar Evaluation Policy

- `v118_candidate`부터 `labels/sidecar_manifest.csv/json`을 sidecar 해석의 기준으로 사용한다.
- `v119_candidate`부터 L3-06 normal after-hours context는 anomaly-labeled 문서를 포함하지 않는다. labeled overlap은 `afterhours_cross_rule_labeled_context*`로 분리한다.
- `v119_candidate`부터 L3-03 IC exception sidecar는 case-level drilldown으로 본다. `ic_unmatched_cases*`, `ic_amount_mismatch_cases*`, `ic_timing_gap_cases*`, `transfer_pricing_review_cases*`는 `target_document_id`/`counterpart_document_id`로 L3-03 truth에 링크되며, `document_id` 기준 subset으로 평가하지 않는다.
- 파일명에 `control`, `negative`, `review_population`이 들어가도 의미가 같다고 보지 않는다.
- 독립 현실성 검증에는 `allowed_for_independent_sidecar_eval=True`인 sidecar만 사용한다.
- detector 계약 검증에는 `rule_truth_*` 또는 `purpose=detector_contract_universe`만 사용한다.
- `purpose=rule_truth_context`, `rule_truth_but_not_audit_issue`, `legacy_alias`, `contract_manifest`는 독립 현실성 평가 분모에 넣지 않는다.

---

### 2.3 L3: 검토 필요 이상징후 (11개 구현, L3-01 폐기)

> **L3-01 폐기 (2026-06-20, 구 계정 분류 불일치)**: 업무프로세스-계정 부조화는 사람이 유지하는 정답 조합표(denylist/category)에 의존하는데 그 기준이 애매하고, 통합점수체계 조합에서도 참조되지 않았다. 도메인상 이상한 계정 조합 중 실제로 드문 것은 **L4-04(희소 차대 계정쌍)** 가 데이터 기반으로 자연 포착하므로 별도 룰로 두지 않는다. 정답표 휴리스틱 룰을 제거하고 통계 룰(L4-04)에 역할을 넘긴다. canonical rule 수에서 제외(31→30).

#### L3-02 — 수기 전표 (Manual Entry Population) ✅

- **심각도**: 4
- **근거**: 240-A45(b) 비인가자 입력, K-SOX 우회금지(외감법§8②). FSS 가공전표: 자동 프로세스 우회
- **탐지 로직 (binary)**: `is_manual_je == True`이면 flag `1.0`, 아니면 `0`. `is_manual_je`가 없으면 `source`가 `manual_source_codes`에 포함되는지로 판정한다. 그 외 가공·완화·점수 차등 없음.
- **해석 원칙**
  - L3-02는 "이 전표가 수기/조정 입력이다"라는 사실 하나만 표시한다. 부정·통제우회 확정이 아니고, 수기 자체가 위반도 아니다.
  - 수기전표는 정상적으로도 흔하므로(결산 조정 등), L3-02 단독으로 검토 우선순위를 만들지 않는다. **고액·기말·자기승인·승인생략·심야·민감계정 등 다른 신호와의 조합 가중은 전부 통합점수체계가 한다.** 룰은 수기 여부만 본다.
  - `ManualOverride` anomaly label은 일부 조작성 수기 시나리오이고, L3-02 운영 truth는 수기/조정 전표 전체 모집단이다(평가 보조 지표).
- **출력 메타데이터**
  - `score_series`: 수기 `1.0` / 비수기 `0`.
  - `row_annotations`: `document_id`, `source`, `created_by`, `approved_by`, `approval_date`, `business_process`, `gl_account` 등 사실값만 기록한다(버킷·우선순위 사유 계산 없음).
  - `breakdown`: `flagged_rows`, `manual_rows`, `adjustment_rows`, `source_counts`.
- **구현**: `fraud_rules_feature.py` → `b08_manual_override()`
- **필요 피처**: `is_manual_je` 또는 `source`
- **DataSynth truth 원칙**: `L3-02`는 수기전표 전체 모집단 coverage로 평가하고, 일부 조작성 시나리오 라벨인 `ManualOverride`와는 분리한다.

#### L3-03 — 관계사 거래 검토 신호 (RelatedPartyTransactionSignal) ✅

- **심각도**: 4
- **근거 (1차)**: IFRS 10 §B86 연결 내부거래 제거, K-IFRS 1110 연결재무제표 작성 시 내부거래 제거 절차, K-IFRS 1024 특수관계자 공시, KICPA Issue Paper 46 (JET 완전성), ISA 600 그룹감사 구성단위 잔액 대사. IC 양측 대사 룰의 회계적 필연성은 이 근거에서 도출된다.
- **근거 (보조)**: ISA 550 §23 특수관계자 거래의 사업상 합리성 검토. Phase 1에서는 순환 구조를 단정하지 않고 관계사 계정 사용 전표를 검토 후보로 올린다.
- **탐지 로직**: IC GL prefix 매칭
  - `intercompany_identifiers: ['1150', '2050', '4500', '2700']`
  - 관계사 채권/채무/매출/미지급 등 고객사 CoA상 IC 전용 계정 사용 여부만 판단
  - 실제 A→B→C→A N-hop 순환 탐지는 **GR01(GraphDetector)** 에서 담당 ([DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD) §4.5)
- **구현**: `fraud_rules_access.py` → `b10_intercompany_review_signal()`
- **필요 피처**: `is_intercompany` (`gl_account` prefix에서 생성), 보강 설명용 `company_code`, `trading_partner`, `reference`
- **PHASE1-1 경계 (binary)**: 함수는 `is_intercompany=True` 모집단을 flag `1.0`(아니면 `0`)으로 표시하는 context 태그다. `RULE_SCORING_REGISTRY` 기준 scoring은 `logic_mismatch/weak/booster`, `final_topic=account_logic`, `standalone_rankable=False`이며 단독 floor는 없다.
- **해석 원칙**
  - L3-03은 "이 전표가 관계사 전용 계정을 썼다"는 사실 하나만 표시하는 **context 태그**다. 부정·순환거래 확정이 아니다.
  - 관계사 거래는 정상적으로도 많으므로 L3-03 단독으로 검토 우선순위를 만들지 않는다. **관계사+역분개·관계사+미대사 등 조합 가중은 전부 통합점수체계가 한다.** 룰은 관계사 계정 사용 여부만 본다.
- **출력 메타데이터**
  - `score_series`: 관계사 계정 사용 `1.0` / 아니면 `0`.
  - `breakdown`: `ic_population_rows`, `ic_population_docs`, `ic_company_count`, `trading_partner_coverage_ratio`.
  - `row_annotations`: `signal_category=ic_population`, `company_code`, `trading_partner`.
- **실무 해석**: 단독 부정 후보가 아니라 특수관계자 거래 모집단/샘플링 후보. 계약서·상대방·정상가격·대사 여부는 후속 확인한다. recall 우선 스크리닝이므로 IC prefix·금액·시차 조건을 임의로 좁혀 미탐을 늘리지 않는다.
- **DataSynth 계약**: `v37_candidate`부터 IC GL prefix 기준 `intercompany_population_truth` sidecar를 별도 관리하고, 실제 비정상 순환거래 라벨(`CircularIntercompany`/`CircularTransaction`)과 혼동하지 않는다.
- **PHASE1-2 family 이관 (2026-06-20)**: 관계사 쌍 대사 예외(IC01/IC02/IC03)·그 evidence_level/floor/PHASE2 확률컬럼, N-hop 순환(GR01)·이전가격 비대칭(GR03)과 평가계약은 [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD) §4.4 IC Matcher / §4.5 Graph Detector 소관이다. L3-03 카드는 관계사 계정 사용 binary 태그만 정의한다.
- **한계**: 정상 내부거래도 많이 포함될 수 있으며, 이 룰만으로 순환거래나 부정을 단정하지 않는다. 고객사 CoA에서 관계사 계정 prefix가 다르면 `patterns.intercompany.pairs`를 먼저 보정해야 한다.

#### L3-04 — 기말/기초 결산 검토 후보군 (Period-start/end Closing Review) ✅

- **심각도**: 3
- **근거**: 240§32(a)(ii)+A44 기말검사 의무. FSS 결산수정 27건(29%)
- **탐지 로직 (binary)**: `posting_date`가 월말 직전 5일 또는 월초 5일 구간(기말/기초)이면 flag `1.0`, 아니면 `0`. 구간 폭은 `period_end_margin_days`(기본 5)로 정한다. 기말/기초 여부만 본다 — 금액·수기·민감계정·승인·시점은 hit 조건도 점수 차등도 아니며, 그 조합 가중은 통합점수체계가 한다.
- **구현**: `anomaly_rules_simple.py` → `c01_period_end_large()`
- **필요 피처**: `posting_date`, `is_period_end` (파생)
- **Phase 1 적용 방침**
  - 결산 일정은 회사별로 다르므로 감사인/사용자가 `period_end_margin_days`와 회계연도 기준을 engagement 시작 시 확정해야 한다. 기본값 5일은 제품 기본값일 뿐 회사 결산일을 대체하지 않는다.
  - **기말+기초 둘 다 잡는다.** 한국 월차결산이 익월 초까지 이어져 전월 조정이 월초에 입력되므로 기초(월초 5일)도 결산 검토 신호다. 정상 이월 노이즈는 통합점수체계 조합이 거른다(룰에서 좁히지 않는다).
- **해석 원칙**
  - L3-04는 "이 전표가 기말/기초 결산 구간에 전기됐다"는 사실 하나만 표시하는 **timing context 태그**다. 부정·조작 확정이 아니다.
  - 결산 구간 전표는 정상적으로도 많으므로 L3-04 단독으로 검토 우선순위를 만들지 않는다. **고액·수기·민감계정·승인문제·심야·역분개 등 조합 가중은 전부 통합점수체계가 한다.** 룰은 기말/기초 여부만 본다.
- **출력 메타데이터**
  - `score_series`: 기말/기초 `1.0` / 아니면 `0`.
  - `row_annotations`: `period_phase`(기말=`end` / 기초=`start` 구분), `posting_date`, `source`, `created_by`, `approved_by`, `business_process`, `account_group`, `gl_account` 등 사실값만 기록한다(버킷·금액 임계·우선순위 사유 계산 없음).
  - `breakdown`: `flagged_rows`, `period_end_rows`, `period_start_rows`, `source_counts`.
- **평가/리포트 표시 방식**: `RushedPeriodEnd` 확정 라벨 기준 precision/recall은 조작 시나리오 보조 참고값이다. L3-04 Phase 1 primary truth는 월말/월초 ±5일 review population coverage다.
- **운영 전제**: L3-04는 탐지 제외 룰이 아니라 결산 검토 후보 모집단이다. 플래그(1/0)는 유지하고, 검토 우선순위는 통합점수체계 조합이 정한다. 반복 마감전표 downgrade·민감계정 가중 같은 정황 보정도 룰이 아니라 통합점수체계 소관이다.

#### L3-05 — 주말/공휴일 전기 (WeekendPosting) ✅ 【OFF-HOUR 트랙】

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. FSS 비정상시점 4건
- **탐지 로직 (binary)**: `weekday() >= 5`(토·일) 또는 공휴일(한국 법정공휴일+`custom_holidays`)이면 flag `1.0`, 아니면 `0`. **source는 보지 않는다.** 구 3단 점수(`weekday_holiday/weekend/weekend_holiday`)·PHASE1 signal_strength 변환 폐기.
- **자동 전표도 발화 (정상성은 통합점수)**: 시스템·배치가 주말/공휴일에 도는 것도 flag `1.0`으로 올린다. "자동이라 정상"은 source/수기 차원이라 룰이 판단하지 않고, `L3-02`(수기 전용 룰)와 통합점수체계가 `비근무일 + 자동 source`를 정상으로 다운웨이트한다. 자동인 척 위장한 전표(batch_id 결측 등) 판별(source-trust)도 통합점수의 L3-02/source_trust leg 소관이다(룰은 비근무일 사실만 본다).
- **해석 원칙**: L3-05는 "비근무일(주말/공휴일)에 전기됐다"는 사실만 표시하는 **OFF-TIME context 태그**다. tier 게이트에 직접 참여하지 않고 severity 보조축으로 쓰인다. 부정 확정이 아니며, 수기·고액·기말/기초·승인우회·중복/역분개·적요결손·사용자집중(L4-05) 조합 가중은 전부 통합점수체계가 한다.
- **출력 메타데이터**
  - `score_series`: 비근무일 `1.0` / 아니면 `0`.
  - `row_annotations`: `is_weekend`, `is_holiday`, `source`, `posting_date` 등 사실값만.
  - `breakdown`: `flagged_rows`, `weekend_rows`, `holiday_rows`, `source_counts`.
- **구현**: `anomaly_rules_simple.py` → `c02_weekend_entry()`
- **필요 피처**: `posting_date`, `is_weekend`(파생), `is_holiday`(파생)
- **운영 전제**: `is_holiday`는 한국 법정공휴일과 `custom_holidays`를 함께 본다. 감사인은 회사 창립기념일·전사 휴무일·공장 셧다운·노사 합의 휴일을 `custom_holidays`에 입력해야 회사 실제 근무 캘린더 기준으로 탐지된다.
- **DataSynth 계약**: `v36_candidate`부터 정상 주말 처리 배경을 `normal_weekend_context` sidecar로 분리한다. `v41_candidate`부터 L3-05 hit는 `labels/weekend_review_population*`에 review population으로 저장하고, 확정 이상은 `WeekendPosting`/`labels/weekend_confirmed_anomalies*`만 사용한다(raw hit 전체를 anomaly precision 분모로 쓰지 않음). 넓은 캘린더 스크리닝이라 확정 라벨 기준 precision이 낮아 보이는 것은 룰 목적과 다른 평가이며, 운영 평가는 확정 라벨 recall·review population coverage·정상 대조군 분리로 본다.

#### L3-06 — 심야 전기 (AfterHoursPosting) ✅ 【OFF-HOUR 트랙】

- **심각도**: 2
- **근거**: 240-A45(c) 비정상시점. KLCA IT 체크리스트
- **탐지 로직 (binary)**: `is_after_hours`(심야 `midnight_start`~`midnight_end`, 기본 22~06시)이면 flag `1.0`, 아니면 `0`. **source는 보지 않는다.** 구 2단 점수(`confirmed_after_hours=0.45`/`normal_system_context=0.20`) 폐기.
- **구현**: `anomaly_rules_simple.py` → `c03_after_hours_entry()`
- **필요 피처**: `posting_date`(시간 포함), `is_after_hours`(파생)
- **자동 전표도 발화 (정상성은 통합점수)**: 야간 배치·인터페이스가 심야에 도는 것도 flag `1.0`으로 올린다. "자동이라 정상"은 source/수기 차원이라 룰이 판단하지 않고, `L3-02`(수기 전용 룰)와 통합점수체계가 `심야 + 자동 source`를 정상으로 다운웨이트한다. 자동인 척 위장한 전표(batch_id 결측 등) 판별(source-trust)도 통합점수의 L3-02/source_trust leg 소관이다(룰은 심야 사실만 본다).
- **해석 원칙**: L3-06은 "심야에 전기됐다"는 사실만 표시하는 **OFF-TIME context 태그**다. tier 게이트 미참여, severity 보조축. 단독 Medium/High를 만들지 않고, 수기·고액·기말/기초·승인생략·자기승인·적요결손·사용자집중(L4-05) 조합 가중은 전부 통합점수체계가 한다.
- **출력 메타데이터**
  - `score_series`: 심야 `1.0` / 아니면 `0`.
  - `row_annotations`: `source`, `created_by`, `posting_date`, `time_bucket` 등 사실값만.
  - `breakdown`: `flagged_rows`, `after_hours_rows`, `source_counts`, `time_bucket_counts`.
- **운영 전제**: 심야 시작/종료 시각은 회사 근무제·교대근무·해외법인 시간대·마감 운영 정책에 맞게 조정한다. 주말/공휴일은 L3-05, 사용자별 overtime·심야 집중은 L4-05에서 별도로 다룬다.
- **DataSynth 계약**: `AfterHoursPosting`을 L3-06 truth로 사용하고, 정상 심야 배경과 date-only/timezone 한계는 별도 sidecar로 분리한다.

#### L3-07 — 전기일-문서일 장기 괴리 (Posting-Document Date Gap) ✅

- **심각도**: 3
- **근거**: 240-A45(c) 기말+설명없음. FSS 횡령은폐
- **탐지 로직**: `abs(posting_date - document_date) > N일`이면 발화(기본 30일 초과). 괴리 폭·방향은 점수에 반영하지 않는다.
  - 조건 충족 시 `score=1.0`, 아니면 `0.0`인 binary flag다. 괴리 폭(31~60/61~90/90일 초과) 3등급과 방향(지연/선전기) 구분은 폐기했다.
  - 폭·방향에 따른 우선순위 차등은 룰이 아니라 PHASE1 통합점수체계(기말·통제·금액 조합)가 담당한다.
- **PHASE1 점수 반영**: 발화 시 `1.0`, 아니면 `0.0`. bucket label 재정규화(구 `0.55/0.75/1.0`)는 폐기했다. 단독으로 High/Medium을 만들지 않으며, 결산·통제·금액 신호와 결합할 때만 통합점수가 우선순위를 올린다.
- **구현**: `anomaly_rules_simple.py` → `c04_backdated_entry()`
- **필요 피처**: `posting_date`, `document_date`, `days_backdated` (파생)
- **리포트 산출**:
  - `breakdown`: `flagged_rows`, `threshold_days`
  - `row_annotations`: `document_id`, `posting_date`, `document_date`, `days_backdated`, `abs_gap_days`, `threshold_days` 등 사실값만 기록한다(버킷·방향·우선순위 사유 계산 없음).
- **운영 해석**: PHASE1에서는 설명 가능한 1차 스크리닝 룰로 사용한다. 이 룰은 `BackdatedEntry`와 `LatePosting` 성격을 모두 포착하는 날짜 괴리 신호이며, 단독으로 부정이나 소급 입력을 확정하지 않는다. 실무에서 진짜 마감 후 소급 입력을 보려면 `entry_date`/`created_at`과 `posting_date`의 차이를 별도 룰로 보강해야 한다.
- **DataSynth 계약**: `v33/v34_candidate`에서 `LatePosting` 라벨 정합성과 정상 업무 지연 negative control을 분리 관리한다.

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
- **결과 제시 방식**
  - L3-09의 raw hit는 확정 `SuspenseAccountAbuse`가 아니라 장기 미정리 가계정 review population이다.
  - 발화 시 `score=1.0`, 아니면 `0.0`인 binary flag다. 체류기간 bucket(`aging_30_60/60_90/over_90`)의 점수 차등(구 `0.45/0.60/0.75`), 미정리 금액 상위 bucket `+0.05` 가산, open_amount 분위수 bucket(`low/medium/high/unknown`)은 모두 폐기했다.
  - 체류기간 강도(오래 묵을수록 의심)와 금액 강도는 룰이 아니라 PHASE1 통합점수체계가 정황으로 받는다.
- **PHASE1 통합점수 반영**
  - L3-09는 `logic_mismatch`, `evidence_strength=medium`, `scoring_role=primary`로 정규화된다. 발화 시 `1.0`, 아니면 `0.0`이며, 구 단조 정규화(`0.45→0.3375`, `0.60→0.45`, `0.75→0.5625`)는 폐기했다.
  - 이 값은 case-level `logic_score`에 들어가고, 기본 `case_priority`에서는 `0.15 * logic_score`로만 반영된다. L3-09 단독 High floor는 두지 않는다.
  - `L3-09 + L3-07/L3-04/L4-03`처럼 날짜 괴리, 기말 조정, 고액 신호가 결합될 때 case priority가 올라가도록 해석한다.
- **리포트 산출**
  - `breakdown`: `flagged_rows`, `threshold_days`(`suspense_aging_days`)
  - `row_annotations`: `document_id`, `gl_account`, `posting_date`, `aging_days`(raw 숫자), `open_amount`(raw), `settlement_date` 등 사실값만 기록한다(버킷·우선순위 사유 계산 없음).
- **운영 전제**:
  - 이 룰의 핵심은 `가계정 사용`이 아니라 `장기 미정리(open)`다.
  - `lettrage` 계열은 ERP/국가별 편차가 커서 보조 입력으로만 사용한다.
  - Phase 1에서는 계정별 적응형 grace 보정 없이, 정해진 `suspense_aging_days`를 공통 기준으로 사용한다.
  - 정상 clearing 계정 구분, 계정별 grace 추천, 예외 후보 자동 제안은 Phase 2/3 보조 분석으로 넘긴다.
- **DataSynth 평가 계약**: `v42_candidate`부터 `lettrage`, `lettrage_date`, `amount_open`, `is_cleared`, `settlement_status`, `settlement_date`를 원장에 포함한다. `labels/suspense_lifecycle_population*.csv/json`은 가계정 정산 lifecycle 모집단, `labels/suspense_aging_review_population*.csv/json`은 L3-09 raw review population, `labels/suspense_confirmed_anomalies*.csv/json`은 확정 `SuspenseAccountAbuse` truth, `labels/suspense_normal_controls*.csv/json`은 정상 clearing 대조군이다. L3-09 raw hit 전체를 확정 anomaly precision 분모로 쓰지 않는다.
- **Future local-only 이관**: 적요 의미 분석은 별도다. L3-09는 Phase 1에서 `정산상태 + 체류일수`를 본다.

#### L3-10 — 추정계정 사용 (EstimateAccountUse) ✅

- **심각도**: 3
- **근거**: ISA 240 §32(b) 회계추정치에 대한 경영진 편의(management bias) 점검 의무 + PCAOB AS 2401 §61(c) 기말 전표+설명없음. SEC "The Numbers Game"(1998) cookie jar reserves. FSS 충당금·손상 위반 약 55건(결산시점 결합 시 HIGH-4). 등급 SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §3 HIGH-4.
- **탐지 로직**: `account_name`/`gl_account_name`이 `patterns.estimate_account_use.account_name_keywords`를 포함(1차, CoA 무관)하거나 `gl_account`가 `accounts`/`account_prefixes`(2차, 클라이언트 확정 코드)에 속하면 발화. 둘 다 미설정이면 0건.
  - 조건 충족 시 `score=1.0`, 아니면 `0.0`인 binary flag다. 카테고리 차등(구 `priority_case=0.65/raw_signal=0.35/normal_control_candidate=0.20`)과 `_high_risk_account_signal_category`(수기·고액·미정리·기말·자동 분류)는 폐기했다.
  - 수기·고액·미정리·기말 등 정황 가중과 자동소스 다운웨이트는 룰이 아니라 PHASE1 통합점수체계(조합·source_trust)가 담당한다.
- **잡는 계정 — 추정계정(회계추정치, ISA 540) A·B·C·D**:
  - **A 평가성 충당금·손상**: 대손충당금, 재고자산평가충당금(NRV 저가법), 유·무형자산 손상차손(영업권 포함), 금융자산 손상(기대신용손실 ECL), 관계기업투자 손상
  - **B 충당부채(IAS 37)**: 판매보증·하자보수, 복구(원상복구), 소송, 구조조정충당부채
  - **C 보험수리·세무 추정**: 퇴직급여충당부채(확정급여채무 DBO), 이연법인세자산(실현가능성 valuation allowance — cookie jar 레버)
  - **D 수익 관련 추정**: 반품·환불부채(변동대가), 건설계약 진행률(계약자산 미청구공사·계약부채)
  - **제외**: 감가상각누계액(내용연수·잔존가치)·공정가치 레벨1(관측가능) — 낮은 재량
  - **주의**: 추정계정은 정상 결산에도 흔히 만진다(퇴직급여·대손충당금 등 정기 분개). L3-10 단독은 LOW 커버리지이며, 결산시점(L3-04/L3-11) 결합 시 HIGH-4 후보가 느는 정상 결산 과탐은 시점 임계(step3)가 담당한다.
- **구현**: `fraud_rules_access.py` → `b13_estimate_account_use()`. config 키는 `patterns.estimate_account_use`(rename 완료).
- **필요 피처**: 판정에는 `gl_account`가 필수다.
- **계정 소싱**: K-IFRS 표준 추정계정 코드를 근거 박힌 기본 프로파일로 탑재하고, engagement가 클라이언트 CoA로 override한다. 회사별 CoA가 다르므로 prefix 기본값은 임시 초기값으로 본다. 최종 추정계정군 정의와 예외 범위는 감사인이 승인한다.
- **PHASE1 점수/조합**: 발화 시 `1.0`, 아니면 `0.0`. 폭·맥락 차등 없음. 단독으로는 High/Medium을 만들지 않으며 LOW(Coverage Queue)로 본다. `L3-04 기말`/`L3-11 컷오프` 결산시점 신호와 결합될 때만 통합점수가 HIGH-4(`period_end_adjustment_high`)로 우선순위를 올린다.
- **리포트 산출**:
  - `breakdown`: `flagged_rows`, `reason_counts.exact/prefix`
  - `row_annotations`: `document_id`, `gl_account`, `match_type`(exact/prefix), `matched_value`, `matched_group`(추정계정 카테고리) 등 사실값만 기록한다(`signal_category`·`category_reason`·우선순위 사유 계산 폐기).
- **운영 해석**: 추정계정 접촉 자체는 부정이 아니라 정상 결산에도 흔하다(충당금 설정 등). 룰은 "추정계정을 건드렸다"는 사실만 발화하고, 이익조정 의심은 결산시점·고액·수기와의 결합으로 통합점수가 판단한다.
- **DataSynth 평가 계약**: 구 `high_risk_account_*` 라벨(가계정/현금 기준 + 3-tier review/confirmed/normal 분리)은 추정계정·binary coverage 기준으로 재생성한다(코드/DataSynth 일괄 반영 단계). 정상 충당금 설정 대조군(normal control)을 둬 "추정계정이면 모두 부정"이라는 shortcut 학습을 막는 원칙은 유지한다.
- **DataSynth 구현 주의**: CSV에서 `gl_account`가 `1190.0`처럼 읽히는 경우가 있으므로 계정 비교는 trailing `.0`을 제거한 계정코드로 수행한다.

#### L3-11 — 기말 컷오프 불일치 (PeriodEndCutoffMismatch) ✅

- **심각도**: 3
- **근거**: 240§32(b), 315호, K-IFRS 15 수익 인식 기간귀속
- **성격**: Phase 1 review-needed 룰. 단독 부정 확정이 아니라, 수익 인식 시점과 근거 이벤트 시점이 맞는지 보는 cutoff 검토 신호다.
- **탐지 로직 (binary)**
  - `delivery_date`와 인식 회계연도(`fiscal_year`, 없으면 `posting_date`의 연도로 폴백)가 모두 존재하는 행만 검사한다.
  - **판정**: `delivery_date`가 속한 회계연도 ≠ 인식 회계연도이면 발화(`1.0`), 같으면 `0.0`. 일수 차이 임계(구 매출 5일/비용 7일)는 폐기한다 — "결산일(회계연도) 경계를 넘겼는가"가 곧 판정이며, 같은 연도 안의 처리지연은 일수가 커도 발화하지 않는다.
  - 매출(`is_revenue_account` 또는 `revenue_account_prefixes`)·비용(`expense_account_prefixes`)은 **동일 판정식**을 쓰고 `account_type`으로 구분만 한다(계정별 별도 임계 없음).
  - 양방향 모두 발화: 차기 매출을 당기로 당겨잡거나, 당기 비용을 차기로 미루는 경우 모두 경계를 넘으므로 잡힌다.
- **출력 방식**
  - 점수는 binary(`발화=1.0`, 아니면 `0.0`)다. 폭·일수·기말 가중 차등 없음. `EvidenceDetector`는 발화 여부를 그대로 `details["L3-11"]`에 반영한다(구 severity factor `0.6`·`day_diff / max_day_diff`·`period_end_weight ×1.5` 폐기).
  - `row_annotations`에는 `reason_code`(`revenue_cutoff_gap`/`expense_cutoff_gap`), `account_type`(revenue/expense), `delivery_year`, `recognition_year`를 기록한다. `day_diff`(달력일 차)는 **참고 사실값으로만** 함께 남기며 점수·우선순위를 구동하지 않는다.
  - `breakdown`에는 `cutoff_review_rows/docs`, `revenue_cutoff_rows/docs`, `expense_cutoff_rows/docs`, `missing_event_date_rows/docs`(=`delivery_date`/`fiscal_year` 부재로 미검증), `reason_counts`를 기록한다.
  - **평가/리포트 표시 방식**
    - binary이므로 점수 band(구 `>=0.30`/`>=0.60`)는 없다. 발화 문서 `cutoff_review_docs`가 곧 review queue다.
    - 조합·우선순위 강조(기말 `L3-04`, 고액 `L4-01` 결합 시 격상 등)는 룰 카드가 아니라 통합점수체계(`rule_scoring.py`)와 조합 SoT(`HIGH_COMBO_GROUNDING.md`) 소관이다.
- **실무 해석**
  - `delivery_date`는 모든 거래의 정답 기준일이 아니라, Phase 1에서 사용할 수 있는 **인식 기준 이벤트의 proxy**다.
  - 제품/상품/O2C 출하 매출에서는 비교적 강한 신호로 본다.
  - 용역, 구독, 공사, 검수조건부, 설치조건부 거래는 `service_confirmation_date`, `service_end_date`, `acceptance_date`, `installation_complete_date`, `billing_plan` 같은 더 적합한 기준일이 있으면 그 날짜를 우선해야 한다.
  - 기준일 후보가 없으면 정상으로 판정하지 않고, cutoff 검증 불가로 해석한다.
- **한계**
  - ERP에 반품권, 검수조건, 설치조건, 기간용역 조건이 항상 구조화 필드로 존재하지 않는다.
  - 계약서/첨부/OCR/업무 모듈에만 있는 조건은 Phase 1 단순 룰로 확정하지 않는다.
  - `delivery_date`가 없는 거래를 0점으로 두는 것은 "정상"이 아니라 "이 룰로는 미검증"이라는 의미다.
- **DataSynth 평가 계약**
  - `v46_candidate`부터 `RevenueCutoffMismatch`와 `ExpenseCutoffMismatch` confirmed label을 추가한다.
  - `labels/cutoff_confirmed_anomalies*.csv/json`는 confirmed subset이다.
  - `labels/cutoff_review_population*.csv/json`는 raw L3-11 hit coverage다.
  - `labels/cutoff_normal_controls*.csv/json`는 허용 범위 정상 대조군이다.
  - `labels/cutoff_reasonable_delay_controls*.csv/json`는 룰에는 걸리지만 정상 사유가 가능한 대조군이다. 회계연도 경계 판정으로 바뀌면서 **같은 연도 안의 장기 지연은 더 이상 발화하지 않으므로**, 이 대조군은 연도를 넘기지만 정책상 합법인 경우(예: 결산조정·특수기수, 검수/설치 조건으로 인식 시점이 이연되는 거래)를 의미한다.
  - `labels/cutoff_untestable_controls*.csv/json`는 `delivery_date` 부재로 미검증인 대조군이다.
  - 따라서 L3-11은 미탐 0만 보고 성공으로 해석하지 않고, reasonable-delay control이 raw FP로 남는지 함께 본다.
- **조합 시 위험도 해석**
  - `L3-11 단독`: 기간귀속 검토 후보. Medium.
  - `L3-11 + L4-01`: 고액 매출과 cutoff 불일치가 결합된 강한 매출 검토 후보. High.
  - `L3-11 + L4-01 + L3-04`: 기말 고액 매출 cutoff 후보. High~Critical.
  - `L3-11 + L4-01 + L3-02/L1-07/L1-05`: 수기 또는 승인통제 우회가 붙은 고액 cutoff 후보. Critical.
- **구현**
  - 오케스트레이터: `evidence_detector.py` → registry rule id `L3-11`
  - 룰 함수: `evidence_rules.py` → `ev02_cutoff_violation()`
- **필요 피처/컬럼**
  - 필수 비교: `delivery_date`, 인식 회계연도 `fiscal_year`(없으면 `posting_date`의 연도로 폴백)
  - 계정 분류: `is_revenue_account` 또는 `gl_account`
  - 보강: `business_process`, `document_type`, 기준 이벤트 날짜(`acceptance_date`, `service_end_date`, `installation_complete_date` 등)

---

### 2.4 L4: 통계적 이상치 (PHASE1-1 3개: L4-01·L4-03·L4-04)

> 2026-06-21 이관: **L4-06(BatchAnomaly)은 PHASE1-2 macro로 이관** → [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD). 모집단(배치·일자·금액분포) 단위 신호라 행 단위 PHASE1-1 룰이 아니며, HIGH/MEDIUM 조합 근거가 없다(`batch_combo` 근거없음→LOW, [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md)).

> 2026-06-17 분리: **L4-02(Benford)는 PHASE1-2로 이관** → [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD).
> **L4-05(비정상시간 집중)는 양쪽 소속(2026-06-20)**: PHASE1-2 family(사용자 행동 집계 단위)에 두되, PHASE1-1 **OFF-TIME set**(L3-05·L3-06과 함께 시간 보조축)에도 등록한다. 제거가 아니라 dual-membership이다. OFF-TIME set에서의 역할은 case 보조축(게이트 제외, 정렬·UI 전용, 점수 병합 금지 — 작성자 맥락 연결)이며 정의는 [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) OFF-TIME 보조축 절. 코드 registry는 PHASE1-1에 잔존(이관 미수행 상태가 dual-membership과 정합).

#### L4-01 — 상대적 고액 매출 (RelativeHighValueRevenue) ✅

- **심각도**: 5
- **근거**: 240보론2, §32(c) 비경상거래. **FSS 최다유형**: 매출 허위계상
- **발화 기준 (binary flag)**: 매출 계정 라인의 금액이 같은 매출계정 모집단 대비 **로그변환 z-score** 임계 초과면 `1.0`, 아니면 `0`.

  ```
  is_revenue_account AND amount_zscore_log > zscore_threshold  →  1.0
  그 외                                                        →  0
  ```

  - `patterns.revenue_account_prefixes: ['4']` (`config/audit_rules.yaml`)
  - `zscore_threshold: 3.0` (`config/settings.py`, 회사/engagement override 가능)
  - **로그변환 z-score (`amount_zscore_log`) 사용 근거 (2026-07-02)**: 매출 금액은 우편향이라 원금액 평균/표준편차 z-score(`amount_zscore`)는 극단값 하나가 표준편차를 부풀려 어지간한 고액도 임계를 못 넘긴다. 실측(v49)에서 매출 라인 z-score 최댓값 23.30인데 상위 1%(p99)가 1.63으로, 큰 금액이 3.0 임계에 대부분 못 미쳤다(계산 오류 아님·분포 특성). log 변환은 곱셈적 차이를 덧셈 거리로 압축해 분포를 정규에 가깝게 만들어 3σ 임계가 원 의도대로 작동한다(회계 금액 log-normal 근사). base = max(차변,대변) ≥ 0 이라 음수는 구조상 없고, 0원 라인만 log 불가 → NaN 처리해 미발화. **적용 범위는 L4-01만**이며 `amount_zscore`(원금액 z)는 L4-03·L1-08·접근통제 정황 신호에서 현행 유지한다.
  - 점수 밴드(`0.45/0.60/0.75`)·bucket(`review/strong/extreme_zscore`)·전용 정규화는 폐기한다. z-score 크기(폭)·고액 정황·조합 강도는 **통합점수체계(`rule_scoring.py`)·case priority** 소관이며 룰은 발화 여부만 결정한다.
  - `amount_zscore_log` 절대값은 `row_annotation`에 사실값으로만 남겨 표시·동점정렬에 통합점수 쪽에서 쓴다(룰 점수에 차등 반영 금지).
- **임계값 근거 (3.0σ)**
  - **경험법칙(68-95-99.7)**: 정규 근사에서 단측 `> +3σ`는 발생확률 약 0.135% — "1000건 중 1.4건 미만으로만 우연 발생할 큰 금액"의 원칙적 컷.
  - **Shewhart 관리도(SPC)**: 3σ는 통계적 공정관리의 표준 관리한계(특별원인 변동 기준선).
  - **감사 CAAT 관행**: 기준서에 고정 숫자 명령은 없고 위험·중요성 기반 판단이나, "계정 평균에서 3 표준편차 초과 금액" 류 z-score outlier 테스트가 JE 분석의 통상 기본값. 실제 임계는 engagement 입력으로 조정한다(§3, 리터럴 고정 금지).
- **구현**: `fraud_rules_feature.py` → `b01_revenue_manipulation()`
- **필요 피처**: `is_revenue_account`, `amount_zscore_log` (파생 — `amount_features.add_amount_zscore_log`)
- **실제 의미**
  - 핵심은 **상대적 고액 매출**(횡단면 outlier)이다 — "같은 매출계정 다른 전표 대비 비정상적으로 큰 매출 라인 1건". 절대 금액 크기가 아니라 같은 매출계정 모집단 대비 상대 편차(z-score)로 판정한다.
  - **범위 밖(중요)**: 매출 급감·음수 조정·환입·취소·후속 역분개, 그리고 **"평소 매출이 추세적으로 급변"(시계열 이상)은 이 룰의 목표가 아니다.** 환입/취소/역분개는 reversal/cutoff 룰, **매출 시계열 이상(추세 break)은 집계·시계열 단위라 PHASE1-1 행 binary로 표현 불가 → PHASE1-2 주제로 위임**한다([DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD)).
- **Phase 1 적용 방침**
  - `L4-01 단독 = 매출조작 확정`이 아니라 `금액적으로 튄 매출 라인`으로 보고, 다른 룰과의 동시 플래그 여부로 우선순위를 정한다.
  - Row-level `anomaly_score`에서는 L4 family 가중치가 낮아 L4-01 단독으로 High를 만들지 않는다.
  - Case-level에서는 `L4-01`이 cutoff, 기말, 수기, 승인통제, reversal 신호와 결합될 때 `priority_floor`로 High queue에 올린다.
- **평가/표시 정책**
  - `L4-01`은 `RevenueManipulation` 전체를 포괄하는 classifier가 아니라 **고액 매출 z-score 이상치 anchor**로 평가한다.
  - 결과 화면의 룰 메타데이터는 다음처럼 표시한다.
    - `Rule objective`: `High-value revenue z-score outlier`
    - `Broad fraud type`: `RevenueManipulation`
    - `Expected coverage`: `partial / anchor`
    - `Status`: `coverage_anchor`
  - 전체 `RevenueManipulation` 라벨 대비 precision/recall은 보조 참고값이다. 이 값만으로 `L4-01` 성공/실패를 판단하지 않는다.
  - 운영 지표는 다음 coverage 중심 지표를 같이 본다.
    - `overlap_docs`: `L4-01` 탐지 문서 중 다른 룰도 동시에 탐지한 문서 수
    - `standalone_docs`: `L4-01`만 단독 탐지한 고액 매출 검토 후보 수
    - `review_queue_docs`: broad label 기준 FP로 집계되지만 실무상 고액 정상거래/미라벨 검토 큐에 해당하는 문서 수
  - 합성데이터는 `RevenueManipulation` broad 라벨을 `L4-01`에 맞춰 억지로 좁히지 않는다.
  - `v47_candidate`부터 `metadata_json.revenue_subtype`과 `labels/revenue_manipulation_subtypes*`를 사용해 subtype을 분리한다.
  - L4-01 직접 정답은 `high_value_revenue_outlier` 및 `labels/revenue_manipulation_l401_direct_truth*`에 한정한다.
  - `v120_candidate`부터 `labels/revenue_outlier_detector_universe*`는 `labels/revenue_outlier_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/revenue_outlier_boundary_controls*`와 `labels/revenue_outlier_boundary_contexts*`는 cutoff/z-score 경계 context이며, strict negative control로 해석하지 않는다.
  - 직접 정답 metadata/sidecar가 없는 후보 데이터에서는 broad `RevenueManipulation` 전체로 fallback하지 않는다. 이 경우 L4-01 direct recall은 계약 부재로 보고, raw hit는 고액 매출 검토 anchor 및 다른 룰과의 overlap으로 해석한다.
  - `cutoff_mismatch`, `reversal_return_credit`, `period_end_push`, `manual_revenue_entry`, `process_account_mismatch`, `composite_low_amount_dispersion`은 L4-01 단독 정답이 아니라 조합 평가 또는 Phase 2/3 coverage로 본다.
- **한계**
  - 정상적인 대형 계약, 신규 고객, 신규 사업, 계절성 매출 집중도 플래그될 수 있다.
  - 여러 건으로 쪼갠 가공매출은 개별 라인의 z-score가 낮으면 놓칠 수 있다.
  - 회사별 CoA에서 매출 계정 prefix가 `4`가 아니면 `revenue_account_prefixes`를 조정하지 않는 한 누락된다.
  - `amount_zscore_log > threshold`만 보므로 큰 양의 이상치 중심이다. 음수 조정, 환입, 취소, 매출 감소 분석은 이 룰의 직접 목표가 아니다(base=max(차변,대변)≥0이라 음수 자체가 구조상 없음).
  - z-score는 모집단 통계에 의존한다. 표본이 작을 때는 CoA 상위그룹/전체 분포 fallback을 사용하므로 해석 강도가 낮아진다.
  - **우편향 대응(2026-07-02 반영)**: 원금액 평균/표준편차 z-score는 매출 우편향에서 σ가 부풀려져 이상치를 가린다. 이를 로그변환 z-score(`amount_zscore_log`, 임계 3.0σ 유지)로 교체해 σ 팽창을 제거했다. 로그변환도 극단값 영향을 완전히 없애진 못하므로(더 강건한 대안은 중앙값+MAD 수정 z-score), 여러 건으로 쪼갠 저액 가공매출은 여전히 개별 라인 z-score가 낮으면 놓칠 수 있다.
- **조합 시 위험도 해석**
  - L4-01은 단독으로 부정 결론을 내리기보다, 아래 조합에서 우선순위를 올리는 anchor로 쓴다.

  | 조합                           | 해석                                    | 우선순위    | 확인 포인트                                                                          |
  | ------------------------------ | --------------------------------------- | ----------- | ------------------------------------------------------------------------------------ |
  | `L4-01 + L3-11`                | 고액 매출 + cutoff 불일치               | High        | 출하일/용역완료일/검수일과 매출인식일의 귀속기간 차이, 계약 조건, 기말 전후 반대분개 |
  | `L4-01 + L3-04`                | 기말 고액 매출                          | High        | 월말/분기말/연말 집중, 다음 기간 취소·환입, 비경상 대형 계약 여부                    |
  | `L4-01 + L3-02`                | 수기 고액 매출                          | High        | 수기 입력 사유, 승인권자, supporting document, 반복 생성자/부서                      |
  | `L4-01 + L1-05/L1-07/L1-07-02` | 승인통제 이상이 붙은 고액 매출          | Critical    | 자기승인, 승인 누락, 유령 승인자, 권한 우회 여부                                     |
  | `L4-01 + L2-05`                | 후속 취소/역분개 가능성                 | High        | 매출 인식 후 credit memo, return, reversal, 동일 고객·금액·계정의 반대분개           |
  | `L4-01 + L4-03`                | 전체 금액 기준으로도 유의적인 고액 매출 | Medium~High | 감사 중요성 기준 초과 여부, 정상 대형계약/신규고객/일회성 거래 여부                  |

  - 현재 Phase 1 floor:
    - `L3-11 >= 0.30 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
    - `L3-04 >= 0.45 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
    - `L3-02 >= 0.60 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
    - `L2-05 >= 0.45 + L4-01` → `priority_score >= 0.75` (Medium 검토 후보)
  - 보조 조합으로 `L4-01 + L3-03`은 관계사 매출, 순환거래, 밀어넣기 가능성을 후속 확인한다.
  - 동일 전표 내 여러 라인이 L4-01에 걸리면 라인별 합산보다 전표 단위 최대점수와 동시 플래그 수를 함께 보여준다.

#### L4-03 — 절대적 이상 고액 (UnusuallyHighAmount) ✅

- **심각도**: 3
- **근거**: 240§33(b), 315호, ISA 320 중요성. FSS 결산수정: 개발비 과대자산화
- **Phase1 탐지 로직**: 라인 금액이 **수행중요성(performance materiality) 절대 임계**를 초과하면 발화한다. 분포 상대 기준(z-score)·모집단 분위수는 폐기한다.
  - 발화 조건: `max(debit_amount, credit_amount) >= threshold`
  - `threshold`는 회사 × 회계연도 단위로 GL에서 자동 산출한다(아래 산식). 저액 방향은 대상이 아니므로 절댓값·음수 이상치를 쓰지 않는다.
- **이익(NI)·임계 산식** (제조업 영리기업 기준, ISA 320.A8):
  - **이익은 마감분개 우선**: 마감분개(`closing_subtype=income_statement_close`)가 닫은 손익계정(`income_account_prefixes`) 라인의 `(차변-대변)=순이익(NI)`. 키워드 분류 없이 GL이 확정한 손익이라 정확하다.
  - **마감분개 없으면(연중 데이터) 키워드 합산 fallback**: `revenue(매출 subtype 대변순) - expense(비용 subtype 차변순)`로 PBT를 근사한다(마감·역분개 제외, 자산/부채 contra subtype 제외).
  - 법인세는 `OPEX_TAX` 등에 세금과공과와 섞여 분리가 부정확하므로 떼지 않고 NI 기준을 쓴다.
  - **임계**: 이익 > 0이면 `threshold = max(이익 × pbt_pct(5%) × pm_ratio(75%), 매출 floor)`, 적자(이익 ≤ 0)면 `threshold = 매출 floor`.
  - **매출 floor** = `revenue × rev_pct(0.5%) × pm_ratio(75%)`. 저마진·손익분기 근처는 이익 기준 임계가 비현실적으로 낮아지므로 매출 기준을 하한으로 둔다(ISA 320: PBT 변동·손익분기 근처는 매출/총자산 벤치마크).
  - 감사인이 `materiality_amount`를 입력하면 그 값을 `threshold`로 직접 사용한다(override).
  - `basis` 기록: `closing_ni` / `keyword_pbt` / `revenue_floor` / `revenue` / `override` / `unset`.
  - `pbt_pct`·`rev_pct`·`pm_ratio`·`income_account_prefixes`·subtype 패턴은 engagement 설정(`patterns.l403_materiality`) 입력이며 코드 리터럴로 박지 않는다(분석 구동값은 입력에서).
  - 매출·이익을 모두 산출할 수 없으면(벤치마크 매핑·입력 부재) 발화 0(annotation `basis=unset`). 분위수 등 대체 발화는 두지 않는다.
- **구현**: `anomaly_rules_simple.py` → `c08_amount_outlier()` / `_compute_pbt_thresholds()`, config `config/audit_rules.yaml` `patterns.l403_materiality`.
- **필요 피처**: `debit_amount`, `credit_amount`, 회사·연도별 수행중요성 임계(파생)
- **결과 표현**
  - 발화는 **binary**다. 조건 충족 시 `1.0`, 아니면 `0.0`. 구 z-score 강도 버킷(`low/medium/high_zscore` → `0.25/0.45/0.70`)과 전용 정규화는 폐기한다.
  - 금액의 크기(강도)는 룰이 가로채지 않고 통합점수체계와 `row_annotations` 사실값(라인 금액·적용 임계·임계 초과배수)으로만 남긴다.

- **PHASE1 통합점수 반영**
  - L4-03은 `statistical_outlier`, `evidence_strength=medium`으로 정규화되며 발화 시 `1.0`, 아니면 `0.0`이다. 구 bucket 라벨 정규화(`low=0.45/medium=0.70/high=1.0`)와 `rule_scoring.py`의 `L403_ZSCORE_BUCKET` 상수·분기는 폐기했다(generic binary fallback으로 흐름).
  - L4-03 단독 row/case floor는 두지 않는다. 절대 고액은 정상 대형거래와 혼재하므로 단독 High/Medium 승격 신호가 아니라, 결산·통제·계정논리·배치 신호와 결합될 때 우선순위를 올리는 review anchor다.
  - case priority의 `amount_score`(case 총액 기반 중요성·정렬 tiebreak)와 역할이 다르다. L4-03은 개별 라인이 수행중요성 임계를 넘는지의 binary 발화 신호(HIGH 조합 다리)이고, `amount_score`는 case 총액 정렬 보조다. 임계 출처를 분리해(L4-03=수행중요성 라인 임계, amount_score=case 총액) 중복을 피한다.

- **Phase1 범위**:
  - 임계는 회사 × 연도 수행중요성으로 자동 산출하고, 감사인 입력(`materiality_amount`)으로 override한다.
  - 계정군별·거래처별 baseline, 대형거래 whitelist, 반복 정상거래 자동 감점, 계정별 P99 프로파일링은 Phase2 이상 고도화 대상으로 둔다.
- **한계**:
  - 정상 대형 자금 이동, 정기 결제, 선수금·미지급비용 같은 큰 정상거래도 임계를 넘으면 후보에 포함될 수 있다.
  - 라인 단위 금액 기준이므로 전표 전체의 경제적 실질이나 차대변 구조까지 판단하지 않는다.
  - 매출·이익을 모두 산출할 수 없으면(벤치마크 매핑·수행중요성 입력 부재) 임계 `unset` → 발화 0.
- **사용 방식**:
  - L4-03 단독 플래그는 "고액 검토 후보"로 보고, 단독으로 부정 또는 실무상 유의미한 finding으로 결론내리지 않는다.
  - case priority의 `amount_score`(case 총액)와 L4-03(라인 단위 수행중요성 임계 초과 binary)은 단위·역할이 다르다. L4-03 발화를 case 총액 materiality score처럼 해석하지 않는다.
  - 다음 룰과 결합될 때 Phase1 우선순위를 높인다.
- **DataSynth 평가 계약**:
  - 기존 `labels/high_amount_review_population*`·`labels/rule_truth_L4_03*`은 구 `amount_zscore > zscore_threshold + 전역 상위 금액 가드` 기준으로 산출됐다(구 기준 truth).
  - **절대 수행중요성 임계로의 재설계 코드 반영 시 truth를 재산출**한다. 재산출 전까지 위 라벨은 구 z-score 기준이며 신 기준 pass/fail 분모로 쓰지 않는다.
  - 정상 대형거래, 자동/반복 고액거래도 임계를 넘으면 룰이 올려야 하는 review anchor이면 rule truth에 포함한다.
  - `UnusuallyHighAmount`와 `StatisticalOutlier`는 injected/confirmed anomaly subset이다.
  - `labels/high_amount_normal_controls*`와 `labels/high_amount_legitimate_contexts*`는 정상 대형거래 context이며, raw L4-03 hit가 될 수 있어도 confirmed FP로 단정하지 않는다.
  - 모든 고액 거래를 `UnusuallyHighAmount`로 라벨링하지 않는다.
- **평가 계약**:
  - L4-03은 strict fraud pass/fail 룰이 아니라 `coverage_anchor`다. `rule_truth_L4_03*`은 Phase1 후보 생성 계약이고, confirmed `UnusuallyHighAmount`/`StatisticalOutlier` 라벨은 조작/이상 주입 subset이다.
  - 발화가 binary라 z-score score band는 없다. 검토 모집단 집계는 `high_amount_review_docs`(전체) 사실 분류로 남긴다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `high_amount_review_docs`를 우선 사용한다.
  - detector는 row annotation에 라인 금액(`base_amount`), 적용 임계(`threshold`), 임계 초과배수, 임계 산출근거(`pbt`/`revenue` 기반 여부 또는 override)를 남긴다.

  | 결합                  | 의미                                | 우선순위 |     |                 |                                                       |      |
  | --------------------- | ----------------------------------- | -------- | --- | --------------- | ----------------------------------------------------- | ---- |
  | `L4-03 + L3-04`       | 기말/기초에 발생한 고액 조정 전표   | High     |     |                 |                                                       |      |
  | `L4-03 + L1-05/L1-07` | 고액 전표의 자가승인 또는 승인 누락 | High     |     |                 |                                                       |      |
  | `L4-03 + L4-04`       | 고액이면서 드문 차변-대변 계정 조합 | High     |     | `L4-03 + L4-01` | 매출 계정 특화 이상치이면서 전체 금액 기준으로도 고액 | High |

#### L4-04 — 희소 차대 계정쌍 (RareDebitCreditAccountPair) ✅

- **심각도**: 2
- **근거**: 240-A45(a) 비경상·저사용 계정, 315호
- **Phase 1 해석**: 비정상 확정 룰이 아니라, 해당 회사/기간 모집단에서 드물게 나타난 차변-대변 계정쌍을 검토 후보로 올리는 설명 가능한 약한 신호다.
- **탐지 로직**: engagement(회사·회계연도) 모집단에서 "정기 반복(recurring)에 못 미치는" 차변→대변 계정쌍을 희소로 본다.
  - **희소 기준 = cadence(주기) 기반**: engagement 기간 내 "분기 1회 미만"으로 등장한 계정쌍이 희소다. 1년 감사면 `빈도 ≤ 3`, 반기면 `≤ 1`로 **기간에 비례해 자동 조정**된다. 고정 퍼센트(구 하위 1%)·고정 count를 박지 않는다.
  - **근거**: 실제 회사의 "희소 비율 X%"는 회사·업종·계정체계마다 달라 공표된 안정값이 없고(학계도 자연 base rate 미상), 감사기준(AS2401·ISA240)에도 숫자 임계가 없다. 따라서 임계는 "정상 거래라면 분기 단위로는 반복된다"는 cadence 판단으로 정의하고, cadence는 감사인 입력으로 조정한다.
  - **engagement 단위 계산 필수**: 빈도는 회사·연도 단위로 센다. 여러 회사를 합본해 빈도를 세면 같은 쌍이 회사 간 재등장해 희소 정의가 붕괴하므로 금지한다(Engagement별 DuckDB 격리와 정합).
  - 빈도 계산은 merge 기반 벡터화 Cartesian product. 복합분개는 같은 전표의 모든 차변 행 × 모든 대변 행 조합을 생성한다(방향 구분: 차변계정→대변계정).
  - `gl_account`가 비어 있는 차변/대변 라인은 L4-04 계정쌍 계산에서 제외한다. 계정 누락은 L4-04가 아니라 `L1-02`/`L1-03` 계열 데이터 품질·계정 유효성 이슈로 평가한다.
  - 희소쌍이 하나라도 포함된 전표는 전표 전체 라인을 플래그한다.
  - 100라인 초과 대형 전표는 제외하지 않는다. 메모리 보호를 위해 `document_id + gl_account` 고유 차변/대변 계정쌍으로 압축하되, 압축된 쌍도 **동일한 cadence 기준**으로 희소를 판정한다. 구 "대형 전표면 신규 조합을 자동 희소로 간주"는 폐기하고, 대형 전표 압축으로 평가됐다는 사실만 `large_doc_distinct_pair` reason_code로 남긴다.
- **구현**: `anomaly_rules_statistical.py` → `c09_rare_account_pair()`
- **필요 피처**: `document_id`, `gl_account`, `debit_amount`, `credit_amount`
- **튜닝 파라미터**: cadence 임계(engagement 입력, 기본 "분기 1회 미만"). 구 `account_pair_rare_percentile`(0.01)은 long-tail 분포에서 `quantile(0.01)`이 항상 1로 붕괴해 무력했으므로 폐기한다.
- **결과 표현 (binary)**
  - 발화는 전표 단위 0/1이다. 희소쌍이 하나라도 포함된 전표는 전표 전체 라인에 `1.0`을 부여한다. score bucket 차등(구 0.25/0.35/0.45)은 폐기한다.
  - "얼마나 드무냐(쌍 개수)"는 강도이므로 룰이 점수로 가로채지 않는다. 강도·정황·조합은 모두 통합점수체계 소관이다(아래 PHASE1 점수 유입).
  - annotation은 사실값만 남긴다: `reason_codes`, `rare_pair_count`(개수는 점수가 아닌 사실 기록), `sample_pairs`, `threshold_count`(적용된 cadence 임계 빈도). 구 `score_bucket`은 남기지 않는다.
  - 대형 전표 압축 평가로 걸린 경우 `large_doc_distinct_pair` reason을 함께 남긴다(점수 가중이 아닌 사실 표시).
- **PHASE1 점수 유입**
  - L4-04는 `logic_mismatch` topic, `evidence_strength=medium`, `scoring_role=primary`로 정규화된다(역할 SoT는 `rule_scoring.py::RuleScoringMetadata`).
  - 룰이 binary(0/1)이므로 detector row score는 발화=`1.0` 단일값이다. bucket별 normalized contribution 차등(구 0.75 배율·0.1875/0.2625/0.3375)은 폐기하고, `rule_scoring.py`의 L4-04 bucket 상수·분기를 제거해 signal_strength가 binary로 흐르게 한다(L3-07/L3-09와 동일 ripple).
  - 강도(희소쌍 개수)·정황(`recurring`/`automated`/`batch` source면 정상 long-tail 가능성↑ → 다운웨이트)·조합 승격은 전부 통합점수·case priority가 담당한다. 희소 계정쌍 단독으로는 Medium/High를 만들지 않는다.
- **실무 사용 방식**
  - 단독으로 fraud 또는 회계처리 오류를 결론내리지 않는다.
  - `L3-04` 기말/기초, `L3-02` 수기전표, `L4-03` 고액, 승인/권한 룰과 겹칠 때 우선순위를 높인다.
  - `L4-04` 단독 케이스는 case priority에서 낮춘다. 특히 `recurring`, `automated`, `batch`, `interface`, `system` source가 대부분인 케이스는 정상 long-tail 조합 가능성이 높으므로 추가로 downgrade한다.
  - 회사·업종·ERP별 계정체계가 다르므로 Phase 1에서 범용 whitelist/blacklist 조합을 직접 유지하지 않는다.
- **Case priority 조정**
  - raw L4-04 hit는 그대로 유지한다. 탐지 coverage를 줄이지 않기 위해 희소쌍 후보 자체를 필터링하지 않는다.
  - `L4-04` 외 보강 룰이 없는 케이스는 `l404_only_penalty`를 적용한다.
  - 반복/자동 source 비중이 `recurring_source_ratio` 이상이면 `recurring_source_penalty`를 추가 적용한다.
  - 설정 위치: `config/phase1_case.yaml` → `priority_adjustments.rare_account_pair`
- **한계**
  - 도메인상 이상하지만 반복적으로 자주 등장한 조합은 희소하지 않으므로 놓칠 수 있다.
  - 정상적인 일회성 조정, 재분류, 연결조정, 시스템 전환 전표도 희소하다는 이유로 플래그될 수 있다.
  - 의미 기반 조합 이상은 Phase 2의 VAE/GNN/관계형 모델에서 보완한다.
- **DataSynth 평가 계약**
  - `UnusualAccountPair`는 confirmed anomaly subset이다.
  - confirmed `UnusualAccountPair` 라벨에는 null-side pair(`->2100`, `500060->` 등)를 넣지 않는다. 이런 문서는 `MissingField`/계정 누락 라벨로만 평가한다.
  - confirmed 라벨은 현재 L4-04 계산 기준에서 non-null 차변 GL과 non-null 대변 GL로 구성된 희소쌍을 최소 1개 포함해야 한다.
  - `v49_candidate`부터 `labels/rare_account_pair_review_population*`을 L4-04 review coverage로 사용한다.
  - `v110_candidate`부터 `labels/rule_truth_L4_04*`와 `labels/rare_account_pair_review_population*`은 현재 L4-04 detector output에서 직접 재산출한 동일한 raw review universe다.
  - `v120_candidate`부터 `labels/rare_account_pair_detector_universe*`는 `labels/rare_account_pair_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/rare_account_pair_confirmed_anomalies*`는 희소 계정쌍 중 보강 정황이 있는 일부만 담는다.
  - `labels/rare_account_pair_normal_controls*`와 `labels/rare_account_pair_legitimate_contexts*`는 정상 희소 계정쌍 context이며, raw L4-04 hit가 될 수 있어도 confirmed FP로 단정하지 않는다.
  - v120 기준 `rare_account_pair_legitimate_contexts`는 258문서 중 256문서가 L4-04 detector universe와 겹친다. 이는 정상 long-tail 계정쌍도 Phase 1 review 후보가 될 수 있다는 뜻이지, detector 오탐 확정이 아니다.
  - confirmed subset이나 normal control이 현재 detector universe 밖에 있으면 raw rule truth의 과탐/미탐으로 해석하지 말고 해당 subset sidecar의 stale 여부를 별도로 점검한다.
  - `v49_candidate` 분석에서 확인된 L4-04 미탐 12건은 모두 null 계정쌍이 섞인 라벨 계약 문제였으므로 DataSynth 라벨 생성 단계에서 제외해야 한다.
  - 100라인 초과 전표도 detector 평가 대상이다. 과거 `labels/rare_account_pair_excluded_large_docs*`는 legacy 진단 산출물로만 취급하고, pass/fail 분모에서 detector 제외 계약으로 사용하지 않는다.
  - 모든 희소 계정쌍을 `UnusualAccountPair`로 라벨링하지 않는다.
- **평가 계약**:
  - L4-04는 strict pass/fail 룰이 아니라 `coverage_anchor`다. confirmed `UnusualAccountPair` 라벨은 direct subset이고, raw hit는 희소 계정쌍 검토 모집단이다.
  - 발화가 binary라 score band는 없다. 검토 모집단 집계는 `rare_pair_review_docs`(전체), `ordinary_rare_pair_docs`, `large_doc_distinct_pair_docs`의 사실 분류로만 남긴다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `rare_pair_review_docs`를 우선 사용한다.
  - null-side 계정쌍은 L4-04 평가에서 제외하고 계정 누락/무결성 문제로 분리한다.

---
## 3. Phase 2 / PHASE1-2 (이관 — 별도 문서)

> 2026-06-17 분리. 본 DETECTION_RULES.md는 **PHASE1-1 룰(L1~L4 행 단위)** 의 SoT다.
> - **Phase 2 ML/DL 보조 분석**(구 §3 전체) → [DETECTION_RULES_PHASE2_ML.md](DETECTION_RULES_PHASE2_ML.md)
> - **PHASE1-2 family·macro**(L4-02 Benford·L4-05·D01·D02·GR01·GR03) → [DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD)
> - 구 §2.5 Variance(D01·D02)·§4.5 Graph Detector(GR) 카드는 DETECTION_RULES_PHASE1-2.MD로 이동.

