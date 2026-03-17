# 02. 데이터 수집·평탄화 (Ingest)

## 목적
다양한 형태의 Excel/CSV 원본 전표 데이터를 읽어 표준 DataFrame으로 변환한다.
ERP마다 다른 헤더 위치, 컬럼명, 병합셀 등을 자동으로 처리하는 것이 핵심.

## 관련 파일
```
src/ingest/
├── file_validator.py     # 파일 안전성 검증
├── excel_reader.py       # 워크북 읽기, 시트 탐지
├── header_detector.py    # 헤더 행 스코어링, 병합셀 해제
├── column_mapper.py      # fuzzy 매핑 (MVP: 수동 폴백, Phase3: LLM)
├── type_caster.py        # 금액·날짜 타입 캐스팅
└── mapping_profile.py    # 매핑 프로파일 JSON 저장/로드
```

## 핵심 클래스/함수

### `file_validator.py`
```python
@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]      # 치명적 오류
    warnings: list[str]    # 경고 (계속 진행 가능)

def validate_file(path: Path) -> ValidationResult:
    """파일 존재, 확장자, 크기, 손상 여부 검증."""
    # 1. 경로 존재 확인
    # 2. 확장자 검증 (settings.allowed_extensions)
    # 3. 파일 크기 검증 (settings.max_file_size_mb)
    # 4. openpyxl로 파일 오픈 시도 (손상 여부)
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
[사용자 Excel 파일]
       ↓
file_validator.validate_file(path)          → ValidationResult (유효성 검증)
       ↓ (is_valid=True인 경우)
excel_reader.read_workbook(path)            → WorkbookInfo (raw 데이터)
       ↓
header_detector.detect_header_row(sheet)    → header_row: int
       ↓
column_mapper.auto_map_columns(columns)     → MappingResult
       ↓ (needs_review=True면 수동 UI 폴백)
type_caster.cast_amount/cast_date(df)       → 타입 정제된 DataFrame
       ↓
mapping_profile.save_profile()              → JSON 저장 (재사용용)
       ↓
[표준 DataFrame] → feature/ 모듈로 전달
```

## 구현 순서
1. `file_validator.py` — 파일 안전성 검증
2. `excel_reader.py` — 워크북 읽기
3. `header_detector.py` — 헤더 행 탐지 (keywords.yaml 필요)
4. `column_mapper.py` — 컬럼 자동 매핑 (schema.yaml + rapidfuzz)
5. `type_caster.py` — 금액/날짜 타입 변환
6. `mapping_profile.py` — 매핑 결과 저장/로드

## 의존성
- **선행:** `01-project-setup` (settings, YAML 설정 파일)
- **외부 패키지:** `openpyxl`, `pandas`, `rapidfuzz`
- **후행:** `03-feature` (표준 DataFrame을 받아 파생변수 생성)

## 테스트 전략
- **file_validator 테스트:** 정상 파일, 확장자 오류, 크기 초과, 손상 파일
- **excel_reader 테스트:** 단일/멀티 시트, 빈 시트
- **header_detector 테스트:** 1행 헤더, 3행 헤더 (상단 제목 있는 경우), 병합셀 헤더
- **column_mapper 테스트:** 완전 매칭, 부분 매칭, 전혀 다른 컬럼명
- **type_caster 테스트:** 쉼표 금액, 괄호 음수, 다양한 날짜 포맷
- **통합 테스트:** `gl_template.xlsx` → 표준 DataFrame 변환 E2E

## Phase 구분
| 항목 | Phase |
|------|-------|
| file_validator ~ mapping_profile | MVP (Phase 1a) |
| 수동 매핑 UI (column_mapper 폴백) | MVP (Phase 1c) |
| LLM 기반 매핑 보조 | Phase 3 |

## 구현 시 주의사항
- **병합셀 처리:** openpyxl `merged_cells.ranges`로 병합 해제 후 값 복제
- **인코딩:** EUC-KR CSV 대비 `chardet`이나 `cp949` 폴백 고려
- **메모리:** 대용량 파일은 `openpyxl read_only=True` 모드 사용
- **차대 통합 컬럼:** ERP에 따라 금액이 하나의 컬럼(+/-)일 수 있음 → `unify_debit_credit` 필수
- **매핑 실패 시:** Phase 1에서는 Streamlit UI로 수동 매핑 폴백, Phase 3에서 LLM 보조
- **프로파일 재사용:** 동일 ERP 재업로드 시 매핑 프로파일로 자동 적용 → UX 향상
