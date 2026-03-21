# 05. 멀티트랙 이상탐지 (Detection) [Phase 1b — 의존: 03-feature, 04-validation]

## 목적
검증 완료된 DataFrame에 3레이어 22개 룰 + ML + NLP/그래프로 이상을 탐지하고,
종합 anomaly_score를 산출한다. BaseDetector 추상 클래스로 트랙 추가를 표준화.

> **탐지 체계 근거**: `docs/AUDIT_DOMAIN_FINAL.md` §4~§5
> DataSynth 52개 anomaly 유형을 3축 평가(법규 × FSS 실증 × 데이터 가용성)로 선별

---

## 데이터 흐름

```
[검증 완료 DataFrame] (from validation/ — is_pipeline_ready=True)
       ↓
① base.validate_input(df)                    → 필수 컬럼 존재 확인 + 빈 DataFrame 차단
       ↓
② integrity_layer.detect(df)                 → A01~A03 무결성 검사
       ↓ (A 위반 시 경고 플래그, 계속 진행)
③ fraud_layer.detect(df)                     → B01~B10 부정 탐지
       ↓
④ anomaly_layer.detect(df)                   → C01~C09 이상 징후 (C07=Benford)
       ↓
⑤ score_aggregator.aggregate_scores(df, [②,③,④])  → anomaly_score + risk_level
       ↓
[anomaly_score + risk_level 보강된 DataFrame] → db/ (06-db)
```

#### 파이프라인 오케스트레이터 (Phase 1b)

위 ①~⑤를 순차 호출하는 단일 진입점. `src/pipeline.py`에서 구현 예정.

```python
# 인터페이스 초안 — Phase 1b에서 구체화
def run_detection_pipeline(
    df: pd.DataFrame,
    *,
    settings: AuditSettings | None = None,
) -> DetectionPipelineResult:
    """검증 완료 DataFrame → 3레이어 탐지 → 종합 점수 산출.

    Returns: DetectionPipelineResult(data, results, risk_summary, elapsed)
    data:         anomaly_score + risk_level 컬럼 추가된 DataFrame
    results:      list[DetectionResult] — 레이어별 상세 결과
    risk_summary: dict — {High: n, Medium: n, Low: n, Normal: n}
    elapsed:      float — 전체 소요 시간(초)
    """
```

---

## 관련 파일

```
src/detection/
├── __init__.py              # public API export
├── constants.py             # RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS 상수 — MVP
├── base.py                  # BaseDetector 추상 클래스 + DetectionResult + RuleFlag — MVP
├── integrity_layer.py       # Layer A: 데이터 무결성 (A01~A03) — MVP
├── fraud_layer.py           # Layer B: 부정 탐지 (B01~B10) — MVP
├── anomaly_layer.py         # Layer C: 이상 징후 (C01~C09, Benford=C07) — MVP
├── score_aggregator.py      # 종합 anomaly_score 산출 — MVP
├── supervised_detector.py   # GridSearchCV 지도학습 — Phase 2
├── vae_detector.py          # VAE + IF 앙상블 — Phase 2
├── duplicate_detector.py    # 중복/분할 거래 — Phase 2
├── timeseries_detector.py   # 시계열 밀도 분석 — Phase 2
├── intercompany_matcher.py  # 내부거래 매칭 — Phase 2
├── nlp_analyzer.py          # 적요 NLP — Phase 3
└── graph_detector.py        # 그래프 순환 탐지 — Phase 3
```

---

## 구현 상태 & 모듈별 가이드

### ① 추상 기반 클래스 (base.py + constants.py) — ⬜ 미구현

```
src/detection/
├── __init__.py      # public API export
├── constants.py     # RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS
└── base.py          # BaseDetector(ABC) + DetectionResult + RuleFlag + validate_input()
```

**구현할 것:**

#### constants.py

- `RULE_CODES: dict[str, str]` — 22개 룰 ID→이름 매핑 (예: `"A01": "차대변 균형"`)
- `SEVERITY_MAP: dict[str, int]` — 룰 ID→severity (1~5) 매핑
- `LAYER_WEIGHTS: dict[str, float]` — 레이어별 가중치 (MVP: `{"layer_a": 0.15, "layer_b": 0.45, "layer_c": 0.25, "benford": 0.15}`)
- `RISK_THRESHOLDS: dict[str, float]` — 위험 등급 임계값 (High=0.7, Medium=0.4, Low=0.2)

> EDA `_generate_warnings`의 `"A02 룰"` 하드코딩 문제를 이 모듈로 해결한다.

#### base.py

```python
from abc import ABC, abstractmethod

@dataclass
class RuleFlag:
    """개별 룰의 탐지 결과."""
    rule_id: str                # "A01", "B03" 등
    rule_name: str              # constants.RULE_CODES에서 참조
    severity: int               # 1~5 (constants.SEVERITY_MAP)
    flagged_count: int          # 플래그된 행 수
    total_count: int            # 검사 대상 행 수
    detail: str | None = None   # 부가 설명

@dataclass
class DetectionResult:
    """하나의 탐지 트랙(Layer) 전체 결과."""
    track_name: str                     # "layer_a", "layer_b", "layer_c"
    flagged_indices: list[int]          # 이상으로 플래그된 행 인덱스
    scores: pd.Series                   # 행별 이상 점수 (0.0~1.0)
    rule_flags: list[RuleFlag]          # 룰별 상세 결과
    details: pd.DataFrame               # 행×룰 상세 (columns=[rule_id, flagged, score])
    metadata: dict                      # {"elapsed": float, "skipped_rules": [...]}
    warnings: list[str]                 # 실행 중 경고 목록

class BaseDetector(ABC):
    """모든 탐지 트랙이 구현해야 할 인터페이스."""

    def __init__(self, settings: AuditSettings | None = None):
        self._settings = settings or get_settings()

    @abstractmethod
    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """DataFrame을 입력받아 이상탐지 수행."""
        ...

    @property
    @abstractmethod
    def track_name(self) -> str:
        """트랙 고유 이름 (예: 'layer_a')."""
        ...

def validate_input(df: pd.DataFrame, required_columns: list[str]) -> list[str]:
    """필수 컬럼 존재 확인. 누락 컬럼 리스트 반환. 빈 DataFrame이면 ValueError."""
```

**설계 결정:**

| 이슈                         | 결정                                          | 사유                                                         |
|:-----------------------------|:----------------------------------------------|:-------------------------------------------------------------|
| scores 타입                  | `pd.Series` (0.0~1.0)                         | DataFrame 조인/집계 편의, numpy 연산 호환                     |
| details 스키마               | `DataFrame(columns=[rule_id, flagged, score])` | 행×룰 매트릭스 — 대시보드 필터링·export 용이                   |
| 룰 코드 상수 위치            | `constants.py` 별도 모듈                       | EDA 등 외부 모듈에서도 import 가능, 하드코딩 제거              |
| settings 주입 방식           | `__init__(settings=None)` → 기본값 `get_settings()` | 테스트 시 DI, 런타임 시 싱글톤                            |
| validate_input 위치          | `base.py` 내 유틸 함수                         | 각 Layer가 중복 검증 안 해도 됨                               |
| RuleFlag vs details 중복     | RuleFlag = 요약, details = 행별 상세           | 대시보드 요약(RuleFlag) / 드릴다운(details) 분리              |

---

### ② Layer A: 데이터 무결성 (integrity_layer.py) — ⬜ 미구현

```
src/detection/
└── integrity_layer.py    # IntegrityLayer(BaseDetector) — A01~A03
```

**구현할 것:**

```python
class IntegrityLayer(BaseDetector):
    """A01~A03: 전표 데이터 자체의 신뢰성 확보. 이후 탐지의 전제조건."""

    @property
    def track_name(self) -> str:
        return "layer_a"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """A01~A03 순차 실행, 결과 통합."""

    def _a01_unbalanced_entry(self, df: pd.DataFrame) -> pd.Series:
        """차대변 균형: groupby('document_id').agg(debit_sum, credit_sum) → abs(diff) > tolerance.
        반환: 행별 위반 여부 (bool → float 1.0/0.0).
        tolerance: settings.py에 추가 또는 기본값 1.0원."""

    def _a02_missing_required(self, df: pd.DataFrame) -> pd.Series:
        """필수필드 누락: schema.yaml required=true인 컬럼 NULL 검사.
        반환: 행별 누락 필드 수 기반 점수 (0.0~1.0)."""

    def _a03_invalid_account(self, df: pd.DataFrame) -> pd.Series:
        """무효 계정: gl_account NOT IN chart_of_accounts.
        CoA 미제공 시 skip + warning 반환."""
```

**피처 매핑:**
- A01: `debit_amount`, `credit_amount` (원본 컬럼 직접 사용)
- A02: 필수 9컬럼 (schema.yaml `required: true`)
- A03: `gl_account` (원본) — CoA 참조 테이블 필요

**설계 결정:**

| 이슈                         | 결정                                          | 사유                                                         |
|:-----------------------------|:----------------------------------------------|:-------------------------------------------------------------|
| A01 차대 불일치 tolerance    | `abs(diff) > 1.0` (원 단위)                   | 부동소수점 오차 허용. settings 오버라이드 가능                 |
| A01 groupby 대상             | `document_id` 단독                             | `fiscal_year + company_code` 복합키는 Phase 2 확장            |
| A03 CoA 없을 때              | skip + warning 반환 (에러 아님)                | 외부 ERP 데이터에는 CoA 미포함 가능                            |
| A03 CoA 로딩 경로            | `data/reference/chart_of_accounts.csv`         | 파일 미존재 → A03 skip. settings에 경로 설정                  |
| A 위반 시 후속 처리          | 경고 플래그만 남기고 B/C 계속 실행             | 차대 불일치가 있어도 부정 징후 탐지는 독립적으로 유의미        |
| scores 산출 방식             | binary (위반=1.0, 정상=0.0)                    | 무결성은 정도 문제가 아니라 위반 여부 판정                      |

---

### ③ Layer B: 부정 탐지 (fraud_layer.py) — ⬜ 미구현

```
src/detection/
└── fraud_layer.py    # FraudLayer(BaseDetector) — B01~B10
```

**구현할 것:**

```python
class FraudLayer(BaseDetector):
    """B01~B10: 부정 징후 탐지. 핵심 레이어.
    권장 컬럼(created_by, business_process 등) 미존재 시 해당 룰 skip + warning."""

    @property
    def track_name(self) -> str:
        return "layer_b"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """B01~B10 순차 실행. 각 룰은 try/except로 격리."""

    def _b01_revenue_manipulation(self, df: pd.DataFrame) -> pd.Series:
        """매출 이상 변동: is_revenue_account==True & amount_zscore > zscore_threshold.
        피처: is_revenue_account, amount_zscore (feature/에서 생성)."""

    def _b02_near_threshold(self, df: pd.DataFrame) -> pd.Series:
        """승인한도 직하: is_near_threshold 피처 직접 사용.
        피처: is_near_threshold (settings.approval_threshold × near_threshold_ratio)."""

    def _b03_exceeds_threshold(self, df: pd.DataFrame) -> pd.Series:
        """승인한도 초과: exceeds_threshold 피처 직접 사용.
        피처: exceeds_threshold (settings.approval_threshold)."""

    def _b04_duplicate_payment(self, df: pd.DataFrame) -> pd.Series:
        """중복 지급: 동일 auxiliary_account_number·금액·30일 내 2건+.
        auxiliary_account_number 미존재 시 skip."""

    def _b05_duplicate_entry(self, df: pd.DataFrame) -> pd.Series:
        """중복 전표: 동일 gl_account·금액·posting_date 매칭.
        원본 컬럼 직접 groupby."""

    def _b06_self_approval(self, df: pd.DataFrame) -> pd.Series:
        """자기 승인: created_by 컬럼 있을 때만 실행.
        created_by == approved_by 또는 단일 사용자 + source=='manual'."""

    def _b07_segregation_of_duties(self, df: pd.DataFrame) -> pd.Series:
        """직무분리 위반: created_by + business_process 교차 검사.
        두 컬럼 모두 있을 때만 실행."""

    def _b08_manual_override(self, df: pd.DataFrame) -> pd.Series:
        """수기 전표: is_manual_je==True & exceeds_threshold==True.
        피처: is_manual_je, exceeds_threshold."""

    def _b09_skipped_approval(self, df: pd.DataFrame) -> pd.Series:
        """승인 생략: exceeds_threshold==True & source != 'automated'.
        source 컬럼 미존재 시 skip."""

    def _b10_circular_intercompany(self, df: pd.DataFrame) -> pd.Series:
        """관계사 순환거래: is_intercompany==True + company_code 간 2-hop 패턴.
        피처: is_intercompany. company_code 미존재 시 skip."""
```

**피처 → 룰 매핑:**

| 룰  | 사용 피처                              | 원본 컬럼 추가 사용                    | 비고                         |
|:----|:---------------------------------------|:---------------------------------------|:-----------------------------|
| B01 | `is_revenue_account`, `amount_zscore`  | —                                      | 피처 2개 조합                |
| B02 | `is_near_threshold`                    | —                                      | 피처 직접 사용               |
| B03 | `exceeds_threshold`                    | —                                      | 피처 직접 사용               |
| B04 | —                                      | `auxiliary_account_number`, 금액, 날짜  | 원본 groupby (피처 없음)     |
| B05 | —                                      | `gl_account`, 금액, `posting_date`     | 원본 groupby (피처 없음)     |
| B06 | —                                      | `created_by`, `source`                 | 권장 컬럼 — 없으면 skip      |
| B07 | —                                      | `created_by`, `business_process`       | 권장 컬럼 — 없으면 skip      |
| B08 | `is_manual_je`, `exceeds_threshold`    | —                                      | 피처 조합                    |
| B09 | `exceeds_threshold`                    | `source`, `created_by`                 | 피처 + 원본 혼합             |
| B10 | `is_intercompany`                      | `company_code`, `reference`            | 피처 + 원본                  |

**설계 결정:**

| 이슈                            | 결정                                          | 사유                                                         |
|:--------------------------------|:----------------------------------------------|:-------------------------------------------------------------|
| 권장 컬럼 미존재 시             | 해당 룰 skip + warning (에러 아님)            | graceful degradation — 외부 데이터에 권장 컬럼 없을 수 있음   |
| B04 중복 판정 window            | 30일                                          | 기간 내 중복 지급 탐지. settings 오버라이드 가능              |
| B05 중복 판정 기준              | 동일 일자 (exact match)                       | B04와 차별화: B04=기간 내 유사, B05=정확 중복                |
| B01 "통계 임계값"               | `amount_zscore > settings.zscore_threshold`   | Z-score 3.0 기본값, settings에 이미 정의                     |
| B10 순환 패턴 depth             | MVP: 2-hop (A→B→A)                           | groupby로 충분. Phase 2 GraphDetector에서 n-hop 확장         |
| scores 산출 방식                | `(severity / 5) × flagged`                    | severity 5단계를 0~1 범위로 정규화                            |
| 룰별 독립 실행                  | 한 룰 실패(exception)해도 나머지 계속 실행     | try/except per rule + warning 수집                           |
| B08 "고액" 기준                 | `exceeds_threshold` 피처 재사용               | 별도 기준 불필요 — 승인한도 초과가 "고액" 정의               |

---

### ④ Layer C: 이상 징후 (anomaly_layer.py) — ⬜ 미구현

```
src/detection/
└── anomaly_layer.py    # AnomalyLayer(BaseDetector) — C01~C09
```

**구현할 것:**

```python
class AnomalyLayer(BaseDetector):
    """C01~C09: 보조 이상 징후. Benford(C07) 포함."""

    @property
    def track_name(self) -> str:
        return "layer_c"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """C01~C09 순차 실행. C07은 validation/benford.py 재사용."""

    def _c01_rushed_period_end(self, df: pd.DataFrame) -> pd.Series:
        """기말 대규모: is_period_end==True & 금액 > 전체 Q3.
        피처: is_period_end. Q3는 detection 내부에서 계산."""

    def _c02_weekend_posting(self, df: pd.DataFrame) -> pd.Series:
        """주말 전기: is_weekend 피처 직접 사용."""

    def _c03_after_hours(self, df: pd.DataFrame) -> pd.Series:
        """심야 전기: is_after_hours 피처 직접 사용."""

    def _c04_backdated_entry(self, df: pd.DataFrame) -> pd.Series:
        """소급 전기: days_backdated > 0. 피처 직접 사용."""

    def _c05_wrong_period(self, df: pd.DataFrame) -> pd.Series:
        """기간 불일치: fiscal_period_mismatch 피처 직접 사용."""

    def _c06_vague_description(self, df: pd.DataFrame) -> pd.Series:
        """위험 적요: description_quality + has_risk_keyword 피처 조합.
        quality 낮음 또는 위험 키워드 포함 시 플래그."""

    def _c07_benford_violation(self, df: pd.DataFrame) -> pd.Series:
        """Benford 위반: src/validation/benford.py의 analyze_benford() 호출.
        first_digit 피처 사용. 최소 샘플(100건) 미달 시 scores=0.0 + warning."""

    def _c08_unusual_amount(self, df: pd.DataFrame) -> pd.Series:
        """이상 고액: amount_zscore > zscore_threshold(settings.py).
        피처: amount_zscore."""

    def _c09_unusual_account_pair(self, df: pd.DataFrame) -> pd.Series:
        """비정상 계정조합: 차변-대변 gl_account 쌍 빈도 하위 1%.
        원본 gl_account 컬럼 사용. document_id별 차변/대변 쌍 추출."""
```

**피처 → 룰 매핑:**

| 룰  | 사용 피처                                  | 원본 컬럼 추가 사용           | 비고                                  |
|:----|:-------------------------------------------|:------------------------------|:--------------------------------------|
| C01 | `is_period_end`                            | `debit_amount`, `credit_amount` | Q3 계산은 detection 내부             |
| C02 | `is_weekend`                               | —                             | 직접 사용                             |
| C03 | `is_after_hours`                           | —                             | 직접 사용                             |
| C04 | `days_backdated`                           | —                             | 직접 사용 (>0이면 플래그)             |
| C05 | `fiscal_period_mismatch`                   | —                             | 직접 사용                             |
| C06 | `description_quality`, `has_risk_keyword`  | —                             | 피처 2개 조합                         |
| C07 | `first_digit`                              | —                             | `validation/benford.py` 재사용        |
| C08 | `amount_zscore`                            | —                             | 직접 사용                             |
| C09 | —                                          | `gl_account`, `document_id`   | 원본 groupby (피처 없음)             |

**설계 결정:**

| 이슈                            | 결정                                              | 사유                                                            |
|:--------------------------------|:--------------------------------------------------|:----------------------------------------------------------------|
| C07: detection vs validation 중복 | detection에서 `validation/benford.py`의 `analyze_benford()` 직접 호출 | 코드 중복 방지, BenfordResult 재사용                 |
| C07 최소 샘플 미달 시           | scores=0.0 + warning 반환 (skip 아닌 0점 처리)    | score_aggregator에서 가중치 적용 시 0이 안전                     |
| C01 "금액 > Q3" 기준            | 전체 DataFrame의 금액 Q3                          | MVP 단순화. Phase 2에서 CoA 상위그룹별 Q3로 확장                |
| C09 "하위 1%" percentile        | `value_counts().cumsum() / total < 0.01`           | 빈도 기반 판정 — 금액 기반 아님                                  |
| C04 소급 전기 기준              | `days_backdated > 0` (0보다 크면 모두 플래그)      | 세분화(경미/심각)는 severity 가중치로 반영                       |
| C02/C03 scores                  | binary: `(severity / 5) × flagged`                 | 시간 관련은 정도가 아닌 여부 판정                                |
| C06 description_quality 기준    | `quality < 0.3` 또는 `has_risk_keyword == True`    | 두 조건 OR — 적요 미비 또는 위험 키워드 포함                     |

---

### ⑤ 종합 점수 산출 (score_aggregator.py) — ⬜ 미구현

```
src/detection/
└── score_aggregator.py    # aggregate_scores() + classify_risk_level()
```

**구현할 것:**

```python
def aggregate_scores(
    df: pd.DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """여러 트랙의 DetectionResult를 종합하여 최종 anomaly_score 산출.

    각 Layer의 scores.mean()을 Layer 점수로 사용한 뒤 가중합 계산.
    결과 컬럼: anomaly_score(float), risk_level(str), flagged_rules(str).
    """

def classify_risk_level(scores: pd.Series) -> pd.Series:
    """anomaly_score → risk_level 변환.
    High: > 0.7, Medium: > 0.4, Low: > 0.2, Normal: ≤ 0.2."""

def _apply_auto_escalation(
    df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Layer A 위반 + Layer B 2개 이상 → High 자동 승격.
    가중합과 독립적인 비즈니스 룰."""

def _extract_flagged_rules(
    results: list[DetectionResult],
    index: int,
) -> str:
    """특정 행이 위반한 룰 ID를 comma-separated 문자열로 반환.
    예: 'A01,B03,C07'. 대시보드 필터링용."""
```

**점수 공식 (AUDIT_DOMAIN_FINAL.md §7):**

> ⚠️ 초기 설계값. Phase 1 완료 후 DataSynth 레이블 대비 back-testing으로 튜닝 필수.

```
anomaly_score = Layer_A × 0.15 + Layer_B × 0.45 + Layer_C × 0.25 + Benford × 0.15

위험 등급:
  High:   anomaly_score > 0.7  또는  Layer_A 위반 + Layer_B 2개 이상
  Medium: anomaly_score > 0.4
  Low:    anomaly_score > 0.2
  Normal: anomaly_score ≤ 0.2
```

**Phase별 가중치 변화:**

| Phase    | 가중치                                                                              |
|:---------|:------------------------------------------------------------------------------------|
| Phase 1  | `layer_a(0.15) + layer_b(0.45) + layer_c(0.25) + benford(0.15)`                    |
| Phase 2  | `rule(0.20) + xgboost(0.25) + vae(0.20) + benford(0.15) + duplicate(0.20)`         |
| Phase 3  | `rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + dup(0.15) + nlp(0.10) + graph(0.15)` |

**설계 결정:**

| 이슈                            | 결정                                             | 사유                                                           |
|:--------------------------------|:-------------------------------------------------|:---------------------------------------------------------------|
| Benford 별도 가중치 vs C07 포함 | Benford를 C07과 별도 가중치(0.15)로 분리         | AUDIT_DOMAIN_FINAL §7 설계 — 통계적 배경 점수로 독립 취급      |
| Layer 점수 정규화               | 각 Layer의 `scores.mean()`을 Layer 점수로 사용   | max는 단일 룰 위반에 과민, mean이 안정적                       |
| 자동 승격 로직 위치             | `_apply_auto_escalation()` 별도 함수             | 가중합과 독립적인 비즈니스 룰 — 테스트 분리 용이                |
| 출력 컬럼                       | `anomaly_score`(float), `risk_level`(str), `flagged_rules`(str) | 대시보드 필터링 + DuckDB 저장 + export 용             |
| 가중치 설정 위치                | `constants.py` LAYER_WEIGHTS + settings.py override 가능 | back-testing 후 .env로 override                    |
| Benford scores 분리 방법        | C07 결과를 AnomalyLayer에서 별도로 반환 받아 분리 | Benford는 행별 점수가 아닌 전체 분포 판정 → 전체에 동일 점수 부여 |

---

## 피처 → 룰 전체 매핑

`src/feature/` 18개 피처가 detection 22개 룰에서 사용되는 관계 전체 정리.

| 카테고리 | 피처명                    | 사용 룰                | 사용 방식            |
|:---------|:--------------------------|:-----------------------|:---------------------|
| Time     | `is_weekend`              | C02                    | 직접 사용            |
| Time     | `is_after_hours`          | C03                    | 직접 사용            |
| Time     | `is_period_end`           | C01                    | + 금액 Q3 조합       |
| Time     | `days_backdated`          | C04                    | >0 판정              |
| Time     | `fiscal_period_mismatch`  | C05                    | 직접 사용            |
| Time     | `is_holiday`              | —                      | MVP 미사용 (Phase 2) |
| Amount   | `is_near_threshold`       | B02                    | 직접 사용            |
| Amount   | `exceeds_threshold`       | B03, B08, B09          | 직접 또는 조합       |
| Amount   | `amount_zscore`           | B01, C08               | 임계값 비교          |
| Amount   | `amount_magnitude`        | —                      | MVP 미사용 (Phase 2) |
| Amount   | `is_round_number`         | —                      | MVP 미사용 (Phase 2) |
| Pattern  | `is_manual_je`            | B08                    | + exceeds_threshold  |
| Pattern  | `is_intercompany`         | B10                    | + company_code       |
| Pattern  | `is_revenue_account`      | B01                    | + amount_zscore      |
| Pattern  | `first_digit`             | C07                    | Benford 분석 입력    |
| Pattern  | `is_suspense_account`     | —                      | MVP 미사용 (Phase 2) |
| Text     | `description_quality`     | C06                    | + has_risk_keyword   |
| Text     | `has_risk_keyword`        | C06                    | OR 조합              |

> `is_holiday`, `amount_magnitude`, `is_round_number`, `is_suspense_account`는 MVP에서 직접 사용하지 않지만,
> Phase 2 탐지기(SupervisedDetector 등)의 ML 입력 피처로 활용 예정.

---

## 22개 감사 룰 상세

### Layer A: 데이터 무결성 (3개)

| ID  | 룰명          | DataSynth 유형      | Sev | 근거                | 탐지 로직                             | 피처                         |
|:----|:-------------|:---------------------|:----|:--------------------|:--------------------------------------|:-----------------------------|
| A01 | 차대변 균형   | UnbalancedEntry      | 5   | 240§32, 복식부기    | sum(debit) ≠ sum(credit) per doc_id   | debit_amount, credit_amount  |
| A02 | 필수필드 누락 | MissingField         | 2   | 240-A45(d), SOX     | 9개 필수 컬럼 NULL 검사               | 전체 필수 컬럼               |
| A03 | 무효 계정     | InvalidAccount       | 3   | 240-A45(a), 315     | gl_account NOT IN chart_of_accounts   | gl_account                   |

### Layer B: 부정 탐지 (10개)

| ID  | 룰명            | DataSynth 유형                  | Sev | 근거                   | 탐지 로직                                    | 피처                                 |
|:----|:---------------|:--------------------------------|:----|:-----------------------|:---------------------------------------------|:-------------------------------------|
| B01 | 매출 이상 변동  | RevenueManipulation             | 5   | 240보론2, FSS최다      | 매출 계정(4xxx) 금액 > 통계 임계값           | is_revenue_account, amount_zscore    |
| B02 | 승인한도 직하   | JustBelowThreshold              | 3   | 240-A45(e), SOX        | 금액 ∈ [threshold×0.9, threshold)            | is_near_threshold                    |
| B03 | 승인한도 초과   | ExceededApprovalLimit           | 3   | SOX, 240§32            | 금액 > threshold                             | exceeds_threshold                    |
| B04 | 중복 지급       | DuplicatePayment                | 3   | 240§32, FSS횡령        | 동일 벤더·금액·30일 내 2건+                  | auxiliary_account_number, 금액, 날짜  |
| B05 | 중복 전표       | DuplicateEntry                  | 3   | 240§32, FSS가공        | 동일 금액·계정·일자 매칭                     | gl_account, 금액, posting_date       |
| B06 | 자기 승인       | SelfApproval                    | 3   | SOX직무분리, FSS오스템  | created_by 기반 추론                         | created_by, source                   |
| B07 | 직무분리 위반   | SegregationOfDutiesViolation    | 4   | SOX직무분리, FSS오스템  | 동일인 다단계 프로세스                       | created_by, business_process         |
| B08 | 수기 전표       | ManualOverride                  | 4   | 240-A45(b), FSS가공    | source == 'manual' + 고액                    | is_manual_je, exceeds_threshold      |
| B09 | 승인 생략       | SkippedApproval                 | 4   | SOX, FSS오스템          | 한도 초과 + 승인 없음                        | exceeds_threshold, source            |
| B10 | 관계사 순환거래  | CircularIntercompany            | 4   | 550호, FSS순환거래      | company_code 간 순환 패턴                    | is_intercompany, company_code        |

### Layer C: 이상 징후 (9개)

| ID  | 룰명           | DataSynth 유형        | Sev | 근거                  | 탐지 로직                           | 피처                                |
|:----|:--------------|:-----------------------|:----|:----------------------|:------------------------------------|:------------------------------------|
| C01 | 기말 대규모    | RushedPeriodEnd        | 3   | 240§32(a)(ii), A44    | 월말 5일 이내 + 금액 > Q3           | is_period_end, 금액                  |
| C02 | 주말 전기      | WeekendPosting         | 2   | 240-A45(c)            | weekday() >= 5                      | is_weekend                           |
| C03 | 심야 전기      | AfterHoursPosting      | 2   | 240-A45(c)            | 22시~06시                           | is_after_hours                       |
| C04 | 소급 전기      | BackdatedEntry         | 3   | 240-A45(c)            | posting_date < document_date - N일  | days_backdated                       |
| C05 | 기간 불일치    | WrongPeriod            | 4   | 240§32                | fiscal_period ≠ month(posting_date) | fiscal_period_mismatch               |
| C06 | 위험 적요      | VagueDescription       | 1   | 240-A45(c), SOX       | line_text 공백·위험키워드           | description_quality, has_risk_keyword |
| C07 | Benford 위반   | BenfordViolation       | 2   | 520호, 240-A45(e)     | MAD > 0.012 or KS p < 0.05         | first_digit                          |
| C08 | 이상 고액      | UnusuallyHighAmount    | 3   | 240§33(b), 315        | Z-score > 3                         | amount_zscore                        |
| C09 | 비정상 계정조합 | UnusualAccountPair    | 2   | 240-A45(a), 315       | 차변-대변 쌍 빈도 하위 1%          | gl_account                           |

---

## 구현 순서

1. - [ ] `constants.py` — RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS 상수
2. - [ ] `base.py` — BaseDetector(ABC), DetectionResult, RuleFlag, validate_input
3. - [ ] `__init__.py` — public API export
4. - [ ] `integrity_layer.py` — A01~A03 (데이터 무결성)
5. - [ ] `fraud_layer.py` — B01~B10 (부정 탐지)
6. - [ ] `anomaly_layer.py` — C01~C09 (이상 징후, C07=Benford)
7. - [ ] `score_aggregator.py` — 3레이어 가중합 + risk_level + 자동 승격

---

## 의존성

- **선행:**
  - `03-feature` (18개 파생변수 — `generate_all_features()`)
  - `04-validation` (`is_pipeline_ready=True` + `benford.py` 재사용)
- **외부 패키지:**
  - MVP: `pandas`, `numpy`, `scipy` (core 그룹에 포함)
- **내부 재사용:**
  - `src/validation/benford.py` → C07 `analyze_benford(first_digits, settings=)` 직접 호출
  - `config/settings.py` → 모든 임계값 참조 (approval_threshold, zscore_threshold 등)
  - `config/audit_rules.yaml` → manual_source_codes, revenue_account_prefixes 등
  - `config/schema.yaml` → A02 필수 컬럼 목록 (`required: true`)
- **후행:**
  - `06-db` (결과를 DuckDB에 적재)
  - `07-dashboard` (Tab 1 Summary에서 risk_summary 렌더링, Tab 3 Explorer에서 드릴다운)

---

## Phase 구분

| 항목                                        | Phase          |
|:--------------------------------------------|:---------------|
| constants.py (룰 코드/가중치 상수)          | MVP (Phase 1b) |
| BaseDetector, DetectionResult, RuleFlag     | MVP (Phase 1b) |
| IntegrityLayer (A01~A03)                    | MVP (Phase 1b) |
| FraudLayer (B01~B10)                        | MVP (Phase 1b) |
| AnomalyLayer (C01~C09, C07=Benford)        | MVP (Phase 1b) |
| score_aggregator (3레이어+Benford)          | MVP (Phase 1b) |
| SupervisedDetector (GridSearchCV)           | Phase 2        |
| VAEDetector + IF 앙상블                     | Phase 2        |
| DuplicateDetector                           | Phase 2        |
| TimeseriesDetector, IntercompanyMatcher     | Phase 2        |
| score_aggregator (5트랙)                    | Phase 2        |
| NLPAnalyzer (kiwipiepy)                     | Phase 3        |
| GraphDetector                               | Phase 3        |
| score_aggregator (7트랙)                    | Phase 3        |

---

## Phase 2/3 탐지기 확장

Phase 1b에서 규칙 기반으로 구현한 탐지를, Phase 2/3에서 ML·NLP·그래프로 확장.
모든 탐지기는 `BaseDetector` 상속 → `detect() -> DetectionResult` 인터페이스 준수.

### Phase 2 탐지기 (5종)

#### 1. SupervisedDetector — GridSearchCV 지도학습

**현재 한계**: 22개 룰은 임계값 기반 → 복합 패턴(다중 피처 조합) 탐지 어려움.

**ML 보완**: Phase 1 룰 결과를 pseudo-label, DataSynth `is_fraud`/`is_anomaly`를 ground truth로
GridSearchCV 최적 모델·하이퍼파라미터 자동 선택.
- 모델 후보: XGBoost, RandomForest, LightGBM
- 피처: 18개 feature + 22개 룰 결과 = 40차원 입력
- ML 모델 후보: LR(베이스라인), RF, XGBoost(메인), LightGBM. KNN 제거(스케일링), DNN 보류(Phase 3 stacking)
- 불균형 처리: 모델별 class_weight 자동 매핑 (scale_pos_weight/class_weight="balanced"/is_unbalance)
- 라벨: DataSynth `is_fraud` ground truth 1순위. 양성 <50건 시 자동 비지도 전환
- 전이 학습: DataSynth 학습 모델을 실무 데이터에 전이 적용 (보조 점수)

#### 2. VAEDetector — VAE + Isolation Forest 앙상블

**현재 한계**: 룰 기반은 "알려진" 패턴만 탐지. 미지 패턴 탐지 불가.

**ML 보완**: 정상 전표의 잠재 분포 학습 → reconstruction error로 미지 이상 탐지.
IF와 앙상블하여 false positive 감소.
- 아키텍처: Basic FC VAE (50→32→8→32→50) Bottleneck 구조
- Phase 3 교체: vae_wrapper.py 내부에서 BiLSTM+Attention으로 교체 실험 (외부 2D 인터페이스 유지)
- 학습 데이터: 검증 모드(is_fraud=False만) / 실전 모드(전체 투입, Contamination Tolerance)

#### 3. DuplicateDetector — 중복/분할 거래

**현재 한계**: B04/B05는 정확 매칭 기반. 분할 거래(동일 계정·일자에 소액 다건 합산) 미탐.

**보완**: 동일 계정·일자의 소액 다건 합산이 승인한도와 유사하면 분할 의심 플래그.

#### 4. TimeseriesDetector — 시계열 밀도 분석

**현재 한계**: 시점별 이상(C01~C03)만 탐지. 거래 빈도 패턴 미분석.

**보완**: TransactionBurst(특정 기간 거래 급증), UnusualFrequency(비정상 거래 주기) 탐지.

#### 5. IntercompanyMatcher — 내부거래 매칭

**현재 한계**: B10은 2-hop 순환만 탐지. 복잡한 내부거래 네트워크 미분석.

**보완**: 관계사 간 거래를 매칭하여 UnmatchedIntercompany(미매칭 내부거래) 탐지.

### Phase 3 탐지기 (2종)

#### 1. NLPAnalyzer — 적요 NLP (kiwipiepy)

**현재 한계**: C06은 키워드 정확 매칭 + 길이 기반. 은어/동의어/맥락 미탐.

**NLP 보완**: kiwipiepy 형태소 분석 → 의미 임베딩 기반 유사도 계산.
MissingDocumentation, LatePosting 등 추가 유형 탐지.

#### 2. GraphDetector — 그래프 순환 탐지

**현재 한계**: B10은 2-hop만. N-hop 순환, 복잡한 자금 순환 경로 미탐.

**그래프 보완**: 거래 네트워크를 방향 그래프로 구성 → 순환 탐지 알고리즘(DFS) 적용.
CircularTransaction, TransferPricingAnomaly 탐지.

---

## 테스트 전략

### 모듈별 테스트 계획

| 테스트 파일                    | 대상 모듈              | 예상 케이스 수 | 주요 검증 항목                                     |
|:-------------------------------|:-----------------------|:---------------|:---------------------------------------------------|
| `test_base.py`                 | base.py + constants.py | ~8건           | DetectionResult 스키마, validate_input, 상수 무결성 |
| `test_integrity_layer.py`      | integrity_layer.py     | ~12건          | A01~A03 각 위반/정상, CoA 미존재 skip              |
| `test_fraud_layer.py`          | fraud_layer.py         | ~25건          | B01~B10 각 위반/정상, 권장 컬럼 미존재 skip        |
| `test_anomaly_layer.py`        | anomaly_layer.py       | ~22건          | C01~C09 각 위반/정상, C07 최소 샘플 미달           |
| `test_score_aggregator.py`     | score_aggregator.py    | ~10건          | 가중합 정확성, risk_level, 자동 승격                |
| **합계**                       |                        | **~77건**      |                                                    |

### 검증 기준

- **Layer A:** A01(차대불일치 전표), A02(NULL 필드 전표), A03(미등록 계정 전표) 각각 위반/정상 검증
- **Layer B:** B01~B10 각각에 대해 DataSynth anomaly 레이블 데이터로 적발률 검증
  - 권장 컬럼(created_by 등) 미존재 시 skip + warning 반환 확인
- **Layer C:** C01~C09 각각 위반/미위반 데이터 검증
  - C07(Benford): 알려진 적합/부적합 데이터셋으로 MAD/KS 판정 검증
  - C07: 100건 미만 → scores=0.0 + warning 확인
- **score_aggregator:** 가중치 합산 정확성, risk_level 임계값 검증, Layer A 위반+B 2개+ → High 자동 승격 검증
- **BaseDetector 준수:** 모든 트랙이 DetectionResult 스키마 반환 확인
- **교차 검증:** DataSynth `is_fraud`/`is_anomaly` 레이블과 룰 탐지 결과 비교 → precision/recall 측정
- **Hold-out Fraud Type**: 8개 유형 중 6개 훈련, 2개(suspense_account_abuse, expense_capitalization) 미지 유형 테스트 → VAE zero-day 탐지 증명
- **Feature Perturbation**: 정상 전표의 피처 간 상관관계를 변조 → VAE 재구성 오차 상승 확인
- **잠재 공간 시각화**: t-SNE/UMAP으로 정상 클러스터 밀집 + 이상치 분리 확인
- **ML 테스트 원칙**: 정확한 점수가 아닌 "배관의 튼튼함" 검증 (구조/범위/결측 체크). Mock으로 비즈니스 로직만 검증

---

## 구현 시 주의사항

- **BaseDetector 인터페이스:** `detect()` → `DetectionResult` 반환 엄수. 새 트랙 추가 시 score_aggregator만 가중치 수정
- **점수 정규화:** 각 트랙의 scores는 0.0~1.0 범위로 정규화할 것
- **Layer A 우선:** A 레이어가 실패(차대 불일치 등)하면 경고 플래그를 남기되, B/C 레이어는 계속 실행
- **C07 Benford 최소 샘플:** 데이터 100건 미만이면 scores=0.0 + warning 반환
- **에러 격리:** 룰 단위 try/except — 한 룰 실패(exception)가 전체 Layer를 중단시키지 않음. warnings에 실패 사유 기록
- **config 통합:** 모든 임계값은 `config/settings.py` 경유. 하드코딩 금지
- **audit_rules.yaml:** manual_source_codes, revenue_account_prefixes 등 패턴 데이터는 YAML에서 로드
- **대용량 처리 (1M+ rows):** vectorized 연산 우선 (for 루프 금지). groupby 최적화 — 불필요한 다중 groupby 회피
- **로깅 전략:** `logging.getLogger(__name__)` 패턴. 룰별 탐지 건수 info 로그, 에러/skip은 warning 로그
- **가중치 튜닝:** ⚠️ 초기 가중치는 근거 없는 설계값. Phase 1 완료 후 DataSynth 레이블 대비 back-testing 필수
- **Supervised pseudo-label:** Phase 2에서 Phase 1 룰 결과를 라벨로 사용 → 룰 정확도가 ML 성능에 직접 영향
- **VAE 학습:** 정상 데이터만으로 학습 → 이상 데이터를 reconstruction error로 탐지
- **SHAP 비용:** SHAP는 계산 비용이 높음 → 플래그된 전표에 대해서만 on-demand 계산
- **점수 스케일 통일**: score_aggregator에서 가중합 전 Percentile Ranking으로 0~1 정규화 필수. XGBoost(0~1)/IF(-0.5~0.5)/VAE(0~∞) 단위 혼재 방지
- **가중치 전략 패턴**: settings.py에 가중치 딕셔너리 정의, score_aggregator는 Phase 분기 없이 받은 딕셔너리로 합산
- **VAE 학습 데이터 오염 방지**: 이상치를 VAE 학습에 섞으면 정상으로 학습 → label_strategy에서 자동 제외

---

## 선행 모듈에서 넘어온 미해결 이슈 (교차 참조)

Phase 2 detection/ML 구현 시 함께 해결해야 하는 선행 모듈 이슈.

| 문제                                  | 현상                                           | Phase 2 해결 방향                                     | 발견 위치                                                         |
|:--------------------------------------|:-----------------------------------------------|:------------------------------------------------------|:------------------------------------------------------------------|
| Z-score 소그룹 fallback 왜곡          | n<30 그룹이 전체 분포에 의존 → 왜곡            | CoA 상위그룹(자산/부채/수익/비용)별 fallback          | [03-feature §G](03-feature.md#g-미해결-이슈-발견--해결-교차-참조)  |
| 외화 소수점 is_round_number           | float % 연산 정수값 전제                       | Decimal 연산 또는 통화별 소수점 설정                  | [03-feature §G](03-feature.md#g-미해결-이슈-발견--해결-교차-참조)  |
| is_suspense_account 대상 컬럼 제한    | gl_account_name 미포함                         | `_SUSPENSE_TEXT_COLS` 상수에 추가                     | [03-feature §G](03-feature.md#g-미해결-이슈-발견--해결-교차-참조)  |
| description_quality 규칙 기반 한계    | 길이+패턴 정밀도 부족                          | Entropy + TTR + ML 분류기                             | [03-feature §G](03-feature.md#g-미해결-이슈-발견--해결-교차-참조)  |
| 은어/동의어 미탐지                    | 정확 키워드만 반응                             | Phase 3 NLP 임베딩으로 이관                           | [08-llm §미해결](08-llm.md#미해결-이슈-phase-3에서-해결--발견-위치-교차-참조) |
| `_generate_warnings` 룰 코드 하드코딩 | `"A02 룰"` 문자열 직접 삽입                    | `detection/constants.py` 룰 코드 상수와 통합          | [eda-profiling.md §코드리뷰](../../tests/test_eda/test-results/eda-profiling.md) |
| model_registry 경로 순회 취약점       | `load()` 시 file_path 검증 없음 → 경로 조작 가능 | `resolve().relative_to()` 검증 삽입               | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| model_registry 상대 경로              | `Path("models")` 하드코딩 → CWD 의존          | `get_settings().project_root / "models"` 변경         | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| vae_wrapper check_is_fitted 누락      | fit 전 predict 호출 시 에러 메시지 불명확      | `check_is_fitted(self, ["model_", "threshold_"])` 추가 | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| label_strategy hybrid 폴백 미비       | 양성 0건 + scores 있을 때 pseudo 폴백 누락     | `positive_rate == 0 and scores` 분기 추가             | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| cv_selector VAE n_jobs 충돌           | VAE Pipeline이 n_jobs>1에서 VRAM 경합          | `_has_vae()` 감지 → n_jobs=1 강제                     | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
