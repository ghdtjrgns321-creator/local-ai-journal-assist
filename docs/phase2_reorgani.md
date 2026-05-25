# Phase 2 Reorganization Memo

작성일: 2026-05-24

## 목적

이 문서는 Phase 2를 입사용 포트폴리오 관점에서 어떻게 설명하고 보강할지
정리한다. 현재 대시보드의 family 중심 UI는 유지한다. 사용자는 Phase 2를
하나의 ML/DL/statistical family layer로 이해하는 것이 더 직관적이며, family별
분리 표시보다 "여러 분석 영역이 병렬로 원장을 해석한다"는 메시지가 효과적이다.

따라서 목표는 UI를 나누는 것이 아니라, 각 family가 ML/DL/statistical 기반의
독립 anomaly signal로 설명될 수 있도록 코드, 문서, 평가 근거를 정리하는 것이다.

핵심 질문은 다음과 같다.

- Phase 2를 Phase 1과 어떻게 다르게 설명할 것인가.
- 현재 family 중심 UI를 유지하면서도 Phase 2를 ML/DL/statistical layer로
  설득력 있게 말하려면 무엇을 보강해야 하는가.
- DataSynth 합성 라벨만 있는 현재 조건에서 무엇을 학습/평가할 수 있는가.
- 실제 고객 CSV에는 라벨이 없다는 조건을 어떻게 한계와 확장 경로로 설명할 것인가.

## 포트폴리오 포지셔닝

Phase 2는 다음과 같이 설명한다.

> Phase 2는 라벨 없는 회계 원장 CSV를 대상으로 VAE/Isolation Forest,
> statistical anomaly detection, pair similarity scoring, graph/entity anomaly,
> probabilistic reconciliation을 family별로 결합한 ML/DL/statistical anomaly
> layer이다. Phase 1이 감사 룰 기반 review queue를 만든다면, Phase 2는 같은
> 원장을 독립적으로 분석해 중복, 시점, 관계망, 관계사, 비지도 분포 꼬리 관점의
> 추가 이상도 점수를 산출한다.

중요한 점은 "모든 family가 딥러닝 모델"이라고 주장하지 않는 것이다. 더 정확한
표현은 **ML/DL/statistical 기반 family layer**다.

| family | 포트폴리오 설명 | 모델링 성격 |
|---|---|---|
| `unsupervised` | VAE/IF 기반 비지도 이상탐지 | Deep learning + classical ML |
| `timeseries` | 거래 빈도·시점의 통계적 이상탐지 | Statistical anomaly detection |
| `duplicate` | 중복 후보 pair의 유사도·이상도 scoring | Pair similarity / anomaly ranking |
| `relational` | 거래처·계정·사용자 관계망 이상탐지 | Graph/entity anomaly |
| `intercompany` | 관계사 전표 대사·matching 이상탐지 | Probabilistic reconciliation |

현재 구현 중 일부 family는 아직 rule-style detector 성격이 남아 있다. 그러나
포트폴리오 방향은 해당 family를 제거하거나 UI에서 숨기는 것이 아니라, family별
score/ranking/anomaly 근거를 보강해 ML/DL/statistical layer로 설명 가능한 수준까지
끌어올리는 것이다.

## Phase 1과 Phase 2의 차이

Phase 1은 감사 룰 엔진이다. 정식 rule id가 붙은 탐지 결과를 만들고,
`flagged_rules`, `review_rules`, `anomaly_score`, `risk_level`, case priority의
근거가 된다. 즉 감사인이 "왜 이 항목이 review queue에 올라왔는가"를 설명하는
1차 감사 룰 근거다.

Phase 2는 같은 원본 CSV를 독립적으로 분석하는 anomaly layer다. Phase 1 결과를
학습 정답이나 입력 gate로 삼지 않고, 원장 전체에서 family별 score를 산출한다.
Phase 1 case와 결합되는 overlay는 화면과 감사 문맥을 위한 후처리이며, Phase 2의
기본 분석 단위는 원본 CSV 전체다.

정리하면 다음과 같다.

| 항목 | Phase 1 | Phase 2 |
|---|---|---|
| 핵심 역할 | 감사 룰 기반 review queue 생성 | ML/DL/statistical anomaly score 생성 |
| 입력 | 원본 회계 CSV | 원본 회계 CSV |
| 분석 방식 | deterministic audit rule | 비지도/통계/pair/graph/matching score |
| 결과 의미 | 룰 근거가 있는 감사 검토 후보 | 분포·관계·시점·중복 관점의 이상도 |
| 라벨 필요 여부 | 불필요 | 운영 기본 경로는 불필요 |
| 포트폴리오 메시지 | 도메인 룰 엔진 | 라벨 없는 데이터에 맞춘 anomaly layer |

이 차이를 유지하려면 Phase 2 family가 Phase 1 rule hit를 단순히 다시 포장하는
형태로 보이면 안 된다. 각 family는 "룰 위반 여부"보다 "score/ranking/anomaly
signal" 중심으로 설명되어야 한다.

## Phase 2 Standalone Contract

Phase 2 는 Phase 1 결과 CSV 를 입력으로 받는 후속 단계가 아니라, **원본/featured
회계 CSV 전체를 standalone primary input 으로 받는 독립 anomaly layer** 다.
Phase 1 case overlay 는 Phase 2 산출 이후의 optional post-step (overlay join /
display attribution) 으로만 결합한다.

### 계약 요약

| 항목 | 값 |
|---|---|
| primary input | `featured_df` (또는 raw GL DataFrame). 전수 모집단 |
| input scope | row-level 전체. Phase 1 case 또는 rule hit 로 잘라낸 부분집합 아님 |
| optional context | `Phase1CaseResult` — 추론 **이후** overlay join 으로만 사용 |
| 학습 입력 deny | `LEAKAGE_DENY_COLUMNS` ∪ `LEAKAGE_DENY_RULES` ∪ `_LEAKAGE_PATTERNS` (label/target/fraud/anomaly/risk/rule/score/model/prediction/probability/export/dashboard) |
| case overlay 정책 | `Phase2CaseOverlay` 는 PHASE1 `priority_score` 를 덮어쓰지 않음 (`phase2_adjusted_priority` 는 표시용) |
| batch_id 의미 | DB row UPDATE 키 (PHASE1 batch row 재사용). ML 입력 gating 과 무관 |

### 코드 경계

| 경로 | 역할 | 비고 |
|---|---|---|
| `src/services/phase2_inference_service.py::run_phase2_inference` | standalone inference entry-point | docstring 에 contract 명시. `phase1_case_result` 인자 없음 |
| `src/services/phase2_inference_service.py::_inherit_phase1_case_result` | post-inference overlay attach | session 의 PHASE1 결과를 결과 객체에 inherit. 입력 gate 아님 |
| `src/services/phase2_inference_service.py::_attach_phase2_case_overlays` | overlay join | standalone 결과의 row score 를 PHASE1 case 단위로 집계 |
| `src/services/phase2_training_service.py::run_phase2_training` | standalone training entry-point | docstring 에 contract 명시. `phase1_case_result` 는 manifest 용 |
| `src/services/phase2_training_service.py::_build_phase1_case_contract_metadata` | manifest only | feature firewall 통과 후 case feature 컬럼 목록만 기록 |
| `src/services/phase2_case_contract.py` | overlay-only 계약 모듈 | `PROVENANCE_ONLY_FIELDS` firewall + `PHASE2_CASE_FEATURE_COLUMNS` 화이트리스트 |
| `src/preprocessing/phase2_plan.py::_decide_column` | matrix builder deny | label/leakage/identifier/datetime/high-missing 자동 exclude |
| `src/pipeline.py::redetect(detection_scope="phase2_only")` | standalone detection scope | base detector 스킵 + family detector 만 병렬 실행 + `phase1_case_result=None` |

### Phase 1 결과가 Phase 2 입력 gate 가 아니라는 근거

1. `pipeline.redetect` 의 `phase2_only` 분기에서 `phase1_case_result = None`, `phase1_case_ref = {}` 로 강제. 학습이나 detection 호출 시 PHASE1 case 객체가 전달되지 않는다 (`src/pipeline.py:676-678`).
2. 추론 후 `_inherit_phase1_case_result` 가 호출자 세션의 `KEY_PHASE1_RESULT` 를 메모리상으로만 inherit 한다 (`src/services/phase2_inference_service.py`). PHASE1 결과가 없으면 `phase1_case_basis_*` status 만 attach 하고 return.
3. `_attach_phase2_case_overlays` 는 detection 산출물 (`result.results`) 과 PHASE1 case 를 결합하는 post-step. PHASE1 case 가 없으면 빈 리스트 overlay 를 부착하고 family score 산출 자체에는 영향 없음 (`src/services/phase2_case_family_aggregator.py:56`).
4. 학습 입력에서 Phase 1 산출 컬럼 (`composite_sort_score`, `topic_score_*`, `risk_level`, `flagged_rule_*`) 은 `_LEAKAGE_PATTERNS` 토큰 deny (rule/score/risk 등) 와 `LEAKAGE_DENY_RULES` 로 자동 제외 (`src/preprocessing/phase2_plan.py:29-42`).
5. case-level 학습 입력은 `PHASE2_CASE_FEATURE_COLUMNS` 화이트리스트만 허용하고, `PROVENANCE_ONLY_FIELDS` (phase1_case_id / primary_theme / top_rule_ids / phase1_case_priority 등) 는 `enforce_phase2_case_feature_firewall` 가 ValueError 로 차단 (`src/services/phase2_case_contract.py:102-121`).

### 다이어그램

```
raw / featured CSV  ─────┐
                         ▼
            standalone Phase 2 inference
            (run_phase2_inference / pipeline.redetect(phase2_only))
                         │
                         ▼
            row-level family scores + VAE anomaly score
                         │
                         ▼
            ┌────────────┴────────────┐
            │                         │
            ▼                         ▼
   Phase 2 row queue        PHASE1 Phase1CaseResult
                                      │
                                      └─► optional overlay join
                                              (_attach_phase2_case_overlays)
                                              → Phase2CaseOverlay
                                                (priority_score 보존)
```

### 비범위

- supervised target 으로 PHASE1 case priority 또는 `is_fraud` 를 사용하지 않는다.
- PHASE1 결과를 row matrix feature 로 join 하지 않는다 (case manifest 메타만 inference contract 에 기록).
- Phase 2 단독 실행을 위한 별도 batch_id 발급 경로는 현재 dashboard 에서 강제되지 않는다. CLI / 스크립트 수준 standalone 실행을 위해서는 `pipeline.redetect(detection_scope="phase2_only")` 직접 호출 + 외부 batch_id 발급이 필요하다.

## 현재 구현의 해석

현재 코드 기준 active family는 5개다.

| family | 현재 상태 | 포트폴리오상 해석 |
|---|---|---|
| `unsupervised` | VAE + Isolation Forest + ECDF | 이미 ML/DL family로 설명 가능 |
| `timeseries` | burst/frequency 중심 rule-style detector | statistical anomaly family로 보강 필요 |
| `duplicate` | exact/fuzzy/split/time-shift detector | pair scoring family로 보강 필요 |
| `relational` | 신규 거래처·휴면계정·IC 편차 등 domain detector | graph/entity anomaly family로 보강 필요 |
| `intercompany` | IC 미대사·불일치 detector | probabilistic matching family로 보강 필요 |

[phase2_training_service.py](../src/services/phase2_training_service.py)는
`timeseries`, `relational`, `duplicate`, `intercompany`를 rule-style family로
다룬다. 이 자체는 포트폴리오에서 숨길 필요가 없다. 대신 설명은 다음처럼 한다.

> Phase 2는 라벨 없는 감사 데이터에 맞춰 family별로 서로 다른 anomaly scoring
> 방식을 사용한다. VAE/IF는 비지도 모델이고, 나머지 family는 통계적 baseline,
> pair similarity, entity graph feature, reconciliation matching score처럼
> 감사 도메인에 맞는 모델링 방식으로 확장 가능한 구조다.

면접에서 "모두 딥러닝인가"라는 질문이 나오면 다음처럼 답한다.

> 모두 딥러닝은 아니다. Phase 2는 ML/DL/statistical anomaly layer다. VAE는
> 딥러닝 기반 비지도 모델이고, 다른 family는 라벨 없는 원장 데이터에 적합한
> 통계·유사도·그래프·matching 기반 score로 설계했다. 실제 감사 데이터에는 라벨이
> 없기 때문에 모든 영역을 supervised classifier로 만드는 대신, family별 anomaly
> score를 산출하고 합성 라벨은 검증용 benchmark로 사용했다.

## UI 방향

현재 Phase 2 UI의 family 중심 구조는 유지한다.

유지 이유:

- 포트폴리오에서 "여러 분석 영역이 병렬로 원장을 해석한다"는 메시지가 명확하다.
- `duplicate`, `timeseries`, `relational`, `intercompany`, `unsupervised`가 한 화면에
  있으면 Phase 2가 단일 모델이 아니라 family ensemble처럼 보인다.
- 감사 도메인에서는 모델 이름보다 "어떤 관점으로 원장을 봤는가"가 중요하다.
- family별 lane, matrix, contribution UI는 설명 가능성과 데모 효과가 좋다.

따라서 UI에서 VAE와 rule-style family를 별도 영역으로 나누지 않는다. 대신 각
family 카드와 설명 문구는 다음 방향으로 정리한다.

| family | UI/문서 표현 |
|---|---|
| `unsupervised` | VAE/IF 비지도 분포 이상 |
| `timeseries` | 시계열·거래 빈도 통계 이상 |
| `duplicate` | 중복 후보 pair 유사도 이상 |
| `relational` | 거래처·계정·사용자 관계망 이상 |
| `intercompany` | 관계사 대사·matching 이상 |

## Family별 보강 방향

### 1. `unsupervised`: VAE/IF 비지도 family

현재 가장 강한 Phase 2 family다. [vae_detector.py](../src/detection/vae_detector.py)는
VAE 재구성 오차와 Isolation Forest score를 ECDF로 결합한다. 실제 고객 CSV에는
라벨이 없으므로 이 family는 Phase 2의 기본 anchor로 유지한다.

보강 포인트:

- VAE/IF score가 부정 확률이 아니라 anomaly ranking임을 명확히 한다.
- 합성 라벨은 학습 target이 아니라 top-tail sanity check에 사용한다.
- 모델 bundle, schema hash, train distribution, ECDF 기준을 문서화한다.

### 2. `timeseries`: statistical anomaly family

**보강 완료 (2026-05-24)** — burst/frequency rule-style boolean 을 robust
z-score + zero-preserving ECDF + period-end concentration 결합으로 격상.
TS01/TS02 rule_id 와 `phase2_subdetector_tiers.yaml` lock 은 유지하고 내부
score 계산만 continuous 화했다.

#### Sub-signal 구성

| sub-signal | 정의 | TS01/TS02 매핑 |
|---|---|---|
| `daily_burst_positive_robust_z` | 일별 거래 건수 → 14일 rolling median+MAD baseline → modified z-score → noise floor 1.5 차감 → [0, 30] clip | TS01 본체 (s1) |
| `group_frequency_positive_robust_z` | vendor/account/user 그룹별 일자 단위 7일 trailing sum → 그룹 자체 시계열 robust z → noise floor 차감 | TS02 본체 (s2) |
| `period_end_concentration` | 월말/분기말/연말까지 거리 (D-3 선형 감쇠) × 일자 모집단 거래량 percentile (top tail) | TS01 보조 (s3, `sub_signal_only=true`) |

#### 결합식 (context-gated, 2026-05-24 추가)

```
s1 = zero_preserving_ecdf(daily_burst_positive_robust_z)
s2 = zero_preserving_ecdf(group_frequency_positive_robust_z)
s3_raw = period_end_concentration_score
amount_tail = row_amount_tail_score  (context-only, row score 직접 포함 X)

context_score   = max(s1, s2, amount_tail)
context_present = context_score >= ts_period_end_context_threshold  (= 0.50)
gated_s3        = s3_raw if context_present else min(s3_raw, ts_period_end_context_cap)  (= 0.30)

ts01_signal = max(s1, gated_s3)
ts02_signal = s2
row_score   = max(ts01_signal, ts02_signal)
TS01 flag   = (ts01_signal >= ts_burst_high_pctile) OR (gated_s3 >= ts_period_end_high)
TS02 flag   = (ts02_signal >= ts_freq_high_pctile)
```

- **period_end context gating**: ISA 240 ¶A41 의 "period-end transactions" 는
  routine 결산을 포함한다. unusual 로 격상하려면 amount/frequency/volume
  baseline 이상 신호가 함께 있어야 한다. context (s1 / s2 / amount_tail) 가
  ECDF 상위 절반 (threshold=0.50) 이상이면 period_end raw 그대로, 부족하면
  cap=0.30 으로 절단해 단독 strong 진입 차단 (boolean 임계 0.95 미달).
- 음의 z (거래량 급감) 는 `max(z, 0)` 로 제거. burst 정의에 부합.
- noise floor 1.5 는 modified z 의 표준 cutoff. partial window/cycle effect 차단.
- zero-preserving ECDF — 0 행은 0 보존, 양수 행만 `rank(method="max", pct=True)`.
- `row_amount_tail_score` 는 동률 amount false-positive 방지를 위해 unique
  amount value < 3 이면 inactive (graceful).
- ts_* 파라미터 9개 (`config/settings.py`): `ts_burst_window_days`,
  `ts_group_window_days`, `ts_group_min_support`, `ts_burst_high_pctile`,
  `ts_freq_high_pctile`, `ts_period_end_window_days`, `ts_period_end_high`,
  `ts_period_end_context_cap`, `ts_period_end_context_threshold`. 모두 audit
  rationale 주석 보유, truth-recall 튜닝 금지.

#### 자체 검증 — period-end-only routine 은 cap 이하

`tests/modules/test_detection/test_timeseries_rule.py::TestPeriodEndContextGating`
7 케이스로 잠금:
- routine period-end (모든 일자 5건, 동일 금액) → row_score ≤ 0.30, TS01 flag = 0
- period-end + daily burst → context 충족 → row_score > 0.30 + TS01 flag
- period-end + amount tail → context 충족 → row_score > 0.30
- non-period burst → 기존처럼 strong (≥ 0.95)
- small sample (3 행) → row_score ≤ 0.30
- Phase 1 / DataSynth 라벨 컬럼 미참조
- `metadata.period_end_gating` 키 shape 잠금 + JSON serializable

#### Phase 1/합성 라벨 의존성

- `flagged_rules` / `review_rules` / DataSynth 라벨을 입력으로 사용하지 않는다.
  Detector 는 raw featured DataFrame 만 받아 sub-signal 을 산출한다.
- 합성 라벨은 evaluation/sanity 용도이며 학습 target 이 아니다 (라벨 없는
  운영 데이터에서도 동일 score 산출).

#### 한계 및 후속

- `phase2_subdetector_tiers.yaml` 의 `distribution_metric` 문구는 옛 0.4/0.8
  이산값 기준이라 새 ECDF 분포로 갱신이 필요하다. 운영 측정 산출 후 별도
  D044 PR 에서 갱신한다 (본 PR 의 범위 외).
- noise floor 1.5 는 hardcode (settings 최소 유지 정책). 도메인 보정이 필요하면
  별도 PR 에서 ts_* 파라미터에 추가.

포트폴리오 설명:

> Timeseries family 는 월말·분기말 집중, 특정 거래처/계정의 단기 burst,
> 평소 빈도 대비 급증을 통계적 robust z-score baseline 과 zero-preserving
> ECDF tail 로 점수화한다.

### 3. `duplicate`: pair similarity/ranking family

현재 duplicate detector는 exact/fuzzy/split/time-shift rule에 가깝다. Phase 2답게
보이려면 row-level flag보다 pair-level scoring을 강조해야 한다.

보강 방향:

- 후보 pair generator 구성
- amount difference, date distance, text similarity, vendor/account/reference
  similarity를 feature화
- pair score를 산출하고 row/case score로 aggregate
- exact duplicate뿐 아니라 near-duplicate와 split transaction을 ranking으로 처리
- pair queue를 별도 artifact로 남긴다.

포트폴리오 설명:

> Duplicate family는 단일 룰 hit가 아니라 후보 거래 pair를 만들고 금액·일자·적요·
> 거래처 유사도를 종합해 중복 가능성이 높은 pair를 ranking한다.

#### 구현 상태 (2026-05-24)

- 후보 pair 생성과 feature 계산은 [`src/detection/duplicate_pair_features.py`](../src/detection/duplicate_pair_features.py)
  의 `build_duplicate_pair_artifact()`로 분리한다. 기존 4개 row scorer
  (`b05a_exact_duplicate` 등)의 반환 타입은 `pd.Series`로 유지한다. row score 식과
  KPI baseline은 변경 없음.
- `DuplicateDetector.detect()` 는 row scoring 후 helper를 호출해
  `result.metadata["pair_artifact"]`에 JSON 직렬화 가능한 dict로 주입한다.
  schema는 `schema_version / total_candidate_pairs / candidate_pairs_after_caps /
  retained_pairs / truncated / truncation_reason / rule_pair_counts / top_pairs /
  coverage`. `total_candidate_pairs`는 cap 적용 후 helper가 생성한 pair 총수,
  `candidate_pairs_after_caps`는 정렬 전 후보 record 수, `retained_pairs`는
  top-N sanitize 후 metadata에 실제 보존된 pair 수다.
- pair feature: `amount_diff_ratio`, `amount_similarity`, `date_distance_days`,
  `date_similarity`, `text_similarity`, `same_account`, `same_partner`,
  `reference_similarity`. 컬럼 부재 시 해당 feature는 `None`(graceful).
- blocking: gl_account 그룹 + amount tolerance sweep (fuzzy) + date sliding window
  (split/time-shift). 동일 도메인 규칙을 row scorer와 helper가 독립 적용한다.
- 안전장치: `duplicate_max_group_size` (group skip), `duplicate_max_pairs_per_row`
  (단일 row 진입 cap, default 200), `duplicate_max_total_pairs` (전역 cap,
  default 200_000), `duplicate_pair_artifact_max_rows` (default 50_000 이상이면
  artifact 부분 skip — row scoring SLA 보호), `duplicate_pair_artifact_top_n`
  (metadata payload top-N, default 500).
- sanitization: `top_pairs`에는 원문 `line_text` / `reference` 노출 금지. 수치
  feature, `rule_id/rule_source`, `left_index/right_index`, `document_id` (있으면)만
  포함한다.

#### 한계와 사용 규약

- pair_artifact는 evidence/attribution 보강용이며 row score를 끌어올리는 추가
  가중치로 사용하지 않는다. row score 식 변경은 KPI baseline 갱신을 동반해야 한다.
- 정상 반복 거래(월세, 정기 카드결제, 주차료)도 동일 blocking에 들어오므로
  pair는 그 자체로 부정 증거가 아니다. 감사인 검토 우선순위 ranking 보조용.
- PHASE1 rule hit는 feature/label로 사용하지 않는다 (`LEAKAGE_DENY_RULES` 준수).
- 합성 라벨(`is_fraud`, `mutation_type`)은 sanity assertion에만 사용. threshold나
  weight 결정에 사용 금지.
- 100k 행 row scoring SLA 1초를 유지하기 위해 대용량 입력에서는 artifact만 skip
  하고 `coverage.skipped_for_size=True` + `truncation_reason="input_too_large"`를
  기록한다. row score/details는 항상 산출된다.

### 4. `relational`: graph/entity anomaly family

기존 R01(신규 거래처)·R02(휴면 계정)·R03(IC 이전가격)·R04(문서흐름)에
2026-05-24부터 graph/entity anomaly 3종(R05~R07)을 공식 등록했다. networkx
신규 의존 없이 pandas vectorization 만으로 산출한다.

| ID | 이름 | 입력 | tier | 설명 |
|---|---|---|---|---|
| R05 | rare_account_partner_edge | `gl_account` × `trading_partner` × `posting_date` | moderate | (account, partner) edge frequency 의 1-ECDF (rank_pct, method=average) + 첫 등장 후 선형 recency 감쇠. 합성 `0.7·rarity_ecdf + 0.3·recency_strength` (rare-tier mask: `freq ≤ rel_r05_min_freq` 행만, unique pair count < `rel_r05_min_pair_population`(50) 시 small sample 무효화). |
| R06 | user_account_degree_spike | `created_by` × `gl_account` × `posting_date` | moderate | period bucket(M/W) 별 user-account unique degree 의 robust z-score (MAD) 산출 후 `z > rel_r06_z_threshold` 행에 한해 z 분포의 ECDF rank (rank_pct, method=average) 부여. cap 없이 ranking 해상도 보존. `rel_r06_min_users`(10), `rel_r06_min_user_obs`(3) guard. |
| R07 | dormant_partner_reactivation | `trading_partner` × `posting_date` | moderate | trading_partner 단위 `inactive_days>180` 후 `reactivation_window=7` 거래에 점수 전파. blank/NaN partner 제외. R02(account level)와 차별. |

설계 근거 (사용자 조정 2026-05-24):

- **R05 min_pair_population guard** — 전체 unique pair 수가 작은 small sample에서 모든
  row가 rare로 분류되는 것을 막는다. 기본 50.
- **R05 rarity 연속화 (2026-05-25)** — 기존 `1/freq` + binary recency boost 는
  {1.0, 0.5, 0.33, …} hyperbolic 격자로 이산화되어 lane sort 해상도를 잃었다.
  모집단 행 freq 분포의 `1 - rank_pct(freq, method=average)` 와 선형 recency
  감쇠 `max(0, 1 - days_since_first/lookback_days)` 합성 `0.7/0.3` 으로 교체.
  rare-tier mask (freq ≤ min_freq) 는 도메인 가드로 유지.
- **R06 period bucket 단순화** — pandas rolling unique 는 구현 복잡도가 높아 첫 구현은
  월/주 bucket 기반 user-period degree spike 로 시작한다. rolling window 는 후속.
- **R06 z-rank ECDF (2026-05-25)** — 기존 `min(z/(z_threshold*3), 1.0)` 은 극단
  spike 가 cap 으로 평탄화되어 ranking 해상도를 잃었다. spike-mask
  (`z > z_threshold`) 내부 z 분포의 ECDF rank (rank_pct, method=average) 로 교체.
  spike 외 행은 0 유지.
- **R07 blank partner 제외** — `trading_partner == ""` 또는 NaN 행을 하나의 partner로
  묶으면 오탐이 크다. dormant 판단 모집단에서 명시적으로 제외.
- **R07 tier moderate** — dormant partner reactivation 은 related-party 발견(ISA 550 A19)
  보다 PCAOB AS 2401 §B7 "unusual activity in dormant business relationships" 에 가까운
  보조 신호. strong 단독 review 가 아닌 보강 증거 필요.

한계 / 비범위:

- **R08 cross-company relation rarity 비범위** — `company_code` 가 단일 회사 CSV에서는
  변별력이 낮다. multi-company/IC 데이터 계약과 연결해 별도 PR.
- **networkx 미도입** — high-cardinality entity (10k+ partner) 에서 add_edge 루프 OOM 위험.
  pandas groupby/value_counts vectorization 만 사용. networkx 기반 community detection 은
  GraphDetector(track=`graph`) 별도 track 에서 GR01/GR03 으로 다룬다.
- **Phase 1 rule hit 미사용** — R05~R07 의 input feature 는 원본 컬럼만. PHASE1 score/
  flag 를 학습 input 으로 쓰지 않는다 (본 문서 §Phase 1 차이 정합).
- **UI 변경 없음** — 신규 sub-detector 는 기존 RelationalDetector contract(details/
  rule_flags/scores)와 phase2_case_family_aggregator 의 family ECDF 경로에 자동
  흡수되며 별도 UI 컴포넌트 추가 없음.

포트폴리오 설명:

> Relational family는 거래처·계정·사용자 간 관계망을 만들고, 새로운 관계,
> 드문 조합, 휴면 거래처 재활성화, 사용자별 계정 degree spike 같은 graph/entity
> anomaly 를 frequency 기반 score 와 robust z-score 로 점수화한다. 데이터 계약이
> 부족한 고객 CSV 에서는 sub-detector 별 graceful degradation 으로 0 score 를 반환한다.

### 5. `intercompany`: probabilistic reconciliation family

Intercompany는 데이터 계약 의존도가 크다. `is_intercompany` 플래그만 있으면 강한
ML family로 보이기 어렵다. 상대 법인 전표, reference, partner mapping이 있어야
matching anomaly로 설명할 수 있다.

보강 방향:

- IC matching에 필요한 최소 컬럼 계약 정의
- company A entry와 company B entry 후보 pair 생성
- amount/date/reference/counterparty/account mapping similarity 산출
- unmatched, amount mismatch, timing gap을 probabilistic score로 표현
- 데이터가 부족할 때는 "matching contract insufficient" 상태를 명확히 표시

포트폴리오 설명:

> Intercompany family는 관계사 간 대응 전표를 후보 pair로 만들고 금액·일자·참조번호·
> 거래처 매핑 유사도를 기준으로 미대사 또는 불일치 가능성을 점수화한다.

#### 보강 1차 구현 (2026-05-24)

`IntercompanyMatcher` 는 기존 IC01/IC02/IC03 hard-threshold rule 을 보존하면서
PHASE2 internal probabilistic surface 를 additive 로 추가한다.

데이터 계약 (3-tier graceful):

| tier | 조건 | 동작 |
|------|------|------|
| `L1_exact` | `company_code` multi + `trading_partner` + `reference` 중 stripped length ≥ `reference_min_length` 인 row 가 1건 이상 | 4-term match_score 산출. pair 별로 reference 양측이 effective 일 때만 reference weight 적용, 아니면 amount/date/counterparty 로 재정규화 |
| `L2_aggregate` | `L1_exact` 에서 `reference` 누락 또는 모든 row 가 `reference_min_length` 미만 (effective empty) | reference weight = 0 + amount/date/counterparty 합 1 재정규화. 완전 매칭 row 가 nonzero floor 에 묶이지 않게 함 |
| `L3_insufficient` | `company_code` 단일/부재 | 신규 prob = 0, warning + metadata 노출, 기존 IC01~03 동작 보존 |

L1 tier 안에서도 reference 가 일부 row 에만 있는 mixed 배치를 대비해 **pair-level
effective weight** 를 추가로 적용한다. 각 pair 의 rec/pay reference 가 모두
`reference_min_length` 이상일 때만 reference weight 를 살리고, 한쪽이라도 짧거나
비어 있으면 그 pair 한정으로 reference weight 를 0 으로 두고 amount/date/counterparty
합 1 로 재정규화한다. 그래서 reference 가 없는 정상 pair 가 reference weight 0.20
floor 에 묶이지 않는다.

후보 pair blocking 은 사전 selectivity 확보를 우선한다:

1. **join key = (amount log-bucket × cp_block)**. `cp_block` 는 rec 의 `trading_partner` (없으면 `company_code`) ↔ pay 의 `company_code` (없으면 `trading_partner`) 매칭 anchor 다. 빈 키는 unique tag 로 치환해 cross-empty merge 폭증을 차단한다.
2. merge 직후 `posting_date` `max_day_diff` window 로 early prune.
3. per-merge 와 final concat 두 단계에서 row 당 `max_candidates_per_row` (기본 50) cap. amount distance 가까운 top-K 만 유지하고 capped warning 을 남긴다.

매칭 점수는 다음 가중합이다.

```
match_score = w_amt · amount_similarity        # 1 - |a-b| / max(|a|,|b|), cross-currency 시 0 (weight 재정규화 없음)
            + w_date · date_proximity          # 1 - min(|Δdays|, max_day_diff) / max_day_diff
            + w_ref  · reference_similarity    # rapidfuzz token_set_ratio / 100, 양측 len ≥ min_length 일 때만
            + w_cp   · counterparty_mapping    # cc ↔ trading_partner cross 양방향 1.0, 한 방향 0.5
```

가중치 default (`audit_rules.yaml::patterns.intercompany.matching_weights`) 는
amount 0.40 / date 0.25 / reference 0.20 / counterparty 0.15 이며 합 1 로 정규화된다.

row 점수는 best candidate 기준이다.

- `ic_unmatched_prob = 1 - best match_score`. 후보가 0 개인 IC row 는 1.0 으로 두되
  user-facing 문구에서는 "unmatched review signal" 로 표현하고 confirmed violation 으로
  격상하지 않는다.
- `ic_amount_prob = 1 - best amount_similarity`
- `ic_timing_prob = 1 - best date_proximity`

세 컬럼은 `DetectionResult.details` 에 추가되며 severity normalization 을 적용하지 않는
0~1 raw probability 다. `DetectionResult.scores` 는 기존 IC01~03 severity 정규화 점수와
row-wise max 로 결합되어 PHASE2 family overlay (zero-preserving ECDF + Noisy-OR) 에
자연 흡수된다. `metadata["probabilistic_reconciliation"]` 에 contract tier / candidate
count / capped / warnings / weights / params 가 노출되며 pair queue artifact 는 노출
하지 않는다 (최소 surface 원칙).

명시 비범위:

- canonical rule id (IC04 등) 신설 없음. `SEVERITY_MAP`, `RULE_CODES`,
  `RULE_DETAIL_METADATA_REGISTRY`, `_RULE_STYLE_SUB_DETECTORS`,
  `config/phase2_subdetector_tiers.yaml` 모두 변경 없음
- Phase 1 rule hit (`flagged_rules`, `priority_score`, ...) / DataSynth truth (`is_fraud`,
  `mutation_*`) / `document_id` 식별자는 입력으로 사용하지 않음
- UI 변경 없음. IC01 evidence_level / review_reason sidecar 계약 보존
- `Phase2CaseOverlay.sub_detectors` 격리 — `ic_unmatched_prob` / `ic_amount_prob` /
  `ic_timing_prob` 컬럼은 family score / Noisy-OR 결합에만 기여하고
  `phase2_case_family_aggregator._top_subdetectors_for_case` 의 tier registry 화이트
  리스트 필터로 sub_detectors entry 에서 제외된다. tier registry 등록되지 않은 모든
  detail column 에 동일 정책이 적용된다. PHASE3 narrator / export 표시 결정은 후속
  PR 에서 별도 tier 등록 또는 `internal_signals` metadata 채널로 처리

## DataSynth 합성 라벨 사용 원칙

현재 데이터는 합성데이터가 중심이다. DataSynth는 시나리오 라벨을 제공할 수 있으므로
개발과 평가에 유용하다. 다만 실제 고객 CSV에는 라벨이 없기 때문에 합성 라벨을
운영 모델의 정답으로 과장하면 안 된다.

사용 원칙:

- 합성 라벨은 training target보다 evaluation/sanity benchmark로 우선 사용한다.
- supervised model은 synthetic-only 성능으로 active 승격하지 않는다.
- 합성 라벨 기반 precision/recall은 포트폴리오에서 "synthetic benchmark"로 표시한다.
- 실제 운영 설명에서는 anomaly score, ECDF tail, review capacity, stability를
  중심 지표로 사용한다.
- DataSynth shortcut을 학습하지 않도록 leakage deny-list와 trivial baseline을 함께 본다.

가능한 활용:

- family별 top-k recall sanity check
- score distribution과 tail capture 측정
- normal high ratio와 score degeneracy 점검
- detector 변경 전후 regression test
- synthetic scenario별 coverage 비교

금지 또는 주의:

- 합성 라벨로 학습한 supervised 모델을 실제 fraud probability로 설명하지 않는다.
- DataSynth 성능 수치를 실제 고객 데이터 성능으로 주장하지 않는다.
- Phase 1 rule hit 또는 생성기 흔적을 학습한 모델을 독립 ML로 설명하지 않는다.

## 실제 고객 CSV에는 라벨이 없다는 조건

실제 운영 데이터에는 일반적으로 `is_fraud`, `is_anomaly`, scenario label이 없다.
따라서 Phase 2의 기본 운영 경로는 라벨 없이 fit 또는 score 산출이 가능한 방식이어야
한다.

운영 기본 흐름:

```
실제 CSV
  → Phase 2 feature/profile 생성
  → family별 anomaly score 산출
  → ECDF 또는 training distribution 기준 정규화
  → family contribution / lane / top-tail queue 표시
  → 감사인 review feedback 축적
  → golden set 확보 후 supervised shadow benchmark
```

이 구조에서 supervised/transformer/sequence/stacking은 삭제하지 않는다. 다만
감사인이 검토한 golden set 또는 익명화된 실제 라벨 데이터가 생기기 전까지는
shadow benchmark로 둔다.

## 한계점과 방어 논리

한계점은 명확히 말한다.

현재 DataSynth는 포트폴리오 개발과 회귀검증에는 충분하지만, 실제 감사 데이터의
복잡성을 완전히 대변하지 못한다. 회사별 ERP 관행, 정상 예외, 승인 프로세스,
거래처 관계, 계정 사용 관행을 모두 반영하기 어렵다. 따라서 합성 라벨로 학습한
supervised 모델을 운영 환경의 부정 확률로 해석하지 않는다.

포트폴리오에서 사용할 수 있는 표현:

> 현재 Phase 2는 DataSynth 합성 데이터로 개발·검증했다. 합성 데이터는 시나리오
> 라벨을 제공하므로 detector sanity check와 회귀검증에는 유용하지만, 실제 감사
> 데이터의 업무 맥락과 정상 예외를 완전히 대변하지는 못한다. 따라서 production
> claim은 하지 않고, 실제 적용을 위해서는 감사인이 검토한 golden set 또는 익명화된
> 실제 원장 데이터가 필요하다. 해당 데이터가 확보되면 현재 구조의 supervised,
> transformer, sequence, stacking 모델을 재학습하고 temporal holdout,
> company holdout, user/group split, leakage audit을 통과한 뒤 승격할 수 있다.

이 한계는 약점이 아니라 설계 성숙도로 설명한다. 실제 감사 데이터에서 라벨이 없다는
문제를 인식했고, 그 조건에 맞춰 기본 경로를 비지도/통계 anomaly로 설계했으며,
라벨 확보 이후 supervised 확장 경로를 열어 두었다는 점이 포트폴리오 가치다.

## 실행 Task

UI 분리 없이 Phase 2를 ML/DL/statistical family layer로 강화하려면 다음 작업을
진행한다.

| 우선순위 | 트랙 | 목표 |
|---|---|---|
| 1 | Phase 2 narrative 정리 | family 중심 UI와 ML/DL/statistical 설명을 일치시킨다 |
| 2 | Standalone Phase 2 contract | Phase 1 결과 없이 원본 CSV에서 family score를 산출한다 |
| 3 | Timeseries 보강 | statistical baseline/ECDF score로 격상한다 |
| 4 | Duplicate 보강 | pair similarity/ranking artifact를 추가한다 |
| 5 | Evaluation harness | 합성 라벨을 evaluation/sanity benchmark로 고정한다 |
| 6 | Relational 보강 | graph/entity anomaly feature를 추가한다 |
| 7 | Intercompany 보강 | matching contract와 probabilistic score를 추가한다 |
| 8 | Portfolio packaging | 한계점, golden set 확장, demo flow를 정리한다 |

혼자 진행할 경우 최소 유효 범위는 다음이다.

1. 문서와 UI 문구를 family 중심 ML/DL/statistical layer로 정리한다.
2. Phase 2 standalone score contract를 명확히 한다.
3. `timeseries`를 statistical anomaly score로 보강한다.
4. `duplicate`를 pair scoring 구조로 보강한다.
5. 합성 라벨 기반 family evaluation report를 만든다.

이 정도면 Phase 2를 포트폴리오에서 "라벨 없는 감사 데이터에 맞춘
ML/DL/statistical anomaly layer"로 충분히 설명할 수 있다.

## 교차 참조

- Phase 1/2 경계와 라벨 정책: [CONSTRAINTS.md](CONSTRAINTS.md)
- Phase 2 governance: [PHASE2_GOVERNANCE_DESIGN.md](PHASE2_GOVERNANCE_DESIGN.md)
- Phase 2 fitting audit: [PHASE2_FITTING_AUDIT.md](PHASE2_FITTING_AUDIT.md)
- Phase 2 ML feasibility: [completed/phase2_ml_feasibility.md](completed/phase2_ml_feasibility.md)
- S9 value baseline: [completed/S9_phase2_value_baseline.md](completed/S9_phase2_value_baseline.md)
- VAE/IF detector: [../src/detection/vae_detector.py](../src/detection/vae_detector.py)
- Phase 2 training service: [../src/services/phase2_training_service.py](../src/services/phase2_training_service.py)
- Phase 2 case overlay: [../src/services/phase2_case_contract.py](../src/services/phase2_case_contract.py)
