# Ingest 모듈 테스트 결과 통합

> 최종 갱신: 2026-03-25 | **240 tests passed** (단위 215 + DataSynth 통합 25) + **5 E2E validation datasets passed**

---

## 1. 전체 요약

```
모듈                    테스트   상태     핵심 기능
──────────────────────  ─────  ──────   ──────────────────────────────
File Validator             32   PASS    경로/확장자/크기/무결성 5단계 검증
File Reader                24   PASS    Excel/CSV/TSV/Parquet 읽기 + 인코딩 감지
Header Detector            20   PASS    구조 기반 헤더 행 탐지 (v2)
Column Mapper              38   PASS    Fuzzy 매핑 + 타입 호환성 검증 (v2)
Mapping Profile            26   PASS    매핑 결과 저장/로드/삭제
Type Caster                44   PASS    금액/날짜/정수/문자열/불린 캐스팅 (v2)
Sheet Scorer                8   PASS    멀티시트 품질 순위 매기기
Text Reader (추가)         12   PASS    인코딩 감지/오버라이드/구분자
DataSynth 통합             25   PASS    319MB CSV 39컬럼 E2E (v1.2.0)
──────────────────────  ─────  ──────
단위 테스트 합계          215   PASS
DataSynth 통합             25   PASS    39컬럼 매핑·캐스팅·데이터 품질
E2E Validation              6   PASS    5종 실데이터셋 + 리포트 생성
──────────────────────  ─────  ──────
총합                      240   PASS
```

---

## 2. v1→v2 주요 개선

3개 모듈에서 v2 개선이 이루어졌으며, 모두 테스트로 검증 완료.

### 2-1. Header Detector — 구조 기반 탐지

**문제:** 키워드 가중치 80% → 미등록 컬럼명이면 탐지 실패

```
v1: Confidence = KeywordScore × 0.80 + StringRatio × 0.20
v2: Confidence = TypeDiversity × 0.35 + Uniqueness × 0.25 + NullDensity × 0.15
                + KeywordScore × 0.15 + StringRatio × 0.10
```

```
데이터셋            v1 conf   v2 conf   상태
─────────────────   ───────   ───────   ────
financial-anomaly   0.20      0.85      해결
general-ledger      0.20      0.77      해결
비회계 파일         실패      성공      해결
```

### 2-2. Column Mapper — 타입 호환성 검증 + dc_indicator

**문제:** Fuzzy 매칭이 문자열 유사도만 사용 → 타입 불일치 오매핑 발생

```
방어선                동작
────────────────────  ──────────────────────────────────────────
dc_indicator 등록     drcrk/shkzg → dc_indicator 정확 매칭
타입 호환성 검증      소스↔스키마 타입 비호환 시 스코어 0
ReviewItem 모델       매핑 판단 근거(action/confidence/reason) 구조화
```

타입 호환 매트릭스:

```
float ← {float, int, unknown}     str→float = 차단
date  ← {date, unknown}           str→date  = 차단
int   ← {int, float, unknown}     str→int   = 차단
str   ← {모든 타입}               unknown   = 모두 허용
```

```
데이터셋            v1                          v2                           상태
────────────────    ─────────────────────────   ──────────────────────────   ────
sap-merged          drcrk→debit_amount (오매핑)  drcrk→dc_indicator (정확)   해결
sap-merged          cpudt→credit_amount         타입 검증 차단 → unmapped    해결
financial-anomaly   AccountID→gl_account        타입 검증 차단 → unmapped    해결
```

### 2-3. Type Caster — Null 3단계 분기

**문제:** 캐스팅 후 결측률 경고가 단일 기준 → 오매핑과 유령 컬럼 미구분

```
원본 100% NaN       → empty_columns     유령 컬럼 — 경고 없이 분리
캐스팅 후 >90% NaN  → high_null_columns 오매핑 의심 — 명시적 경고
캐스팅 후 >10% NaN  → warnings          일반 경고
```

---

## 3. E2E 데이터셋 검증

### 3-1. DataSynth v1.2.0 통합 검증 (25 tests)

DataSynth CSV (319MB, 39컬럼, 1,106,356 라인아이템)에 대한 전체 파이프라인 검증.

```
데이터셋            형식   크기    rows         cols  매핑  필수 미매핑
──────────────────  ─────  ──────  ───────────  ────  ────  ──────────
DataSynth v1.2.0    CSV    319MB   1,106,356     39    36    0
```

- **fast path 활성화**: 필수 10컬럼 정확 일치 → 매핑 스킵
- **비레이블 36컬럼 매핑**: bool 레이블(is_fraud, is_anomaly, sod_violation) 3개는 의도적 제외
- **타입 캐스팅 성공**: debit/credit→float64, posting_date→datetime64, fiscal_period→Int64, gl_account→str
- **데이터 품질 검증**: 3법인, 9+전표유형, 6프로세스, 5페르소나, 106,489전표, 2,008부정

### 3-2. 외부 Validation 데이터셋 (5종)

5종 실데이터셋에 대해 전체 파이프라인(검증→읽기→헤더→매핑→캐스팅) 통과.

```
데이터셋            형식      크기     rows        cols  매핑  필수 미매핑
─────────────────   ────────  ──────   ──────────  ────  ────  ──────────
bpi2019             CSV       527MB    1,595,923    22     3    8
financial-anomaly   CSV        15MB      217,441     7     1    8
general-ledger      XLSX        2MB       27,909     6     1    8
sap-merged          Parquet   8.5MB      331,934    60    14    2
schreyer-fraud      CSV        27MB      533,009    10     4    6
```

### 데이터셋별 비고

| 데이터셋          | 비고                                                        |
|:------------------|:------------------------------------------------------------|
| DataSynth v1.2.0  | 메인 데이터. 39컬럼 fast path 검증. 319MB 13초 처리          |
| bpi2019           | SAP P2P 이벤트 로그. latin-1 인코딩. 회계 전표가 아닌 프로세스 로그라 필수 미매핑 다수 |
| financial-anomaly | 금융 이상치 데이터. 범용 컬럼명(Amount, Merchant) → 매핑 한계 |
| general-ledger    | 교육용 총계정원장 6시트. GL 시트 자동 선택                    |
| sap-merged        | SAP FICO 60컬럼. 14개 확정 매핑 — 가장 높은 매핑률           |
| schreyer-fraud    | SAP 합성 벤치마크. HKONT(익명화 str)→gl_account 매핑        |

---

## 4. 남은 문제점

```
문제                     현상                               해결 시점
───────────────────────  ─────────────────────────────────  ──────────
일부 Fuzzy 추천 부정확   monat→debit_amount, WAERS→header_text  Phase 1c~3
차단 vs unmapped 미구분  ReviewItem에서 타입 차단 사유 미표시     Phase 1c
Parquet 헤더 탐지 스킵   불필요한 탐지 시도 (동작 무영향)        Phase 1c
멀티시트 UI 선택         active_sheet가 데이터 양 무관            Phase 1c
```

---

## 5. 모듈별 세부 테스트 케이스

### 5-1. File Validator (32 tests)

| 그룹                | 수  | 검증 포인트                                          |
|:--------------------|:---:|:-----------------------------------------------------|
| 확장자 분류          | 15  | xlsx/xls/xlsb→excel, csv/tsv/txt/dat→text, parquet→columnar, 미지원→None, 대소문자 무관 |
| 경로 검증            |  2  | 존재하지 않는 파일, 디렉토리 경로                    |
| 확장자 검증          |  3  | 미지원 확장자, PDF/HWP 거부                          |
| 빈 파일              |  1  | 0바이트 파일                                         |
| 크기 검증            |  2  | 100MB 초과 거부, 80% 이상 경고                       |
| 무결성 검증          |  7  | 정상 xlsx/csv/tsv/parquet, 손상 xlsx/parquet, CP949 경고 |
| 결과 출력            |  2  | PASS/FAIL 문자열 표시                                |

### 5-2. File Reader (24 tests)

| 그룹            | 수  | 검증 포인트                                          |
|:----------------|:---:|:-----------------------------------------------------|
| Excel 기본 읽기  |  4  | 단일/멀티 시트, source_format, encoding=None          |
| 병합셀 처리      |  3  | 가로/세로 병합 해제, 비병합 셀 보존                   |
| 미지원 확장자    |  1  | ValueError 발생                                      |
| CSV/TSV 읽기     |  7  | UTF-8, CP949, BOM, encoding 필드, TSV 탭 구분자      |
| Parquet 읽기     |  3  | 기본 읽기, 타입 보존, 시트 정규화                     |
| 퍼사드 디스패치  |  6  | xlsx/csv/tsv/parquet 라우팅, str 경로, 미지원 에러    |

### 5-3. Header Detector (20 tests)

| 그룹                | 수  | 검증 포인트                                          |
|:--------------------|:---:|:-----------------------------------------------------|
| 핵심 탐지 로직       |  8  | 표준/ERP/병합 헤더, 빈 DF, 비회계, 빈 컬럼 방어, 간섭, SAP i18n |
| 메시지 분기          |  3  | >=0.7 "완벽히 인식", 0.3~0.7 "확인", <0.3 "직접 지정" |
| 구조적 스코어링 (v2) |  8  | TypeDiversity/Uniqueness/NullDensity 개별 검증, 키워드 0개 탐지 |
| 멀티시트 퍼사드      |  1  | ReadResult 일괄 처리                                 |

### 5-4. Column Mapper (38 tests)

| 그룹                | 수  | 검증 포인트                                          |
|:--------------------|:---:|:-----------------------------------------------------|
| prepare_dataframe    |  3  | row=0/2 추출, NaN 필터링                             |
| fast path            |  2  | 표준 컬럼→True, 한글→False                           |
| exact match          |  3  | 한글, SAP, matched_keywords                          |
| fuzzy match          |  3  | 유사/낮은 스코어/부분 매칭                           |
| 충돌 해결            |  2  | greedy 우선순위, threshold 경계                      |
| auto_map 통합        |  5  | 한글 전체, 혼합, 누락, fast, 빈                      |
| map_columns          |  2  | 단일시트, 멀티+실패                                  |
| 내부 헬퍼            |  5  | alias_map, required, standard                        |
| 타입 추론 (v2)       |  5  | int/float/date/str/unknown 추론                      |
| 타입 호환성 (v2)     |  6  | str→float/date 차단, int→float 허용, unknown 허용, E2E |
| ReviewItem (v2)      |  2  | 항목 생성, source_type 포함                          |

### 5-5. Mapping Profile (26 tests)

| 그룹           | 수  | 검증 포인트                                          |
|:---------------|:---:|:-----------------------------------------------------|
| fingerprint     |  6  | 동일/다른 해시, 순서/대소문자/공백 무관, 길이 12자    |
| save_profile    |  5  | JSON 생성, 필수 필드, suggestions 미포함, 디렉토리 생성, created_at 유지 |
| mapping_log     |  3  | suggestions→로그 생성, unmapped 포함, 깨끗→미생성    |
| load_profile    |  5  | 왕복 일치, suggestions 빈 상태, None(없음/손상/누락)  |
| list_profiles   |  3  | 빈 리스트, 복수 목록, 메타데이터 필드                 |
| delete_profile  |  3  | 삭제 성공, 미존재→False, 관련 로그 삭제              |
| 통합            |  1  | save→load→list→delete 전체 워크플로우                 |

### 5-6. Type Caster (44 tests)

| 그룹              | 수  | 검증 포인트                                          |
|:------------------|:---:|:-----------------------------------------------------|
| CastAmount         |  9  | 쉼표, ₩, $, 괄호음수, 빈값/대시, None/NaN, 0, 일반, numeric |
| CastDate           |  8  | ISO, 슬래시, 점, 8자리, 한국어, Excel serial, 빈값, datetime |
| CastInt            |  4  | str→Int64, 소수점→반올림, NaN, 이미 int              |
| CastStr            |  5  | int/float/str→str, NaN→pd.NA, Int64→str              |
| CastBool           |  3  | true 변형, false 변형, NaN                           |
| UnifyDebitCredit   |  4  | 이미 분리, dc_indicator, 부호, amount 없음           |
| CastDataframe      |  6  | 전체/Parquet 스킵/필수 실패/결측 경고/빈 DF/debit-credit |
| NullDemote (v2)    |  5  | 유령 컬럼 분리, 오매핑 감지, 정상 미감지, 90% 경계, 분류 구분 |

### 5-7. DataSynth 통합 (25 tests)

| 그룹                 | 수  | 검증 포인트                                          |
|:---------------------|:---:|:-----------------------------------------------------|
| 파일 검증             |  1  | 319MB CSV 파일 검증 통과                              |
| 파일 읽기             |  3  | source_format=csv, 인코딩 감지, 1,106,356행           |
| 컬럼 매핑             |  5  | fast path 활성, 필수 미매핑 0, 비레이블 36개 매핑, 39컬럼 |
| 타입 캐스팅           |  8  | 성공, 에러 0, float64/datetime/bool/Int64/str 확인, 최종 shape |
| 데이터 품질           |  8  | 3법인, 9+전표유형, 6프로세스, 5페르소나, 106,489전표, 2,008부정, 2022년, KRW |

---

## 6. 소스 바로가기

```
구현 코드:
  src/ingest/file_validator.py      파일 검증 퍼사드
  src/ingest/file_categories.py     확장자 카테고리 분류
  src/ingest/integrity_checkers.py  무결성 체커
  src/ingest/excel_reader.py        Excel 읽기
  src/ingest/text_reader.py         CSV/TSV 읽기
  src/ingest/parquet_reader.py      Parquet 읽기
  src/ingest/reader_api.py          읽기 퍼사드
  src/ingest/header_detector.py     헤더 탐지
  src/ingest/_header_scoring.py     구조적 스코어링
  src/ingest/column_mapper.py       컬럼 매핑
  src/ingest/_type_compat.py        타입 호환성 검증
  src/ingest/mapping_profile.py     매핑 프로파일 CRUD
  src/ingest/type_caster.py         타입 캐스팅

테스트 코드:
  tests/test_ingest/test_file_validator.py
  tests/test_ingest/test_excel_reader.py
  tests/test_ingest/test_text_reader.py
  tests/test_ingest/test_parquet_reader.py
  tests/test_ingest/test_reader_api.py
  tests/test_ingest/test_header_detector.py
  tests/test_ingest/test_column_mapper.py
  tests/test_ingest/test_mapping_profile.py
  tests/test_ingest/test_type_caster.py
  tests/test_ingest/test_validation_datasets.py
  tests/test_ingest/test_datasynth_integration.py
```

## 7. 실행 명령어

```bash
# 전체 ingest 테스트
uv run pytest tests/test_ingest/ -v

# E2E 데이터셋 (bpi2019 제외 — 빠른 실행)
uv run pytest tests/test_ingest/test_validation_datasets.py -v -k 'not slow'

# 개별 모듈
uv run pytest tests/test_ingest/test_file_validator.py -v
uv run pytest tests/test_ingest/test_excel_reader.py tests/test_ingest/test_text_reader.py tests/test_ingest/test_parquet_reader.py tests/test_ingest/test_reader_api.py -v
uv run pytest tests/test_ingest/test_header_detector.py -v
uv run pytest tests/test_ingest/test_column_mapper.py -v
uv run pytest tests/test_ingest/test_mapping_profile.py -v
uv run pytest tests/test_ingest/test_type_caster.py -v
```
