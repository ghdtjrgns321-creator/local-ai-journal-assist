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

#### 파이프라인 오케스트레이터 (Phase 1c 예정)

위 ①~⑥을 순차 호출하는 단일 진입점. Phase 1c에서 UI와 함께 구현 예정.

```python
# 인터페이스 초안 — Phase 1c에서 구체화
def run_ingest_pipeline(path: Path) -> IngestResult:
    """파일 경로 → 표준 DataFrame 변환 전체 파이프라인.

    Returns: IngestResult(data, mapping_result, casting_result, state, warnings)
    state: COMPLETED | NEEDS_REVIEW | FAILED
    """
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
| text     | .csv, .tsv, .txt, .dat      | 800MB    | charset_normalizer 인코딩 감지 |
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
├── header_detector.py    # detect_header_row() + detect_headers() 퍼사드
├── _header_scoring.py    # 구조적 스코어 함수 3개 (type_diversity, uniqueness, null_density)
└── models.py             # HeaderDetectionResult 추가
```

**스코어 공식 (v2 — 구조적 신호 기반):**
```
Confidence = TypeDiversity × 0.35 + Uniqueness × 0.25 + NullDensity × 0.15
           + KeywordScore × 0.15 + StringRatio × 0.10

TypeDiversity = 순수문자열 셀 / 유효 셀    # 헤더=100% 문자열, 데이터=숫자/날짜 혼재
Uniqueness    = 고유값 / 유효 셀            # 헤더=고유, 데이터=반복값 존재
NullDensity   = notna 셀 / 전체 컬럼       # 헤더=NaN 거의 없음
KeywordScore  = min(matched / 4, 1.0)       # 보조 신호 (0.80→0.15로 격하)
StringRatio   = 문자열 셀 / 유효 셀
```

**v1→v2 변경 이유:** 키워드 의존도 80%→15%로 낮춰 미등록 컬럼명에도 작동.
비회계 파일도 헤더 탐지 성공 (올바른 동작) → column_mapper에서 필수 컬럼 미매핑으로 차단.

**설계 결정:**

| 항목             | 결정                                                    |
|:-----------------|:-------------------------------------------------------|
| 스코어 신호      | 5개 가중합 (구조 70% + 키워드/문자열 30%)               |
| 매칭 방식        | 정확 일치 (`strip().lower()`) — fuzzy 불필요            |
| 탐색 범위        | 상위 20행 (`max_header_scan_rows`, settings.py 튜닝)    |
| 메시지 4분기     | 키워드有/無 × 신뢰도高/低 → 4가지 메시지               |
| 동점 처리        | strict `>` 비교 → 상단 행 우선                          |
| 멀티시트         | `detect_headers(ReadResult)` 퍼사드로 일괄 처리         |
| 빈 DF/NaN        | 빈 DF → 즉시 실패, NaN 행 → 스코어링에서 자연 처리     |

**반환 타입:** `HeaderDetectionResult(header_row, confidence, matched_keywords, total_columns, message)`

**테스트:** 21개 통과 (핵심 탐지 8 + 메시지 3단계 3 + 구조적 스코어링 9 + 멀티시트 1)

**중복 헤더 처리 정책 (Phase 1c 구현 예정):**
- Pandas는 중복 컬럼명에 `.1`, `.2` 접미사를 자동 부여 (예: `금액`, `금액.1`)
- 정책: 중복 컬럼 감지 시 `warnings`에 기록 + 첫 번째 우선 매핑 + UI에서 사용자 선택 대기
- Phase 1c에서 매핑 UI와 함께 구현 (사용자가 중복 컬럼 중 어떤 것이 차변/대변인지 직접 선택)

**부수 변경:** `AuditSettings.model_config`에 `extra="ignore"` 추가 — 환경변수 확장 시 ValidationError 방지

---

### ④ 컬럼 자동 매핑 — ✅ 구현 완료

```
src/ingest/
├── column_mapper.py    # auto_map_columns() + map_columns() 퍼사드
├── _type_compat.py     # infer_column_type + validate_type_compatibility (B1 타입 검증)
└── models.py           # MappingResult + ReviewItem 추가
```

**알고리즘 (Exact → Fuzzy+타입검증 2단계):**
```
1. fast path: 필수 9컬럼 정확 일치 → 동일 매핑 즉시 반환 (DataSynth CSV 등)
2. Phase 1 (Exact): keywords.yaml 별칭으로 정확 일치
3. Phase 2 (Fuzzy): 미매칭 컬럼만 rapidfuzz.process.extractOne
   + 타입 호환성 검증 (B1): data_df 상위 100행 → 소스 타입 추론 → 스키마 타입 비교
   → 비호환 시 스코어 0 (차단) 예: drcrk(str) → debit_amount(float)
4. greedy assign: 스코어 내림차순 1:1 할당 (충돌 해결)
5. 3-tier 분류: mapping(>=80) / suggestions(40~80) / unmapped(<40)
6. ReviewItem 리스트 생성 (투명성 레이어)
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

**반환 타입:** `MappingResult(mapping, suggestions, confidence, unmapped, missing_required, needs_review, review_items)`

**ReviewItem (투명성 UX 데이터 모델):**
```python
ReviewItem(column, action, confidence, reason, source_type?, target_type?)
# action: "auto" | "review" | "blocked" | "empty"
# Phase 1c UI에서 매핑 판단 근거 노출용
```

**3-tier 매핑 확인 UI (Phase 1c):**
```
confidence >= 80%  → 자동 확정 (초록)   → mapping
40% <= conf < 80%  → 추천 + 사용자 확인 (노랑) → suggestions
conf < 40%         → 수동 선택 (빨강)   → unmapped
```
- 필수 9컬럼 미매핑 시 진행 차단 (`missing_required`)
- DataSynth CSV는 fast path → UI 스킵

**테스트:** 37개 통과 (prepare 3 + fast path 2 + exact 3 + fuzzy 3 + 충돌 2 + 통합 5 + 퍼사드 2 + 헬퍼 5 + 타입추론 5 + 타입호환 6 + ReviewItem 2 + dc_indicator 1)

**부수 변경:**
- `keywords.yaml`: 10개 컬럼 별칭 추가 (fiscal_year~business_process), source에서 "전표유형" 제거, `dc_indicator` 추가 (drcrk/shkzg)
- `schema.yaml`: `dc_indicator` 컬럼 추가 (str, required=false)
- `settings.py`: `fuzzy_low_threshold: int = 40` 추가

---

### ⑤ 타입 캐스팅 — ✅ 구현 완료

```
src/ingest/
├── type_caster.py    # cast_amount/cast_date/_cast_int/_cast_bool/unify_debit_credit + cast_dataframe() 퍼사드
└── models.py         # CastingResult 추가
```

**알고리즘:**
```
1. cast_dataframe(df, schema) 진입
2. schema.yaml → {컬럼명: type} 맵 생성
3. 컬럼 순회 → 이미 올바른 dtype이면 스킵(Parquet fast path)
4. 타입별 캐스터 디스패치: float→cast_amount, date→cast_date, int→_cast_int, bool→_cast_bool, str→_cast_str
5. 필수 컬럼 실패 → errors, 권장 컬럼 실패 → warnings
6. 결측률 > 10% → warnings
7. debit/credit 없고 amount 있으면 → unify_debit_credit 호출
8. CastingResult 반환
```

**설계 결정:**

| 항목                    | 결정                                                           |
|:------------------------|:--------------------------------------------------------------|
| 퍼사드 추가             | `cast_dataframe()` — 파이프라인 단일 진입점 (문서 대비 추가)   |
| int/bool 캐스팅         | `_cast_int()`/`_cast_bool()` 추가 — fiscal_year, is_fraud 등  |
| str 캐스팅              | `_cast_str()` 추가 — Excel int64→str 변환, NaN 보존           |
| Parquet fast path       | `_is_already_correct_type()` — 이미 올바른 dtype이면 스킵     |
| 금액 처리 순서          | 통화기호→괄호음수→쉼표 제거 후 `pd.to_numeric(coerce)`         |
| 날짜 5단계 폴백         | ISO8601→한국어→8자리→Excel serial→dayfirst 폴백               |
| 차대변 통합 3케이스     | Case A(이미 분리), B(DC indicator), C(부호 기반)              |
| 유럽 금액 포맷          | MVP 범위 외 — Phase 2에서 확장                                 |

**반환 타입:** `CastingResult(data, errors, warnings, cast_summary, skipped_columns, high_null_columns, empty_columns, success)`

**Null 3단계 분기 (B3):**
```
원본 100% NaN → empty_columns (유령 컬럼, 경고 없음)
캐스팅 후 >90% NaN → high_null_columns (오매핑 의심 경고)
캐스팅 후 >10% NaN → warnings (일반 경고)
```

**테스트:** 44개 통과 (cast_amount 9 + cast_date 8 + cast_int 4 + cast_str 5 + cast_bool 3 + unify 4 + 퍼사드 6 + null_demote 5)

**부수 변경:**
- `models.py`: `CastingResult` dataclass에 `high_null_columns`, `empty_columns` 추가
- `settings.py`: `casting_null_warn_threshold`, `casting_date_dayfirst`, `casting_null_demote_threshold` 추가
- `__init__.py`: `cast_dataframe`, `CastingResult` export 추가
- `text_reader.py`: ascii→latin-1 폴백 (charset_normalizer 64KB 샘플 오탐 대응)

---

### ⑥ 매핑 프로파일 — ✅ 구현 완료

```
src/ingest/
└── mapping_profile.py   # save_profile/load_profile/list_profiles/delete_profile
```

**매칭 전략:** 원본 컬럼명 집합의 SHA-256 해시(fingerprint, 앞 12자)로 프로파일 식별.
순서·대소문자 무관 → 동일 ERP면 동일 fingerprint.

**2계층 저장 구조:**
```
data/profiles/
├── {fingerprint}.json              ← 확정 매핑 프로파일 (load_profile 대상)
└── logs/
    └── {fingerprint}_{timestamp}.json  ← 메타데이터 로그 (suggestions, unmapped)
```

**설계 결정:**

| 항목                  | 결정                                                            |
|:----------------------|:---------------------------------------------------------------|
| 프로파일 저장 범위    | 확정 매핑(mapping + confidence)만 저장                          |
| 불확실 정보 분리      | suggestions/unmapped → 별도 로그 파일로 분리                    |
| 재저장 시             | created_at 유지, updated_at만 갱신                              |
| 손상 JSON 처리        | load_profile → None 반환 + 경고 로그                            |
| 로드된 결과           | suggestions=빈, needs_review=False (확정 매핑만 복원)           |
| 삭제 시               | 프로파일 + 관련 로그 모두 삭제                                  |

**API:**
- `column_fingerprint(columns)` → SHA-256 앞 12자
- `save_profile(result, source_columns, **meta)` → Path
- `load_profile(source_columns)` → MappingResult | None
- `list_profiles()` → list[dict] (최신 순)
- `delete_profile(fingerprint)` → bool

**테스트:** [26개 통과](../../tests/test_ingest/test-results/ingest-mapping-profile.md) (fingerprint 6 + save 5 + log 3 + load 5 + list 3 + delete 3 + 통합 1)

---

## 구현 순서

1. ~~`file_categories.py`~~ ✅
2. ~~`integrity_checkers.py`~~ ✅
3. ~~`file_validator.py`~~ ✅
4. ~~`models.py` (ReadResult dataclass)~~ ✅
5. ~~`parquet_reader.py` (가장 단순)~~ ✅
6. ~~`text_reader.py` (CSV fast path — 메인 데이터 경로)~~ ✅
7. ~~`excel_reader.py` (병합셀 처리 — 가장 복잡)~~ ✅
8. ~~`reader_api.py` (퍼사드 — 모든 리더 완성 후)~~ ✅
9. ~~`header_detector.py` (keywords.yaml 필요)~~ ✅
10. ~~`column_mapper.py` (schema.yaml + rapidfuzz)~~ ✅
11. ~~`type_caster.py`~~ ✅
12. ~~`mapping_profile.py`~~ ✅

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
| models + readers(excel/text/parquet) + reader_api      | MVP (Phase 1a) ✅     |
| header_detector ~ mapping_profile                      | MVP (Phase 1a) ✅     |
| pipeline orchestrator (run_ingest_pipeline)             | MVP (Phase 1c)        |
| 수동 매핑 UI (column_mapper 폴백)                       | MVP (Phase 1c)        |
| LLM 기반 매핑 보조                                      | Phase 3               |
| PDF/HWP 데이터 추출                                     | 범위 외 (별도 프로젝트) |

---

## 대용량 파일 처리 전략 (Phase별 로드맵)

> Phase 1a 분석 결과 기록. 현 파이프라인이 전부 pandas 기반이므로
> DuckDB/Polars 전면 전환은 시기상조. 단계적으로 확장한다.

### Phase 1a (현재) — 크기 제한 상향

- TEXT 카테고리 500MB → **800MB** (`file_categories.py` 1줄)
- 16GB RAM에서 800MB CSV → pandas ~5GB → Streamlit/OS 제외 여유 충분
- 80% 경고(640MB+)에 "기간을 좁혀 추출하면 처리 속도가 향상됩니다" 안내 추가
- **판단 근거**: 1GB는 Phase 2/3에서 Ollama(3~5GB) + detection 동시 실행 시 OOM 위험

### Phase 1b (DuckDB 도입 시) — 적재 시점 최적화

- ingest 완료 후 **표준 DataFrame → DuckDB 적재** 시 대용량 최적화
- 500MB+ DataFrame은 **Parquet 중간 저장 → DuckDB COPY** 경로 (피크 메모리 절감)
- 상세: [06-db.md → 대용량 파일 직접 적재](06-db.md#대용량-파일-직접-적재-phase-1b-확장-고려)

### Phase 2+ (선택) — DuckDB를 ingest 리더로 전면 전환

- `duckdb.read_csv_auto()`로 pandas 우회 → 메모리 근본 해결
- **전제 조건**: header_detector/column_mapper/type_caster SQL 재작성 + cp949 인코딩 대응
- **판단 기준**: Phase 2 시점에서 실제 메모리 병목 발생 시 검토

### 검토했으나 보류한 방안

| 방안              | 보류 사유                                                       |
|:------------------|:---------------------------------------------------------------|
| pandas chunksize  | concat 시 전체 메모리 사용 동일 → 피크만 줄고 근본 해결 아님    |
| Polars 전환       | 전체 재작성 비용 + 학습 곡선 → Phase 3+에서 재검토               |
| 사용자 분할 요청  | 단독 전략 부적절 (ERP 추출 파일 재분할 비합리) → 경고 안내로만  |

## 테스트 전략

- **file_categories:** 모든 확장자→올바른 카테고리, 미지원→None ✅ 32 passed
- **file_validator:** 정상/손상/빈/초과/PDF거부 등 카테고리별 ✅ 32 passed
- **excel_reader:** 단일/멀티 시트, 빈 시트, 병합셀 해제+값복제, xls/xlsb ✅ 24 passed (reader 전체)
- **text_reader:** UTF-8, CP949, BOM, TSV 구분자 자동감지, dtype=str 검증 ✅ (위 24에 포함)
- **parquet_reader:** 기본 읽기, 타입 보존 ✅ (위 24에 포함)
- **reader_api:** 확장자별 디스패치, 미지원 확장자 ValueError ✅ (위 24에 포함)
- **header_detector:** 1행/3행/병합셀 헤더 + 구조적 스코어링(v2) + 메시지 분기 ✅ 20 passed
- **column_mapper:** exact/fuzzy + 타입 호환성 검증(v2) + ReviewItem + dc_indicator ✅ 38 passed
- **type_caster:** 금액/날짜/정수/문자열/불리언 캐스팅 + Null 3단계 분기(v2) ✅ 44 passed
- **mapping_profile:** fingerprint, save/load/list/delete, 통합 ✅ 26 passed
- **text_reader:** ascii→latin-1 폴백(v2)으로 bpi2019(527MB, latin-1) 읽기 성공
- **validation 데이터셋:** 5종 전체 파이프라인 통과 (bpi2019 포함) ✅ 6 passed → [결과](../../tests/test_ingest/test-results/ingest-validation-datasets.md)
- **통합 테스트:** `gl_template.xlsx` → 표준 DataFrame 변환 E2E — Phase 1c에서 구현 예정

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
TEXT     = FileCategory("text",     800,  frozenset({".csv", ".tsv", ".txt", ".dat"}))
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
    """csv/tsv/txt/dat 인코딩·구분자 자동 감지, dtype=str."""
```

### parquet_reader.py
```python
def read_parquet(path: Path) -> ReadResult:
    """parquet → ReadResult"""
```

### header_detector.py
```python
@dataclass
class HeaderDetectionResult:
    header_row: int | None = None    # 탐지 실패
    confidence: float = 0.0
    matched_keywords: list[str]      # 매칭된 키워드 원본명 (예: ["전표일자", "차변"])
    total_columns: int = 0
    message: str = ""                # 사용자 안내 메시지

def detect_header_row(df: pd.DataFrame, keywords: dict | None = None) -> HeaderDetectionResult: ...
def detect_headers(result: ReadResult, keywords: dict | None = None) -> dict[str, HeaderDetectionResult]: ...
```

### column_mapper.py
```python
@dataclass
class MappingResult:
    mapping: dict[str, str]        # 확정 매핑 {원본: 표준}
    suggestions: dict[str, str]    # 추천 매핑 {원본: 표준} — UI 확인 대기
    confidence: dict[str, float]   # mapping+suggestions 전체 (0.0~1.0)
    unmapped: list[str]            # 매핑 불가 원본 컬럼명
    missing_required: list[str]    # 필수 표준 컬럼 중 미매핑
    needs_review: bool             # suggestions 있거나 missing_required 있으면 True
    review_items: list[ReviewItem] # 판단 근거 리스트 (v2)

def auto_map_columns(source_columns, matched_keywords=None, *, data_df=None, ...) -> MappingResult: ...
```

### type_caster.py
```python
@dataclass
class CastingResult:
    data: pd.DataFrame
    errors: list[str]
    warnings: list[str]
    cast_summary: dict[str, str]     # {"posting_date": "object→datetime64[ns]"}
    skipped_columns: list[str]       # Parquet fast path
    high_null_columns: list[str]     # 캐스팅 후 90%+ NaN (오매핑 의심, v2)
    empty_columns: list[str]         # 원본 100% NaN (유령 컬럼, v2)
    success: bool

def cast_amount(series: pd.Series) -> pd.Series: ...   # → float64
def cast_date(series: pd.Series) -> pd.Series: ...     # → datetime64[ns]
def _cast_int(series: pd.Series) -> pd.Series: ...     # → Int64 (nullable)
def _cast_str(series: pd.Series) -> pd.Series: ...     # → str (object), NaN→pd.NA 보존
def _cast_bool(series: pd.Series) -> pd.Series: ...    # → boolean (nullable)
def unify_debit_credit(df: DataFrame) -> tuple[DataFrame, list[str]]: ...
def cast_dataframe(df: DataFrame, schema: dict | None = None) -> CastingResult: ...  # 퍼사드
```

### mapping_profile.py
```python
def column_fingerprint(columns: list[str]) -> str: ...             # SHA-256 앞 12자
def save_profile(result: MappingResult, source_columns: list[str], **meta) -> Path: ...
def load_profile(source_columns: list[str]) -> MappingResult | None: ...
def list_profiles() -> list[dict]: ...                              # 최신 순
def delete_profile(fingerprint: str) -> bool: ...
```

</details>

---

## UX 1단계: 데이터 수집 투명성 (Phase 1a 구현 완료)

사용자가 데이터를 넣으면 AI가 자동 처리하고, 애매한 부분만 사용자에게 위임하며,
모든 판단 근거를 투명하게 노출하는 UX 모델. Phase 1c UI의 데이터 기반.

### 핵심 원칙

| 원칙                 | 구현                                                              |
|:---------------------|:------------------------------------------------------------------|
| 80/20 자동화         | 확신 높은 80%는 auto, 나머지 20%는 review로 분류                  |
| 블랙박스 공포증 해소 | ReviewItem에 reason(판단 근거) + confidence(신뢰도) 노출          |
| 3-tier 시각 피드백   | 확정(초록, auto) / 추천(노랑, review) / 차단(빨강, blocked)       |
| 구조적 판단          | 키워드 미등록 데이터도 타입 다양성/고유값/null 밀도로 헤더 판별   |
| 타입 안전            | fuzzy 매칭 후보의 소스↔스키마 타입 비호환 시 자동 차단            |

### ReviewItem 데이터 모델

```python
ReviewItem(column, action, confidence, reason, source_type?, target_type?)
# action: "auto" | "review" | "blocked" | "empty"
```

Phase 1c Streamlit UI 예시:
```
✅ 자동 매핑 (8개)           — action="auto"
   전표번호 → document_id     [정확 일치, 100%]

⚠️ 확인 필요 (2개)           — action="review"
   GL코드 → gl_account       [fuzzy 65%]  [확인] [변경]

🚫 차단됨 (1개)              — action="blocked"
   drcrk → debit_amount      [타입 비호환: str≠float]

📭 빈 컬럼 (3개 제외됨)      — empty_columns
```

### 구현 파일 맵

| 파일                    | UX 역할                                           |
|:------------------------|:--------------------------------------------------|
| `_header_scoring.py`    | 구조적 헤더 판별 — 키워드 없어도 동작             |
| `_type_compat.py`       | 타입 비호환 차단 — 오매핑 사전 방지               |
| `models.py:ReviewItem`  | 판단 근거 구조화 — Phase 1c UI 데이터 소스        |
| `models.py:CastingResult` | high_null/empty 분류 — 오매핑 사후 감지         |
| `text_reader.py`        | ascii→latin-1 폴백 — 인코딩 에러 없는 읽기       |

---

## Phase 1c 설계 메모: UI 상호작용 상태

Ingest 파이프라인이 UI와 연동될 때 필요한 상태 관리 개념.

### IngestState (상태 코드)

```python
class IngestState(str, Enum):
    COMPLETED    = "completed"     # 전체 자동 처리 완료
    NEEDS_REVIEW = "needs_review"  # 매핑 확인/중복 헤더 등 사용자 개입 필요
    FAILED       = "failed"        # 파일 검증 실패 등 복구 불가
```

### 상태별 흐름

- **COMPLETED**: fast path (DataSynth CSV 등) → 바로 feature 모듈로 전달
- **NEEDS_REVIEW**: 임시 세션에 중간 결과 저장 → UI에서 사용자 확인 → 재개
  - `needs_review=True` 트리거: suggestions 존재, missing_required, 중복 헤더 감지
- **FAILED**: 에러 메시지 표시 → 다른 파일 업로드 유도

> Phase 1c 구현 시 구체화 예정. 현재는 개념 정의만 기록.
