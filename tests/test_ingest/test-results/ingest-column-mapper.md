# Column Mapper 테스트 결과

> 실행일: 2026-03-20 | **38 passed** in 0.21s

## 1. 테스트 요약

| 구분                    | 테스트 수 | 결과     |
|:------------------------|:---------:|:--------:|
| 기존 (v1)               |    25     | 25 passed |
| 타입 추론 (v2)          |     5     | 5 passed |
| 타입 호환성 검증 (v2)   |     6     | 6 passed |
| ReviewItem (v2)         |     2     | 2 passed |
| **합계**                |  **38**   | **38 passed** |

---

## 2. v1 문제점

**Fuzzy 매칭이 문자열 유사도만 사용** → 데이터 타입을 무시하여 오매핑 발생.

| 데이터셋       | 오매핑                    | 원인                               | 결과               |
|:---------------|:--------------------------|:-----------------------------------|:-------------------|
| sap-merged     | drcrk → debit_amount      | 'drcrk'와 'debit' 글자 유사        | 캐스팅 100% NaN    |
| sap-merged     | cpudt → credit_amount     | 날짜 컬럼인데 float 매핑           | 캐스팅 100% NaN    |
| financial-anomaly | AccountID → gl_account | str 컬럼인데 int 매핑              | 캐스팅 100% NaN    |

추가로 `dc_indicator` 표준 컬럼이 미등록 → drcrk/shkzg가 갈 곳 없음.

---

## 3. 개선방안

**3가지 방어선:**

| 방어선                | 동작                                                          |
|:----------------------|:--------------------------------------------------------------|
| C. dc_indicator 등록  | drcrk/shkzg → dc_indicator 정확 매칭 (1차 — 오매핑 원천 차단) |
| B1. 타입 호환성 검증  | fuzzy 후보의 소스 타입↔스키마 타입 비교 → 비호환 스코어 0     |
| D. ReviewItem 모델    | 매핑 판단 근거(action/confidence/reason) 구조화 → UI 투명성   |

**타입 호환 매트릭스:**
```
float ← {float, int, unknown}      str→float = 차단
date  ← {date, unknown}            str→date  = 차단
int   ← {int, float, unknown}      str→int   = 차단
str   ← {모든 타입}                unknown   = 모두 허용
```

---

## 4. v2 개선 결과

| 데이터셋          | v1                              | v2                                    | 상태 |
|:------------------|:--------------------------------|:--------------------------------------|:----:|
| sap-merged        | drcrk→debit_amount (오매핑)     | drcrk→dc_indicator (정확 매칭)        | 해결 |
| sap-merged        | cpudt→credit_amount (추천)      | 타입 검증 차단 → unmapped             | 해결 |
| financial-anomaly | AccountID→gl_account (str→int)  | 타입 검증 차단 → unmapped             | 해결 |
| 전체              | 판단 근거 불투명                | ReviewItem으로 action/reason 노출     | 해결 |

---

## 5. 남은 문제점

| 문제                           | 현상                                 | 시점       |
|:-------------------------------|:-------------------------------------|:-----------|
| 일부 Fuzzy 추천 부정확         | monat→debit_amount, WAERS→header_text | Phase 1c~3 |
| 차단 vs 단순 unmapped 미구분   | ReviewItem에서 타입 차단 사유 미표시  | Phase 1c   |

---

## 6. 세부 테스트 케이스

### 기존 (25)

| #   | 그룹              | 테스트                          |
|-----|-------------------|---------------------------------|
| 1-3 | prepare_dataframe | row=0/row=2 추출, NaN 필터링    |
| 4-5 | fast path         | 표준 컬럼 → True, 한글 → False  |
| 6-8 | exact match       | 한글, SAP, matched_keywords     |
| 9-11 | fuzzy match      | 유사, 낮은 스코어, 부분 매칭    |
| 12-13 | 충돌 해결       | greedy 우선순위, threshold 경계 |
| 14-18 | auto_map 통합   | 한글 전체, 혼합, 누락, fast, 빈 |
| 19-20 | map_columns     | 단일시트, 멀티+실패             |
| 21-25 | 내부 헬퍼       | alias_map, required, standard   |

### 타입 추론 (5)

| #  | 테스트명             | 입력            | 기대 결과 |
|:---|:---------------------|:----------------|:----------|
| 26 | test_numeric_int     | ["1000","2000"] | "int"     |
| 27 | test_numeric_float   | ["1000.5"]      | "float"   |
| 28 | test_date_regex_fast | ["2025-01-01"]  | "date"    |
| 29 | test_string          | ["hello"]       | "str"     |
| 30 | test_all_nan         | [None, None]    | "unknown" |

### 타입 호환성 검증 (6)

| #  | 테스트명                        | 검증 포인트                    |
|:---|:--------------------------------|:-------------------------------|
| 31 | test_str_to_float_blocked       | str→float 차단                 |
| 32 | test_str_to_date_blocked        | str→date 차단                  |
| 33 | test_int_to_float_allowed       | int→float 허용                 |
| 34 | test_unknown_always_allowed     | unknown→모든 타입 허용         |
| 35 | test_fuzzy_blocks_mismatch      | drcrk(str)→debit(float) E2E   |
| 36 | test_dc_indicator_exact_match   | drcrk→dc_indicator 정확 매칭   |

### ReviewItem (2)

| #  | 테스트명                       | 검증 포인트                 |
|:---|:-------------------------------|:---------------------------|
| 37 | test_review_items_generated    | auto/review 항목 정상 생성 |
| 38 | test_review_items_with_data_df | source_type 정보 포함      |

---

## 7. 소스 바로가기

| 구현 코드    | [column_mapper.py](../../../src/ingest/column_mapper.py), [_type_compat.py](../../../src/ingest/_type_compat.py) |
|:------------|:------------|
| 테스트 코드  | [test_column_mapper.py](../test_column_mapper.py) |

```bash
uv run pytest tests/test_ingest/test_column_mapper.py -v
```
