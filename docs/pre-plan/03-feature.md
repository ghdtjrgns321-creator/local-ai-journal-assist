# 03. 감사 파생변수 엔진 (Feature Engineering)

## 목적
표준 DataFrame에 감사 관점의 파생변수 11개를 추가하여, 이상탐지 룰과 ML 모델의 입력 피처로 활용한다.
각 파생변수는 PCAOB AS 2401 / ISA 240의 부정위험지표에 대응.

## 관련 파일
```
src/feature/
├── engine.py              # 전체 피처 오케스트레이션
├── time_features.py       # 시간 관련 파생변수 (3개)
├── amount_features.py     # 금액 관련 파생변수 (3개)
├── pattern_features.py    # 패턴 관련 파생변수 (3개)
└── text_features.py       # 텍스트 관련 파생변수 (2개)
```

## 핵심 클래스/함수

### `engine.py` — 피처 오케스트레이터
```python
def generate_all_features(
    df: DataFrame,
    settings: AuditSettings
) -> DataFrame:
    """모든 파생변수를 순서대로 생성하여 DataFrame에 추가.

    1. time_features → is_weekend, is_midnight, is_period_end
    2. amount_features → is_round_number, is_near_threshold, amount_magnitude
    3. pattern_features → is_reversal, is_manual_je, is_intercompany
    4. text_features → has_risk_keyword, is_description_missing
    """
```

### `time_features.py` — 시간 파생변수 (3개)
```python
def add_is_weekend(df: DataFrame) -> DataFrame:
    """entry_date의 요일이 토/일이면 True. (R002 대응)
    감사 관점: 주말 전표는 정상 업무 외 처리로 부정 가능성."""

def add_is_midnight(df: DataFrame, start: int = 22, end: int = 6) -> DataFrame:
    """entry_date의 시간이 start~end 범위이면 True. (R003 대응)
    감사 관점: 심야 전표는 승인 우회 가능성."""

def add_is_period_end(df: DataFrame, days: int = 5) -> DataFrame:
    """entry_date가 월말/분기말/연말 n일 이내이면 True. (R004 대응)
    감사 관점: 기말 집중 전표는 실적 조정 가능성."""
```

### `amount_features.py` — 금액 파생변수 (3개)
```python
def add_is_round_number(df: DataFrame) -> DataFrame:
    """금액이 1,000,000 단위 정수이면 True.
    감사 관점: 지나치게 깔끔한 금액은 추정/조작 가능성."""

def add_is_near_threshold(
    df: DataFrame,
    threshold: float = 50_000_000,
    ratio: float = 0.98
) -> DataFrame:
    """금액이 승인 한도의 ratio% 이상이면 True. (R001 대응)
    감사 관점: 한도 직하 금액은 승인 우회 의도 가능성."""

def add_amount_magnitude(df: DataFrame) -> DataFrame:
    """금액의 자릿수(log10)를 피처로 추가. (ML용)
    예: 1,000 → 3, 50,000,000 → 7.7"""
```

### `pattern_features.py` — 패턴 파생변수 (3개)
```python
def add_is_reversal(df: DataFrame) -> DataFrame:
    """동일 계정·금액·일자로 차변/대변이 쌍으로 존재하면 True. (R005 대응)
    감사 관점: 역분개 쌍은 부정 은폐 수단."""

def add_is_manual_je(df: DataFrame) -> DataFrame:
    """source_type이 '수동'/'Manual'이면 True. (R006 대응)
    감사 관점: 수기 전표는 자동화 통제 우회."""

def add_is_intercompany(df: DataFrame) -> DataFrame:
    """계정과목/거래처에 '관계사', '특수관계' 등 키워드가 포함되면 True. (R008 대응)
    감사 관점: 관계사 거래는 이전가격 조작 위험."""
```

### `text_features.py` — 텍스트 파생변수 (2개)
```python
def add_has_risk_keyword(
    df: DataFrame,
    keywords: dict[str, list[str]]  # risk_keywords.yaml
) -> DataFrame:
    """적요(description)에 위험 키워드가 포함되면 risk_level 반환. (R007 대응)
    감사 관점: '상품권', '가계정' 등은 자금 유용 가능성."""

def add_is_description_missing(df: DataFrame) -> DataFrame:
    """적요가 빈 문자열이거나 NaN이면 True.
    감사 관점: 적요 누락은 거래 목적 불명확."""
```

## 11개 파생변수 요약

| #  | 변수명                     | 타입  | 대응 룰 | 카테고리 |
|----|----------------------------|-------|---------|----------|
| 1  | `is_weekend`               | bool  | R002    | time     |
| 2  | `is_midnight`              | bool  | R003    | time     |
| 3  | `is_period_end`            | bool  | R004    | time     |
| 4  | `is_round_number`          | bool  | —       | amount   |
| 5  | `is_near_threshold`        | bool  | R001    | amount   |
| 6  | `amount_magnitude`         | float | — (ML)  | amount   |
| 7  | `is_reversal`              | bool  | R005    | pattern  |
| 8  | `is_manual_je`             | bool  | R006    | pattern  |
| 9  | `is_intercompany`          | bool  | R008    | pattern  |
| 10 | `has_risk_keyword`         | str   | R007    | text     |
| 11 | `is_description_missing`   | bool  | —       | text     |

## 데이터 흐름
```
[표준 DataFrame] (from ingest)
       ↓
engine.generate_all_features(df, settings)
       ↓
  ├── time_features    → is_weekend, is_midnight, is_period_end
  ├── amount_features  → is_round_number, is_near_threshold, amount_magnitude
  ├── pattern_features → is_reversal, is_manual_je, is_intercompany
  └── text_features    → has_risk_keyword, is_description_missing
       ↓
[피처 보강된 DataFrame] → validation/ → detection/
```

## 구현 순서
1. `time_features.py` — 가장 단순 (날짜 기반 계산)
2. `amount_features.py` — 금액 기반 계산
3. `pattern_features.py` — DataFrame 내 패턴 매칭 (역분개 탐지가 가장 복잡)
4. `text_features.py` — 문자열 매칭 (risk_keywords.yaml 참조)
5. `engine.py` — 4개 서브모듈 통합 오케스트레이션

## 의존성
- **선행:** `02-ingest` (표준 DataFrame), `01-project-setup` (settings, risk_keywords.yaml)
- **외부 패키지:** `pandas`, `numpy`
- **후행:** `04-validation` (피처 보강된 DataFrame 검증), `05-detection` (피처를 입력으로 이상탐지)

## 테스트 전략
- **각 피처 함수 단위 테스트:**
  - 토요일 날짜 → `is_weekend=True` 확인
  - 23시 전표 → `is_midnight=True` 확인
  - 49,500,000원 → `is_near_threshold=True` 확인 (5천만 × 0.98 = 4,900만)
  - 동일 계정·금액 차대 쌍 → `is_reversal=True` 확인
- **edge case:** NaN 적요, 0원 금액, 시간 정보 없는 날짜
- **engine 통합 테스트:** 전체 11개 변수 생성 + 컬럼 존재 확인

## Phase 구분
| 항목                       | Phase               |
|----------------------------|---------------------|
| 11개 파생변수 전체         | MVP (Phase 1a)      |
| NLP 기반 텍스트 피처 확장  | Phase 3 (kiwipiepy) |

## 구현 시 주의사항
- **is_reversal 성능:** 대량 데이터에서 O(n²) 방지 → groupby + merge 활용
- **is_period_end 판정:** 회계기간(fiscal year)이 1~12월이 아닌 경우 대비 → settings에서 설정 가능하게
- **is_near_threshold:** threshold는 회사마다 다름 → settings.approval_threshold로 외부화
- **risk_keywords:** YAML에서 로드하여 하드코딩 방지 → 사용자 커스터마이징 지원
- **컬럼 의존성:** `is_midnight`은 entry_date에 시간 정보가 있어야 작동 → 시간 없으면 skip 또는 warning
