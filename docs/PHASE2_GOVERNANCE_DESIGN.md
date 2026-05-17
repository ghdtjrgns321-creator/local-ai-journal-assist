# PHASE2 거버넌스 / KPI 가드 설계

> **상태**: 설계안 (학습 baseline 측정 전). 본 문서는 가드 항목·정책·구조 정의이며, 임계값 baseline은 PHASE2 첫 학습 후 별도 PR에서 채운다.
>
> **단일 출처 예정**:
> - `tests/phase2_rulebase/kpi_baseline.json` — Layer A/B/C 기준값 (구조만 선반영)
> - `tests/phase2_rulebase/nightly_kpi_guard.py` — 가드 실행 (후속 구현)
> - `.github/workflows/phase2-kpi-guard.yml` — CI 트리거 (초안)
>
> **PHASE1 거버넌스 정합**: [docs/CONSTRAINTS.md §"PHASE1 CI KPI 가드 정책 (3-Layer 구조)"](CONSTRAINTS.md) · [tests/phase1_rulebase/kpi_baseline.json](../tests/phase1_rulebase/kpi_baseline.json) · [tests/phase1_rulebase/nightly_kpi_guard.py](../tests/phase1_rulebase/nightly_kpi_guard.py)

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
| **M2** | feature_id ↔ PHASE3 narrator enum 정합 | `training_report.feature_metadata.feature_ids` ⊆ `PHASE3_FEATURE_ENUM` | SHAP / feature_importance → narrator 인용 일관성. PHASE3 의 rule_id/feature_id 인용 계약 ([PHASE3_REVIEW_NARRATOR_SPEC.md](PHASE3_REVIEW_NARRATOR_SPEC.md)) |
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

#### 옵션 R — supervised 결과는 zero-day 발견용, 운영 ranking 은 PHASE1 우선 (권장)

- supervised score 는 "rule 이 못 잡은 잔여 후보" 발견용 부가 입력
- 운영 ranking 은 PHASE1 `composite_sort_score` + PHASE2 anomaly_score 의 조합 (PHASE3 narrator 가 재정렬)
- PHASE2 자체 평가 목표는 `unsupervised_selection_score` 향상 (truth recall 직접 아님)
- 장점: PHASE1 원칙 보존 + PHASE2 의 zero-day 발견 가치 확보
- 단점: PHASE2 의 운영 영향이 PHASE3 narrator 에 의존

### 권장: 옵션 R

**적용 방식**:

1. **PHASE2 학습 목표 = anomaly_score 의 ranking 품질** (`unsupervised_selection_score`)
   - 학습 metric: reconstruction_loss + KL_loss + group weight
   - 평가 metric: `score_tail_gap`, `topk_stability`, `capacity_penalty`, `score_degeneracy_penalty`
   - truth recall 은 보조 평가 (Layer C C4 SOFT WARN)

2. **supervised 활성화 조건 (future-state)**
   - 감사인 라벨 또는 신뢰 가능한 ground truth 확보
   - group/temporal holdout 검증
   - PR-AUC / precision@k / recall@k 4종 동시 측정
   - 본 거버넌스 적용 시 옵션 Q 로 전환하되 fitting 가드 (A3 / A4 / C5) 우선

3. **PHASE3 narrator 재정렬에서 ranking 결정**
   - PHASE1 ranking + PHASE2 anomaly_score → narrator 가 reorder
   - PHASE2 가 단독 운영 ranking 결정권 미보유

4. **"PHASE2 가 향상시켜야 할 metric"의 정의**:
   - **PHASE2 자체 목표**: `unsupervised_selection_score` 안정성 (C1~C3)
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
| 5. PHASE3 narrator 인용 정합 | M2 feature_id enum ⊆ |

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
| 신구 병행 운영 | 1 분기 (`active` + `previous` 동시 로드 가능). PHASE3 narrator 가 분기 비교 |
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
