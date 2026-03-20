# 04. 계층적 데이터 검증 (Validation) [Phase 1a — 의존: 02]

## 목적
피처 보강된 DataFrame을 3단계(L1 구조 → L2 회계 → L3 통계)로 검증하여 데이터 품질을 보장하고,
검증 결과를 전처리 리포트로 자동 생성한다.

## 관련 파일
```
src/validation/
├── schema_validator.py       # L1: Pandera 구조 검증
├── accounting_validator.py   # L2: 대차일치, 일자 연속성
├── statistical_validator.py  # L3: 월별 급변, 분포 통계 (Phase 2)
└── report_generator.py       # 전처리 리포트 자동 생성
```

## 핵심 클래스/함수

### `schema_validator.py` — L1: 구조 검증
```python
import pandera as pa

# Pandera 스키마 정의 (schema.yaml 기반으로 동적 생성 가능)
class GeneralLedgerSchema(pa.DataFrameModel):
    """표준 GL DataFrame의 구조 스키마.
    필수 컬럼 존재, 타입, 기본 제약조건을 검증."""

    document_id: pa.typing.Series[str] = pa.Field(nullable=False)
    posting_date: pa.typing.Series[pa.DateTime] = pa.Field(nullable=False)
    gl_account: pa.typing.Series[int] = pa.Field(nullable=False)
    debit_amount: pa.typing.Series[float] = pa.Field(ge=0, nullable=False)
    credit_amount: pa.typing.Series[float] = pa.Field(ge=0, nullable=False)
    line_text: pa.typing.Series[str] = pa.Field(nullable=True)

def validate_schema(df: DataFrame) -> ValidationReport:
    """L1 검증: Pandera로 구조·타입·제약조건 검증.

    반환:
    - is_valid: 통과 여부
    - errors: 컬럼별 위반 상세
    - stats: 각 컬럼의 null 비율, 유니크 수 등
    """
```

### `accounting_validator.py` — L2: 회계 검증
```python
@dataclass
class AccountingValidation:
    balance_check: bool          # 대차일치 여부
    balance_diff: float          # 차이 금액
    date_continuity: bool        # 일자 연속성
    missing_dates: list[str]     # 누락 영업일
    duplicate_entries: int       # 완전 중복 행 수

def validate_accounting(df: DataFrame) -> AccountingValidation:
    """L2 검증: 회계 규칙 준수 여부.

    1. 대차일치: sum(debit) == sum(credit) (전표 단위 + 전체)
    2. 일자 연속성: 영업일 기준 누락 일자 탐지
    3. 중복 행: 완전 동일한 행 탐지 (hash 기반)
    """

def check_balance(df: DataFrame) -> tuple[bool, float]:
    """document_id 단위 + 전체 대차일치 검증.
    반환: (일치 여부, 차이 금액)"""

def check_date_continuity(df: DataFrame) -> tuple[bool, list[str]]:
    """영업일 기준 일자 연속성 검증.
    반환: (연속 여부, 누락 일자 목록)"""
```

### `statistical_validator.py` — L3: 통계 검증 (Phase 2)
```python
@dataclass
class StatisticalValidation:
    monthly_volatility: dict[str, float]   # 월별 금액 변동률
    outlier_months: list[str]              # 급변 월 목록
    distribution_stats: dict               # 기초통계량

def validate_statistics(df: DataFrame) -> StatisticalValidation:
    """L3 검증: 통계적 이상 징후 탐지.

    1. 월별 총액 변동률 → 급변 월 탐지 (Z-score > 2)
    2. 계정별 기초통계 (평균, 중앙값, 표준편차)
    3. 분포 정규성 검정 (Shapiro-Wilk)
    """
```

### `report_generator.py` — 전처리 리포트
```python
@dataclass
class PreprocessReport:
    total_rows: int
    valid_rows: int
    schema_errors: list[dict]
    accounting_issues: list[dict]
    statistical_flags: list[dict]    # Phase 2
    feature_summary: dict            # 피처별 분포 요약
    data_quality_score: float        # 0~100 종합 품질 점수

def generate_report(
    df: DataFrame,
    schema_result: ValidationReport,
    accounting_result: AccountingValidation,
    statistical_result: StatisticalValidation | None = None
) -> PreprocessReport:
    """모든 검증 결과를 종합하여 전처리 리포트 생성.
    대시보드 Tab 1(Summary)에서 표시."""
```

## 데이터 흐름
```
[피처 보강된 DataFrame] (from feature/)
       ↓
L1: schema_validator.validate_schema(df)
       ↓ (치명적 오류 시 중단, 경고는 계속)
L2: accounting_validator.validate_accounting(df)
       ↓
L3: statistical_validator.validate_statistics(df)    ← Phase 2
       ↓
report_generator.generate_report(df, L1, L2, L3)
       ↓
[검증 완료 DataFrame + PreprocessReport] → detection/
```

## 구현 순서
1. `schema_validator.py` — Pandera 스키마 정의 + L1 검증
2. `accounting_validator.py` — 대차일치 + 일자 연속성 + 중복
3. `report_generator.py` — L1+L2 결과 종합 리포트
4. `statistical_validator.py` — L3 통계 검증 (Phase 2에서 구현)

## 의존성
- **선행:** `03-feature` (피처 보강된 DataFrame), `03a-preprocessing` (EDA 프로파일링 — 데이터 현황 파악 후 검증)
- **외부 패키지:** `pandera`, `pandas`, `numpy`, `scipy` (L3)
- **후행:** `05-detection` (검증 통과된 DataFrame으로 이상탐지)

## 테스트 전략
- **L1 테스트:**
  - 필수 컬럼 누락 → 에러 반환
  - 금액에 음수 → 에러 반환
  - posting_date에 문자열 → 에러 반환
- **L2 테스트:**
  - 차변 합계 ≠ 대변 합계 → balance_check=False
  - 중간 영업일 누락 → 누락 일자 리스트 반환
  - 완전 중복 행 포함 → duplicate_entries > 0
- **L3 테스트 (Phase 2):**
  - 12월 금액이 평균의 5배 → outlier_months에 포함
- **리포트 테스트:** 모든 필드 정상 생성 확인

## Phase 구분
| 항목                     | Phase          |
|--------------------------|----------------|
| L1 구조 검증 (Pandera)   | MVP (Phase 1a) |
| L2 회계 검증             | MVP (Phase 1a) |
| L3 통계 검증             | Phase 2        |
| 전처리 리포트 (L1+L2)    | MVP (Phase 1a) |
| 전처리 리포트 (L3 포함)  | Phase 2        |

## 구현 시 주의사항
- **Pandera 유연성:** 필수/선택 컬럼을 schema.yaml 기반으로 동적 생성하면 ERP별 유연성 확보
- **대차일치 허용오차:** 부동소수점 비교 → `abs(diff) < 0.01` 등 허용 범위 설정
- **영업일 판정:** `pandas.bdate_range` 사용 (한국 공휴일은 Phase 2에서 고려)
- **L1 실패 시 흐름:** 치명적(필수 컬럼 누락)이면 중단, 경고(null 비율 높음)면 계속 진행
- **리포트 포맷:** dict → JSON 직렬화 가능하게 설계 (대시보드 + export 양쪽에서 사용)
