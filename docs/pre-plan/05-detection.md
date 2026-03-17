# 05. 멀티트랙 이상탐지 (Detection)

## 목적
검증 완료된 DataFrame에 3레이어 22개 룰 + ML + NLP/그래프로 이상을 탐지하고,
종합 anomaly_score를 산출한다. BaseDetector 추상 클래스로 트랙 추가를 표준화.

> **탐지 체계 근거**: `docs/AUDIT_DOMAIN_FINAL.md` §4~§5
> DataSynth 52개 anomaly 유형을 3축 평가(법규 × FSS 실증 × 데이터 가용성)로 선별

## 관련 파일
```
src/detection/
├── base.py                 # BaseDetector 추상 클래스 + DetectionResult
├── integrity_layer.py      # Layer A: 데이터 무결성 (A01~A03) — MVP
├── fraud_layer.py          # Layer B: 부정 탐지 (B01~B10) — MVP
├── anomaly_layer.py        # Layer C: 이상 징후 (C01~C09, Benford=C07) — MVP
├── score_aggregator.py     # 종합 anomaly_score 산출 — MVP
├── supervised_detector.py  # GridSearchCV 지도학습 — Phase 2
├── vae_detector.py         # VAE + IF 앙상블 — Phase 2
├── duplicate_detector.py   # 중복/분할 거래 — Phase 2
├── timeseries_detector.py  # 시계열 밀도 분석 — Phase 2
├── intercompany_matcher.py # 내부거래 매칭 — Phase 2
├── nlp_analyzer.py         # 적요 NLP — Phase 3
└── graph_detector.py       # 그래프 순환 탐지 — Phase 3
```

## 핵심 클래스/함수

### `base.py` — 추상 기반 클래스
```python
from abc import ABC, abstractmethod

@dataclass
class DetectionResult:
    track_name: str                     # 트랙 식별자 (e.g., "layer_a")
    flagged_indices: list[int]          # 이상으로 플래그된 행 인덱스
    scores: pd.Series                   # 행별 이상 점수 (0.0~1.0)
    details: pd.DataFrame               # 상세 정보 (어떤 룰 위반인지 등)
    metadata: dict                      # 트랙별 메타데이터

class BaseDetector(ABC):
    """모든 탐지 트랙이 구현해야 할 인터페이스."""

    @abstractmethod
    def detect(self, df: DataFrame) -> DetectionResult:
        """DataFrame을 입력받아 이상탐지 수행."""
        ...

    @property
    @abstractmethod
    def track_name(self) -> str:
        """트랙 고유 이름."""
        ...
```

### `integrity_layer.py` — Layer A: 데이터 무결성 (MVP)
```python
class IntegrityLayer(BaseDetector):
    """A01~A03: 전표 데이터 자체의 신뢰성 확보. 이후 탐지의 전제조건.

    A01 차대변 균형: sum(debit) ≠ sum(credit) per document_id
        → 240§32, 복식부기 원칙 위반
    A02 필수필드 누락: 9개 필수 컬럼 NULL 검사
        → 240-A45(d) 계정번호 없음, SOX 전표기록
    A03 무효 계정: gl_account NOT IN chart_of_accounts
        → 240-A45(a) 비정상 계정, 315
    """
```

### `fraud_layer.py` — Layer B: 부정 탐지 (MVP)
```python
class FraudLayer(BaseDetector):
    """B01~B10: 부정 징후 탐지. 핵심 레이어.

    B01 매출 이상 변동: 매출 계정(4xxx) 금액 > 통계 임계값
        → 240보론2, FSS 최다 유형
    B02 승인한도 직하: 금액 ∈ [threshold×0.9, threshold)
        → 240-A45(e) 단수/끝자리, SOX 승인
    B03 승인한도 초과: 금액 > threshold
        → SOX 승인, 240§32
    B04 중복 지급: 동일 벤더·금액·기간 내 2건+
        → 240§32, FSS 횡령은폐
    B05 중복 전표: 동일 금액·계정·일자 매칭
        → 240§32, FSS 가공전표
    B06 자기 승인: created_by 기반 추론
        → SOX 직무분리, FSS 오스템임플란트
    B07 직무분리 위반: 동일인 다단계 프로세스
        → SOX 직무분리, FSS 오스템임플란트
    B08 수기 전표: source == 'manual' + 고액
        → 240-A45(b) 비인가자 입력, FSS 가공전표
    B09 승인 생략: 한도 초과 + 승인 없음
        → SOX 승인, FSS 오스템임플란트
    B10 관계사 순환거래: company_code 간 순환 패턴
        → 550호 특수관계자, FSS 순환거래
    """
```

### `anomaly_layer.py` — Layer C: 이상 징후 (MVP)
```python
class AnomalyLayer(BaseDetector):
    """C01~C09: 보조 이상 징후. Benford(C07) 포함.

    C01 기말 대규모: 월말 5일 이내 + 금액 > Q3
        → 240§32(a)(ii)+A44, FSS 결산수정
    C02 주말 전기: weekday() >= 5
        → 240-A45(c), FSS 비정상시점
    C03 심야 전기: 22시~06시
        → 240-A45(c), FSS 비정상시점
    C04 소급 전기: posting_date < document_date - N일
        → 240-A45(c), FSS 횡령은폐
    C05 기간 불일치: fiscal_period ≠ month(posting_date)
        → 240§32 기간귀속 적정성
    C06 위험 적요: line_text 공백·위험키워드
        → 240-A45(c) 설명없음, SOX 전표기록
    C07 Benford 위반: MAD > 0.012 or KS p < 0.05
        → 520호 기대값-차이 분석
    C08 이상 고액: Z-score > 3
        → 240§33(b), 315
    C09 비정상 계정조합: 차변-대변 쌍 빈도 하위 1%
        → 240-A45(a), 315
    """
```

### `score_aggregator.py` — 종합 점수 산출
```python
def aggregate_scores(
    df: DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None
) -> DataFrame:
    """여러 트랙의 DetectionResult를 종합하여 최종 anomaly_score 산출.

    MVP (3레이어 + Benford):
      Layer_A(0.15) + Layer_B(0.45) + Layer_C(0.25) + Benford(0.15)

    Phase 2 (5트랙):
      rule(0.20) + supervised(0.25) + vae(0.20) + benford(0.15) + duplicate(0.20)

    Phase 3 (7트랙):
      rule(0.15) + supervised(0.20) + vae(0.15) + benford(0.10)
      + duplicate(0.15) + nlp(0.10) + graph(0.15)

    위험등급:
      High:   anomaly_score > 0.7 또는 Layer_A 위반 + Layer_B 2개 이상
      Medium: anomaly_score > 0.4
      Low:    anomaly_score > 0.2
      Normal: anomaly_score ≤ 0.2

    ⚠️ 가중치·임계값은 초기 설계값. Phase 1 완료 후 back-testing으로 튜닝
    """
```

### Phase 2 탐지기 (6종)
```python
class SupervisedDetector(BaseDetector):
    """GridSearchCV 지도학습.
    Phase 1의 22개 룰 결과를 pseudo-label로, DataSynth is_fraud/is_anomaly를 ground truth로.
    모델 후보군 조사 → GridSearchCV로 최적 모델·하이퍼파라미터 선택."""

class VAEDetector(BaseDetector):
    """VAE + Isolation Forest 앙상블.
    정상 전표의 잠재 분포 학습 → reconstruction error로 이상 탐지."""

class DuplicateDetector(BaseDetector):
    """중복/분할 거래 탐지.
    완전 중복 + 분할 의심 (동일 계정·일자에 소액 다건 합산)."""

class TimeseriesDetector(BaseDetector):
    """시계열 밀도 분석. TransactionBurst, UnusualFrequency 탐지."""

class IntercompanyMatcher(BaseDetector):
    """내부거래 매칭. UnmatchedIntercompany 탐지."""
```

### Phase 3 탐지기 (2종)
```python
class NLPAnalyzer(BaseDetector):
    """적요 NLP 분석 (kiwipiepy). MissingDocumentation, LatePosting."""

class GraphDetector(BaseDetector):
    """그래프 순환 탐지. CircularTransaction, TransferPricingAnomaly."""
```

## 22개 감사 룰 상세

### Layer A: 데이터 무결성 (3개)

| ID  | 룰명         | DataSynth 유형     | Sev | 근거                    | 탐지 로직                              | 피처                            |
|-----|-------------|---------------------|-----|------------------------|---------------------------------------|---------------------------------|
| A01 | 차대변 균형  | UnbalancedEntry     | 5   | 240§32, 복식부기       | sum(debit) ≠ sum(credit) per doc_id   | debit_amount, credit_amount     |
| A02 | 필수필드 누락 | MissingField       | 2   | 240-A45(d), SOX        | 9개 필수 컬럼 NULL 검사               | 전체 필수 컬럼                   |
| A03 | 무효 계정    | InvalidAccount      | 3   | 240-A45(a), 315        | gl_account NOT IN chart_of_accounts   | gl_account                      |

### Layer B: 부정 탐지 (10개)

| ID  | 룰명           | DataSynth 유형                 | Sev | 근거                  | 탐지 로직                                   | 피처                                |
|-----|---------------|--------------------------------|-----|----------------------|---------------------------------------------|-------------------------------------|
| B01 | 매출 이상 변동 | RevenueManipulation            | 5   | 240보론2, FSS최다    | 매출 계정(4xxx) 금액 > 통계 임계값          | gl_account, debit_amount            |
| B02 | 승인한도 직하  | JustBelowThreshold             | 3   | 240-A45(e), SOX      | 금액 ∈ [threshold×0.9, threshold)           | debit_amount, credit_amount         |
| B03 | 승인한도 초과  | ExceededApprovalLimit          | 3   | SOX, 240§32          | 금액 > threshold                            | debit_amount, credit_amount         |
| B04 | 중복 지급      | DuplicatePayment               | 3   | 240§32, FSS횡령      | 동일 벤더·금액·기간 내 2건+                 | auxiliary_account_number, 금액, 날짜 |
| B05 | 중복 전표      | DuplicateEntry                 | 3   | 240§32, FSS가공      | 동일 금액·계정·일자 매칭                    | gl_account, 금액, posting_date      |
| B06 | 자기 승인      | SelfApproval                   | 3   | SOX직무분리, FSS오스템 | created_by 기반 추론                       | created_by, source                  |
| B07 | 직무분리 위반  | SegregationOfDutiesViolation   | 4   | SOX직무분리, FSS오스템 | 동일인 다단계 프로세스                     | created_by, business_process        |
| B08 | 수기 전표      | ManualOverride                 | 4   | 240-A45(b), FSS가공  | source == 'manual' + 고액                   | source, 금액                        |
| B09 | 승인 생략      | SkippedApproval                | 4   | SOX, FSS오스템        | 한도 초과 + 승인 없음                      | 금액, source, created_by            |
| B10 | 관계사 순환거래 | CircularIntercompany          | 4   | 550호, FSS순환거래    | company_code 간 순환 패턴                   | company_code, reference             |

### Layer C: 이상 징후 (9개)

| ID  | 룰명          | DataSynth 유형         | Sev | 근거                 | 탐지 로직                          | 피처                           |
|-----|--------------|------------------------|-----|---------------------|------------------------------------|--------------------------------|
| C01 | 기말 대규모   | RushedPeriodEnd        | 3   | 240§32(a)(ii), A44  | 월말 5일 이내 + 금액 > Q3          | posting_date, 금액             |
| C02 | 주말 전기     | WeekendPosting         | 2   | 240-A45(c)          | weekday() >= 5                     | posting_date                   |
| C03 | 심야 전기     | AfterHoursPosting      | 2   | 240-A45(c)          | 22시~06시                          | posting_date (시간)            |
| C04 | 소급 전기     | BackdatedEntry         | 3   | 240-A45(c)          | posting_date < document_date - N일 | posting_date, document_date    |
| C05 | 기간 불일치   | WrongPeriod            | 4   | 240§32              | fiscal_period ≠ month(posting_date)| fiscal_period, posting_date    |
| C06 | 위험 적요     | VagueDescription       | 1   | 240-A45(c), SOX     | line_text 공백·위험키워드          | line_text, header_text         |
| C07 | Benford 위반  | BenfordViolation       | 2   | 520호, 240-A45(e)   | MAD > 0.012 or KS p < 0.05        | debit_amount, credit_amount    |
| C08 | 이상 고액     | UnusuallyHighAmount    | 3   | 240§33(b), 315      | Z-score > 3                        | debit_amount, credit_amount    |
| C09 | 비정상 계정조합 | UnusualAccountPair   | 2   | 240-A45(a), 315     | 차변-대변 쌍 빈도 하위 1%         | gl_account                     |

## 데이터 흐름
```
[검증 완료 DataFrame] (from validation/)
       ↓
  ┌─── 3레이어 순차 실행 ───────────────────────────┐
  │ Layer A: integrity_layer.detect(df) → A01~A03     │  MVP
  │   ↓ (A 위반 시 경고, 계속 진행)                    │
  │ Layer B: fraud_layer.detect(df) → B01~B10          │  MVP
  │ Layer C: anomaly_layer.detect(df) → C01~C09        │  MVP
  ├─── Phase 2 병렬 트랙 ─────────────────────────────┤
  │ supervised_detector, vae_detector,                  │
  │ duplicate_detector, timeseries, intercompany        │
  ├─── Phase 3 병렬 트랙 ─────────────────────────────┤
  │ nlp_analyzer, graph_detector                        │
  └─────────────────────────────────────────────────────┘
       ↓
score_aggregator.aggregate_scores(df, results)
       ↓
[anomaly_score + risk_level 보강된 DataFrame] → db/
```

## 구현 순서
1. `base.py` — BaseDetector, DetectionResult 정의
2. `integrity_layer.py` — A01~A03 (데이터 무결성)
3. `fraud_layer.py` — B01~B10 (부정 탐지)
4. `anomaly_layer.py` — C01~C09 (이상 징후, C07=Benford)
5. `score_aggregator.py` — 3레이어 가중 합산
6. (Phase 2) supervised_detector, vae_detector, duplicate_detector, timeseries, intercompany
7. (Phase 3) nlp_analyzer, graph_detector
8. Phase 추가 시 score_aggregator 가중치 조정

## 의존성
- **선행:** `04-validation` (검증 완료 DataFrame), `03-feature` (파생변수)
- **외부 패키지:**
  - MVP: `pandas`, `numpy`, `scipy`
  - Phase 2: `xgboost`, `scikit-learn`, `shap`, `torch`
  - Phase 3: `kiwipiepy`
- **후행:** `06-db` (결과를 DuckDB에 적재)

## 테스트 전략
- **Layer A:** A01(차대불일치 전표), A02(NULL 필드 전표), A03(미등록 계정 전표) 각각 위반/정상 검증
- **Layer B:** B01~B10 각각에 대해 DataSynth anomaly 레이블 데이터로 적발률 검증
- **Layer C:** C01~C09 각각 위반/미위반 데이터 검증. C07(Benford)은 알려진 적합/부적합 데이터셋으로 MAD/KS 판정 검증
- **score_aggregator:** 가중치 합산 정확성, risk_level 임계값 검증, Layer A 위반+B 2개+ → High 자동 승격 검증
- **BaseDetector 준수:** 모든 트랙이 DetectionResult 스키마 반환 확인
- **교차 검증:** DataSynth is_fraud/is_anomaly 레이블과 룰 탐지 결과 비교 → precision/recall 측정

## Phase 구분
| 항목                                       | Phase          |
|--------------------------------------------|----------------|
| BaseDetector, DetectionResult              | MVP (Phase 1b) |
| IntegrityLayer (A01~A03)                   | MVP (Phase 1b) |
| FraudLayer (B01~B10)                       | MVP (Phase 1b) |
| AnomalyLayer (C01~C09, C07=Benford)       | MVP (Phase 1b) |
| score_aggregator (3레이어+Benford)         | MVP (Phase 1b) |
| SupervisedDetector (GridSearchCV)          | Phase 2        |
| VAEDetector + IF 앙상블                    | Phase 2        |
| DuplicateDetector                          | Phase 2        |
| TimeseriesDetector, IntercompanyMatcher    | Phase 2        |
| score_aggregator (5트랙)                   | Phase 2        |
| NLPAnalyzer (kiwipiepy)                    | Phase 3        |
| GraphDetector                              | Phase 3        |
| score_aggregator (7트랙)                   | Phase 3        |

## 구현 시 주의사항
- **BaseDetector 인터페이스:** `detect()` → `DetectionResult` 반환 엄수. 새 트랙 추가 시 score_aggregator만 가중치 수정
- **점수 정규화:** 각 트랙의 scores는 0.0~1.0 범위로 정규화할 것
- **Layer A 우선:** A 레이어가 실패(차대 불일치 등)하면 경고 플래그를 남기되, B/C 레이어는 계속 실행
- **C07 Benford 최소 샘플:** 데이터 100건 미만이면 Benford 검정의 의미가 낮음 → 경고 반환
- **Supervised pseudo-label:** Phase 1 룰 결과를 라벨로 사용하므로, 룰 정확도가 ML 성능에 직접 영향
- **VAE 학습:** 정상 데이터만으로 학습 → 이상 데이터를 reconstruction error로 탐지
- **SHAP 비용:** SHAP는 계산 비용이 높음 → 플래그된 전표에 대해서만 on-demand 계산
- **가중치 튜닝:** ⚠️ 초기 가중치는 근거 없는 설계값. Phase 1 완료 후 DataSynth 레이블 대비 back-testing 필수
