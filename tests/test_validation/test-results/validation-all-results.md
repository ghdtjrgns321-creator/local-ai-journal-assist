# Validation 모듈 테스트 결과 통합

> 최종 갱신: 2026-03-21 | **89 tests passed** (0.81s)

---

## 1. 전체 요약

```
모듈                    테스트   상태     핵심 기능
──────────────────────  ─────  ──────   ──────────────────────────────
Schema Validator (L1)      14   PASS    Pandera 구조·타입·제약조건 검증
Accounting Validator (L2)  20   PASS    대차일치·일자 연속성·중복 탐지
Benford Analyzer            9   PASS    Benford's Law 적합도 (Chi²/KS)
Statistical Validator (L3)  7   PASS    월별 급변·분포·Benford 통합 리포트
Temporal Stats              6   PASS    주말비율·기말집중·YoY 패턴
Volatility                 16   PASS    월별 변동·분포 정규성·계정 집중도
Report Generator           17   PASS    L1+L2 종합 리포트·score·직렬화
──────────────────────  ─────  ──────
합계                       89   PASS
```

---

## 2. 모듈별 검증 포인트

### 2-1. Schema Validator — L1 구조 검증 (14 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 정상 검증               |  2  | 풀 스펙 df, 최소 필수 컬럼 df                             |
| 필수 컬럼 누락          |  2  | 단일/복수 필수 컬럼 누락 → is_valid=False                 |
| 타입 불일치             |  1  | 필수 컬럼 dtype 오류 → 치명적 에러                        |
| 값 범위 경고            |  1  | 음수 금액 → is_valid=True + warning                       |
| Nullable 검증           |  1  | 필수 컬럼 NaN → 에러                                     |
| 선택 컬럼               |  1  | line_text 미존재 → 에러 미발생                            |
| 피처 컬럼 제외          |  2  | is_weekend 등 파생변수 검증 대상 외, stats에서도 제외     |
| column_stats            |  1  | null 비율, 유니크 수 등 통계 수집                         |
| null 비율 경고          |  1  | 높은 결측률 → warning                                    |
| 빈 DataFrame            |  1  | 0행 → 정상 처리                                          |
| Int64 nullable 호환     |  1  | pandas nullable Int64 타입 호환                           |

### 2-2. Accounting Validator — L2 회계 검증 (20 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 대차일치 (check_balance)|  7  | 정상일치, 불일치, 허용오차 내/초과, NaN, docid 부재, 빈df |
| 일자 연속성             |  5  | 연속, 1일 누락, 전부 NaT, 단일날짜, 컬럼 부재            |
| 중복 행 탐지            |  4  | 중복 없음, 2쌍 중복, 피처컬럼 제외, 빈df                 |
| 통합 (validate)         |  4  | 정상, 복합이슈, 반환타입, graceful degradation            |

핵심 설계:
- **성능 최적화**: `diff_series = debit - credit` 단일 차액 컬럼 → groupby 1회 처리
- **피처 컬럼 제외**: `get_schema()` 기반 원본 컬럼만으로 중복 판정
- **Graceful Degradation**: 필수 컬럼 부재 시 crash 대신 기본값 반환
- **반환 타입**: Python 네이티브 타입 (JSON 직렬화 보장)

### 2-3. Benford Analyzer (9 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| Benford 적합            |  1  | Benford 분포 데이터 → conforming 판정                     |
| 균등 분포 비적합        |  1  | 균등 분포 → nonconforming 판정                            |
| 소표본 낮은 신뢰도      |  1  | n < 임계값 → low confidence                               |
| 중간 신뢰도             |  1  | moderate 범위 → moderate 판정                             |
| 빈 시리즈               |  1  | 빈 입력 → 안전 처리                                      |
| observed 합계           |  1  | 관측 빈도 합 = 1.0                                       |
| expected Benford 일치   |  1  | 기대 빈도 = log₁₀(1 + 1/d)                               |
| KS 검정 (대표본)        |  1  | 큰 표본 → KS 통계량 산출                                  |
| KS 검정 (소표본)        |  1  | 작은 표본 → KS None                                      |

### 2-4. Statistical Validator — L3 통계 통합 (7 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 풀 DataFrame            |  1  | 모든 필드 정상 산출                                       |
| 컬럼 부재 graceful      |  1  | 필수 컬럼 미존재 시 기본값 반환                           |
| 빈 DataFrame            |  1  | 0행 → 안전 처리                                          |
| flags 수집              |  1  | 이상 징후 플래그 목록 반환                                |
| JSON 직렬화 왕복        |  1  | dict → json.dumps → json.loads 성공                       |
| numpy 타입 변환         |  1  | int64/float64 → Python 네이티브                           |
| first_digit fallback    |  1  | first_digit 컬럼 미존재 시 debit_amount 폴백              |

### 2-5. Temporal Stats (6 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 주말 비율               |  1  | 주말 전표 비율 산출                                       |
| 기말 집중도             |  1  | 월말 근처 전표 집중 비율                                  |
| posting_date 부재       |  1  | 컬럼 미존재 시 안전 처리                                  |
| YoY 단일연도            |  1  | 1개 연도 → None 반환                                     |
| YoY 다중연도            |  1  | 2+ 연도 → 전년 대비 변동률                                |
| 요일별 건수 키          |  1  | weekday_volume dict 키 검증                               |

### 2-6. Volatility (16 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 월별 변동 (spike)       |  1  | 급증 월 탐지 (Z-score > 2)                                |
| 균등 월 (no outlier)    |  1  | 균등 분포 → outlier 없음                                  |
| 단일 월 경고            |  1  | 1개 월만 존재 → warning                                   |
| posting_date 부재       |  1  | 컬럼 미존재 시 안전 처리                                  |
| 계절성 지수             |  1  | 월별 seasonality index 산출                               |
| 정규분포 검정           |  1  | 정규 분포 → shapiro p > 0.05                              |
| 우편향 검정             |  1  | 로그정규 → skewness > 0                                   |
| 소표본 shapiro 스킵     |  1  | n < 8 → shapiro 스킵                                     |
| 빈 시리즈               |  1  | 빈 입력 → 안전 처리                                      |
| 대표본 샘플링           |  1  | n > 5000 → 샘플링 후 검정                                 |
| 이상치 집중도           |  1  | outlier_concentration 산출                                |
| 단일 계정 집중          |  1  | 1개 계정 → HHI = 1.0                                     |
| 다계정 분산             |  1  | 다수 계정 → 낮은 HHI                                     |
| gl_account 부재         |  1  | 컬럼 미존재 시 안전 처리                                  |
| CV zero mean 방어       |  1  | 평균 0 → ZeroDivisionError 방지                           |
| 높은 CV 계정 탐지       |  1  | CV > 임계값 계정 목록 반환                                |

### 2-7. Report Generator (17 tests)

| 그룹                    | 수  | 검증 포인트                                               |
|:------------------------|:---:|:----------------------------------------------------------|
| 정상 동작               |  2  | 전체 필드 생성, source_file 전달                          |
| is_pipeline_ready       |  2  | L1 치명적 에러 → False, L1 경고만 → True                  |
| accounting_issues       |  4  | 대차불일치, 일자 누락, 중복, valid_documents 산출         |
| validation_score        |  2  | 전체 위반 → 0점 클리핑, L1 치명적 50점 감점              |
| JSON 직렬화             |  2  | json.dumps 성공, numpy 네이티브 변환                      |
| 메타데이터              |  2  | generated_at UTC, date_range min/max                      |
| Edge cases              |  3  | 빈 df, statistical_result None, 전체 NaT                  |

---

## 3. L1~L3 검증 아키텍처

```
L1 Schema (Pandera)        L2 Accounting           L3 Statistics (Phase 2)
─────────────────────      ───────────────────     ──────────────────────
필수 컬럼 존재/타입        대차일치 (document별)   월별 변동 (Z-score)
값 범위 (ge=0 등)          일자 연속성 (bdate)     분포 정규성 (Shapiro-Wilk)
null 비율 경고             완전 중복 행 탐지       계정 집중도 (HHI)
피처 컬럼 제외             피처 컬럼 제외          Benford's Law (Chi²/KS)
                                                    시계열 패턴 (주말/기말/YoY)
           ↓                         ↓                         ↓
           └─────── report_generator.generate_report() ────────┘
                              ↓
                    ValidationReport (JSON)
                    - validation_score (0~100)
                    - is_pipeline_ready
                    - schema_errors/warnings
                    - accounting_issues
                    - statistical_flags
```

---

## 4. pre-plan 대비 보완 반영 사항

| #  | 보완 내용                          | 반영 결과                                                        |
|:---|:-----------------------------------|:-----------------------------------------------------------------|
| 1  | `valid_rows` 산출 로직 미정의      | L1 is_valid 기준 근사치 + `total_documents`/`valid_documents` 신규 |
| 2  | `accounting_issues` dict 키 미정의 | `{check_type, severity, message, detail}` 표준 구조 확정          |
| 3  | `data_quality_score` 음수 가능     | 비율 기반 감점 + 클리핑(0~100), 필드명 `validation_score`로 변경  |
| 4  | 메타데이터 필드 부재               | `generated_at`(UTC), `source_file`, `date_range` 추가             |
| 5  | `_sanitize` 중복                   | validation 내 private 복사, Phase 1b에서 공용 추출 예정           |

---

## 5. 남은 과제

```
문제                           현상                                    해결 시점
─────────────────────────────  ────────────────────────────────────    ──────────
L3 통계 검증 리포트 통합       statistical_flags 빈 리스트 상태        Phase 2
한국 공휴일 지원               bdate_range만 사용 중                   Phase 2
업종별 영업일 차이             단일 bdate_range 기준                   Phase 1c
_sanitize 공용 추출            validation 내 private 복사 상태         Phase 1b
```

---

## 6. 소스 바로가기

```
구현 코드:
  src/validation/__init__.py              퍼블릭 API 재익스포트
  src/validation/models.py                dataclass 3종 (SchemaResult, AccountingResult, ValidationReport)
  src/validation/schema_validator.py      L1: Pandera 구조 검증
  src/validation/accounting_validator.py  L2: 대차일치·일자·중복
  src/validation/report_generator.py      L1+L2 종합 리포트
  src/validation/benford.py              Benford's Law 분석기
  src/validation/statistical_validator.py L3: 통계 검증 통합
  src/validation/temporal_stats.py        시계열 패턴 분석
  src/validation/volatility.py            변동성·분포·계정 집중도

테스트 코드:
  tests/test_validation/test_schema_validator.py
  tests/test_validation/test_accounting_validator.py
  tests/test_validation/test_report_generator.py
  tests/test_validation/test_benford.py
  tests/test_validation/test_statistical_validator.py
  tests/test_validation/test_temporal_stats.py
  tests/test_validation/test_volatility.py
```

## 7. 실행 명령어

```bash
# 전체 validation 테스트
uv run pytest tests/test_validation/ -v

# 개별 모듈
uv run pytest tests/test_validation/test_schema_validator.py -v
uv run pytest tests/test_validation/test_accounting_validator.py -v
uv run pytest tests/test_validation/test_report_generator.py -v
uv run pytest tests/test_validation/test_benford.py -v
uv run pytest tests/test_validation/test_statistical_validator.py -v
uv run pytest tests/test_validation/test_temporal_stats.py -v
uv run pytest tests/test_validation/test_volatility.py -v
```
