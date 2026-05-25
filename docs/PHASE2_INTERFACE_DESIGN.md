# PHASE1 ↔ PHASE2 Interface Design

> 작성일: 2026-05-15
> 상태: 설계 문서 초안. 결정 1/2/3 사용자 확정 후 lock 예정. 코드/yaml/스키마 변경은 별도 컨텍스트.
> 단일 출처(SoT): 본 문서. PHASE2 row feature contract / prior 활용 정책 / ml_score 결합 정책의 합의 기록.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

## PHASE1 역할 원칙 (재확인)

PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1 출력은 **감사인 review queue 후보와 우선순위**다. PHASE2 ML은 이 후보 집합 위에서 (a) row-level anomaly 신호를 보강하고 (b) case-level adjusted priority를 overlay 한다. **PHASE2가 PHASE1 ranking을 덮어쓰지 않는다**는 것이 본 문서의 lock 전제다.

## Phase 2 Standalone Contract (선결 lock)

PHASE2 ML 은 **원본/featured 회계 CSV 전체를 standalone primary input** 으로 받는다. PHASE1 case priority, rule hit, review queue, composite_sort_score 가 PHASE2 detection 입력이나 학습 gate 로 들어가지 않는다. PHASE1 결과는 PHASE2 산출 이후의 optional overlay join 으로만 결합한다.

본 lock 의 전체 계약·코드 경계·검증 근거는 [phase2_reorgani.md §Phase 2 Standalone Contract](phase2_reorgani.md#phase-2-standalone-contract) 단일 출처를 참조한다. 본 문서의 결정 1/2/3 은 이 standalone contract 위에서 row matrix / prior 활용 / ml_score 결합 정책을 lock 한다.

## 범위

본 문서는 다음 3가지 인터페이스 결정만 다룬다.

1. **결정 1**. PHASE2 row feature contract — row-level matrix 입력/라벨/deny-list 컬럼 매트릭스.
2. **결정 2**. PHASE1 산출물(`composite_sort_score`, `topic_score_breakdown`) 의 PHASE2 활용 정책 — 입력 feature 포함 여부.
3. **결정 3**. PHASE2 `ml_score` 와 PHASE1 ranking 의 결합 정책 — override / 보강 / 독립.

비범위:
- PHASE2 모델 알고리즘 (VAE/IF/XGBoost 등)
- PHASE3 Narrator citation 구현 (별도 spec)
- DataSynth fitting / promotion gate
- dashboard tab_phase2 UI 구현

## 근거 산출물

- `artifacts/phase1_audit_phase2_3_interface.md` (P-7 §1, §3, §5)
- `docs/raw-plan/05a-detection-ml.md`
- `docs/PHASE3_REVIEW_NARRATOR_SPEC.md`
- `src/models/phase1_case.py` — `CaseGroupResult`, `RawRuleHitRef`, `CaseDocumentRef`
- `src/services/phase2_case_contract.py` — `PHASE2_CASE_FEATURE_COLUMNS`, `Phase2CaseOverlay`
- `src/preprocessing/phase2_plan.py`, `src/preprocessing/phase2_matrix.py`
- `src/preprocessing/constants.py` — `LABEL_COLUMNS`, `LEAKAGE_DENY_COLUMNS`, `LEAKAGE_DENY_RULES`
- `artifacts/phase1_cases/_anonymous/*.json`

---

## 1. 현 PHASE2 구현 요약

본 결정은 코드와 정합해야 한다. 현 코드 상태:

### 1.1 row-level matrix (`Phase2AutoencoderMatrixBuilder`)

- 입력: EDA → `Phase2PreprocessingPlan.decisions` → matrix builder
- 컬럼 분류 (`role`): `numeric`, `amount`, `categorical_low`, `categorical_high`, `boolean`, `sparse_dropped` → `has_{column}` indicator
- 변환기: `SignedLogTransformer`, `NumericPolicyTransformer`, `RareCategoryOneHotEncoder`, `FrequencyCountEncoder`
- 출력 schema: `feature_names_`, `output_feature_groups_`, `schema_hash_`
- deny: `phase2_plan._decide_column` 에서 `LABEL_COLUMNS` / `LEAKAGE_DENY_COLUMNS` / `_LEAKAGE_PATTERNS` (label, target, fraud, anomaly, risk, rule, score, model, prediction, probability, export, dashboard) / `_ID_NAMES` / `_*_id` / datetime / `high_missing >= 0.90` 일괄 exclude. `LEAKAGE_DENY_COLUMNS` 는 `src/preprocessing/feature_groups.py::classify_features` 와 `feature_quality.apply_feature_quality_policy` 에서도 동일하게 exclude.
- 단일 사용 deny: `f_manual` (`phase2_plan._SINGLE_USE_DENY`) — interaction feature 형태로만 진입 허용

### 1.2 case-level overlay (`src/services/phase2_case_contract.py`)

- `PHASE2_CASE_FEATURE_COLUMNS` — ML-safe case features 20개 (rule_diversity_count, evidence_type_count, theme_entropy, cross_process/user/counterparty_flag, repeat_*, document_count, row_count, total_amount, amount/control/logic/timing/behavior_score, has_*).
- `PROVENANCE_ONLY_FIELDS` — display/debug 전용 (phase1_case_id, primary_theme, secondary_tags, top_rule_ids, raw_rule_hits, representative_explanation, review_focus, risk_narrative, recommended_audit_actions, rule_evidence_summary, phase1_case_priority, phase1_base_priority, phase1_priority_adjustments). **PHASE2 입력 금지** firewall (`enforce_phase2_case_feature_firewall`).
- `Phase2CaseOverlay` — `phase2_family_scores`, `phase2_adjusted_priority`, `precision_adjustment_reason`, `detector_statuses`, `phase2_inference_contract`, `phase2_training_report_id`. **PHASE1 `priority_score` 를 덮어쓰지 않는다** (`build_phase2_case_overlays` docstring).
- `_adjusted_priority = clamp01(base_priority * 0.7 + mean(family_scores) * 0.3)` — 사용처는 overlay 노출용. PHASE1 ranking은 변경되지 않음.

### 1.3 inference service (`src/services/phase2_inference_service.py`)

- `run_phase2_inference` → `pipeline.redetect(..., detection_scope="phase2_only")` 호출
- 결과 객체에 `phase2_training_report_id`, `phase2_inference_contract`, `phase2_inference_mode`, `phase2_case_overlays` 부착
- `_attach_phase2_case_overlays` 가 `phase1_case_result` 가 상속된 뒤 overlay 생성

### 1.4 정합성 판정

- 결정 1 row matrix contract: 부분 존재. 단, **row-level citation 식별자 (`document_id` + `row_index` / `record_id`)** 가 ML 입력 deny 와 PHASE3 citation source 사이에서 명시적으로 분리되어 있지 않다. 명세 필요.
- 결정 2 prior 활용: 현 코드는 옵션 A (배제) 에 정합. case-level feature는 rule_id/theme/composite_sort_score 가 아닌 별도 ML-safe column 사용.
- 결정 3 ml_score 결합: 현 코드는 옵션 Z (independent overlay) 에 정합. PHASE1 priority_score 보존.

본 문서는 위 정합을 **명시적으로 lock** 하고, 결정 1 row contract 의 누락된 명세를 보충한다.

---

## 2. 결정 1 — PHASE2 row feature contract

### 2.1 식별자

| 컬럼 | 역할 | ML 입력 | PHASE3 citation |
|------|------|--------|------|
| `document_id` | 전표 ID | ❌ deny | ✅ `journal_id` |
| `row_index` | 전표 내 행 번호 (0-based) | ❌ deny | ✅ `line_no` |
| `record_id` | 전체 GL 내 unique row 식별자 | ❌ deny | ✅ row 식별 보조 |

**원칙**: 식별자는 학습 입력 금지, citation 출력 전용. row matrix는 식별자 없는 feature 만 보유. inference 시 `row_index` 보존을 위한 별도 키 컬럼 (예: `_row_key`) 을 matrix 와 분리해서 유지.

### 2.2 입력 feature 분류

#### (a) 원장 컬럼 (raw GL columns)

| 컬럼 | role | 처리 | 비고 |
|------|------|------|------|
| `debit_amount`, `credit_amount`, `amount`, `*_amt` | numeric/amount | `SignedLogTransformer` | 금액 컬럼 자동 검출 (`_is_amount_column`) |
| `tax_amount`, `discount_amount` | numeric/amount | `SignedLogTransformer` | 면세/영세율은 `tax_amount=0/NaN` 으로 정상 통과 |
| `gl_account`, `business_process`, `counterparty_id` | categorical_high | `FrequencyCountEncoder` | unique_count >= 50 |
| `user_persona`, `currency`, `posting_status` | categorical_low | `RareCategoryOneHotEncoder` | unique_count < 50 |
| `is_period_end`, `is_weekend`, `is_holiday` | boolean | astype(float) | |
| `posting_date`, `created_at` | datetime | ❌ exclude (raw) | 파생만 사용 |

#### (b) 파생 feature (engineered)

| 컬럼 | 정의 | 비고 |
|------|------|------|
| `amount_zscore` | counterparty/process 그룹 내 amount z-score | float precision 가드 |
| `amount_zscore_log` | signed log amount 의 그룹 z-score | tail 보존용 |
| `weekday_idx` | posting_date.weekday() | 0-6 |
| `month_idx`, `fiscal_period_idx` | posting_date.month, derived fiscal | |
| `hours_after_close` | posting 시각 - 영업 종료 시각 | NaT 가드 (np.busday 함정) |
| `time_zone_category` | normal/after_hours/weekend/holiday | categorical_low |
| `period_end_flag` | 결산기 ±3 영업일 | boolean |
| `repeat_within_30d` | 동 counterparty/account 30일 내 빈도 | numeric |
| `amount_round_indicator` | amount 가 10^k 근접 여부 | boolean |
| `f_manual_x_amount_high` | 수기 입력 × high amount (interaction) | `f_manual` 단독 사용 금지 우회 |
| `f_manual_x_weekend` | 수기 입력 × 주말 | 동일 |

원칙:
- 단독 shortcut feature (`f_manual`, deterministic rule flag) 는 interaction 으로만 진입.
- groupby z-score 등 통계 feature 는 fit 시점에 통계 저장 → transform 시 재계산 금지 (CV 누수 방지, `feedback_imbalanced_data` 정합).

#### (c) PHASE1 rule hit (row 단위) — standalone contract 하에서 전면 EXCLUDE

> **변경 (2026-05-24, standalone contract lock 반영)**: 본 표의 이전 정책은 `flagged_rule_count`, `review_rule_count`, `flagged_rule_severity_max` 를 화이트리스트로 include 하고 multi-hot 만 deny 하던 안이었다. Phase 2 Standalone Contract lock (본 문서 상단 §"Phase 2 Standalone Contract (선결 lock)" 및 [phase2_reorgani.md §Phase 2 Standalone Contract](phase2_reorgani.md#phase-2-standalone-contract)) 아래에서는 PHASE1 rule hit 의 **모든 row-level 파생 컬럼** 을 ML 입력으로 받지 않는다. PHASE1 rule hit 정보는 PHASE3 narrator citation 과 dashboard overlay 에서만 사용한다.

| 컬럼 | 정의 | ML 입력 정책 |
|------|------|------|
| `flagged_rule_count` | row 가 트리거한 PHASE1 rule 개수 | ❌ exclude (standalone contract) |
| `review_rule_count` | review-only rule 개수 | ❌ exclude (standalone contract) |
| `flagged_rule_severity_max` | max(severity) | ❌ exclude (standalone contract) |
| `flagged_rule_ids` / `flagged_rules` | rule_id list (raw) | ❌ exclude — PHASE3 citation source 전용 |
| `review_rule_ids` / `review_rules` | review-only rule_id list | ❌ exclude — overlay 전용 |
| `flagged_rules__rule_{rule_id}` (multi-hot) | 각 rule_id 발화 여부 | ❌ exclude (전체) |

차단 메커니즘: `src/preprocessing/phase2_plan.py::_LEAKAGE_PATTERNS` 의 `rule` 토큰 (단복수 매칭) + `LEAKAGE_DENY_RULES` (`rule_L3-02`, `rule_L3-09`, `rule_L1-03`, `rule_L2-03`, `rule_L1-05`). standalone contract 회귀 가드는 `tests/modules/test_preprocessing/test_phase2_plan.py::test_phase2_standalone_contract_excludes_phase1_output_columns`.

historical 근거 (이전 화이트리스트 안의 출발점): Top-5 deterministic rule 이 manipulated 신호의 99.7% 를 차지하므로 (S5 §5), 화이트리스트 안에서도 `LEAKAGE_DENY_RULES` 5건은 multi-hot 에서 제외해야 했다. standalone contract 아래에서는 5건 외 나머지 rule 도 한꺼번에 exclude 한다.

#### (d) PHASE1 case 메타 prior

별도 결정 2 에서 다룸. 결론은 **옵션 A (배제)** 권장이므로 row matrix 에 포함하지 않는다. 옵션 B 채택 시 (case_id join 후) `_prior_*` prefix 로만 진입.

### 2.3 라벨 컬럼 (학습 전용, feature 미포함)

학습 시점에만 사용. inference / transform 시 feature 로 흘러서는 안 된다.

| 컬럼 | 비고 |
|------|------|
| `is_fraud` | 1차 ground truth (DataSynth) |
| `is_anomaly` | 1차 ground truth (DataSynth) |
| `fraud_type` | multi-class supervised 용 |
| `anomaly_type` | multi-class supervised 용 |

원칙: `LABEL_COLUMNS` frozenset (`constants.py`) 으로 deny. `Phase2PreprocessingPlan` 의 `action="exclude"`, `reason_code="leakage_label"` 로 기록.

### 2.4 deny-list (절대 입력 금지, 학습/inference 공통)

#### (1) 라벨/시나리오/생성 provenance

| 컬럼 | 분류 | 사유 |
|------|------|------|
| `is_fraud`, `is_anomaly` | label | direct truth |
| `fraud_type`, `anomaly_type` | label | direct truth |
| `sod_violation`, `sod_conflict_type` | label | direct truth |
| `label`, `target` | label | generic |
| `manipulation_scenario`, `scenario` | provenance | DataSynth shortcut |
| `semantic_scenario_id` | provenance | `LEAKAGE_DENY_COLUMNS` |
| `mutation_type`, `mutation_base_event_type`, `mutation_mutated_field`, `mutation_mutated_value`, `mutation_original_value`, `mutation_reason` | provenance | `LEAKAGE_DENY_COLUMNS` |
| `manipulated_entry_truth` | provenance | DataSynth sidecar |
| `detection_surface_hints` | provenance | DataSynth sidecar |

#### (2) 식별자 / shortcut

| 컬럼 | 사유 |
|------|------|
| `document_id`, `doc_id`, `journal_id`, `row_id`, `id`, `transaction_id`, `record_id`, `anomaly_id` | ID shortcut |
| `*_id` (suffix) | ID shortcut |
| `document_number`, `header_text`, `ip_address`, `reference` | `LEAKAGE_DENY_COLUMNS` (텍스트/주소 leakage 위험) |

#### (2-a) DataSynth manipulation V6/V7 synthetic shortcut deny

V6/V7 감사에서 생성기 fitting 으로 더 밀어붙이면 회계 substance가 손상되는 영역은 PHASE2 feature policy 로 차단한다. 아래 컬럼은 DataSynth truth 식별에 과도하게 직접적이므로, real-data 재검증으로 해제되기 전까지 `LEAKAGE_DENY_COLUMNS` 로 고정한다.

| 컬럼군 | 컬럼 |
|------|------|
| 금액 shortcut | `amount_magnitude`, `amount_zscore`, `local_amount`, `debit_amount`, `credit_amount`, `document_approval_amount`, `near_threshold_amount`, `supply_amount`, `invoice_amount`, `tax_amount` |
| 승인/시간 shortcut | `approval_lag_abs`, `approval_before_posting`, `approval_after_30d`, `approval_lag_days`, `approval_level`, `approval_excess_amount`, `approval_limit_exceeded_independent`, `approval_date_null`, `exceeds_threshold` |
| 시나리오 표면 | `days_backdated`, `is_suspense_account`, `is_round_number`, `has_revenue_line`, `self_approval`, `approval_contract_gap`, `approval_matrix_gap`, `near_threshold_ratio_to_limit`, `is_intercompany`, `master_counterparty_intercompany`, `first_digit` |
| V7 파생 shortcut | `near_threshold_gap_amount`, `near_threshold_gap_ratio`, `near_threshold_limit_amount`, `approver_limit_amount`, `approver_can_approve_je`, `line_number` |

근거: `artifacts/datasynth_v6_phase2_cheat_route_audit.md`, `artifacts/datasynth_v7_phase2_cheat_route_audit.md`, `artifacts/datasynth_v7_candidate_fixed3_phase2_cheat_route_audit.md`. V7 fixed3 승격 기준 cheat-route hard shortcut은 0건이며, active manipulation 기준은 `datasynth_manipulation_v7_candidate_fixed3`이다.
| `f_manual` (단독) | `_SINGLE_USE_DENY` — interaction 형태로만 허용 |

#### (3) 패턴 기반 토큰 deny (`_LEAKAGE_PATTERNS`)

normalized name 토큰에 다음이 포함되면 자동 exclude (`reason_code` 부여):

| token | reason_code | 비고 |
|-------|-------------|------|
| `label`, `target`, `fraud`, `anomaly` | leakage_label | 직접 truth |
| `risk` | leakage_risk | risk_level 등 PHASE1 산출물 |
| `rule` | leakage_rule | rule hit / rule_count / flagged_rules 등 단복수 매칭 (standalone contract 하에서 화이트리스트 없음) |
| `score` | leakage_score | composite_sort_score / topic_score_* / priority_score 등 |
| `model`, `prediction`, `probability` | leakage_model | PHASE2 자체 출력 |
| `export`, `dashboard` | leakage_export/dashboard | 후공정 컬럼 |

추가 명시 exact-name deny (`_PHASE_OUTPUT_DENY_EXACT`, 본 문서 §2.4 (4) 와 정합):
- `priority_band` — token deny 매칭 없음, exact deny 로 차단.
- `review_narrative_text` — token deny 매칭 없음, exact deny 로 차단.
- `phase1_*`, `phase2_*`, `phase3_*` prefix — phase 출력 재투입 방지.

> standalone contract lock (2026-05-24) 반영: PHASE1 rule hit 파생 컬럼에 대한 화이트리스트 예외는 제거되었다. `flagged_rule_count`/`review_rule_count`/`flagged_rule_severity_max` 도 `rule` 토큰 deny 로 일괄 exclude. 회귀 가드: `tests/modules/test_preprocessing/test_phase2_plan.py::test_phase2_standalone_contract_excludes_phase1_output_columns`.

#### (4) PHASE2/3 출력 컬럼 (전 단계 출력 재투입 금지)

| 컬럼 | 사유 |
|------|------|
| `anomaly_score`, `risk_level`, `phase2_*`, `ml_*` | PHASE2 자체 출력 |
| `phase1_case_id`, `composite_sort_score`, `triage_rank_score`, `topic_score_*`, `priority_score`, `priority_band` | PHASE1 case-level 출력 (결정 2 옵션 A) |
| `review_narrative_*`, `priority_rank` | PHASE3 출력 |

### 2.5 feature_id 명명 규칙 (PHASE3 citation 호환)

`Phase2AutoencoderMatrixBuilder` 의 `feature_names_` 는 변환기별로 자동 생성된다. PHASE3 Narrator 의 `ml_scores.top_features[].feature_id` 와 호환되도록 다음 규칙 lock:

| 변환기 | feature_id 형식 |
|--------|----------------|
| `SignedLogTransformer` | `{column}__signed_log` |
| `NumericPolicyTransformer` | `{column}__{policy}` (예: `amount_zscore__zscore`) |
| `RareCategoryOneHotEncoder` | `{column}__{category}` |
| `FrequencyCountEncoder` | `{column}__freq`, `{column}__count` |
| boolean passthrough | `{column}` |
| sparse_dropped indicator | `has_{column}` |

PHASE3 citation validator 는 `ml_scores.top_features[].feature_id` 가 PHASE2 `feature_names_` (또는 `output_feature_groups_` 키) 에 존재함을 검증한다. 명명 규칙 변경은 PHASE3 spec 과 함께 lock 해야 한다.

### 2.6 Pandera schema 계층 관계

현 L1/L2/L3 Pandera 계층 (`src/validation/schema_validator.py`) 은 ingest/feature 단계용이며 PHASE2 matrix 계약과 직접 연결되지 않는다. 본 결정은 **별도 L4 schema 도입하지 않고** `Phase2PreprocessingPlan` 의 `decisions[].action`/`reason_code` 메타가 contract 역할을 한다.

후속 구현 (별도 컨텍스트):
- `Phase2PreprocessingPlan` 의 deny coverage 단위 테스트 보강 — 위 2.4 (1)~(4) 컬럼 전체가 `action="exclude"` 인지 회귀 가드 (현재 standalone 회귀 가드 1건은 추가됨).
- ~~`flagged_rule_count` 등 화이트리스트 컬럼 진입 로직~~ — standalone contract lock 으로 폐기 (2026-05-24).

---

## 3. 결정 2 — composite_sort_score / topic_score 활용 정책

### 3.1 P-7 §3 결론 재확인

`composite_sort_score`, `topic_score_breakdown`, `composite_sort_score_components` 는 **rule-derived prior**다. PHASE2 가 "독립 ML feature" 로 입력하면 PHASE1 rule이 이미 잡은 정보를 ML이 재학습하는 순환 학습이 발생한다.

`composite_sort_score_components`:
- `topic_score`
- `max_primary_rule_score`
- `audit_evidence_score`
- `corroboration_score`
- `independent_evidence_count`, `independent_evidence_norm`

이들은 모두 rule hit 집계의 함수이므로 PHASE1 rule 자체와 강한 종속 관계.

### 3.2 옵션 비교

#### 옵션 A — PHASE2 입력에서 완전 배제 ✅ **권장 / 현 코드 정합**

- PHASE2 row matrix: PHASE1 rule hit 파생 컬럼 전면 제외 (standalone contract). composite_sort_score / topic_score / priority_score / priority_band / flagged_rule_* / review_rule_* 모두 미포함.
- PHASE2 case feature (`PHASE2_CASE_FEATURE_COLUMNS`): rule_diversity_count, evidence_type_count, theme_entropy 등 **rule-id-agnostic** signal 만 사용. composite_sort_score 자체는 `PROVENANCE_ONLY_FIELDS` 에 들어가 firewall 차단.

| 평가 항목 | 결과 |
|---------|------|
| fitting 위험 | 낮음 — rule prior 가 ML 에 흐르지 않음 |
| 새 신호 발견 가능성 | 높음 — ML 이 rule 이 못 잡은 잔여 신호에 집중 |
| 학습 효율 | 중간 — rule 이 잡은 정보는 PHASE2 가 별도 학습 필요 |
| 설명 가능성 | 높음 — ML 출력이 rule 과 독립적이므로 PHASE3 citation 시 충돌 없음 |
| 회귀 위험 | 낮음 — 현 코드 정책 유지 |

#### 옵션 B — meta-feature 로 분리 입력

- `_prior_composite_sort_score`, `_prior_topic_{topic}` 등 prefix 로 row matrix 진입.
- with/without prior ablation 학습 필수 (PR-AUC 차이가 정상 모집단에서 의미 있는지 검증).

| 평가 항목 | 결과 |
|---------|------|
| fitting 위험 | **높음** — ML 이 rule prior 에 의존, prior 가 100% positive 인 row 가 학습 데이터에서 truth 와 직접 결합 |
| 새 신호 발견 가능성 | 낮음 — ML 이 rule 점수와 truth 의 거의 결정적 매핑을 학습 |
| 학습 효율 | 높음 — rule 정보를 prior 로 흡수 |
| 설명 가능성 | 중간 — ml_score top_features 가 prior 컬럼에 집중되면 PHASE3 가 "ML이 rule 점수를 재진술" 형태로 환원 |
| 회귀 위험 | 높음 — truth recall 향상 압력이 ML prior 가중치 튜닝으로 옮겨가서 PHASE2 자체가 PHASE1 rule 의 가중 합성으로 수렴 |

#### 옵션 C — PHASE2 학습 prior 없이, inference 시점에 외부 결합

- PHASE2 row matrix 와 case feature 는 옵션 A 와 동일.
- inference 후 PHASE1 prior 와 PHASE2 ml_score 를 별도 score 로 dashboard / Narrator 에서 결합.

| 평가 항목 | 결과 |
|---------|------|
| fitting 위험 | 낮음 — 학습 단계 분리 |
| 새 신호 발견 가능성 | 높음 — 옵션 A 와 동일 |
| 운영 복잡도 | 높음 — dashboard 결합 가중치, Narrator 가 두 score 를 동시 인용 |
| 설명 가능성 | 중간 — 두 score 의 결합식이 별도 lock 필요 |

### 3.3 권장 결정

**옵션 A (배제) 유지 + lock**.

근거:
1. CLAUDE.md PHASE1 역할 원칙: PHASE1 출력은 review queue 후보 우선순위지 truth label 이 아니다. PHASE2 가 rule prior 를 학습 입력으로 받으면 "PHASE1 priority 와 truth 의 일치도" 가 PHASE2 학습 목표로 흘러 들어가서 PHASE1 의 review queue 정합성이 ML 학습 보조 지표로 환원된다.
2. P-7 §3.4 권고: "rule-derived prior 또는 meta-feature 로 분리".
3. 현 코드 (`PHASE2_CASE_FEATURE_COLUMNS`, `PROVENANCE_ONLY_FIELDS` firewall) 이미 옵션 A 적용.
4. DataSynth fitting 가드 (D044): label/scenario/document id/특정 생성 패턴에 맞춘 score 조정 차단. composite_sort_score 가 ML 입력으로 흐르면 D044 가드와 충돌.

### 3.4 옵션 B 시험 protocol (옵션 A 유지 하에 실험만 허용)

옵션 B 를 향후 재검토할 경우의 ablation protocol:

- Phase 2 training service 에 `--include-phase1-prior` 플래그 추가 (default off).
- 동일 split / 동일 평가 셋에서 with/without prior 2종 학습.
- 평가:
  - macro PR-AUC: prior 포함 시 정상 모집단 false positive 영향 확인.
  - **scenario_delta_recall** (`phase2_evaluation.evaluate_s4_p4_delta_recall_gate`): prior 포함이 scenario별 +0.05 이상 delta recall 을 만들어야 의미 있음.
  - **anti_shortcut_cap** (`evaluate_anti_shortcut_cap`): prior 포함 시 ensemble_macro_auprc / trivial_macro_auprc 비율 4.0 이하 유지 필수.
- 통과해도 옵션 B 채택은 별도 결정. 본 문서 lock 변경 없이 실험 자체는 금지하지 않음.

### 3.5 `composite_sort_score_components` 내부 분리 가능성

`max_primary_rule_score` / `audit_evidence_score` / `corroboration_score` / `independent_evidence_count` 각각도 rule hit 의 함수다. 별도 분리 처리는 불가능 (= 셋 다 옵션 A 적용). 단, 본 문서는 다음을 허용한다:

- `evidence_type_count`, `rule_diversity_count` (이미 `PHASE2_CASE_FEATURE_COLUMNS` 에 있음) 는 rule_id 자체가 아닌 **다양성 메트릭** 이므로 옵션 A 와 충돌하지 않는다.
- `theme_entropy` 도 동일 (정보 이론 변환으로 특정 rule_id 와의 직접 매핑 차단).

---

## 4. 결정 3 — PHASE2 ml_score 의 PHASE1 ranking 관계

### 4.1 옵션 비교

#### 옵션 X — override

- PHASE1 case ranking 을 PHASE2 ml_score 가 덮어쓴다.
- dashboard 와 PHASE3 Narrator 는 단일 final_score 만 본다.

| 평가 항목 | 결과 |
|---------|------|
| 운영 단순성 | 높음 — 단일 큐 |
| fitting 위험 | **매우 높음** — PHASE2 가 fitting 된 순간 PHASE1 의 rule-based detection 보호망 무력화 |
| 설명 가능성 | 낮음 — rule hit 가 명백한 case 가 ml_score 낮다는 이유로 후순위 밀리면 감사인 신뢰 손상 |
| CLAUDE.md 역할 원칙 정합 | 위배 — PHASE1 의 review queue 책임을 ML 출력이 침범 |

#### 옵션 Y — 보강 (combined score)

- `final_score = f(composite_sort_score, ml_score)`. 결합식 예: weighted sum (w1·phase1 + w2·phase2), rank fusion (RRF), multiplication.

| 평가 항목 | 결과 |
|---------|------|
| 운영 단순성 | 중간 — 단일 final ranking |
| fitting 위험 | **높음** — 결합 가중치 자체가 fitting 대상. truth recall 을 직접 목표로 가중치 튜닝하면 PHASE1 + PHASE2 합쳐서 truth 에 맞추는 과적합 발생 (`feedback_phase1_truth_recall_guard` 위배) |
| 설명 가능성 | 중간 — Narrator 가 "rule 점수 + ml 점수 = final" 형태로 단순 인용 가능하지만 가중치 변경 시 ranking 흔들림 |
| 회귀 위험 | 높음 — 결합 가중치 변경이 전수 case ranking 을 흔든다 |

#### 옵션 Z — 독립 (parallel queue) ✅ **권장 / 현 코드 정합**

- PHASE1 ranking 과 PHASE2 ranking 을 별도 큐로 유지.
- case-level: `Phase2CaseOverlay.phase2_adjusted_priority` 는 **참고 overlay**, PHASE1 `priority_score` 는 보존.
- row-level: PHASE2 가 row 단위 `anomaly_score` 와 `risk_level` 을 생성, PHASE1 rule hit 와 별도로 노출.
- dashboard: tab_phase1 (rule-based) + tab_phase2 (ml-based) 분리, 동일 case 의 두 view 를 사용자가 동시 확인.
- PHASE3 Narrator: PHASE1 `case_id` / `composite_sort_score` 인용을 1차 source 로, PHASE2 `model_id` / `feature_id` / `score` 를 보조 인용.

| 평가 항목 | 결과 |
|---------|------|
| 운영 단순성 | 낮음 — 두 큐 |
| fitting 위험 | 낮음 — PHASE1 ↔ PHASE2 학습 압력이 서로 침투하지 않음 |
| 설명 가능성 | 높음 — 각 score 가 독립적으로 인용됨 |
| CLAUDE.md 역할 원칙 정합 | 정합 — PHASE1 은 review queue, PHASE2 는 row anomaly 보강. 책임 분리 |
| 현 코드 정합 | 정합 — `Phase2CaseOverlay`, `_adjusted_priority` overlay 비파괴 |

### 4.2 권장 결정

**옵션 Z (independent) 유지 + lock**.

근거:
1. `feedback_phase1_truth_recall_guard`: PHASE1 변경은 도메인 정합성으로만 정당화. truth recall 직접 추구 금지 (PHASE2 이관). 본 가드는 옵션 X/Y 에서 무력화된다.
2. CLAUDE.md PHASE1 역할 원칙: PHASE1 은 감사인이 봐야 할 항목과 우선순위 생성. ML override 는 이 책임을 침범.
3. 현 코드 `Phase2CaseOverlay` 가 이미 옵션 Z 형태.
4. PHASE3 Narrator citation 계약 (`reasoning[].evidence`) 은 rule_id / feature_id / journal_id 를 **서로 다른 type 으로 인용**하도록 설계됨. 두 score 가 독립이어야 citation 다양성이 보장된다.

### 4.3 dashboard 노출 정책 (초안)

옵션 Z 채택 하에서 dashboard tab 구조:

- `tab_phase1`: rule-based ranking, `composite_sort_score` 정렬. PHASE2 overlay 는 **참고 컬럼 1개** (`phase2_adjusted_priority`) 로만 표시.
- `tab_phase2`: ml-based ranking, row-level `anomaly_score` percentile 정렬. case 단위 grouping 시 case 내 max(anomaly_score) 노출.
- `tab_review_queue` (PHASE3): Candidate Builder 가 (a) PHASE1 case priority 상위 N + (b) PHASE2 percentile ≥ 0.99 단독 보충 (`candidate_builder.py` Sprint B 정책) 으로 후보 구성. 이 정책은 본 결정과 정합.
- band 축 표기: PHASE1 `priority_band` 는 그대로 유지. PHASE2 band 는 별도 컬럼 `ml_band` 로 추가, **PHASE1 band 와 결합하지 않는다**.

#### 4.3.1 family lane 보조 view (PHASE2 GOVERNANCE 결정 8 정합, 2026-05-19)

PHASE2 family 별 보조 큐를 tab_phase2 내에 lane selector + lane content 로 노출한다. lane 은 primary queue 의 순위를 변경하지 않으며 family signal attribution 용도다.

| Lane | 정렬 기준 | 노출 조건 |
|---|---|---|
| Duplicate | evidence_tier desc → pair_evidence_tier desc → family ECDF desc → score desc | duplicate family active |
| Relational | evidence_tier desc → family ECDF desc → score desc | relational family active |
| Timing | 동일 (Relational 과 동일 sort key) | timeseries family active (coarse-booster 도 lane 으로는 노출) |
| Intercompany | evidence_tier desc → **ic_role_priority** desc → family ECDF desc → score desc | active 또는 near-dormant (배지 노출) |

near-dormant family lane 은 "데이터 미보유" 배지로 표시하고 case 목록은 비운다. 구현은 `dashboard/components/phase2_family_lanes.py::render_lane_view`.

#### 4.3.2 Intercompany lane evidence_role priority (2026-05-25, 옵션 2)

IC family 점수는 `IntercompanyMatcher._build_result` 의 `details.max(axis=1)` 으로 IC01~03 + 4개 internal probability column (`ic_reciprocal_flow_prob` / `ic_amount_prob` / `ic_unmatched_prob` / `ic_timing_prob`) 의 row-wise max 다. 1.0 bucket 안에 reciprocal_flow / amount mismatch / timing-only / no_candidate 가 같이 들어가며, 기존 lane sort key (`evidence_tier_weight, ecdf, score`) 만으로는 1.0 동률 case 들이 audit evidence 강도와 무관하게 갈렸다.

옵션 2 (score 합성 변경 없음, lane visibility + ordering 만 보정) 적용:

**(1) sub-detector tier 등록** — `config/phase2_subdetector_tiers.yaml` 에 4개 internal column 을 추가 등록 (총 17 → 21).

| code | tier | evidence_role | 인용 |
|---|---|---|---|
| `ic_reciprocal_flow_prob` | strong | reciprocal_flow | ISA 550 ¶A20 + PCAOB AS 2401 §B7 (양방향 reconciliation) |
| `ic_amount_prob` | moderate | amount_mismatch | ISA 550 ¶A20 보조 + AS 2401 .A6 (3) |
| `ic_unmatched_prob` | weak | no_candidate | ISA 550 ¶A20 보조 + AS 2401 §B7 |
| `ic_timing_prob` | weak | timing_gap | ISA 550 ¶A20 보조 (cut-off normal 차이) |

각 entry 는 `POST-MIGRATION REMEASUREMENT PENDING` 표기 (TS01/TS02 선례와 동일). truth recall 튜닝 금지.

**(2) lane sort secondary dim — `ic_role_priority`** (intercompany 한정).

`sub_detectors[].code` 중 `_IC_ROLE_PRIORITY` 매핑 최대값. 매칭 없으면 0 (weak_contract fallback).

| evidence_role | priority | 대응 sub-detector code |
|---|---|---|
| reciprocal_flow | 5 | `ic_reciprocal_flow_prob` |
| amount_mismatch | 4 | `IC02`, `ic_amount_prob` |
| no_candidate | 3 | `IC01`, `ic_unmatched_prob` |
| timing_gap | 2 | `IC03`, `ic_timing_prob` |
| weak_contract | 0 (fallback) | sub-detector 코드 없음 — `prob_summary.contract_tier` (L2_aggregate/L3_insufficient) metadata 에서만 노출 |

sort key 전체: `(evidence_tier_weight, secondary_dim, ecdf, score, review_only_count)`. secondary_dim 은 family 별 단일 슬롯 (duplicate=`pair_evidence_tier_weight`, intercompany=`ic_role_priority`, 그 외=0).

**(3) 비변경 범위** — IC row score, family score 분포, IntercompanyMatcher 내부 합성 로직, KPI 가드, PHASE1 priority_score 모두 변경 없음. lane 내부 ordering 만 evidence_role 강도 순으로 재배치.

**(4) 부수효과 — `phase2_review_band` 영향 허용 (의도)**

`_build_family_contributions` 가 sub_detectors 의 max tier 를 family entry 의 `evidence_tier` 로 set 하고, 그 값이 overlay `max_evidence_tier` → `classify_phase2_review_band` 분류 input 으로 흐른다. IC internal prob column 4개를 tier registry 에 등록한 결과, IC family entry 의 `evidence_tier` 가 sub_detector hit 에 따라 strong/moderate/weak 로 결정되며 다음 chain 이 활성화된다:

| IC sub_detector hit | family `evidence_tier` | 동시 active family breadth | `phase2_review_band` |
|---|---|---|---|
| `ic_reciprocal_flow_prob` 단독 | strong | 1 | review |
| `ic_reciprocal_flow_prob` + 다른 family active | strong | ≥2 | immediate |
| `ic_amount_prob` 단독 | moderate | 1 | candidate (D060 4번 — moderate 단독 review 금지) |
| `ic_amount_prob` + 다른 family active | moderate | ≥2 | review |
| `ic_unmatched_prob` 단독 (no_candidate) | weak | 임의 | candidate (weak 단독 review 진입 금지) |
| `ic_timing_prob` 단독 | weak | 임의 | candidate (weak 단독 review 진입 금지) |

audit semantic 정당화: ISA 550 ¶A20 (양방향 reconciliation) + PCAOB AS 2401 §B7 (intercompany unusual journal entries) 직접 인용. `ic_reciprocal_flow_prob` hit (단일 document 안에 receivable + payable 동시 + amount symmetry ≥ 0.95) 은 reconciliation 구조 자체를 보여주는 strong evidence 이므로 review/immediate 승격이 도메인 정합. moderate (amount mismatch) 는 보강증거 (breadth≥2) 함께일 때만 review. weak (no_candidate / timing) 단독은 review band 진입 금지 — 정상 단방향 거래·cut-off normal 차이와 구분 어려움.

회귀 가드: `tests/modules/test_services/test_phase2_case_contract.py::TestIntercompanyInternalProbReviewBandImpact` (6 케이스).

**(5) fitting 가드** — tier 값과 priority 값은 ISA 550 / PCAOB AS 2401 인용으로만 정당화. truth_recall / IC TOP100 수치로 priority 또는 tier 재조정 금지 (D044 PR 템플릿 강제).

### 4.4 PHASE3 Narrator 의 ranking 인용 정책

- `priority_rank` (output): PHASE3 LLM 이 candidate 내에서 재정렬한 결과. 입력으로 들어간 PHASE1 / PHASE2 score 와 직접 매핑 강제되지 않음 (LLM 추론 결과). citation_validator 는 ranking 값의 정합이 아닌 **evidence id 존재** 만 검증.
- 후보 집합 구성은 옵션 Z 의 두 score 를 union 으로 (Sprint B 정책) 사용. PHASE3 가 자체적으로 ranking 을 만든다.

#### 4.4.1 family signal citation 보강 (PHASE2 GOVERNANCE 결정 8 정합, 2026-05-19)

`build_phase3_selected_case_inputs` 가 case overlay 의 다음 필드를 prompt payload 에 노출한다. narrator 는 이를 evidence attribution 으로 인용한다.

| Prompt field | 출처 overlay 필드 | 역할 |
|---|---|---|
| `phase2_family_scores` | `phase2_family_scores` (기존) | 기존 호환 — family raw score dict |
| `phase2_family_contributions` | `family_contributions` | 각 family 의 score / ecdf / role / evidence_tier / sub_detectors |
| `phase2_top_family` | `top_family` | 가장 강한 evidence tier 의 family 이름 |
| `phase2_coverage_breadth_q95` | `coverage_breadth_q95` | family q95 진입 개수 |
| `phase2_max_family_ecdf` | `max_family_ecdf` | 최대 ECDF |
| `phase2_max_evidence_tier` | `max_evidence_tier` | strong/moderate/weak/ml_quantile |
| `phase2_lane_membership` | `lane_membership` | case 가 노출되는 lane 목록 |
| `phase2_coverage_gap_families` | `coverage_gap_families` | near-dormant family 목록 (감사인 enrichment 신호) |

---

## 5. fitting / 회귀 / 설명 가능성 요약

| 결정 | 권장 옵션 | fitting 위험 | 회귀 위험 | 설명 가능성 | 현 코드 정합 |
|------|----------|------------|----------|------------|----------|
| 결정 1 (row contract) | 명세 보강 (식별자 분리) + standalone contract 하 PHASE1 rule hit 파생 컬럼 전면 exclude | 낮음 (standalone 회귀 가드 + deny coverage 테스트) | 낮음 | 높음 (feature_id 명명 lock) | 정합 — standalone contract lock (2026-05-24) 으로 화이트리스트 폐기, `rule` 토큰 단복수 매칭 + exact deny 적용 |
| 결정 2 (prior 활용) | A (배제) | 낮음 | 낮음 | 높음 | 정합 |
| 결정 3 (ml_score 결합) | Z (독립) | 낮음 | 낮음 | 높음 | 정합 |

---

## 6. 후속 작업 (별도 컨텍스트)

본 문서는 설계 lock 만 다룬다. 실제 구현 prompt 후보:

1. **결정 1 구현 보강** (`src/preprocessing/phase2_plan.py`, `phase2_matrix.py`)
   - ~~`flagged_rule_count`, `review_rule_count`, `flagged_rule_severity_max` 화이트리스트 진입 로직~~ — standalone contract lock (2026-05-24) 으로 폐기. 전면 exclude.
   - `LEAKAGE_DENY_RULES` 기반 multi-hot rule feature 차단 (현재 `rule` 토큰 단복수 deny 로 차단됨; 명시 multi-hot 진입 자체가 없음).
   - row-level 식별자 (`record_id`) 보존을 위한 `_row_key` 별도 컬럼 도입.
   - feature_id 명명 규칙 단위 테스트 (`tests/modules/test_preprocessing/test_phase2_matrix_feature_names.py`).
2. **결정 2 lock 테스트** (`tests/modules/test_services/test_phase2_case_contract.py`)
   - `PROVENANCE_ONLY_FIELDS` 가 firewall 에 의해 차단되는 회귀 테스트.
   - `composite_sort_score`, `topic_score_*`, `composite_sort_score_components` 가 PHASE2 입력에 흐르지 않음 확인.
3. **결정 3 lock 테스트** (`tests/modules/test_services/test_phase2_inference_service.py`)
   - `phase2_inference_service.run_phase2_inference` 후 `phase1_case_result.priority_score` 가 보존되는지 회귀 테스트.
   - `phase2_adjusted_priority` 가 overlay 로만 존재함 검증.
4. **dashboard 정책 반영** (`dashboard/tab_phase2.py`, `dashboard/components/`)
   - band 축 분리 (PHASE1 `priority_band` / PHASE2 `ml_band`) UI 구현.
5. **PHASE3 citation 호환** (`src/llm/review_narrator/candidate_builder.py`)
   - PHASE2 `ml_scores.top_features[].feature_id` 가 본 §2.5 명명 규칙과 일치함을 입력 단계에서 검증.
6. **D044 PR 템플릿 확장** (`docs/DECISION.md`)
   - PHASE2/3 handoff checklist: feature deny-list 적용 여부, train/test split, OOF leakage 점검, citation enum 검증.

## 7. 변경 이력

- 2026-05-15: 초안 작성. 결정 1 명세 보강 (row contract), 결정 2 옵션 A 권장, 결정 3 옵션 Z 권장. 사용자 확정 후 lock 예정.
- 2026-05-25: §4.3.2 추가 — IC family lane evidence_role priority (옵션 2). 4개 IC internal probability column 을 `phase2_subdetector_tiers.yaml` 에 등록(17→21) + `phase2_lane_sort.py` 에 `ic_role_priority` secondary dim 도입. score 합성 / KPI 가드 / family score 분포 모두 비변경. §4.3.2 (4) 부수효과 — `phase2_review_band` 영향은 의도된 변화로 계약 고정 (ISA 550 ¶A20 + PCAOB AS 2401 §B7 인용, `TestIntercompanyInternalProbReviewBandImpact` 6 회귀).
