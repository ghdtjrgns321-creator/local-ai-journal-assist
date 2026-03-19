# Type Caster 테스트 결과

> 실행일: 2026-03-19 | 39 passed in 0.26s

## 테스트 요약

| 클래스                 | 테스트 수 | 상태 |
|:-----------------------|:---------:|:----:|
| TestCastAmount         |     9     |  ✅  |
| TestCastDate           |     8     |  ✅  |
| TestCastInt            |     4     |  ✅  |
| TestCastStr            |     5     |  ✅  |
| TestCastBool           |     3     |  ✅  |
| TestUnifyDebitCredit   |     4     |  ✅  |
| TestCastDataframe      |     6     |  ✅  |
| **합계**               |  **39**   |  ✅  |

## 상세

### TestCastAmount (9)
- `test_comma_separated` — 쉼표 구분 금액 ("1,234,567" → 1234567.0)
- `test_won_symbol` — 원화 기호 ("₩10,000", "1000원")
- `test_dollar_symbol` — 달러 기호 ("$5,000.50")
- `test_parenthesis_negative` — 괄호 음수 ("(1,234)" → -1234.0)
- `test_empty_and_dash` — 빈값/대시 → NaN
- `test_none_and_nan` — None/NaN/문자열 nan → NaN
- `test_zero` — "0", "0.0", "0.00" → 0.0
- `test_plain_number` — 일반 숫자 문자열
- `test_already_numeric` — int64 → float64 fast path

### TestCastDate (8)
- `test_iso` — "2025-01-15" ISO 형식
- `test_slash` — "2025/01/15" 슬래시 형식
- `test_dot` — "2025.01.15" 점 형식
- `test_compact_yyyymmdd` — "20250115" 8자리
- `test_korean` — "2025년 1월 5일" 한국어
- `test_excel_serial` — 45678 Excel serial number
- `test_empty_and_none` — 빈값/None → NaT
- `test_already_datetime` — datetime → 스킵

### TestCastStr (5)
- `test_int_to_str` — Excel int64 계정코드 → str 변환
- `test_float_to_str` — float64 → str (소수점 유지)
- `test_already_str` — object dtype → strip만 적용
- `test_nan_preserved` — NaN 혼합 Series → pd.NA 보존
- `test_nan_preserved_pure_int` — Int64(nullable) → NaN은 pd.NA

### TestCastInt (4)
- `test_string_to_int64` — "2025" → Int64
- `test_float_string` — "2025.0" → Int64 (반올림)
- `test_nan` — None/빈값 → NA
- `test_already_int` — int64 → Int64 nullable

### TestCastBool (3)
- `test_true_variants` — true/1/yes/Y/t
- `test_false_variants` — false/0/no/N/f
- `test_nan` — None/빈값 → NA

### TestUnifyDebitCredit (4)
- `test_case_a_already_split` — debit/credit 이미 존재 → 통과
- `test_case_b_dc_indicator` — amount + D/C indicator → 분리
- `test_case_c_sign_based` — 양수=차변, 음수=대변
- `test_no_amount_column` — amount 없음 → warning

### TestCastDataframe (6)
- `test_full_casting` — object → float/datetime/Int64 전체 변환
- `test_parquet_skip` — 이미 올바른 dtype → skipped_columns
- `test_missing_required_error` — 필수 컬럼 NaN → warning
- `test_partial_nan_warning` — 결측률 50% → 임계 초과 warning
- `test_empty_dataframe` — 빈 DF → 에러 없이 통과
- `test_unify_called_when_amount_exists` — amount만 → debit/credit 자동 생성
