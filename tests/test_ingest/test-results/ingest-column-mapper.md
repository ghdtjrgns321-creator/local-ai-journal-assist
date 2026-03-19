# 컬럼 자동 매핑 (column_mapper) 테스트 결과

> 실행일: 2026-03-19
> 명령어: `uv run pytest tests/test_ingest/test_column_mapper.py -v`

## 결과: 25 passed

| #  | 그룹                | 테스트                                | 결과 |
|----|---------------------|---------------------------------------|------|
| 1  | prepare_dataframe   | row=0 추출                            | PASS |
| 2  | prepare_dataframe   | row=2 추출                            | PASS |
| 3  | prepare_dataframe   | NaN 컬럼 필터링                       | PASS |
| 4  | fast path           | DataSynth 표준 컬럼 → True            | PASS |
| 5  | fast path           | ERP 한글 → False (exact match 경로)   | PASS |
| 6  | exact match         | 한글 별칭 정확 일치                    | PASS |
| 7  | exact match         | SAP 코드 정확 일치                    | PASS |
| 8  | exact match         | matched_keywords 활용                 | PASS |
| 9  | fuzzy match         | 유사 별칭 (높은 스코어)               | PASS |
| 10 | fuzzy match         | 전혀 다른 컬럼명 (낮은 스코어)        | PASS |
| 11 | fuzzy match         | 부분 매칭                             | PASS |
| 12 | 충돌 해결           | 두 원본 → 같은 표준 (greedy)          | PASS |
| 13 | 충돌 해결           | threshold 경계값 3-tier               | PASS |
| 14 | auto_map (통합)     | 한글 별칭 전체 매핑                   | PASS |
| 15 | auto_map (통합)     | 혼합 컬럼                             | PASS |
| 16 | auto_map (통합)     | 필수 컬럼 누락 감지                   | PASS |
| 17 | auto_map (통합)     | fast path 동일 매핑                   | PASS |
| 18 | auto_map (통합)     | 빈 리스트                             | PASS |
| 19 | map_columns 퍼사드  | CSV 단일시트                          | PASS |
| 20 | map_columns 퍼사드  | 멀티시트 + 헤더 실패                  | PASS |
| 21 | _build_alias_map    | 기본 매핑 생성                        | PASS |
| 22 | _build_alias_map    | 대소문자 무관                         | PASS |
| 23 | _get_required       | 필수 9개 추출                         | PASS |
| 24 | _is_standard_schema | 필수 포함 → True                      | PASS |
| 25 | _is_standard_schema | 필수 누락 → False                     | PASS |

## 전체 ingest 회귀: 93 passed (기존 68 + 신규 25)
