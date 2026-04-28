# 03. 감사 파생변수 엔진 (Feature Engineering) [Phase 1a — 의존: 02]

## 목적
표준 DataFrame에 감사 관점의 파생변수 18개를 추가하여, 이상탐지 룰과 ML 모델의 입력 피처로 활용한다.
각 파생변수는 DETECTION_RULES.md §5의 24개 룰(L1-01~L3-09)에 대응.

> **선행 모듈**: ingest에서 타입 캐스팅·Null 처리 완료된 표준 DataFrame을 입력으로 받는다.
> 컬럼 타입(float, datetime 등)이 보장된 상태이므로 별도 타입 검증 없이 연산에 집중.

---

## 데이터 흐름

```
[표준 DataFrame] (from ingest — type_caster 완료)
       ↓
engine.generate_all_features(df, settings)
       ↓
  ├── time_features    → is_weekend, is_after_hours, is_period_end, days_backdated, fiscal_period_mismatch, is_holiday, time_zone_category
  ├── amount_features  → is_near_threshold, exceeds_threshold, amount_zscore, amount_magnitude, is_round_number
  ├── pattern_features → is_manual_je, is_intercompany, is_revenue_account, first_digit, is_suspense_account
  └── text_features    → has_risk_keyword, description_quality
       ↓
[피처 보강된 DataFrame] → validation/ → detection/
```

---

## 구현 상태 & 모듈별 가이드

### engine.py — ✅ 구현 완료 (14 tests passed)

4개 서브모듈을 순서대로 호출하여 18개 파생변수를 일괄 생성하는 오케스트레이터.
[테스트 결과](../../tests/test_feature/test-results/feature-test-summary.md#5-엔진-오케스트레이터-14-cases)

#### 이 모듈이 하는 일

파생변수 생성은 4개 서브모듈(time/amount/pattern/text)로 분리되어 있다.
각 서브모듈을 개별 호출하면 호출 순서·설정 주입·에러 처리를 매번 반복해야 한다.

engine.py는 이 **"조립 과정"을 단일 진입점으로 캡슐화**하는 역할을 한다.

```
문제:
  detection이나 dashboard에서 파생변수가 필요할 때마다
  time_features → amount_features → pattern_features → text_features를
  직접 순서대로 호출하고, settings와 audit_rules를 각각 주입해야 한다.
  → 호출부가 늘어날수록 누락·순서 오류 위험이 커진다.

해결:
  engine.generate_all_features(df, settings)를 호출하면
  4개 서브모듈을 정해진 순서로 실행하고, 설정·룰을 자동 주입한다.
  호출부는 engine만 알면 되므로 서브모듈 내부 변경에 영향받지 않는다.
```

```
src/feature/
├── engine.py              # 전체 피처 오케스트레이션
├── time_features.py       # 시간 관련 파생변수 (7개)
├── amount_features.py     # 금액 관련 파생변수 (5개)
├── pattern_features.py    # 패턴 관련 파생변수 (4개)
└── text_features.py       # 텍스트 관련 파생변수 (2개)
```

**호출 순서**: time → amount → pattern → text (의존 관계 없으므로 순서 교체 가능)

---

### time_features.py — ✅ 구현 완료 (7개 변수)

#### 이 모듈이 하는 일

전표의 날짜·시간 정보를 감사 관점의 플래그로 변환한다.

```
문제:
  부정 전표는 정상 업무 시간 외(주말·심야·공휴일)에 입력되거나,
  기말에 집중 처리되거나, 문서일자보다 한참 뒤에 전기되는 패턴을 보인다.
  원본 DataFrame의 posting_date, document_date는 날짜 값일 뿐,
  이런 "감사적 의미"를 직접 담고 있지 않다.

해결:
  날짜 컬럼으로부터 is_weekend, is_after_hours, is_period_end,
  days_backdated, fiscal_period_mismatch, is_holiday 6개 bool/int 변수를 산출한다.
  detection L3/L4(L3-04~L1-08)가 이 변수를 직접 참조하여 이상 여부를 판정한다.
```

시간/날짜 기반 파생변수. `posting_date`(datetime), `document_date`(datetime), `fiscal_period`(int)를 입력으로 사용.

| 변수명                   | 타입    | 대응 룰 | 감사 관점                                                  |
|:-------------------------|:--------|:--------|:----------------------------------------------------------|
| `is_weekend`             | bool    | L3-05     | 주말 전기 — 정상 업무 외 처리, 부정 가능성                  |
| `is_after_hours`         | bool    | L3-06     | 심야 전기(22~06시) — 승인 우회 가능성                       |
| `is_period_end`          | bool    | L3-04     | 기말 양방향 탐지(월말 전 + 익월 초 margin일) — 실적 조정    |
| `days_backdated`         | Int64   | L3-07     | posting − document 일수 **부호 유지** — +지연/−선전기       |
| `fiscal_period_mismatch` | boolean | L1-08     | **modulo 연산** — 비표준 회계연도(4월 결산 등) 대응         |
| `is_holiday`             | bool    | L3-05     | **holidays.KR + custom** 하이브리드 — 법정+회사 지정 병합   |
| `time_zone_category`     | str     | L4-05     | 3단계 시간대 분류(normal/overtime/midnight) — 결산기(12/20~1/15)·주말 보정, 초 단위 정밀도 |

**설계 결정:**

| 이슈                                          | 결정                                                          |
|:----------------------------------------------|:--------------------------------------------------------------|
| is_after_hours — 시간 정보 없는 날짜           | `_has_time_info()` 컬럼 단위 판정 → False + warning            |
| is_period_end — 양방향 탐지                    | 월말 전 margin일 + 익월 초 margin일, `period_end_margin_days` 외부화 |
| is_holiday — 공휴일 목록 관리                  | `holidays.KR` (법정공휴일 자동) + `custom_holidays` (회사 지정) 하이브리드 |
| days_backdated — 부호 의미                     | **부호 유지** — 양수=지연전기, 음수=선전기. abs() 미적용       |
| days_backdated — document_date 누락            | skip + warning (NaN 반환), dtype=Int64(nullable)               |
| fiscal_period_mismatch — 비표준 회계연도       | `(month - fiscal_year_start) % 12 + 1` modulo 연산            |
| fiscal_period_mismatch — NaN 함정              | 결측치 마스크 → pd.NA 덮어씌움 (오탐 방지), dtype=boolean      |
| fiscal_period_mismatch — K4 variant 검증       | DataSynth v1.2.0 실측: `fiscal_year_variant: K4`이나 실제 매핑은 1월=period 1 (표준). fiscal_period = posting_date month 정확히 1:1. `fiscal_year_start=1` 유지 |

**테스트**: [test_time_features.py](../../tests/test_feature/test_time_features.py) — 49 케이스 | [테스트 결과](../../tests/test_feature/test-results/feature-test-summary.md#time_features-49-cases)

---

### amount_features.py — ✅ 구현 완료 (5개 변수, 27 tests passed)

#### 이 모듈이 하는 일

전표의 차변·대변 금액을 감사 관점의 통계·임계치 변수로 변환한다.

```
문제:
  부정 전표는 승인한도 직전 금액(한도 우회), 정확히 떨어지는 라운드 금액(가공전표),
  통계적으로 극단적인 금액(이상치) 패턴을 보인다.
  원본 debit_amount, credit_amount는 단순 숫자이므로
  "이 금액이 비정상적인가?"를 판단할 수 없다.

해결:
  base_amount(=max(debit, credit))를 기준으로
  is_near_threshold, exceeds_threshold, amount_zscore,
  amount_magnitude, is_round_number 5개 변수를 산출한다.
  detection L2(L2-01~L2-02)와 L3/L4(L4-03)가 이 변수로 부정·이상 여부를 판정한다.
```

금액 기반 파생변수. `debit_amount`(float), `credit_amount`(float)를 입력으로 사용.
`base_amount = max(debit, credit).fillna(0)` 중간 Series로 산출 후 각 피처에 전달 (컬럼 미추가).

| 변수명              | 타입  | 대응 룰  | 감사 관점                                           |
|:--------------------|:------|:---------|:---------------------------------------------------|
| `is_near_threshold` | bool  | L2-01      | 승인한도 × 0.90 이상 ~ 한도 미만 — 승인 우회 의도   |
| `exceeds_threshold` | bool  | L1-04      | 승인한도 초과 — 승인 절차 확인 필요                  |
| `amount_zscore`     | float | L4-03      | 금액 Z-score > 3 — 통계적 이상치                    |
| `amount_magnitude`  | float | — (ML)   | 금액 자릿수(log10) — ML 피처용                      |
| `is_round_number`   | bool  | L2-02      | 백만/천만 단위 round 금액 — 가공전표/횡령 탐지       |

**설계 결정:**

| 이슈                                    | 결정                                                                       |
|:----------------------------------------|:---------------------------------------------------------------------------|
| base_amount 산출                         | `max(debit, credit).fillna(0)` — 복식부기 한 라인은 차/대 중 하나만 양수    |
| threshold 값이 회사마다 다름             | `settings.approval_thresholds: list[int]`로 외부화. 6단계 `[10M, 100M, 1B, 5B, 10B, 50B]` |
| ✅ 다단계 threshold 확장 완료            | `is_near_threshold`·`exceeds_threshold`가 `thresholds: list[int]`를 수용하여 각 레벨별 near/exceeds 판정. 가장 가까운 상위 한도 기준으로 판정 |
| near/exceeds 경계 gap                   | `ratio*threshold ≤ x < threshold` / `x ≥ threshold` — 겹침·gap 없음 보장   |
| amount_zscore 계산 단위                  | gl_account별 groupby — n≥30 그룹별, n<30 전체 fallback, n<10 전체 NaN       |
| Z-score std==0                           | 0.0 반환 (ZeroDivisionError 방지)                                          |
| Z-score 소그룹 fallback 왜곡             | 큰 그룹 분포에 의해 왜곡 가능 → Phase 2 CoA 상위그룹 fallback 개선 예정     |
| 0원 금액 처리                            | Z-score에 포함, is_round_number에서 제외(False)                             |
| is_round_number 판정 기준                | `amount % round_unit == 0` — settings.round_unit 외부화 (기본 100만)        |
| float % 연산 안전성                      | ingest에서 정수값 보장 → 안전. 외화 소수점은 Phase 2 round() 전처리 예정    |
| gl_account 컬럼 누락                     | zscore NaN + warning 로깅 (에러 미발생)                                     |

**테스트**: [test_amount_features.py](../../tests/test_feature/test_amount_features.py) — 27 케이스 | [테스트 결과](../../tests/test_feature/test-results/feature-test-summary.md#amount_features-27-cases)

---

### pattern_features.py — ✅ 구현 완료 (5개 변수, 41 tests passed)

#### 이 모듈이 하는 일

전표의 속성(전기원천·계정코드·금액)을 감사 업무 룰과 매칭하여 패턴 플래그를 생성한다.

```
문제:
  부정 전표는 수기 입력(자동화 통제 우회), 관계사 간 순환거래,
  매출계정 집중 조작, 가계정 장기 미정리 등 특정 속성 패턴을 보인다.
  원본 source, gl_account 컬럼은 코드 값이므로
  "이 전표가 수기인지", "매출계정인지"를 바로 알 수 없다.

해결:
  audit_rules.yaml에 정의된 업무 룰(수기전표 코드, 매출계정 prefix,
  가계정 키워드 등)과 매칭하여 is_manual_je, is_intercompany,
  is_revenue_account, first_digit, is_suspense_account 5개 변수를 산출한다.
  detection L2(L4-01, L3-02, L3-03, L2-04)와 L3/L4(L3-08, L4-02)가 이 변수를 참조한다.
```

전표 속성 기반 패턴 매칭. `source`(str), `company_code`(str), `gl_account`(Int64), 금액·텍스트 컬럼 사용.
감사 업무 룰(키워드/코드)은 `config/audit_rules.yaml`에서 로드 — 함수 인자로 주입 (테스트 용이).

| 변수명                 | 타입  | 대응 룰  | 감사 관점                                         |
|:-----------------------|:------|:---------|:--------------------------------------------------|
| `is_manual_je`         | bool  | L3-02      | source 수기전표 코드 매칭 — 자동화 통제 우회       |
| `is_intercompany`      | bool  | L3-03      | 관계사 거래 패턴 — 순환거래 위험                   |
| `is_revenue_account`   | bool  | L4-01      | gl_account 매출계정 prefix 매칭                    |
| `first_digit`          | Int64 | L4-02      | 금액 첫 유효숫자(1~9) — Benford 분석 입력          |
| `is_suspense_account`  | bool  | L2-04/L3-08  | 가계정·미결산 키워드 매칭 — 장기미정리 부정 은폐    |

**설계 결정:**

| 이슈                                          | 결정                                                                       |
|:----------------------------------------------|:---------------------------------------------------------------------------|
| 업무 룰 하드코딩 문제                          | `config/audit_rules.yaml`로 완전 외부화. settings.py는 로더만 제공          |
| YAML vs settings 관심사 분리                   | settings = 시스템 설정(env), audit_rules = 도메인 업무 룰(YAML). 별도 로더  |
| first_digit — 음수/소수/과학표기법             | `str.extract(r"([1-9])")` — 모든 edge case 한 줄로 안전 처리               |
| first_digit — 0원 금액                         | NaN 반환 (Benford 분석 대상 외)                                            |
| gl_account가 Int64                             | `.astype(str)` 변환 후 startswith. `<NA>` → 매칭 안 됨 (정상)              |
| is_suspense_account 매칭 대상                  | `_SUSPENSE_TEXT_COLS` 상수. MVP: line_text + header_text                    |
| 정규식 키워드 안전성                           | `re.compile` 실패 시 `re.escape()` 폴백 + warning                          |
| 함수 인자 vs settings 직접 참조                | 함수 인자로 받기 (테스트 용이, engine.py에서 audit_rules 주입)              |
| ✅ IC identifiers 수정 완료                     | audit_rules.yaml `["1150", "2050", "4500", "2700"]`으로 변경. "C" 접미사 제거 + IC Revenue/Accrued prefix 추가 |
| ✅ manual_source_codes 수정 완료                | `["Manual", "Adjustment"]`으로 변경. `SA`(document_type 오매칭) 제거, `Adjustment`(결산 조정 수기) 추가 |
| ✅ suspense 하이브리드 방식 적용                | 텍스트 키워드(한글+영문) OR gl_account prefix(`1190`, `2190` 등 5개) 매칭. DataSynth 영문 적요에서도 GL 코드로 탐지 가능 |

**테스트**: [test_pattern_features.py](../../tests/test_feature/test_pattern_features.py) — 42 케이스 | [테스트 결과](../../tests/test_feature/test-results/feature-test-summary.md#pattern_features-42-cases)

---

### text_features.py — ✅ 구현 완료 (2개 변수, 38 tests passed)

#### 이 모듈이 하는 일

전표 적요(description)의 텍스트를 분석하여 위험 키워드 매칭과 품질 등급을 산출한다.

```
문제:
  부정 전표는 적요에 '상품권', '가계정' 등 위험 키워드가 포함되거나,
  반대로 적요가 비어 있거나 1~2글자로 극히 빈약한 경우가 많다.
  숫자·날짜 기반 탐지로는 이런 텍스트 패턴을 포착할 수 없다.

해결:
  line_text + header_text를 결합한 뒤,
  has_risk_keyword(위험 키워드 매칭 결과)와
  description_quality(missing/poor/normal 3단계 품질 등급)를 산출한다.
  detection L3/L4(L3-08)가 이 변수로 적요 관련 이상 여부를 판정한다.
  Phase 2~3에서 형태소 분석(kiwipiepy)과 LLM 기반 의미 이상 탐지로 확장 예정.
```

적요(description) 텍스트 분석. `line_text`(str), `header_text`(str)를 입력으로 사용.

| 변수명                  | 타입 | 대응 룰 | 감사 관점                                           |
|:------------------------|:-----|:--------|:---------------------------------------------------|
| `has_risk_keyword`       | str  | NLP/semantic 후보 | '상품권', '가계정' 등 위험 키워드 — Phase 1 L3-08 조건 아님 |
| `description_quality`   | str  | L3-08     | 적요 품질 등급: missing(NaN/빈값) / corrupted(깨짐) / normal |

**설계 결정:**

| 이슈                              | 결정                                                                        |
|:----------------------------------|:----------------------------------------------------------------------------|
| 헤더/라인 결합 (함정①)             | `_combine_text()` — 공백 concat, 둘 다 없으면 NaN. concat으로 normal 구제    |
| 텍스트 정제 (함정②)               | `_clean_for_keyword()` — 한글+영숫자 외 제거. description_quality에서는 미사용 |
| 노이즈 필터링 (MVP 타협)          | `_is_noise_pattern()` — 자음만/특수문자만/동일문자 반복 → poor에 병합         |
| 위험 키워드 관리                   | risk_keywords.yaml에서 로드 + risk_kw 직접 주입 가능 (테스트 용이)           |
| 키워드 매칭 우선순위               | high → medium → low 순서 (최고 등급 우선 반환)                               |
| description_quality 등급           | NaN→missing, noise→corrupted, else→normal. legacy `poor`는 하위 호환으로만 처리 |
| Phase 2/3 stubs                   | `add_semantic_similarity`, `add_semantic_anomaly` — no-op + logger.info      |

**테스트**: [test_text_features.py](../../tests/test_feature/test_text_features.py) — 38 케이스 | [테스트 결과](../../tests/test_feature/test-results/feature-test-summary.md#text_features-38-cases)

#### Phase 2/3 텍스트 피처 확장 로드맵

현재 stub으로 선언된 2개 함수의 구체적 구현 계획:

| 함수                       | Phase | 입력                      | 출력 (컬럼)              | 알고리즘                                          | 감사 관점                                   |
|:---------------------------|:------|:--------------------------|:-------------------------|:--------------------------------------------------|:--------------------------------------------|
| `add_semantic_similarity`  | 2     | combined_text (정제 버전) | `semantic_similarity` (float 0~1) | kiwipiepy 형태소 분석 → TF-IDF/임베딩 벡터화 → gl_account 그룹 내 코사인 유사도 | 같은 계정인데 적요가 이질적인 전표 탐지 — 계정 오분류·위장 거래 |
| `add_semantic_anomaly`     | 3     | combined_text + 주변 컨텍스트 | `semantic_anomaly` (bool/float) | Ollama (Qwen3-8B) 프롬프트 기반 문맥 이상 판단 | 숫자·키워드로는 잡히지 않는 문맥상 부자연스러운 적요 탐지 |

**Phase 2 — `add_semantic_similarity` 구현 방향:**
- **형태소 분석**: kiwipiepy로 한글 적요 토큰화 (명사+동사 추출)
- **벡터화**: 그룹(gl_account)별 TF-IDF 매트릭스 구축
- **유사도**: 각 전표의 적요 벡터를 그룹 중심 벡터와 코사인 유사도 계산
- **이상 판정**: 유사도 < threshold → 그룹 내 이질적 전표로 플래그
- **성능 고려**: 대량 전표 시 배치 처리, sparse matrix 활용

**Phase 3 — `add_semantic_anomaly` 구현 방향:**
- **LLM**: Ollama + Qwen3-8B (Q4_K_M), 로컬 추론
- **프롬프트 전략**: 전표의 계정·금액·날짜·적요를 컨텍스트로 제공 → "이 전표의 적요가 거래 내용과 부합하는가?" 판정
- **배치 처리**: 전체 전표가 아닌 Phase 1~2에서 플래그된 고위험 전표만 LLM 통과 (비용·시간 절약)
- **출력**: 이상 여부(bool) + 이유 텍스트(str) — 감사 보고서 근거 자료로 활용
- **fallback**: Ollama 미실행 시 skip + warning (MVP와 동일한 graceful degradation)

---

## 19개 파생변수 요약

| #  | 변수명                    | 타입  | 대응 룰  | 카테고리 |
|----|---------------------------|-------|----------|----------|
| 1  | `is_weekend`              | bool  | L3-05      | time     |
| 2  | `is_after_hours`          | bool  | L3-06      | time     |
| 3  | `is_period_end`           | bool  | L3-04      | time     |
| 4  | `days_backdated`          | Int64 | L3-07      | time     |
| 5  | `fiscal_period_mismatch`  | bool  | L1-08      | time     |
| 6  | `is_holiday`              | bool  | L3-05      | time     |
| 7  | `time_zone_category`      | str   | L4-05      | time     |
| 8  | `is_near_threshold`       | bool  | L2-01      | amount   |
| 9  | `exceeds_threshold`       | bool  | L1-04      | amount   |
| 10 | `amount_zscore`           | float | L4-03      | amount   |
| 11 | `amount_magnitude`        | float | — (ML)   | amount   |
| 12 | `is_round_number`         | bool  | L2-02      | amount   |
| 13 | `is_manual_je`            | bool  | L3-02      | pattern  |
| 14 | `is_intercompany`         | bool  | L3-03      | pattern  |
| 15 | `is_revenue_account`      | bool  | L4-01      | pattern  |
| 16 | `first_digit`             | Int64 | L4-02      | pattern  |
| 17 | `is_suspense_account`     | bool  | L3-09 보조  | pattern  |
| 18 | `has_risk_keyword`        | str   | NLP/semantic 후보 | text     |
| 19 | `description_quality`     | str   | L3-08      | text     |

## 구현 순서
1. `time_features.py` — 가장 단순 (날짜 기반 계산)
2. `amount_features.py` — 금액 기반 계산
3. `pattern_features.py` — DataFrame 내 패턴 매칭 (관계사·매출계정 판별)
4. `text_features.py` — 문자열 매칭 (risk_keywords.yaml 참조)
5. `engine.py` — 4개 서브모듈 통합 오케스트레이션

## 의존성
- **선행:** `02-ingest` (타입 캐스팅·Null 처리 완료된 표준 DataFrame), `01-project-setup` (settings, risk_keywords.yaml)
- **전처리 전제:** ingest type_caster가 float/datetime/str 변환을 보장 → feature에서는 타입 검증 불필요
- **외부 패키지:** `pandas`, `numpy`, `holidays` (time_features — 법정공휴일 자동 판정)
- **후행:** `03a-preprocessing` (EDA 프로파일링 — 피처 추가된 DataFrame 대상), `04-validation` (피처 보강된 DataFrame 검증), `05-detection` (피처를 입력으로 이상탐지)

## Phase 구분

| 항목                                                          | Phase    |
|---------------------------------------------------------------|----------|
| 18개 파생변수 전체 (time 6 + amount 5 + pattern 5 + text 2)   | Phase 1a |
| `add_semantic_similarity` — kiwipiepy 형태소 + TF-IDF 유사도  | Phase 2  |
| `add_semantic_anomaly` — Ollama LLM 문맥 이상 탐지            | Phase 3  |

> Phase 2/3 확장 상세는 문서 하단 **[Phase 2/3 확장 로드맵](#phase-23-확장-로드맵)** 참조.

## E2E 테스트 (ingest → feature)

실 데이터로 전체 파이프라인을 검증하는 통합 테스트. 단위 테스트 172개와 별도.

| 데이터셋                | 행수      | 피처 생성 | 소요시간 | 결과                                                                           |
|:------------------------|----------:|:---------:|:--------:|:-------------------------------------------------------------------------------|
| datasynth (1,108K건)    | 1,107,720 | 18/18     | ~7.7s    | [e2e-datasynth.md](../../tests/test_feature/test-results/e2e-datasynth.md)     |
| sap-merged (331K건)     |   331,934 | 13/18     | ~0.8s    | [e2e-sap-merged.md](../../tests/test_feature/test-results/e2e-sap-merged.md) — graceful degradation |

**engine.py 개선**: `_run_category()` try/except(KeyError) 추가 — 필수 컬럼 누락 시 해당 카테고리만 스킵, 나머지 정상 실행.

**피처별 실측 분포** (datasynth v1.2.0, 2026-03-26):

| 피처                     | True 비율 | 비고                                                                       |
|:-------------------------|----------:|:---------------------------------------------------------------------------|
| `is_weekend`             |    10.0%  | 주말 전기 — L3-05 탐지 대상                                                   |
| `is_after_hours`         |     1.1%  | 심야(22-06) 전기 — L3-06 탐지 대상                                            |
| `is_period_end`          |    52.6%  | 기말 양방향 margin=5일 — 분기말·연말 집중 반영                               |
| `is_holiday`             |     5.6%  | 법정공휴일 + 커스텀                                                         |
| `is_near_threshold`      |     0.4%  | 다단계 6레벨 near 구간 합산 (v1.2.0에서 다단계 확장)                         |
| `exceeds_threshold`      |     0.0%  | max threshold(50B) 초과 없음                                                |
| `is_round_number`        |     0.0%  | `base.round(0) % unit` 적용으로 float 꼬리 허용 (DataSynth 재생성 시 확인 필요) |
| `is_manual_je`           |    25.8%  | source `manual` + `adjustment` 매칭 (v1.2.0에서 Adjustment 추가)            |
| `is_intercompany`        |     1.3%  | IC identifiers `[1150,2050,4500,2700]` 매칭 (v1.2.0에서 "C" 접미사 제거 + 확장) |
| `is_revenue_account`     |    20.2%  | gl_account prefix "4" 매칭                                                  |
| `is_suspense_account`    |     0.0%→TBD | 하이브리드 방식 적용: 텍스트 키워드 OR gl_account 코드 prefix 매칭 (2026-03-26) |
| `fiscal_period_mismatch` |     (2값) | fiscal_period = posting_date month 1:1 대응. K4 variant이나 1월=period 1     |

**잔존 이슈**:
- `is_round_number` 0%: 파이프라인에 `base.round(0)` float tolerance 적용 완료 (2026-03-26). DataSynth Rust 금액 생성기의 클램핑 로직 확인 필요 (범위 외)
- `is_suspense_account` 0%→해결 중: 하이브리드 방식 적용 완료 (2026-03-26) — 텍스트 키워드 OR `suspense_account_codes` GL prefix 매칭. DataSynth 적요에 ~30% 키워드 주입은 범위 외

```bash
# E2E 빠른 실행 (리포트 제외)
uv run pytest tests/test_feature/test_e2e_datasynth.py tests/test_feature/test_e2e_validation.py -v -k "not slow"

# 리포트 포함
uv run pytest tests/test_feature/test_e2e_datasynth.py -v -k slow
```

---

## 테스트 전략
- **각 피처 함수 단위 테스트:**
  - 토요일 날짜 → `is_weekend=True` 확인
  - 23시 전표 → `is_after_hours=True` 확인
  - 9,500,000원 → `is_near_threshold=True` 확인 (Level 1: 1천만 × 0.90 = 900만)
  - 15,000,000원 → `exceeds_threshold=True` 확인 (Level 1: 1천만 초과)
  - posting_date - document_date = 30일 → `days_backdated=30` 확인
  - gl_account '4100' → `is_revenue_account=True` 확인
  - 10,000,000원 → `is_round_number=True` 확인
  - 공휴일(설날 등) 전표 → `is_holiday=True` 확인
  - 적요 "." → `description_quality='poor'` 확인
  - 금액 -1500 → `first_digit=1` 확인 (abs 후 추출)
  - 금액 0.0053 → `first_digit=5` 확인 (non-zero digit)
- **edge case:** NaN 적요, 0원 금액, 시간 정보 없는 날짜, document_date 누락, 음수 금액, 소수점 금액
- **engine 통합 테스트:** 전체 18개 변수 생성 + 컬럼 존재 확인

## 구현 시 주의사항
- **days_backdated:** document_date가 없는 ERP 대비 → skip 또는 warning
- **is_period_end 판정:** 회계기간(fiscal year)이 1~12월이 아닌 경우 대비 → settings에서 설정 가능하게
- **is_near_threshold/exceeds_threshold:** threshold는 회사마다 다름 → settings.approval_thresholds (6단계 리스트)로 외부화
- **amount_zscore:** Phase 1부터 gl_account별 groupby Z-score 적용 (fallback: n≥30 계정별 → n<30 상위그룹 → n<10 NaN)
- **risk_keywords:** YAML에서 로드하여 하드코딩 방지 → 사용자 커스터마이징 지원
- **컬럼 의존성:** is_after_hours는 posting_date에 시간 정보가 있어야 작동 → 시간 없으면 skip 또는 warning
- **is_holiday:** settings.holidays YAML 날짜 목록 기반 판정 — 외부 패키지(holidays) 의존 없음
- **is_round_number:** settings.round_unit(기본 1,000,000) 기준 modulo 판정 — 가공전표/횡령 탐지
- **first_digit:** abs() → 0이 아닌 첫 번째 숫자 추출. 0원은 NaN 반환
- **description_quality:** is_description_missing + short_text 통합. missing/poor/normal 3단계 등급

---

## 부록: API 레퍼런스

<details>
<summary>클릭하여 상세 함수 시그니처 보기</summary>

### engine.py
```python
def generate_all_features(
    df: DataFrame,
    settings: AuditSettings
) -> DataFrame:
    """모든 파생변수를 순서대로 생성하여 DataFrame에 추가.

    1. time_features → is_weekend, is_after_hours, is_period_end, days_backdated, fiscal_period_mismatch, is_holiday
    2. amount_features → is_near_threshold, exceeds_threshold, amount_zscore, amount_magnitude, is_round_number
    3. pattern_features → is_manual_je, is_intercompany, is_revenue_account, first_digit, is_suspense_account
    4. text_features → has_risk_keyword, description_quality
    """
```

### time_features.py
```python
def add_is_weekend(df: DataFrame) -> DataFrame:
    """posting_date의 요일이 토/일이면 True. (L3-05 대응)
    감사 관점: 주말 전기는 정상 업무 외 처리로 부정 가능성."""

def add_is_after_hours(df: DataFrame, start: int = 22, end: int = 6) -> DataFrame:
    """posting_date의 시간이 22~06시이면 True. (L3-06 대응)
    감사 관점: 심야 전기는 승인 우회 가능성."""

def add_is_period_end(df: DataFrame, days: int = 5) -> DataFrame:
    """posting_date가 월말/분기말/연말 n일 이내이면 True. (L3-04 대응)
    감사 관점: 기말 집중 전표는 실적 조정 가능성."""

def add_days_backdated(df: DataFrame) -> DataFrame:
    """posting_date - document_date 일수 차이. (L3-07 대응)
    감사 관점: 큰 양수 = 소급 전기, 통제 우회."""

def add_fiscal_period_mismatch(df: DataFrame) -> DataFrame:
    """fiscal_period ≠ month(posting_date)이면 True. (L1-08 대응)
    감사 관점: 기간 귀속 오류."""

def add_is_holiday(df: DataFrame, holidays: list[str]) -> DataFrame:
    """posting_date가 settings.holidays 목록에 포함되면 True. (L3-05 대응)
    감사 관점: 공휴일 전기는 비영업일 부정 가능성."""
```

### amount_features.py
```python
def add_is_near_threshold(
    df: DataFrame,
    threshold: float = 50_000_000,
    ratio: float = 0.90
) -> DataFrame:
    """금액이 승인 한도의 ratio% 이상이고 한도 미만이면 True. (L2-01 대응)
    감사 관점: 한도 직하 금액은 승인 우회 의도 가능성."""

def add_exceeds_threshold(
    df: DataFrame,
    threshold: float = 50_000_000
) -> DataFrame:
    """금액이 승인 한도 초과이면 True. (L1-04 대응)
    감사 관점: 한도 초과 전표의 승인 절차 확인 필요."""

def add_amount_zscore(df: DataFrame, group_col: str = "gl_account") -> DataFrame:
    """gl_account별 groupby Z-score. > 3이면 이상 고액 후보. (L4-03 대응)
    fallback: n≥30 계정별 → n<30 상위그룹(자산/부채/수익/비용) → n<10 NaN.
    감사 관점: 통계적 이상치."""

def add_amount_magnitude(df: DataFrame) -> DataFrame:
    """금액의 자릿수(log10)를 피처로 추가. (ML용)"""

def add_is_round_number(df: DataFrame, unit: int = 1_000_000) -> DataFrame:
    """금액이 unit 단위로 딱 떨어지면 True. (L2-02 대응)
    감사 관점: round 금액은 가공전표/횡령 가능성."""
```

### pattern_features.py
```python
def add_is_manual_je(df: DataFrame, manual_codes: list[str]) -> DataFrame:
    """source 컬럼이 수기 전표 코드와 매칭되면 True. (L3-02 대응)
    감사 관점: 수기 전표는 자동화 통제 우회. codes는 audit_rules.yaml에서 주입."""

def add_is_intercompany(df: DataFrame, identifiers: list[str]) -> DataFrame:
    """gl_account에서 IC 전용 계정 prefix 매칭. (L3-03 대응)
    감사 관점: 관계사 거래는 순환거래·이전가격 위험. identifiers는 GL prefix 목록."""

def add_is_revenue_account(df: DataFrame, prefixes: list[str]) -> DataFrame:
    """gl_account가 매출 계정 prefix에 해당하면 True. (L4-01 대응)
    감사 관점: 매출 이상 변동 탐지의 기준. audit_rules.yaml에서 주입."""

def add_first_digit(df: DataFrame) -> DataFrame:
    """금액의 첫 유효숫자(1~9) 추출. str.extract(r"([1-9])") 사용. (L4-02 대응)
    전처리: abs() → str → regex. 0원 → NaN. 과학표기법/소수 안전."""

def add_is_suspense_account(df: DataFrame, keywords: list[str]) -> DataFrame:
    """line_text/header_text에서 가계정·미결산 키워드 매칭. (L2-04/L3-08 대응)
    감사 관점: 가수금/가지급/미결산 장기 미정리 시 부정 은폐 수단.
    keywords는 정규식 지원, audit_rules.yaml에서 주입."""
```

### text_features.py
```python
def add_has_risk_keyword(
    df: DataFrame,
    keywords: dict[str, list[str]]  # risk_keywords.yaml
) -> DataFrame:
    """적요(description)에 위험 키워드가 포함되면 risk_level 반환. (L3-08 대응)
    감사 관점: '상품권', '가계정' 등은 자금 유용 가능성."""

def add_description_quality(df: DataFrame, min_length: int = 3) -> DataFrame:
    """적요 품질 등급 반환: missing(NaN/빈값), poor(1~2글자), normal(3글자+).
    감사 관점: 적요 누락·성의없는 기재는 거래 실질 은폐 가능성."""
```

</details>

---

## Phase 2/3 확장 로드맵

Phase 1a에서 구현한 18개 파생변수를 토대로, Phase 2/3에서 기존 피처를 개선하고 새 피처를 추가한다.
이 섹션은 **미래 LLM/개발자가 Phase 2/3 작업에 진입할 때 맥락을 빠르게 파악**하기 위한 종합 가이드.

---

### A. 기존 피처 개선 (Phase 2)

Phase 1a에서 MVP 타협한 항목들. 각 모듈의 설계 결정 테이블에 흩어진 "Phase 2 개선" 메모를 한 곳에 모음.

| 모듈              | 대상                       | 현재 (Phase 1a)                                | 개선 (Phase 2)                                               |
|:------------------|:---------------------------|:-----------------------------------------------|:-------------------------------------------------------------|
| amount_features   | `amount_zscore` fallback   | n<30 그룹 → 전체 데이터 mean/std 사용          | CoA 상위그룹(자산/부채/수익/비용)별 fallback으로 왜곡 최소화 |
| amount_features   | `is_round_number` 외화     | float % 연산 (정수값 전제)                     | 외화 소수점 → `round()` 전처리 후 판정                       |
| pattern_features  | `is_suspense_account` 대상 | `_SUSPENSE_TEXT_COLS = [line_text, header_text]` | `gl_account_name` 컬럼 추가 (상수에 한 줄 추가)              |
| text_features     | `description_quality` 노이즈 | `_is_noise_pattern()` 규칙 기반                 | Entropy + 어휘 다양성 + kiwipiepy 형태소 분석 (아래 상세)    |

#### `description_quality` 진화 로드맵 (Length → Entropy & Pattern)

Phase 1a의 `description_quality`는 `len() ≤ 2 → poor` + `_is_noise_pattern()` 규칙 기반.
Phase 2에서 텍스트의 **정보량(Entropy)과 패턴**을 수학적으로 분석하여 정밀도를 높인다.

**Phase 1a (현재)**:
```
missing: NaN/빈문자열
poor:    len(strip()) ≤ 2 또는 _is_noise_pattern() (자음만/특수문자만/동일문자 반복)
normal:  3글자 이상
```

**Phase 2 (개선)**:
```
1단계 — 반복/무의미 패턴 강화:
  - 정규식으로 자음·모음 단독("ㅋㅋㅋ", "ㅇㅇ"), 특수문자 도배("...", "---"), 동일문자 반복("비품비품비품") 정밀 탐지
  - Phase 1a의 _is_noise_pattern()을 확장 (현재 3가지 → 추가 패턴)

2단계 — 어휘 다양성 (Lexical Diversity):
  - 정상 적요는 2개+ 형태소로 구성 (예: "3월 / 식대")
  - 고유 토큰 수 / 전체 토큰 수 = TTR(Type-Token Ratio)
  - TTR < threshold → poor 판정
  - 파이썬 내장 split()만으로 MVP 가능, Phase 3에서 kiwipiepy 형태소 분석으로 정밀화

3단계 — 정보 엔트로피 (Shannon Entropy):
  - 문자 단위 정보 엔트로피: H = -Σ p(c)·log2(p(c))
  - "aaaa" → H≈0 (극저), "3월 식대 외근" → H≈3.5 (정상)
  - 극저 엔트로피 = 의미 없는 반복/패딩 → poor 판정
```

**등급 체계 (Phase 2 확장)**:
```
missing:  NaN/빈문자열
poor:     len ≤ 2 OR noise_pattern OR TTR < 0.3 OR entropy < 1.0
normal:   3글자+ AND 패턴 통과
good:     (Phase 3) LLM 실질 평가 — 아래 상세
```

**Phase 3 "good" 등급 — LLM 기반 적요 실질 평가**:

Phase 2까지는 kiwipiepy 형태소 분석(명사 2개+ 포함)으로 `good` 후보를 선별한다.
Phase 3에서는 LLM이 **"제3자(감사인)가 거래 실질을 파악할 수 있는가"** 관점에서 최종 등급을 판정한다.

```
평가 기준: 육하원칙(5W1H) 기반 실질 정보 포함 여부
  - Who:  거래 상대방 식별 가능 (예: "○○전자")
  - What: 거래 대상/내용 명시 (예: "서버 호스팅비")
  - When: 귀속 시점 식별 가능 (예: "3월분")
  - Why:  거래 사유/목적 추론 가능

판정 흐름:
  1. Phase 2 형태소 필터 통과 (명사 2개+, TTR ≥ 0.3)
  2. LLM 프롬프트: "이 적요만 보고 제3자가 거래 실질을 파악할 수 있는가?"
  3. LLM 응답 → good / normal 재분류
     - 5W1H 중 2개+ 충족 → good
     - 미충족 → normal 유지

호출 최적화:
  - Phase 2 필터 통과 건만 LLM에 전달 (전체 대비 ~10~20%)
  - 배치 프롬프트: 한 번에 50건씩 묶어 호출 → API 오버헤드 최소화
```

---

### B. 새 피처 추가 — Phase 2 (`add_semantic_similarity`)

**Stub 위치**: `src/feature/text_features.py` (no-op + logger.info)
**호출 경로**: `add_all_text_features()` → 내부에서 호출 (현재 no-op)

**목적**: 같은 gl_account 내에서 적요(description)가 이질적인 전표 탐지

```
입력: combined_text (line_text + header_text), gl_account (그룹화 키)
출력: semantic_similarity (float, 0~1) — 그룹 내 코사인 유사도
```

**알고리즘**:
1. kiwipiepy 형태소 분석 → 명사/동사 토큰화
2. TF-IDF 벡터화 (sklearn TfidfVectorizer) → gl_account별 sparse matrix
3. 각 전표 벡터 → 그룹 중심 벡터와 코사인 유사도 계산
4. similarity < 0.3 → 이상 플래그

**의존성**: `kiwipiepy` (dependency-groups: nlp)

**edge case**:
- gl_account별 n<10: 스킵 (신뢰도 부족)
- 대량 전표(100만건): 배치 처리 + sparse matrix 활용

**감사 관점**: 같은 계정인데 적요 패턴 급변 → 계정 오분류·위장거래 의심

**Phase 2 추가 활용 — 은어/동의어 임베딩 매칭**:
`add_semantic_similarity`의 벡터화 인프라를 활용해 **키워드 동의어 탐지**도 수행.
Phase 1a의 `is_suspense_account`, `has_risk_keyword`는 정확한 키워드/정규식에만 반응하므로,
의도적으로 우회하는 변형 표현을 못 잡음.

```
현재 한계: audit_rules.yaml에 "상품권"만 등록 → "기프트카드", "백화점티켓"은 미탐지
Phase 2 보완: 임베딩 벡터 유사도로 "상품권과 85% 유사한 의미" → 자동 탐지
```

**구현 방향**:
1. risk_keywords.yaml의 키워드 목록 → kiwipiepy + TF-IDF (또는 sentence embedding) 벡터화
2. 전표 적요 → 동일 벡터 공간에 투영
3. 코사인 유사도 > threshold → "등록된 키워드의 의미적 변형" 플래그
- 예: "상품권" ↔ "기프트카드" (유사도 0.85), "가수금" ↔ "대표이사_개인대체" (유사도 0.72)

---

### C. 새 피처 추가 — Phase 3 (`add_semantic_anomaly`)

**Stub 위치**: `src/feature/text_features.py` (no-op + logger.info)
**호출 경로**: `add_all_text_features()` → 내부에서 호출 (현재 no-op)

**목적**: Ollama(Qwen3-8B) LLM의 문맥 기반 이상 탐지

```
입력: combined_text, gl_account, debit/credit_amount, posting_date
출력: semantic_anomaly (bool), semantic_anomaly_reason (str) — LLM 판단 이유
```

**구현 전략**:
- **선별 투입**: 전체 전표가 아님 — Phase 1~2에서 플래그된 고위험 전표만 LLM 통과
- **프롬프트**: 계정과목 + 금액 + 거래일 + 적요 → "문맥상 부자연스러운가?" 판정
- **VRAM 관리**: Qwen3-8B Q4_K_M 단독 ~5GB (RTX 3070 Ti 8GB — 여유)
- **Fail-safe**: Ollama 미실행 시 skip + warning (graceful degradation)

**감사 관점**: 숫자·키워드로 못 잡는 문맥 불일치 탐지
- 예1: "소프트웨어구입비" 계정 + "스타벅스 리저브 10잔" 적요 → 계정-적요 의미 충돌
- 예2: "ZZ_Temp", "대표이사_개인대체" 같은 교묘한 가계정명 → LLM이 계정 성격을 추론하여 가계정 분류

**`is_suspense_account` 고도화 연계**:
Phase 1a의 `is_suspense_account`는 키워드 매칭 전용이므로, 의도적 우회(은어·변형)에 취약.
Phase 3에서 LLM이 계정명의 **의미 자체**를 읽어 "이건 사실상 가계정이다"라고 추론하는 보완 레이어 추가.
```
Phase 1a: "가수금" 키워드 → 탐지 ✅ / "ZZ_Temp" → 미탐지 ❌
Phase 3:  LLM("ZZ_Temp는 임시계정의 관행적 명명 패턴") → 탐지 ✅
```

---

### D. Phase 1c Data Flywheel (audit_rules.yaml ↔ UI ↔ Profile)

Phase 1c 대시보드에서 `config/audit_rules.yaml`의 업무 룰을 UI로 편집하고, 고객사 프로파일에 저장하는 순환 구조.

```
[config/audit_rules.yaml] ← 기본값 (K-IFRS 표준)
        ↓ 로드
[Streamlit UI] — 감사인이 고객사별 커스터마이징
  ├── manual_source_codes: SAP→SA, Oracle→Manual, ...
  ├── revenue_account_prefixes: 4 (+ 필요 시 9 추가)
  ├── intercompany_identifiers: IC 전용 GL 계정 prefix 입력
  └── suspense_keywords: 고객사 특수 키워드 추가
        ↓ 저장
[data/profiles/customer_A.json] ← mapping_profile + audit_rules 통합
        ↓ 다음 감사 시 자동 로드
[config/audit_rules.yaml 대신 프로파일 우선 적용]
```

**UX 원칙** ([ux-flow.md → 3가지 원칙](ux-flow.md#3가지-ux-디자인-원칙)):
- **스마트 디폴트**: 기본값만으로 분석 가능 (intercompany_identifiers는 IC GL prefix)
- **점진적 공개**: 기본 모드(디폴트 사용) / 전문가 모드(직접 편집)
- **프로파일 재사용**: 결정 피로 해소 — "이번 설정은 내년 감사에 자동 적용"

> 이 섹션은 [ux-flow.md → UX 2단계](ux-flow.md#ux-2단계-감사-룰-세팅--파생변수-생성-feature--엔진-구현-완료-ui-예정)의 상세 구현입니다.

---

### E. Phase 2 ML Pipeline과 피처의 관계

Phase 2에서 feature 모듈이 생성한 18+1개 피처가 ML Pipeline의 입력이 된다.

```
[18개 파생변수 + semantic_similarity]
        ↓
sklearn ColumnTransformer
  ├── 수치형: SimpleImputer(median) → StandardScaler (VAE/IF용, XGBoost는 불필요)
  ├── 범주형: SimpleImputer(most_frequent) → TargetEncoder (gl_account 4000+ 대응)
  └── 시간형: forward fill
        ↓
GridSearchCV로 최적 모델/파라미터 동시 선택
  ├── XGBClassifier      — Tier 2 지도학습 (Phase 1 룰 결과 = pseudo-label)
  ├── VAEDetector         — 비지도 이상탐지 (reconstruction error)
  └── IsolationForest     — 비지도 이상탐지 (앙상블)
```

**핵심 결정**:
- gl_account 고카디널리티(4000+) → OneHotEncoder 대신 **TargetEncoder** (cross-fitting)
- Phase 1 룰 탐지 결과를 **pseudo-label**로 활용 → 별도 라벨링 비용 없음
- VAE와 LLM(Phase 3) **순차 실행** — 동시 VRAM ~7GB, RTX 3070 Ti에서 위험

---

### F. 관련 참조 문서

| 문서                                                               | 관련 내용                                  |
|:-------------------------------------------------------------------|:-------------------------------------------|
| [03a-preprocessing.md](03a-preprocessing.md)                       | EDA 프로파일링, ML Pipeline 전처리 전략    |
| [DETECTION_RULES.md](../DETECTION_RULES.md)                        | 22→36→41개 유형 Tier 분류, 점수 체계       |
| [08-llm.md](08-llm.md)                                            | Ollama, Vanna Text-to-SQL, Insight 생성    |
| [ux-flow.md](ux-flow.md)                                          | UX 2단계, 스마트 디폴트, 프로파일 재사용   |
| [config/audit_rules.yaml](../../config/audit_rules.yaml)           | 감사 업무 룰 (Data Flywheel 시작점)        |

---

### G. 미해결 이슈 (발견 → 해결 교차 참조)

> 출처: [feature-test-summary.md](../../tests/test_feature/test-results/feature-test-summary.md), [e2e-datasynth.md](../../tests/test_feature/test-results/e2e-datasynth.md), [e2e-sap-merged.md](../../tests/test_feature/test-results/e2e-sap-merged.md)

| Phase | 모듈           | 문제                                  | 현상                                            | 해결 위치                                                                      |
|:------|:---------------|:--------------------------------------|:------------------------------------------------|:-------------------------------------------------------------------------------|
| ~~2~~ | ~~engine~~     | ~~FeatureResult 상세 로그~~           | ~~경고/스킵 사유 미기록~~                       | ✅ **해결됨** — `warnings` 필드 추가 완료                                      |
| ~~1b~~ | ~~engine~~         | ~~rules 전달 형식 불일치~~            | ~~`get_audit_rules()` 중첩 dict 전달 시 pattern 피처 전부 False~~ | ✅ **해결됨** — `engine.py:117-119` 자동 언래핑 추가. [발견](../../tests/test_detection/test-results/e2e-detection-datasynth.md) |
| ~~1c~~ | ~~time_features~~ | ~~is_after_hours 날짜 경계~~       | ✅ **버그 아님** — `dt.hour` 기반 자정 걸침 정확 처리 확인 | —                                                                             |
| 1c    | time_features  | fiscal_period_mismatch NaN (SAP)      | sap-merged에서 전체 NaN                         | [07-dashboard §미해결과제](07-dashboard.md#phase-1a에서-넘어온-미해결-과제-ux-1단계-잔여) |
| 2     | amount_features| Z-score 소그룹 fallback 왜곡          | n<30 그룹이 전체 분포에 의존                    | [05-detection](05-detection.md) — Phase 2 ML 파이프라인에서 CoA 상위그룹 fallback |
| 2     | amount_features| 외화 소수점 is_round_number           | float % 연산 정수값 전제                        | 자체 수정 — Decimal 연산 또는 통화별 소수점 설정                               |
| ~~2~~ | ~~pattern_features~~| ~~is_suspense_account 대상 컬럼 제한~~ | ~~line_text + header_text만 (gl_account_name 미포함)~~ | ✅ **해결됨** — `_SUSPENSE_TEXT_COLS`에 `gl_account_name` 추가 완료 (Phase 2 스키마 확장 시 자동 반영) |
| 2     | text_features  | description_quality 규칙 기반 한계    | 길이+패턴 정밀도 부족                           | 자체 수정 — [03a-preprocessing](03a-preprocessing.md) Entropy + TTR 도입       |
| 2     | engine         | 순차 실행 성능                        | 대용량 시 병목                                  | 자체 수정 — concurrent.futures 병렬 실행 옵션                                  |
| 2~3   | pattern + text | 은어/동의어 미탐지                    | 키워드 정확 매칭만 지원                         | [08-llm §미해결과제](08-llm.md#phase-1a에서-넘어온-미해결-과제-ux-1단계-잔여) — NLP 임베딩 유사도 |
| 2~3   | text_features  | semantic stub 미구현                  | no-op 상태                                      | [08-llm §미해결과제](08-llm.md#phase-1a에서-넘어온-미해결-과제-ux-1단계-잔여) — Ollama 임베딩 연동 |

---

## 신규 파생변수 후보 (DETECTION_RULES.md §3.3 기반)

> DataSynth 확장 컬럼 및 기존 컬럼 조합에서 생성하는 추가 피처.

### 시간대 분석

| 피처명                    | 산출 로직                                         | 탐지 활용          |
|--------------------------|--------------------------------------------------|-------------------|
| `is_late_night`          | posting_date 시간 22:00~06:00                     | 심야 전표 (L3-06 확장) |
| `is_overtime`            | posting_date 시간 18:30~22:00                     | 야근 구간 구분      |
| `user_night_ratio`       | created_by별 심야 전표 비율                        | 입력자 집중 분석    |
| `user_night_zscore`      | user_night_ratio의 Z-score (전체 사용자 대비)       | 3σ 이상치 탐지     |

### 역분개 분석

| 피처명                    | 산출 로직                                         | 탐지 활용          |
|--------------------------|--------------------------------------------------|-------------------|
| `is_reversal_pair`       | 동일 gl_account + 금액 + 반대방향 ±1일 매칭         | 1:1 역분개         |
| `rolling_net_7d`         | gl_account × created_by 7일 윈도우 순액             | N:M 분할 역분개     |
| `is_correcting_entry`    | source='manual' + line_text 키워드("수정","정정")    | 수정 전표 구분      |

### Top-side JE 점수 (후처리 복합 점수)

> `topside_score`는 피처 엔진이 아닌 `score_aggregator.py::_compute_topside_score()`에서 산출.
> 기존 피처(`is_manual_je`)와 기존 룰 플래그(L3-04, L1-05, L1-07, L1-03, L4-04, L4-03, L3-08)를 조합.

| 컬럼명             | 산출 위치                          | 산출 로직                                                     |
|--------------------|------------------------------------|--------------------------------------------------------------|
| `topside_score`    | `score_aggregator.py` (후처리)     | 게이트키퍼(수기 필수) + 5개 가점(기말/승인/계정/고액/적요) / 5.0 |

### 승인 분석 (DataSynth v1.2.0: approved_by, approval_date 생성 완료)

> **DataSynth 변경 반영** (2026-03-25):
> - `approval_timestamp` → `approval_date` (date, 시분초 없음)
> - `approval_level` → DuckDB 파생 컬럼 (loader.py CASE WHEN, 전결규정 6단계)

| 피처명                    | 산출 로직                                         | 탐지 활용          |
|--------------------------|--------------------------------------------------|-------------------|
| `approval_delay_days`    | approval_date - posting_date (일수)                | 승인 지연          |
| `is_level_skip`          | 금액 대비 required_approval_level 부족 여부 (DuckDB 파생) | 레벨 건너뜀  |
| `approval_speed_ratio`   | 입력-승인 일수 차이 / 평균                          | 부실 검토 의심      |
