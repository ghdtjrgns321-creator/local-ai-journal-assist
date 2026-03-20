# time_features 단위 테스트 결과

> 실행일: 2026-03-20 | 49 passed, 0 failed | 0.46s

## 1. 테스트 요약

| 테스트 클래스              | 케이스 수 | 결과 | 검증 대상                         |
|:---------------------------|:---------:|:----:|:----------------------------------|
| TestBuildHolidaySet        | 3         | ✅   | 법정공휴일 포함, 커스텀 병합, 잘못된 날짜 스킵 |
| TestHasTimeInfo            | 4         | ✅   | 시간 정보 유무 판정 (시간 있음/없음/빈 Series/전부 NaT) |
| TestIsWeekend              | 4         | ✅   | 토/일 True, 평일 False, NaT 방어  |
| TestIsAfterHours           | 7         | ✅   | 심야(22~6시) 판정, 시간정보 없으면 False, start<end/start==end 분기 |
| TestIsPeriodEnd            | 9         | ✅   | 양방향 탐지(월말 전 + 익월 초), 윤년 2/29, margin=0, NaT 방어 |
| TestDaysBackdated          | 6         | ✅   | 부호 유지(+지연/-선전기), NaT→NaN, document_date 컬럼 부재, dtype=Int64 |
| TestFiscalPeriodMismatch   | 9         | ✅   | 표준(1월)/비표준(4월) 회계연도, modulo 연산, NaT/NaN→pd.NA, dtype=boolean |
| TestIsHoliday              | 5         | ✅   | 신정/삼일절 True, 평일 False, 커스텀 휴일 추가, NaT 방어 |
| TestAddAllTimeFeatures     | 2         | ✅   | 6개 컬럼 생성 확인, settings 커스텀 전달 |

---

## 2. 발견된 문제점

없음. 모든 케이스 정상 통과.

---

## 3. 주요 edge case 커버리지

| edge case                          | 테스트                              | 처리 방식                     |
|:-----------------------------------|:------------------------------------|:------------------------------|
| 시간 정보 없는 날짜(date only)     | test_no_time_info_all_false         | `_has_time_info()` 판정 → 전체 False + warning |
| NaT(결측 날짜)                     | test_nat_false 등 4개               | fillna(False) 또는 NaN 반환   |
| 윤년 2/29                          | test_leap_year_feb29                | 월말 당일 → True 정상 처리    |
| margin=0                           | test_margin_zero_only_month_end     | 월말 당일만 True, 익월 초 제외 |
| start==end(구간 없음)              | test_start_equals_end_all_false     | 전체 False (무한루프 방지)    |
| document_date 컬럼 부재            | test_no_document_date_column        | 전체 NaN + warning            |
| fiscal_period 컬럼 부재            | test_no_fiscal_period_column        | 전체 pd.NA                    |
| 비표준 회계연도(4월 결산)          | test_nonstandard_april_match 등 3개 | modulo 연산으로 범용 대응     |

---

## 4. 남은 문제점

| 문제                                | 현상                                   | 해결 시점  |
|:------------------------------------|:---------------------------------------|:-----------|
| ~~is_after_hours 날짜 경계~~        | ✅ **버그 아님** — `dt.hour` 기반으로 자정 걸침 정확히 처리 (23→True, 0→True). 시간정보 없는 데이터는 전체 False가 정상 동작. | —  |
| is_holiday 연도별 음력 공휴일       | holidays.KR 라이브러리 의존            | 현재 정상  |

---

## 5. 실행 명령어

```bash
uv run pytest tests/test_feature/test_time_features.py -v
```
