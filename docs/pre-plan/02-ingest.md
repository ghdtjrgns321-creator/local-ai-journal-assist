# 02. 데이터 수집·평탄화 (Ingest)

## 목적
다양한 형태의 Excel/CSV 원본 전표 데이터를 읽어 표준 DataFrame으로 변환한다.
ERP마다 다른 헤더 위치, 컬럼명, 병합셀 등을 자동으로 처리하는 것이 핵심.

> **메인 데이터**: DataSynth CSV (`data/journal/primary/datasynth/journal_entries.csv`)는
> 표준 스키마와 동일한 컬럼명을 사용하므로 매핑 없이 직접 로드 가능.
> ingest 파이프라인은 **외부 ERP 엑셀 업로드 시** 필요한 모듈이다.

## 관련 파일
```
src/ingest/
├── file_categories.py    # 확장자→카테고리 분류 + 크기 제한 정의
├── integrity_checkers.py # 카테고리별 파일 열기 검증 함수
├── file_validator.py     # validate_file() 퍼사드 (진입점)
├── excel_reader.py       # 워크북 읽기, 시트 탐지
├── header_detector.py    # 헤더 행 스코어링, 병합셀 해제
├── column_mapper.py      # fuzzy 매핑 (MVP: 수동 폴백, Phase3: LLM)
├── type_caster.py        # 금액·날짜 타입 캐스팅
└── mapping_profile.py    # 매핑 프로파일 JSON 저장/로드
```

## 핵심 클래스/함수

### `file_categories.py`
```python
@dataclass(frozen=True)
class FileCategory:
    name: str              # "excel" | "text" | "columnar"
    max_size_mb: int
    extensions: frozenset[str]

# 3개 카테고리 정의
EXCEL    = FileCategory("excel",    100,  frozenset({".xlsx", ".xls", ".xlsb"}))
TEXT     = FileCategory("text",     500,  frozenset({".csv", ".tsv", ".txt", ".dat"}))
COLUMNAR = FileCategory("columnar", 1000, frozenset({".parquet"}))

# 지원하지 않지만 사유 안내가 필요한 확장자
UNSUPPORTED_WITH_REASON: dict[str, str] = {
    ".pdf": "PDF는 비정형 문서입니다. 구조화된 전표 데이터를 사용해주세요.",
    ".hwp": "HWP는 비정형 문서입니다. 구조화된 전표 데이터를 사용해주세요.",
}

def classify_extension(ext: str) -> FileCategory | None:
    """확장자 → FileCategory. 해당 없으면 None."""
```

### `integrity_checkers.py`
```python
# 확장자별 파일 열기 검증 함수
# 반환: tuple[list[str], list[str]]  (errors, warnings)

def check_excel_xlsx(path) -> ...:  # openpyxl load_workbook(read_only=True)
def check_excel_xls(path) -> ...:   # xlrd open_workbook + 레거시 경고
def check_excel_xlsb(path) -> ...:  # pyxlsb open_workbook
def check_text(path) -> ...:        # charset_normalizer 8KB 샘플 인코딩 감지 + 읽기
def check_parquet(path) -> ...:     # pandas read_parquet(columns=[]) 메타만

# 확장자 → 검증 함수 매핑
INTEGRITY_CHECKERS: dict[str, Callable] = { ... }
```

### `file_validator.py`
```python
@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]      # 치명적 오류 → 파이프라인 중단
    warnings: list[str]    # 경고 → 계속 진행 가능
    file_category: str     # "excel" | "text" | "columnar" | "unsupported" | "unknown"

def validate_file(path: Path | str) -> ValidationResult:
    """파일 검증 5단계: 존재 → 확장자 → 빈파일 → 크기 → 무결성.

    확장자별 카테고리에 따라 크기 제한과 검증 전략이 달라진다:
    - excel (.xlsx/.xls/.xlsb): 100MB, 각 라이브러리로 열기 시도
    - text  (.csv/.tsv/.txt/.dat): 500MB, 인코딩 감지 + 읽기 시도
    - columnar (.parquet): 1GB, pyarrow 메타데이터 읽기
    - unsupported (.pdf/.hwp): 거부 + 사유 메시지
    """
```

### `excel_reader.py`
```python
@dataclass
class WorkbookInfo:
    sheets: list[str]          # 시트 이름 목록
    active_sheet: str          # 기본 시트
    raw_data: dict[str, DataFrame]  # 시트별 raw DataFrame

def read_workbook(path: Path) -> WorkbookInfo:
    """워크북의 모든 시트를 raw DataFrame으로 읽는다."""
    # openpyxl로 읽기 (data_only=True)
    # 각 시트를 header=None으로 DataFrame 변환
```

### `header_detector.py`
```python
def detect_header_row(
    sheet_data: DataFrame,
    keywords: dict[str, list[str]]
) -> int:
    """헤더 행을 스코어링 방식으로 탐지.

    각 행에 대해:
    - keywords.yaml의 키워드와 매칭되는 셀 수 카운트
    - 문자열 셀 비율 계산
    - 병합셀이면 해제 후 재평가
    최고 점수 행 = 헤더 행
    """
```

### `column_mapper.py`
```python
@dataclass
class MappingResult:
    mapping: dict[str, str]       # {원본 컬럼: 표준 컬럼}
    confidence: dict[str, float]  # {원본 컬럼: 매칭 점수}
    unmapped: list[str]           # 매핑 실패 컬럼
    needs_review: bool            # confidence < threshold인 것이 있으면 True

def auto_map_columns(
    source_columns: list[str],
    schema: dict,                 # schema.yaml에서 로드
    threshold: int = 80           # settings.fuzzy_threshold
) -> MappingResult:
    """rapidfuzz로 원본 컬럼명을 표준 스키마에 자동 매핑.

    1. keywords.yaml에서 각 표준 컬럼의 알려진 이름 로드
    2. rapidfuzz.process.extractOne으로 최적 매칭
    3. threshold 미만이면 unmapped에 추가
    """
```

### 매핑 확인 UI 흐름 (Phase 1c 대시보드)

`column_mapper.auto_map_columns()`가 반환한 `MappingResult`를 기반으로,
대시보드에서 사용자에게 매핑 결과를 확인/수정할 기회를 제공한다.

**keywords.yaml은 "자동 매칭 적중률을 높이는 힌트"이고, 최종 안전망은 이 UI다.**

```
auto_map_columns() 결과
  ↓
┌─ confidence ≥ 80% ──→ 자동 확정 (초록색 표시)
├─ 40% ≤ confidence < 80% ──→ 추천 표시 + 사용자 확인 필요 (노란색)
└─ confidence < 40% 또는 unmapped ──→ 드롭다운 수동 선택 (빨간색)
```

#### Streamlit UI 예시 (tab_upload.py)
```python
st.subheader("컬럼 매핑 확인")

for src_col, std_col in mapping_result.mapping.items():
    conf = mapping_result.confidence[src_col]
    if conf >= 80:
        # 자동 확정: 수정 가능하지만 기본 선택됨
        st.success(f'✓ "{src_col}" → {std_col} ({conf:.0f}%)')
    else:
        # 사용자 확인 필요
        selected = st.selectbox(
            f'"{src_col}" → ({conf:.0f}%)',
            options=[std_col] + other_standard_columns + ["(매핑 안함)"],
            key=src_col,
        )

for unmapped_col in mapping_result.unmapped:
    st.selectbox(
        f'"{unmapped_col}" → 매핑 대상 선택',
        options=["(매핑 안함)"] + all_standard_columns,
        key=unmapped_col,
    )

# 필수 컬럼 누락 시 진행 차단
missing_required = get_missing_required(final_mapping)
if missing_required:
    st.error(f"필수 컬럼 미매핑: {missing_required}")
else:
    if st.button("매핑 확정 → 다음 단계"):
        save_profile(final_mapping, source_name)  # 재사용용 저장
```

#### 핵심 원칙
- **필수 9컬럼** 중 미매핑이 있으면 진행 차단 (document_id, posting_date 등)
- **권장 컬럼**은 "(매핑 안함)" 허용 — 없어도 탐지 가능
- 확정된 매핑은 `mapping_profile.py`로 JSON 저장 → 동일 ERP 재업로드 시 자동 적용
- DataSynth CSV는 헤더가 정확히 일치하므로 이 UI를 거치지 않고 직접 로드

### `type_caster.py`
```python
def cast_amount(series: pd.Series) -> pd.Series:
    """금액 컬럼을 float으로 변환. 쉼표, 원화 기호, 괄호(음수) 처리."""

def cast_date(series: pd.Series) -> pd.Series:
    """날짜 컬럼을 datetime으로 변환. 다양한 한국어 날짜 포맷 지원."""

def unify_debit_credit(df: DataFrame) -> DataFrame:
    """차변/대변이 하나의 '금액' 컬럼 + '차대구분' 형태인 경우
    debit_amount / credit_amount 두 컬럼으로 분리."""
```

### `mapping_profile.py`
```python
def save_profile(mapping: MappingResult, source_name: str) -> Path:
    """매핑 결과를 JSON으로 저장. 동일 ERP 파일 재업로드 시 재사용."""

def load_profile(source_name: str) -> MappingResult | None:
    """기존 매핑 프로파일 로드. 없으면 None."""
```

## 데이터 흐름
```
[사용자 파일 업로드] (.xlsx/.xls/.xlsb/.csv/.tsv/.txt/.dat/.parquet)
       ↓
file_categories.classify_extension(ext)     → FileCategory (카테고리 분류)
       ↓
file_validator.validate_file(path)          → ValidationResult (5단계 검증)
  ├─ 존재 확인 → 확장자 분류 → 빈파일 → 크기(카테고리별) → 무결성(확장자별)
  └─ .pdf/.hwp → "unsupported" 즉시 거부 + 사유 안내
       ↓ (is_valid=True인 경우)
excel_reader.read_workbook(path)            → WorkbookInfo (raw 데이터)
       ↓
header_detector.detect_header_row(sheet)    → header_row: int
       ↓
column_mapper.auto_map_columns(columns)     → MappingResult
       ↓
  ┌─ needs_review=False (전부 ≥80%) → 자동 진행
  └─ needs_review=True              → 매핑 확인 UI (사용자 확인/수정)
       ↓ (매핑 확정)
type_caster.cast_amount/cast_date(df)       → 타입 정제된 DataFrame
       ↓
mapping_profile.save_profile()              → JSON 저장 (재사용용)
       ↓
[표준 DataFrame] → feature/ 모듈로 전달
```

## 구현 순서
1. `file_categories.py` — 카테고리 정의 (의존성 없음)
2. `integrity_checkers.py` — 확장자별 열기 검증 함수
3. `file_validator.py` — validate_file() 퍼사드
2. `excel_reader.py` — 워크북 읽기
3. `header_detector.py` — 헤더 행 탐지 (keywords.yaml 필요)
4. `column_mapper.py` — 컬럼 자동 매핑 (schema.yaml + rapidfuzz)
5. `type_caster.py` — 금액/날짜 타입 변환
6. `mapping_profile.py` — 매핑 결과 저장/로드

## 의존성
- **선행:** `01-project-setup` (settings, YAML 설정 파일)
- **외부 패키지:**
  - 기존: `openpyxl`, `pandas`, `rapidfuzz`
  - 추가: `xlrd` (.xls), `pyxlsb` (.xlsb), `pyarrow` (.parquet), `charset-normalizer` (인코딩 감지)
- **후행:** `03-feature` (표준 DataFrame을 받아 파생변수 생성)

## 테스트 전략
- **file_categories 테스트:** 모든 확장자→올바른 카테고리 매핑, 미지원 확장자→None
- **file_validator 테스트:** 카테고리별 정상 파일, 확장자 오류, 크기 초과(카테고리별), 손상 파일, 빈 파일, PDF/HWP 거부 메시지
- **excel_reader 테스트:** 단일/멀티 시트, 빈 시트
- **header_detector 테스트:** 1행 헤더, 3행 헤더 (상단 제목 있는 경우), 병합셀 헤더
- **column_mapper 테스트:** 완전 매칭, 부분 매칭, 전혀 다른 컬럼명
- **type_caster 테스트:** 쉼표 금액, 괄호 음수, 다양한 날짜 포맷
- **통합 테스트:** `gl_template.xlsx` → 표준 DataFrame 변환 E2E

## Phase 구분
| 항목                                         | Phase          |
|---------------------------------------------|----------------|
| file_categories + integrity_checkers + file_validator | MVP (Phase 1a) |
| excel_reader ~ mapping_profile               | MVP (Phase 1a) |
| 수동 매핑 UI (column_mapper 폴백)            | MVP (Phase 1c) |
| LLM 기반 매핑 보조                           | Phase 3        |
| PDF/HWP 데이터 추출                          | 범위 외 (별도 프로젝트) |

## 구현 시 주의사항
- **파일 카테고리별 전략:** Excel(100MB/openpyxl·xlrd·pyxlsb), Text(500MB/charset_normalizer), Parquet(1GB/pyarrow) 각각 다른 검증·읽기 전략
- **병합셀 처리:** openpyxl `merged_cells.ranges`로 병합 해제 후 값 복제
- **인코딩:** charset_normalizer로 자동 감지 (EUC-KR/CP949/UTF-8 BOM 등). 8KB 샘플링
- **메모리:** 대용량 파일은 `openpyxl read_only=True` 모드 사용
- **차대 통합 컬럼:** ERP에 따라 금액이 하나의 컬럼(+/-)일 수 있음 → `unify_debit_credit` 필수
- **매핑 실패 시:** Phase 1에서는 Streamlit UI로 수동 매핑 폴백, Phase 3에서 LLM 보조
- **프로파일 재사용:** 동일 ERP 재업로드 시 매핑 프로파일로 자동 적용 → UX 향상
- **PDF/HWP 미지원:** 비정형 문서 데이터 추출은 별도 프로젝트 범위. CONSTRAINTS.md 참고
