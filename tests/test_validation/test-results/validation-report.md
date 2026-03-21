# report_generator 테스트 결과

## 1. 전체 요약

```
테스트 파일: tests/test_validation/test_report_generator.py
테스트 수  : 17 passed, 0 failed
소요 시간 : 0.09s
회귀 확인 : 전체 509 tests passed (59.92s)
```

| 카테고리           | 테스트 수 | 상태 |
|:-------------------|:---------|:-----|
| 정상 동작          | 2        | PASS |
| is_pipeline_ready  | 2        | PASS |
| accounting_issues  | 4        | PASS |
| validation_score   | 2        | PASS |
| JSON 직렬화        | 2        | PASS |
| 메타데이터         | 2        | PASS |
| Edge cases         | 3        | PASS |

## 2. pre-plan 대비 보완 5건 반영

| #  | 보완 내용                          | 반영 결과                                         |
|:---|:-----------------------------------|:--------------------------------------------------|
| 1  | `valid_rows` 산출 로직 미정의      | L1 is_valid 기준 근사치 + `total_documents`/`valid_documents` 신규 |
| 2  | `accounting_issues` dict 키 미정의 | `{check_type, severity, message, detail}` 표준 구조 확정 |
| 3  | `data_quality_score` 음수 가능     | 비율 기반 감점 + 클리핑(0~100), 필드명 `validation_score`로 변경 |
| 4  | 메타데이터 필드 부재               | `generated_at`(UTC), `source_file`, `date_range` 추가 |
| 5  | `_sanitize` 중복                   | validation 내 private 복사, Phase 1b에서 공용 추출 예정 |

## 3. 핵심 검증 포인트

- **validation_score**: L1 치명적 에러 시 최소 50점 감점, 모든 위반 시에도 score >= 0 (클리핑)
- **is_pipeline_ready**: `schema_result.is_valid` 기반 — L1 경고만 있으면 True
- **generated_at**: UTC 타임존 포함 ISO 8601 (Naive datetime 방지)
- **date_range**: posting_date 전체 NaT / 0행 / 컬럼 미존재 시 None 반환 (방어 로직)
- **JSON 직렬화**: numpy int64/float64 → Python 네이티브 변환, json.dumps 성공

## 4. 소스 바로가기

```
src/validation/models.py              # dataclass 3종
src/validation/report_generator.py    # generate_report + report_to_dict
src/validation/__init__.py            # 퍼블릭 API
tests/test_validation/conftest.py     # vr_ prefix fixtures
tests/test_validation/test_report_generator.py  # 17 tests
```

## 5. 실행 명령어

```bash
uv run pytest tests/test_validation/test_report_generator.py -v
```
