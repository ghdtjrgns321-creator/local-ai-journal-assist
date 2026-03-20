# amount_features 단위 테스트 결과

> 실행일: 2026-03-20 | 27 passed, 0 failed | 0.17s

## 1. 테스트 요약

| 테스트 클래스              | 케이스 수 | 결과 | 검증 대상                         |
|:---------------------------|:---------:|:----:|:----------------------------------|
| TestBaseAmount             | 5         | ✅   | base_amount 산출: debit/credit 중 큰 값, NaN 방어 |
| TestIsNearThreshold        | 3         | ✅   | B02: 승인한도 직하 판정 (경계값 정확히/미만/한도 정확히) |
| TestExceedsThreshold       | 3         | ✅   | B03: 승인한도 초과 판정 + near/exceeds gap 없음 보장 |
| TestAmountZscore           | 5         | ✅   | C08: 그룹별 Z-score, 소그룹 fallback, std=0, n<10 NaN, gl_account 부재 |
| TestAmountMagnitude        | 3         | ✅   | log10 스케일: 백만원, 0원, NaN |
| TestIsRoundNumber          | 4         | ✅   | B04: 라운드넘버 판정, 0원 제외, NaN 방어 |
| TestAddAllAmountFeatures   | 4         | ✅   | 5개 컬럼 생성, base_amount 미포함, settings 커스텀, edge cases |

---

## 2. 발견된 문제점

없음. 모든 케이스 정상 통과.

---

## 3. 주요 edge case 커버리지

| edge case                       | 테스트                         | 처리 방식                          |
|:--------------------------------|:-------------------------------|:-----------------------------------|
| debit/credit 모두 NaN           | test_both_nan                  | fillna(0) → base_amount=0          |
| 한쪽만 NaN                      | test_one_nan                   | 유효값 사용                        |
| threshold 정확히 경계값         | test_at_threshold_is_false     | near=False, exceeds=True (gap 없음) |
| near/exceeds 영역 겹침 없음    | test_no_gap_with_near          | `ratio*t ≤ x < t` / `x ≥ t` 보장 |
| std==0 (모든 금액 동일)         | test_std_zero_returns_zero     | 0.0 반환 (ZeroDivisionError 방지)  |
| 전체 n<10                       | test_too_few_rows_returns_nan  | Z-score 전부 NaN                   |
| gl_account 컬럼 누락            | test_missing_gl_account        | NaN + warning (에러 미발생)        |
| 0원 금액                        | test_zero_excluded             | is_round_number=False              |

---

## 4. 남은 문제점

| 문제                                    | 현상                                          | 해결 시점  |
|:----------------------------------------|:----------------------------------------------|:-----------|
| Z-score 소그룹 fallback 왜곡            | n<30 그룹이 전체 분포에 의존 → 왜곡 가능      | Phase 2    |
| 외화 소수점 is_round_number             | float % 연산 (정수값 전제)                     | Phase 2    |

---

## 5. 실행 명령어

```bash
uv run pytest tests/test_feature/test_amount_features.py -v
```
