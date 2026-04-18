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
feature (03) → 18개 파생변수 추가
       ↓
① EDA 프로파일링 (profiler.py)        → EDAProfile(JSON)
       ↓
② EDA 리포트 (report.py)              → 대시보드용 요약
       ↓
validation (04) → L1 구조 / L2 회계 검증
       ↓
detection (05) → 3레이어 24개 룰 탐지 (Phase 1b)
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

> **⚠️ Phase 2 착수 전 필수 논의: 데이터 분할 전략**
> train/validation/test split 비율, 분할 시점(pipeline 흐름 내 위치), holdout test set 관리 정책,
> DataSynth(라벨 있음) vs 실무 데이터(라벨 없음)의 분할 전략 차이를 사전에 정의해야 한다.

---

## 구현 상태 & 모듈별 가이드

### ① EDA 프로파일링 — ✅ 구현 완료 (Phase 1a)

#### 이 모듈이 하는 일

ingest가 완료된 표준 DataFrame을 받아 **컬럼별 통계 프로파일(EDAProfile)**을 JSON 형태로 산출한다.
이 프로파일은 이후 모든 전처리 판단의 근거 데이터가 된다.

```
문제:
  결측치를 중앙값으로 채울지, 평균으로 채울지 판단하려면 분포를 알아야 한다.
  인코딩 방식(OrdinalEncoder vs TargetEncoder)도 카디널리티를 보고 결정해야 한다.
  → 전처리 전략을 세우려면 데이터 현황 파악이 선행되어야 한다.

해결:
  profiler.py가 수치형(mean/std/skew/IQR/이상치), 범주형(카디널리티/top_values),
  시간형(min/max/요일분포), 불린형(true_rate)을 자동 측정하여 EDAProfile로 반환한다.
  이 프로파일을 Phase 1c 대시보드(EDA 탭), Phase 2 Pipeline(feature_groups),
  Phase 3 LLM(전처리 제안 프롬프트)이 공통으로 소비한다.
```

3가지 역할을 수행한다:

**1) 데이터 현황 자동 측정 (profiler.py)**

DataFrame을 입력받아 행 수, 컬럼 수, 메모리, 중복행 등 전체 수준 통계와
컬럼별 dtype·결측률·유니크 수·분포 통계를 산출한다.
100만행 이상 시 자동 샘플링(10만행)하여 성능을 보장한다.

**2) 대시보드 요약 변환 (report.py)**

EDAProfile(JSON)을 대시보드 렌더링에 적합한 형태로 변환한다.
데이터 품질 점수, 경고 목록 등 사용자가 한눈에 파악할 수 있는 요약을 생성한다.

**3) 후속 모듈의 공통 입력 제공**

EDAProfile은 JSON-serializable하므로 Phase 2 feature_groups.py(컬럼 자동 분류),
Phase 3 LLM 프롬프트(전처리 전략 추천) 등이 동일한 프로파일을 재사용한다.
프로파일링을 각 모듈에서 중복 구현하지 않아도 된다.

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

#### 이 모듈이 하는 일

표준 DataFrame을 ML 모델이 소비할 수 있는 형태로 변환하되,
**전처리와 모델을 하나의 Pipeline으로 번들링**하여 실험·배포를 단순화한다.

```
문제:
  결측치 처리→인코딩→스케일링을 모델과 분리하면 "닭-달걀 문제"가 발생한다.
  어떤 전처리가 최적인지는 모델 성능을 봐야 알 수 있고,
  모델을 학습하려면 전처리가 먼저 완료되어야 한다.
  전처리와 모델을 따로 관리하면 data leakage 위험도 증가한다.

해결:
  sklearn Pipeline이 전처리+모델을 하나의 단위로 묶는다.
  GridSearchCV로 Pipeline 단위 비교(XGB/VAE/IF)를 수행하면
  "어떤 전처리+모델 조합이 최적인가?"를 데이터 기반으로 결정할 수 있다.
  cross-validation 내부에서 전처리가 실행되므로 data leakage도 자동 방지된다.
```

핵심 구성요소:

**1) 컬럼 자동 분류 (feature_groups.py)**

EDAProfile을 입력받아 수치형·범주형·시간형·불린형·고카디널리티·ID성 컬럼을
6그룹으로 자동 분류한다. 이 분류 결과가 ColumnTransformer의 입력이 된다.

**2) 모델별 Pipeline 조립 (pipeline_builder.py)**

XGBoost(스케일링 불필요), VAE(StandardScaler 필수), IF(StandardScaler 필수) 등
모델 특성에 맞는 전처리 단계를 자동 조합하여 Pipeline 객체를 생성한다.

**3) Pipeline 비교 선택 (cv_selector.py)**

동일 데이터에 대해 각 Pipeline의 cross_val_score(F1/AUC)를 비교하고
최적 Pipeline을 자동 선택한다. GridSearchCV로 하이퍼파라미터 튜닝도 수행한다.

**4) 전처리 투명성 (transparency.py)**

전처리 전/후 데이터를 비교하는 메타데이터를 생성하여
대시보드에서 사용자가 각 단계의 변환 내용을 확인할 수 있도록 한다.

**5) XAI 기여도 (explainer.py)**

SHAP으로 최적 Pipeline의 피처 중요도를 산출하여
탐지 결과의 해석 가능성을 확보한다.

```
src/preprocessing/
├── __init__.py            # 퍼블릭 API 재익스포트
├── feature_groups.py      # EDAProfile → 6그룹 자동 분류
├── transformers.py        # NullFlagTransformer, SafePowerTransformer
├── pipeline_builder.py    # XGB/VAE/IF Pipeline 조립
├── vae_model.py           # AuditVAE PyTorch 네트워크
├── vae_wrapper.py         # VAEDetector sklearn 래퍼
├── label_strategy.py      # 3가지 라벨 전략 (datasynth/pseudo/hybrid)
├── cv_selector.py         # StratifiedKFold Pipeline 비교 + GridSearchCV
├── transparency.py        # 전처리 전/후 비교 메타데이터
├── explainer.py           # SHAP XAI 기여도
└── model_registry.py      # Pipeline 직렬화/버전 관리
```

**테스트**: [62 tests passed](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) — 8개 테스트 파일, 11개 구현 모듈

#### 전처리 단계 정의

| 단계             | 수치형 컬럼                   | 범주형 컬럼                      | 시간형 컬럼           |
|:-----------------|:-----------------------------|:---------------------------------|:---------------------|
| **결측치**       | 중앙값 대체 (SimpleImputer)   | 최빈값 대체 (SimpleImputer)       | forward fill         |
| **인코딩**       | —                            | gl_account → TargetEncoder        | —                    |
|                  |                              | bool → passthrough                |                      |
|                  |                              | 저카디널리티 → OrdinalEncoder     |                      |
| **스케일링**     | XGBoost → 불필요              | —                                | —                    |
|                  | VAE/IF → StandardScaler      |                                  |                      |
| **불균형**       | SMOTE / class_weight='balanced' | —                             | —                    |
| **구간화** (선택) | amount_magnitude → 구간 범주  | —                                | —                    |

> **gl_account 고카디널리티 처리:**
> 계정코드(414개 사용/431개 정의)는 OneHotEncoder 시 차원 폭발 → TargetEncoder 사용.
> TargetEncoder는 타겟 누출 방지를 위해 cross-fitting 적용 (sklearn 기본).

#### 모델별 Pipeline 정의

**구현할 것:**
- Pipeline 1 (XGBoost): 수치 imputer + 범주 imputer/encoder → `XGBClassifier`
- Pipeline 2 (VAE): 수치 imputer/**scaler** + 범주 imputer/encoder → `VAEDetector`
- Pipeline 3 (Isolation Forest): 수치 imputer/**scaler** + 범주 imputer/encoder → `IsolationForest`

**설계 결정:**

| 항목                      | 결정                                                                   |
|:--------------------------|:----------------------------------------------------------------------|
| 전처리+모델 번들링        | sklearn Pipeline — 전처리를 모델과 함께 실험 (닭-달걀 해결)            |
| 모델 선택 방식            | cross_val_score (cv=5, scoring="f1_macro") → Pipeline 비교             |
| scaler 분기               | XGBoost=불필요 / VAE·IF=StandardScaler 필수                           |
| TargetEncoder 누출 방지   | sklearn ≥1.3 내부 cross-fitting 적용                                   |
| 불균형 대응               | SMOTE 또는 class_weight='balanced' (데이터 특성에 따라 선택)           |

#### GridSearchCV Pipeline 비교

**동일 데이터 → 각 Pipeline cross_val_score → F1/AUC 비교 → 최적 Pipeline 자동 선택.**
sklearn Pipeline이 전처리+모델을 하나의 단위로 묶으므로, "어떤 전처리가 최적인가?"를 모델과 함께 실험 가능.

---

### ③ LLM 전처리 제안 — ✅ 구현 완료 (Phase 3)

#### 이 모듈이 하는 일

EDAProfile(JSON)을 LLM에 입력하여 **데이터 특성에 맞는 전처리 전략을 자연어+JSON으로 추천**받는다.
사용자가 전처리 옵션을 직접 선택하지 않아도 데이터 기반 제안을 받을 수 있다.

```
문제:
  Phase 2 Pipeline은 전처리 옵션(imputer, scaler, encoder)의 조합을 실험할 수 있지만,
  "왜 이 옵션이 적절한지"에 대한 설명은 제공하지 않는다.
  비전문 사용자는 skewness=8.7인 컬럼에 로그변환이 필요한지 판단하기 어렵다.
  전처리 옵션이 많아질수록 수동 선택의 인지 부하가 증가한다.

해결:
  EDAProfile(JSON)을 Ollama(Qwen3-8B)에 전달하면,
  LLM이 컬럼별 결측치 전략, 인코딩 방식, 스케일링 방법, 이상치 처리를
  데이터 특성(분포, 카디널리티, 결측률)에 근거하여 추천하고 이유를 설명한다.
  추천 결과는 JSON으로 반환되어 Pipeline 옵션으로 자동 변환 가능하다.
```

```
EDAProfile(JSON) → 프롬프트 템플릿 → Ollama(Qwen3-8B) → 전처리 추천(JSON)
```

**프롬프트 설계:**
- 입력: EDAProfile(JSON) — profiler.py 결과 직접 주입
- 추천 항목: 결측치(컬럼별), 인코딩(범주형 컬럼별), 스케일링, 이상치 처리, 불균형 대응
- 출력: JSON 형식 → Pipeline 옵션으로 자동 변환

**하드웨어 제약 (RTX 3070 Ti 8GB):**

| 작업                     | VRAM 사용        | 대응 전략                     |
|:-------------------------|:----------------|:------------------------------|
| Qwen3-8B (Q4_K_M)       | ~5GB            | 단독 실행 시 여유             |
| VAE 학습                 | ~2GB            | 단독 실행 시 여유             |
| LLM + VAE 동시           | ~7GB → 위험     | **순차 실행** (LLM → 종료 → VAE) |

> LLM 추천 → 사용자 확인 → Pipeline 재실행의 순차 워크플로우로 설계하면 VRAM 충돌 없이 운영 가능.

---

## 구현 순서

1. `profiler.py` (EDAProfile — DataFrame → JSON 프로파일) ✅ Phase 1a
2. `report.py` (대시보드용 요약 변환) ✅ Phase 1a
3. 대시보드 EDA 탭 (시각화) ⬜ Phase 1c
4. sklearn Pipeline 전처리+모델 번들링 ✅ Phase 2
5. GridSearchCV Pipeline 비교 선택 ✅ Phase 2
6. 전처리 전/후 비교 시각화 + 옵션 변경 UI ⬜ Phase 2
7. LLM(Ollama) EDA→전처리 전략 제안 ✅ Phase 3

## 의존성

- **선행:**
  - `02-ingest` (표준 DataFrame — 타입 캐스팅 완료)
  - `03-feature` (15개 파생변수 추가된 DataFrame)
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
| GridSearchCV Pipeline 비교 선택                    | Phase 2              |
| 전처리 전/후 비교 시각화 + 옵션 변경 UI            | Phase 2              |
| LLM(Ollama) EDA→전처리 전략 제안                   | Phase 3              |

## 테스트 전략

- **profiler.py:** 수치/범주/시간형 컬럼별 프로파일링 + 대용량 샘플링 동작 검증 ✅ [52 passed](../../tests/test_eda/test-results/eda-profiling.md)
- **report.py:** EDAProfile → 대시보드 요약 변환 + JSON 직렬화 ✅ (eda-profiling 리포트에 포함)
- **sklearn Pipeline:** Pipeline별 fit/predict + cross_val_score 동작 검증 ✅ [62 passed](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md)
- **LLM 전처리 제안:** 프롬프트 → JSON 파싱 + 유효한 전처리 옵션 검증 ✅ [llm-preprocessing-advisor](../../tests/test_llm/test-results/llm-preprocessing-advisor.md)

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
from sklearn.preprocessing import StandardScaler, OrdinalEncoder
from sklearn.impute import SimpleImputer

# 공통 전처리 (수치형)
numeric_transformer = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    # scaler는 모델별로 다름 — 아래 Pipeline에서 결정
])

# 공통 전처리 (범주형)
categorical_transformer = Pipeline([
    ("imputer", SimpleImputer(strategy="most_frequent")),
    ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
])

# --- Pipeline 1: XGBoost (스케일링 불필요) ---
pipeline_xgb = Pipeline([
    ("preprocessor", ColumnTransformer([
        ("num", numeric_transformer, numeric_cols),
        ("cat", categorical_transformer, categorical_cols),
    ])),
    ("classifier", XGBClassifier(use_label_encoder=False, eval_metric="logloss")),
])

# --- Pipeline 2: VAE (StandardScaler 필수) ---
pipeline_vae = Pipeline([
    ("preprocessor", ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]), numeric_cols),
        ("cat", categorical_transformer, categorical_cols),
    ])),
    ("detector", VAEDetector()),  # 커스텀 sklearn-compatible wrapper
])

# --- Pipeline 3: Isolation Forest ---
pipeline_if = Pipeline([
    ("preprocessor", ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]), numeric_cols),
        ("cat", categorical_transformer, categorical_cols),
    ])),
    ("detector", IsolationForest(contamination=0.01, random_state=42)),
])

# GridSearchCV Pipeline 비교
pipelines = {"xgb": pipeline_xgb, "vae": pipeline_vae, "isolation_forest": pipeline_if}
results = {}
for name, pipe in pipelines.items():
    scores = cross_val_score(pipe, X, y, cv=5, scoring="f1_macro")
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
│   행: 1,107,720 | 컬럼: 39 | 메모리: ~300MB     │
│   중복행: 0 | 결측률: 2.3%                       │
│                                                  │
│ [컬럼별 프로파일]                                 │
│   ┌──────────────────────────────────────┐       │
│   │ debit_amount (int64)                 │       │
│   │ 결측: 0% | min: 0 | max: 100B       │       │
│   │ mean: 29M | median: 1.2M            │       │
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

---

## ML 탐지 관련 결정사항 (2026-03-21 논의 반영)

### 라벨 전략 자동 전환
label_strategy.py에서 양성 비율/건수 체크 → 기준 미달 시 자동 비지도(VAE+IF) 전환.
- 임계값: min_positive=50, min_positive_rate=0.01
- DataSynth: fraud_rate 1.96% (~6,262건/319,204전표, 2026-04-14 실측) → 지도학습 충분
- 실무 데이터: 라벨 없음 → 비지도 자동 전환

### VAE 학습 데이터 모드 분리
- 검증 모드 (DataSynth): is_fraud=False만 필터링 (정상 100%)
- 실전 모드 (Production): 전체 데이터 투입 (Contamination Tolerance — 이상치 <2%이면 정상 작동)

### VAE 하이퍼파라미터 (MVP)
- 아키텍처: Input(~50) → Hidden(32) → Latent(8) → Hidden(32) → Output(~50)
- Latent을 입력의 16%로 줄여 압축 강제 (Identity Mapping 방지)
- Phase 3: vae_model.py를 BiLSTM+Attention으로 교체 실험 (래퍼 내부 캡슐화)

### 데이터 불균형 처리
- 1순위: 모델별 class_weight 자동 매핑 (scale_pos_weight / class_weight="balanced" / is_unbalance)
- 2순위: SMOTE-ENN (train set에만, data leakage 방지)
- 평가: AUPRC + F2-score (Recall 2배 가중)

### VRAM 관리 (RTX 3070 Ti 8GB)
- Tabular VAE ~100~200MB (이미지 VAE 대비 극소)
- Ollama keep_alive="0" → LLM 후 VRAM 즉시 반환
- LLM과 VAE 타임 슬라이싱 (동시 불필요)

---

## 감사기준서 갭 분석 반영 (DETECTION_RULES.md §3.3 기반)

### DataSynth v1.2.0 컬럼 → 전처리 파이프라인 영향

DataSynth v1.2.0 기준 39개 컬럼 (PREVIEW.md 참조). 전처리 파이프라인에서의 처리:

- **승인 관련** (`approved_by`, `approval_date`): 결측치 = 승인 없음 → 승인 누락 플래그. 피처 파생: `approval_delay_days = approval_date - posting_date`
- **라벨 컬럼** (`is_fraud`, `fraud_type`, `is_anomaly`, `anomaly_type`, `sod_violation`, `sod_conflict_type`): ML 학습 타겟으로 사용. 피처에서 제외 (data leakage 방지). label_strategy.py에서 라벨 전략 결정
- **범주형** (`user_persona`, `business_process`, `document_type`, `source`): 저카디널리티(5~9개) → OrdinalEncoder
- **세금** (`tax_code`, `tax_amount`): nullable. 결측치 = 세금 비해당
- **IC 거래** (`trading_partner`): nullable. IC 전표만 값 존재
- **대사** (`lettrage`, `lettrage_date`): nullable. 대사 완료 건만 값 존재
- **보조원장** (`auxiliary_account_number`, `auxiliary_account_label`): nullable
- **단일값 컬럼** (`currency`=KRW, `exchange_rate`=1.0, `ledger`=0L): 정보량 없음 → drop 후보

### White Box 원칙 유지

모든 피처는 기존 White Box 원칙을 따른다:
- 감사인이 해석 가능한 피처만 생성
- 블랙박스 변환(PCA, 임베딩) 금지
- 각 피처에 감사기준서 근거 태그 부여
