# feature/engine.py 테스트 결과

## 요약

| 항목           | 값                      |
|:---------------|:------------------------|
| 테스트 파일    | test_engine.py          |
| 테스트 수      | 14                      |
| 통과           | 14/14                   |
| 회귀 테스트    | 170/170 (전체 feature)  |
| 소요 시간      | 0.64s (엔진만) / 0.80s (전체) |

## 테스트 구성

| 클래스                   | 테스트                             | 검증 내용                         |
|:-------------------------|:-----------------------------------|:---------------------------------|
| TestGenerateAllFeatures  | test_all_18_columns_present        | 풀 스펙 df -> 18개 컬럼 생성     |
|                          | test_feature_result_metadata       | FeatureResult 메타데이터 정합성  |
|                          | test_column_dtypes                 | bool/float/Int64/str dtype 검증  |
| TestSelectiveCategories  | test_time_only                     | 6개만 추가, 나머지 없음          |
|                          | test_amount_and_pattern            | 10개만 추가                       |
|                          | test_order_preserved               | 역순 입력 -> 고정 순서 실행      |
| TestIdempotency          | test_run_twice_no_duplicate        | 2회 실행 컬럼 수 동일            |
|                          | test_run_twice_metadata_consistent | 2회째 added_columns=18 유지      |
| TestGracefulDegradation  | test_minimal_df                    | 최소 컬럼 에러 없이 완료         |
|                          | test_empty_df                      | 0행 정상 반환                     |
|                          | test_missing_columns_logged        | 누락 컬럼 메타데이터 표시        |
| TestSettingsInjection    | test_custom_settings               | threshold 변경 결과 반영          |
|                          | test_custom_rules                  | manual_codes 변경 결과 반영      |
|                          | test_auto_load                     | None 전달시 자동 로드            |

## 핵심 설계 결정

- **added_columns**: df에 존재하는 피처 컬럼 전체 (diff 아님) -> 2회 실행해도 "18개 있음" 명확
- **In-place 수정**: df.copy() 안함 -> 메모리 최적화 우선
- **고정 실행 순서**: time -> amount -> pattern -> text (입력 순서 무관)
- **execution_times**: 카테고리별 소요 시간 dict -> Phase 2/3 병목 추적 대비

## 개선 방안

- Phase 2: 병렬 실행 옵션 (concurrent.futures) — 현재는 의존성 없지만 순차 실행
- ~~Phase 2: FeatureResult에 경고/스킵 사유 상세 로그 추가~~ → ✅ **해결됨** — `warnings: dict[str, list[str]]` 필드 추가 + `_run_category`에서 수집
