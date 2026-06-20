# Detection Rules — Phase 2: ML / DL 보조 분석

> 2026-06-17 [DETECTION_RULES.md](DETECTION_RULES.md)에서 분리. 본 문서는 PHASE2(VAE companion surface 등 ML/DL 보조 분석) 영역이다. PHASE1-1 룰(전표 행 단위)·PHASE1-2 family([DETECTION_RULES_PHASE1-2.MD](DETECTION_RULES_PHASE1-2.MD))와 비병합 독립 surface(3-surface 불변식).

---

<!-- 이하 DETECTION_RULES.md §3에서 byte-exact 이관 -->
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
4. **Local evidence provenance 강화**: 이후 요약·설명 단계가 어떤 로컬 근거와 어떤 계약 위에서 생성됐는지 남김

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
- `amount_score`, `control_score`, `duplicate_or_outflow_score`, `logic_score`, `timing_score`, `behavior_score`
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

- `timeseries`: statistical anomaly — 일별 burst robust z-score (median/MAD baseline), 그룹별 단기 빈도 robust z, 월말/분기말/연말 concentration. zero-preserving ECDF 정규화 후 결합 (2026-05-24 보강, `src/detection/timeseries_rules.py`). Phase 1 rule hit / 합성 라벨 입력 없음.
- `relational` (7 sub-detector — R01·R02·R03·R04 기본 + R05·R06·R07 graph/entity 2026-05-24): 신규 거래쌍, dormant 재활성(account/partner), 희귀 (account, partner) edge, user-account degree spike, IC 가격 편차, 문서 흐름 누락
- `duplicate`: exact duplicate, near duplicate, 반복 금액/설명 패턴
- `intercompany`: 법인 간 쌍방향, unmatched pair, 비정상 offset 패턴

### 3.3 모델 Family 구성

Phase 2는 하나의 모델이 아니라 여러 family를 병렬로 비교하고, 각 family에서 가장 나은 trial만 승격 대상으로 삼는다.

#### A3 Family Matrix (2026-05-17)

| Family | 동작 여부 | 학습 필요 여부 | Metric | `schema_hash` |
|---|---|---|---|---|
| `unsupervised` | active default | VAE/IF 학습 필요 | `unsupervised_selection_score` | string |
| `timeseries` | active default | stateless rule + calibration metadata | `burst_detection_rate` | null |
| `relational` | active default | stateless rule + calibration metadata | `new_counterparty_precision` | null |
| `duplicate` | active default | stateless rule + calibration metadata | `fuzzy_match_f1` | null |
| `intercompany` | active default | stateless rule + calibration metadata | `ic_match_completeness` | null |
| `supervised` | dormant | label gate 통과 시 학습 | `f1_macro` | string |
| `transformer` | dormant | label gate 통과 시 학습 | `f1_macro` | string |
| `sequence` | dormant, D047 guard 적용 | D047 통과 후 학습 | `f1_macro` | string |
| `stacking` | dormant | base family 결과 필요 | `f1_macro` | string 또는 null |

A3 기준 기본 운영 트랙은 `unsupervised`, `timeseries`, `relational`, `duplicate`, `intercompany` 5개다. `supervised`, `transformer`, `sequence`, `stacking`은 registry에는 남아 있지만 기본 실행 family에는 포함하지 않는다.

Rule-style family는 `model_bundle.pt`를 생성하지 않는다. 승격 시 `{model_dir}/phase2_<family>/vNNNN/calibration_metadata.json`에 preset, sub-detector, metric, flagged count, `schema_hash: null`을 저장한다. 이 score는 truth recall이 아니라 selection/provenance용 `rule_proxy_score` 해석이다.

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
- Native review surface note (2026-05-29):
  - Product default is `structural_moderate_audit_then_business_lane_split_v1`.
  - The primary surface interleaves R03/R07 structural relationship evidence with R01/R02
    moderate audit/business relationship evidence at 1:1.
  - R05/R06 high-volume context evidence is not mixed into the primary surface by default.
  - The 1:4 anchor variant remains a diagnostic-only upper-bound, not the adopted product policy.
  - PHASE1 all-document inclusion is broad review-universe coverage only; relational value is
    judged by PHASE1 TOP-N uplift, structural relationship evidence, and explanation incremental.

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
- Native case surface note (2026-05-29):
  - Duplicate native cases are evaluated as pair evidence units, not row-score hits.
  - The first review surface should preserve PHASE1 TOP100 complement value: fixed5 current
    document-diversity ordering places 19 truth-covering DuplicateCase documents outside PHASE1
    TOP100 in Duplicate TOP100, while evidence-diversity improves total coverage but mostly
    reinforces documents already high in PHASE1.
  - Evidence-diversity and grouped sidecar designs remain diagnostic/export candidates. They do not
    change PHASE1 priority/composite/ranking, PHASE2 family fusion, detector thresholds, or the
    production default duplicate selector.
  - PHASE1 rank-gap alone is not an adoption-safe duplicate selector; duplicate-specific pair
    evidence tier, amount/reference/text/partner similarity, and bounded review burden must remain
    the controlling review-candidate semantics.
  - Cross-batch PHASE1-uplift diagnostics show why the first-review default remains unchanged:
    evidence-diversity improves export coverage on fixed4, but on fixed5 it reduces PHASE1 TOP100
    complement value. PHASE1-gap case-grade ordering is also unstable across batches.

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

### 3.4 어떤 감사 검토 패턴을 보완하는가

Phase 2는 특정 유형 이름을 1:1로 직접 매핑해 부정을 확정하기보다, 다음과 같은 감사 검토 패턴군을 보완한다.

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

Rule-style family는 일반 AUC 대신 `rule_proxy_score` 성격의 정규화 점수를 사용해 leaderboard에 올린다. leaderboard의 metric name은 family별 의미를 드러내기 위해 `timeseries=burst_detection_rate`, `relational=new_counterparty_precision`, `duplicate=fuzzy_match_f1`, `intercompany=ic_match_completeness`로 저장하고, `metadata.metric_interpretation=rule_proxy_score`로 해석 범위를 고정한다.

`sequence` family와 `timeseries` family는 분리한다. `sequence`는 BiLSTM/attention 기반 사용자 temporal context 모델이며 D047의 leakage guard가 적용된다. A3 신규 `timeseries`는 transaction-level burst/frequency rule detector이므로 D047 보류 조건을 적용하지 않는다.

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

이 provenance는 DB 저장, 복원, export, Local Evidence Brief까지 연결된다.

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
