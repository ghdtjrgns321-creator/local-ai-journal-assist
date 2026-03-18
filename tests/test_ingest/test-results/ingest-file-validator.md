# File Validator 테스트 결과

> 실행일: 2026-03-18 | Python 3.11.14 | pytest 9.0.2 | **32 passed** in 0.46s

## 요약

| 구분                     | 테스트 수 | 결과          |
|:-------------------------|:---------:|:-------------:|
| 확장자 분류              |    15     | 15 passed     |
| 경로 검증                |     2     | 2 passed      |
| 확장자 검증              |     3     | 3 passed      |
| 빈 파일                  |     1     | 1 passed      |
| 크기 검증                |     2     | 2 passed      |
| 무결성 검증              |     7     | 7 passed      |
| ValidationResult 출력    |     2     | 2 passed      |
| **합계**                 |   **32**  | **32 passed** |

## 상세 테스트 케이스

### TestClassifyExtension — 확장자 → 카테고리 분류

| #  | 테스트명                        | 시나리오                            | 검증 포인트                    | 결과 |
|:---|:-------------------------------|:-----------------------------------|:------------------------------|:----:|
| 1  | test_supported_extensions[.xlsx] | xlsx → excel 카테고리              | category.name == "excel"       | PASS |
| 2  | test_supported_extensions[.xls]  | xls → excel 카테고리              | category.name == "excel"       | PASS |
| 3  | test_supported_extensions[.xlsb] | xlsb → excel 카테고리             | category.name == "excel"       | PASS |
| 4  | test_supported_extensions[.csv]  | csv → text 카테고리               | category.name == "text"        | PASS |
| 5  | test_supported_extensions[.tsv]  | tsv → text 카테고리               | category.name == "text"        | PASS |
| 6  | test_supported_extensions[.txt]  | txt → text 카테고리               | category.name == "text"        | PASS |
| 7  | test_supported_extensions[.dat]  | dat → text 카테고리               | category.name == "text"        | PASS |
| 8  | test_supported_extensions[.parquet] | parquet → columnar 카테고리    | category.name == "columnar"    | PASS |
| 9  | test_unknown_extensions[.json]   | json → None                       | classify_extension == None     | PASS |
| 10 | test_unknown_extensions[.xml]    | xml → None                        | classify_extension == None     | PASS |
| 11 | test_unknown_extensions[.zip]    | zip → None                        | classify_extension == None     | PASS |
| 12 | test_unknown_extensions[.docx]   | docx → None                       | classify_extension == None     | PASS |
| 13 | test_case_insensitive            | .XLSX → excel (대소문자 무관)      | 대문자 확장자 정상 분류         | PASS |
| 14 | test_all_categories_have_max_size | 모든 카테고리에 크기 제한 존재    | max_size_mb > 0                | PASS |
| 15 | test_category_size_limits        | 카테고리별 크기 제한 정확성        | excel=100, text=500, col=1000  | PASS |

### TestPathValidation — 경로 검증 (1단계)

| #  | 테스트명          | 시나리오         | 검증 포인트                 | 결과 |
|:---|:-----------------|:----------------|:---------------------------|:----:|
| 16 | test_file_not_found | 존재하지 않는 파일 | is_valid=False, error 포함 | PASS |
| 17 | test_directory_path | 디렉토리 경로    | is_valid=False, error 포함 | PASS |

### TestExtensionValidation — 확장자 검증 (2단계)

| #  | 테스트명               | 시나리오              | 검증 포인트                             | 결과 |
|:---|:----------------------|:---------------------|:---------------------------------------|:----:|
| 18 | test_unknown_extension | 미지원 확장자 (.json) | is_valid=False, "지원하지 않는" 메시지  | PASS |
| 19 | test_unsupported_pdf   | PDF 거부             | is_valid=False, "unsupported" 사유 안내 | PASS |
| 20 | test_unsupported_hwp   | HWP 거부             | is_valid=False, "unsupported" 사유 안내 | PASS |

### TestEmptyFile — 빈 파일 검증 (3단계)

| #  | 테스트명        | 시나리오    | 검증 포인트                | 결과 |
|:---|:---------------|:-----------|:--------------------------|:----:|
| 21 | test_empty_file | 0바이트 파일 | is_valid=False, error 포함 | PASS |

### TestSizeValidation — 크기 검증 (4단계)

| #  | 테스트명                      | 시나리오                  | 검증 포인트                 | 결과 |
|:---|:-----------------------------|:-------------------------|:---------------------------|:----:|
| 22 | test_excel_size_exceeds_limit | excel 100MB 초과         | is_valid=False, error 포함  | PASS |
| 23 | test_size_warning_at_80_percent | excel 80% 이상 크기    | is_valid=True, warning 포함 | PASS |

### TestIntegrityValidation — 무결성 검증 (5단계)

| #  | 테스트명                      | 시나리오                  | 검증 포인트                  | 결과 |
|:---|:-----------------------------|:-------------------------|:----------------------------|:----:|
| 24 | test_valid_xlsx               | 정상 xlsx                | is_valid=True, errors=[]     | PASS |
| 25 | test_valid_csv                | 정상 UTF-8 csv           | is_valid=True, errors=[]     | PASS |
| 26 | test_valid_tsv                | 정상 tsv                 | is_valid=True, errors=[]     | PASS |
| 27 | test_valid_parquet            | 정상 parquet             | is_valid=True, errors=[]     | PASS |
| 28 | test_corrupted_xlsx           | 손상된 xlsx              | is_valid=False, error 포함   | PASS |
| 29 | test_csv_cp949_encoding_warning | CP949 인코딩 csv       | is_valid=True, warning 포함  | PASS |
| 30 | test_corrupted_parquet        | 손상된 parquet           | is_valid=False, error 포함   | PASS |

### TestValidationResultStr — 결과 문자열 출력

| #  | 테스트명         | 시나리오        | 검증 포인트            | 결과 |
|:---|:----------------|:---------------|:----------------------|:----:|
| 31 | test_pass_result | PASS 결과 표시  | str에 "PASS" 포함      | PASS |
| 32 | test_fail_result | FAIL 결과 표시  | str에 "FAIL" + 사유 포함 | PASS |

## 소스 바로가기

| 구분               | 경로                                                                 |
|:-------------------|:--------------------------------------------------------------------|
| 테스트 코드         | [test_file_validator.py](../test_file_validator.py)                 |
| 테스트 fixture      | [conftest.py](../conftest.py)                                      |
| 구현: 검증 퍼사드   | [file_validator.py](../../../src/ingest/file_validator.py)          |
| 구현: 카테고리 분류 | [file_categories.py](../../../src/ingest/file_categories.py)        |
| 구현: 무결성 체커   | [integrity_checkers.py](../../../src/ingest/integrity_checkers.py)  |

## 실행 명령어

```bash
uv run pytest tests/test_ingest/test_file_validator.py -v
uv run pytest tests/test_ingest/test_file_validator.py::TestIntegrityValidation -v
```
