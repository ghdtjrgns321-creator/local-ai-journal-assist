# 03. 감사 파생변수 엔진 (Feature Engineering)

## 목적
표준 DataFrame에 감사 관점의 파생변수 18개를 추가하여, 이상탐지 룰과 ML 모델의 입력 피처로 활용한다.
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
  ├── time_features    → is_weekend, is_after_hours, is_period_end, days_backdated, fiscal_period_mismatch, is_holiday
  ├── amount_features  → is_near_threshold, exceeds_threshold, amount_zscore, amount_magnitude, is_round_number
  ├── pattern_features → is_manual_je, is_intercompany, is_revenue_account, first_digit, is_suspense_account
  └── text_features    → has_risk_keyword, description_quality
       ↓
[피처 보강된 DataFrame] → validation/ → detection/
```

---

## 구현 상태 & 모듈별 가이드

### engine.py — ⬜ 구현 예정

4개 서브모듈을 순서대로 호출하여 18개 파생변수를 일괄 생성하는 오케스트레이터.

```
src/feature/
├── engine.py              # 전체 피처 오케스트레이션
├── time_features.py       # 시간 관련 파생변수 (6개)
├── amount_features.py     # 금액 관련 파생변수 (5개)
├── pattern_features.py    # 패턴 관련 파생변수 (4개)
└── text_features.py       # 텍스트 관련 파생변수 (2개)
```

**호출 순서**: time → amount → pattern → text (의존 관계 없으므로 순서 교체 가능)

---

### time_features.py — ✅ 구현 완료 (6개 변수, 47 tests passed)

시간/날짜 기반 파생변수. `posting_date`(datetime), `document_date`(datetime), `fiscal_period`(int)를 입력으로 사용.

| 변수명                   | 타입    | 대응 룰 | 감사 관점                                                  |
|:-------------------------|:--------|:--------|:----------------------------------------------------------|
| `is_weekend`             | bool    | C02     | 주말 전기 — 정상 업무 외 처리, 부정 가능성                  |
| `is_after_hours`         | bool    | C03     | 심야 전기(22~06시) — 승인 우회 가능성                       |
| `is_period_end`          | bool    | C01     | 기말 양방향 탐지(월말 전 + 익월 초 margin일) — 실적 조정    |
| `days_backdated`         | Int64   | C04     | posting − document 일수 **부호 유지** — +지연/−선전기       |
| `fiscal_period_mismatch` | boolean | C05     | **modulo 연산** — 비표준 회계연도(4월 결산 등) 대응         |
| `is_holiday`             | bool    | C02     | **holidays.KR + custom** 하이브리드 — 법정+회사 지정 병합   |

**설계 결정:**

| 이슈                                          | 결정                                                          |
|:----------------------------------------------|:--------------------------------------------------------------|
| is_after_hours — 시간 정보 없는 날짜           | `_has_time_info()` 컬럼 단위 판정 → False + warning            |
| is_period_end — 양방향 탐지                    | 월말 전 margin일 + 익월 초 margin일, `period_end_margin_days` 외부화 |
| is_holiday — 공휴일 목록 관리                  | `holidays.KR` (법정공휴일 자동) + `custom_holidays` (회사 지정) 하이브리드 |
| days_backdated — 부호 의미                     | **부호 유지** — 양수=지연전기, 음수=선전기. abs() 미적용       |
| days_backdated — document_date 누락            | skip + warning (NaN 반환), dtype=Int64(nullable)               |
| fiscal_period_mismatch — 비표준 회계연도       | `(month - fiscal_year_start) % 12 + 1` modulo 연산            |
| fiscal_period_mismatch — NaN 함정              | 결측치 마스크 → pd.NA 덮어씌움 (오탐 방지), dtype=boolean      |

**테스트**: [test_time_features.py](../../tests/test_feature/test_time_features.py) — 47 케이스

---

### amount_features.py — ✅ 구현 완료 (5개 변수, 27 tests passed)

금액 기반 파생변수. `debit_amount`(float), `credit_amount`(float)를 입력으로 사용.
`base_amount = max(debit, credit).fillna(0)` 중간 Series로 산출 후 각 피처에 전달 (컬럼 미추가).

| 변수명              | 타입  | 대응 룰  | 감사 관점                                           |
|:--------------------|:------|:---------|:---------------------------------------------------|
| `is_near_threshold` | bool  | B02      | 승인한도 × 0.90 이상 ~ 한도 미만 — 승인 우회 의도   |
| `exceeds_threshold` | bool  | B03      | 승인한도 초과 — 승인 절차 확인 필요                  |
| `amount_zscore`     | float | C08      | 금액 Z-score > 3 — 통계적 이상치                    |
| `amount_magnitude`  | float | — (ML)   | 금액 자릿수(log10) — ML 피처용                      |
| `is_round_number`   | bool  | B04      | 백만/천만 단위 round 금액 — 가공전표/횡령 탐지       |

**설계 결정:**

| 이슈                                    | 결정                                                                       |
|:----------------------------------------|:---------------------------------------------------------------------------|
| base_amount 산출                         | `max(debit, credit).fillna(0)` — 복식부기 한 라인은 차/대 중 하나만 양수    |
| threshold 값이 회사마다 다름             | settings.approval_threshold로 외부화 (기본값 5천만)                          |
| near/exceeds 경계 gap                   | `ratio*threshold ≤ x < threshold` / `x ≥ threshold` — 겹침·gap 없음 보장   |
| amount_zscore 계산 단위                  | gl_account별 groupby — n≥30 그룹별, n<30 전체 fallback, n<10 전체 NaN       |
| Z-score std==0                           | 0.0 반환 (ZeroDivisionError 방지)                                          |
| Z-score 소그룹 fallback 왜곡             | 큰 그룹 분포에 의해 왜곡 가능 → Phase 2 CoA 상위그룹 fallback 개선 예정     |
| 0원 금액 처리                            | Z-score에 포함, is_round_number에서 제외(False)                             |
| is_round_number 판정 기준                | `amount % round_unit == 0` — settings.round_unit 외부화 (기본 100만)        |
| float % 연산 안전성                      | ingest에서 정수값 보장 → 안전. 외화 소수점은 Phase 2 round() 전처리 예정    |
| gl_account 컬럼 누락                     | zscore NaN + warning 로깅 (에러 미발생)                                     |

**테스트**: [test_amount_features.py](../../tests/test_feature/test_amount_features.py) — 27 케이스

---

### pattern_features.py — ✅ 구현 완료 (5개 변수, 41 tests passed)

전표 속성 기반 패턴 매칭. `source`(str), `company_code`(str), `gl_account`(Int64), 금액·텍스트 컬럼 사용.
감사 업무 룰(키워드/코드)은 `config/audit_rules.yaml`에서 로드 — 함수 인자로 주입 (테스트 용이).

| 변수명                 | 타입  | 대응 룰  | 감사 관점                                         |
|:-----------------------|:------|:---------|:--------------------------------------------------|
| `is_manual_je`         | bool  | B08      | source 수기전표 코드 매칭 — 자동화 통제 우회       |
| `is_intercompany`      | bool  | B10      | 관계사 거래 패턴 — 순환거래 위험                   |
| `is_revenue_account`   | bool  | B01      | gl_account 매출계정 prefix 매칭                    |
| `first_digit`          | Int64 | C07      | 금액 첫 유효숫자(1~9) — Benford 분석 입력          |
| `is_suspense_account`  | bool  | B11/C06  | 가계정·미결산 키워드 매칭 — 장기미정리 부정 은폐    |

**설계 결정:**

| 이슈                                          | 결정                                                                       |
|:----------------------------------------------|:---------------------------------------------------------------------------|
| 업무 룰 하드코딩 문제                          | `config/audit_rules.yaml`로 완전 외부화. settings.py는 로더만 제공          |
| YAML vs settings 관심사 분리                   | settings = 시스템 설정(env), audit_rules = 도메인 업무 룰(YAML). 별도 로더  |
| first_digit — 음수/소수/과학표기법             | `str.extract(r"([1-9])")` — 모든 edge case 한 줄로 안전 처리               |
| first_digit — 0원 금액                         | NaN 반환 (Benford 분석 대상 외)                                            |
| gl_account가 Int64                             | `.astype(str)` 변환 후 startswith. `<NA>` → 매칭 안 됨 (정상)              |
| is_suspense_account 매칭 대상                  | `_SUSPENSE_TEXT_COLS` 상수. MVP: line_text + header_text                    |
| 정규식 키워드 안전성                           | `re.compile` 실패 시 `re.escape()` 폴백 + warning                          |
| 함수 인자 vs settings 직접 참조                | 함수 인자로 받기 (테스트 용이, engine.py에서 audit_rules 주입)              |

**테스트**: [test_pattern_features.py](../../tests/test_feature/test_pattern_features.py) — 41 케이스

---

### text_features.py — ✅ 구현 완료 (2개 변수, 38 tests passed)

적요(description) 텍스트 분석. `line_text`(str), `header_text`(str)를 입력으로 사용.

| 변수명                  | 타입 | 대응 룰 | 감사 관점                                           |
|:------------------------|:-----|:--------|:---------------------------------------------------|
| `has_risk_keyword`       | str  | C06     | '상품권', '가계정' 등 위험 키워드 — 자금 유용 가능성 |
| `description_quality`   | str  | C06     | 적요 품질 등급: missing(NaN/빈값) / poor(1~2글자) / normal(3글자+) |

**설계 결정:**

| 이슈                              | 결정                                                                        |
|:----------------------------------|:----------------------------------------------------------------------------|
| 헤더/라인 결합 (함정①)             | `_combine_text()` — 공백 concat, 둘 다 없으면 NaN. concat으로 normal 구제    |
| 텍스트 정제 (함정②)               | `_clean_for_keyword()` — 한글+영숫자 외 제거. description_quality에서는 미사용 |
| 노이즈 필터링 (MVP 타협)          | `_is_noise_pattern()` — 자음만/특수문자만/동일문자 반복 → poor에 병합         |
| 위험 키워드 관리                   | risk_keywords.yaml에서 로드 + risk_kw 직접 주입 가능 (테스트 용이)           |
| 키워드 매칭 우선순위               | high → medium → low 순서 (최고 등급 우선 반환)                               |
| description_quality 등급           | NaN→missing, noise→poor, len<min_length→poor, else→normal (3단계)            |
| Phase 2/3 stubs                   | `add_semantic_similarity`, `add_semantic_anomaly` — no-op + logger.info      |

---

## 18개 파생변수 요약

| #  | 변수명                    | 타입  | 대응 룰  | 카테고리 |
|----|---------------------------|-------|----------|----------|
| 1  | `is_weekend`              | bool  | C02      | time     |
| 2  | `is_after_hours`          | bool  | C03      | time     |
| 3  | `is_period_end`           | bool  | C01      | time     |
| 4  | `days_backdated`          | Int64 | C04      | time     |
| 5  | `fiscal_period_mismatch`  | bool  | C05      | time     |
| 6  | `is_holiday`              | bool  | C02      | time     |
| 7  | `is_near_threshold`       | bool  | B02      | amount   |
| 8  | `exceeds_threshold`       | bool  | B03      | amount   |
| 9  | `amount_zscore`           | float | C08      | amount   |
| 10 | `amount_magnitude`        | float | — (ML)   | amount   |
| 11 | `is_round_number`         | bool  | B04      | amount   |
| 12 | `is_manual_je`            | bool  | B08      | pattern  |
| 13 | `is_intercompany`         | bool  | B10      | pattern  |
| 14 | `is_revenue_account`      | bool  | B01      | pattern  |
| 15 | `first_digit`             | Int64 | C07      | pattern  |
| 16 | `is_suspense_account`     | bool  | B11/C06  | pattern  |
| 17 | `has_risk_keyword`        | str   | C06      | text     |
| 18 | `description_quality`     | str   | C06      | text     |

## 구현 순서
1. `time_features.py` — 가장 단순 (날짜 기반 계산)
2. `amount_features.py` — 금액 기반 계산
3. `pattern_features.py` — DataFrame 내 패턴 매칭 (관계사·매출계정 판별)
4. `text_features.py` — 문자열 매칭 (risk_keywords.yaml 참조)
5. `engine.py` — 4개 서브모듈 통합 오케스트레이션

## 의존성
- **선행:** `02-ingest` (타입 캐스팅·Null 처리 완료된 표준 DataFrame), `01-project-setup` (settings, risk_keywords.yaml)
- **전처리 전제:** ingest type_caster가 float/datetime/str 변환을 보장 → feature에서는 타입 검증 불필요
- **외부 패키지:** `pandas`, `numpy`, `holidays` (time_features — 법정공휴일 자동 판정)
- **후행:** `03a-preprocessing` (EDA 프로파일링 — 피처 추가된 DataFrame 대상), `04-validation` (피처 보강된 DataFrame 검증), `05-detection` (피처를 입력으로 이상탐지)

## Phase 구분

| 항목                       | Phase               |
|----------------------------|---------------------|
| 17개 파생변수 전체         | MVP (Phase 1a)      |
| NLP 기반 텍스트 피처 확장  | Phase 3 (kiwipiepy) |

## 테스트 전략
- **각 피처 함수 단위 테스트:**
  - 토요일 날짜 → `is_weekend=True` 확인
  - 23시 전표 → `is_after_hours=True` 확인
  - 45,000,000원 → `is_near_threshold=True` 확인 (5천만 × 0.90 = 4,500만)
  - 55,000,000원 → `exceeds_threshold=True` 확인
  - posting_date - document_date = 30일 → `days_backdated=30` 확인
  - gl_account '4100' → `is_revenue_account=True` 확인
  - 10,000,000원 → `is_round_number=True` 확인
  - 공휴일(설날 등) 전표 → `is_holiday=True` 확인
  - 적요 "." → `description_quality='poor'` 확인
  - 금액 -1500 → `first_digit=1` 확인 (abs 후 추출)
  - 금액 0.0053 → `first_digit=5` 확인 (non-zero digit)
- **edge case:** NaN 적요, 0원 금액, 시간 정보 없는 날짜, document_date 누락, 음수 금액, 소수점 금액
- **engine 통합 테스트:** 전체 17개 변수 생성 + 컬럼 존재 확인

## 구현 시 주의사항
- **days_backdated:** document_date가 없는 ERP 대비 → skip 또는 warning
- **is_period_end 판정:** 회계기간(fiscal year)이 1~12월이 아닌 경우 대비 → settings에서 설정 가능하게
- **is_near_threshold/exceeds_threshold:** threshold는 회사마다 다름 → settings.approval_threshold로 외부화
- **amount_zscore:** Phase 1부터 gl_account별 groupby Z-score 적용 (fallback: n≥30 계정별 → n<30 상위그룹 → n<10 NaN)
- **risk_keywords:** YAML에서 로드하여 하드코딩 방지 → 사용자 커스터마이징 지원
- **컬럼 의존성:** is_after_hours는 posting_date에 시간 정보가 있어야 작동 → 시간 없으면 skip 또는 warning
- **is_holiday:** settings.holidays YAML 날짜 목록 기반 판정 — 외부 패키지(holidays) 의존 없음
- **is_round_number:** settings.round_unit(기본 1,000,000) 기준 modulo 판정 — 가공전표/횡령 탐지
- **first_digit:** abs() → 0이 아닌 첫 번째 숫자 추출. 0원은 NaN 반환
- **description_quality:** is_description_missing + short_text 통합. missing/poor/normal 3단계 등급

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

    1. time_features → is_weekend, is_after_hours, is_period_end, days_backdated, fiscal_period_mismatch, is_holiday
    2. amount_features → is_near_threshold, exceeds_threshold, amount_zscore, amount_magnitude, is_round_number
    3. pattern_features → is_manual_je, is_intercompany, is_revenue_account, first_digit, is_suspense_account
    4. text_features → has_risk_keyword, description_quality
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

def add_is_holiday(df: DataFrame, holidays: list[str]) -> DataFrame:
    """posting_date가 settings.holidays 목록에 포함되면 True. (C02 대응)
    감사 관점: 공휴일 전기는 비영업일 부정 가능성."""
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

def add_amount_zscore(df: DataFrame, group_col: str = "gl_account") -> DataFrame:
    """gl_account별 groupby Z-score. > 3이면 이상 고액 후보. (C08 대응)
    fallback: n≥30 계정별 → n<30 상위그룹(자산/부채/수익/비용) → n<10 NaN.
    감사 관점: 통계적 이상치."""

def add_amount_magnitude(df: DataFrame) -> DataFrame:
    """금액의 자릿수(log10)를 피처로 추가. (ML용)"""

def add_is_round_number(df: DataFrame, unit: int = 1_000_000) -> DataFrame:
    """금액이 unit 단위로 딱 떨어지면 True. (B04 대응)
    감사 관점: round 금액은 가공전표/횡령 가능성."""
```

### pattern_features.py
```python
def add_is_manual_je(df: DataFrame) -> DataFrame:
    """source == 'manual'이면 True. (B08 대응)
    감사 관점: 수기 전표는 자동화 통제 우회."""

def add_is_intercompany(df: DataFrame) -> DataFrame:
    """company_code 쌍 또는 reference에 관계사 패턴이 있으면 True. (B10 대응)
    감사 관점: 관계사 거래는 순환거래 위험."""

def add_is_revenue_account(df: DataFrame, prefixes: list[str] = None) -> DataFrame:
    """gl_account가 settings.revenue_account_prefixes에 해당하면 True. (B01 대응)
    감사 관점: 매출 이상 변동 탐지의 기준. 기본값 ['4'], settings로 외부화."""

def add_first_digit(df: DataFrame) -> DataFrame:
    """금액의 첫째 non-zero 자릿수(1~9) 추출. (C07 Benford 대응)
    전처리: abs() → 0이 아닌 첫 번째 숫자. 0원 → NaN.
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

def add_description_quality(df: DataFrame, min_length: int = 3) -> DataFrame:
    """적요 품질 등급 반환: missing(NaN/빈값), poor(1~2글자), normal(3글자+).
    감사 관점: 적요 누락·성의없는 기재는 거래 실질 은폐 가능성."""
```

</details>
