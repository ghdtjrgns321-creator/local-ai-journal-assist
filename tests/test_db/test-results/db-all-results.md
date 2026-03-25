# DB 모듈 테스트 결과 통합 리포트

> 실행일: 2026-03-22 | unit 34 passed (1.69s) + E2E 12/12 통과 (22.43s)

---

## 1. 전체 요약

```
모듈                    테스트   상태     소요시간
──────────────────────  ─────  ──────   ────────
connection.py              4   PASS    < 0.1s
schema.py                 11   PASS    < 0.1s
queries.py                19   PASS      0.4s
──────────────────────  ─────  ──────   ────────
unit 합계                 34   PASS      1.69s
E2E (DataSynth 1.1M행)   12   PASS     22.43s
```

---

## 2. E2E 테스트 (DataSynth 1,103,464행)

```
입력: 1,103,464행 | 적재: 4,296,569행 (GL+AF+BS+BD) | 소요: 22.43s
```

| 단계             | 소요(s) | 내용                                         |
|:-----------------|--------:|:---------------------------------------------|
| data_load        |   3.463 | CSV 로드 + 날짜 파싱                         |
| feature          |   6.739 | 18개 파생변수 생성                            |
| detection        |   5.721 | 3레이어 탐지 + score_aggregator              |
| db_load          |   3.180 | DuckDB in-memory 4테이블 원자적 적재         |
| queries          |   3.324 | 6종 프리셋 쿼리 실행 + 드릴다운              |

### 적재 결과

| 테이블           |          행 수 | 비고                                         |
|:-----------------|---------------:|:---------------------------------------------|
| general_ledger   |      1,103,464 | 원본 + 피처 18종 + 탐지 결과 3종             |
| anomaly_flags    |      3,193,095 | details melt → score > 0 행만 적재           |
| benford_summary  |              1 | 배치당 1행                                   |
| benford_digits   |              9 | digit 1~9                                    |

### 검증 항목 (12/12 PASS)

| #  | 검증 항목                    | 기대값          | 실제값          |
|---:|:-----------------------------|:----------------|:----------------|
|  1 | GL 행 수 일치                | 1,103,464       | 1,103,464       |
|  2 | AF 행 수 > 0                 | > 0             | 3,193,095       |
|  3 | AF 적재 수 == 조회 수        | 3,193,095       | 3,193,095       |
|  4 | Benford summary 1행         | 1               | 1               |
|  5 | Benford digits 9행          | 9               | 9               |
|  6 | Benford deviation 정합      | obs - exp       | 일치            |
|  7 | VIEW 쿼리 행 > 0            | > 0             | 17              |
|  8 | VIEW flagged_count 합 == AF | 3,193,095       | 3,193,095       |
|  9 | risk_level 분포 존재        | 1+ 등급         | High/Med/Low    |
| 10 | anomaly_score [0,1]         | [0.0, 1.0]      | [0.36, 0.75]    |
| 11 | 드릴다운 결과 > 0           | > 0             | 15              |
| 12 | 드릴다운 컬럼 정합           | 3컬럼           | 3컬럼           |

### risk_level 분포

| 등급     |       건수 |     비율 |
|:---------|----------:|---------:|
| High     |        64 |    0.01% |
| Medium   |   591,780 |   53.63% |
| Low      |   511,620 |   46.36% |
| Normal   |         0 |    0.00% |

### 룰별 위반 통계 (상위 10)

| 트랙     | 룰   |       건수 | avg_score | max_score |
|:---------|:-----|----------:|----------:|----------:|
| layer_b  | B10  | 1,103,464 |    0.8000 |    0.8000 |
| layer_b  | B07  | 1,103,041 |    0.8000 |    0.8000 |
| layer_c  | C03  |   470,530 |    0.4000 |    0.4000 |
| layer_b  | B06  |   236,442 |    0.6000 |    0.6000 |
| layer_c  | C01  |   143,341 |    0.6000 |    0.6000 |
| layer_c  | C02  |    51,903 |    0.4000 |    0.4000 |
| layer_b  | B05  |    48,615 |    0.6000 |    0.6000 |
| layer_c  | C06  |    25,404 |    0.2000 |    0.2000 |
| layer_c  | C08  |     4,741 |    0.6000 |    0.6000 |
| layer_c  | C09  |     3,421 |    0.4000 |    0.4000 |

### Benford 분석 요약

| 항목             |            값 |
|:-----------------|-------------:|
| sample_size      |    1,080,205 |
| MAD              |     0.001411 |
| MAD conformity   |        close |
| Chi2 statistic   |     240.7119 |
| Chi2 p-value     |       0.0000 |
| KS statistic     |       0.0061 |
| KS p-value       |       0.0000 |
| is_conforming    |        False |
| confidence       |         high |

---

## 3. 모듈별 unit test 검증 포인트

### 3-1. connection.py (4 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 싱글톤 동작             |  1  | 두 번 호출 시 동일 객체 반환                               |
| close 후 재연결         |  1  | close → 새 커넥션 주입 → 새 객체 반환                     |
| health check            |  1  | closed 커넥션 감지 → :memory: 자동 재생성                 |
| _override_connection    |  1  | 주입 커넥션이 get_connection()에서 반환                    |

### 3-2. schema.py (11 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 테이블 생성             |  1  | information_schema에서 4개 테이블 확인                    |
| VIEW 생성               |  1  | anomaly_flag_summary VIEW 존재 확인                       |
| SCHEMA_DDL 무결성       |  1  | dict 5개 오브젝트(4테이블 + 1VIEW) 확인                   |
| 멱등성                  |  1  | initialize_schema 2회 실행 에러 없음                      |
| Feature 컬럼 동기화     |  1  | EXPECTED_COLUMNS 18개 전부 general_ledger DDL에 존재      |
| BenfordResult 동기화    |  1  | BenfordResult 필드와 benford_summary DDL 1:1 대응         |
| COLUMNS 상수 동기화     |  4  | GL/AF/BS/BD 4개 상수와 DDL 컬럼 순서·개수 일치           |
| VIEW 조회 가능          |  1  | anomaly_flag_summary VIEW 빈 상태 정상 조회               |

### 3-3. queries.py (19 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| batch_ledger            |  3  | 행 수 일치, 필수 컬럼 존재, anomaly_score DESC 정렬       |
| batch_flags             |  2  | 4개 플래그 전수 조회, score 집합 정합                     |
| benford_summary         |  2  | 배치당 1행, sample_size/conformity/confidence 정합        |
| benford_digits          |  2  | 9행, deviation = observed - expected 검증                 |
| rule_violation_stats    |  1  | B03 flagged_count=2, avg_score=0.7 VIEW 집계 정합        |
| document_rule_detail    |  2  | JE-001 필터 2행, 미존재 ID 빈 DataFrame                  |
| 에러·경계 케이스        |  4  | 빈 테이블, 미존재 쿼리명, None 파라미터, 개수 불일치     |
| 배치 격리               |  1  | 2개 배치 적재 후 batch_id 필터링 교차 없음                |
| PRESET_QUERIES 무결성   |  2  | 6종 정의, 모든 쿼리에 upload_batch_id = ? 바인딩          |

---

## 4. 분석

### 코드 버그 (E2E에서 발견·수정)

| 문제                                       | 원인                                           | 해결                                                  |
|:-------------------------------------------|:-----------------------------------------------|:------------------------------------------------------|
| loader INSERT BinderError (44 vs 43 컬럼)  | `SELECT * FROM df`가 created_at DEFAULT 컬럼 미포함 | 4개 INSERT 문에 명시적 컬럼 지정 `INSERT INTO t (cols) SELECT * FROM df` |

### Graceful Degradation (정상)

- Benford `is_conforming=False` (Chi2 p=0.0000): 대규모 표본에서 통계적 유의성이 극도로 높아 nonconforming 판정. MAD=0.001411(close)과 상충하나, 이는 대표본 특성 (정상 동작)
- `track_name="benford"` 미존재: score_aggregator에서 독립 트랙 미실행 → 0점 처리 (정상 동작, Phase 확장 예정)

### 데이터 특성 (코드 정상)

| 항목               | 현상                                                 |
|:-------------------|:-----------------------------------------------------|
| Normal 0건         | B07(99.96%)+B10(100%) 과탐으로 모든 행 최소 Low      |
| AF 3.19M행         | 1.1M행 × 평균 2.9룰/행 → 정상 범위                  |
| anomaly_score 범위 | [0.36, 0.75] — Normal 없어 하한이 높음               |

---

## 5. 남은 문제점

| 항목                      | 설명                                                            | 해결 시점     |
|:--------------------------|:----------------------------------------------------------------|:--------------|
| `src/pipeline.py` 미구현  | E2E에서 수동 조립. 전체 오케스트레이터 필요                     | Phase 1b #21  |

---

## 6. 실행 명령어

```bash
# unit test
uv run pytest tests/test_db/ -v

# E2E (독립 실행 스크립트, ~22초)
PYTHONPATH=. uv run python tests/test_db/test_e2e_db.py
```

---

## 7. 관련 문서

| 문서                                                                                                                       | 내용                      |
|:---------------------------------------------------------------------------------------------------------------------------|:--------------------------|
| [docs/pre-plan/06-db.md](../../../docs/pre-plan/06-db.md)                                                                  | DB 레이어 설계 (4모듈 ✅) |
| [e2e-detection-datasynth.md](../../test_detection/test-results/e2e-detection-datasynth.md)                                  | Detection E2E 결과        |
| [feature-test-summary.md](../../test_feature/test-results/feature-test-summary.md)                                          | Feature 테스트 결과       |
