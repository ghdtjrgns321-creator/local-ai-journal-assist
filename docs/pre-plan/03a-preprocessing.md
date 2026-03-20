# 03a. 전처리 전략 (Preprocessing)

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
| **UX 단계**    | UX 1단계 (수집 투명성)                    | UX 2단계 (전처리 투명성)                    |

---

## 데이터 흐름

```
[사용자 파일 업로드]
       ↓
ingest (02) → 표준 DataFrame (타입 캐스팅 완료)
       ↓
feature (03) → 15개 파생변수 추가
       ↓
EDA 프로파일링 (본 문서 §4) → EDAProfile(JSON)
       ↓
validation (04) → L1 구조 / L2 회계 검증
       ↓
detection (05) → 3레이어 22개 룰 탐지 (Phase 1b)
       ↓
  ┌──────────────────────────────────────────────────┐
  │ Phase 2: sklearn Pipeline                        │
  │   전처리(결측치/인코딩/스케일링) + 모델 번들링   │
  │   → GridSearchCV로 Pipeline 비교 선택            │
  └──────────────────────────────────────────────────┘
       ↓
  ┌──────────────────────────────────────────────────┐
  │ Phase 3: LLM 전처리 제안                         │
  │   EDAProfile(JSON) → Ollama(Qwen3-8B)           │
  │   → 전처리 전략 추천                              │
  └──────────────────────────────────────────────────┘
```

**핵심 포인트 — 닭-달걀 해결:**
Phase 1에서는 전처리를 분리하지 않는다. Phase 2에서 sklearn Pipeline으로
전처리+모델을 번들링하면 "어떤 전처리가 최적인가?"를 모델과 함께 실험할 수 있다.

---

## UX 2단계: 전처리 투명성

### UX 1단계 vs 2단계 대비

| 항목           | UX 1단계 (수집 투명성) ✅                | UX 2단계 (전처리 투명성)                      |
|:---------------|:----------------------------------------|:---------------------------------------------|
| **Phase**      | Phase 1a                                | Phase 1a(EDA) ~ 1c(시각화) ~ 2(ML Pipeline)  |
| **대상**       | 헤더 탐지, 컬럼 매핑, 타입 캐스팅       | EDA 결과, 결측치/인코딩/스케일링 처리          |
| **투명성 모델** | ReviewItem (action, confidence, reason) | EDAProfile(JSON) + Pipeline 설정 노출          |
| **사용자 역할** | 매핑 확인/변경 (3-tier UI)              | EDA 결과 확인 + 전처리 옵션 선택/변경          |
| **구현 파일**   | models.py:ReviewItem                    | src/eda/profiler.py + dashboard EDA 탭         |

### 핵심 원칙

1. **EDA 결과 시각화**: 데이터 현황(분포, 결측률, 이상치)을 대시보드에서 확인
2. **전처리 과정 확인**: 각 단계(결측치 처리, 인코딩, 스케일링)의 방법과 근거 노출
3. **사용자 선택 가능**: 기본값 자동 적용 + 변경 옵션 제공
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

---

## Phase 1a — EDA 프로파일링 모듈 (⬜ 구현 예정)

### 모듈 구조

```
src/eda/
├── __init__.py
├── profiler.py     # DataFrame → EDAProfile (JSON-serializable dict)
└── report.py       # EDAProfile → 대시보드용 요약
```

### profiler.py — DataFrame → EDAProfile

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

### report.py — EDAProfile → 대시보드 요약

- `profiler.py`의 EDAProfile(dict/JSON)을 대시보드에서 렌더링 가능한 형태로 변환
- 컬럼별 요약 카드, 전체 데이터 품질 점수 등
- Phase 1c 대시보드 EDA 탭의 데이터 소스

### 설계 결정

| 항목                      | 결정                                                              |
|:--------------------------|:------------------------------------------------------------------|
| 반환 타입                 | JSON-serializable dict (EDAProfile) — 대시보드/LLM 양쪽에서 사용  |
| 대용량 대응               | 100만행 이상 시 샘플링(10만행) + 전체 통계 병행                    |
| 프로파일링 라이브러리     | 직접 구현 (pandas 기본 API) — ydata-profiling 의존성 회피          |
| 이상치 기준               | IQR × 1.5 (Tukey's fence) — 감사 도메인 표준                     |
| Phase 3 연동              | EDAProfile(JSON) → LLM 프롬프트 입력으로 직접 전달 가능            |

### API 초안

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

---

## Phase 2 — ML 전처리 전략 (sklearn Pipeline)

### 5.1 전처리 단계 정의

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
> 계정코드(4000+종)는 OneHotEncoder 시 차원 폭발 → TargetEncoder 사용.
> TargetEncoder는 타겟 누출 방지를 위해 cross-fitting 적용 (sklearn 기본).

### 5.2 모델별 Pipeline 정의

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
```

### 5.3 모델 선택 (GridSearchCV)

```python
from sklearn.model_selection import cross_val_score

# 동일 데이터 → 각 Pipeline cross_val_score → F1/AUC 비교
pipelines = {
    "xgb": pipeline_xgb,
    "vae": pipeline_vae,
    "isolation_forest": pipeline_if,
}

results = {}
for name, pipe in pipelines.items():
    scores = cross_val_score(pipe, X, y, cv=5, scoring="f1_macro")
    results[name] = {"mean_f1": scores.mean(), "std_f1": scores.std()}

# 최적 Pipeline = 확정 모델 + 확정 전처리
best_pipeline = max(results, key=lambda k: results[k]["mean_f1"])
```

**닭-달걀 해결 핵심:**
sklearn Pipeline이 전처리+모델을 하나의 단위로 묶으므로,
"어떤 전처리가 이 모델에 최적인가?"를 cross validation으로 동시에 답할 수 있다.
전처리를 먼저 확정할 필요 없이 모델과 함께 실험.

### 5.4 UX 2단계 연동 (Phase 2 대시보드)

- **전처리 전/후 데이터 비교**: 원본 분포 vs 전처리 후 분포 (히스토그램 오버레이)
- **Pipeline별 성능 비교 차트**: F1/AUC 바 차트 + 신뢰구간
- **전처리 옵션 변경 UI**: 사용자가 imputer/scaler/encoder 옵션을 변경하고 재실행 가능
- **SHAP 시각화**: 최적 Pipeline의 피처 중요도 (Phase 2 detection과 연계)

---

## Phase 3 — LLM 전처리 제안

### 구조

```
EDAProfile(JSON) → 프롬프트 템플릿 → Ollama(Qwen3-8B) → 전처리 추천(JSON)
```

### 프롬프트 설계

```
다음은 감사 전표 데이터의 EDA 프로파일입니다:
{eda_profile_json}

이 데이터에 적합한 전처리 전략을 추천해주세요:
1. 결측치 처리 방법 (컬럼별)
2. 인코딩 방법 (범주형 컬럼별)
3. 스케일링 방법 (수치형 컬럼)
4. 이상치 처리 전략
5. 불균형 대응 방법

JSON 형식으로 응답하세요.
```

### 하드웨어 제약 (RTX 3070 Ti 8GB)

| 작업                     | VRAM 사용        | 대응 전략                     |
|:-------------------------|:----------------|:------------------------------|
| Qwen3-8B (Q4_K_M)       | ~5GB            | 단독 실행 시 여유             |
| VAE 학습                 | ~2GB            | 단독 실행 시 여유             |
| LLM + VAE 동시           | ~7GB → 위험     | **순차 실행** (LLM → 종료 → VAE) |

> Phase 3에서 LLM 추천 → 사용자 확인 → Pipeline 재실행의 순차 워크플로우로 설계하면
> VRAM 충돌 없이 운영 가능.

---

## Phase 구분

| 항목                                              | Phase                |
|:--------------------------------------------------|:---------------------|
| EDA 프로파일링 모듈 (src/eda/profiler.py, report.py) | MVP (Phase 1a)     |
| 대시보드 EDA 탭 (시각화)                           | MVP (Phase 1c)       |
| sklearn Pipeline 전처리+모델 번들링                 | Phase 2              |
| GridSearchCV Pipeline 비교 선택                    | Phase 2              |
| 전처리 전/후 비교 시각화 + 옵션 변경 UI            | Phase 2              |
| LLM(Ollama) EDA→전처리 전략 제안                   | Phase 3              |

---

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
