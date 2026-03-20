# Type Caster 테스트 결과

> 실행일: 2026-03-20 | **44 passed** in 0.24s

## 1. 테스트 요약

| 클래스               | 테스트 수 | 상태 |
|:---------------------|:---------:|:----:|
| TestCastAmount       |     9     |  ✅  |
| TestCastDate         |     8     |  ✅  |
| TestCastInt          |     4     |  ✅  |
| TestCastStr          |     5     |  ✅  |
| TestCastBool         |     3     |  ✅  |
| TestUnifyDebitCredit |     4     |  ✅  |
| TestCastDataframe    |     6     |  ✅  |
| TestNullDemote (v2)  |     5     |  ✅  |
| **합계**             |  **44**   |  ✅  |

---

## 2. v1 문제점

**캐스팅 후 결측률 경고가 단일 기준** → 오매핑과 유령 컬럼을 구분 못함.

| 현상                      | 원인                     | 영향                         |
|:--------------------------|:-------------------------|:-----------------------------|
| gl_account 결측률 100%    | HKONT(익명화 str)→int 캐스팅 | 오매핑인데 단순 warning만    |
| SAP 빈 컬럼 60개 중 다수  | 원본부터 100% NaN        | warnings 리스트 노이즈       |

---

## 3. 개선방안

**Null 3단계 분기** — `CastingResult`에 `high_null_columns`, `empty_columns` 추가:

```
원본 100% NaN → empty_columns  (유령 컬럼 — 경고 없이 조용히 분리)
캐스팅 후 >90% → high_null_columns (오매핑 의심 — 명시적 경고)
캐스팅 후 >10% → warnings     (일반 경고)
```

---

## 4. v2 개선 결과

| 시나리오              | v1                  | v2                                 |
|:----------------------|:--------------------|:-----------------------------------|
| SAP 빈 컬럼          | warning 노이즈      | empty_columns 분리 (경고 없음)     |
| HKONT→gl_account 100% | "결측률 100%" 경고  | "오매핑 의심" 명시 + high_null 분류 |
| 정상 캐스팅          | 변화 없음           | 변화 없음 (하위 호환)             |

---

## 5. 남은 문제점

없음 — 캐스팅 모듈 단독으로는 모든 케이스 해결. 오매핑 자체의 방지는 column_mapper 책임.

---

## 6. 세부 테스트 케이스

### TestCastAmount (9)
- 쉼표, 원화(₩), 달러($), 괄호음수, 빈값/대시, None/NaN, 0, 일반숫자, 이미 numeric

### TestCastDate (8)
- ISO, 슬래시, 점, 8자리, 한국어, Excel serial, 빈값, 이미 datetime

### TestCastInt (4)
- 문자열→Int64, 소수점→반올림, NaN, 이미 int

### TestCastStr (5)
- int→str, float→str, 이미 str, NaN→pd.NA 보존, Int64→str

### TestCastBool (3)
- true 변형(true/1/yes), false 변형, NaN

### TestUnifyDebitCredit (4)
- Case A(이미 분리), Case B(dc_indicator), Case C(부호), amount 없음

### TestCastDataframe (6)
- 전체 캐스팅, Parquet 스킵, 필수 실패, 결측률 경고, 빈 DF, amount→debit/credit

### TestNullDemote (5) — v2

| #  | 테스트명                       | 시나리오                       | 검증 포인트                     |
|:---|:-------------------------------|:-------------------------------|:-------------------------------|
| 40 | test_empty_column_separated    | 원본 100% NaN                  | empty_columns, warning 없음    |
| 41 | test_high_null_detected        | 캐스팅 후 100% NaN (원본 str)  | high_null + "오매핑 의심"      |
| 42 | test_normal_not_flagged        | 정상 캐스팅                    | 둘 다 비어있음                 |
| 43 | test_demote_threshold_boundary | 90% 경계 (90%=통과, 91%=감지)  | threshold 정확 동작            |
| 44 | test_empty_vs_high_null        | 유령 vs 오매핑 구분            | 각각 올바른 리스트 분류        |

---

## 7. 소스 바로가기

| 구현 코드    | [type_caster.py](../../../src/ingest/type_caster.py) |
|:------------|:------------|
| 테스트 코드  | [test_type_caster.py](../test_type_caster.py) |

```bash
uv run pytest tests/test_ingest/test_type_caster.py -v
```
