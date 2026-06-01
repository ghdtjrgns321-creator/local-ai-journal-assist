# PHASE2 거버넌스 / KPI 가드 설계

> **상태**: 설계안 (학습 baseline 측정 전). 본 문서는 가드 항목·정책·구조 정의이며, 임계값 baseline은 PHASE2 첫 학습 후 별도 PR에서 채운다.
>
> **단일 출처 예정**:
> - `tests/phase2_rulebase/kpi_baseline.json` — Layer A/B/C 기준값 (구조만 선반영)
> - `tests/phase2_rulebase/nightly_kpi_guard.py` — 가드 실행 (후속 구현)
> - `.github/workflows/phase2-kpi-guard.yml` — CI 트리거 (초안)
>
> **PHASE1 거버넌스 정합**: [docs/CONSTRAINTS.md §"PHASE1 CI KPI 가드 정책 (3-Layer 구조)"](CONSTRAINTS.md) · [tests/phase1_rulebase/kpi_baseline.json](../tests/phase1_rulebase/kpi_baseline.json) · [tests/phase1_rulebase/nightly_kpi_guard.py](../tests/phase1_rulebase/nightly_kpi_guard.py)


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

---

## 0. 배경 및 원칙

### 0.1 PHASE2 MVP 정의 재확인

[CONSTRAINTS.md §Phase2 기본 모델 제약](CONSTRAINTS.md) 및 [dev/active/phase2-unsupervised-autoencoder/phase2-unsupervised-autoencoder-plan.md](../dev/active/phase2-unsupervised-autoencoder/phase2-unsupervised-autoencoder-plan.md) 기준 PHASE2 MVP는 다음과 같다.

| 항목 | 값 |
|------|---|
| Trainable family | `unsupervised` only |
| Promoted model | VAE 기반 비지도 오토인코더 1개 |
| 점수 의미 | anomaly evidence / ranking score (fraud probability 아님) |
| 학습/평가 분리 | `document_id` group split, train split에서만 fit |
| no-label metric | `unsupervised_selection_score` (score_tail_gap / topk_stability / capacity_penalty / score_degeneracy_penalty) |
| ground truth | DataSynth `is_fraud` / `is_anomaly` (개발 검증 보조용) |

### 0.2 PHASE1 거버넌스에서 계승하는 원칙

1. **3-Layer 분리**: A 도메인 정합성 (HARD) / B 운영 부하 (HARD) / C 회귀 방지선 (SOFT WARN)
2. **truth recall 향상 강제 금지** — Layer C 는 baseline × 70% 하한만, 절대값 임계 금지
3. **메타 가드 자기검증** — 가드 정의 자체에 truth recall 직접 추구 가드가 못 끼게 차단
4. **baseline 갱신은 도메인 정당성 의무**, fitting-risk check + rollback 조건 명시 (D044 PR 템플릿)

### 0.3 PHASE2 고유 거버넌스 요구

PHASE1과 다른 점:

| 차이 | PHASE1 | PHASE2 |
|------|--------|--------|
| 출력 | rule hit + topic score (deterministic) | reconstruction score (stochastic) |
| 정답 라벨 사용 | rule 자체는 라벨 미사용 | 학습 시 미사용(비지도) + 평가 시 보조 사용 가능 |
| 학습 단계 | 없음 (rule 코드 자체가 산출물) | fit/calibration/inference 분리 필요 |
| 회사 격리 | 단일 모집단 운영 | engagement별 모델 격리 필수 (RC-3 ✅) |
| 가드 대상 산출물 | `phase1_case_artifact` + `topic_analysis` | `training_report` + `model_bundle` + `phase2_inference_report` |
| fitting 위험 | rule scoring 가중치 튜닝 | 학습 누설 (split before fit / 라벨 학습 / contract noise overfit) |

---

## 결정 4 — PHASE2 KPI Guard Layer 정의

### Layer A — 도메인 정합성 (HARD FAIL)

PHASE1 A1~A6 패턴을 PHASE2 학습 무결성 관점으로 확장.

| ID | 가드 | 임계값 후보 | baseline 측정 방식 | 사유 |
|----|------|------------|------------------|------|
| **A1** | leakage deny column 미사용 | 학습 입력 컬럼 ∩ `LEAKAGE_DENY_COLUMNS` = ∅ | `training_report.feature_metadata.input_columns` 와 `src/preprocessing/constants.LEAKAGE_DENY_COLUMNS` 비교 | DataSynth truth sidecar 누설 차단 (현재 12개 컬럼 — `mutation_*`, `semantic_scenario_id`, `document_id` 등). PHASE2 학습기가 truth 컬럼을 보면 무조건 AUROC ≥ 0.95 가 나옴. |
| **A2** | leakage deny rule 미사용 | 학습 입력 rule 컬럼 ∩ `LEAKAGE_DENY_RULES` = ∅ | `training_report.feature_metadata.excluded_rule_columns` ⊇ `LEAKAGE_DENY_RULES` | Top-5 deterministic rule 이 manipulated 신호 99.7% 점유 (S5 §5). 5개 룰 입력 시 PHASE1 단순 재현으로 ML 부가가치 0. |
| **A3** | normal_sample_300 false positive | ml_high_score 비율 ≤ 5% | `normal_sample_300.csv` 로 inference → `ml_score >= HIGH_threshold` 행 비율 | PHASE1 A4 와 동일 fixture 공유. 정상 모집단에서 ML 가 폭증하면 학습 분포가 contract noise 에 fitting. |
| **A4** | contract_v2 HIGH ml_score 비율 | ≤ 1% | `contract_v2` profile 에서 ml_score HIGH 행 / 전체 | PHASE1 A2 의 PHASE2 변형. semantic-clean contract noise 모집단에서 ML 가 HIGH 를 1% 초과 발생시키면 정상 분포 학습 실패. |
| **A5** | leakage-safe split 검증 | split 방식 ∈ {`group_by_document_id`, `temporal_holdout`} | `training_report.split_policy` 메타 | random row split 은 fallback only. `document_id` line leakage 위험 차단. |
| **A6** | preprocessing fit 누설 검증 | `preprocessing_fit_split` == `train` | `training_report.preprocessing_plan.fit_split` 메타 | scaler / imputer / frequency encoder / rare grouping 이 calibration·test 분포를 보면 누설. |
| **A7** | 비지도 모델의 y 사용 금지 | `training_report.training_mode` ∈ {`unsupervised_autoencoder_mvp`} AND `target_used` == false | training 메타 | feedback_unsupervised_no_y 메모리 정합. 비지도 학습에서 y 를 사용하면 supervised 변종이 됨. |
| **A8** | matrix schema hash 고정 | `model_bundle.schema_hash` == `training_report.schema_hash` | bundle vs report | inference 시 column order / encoding 불일치 차단. |

### Layer B — 운영 부하 (HARD FAIL)

PHASE1 B1~B4 패턴의 학습/추론 시간·자원 변형.

| ID | 가드 | 임계값 후보 | baseline 측정 방식 | 사유 |
|----|------|------------|------------------|------|
| **B1** | inference latency | 50k 행 ≤ 60s (CPU) / ≤ 30s (GPU) | `phase2_inference_report.elapsed_sec` | review queue 운영에서 inference 가 PHASE1 case builder 보다 느려지면 안 됨 (PHASE1 B2 600s 의 1/10). |
| **B2** | model bundle 크기 | ≤ 50 MB | `os.path.getsize(model_bundle.pt)` | engagement 디렉토리 누적 크기 제한. VAE 기본 hidden dim 에서 충분. 폭증 시 model architecture 변경 의심. |
| **B3** | 학습 시간 | 50k row ≤ 600s (RTX 3070 Ti) | `training_report.training_elapsed_sec` | PHASE1 B2 와 동일 quota. 실 운영은 CompanyContext 별 학습이므로 단일 학습이 600s 초과하면 운영 부담 폭증. |
| **B4** | 학습 메모리 | ≤ 6 GB (RTX 3070 Ti VRAM 8GB) | `training_report.peak_vram_mb` (PyTorch `torch.cuda.max_memory_allocated`) | C-Memory `user_dev_environment` 환경 제약. VAE + IF 동시 운영 여지. |
| **B5** | training_report 산출물 무결성 | required 키 ∈ {`training_mode`, `evaluation_policy`, `metric_name`, `metric_semantics`, `split_policy`, `preprocessing_plan`, `schema_hash`, `promoted_versions`} | report JSON validation | inference contract pin (Phase 1 §B4 baseline 미측정 패턴 = `null` 허용) |

### Layer C — 회귀 방지선 (SOFT WARN)

PHASE1 의 truth recall 회귀 방지를 PHASE2 의 anomaly ranking 안정성으로 치환. 절대값 임계 금지, baseline × 70% 비율 하한만.

| ID | 가드 | 임계값 후보 | baseline 측정 방식 | 사유 |
|----|------|------------|------------------|------|
| **C1** | unsupervised_selection_score 회귀 | ≥ baseline × 70% | `training_report.metrics.unsupervised_selection_score` | PHASE2 자체 ranking 안정성 회귀 방지. 향상 강제 아님. |
| **C2** | score_tail_gap 회귀 | ≥ baseline × 70% | `training_report.metrics.score_tail_gap` | calibration split 의 anomaly score tail 분리도. 0 이면 ranking 의미 없음. |
| **C3** | topk_stability 회귀 | ≥ baseline × 70% | bootstrap top-N 교집합 비율 (학습 시 측정) | top-N 재현성. 작은 입력 변동에 top-N 이 흔들리면 운영 ranking 신뢰 불가. |
| **C4** | DataSynth truth Top500 recall | ≥ baseline × 70% | manipulation_v2 truth ∈ ml_score Top500 | PHASE1 C3 의 PHASE2 보조 평가. truth recall 향상 강제 아님 — 회귀 감지선. |
| **C5** | cross-engagement 점수 분포 안정성 | 평균 score · std 변동 ≤ baseline × 1.5 | engagement A vs engagement B 동일 fixture inference | 학습-추론 환경 격리 회귀. 회사별 격리에서 동일 fixture 점수가 너무 다르면 학습 환경 차이. |

### Meta — 가드 자체 무결성 (HARD FAIL)

| ID | 메타 가드 | 검증 방식 | 사유 |
|----|----------|----------|------|
| **M1** | truth recall 향상 강제 가드 금지 | Layer C 모든 항목 `fail_mode == "SOFT_WARN"` | PHASE1 원칙 계승 ([nightly_kpi_guard.py::test_no_truth_recall_improvement_guard](../tests/phase1_rulebase/nightly_kpi_guard.py)) |
| **M2** | feature_id metadata 정합 | `training_report.feature_metadata.feature_ids` 가 bundle feature schema와 일치 | SHAP / feature_importance / Local Evidence Brief provenance 일관성. 외부 LLM narrator enum 계약은 D068로 폐기됨. |
| **M3** | 학습 메타데이터 의무 | required 키 ∈ {`seed`, `dataset_id`, `dataset_version`, `fold_count`, `hyperparams`, `git_sha`, `training_started_at`, `training_completed_at`} | report 갱신 시점에 변경 사유 추적 가능 |
| **M4** | artifact freshness | training_report mtime ≤ 30일 | PHASE1 7일 보다 길게 — PHASE2 학습은 분기 단위 |
| **M5** | principle 문구 보존 | `_meta.principle` 에 "도메인 정합성" + "부수효과" 포함 | PHASE1 원칙 lineage 유지 |

### PHASE1 ↔ PHASE2 가드 매핑 요약

| PHASE1 가드 | PHASE2 대응 | 변화 |
|------------|-----------|------|
| A1 light_seeder | (없음) | PHASE2 는 PHASE1 rule_detail 미사용 |
| A2 contract HIGH 비율 | A4 contract ml_score HIGH 비율 | rule → ml_score |
| A3 rule_truth 과탐/미탐 | (없음) | PHASE2 는 rule 계약 미보유 |
| A4 normal sample FP | A3 normal sample ml FP | fixture 공유 |
| A5 정책 floor 충돌 | (없음) | PHASE2 는 정책 floor 미사용 |
| A6 master/flow gap | (없음) | PHASE1 only |
| — | A1/A2 leakage deny column/rule | PHASE2 신규 |
| — | A5/A6/A7/A8 split / fit / target / schema | PHASE2 신규 |
| B1 case 수 | B5 training_report 무결성 | 산출물 구조로 치환 |
| B2 case builder runtime | B1/B3 inference/training time | 학습/추론 분리 |
| B3 priority band 분포 | (없음, C2/C3 점수 분포로 부분 대응) | PHASE2 는 band 미직접 산출 |
| B4 floor 적용 비율 | (없음) | PHASE1 only |
| — | B2/B4 model size / VRAM | PHASE2 신규 |
| C1 manipulation 포착률 | C4 DataSynth truth Top500 recall | proxy 만 회귀 감지 |
| C2 high truth | (없음, PHASE2 band 미산출) | |
| C3 Top500 truth | C4 | 동일 |
| C4 scenario full entry | (없음) | PHASE2 는 시나리오 미직접 측정 |
| C5 contract Medium+ recall | (없음) | |
| — | C1/C2/C3/C5 selection_score / tail_gap / topk / cross-engagement | PHASE2 신규 |

---

## 결정 5 — fitting 회피의 PHASE2 변형

### 모순 정리

PHASE1 원칙: *"truth recall 은 부수효과로만 측정, 향상 강제 금지"*

PHASE2 가 supervised 였다면 본질적으로 truth recall 최적화 학습 → 모순. 다만 **PHASE2 MVP 는 VAE 비지도** ([CONSTRAINTS.md §Phase2 기본 모델 제약](CONSTRAINTS.md)) 이므로 supervised target 자체가 없고, 학습 metric 은 `reconstruction_loss + KL_loss` 이다. truth 는 평가 시 보조 지표.

따라서 옵션 비교는 "supervised 가 활성화되었을 때" 거버넌스 형태가 핵심.

### 옵션 비교

#### 옵션 P — PHASE1 원칙 그대로 (보수)

- 학습 목표를 truth recall 이 아닌 도메인 metric (회계 anomaly 정의) 만 사용
- 장점: PHASE1 과 완전 일관
- 단점: supervised 학습 자체 불가. PHASE2 가 미래에 supervised 로 확장될 때 막힘

#### 옵션 Q — supervised 허용 + 학습/평가 분리 (중도)

- 학습: truth recall 최적화 허용 (XGBoost / FT-Transformer 가 활성화될 경우)
- 평가/거버넌스: fitting 검사는 회계 도메인 가드 (contract noise FP / normal_sample FP / cross-engagement AUC) 우선, truth recall 은 보조
- 장점: ML 본연 기능 + fitting 가드 분리
- 단점: 정책 복잡, "ML 학습이 truth 를 보는데 거버넌스는 truth 회귀를 SOFT WARN 으로만 본다" 논리 충돌 위험

#### 옵션 R — supervised 결과는 zero-day 발견용, 운영 ranking 은 PHASE1 우선 (과거안, 폐기)

- supervised score 는 "rule 이 못 잡은 잔여 후보" 발견용 부가 입력
- 과거안은 운영 ranking 을 PHASE1 `composite_sort_score` + PHASE2 anomaly_score 조합과 narrator ordering 에 연결했으나, 2026-05-26 계약 재정의로 폐기됐다.
- PHASE2 자체 평가 목표는 `unsupervised_selection_score` 향상 (truth recall 직접 아님)
- 장점: PHASE1 원칙 보존 + PHASE2 의 zero-day 발견 가치 확보
- 단점: PHASE2 의 운영 영향이 selected-case explanation layer가 아닌 ordering layer에 의존하게 된다.

### 현재 계약: PHASE1 기본 queue + PHASE2 family lane

**적용 방식**:

1. **PHASE2 학습 목표 = family signal 안정성**
   - 학습 metric: reconstruction_loss + KL_loss + group weight
   - 평가 metric: `score_tail_gap`, `topk_stability`, `capacity_penalty`, `score_degeneracy_penalty`
   - truth recall 은 보조 평가 (Layer C C4 SOFT WARN)

2. **supervised 활성화 조건 (future-state)**
   - 감사인 라벨 또는 신뢰 가능한 ground truth 확보
   - group/temporal holdout 검증
   - PR-AUC / precision@k / recall@k 4종 동시 측정
   - 본 거버넌스 적용 시 옵션 Q 로 전환하되 fitting 가드 (A3 / A4 / C5) 우선

3. **Local Evidence Brief**
   - PHASE1 review queue 또는 PHASE2 family lane 에서 사용자가 선택한 case만 설명한다.
   - Local Evidence Brief는 후보 순서를 바꾸거나 새 priority 를 부여하지 않는다.
   - PHASE2 family signal 은 local provenance / evidence brief 입력으로만 사용한다.

4. **"PHASE2 가 향상시켜야 할 metric"의 정의**:
   - **PHASE2 자체 목표**: family별 standalone signal 안정성 (C1~C3)
   - **PHASE2 부수효과**: DataSynth truth Top500 recall (C4 — 향상 강제 금지, 회귀 방지선만)
   - **PHASE2 가 절대 직접 추구하면 안 되는 metric**: truth recall, precision@k (supervised target 없음)

### 옵션 R 의 가드 충돌 방지

| 위험 | 차단 가드 |
|------|----------|
| 라벨 누설 학습 | A1 (deny column), A7 (target_used==false) |
| 학습 분포 fitting | A3 (normal sample FP), A4 (contract HIGH 비율) |
| split 누설 | A5 (split policy), A6 (preprocessing fit split) |
| truth recall 강제 향상 PR | M1 (Layer C 가드 모두 SOFT_WARN), baseline 갱신 PR 의 D044 fitting-risk check |
| ranking instability | C2 (tail_gap), C3 (topk_stability) |

---

## 결정 6 — 모델 lock / 버전관리 / 재학습 정책

### 6.1 회사별 모델 저장 격리 (RC-3 ✅ 활용)

[NEW_TASKS.MD RC-3 완료 항목](completed/NEW_TASKS.MD) 인프라 사용. `CompanyContext.model_dir` 가 이미 제공.

```
data/companies/{company_id}/engagements/{year}/models/
└── phase2_unsupervised/
    └── {model_version}/                   # e.g. 2026Q2-vae-balanced-a7f3
        ├── model.pt                       # PyTorch state_dict
        ├── preprocessing.pkl              # fitted preprocessing plan
        ├── training_report.json           # 학습 메타데이터 (M3)
        ├── schema_hash.txt                # column order / encoding hash
        ├── shap_background.parquet        # SHAP background sample
        └── promotion_record.json          # 승격 결정 (옵션)
```

**model_version 규칙**: `{YYYY}Q{q}-{family}-{preset}-{git_sha[:4]}`
예: `2026Q2-vae-balanced-a7f3`

**격리 정책**:
- engagement 디렉토리는 회사·연도별 독립
- 다른 회사의 모델 로드 금지 (`ContextFactory.create()` 가 model_dir 강제)
- CI 가드 fixture (normal_sample_300, contract_v2) 는 `data/journal/test_normal_sample/` 공용

### 6.2 재학습 trigger matrix

| trigger | 검증 강도 | 자동/수동 | 단일 출처 |
|---------|----------|----------|----------|
| 데이터셋 버전 변경 | 전체 재학습 + 전 가드 | 자동 (dataset_id 변경 감지) | `training_report.dataset_version` |
| 시간 경과 — 분기 | 전체 재학습 + 전 가드 | 수동 권장 (Q+1 첫 주) | `training_completed_at` |
| 시간 경과 — 연도 | 전체 재학습 + supervised 활성화 검토 | 수동 | engagement 신규 생성 |
| Layer C SOFT WARN 3회 누적 | 회귀 원인 분석 + 선택적 재학습 | 자동 (issue 생성) → 수동 결정 | `_kpi_guard_softwarn_history.json` (PHASE1 과 동일 패턴) |
| Layer C SOFT WARN 6회 누적 | 재학습 또는 baseline 갱신 PR 의무 | 수동 (PR 의무) | 동일 |
| 사용자 명시 trigger | 사용자 정의 | 수동 | dashboard / CLI |
| 새 engagement 생성 | base 모델 복제 또는 재학습 선택 | 수동 | RC-4 UI |

### 6.3 모델 lock + 승격 절차

**lock** (학습 완료 시 자동):

1. `model.pt` SHA-256 hash 계산 → `training_report.model_hash`
2. `schema_hash` 계산 → `model_bundle.schema_hash` 와 일치 검증 (A8 가드)
3. `training_report.json` 의 read-only 권한 부여 (RC-3 ConnectionManager 와 별도)

**baseline 모델 vs candidate 모델 비교**:

| 단계 | 검증 |
|------|------|
| 1. 동일 fixture (normal_sample_300, contract_v2) 추론 | 가드 A3 / A4 통과 |
| 2. 동일 manipulation_v2 truth set 측정 | C4 (Top500 recall) baseline × 70% 이상 |
| 3. cross-engagement 분포 차이 | C5 baseline × 1.5 이하 |
| 4. unsupervised_selection_score | C1 baseline × 70% 이상 |
| 5. Local Evidence Brief provenance 정합 | M2 feature_id metadata 정합 |

### 6.4 승격 PR 템플릿 (D044 확장)

```markdown
## PHASE2 모델 승격

- engagement: {company_id}/{year}
- candidate model_version:
- baseline model_version:
- training dataset (id, version, hash):
- preset / hyperparams:
- git_sha:

## Layer A 도메인 정합성 통과

- [ ] A1 leakage deny column 미사용
- [ ] A2 leakage deny rule 미사용
- [ ] A3 normal_sample_300 FP ≤ 5%
- [ ] A4 contract_v2 HIGH 비율 ≤ 1%
- [ ] A5 split policy ∈ {group_by_document_id, temporal_holdout}
- [ ] A6 preprocessing fit split == train
- [ ] A7 비지도 모델 target_used == false
- [ ] A8 schema_hash 일치

## Layer B 운영 부하 통과

- [ ] B1 inference 50k 행 elapsed_sec:
- [ ] B2 bundle size MB:
- [ ] B3 training elapsed_sec:
- [ ] B4 peak VRAM MB:
- [ ] B5 training_report 필수 키 존재

## Layer C 회귀 영향 검토

- C1 unsupervised_selection_score: baseline vs candidate
- C2 score_tail_gap: baseline vs candidate
- C3 topk_stability: baseline vs candidate
- C4 manipulation truth Top500: baseline vs candidate (SOFT WARN 기준)
- C5 cross-engagement std: baseline vs candidate

## fitting-risk check (D044 계승)

- truth recall 향상을 직접 사유로 한 학습 코드 / 하이퍼파라미터 조정 여부:
- label, scenario, document id, 특정 생성 패턴에 맞춘 학습 데이터 필터링 여부:
- 정상 모집단 (normal_sample_300 / contract_v2 noise) false positive 영향:
- rollback 필요 여부:

## 후속 action

- 구 모델 archive:
- inference contract pin:
- dashboard 메타 갱신:
- 문서 갱신:
```

### 6.5 모델 deprecation

| 단계 | 정책 |
|------|------|
| 신구 병행 운영 | 1 분기 (`active` + `previous` 동시 로드 가능). Local Evidence Brief는 active model metadata만 참조 |
| 구 모델 archive | `data/companies/{id}/engagements/{year}/models/_archive/{model_version}/` 이동, read-only |
| 구 모델 deletion | 2 분기 경과 후 또는 사용자 명시 요청 시. `git` 로 hash 추적 가능 |
| rollback | archive 디렉토리에서 active 로 복원 + ConnectionManager 캐시 무효화 |

---

## 결정 7 — CI 가드 자동화 (phase2-kpi-guard.yml)

### 7.1 workflow 구조 (초안)

PHASE1 `phase1-kpi-guard.yml` 패턴 계승.

```yaml
name: phase2-kpi-guard

on:
  pull_request:
    branches: [main, develop]
    paths:
      - "src/preprocessing/**"
      - "src/detection/vae_detector.py"
      - "src/services/phase2_training_service.py"
      - "src/services/phase2_inference_service.py"
      - "config/settings.py"
      - "tests/phase2_rulebase/**"
      - "artifacts/phase2_*"
  push:
    branches: [main]
  schedule:
    - cron: "0 10 * * 1"   # 월요일 10:00 UTC (PHASE1 보다 1시간 뒤 — 자원 충돌 회피)
  workflow_dispatch: {}

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  kpi-guard:
    runs-on: ubuntu-latest
    timeout-minutes: 60     # PHASE1 (30분) 보다 길게, 학습 검증 포함
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --group core --group ml --group dev

      - name: Restore Layer C soft warn history
        id: softwarn-history-restore
        uses: actions/cache/restore@v4
        with:
          path: artifacts/_phase2_kpi_guard_softwarn_history.json
          key: phase2-kpi-guard-softwarn-${{ github.ref_name }}-${{ github.run_id }}
          restore-keys: |
            phase2-kpi-guard-softwarn-${{ github.ref_name }}-

      - name: Layer A + B (HARD FAIL)
        id: hard
        shell: bash
        run: |
          set -o pipefail
          uv run pytest tests/phase2_rulebase/nightly_kpi_guard.py \
            -v \
            -k "TestLayerADomainIntegrity or TestLayerBOperationalLoad or TestGuardMetaIntegrity" \
            --tb=short \
            2>&1 | tee artifacts/_phase2_kpi_guard_hard.log

      - name: Layer C (SOFT WARN)
        id: soft
        if: always()
        continue-on-error: true
        run: |
          uv run pytest tests/phase2_rulebase/nightly_kpi_guard.py \
            -v \
            -k "TestLayerCRankingRegressionSoftWarn" \
            -W "default::UserWarning" \
            --tb=no \
            2>&1 | tee artifacts/_phase2_kpi_guard_soft.log

      # PR 코멘트 / 누적 issue / post-merge 등은 PHASE1 패턴 동일
      # (artifacts/_phase2_kpi_guard_softwarn_history.json 별도 키)
```

### 7.2 회사별 격리 모델 vs CI 단일 fixture 의 관계

**문제**: 회사별 모델이 격리 저장되는데, CI 는 단일 fixture 로 어떻게 회귀를 검증?

**해법** — CI 는 합성 데이터 기반 baseline 모델만 검증:

| CI 검증 대상 | baseline 모델 |
|------------|-------------|
| Layer A1/A2/A5/A6/A7/A8 | 학습 코드 무결성 — 모델 없이 dry-run / contract 검증 |
| Layer A3 (normal sample FP) | `data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/{ci_baseline_version}/` |
| Layer A4 (contract HIGH) | 동일 baseline 모델 |
| Layer B1~B4 | baseline 모델 학습/추론 |
| Layer C1~C5 | baseline 모델 metrics vs `tests/phase2_rulebase/kpi_baseline.json` |

**CI baseline 모델 운영**:
- 학습 데이터: `datasynth_manipulation_v3` (현재 Rust 승격) + `datasynth_contract_v2`
- 학습 환경: GitHub Actions runner (CPU only) 또는 self-hosted runner (GPU)
- 갱신 trigger: dataset 버전 변경 또는 학습 코드 major 변경
- 회사별 실 운영 모델과 별개

### 7.3 post-merge issue 생성 조건

PHASE1 패턴 그대로:

| trigger | issue label |
|---------|-----------|
| main push + Layer A/B HARD FAIL | `kpi-guard`, `regression`, `phase2` |
| weekly cron + Layer C SOFT WARN ≥ 3 consecutive | `kpi-guard`, `soft-warn`, `phase2` (milestone 3) |
| weekly cron + Layer C SOFT WARN ≥ 6 consecutive | 위 + baseline 갱신 PR 의무 (milestone 6) |
| streak reset | milestones_opened 초기화 (PHASE1 [CONSTRAINTS.md §milestones 초기화 정책 (streak-reset)](CONSTRAINTS.md) 그대로) |

### 7.4 PHASE1 / PHASE2 가드의 독립성

| 분리 항목 | 이유 |
|----------|------|
| `_kpi_guard_softwarn_history.json` 파일 별도 | PHASE1 회귀 vs PHASE2 회귀 streak 독립 |
| workflow 별도 (`phase1-kpi-guard.yml` / `phase2-kpi-guard.yml`) | PR diff scope 가 다름 (`paths:` filter) |
| baseline JSON 별도 (`tests/phase1_rulebase/` / `tests/phase2_rulebase/`) | 가드 의미 충돌 방지 |
| cron 시간차 (09:00 / 10:00 UTC) | runner 자원 충돌 회피 |

---

## 결정 8 — PHASE2 family ranking 정책 (2026-05-19 기록, 2026-05-26 user-facing 계약 갱신)

> **2026-05-26 계약 갱신**: 아래 Noisy-OR / RRF 통합 queue 서술은 과거 측정·구현 기록으로만 유지한다. 현재 user-facing 공식 queue 계약은 PHASE1 기본 review queue + PHASE2 family별 독립 review lane 이다. PHASE1+2 통합 ranking, PHASE2 global risk score, and PHASE3 LLM ordering layer are removed from the official queue contract. Selected-case explanation may use only deterministic Local Evidence Brief.

### 8.0 현재 결정 요지

1. **PHASE1 기본 review queue 유지**: 공식 user-facing 기본 queue는 PHASE1 case priority를 따른다.
2. **PHASE2 family별 독립 review lane 유지**: PHASE2는 duplicate / relational / timing / intercompany / unsupervised 등 family lane별 신호와 설명 feature를 노출한다.
3. **통합 ranking 제거**: PHASE1+2 통합 queue, PHASE2 global risk score, final combined rank는 공식 queue 계약에서 제거한다.
4. **Local Evidence Brief**: selected case 화면은 외부 LLM 없이 PHASE1 evidence와 PHASE2 family signal을 deterministic하게 요약하며, ordering에 영향을 주지 않는다.

### 8.0a 과거 Noisy-OR 결정 기록 (현재 공식 queue 계약 아님)

PHASE2 5 family 결합 ranking 은 과거 **Noisy-OR separated** 로 채택된 적이 있다. 이 기록은 측정 재현성과 구현 이력 보존 목적이며, 현재 user-facing 공식 queue 계약이 아니다. 당시 결정은 다음과 같았다.

1. **RRF 적용 범위 제한**: PHASE1 ↔ PHASE2 의 전역 결합 (2-way RRF k=60) 한정. PHASE2 내부 5 family 결합에는 RRF 미사용.
2. **PHASE2 internal 결합 = Noisy-OR**: `phase2_internal_noisy_or(case) = 1 - Π_f (1 - ecdf_f(case))`. 5 family ECDF 를 독립 anomaly 확률로 해석한 OR 결합. 단, 0/NaN 은 "무신호"로 보존하며 percentile 중간값으로 올리지 않는다.
3. **Reject 결정** (PHASE2 internal hierarchical RRF): V7 fixed3 measurement-only 비교에서 TOP 100~5000 평균 -6.45pp 손실. supervised/transformer 활성화 시 재평가.
4. **family signal lane/overlay/tie-break/narrator citation 보조 노출 유지**: ranking 합산과 별개로 attribution 용도. 현재는 family lane과 selected-case evidence brief 입력으로만 유지한다.

### 8.0b 과거 채택 산출물 (Noisy-OR separated, 2026-05-19)

| 항목 | 값 |
|------|---|
| 채택 측정 산출물 | [`artifacts/phase2_family_ranking_alt_aggregators_20260519.md`](../artifacts/phase2_family_ranking_alt_aggregators_20260519.md) (탐색) / [`artifacts/phase1_phase2_integration_report_noisy_or_20260519.md`](../artifacts/phase1_phase2_integration_report_noisy_or_20260519.md) (운영 production run) |
| 탐색 measurement Δ — alt_aggregator (`synthesize_phase1_composite` 근사 + 일반 ECDF) | 초기 batch-local 일반 ECDF 측정에서는 전 깊이 양수였으나, 0/NaN 무신호를 percentile 중간값으로 올리는 결함이 있어 **운영 성능 주장으로 사용하지 않음** |
| 운영 production V7 fixed3 recall — Noisy-OR voter (queue_integrated.parquet) | TOP 100 22.42% (139) / TOP 500 45.48% (282) / TOP 1,000 49.68% (308) / TOP 2,000 59.68% (370) |
| 운영 production V7 fixed3 recall — legacy PHASE1+VAE 2-way RRF (비교용) | TOP 100 16.77% (104) / TOP 500 43.23% (268) / TOP 1,000 53.71% (333) / TOP 2,000 63.55% (394) |
| 깊이별 Δ (Noisy-OR − legacy) | TOP 100 **+5.65pp** / TOP 500 **+2.26pp** / TOP 1,000 **-4.03pp** / TOP 2,000 **-3.87pp** — **단조 우월 아님, 깊이별 trade-off** |
| 종합 truth recall 비교 | TOP 100~2,000 평균 Δ ≈ 0pp — 운영적으로 **사실상 동률**. 분포만 상단(TOP 100~500)으로 재배치된 형태. truth recall 은 informational only (feedback_phase1_truth_recall_guard 준수). |
| 채택 사유 (truth recall 개선 아님) | (a) 5-family signal 을 단일 PHASE2 voter 와 narrator attribution 으로 **일관되게 표준화** (b) **무신호(0/NaN) 보존** — 일반 ECDF 의 percentile 중간값 결함 회피 (c) **parameter 0개 / weight 0개 / fitting 위험 0** — PHASE1 truth-recall-guard 무충돌 |
| Production run 산출 위치 | 과거 산출: `queue.parquet` 는 PHASE1 단독 큐 alias, `queue_integrated.parquet` 는 통합 큐 산출물. 현재 공식 user-facing queue 계약에서는 통합 큐를 사용하지 않음. |
| 채택 helper | `src/services/queue_fusion.py::compute_phase2_internal_noisy_or` |
| 채택 wiring | `tools/scripts/phase1_phase2_integration_stage7.py::build_integrated_queue` |
| 정정 기록 | [`docs/TROUBLESHOOT.md` TS-15](TROUBLESHOOT.md#ts-15) |

### 8.1 사용자 승인 문장 (lock)

> Proceed with design pivot: keep primary PHASE1+VAE 2-way RRF, reject PHASE2 internal hierarchical RRF for production, preserve family diagnostics as lane/evidence overlays, and update governance/docs/tests accordingly.

후속 사용자 지시 (RRF 외 측정 진행 후):
> RRF를 버리고 다른방식으로 합산하는 건은 왜 안진행했어? RRF좀 씨발 집착하지말라고

→ 8 결합식 × 3 적용 방식 측정 → **Noisy-OR separated 채택**으로 결정 8 갱신.

### 8.2 측정 근거

#### 8.2a Hierarchical RRF reject 측정 (1차 시도, 폐기)

| 항목 | 값 |
|------|---|
| 측정 산출물 | [`artifacts/phase2_family_ranking_measurement_20260519.md`](../artifacts/phase2_family_ranking_measurement_20260519.md) |
| baseline | PHASE1 composite (dry-run 근사) ↔ VAE ECDF 2-way RRF k=60 |
| 비교 대상 | hierarchical RRF (active=unsup+duplicate / booster=timeseries+relational / near-dormant=intercompany) |
| TOP 100 Δrecall | -0.48pp |
| TOP 500 Δrecall | -6.45pp |
| TOP 1,000 Δrecall | -10.64pp |
| TOP 2,000 Δrecall | -7.90pp |
| TOP 5,000 Δrecall | -6.77pp |
| 원인 진단 | 5 family 가 동등 voter 가 아님 (unsupervised 연속 / duplicate 이산 cap / timeseries 2값 이산 / intercompany 99.997% 0). voter 형식 통일 시 unsupervised 의 연속 분해능이 dilute 됨. |
| 재평가 조건 | supervised / transformer 등 family 가 추가 활성화되어 모든 active family 가 연속·전역 ranker 가 될 때 |

#### 8.2b Noisy-OR separated 채택 측정 (2차 시도, 채택)

| 항목 | 값 |
|------|---|
| 측정 산출물 | [`artifacts/phase2_family_ranking_alt_aggregators_20260519.md`](../artifacts/phase2_family_ranking_alt_aggregators_20260519.md) |
| 측정 범위 | 8 결합식 (max / tier_weighted_sum / cascade_boost / evidence_vote / noisy_or / rank_product / geometric_mean / top_k_mean) × 3 적용 (phase2_only / separated / unified) = 24 측정 + baseline 2 |
| **측정 1 baseline** | VAE ECDF 단독 (PHASE2 internal 비교) |
| Noisy-OR Δ vs VAE 단독 | 초기 batch-local ECDF 측정값. 0/NaN 무신호 row 에 양의 ECDF가 부여되는 문제가 있어 운영 성능 근거로 사용하지 않음 |
| **측정 2 baseline** | PHASE1 composite + VAE ECDF 2-way RRF k=60 |
| Noisy-OR separated Δ vs baseline | 초기 batch-local ECDF 측정값. 운영 helper 를 zero-preserving ECDF 로 수정한 뒤에는 local V7 fixture 에서 legacy PHASE1+VAE 2-way 와 동률 |
| 일관성 | Noisy-OR 식은 유지하되, 성능 향상 주장은 제거. 사용 목적은 5-family attribution 을 단일 PHASE2 voter 로 표준화하는 것 |
| 도메인 해석 | 각 family ECDF 를 독립 anomaly 확률로 해석한 OR 결합. 0/NaN 은 무신호로 보존. V7 §6 family 보완성 (시나리오별 분담) 을 한 점수에 흡수하되, truth recall 향상 근거로 주장하지 않음 |
| Production run 검증 | TOP 100/500/1,000/2,000 doc recall (queue_integrated.parquet, Noisy-OR voter): **22.42% / 45.48% / 49.68% / 59.68%** (139 / 282 / 308 / 370 truth docs). legacy PHASE1+VAE 2-way 대비 깊이별 trade-off: TOP 100 +5.65pp / TOP 500 +2.26 / TOP 1,000 **-4.03** / TOP 2,000 **-3.87**. **단조 우월 아님**, 평균 ≈ 0pp 종합 동률. queue.parquet alias 는 PHASE1 단독 큐 분리 보존. |

### 8.3 RRF 적용 범위 + PHASE2 internal 결합식

| 적용 영역 | 결합식 | 상태 |
|---|---|---|
| primary global queue | `1/(60 + rank_phase1_composite) + 1/(60 + rank_phase2_internal_noisy_or)` | 과거 산출 기록. 현재 공식 user-facing queue 에서 제거 |
| PHASE2 internal family 결합 | `1 - Π_{f ∈ 5 families} (1 - ecdf_f)` (Noisy-OR) | 과거 PHASE2 voter/helper 기록. 현재는 family별 lane과 설명용 overlay가 공식 노출 단위 |
| PHASE2 internal hierarchical RRF | (도입 안 함) | ❌ V7 fixed3 -6.45pp 손실로 reject |
| 미래 supervised/transformer 결합 | (재평가 조건부) | hierarchical RRF 재평가 가능 |

과거 운영 식 기록 (현재 공식 user-facing queue 계약 아님):

```
# 이전 (PHASE2 voter = VAE ECDF 단독)
final_score(case) = 1/(60 + rank(phase1_composite_sort_score))
                  + 1/(60 + rank(phase2_unsupervised_score_max))

# 과거 기록 (PHASE2 voter = 5-family Noisy-OR)
phase2_internal_noisy_or(case) = 1 - Π_f (1 - ecdf_f(case))  # zero-preserving 5 family ECDF
final_score(case) = 1/(60 + rank(phase1_composite_sort_score))
                  + 1/(60 + rank(phase2_internal_noisy_or))
```

위 식은 과거 통합 queue 산출 기록이다. 현재 공식 user-facing queue 는 PHASE1 기본 review queue 와 PHASE2 family lane 으로 분리되며, 위 final_score 를 최종 우선순위로 사용하지 않는다.

과거 측정 효과 — V7 fixed3 fixture 측정으로는 **종합 truth recall 사실상 동률**. TOP 100/500 에서 +5.65/+2.26pp 개선, TOP 1,000/2,000 에서 -4.03/-3.87pp 손실의 깊이별 trade-off. 이 기록은 truth recall 개선 주장이 아니라 과거 산출물의 재현성 설명으로만 유지한다.

### 8.4 family signal 노출 4 경로

| 경로 | 정의 | 출처 코드 |
|---|---|---|
| lane | dashboard 보조 큐. `duplicate / relational / timing / intercompany` 별 정렬. evidence_tier desc → family ECDF desc. | `dashboard/components/phase2_family_lanes.py`, `src/services/phase2_lane_sort.py` |
| overlay | `Phase2CaseOverlay.family_contributions[{family, score, ecdf, role, evidence_tier, sub_detectors}]` + `top_family` + `coverage_breadth_q95` + `max_family_ecdf` + `max_evidence_tier` + `lane_membership` + `coverage_gap_families` | `src/services/phase2_case_contract.py::build_phase2_case_overlays` |
| tie-break | primary RRF 동률·near-tie 한정 6단 ladder. weighted score 금지. | `src/services/phase2_case_contract.py::apply_phase2_tie_break` |
| local evidence provenance | `phase2_family_contributions`, `phase2_top_family`, `phase2_lane_membership`, `phase2_max_evidence_tier` 등 Local Evidence Brief 입력 | dashboard/detail/export local evidence view |

### 8.5 Tie-break 가드 (lock)

> **Tie-break ladder는 primary RRF의 동률 또는 near-tie 보조 정렬에만 사용하며, primary queue의 기본 순위를 뒤집는 별도 weighted score로 사용하지 않는다.**

구현 가드:
- 동률 정의: `primary RRF score 차이 ≤ near_tie_eps` (기본 1e-9, float 정밀도)
- ladder 적용은 lexicographic 비교만, weight 가중합 금지
- regression test `tests/modules/test_services/test_phase2_case_contract.py::test_tie_break_preserves_primary_order_outside_near_tie` 가 near-tie 외 영역에서 primary 순위 보존을 검증

### 8.6 family role 4 상태 (L0 metric 자동 판정)

| role | 임계값 | 운영 의미 |
|---|---|---|
| active-ranker | row_nonzero_rate ≥ 0.001 AND rank_resolution ≥ 0.01 AND top_tail_resolution ≥ 0.5 | lane 노출, primary tier badge 계산에 참여 |
| coarse-booster | rank_resolution < 0.01 OR top_tail_resolution < 0.5 (≥ 0.2) | lane 노출, "보조" 배지 |
| tail-only-fallback | top_tail_resolution < 0.2 | lane 노출, "꼬리만" 배지 |
| near-dormant | row_nonzero_rate < 0.001 | lane 표시는 유지하되 "데이터 미보유" 배지, coverage_gap_families 에 포함 |

L0 metric:
- `row_nonzero_rate`: score > 0 인 행 / 전체 행 (near-dormant 진단)
- `rank_resolution`: unique rank 수 / 전체 행 (coarse 진단)
- `top_tail_resolution`: 1 - (largest tie block at or above q95 / top_tail_count) (tail 변별력 진단)

role classification 은 **training 시점에 결정 + `training_report.json` 의 `metadata.family_diagnostics.roles` 에 pin**. inference 마다 재계산하면 role 이 진동하므로 재분류는 재학습 trigger 로만 통제 (§6.2 trigger matrix 정합).

### 8.7 evidence_tier 거버넌스 lock

`config/phase2_subdetector_tiers.yaml` 단일 출처. 21 sub-detector (1 unsupervised + 2 timeseries + 7 relational + 4 duplicate + 7 intercompany) 모두 cover. relational R05~R07 (rare_account_partner_edge / user_account_degree_spike / dormant_partner_reactivation) 은 2026-05-24 graph/entity anomaly 보강으로 추가. intercompany internal probability column 4개 (`ic_reciprocal_flow_prob` strong / `ic_amount_prob` moderate / `ic_unmatched_prob` weak / `ic_timing_prob` weak) 는 2026-05-25 옵션 2 (lane evidence_role priority) 적용으로 추가 등록 — score 합성 변경 없음, lane sort `ic_role_priority` secondary dim 노출 용도 (docs/PHASE2_INTERFACE_DESIGN.md §4.3.2). IC internal prob hit 은 의도적으로 family entry `evidence_tier` 로 승격되어 `classify_phase2_review_band` 분류에도 영향 (audit semantic — ISA 550 ¶A20 / PCAOB AS 2401 §B7 인용 정합). 회귀 가드는 `TestIntercompanyInternalProbReviewBandImpact` 6 케이스. 각 항목에 `source_type ∈ {standard, distribution}` + 출처 인용 (PCAOB AS 2401 / ISA 240 / ISA 550 또는 V7 fixed3 분포 측정값) 필수.

| 가드 | 위치 |
|---|---|
| 21 항목 누락 차단 | `tests/phase2_rulebase/test_subdetector_tiers_schema.py::TestCoverage` |
| tier ∈ {strong, moderate, weak, ml_quantile} | 동 schema test `TestTierValues` |
| 출처 필수 | 동 schema test `TestSourceFields` + `TestStrongTierStandardBacking` |
| IC lane role priority 회귀 | `tests/modules/test_services/test_phase2_lane_sort.py::TestIntercompanyRolePriority` |
| PR 변경 절차 | [`docs/DECISION.md` D044 fitting-risk check](DECISION.md) — "PHASE2 sub-detector tier 변경 여부" 명시. truth recall 사유 금지. |

### 8.8 PHASE1 truth-recall-guard / 옵션 R / 옵션 Z 정합

| 기존 정책 | 결정 8 정합 여부 | 근거 |
|---|---|---|
| `feedback_phase1_truth_recall_guard` | ✅ 정합 | tier·role·tie-break 가드 모두 truth label 미사용. parameter 0 개. |
| 결정 5 옵션 R 의 과거 ranking 서술 | 폐기됨 | 2026-05-26 계약 재정의로 narrator ordering 의존을 제거. PHASE2 family signal 은 selected-case evidence brief 입력으로만 사용. |
| 결정 3 옵션 Z (independent queue) | 갱신 필요 | PHASE1 기본 queue 와 PHASE2 family별 독립 lane 은 유지. PHASE1+2 통합 queue / Noisy-OR final ranking 은 공식 user-facing queue 에서 제거. |
| Layer C SOFT WARN 원칙 | ✅ 정합 | family_diagnostics 안정성 metric 은 SOFT WARN 만 (baseline × 0.7 하한). 향상 강제 금지. |
| Meta M1 (truth recall 향상 강제 가드 금지) | ✅ 정합 | tier/role 모두 truth 미사용. lane 정렬도 분포 기반. |

### 8.9 산출물 인덱스 (결정 8 과거 기록)

#### 과거 채택 코드 (Noisy-OR separated, 2026-05-19)

| 파일 | 역할 |
|------|------|
| `src/services/queue_fusion.py::compute_phase2_internal_noisy_or` | 과거 PHASE2 5-family Noisy-OR helper. 현재 공식 user-facing queue priority 산출에는 사용하지 않음 |
| `src/services/queue_fusion.py::to_ecdf` | zero-preserving ECDF 변환 helper (0/NaN 무신호 보존) |
| `tools/scripts/phase1_phase2_integration_stage7.py::build_integrated_queue` | 과거 통합 큐 산출물 생성. 현재 공식 user-facing queue 계약에서는 제거 |
| `tools/scripts/phase2_family_ranking_alt_aggregators.py` | 8 결합식 measurement script (재현 가능) |
| `tests/modules/test_services/test_queue_fusion.py::TestNoisyOr*` | Noisy-OR helper 회귀 (33 tests) |
| `tests/modules/test_services/test_phase1_phase2_integration_stage7.py` | 운영 wiring 회귀 (15 tests) |

#### 보조 코드 (Phase A~F 사전 작업)

| 파일 | 역할 |
|------|------|
| `config/phase2_subdetector_tiers.yaml` | 21 sub-detector tier lock 단일 출처 (relational R05~R07 graph/entity 보강 2026-05-24, IC 4개 internal prob column 2026-05-25 옵션 2) |
| `src/services/subdetector_tiers.py` | tier loader + 검증 |
| `src/services/phase2_family_diagnostics.py` | L0 3 metric + role classifier + metadata pin |
| `src/services/phase2_case_contract.py` | Phase2CaseOverlay 확장 + 6단 tie-break (가드 포함) |
| `src/services/phase2_lane_sort.py` | lane 내부 정렬 helper |
| `dashboard/components/phase2_family_lanes.py` | lane view 컴포넌트 |
| `tests/phase2_rulebase/test_subdetector_tiers_schema.py` | tier YAML schema test |
| `tests/modules/test_services/test_phase2_family_diagnostics.py` | L0 metric + role classifier 회귀 |
| `tests/modules/test_services/test_phase2_case_contract.py` | overlay 신규 필드 + 6단 tie-break 가드 회귀 |
| `tests/modules/test_services/test_phase2_lane_sort.py` | lane 정렬 회귀 |
| `tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py` | primary queue 보존 회귀 |
| `tests/modules/test_dashboard/test_phase2_family_lanes.py` | lane UI helper 회귀 |

#### 격리 코드 (Hierarchical RRF, V7 fixed3 reject)

| 파일 | 역할 |
|------|------|
| `src/services/queue_fusion.py::compute_phase2_internal_rrf` | **EXPERIMENTAL** — V7 fixed3 -6.45pp reject, 미래 재평가용 보존 |
| `tests/modules/test_services/test_queue_fusion_hierarchical.py` | `@pytest.mark.experimental_phase2_internal_rrf` 격리 |
| `tools/scripts/phase2_family_ranking_dry_run.py` | reject measurement 재현 script |

#### 측정 산출물

| 파일 | 역할 |
|------|------|
| `artifacts/phase2_family_ranking_measurement_20260519.{md,json}` | hierarchical RRF reject 근거 |
| `artifacts/phase2_family_ranking_alt_aggregators_20260519.{md,json}` | **Noisy-OR 채택 근거 — 8 결합식 × 3 적용 측정** |
| `artifacts/phase1_phase2_integration_report_5way_20260519.{md,json}` | production run TOP 100/500/1000/2000 recall (Noisy-OR voter 적용) |

#### 거버넌스 / 플랜 / 정정 기록

| 파일 | 역할 |
|------|------|
| `docs/TROUBLESHOOT.md` TS-15 | 결정 과정 (hierarchical RRF reject → Noisy-OR 채택) 정리 |
| `docs/users/08_PHASE2_FAMILY_STRUCTURE.md` | 사용자 문서 — Noisy-OR 채택 반영 |
| `docs/users/09_REVIEW_QUEUE_RRF_FUSION.md` | 사용자 문서 — RRF 적용 범위 한정 + Noisy-OR 식 명시 |
| `dev/active/phase2-family-ranking/` | plan/context/tasks 3 파일 |

---

## 결정 9 — Timeseries family role lock (2026-05-25)

### 9.1 결정 요지

`timeseries` family (TS01 transaction_burst / TS02 unusual_frequency) 의 운영 역할을 **결산·시점·빈도 컨텍스트 lane** 으로 고정한다. TOP100/500 단독 ranker 성능 추격(특히 truth recall 튜닝)을 거버넌스 단에서 차단한다.

### 9.2 배경 — 왜 락이 필요한가

V7 fixed3 → fixed4/fixed5 의 timeseries detector 재설계 측정에서 다음이 관찰됨.

| 깊이 | timeseries 단독 lane recall (방향성) | 해석 |
|---|---|---|
| TOP 100 | 약함 | 단독 precision ranker 로 부적합 — 정상 결산 이벤트와 분포 겹침 |
| TOP 500 | 약함 | 동일 — period_end/manual/amount_tail 조합 fitting attractor 존재 |
| TOP 2000+ | 보조 coverage 회복 | 결산/시점 컨텍스트로 다른 family 후보를 보강 |

추가 튜닝 시 발생 가능한 fitting attractor:
- `period_end` window 임의 확장 (분포는 좁아지지만 정상 결산도 같이 끌려옴)
- `manual` flag · `amount_tail` 조합 weight 강화 (DataSynth 의 `is_anomaly` sidecar 형태에 맞춰 학습되는 형태)
- inference batch ECDF 의 q-cap 조정 (정상 routine close 이벤트와 조작 close 이벤트가 batch 분포상 겹침)

### 9.3 락 대상 정책

| 항목 | 락 내용 |
|------|--------|
| 단독 precision ranker | **금지** — TS lane 단독으로 review queue 의 TOP recall metric 을 직접 목표로 삼지 않는다 |
| TOP100/500 recall 튜닝 | **금지** — `period_end`/`manual`/`amount_tail` 등 fitting attractor 가중치 조정 차단 |
| primary queue 영향 | **없음** — TS lane 정렬은 `phase2_lane_sort.sort_lane` 의 evidence_tier desc → ECDF desc, primary 2-way RRF 순위 미변경 |
| ranker 의미 | **TOP2000+ 보조 coverage** — 결산/시점 컨텍스트 후보 검토 lane 으로만 사용 |
| 분포 baseline | inference batch-local ECDF 한정 — 회사별 routine closing calendar baseline 은 **후속 과제**, 본 락은 현 baseline 의 한계를 명시만 |

### 9.4 yaml 메타 (단일 출처)

`config/phase2_subdetector_tiers.yaml` TS01/TS02 항목에 결정 9 메타 5개 필드 추가.

| 필드 | 값 |
|------|---|
| `role_lock` | `context_lane` |
| `ranker_use` | `top2000_plus_context` |
| `do_not_tune_for_top_recall` | `true` |
| `coverage_profile` | "TOP100~500 단독 약함, TOP2000+ 보조 coverage 회복" |
| `batch_local_ecdf_caveat` | inference batch 분포 한정 + routine closing/batch calendar baseline 후속 명시 |

다른 family (relational/duplicate/intercompany/unsupervised) 는 본 메타 미설정 (락 범위 timeseries 한정).

### 9.5 가드 위치

| 가드 | 위치 |
|------|------|
| TS01/TS02 `role_lock == "context_lane"` | `tests/phase2_rulebase/test_subdetector_tiers_schema.py::TestTimeseriesRoleLock::test_ts0{1,2}_role_lock_is_context_lane` |
| TS01/TS02 `do_not_tune_for_top_recall == True` | 동 `test_ts0{1,2}_do_not_tune_for_top_recall` |
| TS01/TS02 `ranker_use == "top2000_plus_context"` | 동 `test_ts_ranker_use_top2000_plus` |
| coverage_profile / batch_local_ecdf_caveat 필수 | 동 `test_ts_coverage_profile_present` / `test_ts_batch_local_ecdf_caveat_present` |
| 다른 family 에 role_lock 설정 금지 | 동 `test_non_timeseries_families_have_no_role_lock` |

### 9.6 UI 표현 (결정 9 정합)

| 경로 | 변경 |
|------|------|
| `dashboard/components/phase2_family_lanes.py::LANE_LABELS["timeseries"]` | "Timing (시계열)" → "Timing Context (결산·시점 보조)" |
| 동 `render_lane_view` caption | "단독 ranker 아님 / 결산·시점 보조 lane / primary queue 영향 없음" 명시 |
| `dashboard/tab_phase2.py::_LANE_LABELS_KR["timeseries"]` / `_LANE_HINTS["timeseries"]` | "시점 이상" → "결산·시점 컨텍스트", 힌트에 TOP100~500 약함·TOP2000+ 보조 명시 |

### 9.7 변경 절차

본 락(role_lock / do_not_tune_for_top_recall / ranker_use) 의 yaml 값을 변경하려면:

1. `docs/PHASE2_TIMESERIES_ROLE_LOCK.md` §변경 절차 통과
2. `docs/DECISION.md` D044 PR 템플릿 "PHASE2 sub-detector tier 변경" fitting-risk check 통과
3. truth recall (DataSynth `is_fraud`/`is_anomaly`) 향상 사유 단독 **금지** — 도메인 정합성·기준서 인용 변경·운영 패턴 변경 등 비-truth 사유 필수
4. `TestTimeseriesRoleLock` 가드 갱신 + 회귀 통과

### 9.8 PHASE1 truth-recall-guard / 결정 8 정합

| 정책 | 정합 여부 | 근거 |
|------|----------|------|
| `feedback_phase1_truth_recall_guard` | ✅ | TS lane 은 `truth recall 향상 강제 금지` 정책의 PHASE2 분야별 적용. 락 자체가 truth label 미사용. |
| 결정 8 (Noisy-OR separated) | 과거 기록 | TS family ECDF 를 Noisy-OR voter 로 결합하던 과거 통합 queue 설명. 현재 공식 계약은 PHASE2 family lane 과 selected-case evidence brief 입력으로 한정. |
| 결정 8.6 (family role 4 상태) | ✅ | TS family 의 `role_lock` 메타 는 sub-detector 단 lock 으로, `family_diagnostics.roles` 자동 분류 (active-ranker / coarse-booster / tail-only-fallback / near-dormant) 와 직교. role lock 은 운영 정책 lock, family_diagnostics 는 분포 진단 자동 분류. |
| Layer C SOFT WARN | ✅ | TS lane 의 분포·case_count 변동은 진단만 (SOFT WARN), 향상 강제 미적용. |

### 9.9 산출물 인덱스 (결정 9)

| 파일 | 역할 |
|------|------|
| `config/phase2_subdetector_tiers.yaml` (TS01/TS02 메타 5필드) | 락 단일 출처 |
| `src/services/subdetector_tiers.py::SubdetectorTier` (optional 필드 5개 + `is_context_lane_locked` property) | loader + dataclass |
| `docs/PHASE2_TIMESERIES_ROLE_LOCK.md` | 락 문서 (변경 절차 포함) |
| `tests/phase2_rulebase/test_subdetector_tiers_schema.py::TestTimeseriesRoleLock` | 가드 8 케이스 |
| `dashboard/components/phase2_family_lanes.py` | lane UI 라벨/caption (결정 9.6) |
| `dashboard/tab_phase2.py::_LANE_LABELS_KR/_LANE_HINTS` | lane 한국어 라벨/힌트 (결정 9.6) |

---

## 부록 A — 산출물 인덱스

| 파일 | 상태 | 다음 단계 |
|------|------|---------|
| `docs/PHASE2_GOVERNANCE_DESIGN.md` (본 문서) | 설계 완료 | review |
| `artifacts/phase2_governance_design_audit.md` | 설계 감사 노트 | review |
| `tests/phase2_rulebase/kpi_baseline.json` | 스켈레톤 (값 미입력) | PHASE2 첫 학습 후 baseline 측정 PR |
| `.github/workflows/phase2-kpi-guard.yml` | 초안 (paths/key 만 설정) | nightly_kpi_guard.py 구현 후 활성화 |
| `tests/phase2_rulebase/nightly_kpi_guard.py` | 미구현 | A1~A8 / B1~B5 / C1~C5 / M1~M5 가드 함수 작성 |
| `data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/{ver}/` | 미생성 | CI baseline 모델 학습 + commit (또는 LFS / artifact storage 검토) |
| D044 PR 템플릿 PHASE2 확장 | 본 문서 §6.4 초안 반영 필요 | DECISION.md 업데이트 PR |

## 부록 B — PHASE1 원칙 정합도 평가

| 결정 | PHASE1 원칙 정합도 | 주의점 |
|------|------------------|------|
| 결정 4 Layer 분리 | ✅ 동일 3-Layer + 메타 가드 구조 | A1/A2/A7 신규 도메인 — leakage 차단으로 정합 |
| 결정 5 옵션 R | ✅ truth recall 직접 목표 아님, 향상 강제 가드 없음 | supervised 활성화 시 옵션 Q 전환에서 정책 충돌 검토 필요 |
| 결정 6 모델 lock | ✅ D044 PR 템플릿 계승 + fitting-risk check 포함 | engagement 격리 vs CI baseline 분리 명확화 필요 |
| 결정 7 CI workflow | ✅ PHASE1 패턴 그대로, history 파일 분리 | CI runner 자원 (cron 시간차로 해결) |

## 부록 C — 리스크 / 미해결 항목

| # | 리스크 | 완화책 |
|---|------|------|
| 1 | CI baseline 모델 학습 비용 (GPU 미지원 runner) | 50k row cap + CPU 학습 600s 이내 / 또는 self-hosted runner / 또는 dataset cap |
| 2 | model_bundle 저장 위치 (git LFS / artifact / S3) | 미결. 본 설계는 CI baseline 만 git 또는 LFS, 회사별 운영 모델은 로컬 디스크 가정 |
| 3 | supervised 활성화 시 옵션 Q 전환 정책 | 별도 design PR 필요 (감사인 라벨 확보 시점) |
| 4 | normal_sample_300 fixture freshness | PHASE1 A4 freshness 정책 (contract_v2 generator 변경 시 갱신) 공유 — 본 설계 변경 없음 |
| 5 | engagement 별 baseline 가 다를 때 가드 임계값 | 본 설계는 CI baseline 단일 값. 회사별 baseline 은 dashboard 표시만 (CI 가드 적용 안 함) |
| 6 | training_report schema 변경 | Layer B5 가드가 required 키 검증. schema migration 시 baseline 갱신 PR 의무 |
