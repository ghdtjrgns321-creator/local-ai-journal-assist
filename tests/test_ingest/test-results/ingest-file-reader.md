# File Reader 테스트 결과

> 실행일: 2026-03-18 | Python 3.11.14 | pytest 9.0.2 | **24 passed** in 0.62s

## 요약

| 모듈           | 테스트 수 | 결과          |
|:---------------|:---------:|:-------------:|
| excel_reader   |     8     | 8 passed      |
| text_reader    |     7     | 7 passed      |
| parquet_reader |     3     | 3 passed      |
| reader_api     |     6     | 6 passed      |
| **합계**       |   **24**  | **24 passed** |

## 상세 테스트 케이스

### test_excel_reader.py — Excel 읽기

#### TestReadXlsx — 기본 읽기

| #  | 테스트명           | 시나리오                  | 검증 포인트                           | 결과 |
|:---|:------------------|:-------------------------|:-------------------------------------|:----:|
| 1  | test_single_sheet  | 단일 시트 xlsx           | sheets=1, raw_data 행/열 수 정확      | PASS |
| 2  | test_multi_sheet   | 3시트 xlsx (데이터2+빈1) | sheets=3, 각 시트 DataFrame 존재      | PASS |
| 3  | test_source_format | source_format 확인       | source_format == "xlsx"               | PASS |
| 4  | test_encoding_is_none | Excel에는 인코딩 없음 | encoding == None                      | PASS |

#### TestMergedCells — 병합셀 처리

| #  | 테스트명                      | 시나리오                      | 검증 포인트                              | 결과 |
|:---|:-----------------------------|:-----------------------------|:----------------------------------------|:----:|
| 5  | test_horizontal_merge         | 가로 병합 (A1:B1)            | 병합 해제 후 양쪽 셀에 동일 값 복제       | PASS |
| 6  | test_vertical_merge           | 세로 병합 (A3:A4)            | 병합 해제 후 위아래 셀에 동일 값 복제     | PASS |
| 7  | test_non_merged_cells_preserved | 비병합 셀 보존 확인         | 병합 처리가 다른 셀에 영향 없음           | PASS |

#### TestUnsupportedExtension — 미지원 확장자

| #  | 테스트명              | 시나리오       | 검증 포인트          | 결과 |
|:---|:---------------------|:-------------|:--------------------|:----:|
| 8  | test_raises_value_error | 미지원 확장자 | ValueError 발생 확인 | PASS |

### test_text_reader.py — 텍스트(CSV/TSV) 읽기

#### TestReadCsv — 기본 읽기

| #  | 테스트명        | 시나리오            | 검증 포인트                    | 결과 |
|:---|:---------------|:-------------------|:------------------------------|:----:|
| 9  | test_utf8_csv   | UTF-8 CSV          | sheets=["Sheet1"], 행 수 정확  | PASS |
| 10 | test_dtype_is_str | dtype=str 강제   | 모든 셀이 문자열 타입           | PASS |

#### TestEncoding — 인코딩 감지

| #  | 테스트명               | 시나리오              | 검증 포인트                        | 결과 |
|:---|:----------------------|:---------------------|:----------------------------------|:----:|
| 11 | test_cp949_csv         | CP949 인코딩 파일     | 한글 정상 읽기, encoding="cp949"   | PASS |
| 12 | test_bom_csv           | UTF-8-BOM 파일       | BOM 제거 후 정상 읽기              | PASS |
| 13 | test_encoding_in_result | encoding 필드 확인  | result.encoding에 감지 결과 저장   | PASS |

#### TestSeparatorDetection — 구분자 자동 감지

| #  | 테스트명            | 시나리오         | 검증 포인트                  | 결과 |
|:---|:-------------------|:----------------|:----------------------------|:----:|
| 14 | test_tsv_separator  | TSV 탭 구분자    | 탭으로 분리된 컬럼 정상 파싱  | PASS |
| 15 | test_tsv_source_format | source_format | source_format == "tsv"       | PASS |

### test_parquet_reader.py — Parquet 읽기

| #  | 테스트명               | 시나리오        | 검증 포인트                    | 결과 |
|:---|:----------------------|:---------------|:------------------------------|:----:|
| 16 | test_basic_read        | 기본 parquet    | sheets=["Sheet1"], 행 수 정확  | PASS |
| 17 | test_type_preservation | 타입 보존       | int/float 원본 타입 유지       | PASS |
| 18 | test_normalized_sheets | 시트 정규화     | sheets=["Sheet1"]로 통일       | PASS |

### test_reader_api.py — 퍼사드 디스패치

#### TestDispatch — 확장자별 디스패치

| #  | 테스트명              | 시나리오         | 검증 포인트                       | 결과 |
|:---|:---------------------|:----------------|:---------------------------------|:----:|
| 19 | test_dispatch_xlsx    | xlsx 디스패치    | excel_reader로 정상 라우팅         | PASS |
| 20 | test_dispatch_csv     | csv 디스패치     | text_reader로 정상 라우팅          | PASS |
| 21 | test_dispatch_tsv     | tsv 디스패치     | text_reader로 정상 라우팅          | PASS |
| 22 | test_dispatch_parquet | parquet 디스패치 | parquet_reader로 정상 라우팅       | PASS |
| 23 | test_dispatch_str_path | str 경로 지원   | Path 외 str 경로도 정상 처리       | PASS |

#### TestUnsupported — 미지원 확장자

| #  | 테스트명                        | 시나리오       | 검증 포인트          | 결과 |
|:---|:-------------------------------|:-------------|:--------------------|:----:|
| 24 | test_unsupported_raises_value_error | 미지원 확장자 | ValueError 발생 확인 | PASS |

## 소스 바로가기

| 구분              | 경로                                                            |
|:-----------------|:---------------------------------------------------------------|
| excel_reader 테스트 | [test_excel_reader.py](../test_excel_reader.py)               |
| text_reader 테스트  | [test_text_reader.py](../test_text_reader.py)                 |
| parquet_reader 테스트 | [test_parquet_reader.py](../test_parquet_reader.py)         |
| reader_api 테스트   | [test_reader_api.py](../test_reader_api.py)                   |
| 테스트 fixture      | [conftest.py](../conftest.py)                                 |
| 구현: models        | [models.py](../../../src/ingest/models.py)                    |
| 구현: excel_reader  | [excel_reader.py](../../../src/ingest/excel_reader.py)        |
| 구현: text_reader   | [text_reader.py](../../../src/ingest/text_reader.py)          |
| 구현: parquet_reader | [parquet_reader.py](../../../src/ingest/parquet_reader.py)   |
| 구현: reader_api    | [reader_api.py](../../../src/ingest/reader_api.py)            |

## 실행 명령어

```bash
# 전체 리더 테스트
uv run pytest tests/test_ingest/test_excel_reader.py tests/test_ingest/test_text_reader.py tests/test_ingest/test_parquet_reader.py tests/test_ingest/test_reader_api.py -v

# 개별 모듈
uv run pytest tests/test_ingest/test_excel_reader.py -v
uv run pytest tests/test_ingest/test_text_reader.py -v
uv run pytest tests/test_ingest/test_reader_api.py -v
```
