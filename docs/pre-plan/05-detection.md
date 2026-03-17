# 05. 멀티트랙 이상탐지 (Detection)

## 목적
검증 완료된 DataFrame에 다중 트랙(룰 → Benford → ML → 비지도 → 중복 → NLP)으로 이상을 탐지하고,
종합 anomaly_score를 산출한다. BaseDetector 추상 클래스로 트랙 추가를 표준화.

## 관련 파일
```
src/detection/
├── base.py                 # BaseDetector 추상 클래스 + DetectionResult
├── rule_engine.py          # 트랙A-1: R001~R008 룰 (MVP)
├── benford_analyzer.py     # 트랙C: Benford's Law (MVP)
├── score_aggregator.py     # 종합 anomaly_score 산출 (MVP)
├── xgboost_detector.py     # 트랙A-2: XGBoost + SHAP (Phase 2)
├── vae_detector.py         # 트랙B: VAE + IF 앙상블 (Phase 2)
├── duplicate_detector.py   # 트랙D: 중복/분할 거래 (Phase 2)
└── nlp_analyzer.py         # 트랙E: 적요 NLP (Phase 3)
```

## 핵심 클래스/함수

### `base.py` — 추상 기반 클래스
```python
from abc import ABC, abstractmethod

@dataclass
class DetectionResult:
    track_name: str                     # 트랙 식별자 (e.g., "rule_engine")
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

### `rule_engine.py` — 트랙A-1: 룰 기반 (MVP)
```python
class RuleEngine(BaseDetector):
    """R001~R008 감사 룰 엔진.

    각 룰은 피처 컬럼을 참조하여 판정:
    - R001: is_near_threshold == True
    - R002: is_weekend == True
    - R003: is_midnight == True
    - R004: is_period_end == True AND 금액 > 일정 기준
    - R005: is_reversal == True
    - R006: is_manual_je == True
    - R007: has_risk_keyword != 'none'
    - R008: is_intercompany == True
    """

    def detect(self, df: DataFrame) -> DetectionResult:
        """8개 룰을 순회하며 위반 행 플래그.
        scores: 위반 룰 수 / 전체 룰 수 (0~1 정규화)
        details: 행별 위반 룰 목록
        """
```

### `benford_analyzer.py` — 트랙C: Benford 분석 (MVP)
```python
class BenfordAnalyzer(BaseDetector):
    """Benford's Law 첫째 자릿수 분석.

    검정 방법 3가지:
    1. MAD (Mean Absolute Deviation): 평균절대편차
       - 적합: < 0.006, 한계적 적합: 0.006~0.012,
         부적합: 0.012~0.015, 부적합(강): > 0.015
    2. KS 검정 (Kolmogorov-Smirnov): p-value < 0.05면 부적합
    3. Runs Test: 연속 편향 패턴 탐지 (Phase 2)
    """

    def detect(self, df: DataFrame) -> DetectionResult:
        """금액 컬럼의 첫째 자릿수 분포를 Benford 분포와 비교.

        metadata에 포함:
        - observed_freq: 관측 빈도
        - expected_freq: Benford 기대 빈도
        - mad_value, ks_statistic, ks_pvalue
        - conformity: 'close' | 'acceptable' | 'marginally' | 'nonconforming'
        """

    def _extract_first_digit(self, series: pd.Series) -> pd.Series:
        """금액의 첫째 자릿수(1~9) 추출. 0, 음수 처리."""

    def _calculate_mad(self, observed: np.array, expected: np.array) -> float:
        """MAD = mean(|observed - expected|)"""

    def _ks_test(self, observed: np.array, expected: np.array) -> tuple[float, float]:
        """scipy.stats.kstest로 KS 검정."""
```

### `score_aggregator.py` — 종합 점수 산출
```python
def aggregate_scores(
    df: DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None
) -> DataFrame:
    """여러 트랙의 DetectionResult를 종합하여 최종 anomaly_score 산출.

    MVP (2트랙): rule_engine(0.6) + benford(0.4)
    Phase 2 (5트랙): rule(0.25) + xgboost(0.25) + vae(0.2) + benford(0.15) + duplicate(0.15)
    Phase 3 (6트랙): + nlp(0.1) 추가, 기존 가중치 조정

    반환: df에 'anomaly_score', 'risk_level'(High/Medium/Low) 컬럼 추가
    """
```

### `xgboost_detector.py` — 트랙A-2 (Phase 2)
```python
class XGBoostDetector(BaseDetector):
    """XGBoost 지도학습 + SHAP 설명가능성.

    학습 데이터: 룰 엔진 결과를 pseudo-label로 사용
    피처: 11개 파생변수 + 금액/날짜 원본
    설명: SHAP waterfall plot으로 각 예측의 기여도 시각화
    """
```

### `vae_detector.py` — 트랙B (Phase 2)
```python
class VAEDetector(BaseDetector):
    """VAE + Isolation Forest 앙상블.

    VAE: 정상 전표의 잠재 분포 학습 → reconstruction error로 이상 탐지
    IF: 다변량 이상치 탐지 보조
    앙상블: max(VAE score, IF score) 또는 가중 평균
    """
```

### `duplicate_detector.py` — 트랙D (Phase 2)
```python
class DuplicateDetector(BaseDetector):
    """중복/분할 거래 탐지.

    1. 완전 중복: 동일 금액·계정·일자·적요
    2. 분할 의심: 동일 계정·일자에 소액 다건이 합산 시 큰 금액
    """
```

### `nlp_analyzer.py` — 트랙E (Phase 3)
```python
class NLPAnalyzer(BaseDetector):
    """적요 NLP 분석 (kiwipiepy).

    1. 형태소 분석으로 적요 토큰화
    2. 비정상 적요 패턴 탐지 (너무 짧은, 반복적, 의미 없는)
    3. 적요 유사도 클러스터링 → 이상 클러스터 탐지
    """
```

## 8개 감사 룰 상세

| 룰 | 이름 | 조건 | 참조 피처 |
|----|------|------|----------|
| R001 | 승인한도 직하 | 금액 ≥ threshold × ratio | `is_near_threshold` |
| R002 | 주말 전표 | 토/일 기표 | `is_weekend` |
| R003 | 심야 전표 | 22시~06시 기표 | `is_midnight` |
| R004 | 기말 대규모 | 월말 5일 이내 + 고액 | `is_period_end` + 금액 |
| R005 | 역분개 | 동일 계정·금액 차대 쌍 | `is_reversal` |
| R006 | 수기 전표 | source_type=수동 | `is_manual_je` |
| R007 | 위험 적요 | 적요에 위험 키워드 | `has_risk_keyword` |
| R008 | 관계사 거래 | 거래처가 특수관계자 | `is_intercompany` |

## 데이터 흐름
```
[검증 완료 DataFrame] (from validation/)
       ↓
  ┌─── 트랙 병렬 실행 ───────────────────────┐
  │ rule_engine.detect(df)     → DetectionResult  │  MVP
  │ benford_analyzer.detect(df)→ DetectionResult  │  MVP
  │ xgboost_detector.detect(df)→ DetectionResult  │  Phase 2
  │ vae_detector.detect(df)    → DetectionResult  │  Phase 2
  │ duplicate_detector.detect(df)→DetectionResult │  Phase 2
  │ nlp_analyzer.detect(df)    → DetectionResult  │  Phase 3
  └───────────────────────────────────────────────┘
       ↓
score_aggregator.aggregate_scores(df, results)
       ↓
[anomaly_score + risk_level 보강된 DataFrame] → db/
```

## 구현 순서
1. `base.py` — BaseDetector, DetectionResult 정의
2. `rule_engine.py` — R001~R008 룰 구현
3. `benford_analyzer.py` — Benford 분석 (MAD + KS)
4. `score_aggregator.py` — 2트랙 가중 합산
5. (Phase 2) `xgboost_detector.py`, `vae_detector.py`, `duplicate_detector.py`
6. (Phase 3) `nlp_analyzer.py`
7. Phase 추가 시 `score_aggregator.py` 가중치 조정

## 의존성
- **선행:** `04-validation` (검증 완료 DataFrame), `03-feature` (파생변수)
- **외부 패키지:**
  - MVP: `pandas`, `numpy`, `scipy`
  - Phase 2: `xgboost`, `scikit-learn`, `shap`, `torch`
  - Phase 3: `kiwipiepy`
- **후행:** `06-db` (결과를 DuckDB에 적재)

## 테스트 전략
- **룰 엔진:** 8개 룰 각각에 대해 위반/미위반 데이터 검증. 의도적 이상 데이터(generate_sample.py)로 적발률 100% 확인
- **Benford:** 알려진 Benford 적합 데이터셋(인구 데이터 등)과 비적합 데이터(인위적 분포)로 MAD/KS 판정 검증
- **score_aggregator:** 가중치 합산 정확성, risk_level 임계값 검증
- **BaseDetector 준수:** 모든 트랙이 DetectionResult 스키마 반환 확인

## Phase 구분
| 항목 | Phase |
|------|-------|
| BaseDetector, DetectionResult | MVP (Phase 1b) |
| RuleEngine (R001~R008) | MVP (Phase 1b) |
| BenfordAnalyzer (MAD + KS) | MVP (Phase 1b) |
| score_aggregator (2트랙) | MVP (Phase 1b) |
| XGBoostDetector + SHAP | Phase 2 |
| VAEDetector + IF 앙상블 | Phase 2 |
| DuplicateDetector | Phase 2 |
| score_aggregator (5트랙) | Phase 2 |
| NLPAnalyzer (kiwipiepy) | Phase 3 |
| score_aggregator (6트랙) | Phase 3 |

## 구현 시 주의사항
- **BaseDetector 인터페이스:** `detect()` → `DetectionResult` 반환 엄수. 새 트랙 추가 시 score_aggregator만 가중치 수정
- **점수 정규화:** 각 트랙의 scores는 0.0~1.0 범위로 정규화할 것
- **Benford 최소 샘플:** 데이터 100건 미만이면 Benford 검정의 의미가 낮음 → 경고 반환
- **XGBoost pseudo-label:** 룰 엔진 결과를 라벨로 사용하므로, 룰 엔진의 정확도가 ML 성능에 직접 영향
- **VAE 학습:** 정상 데이터만으로 학습 → 이상 데이터를 reconstruction error로 탐지
- **SHAP 비용:** SHAP는 계산 비용이 높음 → 플래그된 전표에 대해서만 on-demand 계산
