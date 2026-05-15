# 룰 기반 탐지 투 트랙 분리: Variance (전기 대비 변동 탐지) 구현 계획

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

## 1. 배경 및 목적

Phase 1 룰 기반 탐지(24개 룰)는 **단일 기간 데이터만 분석**한다.
과거 데이터가 있는 기존회사에 대해 "전기 대비 급변"을 탐지하면, 감사인이 전기 대비 이상 변동을 조기 파악할 수 있다.

### 투 트랙 정의

| 트랙       | 대상                 | 탐지 방식                                     |
|------------|----------------------|-----------------------------------------------|
| 신규회사   | 과거 engagement 없음 | 기존 24개 룰 그대로 (변경 없음)               |
| 기존회사   | 과거 engagement 존재 | 기존 24개 룰 + **Variance (전기 대비 변동 탐지)** |

### 분기 판단 기준

1. `CompanyContext.is_anonymous == True` → 신규회사 트랙
2. `CompanyRepository.list_engagements(company_id)`에서 `fiscal_year == 현재 - 1`인 engagement 존재 → 기존회사 트랙
3. 전기 engagement DB 파일 존재 + `general_ledger` 테이블에 데이터 존재 → Variance 실행
4. 위 조건 불충족 시 → 신규회사 트랙으로 graceful fallback

---

## 2. 신규 룰 상세 설계

### D01: 계정과목별 집계 급변

| 항목         | 내용                                                                    |
|--------------|-------------------------------------------------------------------------|
| Rule ID      | D01                                                                     |
| 룰 이름      | 계정과목 집계 급변                                                      |
| Layer        | D (전기 대비 변동)                                                      |
| Severity     | 4                                                                       |
| 감사기준서   | ISA 520 §5 (분석적 절차), PCAOB AS 2305                                 |
| 입력         | 당기 DataFrame + PriorSummary.account_aggregates                        |
| 출력         | `pd.Series[bool]` — 급변 계정에 속하는 행이면 True                      |

**판정 로직**:

```
1. 당기 gl_account별 집계 산출:
   - total_amount = SUM(debit_amount + credit_amount)
   - count = COUNT(*)
   - avg_amount = AVG(debit_amount + credit_amount)

2. 전기 동일 계정의 집계와 변동률 계산:
   variance_ratio = |당기 - 전기| / max(전기, epsilon)
   (epsilon = 1.0, 전기 값이 0일 때 0-division 방지)

3. 3개 지표의 가중평균:
   weighted_variance = total_var × 0.5 + count_var × 0.3 + avg_var × 0.2

4. 플래그 조건:
   - weighted_variance > variance_threshold (기본 0.5 = 50%) → 해당 계정의 모든 행 플래그
   - 전기에 없던 계정이 당기에 신규 등장 → 자동 플래그 (변동률 = 1.0)
   - 전기에 있었으나 당기에 소멸 → 탐지 대상 아님 (당기 행이 없으므로)
```

**예시**:

```
전기: 접대비(8220) 합계 50,000,000원, 120건
당기: 접대비(8220) 합계 180,000,000원, 95건
→ total_var = |180M - 50M| / 50M = 2.6 (260%)
→ count_var = |95 - 120| / 120 = 0.208
→ avg_var = |1,894,737 - 416,667| / 416,667 = 3.55
→ weighted = 2.6×0.5 + 0.208×0.3 + 3.55×0.2 = 2.07 > 0.5 ✓ 플래그
```

### D02: 월별 분포 패턴 변화

| 항목         | 내용                                                                    |
|--------------|-------------------------------------------------------------------------|
| Rule ID      | D02                                                                     |
| 룰 이름      | 월별 분포 패턴 변화                                                     |
| Layer        | D (전기 대비 변동)                                                      |
| Severity     | 3                                                                       |
| 감사기준서   | ISA 520 §5 (분석적 절차)                                                |
| 입력         | 당기 DataFrame + PriorSummary.monthly_patterns                          |
| 출력         | `pd.Series[bool]` — 패턴 변화 계정에 속하는 행이면 True                 |

**판정 로직**:

```
1. 전기 각 계정의 월별 금액 비율 (PriorSummary에 사전 계산됨):
   prior_ratio[month] = month_amount / annual_total
   (12개 월에 대한 확률분포, 합계 = 1.0)

2. 당기 동일 계정의 월별 금액 비율 산출:
   current_ratio[month] = month_amount / annual_total

3. Jensen-Shannon Divergence (JSD) 산출:
   - scipy.spatial.distance.jensenshannon(prior_dist, current_dist)
   - JSD 범위: 0.0 (동일 분포) ~ 1.0 (완전 상이)
   - 데이터 없는 월은 0으로 채움 (12개월 고정 벡터)

4. 플래그 조건:
   - JSD > monthly_pattern_threshold (기본 0.3) → 해당 계정의 모든 행 플래그
   - 전기/당기 모두 3개월 이상 데이터 존재해야 비교 수행
   - 3개월 미만이면 비교 불가 → 플래그하지 않음
```

**예시**:

```
전기 매출(4110): [8%, 7%, 9%, 8%, 10%, 9%, 8%, 9%, 8%, 7%, 8%, 9%] (균등)
당기 매출(4110): [3%, 3%, 5%, 5%, 5%, 5%, 5%, 5%, 5%, 5%, 5%, 49%] (12월 집중)
→ JSD ≈ 0.52 > 0.3 ✓ 플래그 (기말 매출 집중 의심)
```

---

## 3. 아키텍처 설계

### 3.1 신규 파일 구조

```
src/detection/
├── (기존 파일 유지)
├── prior_data_loader.py     # 전기 데이터 로딩 + 집계 (신규, ~70줄)
├── variance_rules.py        # D01, D02 순수 함수 (신규, ~90줄)
└── variance_layer.py        # Variance 오케스트레이터 (신규, ~80줄)
```

### 3.2 PriorSummary 데이터 모델

**파일**: `src/detection/prior_data_loader.py`

```python
@dataclass(frozen=True)
class PriorSummary:
    """전기 집계 결과 — 변동 탐지 룰의 비교 기준.

    Why: 전기 원장 전체를 메모리에 올리지 않고,
         DuckDB GROUP BY 집계만 가져와서 비교 기준으로 사용.
    """
    # D01용: {gl_account: {"total_amount": float, "count": int, "avg_amount": float}}
    account_aggregates: dict[str, dict[str, float]]

    # D02용: {gl_account: {1: ratio, 2: ratio, ..., 12: ratio}}
    #   ratio = month_amount / annual_total (확률분포, 합=1.0)
    monthly_patterns: dict[str, dict[int, float]]

    # 메타데이터
    prior_total_rows: int
    prior_fiscal_year: int
```

### 3.3 전기 데이터 로딩 흐름

```
AuditPipeline._run_detection(df)
  │
  ├─ (기존) IntegrityDetector → FraudLayer → AnomalyDetector → BenfordDetector
  │
  └─ (신규) self._ctx.is_anonymous 확인
       │
       ├─ True → 스킵 (신규회사)
       │
       └─ False → find_prior_engagement(repo, company_id, fiscal_year)
                    │
                    ├─ None → 스킵 (전기 없음)
                    │
                    └─ EngagementProfile
                         → load_prior_summary(conn, prior_db_path)
                            │
                            ├─ None → 스킵 (DB 없음/빈 데이터)
                            │
                            └─ PriorSummary
                                 → VarianceDetector(settings, prior_summary).detect(df)
                                      → DetectionResult (track_name="layer_d")
```

### 3.4 DuckDB ATTACH 활용

**재사용**: `src/db/queries.py:187`의 `attached_engagement()` 컨텍스트 매니저

```python
def load_prior_summary(
    conn: duckdb.DuckDBPyConnection,
    prior_db_path: Path,
    prior_fiscal_year: int,
) -> PriorSummary | None:
    """전기 DB에서 계정별 집계 + 월별 분포를 로드.

    Why: DuckDB ATTACH READ_ONLY로 전기 DB에 접근하여
         GROUP BY 집계만 가져옴 (전체 원장을 메모리에 올리지 않음).
    """
    try:
        with attached_engagement(conn, prior_db_path, "prior") as alias:
            # D01용: 계정별 집계
            agg_sql = f"""
                SELECT gl_account,
                       SUM(debit_amount + credit_amount) AS total_amount,
                       COUNT(*)                          AS count,
                       AVG(debit_amount + credit_amount) AS avg_amount
                FROM {alias}.general_ledger
                GROUP BY gl_account
            """
            agg_df = conn.execute(agg_sql).fetchdf()

            # D02용: 계정×월별 금액
            monthly_sql = f"""
                SELECT gl_account,
                       fiscal_period                     AS month,
                       SUM(debit_amount + credit_amount) AS month_amount
                FROM {alias}.general_ledger
                GROUP BY gl_account, fiscal_period
            """
            monthly_df = conn.execute(monthly_sql).fetchdf()

            # 총 행수
            total_rows = conn.execute(
                f"SELECT COUNT(*) FROM {alias}.general_ledger"
            ).fetchone()[0]

        # PriorSummary로 변환
        # ... (dict 변환 로직)

        return PriorSummary(
            account_aggregates=account_agg_dict,
            monthly_patterns=monthly_pattern_dict,
            prior_total_rows=total_rows,
            prior_fiscal_year=prior_fiscal_year,
        )
    except Exception:
        logger.warning("전기 데이터 로드 실패 — Variance 스킵", exc_info=True)
        return None
```

### 3.5 VarianceDetector 오케스트레이터

**파일**: `src/detection/variance_layer.py`

AnomalyDetector (`src/detection/anomaly_layer.py`)와 동일한 패턴:

```python
class VarianceDetector(BaseDetector):
    """Variance: 전기 대비 변동 탐지. 기존회사 전용.

    Why: 과거 데이터가 있는 회사에서만 실행되어
         계정과목별 급변(D01)과 월별 패턴 변화(D02)를 탐지.
    """

    def __init__(
        self,
        settings: AuditSettings | None = None,
        prior_summary: PriorSummary | None = None,
    ) -> None:
        super().__init__(settings)
        self._prior = prior_summary

    @property
    def track_name(self) -> str:
        return "layer_d"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """D01, D02 순차 실행. prior_summary 없으면 빈 결과."""
        if self._prior is None:
            return self._empty_result(df, ["전기 데이터 없음 — Variance 스킵"], 0.0)

        # _build_registry() → 룰 순회 → _build_result()
        # (AnomalyDetector와 동일한 패턴)
```

### 3.6 전기 engagement 탐색 로직

```python
def find_prior_engagement(
    repo: CompanyRepository,
    company_id: str,
    current_fiscal_year: int,
) -> EngagementProfile | None:
    """직전 연도 engagement 탐색.

    Why: 동일 회사의 fiscal_year == current - 1인 engagement 중
         가장 신뢰도 높은 것(completed > in_progress > draft)을 반환.
    """
    engagements = repo.list_engagements(company_id)
    candidates = [e for e in engagements if e.fiscal_year == current_fiscal_year - 1]
    if not candidates:
        return None

    # completed → in_progress → draft 우선순위
    for status in [EngagementStatus.COMPLETED, EngagementStatus.IN_PROGRESS]:
        match = next((e for e in candidates if e.status == status), None)
        if match:
            return match
    return candidates[0]
```

---

## 4. 점수 체계 통합

### 4.1 가중치 재배분

기존회사 트랙에서 Variance가 추가되면 가중치를 재배분한다.
L2(부정)의 비중이 가장 높은 것은 동일하나, Variance에 0.18을 할당하여 전기 변동의 중요성을 반영.

| 레이어              | 신규회사 (현행) | 기존회사 (제안) |
|---------------------|:---------------:|:---------------:|
| A (무결성)          | 0.15            | 0.12            |
| B (부정)            | 0.45            | 0.38            |
| C (이상징후)        | 0.25            | 0.20            |
| Benford             | 0.15            | 0.12            |
| **D (전기 변동)**   | **-**           | **0.18**        |
| 합계                | 1.00            | 1.00            |

### 4.2 구현 위치

**파일**: `src/detection/constants.py`

```python
LAYER_WEIGHTS_WITH_PRIOR: dict[Layer, float] = {
    Layer.LAYER_A: 0.12,
    Layer.LAYER_B: 0.38,
    Layer.LAYER_C: 0.20,
    Layer.BENFORD: 0.12,
    Layer.LAYER_D: 0.18,
}
```

### 4.3 가중치 선택 로직

**파일**: `src/pipeline.py` (`_execute` 내 aggregate 호출부)

```python
# Variance 결과가 있으면 기존회사 가중치 사용
has_variance = any(r.track_name == "layer_d" for r in results)
weights = LAYER_WEIGHTS_WITH_PRIOR if has_variance else None  # None → 기본 LAYER_WEIGHTS
agg_df = aggregate_scores(df, results, weights=weights)
```

`score_aggregator.aggregate_scores()`는 이미 `weights` 파라미터를 지원하므로 (`src/detection/score_aggregator.py:33`) 내부 로직 변경 불필요.

---

## 5. 수정 대상 파일 목록

### 5.1 신규 생성 (3개)

| 파일                                  | 줄 수 | 내용                                       |
|---------------------------------------|:-----:|--------------------------------------------|
| `src/detection/prior_data_loader.py`  | ~70   | PriorSummary, find_prior_engagement, load_prior_summary |
| `src/detection/variance_rules.py`     | ~90   | d01_account_aggregate_variance, d02_monthly_pattern_variance |
| `src/detection/variance_layer.py`     | ~80   | VarianceDetector (BaseDetector 상속)       |

### 5.2 기존 파일 수정 (4개)

| 파일                              | 변경 내용                                                | 영향도 |
|-----------------------------------|----------------------------------------------------------|:------:|
| `src/detection/constants.py`      | Layer.LAYER_D 추가, RULE_CODES D01/D02, SEVERITY_MAP, LAYER_WEIGHTS_WITH_PRIOR | 낮음   |
| `config/settings.py`              | AuditSettings에 variance_threshold 등 3개 필드 추가      | 낮음   |
| `src/pipeline.py`                 | `_run_detection`에 Variance 분기, `_execute`에 가중치 선택 | 중간   |
| `src/detection/__init__.py`       | VarianceDetector export 추가                             | 낮음   |

### 5.3 문서 업데이트 (구현 완료 후)

| 문서                         | 변경 내용                                  |
|------------------------------|--------------------------------------------|
| `docs/DETECTION_RULES.md`    | Variance 섹션 추가 (D01, D02 룰 상세)       |
| `docs/TASKS.md`              | Variance 완료 상태 업데이트                  |

---

## 6. 재사용 기존 모듈

| 모듈                                        | 위치                           | 용도                            |
|----------------------------------------------|--------------------------------|---------------------------------|
| `BaseDetector` ABC                           | `src/detection/base.py`        | 탐지기 인터페이스 상속          |
| `DetectionResult`, `RuleFlag`                | `src/detection/base.py`        | 결과 모델                       |
| `validate_input()`                           | `src/detection/base.py:94`     | 필수 컬럼 검증                  |
| `attached_engagement()`                      | `src/db/queries.py:187`        | DuckDB ATTACH 컨텍스트 매니저   |
| `CompanyRepository.list_engagements()`       | `src/company/repository.py:193`| 전기 engagement 목록 조회       |
| `CompanyRepository.get_engagement()`         | `src/company/repository.py:180`| engagement 프로파일 로드        |
| `CompanyRepository.db_path()`                | `src/company/repository.py`    | engagement DB 경로              |
| `score_aggregator.aggregate_scores(weights=)`| `src/detection/score_aggregator.py:33`| 가중치 파라미터로 전환    |
| `AnomalyDetector` 패턴                      | `src/detection/anomaly_layer.py`| 오케스트레이터 구조 참조        |
| `scipy.spatial.distance.jensenshannon`       | scipy (기존 의존성)            | D02 분포 비교                   |

---

## 7. 구현 순서 (작업 배치 단위)

3개 배치로 분리. 각 배치는 Claude 1회 컨텍스트에서 완결 가능한 단위.
배치 간 의존성이 있으므로 순차 실행.

---

### Batch 1: 인프라 + 데이터 로더 (신규 모듈 기반 구축)

**목표**: Variance가 동작하기 위한 기반 — 상수, 설정, 전기 데이터 로딩

**산출물**: 3개 파일 수정 + 1개 신규 생성 + 단위 테스트

```
[수정] config/settings.py           ← variance 설정 3개 필드 추가
[수정] src/detection/constants.py   ← Layer.LAYER_D, D01/D02 메타, LAYER_WEIGHTS_WITH_PRIOR
[신규] src/detection/prior_data_loader.py ← PriorSummary, find_prior_engagement, load_prior_summary
[테스트] tests/test_detection/test_prior_data_loader.py
```

**검증 기준**:
- `find_prior_engagement()`: fiscal_year-1 매칭, status 우선순위, 미존재→None
- `load_prior_summary()`: 정상 로드, DB 미존재→None, ATTACH 실패→None
- `uv run pytest tests/test_detection/test_prior_data_loader.py -v` 통과

---

### Batch 2: 룰 함수 + 오케스트레이터 (탐지 로직 구현)

**목표**: D01/D02 룰 함수 + VarianceDetector 오케스트레이터

**산출물**: 2개 신규 생성 + 1개 수정 + 단위 테스트

**의존**: Batch 1 완료 (PriorSummary, constants)

```
[신규] src/detection/variance_rules.py  ← d01_account_aggregate_variance, d02_monthly_pattern_variance
[신규] src/detection/variance_layer.py  ← VarianceDetector(BaseDetector)
[수정] src/detection/__init__.py        ← VarianceDetector export 추가
[테스트] tests/test_detection/test_variance_rules.py
[테스트] tests/test_detection/test_variance_layer.py
```

**검증 기준**:
- D01: 변동률 50% 초과만 플래그, 신규 계정 자동 플래그, 정상 계정 미플래그
- D02: JSD > 0.3 플래그, 동일 분포 JSD ≈ 0, 3개월 미만 미비교
- VarianceDetector: prior=None→빈 결과, 정상→D01/D02 통합, track_name="layer_d"
- `uv run pytest tests/test_detection/test_variance_*.py -v` 통과

---

### Batch 3: 파이프라인 통합 + 문서 + 회귀 검증

**목표**: pipeline에 Variance 분기 삽입 + 가중치 전환 + 문서 + 전체 테스트

**산출물**: 1개 수정 + 문서 2개 업데이트 + 통합 테스트

**의존**: Batch 1, 2 완료

```
[수정] src/pipeline.py               ← _run_detection 분기, _execute 가중치 선택
[수정] docs/DETECTION_RULES.md       ← Variance 섹션 추가 (D01, D02)
[수정] docs/TASKS.md                 ← Variance 완료 상태 업데이트
[테스트] tests/test_detection/test_pipeline_variance.py  ← 통합 테스트
```

**검증 기준**:
- 신규회사(anonymous) → Variance 미실행, 기존 L1/L2/L3/L4만
- 기존회사(전기 존재) → 5레이어 실행, LAYER_WEIGHTS_WITH_PRIOR 적용
- 기존회사(전기 미존재) → L1/L2/L3/L4만, LAYER_WEIGHTS 적용 (graceful fallback)
- `uv run pytest tests/ -v` 전체 통과 (회귀 확인)

---

## 8. 위험 요소 및 대응

| 위험                              | 대응                                                                       |
|-----------------------------------|----------------------------------------------------------------------------|
| DuckDB ATTACH 파일 락 충돌        | `attached_engagement()`가 READ_ONLY + finally DETACH 보장                  |
| 전기 DB 스키마 불일치 (구버전)    | SQL 실패 시 `load_prior_summary()` → None 반환, Variance 스킵              |
| 전기 데이터 대규모 (100만 행+)    | GROUP BY 집계 SQL만 실행, 전체 원장을 메모리에 올리지 않음                 |
| Phase 2 ML 확장 시 가중치 충돌    | Variance는 독립 track_name 사용, 가중치 딕셔너리만 확장하면 됨              |
| scipy 의존성                      | core 그룹에 이미 포함 (scipy)                                              |
| fiscal_period 컬럼 부재           | D02에서 컬럼 없으면 해당 룰만 스킵 (D01은 정상 실행)                       |

---

## 9. 검증 계획

### 9.1 단위 테스트

**prior_data_loader**:
- 전기 engagement 탐색: fiscal_year-1 매칭, status 우선순위, 미존재 시 None
- DB 로드: 정상 로드, DB 파일 미존재, 빈 테이블, ATTACH 실패 → 모두 graceful

**variance_rules**:
- D01: 변동률 50% 초과만 플래그, 신규 계정 자동 플래그, 정상 계정 미플래그
- D02: JSD > 0.3 플래그, 동일 분포는 JSD ≈ 0, 3개월 미만 미비교

**variance_layer**:
- prior_summary=None → 빈 결과 (빈 scores, 빈 details)
- 정상 입력 → D01/D02 결과 통합, track_name="layer_d"

### 9.2 통합 테스트

- 신규회사(anonymous) → Variance 미실행, 기존 L1/L2/L3/L4만
- 기존회사(전기 존재) → 5레이어 실행, 가중치 LAYER_WEIGHTS_WITH_PRIOR 적용
- 기존회사(전기 미존재) → L1/L2/L3/L4만, 가중치 LAYER_WEIGHTS 적용

### 9.3 회귀 테스트

```bash
uv run pytest tests/ -v
```

기존 24개 룰 + score_aggregator + pipeline 테스트 전체 통과 확인.
