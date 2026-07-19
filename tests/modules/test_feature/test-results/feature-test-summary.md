# Feature Engine 테스트 결과 통합 리포트

> 실행일: 2026-03-26 | 총 195 passed, 0 failed (L4-05 time_zone_category 추가)

---

## 1. 전체 요약

```
모듈              테스트 수   결과     소요시간
─────────────────────────────────────────────
time_features          49   ✅ PASS   0.46s   ← +1 (time_zone_category)
amount_features        29   ✅ PASS   0.17s   ← +2 (다단계 threshold)
pattern_features       42   ✅ PASS   0.19s
text_features          38   ✅ PASS   0.18s
engine (오케스트레이터) 14   ✅ PASS   0.64s
회귀 테스트 (전체)    172   ✅ PASS   0.96s
settings 테스트          7   ✅ PASS   0.01s
─────────────────────────────────────────────
합계                  195   ALL PASS
```

---

## 2. E2E 테스트 (실제 데이터)

### DataSynth v1.2.0 (풀 스펙)

```
입력: 1,106,356행 | 피처: 19/19 생성 | 소요: ~9s
```

| 카테고리 | 소요(s) | 피처 수 | 상태 |
|:---------|--------:|--------:|:----:|
| time     |   1.500 |       7 | 성공 |
| amount   |   0.297 |       5 | 성공 |
| pattern  |   3.937 |       5 | 성공 |
| text     |   3.110 |       2 | 성공 |

### SAP-Merged (Graceful Degradation)

```
입력: 331,934행 | 피처: 13/18 생성 | 소요: 0.89s
미매핑: credit_amount, debit_amount → amount 카테고리 5개 스킵
```

| 카테고리 | 소요(s) | 피처 수 | 상태 |
|:---------|--------:|--------:|:----:|
| time     |   0.219 |       6 | 성공 |
| amount   |   0.000 |       5 | 스킵 |
| pattern  |   0.266 |       5 | 성공 |
| text     |   0.406 |       2 | 성공 |

> amount 스킵은 필수 컬럼(debit/credit_amount) 미매핑에 의한 의도된 동작. Phase 1c 매핑 UI에서 해결 예정.

---

## 3. 18개 피처 현황

```
피처                     카테고리   dtype     DataSynth v1.2.0  SAP-Merged
────────────────────────────────────────────────────────────────────────────
is_weekend               time      bool      True 10.0%        True 19.6%
is_after_hours           time      bool      True 1.1%         all-False(*)
is_period_end            time      bool      True 52.6%        True 36.7%
days_backdated           time      Int64     [-32, 32]         [-730, 365]
fiscal_period_mismatch   time      boolean   2값               all-NaN(**)
is_holiday               time      bool      True 5.6%         True 2.8%
is_near_threshold        amount    bool      True 0.4%         — 스킵
exceeds_threshold        amount    bool      True 0.0%         — 스킵
amount_zscore            amount    float64   [-0.98, 63.90]    — 스킵
amount_magnitude         amount    float64   [0.0, 10.90]      — 스킵
is_round_number          amount    bool      all-False(*)      — 스킵
is_manual_je             pattern   bool      True 25.8%        all-False(*)
is_intercompany          pattern   bool      True 1.3%         all-False(*)
is_revenue_account       pattern   bool      True 20.2%        True 7.1%
first_digit              pattern   Int64     [1-9]             all-NaN
is_suspense_account      pattern   bool      all-False(*)      all-False(*)
description_quality      text      object    2 levels          2 levels
has_risk_keyword         text      object    1 level           all-low
```

(*) 데이터 특성 — 코드 정상, 해당 패턴이 데이터에 부재
(**) 조사 필요 — 입력 데이터 또는 로직 확인 필요

---

## 4. Edge Case 커버리지

### time_features (49 cases)

| edge case                    | 처리 방식                                |
|:-----------------------------|:-----------------------------------------|
| 시간 정보 없는 날짜          | `_has_time_info()` → 전체 False + warning |
| NaT (결측 날짜)              | fillna(False) 또는 NaN 반환              |
| 윤년 2/29                    | 월말 당일 → True 정상 처리               |
| margin=0                     | 월말 당일만 True, 익월 초 제외           |
| start==end (구간 없음)       | 전체 False (무한루프 방지)               |
| document_date 컬럼 부재      | 전체 NaN + warning                       |
| 비표준 회계연도 (4월 결산)   | modulo 연산으로 범용 대응                |

### amount_features (29 cases)

| edge case                    | 처리 방식                                |
|:-----------------------------|:-----------------------------------------|
| debit/credit 모두 NaN        | fillna(0) → base_amount=0               |
| 다단계 threshold 경계값      | 각 레벨별 near/exceeds gap 없음 보장     |
| 레벨 사이 금액               | 어떤 near 구간에도 미해당 → False        |
| std==0 (모든 금액 동일)      | 0.0 반환 (ZeroDivisionError 방지)       |
| 전체 n<10                    | Z-score 전부 NaN                        |
| gl_account 컬럼 누락         | NaN + warning (에러 미발생)             |
| 0원 금액                     | is_round_number=False                    |

### pattern_features (42 cases)

| edge case                    | 처리 방식                                |
|:-----------------------------|:-----------------------------------------|
| source NaN / 컬럼 부재       | 전부 False (오탐 방지)                   |
| manual_codes 빈 리스트       | 전부 False                               |
| 음수 금액                    | abs() 후 첫 자리 추출                    |
| 소수 0.005                   | 첫 non-zero digit=5                      |
| 과학표기법 1.5e-05           | str.extract로 안전 추출                  |
| 잘못된 정규식 키워드         | re.escape() 폴백 + warning              |

### text_features (38 cases)

| edge case                    | 처리 방식                                |
|:-----------------------------|:-----------------------------------------|
| line+header 모두 None        | NaN → missing 판정                       |
| 은폐 패턴 ("상 품 권")      | _clean_for_keyword 정제 후 매칭          |
| 자음만/특수문자만/동일문자   | _is_noise_pattern → poor                 |
| line poor + header 구제      | concat 후 normal로 승격                  |
| 텍스트 컬럼 자체 부재        | 전체 NaN → missing/low                   |

---

## 5. 엔진 오케스트레이터 (14 cases)

| 검증 항목        | 설명                                            |
|:-----------------|:------------------------------------------------|
| 풀 스펙 실행     | 18개 컬럼 생성, dtype 검증, 메타데이터 정합성   |
| 선택적 카테고리  | time_only→6개, amount+pattern→10개, 역순→고정순 |
| 멱등성           | 2회 실행 시 컬럼 수 동일, added_columns=18 유지 |
| Graceful 처리    | 최소 df, 0행 df, 누락 컬럼 → 에러 없이 완료    |
| Settings 주입    | threshold/manual_codes 커스텀 반영, auto_load   |

설계 결정:
- **In-place 수정**: df.copy() 안함 → 메모리 최적화 우선
- **고정 실행 순서**: time → amount → pattern → text (입력 순서 무관)
- **execution_times**: 카테고리별 소요 시간 dict → Phase 2/3 병목 추적 대비

---

## 6. 해결 완료 이력

| 문제                                | 원인                                           | 해결 내용                                              | 해결 위치                     |
|:------------------------------------|:-----------------------------------------------|:-------------------------------------------------------|:------------------------------|
| FeatureResult에 경고/스킵 사유 누락 | 카테고리 스킵 시 사유를 확인할 수 없었음       | `warnings: dict[str, list[str]]` 필드 추가, `_run_category`에서 수집 | `src/feature/engine.py`       |
| is_suspense_account 대상 컬럼 제한  | `gl_account_name` 컬럼이 검색 대상에서 빠져 있었음 | `_SUSPENSE_TEXT_COLS`에 `gl_account_name` 추가          | `src/feature/pattern_features.py` |
| is_after_hours 날짜 경계 오판 의심  | 자정 걸침 시 오동작 우려                       | 버그 아님 확인 — `dt.hour` 기반으로 23→True, 0→True 정상 동작 | `src/feature/time_features.py`    |

---

## 7. 남은 문제점

| 문제                            | 현상                                     | 해결 시점  |
|:--------------------------------|:-----------------------------------------|:-----------|
| Z-score 소그룹 fallback 왜곡   | n<30 그룹이 전체 분포에 의존 → 왜곡 가능 | Phase 2    |
| 외화 소수점 is_round_number    | float % 연산 (정수값 전제)               | Phase 2    |
| 은어/동의어 미탐지             | 정확한 키워드/정규식에만 반응            | Phase 2~3  |
| description_quality 규칙 한계  | 길이+패턴만으로 정밀도 부족              | Phase 2    |
| semantic stub 미구현           | no-op + logger.info                      | Phase 2~3  |
| SAP fiscal_period_mismatch     | 전체 NaN — 입력 데이터 확인 필요         | 조사 필요  |

---

## 8. 실행 명령어

```bash
# 전체 feature 테스트
uv run pytest tests/test_feature/ -v

# 개별 모듈
uv run pytest tests/test_feature/test_time_features.py -v
uv run pytest tests/test_feature/test_amount_features.py -v
uv run pytest tests/test_feature/test_pattern_features.py -v
uv run pytest tests/test_feature/test_text_features.py -v
uv run pytest tests/test_feature/test_engine.py -v
```
