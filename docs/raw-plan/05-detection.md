# 05. 룰 기반 이상탐지 (Detection) [Phase 1b — 의존: 03-feature, 04-validation]

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
> Latest PHASE1 role note (2026-04-28): this raw plan is historical. Current PHASE1 is not a final answer classifier and must not be judged only by DataSynth `is_fraud` / `is_anomaly` or document-level precision/recall. PHASE1 first captures rule/policy/anomaly candidates broadly, then classifies them into normal exceptions, auditor review targets, and high-risk candidates by materiality, evidence strength, case priority, company exception policy, and rule combinations. Use `docs/DETECTION_RULES.md`, `docs/PHASE1_RULE_RELATIONSHIP_MAP.md`, and `docs/metrics.md` for the current contract.

> Historical plan note (updated 2026-04-28): 이 문서는 초기 24개 룰 설계 기록이다. 현재 PHASE1은 32개 L1~L4 룰과 case-level queue를 사용한다. L3-12는 L1-06과 분리된 `access_scope_review` 업무범위 검토 신호이며, `work_scope_combo_score` 보강 기준은 [PHASE1_RULE_RELATIONSHIP_MAP.md](../PHASE1_RULE_RELATIONSHIP_MAP.md)를 따른다. row-level detector `details`는 여전히 detector별 score를 담지만, PHASE1 case priority는 `src/detection/rule_scoring.py`의 `signal_strength -> normalized_score` 정규화 후 `src/detection/phase1_case_builder.py`에서 evidence type별로 합산한다. 최신 운영 기준은 [DETECTION_RULES.md](../DETECTION_RULES.md)와 [PHASE1_RULE_RELATIONSHIP_MAP.md](../PHASE1_RULE_RELATIONSHIP_MAP.md)를 따른다.

## 목적

검증 완료된 DataFrame에 **L1/L2/L3/L4 24개 룰(if/threshold 기반)**을 적용하여 이상을 탐지하고,
종합 anomaly_score를 산출한다. ML/DL 라이브러리를 사용하지 않으며,
pandas·numpy·scipy만으로 구현한다.
BaseDetector 추상 클래스로 트랙 추가를 표준화.

본 문서는 **Phase 1b(MVP)** 범위의 룰 기반 탐지만 다룬다.
Phase 2 ML 탐지기(XGBoost, VAE+IF 앙상블)는 [05a-detection-ml.md](05a-detection-ml.md) 참조.

### 05-detection vs 05a-detection-ml 역할 구분

| 항목        | 05-detection (본 문서)                    | 05a-detection-ml                        |
|:------------|:------------------------------------------|:----------------------------------------|
| Phase       | 1b (MVP)                                  | 2b                                      |
| 방식        | if/threshold 룰 24개                      | XGBoost 지도학습 + VAE+IF 비지도학습    |
| 사용 패키지 | pandas, numpy, scipy                      | xgboost, scikit-learn, torch            |
| 선행 의존   | 03-feature, 04-validation                 | 03a-preprocessing, 05-detection         |
| 탐지 대상   | "사람이 정한 조건"에 해당하는 전표         | "데이터에서 학습한 패턴"과 유사한 전표   |
| 단독 활용   | 가능 (ML 없이도 감사 결과 산출)           | 룰 기반 결과와 합산하여 사용            |

### 24개 룰 선정 근거

DataSynth 52개 anomaly 유형을 3축 평가로 선별하여 Phase 1에 배치.

- **축 1**: 법규 근거 (KICPA 240, 감사법, FSC 규정) 0~3점
- **축 2**: FSS 실제 발생 빈도 (189건 제재 사례) 0~3점
- **축 3**: 39컬럼 스키마로 즉시 탐지 가능 여부 0~3점
- 합계 7~9점 → Tier 1(Must) → Phase 1 = 22개 유형 = **24개 룰**

Phase 1만으로 FSS 6대 주요 감사 검토 패턴(가공거래·기말조정·횡령은폐·관계사순환·승인위반·비정상시점)에
대응하는 후보 모집단을 넓게 커버하며, AICPA/CAQ CAAT 15개 시나리오 중 14개, PCAOB A49 의심 특성 11개를 검토 큐 기준으로 매핑한다.

> **탐지 체계 상세 근거**: `docs/DETECTION_RULES.md` §4~§5

---

## 데이터 흐름

```
[검증 완료 DataFrame] (from validation/ — is_pipeline_ready=True)
       ↓
① base.validate_input(df)                    → 필수 컬럼 존재 확인 + 빈 DataFrame 차단
       ↓
② integrity_layer.detect(df)                 → L1-01~L1-03 무결성 검사
       ↓ (A 위반 시 경고 플래그, 계속 진행)
③ fraud_layer.detect(df)                     → L4-01~L2-04 통제우회·자금유출 검토 신호
       ↓
④ anomaly_layer.detect(df)                   → L3-04~L3-09 이상 징후 (L4-02=Benford)
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
    """검증 완료 DataFrame → L1/L2/L3/L4 탐지 → 종합 점수 산출.

    Returns: DetectionPipelineResult(data, results, risk_summary, elapsed)
    data:         anomaly_score + risk_level 컬럼 추가된 DataFrame
    results:      list[DetectionResult] — L1~L4 상세 결과
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
├── integrity_layer.py       # L1: 데이터 무결성 (L1-01~L1-03) — MVP
├── fraud_layer.py           # L2: 오케스트레이터 (L4-01~L2-04) — MVP
├── fraud_rules_feature.py   # L2: 피처 기반 룰 (L4-01, L2-01, L1-04, L3-02)
├── fraud_rules_groupby.py   # L2: groupby 기반 룰 (L2-02, L2-03, L2-04)
├── fraud_rules_access.py    # L2: 접근통제 룰 (L1-05, L1-06, L1-07, L3-03)
├── anomaly_layer.py              # L3/L4: 오케스트레이터 (L3-04~L3-08, L4-03~L3-09)
├── anomaly_rules_simple.py       # L3/L4: 피처 기반 룰 (L3-04~L3-08, L4-03, L3-09)
├── anomaly_rules_statistical.py  # L3/L4: L4-04 계정 쌍 + L4-02 Benford 공용 함수
├── benford_detector.py           # Benford 독립 트랙 (L4-02, 가중치 0.15)
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
├── constants.py     # 24개 룰 메타데이터 + 레이어/위험등급 상수
└── base.py          # BaseDetector ABC + DetectionResult + RuleFlag + validate_input()
```

#### 이 모듈이 하는 일

detection 파이프라인은 여러 종류의 탐지기(L1/B/C, Phase 2 ML, Phase 3 NLP/Graph)가
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

24개 룰의 ID·이름·심각도·가중치를 한 곳에서 관리한다.
- Layer 구현체에서 `"L1-01"` 같은 문자열을 직접 쓰지 않고 constants에서 참조
- `_create_rule_flag("L1-01", ...)` 호출 시 이름·심각도가 자동 채워짐
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
rule_results = {"L1-01": series_a01, "L1-02": series_a02}
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

### ② L1: 데이터 무결성 (integrity_layer.py) — ✅ 구현 완료

```
src/detection/
└── integrity_layer.py    # IntegrityDetector(BaseDetector) — L1-01~L1-03
```

#### 이 모듈이 하는 일

L1/L2/L3/L4 탐지의 **첫 번째 단계**로, "이 전표 데이터를 신뢰할 수 있는가?"를 판정한다.
L2(통제우회·자금유출 검토 신호)·C(이상 징후)가 의미 있는 결과를 내려면,
**데이터 자체가 올바르게 기록되었는지** 먼저 확인해야 한다.

```
파이프라인 위치:
  L1/L2 Validation (Gate)  →  L1 (감사 증거)  →  L2/C (탐지)

역할 차이:
  L1/L2: "이 파일을 읽을 수 있는가?"  → is_valid=False면 중단
  L1: "이 '행'의 무결성 점수는?"  → score 부여 후 계속 진행
```

L1 Validation과의 핵심 차이는 **판단 단위와 출력**이다:

```
┌──────────────┬──────────────────┬──────────────────────┐
│              │ L1/L2 Validation │ L1 Detection     │
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
- 해당 전표에서 L1-05(자기 승인)이나 L3-06(심야 전기)을 추가 발견하면 **감사 증거가 더 강력**해짐
- 중단하면 "무결성 이슈 + 부정 징후 동시 발생"이라는 중요한 패턴을 놓침

#### 구현 내용

```python
class IntegrityDetector(BaseDetector):
    """L1-01~L1-03: 전표 데이터 무결성 검증."""

    def __init__(self, settings=None, tolerance=None, chart_of_accounts=None):
        # tolerance: settings.balance_tolerance (기본 1.0원) 또는 명시적 주입
        # chart_of_accounts: set[str] — None이면 L1-03 skip

    def detect(self, df) -> DetectionResult:
        # L1-01→L1-02→L1-03 순차 실행, 룰별 try/except 격리
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
| L1-01 | ISA 240 §32(a), K-SOX §8①2호         | 차변합 ≠ 대변합 → 복식부기 위반   |
| L1-02 | ISA 240 A45(d) "계정번호가 없는 기입" | 필수필드(9컬럼) NULL → 통제 미작동 |
| L1-03 | ISA 240 A45(a) "거의 사용되지 않는 계정" | CoA에 없는 계정 → 가공 계정 의심 |

#### 피처 매핑

- L1-01: `debit_amount`, `credit_amount`, `document_id` (원본 컬럼 직접 사용)
- L1-02: 필수 9컬럼 (schema.yaml `required: true`)
- L1-03: `gl_account` (원본) + CoA 참조 (`chart_of_accounts: set[str]` 외부 주입)

#### Scoring

```
per-rule: flagged ? (severity / 5) : 0.0
  L1-01 (severity 5) → 위반 시 1.0
  L1-02 (severity 2) → 위반 시 0.4
  L1-03 (severity 3) → 위반 시 0.6
row_score = max(L1-01_score, L1-02_score, L1-03_score)
```

max 방식 사용 이유: 무결성은 "가장 심각한 위반"이 해당 행의 위험도를 결정한다.

Score Aggregator에서 L1 가중치는 0.15 (최저)이나,
**L1 위반 + L2 2개 이상 → 자동 High 등급** 에스컬레이션 적용.

#### 구현 시 주의사항

**L1-01 groupby NaN 키 문제:**
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

**L1-02 vs L1 역할 분담 (이중 안전장치):**
L1(schema_validator)이 컬럼 존재+타입을 검증하여 gate 역할.
L1-02는 L1 통과 후에도 남아있는 **행 단위 NULL**을 잡는 fallback.
정상 흐름에서 L1-02 플래그 = 0이 기대값. 플래그 발생 시 L1 검증 로직 점검 필요.

#### 설계 결정

| 이슈                         | 결정                                          | 사유                                                         |
|:-----------------------------|:----------------------------------------------|:-------------------------------------------------------------|
| L1-01 차대 불일치 tolerance    | `settings.balance_tolerance` (기본 1.0원)      | 부동소수점 오차 허용. settings 오버라이드 + DI 지원            |
| L1-01 groupby 대상             | `document_id` 단독                             | `fiscal_year + company_code` 복합키는 Phase 2 확장            |
| L1-01 NaN document_id          | 고유 더미 키 부여, 개별 행 취급                 | groupby NaN drop 방지 + 행 간 잘못된 합산 방지                |
| L1-02 vs L1 역할               | L1=gate, L1-02=행 단위 fallback                  | L1 통과 후에도 개별 행 NULL 잡아 감사 증거 생성               |
| L1-03 CoA 없을 때              | skip + warning 반환 (에러 아님)                | 외부 ERP 데이터에는 CoA 미포함 가능                            |
| L1-03 타입 매칭                | `astype(str)` 통일                             | schema는 int, CoA는 str일 수 있음                             |
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

### ③ L2: 통제우회·자금유출 검토 신호 (fraud_layer.py) — ✅ 구현 완료

#### L2가 하는 일

L1/L2/L3/L4 탐지 체계에서 **핵심 레이어**(가중치 0.45)이다.
L1가 "이 데이터를 믿을 수 있는가?"를 검증한다면,
L2는 **"이 전표가 부정·횡령의 징후를 보이는가?"** 를 판정한다.

11개 룰(L4-01~L2-04)이 각각 독립적으로 부정 패턴 하나를 탐지하며,
하나의 전표가 여러 룰에 동시에 걸릴 수 있다 (예: L3-02 수기 전표 + L1-04 한도 초과).

#### 왜 필요한가

감사기준서 240호 §32는 **"경영진의 내부통제 무력화 위험에 대한 평가와 관계없이"**
전표의 적정성을 테스트하라고 의무화한다.
이 의무를 자동화한 것이 L2의 10개 룰이다.

```
법규 근거 → 룰 도출:

감사기준서 240호 §32(c)  "비정상 유의적 거래의 사업상 합리성 평가"
  → L4-01 매출 이상 변동 — FSS 189건 분석 결과 가공매출이 최다 부정 패턴

감사기준서 240호 A45(b)  "통상 분개하지 않는 개인에 의한 기입"
  → L3-02 수기 전표 — 자동 프로세스를 우회하여 수기 입력된 고액 전표

감사기준서 240호 A45(e)  "단수(round number) 또는 일관된 끝자리"
  → L2-01 승인한도 직하 — 의도적으로 승인 한도 바로 아래에 금액을 맞추는 분할 징후

외감법 §8①5호  "업무 분장과 책임"
  → L1-05 자기 승인, L1-06 직무분리 위반
    오스템임플란트(2021) 사례: 1인이 입력·승인·이체 전부 수행 → 2,215억 횡령

외감법 §8②  "내회관 우회 금지"
  → L1-07 승인 생략 — 승인 절차 없이 처리된 한도 초과 전표

감사기준서 550호 §23  "특수관계자 거래의 사업상 합리성"
  → L3-03 관계사 거래 검토 신호 — 관계사 거래 모집단 및 후속 구조 분석 후보
```

L1(무결성)만으로는 "차대변이 맞고 필수필드가 있다"는 것만 확인할 수 있고,
L3/L4(이상 징후)는 시점·금액 패턴만 보는 보조 지표이다.
**부정 여부를 직접 판정하는 것은 L2뿐**이며,
이것이 가중치가 0.45 (전체의 거의 절반)인 이유이다.

#### 파일 구조

100줄 제한을 맞추기 위해 **데이터 접근 패턴 기준**으로 4개 파일로 분할.

```
src/detection/
├── fraud_layer.py             # FraudLayer 오케스트레이터 — 룰 레지스트리 순회 + 결과 조합
├── fraud_rules_feature.py     # 피처 기반 룰: L4-01, L2-01, L1-04, L3-02 — bool 컬럼 마스크 연산
├── fraud_rules_groupby.py     # groupby 기반 룰: L2-02, L2-03, L2-04 — 원본 컬럼 집계/중복 판정
└── fraud_rules_access.py      # 접근통제 룰: L1-05, L1-06, L1-07, L3-03 — 권장 컬럼 의존 (skip 가능)
```

| 서브모듈                  | 분할 근거                                               | 포함 룰            |
|:--------------------------|:-------------------------------------------------------|:-------------------|
| `fraud_rules_feature.py`  | 피처 엔진이 생성한 bool/float 컬럼을 직접 조합           | L4-01, L2-01, L1-04, L3-02 |
| `fraud_rules_groupby.py`  | 원본 컬럼 groupby + window 비교. 연산 비용 높음          | L2-02, L2-03, L2-04      |
| `fraud_rules_access.py`   | 권장 컬럼(`created_by`, `source` 등) 의존. skip 확률 높음 | L1-05, L1-06, L1-07, L3-03 |

#### 각 파일의 역할

##### fraud_layer.py — 오케스트레이터

FraudLayer 클래스가 BaseDetector를 상속하고 `detect(df) → DetectionResult`를 구현한다.
내부에서 룰 레지스트리(`_build_registry()`)를 순회하며 서브모듈의 함수를 호출한다.

```
실행 흐름:
  1. validate_input(df, ["debit_amount", "credit_amount"])
  2. _build_registry() → [(rule_id, callable, kwargs), ...] 11개
  3. for rule in registry:
       try: rule_results[rule_id] = func(df, **kwargs)
       except: skipped_rules.append(rule_id) + warning
  4. _build_result() → scores(max severity/5), details(행×룰), RuleFlag 리스트
```

**scores 산출 규칙:**
한 행이 L4-01(severity=5)과 L2-01(severity=3)에 동시에 해당하면
`max(5/5, 3/5) = 1.0`. 합산이 아닌 **최대값**을 사용한다.
합산하면 이론상 2.0을 초과하여 score_aggregator의 0~1 정규화가 깨지기 때문이다.

**settings에서 주입하는 파라미터:**
- `zscore_threshold` → L4-01
- `duplicate_payment_window_days` → L2-02
- `sod_process_threshold` → L3-12 업무범위 검토 fallback (L1-06 점수에는 미반영)
- `audit_rules.yaml sod_toxic_pairs` → L1-06 Toxic Pair 5쌍
- `audit_rules.yaml sod_role_thresholds` → L3-12 직급별 업무범위 검토 임계값

##### fraud_rules_feature.py — 피처 기반 룰 (L4-01, L2-01, L1-04, L3-02)

피처 엔진이 미리 생성한 bool/float 컬럼을 AND/OR 조합하는 단순 마스크 연산.
모든 함수는 `(df, **params) → pd.Series[bool]` 시그니처.
피처 미존재 시 `pd.Series(False, index=df.index)` 반환.

```
b01_revenue_manipulation  is_revenue_account & (amount_zscore > threshold)
b02_near_threshold        is_near_threshold.fillna(False)
b03_exceeds_threshold     exceeds_threshold.fillna(False)
b08_manual_override       is_manual_je.fillna(False) & exceeds_threshold.fillna(False)
```

##### fraud_rules_groupby.py — groupby 기반 룰 (L2-02, L2-03, L2-04)

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

b11_expense_capitalization
  ① 차변 뷰: debit_amount > 0 & gl_account.startswith("15") (자산 계정)
  ② 대변 뷰: credit_amount > 0 & gl_account.startswith("6") (비용 계정)
  ③ inner merge(on=document_id) → 동일 전표 내 자산↔비용 조합 추출
  ④ 해당 document_id의 모든 행 플래그
```

**L2-02 양방향 diff가 필요한 이유:**
단순 `diff()`만 쓰면 그룹 첫 행이 NaT → 중복 쌍의 원본 건이 누락된다.
`diff()` (앞 행과의 차이) + `diff(-1).abs()` (뒷 행과의 차이) 양방향을 OR 조합하여
모든 중복 행을 빠짐없이 포착한다.

```python
# 양방향 diff 패턴
diff_forward = grouped["posting_date"].diff()
diff_backward = grouped["posting_date"].diff(-1).abs()
is_duplicate = (diff_forward <= window) | (diff_backward <= window)
```

##### fraud_rules_access.py — 접근통제 룰 (L1-05, L1-06, L1-07, L3-03)

`created_by`, `business_process`, `source`, `company_code` 등 **권장 컬럼**에 의존.
외부 ERP 데이터에는 이 컬럼이 없을 수 있으므로 skip 확률이 가장 높은 그룹이다.

```
b06_self_approval
  Case A: approved_by 존재 → created_by == approved_by (DataSynth: 항상 이 경로)
  Case B: approved_by 부재 → 수기 소스 + created_by 존재 = 자기 승인 추정 (외부 데이터 fallback)

  정밀화 완료 (#19g): 111,569건(10.08%) → 1,530건(0.14%). 98.6% 감소.
    ① automated_system 제외 (ERP 자동 전기, 71% 과탐 원인)
    ② 소액 제외: max(debit, credit) ≤ approval_thresholds[0] (10M) 제외
    ③ NaN 방어: user_persona.fillna(""), 금액 .fillna(0)

b07_segregation_of_duties  (하이브리드 3단계)
  ① automated_system 제외 (ERP 자동 전기는 인간 SoD 대상 아님)
  ② Toxic Pair: 위험 프로세스 쌍 동시 관여 → 직급 불문 Critical
     TRE+P2P, TRE+O2C, O2C+P2P, H2R+O2C, H2R+P2P
  ③ In-Process: sod_conflict_type 존재 → 해당 행 High
  ④ Role-based: junior >1, senior >3 → L3-12 업무범위 검토 후보 (L1-06 점수 미반영)

b09_skipped_approval
  exceeds_threshold & (source != 'automated')

b10_circular_intercompany  (MVP: 관계사 전표 존재 감지)
  is_intercompany == True인 행을 flag. 실제 순환 탐지는 Phase 2 GraphDetector.
```

**L1-06 direct SoD + L3-12 업무범위 검토 분리:**
단순 프로세스 수 세기(이전: 99.96% 과탐)를 3단계 정밀 판정으로 교체.
L1-06은 In-Process Conflict와 direct SoD marker만 점수화한다.
Toxic/review pair와 Role-based 임계값은 L3-12/work-scope review로 분리한다.

```python
# 하이브리드 판정 흐름
# 1. automated_system 제외
human_df = df[df["user_persona"] != "automated_system"]
# 2. Toxic Pair: 사용자별 프로세스 집합 → 위험 쌍 포함 여부
user_procs = human_df.groupby("created_by")["business_process"].apply(frozenset)
toxic_violators = {u for u, p in user_procs.items() if any(pair <= p for pair in TOXIC_PAIRS)}
# 3. In-Process: sod_conflict_type 존재 여부
# 4. L3-12 Role-based: persona별 허용 프로세스 수 초과 여부
```

#### 피처 → 룰 매핑

| 룰  | 사용 피처                              | 원본 컬럼 추가 사용                    | 비고                         |
|:----|:---------------------------------------|:---------------------------------------|:-----------------------------|
| L4-01 | `is_revenue_account`, `amount_zscore`  | —                                      | 피처 2개 조합                |
| L2-01 | `is_near_threshold`                    | —                                      | 피처 직접 사용               |
| L1-04 | `exceeds_threshold`                    | —                                      | 피처 직접 사용               |
| L2-02 | —                                      | `auxiliary_account_number`, 금액, 날짜  | 원본 groupby (피처 없음)     |
| L2-03 | —                                      | `gl_account`, 금액, `posting_date`     | 원본 groupby (피처 없음)     |
| L1-05 | —                                      | `created_by`, `source`                 | 권장 컬럼 — 없으면 skip      |
| L1-06 | —                                      | `created_by`, `business_process`, `user_persona`, `sod_violation`, `sod_conflict_type` | direct SoD conflict |
| L3-02 | `is_manual_je`, `exceeds_threshold`    | —                                      | 피처 조합                    |
| L1-07 | `exceeds_threshold`                    | `source`, `created_by`                 | 피처 + 원본 혼합             |
| L3-03 | `is_intercompany`                      | `company_code`, `trading_partner`      | MVP: 관계사 존재 감지 + IC 상대 식별 |
| L2-04 | —                                      | `gl_account`, `document_id`            | merge 기반 계정 조합 탐지    |

#### 설계 결정

| 이슈                            | 결정                                          | 사유                                                         |
|:--------------------------------|:----------------------------------------------|:-------------------------------------------------------------|
| 권장 컬럼 미존재 시             | 해당 룰 skip + warning (에러 아님)            | graceful degradation — 외부 데이터에 권장 컬럼 없을 수 있음   |
| L2-02 중복 판정 window            | 30일 (`settings.duplicate_payment_window_days`) | 기간 내 중복 지급 탐지. settings 오버라이드 가능             |
| L2-02 diff 방향                   | 양방향 (forward + backward)                   | 단방향 시 그룹 첫 행 NaT → 원본 건 누락 방지                |
| L2-03 중복 판정 기준              | 동일 일자 (exact match)                       | L2-02와 차별화: L2-02=기간 내 유사, L2-03=정확 중복                |
| L4-01 "통계 임계값"               | `amount_zscore > settings.zscore_threshold`   | Z-score 3.0 기본값, settings에 이미 정의                     |
| L1-06 direct SoD / L3-12 업무범위 | L1-06은 direct conflict, L3-12는 Toxic Pair + Role-based 검토 | 단순 nunique와 role breadth는 L1-06 점수에서 제외 |
| L3-03 순환 패턴 depth             | MVP: 관계사 전표 존재 감지만                  | 실제 n-hop 순환은 Phase 2 GraphDetector에서 구현              |
| scores 산출 방식                | `max(severity / 5 × flagged)` per row         | severity 5단계를 0~1 범위로 정규화. 합산 시 1.0 초과 위험     |
| 룰별 독립 실행                  | 한 룰 실패(exception)해도 나머지 계속 실행     | try/except per rule + warning 수집                           |
| L3-02 "고액" 기준                 | `exceeds_threshold` 피처 재사용               | 별도 기준 불필요 — 승인한도 초과가 "고액" 정의               |
| 수기 전표 코드 관리             | `audit_rules.yaml` → `lru_cache` 로딩         | 스레드 안전, 테스트 격리 가능 (`cache_clear()`)              |
| L2-04 비용→자산 계정 기준        | 차변 `15xx`(자산) + 대변 `6xxx`(비용)          | K-IFRS 계정과목 체계. audit_rules.yaml로 확장 가능           |
| L2-04 탐지 방식                  | L4-04와 동일한 merge 기반 Cartesian Product      | document_id 기준 N:M 복합 분개 대응. 벡터화 연산             |

#### settings.py 추가 설정

| 설정                            | 타입  | 기본값 | 환경변수                              | 사용 룰 |
|:--------------------------------|:------|:-------|:--------------------------------------|:--------|
| `approval_thresholds`           | `list[int]` | `[10M, 100M, 1B, 5B, 10B, 50B]` | `AUDIT_APPROVAL_THRESHOLDS` | L2-01, L1-04 |
| `duplicate_payment_window_days` | `int` | `30`   | `AUDIT_DUPLICATE_PAYMENT_WINDOW_DAYS` | L2-02     |
| `sod_process_threshold`         | `int` | `3`    | `AUDIT_SOD_PROCESS_THRESHOLD`         | L3-12 업무범위 검토 fallback |

> `sod_process_threshold`: user_persona 미존재 시 L3-12 work-scope fallback용.
> L1-06 direct SoD 점수에는 사용하지 않는다.

> `approval_thresholds`: 6단계 승인한도 (generation_principles §11).
> `is_near_threshold`/`exceeds_threshold` 피처는 금액에 가장 가까운 한도를 기준으로 판정.
> 기존 `approval_threshold`(단일값)은 하위호환 유지, `approval_thresholds` 우선 적용.

#### 테스트 결과

```
tests/test_detection/test_fraud_rules_feature.py — 12개 통과
  L4-01: 매출+고zscore flagged, 저zscore not, 비매출 not, 피처 미존재 skip
  L2-01: near_threshold flagged/not/미존재
  L1-04: exceeds flagged/not
  L3-02: 수기+초과 flagged, 수기만 not, 초과만 not

tests/test_detection/test_fraud_rules_groupby.py — 10개 통과
  L2-02: 윈도우 내 flagged(양방향 diff), 윈도우 초과 not, 다른 거래처 not,
       컬럼 미존재 skip, 3건 중복 전체 flagged, 정확히 30일 경계 flagged
  L2-03: exact match flagged, 날짜 다름 not, GL 다름 not, 컬럼 미존재 skip

tests/test_detection/test_fraud_rules_access.py — 12개 통과
  L1-05: 동일 승인자 flagged, fallback(수기 소스), created_by 미존재 skip, NaN 처리
  L1-06: toxic pair flagged, in-process conflict flagged, junior 초과 flagged,
       controller safe 통과, automated 제외, fallback, 컬럼 미존재 skip (8개)
  L1-07: 초과+비자동 flagged, 컬럼 미존재 skip
  L3-03: 관계사 다수 회사 flagged, 단일 회사 flagged, 컬럼 미존재 skip

tests/test_detection/test_fraud_layer.py — 8개 통과
  통합: DetectionResult 구조, scores max≤1.0, minimal_df graceful, 빈 df ValueError,
       rule_flags 수, L4-01 매출 이상치 details 검증, 컬럼명 B prefix, flagged_indices 정합
```

> E2E 테스트 결과: [e2e-detection-datasynth.md](../../tests/test_detection/test-results/e2e-detection-datasynth.md)

---

### ④ L3/L4: 이상 징후 (anomaly_layer.py) — ✅ 구현 완료

```
src/detection/
├── anomaly_layer.py              # AnomalyDetector 오케스트레이터 — L3-04~L3-08, L4-03~L3-09 (9개)
├── anomaly_rules_simple.py       # 피처 기반 룰: L3-04~L3-08, L4-03, L3-09 — bool 컬럼 마스크 연산
├── anomaly_rules_statistical.py  # L4-04 계정 쌍 + L4-02 Benford 공용 함수
└── benford_detector.py           # BenfordDetector 독립 트랙 — L4-02 (가중치 0.15)
```

> L4-02(Benford)은 전체 분포 검정으로 행별 룰과 성격이 달라 독립 트랙으로 분리.
> DETECTION_RULES.md §7: `anomaly_score = A×0.15 + B×0.45 + C×0.25 + Benford×0.15`

#### 이 모듈이 하는 일

L1/L2/L3/L4 탐지 체계에서 **보조 레이어**(가중치 0.25)이다.
L2가 "이 전표가 부정·횡령의 징후를 보이는가?"를 직접 판정한다면,
L3/L4는 **"이 전표가 비정상적인 패턴을 보이는가?"** 를 간접 지표로 탐지한다.

10개 룰(L3-04~L3-09)이 시점·금액·적요·분포·가계정 관점에서 이상 패턴을 감지하며,
L2와 동시에 걸리면 감사 증거가 더 강력해진다.

#### 왜 필요한가

```
법규 근거 → 룰 도출:

감사기준서 240호 §32(b)  "결산 수정 분개의 적정성"
  → L3-04 기말 대규모 — 기말에 집중되는 고액 전표는 결산 조정 조작 가능성
  → L1-08 기간 불일치 — 회계기간 귀속 오류는 의도적 기간 이동 의심

감사기준서 240호 A49(c)  "비정상적 시기에 이루어진 거래"
  → L3-05 주말 전기, L3-06 심야 전기 — 감시 부재 시점 악용
  → L3-07 전기일-문서일 장기 괴리 — 과도한 날짜 괴리는 기록 조작 은폐 후보
  → L3-08 적요 결손/파손 — 적요 누락·깨짐은 전표 추적 방해

감사기준서 520호 §5, 240 A45(e)  "예상치 못한 관계나 추세"
  → L4-02 Benford 위반 — 첫째자리 분포의 통계적 비적합성
  → L4-03 이상 고액 — 3σ 초과 금액은 조작 가능성

감사기준서 240호 A49(a), ISA 315  "비정상적 계정 조합"
  → L4-04 비정상 계정조합 — 희소한 차변-대변 쌍은 비정상 거래 의심
```

L3/L4 단독으로는 부정 판정이 아니지만,
L1 위반 + L2 패턴 + L3/L4 징후가 동시에 발생하면
**감사 증거의 설득력이 기하급수적으로 강화**된다.

#### 파일 구조

100줄 제한을 맞추기 위해 **데이터 접근 패턴 기준**으로 3개 파일로 분할.

| 서브모듈                      | 분할 근거                                                    | 포함 룰                |
|:------------------------------|:------------------------------------------------------------|:-----------------------|
| `anomaly_rules_simple.py`     | 피처 엔진이 생성한 bool/float 컬럼을 직접 조합               | L3-04~L3-08, L4-03 (7개)     |
| `anomaly_rules_statistical.py`| 별도 통계 연산(Benford 분석, 계정 쌍 빈도) 필요              | L4-02, L4-04 (2개)         |

#### 각 파일의 역할

##### anomaly_layer.py — 오케스트레이터

AnomalyDetector 클래스가 BaseDetector를 상속하고 `detect(df) → DetectionResult`를 구현한다.
FraudLayer와 동일한 오케스트레이션 패턴을 따른다.

```
실행 흐름:
  1. validate_input(df, ["debit_amount", "credit_amount"])
  2. _build_registry() → [(rule_id, callable, kwargs), ...] 10개
  3. for rule in registry:
       try: result = func(df, **kwargs)
            if isinstance(result, tuple):   # L4-02: (Series, metadata)
                rule_results[id] = result[0]
                extra_metadata.update(result[1])
            else:
                rule_results[id] = result
       except: skipped_rules.append(rule_id) + warning
  4. _build_result() → scores(max severity/5), details(행×룰), RuleFlag 리스트
```

**scores 산출 규칙:**
한 행이 L1-08(severity=4)와 L3-05(severity=2)에 동시에 해당하면
`max(4/5, 2/5) = 0.8`. 합산이 아닌 **최대값**을 사용한다.

**settings에서 주입하는 파라미터:**
- `period_end_amount_quantile` → L3-04
- `backdated_threshold_days` → L3-07
- `zscore_threshold` → L4-03
- `benford_*` → L4-02 (settings 전체를 전달)
- `account_pair_rare_percentile` → L4-04

##### anomaly_rules_simple.py — 피처 기반 룰 (L3-04~L3-08, L4-03, L3-09)

피처 엔진이 미리 생성한 bool/float 컬럼을 AND/OR 조합하는 단순 마스크 연산.
모든 함수는 `(df, **params) → pd.Series[bool]` 시그니처.
피처 미존재 시 `pd.Series(False, index=df.index)` 반환.

```
c01_period_end_large    is_period_end & (max(debit, credit) > quantile(0.75))
c02_weekend_entry       is_weekend | is_holiday
c03_after_hours_entry   is_after_hours
c04_backdated_entry     abs(days_backdated) > threshold_days (기본 30일)
c05_fiscal_period_mismatch   fiscal_period_mismatch == True
c06_missing_or_corrupted_description   description_quality in (missing,corrupted,poor)
c08_amount_outlier      abs(amount_zscore) > zscore_threshold (기본 3.0)
c10_suspense_account    suspense 계정 + 미정리 상태 + aging threshold
```

##### anomaly_rules_statistical.py — 통계 기반 룰 (L4-02, L4-04)

L4-02과 L4-04는 단순 피처 조회가 아닌 **별도 통계 연산**이 필요하다.

```
c07_benford_violation   (L4-02)
  ① analyze_benford(first_digit, settings) 호출
  ② is_conforming=True → 전체 False
  ③ is_conforming=False → 개별 자릿수 편차 > MAD 임계값인 자릿수 선별
  ④ 해당 first_digit을 가진 행만 플래그
  ⑤ benford_result를 metadata로 반환 (score_aggregator의 독립 트랙 참조용)

c09_rare_account_pair   (L4-04)
  ① 차변 뷰(debit_amount > 0)와 대변 뷰(credit_amount > 0) 분리
  ② document_id 기준 inner merge → N:M 복합 분개의 모든 (차변, 대변) 쌍 생성
  ③ (gl_account_dr, gl_account_cr) 빈도 계산 → 하위 percentile 임계값
  ④ 희소 쌍에 속한 document_id의 모든 행 플래그
```

**L4-04 복합 분개(N:M) 대응:**
회계 전표는 차변 2개 × 대변 3개 같은 복합 분개가 존재한다.
`groupby+apply`(반복문)는 대규모 데이터에서 느리므로,
`merge` 기반 Cartesian Product로 벡터화 연산을 수행한다.
수백만 건에서도 O(n) 수준 성능.

#### 룰별 감사 근거

| 룰  | 감사 근거                                    | 탐지 대상                                  |
|:----|:---------------------------------------------|:-------------------------------------------|
| L3-04 | PCAOB AS 240 §32(b), FSS 결산 수정 조작     | 월말 근접 + 금액 > Q3 → 기말 대규모 전표    |
| L3-05 | 감사기준서 240호 A49(c), FSS 비정상 시점     | 토/일/공휴일 전기                           |
| L3-06 | 감사기준서 240호 A49(c), FSS 비정상 시점     | 22시~06시 심야 전기                         |
| L3-07 | 감사기준서 240호 A49(c), FSS 횡령 은폐       | abs(전기일-전표일) > 30일 소급              |
| L1-08 | PCAOB AS 240 §32(b), 기간 귀속 오류          | 회계기간 ≠ 전기월                           |
| L3-08 | 감사기준서 240호 A49(c), K-SOX §8①1호        | 적요 결손/파손                              |
| L4-02 | 감사기준서 520호 §5, 240 A45(e)              | 첫째자리 분포 Benford 비적합 자릿수 행      |
| L4-03 | PCAOB AS 240 §33(b), ISA 315                | abs(Z-score) > 3σ 통계적 이상 금액          |
| L4-04 | 감사기준서 240호 A49(a), ISA 315             | 차변-대변 계정 쌍 빈도 하위 1%              |
| L3-09 | 외감법 §8①2호, FSS 횡령 은폐 사례            | 가수금·가지급 등 가계정 장기 체류 전표       |

#### 피처 → 룰 매핑

| 룰  | 사용 피처                                  | 원본 컬럼 추가 사용              | 비고                              |
|:----|:-------------------------------------------|:---------------------------------|:----------------------------------|
| L3-04 | `is_period_end`                            | `debit_amount`, `credit_amount`  | Q3 계산은 detection 내부          |
| L3-05 | `is_weekend`, `is_holiday`                 | —                                | 피처 OR 조합                      |
| L3-06 | `is_after_hours`                           | —                                | 직접 사용                         |
| L3-07 | `days_backdated`                           | —                                | abs() > 30일 임계값               |
| L1-08 | `fiscal_period_mismatch`                   | —                                | 직접 사용                         |
| L3-08 | `description_quality`                      | —                                | missing/corrupted/poor            |
| L4-02 | `first_digit`                              | —                                | `validation/benford.py` 재사용    |
| L4-03 | `amount_zscore`                            | —                                | abs() > 3.0 임계값                |
| L4-04 | —                                          | `gl_account`, `document_id`, 금액 | merge 기반 계정 쌍 빈도 분석     |
| L3-09 | `is_suspense_account`                      | —                                | 직접 사용                         |

#### Scoring

```
per-rule: flagged ? (severity / 5) : 0.0
  L3-04 (severity 3) → 위반 시 0.6
  L3-05 (severity 2) → 위반 시 0.4
  L3-06 (severity 2) → 위반 시 0.4
  L3-07 (severity 3) → 위반 시 0.6
  L1-08 (severity 4) → 위반 시 0.8
  L3-08 (severity 1) → 위반 시 0.2
  L4-02 (severity 2) → 위반 시 0.4
  L4-03 (severity 3) → 위반 시 0.6
  L4-04 (severity 2) → 위반 시 0.4
  L3-09 (severity 3) → 위반 시 0.6
row_score = max(L3-04_score, ..., L3-09_score)
```

max 방식 사용 이유: 이상 징후는 "가장 심각한 징후"가 해당 행의 위험도를 결정한다.
Score Aggregator에서 L3/L4 가중치는 0.25.

#### 구현 시 주의사항

**L4-02 Benford 전체 플래그 vs 자릿수 선별:**
Benford는 데이터셋 전체에 대한 통계 검정이지 행별 판정이 아니다.
전체 행 플래그는 과탐이므로, 비적합 판정 시에도 **편차가 큰 자릿수의 행만** 선별한다.
`benford_result`는 metadata에 포함하여 score_aggregator의 독립 트랙(0.15)이 참조한다.

**L4-04 복합 분개(N:M) 계정 쌍 생성:**
차변 2개 × 대변 3개인 전표에서 6개 쌍이 Cartesian Product로 생성된다.
`groupby+apply`(반복문)는 느리므로, 차변/대변 뷰를 `merge(on=document_id)`로
inner join하여 벡터화 연산으로 처리한다.

**L3-08 피처 부분 미존재 대응:**
`description_quality`가 없으면 graceful skip한다. `has_risk_keyword`는 Phase 1 L3-08 플래그 조건이 아니다.
둘 다 미존재 시에만 `Series(False)` 반환.

**L3-07 양방향 소급 판정:**
`days_backdated` 양수(지연)/음수(선전기) 모두 이상이므로 `.abs() > threshold` 사용.
기본 임계값 30일 — `settings.backdated_threshold_days`로 조정 가능.

#### 설계 결정

| 이슈                              | 결정                                                         | 사유                                                           |
|:----------------------------------|:-------------------------------------------------------------|:---------------------------------------------------------------|
| L4-02: detection vs validation 중복 | `validation/benford.py`의 `analyze_benford()` 직접 호출       | 코드 중복 방지, BenfordResult 재사용                            |
| L4-02 플래그 방식                   | 비적합 시 편차 큰 자릿수 행만 선별                            | 전체 행 플래그는 과탐. 감사적으로 유의미한 표본 추출             |
| L4-02 최소 샘플 미달 시             | scores=0.0 + warning (skip 아닌 0점 처리)                    | score_aggregator에서 가중치 적용 시 0이 안전                    |
| L3-04 "금액 > Q3" 기준              | 전체 DataFrame의 `max(debit, credit)` Q3                     | MVP 단순화. Phase 2에서 계정그룹별 Q3로 확장                    |
| L4-04 계정 쌍 추출                  | merge 기반 Cartesian Product (벡터화)                        | N:M 복합 분개 대응. groupby+apply 대비 대규모 데이터 성능 우수  |
| L4-04 "하위 1%" percentile          | `pair_counts.quantile(percentile)` (최소 1)                  | 빈도 기반 판정 — 금액 기반 아님                                 |
| L3-07 소급 기준                     | `abs(days_backdated) > 30일` (양방향)                        | 양수(지연)/음수(선전기) 모두 이상. settings로 조정 가능          |
| L3-08 조건                          | quality in (missing,corrupted,poor)                          | 적요 결손/파손만 Phase 1에서 플래그                             |
| scores 산출 방식                  | `max(severity / 5 × flagged)` per row                        | severity 5단계를 0~1 범위로 정규화. 합산 시 1.0 초과 위험       |
| 룰별 독립 실행                    | 한 룰 실패(exception)해도 나머지 계속 실행                   | try/except per rule + warning 수집                              |
| 모듈 분할                         | simple(7개) + statistical(2개)                               | L3-04~L3-08,L4-03은 피처 조회, L4-02/L4-04만 별도 연산. 100줄 제한 준수   |

#### settings.py 추가 설정

| 설정                            | 타입    | 기본값 | 환경변수                                | 사용 룰 |
|:--------------------------------|:--------|:-------|:----------------------------------------|:--------|
| `backdated_threshold_days`      | `int`   | `30`   | `AUDIT_BACKDATED_THRESHOLD_DAYS`        | L3-07     |
| `account_pair_rare_percentile`  | `float` | `0.01` | `AUDIT_ACCOUNT_PAIR_RARE_PERCENTILE`    | L4-04     |
| `period_end_amount_quantile`    | `float` | `0.75` | `AUDIT_PERIOD_END_AMOUNT_QUANTILE`      | L3-04     |

#### 테스트 결과

```
tests/test_detection/test_anomaly_rules_simple.py — 22개 통과
  L3-04: 기말+고액 flagged, 기말+저액 not, 비기말 not, 피처 미존재 skip
  L3-05: 주말 flagged, 공휴일 flagged, 평일 not
  L3-06: 심야 flagged, 업무시간 not, 피처 미존재 skip
  L3-07: abs>30 flagged(양방향), abs≤30 not, 피처 미존재 skip
  L1-08: 불일치 flagged, 일치 not
  L3-08: missing/corrupted/poor flagged, normal not
  L4-03: abs(zscore)>3 flagged, ≤3 not, 피처 미존재 skip

tests/test_detection/test_anomaly_rules_statistical.py — 9개 통과
  L4-02: Benford 적합 all-false, 비적합 선별 플래그, 피처 미존재 skip, 튜플 반환 확인
  L4-04: 희소 쌍 flagged, 빈번 쌍 not, 복합 분개 N:M 정상 처리,
       컬럼 미존재 skip, 빈 차변 skip

tests/test_detection/test_anomaly_layer.py — 10개 통과
  통합: DetectionResult 구조, scores 범위 0~1, NaN 없음, C prefix 컬럼,
       rule_flags 8개(L4-02 제외), flagged_indices 정합, elapsed 기록,
       minimal_df graceful, 빈 df ValueError, L4-02 미포함 확인

tests/test_detection/test_benford_detector.py — 8개 통과
  BenfordDetector: track_name="benford", DetectionResult 반환, scores 0~1,
       적합 시 전체 0점, metadata에 benford_result 포함,
       rule_flags L4-02, first_digit 미존재 graceful, 빈 df ValueError
```

> E2E 테스트 결과: [e2e-detection-datasynth.md](../../tests/test_detection/test-results/e2e-detection-datasynth.md)

---

### ⑤ 종합 점수 산출 (score_aggregator.py) — ✅ 구현 완료

```
src/detection/
└── score_aggregator.py    # aggregate_scores() + classify_risk_level()
```

#### 이 모듈이 하는 일

L1/L2/L3/L4 탐지의 **최종 단계**로, 각 Layer(A/B/C)와 Benford가 산출한
DetectionResult를 하나의 **종합 anomaly_score**로 합산하여 위험 등급을 분류한다.

```
파이프라인 위치:
  L1/B/C  →  score_aggregator  →  DuckDB 적재 + 대시보드 표시

역할:
  ① 가중합 산출: L1~L4 rule scores × weight → 행별 anomaly_score
  ② 위험 등급 분류: High / Medium / Low / Normal
  ③ 자동 승격: L1 + B 복합 위반 → High 강제
  ④ 위반 룰 집계: 행별 "L1-01,L1-04,L4-02" 문자열 생성
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
    """L1 ≥ 1개 위반 AND L2 ≥ 2개 위반 → risk_level = High 강제.
    details > 0의 행별 sum으로 판정. L1/B 결과 없으면 no-op."""

def _collect_flagged_rules(
    results: list[DetectionResult],
    index: pd.Index,
) -> pd.Series:
    """모든 result.details를 가로 concat → boolean mask → dot product 문자열 합성.
    apply(axis=1) 대신 mask.dot(cols + ",") 벡터화로 100만 행 1초 미만."""
```

#### Scoring

```
anomaly_score = L1~L4 rule scores + Benford distribution signal

위험 등급:
  High:   anomaly_score > 0.7  또는  L1/L2 control 위반 + L3/L4 review signal 2개 이상 (자동 승격)
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
| Benford 별도 가중치 vs L4-02 포함 | Benford를 L4-02과 별도 가중치(0.15)로 분리                 | DETECTION_RULES.md §7 설계 — 통계적 배경 점수로 독립 취급      |
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

`src/feature/` 18개 피처가 detection 24개 룰에서 사용되는 관계 전체 정리.

| 카테고리 | 피처명                    | 사용 룰                | 사용 방식            |
|:---------|:--------------------------|:-----------------------|:---------------------|
| Time     | `is_weekend`              | L3-05                    | 직접 사용            |
| Time     | `is_after_hours`          | L3-06                    | 직접 사용            |
| Time     | `is_period_end`           | L3-04                    | + 금액 Q3 조합       |
| Time     | `days_backdated`          | L3-07                    | >0 판정              |
| Time     | `fiscal_period_mismatch`  | L1-08                    | 직접 사용            |
| Time     | `is_holiday`              | L3-05                    | is_weekend와 OR 조합 |
| Amount   | `is_near_threshold`       | L2-01                    | 직접 사용            |
| Amount   | `exceeds_threshold`       | L1-04, L3-02, L1-07          | 직접 또는 조합       |
| Amount   | `amount_zscore`           | L4-01, L4-03               | 임계값 비교          |
| Amount   | `amount_magnitude`        | —                      | MVP 미사용 (Phase 2) |
| Amount   | `is_round_number`         | —                      | MVP 미사용 (Phase 2) |
| Pattern  | `is_manual_je`            | L3-02                    | + exceeds_threshold  |
| Pattern  | `is_intercompany`         | L3-03                    | + company_code       |
| Pattern  | `is_revenue_account`      | L4-01                    | + amount_zscore      |
| Pattern  | `first_digit`             | L4-02                    | Benford 분석 입력    |
| Pattern  | `is_suspense_account`     | L3-09                    | 직접 사용            |
| Text     | `description_quality`     | L3-08                    | missing/corrupted/poor |
| Text     | `has_risk_keyword`        | NLP/semantic 후보        | Phase 1 L3-08 조건 아님 |

> `is_holiday`, `amount_magnitude`, `is_round_number`, `is_suspense_account`는 MVP에서 직접 사용하지 않지만,
> Phase 2 탐지기(SupervisedDetector 등)의 ML 입력 피처로 활용 예정.

---

## 24개 감사 룰 상세

### L1: 데이터 무결성 (3개)

| ID  | 룰명          | DataSynth 유형      | Sev | 근거                | 탐지 로직                             | 피처                         |
|:----|:-------------|:---------------------|:----|:--------------------|:--------------------------------------|:-----------------------------|
| L1-01 | 차대변 균형   | UnbalancedEntry      | 5   | 240§32, 복식부기    | sum(debit) ≠ sum(credit) per doc_id   | debit_amount, credit_amount  |
| L1-02 | 필수필드 누락 | MissingField         | 2   | 240-A45(d), SOX     | 9개 필수 컬럼 NULL 검사               | 전체 필수 컬럼               |
| L1-03 | 무효 계정     | InvalidAccount       | 3   | 240-A45(a), 315     | gl_account NOT IN chart_of_accounts   | gl_account                   |

### L2: 통제우회·자금유출 검토 신호 (11개)

| ID  | 룰명            | DataSynth 유형                  | Sev | 근거                   | 탐지 로직                                    | 피처                                 |
|:----|:---------------|:--------------------------------|:----|:-----------------------|:---------------------------------------------|:-------------------------------------|
| L4-01 | 매출 이상 변동  | RevenueManipulation             | 5   | 240보론2, FSS최다      | 매출 계정(4xxx) 금액 > 통계 임계값           | is_revenue_account, amount_zscore    |
| L2-01 | 승인한도 직하   | JustBelowThreshold              | 3   | 240-A45(e), SOX        | 6단계 한도 중 가장 가까운 한도×0.9 이상      | is_near_threshold                    |
| L1-04 | 승인한도 초과   | ExceededApprovalLimit           | 3   | SOX, 240§32            | 6단계 한도 중 가장 가까운 한도 초과           | exceeds_threshold                    |
| L2-02 | 중복 지급       | DuplicatePayment                | 3   | 240§32, FSS횡령        | 동일 벤더·금액·30일 내 2건+                  | auxiliary_account_number, 금액, 날짜  |
| L2-03 | 중복 전표       | DuplicateEntry                  | 3   | 240§32, FSS가공        | 동일 금액·계정·일자 매칭                     | gl_account, 금액, posting_date       |
| L1-05 | 자기 승인       | SelfApproval                    | 3   | SOX직무분리, FSS오스템  | created_by == approved_by (직접 비교)        | created_by, approved_by, source      |
| L1-06 | 직무분리 위반   | SegregationOfDutiesViolation    | 4   | SOX직무분리, FSS오스템  | direct SoD conflict only | created_by, business_process, user_persona, sod_violation, sod_conflict_type |
| L3-02 | 수기 전표       | ManualOverride                  | 4   | 240-A45(b), FSS가공    | source == 'manual' + 고액                    | is_manual_je, exceeds_threshold      |
| L1-07 | 승인 생략       | SkippedApproval                 | 4   | SOX, FSS오스템          | 한도 초과 + 승인 없음                        | exceeds_threshold, source            |
| L3-03 | 관계사 거래 검토 신호 | RelatedPartyTransactionReview | 4   | 550호, 관계사 거래 검토 | 관계사 계정 사용 모집단                       | is_intercompany, company_code, trading_partner |
| L2-04 | 비용 자산화     | ExpenseCapitalization           | 4   | 240§32, FSS분식회계     | 동일 doc 내 차변=자산(15xx)+대변=비용(6xxx)  | gl_account, document_id              |

### L3/L4: 이상 징후 (10개)

| ID  | 룰명           | DataSynth 유형        | Sev | 근거                  | 탐지 로직                           | 피처                                |
|:----|:--------------|:-----------------------|:----|:----------------------|:------------------------------------|:------------------------------------|
| L3-04 | 기말 대규모    | RushedPeriodEnd        | 3   | 240§32(a)(ii), A44    | 월말 5일 이내 + 금액 > Q3           | is_period_end, 금액                  |
| L3-05 | 주말 전기      | WeekendPosting         | 2   | 240-A45(c)            | weekday() >= 5                      | is_weekend                           |
| L3-06 | 심야 전기      | AfterHoursPosting      | 2   | 240-A45(c)            | 22시~06시                           | is_after_hours                       |
| L3-07 | 전기일-문서일 장기 괴리 | TimingAnomaly          | 3   | 240-A45(c)            | abs(posting_date - document_date) > N일 | days_backdated                    |
| L1-08 | 기간 불일치    | WrongPeriod            | 4   | 240§32                | fiscal_period ≠ month(posting_date) | fiscal_period_mismatch               |
| L3-08 | 적요 결손/파손 | MissingOrCorruptedDescription | 1   | 240-A45(c), SOX       | 적요 누락·깨짐                       | description_quality                 |
| L4-02 | Benford 위반   | BenfordViolation       | 2   | 520호, 240-A45(e)     | MAD > 0.012 or KS p < 0.05         | first_digit                          |
| L4-03 | 이상 고액      | UnusuallyHighAmount    | 3   | 240§33(b), 315        | Z-score > 3                         | amount_zscore                        |
| L4-04 | 비정상 계정조합 | UnusualAccountPair    | 2   | 240-A45(a), 315       | 차변-대변 쌍 빈도 하위 1%          | gl_account                           |
| L3-09 | 가수금 장기체류 | SuspenseAccountAging  | 3   | 외감법§8①2호, FSS횡령  | suspense 계정 + 미정리 상태 + aging threshold | is_suspense_account, amount_open, is_cleared |

---

## 구현 순서

1. - [x] `constants.py` — RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS 상수
2. - [x] `base.py` — BaseDetector(ABC), DetectionResult, RuleFlag, validate_input
3. - [x] `__init__.py` — public API export
4. - [ ] `integrity_layer.py` — L1-01~L1-03 (데이터 무결성)
5. - [ ] `fraud_layer.py` — L4-01~L2-04 (통제우회·자금유출 검토 신호)
6. - [ ] `anomaly_layer.py` — L3-04~L3-09 (이상 징후, L4-02=Benford)
7. - [ ] `score_aggregator.py` — L1/L2/L3/L4 가중합 + risk_level + 자동 승격

---

## 의존성

- **선행:**
  - `03-feature` (18개 파생변수 — `generate_all_features()`)
  - `04-validation` (`is_pipeline_ready=True` + `benford.py` 재사용)
- **외부 패키지:**
  - MVP: `pandas`, `numpy`, `scipy` (core 그룹에 포함)
- **내부 재사용:**
  - `src/validation/benford.py` → L4-02 `analyze_benford(first_digits, settings=)` 직접 호출
  - `config/settings.py` → 모든 임계값 참조 (approval_thresholds, zscore_threshold 등)
  - `config/audit_rules.yaml` → manual_source_codes, revenue_account_prefixes 등
  - `config/schema.yaml` → L1-02 필수 컬럼 목록 (`required: true`)
- **후행:**
  - `06-db` (결과를 DuckDB에 적재)
  - `07-dashboard` (Tab 1 Summary에서 risk_summary 렌더링, Tab 3 Explorer에서 드릴다운)

---

## Phase 구분

| 항목                                        | Phase          |
|:--------------------------------------------|:---------------|
| constants.py (룰 코드/가중치 상수)          | MVP (Phase 1b) |
| BaseDetector, DetectionResult, RuleFlag     | MVP (Phase 1b) |
| IntegrityLayer (L1-01~L1-03)                    | MVP (Phase 1b) |
| FraudLayer (L4-01~L2-04)                        | MVP (Phase 1b) |
| AnomalyLayer (L3-04~L3-09, L4-02=Benford)        | MVP (Phase 1b) |
| score_aggregator (L1/L2/L3/L4+Benford)          | MVP (Phase 1b) |
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

**현재 한계**: 24개 룰은 임계값 기반 → 복합 패턴(다중 피처 조합) 탐지 어려움.

**ML 보완 (historical)**: 당시 설계는 Phase 1 룰 결과를 pseudo-label, DataSynth `is_fraud`/`is_anomaly`를 ground truth로 두고
GridSearchCV 최적 모델·하이퍼파라미터를 자동 선택하는 방식이었다. 최신 기준에서는 PHASE1 rule output을 최종 fraud label로 쓰지 않고, structured case summary와 provenance/display 입력으로만 사용한다. DataSynth label은 `rule_truth`, review population, confirmed audit issue truth와 분리해 해석한다.
- 모델 후보: XGBoost, RandomForest, LightGBM
- 피처: 18개 feature + 24개 룰 결과 = 42차원 입력
- ML 모델 후보: LR(베이스라인), RF, XGBoost(메인), LightGBM. KNN 제거(스케일링), DNN 보류(Phase 3 stacking)
- 불균형 처리: 모델별 class_weight 자동 매핑 (scale_pos_weight/class_weight="balanced"/is_unbalance)
- 라벨: DataSynth `is_fraud` ground truth 1순위. 양성 <50건 시 자동 비지도 전환
- 전이 학습: DataSynth 학습 모델을 실무 데이터에 전이 적용 (보조 점수)

#### 2. VAEDetector — VAE + Isolation Forest 앙상블

**현재 한계**: 룰 기반은 "알려진" 패턴만 탐지. 미지 패턴 탐지 불가.

**실증 근거 (2026-03-28 E2E 전수조사, v7)**:
- L4-04 recall=10% (1,039건 라벨 중 105건 탐지). 통계적 하위 1% 기준의 L4-04 룰은 정상 작동하나,
  라벨 중 ~56%가 실제로는 흔한 GL 조합(빈도 상위). DataSynth가 "도메인상 비정상"이라 부여한 라벨을
  빈도 기반 통계 룰로는 구조적으로 포착 불가.
- VAE 잠재 공간에서 정상 GL 조합 패턴을 학습하면, 빈도와 무관하게
  "본 적 없는 조합"을 재구성 오차로 탐지 가능 → UnusualAccountPair 커버.

**ML 보완**: 정상 전표의 잠재 분포 학습 → reconstruction error로 미지 이상 탐지.
IF와 앙상블하여 false positive 감소.
- 아키텍처: Basic FC VAE (50→32→8→32→50) Bottleneck 구조
- Phase 3 교체: vae_wrapper.py 내부에서 BiLSTM+Attention으로 교체 실험 (외부 2D 인터페이스 유지)
- 학습 데이터: 검증 모드(is_fraud=False만) / 실전 모드(전체 투입, Contamination Tolerance)

#### 3. DuplicateDetector — 중복/분할 거래

**현재 한계**: L2-02/L2-03는 정확 매칭(exact match) 기반. 유사 중복/분할 거래 미탐.

**실증 근거 (2026-03-28 E2E 전수조사, v7)**:
- L2-03 recall=9% (134건 라벨 중 12건 탐지). 샘플 20건 중 18건(90%)이 동일 날짜+GL+금액의
  실제 중복 쌍이 존재하지 않음. DataSynth가 "중복" 라벨을 부여했으나 정확히 일치하는 쌍을
  생성하지 않은 것이 1차 원인이지만, 실무에서도 exact match만으로는 다음을 탐지 불가:
  - **유사 금액 중복**: 100만원 → 99.8만원 (금액 미세 변경)
  - **분할 거래**: 100만원 → 50만원+50만원 (승인한도 회피 목적 분할)
  - **시차 중복**: 동일 거래의 다른 날짜 입력

**보완**: Fuzzy matching(금액 허용 오차) + 분할 거래 탐지(동일 계정·일자 소액 다건 합산이
승인한도와 유사하면 분할 의심 플래그) + embedding similarity(적요 유사도).

#### 4. TimeseriesDetector — 시계열 밀도 분석

**현재 한계**: 시점별 이상(L3-04~L3-06)만 탐지. 거래 빈도 패턴 미분석.

**보완**: TransactionBurst(특정 기간 거래 급증), UnusualFrequency(비정상 거래 주기) 탐지.

#### 5. IntercompanyMatcher — 내부거래 매칭

**현재 한계**: L3-03은 2-hop 순환만 탐지. 복잡한 내부거래 네트워크 미분석.

**보완**: 관계사 간 거래를 매칭하여 UnmatchedIntercompany(미매칭 내부거래) 탐지.

#### 6~10. Relational 모듈 (E2E 미탐지 대응)

**현재 한계**: Phase 1의 26개 룰은 Relational 이상 탐지 전무.

**실증 근거 (2026-03-28 E2E 전수조사, v7)**:
- L4-04 recall=10% (1,039건 라벨 중 105건 탐지): 통계적 하위 1% 기준과 DataSynth 도메인 라벨 기준이 불일치.
  전수조사 결과 라벨 중 ~56%가 실제로는 흔한 GL 조합. 통계 룰로는 구조적으로 포착 불가.
  L4-04 룰 자체는 정상 작동(하위 1% 빈도 쌍 탐지). 도메인 기반 "비정상"은 Phase 2 ML(GNN/VAE)로 이관.
- L3-03 recall=7% (643건 중 48건 탐지): 643건 중 640건이 trading_partner 자체가 NULL.
  2-hop cycle 형성 0건. 3자 이상 cycle은 Phase 3 GraphDetector로 이관.
- L2-03 recall=9% (134건 중 12건 탐지): 샘플 20건 중 18건이 실제 중복 쌍 부재.
  exact match 한계 → Phase 2 DuplicateDetector(fuzzy + split + embedding)로 이관.

| 유형                   | 라벨 | Phase 1 탐지     | 룰 한계                                    | 보완 전략                               | Phase |
|:-----------------------|-----:|:-----------------|:-------------------------------------------|:----------------------------------------|:------|
| UnusualAccountPair     | 1039 | L4-04(105건/10%)   | 빈도 기반만 → 흔하지만 도메인상 이상한 조합 미탐 | VAE/GNN 잠재공간 학습                   | 2c    |
| NewCounterparty        | 1317 | --               | 신규 거래처 판별 룰 없음                    | 마스터 데이터 교차 검증 + ML            | 2c    |
| MissingRelationship    |  877 | --               | 관계 데이터 룰 없음                         | 필수 관계 데이터 매칭                   | 2c    |
| DormantAccountActivity |  834 | --               | 계정 활동 이력 룰 없음                      | 계정 사용 이력 분석                     | 2c    |
| UnmatchedIntercompany  |  711 | --               | IC 매칭 룰 없음                             | 양측 거래 대사 (IC 매칭 확장)           | 2c    |
| CircularTransaction    |  643 | L3-03(48건/7%)     | 2-hop만, 640건 trading_partner NULL         | 그래프 DFS/BFS N-hop 순환 경로          | 3     |
| TransferPricingAnomaly |  446 | --               | 가격 분석 룰 없음                           | 거래처별 가격 분포 분석                 | 2c    |
| CentralityAnomaly      |  421 | --               | 그래프 분석 룰 없음                         | 그래프 Betweenness centrality           | 3     |

### Phase 3 탐지기 (2종)

#### 1. NLPAnalyzer — 적요 NLP (kiwipiepy + Transformer)

**현재 한계**: L3-08은 적요 누락·깨짐만 포착한다. 은어/동의어/위험 키워드 맥락 판단은 NLP/semantic 보조 분석 영역이다.

**NLP 보완**: kiwipiepy 형태소 분석 → Transformer(Qwen3-8B) 임베딩 기반 의미 유사도 계산.
MissingDocumentation, LatePosting 등 추가 유형 탐지.

> NLP & Transformer 동기 및 상세 설계: [08-llm.md](08-llm.md) §NLP & Transformer 참조

#### 2. GraphDetector — 그래프 순환 탐지

**현재 한계**: L3-03은 2-hop만. N-hop 순환, 복잡한 자금 순환 경로 미탐.

**실증 근거 (2026-03-28 E2E 전수조사, v7)**:
L3-03 recall=7% (643건 라벨 중 48건만 탐지). 전수조사 결과 643건 중 640건이
trading_partner 컬럼 자체가 NULL이며, 실제 2-hop cycle 형성 0건.
DataSynth가 순환 구조를 데이터로 구현하지 못한 것이 1차 원인이지만,
실무에서도 A→B→C→A (3-hop 이상) 순환은 룰 기반으로 탐지 불가.
GraphDetector의 DFS/BFS 기반 N-hop 순환 탐지가 이 갭의 해결책.

**그래프 보완**: 거래 네트워크를 방향 그래프로 구성 → 순환 탐지 알고리즘(DFS) 적용.
CircularTransaction(N-hop cycle), CentralityAnomaly(Betweenness), TransferPricingAnomaly 탐지.

---

## 테스트 전략

### 모듈별 테스트 계획

| 테스트 파일                    | 대상 모듈              | 예상 케이스 수 | 주요 검증 항목                                     |
|:-------------------------------|:-----------------------|:---------------|:---------------------------------------------------|
| `test_constants.py`            | constants.py           | 16건 ✅        | RULE_CODES 24개, SEVERITY_MAP 범위, LAYER_WEIGHTS 합계, enum 값 |
| `test_base.py`                 | base.py                | 20건 ✅        | validate_input, RuleFlag, DetectionResult, BaseDetector ABC/헬퍼 |
| `test_integrity_layer.py`      | integrity_layer.py     | ~12건          | L1-01~L1-03 각 위반/정상, CoA 미존재 skip              |
| `test_fraud_layer.py`          | fraud_layer.py         | ~28건          | L4-01~L2-04 각 위반/정상, 권장 컬럼 미존재 skip        |
| `test_anomaly_layer.py`        | anomaly_layer.py       | ~24건          | L3-04~L3-09 각 위반/정상, L4-02 최소 샘플 미달           |
| `test_score_aggregator.py`     | score_aggregator.py    | ~10건          | 가중합 정확성, risk_level, 자동 승격                |
| **합계**                       |                        | **~82건**      |                                                    |

### 검증 기준

- **L1:** L1-01(차대불일치 전표), L1-02(NULL 필드 전표), L1-03(미등록 계정 전표) 각각 위반/정상 검증
- **L2:** L4-01~L2-04 각각에 대해 DataSynth anomaly 레이블 데이터로 적발률 검증
  - 권장 컬럼(created_by 등) 미존재 시 skip + warning 반환 확인
  - L2-04: ExpenseCapitalization(90건) fraud_type 레이블 대비 탐지율 측정
- **L3/L4:** L3-04~L3-09 각각 위반/미위반 데이터 검증
  - L3-09: SuspenseAccountAbuse(102건) fraud_type 레이블 대비 탐지율 측정
  - L4-02(Benford): 알려진 적합/부적합 데이터셋으로 MAD/KS 판정 검증
  - L4-02: 100건 미만 → scores=0.0 + warning 확인
- **score_aggregator:** 가중치 합산 정확성, risk_level 임계값 검증, L1 위반+B 2개+ → High 자동 승격 검증
- **BaseDetector 준수:** 모든 트랙이 DetectionResult 스키마 반환 확인
- **교차 검증:** DataSynth `is_fraud`/`fraud_type`/`is_anomaly`/`anomaly_type` 레이블과 룰 탐지 결과 비교 → precision/recall 측정
- **SoD Ground Truth:** `sod_violation`/`sod_conflict_type` 레이블 대비 L1-06 성능 측정
- **Hold-out Fraud Type**: 8개 유형 중 6개 훈련, 2개(suspense_account_abuse, expense_capitalization) 미지 유형 테스트 → VAE zero-day 탐지 증명
- **Feature Perturbation**: 정상 전표의 피처 간 상관관계를 변조 → VAE 재구성 오차 상승 확인
- **잠재 공간 시각화**: t-SNE/UMAP으로 정상 클러스터 밀집 + 이상치 분리 확인
- **ML 테스트 원칙**: 정확한 점수가 아닌 "배관의 튼튼함" 검증 (구조/범위/결측 체크). Mock으로 비즈니스 로직만 검증

---

## 구현 시 주의사항

- **BaseDetector 인터페이스:** `detect()` → `DetectionResult` 반환 엄수. 새 트랙 추가 시 score_aggregator만 가중치 수정
- **점수 정규화:** 각 트랙의 scores는 0.0~1.0 범위로 정규화할 것
- **L1 우선:** A 레이어가 실패(차대 불일치 등)하면 경고 플래그를 남기되, B/C 레이어는 계속 실행
- **L4-02 Benford 최소 샘플:** 데이터 100건 미만이면 scores=0.0 + warning 반환
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
| `_generate_warnings` 룰 코드 하드코딩 | `"L1-02 룰"` 문자열 직접 삽입                    | `detection/constants.py` 룰 코드 상수와 통합          | [eda-profiling.md §코드리뷰](../../tests/test_eda/test-results/eda-profiling.md) |
| model_registry 경로 순회 취약점       | `load()` 시 file_path 검증 없음 → 경로 조작 가능 | `resolve().relative_to()` 검증 삽입               | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| model_registry 상대 경로              | `Path("models")` 하드코딩 → CWD 의존          | `get_settings().project_root / "models"` 변경         | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| vae_wrapper check_is_fitted 누락      | fit 전 predict 호출 시 에러 메시지 불명확      | `check_is_fitted(self, ["model_", "threshold_"])` 추가 | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| label_strategy hybrid 폴백 미비       | 양성 0건 + scores 있을 때 pseudo 폴백 누락     | `positive_rate == 0 and scores` 분기 추가             | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |
| cv_selector VAE n_jobs 충돌           | VAE Pipeline이 n_jobs>1에서 VRAM 경합          | `_has_vae()` 감지 → n_jobs=1 강제                     | [preprocessing §코드리뷰](../../tests/test_preprocessing/test-results/preprocessing-test-summary.md) |

---

## 신규 탐지 룰 후보 (DETECTION_RULES.md §3.3 기반)

> 아래는 감사기준서 갭 분석에서 도출된 신규 룰 후보. 24개 기존 룰과 별도로 Phase 1b 확장 또는 Phase 2에서 구현 검토.
> 상세 분석: [DETECTION_RULES.md §3.3](../DETECTION_RULES.md) 참조.

### Phase 1 구현 후보 (현재 39컬럼으로 가능)

#### 역분개 패턴 탐지 — ✅ L2-05 구현 완료

- 근거: 감사기준서 240호 (기말 조정·재분개 중점 검사)
- 룰 ID: **L2-05**, 심각도 4
- 구현 위치: `src/detection/anomaly_rules_reversal.py` → `c11_reversal_entry()`
- 설정: `config/audit_rules.yaml` (`reversal_keywords` 18개, 기말 부스트 기간)
- 로직 (5개 서브 신호 가중 합산, 임계값 0.3):
  1. S1(0.35) 1:1 매칭: 동일 gl_account + 동일 금액 + 반대 방향(차↔대) ±1일
  2. S2(0.25) N:M 분할 역분개: gl_account × created_by 그룹, 7일 롤링 윈도우 순액 ≈ 0
  3. S3(±0.15) 정상/수정 구분: auto + 월초(D≤5) = 감점, manual = 가중
  4. S4(0.10) 적요 키워드: config/audit_rules.yaml `reversal_keywords` 18개
  5. S5(×1.5) 기말 부스트: 12/20~12/31 + 1/1~1/5 결산 전후 15일
- 상세 사양: [DETECTION_RULES.md §2.3 L2-05](../DETECTION_RULES.md) 참조

#### Top-side JE (경영진 조정 전표) — 조합 점수 ✅

- 근거: 감사기준서 240호 §32(a)(ii), PCAOB AS 2401
- 룰 ID: **L2-05**, 심각도 5 (최고)
- 구현 위치: `src/detection/score_aggregator.py` (후처리 복합 탐지)
- 로직 (게이트키퍼 + 가점 방식):
  - **게이트키퍼**: `is_manual_je == True` 필수. 자동 전표는 원천 차단 (과탐 방지)
  - **가점** (각 1점, 최대 5점):
    1. 기말 시점 (L3-04 > 0)
    2. 자기승인/승인 생략 (L1-05 > 0 OR L1-07 > 0)
    3. 비정상 계정 (L1-03 > 0 OR L4-04 > 0)
    4. 이상 고액 (L4-03 > 0)
    5. 적요 결손/파손 (L3-08 > 0)
  - 판정: 수기 전표에 대해 가점 합산 → `topside_score` 산출
  - 정규화: `topside_score = raw / 5.0` (0.0~1.0)
- 설정: `config/settings.py::AuditSettings.topside_threshold`
- 테스트: `tests/test_detection/test_score_aggregator.py::TestTopsideDetection` (9개)

#### 비정상 시간대 입력자 집중 — ✅ L4-05 구현 완료

- **룰 ID**: L4-05, severity 3
- **구현**: `src/detection/anomaly_rules_simple.py::c12_abnormal_hours_concentration`
- **피처**: `time_zone_category` (normal/overtime/midnight) — `src/feature/time_features.py`
- 근거: KLCA IT 체크리스트
- 5가지 하위 로직:
  1. 시간대 분류: midnight(22:00~06:00), normal(08:30~18:30), overtime(나머지). 초 단위 포함(`hour+min/60+sec/3600`)
  2. 사용자별 비정상 비율: groupby(created_by) → abnormal_ratio. `min_user_entries`(기본 10) 미만 사용자 제외
  3. 3σ 이상치 판정: 단순 비율(0~1)로 판정, ratio > mean + 3σ AND ratio ≥ 10%. 소수 인원 폴백: 절대 건수 ≥ 3
  4. 이상치 사용자의 **비정상 시간대 행만** 플래그 (정상 시간 전표 미포함)
  5. 급속 승인: |approval_date - posting_date| < 5분 + 비정상 시간대 (자동 승인 제외, source 컬럼 대체 판별)
- 결산 집중기간(12/20~1/15, settings.py 설정 가능)만 overtime→normal 보정
- 설계 원칙: 통계 판정은 단순 비율, 심야 가중은 별도 위험점수(2계층 분리)
- 테스트: `tests/test_detection/test_c12_abnormal_hours.py` (46 cases)

### DataSynth 컬럼 추가 시 구현 가능

#### 승인 프로세스·승인자 계층 (approval.rs 활성화)

- 근거: 감사기준서 315호/330호, 1100호
- 필요 컬럼: approved_by, approval_date (DataSynth v1.2.0 생성 완료), approval_level (DuckDB 파생 컬럼)
- 로직: 승인 누락률, 승인 지연(일수 기준), 레벨 건너뜀, 자기승인 정밀화
- DataSynth: approved_by/approval_date 39컬럼에 포함. approval_level은 loader.py CASE WHEN으로 생성

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
