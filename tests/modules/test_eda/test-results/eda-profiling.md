# EDA 프로파일링 모듈 테스트 결과

## 요약

| 항목          | 값                     |
|---------------|------------------------|
| 테스트 수     | 52                     |
| 통과          | 52                     |
| 실패          | 0                      |
| 소요 시간     | 0.78s                  |
| 날짜          | 2026-03-25             |
| 커버리지 대상 | src/eda/ (7개 모듈)    |

## 모듈별 테스트 분포

| 테스트 파일                 | 케이스 수 | 대상 모듈                |
|-----------------------------|-----------|--------------------------|
| test_type_classifier.py     | 7         | type_classifier.py       |
| test_numeric_profiler.py    | 8         | numeric_profiler.py      |
| test_category_profiler.py   | 5         | category_profiler.py     |
| test_datetime_profiler.py   | 5         | datetime_profiler.py     |
| test_boolean_profiler.py    | 4         | boolean_profiler.py      |
| test_profiler.py            | 13        | profiler.py (통합)       |
| test_report.py              | 10        | report.py                |

## 주요 검증 항목

- dtype 4분류 정확성 (boolean 우선순위 포함)
- 수치형 IQR 이상치 탐지 (Tukey's fence)
- std=0 / 전체 NaN / 단일값 등 엣지케이스
- numpy → Python 네이티브 변환 (json.dumps 호환)
- 110만행 샘플링 트리거 (sampled=True, sample_size=100K)
- 0행 빈 DataFrame 안전 처리
- quality_score 0~100 범위 + 감점 로직
- warnings 생성 (결측률/카디널리티/중복률/이상치)
- 한글 범주값 처리

## 발견된 문제점 및 해결

| #  | 문제                                           | 원인                                             | 해결                                                          | 발견 단계       |
|----|------------------------------------------------|--------------------------------------------------|---------------------------------------------------------------|-----------------|
| 1  | datetime dropna() 후 .dt accessor 실패         | dropna()가 DatetimeIndex 반환                    | pd.Series()로 감싸서 .dt accessor 보장 (`datetime_profiler.py:14`) | 테스트 실행     |
| 2  | `profile_boolean` pd.NA 방어 누락              | nullable BooleanDtype의 sum()이 pd.NA 반환 가능  | `pd.isna()` 체크 추가 (`boolean_profiler.py:18`)              | 코드 리뷰       |
| 3  | `_column_highlights` std=None 시 포맷 에러     | 전체 결측 수치 컬럼에서 mean≠None이지만 std=None | `cp.std is not None` 가드 추가 (`report.py:141`)              | 코드 리뷰       |

## 코드 리뷰 후속 (Phase 1c 이전 처리 권장)

| #  | 이슈                                                          | 대상 파일              | 처리 시점                | 해결 위치 (pre-plan)                                                              |
|----|---------------------------------------------------------------|------------------------|--------------------------|-----------------------------------------------------------------------------------|
| 1  | `datetime_profiler` `.values` → `.array` 전환 (타임존 보존)   | datetime_profiler.py   | Phase 1c 타임존 지원 시  | [07-dashboard §미해결](../../docs/pre-plan/07-dashboard.md#미해결-이슈-phase-1c에서-해결--발견-위치-교차-참조) |
| 2  | `top_values` tuple→list 변환 계약 문서화                      | category_profiler.py   | Phase 1c 대시보드 연동 시 | [07-dashboard §미해결](../../docs/pre-plan/07-dashboard.md#미해결-이슈-phase-1c에서-해결--발견-위치-교차-참조) |
| 3  | `_generate_warnings` 룰 코드 상수화 (L1-02 등)                  | report.py              | Phase 1b detection 연동 시 | [05-detection §선행이슈](../../docs/pre-plan/05-detection.md#선행-모듈에서-넘어온-미해결-이슈-교차-참조) |

## 개선 방안 (후속 Phase)

- Phase 2: 상관관계 분석 (수치 컬럼 간 pearson/spearman) → [03a-preprocessing §Phase구분](../../docs/pre-plan/03a-preprocessing.md#phase-구분)
- Phase 2: sklearn Pipeline 전처리 전략 자동 제안 → [03a-preprocessing §②](../../docs/pre-plan/03a-preprocessing.md#-sklearn-pipeline-전처리---구현-예정-phase-2)
- Phase 3: EDAProfile → LLM 프롬프트 입력 (profile_to_llm_context) → [03a-preprocessing §③](../../docs/pre-plan/03a-preprocessing.md#-llm-전처리-제안---구현-예정-phase-3)
