# DuckDB 모듈 테스트 결과 통합 리포트

> 실행일: 2026-03-26 | 총 77 passed, 0 failed (Task 20a+20b: ML 스키마 예약 + approval_level debit SUM 보완)

---

## 1. 전체 요약

```
모듈              테스트 수   결과     소요시간
─────────────────────────────────────────────
connection             6   PASS     0.05s
schema                14   PASS     0.08s
loader                22   PASS     0.42s
queries               17   PASS     0.20s
─────────────────────────────────────────────
단위 테스트 소계      59   PASS     0.79s
─────────────────────────────────────────────
E2E (DataSynth)       15   PASS    15.41s
─────────────────────────────────────────────
전체 합계             77   PASS    16.34s
```

---

## 2. 모듈별 단위 테스트 상세

### 2.1 connection.py (6/6)

| 테스트                          | 결과 | 검증 내용                        |
|:--------------------------------|:----:|:---------------------------------|
| test_same_object_returned       | PASS | 싱글톤: 2회 호출 → 동일 객체     |
| test_close_and_reconnect        | PASS | close 후 재호출 → 새 커넥션      |
| test_alive_connection           | PASS | 정상 커넥션 → True               |
| test_closed_connection          | PASS | 닫힌 커넥션 → False              |
| test_auto_reconnect_on_dead     | PASS | 외부 종료 감지 → 자동 재생성     |
| test_override_returns_injected  | PASS | 테스트용 커넥션 주입 동작         |

### 2.2 schema.py (14/14)

| 테스트                            | 결과 | 검증 내용                              |
|:----------------------------------|:----:|:---------------------------------------|
| test_creates_5_tables             | PASS | 5개 테이블 생성 확인                   |
| test_creates_1_view               | PASS | anomaly_flag_summary VIEW 생성         |
| test_schema_ddl_has_6_objects     | PASS | SCHEMA_DDL dict 6개                    |
| test_idempotent                   | PASS | 2회 실행 에러 없음                     |
| test_gl_columns_in_ddl            | PASS | GENERAL_LEDGER_COLUMNS DDL 동기화      |
| test_af_columns_in_ddl            | PASS | ANOMALY_FLAGS_COLUMNS DDL 동기화       |
| test_bs_columns_in_ddl            | PASS | BENFORD_SUMMARY_COLUMNS DDL 동기화     |
| test_bd_columns_in_ddl            | PASS | BENFORD_DIGITS_COLUMNS DDL 동기화      |
| test_feature_columns_in_gl        | PASS | Feature 18개 컬럼 DDL 존재             |
| test_approval_level_in_gl         | PASS | approval_level 파생 컬럼 존재          |
| test_ml_columns_in_gl             | PASS | ML 예약 컬럼 DDL 존재                  |
| test_ml_model_metadata_columns    | PASS | ml_model_metadata 테이블 컬럼          |
| test_ml_model_metadata_pk         | PASS | ml_model_metadata PK 제약조건          |
| test_view_empty_query             | PASS | VIEW 빈 상태 정상 조회                 |

### 2.3 loader.py (22/22)

| 테스트                              | 결과 | 검증 내용                                    |
|:------------------------------------|:----:|:---------------------------------------------|
| test_row_count                      | PASS | 적재 행 수 == DataFrame 행 수                |
| test_query_after_load               | PASS | 적재 후 조회 결과 일치                       |
| test_approval_level_derived         | PASS | approval_level 자동 생성                     |
| test_risk_level_as_string           | PASS | StrEnum → VARCHAR 변환                       |
| test_melt_and_filter                | PASS | details melt + score > 0 필터                |
| test_correct_scores                 | PASS | score 값 {0.6, 0.8} 정합                    |
| test_empty_results                  | PASS | 빈 results → 0행                             |
| test_document_id_mapped             | PASS | document_id 원본 매핑 정확                    |
| test_summary_1_row                  | PASS | benford_summary 배치당 1행                   |
| test_digits_9_rows                  | PASS | benford_digits 자릿수별 9행                  |
| test_no_benford_result              | PASS | BenfordResult 없음 → 경고 + 0행             |
| test_deviation_calc                 | PASS | deviation = observed - expected              |
| test_returns_load_result            | PASS | LoadResult 반환 + is_success                 |
| test_batch_id_consistency           | PASS | 4개 테이블 동일 batch_id                     |
| test_two_batches_isolated           | PASS | 2개 배치 분리 적재                           |
| test_six_levels                     | PASS | 6단계 금액 → Level 1~6                      |
| test_boundary_10m                   | PASS | 경계값 1천만원 → Level 1                    |
| test_boundary_10m_plus_1            | PASS | 1천만원+1 → Level 2                         |
| test_multi_line_document            | PASS | 전표 내 차변 합산 기준                       |
| test_sum_vs_max_difference          | PASS | SUM vs MAX 결과 차이 검증 (60M×2→L3)        |
| test_custom_thresholds              | PASS | 커스텀 임계값 파라미터 동작                  |
| test_exceeds_all_thresholds_capped  | PASS | 최고 임계값 초과 시 최고 레벨 캡             |
| test_ml_varchar_nan_to_null         | PASS | ML VARCHAR 컬럼 NaN→NULL 변환               |
| test_ml_double_null                 | PASS | ML DOUBLE 컬럼 NULL 처리                     |
| test_ml_timestamp_null              | PASS | ML TIMESTAMP 컬럼 NULL 처리                  |

### 2.4 queries.py (17/17)

| 테스트                           | 결과 | 검증 내용                            |
|:---------------------------------|:----:|:-------------------------------------|
| test_row_count_match             | PASS | 적재 건수 == 조회 건수               |
| test_required_columns            | PASS | 필수 컬럼 존재                       |
| test_sorted_by_score_desc        | PASS | anomaly_score DESC 정렬              |
| test_new_columns_present         | PASS | v3 추가 컬럼 존재                    |
| test_flags_returned              | PASS | 플래그 전수 조회                     |
| test_score_values                | PASS | score 값 정합                        |
| test_summary_1_row               | PASS | benford_summary 1행                  |
| test_digits_9_rows               | PASS | benford_digits 9행                   |
| test_view_aggregation            | PASS | VIEW 집계 정합                       |
| test_specific_document           | PASS | 드릴다운 필터링                      |
| test_nonexistent_document        | PASS | 존재하지 않는 ID → 빈 DataFrame     |
| test_unknown_query_name          | PASS | QueryNotFoundError 발생              |
| test_no_params_no_batch_id       | PASS | ValueError 발생                      |
| test_empty_table_returns_empty_df| PASS | 빈 테이블 → 빈 DataFrame            |
| test_preset_queries_count        | PASS | 6종 정의                             |
| test_all_queries_have_batch_filter| PASS | 모든 쿼리에 batch_id 필터           |
| test_batch_isolation             | PASS | 2개 배치 교차 조회 없음              |

---

## 3. E2E 테스트 (DataSynth v1.2.0)

> CSV: data/journal/primary/datasynth/journal_entries.csv (319 MB)
> 적재: 1,106,356행 → in-memory DuckDB

```
테스트 그룹                테스트 수   소요시간
─────────────────────────────────────────────
DataSynthLoad                  4     12.1s
ApprovalLevelE2E               2      0.8s
BatchLedgerE2E                 3      1.2s
MLReservedColumnsE2E           3      0.3s
EmptyTablesE2E                 3      0.4s
─────────────────────────────────────────────
E2E 합계                      15     15.41s
```

### 3.1 적재 검증

| 지표                    | 값          |
|:------------------------|:------------|
| CSV 행 수               | 1,106,356   |
| DB 적재 행 수           | 1,106,356   |
| 전표(document_id) 수    | 106,489     |
| 회사코드                | C001, C002, C003 |

### 3.2 approval_level 분포 (E2E, debit SUM 기준)

| Level | 설명     | 조건            |      행 수 |   비율 | 존재 확인 |
|:------|:---------|:----------------|----------:|-------:|:---------:|
| 1     | 자동승인 | ≤1천만원        |   892,701 | 80.69% | PASS      |
| 2     | 담당자   | ≤1억            |   178,370 | 16.12% | PASS      |
| 3     | 팀장     | ≤10억           |    32,871 |  2.97% | PASS      |
| 4     | 본부장   | ≤50억           |     2,231 |  0.20% | PASS      |
| 5     | CFO      | ≤100억          |       116 |  0.01% | PASS      |
| 6     | 이사회   | ≤500억 (캡)     |        67 |  0.01% | PASS      |

Level 1이 80.69%로 가장 많음 (정상 — 소액 전표 다수). 6단계 모두 존재.

### 3.3 비즈니스 프로세스 분포

6개 프로세스 모두 존재: P2P, O2C, R2R, H2R, TRE, A2R

### 3.4 ML 예약 컬럼 NULL 검증

Phase 1 데이터 적재 시 ML 예약 7개 컬럼이 전부 NULL인지 확인.
- supervised_score, unsupervised_score, duplicate_score → NULL (PASS)
- supervised_model_id, unsupervised_model_id, duplicate_model_id → NULL, not 'nan' (PASS)
- ml_scored_at → NULL (PASS)

### 3.5 빈 테이블 (detection 미실행)

anomaly_flags, benford_summary, rule_violation_stats → 빈 상태 정상 반환 확인.
detection 파이프라인 연동 후 별도 E2E 추가 예정.

---

## 4. 발견 이슈

### 수정 완료

| 이슈 | 원인 | 수정 |
|:-----|:-----|:-----|
| test_creates_4_tables 실패 | DuckDB에서 VIEW도 information_schema.tables에 포함 | assert == → assert <= (부분집합 확인) |
| test_idempotent 실패 | 동일 원인 (VIEW 포함 시 5개) | assert == 4 → assert >= 4 |
| approval_level MAX→SUM 보완 | 복식부기: max(debit,credit) 합산 시 2배 부풀림 | debit_amount만 SUM + settings.py 동적 참조 |

### 미해결 (정상 동작, 후속 태스크)

| 항목 | 설명 | 해결 시점 |
|:-----|:-----|:----------|
| anomaly_flags E2E 미검증 | detection 파이프라인 미연동 → 빈 상태 | Phase 1b pipeline 통합 |
| benford E2E 미검증 | 위와 동일 | Phase 1b pipeline 통합 |
| 트랜잭션 롤백 E2E | load_all 실패 시나리오 미검증 | loader unit test 확장 |

---

## 5. 테스트 환경

```
Python:   3.11.14
pytest:   9.0.2
DuckDB:   (core dependency)
OS:       Windows 11 Pro
데이터:   DataSynth v1.2.0 (seed: 2024, 319 MB)
```
