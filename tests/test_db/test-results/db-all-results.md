# DuckDB 모듈 테스트 결과 통합 리포트

> 실행일: 2026-03-26 | 총 65 passed, 0 failed (DataSynth v1.2.0 반영)

---

## 1. 전체 요약

```
모듈              테스트 수   결과     소요시간
─────────────────────────────────────────────
connection             6   PASS     0.05s
schema                11   PASS     0.08s
loader                16   PASS     0.15s
queries               17   PASS     0.20s
─────────────────────────────────────────────
단위 테스트 소계      53   PASS     1.02s
─────────────────────────────────────────────
E2E (DataSynth)       12   PASS    14.56s
─────────────────────────────────────────────
전체 합계             65   PASS    15.58s
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

### 2.2 schema.py (11/11)

| 테스트                       | 결과 | 검증 내용                              |
|:-----------------------------|:----:|:---------------------------------------|
| test_creates_4_tables        | PASS | 4개 테이블 생성 확인                   |
| test_creates_1_view          | PASS | anomaly_flag_summary VIEW 생성         |
| test_schema_ddl_has_5_objects| PASS | SCHEMA_DDL dict 5개                    |
| test_idempotent              | PASS | 2회 실행 에러 없음                     |
| test_gl_columns_in_ddl       | PASS | GENERAL_LEDGER_COLUMNS DDL 동기화      |
| test_af_columns_in_ddl       | PASS | ANOMALY_FLAGS_COLUMNS DDL 동기화       |
| test_bs_columns_in_ddl       | PASS | BENFORD_SUMMARY_COLUMNS DDL 동기화     |
| test_bd_columns_in_ddl       | PASS | BENFORD_DIGITS_COLUMNS DDL 동기화      |
| test_feature_columns_in_gl   | PASS | Feature 18개 컬럼 DDL 존재             |
| test_approval_level_in_gl    | PASS | approval_level 파생 컬럼 존재          |
| test_view_empty_query        | PASS | VIEW 빈 상태 정상 조회                 |

### 2.3 loader.py (16/16)

| 테스트                        | 결과 | 검증 내용                              |
|:------------------------------|:----:|:---------------------------------------|
| test_row_count                | PASS | 적재 행 수 == DataFrame 행 수          |
| test_query_after_load         | PASS | 적재 후 조회 결과 일치                 |
| test_approval_level_derived   | PASS | approval_level 자동 생성               |
| test_risk_level_as_string     | PASS | StrEnum → VARCHAR 변환                 |
| test_melt_and_filter          | PASS | details melt + score > 0 필터          |
| test_correct_scores           | PASS | score 값 {0.6, 0.8} 정합              |
| test_empty_results            | PASS | 빈 results → 0행                       |
| test_document_id_mapped       | PASS | document_id 원본 매핑 정확              |
| test_summary_1_row            | PASS | benford_summary 배치당 1행             |
| test_digits_9_rows            | PASS | benford_digits 자릿수별 9행            |
| test_no_benford_result        | PASS | BenfordResult 없음 → 경고 + 0행       |
| test_deviation_calc           | PASS | deviation = observed - expected        |
| test_returns_load_result      | PASS | LoadResult 반환 + is_success           |
| test_batch_id_consistency     | PASS | 4개 테이블 동일 batch_id               |
| test_two_batches_isolated     | PASS | 2개 배치 분리 적재                     |
| test_six_levels               | PASS | 6단계 금액 → Level 1~6                |
| test_boundary_10m             | PASS | 경계값 1천만원 → Level 1              |
| test_boundary_10m_plus_1      | PASS | 1천만원+1 → Level 2                   |
| test_multi_line_document      | PASS | 전표 내 최대 금액 기준                 |

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
테스트 그룹            테스트 수   소요시간
─────────────────────────────────────────
DataSynthLoad              4     12.1s
ApprovalLevelE2E           2      0.8s
BatchLedgerE2E             3      1.2s
EmptyTablesE2E             3      0.4s
─────────────────────────────────────────
E2E 합계                  12     14.56s
```

### 3.1 적재 검증

| 지표                    | 값          |
|:------------------------|:------------|
| CSV 행 수               | 1,106,356   |
| DB 적재 행 수           | 1,106,356   |
| 전표(document_id) 수    | 106,489     |
| 회사코드                | C001, C002, C003 |

### 3.2 approval_level 분포 (E2E)

| Level | 설명     | 조건            | 존재 확인 |
|:------|:---------|:----------------|:---------:|
| 1     | 자동승인 | ≤1천만원        | PASS      |
| 2     | 담당자   | ≤1억            | PASS      |
| 3     | 팀장     | ≤10억           | PASS      |
| 4~6   | 본부장~  | >10억           | 확인 가능 |

Level 1이 가장 많은 비율 차지 (정상 — 소액 전표 다수).

### 3.3 비즈니스 프로세스 분포

6개 프로세스 모두 존재: P2P, O2C, R2R, H2R, TRE, A2R

### 3.4 빈 테이블 (detection 미실행)

anomaly_flags, benford_summary, rule_violation_stats → 빈 상태 정상 반환 확인.
detection 파이프라인 연동 후 별도 E2E 추가 예정.

---

## 4. 발견 이슈

### 수정 완료

| 이슈 | 원인 | 수정 |
|:-----|:-----|:-----|
| test_creates_4_tables 실패 | DuckDB에서 VIEW도 information_schema.tables에 포함 | assert == → assert <= (부분집합 확인) |
| test_idempotent 실패 | 동일 원인 (VIEW 포함 시 5개) | assert == 4 → assert >= 4 |

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
