# 02. 데이터 수집·평탄화 (Ingest)

## 목적
다양한 형태의 Excel/CSV 원본 전표 데이터를 읽어 표준 DataFrame으로 변환한다.
ERP마다 다른 헤더 위치, 컬럼명, 병합셀 등을 자동으로 처리하는 것이 핵심.

> **메인 데이터**: DataSynth CSV (`data/journal/primary/datasynth/journal_entries.csv`)는
> 표준 스키마와 동일한 컬럼명을 사용하므로 매핑 없이 직접 로드 가능.
> ingest 파이프라인은 **외부 ERP 엑셀 업로드 시** 필요한 모듈이다.

---

## 데이터 흐름

```
[사용자 파일 업로드] (.xlsx/.xls/.xlsb/.csv/.tsv/.txt/.dat/.parquet)
       ↓
① file_validator.validate_file(path)         → 5단계 검증 (존재→확장자→빈파일→크기→무결성)
       ↓ (is_valid=True)
② reader_api.read_file(path)                → 시트별 raw DataFrame (포맷별 자동 디스패치)
       ↓
③ header_detector.detect_header_row(sheet)   → 헤더 행 위치
       ↓
④ column_mapper.auto_map_columns(columns)    → 원본→표준 컬럼 매핑
       ↓
  ┌─ 전부 ≥80% → 자동 진행
  └─ 일부 <80% → 매핑 확인 UI (Phase 1c)
       ↓ (매핑 확정)
⑤ type_caster.cast_amount/cast_date(df)      → 타입 정제된 DataFrame
       ↓
⑥ mapping_profile.save_profile()             → JSON 저장 (재사용)
       ↓
[표준 DataFrame] → feature/ 모듈로 전달
```

---

## 구현 상태 & 모듈별 가이드

### ① 파일 검증 — ✅ 구현 완료

```
src/ingest/
├── file_categories.py     # 확장자→카테고리 분류 + 크기 제한
├── integrity_checkers.py  # 카테고리별 파일 열기 검증
└── file_validator.py      # validate_file() 퍼사드
```

**구현 내용:**
- 10개 확장자를 3개 카테고리로 분류, 카테고리별 크기 제한·검증 전략 분리
- PDF/HWP는 "unsupported"로 거부 + 사유 안내 (CONSTRAINTS.md)

| 카테고리  | 확장자                       | 크기 제한 | 검증 방법                      |
|----------|------------------------------|----------|-------------------------------|
| excel    | .xlsx, .xls, .xlsb          | 100MB    | openpyxl / xlrd / pyxlsb 열기 |
| text     | .csv, .tsv, .txt, .dat      | 500MB    | charset_normalizer 인코딩 감지 |
| columnar | .parquet                     | 1GB      | pyarrow 메타데이터 읽기         |

**검증 5단계:** 존재 → 확장자 → 빈파일 → 크기(카테고리별) → 무결성(확장자별)
**error/warning 분류:** error = 파이프라인 중단 / warning = 계속 진행 + 사용자 안내
**테스트:** [32개 통과](../../tests/test_ingest/test-results/ingest-file-validator.md) (확장자 분류 15 + 경로 2 + 확장자 3 + 빈파일 1 + 크기 2 + 무결성 7 + 출력 2)

---

### ② 파일 읽기 — ✅ 구현 완료

검증 통과된 파일을 포맷별 리더로 읽어 통합 `ReadResult`로 반환한다.
pre-plan 초안은 xlsx만 고려했으나, **10개 확장자 전체를 지원**하도록 확장.

#### 모듈 구조 (4개 리더 + 1개 퍼사드 + 1개 모델)

```
src/ingest/
├── models.py           # ReadResult dataclass (순환참조 방지용 별도 모듈)
├── excel_reader.py     # xlsx/xls/xlsb → ReadResult
├── text_reader.py      # csv/tsv/txt/dat → ReadResult (DataSynth CSV fast path)
├── parquet_reader.py   # parquet → ReadResult
└── reader_api.py       # read_file() 퍼사드 — 확장자 기반 디스패치
```

#### 설계 결정

| 이슈                              | 결정                        | 사유                                               |
|----------------------------------|----------------------------|----------------------------------------------------|
| `read_only=True` vs 병합셀 충돌   | **`read_only=False`** 사용  | read_only에서 merged_cells 접근 불가. 100MB 제한이 안전장치 |
| Multi-format 지원                 | 포맷별 리더 분리 + 퍼사드    | xlsx/xls/xlsb/csv/parquet API가 모두 다름             |
| CSV fast path                    | `pd.read_csv` 직접 호출     | DataSynth 232MB CSV가 메인 데이터                     |
| 통합 반환 타입                    | `ReadResult` (WorkbookInfo 대체) | CSV/Parquet에는 시트 개념 없음 → 정규화 필요          |
| 인코딩 감지 중복                  | text_reader에서 재감지       | integrity_checkers 시그니처 변경 시 32개 기존 테스트 영향 |
| 메모리 (232MB CSV → ~1.5GB)      | Phase 1a에서는 최적화 안 함  | 16GB RAM 충분. 문제 시 chunksize 대응                 |

#### excel_reader.py

**구현할 것:**
- `_read_xlsx(path)`: openpyxl `data_only=True` (read_only=**False**), 병합셀 해제 + 값 복제
- `_read_xls(path)`: xlrd, `sheet.merged_cells`로 병합셀 처리
- `_read_xlsb(path)`: pyxlsb, 병합셀 정보 없음 → warning 로깅
- `read_excel(path)`: 확장자별 내부 함수 디스패치
- 모든 시트를 `header=None` DataFrame으로 변환 (헤더는 다음 단계에서 탐지)

**병합셀 처리 흐름:**
```
ws.merged_cells.ranges 순회 → unmerge → 좌상단 값을 모든 셀에 복제 → pd.DataFrame(ws.values)
```

#### text_reader.py

**구현할 것:**
- `_detect_encoding(path)`: charset_normalizer 64KB 샘플링
- `_detect_separator(path, encoding)`: csv.Sniffer로 구분자 감지, 실패 시 확장자 폴백
- `read_text(path)`: `pd.read_csv(path, sep, encoding, header=None, dtype=str)`
- `sheets=["Sheet1"]`로 정규화하여 다운스트림 호환

#### parquet_reader.py

**구현할 것:**
- `read_parquet(path)`: `pd.read_parquet(path)`, 타입 보존 (str 변환 안 함)
- `sheets=["Sheet1"]`로 정규화

#### reader_api.py (퍼사드)

**구현할 것:**
- `read_file(path) -> ReadResult`: 확장자 기반 디스패치
- 미지원 확장자 → `ValueError` (정상적으로는 file_validator에서 이미 걸림)

**테스트:** [24개 통과](../../tests/test_ingest/test-results/ingest-file-reader.md) (excel 8 + text 7 + parquet 3 + reader_api 6)

---

### ③ 헤더 행 탐지 — ✅ 구현 완료

```
src/ingest/
├── header_detector.py  # detect_header_row() + detect_headers() 퍼사드
└── models.py           # HeaderDetectionResult 추가
```

**스코어 공식:**
```
Confidence = (KeywordScore × 0.8) + (StringRatio × 0.2)

KeywordScore = min(matched / MIN_EXPECTED_HEADERS, 1.0)  # MIN_EXPECTED_HEADERS=4
StringRatio  = string_cells / valid_cells                 # NaN 제외, 0/0 방어
```

**설계 결정:**

| 항목             | 결정                                                    |
|:-----------------|:-------------------------------------------------------|
| 매칭 방식        | 정확 일치 (`strip().lower()`) — fuzzy 불필요            |
| 탐색 범위        | 상위 20행 (`max_header_scan_rows`, settings.py 튜닝)    |
| 메시지 3단계     | >= 0.7 자동패스 / 0.3~0.7 UI경고 / < 0.3 수동입력      |
| 동점 처리        | strict `>` 비교 → 상단 행 우선                          |
| 멀티시트         | `detect_headers(ReadResult)` 퍼사드로 일괄 처리         |
| 빈 DF/NaN        | 빈 DF → 즉시 실패, NaN 행 → 스코어링에서 자연 처리     |

**반환 타입:** `HeaderDetectionResult(header_row, confidence, matched_keywords, total_columns, message)`

**테스트:** [12개 통과](../../tests/test_ingest/test-results/ingest-header-detector.md) (핵심 탐지 8 + 메시지 3단계 3 + 멀티시트 1)

**부수 변경:** `AuditSettings.model_config`에 `extra="ignore"` 추가 — 환경변수 확장 시 ValidationError 방지

---

### ④ 컬럼 자동 매핑 — ✅ 구현 완료

```
src/ingest/
├── column_mapper.py   # auto_map_columns() + map_columns() 퍼사드
└── models.py          # MappingResult 추가
```

**알고리즘 (Exact → Fuzzy 2단계):**
```
1. fast path: 필수 9컬럼 정확 일치 → 동일 매핑 즉시 반환 (DataSynth CSV 등)
2. Phase 1 (Exact): keywords.yaml 별칭 + header_detector matched_keywords로 정확 일치
3. Phase 2 (Fuzzy): 미매칭 컬럼만 rapidfuzz.process.extractOne
4. greedy assign: 스코어 내림차순 1:1 할당 (충돌 해결)
5. 3-tier 분류: mapping(>=80) / suggestions(40~80) / unmapped(<40)
```

**설계 결정:**

| 항목                            | 결정                                                               |
|:--------------------------------|:------------------------------------------------------------------|
| 매핑 방향                       | `{원본: 표준}` → `df.rename(columns=mapping)` 바로 사용            |
| threshold 단위                  | 내부 비교 0-100, confidence 저장 시 /100 → 0.0~1.0                 |
| 1:1 충돌 해결                   | 스코어 내림차순 greedy 할당, 이미 할당된 표준 컬럼 스킵             |
| fast path 판정                  | 필수 9컬럼 정확 일치 → 소스 무관 일반화                            |
| 설정 주입                       | 내부에서 schema/keywords/settings 자동 로드, 테스트 시만 주입       |
| "전표유형" 충돌                 | source에서 제거 → document_type으로 이동                            |

**반환 타입:** `MappingResult(mapping, suggestions, confidence, unmapped, missing_required, needs_review)`

**3-tier 매핑 확인 UI (Phase 1c):**
```
confidence >= 80%  → 자동 확정 (초록)   → mapping
40% <= conf < 80%  → 추천 + 사용자 확인 (노랑) → suggestions
conf < 40%         → 수동 선택 (빨강)   → unmapped
```
- 필수 9컬럼 미매핑 시 진행 차단 (`missing_required`)
- DataSynth CSV는 fast path → UI 스킵

**테스트:** [25개 통과](../../tests/test_ingest/test-results/ingest-column-mapper.md) (prepare 3 + fast path 2 + exact 3 + fuzzy 3 + 충돌 2 + 통합 5 + 퍼사드 2 + 헬퍼 5)

**부수 변경:**
- `keywords.yaml`: 10개 컬럼 별칭 추가 (fiscal_year~business_process), source에서 "전표유형" 제거
- `settings.py`: `fuzzy_low_threshold: int = 40` 추가

---

### ⑤ 타입 캐스팅 — 🔲 미구현

`type_caster.py` — 금액·날짜 컬럼을 올바른 타입으로 변환한다.

**구현할 것:**
- `cast_amount`: 쉼표, 원화 기호(₩), 괄호 음수 처리 → float
- `cast_date`: 다양한 한국어 날짜 포맷 → datetime
- `unify_debit_credit`: 단일 금액 컬럼(+/-) → debit_amount/credit_amount 분리

---

### ⑥ 매핑 프로파일 — 🔲 미구현

`mapping_profile.py` — 매핑 결과를 JSON으로 저장/로드한다.

**구현할 것:**
- `save_profile`: MappingResult → JSON 저장
- `load_profile`: 동일 ERP 재업로드 시 기존 매핑 자동 적용 → UX 향상

---

## 구현 순서

1. ~~`file_categories.py`~~ ✅
2. ~~`integrity_checkers.py`~~ ✅
3. ~~`file_validator.py`~~ ✅
4. `models.py` (ReadResult dataclass)
5. `parquet_reader.py` (가장 단순)
6. `text_reader.py` (CSV fast path — 메인 데이터 경로)
7. `excel_reader.py` (병합셀 처리 — 가장 복잡)
8. `reader_api.py` (퍼사드 — 모든 리더 완성 후)
9. `header_detector.py` (keywords.yaml 필요)
10. `column_mapper.py` (schema.yaml + rapidfuzz)
11. `type_caster.py`
12. `mapping_profile.py`

## 의존성

- **선행:** `01-project-setup` (settings, YAML 설정 파일)
- **외부 패키지:**
  - 기존: `openpyxl`, `pandas`, `rapidfuzz`
  - 추가: `xlrd` (.xls), `pyxlsb` (.xlsb), `pyarrow` (.parquet), `charset-normalizer` (인코딩 감지)
- **후행:** `03-feature` (표준 DataFrame을 받아 파생변수 생성)

## Phase 구분

| 항목                                                   | Phase                 |
|-------------------------------------------------------|-----------------------|
| file_categories + integrity_checkers + file_validator  | MVP (Phase 1a) ✅     |
| models + readers(excel/text/parquet) + reader_api      | MVP (Phase 1a)        |
| header_detector ~ mapping_profile                      | MVP (Phase 1a)        |
| 수동 매핑 UI (column_mapper 폴백)                       | MVP (Phase 1c)        |
| LLM 기반 매핑 보조                                      | Phase 3               |
| PDF/HWP 데이터 추출                                     | 범위 외 (별도 프로젝트) |

## 테스트 전략

- **file_categories:** 모든 확장자→올바른 카테고리, 미지원→None ✅ 32 passed
- **file_validator:** 정상/손상/빈/초과/PDF거부 등 카테고리별 ✅ 32 passed
- **excel_reader:** 단일/멀티 시트, 빈 시트, 병합셀 해제+값복제, xls/xlsb
- **text_reader:** UTF-8, CP949, BOM, TSV 구분자 자동감지, dtype=str 검증
- **parquet_reader:** 기본 읽기, 타입 보존
- **reader_api:** 확장자별 디스패치, 미지원 확장자 ValueError
- **header_detector:** 1행 헤더, 3행 헤더, 병합셀 헤더
- **column_mapper:** 완전 매칭, 부분 매칭, 전혀 다른 컬럼명
- **type_caster:** 쉼표 금액, 괄호 음수, 다양한 날짜 포맷
- **통합 테스트:** `gl_template.xlsx` → 표준 DataFrame 변환 E2E

---

## 부록: API 레퍼런스

<details>
<summary>클릭하여 상세 함수 시그니처 보기</summary>

### file_categories.py
```python
@dataclass(frozen=True)
class FileCategory:
    name: str              # "excel" | "text" | "columnar"
    max_size_mb: int
    extensions: frozenset[str]

EXCEL    = FileCategory("excel",    100,  frozenset({".xlsx", ".xls", ".xlsb"}))
TEXT     = FileCategory("text",     500,  frozenset({".csv", ".tsv", ".txt", ".dat"}))
COLUMNAR = FileCategory("columnar", 1000, frozenset({".parquet"}))

UNSUPPORTED_WITH_REASON: dict[str, str] = {".pdf": "...", ".hwp": "..."}

def classify_extension(ext: str) -> FileCategory | None: ...
```

### integrity_checkers.py
```python
def check_excel_xlsx(path) -> tuple[list[str], list[str]]:  # openpyxl
def check_excel_xls(path) -> tuple[list[str], list[str]]:   # xlrd
def check_excel_xlsb(path) -> tuple[list[str], list[str]]:  # pyxlsb
def check_text(path) -> tuple[list[str], list[str]]:        # charset_normalizer
def check_parquet(path) -> tuple[list[str], list[str]]:      # pyarrow

INTEGRITY_CHECKERS: dict[str, Callable] = { ... }
```

### file_validator.py
```python
@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    file_category: str  # "excel" | "text" | "columnar" | "unsupported" | "unknown"

def validate_file(path: Path | str) -> ValidationResult: ...
```

### models.py
```python
@dataclass
class ReadResult:
    sheets: list[str]              # CSV/parquet: ["Sheet1"]로 정규화
    active_sheet: str
    raw_data: dict[str, DataFrame]
    encoding: str | None = None    # 텍스트만 해당
    source_format: str = ""        # "xlsx" | "csv" | "parquet" 등
```

### reader_api.py
```python
def read_file(path: Path) -> ReadResult:
    """확장자 기반 디스패치. Raises ValueError(미지원), IOError(읽기 실패)."""
```

### excel_reader.py
```python
def read_excel(path: Path) -> ReadResult:
    """xlsx/xls/xlsb → ReadResult. 병합셀 해제 + 값 복제."""
```

### text_reader.py
```python
def read_text(path: Path) -> ReadResult:
    """csv/tsv/txt/dat → ReadResult. 인코딩·구분자 자동 감지, dtype=str."""
```

### parquet_reader.py
```python
def read_parquet(path: Path) -> ReadResult:
    """parquet → ReadResult. 타입 보존."""
```

### header_detector.py
```python
@dataclass
class HeaderDetectionResult:
    header_row: int | None       # None = 탐지 실패
    confidence: float            # 0.0~1.0
    matched_keywords: list[str]  # 매칭된 키워드 원본명
    total_columns: int
    message: str                 # 사용자 안내 메시지

def detect_header_row(sheet_data: DataFrame, keywords: dict | None = None) -> HeaderDetectionResult: ...
def detect_headers(read_result: ReadResult, keywords: dict | None = None) -> dict[str, HeaderDetectionResult]: ...
```

### column_mapper.py
```python
@dataclass
class MappingResult:
    mapping: dict[str, str]
    confidence: dict[str, float]
    unmapped: list[str]
    needs_review: bool

def auto_map_columns(source_columns: list[str], schema: dict, threshold: int = 80) -> MappingResult: ...
```

### type_caster.py
```python
def cast_amount(series: pd.Series) -> pd.Series: ...
def cast_date(series: pd.Series) -> pd.Series: ...
def unify_debit_credit(df: DataFrame) -> DataFrame: ...
```

### mapping_profile.py
```python
def save_profile(mapping: MappingResult, source_name: str) -> Path: ...
def load_profile(source_name: str) -> MappingResult | None: ...
```

</details>
