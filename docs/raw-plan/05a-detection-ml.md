# 05a. ML 이상탐지 (Phase 2b — 의존: 03a-preprocessing, 05-detection)

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> **🔄 Phase 3 v2 Rescope (2026-05-14) ✅ 구현 완료 (Sprint A~G, 2026-05-15)**: Phase 3 단일 목표는 [Review Queue Narrator](../PHASE3_REVIEW_NARRATOR_SPEC.md), 완료 리포트 [completed/phase3_review_narrator_completion.md](../completed/phase3_review_narrator_completion.md). 본 문서 내 "Phase 3 BiLSTM+Attention 교체 실험" / "DNN stacking meta-learner" / "7트랙 점수 가중" 절은 historical v1 기록. Phase 2의 Basic FC VAE + Isolation Forest는 그대로 보존되며 Narrator의 ML 스코어 입력으로 사용된다. [DECISION.md §D041](../DECISION.md) 참조.

> Latest PHASE1 role note (2026-04-28): this raw plan predates the current PHASE1 contract. PHASE1 rule output is a candidate-generation and case-priority input, not a final fraud label. Phase 2 should not treat PHASE1 rule IDs or DataSynth `is_fraud` / `is_anomaly` as a clean final truth for PHASE1 success. Use PHASE1 structured case summaries, rule-truth sidecars, and provenance-safe features; preserve the distinction between review candidates and confirmed audit issues.

## 목적

룰 기반 24개(Phase 1b)로 탐지할 수 없는 **복합 패턴**과 **미지 패턴**을 ML/DL로 보완한다.
6개 base model + Stacking meta-learner 앙상블 체계를 구현한다.

### ML 전략: 비지도학습 중심 (TS-3, 2026-04-01)

DataSynth 합성 데이터의 이상치는 룰 기반 주입이므로, 지도학습 시 **순환 학습** 문제가 발생한다.
(Phase 1 룰이 주입한 패턴을 ML이 재학습 → 부가가치 제한)

- **비지도학습(VAE+IF)**: 핵심 탐지기. 정상 분포 학습이므로 순환 문제 없음, 합성 데이터 적합도 높음
- **지도학습(XGBoost, FT-Transformer, BiLSTM)**: 파이프라인 인프라 구축. 고객사 실데이터 유입 시 fine-tuning 활성화
- **앙상블(Stacking)**: 전 모델 출력 결합. 비지도 점수에 더 높은 가중치 기대

상세: [CONSTRAINTS.md §ML 학습 전략](../CONSTRAINTS.md) | [TROUBLESHOOT.md §TS-3](../TROUBLESHOOT.md)

**6개 Base Model**:
1. **XGBoost/RF/LR/LGBM** (지도학습, cv_selector 자동 선택) — 파이프라인 인프라 (고객사 확장용)
2. **VAE + IF** (비지도학습 앙상블) — **핵심 탐지기**: 미지 패턴(zero-day)
3. **FT-Transformer** (D033) — 피처 간 상호작용을 self-attention으로 학습 (파이프라인 인프라)
4. **BiLSTM + Attention** (D032) — 사용자-시간 시퀀스 패턴 탐지 (파이프라인 인프라)

**앙상블**: Stacking meta-learner(LR Ridge)가 6개 모델의 가중치를 데이터 기반으로 학습 (D034)

> 원본 논의: `docs/detection_implementation_notes.md`
> 룰 기반 구현 가이드: `docs/pre-plan/05-detection.md`
> 전처리 파이프라인: `docs/pre-plan/03a-preprocessing.md`

> **데이터 분할 전략**: D029에서 확정 — Stratified 60/20/20, fraud_type 기준 층화추출.
> Hold-out Fraud Type(D027): suspense_account_abuse, expense_capitalization 2종 test 전용.

---

## 이상치 vs 특이치 이중 탐지 체계

| 구분       | 이상치 (Outlier)                  | 특이치 (Novelty)                     |
|:-----------|:----------------------------------|:-------------------------------------|
| 훈련 데이터 | 정상 + 이상 혼재                  | 정상만                               |
| 핵심 모델   | Classification (cv_selector 자동 선택) | VAE + Isolation Forest               |
| 질문        | "이 건이 부정인가?"               | "이 건이 본 적 없는 패턴인가?"       |

- **지도학습 모델**: "알려진 부정 패턴"을 학습하여 탐지. 과거 의존적. cv_selector가 후보군(LR/RF/XGBoost/LightGBM)에서 자동 선택.
- **VAE+IF**: "정상 분포"를 학습하여 벗어난 모든 것을 탐지. 미지 부정(zero-day)도 포착.

---

## 데이터 흐름

```
[피처 엔진 결과] (from feature/ — FeatureResult, 42차원)
       ↓
① label_strategy.select_learning_mode(y)    → "supervised" | "unsupervised" 판정
       ↓
② preprocessing/ pipeline_builder           → 6개 전처리+모델 파이프라인 구성
       ↓
   ┌─────────────────────────────────────────────────────────────────┐
   │  Level 0: Base Models (각각 독립 학습)                          │
   │                                                                 │
   │  [1] 룰 기반 24개 ──────────────── 이미 존재 (Phase 1)          │
   │  [2] XGBoost (cv_selector 최적) ── supervised_detector          │
   │  [3] VAE 재구성 오차 ──────────── vae_detector                  │
   │  [4] Isolation Forest ────────── vae_detector (앙상블)          │
   │  [5] FT-Transformer ─────────── tabular_transformer (D033)     │
   │  [6] BiLSTM + Attention ──────── sequence_detector (D032)      │
   └─────────────────────────────────────────────────────────────────┘
       ↓ (6개 predict_proba 결과)
   ┌─────────────────────────────────────────────────────────────────┐
   │  Level 1: Stacking Meta-Learner (D034)                         │
   │  Input: 6개 확률값 → LR(Ridge) → 최종 anomaly_score            │
   │  Leakage 방지: 5-fold out-of-fold prediction                   │
   │  Fallback: 라벨 부족 시 Percentile Ranking 가중합              │
   └─────────────────────────────────────────────────────────────────┘
       ↓
[anomaly_score + risk_level 보강된 DataFrame] → db/ (06-db)
```

---

## 관련 파일

```
src/detection/
├── supervised_detector.py   # GridSearchCV 지도학습 (모델 자동 선택) — WU-01
├── vae_detector.py          # VAE + IF 앙상블 — WU-02
├── tabular_transformer.py   # FT-Transformer 탐지기 — WU-01b (D033)
├── sequence_detector.py     # BiLSTM+Attention 시퀀스 탐지기 — WU-01c (D032)
├── ensemble_detector.py     # Stacking meta-learner 오케스트레이터 — WU-03 (D034)
└── score_aggregator.py      # Stacking 기반 집계 확장 — WU-03

src/preprocessing/           # Phase 2a (선행 의존) + Phase 2b 신규
├── label_strategy.py        # ✅ 라벨 판정 + 학습 모드 자동 전환
├── pipeline_builder.py      # ✅ 전처리 파이프라인 구성 (확장: build_ft_pipeline, build_bilstm_pipeline)
├── cv_selector.py           # ✅ GridSearchCV 모델 비교 (_has_vae → _has_torch_model 일반화)
├── vae_model.py             # ✅ Basic FC VAE PyTorch 모듈
├── vae_wrapper.py           # ✅ VAEDetector sklearn 래퍼 (canonical 패턴)
├── ft_model.py              # FT-Transformer PyTorch 모듈 — WU-01b (신규)
├── ft_wrapper.py            # FTTransformerDetector sklearn 래퍼 — WU-01b (신규)
├── sequence_builder.py      # 2D→3D 시퀀스 윈도우 구성 — WU-01c (신규)
├── bilstm_model.py          # BiLSTM+Attention PyTorch 모듈 — WU-01c (신규)
├── bilstm_wrapper.py        # BiLSTMDetector sklearn 래퍼 — WU-01c (신규)
└── stacking.py              # StackingEnsemble sklearn 래퍼 — WU-03 (신규)
```

---

## 모듈별 설계 가이드

### ① 라벨링 전략 (label_strategy.py) — ⬜ 미구현

```
src/preprocessing/
└── label_strategy.py    # 라벨 판정 + 학습 모드 자동 전환
```

#### 이 모듈이 하는 일

실무 감사 데이터에는 라벨이 없다. DataSynth 라벨로 지도학습을 하는 이유는
모델의 탐지 성능(precision/recall/F1)을 **정량 검증**하기 위함이다.
단, 합성 데이터 지도학습은 순환 학습 한계가 있으므로 (TS-3 참조),
**비지도학습(VAE+IF)이 실질적 핵심 탐지기**이며, 지도학습은 파이프라인 인프라 역할이다.

이 모듈은 입력 데이터의 라벨 상태를 분석하여 학습 모드를 자동 결정한다:
- 양성 샘플 충분 → `"supervised"` (cv_selector 자동 비교·선택)
- 양성 샘플 부족 → `"unsupervised"` (VAE + IF)

또한 VAE 학습 데이터 오염 방지를 위해 검증/실전 모드를 분기한다.

| 용도               | 학습 방식        | 사용 시점                        |
|:-------------------|:-----------------|:---------------------------------|
| 모델 성능 검증     | 지도학습(cv_selector) | 개발 중 DataSynth로 F1/AUROC 측정 |
| 실전 탐지          | VAE+IF(비지도)   | 실무 데이터 투입 시 (라벨 없음)   |
| 실전 탐지          | 룰 기반 24개     | 항상 (라벨 유무 무관)            |

#### 구현할 것

```python
def select_learning_mode(
    y: np.ndarray,
    min_positive: int = 50,          # StratifiedKFold 5-fold × 최소 10건
    min_positive_rate: float = 0.01,
) -> str:
    positive_count = y.sum()
    positive_rate = positive_count / len(y)

    if positive_count >= min_positive \
       and positive_rate >= min_positive_rate:
        return "supervised"    # cv_selector 자동 비교·선택
    else:
        return "unsupervised"  # VAE + IF (정상 데이터만 학습)

def get_vae_train_data(df: pd.DataFrame) -> pd.DataFrame:
    if "is_fraud" in df.columns:
        # 검증 모드: 라벨 있으면 정상만 필터링 (엄격)
        return df[df["is_fraud"] == False]
    else:
        # 실전 모드: 라벨 없으면 전체 투입 (Contamination Tolerance)
        return df
```

- 임계값은 `settings.py`에서 설정 가능
- 판단 근거: StratifiedKFold 5-fold 기준, 각 fold에 최소 양성 10건 필요 → 전체 ≥50건

#### 지도학습 모델 확장 경로 (고객사별 개별 학습)

현재 MVP에서 지도학습은 합성 데이터 순환 학습 한계로 실탐지 성능이 제한적이다.
그러나 파이프라인 인프라를 미리 구축하면, 고객사 실데이터 유입 시 즉시 활성화 가능하다.

| 단계             | 지도학습 모델 역할                              |
|:-----------------|:------------------------------------------------|
| 현재 MVP         | 파이프라인 인프라 시연 (합성 데이터, 성능 제한적)  |
| 고객사 1회차     | 감사인이 이상 여부 라벨링 → fine-tuning 활성화     |
| 고객사 2회차 이후 | 고객사 맞춤 모델 재사용 + 피드백 루프 재학습       |

#### 라벨링 소스

- **1차**: DataSynth `is_fraud`/`is_anomaly` 컬럼을 ground truth로 사용
- **추후**: validation 데이터로 라벨링 전략 재검토 (pseudo-label, hybrid 등)

#### VAE 학습 데이터: 검증 모드 vs 실전 모드

| 모드       | 학습 데이터                          | 근거                                          |
|:-----------|:-------------------------------------|:----------------------------------------------|
| 검증 모드   | `is_fraud=False`만 필터링 (정상 100%) | 엄격한 Zero-day 테스트. 라벨 있으므로 분리 가능 |
| 실전 모드   | 전체 데이터 그대로 투입               | 라벨 없으므로 정상만 분리 불가                  |

실전 모드가 작동하는 이유 — **Contamination Tolerance**:
- 실무 이상치 비율 <1~2%이므로 정상이 압도적 다수
- VAE 잠재 공간은 다수인 정상 데이터 위주로 형성
- 소수의 이상치는 잠재 공간에서 복원 실패 → 재구성 오차 여전히 높음

#### 설계 결정

| 이슈                              | 결정                                                    | 사유                                                        |
|:----------------------------------|:--------------------------------------------------------|:------------------------------------------------------------|
| 양성 최소 건수                    | 50건 (StratifiedKFold 5-fold × 10건)                    | 각 fold에 최소 양성 10건 보장                                |
| 양성 최소 비율                    | 1% (`min_positive_rate=0.01`)                           | 극단적 불균형 시 지도학습 의미 없음                           |
| 모드 전환 방식                    | 자동 (label_strategy가 데이터 상태 분석)                | 사용자 개입 없이 최적 모드 선택                               |
| VAE 학습 데이터 오염 방지          | 검증 모드: `is_fraud=False`만 필터링                    | 이상치를 정상으로 학습하면 탐지 실패                          |
| 실전 모드 Contamination Tolerance | 전체 투입 허용 (이상 <2%)                               | 정상 압도적 다수 → 잠재 공간 정상 위주 형성                   |

---

### ② 지도학습 탐지기 (supervised_detector.py) — ⬜ 미구현

```
src/detection/
└── supervised_detector.py    # SupervisedDetector(BaseDetector) — GridSearchCV
```

#### 이 모듈이 하는 일

24개 룰은 임계값 기반이므로 **복합 패턴**(다중 피처 조합) 탐지에 한계가 있다.
SupervisedDetector는 18개 피처 + 24개 룰 결과 = 42차원 입력을 ML 모델에 넣어
룰 기반으로 잡지 못하는 부정 패턴을 탐지한다.

cv_selector가 XGBoost/RandomForest/LightGBM을 자동 비교·선택하므로,
**모델 무관(model-agnostic) 전략**으로 불균형 처리와 평가를 수행한다.

#### 모델 후보

| 모델                | 판정              | 근거                                                                |
|:--------------------|:------------------|:--------------------------------------------------------------------|
| Logistic Regression | **유지 (베이스라인)** | 성능 낮지만(AUC ~0.66) 해석력 최고. "이 정도는 넘어야 한다" 기준선   |
| RandomForest        | **유지**           | 트리 계열 중 가장 안정적. 앙상블 base learner로도 활용               |
| XGBoost             | **유지**           | fraud detection 벤치마크 최고 성능 (AUC 0.91, PRAUC 0.89)           |
| LightGBM            | **유지**           | XGBoost 비교군. 대용량에서 속도 우위                                 |
| KNN                 | **제거**           | 1M건 + 고차원에서 O(n²) 계산 비용. curse of dimensionality           |
| DNN                 | **보류**           | 피처 엔지니어링 완료 상태에서 이점 감소. Phase 3 stacking meta-learner로 재고 |

#### 데이터 불균형 처리

감사 데이터는 비정상 비율 <1%인 극단적 불균형.

##### 4단계 불균형 대응

| 단계       | 전략                      | 적용 위치        | 비고                                     |
|:-----------|:--------------------------|:-----------------|:-----------------------------------------|
| 1. 데이터   | SMOTE-ENN (선택적)        | pipeline_builder | train set에만 적용. data leakage 방지 필수 |
| 2. 알고리즘 | 모델별 class weight 자동 매핑 | pipeline_builder | 아래 매핑표 참조                          |
| 3. 평가     | PR-AUC / F1-macro         | cv_selector      | accuracy는 불균형 시 무의미               |
| 4. 후처리   | Threshold Moving          | score_aggregator | predict_proba 기반 최적 cutoff 탐색       |

##### 모델별 class weight 매핑

```python
# pipeline_builder.py에서 모델 유형에 따라 자동 적용
IMBALANCE_PARAMS = {
    "XGBClassifier":          {"scale_pos_weight": neg_count / pos_count},
    "RandomForestClassifier": {"class_weight": "balanced"},
    "LGBMClassifier":         {"is_unbalance": True},
}
```

##### SMOTE-ENN 적용 시 주의

- 반드시 train/test split 이후, train set에만 적용
- split 전 적용 시 합성 데이터가 test set에 누출 → 성능 부풀림
- 추가 패키지: `imbalanced-learn` (설치 여부 추후 결정)
- 1순위는 `class_weight` 계열. SMOTE-ENN은 부족 시에만 사용.

#### 설계 결정

| 이슈                         | 결정                                                    | 사유                                                         |
|:-----------------------------|:--------------------------------------------------------|:-------------------------------------------------------------|
| 모델 선택                    | cv_selector가 4개 후보 자동 비교·선택                   | GridSearchCV로 LR/RF/XGBoost/LightGBM 중 최적 모델 결정      |
| 베이스라인                   | Logistic Regression                                     | "이 정도는 넘어야 한다" 기준선. 해석력 최고                   |
| KNN 제거                     | 1M건 + 고차원에서 O(n²)                                | 스케일링 불가                                                |
| DNN 보류                     | Phase 3 stacking meta-learner로 재고                    | 피처 엔지니어링 완료 상태에서 이점 감소                       |
| 불균형 1순위                 | 모델별 class_weight 자동 매핑                           | 추가 패키지 없이 적용 가능                                    |
| SMOTE-ENN                   | 선택적 (class_weight 부족 시만)                         | data leakage 위험, 추가 패키지 필요                           |
| 입력 차원                    | 18개 피처 + 24개 룰 결과 = 42차원                       | 룰 결과를 피처로 활용하여 ML 성능 향상                        |

---

### ③ VAE 탐지기 (vae_detector.py) — ⬜ 미구현

```
src/detection/
└── vae_detector.py    # VAEDetector(BaseDetector) — VAE + Isolation Forest 앙상블
```

#### 이 모듈이 하는 일

룰 기반은 "알려진" 패턴만 탐지한다. **미지 패턴(zero-day)** 탐지가 불가능하다.
VAEDetector는 정상 전표의 잠재 분포를 학습하여 reconstruction error로 미지 이상을 탐지하고,
Isolation Forest와 앙상블하여 false positive를 감소시킨다.

**실증 근거 (2026-03-28 E2E 전수조사, v7)**:
L4-04(비정상 계정조합) recall=10% (1,039건 중 105건). 전수조사 결과 라벨 중 ~56%가
실제로는 흔한 GL 조합(빈도 상위, 통계적 하위 1% 밖). 통계 룰의 구조적 한계:
- 룰이 잡는 것: GL 쌍 빈도 하위 1% (예: 빈도 3회 이하)
- 룰이 못 잡는 것: 빈도 4,700회이지만 도메인상 비정상인 조합
도메인 기반 "비정상 조합"은 통계 룰로 구조적으로 포착 불가.
VAE의 잠재 공간에서 정상 GL 조합 패턴을 학습하면, 빈도와 무관하게
"정상 패턴에서 벗어난 조합"을 재구성 오차로 탐지 가능 → UnusualAccountPair 커버.

#### 비지도 모델 후보

| 모델             | 판정           | 근거                                                                 |
|:-----------------|:---------------|:---------------------------------------------------------------------|
| LOF              | **제거**       | 1M건에서 O(n²) 스케일링. IF 대비 정밀도 낮음. 메모리 과다             |
| Isolation Forest | **유지 (메인)** | O(n·log n) 스케일링, 고차원 탐지 강점. VAE와 앙상블 상성 우수         |
| VAE              | **유지 (메인)** | 비선형 잠재 공간 학습. IF가 못 잡는 복합 패턴 탐지. 앙상블 상호 보완   |

#### Basic FC VAE 선택 근거 (Phase 2 MVP)

**근거 1 — 파이프라인 호환성 (2D vs 3D Tensor)**

pipeline_builder.py와 cv_selector.py는 사이킷런의 2D 배열 `(n_samples, n_features)` 입력을 가정.
Conv1D 도입 시 3D 배열 `(n_samples, sequence_length, features)`로 변환이 필요하여
기존 전처리 파이프라인(SimpleImputer, StandardScaler 등)과 구조적으로 충돌.

**근거 2 — 회계 데이터의 본질**

회계 전표는 연속 신호(ECG 등)가 아닌 개별 사건(Discrete Events).
time_features.py에서 시간적 맥락(is_weekend, days_backdated, period_end_concentration 등)을
파생변수로 이미 추출 완료. FC 레이어가 이 파생변수를 개별 피처로 학습 가능.

**근거 3 — 모델 앙상블 시너지**

- **Isolation Forest**: 다차원 공간에서 데이터 포인트의 고립도 기반 탐지
- **Basic VAE**: 비선형 잠재 공간 학습 → 재구성 오차 기반 탐지
- 두 알고리즘이 약점을 상호 보완. VAE 자체를 무겁게 만들 필요 없음.

#### 하이퍼파라미터: 모래시계(Bottleneck) 구조

입력 ~50차원 대비 Latent을 입력의 16% 수준으로 줄여 "핵심만 외우는" 압축을 강제.

```
Input(50) → Hidden(32) → Latent(8~12) → Hidden(32) → Output(50)
  100%        64%           16~24%          64%          100%
```

| 파라미터       | MVP 값     | 비고                                        |
|:--------------|:-----------|:--------------------------------------------|
| input_dim     | ~50        | One-hot 인코딩 후 피처 수 (동적 결정)        |
| hidden_dim    | 32         | 후보: [32, 64] — GridSearch 대상             |
| latent_dim    | 8          | 후보: [8, 12] — GridSearch 대상              |
| learning_rate | 1e-3       | 후보: [1e-3, 1e-4]                          |
| batch_size    | 256        | VRAM ~100MB로 충분                           |
| epochs        | 50~100     | early stopping 적용                          |

#### Phase 3 고도화: VAE + BiLSTM + Attention

vae_wrapper.py 내부에서 모델만 교체하는 래퍼 패턴.

```
pipeline_builder → 2D array → vae_wrapper.fit(X_2d)
                                    ↓ (내부에서)
                              sliding_window → 3D tensor
                              BiLSTM + Attention 인코더
                              reconstruction error → 1D scores
                              ↓
                         vae_wrapper.predict() → 2D 결과
```

- 외부 인터페이스는 sklearn 호환 2D 유지 → pipeline_builder/cv_selector 수정 없음
- vae_model.py만 교체하면 되는 구조

**Sliding Window 순서 유의미성 검증 필요:**
- 회계 전표는 같은 날 수백 건 배치 처리 → 순서가 임의적일 수 있음
- 순서 기준: `posting_date + document_id` 정렬로 시도
- Phase 2 Basic FC vs Phase 3 BiLSTM+Attention 성능 비교로 실증 검증

#### 설계 결정

| 이슈                         | 결정                                                    | 사유                                                         |
|:-----------------------------|:--------------------------------------------------------|:-------------------------------------------------------------|
| MVP 아키텍처                 | Basic FC VAE (50→32→8→32→50)                           | 파이프라인 호환(2D), 회계 데이터 본질(이산), 앙상블 시너지     |
| LOF 제거                     | 1M건에서 O(n²) 스케일링                                | IF 대비 정밀도 낮음, 메모리 과다                              |
| 앙상블 구성                  | VAE + Isolation Forest                                  | 약점 상호 보완 (비선형 잠재공간 + 고립도)                     |
| Phase 3 교체 전략            | vae_wrapper 내부에서 모델만 교체                        | 외부 2D 인터페이스 유지 → 파이프라인 수정 불필요              |
| Latent 차원                  | 입력의 16% (8~12)                                       | 과소 압축(정보 손실) / 과대(이상 학습) 사이 균형              |

---

### ④ 점수 통합 확장 (score_aggregator.py 확장) — ⬜ 미구현

```
src/detection/
└── score_aggregator.py    # Phase 1: L1/L2/L3/L4+Benford → Phase 2: 5트랙 가중합
```

#### 이 모듈이 하는 일

Phase 1에서 L1/L2/L3/L4(A/B/C) + Benford 4트랙 가중합을 구현한 score_aggregator를
Phase 2에서 5트랙(rule + supervised + vae + benford + duplicate)으로 확장한다.

각 모델의 점수 단위(Scale)가 다르므로, 가중합 전 0~1로 통일이 필요하다.

> 상세 전략 패턴은 `05-detection.md` §score_aggregator 참조

#### 점수 스케일 통일

```
모델별 원시 점수 범위:
  지도학습 모델 predict_proba: 0.0 ~ 1.0     (확률)
  Isolation Forest:         -0.5 ~ 0.5     (고립도, 음수=이상)
  VAE reconstruction error:  0.0 ~ ∞       (오차, 클수록 이상)
  룰 기반:                   0.0 ~ 1.0     (이미 정규화됨)
```

**방법: 백분위수 랭킹 (Percentile Ranking)**

```python
# score_aggregator.py — 가중합 전 정규화
from scipy.stats import rankdata

def normalize_scores(scores: pd.Series) -> pd.Series:
    """백분위수 기반 0~1 정규화.
    "이 전표가 전체 중 상위 몇 %인가?" → 분포 무관, 극단값에 강건."""
    return pd.Series(rankdata(scores) / len(scores), index=scores.index)
```

- Min-Max: 극단값에 취약
- Z-score: 정규분포 가정 필요
- **Percentile Ranking: 분포 무관, 극단값에 강건**

#### Phase별 가중치 변화

| Phase    | 가중치                                                                              |
|:---------|:------------------------------------------------------------------------------------|
| Phase 1  | `layer_a(0.15) + layer_b(0.45) + layer_c(0.25) + benford(0.15)`                    |
| Phase 2  | `rule(0.20) + supervised(0.25) + vae(0.20) + benford(0.15) + duplicate(0.20)`         |
| Phase 3  | `rule(0.15) + supervised(0.20) + vae(0.15) + benford(0.10) + dup(0.15) + nlp(0.10) + graph(0.15)` |

#### 설계 결정

| 이슈                         | 결정                                                    | 사유                                                         |
|:-----------------------------|:--------------------------------------------------------|:-------------------------------------------------------------|
| 정규화 방법                  | Percentile Ranking                                      | 분포 무관, 극단값에 강건. Min-Max/Z-score 대비 우위           |
| 가중치 설정 위치             | `constants.py` LAYER_WEIGHTS + settings.py override     | back-testing 후 .env로 override 가능                         |
| Phase 분기 방식              | settings.py에 가중치 딕셔너리 정의                      | score_aggregator는 Phase 분기 없이 받은 딕셔너리로 합산       |

---

## 성능 평가 지표 체계

### 용어 매핑

```
전통 ML 용어          이상탐지 도메인 용어       동일 여부
─────────────────    ──────────────────────    ──────────
Recall (TPR)       = Detection Rate (DR)       ✅ 동일
FPR                = FAR (False Alarm Rate)     ✅ 동일
FNR (1-Recall)     = FRR (False Rejection Rate) ✅ 동일
—                  = EER (Equal Error Rate)     FAR=FRR 교차점
Precision          = (대응 없음)                별도 개념
```

### 지표 선정 기준

- **부정 놓치면 안 됨** (FN 비용 >> FP 비용) → Recall/DR 중시
- **극단적 불균형** (<1%) → Accuracy, ROC-AUC 무의미
- **지도/비지도 둘 다 평가** → threshold-free 지표 필요

### 평가 지표 계층

| 계층              | 지표                      | 용도                                        |
|:------------------|:--------------------------|:--------------------------------------------|
| **1차 (메인)**     | AUPRC (PR-AUC)            | threshold-free, 불균형에 강건. 지도/비지도 공통 |
| **1차 (메인)**     | F2-score                  | Recall 가중 F-score. 부정 놓치지 않는 것 우선  |
| **2차 (보조)**     | MCC                       | 불균형에서도 신뢰할 수 있는 단일 지표         |
| **2차 (보조)**     | DR@FAR=5%                 | "오탐 5% 허용 시 탐지율" — 실무 의사결정용    |
| **3차 (참고)**     | ROC-AUC                   | 모델 간 비교용 (불균형 caveat 명시)           |
| **보고용**         | Precision, Recall, F1     | 대시보드 표시 + 감사인 소통용                 |

### F2를 F1 대신 사용하는 이유

```
F1 = 2 × (P × R) / (P + R)        → Precision과 Recall 동등
F2 = 5 × (P × R) / (4P + R)       → Recall에 2배 가중
```

감사에서는 "부정을 놓치는 것(FN)"이 "정상을 부정으로 잡는 것(FP)"보다 비용이 크므로 F2가 적합.

### DR@FAR=5%

"오탐률을 5%로 고정했을 때, 실제 부정을 몇 % 잡는가?"
감사인이 "전표 100건 검토할 때 5건은 오탐이어도 괜찮다" 전제에서 가장 직관적인 지표.

### 대시보드 UI 요구사항

감사인은 ML 지표에 익숙하지 않을 수 있으므로 Phase 1c 대시보드에서
각 지표의 의미를 비전문가 친화적으로 설명해야 한다.

- AUPRC → "모델이 부정 전표를 얼마나 정확하게 골라내는지를 나타내는 종합 점수 (0~1)"
- F2-score → "부정을 놓치지 않는 능력에 가중치를 둔 정확도 (0~1)"
- DR@FAR=5% → "오탐 5건을 허용할 때 실제 부정을 몇 건 잡는지"
- 위험 등급(High/Medium/Low/Normal) 기준도 대시보드에 명시

---

## DataSynth 비정상 비율

| 항목                   | 값                                              |
|:-----------------------|:------------------------------------------------|
| 설정 (datasynth.yaml)  | `fraud_rate: 0.02` (2%)                         |
| 데이터 규모            | 1,105K건                                        |
| 예상 비정상 건수        | ~22,069건                                       |
| 라벨 컬럼              | `is_fraud`, `is_anomaly`                        |

### 벤치마크 비교

| 데이터셋                  | 비정상 비율 |
|:-------------------------|:-----------|
| Kaggle Credit Card Fraud | 0.17%      |
| PaySim (합성)             | 1.3%       |
| IEEE-CIS Fraud           | 3.5%       |
| **DataSynth**            | **2.0%**   |
| 실무 감사 전표 (일반적)    | <1%        |

- 2%는 지도학습에 충분한 양성 샘플 (~21,000건 >> min_positive=50)
- 실무보다 높지만 벤치마크 범위 내

### 부정 유형 분포 (8가지)

| 유형                      | 비중 |
|:--------------------------|:-----|
| duplicate_payment         | 20%  |
| fictitious_transaction    | 20%  |
| revenue_manipulation      | 15%  |
| split_transaction         | 15%  |
| timing_anomaly            | 10%  |
| unauthorized_access       | 10%  |
| suspense_account_abuse    | 5%   |
| expense_capitalization    | 5%   |

---

## 구현 순서

```
1단계: src/detection/ 룰 기반 24개   (Phase 1b) — preprocessing 불필요
2단계: src/preprocessing/ 11개 모듈  (Phase 2a) — 독립 구현 + 테스트
3단계: src/detection/ ML 탐지기      (Phase 2b) — preprocessing import
```

- 각 단계가 독립적으로 테스트 가능
- 순환 의존성 없음 (detection → preprocessing 단방향)

### Phase 2b 구현 체크리스트

1. - [ ] `label_strategy.py` — 라벨 판정 + 학습 모드 자동 전환
2. - [ ] `supervised_detector.py` — GridSearchCV 지도학습 (모델 자동 선택)
3. - [ ] `vae_detector.py` — VAE + IF 앙상블
4. - [ ] `score_aggregator.py` — 5트랙 가중합으로 확장

Phase 2c (DuplicateDetector, TimeseriesDetector, IntercompanyMatcher)는 별도 계획으로 분리.

---

## 의존성

- **선행:**

| 모듈                  | 상태     | 비고                                           |
|:----------------------|:---------|:-----------------------------------------------|
| src/feature/          | ✅ 완료   | 18개 피처, generate_all_features() → FeatureResult |
| src/validation/       | ✅ 완료   | benford.py의 analyze_benford() L4-02에서 재사용    |
| config/settings.py    | ✅ 완료   | 모든 detection 임계값 구성 완료                  |
| config/audit_rules.yaml | ✅ 완료 | manual_source_codes, revenue_account_prefixes 등 |
| src/detection/ (룰)   | ⬜ 미구현 | Phase 1b — ML 탐지기의 입력(룰 결과)             |
| src/preprocessing/    | ⬜ 미구현 | Phase 2a — ML 탐지기의 전처리 파이프라인         |

- **외부 패키지:**
  - `xgboost`, `scikit-learn`, `torch` (ml 그룹)
  - `shap` (ml 그룹 — 설명 가능성)

- **내부 재사용:**
  - `src/preprocessing/pipeline_builder.py` → 전처리 파이프라인 구성
  - `src/preprocessing/cv_selector.py` → GridSearchCV 모델 비교
  - `src/preprocessing/label_strategy.py` → 학습 모드 자동 전환
  - `src/detection/score_aggregator.py` → Phase 1 구현체를 5트랙으로 확장
  - `config/settings.py` → 모든 임계값 참조

- **후행:**
  - `06-db` (ML 결과를 DuckDB에 적재)
  - `07-dashboard` (ML 점수 시각화 + 잠재 공간 t-SNE/UMAP)

> 디렉토리 분리 전략은 `05-detection.md` §구현 주의사항 참조

---

## 테스트 전략

### "배관의 튼튼함" 검증 원칙

ML 모델은 확률적(Stochastic)이므로 정확한 예측값을 단정할 수 없다.
**"정확한 점수"가 아닌 "파이프라인이 깨지지 않는가"를 테스트한다.**

```
❌ assert model.predict(X)[0] == 0.85   → 매번 다름
✅ assert result.shape == (100,)         → 구조 검증
✅ assert 0 <= result.min()               → 범위 검증
✅ assert result.max() <= 1.0             → 범위 검증
✅ assert not result.isna().any()          → 결측 없음
```

### 모듈별 테스트 계획

| 테스트 레벨  | 검증 대상                      | 방법                                        |
|:------------|:------------------------------|:--------------------------------------------|
| Unit        | score_aggregator 가중합 정확성  | Mock 모델 → 고정 점수 → 합산 검증            |
| Unit        | DetectionResult 스키마          | 반환 타입/필드 검증                          |
| Integration | 파이프라인 end-to-end           | 100건 미니 샘플 + seed=42 → 크래시 없이 완주  |
| Integration | 출력 스키마                     | anomaly_score(0~1), risk_level(str) 컬럼 존재 |

- Unit 테스트: ML 모델은 Mock으로 대체, 비즈니스 로직만 검증
- Integration 테스트: random_state=42 고정, "에러 없이 결과물이 나오는가"만 검증
- 성능(F1/AUPRC) 측정은 별도 벤치마크 스크립트로 분리 (테스트 스위트에 포함하지 않음)

### Hold-out Fraud Type (Zero-Day 테스트)

8개 부정 유형 중 6개로 훈련, 2개는 "미지의 부정"으로 테스트에만 사용.

```
훈련 데이터:
  지도학습 모델: [정상 + 6개 유형 이상치] (라벨 포함)
  VAE:     [정상 데이터만]

테스트 데이터:
  - 정상 데이터 (일부)
  - 6개 기출 유형 (seen)
  - 2개 미지 유형 (unseen) ← VAE 존재 이유 증명
```

| 모델     | 6개 기출 유형 | 2개 미지 유형 | 기대 결과                    |
|:---------|:-------------|:-------------|:----------------------------|
| 지도학습 모델 | 높은 탐지율   | 낮은 탐지율   | 본 적 없으므로 탐지 실패      |
| VAE+IF   | 높은 탐지율   | 여전히 탐지   | 정상 분포 밖이면 탐지         |

Hold-out 후보 (비중 낮은 2개 유형):
- `suspense_account_abuse` (5%)
- `expense_capitalization` (5%)

### Feature Perturbation (변수 교란 테스트)

정상 전표를 복사한 뒤 회계 원칙상 비정상 조합으로 변조.

```
예시: '복리후생비' 계정 + '페이퍼 컴퍼니' 거래처
  → 개별 변수는 흔한 값 → 룰/EDA 통과
  → VAE: "이 조합은 본 적 없다" → 재구성 오차 상승 → 탐지
```

VAE가 단순 통계가 아닌 "데이터의 논리적 관계"를 이해했는지 검증.

### 잠재 공간 시각화 (t-SNE / UMAP)

VAE 인코더로 테스트 데이터를 잠재 벡터로 압축 → 2D 시각화.

```
성공 조건:
  - 정상 데이터: 거대한 클러스터로 밀집
  - 6개 기출 이상치: 클러스터 외곽에 분리
  - 2개 미지 이상치: 역시 클러스터 외곽에 분리 → zero-day 탐지 증명
```

Phase 1c 대시보드 탭에 시각화 포함 가능.

### VAE 학습 데이터 오염 방지

VAE 학습 데이터에 이상치를 혼합하면 부정 패턴을 "정상 분포의 일부"로 학습 → 탐지 실패.

```
❌ VAE.fit([정상 98% + 이상치 2%])  → 이상치도 정상으로 학습
✅ VAE.fit([정상 100%])              → 이상치는 재구성 오차 상승
```

---

## 구현 시 주의사항

- **BaseDetector 인터페이스:** `detect()` → `DetectionResult` 반환 엄수. 새 트랙 추가 시 score_aggregator만 가중치 수정
- **점수 스케일 통일**: score_aggregator에서 가중합 전 Percentile Ranking으로 0~1 정규화 필수. 지도학습 모델(0~1)/IF(-0.5~0.5)/VAE(0~∞) 단위 혼재 방지
- **가중치 전략 패턴**: settings.py에 가중치 딕셔너리 정의, score_aggregator는 Phase 분기 없이 받은 딕셔너리로 합산
- **VAE 학습 데이터 오염 방지**: 이상치를 VAE 학습에 섞으면 정상으로 학습 → label_strategy에서 자동 제외
- **SHAP 비용:** SHAP는 계산 비용이 높음 → 플래그된 전표에 대해서만 on-demand 계산
- **VRAM 관리 (RTX 3070 Ti 8GB)**:

  Tabular VAE는 파라미터 수가 극히 적어 VRAM 부담이 거의 없다.

  ```
  이미지 VAE:   수백만 파라미터 → VRAM 2~4GB
  Tabular VAE:  ~5,000 파라미터 → VRAM ~100~200MB
  Ollama Qwen3: 4-bit 양자화   → VRAM ~5~5.5GB
  ```

  3단계 전략:

  | 순서 | 전략                          | 효과                              |
  |:-----|:-----------------------------|:----------------------------------|
  | 1    | Ollama `keep_alive="0"`      | LLM 사용 후 VRAM 즉시 반환        |
  | 2    | `torch.cuda.empty_cache()`   | VAE 학습 전후 잔여 캐시 정리       |
  | 3    | CPU fallback                 | 최후 수단. tabular은 CPU로 수 분   |

  LLM과 VAE를 동시에 돌릴 필요 없음 (타임 슬라이싱)

---

## 미해결 이슈 (교차 참조)

> Phase 1b/2a에서 넘어온 이슈. ML 탐지기 구현 시 함께 해결.

| 문제                            | 해결 방향                                     | 발견 위치                        |
|:--------------------------------|:----------------------------------------------|:---------------------------------|
| model_registry 경로 순회 취약점  | `resolve().relative_to()` 검증 삽입           | preprocessing 코드리뷰           |
| model_registry 상대 경로        | `get_settings().project_root / "models"` 변경 | preprocessing 코드리뷰           |
| vae_wrapper check_is_fitted 누락 | `check_is_fitted()` 추가                      | preprocessing 코드리뷰           |
| label_strategy hybrid 폴백 미비  | `positive_rate == 0 and scores` 분기 추가     | preprocessing 코드리뷰           |
| cv_selector VAE n_jobs 충돌     | `_has_vae()` 감지 → n_jobs=1 강제            | preprocessing 코드리뷰           |

> 전체 미해결 이슈 목록은 `05-detection.md` §선행 모듈에서 넘어온 미해결 이슈 참조.

---

## 감사기준서 갭 분석 반영 (DETECTION_RULES.md §3.3 기반)

> Phase 2에서 구현해야 할 신규 탐지 항목.

### TrendBreak — 회계추정치 편의(bias) 탐지

- **근거**: 감사기준서 240호 §32(b), ISA 540
- **입력**: 추정치 관련 계정(충당금, 감가상각, 보증)의 **다기간 시계열 데이터**
- **로직** (ISA 540 소급 검토 방식):
  1. 전기 추정치 vs 실제 결과 차이(estimation error) 시계열 산출
  2. 부호가 일관되게 한 방향이면 bias 의심 (이익 방향 편향)
  3. 추정치가 합리적 범위의 상한/하한에만 위치하는 패턴
- **데이터 요건**: `fiscal_year` 별 추정치 계정 잔액 (최소 3개년)

### MisclassifiedAccount — 계정분류 적정성

- **근거**: 감사기준서 315호, 330호
- **입력**: 계정-거래유형 매핑 마스터, `tax_code`/`tax_amount` (DataSynth 확장)
- **로직**: K-IFRS 표준계정과목 체계(자산 1xx~2xx, 수익 4xx, 판관비 8xx) 기반 이상 분류 탐지
- **한국 실무**: 부가세 10% 검증 (`tax_amount ≠ round(supply_amount × 0.1)`)

### 통제테스트(TOE) 데이터 기반 검증

- **근거**: 감사기준서 330호, 1100호
- **입력**: `approved_by`, `approval_date` (DataSynth v1.2.0 생성 완료), `required_approval_level` (DuckDB 파생 컬럼)
- **로직**: 승인 누락률(>5%), 평균 승인 지연(>48시간), 레벨 우회율(>3%) → 통제 미작동 판정

### 재무제표-장부 대사 (Trial Balance)

- **근거**: 감사기준서 330호
- **입력**: Trial Balance 테이블 (DuckDB 추가, `06-db.md` 스키마 참조)
- **로직**: GL 잔액 vs AR/AP Aging, 고정자산 대장 합계. 중요성 이하 차이 자동 통과

### 배치 전표 이상 패턴

- **근거**: 금융권 IT 감사 가이드라인
- **입력**: `source='batch'` 전표
- **로직**: 기말 집중, 대량 동시 생성, 금액 이상 탐지

---

## FT-Transformer 설계 (D033, WU-01b)

### 모델 선택 근거

| 후보            | 특징                                          | 적합도 |
|:----------------|:----------------------------------------------|:-------|
| TabTransformer  | 범주형 피처만 attention → 42차원 중 수치형 다수 제외 | ❌     |
| TabNet          | 벤치마크 열세 (Grinsztajn et al., NeurIPS 2022)  | ❌     |
| FT-Transformer  | 모든 피처를 토큰화 → self-attention               | ✅     |

FT-Transformer(Gorishniy et al., 2021 "Revisiting Deep Learning Models for Tabular Data")는
medium-size tabular에서 XGBoost와 경쟁적 성능을 보인다. 42차원 전체에 대해 attention 적용 가능.

### 아키텍처

```
42 features
  → Feature Tokenizer (각 피처 → 64-dim embedding)
    - 수치형: Linear(1, 64) + bias
    - 범주형: Embedding(num_categories, 64)
  → 42 tokens + [CLS] token (learnable)
  → Transformer Encoder
    - layers: 2
    - heads: 4
    - dim: 64
    - ff_dim: 128
    - dropout: 0.1
    - pre-norm (LayerNorm → Attention → Residual)
  → [CLS] output (64-dim)
  → FC(64 → 2) → softmax
```

### VRAM 예산

| 항목          | 크기   |
|:--------------|:-------|
| 토큰 임베딩   | 43 × 64 × batch = ~3MB |
| Attention     | 2층 × 4헤드 × 43² × batch = ~15MB |
| Feed-forward  | 2층 × 64×128 × batch = ~10MB |
| **총 추정**   | **~300MB** (batch=256) |

RTX 3070 Ti 8GB에서 여유 충분.

### sklearn 래퍼 설계 (ft_wrapper.py)

`vae_wrapper.py` 패턴을 동일하게 따른다:

- `BaseEstimator` 상속, `fit(X, y)` / `predict(X)` / `predict_proba(X)` 구현
- `__getstate__/__setstate__`: `state_dict` → bytes 직렬화 (joblib 호환)
- `_resolve_device()`: CUDA/CPU 자동 감지
- GPU 메모리 관리: `torch.cuda.empty_cache()` 학습 후 호출
- `n_features_in_` 속성으로 입력 차원 자동 결정

### 핵심 이점

24개 룰 결과가 ML 피처로 들어갈 때, FT-Transformer의 self-attention은
"어떤 룰 조합이 고위험인가"를 자동 학습한다.
Top-side JE 복합 점수의 학습 버전에 해당한다.

---

## BiLSTM + Attention 설계 (D032, WU-01c)

### 시퀀스 구성 전략

회계 전표는 개별 행(row)이지 시퀀스가 아니다.
그러나 같은 사용자의 연속 입력에서 시퀀스 패턴(점진적 금액 증가, 반복 수기 입력 등)이 존재한다.
ISA 240은 "경영진 override"를 핵심 부정 위험으로 지목한다.

**사용자-시간 윈도우 방식**:

| 항목           | 값                                        |
|:---------------|:------------------------------------------|
| 그룹 키        | `created_by` (입력자)                      |
| 정렬 기준      | `posting_date` + `document_id` (tie-break) |
| 윈도우 크기    | `seq_len=16` (ERP 일평균 5~20건, 2~3일분)  |
| 슬라이딩       | stride=1                                   |
| 패딩           | 3건 미만 사용자 → 제로 패딩 + 마스킹       |
| 예측 대상      | 윈도우 마지막 항목의 이상 여부              |

### 2D → 3D 변환 (sequence_builder.py)

```python
def build_sequences(
    X: np.ndarray,           # (N, 42) 전처리 완료 피처
    user_ids: np.ndarray,    # (N,) created_by
    timestamps: np.ndarray,  # (N,) posting_date
    seq_len: int = 16,
    stride: int = 1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns:
        X_seq: (N_windows, seq_len, 42)   시퀀스 텐서
        y_seq: (N_windows,)               마지막 항목의 라벨
        mask:  (N_windows, seq_len)       패딩 마스크 (1=유효, 0=패딩)
    """
```

### 아키텍처

```
Input (batch, 16, 42)
  → BiLSTM
    - input_size: 42
    - hidden_size: 64
    - num_layers: 1
    - bidirectional: True
    → output: (batch, 16, 128)
  → Additive Attention
    - query: learnable (128-dim)
    - attention weights: softmax(V^T · tanh(W·h + b))
    - 패딩 마스크 적용 (masked_fill -inf)
    → context: (batch, 128)
  → FC(128 → 64) → ReLU → Dropout(0.3)
  → FC(64 → 2) → softmax
```

### VRAM 예산

| 항목           | 크기    |
|:---------------|:--------|
| LSTM 파라미터  | 4 × (42+64) × 64 × 2 = ~54K params |
| Attention      | 128 × 1 = 128 params |
| FC layers      | 128×64 + 64×2 = ~8K params |
| **총 추정**    | **~100MB** (batch=256, seq=16) |

### sklearn 래퍼 설계 (bilstm_wrapper.py)

`vae_wrapper.py` 패턴을 따르되, 시퀀스 변환이 추가된다:

- **외부 API는 2D**: `fit(X_2d, y)`, `predict(X_2d)` — sklearn Pipeline 호환
- **내부에서 3D 변환**: `sequence_builder.build_sequences()` 호출
- `fit()` 시 `user_ids`, `timestamps`를 별도 파라미터로 전달하거나,
  DataFrame에서 추출하는 설정 방식 필요 (구현 시 결정)
- 시퀀스 빌더 파라미터(seq_len, stride)도 함께 직렬화

---

## Stacking Meta-Learner 설계 (D034, WU-03)

### 아키텍처

```
Level 0 (Base Models):
  [1] 룰 기반 24개 → aggregate → 1개 점수
  [2] XGBoost (cv_selector 최적) → predict_proba → 1개 확률
  [3] VAE → normalized reconstruction error → 1개 점수
  [4] Isolation Forest → normalized anomaly score → 1개 점수
  [5] FT-Transformer → predict_proba → 1개 확률
  [6] BiLSTM+Attention → predict_proba → 1개 확률

Level 1 (Meta-Learner):
  Input: (N, 6) 확률/점수 행렬
  Model: LogisticRegression(penalty="l2", C=1.0)
  Output: (N, 1) 최종 anomaly_score
```

### 메타 모델 선택 근거

| 후보         | 장점                          | 단점                        | 판정 |
|:-------------|:------------------------------|:----------------------------|:-----|
| LR (Ridge)   | 해석 가능, 계수=가중치        | 비선형 무시                 | ✅   |
| XGBoost      | 비선형 포착                   | 6개 입력에 과적합, self-amp | ❌   |
| RF           | 앙상블 안정성                 | 6개 입력에 과잉             | ❌   |

LR 계수가 곧 각 모델의 "데이터 기반 가중치"이므로, 기존 고정 가중합(D024)의 근거 없는 비율을 대체한다.

### Out-of-Fold Prediction 프로토콜 (Leakage 방지)

```python
class StackingEnsemble(BaseEstimator):
    def fit(self, X, y, base_pipelines: dict[str, Pipeline]):
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        oof_preds = np.zeros((len(X), len(base_pipelines)))

        for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train = y[train_idx]

            for model_idx, (name, pipe) in enumerate(base_pipelines.items()):
                pipe_clone = clone(pipe)
                pipe_clone.fit(X_train, y_train)
                oof_preds[val_idx, model_idx] = pipe_clone.predict_proba(X_val)[:, 1]

        # meta-learner 학습
        self.meta_learner_ = LogisticRegression(penalty="l2")
        self.meta_learner_.fit(oof_preds, y)

        # 최종 base model: 전체 데이터로 재학습
        self.base_models_ = {}
        for name, pipe in base_pipelines.items():
            self.base_models_[name] = clone(pipe).fit(X, y)
```

**비지도 모델 처리**: VAE와 IF는 `fit(X_train[y_train==0])` (정상만), `predict_proba(X_val)` (전체).

### Fallback 모드

라벨 부족(unsupervised 모드) 시 stacking 학습 불가 → 기존 Percentile Ranking 가중합으로 폴백:
- 각 base model 점수를 `scipy.stats.rankdata` → 0~1 정규화
- 고정 가중치로 합산 (기존 D024 방식)

---

## VRAM 예산 총괄 (RTX 3070 Ti 8GB)

| 모델            | 추정 사용량 | 학습 방식 | 비고              |
|:----------------|:-----------|:----------|:------------------|
| XGBoost         | ~200MB     | CPU       | GPU 학습 불필요   |
| LR/RF/LGBM      | ~100MB     | CPU       | GridSearchCV 포함 |
| VAE             | ~100MB     | GPU       | batch=256         |
| Isolation Forest| ~50MB      | CPU       | sklearn 내장      |
| FT-Transformer  | ~300MB     | GPU       | batch=256         |
| BiLSTM+Attention| ~100MB     | GPU       | batch=256, seq=16 |
| **최대 동시**   | **~300MB** |           | 모델 순차 학습    |

모델은 순차 학습이므로 동시 VRAM 최대는 ~300MB (FT-Transformer). 8GB 중 ~4% 사용.
