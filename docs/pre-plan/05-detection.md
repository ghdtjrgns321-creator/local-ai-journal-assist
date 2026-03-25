# 05. 룰 기반 이상탐지 (Detection) [Phase 1b — 의존: 03-feature, 04-validation]

## 목적

검증 완료된 DataFrame에 **3레이어 22개 룰(if/threshold 기반)**을 적용하여 이상을 탐지하고,
종합 anomaly_score를 산출한다. ML/DL 라이브러리를 사용하지 않으며,
pandas·numpy·scipy만으로 구현한다.
BaseDetector 추상 클래스로 트랙 추가를 표준화.

본 문서는 **Phase 1b(MVP)** 범위의 룰 기반 탐지만 다룬다.
Phase 2 ML 탐지기(XGBoost, VAE+IF 앙상블)는 [05a-detection-ml.md](05a-detection-ml.md) 참조.

### 05-detection vs 05a-detection-ml 역할 구분

| 항목        | 05-detection (본 문서)                    | 05a-detection-ml                        |
|:------------|:------------------------------------------|:----------------------------------------|
| Phase       | 1b (MVP)                                  | 2b                                      |
| 방식        | if/threshold 룰 22개                      | XGBoost 지도학습 + VAE+IF 비지도학습    |
| 사용 패키지 | pandas, numpy, scipy                      | xgboost, scikit-learn, torch            |
| 선행 의존   | 03-feature, 04-validation                 | 03a-preprocessing, 05-detection         |
| 탐지 대상   | "사람이 정한 조건"에 해당하는 전표         | "데이터에서 학습한 패턴"과 유사한 전표   |
| 단독 활용   | 가능 (ML 없이도 감사 결과 산출)           | 룰 기반 결과와 합산하여 사용            |

### 22개 룰 선정 근거

DataSynth 52개 anomaly 유형을 3축 평가로 선별하여 Phase 1에 배치.

- **축 1**: 법규 근거 (KICPA 240, 감사법, FSC 규정) 0~3점
- **축 2**: FSS 실제 발생 빈도 (189건 제재 사례) 0~3점
- **축 3**: 29컬럼 스키마로 즉시 탐지 가능 여부 0~3점
- 합계 7~9점 → Tier 1(Must) → Phase 1 = 20개 유형 = **22개 룰**

Phase 1만으로 FSS 6대 부정 패턴(가공거래·기말조정·횡령은폐·관계사순환·승인위반·비정상시점)을
전부 커버하며, AICPA/CAQ CAAT 15개 시나리오 중 14개, PCAOB A49 의심 특성 11개 전부 매핑.

> **탐지 체계 상세 근거**: `docs/AUDIT_DOMAIN_FINAL.md` §4~§5

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
├── fraud_layer.py           # Layer B: 오케스트레이터 (B01~B10) — MVP
├── fraud_rules_feature.py   # Layer B: 피처 기반 룰 (B01, B02, B03, B08)
├── fraud_rules_groupby.py   # Layer B: groupby 기반 룰 (B04, B05)
├── fraud_rules_access.py    # Layer B: 접근통제 룰 (B06, B07, B09, B10)
├── anomaly_layer.py              # Layer C: 오케스트레이터 (C01~C06, C08~C09)
├── anomaly_rules_simple.py       # Layer C: 피처 기반 룰 (C01~C06, C08)
├── anomaly_rules_statistical.py  # Layer C: C09 계정 쌍 + C07 Benford 공용 함수
├── benford_detector.py           # Benford 독립 트랙 (C07, 가중치 0.15)
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

### ① 추상 기반 클래스 (base.py + constants.py) — ✅ 구현 완료

```
src/detection/
├── __init__.py      # public API export
├── constants.py     # 22개 룰 메타데이터 + 레이어/위험등급 상수
└── base.py          # BaseDetector ABC + DetectionResult + RuleFlag + validate_input()
```

#### 이 모듈이 하는 일

detection 파이프라인은 여러 종류의 탐지기(Layer A/B/C, Phase 2 ML, Phase 3 NLP/Graph)가
**각자 다른 방식으로** 전표를 검사하지만, 결과를 **하나의 score_aggregator**가 합산해야 한다.

추상 기반 클래스는 이 **"입력-출력 계약"**을 강제하는 역할을 한다.

```
문제:
  IntegrityLayer는 if문으로 차대변 균형을 검사하고,
  FraudLayer는 groupby로 중복 지급을 찾고,
  Phase 2 VAEDetector는 reconstruction error로 미지 패턴을 탐지한다.
  → 각자 반환 형식이 다르면 score_aggregator가 합산할 수 없다.

해결:
  BaseDetector(ABC)를 상속하면 detect(df) → DetectionResult 형식이 강제된다.
  score_aggregator는 DetectionResult 리스트만 받으면 되므로,
  탐지기가 내부에서 무엇을 하든 상관없이 동일하게 가중합 산출이 가능하다.
```

구체적으로 3가지를 제공한다:

**1) 결과 표준화 (DetectionResult + RuleFlag)**

어떤 탐지기든 결과를 동일한 구조로 반환한다:
- 어떤 행이 플래그되었는지 (`flagged_indices`)
- 행별 점수가 얼마인지 (`scores`: 0.0~1.0)
- 어떤 룰이 몇 건을 잡았는지 (`rule_flags`)
- 행×룰 상세 매트릭스 (`details`: DataFrame)

이 표준 구조 덕분에 score_aggregator, 대시보드, DuckDB 적재가 탐지기 종류를 몰라도 동작한다.

**2) 룰 메타데이터 중앙 관리 (constants.py)**

22개 룰의 ID·이름·심각도·가중치를 한 곳에서 관리한다.
- Layer 구현체에서 `"A01"` 같은 문자열을 직접 쓰지 않고 constants에서 참조
- `_create_rule_flag("A01", ...)` 호출 시 이름·심각도가 자동 채워짐
- EDA·대시보드 등 외부 모듈에서도 `from src.detection.constants import RULE_CODES`로 일관된 참조
- 룰 추가/수정 시 constants.py 한 곳만 변경하면 전체 반영

**3) 공용 유틸리티 (validate_input + 헬퍼 메서드)**

각 Layer가 반복해야 할 보일러플레이트를 제거한다:
- `validate_input()`: 빈 DataFrame 차단 + 필수 컬럼 존재 확인
- `_make_result()`: DetectionResult 생성 시 track_name 자동 설정 + numpy.int64 방어
- `_create_rule_flag()`: RULE_CODES/SEVERITY_MAP 자동 조회

#### 구현 시 주의사항

**details DataFrame 인덱스 정합성:**
각 룰이 반환하는 Series의 인덱스가 원본 `df.index`와 틀어지면 병합 시 NaN 발생.
Layer `detect()` 내부에서 룰 결과를 dict로 모은 뒤, 원본 인덱스를 강제 할당한다.

```python
rule_results = {"A01": series_a01, "A02": series_a02}
details = pd.DataFrame(rule_results, index=df.index).fillna(0.0)
```

**flagged_indices의 numpy.int64 방어:**
`df[condition].index.tolist()`가 `numpy.int64`를 반환하면 JSON 직렬화 실패.
`_make_result()` 내부에서 `[int(idx) for idx in flagged_indices]`로 강제 캐스팅.

#### 설계 결정

| 이슈                         | 결정                                                        | 사유                                                        |
|:-----------------------------|:------------------------------------------------------------|:------------------------------------------------------------|
| scores 타입                  | `pd.Series` (0.0~1.0)                                      | DataFrame 조인/집계 편의, numpy 연산 호환                    |
| details 스키마               | `DataFrame(columns=룰 ID, values=float)`                    | 행×룰 매트릭스 — 대시보드 필터링·export 용이                  |
| 룰 코드 상수 위치            | `constants.py` 별도 모듈                                    | EDA 등 외부 모듈에서도 import 가능, 하드코딩 제거             |
| settings 주입 방식           | `__init__(settings=None)` → 기본값 `get_settings()`         | 테스트 시 DI, 런타임 시 싱글톤                                |
| validate_input 위치          | `base.py` 내 유틸 함수                                      | 각 Layer가 중복 검증 안 해도 됨                               |
| RuleFlag vs details 중복     | RuleFlag = 요약, details = 행별 상세                        | 대시보드 요약(RuleFlag) / 드릴다운(details) 분리              |
| flagged_indices numpy 방어   | `_make_result()`에서 int() 강제 캐스팅                      | JSON 직렬화 시 numpy.int64 TypeError 방지                    |

#### 테스트 결과

```
tests/detection/test_constants.py — 16개 통과
tests/detection/test_base.py     — 22개 통과
합계 38개 전체 통과
```

> E2E 테스트 결과: [e2e-detection-datasynth.md](../../tests/test_detection/test-results/e2e-detection-datasynth.md)

---

### ② Layer A: 데이터 무결성 (integrity_layer.py) — ✅ 구현 완료

```
src/detection/
└── integrity_layer.py    # IntegrityDetector(BaseDetector) — A01~A03
```

#### 이 모듈이 하는 일

3레이어 탐지의 **첫 번째 단계**로, "이 전표 데이터를 신뢰할 수 있는가?"를 판정한다.
Layer B(부정 탐지)·C(이상 징후)가 의미 있는 결과를 내려면,
**데이터 자체가 올바르게 기록되었는지** 먼저 확인해야 한다.

```
파이프라인 위치:
  L1/L2 Validation (Gate)  →  Layer A (감사 증거)  →  Layer B/C (탐지)

역할 차이:
  L1/L2: "이 파일을 읽을 수 있는가?"  → is_valid=False면 중단
  Layer A: "이 '행'의 무결성 점수는?"  → score 부여 후 계속 진행
```

L1 Validation과의 핵심 차이는 **판단 단위와 출력**이다:

```
┌──────────────┬──────────────────┬──────────────────────┐
│              │ L1/L2 Validation │ Layer A Detection     │
├──────────────┼──────────────────┼──────────────────────┤
│ 목적         │ 파이프라인 Gate   │ 감사 증거 생성        │
│ 판단 단위    │ DataFrame 전체   │ 행(row) 단위          │
│ 출력         │ is_valid: bool   │ score: 0.0~1.0/row   │
│ 실패 시      │ 파이프라인 중단   │ 경고 플래그+계속 진행  │
│ 사용처       │ 개발자 디버깅     │ 감사인 보고서          │
└──────────────┴──────────────────┴──────────────────────┘
```

"경고하되 중단하지 않는다"가 핵심 설계 원칙이다.
차대변 불일치가 있어도 파이프라인을 중단하지 않는 이유:
- 해당 전표에서 B06(자기 승인)이나 C03(심야 전기)을 추가 발견하면 **감사 증거가 더 강력**해짐
- 중단하면 "무결성 이슈 + 부정 징후 동시 발생"이라는 중요한 패턴을 놓침

#### 구현 내용

```python
class IntegrityDetector(BaseDetector):
    """A01~A03: 전표 데이터 무결성 검증."""

    def __init__(self, settings=None, tolerance=None, chart_of_accounts=None):
        # tolerance: settings.balance_tolerance (기본 1.0원) 또는 명시적 주입
        # chart_of_accounts: set[str] — None이면 A03 skip

    def detect(self, df) -> DetectionResult:
        # A01→A02→A03 순차 실행, 룰별 try/except 격리
        # details DF 구성 → 행별 max score → DetectionResult 반환

    def _a01_unbalanced_entry(self, df) -> Series | None:
        # groupby(document_id).transform("sum") → abs(diff) > tolerance
        # NaN document_id → 고유 더미 키로 개별 행 취급

    def _a02_missing_required(self, df) -> Series:
        # schema.yaml required=true 컬럼 중 NULL 존재 시 플래그
        # L1의 이중 안전장치 — 정상 흐름에서 플래그 0 기대

    def _a03_invalid_account(self, df) -> Series | None:
        # gl_account NOT IN CoA → 플래그. CoA 미제공 시 skip
        # astype(str)로 int/str 타입 통일
```

#### 룰별 감사 근거

| 룰  | 감사 근거                             | 탐지 대상                        |
|:----|:--------------------------------------|:---------------------------------|
| A01 | ISA 240 §32(a), K-SOX §8①2호         | 차변합 ≠ 대변합 → 복식부기 위반   |
| A02 | ISA 240 A45(d) "계정번호가 없는 기입" | 필수필드(9컬럼) NULL → 통제 미작동 |
| A03 | ISA 240 A45(a) "거의 사용되지 않는 계정" | CoA에 없는 계정 → 가공 계정 의심 |

#### 피처 매핑

- A01: `debit_amount`, `credit_amount`, `document_id` (원본 컬럼 직접 사용)
- A02: 필수 9컬럼 (schema.yaml `required: true`)
- A03: `gl_account` (원본) + CoA 참조 (`chart_of_accounts: set[str]` 외부 주입)

#### Scoring

```
per-rule: flagged ? (severity / 5) : 0.0
  A01 (severity 5) → 위반 시 1.0
  A02 (severity 2) → 위반 시 0.4
  A03 (severity 3) → 위반 시 0.6
row_score = max(A01_score, A02_score, A03_score)
```

max 방식 사용 이유: 무결성은 "가장 심각한 위반"이 해당 행의 위험도를 결정한다.

Score Aggregator에서 Layer A 가중치는 0.15 (최저)이나,
**Layer A 위반 + Layer B 2개 이상 → 자동 High 등급** 에스컬레이션 적용.

#### 구현 시 주의사항

**A01 groupby NaN 키 문제:**
pandas `groupby()`는 NaN 키를 기본 drop한다. document_id에 결측치가 있으면
해당 행이 연산에서 누락되어 인덱스 불일치 발생.
해결: NaN document_id에 고유 더미 키(`_nan_{index}`) 부여 → 개별 행 취급.

```python
safe_doc_id = df["document_id"].copy()
nan_mask = safe_doc_id.isna()
if nan_mask.any():
    safe_doc_id.loc[nan_mask] = "_nan_" + nan_mask[nan_mask].index.astype(str)
doc_diff = diff.groupby(safe_doc_id).transform("sum")
```

**A02 vs L1 역할 분담 (이중 안전장치):**
L1(schema_validator)이 컬럼 존재+타입을 검증하여 gate 역할.
A02는 L1 통과 후에도 남아있는 **행 단위 NULL**을 잡는 fallback.
정상 흐름에서 A02 플래그 = 0이 기대값. 플래그 발생 시 L1 검증 로직 점검 필요.

#### 설계 결정

| 이슈                         | 결정                                          | 사유                                                         |
|:-----------------------------|:----------------------------------------------|:-------------------------------------------------------------|
| A01 차대 불일치 tolerance    | `settings.balance_tolerance` (기본 1.0원)      | 부동소수점 오차 허용. settings 오버라이드 + DI 지원            |
| A01 groupby 대상             | `document_id` 단독                             | `fiscal_year + company_code` 복합키는 Phase 2 확장            |
| A01 NaN document_id          | 고유 더미 키 부여, 개별 행 취급                 | groupby NaN drop 방지 + 행 간 잘못된 합산 방지                |
| A02 vs L1 역할               | L1=gate, A02=행 단위 fallback                  | L1 통과 후에도 개별 행 NULL 잡아 감사 증거 생성               |
| A03 CoA 없을 때              | skip + warning 반환 (에러 아님)                | 외부 ERP 데이터에는 CoA 미포함 가능                            |
| A03 타입 매칭                | `astype(str)` 통일                             | schema는 int, CoA는 str일 수 있음                             |
| A 위반 시 후속 처리          | 경고 플래그만 남기고 B/C 계속 실행             | 차대 불일치가 있어도 부정 징후 탐지는 독립적으로 유의미        |
| scores 산출 방식             | `(severity/5) × flagged` → 행별 max            | 무결성은 위반 여부 판정. 다중 위반 시 가장 심각한 것이 대표    |

#### 테스트 결과

```
tests/test_detection/test_integrity_layer.py — 18개 통과
  TestA01UnbalancedEntry   — 6개 (균형/불균형/tolerance경계/NaN처리/skip)
  TestA02MissingRequired   — 3개 (정상/NULL/다중NULL)
  TestA03InvalidAccount    — 4개 (유효/무효/CoA미제공/int-str호환)
  TestDetectIntegration    — 5개 (반환타입/max scoring/skipped/elapsed/빈DF)
```

> E2E 테스트 결과: [e2e-detection-datasynth.md](../../tests/test_detection/test-results/e2e-detection-datasynth.md)

---

### ③ Layer B: 부정 탐지 (fraud_layer.py) — ✅ 구현 완료

#### Layer B가 하는 일

3레이어 탐지 체계에서 **핵심 레이어**(가중치 0.45)이다.
Layer A가 "이 데이터를 믿을 수 있는가?"를 검증한다면,
Layer B는 **"이 전표가 부정·횡령의 징후를 보이는가?"** 를 판정한다.

10개 룰(B01~B10)이 각각 독립적으로 부정 패턴 하나를 탐지하며,
하나의 전표가 여러 룰에 동시에 걸릴 수 있다 (예: B08 수기 전표 + B03 한도 초과).

#### 왜 필요한가

감사기준서 240호 §32는 **"경영진의 내부통제 무력화 위험에 대한 평가와 관계없이"**
전표의 적정성을 테스트하라고 의무화한다.
이 의무를 자동화한 것이 Layer B의 10개 룰이다.

```
법규 근거 → 룰 도출:

감사기준서 240호 §32(c)  "비정상 유의적 거래의 사업상 합리성 평가"
  → B01 매출 이상 변동 — FSS 189건 분석 결과 가공매출이 최다 부정 패턴

감사기준서 240호 A45(b)  "통상 분개하지 않는 개인에 의한 기입"
  → B08 수기 전표 — 자동 프로세스를 우회하여 수기 입력된 고액 전표

감사기준서 240호 A45(e)  "단수(round number) 또는 일관된 끝자리"
  → B02 승인한도 직하 — 의도적으로 승인 한도 바로 아래에 금액을 맞추는 분할 징후

외감법 §8①5호  "업무 분장과 책임"
  → B06 자기 승인, B07 직무분리 위반
    오스템임플란트(2021) 사례: 1인이 입력·승인·이체 전부 수행 → 2,215억 횡령

외감법 §8②  "내회관 우회 금지"
  → B09 승인 생략 — 승인 절차 없이 처리된 한도 초과 전표

감사기준서 550호 §23  "특수관계자 거래의 사업상 합리성"
  → B10 관계사 순환거래 — 합리적 사업 근거 없는 순환 자금 이동
```

Layer A(무결성)만으로는 "차대변이 맞고 필수필드가 있다"는 것만 확인할 수 있고,
Layer C(이상 징후)는 시점·금액 패턴만 보는 보조 지표이다.
**부정 여부를 직접 판정하는 것은 Layer B뿐**이며,
이것이 가중치가 0.45 (전체의 거의 절반)인 이유이다.

#### 파일 구조

100줄 제한을 맞추기 위해 **데이터 접근 패턴 기준**으로 4개 파일로 분할.

```
src/detection/
├── fraud_layer.py             # FraudLayer 오케스트레이터 — 룰 레지스트리 순회 + 결과 조합
├── fraud_rules_feature.py     # 피처 기반 룰: B01, B02, B03, B08 — bool 컬럼 마스크 연산
├── fraud_rules_groupby.py     # groupby 기반 룰: B04, B05 — 원본 컬럼 집계/중복 판정
└── fraud_rules_access.py      # 접근통제 룰: B06, B07, B09, B10 — 권장 컬럼 의존 (skip 가능)
```

| 서브모듈                  | 분할 근거                                               | 포함 룰            |
|:--------------------------|:-------------------------------------------------------|:-------------------|
| `fraud_rules_feature.py`  | 피처 엔진이 생성한 bool/float 컬럼을 직접 조합           | B01, B02, B03, B08 |
| `fraud_rules_groupby.py`  | 원본 컬럼 groupby + window 비교. 연산 비용 높음          | B04, B05           |
| `fraud_rules_access.py`   | 권장 컬럼(`created_by`, `source` 등) 의존. skip 확률 높음 | B06, B07, B09, B10 |

#### 각 파일의 역할

##### fraud_layer.py — 오케스트레이터

FraudLayer 클래스가 BaseDetector를 상속하고 `detect(df) → DetectionResult`를 구현한다.
내부에서 룰 레지스트리(`_build_registry()`)를 순회하며 서브모듈의 함수를 호출한다.

```
실행 흐름:
  1. validate_input(df, ["debit_amount", "credit_amount"])
  2. _build_registry() → [(rule_id, callable, kwargs), ...] 10개
  3. for rule in registry:
       try: rule_results[rule_id] = func(df, **kwargs)
       except: skipped_rules.append(rule_id) + warning
  4. _build_result() → scores(max severity/5), details(행×룰), RuleFlag 리스트
```

**scores 산출 규칙:**
한 행이 B01(severity=5)과 B02(severity=3)에 동시에 해당하면
`max(5/5, 3/5) = 1.0`. 합산이 아닌 **최대값**을 사용한다.
합산하면 이론상 2.0을 초과하여 score_aggregator의 0~1 정규화가 깨지기 때문이다.

**settings에서 주입하는 파라미터:**
- `zscore_threshold` → B01
- `duplicate_payment_window_days` → B04
- `sod_process_threshold` → B07

##### fraud_rules_feature.py — 피처 기반 룰 (B01, B02, B03, B08)

피처 엔진이 미리 생성한 bool/float 컬럼을 AND/OR 조합하는 단순 마스크 연산.
모든 함수는 `(df, **params) → pd.Series[bool]` 시그니처.
피처 미존재 시 `pd.Series(False, index=df.index)` 반환.

```
b01_revenue_manipulation  is_revenue_account & (amount_zscore > threshold)
b02_near_threshold        is_near_threshold.fillna(False)
b03_exceeds_threshold     exceeds_threshold.fillna(False)
b08_manual_override       is_manual_je.fillna(False) & exceeds_threshold.fillna(False)
```

##### fraud_rules_groupby.py — groupby 기반 룰 (B04, B05)

원본 컬럼에 직접 접근하여 groupby/duplicated 연산을 수행한다.
`_compute_base_amount(df)` 헬퍼로 `max(debit, credit)` 대표 금액을 산출.

```
b04_duplicate_payment
  ① base_amount = max(debit, credit)
  ② sort(vendor, amount, date)
  ③ groupby(vendor, amount) → 양방향 diff (forward + backward)
  ④ diff ≤ window → flag

b05_duplicate_entry
  ① base_amount 산출
  ② duplicated(subset=[gl_account, base_amount, posting_date], keep=False)
```

**B04 양방향 diff가 필요한 이유:**
단순 `diff()`만 쓰면 그룹 첫 행이 NaT → 중복 쌍의 원본 건이 누락된다.
`diff()` (앞 행과의 차이) + `diff(-1).abs()` (뒷 행과의 차이) 양방향을 OR 조합하여
모든 중복 행을 빠짐없이 포착한다.

```python
# 양방향 diff 패턴
diff_forward = grouped["posting_date"].diff()
diff_backward = grouped["posting_date"].diff(-1).abs()
is_duplicate = (diff_forward <= window) | (diff_backward <= window)
```

##### fraud_rules_access.py — 접근통제 룰 (B06, B07, B09, B10)

`created_by`, `business_process`, `source`, `company_code` 등 **권장 컬럼**에 의존.
외부 ERP 데이터에는 이 컬럼이 없을 수 있으므로 skip 확률이 가장 높은 그룹이다.

```
b06_self_approval
  Case A: approved_by 존재 → created_by == approved_by
  Case B: approved_by 부재 → 수기 소스 + created_by 존재 = 자기 승인 추정

b07_segregation_of_duties
  groupby(created_by).nunique(business_process) → 위반자 목록 → isin()으로 행 레벨 매핑

b09_skipped_approval
  exceeds_threshold & (source != 'automated')

b10_circular_intercompany  (MVP: 관계사 전표 존재 감지)
  is_intercompany == True인 행을 flag. 실제 순환 탐지는 Phase 2 GraphDetector.
```

**B07 행 레벨 매핑이 필요한 이유:**
`groupby().nunique()`는 사용자 단위 집계를 반환하므로 원본 DataFrame 인덱스와 불일치한다.
위반 사용자 목록을 먼저 추출한 뒤, `isin()`으로 원본 행에 역매핑한다.

```python
# 집계 → 행 레벨 변환 패턴
counts = df.groupby("created_by")["business_process"].nunique()
violators = counts[counts >= threshold].index
return df["created_by"].isin(violators)
```

#### 피처 → 룰 매핑

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
| B10 | `is_intercompany`                      | `company_code`                         | MVP: 관계사 존재 감지만      |

#### 설계 결정

| 이슈                            | 결정                                          | 사유                                                         |
|:--------------------------------|:----------------------------------------------|:-------------------------------------------------------------|
| 권장 컬럼 미존재 시             | 해당 룰 skip + warning (에러 아님)            | graceful degradation — 외부 데이터에 권장 컬럼 없을 수 있음   |
| B04 중복 판정 window            | 30일 (`settings.duplicate_payment_window_days`) | 기간 내 중복 지급 탐지. settings 오버라이드 가능             |
| B04 diff 방향                   | 양방향 (forward + backward)                   | 단방향 시 그룹 첫 행 NaT → 원본 건 누락 방지                |
| B05 중복 판정 기준              | 동일 일자 (exact match)                       | B04와 차별화: B04=기간 내 유사, B05=정확 중복                |
| B01 "통계 임계값"               | `amount_zscore > settings.zscore_threshold`   | Z-score 3.0 기본값, settings에 이미 정의                     |
| B07 행 레벨 변환                | `groupby.nunique` → 위반자 목록 → `isin()`   | groupby 집계는 사용자 단위, detect()는 행 단위 결과 필요      |
| B10 순환 패턴 depth             | MVP: 관계사 전표 존재 감지만                  | 실제 n-hop 순환은 Phase 2 GraphDetector에서 구현              |
| scores 산출 방식                | `max(severity / 5 × flagged)` per row         | severity 5단계를 0~1 범위로 정규화. 합산 시 1.0 초과 위험     |
| 룰별 독립 실행                  | 한 룰 실패(exception)해도 나머지 계속 실행     | try/except per rule + warning 수집                           |
| B08 "고액" 기준                 | `exceeds_threshold` 피처 재사용               | 별도 기준 불필요 — 승인한도 초과가 "고액" 정의               |
| 수기 전표 코드 관리             | `audit_rules.yaml` → `lru_cache` 로딩         | 스레드 안전, 테스트 격리 가능 (`cache_clear()`)              |

#### settings.py 추가 설정

| 설정                            | 타입  | 기본값 | 환경변수                              | 사용 룰 |
|:--------------------------------|:------|:-------|:--------------------------------------|:--------|
| `duplicate_payment_window_days` | `int` | `30`   | `AUDIT_DUPLICATE_PAYMENT_WINDOW_DAYS` | B04     |
| `sod_process_threshold`         | `int` | `3`    | `AUDIT_SOD_PROCESS_THRESHOLD`         | B07     |

#### 테스트 결과

```
tests/test_detection/test_fraud_rules_feature.py — 12개 통과
  B01: 매출+고zscore flagged, 저zscore not, 비매출 not, 피처 미존재 skip
  B02: near_threshold flagged/not/미존재
  B03: exceeds flagged/not
  B08: 수기+초과 flagged, 수기만 not, 초과만 not

tests/test_detection/test_fraud_rules_groupby.py — 10개 통과
  B04: 윈도우 내 flagged(양방향 diff), 윈도우 초과 not, 다른 거래처 not,
       컬럼 미존재 skip, 3건 중복 전체 flagged, 정확히 30일 경계 flagged
  B05: exact match flagged, 날짜 다름 not, GL 다름 not, 컬럼 미존재 skip

tests/test_detection/test_fraud_rules_access.py — 12개 통과
  B06: 동일 승인자 flagged, fallback(수기 소스), created_by 미존재 skip, NaN 처리
  B07: 3프로세스 위반자 flagged(행 레벨 매핑), 미달 not, 컬럼 미존재 skip
  B09: 초과+비자동 flagged, 컬럼 미존재 skip
  B10: 관계사 다수 회사 flagged, 단일 회사 flagged, 컬럼 미존재 skip

tests/test_detection/test_fraud_layer.py — 8개 통과
  통합: DetectionResult 구조, scores max≤1.0, minimal_df graceful, 빈 df ValueError,
       rule_flags 수, B01 매출 이상치 details 검증, 컬럼명 B prefix, flagged_indices 정합
```

> E2E 테스트 결과: [e2e-detection-datasynth.md](../../tests/test_detection/test-results/e2e-detection-datasynth.md)

---

### ④ Layer C: 이상 징후 (anomaly_layer.py) — ✅ 구현 완료

```
src/detection/
├── anomaly_layer.py              # AnomalyDetector 오케스트레이터 — C01~C06, C08~C09 (8개)
├── anomaly_rules_simple.py       # 피처 기반 룰: C01~C06, C08 — bool 컬럼 마스크 연산
├── anomaly_rules_statistical.py  # C09 계정 쌍 + C07 Benford 공용 함수
└── benford_detector.py           # BenfordDetector 독립 트랙 — C07 (가중치 0.15)
```

> C07(Benford)은 전체 분포 검정으로 행별 룰과 성격이 달라 독립 트랙으로 분리.
> AUDIT_DOMAIN_FINAL §7: `anomaly_score = A×0.15 + B×0.45 + C×0.25 + Benford×0.15`

#### 이 모듈이 하는 일

3레이어 탐지 체계에서 **보조 레이어**(가중치 0.25)이다.
Layer B가 "이 전표가 부정·횡령의 징후를 보이는가?"를 직접 판정한다면,
Layer C는 **"이 전표가 비정상적인 패턴을 보이는가?"** 를 간접 지표로 탐지한다.

9개 룰(C01~C09)이 시점·금액·적요·분포 관점에서 이상 패턴을 감지하며,
Layer B와 동시에 걸리면 감사 증거가 더 강력해진다.

#### 왜 필요한가

```
법규 근거 → 룰 도출:

감사기준서 240호 §32(b)  "결산 수정 분개의 적정성"
  → C01 기말 대규모 — 기말에 집중되는 고액 전표는 결산 조정 조작 가능성
  → C05 기간 불일치 — 회계기간 귀속 오류는 의도적 기간 이동 의심

감사기준서 240호 A49(c)  "비정상적 시기에 이루어진 거래"
  → C02 주말 전기, C03 심야 전기 — 감시 부재 시점 악용
  → C04 소급 전기 — 과도한 소급은 기록 조작 은폐
  → C06 위험 적요 — 적요 미비/위험 키워드는 전표 추적 방해

감사기준서 520호 §5, 240 A45(e)  "예상치 못한 관계나 추세"
  → C07 Benford 위반 — 첫째자리 분포의 통계적 비적합성
  → C08 이상 고액 — 3σ 초과 금액은 조작 가능성

감사기준서 240호 A49(a), ISA 315  "비정상적 계정 조합"
  → C09 비정상 계정조합 — 희소한 차변-대변 쌍은 비정상 거래 의심
```

Layer C 단독으로는 부정 판정이 아니지만,
Layer A 위반 + Layer B 패턴 + Layer C 징후가 동시에 발생하면
**감사 증거의 설득력이 기하급수적으로 강화**된다.

#### 파일 구조

100줄 제한을 맞추기 위해 **데이터 접근 패턴 기준**으로 3개 파일로 분할.

| 서브모듈                      | 분할 근거                                                    | 포함 룰                |
|:------------------------------|:------------------------------------------------------------|:-----------------------|
| `anomaly_rules_simple.py`     | 피처 엔진이 생성한 bool/float 컬럼을 직접 조합               | C01~C06, C08 (7개)     |
| `anomaly_rules_statistical.py`| 별도 통계 연산(Benford 분석, 계정 쌍 빈도) 필요              | C07, C09 (2개)         |

#### 각 파일의 역할

##### anomaly_layer.py — 오케스트레이터

AnomalyDetector 클래스가 BaseDetector를 상속하고 `detect(df) → DetectionResult`를 구현한다.
FraudLayer와 동일한 오케스트레이션 패턴을 따른다.

```
실행 흐름:
  1. validate_input(df, ["debit_amount", "credit_amount"])
  2. _build_registry() → [(rule_id, callable, kwargs), ...] 9개
  3. for rule in registry:
       try: result = func(df, **kwargs)
            if isinstance(result, tuple):   # C07: (Series, metadata)
                rule_results[id] = result[0]
                extra_metadata.update(result[1])
            else:
                rule_results[id] = result
       except: skipped_rules.append(rule_id) + warning
  4. _build_result() → scores(max severity/5), details(행×룰), RuleFlag 리스트
```

**scores 산출 규칙:**
한 행이 C05(severity=4)와 C02(severity=2)에 동시에 해당하면
`max(4/5, 2/5) = 0.8`. 합산이 아닌 **최대값**을 사용한다.

**settings에서 주입하는 파라미터:**
- `period_end_amount_quantile` → C01
- `backdated_threshold_days` → C04
- `zscore_threshold` → C08
- `benford_*` → C07 (settings 전체를 전달)
- `account_pair_rare_percentile` → C09

##### anomaly_rules_simple.py — 피처 기반 룰 (C01~C06, C08)

피처 엔진이 미리 생성한 bool/float 컬럼을 AND/OR 조합하는 단순 마스크 연산.
모든 함수는 `(df, **params) → pd.Series[bool]` 시그니처.
피처 미존재 시 `pd.Series(False, index=df.index)` 반환.

```
c01_period_end_large    is_period_end & (max(debit, credit) > quantile(0.75))
c02_weekend_entry       is_weekend | is_holiday
c03_after_hours_entry   is_after_hours
c04_backdated_entry     abs(days_backdated) > threshold_days (기본 30일)
c05_fiscal_period_mismatch   fiscal_period_mismatch == True
c06_risky_description   description_quality in (missing,poor) | has_risk_keyword in (high,medium)
c08_amount_outlier      abs(amount_zscore) > zscore_threshold (기본 3.0)
```

##### anomaly_rules_statistical.py — 통계 기반 룰 (C07, C09)

C07과 C09는 단순 피처 조회가 아닌 **별도 통계 연산**이 필요하다.

```
c07_benford_violation   (C07)
  ① analyze_benford(first_digit, settings) 호출
  ② is_conforming=True → 전체 False
  ③ is_conforming=False → 개별 자릿수 편차 > MAD 임계값인 자릿수 선별
  ④ 해당 first_digit을 가진 행만 플래그
  ⑤ benford_result를 metadata로 반환 (score_aggregator의 독립 트랙 참조용)

c09_rare_account_pair   (C09)
  ① 차변 뷰(debit_amount > 0)와 대변 뷰(credit_amount > 0) 분리
  ② document_id 기준 inner merge → N:M 복합 분개의 모든 (차변, 대변) 쌍 생성
  ③ (gl_account_dr, gl_account_cr) 빈도 계산 → 하위 percentile 임계값
  ④ 희소 쌍에 속한 document_id의 모든 행 플래그
```

**C09 복합 분개(N:M) 대응:**
회계 전표는 차변 2개 × 대변 3개 같은 복합 분개가 존재한다.
`groupby+apply`(반복문)는 대규모 데이터에서 느리므로,
`merge` 기반 Cartesian Product로 벡터화 연산을 수행한다.
수백만 건에서도 O(n) 수준 성능.

#### 룰별 감사 근거

| 룰  | 감사 근거                                    | 탐지 대상                                  |
|:----|:---------------------------------------------|:-------------------------------------------|
| C01 | PCAOB AS 240 §32(b), FSS 결산 수정 조작     | 월말 근접 + 금액 > Q3 → 기말 대규모 전표    |
| C02 | 감사기준서 240호 A49(c), FSS 비정상 시점     | 토/일/공휴일 전기                           |
| C03 | 감사기준서 240호 A49(c), FSS 비정상 시점     | 22시~06시 심야 전기                         |
| C04 | 감사기준서 240호 A49(c), FSS 횡령 은폐       | abs(전기일-전표일) > 30일 소급              |
| C05 | PCAOB AS 240 §32(b), 기간 귀속 오류          | 회계기간 ≠ 전기월                           |
| C06 | 감사기준서 240호 A49(c), K-SOX §8①1호        | 적요 품질 불량 또는 위험 키워드              |
| C07 | 감사기준서 520호 §5, 240 A45(e)              | 첫째자리 분포 Benford 비적합 자릿수 행      |
| C08 | PCAOB AS 240 §33(b), ISA 315                | abs(Z-score) > 3σ 통계적 이상 금액          |
| C09 | 감사기준서 240호 A49(a), ISA 315             | 차변-대변 계정 쌍 빈도 하위 1%              |

#### 피처 → 룰 매핑

| 룰  | 사용 피처                                  | 원본 컬럼 추가 사용              | 비고                              |
|:----|:-------------------------------------------|:---------------------------------|:----------------------------------|
| C01 | `is_period_end`                            | `debit_amount`, `credit_amount`  | Q3 계산은 detection 내부          |
| C02 | `is_weekend`, `is_holiday`                 | —                                | 피처 OR 조합                      |
| C03 | `is_after_hours`                           | —                                | 직접 사용                         |
| C04 | `days_backdated`                           | —                                | abs() > 30일 임계값               |
| C05 | `fiscal_period_mismatch`                   | —                                | 직접 사용                         |
| C06 | `description_quality`, `has_risk_keyword`  | —                                | 피처 2개 OR 조합                  |
| C07 | `first_digit`                              | —                                | `validation/benford.py` 재사용    |
| C08 | `amount_zscore`                            | —                                | abs() > 3.0 임계값                |
| C09 | —                                          | `gl_account`, `document_id`, 금액 | merge 기반 계정 쌍 빈도 분석     |

#### Scoring

```
per-rule: flagged ? (severity / 5) : 0.0
  C01 (severity 3) → 위반 시 0.6
  C02 (severity 2) → 위반 시 0.4
  C03 (severity 2) → 위반 시 0.4
  C04 (severity 3) → 위반 시 0.6
  C05 (severity 4) → 위반 시 0.8
  C06 (severity 1) → 위반 시 0.2
  C07 (severity 2) → 위반 시 0.4
  C08 (severity 3) → 위반 시 0.6
  C09 (severity 2) → 위반 시 0.4
row_score = max(C01_score, ..., C09_score)
```

max 방식 사용 이유: 이상 징후는 "가장 심각한 징후"가 해당 행의 위험도를 결정한다.
Score Aggregator에서 Layer C 가중치는 0.25.

#### 구현 시 주의사항

**C07 Benford 전체 플래그 vs 자릿수 선별:**
Benford는 데이터셋 전체에 대한 통계 검정이지 행별 판정이 아니다.
전체 행 플래그는 과탐이므로, 비적합 판정 시에도 **편차가 큰 자릿수의 행만** 선별한다.
`benford_result`는 metadata에 포함하여 score_aggregator의 독립 트랙(0.15)이 참조한다.

**C09 복합 분개(N:M) 계정 쌍 생성:**
차변 2개 × 대변 3개인 전표에서 6개 쌍이 Cartesian Product로 생성된다.
`groupby+apply`(반복문)는 느리므로, 차변/대변 뷰를 `merge(on=document_id)`로
inner join하여 벡터화 연산으로 처리한다.

**C06 피처 부분 미존재 대응:**
`description_quality`와 `has_risk_keyword` 중 하나만 존재해도 해당 조건만으로 판정.
둘 다 미존재 시에만 `Series(False)` 반환.

**C04 양방향 소급 판정:**
`days_backdated` 양수(지연)/음수(선전기) 모두 이상이므로 `.abs() > threshold` 사용.
기본 임계값 30일 — `settings.backdated_threshold_days`로 조정 가능.

#### 설계 결정

| 이슈                              | 결정                                                         | 사유                                                           |
|:----------------------------------|:-------------------------------------------------------------|:---------------------------------------------------------------|
| C07: detection vs validation 중복 | `validation/benford.py`의 `analyze_benford()` 직접 호출       | 코드 중복 방지, BenfordResult 재사용                            |
| C07 플래그 방식                   | 비적합 시 편차 큰 자릿수 행만 선별                            | 전체 행 플래그는 과탐. 감사적으로 유의미한 표본 추출             |
| C07 최소 샘플 미달 시             | scores=0.0 + warning (skip 아닌 0점 처리)                    | score_aggregator에서 가중치 적용 시 0이 안전                    |
| C01 "금액 > Q3" 기준              | 전체 DataFrame의 `max(debit, credit)` Q3                     | MVP 단순화. Phase 2에서 계정그룹별 Q3로 확장                    |
| C09 계정 쌍 추출                  | merge 기반 Cartesian Product (벡터화)                        | N:M 복합 분개 대응. groupby+apply 대비 대규모 데이터 성능 우수  |
| C09 "하위 1%" percentile          | `pair_counts.quantile(percentile)` (최소 1)                  | 빈도 기반 판정 — 금액 기반 아님                                 |
| C04 소급 기준                     | `abs(days_backdated) > 30일` (양방향)                        | 양수(지연)/음수(선전기) 모두 이상. settings로 조정 가능          |
| C06 OR 조건                       | quality in (missing,poor) OR risk_kw in (high,medium)        | 적요 미비 또는 위험 키워드 — 어느 하나만으로도 플래그            |
| scores 산출 방식                  | `max(severity / 5 × flagged)` per row                        | severity 5단계를 0~1 범위로 정규화. 합산 시 1.0 초과 위험       |
| 룰별 독립 실행                    | 한 룰 실패(exception)해도 나머지 계속 실행                   | try/except per rule + warning 수집                              |
| 모듈 분할                         | simple(7개) + statistical(2개)                               | C01~C06,C08은 피처 조회, C07/C09만 별도 연산. 100줄 제한 준수   |

#### settings.py 추가 설정

| 설정                            | 타입    | 기본값 | 환경변수                                | 사용 룰 |
|:--------------------------------|:--------|:-------|:----------------------------------------|:--------|
| `backdated_threshold_days`      | `int`   | `30`   | `AUDIT_BACKDATED_THRESHOLD_DAYS`        | C04     |
| `account_pair_rare_percentile`  | `float` | `0.01` | `AUDIT_ACCOUNT_PAIR_RARE_PERCENTILE`    | C09     |
| `period_end_amount_quantile`    | `float` | `0.75` | `AUDIT_PERIOD_END_AMOUNT_QUANTILE`      | C01     |

#### 테스트 결과

```
tests/test_detection/test_anomaly_rules_simple.py — 22개 통과
  C01: 기말+고액 flagged, 기말+저액 not, 비기말 not, 피처 미존재 skip
  C02: 주말 flagged, 공휴일 flagged, 평일 not
  C03: 심야 flagged, 업무시간 not, 피처 미존재 skip
  C04: abs>30 flagged(양방향), abs≤30 not, 피처 미존재 skip
  C05: 불일치 flagged, 일치 not
  C06: missing/poor flagged, high/medium risk flagged, normal+low not
  C08: abs(zscore)>3 flagged, ≤3 not, 피처 미존재 skip

tests/test_detection/test_anomaly_rules_statistical.py — 9개 통과
  C07: Benford 적합 all-false, 비적합 선별 플래그, 피처 미존재 skip, 튜플 반환 확인
  C09: 희소 쌍 flagged, 빈번 쌍 not, 복합 분개 N:M 정상 처리,
       컬럼 미존재 skip, 빈 차변 skip

tests/test_detection/test_anomaly_layer.py — 10개 통과
  통합: DetectionResult 구조, scores 범위 0~1, NaN 없음, C prefix 컬럼,
       rule_flags 8개(C07 제외), flagged_indices 정합, elapsed 기록,
       minimal_df graceful, 빈 df ValueError, C07 미포함 확인

tests/test_detection/test_benford_detector.py — 8개 통과
  BenfordDetector: track_name="benford", DetectionResult 반환, scores 0~1,
       적합 시 전체 0점, metadata에 benford_result 포함,
       rule_flags C07, first_digit 미존재 graceful, 빈 df ValueError
```

> E2E 테스트 결과: [e2e-detection-datasynth.md](../../tests/test_detection/test-results/e2e-detection-datasynth.md)

---

### ⑤ 종합 점수 산출 (score_aggregator.py) — ✅ 구현 완료

```
src/detection/
└── score_aggregator.py    # aggregate_scores() + classify_risk_level()
```

#### 이 모듈이 하는 일

3레이어 탐지의 **최종 단계**로, 각 Layer(A/B/C)와 Benford가 산출한
DetectionResult를 하나의 **종합 anomaly_score**로 합산하여 위험 등급을 분류한다.

```
파이프라인 위치:
  Layer A/B/C  →  score_aggregator  →  DuckDB 적재 + 대시보드 표시

역할:
  ① 가중합 산출: Layer별 scores × weight → 행별 anomaly_score
  ② 위험 등급 분류: High / Medium / Low / Normal
  ③ 자동 승격: Layer A + B 복합 위반 → High 강제
  ④ 위반 룰 집계: 행별 "A01,B03,C07" 문자열 생성
```

BaseDetector를 상속하지 않는 순수 함수 모듈이다.
외부에서는 `aggregate_scores()` 하나만 호출하면 내부 로직이 순차 실행된다.

#### 구현 내용

```python
def aggregate_scores(
    df: pd.DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """여러 트랙의 DetectionResult를 종합하여 최종 anomaly_score 산출.

    로직:
    1. weights가 None이면 LAYER_WEIGHTS 사용 (키를 str로 통일)
    2. results를 {track_name: result} dict로 변환
    3. 각 result.scores를 reindex(df.index, fill_value=0.0)로 인덱스 정합
    4. anomaly_score = sum(scores * weight) → clip(0.0, 1.0)
    5. 결과에 없는 트랙은 0점 처리 + logger.warning (에러 아님)
    6. classify_risk_level → _apply_auto_escalation → _collect_flagged_rules
    반환: DataFrame(anomaly_score, risk_level, flagged_rules), index=df.index
    """

def classify_risk_level(scores: pd.Series) -> pd.Series:
    """anomaly_score → risk_level 변환.
    Normal→Low→Medium→High 순서로 덮어쓰기. RISK_THRESHOLDS 참조."""

def _apply_auto_escalation(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Layer A ≥ 1개 위반 AND Layer B ≥ 2개 위반 → risk_level = High 강제.
    details > 0의 행별 sum으로 판정. Layer A/B 결과 없으면 no-op."""

def _collect_flagged_rules(
    results: list[DetectionResult],
    index: pd.Index,
) -> pd.Series:
    """모든 result.details를 가로 concat → boolean mask → dot product 문자열 합성.
    apply(axis=1) 대신 mask.dot(cols + ",") 벡터화로 100만 행 1초 미만."""
```

#### Scoring

```
anomaly_score = Layer_A × 0.15 + Layer_B × 0.45 + Layer_C × 0.25 + Benford × 0.15

위험 등급:
  High:   anomaly_score > 0.7  또는  Layer_A 위반 + Layer_B 2개 이상 (자동 승격)
  Medium: anomaly_score > 0.4
  Low:    anomaly_score > 0.2
  Normal: anomaly_score ≤ 0.2
```

> ⚠️ 초기 설계값. Phase 1 완료 후 DataSynth 레이블 대비 back-testing으로 튜닝 필수.

#### Phase별 가중치 변화

| Phase    | 가중치                                                                              |
|:---------|:------------------------------------------------------------------------------------|
| Phase 1  | `layer_a(0.15) + layer_b(0.45) + layer_c(0.25) + benford(0.15)`                    |
| Phase 2  | `rule(0.20) + xgboost(0.25) + vae(0.20) + benford(0.15) + duplicate(0.20)`         |
| Phase 3  | `rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + dup(0.15) + nlp(0.10) + graph(0.15)` |

Phase 확장 시 weights dict만 교체하면 함수 로직 변경 없이 트랙 수 확장 가능.

#### 구현 시 주의사항

**인덱스 정합성:**
각 DetectionResult.scores의 index가 df.index와 일치하지 않을 수 있다.
`reindex(df.index, fill_value=0.0)` 방어 코드로 NaN/행 밀림 방지 필수.

**에러 격리:**
개별 DetectionResult 처리를 try/except로 감싸서 하나의 레이어가 실패해도
나머지 레이어는 계속 합산. 실패한 레이어는 score=0 처리 + logger.warning.

**가중치 정규화:**
weights 합이 1.0 미만일 수 있음 (일부 레이어 누락 시). 정규화하지 않는다.
누락 레이어는 0점이 올바른 동작이며, 가중치 재분배는 점수를 인위적으로 부풀린다.

**_collect_flagged_rules 성능 최적화:**
`apply(axis=1, lambda)` 방식은 내부 Python for 루프라 100만 행에서 수십 초 병목.
`mask.dot(cols_with_comma)` 행렬 내적으로 C 레벨에서 문자열 합성하여 1초 미만 처리.

```python
mask = combined_details > 0
cols_with_comma = mask.columns + ","
flagged_str = mask.dot(cols_with_comma).str.rstrip(",")
```

**Benford 특수 처리:**
Benford는 전체 분포 판정이므로 모든 행에 동일 점수가 채워져 온다.
score_aggregator에서 별도 분기 불필요. 100건 미만으로 skip된 경우 scores=0.0.

#### 설계 결정

| 이슈                            | 결정                                                     | 사유                                                           |
|:--------------------------------|:---------------------------------------------------------|:---------------------------------------------------------------|
| Benford 별도 가중치 vs C07 포함 | Benford를 C07과 별도 가중치(0.15)로 분리                 | AUDIT_DOMAIN_FINAL §7 설계 — 통계적 배경 점수로 독립 취급      |
| Layer 점수 정규화               | 각 Layer의 scores를 그대로 사용 (이미 0~1 정규화됨)      | 각 Layer에서 severity/5 × flagged 방식으로 산출 완료            |
| 자동 승격 로직 위치             | `_apply_auto_escalation()` 별도 함수                     | 가중합과 독립적인 비즈니스 룰 — 테스트 분리 용이                |
| 출력 컬럼                       | anomaly_score, risk_level, flagged_rules (3개)           | 대시보드 필터링 + DuckDB 저장 + export 용                      |
| 가중치 설정 위치                | constants.py LAYER_WEIGHTS + weights 파라미터 override   | back-testing 후 .env 또는 호출 시 override                     |
| flagged_rules 성능              | dot product 벡터화 (apply 대신)                          | 100만 행에서 수십 초→1초 미만으로 개선                          |
| 가중치 정규화                   | 안 함 (누락 레이어는 0점이 정답)                         | 재분배하면 나머지 레이어 점수가 부풀려져 오탐 증가              |
| BaseDetector 상속               | 안 함 (순수 함수 모듈)                                   | 탐지기가 아닌 결과 집계기 — detect() 인터페이스 불필요          |
| Benford scores 분리 방법        | AnomalyLayer에서 별도 반환 받아 분리                     | Benford는 행별 점수가 아닌 전체 분포 판정 → 전체에 동일 점수    |

#### 테스트 결과

```
tests/test_detection/test_score_aggregator.py — 12개 통과
  TestAggregateScores     — 3개 (기본가중합/누락레이어/커스텀가중치)
  TestClassifyRiskLevel   — 4개 (High/Medium/Low/Normal 경계값)
  TestAutoEscalation      — 2개 (승격 발동/미발동)
  TestFlaggedRules        — 1개 (comma-separated 형식)
  TestEdgeCases           — 2개 (score clamp/비연속 인덱스 보존)
```

> E2E 테스트 결과: [e2e-detection-datasynth.md](../../tests/test_detection/test-results/e2e-detection-datasynth.md)

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

1. - [x] `constants.py` — RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS 상수
2. - [x] `base.py` — BaseDetector(ABC), DetectionResult, RuleFlag, validate_input
3. - [x] `__init__.py` — public API export
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

#### 1. NLPAnalyzer — 적요 NLP (kiwipiepy + Transformer)

**현재 한계**: C06은 키워드 정확 매칭 + 길이 기반. 은어/동의어/맥락 미탐.

**NLP 보완**: kiwipiepy 형태소 분석 → Transformer(Qwen3-8B) 임베딩 기반 의미 유사도 계산.
MissingDocumentation, LatePosting 등 추가 유형 탐지.

> NLP & Transformer 동기 및 상세 설계: [08-llm.md](08-llm.md) §NLP & Transformer 참조

#### 2. GraphDetector — 그래프 순환 탐지

**현재 한계**: B10은 2-hop만. N-hop 순환, 복잡한 자금 순환 경로 미탐.

**그래프 보완**: 거래 네트워크를 방향 그래프로 구성 → 순환 탐지 알고리즘(DFS) 적용.
CircularTransaction, TransferPricingAnomaly 탐지.

---

## 테스트 전략

### 모듈별 테스트 계획

| 테스트 파일                    | 대상 모듈              | 예상 케이스 수 | 주요 검증 항목                                     |
|:-------------------------------|:-----------------------|:---------------|:---------------------------------------------------|
| `test_constants.py`            | constants.py           | 16건 ✅        | RULE_CODES 22개, SEVERITY_MAP 범위, LAYER_WEIGHTS 합계, enum 값 |
| `test_base.py`                 | base.py                | 20건 ✅        | validate_input, RuleFlag, DetectionResult, BaseDetector ABC/헬퍼 |
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

---

## 신규 탐지 룰 후보 (audit_domain_additional.md 기반)

> 아래는 감사기준서 갭 분석에서 도출된 신규 룰 후보. 22개 기존 룰과 별도로 Phase 1b 확장 또는 Phase 2에서 구현 검토.
> 상세 분석: [audit_domain_additional.md](../audit_domain_additional.md) 참조.

### Phase 1 구현 후보 (현재 29컬럼으로 가능)

#### 역분개 패턴 탐지

- 근거: 감사기준서 240호 (기말 조정·재분개 중점 검사)
- 로직:
  1. 1:1 매칭: 동일 gl_account + 동일 금액 + 반대 방향(차↔대) ±1일
  2. N:M 분할 역분개 (Rolling Sum Zero-Out): gl_account × created_by 그룹에서 윈도우 내 순액 ≈ 0
  3. Reversing vs Correcting: SAP RRC 05(accrual 자동)=정상, RRC 01/02(수동)=검토 대상
  4. line_text 키워드: "수정", "정정", "오류", "결산조정", "역분개"
  5. 기말 30일 이내 역분개 집중도 가중

#### Top-side JE (경영진 조정 전표)

- 근거: 감사기준서 240호, PCAOB AS 2401
- 로직 (Arbutus 가중 점수):
  - source='manual' + 기말 시점 + 자기승인/승인없음 + 비정상계정 + 고액 + 적요 부실
  - 각 특성에 이진 점수 → 합산 → 임계값 초과 시 Top-side JE 의심

#### 비정상 시간대 입력자 집중

- 근거: KLCA IT 체크리스트
- 로직:
  - 비정상 시간대: 22:00~06:00 (한국 실무: 18:30~22:00은 야근으로 저위험)
  - 사용자별 심야/비근무일 전표 비율 → 전체 평균 대비 3σ 이상 = 이상치
  - 결산기(12~1월) 야근은 정상 취급 (동적 임계값)

### DataSynth 컬럼 추가 시 구현 가능

#### 승인 프로세스·승인자 계층 (approval.rs 활성화)

- 근거: 감사기준서 315호/330호, 1100호
- 필요 컬럼: approved_by, approval_timestamp, approval_level
- 로직: 승인 누락률, 승인 지연, 레벨 건너뜀, 자기승인 정밀화
- DataSynth: approval.rs 이미 구현됨. Rust 3개 파일 수정 + YAML 활성화 필요

#### 증빙 존재 확인

- 근거: 감사기준서 240호, 500호, 한국 세법
- 필요 컬럼: has_attachment, supporting_doc_type
- 로직: has_attachment=False + 수기 + 고액 → 증빙 누락. 3만원 초과 적격증빙 미수취 탐지. 29,000원×N건 분할 회피

#### 컷오프 (납품일 vs 전기일)

- 근거: 감사기준서 315호, 330호, K-IFRS 15
- 필요 컬럼: delivery_date
- 로직: |posting_date - delivery_date| > N영업일. 12월 마지막 2주 집중 분석

#### 증빙 금액 불일치

- 근거: 감사기준서 500호
- 필요 컬럼: invoice_amount, tax_amount, supply_amount
- 로직: |debit_amount - invoice_amount| > 허용오차. 부가세 10% 검증

#### 전표 수정 이력

- 근거: KLCA IT 체크리스트 4.3~4.5
- 필요 컬럼: changed_by, change_date, changed_field
- 로직: SAP에서 금액/계정 직접 수정 불가 → 역분개로 탐지. 텍스트 변경만 추적

#### IP 추적

- 근거: KLCA IT 체크리스트
- 필요 컬럼: ip_address
- 로직: 사내(10.x.x.x) vs VPN(10.10.x.x) vs 외부. 희귀 IP + 고액/심야 = 비정상

#### 전표번호 연속성

- 근거: 감사기준서 240호, 315호
- 필요 컬럼: document_number (순차 int)
- 로직: 회사코드+연도+전표유형별 분할 → LEAD 갭 탐지. SAP Document Type: SA/KR/DR/AA 등

### Phase 2 구현 (ML/추가 데이터)

- 계정분류 적정성: 계정-거래유형 매핑 마스터 → MisclassifiedAccount ML
- 회계추정치 편의: 다기간 시계열 → TrendBreak (ISA 540 소급 검토)
- 재무제표-장부 대사: Trial Balance 테이블 → GL 잔액 교차검증
- 통제테스트(TOE): approval 데이터 → 승인 누락률/지연/우회율 임계값 검증
- 배치 전표 이상: source='batch' → 기말 집중/대량 동시 생성

### Phase 3 구현 (LLM/NLP)

- 경제적 실질: 계정-거래유형 불일치 + NLP 적요 분석
- 유의적 거래 합리성: LLM이 적요+계정+금액 분석 → 보조 의견
