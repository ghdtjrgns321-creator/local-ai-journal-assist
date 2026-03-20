# 03. 감사 파생변수 엔진 (Feature Engineering)

## 목적
표준 DataFrame에 감사 관점의 파생변수 15개를 추가하여, 이상탐지 룰과 ML 모델의 입력 피처로 활용한다.
각 파생변수는 AUDIT_DOMAIN_FINAL.md §5의 22개 룰(A01~C09)에 대응.

> **선행 모듈**: ingest에서 타입 캐스팅·Null 처리 완료된 표준 DataFrame을 입력으로 받는다.
> 컬럼 타입(float, datetime 등)이 보장된 상태이므로 별도 타입 검증 없이 연산에 집중.

---

## 데이터 흐름

```
[표준 DataFrame] (from ingest — type_caster 완료)
       ↓
engine.generate_all_features(df, settings)
       ↓
  ├── time_features    → is_weekend, is_after_hours, is_period_end, days_backdated, fiscal_period_mismatch
  ├── amount_features  → is_near_threshold, exceeds_threshold, amount_zscore, amount_magnitude
  ├── pattern_features → is_manual_je, is_intercompany, is_revenue_account, first_digit
  └── text_features    → has_risk_keyword, is_description_missing
       ↓
[피처 보강된 DataFrame] → validation/ → detection/
```

---

## 구현 상태 & 모듈별 가이드

### engine.py — ⬜ 구현 예정

4개 서브모듈을 순서대로 호출하여 15개 파생변수를 일괄 생성하는 오케스트레이터.

```
src/feature/
├── engine.py              # 전체 피처 오케스트레이션
├── time_features.py       # 시간 관련 파생변수 (5개)
├── amount_features.py     # 금액 관련 파생변수 (4개)
├── pattern_features.py    # 패턴 관련 파생변수 (4개)
└── text_features.py       # 텍스트 관련 파생변수 (2개)
```

**호출 순서**: time → amount → pattern → text (의존 관계 없으므로 순서 교체 가능)

---

### time_features.py — ⬜ 구현 예정 (5개 변수)

시간/날짜 기반 파생변수. `posting_date`(datetime), `document_date`(datetime), `fiscal_period`(int)를 입력으로 사용.

| 변수명                   | 타입 | 대응 룰 | 감사 관점                                                  |
|:-------------------------|:-----|:--------|:----------------------------------------------------------|
| `is_weekend`             | bool | C02     | 주말 전기 — 정상 업무 외 처리, 부정 가능성                  |
| `is_after_hours`         | bool | C03     | 심야 전기(22~06시) — 승인 우회 가능성                       |
| `is_period_end`          | bool | C01     | 기말(월말/분기말/연말 5일 이내) — 실적 조정 가능성           |
| `days_backdated`         | int  | C04     | posting_date − document_date 일수 — 소급 전기, 통제 우회    |
| `fiscal_period_mismatch` | bool | C05     | fiscal_period ≠ month(posting_date) — 기간 귀속 오류       |

**설계 결정:**

| 이슈                                          | 결정                                              |
|:----------------------------------------------|:--------------------------------------------------|
| is_after_hours — 시간 정보 없는 날짜           | skip 또는 warning (시간 미포함 시 False 반환)      |
| is_period_end — 비표준 회계기간(4월~3월 등)    | settings.fiscal_year_start로 외부화               |
| days_backdated — document_date 누락            | skip + warning (NaN 반환)                         |

---

### amount_features.py — ⬜ 구현 예정 (4개 변수)

금액 기반 파생변수. `debit_amount`(float), `credit_amount`(float)를 입력으로 사용.

| 변수명              | 타입  | 대응 룰  | 감사 관점                                           |
|:--------------------|:------|:---------|:---------------------------------------------------|
| `is_near_threshold` | bool  | B02      | 승인한도 × 0.90 이상 ~ 한도 미만 — 승인 우회 의도   |
| `exceeds_threshold` | bool  | B03      | 승인한도 초과 — 승인 절차 확인 필요                  |
| `amount_zscore`     | float | C08      | 금액 Z-score > 3 — 통계적 이상치                    |
| `amount_magnitude`  | float | — (ML)   | 금액 자릿수(log10) — ML 피처용                      |

**설계 결정:**

| 이슈                                    | 결정                                                     |
|:----------------------------------------|:---------------------------------------------------------|
| threshold 값이 회사마다 다름             | settings.approval_threshold로 외부화 (기본값 5천만)       |
| amount_zscore 계산 단위                  | Phase 1: 전체 데이터 기준 / Phase 2: 계정별 분리 계산    |
| 0원 금액 처리                            | Z-score 계산에 포함 (이상치로 잡힐 수 있음)               |

---

### pattern_features.py — ⬜ 구현 예정 (4개 변수)

전표 속성 기반 패턴 매칭. `source`(str), `company_code`(str), `gl_account`(str), 금액 컬럼을 사용.

| 변수명               | 타입 | 대응 룰 | 감사 관점                                    |
|:---------------------|:-----|:--------|:--------------------------------------------|
| `is_manual_je`       | bool | B08     | source == 'manual' — 자동화 통제 우회        |
| `is_intercompany`    | bool | B10     | 관계사 거래 패턴 — 순환거래 위험              |
| `is_revenue_account` | bool | B01     | gl_account가 매출 계정(4xxx) — 매출 이상 탐지 |
| `first_digit`        | int  | C07     | 금액 첫째 자릿수(1~9) — Benford 분석 입력     |

---

### text_features.py — ⬜ 구현 예정 (2개 변수)

적요(description) 텍스트 분석. `line_text`(str), `header_text`(str)를 입력으로 사용.

| 변수명                  | 타입 | 대응 룰 | 감사 관점                                           |
|:------------------------|:-----|:--------|:---------------------------------------------------|
| `has_risk_keyword`      | str  | C06     | '상품권', '가계정' 등 위험 키워드 — 자금 유용 가능성 |
| `is_description_missing`| bool | C06     | 적요 빈 문자열/NaN — 거래 목적 불명확                |

**설계 결정:**

| 이슈                     | 결정                                                        |
|:-------------------------|:------------------------------------------------------------|
| 위험 키워드 관리          | risk_keywords.yaml에서 로드 — 하드코딩 금지, 사용자 커스터마이징 |
| 키워드 매칭 결과 타입     | risk_level(str) 반환 — high/medium/low 분류                  |

---

## 15개 파생변수 요약

| #  | 변수명                    | 타입  | 대응 룰 | 카테고리 |
|----|---------------------------|-------|---------|----------|
| 1  | `is_weekend`              | bool  | C02     | time     |
| 2  | `is_after_hours`          | bool  | C03     | time     |
| 3  | `is_period_end`           | bool  | C01     | time     |
| 4  | `days_backdated`          | int   | C04     | time     |
| 5  | `fiscal_period_mismatch`  | bool  | C05     | time     |
| 6  | `is_near_threshold`       | bool  | B02     | amount   |
| 7  | `exceeds_threshold`       | bool  | B03     | amount   |
| 8  | `amount_zscore`           | float | C08     | amount   |
| 9  | `amount_magnitude`        | float | — (ML)  | amount   |
| 10 | `is_manual_je`            | bool  | B08     | pattern  |
| 11 | `is_intercompany`         | bool  | B10     | pattern  |
| 12 | `is_revenue_account`      | bool  | B01     | pattern  |
| 13 | `first_digit`             | int   | C07     | pattern  |
| 14 | `has_risk_keyword`        | str   | C06     | text     |
| 15 | `is_description_missing`  | bool  | C06     | text     |

## 구현 순서
1. `time_features.py` — 가장 단순 (날짜 기반 계산)
2. `amount_features.py` — 금액 기반 계산
3. `pattern_features.py` — DataFrame 내 패턴 매칭 (관계사·매출계정 판별)
4. `text_features.py` — 문자열 매칭 (risk_keywords.yaml 참조)
5. `engine.py` — 4개 서브모듈 통합 오케스트레이션

## 의존성
- **선행:** `02-ingest` (타입 캐스팅·Null 처리 완료된 표준 DataFrame), `01-project-setup` (settings, risk_keywords.yaml)
- **전처리 전제:** ingest type_caster가 float/datetime/str 변환을 보장 → feature에서는 타입 검증 불필요
- **외부 패키지:** `pandas`, `numpy`
- **후행:** `03a-preprocessing` (EDA 프로파일링 — 피처 추가된 DataFrame 대상), `04-validation` (피처 보강된 DataFrame 검증), `05-detection` (피처를 입력으로 이상탐지)

## Phase 구분

| 항목                       | Phase               |
|----------------------------|---------------------|
| 15개 파생변수 전체         | MVP (Phase 1a)      |
| NLP 기반 텍스트 피처 확장  | Phase 3 (kiwipiepy) |

## 테스트 전략
- **각 피처 함수 단위 테스트:**
  - 토요일 날짜 → `is_weekend=True` 확인
  - 23시 전표 → `is_after_hours=True` 확인
  - 45,000,000원 → `is_near_threshold=True` 확인 (5천만 × 0.90 = 4,500만)
  - 55,000,000원 → `exceeds_threshold=True` 확인
  - posting_date - document_date = 30일 → `days_backdated=30` 확인
  - gl_account '4100' → `is_revenue_account=True` 확인
- **edge case:** NaN 적요, 0원 금액, 시간 정보 없는 날짜, document_date 누락
- **engine 통합 테스트:** 전체 15개 변수 생성 + 컬럼 존재 확인

## 구현 시 주의사항
- **days_backdated:** document_date가 없는 ERP 대비 → skip 또는 warning
- **is_period_end 판정:** 회계기간(fiscal year)이 1~12월이 아닌 경우 대비 → settings에서 설정 가능하게
- **is_near_threshold/exceeds_threshold:** threshold는 회사마다 다름 → settings.approval_threshold로 외부화
- **amount_zscore:** 전체 데이터 기준 Z-score → 계정별로 분리 계산 시 Phase 2에서 확장
- **risk_keywords:** YAML에서 로드하여 하드코딩 방지 → 사용자 커스터마이징 지원
- **컬럼 의존성:** is_after_hours는 posting_date에 시간 정보가 있어야 작동 → 시간 없으면 skip 또는 warning

---

## 부록: API 레퍼런스

<details>
<summary>클릭하여 상세 함수 시그니처 보기</summary>

### engine.py
```python
def generate_all_features(
    df: DataFrame,
    settings: AuditSettings
) -> DataFrame:
    """모든 파생변수를 순서대로 생성하여 DataFrame에 추가.

    1. time_features → is_weekend, is_after_hours, is_period_end, days_backdated, fiscal_period_mismatch
    2. amount_features → is_near_threshold, exceeds_threshold, amount_zscore, amount_magnitude
    3. pattern_features → is_manual_je, is_intercompany, is_revenue_account, first_digit
    4. text_features → has_risk_keyword, is_description_missing
    """
```

### time_features.py
```python
def add_is_weekend(df: DataFrame) -> DataFrame:
    """posting_date의 요일이 토/일이면 True. (C02 대응)
    감사 관점: 주말 전기는 정상 업무 외 처리로 부정 가능성."""

def add_is_after_hours(df: DataFrame, start: int = 22, end: int = 6) -> DataFrame:
    """posting_date의 시간이 22~06시이면 True. (C03 대응)
    감사 관점: 심야 전기는 승인 우회 가능성."""

def add_is_period_end(df: DataFrame, days: int = 5) -> DataFrame:
    """posting_date가 월말/분기말/연말 n일 이내이면 True. (C01 대응)
    감사 관점: 기말 집중 전표는 실적 조정 가능성."""

def add_days_backdated(df: DataFrame) -> DataFrame:
    """posting_date - document_date 일수 차이. (C04 대응)
    감사 관점: 큰 양수 = 소급 전기, 통제 우회."""

def add_fiscal_period_mismatch(df: DataFrame) -> DataFrame:
    """fiscal_period ≠ month(posting_date)이면 True. (C05 대응)
    감사 관점: 기간 귀속 오류."""
```

### amount_features.py
```python
def add_is_near_threshold(
    df: DataFrame,
    threshold: float = 50_000_000,
    ratio: float = 0.90
) -> DataFrame:
    """금액이 승인 한도의 ratio% 이상이고 한도 미만이면 True. (B02 대응)
    감사 관점: 한도 직하 금액은 승인 우회 의도 가능성."""

def add_exceeds_threshold(
    df: DataFrame,
    threshold: float = 50_000_000
) -> DataFrame:
    """금액이 승인 한도 초과이면 True. (B03 대응)
    감사 관점: 한도 초과 전표의 승인 절차 확인 필요."""

def add_amount_zscore(df: DataFrame) -> DataFrame:
    """금액의 Z-score. > 3이면 이상 고액 후보. (C08 대응)
    감사 관점: 통계적 이상치."""

def add_amount_magnitude(df: DataFrame) -> DataFrame:
    """금액의 자릿수(log10)를 피처로 추가. (ML용)"""
```

### pattern_features.py
```python
def add_is_manual_je(df: DataFrame) -> DataFrame:
    """source == 'manual'이면 True. (B08 대응)
    감사 관점: 수기 전표는 자동화 통제 우회."""

def add_is_intercompany(df: DataFrame) -> DataFrame:
    """company_code 쌍 또는 reference에 관계사 패턴이 있으면 True. (B10 대응)
    감사 관점: 관계사 거래는 순환거래 위험."""

def add_is_revenue_account(df: DataFrame) -> DataFrame:
    """gl_account가 매출 계정(4xxx)이면 True. (B01 대응)
    감사 관점: 매출 이상 변동 탐지의 기준."""

def add_first_digit(df: DataFrame) -> DataFrame:
    """금액의 첫째 자릿수(1~9) 추출. (C07 Benford 대응)
    감사 관점: Benford 분석 입력."""
```

### text_features.py
```python
def add_has_risk_keyword(
    df: DataFrame,
    keywords: dict[str, list[str]]  # risk_keywords.yaml
) -> DataFrame:
    """적요(description)에 위험 키워드가 포함되면 risk_level 반환. (C06 대응)
    감사 관점: '상품권', '가계정' 등은 자금 유용 가능성."""

def add_is_description_missing(df: DataFrame) -> DataFrame:
    """적요가 빈 문자열이거나 NaN이면 True.
    감사 관점: 적요 누락은 거래 목적 불명확."""
```

</details>
