# 05-detection 구현 논의 메모 (2026-03-21)

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
> **재구성 완료**: 이 문서의 내용은 [`docs/pre-plan/05a-detection-ml.md`](pre-plan/05a-detection-ml.md)로 기술문서 형태로 재구성됨.
> 원본 논의 메모는 참고용으로 보존.

## 확정된 결정사항

### 1. 이상치 vs 특이치 이중 탐지 체계

| 구분       | 이상치 (Outlier)                  | 특이치 (Novelty)                     |
|:-----------|:----------------------------------|:-------------------------------------|
| 훈련 데이터 | 정상 + 이상 혼재                  | 정상만                               |
| 핵심 모델   | Classification (XGBoost)          | VAE + Isolation Forest               |
| 질문        | "이 건이 부정인가?"               | "이 건이 본 적 없는 패턴인가?"       |

### 2. 구현 범위

- **전체 한 번에 계획**: 룰 기반(24개) + SupervisedDetector(XGBoost) + VAEDetector(Basic FC + IF) + score_aggregator
- **구현 순서**: 룰 기반 → XGBoost → VAE+IF → score_aggregator(5트랙)
- **Phase 2 나머지 3종(DuplicateDetector, TimeseriesDetector, IntercompanyMatcher)은 별도 계획으로 분리**

### 3. 라벨링 전략 + 자동 학습 모드 전환

#### 라벨 데이터의 역할: "모델 검증"용이지 "실전 운영"용이 아님

실무 감사 데이터에는 라벨이 없다. DataSynth 라벨로 지도학습을 하는 이유는
모델의 탐지 성능(precision/recall/F1)을 정량 검증하기 위함이다.

| 용도               | 학습 방식        | 언제 사용                        |
|:-------------------|:-----------------|:---------------------------------|
| 모델 성능 검증     | XGBoost(지도)    | 개발 중 DataSynth로 F1/AUROC 측정 |
| 실전 탐지          | VAE+IF(비지도)   | 실무 데이터 투입 시 (라벨 없음)   |
| 실전 탐지          | 룰 기반 24개     | 항상 (라벨 유무 무관)            |

- **XGBoost**: "우리 시스템이 부정을 잡는다"를 증명하는 벤치마크 도구.
  포트폴리오에서 성능 지표를 보여줄 수 있음.
- **VAE+IF + 룰 기반**: 실전 메인. 라벨 없이도 동작.

#### XGBoost의 실전 활용: 전이 학습 (Transfer Learning)

XGBoost는 라벨 없는 실전에서도 활용 가능하다.
"부정 전표의 패턴"은 회사가 달라도 유사하므로 (기말 대규모, 승인한도 직하 등)
DataSynth에서 학습한 패턴이 실무 데이터에도 전이된다.

| 단계             | XGBoost 역할                                    |
|:-----------------|:------------------------------------------------|
| 개발 중          | DataSynth 벤치마크 (F1/AUROC 측정)               |
| 실전 1회차       | DataSynth 학습 모델 전이 적용 (보조 점수)         |
| 실전 2회차 이후   | 감사인 피드백으로 재학습 → 점점 정밀해짐 (Phase 3) |

- **1회차**: DataSynth로 학습한 모델을 실무 데이터에 그대로 적용 → 보조 anomaly score로 활용
- **2회차+**: 감사인이 "이건 진짜 부정"이라고 판정한 결과가 라벨이 됨 → XGBoost 재학습 → 정밀도 향상
- 피드백 루프 UI는 Phase 3 범위. MVP에서는 전이 적용(1회차)까지만 구현.

#### 라벨링 소스

- **1차**: DataSynth `is_fraud`/`is_anomaly` 컬럼을 ground truth로 사용
- **추후**: validation 데이터를 돌려보면서 라벨링 전략 재검토 (pseudo-label, hybrid 등)

#### 양성 샘플 부족 시 자동 전환 로직

`label_strategy.py`에서 양성 비율/건수 체크 → 기준 미달 시 자동으로 비지도(VAE+IF) 전환.

```python
def select_learning_mode(
    y: np.ndarray,
    min_positive: int = 50,       # StratifiedKFold 5-fold × 최소 10건
    min_positive_rate: float = 0.01,
) -> str:
    positive_count = y.sum()
    positive_rate = positive_count / len(y)

    if positive_count >= min_positive \
       and positive_rate >= min_positive_rate:
        return "supervised"   # XGBoost Classification
    else:
        return "unsupervised" # VAE + IF (정상 데이터만 학습)
```

- 임계값(`min_positive`, `min_positive_rate`)은 `settings.py`에서 설정 가능
- 판단 근거: StratifiedKFold 5-fold 기준, 각 fold에 최소 양성 10건 필요 → 전체 ≥50건

### 4. VAE 아키텍처: Basic FC VAE + IF 앙상블

#### 왜 VAE가 핵심인가 (포트폴리오 강조 포인트)

**전통적 지도학습(XGBoost, RF 등)의 한계:**
- "이미 본 부정 패턴"만 탐지할 수 있다 (known fraud detection)
- 학습 데이터에 없는 새로운 부정 수법에 대응 불가
- 부정 수법은 계속 진화하므로, 지도학습만으로는 항상 한 발 늦다

**VAE의 근본적 차별점: "정상을 학습"하는 접근**
- 정상 거래의 잠재 분포(latent distribution)만 학습
- 그 분포에서 벗어난 **모든 것**을 이상거래로 플래그
- 새로운 부정 수법이 등장해도, 그것이 정상 분포 밖이면 자동 탐지
- 즉, 부정 패턴을 몰라도 탐지할 수 있다 (zero-day fraud detection)

```
지도학습 (XGBoost):  "이 패턴은 과거에 부정이었으니 부정이다"  → 과거 의존
비지도학습 (VAE):    "이 패턴은 정상이 아니다"                → 미래 부정도 탐지
```

**포트폴리오 관점에서의 가치:**
- 실무 감사에서 "어떤 부정이 있는지 모르는 상태"가 기본 전제
- VAE는 이 전제에 가장 부합하는 접근 → 프로젝트 차별화 핵심
- 지도학습은 "시스템 성능 검증용", VAE+IF는 "실전 탐지 엔진"으로 역할 분리

#### Phase 3 고도화: VAE + BiLSTM + Attention (래퍼 내부 교체)

2025년 논문에서 VAE+BiLSTM+Attention이 99.56% 정확도를 보인다.
이 아키텍처를 포기하지 않되, **vae_wrapper.py 내부로 복잡도를 캡슐화**하여 반영한다.

**캡슐화 전략:**
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
- 내부에서만 sliding window로 3D 변환 + BiLSTM + Attention 처리
- vae_model.py만 교체하면 되는 구조 — 래퍼 패턴의 핵심 가치

**단계적 로드맵:**
```
Phase 2 (MVP):  Basic FC VAE + IF → 파이프라인 end-to-end 검증 + 베이스라인 성능 측정
Phase 3 (고도화): vae_model.py를 BiLSTM + Attention으로 교체 실험
                 → 성능 향상 확인 시 유지, 아니면 Basic FC로 복귀
```

**검증 포인트 — Sliding Window 순서의 유의미성:**
- 카드 결제는 순서에 패턴이 있지만, 회계 전표는 같은 날 수백 건이 배치 처리되어 순서가 임의적일 수 있음
- 순서 기준: `posting_date + document_id` 정렬로 시도
- Phase 2 Basic FC vs Phase 3 BiLSTM+Attention 성능 비교로 실증 검증
- 차이가 유의미하면 유지, 아니면 복귀 — 래퍼 패턴이라 교체 비용 최소

---

**Conv1D 대신 Basic FC를 선택한 3가지 근거 (Phase 2 MVP):**

#### 근거 1: 파이프라인 호환성 (2D vs 3D Tensor)
pipeline_builder.py와 cv_selector.py는 사이킷런의 2D 배열 `(n_samples, n_features)` 입력을 가정.
Conv1D 도입 시 3D 배열 `(n_samples, sequence_length, features)`로 변환하는 슬라이딩 윈도우 로직이 필요.
기존 전처리 파이프라인(SimpleImputer, StandardScaler 등)과 구조적으로 충돌하며, 코드 복잡도 통제 불능.

#### 근거 2: 회계 데이터의 본질과 기발생 피처
회계 전표는 연속 신호(ECG 등)가 아닌 개별 사건(Discrete Events).
이미 time_features.py에서 시간적 맥락(is_weekend, days_backdated, period_end_concentration 등)을
파생변수로 추출 완료. FC 레이어가 이 파생변수를 개별 피처로 받아 시간적 특성을 학습 가능.
Conv1D로 시계열을 다시 학습할 필요 없음.

#### 근거 3: 모델 앙상블의 시너지 효과
- **Isolation Forest**: 다차원 공간에서 데이터 포인트의 고립도 기반 탐지
- **Basic VAE**: 비선형 잠재 공간 학습 → 재구성 오차(Reconstruction Error) 기반 탐지
- 두 알고리즘의 약점을 상호 보완하여 실무적으로 충분한 특이치 탐지 성능 확보.
  VAE 자체를 무겁게 만들 필요 없음.

### 5. 데이터 불균형 처리 전략

감사 데이터는 비정상 비율 <1%인 극단적 불균형. cv_selector가 XGBoost/RandomForest/LightGBM을
비교 선택하므로 **모델 무관(model-agnostic) 전략**을 적용한다.

#### 4단계 불균형 대응 (모델 무관)

| 단계       | 전략                      | 적용 위치        | 비고                                     |
|:-----------|:--------------------------|:-----------------|:-----------------------------------------|
| 1. 데이터   | SMOTE-ENN (선택적)        | pipeline_builder | train set에만 적용. data leakage 방지 필수 |
| 2. 알고리즘 | 모델별 class weight 자동 매핑 | pipeline_builder | 아래 매핑표 참조                          |
| 3. 평가     | PR-AUC / F1-macro         | cv_selector      | accuracy는 불균형 시 무의미               |
| 4. 후처리   | Threshold Moving          | score_aggregator | predict_proba 기반 최적 cutoff 탐색       |

#### 모델별 class weight 매핑

```python
# pipeline_builder.py에서 모델 유형에 따라 자동 적용
IMBALANCE_PARAMS = {
    "XGBClassifier":          {"scale_pos_weight": neg_count / pos_count},
    "RandomForestClassifier": {"class_weight": "balanced"},
    "LGBMClassifier":         {"is_unbalance": True},
}
```

#### SMOTE-ENN 적용 시 주의

- **반드시 train/test split 이후, train set에만 적용**
- split 전에 적용하면 합성 데이터가 test set에 누출 → 성능 지표 부풀려짐
- 추가 패키지: `imbalanced-learn` (설치 여부 추후 결정)
- 1순위는 `class_weight` 계열. SMOTE-ENN은 그것으로 부족할 때만 사용.

#### 근거 (2025~2026 최신 연구)

- 알고리즘 수준 조정(scale_pos_weight, class_weight)이 데이터 수준 조정(SMOTE)보다 안정적
- ICML 2025: 최적 train 불균형 비율은 50:50이 아니며, 데이터 양과 노이즈에 따라 달라짐
- XGBoost + scale_pos_weight 튜닝만으로 SMOTE급 성능 달성 가능 (leakage 위험 없음)

### 6. ML 모델 후보 선정

cv_selector가 자동 비교하므로, 후보군만 확정하면 된다.

#### 지도학습 (Classification) — cv_selector 자동 비교

| 모델                | 판정              | 근거                                                                |
|:--------------------|:------------------|:--------------------------------------------------------------------|
| Logistic Regression | **유지 (베이스라인)** | 성능 낮지만(AUC ~0.66) 해석력 최고. "이 정도는 넘어야 한다" 기준선   |
| RandomForest        | **유지**           | 트리 계열 중 가장 안정적. 앙상블 base learner로도 활용               |
| XGBoost             | **유지 (메인)**    | fraud detection 벤치마크 최고 성능 (AUC 0.91, PRAUC 0.89)           |
| LightGBM            | **유지**           | XGBoost 비교군. 대용량에서 속도 우위                                 |
| KNN                 | **제거**           | 1M건 + 고차원에서 O(n²) 계산 비용. curse of dimensionality           |
| DNN                 | **보류**           | 피처 엔지니어링 완료 상태에서 이점 감소. stacking meta-learner로 재고 가능 |

#### 비지도학습 (Novelty Detection) — 앙상블

| 모델             | 판정           | 근거                                                                 |
|:-----------------|:---------------|:---------------------------------------------------------------------|
| LOF              | **제거**       | 1M건에서 O(n²) 스케일링. IF 대비 정밀도 낮다는 연구 다수. 메모리 과다 |
| Isolation Forest | **유지 (메인)** | O(n·log n) 스케일링, 고차원 탐지 강점. VAE와 앙상블 상성 좋음         |
| VAE              | **유지 (메인)** | 비선형 잠재 공간 학습. IF가 못 잡는 복합 패턴 탐지. 앙상블 상호 보완   |

#### 최종 후보 요약

```
지도학습 (cv_selector 자동 비교):
  ✅ Logistic Regression  — 베이스라인
  ✅ RandomForest          — 안정적 앙상블
  ✅ XGBoost               — 메인 후보
  ✅ LightGBM              — 속도 비교군
  ❌ KNN                   — 제거 (스케일링 문제)
  🔄 DNN                   — 보류 (Phase 3 stacking에서 재고)

비지도학습 (앙상블):
  ❌ LOF                   — 제거 (스케일링 + 정밀도)
  ✅ Isolation Forest       — 메인
  ✅ VAE                    — 메인
```

### 7. 성능 평가 지표 체계

#### 용어 매핑: 전통 ML vs 이상탐지 도메인

```
전통 ML 용어          이상탐지 도메인 용어       동일 여부
─────────────────    ──────────────────────    ──────────
Recall (TPR)       = Detection Rate (DR)       ✅ 동일
FPR                = FAR (False Alarm Rate)     ✅ 동일
FNR (1-Recall)     = FRR (False Rejection Rate) ✅ 동일
—                  = EER (Equal Error Rate)     FAR=FRR 교차점
Precision          = (대응 없음)                별도 개념
```

같은 confusion matrix 기반이며 용어만 다르다.

#### 지표 선정 기준

- **부정 놓치면 안 됨** (FN 비용 >> FP 비용) → Recall/DR 중시
- **극단적 불균형** (<1%) → Accuracy, ROC-AUC 무의미
- **지도/비지도 둘 다 평가** → threshold-free 지표 필요

#### 평가 지표 체계

| 계층              | 지표                      | 용도                                        |
|:------------------|:--------------------------|:--------------------------------------------|
| **1차 (메인)**     | AUPRC (PR-AUC)            | threshold-free, 불균형에 강건. 지도/비지도 공통 |
| **1차 (메인)**     | F2-score                  | Recall 가중 F-score. 부정 놓치지 않는 것 우선  |
| **2차 (보조)**     | MCC                       | 불균형에서도 신뢰할 수 있는 단일 지표         |
| **2차 (보조)**     | DR@FAR=5%                 | "오탐 5% 허용 시 탐지율" — 실무 의사결정용    |
| **3차 (참고)**     | ROC-AUC                   | 모델 간 비교용 (단, 불균형 caveat 명시)       |
| **보고용**         | Precision, Recall, F1     | 대시보드 표시 + 감사인 소통용                 |

#### F2를 F1 대신 사용하는 이유

```
F1 = 2 × (P × R) / (P + R)        → Precision과 Recall 동등
F2 = 5 × (P × R) / (4P + R)       → Recall에 2배 가중

감사에서는 "부정을 놓치는 것(FN)"이 "정상을 부정으로 잡는 것(FP)"보다
비용이 훨씬 크므로 F2가 적합.
```

#### DR@FAR=5%

"오탐률을 5%로 고정했을 때, 실제 부정을 몇 % 잡는가?"
감사인이 "전표 100건 검토할 때 5건은 오탐이어도 괜찮다" 전제에서 가장 직관적인 지표.

#### 대시보드 UI 요구사항

감사인은 ML 지표에 익숙하지 않을 수 있다.
Phase 1c 대시보드에서 각 지표의 의미를 **비전문가 친화적으로 설명**해야 한다.

- 각 지표 옆에 tooltip 또는 info icon으로 한글 설명 표시
- 예: AUPRC → "모델이 부정 전표를 얼마나 정확하게 골라내는지를 나타내는 종합 점수 (0~1, 높을수록 좋음)"
- 예: F2-score → "부정을 놓치지 않는 능력에 가중치를 둔 정확도 (0~1)"
- 예: DR@FAR=5% → "오탐 5건을 허용할 때 실제 부정을 몇 건 잡는지"
- 위험 등급(High/Medium/Low/Normal) 기준도 대시보드에 명시

---

## 탐색 결과 요약

### 선행 의존성 상태

| 모듈                  | 상태     | 비고                                           |
|:----------------------|:---------|:-----------------------------------------------|
| src/feature/          | ✅ 완료   | 18개 피처, generate_all_features() → FeatureResult |
| src/validation/       | ✅ 완료   | benford.py의 analyze_benford() C07에서 재사용    |
| config/settings.py    | ✅ 완료   | 모든 detection 임계값 구성 완료                  |
| config/audit_rules.yaml | ✅ 완료 | manual_source_codes, revenue_account_prefixes 등 |
| src/preprocessing/    | ⬜ 미구현 | 설계 완료(11개 모듈 스펙), ML 탐지기의 선행 의존성 |
| src/detection/        | ⬜ 미구현 | 디렉토리 미존재, 전체 생성 필요                  |

### preprocessing 모듈 (ML 탐지기 선행 의존)

설계는 완료(03a-preprocessing.md + 62 tests 스펙). 코드 미구현.
- pipeline_builder.py: XGBoost/VAE/IF 3개 파이프라인 빌드
- cv_selector.py: StratifiedKFold 파이프라인 비교
- label_strategy.py: DataSynth GT / pseudo / hybrid 3단 라벨링
- vae_wrapper.py: sklearn 호환 VAE 래퍼 (fit/predict/predict_proba)
- vae_model.py: PyTorch VAE 네트워크

---

## 추가 결정사항

### 8. preprocessing과 detection 디렉토리 분리 + 단방향 의존성

디렉토리는 분리하되, detection → preprocessing 단방향 의존으로 설계한다.
전처리는 "데이터를 모델이 먹기 좋게 요리"하는 것, 탐지는 "요리를 먹고 판단"하는 것.

```
src/preprocessing/          src/detection/
  pipeline_builder.py         supervised_detector.py
  cv_selector.py              vae_detector.py
  vae_wrapper.py              ↑
  label_strategy.py           │ import (단방향)
       ↓                      │
  "요리 준비"          ←───  "요리를 먹고 판단"
```

**구현 순서:**
```
1단계: src/detection/ 룰 기반 (24개) — preprocessing 불필요
2단계: src/preprocessing/ (11개 모듈) — 독립 구현 + 테스트
3단계: src/detection/ ML 탐지기 — preprocessing import해서 사용
```

- 각 단계가 독립적으로 테스트 가능
- 순환 의존성 없음
- 결합도(Coupling) 최소화

---

## 미논의 사항

- [x] ~~preprocessing 모듈 구현을 detection과 함께 할 것인지, 별도로 할 것인지~~ → 디렉토리 분리 + 단방향 의존
- [x] ~~score_aggregator Phase 1 → Phase 2 가중치 전환 방식~~ → 전략 패턴 (아래)

### 9. score_aggregator 가중치 전환: 전략 패턴 (Strategy Pattern)

코드에 `if phase == 1:` 같은 하드코딩을 넣지 않는다.
settings.py에 가중치 딕셔너리를 정의하고, score_aggregator는 받은 딕셔너리로 합산만 한다.

```python
# settings.py — 가중치 딕셔너리 (Phase별 override 가능)
scoring_weights: dict[str, float] = {
    "layer_a": 0.15, "layer_b": 0.45, "layer_c": 0.25, "benford": 0.15
}
# Phase 2 전환 시 .env 또는 YAML에서 override:
# scoring_weights = {"rule": 0.20, "xgboost": 0.25, "vae": 0.20, "benford": 0.15, "duplicate": 0.20}

# score_aggregator.py — 로직 코드 수정 없음
def aggregate_scores(df, results, weights: dict[str, float]):
    # weights가 뭐든 그냥 합산. Phase 분기 없음.
```

- 설정만 바꾸면 Phase 전환 완료
- back-testing 후 가중치 튜닝도 코드 수정 없이 가능
- score_aggregator는 순수 함수로 유지

#### ⚠️ 보완: 가중합 전 점수 스케일 통일 (Percentile Ranking)

각 모델의 점수 단위(Scale)가 다르므로, 가중치를 곱하기 전에 0~1로 통일해야 한다.

```
모델별 원시 점수 범위:
  XGBoost predict_proba:     0.0 ~ 1.0     (확률)
  Isolation Forest:         -0.5 ~ 0.5     (고립도, 음수=이상)
  VAE reconstruction error:  0.0 ~ ∞       (오차, 클수록 이상)
  룰 기반:                   0.0 ~ 1.0     (이미 정규화됨)
```

통일하지 않으면 VAE 오차(50, 100 등)가 전체 점수를 지배(Dominate)하여
XGBoost와 룰 기반 점수가 묻힘.

**방법: 백분위수 랭킹 (Percentile Ranking)**
```python
# score_aggregator.py — 가중합 전 정규화
from scipy.stats import rankdata

def normalize_scores(scores: pd.Series) -> pd.Series:
    """백분위수 기반 0~1 정규화.
    "이 전표가 전체 중 상위 몇 %인가?" → 분포 무관, 극단값에 강건."""
    return pd.Series(rankdata(scores) / len(scores), index=scores.index)
```

- Min-Max: 극단값에 취약 ❌
- Z-score: 정규분포 가정 필요 ❌
- **Percentile Ranking: 분포 무관, 극단값에 강건 ✅**
- [x] ~~DataSynth 데이터에서 정상/이상 비율 확인~~ → §10
- [x] ~~VAE latent dimension, hidden layer 크기 등 하이퍼파라미터~~ → §12
- [x] ~~VRAM 관리 전략 (RTX 3070 Ti 8GB: Qwen3 ~5GB + VAE ~2GB)~~ → §13
- [x] ~~테스트 전략: 룰 + ML 통합 테스트 범위~~ → §11, §14

### 10. DataSynth 비정상 비율

| 항목                   | 값                                              |
|:-----------------------|:------------------------------------------------|
| 설정 (datasynth.yaml)  | `fraud_rate: 0.02` (2%)                         |
| 데이터 규모            | 1,105K건                                        |
| 예상 비정상 건수        | ~22,069건                                       |
| 라벨 컬럼              | `is_fraud`, `is_anomaly`                        |

벤치마크 비교:

| 데이터셋                  | 비정상 비율 |
|:-------------------------|:-----------|
| Kaggle Credit Card Fraud | 0.17%      |
| PaySim (합성)             | 1.3%       |
| IEEE-CIS Fraud           | 3.5%       |
| **우리 DataSynth**       | **2.0%**   |
| 실무 감사 전표 (일반적)    | <1%        |

- 2%는 지도학습(XGBoost)에 충분한 양성 샘플 (~21,000건 >> min_positive=50)
- 실무보다는 높지만 벤치마크 범위 내

부정 유형 분포 (8가지):

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

### 11. ML 테스트 전략: Hold-out Fraud Type + VAE 보완 테스트

#### 메인 테스트: Hold-out Fraud Type (Zero-Day 공격 테스트)

8개 부정 유형 중 6개로 훈련, 2개는 "미지의 부정"으로 테스트에만 사용.

```
훈련 데이터:
  XGBoost: [정상 + 6개 유형 이상치] (라벨 포함)
  VAE:     [정상 데이터만] ← ⚠️ 핵심 주의사항

테스트 데이터:
  - 정상 데이터 (일부)
  - 6개 기출 유형 (seen)
  - 2개 미지 유형 (unseen) ← VAE 존재 이유 증명
```

| 모델     | 6개 기출 유형 | 2개 미지 유형 | 기대 결과                    |
|:---------|:-------------|:-------------|:----------------------------|
| XGBoost  | 높은 탐지율   | 낮은 탐지율   | 본 적 없으니 못 잡음         |
| VAE+IF   | 높은 탐지율   | 여전히 탐지   | 정상 분포 밖이면 잡음        |

Hold-out 후보 (비중 낮은 2개 유형):
- `suspense_account_abuse` (5%)
- `expense_capitalization` (5%)

#### ⚠️ 핵심 주의사항: VAE 학습 데이터 오염 방지

VAE 학습 데이터에 이상치를 비중 있게 섞으면, VAE가 부정 패턴을 "정상 분포의 일부"로
학습하여 재구성 오차가 낮아짐 → 탐지 실패.

```
❌ 잘못된 구성: VAE.fit([정상 98% + 이상치 2%])  → 이상치도 정상으로 학습
✅ 올바른 구성: VAE.fit([정상 100%])              → 이상치는 재구성 오차 높음
```

label_strategy.py에서 VAE 학습 시 `is_fraud=True` 데이터를 자동 제외하는 로직 필요.

#### 검증 모드 vs 실전 모드 VAE 학습 데이터

| 모드       | 학습 데이터                          | 근거                                          |
|:-----------|:-------------------------------------|:----------------------------------------------|
| 검증 모드   | `is_fraud=False`만 필터링 (정상 100%) | 엄격한 Zero-day 테스트. 라벨 있으므로 분리 가능 |
| 실전 모드   | 전체 데이터 그대로 투입               | 라벨 없으므로 정상만 분리 불가                  |

**실전 모드가 작동하는 이유 — Contamination Tolerance:**
- 실무 이상치 비율 <1~2%이므로 압도적으로 정상이 다수
- VAE 잠재 공간은 다수인 정상 데이터 위주로 형성됨
- 소수의 이상치는 잠재 공간에서 복원하지 못해 재구성 오차가 여전히 높음
- 즉, 이상치가 살짝 섞여도 VAE는 정상 작동함

```python
# label_strategy.py — 모드 분기
def get_vae_train_data(df: pd.DataFrame) -> pd.DataFrame:
    if "is_fraud" in df.columns:
        # 검증 모드: 라벨 있으면 정상만 필터링 (엄격)
        return df[df["is_fraud"] == False]
    else:
        # 실전 모드: 라벨 없으면 전체 투입 (Contamination Tolerance)
        return df
```

#### 보완 테스트 A: 변수 교란 테스트 (Feature Perturbation)

정상 전표를 복사한 뒤 회계 원칙상 말이 안 되는 조합으로 변조.

```
예시: '복리후생비' 계정 + '페이퍼 컴퍼니' 거래처
  → 개별 변수는 흔한 값 → 룰/EDA 통과
  → VAE: "이 조합은 본 적 없다" → 재구성 오차 상승 → 탐지
```

- 개별 피처는 정상 범위이지만, 피처 간 상관관계가 비정상인 케이스
- VAE가 단순 통계가 아닌 "데이터의 논리적 관계"를 이해했는지 검증

#### 보완 테스트 B: 잠재 공간 시각화 (t-SNE / UMAP)

VAE 인코더로 테스트 데이터를 잠재 벡터로 압축 → t-SNE/UMAP으로 2D 시각화.

```
성공 조건:
  - 정상 데이터: 거대한 클러스터로 밀집
  - 6개 기출 이상치: 클러스터 외곽에 분리
  - 2개 미지 이상치: 역시 클러스터 외곽에 분리 → zero-day 탐지 증명
```

- Phase 1c 대시보드 Tab에 시각화 포함 가능
- 포트폴리오에서 "모델이 우아하게 학습되었다"를 시각적으로 증명

### 12. VAE 하이퍼파라미터: 모래시계(Bottleneck) 구조

입력이 ~50차원인데 Latent을 32~64로 잡으면 압축 없이 값을 복사(Identity Mapping)함.
Latent을 입력의 16% 수준으로 줄여야 "핵심만 외우는" 압축을 강제.

```
MVP 기준 아키텍처:
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

- Latent 8 vs 12는 실험으로 결정 (cv_selector 또는 별도 비교)
- vae_wrapper.py에서 하이퍼파라미터를 외부 주입 가능하도록 설계

### 13. VRAM 관리 전략 (RTX 3070 Ti 8GB)

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

- LLM과 VAE를 동시에 돌릴 필요 없음 (타임 슬라이싱)
- Phase 1c 대시보드에서 LLM 조언 탭 → VAE 탐지 탭 순차 사용

### 14. 테스트 전략: "배관의 튼튼함" 검증

ML 모델은 확률적(Stochastic)이므로 정확한 예측값을 단정할 수 없다.
**"정확한 점수"가 아닌 "파이프라인이 깨지지 않는가"를 테스트한다.**

```
❌ 잘못된 테스트: assert model.predict(X)[0] == 0.85   → 매번 다름
✅ 올바른 테스트: assert result.shape == (100,)         → 구조 검증
                 assert 0 <= result.min()               → 범위 검증
                 assert result.max() <= 1.0             → 범위 검증
                 assert not result.isna().any()          → 결측 없음
```

| 테스트 레벨  | 검증 대상                      | 방법                                        |
|:------------|:------------------------------|:--------------------------------------------|
| Unit        | score_aggregator 가중합 정확성  | Mock 모델 → 고정 점수 → 합산 검증            |
| Unit        | DetectionResult 스키마          | 반환 타입/필드 검증                          |
| Integration | 파이프라인 end-to-end           | 100건 미니 샘플 + seed=42 → 크래시 없이 완주  |
| Integration | 출력 스키마                     | anomaly_score(0~1), risk_level(str) 컬럼 존재 |

- Unit 테스트: ML 모델은 Mock으로 대체, 비즈니스 로직만 검증
- Integration 테스트: random_state=42 고정, "에러 없이 결과물이 나오는가"만 검증
- 성능(F1/AUPRC) 측정은 별도 벤치마크 스크립트로 분리 (테스트 스위트에 포함하지 않음)
