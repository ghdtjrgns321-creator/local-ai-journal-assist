# 03a. 전처리 전략 (Preprocessing) [Phase 1a + 2 — 의존: 02, 03]

## 목적
전체 전처리 파이프라인의 전략을 정의한다.
**ingest**(원시→표준 DataFrame)와 **preprocessing**(표준→ML-ready)의 경계를 명확히 구분하고,
Phase별로 전처리 범위·구현 방식·UX 투명성을 계획한다.

> **핵심 원칙: White Box 전처리**
> 사용자가 전처리 전후를 대시보드 EDA 탭에서 확인하고, 각 단계의 판단 근거를 투명하게 볼 수 있어야 한다.

### ingest vs preprocessing 구분

| 구분           | ingest (02-ingest)                       | preprocessing (본 문서)                     |
|:---------------|:-----------------------------------------|:-------------------------------------------|
| **변환 방향**  | 원시 파일 → 표준 DataFrame               | 표준 DataFrame → ML-ready DataFrame        |
| **대상**       | 헤더 탐지, 컬럼 매핑, 타입 캐스팅        | 결측치 처리, 인코딩, 스케일링, 불균형 처리  |
| **시점**       | 파일 업로드 직후 (1회)                    | 모델 학습/추론 직전 (모델별 다를 수 있음)   |
| **Phase**      | Phase 1a ✅                               | EDA: Phase 1a / ML Pipeline: Phase 2       |
| **UX 단계**    | UX 1단계 (수집 투명성)                    | UX 3단계 (전처리 투명성)                    |

---

## 데이터 흐름

```
[사용자 파일 업로드]
       ↓
ingest (02) → 표준 DataFrame (타입 캐스팅 완료)
       ↓
feature (03) → 15개 파생변수 추가
       ↓
① EDA 프로파일링 (profiler.py)        → EDAProfile(JSON)
       ↓
② EDA 리포트 (report.py)              → 대시보드용 요약
       ↓
validation (04) → L1 구조 / L2 회계 검증
       ↓
detection (05) → 3레이어 22개 룰 탐지 (Phase 1b)
       ↓
  ┌──────────────────────────────────────────────────┐
  │ Phase 2: sklearn Pipeline                        │
  │ ③ 전처리(결측치/인코딩/스케일링) + 모델 번들링   │
  │ ④ GridSearchCV로 Pipeline 비교 선택              │
  └──────────────────────────────────────────────────┘
       ↓
  ┌──────────────────────────────────────────────────┐
  │ Phase 3: LLM 전처리 제안                         │
  │ ⑤ EDAProfile(JSON) → Ollama(Qwen3-8B)           │
  │    → 전처리 전략 추천                             │
  └──────────────────────────────────────────────────┘
```

**핵심 포인트 — 닭-달걀 해결:**
Phase 1에서는 전처리를 분리하지 않는다. Phase 2에서 sklearn Pipeline으로
전처리+모델을 번들링하면 "어떤 전처리가 최적인가?"를 모델과 함께 실험할 수 있다.

---

## 구현 상태 & 모듈별 가이드

### ① EDA 프로파일링 — ✅ 구현 완료 (Phase 1a)

```
src/eda/
├── __init__.py          # 퍼블릭 API 재익스포트
├── models.py            # EDAProfile, ColumnProfile dataclass
├── type_classifier.py   # dtype → 4분류 (numeric/categorical/datetime/boolean)
├── numeric_profiler.py  # mean/std/IQR/outlier (Tukey's fence)
├── category_profiler.py # cardinality/top_values
├── datetime_profiler.py # min/max/range/요일·월별 분포
├── boolean_profiler.py  # true_rate
├── profiler.py          # 오케스트레이터 + profile_to_dict
└── report.py            # summarize_for_dashboard (quality_score, warnings)
```

**테스트**: [52 tests passed](../../tests/test_eda/test-results/eda-profiling.md) — 7개 테스트 파일

**프로파일링 항목:**

#### 전체 수준

| 항목         | 산출 방법                    | 용도                          |
|:-------------|:-----------------------------|:------------------------------|
| 행 수        | `len(df)`                    | 데이터 규모 파악              |
| 컬럼 수      | `len(df.columns)`           | 스키마 확인                   |
| 메모리       | `df.memory_usage(deep=True)` | 리소스 제약 판단              |
| 중복행 수    | `df.duplicated().sum()`      | 데이터 품질 (A02 연계)        |

#### 컬럼별 공통

| 항목       | 산출 방법           | 용도                                    |
|:-----------|:-------------------|:----------------------------------------|
| dtype      | `df[col].dtype`    | 타입 확인                                |
| 결측률     | `isna().mean()`    | 결측치 처리 전략 결정                     |
| 유니크 수  | `nunique()`        | 카디널리티 파악 → 인코딩 전략 결정        |
| 최빈값     | `mode()`           | 범주형 분포 이해                          |

#### 수치형 컬럼 추가

| 항목       | 산출 방법                      | 용도                                |
|:-----------|:------------------------------|:------------------------------------|
| mean       | `df[col].mean()`              | 중심 경향                            |
| median     | `df[col].median()`            | 왜도 보정 중심값                     |
| std        | `df[col].std()`               | 변동성                               |
| skewness   | `df[col].skew()`              | 분포 비대칭 → 로그변환 필요 판단     |
| kurtosis   | `df[col].kurtosis()`          | 꼬리 두께 → 이상치 민감도            |
| Q1/Q3/IQR  | `df[col].quantile([.25,.75])` | IQR 기반 이상치 탐지                 |
| 이상치 수  | `IQR × 1.5` 범위 벗어난 수    | 이상치 규모 파악                     |
| min/max    | `min()`, `max()`              | 값 범위                              |

#### 범주형 컬럼 추가

| 항목           | 산출 방법                        | 용도                                    |
|:---------------|:--------------------------------|:----------------------------------------|
| 카디널리티     | `nunique()`                     | 고카디널리티 → TargetEncoder 필요 판단   |
| 상위 10개 값   | `value_counts().head(10)`       | 분포 편중 파악                           |
| 분포           | 상위 10개의 비율                 | 불균형 판단                              |

**설계 결정:**

| 항목                      | 결정                                                              |
|:--------------------------|:------------------------------------------------------------------|
| 반환 타입                 | JSON-serializable dict (EDAProfile) — 대시보드/LLM 양쪽에서 사용  |
| 대용량 대응               | 100만행 이상 시 샘플링(10만행) + 전체 통계 병행                    |
| 프로파일링 라이브러리     | 직접 구현 (pandas 기본 API) — ydata-profiling 의존성 회피          |
| 이상치 기준               | IQR × 1.5 (Tukey's fence) — 감사 도메인 표준                     |
| Phase 3 연동              | EDAProfile(JSON) → LLM 프롬프트 입력으로 직접 전달 가능            |
| 성능 목표                 | 0.5초 이내 (100만행 기준, 샘플링 포함) — B2B 파이프라인 응답성 확보 |
| LLM 해석 필드 분리        | profiler는 raw 측정값만 반환. 해석 필드(is_highly_skewed 등)는 Phase 3에서 별도 변환 함수(profile_to_llm_context)로 추가 — 판정 기준 변경 시 profiler 수정 불필요 |

**report.py — EDAProfile → 대시보드 요약:**
- `profiler.py`의 EDAProfile(dict/JSON)을 대시보드에서 렌더링 가능한 형태로 변환
- 컬럼별 요약 카드, 전체 데이터 품질 점수 등
- Phase 1c 대시보드 EDA 탭의 데이터 소스

---

### ② sklearn Pipeline 전처리 — ✅ 구현 완료 (Phase 2)

> 상세 구현 계획: [Plan 파일](../../.claude/plans/reactive-moseying-scroll.md)

#### 모듈 구조

```
src/preprocessing/
├── __init__.py              # 퍼블릭 API
├── feature_groups.py        # EDAProfile 기반 피처 자동 분류
├── transformers.py          # 커스텀 Transformer + PowerTransformer 래퍼
├── pipeline_builder.py      # ColumnTransformer + Pipeline 조립
├── vae_model.py             # PyTorch VAE 네트워크
├── vae_wrapper.py           # VAE sklearn BaseEstimator 래퍼
├── cv_selector.py           # Pipeline 비교 + GridSearchCV (StratifiedKFold)
├── label_strategy.py        # 라벨 전략 (DataSynth/pseudo/hybrid)
├── transparency.py          # 전처리 전/후 메타데이터
├── explainer.py             # SHAP 기반 XAI 피처 기여도
└── model_registry.py        # Pipeline 직렬화/버전 관리 (joblib)
```

#### 전처리 매핑 — 지도/비지도 분기

**핵심: 비지도 모델(IF, VAE)은 타겟(y)이 없으므로 TargetEncoder 사용 불가.**

```
+-----------------+-------------------------------+-------------------------------+
| 그룹            | XGBoost (지도)                | VAE / IF (비지도)             |
+-----------------+-------------------------------+-------------------------------+
| numeric         | SimpleImputer(median)         | SimpleImputer(median)         |
|                 |                               | + PowerTransformer(Yeo-Johnson)|
|                 |                               | + StandardScaler              |
| categorical_high| SimpleImputer(most_frequent)  | **DROP** (제외)               |
|                 | + TargetEncoder (sklearn 1.3) | 고카디널리티는 트리 깊이만    |
|                 |                               | 깊어지고 이상치 탐지 방해     |
| categorical_low | SimpleImputer(most_frequent)  | SimpleImputer(most_frequent)  |
|                 | + OrdinalEncoder(unknown=-1)  | + OrdinalEncoder(unknown=-1)  |
| boolean         | passthrough                   | passthrough                   |
| ordinal         | OrdinalEncoder(수동 카테고리) | OrdinalEncoder                |
+-----------------+-------------------------------+-------------------------------+
```

#### 핵심 설계 결정

| 항목                       | 결정                                                                           |
|:---------------------------|:------------------------------------------------------------------------------|
| 지도/비지도 인코딩 분기     | XGBoost=TargetEncoder / IF·VAE=고카디널리티 DROP (y 부재 + 차원 폭발 방지)     |
| 우측 꼬리 분포 대응         | VAE·IF에 PowerTransformer(Yeo-Johnson) → StandardScaler 순서 적용              |
| 교차 검증 분할              | **StratifiedKFold** 필수 (이상 전표 1% 미만 → KFold 시 특정 Fold 양성 0건 위험) |
| 전처리+모델 번들링          | sklearn Pipeline — 전처리를 모델과 함께 실험 (닭-달걀 해결)                     |
| 불균형 대응                 | class_weight='balanced' / XGBoost는 scale_pos_weight. SMOTE 초기 제외          |
| TargetEncoder 누출 방지     | sklearn ≥1.3 내부 cross-fitting 적용 (XGBoost Pipeline에서만 사용)              |
| XAI (설명 가능성)           | SHAP — XGBoost=TreeExplainer / VAE·IF=KernelExplainer (on-demand)             |
| 모델 직렬화                 | joblib.dump (sklearn) + torch.save (VAE) → models/ 디렉토리                   |

#### GridSearchCV Pipeline 비교

**동일 데이터 → 각 Pipeline cross_val_score(StratifiedKFold) → F1/AUC 비교 → 최적 Pipeline 자동 선택.**
sklearn Pipeline이 전처리+모델을 하나의 단위로 묶으므로, "어떤 전처리가 최적인가?"를 모델과 함께 실험 가능.

---

### ③ LLM 전처리 제안 — ✅ 구현 완료 (Phase 3, 70 tests passed)

```
EDAProfile(JSON) → profile_to_llm_context() → build_preprocessing_prompt()
  → Ollama(Qwen3-8B, Structured Output) → PreprocessingAdvice(Pydantic)
  → to_pipeline_config(model_group="tree"|"distance") → sklearn Pipeline 구성 dict
```

**구현 모듈:**

```
src/llm/
├── models.py                  # Pydantic 응답 스키마 (StrEnum 5종 + ModelGroupStrategy)
├── ollama_client.py           # Ollama API 래퍼 (format=JSON Schema 지원)
├── prompt_templates.py        # EDAProfile → 해석 플래그 추가 → 프롬프트 생성
└── preprocessing_advisor.py   # 오케스트레이터 (LLM 호출 + 규칙 기반 폴백)
```

**핵심 설계 결정:**

| 항목                         | 결정                                                             |
|:-----------------------------|:-----------------------------------------------------------------|
| Structured Output            | `format=model_json_schema()` → 파싱 실패율 최소화               |
| 모델 그룹별 전략             | `tree_model`/`distance_model` 분기 → 1회 LLM 호출로 전략 동시 수령 |
| 매직 넘버 외부화             | `config/settings.py`의 `heuristic_*` 5개 설정으로 관리           |
| Graceful Degradation         | Ollama 미실행 시 `rule_based_fallback()` 자동 전환               |
| 재시도                       | 1회 (총 2회). Structured Output으로 안정성 확보                  |

**판정 기준 (settings.py에서 조정 가능):**

| 설정                                   | 기본값 | 용도                        |
|:---------------------------------------|:-------|:----------------------------|
| `heuristic_skewness_threshold`         | 2.0    | 고왜도 → median imputation  |
| `heuristic_outlier_rate_threshold`     | 0.10   | 다수 이상치 → robust scaler |
| `heuristic_high_cardinality_threshold` | 50     | 고카디널리티 → target encoder |
| `heuristic_imbalance_threshold`        | 0.05   | 불균형 → smote              |
| `heuristic_missing_rate_threshold`     | 0.10   | 고결측 판정 플래그          |

**하드웨어 제약 (RTX 3070 Ti 8GB):**

| 작업                     | VRAM 사용        | 대응 전략                     |
|:-------------------------|:----------------|:------------------------------|
| Qwen3-8B (Q4_K_M)       | ~5GB            | 단독 실행 시 여유             |
| VAE 학습                 | ~2GB            | 단독 실행 시 여유             |
| LLM + VAE 동시           | ~7GB → 위험     | **순차 실행** (LLM → 종료 → VAE) |

> LLM 추천 → 사용자 확인 → Pipeline 재실행의 순차 워크플로우로 설계하면 VRAM 충돌 없이 운영 가능.

**테스트 결과:** [tests/test_llm/test-results/llm-preprocessing-advisor.md](../../tests/test_llm/test-results/llm-preprocessing-advisor.md)

---

## 구현 순서

1. `profiler.py` (EDAProfile — DataFrame → JSON 프로파일) ✅ Phase 1a
2. `report.py` (대시보드용 요약 변환) ✅ Phase 1a
3. 대시보드 EDA 탭 (시각화) ⬜ Phase 1c
4. `feature_groups.py` + `transformers.py` (피처 분류 + 커스텀 변환) ✅ Phase 2
5. `pipeline_builder.py` (3개 Pipeline 조립 — 지도/비지도 분기) ✅ Phase 2
6. `vae_model.py` + `vae_wrapper.py` (VAE sklearn 래퍼) ✅ Phase 2
7. `label_strategy.py` (DataSynth/pseudo/hybrid 라벨) ✅ Phase 2
8. `cv_selector.py` (StratifiedKFold 비교 선택) ✅ Phase 2
9. `transparency.py` (전처리 전/후 비교 메타데이터) ✅ Phase 2
10. `explainer.py` (SHAP XAI 기여도) ✅ Phase 2
11. `model_registry.py` (Pipeline 직렬화/버전 관리) ✅ Phase 2
12. 전처리 전/후 비교 시각화 + 옵션 변경 UI ⬜ Phase 2
13. LLM(Ollama) EDA→전처리 전략 제안 ⬜ Phase 3

## 의존성

- **선행:**
  - `02-ingest` (표준 DataFrame — 타입 캐스팅 완료)
  - `03-feature` (18개 파생변수 추가된 DataFrame)
- **외부 패키지:**
  - Phase 1a: `pandas`, `numpy` (EDA 프로파일링 — 추가 설치 불필요)
  - Phase 2: `scikit-learn` (Pipeline, GridSearchCV — ml 그룹)
  - Phase 3: `ollama` (LLM — llm 그룹)
- **후행:**
  - `04-validation` (EDA 프로파일링 결과를 L1/L2 검증과 함께 활용)
  - `05-detection` (Phase 2 Pipeline의 모델이 detection 트랙으로 등록)
  - `07-dashboard` (EDA 탭에서 프로파일링 결과 시각화)

## Phase 구분

| 항목                                              | Phase                |
|:--------------------------------------------------|:---------------------|
| EDA 프로파일링 모듈 (src/eda/profiler.py, report.py) | MVP (Phase 1a)     |
| 대시보드 EDA 탭 (시각화)                           | MVP (Phase 1c)       |
| sklearn Pipeline 전처리+모델 번들링                 | Phase 2              |
| GridSearchCV Pipeline 비교 선택 (StratifiedKFold)  | Phase 2              |
| SHAP XAI 피처 기여도                               | Phase 2              |
| Pipeline 직렬화/모델 레지스트리                     | Phase 2              |
| 수치 컬럼 상관관계 분석 (pearson/spearman)          | Phase 2              |
| 전처리 전/후 비교 시각화 + 옵션 변경 UI            | Phase 2              |
| LLM(Ollama) EDA→전처리 전략 제안                   | Phase 3              |

## Feature 엔진 E2E 테스트 결과

| 데이터셋   | 링크                                                                          | 피처 생성 | 비고                                        |
|:-----------|:------------------------------------------------------------------------------|:---------:|:--------------------------------------------|
| DataSynth  | [e2e-datasynth.md](../../tests/test_feature/test-results/e2e-datasynth.md)    |     18/18 | 전 카테고리 정상                            |
| SAP-Merged | [e2e-sap-merged.md](../../tests/test_feature/test-results/e2e-sap-merged.md) |     13/18 | amount 카테고리 스킵 (Graceful Degradation) |

---

## 테스트 전략

- **profiler.py:** 수치/범주/시간형 컬럼별 프로파일링 + 대용량 샘플링 동작 검증 ✅ (52 tests)
- **report.py:** EDAProfile → 대시보드 요약 변환 + JSON 직렬화 ✅
- **feature_groups.py:** EDAProfile → 6그룹 자동 분류 정확성 ✅ (10 tests)
- **transformers.py:** NullFlagTransformer + SafePowerTransformer fit/transform ✅ (8 tests)
- **pipeline_builder.py:** 지도/비지도 Pipeline build + fit/predict ✅ (6 tests)
- **cv_selector.py:** StratifiedKFold 기반 compare_pipelines 동작 ✅ (7 tests)
- **vae_wrapper.py:** VAE sklearn 호환성 + 직렬화 ✅ (8 tests)
- **label_strategy.py:** DataSynth/pseudo/hybrid 3가지 전략 + 폴백 ✅ (9 tests)
- **transparency.py:** 전처리 메타데이터 생성 ✅ (4 tests)
- **model_registry.py:** save/load/list + 버전 관리 ✅ (10 tests)
- **LLM 전처리 제안:** 프롬프트 → JSON 파싱 + 유효한 전처리 옵션 검증 ⬜

---

## 부록: API 레퍼런스

<details>
<summary>클릭하여 상세 함수 시그니처 보기</summary>

### profiler.py
```python
@dataclass
class EDAProfile:
    """DataFrame 프로파일링 결과. JSON 직렬화 가능."""
    total_rows: int
    total_columns: int
    memory_bytes: int
    duplicate_rows: int
    columns: dict[str, ColumnProfile]  # {컬럼명: 컬럼 프로파일}

@dataclass
class ColumnProfile:
    """컬럼별 프로파일링 결과."""
    name: str
    dtype: str
    missing_rate: float          # 0.0~1.0
    unique_count: int
    mode: str | None
    # 수치형 전용
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    outlier_count: int | None = None
    min_val: float | None = None
    max_val: float | None = None
    # 범주형 전용
    cardinality: int | None = None
    top_values: list[tuple[str, int]] | None = None  # [(값, 빈도)]

def profile_dataframe(df: pd.DataFrame) -> EDAProfile:
    """DataFrame → EDAProfile. 대용량 시 자동 샘플링."""

def profile_to_dict(profile: EDAProfile) -> dict:
    """EDAProfile → JSON-serializable dict."""

def summarize_for_dashboard(profile: EDAProfile) -> dict:
    """대시보드 렌더링용 요약 생성."""
```

### sklearn Pipeline (Phase 2)
```python
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OrdinalEncoder, PowerTransformer, TargetEncoder
from sklearn.impute import SimpleImputer
from sklearn.model_selection import cross_val_score, StratifiedKFold

# --- 공통 전처리 블록 ---
# 범주형 (저카디널리티)
cat_low_transformer = Pipeline([
    ("imputer", SimpleImputer(strategy="most_frequent")),
    ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
])

# --- Pipeline 1: XGBoost (지도학습 — TargetEncoder 사용) ---
pipeline_xgb = Pipeline([
    ("preprocessor", ColumnTransformer([
        ("num", SimpleImputer(strategy="median"), numeric_cols),
        ("cat_high", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", TargetEncoder(smooth="auto")),  # 지도학습만 사용
        ]), high_card_cols),
        ("cat_low", cat_low_transformer, low_card_cols),
        ("bool", "passthrough", boolean_cols),
    ])),
    ("classifier", XGBClassifier(eval_metric="logloss", scale_pos_weight=ratio)),
])

# --- Pipeline 2: VAE (비지도 — 고카디널리티 DROP + PowerTransformer) ---
pipeline_vae = Pipeline([
    ("preprocessor", ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("power", PowerTransformer(method="yeo-johnson")),  # 우측 꼬리 분포 대응
            ("scaler", StandardScaler()),
        ]), numeric_cols),
        # categorical_high: DROP (ColumnTransformer에 포함하지 않음)
        ("cat_low", cat_low_transformer, low_card_cols),
        ("bool", "passthrough", boolean_cols),
    ])),
    ("detector", VAEDetector()),
])

# --- Pipeline 3: Isolation Forest (비지도 — 동일 구조) ---
pipeline_if = Pipeline([
    ("preprocessor", ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("power", PowerTransformer(method="yeo-johnson")),
            ("scaler", StandardScaler()),
        ]), numeric_cols),
        ("cat_low", cat_low_transformer, low_card_cols),
        ("bool", "passthrough", boolean_cols),
    ])),
    ("detector", IsolationForest(contamination=0.01, random_state=42)),
])

# --- Pipeline 비교 (StratifiedKFold 필수) ---
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
pipelines = {"xgb": pipeline_xgb, "vae": pipeline_vae, "if": pipeline_if}
results = {}
for name, pipe in pipelines.items():
    scores = cross_val_score(pipe, X, y, cv=skf, scoring="f1_macro")
    results[name] = {"mean_f1": scores.mean(), "std_f1": scores.std()}
best_pipeline = max(results, key=lambda k: results[k]["mean_f1"])
```

</details>

---

## UX 3단계: 전처리 투명성

> **UX 단계 정의**: [ux-flow.md](ux-flow.md) 참조
> - UX 1단계 = 데이터 수집 투명성 (Ingest) ✅
> - UX 2단계 = 감사 룰 세팅 & 파생변수 생성 (Feature) ✅ 엔진 / ⬜ UI
> - **UX 3단계 = 전처리 투명성 & EDA (본 문서)**

### UX 단계 대비

| 항목           | UX 1단계 (수집 투명성) ✅                | UX 2단계 (룰 세팅) ✅ 엔진              | UX 3단계 (전처리 투명성) ⬜              |
|:---------------|:----------------------------------------|:----------------------------------------|:----------------------------------------|
| **Phase**      | Phase 1a                                | Phase 1a(엔진) + 1c(UI)                | Phase 1a(EDA) ~ 1c(시각화) ~ 2(ML)     |
| **대상**       | 헤더 탐지, 컬럼 매핑, 타입 캐스팅       | 감사 룰 설정, 18개 파생변수 생성         | EDA 결과, 결측치/인코딩/스케일링 처리    |
| **투명성 모델** | ReviewItem (action, confidence, reason) | audit_rules.yaml + settings + profile   | EDAProfile(JSON) + Pipeline 설정 노출    |
| **사용자 역할** | 매핑 확인/변경 (3-tier UI)              | 감사 기준 세팅 (Control Panel)           | EDA 확인 + 전처리 옵션 선택/변경         |
| **구현 파일**   | models.py:ReviewItem                    | feature/engine.py + audit_rules.yaml    | src/eda/profiler.py + dashboard EDA 탭   |

### 핵심 원칙

[ux-flow.md 3가지 UX 디자인 원칙](ux-flow.md#3가지-ux-디자인-원칙)을 본 단계에도 적용:

1. **스마트 디폴트**: 전처리 옵션 자동 선택 (결측치→중앙값, 스케일링→StandardScaler)
2. **점진적 공개**: EDA 요약만 기본 노출, Pipeline 상세 옵션은 접이식 패널
3. **프로파일 재사용**: Pipeline 설정 프로파일 저장 → 동일 데이터셋 재분석 시 자동 적용
4. **EDA 결과 시각화**: 데이터 현황(분포, 결측률, 이상치)을 대시보드에서 확인
5. **전처리 과정 확인**: 각 단계(결측치 처리, 인코딩, 스케일링)의 방법과 근거 노출
6. **사용자 선택 가능**: 기본값 자동 적용 + 변경 옵션 제공
   - 예: "결측치 처리: 중앙값 대체 [변경]" / "스케일링: StandardScaler [변경]"

### 대시보드 EDA 탭 UI 개요 (Phase 1c 시각화)

```
┌─────────────────────────────────────────────────┐
│ EDA 탭                                          │
├─────────────────────────────────────────────────┤
│ [데이터 개요]                                    │
│   행: 1,068,000 | 컬럼: 24 | 메모리: 196MB      │
│   중복행: 0 | 결측률: 2.3%                       │
│                                                  │
│ [컬럼별 프로파일]                                 │
│   ┌──────────────────────────────────────┐       │
│   │ debit_amount (float64)               │       │
│   │ 결측: 0.1% | min: 0 | max: 9.9B     │       │
│   │ mean: 2.1M | std: 15.3M             │       │
│   │ skew: 8.7 | kurtosis: 102.3         │       │
│   │ [히스토그램]  [박스플롯]              │       │
│   └──────────────────────────────────────┘       │
│                                                  │
│ [결측률 히트맵]  [이상치 분포]                     │
│                                                  │
│ Phase 2: [전처리 설정 패널]                       │
│   결측치: 수치→중앙값, 범주→최빈값 [변경]         │
│   스케일링: StandardScaler [변경]                 │
│   [재실행]                                        │
└─────────────────────────────────────────────────┘
```

### Phase 2 UX 연동 (대시보드)

- **전처리 전/후 데이터 비교**: 원본 분포 vs 전처리 후 분포 (히스토그램 오버레이)
- **Pipeline별 성능 비교 차트**: F1/AUC 바 차트 + 신뢰구간
- **전처리 옵션 변경 UI**: 사용자가 imputer/scaler/encoder 옵션을 변경하고 재실행 가능
- **SHAP 시각화**: 최적 Pipeline의 피처 중요도 (Phase 2 detection과 연계)

---

## 구현 시 주의사항

- **EDA 프로파일링은 pandas 기본 API만 사용:** ydata-profiling 등 외부 프로파일링 라이브러리 의존성 회피.
  직접 구현이 커스터마이징과 JSON 직렬화에 유리.
- **대용량 DataFrame 대응:** 100만행 이상 시 통계 샘플링(10만행) + 전체 집계(행수, 결측률) 병행.
  `df.sample(n=100_000, random_state=42)` 사용.
- **Pipeline 전처리는 Phase 2에서:** Phase 1a에서는 EDA 프로파일링만 구현.
  결측치/인코딩/스케일링은 sklearn Pipeline에 포함하여 모델과 함께 실험.
- **TargetEncoder 누출 방지:** sklearn ≥1.3의 TargetEncoder는 내부적으로 cross-fitting 적용.
  수동 구현 시 반드시 fold 분리 필요.
- **VRAM 순차 실행:** Phase 3에서 LLM과 VAE를 동시에 실행하지 않도록 파이프라인 설계.
  RTX 3070 Ti 8GB 제약.
- **EDAProfile JSON 호환:** Phase 3 LLM 프롬프트에 직접 주입 가능하도록
  모든 값을 JSON-serializable 타입(int, float, str, list, dict)으로 제한.
  numpy int64/float64 → Python 네이티브 변환 필수.
