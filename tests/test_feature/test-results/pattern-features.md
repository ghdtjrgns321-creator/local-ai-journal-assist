# pattern_features 단위 테스트 결과

> 실행일: 2026-03-20 | 42 passed, 0 failed | 0.19s

## 1. 테스트 요약

| 테스트 클래스              | 케이스 수 | 결과 | 검증 대상                         |
|:---------------------------|:---------:|:----:|:----------------------------------|
| TestAddIsManualJe          | 8         | ✅   | B08: 수기전표 코드 매칭, 대소문자 무시, 공백 trim, NaN/빈 코드 방어 |
| TestAddIsIntercompany      | 6         | ✅   | B10: gl_account prefix + company_code startswith OR 조합, NA 방어 |
| TestAddIsRevenueAccount    | 6         | ✅   | B01: 매출계정 prefix, 복수 prefix, 문자열 gl_account, NA 방어 |
| TestAddFirstDigit          | 11        | ✅   | C07: 양수/음수/소수/0원/NaN/과학표기법, credit>debit, dtype=Int64 |
| TestAddIsSuspenseAccount   | 8         | ✅   | B11/C06: line/header OR 조합, 정규식 키워드, 잘못된 regex 폴백, NaN 방어 |
| TestAddAllPatternFeatures  | 3         | ✅   | 5개 컬럼 생성, in-place 반환, 최소 DataFrame 에러 없음 |

---

## 2. 발견된 문제점

없음. 모든 케이스 정상 통과.

---

## 3. 주요 edge case 커버리지

| edge case                        | 테스트                         | 처리 방식                          |
|:---------------------------------|:-------------------------------|:-----------------------------------|
| source NaN                       | test_nan_source                | False (오탐 방지)                  |
| source 전부 NaN                  | test_all_nan_source            | 전부 False                         |
| source 컬럼 부재                 | test_missing_source_column     | 전부 False                         |
| manual_codes 빈 리스트           | test_empty_codes               | 전부 False                         |
| gl_account/company_code 모두 부재 | test_no_relevant_columns      | 전부 False                         |
| gl_account NA                    | test_gl_account_na (3곳)       | 매칭 안 됨 (정상)                  |
| 음수 금액                        | test_negative_amount           | abs() 후 첫 자리 추출              |
| 소수 0.005                       | test_decimal_leading_zero      | 첫 non-zero digit=5                |
| 과학표기법 1.5e-05               | test_scientific_notation       | str.extract로 안전 추출            |
| 0원 금액                         | test_zero_amount               | NaN (Benford 대상 외)              |
| 잘못된 정규식 키워드             | test_invalid_regex_fallback    | re.escape() 폴백 + warning         |
| 텍스트 NaN                       | test_nan_text_no_match         | na=False → 매칭 안 됨              |

---

## 4. 남은 문제점

| 문제                                    | 현상                                          | 해결 시점  |
|:----------------------------------------|:----------------------------------------------|:-----------|
| ~~is_suspense_account 대상 컬럼 제한~~  | ✅ **해결됨** — `_SUSPENSE_TEXT_COLS`에 `gl_account_name` 추가 (Phase 2 스키마 확장 시 자동 반영) | — |
| 은어/동의어 미탐지                      | 정확한 키워드/정규식에만 반응                  | Phase 2~3  |

---

## 5. 실행 명령어

```bash
uv run pytest tests/test_feature/test_pattern_features.py -v
```
