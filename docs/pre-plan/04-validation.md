# 04. 계층적 데이터 검증 (Validation) [Phase 1a + 2 — 의존: 02, 03, 03a]

## 목적
피처 보강된 DataFrame을 3단계(L1 구조 → L2 회계 → L3 통계)로 검증하여 데이터 품질을 보장하고,
검증 결과를 종합 리포트로 자동 생성한다.

> **EDA(03a)와의 역할 구분:**
> - `eda/report.py`: 데이터 현황 요약 (분포, 결측률, 이상치 등 프로파일링 결과)
> - `validation/report_generator.py`: 검증 결과 종합 리포트 (L1 구조 통과/실패, L2 회계 규칙 위반 목록)
>
> EDA는 "데이터가 어떤 상태인가?"를 보여주고, Validation은 "데이터가 규칙을 충족하는가?"를 판정한다.

---

## 데이터 흐름

```
[표준 DataFrame] (from ingest — type_caster 완료)
       ↓
feature (03) → 18개 파생변수 추가
       ↓
EDA profiling (03a) → EDAProfile(JSON) — 데이터 현황 파악
       ↓
① schema_validator.validate_schema(df)       → L1: Pandera 구조·타입 검증
       ↓ (치명적 오류 시 중단, 경고는 계속)
② accounting_validator.validate_accounting(df) → L2: 대차일치·일자 연속성·중복
       ↓
③ report_generator.generate_report(L1, L2)    → ValidationReport(JSON)
       ↓
[검증 완료 DataFrame + ValidationReport] → detection/ (05)
       ↓
  ┌──────────────────────────────────────────────────┐
  │ Phase 2: L3 통계 검증                             │
  │ ④ statistical_validator.validate_statistics(df)   │
  │    → 월별 급변, 분포 정규성 검정                   │
  └──────────────────────────────────────────────────┘
```

**핵심 포인트 — L1 실패 시 분기:**
- 치명적(필수 컬럼 누락, 타입 불일치) → 파이프라인 중단 + 에러 리포트
- 경고(null 비율 높음, 값 범위 일탈) → 계속 진행 + warning 목록 누적

---

## 구현 상태 & 모듈별 가이드

```
src/validation/
├── __init__.py                # 퍼블릭 API 재익스포트
├── models.py                  # ValidationReport, SchemaResult, AccountingResult dataclass
├── schema_validator.py        # L1: Pandera 구조 검증
├── accounting_validator.py    # L2: 대차일치, 일자 연속성, 중복
├── report_generator.py        # L1+L2 종합 리포트
└── statistical_validator.py   # L3: 월별 급변, 분포 통계 (Phase 2)
```

---

### ① schema_validator.py — ✅ 구현 완료 (Phase 1a) → [테스트 결과](../../tests/test_validation/test-results/validation-all-results.md)

#### 이 모듈이 하는 일

Excel에서 읽어온 DataFrame이 후속 파이프라인(detection, DB, 대시보드)에서 안전하게 사용될 수 있는지
**구조적 무결성**을 사전에 보장한다.

```
문제:
  ingest의 type_caster가 타입 변환을 수행하지만,
  원본 데이터 자체가 필수 컬럼 누락·음수 금액·비정상 타입인 경우가 있다.
  → 이 상태로 detection에 진입하면 런타임 에러 또는 침묵하는 오탐이 발생한다.

해결:
  Pandera DataFrameModel로 10개 필수 + 29개 선택 컬럼(schema.yaml 39개)의 존재·타입·값 범위를 정의하고,
  lazy=True로 모든 위반을 일괄 수집한 뒤 치명적(structural) vs 경고(값 범위)로 분류한다.
  치명적 에러가 있으면 파이프라인을 중단하고, 경고만 있으면 누적 후 계속 진행한다.
```

구체적으로 3가지를 수행한다:

- **필수 컬럼 사전 체크**: schema.yaml 기반으로 필수/전체 컬럼 set을 캐싱하여,
  Pandera 검증 전에 누락 컬럼을 빠르게 식별
- **Pandera lazy 검증**: `schema.validate(df, lazy=True)`로 첫 에러에서 중단하지 않고
  모든 위반을 수집 → 사용자에게 한 번에 전체 문제 목록 제공
- **치명적/경고 분류**: `_classify_failures()`가 에러를 구조적 치명(필수 컬럼 누락, 타입 불일치)과
  값 범위 경고(null 비율, 음수 등)로 분리 → `is_valid` 판정에 반영

Pandera 스키마 기반 구조·타입·제약조건 검증. ingest의 type_caster가 보장한 타입을 재확인하고, 값 범위 제약을 추가 검증한다.

**구현할 것:**
- `GeneralLedgerSchema(pa.DataFrameModel)`: 표준 GL DataFrame 스키마 정의
- `validate_schema(df) -> SchemaResult`: L1 검증 실행 + 결과 반환
- 필수 컬럼 존재, dtype 일치, nullable 제약, 값 범위(ge=0 등) 검증

```python
import pandera as pa

class GeneralLedgerSchema(pa.DataFrameModel):
    """표준 GL DataFrame의 구조 스키마 (필수 10 + 선택 29 = 39컬럼)."""
    # --- 필수 10개 (schema.yaml required: true) ---
    document_id: pa.typing.Series[str]           = pa.Field(nullable=False)
    company_code: pa.typing.Series[str]          = pa.Field(nullable=False)
    fiscal_year: pa.typing.Series[int]           = pa.Field(nullable=False)
    fiscal_period: pa.typing.Series[int]         = pa.Field(ge=1, le=12, nullable=False)
    posting_date: pa.typing.Series[pa.DateTime]  = pa.Field(nullable=False)
    document_date: pa.typing.Series[pa.DateTime] = pa.Field(nullable=False)
    document_type: pa.typing.Series[str]         = pa.Field(nullable=False)
    gl_account: pa.typing.Series[str]            = pa.Field(nullable=False)
    debit_amount: pa.typing.Series[float]        = pa.Field(ge=0, nullable=False)
    credit_amount: pa.typing.Series[float]       = pa.Field(ge=0, nullable=False)
    # --- 선택 29개는 schema.yaml 참조 (nullable=True) ---

@dataclass
class SchemaResult:
    is_valid: bool                   # 치명적 오류 없음 여부
    errors: list[dict]               # 컬럼별 위반 상세 [{column, check, failure_count}]
    warnings: list[dict]             # 경고 목록 [{column, issue, detail}]
    column_stats: dict[str, dict]    # 컬럼별 null 비율, 유니크 수 등

def validate_schema(df: DataFrame) -> SchemaResult:
    """L1 검증: Pandera로 구조·타입·제약조건 검증.
    치명적 오류 → is_valid=False, 경고 → is_valid=True + warnings."""
```

**설계 결정:**

| 이슈                              | 결정                                                               |
|:----------------------------------|:------------------------------------------------------------------|
| 스키마 정적 vs 동적               | 정적 클래스 정의 (schema.yaml 동적 생성은 Phase 2 고려)            |
| 필수/선택 컬럼 구분               | schema.yaml 기준 — 필수 10개, 선택 29개는 nullable                     |
| 치명적/경고 분류 기준             | 필수 컬럼 누락·타입 불일치 → 치명적 / null 비율·값 범위 → 경고     |
| Pandera 에러 핸들링               | `schema.validate(df, lazy=True)` — 모든 에러 수집 후 일괄 반환     |
| 피처 컬럼(is_weekend 등) 검증     | 피처 컬럼은 L1 검증 대상 외 — ingest 원본 컬럼만 검증              |

---

### ② accounting_validator.py — ✅ 구현 완료 (Phase 1a) → [테스트 결과](../../tests/test_validation/test-results/validation-all-results.md)

#### 이 모듈이 하는 일

L1(구조) 검증을 통과한 DataFrame이 **복식부기 원칙**을 준수하는지 검증한다.
구조적으로 올바른 데이터라도 회계적으로 불균형이면 detection 결과가 왜곡된다.

```
문제:
  L1 통과 = "컬럼과 타입이 맞다"는 뜻이지, "회계적으로 올바르다"는 뜻이 아니다.
  차변 ≠ 대변인 전표, 영업일 누락, 완전 중복 행이 있으면
  detection의 대차집중도·기말집중 룰이 정상 데이터를 오탐하거나 진짜 이상을 놓친다.

해결:
  3가지 회계 규칙(대차일치, 일자 연속성, 중복)을 각각 검증하고,
  위반 건은 report_generator에 전달하여 감점 + 대시보드 경고로 표시한다.
```

3가지 검증을 수행한다:

- **대차일치 (`check_balance`)**: document_id별 + 전체 차변-대변 차이를 단일 diff Series로
  groupby 1회 처리. 허용오차(0.01) 초과 시 불일치 전표 ID 목록 반환.
  DataSynth v1.2.0 기준 44건 의도적 불일치 존재 (A01 탐지 테스트용)
- **일자 연속성 (`check_date_continuity`)**: `pandas.bdate_range`로 영업일 기준
  누락 날짜 식별 (한국 공휴일은 Phase 2에서 holidays.KR 연동 예정)
- **중복 행 탐지 (`check_duplicates`)**: schema.yaml 원본 컬럼만 추출하여 중복 판정
  (feature에서 추가한 파생변수는 제외 — 같은 원본 데이터의 중복만 탐지)

회계 규칙 준수 여부를 검증한다. L1 통과 후 실행.

**구현할 것:**
- `validate_accounting(df) -> AccountingResult`: L2 검증 실행
- `check_balance(df) -> tuple[bool, float, list[str]]`: 전표 단위 + 전체 대차일치
- `check_date_continuity(df) -> tuple[bool, list[str]]`: 영업일 기준 일자 연속성
- `check_duplicates(df) -> int`: 완전 중복 행 탐지 (hash 기반)

```python
@dataclass
class AccountingResult:
    balance_check: bool          # 대차일치 여부
    balance_diff: float          # 전체 차이 금액
    unbalanced_docs: list[str]   # 불일치 document_id 목록
    date_continuity: bool        # 일자 연속성
    missing_dates: list[str]     # 누락 영업일
    duplicate_entries: int       # 완전 중복 행 수

def validate_accounting(df: DataFrame) -> AccountingResult:
    """L2 검증: 대차일치 + 일자 연속성 + 중복 행 탐지."""

def check_balance(df: DataFrame, tolerance: float = 0.01) -> tuple[bool, float, list[str]]:
    """document_id 단위 + 전체 대차일치 검증.
    반환: (일치 여부, 전체 차이 금액, 불일치 document_id 목록)"""

def check_date_continuity(df: DataFrame) -> tuple[bool, list[str]]:
    """영업일 기준 일자 연속성 검증.
    반환: (연속 여부, 누락 일자 목록)"""
```

**설계 결정:**

| 이슈                              | 결정                                                              |
|:----------------------------------|:------------------------------------------------------------------|
| 대차일치 허용오차                 | `abs(diff) < 0.01` — 부동소수점 비교 안전장치. KRW 정수 데이터에서는 실질적으로 diff == 0 기대 |
| 대차일치 검증 단위                | document_id별 + 전체 — 전표 단위에서 불일치 시 해당 ID 리스트 반환 |
| 영업일 판정                       | `pandas.bdate_range` 사용 (한국 공휴일은 Phase 2에서 고려)         |
| 중복 행 판정                      | 전체 컬럼 hash → `duplicated()` — 피처 컬럼 제외 (원본 컬럼만)    |
| posting_date 범위 미지정 시       | df 내 min/max로 자동 산출 — 외부 기간 지정 옵션은 Phase 1c UI     |

---

### ③ report_generator.py — ✅ 구현 완료 (Phase 1a)

#### 이 모듈이 하는 일

L1(구조) + L2(회계) 검증 결과를 **단일 ValidationReport**로 통합하고,
**파이프라인 진입 게이트** 역할을 수행한다.

```
문제:
  schema_validator와 accounting_validator가 각각 별도 결과(SchemaResult, AccountingResult)를 반환한다.
  대시보드는 하나의 요약 리포트를 필요로 하고,
  detection 파이프라인은 "이 데이터를 처리해도 되는가?"라는 단일 판정이 필요하다.

해결:
  두 결과를 합산하여 0~100 validation_score를 산출하고,
  L1 치명적 에러가 0건이면 is_pipeline_ready=True로 detection 진입을 허용한다.
  모든 숫자를 Python native 타입으로 변환(_sanitize)하여 JSON 직렬화를 보장한다.
```

핵심 기능 3가지:

- **감점 기반 점수 산출**: L1 치명적(-50), 경고 비율(-20), L2 대차불일치(-15),
  일자 누락(-5), 중복(-10) — 비율 기반 차등 감점으로 데이터 품질을 수치화
- **유효 행/전표 수 산출**: 에러 건수를 차감하여 근사치 계산.
  `valid_documents` = 전체 전표 - L2 대차불일치 전표 수
- **JSON 안전 변환**: `_sanitize()` 재귀 함수로 numpy int64/float64 → Python int/float 변환.
  대시보드·DuckDB 적재·export 모두에서 안전하게 사용 가능

L1+L2 검증 결과를 종합하여 JSON-serializable 리포트를 생성한다.
대시보드 Tab 1(Summary)에서 표시 + export 양쪽에서 사용.

**테스트 결과:** [validation-all-results.md](../../tests/test_validation/test-results/validation-all-results.md) (90 tests passed)

**퍼블릭 API:**
- `generate_report(df, schema_result, accounting_result, *, source_file=None) -> ValidationReport`
- `report_to_dict(report) -> dict`

```python
@dataclass
class ValidationReport:
    total_rows: int
    total_documents: int                          # 전체 document_id 수
    valid_rows: int                               # L1 통과 시 total_rows, 실패 시 근사치
    valid_documents: int                          # L2 위반 없는 전표 수
    schema_errors: list[dict]                     # L1 위반 상세
    schema_warnings: list[dict]                   # L1 경고
    accounting_issues: list[dict]                 # L2 표준화 이슈 목록
    # [{check_type, severity, message, detail}]
    statistical_flags: list[dict]                 # Phase 2 (빈 리스트)
    validation_score: float                       # 0~100 규칙 준수 품질
    is_pipeline_ready: bool                       # L1 치명적 에러 0건 → True
    generated_at: str                             # ISO 8601 UTC 타임스탬프
    source_file: str | None = None
    date_range: tuple[str, str] | None = None     # posting_date min/max

def generate_report(
    df: DataFrame,
    schema_result: SchemaResult,
    accounting_result: AccountingResult,
    *,
    source_file: str | None = None,
) -> ValidationReport:
    """L1+L2 검증 결과를 종합하여 ValidationReport 생성."""
```

**설계 결정:**

| 이슈                              | 결정                                                                               |
|:----------------------------------|:-----------------------------------------------------------------------------------|
| EDA report.py와의 역할 구분       | EDA = 현황 요약 (프로파일링) / Validation = 규칙 판정 (통과/실패)                   |
| 필드명 변경                       | `data_quality_score` → `validation_score` (EDA `quality_score`와 혼동 방지)         |
| validation_score 산출             | 비율 기반 감점 + 클리핑(0~100). L1 치명적 50점, 경고 비율 20점, L2 대차 15점+일자 5점+중복 10점 |
| valid_rows 산출                   | L1 is_valid=True → total_rows, False → failure_count 합산 차감 (근사치)             |
| 전표 단위 필드 추가               | `total_documents` / `valid_documents` — L2 대차불일치 반영                          |
| is_pipeline_ready 판정            | `schema_result.is_valid` (L1 치명적 에러 0건 → True)                                |
| 타임스탬프                        | `datetime.now(timezone.utc).isoformat()` — Naive datetime 금지 (법적 증적 고려)     |
| date_range 방어                   | posting_date 미존재/0행/전체 NaT → None 반환                                        |
| accounting_issues 키 표준화       | `{check_type, severity, message, detail}` 4개 키 고정                               |
| JSON 직렬화                       | `_sanitize()` 재귀 변환 (numpy → native). Phase 1b에서 공용 추출 예정               |
| Phase 2 확장                      | `statistical_flags` 빈 리스트 → L3 추가 시 score 반영                               |

---

### ④ statistical_validator.py — ⬜ 구현 예정 (Phase 2)

#### 이 모듈이 하는 일

L1(구조) + L2(회계) 검증을 넘어, **통계적 관점에서 데이터의 이상 징후**를 사전 탐지한다.
detection Layer C의 기반 데이터를 제공하는 역할을 한다.

```
문제:
  L1+L2는 "규칙 위반 여부"만 판정한다.
  하지만 규칙을 충족하더라도 12월 금액이 평균의 5배이거나,
  Benford 법칙에서 벗어나는 분포는 부정의 징후일 수 있다.
  → 이런 통계적 패턴은 규칙 기반 검증으로는 잡을 수 없다.

해결:
  5개 서브모듈(benford, volatility, distribution, account_stats, temporal_patterns)을
  오케스트레이션하여 통계적 이상 징후를 수집하고,
  detection Layer C(C01 기말집중, C07 Benford 등)에 입력 데이터를 제공한다.
```

5가지 통계 분석을 조합한다:

- **Benford 분석**: 첫째 자릿수 분포가 Benford 법칙과 부합하는지 검정 → C07 detection 입력
- **월별 변동성**: Z-score > 2인 급변 월 식별 → C01 기말집중 detection 입력
- **분포 분석**: 정규성 검정(Shapiro-Wilk), 이상치 비율 산출
- **계정별 통계**: CV(변동계수), HHI(집중도 지수) 등 계정 단위 요약
- **시간 패턴**: 요일별·기말·전년 대비(YoY) 패턴 분석

통계적 이상 징후를 탐지한다. Phase 2에서 구현.

```python
@dataclass
class StatisticalResult:
    monthly_volatility: dict[str, float]   # 월별 금액 변동률
    outlier_months: list[str]              # 급변 월 목록
    distribution_stats: dict               # 기초통계량

def validate_statistics(df: DataFrame) -> StatisticalResult:
    """L3 검증: 월별 총액 변동률(Z-score > 2), 계정별 기초통계, 분포 정규성 검정(Shapiro-Wilk)."""
```

---

## 구현 순서
1. `models.py` — SchemaResult, AccountingResult, ValidationReport dataclass 정의
2. `schema_validator.py` — Pandera 스키마 정의 + L1 검증
3. `accounting_validator.py` — 대차일치 + 일자 연속성 + 중복
4. `report_generator.py` — L1+L2 결과 종합 리포트
5. `statistical_validator.py` — L3 통계 검증 (Phase 2)

## 의존성
- **선행:**
  - `02-ingest` (타입 캐스팅 완료된 표준 DataFrame)
  - `03-feature` (18개 파생변수 추가된 DataFrame)
  - `03a-preprocessing` (EDA 프로파일링 — 데이터 현황 파악 후 검증)
- **외부 패키지:**
  - Phase 1a: `pandera`, `pandas`, `numpy` (core 그룹에 포함)
  - Phase 2: `scipy` (Shapiro-Wilk 검정 — core 그룹에 포함)
- **후행:**
  - `05-detection` (검증 통과된 DataFrame + ValidationReport로 이상탐지)
  - `07-dashboard` (Tab 1 Summary에서 ValidationReport 렌더링)

## Phase 구분

| 항목                          | Phase          |
|:------------------------------|:---------------|
| L1 구조 검증 (Pandera)        | MVP (Phase 1a) |
| L2 회계 검증                  | MVP (Phase 1a) |
| 종합 리포트 (L1+L2)          | MVP (Phase 1a) |
| L3 통계 검증                  | Phase 2        |
| 종합 리포트 (L3 포함)        | Phase 2        |

## 테스트 전략
- **L1 테스트:**
  - 필수 컬럼 누락 → is_valid=False + errors에 상세
  - 금액에 음수 → errors 반환
  - posting_date에 문자열 → errors 반환
  - null 비율 높은 컬럼 → is_valid=True + warnings
- **L2 테스트:**
  - 차변 합계 ≠ 대변 합계 → balance_check=False + unbalanced_docs 목록
  - 중간 영업일 누락 → missing_dates 리스트 반환
  - 완전 중복 행 포함 → duplicate_entries > 0
  - 허용오차 내 차이 → balance_check=True
- **L3 테스트 (Phase 2):**
  - 12월 금액이 평균의 5배 → outlier_months에 포함
- **리포트 테스트:**
  - 모든 필드 정상 생성 확인
  - is_pipeline_ready 판정 로직 검증
  - data_quality_score 산출 검증
  - JSON 직렬화 왕복 검증

## 구현 시 주의사항
- **Pandera lazy=True:** `schema.validate(df, lazy=True)`로 모든 에러를 수집 후 일괄 반환. 첫 에러에서 중단하지 않음.
- **대차일치 허용오차:** 부동소수점 비교 → `abs(diff) < tolerance` (기본 0.01). settings에서 오버라이드 가능.
- **영업일 판정:** `pandas.bdate_range` 사용. 한국 공휴일은 Phase 2에서 holidays.KR 연동 시 고려.
- **L1 실패 시 흐름:** 치명적(필수 컬럼 누락) → 파이프라인 중단 / 경고(null 비율 높음) → 계속 진행.
- **피처 컬럼 제외:** L1 검증은 ingest 원본 컬럼만 대상. feature에서 추가한 18개 파생변수는 검증 범위 외.
- **리포트 포맷:** dict → JSON 직렬화 가능하게 설계 (numpy int64/float64 → Python 네이티브 변환 필수).

## 테스트 결과

**통합 리포트:** [validation-all-results.md](../../tests/test_validation/test-results/validation-all-results.md) (90 tests passed)

## 남은 과제 (교차 참조)

| 문제                         | 해결 시점 | 해결 위치                                                                        |
|:-----------------------------|:----------|:---------------------------------------------------------------------------------|
| L3 통계 검증 리포트 통합     | Phase 2   | [05-detection §교차참조](05-detection.md#선행-모듈에서-넘어온-미해결-이슈-교차-참조) |
| 한국 공휴일 지원             | Phase 2   | [05-detection §교차참조](05-detection.md#선행-모듈에서-넘어온-미해결-이슈-교차-참조) |
| 업종별 영업일 차이           | Phase 1c  | [07-dashboard §미해결](07-dashboard.md#미해결-이슈-phase-1c에서-해결--발견-위치-교차-참조) |
| `_sanitize` 공용 추출        | Phase 1b  | [05-detection §교차참조](05-detection.md#선행-모듈에서-넘어온-미해결-이슈-교차-참조) |

---

## L3 검증 확장 후보 (audit_domain_additional.md 기반)

### 통제 운영 효과성 검증 (approved_by, approval_date — schema.yaml 포함 확인됨)

| 검증 항목          | 산출 로직                                      | 임계값 기준          |
|-------------------|-----------------------------------------------|---------------------|
| 승인 누락률        | 한도 초과 전표 중 approved_by IS NULL 비율        | > 5% 시 통제 미작동   |
| 평균 승인 지연      | approval_date - posting_date 일수 평균            | > 2일 시 경고        |
| 레벨 우회율        | 금액 대비 required_approval_level 부족 비율 (DuckDB 파생) | > 3% 시 통제 미작동 |

### 재무제표-장부 대사 (Phase 2, TB 테이블 추가 시)

| 대사 유형    | GL 계정      | 비교 대상                | 허용 차이         |
|-------------|-------------|-------------------------|------------------|
| 매출채권     | AR GL 잔액   | AR Aging Report 합계     | 중요성 금액 이하   |
| 매입채무     | AP GL 잔액   | AP Aging Report 합계     | 중요성 금액 이하   |
| 고정자산     | FA GL 잔액   | 고정자산 보조원장 합계    | 중요성 금액 이하   |
