# Phase 2 ML/DL 기술 타당성 분석 — 과도한 기술 심층 분석

> 작성일: 2026-04-10
> 최종 갱신: 2026-04-11 — 4대 결함 해결 플랜 실행 결과 반영
> 분석 범위: TASKS.md Phase 2 (WU-00 ~ WU-17) + 05a-detection-ml.md
> 분석 축: 과도한 기술, 누락된 기술, 아키텍처 정합성, 하드웨어 적합성

## 분석 대상
1. FT-Transformer vs XGBoost 역할 중복
2. BiLSTM+Attention 시퀀스 의미성
3. 6-model Stacking 순환 학습 위험

---

## 📋 결함 해결 현황 (2026-04-11 오후 갱신)

오전 세션(4대 결함) + 오후 세션(잔여 14개 항목 중 13개) 실행 결과.
스코프 내 단위 테스트 **234개 모두 통과**.

### 4대 결함

| # | 결함 | 우선순위 | 상태 | 비고 |
|---|------|---------|------|------|
| 1 | VAE 피처별 오차 분해 부재 | P0 | ✅ 완료 | §4-1 참조 |
| 2 | Stacking OOF 미구현 (Data Leakage) | P0 | ✅ 완료 | §3 참조 |
| 3 | BiLSTM 시퀀스 시간(시:분:초) 부재 | P1 | ⚠️ 코드만 완료 — **DataSynth 재생성 필요** | §2 참조 |
| 4 | 모델 드리프트 메타데이터 부재 | P1 | ✅ 완료 (저장까지) | §4-3 참조 |

### 잔여 14개 항목 처리 (오후 세션)

| # | 항목 | 묶음 | 상태 |
|---|------|------|------|
| 1 | BiLSTM `get_attention_weights()` 노출 | 1 | ✅ |
| 2 | FT-Transformer attention 추출 | 1 | ✅ |
| 3 | `drift_detector.py` + PSI 함수 | 1 | ✅ |
| 4 | risk_level 분위수 전환 | 1 | ✅ |
| 5 | 탐지기별 프로파일링 | 2 | ✅ |
| 6 | ThreadPoolExecutor 병렬화 | 2 | ✅ |
| 7 | 진행률 상세도 (탐지기별 콜백) | 2 | ✅ |
| 8 | 감사 증거 템플릿 (`src/export/audit_evidence.py`) | 3 | ✅ |
| 9 | VAE Waterfall 대시보드 UI | 3 | ✅ |
| 10 | 드리프트 배너 UI | 3 | ✅ |
| 11 | FT-T ablation 스크립트 골격 | 4 | ✅ (dry-run) |
| 12 | 재학습 정책 문서화 (D037) | 4 | ✅ |
| 13 | FT-T 유지/제거 판정 정책 (D038) | 4 | ✅ |
| 14 | FT-T ablation **실측** | 4 | ⚠️ 데이터 재생성 후 |

### 해결 요약

**P0-1 (VAE 설명력)**: `src/preprocessing/vae_wrapper.py::score_samples_per_feature(X) → (N, D)` 신규 public API. `src/detection/vae_detector.py::detect()`가 `details` DataFrame에 `ML02_top_feature_{1..3}` + `_contrib` 6개 컬럼 첨부. Top-K는 `np.argpartition`으로 O(N·D).

**P0-2 (OOF Stacking — User-Leakage 방어)**: `src/detection/ensemble_detector.py::train_oof()` 신규 진입점. `GroupKFold(n_splits=settings.stacking_cv_folds=3, groups=user_ids)` + `joblib.Parallel(n_jobs=-1, backend="loky")`. leakage-prone 트랙(Supervised/Transformer/Sequence)만 fold마다 재학습, 룰/VAE는 1회만 실행. `_train_fold_worker`는 모듈 최상위 함수로 분리하여 loky pickle 호환.

**P1-1 (시퀀스 시간)**: `tools/datasynth/crates/datasynth-output/src/csv_sink.rs` 헤더에 `posting_time` 컬럼 추가 (`item.header.created_at.format("%H:%M:%S")`). `src/db/schema.py`에 `posting_time TIME` 컬럼. `src/detection/sequence_detector.py::_build_timestamps()` 헬퍼 — `posting_date + to_timedelta(posting_time)` 조합으로 결정론적 시:분:초 정렬, 부재 시 기존 동작 fallback. **주의: 바이너리 재빌드 + 데이터 재생성 미수행 — 코드 경로만 준비된 상태.**

**P1-2 (드리프트 메타데이터)**: `src/preprocessing/data_stats.py` 신규 (`compute_training_stats` / `compute_class_imbalance` / `compute_feature_schema_version`). `ModelMetadata`에 `training_data_stats` / `feature_schema_version` / `class_imbalance_ratio` / `n_train_samples` 4개 필드 추가. 모든 detector(`supervised/transformer/sequence/vae/ensemble`) `save_model()`에서 전달. `list_models()`는 구버전 `registry.json` 하위호환 로드. **본 스프린트 범위 외**: `drift_detector.py`, PSI 계산, 대시보드 배너, 재학습 정책 문서화.

### 미수행 항목 (의도적)

- **DataSynth 재빌드 + CSV 재생성**: P1-1 Rust 변경은 코드·단위 테스트까지만. 실제 운영 데이터 반영은 별도 작업 필요:
  ```bash
  cd tools/datasynth && cargo build --release
  ./target/release/datasynth-data generate --config <config.yaml> --output ../../data/synthetic
  ```
- **`src/db/loader.py` 수정**: `posting_time` 컬럼 매핑 — 데이터 재생성 후 연동 시 추가 예정.
- **`json_sink.rs` / `parquet_sink.rs`**: csv_sink만 수정. 다른 sink는 필요 시 별도.
- **Stride 학습-추론 일치 권장**: 플랜 단계에서 **채택 안 함** 결정. stride는 윈도우 샘플링 간격일 뿐 입력 텐서 분포와 무관 → 학습 stride=4 / 추론 stride=1은 의도된 설계.

### 스코프 내 검증 테스트 (139/139 통과)

| 모듈 | 테스트 수 | 신규 |
|------|---------|------|
| `test_preprocessing/test_data_stats.py` (신규 파일) | 14 | +14 |
| `test_preprocessing/test_model_registry.py` | 14 | +4 (TestDriftMetadata) |
| `test_preprocessing/test_vae_wrapper.py` | 11 | +3 (피처별 오차) |
| `test_detection/test_vae_detector.py` | 29 | +5 (TestExplainability) |
| `test_detection/test_ensemble_detector.py` | 24 | +5 (TestOOF*) |
| `test_detection/test_sequence_detector.py` | 31 | +4 (TestPostingTime) |
| `test_detection/test_supervised_detector.py` | 16 | 0 (회귀만) |
| Rust `datasynth-output::csv_output_integration` | 4 | 0 (회귀만) |

---

## 1. FT-Transformer vs XGBoost — 역할 중복 분석 ⚠️ Ablation 스크립트 준비, 실측 대기 (2026-04-11)

> **해결 상태**:
> - `tools/scripts/ft_ablation_study.py` 신규 (골격 + `--dry-run`)
> - `classify_conclusion(f1_with, f1_without, threshold=0.005)` → "keep"/"remove"/"inconclusive"
> - `write_report()` → `tests/datasynth_quality_gate/results/ft_ablation_report.md`
> - `docs/DECISION.md::D038` — FT-T 유지 + 분기별 ablation 정책 문서화
>
> **잔여**: 실제 학습·평가 (`run_ablation()` 본체) — 데이터 재생성 이후 단계에서 구현

### 1-1. 입출력 동일성: 확인됨

| 비교 항목 | XGBoost (SupervisedDetector) | FT-Transformer (TransformerDetector) |
|----------|------------------------------|--------------------------------------|
| 전처리기 | `_build_supervised_preprocessor(groups)` | **동일** |
| 입력 차원 | 42 (18 피처 + 24 룰) | **동일** |
| 출력 | `predict_proba()[:, 1]` → 0~1 | **동일** |
| threshold | F1-macro 최대화 | **동일** |
| 결과 형식 | `DetectionResult.scores` | **동일** |

### 1-2. 그러나 아키텍처는 근본적으로 다름

| 측면 | XGBoost | FT-Transformer |
|------|---------|-----------------|
| 학습 원리 | Greedy top-down 트리 분기 | Self-attention 병렬 피처 상호작용 |
| 피처 상호작용 | 순차적 분기 노드에서 암묵적 | Multi-head attention으로 **모든 피처 쌍** 명시적 |
| 피처 처리 | 원본 스케일 그대로 | 각 피처를 d_token=64 벡터로 토큰화 |
| 파라미터 | 트리 분할 수백~수천개 | ~53,000개 (FC + Transformer 2층) |

### 1-3. 판정: **과도하지만 해롭지는 않음**

**과도한 이유:**
- 42차원에서 XGBoost의 피처 상호작용 학습 능력은 충분함
- 합성 데이터 순환 학습 환경에서 FT-Transformer의 추가 가치를 실증할 방법 없음
- 파라미터 53K → XGBoost보다 과적합 위험 높음 (합성 데이터에서 더 심각)

**해롭지 않은 이유:**
- VRAM ~300MB로 하드웨어 부담 미미
- Stacking Meta-learner가 Ridge(positive=True)로 가중치 자동 조절 → 기여도 낮으면 계수 0에 수렴
- Fallback 가중치: XGBoost 0.12, FT-Transformer 0.10 → 이미 낮게 설정됨
- 이미 구현 완료(✅)이므로 제거 비용 > 유지 비용

**권장: 유지하되, ablation study 1건 추가**
- Stacking에서 FT-Transformer 열을 제거한 7-model vs 8-model 성능 비교
- 유의미한 차이 없으면 Phase 3에서 제거 검토

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 타당한 분석**
>
> `src/preprocessing/stacking.py:57-62` 에서 `Ridge(positive=True)` 확인됨. 기여도 낮은 모델은 계수가 0에 수렴하므로 "유지하되 ablation" 결론은 합리적.
>
> **보조 발견**: FT-Transformer와 XGBoost가 **동일한 전처리기**(`build_supervised_preprocessor`)를 공유하는 구조 자체는 코드 재사용 측면에서 건전함. 문제는 아키텍처 중복이 아니라 "동일 입력·동일 출력·동일 전처리"에서 self-attention 이점이 42차원에서 체감되기 어렵다는 것. 결론 동의.

---

## 2. BiLSTM+Attention — 시퀀스 의미성 분석 ⚠️ 코드 준비 완료, 데이터 재생성 대기 (2026-04-11)

> **추가 해결 (오후 세션)**: `BiLSTMClassifier.get_attention_weights()` public API 노출.
> `AuditBiLSTM.forward()`가 이미 저장하던 `_attn_weights`를 `(n_windows, seq_len)` 형태로
> 외부 접근 가능하게 함. 각 행 softmax 합 ≈ 1, 마스킹 위치 = 0 검증.
> → ISA 240 "16-step 윈도우 중 어느 시점에 집중" 설명 가능.

> **해결 상태 (코드 경로만)**:
> - **Rust**: `csv_sink.rs` 헤더에 `posting_time` 컬럼 추가. `item.header.created_at.format("%H:%M:%S")`로 출력. `cargo test -p datasynth-output --test csv_output_integration` 4/4 통과.
> - **Python 스키마**: `src/db/schema.py::general_ledger`에 `posting_time TIME` + `GENERAL_LEDGER_COLUMNS` 추가.
> - **Python 탐지기**: `sequence_detector.py::_build_timestamps()` 헬퍼 추가 — `posting_date + to_timedelta(posting_time)` 조합으로 결정론적 시:분:초 타임스탬프. `posting_time` 컬럼 부재 시 기존 동작(date only) fallback.
> - 단위 테스트: `TestPostingTime` 4개 — build_timestamps 동작, 결측 처리, 같은 날 역순 입력 정렬 검증.
>
> **⚠️ 미수행 (다음 단계)**:
> - `cargo build --release` 로 `datasynth-data` 바이너리 재빌드
> - `datasynth-data generate --config ... --output data/synthetic` 로 CSV 재생성
> - `src/db/loader.py`에 `posting_time` 컬럼 파싱 매핑 (현재는 schema 선언만 됨)
> - DataSynth `temporal_patterns.intraday` 프로파일 활성화 검증 (`morning_spike` / `lunch_dip` / `eod_rush`)
>
> **채택 안 함**:
> - Stride 학습-추론 일치 권장 — stride는 윈도우 샘플링 간격일 뿐 입력 텐서 분포와 무관. 학습 stride=4(메모리·속도) / 추론 stride=1(전수 커버리지)는 의도된 설계.

### 2-1. 시퀀스 구성의 현재 구현

```
sequence_builder.py:
  user_ids(created_by) 그룹별 → posting_date argsort(stable) →
  seq_len=16 슬라이딩 윈도우(stride=1 추론, stride=4 학습)
```

### 2-2. 문제점 3가지

**문제 1: Tie-break 불완전**
- 같은 날짜의 거래는 `kind="stable"` (원본 위치 순서)로만 정렬
- document_id나 created_time(시:분:초)이 반영되지 않음
- 동일 사용자가 같은 날 5건 전표 처리 시 → 순서가 무의미

**문제 2: 회계 데이터의 순서 본질**
- 회계 전표는 연속 신호(ECG, 음성)가 아닌 **이산 사건(Discrete Events)**
- 같은 날 수백 건 배치 처리 → ERP 시스템의 입력 순서 ≠ 부정 의도 순서
- `posting_date` 기준 일 단위 정렬만으로는 "경영진 override 반복 패턴"을 16-step 윈도우에서 포착하기 어려움

**문제 3: 학습-추론 불일치**
- 학습: stride=4 (설정값)
- 추론: stride=1 (고정, sequence_detector.py:167)
- 추론 시 겹치는 윈도우가 더 많아 → 학습 분포와 다른 입력 분포

### 2-3. 그러나 아키텍처 자체는 건전

- Additive Attention + mask → padding 정확히 처리
- BiLSTM 양방향 → 시퀀스 문맥 양쪽 포착
- ~53K 파라미터, VRAM ~100MB → 경량

### 2-4. 판정: **개념은 건전하나, 회계 데이터에서 효과 의문**

**시퀀스 기반 탐지가 의미 있는 시나리오:**
- 같은 사용자가 짧은 기간에 비슷한 금액 반복 입력 (ISA 240 override)
- 근무 외 시간에 연속 전표 입력 후 즉시 승인

**현재 구현으로 포착 어려운 이유:**
- 일 단위 정렬로는 "30분 내 3건 연속 입력" 패턴을 시퀀스로 구성 불가
- **시:분:초 타임스탬프가 있어야 의미 있는 시퀀스 구성 가능**

**권장:**
1. created_time(시:분:초) 컬럼 존재 여부 확인 → 있으면 tie-break에 추가
2. seq_len=16이 ISA 240 패턴에 적절한지 도메인 검증 (감사 사례 연구)
3. stride 학습-추론 일치시키기 (둘 다 stride=1로 통일 권장)

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ⚠️ 부분 타당 + ❌ 과장 1건**
>
> #### 2-1 (Tie-break 불완전) — ⚠️ 조건부 타당
>
> `src/preprocessing/sequence_builder.py:68-69`:
> ```python
> sort_order = np.argsort(ts_values, kind="stable")
> ```
>
> `src/detection/sequence_detector.py:71`:
> ```python
> timestamps = pd.to_datetime(X[_SEQ_TIME_COL]).values
> ```
>
> **핵심**: `posting_date` 원본이 **"2026-04-10"(날짜만)** 이면 같은 날 거래는 원본 위치로만 tie-break → 지적 맞음. **반대로 "2026-04-10 14:35:22"(타임스탬프)** 면 시:분:초가 실제 반영됨 → 지적 과장.
>
> → **확인 필요**: DataSynth의 `posting_date` 컬럼 dtype. 스키마상 `date`로 정의되어 있어 날짜만일 가능성 높음. `created_time` 별도 컬럼을 생성하거나 `posting_date`를 datetime으로 업그레이드하는 결정 필요.
>
> #### 2-2 (학습-추론 stride 불일치) — ❌ 과장 (ML 상식 오해)
>
> **문서 주장**: "추론 시 겹치는 윈도우가 더 많아 → 학습 분포와 다른 입력 분포"
>
> **실제 코드 분석** (`sequence_detector.py:181-186`):
> ```python
> # 동일 행이 여러 윈도우의 마지막 항목일 수 있음 → 최대 확률 사용
> for window_idx, pos_idx in enumerate(seq_result.original_indices):
>     actual_df_idx = df_index_array[pos_idx]
>     current = scores_full.at[actual_df_idx]
>     scores_full.at[actual_df_idx] = max(current, proba[window_idx])
> ```
>
> **왜 과장인가**:
> - `stride`는 **윈도우 샘플링 간격**일 뿐, 개별 윈도우 입력 텐서의 분포(shape=(16, n_features))는 학습/추론 동일
> - BiLSTM 모델 입장에선 "16-step 윈도우 1개"를 입력받는 것은 학습/추론 동일
> - 추론 stride=1은 **의도된 설계** — 모든 행을 최소 1회 마지막 항목으로 평가 (전수 커버리지 보장)
> - `max` 집계로 중복 윈도우 처리까지 완비
>
> → **stride=1 통일 권장은 불필요**. 오히려 학습 stride=4가 메모리·속도 절약 이점 있음. 이 권장사항은 채택하지 않아야 함.
>
> #### 보조 발견: 성능 버그
>
> `sequence_detector.py:185` 의 `pd.Series.at[]` 루프는 100만 행에서 매우 느림. `np.maximum.at()` 또는 groupby 벡터화로 개선 가능. 문서가 놓친 실제 성능 이슈.

---

## 3. 6-model Stacking — 순환 학습 위험 (가장 심각) ✅ 해결 (2026-04-11)

> **해결 상태**: `ensemble_detector.py::train_oof()` 구현.
> - `GroupKFold(n_splits=3, groups=user_ids)` — user-leakage 방어
> - `joblib.Parallel(n_jobs=-1, backend="loky")` — fold 병렬 학습
> - leakage-prone 트랙(ML_SUPERVISED/ML_TRANSFORMER/ML_SEQUENCE)만 fold마다 재학습
> - 룰 4종 + VAE는 `non_leakage_results`로 한 번만 실행
> - 라벨 부족(<stacking_min_positive) 시 기존 `train_from_results` fallback 유지
> - `settings.stacking_cv_folds`로 노출 → Phase 3 안정화 후 5로 승격 가능
> - User-leakage 차단 단위 테스트: `set(users[train]) ∩ set(users[val]) == ∅` 직접 검증
> - 참고: 3-fold 선택 근거는 `docs/debugging.md` 2026-04-11 섹션.

### 3-1. 순환 학습 전파 경로

```
DataSynth 합성 라벨 (is_fraud)
    ↓
label_strategy.create_labels() → y (0/1)
    ↓
┌─────────────────────────────────────────────┐
│ ML_SUPERVISED (XGBoost)    ← y로 학습       │
│ ML_TRANSFORMER (FT-T)      ← 동일 y로 학습  │
│ ML_SEQUENCE (BiLSTM)       ← 동일 y로 학습  │
│ ML_UNSUPERVISED (VAE+IF)   ← y 미사용 ✅    │
│ 룰 4개 (A/B/C/Benford)     ← y 미사용 ✅    │
└─────────────────────────────────────────────┘
    ↓ 8개 모델의 predict 결과 (score_matrix)
    ↓
StackingEnsemble.fit(score_matrix, y)  ← **동일한 y로 다시 학습**
    ↓
⚠️ 순환: y → 3개 ML → scores → Meta-Learner ← y
```

### 3-2. 현재 방어 메커니즘의 한계

| 방어 | 현황 | 효과 |
|------|------|------|
| Fallback 모드 | 라벨 < 50건 시 Percentile Ranking | ✅ 라벨 부족만 대응 |
| Ridge(positive=True) | 음수 가중치 제거 | ⚠️ 순환 구조 자체는 차단 못함 |
| OOF 5-fold | **미구현** | ❌ TASKS.md에 "5-fold out-of-fold prediction 프로토콜" 명시했으나 실제 코드 부재 |
| Train/Test 분리 | Base model은 전체 df로 추론 → 동일 데이터 | ❌ |

### 3-3. OOF 프로토콜 미구현 증거

TASKS.md WU-03에 명시:
> **Leakage 방지**: 5-fold out-of-fold prediction 프로토콜

실제 코드 (`src/detection/ensemble_detector.py`):
```python
def train_from_results(self, results, y, df_index):
    """Why: 완전 OOF가 아닌 간소화 경로. base model이 이미 전체 데이터에
             대해 실행된 상태이므로 약간의 leakage 가능하나..."""
    score_matrix = self._build_score_matrix(results, df_index)
    self._meta.fit(score_matrix, y)  # 전체 데이터, 동일 라벨
```

**문서와 구현이 불일치** — OOF가 설계에는 있지만 코드에는 없음.

### 3-4. 실제 위험 시나리오

**Pseudo Labeling 순환 시:**
1. 룰 스코어 → threshold(0.5) → pseudo label
2. ML 3개 모델이 pseudo label 학습 → 결과: 룰 스코어와 높은 상관관계
3. Meta-Learner가 "ML 모델들의 합의" 학습 = 사실상 "룰 스코어 재현"
4. **새로운 신호 추출 불가** — ML이 추가된 의미 없음

**DataSynth GT 사용 시:**
1. DataSynth의 is_fraud는 룰 기반 주입 (TS-3 문제)
2. ML 모델이 "룰로 주입된 패턴" 재학습
3. Meta-Learner가 "룰 재현 모델들의 합의" 학습
4. 동일 문제

### 3-5. 판정: **설계 의도(OOF)와 구현 괴리, 순환 방어 불충분**

**그러나 실질적 영향은 제한적:**
- Fallback 모드가 라벨 부족 시 Percentile Ranking으로 전환
- 실무 데이터에는 라벨이 없으므로 → **거의 항상 Fallback 모드 작동**
- 즉, 순환 학습은 "DataSynth 검증 환경에서만" 문제
- 실전에서는 Percentile Ranking 가중합이 작동

**권장 (우선순위순):**
1. **OOF 구현**: ensemble_detector에 K-Fold CV 기반 OOF 프로토콜 추가 (문서와 코드 일치)
2. **비지도 모델 가중치 강화**: ML_UNSUPERVISED(VAE+IF)에 더 높은 가중치 → 순환 무관 모델 우선
3. **문서 정정**: "5-fold OOF" → 현재는 "간소화 경로, 향후 OOF 구현 예정"으로 명시

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 가장 정확한 지적. 실제 버그 확정.**
>
> `src/detection/ensemble_detector.py:127-161` **코드 자체가 OOF 미구현을 명시적으로 인정**:
> ```python
> def train_from_results(self, results, y, df_index):
>     """Why: 완전 OOF가 아닌 간소화 경로. base model이 이미 전체 데이터에
>              대해 실행된 상태이므로 약간의 leakage 가능하나, 실무에서는
>              라벨 수가 제한적일 때 이 경로를 사용한다."""
>     ...
>     score_matrix = self._build_score_matrix(results, df_index)
>     ...
>     self._meta.fit(score_matrix, y)  # 전체 데이터, 동일 y로 학습
> ```
>
> - K-Fold 로직 자체가 없음 (grep으로 `KFold`, `cross_val_predict` 검색 결과 0)
> - 문서(`docs/pre-plan/05a-detection-ml.md`, `TASKS.md`)에는 "5-fold OOF prediction" 명시
> - **문서-코드 괴리 확정**
>
> **Leakage 경로 구분** (실제 영향도 분석):
> - ✅ **Leakage 있음**: `ML_SUPERVISED`, `ML_TRANSFORMER`, `ML_SEQUENCE` (3개 모델) — `y`로 학습 후 동일 데이터 predict → meta-learner가 훈련 정확도 기반 과적합
> - ✅ **Leakage 없음**: `ML_UNSUPERVISED` (VAE+IF), 룰 4개 (L1/B/C/Benford) — `y` 미사용
>
> **실무 피해 추정**:
> - 검증 환경(DataSynth GT 사용)에서 **validation F1이 허위로 높게 나옴** → 모델 성능 비교 판단 왜곡
> - 실전(라벨 <50건) → fallback 모드 자동 전환되어 Percentile Ranking 사용 → leakage 무관
> - 즉, **개발·검증 단계에서만 문제, 실전 투입 시에는 회피됨**
>
> → **P1 우선순위 수정 권장**. 구현 자체는 sklearn `cross_val_predict`로 간단하나, `detect()` 이미 완료된 base model 결과를 재활용하는 현 구조를 깨야 해서 리팩토링 범위가 있음. "문서 정정 먼저 + OOF는 다음 스프린트"가 현실적.
>
> **추가 권장**: 문서 권장사항 #2(비지도 가중치 강화)는 이미 `LAYER_WEIGHTS_WITH_ML`에서 `ML_UNSUPERVISED: 0.17 > ML_SUPERVISED: 0.15` 로 반영되어 있음 (`constants.py:178-185`). 중복 권장사항.

---

## 4. 누락된 기술 심층 분석

> 초기 요약에서 "모델 설명력: XGBoost SHAP만 대상"이라고 기술했으나, 실제 코드 조사 결과 `src/preprocessing/explainer.py`와 `dashboard/components/shap_waterfall.py`가 이미 구현되어 있음을 확인. 아래는 정정된 정밀 분석.

### 4-1. 모델 설명력 (Explainability) — ✅ **전부 해결** (2026-04-11 오후)

> **VAE 분해 (오전)**:
> - `vae_wrapper.py::score_samples_per_feature(X) → (N, D)` 신규 public API
> - `vae_detector.py::detect()`가 `details`에 `ML02_top_feature_{1..3}` + `_contrib` 첨부
> - `np.argpartition`으로 O(N·D) Top-K 선택 (정렬 비용 없음)
> - ColumnTransformer `get_feature_names_out()`으로 피처명 자동 추출
>
> **BiLSTM Attention 노출 (오후)**:
> - `BiLSTMClassifier.get_attention_weights(X, mask) → (n_windows, seq_len)` 신규 public API
> - `AuditBiLSTM.forward()`의 기존 `_attn_weights` 저장을 활용 — 모델 구조 변경 없음
>
> **FT-Transformer Attention 추출 (오후)**:
> - `AuditFTTransformer.forward_with_attention(x) → (logits, List[attn])` 신규
> - `nn.TransformerEncoder` fast-path 우회 — 각 layer의 `self_attn`을 수동 호출하여
>   `need_weights=True, average_attn_weights=True`로 head 평균 추출
> - `FTTransformerClassifier.get_attention_weights(X) → (n_samples, n_features)`:
>   layer 평균 후 `[CLS]` 행의 피처 토큰 부분 `[:, 0, 1:]` 추출
>
> **감사 증거 템플릿 (오후)**:
> - `src/export/audit_evidence.py` 신규
> - `RULE_LEGAL_BASIS` dict — 룰 ID → ISA/PCAOB/K-IFRS 근거 매핑
> - `build_evidence_row(row, top_feature_k=3)` → `AuditEvidence` dataclass
> - `format_narrative(...)` → "전표 D001은 위험도 'High' (anomaly_score=0.85)로 분류...
>   위반 룰: L3-04(기말 대규모) [ISA 240 §32]... VAE 재구성 오차 주요 기여 피처: amount(0.43)..."
>
> **VAE Waterfall UI (오후)**:
> - `dashboard/components/shap_waterfall.py::render_vae_waterfall(row, top_k=3)` 신규
> - P0-1의 `ML02_top_feature_*` 컬럼 직접 소비
> - SHAP과 달리 양수 전용 Waterfall (MSE는 항상 ≥ 0)

#### 현재 구현 상태: **부분**

| 구성요소 | 상태 | 파일 |
|---------|------|------|
| SHAP 계산 엔진 | ✅ 구현 | `src/preprocessing/explainer.py` — `PipelineExplainer.explain_batch()` |
| SHAP Waterfall UI | ✅ 구현 | `dashboard/components/shap_waterfall.py` |
| 파이프라인 오케스트레이션 | ✅ 구현 | `src/pipeline.py:688-710` — `_try_shap_explanation()` (flagged rows만) |
| **VAE 재구성 오차 분해** | ❌ 없음 | `src/detection/vae_detector.py:178-186` — MSE 전체만 반환 |
| **BiLSTM Attention 추출** | ❌ 버려짐 | `src/preprocessing/bilstm_model.py:104` — `self._attn_weights` 저장만 하고 forward 후 폐기 |
| **FT-Transformer Attention 추출** | ❌ 없음 | Multi-head attention 가중치 미추출 |
| **트리 모델 feature_importances_** | ❌ 없음 | `src/detection/supervised_detector.py`의 최적 모델이 RF/XGB인 경우에도 미사용 |

#### 구체적 증거

**BiLSTM Attention 폐기 (`bilstm_model.py:104`)**
```python
context, self._attn_weights = self.attention(lstm_out, mask)
# _attn_weights 저장되지만 forward 호출 후 외부 접근 경로 없음
```

**VAE 피처별 오차 미분해 (`vae_detector.py`)**
```python
def _score_vae(self, df):
    """VAE 파이프라인의 raw 재구성 오차(MSE) 반환."""
    # 전체 MSE만 반환 → 어느 피처가 재구성 실패했는지 알 수 없음
```

#### 누락의 정확한 범위

1. **지도학습(XGBoost/RF/LGBM/FT-T/BiLSTM) 설명**: SHAP 엔진은 있지만, flagged rows에 대해서만 계산되고 **그마저도 지도학습 모델 한정**. FT-Transformer와 BiLSTM은 SHAP KernelExplainer로 가능하나 현재 미연결
2. **비지도학습(VAE+IF) 설명**: 감사에서 가장 많이 사용되는 "미지 패턴 탐지"인데 **설명 로직 0건**
3. **감사 증거 구조화**: SHAP top-5 피처 기여도만 있음. "왜 이 전표가 ISA 240 위반 가능성인지"를 감사보고서 문구로 생성하는 로직 없음

#### 실무 영향도: 🔴 **심각 (Tier 1)**

- 감사인이 "이상 의심" 전표를 감사조서에 기록할 때 **정량적 근거 필수**
- ISA 240 "부정 위험 대응" 문서 작성 시, "시스템 판단"만으로는 감사 절차 미충족
- VAE가 핵심 탐지기(WU-02)인데 설명 없음 → 탐지 결과를 감사 증거로 채택하기 어려움

#### 권장 조치

1. **VAE 피처별 기여도 분해**: `recon_error_per_feature = (x - x_hat)**2` 반환 추가 → Top-K 피처 Waterfall
2. **BiLSTM Attention 노출**: `get_attention_weights()` 메서드 추가 → 시퀀스 타임스텝별 중요도 히트맵
3. **FT-T Multi-head Attention 추출**: `encoder.layers[i].self_attn` hook 등록 → 피처 상호작용 행렬
4. **감사 증거 템플릿**: 탐지 룰 ID + 기여 피처 + 실증 근거 → 감사조서 문구 자동 생성

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 정확하고 가장 심각한 실무 공백**
>
> #### VAE 재구성 오차 분해 (P0)
>
> `src/detection/vae_detector.py:178-186` 확인:
> ```python
> def _score_vae(self, df: pd.DataFrame) -> np.ndarray:
>     """VAE 파이프라인의 raw 재구성 오차(MSE) 반환."""
>     preprocessor = self.vae_pipeline_[:-1]
>     X_transformed = np.array(preprocessor.transform(df), dtype=np.float32)
>     vae = self.vae_pipeline_.named_steps["detector"]
>     return vae.score_samples(X_transformed)
> ```
>
> → 전체 MSE 스칼라만 반환. 피처별 `(x_i - x_hat_i)**2` 분해 없음.
>
> **왜 가장 심각한가**:
> - VAE+IF는 **실전 주력 탐지기** — 라벨 없는 고객사에서 거의 유일한 ML 탐지 수단
> - 규칙 24개는 설명이 **룰 이름·근거 법규로 내재** ("L3-04: 기말 대규모 전표", ISA 240 §32)
> - 지도학습 모델은 `dashboard/components/shap_waterfall.py`로 설명 가능
> - **주력 탐지기만 설명 0건** — 역설적 구조
>
> **감사 도메인에서의 영향**:
> - 감사인이 VAE 플래그를 감사조서에 기재하려면 "왜 이상인지" 근거 필수
> - ISA 240 §33 "부정 위험 대응 절차"에서 **정량적 증거** 요구
> - 현재 구조로는 "시스템이 이상이라 했음" 이외 설명 불가 → **감사 증거로 채택 불가**
>
> **수정 비용**: 매우 낮음. VAE forward에서 이미 `recon`과 `x` 모두 계산하므로 `(x - recon)**2` 를 피처별로 반환하는 메서드 추가는 10줄 이내.
>
> → **P0 확정. Phase 2 완료 선언 전 필수 수정.**
>
> #### BiLSTM Attention 폐기 (P1)
>
> `src/preprocessing/bilstm_model.py:104` 확인:
> ```python
> context, self._attn_weights = self.attention(lstm_out, mask)
> ```
>
> Grep 결과: `get_attention_weights`, `attention_weights` 공식 API 없음.
>
> - **기술적으로는** `model._attn_weights`로 직접 접근 가능 (Python private convention일 뿐)
> - **공식 API가 없어 용도 불명확** — `sequence_detector`가 이 값을 사용하는 코드 경로 0건
> - **문서 지적 정확**. 그러나 "폐기"는 약간 과장 — "API 미제공으로 사용 불가 상태"가 정확
>
> → P1 우선순위 동의. `BiLSTMClassifier.get_attention_weights()` 메서드 추가는 S급 작업.
>
> #### 지도학습 SHAP 범위
>
> 문서 주장 "XGB/RF/LGBM에만 SHAP, FT-T/BiLSTM은 KernelExplainer 가능하나 미연결" — 코드 확인. `explainer.py:25-33`:
> ```python
> def _resolve_model_type(self) -> str:
>     cls_name = type(model).__name__.lower()
>     if "xgb" in cls_name: return "tree"
>     if "forest" in cls_name: return "tree"
>     return "kernel"  # ← 이 분기로 들어가긴 함
> ```
>
> → 실제로는 **KernelExplainer 분기가 존재**하므로 FT-T/BiLSTM도 **원칙적으로 SHAP 가능**. 단 pipeline.py에서 실제 호출 여부 별도 확인 필요. 문서가 약간 과장.

---

### 4-2. 추론 시간 예산 (Inference Latency) — ✅ **해결** (2026-04-11 오후)

> **해결 상태**:
> - `pipeline.py::_run_detectors_parallel(detectors, df, max_workers, progress_callback)` 신규
>   - ThreadPoolExecutor — pandas/numpy GIL 해제 활용
>   - `max_workers=None|1`이면 순차 (테스트/디버깅 모드)
>   - 결과 순서는 입력 `detectors` 순서로 정렬 (병렬 완료 순 아님) → downstream 안전
>   - per-detector `try/except` 격리 + progress_callback 예외 격리
> - `_run_detection()`의 base 6개 탐지기 루프가 자동으로 병렬 헬퍼 사용
> - `collect_detection_profile(results)` + `format_detection_profile(profile)` 신규
>   — 탐지기별 `metadata["elapsed"]` 집계 + 마크다운 표 포맷
> - `settings.detection_parallel_workers=4` 기본값, 테스트에서는 `None`으로 순차 강제
> - 검증: 3개 × 0.1초 sleep 탐지기 → 순차 0.3초 vs 병렬 ≤ 0.15초 (2배 단축)
>
> **잔여**: ML 4개 모델(`_try_ml_detection`) 병렬화, 탐지기별 progress bar UI는 다음 스프린트

#### 현재 구현 상태: **순차 실행**

**`src/pipeline.py:344-396` — 탐지 오케스트레이션**
```python
def _run_detection(self, df) -> tuple[list[DetectionResult], list[str]]:
    results = []
    for det in [IntegrityDetector(...), FraudLayer(...), AnomalyDetector(...),
                BenfordDetector(...), DuplicateDetector(...), IntercompanyMatcher(...)]:
        try:
            results.append(det.detect(df))  # 순차 실행, 하나 끝날 때까지 대기
        except Exception:
            logger.warning(...)
```

**ML 탐지기도 순차 (`pipeline.py:629-652`)**
```python
# Supervised (ML01) — 끝날 때까지 대기
det = SupervisedDetector(...).load_model("supervised")
results.append(det.detect(df))

# Unsupervised (ML02) — Supervised 완료 후 시작
det = UnsupervisedDetector(...).load_model("unsupervised")
results.append(det.detect(df))
```

#### 누락의 정확한 범위

| 항목 | 현재 | 누락 |
|------|------|------|
| 병렬 라이브러리 | 0건 | `concurrent.futures`, `joblib.Parallel` 미사용 |
| 계층 병렬화 | 없음 | L1/B/C/Benford/Duplicate/IC는 서로 독립적인데 순차 실행 |
| ML 병렬화 | 없음 | Supervised/Unsupervised/Transformer/Sequence 4개 모델 순차 로드+추론 |
| 진행률 상세도 | 낮음 | `st.progress(0.65, "탐지 룰 실행 중...")` — 6개 탐지기 중 어디에 있는지 모름 |

#### 예상 개선 효과

100만 행 기준 추정:
- **현재 순차**: 룰 6개(~20s) + ML 4개(~40s) ≈ **60초**
- **ThreadPoolExecutor 4-worker**: max(룰)(~5s) + max(ML)(~15s) ≈ **20초** (3배 단축)

#### 실무 영향도: 🟡 **중요 (Tier 2)**

- UX: 100만 행 분석 시 3~5분 → Streamlit 무한 대기 → 감사인 이탈
- 재탐지 반복: 임계값 튜닝할 때마다 전체 재실행 → 생산성 저하
- 확장성: 다수 고객사 병렬 처리 시 병목

#### 권장 조치

1. **ThreadPoolExecutor 도입**: 독립 탐지기 병렬 실행 (I/O bound는 Thread, CPU bound는 Process)
2. **상세 진행률**: `_run_detection()` 내부에서 탐지기별 콜백 호출 → `st.progress` 세분화
3. **캐시**: 동일 입력에 대한 재탐지는 `@st.cache_data` 활용

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 순차 실행은 정확, 성능 추정치는 검증 필요**
>
> `src/pipeline.py:344-366` 확인:
> ```python
> for det in [
>     IntegrityDetector(...),
>     FraudLayer(...),
>     AnomalyDetector(...),
>     BenfordDetector(...),
>     DuplicateDetector(...),
>     IntercompanyMatcher(...),
> ]:
>     results.append(det.detect(df))  # 확실한 순차
> ```
>
> → `concurrent.futures` 0건 사용 확인.
>
> #### 그러나 "3배 단축(60→20초)" 추정은 근거 부족
>
> **병렬화 이득을 제한하는 요소들**:
> 1. **pandas/numpy 내부 병렬화**: 많은 탐지기가 이미 vectorized pandas 연산 사용 → BLAS/MKL 수준에서 이미 다중 코어 활용 중. ThreadPoolExecutor는 Python GIL에 묶여 추가 이득 거의 없을 수 있음
> 2. **ProcessPoolExecutor 대안**: GIL 회피 가능하나 DataFrame 직렬화 비용(pickle)이 100만 행에서 수 초 발생 → 작은 탐지기는 오히려 느려짐
> 3. **탐지기 간 실행 시간 편차**: 가장 느린 탐지기가 병목 → Amdahl's law로 3배 단축은 모든 탐지기가 비슷한 시간일 때만 성립
>
> **선행 작업 필요**:
> - 100만 행 기준 **각 탐지기별 실제 실행 시간 프로파일링** (cProfile 또는 `metadata["elapsed"]` 수집)
> - 프로파일 결과 없이 병렬화부터 착수하면 최적화 방향 오판 가능성
>
> → **병렬화 자체는 타당한 개선**, 그러나 **P2 이전에 프로파일링 1회 필수**. "3배 단축" 추정은 근거 없는 과장.
>
> #### 보조 발견
>
> `pipeline.py` 의 ML 탐지 시도(`_try_ml_detection`)도 순차 추정. 4개 ML 모델(Supervised/Unsupervised/Transformer/Sequence) 순차 로드+추론 시 joblib 로드 비용(~2초 × 4 = 8초)이 상당할 수 있음. **모델 로드는 최초 1회 + 캐싱**이 병렬화보다 먼저 검토할 가치 있음.

---

### 4-3. 모델 드리프트 & 재학습 트리거 — ✅ **해결** (2026-04-11 오후)

> **메타데이터 기반 (오전)**:
> - `src/preprocessing/data_stats.py` — `compute_training_stats` / `compute_class_imbalance` / `compute_feature_schema_version`
> - `ModelMetadata`에 `training_data_stats` / `feature_schema_version` / `class_imbalance_ratio` / `n_train_samples` 4개 필드
> - 모든 detector `train()`이 학습 시점 분포를 `self._train_stats`로 보존 → `save_model()`이 registry로 전달
> - `list_models()`는 구버전 `registry.json` 하위호환 로드
>
> **PSI 계산 + 배너 + 정책 (오후)**:
> - `src/preprocessing/drift_detector.py` 신규
>   - `compute_psi_numeric(mean, std, current_values)` — 가우시안 10-bin
>   - `compute_psi_categorical(top_categories, current_values)` — Top-N + `_OTHER_` 버킷
>   - `compute_drift_report(model_metadata, current_df) → DriftReport`
>   - 임계값: `DRIFT_THRESHOLD_WARN=0.10`, `DRIFT_THRESHOLD_CRITICAL=0.25`
> - `dashboard/components/drift_banner.py` 신규
>   - 4단계 상태 — critical(🚨) / warn(⚠️) / stable(✅) / skip
>   - `st.expander` 로 드리프트 상세 DataFrame
> - `docs/DECISION.md::D037` — SOC 2 / ISO 27001 대응 재학습 정책
>   - 자동 트리거 (PSI ≥ 0.25) + 주기 트리거 (분기별) + 모니터링 트리거 (0.1 ≤ PSI < 0.25)
>
> **잔여**: 재학습 워크플로우 자동화 스크립트 (`retrain_all_models.py` — Phase 3)

#### 현재 구현 상태: **없음** (버전 관리만 존재)

**`src/preprocessing/model_registry.py:25-130` — 버전 관리만**
```python
@dataclass
class ModelMetadata:
    model_name: str
    version: int
    file_path: str
    mean_f1: float              # F1 스코어만 기록
    feature_count: int = 0
    params: dict = field(default_factory=dict)
    saved_at: str = ""          # 학습 시점만 기록
    # training_data_stats ← 없음
    # feature_schema_version ← 없음
    # class_imbalance_ratio ← 없음
```

**`src/context.py:39-72` — CompanyContext에 drift 필드 0개**

#### 누락의 정확한 범위

| 항목 | 현재 | 누락 |
|------|------|------|
| 데이터 분포 메타 | 없음 | 학습 시점 수치 컬럼 mean/std/min/max, 범주형 분포 미저장 |
| PSI (Population Stability Index) | 없음 | 분포 이동 정량화 지표 미계산 |
| KS-test | Benford 전용 | `validation/benford.py`에만 사용, 전역 드리프트 감지 없음 |
| 재학습 트리거 | 없음 | PSI > 0.25 자동 재학습 / 주기적 재학습 / 성능 저하 경고 모두 없음 |
| 대시보드 경고 | 없음 | "모델이 오래되었습니다" 표시 없음 |

#### 실무 영향도: 🔴 **심각 (Tier 1)**

감사 데이터는 시간에 따라 **큰 변화** 발생:
- 신규 자회사 인수 → 거래 유형 변화
- 회계 정책 변경 → 계정 구조 변경
- 내부통제 강화 → 부정 패턴 변화
- ERP 시스템 업그레이드 → 컬럼 스키마 변경

**Risk**:
- 낡은 모델이 현재 정상 거래를 오탐 → 감사 효율성 저하
- 새로운 부정 패턴을 모델이 놓침 → 감사 리스크
- 규정 감시: "모델 재학습 계획" 문서화 불가 → SOC 2 / ISO 27001 부적합

#### 권장 조치 (우선순위)

1. **MVP 단계**: ModelMetadata에 `training_data_stats` 필드 추가 (mean/std/nunique)
2. **Phase 2 완료 전**: PSI 계산 유틸 구현 (`src/preprocessing/drift_detector.py`)
3. **Phase 3**: 대시보드에 드리프트 경고 배너 추가 + 재학습 워크플로우
4. **문서화**: "재학습 주기는 분기별 또는 PSI > 0.25 시" 정책 docs에 명시

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 정확. Phase 2 완료 전 반드시 해결해야 하는 P0 공백**
>
> `src/preprocessing/model_registry.py:25-35` 확인:
> ```python
> @dataclass
> class ModelMetadata:
>     model_name: str
>     version: int
>     file_path: str
>     mean_f1: float
>     feature_count: int = 0
>     params: dict = field(default_factory=dict)
>     saved_at: str = ""
> ```
>
> → `training_data_stats`, `feature_schema_version`, `class_imbalance_ratio`, `psi_*` 모두 부재. PSI 계산 유틸, KS-test 전역 사용, drift trigger 완전 부재. **문서 지적 정확**.
>
> **감사 도메인의 특수성으로 심각도 증폭**:
> - 일반 ML 서비스: 실시간 드리프트 감지, 주간/월간 재학습
> - 감사 실무: **연 1회 감사 사이클** → 1년 전 학습 모델을 그대로 재사용 가능성 높음
> - 1년 동안 발생할 변화:
>   - 신규 자회사 인수 → 거래 유형 변화
>   - 회계 정책 변경 → 계정 구조 변경
>   - 내부통제 강화 → 부정 패턴 변화 (감사인이 의도한 긍정적 변화가 모델에게는 드리프트)
>   - ERP 업그레이드 → 컬럼 스키마 변경
>
> **규정 준수 관점**:
> - SOC 2 / ISO 27001 감사 시 "AI 모델 거버넌스" 항목에 "재학습 정책 문서" 필수
> - 현재 상태로는 감사 산업에 납품할 수 없는 상태
>
> #### 단계별 수정 계획 (문서 권장보다 현실적으로 재정렬)
>
> | 단계 | 작업 | 난이도 | 이유 |
> |------|------|--------|------|
> | **P0 즉시** | `ModelMetadata`에 `training_data_stats` 추가 (mean/std/nunique 딕셔너리) | S | 1시간 내 완료. 메타데이터만 확장. 향후 PSI 계산 기반 데이터 확보 |
> | **P0 즉시** | `feature_schema_version` 필드 추가 (단순 정수) | S | 컬럼 스키마 변경 감지용 |
> | **P1 Phase 2 마감 전** | `drift_detector.py` + PSI 계산 함수 | M | scipy 기반 간단 구현 |
> | **P2 Phase 3** | 대시보드 드리프트 배너 + 재학습 트리거 | M | UI 작업 |
> | **P3** | 정책 문서화 | S | docs/DECISION.md에 추가 |
>
> **누락된 버그 발견**: `src/detection/ensemble_detector.py:177-182` 의 `save_model()`에서 `feature_count`를 전달하지 않아 `ModelMetadata.feature_count=0`으로 저장됨. 드리프트 감지 인프라 구축 시 같이 수정 필요.

---

### 4-4. Calibration (확률 보정) — ⚠️ **분위수 전환 완료, Isotonic 잔여** (2026-04-11 오후)

> **단기 해결**: risk_level 임계값을 절대값 → 분위수 모드로 전환 가능하게 확장.
> - `config/settings.py::risk_classification_mode="absolute"|"quantile"` 신설
> - `classify_risk_level(mode="quantile")` — `scores.rank(method="max", pct=True)`로
>   percentile rank 계산 후 `risk_quantile_high/medium/low`로 분류
> - score=0인 행은 rank가 높아도 NORMAL 보존 (실제 위험 없음)
> - 기본값은 `absolute` (하위호환). 프로젝트 전환은 설정 파일 한 줄 변경으로 가능
>
> **잔여 (우선순위 낮음)**: Stacking Ridge에 Isotonic 후처리, 개별 모델 `CalibratedClassifierCV`
> — Percentile Ranking이 실무적 대체 역할을 하므로 Phase 3 이후 검토

#### 현재 구현 상태: **부분** (Stacking Ridge만)

**`src/preprocessing/stacking.py` — Ridge 선형 결합**
```python
self.meta_ = Ridge(alpha=self.alpha, positive=True, fit_intercept=True)

def predict_proba(self, X):
    raw = self.meta_.predict(X)
    score = np.clip(raw, 0.0, 1.0)  # ← clip만 함, Platt/Isotonic 아님
    return np.column_stack([1 - score, score])
```

**개별 모델은 보정 없음**
- `supervised_detector.py:106`: `proba = self.pipeline_.predict_proba(df)[:, 1]` — 원시 확률
- `tabular_transformer.py:91`: 동일
- `sequence_detector.py:174`: 동일

#### 누락의 정확한 범위

| 항목 | 현재 | 누락 |
|------|------|------|
| `sklearn.calibration.CalibratedClassifierCV` | 미사용 | Sigmoid(Platt)/Isotonic 보정 0건 |
| 개별 모델 보정 | 없음 | XGB/RF/LGBM predict_proba의 실제 정확도와 괴리 가능 |
| Threshold-Aware Calibration | 없음 | risk_level 임계값(0.3/0.5/0.7/0.9)별 보정 없음 |

#### 실무 영향도: 🟡 **중요, 그러나 우선순위 낮음**

**이유**: Percentile Ranking이 사실상 calibration 역할 수행
- score_aggregator에서 Stacking fallback 시 Percentile Ranking 사용
- Percentile은 **분포 자체를 재매핑**하므로 절대 확률은 아니지만 순위는 보존
- 감사 도메인에서는 "절대 확률"보다 "상대 순위"가 더 의미 있음 (Top-N 조사)

**그러나 문제:**
- risk_level 임계값(`NORMAL<0.3, LOW<0.5, MEDIUM<0.7, HIGH<0.9`)은 **절대 확률 가정**
- Stacking Ridge는 계수 합이 1이 아니므로 출력이 실제 확률과 괴리
- 감사인이 "HIGH risk = 90% 확률"로 해석하면 오해

#### 권장 조치

1. **단기**: risk_level 임계값을 **분위수 기반**으로 변경 (상위 10% = HIGH)
2. **중기**: Stacking Ridge에 Isotonic Regression 후처리 추가
3. **장기**: 개별 모델에 `CalibratedClassifierCV(cv=5, method='isotonic')` 래핑

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 정확. 단 우선순위 낮음 판정 동의.**
>
> `src/preprocessing/stacking.py:83-85` 확인:
> ```python
> raw = self.meta_.predict(X)
> score = np.clip(raw, 0.0, 1.0)
> return np.column_stack([1 - score, score])
> ```
>
> → Ridge 출력을 `clip`만 사용. Platt/Isotonic 부재. `supervised_detector.py`, `tabular_transformer.py`, `sequence_detector.py` 모두 `predict_proba` 원시 출력 사용. **문서 지적 정확**.
>
> #### 그러나 실무 피해가 낮은 이유 (문서 판단 동의)
>
> - 감사 도메인에서 "절대 확률 0.87"보다 **"상위 N건 조사"** 가 실무 워크플로우
> - Percentile Ranking이 이미 순위 보존 역할 수행
> - **진짜 문제**는 `risk_level` 임계값(`NORMAL<0.3, LOW<0.5, MEDIUM<0.7, HIGH<0.9`)이 **절대 확률 가정**이라는 점. Ridge 출력은 진짜 확률이 아니므로 "HIGH = 90% 확률" 해석은 오해
>
> #### 권장 수정 순위 (문서 동의)
>
> 1. **단기 (P3)**: risk_level을 분위수 기반으로 변경 — **단순 리팩토링 1시간**
>    - `config/settings.py`에 `risk_quantiles = {high: 0.9, medium: 0.7, low: 0.5}` 추가
>    - `score_aggregator._determine_risk_level()`에서 `np.quantile(scores, q)` 사용
> 2. **중기**: Isotonic 후처리는 **라벨 있을 때만 의미** → 실전 활성화 여부 불확실
> 3. **장기**: 개별 모델 보정도 동일 조건. 우선순위 매우 낮음.
>
> → 단기 수정(분위수 기반)만 즉시 적용하고 나머지는 Phase 3 이후로 연기 가능.

---

## 종합 판정표

### A. 과도한 기술

| 기술 | 과도 여부 | 심각도 | 즉시 조치 필요 | 권장 |
|------|----------|--------|---------------|------|
| FT-Transformer | 약간 과도 | 🟢 낮음 | 아니오 | 유지 + ablation study |
| BiLSTM 시퀀스 | 개념 OK, 효과 의문 | 🟡 중간 | tie-break 개선 | 시:분:초 추가, seq_len 검증 |
| Stacking 순환 학습 | 설계-구현 괴리 | 🔴 높음 | OOF 미구현 정정 | OOF 구현 or 문서 정정 |

### B. 누락된 기술

| 영역 | 상태 | 심각도 | 주요 누락 기술 |
|------|------|--------|---------------|
| Explainability | 부분 구현 | 🔴 심각 | VAE 재구성 분해, BiLSTM/FT-T Attention 추출, 감사 증거 구조화 |
| Inference Latency | 순차 실행 | 🟡 중요 | ThreadPoolExecutor 병렬화, 상세 진행률 |
| Model Drift | 없음 | 🔴 심각 | PSI/KS-test, 데이터 분포 메타, 재학습 트리거 |
| Calibration | Stacking Ridge만 | 🟡 낮음 | 개별 모델 Platt/Isotonic — Percentile Ranking이 대체 |

### 핵심 결론

**과도한 기술 중 가장 시급한 문제**:
- Stacking OOF 미구현 (문서에는 있다고 적혀 있지만 실제 코드에 없음)

**누락된 기술 중 가장 시급한 문제**:
- 비지도 탐지기(VAE+IF) 설명력 부재 — 핵심 탐지기인데 "왜 이상인지" 근거 없음
- 모델 드리프트 감지 인프라 0건 — 감사 규정 준수에 필수

**가장 덜 문제인 것**:
- FT-Transformer 과도성 (해롭지 않고, Stacking이 자동 조절)
- Calibration 누락 (Percentile Ranking이 사실상 대체, risk_level 임계값을 분위수 기반으로 전환하면 해결)

**구조적 한계**:
- 합성 데이터 기반이므로 모든 지도학습 모델의 가치가 제한적 — 이는 TS-3에서 이미 인지한 사항이며, 설계 자체에 반영되어 있음 (비지도 중심 전략)
- 따라서 비지도 탐지기의 설명력 보강이 우선순위 1순위

### 우선순위 액션 아이템

| 우선순위 | 영역 | 작업 | 예상 난이도 |
|---------|------|------|------------|
| P0 | Drift | ModelMetadata에 `training_data_stats` 필드 추가 | S |
| P0 | Explainability | VAE `recon_error_per_feature` 분해 메서드 추가 | M |
| P1 | Stacking | OOF 프로토콜 실제 구현 or 문서 정정 | M |
| P1 | Explainability | BiLSTM `get_attention_weights()` 메서드 노출 | S |
| P2 | Latency | ThreadPoolExecutor로 독립 탐지기 병렬화 | M |
| P2 | BiLSTM | tie-break에 created_time 추가 | S |
| P3 | Calibration | risk_level 임계값을 분위수 기반으로 전환 | S |
| P3 | FT-Transformer | Ablation study 1건 수행 | M |

---

## 참고 파일 경로

| 역할 | 경로 |
|------|------|
| FT-Transformer 탐지기 | `src/detection/tabular_transformer.py` |
| FT-Transformer sklearn 래퍼 | `src/preprocessing/ft_wrapper.py` |
| FT-Transformer PyTorch 모델 | `src/preprocessing/ft_model.py` |
| SupervisedDetector (XGBoost 등) | `src/detection/supervised_detector.py` |
| 공용 전처리기 | `src/preprocessing/pipeline_builder.py` |
| BiLSTM 시퀀스 탐지기 | `src/detection/sequence_detector.py` |
| 시퀀스 빌더 (2D→3D) | `src/preprocessing/sequence_builder.py` |
| BiLSTM PyTorch 모델 | `src/preprocessing/bilstm_model.py` |
| EnsembleDetector (Stacking) | `src/detection/ensemble_detector.py` |
| StackingEnsemble (Ridge) | `src/preprocessing/stacking.py` |
| Stacking 상수 (가중치) | `src/detection/constants.py` |



## gemini 의견
🚨 반드시 당장 고쳐야 하는 치명적 결함 (Must Fix - P0/P1)
이 항목들은 방치할 경우 파이프라인의 존재 이유가 사라지거나, 잘못된 결과를 내뱉는 진짜 버그들입니다.

1. VAE 비지도 학습의 설명력(Explainability) 부재 (가장 심각)

실제 문제인가? 네. 감사 도메인에서 "왜 이게 횡령 의심 전표인가요?"라는 질문에 "AI의 재구성 오차(MSE)가 높다네요"라고 대답하면 아무도 그 시스템을 쓰지 않습니다.

해결책: VAE가 전체 오차만 뱉지 말고, "어떤 피처(예: 금액, 특정 계정)에서 오차가 가장 크게 났는지" 피처별 오차((x - x_hat)**2)를 배열로 반환하도록 반드시 고쳐야 합니다. 코드는 10줄 내외로 수정 가능하지만, 파급력은 시스템 전체의 신뢰도를 좌우합니다.

2. 6-model Stacking의 데이터 누수 (Data Leakage) & 순환 학습

실제 문제인가? 네, 명백한 로직 버그입니다. OOF(Out-of-Fold) 교차 검증 없이 베이스 모델이 학습한 데이터로 메타 모델을 또 학습시키면, 메타 모델은 앙상블의 지혜를 모으는 게 아니라 "가장 훈련 데이터에 과적합(Overfitting)된 모델(예: XGBoost)의 결과만 무지성으로 따라가는" 바보가 됩니다.

해결책: ensemble_detector.py에 cross_val_predict를 도입하여 진정한 OOF 프로토콜을 구현해야 합니다.

3. BiLSTM 시퀀스의 '시간(시:분:초)' 누락

실제 문제인가? 네. 같은 날짜(Day)에 발생한 수십 건의 전표를 시간순(Time) 정렬 없이 그저 원본 엑셀 행 순서대로 16개씩 묶어서 LSTM에 넣는다면, 모델은 '경영진의 반복적인 조작 패턴'을 배우는 것이 아니라 '랜덤하게 섞인 전표 묶음'을 학습할 뿐입니다.

해결책: DataSynth 데이터에 created_time이나 정밀한 Timestamp가 없다면 시퀀스 모델의 존재 가치가 급락합니다. Tie-break 정렬 기준에 반드시 시간을 추가해야 합니다.

4. 모델 드리프트(Drift) 메타데이터 누락

실제 문제인가? 네. 감사 데이터는 회계 기준 변경이나 회사 인수로 1년만 지나도 분포가 크게 바뀝니다. 모델이 학습할 당시의 통계치(Mean/Std 등)를 저장해두지 않으면, 나중에 데이터가 썩어서 오탐을 뿜어내도 알 길이 없습니다. 규정 준수(SOC 2 등)를 위해서도 메타데이터 저장은 필수입니다.

😌 알면서도 일단 안고 가도 되는 기술 부채 (Can Wait - P2/P3)
이 항목들은 이론적으로는 아쉬우나, 당장 실무적인 가치를 훼손하지 않으므로 Phase 3 이후로 미뤄도 되는 것들입니다.

1. FT-Transformer의 과도성

판단: 구조가 무겁고 XGBoost와 역할이 겹치긴 하지만, VRAM 300MB 정도면 시스템을 터뜨리지 않습니다. 이미 구현되어 잘 돌아가고 있다면 굳이 지금 걷어낼 필요 없습니다. Stacking 모델이 알아서 가중치를 0으로 수렴시킬 것입니다.

2. 확률 보정 (Calibration)

판단: 모델의 출력이 '진짜 확률'이 아니라는 지적은 맞습니다. 하지만 현업 감사인은 "이 전표가 횡령일 확률이 정확히 87%다"라는 수치보다, **"가장 위험한 전표 Top 100개를 뽑아달라"**는 상대적 순위(Rank)를 훨씬 중요하게 생각합니다. 현재의 Percentile 기반 평가로 충분히 방어 가능합니다.

3. 추론 시간 지연 (순차 실행 vs 병렬화)

판단: 병렬 처리(ThreadPoolExecutor)를 짜는 것 자체는 좋으나, Python의 GIL(Global Interpreter Lock) 특성상 Pandas 연산이 섞여 있으면 생각보다 속도 향상이 크지 않을 수 있습니다. 100만 건 데이터를 실제로 돌려보고 진짜로 답답할 때 프로파일링을 거쳐 최적화해도 늦지 않습니다.